"""Tests for Jayce champion ability parsing and damage calculation.

Reference values (wiki: https://wiki.leagueoflegends.com/en-us/Jayce),
all at level 18 with Q/W/E at rank 6, 250 total AD / 150 bonus AD /
0 AP against a 2500 max-HP target — RAW, pre-mitigation:

- Cannon Q (Shock Blast), not gated: 285 + 130% bonus AD = 480 physical
- Cannon Q, through the Acceleration Gate: 399 + 182% bonus AD = 672
  physical (exactly 1.4x the ungated line — "Increased Damage" is the
  TOTAL of a supercharged blast, never an addition to the base line)
- Hammer Q (To the Skies!): 310 + 135% bonus AD = 512.5 physical
- Hammer W (Lightning Field), 4 ticks: 440 (+100% AP) magic
- Cannon W (Hyper Charge): 110% TOTAL AD per attack x 3 = 825 physical.
  Its +360% attack speed belongs to those 3 attacks only (they fire at
  the game's 3.003 cap), never to the whole fight
- Hammer E (Thundering Blow): 22% of target max health + 100% bonus AD
  = 550 + 150 = 700 MAGIC
- R Hammer empowered auto: 130 + 30% bonus AD = 175 magic
- R Hammer resists: 26 + 7.5% bonus AD = +37.25 armor AND magic resist
- R Cannon shred: 35% of the target's armor and magic resist

Jayce starts with R at rank 1 and can never level it, so Q/W/E have SIX
ranks and R's values step with CHAMPION LEVEL at 1 / 6 / 11 / 16.
"""

import pytest

from src.calculator.champions import get_champion_cast_order
from src.calculator.champions import parse_champion_abilities as parse_abilities
from src.calculator.champions.skill_orders import get_ability_rank
from src.calculator.champions.slotlib import extract_value
from src.calculator.data_fetcher import get_item_by_name
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.stats import ATTACK_SPEED_CAP

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# The reference build from the module docstring.
STATS_250_AD = {
    "attack_damage": 250.0,
    "base_attack_damage": 100.0,
    "bonus_attack_damage": 150.0,
    "attack_speed": 1.0,
    "attack_speed_ratio": 0.658,
    "bonus_attack_speed": 0.0,
}

TARGET_2500 = {"target_max_health": 2500.0}

HAMMER = {"hammer_stance": True}
CANNON = {"hammer_stance": False}


def _parse(data, level=18, options=None, ap=0.0, stats=None, target=None):
    """Parse at a champion level (Jayce ranks come from the skill order)."""
    return parse_abilities(
        data,
        level,
        ap,
        champion_options=options,
        champion_stats=dict(stats or STATS_250_AD),
        target_stats=dict(target or TARGET_2500),
    )


def _fight(
    stats, abilities, *, uptime=0.0, one_rotation=True, duration=5.0, items=None
):
    """Run the fight engine against a 0-resist target (raw == mitigated)."""
    return calculate_fight_damage(
        stats,
        abilities,
        items or [],
        FightConfig(
            target_health=2500,
            target_armor=0,
            target_magic_resistance=0,
            fight_duration_seconds=duration,
            auto_attack_uptime=uptime,
            one_rotation=one_rotation,
            deterministic=True,
        ),
    )


# ---------------------------------------------------------------------------
# Skill order: six ranks of Q/W/E, no R rank at all
# ---------------------------------------------------------------------------


class TestSkillOrder:
    """Jayce's 18 skill points all go to Q/W/E — R is never leveled."""

    def test_r_is_never_leveled(self) -> None:
        """R has no entry in the order, at any level."""
        for level in range(1, 21):
            assert get_ability_rank("R", level, "Jayce") == 0

    def test_basic_abilities_reach_rank_six(self) -> None:
        for key in ("Q", "W", "E"):
            assert get_ability_rank(key, 18, "Jayce") == 6

    def test_max_order_is_q_then_w_then_e(self) -> None:
        """Q maxes at 8, W at 13, E at 18 — one short a level earlier."""
        assert get_ability_rank("Q", 7, "Jayce") == 5
        assert get_ability_rank("Q", 8, "Jayce") == 6
        assert get_ability_rank("W", 12, "Jayce") == 5
        assert get_ability_rank("W", 13, "Jayce") == 6
        assert get_ability_rank("E", 17, "Jayce") == 5
        assert get_ability_rank("E", 18, "Jayce") == 6

    def test_level_cap_20_keeps_rank_six(self) -> None:
        """Levels 19-20 grant no skill points — ranks stay at 6."""
        for level in (19, 20):
            for key in ("Q", "W", "E"):
                assert get_ability_rank(key, level, "Jayce") == 6

    def test_json_arrays_have_six_ranks(self, jayce_data) -> None:
        """The 6-rank order is grounded in the data, not an assumption."""
        for slot in ("Q", "W", "E"):
            for ability in jayce_data["abilities"][slot]:
                for effect in ability.get("effects", []):
                    for leveling in effect.get("leveling", []):
                        for modifier in leveling.get("modifiers", []):
                            assert len(modifier["values"]) == 6


