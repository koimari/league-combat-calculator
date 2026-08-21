"""Phase 4's deletion frontier — the rows nothing else pins.

Phase 0 has its own frontier (``tests/test_deletion_frontier.py``) and this
is deliberately a second file rather than an extension of it: the two lists
have different owners, and a phase able to edit another phase's frontier
could retire a name by moving it.

Eight of Phase 4's nine rows are closed.  Three of those were closed by a
stage that pinned them where it worked, and re-asserting them here would give
one absence two homes — the drift this campaign exists to remove, aimed at
itself.  Those three are carried by :data:`PINNED_ELSEWHERE`, which is
checked rather than recited: each names the file and the test that holds it,
and a row whose test has been renamed or deleted fails here.  The other five
are asserted below, each under the stage that closed it.

**One row is open**, and it is named here rather than left out, because a
frontier that lists only its successes is a progress report.  It is carried
by ``docs/receipts/escalated-defects-P4-S10.json`` with a dated reason, a
reproducer and a live gate, and this file asserts that the artifact still
holds exactly it — so a row cannot be dropped from both places at once.
:data:`RETIRED_ROWS` is the other direction: a row that *was* escalated and
has since closed stays named here, against the artifact's ``retired`` list,
so "how many rows are open" has one answer and not two.

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
* ``WalkCompiler``'s duplicated dict/tuple branches — S10, unified into one
  loop with one tail — here
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
OPEN_ROWS: dict[str, str] = {}

#: Rows this frontier closed *after* escalating them, and the escalation
#: entry each retired.  A closed row leaves ``OPEN_ROWS`` and arrives here
#: rather than simply vanishing: the artifact's own rule is that an entry
#: retires with the inversion of its test, never by deletion, and a frontier
#: that dropped the row would leave the artifact the only place the history
#: existed.
RETIRED_ROWS: dict[str, str] = {
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
    assert set(RETIRED_ROWS.values()) <= {defect["id"] for defect in receipt["retired"]}
    assert not set(RETIRED_ROWS.values()) & carried


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


# --- S10: the compiler's two row readers, retired ----------------------------


def test_the_compiler_reads_its_two_row_shapes_in_one_loop() -> None:
    """The row ``RETIRED_ROWS`` names, read off the tree that closed it.

    Not "no ``damage_events_tuple`` mention" — the light ledger is a live
    representation and the reader has to know which one it holds.  What the
    row was about is *duplication*, so what is asserted is the shape that
    ends it: one loop over the damage events, one call to the constructor,
    one call to each of the two appenders the tail performs.  Two loops
    would show two of each.
    """
    from src.calculator.program import compile as compile_module

    function = _function(Path(compile_module.__file__), "add_engine_result")
    damage_loops = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.For)
        and "damage_events" in ast.dump(node.iter)
        and "damage_events_tuple" not in ast.dump(node.iter)
    ]
    assert len(damage_loops) == 1
    calls = [
        node.func.id
        for node in ast.walk(damage_loops[0])
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    assert calls.count("compiled_damage_action") == 1
    assert calls.count("champion_wound_tuple") == 1
    assert calls.count("live_amp_for") == 1


def test_a_light_ledger_declaring_a_self_heal_is_refused() -> None:
    """What the deleted early return used to enforce, enforced on purpose.

    Unifying the two row readers let a light ledger *enter* the heal loop
    instead of being skipped before it, and the loop is a no-op there only
    because ``pipeline.py`` sets ``self_healing_events = []`` on the same
    three lines that set ``damage_events_tuple``.  That is a cross-module
    invariant, and it was carried by a comment in the other module: nothing
    failed if it stopped being true, and what it protects is invisible —
    a light row is a positional tuple with no ``time`` or ``source_key``
    key, so the linkage the heal loop performs would find nothing and the
    heals would compile to zero actions.  A number that vanishes without a
    symptom is this campaign's subject, so the compiler refuses instead.
    """
    from src.calculator.program.compile import WalkCompiler

    compiler = WalkCompiler(0)
    with pytest.raises(ValueError, match="compile to nothing"):
        compiler.add_engine_result(
            {
                "damage_events": [],
                "damage_events_tuple": True,
                "self_healing_events": [{"time": 1.0, "amount": 10.0}],
            },
            "main",
            0,
            "enemy:X",
            1,
            {},
            10.0,
            {},
            [],
            0,
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
