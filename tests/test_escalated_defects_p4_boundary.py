"""The Phase 4 boundary's 60 verdicts are in, and 13 of them say do not pin it.

R-19 forbids re-capturing a baseline while any qualifying occurrence lacks an
independent verdict, and it forbids moving one onto a value a verdict says is
wrong.  The first prohibition is discharged: the investigator pass filed all
60 receipts, every one certifying by value the reading the live compare holds,
so ``the_phase_4_boundary_recapture_is_owed_60_oracle_receipts`` retires and
the assertion that used to say "no owed leaf has a covering receipt" is
inverted rather than deleted.  The second prohibition is now the live one:
13 of the 60 verdicts are ``old_value_correct``, so the coupled baseline still
may not move, and the successor entry
``thirteen_of_the_sixty_boundary_verdicts_certify_the_old_value`` is what says
so.

The reproducers this file carries are therefore three, and all three must hold
while the successor stands: every owed leaf now carries a receipt certifying
the current value; the dissent enumeration is exactly the pass's non-
``new_value_correct`` verdicts, read from the receipts and never from the
ledger's own prose; and every one of the 60 recorded ``old_value`` readings
still reproduces against the committed coupled baseline, which is the machine
statement that no re-capture has happened.

A fourth reproducer joins them once the amendment's clause 1 is exercised: the
re-adjudication pass that supersedes those verdicts is checked against its own
receipts — one cluster per dissent class, the thirteen covered exactly once,
each re-run naming the defect in the brief it replaces (clause 3), and the
entry still open because two of the thirteen are sustained.

One thing this file reads differently from the scan that produced the retired
entry's published figures: a receipt's leaf path may sit at the top level or
nested under a ``leaf`` object, and six committed receipts use the second
shape.  Reading only the first reported four already-adjudicated leaves as
owed and one stale receipt as absent, so ``_receipt_leaf`` accepts both and
the entry carries the corrected figures beside the published ones.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import golden_snapshot as gs  # noqa: E402  (path is set above)

RECEIPTS = ROOT / "docs" / "receipts"
RECEIPT = RECEIPTS / "escalated-defects-P4-boundary.json"
COUPLED_BASELINE = ROOT / "scripts" / "golden_coupled_baseline.json"
RUNBOOK = ROOT / "docs" / "plans" / "silent-failure-runbook.md"

# The runbook ruling this entry's third owner decision cites, verbatim.
AMENDMENT_SECTION = "### Independent investigation"
AMENDMENT_HEADING = (
    "**Amendment R-15/R-18 — 2026-08-14, briefing a leaf that cannot be judged alone.**"
)
RULING_FIELD = "the_third_owner_decision_is_now_ruled"

RETIRED_ID = "the_phase_4_boundary_recapture_is_owed_60_oracle_receipts"
DISSENT_ID = "thirteen_of_the_sixty_boundary_verdicts_certify_the_old_value"
PASS_PREFIX = "oracle-P4B-"
# The re-adjudication pass the amendment's clause 1 licensed.  It POSTdates the
# boundary pass, so it is neither one of its receipts nor one of the priors the
# entry classified; the tests below say what it is instead, so that excluding it
# from "prior" is a stated fact about a named pass and not a silent exemption.
SUPERSEDING_PREFIX = "oracle-P4C-"
SUPERSESSION_FIELDS = (
    "prior_brief_defect_superseded",
    "supersedes_prior_briefs",
    "supersedes_prior_brief_defect",
)

REQUIRED = ("id", "dated", "raised_by", "what", "reproducer", "for_the_owner")
REQUIRED_TO_RETIRE = ("retired_on", "resolved_by", "resolution")

_SEGMENT = re.compile(r"([^\[\]]+)((?:\[\d+\])*)")
_MISSING = object()


def _ledger():
    return json.loads(RECEIPT.read_text(encoding="utf-8"))


def _entry():
    """The retired entry: the receipts this boundary was owed."""
    for entry in _ledger()["retired"]:
        if entry["id"] == RETIRED_ID:
            return entry
    raise AssertionError(f"{RETIRED_ID} is neither open nor retired by name")


def _dissent():
    """The open entry: the verdicts that keep the re-capture blocked."""
    for entry in _ledger()["defects"]:
        if entry["id"] == DISSENT_ID:
            return entry
    raise AssertionError(f"{DISSENT_ID} is neither open nor retired by name")


def _population():
    return _entry()["owed_population"]


def _resolve(document, path):
    """The value a golden leaf path addresses, or ``_MISSING``.

    ``leaf_report`` addresses list members by ordinal, so a path segment is a
    key optionally followed by one or more ``[index]`` suffixes.
    """
    current = document
    for segment in path.strip("/").split("/"):
        match = _SEGMENT.fullmatch(segment)
        assert match is not None, f"unparsable leaf path segment {segment!r}"
        try:
            current = current[match.group(1)]
        except (KeyError, TypeError):
            return _MISSING
        for index in re.findall(r"\[(\d+)\]", match.group(2) or ""):
            try:
                current = current[int(index)]
            except (IndexError, TypeError):
                return _MISSING
    return current


def _reportable(value):
    """One baseline value rendered the way ``leaf_report`` renders it."""
    if value is _MISSING:
        return _MISSING
    return gs._reportable(value)  # pylint: disable=protected-access


def _receipt_leaf(receipt):
    """One receipt's ``(leaf_path, new_value)``, under any shape it uses.

    Three spellings are committed: ``leaf_path`` beside ``new_value`` at the
    top level; a ``leaf`` object carrying both; and — the re-adjudication
    pass's — a ``leaf`` string beside a top-level ``new_value``.  Reading only
    one shape would report an adjudicated leaf as uncovered, which is the
    failure this whole file exists to make impossible.
    """
    if "leaf_path" in receipt:
        return receipt["leaf_path"], receipt.get("new_value")
    nested = receipt.get("leaf")
    if isinstance(nested, str):
        return nested, receipt.get("new_value")
    nested = nested or {}
    return nested.get("path"), nested.get("new_value")


def _certified_values(leaf_path):
    """Every ``new_value`` an oracle receipt certifies for one leaf path."""
    values = []
    for path in sorted(RECEIPTS.glob("oracle-*.json")):
        certified_path, certified = _receipt_leaf(
            json.loads(path.read_text(encoding="utf-8"))
        )
        if certified_path == leaf_path:
            values.append((path.name, certified))
    return values


def _amendment_block():
    """The runbook amendment this entry cites, from its heading to the next section.

    Read out of the runbook rather than restated here: a citation whose target
    the gate does not open is the prose-outruns-code shape the campaign exists
    to kill.
    """
    text = RUNBOOK.read_text(encoding="utf-8")
    section = text.find(AMENDMENT_SECTION)
    assert section != -1, f"the runbook no longer has a {AMENDMENT_SECTION!r} section"
    start = text.find(AMENDMENT_HEADING, section)
    assert start != -1, "the cited amendment is not in the runbook under that heading"
    opening = text.rfind("\n", 0, start) + 1
    end = text.find("\n### ", start)
    return text[opening : end if end != -1 else len(text)], section, start


def _this_pass():
    """Every receipt this investigator pass filed, by name."""
    return sorted(path.name for path in RECEIPTS.glob(f"{PASS_PREFIX}*.json"))


def _readjudication():
    """The dissent entry's record of the pass that supersedes its verdicts."""
    return _dissent()["re_adjudicated_under_the_amendment"]


