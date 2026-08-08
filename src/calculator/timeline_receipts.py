"""Public timeline receipt assembly and serialization.

This module owns the public and score-only result shapes emitted after the
roster has been composed and the survival walk has completed.
"""

# The public schema is intentionally explicit. The field groups preserve the
# existing receipt contract for API callers and score-only optimizer clients.
# pylint: disable=duplicate-code,too-many-arguments,too-many-locals,too-many-positional-arguments

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .item_coverage import item_model_coverage
from .roster_composition import Combatant
from .survival import action_key as _action_key
from .timeline_coverage import combine_timeline_coverages


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
    support = [
        event
        for event in support_events
        if event.get("kind") != "damage"
        if float(event.get("applied_amount", event.get("amount", 0.0)) or 0.0) > 0.0
    ]
    movement = [event for event in support if event.get("kind") == "movement"]
    cleanse = [event for event in support if event.get("kind") == "cleanse"]
    slow = [event for event in support if event.get("kind") == "slow"]
    economy = [event for event in support if event.get("kind") == "economy"]
    vision = [event for event in support if event.get("kind") == "vision"]
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
        if str(row.get("kind", ""))
        in {
            "active_secondary",
            "chain_lightning",
            "chain_lightning_copied_on_hit",
            "cleave_secondary",
            "hydra_cleave",
            "runaan_bolt",
            "runaan_bolt_copied_on_hit",
        }
    ]
    coverage = [item_model_coverage(item) for item in actor.items]
    dimensions = sorted(
        {
            str(dimension)
            for entry in coverage
            for dimension in entry.get("outcome_dimensions", [])
        }
    )
    applied_dimensions = set()
    if movement:
        applied_dimensions.add("movement")
    if cleanse:
        applied_dimensions.add("cleanse")
    if slow:
        applied_dimensions.add("slow")
    if secondary:
        applied_dimensions.add("multi_target")
    if economy:
        applied_dimensions.add("economy")
    if vision:
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
                "name": entry.get("name", ""),
                "status": entry.get("status", ""),
                "dimensions": list(entry.get("outcome_dimensions", [])),
                "reason": entry.get("reason", ""),
            }
            for entry in coverage
            if entry.get("outcome_dimensions")
        ],
        "metric_note": (
            "Movement, cleanse, economy, and vision remain separate units; no "
            "cross-unit utility score is inferred. Healing, shielding, and "
            "applied support amounts remain event-derived values."
        ),
    }


