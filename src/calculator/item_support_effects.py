"""Typed, timestamped ally/team item packets for the participant ledger.

The ordinary item compiler owns damage emitted by the holder.  This module
owns the other side of the same Wiki entries: ally shields/heals, temporary
health, stat buffs, all-source debuffs, and explicit item-actives.  It never
assumes an active or a trigger that is absent from the authored event stream.
"""

from __future__ import annotations

import ast
from collections.abc import Collection, Iterable, Mapping
from functools import lru_cache
import math
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .ability_spec import (
    IMMOBILIZING_CC_KINDS,
    AttackClass,
    Authority,
    DamageClass,
    is_immobilizing_event,
)
from .item_effects import (
    ALLY_ITEM_EFFECTS,
    ITEM_INPUT_OPTIONS,
    ally_item_effect_value,
    ally_item_level_value,
    required_effect_value,
)

# The item layer's one edge into the survival kernel: packet authors declare
# when their packet arms, in the walk's vocabulary, so there is no second
# ordering language to keep in sync.  Note the reach — importing
# ``.survival.actions`` executes ``survival/__init__.py``, so the whole
# kernel package loads with this module.  Acyclic: nothing under
# ``survival/`` imports ``item_support_effects``.
from .survival.actions import SUPPORT_RANK_KEY, TransitionRank


def _same_side(attacker: Any, actor: Any) -> bool:
    left = "main" if attacker.team in {"main", "ally"} else attacker.team
    right = "main" if actor.team in {"main", "ally"} else actor.team
    return left == right


def _teammates(attacker: Any, all_actors: Iterable[Any]) -> list[Any]:
    return [
        actor
        for actor in all_actors
        if actor.participant_id != attacker.participant_id
        and _same_side(attacker, actor)
    ]


def _item_names(attacker: Any) -> set[str]:
    return {str(item.get("name", "")) for item in attacker.items}


def _option(attacker: Any, item_name: str, key: str, default: float = 0.0) -> float:
    request = getattr(attacker, "request", None)
    item_options = getattr(request, "item_options", {}) or {}
    options = item_options.get(item_name, {})
    value = options.get(key, default) if isinstance(options, Mapping) else default
    if isinstance(value, bool):
        raise ValueError(f"{item_name}.{key} must be numeric")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{item_name}.{key} must be numeric") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{item_name}.{key} must be finite")
    return parsed


def _event_time(event: Mapping[str, Any]) -> float:
    value = event.get("time", 0.0)
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("item support event time must be numeric") from exc
    if not math.isfinite(parsed):
        raise ValueError("item support event time must be finite")
    return parsed


def _packet(
    *,
    attacker: Any,
    target: Any,
    time: float,
    kind: str,
    source: str,
    amount: float = 0.0,
    duration: float = 0.0,
    target_scope: str = "one_teammate",
    rank: TransitionRank | None = None,
    authority: Authority | None = None,
    damage_classes: frozenset[DamageClass] | None = None,
    attack_classes: frozenset[AttackClass] | None = None,
    **fields: Any,
) -> dict[str, Any]:
    """Build one sourced packet.

    ``rank`` is how a packet declares *when* it arms, for the packets whose
    kind does not decide it (a barrier the triggering damage placed, say).
    It is the only way to override the walk's ladder: an author names a
    :class:`TransitionRank`, never a number.

    ``authority`` is how a ``damage_modifier`` packet declares which engine
    owns its mechanic.  It is required of those packets and meaningless on
    the rest, it is checked here — the one construction site all six
    cross-participant producers pass through — and it is deliberately *not*
    written into the returned dict: the declaration's homes are this call
    site and :func:`cross_participant_authorities`, and a packet payload
    that grew a key would move receipts inside a semantic commit (R-17).

    ``damage_classes`` and ``attack_classes`` are how a ``damage_modifier``
    packet says *what it applies to* — the two axes of D-04, both required
    of those packets, both banned from being empty, and both checked here.
    Unlike ``authority`` they are written into the returned dict, because
    the walk reads them per packet; they reach no receipt, because the
    published support-event payload is an explicit key list
    (``participant_timeline``'s ``support_events`` block) and neither key is
    on it.

    ``rank`` also sits earlier in the returned dict than the open ordering
    float it replaced did: that arrived through ``**fields``, after every
    explicit key, and the rank is injected before them.  Inert — the
    published receipt is assembled from an explicit key list, not from this
    dict's order — but it is a payload-shape change beyond the key's name
    and type, and a fixture comparing serialized packet order would see it.
    """
    if not math.isfinite(float(amount)) or float(amount) < 0.0:
        raise ValueError(f"{source} packet amount must be finite and non-negative")
    if not math.isfinite(float(duration)) or float(duration) < 0.0:
        raise ValueError(f"{source} packet duration must be finite and non-negative")
    if kind == _DAMAGE_MODIFIER_KIND:
        _check_cross_participant_authority(source, authority, fields.get("owner"))
        _check_declared_classes(source, damage_classes, attack_classes)
        _check_aura_arming(source, fields.get("persistent"), rank)
        fields = {
            "damage_classes": damage_classes,
            "attack_classes": attack_classes,
            **fields,
        }
    return {
        "time": float(time),
        "kind": kind,
        "amount": float(amount),
        "duration": float(duration),
        "source": source,
        "source_key": source,
        "attacker": attacker.participant_id,
        "target": target.participant_id,
        "target_scope": target_scope,
        "target_policy": "explicit_selected_roster_target",
        "_item_support": True,
        **({SUPPORT_RANK_KEY: rank} if rank is not None else {}),
        **fields,
    }


def _support_triggers(
    trigger_effects: Iterable[Mapping[str, Any]], attacker: Any
) -> list[Mapping[str, Any]]:
    """Return ally heal/shield packets that can trigger item passives."""
    return [
        event
        for event in trigger_effects
        if str(event.get("kind", "")) in {"heal", "shield"}
        and str(event.get("target", "")) != attacker.participant_id
    ]


# Any authored cc_kind that means real crowd control — the immobilize
# class plus slows. ("none" is a reviewed no-CC statement, never a trigger.)
_CC_TRIGGER_KINDS = IMMOBILIZING_CC_KINDS | frozenset({"slow"})


