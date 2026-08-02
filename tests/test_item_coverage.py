"""Fail-closed item-mechanic coverage for BIS search."""

import pytest

from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.item_coverage import (
    item_model_coverage,
    optimizer_candidate_coverage,
    require_target_item_coverage,
    target_build_coverage,
    target_item_model_coverage,
)
from src.calculator.optimizer import (
    get_eligible_boots,
    get_eligible_legendaries,
    optimize_build,
)


def test_every_current_optimizer_candidate_has_an_explicit_classification():
    candidates = get_eligible_legendaries() + get_eligible_boots(tier=None)
    classifications = [item_model_coverage(item) for item in candidates]

    assert classifications
    assert not [
        entry for entry in classifications if entry["status"] == "review_pending"
    ]


@pytest.mark.parametrize(
    ("item_name", "expected_status"),
    [
        ("Runaan's Hurricane", "blocked"),
        ("Zeke's Convergence", "blocked"),
        ("Immortal Path", "blocked"),
        ("Mejai's Soulstealer", "modeled_state"),
        ("Rabadon's Deathcap", "modeled_effect"),
        ("Kaenic Rookern", "stats_only"),
        ("Void Staff", "stats_only"),
    ],
)
def test_representative_item_classifications(item_name, expected_status):
    coverage = item_model_coverage(get_item_by_name(item_name))

    assert coverage["status"] == expected_status
    assert coverage["optimizer_eligible"] is (
        expected_status not in {"blocked", "review_pending"}
    )


def test_multitool_is_not_a_summoners_rift_optimizer_candidate():
    names = {item["name"] for item in get_eligible_legendaries()}

    assert "Multitool" not in names


def test_candidate_receipt_names_every_withheld_item():
    candidates = get_eligible_legendaries() + get_eligible_boots(tier=2)
    receipt = optimizer_candidate_coverage(candidates)
    excluded_names = {entry["name"] for entry in receipt["excluded"]}

    assert receipt["complete"] is False
    assert receipt["eligible_candidates"] == len(candidates)
    assert receipt["scored_candidates"] + receipt["excluded_count"] == len(candidates)
    assert {"Runaan's Hurricane", "Redemption", "Rod of Ages"} <= excluded_names


def test_optimizer_withholds_unmodeled_candidates_and_returns_receipt():
    result = optimize_build(
        get_champion("Ahri"),
        level=18,
        max_legendary_slots=1,
        locked_boots="Sorcerer's Shoes",
    )
    excluded_names = {
        entry["name"] for entry in result["candidate_coverage"]["excluded"]
    }

    assert result["items"]
    assert not (set(result["items"]) & excluded_names)
    assert result["search_guarantee"] == "exhaustive_modeled_candidates"
    assert result["is_certified_best"] is False


def test_optimizer_rejects_a_locked_item_with_unmodeled_damage_mechanics():
    with pytest.raises(
        ValueError,
        match="Runaan's Hurricane cannot be locked into BIS search yet",
    ):
        optimize_build(
            get_champion("Ahri"),
            level=18,
            max_legendary_slots=1,
            locked_items=["Runaan's Hurricane"],
            locked_boots="Sorcerer's Shoes",
        )


@pytest.mark.parametrize(
    ("item_name", "status"),
    [
        ("Kaenic Rookern", "modeled"),
        ("Spirit Visage", "modeled"),
        ("Warmog's Armor", "modeled"),
        ("Banshee's Veil", "blocked"),
        ("Plated Steelcaps", "modeled"),
        ("Warden's Mail", "modeled"),
        ("Randuin's Omen", "modeled"),
        ("Void Staff", "not_target_relevant"),
    ],
)
def test_target_item_coverage_is_mechanic_specific(item_name, status):
    coverage = target_item_model_coverage(get_item_by_name(item_name))

    assert coverage["status"] == status
    assert coverage["calculation_eligible"] is (status != "blocked")


def test_target_build_coverage_and_guard_name_the_omitted_defense():
    items = [get_item_by_name("Kaenic Rookern"), get_item_by_name("Banshee's Veil")]
    coverage = target_build_coverage(items)

    assert coverage["complete"] is False
    assert [entry["name"] for entry in coverage["blocked"]] == ["Banshee's Veil"]
    with pytest.raises(ValueError, match="Annul's first-hostile-ability"):
        require_target_item_coverage(items)


def test_unknown_target_passive_fails_closed():
    item = {"name": "Future Bulwark", "passives": [{"name": "Unknown"}]}

    coverage = target_item_model_coverage(item)

    assert coverage["status"] == "review_pending"
    assert coverage["calculation_eligible"] is False
