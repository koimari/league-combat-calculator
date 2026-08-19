"""Tests for the Dr. Mundo champion module.

Hand-validated against the wiki, the champion JSON and the Community
Dragon game files at level 18 (Q/W/E rank 5, R rank 3). Base stats there
are health 2391 and AD 104; the reference build adds 2000 bonus health,
so max health is 4391 before R:

    Q vs a 2400 HP target = 30% x 2400            = 720.0 magic
    Q vs a  900 HP target = floor                 = 280.0 magic
    W charge              = 20 x 12 ticks         = 240.0 magic
    W detonation          = 80 + 7% x 2000        = 220.0 magic
    E passive bonus AD    = 3.2% x 4391           = 140.512
    E active @30% missing = (45 + 5% x 2000) x 1.171428 = 169.857
    E active @70% missing = 145 x 1.4             = 203.0
    R rank 3 @30% missing = 25% x (30% x 4391)    = +329.325 base health

The two numbers this file exists to defend are the ones the cached wiki
data gets WRONG: W's charge is 12 ticks (the JSON's "Total Magic Damage"
still carries 16 from the pre-V12.23 four-second duration), and E's amp
maxes at 70% missing health (absent from the wiki ability page).
"""

import copy

import pytest

from src.calculator.champions import parse_champion_abilities
from src.calculator.champions.dr_mundo import (
    E_MAX_AMP_MISSING_HEALTH_PERCENT,
    E_MAX_DAMAGE_AMP,
    OPTIONS,
    R_NEARBY_CHAMPION_BONUS,
    W_CHARGE_TICKS,
    W_DURATION,
)
from src.calculator.champions.skill_orders import get_ability_rank
from src.calculator.champions.slotlib import extract_named, extract_value
from src.calculator.data_fetcher import get_item_by_name
from src.calculator.pipeline import FightParams, run_fight
from src.calculator.stats import calculate_total_stats
from src.calculator.champions import dr_mundo
from tests import cc_review

LEVEL = 18
BASE_HEALTH = 2391.0
BASE_AD = 104.0
BONUS_HEALTH = 2000.0
MAX_HEALTH = BASE_HEALTH + BONUS_HEALTH
TARGET_HEALTH = 2400.0

DEFAULT_MISSING_PERCENT = 30
R_RANK_3_PERCENT = 0.25


def _stats(bonus_health: float = BONUS_HEALTH) -> dict[str, float]:
    """Champion stats matching the module docstring's reference build."""
    return {
        "level": float(LEVEL),
        "health": BASE_HEALTH + bonus_health,
        "bonus_health": bonus_health,
        "base_attack_damage": BASE_AD,
        "bonus_attack_damage": 0.0,
        "attack_damage": BASE_AD,
        "ability_power": 0.0,
        "armor": 100.0,
        "magic_resistance": 50.0,
        "attack_speed": 1.0,
        "attack_speed_ratio": 0.625,
        "critical_strike_chance": 0.0,
        "ability_haste": 0.0,
        "basic_ability_haste": 0.0,
        "armor_penetration_percent": 0.0,
        "flat_armor_penetration": 0.0,
        "lethality": 0.0,
        "magic_penetration_flat": 0.0,
        "magic_penetration_percent": 0.0,
        "max_mana": 500.0,
        "bonus_mana": 0.0,
        "is_melee": True,
    }


def _abilities(
    dr_mundo_data,
    *,
    bonus_health: float = BONUS_HEALTH,
    target_health: float = TARGET_HEALTH,
    **options,
) -> dict:
    """Parse Dr. Mundo at the reference build, with optional options."""
    return parse_champion_abilities(
        dr_mundo_data,
        LEVEL,
        0.0,
        champion_stats=_stats(bonus_health),
        target_stats={"target_max_health": target_health},
        champion_options=options or None,
    )


def _amp(missing_percent: float) -> float:
    """The E amp the spec defines, recomputed independently of the module."""
    ramp = min(missing_percent / E_MAX_AMP_MISSING_HEALTH_PERCENT, 1.0)
    return 1.0 + E_MAX_DAMAGE_AMP * ramp


