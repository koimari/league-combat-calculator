"""Typed, timestamped ally/team item packets for the participant ledger.

The ordinary item compiler owns damage emitted by the holder.  This module
owns the other side of the same Wiki entries: ally shields/heals, temporary
health, stat buffs, all-source debuffs, and explicit item-actives.  It never
assumes an active or a trigger that is absent from the authored event stream.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any

from .ability_spec import (
    AttackClass,
    Authority,
    DamageClass,
)
from .ally_packet_recipient import (
    _CHAIN_FRACTION_KEYS,
    _CHAIN_KINDS,
    _ramp_value,
    _recipient_amount,
)
from .ally_packet_shape import (
    _MISSING,
    _active_seconds,
    _active_seconds_for,
    _item_names,
    _option,
    _packet,
    _producer,
    _same_side,
    _shred_ramp,
    _teammates,
)

# The closed support-scope vocabulary and the kernel's typed trigger,
# cooldown and cadence rules an item packet arms under.
from .control_intervals import movement_entry
from .interpreters.ally_packet import AllyPacketSlot, resolve_slots

# Phase 3's declarations, and the interpreter that resolves them.  A producer
# is reached through the rule its registry entry declares — "does this holder
# declare Everlasting?" — rather than by spelling the item that has it, and
# every number comes back through the rule's own references, so a key no
# declaration carries is a stop instead of a silent registry read.
from .item_behavior import AllyProducer, PacketKind, Resistance
from .item_effects import (
    AUTHORIZED_MANA_GATE_STATUSES,
    ITEM_INPUT_OPTIONS,
    fimbulwinter_mana_gate_authority,
    fimbulwinter_nearby_enemy_range_authority,
    manaflow_declaration,
    required_effect_value,
)

# Phase 4's routing layer.  A crowd-control mark's subject is a decision the
# ability's ``CcScope`` makes and ``resolve_route`` delivers, never the roster
# position a pair scan happened to stamp.  ``program`` imports nothing from
# here, so the edge is one-way.
from .program.scope import Unreviewed, reviewed_scope
from .roster_composition import Combatant
from .state_lifecycle import CooldownRule, CooldownState, InstanceCadence
from .state_timeline import EventStamp, SourceReceipt
from .support_event_view import (
    _bus_streams,
    _cc_ability_label,
    _cc_event_stream,
    _cc_mark_subjects,
    _current_mana_at,
    _mana_input,
    _stack_triggers,
    _support_triggers,
    _target_by_id,
    require_event_view,
    resolve_knights_vow_tether,
)

# The item layer's one edge into the survival kernel: packet authors declare
# when their packet arms, in the walk's vocabulary, so there is no second
# ordering language to keep in sync.  Note the reach — importing
# ``.survival.actions`` executes ``survival/__init__.py``, so the whole
# kernel package loads with this module.  Acyclic: nothing under
# ``survival/`` imports ``item_support_effects``.
from .survival.actions import event_timestamp
from .survival.phases import TransitionRank

# The typed bus: one home for "what does this raw row mean?" and one for
# "which streams does this holder read?".  A hand name set drifts from the
# branch it gates.  ``trigger_stream``'s only intra-package import is
# ``ability_spec``, so this edge adds no cycle.
from .trigger_stream import CcClass


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
                kind=PacketKind.ECONOMY.value,
                source=f"{quest_item} — Shared Riches",
                amount=min(gold, gold_cap),
                target_scope="self",
                gold_amount=min(gold, gold_cap),
                quest_threshold=gold_cap,
                quest_complete=gold >= gold_cap,
                shared_riches_interval=required_effect_value(
                    quest_item, "shared_riches_interval"
                ),
                shared_riches_gold_minion=required_effect_value(
                    quest_item, "shared_riches_gold_minion"
                ),
                shared_riches_gold_melee=required_effect_value(
                    quest_item, "shared_riches_gold_melee"
                ),
                shared_riches_gold_ranged=required_effect_value(
                    quest_item, "shared_riches_gold_ranged"
                ),
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
                kind=PacketKind.VISION.value,
                source=f"{quest_item} — Ward",
                amount=ward_uses,
                target_scope="self",
                ward_uses=ward_uses,
                ward_charges=ward.value("ward_charges"),
                quest_threshold=gold_cap,
                source_url=source_meta["source_url"],
                source_revision_id=source_meta["source_revision_id"],
            )
        )
    return packets


def _cleanse_active_packet(
    attacker: Any, target: Any, time: float, item: str
) -> dict[str, Any]:
    """One self-cast cleanse-kind packet for a cleanse active item."""
    from .cleanse_declarations import item_declaration

    declaration = item_declaration(item)
    return _packet(
        attacker=attacker,
        target=target,
        time=time,
        kind=PacketKind.CLEANSE.value,
        source=f"{item} — {declaration['active_name']}",
        amount=1.0,
        target_scope="self",
        cleanse_item=item,
        source_key=item,
        utility_kind="cleanse",
    )


def _cleanse_movement_entry(item: str) -> dict[str, Any] | None:
    """*item*'s atom-backed movement entry, or ``None`` when it grants none."""
    from .cleanse_declarations import item_declaration

    return movement_entry(item_declaration(item))


