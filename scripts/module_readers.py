"""Repointing a reader of the split module at the new home of each name it reads."""

from __future__ import annotations

import ast
import re
from collections.abc import Collection, Iterator, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from scripts.module_units import (
    DEFINITIONS,
    _piece,
    bound_alias,
    import_sort_key,
    import_statement,
    merge_imports,
    read_lines,
    read_parts,
    relative_import,
)

if TYPE_CHECKING:
    from scripts.extract_modules import Plan

READER_ROOTS = ("src", "tests", "scripts")

#: ``from . import X`` names the source nowhere in its own text.
BARE_RELATIVE = re.compile(r"^\s*from \.+ import", re.MULTILINE)


class Edit(NamedTuple):
    """A replacement over one span, in line numbers and utf-8 column offsets."""

    line: int
    col: int
    end_line: int
    end_col: int
    text: str


class ImportScope(NamedTuple):
    """One import statement and the definition whose body it binds names in."""

    node: ast.stmt
    scope: ast.AST


class Reader(NamedTuple):
    """One file being repointed, against the plan that says where each name went."""

    plan: Plan
    pkg: tuple[str, ...]
    tree: ast.Module
    lines: list[str]


def reader_files(plan: Plan, repo: Path) -> list[Path]:
    """Every repo-relative reader file that is not itself part of the move."""
    skip = {plan.source.path.as_posix()} | {module.key for module in plan.modules}
    found = (
        p.relative_to(repo)
        for r in READER_ROOTS
        for p in sorted((repo / r).rglob("*.py"))
    )
    return [p for p in found if p.as_posix() not in skip and ".claude" not in p.parts]


def slice_span(lines: Sequence[str], edit: Edit) -> str:
    """The text one edit replaces."""
    head = lines[edit.line - 1].encode("utf-8")[edit.col :]
    if edit.line == edit.end_line:
        return head[: edit.end_col - edit.col].decode("utf-8")
    tail = lines[edit.end_line - 1].encode("utf-8")[: edit.end_col].decode("utf-8")
    return "\n".join(
        [head.decode("utf-8"), *lines[edit.line : edit.end_line - 1], tail]
    )


def apply_edits(lines: list[str], edits: list[Edit]) -> list[str]:
    """Apply replacements back to front so earlier spans keep their positions."""
    out = list(lines)
    for edit in sorted(edits, key=lambda e: (e.line, e.col), reverse=True):
        head = out[edit.line - 1].encode("utf-8")[: edit.col].decode("utf-8")
        tail = out[edit.end_line - 1].encode("utf-8")[edit.end_col :].decode("utf-8")
        out[edit.line - 1 : edit.end_line] = (head + edit.text + tail).split("\n")
    return out


def source_aliases(
    tree: ast.Module, pkg: tuple[str, ...], target: str
) -> tuple[set[str], bool]:
    """Names bound to the source module here, and whether one came in relative."""
    aliases: set[str] = set()
    levels: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            aliases.update(
                a.asname for a in node.names if a.name == target and a.asname
            )
        elif isinstance(node, ast.ImportFrom):
            package = ".".join(read_parts(node, pkg))
            hits = [a for a in node.names if f"{package}.{a.name}" == target]
            aliases.update(a.asname or a.name for a in hits)
            levels += [node.level] * len(hits)
    return aliases, any(levels)


def regroup_import(node: ast.ImportFrom, reader: Reader, line: str) -> Edit:
    """Split one ``from <source> import ...`` across the homes its names moved to."""
    plan = reader.plan
    stay = plan.source.parts
    by_home: dict[tuple[str, ...], list[ast.alias]] = {}
    for alias in node.names:
        home = plan.home[alias.name].parts if alias.name in plan.moved else stay
        by_home.setdefault(home, []).append(alias)
    statements = [
        relative_import(home, reader.pkg, _piece(group), relative=node.level > 0)
        for home, group in by_home.items()
    ]
    text = ("\n" + " " * node.col_offset).join(sorted(statements, key=import_sort_key))
    end = node.end_lineno or node.lineno
    return Edit(node.lineno, node.col_offset, end, len(line.encode("utf-8")), text)


