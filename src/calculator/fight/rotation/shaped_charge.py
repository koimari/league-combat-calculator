"""Ability-triggered lethality procs."""

import math
from collections.abc import Mapping, Sequence
from typing import Any

from ...ability_atoms import ability_field
from ...ability_spec import AttackClass
from ...survival.pricing import AuthoredDeclaration
from ..ledger.event_rows import (
    _CAST_TIME_RESOLUTION,
    _finite_numeric_receipt,
    _item_proc_precision,
)
from ..results import RotationResult
from ..state import FightState, _damage_inputs


# ``mechanic_id`` is the rule the row this packet belongs to previews, handed
# in by its author rather than looked up by owner here, so one row and its
# packets cannot name the rule two ways.  ``AttackClass.OTHER`` is the default
# because an item's own charged packet is priced by ``_mitigate`` alone; the
# ultimate's empowered run states its class, because Fiendhunter's true
# instance rides the swing and earns the basic part amp.  ``raw_amount``
# carries the caller's pair-local factors, which allocate rather than amplify.
def _strike_declaration(
    mechanic_id: str,
    raw_amount: float,
    attack_class: AttackClass = AttackClass.OTHER,
) -> tuple[Any, ...]:
    """One charged-strike packet's declaration: rule, magnitude, attack class."""
    return tuple(AuthoredDeclaration(mechanic_id, raw_amount, attack_class.value))


def _next_authored_event(
    authored_events: Sequence[Any], cursor: int, event_time: float
) -> tuple[int, float | None, str | None] | None:
    """Advance ``cursor`` past the first positive-damage authored event at or
    after ``event_time``: ``(cursor, time, precision)``, the time ``None`` when
    the ledger is exhausted, the whole ``None`` on a malformed row."""
    while cursor < len(authored_events):
        candidate = authored_events[cursor]
        if not isinstance(candidate, Mapping):
            return None
        candidate_time = _finite_numeric_receipt(candidate.get("time"))
        candidate_damage = _finite_numeric_receipt(candidate.get("damage"))
        if candidate_time is None or candidate_damage is None:
            return None
        cursor += 1
        if candidate_time + _CAST_TIME_RESOLUTION + 1e-9 < event_time:
            continue
        if candidate_damage > 0.0:
            precision = str(candidate.get("event_precision", "exact"))
            return cursor, candidate_time, precision
    return cursor, None, None


def _shaped_charge_proc_receipts(
    state: FightState,
    rotation: RotationResult,
    cooldown: float,
) -> list[dict[str, Any]] | None:
    """Return Shaped Charge trigger times with their timing precision.

    Exact ability hit packets are preferred when the champion module authors
    them. Otherwise, the existing cast-boundary fallback is retained and
    explicitly marked coarse. A per-slot cursor prevents repeated casts from
    reusing one authored packet.
    """
    if not math.isfinite(cooldown) or cooldown <= 0.0:
        return None
    receipts: list[dict[str, Any]] = []
    ready_at = 0.0
    event_cursors: dict[str, int] = {}
    breakdown = state.breakdown
    for cast_event in rotation.cast_events:
        if not isinstance(cast_event, Mapping):
            return None
        slot = cast_event.get("slot")
        if not isinstance(slot, str):
            return None
        event_time = _finite_numeric_receipt(cast_event.get("time"))
        if event_time is None or event_time < 0.0:
            return None
        ability = state.ability_damages.get(slot)
        if not isinstance(ability, Mapping):
            return None
        parts = ability_field(ability, "parts")
        if not isinstance(parts, (tuple, list)):
            return None
        damaging = any(
            part.amount > 0.0 or part.hp_scaled_damage is not None for part in parts
        )
        if not damaging:
            continue
        trigger_time = event_time
        precision = _item_proc_precision(state, slot)
        row = breakdown.get(slot) if isinstance(breakdown, Mapping) else None
        authored_events = row.get("damage_events") if isinstance(row, Mapping) else None
        if isinstance(authored_events, list):
            found = _next_authored_event(
                authored_events, event_cursors.get(slot, 0), event_time
            )
            if found is None:
                return None
            event_cursors[slot], authored_time, authored_precision = found
            if authored_time is not None:
                trigger_time, precision = authored_time, authored_precision
        if trigger_time < ready_at:
            continue
        receipts.append({"time": trigger_time, "event_precision": precision})
        ready_at = trigger_time + cooldown
    return receipts


def _add_shaped_charge_damage(state: FightState, rotation: RotationResult) -> None:
    """Add ability-triggered lethality procs from the authored cast ledger."""
    for effect in state.declared.charged_strikes.shaped_charges:
        source = effect.source
        proc_receipts = _shaped_charge_proc_receipts(state, rotation, effect.cooldown)
        if proc_receipts is None:
            # A malformed cast ledger withholds every proc boundary.  Keep a
            # NAMED zero-damage row (P3 package 3D): callers can distinguish
            # a malformed ledger from a passive that never fired, and the
            # coverage classifier treats the withheld row as coarse so the
            # optimizer exclusion receipt names it.  No damage is invented.
            per_proc = source.raw_damage(_damage_inputs(state))
            state.breakdown[source.breakdown_key] = {
                "name": source.display_name,
                "count": 0,
                "damage_per_proc": per_proc,
                "total_damage": 0.0,
                "damage_type": source.damage_type,
                "event_phase": "coarse",
                "withheld_reason": "malformed_proc_receipt",
            }
            continue
        if not proc_receipts:
            # No damaging ability cast consumed the charge: the passive
            # never fired, and no row is authored (no aggregate substitute).
            continue
        per_proc = source.raw_damage(_damage_inputs(state))
        procs = len(proc_receipts)
        total_damage = per_proc * procs
        mechanic = source.previewed_mechanic()
        state.breakdown[source.breakdown_key] = {
            "name": source.display_name,
            "count": procs,
            "damage_per_proc": per_proc,
            "total_damage": total_damage,
            "damage_type": source.damage_type,
            # This row is the pair engine's preview of a number the coupled
            # walk owns: the roster composition reads the stamp and takes the
            # figure below out of every total it composes, while the pair
            # fight's own receipt publishes it unchanged.
            "pair_preview_of": mechanic,
            "declared": _strike_declaration(mechanic, total_damage),
            "damage_events": [
                {
                    "time": receipt["time"],
                    "damage": per_proc,
                    "damage_type": source.damage_type,
                    "event_precision": receipt["event_precision"],
                    "declared": _strike_declaration(mechanic, per_proc),
                }
                for receipt in proc_receipts
            ],
            "event_phase": "ability",
        }
        state.total_damage += total_damage
