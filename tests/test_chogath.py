"""Tests for Cho'Gath champion ability parsing and damage calculation.

Reference damage (wiki: https://wiki.leagueoflegends.com/en-us/Cho'Gath):
- Q (Rupture) rank 5: 300 + 100% AP magic damage, 6s flat cooldown.
- W (Feral Scream) rank 5: 280 + 70% AP magic damage.
- E (Vorpal Spikes): the next 3 basic attacks each deal 20-100 + 30% AP
  + (2.5-3.9% + 0.5% per Feast stack) of target's MAX health as bonus
  magic damage. The empowered hits are real basic attacks.
- R (Feast) rank 3 vs champions: 300/475/650 + 50% AP + 10% of
  Cho'Gath's BONUS health as TRUE damage; each Feast stack grants
  80/120/160 bonus health (retroactive to R rank).
"""

import pytest

from src.calculator.champions import parse_champion_abilities as parse_abilities
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.data_fetcher import get_item_by_name
from src.calculator.champions.slotlib import extract_value
from src.calculator.champions import chogath
from tests import cc_review

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ALL_MAXED = {"Q": 5, "W": 5, "E": 5, "R": 3}
NO_R = {"Q": 5, "W": 5, "E": 5, "R": 0}

STATS_100_AD = {
    "attack_damage": 100.0,
    "base_attack_damage": 100.0,
    "bonus_attack_damage": 0.0,
    "bonus_health": 0.0,
    "health": 1000.0,
}

TARGET_2000 = {"target_max_health": 2000.0}


def _parse(data, ranks, ap=0.0, stats=None, options=None, target=None):
    """Parse at level 18 with explicit ranks (skill-order independent)."""
    return parse_abilities(
        data,
        18,
        ap,
        ability_ranks=ranks,
        champion_options=options,
        champion_stats=dict(stats or STATS_100_AD),
        target_stats=dict(target or TARGET_2000),
    )


# ---------------------------------------------------------------------------
# Q: Rupture
# ---------------------------------------------------------------------------


class TestQRupture:
    """Q: single-hit magic nuke, 80-300 + 100% AP, 6s flat cooldown."""

    def test_q_is_magic_damage(self, chogath_data, parse_at) -> None:
        _, abilities = parse_at(chogath_data, 9)
        assert "Q" in abilities
        assert abilities["Q"]["damage_type"] == "magic"

    def test_q_rank5_no_ap(self, chogath_data) -> None:
        abilities = _parse(chogath_data, ALL_MAXED, ap=0.0)
        assert abilities["Q"]["total_raw"] == pytest.approx(300.0)

    def test_q_rank5_100_ap(self, chogath_data) -> None:
        """Q rank 5 with 100 AP: 300 + 100 = 400 (spec sanity check)."""
        abilities = _parse(chogath_data, ALL_MAXED, ap=100.0)
        assert abilities["Q"]["total_raw"] == pytest.approx(400.0)

    def test_q_rank1_no_ap(self, chogath_data) -> None:
        abilities = _parse(chogath_data, {"Q": 1, "W": 0, "E": 0, "R": 0})
        assert abilities["Q"]["total_raw"] == pytest.approx(80.0)

    def test_q_cooldown_flat_6(self, chogath_data) -> None:
        r1 = _parse(chogath_data, {"Q": 1, "W": 0, "E": 0, "R": 0})
        r5 = _parse(chogath_data, ALL_MAXED)
        assert r1["Q"]["cooldown"] == pytest.approx(6.0)
        assert r5["Q"]["cooldown"] == pytest.approx(6.0)


# ---------------------------------------------------------------------------
# W: Feral Scream
# ---------------------------------------------------------------------------


class TestWFeralScream:
    """W: single-hit magic nuke, 80-280 + 70% AP; silence never leaks."""

    def test_w_is_magic_damage(self, chogath_data, parse_at) -> None:
        _, abilities = parse_at(chogath_data, 9)
        assert abilities["W"]["damage_type"] == "magic"

    def test_w_rank5_100_ap(self, chogath_data) -> None:
        """W rank 5 with 100 AP: 280 + 70 = 350 (spec sanity check) —
        exact value proves the Silence Duration entry never leaks in."""
        abilities = _parse(chogath_data, ALL_MAXED, ap=100.0)
        assert abilities["W"]["total_raw"] == pytest.approx(350.0)

    def test_w_rank1_no_ap(self, chogath_data) -> None:
        abilities = _parse(chogath_data, {"Q": 0, "W": 1, "E": 0, "R": 0})
        assert abilities["W"]["total_raw"] == pytest.approx(80.0)

    def test_w_cooldown(self, chogath_data) -> None:
        """W cooldown 11/10.5/10/9.5/9."""
        r1 = _parse(chogath_data, {"Q": 0, "W": 1, "E": 0, "R": 0})
        r5 = _parse(chogath_data, ALL_MAXED)
        assert r1["W"]["cooldown"] == pytest.approx(11.0)
        assert r5["W"]["cooldown"] == pytest.approx(9.0)


