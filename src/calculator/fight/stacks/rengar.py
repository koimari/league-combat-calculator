"""Rengar's Ferocity timeline."""

from typing import Any

from ...ability_atoms import ability_field
from ...state_timeline import EventStamp
from ...timed_stacks import TimedStackState
from ..config import _seeded_option_stacks
from ..results import CastPlan, FerocityTimeline, RotationResult
from ..state import FightState


def _build_ferocity_timeline(
    state: FightState, plan: CastPlan
) -> FerocityTimeline | None:
    """Walk Rengar's accepted basic-ability casts against the kernel rule.

    The module prices live empowered casts from the typed rule; this
    timeline (a) seeds the kernel stack state from the same ``p_ferocity``
    option the module parse consumed, (b) applies one gain per accepted
    Q/W/E cast at its cast time (the kernel owns the 1-second per-stack
    no-refresh expiry, the 10-second combat freeze, and the cap), and
    (c) marks the cast that consumes the cap as empowered.  Returns None
    for any champion whose module does not emit ``ferocity_parts``.
    """
    if not any(
        "ferocity_parts" in info
        for info in state.ability_damages.values()
        if isinstance(info, dict)
    ):
        return None
    from ...champions.rengar import RENGAR_FEROCITY_STACK_RULE

    rule = RENGAR_FEROCITY_STACK_RULE
    options = state.champion_options
    seeded = _seeded_option_stacks(options, "champion", "Rengar", "p_ferocity")
    stack = TimedStackState(RENGAR_FEROCITY_STACK_RULE, starting_stacks=seeded)
    empowered: dict[tuple[str, int], bool] = {}
    receipts: list[dict[str, Any]] = []
    sequence = 0
    casts: list[tuple[float, str, int]] = []
    for ability_key in ("Q", "W", "E"):
        for ordinal, cast_time in enumerate(plan.times.get(ability_key, ())):
            casts.append((float(cast_time), ability_key, ordinal))
    casts.sort(key=lambda row: (row[0], ("Q", "W", "E").index(row[1]), row[2]))
    for cast_time, ability_key, ordinal in casts:
        before = stack.stacks
        transitions = stack.apply_gain(
            EventStamp(cast_time, sequence),
            kind="basic_ability_cast",
            packet="ability_cast",
            meta={"source": f"{ability_key} cast", "source_key": ability_key},
        )
        sequence += 1
        denied = any(transition.kind == "gain_denied" for transition in transitions)
        receipts.append(
            {
                "operation": "gain",
                "amount": 1.0,
                "time": round(float(cast_time), 3),
                "source": f"{ability_key} cast",
                "sequence": sequence,
                "tier": 0.0,
                "atoms": [],
                "current_before": before,
                "maximum_before": rule.max_stacks,
                "current_after": stack.stacks,
                "maximum_after": rule.max_stacks,
                "accepted": not denied,
                "reason": "at_cap" if denied else "",
            }
        )
        if denied:
            # At the cap the cast is EMPOWERED: consume the four stacks
            # and price the module's ferocity parts.
            consume_before = stack.stacks
            stack.consume(
                EventStamp(cast_time, sequence),
                meta={"source": f"{ability_key} cast"},
            )
            sequence += 1
            receipts.append(
                {
                    "operation": "consume",
                    "amount": float(consume_before),
                    "time": round(float(cast_time), 3),
                    "source": f"{ability_key} cast",
                    "sequence": sequence,
                    "tier": 0.0,
                    "atoms": [],
                    "current_before": consume_before,
                    "maximum_before": rule.max_stacks,
                    "current_after": stack.stacks,
                    "maximum_after": rule.max_stacks,
                    "accepted": True,
                    "reason": "empowered",
                }
            )
            empowered[(ability_key, ordinal)] = True
    return FerocityTimeline(
        stack=stack,
        starting_stacks=seeded,
        _empowered_by_cast=empowered,
        receipts=receipts,
    )


def _slot_ordinals(rotation: RotationResult, slot: str) -> list[int]:
    """The accepted-cast ordinals of one basic-ability slot."""
    return [
        int(event.get("ordinal", 0) or 0) - 1
        for event in rotation.cast_events
        if str(event.get("slot", "")) == slot
    ]


