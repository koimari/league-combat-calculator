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
import re
import subprocess
from pathlib import Path
from typing import Callable

import pytest

ROOT = Path(__file__).resolve().parents[1]
RULINGS = ROOT / "docs" / "receipts" / "rulings-owed.json"
UMBRELLA = ROOT / "docs" / "plans" / "2026-08-08-silent-failure-campaign.md"
LEDGER_PATH = "docs/receipts/verify-ledger.json"

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


# --------------------------------------------------------------------------
# The open row's measurement, gated.
#
# ``what_the_measurement_now_reads`` was added so the owed ruling's population
# would be read from the artifact that owns it instead of frozen in a question
# written on 2026-08-14.  It froze anyway: it says "Measured on this tip", and
# a sentence that names no tip is a reading of whichever commit wrote it.  An
# R-35 verifier found it (round 129, ``campaign-close-final-integration-r35``),
# not a reader, and nothing in the tree would have.
#
# Two mechanisms replace the promise.  The dated reading is **anchored** at the
# commit that stated it and re-derived out of git, which is where the close
# report already reads its own dated figures.  The tip's readings are **named
# rather than restated** -- ``live_figures`` gives each an artifact and a path,
# the gap ledger's own rule, so this row cannot state a number its measurement
# artifact contradicts.
# --------------------------------------------------------------------------


def _open_row() -> dict:
    """The one open row -- the only one carrying a measurement to gate."""
    owed = _owed()
    assert len(owed) == 1, [row["id"] for row in owed]
    return owed[0]


def _ledger_at(sha: str) -> dict:
    """The measurement artifact as one commit left it, read out of git."""
    blob = subprocess.run(
        ["git", "show", f"{sha}:{LEDGER_PATH}"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=True,
    ).stdout
    return json.loads(blob)


def _anchored_coverage() -> dict:
    return _ledger_at(_open_row()["measurement_anchor"]["commit"])["coverage"]


def _stated(text: str, pattern: str) -> str:
    match = re.search(pattern, text)
    assert match is not None, pattern
    return match.group(1)


#: ``(label, pattern, what the artifact says)``.  The pattern's one group is the
#: figure the row states; the callable re-derives it at the anchor.
ANCHORED_FIGURES: list[tuple[str, str, Callable[[], str]]] = [
    (
        "slice tags",
        r"Measured on this tip: (\d+) slice tags",
        lambda: str(
            len(_anchored_coverage()["slice_groups_with_a_verdict_in_this_ledger"])
            + len(_anchored_coverage()["slice_groups_without_one"])
        ),
    ),
    (
        "with a verdict",
        r"slice tags derived from commit subjects, (\d+) with a verdict",
        lambda: str(
            len(_anchored_coverage()["slice_groups_with_a_verdict_in_this_ledger"])
        ),
    ),
    (
        "residue",
        r"a residue of (\d+)",
        lambda: str(_anchored_coverage()["residue"]),
    ),
    (
        "citing nothing anywhere",
        r"and (\d+) citing nothing anywhere",
        lambda: str(_anchored_coverage()["residue_with_no_verdict_anywhere"]),
    ),
]


@pytest.mark.parametrize(
    "case", ANCHORED_FIGURES, ids=[case[0] for case in ANCHORED_FIGURES]
)
def test_the_dated_measurement_is_true_at_the_commit_it_is_anchored_at(
    case: tuple[str, str, Callable[[], str]],
) -> None:
    """A reading of "this tip" is checked against the tip it was read at."""
    _label, pattern, measured = case
    assert _stated(_open_row()["what_the_measurement_now_reads"], pattern) == measured()


@pytest.mark.parametrize(
    "case", ANCHORED_FIGURES, ids=[case[0] for case in ANCHORED_FIGURES]
)
def test_the_measurement_gate_fails_when_a_stated_figure_drifts(
    case: tuple[str, str, Callable[[], str]],
) -> None:
    """R-05's permanent red: doctor the figure and require the same red."""
    _label, pattern, measured = case
    text = _open_row()["what_the_measurement_now_reads"]
    match = re.search(pattern, text)
    assert match is not None
    drifted = str(int(match.group(1)) + 1)
    doctored = text[: match.start(1)] + drifted + text[match.end(1) :]
    assert _stated(doctored, pattern) != measured()


def test_the_anchor_names_a_commit_that_exists() -> None:
    """An anchor nobody can open is a date with better grammar."""
    sha = _open_row()["measurement_anchor"]["commit"]
    resolved = subprocess.run(
        ["git", "cat-file", "-t", sha],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    assert resolved.returncode == 0 and resolved.stdout.strip() == "commit", sha


def _live_figures() -> list[tuple[str, dict]]:
    live = _open_row()["live_figures"]
    return [(name, spec) for name, spec in live.items() if name != "rule"]


@pytest.mark.parametrize(
    "case", _live_figures(), ids=[name for name, _spec in _live_figures()]
)
def test_every_live_figure_resolves_in_the_artifact_that_owns_it(
    case: tuple[str, dict],
) -> None:
    """A named figure with no home is the second home wearing a label."""
    name, spec = case
    payload = json.loads((ROOT / spec["artifact"]).read_text(encoding="utf-8"))
    for step in spec["path"].split("."):
        assert step in payload, f"{name}: {spec['path']}"
        payload = payload[step]
    if spec["read_as"] == "length":
        assert isinstance(payload, list), name
    else:
        assert isinstance(payload, int), name


def test_the_row_states_no_live_figure_it_could_instead_read() -> None:
    """The mechanism, asserted rather than promised.

    The field's own history is the argument for this test: it promised twice
    that it could not go stale and went stale twice, because it *restated* a
    number the ledger owns.  Every figure it now states is either anchored --
    matched by one of ``ANCHORED_FIGURES`` and re-derived out of git -- or is
    named in ``live_figures`` and read at run time.  What this refuses is a
    third undated number arriving in the same field.
    """
    text = _open_row()["what_the_measurement_now_reads"]
    for _label, pattern, _measured in ANCHORED_FIGURES:
        assert re.search(pattern, text), pattern
    assert "live_figures" in text
    assert _open_row()["measurement_anchor"]["gate"] == "tests/test_rulings_owed.py"
