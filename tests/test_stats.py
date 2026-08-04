"""Tests for the champion stats calculation module."""

import pytest

from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.stats import (
    apply_movement_speed_soft_caps,
    growth_stat,
    calculate_attack_speed,
    get_champion_base_stats,
    get_item_stats,
    calculate_total_stats,
)


class TestLethality:
    """Lethality grants its full value as flat armor pen at every level.

    Since V14.1 lethality no longer scales with level -- it is 1:1 flat
    armor penetration (the name survives only to distinguish it from
    percent penetration).
    """

    @pytest.mark.parametrize("level", [1, 9, 18, 20])
    def test_lethality_is_full_flat_armor_pen(self, ahri_data: dict, level: int):
        ghostblade = get_item_by_name("Youmuu's Ghostblade")
        stats = calculate_total_stats(ahri_data, level, [ghostblade])
        assert stats["lethality"] > 0
        assert stats["flat_armor_penetration"] == stats["lethality"]


class TestStatefulItemStats:
    """Explicit item state feeds downstream stat conversions exactly."""

    def test_heartsteel_health_state_increases_max_health(self, ahri_data: dict):
        item = get_item_by_name("Heartsteel")
        base = calculate_total_stats(ahri_data, 18, [item])
        stacked = calculate_total_stats(
            ahri_data,
            18,
            [item],
            item_options={"Heartsteel": {"bonus_health": 500}},
        )
        assert stacked["health"] == base["health"] + 500
        assert stacked["bonus_health"] == base["bonus_health"] + 500

    def test_rod_of_ages_timeless_state_adds_all_three_stats(self, ahri_data: dict):
        item = get_item_by_name("Rod of Ages")
        base = calculate_total_stats(ahri_data, 18, [item])
        stacked = calculate_total_stats(
            ahri_data,
            18,
            [item],
            item_options={"Rod of Ages": {"timeless_stacks": 10}},
        )
        assert stacked["ability_power"] == base["ability_power"] + 30
        assert stacked["health"] == base["health"] + 100
        assert stacked["max_mana"] == base["max_mana"] + 300

    def test_riftmaker_void_infusion_converts_bonus_health_to_ap(self, ahri_data: dict):
        item = get_item_by_name("Riftmaker")
        stats = calculate_total_stats(ahri_data, 18, [item])
        assert stats["ability_power"] == 77

    @pytest.mark.parametrize("item_name", ["Fimbulwinter", "Winter's Approach"])
    def test_awe_converts_bonus_mana_to_bonus_health(
        self, ahri_data: dict, item_name: str
    ) -> None:
        item = get_item_by_name(item_name)
        baseline = calculate_total_stats(ahri_data, 18, [item])
        item_stats = get_item_stats(item)
        expected = item_stats["health"] + baseline["bonus_mana"] * 0.15
        assert baseline["bonus_health"] == pytest.approx(expected)

    @pytest.mark.parametrize(
        ("champion_name", "stacks", "expected_crit"),
        [
            ("Ahri", 0, 0.0),
            ("Ahri", 50, 10.0),
            ("Ahri", 125, 25.0),
            ("Aatrox", 50, 20.0),
            ("Aatrox", 125, 25.0),
        ],
    )
    def test_yun_tal_permanent_crit_state_is_applied_by_melee_split(
        self, champion_name: str, stacks: int, expected_crit: float
    ) -> None:
        champion = get_champion(champion_name)
        item = get_item_by_name("Yun Tal Wildarrows")
        stats = calculate_total_stats(
            champion,
            18,
            [item],
            item_options={"Yun Tal Wildarrows": {"crit_stacks": stacks}},
        )
        assert stats["critical_strike_chance"] == pytest.approx(expected_crit)

    def test_yun_tal_crit_state_does_not_duplicate_flurry_attack_speed(
        self, ahri_data: dict
    ) -> None:
        item = get_item_by_name("Yun Tal Wildarrows")
        zero = calculate_total_stats(
            ahri_data,
            18,
            [item],
            item_options={"Yun Tal Wildarrows": {"crit_stacks": 0}},
        )
        capped = calculate_total_stats(
            ahri_data,
            18,
            [item],
            item_options={"Yun Tal Wildarrows": {"crit_stacks": 125}},
        )
        assert capped["critical_strike_chance"] > zero["critical_strike_chance"]
        assert capped["attack_speed"] == zero["attack_speed"]


