"""Sections 15 and 16 of the close report, gated: every figure is re-derived.

The R-35 pass over ``campaign-close-final-integration`` failed section 14 on
three figures and closed its evidence with the reason all three survived to be
found by a reader: "Section 14 is also ungated: plan_audit.py runs over
docs/plans/*.md only, so nothing in the tree would catch any of these three."

``plan_audit.py`` gates the plan documents (R-37).  Nothing gated this report,
which is where the campaign's closing figures live, so a corrected figure could
go stale exactly the way the corrected one did.  This file is the missing half
for the section that carries the corrections: every number section 15 states is
matched against the artifact it was read from -- the ledger's coverage block and
pass rows, the backlog, and for the dated readings the ledger's own history --
and every non-numeric claim it makes about a round or a range is re-measured.

A figure that is a reading of a moving artifact is anchored at the commit that
stated it and read out of git there; a figure about this tip is read from the
tree.  What section 15 quotes out of section 14 is checked as a quotation and
not re-derived, because a correction that misquotes the sentence it corrects is
one no reader can check.

The negative half is permanent and rides beside the positive one (R-05):
``test_the_gate_fails_when_a_stated_figure_drifts`` doctors each figure in a copy
of the section and requires the same comparison to fail.  A check that cannot
fail is the shape this campaign exists to remove.

Section 16 joins on the same terms and had to: it is the section that closes two
gap rows and states a criterion's re-grade, so its counts are the load-bearing
ones in this report.  Its figures are read *live* from the instruments they were
measured with -- the standing-dissent scan, the retirement schedule, the
interpreter registry, a fresh term census and the verify ledger -- because they
are facts about this tip rather than dated readings.  A later pass that moves one
faces the choice ``e4338b7`` faced and now has both answers written down: restate
the figure, or anchor it at the commit that stated it the way
``SECTION_15_5_ANCHOR`` does.

Section 16 joins on the same terms, and it had to: it is the section that closes
two gap rows and states a criterion's re-grade, so every count in it is load
bearing in the strongest sense this report has.  Its figures are read live from
the instruments they were measured with -- the standing-dissent scan, the
behaviour frontier, the retirement schedule, the interpreter registry, the term
census and the verify ledger -- because they are facts about this tip.  When a
later pass moves one of them the choice is the one section 15.5 already had to
make: restate the figure, or anchor it at the commit that stated it the way
``SECTION_15_5_ANCHOR`` does.  The mechanism exists now, which is the whole of
what 15.5's anchoring bought.

Section 17 joins on the same terms and made the choice section 16.6 wrote down:
round 129 moved two of 16.3's readings, so those seven are anchored at
``SECTION_16_3_ANCHOR`` and 17 states the live ones.  Two of 17's own figures are
readings of the campaign's *commit bodies*, which grow with every commit
including the one that states them, so they are anchored too and the section
names the anchor.

The guarantee is a property here rather than a list.  ``ungated_figures`` scans a
section for a bold figure nothing in this file reads -- the shape all three
sections use for a figure they state -- so a figure added later is caught instead
of being silently ungated, which is what "re-derives every figure" claimed and
an enumeration could not deliver.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from typing import Callable

import pytest

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "docs" / "receipts" / "campaign-close-report.md"
LEDGER_PATH = "docs/receipts/verify-ledger.json"
BACKLOG = ROOT / "docs" / "receipts" / "verify-backlog.json"

#: The commit section 15.4's table is measured at, named in the section itself.
TABLE_ANCHOR = "832a91f"

#: The group whose range section 15.2 says no verifier's brief has reached.
UNREACHED_COMMIT = "209da2f"

#: Where R-32's ``tests.collected`` amendment landed, per section 15.3.
MINOR_4_COMMIT = "1bd837e"

#: The commit section 15.3's "all N passes" search was run at.
SEARCH_ANCHOR = "86114ed"

#: The sweep batch section 15.4's first clause counts, and its parent.
BATCH = "a431e34"
BATCH_PARENT = "1e7c342"

#: The commit that wrote section 15.4's closing paragraph and section 15.5.
#: Both read "this tip", which they were, and stopped being so the moment
#: another slice group shipped.  A dated reading is anchored at the commit
#: that stated it and read out of git; only a fact about the live tree is
#: read from the tree.
SECTION_15_4_TIP_ANCHOR = "e4338b7"

#: The commit that wrote section 16.3.  Its seven ledger readings were facts
#: about that tip, and section 16.6 wrote down in advance what the next pass
#: that moved one had to do: "restate the figure, or anchor it the way
#: ``SECTION_15_5_ANCHOR`` does".  Round 129 moved two of them -- a verdict that
#: had been rendered and never transcribed -- so they are anchored, which is the
#: branch that leaves the section's text as written.  Section 17 states the live
#: readings and is gated against the tree.
SECTION_16_3_ANCHOR = "3799bef"

#: The commit that wrote section 15.5.  Its coverage figures were "about this
#: tip" when they were written and stopped being so the moment another slice
#: group shipped -- which is a thing the campaign expects to happen, not a
#: defect in the section.  So they are read where every other moving reading in
#: this file is read: at the commit that stated them, out of git.  The anchor is
#: named rather than inferred, so moving it is a deliberate act.
SECTION_15_5_ANCHOR = "e4338b7"

#: The commit that wrote section 17.  Its nine readings of the verify ledger --
#: three in 17.1 and six in 17.3 -- were facts about that tip, stated live
#: because they were.  The pass that appended section 18 shipped a slice group
#: of its own, which moved four of them, so all nine take the branch 16.6 wrote
#: down and 17's own preamble already applies to the sections above it: they
#: stay exactly as written and are read at the commit that stated them.  They
#: are anchored as a group and not one at a time, the way 16.3's seven were,
#: because a section whose readings come half from a tip and half from git is a
#: section no reader can date.
SECTION_17_LEDGER_ANCHOR = "407428f"

#: The commit that wrote section 19.  Its five readings of the verify ledger,
#: all in 19.1, were facts about that tip and were stated live because they
#: were.  The lane recording the owner's ruling on criterion 11 shipped a slice
#: group of its own and its first commit moved two of them -- the residue and
#: the prepared-pass count -- exactly as the two passes before it moved section
#: 17's and section 16.3's.  So they take the branch 16.6 wrote down, as a group
#: rather than one at a time: the section stays exactly as written and is read
#: at the commit that stated it.  The three that did not move are anchored with
#: them for the reason 17's note gives -- a section read half from a tip and
#: half from git is a section no reader can date.
SECTION_19_LEDGER_ANCHOR = "53b792c"


@lru_cache(maxsize=1)
def section_15() -> str:
    """The report's section 15, bounded at 16 rather than at the file's end.

    It ran to the end of the file until section 16 existed, which was true and
    stopped being so; an unbounded section lets a gate match a figure a later
    section states and report it as this one's.
    """
    text = REPORT.read_text(encoding="utf-8")
    return text[text.index("\n## 15.") : text.index("\n## 16.")]


@lru_cache(maxsize=1)
def section_16() -> str:
    """The report's section 16, bounded at 17 for section 15's own reason.

    It ran to the end of the file until section 17 existed, which was true and
    stopped being so; an unbounded section lets a gate match a figure a later
    section states and report it as this one's.
    """
    text = REPORT.read_text(encoding="utf-8")
    return text[text.index("\n## 16.") : text.index("\n## 17.")]


@lru_cache(maxsize=1)
def section_17() -> str:
    """The report's section 17, bounded at 18 for section 15's own reason.

    It ran to the end of the file until section 18 existed, which was true and
    stopped being so; an unbounded section lets a gate match a figure a later
    section states and report it as this one's.
    """
    text = REPORT.read_text(encoding="utf-8")
    return text[text.index("\n## 17.") : text.index("\n## 18.")]


@lru_cache(maxsize=1)
def section_18() -> str:
    """The report's section 18, bounded at 19 for section 15's own reason.

    It ran to the end of the file until section 19 existed, which was true and
    stopped being so; an unbounded section lets a gate match a figure a later
    section states and report it as this one's.
    """
    text = REPORT.read_text(encoding="utf-8")
    return text[text.index("\n## 18.") : text.index("\n## 19.")]


@lru_cache(maxsize=1)
def section_19() -> str:
    """The report from its section 19 heading to the end of the file."""
    text = REPORT.read_text(encoding="utf-8")
    return text[text.index("\n## 19.") :]


@lru_cache(maxsize=1)
def scan():
    """The standing-dissent instrument, imported by path as its own suite does."""
    spec = importlib.util.spec_from_file_location(
        "standing_dissent_scan", ROOT / "scripts" / "standing_dissent_scan.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("standing_dissent_scan", module)
    spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=1)
def term_census() -> dict:
    """The term census, re-run rather than read off prose."""
    spec = importlib.util.spec_from_file_location(
        "term_census", ROOT / "scripts" / "term_census.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("term_census", module)
    spec.loader.exec_module(module)
    return module.report(module.census())


def receipt(name: str) -> dict:
    """One committed receipt at this tip."""
    return json.loads((ROOT / "docs" / "receipts" / name).read_text(encoding="utf-8"))


def receipt_walk_interpreter_keys() -> str:
    """How many ``(family, RECEIPT_WALK)`` keys the interpreter registry holds."""
    if str(ROOT / "src") not in sys.path:
        sys.path.insert(0, str(ROOT / "src"))
    from calculator.interpreters import (  # pylint: disable=import-outside-toplevel
        INTERPRETERS,
    )

    return str(sum(1 for key in INTERPRETERS if "RECEIPT_WALK" in str(key)))


@lru_cache(maxsize=None)
def ledger_at(sha: str) -> dict:
    """The ledger as one commit left it, read out of git rather than restated."""
    blob = subprocess.run(
        ["git", "show", f"{sha}:{LEDGER_PATH}"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=True,
    ).stdout
    return json.loads(blob)


def ledger() -> dict:
    """The ledger at this tip."""
    return json.loads((ROOT / LEDGER_PATH).read_text(encoding="utf-8"))


def residue_at(sha: str) -> str:
    """``coverage.residue`` as of one commit, which is what 15.1 tabulates."""
    return str(ledger_at(sha)["coverage"]["residue"])


def criterion_rows(block: dict) -> list[dict]:
    """A pass's criterion rows -- the population the verdict counts are over."""
    return list(block["criteria"])


