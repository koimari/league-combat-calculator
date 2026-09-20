"""Reviewed crowd control for Vladimir (MODULE_CC), and R's burst timing.

Sanguine Pool and a fully charged Tides of Blood slow; Transfusion does
not.  Hemoplague controls nothing and its burst lands 4 seconds after the
cast, which the packet now authors.
"""

from src.calculator.champions import parse_champion_abilities, vladimir
from src.calculator.stats import calculate_total_stats
from tests import cc_review
from functools import partial
from tests import champion_closure as closure
import pytest


class TestReviewedCrowdControl:
    """Vladimir's reviewed crowd control, and the delay that carries R.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Vladimir")
        assert vladimir.MODULE_CC == {
            "Q": "none",
            "W": "slow",
            "E": "slow",
            "R": "none",
            "P": "none",
        }
        assert vladimir.parse_abilities.cc_kinds == vladimir.MODULE_CC
        # Q's only control words describe Vladimir's own Crimson Rush:
        # it "depletes 75% slower during Sanguine Pool, Tides of Blood, or
        # stasis" — a condition on him, never applied to the target.
        q_text = cc_review.slot_text(data, "Q")
        assert cc_review.control_words(q_text) == ["slow", "stasis"]
        assert "crimson rush depletes 75% slower during" in q_text
        assert "are slowed by 40%" in cc_review.slot_text(data, "W")
        # E prices the fully charged nova, which is exactly the branch the
        # cached text puts the slow on.
        e_text = cc_review.slot_text(data, "E")
        assert "charged for at least 1 second, enemies hit are also slowed" in e_text
        assert vladimir.SLOTS.packet_spec["slots"]["E"]["base"] == [
            60.0,
            90.0,
            120.0,
            150.0,
            180.0,
        ]

    def test_hemoplague_bursts_at_the_end_of_its_sourced_infection(self):
        """R controls nothing, and its burst lands 4 seconds after the cast."""
        data = cc_review.kit("Vladimir")
        r_text = cc_review.slot_text(data, "R")
        assert cc_review.control_words(r_text) == []
        assert "infects enemies hit for 4 seconds" in r_text
        assert "after the duration, the infection bursts" in r_text
        # E (Tides of Blood) prices a share of Vladimir's health, and the
        # module reads ``ctx.stats["health"]`` with no default — a parse
        # with no champion stats raises rather than pricing it at zero.
        stats = calculate_total_stats(data, 18, [])
        parsed = parse_champion_abilities(
            data,
            18,
            100.0,
            {"Q": 5, "W": 5, "E": 5, "R": 3},
            champion_stats=stats,
        )
        (part,) = parsed["R"]["parts"]
        assert part.time_offset == 4.0
        assert part.cc_kind == "none"

    def test_the_reviewed_kit_clears_the_control_armed_scan(self):
        assert cc_review.unreviewed_ability_slots("Vladimir") == []
        coverage = cc_review.fimbulwinter_coverage("Vladimir")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


# One rotation at level 18 into the bare 2000-HP dummy; slot rows are parsed
# against the shared reference stat block.
_closure_fight = partial(closure.fight, role="top")
_closure_parse = closure.reference_abilities


# ---------------------------------------------------------------------------
# Vladimir — R Hemoplague 10% increased-damage-taken
# ---------------------------------------------------------------------------


class TestVladimir:
    """P1-3: the R debuff amplifies every damage entry by 10%."""

    def test_r_debuff_amplifies_all_damage(self):
        """R-first combo: every entry is amplified 10%, so the R
        detonation itself prices the wiki's self-amplified 385."""
        data = _closure_fight("Vladimir", cast_order=["R", "Q", "W", "E"])
        assert closure.slot_total(data, "R") == pytest.approx(350.0 * 1.1)
        assert closure.slot_total(data, "Q") == pytest.approx(160.0 * 1.1)
        assert closure.slot_total(data, "W") == pytest.approx(300.0 * 1.1)

    def test_hemoplague_debuff_option_probe(self):
        """r_hemoplague_debuff=False prices the unmarked rotation."""
        data = _closure_fight("Vladimir", options={"r_hemoplague_debuff": False})
        assert closure.slot_total(data, "R") == pytest.approx(350.0)
        assert closure.slot_total(data, "Q") == pytest.approx(160.0)

    def test_sanguine_pool_keeps_four_sourced_ticks(self):
        """The E2 tick certification survives the AMP (4 x 82.5 at rank 5)."""
        data = _closure_fight("Vladimir")
        assert closure.slot_total(data, "W") == pytest.approx(300.0 * 1.1, abs=0.6)
