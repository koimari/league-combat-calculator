"""Reviewed crowd control for Zac (MODULE_CC).

Stretching Strikes slows, Elastic Slingshot knocks up, and Let's Bounce!
displaces on its opening bounce only — so R's kinds are authored per part.
"""

from src.calculator.champions import parse_champion_abilities, zac
from tests import cc_review
from src.calculator.champions.engine import CC_PER_PART

_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}


class TestReviewedCrowdControl:
    """Zac's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Zac")
        assert zac.MODULE_CC == {
            "Q": "slow",
            "W": "none",
            "E": "knockup",
            "R": CC_PER_PART,
        }
        assert zac.parse_abilities.cc_kinds == zac.MODULE_CC
        q_text = cc_review.slot_text(data, "Q")
        assert "slowing them by 40% for 0.5 seconds" in q_text
        # Q's root and knock-up need a second, different target.
        assert "if the two stretching strikes affect different targets" in q_text
        assert "knocks them up and stuns them for 0.5 seconds" in (
            cc_review.slot_text(data, "E")
        )
        assert cc_review.control_words(cc_review.slot_text(data, "W")) == []

    def test_lets_bounce_displaces_only_on_its_opening_bounce(self):
        data = cc_review.kit("Zac")
        assert zac.MODULE_CC["R"] == CC_PER_PART
        r_text = cc_review.slot_text(data, "R")
        assert "knocks them back over 1 second, and slows them by 20%" in r_text
        assert "do not apply the knock back" in r_text
        parsed = parse_champion_abilities(data, 18, 100.0, _RANKS)
        opening, later = parsed["R"]["parts"]
        assert opening.cc_kind == "knockback"
        assert later.cc_kind == "slow" and later.count == 3

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Zac") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Zac")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


def test_p_is_modeled_through_the_1269_cell_division_revive() -> None:
    """P's own packet row prices nothing; two channels price the slot.

    Cell Division revives with 50% of Zac's maximum health — 1269.0 at
    level 18 with no items — and the healing rule pays the Goo chunk on
    every ability hit.  Those are the receipts behind P's ``modeled``
    label, not the zero-valued packet row.
    """
    import pytest

    from src.calculator.champions import get_champion_module_contract
    from src.calculator.defensive_effects import resolve_starting_defenses
    from src.calculator.stats import calculate_total_stats

    contract = get_champion_module_contract("Zac")
    assert contract.coverage["P"] == "modeled"
    assert contract.coverage_channels["P"] == (
        "starting_revive_defense",
        "self_healing_rule",
    )

    data = cc_review.kit("Zac")
    parsed = parse_champion_abilities(data, 18, 0.0, _RANKS)
    assert parsed["passive"]["total_raw"] == 0.0

    defenses = resolve_starting_defenses(
        "Zac", 18, calculate_total_stats(data, 18, []), []
    )
    assert defenses.revive_source == "Cell Division"
    assert defenses.revive_health_amount == pytest.approx(1269.0)