class TestGrowthStat:
    """Tests for the LoL growth formula."""

    def test_level_1_returns_base(self) -> None:
        assert growth_stat(590, 104, 1) == 590.0

    def test_level_18_linear_growth(self) -> None:
        # At level 18, multiplier is exactly 1.0
        result = growth_stat(590, 104, 18)
        assert result == 590 + 104 * 17 * 1.0

    def test_level_6_health(self) -> None:
        result = growth_stat(590, 104, 6)
        assert round(result) == 1001

    def test_level_11_health(self) -> None:
        result = growth_stat(590, 104, 11)
        assert round(result) == 1503

    def test_invalid_level_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="Level must be between 1 and 20"):
            growth_stat(100, 10, 0)

    def test_invalid_level_21_raises(self) -> None:
        with pytest.raises(ValueError, match="Level must be between 1 and 20"):
            growth_stat(100, 10, 21)

    def test_zero_growth(self) -> None:
        assert growth_stat(100, 0, 18) == 100.0

    def test_zero_base(self) -> None:
        result = growth_stat(0, 10, 18)
        assert result == 10 * 17 * 1.0


class TestCalculateAttackSpeed:
    """Tests for attack speed calculation."""

    def test_zero_bonus(self) -> None:
        assert calculate_attack_speed(0.668, 0.625, 0.0) == 0.668

    def test_with_bonus(self) -> None:
        # base AS + ratio * bonus% = 0.668 + 0.625 * 0.20 = 0.793
        result = calculate_attack_speed(0.668, 0.625, 20.0)
        assert abs(result - 0.793) < 0.001

    def test_ratio_equals_base(self) -> None:
        # When ratio == base, equivalent to base * (1 + bonus%)
        result = calculate_attack_speed(0.625, 0.625, 50.0)
        assert abs(result - 0.625 * 1.50) < 0.001


class TestMovementSpeed:
    """Static item movement speed and the game's displayed soft caps."""

    def test_flat_boots_and_percent_item_stack(self, ahri_data: dict) -> None:
        boots = get_item_by_name("Boots of Swiftness")
        cosmic_drive = get_item_by_name("Cosmic Drive")

        stats = calculate_total_stats(ahri_data, 18, [boots, cosmic_drive])

        # Ahri 330 base + 55 flat, then Cosmic Drive's 4% = 400.4.
        assert stats["move_speed"] == pytest.approx(400.4)

    @pytest.mark.parametrize(
        ("raw", "displayed"),
        [(200, 210), (415, 415), (450, 443), (500, 480)],
    )
    def test_soft_caps(self, raw: float, displayed: float) -> None:
        assert apply_movement_speed_soft_caps(raw) == displayed

    def test_mejais_ten_stacks_add_ap_and_move_speed(self, ahri_data: dict) -> None:
        mejais = get_item_by_name("Mejai's Soulstealer")

        stats = calculate_total_stats(
            ahri_data,
            18,
            [mejais],
            item_options={"Mejai's Soulstealer": {"glory_stacks": 10}},
        )

        assert stats["ability_power"] == 70
        assert stats["move_speed"] == pytest.approx(363)

    def test_dark_seal_stacks_are_multiplied_by_rabadons(self, ahri_data: dict) -> None:
        dark_seal = get_item_by_name("Dark Seal")
        rabadons = get_item_by_name("Rabadon's Deathcap")

        stats = calculate_total_stats(
            ahri_data,
            18,
            [dark_seal, rabadons],
            item_options={"Dark Seal": {"glory_stacks": 10}},
        )

        # (15 base item AP + 40 Glory AP + 130 Deathcap AP) * 1.3.
        assert stats["ability_power"] == 240


