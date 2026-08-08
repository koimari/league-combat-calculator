"""Front-door tests for best-in-slot objectives and receipts."""

import pytest

from src.calculator.bis import bis_objective_contract, bis_objective_meta


def test_bis_objective_contract_has_stable_units() -> None:
    contract = bis_objective_contract()

    assert contract["overall"]["unit"] == "TDD"
    assert contract["survival"]["unit"] == "eHP"
    assert set(contract) == {"overall", "kill", "survival", "damage", "utility"}


def test_unknown_bis_objective_fails_closed() -> None:
    with pytest.raises(ValueError, match="objective must be one of"):
        bis_objective_meta("unknown")
