"""Tests for the build optimizer."""

import pytest

from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.optimizer import (
    _evaluate_build,
    exclusivity_groups,
    get_eligible_legendaries,
    get_eligible_boots,
    optimize_build as _optimize_build,
    get_selectable_items,
    _SPELLBLADE_ITEMS,
    _hill_climb,
)
from src.calculator.pipeline import FightParams
from src.calculator.loadout_rules import role_scoped_shop_items

_FIGHT_PARAM_KEYS = {
    "target_health",
    "target_bonus_health",
    "target_armor",
    "target_mr",
    "fight_mode",
    "fight_duration",
    "include_auto_attacks",
    "auto_attack_uptime",
    "auto_attacks_only",
    "ability_ranks",
    "include_actives",
    "cast_order",
    "champion_options",
    "role",
    "role_quest_complete",
}


def optimize_build(_champion_name, champion_data, level, **kwargs):
    """Keep scenarios readable while exercising the public FightParams seam."""
    request_values = {
        key: kwargs.pop(key) for key in tuple(kwargs) if key in _FIGHT_PARAM_KEYS
    }
    fight_params = FightParams.from_request(request_values, deterministic=True)
    return _optimize_build(
        champion_data,
        level,
        fight_params=fight_params,
        **kwargs,
    )


class TestItemPools:
    """Tests for item pool loading."""

    def test_eligible_legendaries_not_empty(self):
        items = get_eligible_legendaries()
        assert len(items) > 100

    def test_eligible_legendaries_excludes_boots(self):
        items = get_eligible_legendaries()
        for item in items:
            assert "BOOTS" not in item.get("rank", [])

    def test_eligible_boots_not_empty(self):
        boots = get_eligible_boots()
        assert len(boots) >= 5

    def test_eligible_boots_are_tier_2_plus(self):
        boots = get_eligible_boots()
        for boot in boots:
            assert boot.get("tier") == 2

    def test_mid_quest_boot_pool_is_tier_3(self):
        boots = get_eligible_boots(tier=3)
        assert boots
        assert all(boot.get("tier") == 3 for boot in boots)

    def test_manual_pool_includes_components_and_starters(self):
        names = {item["name"] for item in get_selectable_items()}

        assert "Ruby Crystal" in names
        assert "Dark Seal" in names
        assert "Doran's Ring" in names
        assert "Boots of Swiftness" not in names

    @pytest.mark.parametrize(
        "name",
        [
            "Guardian's Amulet",
            "Guardian's Blade",
            "Guardian's Dirk",
            "Guardian's Hammer",
            "Guardian's Horn",
            "Guardian's Orb",
            "Guardian's Shroud",
            "Lifeline",
        ],
    )
    def test_pool_excludes_items_absent_from_summoners_rift(self, name):
        """ARAM starters and the Arena-only Soul Anchor item are not SR builds."""
        assert name not in {item["name"] for item in get_selectable_items()}

    def test_pool_excludes_champion_granted_items(self):
        """Black Spear is handed to Kalista and Sylas, never bought."""
        assert "Black Spear" not in {item["name"] for item in get_selectable_items()}

    def test_pool_excludes_quest_transforms_that_are_never_sold(self):
        """Bounty of Worlds only exists once the support quest transforms it."""
        pools = (
            get_selectable_items()
            + get_eligible_legendaries()
            + get_eligible_boots(None)
        )
        assert "Bounty of Worlds" not in {item["name"] for item in pools}

    def test_every_pool_item_is_available_on_summoners_rift(self):
        pools = (
            get_selectable_items()
            + get_eligible_legendaries()
            + get_eligible_boots(None)
        )
        off_rift = [
            item["name"] for item in pools if not item["modes"].get("classic sr 5v5")
        ]
        assert off_rift == []

    def test_main_optimizer_uses_the_sourced_role_shop_scope(self):
        candidates = get_eligible_legendaries()
        top = {item["name"] for item in role_scoped_shop_items(candidates, "top")}
        support = {
            item["name"] for item in role_scoped_shop_items(candidates, "support")
        }

        assert "Shurelya's Battlesong" not in top
        assert "Shurelya's Battlesong" in support
        assert "Warmog's Armor" in top
        assert "Warmog's Armor" not in support

    def test_top_search_never_evaluates_a_support_only_candidate(self, monkeypatch):
        def fake_evaluate(_champion, _level, items, **_kwargs):
            assert "Shurelya's Battlesong" not in {item["name"] for item in items}
            return 1.0

        monkeypatch.setattr("src.calculator.optimizer._evaluate_build", fake_evaluate)
        params = FightParams.from_request({"role": "top"}, deterministic=True)
        result = _optimize_build(
            get_champion("Aatrox"),
            6,
            fight_params=params,
            max_legendary_slots=1,
            include_boots=False,
        )

        assert "Shurelya's Battlesong" not in result["items"]


