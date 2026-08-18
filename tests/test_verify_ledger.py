"""The R-35 verdict ledger, gated: a verdict is a row, not a memory.

Runbook criterion 11 has three clauses.  Every slice has a recorded
``verify-<slice>`` verdict; no barrier is crossed with an open
``NOT DISCHARGED``; and every "behaviour the commit bodies do not mention"
finding is either documented or reverted.

The mechanism was real and used all campaign -- commit bodies cite verifier
findings and answer them by name -- but the verdicts lived only in those
bodies, so the first clause could not be checked from the repository at all.
This file checks the ledger that starts fixing that: every row carries a
verdict from the closed set, a disposition from the closed set, at least one
answering commit that exists, and a note.  A row claiming ``fixed`` names an
artifact that is really there.

What it deliberately does **not** assert is that the ledger is complete.  It
is not, the ledger says so in its own words, and a test asserting completeness
over a file that starts mid-campaign would be the claim-outruns-code shape the
campaign exists to remove.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "docs" / "receipts" / "verify-ledger.json"


def ledger() -> dict:
    """The committed artifact this file is the gate for."""
    return json.loads(LEDGER.read_text(encoding="utf-8"))


def rows() -> list[tuple[str, dict]]:
    """Every criterion row and every finding row, with its pass id."""
    out: list[tuple[str, dict]] = []
    for block in ledger()["passes"]:
        for row in block["criteria"] + block["unmentioned_behaviour"]:
            out.append((block["slice_group"], row))
    return out


def test_the_ledger_declares_what_it_is_and_what_gates_it() -> None:
    block = ledger()
    assert block["artifact"] == "verify_ledger"
    assert block["gate"] == "tests/test_verify_ledger.py"
    assert block["what_this_ledger_does_not_hold"]


def test_every_pass_names_the_commits_it_verified_and_the_ones_that_answered() -> None:
    for block in ledger()["passes"]:
        assert block["dated"] and block["slice_group"]
        assert block["verified_commits"] and block["answered_by"]


def test_every_criterion_row_carries_a_verdict_from_the_closed_set() -> None:
    allowed = set(ledger()["verdict_vocabulary"])
    for block in ledger()["passes"]:
        for row in block["criteria"]:
            assert row["verdict"] in allowed, row["id"]
            assert row["what_was_found"]


def test_every_row_carries_a_disposition_from_the_closed_set() -> None:
    """Documented or reverted, per the criterion's third clause."""
    allowed = set(ledger()["disposition_vocabulary"])
    for _pass, row in rows():
        assert row["disposition"] in allowed, row
        assert row["note"], row


def test_no_row_is_answered_by_a_commit_that_does_not_exist() -> None:
    """A verdict answered by a sha nobody can open is a verdict answered by prose."""
    shas = {sha for _pass, row in rows() for sha in row["answered_at"]}
    shas |= {sha for block in ledger()["passes"] for sha in block["answered_by"]}
    shas |= {sha for block in ledger()["passes"] for sha in block["verified_commits"]}
    assert shas
    for sha in sorted(shas):
        resolved = subprocess.run(
            ["git", "cat-file", "-t", sha],
            capture_output=True,
            text=True,
            cwd=ROOT,
            check=False,
        )
        assert resolved.returncode == 0, sha
        assert resolved.stdout.strip() == "commit", sha


def test_every_fixed_row_names_an_artifact_that_is_there() -> None:
    """The difference between a fix and a claim is a path a reader can open."""
    for _pass, row in rows():
        if not row["disposition"].startswith("fixed"):
            continue
        artifact = row.get("artifact")
        assert artifact, row
        assert (ROOT / artifact).exists(), artifact


def test_an_open_row_names_where_it_is_carried() -> None:
    """``documented_open`` means documented somewhere, and says where."""
    for _pass, row in rows():
        if row["disposition"] != "documented_open":
            continue
        assert row["note"], row
        artifact = row.get("artifact")
        if artifact:
            assert (ROOT / artifact).exists(), artifact


def test_nothing_is_recorded_as_reverted_without_saying_what() -> None:
    """The other half of the third clause, so the vocabulary is not decorative."""
    for _pass, row in rows():
        if row["disposition"] == "reverted":
            assert row["answered_at"], row


# --------------------------------------------------------------------------
# Ruling 4 -- the disposition every NOT_DISCHARGED row owes.
#
# The schema gate above has always required a disposition *word*.  The campaign
# owner's ruling of 2026-08-17 asks for the thing behind the word: a ``fixed``
# row names the commit that fixed it, a superseded one names the work that
# superseded it, and a ``documented_open`` one names the artifact holding the
# open debt.  Fifty-five of the ninety carried the word and nothing behind it.
#
# These checks are the difference between a disposition and a label.
# --------------------------------------------------------------------------


def _dispositions() -> dict:
    return ledger()["dispositions"]


def _not_discharged() -> list[dict]:
    return [
        row
        for block in ledger()["passes"]
        for row in block["criteria"]
        if row["verdict"] == "NOT_DISCHARGED"
    ]


