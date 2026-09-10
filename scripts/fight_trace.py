"""Print one request's fight trace, or capture it as a fixture.

Reads a calculate request as JSON and runs it through ``calculate_payload``
with ``trace=True``, so the table below is the fight the API would serve.
Every column is a fact the engine stated; a column a fight left unstated
prints its refusal name instead of a number.

    python scripts/fight_trace.py request.json
    python scripts/fight_trace.py request.json --capture fixture.json
"""

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.calculator.calculate import calculate_payload
from src.calculator.fight.ledger.trace import NO_RAW_PUBLISHED
from src.calculator.survival.pricing import NO_RESISTANCE_PUBLISHED

#: Which refusal stands in for which column, read off the names the trace
#: itself refuses by, so the table cannot print a token no line carries.
_REFUSAL_PER_COLUMN = {
    "raw": NO_RAW_PUBLISHED,
    "resistance_met": NO_RESISTANCE_PUBLISHED,
}

#: The column widths the table prints at, in order.
_COLUMNS = (
    ("time", 8),
    ("source", 30),
    ("mechanic", 30),
    ("raw", 23),
    ("damage_class", 9),
    ("resistance_met", 15),
    ("amp", 22),
    ("mitigated", 12),
    ("step", 52),
)


def _traces(payload: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any]]]:
    """Every trace the payload carries, named by the fight that produced it.

    A roster fight is keyed by index and champion, the spelling
    ``golden_snapshot.coupled_entry`` already uses, because two of one
    champion is a legal roster and a name alone would collapse them.
    """
    if "trace" in payload:
        return [("manual target", payload["trace"])]
    return [
        (f"{index}:{row['target']['champion']}", row["trace"])
        for index, row in enumerate(payload.get("targets", []))
        if "trace" in row
    ]


def _cell(line: Mapping[str, Any], column: str) -> str:
    """One column of one line: its value, or the refusal standing in for it.

    A blank is not a refusal: a true-damage line states no resistance because
    it met none, so only a column the line actually refused prints a name.
    """
    value = line[column]
    if value is not None:
        return f"{value:.4f}" if isinstance(value, float) else str(value)
    refusal = _REFUSAL_PER_COLUMN.get(column, "")
    return refusal if refusal in line["refusals"] else ""


def _print_trace(name: str, trace: Mapping[str, Any]) -> None:
    """Print one fight's header, its lines, and its refusals by source."""
    print(
        f"\n== {name}: {len(trace['lines'])} lines, effective armor "
        f"{trace['effective_armor']:.4f}, effective MR {trace['effective_mr']:.4f}"
    )
    print("  ".join(head.ljust(width) for head, width in _COLUMNS))
    for line in trace["lines"]:
        print("  ".join(_cell(line, head).ljust(width) for head, width in _COLUMNS))
    refused: dict[str, set[str]] = {}
    for line in trace["lines"]:
        if line["refusals"]:
            refused.setdefault(line["source"], set()).update(line["refusals"])
    print(f"refusals by source: {len(refused)} of the fight's sources")
    for source, names in sorted(refused.items()):
        print(f"  {source}: {', '.join(sorted(names))}")


def main() -> None:
    """Trace the request named on the command line."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("request", help="a calculate request as JSON")
    parser.add_argument("--capture", default=None, help="write the trace JSON here")
    args = parser.parse_args()

    request = json.loads(Path(args.request).read_text(encoding="utf-8"))
    payload = calculate_payload(request, deterministic=True, trace=True)
    traces = _traces(payload)
    if not traces:
        raise SystemExit("the request produced no traceable fight")
    if args.capture:
        captured = {"request": request, "traces": dict(traces)}
        Path(args.capture).write_text(
            json.dumps(captured, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"wrote {args.capture}")
        return
    for name, trace in traces:
        _print_trace(name, trace)


if __name__ == "__main__":
    main()
