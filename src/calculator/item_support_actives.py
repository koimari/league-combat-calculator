"""The explicit item-actives, and the self-cast cleanses beside them."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .ally_packet_recipient import _recipient_amount
from .ally_packet_shape import _active_seconds, _active_seconds_for, _packet, _same_side
from .control_intervals import movement_entry
from .item_behavior import AllyProducer, PacketKind
from .support_context import SupportCtx
from .survival.phases import TransitionRank


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


def _devotion_packets(ctx: SupportCtx) -> list[dict[str, Any]]:
    """Locket of the Iron Solari's shield, to every selected teammate.

    A non-zero timestamp is the complete trigger contract, so the packet is
    not emitted at t=0 by default.
    """
    devotion = ctx.producer(AllyProducer.DEVOTION)
    active_time = _active_seconds(ctx.attacker, devotion)
    if devotion is None or active_time <= 0.0:
        return []
    attacker = ctx.attacker
    devotion.declared(PacketKind.SHIELD)
    return [
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
        for target in (attacker, *ctx.allies)
    ]


def _purify_packets(ctx: SupportCtx) -> list[dict[str, Any]]:
    """Mikael's Blessing's heal and cleanse, on the default ally.

    The recipient this packet is priced for is the roster's first ally;
    ``participant_timeline`` is the one place a selection moves it.
    """
    purify = ctx.producer(AllyProducer.PURIFY)
    active_time = _active_seconds(ctx.attacker, purify)
    allies = ctx.allies
    if purify is None or active_time <= 0.0 or not allies:
        return []
    attacker = ctx.attacker
    packets: list[dict[str, Any]] = []
    purify.declared(PacketKind.HEAL)
    target = allies[0]
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
    return packets


def _self_cleanse_packets(ctx: SupportCtx) -> list[dict[str, Any]]:
    """The self-cast cleanse actives, driven by the cleanse registry.

    ``cleanse_eligibility`` is the one home of every cleanse fact, so which
    items cleanse their own holder is a question that registry answers.  An
    ``AllyProducer`` could not: ``ALLY_ENTRY_SHAPES`` identifies a producer
    by its ``ITEM_EFFECTS`` value keys, and Quicksilver Sash carries no such
    record because its active has no numbers.  An explicit ``active_seconds``
    input emits the sourced cleanse packet; a declaration carrying a movement
    entry grants that separate utility from the same atom-backed source.
    """
    attacker = ctx.attacker
    names = ctx.names
    packets: list[dict[str, Any]] = []
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
    return packets


def _intervention_packets(ctx: SupportCtx) -> list[dict[str, Any]]:
    """Redemption's beam: the heal, the area true damage and the reveal.

    The calculator has no map coordinates, so every selected enemy is an
    explicit roster target under the sourced area-radius assumption and no
    proximity order is invented.  The damage packet enters the normal phase-0
    walk, so shields, death cutoffs and attribution stay shared.
    """
    intervention = ctx.producer(AllyProducer.INTERVENTION)
    active_time = _active_seconds(ctx.attacker, intervention)
    if intervention is None or active_time <= 0.0:
        return []
    attacker = ctx.attacker
    allies = ctx.allies
    all_actors = ctx.all_actors
    packets: list[dict[str, Any]] = []
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
        for target in (attacker, *allies)
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
    for target in (actor for actor in all_actors if not _same_side(attacker, actor)):
        amount = max(0.0, float(target.stats.get("health", 0.0))) * true_damage_ratio
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
        for target in (actor for actor in all_actors if not _same_side(attacker, actor))
    )
    return packets


def _inspiring_speech_packets(ctx: SupportCtx) -> list[dict[str, Any]]:
    """Shurelya's Battlesong's move speed, to every selected teammate."""
    inspiring_speech = ctx.producer(AllyProducer.INSPIRING_SPEECH)
    active_time = _active_seconds(ctx.attacker, inspiring_speech)
    if inspiring_speech is None or active_time <= 0.0:
        return []
    attacker = ctx.attacker
    inspiring_speech.declared(PacketKind.MOVEMENT)
    return [
        _packet(
            attacker=attacker,
            target=target,
            time=active_time,
            kind=PacketKind.MOVEMENT.value,
            source="Shurelya's Battlesong — Inspiring Speech",
            amount=inspiring_speech.value("bonus_move_speed_percent"),
            duration=inspiring_speech.value("duration"),
            bonus_move_speed_percent=inspiring_speech.value("bonus_move_speed_percent"),
            target_scope="all_selected_teammates",
        )
        for target in (attacker, *ctx.allies)
    ]


def _shockwave_packets(ctx: SupportCtx) -> list[dict[str, Any]]:
    """Stridebreaker's slow on every enemy and its move speed per champion hit."""
    shockwave = ctx.producer(AllyProducer.BREAKING_SHOCKWAVE)
    active_time = _active_seconds(ctx.attacker, shockwave)
    if shockwave is None or active_time <= 0.0:
        return []
    attacker = ctx.attacker
    all_actors = ctx.all_actors
    packets: list[dict[str, Any]] = []
    shockwave.declared(PacketKind.SLOW)
    shockwave.declared(PacketKind.MOVEMENT)
    slow_percent = shockwave.value("slow_percent")
    slow_duration = shockwave.value("slow_duration")
    move_speed_percent = shockwave.value("bonus_move_speed_percent")
    move_speed_duration = shockwave.value("bonus_move_speed_duration")
    area_radius = shockwave.value("area_radius")
    front_offset = shockwave.value("front_offset")
    for target in (actor for actor in all_actors if not _same_side(attacker, actor)):
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
