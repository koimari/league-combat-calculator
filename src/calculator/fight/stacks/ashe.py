"""Ashe's Focus stacks and the denial receipt."""

from collections.abc import Iterable, Mapping
from typing import Any

from ...ability_atoms import ability_field, ability_payload
from ...champions.ashe import ASHE_FOCUS_STACK_RULE
from ...state_lifecycle import EventStamp, TimedStackState
from ..config import _seeded_option_stacks, declared_option_default
from ..results import RotationResult
from ..state import FightState
from .account import StackEvent, _resource_ledger, _stack_receipt_row


def _feed_ashe_focus_stack(
    stack: Any,
    swings: list[Any],
    q_casts: Iterable[Mapping[str, Any]],
    duration: float,
    *,
    q_window_end: float = 0.0,
) -> tuple[list[dict[str, Any]], int, int]:
    """Feed the Focus stack machine from the engine's per-swing stream.

    The Q-activation consume sorts BEFORE the same-timestamp swings (the
    model activates Q before any swing at t=0 when the gate is open);
    each auto swing then gains a stack at its swing time.  Returns the
    receipt list, the accepted-gain count and the activation count.
    """
    receipts: list[dict[str, Any]] = []
    current = 0
    gains = 0
    consumes = 0
    sequence = 0

    def _record(
        operation: str,
        amount: float,
        time: float,
        source: str,
        *,
        status: tuple[bool, str],
    ) -> None:
        nonlocal current, gains
        accepted, reason = status
        before = current
        if accepted:
            current = max(0, current + amount)
            if operation == "gain":
                gains += 1
        receipts.append(
            _stack_receipt_row(
                "focus",
                len(receipts) + 1,
                StackEvent(operation, amount, time, source, accepted, reason),
                current_before=before,
                current_after=current,
                maximum=4,
            )
        )

    events: list[tuple[float, str, int]] = []
    events.extend((float(cast.get("time", 0.0)), "consume", 0) for cast in q_casts)
    for index, swing in enumerate(swings):
        if isinstance(swing, Mapping):
            events.append((float(swing.get("time", 0.0) or 0.0), "gain", index + 1))
    events.sort(
        key=lambda entry: (entry[0], 0 if entry[1] == "consume" else 1, entry[2])
    )
    for time, kind, index in events:
        sequence += 1
        if kind == "consume":
            before = stack.stacks
            stack.consume(
                EventStamp(time, sequence),
                meta={"source": "Ranger's Focus activation"},
            )
            after = stack.stacks
            if before >= 4:
                consumes += 1
                _record(
                    "consume",
                    -(before - after),
                    time,
                    "Ranger's Focus activation",
                    status=(True, ""),
                )
            else:
                _record(
                    "consume",
                    0.0,
                    time,
                    "Ranger's Focus activation",
                    status=(False, "below_cap"),
                )
        elif q_window_end > 0.0 and time < q_window_end:
            # P1 Slice 11: the "while Ranger's Focus is INACTIVE" clause
            # — the flurry-window swings generate NO Focus (a named
            # denial distinct from at_cap, the stack never mutates); the
            # gains resume at t >= q_window_end.
            _record(
                "gain",
                0.0,
                time,
                f"auto attack {index}",
                status=(False, "active_window"),
            )
        else:
            before = stack.stacks
            transitions = stack.apply_gain(
                EventStamp(time, sequence),
                kind="auto_attack",
                packet="basic_attack",
                meta={
                    "source": f"auto attack {index}",
                    "source_key": "auto_attacks",
                },
            )
            after = stack.stacks
            denied = bool(transitions) and transitions[-1].kind == "gain_denied"
            if denied:
                _record(
                    "gain",
                    0.0,
                    time,
                    f"auto attack {index}",
                    status=(False, "at_cap"),
                )
            else:
                _record(
                    "gain",
                    after - before,
                    time,
                    f"auto attack {index}",
                    status=(True, ""),
                )
    sequence += 1
    stack.materialize_expiries(duration, sequence=sequence)
    return receipts, gains, consumes


