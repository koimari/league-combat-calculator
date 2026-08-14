"""The Phase 4 boundary re-capture is owed 60 oracle receipts, and says so.

R-19 forbids re-capturing a baseline while any qualifying occurrence lacks an
independent verdict.  On this tip the coupled comparison holds 127 qualifying
leaves; 64 carry a receipt certifying the value a re-capture would pin, 3 are
declared ``NOT_OWED_NO_OLD_VALUE`` by a committed allowlist, and 60 are owed.
23 of those 60 carry a receipt on the same leaf path certifying a *different*
value, because the S6/S7 oracle pass adjudicated the tree before the rearm
correction, the H5 stage and S9 moved those leaves again — which is why this
gate matches receipts by value and never by path alone.

The reproducers are the two properties that must both hold while the entry
stands: no leaf in the population has a covering receipt, and every leaf's
recorded ``old_value`` still reproduces against the committed coupled
baseline.  The second is the assertion that the baseline did not move while
the receipts were owed; the first inverts the day the investigator pass files
them, which is how the entry is closed deliberately rather than quietly.
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

ENTRY_ID = "the_phase_4_boundary_recapture_is_owed_60_oracle_receipts"
REQUIRED = ("id", "dated", "raised_by", "what", "reproducer", "for_the_owner")
REQUIRED_TO_RETIRE = ("retired_on", "resolved_by", "resolution")

_SEGMENT = re.compile(r"([^\[\]]+)((?:\[\d+\])*)")
_MISSING = object()


def _ledger():
    return json.loads(RECEIPT.read_text(encoding="utf-8"))


def _entry():
    for entry in _ledger()["defects"]:
        if entry["id"] == ENTRY_ID:
            return entry
    raise AssertionError(f"{ENTRY_ID} is neither open nor retired by name")


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


def _certified_values(leaf_path):
    """Every ``new_value`` an oracle receipt certifies for one leaf path."""
    values = []
    for path in sorted(RECEIPTS.glob("oracle-*.json")):
        receipt = json.loads(path.read_text(encoding="utf-8"))
        if receipt.get("leaf_path") == leaf_path:
            values.append((path.name, receipt.get("new_value")))
    return values


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


class TestTheOwedPopulationIsStillOwed:
    """The reproducer: 60 leaves, no covering verdict, baseline unmoved."""

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

    def test_no_owed_leaf_has_a_receipt_certifying_its_new_value(self):
        """Inverts the day the investigator pass files them (R-18/R-19)."""
        covered = []
        for leaf in _population():
            for name, certified in _certified_values(leaf["leaf_path"]):
                if _same_value(certified, leaf["new_value"]):
                    covered.append((leaf["leaf_path"], name))
        assert covered == [], (
            "these leaves now carry a covering oracle receipt: the entry must "
            f"retire and the baselines re-capture — {covered}"
        )

    def test_a_stale_receipt_is_recorded_as_stale_and_not_as_coverage(self):
        """23 leaves have a verdict on the path and none on the value."""
        for leaf in _population():
            names = [name for name, _ in _certified_values(leaf["leaf_path"])]
            assert names == leaf["stale_receipt_on_the_same_path"], leaf["leaf_path"]

    @pytest.mark.parametrize("index", range(60))
    def test_the_committed_baseline_still_holds_the_old_value(self, index):
        """R-19's real subject: the baseline did not move while this was owed."""
        baseline = json.loads(COUPLED_BASELINE.read_text(encoding="utf-8"))
        leaf = _population()[index]
        found = _reportable(_resolve(baseline, leaf["leaf_path"]))
        if leaf["transition"] == "absent_to_value":
            assert found is _MISSING, leaf["leaf_path"]
        else:
            assert _same_value(found, leaf["old_value"]), leaf["leaf_path"]

    def test_the_population_is_the_size_the_entry_declares(self):
        assert len(_population()) == 60


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