def test_evaluate_build_sums_objective_across_target_roster(monkeypatch):
    """One candidate build is scored into every selected enemy."""

    def fake_run_fight(_champion, _level, _items, params):
        damage = params.target_health / 10
        return {
            "total_damage": damage,
            "breakdown": {
                "spell": {
                    "damage_type": "magic",
                    "total_damage": damage,
                }
            },
        }

    monkeypatch.setattr("src.calculator.optimizer.run_fight", fake_run_fight)
    first = FightParams.from_request({"target_health": 1000}, deterministic=True)
    second = FightParams.from_request({"target_health": 2500}, deterministic=True)

    score = _evaluate_build({}, 1, [], (first, second), "magic_damage")

    assert score == 350


def test_hill_climb_reuses_greedy_score_without_duplicate_evaluation(monkeypatch):
    monkeypatch.setattr(
        "src.calculator.optimizer._evaluate_build",
        lambda *_args, **_kwargs: pytest.fail("duplicate initial evaluation"),
    )
    item = {"name": "Rabadon's Deathcap"}
    legendaries, boots, score, evals = _hill_climb(
        {},
        18,
        [item],
        None,
        set(),
        True,
        [],
        [],
        {
            "fight_params": FightParams.from_request({}, deterministic=True),
            "objective": "total_damage",
        },
        max_iterations=0,
        initial_score=42.0,
    )

    assert legendaries == [item]
    assert boots is None
    assert score == 42.0
    assert evals == 0


def test_coupled_total_damage_does_not_add_effective_health_twice(monkeypatch):
    """Survival-coupled output is already truncated at the main actor's death."""
    monkeypatch.setattr(
        "src.calculator.optimizer.build_participant_timeline",
        lambda *args, **kwargs: {
            "breakdown": [{"participant_id": "main", "total_damage": 125.0}],
            "participants": [
                {"participant_id": "main", "survival": {"effective_health": 4000.0}}
            ],
            "events": [],
            "timeline_coverage": {
                "complete": True,
                "exact_sources": [],
                "coarse_sources": [],
            },
        },
    )
    params = FightParams.from_request({}, deterministic=True)

    score = _evaluate_build(
        get_champion("Aatrox"),
        18,
        [],
        params,
        "total_damage",
        combat_context={"enemies": [object()], "allies": []},
    )

    assert score == 125.0


def test_coupled_equal_damage_uses_event_health_only_as_tie_break(monkeypatch):
    def fake_timeline(*_args, **kwargs):
        items = kwargs.get("items") or _args[2]
        health = (
            2_000.0
            if any(item["name"] == "Warmog's Armor" for item in items)
            else 1_000.0
        )
        return {
            "breakdown": [{"participant_id": "main", "total_damage": 500.0}],
            "participants": [
                {"participant_id": "main", "survival": {"effective_health": health}}
            ],
            "events": [],
            "timeline_coverage": {
                "complete": True,
                "exact_sources": [],
                "coarse_sources": [],
            },
        }

    monkeypatch.setattr(
        "src.calculator.optimizer.build_participant_timeline", fake_timeline
    )
    result = optimize_build(
        "Aatrox",
        get_champion("Aatrox"),
        level=6,
        role="top",
        max_legendary_slots=1,
        include_boots=False,
        enemy_loadouts=[object()],
        require_complete_timeline=True,
    )

    assert result["total_damage"] == 500.0
    assert "Warmog's Armor" in result["items"]


