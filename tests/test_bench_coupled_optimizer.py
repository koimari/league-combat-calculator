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

import bench_coupled_optimizer  # noqa: E402  (path is set above)


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


class TestScenarioSet:
    """R-27: the fourth scenario exists to make an immobilize visible."""

    def test_four_scenarios_each_with_a_probe_build(self, bench):
        assert set(bench.SCENARIOS) == set(bench.PROBE_BUILDS)
        assert "syndra_mandate_3champ" in bench.SCENARIOS

    def test_the_fourth_scenario_locks_the_mandate(self, bench):
        scenario = bench.SCENARIOS["syndra_mandate_3champ"]
        assert scenario["locked_items"] == ["Imperial Mandate"]

    def test_exactly_one_scenario_main_authors_an_immobilize(self, bench):
        """Asserted against the champion modules, not against the name.

        If Syndra's E ever stops authoring its stun this fails on the
        mechanism, and if one of the three legacy mains gains one the
        scenario stops being the campaign's only immobilizing shape and
        says so.
        """
        authoring = {
            name
            for name, scenario in bench.SCENARIOS.items()
            if _authors_an_immobilize(scenario["champion"])
        }
        assert authoring == {"syndra_mandate_3champ"}

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


class TestWorkCounters:
    """The sink's own shape — it is what the receipt is written from."""

    def test_as_dict_carries_the_four_families_and_the_rungs(self, bench):
        counters = bench.WorkCounters(
            public_evaluations=1,
            measured_proposals=2,
            score_memo_misses=3,
            pair_run_fight_calls=4,
            rungs=Counter({"compiled": 5}),
        )
        assert counters.as_dict() == {
            "public_evaluations": 1,
            "measured_proposals": 2,
            "score_memo_misses": 3,
            "pair_run_fight_calls": 4,
            "rungs": {"compiled": 5},
        }