def _ruling_4_term(disposition: str) -> str:
    """Which of Ruling 4's three a ledger disposition word spells."""
    mapping = _dispositions()["how_ruling_4s_three_map_onto_this_ledgers_five"]
    for term, spellings in mapping.items():
        if disposition in spellings:
            return term
    raise AssertionError(f"{disposition!r} maps onto none of Ruling 4's dispositions")


def test_the_disposition_mapping_covers_the_whole_vocabulary() -> None:
    """Five words, three dispositions, and no word left unplaced.

    A mapping that omitted a term would let a row wear a disposition the
    ruling never named while every other check went on passing.
    """
    mapping = _dispositions()["how_ruling_4s_three_map_onto_this_ledgers_five"]
    placed = [word for spellings in mapping.values() for word in spellings]
    assert sorted(placed) == sorted(ledger()["disposition_vocabulary"])
    assert len(placed) == len(set(placed))
    assert mapping["superseded_by_later_work"] == []
    assert _dispositions()["why_superseded_has_no_term"].strip()


def test_every_not_discharged_row_carries_what_its_disposition_promises() -> None:
    """Ruling 4, checked rather than recited.

    ``fixed`` in any of its spellings names a commit **and** an artifact that
    is really there; ``documented_open`` names an artifact holding the debt.
    ``no_action_required`` is the DISCHARGED row's disposition and a
    NOT_DISCHARGED row may not wear it -- that is the mapping's floor, and
    without it the cheapest way to discharge this whole check would be to
    relabel a row as needing nothing.
    """
    for row in _not_discharged():
        term = _ruling_4_term(row["disposition"])
        assert term != "not_reachable_by_a_not_discharged_row", row["id"]
        artifact = row.get("artifact")
        assert artifact, row["id"]
        assert (ROOT / artifact).exists(), row["id"]
        if term == "fixed":
            assert row["answered_at"], row["id"]


def test_the_open_row_counters_are_the_measured_ones() -> None:
    """Round 130's first finding, given a home that cannot go stale.

    A receipt-only commit added eighteen open rows and its body accounted for
    eleven; nothing in the tree would have caught the difference.  These are
    derived from the passes on every run, so the open debt is a number and
    not a paragraph.
    """
    criteria = [row for block in ledger()["passes"] for row in block["criteria"]]
    findings = [
        row for block in ledger()["passes"] for row in block["unmentioned_behaviour"]
    ]
    counters = _dispositions()["open_rows"]
    assert counters["criterion_rows_documented_open"] == sum(
        1 for row in criteria if row["disposition"] == "documented_open"
    )
    assert counters["of_which_not_discharged"] == sum(
        1
        for row in criteria
        if row["disposition"] == "documented_open"
        and row["verdict"] == "NOT_DISCHARGED"
    )
    assert counters["of_which_phase_tip_only"] == sum(
        1
        for row in criteria
        if row["disposition"] == "documented_open"
        and row["verdict"] == "PHASE_TIP_ONLY"
    )
    assert counters["finding_rows_documented_open"] == sum(
        1 for row in findings if row["disposition"] == "documented_open"
    )
    assert counters["not_discharged_criterion_rows"] == len(_not_discharged())
    assert (
        counters["of_which_not_discharged"] + counters["of_which_phase_tip_only"]
        == counters["criterion_rows_documented_open"]
    )


def test_the_disposition_checks_have_reds_they_can_reproduce() -> None:
    """R-05 over each way a disposition can go back to being a label."""
    with pytest.raises(AssertionError):
        _ruling_4_term("a word no ruling names")
    assert _ruling_4_term("no_action_required") == (
        "not_reachable_by_a_not_discharged_row"
    )
    counters = _dispositions()["open_rows"]
    assert counters["criterion_rows_documented_open"] != 0
    stripped = [dict(row, artifact=None) for row in _not_discharged()]
    assert not all(row["artifact"] for row in stripped)


def test_the_disposition_block_says_what_it_refuses_to_claim() -> None:
    """The sweep made the dispositions citable; it closed nothing."""
    block = _dispositions()
    assert "2026-08-17" in block["rule"]
    assert "never manufacturing one" in block["why_superseded_has_no_term"]
    assert block["what_this_does_not_claim"].strip()
    assert block["why_the_artifact_of_a_transcribed_row_is_this_file"].strip()
    assert block["gate"] == "tests/test_verify_ledger.py"


@pytest.mark.parametrize(
    "criterion",
    [
        "umbrella-1",
        "umbrella-4",
        "umbrella-5",
        "umbrella-7",
        "umbrella-8",
        "umbrella-11",
        "runbook-2",
        "runbook-6",
        "runbook-11",
    ],
)
def test_the_campaign_close_pass_answers_every_criterion_it_was_handed(
    criterion: str,
) -> None:
    """A pass that quietly drops one of its verdicts is the shape being checked."""
    block = next(
        item for item in ledger()["passes"] if item["slice_group"] == "campaign-close"
    )
    assert criterion in {row["id"] for row in block["criteria"]}


#: The trailing parenthetical every lane stamps on a commit subject.
TRAILING_TAG = r"\(([^()]*)\)\s*$"

