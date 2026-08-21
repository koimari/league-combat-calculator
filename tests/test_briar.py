"""Briar champion module tests.

Hand-validated against https://wiki.leagueoflegends.com/en-us/Briar
- P (Crimson Curse): hit-driven stacking bleed — single stack 10-50 by
  level (+50% bonus AD) physical over 5s; max 5 stacks, extra stacks at
  25%; every attack/ability application adds one and refreshes.
- Q (Head Rush): 60/85/110/135/160 (+80% bonus AD)(+60% AP) physical,
  cd 13-9; 10-20% armor AND magic resist shred; applies item on-hits.
- W (Blood Frenzy): +55-95% attack speed, +24-60% movement speed.
  W recast (Snack Attack): empowered auto, 5-65 (+5% AD)
  (+[9% +2.5% per 100 bonus AD] of target's missing health) physical.
- E (Chilling Scream, full charge): 80-220 (+100% bonus AD)(+100% AP)
  magic, cd 16; wall collision adds 140-440 (+240% bAD)(+240% AP).
- R (Certain Death): 150/250/350 (+130% AP) magic, cd 120/100/80;
  +20% total AD armor and MR, 10-20% life steal, 10-30% move speed.
"""

import pytest

from src.calculator.champions import parse_champion_abilities
from src.calculator.champions.slotlib import extract_named, extract_value
from src.calculator.pipeline import FightParams, run_fight
from src.calculator.stats import calculate_total_stats
from src.calculator.champions import briar
from tests import cc_review

# Rank pins for hand-math tests (independent of level/skill order).
MAX_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 2}


def _parse(briar_data, level=18, *, options=None, ranks=MAX_RANKS, **stat_overrides):
    """Parse Briar with crafted stats (deterministic hand-math inputs)."""
    champion_stats = {
        "ability_haste": 0.0,
        "ability_power": 0.0,
        "armor_penetration_bonus_percent": 0.0,
        "armor_penetration_percent": 0.0,
        "basic_ability_haste": 0.0,
        "bonus_health": 0.0,
        "bonus_mana": 0.0,
        "critical_strike_chance": 0.0,
        "flat_armor_penetration": 0.0,
        "is_melee": True,
        "lethality": 0.0,
        "level": 1,
        "magic_penetration_flat": 0.0,
        "magic_penetration_percent": 0.0,
        "max_mana": 0.0,
        "move_speed": 0.0,
        "omnivamp_percent": 0.0,
        "resource_regen_per_second": 0.0,
        "ultimate_haste": 0.0,
        "attack_damage": 200.0,
        "base_attack_damage": 100.0,
        "bonus_attack_damage": 100.0,
        "health": 2000.0,
        "attack_speed": 1.0,
        "attack_speed_ratio": 0.644,
    }
    champion_stats.update(stat_overrides)
    ap = champion_stats.pop("ability_power", 0.0)
    return parse_champion_abilities(
        briar_data,
        level,
        ap,
        ability_ranks=ranks,
        champion_stats=champion_stats,
        champion_options=options,
        target_stats={
            "target_max_health": 3000.0,
            "target_current_health": 3000.0,
            "target_missing_health": 0.0,
        },
    )


def _fight_params(**overrides):
    """FightParams for a default one-rotation fight, field-overridable."""
    config = {
        "target_health": 1000.0,
        "target_bonus_health": 0.0,
        "target_armor": 0.0,
        "target_magic_resistance": 0.0,
        "fight_duration_seconds": 5.0,
        "auto_attack_uptime": 0.0,
        "one_rotation": True,
        "include_actives": True,
        "cast_order": None,
        "auto_attacks_only": False,
        "ability_ranks": None,
        "champion_options": None,
        "deterministic": True,
    }
    config.update(overrides)
    return FightParams(**config)


