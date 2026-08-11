"""Tests for the Corki slot map (src.calculator.champions.corki).

Hand-validated against the wiki at known ranks with round stats, plus
the cross-checks that keep the module's hardcoded constants honest: the
passive's 20% ratio has no JSON home at all, and W/E's tick counts and
E's total shred must stay consistent with the JSON attributes they are
derived from.
"""

import pytest

from src.calculator.champions import corki
from src.calculator.champions.slotlib import extract_named, extract_value
from src.calculator.damage import (
    FightConfig,
    Resists,
    _ability_mr,
    calculate_fight_damage,
)
from src.calculator.data_fetcher import get_item_by_name
from src.calculator.interpreters import resistance_shred
from src.calculator.item_behavior import Resistance
from src.calculator.pipeline import FightParams, run_fight
from src.calculator.resistance import apply_resistance

# Round stats so wiki arithmetic is checkable by eye.
_STATS = {
    "attack_damage": 200.0,
    "base_attack_damage": 100.0,
    "bonus_attack_damage": 100.0,
    "ability_power": 0.0,
    "attack_speed": 1.0,
    "attack_speed_ratio": 0.625,
    "critical_strike_chance": 0.0,
    "ability_haste": 0.0,
    "basic_ability_haste": 0.0,
    "magic_penetration_flat": 0.0,
    "magic_penetration_percent": 0.0,
    "flat_armor_penetration": 0.0,
    "armor_penetration_percent": 0.0,
    "max_mana": 500.0,
    "bonus_mana": 0.0,
    "health": 2000.0,
    "bonus_health": 0.0,
    "is_melee": False,
    "level": 18,
}
_RANKS = {"Q": 5, "W": 3, "E": 1, "R": 2}


def _parse(corki_data, *, level=18, ranks=None, options=None, stats=None):
    """Parse Corki at explicit ranks with the round test stats."""
    return corki.parse_abilities(
        corki_data,
        level,
        (stats or _STATS)["ability_power"],
        ranks or _RANKS,
        champion_options=options,
        champion_stats=dict(stats or _STATS),
        target_stats={"target_max_health": 2000.0},
    )


class TestAbilityValues:
    """Hand-validated raw damage against the wiki at 100 bonus AD, 0 AP."""

    def test_q_rank_5(self, corki_data) -> None:
        """240 base + 125% bonus AD = 365 magic."""
        abilities = _parse(corki_data)
        assert abilities["Q"]["damage_type"] == "magic"
        assert abilities["Q"]["total_raw"] == pytest.approx(365.0)

    def test_w_rank_3_is_the_total_not_one_tick(self, corki_data) -> None:
        """300 base + 200% bonus AD = 500 magic over 5 ticks (100/tick)."""
        abilities = _parse(corki_data)
        assert abilities["W"]["damage_type"] == "magic"
        assert abilities["W"]["total_raw"] == pytest.approx(500.0)

    def test_e_rank_1_is_the_total_not_one_tick(self, corki_data) -> None:
        """80 base + 240% bonus AD = 320 physical over 16 ticks (20/tick)."""
        abilities = _parse(corki_data)
        assert abilities["E"]["damage_type"] == "physical"
        assert abilities["E"]["total_raw"] == pytest.approx(320.0)

    def test_r_missiles_rank_2(self, corki_data) -> None:
        """Regular 170 + 85% bAD = 255; Big One is exactly double = 510."""
        abilities = _parse(corki_data)
        amounts = {part.amount for part in abilities["R"]["parts"]}
        assert amounts == {255.0, 510.0}
        assert abilities["R"]["damage_type"] == "physical"

    def test_ap_scaling_reaches_q_and_w_only(self, corki_data) -> None:
        """Q +100% AP, W +150% AP; E and R are AD-only."""
        stats = dict(_STATS, ability_power=100.0)
        with_ap = _parse(corki_data, stats=stats)
        without = _parse(corki_data)
        assert with_ap["Q"]["total_raw"] - without["Q"]["total_raw"] == pytest.approx(
            100.0
        )
        assert with_ap["W"]["total_raw"] - without["W"]["total_raw"] == pytest.approx(
            150.0
        )
        assert with_ap["E"]["total_raw"] == pytest.approx(without["E"]["total_raw"])
        assert with_ap["R"]["total_raw"] == pytest.approx(without["R"]["total_raw"])


