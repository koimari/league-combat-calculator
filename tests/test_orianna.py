"""Tests for Orianna champion ability parsing and damage calculation.

Reference damage (raw, pre-mitigation, hand-computed from the wiki):
- P (Clockwork Windup): (base_at_level + 15% AP) x (1 + 0.15 x stacks),
  stacks 0-2 building one per basic attack on the same target.
  Level 1 bases: 10 / 11.5 / 13 at 0/1/2 stacks; level 18: 50 / 57.5 / 65.
  At level 1 with 100 AP: 25 at 0 stacks, 32.5 at 2 stacks
  (cross-check vs the JSON's pre-computed 2-stack row: 13 + 19.5 = 32.5).
- Q rank 5 at 100 AP: 180 + 55 = 235 magic, CD 3
- W rank 5 at 100 AP: 230 + 80 = 310 magic, CD 7 (slow/speed excluded)
- E rank 5 at 100 AP: 180 + 30 = 210 magic, CD 9 (shield/resists excluded)
- R rank 3 at 100 AP: 475 + 110 = 585 magic, CD 80
"""

import pytest

from src.calculator.champions import parse_champion_abilities as parse_abilities
from src.calculator.damage import FightConfig, calculate_fight_damage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ALL_MAXED = {"Q": 5, "W": 5, "E": 5, "R": 3}

STATS_100AP = {
    "attack_damage": 100.0,
    "bonus_attack_damage": 0.0,
    "ability_power": 100.0,
}


def _parse(orianna_data, level=18, ap=100.0, options=None, ranks=None):
    """Parse Orianna at a level with explicit AP and champion options."""
    return parse_abilities(
        orianna_data,
        level,
        ap,
        ability_ranks=ranks or dict(ALL_MAXED),
        champion_stats=dict(STATS_100AP, ability_power=ap),
        champion_options=options,
    )


def _fight(stats, abilities, **overrides):
    """Unmitigated deterministic fight (0 resistances) for exact numbers."""
    config = {
        "target_health": 5000.0,
        "target_armor": 0.0,
        "target_magic_resistance": 0.0,
        "fight_duration_seconds": 10.0,
        "auto_attack_uptime": 1.0,
        "one_rotation": False,
        "deterministic": True,
    }
    config.update(overrides)
    return calculate_fight_damage(stats, abilities, [], FightConfig(**config))


# ---------------------------------------------------------------------------
# Slot coverage and damage types
# ---------------------------------------------------------------------------


class TestSlotMap:
    """Every kit slot is emitted, all magic."""

    def test_all_slots_present(self, orianna_data) -> None:
        abilities = _parse(orianna_data)
        assert set(abilities) == {"Q", "W", "E", "R", "passive"}

    @pytest.mark.parametrize("slot", ["Q", "W", "E", "R"])
    def test_damage_types_magic(self, orianna_data, slot) -> None:
        abilities = _parse(orianna_data)
        assert abilities[slot]["damage_type"] == "magic"

    def test_cooldowns(self, orianna_data) -> None:
        abilities = _parse(orianna_data)
        assert abilities["Q"]["cooldown"] == 3.0
        assert abilities["W"]["cooldown"] == 7.0
        assert abilities["E"]["cooldown"] == 9.0
        assert abilities["R"]["cooldown"] == 80.0


# ---------------------------------------------------------------------------
# Hand-validated ability damage (wiki anchors)
# ---------------------------------------------------------------------------


class TestAbilityDamage:
    """Raw values match the wiki at max rank with 100 AP."""

    def test_q_rank5(self, orianna_data) -> None:
        """Q rank 5: 180 + 55% AP = 235 (full primary-target damage —
        the 70% 'Reduced Damage' row must not be parsed)."""
        abilities = _parse(orianna_data)
        assert abilities["Q"]["total_raw"] == pytest.approx(235.0)

    def test_w_rank5_excludes_movement_speed(self, orianna_data) -> None:
        """W rank 5: 230 + 80% AP = 310 exactly — the speed/slow
        modifier contributes nothing."""
        abilities = _parse(orianna_data)
        assert abilities["W"]["total_raw"] == pytest.approx(310.0)

    def test_e_rank5_excludes_shield_and_resists(self, orianna_data) -> None:
        """E rank 5: 180 + 30% AP = 210 exactly — shield strength
        (45% AP) and bonus resistances must not leak into damage."""
        abilities = _parse(orianna_data)
        assert abilities["E"]["total_raw"] == pytest.approx(210.0)

    def test_r_rank3(self, orianna_data) -> None:
        """R rank 3: 475 + 110% AP = 585."""
        abilities = _parse(orianna_data)
        assert abilities["R"]["total_raw"] == pytest.approx(585.0)


# ---------------------------------------------------------------------------
# E champion option (ball passes through target)
# ---------------------------------------------------------------------------


