"""Phase 4 S4 — one kernel call site, and a result nothing can rewrite.

``program/walk`` is the front door for the seam that makes "one engine prices
one mechanic" structural.  Two properties are under test here, and neither is
about arithmetic: the walk adds none of its own, and what it returns is
frozen, so a view is a projection of the result rather than a sixth producer
of numbers.

Repointing the timeline's two legacy call sites at :func:`walk` is Phase 4
S9's; what S4 owes is that the seam exists, runs the kernel exactly once, and
returns exactly what the kernel produced.
"""

from types import SimpleNamespace

import pytest

from src.calculator.program import rung, walk as walk_module
from src.calculator.survival import (
    ScoreLedger,
    SurvivalAction,
    TransitionContext,
    TransitionRank,
    build_states,
)
from src.calculator.survival.actions import EVENT_SLOTS, ActionKind


def one_participant_context() -> tuple[TransitionContext, ScoreLedger]:
    """A single subject with 100 health and no defensive declarations."""
    combatants = [
        SimpleNamespace(
            participant_id="target",
            stats={"health": 100.0, "is_melee": True},
            defenses=SimpleNamespace(
                magic_shield=0.0,
                physical_shield=0.0,
                general_shield=0.0,
                healing_received_multiplier=1.0,
            ),
        )
    ]
    ledger = ScoreLedger(1)
    ctx = TransitionContext(
        duration=5.0,
        states=build_states(combatants, (0.0,)),
        combatants=combatants,
        index_of={"target": 0},
        ledger=ledger,
        regeneration_windows=(None,),
    )
    return ctx, ledger


def damage_action(amount: float) -> SurvivalAction:
    """One plain damage packet at t=0 against the single subject."""
    return SurvivalAction(
        sort_key=(0.0, TransitionRank.DAMAGE, 0, 0, "", "target", "e", "s"),
        time=0.0,
        phase=TransitionRank.DAMAGE,
        kind=ActionKind.PLAIN_DAMAGE,
        subject=0,
        attacker=0,
        aidx=0,
        amount=amount,
        damage_type="true",
        source_key="s",
        source="s",
        event_slot=EVENT_SLOTS.slot("program-walk-fixture"),
        sequence=0,
    )


class TestTheSeamRunsTheKernelAndNothingElse:
    """A body of one call and one record."""

    def test_the_result_carries_exactly_the_actions_it_was_given(self) -> None:
        ctx, _ = one_participant_context()
        actions = [damage_action(30.0)]
        result = walk_module.walk(actions, ctx)
        assert result.actions == tuple(actions)
        assert result.action_count() == 1

    def test_the_kernel_actually_ran(self) -> None:
        """The one number the fixture asserts: 30 damage was applied."""
        ctx, ledger = one_participant_context()
        walk_module.walk([damage_action(30.0)], ctx)
        assert ledger.applied == [30.0]

    def test_the_walk_does_not_reorder_what_it_was_handed(self) -> None:
        """Sorting twice by two rules is how two engines end up disagreeing."""
        ctx, _ = one_participant_context()
        later = damage_action(10.0)._replace(time=1.0, aidx=1)
        earlier = damage_action(20.0)
        result = walk_module.walk([later, earlier], ctx)
        assert [action.amount for action in result.actions] == [10.0, 20.0]


class TestTheResultIsFrozen:
    """A view projects the result; it may not become a second producer."""

    def test_the_record_rejects_assignment(self) -> None:
        ctx, _ = one_participant_context()
        result = walk_module.walk([damage_action(5.0)], ctx)
        with pytest.raises(AttributeError):
            result.rung = rung.CompiledFull()  # type: ignore[misc]

    def test_the_rung_rides_the_result_rather_than_the_caller(self) -> None:
        ctx, _ = one_participant_context()
        reason = "delta_amp is not representable in the score kernel"
        result = walk_module.walk(
            [damage_action(5.0)], ctx, rung=rung.ReceiptWalk(reason)
        )
        assert rung.reason_of(result.rung) == reason

    def test_the_states_come_back_as_a_tuple(self) -> None:
        ctx, _ = one_participant_context()
        result = walk_module.walk([damage_action(5.0)], ctx)
        assert isinstance(result.states, tuple)
        assert len(result.states) == 1
