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
# The measured row's measurement, gated.
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
#
# The row closed on 2026-08-18 and every check below still runs, because it is
# found by the measurement it carries rather than by the list it sits in.  A
# gate keyed on "the one open row" would have gone quietly empty on the commit
# that answered the question -- which is R-01 row 1's skip, and is the shape
# ``_every_row`` already refuses one function up.
# --------------------------------------------------------------------------


def _the_measured_row() -> dict:
    """The one row carrying an anchored measurement, owed or answered.

    Keyed on ``measurement_anchor`` and not on which list holds the row.  This
    row's whole history is a measurement going stale beside a question, so the
    checks over that measurement have to outlive the question closing; keying
    them on ``owed`` would have retired them at the exact moment the row became
    a permanent record rather than a live debt.
    """
    measured = [row for row in _every_row() if "measurement_anchor" in row]
    assert len(measured) == 1, [row["id"] for row in measured]
    return measured[0]


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
    return _ledger_at(_the_measured_row()["measurement_anchor"]["commit"])["coverage"]


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
    assert (
        _stated(_the_measured_row()["what_the_measurement_now_reads"], pattern)
        == measured()
    )


@pytest.mark.parametrize(
    "case", ANCHORED_FIGURES, ids=[case[0] for case in ANCHORED_FIGURES]
)
def test_the_measurement_gate_fails_when_a_stated_figure_drifts(
    case: tuple[str, str, Callable[[], str]],
) -> None:
    """R-05's permanent red: doctor the figure and require the same red."""
    _label, pattern, measured = case
    text = _the_measured_row()["what_the_measurement_now_reads"]
    match = re.search(pattern, text)
    assert match is not None
    drifted = str(int(match.group(1)) + 1)
    doctored = text[: match.start(1)] + drifted + text[match.end(1) :]
    assert _stated(doctored, pattern) != measured()


