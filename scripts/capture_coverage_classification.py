"""Phase 1's numeric gate: the full coverage classification of every cached item.

Golden is near-vacuous for coverage — ``pipeline.py`` does not import
``item_coverage`` — so per runbook R-11/D-93 this phase needs its own numeric
gate, and only a before-image captured from unmodified behaviour can prove
"evidence added, nothing moved".  This script is that instrument.

The receipt holds one record per **(cached item, lane)**: the complete public
dict returned by ``item_model_coverage`` on the attacker lane and by
``target_item_model_coverage`` on the target lane, for every item in
``fetch_item_data()``.  The whole dict is stored, not a status string — the
reason text, the eligibility flags, the outcome dimensions and the issue refs
are all public contract, and a receipt that kept only the status would let a
reason silently change under a green gate.

The record count is ``metadata.item_count`` x ``len(metadata.lanes)``, read
from **this** receipt.  ``scripts/golden_baseline.json`` carries a field of the
same name with the same value today; reading it there would tie a coverage
figure to the pair-engine snapshot's data pull, which is why the count has one
home and this docstring names it.  It is a coverage-record count, not a golden
leaf or entry count, so the campaign's sole-home rule for golden shape figures
(umbrella criterion 4) does not reach it.

Usage:
    python scripts/capture_coverage_classification.py capture <outfile.json>
    python scripts/capture_coverage_classification.py compare <baseline.json>
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# The sys.path bootstrap above forces every first-party import below it.
# pylint: disable=wrong-import-position
from src.calculator.data_fetcher import fetch_item_data
from src.calculator.item_coverage import (
    ATTACKER_LANES,
    item_model_coverage,
    target_item_model_coverage,
)

RECEIPT_PATH = REPO_ROOT / "docs" / "receipts" / "item-coverage-classification.json"

SCHEMA_VERSION = 1
SNAPSHOT_KIND = "item_coverage_classification"

# One classifier per lane.  ``ClaimLane`` (Phase 1's coverage vocabulary) has
# four members, but only these two answer "what is this item's coverage"; the
# support_packet and utility lanes are claim lanes with no classifier of their
# own.
CLASSIFIERS: Mapping[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "attacker": lambda item: item_model_coverage(
        str(item.get("name", "")), ATTACKER_LANES
    ).as_payload(),
    "target": target_item_model_coverage,
}

# The dotted name each lane's answer comes from.  Written out rather than read
# off ``__name__``: the attacker lane is a lambda that supplies the lane set
# ``item_model_coverage`` now requires, and a receipt recording "<lambda>" as
# its producer would name nothing a reader could look up.
CLASSIFIER_NAMES: Mapping[str, str] = {
    "attacker": "item_model_coverage",
    "target": "target_item_model_coverage",
}

# Metadata keys ``compare`` ignores: ``git_head`` moves every commit and the
# fetch stamp moves on every data pull.  ``item_count`` is deliberately absent
# from this set — it is the gate, not provenance (R-14's named-home rule).
COMPARE_EXCLUDED_PROVENANCE: frozenset[str] = frozenset(
    {"git_head", "items_fetched_at"}
)

# How a record present on one side only is rendered in a diff.
ABSENT = "<absent>"


def _git_head() -> str:
    """The current commit, or ``unknown`` outside a work tree."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip()


def capture() -> dict[str, Any]:
    """Classify every cached item on every lane, from unmodified behaviour."""
    cached = fetch_item_data()
    items = sorted(cached.values(), key=lambda item: str(item.get("name", "")))
    names = [str(item.get("name", "")) for item in items]
    if len(set(names)) != len(names):
        raise ValueError(
            "cached items do not have distinct names; the receipt keys on name "
            "and cannot represent a collision"
        )
    records = {
        lane: {name: classify(item) for name, item in zip(names, items)}
        for lane, classify in CLASSIFIERS.items()
    }
    return {
        "metadata": {
            "schema_version": SCHEMA_VERSION,
            "snapshot_kind": SNAPSHOT_KIND,
            "git_head": _git_head(),
            "items_fetched_at": _items_fetched_at(),
            "item_count": len(items),
            "lanes": sorted(CLASSIFIERS),
            "classifiers": {
                lane: f"src.calculator.item_coverage.{name}"
                for lane, name in sorted(CLASSIFIER_NAMES.items())
            },
        },
        "records": records,
    }


def _items_fetched_at() -> float | None:
    """When ``data/items.json`` was last pulled, for provenance only."""
    metadata_path = REPO_ROOT / "data" / ".items.json.meta"
    if not metadata_path.exists():
        return None
    stamp = json.loads(metadata_path.read_text(encoding="utf-8")).get("fetched_at")
    return float(stamp) if stamp is not None else None


def record_count(snapshot: Mapping[str, Any]) -> int:
    """The receipt's own record count: item_count x lanes, from its metadata."""
    metadata = snapshot["metadata"]
    return int(metadata["item_count"]) * len(metadata["lanes"])


def differing_leaves(
    old: Any, new: Any, path: str = ""
) -> tuple[tuple[str, Any, Any], ...]:
    """Every ``(path, old, new)`` where two snapshots disagree on a leaf.

    A record present on one side only is reported whole, as one diff against
    ``ABSENT`` — a dropped item is a coverage move, not a hundred leaf moves.
    """
    if isinstance(old, Mapping) and isinstance(new, Mapping):
        diffs: list[tuple[str, Any, Any]] = []
        for key in sorted(set(old) | set(new)):
            child = f"{path}.{key}" if path else str(key)
            if key not in old:
                diffs.append((child, ABSENT, new[key]))
            elif key not in new:
                diffs.append((child, old[key], ABSENT))
            else:
                diffs.extend(differing_leaves(old[key], new[key], child))
        return tuple(diffs)
    if old == new:
        return ()
    return ((path, old, new),)


def _render(value: Any) -> str:
    """One side of a diff line, with the absence marker printed bare."""
    return ABSENT if value is ABSENT else repr(value)


def compare(baseline_path: str) -> int:
    """Re-capture and report every leaf that moved against the committed receipt."""
    baseline = json.loads(Path(baseline_path).read_text(encoding="utf-8"))
    current = capture()
    for snapshot in (baseline, current):
        for key in COMPARE_EXCLUDED_PROVENANCE:
            snapshot["metadata"].pop(key, None)
    diffs = differing_leaves(baseline, current)
    for leaf, old, new in diffs:
        print(f"{leaf}: {_render(old)} -> {_render(new)}")
    if diffs:
        print(f"FAIL: {len(diffs)} difference(s) vs {baseline_path}")
        return 1
    print(f"OK: {record_count(current)} coverage records identical to {baseline_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Capture the receipt or compare a committed one against live behaviour."""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    capture_parser = sub.add_parser("capture", help="write a fresh receipt")
    capture_parser.add_argument("outfile", nargs="?", default=str(RECEIPT_PATH))
    compare_parser = sub.add_parser("compare", help="diff against a committed receipt")
    compare_parser.add_argument("baseline", nargs="?", default=str(RECEIPT_PATH))
    args = parser.parse_args(argv)

    if args.command == "capture":
        snapshot = capture()
        Path(args.outfile).write_text(
            json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"wrote {record_count(snapshot)} coverage records -> {args.outfile}")
        return 0
    return compare(args.baseline)


if __name__ == "__main__":
    sys.exit(main())