def test_coupled_candidate_with_fail_closed_protoplasm_is_skipped(monkeypatch):
    """One unsupported target-state candidate must not abort the search."""

    def fake_timeline(*_args, **kwargs):
        items = kwargs.get("items") or _args[2]
        if any(item["name"] == "Protoplasm Harness" for item in items):
            raise ValueError(
                "This damage package scales from target maximum health and "
                "cannot yet be certified against Protoplasm Harness's "
                "temporary maximum-health change."
            )
        return {
            "breakdown": [{"participant_id": "main", "total_damage": 10.0}],
            "participants": [
                {"participant_id": "main", "survival": {"effective_health": 1.0}}
            ],
            "events": [],
            "timeline_coverage": {
                "complete": True,
                "exact_sources": [],
                "coarse_sources": [],
            },
        }

    monkeypatch.setattr(
        "src.calculator.optimizer.build_participant_timeline", fake_timeline
    )
    params = FightParams.from_request({"role": "top"}, deterministic=True)
    result = _optimize_build(
        get_champion("Aatrox"),
        6,
        fight_params=params,
        max_legendary_slots=1,
        include_boots=False,
        enemy_loadouts=[object()],
        require_complete_timeline=True,
    )

    assert result["items"]
    assert "Protoplasm Harness" not in result["items"]
    assert result["timeline_withheld_evaluations"] > 0


def test_coupled_optimizer_rejects_partial_candidates_before_ranking(monkeypatch):
    """A partial item event cannot win the main champion's coupled search."""

    def fake_timeline(*_args, **kwargs):
        items = kwargs.get("items") or _args[2]
        partial = any(item.get("name") == "Unending Despair" for item in items)
        return {
            "breakdown": [{"participant_id": "main", "total_damage": 900.0}],
            "participants": [],
            "events": [],
            "timeline_coverage": {
                "complete": not partial,
                "exact_sources": [],
                "coarse_sources": ["periodic_Unending Despair"] if partial else [],
            },
        }

    monkeypatch.setattr(
        "src.calculator.optimizer.build_participant_timeline", fake_timeline
    )
    result = optimize_build(
        "Aatrox",
        get_champion("Aatrox"),
        level=6,
        max_legendary_slots=1,
        locked_boots="Sorcerer's Shoes",
        enemy_loadouts=[object()],
        require_complete_timeline=True,
    )

    assert result["is_certified_best"] is True
    assert result["selection_certification"] == "event_ordered_local_search"
    assert "Unending Despair" not in result["items"]


def test_coupled_evaluate_withholds_partial_timeline(monkeypatch):
    monkeypatch.setattr(
        "src.calculator.optimizer.build_participant_timeline",
        lambda *_args, **_kwargs: {
            "breakdown": [{"participant_id": "main", "total_damage": 125.0}],
            "participants": [],
            "events": [],
            "timeline_coverage": {
                "complete": False,
                "exact_sources": [],
                "coarse_sources": ["periodic_item"],
            },
        },
    )
    params = FightParams.from_request({}, deterministic=True)
    score = _evaluate_build(
        get_champion("Aatrox"),
        18,
        [],
        params,
        "total_damage",
        require_complete_timeline=True,
        combat_context={"enemies": [object()], "allies": []},
    )

    assert score == float("-inf")


def test_optimizer_respects_gold_budget():
    result = optimize_build(
        "Ahri",
        get_champion("Ahri"),
        level=18,
        max_legendary_slots=2,
        gold_budget=7_000,
    )

    assert result["ranked_builds"]
    assert all(build["gold"] <= 7_000 for build in result["ranked_builds"])


def test_one_open_slot_is_exhaustive_for_modeled_items_and_has_runner_up():
    result = optimize_build(
        "Ahri",
        get_champion("Ahri"),
        level=18,
        max_legendary_slots=2,
        locked_items=["Rabadon's Deathcap"],
        locked_boots="Sorcerer's Shoes",
    )

    assert result["is_certified_best"] is False
    assert result["search_guarantee"] == "exhaustive_modeled_candidates"
    assert result["candidate_coverage"]["excluded_count"] > 0
    assert len(result["ranked_builds"]) == 2
    assert result["ranked_builds"][0]["items"] != result["ranked_builds"][1]["items"]


def test_candidate_item_coverage_alone_does_not_certify_partial_timelines(
    monkeypatch,
):
    monkeypatch.setattr(
        "src.calculator.optimizer.optimizer_candidate_coverage",
        lambda items: {
            "eligible_candidates": len(items),
            "scored_candidates": len(items),
            "excluded_count": 0,
            "complete": True,
            "excluded": [],
            "note": "Every available candidate is fully modelled.",
        },
    )

    result = optimize_build(
        "Ahri",
        get_champion("Ahri"),
        level=18,
        max_legendary_slots=2,
        locked_items=["Rabadon's Deathcap"],
        locked_boots="Sorcerer's Shoes",
    )

    assert result["is_certified_best"] is False
    assert result["search_guarantee"] == "exhaustive_legal_candidates"
    assert result["search_timeline_coverage"]["complete"] is False
    assert result["search_timeline_coverage"]["partial_evaluations"] > 0