def _cc_triggers(result: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Return damage packets with an authored crowd-control marker."""
    markers = {"immobilized", "crowd_control", "hard_cc"}
    return [
        event
        for event in result.get("damage_events", [])
        if isinstance(event, Mapping)
        if any(bool(event.get(marker)) for marker in markers)
        or str(event.get("cc_kind", "")).lower() in _CC_TRIGGER_KINDS
    ]


def _fimbulwinter_trigger_kind(event: Mapping[str, Any]) -> str:
    """Return the explicitly reviewed Everlasting trigger kind, if any."""
    kind = str(event.get("cc_kind", "")).lower().strip()
    if kind in IMMOBILIZING_CC_KINDS:
        return "immobilize"
    if kind == "slow" or bool(event.get("slowed")) or bool(event.get("slow")):
        return "slow"
    if is_immobilizing_event(event):
        # Legacy ``immobilized`` / ``hard_cc`` flags without a narrowed kind.
        return "immobilize"
    # A bare ``crowd_control`` flag does not distinguish Everlasting's
    # immobilize/slow branches, so it is intentionally not enough here.
    return ""


def _current_mana_at(
    result: Mapping[str, Any], event_time: float, maximum_mana: float
) -> float:
    """Resolve current mana from the ordered cast receipt at one timestamp."""
    current = max(0.0, float(maximum_mana))
    casts = result.get("cast_timeline", ())
    if not isinstance(casts, Iterable):
        return current
    ordered = []
    for cast in casts:
        if not isinstance(cast, Mapping):
            continue
        try:
            cast_time = float(cast.get("time", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(cast_time) or cast_time > event_time + 1e-9:
            continue
        ordered.append((cast_time, cast))
    for _, cast in sorted(ordered, key=lambda row: row[0]):
        raw_after = cast.get("resource_after")
        if raw_after is None:
            continue
        try:
            parsed = float(raw_after)
        except (TypeError, ValueError):
            continue
        if math.isfinite(parsed):
            current = max(0.0, parsed)
    return current


def _takedown_triggers(result: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Return only explicit takedown receipts; never infer a kill from damage."""
    return [
        event
        for event in result.get("takedown_events", [])
        if isinstance(event, Mapping)
        and event.get("time") is not None
        and str(event.get("target", ""))
    ]


def _damage_triggers(result: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Return authored non-reactive champion damage packets for item stacks."""
    return [
        event
        for event in result.get("damage_events", [])
        if isinstance(event, Mapping)
        and float(event.get("damage", 0.0) or 0.0) > 0.0
        and not event.get("_reactive")
        and str(event.get("target", ""))
    ]


def _target_by_id(all_actors: Iterable[Any], participant_id: str) -> Any | None:
    return next(
        (actor for actor in all_actors if actor.participant_id == participant_id), None
    )


def _selected_teammate(attacker: Any, teammates: list[Any]) -> Any | None:
    if not teammates:
        return None
    raw_index = _option(attacker, "Knight's Vow", "worthy_target_index", 0.0)
    index = max(0, min(len(teammates) - 1, int(raw_index)))
    return teammates[index]


# Items whose cross-participant packets are derived by scanning the
# holder's damage/takedown event stream below (Phage's Rage autos, Black
# Cleaver Carve stacks, Bloodletter's Curse, Bloodsong's Expose Weakness,
# Cryptbloom's takedown nova).  The optimizer's score-only tuple ledger
# carries positional rows the scan cannot read, so the pipeline's tuple
# predicate consults this set and keeps dict rows for these holders
# (issue #169).  Every new branch below that reads ``damage_events`` or
# ``takedown_events`` must add its item here, or a score-only fight will
# silently starve its scan.
EVENT_SCAN_SUPPORT_ITEMS = frozenset(
    {
        "Black Cleaver",
        "Bloodletter's Curse",
        "Bloodsong",
        "Cryptbloom",
        "Phage",
    }
)


def has_event_scan_support_items(items: Iterable[Mapping[str, Any]]) -> bool:
    """Whether any held item derives support packets from the event stream."""
    return any(str(item.get("name", "")) in EVENT_SCAN_SUPPORT_ITEMS for item in items)


# The subset whose trigger is the takedown stream: the receipt composition
# synthesizes ``takedown_events`` from the pair fight's one-pair shield
# outcome (``target_ending_health``), so a score-only fight for these
# holders must keep that outcome instead of skipping it (issue #169).
TAKEDOWN_SCAN_SUPPORT_ITEMS = frozenset({"Cryptbloom"})


def has_takedown_scan_support_items(items: Iterable[Mapping[str, Any]]) -> bool:
    """Whether any held item derives support packets from takedowns."""
    return any(
        str(item.get("name", "")) in TAKEDOWN_SCAN_SUPPORT_ITEMS for item in items
    )


# The holders that consume each pre-scanned trigger stream below.  The
# streams are built lazily from these sets: every consumer branch in
# ``derive_item_support_effects`` is gated on its item name, so a holder
# with none of a stream's items can skip that scan entirely.  A new branch
# that reads ``cc_events``/``damage_events`` must add its item here, or
# its stream will arrive empty.
CC_TRIGGER_ITEMS = frozenset(
    {"Fimbulwinter", "Bandlepipes", "Solstice Sleigh", "Imperial Mandate"}
)
DAMAGE_TRIGGER_ITEMS = frozenset({"Bloodsong", "Black Cleaver", "Bloodletter's Curse"})

# Which per-event stream each event-view holder reads.  Grouping the
# registries above by stream is what lets a starved holder be told *which*
# projection failed to answer, instead of only that it starved.
EVENT_VIEW_STREAMS: Mapping[str, frozenset[str]] = {
    "cc_events": CC_TRIGGER_ITEMS,
    # Echoes of Helia sums raw per-event damage; the scanners read the same
    # rows for stacks and procs.  Cryptbloom is a takedown reader only.
    "damage_events": (EVENT_SCAN_SUPPORT_ITEMS - TAKEDOWN_SCAN_SUPPORT_ITEMS)
    | frozenset({"Echoes of Helia"}),
    "takedown_events": TAKEDOWN_SCAN_SUPPORT_ITEMS,
}

# Every holder whose scan reads the per-event view at all (``target`` /
# ``_event_id`` enrichment, the takedown synthesis, or a raw damage sum).
# The optimizer's compiled path builds that enriched per-event view only
# for these holders; everyone else scans the plain engine result — and the
# pipeline's score-only tuple gate keeps dict rows for exactly this set, so
# one predicate answers the tuple question on both paths (D-01).
EVENT_VIEW_SUPPORT_ITEMS = frozenset().union(*EVENT_VIEW_STREAMS.values())


def has_event_view_support_items(items: Iterable[Mapping[str, Any]]) -> bool:
    """Whether any held item scans the per-event damage/takedown view."""
    return any(str(item.get("name", "")) in EVENT_VIEW_SUPPORT_ITEMS for item in items)


class EventViewStarvationError(ValueError):
    """A declared event-view holder was handed the light tuple ledger.

    The tuple rows are positional, so every scan below reads them as an
    empty stream and prices the item at zero without failing.  That is a
    projection a consumer cannot answer from — a programming error, not a
    data condition — so it is raised rather than absorbed.
    """


def require_event_view(result: Mapping[str, Any], names: Collection[str]) -> None:
    """Raise when a declared event-view holder is handed tuple rows.

    The score-only tuple ledger (``damage_events_tuple``) carries positional
    rows that no scan below can read.  After the pipeline's tuple gate
    consults ``has_event_view_support_items`` no public request can reach
    this state, so the raise is a programming-error tripwire rather than a
    user-facing outcome.
    """
    if not result.get("damage_events_tuple"):
        return
    starved = sorted(
        (item, stream)
        for stream, holders in EVENT_VIEW_STREAMS.items()
        for item in holders
        if item in names
    )
    if not starved:
        return
    read = "; ".join(f"{item} reads {stream}" for item, stream in starved)
    raise EventViewStarvationError(
        "STARVED: the score-only tuple ledger cannot answer the item support "
        f"scan — {read}.  The pipeline's tuple gate must keep dict rows for "
        "every event-view holder."
    )


def derive_item_support_effects(
    attacker: Any,
    result: Mapping[str, Any],
    all_actors: list[Any],
    trigger_effects: Iterable[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    """Compile the holder's explicit cross-participant item packets."""
    if attacker.team == "ally" and not getattr(
        getattr(attacker, "request", None), "ally_effects_enabled", False
    ):
        return []
    names = _item_names(attacker)
    require_event_view(result, names)
    teammates = _teammates(attacker, all_actors)
    packets: list[dict[str, Any]] = []
    triggers = _support_triggers(trigger_effects, attacker)
    # Each stream scans the full event ledger, so it is built only when a
    # held item consumes it (the registries above own that knowledge).
    cc_events = _cc_triggers(result) if names & CC_TRIGGER_ITEMS else []
    takedown_events = (
        _takedown_triggers(result) if names & TAKEDOWN_SCAN_SUPPORT_ITEMS else []
    )
    damage_events = _damage_triggers(result) if names & DAMAGE_TRIGGER_ITEMS else []

    # Reap is a progression/economy branch, not a guessed combat bonus.  The
    # authored minion-kill count is bounded by its sourced 100-kill quest and
    # produces one inspectable gold receipt only after the caller supplies it.
    if "Cull" in names:
        minion_kills = max(0.0, _option(attacker, "Cull", "reap_minion_kills"))
        cap = required_effect_value("Cull", "reap_max_gold")
        per_minion = required_effect_value("Cull", "reap_gold_per_minion")
        completion_gold = required_effect_value("Cull", "reap_completion_gold")
        earned = min(minion_kills, cap) * per_minion
        if minion_kills >= cap:
            earned += completion_gold
        if earned > 0.0:
            source_meta = ITEM_INPUT_OPTIONS["Cull"]
            packets.append(
                _packet(
                    attacker=attacker,
                    target=attacker,
                    time=0.0,
                    kind="economy",
                    source="Cull — Reap",
                    amount=earned,
                    target_scope="self",
                    gold_amount=earned,
                    minion_kills=min(minion_kills, cap),
                    completion_granted=minion_kills >= cap,
                    source_url=source_meta["source_url"],
                    source_revision_id=source_meta["source_revision_id"],
                )
            )

    # Rage is emitted from the same authored auto stream used by the damage
    # ledger.  No movement state is invented when the stream is absent or
    # coarse; each qualifying basic attack gets its own timestamped packet.
    if "Phage" in names:
        is_melee = bool(attacker.stats.get("is_melee", False))
        speed_key = (
            "rage_bonus_move_speed_melee"
            if is_melee
            else "rage_bonus_move_speed_ranged"
        )
        bonus_speed = required_effect_value("Phage", speed_key)
        duration = required_effect_value("Phage", "rage_duration")
        source_meta = ITEM_INPUT_OPTIONS["Phage"]
        for event in result.get("damage_events", ()):
            if not isinstance(event, Mapping):
                continue
            if str(event.get("source_key", "")) != "auto_attacks" and not bool(
                event.get("basic_attack")
            ):
                continue
            packets.append(
                _packet(
                    attacker=attacker,
                    target=attacker,
                    time=_event_time(event),
                    kind="movement",
                    source="Phage — Rage",
                    amount=bonus_speed,
                    duration=duration,
                    target_scope="self",
                    bonus_move_speed_percent=bonus_speed,
                    trigger="authored_basic_attack",
                    source_url=source_meta["source_url"],
                    source_revision_id=source_meta["source_revision_id"],
                )
            )

    # Support Quest is represented as explicit economy and vision outcomes.
    # The role-quest contract decides which transformed item is equipped; this
    # packet layer records only the authored progress/ward state for that item.
    for quest_item in ("World Atlas", "Runic Compass"):
        if quest_item not in names:
            continue
        source_meta = ITEM_INPUT_OPTIONS[quest_item]
        gold = max(0.0, _option(attacker, quest_item, "shared_riches_gold"))
        gold_cap = required_effect_value(quest_item, "support_quest_threshold")
        if gold > 0.0:
            packets.append(
                _packet(
                    attacker=attacker,
                    target=attacker,
                    time=0.0,
                    kind="economy",
                    source=f"{quest_item} — Shared Riches",
                    amount=min(gold, gold_cap),
                    target_scope="self",
                    gold_amount=min(gold, gold_cap),
                    quest_threshold=gold_cap,
                    source_url=source_meta["source_url"],
                    source_revision_id=source_meta["source_revision_id"],
                )
            )
        ward_uses = max(
            0.0,
            min(
                _option(attacker, quest_item, "ward_uses"),
                required_effect_value(quest_item, "ward_charges"),
            ),
        )
        if ward_uses > 0.0:
            packets.append(
                _packet(
                    attacker=attacker,
                    target=attacker,
                    time=0.0,
                    kind="vision",
                    source=f"{quest_item} — Ward",
                    amount=ward_uses,
                    target_scope="self",
                    ward_uses=ward_uses,
                    quest_threshold=gold_cap,
                    source_url=source_meta["source_url"],
                    source_revision_id=source_meta["source_revision_id"],
                )
            )

    # Fimbulwinter's Everlasting is a self shield that fires only from an
    # explicitly marked immobilize, or a slow for a melee holder.  Its
    # current-mana threshold and cooldown are resolved from the same ordered
    # cast receipt that drives resource admission; no cast or crowd-control
    # state is inferred from a spell name.
    if "Fimbulwinter" in names:
        is_melee = bool(attacker.stats.get("is_melee", False))
        champion_stats = result.get("champion_stats", attacker.stats)
        if not isinstance(champion_stats, Mapping):
            champion_stats = attacker.stats
        maximum_mana = max(
            0.0,
            float(champion_stats.get("max_mana", attacker.stats.get("max_mana", 0.0))),
        )
        mana_threshold_ratio = required_effect_value(
            "Fimbulwinter", "everlasting_mana_threshold_ratio"
        )
        nearby_enemy_count = sum(
            1 for actor in all_actors if not _same_side(attacker, actor)
        )
        cooldown = required_effect_value("Fimbulwinter", "everlasting_cooldown")
        last_activation = float("-inf")
        seen_casts: set[str] = set()
        source_meta = ITEM_INPUT_OPTIONS["Fimbulwinter"]
        for event in cc_events:
            trigger_kind = _fimbulwinter_trigger_kind(event)
            if not trigger_kind or (trigger_kind == "slow" and not is_melee):
                continue
            time = _event_time(event)
            cast_identity = str(
                event.get("ability_instance")
                or f"{event.get('source_key', '')}:{round(time, 9)}"
            )
            if cast_identity in seen_casts:
                continue
            seen_casts.add(cast_identity)
            if time < last_activation + cooldown - 1e-9:
                continue
            current_mana = _current_mana_at(result, time, maximum_mana)
            if (
                maximum_mana <= 0.0
                or current_mana <= maximum_mana * mana_threshold_ratio
            ):
                continue
            multiplier = (
                required_effect_value(
                    "Fimbulwinter", "everlasting_multi_target_multiplier"
                )
                if nearby_enemy_count > 1
                else 1.0
            )
            amount = (
                required_effect_value("Fimbulwinter", "everlasting_base_shield")
                + current_mana
                * required_effect_value(
                    "Fimbulwinter", "everlasting_current_mana_ratio"
                )
            ) * multiplier
            packets.append(
                _packet(
                    attacker=attacker,
                    target=attacker,
                    time=time,
                    kind="shield",
                    source="Fimbulwinter — Everlasting",
                    amount=amount,
                    duration=required_effect_value(
                        "Fimbulwinter", "everlasting_duration"
                    ),
                    target_scope="self",
                    trigger=trigger_kind,
                    _trigger_event_id=event.get("_event_id"),
                    trigger_kind=trigger_kind,
                    current_mana=current_mana,
                    mana_threshold=maximum_mana * mana_threshold_ratio,
                    nearby_enemy_count=nearby_enemy_count,
                    multi_target_multiplier=multiplier,
                    cooldown=cooldown,
                    cooldown_until=time + cooldown,
                    source_url=source_meta["source_url"],
                    source_revision_id=source_meta["source_revision_id"],
                    rank=TransitionRank.LATE_BARRIER,
                )
            )
            last_activation = time

    # Shared target modifiers are emitted only from an authored trigger.  The
    # holder's own pair engine already prices its personal Black Cleaver,
    # Bloodletter, Bloodsong, and Abyssal branches; the ordered participant
    # walk consumes these packets for every other eligible source without
    # double-counting the originating holder.
    if "Abyssal Mask" in names:
        for target in (
            actor for actor in all_actors if not _same_side(attacker, actor)
        ):
            packets.append(
                _packet(
                    attacker=attacker,
                    target=target,
                    time=0.0,
                    kind="damage_modifier",
                    source="Abyssal Mask — Unmake",
                    amount=ally_item_effect_value("Abyssal Mask", "magic_damage_amp"),
                    multiplier=1.0
                    + ally_item_effect_value("Abyssal Mask", "magic_damage_amp"),
                    all_sources=True,
                    persistent=True,
                    # Unmake is an aura, not a triggered debuff: an enemy
                    # inside the radius is cursed from the first frame, so
                    # the curse must be in force for the damage that lands
                    # at the packet's own timestamp.  The kind ladder's
                    # ``DEBUFF_ARM`` armed it *after* that damage, which
                    # made the opening exchange the one exchange Unmake did
                    # not price (C4).
                    rank=TransitionRank.AURA_ARM,
                    range_assumption="within_700_units",
                    # "receive 12% increased *magic* damage from all
                    # sources": one damage class, every attack class.  The
                    # walk applied it to physical and true damage too until
                    # this declaration existed to say otherwise.
                    damage_classes=frozenset({DamageClass.MAGIC}),
                    attack_classes=frozenset(AttackClass),
                    authority=Authority.SPLIT,
                    # The holder's own Unmake is priced pair-side, as the
                    # ``magic_amp`` term of the damage engine's build
                    # projection.  Without this handshake the walk amps the
                    # holder a second time and the holder's magic arrives at
                    # 1.12 squared.
                    owner=attacker.participant_id,
                )
            )

    if "Bloodsong" in names:
        expose_key = (
            "expose_weakness_melee"
            if bool(attacker.stats.get("is_melee", False))
            else "expose_weakness_ranged"
        )
        for event in damage_events:
            if str(event.get("source_key", "")) != "spellblade_Bloodsong":
                continue
            target = _target_by_id(all_actors, str(event.get("target", "")))
            if target is None:
                continue
            rate = ally_item_effect_value("Bloodsong", expose_key)
            packets.append(
                _packet(
                    attacker=attacker,
                    target=target,
                    time=_event_time(event),
                    kind="damage_modifier",
                    source="Bloodsong — Expose Weakness",
                    amount=rate,
                    duration=ally_item_effect_value(
                        "Bloodsong", "expose_weakness_duration"
                    ),
                    multiplier=1.0 + rate,
                    all_sources=True,
                    cooldown=ally_item_effect_value(
                        "Bloodsong", "expose_weakness_cooldown"
                    ),
                    # "take 8% increased damage from all sources" — no class
                    # is named, so every member of both vocabularies is
                    # declared explicitly rather than left to an empty set.
                    damage_classes=frozenset(DamageClass),
                    attack_classes=frozenset(AttackClass),
                    # The pair engine prices the holder's own Expose Weakness
                    # on a schedule that is not the walk's; the umbrella
                    # freezes that divergence in Phase 3 and moves this row to
                    # COUPLED_AUTHORITATIVE in Phase 4.  Until then the owner
                    # skip is what keeps the two halves from summing.
                    authority=Authority.SPLIT,
                    owner=attacker.participant_id,
                    trigger_event_id=event.get("_event_id"),
                )
            )

    reduction_stacks: dict[tuple[str, str], int] = {}
    for event in damage_events:
        target = _target_by_id(all_actors, str(event.get("target", "")))
        if target is None:
            continue
        damage_type = str(event.get("damage_type", ""))
        source_id = str(event.get("_event_id", ""))
        if "Black Cleaver" in names and damage_type == "physical":
            key = (target.participant_id, "armor")
            stacks = min(
                int(
                    ally_item_effect_value(
                        "Black Cleaver", "armor_reduction_max_stacks"
                    )
                ),
                reduction_stacks.get(key, 0) + 1,
            )
            reduction_stacks[key] = stacks
            percent = stacks * ally_item_effect_value(
                "Black Cleaver", "armor_reduction_per_stack"
            )
            packets.append(
                _packet(
                    attacker=attacker,
                    target=target,
                    time=_event_time(event),
                    kind="damage_modifier",
                    source="Black Cleaver — Carve",
                    amount=percent,
                    duration=ally_item_effect_value(
                        "Black Cleaver", "armor_reduction_duration"
                    ),
                    armor_reduction_percent=percent,
                    resistance_type="armor",
                    # "6% armor reduction": armour mitigates physical
                    # damage, so that is the class the reduction reaches.
                    damage_classes=frozenset({DamageClass.PHYSICAL}),
                    attack_classes=frozenset(AttackClass),
                    # The stack ledger is a roster fact and Carve's move to
                    # coupled-authoritative is H1's to rule; until it is
                    # ruled the pair engine keeps its own Cesàro
                    # approximation and the walk skips the holder.
                    authority=Authority.SPLIT,
                    owner=attacker.participant_id,
                    trigger_event_id=event.get("_event_id", source_id),
                    stack_count=stacks,
                )
            )
        if (
            "Bloodletter's Curse" in names
            and damage_type == "magic"
            and bool(event.get("is_ability"))
        ):
            key = (target.participant_id, "mr")
            stacks = min(
                int(
                    ally_item_effect_value(
                        "Bloodletter's Curse", "mr_reduction_max_stacks"
                    )
                ),
                reduction_stacks.get(key, 0) + 1,
            )
            reduction_stacks[key] = stacks
            percent = stacks * ally_item_effect_value(
                "Bloodletter's Curse", "mr_reduction_per_stack"
            )
            packets.append(
                _packet(
                    attacker=attacker,
                    target=target,
                    time=_event_time(event),
                    kind="damage_modifier",
                    source="Bloodletter's Curse — Vile Decay",
                    amount=percent,
                    duration=ally_item_effect_value(
                        "Bloodletter's Curse", "mr_reduction_duration"
                    ),
                    mr_reduction_percent=percent,
                    resistance_type="magic_resistance",
                    # "magic resistance reduction": the mirror of Carve.
                    damage_classes=frozenset({DamageClass.MAGIC}),
                    attack_classes=frozenset(AttackClass),
                    # Vile Decay is Carve's shape, magic- and ability-gated,
                    # and is H1-blocked with it.
                    authority=Authority.SPLIT,
                    owner=attacker.participant_id,
                    trigger_event_id=event.get("_event_id", source_id),
                    stack_count=stacks,
                )
            )

    for takedown in takedown_events:
        if "Cryptbloom" not in names:
            break
        amount = ally_item_effect_value("Cryptbloom", "life_from_death_base_heal") + (
            float(attacker.stats.get("ability_power", 0.0) or 0.0)
            * ally_item_effect_value("Cryptbloom", "life_from_death_ap_ratio")
        )
        for recipient in (attacker, *teammates):
            packets.append(
                _packet(
                    attacker=attacker,
                    target=recipient,
                    time=_event_time(takedown),
                    kind="heal",
                    source="Cryptbloom — Life From Death",
                    amount=amount,
                    duration=ally_item_effect_value(
                        "Cryptbloom", "life_from_death_nova_duration"
                    ),
                    target_scope="nova_allied_champions",
                    trigger="explicit_takedown_within_damage_window",
                    cooldown=ally_item_effect_value(
                        "Cryptbloom", "life_from_death_cooldown"
                    ),
                )
            )

    # Triggered enchanter passives.  The target is carried by the authored
    # champion packet; no cursor or radius is guessed.
    for trigger in triggers:
        target = _target_by_id(all_actors, str(trigger.get("target", "")))
        if target is None:
            continue
        time = _event_time(trigger)
        if "Ardent Censer" in names:
            packets.extend(
                (
                    _packet(
                        attacker=attacker,
                        target=recipient,
                        time=time,
                        kind="stat_buff",
                        source="Ardent Censer — Sanctify",
                        amount=ally_item_effect_value(
                            "Ardent Censer", "sanctify_bonus_attack_speed"
                        ),
                        duration=ally_item_effect_value(
                            "Ardent Censer", "sanctify_duration"
                        ),
                        bonus_attack_speed_percent=ally_item_effect_value(
                            "Ardent Censer", "sanctify_bonus_attack_speed"
                        ),
                        on_hit_magic_damage=ally_item_effect_value(
                            "Ardent Censer", "sanctify_on_hit_magic"
                        ),
                        recipient_role="holder_and_healed_ally",
                    )
                    for recipient in (attacker, target)
                )
            )
        if "Staff of Flowing Water" in names:
            packets.extend(
                (
                    _packet(
                        attacker=attacker,
                        target=recipient,
                        time=time,
                        kind="stat_buff",
                        source="Staff of Flowing Water — Rapids",
                        amount=ally_item_effect_value(
                            "Staff of Flowing Water", "bonus_ability_power"
                        ),
                        duration=ally_item_effect_value(
                            "Staff of Flowing Water", "duration"
                        ),
                        ability_power=ally_item_effect_value(
                            "Staff of Flowing Water", "bonus_ability_power"
                        ),
                        ability_haste=ally_item_effect_value(
                            "Staff of Flowing Water", "bonus_ability_haste"
                        ),
                        recipient_role="holder_and_healed_ally",
                    )
                    for recipient in (attacker, target)
                )
            )
        if "Moonstone Renewer" in names:
            candidates = [
                actor
                for actor in teammates
                if actor.participant_id != target.participant_id
            ]
            chain_target = candidates[0] if candidates else target
            fraction_key = (
                "heal_chain_fraction"
                if str(trigger.get("kind")) == "heal"
                else "shield_chain_fraction"
            )
            packets.append(
                _packet(
                    attacker=attacker,
                    target=chain_target,
                    time=time,
                    kind=str(trigger.get("kind", "shield")),
                    source="Moonstone Renewer — Starlit Grace",
                    amount=float(trigger.get("amount", 0.0))
                    * ally_item_effect_value("Moonstone Renewer", fraction_key),
                    duration=float(trigger.get("duration", 0.0) or 0.0),
                    target_scope="other_nearest_wounded_ally",
                    chain_fraction=ally_item_effect_value(
                        "Moonstone Renewer", fraction_key
                    ),
                )
            )
        if "Dream Maker" in names:
            packets.extend(
                (
                    _packet(
                        attacker=attacker,
                        target=target,
                        time=time,
                        kind="damage_modifier",
                        source="Dream Maker — Blue Dream Bubble",
                        amount=ally_item_level_value(
                            "Dream Maker",
                            "blue_reduction_min",
                            "blue_reduction_max",
                            target.level,
                        ),
                        duration=ally_item_effect_value(
                            "Dream Maker", "dream_duration"
                        ),
                        damage_reduction=True,
                        next_event_only=True,
                        # "reduces the damage of the next *attack or spell*
                        # they receive": every damage class, but only two
                        # attack classes.  This is the one producer whose
                        # own text matches the walk's delivery gate — the
                        # gate is this restriction, generalised to five
                        # mechanics that never claimed it.
                        damage_classes=frozenset(DamageClass),
                        attack_classes=frozenset(
                            {AttackClass.BASIC_ATTACK, AttackClass.ABILITY}
                        ),
                        # No pair engine prices Blue Dream Bubble: it shields
                        # an *ally* against the next hit from anyone, which is
                        # a roster fact with no pair-local restriction, and
                        # ``item_coverage`` already records that the item is
                        # outside the holder's own TDD.  So there is no
                        # pair-side half to skip and no owner to declare.
                        authority=Authority.COUPLED_ONLY,
                    ),
                    _packet(
                        attacker=attacker,
                        target=target,
                        time=time,
                        kind="on_hit_magic",
                        source="Dream Maker — Purple Dream Bubble",
                        amount=ally_item_level_value(
                            "Dream Maker",
                            "purple_magic_min",
                            "purple_magic_max",
                            target.level,
                        ),
                        duration=ally_item_effect_value(
                            "Dream Maker", "dream_duration"
                        ),
                        next_event_only=True,
                    ),
                )
            )
        if "Echoes of Helia" in names:
            raw_damage = sum(
                max(
                    0.0,
                    float(event.get("raw_damage", event.get("damage", 0.0)) or 0.0),
                )
                for event in result.get("damage_events", [])
            )
            cap = ally_item_level_value(
                "Echoes of Helia", "charge_cap_min", "charge_cap_max", target.level
            )
            charges = min(
                cap,
                raw_damage
                * ally_item_effect_value("Echoes of Helia", "charge_damage_ratio"),
            )
            if charges > 0.0:
                packets.append(
                    _packet(
                        attacker=attacker,
                        target=target,
                        time=time,
                        kind="heal",
                        source="Echoes of Helia — Soul Siphon",
                        amount=charges,
                        target_scope="healed_or_shielded_ally",
                        charges_consumed=charges,
                    )
                )
                # Soul Charges are consumed by the first qualifying heal or
                # shield; subsequent triggers in this authored window do not
                # duplicate the same stored pool.
                break
        if "Diadem of Songs" in names:
            wounded = target
            packets.append(
                _packet(
                    attacker=attacker,
                    target=wounded,
                    time=time,
                    kind="heal",
                    source="Diadem of Songs — Consonance",
                    amount=float(attacker.stats.get("mana", 0.0))
                    * ally_item_effect_value(
                        "Diadem of Songs", "consonance_max_mana_ratio"
                    ),
                    target_scope="nearest_most_wounded_ally",
                    cooldown=ally_item_effect_value(
                        "Diadem of Songs", "consonance_cooldown"
                    ),
                )
            )

    # A hard-CC marker is required for the passives below.  If the reviewed
    # champion module does not emit one, the effect is intentionally absent;
    # callers must not turn an arbitrary cast boundary into a slow/root.
    for cc in cc_events:
        time = _event_time(cc)
        if "Bandlepipes" in names:
            is_melee = bool(attacker.stats.get("is_melee", False))
            duration_key = (
                "fanfare_duration_melee" if is_melee else "fanfare_duration_ranged"
            )
            as_key = (
                "fanfare_ally_attack_speed_melee"
                if is_melee
                else "fanfare_ally_attack_speed_ranged"
            )
            packets.append(
                _packet(
                    attacker=attacker,
                    target=attacker,
                    time=time,
                    kind="movement",
                    source="Bandlepipes — Fanfare",
                    amount=ally_item_effect_value(
                        "Bandlepipes", "fanfare_bonus_move_speed"
                    ),
                    duration=ally_item_effect_value("Bandlepipes", duration_key),
                    bonus_move_speed_percent=ally_item_effect_value(
                        "Bandlepipes", "fanfare_bonus_move_speed"
                    ),
                    target_scope="self",
                    trigger="authored_immobilize_or_slow",
                )
            )
            for recipient in (attacker, *teammates):
                packets.append(
                    _packet(
                        attacker=attacker,
                        target=recipient,
                        time=time,
                        kind="stat_buff",
                        source="Bandlepipes — Fanfare",
                        amount=ally_item_effect_value("Bandlepipes", as_key),
                        duration=ally_item_effect_value("Bandlepipes", duration_key),
                        bonus_attack_speed_percent=ally_item_effect_value(
                            "Bandlepipes", as_key
                        ),
                        trigger="authored_immobilize_or_slow",
                    )
                )
        if "Solstice Sleigh" in names and teammates:
            target = teammates[0]
            for recipient in (attacker, target):
                packets.append(
                    _packet(
                        attacker=attacker,
                        target=recipient,
                        time=time,
                        kind="temporary_health",
                        source="Solstice Sleigh — Going Sledding",
                        amount=ally_item_level_value(
                            "Solstice Sleigh",
                            "temporary_health_min",
                            "temporary_health_max",
                            recipient.level,
                        ),
                        duration=ally_item_effect_value("Solstice Sleigh", "duration"),
                        bonus_move_speed_percent=ally_item_effect_value(
                            "Solstice Sleigh", "bonus_move_speed_percent"
                        ),
                        cooldown=ally_item_effect_value("Solstice Sleigh", "cooldown"),
                        target_scope=(
                            "self" if recipient is attacker else "most_wounded_ally"
                        ),
                    )
                )
        if "Imperial Mandate" in names and is_immobilizing_event(cc):
            target = _target_by_id(all_actors, str(cc.get("target", "")))
            if target is not None:
                packets.append(
                    _packet(
                        attacker=attacker,
                        target=target,
                        time=time,
                        kind="damage_modifier",
                        source="Imperial Mandate — Command",
                        amount=ally_item_effect_value(
                            "Imperial Mandate", "command_damage_amp"
                        ),
                        duration=ally_item_effect_value(
                            "Imperial Mandate", "command_duration"
                        ),
                        multiplier=1.0
                        + ally_item_effect_value(
                            "Imperial Mandate", "command_damage_amp"
                        ),
                        all_sources=True,
                        # "increasing the damage they take from all sources
                        # by 7%": every class on both axes.
                        damage_classes=frozenset(DamageClass),
                        attack_classes=frozenset(AttackClass),
                        # The holder's pair engine prices its own amp
                        # (damage._apply_command_amp); the walk applies
                        # this packet to every other participant only.
                        # Command's move to coupled-authoritative-with-preview
                        # waits on H2's CcScope reading and is Phase 4's; the
                        # umbrella's recorded default until then is SPLIT.
                        authority=Authority.SPLIT,
                        owner=attacker.participant_id,
                    )
                )

    # Explicit item-actives.  A non-zero timestamp is the complete trigger
    # contract; the packet is not emitted at t=0 by default.
    active_time = _option(attacker, "Locket of the Iron Solari", "active_seconds")
    if "Locket of the Iron Solari" in names and active_time > 0.0:
        for target in (attacker, *teammates):
            packets.append(
                _packet(
                    attacker=attacker,
                    target=target,
                    time=active_time,
                    kind="shield",
                    source="Locket of the Iron Solari — Devotion",
                    amount=ally_item_level_value(
                        "Locket of the Iron Solari",
                        "shield_min",
                        "shield_max",
                        target.level,
                    ),
                    duration=ally_item_effect_value(
                        "Locket of the Iron Solari", "shield_duration"
                    ),
                    target_scope="all_selected_teammates",
                )
            )
    active_time = _option(attacker, "Mikael's Blessing", "active_seconds")
    if "Mikael's Blessing" in names and active_time > 0.0 and teammates:
        target = teammates[0]
        packets.append(
            _packet(
                attacker=attacker,
                target=target,
                time=active_time,
                kind="heal",
                source="Mikael's Blessing — Purify",
                amount=ally_item_level_value(
                    "Mikael's Blessing", "heal_min", "heal_max", target.level
                ),
                target_scope="explicit_selected_ally",
                cleanse=True,
            )
        )
    active_time = _option(attacker, "Redemption", "active_seconds")
    if "Redemption" in names and active_time > 0.0:
        beam_delay = ally_item_effect_value("Redemption", "beam_delay")
        range_units = ally_item_effect_value("Redemption", "target_area_range_units")
        for target in (attacker, *teammates):
            packets.append(
                _packet(
                    attacker=attacker,
                    target=target,
                    time=active_time + beam_delay,
                    kind="heal",
                    source="Redemption — Intervention",
                    amount=ally_item_level_value(
                        "Redemption", "heal_min", "heal_max", target.level
                    ),
                    target_scope="redemption_allies_in_radius",
                    beam_delay=beam_delay,
                    range_assumption=f"within_{range_units:g}_units",
                )
            )
        # Intervention is also an area true-damage packet.  The calculator has
        # no map coordinates, so every selected enemy is an explicit roster
        # target under the sourced area-radius assumption; no proximity order
        # is invented.  The packet enters the normal phase-0 damage walk so
        # shields, death cutoffs, and attribution remain shared with all other
        # damage events.
        true_damage_ratio = ally_item_effect_value(
            "Redemption", "enemy_max_health_true_damage_ratio"
        )
        for target in (
            actor for actor in all_actors if not _same_side(attacker, actor)
        ):
            amount = (
                max(0.0, float(target.stats.get("health", 0.0))) * true_damage_ratio
            )
            packets.append(
                _packet(
                    attacker=attacker,
                    target=target,
                    time=active_time + beam_delay,
                    kind="damage",
                    source="Redemption — Intervention",
                    amount=amount,
                    damage=amount,
                    damage_type="true",
                    event_precision="exact",
                    target_scope="enemy_champions_in_radius",
                    range_assumption=f"within_{range_units:g}_units",
                    beam_delay=beam_delay,
                    rank=TransitionRank.DAMAGE,
                    sequence=0,
                )
            )
    active_time = _option(attacker, "Shurelya's Battlesong", "active_seconds")
    if "Shurelya's Battlesong" in names and active_time > 0.0:
        for target in (attacker, *teammates):
            packets.append(
                _packet(
                    attacker=attacker,
                    target=target,
                    time=active_time,
                    kind="movement",
                    source="Shurelya's Battlesong — Inspiring Speech",
                    amount=ally_item_effect_value(
                        "Shurelya's Battlesong", "bonus_move_speed_percent"
                    ),
                    duration=ally_item_effect_value(
                        "Shurelya's Battlesong", "duration"
                    ),
                    bonus_move_speed_percent=ally_item_effect_value(
                        "Shurelya's Battlesong", "bonus_move_speed_percent"
                    ),
                    target_scope="all_selected_teammates",
                )
            )
    active_time = _option(attacker, "Stridebreaker", "active_seconds")
    if "Stridebreaker" in names and active_time > 0.0:
        slow_percent = float(required_effect_value("Stridebreaker", "slow_percent"))
        slow_duration = float(required_effect_value("Stridebreaker", "slow_duration"))
        move_speed_percent = float(
            required_effect_value("Stridebreaker", "bonus_move_speed_percent")
        )
        move_speed_duration = float(
            required_effect_value("Stridebreaker", "bonus_move_speed_duration")
        )
        area_radius = float(required_effect_value("Stridebreaker", "area_radius"))
        front_offset = float(required_effect_value("Stridebreaker", "front_offset"))
        for target in (
            actor for actor in all_actors if not _same_side(attacker, actor)
        ):
            packets.append(
                _packet(
                    attacker=attacker,
                    target=target,
                    time=active_time,
                    kind="slow",
                    source="Stridebreaker — Breaking Shockwave",
                    amount=slow_percent,
                    duration=slow_duration,
                    target_scope="enemy_champions_in_radius",
                    slow_percent=slow_percent,
                    range_assumption=f"within_{area_radius:g}_units",
                    cast_geometry=f"{front_offset:g}_unit_front_offset",
                    trigger="explicit_active_seconds",
                )
            )
            packets.append(
                _packet(
                    attacker=attacker,
                    target=attacker,
                    time=active_time,
                    kind="movement",
                    source="Stridebreaker — Breaking Shockwave",
                    amount=move_speed_percent,
                    duration=move_speed_duration,
                    target_scope="self_per_champion_hit",
                    bonus_move_speed_percent=move_speed_percent,
                    champion_hit_target=target.participant_id,
                    range_assumption=f"within_{area_radius:g}_units",
                    cast_geometry=f"{front_offset:g}_unit_front_offset",
                    trigger="explicit_active_seconds",
                )
            )
    return packets


def schedule_knights_vow(
    all_actors: list[Any],
    incoming: Mapping[str, list[dict[str, Any]]],
    outgoing: Mapping[str, list[dict[str, Any]]],
    support_effects: dict[str, list[dict[str, Any]]],
) -> None:
    """Attach one deterministic Worthy tether and redirect/heal receipts."""
    for holder in all_actors:
        if "Knight's Vow" not in _item_names(holder):
            continue
        teammates = _teammates(holder, all_actors)
        target = _selected_teammate(holder, teammates)
        if target is None:
            continue
        fraction = ally_item_effect_value("Knight's Vow", "redirect_fraction")
        heal_fraction = ally_item_effect_value("Knight's Vow", "holder_heal_fraction")
        within_range = _option(holder, "Knight's Vow", "worthy_within_range", 1.0)
        holder_health_ready = _option(
            holder, "Knight's Vow", "holder_above_30_percent", 1.0
        )
        # Pledge is unit-targeted and only operates inside 1250 units.  The
        # roster has no spatial coordinates, so the scenario must expose the
        # authored in-range assumption instead of letting the calculator
        # silently guess it.  The holder-health gate is checked again by the
        # ordered survival walk as health changes over time.
        if within_range <= 0.0 or holder_health_ready <= 0.0:
            reason = (
                "worthy_out_of_range"
                if within_range <= 0.0
                else "holder_health_gate_disabled"
            )
            for event in incoming.get(target.participant_id, []):
                if str(event.get("damage_type", "")) in {"physical", "magic"}:
                    event["redirect_skipped_reason"] = reason
            continue
        for event in incoming.get(target.participant_id, []):
            if str(event.get("damage_type", "")) not in {"physical", "magic"}:
                continue
            if event.get("_reactive") or event.get("_deferred"):
                continue
            if event.get("redirect_fraction"):
                continue
            if not any(
                actor.participant_id == str(event.get("attacker", ""))
                and not _same_side(holder, actor)
                for actor in all_actors
            ):
                continue
            event["redirect_fraction"] = fraction
            event["redirect_target"] = holder.participant_id
            event["redirect_source"] = "Knight's Vow — Sacrifice"
            event["redirect_pre_mitigation_required"] = True
            event["redirect_holder_health_ratio"] = ally_item_effect_value(
                "Knight's Vow", "holder_health_threshold_ratio"
            )
            event["redirect_range_units"] = ally_item_effect_value(
                "Knight's Vow", "worthy_range_units"
            )
            event["redirect_source_revision_id"] = int(
                ally_item_effect_value("Knight's Vow", "source_revision_id")
            )
        for event in outgoing.get(target.participant_id, []):
            if str(event.get("damage_type", "")) not in {"physical", "magic", "true"}:
                continue
            amount = max(0.0, float(event.get("damage", 0.0) or 0.0))
            if amount <= 0.0:
                continue
            support_effects[holder.participant_id].append(
                _packet(
                    attacker=holder,
                    target=holder,
                    time=_event_time(event),
                    kind="heal",
                    source="Knight's Vow — Sacrifice",
                    amount=amount * heal_fraction,
                    target_scope="holder_from_worthy_damage",
                    healing_category="knights_vow",
                    requires_holder_health_ratio=ally_item_effect_value(
                        "Knight's Vow", "holder_health_threshold_ratio"
                    ),
                    range_units=ally_item_effect_value(
                        "Knight's Vow", "worthy_range_units"
                    ),
                    source_revision_id=int(
                        ally_item_effect_value("Knight's Vow", "source_revision_id")
                    ),
                )
            )


def has_ordered_item_team_effects(items: Iterable[Mapping[str, Any]]) -> bool:
    """Whether any build requires the legacy event walk for team packets."""
    return any(str(item.get("name", "")) in ALLY_ITEM_EFFECTS for item in items)


# ---------------------------------------------------------------------------
# Cross-participant producers
# ---------------------------------------------------------------------------
#
# A ``damage_modifier`` packet changes how much damage some *other*
# participant deals or takes, so the question "which engine owns this
# mechanic" has to be answered for every one of them.  The answer is an
# ``ability_spec.Authority`` member, declared in 0A and carried by the
# packets themselves from C2.  It is also what the coupled golden baseline
# reads to prove its scenario set covers every producer (runbook R-12).
#
# The table is DERIVED from this module's own ``_packet(...)`` call sites,
# never typed out: a hand list is a second home for a fact the construction
# sites already state, and the campaign exists because a hand-maintained
# claim outlived the code it described.  ``_declared_authorities`` reads the
# module's source with ``ast`` and returns the ``source=`` literal and the
# ``authority=`` member of every ``kind="damage_modifier"`` packet, so a
# seventh producer joins the table on the commit that constructs it — and a
# seventh producer that declares no authority fails to resolve rather than
# joining as a silent hole.

_MODULE_PATH = Path(__file__)
_DAMAGE_MODIFIER_KIND = "damage_modifier"


def _packet_keyword(call: ast.Call, name: str) -> ast.expr | None:
    """The value node of one keyword argument of a ``_packet(...)`` call."""
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _declared_authority(node: ast.Call, source: str) -> Authority:
    """The ``Authority`` member one ``_packet(...)`` call site declares.

    The declaration must be a literal ``Authority.MEMBER`` attribute: an
    expression the reader cannot resolve statically is exactly the kind of
    claim this table exists to make checkable.
    """
    declared = _packet_keyword(node, "authority")
    if not (
        isinstance(declared, ast.Attribute)
        and isinstance(declared.value, ast.Name)
        and declared.value.id == Authority.__name__
        and declared.attr in Authority.__members__
    ):
        raise ValueError(
            f"{source} modifies another participant's damage and declares no "
            f"literal Authority.<member> at line {node.lineno} of "
            f"{_MODULE_PATH.name}; one of "
            f"{sorted(member.value for member in Authority)} is required (D-07)"
        )
    return Authority[declared.attr]


@lru_cache(maxsize=1)
def _declared_authorities() -> Mapping[str, Authority]:
    """Every ``kind="damage_modifier"`` packet's source and declared engine.

    Derived from this module's own construction sites so that the table
    cannot disagree with the packets: a new cross-participant modifier is a
    row the moment its ``_packet`` call exists, and two call sites sharing
    one ``source`` may not disagree about who owns the mechanic.

    Returned read-only and cached because ``_packet`` consults it on every
    cross-participant packet it builds, and the stack-ledger producers build
    one per damage event.
    """
    tree = ast.parse(_MODULE_PATH.read_text(encoding="utf-8"))
    declared: dict[str, Authority] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Name) and func.id == "_packet"):
            continue
        kind = _packet_keyword(node, "kind")
        if not (isinstance(kind, ast.Constant) and kind.value == _DAMAGE_MODIFIER_KIND):
            continue
        source = _packet_keyword(node, "source")
        if not (isinstance(source, ast.Constant) and isinstance(source.value, str)):
            raise ValueError(
                "a damage_modifier packet must name a literal source; "
                f"line {node.lineno} of {_MODULE_PATH.name} does not"
            )
        authority = _declared_authority(node, source.value)
        previous = declared.get(source.value)
        if previous is not None and previous is not authority:
            raise ValueError(
                f"{source.value} declares {previous.value} at one call site and "
                f"{authority.value} at line {node.lineno} of {_MODULE_PATH.name}; "
                "one mechanic has one owning engine"
            )
        declared[source.value] = authority
    return MappingProxyType(dict(sorted(declared.items())))


