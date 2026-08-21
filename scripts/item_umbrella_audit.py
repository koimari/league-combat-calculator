"""Audit ordinary-item coverage across manual, roster, and optimizer paths.

The full-entry audit proves that each cached page was read.  This companion
gate proves that the runtime coverage contract does not lose an item between
the manual picker, passive roster validation, and optimizer candidate pool.
Blocked effects are acceptable only when their source-backed reason is
explicit; an unexplained block or a review-pending item fails the audit.

Usage::

    .venv/bin/python scripts/item_umbrella_audit.py
    .venv/bin/python scripts/item_umbrella_audit.py --json
    .venv/bin/python scripts/item_umbrella_audit.py --output docs/item-umbrella-audit.json
    .venv/bin/python scripts/item_umbrella_audit.py --check

``--check`` compares the committed receipt against a fresh run and names every
field that drifted; ``--output`` is how a slice that moved one refreshes it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from gate_receipt import build_receipt
except ImportError:  # imported as scripts.item_umbrella_audit in tests
    from scripts.gate_receipt import build_receipt

from src.calculator.data_fetcher import fetch_item_data
from src.calculator.item_coverage import (
    ATTACKER_LANES,
    item_model_coverage,
    target_item_model_coverage,
)
from src.calculator.item_source import is_ordinary_sr_item, source_audit
from src.calculator.optimizer import (
    get_eligible_boots,
    get_eligible_legendaries,
    get_selectable_items,
)

RECEIPT_PATH = ROOT / "docs" / "item-umbrella-audit.json"

# How a field present on one side of a comparison only is rendered.
ABSENT = "<absent>"


def _names(items: list[Mapping[str, Any]]) -> set[str]:
    """Return stable item names from a runtime pool."""

    return {str(item.get("name", "")) for item in items if item.get("name")}


def _keyed_by_item(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """The receipt with its entry list re-keyed by item name.

    Comparison is by name and never by list position: the entries are sorted
    by name today, so a cache that gains an item would otherwise report every
    entry after it as moved and bury the one field that actually changed.
    """

    keyed = dict(receipt)
    keyed["entries"] = {
        str(entry.get("name", "")): entry for entry in receipt.get("entries", [])
    }
    return keyed


def receipt_diff(
    committed: Mapping[str, Any], fresh: Mapping[str, Any]
) -> tuple[tuple[str, Any, Any], ...]:
    """Every ``(path, committed, fresh)`` where two audit receipts disagree.

    The committed receipt is a coverage answer for 209 items, refreshed by
    hand; nothing regenerates it and, before this function existed, nothing
    compared it to a fresh run either — so a coverage change moved the runtime
    answer and left the published one behind with every gate green.  This is
    the comparison that makes that visible, and ``--check`` and the test in
    ``tests/test_item_umbrella_audit.py`` are its two callers.
    """

    def walk(old: Any, new: Any, path: str) -> list[tuple[str, Any, Any]]:
        if isinstance(old, Mapping) and isinstance(new, Mapping):
            found: list[tuple[str, Any, Any]] = []
            for key in sorted(set(old) | set(new)):
                child = f"{path}.{key}" if path else str(key)
                found.extend(walk(old.get(key, ABSENT), new.get(key, ABSENT), child))
            return found
        return [] if old == new else [(path, old, new)]

    return tuple(walk(_keyed_by_item(committed), _keyed_by_item(fresh), ""))


def run_audit() -> dict[str, Any]:
    """Return the deterministic CP20 item-umbrella audit receipt."""

    cached = fetch_item_data()
    ordinary = sorted(
        (item for item in cached.values() if is_ordinary_sr_item(item)),
        key=lambda item: str(item.get("name", "")),
    )
    by_name = {str(item["name"]): item for item in ordinary}

    manual_names = _names(get_selectable_items()) | _names(get_eligible_boots(None))
    optimizer_names = (
        _names(get_eligible_legendaries())
        | _names(get_eligible_boots(2))
        | _names(get_eligible_boots(3))
    )
    runtime_names = manual_names | optimizer_names

    entries: list[dict[str, Any]] = []
    unexplained_blocks: list[dict[str, str]] = []
    review_pending: list[str] = []
    path_mismatches: list[dict[str, Any]] = []
    for name in sorted(by_name):
        item = by_name[name]
        attacker = item_model_coverage(
            str(item.get("name", "")), ATTACKER_LANES
        ).as_payload()
        target = target_item_model_coverage(item)
        if (
            attacker["status"] == "review_pending"
            or target["status"] == "review_pending"
        ):
            review_pending.append(name)
        for path, coverage in (("attacker", attacker), ("target", target)):
            if (
                coverage["status"] in {"withheld", "review_pending"}
                and not str(coverage.get("reason", "")).strip()
            ):
                unexplained_blocks.append({"item": name, "path": path})
        manual = name in manual_names
        optimizer = name in optimizer_names
        if (
            manual
            and optimizer
            and attacker["calculation_eligible"] != attacker["optimizer_eligible"]
        ):
            path_mismatches.append(
                {
                    "item": name,
                    "manual_calculation_eligible": attacker["calculation_eligible"],
                    "optimizer_eligible": attacker["optimizer_eligible"],
                    "reason": attacker["reason"],
                }
            )
        entries.append(
            {
                "name": name,
                "manual": manual,
                "optimizer": optimizer,
                "attacker": attacker,
                "target": target,
            }
        )

    source = source_audit(cached.values())
    unresolved_source = [
        {"item": entry["item"], "effect": entry["effect"]}
        for entry in source.get("conflicts", [])
        if not entry.get("acknowledged")
    ]
    unresolved_source.extend(
        {"item": entry["item"], "effect": entry["effect"]}
        for entry in source.get("open_conflicts", [])
    )

    counts = {
        "ordinary_source_items": len(ordinary),
        "manual_items_and_boots": len(manual_names),
        "optimizer_items_and_boots": len(optimizer_names),
        "runtime_items": len(runtime_names),
        "review_pending": len(review_pending),
        "unexplained_blocks": len(unexplained_blocks),
        "path_mismatches": len(path_mismatches),
        "unresolved_source_conflicts": len(unresolved_source),
        "attacker_blocked": sum(
            entry["attacker"]["status"] == "withheld" for entry in entries
        ),
        "target_blocked": sum(
            entry["target"]["status"] == "withheld" for entry in entries
        ),
    }
    passed = not any(
        (
            review_pending,
            unexplained_blocks,
            path_mismatches,
            unresolved_source,
        )
    )

    # Envelope (issue #139): one unit per failing *distinct* item, deduped
    # across the four checks so the sums cannot double-count.  Source
    # conflicts can name non-ordinary records, which are outside the runtime
    # umbrella's covered units; they still fail the gate, so they are added
    # to ``total`` as gate units rather than silently ignored.
    failing: dict[str, list[str]] = {}
    for name in review_pending:
        failing.setdefault(name, []).append("review_pending")
    for row in unexplained_blocks:
        failing.setdefault(row["item"], []).append("unexplained_block")
    for row in path_mismatches:
        failing.setdefault(row["item"], []).append("path_mismatch")
    for row in unresolved_source:
        failing.setdefault(row["item"], []).append("unresolved_source_conflict")
    ordinary_names = {entry["name"] for entry in entries}
    failed = len(failing)
    total = len(entries) + len(set(failing) - ordinary_names)
    failures = [
        {"item": name, "reason": "; ".join(sorted(reasons))}
        for name, reasons in sorted(failing.items())
    ]
    report = build_receipt(
        matrix="item_umbrella_runtime_coverage",
        passed=passed,
        passed_count=total - failed,
        failed_count=failed,
        total_count=total,
        withheld_count=0,
        failures=failures,
        extra={
            "audit": "item_umbrella_runtime_coverage",
            "review_pending": review_pending,
            "unexplained_blocks": unexplained_blocks,
            "path_mismatches": path_mismatches,
            "unresolved_source_conflicts": unresolved_source,
            "entries": entries,
            "source_complete": bool(source.get("complete")),
        },
    )
    # The detailed per-scope counts stay addressable for existing consumers.
    report["counts"].update(counts)
    return report


def check_committed_receipt() -> int:
    """Report every field where the committed receipt and a fresh run disagree."""

    committed = json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))
    drift = receipt_diff(committed, run_audit())
    for path, old, new in drift:
        print(f"{path}: {old!r} -> {new!r}")
    if drift:
        print(
            f"FAIL: {len(drift)} field(s) drifted vs {RECEIPT_PATH.name}; refresh it "
            f"with --output docs/{RECEIPT_PATH.name} in the commit that moved them"
        )
        return 1
    print(f"OK: {RECEIPT_PATH.name} is what a fresh audit produces")
    return 0


def main() -> int:
    """Run the audit and return a shell-friendly status code."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit the full receipt")
    parser.add_argument("--output", type=Path, help="write the full receipt to a file")
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare the committed receipt against a fresh run",
    )
    args = parser.parse_args()
    if args.check:
        return check_committed_receipt()
    receipt = run_audit()
    encoded = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
    if args.json:
        print(encoded, end="")
    else:
        print(json.dumps({"passed": receipt["passed"], "counts": receipt["counts"]}))
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