def _superseding(cluster_id=None):
    """``[(name, receipt)]`` from the superseding pass, one cluster or all."""
    members = []
    for path in sorted(RECEIPTS.glob(f"{SUPERSEDING_PREFIX}*.json")):
        body = json.loads(path.read_text(encoding="utf-8"))
        if cluster_id in (None, body["cluster_id"]):
            members.append((path.name, body))
    return members


def _verdicts():
    """``{receipt name: verdict}`` over this pass, read from the receipts."""
    verdicts = {}
    for name in _this_pass():
        receipt = json.loads((RECEIPTS / name).read_text(encoding="utf-8"))
        verdicts[name] = receipt["verdict"]
    return verdicts


def _same_value(certified, recorded):
    """Does a receipt's ``new_value`` certify the value the report holds?

    A receipt may render an absent leaf as ``<absent…>`` prose and a container
    leaf as a JSON string, which is what ``leaf_report`` writes too, so both
    are normalised before the comparison.
    """
    if isinstance(certified, str):
        text = certified.strip()
        if text.startswith("<absent"):
            certified = None
        else:
            try:
                certified = json.loads(text)
            except json.JSONDecodeError:
                pass
    if isinstance(recorded, str):
        try:
            recorded = json.loads(recorded)
        except json.JSONDecodeError:
            pass
    if isinstance(certified, bool) or isinstance(recorded, bool):
        return certified is recorded
    if isinstance(certified, (int, float)) and isinstance(recorded, (int, float)):
        return abs(certified - recorded) < 1e-9
    return certified == recorded


