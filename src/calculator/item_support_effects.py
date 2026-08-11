"""Typed, timestamped ally/team item packets for the participant ledger.

The ordinary item compiler owns damage emitted by the holder.  This module
owns the other side of the same Wiki entries: ally shields/heals, temporary
health, stat buffs, all-source debuffs, and explicit item-actives.  It never
assumes an active or a trigger that is absent from the authored event stream.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Iterator, Mapping
from functools import lru_cache
import math
from types import MappingProxyType
from typing import Any

from .ability_spec import (
    AttackClass,
    Authority,
    DamageClass,
)

# The typed bus: one home for "what does this raw row mean?" and one for
# "which streams does this holder read?".  Both used to be answered here, by
# four scanners and five hand-maintained name sets that could drift from the
# branches they gated (D-30, D-32).  ``trigger_stream``'s only intra-package
# import is ``ability_spec``, so this edge adds no cycle.
from .trigger_stream import (
    CAPABILITIES,
    CROSS_PARTICIPANT_AUTHORITIES,
    RAW_STREAMS,
    CcClass,
    Engine,
    Trigger,
    TriggerKind,
    authored_triggers,
    streams_for,
    tuple_incapable_items,
)
from .item_effects import ALLY_ITEM_EFFECTS, ITEM_INPUT_OPTIONS

# Phase 3's declarations, and the interpreter that resolves them.  A producer
# is reached through the rule its registry entry declares — "does this holder
# declare Everlasting?" — rather than by spelling the item that has it, and
# every number comes back through the rule's own references, so a key no
# declaration carries is a stop instead of a silent registry read.
from .item_behavior import AllyProducer, PacketKind
from .interpreters.ally_packet import AllyPacketSlot, resolve_slots

# The item layer's one edge into the survival kernel: packet authors declare
# when their packet arms, in the walk's vocabulary, so there is no second
# ordering language to keep in sync.  Note the reach — importing
# ``.survival.actions`` executes ``survival/__init__.py``, so the whole
# kernel package loads with this module.  Acyclic: nothing under
# ``survival/`` imports ``item_support_effects``.
from .survival.actions import SUPPORT_RANK_KEY, TransitionRank

# The one packet kind that changes how much damage some *other* participant
# deals or takes, and therefore the kind ``_packet`` runs its authority and
# damage-class checks on.  See *Cross-participant producers* below.
_DAMAGE_MODIFIER_KIND = "damage_modifier"


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


def _producer(
    slots: Mapping[AllyProducer, tuple[AllyPacketSlot, ...]], producer: AllyProducer
) -> AllyPacketSlot | None:
    """This build's one holder of *producer*, or ``None``.

    ``None`` is an answer, not a zero: the build declares the mechanic
    nowhere, so no packet is owed.  Two holders is a stop — every producer but
    the support quest is carried by exactly one registry record, and a second
    one would be two ledgers nothing says how to combine.
    """
    found = slots.get(producer, ())
    if len(found) > 1:
        raise ValueError(
            f"{[slot.owner for slot in found]} all declare the "
            f"{producer.value} producer and no rule says how two of them "
            "combine"
        )
    return found[0] if found else None


def _active_seconds(attacker: Any, slot: AllyPacketSlot | None) -> float:
    """When the scenario cast *slot*'s active, or ``0.0`` if it never did.

    An explicit non-zero timestamp is the whole trigger contract for an
    item-active: the packet is never emitted at ``t = 0`` by default.  The
    option is read under the declaration's owner, so a build that declares no
    active reads nothing — the option's own type checking lives at the request
    boundary (``scenario.py`` -> ``item_effects.validate_item_input_options``)
    and covers every named item whether the build holds it or not.
    """
    if slot is None:
        return 0.0
    return _option(attacker, slot.owner, "active_seconds")


def _event_time(event: Mapping[str, Any]) -> float:
    value = event.get("time", 0.0)
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("item support event time must be numeric") from exc
    if not math.isfinite(parsed):
        raise ValueError("item support event time must be finite")
    return parsed


def _packet(  # pylint: disable=too-many-arguments
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

    Keyword-only, and the argument-count check is disabled for the reason
    ``trigger_stream``'s own builder disables it: every parameter is a
    declared packet axis a call site names by keyword, and folding them into
    one dict is the untyped bag the typed packet replaced.

    ``rank`` is how a packet declares *when* it arms, for the packets whose
    kind does not decide it (a barrier the triggering damage placed, say).
    It is the only way to override the walk's ladder: an author names a
    :class:`TransitionRank`, never a number.

    ``authority`` is how a ``damage_modifier`` packet declares which engine
    owns its mechanic.  It is required of those packets and meaningless on
    the rest, it is checked here — the one construction site all six
    cross-participant producers pass through — and it is deliberately *not*
    written into the returned dict: the declaration's homes are this call
    site and the mechanic's ``trigger_stream`` capability, and a packet
    payload that grew a key would move receipts inside a semantic commit
    (R-17).

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


# Which declared packet a chained enchanter effect emits, keyed by the kind
# of the packet that triggered it, and which sourced fraction that packet
# carries.  Two tables rather than one runtime-computed kind (D-50): the kind
# a producer emits has to be readable from the declaration, and the fraction
# it uses has to be readable from the kind.
_CHAIN_KINDS: Mapping[str, PacketKind] = MappingProxyType(
    {"heal": PacketKind.HEAL, "shield": PacketKind.SHIELD}
)

_CHAIN_FRACTION_KEYS: Mapping[PacketKind, str] = MappingProxyType(
    {
        PacketKind.HEAL: "heal_chain_fraction",
        PacketKind.SHIELD: "shield_chain_fraction",
    }
)


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


def _everlasting_trigger_kind(trigger: Trigger) -> str:
    """Which of Everlasting's two rungs a control trigger takes, if any.

    The shield fires on an immobilize, or on a slow for a melee holder, and
    the receipt records which.  A bare ``crowd_control`` marker —
    ``UNCLASSIFIED_CONTROL`` on the bus — says control happened without
    saying which rung it was, so it takes neither: an unnarrowed marker must
    not be promoted into a narrowed one.
    """
    if trigger.cc is CcClass.IMMOBILIZE:
        return "immobilize"
    if trigger.cc is CcClass.SLOW:
        return "slow"
    return ""


def _stack_triggers(triggers: Iterable[Trigger]) -> Iterator[Trigger]:
    """Non-reactive champion damage that landed on a named target.

    The bus emits a damage trigger for every authored row, because its
    consumers disagree about which damage matters and one that pre-filtered
    would have to pick a side.  This is the stack ledgers' own side — "a hit
    that stacked" — stated where the ledgers read it instead of inside the
    transport.
    """
    for trigger in triggers:
        if trigger.damage <= 0.0 or trigger.reactive or not trigger.target_id:
            continue
        yield trigger


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


def _target_by_id(all_actors: Iterable[Any], participant_id: str) -> Any | None:
    return next(
        (actor for actor in all_actors if actor.participant_id == participant_id), None
    )


def _selected_teammate(attacker: Any, teammates: list[Any], owner: str) -> Any | None:
    """The teammate the holder's scenario tethered, under *owner*'s options."""
    if not teammates:
        return None
    raw_index = _option(attacker, owner, "worthy_target_index", 0.0)
    index = max(0, min(len(teammates) - 1, int(raw_index)))
    return teammates[index]


def _starved_streams(names: Collection[str]) -> list[tuple[str, str]]:
    """Each held holder that reads a raw stream, paired with that stream.

    The holder-to-stream fact has exactly one home — every mechanic's
    declared ``reads`` in ``trigger_stream.CAPABILITIES`` — so this is a
    projection of the registry and not the second name list it replaced.
    The label is the raw ledger key the stream is parsed off, derived from
    the stream's own value rather than tabulated beside it.
    """
    return sorted(
        (item, f"{stream.value}_events")
        for item in frozenset(names) & tuple_incapable_items()
        for stream in streams_for(frozenset({item})) & RAW_STREAMS
    )


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
    consults ``tuple_incapable_items()`` no public request can reach this
    state, so the raise is a programming-error tripwire rather than a
    user-facing outcome.
    """
    if not result.get("damage_events_tuple"):
        return
    starved = _starved_streams(names)
    if not starved:
        return
    read = "; ".join(f"{item} reads {stream}" for item, stream in starved)
    raise EventViewStarvationError(
        "STARVED: the score-only tuple ledger cannot answer the item support "
        f"scan — {read}.  The pipeline's tuple gate must keep dict rows for "
        "every event-view holder."
    )