class TestCooldowns:
    """Every castable slot carries a cooldown; R's is the recharge."""

    def test_basic_ability_cooldowns(self, corki_data) -> None:
        abilities = _parse(corki_data)
        assert abilities["Q"]["cooldown"] == pytest.approx(7.0)  # rank 5
        assert abilities["W"]["cooldown"] == pytest.approx(16.0)  # rank 3
        assert abilities["E"]["cooldown"] == pytest.approx(12.0)  # flat

    def test_r_uses_recharge_not_the_inter_cast_cooldown(self, corki_data) -> None:
        """The JSON ``cooldown`` (2s) is the inter-cast timer; the limiter
        on sustained use is ``rechargeRate`` (20s) — the Amumu rule."""
        abilities = _parse(corki_data)
        assert abilities["R"]["cooldown"] == pytest.approx(20.0)


class TestJsonCrossChecks:
    """The module's hardcoded constants must stay true to the JSON."""

    def test_w_tick_count_matches_total_over_per_tick(self, corki_data) -> None:
        ability = corki_data["abilities"]["W"][0]
        total = extract_named(ability, "Total Magic Damage", 3)
        per_tick = extract_named(ability, "Magic Damage Per Tick", 3)
        assert total / per_tick == pytest.approx(corki._W_TICKS)

    def test_e_tick_count_matches_total_over_per_tick(self, corki_data) -> None:
        ability = corki_data["abilities"]["E"][0]
        total = extract_named(ability, "Total Physical Damage", 1)
        per_tick = extract_named(ability, "Physical Damage Per Tick", 1)
        assert total / per_tick == pytest.approx(corki._E_TICKS)

    def test_e_total_shred_is_four_stacks_worth(self, corki_data) -> None:
        """ "Total Resistances Reduction" == per-stack x the 4-stack cap."""
        ability = corki_data["abilities"]["E"][0]
        for rank in range(1, 6):
            per_stack = extract_value(ability, "Resistances Reduction Per Stack", rank)
            total = extract_value(ability, "Total Resistances Reduction", rank)
            assert per_stack * corki._E_MAX_SHRED_STACKS == pytest.approx(total)

    def test_passive_has_no_leveling_data_at_all(self, corki_data) -> None:
        """The 20% ratio is a module constant precisely because of this."""
        passive = corki_data["abilities"]["P"][0]
        assert passive["effects"][0]["leveling"] == []
        assert "20% AD" in passive["effects"][0]["description"]

    def test_r_recharge_rate_is_twenty_at_every_rank(self, corki_data) -> None:
        assert corki_data["abilities"]["R"][0]["rechargeRate"] == [20, 20, 20]


class TestPassive:
    """Hextech Munitions rides the auto stream as a true-damage share."""

    def test_emits_both_true_damage_riders_from_one_constant(self, corki_data) -> None:
        """One wiki ratio, two consumers: the swing and its spellblade proc."""
        passive = _parse(corki_data)["passive"]
        assert passive["basic_attack_true_ratio"] == pytest.approx(0.20)
        assert passive["spellblade_bonus_true_ratio"] == pytest.approx(0.20)
        assert passive["name"] == "Hextech Munitions"
        assert passive["total_raw"] == 0.0  # priced per attack by the engine

    def test_true_damage_is_twenty_percent_of_total_ad(self, corki_data) -> None:
        """8 autos of 200 AD -> 8 x 40 = 320 unmitigated true damage."""
        abilities = _parse(corki_data)
        result = calculate_fight_damage(
            dict(_STATS),
            {"passive": abilities["passive"]},
            [],
            FightConfig(
                target_health=5000.0,
                target_armor=100.0,
                target_magic_resistance=100.0,
                fight_duration_seconds=8.0,
                auto_attack_uptime=1.0,
                one_rotation=False,
                deterministic=True,
            ),
        )
        row = result["breakdown"]["auto_attacks_true_damage"]
        assert row["damage_type"] == "true"
        assert row["count"] == 8
        assert row["total_damage"] == pytest.approx(320.0)

    def test_crit_multiplies_the_true_instance(self, corki_data) -> None:
        """ "Affected by critical strike modifiers": at 100% crit the rider
        doubles with the swing (expected-value crit in deterministic mode)."""
        abilities = _parse(corki_data)
        stats = dict(_STATS, critical_strike_chance=100.0)
        result = calculate_fight_damage(
            stats,
            {"passive": abilities["passive"]},
            [],
            FightConfig(
                target_health=5000.0,
                target_armor=100.0,
                target_magic_resistance=100.0,
                fight_duration_seconds=8.0,
                auto_attack_uptime=1.0,
                one_rotation=False,
                deterministic=True,
            ),
        )
        row = result["breakdown"]["auto_attacks_true_damage"]
        assert row["total_damage"] == pytest.approx(640.0)

    def test_basic_damage_amplifiers_apply_to_the_true_instance(
        self, corki_data
    ) -> None:
        """The wiki: "Both instances deal basic damage", so Hexoptics amps
        the true half exactly as it amps the physical one."""
        abilities = _parse(corki_data)
        config = FightConfig(
            target_health=5000.0,
            target_armor=100.0,
            target_magic_resistance=100.0,
            fight_duration_seconds=8.0,
            auto_attack_uptime=1.0,
            one_rotation=False,
            deterministic=True,
        )
        entries = {"passive": abilities["passive"]}
        plain = calculate_fight_damage(dict(_STATS), entries, [], config)
        hexoptics = get_item_by_name("Hexoptics C44")
        amped = calculate_fight_damage(dict(_STATS), entries, [hexoptics], config)

        plain_true = plain["breakdown"]["auto_attacks_true_damage"]["total_damage"]
        amped_true = amped["breakdown"]["auto_attacks_true_damage"]["total_damage"]
        # Same AD both runs (Hexoptics grants no AD), so the whole delta
        # is the amp, and it matches the autos' own multiplier.
        auto_ratio = (
            amped["breakdown"]["auto_attacks"]["total_damage"]
            / plain["breakdown"]["auto_attacks"]["total_damage"]
        )
        assert amped_true / plain_true == pytest.approx(auto_ratio)
        assert amped_true > plain_true

    def test_no_autos_means_no_true_damage_row(self, corki_data) -> None:
        abilities = _parse(corki_data)
        result = calculate_fight_damage(
            dict(_STATS),
            {"passive": abilities["passive"]},
            [],
            FightConfig(
                target_health=5000.0,
                target_armor=100.0,
                target_magic_resistance=100.0,
                fight_duration_seconds=5.0,
                auto_attack_uptime=0.0,
                one_rotation=True,
                deterministic=True,
            ),
        )
        assert "auto_attacks_true_damage" not in result["breakdown"]


