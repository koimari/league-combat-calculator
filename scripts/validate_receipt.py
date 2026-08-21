#!/usr/bin/env python3
"""Validate gate-receipt JSON artifacts against the shared envelope.

CI runs this on every emitted ``artifacts/backend/*.json`` receipt before the
evidence bundle is uploaded.  Exit 0 when every file parses AND validates
against ``gate_receipt.validate_receipt``; exit 1 otherwise, with per-file
errors.  Schema validity is deliberately NOT the same as a green gate: a
``passed: false`` receipt is valid and must keep the job's failure signal,
while a malformed receipt fails the job even when the gate exited 0.

Usage::

    python scripts/validate_receipt.py <receipt.json> [more.json ...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from gate_receipt import validate_receipt
except ImportError:  # imported as scripts.validate_receipt in tests
    from scripts.gate_receipt import validate_receipt


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args:
        print(__doc__)
        return 2
    failed = 0
    for raw in args:
        path = Path(raw)
        try:
            receipt = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            print(f"FAIL {path}: could not read JSON — {exc}")
            failed = 1
            continue
        try:
            validate_receipt(receipt)
        except ValueError as exc:
            print(f"FAIL {path}: {exc}")
            failed = 1
            continue
        print(f"ok   {path}")
    return failed


if __name__ == "__main__":
    raise SystemExit(main())
