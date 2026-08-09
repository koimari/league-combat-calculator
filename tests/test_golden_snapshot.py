"""The golden instrument: fingerprint, classified diffs, and the coupled baseline.

Every check here is about the *instrument*, never about a champion's numbers:
what `compare` ignores, what `fingerprint` counts, which producers the coupled
scenario set reaches, and whether each new gate can be made to fail on demand
(runbook R-05).
"""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import golden_snapshot as gs  # noqa: E402  (path is set above)

from src.calculator import pipeline  # noqa: E402
from src.calculator.item_support_effects import (  # noqa: E402
    cross_participant_authorities,
    producer_item,
)

COUPLED_BASELINE = REPO_ROOT / "scripts" / "golden_coupled_baseline.json"
COUPLED_EXACT = REPO_ROOT / "scripts" / "golden_coupled_exact.json"
PAIR_BASELINE = REPO_ROOT / "scripts" / "golden_baseline.json"


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def coupled():
    """One coupled capture, shared by every check that reads its numbers."""
    return gs.capture_coupled(
        gs.COUPLED_SCENARIOS, producers=cross_participant_authorities()
    )


# ---------------------------------------------------------------------------
# Provenance exclusion (R-14) and the fingerprint domain
# ---------------------------------------------------------------------------


class TestProvenanceExclusion:
    def test_src_tree_sha_is_excluded(self):
        """A comment-only edit moves it, so comparing it waives the gate."""
        assert "src_tree_sha" in gs.COMPARE_EXCLUDED_PROVENANCE

    @pytest.mark.parametrize("path", [PAIR_BASELINE, COUPLED_BASELINE])
    def test_no_numeric_section_is_excluded(self, path):
        sections = set(gs.numeric_sections(_load(path)))
        assert sections
        assert not sections & gs.COMPARE_EXCLUDED_PROVENANCE

    @pytest.mark.parametrize("path", [PAIR_BASELINE, COUPLED_BASELINE])
    def test_every_excluded_key_is_actually_captured(self, path):
        """The exclusion set names keys the snapshot carries, not aspirations."""
        metadata = _load(path)["metadata"]
        assert gs.COMPARE_EXCLUDED_PROVENANCE <= set(metadata)

    def test_dropping_git_head_from_the_exclusion_set_turns_compare_red(self):
        """R-05: the gate's own red, reproducible on demand.

        `compare` pops exactly `COMPARE_EXCLUDED_PROVENANCE`; with `git_head`
        out of that set, two captures of one unchanged tree differ on every
        commit.  The seam is the constant.
        """
        baseline = _load(COUPLED_BASELINE)
        current = json.loads(json.dumps(baseline))
        current["metadata"]["git_head"] = "0" * 40
        for excluded in (gs.COMPARE_EXCLUDED_PROVENANCE, frozenset({"src_tree_sha"})):
            left = json.loads(json.dumps(baseline))
            right = json.loads(json.dumps(current))
            for snapshot in (left, right):
                for key in excluded:
                    snapshot["metadata"].pop(key, None)
            diffs = gs.leaf_report(left, right)
            assert bool(diffs) is ("git_head" not in excluded)


class TestFingerprint:
    @pytest.mark.parametrize("path", [PAIR_BASELINE, COUPLED_BASELINE])
    def test_metadata_carries_the_counts_the_fingerprint_prints(self, path):
        """One function produces the receipt figure and the snapshot's copy."""
        snapshot = _load(path)
        printed = gs.fingerprint(snapshot)
        assert snapshot["metadata"]["fingerprint"] == {
            field: printed[field] for field in gs.FINGERPRINT_COUNT_FIELDS
        }

    @pytest.mark.parametrize("path", [PAIR_BASELINE, COUPLED_BASELINE])
    def test_excluded_key_set_is_exactly_the_compare_exclusion(self, path):
        assert set(gs.fingerprint(_load(path))["excluded_metadata"].split(",")) == set(
            gs.COMPARE_EXCLUDED_PROVENANCE
        )

    def test_metadata_is_not_counted(self):
        """Its two wall-clock stamps move on every capture; counting them lies."""
        snapshot = {"a": {"x": 1.0}, "metadata": {"noise": [1, 2, 3, 4, 5]}}
        assert gs.fingerprint(snapshot)["leaves"] == 1
        assert gs.numeric_sections(snapshot) == {"a": {"x": 1.0}}

    def test_counts_separate_numeric_leaves_from_text(self):
        snapshot = {"s": {"n": 1.5, "i": 2, "t": "x", "b": True, "z": None}}
        counts = gs.fingerprint_counts(snapshot)
        assert counts["leaves"] == 5
        assert counts["numeric_leaves"] == 2
        # One entry per top-level key of each section — the scenario/champion
        # count, not the leaf count.
        assert counts["entries"] == 5
        assert gs.fingerprint_counts({"s": {"a": {}}, "t": {}})["entries"] == 1


