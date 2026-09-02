"""Tests for Aurora champion ability parsing and damage calculation.

Reference damage (raw, pre-mitigation, at 100 AP, rank 5 basics / rank 3 R):
- P proc vs 2000 max-HP target: (1% + 2.7%) * 2000 = 74 magic per proc
- Q first cast: 145 + 0.40 * 100 = 185 magic
- Q recast at full HP (minimum): 145 + 0.40 * 100 = 185 magic (total 370)
- Q recast at zero HP (maximum): 217.5 + 0.60 * 100 = 277.5 magic
- E: 230 + 0.70 * 100 = 300 magic
- R: 375 + 0.70 * 100 = 445 magic
"""

import pytest

from src.calculator.champions import aurora
from src.calculator.champions import parse_champion_abilities as parse_abilities
from src.calculator.champions.skill_orders import get_ability_rank
from src.calculator.damage import FightConfig, calculate_fight_damage
from tests import cc_review

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TARGET_2000_HP = {"target_max_health": 2000.0}

ALL_MAXED = {"Q": 5, "W": 5, "E": 5, "R": 3}

STATS_100AP = {
    "attack_damage": 100.0,
    "bonus_attack_damage": 0.0,
    "ability_power": 100.0,
}


def _parse_100ap(aurora_data, ranks=None, target=TARGET_2000_HP):
    """Parse Aurora at level 18 with 100 AP and explicit ranks."""
    return parse_abilities(
        aurora_data,
        18,
        100.0,
        ability_ranks=ranks or dict(ALL_MAXED),
        champion_stats=dict(STATS_100AP),
        target_stats=dict(target),
    )


def _fight(stats, abilities, **overrides):
    """Unmitigated deterministic fight (0 resistances) for exact numbers."""
    config = {
        "target_health": 2000.0,
        "target_armor": 0.0,
        "target_magic_resistance": 0.0,
        "fight_duration_seconds": 5.0,
        "auto_attack_uptime": 0.0,
        "one_rotation": True,
        "deterministic": True,
    }
    config.update(overrides)
    return calculate_fight_damage(stats, abilities, [], FightConfig(**config))


# ---------------------------------------------------------------------------
# P: Spirit Abjuration
# ---------------------------------------------------------------------------


class TestPassiveSpiritAbjuration:
    """P: every-3rd-hit %maxHP magic proc; autos AND ability hits stack."""

    def test_passive_present_with_on_hit(self, aurora_data) -> None:
        abilities = _parse_100ap(aurora_data)
        assert "passive" in abilities
        assert "on_hit" in abilities["passive"]

    def test_passive_damage_type_is_magic(self, aurora_data) -> None:
        abilities = _parse_100ap(aurora_data)
        assert abilities["passive"]["on_hit"]["damage_type"] == "magic"

    def test_passive_requires_three_stacks(self, aurora_data) -> None:
        abilities = _parse_100ap(aurora_data)
        assert abilities["passive"]["on_hit"]["stacks_required"] == 3

    def test_passive_counts_ability_hits(self, aurora_data) -> None:
        """Aurora's stack counter includes damaging ability hits."""
        abilities = _parse_100ap(aurora_data)
        assert abilities["passive"]["on_hit"]["count_ability_hits"] is True

    def test_passive_per_proc_reference_100ap(self, aurora_data) -> None:
        """(1% + 2.7% per 100 AP) * 2000 = 74 per proc; per hit = 74/3."""
        abilities = _parse_100ap(aurora_data)
        per_hit = abilities["passive"]["on_hit"]["damage_per_hit"]
        assert per_hit == pytest.approx(74.0 / 3, abs=0.01)

    def test_passive_per_proc_no_ap(self, aurora_data) -> None:
        """At 0 AP: 1% of 2000 = 20 per proc; per hit = 20/3."""
        abilities = parse_abilities(
            aurora_data,
            18,
            0.0,
            ability_ranks=dict(ALL_MAXED),
            champion_stats={"attack_damage": 100.0, "ability_power": 0.0},
            target_stats=dict(TARGET_2000_HP),
        )
        per_hit = abilities["passive"]["on_hit"]["damage_per_hit"]
        assert per_hit == pytest.approx(20.0 / 3, abs=0.01)

    def test_passive_no_direct_damage(self, aurora_data) -> None:
        """The passive shell carries no castable damage."""
        abilities = _parse_100ap(aurora_data)
        assert abilities["passive"]["total_raw"] == 0.0

    def test_passive_zero_without_target(self, aurora_data) -> None:
        """No target stats -> no max health -> zero per-hit damage."""
        abilities = _parse_100ap(aurora_data, target={})
        assert abilities["passive"]["on_hit"]["damage_per_hit"] == 0.0


# ---------------------------------------------------------------------------
# Q: Twofold Hex
# ---------------------------------------------------------------------------


