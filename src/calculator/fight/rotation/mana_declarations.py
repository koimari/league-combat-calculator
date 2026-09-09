"""What a build declares about mana before anything is walked."""

import math
from collections.abc import Callable, Mapping
from functools import partial
from typing import Any

from ... import item_effects, resource_ledger
from ...ability_atoms import ability_field, ability_payload
from ...interpreters import stat_derivation
from ...item_behavior import ResourceRestoreRule
from ..autos.swing_schedule import _restore_stream_attack_timestamps, _swings_at_rate
from ..config import declared_option_default
from ..empower_declaration import _empower_burst_attack_speed, _empower_hits
from ..results import CastPlan
from ..state import FightState
from .cast_schedule import _CAST_SCHEDULE_EPS


def _manaflow_hit_identity(
    key: str, accepted_ordinal: int, info: Mapping[str, Any]
) -> str | None:
    """Return a proven hit identity for an accepted cast, or None.

    Manaflow's wording triggers on affecting an enemy or ally with an
    ability.  In the fighter model a cast is a PROVEN eligible hit when its
    reviewed packet carries a champion-affecting marker: a damage part
    (``amount`` > 0 or an ``hp_scaled_damage`` closure), a crowd-control
    part, or an on-hit/empowered-auto/DoT application.  An accepted cast
    with none of those (a pure self-only receipt) fails closed with a
    ``missing_hit_identity`` denial instead of being treated as a hit.
    """
    parts = ability_field(info, "parts")
    for part in parts:
        if part.cc_kind is not None:
            return f"{key}:{accepted_ordinal + 1}"
        try:
            amount = float(part.amount or 0.0)
        except (TypeError, ValueError):
            amount = 0.0
        if amount > 0.0 or part.hp_scaled_damage is not None:
            return f"{key}:{accepted_ordinal + 1}"
    if any(
        info.get(marker)
        for marker in (
            "empowers_next_auto",
            "on_hit",
            "applies_dot_stack",
            "applies_item_on_hits",
        )
    ):
        return f"{key}:{accepted_ordinal + 1}"
    return None


def _manaflow_swing_rows(
    state: FightState,
    plan: CastPlan,
    manaflow: resource_ledger.ManaflowLedger | None,
) -> list[dict[str, Any]]:
    """The basic attacks that spend a Manaflow charge, in swing order.

    Empty unless the holder's cached clause names an on-hit trigger.  The
    schedule is the one ``_auto_restore_schedule`` resolves, so the two
    per-auto ledger walks ride the same swings; an empowered-burst swing
    carries its arming slot so a denied cast cannot spend a charge with a
    swing it never fired.
    """
    if manaflow is None or not manaflow.declaration.on_hit_charge:
        return []
    ordinary_times, swing_events = _auto_restore_schedule(state, plan)
    rows: list[dict[str, Any]] = [
        {"time": swing_time, "auto_index": index + 1, "arming_key": None}
        for index, swing_time in enumerate(ordinary_times)
    ]
    rows.extend(
        {
            "time": swing["time"],
            "auto_index": len(ordinary_times) + index + 1,
            "arming_key": swing["arming_key"],
            "arming_ordinal": swing["arming_ordinal"],
        }
        for index, swing in enumerate(swing_events)
        if swing["time"] <= state.fight_duration_seconds + _CAST_SCHEDULE_EPS
    )
    return rows


def _manaflow_ledger_for(
    state: FightState, owner: str
) -> resource_ledger.ManaflowLedger | None:
    """Build the build's Manaflow state, or None when no holder is equipped.

    The holder comes from the build — whichever of the five registered
    Manaflow items it holds — and every number, receipt and atom is that
    holder's own, read through the typed ``item_effects`` accessor.
    """
    holder = item_effects.manaflow_holder(state.items)
    if holder is None:
        return None
    options = state.item_options or {}
    unset = declared_option_default("item", holder, "manaflow_bonus_mana")
    authored = float(
        (options.get(holder) or {}).get("manaflow_bonus_mana", unset) or unset
    )
    declaration = resource_ledger.ManaflowDeclaration(
        **item_effects.manaflow_declaration(holder)
    )
    return resource_ledger.ManaflowLedger(
        declaration, owner=owner, authored_bonus_mana=authored
    )


