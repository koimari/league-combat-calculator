"""Tests for the Rek'Sai champion module."""

from functools import partial

import pytest

from src.calculator.champions import reksai
from src.calculator.champions.slot_extract import extract_named
from tests import cc_review, row_review
from tests import champion_closure as closure


class TestReviewedCrowdControl:
    """Rek'Sai's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Rek'Sai")
        assert reksai.MODULE_CC == {
            "Q": "none",
            "W": "knockup",
            "E": "none",
            "R": "none",
            "P": "none",
        }
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert "knock them up for 1 second" in cc_review.slot_text(data, "W")
        # E's only control word is about Rek'Sai being unable to enter a
        # tunnel while immobilized, not about control she applies.
        e_text = cc_review.slot_text(data, "E")
        assert "bites the target enemy, dealing physical damage" in e_text
        assert "cannot enter a tunnel while immobilized" in e_text
        assert cc_review.control_words(cc_review.slot_text(data, "R")) == []
        # P is Fury generation and healing, with no damage row.
        assert reksai.MODULE_CC["P"] == "none"

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Rek'Sai") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Rek'Sai")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


class TestPricedRows:
    """Queen's Wrath prices all three empowered attacks.

    The generated packet read "Bonus Physical Damage", one of the three
    the cast empowers ("for up to 3 total empowered attacks"); the
    cache's "Total Bonus Physical Damage" row is all three.
    """

    def test_queens_wrath_prices_all_three_empowered_attacks(self):
        total = row_review.cached_row("Rek'Sai", "Q", "Total Bonus Physical Damage")
        one = row_review.cached_row("Rek'Sai", "Q", "Bonus Physical Damage")
        assert total == pytest.approx(3 * one)
        assert row_review.priced("Rek'Sai", "Q", q_variant=0) == pytest.approx(total)
        assert row_review.packet_row("Rek'Sai", "Q", reksai, variant=0)[4] == 0.0

    def test_prey_seeker_is_untouched(self):
        """Variant 1 is one bolt and keeps the packet's own row."""
        magic = row_review.cached_row("Rek'Sai", "Q", "Magic Damage", entry=1)
        assert row_review.priced("Rek'Sai", "Q", q_variant=1) == pytest.approx(magic)


def test_the_published_options_are_the_three_the_module_reads():
    """Q variant, the Fury Furious Bite reads, and the Fury the burrow spends."""
    from src.calculator.champions import get_champion_options_meta

    keys = {option["key"] for option in get_champion_options_meta("Rek'Sai")["options"]}
    assert keys == {"q_variant", "e_fury", "p_burrow_fury"}


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
# Rek'Sai — E max-Fury true-damage variant
# ---------------------------------------------------------------------------


def test_reksai_e_prices_physical_bite_by_default():
    data, stats, abilities = _closure_parse("RekSai")
    e = data["abilities"]["E"][0]
    expected = extract_named(e, "Physical Damage", 5, stats, {})
    assert abilities["E"]["total_raw"] == pytest.approx(expected)
    assert abilities["E"]["damage_type"] == "physical"
    combat = _closure_fight("RekSai")
    events = closure.main_damage_events(combat, "E")
    assert events
    assert events[0]["damage_type"] == "physical"
    assert events[0]["raw_damage"] == pytest.approx(expected / len(events))


def test_reksai_e_at_max_fury_is_true_damage():
    data, stats, abilities = _closure_parse("RekSai", options={"e_fury": 100})
    e = data["abilities"]["E"][0]
    expected = extract_named(e, "True Damage", 5, stats, {})
    assert expected == pytest.approx(204.0)  # 120% of 170 physical
    assert abilities["E"]["total_raw"] == pytest.approx(expected)
    assert abilities["E"]["damage_type"] == "true"
    combat = _closure_fight("RekSai", options={"e_fury": 100})
    events = closure.main_damage_events(combat, "E")
    assert events
    assert events[0]["damage_type"] == "true"
    # True damage ignores the target's armor entirely at 0 resists.
    assert sum(e["damage"] for e in events) == pytest.approx(expected, rel=1e-3)