# ---------------------------------------------------------------------------
# Q — Infected Bonesaw
# ---------------------------------------------------------------------------


class TestQ:
    """%current-health magic damage with a flat floor under it."""

    def test_percent_branch(self, dr_mundo_data) -> None:
        """Above the floor, Q is 30% of the target's health at rank 5."""
        abilities = _abilities(dr_mundo_data, target_health=2400.0)
        assert abilities["Q"]["total_raw"] == pytest.approx(720.0)
        assert abilities["Q"]["damage_type"] == "magic"

    def test_floor_branch(self, dr_mundo_data) -> None:
        """Against a low-health target the minimum damage binds instead.

        30% of 900 is 270, below the rank-5 floor of 280 — the floor wins.
        """
        abilities = _abilities(dr_mundo_data, target_health=900.0)
        assert abilities["Q"]["total_raw"] == pytest.approx(280.0)

    def test_floor_crossover_is_where_the_two_branches_meet(
        self, dr_mundo_data
    ) -> None:
        """The floor takes over below ~933 target health at rank 5."""
        crossover = 280.0 / 0.30
        just_above = _abilities(dr_mundo_data, target_health=crossover + 100.0)
        just_below = _abilities(dr_mundo_data, target_health=crossover - 100.0)
        assert just_above["Q"]["total_raw"] > 280.0
        assert just_below["Q"]["total_raw"] == pytest.approx(280.0)

    def test_reads_the_json_percent_and_floor_arrays(self, dr_mundo_data) -> None:
        """Both numbers come from the JSON, not from module constants."""
        ability = dr_mundo_data["abilities"]["Q"][0]
        assert extract_value(ability, "Magic Damage", 5) == pytest.approx(30.0)
        assert extract_value(ability, "Minimum Damage", 5) == pytest.approx(280.0)

    def test_has_no_ap_scaling(self, dr_mundo_data) -> None:
        """Mundo has no AP scaling anywhere; 500 AP must change nothing."""
        base = _abilities(dr_mundo_data)["Q"]["total_raw"]
        with_ap = parse_champion_abilities(
            dr_mundo_data,
            LEVEL,
            500.0,
            champion_stats=_stats(),
            target_stats={"target_max_health": TARGET_HEALTH},
        )["Q"]["total_raw"]
        assert with_ap == pytest.approx(base)

    def test_cooldown(self, dr_mundo_data) -> None:
        assert _abilities(dr_mundo_data)["Q"]["cooldown"] == pytest.approx(4.0)


# ---------------------------------------------------------------------------
# W — Heart Zapper
# ---------------------------------------------------------------------------


class TestW:
    """The 12-tick charge, the automatic detonation, and the stale field."""

    def test_charge_is_twelve_ticks_not_the_stale_total(self, dr_mundo_data) -> None:
        """W's charge is per-tick x 12, NOT the JSON's 16-tick total.

        The JSON's "Total Magic Damage" (320 at rank 5) is stale wiki
        data from W's pre-V12.23 four-second duration. Using it would
        make W 540 instead of 460 on the reference build.
        """
        ability = dr_mundo_data["abilities"]["W"][0]
        per_tick = extract_named(ability, "Magic Damage per Tick", 5)
        stale_total = extract_named(ability, "Total Magic Damage", 5)

        assert per_tick == pytest.approx(20.0)
        assert stale_total == pytest.approx(320.0)
        assert per_tick * W_CHARGE_TICKS == pytest.approx(240.0)
        assert stale_total != pytest.approx(per_tick * W_CHARGE_TICKS)

        assert _abilities(dr_mundo_data)["W"]["total_raw"] == pytest.approx(460.0)

    def test_detonation_scales_with_bonus_health(self, dr_mundo_data) -> None:
        """Detonation is 80 + 7% BONUS health, and always happens."""
        naked = _abilities(dr_mundo_data, bonus_health=0.0)["W"]["total_raw"]
        stacked = _abilities(dr_mundo_data)["W"]["total_raw"]
        assert naked == pytest.approx(240.0 + 80.0)
        assert stacked - naked == pytest.approx(0.07 * BONUS_HEALTH)

    def test_charge_does_not_scale_with_bonus_health(self, dr_mundo_data) -> None:
        """Only the detonation carries the %bonus-health modifier."""
        ability = dr_mundo_data["abilities"]["W"][0]
        stats = _stats()
        per_tick = extract_named(ability, "Magic Damage per Tick", 5, stats)
        assert per_tick == pytest.approx(20.0)

    def test_dot_duration_keeps_item_burns_running(self, dr_mundo_data) -> None:
        """Without dot_duration, item burns would end at the cast instant."""
        assert _abilities(dr_mundo_data)["W"]["dot_duration"] == pytest.approx(3.0)
        assert W_DURATION * 4.0 == W_CHARGE_TICKS

    def test_damage_type_and_cooldown(self, dr_mundo_data) -> None:
        entry = _abilities(dr_mundo_data)["W"]
        assert entry["damage_type"] == "magic"
        assert entry["cooldown"] == pytest.approx(15.0)


