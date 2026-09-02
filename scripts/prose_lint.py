#!/usr/bin/env python3
"""Prose lint over ``src/`` and ``scripts/``: docstrings and comments hold current state.

``tests/test_prose_lint.py`` pins three findings at zero: a function docstring
longer than the body it documents, a comment run longer than the function it
belongs to, and prose about what the code was rather than what it is.  A fourth,
``pointer``, names prose citing a campaign document where the reason itself
belongs; it reports without failing.  Prose citing a wiki URL or a game file for
a number is evidence, and is never reported.

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
from collections.abc import Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGETS = ("src", "scripts")
FAILING = ("long_docstring", "long_comment", "history")
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


def _cite(found: Mapping[str, list], where: str, line: int, text: str) -> None:
    for offset, raw in enumerate(text.splitlines()):
        if EVIDENCE.search(raw):
            continue
        for kind, pattern in (("history", HISTORY), ("pointer", POINTER)):
            if pattern.search(raw):
                found[kind].append(f"{where}:{line + offset}: {raw.strip()[:100]}")
                break


def scan(root: Path = ROOT, exclude: tuple[str, ...] = ()) -> dict[str, list[str]]:
    """Report the four findings over every ``.py`` file under ``TARGETS``."""
    found: dict[str, list[str]] = {k: [] for k in (*FAILING, "pointer")}
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
        for line, block in _comment_blocks(source):
            _cite(found, where, line, "\n".join(block))
            bound = _comment_bound(line, block, funcs, heads)
            if bound is not None and len(block) > bound:
                found["long_comment"].append(f"{where}:{line}: {len(block)} lines")
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