def string_edits(reader: Reader) -> Iterator[Edit]:
    """Repoint each string whose whole value is a moved name's dotted path."""
    plan = reader.plan
    for node in ast.walk(reader.tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        name = node.value.removeprefix(f"{plan.source.dotted}.")
        span = Edit(
            node.lineno, node.col_offset, node.end_lineno, node.end_col_offset, ""
        )
        literal = slice_span(reader.lines, span)
        if name != node.value and name in plan.moved and literal[:1] in "\"'":
            home = ".".join(plan.home[name].parts)
            yield span._replace(text=literal.replace(node.value, f"{home}.{name}"))


def import_edits(reader: Reader) -> Iterator[Edit]:
    """Repoint each ``from <source> import ...`` that names a moved unit."""
    plan = reader.plan
    for node in ast.walk(reader.tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if ".".join(read_parts(node, reader.pkg)) != plan.source.dotted:
            continue
        if any(alias.name in plan.moved for alias in node.names):
            end = node.end_lineno or node.lineno
            yield regroup_import(node, reader, reader.lines[end - 1])


def quoted_attributes(
    node: ast.Constant, aliases: Collection[str]
) -> list[ast.Attribute]:
    """Every ``<alias>.<name>`` the expression this string spells reads."""
    if not any(alias in node.value for alias in aliases):
        return []
    try:
        inner = ast.parse(node.value, mode="eval").body
    except SyntaxError:
        return []
    return [
        sub
        for sub in ast.walk(inner)
        if isinstance(sub, ast.Attribute)
        and isinstance(sub.value, ast.Name)
        and sub.value.id in aliases
    ]


def quoted_edits(reader: Reader) -> Iterator[tuple[Edit, tuple[str, ...]]]:
    """Repoint each ``"damage.X"`` a quoted annotation spells, with its imports.

    Python never evaluates one, so no ``ast.Name`` carries the read and the
    plain alias pass cannot see it.
    """
    plan, pkg = reader.plan, reader.pkg
    aliases, is_relative = source_aliases(reader.tree, pkg, plan.source.dotted)
    for node in ast.walk(reader.tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        moved = [a for a in quoted_attributes(node, aliases) if a.attr in plan.moved]
        if not moved:
            continue
        span = Edit(
            node.lineno, node.col_offset, node.end_lineno, node.end_col_offset, ""
        )
        text, needed = slice_span(reader.lines, span), []
        for sub in moved:
            home = plan.home[sub.attr]
            text = text.replace(
                f"{sub.value.id}.{sub.attr}", f"{home.path.stem}.{sub.attr}"
            )
            needed.append(
                relative_import(home.pkg, pkg, home.path.stem, relative=is_relative)
            )
        yield span._replace(text=text), tuple(needed)


def alias_edits(reader: Reader) -> Iterator[tuple[Edit, str]]:
    """Repoint each ``damage.X`` read, with the import its new module needs."""
    plan, pkg = reader.plan, reader.pkg
    aliases, is_relative = source_aliases(reader.tree, pkg, plan.source.dotted)
    for node in ast.walk(reader.tree):
        if not (isinstance(node, ast.Attribute) and node.attr in plan.moved):
            continue
        if not (isinstance(node.value, ast.Name) and node.value.id in aliases):
            continue
        home, value = plan.home[node.attr], node.value
        stem = home.path.stem
        span = (value.lineno, value.col_offset, value.end_lineno, value.end_col_offset)
        yield Edit(*span, stem), relative_import(
            home.pkg, pkg, stem, relative=is_relative
        )


def scoped_imports(
    scope: ast.AST, body: ast.AST | None = None
) -> Iterator[ImportScope]:
    """Each import with the definition whose body its names are bound in."""
    for child in ast.iter_child_nodes(body if body is not None else scope):
        if isinstance(child, (ast.Import, ast.ImportFrom)):
            yield ImportScope(child, scope)
        elif isinstance(child, DEFINITIONS):
            yield from scoped_imports(child)
        else:
            yield from scoped_imports(scope, child)


def _live_aliases(
    scope: ast.AST,
    aliases: set[str],
    repointed: Collection[tuple[int, int]],
    moved: Collection[str],
) -> set[str]:
    """The aliases still read inside one scope, a quoted annotation counted."""
    read = {
        node.id
        for node in ast.walk(scope)
        if isinstance(node, ast.Name)
        and node.id in aliases
        and (node.lineno, node.col_offset) not in repointed
    }
    return read | {
        sub.value.id
        for node in ast.walk(scope)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        for sub in quoted_attributes(node, aliases)
        if sub.attr not in moved
    }


def stale_alias_edits(
    reader: Reader, *, repointed: Collection[tuple[int, int]]
) -> Iterator[Edit]:
    """Drop an import of the source module no read is left for.

    A name is still read where the repointing did not take it, so an alias a
    ``monkeypatch.setattr(damage, ...)`` names keeps its import.  Liveness is
    per scope, because a deferred import inside one function goes stale while
    the module-level one a sibling function reads does not, and an import the
    reader has already marked ``noqa`` is there for its side effect.
    """
    tree, lines = reader.tree, reader.lines
    aliases, _ = source_aliases(tree, reader.pkg, reader.plan.source.dotted)
    for node, scope in scoped_imports(tree):
        live = _live_aliases(scope, aliases, repointed, reader.plan.moved)
        read = [a for a in node.names if bound_alias(a) not in aliases - live]
        end = node.end_lineno or node.lineno
        suppressed = any("# noqa" in line for line in lines[node.lineno - 1 : end])
        if len(read) == len(node.names) or suppressed:
            continue
        width = len(lines[end - 1].encode("utf-8"))
        if read:
            statement = import_statement(node, read)
            yield Edit(node.lineno, node.col_offset, end, width, statement)
        else:
            above = len(lines[node.lineno - 2].encode("utf-8"))
            yield Edit(node.lineno - 1, above, end, width, "")


def rewrite_reader(relative: Path, plan: Plan, repo: Path) -> list[str]:
    """Repoint one file's reads of moved names, writing it under ``--write``."""
    lines, newline = read_lines(repo / relative)
    text = newline.join(lines)
    if plan.source.stem not in text and not BARE_RELATIVE.search(text):
        return []
    reader = Reader(plan, relative.parent.parts, ast.parse(text), lines)
    aliased = list(alias_edits(reader))
    quoted = list(quoted_edits(reader))
    repointed = {(edit.line, edit.col) for edit, _ in aliased}
    edits = [
        *import_edits(reader),
        *(edit for edit, _ in aliased),
        *(edit for edit, _ in quoted),
        *string_edits(reader),
        *stale_alias_edits(reader, repointed=repointed),
    ]
    needed = {statement for _, statement in aliased}
    needed |= {statement for _, group in quoted for statement in group}
    if not edits:
        return []
    merged = merge_imports(sorted(needed, key=lambda s: (*import_sort_key(s), s)))
    by_anchor: dict[int, list[str]] = {}
    for statement in sorted(merged, key=import_sort_key):
        if statement not in text:
            line = _import_anchor(reader.tree, statement)
            by_anchor.setdefault(line, []).append(statement)
    edits += [
        Edit(line, 0, line, 0, "".join(s + "\n" for s in group))
        for line, group in by_anchor.items()
    ]
    report = [
        f"{e.line}  {slice_span(lines, e)!r} -> {e.text!r}"
        for e in sorted(edits, key=lambda e: (e.line, e.col))
    ]
    if plan.write:
        (repo / relative).write_bytes(
            newline.join(apply_edits(lines, edits)).encode("utf-8")
        )
    return report


def _import_anchor(tree: ast.Module, statement: str) -> int:
    """The line a new top-level import goes on: the one isort sorts it in front of."""
    key = import_sort_key(statement)
    line = 1
    for node in tree.body:
        if isinstance(node, ast.Expr) and line == 1:
            line = (node.end_lineno or node.lineno) + 1
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            if import_sort_key(import_statement(node, node.names)) > key:
                return node.lineno
            line = (node.end_lineno or node.lineno) + 1
    return line
