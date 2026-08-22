"""Tests for Gnar champion ability parsing and damage calculation.

Reference damage (raw, before resistances — from the wiki):
- Mini Q rank 5, 200 total AD: 165 + 1.25*200 = 415 physical
- Mega Q rank 5, 200 total AD: 225 + 1.40*200 = 505 physical
- Hyper proc rank 5, 0 AP, target 2000 max HP: 40 + 0.14*2000 = 320 magic
  per proc (every 3rd basic attack)
- Wallop rank 5, 200 total AD: 165 + 1.00*200 = 365 physical
- Hop rank 5, Gnar 2500 max HP: 190 + 0.06*2500 = 340 physical
- Crunch rank 5, Gnar 3000 max HP (incl. Mega bonus): 220 + 0.06*3000 = 400
- R rank 3, 100 bonus AD, 0 AP: no wall 400 + 0.5*100 = 450;
  wall 600 + 0.75*100 = 675 physical

Mega form stat constants (module constants — the passive's JSON leveling
is empty) come from the live game files (Community Dragon: Gnar vs
GnarBig CharacterRecords — the wiki's Mega stat box is stale). Endpoints
via the standard growth formula (growth multiplier at 18 is exactly
17.0): HP +100/+831, AD +6/+45.1, Armor +4/+55, MR +3/+62.5, bonus AS
loss 0/93.5. Mega AD is a BASE-stat increase (GnarBig base AD block), so
it must never appear in bonus_attack_damage — R's %bonus-AD ratios see 0
without items (confirmed in-game: level 18, no items, R wall = 300 flat).

Mega-form reference tests pass PRE-buff champion stats chosen so the
POST-buff stat hits the reference number (e.g. 154.9 AD + 45.1 Mega AD
= 200) — this simultaneously verifies the BUFF phase lands before the
damage slots parse.
"""

import pytest

from src.calculator.champions import parse_champion_abilities as parse_abilities
from src.calculator.champions.gnar import (
    MEGA_ATTACK_SPEED_LOSS,
    MEGA_BONUS_AD,
    MEGA_BONUS_ARMOR,
    MEGA_BONUS_HEALTH,
    MEGA_BONUS_MR,
)
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.pipeline import FightParams, run_fight
from src.calculator.stats import growth_stat
from tests import cc_review

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ALL_MAXED = {"Q": 5, "W": 5, "E": 5, "R": 3}
TARGET_2000_HP = {"target_max_health": 2000.0}

# Pre-buff stats that land on clean post-buff numbers at level 18
# (Mega grants +45.1 base AD and +831 HP at 18; bonus AD is untouched).
MEGA_18_STATS = {
    "attack_damage": 154.9,  # -> 200 total AD after Mega buff
    "bonus_attack_damage": 100.0,  # unchanged by the Mega buff (base AD)
    "health": 2169.0,  # -> 3000 max HP after Mega buff
}


def parse_mini(gnar_data, level=18, ranks=ALL_MAXED, **kwargs):
    return parse_abilities(gnar_data, level, 0.0, ability_ranks=ranks, **kwargs)