def _add_rengar_ferocity(state: FightState, rotation: RotationResult) -> None:
    """Add Rengar's live Ferocity stack timeline receipt (P3 package 3V).

    The stack machine already ran inside the rotation (``_build_ferocity_
    timeline`` priced the empowered casts); this walk publishes the same
    accepted Q/W/E cast stream as the breakdown's ``ferocity`` row with
    the kernel's stack_events and state_transitions, mirroring the
    Conqueror receipt shape.
    """
    timeline = state.ferocity_timeline
    if timeline is None:
        return
    stack = timeline.stack
    rule = stack.rule
    cast_events = [
        event
        for event in rotation.cast_events
        if str(event.get("slot", "")) in {"Q", "W", "E"}
    ]
    # P3 package 3V fail-closed: a requested cast slot that is not one of
    # the champion's known slots authors a named denial receipt instead of
    # being silently dropped (the counter ledger's accepted=False row).
    known_slots = set(state.ability_damages)
    for slot in state.cast_order:
        if slot in {"Q", "W", "E"} or slot in known_slots:
            continue
        if not any(
            receipt.get("reason", "").startswith("unknown_cast_slot")
            for receipt in timeline.receipts
        ):
            timeline.receipts.append(
                {
                    "operation": "gain",
                    "amount": 0.0,
                    "time": 0.0,
                    "source": f"{slot} cast",
                    "sequence": len(timeline.receipts),
                    "tier": 0.0,
                    "atoms": [],
                    "current_before": stack.stacks,
                    "maximum_before": rule.max_stacks,
                    "current_after": stack.stacks,
                    "maximum_after": rule.max_stacks,
                    "accepted": False,
                    "reason": f"unknown_cast_slot:{slot}",
                }
            )
    state.breakdown["ferocity"] = {
        "name": rule.name,
        "owner": "champion",
        "informational": True,
        "event_phase": "effect",
        "count": len(cast_events),
        "starting_stacks": timeline.starting_stacks,
        "state": (
            f"{timeline.starting_stacks}/4 Ferocity stacks (seeded); "
            f"{stack.stacks}/4 at fight end"
        ),
        "max_stacks": rule.max_stacks,
        "stack_duration_seconds": rule.duration_seconds,
        "combat_extension_seconds": rule.combat_extension_seconds,
        "stack_events": [
            {
                "time": round(float(event["time"]), 3),
                "slot": event.get("slot"),
                "ordinal": event.get("ordinal"),
                "empowered": timeline.cast_empowered(
                    str(event.get("slot", "")),
                    int(event.get("ordinal", 0) or 0) - 1,
                ),
            }
            for event in cast_events
        ],
        "state_transitions": stack.public_receipt()["transitions"],
    }
    if not cast_events:
        state.notes.append("Rengar Ferocity recorded no accepted basic-ability casts.")
    else:
        state.notes.append(
            f"Rengar Ferocity: {stack.stacks}/4 stacks at fight end "
            f"({len(cast_events)} accepted basic-ability casts)."
        )
    # P3 package 3V: the live empowered cast consumes the cap; later
    # casts of the same slot price the base values.  The module's static
    # detail describes the seeded branch — append the live consumption
    # note so the public breakdown reflects the actual first-cast-only
    # empowerment.
    for slot in ("Q", "W", "E"):
        empowered_any = any(
            timeline.cast_empowered(slot, ordinal)
            for ordinal in _slot_ordinals(rotation, slot)
        )
        base_any = any(
            not timeline.cast_empowered(slot, ordinal)
            for ordinal in _slot_ordinals(rotation, slot)
        )
        info = state.ability_damages.get(slot)
        row = state.breakdown.get(slot)
        detail = (
            str(row.get("detail", ""))
            if isinstance(row, dict)
            else str(ability_field(info, "detail")) if info is not None else ""
        )
        if not detail or not empowered_any or not base_any:
            continue
        if "consuming all 4 stacks" in detail and "later casts" not in detail:
            note = (
                "  (Live: only the first basic-ability cast at the cap is "
                "empowered; later casts price the base values.)"
            )
            if isinstance(row, dict):
                row["detail"] = detail + note
            elif info is not None:
                info["detail"] = detail + note
