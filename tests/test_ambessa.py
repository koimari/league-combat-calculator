"""Tests for Ambessa champion ability parsing and damage calculation."""

import pytest

from src.calculator.calculate import calculate_payload
from src.calculator.champions import ambessa
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.data_fetcher import get_item_by_name
from src.calculator.pipeline import FightParams, run_fight
from src.calculator.scenario import load_public_champion
from tests import cc_review
from tests.ability_math import parts_raw_total


class TestQ1CunningSweep:
    """Tests for Q1 (Cunning Sweep) damage."""

    def test_q1_returns_physical_damage(self, ambessa_data, parse_at) -> None:
        _, abilities = parse_at(
            ambessa_data,
            9,
            champion_options={"sweetspot": False},
        )
        assert "Q" in abilities
        assert abilities["Q"]["damage_type"] == "physical"

    def test_q1_sweetspot_deals_more_damage(self, ambessa_data, parse_at) -> None:
        _, normal = parse_at(
            ambessa_data,
            9,
            champion_options={"sweetspot": False},
        )
        _, sweetspot = parse_at(
            ambessa_data,
            9,
            champion_options={"sweetspot": True},
        )
        assert sweetspot["Q"]["total_raw"] > normal["Q"]["total_raw"]

    def test_q1_sweetspot_is_default(self, ambessa_data, parse_at) -> None:
        _, default = parse_at(ambessa_data, 9)
        _, sweetspot = parse_at(
            ambessa_data,
            9,
            champion_options={"sweetspot": True},
        )
        assert abs(default["Q"]["total_raw"] - sweetspot["Q"]["total_raw"]) < 0.1

    def test_q1_has_cooldown(self, ambessa_data, parse_at) -> None:
        _, abilities = parse_at(ambessa_data, 9)
        assert abilities["Q"]["cooldown"] > 0

    def test_q1_rank1_normal_damage(self, ambessa_data, parse_at) -> None:
        """Verify Q1 rank 1 normal damage = base + bonus AD scaling."""
        _, abilities = parse_at(
            ambessa_data,
            1,
            champion_options={"sweetspot": False},
        )
        assert abilities["Q"]["total_raw"] > 0


class TestQ2SunderingSlam:
    """Tests for Q2 (Sundering Slam) damage."""

    def test_q2_present_in_results(self, ambessa_data, parse_at) -> None:
        _, abilities = parse_at(ambessa_data, 9)
        assert "Q2" in abilities

    def test_q2_is_physical_damage(self, ambessa_data, parse_at) -> None:
        _, abilities = parse_at(ambessa_data, 9)
        assert abilities["Q2"]["damage_type"] == "physical"

    def test_q2_separate_from_q1(self, ambessa_data, parse_at) -> None:
        """Q2 should have a different name and different damage from Q1."""
        _, abilities = parse_at(ambessa_data, 9)
        assert abilities["Q"]["name"] != abilities["Q2"]["name"]

    def test_q2_sweetspot_deals_more_damage(self, ambessa_data, parse_at) -> None:
        _, normal = parse_at(
            ambessa_data,
            9,
            champion_options={"sweetspot": False},
        )
        _, sweetspot = parse_at(
            ambessa_data,
            9,
            champion_options={"sweetspot": True},
        )
        assert sweetspot["Q2"]["total_raw"] > normal["Q2"]["total_raw"]

    def test_q2_shares_q1_cooldown(self, ambessa_data, parse_at) -> None:
        """Q2 is a recast, so its cooldown should match Q1."""
        _, abilities = parse_at(ambessa_data, 9)
        assert abilities["Q2"]["cooldown"] == abilities["Q"]["cooldown"]


