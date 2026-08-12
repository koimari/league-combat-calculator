"""Phase 0's deletion frontier — each absence asserted, not remembered.

Dead code is deleted once and grows back for free.  Every name Phase 0
removes is pinned here as an absence over the source tree, so a later
slice that re-adds one fails on this file instead of on a reviewer
noticing.  The list is closed: nothing else in ``src/`` is removed by
Phase 0, and this module asserts only what its own commits deleted.
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


def _holders(name: str) -> list[str]:
    """Every file under src/ whose text still contains ``name``."""
    return [
        path.relative_to(ROOT).as_posix()
        for path in sorted(SRC.rglob("*.py"))
        if name in path.read_text(encoding="utf-8")
    ]


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


# --- D-10: the second dispatch ladder and its two exports -------------------


def test_the_dead_transition_entry_point_is_gone_from_the_source() -> None:
    """``apply_transition`` had zero callers and is not a name any more."""
    assert _holders("apply_transition") == []


def test_the_survival_package_no_longer_exports_it() -> None:
    """Both exports go with the function: the package API and the module's."""
    from src.calculator import survival
    from src.calculator.survival import transitions

    assert "apply_transition" not in survival.__all__
    assert "apply_transition" not in transitions.__all__
    assert not hasattr(survival, "apply_transition")
    assert not hasattr(transitions, "apply_transition")


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


# --- D-09: the write-only utility state -------------------------------------


def test_the_write_only_utility_state_is_gone_from_the_source() -> None:
    """A field, its vocabulary and the state nobody ever read.

    ``utility_kind`` could only ever be ``""``: it was set by testing an
    ``ActionKind`` member for membership in a ``frozenset[str]``, and
    ``ActionKind`` is not a string enum, so the comparison was permanently
    false.  The ledger entry it fed was appended and never read back.
    """
    assert _holders("utility_kind") == []
    assert _holders("_UTILITY_KINDS") == []
    assert _holders("utility_effects") == []


def test_the_survival_action_carries_no_utility_kind() -> None:
    """The field is gone from the typed interface, not merely unset."""
    from src.calculator.survival.actions import SurvivalAction

    assert "utility_kind" not in SurvivalAction._fields


# --- The unused import ------------------------------------------------------


def test_the_timeline_imports_no_catalyst_predicate() -> None:
    """The alias was imported and never called.

    Phase 0 deleted the unused alias; 3.9 then retired the predicate itself,
    because "does this build hold Catalyst" was the item-name spelling of
    "does this build declare a mana-spent heal".  Both spellings are asserted
    absent here, so neither can come back as the other.
    """
    from src.calculator import roster_composition

    assert _holders("_has_catalyst") == []
    assert not hasattr(roster_composition, "has_catalyst")
    assert callable(roster_composition.mana_spent_heal_slot)


# --- The last item name the survival kernel spelled --------------------------


def test_the_receipt_state_names_no_item() -> None:
    """3.9: the walk's state builder reads a declaration, not an item name.

    ``receipt_state`` armed the below-half healing bonus behind
    ``item.get("name") == "Immortal Path"`` and read the number back through
    ``sustain_effect_value`` — the last two name-dispatch sites in the
    survival kernel outside the compiled-walk gate the flip rewrites.  Both
    the item name and the registry accessor are asserted absent, and the
    state key that spelled the item is asserted renamed, so the read cannot
    come back under any of its three old spellings.
    """
    text = (SURVIVAL / "receipt_state.py").read_text(encoding="utf-8")
    assert "Immortal Path" not in text
    assert "sustain_effect_value" not in text
    assert "immortal_path_below_half_healing_multiplier" not in "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(SRC.rglob("*.py"))
    )
