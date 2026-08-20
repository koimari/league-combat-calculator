"""Tests for Blitzcrank champion ability parsing and damage calculation.

Reference damage (wiki: https://wiki.leagueoflegends.com/en-us/Blitzcrank):
- Q (Rocket Grab) rank 5: 310 + 120% AP magic damage.
- W (Overdrive): 30-70% bonus attack speed for the first 5 seconds of
  the fight, zero damage.
- E (Power Fist): next basic attack deals 100% total AD (+ 25% AP)
  BONUS physical damage (rank-independent; only the cooldown scales),
  affected by critical strike modifiers.
- R (Static Field) active rank 3: 525 + 100% AP magic damage. The
  passive lightning bolts (50/100/150 + 30-50% AP + 2% max mana) are
  deliberately NOT modeled and must never leak into any total.
"""

import pytest

from src.calculator.champions import parse_champion_abilities as parse_abilities
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.resistance import apply_resistance
from src.calculator.data_fetcher import get_item_by_name
from src.calculator.champions import blitzcrank
from tests import cc_review

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ALL_MAXED = {"Q": 5, "W": 5, "E": 5, "R": 3}

STATS_100_AD = {
    "attack_damage": 100.0,
    "bonus_attack_damage": 0.0,
}


def _parse(data, ranks, ap=0.0, stats=None, options=None):
    """Parse at level 18 with explicit ranks (skill-order independent)."""
    return parse_abilities(
        data,
        18,
        ap,
        ability_ranks=ranks,
        champion_options=options,
        champion_stats=dict(stats or STATS_100_AD),
    )


# ---------------------------------------------------------------------------
# Q: Rocket Grab
# ---------------------------------------------------------------------------


class TestQRocketGrab:
    """Q: single-hit magic nuke, 110-310 + 120% AP."""

    def test_q_is_magic_damage(self, blitzcrank_data, parse_at) -> None:
        _, abilities = parse_at(blitzcrank_data, 9)
        assert "Q" in abilities
        assert abilities["Q"]["damage_type"] == "magic"

    def test_q_rank5_no_ap(self, blitzcrank_data) -> None:
        """Q rank 5 with 0 AP: 310 magic pre-mitigation."""
        abilities = _parse(blitzcrank_data, ALL_MAXED, ap=0.0)
        assert abilities["Q"]["total_raw"] == pytest.approx(310.0)

    def test_q_rank5_100_ap(self, blitzcrank_data) -> None:
        """Q rank 5 with 100 AP: 310 + 120 = 430."""
        abilities = _parse(blitzcrank_data, ALL_MAXED, ap=100.0)
        assert abilities["Q"]["total_raw"] == pytest.approx(430.0)

    def test_q_rank1_no_ap(self, blitzcrank_data) -> None:
        """Q rank 1 with 0 AP: 110."""
        abilities = _parse(blitzcrank_data, {"Q": 1, "W": 0, "E": 0, "R": 0})
        assert abilities["Q"]["total_raw"] == pytest.approx(110.0)

    def test_q_cooldown(self, blitzcrank_data) -> None:
        """Q cooldown 20/19/18/17/16."""
        r1 = _parse(blitzcrank_data, {"Q": 1, "W": 0, "E": 0, "R": 0})
        r5 = _parse(blitzcrank_data, ALL_MAXED)
        assert r1["Q"]["cooldown"] == pytest.approx(20.0)
        assert r5["Q"]["cooldown"] == pytest.approx(16.0)


# ---------------------------------------------------------------------------
# W: Overdrive
# ---------------------------------------------------------------------------