def test_one_open_slot_is_certified_when_candidates_and_timelines_are_complete(
    monkeypatch,
):
    monkeypatch.setattr(
        "src.calculator.optimizer.optimizer_candidate_coverage",
        lambda items: {
            "eligible_candidates": len(items),
            "scored_candidates": len(items),
            "excluded_count": 0,
            "complete": True,
            "excluded": [],
            "note": "Every available candidate is fully modelled.",
        },
    )

    def exact_fight(_champion, _level, items, _params):
        damage = float(len(items) * 100)
        return {
            "total_damage": damage,
            "breakdown": {},
            "timeline_coverage": {
                "complete": True,
                "certification": "event_order_certified",
                "exact_sources": [],
                "coarse_sources": [],
                "note": "Every active damage source is event-ordered.",
            },
        }

    monkeypatch.setattr("src.calculator.optimizer.run_fight", exact_fight)
    result = optimize_build(
        "Ahri",
        get_champion("Ahri"),
        level=18,
        max_legendary_slots=2,
        locked_items=["Rabadon's Deathcap"],
        locked_boots="Sorcerer's Shoes",
    )

    assert result["is_certified_best"] is True
    assert result["search_timeline_coverage"]["complete"] is True
    assert result["timeline_coverage"]["complete"] is True
    assert all(
        build["timeline_coverage"]["complete"] for build in result["ranked_builds"]
    )


def test_optimizer_is_champion_specific_for_orianna_auto_uptime():
    """High AA uptime must not collapse Orianna and Aatrox to one AD build."""
    shared = {
        "level": 18,
        "target_health": 2500,
        "target_armor": 100,
        "target_mr": 55,
        "fight_mode": "time_based",
        "fight_duration": 10,
        "include_auto_attacks": True,
        "auto_attack_uptime": 0.8,
        "max_legendary_slots": 5,
    }
    orianna = optimize_build("Orianna", get_champion("Orianna"), **shared)
    aatrox = optimize_build("Aatrox", get_champion("Aatrox"), **shared)

    orianna_items = [get_item_by_name(name) for name in orianna["items"]]
    ap_items = sum(
        item.get("stats", {}).get("abilityPower", {}).get("flat", 0) > 0
        for item in orianna_items
    )

    assert ap_items >= 3
    assert orianna["items"] != aatrox["items"]


class TestOptimizerBasic:
    """Basic optimizer functionality tests."""

    def test_optimizer_returns_correct_keys(self):
        champ_data = get_champion("Ahri")
        result = optimize_build(
            "Ahri",
            champ_data,
            level=18,
            target_health=2000,
            target_armor=50,
            target_mr=40,
            max_legendary_slots=5,
        )

        assert len(result["ranked_builds"]) == 2
        assert (
            result["ranked_builds"][0]["items"] != result["ranked_builds"][1]["items"]
        )
        assert (
            result["ranked_builds"][0]["total_damage"]
            >= result["ranked_builds"][1]["total_damage"]
        )
        assert result["ranked_builds"][0]["dps"] > 0
        assert result["is_certified_best"] is False
        assert "items" in result
        assert "boots" in result
        assert "total_damage" in result
        assert "objective" in result
        assert "optimization_time_ms" in result
        assert "evaluations" in result

    @pytest.mark.parametrize("slot_count", [1, 2, 3, 4, 5, 6])
    def test_optimizer_fills_correct_slot_count(self, slot_count):
        champ_data = get_champion("Ahri")
        result = optimize_build(
            "Ahri",
            champ_data,
            level=18,
            target_health=2000,
            target_armor=50,
            target_mr=40,
            max_legendary_slots=slot_count,
        )
        assert len(result["items"]) == slot_count
        assert result["boots"] is not None

    def test_optimizer_no_duplicate_items(self):
        champ_data = get_champion("Aatrox")
        result = optimize_build(
            "Aatrox",
            champ_data,
            level=18,
            target_health=3000,
            target_armor=100,
            target_mr=60,
            fight_mode="timed",
            fight_duration=10,
            include_auto_attacks=True,
            auto_attack_uptime=0.7,
            max_legendary_slots=6,
        )
        names = result["items"]
        assert len(names) == len(set(names)), f"Duplicate items found: {names}"

    def test_optimizer_positive_damage(self):
        champ_data = get_champion("Ahri")
        result = optimize_build(
            "Ahri",
            champ_data,
            level=18,
            target_health=2000,
            target_armor=50,
            target_mr=40,
            max_legendary_slots=5,
        )
        assert result["total_damage"] > 0

    def test_optimizer_completes_under_5_seconds(self):
        champ_data = get_champion("Ahri")
        result = optimize_build(
            "Ahri",
            champ_data,
            level=18,
            target_health=2000,
            target_armor=50,
            target_mr=40,
            max_legendary_slots=5,
        )
        assert result["optimization_time_ms"] < 5000


