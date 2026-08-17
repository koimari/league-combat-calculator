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

#: The commit that wrote section 15.5.  Its coverage figures were "about this
#: tip" when they were written and stopped being so the moment another slice
#: group shipped -- which is a thing the campaign expects to happen, not a
#: defect in the section.  So they are read where every other moving reading in
#: this file is read: at the commit that stated them, out of git.  The anchor is
#: named rather than inferred, so moving it is a deliberate act.
SECTION_15_5_ANCHOR = "e4338b7"


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
    """The report from its section 16 heading to the end of the file."""
    text = REPORT.read_text(encoding="utf-8")
    return text[text.index("\n## 16.") :]


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
        lambda: slice_tag_total_at(ledger()["coverage"]),
    ),
    (
        "16.3 recorded passes",
        r"\*\*(\d+)\*\* recorded\s+passes",
        lambda: str(len(here())),
    ),
    (
        "16.3 residue",
        r"a residue of \*\*(\d+)\*\*",
        lambda: str(ledger()["coverage"]["residue"]),
    ),
    (
        "16.3 not discharged",
        r"\*\*(\d+)\*\* `NOT_DISCHARGED` rows",
        lambda: verdict_count(here(), "NOT_DISCHARGED"),
    ),
    (
        "16.3 documented_open",
        r"of which \*\*(\d+)\*\* stand",
        lambda: disposition_count(here(), "documented_open"),
    ),
    (
        "16.3 fixed",
        r"`documented_open`, (\d+) `fixed`",
        lambda: disposition_count(here(), "fixed"),
    ),
    (
        "16.3 fixed_and_gated",
        r"`fixed` and (\d+) `fixed_and_gated`",
        lambda: disposition_count(here(), "fixed_and_gated"),
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
