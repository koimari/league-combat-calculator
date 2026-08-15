"""Every open debt is docketed, and every docket row is startable.

`standing-dissent-adjudications.json` made the blocking population countable
and gave each member a remedy in words.  The sign-off review found what words
do not do: twenty-two debts each naming "a fresh whole-series
re-adjudication" and not one of them handed to anybody, because the
R-15/R-18 amendment's clause 3 makes a re-run unwritable until its superseding
receipt cites *the specific defect in the brief it replaces*, and nothing had
named one.

This gate holds the join in both directions.  A debt with no docket row fails,
so the docket cannot fall behind the population; a docket row for a dissent
that has cleared fails, so it cannot outlive it.  And every row must carry
what a re-adjudication needs to start — the defect, the measurement behind it,
and the brief — with the last assertion the load-bearing one: a cluster whose
remedy is a ruling rather than an investigation must name the owed-ruling row
that carries it, so "this one needs a decision" cannot become the place a debt
goes to rest.

A worked docket needs a third remedy, and the 2026-08-15 re-adjudication is
what needed it.  Clause 1 ran on the cast-timeline cluster, was well posed,
and cleared one of its three leaves: the whole-series computation certified
neither side on the other two.  That row owes clause 2 — the producing
correction re-opened as a ruled ``src/`` slice — and it owes it *instead of*
another investigation, because clause 3 requires a re-run to cite a defect in
the brief it replaces and this docket's brief has none.  Written as an
investigation it would say a re-run is owed, which is the oracle shopping
clause 3 exists to make unwritable; written as a ruling it would name a
decision nobody owes.  So :func:`disposition` reads the remedy off the keys a
row carries, and a row claiming two remedies is the failure it refuses.

The other half of a worked docket is closure.  A cluster every one of whose
receipts has cleared cannot stay in ``clusters`` — the join above would fail
on it — and deleting it would cut the debt from the answer that discharged it.
It moves to ``cleared`` instead, and
:func:`test_a_cleared_cluster_was_answered_rather_than_moved` is what stops
that list from becoming the resting place a routed debt was already refused:
every receipt in it is joined, through the adjudication ledger, to what
answered it.

There are two such joins, because the campaign has two instruments for
answering a question.  A superseded receipt joins to a filed receipt that
exists, adjudicates the *same leaf*, and carries ``new_value_correct``.  A
receipt answered by a **ruling** joins to the ruling instead — the row it
closed in ``rulings-owed.json`` and the amendment recorded verbatim in the
umbrella — and it has to, because the whole content of a routed row is that
no investigation can clear it: demanding a superseding receipt there would
demand exactly the oracle shopping clause 3 makes unwritable.
:func:`closure_mechanism` is where the two-way split lives, so it cannot drift
into prose and so R-05's negative can refuse the third state — a row that left
``clusters`` because somebody moved it.

The coverage-prose row is the one that closed that second way, and it is why
:func:`_row` reads both lists: a measurement recomputed by id must follow the
row that carries it, or the check stops running on the commit that answers the
question it was measured for.  Its measurement is recomputed here.
That row's whole content was that its brief has no defect to name, so what a
lane could still measure was the *shape of the population* its single receipt
belongs to: one predicate produces the string, the payload publishes it at
four addresses in each of six scenarios, and twenty-four receipts adjudicate
the identical pair of strings.  Which way they went is the fact the ruling
read, and a number nobody recomputes is the prose this docket exists
to stop being — so :func:`test_the_sibling_census_reproduces` counts them
from the receipts, and its sibling refuses a census that has silently become
an average over two different questions.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RECEIPTS = ROOT / "docs" / "receipts"
DOCKET = RECEIPTS / "standing-dissent-docket.json"
ADJUDICATIONS = RECEIPTS / "standing-dissent-adjudications.json"
RULINGS = RECEIPTS / "rulings-owed.json"
UMBRELLA = ROOT / "docs" / "plans" / "2026-08-08-silent-failure-campaign.md"

#: What every cluster carries, whichever way it clears.  ``if_sustained`` is
#: here because clause 2 is the half a docket most easily loses: a
#: re-adjudication with no stated consequence for sustaining the dissent is a
#: re-run whose only possible outcome is closure.
REQUIRED = (
    "id",
    "receipts",
    "series",
    "producing_correction",
    "defect_in_the_prior_brief",
    "how_the_defect_was_measured",
    "remedy",
    "if_sustained",
)

#: What a cluster clause 1 clears carries on top: the brief, and the receipts
#: the verdicts will supersede.  A cluster routed to a ruling carries neither
#: and must not — writing a brief for a question no investigator may be asked
#: is how a routed debt quietly becomes an investigation anyway.
REQUIRED_INVESTIGATED = (
    "brief_for_the_re_adjudication",
    "supersedes_on_filing",
)

#: The facts of the *question* the 2026-08-14 R-18 amendment lets a brief
#: carry, and the one sentence that keeps the answer out of it.
REQUIRED_BRIEF = (
    "unit",
    "scenario_parameters",
    "question",
    "position_and_context_supplied",
    "sibling_facts_that_did_not_move",
    "what_the_brief_may_not_carry",
)

#: What a cluster whose clause-1 investigation has already RUN carries: the
#: filing, and what the ``src/`` slice clause 2 owes inherits from it.  It
#: carries no brief and no ``supersedes_on_filing``, and that absence is the
#: rule rather than an omission — a row that has been investigated and still
#: dockets debts owes a correction, and offering a second brief for the same
#: question is clause 3's oracle shopping with a docket row behind it.
REQUIRED_RE_ADJUDICATED = (
    "re_adjudication_filed",
    "what_the_slice_inherits",
)

#: What the filing itself must say.  ``what_did_not`` is the load-bearing one:
#: a filing that records only what it cleared is a pass reporting its own
#: successes, and the receipts that still block are the reason the row stays.
REQUIRED_FILING = (
    "dated",
    "receipts",
    "unit",
    "what_it_returned",
    "what_cleared",
    "what_did_not",
)

#: The three remedies, keyed by the field that carries each.  A row owes
#: exactly one; :func:`disposition` is where that is enforced.
REMEDY_KEYS = {
    "whole_series_re_adjudication": "supersedes_on_filing",
    "owed_ruling": "owed_ruling_id",
    "owed_src_correction": "re_adjudication_filed",
}


def disposition(cluster: dict) -> str:
    """Which remedy a row owes, read off the keys it carries.

    A pure function over one row — the seam R-05 asks for, and the reason the
    three-way split cannot drift into prose.  Claiming two remedies is the
    failure it exists to catch: a row that has been investigated *and* offers a
    brief is a second run of a question clause 3 permits nobody to re-ask.
    """
    live = sorted(name for name, key in REMEDY_KEYS.items() if cluster.get(key))
    if len(live) != 1:
        raise AssertionError(
            f"{cluster.get('id')} owes {live or 'no'} remedy; exactly one is a row"
        )
    return live[0]


@pytest.fixture(name="scan", scope="module")
def _scan():
    """The instrument, imported by path exactly as its siblings are."""
    spec = importlib.util.spec_from_file_location(
        "standing_dissent_scan", ROOT / "scripts" / "standing_dissent_scan.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("standing_dissent_scan", module)
    spec.loader.exec_module(module)
    return module


def _docket() -> dict:
    return json.loads(DOCKET.read_text(encoding="utf-8"))


def _clusters() -> list[dict]:
    return _docket()["clusters"]


def _row(cluster_id: str) -> dict:
    """One docket row wherever it lives — open in ``clusters`` or ``cleared``.

    A row that closes moves lists and keeps everything it carried, so a
    measurement recomputed by id must follow it.  Reading ``clusters`` alone
    would turn the census below into a ``StopIteration`` on the commit that
    answers the question it was measured for — a check that stops running at
    the moment it stops being convenient.
    """
    body = _docket()
    rows = list(body["clusters"]) + list(body.get("cleared", ()))
    return next(row for row in rows if row["id"] == cluster_id)


def open_debts() -> set[str]:
    """The receipts the adjudication ledger classes as open debts."""
    rows = json.loads(ADJUDICATIONS.read_text(encoding="utf-8"))["adjudications"]
    return {row["receipt"] for row in rows if row["kind"] == "open_debt"}


def docketed() -> list[str]:
    """Every receipt a cluster claims, as a list so duplicates are visible."""
    return [name for cluster in _clusters() for name in cluster["receipts"]]


def undocketed(debts: set[str], claimed: list[str]) -> tuple[str, ...]:
    """The check itself, as a pure function — the seam R-05 requires."""
    return tuple(sorted(debts - set(claimed)))


def test_the_docket_declares_what_it_is_and_what_gates_it() -> None:
    block = _docket()
    assert block["artifact"] == "standing_dissent_docket"
    assert block["gate"] == "tests/test_standing_dissent_docket.py"
    assert block["rule"].strip()
    assert block["what_this_file_does_not_do"].strip()
    assert block["why_a_lane_may_write_this_and_not_the_verdict"].strip()


def test_every_open_debt_is_docketed_exactly_once() -> None:
    """The join forwards: the docket cannot fall behind the population."""
    claimed = docketed()
    assert undocketed(open_debts(), claimed) == ()
    assert len(claimed) == len(set(claimed)), "a receipt is docketed twice"


def test_no_docket_row_outlives_its_dissent() -> None:
    """The join backwards: a cleared dissent may not keep a docket row."""
    assert set(docketed()) <= open_debts()


def test_an_undocketed_debt_turns_the_check_red() -> None:
    """The permanent negative (R-05): the check can fail on demand."""
    assert undocketed({"oracle-fabricated.json"}, docketed()) == (
        "oracle-fabricated.json",
    )


@pytest.mark.parametrize("cluster", _clusters(), ids=[c["id"] for c in _clusters()])
def test_every_cluster_is_startable(cluster) -> None:
    """A row somebody can begin, rather than a remedy somebody can agree with."""
    for key in REQUIRED:
        assert cluster[key], f"{cluster['id']} is missing {key}"
    assert len(cluster["defect_in_the_prior_brief"].split()) >= 30, cluster["id"]
    assert cluster["how_the_defect_was_measured"]["instrument"].strip()
    route = disposition(cluster)
    if route == "owed_ruling":
        for key in REQUIRED_INVESTIGATED + REQUIRED_RE_ADJUDICATED:
            assert not cluster.get(key), f"{cluster['id']} is routed to a ruling"
        return
    if route == "owed_src_correction":
        for key in REQUIRED_INVESTIGATED:
            assert not cluster.get(key), f"{cluster['id']} has been investigated"
        for key in REQUIRED_RE_ADJUDICATED:
            assert cluster[key], f"{cluster['id']} is missing {key}"
        for key in REQUIRED_FILING:
            assert cluster["re_adjudication_filed"][key], cluster["id"]
        return
    for key in REQUIRED_INVESTIGATED:
        assert cluster[key], f"{cluster['id']} is missing {key}"
    for key in REQUIRED_BRIEF:
        assert cluster["brief_for_the_re_adjudication"][key].strip(), cluster["id"]


def test_an_investigated_cluster_files_receipts_that_exist_and_agree() -> None:
    """Clause 1 discharged is a claim about files, so it is read off them.

    The filing names its receipts with the verdict each returned.  Every one
    must exist and carry that verdict — otherwise "the investigation ran" is
    the same unverifiable sentence about the past that the docket replaced,
    one layer further in.  And at least one must be adverse: a filing where
    every verdict is ``new_value_correct`` cleared its cluster, and a cleared
    cluster does not stay in ``clusters``.

    A loop rather than a parametrisation, here and below, because an empty
    parameter set is a *skip* and R-01 row 1 counts those — a docket with no
    row of this shape must read as a check with nothing to say, not as a
    check that stopped running.
    """
    for cluster in _clusters():
        if disposition(cluster) != "owed_src_correction":
            continue
        filed = cluster["re_adjudication_filed"]["receipts"]
        for name, verdict in filed.items():
            body = json.loads((RECEIPTS / name).read_text(encoding="utf-8"))
            assert body["verdict"] == verdict, name
            assert body.get("superseded_brief_defect") or body.get("supersedes"), name
        adverse = {n for n, verdict in filed.items() if verdict != "new_value_correct"}
        assert adverse, cluster["id"]
        assert adverse <= set(cluster["receipts"]), cluster["id"]


@pytest.mark.parametrize("cluster", _clusters(), ids=[c["id"] for c in _clusters()])
def test_every_docketed_receipt_exists(cluster) -> None:
    for name in cluster["receipts"]:
        assert (RECEIPTS / name).exists(), name
    for name in cluster.get("supersedes_on_filing", ()):
        assert name in cluster["receipts"], name


@pytest.mark.parametrize("cluster", _clusters(), ids=[c["id"] for c in _clusters()])
def test_a_cluster_answered_by_a_ruling_names_the_owed_row(cluster) -> None:
    """The load-bearing one: "it needs a decision" must point at the decision.

    A cluster that routes to a ruling files no superseding receipt, so the
    ``supersedes_on_filing`` join above cannot see it.  Without this, routing a
    debt to a ruling would be the one way to leave it with no forward
    reference at all — which is the resting place the adjudication ledger's
    own rule refuses.

    The join ranges over ``owed`` *and* ``answered``, for the reason
    ``test_rulings_owed`` gives for the same widening: a row that closes moves
    lists rather than vanishing, and a join that reads only the open list
    would break on the commit that answers the question — reading as a
    dangling forward reference exactly when the reference finally resolves.
    An answered row is held to more, not less: it must name the amendment
    that answers it, and that amendment must be findable verbatim in the
    umbrella, so "answered" is a fact about a document rather than a claim.
    """
    if disposition(cluster) != "owed_ruling":
        assert "owed_ruling_id" not in cluster, cluster["id"]
        return
    rulings = json.loads(RULINGS.read_text(encoding="utf-8"))
    rows = {row["id"]: row for row in rulings["owed"] + rulings["answered"]}
    assert cluster["owed_ruling_id"] in rows, cluster["id"]
    row = rows[cluster["owed_ruling_id"]]
    if row in rulings["answered"]:
        assert row["amendment"] in UMBRELLA.read_text(encoding="utf-8"), row["id"]


def test_a_row_may_not_owe_two_remedies() -> None:
    """R-05's negative for the three-way split, at the pure function.

    The shape it refuses is the one clause 3 refuses: a cluster whose
    investigation has run, still offering a brief for the same question.  A
    row with no remedy at all fails the same way, because "docketed" would
    then mean nothing more than "listed".
    """
    investigated = {"id": "fabricated", "supersedes_on_filing": ["x.json"]}
    assert disposition(investigated) == "whole_series_re_adjudication"
    with pytest.raises(AssertionError):
        disposition(dict(investigated, re_adjudication_filed={"dated": "2026-01-01"}))
    with pytest.raises(AssertionError):
        disposition({"id": "fabricated"})


def closure_mechanism(name: str, ledger: dict) -> str:
    """Which instrument answered one cleared receipt, read off the ledger.

    Two and there is no third, because a docket row is answered by a receipt
    or by a ruling and *moved* by nothing.  ``supersession`` is a row in the
    ledger's ``cleared`` naming the receipt that discharged it;
    ``ruling`` is a live ``citation`` row naming the ruling that decides the
    leaf — the shape a routed cluster closes in, where no receipt supersedes
    the dissent and none may.  A pure function over the ledger, so R-05's
    negative needs no file on disk.
    """
    if any(row["receipt"] == name for row in ledger["cleared"]):
        return "supersession"
    live = {row["receipt"]: row for row in ledger["adjudications"]}
    if name in live and live[name]["kind"] == "citation":
        return "ruling"
    raise AssertionError(f"{name} is cleared and no ledger row says by what")


def test_a_cleared_cluster_was_answered_rather_than_moved(scan) -> None:
    """Closure is a join to an answer, never a row changing lists.

    ``cleared`` is the one list a debt can reach without an answer, so every
    receipt in it is followed through the adjudication ledger to what answered
    it.  A superseded receipt is followed to the receipt that discharged it:
    the same leaf address, ``new_value_correct``, and a file a reader can
    open.  A receipt answered by a *ruling* is followed to the ruling instead
    — the row it closed in ``rulings-owed``, and the amendment recorded
    verbatim in the umbrella — because a routed cluster's whole content is
    that no investigation can clear it, so demanding a superseding receipt
    here would demand the oracle shopping clause 3 forbids.  Without this the
    docket would close a debt by moving it, which is the deletion the ledger's
    own rule refuses wearing a different name.
    """
    ledger = json.loads(ADJUDICATIONS.read_text(encoding="utf-8"))
    answers = {row["receipt"]: row for row in ledger["cleared"]}
    rulings = json.loads(RULINGS.read_text(encoding="utf-8"))
    answered_rulings = {row["id"]: row for row in rulings["answered"]}
    umbrella = UMBRELLA.read_text(encoding="utf-8")
    debts = open_debts()
    for cluster in _docket().get("cleared", ()):
        closure = cluster["cleared"]
        assert closure["how_it_closed"].strip(), cluster["id"]
        for name in cluster["receipts"]:
            assert name not in debts, f"{name} is cleared and still an open debt"
            if closure_mechanism(name, ledger) == "ruling":
                assert cluster["owed_ruling_id"] in answered_rulings, cluster["id"]
                row = answered_rulings[cluster["owed_ruling_id"]]
                assert closure["amendment"] == row["amendment"], cluster["id"]
                assert row["amendment"] in umbrella, cluster["id"]
                gate, _, _rest = closure["the_source_assertion"].partition(" ")
                assert (ROOT / gate).exists(), gate
                continue
            row = answers[name]
            answer = RECEIPTS / row["cleared_by"]
            assert answer.exists(), row["cleared_by"]
            body = json.loads(answer.read_text(encoding="utf-8"))
            dissent = json.loads((RECEIPTS / name).read_text(encoding="utf-8"))
            assert body["verdict"] == "new_value_correct", row["cleared_by"]
            assert scan.leaf_address(body) == scan.leaf_address(dissent), name


def test_a_cleared_receipt_with_no_answer_anywhere_is_reported() -> None:
    """R-05 for the closure join, at the pure function.

    The shape it refuses is the one the docket's own rule refuses: a row that
    left ``clusters`` because somebody moved it.  Neither a superseding
    receipt nor a live citation is an answer that can be written by editing
    one list.
    """
    ledger = {
        "cleared": [{"receipt": "oracle-superseded.json"}],
        "adjudications": [
            {"receipt": "oracle-ruled.json", "kind": "citation"},
            {"receipt": "oracle-owing.json", "kind": "open_debt"},
        ],
    }
    assert closure_mechanism("oracle-superseded.json", ledger) == "supersession"
    assert closure_mechanism("oracle-ruled.json", ledger) == "ruling"
    with pytest.raises(AssertionError):
        closure_mechanism("oracle-owing.json", ledger)
    with pytest.raises(AssertionError):
        closure_mechanism("oracle-moved.json", ledger)


def test_the_recorded_counts_reproduce(scan) -> None:
    """A receipt that records a number nobody recomputes is prose."""
    recorded = _docket()["measured_on_the_commit_that_lands_this"]
    assert recorded["docketed"] == len(docketed()) == len(open_debts())
    assert recorded["clusters"] == len(_clusters())
    counted = Counter(disposition(cluster) for cluster in _clusters())
    assert recorded["remedy_kinds"] == {
        name: counted[name] for name in sorted(REMEDY_KEYS)
    }
    assert sum(counted.values()) == len(_clusters())
    assert scan.report()["by_kind"]["open_debt"] == len(open_debts())


def _reason_prose_receipts() -> list[dict]:
    """Every committed receipt adjudicating the all-defence coverage string.

    Found by the leaf they address rather than by a list, so a receipt filed
    later joins the census by existing.
    """
    bodies = []
    for path in sorted(RECEIPTS.glob("oracle-P3-3.8-leaf*.json")):
        body = json.loads(path.read_text(encoding="utf-8"))
        if str(body.get("leaf_path", "")).endswith("item_coverage[0]/reason"):
            bodies.append(body)
    return bodies


def test_the_sibling_census_reproduces() -> None:
    """The one measurement the coverage cluster carries, recomputed.

    A census recorded and never recomputed is the prose this docket exists
    to stop being.  It is also the fact that decides whether clause 2 may
    fire on this row at all, so it is the last thing that should be taken on
    the file's word.
    """
    census = _row("item_coverage_reason_prose")["the_sibling_census"]
    bodies = _reason_prose_receipts()
    counted = Counter(body["verdict"] for body in bodies)
    recorded = census["the_count"]
    assert recorded["receipts_on_the_identical_question"] == len(bodies)
    assert recorded["new_value_correct"] == counted["new_value_correct"]
    assert recorded["old_value_correct"] == counted["old_value_correct"]


def test_the_census_counts_one_question_and_not_several() -> None:
    """The count means nothing unless every receipt was asked the same thing.

    One predicate produces the string and the payload publishes it at four
    addresses per scenario, so all of them carry one ``(old_value,
    new_value)`` pair.  If a future edit gave the addresses different
    strings, the census would silently become an average over two questions
    and this is what refuses it.
    """
    pairs = {
        (body["old_value"], body["new_value"]) for body in _reason_prose_receipts()
    }
    assert len(pairs) == 1, f"the census spans {len(pairs)} distinct questions"
