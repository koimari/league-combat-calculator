"""The vocabulary a module split is cut with: units, free names and import spelling."""

from __future__ import annotations

import ast
import builtins
import symtable
import sys
from collections.abc import Iterable, Iterator
from contextlib import suppress
from itertools import groupby
from pathlib import Path
from typing import NamedTuple

BUILTIN_NAMES = frozenset(dir(builtins)) | {"__file__", "__name__", "__doc__"}
DEFINITIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
MOVABLE = (*DEFINITIONS, ast.Assign, ast.AnnAssign)
_STDLIB = set(sys.stdlib_module_names)


class Unit(NamedTuple):
    """One movable top-level statement and the source span that carries it."""

    names: tuple[str, ...]
    start: int
    end: int
    node: ast.stmt


def relative_head(from_parts: tuple[str, ...], pkg: tuple[str, ...]) -> str:
    """The ``from <dots><module> import`` one package reads another by."""
    common = 0
    while common < min(len(from_parts), len(pkg)) and from_parts[common] == pkg[common]:
        common += 1
    return f"from {'.' * (len(pkg) - common + 1)}{'.'.join(from_parts[common:])} import"


def relative_import(
    from_parts: tuple[str, ...],
    pkg: tuple[str, ...],
    piece: str,
    *,
    relative: bool = True,
) -> str:
    """Spell an import of ``piece`` out of ``from_parts`` as read from ``pkg``."""
    if not relative:
        return f"from {'.'.join(from_parts)} import {piece}"
    return f"{relative_head(from_parts, pkg)} {piece}"


def read_parts(node: ast.ImportFrom, pkg: tuple[str, ...]) -> tuple[str, ...]:
    """The package parts an ``ImportFrom`` reads, its relative level resolved."""
    if node.level == 0:
        return tuple((node.module or "").split("."))
    base = pkg[: len(pkg) - node.level + 1]
    return base + tuple(node.module.split(".")) if node.module else base


def bound_names(node: ast.stmt) -> tuple[str, ...]:
    """The module-level names one statement binds."""
    if isinstance(node, DEFINITIONS):
        return (node.name,)
    if isinstance(node, ast.AnnAssign):
        targets: list[ast.expr] = [node.target]
    else:
        targets = getattr(node, "targets", [])
    return tuple(n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name))


def bound_alias(alias: ast.alias) -> str:
    """The name one imported alias binds."""
    return alias.asname or alias.name.split(".")[0]


def is_future_import(node: ast.stmt) -> bool:
    """Whether one statement is a ``from __future__`` directive, never a read."""
    return isinstance(node, ast.ImportFrom) and node.module == "__future__"


def _annotation_parts(node: ast.AST) -> Iterable[ast.AST]:
    """The parts of one annotation node that can name something.

    A ``Literal``'s constant members are the values it admits, not names.
    """
    if not isinstance(node, ast.Subscript):
        return ast.iter_child_nodes(node)
    head = node.value
    if (getattr(head, "attr", None) or getattr(head, "id", None)) != "Literal":
        return ast.iter_child_nodes(node)
    members = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
    return [head, *(m for m in members if not isinstance(m, ast.Constant))]


def _read_names(node: ast.AST) -> Iterator[str]:
    """Names one annotation reads, a quoted part parsed as the expression it spells."""
    if isinstance(node, ast.Name):
        yield node.id
    elif isinstance(node, ast.Constant) and isinstance(node.value, str):
        with suppress(SyntaxError):
            yield from _read_names(ast.parse(node.value, mode="eval").body)
    else:
        for part in _annotation_parts(node):
            yield from _read_names(part)


def _type_parameters(node: ast.stmt) -> set[str]:
    """The names a ``def`` or ``class`` binds by declaring them (PEP 695)."""
    return {p.name for sub in ast.walk(node) for p in getattr(sub, "type_params", ())}


def _annotation_names(node: ast.stmt) -> Iterator[str]:
    """Names an annotation reads, whether it is spelled or quoted.

    A local variable's annotation is never evaluated, so symtable cannot see it.
    """
    for sub in ast.walk(node):
        annotation = getattr(sub, "annotation", None) or getattr(sub, "returns", None)
        if annotation:
            yield from _read_names(annotation)


def free_names(node: ast.stmt) -> set[str]:
    """Names a statement reads and does not bind, builtins excluded.

    Wrapping it in a function makes a symbol table answer with real scoping:
    comprehensions, f-strings and class bodies included, locals excluded.
    """
    holder = ast.parse("def _unit():\n    pass").body[0]
    holder.body = [node]
    module = ast.fix_missing_locations(ast.Module(body=[holder], type_ignores=[]))
    top = symtable.symtable(ast.unparse(module), "<unit>", "exec")
    tables = list(top.get_children())
    reads: set[str] = set()
    while tables:
        table = tables.pop()
        reads.update(s.get_name() for s in table.get_symbols() if s.is_global())
        tables.extend(table.get_children())
    bound = BUILTIN_NAMES | _type_parameters(node)
    return (reads | set(_annotation_names(node))) - bound


def import_sort_key(statement: str) -> tuple[int, int, str]:
    """Rank an import the way ruff's isort rule orders one."""
    module = statement.split()[1]
    head = module.split(".")[0]
    section = 1 if head in _STDLIB else 3
    section = 4 if module.startswith(".") else 0 if head == "__future__" else section
    return (section, int(statement.startswith("from ")), module.lower())


def import_sections(statements: Iterable[str]) -> list[str]:
    """One block per isort section, in order; a blank line separates them."""
    ordered = sorted(statements, key=import_sort_key)
    grouped = groupby(ordered, key=lambda statement: import_sort_key(statement)[0])
    return ["\n".join(section) for _, section in grouped]


def member_key(piece: str) -> tuple[int, str, str]:
    """Rank one imported name the way ruff's isort orders members: constants,
    then classes, then the rest, each case blind."""
    name = piece.partition(" as ")[0]
    kind = 0 if len(name) > 1 and name.isupper() else 1 if name[:1].isupper() else 2
    return (kind, name.lower(), name)


def merge_imports(statements: Iterable[str]) -> list[str]:
    """Combine two ``from`` imports of one module into one, the way isort does."""
    merged: dict[str, list[str]] = {}
    for statement in statements:
        head, _, piece = statement.partition(" import ")
        merged.setdefault(head, []).append(piece)
    return [
        (
            head
            if not pieces[0]
            else f"{head} import {', '.join(sorted(set(pieces), key=member_key))}"
        )
        for head, pieces in merged.items()
    ]


def read_lines(path: Path) -> tuple[list[str], str]:
    """A file's lines without terminators, and the newline it is written with."""
    raw = path.read_bytes()
    newline = "\r\n" if b"\r\n" in raw else "\n"
    return raw.decode("utf-8").split(newline), newline


def _piece(aliases: list[ast.alias]) -> str:
    return ", ".join(a.name + (f" as {a.asname}" if a.asname else "") for a in aliases)


def import_statement(node: ast.stmt, aliases: list[ast.alias]) -> str:
    """One import statement re-spelled over the aliases it still carries."""
    if isinstance(node, ast.Import):
        return f"import {_piece(aliases)}"
    return f"from {'.' * node.level}{node.module or ''} import {_piece(aliases)}"
