"""The corrections ledger in ``campaign-fingerprints.json``, gated.

A campaign note is prose and no gate reads prose, which is how the Phase 4
boundary re-capture landed a receipt sentence its own artifacts contradict:
``coupled_golden_exact`` was said to move no value in the same commit that
moved three of its eighty-two per-attacker totals.  The values were never at
risk — ``TestExactBaseline`` re-captures and compares all eighty-two against
the committed allowlists — so what failed was a claim about the past, which
is the one thing this campaign exists to make checkable.

Two mechanisms, and this module is the gate on both:

* ``corrections[]`` stands *beside* the note it corrects rather than editing
  it, quoting the sentence verbatim, and the quotation is asserted to still
  be literally in that note so a later edit cannot slide the correction off
  the claim.
* ``coupled_golden_exact_values.sha256`` is the fingerprint field that moves
  when a total moves.  ``leaves`` and ``numeric_leaves`` cannot: the exact
  capture stores ``repr`` strings, so its numeric-leaf count is zero by
  construction and its leaf count is the scenario shape.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RECEIPT = REPO_ROOT / "docs" / "receipts" / "campaign-fingerprints.json"
COUPLED_EXACT = REPO_ROOT / "scripts" / "golden_coupled_exact.json"
RECEIPTS = REPO_ROOT / "docs" / "receipts"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def exact_values_digest(scenarios: dict) -> str:
    """The recorded rule, implemented once and read by receipt and test alike."""
    payload = json.dumps(
        {
            name: dict(sorted(totals.items()))
            for name, totals in sorted(scenarios.items())
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def corrections() -> list[dict]:
    return _load(RECEIPT).get("corrections", [])


class TestTheDigestIsTheFieldThatMoves:
    """The gate the false sentence would have tripped."""

    def test_the_recorded_digest_reproduces_from_the_committed_exact_baseline(self):
        recorded = _load(RECEIPT)["coupled_golden_exact_values"]
        scenarios = _load(COUPLED_EXACT)["coupled_scenarios"]
        assert recorded["sha256"] == exact_values_digest(scenarios)

    def test_the_digest_moves_when_a_per_attacker_total_moves(self):
        """R-05's permanent negative: the seam is a one-value edit of the input."""
        scenarios = _load(COUPLED_EXACT)["coupled_scenarios"]
        unchanged = exact_values_digest(scenarios)
        moved = json.loads(json.dumps(scenarios))
        scenario = sorted(moved)[0]
        key = sorted(moved[scenario])[0]
        moved[scenario][key] = repr(float(moved[scenario][key]) + 0.1)
        assert exact_values_digest(moved) != unchanged

    def test_the_digest_is_not_a_field_of_the_snapshot_fingerprint(self):
        """It rides the receipt, never ``metadata.fingerprint`` (which compare reads)."""
        metadata_fingerprint = _load(COUPLED_EXACT)["metadata"]["fingerprint"]
        assert "sha256" not in metadata_fingerprint
        assert metadata_fingerprint["numeric_leaves"] == 0

    def test_the_digest_carries_a_provenance_class(self):
        receipt = _load(RECEIPT)
        assert receipt["provenance"]["coupled_golden_exact_values"] in {
            "VERIFIED",
            "CARRIED",
            "PRIOR",
        }


class TestEveryCorrectionStaysJoinedToTheClaimItCorrects:
    """A correction that drifts off its claim is a second unchecked sentence."""

    @pytest.mark.parametrize("entry", corrections(), ids=lambda e: e["id"])
    def test_the_quoted_claim_is_still_literally_in_the_note_it_names(self, entry):
        notes = _load(RECEIPT)["notes"]
        corrects = entry["corrects"]
        assert corrects["quoted_claim"] in notes[corrects["note_index"]]
        assert notes[corrects["note_index"]].startswith(corrects["note_opens"])

    @pytest.mark.parametrize("entry", corrections(), ids=lambda e: e["id"])
    def test_every_correction_is_dated_and_gated(self, entry):
        assert entry["dated"]
        assert entry["gate"] == "tests/test_fingerprints_corrections.py"


class TestTheThreeMovedTotalsAreWhatTheCorrectionSays:
    """The corrected facts, asserted against the artifacts rather than restated."""

    ENTRY_ID = "the_exact_baselines_three_moved_totals_were_denied_by_the_note_that_landed_them"

    @property
    def entry(self) -> dict:
        return next(e for e in corrections() if e["id"] == self.ENTRY_ID)

    def test_the_baseline_holds_the_new_value_of_every_total_the_entry_lists(self):
        totals = _load(COUPLED_EXACT)["coupled_scenarios"]["cleaver_bloodsong_roster"]
        for moved in self.entry["what_is_true"]["moved"]:
            assert totals[moved["key"]] == moved["new"]
            assert moved["old"] != moved["new"]
            assert float(moved["new"]) - float(moved["old"]) == pytest.approx(
                moved["delta"], abs=0.05
            )

    def test_each_moved_total_was_declared_in_advance_by_a_committed_allowlist(self):
        """R-17: the values are allowlisted, which is why they were never unreceipted."""
        declared: dict[str, dict[str, str]] = {}
        for receipt in sorted(RECEIPTS.glob("expected-*-diff-*.json")):
            body = _load(receipt)
            moves = body.get("expected_diff_paths", {}).get("coupled_exact", {})
            for key, pair in moves.get("cleaver_bloodsong_roster", {}).items():
                declared.setdefault(key, {})[pair["new"]] = receipt.name
        for moved in self.entry["what_is_true"]["moved"]:
            assert moved["new"] in declared[moved["key"]]

    def test_the_defender_total_is_the_sum_of_the_two_attacker_totals(self):
        """Two moves and one identity, on both sides of the re-capture."""
        totals = _load(COUPLED_EXACT)["coupled_scenarios"]["cleaver_bloodsong_roster"]
        moved = {m["key"]: m for m in self.entry["what_is_true"]["moved"]}
        for side in ("old", "new"):
            attackers = float(moved["combat/0:main/outgoing"][side]) + float(
                moved["combat/1:ally:Lulu/outgoing"][side]
            )
            assert attackers == pytest.approx(
                float(moved["combat/2:enemy:Aatrox/incoming"][side]), abs=0.05
            )
        assert totals["combat/2:enemy:Aatrox/incoming"] == (
            moved["combat/2:enemy:Aatrox/incoming"]["new"]
        )