# ---------------------------------------------------------------------------
# E — Blunt Force Trauma
# ---------------------------------------------------------------------------


class TestEPassive:
    """The %MAXIMUM-health bonus AD steroid (not % bonus health)."""

    def test_bonus_ad_is_percent_of_total_health(self, dr_mundo_data) -> None:
        """3.2% of MAX health at rank 5 — 76.5 naked, 140.5 stacked."""
        naked = _abilities(
            dr_mundo_data, bonus_health=0.0, mundo_missing_health_percent=0
        )
        stacked = _abilities(dr_mundo_data, mundo_missing_health_percent=0)
        assert naked["E"]["stat_buff"]["bonus_attack_damage"] == pytest.approx(
            0.032 * BASE_HEALTH
        )
        assert stacked["E"]["stat_buff"]["bonus_attack_damage"] == pytest.approx(
            0.032 * MAX_HEALTH
        )

    def test_bonus_ad_is_not_percent_of_bonus_health(self, dr_mundo_data) -> None:
        """A naked Mundo still gets +76.5 AD; % bonus health would give 0."""
        naked = _abilities(
            dr_mundo_data, bonus_health=0.0, mundo_missing_health_percent=0
        )
        assert naked["E"]["stat_buff"]["bonus_attack_damage"] > 0.0

    def test_buff_reaches_the_parse_context(self, dr_mundo_data) -> None:
        """apply_to feeds both AD keys, so autos and later slots see it."""
        stats = _stats(bonus_health=0.0)
        parse_champion_abilities(
            dr_mundo_data,
            LEVEL,
            0.0,
            champion_stats=stats,
            target_stats={"target_max_health": TARGET_HEALTH},
            champion_options={"mundo_missing_health_percent": 0},
        )
        # The parse copies the caller's dict, so the caller's is untouched.
        assert stats["attack_damage"] == pytest.approx(BASE_AD)


