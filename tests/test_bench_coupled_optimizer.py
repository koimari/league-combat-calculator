"""The fixed-work bench: its arithmetic, its void rule, and its scenarios.

R-01 row 8 gates every campaign commit on this harness, so the harness needs
gates of its own — most of all a void rule that can be made to fire, because
a run the wall clock truncated measured the machine and must never be read as
a counter.
"""

import sys
from collections import Counter
from pathlib import Path

import pytest

from src.calculator.ability_spec import IMMOBILIZING_CC_KINDS
from src.calculator.champions import parse_champion_abilities
from src.calculator.data_fetcher import get_champion

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import bench_coupled_optimizer


@pytest.fixture(scope="module")
def bench():
    """The bench module under test."""
    return bench_coupled_optimizer


def _counters(bench, **fields):
    """A ``WorkCounters`` with the named fields set."""
    counters = bench.WorkCounters()
    for name, value in fields.items():
        setattr(counters, name, value)
    return counters


class TestResidual:
    """``pair fights - evaluations x enemies`` (R-25)."""

    def test_a_perfectly_cached_search_has_a_zero_residual(self, bench):
        counters = _counters(bench, public_evaluations=100, pair_run_fight_calls=200)
        assert bench.residual(counters, 2) == 0

    def test_extra_pair_fights_are_the_whole_signal(self, bench):
        counters = _counters(bench, public_evaluations=100, pair_run_fight_calls=287)
        assert bench.residual(counters, 2) == 87


class TestVoidRule:
    """R-09: a truncated search is void, never a counter."""

    def _body(self, **overrides):
        body = {
            "evaluations": 10,
            "total_damage": 1234.5,
            "items": ["Void Staff"],
            "boots": "Sorcerer's Shoes",
            "search_timeline_coverage": {"complete": True},
        }
        body.update(overrides)
        return body

    def test_an_untruncated_response_reports_its_counters(self, bench):
        report = bench.report_from_response(
            "cassiopeia_3champ",
            self._body(),
            _counters(bench, public_evaluations=10, pair_run_fight_calls=21),
            wall_ms=12.0,
        )
        assert report["void"] is False
        assert report["residual"] == 1
        assert report["score"] == 1234.5

    def test_a_truncated_response_voids_the_run(self, bench):
        report = bench.report_from_response(
            "cassiopeia_3champ",
            self._body(truncated=True),
            _counters(bench, public_evaluations=10, pair_run_fight_calls=21),
            wall_ms=12.0,
        )
        assert report["void"] is True


class TestDeterminismProbe:
    """R-08: only a counter that repeats exactly may be equality gated."""

    def _repeat(self, evaluations, pair_calls, rungs=None):
        return {
            "counters": {
                "public_evaluations": evaluations,
                "measured_proposals": evaluations,
                "score_memo_misses": evaluations,
                "pair_run_fight_calls": pair_calls,
            },
            "residual": pair_calls - evaluations * 2,
            "rungs": rungs if rungs is not None else {"compiled": evaluations},
        }

    def test_identical_repeats_are_exact(self, bench):
        repeats = [self._repeat(100, 287) for _ in range(5)]
        verdict = bench.determinism_probe(repeats)
        assert set(verdict.values()) == {"exact"}
        assert set(bench.determinism_spread(repeats).values()) == {0}

    def test_one_drifting_counter_is_demoted_with_its_spread(self, bench):
        repeats = [self._repeat(100, 287) for _ in range(4)]
        repeats.append(self._repeat(100, 289))
        verdict = bench.determinism_probe(repeats)
        assert verdict["public_evaluations"] == "exact"
        assert verdict["pair_run_fight_calls"] == "tolerant"
        assert verdict["residual"] == "tolerant"
        assert bench.determinism_spread(repeats)["pair_run_fight_calls"] == 2

    def test_a_moving_rung_histogram_is_tolerant(self, bench):
        repeats = [self._repeat(100, 287) for _ in range(4)]
        repeats.append(self._repeat(100, 287, rungs={"receipt_walk_gate": 100}))
        assert bench.determinism_probe(repeats)["rungs"] == "tolerant"


