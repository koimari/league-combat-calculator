"""Every standing golden diff is enumerated in a committed receipt.

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
PAIR_BASELINE = REPO_ROOT / "scripts" / "golden_baseline.json"


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


def allowlisted_pair_paths() -> dict[str, str]:
    """The same map for the pair jurisdiction's two declaration keys."""
    claimed: dict[str, str] = {}
    for receipt in expected_diff_receipts():
        block = json.loads(receipt.read_text(encoding="utf-8"))
        paths = block.get("expected_diff_paths", {})
        for key in ("golden", "golden_shape_counters"):
            for path in paths.get(key, ()):
                claimed.setdefault(path, receipt.name)
    return claimed


def _standing_diffs(baseline_path: Path) -> tuple[gs.LeafDiff, ...]:
    """``compare``'s own difference set, without the printing or the exit code."""
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    current = gs.rebuild_for(baseline)
    for snapshot in (baseline, current):
        for key in gs.COMPARE_EXCLUDED_PROVENANCE:
            snapshot.get("metadata", {}).pop(key, None)
    return gs.leaf_report(baseline, current)


def standing_coupled_diffs() -> tuple[gs.LeafDiff, ...]:
    """The coupled baseline's standing difference set."""
    return _standing_diffs(COUPLED_BASELINE)


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


def test_every_standing_pair_diff_is_claimed_by_a_receipt():
    """The same reading for the pair baseline, which no other test compares.

    A slice that touches the pair engine declares its leaves under the
    ``golden`` keys of the same R-17 receipt; anything else moving here is
    the leak this row exists to catch.
    """
    assert unexplained(_standing_diffs(PAIR_BASELINE), allowlisted_pair_paths()) == ()


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


def _disposition_entry_claims() -> dict[str, str]:
    """Every claimed diff on a ``dispositions`` entry, mapped to its receipt."""
    return {
        path: receipt
        for path, receipt in allowlisted_coupled_paths().items()
        if "/combat/dispositions/" in path
    }


def _described_leaf(entry_path: str) -> str:
    """The payload leaf a claimed ``dispositions`` entry describes.

    ``/…/combat/dispositions/events[57].damage/disposition`` describes
    ``/…/combat/events[57]/damage`` — the map is keyed by the dotted path a
    reader walks to reach the leaf, while ``compare`` spells the same leaf
    with slashes, so the dots are translated here and the two can meet.
    """
    scenario, _, rest = entry_path.partition("/combat/dispositions/")
    leaf = rest.rsplit("/", 1)[0]
    return _slash_leaf(f"{scenario}/combat/{leaf}")


def _slash_leaf(path: str) -> str:
    """``compare``'s spelling of a leaf path: slashes between keys, ``[N]`` kept."""
    scenario, sep, leaf = path.partition("/combat/")
    return f"{scenario}{sep}{leaf.replace('.', '/')}"


def test_a_claimed_disposition_transition_names_the_leaf_it_describes():
    """Amendment E's third guard, half one: the receipt states the leaf.

    A citation adjudicates a change in what a payload *says about* a number.
    Which number is not left to a reader to work out from a path: the
    allowlist names it, with the value it holds on both sides, or the claim
    is not one this guard can check.
    """
    for path, receipt_name in _disposition_entry_claims().items():
        if not path.endswith("/disposition"):
            continue
        block = json.loads((RECEIPTS / receipt_name).read_text(encoding="utf-8"))
        described = block.get("described_leaves", {}).get("leaves", {})
        assert path in described, f"{receipt_name} claims {path} and describes no leaf"
        # Receipts may spell the leaf in either the dotted entry form or
        # ``compare``'s slash form; both name the same leaf.
        assert _slash_leaf(described[path]["describes"]) == _described_leaf(path)


def test_a_claimed_disposition_transition_moves_no_number():
    """Amendment E's third guard, half two: and the leaf did not move — or,
    if it did, the number itself is claimed under its own snapshot path.

    This is the guard that separates the ruling from a loophole.  Citation
    adjudication is available *because* nothing an oracle could price
    changed; the moment the described leaf is itself in the difference set,
    the occurrence is a value question, owes its investigator under R-19,
    and no citation reaches it.  Asserted against ``compare``'s own
    difference set rather than against the receipt's word for it.
    """
    moved = {diff.path for diff in standing_coupled_diffs()}
    claimed = allowlisted_coupled_paths()
    for path in _disposition_entry_claims():
        if not path.endswith("/disposition"):
            continue
        leaf = _described_leaf(path)
        if leaf not in moved:
            continue
        # The leaf moved: the disposition change is a consequence of a value
        # change, so the value itself must be claimed under its own snapshot
        # path — a citation alone cannot carry it.
        assert leaf in claimed, (
            f"{path} is claimed as a disposition transition, but the leaf it "
            f"describes moved and {leaf} is claimed by no receipt — that is a "
            "value question and owes an oracle"
        )