class TestCalculateTotalStats:
    """Tests for total stats with items applied using Ahri data.

    Champion/item data fixtures come from tests/conftest.py.
    """

    def test_level_6_liandrys_hp(self, ahri_data: dict, liandrys: dict) -> None:
        stats = calculate_total_stats(ahri_data, 6, [liandrys])
        assert stats["health"] == 1301

    def test_level_6_liandrys_ad(self, ahri_data: dict, liandrys: dict) -> None:
        stats = calculate_total_stats(ahri_data, 6, [liandrys])
        assert stats["attack_damage"] == 65

    def test_level_6_liandrys_ap(self, ahri_data: dict, liandrys: dict) -> None:
        stats = calculate_total_stats(ahri_data, 6, [liandrys])
        assert stats["ability_power"] == 60

    def test_level_6_liandrys_armor(self, ahri_data: dict, liandrys: dict) -> None:
        stats = calculate_total_stats(ahri_data, 6, [liandrys])
        assert stats["armor"] == 38

    def test_level_6_liandrys_mr(self, ahri_data: dict, liandrys: dict) -> None:
        stats = calculate_total_stats(ahri_data, 6, [liandrys])
        assert stats["magic_resistance"] == 35

    def test_level_11_three_items(
        self, ahri_data: dict, liandrys: dict, malignance: dict, rylais: dict
    ) -> None:
        stats = calculate_total_stats(ahri_data, 11, [liandrys, malignance, rylais])
        assert stats["health"] == 2203
        assert stats["attack_damage"] == 79
        assert stats["ability_power"] == 215
        assert stats["armor"] == 58
        assert stats["magic_resistance"] == 41

    def test_rabadons_multiplies_ap(
        self,
        ahri_data: dict,
        liandrys: dict,
        malignance: dict,
        rylais: dict,
        rabadons: dict,
        sorc_shoes: dict,
        void_staff: dict,
    ) -> None:
        items = [liandrys, malignance, rylais, sorc_shoes, void_staff, rabadons]
        stats = calculate_total_stats(ahri_data, 18, items)
        assert stats["ability_power"] == 572

    def test_no_items_zero_ap(self, ahri_data: dict) -> None:
        stats = calculate_total_stats(ahri_data, 1, [])
        assert stats["ability_power"] == 0

    def test_archangels_awe_passive_ap(self, ahri_data: dict) -> None:
        """Archangel's Staff Awe: 1% bonus mana as AP.

        70 AP base + 1% of 600 bonus mana = 76 AP.
        """
        from src.calculator.data_fetcher import get_item_by_name

        archangels = get_item_by_name("Archangel's Staff")
        stats = calculate_total_stats(ahri_data, 18, [archangels])
        assert stats["ability_power"] == 76

    def test_seraphs_embrace_awe_passive_ap(self, ahri_data: dict) -> None:
        """Seraph's Embrace Awe: 2% bonus mana as AP.

        70 AP base + 2% of 1000 bonus mana = 90 AP.
        """
        from src.calculator.data_fetcher import get_item_by_name

        seraphs = get_item_by_name("Seraph's Embrace")
        stats = calculate_total_stats(ahri_data, 18, [seraphs])
        assert stats["ability_power"] == 90

    def test_bandlepipes_fanfare_attack_speed(self, ahri_data: dict) -> None:
        """Bandlepipes Fanfare: 20% bonus AS for ranged (Ahri is ranged)."""
        from src.calculator.data_fetcher import get_item_by_name

        bandlepipes = get_item_by_name("Bandlepipes")
        stats_with = calculate_total_stats(ahri_data, 18, [bandlepipes])
        stats_without = calculate_total_stats(ahri_data, 18, [])
        # Ahri is ranged, so 20% bonus AS from Fanfare
        base_as = ahri_data["stats"]["attackSpeed"]["flat"]
        expected_diff = base_as * 20.0 / 100.0
        assert (
            abs(
                stats_with["attack_speed"]
                - stats_without["attack_speed"]
                - expected_diff
            )
            < 0.01
        )

    def test_hexplate_overdrive_attack_speed(self, ahri_data: dict) -> None:
        """Overdrive is a melee/ranged split: Ahri is ranged, so 35%."""
        from src.calculator.data_fetcher import get_item_by_name

        hexplate = get_item_by_name("Experimental Hexplate")
        stats_with = calculate_total_stats(ahri_data, 18, [hexplate])
        stats_without = calculate_total_stats(ahri_data, 18, [])
        as_ratio = (
            ahri_data["stats"]
            .get("attackSpeedRatio", {})
            .get("flat", ahri_data["stats"]["attackSpeed"]["flat"])
        )
        # 35% ranged bonus AS from Overdrive + any AS from item stats
        hexplate_item_as = get_item_stats(hexplate).get("attack_speed_percent", 0.0)
        expected_bonus_as = as_ratio * (35.0 + hexplate_item_as) / 100.0
        actual_diff = stats_with["attack_speed"] - stats_without["attack_speed"]
        assert abs(actual_diff - expected_bonus_as) < 0.01

    def test_blackfire_torch_ap_passive(self, ahri_data: dict) -> None:
        """Blackfire Torch: 4% AP per burning target (assume 1 target).

        80 AP from item * 1.04 = 83.2 -> 83 rounded.
        """
        from src.calculator.data_fetcher import get_item_by_name

        blackfire = get_item_by_name("Blackfire Torch")
        stats = calculate_total_stats(ahri_data, 18, [blackfire])
        assert stats["ability_power"] == 83

    def test_overlord_bloodmail_tyranny_bonus_ad(self, ahri_data: dict) -> None:
        """Overlord's Bloodmail Tyranny: 2.5% bonus health as bonus AD.

        Bloodmail gives 500 HP. 2.5% of 500 = 12.5 bonus AD (rounds to 13).
        Total AD = base AD at 18 + 40 (item AD) + 12.5 (Tyranny).
        """
        from src.calculator.data_fetcher import get_item_by_name

        bloodmail = get_item_by_name("Overlord's Bloodmail")
        stats = calculate_total_stats(ahri_data, 18, [bloodmail])
        item_ad = bloodmail["stats"]["attackDamage"]["flat"]
        bonus_hp = bloodmail["stats"]["health"]["flat"]
        expected_bonus_ad = round(item_ad + 0.025 * bonus_hp)
        assert stats["bonus_attack_damage"] == expected_bonus_ad

    def test_dawncore_first_light_passive_ap(self, ahri_data: dict) -> None:
        """Dawncore First Light: 10 AP per 100% additional base mana regen.

        45 AP base + 10 AP from 100% mana regen passive = 55 AP.
        """
        from src.calculator.data_fetcher import get_item_by_name

        dawncore = get_item_by_name("Dawncore")
        stats = calculate_total_stats(ahri_data, 18, [dawncore])
        assert stats["ability_power"] == 55