class TestCrimsonCurse:
    """P: single-stack bleed value + the stacking_dot declaration."""

    def test_single_stack_level18_with_100_bonus_ad(self, briar_data):
        """Reference: level 18, 100 bonus AD -> 50 + 50 = 100 over 5s."""
        passive = _parse(briar_data, 18)["passive"]
        assert passive["damage_type"] == "physical"
        dot = passive["stacking_dot"]
        assert dot["single_stack_raw"] == pytest.approx(100.0)
        assert dot["duration"] == 5.0
        assert dot["max_stacks"] == 5
        assert dot["extra_stack_effectiveness"] == 0.25
        assert dot["applied_by_autos"] is True
        assert dot["damage_type"] == "physical"

    def test_single_stack_level1(self, briar_data):
        """Level 1: 10 base + 50% of 100 bonus AD = 60."""
        passive = _parse(briar_data, 1, ranks=None)["passive"]
        assert passive["stacking_dot"]["single_stack_raw"] == pytest.approx(60.0)

    def test_level_scaling_clamps_past_18(self, briar_data):
        """Wiki defines 1-18; repo levels 19-20 clamp at the 18 value."""
        at_18 = _parse(briar_data, 18)["passive"]["stacking_dot"]
        at_20 = _parse(briar_data, 20)["passive"]["stacking_dot"]
        assert at_20["single_stack_raw"] == at_18["single_stack_raw"]

    def test_json_per_tick_array_matches_formula(self, briar_data):
        """JSON cross-check: the first per-level array is the single-stack
        flat base (10 -> 50); the 5-stack window total array (leveling[4])
        is exactly 2x it (values are wiki-rounded to 2 decimals)."""
        passive_json = briar_data["abilities"]["P"][0]
        five_stack = passive_json["effects"][0]["leveling"][4]["modifiers"][0]
        for level in range(1, 19):
            flat_base = 10.0 + 40.0 * (level - 1) / 17.0
            assert extract_value(
                passive_json, "Per-Level Scaling", level
            ) == pytest.approx(flat_base, abs=0.01)
            assert five_stack["values"][level - 1] == pytest.approx(
                2.0 * flat_base, abs=0.01
            )


class TestHeadRush:
    """Q: physical damage + on-hit carrier + resistance shred."""

    def test_rank5_reference_damage(self, briar_data):
        """Reference: rank 5, 100 bonus AD, 0 AP -> 160 + 80 = 240."""
        q = _parse(briar_data, 18)["Q"]
        assert q["rank"] == 5
        assert q["damage_type"] == "physical"
        assert q["total_raw"] == pytest.approx(240.0)
        assert q["cooldown"] == pytest.approx(9.0)

    def test_rank1_with_ap(self, briar_data):
        """Rank 1, 100 bonus AD, 100 AP: 60 + 80 + 60 = 200; cd 13."""
        q = _parse(briar_data, 18, ranks={"Q": 1}, ability_power=100.0)["Q"]
        assert q["total_raw"] == pytest.approx(200.0)
        assert q["cooldown"] == pytest.approx(13.0)

    def test_shred_debuff(self, briar_data):
        """20% armor AND MR shred at rank 5 (10% at rank 1)."""
        q5 = _parse(briar_data, 18)["Q"]
        assert q5["target_debuff"] == {
            "armor_reduction_percent": 20.0,
            "mr_reduction_percent": 20.0,
            "duration": 5.0,
        }
        q1 = _parse(briar_data, 18, ranks={"Q": 1})["Q"]
        assert q1["target_debuff"]["armor_reduction_percent"] == 10.0

    def test_applies_item_on_hits_as_attack(self, briar_data):
        """Q applies item on-hits at 100% and counts as an attack
        (advances on-hit counters AND on-attack cadences)."""
        q = _parse(briar_data, 18)["Q"]
        assert q["applies_item_on_hits"] == {
            "effectiveness": 1.0,
            "hits": 1,
            "triggers": ("on_hit", "on_attack"),
        }
        assert q["applies_dot_stack"] is True


class TestBloodFrenzy:
    """W buff: zero-damage attack/move speed steroid, option-gated."""

    def test_rank5_stat_buff(self, briar_data):
        """+95% bonus attack speed and +60% movement speed at rank 5."""
        frenzy = _parse(briar_data, 18)["W_frenzy"]
        assert frenzy["total_raw"] == 0.0
        assert frenzy["stat_buff"] == {
            "bonus_attack_speed": 95.0,
            "movement_speed_percent": 60.0,
        }
        assert frenzy["cooldown"] == pytest.approx(10.0)

    def test_rank1_stat_buff(self, briar_data):
        frenzy = _parse(briar_data, 18, ranks={"W": 1})["W_frenzy"]
        assert frenzy["stat_buff"]["bonus_attack_speed"] == 55.0
        assert frenzy["stat_buff"]["movement_speed_percent"] == 24.0

    def test_toggle_off_drops_frenzy_and_snack(self, briar_data):
        """blood_frenzy_active=False: no buff AND no Snack Attack
        (it only exists during the frenzy)."""
        abilities = _parse(briar_data, 18, options={"blood_frenzy_active": False})
        assert "W_frenzy" not in abilities
        assert "W" not in abilities


