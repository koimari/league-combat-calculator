"""Tests for the bounded issue #38 champion optimizer smoke matrix."""

from scripts.champion_optimizer_matrix import build_gate_report, run_matrix


def test_partial_and_expected_withholding_fail_the_matrix_and_are_not_certified():
    def post(_path, payload):
        if payload["champion"] == "partial":
            return 200, {
                "items": ["Shadowflame"],
                "boots": None,
                "is_certified_best": False,
                "search_timeline_coverage": {
                    "complete": False,
                    "certification": "partial_candidate_event_order",
                    "coarse_sources": ["muramana_ability"],
                },
            }
        return 400, {
            "error": "No complete legal event-ordered build fits the selected constraints"
        }

    report = run_matrix(post, ["partial", "withheld"])
    assert report["passed"] is False
    assert report["outcome_counts"] == {
        "expected_withholding": 1,
        "partial_or_unexhaustive": 1,
    }
    assert report["results"][0]["build"] == {
        "items": ["Shadowflame"],
        "boots": None,
    }
    receipt = build_gate_report(report, ["partial", "withheld"])
    assert receipt["passed"] is False
    assert receipt["counts"] == {
        "passed": 0,
        "failed": 2,
        "total": 2,
        "withheld": 2,
    }


def test_item_scope_gap_does_not_withhold_a_complete_champion_package():
    def post(_path, payload):
        assert payload["champion"] == "Aatrox"
        return 200, {
            "items": ["Shadowflame"],
            "boots": None,
            "is_certified_best": False,
            "selection_certification": "event_ordered_item_scope_gap",
            "search_timeline_coverage": {
                "complete": True,
                "certification": "candidate_event_order_certified",
                "coarse_sources": [],
            },
            "candidate_coverage": {
                "complete": False,
                "excluded_count": 21,
                "excluded": [{"name": "Redemption", "reason": "active"}],
            },
        }

    report = run_matrix(post, ["Aatrox"])
    assert report["passed"] is True
    assert report["outcome_counts"] == {"certified_with_item_scope_gap": 1}
    assert report["results"][0]["candidate_coverage"]["excluded_count"] == 21
    assert report["results"][0]["selection_certification"] != "partial_or_unexhaustive"
    receipt = build_gate_report(report, ["Aatrox"])
    assert receipt["passed"] is True
    assert receipt["counts"] == {
        "passed": 1,
        "failed": 0,
        "total": 1,
        "withheld": 0,
    }
    assert receipt["failures"] == []


def test_matrix_requires_every_registered_name_and_elapsed_receipt():
    def post(_path, payload):
        return 200, {
            "is_certified_best": True,
            "search_timeline_coverage": {"complete": True},
            "items": [payload["champion"]],
        }

    report = run_matrix(post, ["Aatrox", "Ahri", "Ziggs"])
    assert report["all_registered_exercised"] is True
    assert report["registered_count"] == report["exercised_count"] == 3
    assert all(row["elapsed_ms"] >= 0 for row in report["results"])
    assert all(row["outcome"] == "certified" for row in report["results"])


def test_unexpected_status_fails_the_matrix():
    report = run_matrix(
        lambda _path, _payload: (500, {"error": "backend down"}), ["Ahri"]
    )
    assert report["passed"] is False
    assert report["outcome_counts"] == {"unexpected_failure": 1}
    assert report["results"][0]["error"] == "backend down"
