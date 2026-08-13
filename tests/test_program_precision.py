"""The precision registry: one home for every published digit count (D-71).

What is asserted here is not that ``round`` works.  It is that the registry
is the *only* place ``program/`` decides a precision, that an undeclared
field fails closed instead of picking a default, and that the death-time
cutoff is a named policy rather than a comparison somebody could quietly
improve.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src.calculator.program import precision

PROGRAM_ROOT = Path(precision.__file__).resolve().parent


def test_every_declared_precision_is_a_digit_count() -> None:
    """A registry entry is a field name and a non-negative integer."""
    for field, digits in precision.ROUNDING.items():
        assert isinstance(field, str) and field.strip(), field
        assert isinstance(digits, int) and digits >= 0, field


def test_the_registry_is_not_writable_through_its_public_name() -> None:
    """One home means one writer: the mapping is a read-only view."""
    with pytest.raises(TypeError):
        precision.ROUNDING["death_time"] = 9  # type: ignore[index]


def test_a_field_with_no_declared_precision_raises_naming_itself() -> None:
    """Fail closed: an undeclared field never gets a default digit count."""
    with pytest.raises(precision.UnregisteredField) as excinfo:
        precision.digits_for("a_field_nobody_declared")
    assert "a_field_nobody_declared" in str(excinfo.value)
    assert "ROUNDING" in str(excinfo.value)


def test_round_field_rounds_at_the_declared_precision() -> None:
    """The three published precisions, each read off the registry."""
    assert precision.round_field("damage_taken", 1234.5678) == 1234.6
    assert precision.round_field("death_time", 4.567891) == 4.568
    assert precision.round_field("venom_factor", 0.8765432198) == 0.876543


def test_round_field_refuses_a_field_it_has_no_precision_for() -> None:
    """``round_field`` is ``digits_for`` plus a call; it fails the same way."""
    with pytest.raises(precision.UnregisteredField):
        precision.round_field("a_field_nobody_declared", 1.0)


def test_the_cutoff_policy_has_exactly_one_member_and_no_default() -> None:
    """One live policy, named.  A second member is what a change looks like."""
    assert [member.name for member in precision.CutoffPolicy] == ["ROUNDED_DEATH_TIME"]


def test_a_survivor_is_cut_off_at_the_fight_window() -> None:
    """No death time means the window itself is the cutoff."""
    assert (
        precision.damage_cutoff(None, 5.0, precision.CutoffPolicy.ROUNDED_DEATH_TIME)
        == 5.0
    )


def test_the_cutoff_is_the_published_death_time_sliver_and_all() -> None:
    """The quirk the policy names, asserted rather than described.

    The walk's raw death time is published rounded to the millisecond, and
    the cutoff reads the published number.  An event at 4.5679 s therefore
    still counts against an actor whose raw death was 4.56789 s, because the
    published time is 4.568.  Reaching for the raw number would be the more
    correct comparison and a silent change to a published total.
    """
    raw_death = 4.567891
    published = precision.round_field("death_time", raw_death)
    cutoff = precision.damage_cutoff(
        published, 10.0, precision.CutoffPolicy.ROUNDED_DEATH_TIME
    )
    assert cutoff == 4.568
    assert 4.5679 <= cutoff
    assert 4.5679 > raw_death


def test_an_unknown_cutoff_policy_raises() -> None:
    """Totality: the function answers for members, and refuses the rest."""
    with pytest.raises(ValueError):
        precision.damage_cutoff(1.0, 5.0, "rounded_death_time")  # type: ignore[arg-type]


def _round_call_sites(path: Path) -> list[int]:
    """Every ``round(...)`` call expression in one module."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "round"
    ]


def test_the_registry_is_the_only_module_in_program_that_rounds() -> None:
    """D-71's scope clause, as a test on the package rather than a rule.

    Migration frontier counter 6 gates the same property from the outside;
    this is the inside view, so a new ``program/`` module that rounds fails
    on the suite rather than only on the gate script.
    """
    offenders = {
        path.relative_to(PROGRAM_ROOT).as_posix(): _round_call_sites(path)
        for path in sorted(PROGRAM_ROOT.rglob("*.py"))
        if path.name != "precision.py" and _round_call_sites(path)
    }
    assert offenders == {}
