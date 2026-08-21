"""Reviewed crowd control for Viego (MODULE_CC).

Spectral Maw stuns, Heartbreaker slows the champion it strikes, Blade of
the Ruined King only damages.
"""

from src.calculator.champions import get_champion_module_contract, viego
from tests import cc_review


class TestReviewedCrowdControl:
    """Viego's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Viego")
        assert viego.MODULE_CC == {"Q": "none", "W": "stun", "R": "slow"}
        assert viego.parse_abilities.cc_kinds == viego.MODULE_CC
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert "stuns them for" in cc_review.slot_text(data, "W")
        # R's slow lands on the champion it strikes; the knockback is for
        # the *other* nearby enemies, not the target this module prices.
        r_text = cc_review.slot_text(data, "R")
        assert "slowing them by 99% for 0.25 seconds" in r_text
        assert "other nearby enemies are knocked back" in r_text

    def test_the_undamaging_slots_stay_absent_from_the_review(self):
        """E leaves a mist trail and P is possession — neither damages.

        E is ``modeled`` all the same: the mist's attack speed is a
        priced stat_buff row.  P grants nothing the engine prices.
        """
        assert "E" not in viego.MODULE_CC and "P" not in viego.MODULE_CC
        assert get_champion_module_contract("Viego").coverage["E"] == "modeled"
        assert get_champion_module_contract("Viego").coverage["P"] == "no_damage"

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Viego") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Viego")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
