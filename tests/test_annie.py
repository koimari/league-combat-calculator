"""Tests for Annie champion module."""

import copy

import pytest

from src.calculator.champions import annie, parse_champion_abilities
from tests import cc_review

# The Pyromania walk reads cooldowns, so every walk test parses at zero
# haste: Q 4s, W 7s, E 10s, R 100s at rank 3 are then the cached numbers
# themselves and the cast stream is hand-checkable.
_NO_HASTE = {"ability_haste": 0.0, "basic_ability_haste": 0.0, "ability_power": 0.0}
_MAX_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}


def _walk(annie_data, level=18, **options):
    """Annie's Pyromania row over a timed window at zero haste."""
    parsed = parse_champion_abilities(
        annie_data,
        level,
        0.0,
        _MAX_RANKS,
        champion_stats=dict(_NO_HASTE),
        champion_options=options or None,
    )
    return parsed["P"]


# ---------------------------------------------------------------------------
# P: Pyromania (stun only, no damage)
# ---------------------------------------------------------------------------


class TestPassivePyromania:
    def test_passive_exists(self, annie_data, parse_at) -> None:
        _, abilities = parse_at(annie_data, 5)
        assert "P" in abilities

    def test_passive_no_damage(self, annie_data, parse_at) -> None:
        _, abilities = parse_at(annie_data, 5)
        assert abilities["P"]["total_raw"] == 0.0

    def test_passive_name_from_json(self, annie_data, parse_at) -> None:
        _, abilities = parse_at(annie_data, 5)
        assert abilities["P"]["name"] == "Pyromania"


class TestPyromaniaChargeWalk:
    """P: the cross-slot charge, walked over the fight's own casts.

    At zero haste a 10s window schedules Q at 0/4/8, W at 0/7, E at 0/10
    and R at 0, in that tie-broken order — so the charge and every cast
    that spends it are hand-countable.
    """

    def test_the_opening_charge_stuns_the_first_spender_cast(self, annie_data):
        """Full at the opening: Q at t=0 spends it, then W at t=7."""
        row = _walk(annie_data, fight_duration_seconds=10.0)
        assert "2 Energized stun(s) of 1.75s" in row["detail"]
        assert "stuns at 0.00s, 7.00s" in row["detail"]
        assert "charge 4/4 at the opening, 2/4 at the end" in row["detail"]

    def test_an_empty_opening_charge_takes_four_casts_to_fill(self, annie_data):
        """From 0/4 the four t=0 casts fill it and Q at t=4 spends it."""
        row = _walk(annie_data, fight_duration_seconds=10.0, pyromania_stacks=0)
        assert "1 Energized stun(s)" in row["detail"]
        assert "stuns at 4.00s" in row["detail"]
        assert "charge 0/4 at the opening, 3/4 at the end" in row["detail"]

    def test_molten_shield_charges_but_never_spends(self, annie_data):
        """E is absent from the cached Energized sentence, so it cannot stun.

        With only E learned the walk charges on every E cast and reaches
        the cap without ever spending it.
        """
        parsed = parse_champion_abilities(
            annie_data,
            18,
            0.0,
            {"Q": 0, "W": 0, "E": 5, "R": 0},
            champion_stats=dict(_NO_HASTE),
            champion_options={"fight_duration_seconds": 40.0, "pyromania_stacks": 0},
        )
        assert "0 Energized stun(s)" in parsed["P"]["detail"]
        assert "charge 0/4 at the opening, 4/4 at the end" in parsed["P"]["detail"]

    def test_an_autos_only_window_never_moves_the_charge(self, annie_data):
        row = _walk(
            annie_data,
            fight_duration_seconds=10.0,
            pyromania_stacks=1,
            auto_attacks_only=True,
        )
        assert "charge 1/4 at the opening, 1/4 at the end" in row["detail"]

    @pytest.mark.parametrize(
        ("level", "seconds"),
        [
            (1, "1.25s"),
            (5, "1.25s"),
            (6, "1.5s"),
            (10, "1.5s"),
            (11, "1.75s"),
            (18, "1.75s"),
        ],
    )
    def test_the_stun_steps_at_the_game_files_breakpoints(
        self, annie_data, level, seconds
    ):
        """The three values come from the cache, the levels from the bin.

        The cached entry says "1.25 / 1.5 / 1.75 (based on level)" and
        names no level, so the breakpoints are the game record's:
        AnniePassive's StunDuration is a ByCharLevelBreakpointsCalculation
        with mLevel1Value 1.25 and +0.25 at mLevel 6 and mLevel 11 (see the
        HARDCODED marker on ``_STUN_BREAKPOINT_LEVELS``).  Both edges of
        every step are pinned, so a silent shift to 1/7/13 turns this red.
        """
        assert annie._STUN_BREAKPOINT_LEVELS == (11, 6, 1)
        assert seconds in _walk(annie_data, level=level)["detail"]

    def test_a_cache_that_stops_stating_the_cap_fails_closed(self, annie_data):
        data = copy.deepcopy(annie_data)
        effect = data["abilities"]["P"][0]["effects"][0]
        effect["description"] = effect["description"].replace("stacking up to 4", "")
        with pytest.raises(ValueError, match="charge cap has no source"):
            parse_champion_abilities(data, 18, 0.0, _MAX_RANKS)

    def test_a_cache_that_stops_naming_a_spender_fails_closed(self, annie_data):
        data = copy.deepcopy(annie_data)
        data["abilities"]["P"][0]["effects"][1]["description"] = (
            "Energized: Annie empowers her next cast to stun enemies hit "
            "for 1.25 / 1.5 / 1.75 (based on level) seconds."
        )
        with pytest.raises(ValueError, match="no slot can be said to spend"):
            parse_champion_abilities(data, 18, 0.0, _MAX_RANKS)


