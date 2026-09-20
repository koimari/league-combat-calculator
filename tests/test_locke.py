"""Locke — the reviewed crowd control its kit declares (MODULE_CC).

The declaration is not decoration: a control-armed holder shield
(Fimbulwinter's Everlasting) reads a control marker off ability damage
events, and one unreviewed ability packet makes the whole timed fight
fall back to coarse ordering.  These tests hold the declaration to the
cached text it was read from, and prove it reaches the event ledger.
"""

from functools import partial

import pytest

from src.calculator.champions import locke
from src.calculator.champions.slot_extract import extract_named
from src.calculator.data_fetcher import get_champion
from tests import cc_review
from tests import champion_closure as closure

# The phrase each declared kind was read from, in that slot's cached text.
QUOTED = {
    "Q": "slows them by 25% for 1 second",
    "R": "slowing them by 99% decaying over 2 seconds",
}

# E's only control word is about Locke himself: he "cannot perform the
# dash while immobilized or grounded".
UNCONTROLLED_MENTIONS = {"E": ["immobiliz"]}


@pytest.fixture(scope="module")
def cached():
    return get_champion("Locke")


class TestReviewedCrowdControl:
    def test_declared_kinds_quote_the_cached_text(self, cached):
        assert locke.MODULE_CC == {
            "Q": "slow",
            "E": "none",
            "R": "slow",
            "P": "none",
            "W": "none",
        }
        for slot, phrase in QUOTED.items():
            assert phrase in cc_review.slot_text(cached, slot), slot

    def test_reviewed_absences_read_the_whole_slot(self, cached):
        """A "none" is a slot that was read, not a slot that was skipped."""
        for slot, kind in locke.MODULE_CC.items():
            if kind != "none":
                continue
            hits = cc_review.any_control_hits(cached, slot)
            assert hits == UNCONTROLLED_MENTIONS.get(slot, []), slot


def test_the_soul_nail_casts_price():
    """Q prices with the soul nails the option arms."""
    from tests import row_review

    assert row_review.priced("Locke", "Q", q_casts=3, soul_nails=3) > 0


# Level 18, ranks Q5/W5/E5/R3, no items, six seconds of autos at full uptime
# into a 3000-HP Aatrox whose own resistances mitigate.
_closure_fight = partial(
    closure.combat,
    mode="time_based",
    duration=6.0,
    include_autos=True,
    auto_uptime=1.0,
    target_health=3000.0,
    enemy=closure.AATROX,
)
_closure_parse = partial(closure.parse, target=closure.TARGET_3000)


# ---------------------------------------------------------------------------
# Locke — W Soul Ignition grey-health recast heal
# ---------------------------------------------------------------------------


def test_locke_w_grey_health_recast_heals_the_capped_pool():
    data, stats, _ = _closure_parse("Locke")
    w = data["abilities"]["W"][0]
    cap = extract_named(w, "Damage taken grey health cap", 5, stats, {})
    combat = _closure_fight("Locke", duration=10)
    heals = list(closure.main_heals(combat, "Soul Ignition (grey health)"))
    assert heals, "Soul Ignition grey-health heal missing"
    survival = closure.main_survival(combat)
    assert survival["grey_health_stored"] == pytest.approx(cap)
    assert survival["grey_health_consumed"] == pytest.approx(cap)
    # Aatrox's incoming damage over the 6s W window exceeds the rank-5 cap,
    # so the heal pays the sourced cap exactly (120 + 100% AP).
    assert heals[0]["amount"] == pytest.approx(cap)
    assert heals[0]["amount"] == pytest.approx(120.0)


def test_locke_w_rank1_caps_the_pool_lower():
    data, stats, _ = _closure_parse("Locke", ranks={"Q": 5, "W": 1, "E": 5, "R": 3})
    w = data["abilities"]["W"][0]
    cap = extract_named(w, "Damage taken grey health cap", 1, stats, {})
    assert cap == pytest.approx(40.0)
    combat = _closure_fight(
        "Locke", duration=10, ranks={"Q": 5, "W": 1, "E": 5, "R": 3}
    )
    survival = closure.main_survival(combat)
    assert survival["grey_health_stored"] == pytest.approx(40.0)
    heals = list(closure.main_heals(combat, "Soul Ignition (grey health)"))
    assert heals
    assert heals[0]["amount"] == pytest.approx(40.0)
