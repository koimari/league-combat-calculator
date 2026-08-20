"""Tests for the Samira champion module."""

from src.calculator.champions import get_champion_module_contract, samira
from tests import cc_review, coverage_truth, row_review


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
    """Q/W/E price rows; the map said ``out_of_scope`` until this campaign.

    ``b03bbad9`` added the Style stack row to P and rewrote the whole
    ``MODULE_COVERAGE`` set as ``{P, R}`` instead of adding P to the
    ``{Q, W, E, R}`` that was there — three priced slots reported as gaps.
    P is the slot that really is a gap, and it is ``out_of_scope`` rather
    than ``no_damage`` because Daredevil Impulse does damage this module
    cannot price.
    """

    def test_the_map_is_the_rows_the_module_prices(self):
        assert get_champion_module_contract("Samira").coverage == {
            "P": "out_of_scope",
            "Q": "modeled",
            "W": "modeled",
            "E": "modeled",
            "R": "modeled",
        }
        assert coverage_truth.emitted("Samira") == {
            "P": coverage_truth.ZERO,
            "Q": coverage_truth.PRICED,
            "W": coverage_truth.PRICED,
            "E": coverage_truth.PRICED,
            "R": coverage_truth.PRICED,
        }

    def test_the_passive_is_out_of_scope_because_its_kit_damages(self):
        """The blade-zone rider is a cached damage row, and it is unpriced."""
        blade = [
            effect
            for effect in cc_review.kit("Samira")["abilities"]["P"][0]["effects"]
            if "bonus magic damage" in (effect.get("description") or "")
        ]
        assert len(blade) == 1
        assert "Bonus Magic Damage" in {
            level["attribute"] for level in blade[0]["leveling"]
        }
        assert row_review.priced("Samira", "passive") == 0.0