class TestWRepudiation:
    """Tests for W (Repudiation) — always uses increased damage."""

    def test_w_returns_physical_damage(self, ambessa_data, parse_at) -> None:
        _, abilities = parse_at(ambessa_data, 3)
        assert "W" in abilities
        assert abilities["W"]["damage_type"] == "physical"

    def test_w_has_cooldown(self, ambessa_data, parse_at) -> None:
        _, abilities = parse_at(ambessa_data, 3)
        assert abilities["W"]["cooldown"] > 0

    def test_w_uses_increased_damage(self, ambessa_data, parse_at) -> None:
        """W should use 'Increased Physical Damage' (empowered)."""
        _, abilities = parse_at(ambessa_data, 3)
        assert abilities["W"]["total_raw"] >= 75.0

    def test_w_rank_scaling(self, ambessa_data, parse_at) -> None:
        """W damage should increase with rank."""
        _, low = parse_at(ambessa_data, 3)
        _, high = parse_at(ambessa_data, 9)
        assert high["W"]["total_raw"] > low["W"]["total_raw"]


class TestELacerate:
    """Tests for E (Lacerate) — both hits (Total Physical Damage)."""

    def test_e_returns_physical_damage(self, ambessa_data, parse_at) -> None:
        _, abilities = parse_at(ambessa_data, 4)
        assert "E" in abilities
        assert abilities["E"]["damage_type"] == "physical"

    def test_e_has_cooldown(self, ambessa_data, parse_at) -> None:
        _, abilities = parse_at(ambessa_data, 4)
        assert abilities["E"]["cooldown"] > 0

    def test_e_uses_total_damage_both_hits(self, ambessa_data, parse_at) -> None:
        """E should use Total Physical Damage (both passes)."""
        stats, abilities = parse_at(ambessa_data, 4)
        e = abilities["E"]
        bonus_ad = stats.get("bonus_attack_damage", 0.0)
        expected_total = 80 + 1.0 * bonus_ad
        assert abs(e["total_raw"] - expected_total) < 0.5

    def test_e_rank_scaling(self, ambessa_data, parse_at) -> None:
        """E damage should increase with rank."""
        _, low = parse_at(ambessa_data, 4)
        _, high = parse_at(ambessa_data, 14)
        assert high["E"]["total_raw"] > low["E"]["total_raw"]


class TestRPublicExecution:
    """Tests for R (Public Execution) stat buff + damage."""

    def test_r_has_stat_buff(self, ambessa_data, parse_at) -> None:
        _, abilities = parse_at(ambessa_data, 11)
        assert "R" in abilities
        assert "stat_buff" in abilities["R"]
        assert abilities["R"]["stat_buff"]["armor_penetration_percent"] > 0

    def test_r_armor_pen_rank1(self, ambessa_data, parse_at) -> None:
        """R rank 1 should grant 10% armor penetration."""
        _, abilities = parse_at(ambessa_data, 6)
        pen = abilities["R"]["stat_buff"]["armor_penetration_percent"]
        assert abs(pen - 10.0) < 0.1

    def test_r_armor_pen_rank3(self, ambessa_data, parse_at) -> None:
        """R rank 3 should grant 30% armor penetration."""
        _, abilities = parse_at(ambessa_data, 16)
        pen = abilities["R"]["stat_buff"]["armor_penetration_percent"]
        assert abs(pen - 30.0) < 0.1

    def test_r_deals_physical_damage(self, ambessa_data, parse_at) -> None:
        _, abilities = parse_at(ambessa_data, 11)
        assert abilities["R"]["damage_type"] == "physical"
        assert abilities["R"]["total_raw"] > 0

    def test_r_has_cooldown(self, ambessa_data, parse_at) -> None:
        _, abilities = parse_at(ambessa_data, 11)
        assert abilities["R"]["cooldown"] > 0

    def test_r_damage_scales_with_rank(self, ambessa_data, parse_at) -> None:
        """R active damage should increase with rank."""
        _, low = parse_at(ambessa_data, 6)
        _, high = parse_at(ambessa_data, 16)
        assert high["R"]["total_raw"] > low["R"]["total_raw"]


