"""Classify every ER5 tail site by what the evidence already says about it.

The tail is about 1,278 ``x.get(key, <literal>)`` reads, and the campaign's
repeated finding is that most of them are contracts rather than debt. A raw
count says the opposite, so this splits the population by the two clauses a
machine can answer, leaving a named remainder for the three it cannot.

``NOT_A_ROW_FIELD``
    The key is in neither census. It is not a field any stream this repo
    publishes or builds carries, so no corpus can license indexing it and
    the default is simply how that value is read. The largest class.

``TOLERANCE_CONTRACT``
    The key is censused, but the reading module's own suite pins it
    TOLERATING malformed or partial input. ``public_response`` withholds a
    malformed event by design; ``bis_objective``'s caller turns a KeyError
    into a withheld build. Indexing there converts graceful degradation
    into a crash or a silent drop, which is clause 5, the one a census can
    never answer.

``CANDIDATE``
    The key is censused and no tolerance contract is evident. Clauses 2, 3
    and 4 still apply and are judgement: does the variable certainly hold a
    row, is the container guaranteed, does the site run after publication.
    This is the only class worth a human's time.

Run it with ``report`` to print the split, or ``write`` to refresh
``docs/receipts/er5-tail-triage.json``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import literal_defaults  # noqa: E402

RECEIPT = REPO_ROOT / "docs" / "receipts" / "er5-tail-triage.json"
CALCULATOR = REPO_ROOT / "src" / "calculator"
TESTS = REPO_ROOT / "tests"
INTERNAL_CENSUS = REPO_ROOT / "docs" / "receipts" / "internal-row-census.json"

#: A test naming one of these beside a module is that module promising to
#: survive input it did not build. Clause 5 in a form a scan can see.
TOLERANCE_WORDS = ("malformed", "withhold", "partial", "unnamed", "invalid")


def _censused_keys() -> set[str]:
    """Every key either census measures on every row of some stream."""
    from tests.test_row_stream_census import CENSUS  # noqa: PLC0415

    keys: set[str] = set()
    for _, universal in CENSUS.values():
        keys |= set(universal)
    internal = json.loads(INTERNAL_CENSUS.read_text(encoding="utf-8"))
    for block in internal["streams"].values():
        keys |= set(block["universal"])
    return keys


def _tolerance_modules() -> set[str]:
    """Modules whose own suite pins them tolerating input they did not build."""
    found: set[str] = set()
    for path in TESTS.rglob("test_*.py"):
        source = path.read_text(encoding="utf-8")
        if not any(word in source.lower() for word in TOLERANCE_WORDS):
            continue
        for match in re.finditer(r"src\.calculator\.([a-z_.]+) import", source):
            found.add(match.group(1).replace(".", "/") + ".py")
    return found


def _tail_modules() -> list[Path]:
    from tests.test_literal_defaults import ER5_TAIL  # noqa: PLC0415

    return [CALCULATOR / rel for rel in ER5_TAIL if (CALCULATOR / rel).exists()]


def triage() -> dict[str, Any]:
    """Split every tail site into the three classes above."""
    censused = _censused_keys()
    tolerant = _tolerance_modules()
    buckets: Counter[str] = Counter()
    by_module: dict[str, Counter[str]] = {}
    for finding in literal_defaults.scan(_tail_modules()):
        rel = finding.path.split("src/calculator/")[1]
        if finding.key.strip("\"'") not in censused:
            bucket = "NOT_A_ROW_FIELD"
        elif rel in tolerant:
            bucket = "TOLERANCE_CONTRACT"
        else:
            bucket = "CANDIDATE"
        buckets[bucket] += 1
        by_module.setdefault(rel, Counter())[bucket] += 1
    return {
        "totals": dict(sorted(buckets.items())),
        "candidates_by_module": {
            module: counts["CANDIDATE"]
            for module, counts in sorted(by_module.items())
            if counts["CANDIDATE"]
        },
    }


def main() -> int:
    """``report`` prints the split; ``write`` refreshes the receipt."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("report", "write"))
    action = parser.parse_args().action
    result = triage()
    if action == "write":
        RECEIPT.write_text(
            json.dumps(result, indent=1, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"Wrote {RECEIPT}")
    total = sum(result["totals"].values())
    for bucket, count in result["totals"].items():
        print(f"  {bucket:20s} {count:5d}  ({count / total:.0%})")
    print(f"  {'TOTAL':20s} {total:5d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