# ---------------------------------------------------------------------------
# Q: Disintegrate
# ---------------------------------------------------------------------------


class TestQDisintegrate:
    def test_q_is_magic_damage(self, annie_data, parse_at) -> None:
        _, abilities = parse_at(annie_data, 5)
        assert abilities["Q"]["damage_type"] == "magic"

    def test_q_has_cooldown(self, annie_data, parse_at) -> None:
        _, abilities = parse_at(annie_data, 5)
        assert abilities["Q"]["cooldown"] > 0

    def test_q_rank5_no_ap(self, annie_data, parse_at) -> None:
        """Rank 5 Q with 0 AP should deal 260 magic damage."""
        _, abilities = parse_at(
            annie_data,
            5,
            ap=0.0,
            ability_ranks={"Q": 5, "R": 0},
        )
        assert abilities["Q"]["total_raw"] == pytest.approx(260.0)

    def test_q_rank5_with_100ap(self, annie_data, parse_at) -> None:
        """Rank 5 Q with 100 AP: 260 + 80 = 340 magic damage."""
        _, abilities = parse_at(
            annie_data,
            5,
            ap=100.0,
            ability_ranks={"Q": 5, "R": 0},
        )
        assert abilities["Q"]["total_raw"] == pytest.approx(340.0)

    def test_q_rank1_base(self, annie_data, parse_at) -> None:
        _, abilities = parse_at(
            annie_data,
            1,
            ap=0.0,
            ability_ranks={"Q": 1, "R": 0},
        )
        assert abilities["Q"]["total_raw"] == pytest.approx(80.0)


# ---------------------------------------------------------------------------
# W: Incinerate
# ---------------------------------------------------------------------------


class TestWIncinerate:
    def test_w_is_magic_damage(self, annie_data, parse_at) -> None:
        _, abilities = parse_at(annie_data, 3)
        assert abilities["W"]["damage_type"] == "magic"

    def test_w_has_cooldown(self, annie_data, parse_at) -> None:
        _, abilities = parse_at(annie_data, 3)
        assert abilities["W"]["cooldown"] > 0

    def test_w_rank5_no_ap(self, annie_data, parse_at) -> None:
        """Rank 5 W with 0 AP should deal 230 magic damage."""
        _, abilities = parse_at(
            annie_data,
            5,
            ap=0.0,
            ability_ranks={"W": 5, "R": 0},
        )
        assert abilities["W"]["total_raw"] == pytest.approx(230.0)

    def test_w_rank5_with_100ap(self, annie_data, parse_at) -> None:
        """Rank 5 W with 100 AP: 230 + 80 = 310 magic damage."""
        _, abilities = parse_at(
            annie_data,
            5,
            ap=100.0,
            ability_ranks={"W": 5, "R": 0},
        )
        assert abilities["W"]["total_raw"] == pytest.approx(310.0)


# ---------------------------------------------------------------------------
# E: Molten Shield (skipped — no offensive damage)
# ---------------------------------------------------------------------------


