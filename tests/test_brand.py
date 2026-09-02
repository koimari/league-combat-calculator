"""Brand module tests — hand-validated against the LoL wiki.

Sanity anchors (magic damage, pre-mitigation, 100 AP):
- Q rank 5: 190 + 65% AP           = 255
- W rank 5 (always empowered):     93.75..318.75 + 87.5% AP = 406.25
- E rank 5: 155 + 60% AP           = 215
- R rank 3, 3 bounces: 3 x (250 + 30% AP) = 840
- Blaze DoT, 3 stacks vs 3000 max HP: 3 x 2% x 3000 = 180
- Blaze detonation, level 18, 100 AP vs 3000 max HP:
  (12% + 2% per 100 AP) x 3000 = 420
"""

import pytest

from src.calculator.champions import brand, parse_champion_abilities
from tests import cc_review

TARGET = {"target_max_health": 3000.0}


class TestBrandAbilities:
    """Direct ability reads at fixed ranks (level 18 = all maxed)."""

    def test_q_rank5_damage(self, brand_data, parse_at):
        _, abilities = parse_at(brand_data, 18, ap=100.0, target_stats=TARGET)
        assert abilities["Q"]["damage_type"] == "magic"
        assert abilities["Q"]["total_raw"] == pytest.approx(255.0)

    def test_w_always_empowered(self, brand_data, parse_at):
        """W must read the Ablaze-empowered values, not the base 325."""
        _, abilities = parse_at(brand_data, 18, ap=100.0, target_stats=TARGET)
        assert abilities["W"]["damage_type"] == "magic"
        assert abilities["W"]["total_raw"] == pytest.approx(406.25)

    def test_e_rank5_damage(self, brand_data, parse_at):
        _, abilities = parse_at(brand_data, 18, ap=100.0, target_stats=TARGET)
        assert abilities["E"]["damage_type"] == "magic"
        assert abilities["E"]["total_raw"] == pytest.approx(215.0)

    def test_r_default_three_bounces(self, brand_data, parse_at):
        """R defaults to 3 bounces: per-bounce x 3, never the JSON's
        'Total Single-Target Damage' summed on top (double-count trap)."""
        _, abilities = parse_at(brand_data, 18, ap=100.0, target_stats=TARGET)
        assert abilities["R"]["damage_type"] == "magic"
        assert abilities["R"]["total_raw"] == pytest.approx(840.0)

    def test_cooldowns_present(self, brand_data, parse_at):
        _, abilities = parse_at(brand_data, 18, ap=100.0, target_stats=TARGET)
        assert abilities["Q"]["cooldown"] == pytest.approx(6.0)
        assert abilities["W"]["cooldown"] == pytest.approx(8.0)
        assert abilities["E"]["cooldown"] == pytest.approx(9.0)
        assert abilities["R"]["cooldown"] == pytest.approx(80.0)


class TestRBouncesOption:
    """r_bounces scales R damage and the Ablaze stacks R contributes."""

    def test_one_bounce(self, brand_data, parse_at):
        _, abilities = parse_at(
            brand_data,
            18,
            ap=100.0,
            target_stats=TARGET,
            champion_options={"r_bounces": 1},
        )
        assert abilities["R"]["total_raw"] == pytest.approx(280.0)

    def test_two_bounces(self, brand_data, parse_at):
        _, abilities = parse_at(
            brand_data,
            18,
            ap=100.0,
            target_stats=TARGET,
            champion_options={"r_bounces": 2},
        )
        assert abilities["R"]["total_raw"] == pytest.approx(560.0)


class TestBlazePassive:
    """Blaze = stack-tracked DoT + once-per-rotation detonation."""

    def test_full_rotation_dot_plus_detonation(self, brand_data, parse_at):
        """Level 18, 100 AP, 3000 max HP: 180 DoT + 420 detonation."""
        _, abilities = parse_at(brand_data, 18, ap=100.0, target_stats=TARGET)
        passive = abilities["passive"]
        assert passive["damage_type"] == "magic"
        assert passive["proc_count"] == 1
        assert passive["total_raw"] == pytest.approx(600.0)

    def test_stack_cap_at_three(self, brand_data, parse_at):
        """Q+W+E+R(3 bounces) = 6 applications, but only 3 stacks burn."""
        _, abilities = parse_at(brand_data, 18, ap=100.0, target_stats=TARGET)
        parts = abilities["passive"]["parts"]
        dot_part = parts[0]
        assert dot_part.count == 3
        assert dot_part.amount == pytest.approx(60.0)  # 2% x 3000

    def test_no_detonation_below_three_stacks(self, brand_data, parse_at):
        """Level 2 (Q+W ranked, no E/R): 2 stacks of DoT, no detonation."""
        _, abilities = parse_at(brand_data, 2, ap=0.0, target_stats=TARGET)
        passive = abilities["passive"]
        assert passive["total_raw"] == pytest.approx(120.0)
        assert len(passive["parts"]) == 1

    def test_level_one_single_stack(self, brand_data, parse_at):
        """Level 1 (Q only): one 60-damage stack. Also proves the mana
        refund array [20..40] never leaks into damage output."""
        _, abilities = parse_at(brand_data, 1, ap=0.0, target_stats=TARGET)
        assert abilities["passive"]["total_raw"] == pytest.approx(60.0)

    def test_detonation_scales_past_level_18(self, brand_data, parse_at):
        """Level 20 keeps the parser array's linear extrapolation
        (12.71%), not the wiki-prose 12% clamp."""
        _, abilities = parse_at(brand_data, 20, ap=100.0, target_stats=TARGET)
        # DoT 180 + (12.71% + 2%) x 3000 = 180 + 441.3
        assert abilities["passive"]["total_raw"] == pytest.approx(621.3)

    def test_r_bounces_feed_stack_count(self, brand_data, parse_at):
        """With only R ranked (1 bounce), one stack burns and no
        detonation fires."""
        _, abilities = parse_at(
            brand_data,
            18,
            ap=0.0,
            target_stats=TARGET,
            ability_ranks={"Q": 0, "W": 0, "E": 0, "R": 3},
            champion_options={"r_bounces": 1},
        )
        passive = abilities["passive"]
        assert passive["total_raw"] == pytest.approx(60.0)
        assert len(passive["parts"]) == 1


