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


def test_a_row_whose_route_is_not_the_pair_engine_is_routed_to_a_ruling() -> None:
    """Amendment F's named act does not describe every row, and this says so.

    A defence-resolver row says in its own words that a walk-lane interpreter
    would be a second producer of one number, which D-60 forbids.  A lane may
    measure that and may not settle it, so the row carries the owed ruling's
    id and that ruling is asserted to be really open.

    As above, the routed list is not asserted non-empty: the day the ruling
    lands and the rows gain a settled act is the day this gap closes, and it
    should close by the derivation changing rather than by a red test.
    """
    block = schedule()
    routed = block["slices_routed_to_an_owed_ruling"]
    owed = {
        row["id"] for row in json.loads(RULINGS.read_text(encoding="utf-8"))["owed"]
    }
    for family in routed:
        act = block["families"][family]["retiring_act"]
        assert act["settled"] is False
        assert act["routed_to"] == receipt_walk_schedule.OWED_RULING
        assert act["routed_to"] in owed
    for family, entry in block["families"].items():
        if family in routed:
            continue
        assert entry["retiring_act"]["settled"] is True
        assert entry["route_today"] == ["pair_engine"]


def test_the_schedule_retires_nothing() -> None:
    """Sizing a debt may not become paying it."""
    block = schedule()
    assert "no row here retires anything" in block["what_this_is_not"]
    assert "fourteen rows in, fourteen slices out" in block["what_this_is_not"]
    for entry in block["families"].values():
        assert "retired" not in entry


@pytest.mark.parametrize(
    "mutation,expected",
    [
        ("drop_a_family", "different set of families"),
        ("shrink_a_population", "committed row differs from derived"),
        ("resettle_a_routed_row", "committed value differs from derived"),
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
    else:
        mutated["slices_routed_to_an_owed_ruling"] = []
    failures = receipt_walk_schedule.check(mutated)
    assert any(expected in failure for failure in failures), failures