# ---------------------------------------------------------------------------
# Q: To the Skies! (Hammer) / Shock Blast (Cannon)
# ---------------------------------------------------------------------------


class TestQ:
    """Q dispatches on stance; Cannon picks its attribute by the gate."""

    def test_hammer_q_rank6(self, jayce_data) -> None:
        """310 + 135% x 150 = 512.5 — proves the Slow entry never leaks."""
        abilities = _parse(jayce_data, options=HAMMER)
        assert abilities["Q"]["name"] == "To the Skies!"
        assert abilities["Q"]["damage_type"] == "physical"
        assert abilities["Q"]["total_raw"] == pytest.approx(512.5)

    def test_hammer_q_rank1(self, jayce_data) -> None:
        """Level 1: rank 1, 60 + 135% x 150 = 262.5."""
        abilities = _parse(jayce_data, level=1, options=HAMMER)
        assert abilities["Q"]["total_raw"] == pytest.approx(262.5)

    def test_hammer_q_cooldown(self, jayce_data) -> None:
        """16 at rank 1 down to 6 at rank 6."""
        assert _parse(jayce_data, level=1, options=HAMMER)["Q"][
            "cooldown"
        ] == pytest.approx(16.0)
        assert _parse(jayce_data, options=HAMMER)["Q"]["cooldown"] == pytest.approx(6.0)

    def test_cannon_q_gated_by_default(self, jayce_data) -> None:
        """399 + 182% x 150 = 672 (the accelerated_q default is True)."""
        abilities = _parse(jayce_data)
        assert abilities["Q"]["name"] == "Shock Blast"
        assert abilities["Q"]["damage_type"] == "physical"
        assert abilities["Q"]["total_raw"] == pytest.approx(672.0)

    def test_cannon_q_ungated(self, jayce_data) -> None:
        """285 + 130% x 150 = 480."""
        abilities = _parse(jayce_data, options={**CANNON, "accelerated_q": False})
        assert abilities["Q"]["total_raw"] == pytest.approx(480.0)

    def test_gated_q_is_exactly_1_4x_ungated(self, jayce_data) -> None:
        """ "Increased Damage" is a TOTAL, not an addition: 1.4x, never 2.4x."""
        gated = _parse(jayce_data)["Q"]["total_raw"]
        plain = _parse(jayce_data, options={**CANNON, "accelerated_q": False})["Q"][
            "total_raw"
        ]
        assert gated == pytest.approx(plain * 1.4)

    def test_json_increased_damage_is_1_4x_at_every_rank(self, jayce_data) -> None:
        """Lock the 1.4x relationship against the raw JSON at all 6 ranks."""
        shock_blast = jayce_data["abilities"]["Q"][1]
        for rank in range(1, 7):
            base = extract_value(shock_blast, "Physical Damage", rank)
            increased = extract_value(shock_blast, "Increased Damage", rank)
            assert increased == pytest.approx(base * 1.4)

    def test_cannon_q_cooldown_flat_8(self, jayce_data) -> None:
        assert _parse(jayce_data)["Q"]["cooldown"] == pytest.approx(8.0)
        assert _parse(jayce_data, level=1)["Q"]["cooldown"] == pytest.approx(8.0)

    def test_accelerated_q_ignored_in_hammer(self, jayce_data) -> None:
        """The gate option is Cannon-only — Hammer Q is unaffected."""
        on = _parse(jayce_data, options={**HAMMER, "accelerated_q": True})
        off = _parse(jayce_data, options={**HAMMER, "accelerated_q": False})
        assert on["Q"]["total_raw"] == off["Q"]["total_raw"] == pytest.approx(512.5)


# ---------------------------------------------------------------------------
# W: Lightning Field (Hammer) / Hyper Charge (Cannon)
# ---------------------------------------------------------------------------


