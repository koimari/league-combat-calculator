"""Rule-5 lint: literal defaults standing in for a cached-data read.

Flags ``x.get("key", <literal>)``, ``<expr> or <literal>`` and
``getattr(o, "attr", <literal>)``.  Two shapes are exempt by shape, not by a
list, because neither reads a named field of cached data:

* ``x.get(<computed key>, <identity element>)`` — an index into a local
  accumulator, where absence is the normal state.  ``ability_damages`` is
  carved out: its keys are champion slots and its home is ``ability_atoms``.
* ``<expr> or <literal>`` where ``<expr>`` is not itself a ``.get()`` — a
  None-coalesce on an Optional value, not a default for missing data.

    python scripts/literal_defaults.py src/calculator/damage.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Iterable, Iterator, NamedTuple

_EMPTY_FACTORIES = frozenset({"dict", "list", "set", "tuple", "frozenset"})
# The one receiver whose computed keys are still cached data: champion slots.
_PAYLOAD_RECEIVERS = frozenset({"ability_damages"})


class Finding(NamedTuple):
    """One flagged site: where it is, what it reads, what it falls back to."""

    path: str
    line: int
    kind: str
    key: str
    default: str
    expression: str
    enclosing: str


def _is_literal(node: ast.AST) -> bool:
    """True for a value baked into the source rather than read from data."""
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.UnaryOp):
        return _is_literal(node.operand)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set, ast.Dict)):
        return all(map(_is_literal, _children(node)))
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in _EMPTY_FACTORIES
        and not node.args
        and not node.keywords
    )


def _children(node: ast.AST) -> list[ast.expr]:
    """The value sub-expressions of a container literal."""
    return [kid for kid in ast.iter_child_nodes(node) if isinstance(kid, ast.expr)]


def _identity_element(node: ast.AST) -> bool:
    """True for the zero of a type: a number, a bool, or an empty container."""
    if isinstance(node, ast.Constant):
        return not isinstance(node.value, str)
    return not _children(node)


def _text(node: ast.AST, source: str) -> str:
    """The source of one node, whitespace-collapsed onto a single line."""
    segment = ast.get_source_segment(source, node)
    return " ".join((segment if segment is not None else ast.unparse(node)).split())


def _is_get_call(node: ast.AST) -> bool:
    """True for any ``<expr>.get(...)`` call."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
    )


def _receiver_name(func: ast.Attribute) -> str:
    """The last name component of a ``.get()`` receiver path."""
    value = func.value
    if isinstance(value, ast.Attribute):
        return value.attr
    return value.id if isinstance(value, ast.Name) else ""


def _enclosing(tree: ast.AST) -> dict[int, str]:
    """Source line to innermost enclosing function or class name."""
    scope: dict[int, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for line in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                scope[line] = node.name
    return scope


def _flagged(node: ast.AST) -> tuple[str, ast.AST | None, ast.AST] | None:
    """The (kind, key, default) this node reads behind a literal fallback."""
    if _is_get_call(node) and len(node.args) == 2 and not node.keywords:
        key, default = node.args
        named = isinstance(key, ast.Constant) and isinstance(key.value, str)
        indexing = (
            not named
            and _identity_element(default)
            and _receiver_name(node.func) not in _PAYLOAD_RECEIVERS
        )
        return (
            ("dict.get", key, default)
            if _is_literal(default) and not indexing
            else None
        )
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        if (
            node.func.id == "getattr"
            and len(node.args) == 3
            and not node.keywords
            and _is_literal(node.args[2])
        ):
            return "getattr", node.args[1], node.args[2]
    if (
        isinstance(node, ast.BoolOp)
        and isinstance(node.op, ast.Or)
        and _is_literal(node.values[-1])
        and _is_get_call(node.values[-2])
    ):
        return "or-default", None, node.values[-1]
    return None


def scan(paths: Iterable[Path]) -> list[Finding]:
    """Every flagged site in the given files, in source order."""
    findings: list[Finding] = []
    for path in paths:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        scope = _enclosing(tree)
        for node in ast.walk(tree):
            flagged = _flagged(node)
            if flagged is None:
                continue
            kind, key, default = flagged
            findings.append(
                Finding(
                    str(path),
                    node.lineno,
                    kind,
                    _text(key, source) if key is not None else "",
                    _text(default, source),
                    _text(node, source),
                    scope.get(node.lineno, "<module>"),
                )
            )
    return sorted(findings, key=lambda f: (f.path, f.line, f.expression))


def targets(raw_paths: Iterable[str]) -> Iterator[Path]:
    """Expand file and directory arguments to Python files."""
    for raw in raw_paths:
        path = Path(raw)
        yield from sorted(path.rglob("*.py")) if path.is_dir() else iter((path,))


if __name__ == "__main__":
    _FOUND = scan(targets(sys.argv[1:]))
    for _row in _FOUND:
        print(f"{_row.path}:{_row.line} [{_row.kind}] {_row.expression}")
    print(f"total {len(_FOUND)}", file=sys.stderr)
    raise SystemExit(1 if _FOUND else 0)