class TestRStatBuffInFightEngine:
    """Tests for R stat buff integration with the fight engine."""

    def test_stat_buff_applied_to_champion_stats(self, ambessa_data, parse_at) -> None:
        """The fight engine should apply R's armor pen to stats."""
        stats, abilities = parse_at(ambessa_data, 11)
        original_pen = stats.get("armor_penetration_percent", 0.0)

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
        assert stats["armor_penetration_percent"] > original_pen

    def test_armor_pen_reduces_effective_armor(self, ambessa_data, parse_at) -> None:
        """R's armor pen should reduce effective armor in fight results."""
        stats, abilities = parse_at(ambessa_data, 16)
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
        effective_armor = result.get("effective_armor", 100)
        assert effective_armor < 100
        assert abs(effective_armor - 70.0) < 1.0

    def test_q2_appears_in_fight_breakdown(self, ambessa_data, parse_at) -> None:
        """Q2 (Sundering Slam) should appear in fight damage breakdown."""
        stats, abilities = parse_at(ambessa_data, 9)
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
        assert "Q2" in result["breakdown"]
        assert result["breakdown"]["Q2"]["total_damage"] > 0


class TestPassiveDrakehoundsStep:
    """Tests for P (Drakehound's Step) empowered auto."""

    def test_passive_present(self, ambessa_data, parse_at) -> None:
        _, abilities = parse_at(ambessa_data, 9)
        assert "passive" in abilities

    def test_passive_is_physical_damage(self, ambessa_data, parse_at) -> None:
        _, abilities = parse_at(ambessa_data, 9)
        assert abilities["passive"]["damage_type"] == "physical"

    def test_passive_scales_with_level(self, ambessa_data, parse_at) -> None:
        _, low = parse_at(ambessa_data, 1)
        _, high = parse_at(ambessa_data, 18)
        assert parts_raw_total(high["passive"]["parts"], "physical") > parts_raw_total(
            low["passive"]["parts"], "physical"
        )

    def test_passive_proc_count_default(self, ambessa_data, parse_at) -> None:
        """Default passive procs should be 4."""
        _, abilities = parse_at(ambessa_data, 9)
        assert abilities["passive"]["proc_count"] == 4

    def test_passive_proc_count_custom(self, ambessa_data, parse_at) -> None:
        """Custom passive proc count should be respected."""
        _, abilities = parse_at(
            ambessa_data,
            9,
            champion_options={"passive_procs": 6},
        )
        assert abilities["passive"]["proc_count"] == 6
        per_proc = parts_raw_total(abilities["passive"]["parts"], "physical")
        assert abs(abilities["passive"]["total_raw"] - per_proc * 6) < 0.1

    @pytest.mark.parametrize(("level", "restored"), [(1, 40.0), (7, 55.0), (13, 70.0)])
    def test_passive_energy_restore_breakpoints(
        self, ambessa_data, parse_at, level, restored
    ) -> None:
        _, abilities = parse_at(ambessa_data, level)
        assert abilities["passive"]["resource_restore_per_proc"] == restored

    def test_passive_zero_procs_excluded(self, ambessa_data, parse_at) -> None:
        """Setting passive_procs to 0 should exclude passive."""
        _, abilities = parse_at(
            ambessa_data,
            9,
            champion_options={"passive_procs": 0},
        )
        assert "passive" not in abilities

    def test_passive_level1_base_damage(self, ambessa_data, parse_at) -> None:
        """Level 1 passive per-proc should be ~5 base + 25% bonus AD."""
        stats, abilities = parse_at(ambessa_data, 1)
        per_proc = parts_raw_total(abilities["passive"]["parts"], "physical")
        bonus_ad = stats.get("bonus_attack_damage", 0.0)
        expected = 5.0 + 0.25 * bonus_ad
        assert abs(per_proc - expected) < 1.0

    def test_passive_includes_bonus_ad_scaling(self, ambessa_data, parse_at) -> None:
        """Passive should scale with bonus AD (25% ratio)."""
        item = get_item_by_name("Voltaic Cyclosword")
        _, no_items = parse_at(ambessa_data, 18)
        _, with_item = parse_at(ambessa_data, 18, items=[item])
        assert parts_raw_total(with_item["passive"]["parts"], "physical") > (
            parts_raw_total(no_items["passive"]["parts"], "physical")
        )

    def test_passive_declares_the_auto_stack_certification(
        self, ambessa_data, parse_at
    ) -> None:
        """Each proc rides exactly one empowered basic attack."""
        _, abilities = parse_at(ambessa_data, 9)
        passive = abilities["passive"]
        assert passive["event_order_certified"] == "auto_stack_proc"
        assert passive["auto_stack_every"] == 1
        # The coupling flag stays: it is what clamps procs to real swings
        # in one-rotation mode, where the stack certification does not.
        assert passive["requires_auto_timeline_coupling"] is True