class TestWHammer:
    """Hammer W is a 4-tick DoT read from "Total Magic Damage"."""

    def test_lightning_field_rank6(self, jayce_data) -> None:
        abilities = _parse(jayce_data, options=HAMMER)
        assert abilities["W"]["name"] == "Lightning Field"
        assert abilities["W"]["damage_type"] == "magic"
        assert abilities["W"]["total_raw"] == pytest.approx(440.0)

    def test_lightning_field_ap_ratio(self, jayce_data) -> None:
        """+100% AP on the total (not the +25% AP per-tick line)."""
        abilities = _parse(jayce_data, options=HAMMER, ap=200.0)
        assert abilities["W"]["total_raw"] == pytest.approx(640.0)

    def test_mana_restored_never_read_as_damage(self, jayce_data) -> None:
        """The ability's FIRST leveling entry is "Mana Restored" (15-25);
        neither it nor the per-tick line may reach the damage row."""
        lightning_field = jayce_data["abilities"]["W"][0]
        assert extract_value(lightning_field, "Mana Restored", 6) == pytest.approx(25.0)
        assert _parse(jayce_data, level=2, options=HAMMER)["W"][
            "total_raw"
        ] == pytest.approx(140.0)

    def test_json_total_is_four_times_per_tick(self, jayce_data) -> None:
        """The 4-tick count is grounded in the data, not counted by hand."""
        lightning_field = jayce_data["abilities"]["W"][0]
        for rank in range(1, 7):
            per_tick = extract_value(lightning_field, "Magic Damage Per Tick", rank)
            total = extract_value(lightning_field, "Total Magic Damage", rank)
            assert total == pytest.approx(4 * per_tick)

    def test_lightning_field_is_a_four_second_dot(self, jayce_data) -> None:
        assert _parse(jayce_data, options=HAMMER)["W"]["dot_duration"] == 4.0

    def test_lightning_field_cooldown_flat_10(self, jayce_data) -> None:
        assert _parse(jayce_data, options=HAMMER)["W"]["cooldown"] == pytest.approx(
            10.0
        )

    def test_hammer_w_has_no_attack_speed_buff(self, jayce_data) -> None:
        assert "stat_buff" not in _parse(jayce_data, options=HAMMER)["W"]


class TestWCannon:
    """Hyper Charge: 3 attacks whose AD ratio REPLACES the auto's own."""

    def test_hyper_charge_rank6(self, jayce_data) -> None:
        """110% x 250 AD = 275 per attack, 825 across the 3 attacks."""
        abilities = _parse(jayce_data)
        assert abilities["W"]["name"] == "Hyper Charge"
        assert abilities["W"]["damage_type"] == "physical"
        assert abilities["W"]["total_raw"] == pytest.approx(825.0)

    def test_parts_carry_only_the_delta_from_a_normal_swing(self, jayce_data) -> None:
        """The attacks REPLACE the auto's damage, so the entry adds only
        (ratio - 1) x total AD on top of the swings it consumes."""
        (part,) = _parse(jayce_data)["W"]["parts"]
        assert part.amount == pytest.approx(0.10 * 250.0)
        assert part.count == 3
        assert part.basic_damage is True
        assert part.crit_effectiveness == 1.0

    def test_rank1_attacks_are_weaker_than_a_normal_auto(self, jayce_data) -> None:
        """70% AD at rank 1: each empowered attack is a DOWNGRADE, so the
        delta is negative and the 3-attack total is below 3 autos."""
        abilities = _parse(jayce_data, level=2)
        (part,) = abilities["W"]["parts"]
        assert part.amount == pytest.approx(-0.30 * 250.0)
        assert abilities["W"]["total_raw"] == pytest.approx(3 * 0.70 * 250.0)

    def test_ratio_scales_off_total_ad_not_bonus_ad(self, jayce_data) -> None:
        """Doubling BASE AD (bonus AD fixed) must move the damage."""
        stats = dict(STATS_250_AD, attack_damage=350.0, base_attack_damage=200.0)
        abilities = _parse(jayce_data, stats=stats)
        assert abilities["W"]["total_raw"] == pytest.approx(3 * 1.10 * 350.0)

    def test_empowers_three_basic_attacks(self, jayce_data) -> None:
        assert _parse(jayce_data)["W"]["empowers_next_auto"]["hits"] == 3

    def test_cooldown(self, jayce_data) -> None:
        """13 at rank 1 down to 5 at rank 6."""
        assert _parse(jayce_data, level=2)["W"]["cooldown"] == pytest.approx(13.0)
        assert _parse(jayce_data)["W"]["cooldown"] == pytest.approx(5.0)

    def test_json_total_cross_checks_three_attacks(self, jayce_data) -> None:
        """The JSON's "Total Physical Damage" (210-330% AD) is the 3-attack
        sum — never a damage row of its own, but it locks the hit count."""
        hyper_charge = jayce_data["abilities"]["W"][1]
        for rank in range(1, 7):
            per_attack = extract_value(hyper_charge, "Physical Damage", rank)
            total = extract_value(hyper_charge, "Total Physical Damage", rank)
            assert total == pytest.approx(3 * per_attack)

    def test_one_rotation_row_is_three_modified_attacks(self, jayce_data) -> None:
        """With no auto stream the cast forces its 3 swings onto its own
        row: 3 x 110% x total AD, NOT 3 autos plus a bonus."""
        stats = dict(STATS_250_AD)
        abilities = _parse(jayce_data, stats=stats)
        result = _fight(stats, abilities, uptime=0.0)
        assert result["breakdown"]["W"]["total_damage"] == pytest.approx(
            3 * 1.10 * 250.0
        )

    def test_one_rotation_row_at_rank1_is_below_three_autos(self, jayce_data) -> None:
        """Rank 1 (70% AD) must come out BELOW three plain autos — the
        modified-damage trap: additive modeling would show 170%."""
        stats = dict(STATS_250_AD)
        abilities = _parse(jayce_data, level=2, stats=stats)
        result = _fight(stats, abilities, uptime=0.0)
        assert result["breakdown"]["W"]["total_damage"] == pytest.approx(
            3 * 0.70 * 250.0
        )

    def test_timed_fight_moves_swings_without_double_counting(self, jayce_data) -> None:
        """With an auto stream the 3 attacks per cast ARE autos: the auto
        row must shed exactly 3 per cast, and each moved swing must be
        priced at 110% AD (not 100% + 110%)."""
        stats = dict(STATS_250_AD)
        abilities = _parse(jayce_data, stats=stats)
        result = _fight(stats, abilities, uptime=1.0, one_rotation=False, duration=10.0)
        auto_row = result["breakdown"]["auto_attacks"]
        w_row = result["breakdown"]["W"]
        swings = 3 * w_row["casts"]
        assert swings > 0
        # The autos left in their own row still price at a plain 100% AD.
        assert auto_row["total_damage"] == pytest.approx(auto_row["count"] * 250.0)
        # The consumed swings, on W's row, price at the modified ratio.
        assert w_row["total_damage"] == pytest.approx(swings * 1.10 * 250.0)