class TestTheLedgerIsWellFormed:
    """An escalation nobody can read is a commit body with a filename."""

    def test_every_open_entry_carries_the_required_fields(self):
        for entry in _ledger()["defects"]:
            missing = [field for field in REQUIRED if field not in entry]
            assert missing == [], f"{entry.get('id')} is missing {missing}"

    def test_a_retired_entry_says_what_resolved_it(self):
        for entry in _ledger()["retired"]:
            missing = [field for field in REQUIRED_TO_RETIRE if field not in entry]
            assert missing == [], f"{entry.get('id')} retired without {missing}"
            assert entry.get("what"), "a retired entry keeps what it said"

    def test_the_gate_named_by_the_ledger_is_this_file(self):
        assert _ledger()["gate"] == "tests/test_escalated_defects_p4_boundary.py"

    def test_the_counts_the_entry_publishes_agree_with_its_own_lists(self):
        entry = _entry()
        coupled = entry["measured"]["coupled_golden"]
        assert coupled["owed"] == len(entry["owed_population"])
        assert coupled["declared_not_owed_by_a_committed_allowlist"] == len(
            entry["declared_not_owed"]["leaves"]
        )
        assert (
            coupled["covered_by_a_receipt_certifying_the_current_value"]
            + coupled["declared_not_owed_by_a_committed_allowlist"]
            + coupled["owed"]
            == coupled["qualifying_leaves"]
        )
        assert coupled["of_the_owed_carrying_a_stale_receipt_on_the_same_path"] == sum(
            1
            for leaf in entry["owed_population"]
            if leaf["stale_receipt_on_the_same_path"]
        )

    def test_the_corrected_counts_agree_with_the_rows_they_correct(self):
        """A count the campaign published about itself gets the same treatment.

        The published figures were produced by a scan that could not see a
        receipt nesting its leaf path, so they sit beside re-measured ones
        rather than being quietly overwritten.  Both must reproduce from the
        rows.
        """
        entry = _entry()
        coupled = entry["measured"]["coupled_golden"]
        correction = coupled["correction"]
        published = correction["figures_as_published"]
        remeasured = correction["figures_re_measured"]
        already = sum(
            1
            for leaf in entry["owed_population"]
            if leaf["covering_receipt_that_predated_the_pass"]
        )
        assert correction["already_covered_before_the_pass"]["count"] == already
        assert remeasured["truly_owed"] == published["owed"] - already
        assert (
            remeasured["covered_by_a_receipt_certifying_the_current_value"]
            == published["covered_by_a_receipt_certifying_the_current_value"] + already
        )
        assert (
            remeasured["covered_by_a_receipt_certifying_the_current_value"]
            + coupled["declared_not_owed_by_a_committed_allowlist"]
            + remeasured["truly_owed"]
            == coupled["qualifying_leaves"]
        )
        assert remeasured["of_the_owed_carrying_a_stale_receipt_on_the_same_path"] == (
            coupled["of_the_owed_carrying_a_stale_receipt_on_the_same_path"]
        )