def cross_participant_authorities() -> Mapping[str, Authority]:
    """One row per packet that modifies another participant's damage.

    The key is the packet's ``source`` literal; the value is the
    ``Authority`` the packet declares — which engine owns the mechanic.  It
    is the table ``_packet``'s owner-iff-``SPLIT`` check reads, so the rule
    keys on the semantic rather than on the ``all_sources`` flag three of the
    six producers never set (D-07).

    Also the producer set ``golden_snapshot.capture_coupled`` reads (R-12):
    the coupled baseline covers whatever this returns, so a seventh producer
    with no covering scenario fails rather than passes.
    """
    return _declared_authorities()


def _check_cross_participant_authority(
    source: str, authority: Authority | None, owner: Any
) -> None:
    """Every ``damage_modifier`` packet names its engine, and only ``SPLIT`` owns.

    The rule keys on the declared :class:`Authority`, never on a flag: three
    of the six producers set no ``all_sources``, so an ``all_sources``-keyed
    check passes Dream Maker, Black Cleaver and Bloodletter's Curse by
    construction (D-07).  ``owner`` is the walk's skip handshake — the
    holder's own contribution is priced pair-side — so it is meaningful
    exactly when the two halves are disjoint, which is what ``SPLIT`` says.
    """
    declared = cross_participant_authorities().get(source)
    if declared is None:
        raise ValueError(
            f"{source} modifies another participant's damage but names no "
            "Authority; every damage_modifier packet declares one (D-07)"
        )
    if authority is not declared:
        raise ValueError(
            f"{source} was built with authority={authority} but its packet "
            f"declares {declared.value}"
        )
    if owner is not None and declared is not Authority.SPLIT:
        raise ValueError(
            f"{source} declares {declared.value} and carries owner={owner!r}; "
            "only SPLIT has a pair-side half for the walk to skip"
        )
    if owner is None and declared is Authority.SPLIT:
        raise ValueError(
            f"{source} declares SPLIT and carries no owner; the pair-local "
            "half is unreachable to the walk's skip and the holder is priced "
            "twice"
        )