# ---------------------------------------------------------------------------
# E: Thundering Blow (Hammer) / Acceleration Gate (Cannon, skipped)
# ---------------------------------------------------------------------------


class TestE:
    """Hammer E is %maxHP MAGIC damage; Cannon E emits nothing."""

    def test_thundering_blow_is_magic(self, jayce_data) -> None:
        """MAGIC despite the bonus-AD scaling."""
        assert _parse(jayce_data, options=HAMMER)["E"]["damage_type"] == "magic"

    def test_thundering_blow_rank6(self, jayce_data) -> None:
        """22% x 2500 + 100% x 150 bonus AD = 700."""
        abilities = _parse(jayce_data, options=HAMMER)
        assert abilities["E"]["name"] == "Thundering Blow"
        assert abilities["E"]["total_raw"] == pytest.approx(700.0)

    def test_thundering_blow_scales_with_target_health(self, jayce_data) -> None:
        abilities = _parse(
            jayce_data, options=HAMMER, target={"target_max_health": 4000.0}
        )
        assert abilities["E"]["total_raw"] == pytest.approx(0.22 * 4000.0 + 150.0)

    def test_monster_cap_never_read_as_damage(self, jayce_data) -> None:
        """ "Capped Monster Damage" (200-700) is a monster-only clamp; at
        rank 1 the champion damage is 8% x 2500 + 150 = 350, not 200."""
        thundering_blow = jayce_data["abilities"]["E"][0]
        assert extract_value(thundering_blow, "Capped Monster Damage", 1) == 200.0
        abilities = _parse(jayce_data, level=3, options=HAMMER)
        assert abilities["E"]["total_raw"] == pytest.approx(0.08 * 2500.0 + 150.0)

    def test_thundering_blow_cooldown(self, jayce_data) -> None:
        """20 at rank 1 down to 10 at rank 6."""
        assert _parse(jayce_data, level=3, options=HAMMER)["E"][
            "cooldown"
        ] == pytest.approx(20.0)
        assert _parse(jayce_data, options=HAMMER)["E"]["cooldown"] == pytest.approx(
            10.0
        )

    def test_acceleration_gate_emits_nothing(self, jayce_data) -> None:
        """Cannon E is a pure movement-speed zone — no damage row."""
        assert "E" not in _parse(jayce_data)


# ---------------------------------------------------------------------------
# R: Transform — no rank, values step with champion level
# ---------------------------------------------------------------------------

# Champion level -> (hammer resists base, hammer auto base, cannon shred %)
R_TIERS = {
    1: (5.0, 25.0, 20.0),
    5: (5.0, 25.0, 20.0),
    6: (12.0, 60.0, 25.0),
    10: (12.0, 60.0, 25.0),
    11: (19.0, 95.0, 30.0),
    15: (19.0, 95.0, 30.0),
    16: (26.0, 130.0, 35.0),
    18: (26.0, 130.0, 35.0),
    20: (26.0, 130.0, 35.0),
}