def verdict_count(passes: list[dict], verdict: str) -> str:
    """How many criterion rows carry this verdict."""
    return str(
        sum(
            1
            for block in passes
            for row in criterion_rows(block)
            if row["verdict"] == verdict
        )
    )


def open_rows(passes: list[dict], disposition: str) -> list[tuple[dict, dict]]:
    """Every NOT_DISCHARGED criterion row with this disposition, with its pass."""
    return [
        (block, row)
        for block in passes
        for row in criterion_rows(block)
        if row["verdict"] == "NOT_DISCHARGED" and row["disposition"] == disposition
    ]


def disposition_count(passes: list[dict], disposition: str) -> str:
    """How many NOT_DISCHARGED rows carry this disposition."""
    return str(len(open_rows(passes, disposition)))


def kind_of(block: dict) -> str:
    """Which of the three provenances a pass block has."""
    if block.get("backfilled"):
        return "backfill"
    if block.get("residue_sweep"):
        return "residue_sweep"
    return "live"


def open_kind_count(passes: list[dict], kind: str) -> str:
    """How many documented_open rows sit in blocks of this provenance."""
    return str(
        sum(
            1
            for block, _row in open_rows(passes, "documented_open")
            if kind_of(block) == kind
        )
    )


def open_group_count(passes: list[dict], group: str | None = None) -> str:
    """Distinct slice groups holding a documented_open row, or one group's rows."""
    rows = open_rows(passes, "documented_open")
    if group is None:
        return str(len({block["slice_group"] for block, _row in rows}))
    return str(sum(1 for block, _row in rows if block["slice_group"] == group))


def open_round_count(passes: list[dict]) -> str:
    """Distinct rounds holding a documented_open row."""
    return str(
        len({block["round"] for block, _row in open_rows(passes, "documented_open")})
    )


def anchored() -> list[dict]:
    """The passes section 15.4's table was measured over."""
    return ledger_at(TABLE_ANCHOR)["passes"]


def here() -> list[dict]:
    """The passes at this tip."""
    return ledger()["passes"]


def anchored_16_3() -> list[dict]:
    """The passes section 16.3's verdict counts were measured over."""
    return ledger_at(SECTION_16_3_ANCHOR)["passes"]


def slice_tag_total_at(block: dict) -> str:
    """The same sum over one coverage block, whichever commit it came from."""
    return str(
        len(block["slice_groups_with_a_verdict_in_this_ledger"])
        + len(block["slice_groups_without_one"])
    )


def coverage_at(sha: str) -> dict:
    """The coverage block as one commit left it."""
    return ledger_at(sha)["coverage"]


