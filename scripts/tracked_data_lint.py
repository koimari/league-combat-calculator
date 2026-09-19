#!/usr/bin/env python3
"""Lint over tracked data: every receipt has a reader, no path names a machine.

``orphan`` covers the JSON under ``docs/receipts/`` and ``data/atoms/``.  Each
file must be named by a regenerator or read by a test, and the reader set is
derived rather than listed: every string literal outside a docstring in
``src/``, ``scripts/`` and ``tests/``, matched against the file's name whole or
as a family glob.  A corpus nothing names cannot be dated, regenerated, or
trusted, which is how 139 oracle receipts stayed tracked while 2 were read.
A glob names a family only when it pins something past the suffix
(``oracle-C6-*.json``); ``*`` and ``*.json`` match every receipt there is, so
counting either as a reader would answer for the whole corpus and leave the
rule reporting nothing, whatever the tree held.

``machine_path`` covers every tracked JSON file.  A string that starts a
Windows drive or a ``/Users`` or ``/home`` home directory is one machine's
scratch path, and a receipt carrying one reproduces nowhere else.

Markdown under those roots is prose and answers to ``prose_lint.py``.  Both
rules read ``git ls-files``, so an untracked scratch file a test writes mid-run
is out of scope and cannot race the gate.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from collections.abc import Iterable, Iterator
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath
from typing import NamedTuple

ROOT = Path(__file__).resolve().parent.parent
RECEIPT_ROOTS = ("docs/receipts", "data/atoms")
READER_ROOTS = ("src", "scripts", "tests")
MACHINE_PATH = re.compile(r"^[A-Za-z]:[\\/]|^/(?:Users|home)/")
RULES = ("orphan", "machine_path")


def tracked(root: Path, *paths: str) -> tuple[Path, ...]:
    """Every file ``git ls-files`` reports under ``paths``, as absolute paths."""
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--", *paths],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return tuple(root / name for name in listed.split("\0") if name)


def _docstring_ids(tree: ast.Module) -> frozenset[int]:
    """The id of every string node that is a docstring or a bare statement."""
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            ids.add(id(node.value))
    return frozenset(ids)


def read_literals(paths: Iterable[Path]) -> frozenset[str]:
    """Every non-docstring string literal in the given Python sources."""
    literals: set[str] = set()
    for path in paths:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        skip = _docstring_ids(tree)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in skip
            ):
                literals.add(node.value)
    return frozenset(literals)


def _segment(text: str) -> str:
    """The last path segment, which is what a file name is matched against."""
    return text.rsplit("/", 1)[-1]


def names_a_family(pattern: str) -> bool:
    """Whether a glob names a family of files rather than scanning a directory."""
    segment = _segment(pattern)
    pinned = segment.replace("*", "").replace("?", "")
    return bool(pinned) and pinned != PurePosixPath(segment).suffix


class Readers(NamedTuple):
    """Every spelling the tree's Python sources use to name a file."""

    literals: frozenset[str]
    families: frozenset[str]

    @classmethod
    def in_tree(cls, root: Path = ROOT) -> Readers:
        """The reader set of a checkout, derived from its tracked sources."""
        sources = [
            path for path in tracked(root, *READER_ROOTS) if path.suffix == ".py"
        ]
        literals = read_literals(sources)
        globs = (text for text in literals if "*" in text or "?" in text)
        return cls(literals, frozenset(filter(names_a_family, globs)))

    def name(self, relative: str) -> bool:
        """Whether a reader names this repo-relative path, exactly or by family."""
        leaf = _segment(relative)
        return (
            relative in self.literals
            or leaf in self.literals
            or any(fnmatch(leaf, _segment(pattern)) for pattern in self.families)
        )


def orphans(root: Path = ROOT) -> tuple[str, ...]:
    """Receipt files no reader in the tree names, directly or by family."""
    readers = Readers.in_tree(root)
    receipts = (
        path.relative_to(root).as_posix()
        for path in tracked(root, *RECEIPT_ROOTS)
        if path.suffix == ".json"
    )
    return tuple(sorted(name for name in receipts if not readers.name(name)))


def _strings(payload: object) -> Iterator[str]:
    """Every string in a decoded JSON document, keys included."""
    if isinstance(payload, str):
        yield payload
    elif isinstance(payload, dict):
        for key, value in payload.items():
            yield key
            yield from _strings(value)
    elif isinstance(payload, list):
        for value in payload:
            yield from _strings(value)


def machine_paths(root: Path = ROOT) -> tuple[str, ...]:
    """Every tracked JSON string that starts an absolute path on one machine."""
    found: list[str] = []
    for path in tracked(root):
        if path.suffix != ".json":
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        relative = path.relative_to(root).as_posix()
        found.extend(
            f"{relative}: {text[:80]}"
            for text in _strings(payload)
            if MACHINE_PATH.search(text)
        )
    return tuple(sorted(found))


def scan(root: Path = ROOT) -> dict[str, tuple[str, ...]]:
    """Both rules, keyed by name, each holding the findings it owns."""
    return {"orphan": orphans(root), "machine_path": machine_paths(root)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="emit findings as JSON")
    args = parser.parse_args(argv)
    found = scan()
    if args.json:
        print(json.dumps({rule: list(hits) for rule, hits in found.items()}, indent=2))
    else:
        for rule in RULES:
            for hit in found[rule]:
                print(f"{rule}: {hit}")
    print(" ".join(f"{rule}={len(found[rule])}" for rule in RULES), file=sys.stderr)
    return 1 if any(found[rule] for rule in RULES) else 0


if __name__ == "__main__":
    sys.exit(main())
