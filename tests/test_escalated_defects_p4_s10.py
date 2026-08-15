"""S10's escalation, gated: what this slice found and may not fix.

An escalation living only in a commit body is absorbed by the next baseline
re-capture, which is why the runbook makes it an artifact (R-16 Shape).  An
artifact nothing runs is prose in a JSON file, which is why it has this.

Each defect declares a reproducer and each reproducer runs here, so an entry
retires *with* the inversion of its own test and never by being deleted.

Three entries have since done exactly that.  S10 unified the compiler's two
row readers after an R-35 verifier reported criterion 2 undischarged on
them; the Phase 4 boundary integration re-pinned ``tests.collected``, which
is the one exit the second entry named; and the first-defender scan row
closed the way its own ``for_the_phase_owner`` demanded -- H2's recorded
default shipped as its own semantic slice, ``CcScope`` authored, the Command
mark routed to ``TriggerTarget``, the scan deleted, the disclosure
published.  All three moved to ``retired`` carrying what the lane measured,
and the tests that reproduced them are inverted below rather than removed,
so the artifact and the tree still say the same thing about a row whose
answer changed.

One of the three open entries began as a deletion-frontier row cleanup
cannot close; the other two are gaps a later reader found in what S10
shipped -- an instrument that holds one scenario set while a criterion names
another, and a fallback reason that is required at construction and
published nowhere.  What the three have in common is not their subject: it
is that closing any of them is a write outside this lane's ownership -- one
of R-32's five baselines, or L0's harness contract.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RECEIPT = ROOT / "docs" / "receipts" / "escalated-defects-P4-S10.json"
SRC = ROOT / "src" / "calculator"


def receipt() -> dict:
    """The committed artifact this file is the gate for."""
    return json.loads(RECEIPT.read_text(encoding="utf-8"))


def test_the_receipt_declares_what_it_is_and_what_gates_it() -> None:
    block = receipt()
    assert block["artifact"] == "escalated_defects"
    assert block["slice"] == "P4-S10"
    assert block["gate"] == "tests/test_escalated_defects_p4_s10.py"


def test_every_open_defect_carries_a_reproducer_and_a_date() -> None:
    """An entry without a reproducer is an opinion with a filename."""
    for defect in receipt()["defects"]:
        assert defect["id"] and defect["dated"]
        assert defect["reproducer"] and defect["reproducer_after_closure"]
        assert defect["why_this_lane_may_not_fix_it"]
        assert defect["for_the_phase_owner"]


def test_the_open_defects_are_the_ones_this_file_reproduces() -> None:
    """A gate that drifted off its entries is a gate for nothing."""
    assert [defect["id"] for defect in receipt()["defects"]] == [
        "no_production_path_emits_a_non_measured_disposition_consumption_half_closed",
    ]


def test_a_retired_entry_says_how_it_closed_and_what_gates_it_now() -> None:
    """Retirement is a record, not a deletion — the artifact's own rule."""
    retired = receipt()["retired"]
    assert [entry["id"] for entry in retired] == [
        "walk_compilers_two_row_readers_are_not_the_duplication_the_frontier_names",
        "r01_row_1s_pinned_collected_count_is_the_integration_agents_and_is_stale",
        "the_first_defender_scan_survives_because_ccscope_was_never_authored",
        "the_fallback_reason_is_carried_on_the_decision_and_published_nowhere",
        "the_bit_exact_clause_names_a_scenario_set_the_instrument_does_not_hold",
    ]
    for entry in retired:
        assert entry["retired"] and entry["retired_by"]
        assert entry["how_it_closed"] and entry["what_the_lane_measured"]
        assert entry["gate_after_closure"]
        # The reproducer it declared has to be the one that stopped
        # reproducing, so the entry still names it.
        assert entry["reproducer"] and entry["reproducer_after_closure"]


# --- the first-defender scan -------------------------------------------------


def _source(*parts: str) -> str:
    return (SRC.joinpath(*parts)).read_text(encoding="utf-8")