class TestRHammer:
    """Transform Mercury Hammer: resists buff + one empowered auto."""

    def test_r_is_emitted_without_a_rank(self, jayce_data) -> None:
        """R is never leveled, so its rank is a fixed 1 and the slot must
        not gate on the skill order (which reports 0)."""
        abilities = _parse(jayce_data, options=HAMMER)
        assert abilities["R"]["name"] == "Transform Mercury Hammer"
        assert abilities["R"]["rank"] == 1

    def test_empowered_auto_damage(self, jayce_data) -> None:
        """Level 18: 130 + 30% x 150 bonus AD = 175 magic."""
        abilities = _parse(jayce_data, options=HAMMER)
        assert abilities["R"]["damage_type"] == "magic"
        assert abilities["R"]["total_raw"] == pytest.approx(175.0)

    def test_resists_stat_buff(self, jayce_data) -> None:
        """Level 18: 26 + 7.5% x 150 bonus AD = +37.25 armor AND MR."""
        buff = _parse(jayce_data, options=HAMMER)["R"]["stat_buff"]
        assert buff == {
            "armor": pytest.approx(37.25),
            "magic_resistance": pytest.approx(37.25),
        }

    def test_empowers_exactly_one_auto(self, jayce_data) -> None:
        """ "Empowers his next basic attack" means ONCE per transform."""
        assert _parse(jayce_data, options=HAMMER)["R"]["empowers_next_auto"] is True

    @pytest.mark.parametrize("level", sorted(R_TIERS))
    def test_level_tiers(self, jayce_data, level) -> None:
        resists, auto_damage, _ = R_TIERS[level]
        abilities = _parse(jayce_data, level=level, options=HAMMER)
        assert abilities["R"]["total_raw"] == pytest.approx(auto_damage + 0.30 * 150.0)
        assert abilities["R"]["stat_buff"]["armor"] == pytest.approx(
            resists + 0.075 * 150.0
        )

    def test_tier_boundaries_step(self, jayce_data) -> None:
        """The 5->6, 10->11 and 15->16 steps are the whole point of the
        breakpoint table — a flat table would pass the tier test above."""
        for lower, upper in ((5, 6), (10, 11), (15, 16)):
            low = _parse(jayce_data, level=lower, options=HAMMER)["R"]
            high = _parse(jayce_data, level=upper, options=HAMMER)["R"]
            assert high["total_raw"] > low["total_raw"]
            assert high["stat_buff"]["armor"] > low["stat_buff"]["armor"]

    def test_r_cooldown_flat_6(self, jayce_data) -> None:
        assert _parse(jayce_data, options=HAMMER)["R"]["cooldown"] == pytest.approx(6.0)
        assert _parse(jayce_data, level=1, options=HAMMER)["R"][
            "cooldown"
        ] == pytest.approx(6.0)

    def test_no_target_debuff(self, jayce_data) -> None:
        """The shred is Cannon-only."""
        assert "target_debuff" not in _parse(jayce_data, options=HAMMER)["R"]


class TestRCannon:
    """Transform Mercury Cannon: a % armor/MR shred, no damage."""

    def test_r_entry_and_zero_damage(self, jayce_data) -> None:
        abilities = _parse(jayce_data)
        assert abilities["R"]["name"] == "Transform Mercury Cannon"
        assert abilities["R"]["total_raw"] == pytest.approx(0.0)

    @pytest.mark.parametrize("level", sorted(R_TIERS))
    def test_shred_level_tiers(self, jayce_data, level) -> None:
        _, _, shred = R_TIERS[level]
        abilities = _parse(jayce_data, level=level)
        assert abilities["R"]["target_debuff"] == {
            "armor_reduction_percent": pytest.approx(shred),
            "mr_reduction_percent": pytest.approx(shred),
            "duration": pytest.approx(5.0),
        }

    def test_shred_boundaries_step(self, jayce_data) -> None:
        for lower, upper in ((5, 6), (10, 11), (15, 16)):
            low = _parse(jayce_data, level=lower)["R"]["target_debuff"]
            high = _parse(jayce_data, level=upper)["R"]["target_debuff"]
            assert high["armor_reduction_percent"] > low["armor_reduction_percent"]

    def test_no_resists_buff(self, jayce_data) -> None:
        """The armor/MR grant is Hammer-only."""
        assert "stat_buff" not in _parse(jayce_data)["R"]

    def test_r_entries_resolved_by_name_not_index(self, jayce_data) -> None:
        """R's JSON entries are ordered [0] = Cannon, [1] = Hammer —
        INVERTED relative to Q/W/E. Lock the ordering the module must not
        assume away."""
        names = [ability["name"] for ability in jayce_data["abilities"]["R"]]
        assert names == ["Transform Mercury Cannon", "Transform Mercury Hammer"]


# ---------------------------------------------------------------------------
# Passive: Hextech Capacitor (skip — movement speed only)
# ---------------------------------------------------------------------------


