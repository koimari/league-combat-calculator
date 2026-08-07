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
    item_model_coverage,
    target_item_model_coverage,
)
from src.calculator.item_source import is_ordinary_sr_item, source_audit
from src.calculator.optimizer import (
    get_eligible_boots,
    get_eligible_legendaries,
    get_selectable_items,
)


def _names(items: list[Mapping[str, Any]]) -> set[str]:
    """Return stable item names from a runtime pool."""

    return {str(item.get("name", "")) for item in items if item.get("name")}


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
        attacker = item_model_coverage(item)
        target = target_item_model_coverage(item)
        if (
            attacker["status"] == "review_pending"
            or target["status"] == "review_pending"
        ):
            review_pending.append(name)
        for path, coverage in (("attacker", attacker), ("target", target)):
            if (
                coverage["status"] in {"blocked", "review_pending"}
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
            entry["attacker"]["status"] == "blocked" for entry in entries
        ),
        "target_blocked": sum(
            entry["target"]["status"] == "blocked" for entry in entries
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


def main() -> int:
    """Run the audit and return a shell-friendly status code."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit the full receipt")
    parser.add_argument("--output", type=Path, help="write the full receipt to a file")
    args = parser.parse_args()
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