def _add_ashe_focus(state: FightState, rotation: RotationResult) -> None:
    """Add Ashe's live Focus stack lifecycle receipts (P1 Slice 10).

    The Focus stack machine runs POST-ROTATION over the engine's
    already-priced per-swing events: each auto attack at its swing time
    gains a stack (cap 4, the 4s window refreshing on subsequent
    attacks, the 1/s step-down expiry, cap noop — a capped attack does
    NOT refresh, NO combat extension) via the typed
    ASHE_FOCUS_STACK_RULE, and the Ranger's Focus activation CONSUMES
    all 4 stacks (the wiki cost box "30 Mana + 4 Focus" — the
    consume-on-activation) when the modeled fight casts Q at the full
    stack.  This walk is documentary: it receipts the gains, the
    consume, the expiries, and the fail-closed denials into an additive
    ``resource_ledger["focus"]`` sub-section — the real mana account is
    never replaced — and never re-prices the parse-time Q (the gate +
    the flurry/AS pricing stay exactly as the module prices them).
    """
    option = state.champion_options
    q_entry = ability_payload(state.ability_damages, "Q")
    q_active = bool(
        option.get("q_active", declared_option_default("champion", "Ashe", "q_active"))
    )
    is_ashe = bool(q_entry) and str(ability_field(q_entry, "name")) == "Ranger's Focus"
    # The Ashe identity: the module's Q entry name, OR the explicitly
    # passed q_active False override (the Q entry is absent when the
    # module gates on q_active first — the Focus still exists, the auto
    # gains are documented, no consume can fire).  The walk must never
    # run for another champion's Q.
    if not is_ashe and (q_active or "q_active" not in option):
        return
    if q_active and not q_entry:
        # Q rank 0 (unlearned) -> no Focus system at all.
        return
    seeded = _seeded_option_stacks(option, "champion", "Ashe", "q_focus_stacks")
    stack = TimedStackState(ASHE_FOCUS_STACK_RULE, starting_stacks=seeded)
    swings = (state.breakdown.get("auto_attacks") or {}).get("damage_events") or []
    q_casts = [
        event for event in rotation.cast_events if str(event.get("slot", "")) == "Q"
    ]
    receipts, gains, consumes = _feed_ashe_focus_stack(
        stack,
        swings,
        q_casts,
        float(state.fight_duration_seconds),
        q_window_end=float(state.q_window_end),
    )
    closing = stack.stacks

    if swings:
        _add_focus_denial(
            receipts,
            "auto_attack_without_identity",
            "missing_identity",
        )
    for source, reason in (
        (
            "unsupported_focus_source:ability_cast",
            "unsupported_focus_source:ability_cast — only auto-attack "
            "swings generate Focus",
        ),
        (
            "unsupported_focus_source:on_hit",
            "unsupported_focus_source:on_hit — on-hit riders never "
            "generate Focus (Runaan's bolts excluded)",
        ),
    ):
        _add_focus_denial(receipts, source, reason)

    _resource_ledger(rotation)["focus"] = {
        "contract": "resource_ledger_v1",
        "owner": "main",
        "kind": "focus",
        "opening_maximum": 4,
        "opening_current": seeded,
        "closing_maximum": 4,
        "closing_current": closing,
        "base_maximum": 4,
        "bonus_maximum": 0,
        "receipts": receipts,
        "declaration": ASHE_FOCUS_STACK_RULE.public_receipt(),
        "state_transitions": stack.public_receipt()["transitions"],
    }
    state.breakdown["focus"] = {
        "name": ASHE_FOCUS_STACK_RULE.public_receipt()["name"],
        "owner": "champion",
        "informational": True,
        "event_phase": "effect",
        "count": gains,
        "starting_stacks": seeded,
        "state": f"{seeded}/4 Focus stacks (seeded); {closing}/4 at fight end",
        "max_stacks": 4,
        "stack_duration_seconds": 4.0,
        "combat_extension_seconds": 0.0,
        "stack_events": [
            {
                "time": receipt["time"],
                "swing_index": None,
                "kind": receipt["operation"],
            }
            for receipt in receipts
            if receipt["operation"] in ("gain", "consume")
        ],
        "state_transitions": stack.public_receipt()["transitions"],
    }
    if gains or consumes:
        state.notes.append(
            f"Ashe Focus: {closing}/4 stacks at fight end ({gains} accepted "
            f"auto-attack gain(s); {consumes} Ranger's Focus activation(s))."
        )
    else:
        state.notes.append(
            "Ashe Focus recorded no accepted auto-attack swings "
            "(the seeded stacks are the whole admission)."
        )


def _add_focus_denial(
    receipts: list[dict[str, Any]],
    source: str,
    reason: str,
) -> None:
    """Append one named fail-closed denial receipt (the Rengar/Senna
    walk shape: accepted False, amount 0, the current unchanged)."""
    receipts.append(
        {
            "owner": "main",
            "kind": "focus",
            "operation": "gain",
            "amount": 0.0,
            "time": 0.0,
            "source": source,
            "sequence": len(receipts) + 1,
            "tier": 0.0,
            "atoms": [],
            "current_before": 0,
            "maximum_before": 4,
            "current_after": 0,
            "maximum_after": 4,
            "accepted": False,
            "reason": reason,
        }
    )
