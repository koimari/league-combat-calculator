"""The close report's last gap table says what the gap ledger says.

The report is a record of *passes*, appended in the order they ran, and each
appended section re-graded only the gaps its own pass touched.  That is the
right way to append — section 9 of the report says earlier text stays as
written — and it has one failure mode, which the sign-off review found by
reading the sections against each other: the fourth table calls G7 and G8
"open with a named blocker" while the first and third had already closed all
three of their entries.  Nothing was wrong; nothing was current either.

So the final state of each gap lives in one artifact, and these checks hold the
report's last table to it.  A pass that closes a gap without moving its ledger
row now fails a gate rather than a reader — and, the other direction, a ledger
row claiming a closure names a commit that exists or an amendment the umbrella
actually holds, so "closed by amendment" cannot name an amendment nobody wrote.

The snapshot figures are the same problem one level down: the report quotes the
verify-ledger residue three times at three values, each true on its date, and
never says which is current.  They are therefore not restated in the ledger at
all — it names the artifact that owns each figure, and
:func:`test_every_live_figure_resolves_in_the_artifact_that_owns_it` reads it.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RECEIPTS = ROOT / "docs" / "receipts"
LEDGER = RECEIPTS / "campaign-gap-ledger.json"
REPORT = RECEIPTS / "campaign-close-report.md"
UMBRELLA = ROOT / "docs" / "plans" / "2026-08-08-silent-failure-campaign.md"

#: The heading whose table is the report's final word on every gap.  Named
#: here rather than found by position: a fifth appended section must move this
#: constant deliberately, which is the moment somebody notices the table it
#: points at is no longer the last one.
FINAL_TABLE_HEADING = "### 20.6 The gaps, as they finally stand"

#: A gap id anywhere in the report, in the bold spelling every table uses.
GAP_IN_REPORT = re.compile(r"\*\*(G\d+)")

#: One row of the final table: the id, then the state, which is a bare member
#: of the ledger's vocabulary and never prose.  Prose belongs in the note.
FINAL_ROW = re.compile(r"^\|\s*\*\*(G\d+)\*\*\s*\|\s*\*\*([A-Z ]+)\*\*\s*\|")


def ledger() -> dict:
    return json.loads(LEDGER.read_text(encoding="utf-8"))


def gaps() -> dict:
    return ledger()["gaps"]


def report_text() -> str:
    return REPORT.read_text(encoding="utf-8")


def final_table_rows(text: str) -> dict[str, str]:
    """``{gap id: state}`` as the report's final table states them.

    The pure function is the seam R-05 asks for: the negative below feeds it a
    doctored report rather than editing the committed one.
    """
    _, _, tail = text.partition(FINAL_TABLE_HEADING)
    rows: dict[str, str] = {}
    for line in tail.splitlines():
        if line.startswith("###"):
            break
        match = FINAL_ROW.match(line)
        if match is not None:
            rows[match.group(1)] = match.group(2).strip()
    return rows


def commit_exists(sha: str) -> bool:
    return (
        subprocess.run(
            ["git", "cat-file", "-e", f"{sha}^{{commit}}"],
            cwd=ROOT,
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )


def test_the_ledger_declares_what_it_is_and_what_gates_it() -> None:
    block = ledger()
    assert block["artifact"] == "campaign_gap_ledger"
    assert block["gate"] == "tests/test_campaign_gap_ledger.py"
    assert block["why_the_report_is_not_the_ledger"].strip()
    assert block["why_snapshot_figures_are_not_restated_here"].strip()


def test_every_gap_the_report_names_has_exactly_one_ledger_row() -> None:
    """Both directions, so the ledger can neither lag the report nor invent."""
    named = set(GAP_IN_REPORT.findall(report_text()))
    assert named == set(gaps()), (
        "the report and the ledger disagree about which gaps exist: "
        f"report-only {sorted(named - set(gaps()))}, "
        f"ledger-only {sorted(set(gaps()) - named)}"
    )


@pytest.mark.parametrize("gap", sorted(gaps()))
def test_every_row_states_a_state_from_the_closed_set(gap: str) -> None:
    assert gaps()[gap]["state"] in ledger()["state_vocabulary"]


@pytest.mark.parametrize("gap", sorted(gaps()))
def test_every_row_names_the_criterion_it_blocks(gap: str) -> None:
    assert gaps()[gap]["blocks"].strip()


@pytest.mark.parametrize(
    "gap", sorted(g for g, row in gaps().items() if row["state"] == "CLOSED")
)
def test_a_closed_row_names_a_commit_or_an_amendment_that_exists(gap: str) -> None:
    """A closure a reader can open, and never a claim standing on its own."""
    row = gaps()[gap]
    shas = row.get("closed_by", ())
    amendment = row.get("unblocked_by")
    assert shas or amendment, f"{gap} is CLOSED and names neither a commit nor a ruling"
    for sha in shas:
        assert commit_exists(sha), f"{gap} names commit {sha}, which does not exist"
    if amendment is not None:
        assert amendment in UMBRELLA.read_text(
            encoding="utf-8"
        ), f"{gap} claims {amendment!r} and the umbrella does not hold it"


@pytest.mark.parametrize(
    "gap", sorted(g for g, row in gaps().items() if row["state"] == "OPEN")
)
def test_an_open_row_names_its_blocker_and_where_it_is_carried(gap: str) -> None:
    """An open gap with no blocker is a gap nobody can schedule."""
    row = gaps()[gap]
    assert row["blocker"].strip()
    assert row["artifact"].strip()


#: An integer written into prose -- not the 35 of "R-35" and not a path
#: fragment, which the pattern's own boundaries drop.
_INTEGER = re.compile(r"(?<![\w.\-/])(\w+ )?(\d+)(?![\w.\-/])")

#: The words that make a following number a NAME rather than a count: criterion
#: 11 is an identifier, sixty passes is a value.  A gap row is expected to name
#: the criteria and clauses it blocks; that is what it is for.
_NAMES_A_THING = frozenset(
    {
        "amendment",
        "clause",
        "criteria",
        "criterion",
        "phase",
        "round",
        "row",
        "rule",
        "section",
        "slice",
    }
)


def counts_in(text: str) -> list[str]:
    """Every integer in ``text`` that is a count rather than an identifier."""
    found: list[str] = []
    for match in _INTEGER.finditer(text):
        preceding = (match.group(1) or "").strip().lower()
        if preceding in _NAMES_A_THING:
            continue
        found.append(match.group(2))
    return found


@pytest.mark.parametrize(
    "gap", sorted(g for g, row in gaps().items() if row["state"] == "OPEN")
)
def test_an_open_rows_blocker_states_no_count_of_its_own(gap: str) -> None:
    """A blocker describes what stands in the way; it does not hold a value.

    The file's own rule says it in one line -- *"Nothing here is a value; a
    value here would be the second home criterion 4 exists to forbid"* -- and
    G14's blocker held one anyway: "schedules some sixty fresh read-only
    passes", written when the residue was sixty-odd and left standing through
    the backfill that took it to three.  An R-35 verifier found it, and nothing
    in the tree would have.

    So an open row's blocker names ``live_figures`` keys instead of counting,
    and a count arriving in one turns this red on the commit that writes it.
    """
    blocker = gaps()[gap]["blocker"]
    assert counts_in(blocker) == [], blocker


def test_the_no_count_rule_has_a_red_it_can_reproduce() -> None:
    """R-05, on the finding's own words."""
    doctored = "Binding the clause backwards schedules some 60 fresh passes."
    assert counts_in(doctored) == ["60"]
    assert counts_in("umbrella criterion 11's own words, and section 16.3") == []


