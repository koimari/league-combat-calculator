"""The front door for ``item_outcomes`` — one declaration, and nothing else.

The module rides the behaviour frontier's declarative-home exclusion, which is
what keeps its forty-three item-name keys out of counter 1.  An exclusion is a
promise about what a module contains, so the promise is asserted here rather
than trusted: the day somebody adds a function to this file, the exclusion
would begin covering a dispatch and the counter would stop counting it.
"""

import ast
from pathlib import Path

from src.calculator.item_behavior import UtilityDimension
from src.calculator.item_outcomes import UTILITY_OUTCOMES

MODULE_PATH = Path(__file__).parents[1] / "src" / "calculator" / "item_outcomes.py"


def test_the_module_holds_the_declaration_and_nothing_else() -> None:
    """No `def`, no `class`, no branch: a declarative home is only declarations."""
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    shapes = [type(node).__name__ for node in tree.body]

    assert shapes == ["Expr", "ImportFrom", "ImportFrom", "AnnAssign"], shapes
    assert isinstance(tree.body[0].value, ast.Constant)
    assert tree.body[-1].target.id == "UTILITY_OUTCOMES"


def test_every_declared_outcome_is_a_member_of_the_one_vocabulary() -> None:
    """The values are typed, so a misspelling is an AttributeError at import."""
    assert UTILITY_OUTCOMES
    for item, dimensions in UTILITY_OUTCOMES.items():
        assert dimensions, item
        assert all(
            isinstance(dimension, UtilityDimension) for dimension in dimensions
        ), item
        assert len(set(dimensions)) == len(dimensions), item