# ---------------------------------------------------------------------------
# Classified diffs (R-15)
# ---------------------------------------------------------------------------


class TestLeafReport:
    @pytest.mark.parametrize(
        "old, new, transition",
        [
            ({"a": 10.0}, {"a": 10.5}, "value"),
            ({"a": 0.0}, {"a": 3.0}, "zero_to_value"),
            ({"a": 3.0}, {"a": 0.0}, "value_to_zero"),
            ({"a": 3.0}, {"a": {"error": "ValueError: x"}}, "value_to_error"),
            ({"a": {"error": "ValueError: x"}}, {"a": 3.0}, "error_to_value"),
            ({}, {"a": 3.0}, "absent_to_value"),
            ({"a": 3.0}, {}, "value_to_absent"),
            ({"a": "left"}, {"a": "right"}, "text_change"),
        ],
    )
    def test_every_transition_is_classified(self, old, new, transition):
        (diff,) = gs.leaf_report({"s": old}, {"s": new})
        assert diff.transition == transition
        assert diff.section == "s"

    def test_percent_is_infinite_from_zero(self):
        (diff,) = gs.leaf_report({"s": {"a": 0.0}}, {"s": {"a": 3.0}})
        assert diff.percent == float("inf")
        assert diff.abs_delta == pytest.approx(3.0)

    def test_a_small_percentage_move_on_a_plain_leaf_owes_nobody(self):
        (diff,) = gs.leaf_report({"s": {"armor": 100.0}}, {"s": {"armor": 100.5}})
        assert not gs.qualifies_for_investigation(diff)

    def test_a_large_percentage_move_qualifies(self):
        (diff,) = gs.leaf_report({"s": {"armor": 100.0}}, {"s": {"armor": 120.0}})
        assert gs.qualifies_for_investigation(diff)

    def test_a_flat_damage_move_qualifies_below_ten_percent(self):
        """The systematic single-digit-percent move R-15's third clause catches."""
        (diff,) = gs.leaf_report(
            {"s": {"total_damage": 1000.0}}, {"s": {"total_damage": 1002.0}}
        )
        assert abs(diff.percent) < gs.INVESTIGATION_PERCENT
        assert gs.qualifies_for_investigation(diff)

    def test_the_same_move_on_a_non_damage_leaf_does_not(self):
        (diff,) = gs.leaf_report({"s": {"armor": 1000.0}}, {"s": {"armor": 1002.0}})
        assert not gs.qualifies_for_investigation(diff)

    def test_every_non_value_transition_qualifies(self):
        (diff,) = gs.leaf_report({"s": {"a": "left"}}, {"s": {"a": "right"}})
        assert gs.qualifies_for_investigation(diff)

    def test_report_is_sorted_by_section_then_magnitude(self):
        old = {"s": {"a": 100.0, "b": 100.0}, "t": {"c": 100.0}}
        new = {"s": {"a": 101.0, "b": 150.0}, "t": {"c": 200.0}}
        paths = [diff.path for diff in gs.leaf_report(old, new)]
        assert paths == ["/s/b", "/s/a", "/t/c"]

    def test_report_file_carries_every_diff_and_the_ratio_clause(self, tmp_path):
        old = {"s": {"a": 100.0}, "metadata": {}}
        new = {"s": {"a": 150.0}, "metadata": {}}
        report = gs._write_report(
            tmp_path / "r.json", gs.leaf_report(old, new), gs.PAIR_SNAPSHOT_KIND
        )
        assert report["differing_leaves"] == 1
        assert report["qualifying_leaves"] == 1
        assert report["largest_abs_delta_per_section"]["s"] == "/s/a"
        assert json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))["diffs"]