def test_cc_scope_is_a_closed_vocabulary_in_src() -> None:
    """The inversion: the shipped H2 default is now constructed.

    ``CcScope`` is the union alias rather than a class, so the assertion is
    on the alias and on every member the union closes over — a vocabulary
    that named itself and left the members to a caller's imagination would
    reproduce the row it retired.
    """
    scope = _source("program", "scope.py")
    tree = ast.parse(scope)
    assigned = {
        target.id
        for node in ast.walk(tree)
        for target in (
            node.targets
            if isinstance(node, ast.Assign)
            else [node.target] if isinstance(node, ast.AnnAssign) else []
        )
        if isinstance(target, ast.Name)
    }
    classes = {node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}
    assert {"CcScope", "CC_SCOPES"} <= assigned
    assert {"SingleTarget", "MultiTarget", "Unreviewed"} <= classes
    functions = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }
    assert {"reviewed_scope", "scope_policy"} <= functions


def test_the_first_defender_scan_has_zero_occurrences() -> None:
    """The inversion: no definition and no call, anywhere under ``src/``."""
    hits = [
        path.relative_to(SRC).as_posix()
        for path in sorted(SRC.rglob("*.py"))
        if "_first_pair_defender_id" in path.read_text(encoding="utf-8")
    ]
    assert hits == []


def test_the_score_paths_support_scan_no_longer_indexes_pair_zero() -> None:
    """The other half of the same convention, inverted in the same commit.

    The defender is captured beside ``first_result`` in the loop that
    produces it, so the fact has one source instead of a second index into
    the same list a hundred lines away.  Asserted over the AST rather than
    over the text: the comment recording what the code used to do names the
    retired expression, and a comment must never be able to fail a gate.
    """
    timeline = _source("participant_timeline.py")
    subscripts = [
        node
        for node in ast.walk(ast.parse(timeline))
        if isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "main_pair_params"
    ]
    assert subscripts == []
    assert "first_defender = defender" in timeline


def test_a_command_mark_routes_to_the_trigger_and_not_to_a_scan() -> None:
    """Criterion 9's third clause, asserted where the mark is authored."""
    tree = ast.parse(_source("item_support_effects.py"))
    subjects = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_cc_mark_subjects"
    )
    policies = {
        node.attr for node in ast.walk(subjects) if isinstance(node, ast.Attribute)
    }
    assert "TriggerTarget" in policies
    assert "resolve_route" in policies


# --- the compiler's two row readers, retired ---------------------------------


def test_the_compiler_still_knows_which_row_shape_it_holds() -> None:
    """Retiring the row did not delete the light ledger, and must not.

    The entry's own ``reproducer_after_closure`` offers two inversions --
    "reads one row shape, **or** the frontier row names the constructor".
    What landed is neither restatement: one loop, one tail, and a two-arm
    read of the two representations.  ``damage_events_tuple`` is therefore
    still consulted, exactly once, and a reader that stopped consulting it
    would be compiling light rows as dicts.
    """
    compiler = _source("program", "compile.py")
    assert compiler.count('result.get("damage_events_tuple")') == 1


def test_the_row_shapes_no_longer_have_a_loop_each() -> None:
    """The inversion: one damage loop, where the entry reproduced two."""
    tree = ast.parse(_source("program", "compile.py"))
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "add_engine_result"
    )
    loops = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.For)
        and "damage_events" in ast.dump(node.iter)
        and "damage_events_tuple" not in ast.dump(node.iter)
    ]
    assert len(loops) == 1


