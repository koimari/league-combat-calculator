"""Tests for Aatrox champion ability parsing and damage calculation."""

from src.calculator.stats import calculate_total_stats
from src.calculator.champions.slotlib import extract_named, extract_value
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.champions import aatrox
from tests import cc_review


class TestQThreeCasts:
    """Tests for Q (The Darkin Blade) three-cast mechanic."""

    def test_q_returns_physical_damage(self, aatrox_data, parse_at) -> None:
        _, abilities = parse_at(
            aatrox_data,
            9,
            champion_options={"sweetspot": False},
        )
        assert "Q" in abilities
        assert abilities["Q"]["damage_type"] == "physical"

    def test_q_sweetspot_deals_more_damage(self, aatrox_data, parse_at) -> None:
        _, normal = parse_at(
            aatrox_data,
            9,
            champion_options={"sweetspot": False},
        )
        _, sweetspot = parse_at(
            aatrox_data,
            9,
            champion_options={"sweetspot": True},
        )
        assert sweetspot["Q"]["total_raw"] > normal["Q"]["total_raw"]

    def test_q_sweetspot_is_default(self, aatrox_data, parse_at) -> None:
        _, default = parse_at(aatrox_data, 9)
        _, sweetspot = parse_at(
            aatrox_data,
            9,
            champion_options={"sweetspot": True},
        )
        assert abs(default["Q"]["total_raw"] - sweetspot["Q"]["total_raw"]) < 0.1

    def test_q_has_cooldown(self, aatrox_data, parse_at) -> None:
        _, abilities = parse_at(aatrox_data, 9)
        assert abilities["Q"]["cooldown"] > 0

    def test_q_rank1_normal_damage_matches_json(self, aatrox_data, parse_at) -> None:
        """Verify Q rank 1 normal damage = sum of 3 casts at base AD."""
        stats, abilities = parse_at(
            aatrox_data,
            1,
            champion_options={"sweetspot": False},
        )
        q = abilities["Q"]
        ad = stats["attack_damage"]
        # First Cast: 10 + 60% AD
        # Second Cast: 12.5 + 75% AD
        # Third Cast: 15 + 90% AD
        expected = (10 + 0.60 * ad) + (12.5 + 0.75 * ad) + (15 + 0.90 * ad)
        assert abs(q["total_raw"] - expected) < 0.5

    def test_q_three_casts_sum(self, aatrox_data, parse_at) -> None:
        """Q total damage equals sum of all three individual casts.

        Uses level 5 (R not yet ranked) so no R buff distorts the
        comparison between manual extraction and parse_abilities.
        """
        q_ability = aatrox_data["abilities"]["Q"][0]
        stats = calculate_total_stats(aatrox_data, 5, [])
        rank = 3  # Q rank 3 at level 5
        stats_ctx = dict(stats)

        first = extract_named(q_ability, "First Cast Damage", rank, stats_ctx)
        second = extract_named(q_ability, "Second Cast Damage", rank, stats_ctx)
        third = extract_named(q_ability, "Third Cast Damage", rank, stats_ctx)

        _, abilities = parse_at(
            aatrox_data,
            5,
            champion_options={"sweetspot": False},
        )
        assert abs(abilities["Q"]["total_raw"] - (first + second + third)) < 0.5


class TestPassiveOnHit:
    """Tests for P (Deathbringer Stance) on-hit parsing."""

    def test_passive_returns_on_hit(self, aatrox_data, parse_at) -> None:
        _, abilities = parse_at(
            aatrox_data,
            9,
            target_stats={"target_max_health": 2000.0},
        )
        assert "passive" in abilities
        assert "on_hit" in abilities["passive"]

    def test_passive_damage_type_is_magic(self, aatrox_data, parse_at) -> None:
        _, abilities = parse_at(
            aatrox_data,
            9,
            target_stats={"target_max_health": 2000.0},
        )
        assert abilities["passive"]["on_hit"]["damage_type"] == "magic"

    def test_passive_scales_with_level(self, aatrox_data, parse_at) -> None:
        target = {"target_max_health": 2000.0}
        _, low = parse_at(aatrox_data, 1, target_stats=target)
        _, high = parse_at(aatrox_data, 18, target_stats=target)
        assert high["passive"]["on_hit"]["damage_per_hit"] > (
            low["passive"]["on_hit"]["damage_per_hit"]
        )

    def test_passive_level1_percent(self, aatrox_data, parse_at) -> None:
        """Level 1 passive should deal ~4% of target max health."""
        _, abilities = parse_at(
            aatrox_data,
            1,
            target_stats={"target_max_health": 2000.0},
        )
        damage = abilities["passive"]["on_hit"]["damage_per_hit"]
        # 4% of 2000 = 80
        assert abs(damage - 80.0) < 1.0

    def test_passive_level18_percent(self, aatrox_data, parse_at) -> None:
        """Level 18 passive should deal 10% of target max health."""
        _, abilities = parse_at(
            aatrox_data,
            18,
            target_stats={"target_max_health": 2000.0},
        )
        damage = abilities["passive"]["on_hit"]["damage_per_hit"]
        assert abs(damage - 200.0) < 1.0

    def test_passive_level20_percent(self, aatrox_data, parse_at) -> None:
        """Level 20 passive should deal ~10.71% of target max health."""
        _, abilities = parse_at(
            aatrox_data,
            20,
            target_stats={"target_max_health": 2000.0},
        )
        damage = abilities["passive"]["on_hit"]["damage_per_hit"]
        assert abs(damage - 214.2) < 1.0