class TestQTwofoldHex:
    """Q: first cast + auto-recast, recast scales with target missing HP."""

    def test_q_is_magic_damage(self, aurora_data) -> None:
        abilities = _parse_100ap(aurora_data)
        assert abilities["Q"]["damage_type"] == "magic"

    def test_q_has_cooldown(self, aurora_data) -> None:
        abilities = _parse_100ap(aurora_data)
        assert abilities["Q"]["cooldown"] == pytest.approx(7.0, abs=0.1)

    def test_q_rank5_full_hp_reference(self, aurora_data) -> None:
        """Rank 5 at 100 AP vs full-HP target: 185 + 185 = 370 total."""
        abilities = _parse_100ap(aurora_data)
        assert abilities["Q"]["total_raw"] == pytest.approx(370.0, abs=0.5)

    def test_q_has_two_parts(self, aurora_data) -> None:
        """First cast + recast: two damage parts, both fire every cast."""
        parts = _parse_100ap(aurora_data)["Q"]["parts"]
        assert len(parts) == 2

    def test_q_first_cast_part(self, aurora_data) -> None:
        """First-cast part is flat 185 at rank 5 / 100 AP."""
        parts = _parse_100ap(aurora_data)["Q"]["parts"]
        assert parts[0].hp_scaled_damage is None
        assert parts[0].amount == pytest.approx(185.0, abs=0.5)

    def test_q_recast_interpolates_missing_hp(self, aurora_data) -> None:
        """Recast part: 185 at full HP -> 277.5 at zero HP, linear."""
        parts = _parse_100ap(aurora_data)["Q"]["parts"]
        scaled = parts[1].hp_scaled_damage
        assert scaled is not None
        assert scaled(0.0) == pytest.approx(185.0, abs=0.5)
        assert scaled(1.0) == pytest.approx(277.5, abs=0.5)
        assert scaled(0.5) == pytest.approx((185.0 + 277.5) / 2, abs=0.5)

    def test_q_rank1_reference(self, aurora_data) -> None:
        """Rank 1 at 0 AP: first 45, recast min 45 -> 90 total."""
        abilities = parse_abilities(
            aurora_data,
            1,
            0.0,
            ability_ranks={"Q": 1, "W": 0, "E": 0, "R": 0},
            champion_stats={"attack_damage": 60.0, "ability_power": 0.0},
            target_stats=dict(TARGET_2000_HP),
        )
        assert abilities["Q"]["total_raw"] == pytest.approx(90.0, abs=0.5)


# ---------------------------------------------------------------------------
# W: Across the Veil
# ---------------------------------------------------------------------------


class TestWAcrossTheVeil:
    """W (Across the Veil) carries no enemy-damage attribute (damageType:
    None, dash/invisibility/MS leveling rows only) — it emits a sourced
    zero-damage row rather than staying silently absent."""

    def test_w_present_zero_damage(self, aurora_data) -> None:
        abilities = _parse_100ap(aurora_data)
        entry = abilities["W"]
        assert entry["name"] == "Across the Veil"
        assert entry["total_raw"] == 0.0
        assert entry["parts"] == ()
        assert entry["detail"]


# ---------------------------------------------------------------------------
# E: The Weirding
# ---------------------------------------------------------------------------


class TestETheWeirding:
    """E: simple magic damage."""

    def test_e_is_magic_damage(self, aurora_data) -> None:
        abilities = _parse_100ap(aurora_data)
        assert abilities["E"]["damage_type"] == "magic"

    def test_e_has_cooldown(self, aurora_data) -> None:
        abilities = _parse_100ap(aurora_data)
        assert abilities["E"]["cooldown"] > 0

    def test_e_rank5_reference(self, aurora_data) -> None:
        """Rank 5 at 100 AP: 230 + 70 = 300 magic."""
        abilities = _parse_100ap(aurora_data)
        assert abilities["E"]["total_raw"] == pytest.approx(300.0, abs=0.5)


# ---------------------------------------------------------------------------
# R: Between Worlds
# ---------------------------------------------------------------------------


class TestRBetweenWorlds:
    """R: simple magic damage on the leap shockwave."""

    def test_r_is_magic_damage(self, aurora_data) -> None:
        abilities = _parse_100ap(aurora_data)
        assert abilities["R"]["damage_type"] == "magic"

    def test_r_has_cooldown(self, aurora_data) -> None:
        abilities = _parse_100ap(aurora_data)
        assert abilities["R"]["cooldown"] > 0

    def test_r_rank3_reference(self, aurora_data) -> None:
        """Rank 3 at 100 AP: 375 + 70 = 445 magic."""
        abilities = _parse_100ap(aurora_data)
        assert abilities["R"]["total_raw"] == pytest.approx(445.0, abs=0.5)


# ---------------------------------------------------------------------------
# Skill order (Q max first, then E, then W)
# ---------------------------------------------------------------------------


