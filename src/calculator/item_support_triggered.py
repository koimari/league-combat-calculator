"""The grants an authored takedown, heal, shield or control mark arms."""

from __future__ import annotations

from typing import Any

from .ability_spec import AttackClass, Authority, DamageClass
from .ally_packet_recipient import _CHAIN_FRACTION_KEYS, _CHAIN_KINDS, _ramp_value
from .ally_packet_shape import _packet
from .item_behavior import AllyProducer, PacketKind
from .program.scope import Unreviewed, reviewed_scope
from .support_context import SupportCtx, _ControlMoment, _TriggerMoment
from .support_event_view import _cc_ability_label, _cc_mark_subjects
from .trigger_stream import CcClass


def _life_from_death_packets(ctx: SupportCtx) -> list[dict[str, Any]]:
    """Cryptbloom's nova heal, one packet per recipient per authored takedown."""
    nova = ctx.producer(AllyProducer.LIFE_FROM_DEATH)
    if nova is None:
        return []
    attacker = ctx.attacker
    allies = ctx.allies
    takedown_events = ctx.takedown_events
    packets: list[dict[str, Any]] = []
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
            for recipient in (attacker, *allies)
        )
    return packets


def _sanctify_packets(moment: _TriggerMoment) -> list[dict[str, Any]]:
    """Ardent Censer's attack speed and on-hit magic, to holder and healed ally."""
    sanctify = moment.ctx.producer(AllyProducer.SANCTIFY)
    if sanctify is None:
        return []
    attacker = moment.ctx.attacker
    return [
        _packet(
            attacker=attacker,
            target=recipient,
            time=moment.time,
            kind="stat_buff",
            source="Ardent Censer — Sanctify",
            amount=sanctify.value("sanctify_bonus_attack_speed"),
            duration=sanctify.value("sanctify_duration"),
            bonus_attack_speed_percent=sanctify.value("sanctify_bonus_attack_speed"),
            on_hit_magic_damage=sanctify.value("sanctify_on_hit_magic"),
            recipient_role="holder_and_healed_ally",
        )
        for recipient in (attacker, moment.target)
    ]


def _rapids_packets(moment: _TriggerMoment) -> list[dict[str, Any]]:
    """Staff of Flowing Water's ability power and haste, to holder and ally."""
    rapids = moment.ctx.producer(AllyProducer.RAPIDS)
    if rapids is None:
        return []
    attacker = moment.ctx.attacker
    return [
        _packet(
            attacker=attacker,
            target=recipient,
            time=moment.time,
            kind="stat_buff",
            source="Staff of Flowing Water — Rapids",
            amount=rapids.value("bonus_ability_power"),
            duration=rapids.value("duration"),
            ability_power=rapids.value("bonus_ability_power"),
            ability_haste=rapids.value("bonus_ability_haste"),
            recipient_role="holder_and_healed_ally",
        )
        for recipient in (attacker, moment.target)
    ]


