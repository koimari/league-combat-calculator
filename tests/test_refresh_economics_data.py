"""The sourced gold table is current for the cache it prices, and the check goes red.

``data/economics-sourced.json`` is what ``economy.py`` prices every purchase
plan from.  ``stale_reasons`` is its one definition of current; the first
test holds the committed file to it, the rest prove each reason fires.
"""

import copy
import json
from pathlib import Path

import pytest

from scripts.patch_regression import extract_ddragon_version
from scripts.refresh_economics_data import (
    ACKNOWLEDGED_TOTAL_DIVERGENCES,
    stale_reasons,
)
from src.calculator.data_fetcher import fetch_item_data

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module", name="tables")
def _tables():
    return json.loads(
        (ROOT / "data" / "economics-sourced.json").read_text(encoding="utf-8")
    )


@pytest.fixture(scope="module", name="items")
def _items():
    return fetch_item_data()


@pytest.fixture(scope="module", name="ddragon_version")
def _ddragon_version():
    champions = json.loads(
        (ROOT / "data" / "champions.json").read_text(encoding="utf-8")
    )
    return extract_ddragon_version(champions)


def _row(tables, items, name):
    item = next(item for item in items.values() if item["name"] == name)
    return next(row for row in tables["per_item_sell"] if row["id"] == int(item["id"]))


def _added_reasons(reasons, baseline):
    """The reasons one injected defect ADDED, on a file with no backlog.

    These tests unpack a single reason, which only means "this defect" if
    the committed file is already current.  The merge briefly left it
    stale (ours' 16.15.1 economics asset against main's 16.16.1 cache),
    an injected defect came back as the second of two reasons, and the
    unpacking blew up on the file's state rather than on the defect.  The
    2026-08-21 refresh cleared that backlog, so the baseline is asserted
    empty here rather than merely subtracted: a silently-reappearing
    backlog would otherwise hide behind the subtraction.
    """
    assert baseline == [], f"the committed economics file is stale: {baseline}"
    return [reason for reason in reasons if reason not in baseline]


def test_the_committed_file_is_current_for_the_committed_cache(
    tables, items, ddragon_version
):
    """A pull without a refresh, a new unpriced item, or an unreviewed total
    disagreement all land here."""
    assert ddragon_version
    assert stale_reasons(tables, items, ddragon_version) == []


def test_the_provenance_carries_no_wall_clock(tables):
    """A refresh that changes no row must leave the file byte-identical."""
    assert set(tables["provenance"]) == {"source_url", "patch"}


def test_a_cache_on_another_release_is_stale(tables, items, ddragon_version):
    baseline = stale_reasons(tables, items, ddragon_version)
    (reason,) = _added_reasons(stale_reasons(tables, items, "99.1.1"), baseline)
    # The reason names the file's own pin and the release it was asked
    # about; the pin is not assumed to already equal the cache.
    assert tables["patch"]["ddragon"] in reason
    assert "99.1.1" in reason


def test_an_ordinary_item_without_a_row_is_stale(tables, items, ddragon_version):
    trimmed = copy.deepcopy(tables)
    edge = _row(trimmed, items, "Infinity Edge")
    trimmed["per_item_sell"].remove(edge)
    baseline = stale_reasons(tables, items, ddragon_version)
    (reason,) = _added_reasons(stale_reasons(trimmed, items, ddragon_version), baseline)
    assert reason == "Infinity Edge: in the cached shop but has no sourced sell row"


def test_an_unacknowledged_total_divergence_is_stale(tables, items, ddragon_version):
    moved = copy.deepcopy(tables)
    _row(moved, items, "Infinity Edge")["total"] += 50
    baseline = stale_reasons(tables, items, ddragon_version)
    (reason,) = _added_reasons(stale_reasons(moved, items, ddragon_version), baseline)
    assert reason.startswith("Infinity Edge: cached shop total ")
    assert reason.endswith("(unacknowledged)")


def test_an_acknowledgement_that_no_longer_reproduces_is_stale(
    tables, items, ddragon_version
):
    settled = copy.deepcopy(tables)
    for name, (cached_total, _) in ACKNOWLEDGED_TOTAL_DIVERGENCES.items():
        _row(settled, items, name)["total"] = cached_total
    baseline = stale_reasons(tables, items, ddragon_version)
    assert _added_reasons(stale_reasons(settled, items, ddragon_version), baseline) == [
        f"{name}: acknowledged total divergence no longer reproduces"
        for name in sorted(ACKNOWLEDGED_TOTAL_DIVERGENCES)
    ]