class TestRWorldEnder:
    """Tests for R (World Ender) stat buff."""

    def test_r_deals_no_damage(self, aatrox_data, parse_at) -> None:
        _, abilities = parse_at(aatrox_data, 11)
        assert abilities["R"]["total_raw"] == 0.0

    def test_r_has_stat_buff(self, aatrox_data, parse_at) -> None:
        _, abilities = parse_at(aatrox_data, 11)
        assert "stat_buff" in abilities["R"]
        assert abilities["R"]["stat_buff"]["bonus_attack_damage"] > 0

    def test_r_buff_increases_q_damage(self, aatrox_data, parse_at) -> None:
        """Q damage should be higher when R is ranked (buff applied)."""
        _, no_r = parse_at(aatrox_data, 5)
        _, with_r = parse_at(aatrox_data, 11)
        assert with_r["Q"]["total_raw"] > no_r["Q"]["total_raw"]

    def test_r_bonus_ad_percent_rank1(self, aatrox_data) -> None:
        """R rank 1 grants 20% bonus AD (the stat_buff percent_of read)."""
        r_ability = aatrox_data["abilities"]["R"][0]
        bonus = extract_value(r_ability, "Bonus Attack Damage", 1) / 100.0
        assert abs(bonus - 0.20) < 0.01

    def test_r_bonus_ad_percent_rank3(self, aatrox_data) -> None:
        """R rank 3 grants 40% bonus AD."""
        r_ability = aatrox_data["abilities"]["R"][0]
        bonus = extract_value(r_ability, "Bonus Attack Damage", 3) / 100.0
        assert abs(bonus - 0.40) < 0.01


class TestRStatBuffInFightEngine:
    """Tests for R stat buff integration with the fight engine."""

    def test_stat_buff_applied_to_champion_stats(self, aatrox_data, parse_at) -> None:
        """The fight engine should apply R's bonus AD to champion stats."""
        stats, abilities = parse_at(
            aatrox_data,
            11,
            target_stats={"target_max_health": 2000.0},
        )
        original_ad = stats["attack_damage"]

        calculate_fight_damage(
            stats,
            abilities,
            [],
            FightConfig(
                target_health=2000,
                target_armor=100,
                target_magic_resistance=60,
                fight_duration_seconds=5.0,
                one_rotation=True,
            ),
        )
        assert stats["attack_damage"] > original_ad

    def test_r_zero_damage_in_breakdown(self, aatrox_data, parse_at) -> None:
        """R should appear in fight engine but contribute 0 damage."""
        stats, abilities = parse_at(
            aatrox_data,
            11,
            target_stats={"target_max_health": 2000.0},
        )
        result = calculate_fight_damage(
            stats,
            abilities,
            [],
            FightConfig(
                target_health=2000,
                target_armor=100,
                target_magic_resistance=60,
                fight_duration_seconds=5.0,
                one_rotation=True,
            ),
        )
        r_entry = result["breakdown"].get("R", {})
        assert r_entry.get("total_damage", 0.0) == 0.0


class TestWInfernalChains:
    """Tests for W (Infernal Chains) damage parsing."""

    def test_w_returns_physical_damage(self, aatrox_data, parse_at) -> None:
        _, abilities = parse_at(aatrox_data, 3)
        assert "W" in abilities
        assert abilities["W"]["damage_type"] == "physical"

    def test_w_has_cooldown(self, aatrox_data, parse_at) -> None:
        _, abilities = parse_at(aatrox_data, 3)
        assert abilities["W"]["cooldown"] > 0

    def test_w_uses_total_damage_both_hits(self, aatrox_data, parse_at) -> None:
        """W should use Total Damage (initial + pull-back), not single hit."""
        stats, abilities = parse_at(aatrox_data, 3)
        w = abilities["W"]
        ad = stats["attack_damage"]
        # W rank 1 Total Damage: 60 + 80% AD (both hits combined)
        expected_total = 60 + 0.80 * ad
        single_hit = 30 + 0.40 * ad
        assert abs(w["total_raw"] - expected_total) < 0.5
        assert w["total_raw"] > single_hit * 1.5


class TestEUmbralDash:
    """Tests for E (Umbral Dash) — should not appear in abilities."""

    def test_e_not_in_results(self, aatrox_data, parse_at) -> None:
        _, abilities = parse_at(aatrox_data, 9)
        assert "E" not in abilities


class TestReviewedCrowdControl:
    """Aatrox declares nothing: neither damaging row has one true answer.

    Q knocks up only in the Sweetspot - this module's own option - and its
    row sums all three casts; W slows on the chain hit and pulls on the
    tether hit, and its row is the cached Total of both.
    """

    def test_the_kit_declares_nothing(self):
        assert not hasattr(aatrox, "MODULE_CC")

    def test_the_darkin_blades_knockup_is_the_sweetspot_branchs(self):
        text = cc_review.slot_text(cc_review.kit("Aatrox"), "Q")
        assert "enemies hit within a sweetspot of the area" in text
        assert "are also knocked up for 0.25 seconds" in text
        assert any(row["key"] == "sweetspot" for row in aatrox.OPTIONS)

    def test_infernal_chains_two_hits_do_not_control_alike(self):
        text = cc_review.slot_text(cc_review.kit("Aatrox"), "W")
        assert "slowing them for 1.5 seconds" in text
        assert "pulled to the center of the area" in text

    def test_the_unreviewable_slots_keep_the_fight_coarse(self):
        assert cc_review.unreviewed_ability_slots("Aatrox") == ["Q", "W"]
        coverage = cc_review.fimbulwinter_coverage("Aatrox")
        assert coverage["complete"] is False
        assert "fimbulwinter_everlasting" in coverage["coarse_sources"]
