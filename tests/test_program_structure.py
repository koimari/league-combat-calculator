"""Phase 4's structural gates: one constructor, one direction, one budget.

Four properties this phase claims about the *tree* rather than about any
one module, each asserted here because none of them belongs to a module's
own front door:

* **One constructor** (criterion 2).  Every ``SurvivalAction(...)``
  expression in ``src/`` is in ``program/compile.py``, bar the one declared
  survivor.
* **One direction.**  ``program -> survival`` and never back, so the kernel
  keeps a hot loop that cannot dispatch on a logical type.
* **One allocation budget** (R-28, criterion 17).  S4 is the single stage
  the campaign gates allocation at, and the margin is read from
  ``campaign-fingerprints.json`` rather than from prose.
* **View purity** (criterion 3).  No view, and no ``src/`` function a view
  can call, performs arithmetic.  The resolver and its counting rule are
  ``tests/view_purity.py``; the reading is here.
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


def _repo_path(path: Path) -> str:
    """One spelling for a scanned file: repo-relative, posix, ``src/`` off."""
    return path.relative_to(ROOT / "src").as_posix()


def _called_name(node: ast.Call) -> str:
    """What one call expression spells, bare name or dotted attribute alike.

    Both spellings, because a gate that counted only ``f(...)`` is silent on
    the one rewrite that would defeat it: ``import transitions`` and call
    ``transitions.f(...)``.  The counting rule is stated here so the number
    a criterion is read against is reproducible (R-29).
    """
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def _construction_sites(callee: str) -> dict[str, int]:
    """Every call expression under ``src/calculator`` spelling *callee*."""
    tally: dict[str, int] = {}
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        count = sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and _called_name(node) == callee
        )
        if count:
            tally[_repo_path(path)] = count
    return tally


class TestOneWalkCallSite:
    """Criterion 1's first clause, as a gate rather than as a measurement.

    "Exactly one ``run_survival_walk(`` call site in ``src/``, inside
    ``program/walk.py`` (baseline two)" was true at the end of S10 and
    nothing in the tree said so: a second composition that entered the
    kernel directly would have landed fully green.  The runtime counter
    (``walk_invocations``) does not cover it either — it counts entries
    through :func:`program.walk.walk`, and a caller that skipped the seam
    would increment nothing at all.

    The dispatch-ladder gate in ``tests/test_deletion_frontier`` is a
    different property: one *definition*, in the module that owns the
    kernel.  One definition with two callers is exactly the arrangement
    this campaign exists to end.
    """

    WALK_HOME = "calculator/program/walk.py"

    def test_the_kernel_has_exactly_one_caller_and_it_is_the_seam(self) -> None:
        assert _construction_sites("run_survival_walk") == {self.WALK_HOME: 1}


class TestOneConstructor:
    """Criterion 2, read off the tree rather than off the frontier receipt."""

    def test_every_construction_expression_is_in_the_one_home(self) -> None:
        """Expressions, not text: ``grep`` also matches the class and a docstring."""
        sites = _construction_sites("SurvivalAction")
        outside = {
            path: count for path, count in sites.items() if path != CONSTRUCTOR_HOME
        }
        assert outside == {DECLARED_SURVIVOR: 1}

    def test_the_home_actually_constructs(self) -> None:
        """A home with no expressions in it would pass the test above vacuously."""
        assert _construction_sites("SurvivalAction")[CONSTRUCTOR_HOME] > 1


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


class TestViewPurity:
    """Criterion 3's first clause: a view re-runs no arithmetic.

    The check is deliberately not path-scoped -- the criterion says "nor any
    ``src/`` function in a view's call graph", because a purity rule that
    only walked ``program/views/`` is satisfied by moving the sum one import
    away and calling it.  The counting rule, the resolver and its committed
    boundary live in ``tests/view_purity.py``; what is here is the phase's
    reading of them.
    """

    def test_no_view_nor_anything_it_calls_performs_arithmetic(self) -> None:
        from tests.view_purity import impurities, report

        sites = impurities()
        assert not sites, "arithmetic reachable from a view:\n" + report(sites)

    def test_the_walk_reaches_the_writer_the_registry_and_all_five_views(
        self,
    ) -> None:
        """A purity check over an empty call graph is not a check."""
        from tests.view_purity import call_graph

        reachable, _ = call_graph()
        assert {
            ("program.views", "serialize_leaf"),
            ("program.views", "measured"),
            ("program.precision", "round_field"),
            ("program.views.score", "score"),
            ("program.views.breakdown", "breakdown"),
            ("program.views.survival", "survival"),
            ("program.views.tdd", "tdd"),
            ("program.views.receipt", "receipt"),
        } <= set(reachable)

    def test_the_callees_the_walk_stops_at_are_the_committed_list(self) -> None:
        """The boundary is enumerated, not whatever the resolver happened to miss."""
        from tests.view_purity import UNRESOLVED_ALLOWED, call_graph

        _, unresolved = call_graph()
        assert unresolved == set(UNRESOLVED_ALLOWED)

    def test_a_sum_inside_a_view_fails_the_check(self) -> None:
        """R-05: the gate ships with a red it can reproduce on demand."""
        from tests.view_purity import impurities

        doctored = (SRC / "program" / "views" / "tdd.py").read_text(encoding="utf-8")
        doctored = doctored.replace(
            "    fold = result.objective",
            "    fold = result.objective\n    _leaked = 1.0 + float(result.duration)",
        )
        sites = impurities({"program.views.tdd": doctored})
        assert [site.what for site in sites] == ["Add"]
        assert sites[0].module == "program.views.tdd"

    def test_a_sum_one_import_away_from_a_view_fails_it_too(self) -> None:
        """The clause the path-scoped version of this check cannot see."""
        from tests.view_purity import impurities

        doctored = (SRC / "program" / "precision.py").read_text(encoding="utf-8")
        doctored = doctored.replace(
            "def round_field(",
            "def _view_math(a, b):\n    return a * b\n\n\ndef round_field(",
        )
        assert not impurities(
            {"program.precision": doctored}
        ), "an unreachable helper is not in the call graph"
        doctored = doctored.replace(
            "    return round(float(value), digits_for(field))",
            "    return round(_view_math(float(value), 1.0), digits_for(field))",
        )
        sites = impurities({"program.precision": doctored})
        assert [(site.module, site.what) for site in sites] == [
            ("program.precision", "Mult")
        ]


class TestEveryViewTakesTheWalkAndNothingElse:
    """Criterion 3's second clause: a view's inputs are exactly two.

    The five front doors have taken ``(program, result)`` since S9, but the
    parameters were annotated ``Any`` and no test read them, so "exactly
    ``Program`` and ``WalkResult``" was a claim three docstrings made about
    themselves.  A view that quietly grew a third parameter -- the roster,
    the request, a cache -- would be reading a number that reached it by
    some route no counter can trace to this walk, which is the whole reason
    the clause is in the criterion.
    """

    #: The five views, by the dotted path a reader would import.
    FRONT_DOORS = (
        "program.views.score:score",
        "program.views.breakdown:breakdown",
        "program.views.survival:survival",
        "program.views.tdd:tdd",
        "program.views.receipt:receipt",
    )

    @staticmethod
    def _front_door(spec: str):
        """One view function, imported the way its consumer imports it."""
        import importlib

        module, name = spec.split(":")
        path = f"src.calculator.{module}"
        imported = importlib.import_module(path)  # sightline-ok: 24 dotted spec
        return getattr(imported, name)  # sightline-ok: 24 dotted spec

    def test_each_view_takes_a_program_and_a_walk_result_and_no_third_thing(
        self,
    ) -> None:
        import inspect
        import typing

        from src.calculator.program.build import Program
        from src.calculator.program.walk import WalkResult

        for spec in self.FRONT_DOORS:
            view = self._front_door(spec)
            parameters = list(inspect.signature(view).parameters.values())
            assert [p.name for p in parameters] == ["program", "result"], spec
            assert all(
                p.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD for p in parameters
            ), spec
            hints = typing.get_type_hints(view)
            assert hints["program"] is Program, spec
            assert hints["result"] is WalkResult, spec

    def test_the_annotations_are_resolvable_and_not_strings(self) -> None:
        """``Any`` passed the old reading of this clause; so would a typo."""
        import typing

        for spec in self.FRONT_DOORS:
            hints = typing.get_type_hints(self._front_door(spec))
            assert typing.Any not in hints.values(), spec