class TestSnackAttack:
    """W recast: empowered next auto with missing-health scaling."""

    def test_rank5_reference_damage(self, briar_data):
        """Reference: rank 5, 200 total AD (100 bonus), 3000 max HP at
        50% missing: 65 + 10 + (0.09 + 0.025) x 1500 = 247.5."""
        w = _parse(briar_data, 18)["W"]
        assert w["name"] == "Snack Attack"
        assert w["damage_type"] == "physical"
        assert w["total_raw"] == pytest.approx(247.5)
        assert w["empowers_next_auto"] is True
        assert w["applies_dot_stack"] is True
        assert w["cooldown"] == pytest.approx(10.0)

    def test_missing_hp_option_drives_the_scaling(self, briar_data):
        """target_missing_hp_pct=0 leaves only 65 + 5% AD = 75."""
        w = _parse(briar_data, 18, options={"target_missing_hp_pct": 0})["W"]
        assert w["total_raw"] == pytest.approx(75.0)

    def test_bonus_ad_raises_the_missing_hp_ratio(self, briar_data):
        """+2.5% per 100 bonus AD: at 200 bonus AD (300 total) the ratio
        is 9% + 5% = 14% of 1500 missing -> 65 + 15 + 210 = 290."""
        w = _parse(
            briar_data,
            18,
            attack_damage=300.0,
            bonus_attack_damage=200.0,
        )["W"]
        assert w["total_raw"] == pytest.approx(65.0 + 15.0 + 0.14 * 1500.0)


class TestChillingScream:
    """E: fully-charged magic AoE with the wall-collision option."""

    def test_rank5_reference_damage(self, briar_data):
        """Reference: rank 5 full charge, 100 bonus AD, 0 AP -> 320."""
        e = _parse(briar_data, 18)["E"]
        assert e["rank"] == 5
        assert e["damage_type"] == "magic"
        assert e["total_raw"] == pytest.approx(320.0)
        assert e["cooldown"] == pytest.approx(16.0)
        assert e["applies_dot_stack"] is True

    def test_wall_collision_adds_bonus_damage(self, briar_data):
        """Reference: wall toggle ON adds 440 + 240 -> 1000 total."""
        e = _parse(briar_data, 18, options={"e_wall_collision": True})["E"]
        assert e["total_raw"] == pytest.approx(1000.0)

    def test_json_total_equals_maximum_plus_bonus(self, briar_data):
        """JSON cross-check: 'Total Magic Damage' == Maximum + Bonus at
        every rank (with live AD/AP scalings resolved)."""
        e_json = briar_data["abilities"]["E"][0]
        stats = {"bonus_attack_damage": 100.0, "ability_power": 150.0}
        for rank in range(1, 6):
            combined = extract_named(
                e_json, "Maximum Magic Damage", rank, stats
            ) + extract_named(e_json, "Bonus Magic Damage", rank, stats)
            total = extract_named(e_json, "Total Magic Damage", rank, stats)
            assert combined == pytest.approx(total)


class TestCertainDeath:
    """R: magic damage + armor/MR/life-steal/move-speed stat buffs."""

    def test_rank2_reference_damage(self, briar_data):
        """Reference: rank 2, 0 AP -> 250 magic; cd 100."""
        r = _parse(briar_data, 18)["R"]
        assert r["rank"] == 2
        assert r["damage_type"] == "magic"
        assert r["total_raw"] == pytest.approx(250.0)
        assert r["cooldown"] == pytest.approx(100.0)
        assert r["applies_dot_stack"] is True

    def test_ap_ratio_is_130_percent(self, briar_data):
        r = _parse(briar_data, 18, ability_power=100.0)["R"]
        assert r["total_raw"] == pytest.approx(380.0)

    def test_stat_buffs(self, briar_data):
        """Armor and MR +20% of 200 total AD = 40 each; 15% life steal
        and +20% movement speed at rank 2."""
        r = _parse(briar_data, 18)["R"]
        assert r["stat_buff"] == {
            "armor": pytest.approx(40.0),
            "magic_resistance": pytest.approx(40.0),
            "life_steal": 15.0,
            "movement_speed_percent": 20.0,
        }


