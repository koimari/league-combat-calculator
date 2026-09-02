"""Braum champion module tests.

Hand-validated against https://wiki.leagueoflegends.com/en-us/Braum
- Q (Winter's Bite): 75/120/165/210/255 (+2.5% of Braum's OWN max HP)
  magic, cooldown 8/7.5/7/6.5/6s.
- W (Stand Behind Me): zero damage; SELF 20/25/30/35/40 (+36% bonus)
  armor and magic resistance.
- E (Unbreakable): selected directional projectile defense with a sourced
  duration and rank reduction.
- R (Glacial Fissure): 150/250/350 (+60% AP) magic.
- P (Concussive Blows): 4 applications (autos + Q) proc 16 + 10 x level
  magic; then 8/6/4s stack immunity during which each AUTO deals 40% of
  the trigger; cycle-simulated over the timed-fight auto/Q timeline.
"""

import pytest

from src.calculator.champions import braum, parse_champion_abilities
from src.calculator.champions.slotlib import extract_value
from src.calculator.pipeline import FightParams, run_fight
from src.calculator.stats import calculate_total_stats
from tests import cc_review


def _parse(braum_data, level, *, stats=None, options=None, ap=0.0):
    """Parse Braum with crafted stats (deterministic hand-math inputs)."""
    champion_stats = {
        "health": 2000.0,
        "attack_speed": 1.0,
        "ability_haste": 0.0,
        "basic_ability_haste": 0.0,
        "bonus_armor": 0.0,
        "bonus_magic_resistance": 0.0,
    }
    champion_stats.update(stats or {})
    return parse_champion_abilities(
        braum_data,
        level,
        ap,
        champion_stats=champion_stats,
        champion_options=options,
    )


