"""When two rules refuse one action, the receipt publishes the first.

A refusal is a receipt: it is the sentence a reader gets in place of a
number, so which of two competing refusals reaches the payload decides what
that reader is told.  The kernel's trigger arm used to overwrite an
already-stamped reason, which published the *consequence* in place of the
*cause* — a redirect child Knight's Vow had cancelled reported
``trigger_event_skipped``, and the trigger was skipped precisely because of
the cancellation the receipt no longer mentioned.

The redirect-cancelled arm three lines below it already carried
``preserve_reason``; this file pins that both arms do, in both directions, so
the fix is a property rather than a one-line agreement between two branches.
"""

from __future__ import annotations


from src.calculator.defensive_effects import StartingDefenses
from src.calculator.program.compile import action_from_event
from src.calculator.survival import (
    EVENT_SLOTS,
    ActionKind,
    ReceiptLedger,
    SurvivalAction,
    TransitionContext,
    TransitionRank,
    build_states,
    run_survival_walk,
)
from src.calculator.participant_timeline import Combatant


def _target() -> Combatant:
    """One defender with health and nothing else."""
    return Combatant(
        participant_id="target",
        team="enemy",
        champion_data={"name": "target"},
        level=1,
        items=(),
        stats={"health": 1000.0, "is_melee": True},
        defenses=StartingDefenses(
            magic_shield=0.0,
            physical_shield=0.0,
            general_shield=0.0,
            healing_received_multiplier=1.0,
        ),
    )


def _host(event: dict) -> SurvivalAction:
    """The trigger packet, authored dead so the walk refuses it."""
    return SurvivalAction(
        sort_key=(0.0, TransitionRank.DAMAGE, 0, 0, 0, "target", "host", "spell"),
        time=0.0,
        phase=TransitionRank.DAMAGE,
        kind=ActionKind.PLAIN_DAMAGE,
        subject=0,
        attacker=0,
        aidx=0,
        amount=0.0,
        damage_type="magic",
        source_key="spell",
        source="spell",
        event_slot=EVENT_SLOTS.slot("host"),
        sequence=0,
        event=event,
    )


def _rider(event: dict) -> SurvivalAction:
    """A recovery packet whose trigger is the host above."""
    return SurvivalAction(
        sort_key=(1.0, TransitionRank.RECOVERY, 1, 0, 0, "target", "rider", "vow"),
        time=1.0,
        phase=TransitionRank.RECOVERY,
        kind=ActionKind.HEAL,
        subject=0,
        attacker=0,
        aidx=1,
        amount=50.0,
        source_key="vow",
        source="vow",
        event_slot=EVENT_SLOTS.slot("rider"),
        trigger_slot=EVENT_SLOTS.slot("host"),
        sequence=1,
        event=event,
    )


def _walk(rider_event: dict) -> dict:
    """Run the kernel over a blocked host and its rider; return the rider row."""
    host_event = {"_event_id": "host", "time": 0.0, "damage": 0.0}
    host = _host(host_event)
    rider = _rider(rider_event)
    target = _target()
    states = build_states([target], (0.0,))
    # The host is refused before it can mark its event applied, which is what
    # sends the rider down the trigger arm under test.
    states[0]["death_time"] = 0.0
    actions = [host, rider]
    ledger = ReceiptLedger(
        actions=actions,
        index_of={"target": 0},
        compile_event=action_from_event,
        annotating=True,
    )
    ctx = TransitionContext(
        duration=10.0,
        states=states,
        combatants=[target],
        index_of={"target": 0},
        ledger=ledger,
        regeneration_windows=(None,),
    )
    run_survival_walk(actions, ctx)
    return rider_event


def test_an_unstamped_rider_reports_the_trigger_refusal() -> None:
    """The control: with no earlier cause, the trigger arm's reason stands."""
    row = _walk({"_event_id": "rider", "_trigger_event_id": "host", "time": 1.0})
    assert row["skipped_reason"] == "trigger_event_skipped"


def test_an_already_refused_rider_keeps_the_reason_that_refused_it() -> None:
    """The fix: a gate that already refused this action owns the receipt."""
    row = _walk(
        {
            "_event_id": "rider",
            "_trigger_event_id": "host",
            "time": 1.0,
            "skipped_reason": "holder_health_gate",
        }
    )
    assert row["skipped_reason"] == "holder_health_gate"


def test_the_score_adapter_answers_the_keyword_the_kernel_sends() -> None:
    """``preserve_reason`` reaches both adapters, so both must accept it.

    The score ledger keeps no reason and therefore does nothing with it —
    but a keyword the one kernel sends and one adapter cannot take is a
    ``TypeError`` waiting for the first roster that reaches the branch.
    """
    from src.calculator.survival.score_state import ScoreLedger

    ledger = ScoreLedger(2)
    ledger.skip(_host({}), "trigger_event_skipped", preserve_reason=True)
    assert ledger.applied == [0.0, 0.0]
