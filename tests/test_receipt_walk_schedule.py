"""The gate over counter 4's fourteen deferrals, sized as slices.

Sizing a debt is the half that can quietly become shrinking it, in three ways
this file makes loud.

The slice set can drift from the deferral rows it sizes -- a scheduled slice
that outlives its deferral reads as work still owed when it is not, and a
deferral with no scheduled slice is the debt going unread under a file that
says it is sized.  A population can stop being the committed one, which is
exactly what R-20's second half forbids: a population measured after the fact
measures the fix rather than predicting it.  And a schedule can start
retiring things -- by registering an interpreter that changes nothing the walk
prices, or by handing a row an act nobody ruled -- so the artifact says in its
own words that it retires nothing, and the row set here is asserted equal to
the frontier's rather than to anything this file chose.

R-05: the last test is the red this gate reproduces on demand, through the
seam ``check()`` takes.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import receipt_walk_schedule  # noqa: E402  pylint: disable=wrong-import-position
from calculator import interpreters  # noqa: E402  pylint: disable=wrong-import-position

SCHEDULE = ROOT / "docs" / "receipts" / "receipt-walk-retirement-schedule.json"
FRONTIER = ROOT / "docs" / "behavior-frontier.json"
RULINGS = ROOT / "docs" / "receipts" / "rulings-owed.json"


def schedule() -> dict:
    """The committed artifact this file is the gate for."""
    return json.loads(SCHEDULE.read_text(encoding="utf-8"))


def deferred_families() -> set[str]:
    """The frontier's own receipt-walk deferral rows, by family."""
    rows = json.loads(FRONTIER.read_text(encoding="utf-8"))["counters"]["counter_4"][
        "deferrals"
    ]["rows"]
    return {
        key.partition("/")[0]
        for key in rows
        if key.partition("/")[2] == receipt_walk_schedule.LANE
    }


def test_the_schedule_declares_what_it_is_and_what_gates_it() -> None:
    block = schedule()
    assert block["artifact"] == "receipt_walk_retirement_schedule"
    assert block["gate"] == "tests/test_receipt_walk_schedule.py"


def test_the_committed_schedule_matches_the_tree() -> None:
    """The whole instrument, run as the gate a reader would run."""
    assert receipt_walk_schedule.check() == []


def test_one_slice_per_deferral_row_and_not_one_more() -> None:
    """Fourteen rows in, fourteen slices out -- sizing is not re-scoping."""
    assert set(schedule()["families"]) == deferred_families()
    assert schedule()["scheduled_slices"] == len(deferred_families())


def test_every_slice_declares_a_population_before_anything_is_edited() -> None:
    """R-20's second half: the line, and a population that is not empty prose."""
    for family, entry in schedule()["families"].items():
        line = entry["expected_qualifying_occurrences"]
        assert line.startswith("Expected qualifying occurrences:"), family
        covering = entry["covering_coupled_scenarios"]
        assert entry["coupled_baseline_is_blind_to_this_family"] == (not covering)
        assert set(entry["population_by_scenario"]) == set(covering)
        assert entry["population_total"] == sum(
            entry["population_by_scenario"].values()
        )


def test_a_blind_family_says_it_owes_a_gate_rather_than_reading_as_clean() -> None:
    """An empty population is the sharpest thing here and the easiest to misread.

    A family with no committed coupled scenario putting one of its owners on a
    participant gives its retiring slice no roster-path signal at all.  Read
    carelessly that is "zero expected occurrences", which is the shape of a
    clean bill; the row has to say the other thing.

    The list is deliberately not asserted non-empty.  A scenario that covers
    one of these families is the gap getting smaller, and a test that goes red
    when its subject improves is a test that pins the gap rather than the
    rule -- which is D-92's argument, applied to this file.
    """
    blind = schedule()["families_with_no_covering_coupled_scenario"]
    for family in blind:
        line = schedule()["families"][family]["expected_qualifying_occurrences"]
        assert "no roster-path signal" in line, family
        assert "D-93" in line, family


def test_every_slice_names_an_interpreter_module_that_exists() -> None:
    """The file the retiring act would land in, checked to be a real one."""
    for family, entry in schedule()["families"].items():
        assert (ROOT / entry["interpreter_module"]).exists(), family


def test_every_declared_owner_and_rule_comes_from_the_catalog() -> None:
    """A population enumerated from a registry, not from a typed list."""
    catalog = receipt_walk_schedule.owners_by_family()
    for family, entry in schedule()["families"].items():
        assert entry["owners"] == sorted(catalog.get(family, {}))
        assert entry["declared_rules"] == sorted(
            mechanic for ids in catalog.get(family, {}).values() for mechanic in ids
        )