def _enlighten_decl_for(
    state: FightState,
) -> resource_ledger.EnlightenDeclaration | None:
    """Return Lost Chapter's sourced Enlighten declaration, or None.

    The 20%-over-3-seconds restore is read off the holder's own
    ``ResourceRestoreRule``, which is what makes the catalog declaration the
    number's one home rather than a second statement of the three registry
    keys.  It is backed by the wiki branch and the client binary
    (ManaRestorePercent=0.2, RestorationDuration=3.0 in
    data/bin/items.bin.json 16.15.8024387); the atom hash is Lost Chapter's
    verified stat.mana catalog hash.
    """
    if not item_effects.has_item(state.items, "Lost Chapter"):
        return None
    slot = stat_derivation.sole_declared_derivation(
        ["Lost Chapter"], ResourceRestoreRule
    )
    if slot is None:
        raise ValueError(
            "Lost Chapter is equipped and declares no resource-restore rule, "
            "so Enlighten has no sourced schedule to run"
        )
    return resource_ledger.EnlightenDeclaration(
        restore_percent=slot.value("share_of_maximum"),
        duration_seconds=slot.value("duration"),
        ticks=int(slot.value("ticks")),
        source_url=str(item_effects.ITEM_INPUT_OPTIONS["Lost Chapter"]["source_url"]),
        source_revision_id=int(
            item_effects.ITEM_INPUT_OPTIONS["Lost Chapter"]["source_revision_id"]
        ),
        atom=("stat.mana", "05327ad078be2bde"),
    )


def _planned_burst_seconds(state: FightState, plan: CastPlan) -> float:
    """The fight's total planned burst-time budget (all arming casts)."""
    total = 0.0
    for key in state.cast_order:
        empower = (ability_payload(state.ability_damages, key)).get(
            "empowers_next_auto"
        )
        burst_as = _empower_burst_attack_speed(empower) if empower else 0.0
        if burst_as <= 0.0:
            continue
        hits = _empower_hits(empower)
        total += hits / burst_as * len(plan.times.get(key, ()))
    return total


def _return_denied_burst_budget(
    state: FightState,
    plan: CastPlan,
    auto_restore_rows: list[dict[str, Any]],
    denied_row: Mapping[str, Any],
    *,
    timeline: list[tuple[Any, ...]],
) -> None:
    """Return one denied burst cast's time to the ordinary restore budget.

    P1 Slice 12 (R1): the pre-admission schedule subtracted every planned
    burst cast's time from the ordinary count; a cast whose arming
    admission was DENIED never fires, so the fight's ordinary stream is
    uninterrupted and its restores must not shrink.  The first denied
    swing of a cast mints the returned ordinary rows at the current
    count's continuation (they ride their own scheduled times and heap
    order).
    """
    burst_seconds = float(denied_row.get("burst_seconds", 0.0))
    normal_rate = state.attack_speed * state.auto_attack_uptime
    if burst_seconds <= 0.0 or normal_rate <= 0.0:
        return
    planned_burst = _planned_burst_seconds(state, plan)
    ordinary_total = sum(1 for row in auto_restore_rows if row["kind"] == "ordinary")
    leftover = max(0.0, state.fight_duration_seconds - (planned_burst - burst_seconds))
    new_total = math.floor(normal_rate * leftover)
    delta = max(0, new_total - ordinary_total)
    if delta <= 0:
        return
    base_index = len(auto_restore_rows)
    for offset, swing_time in enumerate(
        _swings_at_rate(delta, normal_rate, ordinary_total / normal_rate)
    ):
        row_index = len(auto_restore_rows)
        auto_restore_rows.append(
            {
                "kind": "ordinary",
                "auto_index": base_index + offset + 1,
                "burst_seconds": 0.0,
            }
        )
        timeline.append((swing_time, 0, -4, row_index, "auto_restore", "", 0.0))


