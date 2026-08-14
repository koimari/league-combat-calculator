"""The rulings the campaign owes itself, as a list with a length.

Four open clauses are blocked on a decision no implementation lane may write,
and until now that fact lived in a report section, three escalation ledgers
and a note inside the verify ledger.  Scattered like that it reads as four
lanes each explaining why it stopped.  Collected it is a list, and a list can
be counted, gated and closed.

The load-bearing assertion here is the last one: every row names what a lane
may **not** do instead.  A blocked-on-a-ruling row without that half is where
work goes to stop, and "we are waiting on a decision" is the most comfortable
sentence in any campaign.  The rows are also joined to their measurement
artifacts, so a row cannot outlive the evidence it rests on.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RULINGS = ROOT / "docs" / "receipts" / "rulings-owed.json"
UMBRELLA = ROOT / "docs" / "plans" / "2026-08-08-silent-failure-campaign.md"

REQUIRED = (
    "id",
    "dated",
    "blocks",
    "measurement_artifact",
    "question",
    "why_no_lane_may_answer_it",
    "what_a_lane_may_not_do_instead",
    "consequence_of_leaving_it_open",
)

#: What a row keeps once it is answered.  A closed row that dropped its
#: question would leave an amendment standing in the umbrella with nothing
#: saying what it answered — a conclusion whose question nobody can recover,
#: which is the shape this campaign exists to remove.
REQUIRED_ANSWERED = (
    "id",
    "dated",
    "answered_on",
    "recorded_in",
    "amendment",
    "the_ruling",
    "blocks",
    "measurement_artifact",
    "question",
    "what_the_ruling_unblocked",
)


def _block() -> dict:
    return json.loads(RULINGS.read_text(encoding="utf-8"))


def _owed() -> list[dict]:
    return _block()["owed"]


def _answered() -> list[dict]:
    return _block()["answered"]


def _every_row() -> list[dict]:
    """Owed and answered together — the population the joins range over.

    Parametrizing over ``_owed()`` alone made every join here vanish into an
    empty parameter set the moment the last row closed: a skip, which R-01
    row 1 counts, and a gate that stops reading the file it exists to read.
    A closed row is still joined to its measurement and still may not
    reappear as an open question, so both checks range over both lists.
    """
    return _owed() + _answered()


def test_the_artifact_declares_what_it_is_and_what_gates_it() -> None:
    block = _block()
    assert block["artifact"] == "rulings_owed"
    assert block["gate"] == "tests/test_rulings_owed.py"
    assert block["how_a_row_closes"].strip()
    assert block["why_a_lane_may_not_write_these"].strip()


def test_every_row_is_complete_and_ids_are_unique() -> None:
    ids = [row["id"] for row in _every_row()]
    assert len(ids) == len(set(ids))
    for row in _owed():
        for key in REQUIRED:
            assert row[key].strip(), f"{row['id']} is missing {key}"
    for row in _answered():
        for key in REQUIRED_ANSWERED:
            assert row[key].strip(), f"{row['id']} is missing {key}"


@pytest.mark.parametrize("row", _every_row(), ids=[row["id"] for row in _every_row()])
def test_every_row_points_at_a_measurement_that_exists(row) -> None:
    """A ruling request resting on nothing is an opinion with a filename."""
    path, _, _rest = row["measurement_artifact"].partition(",")
    assert (ROOT / path.strip()).exists(), row["id"]


def test_every_row_names_what_a_lane_may_not_do_instead() -> None:
    """The half that keeps 'blocked on a ruling' from being a resting place.

    A loop rather than a parametrization, because ``owed`` is empty whenever
    the campaign owes itself nothing and an empty parameter set is a *skip* —
    which R-01 row 1 counts, and which would turn a closed ledger into an
    unread one on the commit that closes it.
    """
    for row in _owed():
        forbidden = row["what_a_lane_may_not_do_instead"]
        assert len(forbidden.split()) >= 8, row["id"]
        assert forbidden != row["why_no_lane_may_answer_it"]


@pytest.mark.parametrize("row", _answered(), ids=[row["id"] for row in _answered()])
def test_an_answered_row_names_its_amendment_and_what_it_unblocked(row) -> None:
    """The closure rule: a row closes by a ruling somebody can open.

    Two halves, and the second is the one that keeps a closure honest.  The
    amendment must be findable in the umbrella verbatim, so "recorded" is a
    fact rather than a claim; and the row must say what the ruling
    *unblocked*, so a ruling that changed nothing is visible as one rather
    than reading like progress.
    """
    assert row["recorded_in"] == "docs/plans/2026-08-08-silent-failure-campaign.md"
    assert row["amendment"] in UMBRELLA.read_text(encoding="utf-8")
    assert row["id"] not in {open_row["id"] for open_row in _owed()}
    assert len(row["what_the_ruling_unblocked"].split()) >= 8


def test_no_owed_row_claims_to_be_recorded_in_the_umbrella_already() -> None:
    """An owed row and an amendment cannot both be true of one question."""
    umbrella = UMBRELLA.read_text(encoding="utf-8")
    for row in _owed():
        assert row["id"] not in umbrella, row["id"]