class TestEActive:
    """The empowered auto's bonus and its missing-health amplifier."""

    def test_base_bonus_before_amp(self, dr_mundo_data) -> None:
        """The un-amped bonus is 45 + 5% bonus health at rank 5."""
        ability = dr_mundo_data["abilities"]["E"][0]
        base = extract_named(
            ability, "Minimum Bonus Physical Damage", 5, _stats(), None
        )
        assert base == pytest.approx(45.0 + 0.05 * BONUS_HEALTH)

    @pytest.mark.parametrize("missing", [0, 35, 70, 100])
    def test_amp_at_each_threshold(self, dr_mundo_data, missing) -> None:
        """Amp ramps 1.0 -> 1.4 over 0-70% missing, then plateaus."""
        entry = _abilities(dr_mundo_data, mundo_missing_health_percent=missing)["E"]
        base = 45.0 + 0.05 * BONUS_HEALTH
        assert entry["total_raw"] == pytest.approx(base * _amp(missing))

    def test_amp_plateaus_above_seventy_percent(self, dr_mundo_data) -> None:
        """70%, 85% and 100% missing all give the SAME damage."""
        totals = {
            missing: _abilities(dr_mundo_data, mundo_missing_health_percent=missing)[
                "E"
            ]["total_raw"]
            for missing in (70, 85, 100)
        }
        assert totals[70] == pytest.approx(totals[85])
        assert totals[70] == pytest.approx(totals[100])
        assert totals[70] == pytest.approx(203.0)

    def test_amp_is_not_reached_at_forty_percent_missing(self, dr_mundo_data) -> None:
        """Guards the 70% threshold against a regression to 100%."""
        at_70 = _abilities(dr_mundo_data, mundo_missing_health_percent=70)["E"]
        at_40 = _abilities(dr_mundo_data, mundo_missing_health_percent=40)["E"]
        assert at_40["total_raw"] < at_70["total_raw"]
        assert at_40["total_raw"] == pytest.approx(
            (45.0 + 0.05 * BONUS_HEALTH) * _amp(40)
        )

    def test_max_damage_identity_matches_the_wiki_row(self, dr_mundo_data) -> None:
        """(minimum) x 1.4 must reproduce the wiki's "Maximum" row exactly.

        This is the check that proves the amp multiplies the WHOLE
        expression (flat AND the %bonus-health term) rather than the flat
        part alone — and that the "Maximum Bonus Physical Damage"
        attribute is the same damage, never a second source to add.
        """
        ability = dr_mundo_data["abilities"]["E"][0]
        for rank in range(1, 6):
            minimum = extract_named(
                ability, "Minimum Bonus Physical Damage", rank, _stats(), None
            )
            maximum = extract_named(
                ability, "Maximum Bonus Physical Damage", rank, _stats(), None
            )
            assert minimum * (1.0 + E_MAX_DAMAGE_AMP) == pytest.approx(maximum)

        # And the module reproduces it: rank 5, no bonus health, 70% missing.
        entry = _abilities(
            dr_mundo_data, bonus_health=0.0, mundo_missing_health_percent=70
        )["E"]
        assert entry["total_raw"] == pytest.approx(63.0)

    def test_default_missing_health_is_thirty_percent(self, dr_mundo_data) -> None:
        """The declared OPTIONS default must match the parse fallback."""
        explicit = _abilities(
            dr_mundo_data, mundo_missing_health_percent=DEFAULT_MISSING_PERCENT
        )
        assert _abilities(dr_mundo_data)["E"]["total_raw"] == pytest.approx(
            explicit["E"]["total_raw"]
        )
        assert _abilities(dr_mundo_data)["E"]["total_raw"] == pytest.approx(169.857142)

    def test_empowers_next_auto_once_per_cast(self, dr_mundo_data) -> None:
        entry = _abilities(dr_mundo_data)["E"]
        assert entry["empowers_next_auto"] is True
        assert entry["damage_type"] == "physical"
        assert entry["cooldown"] == pytest.approx(6.0)


# ---------------------------------------------------------------------------
# R — Maximum Dosage
# ---------------------------------------------------------------------------


class TestR:
    """Zero damage, a BASE-health grant, and the rank-3 proximity bonus."""

    def test_deals_no_damage(self, dr_mundo_data) -> None:
        """R is a stat buff only — no damage calculation exists in game."""
        entry = _abilities(dr_mundo_data)["R"]
        assert entry["total_raw"] == 0.0
        assert sum(part.amount for part in entry["parts"]) == 0.0

    def test_grants_base_health_from_missing_health(self, dr_mundo_data) -> None:
        """Rank 3 grants 25% of missing health as BASE health."""
        entry = _abilities(dr_mundo_data)["R"]
        expected = R_RANK_3_PERCENT * MAX_HEALTH * DEFAULT_MISSING_PERCENT / 100.0
        assert entry["stat_buff"]["base_health"] == pytest.approx(expected)
        assert entry["stat_buff"]["base_health"] == pytest.approx(329.325)

    def test_grant_is_base_health_not_bonus_health(self, dr_mundo_data) -> None:
        """The key matters: bonus_health would feed Bloodmail-style items."""
        stat_buff = _abilities(dr_mundo_data)["R"]["stat_buff"]
        assert "base_health" in stat_buff
        assert "bonus_health" not in stat_buff

    def test_nearby_champions_only_help_at_rank_three(self, dr_mundo_data) -> None:
        """+5% per nearby champion, rank 3 only."""
        alone = _abilities(dr_mundo_data)["R"]["stat_buff"]["base_health"]
        crowded = _abilities(dr_mundo_data, r_nearby_champions=2)["R"]["stat_buff"][
            "base_health"
        ]
        assert crowded == pytest.approx(alone * (1.0 + 2 * R_NEARBY_CHAMPION_BONUS))
        assert crowded == pytest.approx(362.2575)

    def test_nearby_bonus_absent_below_rank_three(self, dr_mundo_data) -> None:
        """At rank 1 the proximity bonus does not exist."""
        params = {
            "champion_stats": _stats(),
            "target_stats": {"target_max_health": TARGET_HEALTH},
            "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 1},
        }
        alone = parse_champion_abilities(dr_mundo_data, LEVEL, 0.0, **params)
        crowded = parse_champion_abilities(
            dr_mundo_data,
            LEVEL,
            0.0,
            champion_options={"r_nearby_champions": 4},
            **params,
        )
        assert alone["R"]["stat_buff"]["base_health"] == pytest.approx(
            crowded["R"]["stat_buff"]["base_health"]
        )

    def test_cooldown(self, dr_mundo_data) -> None:
        assert _abilities(dr_mundo_data)["R"]["cooldown"] == pytest.approx(120.0)


