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
can disagree with the walk it claims to project.  A wound window's end and a
skipped recovery's overheal are written by the composition that annotates the
event and read here by name: a number a view can produce for itself is a
number with two producers, whatever the expression looks like.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ...capabilities import PRE_COMBAT_STATS
from ...survival.outcome_state import outcome_quantity
from ..build import Program
from ..precision import round_field, sum_plan
from ..walk import WalkResult
from . import LeafBlock, LeafWriter
from .breakdown import breakdown_leaves
from .survival import participant_paths, survival_leaves
from .tdd import tdd_leaves

__all__ = ["receipt"]


def _outcome(leaf: LeafBlock, key: str, value: float, refusal: str | None) -> None:
    """Publish one outcome field: a refused row's zero is declared, not measured."""
    leaf.put(key, outcome_quantity(value, refusal))


def _refusal(event: Mapping[str, Any]) -> str | None:
    """This row's refusal, or ``None`` if the walk priced it; empty means none."""
    reason = event.get("skipped_reason")
    return str(reason) if reason else None


# The support row's three key families, named rather than inline: a support
# template is a declaration with dozens of optional fields, and the three
# loops that read them differ only in what a present value *is* -- a quantity
# that carries a disposition, a flag, or a label.  Publishing them from named
# tuples is what keeps the quantity family the one that writes leaves.
_SUPPORT_QUANTITY_KEYS = (
    "bonus_attack_speed_percent",
    "bonus_armor",
    "bonus_magic_resistance",
    "bonus_health",
    "permanent_bonus_health",
    "on_hit_magic_damage",
    "ability_power",
    "ability_haste",
    "bonus_move_speed_percent",
    "slow_resist_percent",
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
    "aftershock_duration",
    "aftershock_cooldown",
    "glacial_ray_count",
    "glacial_zone_radius_units",
    "glacial_zone_width_units",
    "glacial_zone_duration",
    "glacial_slow_percent",
    "glacial_damage_reduction_ratio",
    "stormraider_damage_threshold_ratio",
    "stormraider_damage_window_seconds",
    "stormraider_trigger_damage",
    "stormraider_target_max_health",
    "stormraider_cooldown_seconds",
    "fleet_starting_charges",
    "fleet_charge_cap",
    "fleet_move_speed_duration_seconds",
    "stacks_before",
    "stacks_after",
    "stacks_gained",
    "max_stacks",
    "adaptive_force",
    "shield_gate_time",
    "activation_delay",
    "on_block_heal_amount",
    "on_block_heal_delay",
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
    "requires_existing_shield",
    "shield_gate_assumed",
)

_SUPPORT_LABEL_KEYS = (
    "resistance_type",
    "owner",
    "aftershock_trigger_kind",
    "source_participant",
    "shield_gate_target",
    "range_assumption",
    "trigger_kind",
    "packet",
    "trigger_source",
    "source_url",
    "on_block_heal_source",
    "range_center",
    "range_input_status",
    "range_boundary_status",
    # The two H2 fields.  ``cc_scope`` is the reviewed CcScope a crowd-control
    # mark was routed under and ``cc_scope_disclosure`` is the sentence that
    # qualifies it when the reading was the shipped default rather than a
    # sourced one.  Published, because a routing assumption a receipt cannot
    # state is a routing assumption nobody can check.
    "cc_scope",
    "cc_scope_disclosure",
)


