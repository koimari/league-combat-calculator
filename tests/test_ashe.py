"""Tests for Ashe champion module."""

import pytest

from src.calculator.champions import ashe
from src.calculator.damage import FightConfig, calculate_fight_damage
from tests import cc_review


class TestPassiveFrostShot:
    """Ashe passive: crit chance converts to bonus damage on every auto."""

    def test_passive_present(self, ashe_data, parse_at) -> None:
        _, abilities = parse_at(ashe_data, 3)
        assert "passive" in abilities
        assert abilities["passive"]["total_raw"] == 0.0

    def test_passive_has_auto_override_without_q(self, ashe_data, parse_at) -> None:
        """When Q is off, passive provides the auto override with ratio 1.0."""
        _, abilities = parse_at(ashe_data, 3, champion_options={"q_active": False})
        override = abilities["passive"].get("auto_attack_override")
        assert override is not None
        assert override["crit_as_bonus"] is True
        assert override["ad_ratio"] == pytest.approx(1.0)

    def test_auto_damage_with_crit_chance(self, ashe_data, parse_at) -> None:
        """Auto with 200 AD and 50% crit: 200 * (1 + 0.5) = 300."""
        stats, abilities = parse_at(
            ashe_data,
            3,
            champion_options={"q_active": False},
        )
        # Override stats for verification
        stats["attack_damage"] = 200.0
        stats["attack_speed"] = 1.0
        stats["critical_strike_chance"] = 50.0
        result = calculate_fight_damage(
            stats,
            abilities,
            [],
            FightConfig(
                target_health=2000.0,
                target_armor=0.0,
                target_magic_resistance=0.0,
                fight_duration_seconds=1.0,
                auto_attack_uptime=1.0,
                auto_attacks_only=True,
            ),
        )
        auto = result["breakdown"]["auto_attacks"]
        # With 0 armor, every auto should do 300 damage
        assert auto["damage_per_hit"] == pytest.approx(300.0, rel=0.01)

    def test_auto_damage_with_crit_and_ie(self, ashe_data, parse_at) -> None:
        """Auto with 200 AD, 50% crit, and IE (+30% crit damage):
        bonus_crit_ratio = (2.30 - 1.0) = 1.30
        200 * (1.0 + 0.50 * 1.30) = 200 * 1.65 = 330."""
        stats, abilities = parse_at(
            ashe_data,
            3,
            champion_options={"q_active": False},
        )
        stats["attack_damage"] = 200.0
        stats["attack_speed"] = 1.0
        stats["critical_strike_chance"] = 50.0
        # Simulate having Infinity Edge via items
        ie_item = {"name": "Infinity Edge"}
        result = calculate_fight_damage(
            stats,
            abilities,
            [ie_item],
            FightConfig(
                target_health=2000.0,
                target_armor=0.0,
                target_magic_resistance=0.0,
                fight_duration_seconds=1.0,
                auto_attack_uptime=1.0,
                auto_attacks_only=True,
            ),
        )
        auto = result["breakdown"]["auto_attacks"]
        assert auto["damage_per_hit"] == pytest.approx(330.0, rel=0.01)

    def test_auto_damage_zero_crit(self, ashe_data, parse_at) -> None:
        """With 0% crit, auto damage is normal (1.0 * AD)."""
        stats, abilities = parse_at(
            ashe_data,
            3,
            champion_options={"q_active": False},
        )
        stats["attack_damage"] = 200.0
        stats["attack_speed"] = 1.0
        stats["critical_strike_chance"] = 0.0
        result = calculate_fight_damage(
            stats,
            abilities,
            [],
            FightConfig(
                target_health=2000.0,
                target_armor=0.0,
                target_magic_resistance=0.0,
                fight_duration_seconds=1.0,
                auto_attack_uptime=1.0,
                auto_attacks_only=True,
            ),
        )
        auto = result["breakdown"]["auto_attacks"]
        assert auto["damage_per_hit"] == pytest.approx(200.0, rel=0.01)


