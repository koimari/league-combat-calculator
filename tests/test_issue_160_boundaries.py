"""Regression tests for the Issue #160 ownership boundaries."""

import inspect
from importlib import import_module
from pathlib import Path

from src.calculator import healing
from src.calculator.champions import _CHAMPION_MODULES
from src.calculator.participant_timeline import build_participant_timeline


def test_each_healing_declaration_calls_a_resolver_in_its_champion_module():
    # 59 on main plus Cho'Gath, Mordekaiser and Rek'Sai, whose rules the
    # sustain slice added.  The set is derived from the declarations, so it
    # has no hand-list to drift from -- main's retired frozenset had already
    # fallen two names behind its own modules.
    assert len(healing.HEALING_RULE_CHAMPIONS) == 62

    for champion_name in sorted(healing.HEALING_RULE_CHAMPIONS):
        module_name = _CHAMPION_MODULES[champion_name]
        module = import_module(f"src.calculator.champions.{module_name}")
        declaration = module.SELF_HEALING_RULE

        assert declaration.champion_name == champion_name
        assert declaration.resolver is not None
        assert declaration.resolver.__module__ == module.__name__


def test_no_global_dispatcher_survives_the_champion_owned_migration():
    """The retired dispatcher is gone, module and all.

    A champion-name formula chain is exactly what module ownership
    replaced, so neither the retired file nor a name chain inside the
    entrypoint may come back.
    """
    assert not Path("src/calculator/healing_legacy.py").exists()
    assert not Path("src/calculator/champions/healing_rules.py").exists()

    source = Path("src/calculator/healing.py").read_text(encoding="utf-8")
    assert "if name ==" not in source
    assert "elif name ==" not in source


def test_optimizer_and_public_receipt_assembly_have_named_owners():
    """The compiled score path and receipt assembly live in ``program/``.

    Main's split of ``participant_timeline`` into ``timeline_optimizer`` /
    ``timeline_receipts`` was a second copy of that path (it broke the
    one-walk-call-site gate in ``test_program_structure``); neither file
    may come back.
    """
    assert not Path("src/calculator/timeline_optimizer.py").exists()
    assert not Path("src/calculator/timeline_receipts.py").exists()

    composer_source = inspect.getsource(build_participant_timeline)
    assert '"events": [' not in composer_source
    assert '"support_events": [' not in composer_source
