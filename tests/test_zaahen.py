"""Reviewed crowd control for Zaahen (MODULE_CC).

Dreaded Return stuns and pulls; The Darkin Glaive knocks up only on its
recast, so that kind is authored per part.
"""

import pytest

from src.calculator.champions import (
    get_champion_options_meta,
    parse_champion_abilities,
    zaahen,
)
from tests import cc_review, row_review

_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}


def _q_kinds(**options):
    """The kinds The Darkin Glaive's parts carry for one option state."""
    parsed = parse_champion_abilities(
        cc_review.kit("Zaahen"), 18, 100.0, _RANKS, champion_options=options or None
    )
    return sorted({part.cc_kind for part in parsed["Q"]["parts"]})


class TestReviewedCrowdControl:
    """Zaahen's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Zaahen")
        assert zaahen.MODULE_CC == {"W": "stun", "E": "none", "R": "none"}
        assert zaahen.parse_abilities.cc_kinds == zaahen.MODULE_CC
        w_text = cc_review.slot_text(data, "W")
        assert "stunned for 0.25 seconds, and pulled 225 units" in w_text
        assert cc_review.control_words(cc_review.slot_text(data, "E")) == []
        # R's only control word is the immunity Zaahen gains himself.
        r_text = cc_review.slot_text(data, "R")
        assert "gains crowd control immunity over the cast time" in r_text

    def test_grim_deliverance_damage_rides_the_slam(self):
        assert zaahen._R_SLAM_DELAY_SECONDS == 0.6
        assert "slams his glaive down after a 0.6-second delay" in (
            cc_review.slot_text(cc_review.kit("Zaahen"), "R")
        )

    def test_the_darkin_glaive_carries_the_variant_it_prices(self):
        """Only the recast row knocks up."""
        data = cc_review.kit("Zaahen")
        assert "Q" not in zaahen.MODULE_CC
        assert "knock up the target for 0.75 seconds" in cc_review.slot_text(data, "Q")
        assert _q_kinds() == ["none"]
        assert _q_kinds(q_variant=1) == ["none"]
        assert _q_kinds(q_variant=2) == ["knockup"]

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Zaahen") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Zaahen")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


class TestPricedRows:
    """Dreaded Return prices both of its legs.

    The generated packet read "Initial Physical Damage" alone, dropping
    the "Subsequent Physical Damage" the cast deals when the glaive
    reaches maximum range.  The cache's "Total Physical Damage" is the
    two summed, and that is what the module reads.
    """

    def test_dreaded_return_prices_the_extension_and_the_return(self):
        total = row_review.cached_row("Zaahen", "W", "Total Physical Damage")
        initial = row_review.cached_row("Zaahen", "W", "Initial Physical Damage")
        subsequent = row_review.cached_row("Zaahen", "W", "Subsequent Physical Damage")
        assert total == pytest.approx(initial + subsequent)
        assert row_review.priced("Zaahen", "W") == pytest.approx(total)
        assert row_review.packet_row("Zaahen", "W", zaahen)[4] == 120.0


class TestQVariants:
    """The Darkin Glaive publishes three sourced rows, and Q picks by option.

    The cache carries a total, a per-hit and a bonus row for the same cast;
    reading the wrong one is a 2x error that no other assertion would see.
    """

    def test_each_variant_selects_the_matching_sourced_damage_row(self):
        assert [
            option["key"] for option in get_champion_options_meta("Zaahen")["options"]
        ] == ["q_variant"]
        entries = [row_review.entry("Zaahen", "Q", q_variant=v) for v in range(3)]
        assert [entry["detail"] for entry in entries] == [
            "Q variant: Total Physical Damage.",
            "Q variant: Physical Damage per Hit.",
            "Q variant: Bonus Physical Damage.",
        ]
        assert [entry["parts"][0].count for entry in entries] == [2, 2, 1]
        # Each variant prices the cached row its detail names — the per-hit
        # row twice, the other two as they stand.
        per_hit = row_review.cached_row("Zaahen", "Q", "Physical Damage per Hit")
        assert [entry["total_raw"] for entry in entries] == pytest.approx(
            [
                row_review.cached_row("Zaahen", "Q", "Total Physical Damage"),
                per_hit * 2,
                row_review.cached_row("Zaahen", "Q", "Bonus Physical Damage"),
            ]
        )