def _starlit_grace_packets(moment: _TriggerMoment) -> list[dict[str, Any]]:
    """Moonstone Renewer's chain, to the nearest other wounded ally."""
    starlit_grace = moment.ctx.producer(AllyProducer.STARLIT_GRACE)
    if starlit_grace is None:
        return []
    attacker = moment.ctx.attacker
    allies = moment.ctx.allies
    trigger = moment.trigger
    target = moment.target
    time = moment.time
    packets: list[dict[str, Any]] = []
    candidates = [
        actor for actor in allies if actor.participant_id != target.participant_id
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
    return packets


def _dream_bubble_packets(moment: _TriggerMoment) -> list[dict[str, Any]]:
    """Dream Maker's two bubbles, the damage reduction and the on-hit magic."""
    blue_bubble = moment.ctx.producer(AllyProducer.BLUE_BUBBLE)
    purple_bubble = moment.ctx.producer(AllyProducer.PURPLE_BUBBLE)
    if blue_bubble is None or purple_bubble is None:
        return []
    attacker = moment.ctx.attacker
    target = moment.target
    time = moment.time
    packets: list[dict[str, Any]] = []
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
    return packets


def _soul_siphon_packets(moment: _TriggerMoment) -> list[dict[str, Any]]:
    """Echoes of Helia's stored Soul Charges, spent on one qualifying trigger.

    Soul Charges read every authored row's raw number, so this block reads
    the damage stream whole rather than the stack ledgers' filtered view, and
    reads it off the bus, where a row that is not a Mapping cannot reach a
    ``.get`` at all.
    """
    soul_siphon = moment.ctx.producer(AllyProducer.SOUL_SIPHON)
    if soul_siphon is None:
        return []
    attacker = moment.ctx.attacker
    damage_events = moment.ctx.damage_events
    target = moment.target
    time = moment.time
    packets: list[dict[str, Any]] = []
    soul_siphon.declared(PacketKind.HEAL)
    raw_damage = sum(event.raw_damage or event.damage for event in damage_events)
    cap = _ramp_value(soul_siphon, "charge_cap_min", holder=attacker, recipient=target)
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
    return packets


def _consonance_packets(moment: _TriggerMoment) -> list[dict[str, Any]]:
    """Diadem of Songs' heal, to the nearest most wounded ally."""
    consonance = moment.ctx.producer(AllyProducer.CONSONANCE)
    if consonance is None:
        return []
    attacker = moment.ctx.attacker
    consonance.declared(PacketKind.HEAL)
    return [
        _packet(
            attacker=attacker,
            target=moment.target,
            time=moment.time,
            kind="heal",
            source="Diadem of Songs — Consonance",
            amount=float(attacker.stats.get("mana", 0.0))
            * consonance.value("consonance_max_mana_ratio"),
            target_scope="nearest_most_wounded_ally",
            cooldown=consonance.value("consonance_cooldown"),
        )
    ]


def _fanfare_packets(moment: _ControlMoment) -> list[dict[str, Any]]:
    """Bandlepipes' move speed for the holder and attack speed for the team."""
    fanfare = moment.ctx.producer(AllyProducer.FANFARE)
    if fanfare is None:
        return []
    attacker = moment.ctx.attacker
    allies = moment.ctx.allies
    time = moment.time
    packets: list[dict[str, Any]] = []
    is_melee = bool(attacker.stats.get("is_melee", False))
    duration_key = "fanfare_duration_melee" if is_melee else "fanfare_duration_ranged"
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
        for recipient in (attacker, *allies)
    )
    return packets


def _going_sledding_packets(moment: _ControlMoment) -> list[dict[str, Any]]:
    """Solstice Sleigh's temporary health, to the holder and one wounded ally."""
    going_sledding = moment.ctx.producer(AllyProducer.GOING_SLEDDING)
    allies = moment.ctx.allies
    if going_sledding is None or not allies:
        return []
    attacker = moment.ctx.attacker
    time = moment.time
    packets: list[dict[str, Any]] = []
    going_sledding.declared(PacketKind.TEMPORARY_HEALTH)
    target = allies[0]
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
            bonus_move_speed_percent=going_sledding.value("bonus_move_speed_percent"),
            cooldown=going_sledding.value("cooldown"),
            target_scope=("self" if recipient is attacker else "most_wounded_ally"),
        )
        for recipient in (attacker, target)
    )
    return packets


def _command_packets(moment: _ControlMoment) -> list[dict[str, Any]]:
    """Imperial Mandate's amp, on every enemy the mark's routed scope names.

    Which enemy is marked is a routed answer rather than a roster position,
    and the ability it was assumed for is published in the disclosure.
    """
    command = moment.ctx.producer(AllyProducer.COMMAND)
    cc = moment.cc
    if command is None or cc.cc is not CcClass.IMMOBILIZE:
        return []
    attacker = moment.ctx.attacker
    all_actors = moment.ctx.all_actors
    time = moment.time
    packets: list[dict[str, Any]] = []
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
            **({"cc_scope_disclosure": disclosures[0].reason} if disclosures else {}),
        )
        for target in _cc_mark_subjects(attacker, cc, all_actors, scope)
    )
    return packets
