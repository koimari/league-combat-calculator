"""Item identity compiles into typed effects before the fight engine runs.

Three rules over `damage.py` and every step of the `fight/` package:

* no step reads a registry dictionary; `ITEM_EFFECTS` belongs to
  `item_effects`;
* no step compares a value against a cached item name, which is dispatch on
  item identity after the point identity was supposed to be gone;
* a step spells a cached item name in code only inside the declared frontier
  below, and set equality holds both ways, so a step that stops spelling one
  leaves in the same commit and a step that starts cannot arrive quietly.

    python scripts/item_name_boundary.py

`tests/test_architecture.py` calls this.
"""

from __future__ import annotations

import ast
import sys
from collections.abc import Mapping
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lint_report import report

from src.calculator.item_effects import _REFERENCE_ITEM_EFFECTS

ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = ROOT / "src" / "calculator"

# The fight engine: the orchestrator and every step of the `fight/` package.
# All three rules are about the engine rather than about one file, so they
# read the whole package.
FIGHT_ENGINE_PATHS = (
    SRC_ROOT / "damage.py",
    *sorted((SRC_ROOT / "fight").rglob("*.py")),
)

#: The nodes a docstring may be the first statement of.
DOCSTRING_SCOPES = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)

#: The registry dictionary a step may not read.
REGISTRY = "ITEM_EFFECTS"


# The steps that still spell a cached item name in code, and what each is
# waiting on.  Set equality, so a step that stops spelling one leaves in the
# same commit and a step that starts spelling one cannot arrive quietly.  A
# name inside a docstring is prose about the mechanic and is not a dispatch,
# so the scan skips docstrings and reads every other literal.
ITEM_NAME_LITERAL_FRONTIER: Mapping[str, tuple[str, frozenset[str]]] = {
    "damage.py": (
        "the published source label on each resource-restore event; it moves "
        "with the restore rule the resource walk names below",
        frozenset({"Catalyst of Aeons"}),
    ),
    "fight/items/eclipse_stack_gate.py": (
        "the row title of the one windowed cooldown proc; it moves when the "
        "cast-proc family reads its display name off the declaration",
        frozenset({"Eclipse"}),
    ),
    "fight/ledger/pool_walk.py": (
        "the one burn row the pool walk consumes by key; it moves with the "
        "periodic family's row keys",
        frozenset({"Liandry's Torment"}),
    ),
    "fight/rotation/mana_declarations.py": (
        "the restore rule the resource walk names its refusals by; it moves "
        "with the resource-ledger declarations",
        frozenset({"Lost Chapter"}),
    ),
    "fight/rotation/mana_walk.py": (
        "the same two restore rules, plus their receipt labels; one slice "
        "with the module above",
        frozenset({"Catalyst of Aeons", "Essence Reaver", "Lost Chapter"}),
    ),
}


def _literal_item_names(path: Path, names: frozenset[str]) -> set[str]:
    """Every cached item name this module spells outside a docstring."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, DOCSTRING_SCOPES)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    return {
        name
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
        for name in names
        if name in node.value
    }


def registry_readers() -> list[str]:
    """Every engine step that spells the registry dictionary's name."""
    return [
        f"{path.name} reads {REGISTRY}"
        for path in FIGHT_ENGINE_PATHS
        if REGISTRY in path.read_text(encoding="utf-8")
    ]


def name_comparisons() -> list[str]:
    """Every engine step that compares a value against a cached item name."""
    names = frozenset(_REFERENCE_ITEM_EFFECTS)
    found = []
    for path in FIGHT_ENGINE_PATHS:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Compare):
                continue
            found.extend(
                f"{path.name}:{node.lineno} dispatches on {value.value!r}"
                for value in (node.left, *node.comparators)
                if isinstance(value, ast.Constant) and value.value in names
            )
    return found


def spelled_names() -> dict[str, set[str]]:
    """Each engine step that spells a cached item name, and which ones."""
    names = frozenset(_REFERENCE_ITEM_EFFECTS)
    return {
        path.relative_to(SRC_ROOT).as_posix(): spelled
        for path in FIGHT_ENGINE_PATHS
        if (spelled := _literal_item_names(path, names))
    }


def frontier_drift() -> list[str]:
    """Where the tree and the declared frontier disagree, in both directions."""
    found = spelled_names()
    declared = {
        module: set(spelled)
        for module, (_, spelled) in ITEM_NAME_LITERAL_FRONTIER.items()
    }
    return [
        f"{module}: spells {sorted(found.get(module, set()))}, "
        f"frontier says {sorted(declared.get(module, set()))}"
        for module in sorted(set(found) | set(declared))
        if found.get(module, set()) != declared.get(module, set())
    ]


def check() -> list[str]:
    """Every finding across the three rules."""
    return [*registry_readers(), *name_comparisons(), *frontier_drift()]


if __name__ == "__main__":
    raise SystemExit(
        report(check(), "OK: item identity stops at the fight engine's door")
    )
