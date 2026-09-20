"""Mel's reviewed crowd control (``MODULE_CC`` plus Solar Snare's two parts).

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

from src.calculator.champions import (
    get_champion_module_contract,
    mel,
    parse_champion_abilities,
)
from src.calculator.champions.slot_cc import CC_PER_PART
from src.calculator.stats import calculate_total_stats
from tests import cc_review, coverage_truth, row_review
from functools import partial
from tests import champion_closure as closure
import pytest
from src.calculator.champions.slot_extract import extract_named
from src.calculator.champions.slot_extract import extract_value


class TestReviewedCrowdControl:
    """Solar Snare's orb roots and its field slows, so E answers per part."""

    def test_module_cc_is_the_declaration_the_parser_wired(self):
        assert mel.MODULE_CC == {
            "P": "none",
            "Q": "none",
            "E": CC_PER_PART,
            "R": "none",
            "W": "none",
        }
        assert mel.parse_abilities.cc_kinds == mel.MODULE_CC

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Mel")
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert cc_review.control_words(cc_review.slot_text(data, "R")) == []

    def test_solar_snares_orb_and_field_carry_their_own_kinds(self):
        text = cc_review.slot_text(cc_review.kit("Mel"), "E")
        assert "rooted for 1.5 seconds" in text
        assert "slowed by 30% every 0.125 seconds" in text
        data = cc_review.kit("Mel")
        parsed = parse_champion_abilities(
            data, 18, 100.0, champion_stats=calculate_total_stats(data, 18, [])
        )
        assert [part.cc_kind for part in parsed["E"]["parts"]] == ["root", "slow"]

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Mel") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Mel")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


class TestCoverageMap:
    """P prices its volley; W's reflection has no enemy projectile to read.

    W's damage is a percentage of an incoming enemy projectile's damage and
    the calculator's target never attacks, so the multiplicand is
    structurally absent - a ``no_damage`` receipt, not a gap.  The volley
    itself is pinned by ``tests/test_mel_searing_brilliance.py``.
    """

    def test_the_map_is_the_rows_the_module_prices(self):
        assert get_champion_module_contract("Mel").coverage == {
            "P": "modeled",
            "Q": "modeled",
            "W": "no_damage",
            "E": "modeled",
            "R": "modeled",
        }
        assert coverage_truth.emitted("Mel") == {
            "P": coverage_truth.PRICED,
            "Q": coverage_truth.PRICED,
            "W": coverage_truth.ZERO,
            "E": coverage_truth.PRICED,
            "R": coverage_truth.PRICED,
        }

    def test_the_reflection_row_is_a_share_of_someone_elses_damage(self):
        rows = {
            level["attribute"]
            for ability in cc_review.kit("Mel")["abilities"]["W"]
            for effect in ability["effects"]
            for level in effect["leveling"] or []
        }
        assert "Replicated Projectile Magic Damage Modifier" in rows
        assert "retain a ratio of the damage that the original ones would deal" in (
            cc_review.slot_text(cc_review.kit("Mel"), "W")
        )
        assert row_review.entry("Mel", "W")["total_raw"] == 0.0


# One rotation at level 18 into the bare 2000-HP dummy; slot rows are parsed
# against the shared reference stat block.
_closure_fight = partial(closure.fight, role="top")
_closure_parse = closure.reference_abilities


# ---------------------------------------------------------------------------
# Mel — Q full volley + E field DoT
# ---------------------------------------------------------------------------


class TestMel:
    """P1-3: Q prices the full 6-10 bolt volley; E prices the field DoT."""

    def test_q_prices_initial_plus_subsequent_bolts(self):
        """Q: Initial Explosion + (Number of Bolts - 1) x Subsequent ==
        the wiki's Total Magic Damage row."""
        data = _closure_fight("Mel")
        stats = closure.fight_stats(data)
        target = closure.target_stats(data)
        total = extract_named(
            closure.ability_row("Mel", "Q"), "Total Magic Damage", 5, stats, target
        )
        assert total == pytest.approx(277.0)
        assert closure.slot_total(data, "Q") == pytest.approx(
            total, abs=closure.ROUNDING
        )

    def test_e_prices_orb_plus_four_field_ticks(self):
        """E: orb + 4 field ticks (game-file DoTDuration 0.5s x 8/s)."""
        data = _closure_fight("Mel")
        stats = closure.fight_stats(data)
        target = closure.target_stats(data)
        orb = extract_named(
            closure.ability_row("Mel", "E"), "Orb Magic Damage", 5, stats, target
        )
        per_tick = extract_named(
            closure.ability_row("Mel", "E"),
            "Field Magic Damage per Tick",
            5,
            stats,
            target,
        )
        assert closure.slot_total(data, "E") == pytest.approx(orb + 4 * per_tick)

    def test_r_overwhelm_stacks_option_probe(self):
        """r_overwhelm_stacks scales the R per-stack term (probe)."""
        data = _closure_fight("Mel", options={"r_overwhelm_stacks": 5})
        stats = closure.fight_stats(data)
        flat = extract_named(
            closure.ability_row("Mel", "R"), "Magic Damage", 3, stats, {}
        )
        per_stack = extract_value(closure.ability_row("Mel", "R"), "Magic Damage", 3, 2)
        assert closure.slot_total(data, "R") == pytest.approx(flat + per_stack * 5)