# ---------------------------------------------------------------------------
# The coupled baseline (R-11, R-12)
# ---------------------------------------------------------------------------


class TestCoupledCoverage:
    def test_the_scenario_set_covers_every_producer(self):
        assert (
            gs._uncovered_producers(
                gs.COUPLED_SCENARIOS, cross_participant_authorities()
            )
            == ()
        )

    def test_a_seventh_producer_without_a_scenario_fails_the_capture(self):
        """R-12's whole point: the producer set is read, so coverage cannot rot."""
        producers = dict(cross_participant_authorities())
        producers["Unequipped Relic — Seventh Wonder"] = None
        with pytest.raises(ValueError, match="Unequipped Relic"):
            gs.capture_coupled(gs.COUPLED_SCENARIOS, producers=producers)

    def test_every_producer_moves_a_leaf_when_its_packet_is_suppressed(
        self, coupled, monkeypatch
    ):
        """Coverage means the baseline can *see* the producer, not merely hold it."""
        from src.calculator import participant_timeline

        original = participant_timeline.derive_item_support_effects
        for producer in cross_participant_authorities():

            def muted(*args, _producer=producer, **kwargs):
                return [
                    packet
                    for packet in original(*args, **kwargs)
                    if packet.get("source") != _producer
                ]

            monkeypatch.setattr(
                participant_timeline, "derive_item_support_effects", muted
            )
            without = gs.capture_coupled(
                gs.COUPLED_SCENARIOS, producers=cross_participant_authorities()
            )
            monkeypatch.setattr(
                participant_timeline, "derive_item_support_effects", original
            )
            assert gs.leaf_report(coupled, without), (
                f"suppressing {producer!r} changes no leaf of the coupled "
                "baseline — the scenario set does not reach it"
            )

    def test_every_producer_item_is_equipped_by_some_scenario(self):
        equipped = frozenset().union(*(s.equipped() for s in gs.COUPLED_SCENARIOS))
        for producer in cross_participant_authorities():
            assert producer_item(producer) in equipped

    def test_score_scenarios_cover_both_damage_ledger_shapes(self, monkeypatch):
        """Both ledger shapes are covered by scenarios, never by assumption."""
        shapes = {}
        original = pipeline.calculate_fight_damage

        def recording(*args, **kwargs):
            if kwargs.get("score_only"):
                shapes.setdefault(recording.name, set()).add(
                    bool(kwargs.get("tuple_ledger"))
                )
            return original(*args, **kwargs)

        monkeypatch.setattr(pipeline, "calculate_fight_damage", recording)
        for scenario in gs.COUPLED_SCENARIOS:
            if not scenario.score_mode:
                continue
            recording.name = scenario.name
            gs.coupled_entry(scenario)
        assert {True, False} <= {
            shape for shapes_ in shapes.values() for shape in shapes_
        }
        assert shapes["score_event_scan_holder"] == {False}
        assert shapes["score_plain_tuple"] == {True}

    def test_one_catalyst_roster_is_present(self):
        equipped = {name for s in gs.COUPLED_SCENARIOS for name in s.equipped()}
        assert "Catalyst of Aeons" in equipped