def test_the_one_loop_ends_in_the_one_constructor() -> None:
    """The half S4 did close, asserted so the entry cannot overstate itself."""
    tree = ast.parse(_source("program", "compile.py"))
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "add_engine_result"
    )
    builders = {
        node.func.id
        for node in ast.walk(function)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "compiled_damage_action" in builders


# --- the consumption half S10 closed -----------------------------------------


def test_the_ranking_surface_rebuilds_its_operand_from_the_payloads_entry() -> None:
    """The half that was implementable as cleanup, asserted as closed."""
    assert "published_quantity(dispositions, path, value" in _source("bis.py")


def test_and_nothing_in_src_still_produces_a_withheld_quantity() -> None:
    """The half that is not: no producer, so the backstop injects its member."""
    producers = {
        path.relative_to(SRC).as_posix()
        for path in sorted(SRC.rglob("*.py"))
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Withheld"
    }
    assert producers <= {"ability_spec.py", "program/views/__init__.py"}


# --- the bit-exact clause's scenario set -------------------------------------


def test_the_exact_baseline_holds_the_derived_scenario_set() -> None:
    """R-12's set, read off the committed file rather than described.

    A superset now rather than an equality, and the four extra members are
    named in the assertion below rather than left as slack: R-12's coverage
    guarantee is that every ``damage_modifier`` producer has a covering
    scenario, which a superset keeps, and the bench rosters are the four
    Phase 4's criterion 14 names.

    Less a scenario a committed allowlist declares this baseline does not
    hold yet: a covering scenario lands as its own act and the capture is
    the integration agent's next commit (R-17, R-32, umbrella Amendment L
    Ruling 2), so between the two the file legitimately holds one fewer.
    """
    import json as _json

    from scripts.golden_snapshot import COUPLED_SCENARIOS

    from tests.test_golden_snapshot import declared_exact_new_scenarios

    exact = _json.loads(
        (ROOT / "scripts" / "golden_coupled_exact.json").read_text(encoding="utf-8")
    )
    assert {scenario.name for scenario in COUPLED_SCENARIOS} <= (
        set(exact["coupled_scenarios"]) | declared_exact_new_scenarios()
    )


def test_every_bench_scenario_is_in_the_exact_baseline() -> None:
    """The row's reproducer, inverted: the two sets now meet, exactly.

    The entry read "the criterion names a set the instrument does not hold",
    as a set operation over an empty intersection.  The instrument holds it:
    the exact capture is R-12's coupled set plus the four bench rosters, and
    nothing else -- so the criterion's sentence is dischargeable against the
    file it cites, and the exact baseline has not become a place scenarios
    accumulate.

    Stated as two containments rather than one equality, because a covering
    scenario declared but not yet captured is the one legal gap between them
    (see the test above).  The half that carries the row's own claim -- the
    file holds nothing the harness does not derive -- is unweakened.
    """
    import json as _json

    from scripts.bench_coupled_optimizer import SCENARIOS
    from scripts.golden_snapshot import COUPLED_SCENARIOS

    from tests.test_golden_snapshot import declared_exact_new_scenarios

    exact = _json.loads(
        (ROOT / "scripts" / "golden_coupled_exact.json").read_text(encoding="utf-8")
    )
    held = set(exact["coupled_scenarios"])
    derived = {scenario.name for scenario in COUPLED_SCENARIOS} | set(SCENARIOS)
    assert set(SCENARIOS) <= held
    assert len(SCENARIOS) == 4
    assert held <= derived
    assert derived - held <= declared_exact_new_scenarios()


def test_the_rounded_baseline_did_not_gain_them() -> None:
    """The half that keeps this from being a jurisdiction change.

    R-01 row 3 compares the *rounded* coupled baseline, and adding four
    rosters to it would have grown the surface every future slice is graded
    against.  The bit-exactness assertion is what criterion 14 asks for, so
    only the exact capture moved.
    """
    import json as _json

    from scripts.bench_coupled_optimizer import SCENARIOS

    rounded = _json.loads(
        (ROOT / "scripts" / "golden_coupled_baseline.json").read_text(encoding="utf-8")
    )
    assert not set(rounded["coupled_scenarios"]) & set(SCENARIOS)


def test_the_exact_baseline_is_unrounded_where_the_other_one_rounds() -> None:
    """The half that *is* discharged: repr(float), not two decimals (R-13)."""
    import json as _json

    exact = _json.loads(
        (ROOT / "scripts" / "golden_coupled_exact.json").read_text(encoding="utf-8")
    )
    assert exact["metadata"]["exact"] is True


# --- the fallback reason nothing publishes -----------------------------------


def test_a_src_call_site_reads_the_rung_reason() -> None:
    """The entry's reproducer, inverted, as a shape rather than as a grep.

    It read: ``program/rung.reason_of`` exists so a fallback can name which
    declaration refused, and nothing in ``src/`` calls it -- the recording
    site kept ``counter_label(decision)`` and dropped the object.  The reason
    now travels the whole way: ``counter_entry`` reads it and the two
    recording sites hand it to the sink, so a fallback in a published report
    names the declaration that caused it.
    """
    readers = set()
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if path.name == "rung.py":
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in {"reason_of", "counter_entry"}
            ):
                readers.add(path.relative_to(SRC).as_posix())
    assert readers == {"participant_timeline.py"}, readers


