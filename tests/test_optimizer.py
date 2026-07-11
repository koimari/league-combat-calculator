"""Tests for the build optimizer."""

import pytest

from src.calculator.data_fetcher import get_champion
from src.calculator.optimizer import (
    get_eligible_legendaries,
    get_eligible_boots,
    optimize_build,
    _SPELLBLADE_ITEMS,
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
            assert boot.get("tier", 0) >= 2


class TestOptimizerBasic:
    """Basic optimizer functionality tests."""

    def test_optimizer_returns_correct_keys(self):
        champ_data = get_champion("Ahri")
        result = optimize_build(
            "Ahri", champ_data, level=18,
            target_health=2000, target_armor=50, target_mr=40,
            max_legendary_slots=5,
        )
        assert "items" in result
        assert "boots" in result
        assert "total_damage" in result
        assert "objective" in result
        assert "optimization_time_ms" in result
        assert "evaluations" in result

    def test_optimizer_fills_correct_slot_count_5(self):
        champ_data = get_champion("Ahri")
        result = optimize_build(
            "Ahri", champ_data, level=18,
            target_health=2000, target_armor=50, target_mr=40,
            max_legendary_slots=5,
        )
        assert len(result["items"]) == 5
        assert result["boots"] is not None

    def test_optimizer_fills_correct_slot_count_6(self):
        champ_data = get_champion("Ahri")
        result = optimize_build(
            "Ahri", champ_data, level=18,
            target_health=2000, target_armor=50, target_mr=40,
            max_legendary_slots=6,
        )
        assert len(result["items"]) == 6
        assert result["boots"] is not None

    def test_optimizer_no_duplicate_items(self):
        champ_data = get_champion("Aatrox")
        result = optimize_build(
            "Aatrox", champ_data, level=18,
            target_health=3000, target_armor=100, target_mr=60,
            fight_mode="timed", fight_duration=10,
            include_auto_attacks=True, auto_attack_uptime=0.7,
            max_legendary_slots=6,
        )
        names = result["items"]
        assert len(names) == len(set(names)), f"Duplicate items found: {names}"

    def test_optimizer_positive_damage(self):
        champ_data = get_champion("Ahri")
        result = optimize_build(
            "Ahri", champ_data, level=18,
            target_health=2000, target_armor=50, target_mr=40,
            max_legendary_slots=5,
        )
        assert result["total_damage"] > 0

    def test_optimizer_completes_under_5_seconds(self):
        champ_data = get_champion("Ahri")
        result = optimize_build(
            "Ahri", champ_data, level=18,
            target_health=2000, target_armor=50, target_mr=40,
            max_legendary_slots=5,
        )
        assert result["optimization_time_ms"] < 5000


class TestLockedItems:
    """Tests for locked item slot support."""

    def test_locked_legendary_preserved(self):
        champ_data = get_champion("Ahri")
        result = optimize_build(
            "Ahri", champ_data, level=18,
            target_health=2000, target_armor=50, target_mr=40,
            locked_items=["Luden's Echo"],
            max_legendary_slots=5,
        )
        assert "Luden's Echo" in result["items"]
        assert len(result["items"]) == 5

    def test_locked_boots_preserved(self):
        champ_data = get_champion("Ahri")
        result = optimize_build(
            "Ahri", champ_data, level=18,
            target_health=2000, target_armor=50, target_mr=40,
            locked_boots="Sorcerer's Shoes",
            max_legendary_slots=5,
        )
        assert result["boots"] == "Sorcerer's Shoes"

    def test_locked_multiple_items(self):
        champ_data = get_champion("Ahri")
        result = optimize_build(
            "Ahri", champ_data, level=18,
            target_health=2000, target_armor=50, target_mr=40,
            locked_items=["Luden's Echo", "Rabadon's Deathcap"],
            max_legendary_slots=5,
        )
        assert "Luden's Echo" in result["items"]
        assert "Rabadon's Deathcap" in result["items"]
        assert len(result["items"]) == 5

    def test_all_slots_locked_returns_quickly(self):
        """When all slots are locked, optimizer should evaluate only that build."""
        champ_data = get_champion("Ahri")
        result = optimize_build(
            "Ahri", champ_data, level=18,
            target_health=2000, target_armor=50, target_mr=40,
            locked_items=["Luden's Echo", "Rabadon's Deathcap",
                          "Shadowflame", "Void Staff", "Stormsurge"],
            locked_boots="Sorcerer's Shoes",
            max_legendary_slots=5,
        )
        assert result["total_damage"] > 0
        assert result["optimization_time_ms"] < 500


class TestExclusivityGroups:
    """Tests for item exclusivity group enforcement."""

    def test_no_two_spellblades(self):
        champ_data = get_champion("Aatrox")
        result = optimize_build(
            "Aatrox", champ_data, level=18,
            target_health=3000, target_armor=100, target_mr=60,
            fight_mode="timed", fight_duration=10,
            include_auto_attacks=True, auto_attack_uptime=0.7,
            max_legendary_slots=6,
        )
        spellblades_in_build = [
            name for name in result["items"] if name in _SPELLBLADE_ITEMS
        ]
        assert len(spellblades_in_build) <= 1, (
            f"Multiple spellblades: {spellblades_in_build}"
        )

    def test_no_two_hydra_items(self):
        champ_data = get_champion("Aatrox")
        result = optimize_build(
            "Aatrox", champ_data, level=18,
            target_health=3000, target_armor=100, target_mr=60,
            fight_mode="timed", fight_duration=10,
            include_auto_attacks=True, auto_attack_uptime=0.7,
            max_legendary_slots=6,
        )
        hydra_group = {"Tiamat", "Profane Hydra", "Ravenous Hydra",
                       "Stridebreaker", "Titanic Hydra"}
        hydras = [n for n in result["items"] if n in hydra_group]
        assert len(hydras) <= 1, f"Multiple Hydra items: {hydras}"

    def test_no_two_blight_items(self):
        champ_data = get_champion("Ahri")
        result = optimize_build(
            "Ahri", champ_data, level=18,
            target_health=2000, target_armor=50, target_mr=40,
            max_legendary_slots=6,
        )
        blight_group = {"Blighting Jewel", "Bloodletter's Curse", "Cryptbloom",
                        "Terminus", "Void Staff"}
        blights = [n for n in result["items"] if n in blight_group]
        assert len(blights) <= 1, f"Multiple Blight items: {blights}"

    def test_no_two_fatality_items(self):
        champ_data = get_champion("Aatrox")
        result = optimize_build(
            "Aatrox", champ_data, level=18,
            target_health=3000, target_armor=200, target_mr=60,
            fight_mode="timed", fight_duration=10,
            include_auto_attacks=True, auto_attack_uptime=0.7,
            objective="physical_damage",
            max_legendary_slots=6,
        )
        fatality_group = {"Last Whisper", "Black Cleaver", "Lord Dominik's Regards",
                          "Mortal Reminder", "Serylda's Grudge", "Terminus"}
        fatalities = [n for n in result["items"] if n in fatality_group]
        assert len(fatalities) <= 1, f"Multiple Fatality items: {fatalities}"


class TestObjectives:
    """Tests for different optimization objectives."""

    def test_ap_champion_magic_objective(self):
        champ_data = get_champion("Ahri")
        result = optimize_build(
            "Ahri", champ_data, level=18,
            target_health=2000, target_armor=50, target_mr=40,
            objective="magic_damage",
            max_legendary_slots=5,
        )
        assert result["objective"] == "magic_damage"
        assert result["total_damage"] > 0

    def test_ad_champion_physical_objective(self):
        champ_data = get_champion("Aatrox")
        result = optimize_build(
            "Aatrox", champ_data, level=18,
            target_health=3000, target_armor=100, target_mr=60,
            fight_mode="timed", fight_duration=10,
            include_auto_attacks=True, auto_attack_uptime=0.7,
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
            "Ahri", champ_data, level=18,
            target_health=2000, target_armor=50, target_mr=40,
            max_legendary_slots=5,
        )
        result_6 = optimize_build(
            "Ahri", champ_data, level=18,
            target_health=2000, target_armor=50, target_mr=40,
            max_legendary_slots=6,
        )
        assert result_6["total_damage"] >= result_5["total_damage"]