def parse_mega(gnar_data, level=18, ranks=ALL_MAXED, options=None, **kwargs):
    return parse_abilities(
        gnar_data,
        level,
        0.0,
        ability_ranks=ranks,
        champion_options={"mega": True, **(options or {})},
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Mega form stat constants (Rage Gene passive)
# ---------------------------------------------------------------------------


class TestMegaStatConstants:
    """The module constants must reproduce the game-file (Community
    Dragon GnarBig minus Gnar) deltas through the standard growth
    formula at levels 1 and 18."""

    @pytest.mark.parametrize(
        "constant, level1, level18",
        [
            (MEGA_BONUS_HEALTH, 100.0, 831.0),  # 640/122 vs 540/79
            (MEGA_BONUS_AD, 6.0, 45.1),  # 66/5.5 vs 60/3.2
            (MEGA_BONUS_ARMOR, 4.0, 55.0),  # 36/6.7 vs 32/3.7
            (MEGA_BONUS_MR, 3.0, 62.5),  # 33/4.8 vs 30/1.3
            (MEGA_ATTACK_SPEED_LOSS, 0.0, 93.5),  # 0.5/lvl vs 6.0/lvl
        ],
    )
    def test_constants_match_game_file_endpoints(
        self, constant, level1, level18
    ) -> None:
        base, growth = constant
        assert growth_stat(base, growth, 1) == pytest.approx(level1)
        assert growth_stat(base, growth, 18) == pytest.approx(level18)


# ---------------------------------------------------------------------------
# Passive: Rage Gene
# ---------------------------------------------------------------------------


class TestPassiveRageGene:
    """Mini: no entry. Mega: zero-damage BUFF entry with the stat deltas."""

    def test_absent_in_mini_form(self, gnar_data) -> None:
        abilities = parse_mini(gnar_data)
        assert "passive" not in abilities
        assert "P" not in abilities

    def test_mega_stat_buff_values_at_18(self, gnar_data) -> None:
        abilities = parse_mega(gnar_data, champion_stats={})
        buff = abilities["passive"]["stat_buff"]
        assert buff["base_health"] == pytest.approx(831.0)
        assert buff["base_attack_damage"] == pytest.approx(45.1)
        assert buff["armor"] == pytest.approx(55.0)
        assert buff["magic_resistance"] == pytest.approx(62.5)
        assert buff["bonus_attack_speed"] == pytest.approx(-93.5)
        # Mega AD is a base-stat increase — never bonus AD.
        assert "bonus_attack_damage" not in buff

    def test_mega_stat_buff_values_at_1(self, gnar_data) -> None:
        abilities = parse_mega(
            gnar_data,
            level=1,
            ranks={"Q": 1, "W": 0, "E": 0, "R": 0},
            champion_stats={},
        )
        buff = abilities["passive"]["stat_buff"]
        assert buff["base_health"] == pytest.approx(100.0)
        assert "health" not in buff, "Mega's grant is BASE health, not total"
        assert buff["base_attack_damage"] == pytest.approx(6.0)
        assert buff["bonus_attack_speed"] == pytest.approx(0.0)

    def test_mega_passive_deals_no_damage(self, gnar_data) -> None:
        abilities = parse_mega(gnar_data, champion_stats={})
        assert abilities["passive"]["total_raw"] == 0.0


# ---------------------------------------------------------------------------
# Q: Boomerang Throw (Mini) / Boulder Toss (Mega)
# ---------------------------------------------------------------------------


class TestQBoomerangThrow:
    def test_mini_q_rank5_damage_reference(self, gnar_data) -> None:
        """Mini Q rank 5, 200 AD: 165 + 1.25*200 = 415 (full damage —
        the 'Reduced Damage' subsequent-target entry is ignored)."""
        abilities = parse_mini(gnar_data, champion_stats={"attack_damage": 200.0})
        assert abilities["Q"]["total_raw"] == pytest.approx(415.0)
        assert abilities["Q"]["damage_type"] == "physical"

    def test_mega_q_rank5_damage_reference(self, gnar_data) -> None:
        """Mega Q rank 5, 200 post-buff AD: 225 + 1.40*200 = 505."""
        abilities = parse_mega(gnar_data, champion_stats=dict(MEGA_18_STATS))
        assert abilities["Q"]["total_raw"] == pytest.approx(505.0)
        assert abilities["Q"]["damage_type"] == "physical"

    def test_mini_q_pickup_cooldown_refund(self, gnar_data) -> None:
        """Catching the boomerang refunds 40%: rank 5 CD 10s -> 6s.
        q_pickup defaults to True."""
        default = parse_mini(gnar_data, champion_stats={})
        caught = parse_mini(
            gnar_data, champion_options={"q_pickup": True}, champion_stats={}
        )
        dropped = parse_mini(
            gnar_data, champion_options={"q_pickup": False}, champion_stats={}
        )
        assert caught["Q"]["cooldown"] == pytest.approx(6.0)
        assert default["Q"]["cooldown"] == pytest.approx(6.0)
        assert dropped["Q"]["cooldown"] == pytest.approx(10.0)

    def test_mega_q_pickup_cooldown_refund(self, gnar_data) -> None:
        """Picking up the boulder refunds 70%: rank 5 CD 10s -> 3s."""
        caught = parse_mega(gnar_data, champion_stats={})
        dropped = parse_mega(gnar_data, options={"q_pickup": False}, champion_stats={})
        assert caught["Q"]["cooldown"] == pytest.approx(3.0)
        assert dropped["Q"]["cooldown"] == pytest.approx(10.0)

    def test_q_pickup_does_not_change_damage(self, gnar_data) -> None:
        stats = {"attack_damage": 200.0}
        caught = parse_mini(gnar_data, champion_stats=dict(stats))
        dropped = parse_mini(
            gnar_data,
            champion_options={"q_pickup": False},
            champion_stats=dict(stats),
        )
        assert caught["Q"]["total_raw"] == dropped["Q"]["total_raw"]


# ---------------------------------------------------------------------------
# W: Hyper (Mini on-hit) / Wallop (Mega)
# ---------------------------------------------------------------------------


class TestWHyper:
    def test_hyper_is_on_hit_magic(self, gnar_data) -> None:
        abilities = parse_mini(gnar_data, target_stats=TARGET_2000_HP)
        assert "on_hit" in abilities["W"]
        assert abilities["W"]["on_hit"]["damage_type"] == "magic"
        assert abilities["W"]["total_raw"] == 0.0

    def test_hyper_procs_every_third_hit(self, gnar_data) -> None:
        abilities = parse_mini(gnar_data, target_stats=TARGET_2000_HP)
        assert abilities["W"]["on_hit"]["stacks_required"] == 3

    def test_hyper_rank5_proc_reference(self, gnar_data) -> None:
        """Rank 5, 0 AP, 2000 HP target: 40 + 0.14*2000 = 320 per proc,
        spread across 3 hits."""
        abilities = parse_mini(
            gnar_data, champion_stats={}, target_stats=TARGET_2000_HP
        )
        per_hit = abilities["W"]["on_hit"]["damage_per_hit"]
        assert per_hit == pytest.approx(320.0 / 3)

    def test_hyper_sums_flat_and_ap_modifiers(self, gnar_data) -> None:
        """Rank 5 with 100 AP: 40 + 0.14*2000 + 1.0*100 = 420 per proc —
        the single leveling entry's flat, %target-HP, and AP modifiers
        must all be summed."""
        abilities = parse_abilities(
            gnar_data,
            18,
            100.0,
            ability_ranks=ALL_MAXED,
            champion_stats={},
            target_stats=TARGET_2000_HP,
        )
        per_hit = abilities["W"]["on_hit"]["damage_per_hit"]
        assert per_hit == pytest.approx(420.0 / 3)


class TestWWallop:
    def test_wallop_rank5_damage_reference(self, gnar_data) -> None:
        """Wallop rank 5, 200 post-buff AD: 165 + 1.0*200 = 365."""
        abilities = parse_mega(gnar_data, champion_stats=dict(MEGA_18_STATS))
        assert abilities["W"]["total_raw"] == pytest.approx(365.0)
        assert abilities["W"]["damage_type"] == "physical"

    def test_wallop_is_a_cast_not_on_hit(self, gnar_data) -> None:
        abilities = parse_mega(gnar_data, champion_stats={})
        assert "on_hit" not in abilities["W"]
        assert abilities["W"]["cooldown"] > 0


# ---------------------------------------------------------------------------
# E: Hop (Mini) / Crunch (Mega)
# ---------------------------------------------------------------------------


class TestEHop:
    def test_hop_rank5_damage_reference(self, gnar_data) -> None:
        """Hop rank 5, 2500 max HP: 190 + 0.06*2500 = 340 (own max HP,
        not target's)."""
        abilities = parse_mini(gnar_data, champion_stats={"health": 2500.0})
        assert abilities["E"]["total_raw"] == pytest.approx(340.0)
        assert abilities["E"]["damage_type"] == "physical"

    def test_hop_grants_attack_speed_buff(self, gnar_data) -> None:
        """Hop rank 5 grants 60% bonus attack speed (40/45/50/55/60)."""
        abilities = parse_mini(gnar_data, champion_stats={"health": 2500.0})
        assert abilities["E"]["stat_buff"]["bonus_attack_speed"] == pytest.approx(60.0)

    def test_hop_ignores_target_health(self, gnar_data) -> None:
        vs_small = parse_mini(
            gnar_data,
            champion_stats={"health": 2500.0},
            target_stats={"target_max_health": 1000.0},
        )
        vs_big = parse_mini(
            gnar_data,
            champion_stats={"health": 2500.0},
            target_stats={"target_max_health": 4000.0},
        )
        assert vs_small["E"]["total_raw"] == vs_big["E"]["total_raw"]


class TestECrunch:
    def test_crunch_rank5_damage_reference(self, gnar_data) -> None:
        """Crunch rank 5, 3000 max HP including the Mega bonus:
        220 + 0.06*3000 = 400 — proves the HP buff lands before E."""
        abilities = parse_mega(gnar_data, champion_stats=dict(MEGA_18_STATS))
        assert abilities["E"]["total_raw"] == pytest.approx(400.0)
        assert abilities["E"]["damage_type"] == "physical"

    def test_crunch_hits_single_target_once(self, gnar_data) -> None:
        """The shockwave deals the same damage once — no double-dip."""
        abilities = parse_mega(gnar_data, champion_stats={"health": 1000.0})
        # 220 + 0.06 * (1000 + 831 Mega HP at 18) = 329.86
        assert abilities["E"]["total_raw"] == pytest.approx(329.86)

    def test_crunch_has_no_attack_speed_buff(self, gnar_data) -> None:
        abilities = parse_mega(gnar_data, champion_stats={})
        assert "stat_buff" not in abilities["E"]


# ---------------------------------------------------------------------------
# R: GNAR! (Mega only)
# ---------------------------------------------------------------------------


class TestRGnar:
    def test_r_absent_in_mini_form(self, gnar_data) -> None:
        abilities = parse_mini(gnar_data)
        assert "R" not in abilities

    def test_r_wall_rank3_damage_reference(self, gnar_data) -> None:
        """Wall crash rank 3, 100 bonus AD, 0 AP:
        600 + 0.75*100 = 675 (total damage, not additive on the base)."""
        abilities = parse_mega(gnar_data, champion_stats=dict(MEGA_18_STATS))
        assert abilities["R"]["total_raw"] == pytest.approx(675.0)
        assert abilities["R"]["damage_type"] == "physical"

    def test_r_ignores_mega_base_ad(self, gnar_data) -> None:
        """The Mega AD grant is BASE AD — R's %bonus-AD ratio must see 0
        with no items: wall crash rank 3 = 600 flat (in-game confirmed:
        level 18, no items, 100 armor target -> 300 dealt)."""
        abilities = parse_mega(gnar_data, champion_stats={})
        assert abilities["R"]["total_raw"] == pytest.approx(600.0)

    def test_r_no_wall_rank3_damage_reference(self, gnar_data) -> None:
        """No wall rank 3, 100 post-buff bonus AD, 0 AP:
        400 + 0.5*100 = 450."""
        abilities = parse_mega(
            gnar_data,
            options={"r_wall": False},
            champion_stats=dict(MEGA_18_STATS),
        )
        assert abilities["R"]["total_raw"] == pytest.approx(450.0)

    def test_r_wall_is_default(self, gnar_data) -> None:
        default = parse_mega(gnar_data, champion_stats=dict(MEGA_18_STATS))
        wall = parse_mega(
            gnar_data,
            options={"r_wall": True},
            champion_stats=dict(MEGA_18_STATS),
        )
        assert default["R"]["total_raw"] == wall["R"]["total_raw"]

    def test_r_scales_with_ap(self, gnar_data) -> None:
        """Wall crash carries a 150% AP ratio."""
        no_ap = parse_mega(gnar_data, champion_stats=dict(MEGA_18_STATS))
        with_ap = parse_abilities(
            gnar_data,
            18,
            100.0,
            ability_ranks=ALL_MAXED,
            champion_options={"mega": True},
            champion_stats=dict(MEGA_18_STATS),
        )
        assert with_ap["R"]["total_raw"] == pytest.approx(
            no_ap["R"]["total_raw"] + 150.0
        )


# ---------------------------------------------------------------------------
# Fight engine integration (Mega stat buffs, Hyper procs)
# ---------------------------------------------------------------------------


class TestFightEngineIntegration:
    def _fight(self, stats, abilities):
        return calculate_fight_damage(
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

    def test_mega_buffs_applied_to_champion_stats(self, gnar_data, parse_at) -> None:
        """The fight engine applies the Mega AD buff (as base AD) and
        the AS loss; bonus AD stays untouched."""
        stats, abilities = parse_at(gnar_data, 18, champion_options={"mega": True})
        original_ad = stats["attack_damage"]
        original_base_ad = stats["base_attack_damage"]
        original_bonus_ad = stats.get("bonus_attack_damage", 0.0)
        original_as = stats["attack_speed"]
        self._fight(stats, abilities)
        assert stats["attack_damage"] == pytest.approx(original_ad + 45.1)
        assert stats["base_attack_damage"] == pytest.approx(original_base_ad + 45.1)
        assert stats.get("bonus_attack_damage", 0.0) == pytest.approx(original_bonus_ad)
        assert stats["attack_speed"] < original_as

    def test_reported_champion_stats_reflect_mega_form(self, gnar_data) -> None:
        """run_fight's champion_stats (the UI stats panel) must show the
        fight-effective stats: Mega form changes them (user bug report:
        the panel showed Mini stats with the Mega toggle on)."""
        params = FightParams.from_request(
            {
                "target_health": 1000,
                "target_armor": 100,
                "target_mr": 100,
                "champion_options": {"mega": True},
            }
        )
        result = run_fight(gnar_data, 18, [], params)
        stats = result["champion_stats"]
        assert stats["health"] == pytest.approx(1883 + 831)
        assert stats["attack_damage"] == pytest.approx(114 + 45.1)
        assert stats["armor"] == pytest.approx(95 + 55.0)
        assert stats["magic_resistance"] == pytest.approx(52 + 62.5)
        assert stats.get("bonus_attack_damage", 0.0) == pytest.approx(0.0)

    def test_steraks_scales_with_mega_base_ad(self, gnar_data) -> None:
        """Sterak's Gage converts base AD to bonus AD — and Mega's AD
        grant IS base AD, so Sterak's must grow with it (user bug:
        Sterak's on Mega Gnar was computed from Mini base AD only).
        At 20: Mini base 123, Mega +51.2 -> Sterak's gives ~78, not ~55.
        """
        from src.calculator.data_fetcher import get_item_by_name
        from src.calculator.item_effects import steraks_bonus_ad

        items = [get_item_by_name("Sterak's Gage")]
        results = {}
        for mega in (False, True):
            params = FightParams.from_request({"champion_options": {"mega": mega}})
            results[mega] = run_fight(gnar_data, 20, list(items), params)[
                "champion_stats"
            ]

        mega_ad = growth_stat(*MEGA_BONUS_AD, 20)
        steraks_extra = steraks_bonus_ad([{"name": "Sterak's Gage"}], mega_ad)
        assert steraks_extra > 0  # guard: the accessor found the item
        bonus_diff = (
            results[True]["bonus_attack_damage"] - results[False]["bonus_attack_damage"]
        )
        total_diff = results[True]["attack_damage"] - results[False]["attack_damage"]
        assert bonus_diff == pytest.approx(steraks_extra)
        assert total_diff == pytest.approx(mega_ad + steraks_extra)

    def test_manual_scenario_level18_no_items(self, gnar_data) -> None:
        """In-game manual test (level 18, no items, Mega, target
        1000 HP / 100 armor / 100 MR): measured Q 224, W 162, E 191,
        R (wall) 300. Pinned to the pipeline's exact outputs — R is
        exact (no bonus AD), the rest are within rounding of in-game."""
        params = FightParams.from_request(
            {
                "target_health": 1000,
                "target_armor": 100,
                "target_mr": 100,
                "champion_options": {"mega": True},
            }
        )
        result = run_fight(gnar_data, 18, [], params)
        breakdown = result["breakdown"]
        assert breakdown["R"]["total_damage"] == pytest.approx(300.0)
        assert breakdown["Q"]["total_damage"] == pytest.approx(224.0, abs=0.5)
        assert breakdown["W"]["total_damage"] == pytest.approx(162.1, abs=0.5)
        assert breakdown["E"]["total_damage"] == pytest.approx(191.4, abs=0.5)

    def test_hyper_procs_in_auto_fight(self, gnar_data, parse_at) -> None:
        """Mini W shows up as every-3rd-hit procs in the breakdown."""
        stats, abilities = parse_at(gnar_data, 18)
        result = calculate_fight_damage(
            stats,
            abilities,
            [],
            FightConfig(
                target_health=5000,
                target_armor=100,
                target_magic_resistance=60,
                fight_duration_seconds=5.0,
                auto_attack_uptime=1.0,
            ),
        )
        hyper = result["breakdown"].get("on_hit_ability_W")
        assert hyper is not None
        assert hyper["unit"] == "procs"


# ---------------------------------------------------------------------------
# Reviewed crowd control (MODULE_CC, wave 4B)
# ---------------------------------------------------------------------------

_CC_CHAMPION = "Gnar"
_CC_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
_CC = cc_review.ChampionReview(_CC_CHAMPION, _CC_RANKS)


class TestReviewedCrowdControl:
    """Both forms slow on Q and E; Mega adds Wallop's stun and R's knock away.

    A control-armed holder shield (Fimbulwinter's Everlasting) reads the
    reviewed ``cc_kind`` off authored damage events; an unreviewed ability
    packet makes the whole timed fight fall back to coarse ordering, so the
    probe below is the reason these declarations exist.
    """

    def test_module_cc_is_the_declaration_the_parser_wired(self):
        from src.calculator.champions import gnar

        assert gnar.MODULE_CC == {
            "Q": "slow",
            "W": "stun",
            "E": "slow",
            "R": "knockback",
        }
        assert gnar.parse_abilities.cc_kinds == gnar.MODULE_CC

    def test_each_declared_kind_is_the_word_its_slot_text_uses(self):
        for slot, word in [["Q", "slow"], ["E", "slow"], ["R", "knock"], ["W", "stun"]]:
            assert word in _CC.slot_text(slot), slot

    def test_every_reviewed_part_carries_its_kind(self):
        assert _CC.kinds() == {"Q": ["slow"], "E": ["slow"]}

    def test_reviewed_kinds_follow_the_other_branch(self):
        """Mega adds Wallop's stun and GNAR!'s knock away."""
        assert _CC.kinds(**{"mega": True}) == {
            "Q": ["slow"],
            "W": ["stun"],
            "E": ["slow"],
            "R": ["knockback"],
        }

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = _CC.coverage()

        assert coverage["complete"] is True
        assert coverage["certification"] == "event_order_certified"
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