class TestEOption:
    """e_passes_through_target gates E's damage, not its presence."""

    def test_default_deals_damage(self, orianna_data) -> None:
        abilities = _parse(orianna_data)
        assert abilities["E"]["total_raw"] == pytest.approx(210.0)

    def test_disabled_is_zero_damage_utility_cast(self, orianna_data) -> None:
        abilities = _parse(orianna_data, options={"e_passes_through_target": False})
        entry = abilities["E"]
        assert entry["total_raw"] == 0.0
        assert sum(part.amount for part in entry["parts"]) == 0.0
        assert entry["cooldown"] == 9.0  # still a real cast


# ---------------------------------------------------------------------------
# Passive parse (level-indexed base + stack ramp payload)
# ---------------------------------------------------------------------------


class TestPassiveParse:
    """Clockwork Windup: level-indexed 0-stack base + JSON-derived ramp."""

    def test_level1_no_ap(self, orianna_data) -> None:
        abilities = _parse(orianna_data, level=1, ap=0.0, ranks={"Q": 1})
        on_hit = abilities["passive"]["on_hit"]
        assert on_hit["damage_per_hit"] == pytest.approx(10.0)
        assert on_hit["damage_type"] == "magic"
        ramp = on_hit["stack_ramp"]
        assert ramp["max_stacks"] == 2
        assert ramp["damage_per_stack"] == pytest.approx(1.5)

    def test_level1_100ap(self, orianna_data) -> None:
        """0-stack 10 + 15 = 25; per stack 1.5 + 2.25 = 3.75; the implied
        2-stack value 32.5 matches the JSON's pre-computed row
        (13 + 19.5% AP)."""
        abilities = _parse(orianna_data, level=1, ap=100.0, ranks={"Q": 1})
        on_hit = abilities["passive"]["on_hit"]
        assert on_hit["damage_per_hit"] == pytest.approx(25.0)
        ramp = on_hit["stack_ramp"]
        assert ramp["damage_per_stack"] == pytest.approx(3.75)
        two_stack = on_hit["damage_per_hit"] + 2 * ramp["damage_per_stack"]
        assert two_stack == pytest.approx(32.5)

    def test_level18_base_is_level_indexed(self, orianna_data) -> None:
        """Level 18 base is the JSON's 18th value (50), NOT the standard
        growth formula."""
        abilities = _parse(orianna_data, level=18, ap=0.0)
        on_hit = abilities["passive"]["on_hit"]
        assert on_hit["damage_per_hit"] == pytest.approx(50.0)
        assert on_hit["stack_ramp"]["damage_per_stack"] == pytest.approx(7.5)

    def test_no_item_on_hit_application(self, orianna_data) -> None:
        """The passive applies spell effects, not on-hit effects — it
        must never declare applies_item_on_hits."""
        abilities = _parse(orianna_data)
        assert "applies_item_on_hits" not in abilities["passive"]


# ---------------------------------------------------------------------------
# Fight-engine integration (natural single-target stack ramp)
# ---------------------------------------------------------------------------


class TestFightEngineRamp:
    """Auto k lands at the CURRENT stack count: x1.00, x1.15, then x1.30.

    Level 18 at 0 AP: 50 / 57.5 / 65 per auto.
    """

    def _passive_only(self, orianna_data, stats):
        return parse_abilities(
            orianna_data,
            18,
            stats["ability_power"],
            ability_ranks={"Q": 0, "W": 0, "E": 0, "R": 0},
            champion_stats=stats,
        )

    def test_single_auto_no_stacks(self, orianna_data, attacker_stats) -> None:
        stats = attacker_stats()
        abilities = self._passive_only(orianna_data, stats)
        result = _fight(stats, abilities, fight_duration_seconds=1.0)
        row = result["breakdown"]["on_hit_ability_passive"]
        assert row["count"] == 1
        assert row["total_damage"] == pytest.approx(50.0)

    def test_two_autos_second_at_one_stack(self, orianna_data, attacker_stats) -> None:
        stats = attacker_stats()
        abilities = self._passive_only(orianna_data, stats)
        result = _fight(stats, abilities, fight_duration_seconds=2.0)
        row = result["breakdown"]["on_hit_ability_passive"]
        assert row["count"] == 2
        assert row["total_damage"] == pytest.approx(50.0 + 57.5)

    def test_ten_autos_ramp_holds_at_two_stacks(
        self, orianna_data, attacker_stats
    ) -> None:
        """50 + 57.5 + 8 x 65 = 627.5 raw over 10 autos."""
        stats = attacker_stats()
        abilities = self._passive_only(orianna_data, stats)
        result = _fight(stats, abilities)
        row = result["breakdown"]["on_hit_ability_passive"]
        assert row["count"] == 10
        assert row["total_damage"] == pytest.approx(627.5)
        assert row["damage_per_hit"] == pytest.approx(62.75)  # displayed average

    def test_ramp_is_mitigated_by_mr(self, orianna_data, attacker_stats) -> None:
        """100 MR halves every hit of the ramp: 627.5 / 2."""
        stats = attacker_stats()
        abilities = self._passive_only(orianna_data, stats)
        result = _fight(stats, abilities, target_magic_resistance=100.0)
        row = result["breakdown"]["on_hit_ability_passive"]
        assert row["total_damage"] == pytest.approx(627.5 / 2.0)
