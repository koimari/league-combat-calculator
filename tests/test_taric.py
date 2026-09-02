"""Taric's reviewed crowd control (``MODULE_CC``).

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

import pytest

from src.calculator.champions import get_champion_module_contract, taric
from tests import cc_review, rider_probe


class TestReviewedCrowdControl:
    """Dazzle is the whole of Taric's reviewable control."""

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Taric")
        assert taric.MODULE_CC == {
            "E": "stun",
            "P": "none",
            "Q": "none",
            "W": "none",
            "R": "none",
        }
        assert "stuns them for 1.5 seconds" in cc_review.slot_text(data, "E")
        # Q heals, W shields and R grants invulnerability: no other slot
        # damages, so no other slot has a control answer to carry.
        for slot in ("P", "Q", "W", "R"):
            assert cc_review.control_words(cc_review.slot_text(data, slot)) == []

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Taric") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Taric")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


class TestBravadoRider:
    """Taric P prices the attacks an ability cast empowers (slice 6).

    MERGE: the count is not a player-declared ``p_empowered_attacks``
    option.  The entry declares an ``empower_window`` (armed by a cast, two
    charges, refreshing rather than stacking) that ``damage.py`` walks
    against the accepted cast timeline — the more capable of the two models,
    since it derives the count instead of asking for it.  The window's own
    matrix lives in ``tests/test_taric_bravado.py``; this file keeps the
    public-entry claim: the rider reaches the fight total, per hit, through
    the ``on_hit_ability_passive`` row.
    """

    def test_empowered_attacks_reach_the_total_at_the_sourced_per_hit(self):
        """Level 18, no items: 93.0 RAW magic per empowered attack.

        Cached P "Per-Level Scaling" 25 : 101 (based on level) + 15% bonus
        armor; with no items the bonus-armor term is 0.  The probe target
        halves magic damage, so the published per-hit number is 46.5 --
        the raw 93.0 is pinned by ``tests/test_taric_bravado.py`` at MR 0.
        """
        result = rider_probe.fight("Taric")
        row = result["breakdown"][rider_probe.RIDER_ROW]

        assert row["name"] == "Bravado (on-hit)"
        assert row["damage_per_hit"] == pytest.approx(46.5, abs=0.05)
        # The window caps at its two sourced charges per arming round, so
        # the row can never reach the fight's swing count.
        assert 0 < row["count"] < result["breakdown"]["auto_attacks"]["count"]
        assert row["total_damage"] == pytest.approx(46.5 * row["count"], abs=0.05)
        assert row["total_damage"] < result["total_damage"]

    def test_no_swing_prices_nothing(self):
        """The window is spent BY an attack, so no attacks spend nothing."""
        result = rider_probe.fight("Taric", include_auto_attacks=False)
        assert rider_probe.RIDER_ROW not in result["breakdown"]

    def test_the_map_reports_what_each_slot_prices(self):
        # MERGE: R (Cosmic Radiance) is priced now — its invulnerability
        # window rides the survival axis — so every slot is modeled.
        assert get_champion_module_contract("Taric").coverage == {
            "P": "modeled",
            "Q": "modeled",
            "W": "modeled",
            "E": "modeled",
            "R": "modeled",
        }
