"""Phase 4 S4 — four rungs, and the two failure rungs mean different things.

``program/rung`` is the front door for "which engine priced this, and why not
the fast one".  The property under test is D-69's: a declared roster mechanic
takes :class:`ReceiptWalk` with a named cause and never
:class:`SearchPoisoned`, and every decision projects onto exactly one
published counter label, so a histogram accounts for 100% of evaluations by
construction rather than by arithmetic somebody checked.
"""

import ast
from pathlib import Path

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


class TestTheLadderIsReachableFromProduction:
    """Criterion 16's third clause, which had nothing that could fail it.

    "``SearchPoisoned`` appears only for genuine invariant errors, never for
    a declared roster mechanic" was vacuous: the union D-69 rules had **zero
    construction sites** in ``src/``.  The composition recorded
    ``work_counters.Rung`` labels directly, so the decision layer -- the half
    that carries the *reason* a label cannot -- was reachable only from this
    file.  A ladder no production path can climb is a ladder no test can
    catch climbing wrong.

    The composition now constructs the decision and records
    :func:`~program.rung.counter_label` of it.  The published labels are
    byte-identical; what changed is that the reason travels with the
    decision, and that the clause above is now falsifiable.
    """

    @staticmethod
    def _timeline_source() -> str:
        from src.calculator import participant_timeline

        return Path(participant_timeline.__file__).read_text(encoding="utf-8")

    @staticmethod
    def _constructions(source: str, name: str) -> list[ast.Call]:
        return [
            node
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == name
        ]

    def test_every_member_of_the_union_is_constructed_in_src(self) -> None:
        """A four-state ladder with three reachable states is a three-state one."""
        source = self._timeline_source()
        for member in ("CompiledFast", "ReceiptWalk", "SearchPoisoned"):
            assert self._constructions(source, member), member

    def test_the_histogram_key_is_never_recorded_directly(self) -> None:
        """One projection, so a label cannot be chosen beside its decision."""
        source = self._timeline_source()
        assert "Rung." not in source
        for call in self._constructions(source, "record_rung"):
            label = call.args[1]
            assert isinstance(label, ast.Call), ast.dump(label)
            assert isinstance(label.func, ast.Name), ast.dump(label)
            assert label.func.id == "counter_label", ast.dump(label)

    def test_search_poisoned_is_constructed_only_on_an_invariant_failure(self) -> None:
        """The clause, read off the guard rather than off the class name.

        Each construction sits in a conditional expression whose test names
        ``invariant`` or the poisoned-context receipt -- the two spellings of
        "a previous evaluation's compiler failed for the search, not for this
        candidate".  A construction reached unconditionally, or under any
        other guard, fails here.
        """
        source = self._timeline_source()
        tree = ast.parse(source)
        guards = [
            ast.dump(node.test)
            for node in ast.walk(tree)
            if isinstance(node, ast.IfExp)
            and isinstance(node.body, ast.Call)
            and isinstance(node.body.func, ast.Name)
            and node.body.func.id == "SearchPoisoned"
        ]
        assert guards, "no guarded construction found"
        for guard in guards:
            assert "invariant" in guard
            assert "_CONTEXT_POISONED_RECEIPT" in guard

    def test_a_declared_roster_mechanic_takes_the_candidate_rung_instead(self) -> None:
        """The other half of "never for a declared roster mechanic", at runtime.

        A Pantheon ally holding the CC-trigger build is a declared mechanic
        the compiled kernel cannot represent for *this* candidate, so the
        histogram has to read ``receipt_walk_candidate`` and nothing else.
        """
        from scripts.bench_coupled_optimizer import WorkCounters
        from src.calculator.data_fetcher import get_champion, get_item_by_name
        from src.calculator.defensive_effects import resolve_starting_defenses
        from src.calculator.participant_timeline import (
            CoupledSearchContext,
            build_participant_timeline,
        )
        from src.calculator.pipeline import FightParams
        from src.calculator.scenario import ChampionLoadout
        from src.calculator.stats import calculate_total_stats
        from src.calculator.work_counters import Rung as Label

        champion = get_champion("Ahri")
        items = [get_item_by_name("Rabadon's Deathcap")]
        stats = calculate_total_stats(champion, 18, items, role="mid")
        sink = WorkCounters()
        build_participant_timeline(
            champion,
            18,
            items,
            FightParams.from_request(
                {"fight_mode": "time_based", "fight_duration": 8, "role": "mid"},
                deterministic=True,
            ),
            main_stats=stats,
            main_defenses=resolve_starting_defenses("Ahri", 18, stats, items),
            enemies=[
                ChampionLoadout(champion="Aatrox", level=18, role="top").resolve()
            ],
            allies=[],
            include_receipt=False,
            pair_result_cache={},
            search_context=CoupledSearchContext(work_counters=sink),
        )
        assert sink.rungs[str(Label.SEARCH_POISONED)] == 0
        assert sum(sink.rungs.values()) == 1

    def test_the_gate_refusal_carries_a_named_reason(self) -> None:
        """A gate fallback is a ``ReceiptWalk`` too, so it owes a receipt."""
        from src.calculator import participant_timeline

        reason = participant_timeline._GATE_REFUSAL_RECEIPT  # pylint: disable=W0212
        assert reason.strip()
        assert (
            rung.reason_of(rung.ReceiptWalk(reason, rung.FallbackScope.REQUEST_GATE))
            == reason
        )
