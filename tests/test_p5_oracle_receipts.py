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

The second half joins the allowlists to the *tree*.  R-17 forbids
re-capturing a baseline inside a semantic slice, so a phase's coupled-golden
diffs stand against the committed baseline plus its allowlists until the
boundary re-capture — which makes "zero diffs" uncheckable inside the phase
and left it being checked by hand, one leaf at a time.
``TestTheCoupledCompareIsFullyAllowlisted`` runs R-01 row 3's compare and
asserts what the phase actually claims: no differing leaf outside a
committed allowlist, none outside a ``rotation`` receipt object, no
allowlist entry excusing a diff that no longer moves, and the pair baseline
identical.  It survives the re-capture — an empty compare satisfies every
clause.
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


# ---------------------------------------------------------------------------
# The other half of the join: the tree against the allowlists
# ---------------------------------------------------------------------------

# The two snapshot counters umbrella criterion 4 disowns to
# ``campaign-fingerprints.json``: they count the snapshot's own leaves, so
# publishing a receipt key moves them and no allowlist may state their value.
DISOWNED_COUNTERS = (
    "/metadata/fingerprint/leaves",
    "/metadata/fingerprint/numeric_leaves",
)


def _live_coupled_diffs():
    """Every differing leaf path in R-01 row 3's compare, right now."""
    from scripts.golden_snapshot import (
        COMPARE_EXCLUDED_PROVENANCE,
        leaf_report,
        rebuild_for,
    )

    baseline = json.loads(
        (Path(__file__).resolve().parents[1] / "scripts")
        .joinpath("golden_coupled_baseline.json")
        .read_text(encoding="utf-8")
    )
    current = rebuild_for(baseline)
    for snapshot in (baseline, current):
        for key in COMPARE_EXCLUDED_PROVENANCE:
            snapshot.get("metadata", {}).pop(key, None)
    return tuple(diff.path for diff in leaf_report(baseline, current))


def _allowlisted_paths():
    """Every coupled-golden path any committed slice allowlist declares."""
    paths: set[str] = set()
    for path in sorted(RECEIPTS.glob("expected-golden-diff-*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        paths.update(data.get("expected_diff_paths", {}).get("coupled_golden", ()))
    return paths


def unallowlisted(diff_paths, allowlisted):
    """Every differing leaf no committed allowlist declares.

    The empty tuple is the pass condition.  Pure, so the negative tests
    below can hand it a diff nobody allowed and watch it say so.
    """
    return tuple(sorted(set(diff_paths) - set(allowlisted) - set(DISOWNED_COUNTERS)))


def outside_a_rotation_receipt(diff_paths):
    """Every differing leaf that is not inside a ``rotation`` object."""
    return tuple(
        sorted(
            path
            for path in diff_paths
            if "/rotation/" not in path and path not in DISOWNED_COUNTERS
        )
    )


class TestTheCoupledCompareIsFullyAllowlisted:
    """Phase 5 criterion 7 as amended: zero *unallowlisted* diffs.

    R-17 forbids re-capturing a baseline inside a semantic slice, so a
    phase's diffs stand against the committed baseline plus a committed
    allowlist until the boundary re-capture.  "Zero diffs" was therefore
    never checkable inside the phase and was checked by hand instead — the
    verifier read all of them against both allowlists one at a time.  This
    is that reading, mechanised, and it survives the re-capture: once the
    boundary lands the compare is empty and every clause holds trivially.
    """

    def test_no_differing_leaf_is_outside_a_committed_allowlist(self) -> None:
        assert unallowlisted(_live_coupled_diffs(), _allowlisted_paths()) == ()

    def test_an_undeclared_diff_is_reported(self) -> None:
        """R-05: the check fails on command, with a leaf nobody allowed."""
        smuggled = "/coupled_scenarios/x/fights/manual_target/total_damage"
        assert unallowlisted(
            _live_coupled_diffs() + (smuggled,), _allowlisted_paths()
        ) == (smuggled,)

    def test_every_differing_leaf_is_inside_a_rotation_receipt(self) -> None:
        """No computed number moves — the retirement's whole claim.

        A leaf outside a ``rotation`` object is a damage, timeline, stat or
        combat leaf, and one of those moving is the seed failing to be
        reproduced rather than the receipt gaining a field.
        """
        assert outside_a_rotation_receipt(_live_coupled_diffs()) == ()

    def test_a_moved_number_is_reported(self) -> None:
        """R-05 for the second clause: a damage leaf is never excusable."""
        moved = "/coupled_scenarios/x/fights/manual_target/breakdown/Q/total"
        assert outside_a_rotation_receipt(_live_coupled_diffs() + (moved,)) == (moved,)

    def test_the_allowlists_are_not_stale(self) -> None:
        """Every P5 allowlist path still moves — until the re-capture.

        A path that stopped moving is an allowlist entry excusing a diff
        that no longer exists, which is how an allowlist grows into a
        blanket.  After the phase-boundary re-capture the compare is empty
        and this clause retires with it.
        """
        differing = set(_live_coupled_diffs())
        if not differing:
            return
        declared: set[str] = set()
        for path in sorted(RECEIPTS.glob("expected-golden-diff-P5-*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            declared.update(data["expected_diff_paths"]["coupled_golden"])
        assert sorted(declared - differing) == []

    def test_the_pair_baseline_is_identical(self) -> None:
        """R-01 row 2's claim, pinned where the phase's other claims are."""
        from scripts.golden_snapshot import (
            COMPARE_EXCLUDED_PROVENANCE,
            leaf_report,
            rebuild_for,
        )

        baseline = json.loads(
            (Path(__file__).resolve().parents[1] / "scripts")
            .joinpath("golden_baseline.json")
            .read_text(encoding="utf-8")
        )
        current = rebuild_for(baseline)
        for snapshot in (baseline, current):
            for key in COMPARE_EXCLUDED_PROVENANCE:
                snapshot.get("metadata", {}).pop(key, None)
        assert [diff.path for diff in leaf_report(baseline, current)] == []