# ---------------------------------------------------------------------------
# E: Vorpal Spikes
# ---------------------------------------------------------------------------


class TestEVorpalSpikes:
    """E: 3 empowered attacks; per hit = base + 30% AP + %maxHP (+ rider)."""

    def test_e_is_magic_damage(self, chogath_data) -> None:
        abilities = _parse(chogath_data, ALL_MAXED)
        assert abilities["E"]["damage_type"] == "magic"

    def test_e_rank5_100_ap_6_stacks(self, chogath_data) -> None:
        """Spec sanity check: rank 5, 100 AP, 6 stacks, 2000 max-HP
        target: per hit = 100 + 30 + (3.9% + 3.0%) x 2000 = 268;
        3 hits = 804."""
        abilities = _parse(
            chogath_data, ALL_MAXED, ap=100.0, options={"feast_stacks": 6}
        )
        (part,) = abilities["E"]["parts"]
        assert part.amount == pytest.approx(268.0)
        assert part.count == 3
        assert abilities["E"]["total_raw"] == pytest.approx(804.0)

    def test_e_zero_stacks(self, chogath_data) -> None:
        """No stacks: per hit = 100 + 30 + 3.9% x 2000 = 208; x3 = 624."""
        abilities = _parse(
            chogath_data, ALL_MAXED, ap=100.0, options={"feast_stacks": 0}
        )
        assert abilities["E"]["total_raw"] == pytest.approx(624.0)

    def test_e_default_stacks_is_6(self, chogath_data) -> None:
        """Absent option -> the declared default (6, the minion cap)."""
        abilities = _parse(chogath_data, ALL_MAXED, ap=100.0)
        assert abilities["E"]["total_raw"] == pytest.approx(804.0)

    def test_e_stacks_require_ranked_r(self, chogath_data) -> None:
        """Feast stacks only exist once R is ranked: with R at rank 0
        the option grants no rider (same as zero stacks)."""
        abilities = _parse(chogath_data, NO_R, ap=100.0, options={"feast_stacks": 6})
        assert abilities["E"]["total_raw"] == pytest.approx(624.0)

    def test_e_rank1_no_ap_no_stacks(self, chogath_data) -> None:
        """Rank 1, 0 AP: per hit = 20 + 2.5% x 2000 = 70; x3 = 210."""
        abilities = _parse(
            chogath_data,
            {"Q": 0, "W": 0, "E": 1, "R": 0},
        )
        assert abilities["E"]["total_raw"] == pytest.approx(210.0)

    def test_e_empowers_three_autos(self, chogath_data) -> None:
        """E rides/forces exactly 3 basic attacks per cast."""
        abilities = _parse(chogath_data, ALL_MAXED)
        assert abilities["E"]["empowers_next_auto"] == {"hits": 3}

    def test_e_cooldown(self, chogath_data) -> None:
        """E cooldown 8/7/6/5/4."""
        r1 = _parse(chogath_data, {"Q": 0, "W": 0, "E": 1, "R": 0})
        r5 = _parse(chogath_data, ALL_MAXED)
        assert r1["E"]["cooldown"] == pytest.approx(8.0)
        assert r5["E"]["cooldown"] == pytest.approx(4.0)

    def test_e_json_total_is_three_times_per_hit(self, chogath_data) -> None:
        """Lock the x3 hit count against the JSON's own pre-multiplied
        "Total Magic Damage" entry (its flat base is 3x the per-hit)."""
        ability = chogath_data["abilities"]["E"][0]
        for rank in range(1, 6):
            per_hit = extract_value(ability, "Magic Damage", rank)
            total = extract_value(ability, "Total Magic Damage", rank)
            assert total == pytest.approx(3 * per_hit)

    def test_e_one_rotation_row_is_three_full_attacks(
        self, chogath_data, parse_at
    ) -> None:
        """One-rotation mode: no auto stream, so the cast carries its 3
        forced basic swings — row = 3 x (base attack + spike bonus)."""
        stats, abilities = parse_at(
            chogath_data, 18, target_stats={"target_max_health": 5000.0}
        )
        result = calculate_fight_damage(
            stats,
            abilities,
            [],
            FightConfig(
                target_health=5000,
                target_armor=0,
                target_magic_resistance=0,
                fight_duration_seconds=5.0,
                auto_attack_uptime=0.0,
                one_rotation=True,
                deterministic=True,
            ),
        )
        expected = 3.0 * stats["attack_damage"] + abilities["E"]["total_raw"]
        assert result["breakdown"]["E"]["total_damage"] == pytest.approx(expected)

    def test_e_timed_casts_capped_by_autos_over_three(
        self, chogath_data, parse_at
    ) -> None:
        """Timed fights with autos: each cast empowers 3 autos in the
        stream, so casts are capped at floor(autos / 3)."""
        stats, abilities = parse_at(
            chogath_data, 18, target_stats={"target_max_health": 5000.0}
        )
        stats["attack_speed"] = 0.5  # 8s x 0.5 AS = 4 autos -> cap 1
        result = calculate_fight_damage(
            stats,
            abilities,
            [],
            FightConfig(
                target_health=5000,
                target_armor=0,
                target_magic_resistance=0,
                fight_duration_seconds=8.0,
                auto_attack_uptime=1.0,
                one_rotation=False,
                deterministic=True,
            ),
        )
        assert result["breakdown"]["E"]["casts"] == 1


