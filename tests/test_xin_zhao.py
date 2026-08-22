"""Reviewed crowd control for Xin Zhao (MODULE_CC) — and the slot that
still withholds.

Wind Becomes Lightning and Audacious Charge slow; Crescent Guard displaces
only unChallenged targets, which the duel target never is.  Q prices one
of three empowered attacks, so it carries no slot-wide answer and this kit
stays coarse.
"""

import pytest

from src.calculator.champions import (
    get_champion_module_contract,
    parse_champion_abilities,
    xin_zhao,
)
from src.calculator.scenario import load_public_champion
from tests import cc_review, rider_probe, row_review


def _row_at_crit(slot, crit_chance_percent):
    """One parsed slot at the shared stat block plus a crit chance."""
    return parse_champion_abilities(
        load_public_champion("Xin Zhao"),
        18,
        row_review.STATS["ability_power"],
        row_review.RANKS,
        champion_stats={
            **row_review.STATS,
            "critical_strike_chance": crit_chance_percent,
        },
        target_stats=dict(row_review.TARGET),
    )[slot]


class TestReviewedCrowdControl:
    """Xin Zhao's reviewed crowd control, and the slots that still withhold.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Xin Zhao")
        assert xin_zhao.MODULE_CC == {"W": "slow", "E": "slow", "R": "none"}
        assert xin_zhao.parse_abilities.cc_kinds == xin_zhao.MODULE_CC
        assert "slowing all targets hit by 30%" in cc_review.slot_text(data, "E")
        # W's slow is the thrust's, and the module now prices the whole
        # cast — the four slashes plus that thrust.
        assert "slowing them by 50%" in cc_review.slot_text(data, "W")
        assert xin_zhao.SLOTS.packet_spec["slots"]["W"]["base"] == [
            7.5,
            10.0,
            12.5,
            15.0,
            17.5,
        ]

    def test_crescent_guard_never_displaces_a_challenged_duel_target(self):
        data = cc_review.kit("Xin Zhao")
        r_text = cc_review.slot_text(data, "R")
        assert "knocking back all targets hit that are not challenged" in r_text
        assert "basic attacks and audacious charge apply the challenged mark" in r_text

    def test_three_talon_strike_has_no_slot_wide_answer(self):
        """Only the third of Q's three empowered attacks knocks up."""
        data = cc_review.kit("Xin Zhao")
        assert "Q" not in xin_zhao.MODULE_CC
        assert "the third attack knocks up the target" in cc_review.slot_text(data, "Q")
        # The row covers all three empowered attacks, but only one of them
        # knocks up, so no slot-wide kind answers for it.
        assert xin_zhao.SLOTS.packet_spec["slots"]["Q"]["base"] == [
            15.0,
            30.0,
            45.0,
            60.0,
            75.0,
        ]

    def test_the_unreviewable_slot_keeps_the_fight_coarse(self):
        assert cc_review.unreviewed_ability_slots("Xin Zhao") == ["Q"]
        coverage = cc_review.fimbulwinter_coverage("Xin Zhao")
        assert coverage["complete"] is False
        assert "fimbulwinter_everlasting" in coverage["coarse_sources"]


class TestPricedRows:
    """Q and W price the cast's own total, not one instance of it.

    The generated packet picked "Bonus Physical Damage" for Q (one of the
    three empowered attacks) and "Physical Damage per Slash" for W (one
    slash of four, and no thrust).  Both cached entries also carry the
    total the wiki computes for the whole cast, and that is what the
    module reads.
    """

    def test_three_talon_strike_prices_all_three_empowered_attacks(self):
        total = row_review.cached_row("Xin Zhao", "Q", "Total Bonus Physical Damage")
        one = row_review.cached_row("Xin Zhao", "Q", "Bonus Physical Damage")
        assert total == pytest.approx(3 * one)
        assert row_review.priced("Xin Zhao", "Q") == pytest.approx(total)
        assert row_review.packet_row("Xin Zhao", "Q", xin_zhao)[4] == 75.0

    def test_wind_becomes_lightning_prices_the_slashes_and_the_thrust(self):
        total = row_review.cached_row("Xin Zhao", "W", "Total Physical Damage")
        slashes = row_review.cached_row("Xin Zhao", "W", "Slash Total Physical Damage")
        thrust = row_review.cached_row("Xin Zhao", "W", "Thrust Physical Damage")
        per_slash = row_review.cached_row("Xin Zhao", "W", "Physical Damage per Slash")
        assert total == pytest.approx(slashes + thrust)
        assert slashes == pytest.approx(4 * per_slash)
        assert row_review.priced("Xin Zhao", "W") == pytest.approx(total)
        assert row_review.packet_row("Xin Zhao", "W", xin_zhao)[4] == 17.5


