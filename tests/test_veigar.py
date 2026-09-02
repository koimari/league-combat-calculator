"""Reviewed crowd control for Veigar (MODULE_CC), and Dark Matter's timing.

Q, W and R are control-free; the cage deals no damage.  W's hit lands on
the cached 1.221-second delay rather than at the cast, which is both what
the source says and what puts the row in the event ledger.
"""

from src.calculator.champions import (
    get_champion_module_contract,
    parse_champion_abilities,
    veigar,
)
from tests import cc_review


class TestReviewedCrowdControl:
    """Veigar's reviewed crowd control, and the delay that carries it.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Veigar")
        assert veigar.MODULE_CC == {
            "Q": "none",
            "W": "none",
            "R": "none",
            "P": "none",
            "E": "stun",
        }
        assert veigar.parse_abilities.cc_kinds == veigar.MODULE_CC
        for slot in ("Q", "W", "R"):
            assert cc_review.control_words(cc_review.slot_text(data, slot)) == [], slot

    def test_the_cage_carries_the_kits_stun_and_no_damage(self):
        data = cc_review.kit("Veigar")
        assert veigar.MODULE_CC["E"] == "stun"
        assert "stunned for a duration" in cc_review.slot_text(data, "E")
        assert get_champion_module_contract("Veigar").coverage["E"] == "no_damage"

    def test_dark_matter_lands_on_its_sourced_impact_delay(self):
        """The offset is the cached number, from the cast start."""
        data = cc_review.kit("Veigar")
        assert "after a 1.221 seconds delay" in cc_review.slot_text(data, "W")
        assert "The delay starts at the beginning of the cast time." in (
            data["abilities"]["W"][0]["notes"]
        )
        parsed = parse_champion_abilities(
            data, 18, 100.0, {"Q": 5, "W": 5, "E": 5, "R": 3}
        )
        (part,) = parsed["W"]["parts"]
        assert part.time_offset == 1.221
        assert part.cc_kind == "none"

    def test_the_reviewed_kit_clears_the_control_armed_scan(self):
        assert cc_review.unreviewed_ability_slots("Veigar") == []
        coverage = cc_review.fimbulwinter_coverage("Veigar")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