class TestGatlingGunShred:
    """E's flat armor/MR shred, ramped one stack per tick."""

    def test_declares_a_flat_shred_of_four_stacks(self, corki_data) -> None:
        entry = _parse(corki_data)["E"]
        debuff = entry["target_debuff"]
        assert debuff["armor_reduction_flat"] == pytest.approx(12.0)  # 3 x 4, rank 1
        assert debuff["mr_reduction_flat"] == pytest.approx(12.0)
        assert debuff["stacks"] == 4

    def test_ticks_are_one_part_the_engine_ramps_per_hit(self, corki_data) -> None:
        """The module declares ticks; the engine owns the stack staging."""
        parts = _parse(corki_data)["E"]["parts"]
        assert len(parts) == 1
        assert parts[0].count == 16
        assert parts[0].amount == pytest.approx(20.0)

    def test_own_later_ticks_land_against_the_shred(self, corki_data) -> None:
        """Deliberate deviation from the Kog'Maw rule: ticks 2-16 benefit."""
        abilities = _parse(corki_data)
        result = calculate_fight_damage(
            dict(_STATS),
            {"E": abilities["E"]},
            [],
            FightConfig(
                target_health=5000.0,
                target_armor=100.0,
                target_magic_resistance=100.0,
                fight_duration_seconds=5.0,
                auto_attack_uptime=0.0,
                one_rotation=True,
                deterministic=True,
            ),
        )
        # Ticks land at 100/97/94/91 armor, then 12 ticks at 88.
        expected = (
            sum(20.0 * 100.0 / (100.0 + armor) for armor in (100.0, 97.0, 94.0, 91.0))
            + 12 * 20.0 * 100.0 / 188.0
        )
        assert result["breakdown"]["E"]["total_damage"] == pytest.approx(expected)
        assert result["effective_armor"] == pytest.approx(88.0)

    def test_mr_reduction_item_never_helps_a_negative_mr_target(
        self, corki_data
    ) -> None:
        """Bloodletter's Vile Decay is a PERCENT reduction. Against MR that
        E already drove negative it must do nothing — scaling a negative
        toward zero would make an MR-shred item lower Corki's damage."""
        resists = Resists(
            magic_pen_flat=0.0,
            magic_pen_percent=0.0,
            armor_pen_percent=0.0,
            flat_armor_pen=0.0,
            has_terminus=False,
            terminus_stat_pen=0.0,
            terminus_avg_pen=0.0,
            target_armor=100.0,
            base_mr=5.0,
            reduced_mr=5.0,
            malignance_mr_reduction=0.0,
            bc_reduction=0.0,
            mr_shred=resistance_shred.resolve_slot(
                ["Bloodletter's Curse"],
                Resistance.MAGIC_RESIST,
                level=18,
                fight_duration_seconds=5.0,
                target_bonus_health=0.0,
                holder_is_melee=False,
            ),
        )
        resists.resolve_magic()
        resists.resolve_armor()
        resists.shred_mr(reduction_flat=12.0)  # Corki E rank 1: 5 -> -7
        assert resists.base_mr == pytest.approx(-7.0)

        damage = [
            apply_resistance(100.0, _ability_mr(resists, False, stacks))
            for stacks in range(4)
        ]
        assert damage == sorted(damage), "more shred stacks must never deal less"
        assert damage[-1] == pytest.approx(damage[0])

    def test_shred_can_push_resistances_below_zero(self, corki_data) -> None:
        abilities = _parse(corki_data)
        result = calculate_fight_damage(
            dict(_STATS),
            {"E": abilities["E"]},
            [],
            FightConfig(
                target_health=5000.0,
                target_armor=5.0,
                target_magic_resistance=5.0,
                fight_duration_seconds=5.0,
                auto_attack_uptime=0.0,
                one_rotation=True,
                deterministic=True,
            ),
        )
        assert result["effective_armor"] == pytest.approx(-7.0)
        assert result["effective_mr"] == pytest.approx(-7.0)


