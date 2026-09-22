"""Typed, timestamped ally/team item packets for the participant ledger.

The ordinary item compiler owns damage emitted by the holder.  This module
owns the other side of the same Wiki entries: ally shields/heals, temporary
health, stat buffs, all-source debuffs, and explicit item-actives.  It never
assumes an active or a trigger that is absent from the authored event stream.

What stays here is the dispatch: four tables keyed by
:class:`~.item_behavior.AllyProducer`, the walks over them, and the two entry
points ``participant_timeline`` calls.  One block per producer lives beside
it, in ``item_support_quests``, ``item_support_everlasting``,
``item_support_shred``, ``item_support_triggered`` and
``item_support_actives``; the inputs every block reads are ``support_context``.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from enum import Enum
from typing import Any

from .ally_packet_shape import _item_names, _packet, _producer, _same_side
from .interpreters.ally_packet import resolve_slots

# The declarations.  A producer is reached through the rule its registry
# entry declares — "does this holder declare Everlasting?" — rather than by
# spelling the item that has it, so a key no declaration carries is a stop
# instead of a silent registry read.
from .item_behavior import AllyProducer

# One block per declared producer, grouped by what arms it.
from .item_support_actives import (
    _devotion_packets,
    _inspiring_speech_packets,
    _intervention_packets,
    _purify_packets,
    _self_cleanse_packets,
    _shockwave_packets,
)
from .item_support_everlasting import _everlasting_packets
from .item_support_quests import (
    _manaflow_packets,
    _nightstalker_packets,
    _quest_packets,
    _rage_packets,
    _reap_packets,
)
from .item_support_shred import (
    _expose_weakness_packets,
    _resistance_shred_packets,
    _unmake_packets,
)
from .item_support_triggered import (
    _command_packets,
    _consonance_packets,
    _dream_bubble_packets,
    _fanfare_packets,
    _going_sledding_packets,
    _life_from_death_packets,
    _rapids_packets,
    _sanctify_packets,
    _soul_siphon_packets,
    _starlit_grace_packets,
)
from .roster_composition import Combatant
from .support_context import SupportCtx, _context, _ControlMoment, _TriggerMoment
from .support_event_view import _target_by_id, resolve_knights_vow_tether

# The item layer's one edge into the survival kernel: packet authors declare
# when their packet arms, in the walk's vocabulary, so there is no second
# ordering language to keep in sync.  Note the reach — importing
# ``.survival.actions`` executes ``survival/__init__.py``, so the whole kernel
# package loads with this module.  Acyclic: nothing under ``survival/``
# imports ``item_support_effects``.
from .survival.actions import event_timestamp


class _Projection(Enum):
    """A block no ally-packet declaration arms, and what arms it instead.

    Manaflow is a projection of the typed mana ledger, whose section names
    its own holder.  The self-cast cleanses are driven by the cleanse
    registry: ``ALLY_ENTRY_SHAPES`` identifies a producer by its
    ``ITEM_EFFECTS`` value keys, and Quicksilver Sash carries no such record
    because its active has no numbers.
    """

    MANAFLOW = "manaflow"
    SELF_CLEANSE = "self_cleanse"


_FightBuild = Callable[[SupportCtx], list[dict[str, Any]]]
_TriggerBuild = Callable[[_TriggerMoment], list[dict[str, Any]]]
_ControlBuild = Callable[[_ControlMoment], list[dict[str, Any]]]


# What the fight's own opening state arms, in the order the ledger takes it.
# A block two producers share is registered under both their keys, and the
# walks run the distinct blocks rather than the keys.
_FIGHT_PACKETS: Mapping[AllyProducer | _Projection, _FightBuild] = {
    AllyProducer.REAP: _reap_packets,
    AllyProducer.RAGE: _rage_packets,
    AllyProducer.SHARED_RICHES: _quest_packets,
    AllyProducer.WARD: _quest_packets,
    _Projection.MANAFLOW: _manaflow_packets,
    AllyProducer.NIGHTSTALKER: _nightstalker_packets,
    AllyProducer.EVERLASTING: _everlasting_packets,
    AllyProducer.UNMAKE: _unmake_packets,
    AllyProducer.EXPOSE_WEAKNESS: _expose_weakness_packets,
    AllyProducer.CARVE: _resistance_shred_packets,
    AllyProducer.VILE_DECAY: _resistance_shred_packets,
    AllyProducer.LIFE_FROM_DEATH: _life_from_death_packets,
}

# The enchanter passives an authored heal or shield on an ally arms.  The
# target is carried by that authored packet; no cursor or radius is guessed.
_TRIGGER_PACKETS: Mapping[AllyProducer, _TriggerBuild] = {
    AllyProducer.SANCTIFY: _sanctify_packets,
    AllyProducer.RAPIDS: _rapids_packets,
    AllyProducer.STARLIT_GRACE: _starlit_grace_packets,
    AllyProducer.BLUE_BUBBLE: _dream_bubble_packets,
    AllyProducer.PURPLE_BUBBLE: _dream_bubble_packets,
    AllyProducer.SOUL_SIPHON: _soul_siphon_packets,
    AllyProducer.CONSONANCE: _consonance_packets,
}

# What an authored hard-CC marker arms.  If the reviewed champion module emits
# none, the effect is intentionally absent: no arbitrary cast boundary becomes
# a slow or a root.
_CONTROL_PACKETS: Mapping[AllyProducer, _ControlBuild] = {
    AllyProducer.FANFARE: _fanfare_packets,
    AllyProducer.GOING_SLEDDING: _going_sledding_packets,
    AllyProducer.COMMAND: _command_packets,
}

# The explicit item-actives.  A non-zero authored timestamp is the complete
# trigger contract, so none of these is emitted at t=0 by default.
_ACTIVE_PACKETS: Mapping[AllyProducer | _Projection, _FightBuild] = {
    AllyProducer.DEVOTION: _devotion_packets,
    AllyProducer.PURIFY: _purify_packets,
    _Projection.SELF_CLEANSE: _self_cleanse_packets,
    AllyProducer.INTERVENTION: _intervention_packets,
    AllyProducer.INSPIRING_SPEECH: _inspiring_speech_packets,
    AllyProducer.BREAKING_SHOCKWAVE: _shockwave_packets,
}

PRODUCER_TABLES = (
    _FIGHT_PACKETS,
    _TRIGGER_PACKETS,
    _CONTROL_PACKETS,
    _ACTIVE_PACKETS,
)

# Knight's Vow's Sacrifice is the one declared producer no table names: it is
# a tether ``schedule_knights_vow`` attaches to a built timeline, not a packet
# this compiler appends.
_SCHEDULED_ELSEWHERE = frozenset({AllyProducer.SACRIFICE})

# Soul Charges are one stored pool, consumed by the first qualifying heal or
# shield: the trigger that spends it is the last trigger the walk reads, so no
# later trigger duplicates the same pool.
_POOL_CONSUMING_BLOCKS = frozenset({_soul_siphon_packets})


def _validate_producer_tables(
    tables: Iterable[Mapping[AllyProducer | _Projection, Any]],
) -> None:
    """Every declared ally producer takes exactly one block in *tables*."""
    keyed = Counter(
        key for table in tables for key in table if isinstance(key, AllyProducer)
    )
    wrong = {
        mechanic.value: keyed[mechanic]
        for mechanic in AllyProducer
        if keyed[mechanic] != (0 if mechanic in _SCHEDULED_ELSEWHERE else 1)
    }
    if wrong:
        raise ValueError(
            "every declared ally producer takes exactly one block in the "
            f"tables above, and these take another count: {wrong}"
        )


_validate_producer_tables(PRODUCER_TABLES)


def _blocks[T](table: Mapping[Any, T]) -> tuple[T, ...]:
    """The table's distinct blocks, in the order it first names them."""
    return tuple(dict.fromkeys(table.values()))