class TestCritVocabulary:
    """Q and W each state a crit clause, and they are different axes.

    ``crit_effectiveness`` scales the crit PROBABILITY, so it routes
    through the fight's crit multiplier.  W's thrust rider does not: it
    reaches a fixed +33.3% at 100% crit chance whatever the multiplier
    is, which is why it is priced in the parser instead.
    """

    def test_three_talon_strike_declares_the_clause_its_row_states(self):
        text = cc_review.slot_text(cc_review.kit("Xin Zhao"), "Q")
        assert "bonus damage is affected by critical strike modifiers" in text
        (part,) = row_review.entry("Xin Zhao", "Q")["parts"]
        assert part.crit_effectiveness == xin_zhao._Q_CRIT_EFFECTIVENESS == 1.0
        # The declaration is on the probability axis only: the priced
        # amount is still the cached row, at any crit chance.
        for crit in (0.0, 100.0):
            assert _row_at_crit("Q", crit)["total_raw"] == pytest.approx(
                row_review.cached_row("Xin Zhao", "Q", "Total Bonus Physical Damage")
            )

    def test_the_thrust_rider_is_priced_here_and_is_not_crit_effectiveness(self):
        text = cc_review.slot_text(cc_review.kit("Xin Zhao"), "W")
        assert "increased by 0% : 33.3% (based on critical strike chance)" in text
        total = row_review.cached_row("Xin Zhao", "W", "Total Physical Damage")
        thrust = row_review.cached_row("Xin Zhao", "W", "Thrust Physical Damage")
        # At 0% crit the row is exactly the cached Total; at 100% it is
        # that total plus a third of the thrust, and nothing else moves.
        assert _row_at_crit("W", 0.0)["total_raw"] == pytest.approx(total)
        assert _row_at_crit("W", 100.0)["total_raw"] == pytest.approx(
            total + thrust * xin_zhao._W_THRUST_CRIT_CHANCE_AMP
        )
        assert _row_at_crit("W", 50.0)["total_raw"] == pytest.approx(
            total + thrust * xin_zhao._W_THRUST_CRIT_CHANCE_AMP * 0.5
        )
        # The key stays off the part: a crit roll would move with the
        # build's crit multiplier, and this rider does not.
        for crit in (0.0, 100.0):
            (part,) = _row_at_crit("W", crit)["parts"]
            assert part.crit_effectiveness == 0.0

    def test_the_crit_clauses_reach_a_real_fight(self):
        """Cloak of Agility grants 15% crit chance and no other stat.

        Both sides of the comparison therefore price the same AD and AP,
        so every difference below is the crit clause and nothing else.
        """
        plain = rider_probe.fight("Xin Zhao", deterministic=True)
        crit = rider_probe.fight(
            "Xin Zhao", items=["Cloak of Agility"], deterministic=True
        )
        assert crit["champion_stats"]["critical_strike_chance"] == pytest.approx(15.0)
        assert crit["champion_stats"]["attack_damage"] == pytest.approx(
            plain["champion_stats"]["attack_damage"]
        )
        # Q's whole row crits: 1 - 0.15 + 0.15 x 2.0 == 1.15.
        assert crit["breakdown"]["Q"]["total_damage"] == pytest.approx(
            1.15 * plain["breakdown"]["Q"]["total_damage"], abs=0.1
        )
        # W's thrust rider is a flat 0.333 x 0.15 of the thrust term, and
        # the four slashes are untouched — so W grows by strictly less
        # than the crit multiplier would have grown it.
        assert (
            1.0
            < (
                crit["breakdown"]["W"]["total_damage"]
                / plain["breakdown"]["W"]["total_damage"]
            )
            < 1.15
        )
        assert "adds 0.00 at 0% crit chance" in plain["breakdown"]["W"]["detail"]
        assert "amplifier adds" in crit["breakdown"]["W"]["detail"]


