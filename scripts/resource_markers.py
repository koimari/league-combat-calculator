"""Every test that needs a local resource carries the marker for it.

A test whose evidence is a locally-built game file, or a browser probe that
shells out to `node`, cannot run on a machine that has neither.  Answering
that with `pytest.skip` takes the green path and reports success for work
that did not happen, so `tests/conftest.py` deselects the node instead and
its terminal summary names what was not run.

Deselection happens at collection, so it needs a marker rather than a guard
inside the body.  This finds the tests that need one: a test is guarded when
its own body, or any module-level helper it calls, reaches a `pytest.skip`
whose reason names one of the resources below.

    python scripts/resource_markers.py

`tests/test_resource_markers.py` is the gate.
"""

from __future__ import annotations

import ast
import sys
from collections.abc import Iterator
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lint_report import report

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"

#: Each resource, the marker that names it, and the skip reasons that mean
#: "this machine does not have it".  A reason outside this table is a skip
#: about something else and is not this rule's business.
RESOURCES = {
    "needs_game_files": (
        "game-file evidence is unavailable",
        "gitignored local game-file cache",
    ),
    "needs_node": ("node is not installed",),
}


def _skip_reason(node: ast.AST) -> str | None:
    """The first argument of a ``pytest.skip(...)`` call, as source text."""
    if not (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "skip"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "pytest"
        and node.args
    ):
        return None
    return ast.unparse(node.args[0])


def _called_names(body: ast.AST) -> set[str]:
    """Every bare or attribute name this definition calls."""
    names = set()
    for node in ast.walk(body):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
    return names


def _definitions(tree: ast.AST) -> Iterator[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Every function and method in the module."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def _is_fixture(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Whether one definition is decorated as a pytest fixture."""
    for decorator in node.decorator_list:
        call = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(call, ast.Attribute) and call.attr == "fixture":
            return True
    return False


def _argument_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Every positional parameter name, which is how a fixture is requested."""
    return {argument.arg for argument in node.args.args}


def guarded_tests(path: Path) -> dict[str, str]:
    """Each test in one module that reaches a resource guard, and its marker.

    A definition reaches a guard through a call or through a fixture it
    requests, so a requested fixture name is an edge like a call is.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    fixtures = {node.name for node in _definitions(tree) if _is_fixture(node)}
    marker_of: dict[str, str] = {}
    calls: dict[str, set[str]] = {}
    for node in _definitions(tree):
        calls[node.name] = _called_names(node) | (_argument_names(node) & fixtures)
        for child in ast.walk(node):
            reason = _skip_reason(child)
            if reason is None:
                continue
            for marker, phrases in RESOURCES.items():
                if any(phrase in reason for phrase in phrases):
                    marker_of[node.name] = marker
    changed = True
    while changed:
        changed = False
        for name, targets in calls.items():
            reached = {marker_of[target] for target in targets if target in marker_of}
            if reached and name not in marker_of:
                marker_of[name] = sorted(reached)[0]
                changed = True
    return {
        name: marker for name, marker in marker_of.items() if name.startswith("test_")
    }


def declared_markers(path: Path) -> dict[str, set[str]]:
    """Each test in one module and the resource markers it declares."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    declared: dict[str, set[str]] = {}
    for node in _definitions(tree):
        if not node.name.startswith("test_"):
            continue
        declared[node.name] = {
            decorator.attr
            for decorator in node.decorator_list
            if isinstance(decorator, ast.Attribute) and decorator.attr in RESOURCES
        }
    return declared


def check(root: Path = TESTS) -> list[str]:
    """Every guarded test whose marker is missing or wrong."""
    findings = []
    for path in sorted(root.glob("test_*.py")):
        needed = guarded_tests(path)
        if not needed:
            continue
        declared = declared_markers(path)
        findings.extend(
            f"{path.name}::{name} reaches a {marker.removeprefix('needs_')} "
            f"guard and carries no @pytest.mark.{marker}"
            for name, marker in sorted(needed.items())
            if marker not in declared.get(name, set())
        )
    return findings


if __name__ == "__main__":
    raise SystemExit(report(check(), "OK: every guarded test names its resource"))