class TestLockedItems:
    """Tests for locked item slot support."""

    def test_locked_legendary_preserved(self):
        champ_data = get_champion("Ahri")
        result = optimize_build(
            "Ahri",
            champ_data,
            level=18,
            target_health=2000,
            target_armor=50,
            target_mr=40,
            locked_items=["Luden's Echo"],
            max_legendary_slots=5,
        )
        assert "Luden's Echo" in result["items"]
        assert len(result["items"]) == 5

    def test_locked_boots_preserved(self):
        champ_data = get_champion("Ahri")
        result = optimize_build(
            "Ahri",
            champ_data,
            level=18,
            target_health=2000,
            target_armor=50,
            target_mr=40,
            locked_boots="Sorcerer's Shoes",
            max_legendary_slots=5,
        )
        assert result["boots"] == "Sorcerer's Shoes"

    def test_locked_multiple_items(self):
        champ_data = get_champion("Ahri")
        result = optimize_build(
            "Ahri",
            champ_data,
            level=18,
            target_health=2000,
            target_armor=50,
            target_mr=40,
            locked_items=["Luden's Echo", "Rabadon's Deathcap"],
            max_legendary_slots=5,
        )
        assert "Luden's Echo" in result["items"]
        assert "Rabadon's Deathcap" in result["items"]
        assert len(result["items"]) == 5

    def test_locked_items_filling_every_slot_returns_exactly_those_items(self):
        """Seeding must not push the build past max_legendary_slots."""
        champ_data = get_champion("Ahri")
        locked = ["Luden's Echo", "Rabadon's Deathcap"]
        result = optimize_build(
            "Ahri",
            champ_data,
            level=18,
            target_health=2000,
            target_armor=50,
            target_mr=40,
            locked_items=locked,
            max_legendary_slots=2,
        )
        assert sorted(result["items"]) == sorted(locked)

    def test_all_slots_locked_returns_quickly(self):
        """When all slots are locked, optimizer should evaluate only that build."""
        champ_data = get_champion("Ahri")
        result = optimize_build(
            "Ahri",
            champ_data,
            level=18,
            target_health=2000,
            target_armor=50,
            target_mr=40,
            locked_items=[
                "Luden's Echo",
                "Rabadon's Deathcap",
                "Shadowflame",
                "Void Staff",
                "Stormsurge",
            ],
            locked_boots="Sorcerer's Shoes",
            max_legendary_slots=5,
        )
        assert result["total_damage"] > 0
        assert result["optimization_time_ms"] < 500


class TestExclusivityGroupsAccessor:
    """Tests for the JSON-safe exclusivity_groups() accessor (served to the UI)."""

    def test_all_groups_present(self):
        groups = exclusivity_groups()
        assert set(groups) == {"Glory", "Spellblade", "Hydra", "Blight", "Fatality"}

    def test_glory_group_members(self):
        groups = exclusivity_groups()
        assert groups["Glory"] == ["Dark Seal", "Mejai's Soulstealer"]

    def test_spellblade_group_members(self):
        # Spellblade was missing from the old hand-copied app.js table;
        # the served table must include it.
        groups = exclusivity_groups()
        assert "Sheen" in groups["Spellblade"]
        assert "Trinity Force" in groups["Spellblade"]
        assert "Lich Bane" in groups["Spellblade"]

    def test_values_are_json_safe_sorted_lists(self):
        groups = exclusivity_groups()
        for members in groups.values():
            assert isinstance(members, list)
            assert members == sorted(members)
            assert all(isinstance(name, str) for name in members)


