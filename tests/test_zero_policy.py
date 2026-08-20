"""D-24's ruled exception, and the guard it ships with.

Every ``BehaviorRule`` carries a ``zero_policy`` with no default, because a
defaulted disposition is the indistinguishable zero this campaign exists to
remove.  The champion tree is the one place that rule is discharged by a
*declared default* instead: ``damage_entry`` and ``simple_damage`` are the
single construction layer for every numeric leaf a champion module authors,
so the policy is stated once there and the 397 call sites across 151
champion modules are deliberately not edited — a required-no-default field
there would be a campaign-wide champion sweep smuggled in by an idiom.  That
blast radius is measured here rather than recalled, because a decision
justified by a number owes the number a producer.

An exception is only as good as its guard, so three things are asserted
here: the default exists at exactly one layer and nowhere else in
``champions/``, it is genuinely overridable (``stat_buff``'s steroid zero is
a ``STRUCTURAL_ZERO`` and says so), and it reaches the leaf — the part, not
just the entry — so Phase 4 has a disposition to serialize.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from src.calculator.ability_spec import DamagePart, Disposition, ZeroPolicy
from src.calculator.champions.slotlib import (
    MODULE_FORMULA_ZERO,
    STEROID_ZERO,
    damage_entry,
    simple_damage,
)

ROOT = Path(__file__).resolve().parents[1]
CHAMPIONS_ROOT = ROOT / "src" / "calculator" / "champions"
SLOTLIB = CHAMPIONS_ROOT / "slotlib.py"


def _defaulted_zero_policy_params(path: Path) -> list[tuple[str, int]]:
    """Every ``zero_policy=<default>`` parameter declared in one module."""
    found: list[tuple[str, int]] = []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        args = node.args
        positional = args.posonlyargs + args.args
        pairs = list(
            zip(positional[len(positional) - len(args.defaults) :], args.defaults)
        )
        pairs += [
            (arg, default)
            for arg, default in zip(args.kwonlyargs, args.kw_defaults)
            if default is not None
        ]
        for arg, _default in pairs:
            if arg.arg == "zero_policy":
                found.append((node.name, node.lineno))
    return found


def test_the_declared_default_lives_at_exactly_one_layer() -> None:
    """D-24's exception is one layer, named — not a habit spread by copying."""
    layers = {
        path.relative_to(CHAMPIONS_ROOT).as_posix(): _defaulted_zero_policy_params(path)
        for path in sorted(CHAMPIONS_ROOT.rglob("*.py"))
        if _defaulted_zero_policy_params(path)
    }
    assert set(layers) == {"slotlib.py"}
    assert {name for name, _line in layers["slotlib.py"]} == {
        "damage_entry",
        "simple_damage",
    }


def _builder_call_sites() -> dict[str, int]:
    """``damage_entry``/``simple_damage`` calls per champion module.

    The counting rule, stated so the figure is reproducible (R-29's idiom):
    every ``ast.Call`` under ``champions/`` whose callee spells
    ``damage_entry`` or ``simple_damage``, by ``ast.Name`` or by attribute,
    excluding ``slotlib.py`` itself — that file is the construction *layer*,
    not one of the call sites the exception is measured over.
    """
    counts: dict[str, int] = {}
    for path in sorted(CHAMPIONS_ROOT.rglob("*.py")):
        if path.name == "slotlib.py":
            continue
        found = 0
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            callee = node.func
            name = (
                callee.id
                if isinstance(callee, ast.Name)
                else callee.attr if isinstance(callee, ast.Attribute) else ""
            )
            if name in ("damage_entry", "simple_damage"):
                found += 1
        if found:
            counts[path.name] = found
    return counts


def test_the_blast_radius_the_exception_avoids_is_measured_not_recalled() -> None:
    """D-24's exception is justified by a figure, so the figure is pinned.

    The decision's own argument is that a required-no-default field would be
    a campaign-wide champion sweep: it names the size of that sweep, and a
    named size nothing measures is the shape of claim this campaign exists to
    end.  ``slotlib.py``'s docstring, this file's, D-24 and phase 3's
    criterion 7 all state these two numbers, so they cannot be restated
    without this going red.
    """
    counts = _builder_call_sites()
    assert (sum(counts.values()), len(counts)) == (397, 151)


