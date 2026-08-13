"""Phase 4 S4 — four rungs, and the two failure rungs mean different things.

``program/rung`` is the front door for "which engine priced this, and why not
the fast one".  The property under test is D-69's: a declared roster mechanic
takes :class:`ReceiptWalk` with a named cause and never
:class:`SearchPoisoned`, and every decision projects onto exactly one
published counter label, so a histogram accounts for 100% of evaluations by
construction rather than by arithmetic somebody checked.
"""

import pytest

from src.calculator.program import rung
from src.calculator.work_counters import Rung as CounterRung


class TestTheLadderIsFourStates:
    """D-69, counted from the declaration rather than from prose."""

    def test_the_union_has_four_members(self) -> None:
        assert len(rung.RUNGS) == 4

    def test_both_failure_rungs_carry_a_reason(self) -> None:
        assert "reason" in rung.ReceiptWalk.__annotations__
        assert "reason" in rung.SearchPoisoned.__annotations__

    def test_neither_success_rung_carries_one(self) -> None:
        """A rung that succeeded has no cause to name."""
        assert rung.reason_of(rung.CompiledFast()) == ""
        assert rung.reason_of(rung.CompiledFull()) == ""


class TestEveryDecisionHasExactlyOneLabel:
    """The bridge to the published counter vocabulary."""

    @pytest.mark.parametrize(
        "decision,label",
        [
            (rung.CompiledFast(), CounterRung.COMPILED),
            (rung.CompiledFull(), CounterRung.COMPILED),
            (rung.ReceiptWalk("delta_amp"), CounterRung.RECEIPT_WALK_CANDIDATE),
            (rung.gate_rung("score_only"), CounterRung.RECEIPT_WALK_GATE),
            (rung.SearchPoisoned("panel"), CounterRung.SEARCH_POISONED),
        ],
    )
    def test_the_decision_projects_onto_its_label(self, decision, label) -> None:
        assert rung.counter_label(decision) is label

    def test_the_four_published_labels_are_all_reachable(self) -> None:
        """A label no decision produces would be a histogram key nobody fills."""
        decisions = [
            rung.CompiledFast(),
            rung.ReceiptWalk("x"),
            rung.gate_rung("y"),
            rung.SearchPoisoned("z"),
        ]
        assert {rung.counter_label(d) for d in decisions} == set(CounterRung)

    def test_a_value_outside_the_union_raises(self) -> None:
        with pytest.raises(TypeError, match="closed"):
            rung.counter_label(object())  # type: ignore[arg-type]


class TestTheTwoFailureRungsAreNotInterchangeable:
    """A declared roster mechanic is a representation choice, never poison."""

    def test_a_gate_fallback_and_a_candidate_fallback_report_differently(self) -> None:
        assert rung.counter_label(rung.gate_rung("r")) is not rung.counter_label(
            rung.ReceiptWalk("r")
        )

    def test_a_scope_is_required_of_every_fallback(self) -> None:
        assert set(rung.FallbackScope) == {
            rung.FallbackScope.REQUEST_GATE,
            rung.FallbackScope.CANDIDATE,
        }


class TestTheHistogramAccountsForEverything:
    """Criterion 16's first clause, as a property of the projection."""

    def test_the_counts_sum_to_the_evaluation_count(self) -> None:
        decisions = [
            rung.CompiledFast(),
            rung.CompiledFull(),
            rung.ReceiptWalk("delta_amp"),
            rung.gate_rung("score_only"),
            rung.SearchPoisoned("panel"),
        ]
        tally = rung.histogram(decisions)
        assert sum(tally.values()) == len(decisions)
        assert tally[str(CounterRung.COMPILED)] == 2

    def test_an_empty_search_reports_an_empty_histogram(self) -> None:
        assert sum(rung.histogram(()).values()) == 0