class TestTheOwedPopulationIsAnswered:
    """The retirement: 60 leaves, one covering verdict each, baseline unmoved."""

    def test_every_owed_leaf_qualifies_under_r15(self):
        """A leaf that does not qualify is owed nothing and does not belong."""
        for leaf in _population():
            diff = gs.LeafDiff(
                path=leaf["leaf_path"],
                section=leaf["leaf_path"].lstrip("/").split("/", 1)[0],
                old=leaf["old_value"],
                new=leaf["new_value"],
                abs_delta=0.0,
                percent=float("inf"),
                transition=leaf["transition"],
            )
            assert gs.qualifies_for_investigation(diff), leaf["leaf_path"]

    def test_every_owed_leaf_now_carries_a_receipt_certifying_its_new_value(self):
        """The inversion R-18/R-19 asked for: coverage exists, by value."""
        uncovered = []
        for leaf in _population():
            covering = [
                name
                for name, certified in _certified_values(leaf["leaf_path"])
                if _same_value(certified, leaf["new_value"])
            ]
            if not covering:
                uncovered.append(leaf["leaf_path"])
        assert uncovered == [], (
            "these owed leaves still have no receipt certifying the value a "
            f"re-capture would pin — {uncovered}"
        )

    def test_the_pass_filed_exactly_one_receipt_per_owed_leaf(self):
        filed = _this_pass()
        assert len(filed) == len(_population())
        paths = set()
        for name in filed:
            leaf_path, _ = _receipt_leaf(
                json.loads((RECEIPTS / name).read_text(encoding="utf-8"))
            )
            paths.add(leaf_path)
        assert paths == {leaf["leaf_path"] for leaf in _population()}

    def test_a_receipt_that_predates_the_pass_is_stale_or_corroborating(self):
        """Every prior verdict on an owed path is classified, never ignored.

        A receipt written before the rearm correction, the H5 stage and S9
        moved these leaves certifies a value the tree no longer holds: the
        fresh receipt supersedes it, and asserting the two certify *different*
        values is what stops a supersession reading as a second agreeing
        opinion.  A prior receipt that does certify the current value is the
        other case — corroboration, recorded as such rather than counted as a
        miss.

        The re-adjudication pass is excluded because it *post*dates the
        boundary pass rather than predating it; what it is instead is asserted
        by ``TestTheDissentsAreReAdjudicatedUnderTheAmendment`` below, so the
        exclusion is a classification and not a hole.
        """
        for leaf in _population():
            prior = [
                (name, value)
                for name, value in _certified_values(leaf["leaf_path"])
                if not name.startswith((PASS_PREFIX, SUPERSEDING_PREFIX))
            ]
            stale = [
                name
                for name, value in prior
                if not _same_value(value, leaf["new_value"])
            ]
            covering = [
                name for name, value in prior if _same_value(value, leaf["new_value"])
            ]
            assert stale == leaf["stale_receipt_on_the_same_path"], leaf["leaf_path"]
            assert covering == leaf["covering_receipt_that_predated_the_pass"], leaf[
                "leaf_path"
            ]

    @pytest.mark.parametrize("index", range(60))
    def test_the_committed_baseline_still_holds_the_old_value(self, index):
        """R-19's real subject: no re-capture has happened, dissents or not."""
        baseline = json.loads(COUPLED_BASELINE.read_text(encoding="utf-8"))
        leaf = _population()[index]
        found = _reportable(_resolve(baseline, leaf["leaf_path"]))
        if leaf["transition"] == "absent_to_value":
            assert found is _MISSING, leaf["leaf_path"]
        else:
            assert _same_value(found, leaf["old_value"]), leaf["leaf_path"]

    def test_the_population_is_the_size_the_entry_declares(self):
        assert len(_population()) == 60


class TestTheThirteenDissentsBlockTheRecapture:
    """The successor entry: a verdict for the old value is a stop, not a note."""

    def test_the_enumeration_is_exactly_the_passes_dissenting_verdicts(self):
        """Read from the receipts, so the ledger cannot under-report itself."""
        measured = sorted(
            name
            for name, verdict in _verdicts().items()
            if verdict != "new_value_correct"
        )
        recorded = sorted(row["receipt"] for row in _dissent()["dissenting_population"])
        assert recorded == measured
        assert len(measured) == 13

    def test_each_recorded_verdict_is_the_verdict_its_receipt_carries(self):
        verdicts = _verdicts()
        for row in _dissent()["dissenting_population"]:
            assert row["verdict"] == verdicts[row["receipt"]], row["receipt"]
            assert row["verdict"] in {"old_value_correct", "both_wrong"}

    def test_every_dissenting_leaf_is_a_member_of_the_owed_population(self):
        owed = {leaf["leaf_path"]: leaf for leaf in _population()}
        for row in _dissent()["dissenting_population"]:
            leaf = owed.get(row["leaf_path"])
            assert leaf is not None, row["leaf_path"]
            assert row["old_value"] == leaf["old_value"]
            assert row["new_value"] == leaf["new_value"]
            assert row["transition"] == leaf["transition"]

    def test_every_dissent_states_a_contradiction_of_one_of_the_two_kinds(self):
        """A dissent nothing stands against is a finding, not a conflict."""
        verdicts = _verdicts()
        entry = _dissent()
        classes = entry["classes"]
        rows = {row["receipt"]: row for row in entry["dissenting_population"]}
        for name, row in rows.items():
            assert row["class"] in classes, row["class"]
            assert row["contradicted_by"] or row["mutually_exclusive_with"], name
            for other in row["contradicted_by"]:
                assert other in verdicts, other
                assert verdicts[other] == "new_value_correct", other
                assert other != name
            for other in row["mutually_exclusive_with"]:
                assert other in rows, f"{other} is not a dissent of this pass"
                assert other != name
                assert name in rows[other]["mutually_exclusive_with"], (
                    f"{name} claims mutual exclusion with {other} and {other} "
                    "does not say the same; the relation is symmetric"
                )

    def test_the_two_contradiction_kinds_are_documented_by_the_entry(self):
        stated = _dissent()["how_a_dissent_is_contradicted"]
        assert set(stated) >= {"contradicted_by", "mutually_exclusive_with"}