class TestWOverdrive:
    """W: timed attack-speed steroid, zero damage."""

    def test_w_deals_no_damage(self, blitzcrank_data) -> None:
        abilities = _parse(blitzcrank_data, ALL_MAXED)
        assert abilities["W"]["total_raw"] == 0.0
        assert sum(part.amount for part in abilities["W"]["parts"]) == 0.0

    def test_w_rank5_full_buff_without_duration(self, blitzcrank_data) -> None:
        """Per-cast model (no fight duration): the full 70% is granted."""
        abilities = _parse(blitzcrank_data, ALL_MAXED)
        assert abilities["W"]["stat_buff"]["bonus_attack_speed"] == pytest.approx(70.0)

    def test_w_rank1_buff(self, blitzcrank_data) -> None:
        abilities = _parse(blitzcrank_data, {"Q": 0, "W": 1, "E": 0, "R": 0})
        assert abilities["W"]["stat_buff"]["bonus_attack_speed"] == pytest.approx(30.0)

    def test_w_buff_scaled_by_fight_window(self, blitzcrank_data) -> None:
        """10s fight: the 5s buff covers half the fight -> 70% * 5/10 = 35%."""
        abilities = _parse(
            blitzcrank_data,
            ALL_MAXED,
            options={"fight_duration_seconds": 10.0},
        )
        assert abilities["W"]["stat_buff"]["bonus_attack_speed"] == pytest.approx(35.0)

    def test_w_buff_full_for_short_fights(self, blitzcrank_data) -> None:
        """Fights <= 5s have the buff up throughout — no scaling."""
        for duration in (3.0, 5.0):
            abilities = _parse(
                blitzcrank_data,
                ALL_MAXED,
                options={"fight_duration_seconds": duration},
            )
            buff = abilities["W"]["stat_buff"]["bonus_attack_speed"]
            assert buff == pytest.approx(70.0)

    def test_w_zero_damage_in_fight_breakdown(self, blitzcrank_data, parse_at) -> None:
        """W appears in the fight breakdown at 0 damage (like Aatrox R)."""
        stats, abilities = parse_at(blitzcrank_data, 13)
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
        assert result["breakdown"]["W"]["total_damage"] == 0.0

    def test_w_buff_raises_fight_attack_speed(self, blitzcrank_data, parse_at) -> None:
        """The fight engine applies W's bonus AS to champion stats."""
        stats, abilities = parse_at(blitzcrank_data, 13)
        original_as = stats["attack_speed"]
        calculate_fight_damage(
            stats,
            abilities,
            [],
            FightConfig(
                target_health=2000,
                target_armor=100,
                target_magic_resistance=60,
                fight_duration_seconds=5.0,
                auto_attack_uptime=1.0,
                one_rotation=True,
            ),
        )
        assert stats["attack_speed"] > original_as


# ---------------------------------------------------------------------------
# E: Power Fist
# ---------------------------------------------------------------------------


