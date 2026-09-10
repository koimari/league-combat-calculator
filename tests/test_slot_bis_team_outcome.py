"""Per-slot team objectives preserve participant identity and budget scope."""

from copy import deepcopy

import pytest

import src.calculator.bis as bis
from src.calculator.data_fetcher import get_item_by_name
from src.calculator.optimizer import item_gold
from src.calculator.program.views import LeafWriter, name_every_number


def _scenario(subject):
    return {
        "champion": "Ashe",
        "level": 18,
        "role": "bottom",
        "items": ["Infinity Edge", "Bloodthirster"],
        "boots": "Berserker's Greaves",
        "fight_mode": "time_based",
        "fight_duration": 3,
        "objective": "team_outcome",
        "subject_team": subject,
        "subject_index": 0,
        "slot_index": 0,
        "allies": [
            {
                "champion": "Lulu",
                "level": 18,
                "role": "support",
                "items": ["Moonstone Renewer"],
            }
        ],
        "enemies": [
            {
                "champion": "Garen",
                "level": 18,
                "role": "top",
                "items": ["Black Cleaver"],
            }
        ],
    }


def _combat():
    payload = {
        "duration": 3.0,
        "objective": {
            "focus_damage_before_death": 20.0,
            "main_team_damage_before_death": 700.0,
            "enemy_team_damage_before_death": 450.0,
        },
        "participants": [
            {"participant_id": "main", "survival": {"effective_health": 1000.0}}
        ],
    }
    payload["dispositions"] = name_every_number(payload, LeafWriter())
    return payload


@pytest.mark.parametrize(
    ("subject", "expected"), [("main", 250), ("ally", 250), ("enemy", -250)]
)
def test_team_advantage_uses_selected_side_and_published_damage(subject, expected):
    combat = _combat()
    score, metric, components, rank_key = bis.bis_objective_score(
        "team_outcome",
        subject_team=subject,
        focus_id="main",
        combat=combat,
        objective=combat["objective"],
        focus=combat["participants"][0],
    )
    assert score == expected
    assert (
        score
        == components["selected_side_damage_before_death"]
        - components["opposing_side_damage_before_death"]
    )
    assert "minus opposing-side" in metric
    assert rank_key is None


def test_team_advantage_requires_opponent_damage_receipt():
    combat = _combat()
    del combat["objective"]["enemy_team_damage_before_death"]
    with pytest.raises(KeyError):
        bis.bis_objective_score(
            "team_outcome",
            subject_team="main",
            focus_id="main",
            combat=combat,
            objective=combat["objective"],
            focus=combat["participants"][0],
        )


def test_team_advantage_refuses_an_unnamed_opponent_value():
    combat = _combat()
    del combat["dispositions"]["objective.enemy_team_damage_before_death"]
    with pytest.raises(bis.UnrankableNumber):
        bis.bis_objective_score(
            "team_outcome",
            subject_team="main",
            focus_id="main",
            combat=combat,
            objective=combat["objective"],
            focus=combat["participants"][0],
        )


@pytest.mark.parametrize("subject", ["main", "ally", "enemy"])
def test_one_slot_changes_only_selected_participant_with_real_timeline(
    monkeypatch, subject
):
    candidate = get_item_by_name("Warmog's Armor")
    monkeypatch.setattr(
        bis, "bis_candidate_pool", lambda *_args, **_kwargs: [candidate]
    )
    original = bis.build_participant_timeline
    observed = []

    def record(champion, level, items, params, **kwargs):
        observed.append(
            {
                "main": [item["name"] for item in items],
                "ally": [item["name"] for item in kwargs["allies"][0].item_data],
                "enemy": [item["name"] for item in kwargs["enemies"][0].item_data],
            }
        )
        return original(champion, level, items, params, **kwargs)

    monkeypatch.setattr(bis, "build_participant_timeline", record)
    request = _scenario(subject)
    frozen = deepcopy(request)
    result = bis.bis_payload(request)
    assert request == frozen
    assert len(observed) == 1
    expected = {
        "main": ["Infinity Edge", "Bloodthirster", "Berserker's Greaves"],
        "ally": ["Moonstone Renewer"],
        "enemy": ["Black Cleaver"],
    }
    expected[subject][0] = "Warmog's Armor"
    for team in expected:
        assert sorted(observed[0][team]) == sorted(expected[team])
    assert result["candidate_count"] == 1
    rows = result["candidates"] + result["partial_candidates"]
    assert rows, result["withheld_candidates"]
    row = rows[0]
    assert row["price"] == item_gold(candidate)
    assert row["objective_value"] == pytest.approx(
        row["components"]["selected_side_damage_before_death"]
        - row["components"]["opposing_side_damage_before_death"],
        abs=0.11,
    )


def test_slot_budget_filters_before_scoring_and_accepts_zero(monkeypatch):
    candidates = [get_item_by_name("Warmog's Armor"), get_item_by_name("Trinity Force")]
    monkeypatch.setattr(bis, "bis_candidate_pool", lambda *_args, **_kwargs: candidates)

    def unexpected(*_args, **_kwargs):
        pytest.fail("Unaffordable candidates must not run the timeline")

    monkeypatch.setattr(bis, "build_participant_timeline", unexpected)
    result = bis.bis_payload({**_scenario("main"), "max_item_gold": 0})
    assert result["candidate_count"] == 0
    assert result["budget_excluded_candidate_count"] == 2
    assert result["candidates"] == []
    assert result["coverage"]["complete"] is False


@pytest.mark.parametrize("budget", [-1, 30001, True, 1.5, "invalid"])
def test_invalid_slot_budgets_fail_closed(budget):
    with pytest.raises(ValueError, match="max_item_gold"):
        bis.bis_payload({**_scenario("main"), "max_item_gold": budget})
