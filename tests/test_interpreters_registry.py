"""The front door for ``interpreters`` — the map, the fold, and both directions.

Three claims live here.  The lane table says which engines owe each family an
answer, so "every family is interpreted" cannot be true of an empty registry.
The ``compilability_for`` fold gives a per-item question a per-item answer,
which is what lets it replace a per-item legacy set.  And reachability is
checked in **both** directions (D-51), because both failures are real: a
declaration no interpreter serves, and an interpreter branch no declaration
reaches.
"""

import ast
from pathlib import Path

import pytest

from src.calculator import interpreters
from src.calculator.item_behavior import (
    Compilable,
    EngineLane,
    ReceiptOnly,
    RuleFamily,
)
from src.calculator.item_behavior_catalog import registry_owners

SRC_ROOT = Path(__file__).parents[1] / "src" / "calculator"


class _StubInterpreter:
    """A registered interpreter, so the registry's own gates have a subject."""

    def __init__(self, family: RuleFamily, lanes: frozenset[EngineLane]) -> None:
        self.FAMILY = family  # pylint: disable=invalid-name
        self.LANES = lanes  # pylint: disable=invalid-name

    def compile(self, rule, ctx):  # pragma: no cover - never called here
        """Emit nothing; these tests are about registration, not compilation."""
        del rule, ctx
        return ()


def test_every_family_declares_the_lanes_that_owe_it_an_answer() -> None:
    """Declared, not inferred — otherwise an empty registry reports full cover."""
    for family in RuleFamily:
        assert interpreters.lanes_for(family)
    assert len(interpreters.declared_pairs()) == 51


def test_counter_four_is_the_gap_between_the_table_and_the_registry() -> None:
    """At the skeleton every declared pair is uninterpreted, and it is counted."""
    assert len(interpreters.uninterpreted_pairs()) == len(interpreters.declared_pairs())
    assert interpreters.INTERPRETERS == {}


def test_an_owner_whose_behaviour_is_still_engine_code_is_not_compilable() -> None:
    """The fold fails closed: an absence never becomes a compiled-lane promise."""
    verdict = interpreters.compilability_for("Black Cleaver")
    assert isinstance(verdict, ReceiptOnly)
    assert "Black Cleaver" in verdict.reason


def test_an_owner_with_no_registry_entry_has_nothing_to_represent() -> None:
    """Stats-only items are compilable because there is no behaviour to compile."""
    assert isinstance(interpreters.compilability_for("Boots"), Compilable)


def test_the_fold_concatenates_receipt_only_reasons_in_declaration_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-43's fold, stated here rather than left to each caller."""

    class _Rule:  # pylint: disable=too-few-public-methods
        def __init__(self, compilability) -> None:
            self.compilability = compilability

    monkeypatch.setattr(
        interpreters,
        "behavior_rules",
        lambda owner: (
            _Rule(Compilable()),
            _Rule(ReceiptOnly("first")),
            _Rule(ReceiptOnly("second")),
        ),
    )
    verdict = interpreters.compilability_for("Anything")
    assert isinstance(verdict, ReceiptOnly)
    assert verdict.reason == "first; second"


def test_all_compilable_folds_to_compilable(monkeypatch: pytest.MonkeyPatch) -> None:
    """The other half of the fold."""

    class _Rule:  # pylint: disable=too-few-public-methods
        def __init__(self, compilability) -> None:
            self.compilability = compilability

    monkeypatch.setattr(
        interpreters, "behavior_rules", lambda owner: (_Rule(Compilable()),)
    )
    assert isinstance(interpreters.compilability_for("Anything"), Compilable)


def test_reachability_is_empty_in_both_directions_at_the_skeleton() -> None:
    """No declaration and no interpreter means neither direction has a subject."""
    report = interpreters.reachability_report(registry_owners())
    assert report.unreached_declarations == ()
    assert report.orphan_branches == ()


def test_an_interpreter_no_declaration_reaches_is_an_orphan_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-51's interpreter->author direction, with a red it can reproduce."""
    stub = _StubInterpreter(RuleFamily.DELTA_AMP, frozenset({EngineLane.PAIR_ENGINE}))
    monkeypatch.setattr(
        interpreters,
        "INTERPRETERS",
        {(RuleFamily.DELTA_AMP, EngineLane.PAIR_ENGINE): stub},
    )
    report = interpreters.reachability_report(frozenset())
    assert report.orphan_branches == (
        "delta_amp/pair_engine is registered and no declaration reaches it",
    )
    with pytest.raises(interpreters.InterpreterRegistryError, match="orphan|reaches"):
        interpreters.validate_registrations()


def test_a_registration_that_contradicts_its_own_interpreter_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The key and the interpreter's own declaration are one fact, checked."""
    stub = _StubInterpreter(RuleFamily.SUSTAIN, frozenset({EngineLane.PAIR_ENGINE}))
    monkeypatch.setattr(
        interpreters,
        "INTERPRETERS",
        {(RuleFamily.DELTA_AMP, EngineLane.PAIR_ENGINE): stub},
    )
    with pytest.raises(interpreters.InterpreterRegistryError, match="does not claim"):
        interpreters.validate_registrations()


def test_a_registration_on_a_lane_the_family_never_declared_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An interpreter on an undeclared lane can never be reached."""
    stub = _StubInterpreter(RuleFamily.ALLY_PACKET, frozenset({EngineLane.PAIR_ENGINE}))
    monkeypatch.setattr(
        interpreters,
        "INTERPRETERS",
        {(RuleFamily.ALLY_PACKET, EngineLane.PAIR_ENGINE): stub},
    )
    with pytest.raises(interpreters.InterpreterRegistryError, match="declares no"):
        interpreters.validate_registrations()


def test_validate_registrations_runs_at_import() -> None:
    """The registry's gates are import-time, so a bad map fails collection."""
    module = SRC_ROOT / "interpreters" / "__init__.py"
    tree = ast.parse(module.read_text(encoding="utf-8"))
    called = {
        node.value.func.id
        for node in tree.body
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
    }
    assert "validate_registrations" in called


def test_nothing_under_survival_imports_the_interpreter_package() -> None:
    """The one-way dependency the build-time contract rests on."""
    offenders = []
    for path in sorted((SRC_ROOT / "survival").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.ImportFrom) and node.module:
                if "interpreters" in node.module or "item_behavior_catalog" in (
                    node.module
                ):
                    offenders.append(f"{path.name}: {node.module}")
            elif isinstance(node, ast.Import):
                offenders.extend(
                    f"{path.name}: {alias.name}"
                    for alias in node.names
                    if "interpreters" in alias.name
                    or "item_behavior_catalog" in alias.name
                )
    assert offenders == []