class TestPassiveEventCertification:
    """Wave 1B: the passive's ledger rides the real swing schedule."""

    @staticmethod
    def _timed_params():
        return FightParams.from_request(
            {
                "fight_mode": "time_based",
                "fight_duration": 8,
                "include_auto_attacks": True,
                "auto_attack_uptime": 0.8,
                "target_health": 1000,
                "target_armor": 100,
                "target_mr": 100,
            },
            deterministic=True,
        )

    def test_timed_payload_probe_certifies_full_timeline(self) -> None:
        """The campaign probe: bare-kit timed Ambessa has no coarse sources."""
        result = calculate_payload(
            {
                "champion": "Ambessa",
                "level": 18,
                "items": [],
                "fight_mode": "timed",
                "include_auto_attacks": True,
            }
        )
        coverage = result["timeline_coverage"]
        assert coverage["complete"] is True
        assert coverage["coarse_sources"] == []
        assert "passive" in coverage["exact_sources"]

    def test_timed_passive_events_land_on_the_swing_schedule(self) -> None:
        result = run_fight(
            load_public_champion("Ambessa"), 18, [], self._timed_params()
        )
        assert result["timeline_coverage"]["complete"] is True
        passive = result["breakdown"]["passive"]
        events = passive["damage_events"]
        assert len(events) == passive["count"]
        assert {event["event_precision"] for event in events} == {"exact"}
        times = [event["time"] for event in events]
        assert times == sorted(times)
        assert times[0] == pytest.approx(0.0)  # proc 1 rides the first swing
        assert sum(event["damage"] for event in events) == pytest.approx(
            passive["total_damage"]
        )

    def test_one_rotation_without_swings_still_prices_no_procs(
        self, ambessa_data, parse_at
    ) -> None:
        """The coupling clamp survives certification: no attacks, no procs."""
        stats, abilities = parse_at(ambessa_data, 9)
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
        assert "passive" not in result["breakdown"]


class TestReviewedCrowdControl:
    """Ambessa's crowd-control review, slot by slot.

    R's strike lands on the far side of its cached suppression, stunning
    what it damages.  E's row is the cached 'Total Physical Damage' of
    both spins, and carries the slow both of them apply.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Ambessa")
        assert ambessa.MODULE_CC == {
            "Q": "none",
            "Q2": "none",
            "W": "none",
            "R": "stun",
            "P": "none",
            "E": "slow",
        }
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert cc_review.control_words(cc_review.slot_text(data, "W")) == []
        assert (
            "afterwards dealing physical damage and stunning them for 0.4 seconds"
            in cc_review.slot_text(data, "R")
        )

    def test_public_execution_lands_after_the_cached_suppression(
        self, ambessa_data, parse_at
    ):
        text = cc_review.slot_text(cc_review.kit("Ambessa"), "R")
        assert "suppresses them for 0.75 seconds" in text
        _, abilities = parse_at(ambessa_data, 18)
        (part,) = abilities["R"]["parts"]
        # 0.7 cached cast time, then the 0.75-second suppression.
        assert part.time_offset == pytest.approx(1.45)
        assert part.cc_kind == "stun"

    def test_lacerates_summed_spins_carry_the_slow(self):
        """The cache never times the second spin, so both land on one row.
        The row declares the slow they share, which is what lets the whole
        fight certify."""
        text = cc_review.slot_text(cc_review.kit("Ambessa"), "E")
        assert (
            "drakehound's step's dash may be buffered during the lockout or "
            "initiated within 0.275 seconds of the lockout ending; in either "
            "case, she will spin a second time at the end of the dash to apply "
            "the same effects at no additional cost." in text
        )
        assert ambessa.MODULE_CC["E"] == "slow"
        assert cc_review.unreviewed_ability_slots("Ambessa") == []
        coverage = cc_review.fimbulwinter_coverage("Ambessa")
        assert coverage["complete"] is True
        assert coverage["coarse_sources"] == []