# ---------------------------------------------------------------------------
# The BUFF-phase ordering chain: R -> max health -> E's bonus AD
# ---------------------------------------------------------------------------


class TestBuffOrdering:
    """R must resolve before E's passive reads ctx.stats["health"]."""

    def test_r_raises_e_passive_bonus_ad(self, dr_mundo_data) -> None:
        """With R ranked and health missing, E's AD is strictly larger."""
        healthy = _abilities(dr_mundo_data, mundo_missing_health_percent=0)
        hurt = _abilities(dr_mundo_data, mundo_missing_health_percent=30)
        healthy_ad = healthy["E"]["stat_buff"]["bonus_attack_damage"]
        hurt_ad = hurt["E"]["stat_buff"]["bonus_attack_damage"]
        assert hurt_ad > healthy_ad

    def test_the_whole_chain_end_to_end(self, dr_mundo_data) -> None:
        """R grant -> new max health -> E's 3.2% of it, exactly."""
        abilities = _abilities(dr_mundo_data)
        grant = abilities["R"]["stat_buff"]["base_health"]
        bonus_ad = abilities["E"]["stat_buff"]["bonus_attack_damage"]

        assert grant == pytest.approx(329.325)
        assert bonus_ad == pytest.approx(0.032 * (MAX_HEALTH + grant))
        assert bonus_ad == pytest.approx(151.0504)
        # Without R's grant it would only be 140.512.
        assert bonus_ad > 0.032 * MAX_HEALTH

    def test_ordering_holds_without_r(self, dr_mundo_data) -> None:
        """Below level 6 (no R) E's passive is plain 3.2% of max health."""
        abilities = parse_champion_abilities(
            dr_mundo_data,
            LEVEL,
            0.0,
            champion_stats=_stats(),
            target_stats={"target_max_health": TARGET_HEALTH},
            ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 0},
        )
        assert "R" not in abilities
        assert abilities["E"]["stat_buff"]["bonus_attack_damage"] == pytest.approx(
            0.032 * MAX_HEALTH
        )


# ---------------------------------------------------------------------------
# The missing-health coupling: ONE option, never two
# ---------------------------------------------------------------------------


