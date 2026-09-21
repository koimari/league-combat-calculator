#!/usr/bin/env python3
"""Python prose lint over ``src/`` and ``scripts/``: docstrings and comments hold current state.

This reads ``.py`` files only.  Markdown is the plugin hook
``comment_lint.lint_prose``, which the stop gate runs over every changed ``.md``
file; the two share no code and no findings.

``tests/test_prose_lint.py`` pins six findings at zero: a function docstring
longer than the body it documents, a comment run longer than the function it
belongs to, prose about what the code was rather than what it is, a section
banner with no statement under it, which is what an extraction leaves when it
cuts the bodies out and not the headers, a module docstring under
``CHAMPIONS_SCOPE`` over ``MODULE_DOCSTRING_CAP`` lines, and an assumption
string there over ``ASSUMPTION_CAP`` characters.  A champion header holds what a
reader of the module needs today, so a trap belongs in ``TRAPS.md``, a review
stamp in that module's ``SOURCES``, and a project id nowhere.  ``/api/config``
and ``/api/not-modeled`` publish the assumption strings, so one holds the
number, the condition and the source and nothing else; a second fact is a
second string.

Assumption text reaches those endpoints through four module-level doors: a name
ending in ``assumptions``, ``extend`` or ``append`` on one, ``+=``, and a call's
assumption keyword.  An element no literal answers for is reported rather than
read past, and the cached text ``static/reviewed-packets.json`` carries into
every packet module is out of an AST's reach.

A seventh, ``pointer``, names prose citing a campaign document where the reason
itself belongs.  It reports rather than failing, under a ceiling the test holds
and that may only fall; moving it into ``FAILING`` is one edit once the ceiling
reaches zero.  Prose citing a wiki URL or a game file for a number is evidence,
and is never reported.

An eighth, ``unsourced_constant``, reports a module-level numeric literal under
``CHAMPIONS_SCOPE`` whose provenance nothing states: a citation, a cached field
name or a composition, either trailing the line or heading the unbroken run of
assignments it sits in.  It reports under its own ceiling for the same reason.

A comment run belongs to the function holding it, or — when it touches a ``def``
— to the definition it introduces.  Inside a body the bound is the body; above
the ``def`` it is the whole definition, header and docstring included, so moving
a paragraph out of a docstring buys it headroom and never exemption.  A run a
blank line away from the ``def`` heads a section, not a definition, and is
bounded by nothing.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import tokenize
from collections.abc import Iterable, Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGETS = ("src", "scripts")
CHAMPIONS_SCOPE = "src/calculator/champions/"
MODULE_DOCSTRING_CAP = 20
ASSUMPTION_CAP = 120
FAILING = (
    "long_docstring",
    "long_comment",
    "history",
    "dead_banner",
    "long_module_docstring",
    "long_assumption",
)
REPORTING = ("pointer", "unsourced_constant")
SCOPES = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef)

EVIDENCE = re.compile(
    r"https?://|wiki|\.bin\.json|CommunityDragon|game file|\batoms?\b|binar",
    re.IGNORECASE,
)
HISTORY = re.compile(
    r"\bretired\b|\bused to\b|\bpreviously\b|\b(?-i:legacy)\b|\bno longer\b"
    r"|\b(?:issue|PR) #\d+"
    r"|\b(?<!\{)(?=[0-9a-f]*[a-f])(?=[0-9a-f]*\d)(?:[0-9a-f]{7,8}|[0-9a-f]{40})\b",
    re.IGNORECASE,
)
POINTER = re.compile(
    r"\bAmendment\b|\bRuling\b|\bD-\d{2,3}\b|\bPhase \d|\bwave \d|\bslice\b|\bcampaign\b",
    re.IGNORECASE,
)
BANNER = re.compile(r"^# -{5,}$")
# Where a number comes from: a citation, a cached field name or a quoted cached
# phrase, or a composition of two numbers.
PROVENANCE = re.compile(
    r"https?://|wiki|\.bin\.json|CommunityDragon|game file|\batoms?\b|binar"
    r"|HARDCODED|SOURCES|\bsourced?\b|\bcach|data/|JSON"
    r"|(?-i:[a-z]+[A-Z][a-zA-Z]*)|\"[^\"]+\""
    r"|\d.*[-+*/×]\s*\d",
    re.IGNORECASE,
)


def _span(nodes: list[ast.stmt]) -> int:
    return nodes[-1].end_lineno - nodes[0].lineno + 1 if nodes else 0


def _docstring(node: ast.AST) -> ast.Constant | None:
    body = node.body if isinstance(node, SCOPES) else []
    head = body[0].value if body and isinstance(body[0], ast.Expr) else None
    return (
        head if isinstance(head, ast.Constant) and isinstance(head.value, str) else None
    )


def _comment_blocks(source: str) -> list[tuple[int, list[str]]]:
    """Runs of consecutive comment-only lines, as (first line, comments)."""
    blocks: list[tuple[int, list[str]]] = []
    lines = iter(source.splitlines(keepends=True))
    for tok in tokenize.generate_tokens(lambda: next(lines, "")):
        if tok.type != tokenize.COMMENT or not tok.line.lstrip().startswith("#"):
            continue
        if blocks and blocks[-1][0] + len(blocks[-1][1]) == tok.start[0]:
            blocks[-1][1].append(tok.string)
        else:
            blocks.append((tok.start[0], [tok.string]))
    return blocks


def _trailing_comments(source: str) -> dict[int, str]:
    """Comments that follow code on their line, by line number."""
    lines = iter(source.splitlines(keepends=True))
    return {
        tok.start[0]: tok.string
        for tok in tokenize.generate_tokens(lambda: next(lines, ""))
        if tok.type == tokenize.COMMENT and not tok.line.lstrip().startswith("#")
    }


def _is_number(node: ast.expr) -> bool:
    """Whether this is a numeric literal, sign included."""
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        return _is_number(node.operand)
    value = node.value if isinstance(node, ast.Constant) else None
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _assignment_runs(tree: ast.Module) -> dict[int, int]:
    """Each module-level assignment's line to the first line of its unbroken run.

    A run is what one comment over it documents, so the note heading a block of
    constants answers for every constant in the block.
    """
    heads: dict[int, int] = {}
    previous: ast.stmt | None = None
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            previous = None
            continue
        abuts = previous is not None and previous.end_lineno + 1 == node.lineno
        heads[node.lineno] = heads[previous.lineno] if abuts else node.lineno
        previous = node
    return heads


def _unsourced_constants(
    source: str, tree: ast.Module, blocks: Iterable[tuple[int, list[str]]], where: str
) -> list[str]:
    """Module-level numbers whose provenance no comment beside them states."""
    trailing = _trailing_comments(source)
    over = {line + len(block): " ".join(block) for line, block in blocks}
    runs = _assignment_runs(tree)
    lines = source.splitlines()
    found = []
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
            continue
        if not _is_number(node.value):
            continue
        notes = (trailing.get(node.lineno, ""), over.get(runs[node.lineno], ""))
        if not any(PROVENANCE.search(note) for note in notes):
            found.append(f"{where}:{node.lineno}: {lines[node.lineno - 1].strip()}")
    return found


def _publishes_assumptions(name: str) -> bool:
    """Whether this name holds assumption text, whatever its prefix."""
    return name.lower().endswith("assumptions")


def _assumption_values(tree: ast.Module) -> Iterable[ast.expr]:
    """Every module-level expression an assumptions name receives."""
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            bound = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = (n for t in bound for n in ast.walk(t) if isinstance(n, ast.Name))
            if node.value is not None and any(
                map(_publishes_assumptions, (n.id for n in names))
            ):
                yield node.value
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            func = node.value.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr in ("append", "extend")
                and isinstance(func.value, ast.Name)
                and _publishes_assumptions(func.value.id)
            ):
                yield from node.value.args


def _assumption_elements(value: ast.expr) -> Iterable[ast.expr]:
    """Every element one such expression contributes, as authored.

    A name that publishes assumptions is read at its own binding, and the
    cached packet text a call resolves at import is out of an AST's reach,
    so a call contributes its assumption keywords alone.  Anything else is
    yielded unresolved, because the cap cannot be read off it.
    """
    if isinstance(value, ast.Starred):
        yield from _assumption_elements(value.value)
    elif isinstance(value, (ast.List, ast.Tuple, ast.Set)):
        for element in value.elts:
            if isinstance(element, ast.Starred):
                yield from _assumption_elements(element)
            else:
                yield element
    elif isinstance(value, ast.BinOp) and isinstance(value.op, ast.Add):
        yield from _assumption_elements(value.left)
        yield from _assumption_elements(value.right)
    elif isinstance(value, ast.Call):
        if isinstance(value.func, ast.Name) and value.func.id in ("list", "tuple"):
            yield from (e for arg in value.args for e in _assumption_elements(arg))
        else:
            yield from (
                e
                for word in value.keywords
                if word.arg and "assumption" in word.arg
                for e in _assumption_elements(word.value)
            )
    elif not (isinstance(value, ast.Name) and _publishes_assumptions(value.id)):
        yield value


def _long_assumptions(tree: ast.Module, where: str) -> list[str]:
    """Every published assumption element the cap does not hold, with why."""
    found = []
    for value in _assumption_values(tree):
        for element in _assumption_elements(value):
            text = element.value if isinstance(element, ast.Constant) else None
            if not isinstance(text, str):
                found.append(f"{where}:{element.lineno}: {ast.unparse(element)[:60]}")
            elif len(text) > ASSUMPTION_CAP:
                found.append(
                    f"{where}:{element.lineno}: "
                    f"{len(text)} characters over {ASSUMPTION_CAP}"
                )
    return found


def _overlong_module_docstring(tree: ast.Module, where: str) -> list[str]:
    """This module's header if it runs past the cap, as a one-item list."""
    doc = _docstring(tree)
    lines = 0 if doc is None else doc.end_lineno - doc.lineno + 1
    if lines <= MODULE_DOCSTRING_CAP:
        return []
    return [f"{where}:{doc.lineno}: {lines} lines over {MODULE_DOCSTRING_CAP}"]