def test_the_counter_sink_declares_the_field_a_reason_goes_in() -> None:
    """The other half, inverted: the sink has somewhere to put the cause.

    ``rungs`` is keyed by one of four published labels and cannot hold a
    sentence, which is why "the reason has nowhere to go" was true rather
    than careless.  ``rung_receipts`` is that somewhere, and it is asserted
    as an exact field set so a seventh member is a decision somebody makes
    rather than one that arrives.
    """
    from src.calculator.work_counters import WorkCounterSink

    declared = set(WorkCounterSink.__annotations__)
    assert declared == {
        "measured_proposals",
        "score_memo_misses",
        "pair_run_fight_calls",
        "walk_invocations",
        "rungs",
        "rung_receipts",
    }


def test_the_published_report_carries_the_causes_beside_the_histogram() -> None:
    """And it reaches a reader: the harness publishes the counter.

    A field on a protocol nothing serialized would be the same defect one
    layer further out.  The bench report is where a rung is read, so this
    asserts the receipts ride beside the histogram in the shape ``as_dict``
    publishes.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "bench_coupled_optimizer", ROOT / "scripts" / "bench_coupled_optimizer.py"
    )
    bench = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("bench_coupled_optimizer", bench)
    spec.loader.exec_module(bench)

    from src.calculator.program.rung import ReceiptWalk, counter_entry
    from src.calculator.work_counters import record_rung

    counters = bench.WorkCounters()
    record_rung(counters, *counter_entry(ReceiptWalk("Imperial Mandate - Command")))
    published = counters.as_dict()
    assert published["rungs"] == {"receipt_walk_candidate": 1}
    assert published["rung_receipts"] == {"Imperial Mandate - Command": 1}


# --- R-01 row 1's pinned half ------------------------------------------------


def test_the_pinned_collected_count_moved_off_the_number_the_entry_named() -> None:
    """The inversion of that entry's reproducer, kept rather than deleted.

    While the entry stood, this asserted ``tests.collected`` was still the
    stale ``pinned_value`` -- the lane's way of keeping a gap it could not
    close visible. The Phase 4 boundary integration re-pinned the count, so
    the assertion is inverted here in the same commit that retired the entry:
    the pin is no longer the number the entry named, and the retired record
    still carries what it was. Deleting the test would have closed the entry
    by forgetting it.
    """
    entry = next(
        record
        for record in receipt()["retired"]
        if record["id"]
        == "r01_row_1s_pinned_collected_count_is_the_integration_agents_and_is_stale"
    )
    fingerprints = json.loads(
        (ROOT / "docs" / "receipts" / "campaign-fingerprints.json").read_text(
            encoding="utf-8"
        )
    )
    tests_block = fingerprints["tests"]
    assert tests_block["collected"] != entry["pinned_value"]
    # The pin moves again whenever a pass declares new node ids, and each move
    # carries its own cause on the receipt.  What this asserts is the property
    # the entry was about -- the pin is not the stale number -- plus the rule
    # that every later move says why, so "the pin is the integration agent's"
    # cannot decay back into "the pin is nobody's".
    assert tests_block["collected"] >= entry["re_pinned_value"]
    if tests_block["collected"] != entry["re_pinned_value"]:
        assert tests_block["re_pinned"]["cause"].strip()
        assert tests_block["re_pinned"]["to"] == tests_block["collected"]
    # The half of the row that was live all along: a test quietly becoming a
    # skip still fails, because both of these are pinned at zero and still are.
    assert tests_block["skipped"] == 0
    assert tests_block["xfailed"] == 0
