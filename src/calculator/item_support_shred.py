"""The cross-participant damage modifiers: one aura, one amp, two shreds."""

from __future__ import annotations

from typing import Any

from .ability_spec import AttackClass, Authority, DamageClass
from .ally_packet_shape import _packet, _same_side, _shred_ramp
from .item_behavior import AllyProducer, PacketKind, Resistance
from .support_context import SupportCtx
from .support_event_view import _stack_triggers, _target_by_id
from .survival.phases import TransitionRank


def _unmake_packets(ctx: SupportCtx) -> list[dict[str, Any]]:
    """Abyssal Mask's aura, one magic-damage curse per enemy.

    The holder's own pair engine already prices its personal branch; the
    ordered participant walk consumes these packets for every other eligible
    source without double-counting the originating holder.
    """
    unmake = ctx.producer(AllyProducer.UNMAKE)
    if unmake is None:
        return []
    attacker = ctx.attacker
    all_actors = ctx.all_actors
    packets: list[dict[str, Any]] = []
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
        for target in (actor for actor in all_actors if not _same_side(attacker, actor))
    )
    return packets


def _expose_weakness_packets(ctx: SupportCtx) -> list[dict[str, Any]]:
    """Bloodsong's all-source amp, armed by the holder's own spellblade row.

    The spellblade breakdown key is built from the item's own name, so the
    row this producer answers to is derived from the declaration's owner
    rather than spelled a second time.
    """
    expose_weakness = ctx.producer(AllyProducer.EXPOSE_WEAKNESS)
    if expose_weakness is None:
        return []
    attacker = ctx.attacker
    all_actors = ctx.all_actors
    damage_events = ctx.damage_events
    packets: list[dict[str, Any]] = []
    expose_weakness.declared(PacketKind.DAMAGE_MODIFIER)
    expose_key = (
        "expose_weakness_melee"
        if bool(attacker.stats.get("is_melee", False))
        else "expose_weakness_ranged"
    )
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
                # The walk owns this.
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
    return packets


def _resistance_shred_packets(ctx: SupportCtx) -> list[dict[str, Any]]:
    """Black Cleaver's armour and Bloodletter's Curse's magic-resist stacks.

    Both ledgers walk one stream, so a holder of either walks it once and a
    holder of neither never walks it at all, which is what the hand-kept
    damage-trigger name set bought before the registry existed.
    """
    carve = ctx.producer(AllyProducer.CARVE)
    vile_decay = ctx.producer(AllyProducer.VILE_DECAY)
    if carve is None and vile_decay is None:
        return []
    attacker = ctx.attacker
    names = ctx.names
    all_actors = ctx.all_actors
    damage_events = ctx.damage_events
    packets: list[dict[str, Any]] = []
    reduction_stacks: dict[tuple[str, str], int] = {}
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
    return packets
