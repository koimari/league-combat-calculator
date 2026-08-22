"""Tests for the Samira champion module."""

import pytest

from src.calculator.champions import get_champion_module_contract, samira, slotlib
from tests import cc_review, coverage_truth, rider_probe, row_review


class TestReviewedCrowdControl:
    """Samira's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_every_damaging_cast_is_free_of_control_vocabulary(self):
        data = cc_review.kit("Samira")
        assert samira.MODULE_CC == {
            "Q": "none",
            "W": "none",
            "E": "none",
            "R": "none",
        }
        for slot in ("Q", "W", "E", "R"):
            assert cc_review.control_words(cc_review.slot_text(data, slot)) == []
        # P is absent: it is a state row with no damage, and its knock-up
        # rider fires only on the empowered basic attack against a target
        # already immobilized and either a monster or airborne.
        assert "P" not in samira.MODULE_CC
        p_text = cc_review.slot_text(data, "P")
        assert "basic attack against an immobilized target" in p_text
        assert "if the target is a monster or is airborne" in p_text

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Samira") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Samira")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


class TestCoverageMap:
    """Every slot prices a row now that P rides the shared hit-rider axis.

    ``b03bbad9`` added the Style stack row to P and rewrote the whole
    ``MODULE_COVERAGE`` set as ``{P, R}`` instead of adding P to the
    ``{Q, W, E, R}`` that was there — three priced slots reported as gaps.
    P stayed ``out_of_scope`` after that only because Daredevil Impulse's
    blade rider had no channel; it has one, so the module declares no map
    and the contract derives all five from ``SLOTS``.
    """

    def test_the_map_is_the_rows_the_module_prices(self):
        assert not hasattr(samira, "MODULE_COVERAGE")
        assert get_champion_module_contract("Samira").coverage == {
            slot: "modeled" for slot in "PQWER"
        }
        assert coverage_truth.emitted("Samira") == {
            slot: coverage_truth.PRICED for slot in "PQWER"
        }

    def test_the_blade_zone_option_is_the_riders_only_gate(self):
        """Outside the zone P falls back to the Style state row."""
        assert coverage_truth.emitted("Samira", p_blade_zone=False)["P"] == (
            coverage_truth.ZERO
        )


class TestBladeRider:
    """P: Daredevil Impulse's rider, on the carriers the sentence names."""

    def test_the_cached_rows_are_the_per_level_terms_and_their_double(self):
        """2 : 21 flat and 3.5% : 11.32% AD, and the "up to" rows are 2x."""
        blade = [
            effect
            for effect in cc_review.kit("Samira")["abilities"]["P"][0]["effects"]
            if "bonus magic damage" in (effect.get("description") or "")
        ]
        assert len(blade) == 1
        text = blade[0]["description"]
        assert "Blade attacks, Blade Whirl, Wild Rush, and the slash and " in text
        assert "explosives of Flair" in text
        assert "increased by 0% : 100% (based on target's missing health)" in text
        # Inferno Trigger is deliberately absent from that carrier list.
        assert "Inferno Trigger" not in text

        ability = cc_review.kit("Samira")["abilities"]["P"][0]
        for level, flat, ad_percent in (
            (1, 2.0, 3.5),
            (18, 19.0, 10.5),
            (20, 21.0, 11.32),
        ):
            assert (
                slotlib.extract_value(ability, "Bonus Magic Damage", level, level=level)
                == flat
            )
            assert (
                slotlib.extract_value(ability, "Per-Level Scaling", level, level=level)
                == ad_percent
            )
            # The wiki's "up to" maximum is exactly the doubling this
            # module prices as a missing-health amplification of 1.0.
            assert (
                slotlib.extract_value(
                    ability, "Per-Level Scaling", level, level=level, occurrence=1
                )
                == 2 * flat
            )
            # abs=0.01: the wiki rounds each array to two decimals before
            # doubling, so level 20 reads 22.65 rather than 2 x 11.32.
            assert slotlib.extract_value(
                ability, "Per-Level Scaling", level, level=level, occurrence=2
            ) == pytest.approx(2 * ad_percent, abs=0.01)

    def test_one_declaration_serves_both_channels(self):
        """The auto entry and the ability parts read the same rider."""
        on_hit = row_review.entry("Samira", "passive")["on_hit"]
        # 19 flat + 10.5% of the 200 total AD row_review fixes at level 18.
        assert on_hit["damage_per_hit"] == pytest.approx(19 + 0.105 * 200)
        assert on_hit["damage_type"] == "magic"
        assert on_hit["missing_health_amp"] == samira.RIDER_MISSING_HEALTH_AMP == 1.0
        for slot, hits in (("Q", 1), ("W", 2), ("E", 1)):
            rider, *rest = row_review.parts("Samira", slot)
            # The rider leads the row and mirrors its carrier's hit count:
            # Blade Whirl slashes twice, so the rider lands twice.
            assert rider.damage_type == "magic"
            assert rider.amount == pytest.approx(on_hit["damage_per_hit"])
            assert rider.count == rest[-1].count == hits
        # Inferno Trigger is not a carrier.
        assert all(
            part.damage_type == "physical" for part in row_review.parts("Samira", "R")
        )

    def test_the_rider_reaches_the_fight_on_both_channels(self):
        """Level 18, no items, timed: +225.8 damage over the un-ridden kit."""
        on = rider_probe.fight("Samira", deterministic=True)
        off = rider_probe.fight(
            "Samira", deterministic=True, champion_options={"p_blade_zone": False}
        )
        row = on["breakdown"][rider_probe.RIDER_ROW]
        assert row["name"] == "Daredevil Impulse (on-hit)"
        assert row["count"] == on["breakdown"]["auto_attacks"]["count"] == 6
        # Each proc reads the target's decayed health, so they escalate.
        assert row["total_damage"] == pytest.approx(107.1, abs=0.05)
        # Outside the blade zone no attack carries it and Flair is the
        # ranged shot; Blade Whirl and Wild Rush still do.
        assert rider_probe.RIDER_ROW not in off["breakdown"]
        assert off["breakdown"]["Q"]["total_damage"] == pytest.approx(277.6, abs=0.05)
        assert on["breakdown"]["Q"]["total_damage"] == pytest.approx(346.1, abs=0.05)
        assert on["total_damage"] == pytest.approx(1414.4, abs=0.05)
