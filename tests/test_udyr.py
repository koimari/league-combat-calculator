"""Udyr's reviewed crowd control (``MODULE_CC``).

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

from src.calculator.champions import get_champion_module_contract, udyr
from tests import cc_review
from functools import partial
from tests import champion_closure as closure
import pytest


class TestReviewedCrowdControl:
    """Wingborne Storm's blizzard is the kit's only cast-damage row."""

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Udyr")
        # A cc-only slot states its kind in MODULE_CC like any other and
        # publishes the sourced interval as a ControlEvent (CF8).
        assert udyr.MODULE_CC == {
            "E": "stun",
            "R": "slow",
            "P": "none",
            "Q": "none",
            "W": "none",
        }
        assert "slows them while they remain within" in cc_review.slot_text(data, "R")
        # Blazing Stampede is where the kit's stun lives, and it deals no
        # damage of its own, so no part can carry that answer: the stun is
        # published as a standalone sourced ControlEvent instead (the
        # Rammus-E shape), which is what lets E be no_damage — nothing
        # damage-relevant is left unmodeled — rather than out_of_scope.
        assert cc_review.control_words(cc_review.slot_text(data, "E")) == ["stun"]
        assert get_champion_module_contract("Udyr").coverage["E"] == "no_damage"

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Udyr") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Udyr")
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
# Udyr — Q Wilding Claw empowered attacks (+ Awaken)
# ---------------------------------------------------------------------------


class TestUdyr:
    """Q's stance empowers 2 basic attacks with the sourced on-hit payload
    (7% max health + 3.5% per 100 bonus AD, plus the 4s on-hit flat);
    q_awaken adds the per-level Max Health Damage row and the lightning
    chain."""

    def test_q_empowered_attacks_on_hit(self) -> None:
        data = _closure_fight(
            "Udyr", include_autos=True, mode="time_based", duration=5.0, ranks=None
        )
        row = data["breakdown"]["on_hit_ability_Q"]
        # rank 5: 7% of 2000 + 3.5% per 100 bonus AD (0) + flat 30.
        expected_per_hit = 0.07 * 2000.0 + 30.0
        assert row["damage_per_hit"] == pytest.approx(expected_per_hit, abs=0.1)
        assert row["count"] == 2
        assert row["total_damage"] == pytest.approx(expected_per_hit * 2, abs=0.6)

    def test_q_awaken_adds_max_health_and_lightning(self) -> None:
        data = _closure_fight(
            "Udyr",
            options={"q_awaken": True},
            include_autos=True,
            mode="time_based",
            duration=5.0,
            ranks=None,
        )
        on_hit = data["breakdown"]["on_hit_ability_Q"]
        # level 18: 4.0% of 2000 extra physical per empowered attack.
        assert on_hit["total_damage"] == pytest.approx(
            (0.07 * 2000.0 + 30.0 + 0.04 * 2000.0) * 2, abs=0.6
        )
        # lightning: 6 strikes x 2 attacks x 3.0% of 2000 magic.
        assert data["breakdown"]["Q"]["total_damage"] == pytest.approx(
            6 * 2 * (0.03 * 2000.0), abs=0.6
        )


def test_the_closed_slots_are_declared_modeled() -> None:
    """Every slot this module closed says so in its MODULE_COVERAGE."""
    coverage = closure.module_coverage("udyr")
    assert {slot: coverage[slot] for slot in ("Q", "W", "R")} == {
        "Q": "modeled",
        "W": "modeled",
        "R": "modeled",
    }