def _definition_spans(funcs: list[ast.stmt]) -> dict[int, int]:
    """First line of each definition (decorators included) to its line count."""
    heads = {}
    for func in funcs:
        head = (func.decorator_list or [func])[0].lineno
        heads[head] = func.end_lineno - head + 1
    return heads


def _comment_bound(
    line: int, block: list[str], funcs: list[ast.stmt], heads: Mapping[int, int]
) -> int | None:
    """How many lines this run may hold, or ``None`` if it heads a section."""
    holders = [f for f in funcs if f.lineno <= line <= f.end_lineno]
    if holders:
        return _span(min(holders, key=lambda f: f.end_lineno - f.lineno).body)
    return heads.get(line + len(block))


def _dead_banners(
    blocks: Iterable[tuple[int, list[str]]], tree: ast.Module
) -> list[int]:
    """The first line of every section banner with no statement beneath it.

    A banner runs to the next banner, so its section is empty when no top-level
    statement starts in between.
    """
    starts = [node.lineno for node in tree.body]
    banners = [
        (line, line + len(block) - 1)
        for line, block in blocks
        if BANNER.match(block[0].strip()) and BANNER.match(block[-1].strip())
    ]
    return [
        line
        for index, (line, end) in enumerate(banners)
        if not any(
            end
            < start
            < (banners[index + 1][0] if index + 1 < len(banners) else 1 << 30)
            for start in starts
        )
    ]