class TestDetermination:
    """P: the third-stack bonus and the maximum-health heal it pays."""

    def test_the_cached_entry_carries_no_number_at_all(self):
        """Why every band is a module constant rather than a cached read."""
        assert [
            leveling
            for effect in cc_review.kit("Xin Zhao")["abilities"]["P"][0]["effects"]
            for leveling in effect.get("leveling") or []
        ] == []
        text = cc_review.slot_text(cc_review.kit("Xin Zhao"), "P")
        assert "stacking up to 3 times" in text
        assert "15% / 30% / 45% / 60% (based on level) ad" in text
        assert "2% / 3.5% / 5% (based on level) of his maximum health" in text

    def test_the_proc_is_shared_over_the_three_attacks_that_build_it(self):
        """60% of 200 AD + 20% of 200 AP = 160 per proc, 53.33 per attack."""
        on_hit = row_review.entry("Xin Zhao", "passive")["on_hit"]
        assert on_hit["damage_type"] == "physical"
        assert on_hit["stacks_required"] == xin_zhao.DETERMINATION_STACKS == 3
        assert on_hit["damage_per_hit"] == pytest.approx(160.0 / 3)

    def test_wind_becomes_lightning_is_the_only_declared_stack_source(self):
        """The cached sentence names exactly W's first slash and thrust."""
        text = cc_review.slot_text(cc_review.kit("Xin Zhao"), "P")
        assert (
            "basic attacks on-hit and wind becomes lightning's first slash "
            "hit and thrust on at least one enemy hit each generate a stack"
        ) in text
        assert xin_zhao.W_DETERMINATION_STACKS == {"W": 2}
        assert (
            row_review.entry("Xin Zhao", "passive")["on_hit"]["ability_stack_slots"]
            == xin_zhao.W_DETERMINATION_STACKS
        )
        # The kit-wide counter is exactly what this row must NOT use: E and
        # R land damaging ability hits and generate no Determination.
        assert (
            "count_ability_hits"
            not in row_review.entry("Xin Zhao", "passive")["on_hit"]
        )

    def test_the_procs_reach_the_fight_total(self):
        """6 autos plus W's two stacks are 8 — 91.2 post-mitigation."""
        result = rider_probe.fight("Xin Zhao")
        row = result["breakdown"][rider_probe.RIDER_ROW]
        assert row["name"] == "Determination"
        assert row["unit"] == "procs"
        assert row["count"] == 2
        assert result["breakdown"]["auto_attacks"]["count"] == 6
        assert result["breakdown"]["W"]["casts"] == 1
        assert row["total_damage"] == pytest.approx(91.2, abs=0.05)
        assert row["total_damage"] < result["total_damage"]

    def test_the_heal_rides_the_same_events_as_the_damage(self):
        """5% maximum health per proc at level 18, on the same cadence."""
        result = rider_probe.fight("Xin Zhao")
        health = result["champion_stats"]["health"]
        stacks = (
            result["breakdown"]["auto_attacks"]["count"]
            + result["breakdown"]["W"]["casts"] * xin_zhao.W_DETERMINATION_STACKS["W"]
        )
        expected = stacks * (0.05 * health) / xin_zhao.DETERMINATION_STACKS
        assert rider_probe.healing_from(result, "Determination") == pytest.approx(
            expected, abs=0.5
        )

    def test_every_slot_now_prices_something(self):
        assert get_champion_module_contract("Xin Zhao").coverage == {
            slot: "modeled" for slot in "PQWER"
        }
