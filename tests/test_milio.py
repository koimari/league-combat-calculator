"""Milio — the reviewed crowd control its kit declares (MODULE_CC).

The declaration is not decoration: a control-armed holder shield
(Fimbulwinter's Everlasting) reads a control marker off ability damage
events, and one unreviewed ability packet makes the whole timed fight
fall back to coarse ordering.  These tests hold the declaration to the
cached text it was read from, and prove it reaches the event ledger.
"""

import pytest

from src.calculator.champions import get_champion_module_contract, milio
from src.calculator.data_fetcher import get_champion
from tests import cc_review, rider_probe

# The phrase each declared kind was read from, in that slot's cached text.
QUOTED = {"Q": "knocks back and stuns the first enemy it hits over 1 second"}


@pytest.fixture(scope="module")
def cached():
    return get_champion("Milio")


class TestReviewedCrowdControl:
    def test_declared_kinds_quote_the_cached_text(self, cached):
        assert milio.MODULE_CC == {
            "Q": "stun",
            "P": "none",
            "W": "none",
            "E": "none",
            "R": "none",
        }
        for slot, phrase in QUOTED.items():
            assert phrase in cc_review.slot_text(cached, slot), slot


class TestFiredUpRider:
    """Milio P prices the burn the enchanted hit applies (census slice 6)."""

    def test_the_burn_reaches_the_total(self):
        """Level 18, no items: the enchanted hits the fight affords.

        Cached P "Per-Level Scaling" 10 : 50 (based on level) + 20% of
        Milio's AP; the probe target halves magic damage, so each enchanted
        hit lands 25.0.
        """
        result = rider_probe.fight("Milio")
        row = result["breakdown"][rider_probe.RIDER_ROW]

        assert row["name"] == "Fired Up! (on-hit)"
        # Two, not one: the casts enchant and the attacks and ability hits
        # spend it, which the fight walks (champions/armed_procs.py).
        assert row["count"] == 2
        assert row["total_damage"] == pytest.approx(25.0 * row["count"], abs=0.05)
        assert row["total_damage"] < result["total_damage"]

    def test_no_enchanted_hit_prices_nothing(self):
        result = rider_probe.fight("Milio", champion_options={"p_procs": 0})
        assert rider_probe.RIDER_ROW not in result["breakdown"]

    def test_every_slot_now_prices_something(self):
        assert get_champion_module_contract("Milio").coverage == dict.fromkeys(
            "PQWER", "modeled"
        )