# ---------------------------------------------------------------------------
# R: Feast
# ---------------------------------------------------------------------------


class TestRFeast:
    """R: true damage off buffed bonus health + the stack health buff."""

    def test_r_is_true_damage(self, chogath_data) -> None:
        abilities = _parse(chogath_data, ALL_MAXED)
        assert abilities["R"]["damage_type"] == "true"

    def test_r_rank3_100_ap_6_stacks(self, chogath_data) -> None:
        """Spec sanity check: 6 stacks x 160 = 960 bonus health ->
        650 + 50 + 96 = 796 true damage."""
        abilities = _parse(
            chogath_data, ALL_MAXED, ap=100.0, options={"feast_stacks": 6}
        )
        assert abilities["R"]["total_raw"] == pytest.approx(796.0)

    def test_r_rank1_no_ap_no_stacks(self, chogath_data) -> None:
        abilities = _parse(
            chogath_data,
            {"Q": 0, "W": 0, "E": 0, "R": 1},
            options={"feast_stacks": 0},
        )
        assert abilities["R"]["total_raw"] == pytest.approx(300.0)

    def test_r_ratio_includes_item_bonus_health(self, chogath_data) -> None:
        """Existing bonus health (items) feeds the 10% ratio alongside
        stack health: 650 + 50 + 10% x (1000 + 960) = 896."""
        stats = dict(STATS_100_AD, bonus_health=1000.0)
        abilities = _parse(
            chogath_data,
            ALL_MAXED,
            ap=100.0,
            stats=stats,
            options={"feast_stacks": 6},
        )
        assert abilities["R"]["total_raw"] == pytest.approx(896.0)

    def test_r_stat_buff_scales_with_rank(self, chogath_data) -> None:
        """Stack health is retroactive to R rank: 80/120/160 per stack."""
        r1 = _parse(
            chogath_data,
            {"Q": 0, "W": 0, "E": 0, "R": 1},
            options={"feast_stacks": 6},
        )
        r3 = _parse(chogath_data, ALL_MAXED, options={"feast_stacks": 6})
        assert r1["R"]["stat_buff"] == {"bonus_health": pytest.approx(480.0)}
        assert r3["R"]["stat_buff"] == {"bonus_health": pytest.approx(960.0)}

    def test_r_unranked_absent(self, chogath_data) -> None:
        """R at rank 0: no damage entry and no stack health anywhere."""
        abilities = _parse(chogath_data, NO_R, options={"feast_stacks": 6})
        assert "R" not in abilities

    def test_r_cooldown(self, chogath_data) -> None:
        """R cooldown 80/70/60."""
        r1 = _parse(chogath_data, {"Q": 0, "W": 0, "E": 0, "R": 1})
        r3 = _parse(chogath_data, ALL_MAXED)
        assert r1["R"]["cooldown"] == pytest.approx(80.0)
        assert r3["R"]["cooldown"] == pytest.approx(60.0)

    def test_fight_stats_show_buffed_health(self, chogath_data, parse_at) -> None:
        """The fight engine applies the stack health to champion stats:
        max health AND bonus health both rise by 6 x 160 = 960 (the
        Gnar UI-panel pattern — run_fight's champion_stats must show
        the buffed values)."""
        stats, abilities = parse_at(chogath_data, 18)
        health_before = stats["health"]
        bonus_before = stats["bonus_health"]
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
        assert stats["health"] == pytest.approx(health_before + 960.0)
        assert stats["bonus_health"] == pytest.approx(bonus_before + 960.0)

    def test_stack_health_feeds_overlords_bloodmail(
        self, chogath_data, parse_at
    ) -> None:
        """Feast stack health is BONUS health: Overlord's Bloodmail
        converts it to AD at fight time (2.5% x 960 = +24 AD on top of
        the item-health conversion already in the parse stats)."""
        bloodmail = get_item_by_name("Overlord's Bloodmail")
        stats, abilities = parse_at(chogath_data, 18, items=[bloodmail])
        ad_before = stats["attack_damage"]
        calculate_fight_damage(
            stats,
            abilities,
            [bloodmail],
            FightConfig(
                target_health=2000,
                target_armor=100,
                target_magic_resistance=60,
                fight_duration_seconds=5.0,
                one_rotation=True,
            ),
        )
        assert stats["attack_damage"] == pytest.approx(ad_before + 0.025 * 960.0)