def _fight_params(**overrides):
    """FightParams for a default one-rotation fight, field-overridable."""
    config = {
        "target_health": 1000.0,
        "target_bonus_health": 0.0,
        "target_armor": 100.0,
        "target_magic_resistance": 100.0,
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


class TestWintersBite:
    """Q: base magic damage + 2.5% of Braum's own built max health."""

    def test_rank5_with_3000_max_hp(self, braum_data):
        """Spec sanity check: 255 + 2.5% of 3000 = 330 raw magic."""
        abilities = _parse(braum_data, 9, stats={"health": 3000.0})
        q = abilities["Q"]
        assert q["rank"] == 5
        assert q["damage_type"] == "magic"
        assert q["total_raw"] == pytest.approx(330.0)
        assert q["cooldown"] == pytest.approx(6.0)

    def test_rank1(self, braum_data):
        """75 + 2.5% of 2000 = 125; cooldown 8s at rank 1."""
        abilities = _parse(braum_data, 1)
        q = abilities["Q"]
        assert q["rank"] == 1
        assert q["total_raw"] == pytest.approx(125.0)
        assert q["cooldown"] == pytest.approx(8.0)

    def test_uses_own_built_hp_not_target(self, braum_data, parse_at):
        """Real built stats: Q = base + 2.5% of Braum's own max HP."""
        stats, abilities = parse_at(
            braum_data,
            9,
            target_stats={"target_max_health": 10_000.0},
        )
        expected = 255.0 + 0.025 * stats["health"]
        assert abilities["Q"]["total_raw"] == pytest.approx(expected)


class TestStandBehindMe:
    """W: zero-damage self armor/MR steroid, option-toggled."""

    def test_zero_damage_with_flat_self_buff(self, braum_data):
        """Rank 2 (level 8), no bonus resists: flat 25 armor and 25 MR."""
        abilities = _parse(braum_data, 8)
        w = abilities["W"]
        assert w["total_raw"] == 0.0
        assert w["stat_buff"] == {"armor": 25.0, "magic_resistance": 25.0}

    def test_scales_with_36_percent_bonus_resists(self, braum_data):
        """25 + 36% of 100 bonus armor = 61; 25 + 36% of 50 bonus MR = 43."""
        abilities = _parse(
            braum_data,
            8,
            stats={"bonus_armor": 100.0, "bonus_magic_resistance": 50.0},
        )
        assert abilities["W"]["stat_buff"] == {
            "armor": pytest.approx(61.0),
            "magic_resistance": pytest.approx(43.0),
        }

    def test_toggle_off_keeps_row_drops_buff(self, braum_data):
        """w_active=False keeps the zero-damage row without a stat_buff."""
        abilities = _parse(braum_data, 8, options={"w_active": False})
        w = abilities["W"]
        assert w["total_raw"] == 0.0
        assert "stat_buff" not in w

    def test_absent_before_first_rank(self, braum_data):
        """Level 1 (W unlearned): the slot emits nothing."""
        abilities = _parse(braum_data, 1)
        assert "W" not in abilities


class TestUnbreakable:
    """E: selected directional projectile defense."""

    def test_emits_typed_defense_atom(self, braum_data):
        """E emits a zero-damage defense row with sourced rank values."""
        abilities = _parse(
            braum_data,
            18,
            options={
                "e_active": True,
                "e_active_seconds": 2.5,
                "e_blocked_skillshots": ["Ezreal:Q"],
            },
        )
        e = abilities["E"]
        assert e["total_raw"] == 0.0
        assert e["parts"] == ()
        assert e["defensive_interaction"] == {
            "kind": "braum_unbreakable",
            "active": True,
            "duration": pytest.approx(2.5),
            "damage_reduction": pytest.approx(0.55),
            "full_block_first": True,
            "blocked_sources": ["Ezreal:Q"],
        }


class TestGlacialFissure:
    """R: 150/250/350 + 60% AP magic."""

    def test_rank3_no_ap_is_exactly_350(self, braum_data):
        """Spec sanity check: rank 3, 0 AP -> exactly 350 raw magic."""
        abilities = _parse(braum_data, 16, ap=0.0)
        r = abilities["R"]
        assert r["rank"] == 3
        assert r["damage_type"] == "magic"
        assert r["total_raw"] == pytest.approx(350.0)

    def test_ap_ratio_is_60_percent(self, braum_data):
        """350 + 60% of 100 AP = 410."""
        abilities = _parse(braum_data, 16, ap=100.0)
        assert abilities["R"]["total_raw"] == pytest.approx(410.0)

    def test_rank1(self, braum_data):
        """Rank 1 (level 6), 0 AP: 150 raw."""
        abilities = _parse(braum_data, 6, ap=0.0)
        assert abilities["R"]["total_raw"] == pytest.approx(150.0)


class TestConcussiveBlows:
    """P: stack -> proc -> immunity-window cycle over the fight timeline."""

    TIMED = {"fight_duration_seconds": 5.0, "auto_attack_uptime": 1.0}

    def test_absent_without_fight_window(self, braum_data):
        """Per-cast mode (one rotation): one Q stack never procs."""
        assert "passive" not in _parse(braum_data, 18)

    def test_one_cycle_at_level_1(self, braum_data):
        """1 AS, 5s: Q+3 autos proc at t=2 (trigger 26), then the 8s
        immunity window covers the last 2 autos (10.4 bonus each)."""
        abilities = _parse(braum_data, 1, options=dict(self.TIMED))
        passive = abilities["passive"]
        assert passive["damage_type"] == "magic"
        assert passive["total_raw"] == pytest.approx(26.0 + 2 * 10.4)
        trigger_part, bonus_part = passive["parts"]
        assert trigger_part.amount == pytest.approx(26.0)
        assert trigger_part.count == 1
        assert bonus_part.amount == pytest.approx(10.4)
        assert bonus_part.count == 2

    def test_trigger_216_and_bonus_86_4_at_level_20(self, braum_data):
        """Spec sanity check: level 20 trigger 216, empowered auto 86.4."""
        abilities = _parse(braum_data, 20, options=dict(self.TIMED))
        trigger_part, bonus_part = abilities["passive"]["parts"]
        assert trigger_part.amount == pytest.approx(216.0)
        assert bonus_part.amount == pytest.approx(86.4)

    def test_trigger_196_and_bonus_78_4_at_level_18(self, braum_data):
        """Level 18: proc at t=2, 4s window -> 2 empowered autos."""
        abilities = _parse(braum_data, 18, options=dict(self.TIMED))
        passive = abilities["passive"]
        assert passive["total_raw"] == pytest.approx(196.0 + 2 * 78.4)

    def test_stacking_restarts_when_window_expires(self, braum_data):
        """Level 12, 1 AS, 8s: proc at t=2, 4s window (3 empowered
        autos), then the t=6 Q and autos stack again."""
        abilities = _parse(
            braum_data,
            12,
            options={"fight_duration_seconds": 8.0, "auto_attack_uptime": 1.0},
        )
        passive = abilities["passive"]
        assert passive["total_raw"] == pytest.approx(136.0 + 3 * 54.4)

    def test_two_full_cycles(self, braum_data):
        """Level 12, 12s: second buildup (t=6 Q + autos) procs at t=8."""
        abilities = _parse(
            braum_data,
            12,
            options={"fight_duration_seconds": 12.0, "auto_attack_uptime": 1.0},
        )
        passive = abilities["passive"]
        assert passive["total_raw"] == pytest.approx(2 * 136.0 + 6 * 54.4)

    def test_q_only_stacks_expire_so_no_procs(self, braum_data):
        """No autos: Q every 8s can never hold 4 stacks (4s duration)."""
        abilities = _parse(
            braum_data,
            1,
            options={"fight_duration_seconds": 20.0, "auto_attack_uptime": 0.0},
        )
        assert "passive" not in abilities

    def test_autos_only_window_drops_the_q_applications(self, braum_data):
        """`auto_attacks_only` casts nothing, so only autos stack.

        Level 12, 1 AS, 12s: autos at t=0..11 alone. Stacks at 0/1/2 and
        the 4th at t=3 procs (136), immunity to t=7 empowers 4/5/6; the
        t=7 auto restarts and t=10 procs again, empowering t=11 —
        2 procs + 4 empowered autos, versus the merged stream's
        2 + 6 (``test_two_full_cycles``) when Q also applies stacks.
        """
        options = {
            "fight_duration_seconds": 12.0,
            "auto_attack_uptime": 1.0,
            "auto_attacks_only": True,
        }
        passive = _parse(braum_data, 12, options=options)["passive"]
        trigger_part, bonus_part = passive["parts"]
        assert trigger_part.count == 2
        assert bonus_part.count == 4
        assert passive["total_raw"] == pytest.approx(2 * 136.0 + 4 * 54.4)

    def test_autos_only_without_autos_never_procs(self, braum_data):
        """No autos and no casts: nothing applies a stack at all."""
        assert "passive" not in _parse(
            braum_data,
            18,
            options={
                "fight_duration_seconds": 20.0,
                "auto_attack_uptime": 0.0,
                "auto_attacks_only": True,
            },
        )

    def test_json_bonus_array_matches_hardcoded_formula(self, braum_data):
        """JSON's 40%-bonus leveling array == 0.4 x (16 + 10 x level)."""
        passive_json = braum_data["abilities"]["P"][0]
        for level in range(1, 19):
            assert extract_value(
                passive_json, "Bonus Magic Damage", level
            ) == pytest.approx(0.4 * (16.0 + 10.0 * level))


class TestFightIntegration:
    """The parsed entries drive the fight engine and stats panel."""

    def test_w_buffs_the_champion_stats_panel(self, braum_data):
        """run_fight's champion_stats reflect W's +25/+25 when toggled on."""
        on = run_fight(
            braum_data,
            8,
            [],
            _fight_params(champion_options={"w_active": True}),
        )
        off = run_fight(
            braum_data,
            8,
            [],
            _fight_params(champion_options={"w_active": False}),
        )
        assert on["champion_stats"]["armor"] == pytest.approx(
            off["champion_stats"]["armor"] + 25.0
        )
        assert on["champion_stats"]["magic_resistance"] == pytest.approx(
            off["champion_stats"]["magic_resistance"] + 25.0
        )

    def test_passive_row_in_timed_fight_matches_parse(self, braum_data):
        """Timed fight, MR 0: the passive breakdown row equals the
        parse-time cycle total (no mitigation, no items)."""
        params = _fight_params(
            target_magic_resistance=0.0,
            auto_attack_uptime=1.0,
            one_rotation=False,
        )
        result = run_fight(braum_data, 11, [], params)

        stats = calculate_total_stats(braum_data, 11, [])
        abilities = parse_champion_abilities(
            braum_data,
            11,
            stats["ability_power"],
            champion_stats=stats,
            champion_options={
                "fight_duration_seconds": params.fight_duration_seconds,
                "auto_attack_uptime": params.auto_attack_uptime,
            },
        )
        row = result["breakdown"]["passive"]
        assert row["total_damage"] == pytest.approx(abilities["passive"]["total_raw"])
        assert "proc(s)" in row["detail"]

    def test_auto_only_passive_counts_swings_without_q(self, braum_data):
        """auto_only casts no Q, so the passive must not price Q's stacks.

        Same 18s window and uptime as the timed fight; the only
        difference is that the engine casts nothing. Engine output at
        level 18, no items, MR 0: timed 1215.2 (3 procs + 8 empowered
        autos), auto_only 1019.2 (2 procs + 8) — Q's applications are
        exactly the third proc.
        """
        shared = {
            "target_magic_resistance": 0.0,
            "fight_duration_seconds": 18.0,
            "auto_attack_uptime": 1.0,
            "one_rotation": False,
        }
        timed = run_fight(braum_data, 18, [], _fight_params(**shared))
        autos = run_fight(
            braum_data, 18, [], _fight_params(**shared, auto_attacks_only=True)
        )
        assert autos["breakdown"]["Q"]["casts"] == 0
        timed_row = timed["breakdown"]["passive"]
        autos_row = autos["breakdown"]["passive"]
        assert timed_row["total_damage"] == pytest.approx(1215.2)
        assert autos_row["total_damage"] == pytest.approx(1019.2)
        assert autos_row["detail"] == "2 proc(s) + 8 empowered auto(s) over 18s"

    def test_passive_absent_in_one_rotation_fight(self, braum_data):
        """One-rotation strips the reserved keys even if the caller
        smuggles them in — the passive stays per-cast (absent)."""
        params = _fight_params(
            champion_options={
                "fight_duration_seconds": 10.0,
                "auto_attack_uptime": 1.0,
            }
        )
        result = run_fight(braum_data, 11, [], params)
        assert "passive" not in result["breakdown"]


class TestReviewedCrowdControl:
    """Braum's damaging casts both control: Winter's Bite slows, R knocks up.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    """

    def test_module_cc_is_the_declaration_the_parser_wired(self):
        assert braum.MODULE_CC == {"Q": "slow", "R": "knockup"}
        assert braum.parse_abilities.cc_kinds == braum.MODULE_CC

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Braum")
        assert "slowing them by 70% decaying over 2 seconds" in (
            cc_review.slot_text(data, "Q")
        )
        assert "all other enemies hit are knocked up for 0.6 seconds" in (
            cc_review.slot_text(data, "R")
        )

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Braum") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Braum")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
