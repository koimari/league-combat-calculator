"""Fail-closed item-mechanic coverage for BIS search."""

import pytest

from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.item_coverage import (
    item_model_coverage,
    optimizer_candidate_coverage,
    require_certified_target_timeline,
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
        ("Serpent's Fang", "modeled_effect"),
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
        ("Force of Nature", "blocked"),
        ("Immortal Shieldbow", "modeled_event_certified"),
        ("Hexdrinker", "modeled_event_certified"),
        ("Maw of Malmortius", "modeled_event_certified"),
        ("Seraph's Embrace", "modeled_event_certified"),
        ("Sterak's Gage", "modeled_event_certified"),
        ("Protoplasm Harness", "modeled_event_certified"),
        ("Serpent's Fang", "not_target_relevant"),
        ("Void Staff", "not_target_relevant"),
    ],
)
def test_target_item_coverage_is_mechanic_specific(item_name, status):
    coverage = target_item_model_coverage(get_item_by_name(item_name))

    assert coverage["status"] == status
    assert coverage["calculation_eligible"] is (status != "blocked")


@pytest.mark.parametrize(
    "item_name",
    [
        "Immortal Shieldbow",
        "Hexdrinker",
        "Maw of Malmortius",
        "Seraph's Embrace",
        "Sterak's Gage",
        "Protoplasm Harness",
    ],
)
def test_lifeline_target_items_pass_precompute_coverage(item_name):
    require_target_item_coverage([get_item_by_name(item_name)])


def test_certified_timeline_guard_allows_certified_lifeline_fights():
    require_certified_target_timeline(
        [get_item_by_name("Sterak's Gage")],
        {"complete": True, "coarse_sources": []},
    )


def test_certified_timeline_guard_withholds_uncertified_lifeline_fights():
    with pytest.raises(
        ValueError,
        match=r"Sterak's Gage.*muramana_ability is not event-certified",
    ):
        require_certified_target_timeline(
            [get_item_by_name("Sterak's Gage")],
            {"complete": False, "coarse_sources": ["muramana_ability"]},
        )


def test_certified_timeline_guard_ignores_targets_without_lifeline_items():
    require_certified_target_timeline(
        [get_item_by_name("Kaenic Rookern")],
        {"complete": False, "coarse_sources": ["passive"]},
    )


def test_target_build_coverage_and_guard_name_the_omitted_defense():
    items = [get_item_by_name("Kaenic Rookern"), get_item_by_name("Banshee's Veil")]
    coverage = target_build_coverage(items)

    assert coverage["complete"] is False
    assert [entry["name"] for entry in coverage["blocked"]] == ["Banshee's Veil"]
    with pytest.raises(ValueError, match="Annul's first-hostile-ability"):
        require_target_item_coverage(items)


def test_armored_advance_target_diagnostic_names_unmodeled_noxian_endurance():
    """Do not imply upgraded Steelcaps are blocked for their modeled Plating.

    Armored Advance combines the supported 10% basic-damage reduction with a
    second, combat-triggered physical shield.  Until that ordered shield event
    is represented, the complete target item must remain fail-closed and the
    receipt should identify the actual missing mechanic.
    """
    coverage = target_item_model_coverage(get_item_by_name("Armored Advance"))

    assert coverage["status"] == "blocked"
    assert "Noxian Endurance" in coverage["reason"]
    with pytest.raises(ValueError, match="Noxian Endurance"):
        require_target_item_coverage([get_item_by_name("Armored Advance")])


def test_force_of_nature_target_defense_fails_closed_with_stack_timing_diagnostic():
    """Do not price Steadfast as permanent +70 MR in target comparisons.

    The passive is conditional on an ordered stream of incoming champion
    damage/immobilize events and has a one-second per-cast-instance throttle;
    aggregate damage rows cannot establish when the eighth stack is reached.
    """
    item = get_item_by_name("Force of Nature")
    coverage = target_item_model_coverage(item)

    assert coverage["status"] == "blocked"
    assert coverage["calculation_eligible"] is False
    assert (
        "at most one stack per incoming cast instance per second" in coverage["reason"]
    )
    assert "+70 bonus magic resistance" in coverage["reason"]

    with pytest.raises(ValueError, match="Force of Nature.*stack timing"):
        require_target_item_coverage([item])


def test_unknown_target_passive_fails_closed():
    item = {"name": "Future Bulwark", "passives": [{"name": "Unknown"}]}

    coverage = target_item_model_coverage(item)

    assert coverage["status"] == "review_pending"
    assert coverage["calculation_eligible"] is False