class TestSkillOrder:
    """Briar maxes W > Q > E (R at 6/11/16)."""

    def test_ranks_at_level_9(self, briar_data):
        abilities = _parse(briar_data, 9, ranks=None)
        assert abilities["W"]["rank"] == 5
        assert abilities["Q"]["rank"] == 2
        assert abilities["E"]["rank"] == 1
        assert abilities["R"]["rank"] == 1


class TestFightIntegration:
    """The parsed entries drive the fight engine end to end."""

    def test_one_rotation_bleed_is_175_percent_of_single_stack(self, briar_data):
        """Q + Snack + E + R = 4 marginal applications: 1.75x the single
        stack (50 raw at level 18 with no items) against 0 armor."""
        result = run_fight(briar_data, 18, [], _fight_params())
        row = result["breakdown"]["stacking_dot_passive"]
        assert row["count"] == 4
        assert row["unit"] == "stacks"
        assert row["total_damage"] == pytest.approx(1.75 * 50.0)
        assert row["damage_events"]
        assert "stacking_dot_passive" in result["timeline_coverage"]["exact_sources"]

    def test_one_rotation_w_row_is_base_swing_plus_bonus(self, briar_data):
        """No auto stream in one-rotation mode: the engine appends the
        consumed basic attack to the Snack Attack row (swing + bonus)."""
        result = run_fight(briar_data, 4, [], _fight_params())
        stats = calculate_total_stats(briar_data, 4, [])
        ad = stats["attack_damage"]
        # Rank 2 Snack: 20 + 5% AD + 9% of missing (50% of 1000) = 45.
        bonus = 20.0 + 0.05 * ad + 0.09 * 500.0
        row = result["breakdown"]["W"]
        assert row["name"] == "Snack Attack"
        assert row["total_damage"] == pytest.approx(bonus + ad)

    def test_q_shred_helps_later_casts_but_not_q_itself(self, briar_data):
        """Kog'Maw rule: the shred lands after Q's own damage, so only
        abilities cast after Q see reduced resistances."""
        params = dict(target_armor=100.0, target_magic_resistance=100.0)
        q_first = run_fight(
            briar_data,
            18,
            [],
            _fight_params(cast_order=["Q", "W", "E", "R"], **params),
        )
        q_last = run_fight(
            briar_data,
            18,
            [],
            _fight_params(cast_order=["E", "W", "R", "Q"], **params),
        )
        # Q's own damage is identical whether it casts first or last.
        assert q_first["breakdown"]["Q"]["total_damage"] == pytest.approx(
            q_last["breakdown"]["Q"]["total_damage"]
        )
        # E (magic) benefits from the 20% MR shred only after Q.
        assert (
            q_first["breakdown"]["E"]["total_damage"]
            > q_last["breakdown"]["E"]["total_damage"]
        )

    def test_r_stat_buffs_reach_the_stats_panel(self, briar_data):
        """run_fight's champion_stats reflect R's +20% total AD armor/MR
        (Gnar UI-panel rule)."""
        result = run_fight(briar_data, 11, [], _fight_params())
        base = calculate_total_stats(briar_data, 11, [])
        expected_bonus = 0.20 * base["attack_damage"]
        panel = result["champion_stats"]
        assert panel["armor"] == pytest.approx(base["armor"] + expected_bonus)
        assert panel["magic_resistance"] == pytest.approx(
            base["magic_resistance"] + expected_bonus
        )
        assert panel["life_steal"] == 15.0  # R rank 2 at level 11

    def test_blood_frenzy_buffs_attack_speed_in_fights(self, briar_data):
        """Frenzy ON (default) raises fight attack speed via the W buff;
        OFF drops both the buff and the Snack Attack row."""
        on = run_fight(briar_data, 18, [], _fight_params())
        off = run_fight(
            briar_data,
            18,
            [],
            _fight_params(champion_options={"blood_frenzy_active": False}),
        )
        assert (
            on["champion_stats"]["attack_speed"] > off["champion_stats"]["attack_speed"]
        )
        assert "W" in on["breakdown"]
        assert "W" not in off["breakdown"]

    def test_timed_fight_bleed_counts_autos_and_ability_casts(self, briar_data):
        """10s timed fight with autos: bleed applications = every auto
        (Snack rides the auto stream) + Q recasts + E + R."""
        result = run_fight(
            briar_data,
            18,
            [],
            _fight_params(
                one_rotation=False,
                fight_duration_seconds=10.0,
                auto_attack_uptime=1.0,
            ),
        )
        # W's empowered swings are reported on the W row, so the auto row
        # counts only the PLAIN autos — every attack still bleeds.
        autos = result["breakdown"]["auto_attacks"]["count"]
        w_row = result["breakdown"].get("W")
        total_attacks = autos + (w_row["casts"] if w_row else 0)
        # Q cd 9 -> 2 casts; E cd 16 -> 1; R -> 1 (no ability haste).
        expected_casts = 2 + 1 + 1
        row = result["breakdown"]["stacking_dot_passive"]
        assert row["count"] == total_attacks + expected_casts


