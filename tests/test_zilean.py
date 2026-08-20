"""Reviewed crowd control for Zilean (MODULE_CC).

A lone Time Bomb only explodes; the kit's stun needs a second bomb inside
the first one's fuse.
"""

from src.calculator.champions import (
    get_champion_module_contract,
    parse_champion_abilities,
    zilean,
)
from tests import cc_review


class TestReviewedCrowdControl:
    """Zilean's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Zilean")
        assert zilean.MODULE_CC == {"Q": "none"}
        assert zilean.parse_abilities.cc_kinds == zilean.MODULE_CC
        q_text = cc_review.slot_text(data, "Q")
        assert "the bomb explodes to deal magic damage to nearby enemies" in q_text
        # The only control word is the double-bomb detonation, which needs
        # a second bomb on the same unit inside the first one's fuse.
        assert cc_review.control_words(q_text) == ["stun"]
        assert "if another bomb attaches itself to the same unit, stunning" in q_text

    def test_time_bomb_damage_rides_its_sourced_fuse(self):
        data = cc_review.kit("Zilean")
        assert zilean._Q_FUSE_SECONDS == 3.0
        assert "after 3 seconds" in cc_review.slot_text(data, "Q")
        parsed = parse_champion_abilities(
            data, 18, 100.0, {"Q": 5, "W": 5, "E": 5, "R": 3}
        )
        (part,) = parsed["Q"]["parts"]
        assert part.time_offset == 3.0

    def test_the_out_of_scope_slots_stay_absent(self):
        """E holds the enemy slow, but Time Warp deals no damage."""
        data = cc_review.kit("Zilean")
        for slot in ("W", "E", "R"):
            assert slot not in zilean.MODULE_CC, slot
            assert (
                get_champion_module_contract("Zilean").coverage[slot] == "out_of_scope"
            ), slot
        assert "if the target is an enemy, they are slowed" in (
            cc_review.slot_text(data, "E")
        )

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Zilean") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Zilean")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