class TestStatsUsesItemEffectsRegistry:
    """Verify stats.py reads values from ITEM_EFFECTS, not hardcoded."""

    def test_rabadons_reads_from_registry(
        self, ahri_data: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Patching Rabadon's ap_percent_increase changes the result."""
        from src.calculator.data_fetcher import get_item_by_name
        from src.calculator import item_effects

        rabadons = get_item_by_name("Rabadon's Deathcap")
        base_ap = rabadons["stats"]["abilityPower"]["flat"]

        # Default: 30% increase → round(120 * 1.30) = 156
        stats_default = calculate_total_stats(ahri_data, 18, [rabadons])

        # Patch to 50% increase
        patched = dict(item_effects.ITEM_EFFECTS.get("Rabadon's Deathcap", {}))
        patched["ap_percent_increase"] = 0.50
        monkeypatch.setitem(item_effects.ITEM_EFFECTS, "Rabadon's Deathcap", patched)
        stats_patched = calculate_total_stats(ahri_data, 18, [rabadons])

        assert stats_patched["ability_power"] == round(base_ap * 1.50)
        assert stats_patched["ability_power"] != stats_default["ability_power"]

    def test_seraphs_reads_from_registry(
        self, ahri_data: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Patching Seraph's bonus_mana_to_ap_ratio changes the result."""
        from src.calculator.data_fetcher import get_item_by_name
        from src.calculator import item_effects

        seraphs = get_item_by_name("Seraph's Embrace")
        base_ap = seraphs["stats"]["abilityPower"]["flat"]
        bonus_mana = seraphs["stats"]["mana"]["flat"]

        # Patch to 5% instead of 2%
        patched = dict(item_effects.ITEM_EFFECTS.get("Seraph's Embrace", {}))
        patched["bonus_mana_to_ap_ratio"] = 0.05
        monkeypatch.setitem(item_effects.ITEM_EFFECTS, "Seraph's Embrace", patched)
        stats = calculate_total_stats(ahri_data, 18, [seraphs])

        expected_ap = round(base_ap + 0.05 * bonus_mana)
        assert stats["ability_power"] == expected_ap

    def test_muramana_reads_from_registry(
        self, ahri_data: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Patching Muramana max_mana_to_ad_ratio changes the result."""
        from src.calculator.data_fetcher import get_item_by_name
        from src.calculator import item_effects

        muramana = get_item_by_name("Muramana")

        stats_default = calculate_total_stats(ahri_data, 18, [muramana])

        # Patch to 5% instead of 2%
        patched = dict(item_effects.ITEM_EFFECTS.get("Muramana", {}))
        patched["max_mana_to_ad_ratio"] = 0.05
        monkeypatch.setitem(item_effects.ITEM_EFFECTS, "Muramana", patched)
        stats_patched = calculate_total_stats(ahri_data, 18, [muramana])

        assert stats_patched["attack_damage"] > stats_default["attack_damage"]


class TestNewItemStats:
    """Tests for the 6 newly implemented items."""

    # ── Staff of Flowing Water ──

    def test_flowing_water_rapids_ap(self, ahri_data: dict) -> None:
        """Staff of Flowing Water Rapids: 35 base AP + 40 bonus AP = 75.

        JSON (16.13.1): Rapids grants 40 AP (down from 45).
        """
        from src.calculator.data_fetcher import get_item_by_name

        staff = get_item_by_name("Staff of Flowing Water")
        stats = calculate_total_stats(ahri_data, 18, [staff])
        assert stats["ability_power"] == 75

    def test_flowing_water_reads_from_registry(
        self,
        ahri_data: dict,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Patching rapids_bonus_ap changes the AP result."""
        from src.calculator.data_fetcher import get_item_by_name
        from src.calculator import item_effects

        staff = get_item_by_name("Staff of Flowing Water")
        patched = dict(item_effects.ITEM_EFFECTS.get("Staff of Flowing Water", {}))
        patched["rapids_bonus_ap"] = 100.0
        monkeypatch.setitem(
            item_effects.ITEM_EFFECTS, "Staff of Flowing Water", patched
        )
        stats = calculate_total_stats(ahri_data, 18, [staff])
        assert stats["ability_power"] == 135  # 35 base + 100 bonus

    # ── Sterak's Gage ──

    def test_steraks_gage_bonus_ad(self, ahri_data: dict) -> None:
        """Sterak's Gage: 45% base AD as bonus AD.

        Ahri base AD at 18 = 104. Bonus = 104 * 0.45 = 46.8.
        Total AD = round(104 + 46.8) = 151.
        """
        from src.calculator.data_fetcher import get_item_by_name

        steraks = get_item_by_name("Sterak's Gage")
        stats = calculate_total_stats(ahri_data, 18, [steraks])
        assert stats["attack_damage"] == 151

    def test_steraks_reads_from_registry(
        self,
        ahri_data: dict,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Patching base_ad_to_bonus_ad_ratio changes the AD result."""
        from src.calculator.data_fetcher import get_item_by_name
        from src.calculator import item_effects

        steraks = get_item_by_name("Sterak's Gage")
        default_stats = calculate_total_stats(ahri_data, 18, [steraks])
        patched = dict(item_effects.ITEM_EFFECTS.get("Sterak's Gage", {}))
        patched["base_ad_to_bonus_ad_ratio"] = 1.00
        monkeypatch.setitem(item_effects.ITEM_EFFECTS, "Sterak's Gage", patched)
        patched_stats = calculate_total_stats(ahri_data, 18, [steraks])
        assert patched_stats["attack_damage"] > default_stats["attack_damage"]

    # ── Spear of Shojin ──

    def test_shojin_basic_ability_haste(self, ahri_data: dict) -> None:
        """Spear of Shojin Dragonforce: 25 basic ability haste."""
        from src.calculator.data_fetcher import get_item_by_name

        shojin = get_item_by_name("Spear of Shojin")
        stats = calculate_total_stats(ahri_data, 18, [shojin])
        assert stats["basic_ability_haste"] == 25.0

    def test_shojin_no_item_zero_basic_haste(self, ahri_data: dict) -> None:
        """Without Spear of Shojin, basic_ability_haste is 0."""
        stats = calculate_total_stats(ahri_data, 18, [])
        assert stats["basic_ability_haste"] == 0.0

    # ── Stormrazor ──

    def test_stormrazor_parsed_values(self) -> None:
        """Parser extracts base=100 and damage_type=magic."""
        from src.calculator.passive_parser import parse_item_effect
        from src.calculator.data_fetcher import fetch_item_data

        items = fetch_item_data()
        parsed = parse_item_effect("Stormrazor", items)
        assert parsed["base"] == 100.0
        assert parsed["damage_type"] == "magic"

    # ── Statikk Shiv ──

    def test_statikk_shiv_parsed_values(self) -> None:
        """Parser extracts the reworked Electrospark: ONE empowered attack
        dealing 60 magic damage, chain-lightning to 4-8 targets by level."""
        from src.calculator.passive_parser import parse_item_effect
        from src.calculator.data_fetcher import fetch_item_data

        items = fetch_item_data()
        parsed = parse_item_effect("Statikk Shiv", items)
        assert parsed["base"] == 60.0
        assert parsed["empowered_auto_count"] == 1
        assert parsed["chain_targets_min"] == 4
        assert parsed["chain_targets_max"] == 8
        assert parsed["damage_type"] == "magic"

    # ── Titanic Hydra ──

    def test_titanic_hydra_active_parsed(self) -> None:
        """Parser extracts active_max_hp_ratio_melee=0.04, ranged=0.02."""
        from src.calculator.passive_parser import parse_item_effect
        from src.calculator.data_fetcher import fetch_item_data

        items = fetch_item_data()
        parsed = parse_item_effect("Titanic Hydra", items)
        assert parsed["active_max_hp_ratio_melee"] == 0.04
        assert parsed["active_max_hp_ratio_ranged"] == 0.02
        assert parsed["secondary_max_hp_ratio_melee"] == 0.03
        assert parsed["secondary_max_hp_ratio_ranged"] == 0.015
        assert parsed["active_secondary_max_hp_ratio_melee"] == 0.09
        assert parsed["active_secondary_max_hp_ratio_ranged"] == 0.045

    def test_ravenous_hydra_cleave_secondary_ad_parsed(self) -> None:
        from src.calculator.passive_parser import parse_item_effect
        from src.calculator.data_fetcher import fetch_item_data

        parsed = parse_item_effect("Ravenous Hydra", fetch_item_data())
        assert parsed["secondary_ad_ratio_melee"] == 0.40
        assert parsed["secondary_ad_ratio_ranged"] == 0.20

    # ── Yun Tal Wildarrows ──

    def test_yun_tal_bonus_attack_speed(self, ahri_data: dict) -> None:
        """Yun Tal Wildarrows Flurry adds 30% bonus AS."""
        base_stats = calculate_total_stats(ahri_data, 18, [])
        yt_item = {"name": "Yun Tal Wildarrows", "stats": {}}
        stats_with = calculate_total_stats(ahri_data, 18, [yt_item])
        # AS should be higher with Yun Tal Flurry
        assert stats_with["attack_speed"] > base_stats["attack_speed"]

    def test_bloodmail_starting_missing_health_adds_retribution_ad(
        self, ahri_data: dict
    ) -> None:
        item = get_item_by_name("Overlord's Bloodmail")
        full = calculate_total_stats(ahri_data, 18, [item])
        hurt = calculate_total_stats(
            ahri_data,
            18,
            [item],
            item_options={"Overlord's Bloodmail": {"missing_health_percent": 50}},
        )
        assert hurt["attack_damage"] > full["attack_damage"]
        assert hurt["bonus_attack_damage"] > full["bonus_attack_damage"]

    def test_yun_tal_reads_from_registry(self, ahri_data: dict, monkeypatch) -> None:
        """Yun Tal AS bonus reads from ITEM_EFFECTS, not hardcoded."""
        from src.calculator import item_effects

        patched = dict(item_effects.ITEM_EFFECTS.get("Yun Tal Wildarrows", {}))
        patched["bonus_attack_speed_percent"] = 60.0  # 60% instead of 30%
        monkeypatch.setitem(item_effects.ITEM_EFFECTS, "Yun Tal Wildarrows", patched)

        yt_item = {"name": "Yun Tal Wildarrows", "stats": {}}
        stats_60 = calculate_total_stats(ahri_data, 18, [yt_item])

        patched["bonus_attack_speed_percent"] = 30.0
        monkeypatch.setitem(item_effects.ITEM_EFFECTS, "Yun Tal Wildarrows", patched)
        stats_30 = calculate_total_stats(ahri_data, 18, [yt_item])

        assert stats_60["attack_speed"] > stats_30["attack_speed"]

    # ── Terminus ──

    def test_terminus_adds_armor_and_mr(self, ahri_data: dict) -> None:
        """Terminus light hits add bonus armor and MR at max stacks."""
        base_stats = calculate_total_stats(ahri_data, 18, [])
        terminus_item = {"name": "Terminus", "stats": {}}
        stats_with = calculate_total_stats(ahri_data, 18, [terminus_item])
        # At level 18, light_resist_max=8, 3 stacks = 24 bonus armor + MR
        assert stats_with["armor"] == base_stats["armor"] + 24
        assert stats_with["magic_resistance"] == base_stats["magic_resistance"] + 24

    def test_terminus_adds_armor_pen(self, ahri_data: dict) -> None:
        """Terminus dark hits add 30% armor penetration at max stacks."""
        base_stats = calculate_total_stats(ahri_data, 18, [])
        terminus_item = {"name": "Terminus", "stats": {}}
        stats_with = calculate_total_stats(ahri_data, 18, [terminus_item])
        expected = base_stats["armor_penetration_percent"] + 30.0
        assert abs(stats_with["armor_penetration_percent"] - expected) < 0.01

    def test_terminus_adds_magic_pen(self, ahri_data: dict) -> None:
        """Terminus dark hits add 30% magic penetration at max stacks."""
        base_stats = calculate_total_stats(ahri_data, 18, [])
        terminus_item = {"name": "Terminus", "stats": {}}
        stats_with = calculate_total_stats(ahri_data, 18, [terminus_item])
        expected = base_stats["magic_penetration_percent"] + 30.0
        assert abs(stats_with["magic_penetration_percent"] - expected) < 0.01

    def test_terminus_parsed_light_resist(self) -> None:
        """Parser extracts light_resist_min and light_resist_max."""
        from src.calculator.passive_parser import parse_item_effect
        from src.calculator.data_fetcher import fetch_item_data

        items = fetch_item_data()
        parsed = parse_item_effect("Terminus", items)
        assert parsed is not None
        assert parsed["light_resist_min"] == 6.0
        assert parsed["light_resist_max"] == 8.0

    def test_yun_tal_parsed_values(self) -> None:
        """Parser extracts bonus_attack_speed_percent, duration, cooldown."""
        from src.calculator.passive_parser import parse_item_effect
        from src.calculator.data_fetcher import fetch_item_data

        items = fetch_item_data()
        parsed = parse_item_effect("Yun Tal Wildarrows", items)
        assert parsed is not None
        assert parsed["bonus_attack_speed_percent"] == 30.0
        assert parsed["duration"] == 6.0
        assert parsed["cooldown"] == 30.0
        assert parsed["attack_refund_base"] == 1.0
        assert parsed["attack_refund_crit"] == 2.0


class TestHealthComponents:
    """Base, bonus, and total health are three separate first-class stats.

    Base health comes from base stats + level growth, bonus health from
    items/runes, and ``health`` is their total. Scalings differ per
    ability ("% base health" vs "% bonus health" vs "% maximum health"),
    so each must be readable on its own and the three must stay
    consistent: ``health == base_health + bonus_health`` always.
    """

    def test_all_three_health_stats_are_emitted(self, ahri_data: dict) -> None:
        stats = calculate_total_stats(ahri_data, 18, [])
        for key in ("health", "base_health", "bonus_health"):
            assert key in stats, f"{key} missing from stats output"

    def test_no_items_means_zero_bonus_health(self, ahri_data: dict) -> None:
        stats = calculate_total_stats(ahri_data, 18, [])
        assert stats["bonus_health"] == 0
        assert stats["base_health"] == stats["health"]

    def test_base_health_matches_growth_formula(self, ahri_data: dict) -> None:
        """Base health is the champion's own base + growth, sans items."""
        base = get_champion_base_stats(ahri_data, 18)
        stats = calculate_total_stats(ahri_data, 18, [])
        assert stats["base_health"] == round(base["health"])

    def test_items_raise_bonus_health_only(self, ahri_data: dict) -> None:
        """An item's health lands in bonus, never in base."""
        naked = calculate_total_stats(ahri_data, 18, [])
        warmogs = get_item_by_name("Warmog's Armor")
        built = calculate_total_stats(ahri_data, 18, [warmogs])

        assert built["base_health"] == naked["base_health"]
        assert built["bonus_health"] > 0
        assert built["health"] > naked["health"]

    def test_warmogs_vitality_multiplies_all_item_health(self, ahri_data: dict) -> None:
        items = [
            get_item_by_name("Warmog's Armor"),
            get_item_by_name("Ruby Crystal"),
        ]
        raw_item_health = sum(get_item_stats(item)["health"] for item in items)

        stats = calculate_total_stats(ahri_data, 18, items)

        assert stats["bonus_health"] == round(raw_item_health * 1.12)
        assert stats["health"] == stats["base_health"] + stats["bonus_health"]

    def test_bloodmail_reads_warmogs_effective_bonus_health(
        self, ahri_data: dict
    ) -> None:
        items = [
            get_item_by_name("Warmog's Armor"),
            get_item_by_name("Overlord's Bloodmail"),
        ]
        raw_item_health = sum(get_item_stats(item)["health"] for item in items)
        raw_item_ad = sum(get_item_stats(item)["attack_damage"] for item in items)

        stats = calculate_total_stats(ahri_data, 18, items)

        assert stats["bonus_attack_damage"] == round(
            raw_item_ad + raw_item_health * 1.12 * 0.025
        )

    @pytest.mark.parametrize("level", [1, 6, 11, 18, 20])
    def test_invariant_holds_across_levels(self, ahri_data: dict, level: int) -> None:
        stats = calculate_total_stats(ahri_data, level, [])
        assert stats["health"] == stats["base_health"] + stats["bonus_health"]

    @pytest.mark.parametrize(
        "item_names",
        [
            ["Warmog's Armor"],
            ["Heartsteel"],
            ["Warmog's Armor", "Heartsteel", "Sunfire Aegis"],
        ],
    )
    def test_invariant_holds_with_items(
        self, ahri_data: dict, item_names: list[str]
    ) -> None:
        items = [get_item_by_name(name) for name in item_names]
        stats = calculate_total_stats(ahri_data, 18, items)
        assert stats["health"] == stats["base_health"] + stats["bonus_health"]


class TestMidRoleQuestStats:
    """V26.11 mid quest grants 8% bonus AD and 8% total AP."""

    def test_mid_quest_ap_stacks_additively_with_rabadon(self, ahri_data: dict) -> None:
        rabadon = get_item_by_name("Rabadon's Deathcap")
        normal = calculate_total_stats(ahri_data, 18, [rabadon])
        quest = calculate_total_stats(
            ahri_data,
            18,
            [rabadon],
            role="mid",
            role_quest_complete=True,
        )

        assert normal["ability_power"] == round(130 * 1.30)
        assert quest["ability_power"] == round(130 * 1.38)

    def test_mid_quest_multiplies_only_bonus_ad(self, ahri_data: dict) -> None:
        sword = get_item_by_name("B. F. Sword")
        normal = calculate_total_stats(ahri_data, 18, [sword])
        quest = calculate_total_stats(
            ahri_data,
            18,
            [sword],
            role="mid",
            role_quest_complete=True,
        )

        assert quest["bonus_attack_damage"] == round(
            normal["bonus_attack_damage"] * 1.08
        )
        assert quest["base_attack_damage"] == normal["base_attack_damage"]


def test_item_sustain_and_economy_stats_are_exposed_from_cached_source() -> None:
    blade = get_item_by_name("Blade of the Ruined King")
    item_stats = get_item_stats(blade)
    assert item_stats["lifesteal_percent"] == pytest.approx(10.0)
    assert get_item_stats(get_item_by_name("Ardent Censer"))[
        "heal_and_shield_power_percent"
    ] == pytest.approx(10.0)

    totals = calculate_total_stats(get_champion("Vayne"), 11, [blade])
    assert totals["lifesteal_percent"] == pytest.approx(10.0)
    assert totals["omnivamp_percent"] == pytest.approx(0.0)
    assert "health_regen_percent" in totals
    assert "tenacity_percent" in totals
    assert "gold_per_10" in totals