def _damage_event_rows(
    events: Sequence[Mapping[str, Any]], writer: LeafWriter, prefix: str
) -> list[dict[str, Any]]:
    """One published damage row per annotated event, in walk order."""
    rows: list[dict[str, Any]] = []
    for index, event in enumerate(events):
        row: dict[str, Any] = {}
        leaf = writer.block(row, f"{prefix}[{index}]")
        refusal = _refusal(event)
        leaf.measured("time", round_field("events.time", float(event.get("time", 0.0))))
        leaf.raw("attacker", event.get("attacker"))
        leaf.raw("target", event.get("target"))
        leaf.raw("source", event.get("source_key", ""))
        leaf.raw("damage_type", event.get("damage_type", ""))
        _outcome(
            leaf,
            "damage",
            round_field("events.damage", float(event.get("damage", 0.0))),
            refusal,
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
        _outcome(
            leaf,
            "overkill",
            round_field("events.overkill", float(event.get("overkill", 0.0))),
            refusal,
        )
        leaf.raw("event_precision", event.get("event_precision", "exact"))
        # The delivery and control facts a certified packet carries.  Every
        # one is conditional, so an absent key is "this packet declared
        # none" rather than a measured zero -- which is why the boolean
        # three publish only ``True`` and never ``False``.
        if event.get("cc_kind") is not None:
            leaf.raw("cc_kind", str(event["cc_kind"]))
        if event.get("cc_duration") is not None:
            leaf.measured(
                "cc_duration",
                round_field("events.cc_duration", float(event["cc_duration"])),
            )
        if event.get("cc_magnitude"):
            # The control's sourced strength, in the units its cached row
            # states -- a slow's percent.  The engine omits the key entirely
            # for a kind that carries no magnitude, so an absent leaf is that
            # declaration and not a measured zero.
            leaf.measured(
                "cc_magnitude",
                round_field("events.cc_magnitude", float(event["cc_magnitude"])),
            )
        if event.get("control_source_atoms"):
            leaf.structure(
                "control_source_atoms",
                [dict(atom) for atom in event["control_source_atoms"]],
            )
        if event.get("damage_over_time"):
            leaf.raw("damage_over_time", True)
        if event.get("skillshot"):
            leaf.raw("skillshot", True)
        if event.get("area_damage"):
            leaf.raw("area_damage", True)
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
            leaf.structure("support_on_hit_magic", list(event["support_on_hit_magic"]))
        # The three kernel-authored interaction receipts that ride a damage
        # packet: the control it applied, the immunity that refused that
        # control, and the projectile defense that reduced or destroyed the
        # packet.  Each is written by ``transitions`` through the ledger, so
        # publishing them is what makes a blocked packet's *reason* readable
        # rather than inferable from a zero.
        if event.get("crowd_control"):
            leaf.structure("crowd_control", dict(event["crowd_control"]))
        if event.get("crowd_control_blocked"):
            leaf.structure(
                "crowd_control_blocked", dict(event["crowd_control_blocked"])
            )
        if event.get("projectile_defense"):
            leaf.structure("projectile_defense", dict(event["projectile_defense"]))
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
                round_field("events.wound_until", float(event["_wound_until"])),
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
        refusal = _refusal(event)
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
        _outcome(
            leaf,
            "applied_amount",
            round_field(
                "healing_events.applied_amount",
                float(event.get("applied_amount", event.get("amount", 0.0))),
            ),
            refusal,
        )
        leaf.measured(
            "overheal",
            round_field("healing_events.overheal", float(event["overheal"])),
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
        refusal = _refusal(event)
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
        # The pre-mitigation figure the packet was authored at.  A support
        # heal that healing reduction cut still says what it was worth, the
        # same way the healing rows do, so a reader comparing a self copy
        # with its fan-out copy reads one field on both.
        leaf.measured(
            "raw_amount",
            round_field(
                "support_events.raw_amount",
                float(event.get("raw_amount", event.get("amount", 0.0))),
            ),
        )
        _outcome(
            leaf,
            "applied_amount",
            round_field(
                "support_events.applied_amount",
                float(event.get("applied_amount", event.get("amount", 0.0))),
            ),
            refusal,
        )
        # Present only on an arming a declared ``IDEMPOTENT_AURA``
        # collapsed into an earlier holder's (D-66).  Absent
        # everywhere else, so the key's presence *is* the statement
        # and a zero applied amount never has to be interpreted.
        if event.get("dedupe"):
            leaf.raw("dedupe", event["dedupe"])
        leaf.measured(
            "reduced_amount",
            round_field(
                "support_events.reduced_amount",
                float(event.get("reduced_amount", event.get("amount", 0.0))),
            ),
        )
        # By name only.  Main's projection fell back to
        # ``reduced_amount - applied_amount`` when the key was absent, which
        # made the view a second producer of a published number; the
        # composition that annotates the packet writes it, and an event with
        # no overheal publishes none.
        if event.get("overheal") is not None:
            leaf.measured(
                "overheal",
                round_field("support_events.overheal", float(event["overheal"])),
            )
        if event.get("healing_reduction_factor") is not None:
            leaf.measured(
                "healing_reduction_factor",
                round_field(
                    "support_events.healing_reduction_factor",
                    float(event["healing_reduction_factor"]),
                ),
            )
        leaf.raw("target_scope", event.get("target_scope", ""))
        leaf.raw("target_policy", event.get("target_policy", ""))
        # Which declared selection rule picked this recipient.  Published
        # unconditionally, with the empty string for a packet whose producer
        # names no rule, because "this template selected nobody in
        # particular" is an answer a consumer reads rather than infers.
        leaf.raw("target_selection_key", event.get("target_selection_key", ""))
        if event.get("shield_pool"):
            leaf.raw("shield_pool", str(event["shield_pool"]))
        # The pair is published together or not at all: a while-held immunity
        # with no named source would be an unattributed capability.
        if event.get("crowd_control_immunity_while_shield"):
            leaf.raw("crowd_control_immunity_while_shield", True)
            leaf.raw(
                "crowd_control_immunity_source",
                str(
                    event.get("crowd_control_immunity_source", event.get("source", ""))
                ),
            )
        for key in ("source_atom", "duration_atom", "activation_delay_atom"):
            if event.get(key) is not None:
                leaf.structure(key, dict(event[key]))
        if event.get("amount_formula_atom") is not None:
            leaf.structure("amount_formula_atom", dict(event["amount_formula_atom"]))
        if event.get("source_atoms"):
            leaf.structure(
                "source_atoms", [dict(atom) for atom in event["source_atoms"]]
            )
        if event.get("aftershock") is not None:
            leaf.structure("aftershock", dict(event["aftershock"]))
        if event.get("crowd_control_blocked") is not None:
            leaf.structure(
                "crowd_control_blocked", dict(event["crowd_control_blocked"])
            )
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


def receipt(program: Program, result: WalkResult) -> dict[str, Any]:
    """Project one walk into the serialized combat receipt.

    The participants block publishes each actor's stats and items beside its
    survival row, which is the one thing the score projection deliberately
    leaves out: nothing displays a candidate's timeline, so nothing pays for
    serializing one.  Both projections read the same walk.
    """
    writer = LeafWriter()
    payload: dict[str, Any] = {}
    root = writer.block(payload, "")
    rows = survival_leaves(program, result, writer, participant_paths(program))
    root.measured("duration", float(result.duration))
    root.raw("participants", _participant_rows(program, rows, writer))
    root.raw("breakdown", breakdown_leaves(program, result, writer))
    events = _damage_event_rows(result.damage_events, writer, "events")
    healing_events = _healing_event_rows(
        result.healing_events, writer, "healing_events"
    )
    support_events = _support_event_rows(
        result.support_events, writer, "support_events"
    )
    # D-65: the three panels are three sources a reader unions, and what
    # kept that union from double-counting was a comment.  Building the plan
    # *is* the check -- ``SumPlan`` refuses at construction -- so a receipt
    # **one of whose panels published an event id twice** fails here rather
    # than serving rows that repeat.  Not a shared id across two panels:
    # that is a support packet that delivered damage, it is recorded in
    # ``SumPlan.shared`` and it serves.  Discarded rather than published:
    # what it declares is a property of the payload below, not a leaf of it.
    #
    # **This is a refusal on the serving path**, so say so: a receipt that
    # served before and repeats an id within one panel now raises out of
    # ``/api/calculate`` instead.  Deliberate and fail-closed -- a panel
    # repeating its own id has no benign reading and no symptom, which is
    # exactly the shape that must not serve -- and empty in practice: no
    # production total folds over ``SumPlan.ids``, so nothing published
    # today was double-counting and nothing published today can trip it.
    # The permanent red is ``tests/test_program_precision.py``'s
    # ``DuplicateSumMember`` pair; the endpoint's own arm -- a named 400,
    # never a 500 and never a served payload -- is asserted in
    # ``tests/test_app.py``.
    sum_plan(
        {
            "events": events,
            "healing_events": healing_events,
            "support_events": support_events,
        }
    )
    root.raw("events", events)
    root.raw("healing_events", healing_events)
    root.raw("support_events", support_events)
    root.raw("utility_outcomes", _utility_block(program, result, writer))
    root.structure("target_allocation", result.target_allocation)
    # A denial is a receipt with no applied amount, so it is published as
    # its own section rather than as a zero packet a reader would have to
    # interpret.  Ordered by (time, reason) so two denials at one
    # timestamp read the same way on every run.
    root.structure(
        "item_denial_receipts",
        sorted(
            (dict(receipt) for receipt in result.item_denial_receipts),
            key=lambda row: (
                float(row.get("time", 0.0) or 0.0),
                str(row.get("reason", "")),
            ),
        ),
    )
    root.raw("objective", tdd_leaves(program, result, writer, rows))
    root.structure("timeline_coverage", result.timeline_coverage)
    payload["dispositions"] = writer.entries()
    return payload


def _participant_rows(
    program: Program, rows: Mapping[str, dict[str, Any]], writer: LeafWriter
) -> list[dict[str, Any]]:
    """One published participant per roster slot: who it is, and what happened.

    The stats block goes through :meth:`~..views.LeafBlock.structure` rather
    than being assigned whole.  Ninety-odd numbers describing a champion at a
    level holding items are published numbers like any others, and they were
    the largest block of the payload that carried no entry -- a stat card a
    consumer renders straight from bare leaves, saying nothing about whether
    a rule produced them.
    """
    published: list[dict[str, Any]] = []
    for index, actor in enumerate(program.actors):
        row: dict[str, Any] = {}
        published.append(row)
        block = writer.block(row, f"participants[{index}]")
        block.raw("participant_id", actor.participant_id)
        block.raw("team", actor.team)
        block.raw("champion", actor.champion_data.get("name", ""))
        block.raw("level", actor.level)
        block.structure("stats", dict(actor.stats))
        # Which fight state that block reports. A raw leaf, deliberately:
        # it is a label on the numbers, not one of them.
        block.raw("stats_state", PRE_COMBAT_STATS)
        block.raw("items", [item.get("name", "") for item in actor.items])
        block.raw("survival", rows[actor.participant_id])
    return published


def _utility_block(
    program: Program, result: WalkResult, writer: LeafWriter
) -> dict[str, Any]:
    """The utility receipt, in native units, with every unit named.

    The note is the block's own declaration and stays exactly as published.
    What changes is that the numbers under it are written through the one
    writer: "the calculator does not convert these into a common scalar" is a
    statement about what the numbers *mean*, not a reason for them to be the
    one published block that says nothing about where they came from.
    """
    block: dict[str, Any] = {}
    leaf = writer.block(block, "utility_outcomes")
    leaf.raw("contract", "utility_outcomes_v1")
    leaf.structure(
        "participants",
        {
            actor.participant_id: result.utility_by_actor[actor.participant_id]
            for actor in program.actors
        },
    )
    leaf.structure("focus", result.utility_by_actor.get(program.focus, {}))
    leaf.raw(
        "metric_note",
        "Utility dimensions are reported in their native units. The "
        "calculator does not convert movement, cleanse, vision, or "
        "economy into TDD or a guessed common scalar.",
    )
    return block
