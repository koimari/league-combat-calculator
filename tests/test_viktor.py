"""Reviewed crowd control for Viktor (MODULE_CC).

Every modelled slot is control-free; the slow and stun live in Gravity
Field, which this module does not price.
"""

from src.calculator.champions import get_champion_module_contract, viktor
from tests import cc_review
from functools import partial
from tests import champion_closure as closure
import pytest


class TestReviewedCrowdControl:
    """Viktor's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Viktor")
        # A cc-only slot states its kind in MODULE_CC like any other and
        # publishes the sourced interval as a ControlEvent (CF8).
        assert viktor.MODULE_CC == {
            "Q": "none",
            "W": "slow",
            "E": "none",
            "R": "none",
            "P": "none",
        }
        assert viktor.parse_abilities.cc_kinds == viktor.MODULE_CC
        for slot in ("Q", "E", "R"):
            assert cc_review.control_words(cc_review.slot_text(data, slot)) == [], slot

    def test_the_coverage_labels_match_what_the_slots_emit(self):
        # W emits its sourced control event, so it is no_damage, not
        # out_of_scope; P alone stays outside the model.
        contract = get_champion_module_contract("Viktor")
        assert contract.coverage["W"] == "no_damage"
        assert contract.coverage["P"] == "out_of_scope"

    def test_gravity_field_publishes_the_slow_it_can_source(self):
        """W prices no damage, so its slow is a sourced control event.

        The 1-second refreshing slow window and the ranked Slow row both
        have atoms; the fifth-stack 1.5s stun has none, so it stays
        unpriced rather than being declared against a prose literal.
        """
        data = cc_review.kit("Viktor")
        w_text = cc_review.slot_text(data, "W")
        assert "slow enemies within for 1 second" in w_text
        assert "knock down and stun the target for 1.5 seconds" in w_text

    def test_arcane_storms_disrupt_is_not_a_kind_in_the_vocabulary(self):
        """R interrupts channels; no control-armed passive keys on that."""
        data = cc_review.kit("Viktor")
        r_text = cc_review.slot_text(data, "R")
        assert "disrupting their channeled abilities" in r_text
        assert cc_review.control_words(r_text) == []

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Viktor") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Viktor")
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
# Viktor — Q shield + Discharge empowered auto
# ---------------------------------------------------------------------------


class TestViktor:
    """Q grants the per-level shield (140 at level 18) for 2.5s and its
    Discharge empowers the next basic attack (Modified Magic Damage)."""

    def test_q_shield_emitted(self) -> None:
        data = _closure_enemy_fight("Viktor")
        shields = closure.main_support(data, "Siphon Power")
        assert shields
        assert float(shields[0]["amount"]) == pytest.approx(140.0, abs=0.2)
        assert float(shields[0]["duration"]) == pytest.approx(2.5)

    def test_q_discharge_on_hit(self) -> None:
        stats = closure.stats("Viktor")
        expected = 120.0 + 1.0 * float(stats["attack_damage"])
        data = _closure_fight(
            "Viktor", include_autos=True, mode="time_based", duration=5.0
        )
        row = data["breakdown"]["on_hit_ability_Q"]
        assert row["count"] == 1
        assert row["damage_per_hit"] == pytest.approx(expected, abs=0.1)

    def test_q_discharge_option_off(self) -> None:
        data = _closure_fight(
            "Viktor",
            options={"q_discharge": False},
            include_autos=True,
            mode="time_based",
            duration=5.0,
        )
        assert "on_hit_ability_Q" not in data["breakdown"]


def test_the_closed_slots_are_declared_modeled() -> None:
    """Every slot this module closed says so in its MODULE_COVERAGE."""
    coverage = closure.module_coverage("viktor")
    assert {slot: coverage[slot] for slot in ("Q", "E", "R")} == {
        "Q": "modeled",
        "E": "modeled",
        "R": "modeled",
    }