def test_every_rows_retiring_act_names_the_lane_that_row_declares() -> None:
    """Amendment K's ruling, as the derivation rather than as a sentence.

    Amendment F named one act and spelled it with one lane, which is true of
    the rows the pair engine feeds and named, for the rest, the second
    producer of one number D-60 forbids.  Amendment K rules the act per lane:
    a per-family interpreter in the lane the row itself declares.  So the act
    is checked against ``via`` row by row rather than against a family list --
    a row that re-declares its route must re-derive its act on the same
    commit, which is the property a typed list would lose.

    The corrected list is deliberately not asserted non-empty.  The day a
    family's declared route changes is the day this list moves, and a test
    that pins the current split would go red when its subject changes rather
    than when the rule breaks (D-92).
    """
    block = schedule()
    corrected = block["slices_whose_retiring_lane_amendment_k_corrects"]
    answered = {
        row["id"] for row in json.loads(RULINGS.read_text(encoding="utf-8"))["answered"]
    }
    assert receipt_walk_schedule.RULING in answered
    for family, entry in block["families"].items():
        act = entry["retiring_act"]
        assert act["ruled_by"] == receipt_walk_schedule.RULING, family
        if entry["route_today"] == [receipt_walk_schedule.PAIR_ENGINE]:
            assert family not in corrected
            assert act["retiring_lane"] == [receipt_walk_schedule.LANE], family
        else:
            assert family in corrected
            assert act["retiring_lane"] == entry["route_today"], family
    assert block["slices_whose_retiring_act_is_amendment_f_as_written"] == len(
        block["families"]
    ) - len(corrected)


def test_whether_a_ruled_act_is_already_performed_is_read_from_the_registry() -> None:
    """The published per-row fact has to be one that can come back false.

    ``settled`` was published on every row and was ``True`` on both branches
    of the derivation, so no tree could have made it say anything else -- the
    ruling it reported had settled every act at once, and a flag that cannot
    discriminate is a receipt column nobody can read a fact out of.  What
    replaces it is the half of the act Amendment K actually measured against
    the tree: whether ``INTERPRETERS`` already holds the row's ruled retiring
    key.  It is checked here against the registry directly rather than against
    the derivation that wrote it, so the two would have to agree by accident
    to pass.

    The split is deliberately not pinned to a number.  Registering one of the
    eleven is the debt getting smaller, and a test that goes red when its
    subject improves pins the gap rather than the rule (D-92).
    """
    block = schedule()
    performed = block["slices_whose_ruled_act_is_already_performed"]
    for family, entry in block["families"].items():
        act = entry["retiring_act"]
        registered = {
            lane.value
            for declared, lane in interpreters.INTERPRETERS
            if declared.value == family
        }
        expected = set(act["retiring_lane"]) <= registered
        assert act["already_performed"] is expected, family
        assert (family in performed) is expected, family
    assert performed == sorted(performed)
    assert (
        "never a count of debts paid" in block["what_already_performed_does_not_mean"]
    )


def test_the_schedule_retires_nothing() -> None:
    """Sizing a debt may not become paying it.

    The count it may not restate is no longer a literal.  A row leaves this
    file when the *tree* stops deferring it — the row set is read from the
    frontier's own deferrals — so a schedule that named its own size would go
    stale on the first retirement and would have to be re-typed by the lane
    that landed it, which is the shape D-40 forbids.  What is pinned instead
    is the sentence that says a departure is a landed slice and never a
    re-count.
    """
    block = schedule()
    assert "no row here retires anything" in block["what_this_is_not"]
    assert "one row out is one slice landed" in block["what_this_is_not"]
    assert "never one debt re-counted" in block["what_this_is_not"]
    for entry in block["families"].values():
        assert "retired" not in entry


@pytest.mark.parametrize(
    "mutation,expected",
    [
        ("drop_a_family", "different set of families"),
        ("shrink_a_population", "committed row differs from derived"),
        ("respell_a_corrected_lane", "committed value differs from derived"),
        ("claim_an_unperformed_act", "committed value differs from derived"),
    ],
)
def test_the_gate_has_a_red_it_can_reproduce(mutation: str, expected: str) -> None:
    """R-05: the check fails on command, through its own seam."""
    mutated = copy.deepcopy(schedule())
    if mutation == "drop_a_family":
        mutated["families"].pop(sorted(mutated["families"])[0])
    elif mutation == "shrink_a_population":
        family = next(
            name
            for name, entry in sorted(mutated["families"].items())
            if entry["population_total"]
        )
        mutated["families"][family]["population_total"] = 0
    elif mutation == "claim_an_unperformed_act":
        mutated["slices_whose_ruled_act_is_already_performed"] = sorted(
            mutated["families"]
        )
    else:
        mutated["slices_whose_retiring_lane_amendment_k_corrects"] = []
    failures = receipt_walk_schedule.check(mutated)
    assert any(expected in failure for failure in failures), failures
