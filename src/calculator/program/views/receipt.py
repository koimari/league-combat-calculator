"""The receipt view — the one producer of a public event dict.

The serialized timeline is the calculator's most-read output and it was built
inside a nine-hundred-line return literal at the bottom of the composition:
three event streams, a utility receipt, a target-allocation receipt, an
objective block and the participants list, all in one expression, with every
digit count spelled at its own call site.  A published field could be added,
renamed or silently re-rounded there and no layer could see it happen.

This module is where that projection lives now.  Every published row comes out
of one of the three row builders below, so "who produces a public event dict"
has an answer that is a file rather than a search; every digit count comes
from :mod:`program.precision`, keyed by the leaf's path in the payload,
because ``amount`` means one digit on a healing row and six on a support row
and a flat registry would have had to guess.

It re-runs no arithmetic.  The three streams arrive ordered, the ten objective
aggregates arrive summed, and the target-allocation receipt arrives built --
all folded once by the composition, because a view that adds is a view that
can disagree with the walk it claims to project.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ..precision import round_field
from . import LeafWriter
from .breakdown import breakdown
from .survival import survival
from .tdd import tdd_leaves

__all__ = ["receipt"]


def _damage_event_rows(events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """One published damage row per annotated event, in walk order."""
    return [
        {
            "time": round_field("events.time", float(event.get("time", 0.0))),
            "attacker": event.get("attacker"),
            "target": event.get("target"),
            "source": event.get("source_key", ""),
            "damage_type": event.get("damage_type", ""),
            "damage": round_field("events.damage", float(event.get("damage", 0.0))),
            "raw_damage": round_field(
                "events.raw_damage",
                float(event.get("raw_damage", event.get("damage", 0.0))),
            ),
            "pair_damage": round_field(
                "events.pair_damage",
                float(event.get("pair_damage", event.get("damage", 0.0))),
            ),
            "overkill": round_field(
                "events.overkill", float(event.get("overkill", 0.0))
            ),
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
                {"reactive_shield_triggered": dict(event["reactive_shield_triggered"])}
                if event.get("reactive_shield_triggered")
                else {}
            ),
            **(
                {
                    "maw_lifeline_omnivamp_activated": round_field(
                        "events.maw_lifeline_omnivamp_activated",
                        float(event["maw_lifeline_omnivamp_activated"]),
                    )
                }
                if event.get("maw_lifeline_omnivamp_activated") is not None
                else {}
            ),
            **(
                {
                    "threshold_shield_expires_at": round_field(
                        "events.threshold_shield_expires_at",
                        float(event["threshold_shield_expires_at"]),
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
            # A live-predicate amplifier that rode this packet.  It is
            # published because the bonus is folded into the host row's
            # damage rather than filed as a source of its own, and a
            # number with no rule beside it is exactly what this campaign
            # exists to stop shipping.
            **(
                {
                    "live_amp": {
                        "mechanic": str(event["live_amp_source"]),
                        "bonus": round_field(
                            "events.live_amp_bonus", float(event["live_amp_bonus"])
                        ),
                    }
                }
                if event.get("live_amp_source")
                else {}
            ),
            **({"execute_triggered": True} if event.get("execute_triggered") else {}),
            **(
                {
                    "redirected_amount": round_field(
                        "events.redirected_amount", float(event["_redirected_amount"])
                    )
                }
                if event.get("_redirected_amount") is not None
                else {}
            ),
            **(
                {"redirected_from": str(event["_redirected_from"])}
                if event.get("_redirected_from")
                else {}
            ),
            **(
                {
                    "redirect_fraction": round_field(
                        "events.redirect_fraction", float(event["_redirect_fraction"])
                    )
                }
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
                    "incoming_damage_multiplier": round_field(
                        "events.incoming_damage_multiplier",
                        float(event["incoming_damage_multiplier"]),
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
                    "incoming_damage_reduction": round_field(
                        "events.incoming_damage_reduction",
                        float(event["incoming_damage_reduction"]),
                    )
                }
                if event.get("incoming_damage_reduction") is not None
                else {}
            ),
            **(
                {"support_damage_multiplier": dict(event["support_damage_multiplier"])}
                if event.get("support_damage_multiplier")
                else {}
            ),
            **(
                {"support_damage_reduction": dict(event["support_damage_reduction"])}
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
                    "wound_duration": round_field(
                        "events.wound_duration", float(event["grievous_duration"])
                    ),
                    "wound_until": round_field(
                        "events.wound_until",
                        float(
                            event.get(
                                "_wound_until",
                                float(event.get("time", 0.0))
                                + float(event["grievous_duration"]),
                            )
                        ),
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
                {
                    "grey_health_stored": round_field(
                        "events.grey_health_stored", float(event["grey_health_stored"])
                    )
                }
                if event.get("grey_health_stored") is not None
                else {}
            ),
        }
        for event in events
    ]


def _healing_event_rows(events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """One published healing row per annotated event, in walk order."""
    return [
        {
            "time": round_field("healing_events.time", float(event.get("time", 0.0))),
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
            "amount": round_field(
                "healing_events.amount", float(event.get("amount", 0.0))
            ),
            "raw_amount": round_field(
                "healing_events.raw_amount",
                float(event.get("raw_amount", event.get("amount", 0.0))),
            ),
            "applied_amount": round_field(
                "healing_events.applied_amount",
                float(event.get("applied_amount", event.get("amount", 0.0))),
            ),
            "overheal": round_field(
                "healing_events.overheal",
                float(
                    event.get(
                        "overheal",
                        max(
                            0.0,
                            float(event.get("reduced_amount", event.get("amount", 0.0)))
                            - float(
                                event.get("applied_amount", event.get("amount", 0.0))
                            ),
                        ),
                    )
                ),
            ),
            "temporary_health": round_field(
                "healing_events.temporary_health",
                float(event.get("temporary_health", 0.0)),
            ),
            **(
                {
                    "temporary_health_expires_at": round_field(
                        "healing_events.temporary_health_expires_at",
                        float(event["temporary_health_expires_at"]),
                    )
                }
                if event.get("temporary_health_expires_at") is not None
                else {}
            ),
            "reduced_amount": round_field(
                "healing_events.reduced_amount",
                float(event.get("reduced_amount", event.get("amount", 0.0))),
            ),
            "healing_reduction_factor": round_field(
                "healing_events.healing_reduction_factor",
                float(event.get("healing_reduction_factor", 1.0)),
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
                    "ichorshield_generated": round_field(
                        "healing_events.ichorshield_generated",
                        float(event["ichorshield_generated"]),
                    )
                }
                if event.get("ichorshield_generated") is not None
                else {}
            ),
            **(
                {
                    "ichorshield_total": round_field(
                        "healing_events.ichorshield_total",
                        float(event["ichorshield_total"]),
                    )
                }
                if event.get("ichorshield_total") is not None
                else {}
            ),
        }
        for event in events
    ]


def _support_event_rows(events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """One published support row per armed template, in reading order."""
    return [
        {
            "time": round_field("support_events.time", float(event.get("time", 0.0))),
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
            "amount": round_field(
                "support_events.amount", float(event.get("amount", 0.0))
            ),
            "applied_amount": round_field(
                "support_events.applied_amount",
                float(event.get("applied_amount", event.get("amount", 0.0))),
            ),
            # Present only on an arming a declared ``IDEMPOTENT_AURA``
            # collapsed into an earlier holder's (D-66).  Absent
            # everywhere else, so the key's presence *is* the statement
            # and a zero applied amount never has to be interpreted.
            **({"dedupe": event["dedupe"]} if event.get("dedupe") else {}),
            "target_scope": event.get("target_scope", ""),
            "target_policy": event.get("target_policy", ""),
            **(
                {
                    key: round_field(f"support_events.{key}", float(event[key]))
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
                {
                    "duration": round_field(
                        "support_events.duration", float(event["duration"])
                    )
                }
                if event.get("duration") is not None
                else {}
            ),
            **(
                {
                    "expires_at": round_field(
                        "support_events.expires_at", float(event["expires_at"])
                    )
                }
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
        for event in events
    ]


def receipt(program: Any, result: Any) -> dict[str, Any]:
    """Project one walk into the serialized combat receipt.

    The participants block publishes each actor's stats and items beside its
    survival row, which is the one thing the score projection deliberately
    leaves out: nothing displays a candidate's timeline, so nothing pays for
    serializing one.  Both projections read the same walk.
    """
    rows = survival(program, result)
    # The ``dispositions`` map is built here and published by the commit that
    # bumps the schema, one commit later: landing the five views and changing
    # the wire shape in one commit would make a payload move unattributable
    # to either.  The producer is already the only writer of a leaf and of its
    # entry, so publishing it is a key in this literal and nothing else.
    writer = LeafWriter()
    objective = tdd_leaves(program, result, writer)
    return {
        "duration": float(result.duration),
        "participants": [
            {
                "participant_id": actor.participant_id,
                "team": actor.team,
                "champion": actor.champion_data.get("name", ""),
                "level": actor.level,
                "stats": dict(actor.stats),
                "items": [item.get("name", "") for item in actor.items],
                "survival": rows[actor.participant_id],
            }
            for actor in program.actors
        ],
        "breakdown": breakdown(program, result),
        "events": _damage_event_rows(result.damage_events),
        "healing_events": _healing_event_rows(result.healing_events),
        "support_events": _support_event_rows(result.support_events),
        "utility_outcomes": {
            "contract": "utility_outcomes_v1",
            "participants": {
                actor.participant_id: result.utility_by_actor[actor.participant_id]
                for actor in program.actors
            },
            "focus": result.utility_by_actor.get(program.focus, {}),
            "metric_note": (
                "Utility dimensions are reported in their native units. The "
                "calculator does not convert movement, cleanse, vision, or "
                "economy into TDD or a guessed common scalar."
            ),
        },
        "target_allocation": result.target_allocation,
        "objective": objective,
        "timeline_coverage": result.timeline_coverage,
    }
