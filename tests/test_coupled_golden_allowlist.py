"""Every standing coupled-golden diff is enumerated in a committed receipt.

R-17 lands a semantic slice against the *old* coupled baseline plus a
committed allowlist of expected diff paths, and re-captures once per phase
boundary.  The consequence nobody wrote down is that between two boundaries
``compare`` against ``scripts/golden_coupled_baseline.json`` **cannot** exit
zero — the allowlisted diffs are still standing, by design.  So a criterion
demanding "zero coupled-golden diffs" is unsatisfiable, and every reader of
it has been reduced to matching the standing paths against the receipts by
hand, which is the silent-reinterpretation shape this campaign exists to end.

This is that match, mechanised.  The predicate is a subset and not an
equality, deliberately: it stays true across the boundary re-capture that
empties the difference set, and it goes red the moment a slice moves a leaf
no receipt claims.
"""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import golden_snapshot as gs  # noqa: E402  (path is set above)

RECEIPTS = REPO_ROOT / "docs" / "receipts"
COUPLED_BASELINE = REPO_ROOT / "scripts" / "golden_coupled_baseline.json"


def expected_diff_receipts() -> tuple[Path, ...]:
    """Every committed R-17 allowlist, found by name and never listed."""
    return tuple(sorted(RECEIPTS.glob("expected-golden-diff-*.json")))


def allowlisted_coupled_paths() -> dict[str, str]:
    """Each allowlisted coupled leaf path mapped to the receipt claiming it.

    ``coupled_golden`` holds the leaves a slice moved; the derived shape
    counters that move *because* leaves were added or removed live beside
    them under ``coupled_golden_shape_counters``, so both are read here and
    neither is special-cased in the assertion.
    """
    claimed: dict[str, str] = {}
    for receipt in expected_diff_receipts():
        block = json.loads(receipt.read_text(encoding="utf-8"))
        paths = block.get("expected_diff_paths", {})
        for key in ("coupled_golden", "coupled_golden_shape_counters"):
            for path in paths.get(key, ()):
                claimed.setdefault(path, receipt.name)
    return claimed


def standing_coupled_diffs() -> tuple[gs.LeafDiff, ...]:
    """``compare``'s own difference set, without the printing or the exit code."""
    baseline = json.loads(COUPLED_BASELINE.read_text(encoding="utf-8"))
    current = gs.rebuild_for(baseline)
    for snapshot in (baseline, current):
        for key in gs.COMPARE_EXCLUDED_PROVENANCE:
            snapshot.get("metadata", {}).pop(key, None)
    return gs.leaf_report(baseline, current)


def unexplained(diffs, claimed) -> tuple[str, ...]:
    """The check itself, as a pure function — the seam R-05 requires."""
    return tuple(sorted(diff.path for diff in diffs if diff.path not in claimed))


def test_the_allowlist_mechanism_has_receipts_to_read():
    """A vacuous allowlist would make the check below pass by emptiness."""
    assert expected_diff_receipts(), "no expected-golden-diff receipt is committed"
    assert allowlisted_coupled_paths()


def test_every_standing_coupled_diff_is_claimed_by_a_receipt():
    """R-01 row 3's real pass condition: *every diff explained*, not zero.

    A leaf this reports is a leaf whose value moved with no slice admitting
    it in advance — an undeclared occurrence, which R-20 makes a stop rather
    than a budget overrun.
    """
    assert unexplained(standing_coupled_diffs(), allowlisted_coupled_paths()) == ()


def test_an_unclaimed_leaf_turns_the_check_red():
    """The permanent negative (R-05): the check can fail on demand.

    Injected at the *predicate*, over a fabricated diff, so the seam needs
    neither a mutated baseline nor a mutated receipt on disk.
    """
    claimed = allowlisted_coupled_paths()
    fabricated = gs.LeafDiff(
        path="/coupled_scenarios/no_such_scenario/combat/total_damage",
        section="coupled_scenarios",
        old=1.0,
        new=2.0,
        abs_delta=1.0,
        percent=100.0,
        transition="value",
    )
    assert unexplained((fabricated,), claimed) == (fabricated.path,)
    # ...and a claimed path is not reported, so the red above is the
    # injection and not the predicate rejecting everything.
    a_claimed_path = sorted(claimed)[0]
    assert (
        unexplained(
            (
                gs.LeafDiff(
                    path=a_claimed_path,
                    section="coupled_scenarios",
                    old=1.0,
                    new=2.0,
                    abs_delta=1.0,
                    percent=100.0,
                    transition="value",
                ),
            ),
            claimed,
        )
        == ()
    )


@pytest.mark.parametrize("receipt", expected_diff_receipts(), ids=lambda p: p.name)
def test_every_receipt_names_the_baseline_it_landed_against(receipt):
    """An allowlist that does not say what it is an allowlist *of* is prose."""
    block = json.loads(receipt.read_text(encoding="utf-8"))
    landed = block.get("landed_against", {})
    assert landed.get("coupled_golden") == "scripts/golden_coupled_baseline.json"
