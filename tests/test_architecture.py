"""Static guards for high-value module boundaries."""

import ast
from pathlib import Path

from src.calculator.item_effects import _OFFLINE_ITEM_EFFECTS

ROOT = Path(__file__).parents[1]
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