class TestReviewedCrowdControl:
    """Briar's crowd-control review, now complete.

    E's scream lands on the recast at the end of the cached charge, which
    this module always prices in full, and the charge's own healing stays
    inside the charge because the heal rule counts from the cast
    (``HealAnchor.CAST_SCHEDULE``) rather than from the scream.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Briar")
        assert briar.MODULE_CC == {"Q": "stun", "W": "none", "R": "none"}
        assert "stuns them for 0.85 seconds" in " ".join(
            cc_review.slot_text(data, "Q").split()
        )
        assert cc_review.control_words(cc_review.slot_text(data, "W")) == []
        assert cc_review.control_words(cc_review.slot_text(data, "R")) == [
            "fear",
            "slow",
        ]
        # R fears "all non-marked targets"; the marked one is the target
        # its explosion damages, and it is not feared.
        assert "fears all non-marked targets" in cc_review.slot_text(data, "R")

    def test_chilling_scream_lands_at_the_end_of_its_cached_charge(
        self, briar_data, parse_at
    ):
        """The scream is the recast, one cached second after the cast."""
        text = cc_review.slot_text(cc_review.kit("Briar"), "E")
        assert (
            "briar prepares to unleash a scream in the target direction, "
            "charging for up to 1 second" in text
        )
        assert (
            "if chilling scream was charged for its full duration, enemies hit "
            "are also knocked back 575 units" in text
        )
        _, abilities = parse_at(briar_data, 18)
        (part,) = abilities["E"]["parts"]
        assert part.time_offset == briar.E_FULL_CHARGE_SECONDS == 1.0
        assert part.cc_kind == "knockback"

    def test_the_charge_heals_during_the_charge_not_after_the_scream(self):
        """The four ticks belong to the charge: "charging for up to 1
        second, during which she ... heals herself every 0.25 seconds".

        This is the defect the anchor exists for.  The ticks used to hang
        off the scream's own damage event, so timing the scream at the end
        of the charge would have pushed the charge's healing to 1.25-2.0s
        — after the thing it happens during.
        """
        from src.calculator.calculate import calculate_payload

        payload = calculate_payload(
            {
                "champion": "Briar",
                "level": 18,
                "items": ["Fimbulwinter"],
                "fight_mode": "timed",
                "include_auto_attacks": True,
            }
        )
        ticks = [
            round(float(event["time"]), 3)
            for event in payload["self_healing_events"]
            if event["source"] == "Chilling Scream"
        ]
        assert ticks[:4] == [0.25, 0.5, 0.75, 1.0]
        scream = [
            round(float(event["time"]), 3)
            for event in payload["damage_events"]
            if event.get("source") == "E"
        ]
        assert scream and min(scream) == 1.0
        assert max(ticks[:4]) <= min(scream)

    def test_the_kit_clears_the_control_armed_scan(self):
        assert cc_review.unreviewed_ability_slots("Briar") == []
        coverage = cc_review.fimbulwinter_coverage("Briar")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
