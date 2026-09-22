"""One actor's utility outcome receipt, folded from its support and damage rows."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from ..item_behavior import PacketKind, is_packet_kind
from ..item_coverage import ATTACKER_LANES, item_model_coverage
from ..roster_composition import Combatant
from .records import SECONDARY_TARGETING_KINDS


def _utility_outcome_receipt(
    actor: Combatant,
    support_events: Iterable[Mapping[str, Any]],
    outgoing_events: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Summarise authored non-TDD outcomes without inventing a conversion.

    Movement and cleanse are real event dimensions, but their units are not
    interchangeable with healing, shielding, or damage.  Keep them as
    separate receipts so the Utility objective can expose what was applied
    while refusing to turn a percent/second or a cleanse count into a made-up
    scalar score.  Item dimensions are sourced from the same full-entry
    coverage table used by the API picker.
    """
    authored = list(support_events)
    support = [
        event
        for event in authored
        if event.get("kind") != "damage"
        if float(event.get("applied_amount", event.get("amount", 0.0)) or 0.0) > 0.0
    ]
    movement = [
        event for event in support if is_packet_kind(event, PacketKind.MOVEMENT)
    ]
    # A Purify cast rides a heal packet carrying the ``cleanse`` marker
    # (kind "heal", cleanse=True), so the marker counts alongside the
    # dedicated kind=="cleanse" packets.  ``cleanse_group`` then folds one
    # cast's per-recipient packets back into the one action they came from
    # — Milio's R cleanses himself and every selected teammate from a
    # single cast, and this receipt counts actions, not recipients.
    cleanse_packets = [
        event
        for event in support
        if is_packet_kind(event, PacketKind.CLEANSE) or bool(event.get("cleanse"))
    ]
    cleanse = list(
        {
            str(
                event.get("cleanse_group")
                or event.get("_event_id")
                or event.get("event_id")
                or id(event)
            ): event
            for event in cleanse_packets
        }.values()
    )
    slow = [event for event in support if is_packet_kind(event, PacketKind.SLOW)]
    # A movement packet that also names a slow-resist share is two
    # utility facts in one packet: the burst and the resistance that
    # rides it (Stormraider's Surge grants both from one trigger).
    slow_resistance = [
        event
        for event in support
        if is_packet_kind(event, PacketKind.MOVEMENT)
        and event.get("slow_resist_percent") is not None
    ]
    economy = [event for event in support if is_packet_kind(event, PacketKind.ECONOMY)]
    vision = [event for event in support if is_packet_kind(event, PacketKind.VISION)]
    # Umbral Glaive's Blackout is a vision packet that applies no amount to
    # anybody -- it denies the enemy's wards rather than granting the holder
    # anything -- so it is read off the AUTHORED stream rather than the
    # applied one.  Filtering it by applied amount was why an armed holder's
    # only vision outcome was the one it does not produce.
    blackout = [
        event
        for event in authored
        if is_packet_kind(event, PacketKind.VISION) and bool(event.get("ward_only"))
    ]
    # A damage modifier is an outcome whether or not it applied an amount:
    # the window it opened is the fact.  ``ratio_seconds`` prices only the
    # ones carrying a positive share, while the event count stays honest
    # about the windows.
    damage_modifiers = [
        event for event in authored if is_packet_kind(event, PacketKind.DAMAGE_MODIFIER)
    ]
    damage_reduction = [
        event
        for event in damage_modifiers
        if float(event.get("amount", 0.0) or 0.0) > 0.0
    ]
    # Manaflow-style resource packets are receipt-only progression events in
    # native mana units (including the zero-amount Helping Hand boundary,
    # which is read from the authored stream so the named boundary stays
    # visible even though it never applies to a champion target).
    resource = [
        event for event in authored if is_packet_kind(event, PacketKind.RESOURCE)
    ]
    movement_speed_percent_seconds = sum(
        abs(
            float(
                event.get("bonus_move_speed_percent", event.get("amount", 0.0)) or 0.0
            )
        )
        * max(0.0, float(event.get("duration", 0.0) or 0.0))
        for event in movement
    )
    slow_percent_seconds = sum(
        abs(float(event.get("slow_percent", event.get("amount", 0.0)) or 0.0))
        * max(0.0, float(event.get("duration", 0.0) or 0.0))
        for event in slow
    )
    targeting = [
        event.get("targeting")
        for event in outgoing_events
        if isinstance(event.get("targeting"), Mapping)
    ]
    secondary = [
        row
        for row in targeting
        if str(row.get("kind", "")) in SECONDARY_TARGETING_KINDS
    ]
    coverage = [
        item_model_coverage(str(item.get("name", "")), ATTACKER_LANES)
        for item in actor.items
    ]
    dimensions = sorted(
        {
            dimension.value
            for entry in coverage
            for dimension in entry.outcome_dimensions
        }
    )
    applied_dimensions = set()
    if movement:
        applied_dimensions.add("movement")
    if cleanse:
        applied_dimensions.add("cleanse")
    if slow:
        applied_dimensions.add("slow")
    if slow_resistance:
        applied_dimensions.add("slow_resistance")
    if damage_modifiers:
        applied_dimensions.add("damage_reduction")
    if secondary:
        applied_dimensions.add("multi_target")
    if economy:
        applied_dimensions.add("economy")
    if vision:
        applied_dimensions.add("vision")
    if resource:
        applied_dimensions.add("resource")
    if blackout:
        applied_dimensions.add("vision")
    return {
        "contract": "utility_outcomes_v1",
        "dimensions": dimensions,
        "applied_dimensions": sorted(applied_dimensions),
        "movement": {
            "event_count": len(movement),
            "speed_percent_seconds": round(movement_speed_percent_seconds, 6),
        },
        "cleanse": {"event_count": len(cleanse)},
        "slow": {
            "event_count": len(slow),
            "percent_seconds": round(slow_percent_seconds, 6),
        },
        "slow_resistance": {
            "event_count": len(slow_resistance),
            "percent_seconds": round(
                sum(
                    abs(float(event.get("slow_resist_percent", 0.0) or 0.0))
                    * max(0.0, float(event.get("duration", 0.0) or 0.0))
                    for event in slow_resistance
                ),
                6,
            ),
        },
        "damage_reduction": {
            "event_count": len(damage_modifiers),
            "ratio_seconds": round(
                sum(
                    max(0.0, float(event.get("amount", 0.0) or 0.0))
                    * max(0.0, float(event.get("duration", 0.0) or 0.0))
                    for event in damage_reduction
                ),
                6,
            ),
            "multiplier_windows": [
                {
                    "source": str(event.get("source", "")),
                    "multiplier": round(float(event.get("multiplier", 1.0) or 1.0), 6),
                    "duration": round(
                        max(0.0, float(event.get("duration", 0.0) or 0.0)), 6
                    ),
                    "expires_at": round(
                        float(event.get("time", 0.0))
                        + max(0.0, float(event.get("duration", 0.0) or 0.0)),
                        6,
                    ),
                }
                for event in damage_modifiers
                if float(event.get("multiplier", 1.0) or 1.0) < 1.0
            ],
        },
        "economy": {
            "event_count": len(economy),
            "gold": round(
                sum(
                    float(event.get("gold_amount", event.get("amount", 0.0)) or 0.0)
                    for event in economy
                ),
                6,
            ),
        },
        "vision": {
            "event_count": len(vision),
            "ward_uses": round(
                sum(
                    float(event.get("ward_uses", event.get("amount", 0.0)) or 0.0)
                    for event in vision
                ),
                6,
            ),
            "blackout": {
                "event_count": len(blackout),
                "trigger_windows": round(
                    sum(
                        float(event.get("blackout_trigger_windows", 0.0) or 0.0)
                        for event in blackout
                    ),
                    6,
                ),
            },
        },
        "resource": {
            "event_count": len(resource),
            "bonus_mana": round(
                sum(float(event.get("amount", 0.0) or 0.0) for event in resource),
                6,
            ),
        },
        "multi_target": {
            "packet_count": len(secondary),
            "allocated_packet_count": sum(
                1 for row in secondary if row.get("allocated_target_index") is not None
            ),
        },
        "scored_support_amount": round(
            sum(
                float(event.get("applied_amount", 0.0) or 0.0)
                for event in support
                if event.get("kind") not in {"economy", "vision"}
            ),
            6,
        ),
        "item_coverage": [
            {
                "name": entry.name,
                "status": entry.status,
                "dimensions": [
                    dimension.value for dimension in entry.outcome_dimensions
                ],
                "reason": entry.reason,
            }
            for entry in coverage
            if entry.outcome_dimensions
        ],
        "metric_note": (
            "Movement, cleanse, economy, and vision remain separate units; no "
            "cross-unit utility score is inferred. Healing, shielding, and "
            "applied support amounts remain event-derived values."
        ),
    }
