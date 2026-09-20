"""The report entry point a tree-scanning lint shares.

A lint here answers a rule over the tree rather than regenerating a file, so
it takes no arguments: running it is the check.  Each finding goes to stdout,
one per line, and the count or the clean line goes to stderr, the shape
``literal_defaults.py`` and ``swing_stream_audit.py`` already print in.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable


def report(findings: Iterable[str], clean: str) -> int:
    """Print every finding; exit 1 when there is one."""
    rows = list(findings)
    for row in rows:
        print(row)
    print(f"{len(rows)} findings" if rows else clean, file=sys.stderr)
    return 1 if rows else 0