class TestBrandSkillOrder:
    """Brand maxes W first, then Q, then E (R at 6/11/16)."""

    def test_w_maxed_by_nine(self, brand_data, parse_at):
        _, abilities = parse_at(brand_data, 9, ap=0.0, target_stats=TARGET)
        assert abilities["W"]["rank"] == 5
        assert abilities["Q"]["rank"] == 2
        assert abilities["E"]["rank"] == 1


class TestBlazeLiandrysInteraction:
    """Ablaze keeps item burns refreshed for its 4s tail after the combo.

    In-game every Blaze tick is ability damage, so Liandry's Torment
    stays lit while Ablaze burns: the Torment window runs to (last cast
    + 4s Ablaze + 3s Torment), not just 3s past the last cast.
    """

    def test_blaze_tail_extends_liandrys_window(
        self, brand_data, parse_at, attacker_stats, fight, liandrys
    ):
        _, abilities = parse_at(
            brand_data,
            18,
            ap=100.0,
            target_stats={"target_max_health": 1000.0},
        )
        assert abilities["passive"]["dot_duration"] == pytest.approx(4.0)

        stats = attacker_stats(ability_power=100.0, is_melee=False)
        with_tail = fight(stats, abilities, items=[liandrys])

        no_tail = {k: dict(v) for k, v in abilities.items()}
        no_tail["passive"].pop("dot_duration")
        without = fight(stats, no_tail, items=[liandrys])

        burn_key = next(k for k in with_tail["breakdown"] if k.startswith("burn_"))
        with_burn = with_tail["breakdown"][burn_key]["total_damage"]
        without_burn = without["breakdown"][burn_key]["total_damage"]

        # Q/W/E/R = 4 casts -> 1.5s spread; the Torment window grows
        # from (1.5 + 3) to (1.5 + 4 + 3) seconds.
        assert with_burn / without_burn == pytest.approx(8.5 / 4.5)


class TestBrandFightIntegration:
    """The Blaze proc entry flows through the fight engine."""

    def test_one_rotation_includes_blaze(
        self, brand_data, parse_at, attacker_stats, fight
    ):
        _, abilities = parse_at(
            brand_data,
            18,
            ap=100.0,
            target_stats={"target_max_health": 1000.0},
        )
        stats = attacker_stats(ability_power=100.0, is_melee=False)
        result = fight(stats, abilities)
        # Raw Blaze vs 1000 HP: 3 x 20 DoT + 140 detonation = 200;
        # 100 MR halves it.
        blaze = result["breakdown"]["passive"]
        assert blaze["count"] == 1
        assert blaze["total_damage"] == pytest.approx(100.0)
        assert sum(
            event["damage"] for event in blaze["damage_events"]
        ) == pytest.approx(blaze["total_damage"])
        assert "passive" in result["timeline_coverage"]["exact_sources"]
        assert result["total_damage"] > 0


class TestReviewedCrowdControl:
    """Brand's crowd-control review, and the slots that still withhold.

    W's eruption is now authored where the cache puts it, and neither W
    nor E controls.  Q's stun and R's slow are both 'Ablaze Bonus'
    branches — they follow the target's stack state, not the slot — so
    one kind per slot cannot state either.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Brand")
        assert brand.MODULE_CC == {"E": "none", "W": "none"}
        assert cc_review.control_words(cc_review.slot_text(data, "E")) == []
        assert "the target takes 25% increased damage" in cc_review.slot_text(data, "W")

    def test_pillar_of_flame_erupts_at_the_cached_total_from_cast_start(self):
        """The note gives the number that includes the cast time."""
        data = cc_review.kit("Brand")
        assert "After a 0.627 seconds delay" in (
            data["abilities"]["W"][0]["effects"][0]["description"]
        )
        assert (
            "The delay would be a total of 0.891 seconds if it included the "
            "cast time." in data["abilities"]["W"][0]["notes"]
        )
        parsed = parse_champion_abilities(
            data, 18, 100.0, {"Q": 5, "W": 5, "E": 5, "R": 3}
        )
        (part,) = parsed["W"]["parts"]
        assert part.time_offset == 0.891
        assert part.cc_kind == "none"

    def test_the_ablaze_conditional_slots_keep_the_fight_coarse(self):
        """Q stuns and R slows only an already-Ablaze target."""
        data = cc_review.kit("Brand")
        assert "Ablaze Bonus: The target is stunned" in (
            data["abilities"]["Q"][0]["effects"][1]["description"]
        )
        assert "Ablaze Bonus: The target is slowed" in (
            data["abilities"]["R"][0]["effects"][2]["description"]
        )
        assert cc_review.unreviewed_ability_slots("Brand") == ["Q", "R"]
        coverage = cc_review.fimbulwinter_coverage("Brand")
        assert coverage["complete"] is False
        assert "fimbulwinter_everlasting" in coverage["coarse_sources"]
