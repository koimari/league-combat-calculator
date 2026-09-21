"""One concept has one spelling in ``src/`` and ``scripts/``.

The vocabulary and its reasons live in ``scripts/one_spelling.py``; this file
is the gate's pytest row and the guard over its two tables.
"""

import ast

import pytest

from scripts.one_spelling import (
    ALLOWED,
    NAME_ONLY,
    RESPELLED,
    ROOT,
    defined_names,
    scan,
)
from src.calculator import quantity

#: A module that misspells both kinds of rule, so a rule silently dropped from
#: either table fails here rather than at the next merge.
DRIFTED = '''"""A catalogue of things."""

from math import prod as teammate_total


def price(teammate, wearer):
    unavailable = teammate or wearer
    return unavailable


def caught():
    try:
        return price(1, 2)
    except ValueError as teammate_error:
        return teammate_total(teammate_error.args)
'''


def test_the_tree_spells_each_concept_once():
    found = scan()
    assert found == [], "\n".join(found)


def test_a_second_spelling_of_either_kind_fails(tmp_path):
    """A banned word fails from the whole file, and a banned name from its name."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "drifted.py").write_text(DRIFTED, encoding="utf-8")
    found = scan(root=tmp_path, targets=("src",))
    reported = {line.split(": ", 1)[1] for line in found}
    assert {"catalogue -> catalog", "wearer -> holder"} <= reported
    assert {
        "teammate holds teammate -> ally",
        "teammate_total holds teammate -> ally",
        "teammate_error holds teammate -> ally",
        "unavailable holds unavailab -> withheld / refusal",
    } <= reported


@pytest.mark.parametrize("word", sorted({*RESPELLED, *NAME_ONLY}))
def test_a_banned_word_names_the_spelling_that_replaces_it(word):
    assert (RESPELLED | NAME_ONLY)[word].strip()


@pytest.mark.parametrize(("where", "name"), sorted(ALLOWED))
def test_every_allowed_name_is_still_defined(where, name):
    """The allowlist only shrinks: an entry the tree does not define fails."""
    tree = ast.parse((ROOT / where).read_text(encoding="utf-8"))
    defined = {bound for _, bound in defined_names(tree)}
    assert name in defined, f"{where} does not define {name}"
    assert ALLOWED[where, name].strip(), f"{where}:{name} needs a reason"


def test_the_two_refusal_kinds_are_quantity_types():
    """``quantity`` owns both spellings the gate leaves standing."""
    assert {quantity.Withheld, quantity.Starved} <= set(quantity.Quantity.__args__)
