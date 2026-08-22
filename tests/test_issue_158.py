"""Architecture and behavior regressions for issue #158."""

from pathlib import Path

import pytest

from src.calculator.pipeline import FightParams

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


def test_public_scalar_parsers_have_one_owner() -> None:
    """Routes, scenarios, and fight params consume the shared parse policy."""
    for relative_path in (
        "src/app.py",
        "src/calculator/scenario.py",
        "src/calculator/pipeline.py",
    ):
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        assert "from src.calculator.request_parsing import" in source or (
            "from .request_parsing import" in source
        )
        assert "def _request_int(" not in source
        assert "def _request_string(" not in source
        assert "def _request_string_list(" not in source


def test_calculate_payload_runs_without_flask_request_context() -> None:
    """The application calculation returns a JSON-safe payload directly."""
    from src.calculator.calculate import calculate_payload

    payload = calculate_payload({"champion": "Ahri", "level": 1})

    assert payload["total_damage"] >= 0
    assert payload["engine"]["registration"] == "reviewed_module"


def test_app_has_no_flask_calculate_round_trip() -> None:
    """Flask delegates calculation and never decodes its own Response."""
    source = (ROOT / "src/app.py").read_text(encoding="utf-8")

    assert "def _calculate_response(" not in source
    assert "def _run_calculate_payload(" not in source
    assert "response.get_json()" not in source
    assert "calculate_payload(" in source


def test_comparison_curve_reuses_resolved_target_projection() -> None:
    """Crossover windows cannot maintain a second target-defense field list."""
    app_source = (ROOT / "src/app.py").read_text(encoding="utf-8")
    calculate_source = (ROOT / "src/calculator/calculate.py").read_text(
        encoding="utf-8"
    )

    assert "resolved.target_fight_params" in calculate_source
    assert "target_threshold_shield_amount=" not in app_source


def test_bis_application_boundary_runs_without_flask_context() -> None:
    """BIS parsing and validation live behind the calculator.bis façade."""
    from src.calculator.bis import bis_payload

    with pytest.raises(ValueError, match="subject_team must be"):
        bis_payload({"champion": "Ahri", "subject_team": "spectator"})


def test_bis_route_only_delegates_and_translates() -> None:
    """The route never owns candidate construction, scoring, or ranking."""
    import ast

    source = (ROOT / "src/app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    route = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "api_bis"
    )
    route_source = ast.get_source_segment(source, route) or ""

    # The route names the façade and hands it to the shared operation ladder,
    # which is the only thing that calls it with the decoded body.
    assert "_pure_payload_response" in route_source
    assert "bis_payload" in route_source
    assert "for candidate in candidates" not in route_source
    assert "ranked.sort" not in route_source


def test_optimizer_errors_are_typed_not_message_classified() -> None:
    """HTTP error codes come from optimizer types, never English prefixes."""
    source = (ROOT / "src/app.py").read_text(encoding="utf-8")
    optimizer_source = (ROOT / "src/calculator/optimizer.py").read_text(
        encoding="utf-8"
    )

    assert "message.startswith(" not in source
    assert "NoCompleteEventOrder(" in optimizer_source


def test_routes_use_loadout_rule_owners() -> None:
    """Inventory and boot-tier decisions have no route-local conditionals."""
    source = (ROOT / "src/app.py").read_text(encoding="utf-8")

    assert "inventory_capacity(" in source
    assert "required_boots_tier(" in source
    assert 'fight_params.role == "mid"' not in source
    assert 'fight_params.role == "bottom"' not in source


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