class TestPassive:
    """The passive is a movement-speed/ghosting buff, duplicated in JSON."""

    def test_passive_absent(self, jayce_data) -> None:
        abilities = _parse(jayce_data)
        assert "passive" not in abilities
        assert "P" not in abilities

    def test_json_has_two_identical_passive_entries(self, jayce_data) -> None:
        """P[0]/P[1] are a parser artifact, not two effects."""
        passives = jayce_data["abilities"]["P"]
        assert len(passives) == 2
        assert [effect["description"] for effect in passives[0]["effects"]] == [
            effect["description"] for effect in passives[1]["effects"]
        ]


# ---------------------------------------------------------------------------
# Champion options and stance defaults
# ---------------------------------------------------------------------------


class TestOptions:
    """Declared defaults must match the parse path's fallbacks."""

    def test_default_stance_is_cannon(self, jayce_data) -> None:
        assert _parse(jayce_data, options=None)["Q"]["name"] == "Shock Blast"
        assert _parse(jayce_data, options={})["W"]["name"] == "Hyper Charge"

    def test_stance_swaps_every_basic_slot(self, jayce_data) -> None:
        cannon = _parse(jayce_data)
        hammer = _parse(jayce_data, options=HAMMER)
        assert cannon["Q"]["name"] != hammer["Q"]["name"]
        assert cannon["W"]["name"] != hammer["W"]["name"]
        assert "E" not in cannon and hammer["E"]["name"] == "Thundering Blow"
        assert cannon["R"]["name"] != hammer["R"]["name"]


# ---------------------------------------------------------------------------
# Fight-engine integration
# ---------------------------------------------------------------------------


class TestFightIntegration:
    """Stat buffs reach the stats panel; the shred never boosts itself."""

    def test_hammer_resists_reach_champion_stats(self, jayce_data) -> None:
        """The Gnar UI-panel bug: the stats panel must follow the stance."""
        stats = dict(STATS_250_AD, armor=100.0, magic_resistance=50.0)
        abilities = _parse(jayce_data, options=HAMMER, stats=stats)
        _fight(stats, abilities)
        assert stats["armor"] == pytest.approx(137.25)
        assert stats["magic_resistance"] == pytest.approx(87.25)

    def test_cannon_leaves_resists_untouched(self, jayce_data) -> None:
        stats = dict(STATS_250_AD, armor=100.0, magic_resistance=50.0)
        abilities = _parse(jayce_data, stats=stats)
        _fight(stats, abilities)
        assert stats["armor"] == pytest.approx(100.0)
        assert stats["magic_resistance"] == pytest.approx(50.0)

    def test_cannon_shred_does_not_amplify_its_own_row(self, jayce_data) -> None:
        """The Kog'Maw rule: R's shred lands after R's own damage. R deals
        none, so its row stays 0 whatever the target's resists."""
        stats = dict(STATS_250_AD)
        abilities = _parse(jayce_data, stats=stats)
        result = calculate_fight_damage(
            stats,
            abilities,
            [],
            FightConfig(
                target_health=2500,
                target_armor=100,
                target_magic_resistance=100,
                fight_duration_seconds=5.0,
                auto_attack_uptime=0.0,
                one_rotation=True,
                deterministic=True,
            ),
        )
        assert result["breakdown"]["R"]["total_damage"] == pytest.approx(0.0)

    def test_hammer_r_row_includes_its_forced_swing(self, jayce_data) -> None:
        """With no auto stream the empowered attack lands on R's own row:
        the 175 magic bonus plus one 250 AD basic swing."""
        stats = dict(STATS_250_AD)
        abilities = _parse(jayce_data, options=HAMMER, stats=stats)
        result = _fight(stats, abilities, uptime=0.0)
        assert result["breakdown"]["R"]["total_damage"] == pytest.approx(175.0 + 250.0)

    def test_timed_fight_runs_in_both_stances(self, jayce_data) -> None:
        """Smoke test: a full timed fight with autos parses and totals."""
        for options in (CANNON, HAMMER):
            stats = dict(STATS_250_AD)
            abilities = _parse(jayce_data, options=options, stats=stats)
            result = _fight(
                stats, abilities, uptime=1.0, one_rotation=False, duration=10.0
            )
            assert result["total_damage"] > 0