class TestSyndraPinScenarios:
    """The cast-order pin C6 is measured against (Phase 0, slice 0A.2)."""

    def test_both_orders_are_captured_at_every_splinter_count(self):
        names = {scenario.name for scenario in gs.COUPLED_SCENARIOS}
        for splinters in gs.SYNDRA_PIN_SPLINTERS:
            assert f"syndra_custom_order_{splinters}" in names
            assert f"syndra_derived_order_{splinters}" in names

    def test_the_two_orders_share_one_parameter_set(self):
        by_name = {scenario.name: scenario for scenario in gs.COUPLED_SCENARIOS}
        custom = dict(by_name["syndra_custom_order_120"].request)
        derived = dict(by_name["syndra_derived_order_120"].request)
        assert custom.pop("cast_order") == gs.SYNDRA_CUSTOM_ORDER
        assert "cast_order" not in derived
        custom["allies"] = [
            {k: v for k, v in ally.items() if k != "cast_order"}
            for ally in custom["allies"]
        ]
        assert custom == derived

    def test_the_parameter_set_is_level_18_600_ap_and_10_ability_haste(self):
        """The haste is what puts Q's recast at 5.0 s and W's at 7.273 s."""
        from src.calculator.data_fetcher import get_champion, get_item_by_name
        from src.calculator.stats import calculate_total_stats

        request = gs._syndra_pin_request(120, cast_order=None)
        stats = calculate_total_stats(
            get_champion("Syndra"),
            request["level"],
            [get_item_by_name(name) for name in request["items"]],
            item_options=request["item_options"],
        )
        assert request["level"] == 18
        assert stats["ability_power"] == pytest.approx(600.0)
        assert stats["ability_haste"] == pytest.approx(10.0)

    def test_the_custom_order_timeline_differs_from_the_derived_one(self, coupled):
        """A pin both the fix and a fall-through satisfy is not a pin."""
        entries = coupled["coupled_scenarios"]
        for splinters in gs.SYNDRA_PIN_SPLINTERS:
            custom = entries[f"syndra_custom_order_{splinters}"]["fights"][
                "manual_target"
            ]["cast_timeline"]
            derived = entries[f"syndra_derived_order_{splinters}"]["fights"][
                "manual_target"
            ]["cast_timeline"]
            assert [(c["time"], c["slot"]) for c in custom] != [
                (c["time"], c["slot"]) for c in derived
            ]

    def test_the_splinter_axis_is_load_bearing(self, coupled):
        """Q's second charge arrives at 40 stacks; 39 is the negative control."""
        entries = coupled["coupled_scenarios"]

        def slots(name):
            timeline = entries[name]["fights"]["manual_target"]["cast_timeline"]
            return [cast["slot"] for cast in timeline]

        assert "Q2" not in slots("syndra_derived_order_39")
        assert "Q2" in slots("syndra_derived_order_60")
        assert "Q2" in slots("syndra_derived_order_120")

    def test_a_custom_order_drops_the_recast_slot_today(self, coupled):
        """The defect C6 corrects, pinned so the correction has a before."""
        entries = coupled["coupled_scenarios"]
        for splinters in (60, 120):
            timeline = entries[f"syndra_custom_order_{splinters}"]["fights"][
                "manual_target"
            ]["cast_timeline"]
            assert "Q2" not in [cast["slot"] for cast in timeline]


class TestExactBaseline:
    """R-13: golden equality is two decimals, so bit-exactness needs its own file."""

    def test_the_exact_capture_reproduces_the_committed_totals(self):
        captured = gs.capture_coupled(
            gs.COUPLED_SCENARIOS,
            producers=cross_participant_authorities(),
            exact=True,
        )
        committed = _load(COUPLED_EXACT)
        assert captured["coupled_scenarios"] == committed["coupled_scenarios"]

    def test_exact_values_are_repr_floats_not_rounded(self):
        captured = gs.capture_coupled(
            gs.COUPLED_SCENARIOS,
            producers=cross_participant_authorities(),
            exact=True,
        )
        values = [
            value
            for entry in captured["coupled_scenarios"].values()
            for value in entry.values()
        ]
        assert values
        assert all(isinstance(value, str) for value in values)
        assert all(float(value) == float(value) for value in values)

    def test_the_exact_file_is_not_the_compared_baseline(self):
        """It is excluded from the 2-dp compare and gated by the test above."""
        assert _load(COUPLED_EXACT)["metadata"]["exact"] is True
        assert _load(COUPLED_BASELINE)["metadata"]["exact"] is False