class TestDotDurations:
    """Item burns must stretch through W's patch and E's cone."""

    def test_w_and_e_declare_their_tick_tails(self, corki_data) -> None:
        abilities = _parse(corki_data)
        assert abilities["W"]["dot_duration"] == pytest.approx(2.5)
        assert abilities["E"]["dot_duration"] == pytest.approx(4.0)

    def test_w_and_e_declare_their_sourced_tick_cadence(self, corki_data) -> None:
        """W ticks every 0.5s and E every 0.25s (wiki, test-locked via
        Total / Per-Tick above); the engine authors tick events from them."""
        abilities = _parse(corki_data)
        assert abilities["W"]["dot_tick_interval"] == pytest.approx(0.5)
        assert abilities["E"]["dot_tick_interval"] == pytest.approx(0.25)

    def test_partial_uptime_scales_the_window_not_the_cadence(self, corki_data) -> None:
        partial = _parse(corki_data, options={"w_patch_uptime": 0.4})["W"]
        assert partial["dot_duration"] == pytest.approx(1.0)
        assert partial["dot_tick_interval"] == pytest.approx(0.5)


class TestOptions:
    """Every declared option changes the parse."""

    def test_w_patch_uptime_scales_ticks_and_tail(self, corki_data) -> None:
        half = _parse(corki_data, options={"w_patch_uptime": 0.4})["W"]
        assert half["total_raw"] == pytest.approx(200.0)  # 2 of 5 ticks
        assert half["dot_duration"] == pytest.approx(1.0)

    def test_e_cone_uptime_scales_ticks_and_shred_stacks(self, corki_data) -> None:
        """2 ticks -> 2 stacks of shred, and only 2 ticks of damage."""
        partial = _parse(corki_data, options={"e_cone_uptime": 0.125})["E"]
        assert partial["total_raw"] == pytest.approx(40.0)
        assert partial["target_debuff"]["stacks"] == 2
        assert partial["target_debuff"]["armor_reduction_flat"] == pytest.approx(6.0)

    def test_e_cone_uptime_zero_drops_damage_and_shred(self, corki_data) -> None:
        empty = _parse(corki_data, options={"e_cone_uptime": 0.0})["E"]
        assert empty["total_raw"] == 0.0
        assert "target_debuff" not in empty

    def test_r_starting_charges_sets_the_burst_missile_count(self, corki_data) -> None:
        for charges in range(corki._R_MAX_CHARGES + 1):
            entry = _parse(corki_data, options={"r_starting_charges": charges})["R"]
            assert sum(part.count for part in entry["parts"]) == charges

    def test_r_starting_charges_zero_emits_an_empty_ultimate(self, corki_data) -> None:
        entry = _parse(corki_data, options={"r_starting_charges": 0})["R"]
        assert entry["total_raw"] == 0.0
        assert entry["parts"] == ()

    def test_big_one_cadence_is_every_third_missile(self, corki_data) -> None:
        """4 missiles from a fresh cycle -> 1 Big One (the 3rd)."""
        entry = _parse(corki_data)["R"]
        counts = {part.amount: part.count for part in entry["parts"]}
        assert counts == {255.0: 3, 510.0: 1}

    def test_cycle_position_pulls_the_big_one_forward(self, corki_data) -> None:
        """Two missiles already fired: the very next one is a Big One, and
        the 4-missile burst carries 2 of them."""
        entry = _parse(corki_data, options={"r_big_one_cycle_position": 2})["R"]
        counts = {part.amount: part.count for part in entry["parts"]}
        assert counts == {255.0: 2, 510.0: 2}