def _auto_restore_decl(
    state: FightState,
) -> tuple[str, dict[str, Any]] | None:
    """The single per-auto mana restore declaration, or None.

    A champion entry (Jayce's W passive) carries ``resource_restore_per_auto``
    as a typed dict ``{amount, source, atoms}``.  More than one declaring
    entry is not representable in this slice and raises (fail closed); the
    returned tuple names the declaring slot for the ledger detail rows.
    """
    declaring: list[tuple[str, dict[str, Any]]] = []
    for key, info in state.ability_damages.items():
        decl = info.get("resource_restore_per_auto")
        if decl is None:
            continue
        if not isinstance(decl, Mapping):
            raise ValueError(
                f"resource_restore_per_auto on slot {key!r} must be a mapping"
            )
        amount = decl.get("amount")
        source = decl.get("source")
        atoms = ability_field(decl, "atoms", form="resource_declaration")
        if (
            isinstance(amount, bool)
            or not isinstance(amount, (int, float))
            or not math.isfinite(float(amount))
            or float(amount) <= 0.0
        ):
            raise ValueError(
                f"resource_restore_per_auto.amount on slot {key!r} must be a "
                f"positive finite number, got {amount!r}"
            )
        if not isinstance(source, str) or not source.strip():
            raise ValueError(
                f"resource_restore_per_auto.source on slot {key!r} must be a "
                "non-empty string"
            )
        if (
            not isinstance(atoms, (list, tuple))
            or not atoms
            or any(
                not isinstance(pair, (list, tuple))
                or len(pair) != 2
                or not all(isinstance(part, str) and part for part in pair)
                for pair in atoms
            )
        ):
            raise ValueError(
                f"resource_restore_per_auto.atoms on slot {key!r} must be a "
                "non-empty list of (atom_id, hash) string pairs"
            )
        declaring.append(
            (
                key,
                {
                    "amount": float(amount),
                    "source": source,
                    "atoms": tuple(tuple(pair) for pair in atoms),
                },
            )
        )
    if not declaring:
        return None
    if len(declaring) > 1:
        raise ValueError(
            "multiple resource_restore_per_auto declarations ("
            + ", ".join(repr(key) for key, _ in declaring)
            + "); the fight model supports one per-auto mana restore source"
        )
    return declaring[0]


def _auto_restore_schedule(
    state: FightState, plan: CastPlan
) -> tuple[tuple[float, ...], list[dict[str, Any]]]:
    """Auto-stream restore timestamps for the walk.

    Returns ``(ordinary_times, swing_events)``.  ``ordinary_times`` are the
    fight's ordinary basic attacks at the uniform ordinary rate (the
    post-burst count, replicating ``_apply_empowered_burst_autos``, which
    runs AFTER this walk); ``swing_events`` are per-swing restore
    descriptors for empowered bursts that fire at their own rate (Jayce's
    Hyper Charge) — each is gated on its arming cast being ACCEPTED when
    it pops (a denied cast never fires its swings, so it cannot mint mana
    — the Spellblade-restore precedent).

    The restore COUNT therefore mirrors the engine's post-admission auto
    stream in denial-free fights (normal autos outside the burst window
    plus the burst swings themselves); a denied burst cast's swings are
    skipped at pop time.  Hail of Blades / Lethal Tempo per-swing timing
    IS mirrored: ``_restore_stream_attack_timestamps`` resolves the same
    stack-sensitive schedule ``_prepare_hail_attack_schedule`` /
    ``_prepare_lethal_tempo_attack_schedule`` install later, directly from
    the keystone effect, because this walk runs before that installation.
    Lich Bane-adjusted schedules still resolve after the walk (Spellblade
    proc times are not known yet), so THEIR per-swing timing is not
    mirrored (the count is); documented in the champion module's
    ASSUMPTIONS.
    """
    times = _restore_stream_attack_timestamps(state)
    if not times:
        return (), []
    burst_swings = 0
    burst_seconds = 0.0
    swing_events: list[dict[str, Any]] = []
    for key in state.cast_order:
        empower = (ability_payload(state.ability_damages, key)).get(
            "empowers_next_auto"
        )
        burst_as = _empower_burst_attack_speed(empower) if empower else 0.0
        if burst_as <= 0.0:
            continue
        hits = _empower_hits(empower)
        for ordinal, cast_time in enumerate(plan.times.get(key, ())):
            burst_swings += hits
            burst_seconds += hits / burst_as
            swing_events.extend(
                {
                    "time": cast_time + (swing_index + 1) / burst_as,
                    "arming_key": key,
                    "arming_ordinal": ordinal,
                    "swing_index": swing_index + 1,
                    "hits": hits,
                    # P1 Slice 12 (R1): this cast's burst-time
                    # contribution — a DENIED arming cast never fires
                    # its swings, so its budget is returned to the
                    # ordinary stream (the denied cast cannot shrink
                    # the per-auto restore budget).
                    "burst_seconds": hits / burst_as,
                }
                for swing_index in range(hits)
            )
    if burst_swings <= 0:
        return tuple(times), []
    normal_rate = state.attack_speed * state.auto_attack_uptime
    if normal_rate <= 0.0:
        return (), swing_events
    leftover = max(0.0, state.fight_duration_seconds - burst_seconds)
    ordinary = math.floor(normal_rate * leftover)
    return tuple(_swings_at_rate(ordinary, normal_rate)), swing_events


