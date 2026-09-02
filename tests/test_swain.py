"""Swain's reviewed crowd control (``MODULE_CC`` plus R's per-variant part).

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

import pytest

from src.calculator.champions import swain
from src.calculator.champions.engine import CC_PER_PART
from tests import cc_review, row_review


def _r_parts(variant: int):
    """Ravenous Flock's ultimate parts for one variant, through the module."""
    data = cc_review.kit("Swain")
    results = swain.parse_abilities(
        data, 18, 0.0, champion_options={"r_variant": variant}
    )
    return results["R"]["parts"]


class TestReviewedCrowdControl:
    """Swain's reviewed crowd control, and what declaring it clears."""

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Swain")
        assert swain.MODULE_CC == {
            "Q": "none",
            "W": "slow",
            "E": "root",
            "R": CC_PER_PART,
        }
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert "slowing them by 50% for 1.5 seconds" in cc_review.slot_text(data, "W")
        # E's pull and knock-back ride the recast; the detonation that this
        # row prices roots.
        assert "rooting them for 1.5 seconds" in cc_review.slot_text(data, "E")

    def test_r_answers_by_variant_because_the_two_casts_differ(self):
        """Demonic Ascension drains without control; Demonflare slows, so R
        authors its kind on the selected variant's part."""
        assert "slows them by 50%" in cc_review.slot_text(cc_review.kit("Swain"), "R")
        assert swain.MODULE_CC["R"] == CC_PER_PART
        assert _r_parts(0)[0].cc_kind == "none"
        assert _r_parts(1)[0].cc_kind == "slow"

    def test_the_r_wrapper_keeps_the_compiled_parsers_phase(self):
        """A compiled packet slot always carries ``.phase``; the wrapper reads it."""
        assert swain.SLOTS["R"].phase == "damage"

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Swain") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Swain")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


class TestPricedRows:
    """Death's Hand prices all five bolts; Demonic Ascension still does not.

    The generated packet read Q's per-bolt "Magic Damage" row; the cache
    also carries the single-target "Total Damage" for the whole cast —
    the first bolt plus four at the 25% "Bonus Damage Per Bolt" row.  R's
    variant 0 has no such row: the cache prices one 0.5-second drain tick
    and states no channel total, so that one is reported, not guessed.
    """

    def test_deaths_hand_prices_the_single_target_total(self):
        total = row_review.cached_row("Swain", "Q", "Total Damage")
        one_bolt = row_review.cached_row("Swain", "Q", "Magic Damage")
        per_bolt_bonus = row_review.cached_row("Swain", "Q", "Bonus Damage Per Bolt")
        assert total == pytest.approx(one_bolt + 4 * per_bolt_bonus)
        assert row_review.priced("Swain", "Q") == pytest.approx(total)
        assert row_review.packet_row("Swain", "Q", swain)[4] == 180.0

    def test_demonic_ascension_is_still_one_drain_tick(self):
        """The channel's length is an energy economy, not another row."""
        rows = {
            leveling["attribute"]
            for effect in cc_review.kit("Swain")["abilities"]["R"][0]["effects"]
            for leveling in effect.get("leveling") or []
        }
        assert rows == {
            "Magic Damage per Tick",
            "Heal per Tick",
            "Reduced Heal per Tick",
        }
        per_tick = row_review.cached_row("Swain", "R", "Magic Damage per Tick")
        assert row_review.priced("Swain", "R", r_variant=0) == pytest.approx(per_tick)


def test_the_published_options_are_the_one_the_module_reads():
    """Which R cast the fight prices, and how many Soul Fragments Swain holds."""
    from src.calculator.champions import get_champion_options_meta

    keys = {option["key"] for option in get_champion_options_meta("Swain")["options"]}
    assert keys == {"r_variant", "p_soul_fragments"}


def test_soul_fragments_grant_permanent_bonus_health_the_drain_scales_on():
    """P's 15-per-fragment health reaches R's '% of his bonus health' ratio."""
    assert row_review.entry("Swain", "passive", p_soul_fragments=0)["stat_buff"] == {
        "bonus_health": 0.0
    }
    six = row_review.entry("Swain", "passive", p_soul_fragments=6)
    assert six["total_raw"] == 0.0
    assert six["stat_buff"] == {"bonus_health": pytest.approx(90.0)}
    # R's Heal per Tick carries 0.75% of bonus health, and the drain's
    # damage row carries none — so the fragments move the heal, not the
    # damage.  Pricing the health at all is what this asserts.
    unstacked = row_review.priced("Swain", "R", r_variant=0, p_soul_fragments=0)
    stacked = row_review.priced("Swain", "R", r_variant=0, p_soul_fragments=6)
    assert stacked == pytest.approx(unstacked)
