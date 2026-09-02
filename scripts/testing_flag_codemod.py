#!/usr/bin/env python3
"""Retire per-test ``app.config["TESTING"] = True`` in favour of the session flag.

``tests/conftest.py`` borrows ``TESTING=True`` for the whole session, so every
per-test assignment of it is dead. This deletes those lines, and only those:
the value must be the literal ``True``, the statement must be the whole line,
and the file has to still parse and still hold at least one statement in every
block the line was part of. Anything else is reported and left alone.

Byte-preserving: lines are split on ``\\n`` and rejoined, so a CRLF checkout
comes back CRLF (a ``sed -i`` here would flatten the tree).

    python scripts/testing_flag_codemod.py tests/        # report
    python scripts/testing_flag_codemod.py tests/ --write
"""

from __future__ import annotations

import argparse
import ast
import re
from collections.abc import Sequence
from pathlib import Path

ASSIGNMENT = re.compile(r"^(\s*)[\w.]*\bconfig\[[\"']TESTING[\"']\]\s*=\s*True\s*$")


def removable(source: str) -> tuple[list[int], list[int]]:
    """``(deletable line numbers, refused line numbers)``, both 1-based.

    A line is refused when deleting it would empty a block — the assignment
    is the only statement under a ``with``, ``if`` or ``def`` — because the
    replacement for that shape is a judgement call and not a deletion.
    """
    lines = source.split("\n")
    deletable, refused = [], []
    for number, line in enumerate(lines, start=1):
        match = ASSIGNMENT.match(line)
        if match is None:
            continue
        (deletable if _has_a_sibling(lines, number, match) else refused).append(number)
    return deletable, refused


def _has_a_sibling(lines: Sequence[str], number: int, match: re.Match) -> bool:
    """Whether another statement shares this line's block."""
    indent = len(match.group(1))
    for offset in (-1, 1):
        cursor = number + offset
        while 1 <= cursor <= len(lines):
            text = lines[cursor - 1]
            stripped = text.strip()
            if stripped and not stripped.startswith("#"):
                width = len(text) - len(text.lstrip())
                if width < indent:
                    break
                if width == indent:
                    return True
            cursor += offset
    return False


def rewrite(source: str, deletable: list[int]) -> str:
    """*source* without the given line numbers, keeping its line endings."""
    dropped = set(deletable)
    lines = source.split("\n")
    return "\n".join(
        line for number, line in enumerate(lines, start=1) if number not in dropped
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--write", action="store_true", help="apply the deletions")
    args = parser.parse_args()

    removed = 0
    for root in args.paths:
        for path in sorted(root.rglob("*.py") if root.is_dir() else [root]):
            source = path.read_text(encoding="utf-8", newline="")
            deletable, refused = removable(source)
            for number in refused:
                print(f"{path}:{number}: refused — sole statement of its block")
            if not deletable:
                continue
            rewritten = rewrite(source, deletable)
            ast.parse(rewritten.replace("\r\n", "\n"), filename=str(path))
            print(f"{path}: {len(deletable)} assignment(s)")
            removed += len(deletable)
            if args.write:
                path.write_text(rewritten, encoding="utf-8", newline="")
    print(f"total {removed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
