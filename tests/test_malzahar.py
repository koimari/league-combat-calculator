"""Reviewed crowd control for Malzahar (MODULE_CC), and Q's portal delay.

Call of the Void silences on the hit it lands 0.4 seconds after the cast,
Malefic Visions only burns, and Nether Grasp suppresses the target it
channels on.  The Voidling swarm is a pet row, not an ability event.
"""

from src.calculator.champions import malzahar, parse_champion_abilities
from tests import cc_review

_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}


class TestReviewedCrowdControl:
    """Malzahar's reviewed crowd control, and the delay that carries Q.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Malzahar")
        assert malzahar.MODULE_CC == {
            "Q": "silence",
            "E": "none",
            "R": "suppression",
        }
        assert malzahar.parse_abilities.cc_kinds == malzahar.MODULE_CC
        assert "are dealt magic damage and silenced for a duration" in (
            cc_review.slot_text(data, "Q")
        )
        assert cc_review.control_words(cc_review.slot_text(data, "E")) == []
        assert "suppressing and revealing the target and dealing them magic" in (
            cc_review.slot_text(data, "R")
        )

    def test_call_of_the_void_lands_on_its_sourced_portal_delay(self):
        data = cc_review.kit("Malzahar")
        assert "After 0.4 seconds, enemies between the portals are dealt" in (
            data["abilities"]["Q"][0]["effects"][0]["description"]
        )
        (part,) = parse_champion_abilities(data, 18, 100.0, _RANKS)["Q"]["parts"]
        assert part.time_offset == 0.4
        assert part.cc_kind == "silence"

    def test_the_swarm_is_a_pet_row_not_an_ability_event(self):
        """W's cast authors no part; its Voidlings ride their own row."""
        data = cc_review.kit("Malzahar")
        assert "W" not in malzahar.MODULE_CC
        parsed = parse_champion_abilities(
            data,
            18,
            100.0,
            _RANKS,
            champion_options={"fight_duration_seconds": 10.0},
        )
        assert parsed["W"]["parts"] == ()
        assert parsed["voidling_attacks"]["damage_events"]

    def test_the_reviewed_kit_clears_the_control_armed_scan(self):
        assert cc_review.unreviewed_ability_slots("Malzahar") == []
        coverage = cc_review.fimbulwinter_coverage("Malzahar")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
