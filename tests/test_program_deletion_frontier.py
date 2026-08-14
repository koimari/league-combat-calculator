"""Phase 4's deletion frontier — the rows nothing else pins.

Phase 0 has its own frontier (``tests/test_deletion_frontier.py``) and this
is deliberately a second file rather than an extension of it: the two lists
have different owners, and a phase able to edit another phase's frontier
could retire a name by moving it.

Seven of Phase 4's nine rows are closed.  Three of those were closed by a
stage that pinned them where it worked, and re-asserting them here would give
one absence two homes — the drift this campaign exists to remove, aimed at
itself.  Those three are carried by :data:`PINNED_ELSEWHERE`, which is
checked rather than recited: each names the file and the test that holds it,
and a row whose test has been renamed or deleted fails here.  The other four
are asserted below, each under the stage that closed it.

**Two rows are open**, and they are named here rather than left out, because
a frontier that lists only its successes is a progress report.  Both are
carried by ``docs/receipts/escalated-defects-P4-S10.json`` with a dated
reason, a reproducer and a live gate, and this file asserts that the
artifact still holds exactly those two — so a row cannot be dropped from
both places at once.

The nine rows, and where each is read:

* ``legacy_phase`` — S2 — ``tests/test_transition_rank.py``
* ``owner: str`` — S1, replaced by the plain-``int`` ``holder`` slot the
  owner skip reads — here, from the kernel side (``tests/test_modifier_classes``
  reads the same absence from the packet side)
* the four ``str | None`` reference fields — S1, replaced by integer slots —
  ``tests/test_event_slots.py``
* ``survival_action_from_event`` — S4 — ``tests/test_program_structure.py``
* ``pipeline.py``'s ten-clause tuple predicate — S5, replaced by projection
  satisfaction — here
* ``_score_with_search_context``'s bespoke result assembly — S9, replaced by
  the score view — here
* ``_packet_typed_actions`` and ``packet["_typed"]`` — S10 — here
* ``WalkCompiler``'s duplicated dict/tuple branches — **open** — escalated
* the hardcoded first-defender scan — **open** — escalated

Rows that are somebody else's are named as *not* Phase 4's, because a
frontier that quietly absorbs a neighbour's deletion is how one phase's
receipt comes to describe another's work: Phase 0A's ``apply_transition``,
``utility_kind``, ``_has_catalyst`` and ``_priority``, Phase 2's five name
sets, and Phase 3's ``COMPILED_WALK_UNREPRESENTABLE_ITEMS`` are asserted
elsewhere and none of them is read here.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
TESTS = ROOT / "tests"

#: The rows this frontier has not closed, and the escalation entry that
#: carries each.  Asserted against the artifact rather than described, so a
#: row cannot quietly leave both the frontier and the escalation.
OPEN_ROWS: dict[str, str] = {
    "WalkCompiler's duplicated dict/tuple branches": (
        "walk_compilers_two_row_readers_are_not_the_duplication_the_frontier_names"
    ),
    "the hardcoded first-defender scan": (
        "the_first_defender_scan_survives_because_ccscope_was_never_authored"
    ),
}

#: Frontier row -> (test file, the test function that asserts its absence).
PINNED_ELSEWHERE: dict[str, tuple[str, str]] = {
    "legacy_phase": (
        "test_transition_rank.py",
        "test_the_float_projection_is_deleted_from_the_tree",
    ),
    "the four str | None reference fields": (
        "test_event_slots.py",
        "test_no_field_is_annotated_str_or_none",
    ),
    "survival_action_from_event": (
        "test_program_structure.py",
        "test_the_retired_builder_names_have_zero_occurrences",
    ),
}


def test_every_open_row_is_carried_by_the_escalation_artifact() -> None:
    """An unclosed row lives in two places or it lives in neither."""
    import json

    receipt = json.loads(
        (ROOT / "docs" / "receipts" / "escalated-defects-P4-S10.json").read_text(
            encoding="utf-8"
        )
    )
    carried = {defect["id"] for defect in receipt["defects"]}
    assert set(OPEN_ROWS.values()) <= carried


def _holders(name: str) -> list[str]:
    """Every file under ``src/`` whose source text still contains *name*."""
    return [
        path.relative_to(ROOT).as_posix()
        for path in sorted(SRC.rglob("*.py"))
        if name in path.read_text(encoding="utf-8")
    ]


def _function(module_path: Path, name: str) -> ast.AST:
    """One named function of a module, found by AST rather than by import."""
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    return next(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    )


# --- the rows another stage pinned where it worked ---------------------------


@pytest.mark.parametrize(("row", "location"), sorted(PINNED_ELSEWHERE.items()))
def test_a_row_pinned_elsewhere_still_has_the_test_that_pins_it(
    row: str, location: tuple[str, str]
) -> None:
    """An index that cannot go stale: the cited test is resolved, not quoted."""
    filename, test_name = location
    path = TESTS / filename
    assert path.is_file(), (row, filename)
    assert _function(path, test_name) is not None, (row, test_name)


def test_the_owner_string_is_gone_and_the_holder_slot_replaced_it() -> None:
    """S1's swap, read off the tuple: no ``owner``, and ``holder`` is an int.

    ``tests/test_modifier_classes`` reads the same absence from the packet
    side; this reads it from the kernel side, which is the half that decides
    what the owner skip compares.
    """
    from src.calculator.survival.actions import SurvivalAction

    assert "owner" not in SurvivalAction._fields
    assert "holder" in SurvivalAction._fields
    assert isinstance(SurvivalAction().holder, int)


# --- S5: the ten-clause tuple predicate --------------------------------------


def test_the_tuple_gate_asks_the_projection_rather_than_ten_clauses() -> None:
    """D-38's ten adequacy clauses are one call to a declared projection.

    The reading is over the gate's own expression, so it survives any
    rewording: whatever the predicate became, it may not be a conjunction of
    adequacy tests kept in ``pipeline.py``.  ``score_only and
    ledger_projection(...) is ...`` is two operands; the retired spelling
    was the ``score_only`` guard and ten more.
    """
    from src.calculator import pipeline

    tree = ast.parse(Path(pipeline.__file__).read_text(encoding="utf-8"))
    assignments = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "tuple_ledger"
            for target in node.targets
        )
    ]
    assert len(assignments) == 1
    conjunction = assignments[0].value
    assert isinstance(conjunction, ast.BoolOp)
    assert len(conjunction.values) == 2


# --- S9: the bespoke score assembly ------------------------------------------


def test_the_score_path_assembles_no_payload_of_its_own() -> None:
    """The ~150-line result assembly is the score view, or it is two engines.

    ``_score_with_search_context`` still exists — it is the compiled panel's
    entry point — and what S9 deleted is the payload it used to end in.  A
    function that builds its own result cannot be the same producer as the
    view, which is what criterion 3 is about, so the assertion is that it
    returns a value it was handed rather than a dict it composed.
    """
    from src.calculator import participant_timeline

    function = _function(
        Path(participant_timeline.__file__), "_score_with_search_context"
    )
    composed = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict)
    ]
    assert composed == []


# --- S10: the packet-side typed-action map -----------------------------------


def test_the_packet_carries_no_typed_action_map() -> None:
    """Criterion 14: ``packet["_typed"]`` has zero occurrences.

    The map was keyed on ``id(template)`` and stashed inside the mutable
    packet dict it was derived from — the id-keyed cache shape counter 7
    exists to remove, one package outside counter 7's scanned trees.
    """
    assert _holders("_packet_typed_actions") == []
    assert _holders('"_typed"') == []
    assert _holders("typed_lookup") == []


def test_the_survival_walk_takes_no_precompiled_actions() -> None:
    """The parameter goes with the map: every event converts in one place."""
    import inspect

    from src.calculator.participant_timeline import _simulate_survival

    assert "typed_actions" not in inspect.signature(_simulate_survival).parameters
