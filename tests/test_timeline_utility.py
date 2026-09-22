"""``timeline/utility.py``'s own contract: one ledger, rows of many shapes.

One actor's support ledger holds every packet kind at once, so a movement row
carries no ``gold_amount`` and an economy row carries no ``slow_percent``.  The
receipt reads each dimension off the rows of that kind and defaults every field
the row does not carry, which is why indexing those reads instead would turn a
partial row into a crash.  The leaf took those defaults out of
``participant_timeline`` with the fold; this is where the tolerance behind them
is pinned.
"""

import pytest

from src.calculator.roster_composition import Combatant
from src.calculator.starting_defenses import StartingDefenses
from src.calculator.timeline.utility import _utility_outcome_receipt


def _actor() -> Combatant:
    """One item-less actor: of the actor the receipt reads only the items."""
    return Combatant(
        participant_id="main",
        team="main",
        champion_data={"name": "Ahri"},
        level=18,
        items=(),
        stats={},
        defenses=StartingDefenses(),
    )


def test_each_support_row_folds_into_its_own_dimension_and_defaults_the_rest():
    """Three kinds, three shapes, one ledger: no row answers another's field."""
    receipt = _utility_outcome_receipt(
        _actor(),
        [
            {
                "kind": "movement",
                "amount": 30.0,
                "duration": 2.0,
                "applied_amount": 30.0,
            },
            {
                "kind": "slow",
                "slow_percent": 40.0,
                "duration": 1.5,
                "applied_amount": 40.0,
            },
            {"kind": "economy", "gold_amount": 350.0, "applied_amount": 350.0},
        ],
        [],
    )

    assert receipt["movement"]["event_count"] == 1
    assert receipt["movement"]["speed_percent_seconds"] == pytest.approx(60.0)
    assert receipt["slow"]["event_count"] == 1
    assert receipt["slow"]["percent_seconds"] == pytest.approx(60.0)
    assert receipt["economy"]["gold"] == pytest.approx(350.0)
    # The economy row carries no applied share of its own, and the two that
    # do are counted whole: a dimension nobody wrote to reads zero.
    assert receipt["scored_support_amount"] == pytest.approx(70.0)
    assert receipt["vision"]["ward_uses"] == 0
    assert receipt["resource"]["bonus_mana"] == 0
    assert receipt["damage_reduction"]["ratio_seconds"] == 0
    assert sorted(receipt["applied_dimensions"]) == ["economy", "movement", "slow"]