def _bus_streams(
    result: Mapping[str, Any], names: Collection[str]
) -> tuple[list[Trigger], list[Trigger], list[Trigger]]:
    """One engine result as the control, damage and takedown views of it.

    The compiler reads each stream once and the bus builds only the streams
    the held holders declare, so a holder reading none pays nothing — that
    laziness is the whole reason the migration is performance-neutral
    (D-30).  ``tuple_incapable_items()`` is exactly the set of holders that
    read a raw stream, so intersecting first also bounds the projection's
    cache key to those names rather than to every build the optimizer
    explores.
    """
    scanning = frozenset(names) & tuple_incapable_items()
    by_kind: dict[TriggerKind, list[Trigger]] = {kind: [] for kind in TriggerKind}
    for trigger in authored_triggers(
        result, streams=streams_for(scanning), holder=", ".join(sorted(scanning))
    ):
        by_kind[trigger.kind].append(trigger)
    return (
        by_kind[TriggerKind.CC],
        by_kind[TriggerKind.DAMAGE],
        by_kind[TriggerKind.TAKEDOWN],
    )


def _support_quest_packets(
    attacker: Any, shared_riches: AllyPacketSlot, ward: AllyPacketSlot
) -> list[dict[str, Any]]:
    """One support-quest item's authored economy and vision outcomes.

    World Atlas and Runic Compass carry the same quest, and the two outcomes
    — the gold and the ward — are two declared producers on the one record,
    because Phase 2 declares a capability and a packet source for each.  The
    item is whichever transformed stage the build equipped, read off the
    declarations rather than spelled: ``validate_resolved_loadout`` already
    refuses a build carrying two support quest items, and ``_producer``'s
    two-holder stop is that same rule restated where the packets are built.
    """
    packets: list[dict[str, Any]] = []
    quest_item = shared_riches.owner
    source_meta = ITEM_INPUT_OPTIONS[quest_item]
    gold = max(0.0, _option(attacker, quest_item, "shared_riches_gold"))
    gold_cap = shared_riches.value("support_quest_threshold")
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
        min(_option(attacker, quest_item, "ward_uses"), ward.value("ward_charges")),
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
    return packets


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
    cc_events, damage_events, takedown_events = _bus_streams(result, names)
    # The build's declared cross-participant producers, resolved once.  Every
    # migrated branch below asks this map whether the holder declares its
    # mechanic; the branches still spelling an item name are the producers
    # the remaining commits of 3.6 migrate.
    slots = resolve_slots(names)
    starlit_grace = _producer(slots, AllyProducer.STARLIT_GRACE)
    soul_siphon = _producer(slots, AllyProducer.SOUL_SIPHON)
    consonance = _producer(slots, AllyProducer.CONSONANCE)
    going_sledding = _producer(slots, AllyProducer.GOING_SLEDDING)
    sanctify = _producer(slots, AllyProducer.SANCTIFY)
    rapids = _producer(slots, AllyProducer.RAPIDS)
    fanfare = _producer(slots, AllyProducer.FANFARE)
    command = _producer(slots, AllyProducer.COMMAND)
    carve = _producer(slots, AllyProducer.CARVE)
    vile_decay = _producer(slots, AllyProducer.VILE_DECAY)
    blue_bubble = _producer(slots, AllyProducer.BLUE_BUBBLE)
    purple_bubble = _producer(slots, AllyProducer.PURPLE_BUBBLE)

    # Reap is a progression/economy branch, not a guessed combat bonus.  The
    # authored minion-kill count is bounded by its sourced 100-kill quest and
    # produces one inspectable gold receipt only after the caller supplies it.
    reap = _producer(slots, AllyProducer.REAP)
    if reap is not None:
        reap.declared(PacketKind.ECONOMY)
        minion_kills = max(0.0, _option(attacker, reap.owner, "reap_minion_kills"))
        cap = reap.value("reap_max_gold")
        per_minion = reap.value("reap_gold_per_minion")
        completion_gold = reap.value("reap_completion_gold")
        earned = min(minion_kills, cap) * per_minion
        if minion_kills >= cap:
            earned += completion_gold
        if earned > 0.0:
            source_meta = ITEM_INPUT_OPTIONS[reap.owner]
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
    rage = _producer(slots, AllyProducer.RAGE)
    if rage is not None:
        rage.declared(PacketKind.MOVEMENT)
        is_melee = bool(attacker.stats.get("is_melee", False))
        speed_key = (
            "rage_bonus_move_speed_melee"
            if is_melee
            else "rage_bonus_move_speed_ranged"
        )
        bonus_speed = rage.value(speed_key)
        duration = rage.value("rage_duration")
        source_meta = ITEM_INPUT_OPTIONS[rage.owner]
        for event in damage_events:
            if event.source_key != "auto_attacks" and not event.basic_attack:
                continue
            packets.append(
                _packet(
                    attacker=attacker,
                    target=attacker,
                    time=event.time,
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
    shared_riches = _producer(slots, AllyProducer.SHARED_RICHES)
    ward = _producer(slots, AllyProducer.WARD)
    if shared_riches is not None and ward is not None:
        shared_riches.declared(PacketKind.ECONOMY)
        ward.declared(PacketKind.VISION)
        packets.extend(_support_quest_packets(attacker, shared_riches, ward))

    # Fimbulwinter's Everlasting is a self shield that fires only from an
    # explicitly marked immobilize, or a slow for a melee holder.  Its
    # current-mana threshold and cooldown are resolved from the same ordered
    # cast receipt that drives resource admission; no cast or crowd-control
    # state is inferred from a spell name.
    everlasting = _producer(slots, AllyProducer.EVERLASTING)
    if everlasting is not None:
        everlasting.declared(PacketKind.SHIELD)
        is_melee = bool(attacker.stats.get("is_melee", False))
        champion_stats = result.get("champion_stats", attacker.stats)
        if not isinstance(champion_stats, Mapping):
            champion_stats = attacker.stats
        maximum_mana = max(
            0.0,
            float(champion_stats.get("max_mana", attacker.stats.get("max_mana", 0.0))),
        )
        mana_threshold_ratio = everlasting.value("everlasting_mana_threshold_ratio")
        nearby_enemy_count = sum(
            1 for actor in all_actors if not _same_side(attacker, actor)
        )
        cooldown = everlasting.value("everlasting_cooldown")
        last_activation = float("-inf")
        seen_casts: set[str] = set()
        source_meta = ITEM_INPUT_OPTIONS[everlasting.owner]
        for event in cc_events:
            trigger_kind = _everlasting_trigger_kind(event)
            if not trigger_kind or (trigger_kind == "slow" and not is_melee):
                continue
            time = event.time
            cast_identity = (
                event.ability_instance or f"{event.source_key}:{round(time, 9)}"
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
                everlasting.value("everlasting_multi_target_multiplier")
                if nearby_enemy_count > 1
                else 1.0
            )
            amount = (
                everlasting.value("everlasting_base_shield")
                + current_mana * everlasting.value("everlasting_current_mana_ratio")
            ) * multiplier
            packets.append(
                _packet(
                    attacker=attacker,
                    target=attacker,
                    time=time,
                    kind="shield",
                    source="Fimbulwinter — Everlasting",
                    amount=amount,
                    duration=everlasting.value("everlasting_duration"),
                    target_scope="self",
                    trigger=trigger_kind,
                    # ``None`` when the producer did not enrich: the survival
                    # compiler's fail-closed ``support_trigger_link`` branch
                    # keys on ``is not None``, so an unenriched shield must
                    # carry an absent link and not an empty one (D-03).
                    _trigger_event_id=event.event_id or None,
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
    unmake = _producer(slots, AllyProducer.UNMAKE)
    if unmake is not None:
        unmake.declared(PacketKind.DAMAGE_MODIFIER)
        curse = unmake.value("magic_damage_amp")
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
                    amount=curse,
                    multiplier=1.0 + curse,
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

    expose_weakness = _producer(slots, AllyProducer.EXPOSE_WEAKNESS)
    if expose_weakness is not None:
        expose_weakness.declared(PacketKind.DAMAGE_MODIFIER)
        expose_key = (
            "expose_weakness_melee"
            if bool(attacker.stats.get("is_melee", False))
            else "expose_weakness_ranged"
        )
        # The spellblade breakdown key is built from the item's own name
        # (``item_effects``), so the row this producer answers to is derived
        # from the declaration's owner rather than spelled a second time.
        spellblade_key = f"spellblade_{expose_weakness.owner}"
        for event in _stack_triggers(damage_events):
            if event.source_key != spellblade_key:
                continue
            target = _target_by_id(all_actors, event.target_id)
            if target is None:
                continue
            rate = expose_weakness.value(expose_key)
            packets.append(
                _packet(
                    attacker=attacker,
                    target=target,
                    time=event.time,
                    kind="damage_modifier",
                    source="Bloodsong — Expose Weakness",
                    amount=rate,
                    duration=expose_weakness.value("expose_weakness_duration"),
                    multiplier=1.0 + rate,
                    all_sources=True,
                    cooldown=expose_weakness.value("expose_weakness_cooldown"),
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
                    trigger_event_id=event.event_id or None,
                )
            )

    reduction_stacks: dict[tuple[str, str], int] = {}
    # Both ledgers walk one stream; the guard is hoisted so a holder of
    # neither never walks it at all, which is what the hand-maintained
    # damage-trigger name set bought before the registry existed.
    if carve is not None or vile_decay is not None:
        for event in _stack_triggers(damage_events):
            target = _target_by_id(all_actors, event.target_id)
            if target is None:
                continue
            damage_type = event.damage_type
            source_id = event.event_id
            if carve is not None and damage_type == "physical":
                key = (target.participant_id, "armor")
                stacks = min(
                    int(carve.value("armor_reduction_max_stacks")),
                    reduction_stacks.get(key, 0) + 1,
                )
                reduction_stacks[key] = stacks
                percent = stacks * carve.value("armor_reduction_per_stack")
                packets.append(
                    _packet(
                        attacker=attacker,
                        target=target,
                        time=event.time,
                        kind="damage_modifier",
                        source="Black Cleaver — Carve",
                        amount=percent,
                        duration=carve.value("armor_reduction_duration"),
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
                        trigger_event_id=source_id,
                        stack_count=stacks,
                    )
                )
            if vile_decay is not None and damage_type == "magic" and event.is_ability:
                key = (target.participant_id, "mr")
                stacks = min(
                    int(vile_decay.value("mr_reduction_max_stacks")),
                    reduction_stacks.get(key, 0) + 1,
                )
                reduction_stacks[key] = stacks
                percent = stacks * vile_decay.value("mr_reduction_per_stack")
                packets.append(
                    _packet(
                        attacker=attacker,
                        target=target,
                        time=event.time,
                        kind="damage_modifier",
                        source="Bloodletter's Curse — Vile Decay",
                        amount=percent,
                        duration=vile_decay.value("mr_reduction_duration"),
                        mr_reduction_percent=percent,
                        resistance_type="magic_resistance",
                        # "magic resistance reduction": the mirror of Carve.
                        damage_classes=frozenset({DamageClass.MAGIC}),
                        attack_classes=frozenset(AttackClass),
                        # Vile Decay is Carve's shape, magic- and ability-gated,
                        # and is H1-blocked with it.
                        authority=Authority.SPLIT,
                        owner=attacker.participant_id,
                        trigger_event_id=source_id,
                        stack_count=stacks,
                    )
                )

    # The holder guard sat *inside* the loop as a ``break``, which reads as a
    # loop condition and is really a name guard — the one shape the capability
    # projections cannot see.  Same packets, same order.
    nova = _producer(slots, AllyProducer.LIFE_FROM_DEATH)
    if nova is not None:
        nova.declared(PacketKind.HEAL)
        for takedown in takedown_events:
            amount = nova.value("life_from_death_base_heal") + (
                float(attacker.stats.get("ability_power", 0.0) or 0.0)
                * nova.value("life_from_death_ap_ratio")
            )
            for recipient in (attacker, *teammates):
                packets.append(
                    _packet(
                        attacker=attacker,
                        target=recipient,
                        time=takedown.time,
                        kind="heal",
                        source="Cryptbloom — Life From Death",
                        amount=amount,
                        duration=nova.value("life_from_death_nova_duration"),
                        target_scope="nova_allied_champions",
                        trigger="explicit_takedown_within_damage_window",
                        cooldown=nova.value("life_from_death_cooldown"),
                    )
                )

    # Triggered enchanter passives.  The target is carried by the authored
    # champion packet; no cursor or radius is guessed.
    for trigger in triggers:
        target = _target_by_id(all_actors, str(trigger.get("target", "")))
        if target is None:
            continue
        time = _event_time(trigger)
        if sanctify is not None:
            packets.extend(
                (
                    _packet(
                        attacker=attacker,
                        target=recipient,
                        time=time,
                        kind="stat_buff",
                        source="Ardent Censer — Sanctify",
                        amount=sanctify.value("sanctify_bonus_attack_speed"),
                        duration=sanctify.value("sanctify_duration"),
                        bonus_attack_speed_percent=sanctify.value(
                            "sanctify_bonus_attack_speed"
                        ),
                        on_hit_magic_damage=sanctify.value("sanctify_on_hit_magic"),
                        recipient_role="holder_and_healed_ally",
                    )
                    for recipient in (attacker, target)
                )
            )
        if rapids is not None:
            packets.extend(
                (
                    _packet(
                        attacker=attacker,
                        target=recipient,
                        time=time,
                        kind="stat_buff",
                        source="Staff of Flowing Water — Rapids",
                        amount=rapids.value("bonus_ability_power"),
                        duration=rapids.value("duration"),
                        ability_power=rapids.value("bonus_ability_power"),
                        ability_haste=rapids.value("bonus_ability_haste"),
                        recipient_role="holder_and_healed_ally",
                    )
                    for recipient in (attacker, target)
                )
            )
        if starlit_grace is not None:
            candidates = [
                actor
                for actor in teammates
                if actor.participant_id != target.participant_id
            ]
            chain_target = candidates[0] if candidates else target
            # D-50: the chained packet's kind used to be computed from the
            # trigger at runtime, which no static reader could resolve — not
            # Phase 1's ``PacketSource``, not a family assignment.  Starlit
            # Grace declares *two* packets instead, one per kind it chains,
            # and the trigger selects between them.  A third kind is a stop
            # rather than a packet nothing declared; ``_support_triggers``
            # admits only heal and shield, so no live trigger can reach it.
            chained = _CHAIN_KINDS[str(trigger.get("kind", "shield"))]
            starlit_grace.declared(chained)
            fraction = starlit_grace.value(_CHAIN_FRACTION_KEYS[chained])
            packets.append(
                _packet(
                    attacker=attacker,
                    target=chain_target,
                    time=time,
                    kind=chained.value,
                    source="Moonstone Renewer — Starlit Grace",
                    amount=float(trigger.get("amount", 0.0)) * fraction,
                    duration=float(trigger.get("duration", 0.0) or 0.0),
                    target_scope="other_nearest_wounded_ally",
                    chain_fraction=fraction,
                )
            )
        if blue_bubble is not None and purple_bubble is not None:
            packets.extend(
                (
                    _packet(
                        attacker=attacker,
                        target=target,
                        time=time,
                        kind="damage_modifier",
                        source="Dream Maker — Blue Dream Bubble",
                        amount=blue_bubble.level_value(
                            "blue_reduction_min", target.level
                        ),
                        duration=blue_bubble.value("dream_duration"),
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
                        amount=purple_bubble.level_value(
                            "purple_magic_min", target.level
                        ),
                        duration=purple_bubble.value("dream_duration"),
                        next_event_only=True,
                    ),
                )
            )
        if soul_siphon is not None:
            # Soul Charges read every authored row's raw number, so this
            # branch reads the damage stream whole rather than the stack
            # ledgers' filtered view — and reads it off the bus, where a row
            # that is not a Mapping cannot reach a ``.get`` at all.  That
            # missing guard is what made a tuple ledger an AttributeError
            # here and a silent zero everywhere else.
            soul_siphon.declared(PacketKind.HEAL)
            raw_damage = sum(
                event.raw_damage or event.damage for event in damage_events
            )
            cap = soul_siphon.level_value("charge_cap_min", target.level)
            charges = min(cap, raw_damage * soul_siphon.value("charge_damage_ratio"))
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
        if consonance is not None:
            consonance.declared(PacketKind.HEAL)
            wounded = target
            packets.append(
                _packet(
                    attacker=attacker,
                    target=wounded,
                    time=time,
                    kind="heal",
                    source="Diadem of Songs — Consonance",
                    amount=float(attacker.stats.get("mana", 0.0))
                    * consonance.value("consonance_max_mana_ratio"),
                    target_scope="nearest_most_wounded_ally",
                    cooldown=consonance.value("consonance_cooldown"),
                )
            )

    # A hard-CC marker is required for the passives below.  If the reviewed
    # champion module does not emit one, the effect is intentionally absent;
    # callers must not turn an arbitrary cast boundary into a slow/root.
    for cc in cc_events:
        time = cc.time
        if fanfare is not None:
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
                    amount=fanfare.value("fanfare_bonus_move_speed"),
                    duration=fanfare.value(duration_key),
                    bonus_move_speed_percent=fanfare.value("fanfare_bonus_move_speed"),
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
                        amount=fanfare.value(as_key),
                        duration=fanfare.value(duration_key),
                        bonus_attack_speed_percent=fanfare.value(as_key),
                        trigger="authored_immobilize_or_slow",
                    )
                )
        if going_sledding is not None and teammates:
            going_sledding.declared(PacketKind.TEMPORARY_HEALTH)
            target = teammates[0]
            for recipient in (attacker, target):
                packets.append(
                    _packet(
                        attacker=attacker,
                        target=recipient,
                        time=time,
                        kind="temporary_health",
                        source="Solstice Sleigh — Going Sledding",
                        amount=going_sledding.level_value(
                            "temporary_health_min", recipient.level
                        ),
                        duration=going_sledding.value("duration"),
                        bonus_move_speed_percent=going_sledding.value(
                            "bonus_move_speed_percent"
                        ),
                        cooldown=going_sledding.value("cooldown"),
                        target_scope=(
                            "self" if recipient is attacker else "most_wounded_ally"
                        ),
                    )
                )
        if command is not None and cc.cc is CcClass.IMMOBILIZE:
            target = _target_by_id(all_actors, cc.target_id)
            if target is not None:
                amp = command.value("command_damage_amp")
                packets.append(
                    _packet(
                        attacker=attacker,
                        target=target,
                        time=time,
                        kind="damage_modifier",
                        source="Imperial Mandate — Command",
                        amount=amp,
                        duration=command.value("command_duration"),
                        multiplier=1.0 + amp,
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
    devotion = _producer(slots, AllyProducer.DEVOTION)
    active_time = _active_seconds(attacker, devotion)
    if devotion is not None and active_time > 0.0:
        devotion.declared(PacketKind.SHIELD)
        for target in (attacker, *teammates):
            packets.append(
                _packet(
                    attacker=attacker,
                    target=target,
                    time=active_time,
                    kind="shield",
                    source="Locket of the Iron Solari — Devotion",
                    amount=devotion.level_value("shield_min", target.level),
                    duration=devotion.value("shield_duration"),
                    target_scope="all_selected_teammates",
                )
            )
    purify = _producer(slots, AllyProducer.PURIFY)
    active_time = _active_seconds(attacker, purify)
    if purify is not None and active_time > 0.0 and teammates:
        purify.declared(PacketKind.HEAL)
        target = teammates[0]
        packets.append(
            _packet(
                attacker=attacker,
                target=target,
                time=active_time,
                kind="heal",
                source="Mikael's Blessing — Purify",
                amount=purify.level_value("heal_min", target.level),
                target_scope="explicit_selected_ally",
                cleanse=True,
            )
        )
    intervention = _producer(slots, AllyProducer.INTERVENTION)
    active_time = _active_seconds(attacker, intervention)
    if intervention is not None and active_time > 0.0:
        intervention.declared(PacketKind.HEAL)
        beam_delay = intervention.value("beam_delay")
        range_units = intervention.value("target_area_range_units")
        for target in (attacker, *teammates):
            packets.append(
                _packet(
                    attacker=attacker,
                    target=target,
                    time=active_time + beam_delay,
                    kind="heal",
                    source="Redemption — Intervention",
                    amount=intervention.level_value("heal_min", target.level),
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
        #
        # D-50: one active, one ``source=`` literal, two packets landing on two
        # different roster classes.  ``secondary_target`` is what says the
        # second half exists — a reader of the declaration alone could
        # otherwise not tell that Intervention damages anybody.
        intervention.declared(PacketKind.DAMAGE)
        true_damage_ratio = intervention.value("enemy_max_health_true_damage_ratio")
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
    inspiring_speech = _producer(slots, AllyProducer.INSPIRING_SPEECH)
    active_time = _active_seconds(attacker, inspiring_speech)
    if inspiring_speech is not None and active_time > 0.0:
        inspiring_speech.declared(PacketKind.MOVEMENT)
        for target in (attacker, *teammates):
            packets.append(
                _packet(
                    attacker=attacker,
                    target=target,
                    time=active_time,
                    kind="movement",
                    source="Shurelya's Battlesong — Inspiring Speech",
                    amount=inspiring_speech.value("bonus_move_speed_percent"),
                    duration=inspiring_speech.value("duration"),
                    bonus_move_speed_percent=inspiring_speech.value(
                        "bonus_move_speed_percent"
                    ),
                    target_scope="all_selected_teammates",
                )
            )
    shockwave = _producer(slots, AllyProducer.BREAKING_SHOCKWAVE)
    active_time = _active_seconds(attacker, shockwave)
    if shockwave is not None and active_time > 0.0:
        shockwave.declared(PacketKind.SLOW)
        shockwave.declared(PacketKind.MOVEMENT)
        slow_percent = shockwave.value("slow_percent")
        slow_duration = shockwave.value("slow_duration")
        move_speed_percent = shockwave.value("bonus_move_speed_percent")
        move_speed_duration = shockwave.value("bonus_move_speed_duration")
        area_radius = shockwave.value("area_radius")
        front_offset = shockwave.value("front_offset")
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
        sacrifice = _producer(
            resolve_slots(_item_names(holder)), AllyProducer.SACRIFICE
        )
        if sacrifice is None:
            continue
        sacrifice.declared(PacketKind.HEAL)
        teammates = _teammates(holder, all_actors)
        target = _selected_teammate(holder, teammates, sacrifice.owner)
        if target is None:
            continue
        fraction = sacrifice.value("redirect_fraction")
        heal_fraction = sacrifice.value("holder_heal_fraction")
        within_range = _option(holder, sacrifice.owner, "worthy_within_range", 1.0)
        holder_health_ready = _option(
            holder, sacrifice.owner, "holder_above_30_percent", 1.0
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
            event["redirect_holder_health_ratio"] = sacrifice.value(
                "holder_health_threshold_ratio"
            )
            event["redirect_range_units"] = sacrifice.value("worthy_range_units")
            event["redirect_source_revision_id"] = int(
                sacrifice.value("source_revision_id")
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
                    requires_holder_health_ratio=sacrifice.value(
                        "holder_health_threshold_ratio"
                    ),
                    range_units=sacrifice.value("worthy_range_units"),
                    source_revision_id=int(sacrifice.value("source_revision_id")),
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
# There is exactly one authority table in the repo and it is
# ``trigger_stream.CAPABILITIES``.  This module used to derive a second one
# by reading its own ``_packet(...)`` call sites with ``ast``; two tables
# that agree today are two tables that can disagree tomorrow, which is the
# whole thesis of the campaign, so the derivation below reads the registry
# and the call sites are bound to it by the check underneath.  A seventh
# producer therefore fails to resolve — loudly, on its first packet — until
# it is declared, and the same registry is what the coupled golden baseline
# reads to prove its scenario set covers every producer (runbook R-12).


@lru_cache(maxsize=1)
def _declared_authorities() -> Mapping[str, Authority]:
    """Every declared cross-participant packet source and its owning engine.

    The key is the walk packet's ``source`` literal — ``packet_source`` on
    the capability — and the value the ``Authority`` that capability
    declares.  ``CROSS_PARTICIPANT_AUTHORITIES`` is the bus's own reading of
    which members mean "a second engine can see this mechanic", so the three
    members are named there and nowhere else.

    Cached because ``_packet`` consults it on every cross-participant packet
    it builds and the stack-ledger producers build one per damage event.
    """
    return MappingProxyType(
        {
            capability.packet_source: capability.authority
            for capability in sorted(
                CAPABILITIES.values(), key=lambda cap: cap.mechanic
            )
            if capability.engine is Engine.WALK
            and capability.authority in CROSS_PARTICIPANT_AUTHORITIES
            and capability.packet_source is not None
        }
    )


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

    This is also where a call site is bound to the registry: the packet is
    built with an ``authority=`` argument and it must be the one
    ``CAPABILITIES`` declares for that ``packet_source``, so the declaration
    and the construction cannot drift without a raise naming both.
    """
    declared = _declared_authorities().get(source)
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
    "derive_item_support_effects",
    "has_ordered_item_team_effects",
    "producer_item",
    "require_event_view",
    "schedule_knights_vow",
]