def _self_cleanse_items(names: Iterable[str]) -> tuple[str, ...]:
    """The build's cleanse actives that target their own holder.

    Declaration order rather than build order, so the emitted packet sequence
    is a property of the registry every reader can see and not of whatever
    order a request happened to list its items in.
    """
    from .cleanse_declarations import ITEM_CLEANSE_DECLARATIONS

    held = frozenset(names)
    return tuple(
        item
        for item, declaration in ITEM_CLEANSE_DECLARATIONS.items()
        if declaration["target_scope"] == "self" and item in held
    )


def derive_item_support_effects(
    attacker: Combatant,
    result: Mapping[str, Any],
    all_actors: list[Combatant],
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
                    kind=PacketKind.ECONOMY.value,
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
                    kind=PacketKind.MOVEMENT.value,
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

    # Manaflow packets are a PROJECTION of the typed mana resource ledger
    # (P3 slice 1): the fight engine admits casts through
    # ``resource_ledger``, records every PROVEN accepted eligible hit (a
    # denied cast can never trigger Manaflow, and a missing hit identity
    # fails closed), and applies each granted bonus max-mana to the same
    # account.  This layer only shapes the accepted hit receipts into the
    # public kind="resource" packet schema.  It never recomputes cadence,
    # charges, or caps.  A fight result without a ledger section has no
    # Manaflow activity by construction, and that section IS the guard: it
    # names its own holder, so this branch asks the typed ledger which item
    # ran instead of asking the build for a name (A3).
    ledger_section = result.get("resource_ledger")
    manaflow = (
        ledger_section.get("manaflow") if isinstance(ledger_section, Mapping) else None
    )
    if isinstance(manaflow, Mapping):
        declaration = manaflow.get("declaration")
        if not isinstance(declaration, Mapping):
            raise ValueError(
                "a Manaflow ledger section carries no declaration, so its "
                "holder cannot be named"
            )
        holder = str(declaration["item"])
        sourced = manaflow_declaration(holder)
        interval = sourced["charge_interval"]
        max_charges = max(1, sourced["max_charges"])
        per_trigger = sourced["bonus_mana_per_trigger"]
        per_champion = sourced["bonus_mana_per_champion"]
        mana_cap = sourced["bonus_mana_max"]
        authored_mana = max(0.0, _option(attacker, holder, "manaflow_bonus_mana"))
        for hit in (
            manaflow.get("hits", ())
            if isinstance(manaflow.get("hits"), Iterable)
            else ()
        ):
            if not isinstance(hit, Mapping):
                continue
            if not hit.get("accepted"):
                # Denial receipts (missing identity, no charge, cap)
                # are public ledger rows, not support packets.
                continue
            try:
                hit_time = float(hit.get("time", 0.0) or 0.0)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(hit_time) or hit_time < 0.0:
                continue
            try:
                grant = float(hit.get("bonus_delta", 0.0) or 0.0)
            except (TypeError, ValueError):
                continue
            if grant <= 0.0:
                continue
            try:
                use_count = max(1, int(hit.get("use_count", 1) or 1))
            except (TypeError, ValueError):
                use_count = 1
            # The packet's public bonus_mana_total keeps the historic
            # in-fight accrual semantics (authored progress is a separate
            # field), while the ledger receipt tracks the full total.
            authored_capped = min(authored_mana, mana_cap)
            try:
                ledger_total = float(hit.get("bonus_total", grant) or grant)
            except (TypeError, ValueError):
                ledger_total = grant
            packets.append(
                _packet(
                    attacker=attacker,
                    target=attacker,
                    time=hit_time,
                    kind=PacketKind.RESOURCE.value,
                    source=f"{holder} — Manaflow",
                    amount=grant,
                    target_scope="self",
                    bonus_mana_total=max(0.0, ledger_total - authored_capped),
                    bonus_mana_cap=float(hit.get("cap", mana_cap) or mana_cap),
                    authored_bonus_mana=authored_capped,
                    manaflow_charge_interval=interval,
                    manaflow_max_charges=max_charges,
                    manaflow_bonus_mana_per_trigger=per_trigger,
                    manaflow_bonus_mana_per_champion=per_champion,
                    trigger_kind=f"{hit.get('trigger')}_vs_{hit.get('target_kind')}",
                    charge_accrued_at=(use_count - 1) * interval,
                    rank=TransitionRank.BARRIER_GRANT,
                    source_url=sourced["source_url"],
                    source_revision_id=sourced["source_revision_id"],
                )
            )

    # Umbral Glaive — Blackout is the ward-denial vision state: the sourced
    # one-second unseen gate arms Nightstalker, whose sourced true damage
    # (50 + 1.5 x lethality) rides the typed first-auto packet in the damage
    # ledger.  Blackout itself (the 8-second ward/trap denial aura) has no
    # champion-facing target in the fighter model, so this layer emits one
    # vision-dimension receipt when the authored ready gate is set; it never
    # guesses ward hits or converts the denial into damage.
    if "Umbral Glaive" in names:
        ready = _option(attacker, "Umbral Glaive", "nightstalker_ready") > 0.0
        if ready:
            source_meta = ITEM_INPUT_OPTIONS["Umbral Glaive"]
            lethality = max(
                0.0,
                float(attacker.stats.get("lethality", 0.0) or 0.0),
            )
            packets.append(
                _packet(
                    attacker=attacker,
                    target=attacker,
                    time=0.0,
                    kind=PacketKind.VISION.value,
                    source="Umbral Glaive — Blackout",
                    amount=1.0,
                    target_scope="self",
                    ward_uses=0.0,
                    nightstalker_ready=True,
                    blackout_trigger_windows=1,
                    unseen_gate_seconds=required_effect_value(
                        "Umbral Glaive", "nightstalker_unseen_seconds"
                    ),
                    trigger_window_seconds=required_effect_value(
                        "Umbral Glaive", "nightstalker_trigger_window"
                    ),
                    blackout_duration=required_effect_value(
                        "Umbral Glaive", "blackout_duration"
                    ),
                    ward_only=True,
                    ward_hits_modeled=0,
                    true_damage_on_ward_hit=(
                        required_effect_value("Umbral Glaive", "base")
                        + required_effect_value("Umbral Glaive", "lethality_ratio")
                        * lethality
                    ),
                    source_url=source_meta["source_url"],
                    source_revision_id=source_meta["source_revision_id"],
                )
            )

    # Fimbulwinter's Everlasting is a self shield that fires only from an
    # explicitly marked immobilize, or a slow for a melee holder.  Its
    # trigger predicate, per-cast-instance cadence, and cooldown are
    # kernel-owned (state_lifecycle); the mana gate and shield pricing stay
    # here.  No cast or crowd-control state is inferred from a spell name.
    # Every denial is a named ``item_denial`` receipt (ranged_slow,
    # mana_gate, cooldown, duplicate_instance, missing_instance_identity,
    # untyped_cc, unknown_cc_kind) so a silent skip can never hide an
    # unreviewed or ambiguous trigger.
    everlasting = _producer(slots, AllyProducer.EVERLASTING)
    if everlasting is not None:
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
            if (
                not isinstance(raw_target_identity, str)
                or not raw_target_identity.strip()
            ):
                packets.append(_denial(event, "missing_target_identity"))
                continue

            # Evaluate holder-centered range: count enemies whose
            # position is within the sourced 1200 units.  Spatial input
            # flows from the actor stats (stats.position tuple).
            from .spatial import SPATIAL_UNAVAILABLE, enemies_within_range

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
                    _event_id=(
                        f"{attacker.participant_id}:fimbulwinter:{cast_identity}"
                    ),
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

    # Shared target modifiers are emitted only from an authored trigger.  The
    # holder's own pair engine already prices its personal Black Cleaver,
    # Bloodletter, Bloodsong, and Abyssal branches; the ordered participant
    # walk consumes these packets for every other eligible source without
    # double-counting the originating holder.
    unmake = _producer(slots, AllyProducer.UNMAKE)
    if unmake is not None:
        unmake.declared(PacketKind.DAMAGE_MODIFIER)
        curse = unmake.value("magic_damage_amp")
        packets.extend(
            _packet(
                attacker=attacker,
                target=target,
                time=0.0,
                kind=PacketKind.DAMAGE_MODIFIER.value,
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
            for target in (
                actor for actor in all_actors if not _same_side(attacker, actor)
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
                    kind=PacketKind.DAMAGE_MODIFIER.value,
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
                    # Phase 4 S7 settled which engine owns this: the walk.
                    # The amplified pool is every roster attacker's damage
                    # inside a live window, which is a roster input, so there
                    # is no pair-local half for the walk to skip and this
                    # packet carries no ``owner`` — the holder's own damage is
                    # amplified here like everyone else's.  The pair engine's
                    # coarse row survives as a declared THEORETICAL preview,
                    # published in the pair fight's own receipt and kept out
                    # of every roster total.
                    authority=Authority.COUPLED_AUTHORITATIVE_WITH_PAIR_PREVIEW,
                    trigger_event_id=event.event_id or None,
                )
            )

    reduction_stacks: dict[tuple[str, str], int] = {}
    # Both ledgers walk one stream; the guard is hoisted so a holder of
    # neither never walks it at all, which is what the hand-maintained
    # damage-trigger name set bought before the registry existed.
    if carve is not None or vile_decay is not None:
        # The ramp both branches multiply and cap by, read once through the
        # family's own receipt-walk interpreter rather than off each ally
        # packet.
        armor_shred = (
            None
            if carve is None
            else _shred_ramp(attacker, names, Resistance.ARMOR, "carve")
        )
        mr_shred = (
            None
            if vile_decay is None
            else _shred_ramp(attacker, names, Resistance.MAGIC_RESIST, "vile_decay")
        )
        for event in _stack_triggers(damage_events):
            target = _target_by_id(all_actors, event.target_id)
            if target is None:
                continue
            damage_type = event.damage_type
            source_id = event.event_id
            if armor_shred is not None and damage_type == "physical":
                key = (target.participant_id, "armor")
                stacks = min(
                    armor_shred.max_stacks,
                    reduction_stacks.get(key, 0) + 1,
                )
                reduction_stacks[key] = stacks
                percent = stacks * armor_shred.per_stack
                packets.append(
                    _packet(
                        attacker=attacker,
                        target=target,
                        time=event.time,
                        kind=PacketKind.DAMAGE_MODIFIER.value,
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
            if mr_shred is not None and damage_type == "magic" and event.is_ability:
                key = (target.participant_id, "mr")
                stacks = min(
                    mr_shred.max_stacks,
                    reduction_stacks.get(key, 0) + 1,
                )
                reduction_stacks[key] = stacks
                percent = stacks * mr_shred.per_stack
                packets.append(
                    _packet(
                        attacker=attacker,
                        target=target,
                        time=event.time,
                        kind=PacketKind.DAMAGE_MODIFIER.value,
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
            packets.extend(
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
                for recipient in (attacker, *teammates)
            )

    # Triggered enchanter passives.  The target is carried by the authored
    # champion packet; no cursor or radius is guessed.
    for trigger in triggers:
        target = _target_by_id(all_actors, str(trigger.get("target", "")))
        if target is None:
            continue
        time = event_timestamp(trigger)
        if sanctify is not None:
            packets.extend(
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
        if rapids is not None:
            packets.extend(
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
        if starlit_grace is not None:
            candidates = [
                actor
                for actor in teammates
                if actor.participant_id != target.participant_id
            ]
            chain_target = candidates[0] if candidates else target
            # A kind computed from the trigger at runtime is a kind no
            # static reader can resolve.  Starlit Grace declares *two*
            # packets, one per kind it chains,
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
                        kind=PacketKind.DAMAGE_MODIFIER.value,
                        source="Dream Maker — Blue Dream Bubble",
                        amount=_ramp_value(
                            blue_bubble,
                            "blue_reduction_min",
                            holder=attacker,
                            recipient=target,
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
                        amount=_ramp_value(
                            purple_bubble,
                            "purple_magic_min",
                            holder=attacker,
                            recipient=target,
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
            cap = _ramp_value(
                soul_siphon, "charge_cap_min", holder=attacker, recipient=target
            )
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
                    kind=PacketKind.MOVEMENT.value,
                    source="Bandlepipes — Fanfare",
                    amount=fanfare.value("fanfare_bonus_move_speed"),
                    duration=fanfare.value(duration_key),
                    bonus_move_speed_percent=fanfare.value("fanfare_bonus_move_speed"),
                    target_scope="self",
                    trigger="authored_immobilize_or_slow",
                )
            )
            packets.extend(
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
                for recipient in (attacker, *teammates)
            )
        if going_sledding is not None and teammates:
            going_sledding.declared(PacketKind.TEMPORARY_HEALTH)
            target = teammates[0]
            packets.extend(
                _packet(
                    attacker=attacker,
                    target=recipient,
                    time=time,
                    kind="temporary_health",
                    source="Solstice Sleigh — Going Sledding",
                    amount=_ramp_value(
                        going_sledding,
                        "temporary_health_min",
                        holder=attacker,
                        recipient=recipient,
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
                for recipient in (attacker, target)
            )
        if command is not None and cc.cc is CcClass.IMMOBILIZE:
            # H2's recorded ruling, *deferred, default shipped*: no ability
            # declares a reviewed crowd-control scope yet, so every mark takes
            # the shipped default -- ``SingleTarget`` on the pair defender --
            # and publishes the disclosure that names the ability it was
            # assumed for.  Which enemy is marked stops being a roster
            # position and becomes a routed answer; what that answer *is*
            # does not move, which is the whole content of "default shipped".
            scope, disclosures = reviewed_scope(
                Unreviewed(ability=_cc_ability_label(cc, all_actors))
            )
            amp = command.value("command_damage_amp")
            packets.extend(
                _packet(
                    attacker=attacker,
                    target=target,
                    time=time,
                    kind=PacketKind.DAMAGE_MODIFIER.value,
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
                    # (fight.after.amplifiers._apply_command_amp); the walk applies
                    # this packet to every other participant only.
                    # Command's authority move to
                    # coupled-authoritative-with-preview is what H2 still
                    # blocks; the umbrella's recorded default is SPLIT and
                    # this phase does not move it.
                    authority=Authority.SPLIT,
                    owner=attacker.participant_id,
                    cc_scope=type(scope).__name__,
                    **(
                        {"cc_scope_disclosure": disclosures[0].reason}
                        if disclosures
                        else {}
                    ),
                )
                for target in _cc_mark_subjects(attacker, cc, all_actors, scope)
            )

    # Explicit item-actives.  A non-zero timestamp is the complete trigger
    # contract; the packet is not emitted at t=0 by default.
    devotion = _producer(slots, AllyProducer.DEVOTION)
    active_time = _active_seconds(attacker, devotion)
    if devotion is not None and active_time > 0.0:
        devotion.declared(PacketKind.SHIELD)
        packets.extend(
            _packet(
                attacker=attacker,
                target=target,
                time=active_time,
                kind="shield",
                source="Locket of the Iron Solari — Devotion",
                **_recipient_amount(
                    devotion,
                    "shield_min",
                    holder=attacker,
                    recipient=target,
                    scope="all_selected_teammates",
                ),
                duration=devotion.value("shield_duration"),
                target_scope="all_selected_teammates",
            )
            for target in (attacker, *teammates)
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
                **_recipient_amount(
                    purify,
                    "heal_min",
                    holder=attacker,
                    recipient=target,
                    scope="explicit_selected_ally",
                ),
                target_scope="explicit_selected_ally",
                cleanse=True,
                cleanse_item="Mikael's Blessing",
            )
        )
    # Quicksilver — the self-cast cleanse actives, driven by the cleanse
    # registry rather than by a pair of item names.  cleanse_eligibility is
    # the one home of every cleanse fact (exclusions, cooldown gap, the
    # atom-backed movement entry), so "which items cleanse their own holder"
    # is a question that registry already answers.  An AllyProducer could
    # not: ALLY_ENTRY_SHAPES identifies a producer by its ITEM_EFFECTS value
    # keys, and Quicksilver Sash carries no such record at all because its
    # active has no numbers.  An explicit active_seconds input emits the
    # sourced cleanse packet; a declaration carrying a movement entry
    # (Mercurial's) grants that SEPARATE utility from the same atom-backed
    # source — never a call-site literal.
    for cleanse_item in _self_cleanse_items(names):
        active_time = _active_seconds_for(attacker, cleanse_item)
        if active_time <= 0.0:
            continue
        packets.append(
            _cleanse_active_packet(attacker, attacker, active_time, cleanse_item)
        )
        movement = _cleanse_movement_entry(cleanse_item)
        if movement is None:
            continue
        packets.append(
            _packet(
                attacker=attacker,
                target=attacker,
                time=active_time,
                kind=PacketKind.MOVEMENT.value,
                source=movement["source"],
                amount=movement["amount"],
                duration=movement["duration"],
                bonus_move_speed_percent=movement["amount"],
                target_scope="self",
                cleanse_item=cleanse_item,
                source_key=cleanse_item,
                utility_kind="movement",
            )
        )
    intervention = _producer(slots, AllyProducer.INTERVENTION)
    active_time = _active_seconds(attacker, intervention)
    if intervention is not None and active_time > 0.0:
        intervention.declared(PacketKind.HEAL)
        beam_delay = intervention.value("beam_delay")
        range_units = intervention.value("target_area_range_units")
        packets.extend(
            _packet(
                attacker=attacker,
                target=target,
                time=active_time + beam_delay,
                kind="heal",
                source="Redemption — Intervention",
                **_recipient_amount(
                    intervention,
                    "heal_min",
                    holder=attacker,
                    recipient=target,
                    scope="redemption_allies_in_radius",
                ),
                target_scope="redemption_allies_in_radius",
                beam_delay=beam_delay,
                range_assumption=f"within_{range_units:g}_units",
            )
            for target in (attacker, *teammates)
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
        # Intervention grants sight of the target area for the beam
        # call-down ("granting sight of the area for the duration"): one
        # vision receipt per selected enemy, window [cast, impact] =
        # the sourced 2.5s beam_delay.  The sourced call-down window is
        # the receipt: neither the wiki text nor the binary names a separate
        # reveal duration.
        packets.extend(
            _packet(
                attacker=attacker,
                target=target,
                time=active_time,
                kind=PacketKind.VISION.value,
                source="Redemption — Intervention",
                amount=beam_delay,
                duration=beam_delay,
                reveal_duration=beam_delay,
                target_scope="enemy_champions_in_radius",
                range_assumption=f"within_{range_units:g}_units",
                beam_delay=beam_delay,
            )
            for target in (
                actor for actor in all_actors if not _same_side(attacker, actor)
            )
        )
    inspiring_speech = _producer(slots, AllyProducer.INSPIRING_SPEECH)
    active_time = _active_seconds(attacker, inspiring_speech)
    if inspiring_speech is not None and active_time > 0.0:
        inspiring_speech.declared(PacketKind.MOVEMENT)
        packets.extend(
            _packet(
                attacker=attacker,
                target=target,
                time=active_time,
                kind=PacketKind.MOVEMENT.value,
                source="Shurelya's Battlesong — Inspiring Speech",
                amount=inspiring_speech.value("bonus_move_speed_percent"),
                duration=inspiring_speech.value("duration"),
                bonus_move_speed_percent=inspiring_speech.value(
                    "bonus_move_speed_percent"
                ),
                target_scope="all_selected_teammates",
            )
            for target in (attacker, *teammates)
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
                    kind=PacketKind.SLOW.value,
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
                    kind=PacketKind.MOVEMENT.value,
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
        # reasons — no producer, no eligible teammate, no authored selection
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
# participant deals or takes, so the question "which engine owns this
# mechanic" has to be answered for every one of them.  The answer is an
# ``ability_spec.Authority`` member, declared in 0A and carried by the
# packets themselves from C2.  It is also what the coupled golden baseline
# reads to prove its scenario set covers every producer (runbook R-12).
#
# There is exactly one authority table in the repo and it is
# ``trigger_stream.CAPABILITIES``.  Two tables that agree today are two
# tables that can disagree tomorrow, so the derivation below reads the
# registry
# and the call sites are bound to it by the check underneath.  A seventh
# producer therefore fails to resolve — loudly, on its first packet — until
# it is declared, and the same registry is what the coupled golden baseline
# reads to prove its scenario set covers every producer (runbook R-12).


__all__ = ["derive_item_support_effects", "schedule_knights_vow"]