class TestHyperChargeBurstAttackSpeed:
    """Hyper Charge's speed belongs to its 3 attacks, not to the fight.

    In game the buff ends when its third attack lands (~1s), so a
    fight-wide attack-speed grant would run every ordinary auto of the
    fight at the burst rate. The entry therefore declares the rate on
    ``empowers_next_auto`` — the swings it owns — and grants no
    fight-wide attack speed at all.
    """

    def test_no_fight_wide_attack_speed_buff(self, jayce_data) -> None:
        """The 360% must NOT reach champion-wide stats: it applies only
        while the 3 empowered attacks are being fired."""
        entry = _parse(jayce_data)["W"]
        assert "bonus_attack_speed" not in entry.get("stat_buff", {})

    def test_burst_rate_declared_on_the_empowered_swings(self, jayce_data) -> None:
        """``empowers_next_auto`` carries the rate its own hits fire at."""
        empower = _parse(jayce_data)["W"]["empowers_next_auto"]
        assert empower["hits"] == 3
        assert "attack_speed" in empower

    def test_burst_is_clamped_to_the_game_attack_speed_cap(self, jayce_data) -> None:
        """1.0 AS + 360% x 0.658 ratio = 3.369, past the game's 3.003 cap.

        This is why the tooltip says "maximum Attack Speed": the 360% is
        tuned to overshoot the clamp for any build.
        """
        empower = _parse(jayce_data)["W"]["empowers_next_auto"]
        assert empower["attack_speed"] == pytest.approx(ATTACK_SPEED_CAP)

    def test_burst_rate_is_base_plus_360_percent_when_under_the_cap(
        self, jayce_data
    ) -> None:
        """Below the clamp the rate is the plain attack-speed formula."""
        stats = dict(STATS_250_AD, attack_speed=0.5, attack_speed_ratio=0.2)
        empower = _parse(jayce_data, stats=stats)["W"]["empowers_next_auto"]
        assert empower["attack_speed"] == pytest.approx(0.5 + 0.2 * 3.6)

    def test_burst_frees_fight_time_for_extra_ordinary_autos(self, jayce_data) -> None:
        """W's swings fire at the cap, so they cost far less than 3 autos.

        10s fight at 1.0 AS: two W casts force 6 attacks, which at
        3.003/s occupy only 1.998s. The remaining 8.002s still runs at
        Jayce's ordinary 1.0 AS, so 8 normal autos land ALONGSIDE the 6
        empowered ones -- 14 attacks total, where a flat 1.0 AS over the
        whole fight would have produced 10.
        """
        stats = dict(STATS_250_AD, critical_strike_chance=0.0)
        abilities = _parse(jayce_data, stats=stats)
        result = _fight(stats, abilities, uptime=1.0, one_rotation=False, duration=10.0)
        breakdown = result["breakdown"]
        assert breakdown["W"]["casts"] == 2
        # 6 swings are consumed by W's row; the ordinary autos remain.
        assert breakdown["auto_attacks"]["count"] == 8
        assert breakdown["W"]["total_damage"] == pytest.approx(6 * 1.10 * 250.0)

    def test_empowered_attacks_crit(self, jayce_data) -> None:
        """They are basic attacks: crit applies to their MODIFIED damage.

        At 100% crit the 3 attacks are worth 3 x 110% AD x 2.0, not
        3 x 110% AD plus an unmodified crit bonus.
        """
        stats = dict(STATS_250_AD, critical_strike_chance=100.0)
        abilities = _parse(jayce_data, stats=stats)
        result = _fight(stats, abilities, uptime=0.0)
        assert result["breakdown"]["W"]["total_damage"] == pytest.approx(
            3 * 1.10 * 250.0 * 2.0
        )

    def test_empowered_attacks_feed_item_on_hit_counters(self, jayce_data) -> None:
        """Kraken fires every 3rd hit on ONE shared sequence, and the burst
        swings are part of it — so the extra attacks the burst buys turn
        into extra procs.

        14 attacks (8 ordinary + 6 empowered) -> 4 procs, where the same
        fight without W's re-timing would land only 10 attacks and 3.
        """
        kraken = get_item_by_name("Kraken Slayer")
        stats = dict(STATS_250_AD, critical_strike_chance=0.0)
        abilities = _parse(jayce_data, stats=stats)
        result = _fight(
            stats,
            abilities,
            uptime=1.0,
            one_rotation=False,
            duration=10.0,
            items=[kraken],
        )
        assert result["breakdown"]["on_hit_Kraken Slayer"]["count"] == 4

    def test_one_rotation_row_reports_its_attacks_and_crit(self, jayce_data) -> None:
        """One Rotation has no auto row, so the crit the empowered attacks
        are getting is invisible unless the ability row spells it out."""
        stats = dict(STATS_250_AD, critical_strike_chance=75.0)
        abilities = _parse(jayce_data, stats=stats)
        result = _fight(stats, abilities, uptime=0.0)
        detail = result["breakdown"]["W"]["detail"]
        assert "3 attacks" in detail
        assert "75% crit" in detail

    def test_burst_is_too_fast_to_reproc_spellblade(self, jayce_data) -> None:
        """Hyper Charge's 3 attacks land ~0.33s apart, so a spellblade
        charge armed during the burst can only be spent ONCE.

        Essence Reaver's 1.5s cooldown plus its 1.5s weave delay outlasts
        the whole ~1s burst; pricing the procs against the nominal
        5s rotation instead used to hand out a second one for free.
        """
        essence_reaver = get_item_by_name("Essence Reaver")
        stats = dict(STATS_250_AD, critical_strike_chance=0.0)
        abilities = _parse(jayce_data, stats=stats)
        result = _fight(stats, abilities, uptime=0.0, items=[essence_reaver])
        assert result["breakdown"]["spellblade_Essence Reaver"]["count"] == 1


