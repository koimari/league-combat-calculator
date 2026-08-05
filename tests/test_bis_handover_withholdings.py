"""End-to-end BIS fail-closed withholding contract (handover #14 re-audit).

Pins the current production scenario behavior on the pinned patch basis:
Bastionbreaker, Eclipse, and Muramana are excluded before ranking with an
unresolved-timing reason; Fimbulwinter stays visible as a partial audit row;
the search reports ``bis_certified_subset_not_exhaustive`` instead of a
certified Best in Slot.
"""

from src import app as app_module


def _ahri_annie_utility_bis_payload() -> dict:
    return {
        "champion": "Ahri",
        "level": 18,
        "items": [],
        "role": "mid",
        "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
        "fight_mode": "one_rotation",
        "include_auto_attacks": True,
        "auto_attack_uptime_mode": "calculated",
        "objective": "utility",
        "subject_team": "main",
        "subject_index": 0,
        "slot_index": 0,
        "slot_kind": "item",
        "enemies": [
            {
                "champion": "Annie",
                "level": 18,
                "items": [],
                "role": "mid",
                "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
            }
        ],
    }


def _run_bis():
    app_module.app.config["TESTING"] = True
    response = app_module.app.test_client().post(
        "/api/bis", json=_ahri_annie_utility_bis_payload()
    )
    assert response.status_code == 200
    return response.get_json()


def test_bis_utility_scenario_withholds_timing_unresolved_candidates():
    body = _run_bis()

    assert body["objective"]["key"] == "utility"
    coverage = body["coverage"]
    assert coverage["complete"] is False
    assert coverage["certification"] == "bis_certified_subset_not_exhaustive"

    assert body["withheld_candidate_count"] == 3
    withheld = {row["name"]: row for row in body["withheld_candidates"]}
    assert set(withheld) == {"Bastionbreaker", "Eclipse", "Muramana"}
    for name, row in withheld.items():
        assert row["reason"] == "candidate_excluded_unresolved_timing"
        assert row["exclusion_type"] == "applicability"
        assert row["excluded_sources"], name
        assert row["detail"], name
        assert row["timeline_coverage"]["certification"] == "partial_event_order"
        assert row["timeline_coverage"]["coarse_sources"], name

    assert body["partial_candidate_count"] == 1
    assert body["partial_candidates"][0]["name"] == "Fimbulwinter"


def test_bis_utility_scenario_certifies_remaining_candidates():
    body = _run_bis()

    assert body["candidate_count"] == 96
    assert body["certified_candidate_count"] == 92
    assert body["candidate_scope"] == "role-tagged:mid"
    assert body["timing_excluded_candidate_count"] == 3

    names = [row["name"] for row in body["candidates"]]
    assert "Bastionbreaker" not in names
    assert "Eclipse" not in names
    assert "Muramana" not in names
    assert "Fimbulwinter" not in names
    assert len(names) == body["certified_candidate_count"]
    for row in body["candidates"]:
        assert row["objective_value"] is not None
