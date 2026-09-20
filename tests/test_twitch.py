"""Twitch's reviewed crowd control (``MODULE_CC``).

The roster-wide half of this review lives in ``test_module_cc_census.py``.
"""

from src.calculator.champions import get_champion_module_contract, twitch
from tests import cc_review


class TestReviewedCrowdControl:
    """Contaminate is the only cast that reaches the ability ledger."""

    def test_the_whole_cached_kit_puts_its_control_outside_the_damage(self):
        data = cc_review.kit("Twitch")
        assert twitch.MODULE_CC == {
            "E": "none",
            "P": "none",
            "Q": "none",
            "W": "slow",
            "R": "none",
        }
        assert cc_review.control_words(cc_review.slot_text(data, "E")) == []
        # Venom Cask is where the kit's slow lives, and it deals no damage.
        assert cc_review.control_words(cc_review.slot_text(data, "W")) == ["slow"]
        # W is emitted and grants nothing the engine prices — the slow
        # carries no magnitude field — which is what ``no_damage`` states.
        assert get_champion_module_contract("Twitch").coverage["W"] == "no_damage"
        for slot in ("P", "Q", "R"):
            assert cc_review.control_words(cc_review.slot_text(data, slot)) == []
