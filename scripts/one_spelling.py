#!/usr/bin/env python3
"""One concept, one spelling, over ``src/`` and ``scripts/``.

A refusal is a rule answering with a named reason instead of a number, and
``src/calculator/quantity.py`` owns both kinds it comes in: ``withheld`` and
``starved``, with ``refusal`` / ``refused`` for either.  This gate fails on a
second spelling of that fact, and on three other concepts whose minority
spelling was the same kind of drift.

Words this gate does **not** ban, because each names something a refusal is
not, and each already has one spelling and one owner: ``blocked`` /
``blocking`` is crowd control (``control_spec`` owns the vocabulary),
``excluded`` is set membership, ``skipped`` and ``omitted`` are schedule
outcomes, ``rejected`` is request validation, ``suppressed`` is an inference a
declaration overrides, and ``denied`` is a fight rule saying no to a gain, a
cast or an application, which is published as ``item_denial`` and disclosed
with a number rather than withheld.  Nothing lexical separates those senses
from a refusal, so a reader is the check there and this gate is not.

``RESPELLED`` words have no other sense anywhere, so they are read out of the
whole file.  ``NAME_ONLY`` words are spelled by a published wire value, so a
string may hold one and a defined name may not.  ``ALLOWED`` carries every name
that keeps a banned word, with the reason; ``tests/test_one_spelling.py`` fails
on an entry whose site the tree does not define, so the list only shrinks.
"""

from __future__ import annotations

import argparse
import ast
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGETS = ("src", "scripts")
SELF = "scripts/one_spelling.py"

#: A word with no other sense in this tree, and the spelling that replaces it.
RESPELLED: Mapping[str, str] = {
    "declin": "refuse / refusal / withheld",
    "catalogue": "catalog",
    "wearer": "holder",
}

#: A word a published wire value spells, so only a defined name is banned.
NAME_ONLY: Mapping[str, str] = {
    "unavailab": "withheld / refusal",
    "teammate": "ally",
}

#: Every defined name that keeps a banned word, and what makes it the name.
ALLOWED: Mapping[tuple[str, str], str] = {
    ("src/calculator/item_coverage.py", "_AUTHORITY_UNAVAILABLE"): (
        "names the published ``source_unavailable`` status value"
    ),
    ("src/calculator/spatial.py", "SPATIAL_UNAVAILABLE"): (
        "names the published ``nearby_enemy_spatial_input_unavailable`` reason"
    ),
    ("src/calculator/minion_stats.py", "MinionStatUnavailable"): (
        "a cached table that is absent, the sense ``CacheUnavailable`` owns"
    ),
    ("src/db.py", "CacheUnavailable"): (
        "a cached table that is absent, and one of the six caught exceptions"
    ),
    ("src/calculator/survival/transitions.py", "declared_price_unavailable"): (
        "a survival receipt key the walk writes onto the event"
    ),
    ("src/calculator/survival/transitions.py", "dynamic_resistance_unavailable"): (
        "a survival receipt key the walk writes onto the event"
    ),
    (
        "src/calculator/survival/transitions.py",
        "support_resistance_reduction_unavailable",
    ): "a survival receipt key the walk writes onto the event",
    ("src/calculator/support_scan.py", "all_teammates"): (
        "the ``all_teammates`` target scope it selects, read back as its name"
    ),
}


#: The nodes that bind a name by carrying one, rather than by context.
NAMED_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def defined_names(tree: ast.Module) -> Iterable[tuple[int, str]]:
    """Every name this module binds, with the line that binds it.

    A keyword argument counts, because the engine's receipt keys are written
    as one (``ledger.write(action, declared_price_unavailable=...)``).
    """
    for node in ast.walk(tree):
        if isinstance(node, NAMED_NODES):
            yield node.lineno, node.name
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            yield node.lineno, node.id
        elif isinstance(node, (ast.arg, ast.keyword)) and node.arg:
            yield node.lineno, node.arg
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
            yield node.lineno, node.attr


def _file_findings(where: str, source: str) -> list[str]:
    """Every banned spelling in one file, as reported lines."""
    found = [
        f"{where}:{number}: {word} -> {owner}"
        for number, line in enumerate(source.splitlines(), start=1)
        for word, owner in RESPELLED.items()
        if word in line.lower()
    ]
    found += [
        f"{where}:{line}: {name} holds {word} -> {owner}"
        for line, name in defined_names(ast.parse(source))
        for word, owner in NAME_ONLY.items()
        if word in name.lower() and (where, name) not in ALLOWED
    ]
    return found


def scan(root: Path = ROOT, targets: Iterable[str] = TARGETS) -> list[str]:
    """Every banned spelling under *targets*, one finding per line."""
    paths = (p for t in targets for p in (root / t).rglob("*.py"))
    found: list[str] = []
    for path in sorted(paths, key=lambda p: p.as_posix()):
        where = path.relative_to(root).as_posix()
        if where == SELF:
            continue
        found += _file_findings(where, path.read_text(encoding="utf-8"))
    return sorted(set(found))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.parse_args()
    found = scan()
    print("\n".join(found))
    print(f"one_spelling={len(found)}", file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
