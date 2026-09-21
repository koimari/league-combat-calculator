"""Fimbulwinter's self shield, and a named receipt for every denial."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .ally_packet_shape import _MISSING, _packet
from .item_behavior import AllyProducer, PacketKind
from .item_effects import (
    AUTHORIZED_MANA_GATE_STATUSES,
    ITEM_INPUT_OPTIONS,
    fimbulwinter_mana_gate_authority,
    fimbulwinter_nearby_enemy_range_authority,
)
from .spatial import SPATIAL_UNAVAILABLE, enemies_within_range
from .state_lifecycle import CooldownRule, CooldownState, InstanceCadence
from .state_timeline import EventStamp, SourceReceipt
from .support_context import SupportCtx
from .support_event_view import _cc_event_stream, _current_mana_at, _mana_input
from .survival.actions import event_timestamp
from .survival.phases import TransitionRank


def _everlasting_packets(ctx: SupportCtx) -> list[dict[str, Any]]:
    """Fimbulwinter's self shield, and a named receipt for every denial.

    The shield fires only from an explicitly marked immobilize, or a slow for
    a melee holder.  Its trigger predicate, per-cast-instance cadence and
    cooldown are kernel-owned (``state_lifecycle``); the mana gate and the
    shield pricing are here.  No cast or crowd-control state is inferred from
    a spell name, and every denial is a named ``item_denial`` receipt so a
    silent skip can never hide an unreviewed or ambiguous trigger.
    """
    everlasting = ctx.producer(AllyProducer.EVERLASTING)
    if everlasting is None:
        return []
    attacker = ctx.attacker
    result = ctx.result
    all_actors = ctx.all_actors
    packets: list[dict[str, Any]] = []
    everlasting.declared(PacketKind.SHIELD)
    arming = everlasting.control_arming
    # The kernel's trigger rule reads the raw event rows, not the bus's
    # typed ``Trigger`` view: a denial receipt names the row's own
    # ``_event_id``, ``cc_kind`` and cast instance, and the bus does not
    # carry the unclassified rows a denial exists to report.
    # Candidacy is the MECHANIC's question, so its own kernel rule answers
    # it: SURVIVAL-API D-08 rules that "applies crowd control" (the bus's
    # ``applies_control``, the wider sibling used by Cheap Shot and
    # friends) and "blocks actions" (this trigger) are two different
    # questions, and they disagree on ``polymorph`` and ``silence``.
    # Filtering on the bus predicate would drop rows Everlasting's own
    # declaration accepts.
    everlasting_events = [
        event for event in _cc_event_stream(result) if arming.is_candidate(event)
    ]
    is_melee = bool(attacker.stats.get("is_melee", False))
    champion_stats = result.get("champion_stats", attacker.stats)
    if not isinstance(champion_stats, Mapping):
        champion_stats = attacker.stats
    raw_maximum_mana = champion_stats.get(
        "max_mana", attacker.stats.get("max_mana", _MISSING)
    )
    maximum_mana, maximum_mana_reason = _mana_input(
        raw_maximum_mana,
        missing_reason="missing_maximum_mana",
        invalid_reason="invalid_maximum_mana",
    )
    raw_current_mana = attacker.stats.get("mana", _MISSING)
    mana_gate = fimbulwinter_mana_gate_authority()
    range_authority = fimbulwinter_nearby_enemy_range_authority()
    holder_identity = getattr(attacker, "participant_id", None)
    source_meta = ITEM_INPUT_OPTIONS[everlasting.owner]

    def _denial(
        event: Mapping[str, Any], reason: str, **details: Any
    ) -> dict[str, Any]:
        """One named fail-closed receipt for a denied Everlasting trigger.

        Receipts are NOT applied packets: consumers of the applied
        support stream filter ``kind == "item_denial"`` (the participant
        timeline splits them into the public denial-receipt section).
        """
        return _packet(
            attacker=attacker,
            target=attacker,
            time=event_timestamp(event),
            kind=PacketKind.ITEM_DENIAL.value,
            source="Fimbulwinter — Everlasting",
            target_scope="self",
            reason=reason,
            cc_kind=str(event.get("cc_kind", "") or ""),
            event_id=event.get("_event_id"),
            trigger_rule=arming.public_receipt(),
            mana_gate_status=mana_gate["status"],
            nearby_enemy_range_units=range_authority["range_units"],
            range_center=(
                holder_identity
                if isinstance(holder_identity, str) and holder_identity.strip()
                else None
            ),
            range_input_status=range_authority["spatial_input_status"],
            source_url=source_meta["source_url"],
            source_revision_id=source_meta["source_revision_id"],
            rank=TransitionRank.DAMAGE,
            **details,
        )

    if not isinstance(holder_identity, str) or not holder_identity.strip():
        packets.extend(
            _denial(event, "missing_holder_identity")
            for event in everlasting_events
            if arming.match(event, is_melee=is_melee)
        )
        everlasting_events = []

    # Ambiguous / unknown / ranged-slow metadata: every CC-adjacent
    # event (damage-attached or control-only) that cannot match a branch
    # is receipted once (an event with NO CC metadata is not a candidate
    # and produces nothing).
    for event in _cc_event_stream(result):
        reason = arming.denial_reason(event, is_melee=is_melee)
        if reason:
            packets.append(_denial(event, reason))

    cooldown_rule = CooldownRule(
        name="Fimbulwinter — Everlasting",
        cooldown_seconds=float(everlasting.value("everlasting_cooldown")),
        per_target=False,
        source=SourceReceipt.from_mapping(source_meta),
    )
    cooldown_state = CooldownState(cooldown_rule)
    # One shield per cast instance: a multi-part cast that carries
    # several CC-marked events still arms Everlasting once.
    cast_cadence = InstanceCadence(once_only=True)
    for event in everlasting_events:
        trigger_kind = arming.match(event, is_melee=is_melee)
        if not trigger_kind:
            # The CC-adjacent scan above already receipted this event
            # with its named reason (ranged_slow / untyped_cc /
            # unknown_cc_kind); it is not an eligible branch.
            continue
        time = event_timestamp(event)
        raw_cast_identity = event.get("ability_instance")
        if not isinstance(raw_cast_identity, str) or not raw_cast_identity.strip():
            packets.append(_denial(event, "missing_instance_identity"))
            continue
        cast_identity = raw_cast_identity.strip()
        if not cast_cadence.allow(time, cast_identity):
            packets.append(_denial(event, "duplicate_instance"))
            continue
        if not cooldown_state.is_ready(time):
            packets.append(_denial(event, "cooldown"))
            continue
        if maximum_mana_reason is not None:
            packets.append(_denial(event, maximum_mana_reason))
            continue
        current_mana, current_mana_reason = _current_mana_at(
            result, time, raw_current_mana
        )
        if current_mana_reason is not None:
            packets.append(_denial(event, current_mana_reason))
            continue
        if mana_gate["status"] == "source_unavailable":
            packets.append(
                _denial(
                    event,
                    "mana_gate_authority_unavailable",
                    current_mana=current_mana,
                    maximum_mana=maximum_mana,
                    mana_threshold_ratio=mana_gate["threshold_ratio"],
                    mana_comparison=mana_gate["comparison"],
                )
            )
            continue
        if mana_gate["status"] not in AUTHORIZED_MANA_GATE_STATUSES:
            raise ValueError(
                "Fimbulwinter Everlasting mana gate has an unsupported "
                f"authority status: {mana_gate['status']!r}"
            )
        if current_mana is None or maximum_mana is None:
            raise RuntimeError("validated Fimbulwinter mana state is unavailable")
        threshold_ratio, threshold_reason = _mana_input(
            mana_gate["threshold_ratio"],
            missing_reason="missing_mana_threshold_ratio",
            invalid_reason="invalid_mana_threshold_ratio",
        )
        if threshold_reason is not None or threshold_ratio is None:
            raise ValueError(
                "script-authorized Fimbulwinter mana gate requires a valid "
                "threshold_ratio"
            )
        if mana_gate["comparison"] != "current_mana > maximum_mana * ratio":
            raise ValueError(
                "script-authorized Fimbulwinter mana gate requires an exact "
                "comparison contract"
            )
        if maximum_mana == 0.0 or current_mana <= maximum_mana * threshold_ratio:
            packets.append(
                _denial(
                    event,
                    "mana_gate",
                    current_mana=current_mana,
                    maximum_mana=maximum_mana,
                    mana_threshold_ratio=threshold_ratio,
                    mana_comparison=mana_gate["comparison"],
                )
            )
            continue

        raw_target_identity = event.get("target")
        if not isinstance(raw_target_identity, str) or not raw_target_identity.strip():
            packets.append(_denial(event, "missing_target_identity"))
            continue

        # Evaluate holder-centered range: count enemies whose
        # position is within the sourced 1200 units.  Spatial input
        # flows from the actor stats (stats.position tuple).
        nearby_count: int
        nearby_count, spatial_reason = enemies_within_range(
            attacker, all_actors, range_authority["range_units"]
        )
        if spatial_reason is not None:
            nearby_count = 0
            multiplier = 1.0
            packets.append(
                _denial(
                    event,
                    SPATIAL_UNAVAILABLE,
                    denied_component="multi_target_multiplier",
                    base_shield_applied=True,
                    nearby_enemy_count=None,
                    requested_multi_target_multiplier=range_authority["multiplier"],
                    applied_multi_target_multiplier=multiplier,
                )
            )
        else:
            multiplier = (
                range_authority["multiplier"]
                if nearby_count >= range_authority["minimum_enemy_count"]
                else 1.0
            )
        amount = (
            everlasting.value("everlasting_base_shield")
            + current_mana * everlasting.value("everlasting_current_mana_ratio")
        ) * multiplier
        cooldown_state.start(EventStamp(time))
        packets.append(
            _packet(
                attacker=attacker,
                target=attacker,
                time=time,
                kind="shield",
                source="Fimbulwinter — Everlasting",
                _event_id=(f"{attacker.participant_id}:fimbulwinter:{cast_identity}"),
                amount=amount,
                duration=everlasting.value("everlasting_duration"),
                target_scope="self",
                trigger=trigger_kind,
                # ``None`` when the producer did not enrich: the survival
                # compiler's fail-closed ``support_trigger_link`` branch
                # keys on ``is not None``, so an unenriched shield must
                # carry an absent link and not an empty one (D-03).
                _trigger_event_id=event.get("_event_id"),
                trigger_kind=trigger_kind,
                current_mana=current_mana,
                mana_threshold=maximum_mana * threshold_ratio,
                nearby_enemy_count=nearby_count if spatial_reason is None else None,
                nearby_enemy_range_units=range_authority["range_units"],
                range_center=holder_identity,
                range_input_status=(
                    "spatially_certified"
                    if spatial_reason is None
                    else range_authority["spatial_input_status"]
                ),
                range_boundary_status=range_authority["boundary_status"],
                requested_multi_target_multiplier=range_authority["multiplier"],
                multi_target_multiplier=multiplier,
                cooldown=cooldown_rule.cooldown_seconds,
                cooldown_until=time + cooldown_rule.cooldown_seconds,
                trigger_rule=arming.public_receipt(),
                source_url=source_meta["source_url"],
                source_revision_id=source_meta["source_revision_id"],
                rank=TransitionRank.LATE_BARRIER,
            )
        )
    return packets
