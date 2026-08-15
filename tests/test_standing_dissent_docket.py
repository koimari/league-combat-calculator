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
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RECEIPTS = ROOT / "docs" / "receipts"
DOCKET = RECEIPTS / "standing-dissent-docket.json"
ADJUDICATIONS = RECEIPTS / "standing-dissent-adjudications.json"
RULINGS = RECEIPTS / "rulings-owed.json"

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
    if "owed_ruling_id" in cluster:
        for key in REQUIRED_INVESTIGATED:
            assert not cluster.get(key), f"{cluster['id']} is routed to a ruling"
        return
    for key in REQUIRED_INVESTIGATED:
        assert cluster[key], f"{cluster['id']} is missing {key}"
    for key in REQUIRED_BRIEF:
        assert cluster["brief_for_the_re_adjudication"][key].strip(), cluster["id"]


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
    """
    if cluster.get("supersedes_on_filing"):
        assert "owed_ruling_id" not in cluster, cluster["id"]
        return
    owed = json.loads(RULINGS.read_text(encoding="utf-8"))["owed"]
    assert cluster["owed_ruling_id"] in {row["id"] for row in owed}, cluster["id"]


def test_the_recorded_counts_reproduce(scan) -> None:
    """A receipt that records a number nobody recomputes is prose."""
    recorded = _docket()["measured_on_the_commit_that_lands_this"]
    assert recorded["docketed"] == len(docketed()) == len(open_debts())
    assert recorded["clusters"] == len(_clusters())
    kinds = recorded["remedy_kinds"]
    ruled = sum(1 for c in _clusters() if not c.get("supersedes_on_filing"))
    assert kinds["owed_ruling"] == ruled
    assert kinds["whole_series_re_adjudication"] == len(_clusters()) - ruled
    assert scan.report()["by_kind"]["open_debt"] == len(open_debts())