def prepared_passes_at(sha: str) -> str:
    """How many startable passes the backlog held at one commit."""
    blob = subprocess.run(
        ["git", "show", f"{sha}:docs/receipts/verify-backlog.json"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=True,
    ).stdout
    return str(json.loads(blob)["prepared_passes"])


def pass_count(sha: str) -> str:
    """How many pass blocks the ledger held at one commit."""
    return str(len(ledger_at(sha)["passes"]))


def batch_blocks() -> list[dict]:
    """The blocks ``a431e34`` added -- the population 15.4's first clause is about.

    Derived as a set difference over round numbers rather than counted from
    prose: the blocks in that commit's ledger that its parent's ledger did not
    hold.
    """
    before = {block["round"] for block in ledger_at(BATCH_PARENT)["passes"]}
    return [
        block for block in ledger_at(BATCH)["passes"] if block["round"] not in before
    ]


#: ``(label, pattern, what the artifact says)``.  The pattern's one group is the
#: figure section 15 states; the callable re-derives it.  Patterns avoid the
#: section's em dashes and arrows so this file stays ASCII.
#:
#: A figure that is a reading of a moving artifact is anchored at the commit
#: that stated it and read out of git there; a figure about this tip is read
#: from the tree.  Both are re-derived, and neither is restated.
FIGURES: list[tuple[str, str, Callable[[], str]]] = [
    (
        "15.1 residue at c029024",
        r"`c029024`[^\n]*?residue \*\*(\d+)\*\*",
        lambda: residue_at("c029024"),
    ),
    (
        "15.1 residue at 0f3adca",
        r"`0f3adca`[^\n]*?residue \*\*(\d+)\*\*",
        lambda: residue_at("0f3adca"),
    ),
    (
        "15.1 residue at a323202",
        r"`a323202`[^\n]*?residue \*\*(\d+)\*\*",
        lambda: residue_at("a323202"),
    ),
    (
        "15.1 residue at 9961bf2",
        r"`9961bf2`[^\n]*?residue \*\*(\d+)\*\*",
        lambda: residue_at("9961bf2"),
    ),
    (
        "15.1 residue at a455839",
        r"`a455839`[^\n]*?residue \*\*(\d+)\*\*",
        lambda: residue_at("a455839"),
    ),
    (
        "15.1 residue at 0be8f37",
        r"`0be8f37`[^\n]*?residue \*\*(\d+)\*\*",
        lambda: residue_at("0be8f37"),
    ),
    (
        "15.4 DISCHARGED",
        r"\| `DISCHARGED` \| (\d+) \|",
        lambda: verdict_count(anchored(), "DISCHARGED"),
    ),
    (
        "15.4 PHASE_TIP_ONLY",
        r"\| `PHASE_TIP_ONLY` \| (\d+) \|",
        lambda: verdict_count(anchored(), "PHASE_TIP_ONLY"),
    ),
    (
        "15.4 NOT_DISCHARGED",
        r"\| `NOT_DISCHARGED` \| (\d+) \|",
        lambda: verdict_count(anchored(), "NOT_DISCHARGED"),
    ),
    (
        "15.4 fixed",
        r"of which `fixed` \| (\d+) \|",
        lambda: disposition_count(anchored(), "fixed"),
    ),
    (
        "15.4 fixed_and_gated",
        r"of which `fixed_and_gated` \| (\d+) \|",
        lambda: disposition_count(anchored(), "fixed_and_gated"),
    ),
    (
        "15.4 documented_open",
        r"of which `documented_open` \| (\d+) \|",
        lambda: disposition_count(anchored(), "documented_open"),
    ),
    (
        "15.4 open rows restated",
        r"The (\d+) stand across",
        lambda: disposition_count(anchored(), "documented_open"),
    ),
    ("15.4 groups", r"across (\d+) slice groups", lambda: open_group_count(anchored())),
    ("15.4 rounds", r"and (\d+) rounds:", lambda: open_round_count(anchored())),
    (
        "15.4 in backfilled blocks",
        r"(\d+) of them in backfilled blocks",
        lambda: open_kind_count(anchored(), "backfill"),
    ),
    (
        "15.4 in sweep blocks",
        r"\n(\d+) in residue-sweep blocks",
        lambda: open_kind_count(anchored(), "residue_sweep"),
    ),
    (
        "15.4 in live passes",
        r"and (\d+) in live passes",
        lambda: open_kind_count(anchored(), "live"),
    ),
    (
        "15.4 R-28's share",
        r"`R-28` alone holds (\d+)",
        lambda: open_group_count(anchored(), "R-28"),
    ),
    (
        "15.4 campaign-close's share",
        r"`campaign-close` (\d+),",
        lambda: open_group_count(anchored(), "campaign-close"),
    ),
    (
        "15.4 NOT_DISCHARGED at this tip",
        r"moves `NOT_DISCHARGED` 89 [^\n]*?\*\*(\d+)\*\*",
        lambda: verdict_count(
            ledger_at(SECTION_15_4_TIP_ANCHOR)["passes"], "NOT_DISCHARGED"
        ),
    ),
    (
        "15.4 fixed at this tip",
        r"\n20 [^\n]*?\*\*(\d+)\*\*",
        lambda: disposition_count(
            ledger_at(SECTION_15_4_TIP_ANCHOR)["passes"], "fixed"
        ),
    ),
    (
        "15.4 documented_open at this tip",
        r"unchanged at \*\*(\d+)\*\*",
        lambda: disposition_count(
            ledger_at(SECTION_15_4_TIP_ANCHOR)["passes"], "documented_open"
        ),
    ),
    (
        "15.5 the round recorded",
        r"\*\*round (\d+)\*\* of",
        lambda: str(
            max(block["round"] for block in ledger_at(SECTION_15_5_ANCHOR)["passes"])
        ),
    ),
    (
        "15.5 residue",
        r"The residue is \*\*(\d+)\*\* again",
        lambda: str(coverage_at(SECTION_15_5_ANCHOR)["residue"]),
    ),
    (
        "15.5 slice tags",
        r"\*\*(\d+)\*\* slice tags, with",
        lambda: slice_tag_total_at(coverage_at(SECTION_15_5_ANCHOR)),
    ),
    (
        "15.5 residue with no verdict anywhere",
        r"`residue_with_no_verdict_anywhere` \*\*(\d+)\*\*",
        lambda: str(
            coverage_at(SECTION_15_5_ANCHOR)["residue_with_no_verdict_anywhere"]
        ),
    ),
    (
        "15.5 prepared passes",
        r"preparing \*\*(\d+)\*\* startable passes",
        lambda: prepared_passes_at(SECTION_15_5_ANCHOR),
    ),
    (
        "15.1 the figure it fell from",
        r"(\d+) at `9961bf2` earlier the same day",
        lambda: residue_at("9961bf2"),
    ),
    (
        "15.1 the figure it rose from",
        r"up\* from (\d+) on 2026-08-14",
        lambda: residue_at("0f3adca"),
    ),
    (
        "15.3 the passes searched",
        r"in all (\d+) passes",
        lambda: pass_count(SEARCH_ANCHOR),
    ),
    (
        "15.4 the batch's blocks",
        r"the (\d+) pass blocks `a431e34` transcribed",
        lambda: str(len(batch_blocks())),
    ),
    (
        "15.4 the batch's NOT_DISCHARGED rows",
        r"transcribed carry (\d+)",
        lambda: verdict_count(batch_blocks(), "NOT_DISCHARGED"),
    ),
    (
        "15.4 the batch's fixed rows",
        r"of which (\d+) are `fixed`",
        lambda: disposition_count(batch_blocks(), "fixed"),
    ),
    (
        "15.4 the batch's open rows",
        r"and (\d+) `documented_open`",
        lambda: disposition_count(batch_blocks(), "documented_open"),
    ),
    (
        "15.4 the closeout's share of the open rows",
        r"Nine of the (\d+) are this",
        lambda: disposition_count(anchored(), "documented_open"),
    ),
    (
        "15.4 the rows that were open before it",
        r"the other (\d+) were open before it began",
        lambda: str(
            int(disposition_count(anchored(), "documented_open"))
            - int(disposition_count(batch_blocks(), "documented_open"))
        ),
    ),
    (
        "15.4 the passes the table was measured over",
        r"over the (\d+) passes the ledger then held",
        lambda: pass_count(TABLE_ANCHOR),
    ),
    (
        "15.6 the gate's own size",
        r"\*\*(\d+)\*\* figures and \*\*6\*\* claims",
        lambda: str(len(FIGURES)),
    ),
]


def stated(text: str, pattern: str) -> str:
    """The figure the section states, or a failure naming the pattern."""
    match = re.search(pattern, text)
    assert match is not None, f"section 15 states no figure matching {pattern!r}"
    return match.group(1)


@pytest.mark.parametrize("case", FIGURES, ids=[case[0] for case in FIGURES])
def test_every_figure_section_15_states_is_the_measured_one(
    case: tuple[str, str, Callable[[], str]],
) -> None:
    """The corrections are gated, which is what section 14's figures were not."""
    _label, pattern, measured = case
    assert stated(section_15(), pattern) == measured()


@pytest.mark.parametrize("case", FIGURES, ids=[case[0] for case in FIGURES])
def test_the_gate_fails_when_a_stated_figure_drifts(
    case: tuple[str, str, Callable[[], str]],
) -> None:
    """R-05's red, permanent and beside the green it protects.

    Each figure is doctored in a copy of the section -- the value only, in the
    one place the pattern finds it -- and the same comparison has to fail.
    """
    _label, pattern, measured = case
    text = section_15()
    match = re.search(pattern, text)
    assert match is not None
    drifted = str(int(match.group(1)) + 1)
    doctored = text[: match.start(1)] + drifted + text[match.end(1) :]
    assert stated(doctored, pattern) != measured()


def test_no_verifier_has_reached_the_p4_batch_range() -> None:
    """15.2's surviving clause: the range no brief reached, re-measured."""
    reached = [
        block["round"]
        for block in here()
        if UNREACHED_COMMIT in block["verified_commits"]
    ]
    assert not reached


def test_the_p4_batch_row_is_flagged_only_as_citing_a_body() -> None:
    """And the flag 15.2 says is the true part of the sentence is really set."""
    groups = json.loads(BACKLOG.read_text(encoding="utf-8"))["groups"]
    row = groups["campaign-close-verify-p4-batch"]
    assert row["cites_an_r35_answer_in_a_commit_body"] is True


def test_round_110_reads_on_round_6s_row_and_not_on_the_re_pin() -> None:
    """15.3's first half: what round 110 actually verifies."""
    block = next(item for item in here() if item["round"] == 110)
    assert block["slice_group"] == "campaign-close-minor-findings-r35"
    ids = [row["id"] for row in block["criteria"]]
    assert ids
    # The ledger stamps every criterion id with its slice group, so the stem is
    # what carries the round the criterion reads on: tag, slash, then round6-.
    assert all(row_id.split("/")[-1].startswith("round6-") for row_id in ids), ids


def test_the_commit_that_closed_minor_4_is_verified_only_by_rounds_6_and_7() -> None:
    """15.3's second half: no round measures the act, and the two that touch it fail."""
    blocks = [item for item in here() if MINOR_4_COMMIT in item["verified_commits"]]
    assert sorted(item["round"] for item in blocks) == [6, 7]
    for block in blocks:
        assert block["slice_group"] == "campaign-close-minor-findings"
        assert all(row["verdict"] == "NOT_DISCHARGED" for row in block["criteria"])


def test_the_three_groups_15_4_calls_five_each_really_hold_five() -> None:
    """The one open-row figure section 15.4 spells as a word, re-derived."""
    for group in ("R-37", "S9", "S10"):
        assert open_group_count(anchored(), group) == "5", group


#: What section 15 quotes out of section 14.  A correction that misquotes the
#: sentence it corrects is a correction a reader cannot check, so the quotations
#: are gated as quotations rather than re-derived as figures.
QUOTED_FROM_SECTION_14 = (
    "down from 118 on 2026-08-14",
    "2 of 125 slice tags",
    "remaining tags cite a verdict a reader can open",
    "whose range no verifier's brief ever reached",
    "ledger round 110",
    "nine stand `documented_open`",
)


def flattened(text: str) -> str:
    """One line, single spaces -- so a quotation is not defeated by a line wrap."""
    return re.sub(r"\s+", " ", text)


def test_every_phrase_15_quotes_from_section_14_is_really_there() -> None:
    """A correction that misquotes what it corrects cannot be checked by a reader."""
    text = REPORT.read_text(encoding="utf-8")
    fourteen = flattened(text[text.index("\n## 14.") : text.index("\n## 15.")])
    fifteen = flattened(section_15())
    for phrase in QUOTED_FROM_SECTION_14:
        assert phrase in fourteen, phrase
        assert phrase in fifteen, phrase


#: Section 16's figures.  Read live from the instruments they were measured with,
#: because they are facts about this tip rather than dated readings; a later pass
#: that moves one either restates it or anchors it the way ``SECTION_15_5_ANCHOR``
#: does.  Section 16 is the section that closes two gap rows and states a
#: criterion's re-grade, so its counts are the load-bearing ones in this report.
FIGURES_16: list[tuple[str, str, Callable[[], str]]] = [
    (
        "16.1 blocking",
        r"\*\*(\d+)\*\* blocking",
        lambda: str(scan().report()["blocking"]),
    ),
    (
        "16.1 standing",
        r"of \*\*(\d+)\*\* standing",
        lambda: str(scan().report()["standing"]),
    ),
    (
        "16.1 receipts",
        r"standing across \*\*(\d+)\*\* receipts",
        lambda: str(scan().report()["oracle_receipts"]),
    ),
    (
        "16.1 open debts",
        r"\*\*(\d+)\*\* open debts",
        lambda: str(scan().report()["by_kind"].get("open_debt", 0)),
    ),
    (
        "16.2 scheduled slices",
        r"`scheduled_slices` is \*\*(\d+)\*\*",
        lambda: str(
            receipt("receipt-walk-retirement-schedule.json")["scheduled_slices"]
        ),
    ),
    (
        "16.2 interpreter keys",
        r"holds exactly \*\*(\d+)\*\* `\(family, RECEIPT_WALK\)` keys",
        receipt_walk_interpreter_keys,
    ),
    (
        "16.2 packet mutation sites",
        r"\*\*(\d+)\*\* post-authoring packet-mutation sites",
        lambda: str(len(term_census()["sites"])),
    ),
    (
        "16.2 mitigation terms",
        r"\*\*(\d+)\*\* authoring-time mitigation terms",
        lambda: str(len(term_census()["authoring_time_terms"])),
    ),
    (
        "16.2 static holder amps",
        r"\*\*(\d+)\*\* static\s+holder amps",
        lambda: str(len(term_census()["static_holder_amps"])),
    ),
    (
        "16.3 slice tags",
        r"\*\*(\d+)\*\* slice tags derived from commit subjects",
        lambda: slice_tag_total_at(coverage_at(SECTION_16_3_ANCHOR)),
    ),
    (
        "16.3 recorded passes",
        r"\*\*(\d+)\*\* recorded\s+passes",
        lambda: pass_count(SECTION_16_3_ANCHOR),
    ),
    (
        "16.3 residue",
        r"a residue of \*\*(\d+)\*\*",
        lambda: residue_at(SECTION_16_3_ANCHOR),
    ),
    (
        "16.3 not discharged",
        r"\*\*(\d+)\*\* `NOT_DISCHARGED` rows",
        lambda: verdict_count(anchored_16_3(), "NOT_DISCHARGED"),
    ),
    (
        "16.3 documented_open",
        r"of which \*\*(\d+)\*\* stand",
        lambda: disposition_count(anchored_16_3(), "documented_open"),
    ),
    (
        "16.3 fixed",
        r"`documented_open`, (\d+) `fixed`",
        lambda: disposition_count(anchored_16_3(), "fixed"),
    ),
    (
        "16.3 fixed_and_gated",
        r"`fixed` and (\d+) `fixed_and_gated`",
        lambda: disposition_count(anchored_16_3(), "fixed_and_gated"),
    ),
    (
        "16.6 the gate's own size",
        r"\*\*(\d+)\*\* figures, the count itself among them",
        lambda: str(len(FIGURES_16)),
    ),
]


@pytest.mark.parametrize("case", FIGURES_16, ids=[case[0] for case in FIGURES_16])
def test_every_figure_section_16_states_is_the_measured_one(
    case: tuple[str, str, Callable[[], str]],
) -> None:
    """Section 16 closes two gap rows, so every count in it is re-derived."""
    _label, pattern, measured = case
    assert stated(section_16(), pattern) == measured()


@pytest.mark.parametrize("case", FIGURES_16, ids=[case[0] for case in FIGURES_16])
def test_the_section_16_gate_fails_when_a_stated_figure_drifts(
    case: tuple[str, str, Callable[[], str]],
) -> None:
    """R-05's permanent red for section 16, injected the same way as 15's."""
    _label, pattern, measured = case
    text = section_16()
    match = re.search(pattern, text)
    assert match is not None
    drifted = str(int(match.group(1)) + 1)
    doctored = text[: match.start(1)] + drifted + text[match.end(1) :]
    assert stated(doctored, pattern) != measured()


# --------------------------------------------------------------------------
# Completeness.
#
# Round 129's fifth finding is that this file's guarantee reads stronger than
# its check: section 15.6 says the file "re-derives every figure this section
# states", and what the file holds is a *list* of figures.  A figure added to a
# section later is silently ungated and the stated count still passes.
#
# So the sections are scanned instead.  Every bold integer -- the spelling both
# sections use for a figure they state -- is either matched by a figure
# pattern, matched by a check that lives outside ``FIGURES``, or named as an
# identifier with the reason it is not a count.  A sixth kind of number arriving
# in either section turns this red on the commit that writes it.
# --------------------------------------------------------------------------

#: How both sections spell a figure they state.
BOLD_FIGURE = re.compile(r"\*\*(\d+)\*\*")

#: The six non-numeric claims section 15.6 counts.  Named rather than counted
#: by introspection: the sentence is about these six assertions, and a rename
#: that silently kept the count would be the drift this file exists to catch.
CLAIM_TESTS = (
    "test_no_verifier_has_reached_the_p4_batch_range",
    "test_the_p4_batch_row_is_flagged_only_as_citing_a_body",
    "test_round_110_reads_on_round_6s_row_and_not_on_the_re_pin",
    "test_the_commit_that_closed_minor_4_is_verified_only_by_rounds_6_and_7",
    "test_the_three_groups_15_4_calls_five_each_really_hold_five",
    "test_every_phrase_15_quotes_from_section_14_is_really_there",
)

#: Figures a section states that are gated somewhere other than its ``FIGURES``
#: list.  Keeping them out of that list keeps the list's own stated size true.
ALSO_GATED_15: list[tuple[str, str, Callable[[], str]]] = [
    (
        "15.6 claims",
        r"figures and \*\*(\d+)\*\* claims",
        lambda: str(len(CLAIM_TESTS)),
    ),
]

#: Bold integers that NAME something -- a ledger round, a finding's ordinal --
#: rather than counting anything.  Each says why, and each names the check that
#: reads the thing it names, so an identifier cannot become a resting place for
#: an ungated count.
IDENTIFIERS_15: list[tuple[str, str]] = [
    (
        r"Round \*\*(110)\*\* verifies",
        "a ledger round number; test_round_110_reads_on_round_6s_row_and_not_on"
        "_the_re_pin asserts what that round holds",
    ),
    (
        r"rounds are \*\*(6)\*\* and",
        "a ledger round number; "
        "test_the_commit_that_closed_minor_4_is_verified_only_by_rounds_6_and_7"
        " asserts the pair",
    ),
    (
        r"\*\*6\*\* and \*\*(7)\*\*",
        "the other half of that pair, asserted by the same check",
    ),
    (
        r"which is finding \*\*(5)\*\*",
        "an ordinal naming one of round 6's findings, not a count of anything",
    ),
]

IDENTIFIERS_16: list[tuple[str, str]] = []


def covered_spans(
    section: str,
    figures: list[tuple[str, str, Callable[[], str]]],
    also: list[tuple[str, str, Callable[[], str]]],
    identifiers: list[tuple[str, str]],
) -> set[tuple[int, int]]:
    """Where in ``section`` a number is already accounted for."""
    spans: set[tuple[int, int]] = set()
    patterns = [pattern for _label, pattern, _measured in figures + also]
    patterns += [pattern for pattern, _reason in identifiers]
    for pattern in patterns:
        for match in re.finditer(pattern, section):
            spans.add(match.span(1))
    return spans


def ungated_figures(
    section: str,
    figures: list[tuple[str, str, Callable[[], str]]],
    also: list[tuple[str, str, Callable[[], str]]],
    identifiers: list[tuple[str, str]],
) -> list[str]:
    """Every bold integer in ``section`` that nothing here reads."""
    spans = covered_spans(section, figures, also, identifiers)
    return [
        section[max(0, match.start() - 60) : match.end()]
        for match in BOLD_FIGURE.finditer(section)
        if match.span(1) not in spans
    ]


def test_section_15_states_no_figure_this_file_does_not_read() -> None:
    """The guarantee 15.6 makes, asserted as a property instead of a list."""
    assert ungated_figures(section_15(), FIGURES, ALSO_GATED_15, IDENTIFIERS_15) == []


def test_section_16_states_no_figure_this_file_does_not_read() -> None:
    """The same property for the section that closes two gap rows."""
    assert ungated_figures(section_16(), FIGURES_16, [], IDENTIFIERS_16) == []


@pytest.mark.parametrize("section", ["15", "16"])
def test_the_completeness_scan_has_a_red_it_can_reproduce(section: str) -> None:
    """R-05, on the finding's own shape: a figure added to a section later."""
    text = section_15() if section == "15" else section_16()
    figures = FIGURES if section == "15" else FIGURES_16
    also = ALSO_GATED_15 if section == "15" else []
    identifiers = IDENTIFIERS_15 if section == "15" else IDENTIFIERS_16
    doctored = text + "\n\nA later pass measured **4321** of them.\n"
    assert ungated_figures(doctored, figures, also, identifiers)


@pytest.mark.parametrize("case", ALSO_GATED_15, ids=[case[0] for case in ALSO_GATED_15])
def test_every_figure_gated_outside_the_list_is_the_measured_one(
    case: tuple[str, str, Callable[[], str]],
) -> None:
    """15.6's count of its own non-numeric claims, re-derived from the names."""
    _label, pattern, measured = case
    assert stated(section_15(), pattern) == measured()


def test_every_claim_15_6_counts_is_a_check_this_file_holds() -> None:
    """A named claim that is not a test is a claim nobody runs."""
    source = Path(__file__).read_text(encoding="utf-8")
    for name in CLAIM_TESTS:
        assert f"def {name}(" in source, name


# --------------------------------------------------------------------------
# Section 17: the certification re-review.
#
# Its figures are read *live*, because they are facts about this tip -- except
# the two that are readings of the campaign's commit bodies, which grow with
# every commit and are therefore anchored the way every other moving reading in
# this file is.  The section states the anchor itself.
# --------------------------------------------------------------------------

#: The commit section 17.4's commit-body scan was run over.  A body-derived
#: figure moves with the next commit, including the one that states it, so it is
#: read at the tip it was measured on and the section says so.
SECTION_17_4_ANCHOR = "993f97e"

#: The file section 17.4's node-id correction is about.
SECTION_17_4_FILE = "tests/test_campaign_gap_ledger.py"

#: How a commit body declares node ids, in the three spellings the campaign
#: actually used.  This is not a parser for a declaration format -- there is no
#: such format, which is 17.4's finding -- it is the measurement that says so.
_DECLARES = (
    re.compile(r"[+](\d+)\s+(?:new\s+)?node ids?", re.I),
    re.compile(r"declar\w*\s+(\d+)\s+node ids?", re.I),
    re.compile(
        r"(declares no new node id|No new node id is declared|no node id is)", re.I
    ),
)


@lru_cache(maxsize=1)
def node_id_declarations() -> tuple[int, int]:
    """``(bodies a parser can read, bodies mentioning node ids it cannot)``."""
    out = subprocess.run(
        ["git", "log", "--format=%h\x1f%b\x1e", f"584071e..{SECTION_17_4_ANCHOR}"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=True,
    ).stdout
    parsed = unparsed = 0
    for chunk in out.split("\x1e"):
        chunk = chunk.strip()
        if not chunk or "\x1f" not in chunk:
            continue
        _sha, body = chunk.split("\x1f", 1)
        if "node id" not in body.lower():
            continue
        if any(pattern.search(body) for pattern in _DECLARES):
            parsed += 1
        else:
            unparsed += 1
    return parsed, unparsed


@lru_cache(maxsize=1)
def collected_node_ids() -> str:
    """How many node ids one test file holds at this tip, collected not counted."""
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", SECTION_17_4_FILE],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=True,
    ).stdout
    match = re.search(r"(\d+) tests? collected", out)
    assert match is not None, out[-400:]
    return match.group(1)


def anchored_17() -> list[dict]:
    """The passes section 17's verdict counts were measured over."""
    return ledger_at(SECTION_17_LEDGER_ANCHOR)["passes"]


def round_129() -> dict:
    """The pass section 17 is about."""
    return next(block for block in here() if block["round"] == 129)


def findings_with(disposition: str) -> str:
    """How many of round 129's findings carry this disposition."""
    return str(
        sum(
            1
            for row in round_129()["unmentioned_behaviour"]
            if row["disposition"] == disposition
        )
    )


#: Section 17's figures.  Live from the instruments they were measured with; the
#: body-derived pair is anchored, and the section names the anchor.
FIGURES_17: list[tuple[str, str, Callable[[], str]]] = [
    (
        "17.1 covered tags",
        r"Coverage moves to \*\*(\d+)\*\* tags",
        lambda: str(
            len(
                coverage_at(SECTION_17_LEDGER_ANCHOR)[
                    "slice_groups_with_a_verdict_in_this_ledger"
                ]
            )
        ),
    ),
    (
        "17.1 derived tags",
        r"tags with a verdict\s+of \*\*(\d+)\*\*",
        lambda: slice_tag_total_at(coverage_at(SECTION_17_LEDGER_ANCHOR)),
    ),
    (
        "17.1 residue",
        r"and the residue is \*\*(\d+)\*\*",
        lambda: residue_at(SECTION_17_LEDGER_ANCHOR),
    ),
    (
        "17.2 findings fixed",
        r"dispositioned: \*\*(\d+)\*\* fixed",
        lambda: findings_with("fixed"),
    ),
    (
        "17.2 findings documented",
        r"fixed and \*\*(\d+)\*\*\s+documented",
        lambda: findings_with("documented_open"),
    ),
    (
        "17.3 residue",
        r"The residue is \*\*(\d+)\*\*:",
        lambda: residue_at(SECTION_17_LEDGER_ANCHOR),
    ),
    (
        "17.3 prepared passes",
        r"prepares \*\*(\d+)\*\* startable",
        lambda: prepared_passes_at(SECTION_17_LEDGER_ANCHOR),
    ),
    (
        "17.3 not discharged",
        r"\*\*(\d+)\*\*\s+`NOT_DISCHARGED` rows stand",
        lambda: verdict_count(anchored_17(), "NOT_DISCHARGED"),
    ),
    (
        "17.3 recorded passes",
        r"the ledger's \*\*(\d+)\*\* passes",
        lambda: pass_count(SECTION_17_LEDGER_ANCHOR),
    ),
    (
        "17.3 documented_open",
        r"of which \*\*(\d+)\*\*\s+are `documented_open`",
        lambda: disposition_count(anchored_17(), "documented_open"),
    ),
    (
        "17.3 untagged commits",
        r"the \*\*(\d+)\*\* commits in the range",
        lambda: str(coverage_at(SECTION_17_LEDGER_ANCHOR)["untagged_commits"]),
    ),
    (
        "17.4 parseable declarations",
        r"\*\*(\d+)\*\* commit\s+bodies state a node-id declaration",
        lambda: str(node_id_declarations()[0]),
    ),
    (
        "17.4 unparseable mentions",
        r"\*\*(\d+)\*\* more mention node ids",
        lambda: str(node_id_declarations()[1]),
    ),
    (
        "17.4 node ids in the file",
        r"The file holds \*\*(\d+)\*\* node\s+ids",
        collected_node_ids,
    ),
    (
        "17.6 the gate's own size",
        r"\*\*(\d+)\*\* figures, the count itself among them",
        lambda: str(len(FIGURES_17)),
    ),
]


@pytest.mark.parametrize("case", FIGURES_17, ids=[case[0] for case in FIGURES_17])
def test_every_figure_section_17_states_is_the_measured_one(
    case: tuple[str, str, Callable[[], str]],
) -> None:
    """Section 17 states what a certification review is still owed, so it is read."""
    _label, pattern, measured = case
    assert stated(section_17(), pattern) == measured()


@pytest.mark.parametrize("case", FIGURES_17, ids=[case[0] for case in FIGURES_17])
def test_the_section_17_gate_fails_when_a_stated_figure_drifts(
    case: tuple[str, str, Callable[[], str]],
) -> None:
    """R-05's permanent red for section 17, injected as 15's and 16's are."""
    _label, pattern, measured = case
    text = section_17()
    match = re.search(pattern, text)
    assert match is not None
    drifted = str(int(match.group(1)) + 1)
    doctored = text[: match.start(1)] + drifted + text[match.end(1) :]
    assert stated(doctored, pattern) != measured()


def test_section_17_states_no_figure_this_file_does_not_read() -> None:
    """The completeness scan, over the section that ships it."""
    assert ungated_figures(section_17(), FIGURES_17, [], []) == []


def test_the_r01_verdict_table_section_17_states_carries_no_figure() -> None:
    """15.8's ruling, held: a gate reading is a verdict here, never a number."""
    table = section_17()[section_17().index("### 17.7") :]
    assert "GREEN" in table
    assert re.search(r"\*\*(\d+)\*\*", table) is None


# --------------------------------------------------------------------------
# The "no baseline moves in this pass" claim, in both sections that make it.
#
# Sections 16.7 and 17.7 each close with a sentence asserting that a range
# ending at ``HEAD`` is empty over R-32's five baselines.  A range ending at
# HEAD is a reading of the tip that wrote it, and both readings stopped being
# true at ``927964c`` -- the ``tests{collected}`` re-pin, legal under Amendment
# R-32's fourth carve-out, disclosed in its own body and on the receipt, and
# which left both sentences standing.  A certification reviewer found 17.7's
# copy; enumerating the population before the edit found that 16.7 carried the
# same sentence over a wider range.
#
# The dated clauses beside those sentences do not restate a reading.  They name
# a range that ends where it ends and otherwise assert *properties* -- the ones
# R-17, D-97 and the carve-out actually promise -- so a later legal re-pin keeps
# this green and a move outside the carve-out turns it red.  That is the whole
# difference between the clause and the sentence it corrects.
# --------------------------------------------------------------------------

#: R-32's five baselines, spelled as the runbook lists them.
R32_BASELINES = frozenset(
    {
        "scripts/golden_baseline.json",
        "scripts/golden_coupled_baseline.json",
        "scripts/golden_coupled_exact.json",
        "docs/receipts/campaign-fingerprints.json",
        "docs/receipts/item-coverage-classification.json",
    }
)

#: The two baselines R-01 rows 2 and 3 compare against.  The carve-out excludes
#: them by name, which is what keeps a lane's re-pin off the golden path.
COMPARED_BASELINES = frozenset(
    {"scripts/golden_baseline.json", "scripts/golden_coupled_baseline.json"}
)

#: The one baseline a lane may move, per Amendment R-32's carve-outs.
CARVE_OUT_BASELINE = "docs/receipts/campaign-fingerprints.json"

#: ``(section, where its range starts, the tip whose reading its sentence was)``.
BASELINE_CLAIMS = (("16.7", "04cdfbf", "3799bef"), ("17.7", "3799bef", "407428f"))

#: The commit both dated clauses name, and the end of the fixed range each
#: measures it in.
DATED_MOVER = "927964c"

#: Every range this report states the properties over: the two claimed ones and
#: section 18.5's, which is this pass's own.  18.5 is not in ``BASELINE_CLAIMS``
#: because it never claims its range empty -- it is the paragraph written the
#: way 18.1 corrected the two before it, and it is gated as what it says.
PROPERTY_RANGES = tuple(start for _section, start, _tip in BASELINE_CLAIMS) + (
    "407428f",
)


@lru_cache(maxsize=None)
def files_by_commit(rev_range: str) -> tuple[tuple[str, frozenset[str]], ...]:
    """``(sha, the files it touched)`` for every commit in a range."""
    out = subprocess.run(
        ["git", "log", "--name-only", "--format=%x1e%h", rev_range],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=True,
    ).stdout
    commits = []
    for chunk in out.split("\x1e"):
        lines = [line for line in chunk.splitlines() if line.strip()]
        if lines:
            commits.append((lines[0], frozenset(lines[1:])))
    return tuple(commits)


def touches_src(files: frozenset[str]) -> bool:
    """Whether a commit's file list holds a ``src/`` path."""
    return any(name.startswith("src/") for name in files)


def touches_gate_script(files: frozenset[str]) -> bool:
    """Whether it holds a gate script -- a ``scripts/`` module, in the carve-out."""
    return any(name.startswith("scripts/") and name.endswith(".py") for name in files)


def baseline_movers(commits: tuple[tuple[str, frozenset[str]], ...]) -> tuple[str, ...]:
    """Every commit in a range that moved one of R-32's five."""
    return tuple(sha for sha, files in commits if files & R32_BASELINES)


def commits_touching_both(
    commits: tuple[tuple[str, frozenset[str]], ...],
) -> tuple[str, ...]:
    """Criterion 10's population: a commit touching ``src/`` *and* a baseline."""
    return tuple(
        sha for sha, files in commits if files & R32_BASELINES and touches_src(files)
    )


def src_touchers(commits: tuple[tuple[str, frozenset[str]], ...]) -> tuple[str, ...]:
    """The half of both sentences that is still true, as a population."""
    return tuple(sha for sha, files in commits if touches_src(files))


def movers_outside_the_carve_out(
    commits: tuple[tuple[str, frozenset[str]], ...],
) -> tuple[str, ...]:
    """Every baseline move a lane was not entitled to make.

    Amendment R-32's fourth carve-out is four conditions, not one: the move is
    ``campaign-fingerprints.json`` and nothing else of the five, in a commit
    touching no ``src/``, no gate script and neither compared baseline.
    """
    outside = []
    for sha, files in commits:
        moved = files & R32_BASELINES
        if not moved:
            continue
        if (
            moved != {CARVE_OUT_BASELINE}
            or files & COMPARED_BASELINES
            or touches_src(files)
            or touches_gate_script(files)
        ):
            outside.append(sha)
    return tuple(outside)


@pytest.mark.parametrize("claim", BASELINE_CLAIMS, ids=[c[0] for c in BASELINE_CLAIMS])
def test_the_baseline_sentence_was_true_of_the_tip_that_wrote_it(
    claim: tuple[str, str, str],
) -> None:
    """A correction that misdates the sentence it corrects is one nobody can check."""
    _section, start, stating_tip = claim
    assert baseline_movers(files_by_commit(f"{start}..{stating_tip}")) == ()


@pytest.mark.parametrize("claim", BASELINE_CLAIMS, ids=[c[0] for c in BASELINE_CLAIMS])
def test_the_baseline_sentence_is_false_of_this_tip(
    claim: tuple[str, str, str],
) -> None:
    """R-05's red for the check above, and it is the reviewer's finding itself."""
    _section, start, _stating_tip = claim
    assert baseline_movers(files_by_commit(f"{start}..HEAD")) != ()


@pytest.mark.parametrize("claim", BASELINE_CLAIMS, ids=[c[0] for c in BASELINE_CLAIMS])
def test_the_dated_clause_names_the_only_mover_in_the_range_it_measures(
    claim: tuple[str, str, str],
) -> None:
    """The clause's one reading, over a range that ends where it ends."""
    _section, start, _stating_tip = claim
    assert baseline_movers(files_by_commit(f"{start}..{DATED_MOVER}")) == (DATED_MOVER,)


@pytest.mark.parametrize("start", PROPERTY_RANGES)
def test_no_src_moves_in_a_stated_range(start: str) -> None:
    """The half of both sentences that is still true, read live."""
    assert src_touchers(files_by_commit(f"{start}..HEAD")) == ()


@pytest.mark.parametrize("start", PROPERTY_RANGES)
def test_no_commit_in_a_stated_range_touches_both_src_and_a_baseline(
    start: str,
) -> None:
    """Criterion 10 over the same ranges -- the rule the sentence stood in for."""
    assert commits_touching_both(files_by_commit(f"{start}..HEAD")) == ()


@pytest.mark.parametrize("start", PROPERTY_RANGES)
def test_every_baseline_move_in_a_stated_range_is_inside_the_carve_out(
    start: str,
) -> None:
    """The property that replaces the reading: a legal re-pin stays green."""
    assert movers_outside_the_carve_out(files_by_commit(f"{start}..HEAD")) == ()


#: Four commits that are not in the tree, each breaking one of the carve-out's
#: four conditions, plus one touching both.  R-05's seam for the property
#: checks: a check whose red cannot be produced on demand is indistinguishable
#: from one that passes.
DOCTORED_MOVERS = (
    (
        "a second baseline",
        (
            "deadbe1",
            frozenset({CARVE_OUT_BASELINE, "scripts/golden_coupled_exact.json"}),
        ),
    ),
    ("a compared baseline", ("deadbe2", frozenset({"scripts/golden_baseline.json"}))),
    (
        "src/ beside it",
        ("deadbe3", frozenset({CARVE_OUT_BASELINE, "src/calculator/pipeline.py"})),
    ),
    (
        "a gate script",
        ("deadbe4", frozenset({CARVE_OUT_BASELINE, "scripts/golden_snapshot.py"})),
    ),
)


@pytest.mark.parametrize(
    "case", DOCTORED_MOVERS, ids=[label for label, _commit in DOCTORED_MOVERS]
)
def test_the_carve_out_check_has_a_red_it_can_reproduce(
    case: tuple[str, tuple[str, frozenset[str]]],
) -> None:
    """Each of the carve-out's four conditions, broken one at a time."""
    _label, commit = case
    assert movers_outside_the_carve_out((commit,)) == (commit[0],)


def test_the_criterion_10_check_has_a_red_it_can_reproduce() -> None:
    """A commit touching both, which no commit in either range does."""
    doctored = (
        "deadbe5",
        frozenset({CARVE_OUT_BASELINE, "src/calculator/pipeline.py"}),
    )
    assert commits_touching_both((doctored,)) == ("deadbe5",)


def test_the_src_check_has_a_red_it_can_reproduce() -> None:
    """The other half of both sentences, failed on demand."""
    doctored = ("deadbe6", frozenset({"src/calculator/pipeline.py"}))
    assert src_touchers((doctored,)) == ("deadbe6",)


# --------------------------------------------------------------------------
# Section 18: the third certification review.
#
# Its figures are read live, from the report's own text for the enumerated
# population and from this module for the rest.  The population is a *scan* and
# not a list, which is round 129's fifth finding applied one level up: a sixth
# sentence claiming a range free of baseline moves turns this red on the commit
# that writes it, rather than sitting outside an enumeration somebody wrote.
# --------------------------------------------------------------------------

#: How this report spells a claim that a commit or a range is free of moves over
#: R-32's five baselines.  Both spellings the report actually uses -- the five
#: are named directly in four places and once by the sentence that scopes itself
#: to a lane instead of a range.
BASELINE_CLAIM_SITE = re.compile(r"R-32's five|No baseline moves in this lane")

#: How this module spells a check parametrised over one of the two populations.
PARAMETRISED_CHECK = re.compile(
    r"@pytest\.mark\.parametrize\(\s*\n?\s*\"(?:claim|start)\","
    r"\s*(?:BASELINE_CLAIMS|PROPERTY_RANGES)"
)


def baseline_claim_sites() -> str:
    """How many sentences in the report make the claim 18.1 enumerates."""
    return str(len(BASELINE_CLAIM_SITE.findall(REPORT.read_text(encoding="utf-8"))))


def parametrised_checks() -> str:
    """How many checks carry 18.1's correction, counted from this file."""
    source = Path(__file__).read_text(encoding="utf-8")
    return str(len(PARAMETRISED_CHECK.findall(source)))


#: Section 18's figures.
FIGURES_18: list[tuple[str, str, Callable[[], str]]] = [
    (
        "18.1 claim sites",
        r"\*\*(\d+)\*\* sentences in this report assert",
        baseline_claim_sites,
    ),
    (
        "18.1 qualifying",
        r"\*\*(\d+)\*\* of them\s+qualify",
        lambda: str(len(BASELINE_CLAIMS)),
    ),
    (
        "18.4 parametrised checks",
        r"\*\*(\d+)\*\* parametrised checks",
        parametrised_checks,
    ),
    (
        "18.4 the gate's own size",
        r"\*\*(\d+)\*\* figures, the count itself among them",
        lambda: str(len(FIGURES_18)),
    ),
]


@pytest.mark.parametrize("case", FIGURES_18, ids=[case[0] for case in FIGURES_18])
def test_every_figure_section_18_states_is_the_measured_one(
    case: tuple[str, str, Callable[[], str]],
) -> None:
    """Section 18 states what a third review found, so every count in it is read."""
    _label, pattern, measured = case
    assert stated(section_18(), pattern) == measured()


@pytest.mark.parametrize("case", FIGURES_18, ids=[case[0] for case in FIGURES_18])
def test_the_section_18_gate_fails_when_a_stated_figure_drifts(
    case: tuple[str, str, Callable[[], str]],
) -> None:
    """R-05's permanent red for section 18, injected as 15's, 16's and 17's are."""
    _label, pattern, measured = case
    text = section_18()
    match = re.search(pattern, text)
    assert match is not None
    drifted = str(int(match.group(1)) + 1)
    doctored = text[: match.start(1)] + drifted + text[match.end(1) :]
    assert stated(doctored, pattern) != measured()


def test_section_18_states_no_figure_this_file_does_not_read() -> None:
    """The completeness scan, over the section that ships it."""
    assert ungated_figures(section_18(), FIGURES_18, [], []) == []


def test_the_completeness_scan_reds_on_section_18() -> None:
    """R-05 for the scan on this section, as the 15/16 parametrisation does."""
    doctored = section_18() + "\n\nA later pass measured **4321** of them.\n"
    assert ungated_figures(doctored, FIGURES_18, [], [])


def test_the_r01_verdict_table_section_18_states_carries_no_figure() -> None:
    """15.8's ruling, held one section further on."""
    table = section_18()[section_18().index("### 18.5") :]
    assert "GREEN" in table
    assert re.search(r"\*\*(\d+)\*\*", table) is None


# --------------------------------------------------------------------------
# Section 19: the fourth certification review.
#
# Its ledger figures are read *live*, because they are facts about this tip and
# this pass moved one of them itself -- the residue, which grew by the tag of
# the pass writing the section.  Its counter figures are the pair the review's
# minor is about: the reading section 5 states at the tip the report was
# written on, read out of git there, and the tip's own, read by re-running the
# instrument.  The movement population is derived by the migration frontier's
# own gate, which is where that derivation belongs; this file imports it rather
# than spelling it a second time.
# --------------------------------------------------------------------------

#: The tip section 5's frontier readings are dated at, by the report's header.
SECTION_5_TIP = "067c94c"


@lru_cache(maxsize=1)
def migration_frontier():
    """The frontier instrument, imported by path as the other scripts are."""
    spec = importlib.util.spec_from_file_location(
        "migration_frontier", ROOT / "scripts" / "migration_frontier.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("migration_frontier", module)
    spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=1)
def frontier_gate():
    """The migration frontier's own suite, for its movement derivation.

    Imported rather than re-implemented: a movement is a value one commit's
    receipt records differently from its parent's, and two spellings of that
    derivation are two things that can disagree about what moved.
    """
    spec = importlib.util.spec_from_file_location(
        "test_migration_frontier", ROOT / "tests" / "test_migration_frontier.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("test_migration_frontier", module)
    spec.loader.exec_module(module)
    return module


def counter_6_kernel_at(sha: str) -> str:
    """Counter 6's kernel value as the receipt at one commit records it."""
    blob = subprocess.run(
        ["git", "show", f"{sha}:docs/migration-frontier.json"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=True,
    ).stdout
    return str(json.loads(blob)["counters"]["counter_6"]["kernel_value"])


def counter_movements_since_the_report() -> list[tuple[str, str, str, int, int]]:
    """Every migration-frontier counter movement after section 5's tip."""
    return frontier_gate().counter_movements(f"{SECTION_5_TIP}..HEAD")


def movements_naming_their_cause() -> str:
    """How many of those movements the moving commit's own body states.

    Counted against the frontier gate's own unexplained list rather than by
    re-applying its predicate here: what counts as a named cause has one home,
    and a second application of it is a second thing that can drift.
    """
    unexplained = frontier_gate().movements_without_a_named_cause(
        f"{SECTION_5_TIP}..HEAD"
    )
    return str(len(counter_movements_since_the_report()) - len(unexplained))


def anchored_19() -> list[dict]:
    """The passes section 19's verdict counts were measured over."""
    return ledger_at(SECTION_19_LEDGER_ANCHOR)["passes"]


#: Section 19's figures.  The five ledger readings of 19.1 are anchored at the
#: commit that stated them; 19.2's and 19.5's are read live, because the frontier
#: counters and the gate's own size are properties of the tip by construction.
FIGURES_19: list[tuple[str, str, Callable[[], str]]] = [
    (
        "19.1 residue",
        r"The residue is \*\*(\d+)\*\*",
        lambda: residue_at(SECTION_19_LEDGER_ANCHOR),
    ),
    (
        "19.1 prepared passes",
        r"prepares \*\*(\d+)\*\* startable passes",
        lambda: prepared_passes_at(SECTION_19_LEDGER_ANCHOR),
    ),
    (
        "19.1 not discharged",
        r"\*\*(\d+)\*\* `NOT_DISCHARGED` rows",
        lambda: verdict_count(anchored_19(), "NOT_DISCHARGED"),
    ),
    (
        "19.1 passes",
        r"the ledger's \*\*(\d+)\*\*\s+passes",
        lambda: str(len(anchored_19())),
    ),
    (
        "19.1 documented_open",
        r"of which \*\*(\d+)\*\* are `documented_open`",
        lambda: disposition_count(anchored_19(), "documented_open"),
    ),
    (
        "19.2 the reading section 5 states",
        r"counter 6's kernel value read \*\*(\d+)\*\*",
        lambda: counter_6_kernel_at(SECTION_5_TIP),
    ),
    (
        "19.2 the tip's reading",
        r"This tip\s+reads \*\*(\d+)\*\*",
        lambda: str(migration_frontier().scan().counter_6_kernel),
    ),
    (
        "19.2 movements since",
        r"\*\*(\d+)\*\* commit in `067c94c\.\.HEAD` moved",
        lambda: str(len(counter_movements_since_the_report())),
    ),
    (
        "19.2 movements naming their cause",
        r"counter and \*\*(\d+)\*\* states the move",
        movements_naming_their_cause,
    ),
    (
        "19.5 the gate's own size",
        r"\*\*(\d+)\*\* figures, the count itself among them",
        lambda: str(len(FIGURES_19)),
    ),
]


@pytest.mark.parametrize("case", FIGURES_19, ids=[case[0] for case in FIGURES_19])
def test_every_figure_section_19_states_is_the_measured_one(
    case: tuple[str, str, Callable[[], str]],
) -> None:
    """Section 19 answers a fourth review, so every count in it is re-derived."""
    _label, pattern, measured = case
    assert stated(section_19(), pattern) == measured()


@pytest.mark.parametrize("case", FIGURES_19, ids=[case[0] for case in FIGURES_19])
def test_the_section_19_gate_fails_when_a_stated_figure_drifts(
    case: tuple[str, str, Callable[[], str]],
) -> None:
    """R-05's permanent red for section 19, injected as every section's is."""
    _label, pattern, measured = case
    text = section_19()
    match = re.search(pattern, text)
    assert match is not None
    drifted = str(int(match.group(1)) + 1)
    doctored = text[: match.start(1)] + drifted + text[match.end(1) :]
    assert stated(doctored, pattern) != measured()


def test_section_19_states_no_figure_this_file_does_not_read() -> None:
    """The completeness scan, over the section that ships it."""
    assert ungated_figures(section_19(), FIGURES_19, [], []) == []


def test_the_completeness_scan_reds_on_section_19() -> None:
    """R-05 for the scan on this section, as 15, 16 and 18's do."""
    doctored = section_19() + "\n\nA later pass measured **4321** of them.\n"
    assert ungated_figures(doctored, FIGURES_19, [], [])


def test_the_r01_verdict_table_section_19_states_carries_no_figure() -> None:
    """15.8's ruling, held one section further on again."""
    table = section_19()[section_19().index("### 19.6") :]
    assert "GREEN" in table
    assert re.search(r"\*\*(\d+)\*\*", table) is None
