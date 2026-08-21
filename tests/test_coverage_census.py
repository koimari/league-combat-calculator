"""The coverage census's residue reconciliation, and the committed receipts agree.

The sweep itself (~10 min) runs as CI's ``coverage-census`` job and on patch
day; what pytest holds is the gate's logic and that the two committed
receipts describe the same frontier.
"""

import json
from pathlib import Path

import scripts.coverage_census as census

ROOT = Path(__file__).resolve().parents[1]


def _receipt(pairs):
    return {
        "frontier": {
            "item_pair_coarse": {
                f"{champion}|Item|timed|autos=True": [source]
                for champion, source in pairs
            }
        }
    }


def _residue(monkeypatch, tmp_path, rows):
    path = tmp_path / "residue.json"
    path.write_text(
        json.dumps({"acknowledged": [{"champion": c, "source": s} for c, s in rows]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(census, "RESIDUE_PATH", path)


def test_an_acknowledged_frontier_reconciles(monkeypatch, tmp_path):
    _residue(monkeypatch, tmp_path, [("Ahri", "x")])
    assert census.reconcile_residue(_receipt([("Ahri", "x")])) == {
        "acknowledged_rows": 1,
        "unacknowledged": [],
        "stale_acknowledgements": [],
    }


def test_an_entry_nothing_acknowledges_is_reported(monkeypatch, tmp_path):
    _residue(monkeypatch, tmp_path, [("Ahri", "x")])
    residue = census.reconcile_residue(_receipt([("Ahri", "x"), ("Vi", "y")]))
    assert residue["unacknowledged"] == ["Vi|y"]
    assert residue["stale_acknowledgements"] == []


def test_an_acknowledgement_that_no_longer_reproduces_is_reported(
    monkeypatch, tmp_path
):
    _residue(monkeypatch, tmp_path, [("Ahri", "x"), ("Vi", "y")])
    residue = census.reconcile_residue(_receipt([("Ahri", "x")]))
    assert residue["unacknowledged"] == []
    assert residue["stale_acknowledgements"] == ["Vi|y"]


def test_the_committed_receipt_has_no_withhold_and_every_coarse_pair_is_acknowledged():
    """Every frontier class but the coarse pairs is empty, and the residue
    acknowledges exactly the pairs the committed receipt still reports
    across every window ``ITEM_WINDOWS`` sweeps - no entry silent, no row
    outliving its cause.  This is the census job's verdict on the pinned
    receipt, without the nine-minute run."""
    receipt = json.loads(
        (ROOT / "docs" / "coverage-census.json").read_text(encoding="utf-8")
    )
    other = {
        key: count
        for key, count in receipt["counts"].items()
        if key not in ("item_pair_coarse", "total")
    }
    assert set(other.values()) == {0}, other
    assert census.reconcile_residue(receipt) == {
        "acknowledged_rows": len(census._residue_rows()),
        "unacknowledged": [],
        "stale_acknowledgements": [],
    }