@pytest.mark.parametrize(
    "gap", sorted(g for g, row in gaps().items() if row["state"] == "OPEN")
)
def test_every_live_figure_an_open_row_names_is_a_figure_this_file_owns(
    gap: str,
) -> None:
    """A blocker that names a counter names one this ledger actually keeps."""
    row = gaps()[gap]
    live = ledger()["live_figures"]
    named = [key for key in live if key != "rule" and key in row["blocker"]]
    for key in named:
        assert live[key]["grades"] == gap, key


def test_the_reports_final_table_states_the_same_state_as_the_ledger() -> None:
    """The finding itself: the last table is the ledger, row for row."""
    assert final_table_rows(report_text()) == {
        gap: row["state"] for gap, row in gaps().items()
    }


def test_a_gap_missing_from_the_final_table_fails() -> None:
    """R-05's permanent negative, through the pure function's seam.

    The doctored report drops G7's row — the exact shape the sign-off review
    found, where a later table simply does not re-state a gap an earlier one
    closed — and the check must not read that as agreement.
    """
    doctored = "\n".join(
        line
        for line in report_text().splitlines()
        if not FINAL_ROW.match(line) or FINAL_ROW.match(line).group(1) != "G7"
    )
    rows = final_table_rows(doctored)
    assert "G7" not in rows
    assert rows != {gap: row["state"] for gap, row in gaps().items()}


def test_a_stale_state_in_the_final_table_fails() -> None:
    """The other half: a row that is present and wrong."""
    doctored = report_text().replace("| **G7** | **CLOSED** |", "| **G7** | **OPEN** |")
    assert doctored != report_text()
    assert final_table_rows(doctored)["G7"] == "OPEN"
    assert final_table_rows(doctored) != {
        gap: row["state"] for gap, row in gaps().items()
    }


@pytest.mark.parametrize(
    "name", sorted(k for k in ledger()["live_figures"] if k != "rule")
)
def test_every_live_figure_resolves_in_the_artifact_that_owns_it(name: str) -> None:
    """No figure is stored here; each is read from its one home.

    This is criterion 4's discipline applied to the report's own counters —
    the drift the review found (70/63, then 68/61, then 73/62) is a figure
    with three homes and no statement of which is current.
    """
    spec = ledger()["live_figures"][name]
    document = json.loads(
        (ROOT / spec["artifact"]).read_text(encoding="utf-8")
        if "/" in spec["artifact"]
        else (RECEIPTS / spec["artifact"]).read_text(encoding="utf-8")
    )
    node = document
    for key in spec["path"].split("."):
        assert key in node, f"{name}: {spec['artifact']} holds no {spec['path']}"
        node = node[key]
    assert isinstance(node, int)
    assert spec["grades"] in gaps()
