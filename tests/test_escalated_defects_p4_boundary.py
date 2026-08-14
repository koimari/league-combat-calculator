"""The Phase 4 boundary re-capture landed, and this file is what inverted with it.

R-19 forbids re-capturing a baseline while any qualifying occurrence lacks an
independent verdict, and it forbids moving one onto a value a verdict says is
wrong.  Both prohibitions are now discharged, and both entries this ledger
carries are retired rather than deleted:

* ``the_phase_4_boundary_recapture_is_owed_60_oracle_receipts`` retired when
  the investigator pass filed all 60 receipts.
* ``thirteen_of_the_sixty_boundary_verdicts_certify_the_old_value`` retires
  here.  Its thirteen dissents stand unedited — clause 3 forbids touching a
  filed receipt — and every one of them is **superseded on its own leaf** by a
  committed whole-series re-adjudication carrying ``new_value_correct``, the
  last of them the C2R round that answered the one cluster that had sustained.

So the assertions invert rather than disappear.  Where this file used to say
"the committed baseline still holds the old value", it now says the
re-captured baseline holds exactly the value each receipt certified — the same
60 leaves, the same recorded values, read the other way round.  Where it used
to say "a sustained dissent is recorded as owing a ruled slice", it now says
that cluster is itself superseded, so the amendment's clause 2 is never
reached and no correction re-opens.  And where two reproducers read the live
compare for facts the C2 brief got wrong, they read the re-captured baseline
for the same facts, because the compare they were reading is now clean by
construction.

What does **not** invert is the enumeration: the thirteen rows are still
exactly the ``oracle-P4B-*.json`` receipts whose verdict is not
``new_value_correct``, read from the receipts and never from the ledger's own
prose, because the receipts were never edited.

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

# R-17's allowlist reader, from its own home: a standing coupled diff is
# legal exactly when a committed receipt claims it, and that predicate has
# one implementation rather than one per gate that needs it.
from tests.test_coupled_golden_allowlist import (  # noqa: E402
    allowlisted_coupled_paths,
    unexplained,
)

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
    """The successor entry: the verdicts that once kept the re-capture blocked.

    Retired at the boundary re-capture, so it is read out of ``retired`` — and
    read by name from the whole ledger, so an entry silently dropped from both
    lists fails here rather than passing as "not open".
    """
    for entry in _ledger()["retired"] + _ledger()["defects"]:
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


def _this_c2_pass():
    """The two P4C receipts whose brief the re-posing names a defect in."""
    return sorted(path.name for path in RECEIPTS.glob(f"{SUPERSEDING_PREFIX}C2-*.json"))


def _standing_by_path():
    """Every standing coupled diff, keyed by path — the live compare.

    Read rather than restated: a refutation quoted out of a commit body is
    the prose this ledger exists to keep out of the evidence chain.
    """
    baseline = json.loads(COUPLED_BASELINE.read_text(encoding="utf-8"))
    current = gs.rebuild_for(baseline)
    for snapshot in (baseline, current):
        for key in gs.COMPARE_EXCLUDED_PROVENANCE:
            snapshot.get("metadata", {}).pop(key, None)
    return {diff.path: diff for diff in gs.leaf_report(baseline, current)}


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
    def test_the_recaptured_baseline_now_holds_the_new_value(self, index):
        """The inversion R-19 was holding back: the re-capture landed.

        This assertion read ``old_value`` and asserted the baseline had not
        moved for as long as any of the 60 lacked a covering verdict.  It is
        turned over rather than deleted, against the same 60 rows and the same
        recorded values: the committed baseline now holds, leaf for leaf,
        exactly the ``new_value`` each row's receipt certified — including the
        removals, which are absent from it.
        """
        baseline = json.loads(COUPLED_BASELINE.read_text(encoding="utf-8"))
        leaf = _population()[index]
        found = _reportable(_resolve(baseline, leaf["leaf_path"]))
        if leaf["transition"] == "value_to_absent":
            assert found is _MISSING, leaf["leaf_path"]
        else:
            assert found is not _MISSING, leaf["leaf_path"]
            assert _same_value(found, leaf["new_value"]), leaf["leaf_path"]

    def test_the_population_is_the_size_the_entry_declares(self):
        assert len(_population()) == 60


class TestTheThirteenDissentsAreSupersededAndTheRecaptureLanded:
    """A verdict for the old value was a stop; it is cleared, never absorbed.

    Three of these four assertions are the ones this class always carried and
    they are untouched, because nothing they read has changed: the thirteen
    receipts stand unedited with their verdicts, and the rows still quote them
    faithfully.  The fourth is the inversion — where the class used to prove
    the baseline had *not* moved onto a dissented value, it now proves that
    every dissented leaf was first superseded by a committed
    ``new_value_correct`` re-adjudication on that same leaf, and that the value
    the re-captured baseline holds is that superseding receipt's, not the
    dissent's.  A re-capture over an unsuperseded dissent would fail here.
    """

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

    def test_no_dissented_leaf_was_pinned_without_a_superseding_verdict(self):
        """The inversion, and the one assertion that could still stop a capture.

        For each of the thirteen: some receipt other than the dissent itself
        adjudicates the same leaf, carries ``new_value_correct``, and names the
        dissent it supersedes; and the value the re-captured baseline holds is
        the one that superseding receipt certified.  A baseline moved onto a
        value only the dissent's own path ever carried fails on both halves.
        """
        baseline = json.loads(COUPLED_BASELINE.read_text(encoding="utf-8"))
        by_name = {
            path.name: json.loads(path.read_text(encoding="utf-8"))
            for path in RECEIPTS.glob("oracle-*.json")
        }
        for row in _dissent()["dissenting_population"]:
            superseding = [
                (name, body)
                for name, body in by_name.items()
                if name != row["receipt"]
                and _receipt_leaf(body)[0] == row["leaf_path"]
                and body.get("verdict") == "new_value_correct"
                and row["receipt"] in json.dumps(body)
            ]
            assert superseding, row["receipt"]
            found = _reportable(_resolve(baseline, row["leaf_path"]))
            for name, body in superseding:
                certified = _receipt_leaf(body)[1]
                if row["transition"] == "value_to_absent":
                    assert found is _MISSING, name
                else:
                    assert _same_value(certified, found), name
            assert not _same_value(row["old_value"], found), row["leaf_path"]


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

    def test_the_round_still_records_what_it_found_including_its_sustain(self):
        """The round's own arithmetic is history and does not move with the entry.

        This block recorded 11 resolved and 2 sustained, and it still does:
        rewriting it once a later round answered the sustain would describe a
        pass that did not happen.  What the clause-2 obligation it wrote down
        turned into is the *next* test's subject, not this one's.
        """
        block = _readjudication()
        sustained = [
            row for row in block["clusters"] if row["verdict"] != "new_value_correct"
        ]
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

    def test_every_sustained_cluster_was_answered_before_the_baseline_moved(self):
        """The inversion: clause 2 is never reached because nothing sustained.

        This assertion used to read "a block with no dissent left would have
        retired the entry" and required a sustained cluster to exist.  The
        entry is retired, so it is turned over: every cluster this round
        sustained carries a committed later round, that round's receipts all
        certify the new value on the same leaves, and only then does the entry
        appear in ``retired``.  A sustain with no answering round fails here
        and the re-capture is unwritable.
        """
        block = _readjudication()
        sustained = [
            row for row in block["clusters"] if row["verdict"] != "new_value_correct"
        ]
        answered = _dissent()["the_sustained_dissent_is_re_posed"]["the_round_landed"]
        assert sorted(answered["answers_clusters"]) == sorted(
            row["cluster_id"] for row in sustained
        )
        members = _superseding(answered["cluster_id"])
        assert members, answered["cluster_id"]
        assert {body["verdict"] for _, body in members} == {"new_value_correct"}
        assert {body["leaf"] for _, body in members} == {
            row["leaf_path"]
            for row in _dissent()["dissenting_population"]
            if row["receipt"]
            in {name for cluster in sustained for name in cluster["supersedes"]}
        }
        assert DISSENT_ID in {entry["id"] for entry in _ledger()["retired"]}
        assert DISSENT_ID not in {entry["id"] for entry in _ledger()["defects"]}


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


class TestTheProtocolGapIsRuledAndTheRulingWasNotTheArithmetic:
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
        """A protocol answer is not the inversion this entry closed on.

        The entry is retired now, so the half that could go stale is the half
        this test keeps: what retired it is named, and it is not this ruling.
        The ruling supplied a well-posed brief; the arithmetic that brief
        produced is what cleared the stop, and the entry says so by name.
        """
        ruling = _dissent()[RULING_FIELD]
        assert "stand exactly where they were" in ruling["why_this_entry_stays_open"]
        assert ruling["gate"].endswith(type(self).__name__)
        rounds = _dissent()["retired_by_these_rounds"]
        assert rounds
        for named in rounds:
            assert (RECEIPTS / named).exists(), named
            body = json.loads((RECEIPTS / named).read_text(encoding="utf-8"))
            assert body["verdict"] == "new_value_correct", named


class TestTheSustainedDissentWasRePosedAndThenAnswered:
    """C2's re-posing, and the round it handed the question to.

    Clause 3 makes a re-run writable only when it cites the *specific* defect
    in the brief it replaces, and an implementation lane may record such a
    defect without deciding the question.  That separation is unchanged and
    still asserted: every quoted premise really is in the receipt it is quoted
    from, and the re-posing itself writes no verdict.

    What inverts is where the refuting facts are read.  They were read off the
    live compare, which the re-capture has since emptied by construction, so
    they are read off the re-captured baseline instead — the same paths, the
    same recorded values, now on the side of the arrow the baseline holds.
    """

    def test_the_re_posing_is_recorded_on_the_retired_entry(self):
        block = _dissent()["the_sustained_dissent_is_re_posed"]
        assert block["dated"] == "2026-08-14"
        assert DISSENT_ID in {entry["id"] for entry in _ledger()["retired"]}

    def test_every_quoted_premise_is_in_the_receipt_it_is_quoted_from(self):
        """A quotation nothing opens is prose; these open the C2 receipts."""
        prior = [
            json.loads((RECEIPTS / name).read_text(encoding="utf-8"))
            for name in _this_c2_pass()
        ]
        bodies = [json.dumps(body) for body in prior]
        for fragment in (
            "with all 63 other heal records unmoved",
            "not the UNMOVED 4074.9",
            "exactly the recorded healing_received 4074.9",
        ):
            assert all(fragment in body for body in bodies), fragment

    def test_each_refuting_fact_is_the_recaptured_baseline_reading(self):
        """The premise is refuted by measurement, not by assertion.

        Read off the baseline rather than off the compare, because the compare
        this once read is clean now: the totals the C2 brief called unmoved are
        recorded as ``old -> new`` and the committed baseline holds ``new``.
        """
        block = _dissent()["the_sustained_dissent_is_re_posed"][
            "refuted_by_the_compare"
        ]
        baseline = json.loads(COUPLED_BASELINE.read_text(encoding="utf-8"))
        claimed = block["the_totals_the_brief_called_unmoved"]
        assert claimed
        # The instrument guard, stated as R-17 actually leaves it. Between two
        # phase boundaries the compare *cannot* be empty -- a landed slice's
        # allowlisted diffs are standing by design -- so demanding emptiness
        # here would forbid every semantic slice until the next re-capture.
        # What must hold, and what a broken instrument would break, is that
        # every standing diff is claimed by a committed allowlist and that
        # none of them is on a total this test reads.
        standing = _standing_by_path()
        assert (
            unexplained(tuple(standing.values()), allowlisted_coupled_paths()) == ()
        ), "the coupled compare holds a diff no receipt claims"
        assert not {line.split(": ")[0] for line in claimed} & set(standing)
        for line in claimed:
            path, values = line.split(": ")
            old, new = (part.strip() for part in values.split("->"))
            found = _reportable(_resolve(baseline, path))
            assert _same_value(found, float(new)), line
            assert not _same_value(found, float(old)), line

    def test_the_three_re_split_siblings_are_really_three_and_really_moved(self):
        """The identities the brief owed, read off the record the capture pinned."""
        block = _dissent()["the_sustained_dissent_is_re_posed"][
            "refuted_by_the_compare"
        ]
        siblings = block["the_sibling_heals_that_re_split"]
        assert len(siblings) == 3
        baseline = json.loads(COUPLED_BASELINE.read_text(encoding="utf-8"))
        prefix = "/coupled_scenarios/cleaver_bloodsong_roster/combat/"
        for line, (ordinal, identity) in zip(
            siblings,
            (
                (25, "enemy:Aatrox:heal:8:main"),
                (31, "enemy:Aatrox:heal:11:main"),
                (55, "enemy:Aatrox:heal:20:main"),
            ),
        ):
            assert f"healing_events[{ordinal}]" in line and identity in line, line
            record = _resolve(baseline, f"{prefix}healing_events[{ordinal}]")
            assert record is not _MISSING
            assert record[gs.IDENTITY_FIELD] == identity
            for field in ("applied_amount", "overheal"):
                recorded = line.split(f"{field} ")[1].split("->")[1]
                expected = float(recorded.split(",")[0].strip())
                assert _same_value(record[field], expected), (line, field)

    def test_every_certified_fact_carries_a_committed_new_value_correct_receipt(self):
        """The chain rule's bound: only a new_value_correct verdict certifies."""
        block = _dissent()["the_sustained_dissent_is_re_posed"][
            "the_certified_facts_the_next_round_may_carry"
        ]
        lines = block[
            "moved_damage_on_the_healed_unit_every_leaf_certified_new_value_correct"
        ]
        assert lines
        for line in lines:
            for name in line.split(" -- ")[1].split(", "):
                body = json.loads((RECEIPTS / name.strip()).read_text(encoding="utf-8"))
                assert body["verdict"] == "new_value_correct", name

    def test_no_verdict_was_written_here_and_the_next_round_wrote_one(self):
        """The load-bearing negative, kept — plus the round that owned the answer.

        The re-posing still writes no verdict and the C2 receipts still read
        ``old_value_correct`` unedited, which is clause 3's never-edit rule
        holding.  What is added is the other half: the round it handed the
        question to is committed, is a different pass, and answered every leaf
        the sustained cluster held.
        """
        block = _dissent()["the_sustained_dissent_is_re_posed"]
        assert "verdict" not in block
        assert "SUSTAINED" in block["what_this_does_not_decide"]
        cluster = next(
            row
            for row in _readjudication()["clusters"]
            if row["cluster_id"] == "P4C-C2"
        )
        assert cluster["verdict"] == "old_value_correct"
        for name in _this_c2_pass():
            body = json.loads((RECEIPTS / name).read_text(encoding="utf-8"))
            assert body["verdict"] == "old_value_correct"

        landed = block["the_round_landed"]
        assert landed["cluster_id"] != cluster["cluster_id"]
        members = _superseding(landed["cluster_id"])
        assert sorted(name for name, _ in members) == sorted(landed["receipts"])
        for name, body in members:
            assert body["verdict"] == "new_value_correct", name
            assert body["prior_brief_defect_superseded"]["defect"], name

    def test_the_baseline_moved_only_after_that_round_landed(self):
        """The sentence that forbade a capture, and the condition that lifted it.

        The re-posing's own words are unedited — it decided nothing and licensed
        no capture — so the assertion becomes the ordering: the answering round
        is committed, and the value the baseline holds is the one that round
        certified rather than the one the sustain defended.
        """
        block = _dissent()["the_sustained_dissent_is_re_posed"]
        assert "stand exactly where they were" in block["what_this_does_not_decide"]
        baseline = json.loads(COUPLED_BASELINE.read_text(encoding="utf-8"))
        for name, body in _superseding(block["the_round_landed"]["cluster_id"]):
            found = _reportable(_resolve(baseline, body["leaf"]))
            assert _same_value(body["new_value"], found), name
            assert not _same_value(body["old_value"], found), name