class TestRoutingComparison:
    """R-01 row 11, and the red it can reproduce on demand (R-05).

    The row demands that forcing every coupled evaluation onto the receipt
    walk elects the same build and scores it the same.  Before this suite the
    row had no code that could say otherwise: the two JSON blobs were paired
    by a reader, so the gate could not fail, which is the exact shape the
    campaign exists to remove.  ``routing_comparison``'s ``report`` argument
    is the seam, the way ``score`` is ``check_ratchet``'s.
    """

    def _report(self, scenario="mundo_3champ", **overrides):
        report = {
            "scenario": scenario,
            "void": False,
            "winner": {"items": ["Void Staff"], "boots": "Sorcerer's Shoes"},
            "score": 3305.0,
            "repeats": [],
        }
        report.update(overrides)
        return report

    def test_the_same_answer_from_both_routings_is_the_pass_condition(self, bench):
        assert (
            bench.routing_divergences(self._report(), self._report()) == ()
        ), "identical winner and score must report no divergence"

    def test_a_differing_rung_histogram_is_not_a_divergence(self, bench):
        """The receipt walk is *expected* to change the rungs; row 11 is
        about the answer, and comparing rungs would make it red always."""
        compiled = self._report(rungs={"compiled": 489})
        receipt = self._report(rungs={"receipt_walk_gate": 577})
        assert bench.routing_divergences(compiled, receipt) == ()

    def test_a_differing_score_is_reported(self, bench):
        (failure,) = bench.routing_divergences(
            self._report(), self._report(score=3305.1)
        )
        assert "mundo_3champ" in failure
        assert "3305.0" in failure
        assert "3305.1" in failure

    def test_a_differing_winner_is_reported(self, bench):
        other = self._report()
        other["winner"] = {"items": ["Serylda's Grudge"], "boots": "Ionian Boots"}
        (failure,) = bench.routing_divergences(self._report(), other)
        assert "winner" in failure
        assert "Serylda's Grudge" in failure

    def test_a_void_routing_is_reported_rather_than_compared(self, bench):
        """R-09: a truncated run measured the machine, so it may not be read
        as agreement — silence on a void run is the absent-but-assumed-green
        counter R-09 forbids."""
        voided = self._report(void=True, reason="every repeat reported truncated")
        (failure,) = bench.routing_divergences(self._report(), voided)
        assert "receipt-walk routing voided" in failure

    def test_the_comparison_runs_both_routings_for_every_scenario(self, bench):
        asked = []

        def measure(scenario, *, isolate, repeats, compiled):
            asked.append((scenario, compiled))
            return self._report(scenario)

        comparison = bench.routing_comparison(
            ["mundo_3champ", "cassiopeia_3champ"],
            isolate=True,
            repeats=1,
            report=measure,
        )
        assert asked == [
            ("mundo_3champ", True),
            ("mundo_3champ", False),
            ("cassiopeia_3champ", True),
            ("cassiopeia_3champ", False),
        ]
        assert set(comparison) == {"mundo_3champ", "cassiopeia_3champ"}
        assert comparison["mundo_3champ"]["routing_divergences"] == []
        assert comparison["mundo_3champ"]["compiled_run"]["scenario"] == "mundo_3champ"

    def test_a_routing_that_changes_the_answer_turns_the_gate_red(self, bench):
        """The gate's red, on demand, forever: one scenario whose receipt
        walk scores differently, driven through the same entry point the
        row 11 command uses."""

        def measure(scenario, *, isolate, repeats, compiled):
            return self._report(scenario, score=3305.0 if compiled else 3200.0)

        comparison = bench.routing_comparison(
            ["mundo_3champ"], isolate=True, repeats=1, report=measure
        )
        (failure,) = comparison["mundo_3champ"]["routing_divergences"]
        assert "score 3305.0 -> 3200.0" in failure

    def test_the_isolated_child_measures_one_routing(self, bench):
        """Row 11 pairs the routings at the top level, so the child must not
        pair them again — a child that ran both would make every isolated
        repeat measure a comparison inside the comparison."""
        source = (REPO_ROOT / "scripts/bench_coupled_optimizer.py").read_text(
            encoding="utf-8"
        )
        assert '"--single-routing",' in source
        assert bench._build_parser().parse_args(["--single-routing"]).single_routing


class TestScenarioSet:
    """R-27: the fourth scenario exists to make an immobilize visible."""

    def test_four_scenarios_each_with_a_probe_build(self, bench):
        assert set(bench.SCENARIOS) == set(bench.PROBE_BUILDS)
        assert "syndra_mandate_3champ" in bench.SCENARIOS

    def test_the_fourth_scenario_locks_the_mandate(self, bench):
        scenario = bench.SCENARIOS["syndra_mandate_3champ"]
        assert scenario["locked_items"] == ["Imperial Mandate"]

    def test_which_scenario_mains_author_an_immobilize(self, bench):
        """Asserted against the champion modules, not against the name.

        This said *exactly one* while Syndra's was the only authored
        immobilize in the set, and it was written to say so if a legacy main
        ever gained one.  One has: the crowd-control fan-out gave Cassiopeia's
        R its reviewed stun, so both Cassiopeia scenarios now author one and
        the membership is re-measured here.  Syndra's E is still asserted,
        because the fourth scenario exists to price the Command amp and a
        Syndra who stops stunning stops pricing it.
        """
        authoring = {
            name
            for name, scenario in bench.SCENARIOS.items()
            if _authors_an_immobilize(scenario["champion"])
        }
        assert authoring == {
            "syndra_mandate_3champ",
            "cassiopeia_3champ",
            "cassiopeia_5champ",
        }
        assert not _authors_an_immobilize(bench.SCENARIOS["mundo_3champ"]["champion"])

    def test_the_time_budget_is_the_app_clamp_ceiling(self, bench):
        assert bench.TIME_BUDGET_CLAMP_MS == 60_000
        payload = bench._fixed_work_payload("mundo_3champ")
        assert payload["time_budget_ms"] == 60_000

    def test_the_probe_build_fills_every_legendary_slot(self, bench):
        for name, build in bench.PROBE_BUILDS.items():
            assert len(build["items"]) == 5, name
            assert build["boots"], name