def _target_allocation_receipt(
    public_events: Iterable[Mapping[str, Any]],
    target_count: int,
    breakdown_rows: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Prove roster allocation for every authored secondary-target packet."""
    rows = [
        event.get("targeting")
        for event in public_events
        if isinstance(event.get("targeting"), Mapping)
    ]
    rows.extend(
        row.get("targeting")
        for row in breakdown_rows
        if isinstance(row.get("targeting"), Mapping)
    )
    for row in breakdown_rows:
        sources = row.get("sources")
        if not isinstance(sources, list):
            continue
        rows.extend(
            source.get("targeting")
            for source in sources
            if isinstance(source, Mapping)
            and isinstance(source.get("targeting"), Mapping)
        )
    secondary = [
        row
        for row in rows
        if str(row.get("kind", ""))
        in {
            "active_secondary",
            "chain_lightning",
            "chain_lightning_copied_on_hit",
            "cleave_secondary",
            "hydra_cleave",
            "runaan_bolt",
            "runaan_bolt_copied_on_hit",
        }
    ]
    missing = [row for row in secondary if row.get("allocated_target_index") is None]
    return {
        "contract": "ordered_roster_target_allocation_v1",
        "target_count": max(0, int(target_count)),
        "secondary_packet_count": len(secondary),
        "allocated_secondary_packet_count": len(secondary) - len(missing),
        "complete": not missing,
        "policy": "roster_index_from_engine_targeting" if secondary else "none",
        "unallocated_reasons": (
            ["secondary packet is missing allocated_target_index"] if missing else []
        ),
    }


def assemble_public_receipt(
    *,
    params: Any,
    all_actors: list[Combatant],
    survival: Mapping[str, Mapping[str, Any]],
    support_effects: Mapping[str, list[dict[str, Any]]],
    healing: Mapping[str, list[dict[str, Any]]],
    outgoing: Mapping[str, list[dict[str, Any]]],
    focus_participant_id: str,
    enemy_actors: list[Combatant],
    coverage_reports: list[Mapping[str, Any]],
    include_receipt: bool,
    public_breakdown: list[dict[str, Any]],
    support_by_attacker: Mapping[str, float],
) -> dict[str, Any]:
    """Build the score-only or full public timeline receipt."""

    if not include_receipt:
        # Optimizer scoring reads only the survival rows, the per-actor
        # damage breakdown, and the ordering receipt.  Skip the public
        # event/healing/support serialization for the thousands of candidate
        # evaluations that never show a timeline to anyone.
        return {
            "duration": float(params.fight_duration_seconds),
            "participants": [
                {
                    "participant_id": actor.participant_id,
                    "team": actor.team,
                    "champion": actor.champion_data.get("name", ""),
                    "level": actor.level,
                    "survival": survival[actor.participant_id],
                }
                for actor in all_actors
            ],
            "breakdown": public_breakdown,
            "timeline_coverage": combine_timeline_coverages(
                coverage_reports,
                target_count=len(coverage_reports),
            ),
        }

    focus_row = next(
        (
            row
            for row in public_breakdown
            if row["participant_id"] == focus_participant_id
        ),
        None,
    )
    focus_survival = survival.get(focus_participant_id)
    focus_support = sum(
        float(event.get("applied_amount", 0.0))
        for events in support_effects.values()
        for event in events
        if event.get("attacker") == focus_participant_id
    )
    focus_healing = sum(
        float(event.get("applied_amount", 0.0))
        for event in healing.get(focus_participant_id, [])
    )
    public_events = sorted(
        (event for events in outgoing.values() for event in events),
        key=lambda event: event.get("_sk")
        or _action_key(
            float(event.get("time", 0.0)),
            0.5 if event.get("_reactive") else 0.0,
            str(event.get("target", "")),
            event,
        ),
    )
    public_healing_events = sorted(
        (event for events in healing.values() for event in events),
        key=lambda event: event.get("_sk")
        or _action_key(
            float(event.get("time", 0.0)),
            1.0,
            str(event.get("attacker", "")),
            event,
        ),
    )
    public_support_events = sorted(
        (event for events in support_effects.values() for event in events),
        key=lambda event: (
            float(event.get("time", 0.0)),
            -1.0 if event.get("kind") in {"shield", "temporary_health"} else 1.0,
            str(event.get("target", "")),
            str(event.get("attacker", "")),
            str(event.get("_event_id", "")),
        ),
    )
    support_by_actor = {
        actor.participant_id: [
            event
            for event in public_support_events
            if event.get("attacker") == actor.participant_id
        ]
        for actor in all_actors
    }
    outgoing_by_actor = {
        actor.participant_id: [
            event
            for event in public_events
            if event.get("attacker") == actor.participant_id
        ]
        for actor in all_actors
    }
    utility_by_actor = {
        actor.participant_id: _utility_outcome_receipt(
            actor,
            support_by_actor[actor.participant_id],
            outgoing_by_actor[actor.participant_id],
        )
        for actor in all_actors
    }
    return {
        "duration": float(params.fight_duration_seconds),
        "participants": [
            {
                "participant_id": actor.participant_id,
                "team": actor.team,
                "champion": actor.champion_data.get("name", ""),
                "level": actor.level,
                "stats": dict(actor.stats),
                "items": [item.get("name", "") for item in actor.items],
                "survival": survival[actor.participant_id],
            }
            for actor in all_actors
        ],
        "breakdown": public_breakdown,
        "events": [
            {
                "time": round(float(event.get("time", 0.0)), 3),
                "attacker": event.get("attacker"),
                "target": event.get("target"),
                "source": event.get("source_key", ""),
                "damage_type": event.get("damage_type", ""),
                "damage": round(float(event.get("damage", 0.0)), 1),
                "raw_damage": round(
                    float(event.get("raw_damage", event.get("damage", 0.0))), 1
                ),
                "pair_damage": round(
                    float(event.get("pair_damage", event.get("damage", 0.0))), 1
                ),
                "overkill": round(float(event.get("overkill", 0.0)), 1),
                "event_precision": event.get("event_precision", "exact"),
                **(
                    {"event_id": str(event["_event_id"])}
                    if event.get("_event_id") is not None
                    else {}
                ),
                **(
                    {"trigger_event_id": str(event["_trigger_event_id"])}
                    if event.get("_trigger_event_id") is not None
                    else {}
                ),
                **(
                    {"sequence": int(event["sequence"])}
                    if event.get("sequence") is not None
                    else {}
                ),
                **({"reactive": True} if event.get("_reactive") else {}),
                **(
                    {"spell_shield_source": str(event["spell_shield_source"])}
                    if event.get("spell_shield_source")
                    else {}
                ),
                **(
                    {"threshold_shield_triggered": True}
                    if event.get("threshold_shield_triggered")
                    else {}
                ),
                **(
                    {
                        "reactive_shield_triggered": dict(
                            event["reactive_shield_triggered"]
                        )
                    }
                    if event.get("reactive_shield_triggered")
                    else {}
                ),
                **(
                    {
                        "maw_lifeline_omnivamp_activated": round(
                            float(event["maw_lifeline_omnivamp_activated"]), 3
                        )
                    }
                    if event.get("maw_lifeline_omnivamp_activated") is not None
                    else {}
                ),
                **(
                    {
                        "threshold_shield_expires_at": round(
                            float(event["threshold_shield_expires_at"]), 3
                        )
                    }
                    if event.get("threshold_shield_expires_at") is not None
                    else {}
                ),
                **(
                    {"threshold_health_triggered": True}
                    if event.get("threshold_health_triggered")
                    else {}
                ),
                **(
                    {"execute_triggered": True}
                    if event.get("execute_triggered")
                    else {}
                ),
                **(
                    {"redirected_amount": round(float(event["_redirected_amount"]), 1)}
                    if event.get("_redirected_amount") is not None
                    else {}
                ),
                **(
                    {"redirected_from": str(event["_redirected_from"])}
                    if event.get("_redirected_from")
                    else {}
                ),
                **(
                    {"redirect_fraction": round(float(event["_redirect_fraction"]), 6)}
                    if event.get("_redirect_fraction") is not None
                    else {}
                ),
                **(
                    {"redirect_source": str(event["redirect_source"])}
                    if event.get("redirect_source")
                    else {}
                ),
                **(
                    {"redirect_pre_mitigation": True}
                    if event.get("redirect_pre_mitigation")
                    else {}
                ),
                **(
                    {"redirect_attributed_to": str(event["redirect_attributed_to"])}
                    if event.get("redirect_attributed_to")
                    else {}
                ),
                **(
                    {"redirect_range_units": int(event["redirect_range_units"])}
                    if event.get("redirect_range_units") is not None
                    else {}
                ),
                **(
                    {"redirect_skipped_reason": str(event["redirect_skipped_reason"])}
                    if event.get("redirect_skipped_reason")
                    else {}
                ),
                **(
                    {
                        "incoming_damage_multiplier": round(
                            float(event["incoming_damage_multiplier"]), 3
                        )
                    }
                    if event.get("incoming_damage_multiplier") is not None
                    else {}
                ),
                **(
                    {"incoming_damage_source": str(event["incoming_damage_source"])}
                    if event.get("incoming_damage_source")
                    else {}
                ),
                **(
                    {
                        "incoming_damage_reduction": round(
                            float(event["incoming_damage_reduction"]), 1
                        )
                    }
                    if event.get("incoming_damage_reduction") is not None
                    else {}
                ),
                **(
                    {
                        "support_damage_multiplier": dict(
                            event["support_damage_multiplier"]
                        )
                    }
                    if event.get("support_damage_multiplier")
                    else {}
                ),
                **(
                    {
                        "support_damage_reduction": dict(
                            event["support_damage_reduction"]
                        )
                    }
                    if event.get("support_damage_reduction")
                    else {}
                ),
                **(
                    {
                        "support_resistance_reduction": list(
                            event["support_resistance_reduction"]
                        )
                    }
                    if event.get("support_resistance_reduction")
                    else {}
                ),
                **(
                    {"support_on_hit_magic": list(event["support_on_hit_magic"])}
                    if event.get("support_on_hit_magic")
                    else {}
                ),
                **(
                    {"targeting": dict(event["targeting"])}
                    if isinstance(event.get("targeting"), Mapping)
                    else {}
                ),
                **(
                    {"deferred_from": str(event["_deferred_from"])}
                    if event.get("_deferred_from")
                    else {}
                ),
                **(
                    {"wound_source": str(event["_wound_source"])}
                    if event.get("_wound_source")
                    else {}
                ),
                **(
                    {
                        "wound_duration": round(float(event["grievous_duration"]), 3),
                        "wound_until": round(
                            float(
                                event.get(
                                    "_wound_until",
                                    float(event.get("time", 0.0))
                                    + float(event["grievous_duration"]),
                                )
                            ),
                            3,
                        ),
                    }
                    if event.get("grievous_duration") is not None
                    else {}
                ),
                **(
                    {"healing_reduction": dict(event["healing_reduction"])}
                    if event.get("healing_reduction")
                    else {}
                ),
                **(
                    {"venom": dict(event["venom"])}
                    if event.get("venom") is not None
                    else {}
                ),
                **(
                    {"skipped_reason": str(event["skipped_reason"])}
                    if event.get("skipped_reason")
                    else {}
                ),
                **(
                    {"grey_health_stored": round(float(event["grey_health_stored"]), 1)}
                    if event.get("grey_health_stored") is not None
                    else {}
                ),
            }
            for event in public_events
        ],
        "healing_events": [
            {
                "time": round(float(event.get("time", 0.0)), 3),
                "attacker": event.get("attacker"),
                "source": event.get("source", ""),
                **(
                    {"event_id": str(event["_event_id"])}
                    if event.get("_event_id") is not None
                    else {}
                ),
                **(
                    {"trigger_event_id": str(event["_trigger_event_id"])}
                    if event.get("_trigger_event_id") is not None
                    else {}
                ),
                **(
                    {"trigger_target": str(event["trigger_target"])}
                    if event.get("trigger_target") is not None
                    else {}
                ),
                "amount": round(float(event.get("amount", 0.0)), 1),
                "raw_amount": round(
                    float(event.get("raw_amount", event.get("amount", 0.0))), 1
                ),
                "applied_amount": round(
                    float(event.get("applied_amount", event.get("amount", 0.0))), 1
                ),
                "overheal": round(
                    float(
                        event.get(
                            "overheal",
                            max(
                                0.0,
                                float(
                                    event.get(
                                        "reduced_amount", event.get("amount", 0.0)
                                    )
                                )
                                - float(
                                    event.get(
                                        "applied_amount", event.get("amount", 0.0)
                                    )
                                ),
                            ),
                        )
                    ),
                    1,
                ),
                "temporary_health": round(float(event.get("temporary_health", 0.0)), 1),
                **(
                    {
                        "temporary_health_expires_at": round(
                            float(event["temporary_health_expires_at"]), 3
                        )
                    }
                    if event.get("temporary_health_expires_at") is not None
                    else {}
                ),
                "reduced_amount": round(
                    float(event.get("reduced_amount", event.get("amount", 0.0))), 1
                ),
                "healing_reduction_factor": round(
                    float(event.get("healing_reduction_factor", 1.0)), 3
                ),
                **(
                    {"skipped_reason": str(event["skipped_reason"])}
                    if event.get("skipped_reason")
                    else {}
                ),
                **({"grey_health": True} if event.get("_grey_health") else {}),
                **(
                    {"charges": int(event["charges"])}
                    if event.get("charges") is not None
                    else {}
                ),
                **(
                    {
                        "ichorshield_generated": round(
                            float(event["ichorshield_generated"]), 1
                        )
                    }
                    if event.get("ichorshield_generated") is not None
                    else {}
                ),
                **(
                    {"ichorshield_total": round(float(event["ichorshield_total"]), 1)}
                    if event.get("ichorshield_total") is not None
                    else {}
                ),
            }
            for event in public_healing_events
        ],
        "support_events": [
            {
                "time": round(float(event.get("time", 0.0)), 3),
                "attacker": event.get("attacker"),
                "target": event.get("target"),
                "recipient": event.get("target"),
                **(
                    {"event_id": str(event["_event_id"])}
                    if event.get("_event_id") is not None
                    else {}
                ),
                **(
                    {"trigger_event_id": str(event["_trigger_event_id"])}
                    if event.get("_trigger_event_id") is not None
                    else {}
                ),
                **(
                    {"source_event_id": str(event["_source_event_id"])}
                    if event.get("_source_event_id") is not None
                    else {}
                ),
                "source": event.get("source", ""),
                "kind": event.get("kind", ""),
                "amount": round(float(event.get("amount", 0.0)), 6),
                "applied_amount": round(
                    float(event.get("applied_amount", event.get("amount", 0.0))), 6
                ),
                "target_scope": event.get("target_scope", ""),
                "target_policy": event.get("target_policy", ""),
                **(
                    {
                        key: round(float(event[key]), 6)
                        for key in (
                            "bonus_attack_speed_percent",
                            "on_hit_magic_damage",
                            "ability_power",
                            "ability_haste",
                            "bonus_move_speed_percent",
                            "slow_percent",
                            "chain_fraction",
                            "multiplier",
                            "cooldown",
                            "charges_consumed",
                            "beam_delay",
                            "armor_reduction_percent",
                            "mr_reduction_percent",
                            "stack_count",
                            "current_mana",
                            "mana_threshold",
                            "nearby_enemy_count",
                            "multi_target_multiplier",
                            "cooldown_until",
                            "gold_amount",
                            "ward_uses",
                            "quest_threshold",
                            "minion_kills",
                        )
                        if event.get(key) is not None
                    }
                ),
                **(
                    {
                        key: bool(event[key])
                        for key in (
                            "damage_reduction",
                            "next_event_only",
                            "all_sources",
                            "cleanse",
                            "persistent",
                            "completion_granted",
                        )
                        if event.get(key) is not None
                    }
                ),
                **(
                    {"trigger": str(event["trigger"])}
                    if event.get("trigger") is not None
                    else {}
                ),
                **(
                    {
                        key: str(event[key])
                        for key in (
                            "resistance_type",
                            "owner",
                            "range_assumption",
                            "trigger_kind",
                            "source_url",
                        )
                        if event.get(key) is not None
                    }
                ),
                **(
                    {"duration": round(float(event["duration"]), 3)}
                    if event.get("duration") is not None
                    else {}
                ),
                **(
                    {"expires_at": round(float(event["expires_at"]), 3)}
                    if event.get("expires_at") is not None
                    else {}
                ),
                **(
                    {"venom": dict(event["venom"])}
                    if event.get("venom") is not None
                    else {}
                ),
                **(
                    {"source_revision_id": int(event["source_revision_id"])}
                    if event.get("source_revision_id") is not None
                    else {}
                ),
                **(
                    {"skipped_reason": str(event["skipped_reason"])}
                    if event.get("skipped_reason")
                    else {}
                ),
            }
            for event in public_support_events
        ],
        "utility_outcomes": {
            "contract": "utility_outcomes_v1",
            "participants": {
                actor.participant_id: utility_by_actor[actor.participant_id]
                for actor in all_actors
            },
            "focus": utility_by_actor.get(focus_participant_id, {}),
            "metric_note": (
                "Utility dimensions are reported in their native units. The "
                "calculator does not convert movement, cleanse, vision, or "
                "economy into TDD or a guessed common scalar."
            ),
        },
        "target_allocation": _target_allocation_receipt(
            public_events, len(enemy_actors), public_breakdown
        ),
        "objective": {
            "main_team_damage_before_death": round(
                sum(
                    row["total_damage"]
                    for row in public_breakdown
                    if row["team"] in {"main", "ally"}
                ),
                1,
            ),
            "enemy_team_damage_before_death": round(
                sum(
                    row["total_damage"]
                    for row in public_breakdown
                    if row["team"] == "enemy"
                ),
                1,
            ),
            "surviving_main_team": sum(
                1
                for actor in all_actors
                if actor.team in {"main", "ally"}
                and survival[actor.participant_id]["survived_window"]
            ),
            "focus_participant_id": focus_participant_id,
            "focus_damage_before_death": round(
                float(focus_row.get("total_damage", 0.0)) if focus_row else 0.0,
                1,
            ),
            "focus_survival": focus_survival,
            "focus_support_value": round(focus_support, 1),
            "focus_utility_outcomes": utility_by_actor.get(focus_participant_id, {}),
            "focus_healing": round(focus_healing, 1),
            "main_team_effective_health": round(
                sum(
                    float(survival[actor.participant_id]["effective_health"])
                    for actor in all_actors
                    if actor.team in {"main", "ally"}
                ),
                1,
            ),
            "enemy_team_effective_health": round(
                sum(
                    float(survival[actor.participant_id]["effective_health"])
                    for actor in all_actors
                    if actor.team == "enemy"
                ),
                1,
            ),
            "total_support_value": round(sum(support_by_attacker.values()), 1),
            "total_healing_reduced": round(
                sum(float(state["healing_reduced"]) for state in survival.values()),
                1,
            ),
        },
        "timeline_coverage": combine_timeline_coverages(
            coverage_reports,
            target_count=len(coverage_reports),
        ),
    }
