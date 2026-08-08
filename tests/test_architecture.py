"""Static guards for high-value module boundaries."""

import ast
from pathlib import Path

from src.calculator.item_effects import _OFFLINE_ITEM_EFFECTS

ROOT = Path(__file__).parents[1]

# These modules are large enough to need a named entry point.  The older
# campaign suites remain in place because their issue history is useful when
# a regression is investigated.
SUBSTANTIAL_MODULE_FRONT_DOORS = (
    "passive_parser",
    "healing",
    "rotation_resolver",
    "capabilities",
    "bis",
    "public_response",
    "atomizer_domains",
    "loadout_rules",
    "auto_attack_policy",
    "data_registry",
    "economics_data",
)
DAMAGE_PATH = ROOT / "src" / "calculator" / "damage.py"


def test_damage_engine_does_not_read_item_registry() -> None:
    """Registry dictionaries belong to item_effects, never damage.py."""
    source = DAMAGE_PATH.read_text(encoding="utf-8")
    assert "ITEM_EFFECTS" not in source


def test_damage_engine_does_not_dispatch_on_item_names() -> None:
    """Item identity compiles into typed effects before engine execution."""
    tree = ast.parse(DAMAGE_PATH.read_text(encoding="utf-8"))
    item_names = frozenset(_OFFLINE_ITEM_EFFECTS)
    offenders: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        compared = [node.left, *node.comparators]
        for value in compared:
            if isinstance(value, ast.Constant) and value.value in item_names:
                offenders.append((node.lineno, value.value))

    assert offenders == []


def test_substantial_calculator_modules_have_named_test_front_doors() -> None:
    """Production module names must lead maintainers to a test suite."""
    missing = [
        module
        for module in SUBSTANTIAL_MODULE_FRONT_DOORS
        if not (ROOT / "tests" / f"test_{module}.py").is_file()
    ]
    assert missing == []