def _check_declared_classes(
    source: str,
    damage_classes: frozenset[DamageClass] | None,
    attack_classes: frozenset[AttackClass] | None,
) -> None:
    """Every ``damage_modifier`` packet says which damage it applies to (D-04).

    Both axes are required with no default and neither may be empty:
    "empty means all" is a silent default, and the walk that consumed these
    packets untyped amplified a magic-only curse onto physical and true
    damage alike.  ``attack_classes`` is the axis on which "from all
    sources" becomes something a packet can *state* rather than something a
    reader infers from a missing restriction.
    """
    for name, declared, vocabulary in (
        ("damage_classes", damage_classes, DamageClass),
        ("attack_classes", attack_classes, AttackClass),
    ):
        if not declared:
            raise ValueError(
                f"{source} modifies another participant's damage and declares "
                f"no {name}; a non-empty frozenset of "
                f"{vocabulary.__name__} is required and empty-means-all is "
                "banned (D-04)"
            )
        if not all(isinstance(member, vocabulary) for member in declared):
            raise ValueError(
                f"{source} declares {name} holding something other than "
                f"{vocabulary.__name__} members"
            )


def _check_aura_arming(
    source: str, persistent: Any, rank: TransitionRank | None
) -> None:
    """A persistent cross-participant modifier is an aura, and arms as one.

    A ``damage_modifier`` some trigger armed is a debuff: it resolves after
    the damage at its own timestamp, because the packet that triggered it
    landed first.  A *persistent* one was already in force when the fight
    opened, so the same ordering makes the opening exchange the one
    exchange the aura does not price — Abyssal Mask's Unmake curses an
    enemy from t = 0 and priced nothing at t = 0 (C4).

    The kind cannot tell the two apart, so the aura declares
    ``AURA_ARM`` on its packet and this refuses a persistent modifier that
    does not.  Fail closed rather than classify on ``persistent`` in the
    walk's kind ladder: a declared rank is greppable, is enumerated by the
    ladder's own source audit, and cannot silently re-order a packet whose
    author never considered the question.
    """
    if not persistent:
        return
    if rank is not TransitionRank.AURA_ARM:
        raise ValueError(
            f"{source} is a persistent damage_modifier and declares "
            f"rank={rank}; a persistent modifier is an aura already in "
            "force and must declare TransitionRank.AURA_ARM, or it prices "
            "nothing at its own timestamp (C4)"
        )


def producer_item(source: str) -> str:
    """The item name a producer's ``source`` literal names.

    Every packet source is spelled ``"<item> — <effect>"``, so the item a
    scenario must equip to reach a producer is derivable from the producer
    itself rather than tabulated beside it.
    """
    return source.split(" — ", 1)[0].strip()


__all__ = [
    "cross_participant_authorities",
    "derive_item_support_effects",
    "has_ordered_item_team_effects",
    "producer_item",
    "require_event_view",
    "schedule_knights_vow",
]
