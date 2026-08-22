"""Reviewed crowd control for Vex, and the two hits R now lands separately.

Doom empowers "her next basic ability", which is fight state this module
does not price — but no slot's kind depends on it, so the whole kit
answers once R's row stops summing its two hits into one instant.
"""

import math

import pytest

from src.calculator.champions import parse_champion_abilities, vex
from src.calculator.champions.slotlib import (
    extract_description_duration,
    extract_named,
    find_named_leveling,
    sum_modifiers,
)
from tests import cc_review

RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}


def _r_ability():
    return cc_review.kit("Vex")["abilities"]["R"][0]


def _parse(ability_power=100.0):
    return parse_champion_abilities(cc_review.kit("Vex"), 18, ability_power, RANKS)


class TestShadowSurgeSplit:
    """R is two hits: the Shadow's, and the recast consume it marked for."""

    def test_the_two_cached_rows_compose_the_cached_total(self):
        """The split is exact, at every rank — that is what licenses it."""
        ability = _r_ability()
        stats = {"ability_power": 100.0}
        for rank in (1, 2, 3):
            surge = extract_named(ability, "Magic Damage", rank, stats, {})
            recast = sum_modifiers(
                find_named_leveling(ability, "Magic Damage", 1), rank, stats, {}
            )
            total = extract_named(ability, "Total Magic Damage", rank, stats, {})
            assert math.isclose(surge + recast, total, rel_tol=1e-9, abs_tol=1e-6)

    def test_the_row_lands_two_parts_at_their_own_instants(self):
        parts = _parse()["R"]["parts"]
        assert len(parts) == 2
        # Rank 3: the Shadow's 175 + 20% AP, the recast's 350 + 50% AP.
        assert parts[0].amount == pytest.approx(195.0)
        assert parts[1].amount == pytest.approx(400.0)
        assert parts[0].time_offset == pytest.approx(0.0)
        assert parts[1].time_offset == pytest.approx(
            vex._R_RECAST_DELAY_SECONDS  # pylint: disable=protected-access
        )

    def test_the_split_keeps_the_cached_total(self):
        entry = _parse()["R"]
        assert sum(part.amount for part in entry["parts"]) == pytest.approx(
            entry["total_raw"]
        )
        assert entry["total_raw"] == pytest.approx(595.0)

    def test_the_authored_cadence_fits_inside_the_cached_mark(self):
        """The recast's instant is the player's; the window it sits in is
        cached, and the parser refuses the slot without one."""
        window = extract_description_duration(
            _r_ability(), vex._R_MARK_EFFECT_INDEX  # pylint: disable=protected-access
        )
        assert window == pytest.approx(4.0)
        assert (
            0.0
            < vex._R_RECAST_DELAY_SECONDS  # pylint: disable=protected-access
            <= window
        )


class TestReviewedCrowdControl:
    """Vex's crowd-control review, now complete across the kit.

    Doom's fear is fight state this module does not price: it empowers
    "her next basic ability" on its own cooldown, and against Looming
    Darkness it replaces E's own slow with a flee.  Neither changes what
    any slot's own cast does, which is what MODULE_CC declares.
    """

    def test_the_kit_declares_every_slot(self):
        data = cc_review.kit("Vex")
        assert vex.MODULE_CC == {
            "P": "none",
            "Q": "none",
            "W": "none",
            "E": "slow",
            "R": "none",
        }
        assert vex.parse_abilities.cc_kinds == vex.MODULE_CC
        passive = cc_review.slot_text(data, "P")
        assert "empowers her next basic ability to knock down and fear" in passive
        assert "flee from the epicenter instead" in passive

    def test_looming_darkness_slow_is_the_one_the_flee_overrides(self):
        data = cc_review.kit("Vex")
        assert "slowing them for 2 seconds" in cc_review.slot_text(data, "E")

    def test_shadow_surge_marks_and_reveals_but_controls_nothing(self):
        """The mark only reveals, and the dash's displacement immunity is
        Vex's own — so "none" is the read, and the split gives it a hit
        time the ledger can stamp it on."""
        r_text = cc_review.slot_text(cc_review.kit("Vex"), "R")
        assert (
            "shadow stops upon hitting an enemy champion to mark them for "
            "4 seconds, during which they are revealed. shadow surge can "
            "be recast while the target is marked" in r_text
        )
        assert (
            "recast: vex dashes towards the marked target with "
            "displacement immunity. upon arrival, she consumes their mark "
            "and deals magic damage" in r_text
        )
        assert cc_review.control_words(r_text) == []

    def test_no_slot_keeps_the_fight_coarse(self):
        """R was the last coarse source (ER2); its two hits now land at
        their own instants, so the control-armed scan is complete."""
        assert cc_review.unreviewed_ability_slots("Vex") == []
        coverage = cc_review.fimbulwinter_coverage("Vex")
        assert coverage["complete"] is True
        assert coverage["coarse_sources"] == []