class TestTheDissentsAreReAdjudicatedUnderTheAmendment:
    """The superseding pass, read from its receipts and not from its prose.

    Clause 1 licenses one whole-series re-adjudication per dissent cluster and
    clause 3 makes a re-run that names no defect in the brief it replaces
    unwritable.  Both are properties of committed files, so both are asserted
    here rather than described: every cluster row's ``supersedes`` list is
    checked against the leaf its own receipts adjudicate, and the thirteen are
    covered exactly once between the rows.  This is what pays for the
    ``SUPERSEDING_PREFIX`` exclusion in the prior-receipt classification above
    — the pass is excluded from *prior* because it is asserted to be *this*.
    """

    def test_the_block_covers_every_dissent_exactly_once(self):
        recorded = [
            name for row in _readjudication()["clusters"] for name in row["supersedes"]
        ]
        assert sorted(recorded) == sorted(
            row["receipt"] for row in _dissent()["dissenting_population"]
        )
        assert len(recorded) == len(set(recorded))

    def test_each_cluster_row_reports_the_verdicts_its_receipts_carry(self):
        """The row's count and verdict are the receipts', or the row is wrong."""
        for row in _readjudication()["clusters"]:
            members = _superseding(row["cluster_id"])
            assert members, row["cluster_id"]
            assert len(members) == row["leaves"]
            assert {body["verdict"] for _, body in members} == {row["verdict"]}

    def test_each_row_supersedes_the_receipt_on_its_own_leaf(self):
        """The mapping is by leaf path, so a mis-stated supersession fails."""
        rows = {row["receipt"]: row for row in _dissent()["dissenting_population"]}
        for row in _readjudication()["clusters"]:
            adjudicated = {body["leaf"] for _, body in _superseding(row["cluster_id"])}
            superseded = {rows[name]["leaf_path"] for name in row["supersedes"]}
            assert adjudicated == superseded, row["cluster_id"]

    def test_every_superseding_receipt_names_the_defect_in_the_brief(self):
        """Clause 3: a re-run citing no brief defect is oracle shopping."""
        for name, body in _superseding():
            fields = [field for field in SUPERSESSION_FIELDS if field in body]
            assert fields, f"{name} supersedes a receipt and says why nowhere"
            for field in fields:
                assert body[field]["defect"], f"{name}'s {field} names no defect"

    def test_a_sustained_dissent_is_recorded_as_owing_a_ruled_slice(self):
        """R-19's stop, kept a stop: sustained means re-opened, never absorbed."""
        block = _readjudication()
        sustained = [
            row for row in block["clusters"] if row["verdict"] != "new_value_correct"
        ]
        assert sustained, "a block with no dissent left would have retired the entry"
        assert block["net_effect_on_the_thirteen"]["sustained"] == sum(
            row["leaves"] for row in sustained
        )
        assert block["net_effect_on_the_thirteen"]["resolved"] == sum(
            row["leaves"]
            for row in block["clusters"]
            if row["verdict"] == "new_value_correct"
        )
        assert (
            block["net_effect_on_the_thirteen"]["prior_receipts_edited_or_deleted"] == 0
        )
        obliges = block["what_the_sustained_dissent_now_obliges"]
        assert "Expected qualifying occurrences" in obliges
        assert "never absorbed into a baseline" in obliges
        assert DISSENT_ID in {entry["id"] for entry in _ledger()["defects"]}


