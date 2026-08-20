"""Tests for the Nasus champion module."""

from src.calculator.champions import nasus
from tests import cc_review


class TestReviewedCrowdControl:
    """Nasus' reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Nasus")
        assert nasus.MODULE_CC == {"Q": "none", "E": "none", "R": "none"}
        for slot in ("Q", "E", "R"):
            assert cc_review.control_words(cc_review.slot_text(data, slot)) == []
        # W is absent rather than "none": Wither is the kit's one control,
        # but it deals no damage, so no event of its own could carry an
        # answer.  P is lifesteal and damages nothing.
        assert "W" not in nasus.MODULE_CC
        assert "slowing them by 35%" in cc_review.slot_text(data, "W")
        assert "P" not in nasus.MODULE_CC
        assert cc_review.control_words(cc_review.slot_text(data, "P")) == []

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Nasus") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Nasus")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


def test_p_is_modeled_through_the_48_6_soul_eater_lifesteal() -> None:
    """P emits a row with no enemy damage; the heal rule prices the slot.

    A level-18 itemless timed fight with autos pays Soul Eater 48.6 — the
    receipt behind P's ``modeled`` label.  W stays out of scope: Wither is
    CC magnitude, an axis the engine does not have.
    """
    import pytest

    from src.calculator.calculate import calculate_payload
    from src.calculator.champions import get_champion_module_contract

    contract = get_champion_module_contract("Nasus")
    assert contract.coverage["P"] == "modeled"
    assert contract.coverage["W"] == "out_of_scope"
    assert contract.coverage_channels["P"] == ("self_healing_rule",)

    payload = calculate_payload(
        {
            "champion": "Nasus",
            "level": 18,
            "fight_mode": "timed",
            "include_auto_attacks": True,
        }
    )
    paid = sum(
        float(event["amount"])
        for event in payload["self_healing_events"]
        if event["source"] == "Soul Eater"
    )
    assert paid == pytest.approx(48.6, abs=0.1)
