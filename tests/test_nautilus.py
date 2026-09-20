"""Tests for the Nautilus champion module."""

from functools import partial

import pytest

from src.calculator.champions import nautilus
from src.calculator.champions.slot_extract import extract_named
from tests import cc_review
from tests import champion_closure as closure


class TestReviewedCrowdControl:
    """Nautilus' reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Nautilus")
        assert nautilus.MODULE_CC == {
            "Q": "immobilize",
            "W": "none",
            "E": "slow",
            "R": "immobilize",
            "P": "root",
        }
        # Q and R each apply two immobilize kinds in one cast, which is
        # what the un-narrowed "immobilize" states.
        q_text = cc_review.slot_text(data, "Q")
        assert "stuns them for 1 second" in q_text
        assert "drags them toward nautilus" in q_text
        r_text = cc_review.slot_text(data, "R")
        assert "knocked up for 1 second, and stunned for a duration" in r_text
        assert cc_review.control_words(cc_review.slot_text(data, "W")) == []
        assert "slows them by an amount that decays" in cc_review.slot_text(data, "E")

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Nautilus") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Nautilus")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


# One rotation at level 18 into the bare 2000-HP dummy, and the same fight
# into an Ahri enemy, which is what produces the coupled participant ledger.
_closure_fight = partial(closure.fight, role="mid", duration=5.0)
_closure_enemy_fight = partial(
    closure.fight, role="top", enemy=closure.AHRI, target_health=None
)
_closure_parse = closure.abilities


# ---------------------------------------------------------------------------
# Nautilus — W two-instance Total Magic Damage + R primary-target damage
# ---------------------------------------------------------------------------


class TestNautilus:
    """W prices Total Magic Damage (70 at rank 5) across its two sourced
    instances; R prices the primary-target Increased Damage (400 at rank
    3); the W shield is scanner-emitted."""

    def test_w_prices_total_across_two_instances(self) -> None:
        data = _closure_fight("Nautilus")
        assert data["breakdown"]["W"]["total_damage"] == pytest.approx(70.0)
        events = _closure_enemy_fight("Nautilus")
        w_events = [
            e
            for e in events["combat"]["events"]
            if e.get("attacker") == "main" and e.get("source") == "W"
        ]
        assert len(w_events) == 2
        assert sum(float(e["raw_damage"]) for e in w_events) == pytest.approx(70.0)

    def test_r_prices_primary_target_increased_damage(self) -> None:
        data = _closure_fight("Nautilus")
        assert data["breakdown"]["R"]["total_damage"] == pytest.approx(400.0)

    def test_w_shield_emitted(self) -> None:
        data = _closure_enemy_fight("Nautilus")
        shields = closure.main_support(data, "Titan's Wrath")
        assert shields
        stats = closure.stats("Nautilus")
        expected = extract_named(
            closure.ability_row("Nautilus", "W"),
            "Shield Strength",
            5,
            stats,
            closure.TARGET_2000,
        )
        assert float(shields[0]["amount"]) == pytest.approx(expected, abs=0.2)


def test_the_closed_slots_are_declared_modeled() -> None:
    """Every slot this module closed says so in its MODULE_COVERAGE."""
    coverage = closure.module_coverage("nautilus")
    assert {slot: coverage[slot] for slot in ("P", "W", "R")} == {
        "P": "modeled",
        "W": "modeled",
        "R": "modeled",
    }
