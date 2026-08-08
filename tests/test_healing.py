"""Front-door tests for champion-owned healing rules.

Detailed issue and champion cases remain in the E1 and ledger suites.  The
Taric case here gives the shared healing module an obvious first file.
"""

import pytest

from src.calculator.data_fetcher import get_champion
from src.calculator.healing import derive_self_healing


def test_taric_q_prices_the_sourced_five_charge_self_heal() -> None:
    heals = derive_self_healing(
        get_champion("Taric"),
        {"level": 18, "health": 2000.0, "ability_power": 0.0},
        {"Q": {"rank": 5}},
        [],
        [{"slot": "Q", "time": 1.0}],
        5.0,
    )

    assert len(heals) == 1
    assert heals[0]["amount"] == pytest.approx(225.0)
    assert heals[0]["source"] == "Starlight's Touch"
    assert heals[0]["charges"] == 5


def test_unknown_champion_has_no_inferred_healing() -> None:
    assert (
        derive_self_healing(
            {"name": "Synthetic Fixture"},
            {"level": 18},
            {},
            [],
        )
        == []
    )