class TestSkillOrder:
    """Aurora levels Q > E > W."""

    def test_e_before_w(self) -> None:
        assert get_ability_rank("E", 2, "Aurora") == 1
        assert get_ability_rank("W", 2, "Aurora") == 0

    def test_q_maxed_first(self) -> None:
        assert get_ability_rank("Q", 9, "Aurora") == 5


# ---------------------------------------------------------------------------
# Fight-engine integration
# ---------------------------------------------------------------------------


class TestFightEngineIntegration:
    """Passive proc counting and Q tracked-HP scaling in the fight sim."""

    def _abilities(self, aurora_data, stats, ranks=None):
        return parse_abilities(
            aurora_data,
            18,
            stats["ability_power"],
            ability_ranks=ranks or dict(ALL_MAXED),
            champion_stats=stats,
            target_stats=dict(TARGET_2000_HP),
        )

    def test_passive_procs_from_ability_hits_alone(
        self, aurora_data, attacker_stats
    ) -> None:
        """No autos: Q (2 hits) + E (1) + R (1) = 4 hits -> 1 proc = 74."""
        stats = attacker_stats(ability_power=100.0)
        abilities = self._abilities(aurora_data, stats)
        result = _fight(stats, abilities)
        passive = result["breakdown"]["on_hit_ability_passive"]
        assert passive["count"] == 1
        assert passive["total_damage"] == pytest.approx(74.0, abs=0.1)
        assert [event["time"] for event in passive["damage_events"]] == [0.0]
        assert "on_hit_ability_passive" in result["timeline_coverage"]["exact_sources"]

    def test_passive_procs_mix_autos_and_abilities(
        self, aurora_data, attacker_stats
    ) -> None:
        """2 autos + 4 ability hits = 6 hits -> 2 procs = 148."""
        stats = attacker_stats(ability_power=100.0)
        abilities = self._abilities(aurora_data, stats)
        result = _fight(
            stats,
            abilities,
            fight_duration_seconds=2.0,
            auto_attack_uptime=1.0,
        )
        passive = result["breakdown"]["on_hit_ability_passive"]
        assert passive["count"] == 2
        assert passive["total_damage"] == pytest.approx(148.0, abs=0.1)

    def test_passive_partial_stacks_do_not_proc(
        self, aurora_data, attacker_stats
    ) -> None:
        """A lone E is 1 hit -> 0 complete procs -> 0 passive damage."""
        stats = attacker_stats(ability_power=100.0)
        abilities = self._abilities(
            aurora_data, stats, ranks={"Q": 0, "W": 0, "E": 5, "R": 0}
        )
        result = _fight(stats, abilities)
        passive = result["breakdown"]["on_hit_ability_passive"]
        assert passive["count"] == 0
        assert passive["total_damage"] == 0.0

    def test_q_recast_scales_with_tracked_hp(self, aurora_data, attacker_stats) -> None:
        """Q first (185) drops target to 1815/2000; recast interpolates:
        185 + 92.5 * 0.0925 = 193.556 -> Q total 378.556 (unmitigated)."""
        stats = attacker_stats(ability_power=100.0)
        abilities = self._abilities(
            aurora_data, stats, ranks={"Q": 5, "W": 0, "E": 0, "R": 0}
        )
        result = _fight(stats, abilities)
        q_total = result["breakdown"]["Q"]["total_damage"]
        assert q_total == pytest.approx(378.556, abs=0.1)

    def test_q_casts_include_recast_every_cast(
        self, aurora_data, attacker_stats
    ) -> None:
        """Timed mode: every Q cast deals both hits (recast auto-fires)."""
        stats = attacker_stats(ability_power=100.0)
        abilities = self._abilities(
            aurora_data, stats, ranks={"Q": 5, "W": 0, "E": 0, "R": 0}
        )
        result = _fight(
            stats,
            abilities,
            one_rotation=False,
            fight_duration_seconds=10.0,
        )
        q_row = result["breakdown"]["Q"]
        # Rank 5 CD 7s over 10s -> 2 casts; each cast >= 370 raw.
        assert q_row["casts"] == 2
        assert q_row["total_damage"] > 2 * 370.0


class TestReviewedCrowdControl:
    """Aurora's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Aurora")
        assert aurora.MODULE_CC == {
            "Q": "none",
            "W": "none",
            "E": "slow",
            "R": "slow",
            "P": "none",
        }
        assert "slows them by 80%" in " ".join(cc_review.slot_text(data, "E").split())
        assert "slow them by 30%" in " ".join(cc_review.slot_text(data, "R").split())
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Aurora") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Aurora")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


class TestModuleCoverage:
    def test_all_five_slots_covered(self) -> None:
        from src.calculator.champions.aurora import MODULE_COVERAGE

        assert MODULE_COVERAGE == {
            "P": "modeled",
            "Q": "modeled",
            "W": "no_damage",
            "E": "modeled",
            "R": "modeled",
        }