class TestEMoltenShield:
    def test_e_exists_with_name(self, annie_data, parse_at) -> None:
        _, abilities = parse_at(annie_data, 5)
        assert "E" in abilities
        assert abilities["E"]["name"] == "Molten Shield"

    def test_e_no_damage(self, annie_data, parse_at) -> None:
        """No declared enemy strikes the shield, so nothing retaliates."""
        _, abilities = parse_at(annie_data, 5)
        assert abilities["E"]["total_raw"] == 0.0

    def test_e_prices_the_cached_retaliation_row_per_declared_enemy(
        self, annie_data, parse_at
    ) -> None:
        """Rank 5 retaliation: 65 + 40% of 100 AP = 105 per enemy struck."""
        _, abilities = parse_at(
            annie_data,
            18,
            ap=100.0,
            ability_ranks={"E": 5, "R": 0},
            champion_options={"e_shield_retaliations": 3},
        )
        assert abilities["E"]["total_raw"] == pytest.approx(315.0)
        (part,) = abilities["E"]["parts"]
        assert (part.amount, part.count) == (pytest.approx(105.0), 3)

    def test_one_retaliation_is_a_certified_landing(self, annie_data, parse_at) -> None:
        """One strike is one hit; several are an aggregate with no boundary."""
        _, one = parse_at(
            annie_data,
            18,
            ability_ranks={"E": 5, "R": 0},
            champion_options={"e_shield_retaliations": 1},
        )
        _, many = parse_at(
            annie_data,
            18,
            ability_ranks={"E": 5, "R": 0},
            champion_options={"e_shield_retaliations": 4},
        )
        assert one["E"]["event_order_certified"] == "single_hit"
        assert "event_order_certified" not in many["E"]

    def test_a_cache_without_the_retaliation_row_fails_closed(self, annie_data) -> None:
        data = copy.deepcopy(annie_data)
        data["abilities"]["E"][0]["effects"][1]["leveling"] = []
        with pytest.raises(ValueError, match="no longer carries a"):
            parse_champion_abilities(data, 18, 0.0, _MAX_RANKS)


# ---------------------------------------------------------------------------
# R: Summon: Tibbers
# ---------------------------------------------------------------------------


class TestRSummonTibbers:
    def test_r_is_magic_damage(self, annie_data, parse_at) -> None:
        _, abilities = parse_at(annie_data, 6)
        assert abilities["R"]["damage_type"] == "magic"

    def test_r_has_cooldown(self, annie_data, parse_at) -> None:
        _, abilities = parse_at(annie_data, 6)
        assert abilities["R"]["cooldown"] > 0

    def test_r_rank3_burst_with_100ap(self, annie_data, parse_at) -> None:
        """Rank 3 R burst with 100 AP: 400 + 75 = 475 magic damage."""
        _, abilities = parse_at(
            annie_data,
            16,
            ap=100.0,
            ability_ranks={"R": 3},
        )
        assert abilities["R"]["initial_burst"] == pytest.approx(475.0)

    def test_r_rank3_aura_per_tick_with_100ap(
        self,
        annie_data,
        parse_at,
    ) -> None:
        """Rank 3 R aura per tick with 100 AP: 4 + 1 = 5."""
        _, abilities = parse_at(
            annie_data,
            16,
            ap=100.0,
            ability_ranks={"R": 3},
        )
        assert abilities["R"]["tibbers_aura"]["damage_per_tick"] == (pytest.approx(5.0))

    def test_r_rank3_aura_total_5s(self, annie_data, parse_at) -> None:
        """Rank 3 R aura over 5s with 100 AP: 5 * 20 ticks = 100."""
        _, abilities = parse_at(
            annie_data,
            16,
            ap=100.0,
            ability_ranks={"R": 3},
        )
        assert abilities["R"]["tibbers_aura"]["aura_total"] == (pytest.approx(100.0))

    def test_r_total_damage_burst_plus_aura(
        self,
        annie_data,
        parse_at,
    ) -> None:
        """Total R = burst + aura: 475 + 100 = 575 at rank 3, 100 AP."""
        _, abilities = parse_at(
            annie_data,
            16,
            ap=100.0,
            ability_ranks={"R": 3},
        )
        assert abilities["R"]["total_raw"] == pytest.approx(575.0)

    def test_r_aura_ticks(self, annie_data, parse_at) -> None:
        """Default 5s aura = 20 ticks."""
        _, abilities = parse_at(annie_data, 6)
        assert abilities["R"]["tibbers_aura"]["total_ticks"] == (pytest.approx(20.0))

    def test_r_custom_aura_duration(self, annie_data, parse_at) -> None:
        """Custom aura duration changes total aura damage."""
        _, abilities = parse_at(
            annie_data,
            16,
            ap=100.0,
            ability_ranks={"R": 3},
            champion_options={"tibbers_aura_seconds": 10.0},
        )
        # 10s = 40 ticks, 5 dmg/tick = 200 aura damage
        assert abilities["R"]["tibbers_aura"]["total_ticks"] == (pytest.approx(40.0))
        assert abilities["R"]["tibbers_aura"]["aura_total"] == (pytest.approx(200.0))


