"""``data/atoms/atoms.schema.json`` is the contract the champion atoms keep.

The schema is the one home for the atom shape, so this reads its ``required``
set, its declared properties and its family enum rather than restating any of
them: a key the atomizer drops, a field it renames, or a family the classifier
invents fails on the commit that lands it, not on the patch day that reads the
corpus back.
"""

import json
from pathlib import Path

from scripts.tracked_data_lint import tracked

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "data/atoms/atoms.schema.json").read_text(encoding="utf-8"))
ATOM = SCHEMA["items"]
REQUIRED = frozenset(ATOM["required"])
DECLARED = frozenset(ATOM["properties"])
FAMILIES = frozenset(ATOM["properties"]["family"]["enum"])


def _rows(path: Path) -> list[dict]:
    """The atom list one corpus file holds, refusing any other top-level shape."""
    document = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(document, list), f"{path.name}: the schema declares an array"
    return document


def _breaks(atom: dict) -> str:
    """The first way an atom leaves the schema, or an empty string."""
    missing = REQUIRED - atom.keys()
    undeclared = atom.keys() - DECLARED
    if missing:
        return f"missing {sorted(missing)}"
    if undeclared:
        return f"undeclared {sorted(undeclared)}"
    if atom["family"] not in FAMILIES:
        return f"family {atom['family']!r} is outside the taxonomy"
    return ""


def test_every_tracked_champion_atom_keeps_the_schema():
    """The tracked corpus is the sample a fresh checkout gets; it must conform."""
    corpus = [
        path
        for path in tracked(ROOT, "data/atoms")
        if path.name.endswith(".atoms.json")
    ]
    assert corpus, "no tracked champion atom file: the corpus this gate reads is gone"
    broken = [
        f"{path.name}[{index}]: {reason}"
        for path in corpus
        for index, atom in enumerate(_rows(path))
        if (reason := _breaks(atom))
    ]
    assert broken == []