def _emit(
    ctx: SupportCtx, table: Mapping[AllyProducer | _Projection, _FightBuild]
) -> list[dict[str, Any]]:
    """Every block of *table*, run once each, in the order the table states."""
    return [packet for build in _blocks(table) for packet in build(ctx)]


def _trigger_packets(ctx: SupportCtx) -> list[dict[str, Any]]:
    """Every grant the authored heal and shield triggers arm.

    One whole pass of the table per trigger, because the grants one trigger
    arms are consecutive in the ledger, and the trigger that spends the stored
    Soul Charge pool is the last one read.
    """
    packets: list[dict[str, Any]] = []
    builds = _blocks(_TRIGGER_PACKETS)
    for trigger in ctx.triggers:
        target = _target_by_id(ctx.all_actors, str(trigger.get("target", "")))
        if target is None:
            continue
        moment = _TriggerMoment(ctx, trigger, target, event_timestamp(trigger))
        for build in builds:
            emitted = build(moment)
            packets.extend(emitted)
            if emitted and build in _POOL_CONSUMING_BLOCKS:
                return packets
    return packets


def _control_packets(ctx: SupportCtx) -> list[dict[str, Any]]:
    """Every grant an authored crowd-control mark arms."""
    packets: list[dict[str, Any]] = []
    builds = _blocks(_CONTROL_PACKETS)
    for cc in ctx.cc_events:
        moment = _ControlMoment(ctx, cc, cc.time)
        for build in builds:
            packets.extend(build(moment))
    return packets