class TestMissingHealthIsOneInput:
    """E's amp and R's grant describe one game state, so they share one input.

    The invariant, not the number (the Darius rule): at EVERY option value
    both consumers must agree with the same input, and no second option may
    move either of them.
    """

    def test_only_two_options_exist(self) -> None:
        assert {option["key"] for option in OPTIONS} == {
            "mundo_missing_health_percent",
            "r_nearby_champions",
        }

    @pytest.mark.parametrize("missing", range(0, 101, 5))
    def test_both_consumers_track_the_single_option(
        self, dr_mundo_data, missing
    ) -> None:
        abilities = _abilities(dr_mundo_data, mundo_missing_health_percent=missing)
        base_bonus = 45.0 + 0.05 * BONUS_HEALTH

        assert abilities["E"]["total_raw"] == pytest.approx(base_bonus * _amp(missing))
        assert abilities["R"]["stat_buff"]["base_health"] == pytest.approx(
            R_RANK_3_PERCENT * MAX_HEALTH * missing / 100.0
        )

    def test_both_move_together_monotonically(self, dr_mundo_data) -> None:
        """More missing health never means less E damage or less R health."""
        e_damage, r_grant = [], []
        for missing in range(0, 101, 10):
            abilities = _abilities(dr_mundo_data, mundo_missing_health_percent=missing)
            e_damage.append(abilities["E"]["total_raw"])
            r_grant.append(abilities["R"]["stat_buff"]["base_health"])
        assert e_damage == sorted(e_damage)
        assert r_grant == sorted(r_grant)
        assert r_grant[-1] > r_grant[0]

    def test_nearby_option_never_touches_e(self, dr_mundo_data) -> None:
        """The rank-3 proximity bonus is R's alone."""
        alone = _abilities(dr_mundo_data)["E"]["total_raw"]
        crowded = _abilities(dr_mundo_data, r_nearby_champions=4)["E"]["total_raw"]
        assert alone == pytest.approx(crowded)


# ---------------------------------------------------------------------------
# Slot map shape
# ---------------------------------------------------------------------------


class TestSlots:
    """What the module emits, and what it deliberately does not."""

    def test_passive_is_absent(self, dr_mundo_data) -> None:
        """Goes Where He Pleases deals no damage — no slot, no row."""
        assert "passive" not in _abilities(dr_mundo_data)

    def test_all_four_castables_emit(self, dr_mundo_data) -> None:
        assert set(_abilities(dr_mundo_data)) == {"Q", "W", "E", "R"}

    def test_skill_order_is_q_then_e_then_w(self, dr_mundo_data) -> None:
        """Q maxed at 9, E at 13, W at 18, R at 6/11/16."""
        ranks = {
            level: {
                slot: get_ability_rank(slot, level, "Dr. Mundo")
                for slot in ("Q", "W", "E", "R")
            }
            for level in (9, 13, 16, 18)
        }
        assert ranks[9]["Q"] == 5
        assert ranks[13]["E"] == 5
        assert ranks[18]["W"] == 5
        assert ranks[16]["R"] == 3


# ---------------------------------------------------------------------------
# Fight integration
# ---------------------------------------------------------------------------


def _one_rotation(dr_mundo_data, items=None, **options) -> dict:
    """One-rotation pipeline fight against a resistance-free target.

    Goes through ``run_fight`` (not ``calculate_fight_damage``) because
    the reported ``champion_stats`` panel is half of what these tests
    check — the parse-context mutation alone would not show up there.
    """
    return run_fight(
        copy.deepcopy(dr_mundo_data),
        LEVEL,
        items or [],
        FightParams(
            target_health=TARGET_HEALTH,
            target_armor=0.0,
            target_magic_resistance=0.0,
            fight_duration_seconds=5.0,
            auto_attack_uptime=0.0,
            one_rotation=True,
            deterministic=True,
            champion_options=options or None,
        ),
    )


