"""Architecture and behavior regressions for issue #158."""

from pathlib import Path

import pytest

from src.calculator.fight_params import FightParams

ROOT = Path(__file__).parents[1]


def test_public_integer_policy_accepts_numeric_strings() -> None:
    """Every public entry point accepts a canonical integer string."""
    params = FightParams.from_request({"rotations": "3"})

    assert params.rotation_count == 3


def test_public_integer_policy_rejects_booleans_and_decimals() -> None:
    """Integer inputs never coerce booleans or decimal strings."""
    with pytest.raises(ValueError, match="rotations must be an integer"):
        FightParams.from_request({"rotations": True})
    with pytest.raises(ValueError, match="rotations must be an integer"):
        FightParams.from_request({"rotations": "3.0"})


def test_calculate_payload_runs_without_flask_request_context() -> None:
    """The application calculation returns a JSON-safe payload directly."""
    from src.calculator.calculate import calculate_payload

    payload = calculate_payload({"champion": "Ahri", "level": 1})

    assert payload["total_damage"] >= 0
    assert payload["engine"]["registration"] == "reviewed_module"


def test_bis_application_boundary_runs_without_flask_context() -> None:
    """BIS parsing and validation live behind the calculator.bis façade."""
    from src.calculator.bis import bis_payload

    with pytest.raises(ValueError, match="subject_team must be"):
        bis_payload({"champion": "Ahri", "subject_team": "spectator"})


def test_observed_paste_logic_has_a_non_flask_owner() -> None:
    """Combat-log parsing is reusable without importing the web app."""
    from src.calculator.validation_receipts import parse_observed_paste

    assert parse_observed_paste("Q 100\nW 50\ntotal 150") == {
        "tdd": 150.0,
        "sources": {"Q": 100.0, "W": 50.0},
    }
    source = (ROOT / "src/app.py").read_text(encoding="utf-8")
    assert "def _parse_observed_paste(" not in source
    assert "def _normalize_observed_payload(" not in source


def test_certainty_logic_has_a_non_flask_owner() -> None:
    """Trust classification is domain code callable without request state."""
    from src.calculator.certainty import derive_certainty
    from src.calculator.data_fetcher import get_champion

    receipt = derive_certainty("Ahri", get_champion("Ahri"))

    assert receipt["certified"] is True
    assert receipt["slots"]["Q"]["certainty"] == "exact"
    source = (ROOT / "src/app.py").read_text(encoding="utf-8")
    assert "def _derive_certainty(" not in source
    assert "def _slot_certainty(" not in source


def test_validation_receipt_calculation_is_reusable() -> None:
    """Prediction comparison and tolerance arithmetic have one owner."""
    from src.calculator.validation_receipts import evaluate_validation_receipt

    evaluation = evaluate_validation_receipt(
        {"total_damage": 100.0, "breakdown": {"Q": {"total_damage": 80.0}}},
        {"off_by_percent": 10, "direction": "higher"},
    )

    assert evaluation["public"] == {
        "predicted": {"tdd": 100.0, "sources": {"Q": 80.0}},
        "observed": {"tdd": 110.0, "sources": {}},
        "delta": 10.0,
        "tolerance": 20.0,
        "matched": True,
    }
    assert evaluation["raw_delta"] == 10.0
