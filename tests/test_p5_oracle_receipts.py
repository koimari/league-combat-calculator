"""Gate for Phase 5's oracle receipts against their diff allowlists.

R-19 says a qualifying golden occurrence moves no baseline until an
independent investigator files a receipt naming the leaf, both values and
a verdict from a closed set.  Sixty-four receipts and fourteen receipts
were filed, and nothing read them: the leaf paths in the P5-retire set all
omitted the ``/fights/manual_target/`` segment, so not one of them was a
string that appears in the compare output or in the committed allowlist,
and a commit body counted the verdicts by hand and got the count wrong.
Both failures are the campaign's own shape — a check that could not fail
was indistinguishable from a check that passed.

So the join is machine-checked here.  For each committed
``expected-golden-diff-P5-*.json``: every expected diff path has exactly
one receipt whose ``leaf_path`` is that path *literally*, every receipt
carries a verdict from R-19's closed set, and the allowlist's recorded
tally is recomputed from the receipts rather than trusted.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

RECEIPTS = Path(__file__).resolve().parents[1] / "docs" / "receipts"

# R-19's closed verdict set.  A receipt outside it has not answered the
# question the investigator was sent to answer.
VERDICTS = {"new_value_correct", "old_value_correct", "both_wrong"}

# The Phase 5 slices whose allowlists carry an oracle-receipt block.
ALLOWLISTS = sorted(
    path.name for path in RECEIPTS.glob("expected-golden-diff-P5-*.json")
)


def _load(name):
    return json.loads((RECEIPTS / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module", params=ALLOWLISTS)
def allowlist(request):
    """One slice's committed diff allowlist."""
    return request.param, _load(request.param)


def _receipts(block):
    """Every receipt file the block's prefix names, by leaf path."""
    by_path = {}
    for path in sorted(RECEIPTS.glob(f"{block['prefix']}leaf*.json")):
        receipt = json.loads(path.read_text(encoding="utf-8"))
        by_path.setdefault(receipt["leaf_path"], []).append((path.name, receipt))
    return by_path


class TestOracleReceiptsCoverTheirAllowlist:
    def test_the_allowlist_declares_its_receipts(self, allowlist) -> None:
        name, data = allowlist
        assert "oracle_receipts" in data, f"{name} names no oracle receipts"
        assert data["oracle_receipts"]["prefix"].startswith("oracle-P5-")

    def test_every_expected_diff_path_has_exactly_one_receipt(self, allowlist) -> None:
        """The join R-19 implies, as strings rather than as intent."""
        name, data = allowlist
        block = data["oracle_receipts"]
        by_path = _receipts(block)
        expected = data["expected_diff_paths"]["coupled_golden"]
        assert expected, f"{name} allowlists no coupled-golden path"
        for path in expected:
            covering = by_path.get(path, [])
            assert len(covering) == 1, f"{name}: {path} has {len(covering)} receipts"
        assert set(by_path) == set(expected), (
            f"{name}: receipts cover paths outside the allowlist: "
            f"{sorted(set(by_path) - set(expected))}"
        )

    def test_the_recorded_receipt_names_are_the_files_on_disk(self, allowlist) -> None:
        name, data = allowlist
        block = data["oracle_receipts"]
        by_path = _receipts(block)
        for path, filename in block["by_leaf_path"].items():
            assert by_path[path][0][0] == filename, f"{name}: {path}"

    def test_every_receipt_carries_a_verdict_and_both_values(self, allowlist) -> None:
        name, data = allowlist
        for covering in _receipts(data["oracle_receipts"]).values():
            filename, receipt = covering[0]
            assert receipt["verdict"] in VERDICTS, f"{name}: {filename}"
            for field in ("old_value", "new_value"):
                assert field in receipt, f"{name}: {filename} omits {field}"

    def test_the_recorded_tally_is_the_measured_tally(self, allowlist) -> None:
        """The one count in the campaign that is a count of receipts."""
        name, data = allowlist
        block = data["oracle_receipts"]
        measured = {verdict: 0 for verdict in VERDICTS}
        for covering in _receipts(block).values():
            measured[covering[0][1]["verdict"]] += 1
        recorded = block["verdict_tally"]
        for verdict, count in measured.items():
            assert recorded[verdict] == count, f"{name}: {verdict}"
        assert recorded["total"] == sum(measured.values()), name
        assert (
            recorded["dissenting"]
            == measured["old_value_correct"] + measured["both_wrong"]
        ), name