class TestExclusivityGroups:
    """Tests for item exclusivity group enforcement."""

    def test_no_two_spellblades(self):
        champ_data = get_champion("Aatrox")
        result = optimize_build(
            "Aatrox",
            champ_data,
            level=18,
            target_health=3000,
            target_armor=100,
            target_mr=60,
            fight_mode="timed",
            fight_duration=10,
            include_auto_attacks=True,
            auto_attack_uptime=0.7,
            max_legendary_slots=6,
        )
        spellblades_in_build = [
            name for name in result["items"] if name in _SPELLBLADE_ITEMS
        ]
        assert (
            len(spellblades_in_build) <= 1
        ), f"Multiple spellblades: {spellblades_in_build}"

    def test_no_two_hydra_items(self):
        champ_data = get_champion("Aatrox")
        result = optimize_build(
            "Aatrox",
            champ_data,
            level=18,
            target_health=3000,
            target_armor=100,
            target_mr=60,
            fight_mode="timed",
            fight_duration=10,
            include_auto_attacks=True,
            auto_attack_uptime=0.7,
            max_legendary_slots=6,
        )
        hydra_group = {
            "Tiamat",
            "Profane Hydra",
            "Ravenous Hydra",
            "Stridebreaker",
            "Titanic Hydra",
        }
        hydras = [n for n in result["items"] if n in hydra_group]
        assert len(hydras) <= 1, f"Multiple Hydra items: {hydras}"

    def test_no_two_blight_items(self):
        champ_data = get_champion("Ahri")
        result = optimize_build(
            "Ahri",
            champ_data,
            level=18,
            target_health=2000,
            target_armor=50,
            target_mr=40,
            max_legendary_slots=6,
        )
        blight_group = {
            "Blighting Jewel",
            "Bloodletter's Curse",
            "Cryptbloom",
            "Terminus",
            "Void Staff",
        }
        blights = [n for n in result["items"] if n in blight_group]
        assert len(blights) <= 1, f"Multiple Blight items: {blights}"

    def test_no_two_fatality_items(self):
        champ_data = get_champion("Aatrox")
        result = optimize_build(
            "Aatrox",
            champ_data,
            level=18,
            target_health=3000,
            target_armor=200,
            target_mr=60,
            fight_mode="timed",
            fight_duration=10,
            include_auto_attacks=True,
            auto_attack_uptime=0.7,
            objective="physical_damage",
            max_legendary_slots=6,
        )
        fatality_group = {
            "Last Whisper",
            "Black Cleaver",
            "Lord Dominik's Regards",
            "Mortal Reminder",
            "Serylda's Grudge",
            "Terminus",
        }
        fatalities = [n for n in result["items"] if n in fatality_group]
        assert len(fatalities) <= 1, f"Multiple Fatality items: {fatalities}"


class TestObjectives:
    """Tests for different optimization objectives."""

    def test_ap_champion_magic_objective(self):
        champ_data = get_champion("Ahri")
        result = optimize_build(
            "Ahri",
            champ_data,
            level=18,
            target_health=2000,
            target_armor=50,
            target_mr=40,
            objective="magic_damage",
            max_legendary_slots=5,
        )
        assert result["objective"] == "magic_damage"
        assert result["total_damage"] > 0

    def test_ad_champion_physical_objective(self):
        champ_data = get_champion("Aatrox")
        result = optimize_build(
            "Aatrox",
            champ_data,
            level=18,
            target_health=3000,
            target_armor=100,
            target_mr=60,
            fight_mode="timed",
            fight_duration=10,
            include_auto_attacks=True,
            auto_attack_uptime=0.7,
            objective="physical_damage",
            max_legendary_slots=5,
        )
        assert result["objective"] == "physical_damage"
        assert result["total_damage"] > 0


class TestSixVsFiveSlots:
    """Tests for 5 vs 6 legendary slots."""

    def test_six_slots_at_least_as_good_as_five(self):
        champ_data = get_champion("Ahri")
        result_5 = optimize_build(
            "Ahri",
            champ_data,
            level=18,
            target_health=2000,
            target_armor=50,
            target_mr=40,
            max_legendary_slots=5,
        )
        result_6 = optimize_build(
            "Ahri",
            champ_data,
            level=18,
            target_health=2000,
            target_armor=50,
            target_mr=40,
            max_legendary_slots=6,
        )
        assert result_6["total_damage"] >= result_5["total_damage"]