def test_the_declared_default_is_keyword_only_at_both_builders() -> None:
    """A trailing positional would let an extra argument bind into it.

    ``damage_entry`` takes six positional parameters and is called with
    them positionally across the champion tree; a seventh positional slot
    named ``zero_policy`` turns any miscounted call into a policy silently
    replaced by a float — the indistinguishable-default shape one layer up
    from the one D-24 removes.
    """
    for builder in (damage_entry, simple_damage):
        parameters = inspect.signature(builder).parameters
        assert (
            parameters["zero_policy"].kind is inspect.Parameter.KEYWORD_ONLY
        ), f"{builder.__name__} must take zero_policy by keyword only"


def test_the_default_is_measured_and_carries_its_reason() -> None:
    """A module formula that evaluates to zero *computed* that zero."""
    assert MODULE_FORMULA_ZERO.disposition is Disposition.MEASURED
    assert "computed zero" in MODULE_FORMULA_ZERO.reason


def test_the_default_reaches_the_leaf_not_only_the_entry() -> None:
    """The disposition lands on the part, which is the numeric leaf."""
    entry = damage_entry("Q", 3, 8.0, 250.0, "physical")
    assert [part.zero_policy for part in entry["parts"]] == [MODULE_FORMULA_ZERO]


def test_a_mixed_entry_stamps_both_of_its_parts() -> None:
    """Two parts are two leaves, and neither may be born undispositioned."""
    entry = damage_entry("Q", 3, 8.0, 100.0, "mixed")
    assert [part.zero_policy for part in entry["parts"]] == [
        MODULE_FORMULA_ZERO,
        MODULE_FORMULA_ZERO,
    ]


def test_the_default_is_overridable_per_call() -> None:
    """Overridable in fact, not only in signature — the steroid slot uses it."""
    declared = ZeroPolicy(Disposition.STRUCTURAL_ZERO, "the mechanic deals no damage")
    entry = damage_entry("R", 3, 70.0, 0.0, "physical", zero_policy=declared)
    assert entry["parts"][0].zero_policy is declared
    assert STEROID_ZERO.disposition is Disposition.STRUCTURAL_ZERO


def test_a_raw_part_is_undispositioned_rather_than_defaulted() -> None:
    """``DamagePart`` itself has no opinion; only a builder declares one.

    The default belongs to the construction *layer*, not to the record: a
    ``DamagePart`` built by hand somewhere the campaign has not reached says
    ``None``, which is a measurable gap, where a ``MEASURED`` default there
    would be the campaign's own failure shape written into the type.
    """
    assert DamagePart("physical", 0.0).zero_policy is None


def test_the_policy_is_absent_from_the_golden_repr() -> None:
    """Publication is Phase 4's ``serialize_leaf``, not the pair snapshot.

    The golden snapshot serializes parts through ``repr``, so a printed
    policy would move every ability repr in the baseline for a field no
    engine reads — and this phase's criterion 17 allows a golden diff for
    exactly one slice, which is not this one.
    """
    printed = repr(DamagePart("physical", 5.0, zero_policy=MODULE_FORMULA_ZERO))
    assert "zero_policy" not in printed
    assert printed == repr(DamagePart("physical", 5.0))


def test_the_policy_is_metadata_and_not_part_of_a_part_s_identity() -> None:
    """Equality and hashing say what the repr says, or one of them is lying.

    ``DamagePart`` is a frozen dataclass, so a new field joins ``__eq__``
    and ``__hash__`` unless it declares otherwise.  A field the repr hides
    but equality reads would make two parts that print identically compare
    unequal and take two slots in a set — a future dedup discriminating on
    an invisible field.  The policy is a statement *about* the number, not
    part of the number's identity, so it is ``compare=False``.
    """
    plain = DamagePart("physical", 5.0)
    dispositioned = DamagePart("physical", 5.0, zero_policy=MODULE_FORMULA_ZERO)
    assert plain == dispositioned
    assert hash(plain) == hash(dispositioned)
    assert len({plain, dispositioned}) == 1
    # And the field still carries its value — excluded from equality is not
    # excluded from the record.
    assert dispositioned.zero_policy is MODULE_FORMULA_ZERO


def test_a_policy_without_a_reason_is_refused() -> None:
    """A disposition with no receipt is a label (the rule-level check too)."""
    with pytest.raises(ValueError, match="reason"):
        ZeroPolicy(Disposition.MEASURED, "  ")
    with pytest.raises(ValueError, match="Disposition"):
        ZeroPolicy("MEASURED", "a string is not a disposition")  # type: ignore[arg-type]
