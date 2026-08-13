"""Phase 4's structural gates: one constructor, one direction, one budget.

Three properties this phase claims about the *tree* rather than about any
one module, each asserted here because none of them belongs to a module's
own front door:

* **One constructor** (criterion 2).  Every ``SurvivalAction(...)``
  expression in ``src/`` is in ``program/compile.py``, bar the one declared
  survivor, and the retired builder names have zero occurrences.
* **One direction.**  ``program -> survival`` and never back, so the kernel
  keeps a hot loop that cannot dispatch on a logical type.
* **One allocation budget** (R-28, criterion 17).  S4 is the single stage
  the campaign gates allocation at, and the margin is read from
  ``campaign-fingerprints.json`` rather than from prose.

The counters themselves live in ``scripts/migration_frontier.py`` and their
receipt is diff-gated by ``tests/test_migration_frontier.py``; what is here
is the phase's own reading of them, which is the reading a criterion is
discharged against.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SRC = ROOT / "src" / "calculator"
SURVIVAL = SRC / "survival"
PROGRAM = SRC / "program"
FINGERPRINTS = ROOT / "docs" / "receipts" / "campaign-fingerprints.json"

# Where the one constructor lives, and the one expression allowed outside it.
CONSTRUCTOR_HOME = "calculator/program/compile.py"
DECLARED_SURVIVOR = "calculator/survival/actions.py"

# The names the move retired.  Pinned as absences over the source text,
# because a retired builder does its remaining damage as prose: a comment
# describing a second constructor reads as a second constructor.
RETIRED_BUILDERS = ("survival_action_from_event",)


def _repo_path(path: Path) -> str:
    """One spelling for a scanned file: repo-relative, posix, ``src/`` off."""
    return path.relative_to(ROOT / "src").as_posix()


def _construction_sites(callee: str) -> dict[str, int]:
    """Every call expression under ``src/calculator`` spelling *callee*."""
    tally: dict[str, int] = {}
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        count = sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == callee
        )
        if count:
            tally[_repo_path(path)] = count
    return tally


class TestOneConstructor:
    """Criterion 2, read off the tree rather than off the frontier receipt."""

    def test_every_construction_expression_is_in_the_one_home(self) -> None:
        """Expressions, not text: ``grep`` also matches the class and a docstring."""
        sites = _construction_sites("SurvivalAction")
        outside = {
            path: count for path, count in sites.items() if path != CONSTRUCTOR_HOME
        }
        assert outside == {DECLARED_SURVIVOR: 1}

    def test_the_survivor_is_the_fast_constructors_default_row(self) -> None:
        """Criteria 2 and 17 are mutually exclusive without this one line."""
        text = (SURVIVAL / "actions.py").read_text(encoding="utf-8")
        assert "_ACTION_DEFAULT_ROW = list(SurvivalAction())" in text

    def test_the_home_actually_constructs(self) -> None:
        """A home with no expressions in it would pass the test above vacuously."""
        assert _construction_sites("SurvivalAction")[CONSTRUCTOR_HOME] > 1

    def test_the_retired_builder_names_have_zero_occurrences(self) -> None:
        holders = {
            _repo_path(path): name
            for path in sorted(SRC.rglob("*.py"))
            for name in RETIRED_BUILDERS
            if name in path.read_text(encoding="utf-8")
        }
        assert holders == {}


class TestOneDirection:
    """``program -> survival``, and the kernel never reaches back."""

    def test_no_kernel_module_imports_the_logical_layer(self) -> None:
        offenders: list[tuple[str, str]] = []
        for path in sorted(SURVIVAL.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and "program" in (
                    node.module or ""
                ):
                    offenders.append((_repo_path(path), node.module or ""))
                if isinstance(node, ast.Import):
                    offenders.extend(
                        (_repo_path(path), alias.name)
                        for alias in node.names
                        if "program" in alias.name
                    )
        assert offenders == []

    def test_the_walk_authored_builder_arrives_as_a_parameter(self) -> None:
        """The device that keeps the direction one-way where the walk needs it.

        ``ReceiptLedger`` authors a recovery packet mid-walk and therefore
        needs the constructor it may not import.  It takes it as a required,
        defaultless argument, so a caller that forgot it fails loudly rather
        than scheduling nothing and looking like a fight in which no trigger
        authored a heal.
        """
        import inspect

        from src.calculator.survival.receipt_state import ReceiptLedger

        parameter = inspect.signature(ReceiptLedger).parameters["compile_event"]
        assert parameter.default is inspect.Parameter.empty
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY

    def test_the_logical_layer_does_reach_the_kernel(self) -> None:
        """The other half: a direction with no edge in it is not a direction."""
        text = (PROGRAM / "compile.py").read_text(encoding="utf-8")
        assert "from ..survival.actions import" in text


class TestTheAllocationBudget:
    """R-28's one allocation gate, at the one stage that declares it."""

    def test_the_probe_stays_within_its_declared_margin(self) -> None:
        """Criterion 17, read from the receipt and never from prose.

        S4 trades per-fight dict churn for cached frozen records, which is
        why the campaign gates allocation here and nowhere else.  If this
        cannot hold, the declared fallback is to keep ``compiled_damage_action``
        as the compiler's inner loop and treat the program as a build-time
        artifact -- never to widen the margin.
        """
        from scripts.bench_coupled_optimizer import allocation_probe

        recorded = json.loads(FINGERPRINTS.read_text(encoding="utf-8"))["alloc"][
            "cassiopeia_3champ"
        ]
        ceiling = recorded["peak_bytes"] * (1 + recorded["margin"])
        assert allocation_probe("cassiopeia_3champ") <= ceiling

    def test_the_margin_is_the_one_the_receipt_declares(self) -> None:
        """A gate whose threshold this file could choose is not a gate."""
        recorded = json.loads(FINGERPRINTS.read_text(encoding="utf-8"))["alloc"][
            "cassiopeia_3champ"
        ]
        assert recorded["margin"] == 0.15
        assert recorded["provenance"] == "VERIFIED"