def _cite(found: Mapping[str, list], where: str, line: int, text: str) -> None:
    for offset, raw in enumerate(text.splitlines()):
        if EVIDENCE.search(raw):
            continue
        for kind, pattern in (("history", HISTORY), ("pointer", POINTER)):
            if pattern.search(raw):
                found[kind].append(f"{where}:{line + offset}: {raw.strip()[:100]}")
                break


def scan(root: Path = ROOT, exclude: tuple[str, ...] = ()) -> dict[str, list[str]]:
    """Report every finding over every ``.py`` file under ``TARGETS``."""
    found: dict[str, list[str]] = {key: [] for key in (*FAILING, *REPORTING)}
    paths = (
        p for t in TARGETS for p in (root / t).rglob("*.py") if p.name not in exclude
    )
    for path in sorted(paths, key=lambda p: p.as_posix()):
        where = path.relative_to(root).as_posix()
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            doc = _docstring(node)
            if doc is None:
                continue
            _cite(found, where, doc.lineno, doc.value)
            body = _span(node.body[1:]) or 1  # a stub's docstring is its body
            if isinstance(node, FUNCS) and doc.end_lineno - doc.lineno + 1 > body:
                found["long_docstring"].append(f"{where}:{doc.lineno}: {node.name}")
        funcs = [n for n in ast.walk(tree) if isinstance(n, FUNCS)]
        heads = _definition_spans(funcs)
        blocks = _comment_blocks(source)
        for line, block in blocks:
            _cite(found, where, line, "\n".join(block))
            bound = _comment_bound(line, block, funcs, heads)
            if bound is not None and len(block) > bound:
                found["long_comment"].append(f"{where}:{line}: {len(block)} lines")
        for line in _dead_banners(blocks, tree):
            found["dead_banner"].append(f"{where}:{line}: banner over nothing")
        if where.startswith(CHAMPIONS_SCOPE):
            found["unsourced_constant"] += _unsourced_constants(
                source, tree, blocks, where
            )
            found["long_module_docstring"] += _overlong_module_docstring(tree, where)
            found["long_assumption"] += _long_assumptions(tree, where)
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--exclude", nargs="*", default=[], help="file names to skip")
    parser.add_argument("--json", action="store_true", help="emit findings as JSON")
    args = parser.parse_args()
    found = scan(exclude=tuple(args.exclude))
    if args.json:
        print(json.dumps(found, indent=2))
    else:
        print("\n".join(f"{k}: {h}" for k, hits in found.items() for h in hits))
    print(" ".join(f"{k}={len(h)}" for k, h in found.items()), file=sys.stderr)
    return 1 if any(found[kind] for kind in FAILING) else 0


if __name__ == "__main__":
    sys.exit(main())