class TestMissileEconomy:
    """R's charges, recharge, and auto-driven recharge acceleration."""

    @staticmethod
    def _missiles(entry) -> int:
        return sum(part.count for part in entry["parts"])

    def test_timed_fight_adds_recharged_missiles(self, corki_data) -> None:
        """0 stored, 10s, no autos: 10s of a 20s recharge is not a charge."""
        entry = _parse(
            corki_data,
            options={
                "r_starting_charges": 0,
                "fight_duration_seconds": 10.0,
                "auto_attack_uptime": 0.0,
            },
        )["R"]
        assert self._missiles(entry) == 0

    def test_autos_accelerate_the_recharge(self, corki_data) -> None:
        """0 stored, 10s, 10 autos at 0% crit: 10 + 10x2 = 30s -> 1 charge."""
        entry = _parse(
            corki_data,
            options={
                "r_starting_charges": 0,
                "fight_duration_seconds": 10.0,
                "auto_attack_uptime": 1.0,
            },
        )["R"]
        assert self._missiles(entry) == 1

    def test_crit_chance_raises_the_per_auto_reduction(self, corki_data) -> None:
        """At 100% crit each auto cuts 6s: 10 + 10x6 = 70s -> 3 charges."""
        entry = _parse(
            corki_data,
            stats=dict(_STATS, critical_strike_chance=100.0),
            options={
                "r_starting_charges": 0,
                "fight_duration_seconds": 10.0,
                "auto_attack_uptime": 1.0,
            },
        )["R"]
        assert self._missiles(entry) == 3

    def test_trigger_cycle_caps_the_barrage(self, corki_data) -> None:
        """Full ammo + recharge over 5s still fits only 1 + 5/2.175 = 3."""
        entry = _parse(
            corki_data,
            stats=dict(_STATS, critical_strike_chance=100.0),
            options={
                "fight_duration_seconds": 5.0,
                "auto_attack_uptime": 1.0,
            },
        )["R"]
        assert self._missiles(entry) == 3

    def test_detail_row_explains_the_count(self, corki_data) -> None:
        entry = _parse(
            corki_data,
            options={"fight_duration_seconds": 8.0, "auto_attack_uptime": 1.0},
        )["R"]
        assert "missile(s) incl." in entry["detail"]
        assert "Big One" in entry["detail"]


class TestSpellbladeRider:
    """Spellblade procs carry the 20% pre-mitigation true-damage rider."""

    @staticmethod
    def _fight(corki_data, items):
        params = FightParams(
            target_health=2000.0,
            target_bonus_health=0.0,
            target_armor=100.0,
            target_magic_resistance=100.0,
            fight_duration_seconds=8.0,
            auto_attack_uptime=1.0,
            one_rotation=False,
            include_actives=True,
            cast_order=None,
            auto_attacks_only=False,
            deterministic=True,
        )
        return run_fight(corki_data, 13, items, params)

    def test_rider_is_a_fifth_of_the_proc_pre_mitigation(self, corki_data) -> None:
        result = self._fight(corki_data, [get_item_by_name("Trinity Force")])
        breakdown = result["breakdown"]
        proc = breakdown["spellblade_Trinity Force"]
        rider = breakdown["spellblade_Trinity Force_bonus_true"]
        assert rider["damage_type"] == "true"
        assert rider["count"] == proc["count"]
        # The proc is physical (mitigated by the post-E-shred armor); the
        # rider is 20% of the PRE-mitigation proc and takes no mitigation.
        unmitigate = (100.0 + result["effective_armor"]) / 100.0
        assert rider["damage_per_hit"] == pytest.approx(
            proc["damage_per_hit"] * unmitigate * 0.20
        )

    def test_no_spellblade_item_means_no_rider(self, corki_data) -> None:
        result = self._fight(corki_data, [])
        assert not any("_bonus_true" in key for key in result["breakdown"])

    def test_rider_counts_as_auto_attack_damage(self, corki_data) -> None:
        """It rides the attack that consumes the charge, like the proc."""
        result = self._fight(corki_data, [get_item_by_name("Trinity Force")])
        rider = result["breakdown"]["spellblade_Trinity Force_bonus_true"]
        assert rider["total_damage"] > 0
        assert result["damage_by_type"]["true"] >= rider["total_damage"]
