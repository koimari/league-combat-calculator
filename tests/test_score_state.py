"""Test front door for ``survival/score_state`` — the parallel-array ledger.

This module was the last ``survival/`` member of Phase 1's front-door
frontier (D-95), entered there under Phase 4's name because Phase 4 is the
phase that rebuilds the score path as a projection.  Everything reachable
through it was reached through ``survival/__init__``'s re-export or through
a coupled request, which is a real gap and not a bookkeeping one: the score
ledger is the half of "one kernel, two ledgers" whose contract is written
almost entirely in *refusals*, and a refusal exercised only end-to-end is a
refusal nobody has seen fire.

Four properties, and each is a refusal or a promise the walk depends on:

* **It records applied amounts and nothing else.**  Two kwarg spellings
  reach the same slot, everything else is dropped, and the slot is the
  action's own ``aidx`` — which is what lets ``survival.accumulate`` replay
  the per-attacker sums in the legacy float-addition order.
* **Its capability flags are what make the hot loop cheap** (issue #171).
  The kernel reads them to skip building kwargs the ledger would discard,
  so a flag flipped to ``True`` silently costs every action a ``round``.
* **Trigger linkage is write-once and fails closed.**  An unmarked trigger
  gates its dependants; a blocked action never gets the marker, so the same
  gate refuses it without a second piece of state.
* **It cannot schedule a walk-authored heal.**  Compilation is supposed to
  have rejected every mechanic that could author one, so reaching this is a
  compiler bug and raises rather than quietly adding a heal the receipt
  path would not have.
"""

from __future__ import annotations

import pytest

from src.calculator.survival.score_state import ScoreLedger
from src.calculator.survival.actions import ActionKind, SurvivalAction, TransitionRank


def action(aidx: int, *, trigger: int = -1) -> SurvivalAction:
    """One damage action at a named slot, optionally gated on another."""
    return SurvivalAction(
        sort_key=(0.0, TransitionRank.DAMAGE, 0, 0, "", "target", "e", "s"),
        time=0.0,
        phase=TransitionRank.DAMAGE,
        kind=ActionKind.PLAIN_DAMAGE,
        subject=0,
        attacker=0,
        aidx=aidx,
        trigger=trigger,
        amount=1.0,
        damage_type="true",
    )


class TestItRecordsAppliedAmountsAndNothingElse:
    """The one write, under both of the kernel's spellings for it."""

    def test_a_damage_write_lands_in_the_actions_own_slot(self) -> None:
        ledger = ScoreLedger(3)
        ledger.write(action(1), damage=42.5)
        assert ledger.applied == [0.0, 42.5, 0.0]

    def test_an_applied_amount_write_lands_in_the_same_slot(self) -> None:
        """Heals and shields spell it differently and mean the same thing."""
        ledger = ScoreLedger(3)
        ledger.write(action(2), applied_amount=7.25)
        assert ledger.applied == [0.0, 0.0, 7.25]

    def test_damage_wins_when_the_kernel_sends_both(self) -> None:
        ledger = ScoreLedger(1)
        ledger.write(action(0), damage=3.0, applied_amount=9.0)
        assert ledger.applied == [3.0]

    def test_a_field_that_is_neither_is_dropped(self) -> None:
        """Every other observation belongs to the receipt ledger."""
        ledger = ScoreLedger(1)
        ledger.write(action(0), overkill=5.0, pair_damage=6.0)
        assert ledger.applied == [0.0]

    def test_a_slot_outside_the_ledger_is_dropped_rather_than_raising(self) -> None:
        """The compilers hand out slots; a stray one costs a number, not a walk."""
        ledger = ScoreLedger(2)
        ledger.write(action(9), damage=1.0)
        ledger.write(action(-1), damage=1.0)
        assert ledger.applied == [0.0, 0.0]

    def test_a_skipped_action_leaves_its_slot_at_zero(self) -> None:
        """The legacy compiled walk's ``continue``, with a name."""
        ledger = ScoreLedger(1)
        ledger.skip(action(0), "unrepresentable", damage_phase=True)
        assert ledger.applied == [0.0]

    def test_annotating_writes_nothing_at_all(self) -> None:
        ledger = ScoreLedger(1)
        ledger.annotate(action(0), damage=11.0, overkill=2.0)
        assert ledger.applied == [0.0]
        assert ledger.status == bytearray(1)


class TestTheCapabilityFlagsThatMakeTheHotLoopCheap:
    """Issue #171: the kernel reads these to skip work this ledger discards."""

    def test_it_records_neither_annotations_nor_event_fields(self) -> None:
        assert ScoreLedger.records_annotations is False
        assert ScoreLedger.records_event_fields is False

    def test_the_flags_are_class_level_so_the_loop_reads_them_once(self) -> None:
        """An instance attribute would be a per-action lookup on the hot path."""
        assert "records_annotations" not in ScoreLedger.__slots__
        assert "records_event_fields" not in ScoreLedger.__slots__


class TestTriggerLinkageIsWriteOnceAndFailsClosed:
    """A dependant resolves only if the action it names actually applied."""

    def test_an_ungated_action_is_always_allowed(self) -> None:
        assert ScoreLedger(1).trigger_applied(action(0)) is True

    def test_a_gated_action_waits_for_its_trigger_to_be_marked(self) -> None:
        ledger = ScoreLedger(2)
        gated = action(1, trigger=0)
        assert ledger.trigger_applied(gated) is False
        ledger.mark_applied(action(0))
        assert ledger.trigger_applied(gated) is True

    def test_a_blocked_action_never_gets_the_marker(self) -> None:
        """One piece of state, not two: blocked fails the same gate as unapplied."""
        ledger = ScoreLedger(2)
        ledger.mark_blocked(action(0))
        assert ledger.status == bytearray(2)
        assert ledger.trigger_applied(action(1, trigger=0)) is False

    def test_marking_a_slot_outside_the_ledger_is_dropped(self) -> None:
        ledger = ScoreLedger(1)
        ledger.mark_applied(action(4))
        assert ledger.status == bytearray(1)


class TestItCannotScheduleAWalkAuthoredHeal:
    """The refusal that says a compiler bug is a bug and not a number."""

    def test_scheduling_one_raises_and_names_the_compilation_that_should_have(
        self,
    ) -> None:
        with pytest.raises(AssertionError, match="failed compilation"):
            ScoreLedger(1).schedule_heal({"amount": 5.0}, "main")
