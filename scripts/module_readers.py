"""Repointing a reader of the split module at the new home of each name it reads."""

from __future__ import annotations

import ast
from collections.abc import Collection, Iterator, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from scripts.module_units import (
    _piece,
    bound_alias,
    import_sort_key,
    import_statement,
    read_lines,
    read_parts,
    relative_import,
)

if TYPE_CHECKING:
    from scripts.extract_modules import Plan

READER_ROOTS = ("src", "tests", "scripts")


class Edit(NamedTuple):
    """A replacement over one span, in line numbers and utf-8 column offsets."""

    line: int
    col: int
    end_line: int
    end_col: int
    text: str


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
    stay = plan.source.path.with_suffix("").parts
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


def stale_alias_edits(
    reader: Reader, *, repointed: Collection[tuple[int, int]]
) -> Iterator[Edit]:
    """Drop an import of the source module no read is left for.

    A name is still read where the repointing did not take it, so an alias a
    ``monkeypatch.setattr(damage, ...)`` names keeps its import.
    """
    tree, lines = reader.tree, reader.lines
    aliases, _ = source_aliases(tree, reader.pkg, reader.plan.source.dotted)
    live = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
        and node.id in aliases
        and (node.lineno, node.col_offset) not in repointed
    }
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        read = [a for a in node.names if bound_alias(a) not in aliases - live]
        if len(read) == len(node.names):
            continue
        end = node.end_lineno or node.lineno
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
    if plan.source.path.stem not in text:
        return []
    reader = Reader(plan, relative.parent.parts, ast.parse(text), lines)
    aliased = list(alias_edits(reader))
    repointed = {(edit.line, edit.col) for edit, _ in aliased}
    edits = [
        *import_edits(reader),
        *(edit for edit, _ in aliased),
        *string_edits(reader),
        *stale_alias_edits(reader, repointed=repointed),
    ]
    needed = {statement for _, statement in aliased}
    if not edits:
        return []
    anchor = _import_anchor(reader.tree)
    edits += [
        Edit(anchor, 0, anchor, 0, s + "\n") for s in sorted(needed) if s not in text
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


def _import_anchor(tree: ast.Module) -> int:
    """The line a new top-level import goes on: after the last one already there."""
    line = 1
    for node in tree.body:
        leading_docstring = isinstance(node, ast.Expr) and line == 1
        if isinstance(node, (ast.Import, ast.ImportFrom)) or leading_docstring:
            line = (node.end_lineno or node.lineno) + 1
    return line
