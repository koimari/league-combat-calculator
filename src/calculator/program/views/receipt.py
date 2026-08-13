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
from .breakdown import breakdown_leaves
from .survival import survival_leaves
from .tdd import tdd_leaves

__all__ = ["receipt"]


# The support row's three key families, named rather than inline: a support
# template is a declaration with dozens of optional fields, and the three
# loops that read them differ only in what a present value *is* -- a quantity
# that carries a disposition, a flag, or a label.  Publishing them from named
# tuples is what keeps the quantity family the one that writes leaves.
_SUPPORT_QUANTITY_KEYS = (
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

_SUPPORT_FLAG_KEYS = (
    "damage_reduction",
    "next_event_only",
    "all_sources",
    "cleanse",
    "persistent",
    "completion_granted",
)

_SUPPORT_LABEL_KEYS = (
    "resistance_type",
    "owner",
    "range_assumption",
    "trigger_kind",
    "source_url",
)


def _damage_event_rows(
    events: Sequence[Mapping[str, Any]], writer: LeafWriter, prefix: str
) -> list[dict[str, Any]]:
    """One published damage row per annotated event, in walk order."""
    rows: list[dict[str, Any]] = []
    for index, event in enumerate(events):
        row: dict[str, Any] = {}
        leaf = writer.block(row, f"{prefix}[{index}]")
        leaf.measured("time", round_field("events.time", float(event.get("time", 0.0))))
        leaf.raw("attacker", event.get("attacker"))
        leaf.raw("target", event.get("target"))
        leaf.raw("source", event.get("source_key", ""))
        leaf.raw("damage_type", event.get("damage_type", ""))
        leaf.measured(
            "damage", round_field("events.damage", float(event.get("damage", 0.0)))
        )
        leaf.measured(
            "raw_damage",
            round_field(
                "events.raw_damage",
                float(event.get("raw_damage", event.get("damage", 0.0))),
            ),
        )
        leaf.measured(
            "pair_damage",
            round_field(
                "events.pair_damage",
                float(event.get("pair_damage", event.get("damage", 0.0))),
            ),
        )
        leaf.measured(
            "overkill",
            round_field("events.overkill", float(event.get("overkill", 0.0))),
        )
        leaf.raw("event_precision", event.get("event_precision", "exact"))
        if event.get("_event_id") is not None:
            leaf.raw("event_id", str(event["_event_id"]))
        if event.get("_trigger_event_id") is not None:
            leaf.raw("trigger_event_id", str(event["_trigger_event_id"]))
        if event.get("sequence") is not None:
            leaf.raw("sequence", int(event["sequence"]))
        if event.get("_reactive"):
            leaf.raw("reactive", True)
        if event.get("spell_shield_source"):
            leaf.raw("spell_shield_source", str(event["spell_shield_source"]))
        if event.get("threshold_shield_triggered"):
            leaf.raw("threshold_shield_triggered", True)
        if event.get("reactive_shield_triggered"):
            leaf.structure(
                "reactive_shield_triggered", dict(event["reactive_shield_triggered"])
            )
        if event.get("maw_lifeline_omnivamp_activated") is not None:
            leaf.measured(
                "maw_lifeline_omnivamp_activated",
                round_field(
                    "events.maw_lifeline_omnivamp_activated",
                    float(event["maw_lifeline_omnivamp_activated"]),
                ),
            )
        if event.get("threshold_shield_expires_at") is not None:
            leaf.measured(
                "threshold_shield_expires_at",
                round_field(
                    "events.threshold_shield_expires_at",
                    float(event["threshold_shield_expires_at"]),
                ),
            )
        if event.get("threshold_health_triggered"):
            leaf.raw("threshold_health_triggered", True)
        # A live-predicate amplifier that rode this packet.  It is
        # published because the bonus is folded into the host row's
        # damage rather than filed as a source of its own, and a
        # number with no rule beside it is exactly what this campaign
        # exists to stop shipping.
        if event.get("live_amp_source"):
            amp: dict[str, Any] = {}
            leaf.raw("live_amp", amp)
            inner = leaf.nested(amp, "live_amp")
            inner.raw("mechanic", str(event["live_amp_source"]))
            inner.measured(
                "bonus",
                round_field("events.live_amp_bonus", float(event["live_amp_bonus"])),
            )
        if event.get("execute_triggered"):
            leaf.raw("execute_triggered", True)
        if event.get("_redirected_amount") is not None:
            leaf.measured(
                "redirected_amount",
                round_field(
                    "events.redirected_amount", float(event["_redirected_amount"])
                ),
            )
        if event.get("_redirected_from"):
            leaf.raw("redirected_from", str(event["_redirected_from"]))
        if event.get("_redirect_fraction") is not None:
            leaf.measured(
                "redirect_fraction",
                round_field(
                    "events.redirect_fraction", float(event["_redirect_fraction"])
                ),
            )
        if event.get("redirect_source"):
            leaf.raw("redirect_source", str(event["redirect_source"]))
        if event.get("redirect_pre_mitigation"):
            leaf.raw("redirect_pre_mitigation", True)
        if event.get("redirect_attributed_to"):
            leaf.raw("redirect_attributed_to", str(event["redirect_attributed_to"]))
        if event.get("redirect_range_units") is not None:
            leaf.raw("redirect_range_units", int(event["redirect_range_units"]))
        if event.get("redirect_skipped_reason"):
            leaf.raw("redirect_skipped_reason", str(event["redirect_skipped_reason"]))
        if event.get("incoming_damage_multiplier") is not None:
            leaf.measured(
                "incoming_damage_multiplier",
                round_field(
                    "events.incoming_damage_multiplier",
                    float(event["incoming_damage_multiplier"]),
                ),
            )
        if event.get("incoming_damage_source"):
            leaf.raw("incoming_damage_source", str(event["incoming_damage_source"]))
        if event.get("incoming_damage_reduction") is not None:
            leaf.measured(
                "incoming_damage_reduction",
                round_field(
                    "events.incoming_damage_reduction",
                    float(event["incoming_damage_reduction"]),
                ),
            )
        if event.get("support_damage_multiplier"):
            leaf.structure(
                "support_damage_multiplier", dict(event["support_damage_multiplier"])
            )
        if event.get("support_damage_reduction"):
            leaf.structure(
                "support_damage_reduction", dict(event["support_damage_reduction"])
            )
        if event.get("support_resistance_reduction"):
            leaf.structure(
                "support_resistance_reduction",
                list(event["support_resistance_reduction"]),
            )
        if event.get("support_on_hit_magic"):
            leaf.raw("support_on_hit_magic", list(event["support_on_hit_magic"]))
        if isinstance(event.get("targeting"), Mapping):
            leaf.structure("targeting", dict(event["targeting"]))
        if event.get("_deferred_from"):
            leaf.raw("deferred_from", str(event["_deferred_from"]))
        if event.get("_wound_source"):
            leaf.raw("wound_source", str(event["_wound_source"]))
        if event.get("grievous_duration") is not None:
            leaf.measured(
                "wound_duration",
                round_field("events.wound_duration", float(event["grievous_duration"])),
            )
            leaf.measured(
                "wound_until",
                round_field(
                    "events.wound_until",
                    float(
                        event.get(
                            "_wound_until",
                            float(event.get("time", 0.0))
                            + float(event["grievous_duration"]),
                        )
                    ),
                ),
            )
        if event.get("healing_reduction"):
            leaf.structure("healing_reduction", dict(event["healing_reduction"]))
        if event.get("venom") is not None:
            leaf.structure("venom", dict(event["venom"]))
        if event.get("skipped_reason"):
            leaf.raw("skipped_reason", str(event["skipped_reason"]))
        if event.get("grey_health_stored") is not None:
            leaf.measured(
                "grey_health_stored",
                round_field(
                    "events.grey_health_stored", float(event["grey_health_stored"])
                ),
            )
        rows.append(row)
    return rows


def _healing_event_rows(
    events: Sequence[Mapping[str, Any]], writer: LeafWriter, prefix: str
) -> list[dict[str, Any]]:
    """One published healing row per annotated event, in walk order."""
    rows: list[dict[str, Any]] = []
    for index, event in enumerate(events):
        row: dict[str, Any] = {}
        leaf = writer.block(row, f"{prefix}[{index}]")
        leaf.measured(
            "time", round_field("healing_events.time", float(event.get("time", 0.0)))
        )
        leaf.raw("attacker", event.get("attacker"))
        leaf.raw("source", event.get("source", ""))
        if event.get("_event_id") is not None:
            leaf.raw("event_id", str(event["_event_id"]))
        if event.get("_trigger_event_id") is not None:
            leaf.raw("trigger_event_id", str(event["_trigger_event_id"]))
        if event.get("trigger_target") is not None:
            leaf.raw("trigger_target", str(event["trigger_target"]))
        leaf.measured(
            "amount",
            round_field("healing_events.amount", float(event.get("amount", 0.0))),
        )
        leaf.measured(
            "raw_amount",
            round_field(
                "healing_events.raw_amount",
                float(event.get("raw_amount", event.get("amount", 0.0))),
            ),
        )
        leaf.measured(
            "applied_amount",
            round_field(
                "healing_events.applied_amount",
                float(event.get("applied_amount", event.get("amount", 0.0))),
            ),
        )
        leaf.measured(
            "overheal",
            round_field(
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
        )
        leaf.measured(
            "temporary_health",
            round_field(
                "healing_events.temporary_health",
                float(event.get("temporary_health", 0.0)),
            ),
        )
        if event.get("temporary_health_expires_at") is not None:
            leaf.measured(
                "temporary_health_expires_at",
                round_field(
                    "healing_events.temporary_health_expires_at",
                    float(event["temporary_health_expires_at"]),
                ),
            )
        leaf.measured(
            "reduced_amount",
            round_field(
                "healing_events.reduced_amount",
                float(event.get("reduced_amount", event.get("amount", 0.0))),
            ),
        )
        leaf.measured(
            "healing_reduction_factor",
            round_field(
                "healing_events.healing_reduction_factor",
                float(event.get("healing_reduction_factor", 1.0)),
            ),
        )
        if event.get("skipped_reason"):
            leaf.raw("skipped_reason", str(event["skipped_reason"]))
        if event.get("_grey_health"):
            leaf.raw("grey_health", True)
        if event.get("charges") is not None:
            leaf.raw("charges", int(event["charges"]))
        if event.get("ichorshield_generated") is not None:
            leaf.measured(
                "ichorshield_generated",
                round_field(
                    "healing_events.ichorshield_generated",
                    float(event["ichorshield_generated"]),
                ),
            )
        if event.get("ichorshield_total") is not None:
            leaf.measured(
                "ichorshield_total",
                round_field(
                    "healing_events.ichorshield_total",
                    float(event["ichorshield_total"]),
                ),
            )
        rows.append(row)
    return rows


def _support_event_rows(
    events: Sequence[Mapping[str, Any]], writer: LeafWriter, prefix: str
) -> list[dict[str, Any]]:
    """One published support row per armed template, in reading order."""
    rows: list[dict[str, Any]] = []
    for index, event in enumerate(events):
        row: dict[str, Any] = {}
        leaf = writer.block(row, f"{prefix}[{index}]")
        leaf.measured(
            "time", round_field("support_events.time", float(event.get("time", 0.0)))
        )
        leaf.raw("attacker", event.get("attacker"))
        leaf.raw("target", event.get("target"))
        leaf.raw("recipient", event.get("target"))
        if event.get("_event_id") is not None:
            leaf.raw("event_id", str(event["_event_id"]))
        if event.get("_trigger_event_id") is not None:
            leaf.raw("trigger_event_id", str(event["_trigger_event_id"]))
        if event.get("_source_event_id") is not None:
            leaf.raw("source_event_id", str(event["_source_event_id"]))
        leaf.raw("source", event.get("source", ""))
        leaf.raw("kind", event.get("kind", ""))
        leaf.measured(
            "amount",
            round_field("support_events.amount", float(event.get("amount", 0.0))),
        )
        leaf.measured(
            "applied_amount",
            round_field(
                "support_events.applied_amount",
                float(event.get("applied_amount", event.get("amount", 0.0))),
            ),
        )
        # Present only on an arming a declared ``IDEMPOTENT_AURA``
        # collapsed into an earlier holder's (D-66).  Absent
        # everywhere else, so the key's presence *is* the statement
        # and a zero applied amount never has to be interpreted.
        if event.get("dedupe"):
            leaf.raw("dedupe", event["dedupe"])
        leaf.raw("target_scope", event.get("target_scope", ""))
        leaf.raw("target_policy", event.get("target_policy", ""))
        for key in _SUPPORT_QUANTITY_KEYS:
            if event.get(key) is not None:
                leaf.measured(
                    key,
                    round_field(f"support_events.{key}", float(event[key])),
                )
        for key in _SUPPORT_FLAG_KEYS:
            if event.get(key) is not None:
                leaf.raw(key, bool(event[key]))
        if event.get("trigger") is not None:
            leaf.raw("trigger", str(event["trigger"]))
        for key in _SUPPORT_LABEL_KEYS:
            if event.get(key) is not None:
                leaf.raw(key, str(event[key]))
        if event.get("duration") is not None:
            leaf.measured(
                "duration",
                round_field("support_events.duration", float(event["duration"])),
            )
        if event.get("expires_at") is not None:
            leaf.measured(
                "expires_at",
                round_field("support_events.expires_at", float(event["expires_at"])),
            )
        if event.get("venom") is not None:
            leaf.structure("venom", dict(event["venom"]))
        if event.get("source_revision_id") is not None:
            leaf.raw("source_revision_id", int(event["source_revision_id"]))
        if event.get("skipped_reason"):
            leaf.raw("skipped_reason", str(event["skipped_reason"]))
        rows.append(row)
    return rows


def receipt(program: Any, result: Any) -> dict[str, Any]:
    """Project one walk into the serialized combat receipt.

    The participants block publishes each actor's stats and items beside its
    survival row, which is the one thing the score projection deliberately
    leaves out: nothing displays a candidate's timeline, so nothing pays for
    serializing one.  Both projections read the same walk.
    """
    writer = LeafWriter()
    rows = survival_leaves(program, result, writer, "participants.survival")
    attacker_rows = breakdown_leaves(program, result, writer)
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
        "breakdown": attacker_rows,
        "events": _damage_event_rows(result.damage_events, writer, "events"),
        "healing_events": _healing_event_rows(
            result.healing_events, writer, "healing_events"
        ),
        "support_events": _support_event_rows(
            result.support_events, writer, "support_events"
        ),
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
        "dispositions": writer.entries(),
    }