class TestTheOtherJurisdictionIsClean:
    """D-93: the two baselines are two jurisdictions, stated separately."""

    def test_the_pair_baseline_is_recorded_as_owing_nothing(self):
        pair = _entry()["measured"]["pair_golden"]
        assert pair == {
            "differing_leaves": 0,
            "qualifying_leaves": 0,
            "owed": 0,
        }

    def test_the_three_not_owed_leaves_cite_the_allowlist_that_declared_them(self):
        declared = _entry()["declared_not_owed"]
        assert "NOT_OWED_NO_OLD_VALUE" in declared["why"]
        allowlist = json.loads(
            (RECEIPTS / "expected-golden-diff-P4-S9-score-map.json").read_text(
                encoding="utf-8"
            )
        )
        assert allowlist["oracle_pass"]["status"] == "NOT_OWED_NO_OLD_VALUE"
        assert sorted(leaf["leaf_path"] for leaf in declared["leaves"]) == sorted(
            allowlist["expected_diff_paths"]["coupled_golden"]
        )


class TestTheProtocolGapIsRuledAndTheEntryStillStands:
    """The third owner decision is answered in the runbook — and only that one.

    The dissent cluster named a protocol gap: a brief carrying only a leaf path
    and two values is underdetermined for one member of a repeated-source
    series.  That gap is now ruled as a dated amendment on R-15/R-18, and this
    entry cites it.  A citation nothing opens is prose, so the gate opens it;
    and a protocol ruling is not the arithmetic, so the same gate asserts the
    entry did not retire on the strength of it.
    """

    def test_the_entry_cites_the_amendment_by_document_and_name(self):
        """The citation names a document and a heading, not "the runbook"."""
        ruling = _dissent()[RULING_FIELD]
        assert "docs/plans/silent-failure-runbook.md" in ruling["amendment"]
        assert "Amendment R-15/R-18" in ruling["amendment"]
        assert ruling["dated"] in AMENDMENT_HEADING

    def test_the_cited_amendment_is_in_the_runbook_under_the_rule_it_amends(self):
        """R-15/R-18 live in *Independent investigation*; so must their amendment."""
        block, section, start = _amendment_block()
        assert start > section, "the amendment sits outside the section it amends"
        assert block.strip().startswith(">"), "an amendment is a block quote, not prose"

    def test_the_amendment_leaves_the_investigator_export_exactly_two_paths(self):
        """The half that did NOT move: an oracle that reads the fix is not one."""
        block, _, _ = _amendment_block()
        assert "stays exactly `data/` and `docs/math-foundations.md`" in block
        assert "The export does not move." in block

    def test_the_amendment_rules_what_a_series_brief_carries_and_from_where(self):
        """The half that did move: the question specification, pre-change only."""
        block, _, _ = _amendment_block()
        for claim in (
            "repeated-source series",
            "question specification",
            "committed **pre-change**",
            "committed scenario definitions",
            "**entire** series from scratch",
            "one verdict per leaf",
        ):
            assert claim in block, claim

    def test_the_amendment_carries_the_anti_oracle_shopping_clause(self):
        """A re-run with no named brief defect must be unwritable, not discouraged."""
        block, _, _ = _amendment_block()
        assert "never re-run merely because it dissents" in block
        assert "specific defect in the prior brief" in block
        assert "receipt that supersedes the prior one" in block
        assert "never absorbed into a baseline" in block or (
            "It is **never** absorbed into a baseline" in block
        )

    def test_the_ruling_did_not_retire_the_entry_that_cites_it(self):
        """A protocol answer is not the inversion this entry closes on."""
        ledger = _ledger()
        assert DISSENT_ID in {entry["id"] for entry in ledger["defects"]}
        assert DISSENT_ID not in {entry["id"] for entry in ledger["retired"]}
        ruling = _dissent()[RULING_FIELD]
        assert "stand exactly where they were" in ruling["why_this_entry_stays_open"]
        assert ruling["gate"].endswith(type(self).__name__)
