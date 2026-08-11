"""Regression tests for the Issue #160 ownership boundaries."""

from importlib import import_module
import inspect
from pathlib import Path

from src.calculator import healing
from src.calculator.champions import _CHAMPION_MODULES
from src.calculator.participant_timeline import build_participant_timeline
from src.calculator.timeline_optimizer import (
    CoupledSearchContext,
    _score_with_search_context,
)
from src.calculator.timeline_receipts import assemble_public_receipt


def test_each_healing_declaration_calls_a_resolver_in_its_champion_module():
    assert len(healing.HEALING_RULE_CHAMPIONS) == 59

    for champion_name in sorted(healing.HEALING_RULE_CHAMPIONS):
        module_name = _CHAMPION_MODULES[champion_name]
        module = import_module(f"src.calculator.champions.{module_name}")
        declaration = module.SELF_HEALING_RULE

        assert declaration.champion_name == champion_name
        assert declaration.resolver is not None
        assert declaration.resolver.__module__ == module.__name__


def test_retired_healing_dispatcher_has_no_champion_name_formula_chain():
    source = Path("src/calculator/healing_legacy.py").read_text()

    assert "if name ==" not in source
    assert "elif name ==" not in source
    assert "_legacy_derive_self_healing" in source


def test_optimizer_and_public_receipt_assembly_have_named_owners():
    assert CoupledSearchContext.__module__ == "src.calculator.timeline_optimizer"
    assert _score_with_search_context.__module__ == "src.calculator.timeline_optimizer"
    assert assemble_public_receipt.__module__ == "src.calculator.timeline_receipts"

    composer_source = inspect.getsource(build_participant_timeline)
    assert "return assemble_public_receipt(" in composer_source
    assert '"events": [' not in composer_source
    assert '"support_events": [' not in composer_source