class TestQRangersFocus:
    """Q: stat buff + empowered auto modifier."""

    def test_q_is_physical(self, ashe_data, parse_at) -> None:
        _, abilities = parse_at(ashe_data, 3)
        assert abilities["Q"]["damage_type"] == "physical"

    def test_q_deals_no_direct_damage(self, ashe_data, parse_at) -> None:
        _, abilities = parse_at(ashe_data, 3)
        assert abilities["Q"]["total_raw"] == 0.0

    def test_q_has_cooldown_field(self, ashe_data, parse_at) -> None:
        """Q cooldown is 0 (stack-activated, no cooldown in JSON)."""
        _, abilities = parse_at(ashe_data, 3)
        assert "cooldown" in abilities["Q"]

    def test_q_has_stat_buff(self, ashe_data, parse_at) -> None:
        _, abilities = parse_at(ashe_data, 3)
        assert "stat_buff" in abilities["Q"]
        assert abilities["Q"]["stat_buff"]["bonus_attack_speed"] > 0

    def test_q_has_auto_override(self, ashe_data, parse_at) -> None:
        _, abilities = parse_at(ashe_data, 3)
        override = abilities["Q"].get("auto_attack_override")
        assert override is not None
        assert override["crit_as_bonus"] is True

    def test_q_flurry_ratio_rank1(self, ashe_data, parse_at) -> None:
        """Q rank 1 flurry = 110% AD -> ratio 1.10."""
        _, abilities = parse_at(
            ashe_data, 1, ability_ranks={"Q": 1, "W": 0, "E": 0, "R": 0}
        )
        override = abilities["Q"]["auto_attack_override"]
        assert override["ad_ratio"] == pytest.approx(1.10)

    def test_q_flurry_ratio_rank5(self, ashe_data, parse_at) -> None:
        """Q rank 5 flurry = 130% AD -> ratio 1.30.

        JSON (16.13.1): "Total Damage Per Flurry" is 110/115/120/125/130
        (+5 per rank, not +10).
        """
        _, abilities = parse_at(
            ashe_data, 9, ability_ranks={"Q": 5, "W": 1, "E": 0, "R": 0}
        )
        override = abilities["Q"]["auto_attack_override"]
        assert override["ad_ratio"] == pytest.approx(1.30)

    def test_q_bonus_as_rank1(self, ashe_data, parse_at) -> None:
        """Q rank 1 grants 20% bonus AS."""
        _, abilities = parse_at(
            ashe_data, 1, ability_ranks={"Q": 1, "W": 0, "E": 0, "R": 0}
        )
        assert abilities["Q"]["stat_buff"]["bonus_attack_speed"] == pytest.approx(20.0)

    def test_q_bonus_as_rank5(self, ashe_data, parse_at) -> None:
        """Q rank 5 grants 60% bonus AS."""
        _, abilities = parse_at(
            ashe_data, 9, ability_ranks={"Q": 5, "W": 1, "E": 0, "R": 0}
        )
        assert abilities["Q"]["stat_buff"]["bonus_attack_speed"] == pytest.approx(60.0)

    def test_q_active_auto_damage(self, ashe_data, parse_at) -> None:
        """Q rank 5 auto with 200 AD, 50% crit: 200 * 1.30 * (1 + 0.50) = 390.
        JSON (16.13.1): flurry rank 5 = 130% AD (see test_q_flurry_ratio_rank5).
        Passive is multiplicative with Q flurry (each arrow applies Frost Shot)."""
        stats, abilities = parse_at(
            ashe_data,
            9,
            ability_ranks={"Q": 5, "W": 1, "E": 0, "R": 0},
            champion_options={"q_active": True},
        )
        stats["attack_damage"] = 200.0
        stats["attack_speed"] = 1.0
        stats["critical_strike_chance"] = 50.0
        result = calculate_fight_damage(
            stats,
            abilities,
            [],
            FightConfig(
                target_health=2000.0,
                target_armor=0.0,
                target_magic_resistance=0.0,
                fight_duration_seconds=1.0,
                auto_attack_uptime=1.0,
                auto_attacks_only=True,
            ),
        )
        auto = result["breakdown"]["auto_attacks"]
        assert auto["damage_per_hit"] == pytest.approx(390.0, rel=0.01)

    def test_q_inactive_no_override_from_q(self, ashe_data, parse_at) -> None:
        """When Q is off, Q entry absent, passive provides override."""
        _, abilities = parse_at(ashe_data, 3, champion_options={"q_active": False})
        assert "Q" not in abilities
        # Passive provides the auto override
        assert "auto_attack_override" in abilities["passive"]