def _declared_mapping(info: Mapping[str, Any], key: str) -> Mapping[str, Any] | None:
    """A champion entry's ``key`` declaration, absent, or a stop when malformed."""
    decl = info.get(key)
    if decl is None:
        return None
    if not isinstance(decl, Mapping):
        raise ValueError(f"{key} must be a mapping")
    return decl


def _finite_non_negative(value: Any, label: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) < 0.0
    ):
        raise ValueError(f"{label} must be a finite non-negative number, got {value!r}")
    return float(value)


def _non_empty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _atom_pairs(value: Any, label: str) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(pair, (list, tuple))
        or len(pair) != 2
        or not all(isinstance(part, str) and part for part in pair)
        for pair in value
    ):
        raise ValueError(f"{label} must be a list of (atom_id, hash) string pairs")
    return tuple(tuple(pair) for pair in value)


def _kill_refund_decl(info: Mapping[str, Any]) -> dict[str, Any] | None:
    """Validate and normalize a champion entry's ``kill_refund`` declaration.

    Darius W declares the typed refund rule behind the asserted kill (the
    w_kill_assertion option): when the empowered attack kills, refund the
    flat (40 = the sourced W cost).  Malformed declarations raise (authored
    code fails closed).
    """
    decl = _declared_mapping(info, "kill_refund")
    if decl is None:
        return None
    atoms = ability_field(decl, "atoms", form="resource_declaration")
    return {
        "flat": _finite_non_negative(decl.get("flat"), "kill_refund.flat"),
        "source": _non_empty_string(decl.get("source"), "kill_refund.source"),
        "atoms": _atom_pairs(atoms, "kill_refund.atoms"),
    }


def _mark_refund_decl(info: Mapping[str, Any]) -> dict[str, Any] | None:
    """Validate and normalize a champion entry's ``mark_refund`` declaration.

    Ezreal's W (Essence Flux) declares the typed refund rule: when the mark
    is detonated BY AN ABILITY, restore ``flat`` mana plus that ability's
    mana cost.  ``detonation`` (from the champion's public option) decides
    the detonation means; ``basic_attack`` disables the refund entirely.
    Malformed declarations raise (authored code fails closed).
    """
    decl = _declared_mapping(info, "mark_refund")
    if decl is None:
        return None
    window_seconds = decl.get("window_seconds")
    detonation = decl.get("detonation")
    atoms = ability_field(decl, "atoms", form="resource_declaration")
    flat = _finite_non_negative(decl.get("flat"), "mark_refund.flat")
    if (
        isinstance(window_seconds, bool)
        or not isinstance(window_seconds, (int, float))
        or not math.isfinite(float(window_seconds))
        or float(window_seconds) <= 0.0
    ):
        raise ValueError(
            "mark_refund.window_seconds must be a finite positive number, "
            f"got {window_seconds!r}"
        )
    source = _non_empty_string(decl.get("source"), "mark_refund.source")
    if detonation not in {"ability", "basic_attack"}:
        raise ValueError(
            f"mark_refund.detonation must be 'ability' or 'basic_attack', got "
            f"{detonation!r}"
        )
    return {
        "flat": flat,
        "window_seconds": float(window_seconds),
        "source": source,
        "detonation": detonation,
        "atoms": _atom_pairs(atoms, "mark_refund.atoms"),
    }


def _sole_refund_slot(
    state: FightState, *, reader: Callable[[Mapping[str, Any]], Any], kind: str
) -> str | None:
    """The single slot declaring a ``kind`` refund, or None; two is a stop.

    The resource walk supports one authored refund rule of each kind per
    fight (the auto-restore guard makes the same refusal).
    """
    declaring = [
        key for key, info in state.ability_damages.items() if reader(info) is not None
    ]
    if len(declaring) > 1:
        raise ValueError(
            f"multiple {kind} declarations ({', '.join(sorted(declaring))})"
        )
    return declaring[0] if declaring else None


_kill_refund_decl_for_state = partial(
    _sole_refund_slot, reader=_kill_refund_decl, kind="kill_refund"
)


_mark_refund_decl_for_state = partial(
    _sole_refund_slot, reader=_mark_refund_decl, kind="mark_refund"
)
