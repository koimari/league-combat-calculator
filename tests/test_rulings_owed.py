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


def _block() -> dict:
    return json.loads(RULINGS.read_text(encoding="utf-8"))


def _owed() -> list[dict]:
    return _block()["owed"]


def test_the_artifact_declares_what_it_is_and_what_gates_it() -> None:
    block = _block()
    assert block["artifact"] == "rulings_owed"
    assert block["gate"] == "tests/test_rulings_owed.py"
    assert block["how_a_row_closes"].strip()
    assert block["why_a_lane_may_not_write_these"].strip()


def test_every_row_is_complete_and_ids_are_unique() -> None:
    ids = [row["id"] for row in _owed()]
    assert len(ids) == len(set(ids))
    for row in _owed():
        for key in REQUIRED:
            assert row[key].strip(), f"{row['id']} is missing {key}"


@pytest.mark.parametrize("row", _owed(), ids=[row["id"] for row in _owed()])
def test_every_row_points_at_a_measurement_that_exists(row) -> None:
    """A ruling request resting on nothing is an opinion with a filename."""
    path, _, _rest = row["measurement_artifact"].partition(",")
    assert (ROOT / path.strip()).exists(), row["id"]


@pytest.mark.parametrize("row", _owed(), ids=[row["id"] for row in _owed()])
def test_every_row_names_what_a_lane_may_not_do_instead(row) -> None:
    """The half that keeps 'blocked on a ruling' from being a resting place."""
    forbidden = row["what_a_lane_may_not_do_instead"]
    assert len(forbidden.split()) >= 8, row["id"]
    assert forbidden != row["why_no_lane_may_answer_it"]


def test_an_answered_row_would_have_to_name_its_amendment() -> None:
    """The closure rule, asserted on whatever answered[] holds.

    Empty today.  Written now rather than when the first row closes, because
    a closure rule authored by the commit that first needs it is a rule that
    was fitted to one case.
    """
    for row in _block()["answered"]:
        assert row["id"] in {owed["id"] for owed in _owed()} or row["id"]
        assert row["recorded_in"] == "docs/plans/2026-08-08-silent-failure-campaign.md"
        assert row["amendment"] in UMBRELLA.read_text(encoding="utf-8")


def test_no_owed_row_claims_to_be_recorded_in_the_umbrella_already() -> None:
    """An owed row and an amendment cannot both be true of one question."""
    umbrella = UMBRELLA.read_text(encoding="utf-8")
    for row in _owed():
        assert row["id"] not in umbrella, row["id"]