class TestWVolley:
    """W: single-target physical damage."""

    def test_w_is_physical(self, ashe_data, parse_at) -> None:
        _, abilities = parse_at(ashe_data, 3)
        assert abilities["W"]["damage_type"] == "physical"

    def test_w_has_cooldown(self, ashe_data, parse_at) -> None:
        _, abilities = parse_at(ashe_data, 3)
        assert abilities["W"]["cooldown"] > 0

    def test_w_damage_rank5(self, ashe_data, parse_at) -> None:
        """W rank 5 with 200 total AD (100 base + 100 bonus):
        200 + 100% * 100 bonus AD = 300 physical damage."""
        stats, abilities = parse_at(
            ashe_data,
            9,
            ability_ranks={"Q": 1, "W": 5, "E": 0, "R": 0},
            champion_options={"q_active": False},
        )
        stats["attack_damage"] = 200.0
        stats["bonus_attack_damage"] = 100.0
        # Re-parse with correct stats
        from src.calculator.champions import parse_abilities as dispatch

        abilities = dispatch(
            "Ashe",
            ashe_data,
            9,
            0.0,
            ability_ranks={"Q": 1, "W": 5, "E": 0, "R": 0},
            champion_stats=stats,
            champion_options={"q_active": False},
        )
        assert abilities["W"]["total_raw"] == pytest.approx(300.0, rel=0.01)

    def test_w_has_positive_damage(self, ashe_data, parse_at) -> None:
        _, abilities = parse_at(ashe_data, 3)
        assert abilities["W"]["total_raw"] > 0


class TestEHawkshot:
    """E (Hawkshot) carries no enemy-damage attribute (damageType: None,
    no leveling row on either effect) — it emits a sourced zero-damage row
    rather than staying silently absent."""

    def test_e_present_zero_damage(self, ashe_data, parse_at) -> None:
        _, abilities = parse_at(ashe_data, 9)
        entry = abilities["E"]
        assert entry["name"] == "Hawkshot"
        assert entry["total_raw"] == 0.0
        assert entry["parts"] == ()
        assert entry["detail"]


class TestREnchantedCrystalArrow:
    """R: magic damage."""

    def test_r_is_magic(self, ashe_data, parse_at) -> None:
        _, abilities = parse_at(ashe_data, 9)
        assert abilities["R"]["damage_type"] == "magic"

    def test_r_has_cooldown(self, ashe_data, parse_at) -> None:
        _, abilities = parse_at(ashe_data, 9)
        assert abilities["R"]["cooldown"] > 0

    def test_r_damage_rank3_zero_ap(self, ashe_data, parse_at) -> None:
        """R rank 3 with 0 AP: 600 magic damage."""
        _, abilities = parse_at(
            ashe_data,
            16,
            ability_ranks={"Q": 5, "W": 5, "E": 1, "R": 3},
        )
        assert abilities["R"]["total_raw"] == pytest.approx(600.0, rel=0.01)

    def test_r_has_positive_damage(self, ashe_data, parse_at) -> None:
        _, abilities = parse_at(ashe_data, 9)
        assert abilities["R"]["total_raw"] > 0

    def test_r_scales_with_ap(self, ashe_data, parse_at) -> None:
        """R should deal more damage with AP."""
        _, abilities_no_ap = parse_at(ashe_data, 9, ap=0.0)
        _, abilities_with_ap = parse_at(ashe_data, 9, ap=100.0)
        assert abilities_with_ap["R"]["total_raw"] > abilities_no_ap["R"]["total_raw"]


class TestFightEngineIntegration:
    """Verify stat buffs and overrides work through the fight engine."""

    def test_q_stat_buff_applied(self, ashe_data, parse_at) -> None:
        """Q bonus AS should appear in stat buff dict."""
        _, abilities = parse_at(ashe_data, 3)
        assert abilities["Q"]["stat_buff"]["bonus_attack_speed"] > 0

    def test_r_damage_in_fight(self, ashe_data, parse_at) -> None:
        """R deals magic damage through the fight engine."""
        stats, abilities = parse_at(ashe_data, 9)
        result = calculate_fight_damage(
            stats,
            abilities,
            [],
            FightConfig(
                target_health=2000.0,
                target_armor=50.0,
                target_magic_resistance=50.0,
                fight_duration_seconds=5.0,
                auto_attack_uptime=0.5,
            ),
        )
        assert result["total_damage"] > 0
        assert "R" in result["breakdown"]


class TestReviewedCrowdControl:
    """Ashe's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Ashe")
        assert ashe.MODULE_CC == {
            "W": "slow",
            "R": "stun",
            "E": "none",
            "P": "slow",
            "Q": "none",
        }
        assert "applying critical slow to enemy champions hit" in " ".join(
            cc_review.slot_text(data, "W").split()
        )
        assert "stunning them for" in " ".join(cc_review.slot_text(data, "R").split())

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Ashe") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Ashe")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


class TestModuleCoverage:
    def test_all_five_slots_covered(self) -> None:
        from src.calculator.champions.ashe import MODULE_COVERAGE

        assert MODULE_COVERAGE == {
            "P": "modeled",
            "Q": "modeled",
            "W": "modeled",
            "E": "no_damage",
            "R": "modeled",
        }
