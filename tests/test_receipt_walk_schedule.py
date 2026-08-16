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


def test_the_priced_row_predicate_reproduces_the_fights_own_total() -> None:
    """The whole triage turns on "a row a total holds", so it is checked exactly.

    Amendment O, Ruling 1 distinguishes a row a family authors from a row that
    publishes a difference and is summed into no total.  If that predicate
    were a heuristic, every class below it would be one.  It is not: summing
    ``total_damage`` over exactly the rows :func:`priced_rows` returns
    reproduces the fight's own ``total_damage``, so a row the predicate drops
    is a row the total genuinely does not hold.  The probe deliberately holds
    one informational-row item (Sundered Sky), one execute (The Collector) and
    one heal row (Bloodthirster's lifesteal), which are the three shapes that
    would otherwise be counted as authored.
    """
    champions = receipt_walk_schedule.golden_snapshot.fetch_champion_data()
    by_name = {
        data["name"]: data
        for data in receipt_walk_schedule.golden_snapshot.fetch_item_data().values()
    }
    held = ["Sundered Sky", "The Collector", "Bloodthirster"]
    result = receipt_walk_schedule.golden_snapshot._run_fight(  # noqa: SLF001
        champions["Caitlyn"],
        receipt_walk_schedule.PROBE_LEVEL,
        [by_name[name] for name in held],
        auto_attack_uptime=1.0,
        one_rotation=False,
    )
    priced = receipt_walk_schedule.priced_rows(result)
    assert {"sundered_sky", "execute", "heal_lifesteal"}.isdisjoint(priced)
    assert sum(
        float(result["breakdown"][key]["total_damage"]) for key in priced
    ) == pytest.approx(float(result["total_damage"]), rel=0, abs=1e-9)


def test_every_open_row_carries_a_triage_class_that_was_measured() -> None:
    """Amendment O, Ruling 2: measured once, for every row, not one halt at a time.

    The class is checked against the measurement rather than against a list of
    families, so a family whose declarations start authoring a row -- or stop
    -- re-derives its class on the same commit.  The three classes are
    asserted to partition the open rows, because a row with no class is
    exactly the row the next retirement round would walk into blind.
    """
    block = schedule()
    by_class = block["triage_by_class"]
    assert set(by_class) <= {"a", "b", "c"}
    assert sorted(family for names in by_class.values() for family in names) == sorted(
        block["families"]
    )
    for family, entry in block["families"].items():
        triage = entry["triage"]
        assert triage["class"] in {"a", "b", "c"}, family
        authored = triage["authored_pair_rows"]
        assert (triage["class"] == "a") is bool(authored), family
        if triage["class"] == "b":
            assert set(triage["declared_subjects"]) == {"holder"}, family
        if triage["class"] == "c":
            assert set(triage["declared_subjects"]) != {"holder"}, family
            assert "named" in triage["walk_side_delivery_term"], family


def test_a_class_c_row_with_no_named_delivery_term_is_named_as_a_stop() -> None:
    """Ruling 2's stop clause, as a derivation rather than as a sentence.

    A class-(c) row may not retire until somebody names its walk-side
    delivery term, and a lane may not invent one.  The stopped list is
    therefore derived from the per-row term check, and it is asserted equal to
    it rather than pinned to today's membership -- naming a term for one of
    these rows is the debt getting startable, and a test that went red when
    its subject improved would pin the gap instead of the rule (D-92).
    """
    block = schedule()
    stopped = block["triage_rows_stopping_the_next_retirement_round"]
    assert stopped == sorted(
        family
        for family, entry in block["families"].items()
        if entry["triage"]["class"] == "c"
        and not entry["triage"]["walk_side_delivery_term"]["named"]
    )
    for family in stopped:
        term = block["families"][family]["triage"]["walk_side_delivery_term"]
        assert "no walk-side delivery term" in term["why"], family


def test_a_reclassified_row_is_closed_in_the_tree_and_not_only_on_paper() -> None:
    """Amendment O, Ruling 1 closes a row; the tree has to agree it is closed.

    A ruling names a family and this file records the name.  What it may not
    do is let the name outlive the closure, so three facts are checked against
    the tree rather than against the receipt that wrote them: the family no
    longer declares the receipt-walk lane, no interpreter serves one -- which
    would make this a retirement wearing a reclassification's name -- and the
    frontier no longer defers the row.
    """
    block = schedule()
    closed = block["closed_by_authority_reclassification"]
    assert closed, "the reclassification record is empty; Ruling 1 named a family"
    for family, entry in closed.items():
        assert family not in block["families"], family
        assert family not in deferred_families(), family
        member = next(
            candidate
            for candidate in interpreters.RuleFamily
            if candidate.value == family
        )
        assert interpreters.EngineLane.RECEIPT_WALK not in interpreters.lanes_for(
            member
        ), family
        assert (
            member,
            interpreters.EngineLane.RECEIPT_WALK,
        ) not in interpreters.INTERPRETERS, family
        assert entry["closed_as"] == "not_a_gap", family
        assert entry["authored_pair_rows"] == [], family
        assert set(entry["declared_subjects"]) == {"holder"}, family


def test_the_machine_check_reopens_a_closed_row_on_an_authored_row() -> None:
    """R-05, on the clause that makes the closure conditional rather than final.

    Ruling 1 closes the row *with a machine check*: the zero-authored-rows
    property is re-measured on every run and the row reopens if a future
    mechanic of the family ever authors one.  A check that could not go red on
    that event would be a closure dressed as a condition, so the event is
    injected -- one of the family's own owners is made to author a row -- and
    the gate is asserted to fail naming the reclassification block.
    """
    committed = schedule()
    bare = receipt_walk_schedule._probe_rows  # noqa: SLF001

    def authoring(champion, items):
        rows = bare(champion, items)
        return rows | {"a_row_this_family_did_not_used_to_author"} if items else rows

    receipt_walk_schedule._probe_rows = authoring  # noqa: SLF001
    try:
        failures = receipt_walk_schedule.check(committed)
    finally:
        receipt_walk_schedule._probe_rows = bare  # noqa: SLF001
    assert any(
        "closed_by_authority_reclassification" in failure for failure in failures
    ), failures


def test_the_triage_says_it_pays_nothing() -> None:
    """Measuring a debt is the half that can quietly become discounting it."""
    block = schedule()
    assert "It retires nothing and it budgets nothing" in (
        block["what_the_triage_does_not_do"]
    )
    assert "measured" in block["triage_rule"]


@pytest.mark.parametrize(
    "mutation,expected",
    [
        ("drop_a_family", "different set of families"),
        ("shrink_a_population", "committed row differs from derived"),
        ("respell_a_corrected_lane", "committed value differs from derived"),
        ("claim_an_unperformed_act", "committed value differs from derived"),
        ("respell_a_triage_class", "committed row differs from derived"),
        ("unstop_a_stopped_row", "committed value differs from derived"),
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
    elif mutation == "respell_a_triage_class":
        family = sorted(mutated["families"])[0]
        mutated["families"][family]["triage"]["class"] = "a"
    elif mutation == "unstop_a_stopped_row":
        mutated["triage_rows_stopping_the_next_retirement_round"] = []
    else:
        mutated["slices_whose_retiring_lane_amendment_k_corrects"] = []
    failures = receipt_walk_schedule.check(mutated)
    assert any(expected in failure for failure in failures), failures