class TestEPowerFist:
    """E: empowered-auto BONUS damage, 100% total AD + 25% AP, can crit."""

    def test_e_is_physical_damage(self, blitzcrank_data) -> None:
        abilities = _parse(blitzcrank_data, ALL_MAXED)
        assert abilities["E"]["damage_type"] == "physical"

    def test_e_rank1_100_ad_no_ap(self, blitzcrank_data) -> None:
        """E rank 1, 100 total AD, 0 AP: bonus is exactly 100 physical."""
        abilities = _parse(blitzcrank_data, {"Q": 0, "W": 0, "E": 1, "R": 0})
        assert abilities["E"]["total_raw"] == pytest.approx(100.0)

    def test_e_ap_ratio(self, blitzcrank_data) -> None:
        """E with 100 AD and 100 AP: 100 + 25 = 125."""
        abilities = _parse(blitzcrank_data, {"Q": 0, "W": 0, "E": 1, "R": 0}, ap=100.0)
        assert abilities["E"]["total_raw"] == pytest.approx(125.0)

    def test_e_damage_is_rank_independent(self, blitzcrank_data) -> None:
        """Only the cooldown scales with rank, never the damage."""
        r1 = _parse(blitzcrank_data, {"Q": 0, "W": 0, "E": 1, "R": 0})
        r5 = _parse(blitzcrank_data, {"Q": 0, "W": 0, "E": 5, "R": 0})
        assert r1["E"]["total_raw"] == pytest.approx(r5["E"]["total_raw"])

    def test_e_cooldown_scales(self, blitzcrank_data) -> None:
        """E cooldown 7/6.5/6/5.5/5."""
        r1 = _parse(blitzcrank_data, {"Q": 0, "W": 0, "E": 1, "R": 0})
        r5 = _parse(blitzcrank_data, {"Q": 0, "W": 0, "E": 5, "R": 0})
        assert r1["E"]["cooldown"] == pytest.approx(7.0)
        assert r5["E"]["cooldown"] == pytest.approx(5.0)

    def test_e_crit_scaling_enabled(self, blitzcrank_data) -> None:
        """The bonus damage is affected by crit modifiers (wiki) —
        full expected-crit effectiveness on the damage part."""
        abilities = _parse(blitzcrank_data, ALL_MAXED)
        (part,) = abilities["E"]["parts"]
        assert part.crit_effectiveness == 1.0

    def test_e_empowers_next_auto(self, blitzcrank_data) -> None:
        """E only lands through the next basic attack — casts must be
        gated by the auto stream (Vayne Q pattern)."""
        abilities = _parse(blitzcrank_data, ALL_MAXED)
        assert abilities["E"]["empowers_next_auto"] is True

    def test_e_zero_uptime_forces_its_attacks(self, blitzcrank_data, parse_at) -> None:
        """With zero AA uptime there is no auto stream to empower, but
        each E cast still forces its own punch: casts run on cooldown
        and every cast carries the base swing (was 0 damage)."""
        stats, abilities = parse_at(blitzcrank_data, 13)
        result = calculate_fight_damage(
            stats,
            abilities,
            [],
            FightConfig(
                target_health=2000,
                target_armor=100,
                target_magic_resistance=60,
                fight_duration_seconds=10.0,
                auto_attack_uptime=0.0,
                one_rotation=False,
            ),
        )
        row = result["breakdown"]["E"]
        assert row["casts"] > 0
        # Each cast is a full empowered hit: swing + bonus, so per-cast
        # damage must exceed the bonus-only raw total per cast.
        per_cast_raw = abilities["E"]["total_raw"]
        assert row["total_damage"] / row["casts"] > apply_resistance(
            per_cast_raw, 100.0
        )

    def test_e_one_rotation_carries_the_consumed_auto(
        self, blitzcrank_data, parse_at
    ) -> None:
        """One-rotation fights have no auto row, but casting E still
        punches: the row is the full empowered hit — base swing + bonus
        (in-game tooltip: 122 AD, 100 AP -> ~269, not the 147 bonus)."""
        stats, abilities = parse_at(blitzcrank_data, 13)
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
        expected = 2.0 * stats["attack_damage"] + 0.25 * stats["ability_power"]
        assert result["breakdown"]["E"]["total_damage"] == pytest.approx(expected)

    def test_e_one_rotation_forced_swing_consumes_spellblade(
        self, blitzcrank_data, parse_at
    ) -> None:
        """E's forced punch is a basic attack, so it consumes the Trinity
        Force spellblade charge even with no auto stream (was: spellblade
        silently absent in one-rotation mode)."""
        triforce = get_item_by_name("Trinity Force")
        stats, abilities = parse_at(blitzcrank_data, 13, items=[triforce])
        result = calculate_fight_damage(
            stats,
            abilities,
            [triforce],
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
        row = result["breakdown"]["spellblade_Trinity Force"]
        # One forced swing (E) -> exactly one proc at 200% base AD.
        assert row["count"] == 1
        assert row["total_damage"] == pytest.approx(2.0 * stats["base_attack_damage"])

    def test_e_crit_increases_fight_damage(self, blitzcrank_data, parse_at) -> None:
        """E's fight damage grows with crit chance (expected-crit model:
        100% crit at 200% crit damage doubles the bonus)."""

        def e_damage(crit_chance: float) -> float:
            stats, abilities = parse_at(blitzcrank_data, 13)
            stats["critical_strike_chance"] = crit_chance
            result = calculate_fight_damage(
                stats,
                abilities,
                [],
                FightConfig(
                    target_health=5000,
                    target_armor=0,
                    target_magic_resistance=0,
                    fight_duration_seconds=5.0,
                    auto_attack_uptime=1.0,
                    one_rotation=True,
                    deterministic=True,
                ),
            )
            return result["breakdown"]["E"]["total_damage"]

        assert e_damage(100.0) == pytest.approx(2.0 * e_damage(0.0))


# ---------------------------------------------------------------------------
# R: Static Field
# ---------------------------------------------------------------------------


class TestRStaticField:
    """R: active burst only — the passive lightning is never modeled."""

    def test_r_is_magic_damage(self, blitzcrank_data) -> None:
        abilities = _parse(blitzcrank_data, ALL_MAXED)
        assert abilities["R"]["damage_type"] == "magic"

    @pytest.mark.parametrize(("rank", "expected"), [(1, 275.0), (2, 400.0), (3, 525.0)])
    def test_r_active_no_ap(self, blitzcrank_data, rank, expected) -> None:
        """R active 275/400/525 at 0 AP — NOT the passive's 50/100/150."""
        abilities = _parse(blitzcrank_data, {"Q": 0, "W": 0, "E": 0, "R": rank})
        assert abilities["R"]["total_raw"] == pytest.approx(expected)

    @pytest.mark.parametrize(("rank", "expected"), [(1, 375.0), (2, 500.0), (3, 625.0)])
    def test_r_active_100_ap(self, blitzcrank_data, rank, expected) -> None:
        """100% AP ratio exactly — no passive 30-50% AP or 2% max mana
        leaking in (the champion has mana in stats, so any leak would
        break these exact values)."""
        abilities = _parse(
            blitzcrank_data,
            {"Q": 0, "W": 0, "E": 0, "R": rank},
            ap=100.0,
            stats={
                "attack_damage": 100.0,
                "bonus_attack_damage": 0.0,
                "max_mana": 1000.0,
            },
        )
        assert abilities["R"]["total_raw"] == pytest.approx(expected)

    def test_r_single_part_matches_total(self, blitzcrank_data) -> None:
        """One damage part, no hidden extra bolt entries anywhere."""
        abilities = _parse(blitzcrank_data, ALL_MAXED)
        (part,) = abilities["R"]["parts"]
        assert part.amount == pytest.approx(abilities["R"]["total_raw"])
        assert set(abilities) == {"Q", "W", "E", "R"}

    def test_r_cooldown(self, blitzcrank_data) -> None:
        """R cooldown 60/40/20."""
        r1 = _parse(blitzcrank_data, {"Q": 0, "W": 0, "E": 0, "R": 1})
        r3 = _parse(blitzcrank_data, {"Q": 0, "W": 0, "E": 0, "R": 3})
        assert r1["R"]["cooldown"] == pytest.approx(60.0)
        assert r3["R"]["cooldown"] == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# Passive: Mana Barrier (skip — defensive shield only)
# ---------------------------------------------------------------------------


class TestPassiveManaBarrier:
    """Passive is a defensive shield — absent from results."""

    def test_passive_not_in_results(self, blitzcrank_data, parse_at) -> None:
        _, abilities = parse_at(blitzcrank_data, 9)
        assert "passive" not in abilities
        assert "P" not in abilities


# ---------------------------------------------------------------------------
# Spellblade integration
# ---------------------------------------------------------------------------


class TestSpellbladeIntegration:
    """Q/W/E/R casts all ready spellblade; autos (including the E-empowered
    one) consume the procs — the engine's cast-vs-auto proc model."""

    def test_spellblade_procs_with_full_rotation(
        self, blitzcrank_data, parse_at
    ) -> None:
        # Sheen itself is a component; spellblade compiles on completed
        # items only. Trinity Force is the core Blitzcrank spellblade.
        triforce = get_item_by_name("Trinity Force")
        stats, abilities = parse_at(blitzcrank_data, 13, items=[triforce])
        result = calculate_fight_damage(
            stats,
            abilities,
            [triforce],
            FightConfig(
                target_health=5000,
                target_armor=50,
                target_magic_resistance=50,
                fight_duration_seconds=8.0,
                auto_attack_uptime=1.0,
                one_rotation=True,
                deterministic=True,
            ),
        )
        sb = result["breakdown"]["spellblade_Trinity Force"]
        # One-rotation: Q + W + E + R = 4 casts ready spellblade; the
        # auto stream (including the Power Fist auto) consumes procs.
        assert sb["count"] >= 1
        assert sb["total_damage"] > 0


class TestReviewedCrowdControl:
    """Blitzcrank's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Blitzcrank")
        assert blitzcrank.MODULE_CC == {
            "Q": "immobilize",
            "E": "knockup",
            "R": "silence",
        }
        assert "stunning them for 0.65 seconds, and pulling them" in " ".join(
            cc_review.slot_text(data, "Q").split()
        )
        assert "knock up the target for 1 second" in " ".join(
            cc_review.slot_text(data, "E").split()
        )
        # A silence is real control, and neither an immobilizing effect
        # nor a slow — so it is its own reviewed kind, not an absence.
        assert "silences them" in cc_review.slot_text(data, "R")
        assert cc_review.control_words(cc_review.slot_text(data, "R")) == []

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Blitzcrank") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Blitzcrank")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


def test_p_is_modeled_through_the_331_45_mana_barrier_shield() -> None:
    """P has no cast; the shield it grants rides Q's damage event.

    Mana Barrier grants 30% of Blitzcrank's maximum mana for 10 seconds —
    331.45 at level 18 with no items, the receipt behind P's ``modeled``
    label.
    """
    from src.calculator.champions import get_champion_module_contract
    from src.calculator.stats import calculate_total_stats

    contract = get_champion_module_contract("Blitzcrank")
    assert "P" not in contract.slots
    assert contract.coverage["P"] == "modeled"
    assert contract.coverage_channels["P"] == ("self_shield_events",)

    data = cc_review.kit("Blitzcrank")
    stats = calculate_total_stats(data, 18, [])
    parsed = parse_abilities(data, 18, stats["ability_power"], champion_stats=stats)
    (payload,) = parsed["Q"]["self_shield_events"]
    assert payload["source"] == "Mana Barrier"
    assert payload["amount"] == pytest.approx(331.45, abs=0.01)
    assert payload["duration"] == pytest.approx(10.0)