# ---------------------------------------------------------------------------
# Passive: Carnivore (kill-triggered heal/mana — no combat-damage interaction)
# ---------------------------------------------------------------------------


class TestPPassiveCarnivore:
    """P (Carnivore) heals ONLY on an enemy kill, which a duel does not
    simulate: the row exists exactly when the user declares the kills."""

    def test_no_receipt_without_declared_kills(self, chogath_data, parse_at) -> None:
        _, abilities = parse_at(chogath_data, 9)
        assert "passive" not in abilities
        assert "P" not in abilities

    def test_declared_kills_emit_a_sourced_zero_damage_receipt(
        self, chogath_data, parse_at
    ) -> None:
        _, abilities = parse_at(
            chogath_data, 9, champion_options={"p_carnivore_kills": 2}
        )
        entry = abilities["passive"]
        assert entry["name"] == "Carnivore"
        assert entry["total_raw"] == 0.0
        assert entry["parts"] == ()
        assert entry["detail"]
        # The level row the heal rule spends: 18 : 52 by level, level 9.
        assert entry["self_heal_state"] == {"kills": 2, "amount": 34.0}


class TestReviewedCrowdControl:
    """Cho'Gath's crowd-control review, whole kit.

    Q's knock-up lands with the rupture, on the sourced delay the row
    authors; E's slow rides the three basic attacks it empowers, on the
    events the fight engine authors from the swings they consume.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Cho'Gath")
        assert chogath.MODULE_CC == {
            "P": "none",
            "Q": "knockup",
            "W": "silence",
            "E": "slow",
            "R": "none",
        }
        assert "slowed by an amount that decays over 1.5 seconds" in (
            cc_review.slot_text(data, "E")
        )
        assert "knocking them up for 1 second" in cc_review.slot_text(data, "Q")
        assert "silenced for a duration" in cc_review.slot_text(data, "W")
        assert cc_review.control_words(cc_review.slot_text(data, "W")) == []
        assert cc_review.control_words(cc_review.slot_text(data, "R")) == []

    def test_rupture_lands_on_the_cast_time_plus_its_sourced_delay(self):
        """The cached note says the delay excludes the cast time."""
        data = cc_review.kit("Cho'Gath")
        assert "after a 0.627 seconds delay" in cc_review.slot_text(data, "Q")
        entry = data["abilities"]["Q"][0]
        assert "The delay before the rupture does not include the cast time." in (
            entry["notes"]
        )
        assert entry["castTime"] == "0.5"
        parsed = parse_abilities(data, 20, 100.0, {"Q": 5, "W": 5, "E": 5, "R": 3})
        (part,) = parsed["Q"]["parts"]
        assert part.time_offset == pytest.approx(1.127)
        assert part.cc_kind == "knockup"

    def test_the_whole_kit_is_reviewed_and_the_fight_certifies(self):
        assert cc_review.unreviewed_ability_slots("Cho'Gath") == []
        coverage = cc_review.fimbulwinter_coverage("Cho'Gath")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


class TestModuleCoverage:
    """Every slot is covered, and P is ``modeled`` rather than no_damage:
    its receipt carries the Carnivore heal the self-heal rule places."""

    def test_all_five_slots_covered(self) -> None:
        from src.calculator.champions import get_champion_module_contract

        contract = get_champion_module_contract("Cho'Gath")
        assert contract.coverage == {
            "P": "modeled",
            "Q": "modeled",
            "W": "modeled",
            "E": "modeled",
            "R": "modeled",
        }