class TestFightIntegration:
    """The engine-facing half: forced swings and the reported stats panel."""

    @staticmethod
    def _reference(dr_mundo_data) -> tuple[dict, dict, float]:
        """A tanked-up fight plus its pre-buff stats and R's grant."""
        items = [get_item_by_name("Warmog's Armor")]
        pre_buff = calculate_total_stats(dr_mundo_data, LEVEL, items)
        grant = R_RANK_3_PERCENT * pre_buff["health"] * DEFAULT_MISSING_PERCENT / 100.0
        return _one_rotation(dr_mundo_data, items), pre_buff, grant

    def test_e_row_carries_its_forced_basic_attack(self, dr_mundo_data) -> None:
        """With no auto stream, E's row is "attack + bonus", not bonus alone.

        The Blitzcrank/Vayne/Caitlyn rule: an empowered-auto cast still
        forces its swing when there is nothing to ride.
        """
        result, pre_buff, _ = self._reference(dr_mundo_data)
        stats = result["champion_stats"]
        e_row = result["breakdown"]["E"]["total_damage"]

        expected_bonus = (45.0 + 0.05 * pre_buff["bonus_health"]) * _amp(
            DEFAULT_MISSING_PERCENT
        )
        assert e_row == pytest.approx(expected_bonus + stats["attack_damage"])
        assert e_row > expected_bonus
        # There is no auto stream here, so that swing can only be E's own.
        assert result["breakdown"]["auto_attacks"]["total_damage"] == 0.0

    def test_champion_stats_panel_reflects_both_buffs(self, dr_mundo_data) -> None:
        """The Gnar rule: verify run_fight's reported stats, not just ratios."""
        result, pre_buff, grant = self._reference(dr_mundo_data)
        stats = result["champion_stats"]
        buffed_health = pre_buff["health"] + grant

        assert grant > 0.0
        assert stats["health"] == pytest.approx(buffed_health)
        assert stats["bonus_attack_damage"] == pytest.approx(0.032 * buffed_health)
        assert stats["attack_damage"] == pytest.approx(
            pre_buff["base_attack_damage"] + 0.032 * buffed_health
        )

    def test_r_base_health_does_not_become_bonus_health(self, dr_mundo_data) -> None:
        """Bonus health must be untouched by R — Bloodmail must not grow."""
        result, pre_buff, _ = self._reference(dr_mundo_data)
        assert result["champion_stats"]["bonus_health"] == pytest.approx(
            pre_buff["bonus_health"]
        )

    def test_bloodmail_does_not_convert_rs_base_health(self, dr_mundo_data) -> None:
        """The base-vs-bonus split, tested against the item that cares.

        Overlord's Bloodmail turns BONUS health into AD. R grants BASE
        health, so Mundo's bonus AD must be exactly the item conversion
        (already priced into the build) plus E's passive — never a third
        term from R's grant.
        """
        items = [get_item_by_name("Overlord's Bloodmail")]
        pre_buff = calculate_total_stats(dr_mundo_data, LEVEL, items)
        grant = R_RANK_3_PERCENT * pre_buff["health"] * DEFAULT_MISSING_PERCENT / 100.0
        stats = _one_rotation(dr_mundo_data, items)["champion_stats"]

        assert pre_buff["bonus_attack_damage"] > 0.0  # the item conversion fired
        assert stats["bonus_attack_damage"] == pytest.approx(
            pre_buff["bonus_attack_damage"] + 0.032 * (pre_buff["health"] + grant)
        )

    def test_r_contributes_no_damage_to_the_rotation(self, dr_mundo_data) -> None:
        assert _one_rotation(dr_mundo_data)["breakdown"]["R"]["total_damage"] == 0.0

    def test_magic_damage_is_q_plus_w(self, dr_mundo_data) -> None:
        """The whole pipeline runs; Q and W are Mundo's only magic damage."""
        result = _one_rotation(dr_mundo_data)
        breakdown = result["breakdown"]
        assert breakdown["Q"]["total_damage"] > 0.0
        assert breakdown["W"]["total_damage"] > 0.0
        assert result["damage_by_type"]["magic"] == pytest.approx(
            breakdown["Q"]["total_damage"] + breakdown["W"]["total_damage"]
        )


class TestReviewedCrowdControl:
    """Dr. Mundo's crowd-control review, and the slot that still withholds.

    Q's bonesaw slow and W's control-free ticks are both readable and
    both reach the ledger, but declaring Q's slow makes
    rotation_resolver order Q first as cc setup, which re-prices its
    current-health formula and moves the fight's numbers (see the batch
    report).
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Dr. Mundo")
        assert not hasattr(dr_mundo, "MODULE_CC")

    def test_the_unreviewable_slots_keep_the_fight_coarse(self):
        assert cc_review.unreviewed_ability_slots("Dr. Mundo") == ["E", "Q", "W"]
        coverage = cc_review.fimbulwinter_coverage("Dr. Mundo")
        assert coverage["complete"] is False
        assert "fimbulwinter_everlasting" in coverage["coarse_sources"]