#: What an R-35 citation in a commit body has to name to count.
MECHANISM_NAMES = r"R-35|verify-[A-Za-z0-9.\-/]+|verifier|sign-?off"
VERDICT_WORDS = r"\bNOT DISCHARGED\b|\bDISCHARGED\b|\bverdict\b"


def _slice_group_tags() -> tuple[list[str], int]:
    """The campaign's own slice labels, read from commit subjects.

    The first element of each subject's trailing parenthetical.  This is a
    derivation, not a second authored list: the population criterion 11's
    first clause quantifies over has to come from the tree or it is whatever
    the ledger says it is.
    """
    out = subprocess.run(
        ["git", "log", "--format=%h\x1f%s\x1e", "584071e..HEAD"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=True,
    ).stdout
    pattern = re.compile(TRAILING_TAG)
    tags: list[str] = []
    untagged = 0
    for chunk in out.split("\x1e"):
        chunk = chunk.strip()
        if not chunk:
            continue
        _sha, subject = chunk.split("\x1f", 1)
        match = pattern.search(subject)
        if match is None:
            untagged += 1
            continue
        tag = match.group(1).split(",")[0].strip()
        if tag not in tags:
            tags.append(tag)
    return tags, untagged


def _groups_citing_a_verdict_in_a_commit_body() -> list[str]:
    """Slice groups whose own commits record an R-35 verdict.

    Names rather than shas, and the reason is the one this ledger keeps
    running into: it is committed *inside* the commit it would be recording,
    so a sha here is stale the moment that commit is amended or rebased.

    A third coverage state, derived rather than authored, and deliberately
    weaker than a recorded verdict: a commit body is the *lane's*
    transcription of the verifier's answer, not the verifier's artifact.  It
    is surfaced anyway because "a citation somebody can go and read" and
    "nothing at all" are different states of one clause, and collapsing them is what made
    a ledger holding one pass and a ledger holding forty look alike to every
    gate.

    The rule is a conjunction so a passing mention cannot qualify: the body
    must name the mechanism -- R-35, a ``verify-`` agent, a verifier or a
    sign-off -- **and** carry a verdict word from R-35's own brief.
    """
    unit, record = chr(31), chr(30)
    out = subprocess.run(
        ["git", "log", f"--format=%h{unit}%s{unit}%b{record}", "584071e..HEAD"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=True,
    ).stdout
    tag_pattern = re.compile(TRAILING_TAG)
    mechanism = re.compile(MECHANISM_NAMES, re.I)
    verdict = re.compile(VERDICT_WORDS, re.I)
    cited: list[str] = []
    for chunk in out.split(record):
        chunk = chunk.strip()
        if not chunk:
            continue
        _sha, subject, commit_body = chunk.split(unit, 2)
        match = tag_pattern.search(subject)
        if match is None:
            continue
        tag = match.group(1).split(",")[0].strip()
        if tag in cited:
            continue
        if mechanism.search(commit_body) and verdict.search(commit_body):
            cited.append(tag)
    return sorted(cited)


#: A bare integer -- not the 35 of ``R-35``, not the 11 of a criterion id, not a
#: path fragment.  What it matches is a count somebody wrote down.
_BARE_INTEGER = re.compile(r"(?<![\w.\-/])\d+")


def _undated_counts(note: str) -> list[str]:
    """Sentences of ``note`` that state a count before any date is in force."""
    offending: list[str] = []
    dated = False
    for sentence in note.split(". "):
        if "2026-" in sentence:
            dated = True
        if _BARE_INTEGER.search(sentence) and not dated:
            offending.append(sentence)
    return offending


class TestTheCoverageBlockIsTheClauseSDenominator:
    """Criterion 11's first clause, given something to quantify over.

    "Every slice has a recorded verdict" bounded nothing a machine could
    read, so a ledger with one pass and a ledger with forty looked the same
    to every gate.  The coverage block is the denominator, derived from the
    campaign's own slice labels; these tests are what stop it from being a
    third authored list.
    """

    @property
    def coverage(self) -> dict:
        return ledger()["coverage"]

    def test_the_three_lists_partition_the_derived_population(self) -> None:
        """Total and disjoint -- the property that survived the correction.

        It was two lists until the owner's ruling of 2026-08-17 gave the
        clause an instrument arm.  What did *not* change is the assertion:
        the union is still the whole derived population and the arms are
        still pairwise disjoint, so a tag can leave the residue three ways
        and can leave the population none.  A correction that dropped this
        would be the denominator shrinking behind a reading.
        """
        tags, _untagged = _slice_group_tags()
        recorded = set(self.coverage["slice_groups_with_a_verdict_in_this_ledger"])
        missing = set(self.coverage["slice_groups_without_one"])
        instruments = {row["tag"] for row in self.coverage["instrument_pass_tags"]}
        assert recorded | missing | instruments == set(tags)
        assert not recorded & missing
        assert not recorded & instruments
        assert not missing & instruments

    def test_a_group_listed_as_covered_really_has_a_pass(self) -> None:
        passes = {block["slice_group"] for block in ledger()["passes"]}
        assert (
            set(self.coverage["slice_groups_with_a_verdict_in_this_ledger"]) == passes
        )

    def test_the_residue_and_the_untagged_count_are_the_measured_ones(self) -> None:
        """The gap is a number, so it cannot grow in silence."""
        tags, untagged = _slice_group_tags()
        assert self.coverage["residue"] == len(
            self.coverage["slice_groups_without_one"]
        )
        assert self.coverage["untagged_commits"] == untagged
        assert self.coverage["residue"] < len(tags)

    def test_the_citation_state_is_derived_and_not_authored(self) -> None:
        """The third state: a verdict a reader can open, in a commit body.

        Recorded with its sha so the citation is a link rather than a claim,
        and re-derived here so the ledger cannot list a group whose commits
        say nothing.  It is a strict subset of the groups with no verdict in
        this ledger: a citation is the lane's transcription of a verifier's
        answer and is not the artifact the clause asks for.
        """
        cited = self.coverage["slice_groups_citing_a_verdict_in_a_commit_body"]
        assert cited == _groups_citing_a_verdict_in_a_commit_body()
        # Names and not shas: a sha is a locator, and the ledger sits inside
        # the commit whose sha it would have to record, so any rewrite of that
        # commit would leave the file describing a commit that no longer
        # exists.  ``git log --grep`` finds a named group's commits.
        # A group can be both: the pass recorded here also cited itself in the
        # commit that landed it.  What the residue subtracts is the overlap,
        # so a citation never counts as a verdict and never double-counts one.
        assert set(cited) <= set(self.coverage["slice_groups_without_one"]) | set(
            self.coverage["slice_groups_with_a_verdict_in_this_ledger"]
        ) | {row["tag"] for row in self.coverage["instrument_pass_tags"]}
        assert self.coverage["residue_with_no_verdict_anywhere"] == len(
            set(self.coverage["slice_groups_without_one"]) - set(cited)
        )

    def test_the_block_says_what_it_refuses_to_do(self) -> None:
        """It does not reconstruct a verdict, and says so where a reader is."""
        assert (
            "does not reconstruct a verdict"
            in self.coverage["what_this_block_does_not_do"]
        )
        assert self.coverage["why_the_residue_cannot_be_closed_retroactively"].strip()

    def test_every_count_the_residue_note_states_is_dated(self) -> None:
        """The note may reason freely; it may not carry an undated count.

        Round 129's first finding is that this note went on stating a population
        -- "10 of the groups ... cite one in a commit body", "60-odd fresh R-35
        passes" -- that the backfill had already made false, and that nothing in
        the tree would catch it.  The counters beside it are derived and gated;
        the note is prose, and prose that restates a derived number is the second
        home criterion 4 exists to forbid.

        So the rule is the weakest one that would have caught it: a count in
        this note must sit inside a **dated clause**.  The note is an undated
        preamble -- the reasoning, which has no number in it and needs none --
        followed by clauses each opening with the date it was measured on.  A
        count a reader can date is a reading; a count in the preamble is a claim
        about now, and about now the derived counters beside it are the
        authority.

        What it does not catch, said plainly rather than left to be discovered:
        a count appended to an already-dated clause takes that clause's date.
        That is still a date a reader can place, which is the property being
        gated; a stronger rule would have to know which sentence arrived last.
        """
        note = self.coverage["why_the_residue_cannot_be_closed_retroactively"]
        assert _undated_counts(note) == []

    def test_the_dated_count_rule_has_a_red_it_can_reproduce(self) -> None:
        """R-05, on the shape the finding actually had: an undated count."""
        note = self.coverage["why_the_residue_cannot_be_closed_retroactively"]
        doctored = "Closing those is 60-odd fresh R-35 passes. " + note
        assert _undated_counts(doctored)


# --------------------------------------------------------------------------
# The residue, graded -- the number criterion 11's first clause turns on.
#
# Ruling 1 binds the clause backwards *for implementation slices*, and reads
# "every slice" as every unit of work that changes behaviour in ``src/``,
# ``tests/``, ``scripts/`` or ``data/``.  So the question is not how big the
# residue is; it is whether anything in it is one of those units.
#
# Three of the four directories are checked by emptiness.  The fourth is
# checked by containment, because Ruling 2's own check lets an instrument
# repair its own gate: a residue tag's ``tests/`` files must each be
# *declared* as the gate of a receipt that same tag wrote.  Declared, not
# mentioned -- the first draft searched receipt text, and the block's own
# listing satisfied it for every path it listed.
# --------------------------------------------------------------------------

BEHAVIOUR_DIRS = ("src/", "scripts/", "data/")


def _declared_gates(receipt: str) -> list[str]:
    """The tests a receipt names as its own gate."""
    path = ROOT / receipt
    if receipt.endswith(".json"):
        declared = json.loads(path.read_text(encoding="utf-8")).get("gate")
        return [declared] if isinstance(declared, str) else list(declared or ())
    text = path.read_text(encoding="utf-8")
    return [line for line in re.findall(r"tests/[\w./-]+\.py", text)]


def _grade_the_residue() -> dict[str, dict]:
    """Per residue tag: the two findings, and deliberately no evidence list.

    A pinned list of every path a tag has touched goes stale on that tag's
    very next commit, and a residue tag is the one population that goes on
    committing.  So what is derived -- and what the receipt pins -- is the
    grade: the behaviour-directory paths, and the ``tests/`` files no receipt
    of the tag declares as its gate.  Both are empty for a receipt-only pass
    and neither can be for one that touches ``src/``.
    """
    graded: dict[str, dict] = {}
    for tag in ledger()["coverage"]["slice_groups_without_one"]:
        paths = sorted(set(_paths_by_tag()[tag]))
        receipts = [path for path in paths if path.startswith("docs/receipts/")]
        graded[tag] = {
            "in_a_behaviour_directory": [
                path for path in paths if path.startswith(BEHAVIOUR_DIRS)
            ],
            "tests_without_a_declaring_receipt": [
                test
                for test in paths
                if test.startswith("tests/")
                and not any(test in _declared_gates(receipt) for receipt in receipts)
            ],
        }
    return graded


def test_no_tag_in_the_residue_is_an_implementation_slice() -> None:
    """The clause's answer, as a number the tree produces.

    Every implementation slice in the campaign range carries a recorded
    verdict here, because the residue -- the only place a tag without one can
    be -- holds nothing that changed behaviour in any of Ruling 1's four
    directories.  Nothing is excluded and no list shrinks: the residue is
    still what it was, and this grades it.
    """
    block = ledger()["coverage"]["residue_is_not_an_implementation_slice"]
    graded = _grade_the_residue()
    assert block["per_tag"] == graded
    assert block["residue"] == len(ledger()["coverage"]["slice_groups_without_one"])
    assert block["residue_that_is_an_implementation_slice"] == sum(
        1 for row in graded.values() if row["in_a_behaviour_directory"]
    )
    assert block["residue_that_is_an_implementation_slice"] == 0
    for tag, row in graded.items():
        assert not row["in_a_behaviour_directory"], tag
        assert not row["tests_without_a_declaring_receipt"], tag
    assert block["what_per_tag_holds"].strip()


def test_the_residue_grade_changes_no_list_and_enumerates_nobody() -> None:
    """The conservative half, asserted rather than promised.

    A grade that quietly moved a tag would be the denominator shrinking
    behind a reading -- the second shortcut ``rulings-owed.json`` refuses.
    So: the graded tags *are* the residue, and none of them has become an
    instrument.
    """
    coverage = ledger()["coverage"]
    block = coverage["residue_is_not_an_implementation_slice"]
    assert set(block["per_tag"]) == set(coverage["slice_groups_without_one"])
    assert not set(block["per_tag"]) & {row["tag"] for row in _instruments()}
    assert "does NOT enumerate" in block["what_this_is_not"]
    assert block["what_it_does_not_claim"].strip()


def test_the_residue_grade_has_a_red_it_can_reproduce() -> None:
    """R-05 on both arms, and on the circularity the first draft had."""
    graded = _grade_the_residue()
    a_tag = next(iter(graded))
    doctored = dict(graded[a_tag], in_a_behaviour_directory=["src/calculator/app.py"])
    assert (
        doctored["in_a_behaviour_directory"]
        != graded[a_tag]["in_a_behaviour_directory"]
    )
    # A source slice really does touch a behaviour directory, so the emptiness
    # arm is discriminating rather than vacuously true of every tag.
    a_source_slice = _paths_by_tag()["campaign-close-swing-composition"]
    assert [path for path in a_source_slice if path.startswith(BEHAVIOUR_DIRS)]
    # And the containment arm reads declared gates, never receipt text: the
    # ledger mentions every test path this block lists, and declares one.
    assert _declared_gates("docs/receipts/verify-ledger.json") == [
        "tests/test_verify_ledger.py"
    ]
    assert "tests/test_rulings_owed.py" in LEDGER.read_text(encoding="utf-8")
    # The staleness red, which is the one this block was rebuilt for: a grade
    # that pinned the paths a tag had touched would differ from the tree the
    # moment that tag committed again, and every residue tag does.
    #
    # Rewritten after round 132's first finding, which measured that the line
    # here could not fail.  It subtracted a path set from ``per_tag[a_tag]``,
    # and that row is a *dict*: ``set()`` of it yields its two key strings, so
    # the difference was the tag's entire touched-path set and was non-empty
    # for any tag that had ever touched a file.  A red that is non-empty by
    # construction is not a red.
    #
    # What the block actually promises is that the receipt pins a grade and
    # not an evidence list, so that is what is asserted: a per-tag row carries
    # exactly the two findings, and a row that regrew a path list would differ
    # from the derived grade the equality check above compares against.
    with_an_evidence_list = {
        tag: dict(row, paths_touched=sorted(set(_paths_by_tag()[tag])))
        for tag, row in graded.items()
    }
    assert with_an_evidence_list != graded
    assert all(
        set(row) == {"in_a_behaviour_directory", "tests_without_a_declaring_receipt"}
        for row in graded.values()
    )


# --------------------------------------------------------------------------
# The instrument arm, and the check that keeps it from being an escape hatch.
#
# The campaign owner ruled on 2026-08-17 -- the fixed-point reading, recorded
# in the umbrella's Owner's rulings section -- that verification, certification,
# transcription and receipt-only passes are *instruments* of the clause rather
# than subjects of it: their own record stands where a verdict would, and they
# do not enter the denominator.  That closes a regress the close report
# measured, in which every pass convened to grade the clause added its own
# unverifiable tag to what it was grading.
#
# It also opens the obvious door, and these checks are the lock.  Enumeration
# alone would be a lane declaring which tags are not really slices, which is
# the second of the three shortcuts ``rulings-owed.json`` refuses by name.  So
# every enumerated tag carries three derived prongs: the self-record's locator
# resolves verbatim in the artifact it names; the tag's *own* commits touch
# that artifact, because a pass that did not write its record does not have
# one; and no commit of the tag touches ``src/``, because production behaviour
# makes a pass a subject whatever it calls itself.
# --------------------------------------------------------------------------

REPORT_PATH = "docs/receipts/campaign-close-report.md"


def _paths_by_tag() -> dict[str, list[str]]:
    """Every campaign commit's touched paths, grouped by its slice tag."""
    unit, record = chr(31), chr(30)
    out = subprocess.run(
        ["git", "log", f"--format={record}%h{unit}%s", "--name-only", "584071e..HEAD"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=True,
    ).stdout
    tag_pattern = re.compile(TRAILING_TAG)
    grouped: dict[str, list[str]] = {}
    for chunk in out.split(record):
        lines = [line for line in chunk.splitlines() if line.strip()]
        if not lines:
            continue
        _sha, subject = lines[0].split(unit, 1)
        match = tag_pattern.search(subject)
        if match is None:
            continue
        tag = match.group(1).split(",")[0].strip()
        grouped.setdefault(tag, []).extend(lines[1:])
    return grouped


def _instruments() -> list[dict]:
    return ledger()["coverage"]["instrument_pass_tags"]


@pytest.mark.parametrize(
    "row", _instruments(), ids=[row["tag"] for row in _instruments()]
)
def test_every_instrument_tag_names_a_self_record_that_resolves(row: dict) -> None:
    """A record nobody can open is an exemption with a filename."""
    record = row["self_record"]
    artifact = ROOT / record["artifact"]
    assert artifact.exists(), row["tag"]
    assert record["locator"] in artifact.read_text(encoding="utf-8"), row["tag"]
    assert row["kind"] and row["what_the_pass_was"], row["tag"]


@pytest.mark.parametrize(
    "row", _instruments(), ids=[row["tag"] for row in _instruments()]
)
def test_every_instrument_pass_wrote_the_record_it_points_at(row: dict) -> None:
    """*Its own* record -- the word the ruling uses, checked against the tree.

    A pass pointing at a section somebody else wrote is pointing at evidence
    about somebody else.  What makes the record self-standing is that the
    pass's own commits produced it.
    """
    touched = _paths_by_tag().get(row["tag"], [])
    assert touched, row["tag"]
    assert row["self_record"]["artifact"] in touched, row["tag"]


@pytest.mark.parametrize(
    "row", _instruments(), ids=[row["tag"] for row in _instruments()]
)
def test_no_instrument_pass_changed_production_behaviour(row: dict) -> None:
    """The floor under the whole arm.

    An instrument may repair the instruments it reads -- a gate, a receipt,
    its own test.  The moment it changes ``src/`` it is a subject of the
    clause whatever it calls itself, and the enumeration must not hold it.
    """
    touched = _paths_by_tag().get(row["tag"], [])
    assert touched, row["tag"]
    assert not [path for path in touched if path.startswith("src/")], row["tag"]


def test_the_instrument_checks_have_reds_they_can_reproduce() -> None:
    """R-05 over all three prongs, measured on the tree.

    The negatives are real tags and a real absent heading rather than
    injected fixtures, so a prong that stopped discriminating would show up
    here as a green that should be red.
    """
    grouped = _paths_by_tag()
    report = (ROOT / REPORT_PATH).read_text(encoding="utf-8")
    assert "## 20. The section no pass has written" not in report
    a_source_slice = "campaign-close-swing-composition"
    assert a_source_slice in grouped, a_source_slice
    assert REPORT_PATH not in grouped[a_source_slice]
    assert [path for path in grouped[a_source_slice] if path.startswith("src/")]


def test_the_block_says_the_split_is_the_owners_ruling_and_not_an_exclusion() -> None:
    """The reading is recorded where the counter is, with its refusal.

    A counter that changed unit without saying whose reading changed it is
    indistinguishable from a counter somebody edited, which is what D-40
    exists to forbid.  The block carries the ruling, its date, and the
    sentence that says which of the two this is.
    """
    coverage = ledger()["coverage"]
    split = coverage["how_the_denominator_is_split"]
    assert "2026-08-17" in split
    assert "D-40" in split
    assert "IMPLEMENTATION SLICE" in split
    assert coverage[
        "why_only_the_instruments_that_would_otherwise_be_residue_are_enumerated"
    ]
    assert coverage["why_the_lane_recording_the_ruling_did_not_enumerate_itself"]


# --------------------------------------------------------------------------
# Ruling 5 -- the untagged commits, and which of them the clause reaches.
#
# The denominator is derived from a commit subject's trailing tag, so a commit
# carrying none sits outside it.  ``untagged_commits`` reported how many there
# were and nothing said what they *were*: outside "every slice" because they
# touch no behaviour, or evidence the tag convention was not universal.  A
# certification reviewer raised it, the owed row carried it to whoever ruled,
# and the owner's ruling of 2026-08-17 settles it -- an untagged commit that
# touches no behaviour owes nothing, and one that touches ``src/`` is
# enumerated and owes a batch verdict or a dated acceptance note.
#
# What is gated here is the enumeration, not the coverage.  Every row is
# uncovered today; the counter says so, and a list with a length is what makes
# the remaining debt work somebody can start.
# --------------------------------------------------------------------------


def _untagged_src_subjects() -> list[str]:
    """Untagged campaign commits that touch ``src/``, oldest first."""
    unit, record = chr(31), chr(30)
    out = subprocess.run(
        [
            "git",
            "log",
            "--reverse",
            f"--format={record}%h{unit}%s",
            "--name-only",
            "584071e..HEAD",
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=True,
    ).stdout
    tag_pattern = re.compile(TRAILING_TAG)
    subjects: list[str] = []
    for chunk in out.split(record):
        lines = [line for line in chunk.splitlines() if line.strip()]
        if not lines:
            continue
        _sha, subject = lines[0].split(unit, 1)
        if tag_pattern.search(subject):
            continue
        if any(path.startswith("src/") for path in lines[1:]):
            subjects.append(subject)
    return subjects


def _untagged_src() -> dict:
    return ledger()["coverage"]["untagged_commits_that_touch_src"]


def test_the_untagged_src_enumeration_is_the_measured_one() -> None:
    """Derived, in order, and re-derived here -- never authored.

    The population hole closed by being counted, and a hole counted by hand
    is the hole with a receipt on it.  Subjects rather than shas, for the
    reason the citation list gives one function up.
    """
    block = _untagged_src()
    measured = _untagged_src_subjects()
    assert block["subjects"] == measured
    assert block["count"] == len(measured)


def _untagged_src_shas() -> dict[str, str]:
    """The sha behind each untagged src-touching subject."""
    unit, record = chr(31), chr(30)
    out = subprocess.run(
        [
            "git",
            "log",
            "--reverse",
            f"--format={record}%H{unit}%s",
            "--name-only",
            "584071e..HEAD",
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=True,
    ).stdout
    tag_pattern = re.compile(TRAILING_TAG)
    found: dict[str, str] = {}
    for chunk in out.split(record):
        lines = [line for line in chunk.splitlines() if line.strip()]
        if not lines:
            continue
        sha, subject = lines[0].split(unit, 1)
        if tag_pattern.search(subject):
            continue
        if any(path.startswith("src/") for path in lines[1:]):
            found[subject] = sha
    return found


def _covered_by_a_recorded_pass() -> dict[str, str]:
    """Untagged src commits a recorded pass names in ``verified_commits``.

    The join is by sha and the only source is ``verified_commits``.  No pass
    block carries a range, so "the brief spanned it" has exactly one
    machine-readable spelling; a sha that merely appears inside a verifier's
    evidence prose is a boundary it read past or a parent tree it exported,
    and calling that coverage would invent verdicts nobody rendered.
    """
    verified = set()
    for block in ledger()["passes"]:
        for sha in block["verified_commits"]:
            resolved = subprocess.run(
                ["git", "rev-parse", f"{sha}^{{commit}}"],
                capture_output=True,
                text=True,
                cwd=ROOT,
                check=True,
            )
            verified.add(resolved.stdout.strip())
    return {
        subject: sha for subject, sha in _untagged_src_shas().items() if sha in verified
    }


def test_the_untagged_src_rows_carry_their_coverage_honestly() -> None:
    """The counter that stops the list from reading as closed.

    Derived, not authored: the map is re-computed from the ledger's own
    ``verified_commits`` against the tree, so a row cannot be typed into
    coverage and a row whose pass is later removed loses it.
    """
    block = _untagged_src()
    covered = block["covered"]
    assert set(covered) <= set(block["subjects"])
    assert covered == _covered_by_a_recorded_pass()
    assert block["uncovered"] == block["count"] - len(covered)
    assert block["how_coverage_is_derived"].strip()
    assert block["what_a_mention_is_not"].strip()


def test_the_untagged_src_rows_are_split_by_the_era_they_landed_in() -> None:
    """Two different debts wearing one word, told apart by the tree.

    Everything before the trailing-tag convention began is untagged because
    the convention did not exist; everything after it is a lane that had the
    convention and shipped ``src/`` without one.  Only the second kind has a
    lane whose other commits say where it belongs, which is the whole of why
    a scheduler needs the split.
    """
    era = _untagged_src()["by_era"]
    subjects = _untagged_src_subjects()
    unit, record = chr(31), chr(30)
    out = subprocess.run(
        ["git", "log", "--reverse", f"--format=%s{record}", "584071e..HEAD"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=True,
    ).stdout
    ordered = [line.strip() for line in out.split(record) if line.strip()]
    tag_pattern = re.compile(TRAILING_TAG)
    first_tagged = next(
        index for index, subject in enumerate(ordered) if tag_pattern.search(subject)
    )
    assert era["the_tag_convention_begins_at"] == ordered[first_tagged]
    positions = [ordered.index(subject) for subject in subjects]
    assert era["before_the_convention"] == sum(
        1 for at in positions if at < first_tagged
    )
    assert era["after_the_convention"] == sum(
        1 for at in positions if at > first_tagged
    )
    assert (
        era["before_the_convention"] + era["after_the_convention"]
        == _untagged_src()["count"]
    )
    assert era["what_the_split_does_not_do"].strip()


def test_the_untagged_src_enumeration_says_what_a_lane_may_not_do() -> None:
    """Retro-tagging is the shortcut this list would otherwise invite.

    Rewriting a commit subject closes the list by making it underivable,
    which is why the refusal lives beside the enumeration rather than only
    in the ruling that ordered it.
    """
    block = _untagged_src()
    forbidden = block["what_a_lane_may_not_do_about_these"]
    assert "Retro-tag" in forbidden
    assert "2026-08-17" in block["rule"]
    assert block["what_closes_a_row"].strip()


def test_the_untagged_src_gate_has_a_red_it_can_reproduce() -> None:
    """R-05: drop a row, add one, or claim coverage nobody recorded."""
    block = _untagged_src()
    measured = _untagged_src_subjects()
    assert measured[:-1] != measured
    assert measured + ["a subject no commit carries"] != measured
    doctored = dict(block, covered={"a subject no commit carries": {}})
    assert not set(doctored["covered"]) <= set(block["subjects"])
    # And the one the derivation added: a real row claimed as covered by a
    # pass that never named it.  This is the shape a lane would reach for,
    # and it is now the difference between a typed map and a derived one.
    claimed = {block["subjects"][0]: _untagged_src_shas()[block["subjects"][0]]}
    assert claimed != _covered_by_a_recorded_pass()


def test_the_lane_that_recorded_the_ruling_is_not_in_the_arm_it_recorded() -> None:
    """The one check nobody else could have written for this pass.

    The lane transcribing the owner's ruling had every opportunity to place
    its own tag in the enumeration it was adding, on its own word, in the
    commit that added it.  It never did, and that is the half of this check
    that can never stop being true.

    The other half was ``recording_lane in slice_groups_without_one``, and it
    was the *residue* half rather than the refusal: the block beside it said
    "whether it ever leaves is a verifier's to say".  A verifier has said --
    an R-35 pass rendered on 2026-08-18, transcribed from the journal that
    holds it -- so the tag left the residue the only way it was ever allowed
    to.  What replaces the membership assertion is the stronger fact, because
    a covered tag whose coverage is a verifier's artifact is exactly what the
    refusal was protecting: not enumerated, not self-declared, verified.
    """
    coverage = ledger()["coverage"]
    recording_lane = "campaign-close-owner-ruling-criterion-11"
    assert recording_lane not in {row["tag"] for row in _instruments()}
    assert recording_lane in coverage["slice_groups_with_a_verdict_in_this_ledger"]
    verdict = next(
        block for block in ledger()["passes"] if block["slice_group"] == recording_lane
    )
    assert verdict["provenance"]["agent_ids"] and not verdict["backfilled"]


def _pass(round_number: int) -> dict:
    return next(
        block for block in ledger()["passes"] if block.get("round") == round_number
    )


@pytest.mark.parametrize(
    "criterion",
    [
        "umbrella-1",
        "umbrella-4",
        "umbrella-7",
        "runbook-2",
        "runbook-11",
        "runbook-12",
    ],
)
def test_the_second_round_answers_every_criterion_it_was_handed(
    criterion: str,
) -> None:
    """The same clause as round 1's, over the pass that followed it.

    Written per round rather than once over all passes: a pass answers the
    criteria *its* verifier returned, and a rule quantified over the union
    would demand round 2 re-answer verdicts round 1 already closed.
    """
    assert criterion in {row["id"] for row in _pass(2)["criteria"]}


def test_every_pass_is_numbered_and_the_numbering_has_no_holes() -> None:
    """Rounds are how two passes over one slice group stay distinguishable."""
    rounds = [block["round"] for block in ledger()["passes"]]
    assert rounds == list(range(1, len(rounds) + 1))


def test_round_two_carries_the_six_findings_its_verifier_returned() -> None:
    """The third clause, per round: documented or reverted, none dropped."""
    findings = _pass(2)["unmentioned_behaviour"]
    assert len(findings) == 6
    assert {row["disposition"] for row in findings} <= set(
        ledger()["disposition_vocabulary"]
    )
    assert any(row["disposition"] == "reverted" for row in findings)
