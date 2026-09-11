"""The coverage page is measured, never kept by hand.

``docs/coverage-status.md`` states how much of the game the calculator
models on every axis at once. A page like that is worth exactly as much as
its freshness, so ``scripts/coverage_status.py`` writes it and this is the
gate that fails when the tree moves and the page does not.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import coverage_status


def test_the_committed_page_matches_the_tree() -> None:
    assert coverage_status.main(["--check"]) == 0, (
        "docs/coverage-status.md is stale; run "
        "`python scripts/coverage_status.py --write`"
    )


def test_every_slot_state_the_measurement_reports_is_a_known_one() -> None:
    """A new state would silently fall out of every total on the page."""
    measured = coverage_status.measure()
    assert set(measured["champions"]["slots"]) <= {
        "modeled",
        "no_damage",
        "out_of_scope",
    }


def test_the_counting_options_are_split_and_nothing_is_counted_twice() -> None:
    axes = coverage_status.measure()["axes"]
    keys = [
        (name, key)
        for bucket in ("in_fight", "pre_fight", "to_review")
        for name, key, _ in axes[bucket]
    ]
    assert len(keys) == len(set(keys))
    assert len(keys) <= axes["total"]


@pytest.mark.parametrize("bucket", ["in_fight", "pre_fight"])
def test_each_split_bucket_holds_something(bucket: str) -> None:
    """An empty bucket would make the page's headline claim vacuous."""
    assert coverage_status.measure()["axes"][bucket]