def test_the_anchor_names_a_commit_that_exists() -> None:
    """An anchor nobody can open is a date with better grammar."""
    sha = _the_measured_row()["measurement_anchor"]["commit"]
    resolved = subprocess.run(
        ["git", "cat-file", "-t", sha],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    assert resolved.returncode == 0 and resolved.stdout.strip() == "commit", sha


def _live_figures() -> list[tuple[str, dict]]:
    live = _the_measured_row()["live_figures"]
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


def test_the_population_hole_is_named_and_carries_no_count_of_its_own() -> None:
    """The untagged commits are part of this ruling, and are named as such.

    The denominator is derived from a commit subject's trailing tag, so a
    commit carrying none sits outside it.  The ledger reports them rather than
    dropping them, and what they *are* -- outside "every slice", or evidence
    the convention was not universal -- is the same question the first clause
    asks.  A certification review asked that it be named to whoever rules, so
    it is named here rather than filed as a gap somebody could close by
    adopting a reading.

    The field carries no count: the number moves with every commit, so it is
    read through ``live_figures`` like every other reading this row makes.
    """
    row = _the_measured_row()
    field = row["what_else_the_same_ruling_must_settle"]
    assert "commits_outside_the_denominator" in field
    assert "commits_outside_the_denominator" in row["live_figures"]
    undated = re.sub(r"\d{4}-\d{2}-\d{2}", "", field)
    assert re.search(r"(?<![\w.\-/])\d+", undated) is None, undated


#: The words that make a following number a NAME rather than a count, spelled
#: as ``tests/test_campaign_gap_ledger.py`` spells them: section 16.3 is an
#: identifier, a residue of three is a value.  The distinction is the campaign's
#: own and is reused rather than re-invented.
_NAMES_A_THING = frozenset(
    {"amendment", "clause", "criteria", "criterion", "round", "row", "rule", "section"}
)

_INTEGER = re.compile(r"(?<![\w.\-/])(\w+ )?(\d+)(?![\w.\-/])")


def _counts_in(text: str) -> list[str]:
    """Every integer in ``text`` that is a count rather than an identifier."""
    undated = re.sub(r"\d{4}-\d{2}-\d{2}", "", text)
    return [
        match.group(2)
        for match in _INTEGER.finditer(undated)
        if (match.group(1) or "").strip().lower() not in _NAMES_A_THING
    ]


def test_the_cost_of_deciding_late_is_named_and_states_no_count_of_its_own() -> None:
    """The argument for deciding soon, carried to the reader who decides.

    A certification reviewer measured that the residue's only remaining source
    of growth is the certification process itself, and asked that it be stated
    to whoever rules.  It lives here rather than only in a report section for
    the same reason the population hole does: an input the ruler has to go
    find is an input the ruler does not have.

    Two things it must do and one it must not.  It must name the third branch
    -- the one the close report measured is the only terminating one -- and it
    must read the residue through ``live_figures`` instead of stating it,
    because this row has twice been broken by a restated number.  And it must
    not choose: the field says in its own words what a lane may not do about
    each branch, which is what keeps an argument about timing from becoming an
    answer.
    """
    row = _the_measured_row()
    field = row["the_cost_of_deciding_late"]
    assert "residue" in row["live_figures"]
    assert "live_figures' residue" in field
    assert "third" in field and "terminat" in field.lower()
    assert "What a lane may not do" in field
    assert _counts_in(field) == [], _counts_in(field)


def test_the_no_count_rule_over_that_field_has_a_red_it_can_reproduce() -> None:
    """R-05, on the shape this row has twice failed in."""
    assert _counts_in("the residue is 5 and the backlog prepares 5 passes") == [
        "5",
        "5",
    ]
    assert (
        _counts_in("close report section 16.3, and criterion 11's first clause") == []
    )


def test_the_row_states_no_live_figure_it_could_instead_read() -> None:
    """The mechanism, asserted rather than promised.

    The field's own history is the argument for this test: it promised twice
    that it could not go stale and went stale twice, because it *restated* a
    number the ledger owns.  Every figure it now states is either anchored --
    matched by one of ``ANCHORED_FIGURES`` and re-derived out of git -- or is
    named in ``live_figures`` and read at run time.  What this refuses is a
    third undated number arriving in the same field.
    """
    text = _the_measured_row()["what_the_measurement_now_reads"]
    for _label, pattern, _measured in ANCHORED_FIGURES:
        assert re.search(pattern, text), pattern
    assert "live_figures" in text
    assert (
        _the_measured_row()["measurement_anchor"]["gate"]
        == "tests/test_rulings_owed.py"
    )


# --------------------------------------------------------------------------
# An owner's ruling is not an amendment, and the tree says which is which.
#
# Nine rows closed by an amendment: the orchestration re-reading its own
# contract on a ground it had measured.  The tenth could not, and said so from
# the day it opened -- every branch it offered was a lane deciding what a
# criterion means.  So the umbrella carries a section of its own, and these
# checks are what keep the distinction a fact about the tree rather than a
# claim in a receipt.
# --------------------------------------------------------------------------

OWNER_RULING_HEADING = "## Owner's rulings"

#: The prefix an owner's ruling's ``amendment`` field carries.  A row using it
#: is claiming the ruling came from outside the orchestration, which is exactly
#: the claim that has to be checkable.
OWNER_RULING_PREFIX = "Owner's ruling"


def _owner_ruling_section() -> str:
    """The umbrella text below the owner's-rulings heading."""
    umbrella = UMBRELLA.read_text(encoding="utf-8")
    _before, marker, section = umbrella.partition(OWNER_RULING_HEADING)
    assert marker, OWNER_RULING_HEADING
    return section


def _owner_rulings() -> list[dict]:
    return [
        row for row in _answered() if row["amendment"].startswith(OWNER_RULING_PREFIX)
    ]


def test_the_umbrella_carries_a_section_for_rulings_no_lane_could_write() -> None:
    """The home, and the sentence that says what it is for.

    A section whose own text does not distinguish it from the amendments
    above it is a heading, and a heading is not a distinction.
    """
    section = _owner_ruling_section()
    assert "not an amendment" in section
    assert "rulings-owed.json" in section


@pytest.mark.parametrize(
    "row", _owner_rulings(), ids=[row["id"] for row in _owner_rulings()]
)
def test_an_owners_ruling_is_recorded_where_owners_rulings_live(row) -> None:
    """Recorded *there*, not merely somewhere in the umbrella.

    The amendments are findable anywhere in the file, which is right for
    them.  A ruling claiming to be the owner's is claiming a provenance no
    lane may claim for itself, so it is checked against the one section that
    carries that meaning.
    """
    section = _owner_ruling_section()
    assert row["amendment"] in section, row["id"]
    assert row["id"] in section, row["id"]
    assert row["answered_on"] in row["amendment"], row["id"]


def test_the_owners_ruling_check_has_a_red_it_can_reproduce() -> None:
    """R-05: a ruling recorded nowhere must not read as recorded."""
    section = _owner_ruling_section()
    for row in _owner_rulings():
        assert row["amendment"].replace("ruling", "rulling") not in section