def _authors_an_immobilize(champion: str) -> bool:
    """Whether any of this champion's parsed abilities marks an immobilize."""
    abilities = parse_champion_abilities(get_champion(champion), 13, 300.0)
    for entry in abilities.values():
        if not isinstance(entry, dict):
            continue
        for part in entry.get("parts", ()):
            kind = str(getattr(part, "cc_kind", "") or "").lower().strip()
            if kind in IMMOBILIZING_CC_KINDS:
                return True
    return False


class TestAllocationReading:
    """Criterion 4: one command emits the probe beside the counters (R-28)."""

    def test_every_report_gains_its_peak(self, bench, monkeypatch):
        monkeypatch.setattr(bench, "allocation_probe", lambda name: 4096)
        reports = {"mundo_3champ": {"void": False}, "cassiopeia_3champ": {}}
        bench.attach_allocation_peaks(reports)
        assert [r["allocation_peak_bytes"] for r in reports.values()] == [4096, 4096]

    def test_the_peak_comes_from_the_one_probe_the_receipt_was_read_with(
        self, bench, monkeypatch
    ):
        """Same function, same process, same order — or it is a new number."""
        probed: list[str] = []
        monkeypatch.setattr(bench, "allocation_probe", probed.append)
        bench.attach_allocation_peaks({name: {} for name in bench.SCENARIOS})
        assert probed == list(bench.SCENARIOS)

    def _run_main(self, bench, monkeypatch, argv):
        probed: list[bool] = []
        monkeypatch.setattr(sys, "argv", ["bench", *argv])
        monkeypatch.setattr(
            bench,
            "fixed_work_report",
            lambda name, **kwargs: {"scenario": name, "void": False},
        )
        monkeypatch.setattr(
            bench,
            "attach_allocation_peaks",
            lambda reports, **kwargs: probed.append(True),
        )
        bench.main()
        return probed

    def test_the_named_command_probes(self, bench, monkeypatch, capsys):
        argv = ["--fixed-work", "--isolate", "--json", "--scenario", "mundo_3champ"]
        assert self._run_main(bench, monkeypatch, argv) == [True]
        assert "mundo_3champ" in capsys.readouterr().out

    def test_an_isolated_child_does_not_probe(self, bench, monkeypatch, capsys):
        """The child measures one routing for its parent, not the criterion."""
        argv = [
            "--fixed-work",
            "--single-routing",
            "--json",
            "--scenario",
            "mundo_3champ",
        ]
        assert self._run_main(bench, monkeypatch, argv) == []
        capsys.readouterr()


class TestWorkCounters:
    """The sink's own shape — it is what the receipt is written from."""

    def test_as_dict_carries_the_four_families_the_rungs_and_their_causes(self, bench):
        counters = bench.WorkCounters(
            public_evaluations=1,
            measured_proposals=2,
            score_memo_misses=3,
            pair_run_fight_calls=4,
            rungs=Counter({"compiled": 5, "receipt_walk_candidate": 2}),
            rung_receipts=Counter({"Imperial Mandate - Command": 2}),
        )
        assert counters.as_dict() == {
            "public_evaluations": 1,
            "measured_proposals": 2,
            "score_memo_misses": 3,
            "pair_run_fight_calls": 4,
            "rungs": {"compiled": 5, "receipt_walk_candidate": 2},
            "rung_receipts": {"Imperial Mandate - Command": 2},
        }

    def test_a_compiled_rung_contributes_no_cause(self, bench):
        """The counter totals fallbacks, not evaluations.

        A compiled evaluation has no declaration to name, so recording an
        empty key for it would make ``rung_receipts`` a second, worse copy of
        ``rungs`` — and would hide the one number this field exists to give:
        how many fallbacks each named declaration caused.
        """
        from src.calculator.program.rung import (
            CompiledFast,
            ReceiptWalk,
            counter_entry,
        )
        from src.calculator.work_counters import record_rung

        counters = bench.WorkCounters()
        record_rung(counters, *counter_entry(CompiledFast()))
        record_rung(
            counters, *counter_entry(ReceiptWalk("Bloodsong - Expose Weakness"))
        )
        assert counters.rung_receipts == Counter({"Bloodsong - Expose Weakness": 1})
        assert (
            sum(counters.rung_receipts.values())
            == counters.rungs["receipt_walk_candidate"]
        )
