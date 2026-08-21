"""One mechanic, one route, one vocabulary — the survival kernel's shape.

D-10 and D-09 each deleted a second answer to a question the kernel already
answered: a second ``ActionKind`` dispatch ladder, and a module-private copy
of the utility vocabulary.  What is asserted here is the shape those
deletions left, not the names they removed.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).parents[1]
SRC = ROOT / "src"
SURVIVAL = SRC / "calculator" / "survival"

# A dispatch ladder is a function whose control flow routes an action by its
# kind, and the reproducible spelling of that is: three or more ``if`` tests
# whose condition names ``ActionKind`` directly or names a module-level set
# built out of ``ActionKind`` members (so ``if kind in _DAMAGE_KINDS`` counts
# too, and a ladder cannot hide behind a constant).  Two is not enough: a
# two-branch special case is a guard, not a router.
LADDER_BRANCH_THRESHOLD = 3


def _action_kind_sets(tree: ast.Module) -> set[str]:
    """Module-level names bound to a collection of ``ActionKind`` members."""
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and "'ActionKind'" in ast.dump(node.value):
            names.update(
                target.id for target in node.targets if isinstance(target, ast.Name)
            )
    return names


def _dispatch_ladders(path: Path) -> dict[str, int]:
    """Function name -> kind-testing branch count, for the ladders in one file."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    kind_sets = _action_kind_sets(tree)
    ladders: dict[str, int] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        branches = 0
        for sub in ast.walk(node):
            if not isinstance(sub, ast.If):
                continue
            test = ast.dump(sub.test)
            if "'ActionKind'" in test or any(
                f"id='{name}'" in test for name in kind_sets
            ):
                branches += 1
        if branches >= LADDER_BRANCH_THRESHOLD:
            ladders[node.name] = branches
    return ladders


def test_exactly_one_dispatch_ladder_survives_in_the_kernel() -> None:
    """One mechanic, one route: the walk loop is the only router left.

    Two ladders over one ``ActionKind`` vocabulary is two places a mechanic
    can be handled differently, which is the drift D-10 deletes.
    """
    ladders = {
        path.name: _dispatch_ladders(path) for path in sorted(SURVIVAL.glob("*.py"))
    }
    found = {
        f"{filename}:{function}"
        for filename, functions in ladders.items()
        for function in functions
    }
    assert found == {"transitions.py:run_survival_walk"}


def test_the_survival_action_carries_a_read_utility_kind() -> None:
    """The field is on the typed interface *and* the walk dispatches on it.

    A field with no reader is the D-09 defect; the cleanse self-cast is what
    makes this one not one, so the dispatch is driven rather than grepped.
    """
    from src.calculator.survival.actions import UTILITY_KINDS, SurvivalAction

    assert "utility_kind" in SurvivalAction._fields
    assert "cleanse" in UTILITY_KINDS


def test_the_utility_vocabulary_has_exactly_one_home() -> None:
    """D-09's real subject: the set of kinds is declared once, not per module."""
    declarers = [
        path
        for path in sorted(SRC.rglob("*.py"))
        if "UTILITY_KINDS = " in path.read_text(encoding="utf-8")
    ]
    assert [path.name for path in declarers] == ["actions.py"]