# ---------------------------------------------------------------------------
# R passive: Magic Penetration
# ---------------------------------------------------------------------------


class TestRMagicPenetration:
    def test_r_stat_buff_has_magic_pen(self, annie_data, parse_at) -> None:
        _, abilities = parse_at(annie_data, 6)
        assert "stat_buff" in abilities["R"]
        assert abilities["R"]["stat_buff"]["magic_penetration_percent"] > 0

    def test_r_rank1_magic_pen_10(self, annie_data, parse_at) -> None:
        _, abilities = parse_at(
            annie_data,
            6,
            ability_ranks={"R": 1},
        )
        assert abilities["R"]["stat_buff"]["magic_penetration_percent"] == (
            pytest.approx(10.0)
        )

    def test_r_rank3_magic_pen_20(self, annie_data, parse_at) -> None:
        _, abilities = parse_at(
            annie_data,
            16,
            ability_ranks={"R": 3},
        )
        assert abilities["R"]["stat_buff"]["magic_penetration_percent"] == (
            pytest.approx(20.0)
        )

    def test_r_pen_applied_before_q(self, annie_data, parse_at) -> None:
        """When R is ranked, Q should still calculate correctly.

        The magic pen is a stat buff — it doesn't change Q's raw damage,
        but it should be present in the R stat_buff for the fight engine.
        Q raw damage remains the same regardless of pen.
        """
        _, abilities_with_r = parse_at(
            annie_data,
            9,
            ap=100.0,
            ability_ranks={"Q": 5, "R": 1},
        )
        _, abilities_no_r = parse_at(
            annie_data,
            9,
            ap=100.0,
            ability_ranks={"Q": 5, "R": 0},
        )
        # Raw damage should be the same (pen affects post-mitigation)
        assert abilities_with_r["Q"]["total_raw"] == (abilities_no_r["Q"]["total_raw"])
        # But R stat_buff should carry the pen
        assert abilities_with_r["R"]["stat_buff"][
            "magic_penetration_percent"
        ] == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# Pre-level-6 (no R)
# ---------------------------------------------------------------------------


class TestPreLevel6:
    def test_no_r_before_level_6(self, annie_data, parse_at) -> None:
        _, abilities = parse_at(annie_data, 5)
        assert "R" not in abilities

    def test_q_works_without_r(self, annie_data, parse_at) -> None:
        _, abilities = parse_at(annie_data, 5, ap=100.0)
        assert abilities["Q"]["total_raw"] > 0


class TestReviewedCrowdControl:
    """Annie's crowd-control review, and the slots that still withhold.

    Pyromania's stun is stack state, not slot state: the charge is
    cross-slot, so which casts of Q, W or R are the empowered ones is a
    property of the fight's cast stream and neither a slot-wide stun nor
    a slot-wide 'none' is true of any of them.  The walk on P's own row
    is where the derived stun schedule is published instead.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        passive = cc_review.slot_text(cc_review.kit("Annie"), "P")
        assert annie.MODULE_CC == {
            "P": "stun",
            "Q": "per_part",
            "W": "per_part",
            "E": "none",
            "R": "per_part",
        }
        assert annie.parse_abilities.cc_kinds == annie.MODULE_CC
        assert (
            "annie generates a stack of pyromania whenever she hits an "
            "enemy with disintegrate or casts her other abilities, "
            "stacking up to 4 times" in passive
        )
        assert (
            "annie empowers her next cast of disintegrate, incinerate, or "
            "summon: tibbers to consume all pyromania stacks to stun "
            "enemies hit" in passive
        )

    def test_no_damaging_slot_states_a_control_of_its_own(self):
        data = cc_review.kit("Annie")
        for slot in ("Q", "W", "R"):
            assert cc_review.control_words(cc_review.slot_text(data, slot)) == [], slot

    def test_the_unreviewable_slots_keep_the_fight_coarse(self):
        assert cc_review.unreviewed_ability_slots("Annie") == ["Q", "R", "W"]
        coverage = cc_review.fimbulwinter_coverage("Annie")
        assert coverage["complete"] is False
        assert "fimbulwinter_everlasting" in coverage["coarse_sources"]