class TestHyperChargeCooldownStart:
    """Hyper Charge's cooldown does not start until its 3 attacks are spent.

    Pressing W does not begin the timer — consuming the third empowered
    attack does. The burst therefore costs its own ~1s BEFORE the
    cooldown even starts, which is why a 7s fight fits two casts and not
    three. The same gap means those 3 attacks cannot refund W's own
    cooldown through Navori Flickerblade (it isn't running yet), though
    they do refund every OTHER basic ability normally.
    """

    _STATS = {
        "attack_damage": 156.0,
        "base_attack_damage": 100.0,
        "bonus_attack_damage": 56.0,
        "attack_speed": 1.137,
        "attack_speed_ratio": 0.658,
        "bonus_attack_speed": 0.0,
        "critical_strike_chance": 50.0,
        "ability_haste": 30.0,
    }

    def _run(self, jayce_data, items):
        abilities = _parse(jayce_data, level=13, stats=self._STATS)
        return calculate_fight_damage(
            dict(self._STATS),
            abilities,
            items,
            FightConfig(
                target_health=1000,
                target_armor=60,
                target_magic_resistance=60,
                fight_duration_seconds=7.0,
                auto_attack_uptime=0.8,
                deterministic=True,
            ),
        )

    def test_two_casts_in_seven_seconds_with_navori(self, jayce_data) -> None:
        """Rank 6 (5s base) at 30 haste is 3.85s, but the ~1s burst runs
        first — so the third cast falls outside a 7s fight."""
        navori = get_item_by_name("Navori Flickerblade")
        breakdown = self._run(jayce_data, [navori])["breakdown"]
        assert breakdown["W"]["casts"] == 2


class TestCannonShredDuration:
    """R's armor/MR shred lasts 5 seconds, not the rest of the fight.

    A 5s fight is fully covered, so the shred lands in full. In longer
    fights it has worn off before the later casts and autos, so it is
    applied time-weighted by the share of the fight it is actually up.
    """

    _STATS = {
        "attack_damage": 156.0,
        "base_attack_damage": 100.0,
        "bonus_attack_damage": 56.0,
        "attack_speed": 1.137,
        "attack_speed_ratio": 0.658,
        "bonus_attack_speed": 0.0,
        "critical_strike_chance": 0.0,
    }

    def _armor(self, jayce_data, duration):
        abilities = _parse(jayce_data, level=13, stats=self._STATS)
        return calculate_fight_damage(
            dict(self._STATS),
            abilities,
            [],
            FightConfig(
                target_health=100000,
                target_armor=60,
                target_magic_resistance=60,
                fight_duration_seconds=duration,
                auto_attack_uptime=0.8,
                deterministic=True,
            ),
        )["effective_armor"]

    def test_five_second_fight_gets_the_full_shred(self, jayce_data) -> None:
        """Fully covered: 60 armor - 30% = 42."""
        assert self._armor(jayce_data, 5.0) == pytest.approx(42.0)

    def test_ten_second_fight_gets_half_the_shred(self, jayce_data) -> None:
        """The 5s window covers half a 10s fight: 60 - 30%*0.5 = 51."""
        assert self._armor(jayce_data, 10.0) == pytest.approx(51.0)

    def test_r_shred_reaches_the_abilities_it_precedes(self, jayce_data) -> None:
        """Jayce transforms INTO Cannon and only then uses its abilities,
        so R's shred must be up before Q/W are priced.

        The engine's default order puts R last, where its shred reaches
        nothing but the autos. Jayce declares his own order instead.
        """
        order = get_champion_cast_order("Jayce")
        assert order is not None
        assert order[0] == "R"

    def test_shredded_q_hits_harder_than_unshredded(self, jayce_data) -> None:
        """Same fight, R's shred before vs after Q: Q must feel it."""
        abilities = _parse(jayce_data, level=13, stats=self._STATS)
        config = dict(
            target_health=100000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=5.0,
            auto_attack_uptime=0.0,
            deterministic=True,
        )
        r_first = calculate_fight_damage(
            dict(self._STATS),
            abilities,
            [],
            FightConfig(cast_order=["R", "Q", "W", "E"], **config),
        )
        r_last = calculate_fight_damage(
            dict(self._STATS),
            abilities,
            [],
            FightConfig(cast_order=["Q", "W", "E", "R"], **config),
        )
        assert (
            r_first["breakdown"]["Q"]["total_damage"]
            > r_last["breakdown"]["Q"]["total_damage"]
        )