def derive_item_support_effects(
    attacker: Combatant,
    result: Mapping[str, Any],
    all_actors: list[Combatant],
    trigger_effects: Iterable[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    """Compile the holder's explicit cross-participant item packets.

    Four tables in one order: what the fight's opening state arms, what an
    authored heal or shield arms, what an authored control mark arms, and what
    an explicit active arms.  That order is the order the packets enter the
    participant ledger.
    """
    if attacker.team == "ally" and not getattr(
        getattr(attacker, "request", None), "ally_effects_enabled", False
    ):
        return []
    ctx = _context(attacker, result, all_actors, trigger_effects)
    return [
        *_emit(ctx, _FIGHT_PACKETS),
        *_trigger_packets(ctx),
        *_control_packets(ctx),
        *_emit(ctx, _ACTIVE_PACKETS),
    ]


def schedule_knights_vow(
    all_actors: list[Combatant],
    incoming: Mapping[str, list[dict[str, Any]]],
    outgoing: Mapping[str, list[dict[str, Any]]],
    support_effects: Mapping[str, list[dict[str, Any]]],
) -> None:
    """Attach one deterministic Worthy tether and redirect/heal receipts."""
    for holder in all_actors:
        # The declaration guard, stated here rather than left to the shared
        # resolver: this is the impl a Knight's Vow capability names, and
        # ``resolve_knights_vow_tether`` answers ``None`` for three different
        # reasons — no producer, no eligible ally, no authored selection
        # — so folding them would hide which one a build tripped.
        if (
            _producer(resolve_slots(_item_names(holder)), AllyProducer.SACRIFICE)
            is None
        ):
            continue
        tether = resolve_knights_vow_tether(holder, all_actors)
        if tether is None:
            continue
        target = tether["target"]
        fraction = tether["redirect_fraction"]
        heal_fraction = tether["heal_fraction"]
        within_range = tether["within_range"]
        holder_health_ready = tether["holder_health_ready"]
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
            event["redirect_holder_health_ratio"] = tether["threshold"]
            event["redirect_range_units"] = tether["range_units"]
            event["redirect_source_revision_id"] = tether["source_revision_id"]
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
                    time=event_timestamp(event),
                    kind="heal",
                    source="Knight's Vow — Sacrifice",
                    amount=amount * heal_fraction,
                    target_scope="holder_from_worthy_damage",
                    healing_category="knights_vow",
                    requires_holder_health_ratio=tether["threshold"],
                    range_units=tether["range_units"],
                    source_revision_id=tether["source_revision_id"],
                )
            )


# ---------------------------------------------------------------------------
# Cross-participant producers
# ---------------------------------------------------------------------------
#
# A ``damage_modifier`` packet changes how much damage some *other*
# participant deals or takes, so every one of them has to answer "which
# engine owns this mechanic" with the ``ability_spec.Authority`` member the
# packet itself carries.  Every block the tables above name, and
# ``schedule_knights_vow`` here, builds its packets through
# ``ally_packet_shape._packet``, which resolves that member against
# ``trigger_stream.CAPABILITIES`` and stops on a producer no capability
# declares.  That one table is also what the coupled golden baseline reads
# to prove its scenario set covers every producer.


__all__ = ["derive_item_support_effects", "schedule_knights_vow"]
