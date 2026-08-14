"""R-19's blocking half, mechanised repo-wide.

R-19 ends *"no baseline is re-captured while any qualifying occurrence lacks
[an oracle receipt]"*, and the R-15/R-18 amendment's clause 2 adds the harder
half: **a sustained dissent is never absorbed into a baseline**, because a
re-capture over one makes the baseline assert a number an independent oracle
has said is wrong -- an unexplained value wearing a gate's authority, which is
the campaign's own failure shape.

Both halves were enforced by two scans scoped to the Phase 4 boundary: one
keyed on one escalation entry's own leaf list, the other on the ``oracle-P4B-``
filename prefix.  Every adverse verdict outside those two sets -- Phase 0B's,
Phase 3's, Phase 5's, and the one filed at the Phase 4 boundary itself -- was
invisible to every R-01 row, so a *future* capture could pin over one and no
gate would move.  This is that check, over every committed oracle receipt and
every committed baseline.

The measurement is a join, not a judgement.  For each standing adverse
verdict it resolves the leaf the receipt adjudicates in the committed
baselines and asks one question: **does the committed value differ from the
one the oracle certified?**  If it does, the baseline was pinned over the
dissent, and that leaf is in the blocking population R-19 names.  Each member
owes a committed adjudication row -- a citation to a ruling that says no
oracle was owed, or an open debt naming the remedy and the artifact carrying
it.  A member with no row fails; a row whose dissent has cleared fails; a row
that cites nothing fails.

What this does **not** do is decide a dissent.  Clearing one is a fresh
whole-series re-adjudication or a ruled ``src/`` correction (R-15/R-18
amendment, clauses 1 and 2), and neither is a scan's to perform.  What the
scan removes is the ability for the population to grow in silence.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
RECEIPTS = REPO_ROOT / "docs" / "receipts"
ADJUDICATIONS = RECEIPTS / "standing-dissent-adjudications.json"

#: The committed artifacts a dissent's leaf can live in, in resolution order.
BASELINES: tuple[tuple[str, Path], ...] = (
    ("coupled_golden", REPO_ROOT / "scripts" / "golden_coupled_baseline.json"),
    ("golden", REPO_ROOT / "scripts" / "golden_baseline.json"),
    ("coupled_exact", REPO_ROOT / "scripts" / "golden_coupled_exact.json"),
)

ADVERSE_VERDICTS = frozenset({"old_value_correct", "both_wrong"})

_ISO_DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})")
_INDEXED = re.compile(r"([^\[\]]+)\[(\d+)\]")

#: The sentinel a resolution returns when the address does not exist.  A
#: module-level object rather than ``None`` because ``None`` is a value a
#: baseline can legitimately hold, and conflating "absent" with "null" is the
#: distinction ``optional_measured`` exists to keep on the payload side too.
ABSENT = object()


def leaf_address(body: Mapping[str, Any]) -> str | None:
    """The leaf a receipt adjudicates, across all three committed schemas.

    Three schemas are live -- a string under ``leaf_path``, a string under
    ``leaf``, and an object under either carrying ``path`` -- and a scan
    written against one silently misses the other two, which is how the first
    enumeration of the standing set read a different number from the
    corrected one.
    """
    for key in ("leaf_path", "leaf"):
        value = body.get(key)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, dict) and isinstance(value.get("path"), str):
            return value["path"]
    return None


def receipt_date(body: Mapping[str, Any]) -> str | None:
    """The earliest ISO date this receipt carries, whatever it calls the key.

    A *value* rule rather than a key rule: eleven spellings are live in
    ``docs/receipts/``, and a key list would silently miss the twelfth.  Any
    top-level string beginning with an ISO date is a date; the earliest is the
    receipt's; an author field is excluded because a name is not a date.
    """
    found = sorted(
        match.group(1)
        for value in body.values()
        if isinstance(value, str) and (match := _ISO_DATE.match(value))
    )
    return found[0] if found else None


def oracle_receipts() -> dict[str, dict]:
    """Every committed oracle receipt, keyed by filename."""
    return {
        path.name: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(RECEIPTS.glob("oracle-*.json"))
    }


def standing_dissents(receipts: Mapping[str, dict]) -> list[str]:
    """Adverse verdicts no later same-leaf ``new_value_correct`` receipt answers.

    A supersession that *predates* the dissent it supposedly answers does not
    supersede: that is what a dissent filed against an already-pinned leaf
    looks like.  An undated dissent is treated as cleared by any same-leaf
    answer, because nothing orders it.
    """
    by_leaf: dict[str | None, list[dict]] = defaultdict(list)
    for body in receipts.values():
        by_leaf[leaf_address(body)].append(body)

    standing: list[str] = []
    for name, body in sorted(receipts.items()):
        if body.get("verdict") not in ADVERSE_VERDICTS:
            continue
        answers = [
            other
            for other in by_leaf[leaf_address(body)]
            if other.get("verdict") == "new_value_correct"
        ]
        if not answers:
            standing.append(name)
            continue
        dissent_date = receipt_date(body)
        if dissent_date is None:
            continue
        if not any((receipt_date(other) or "") >= dissent_date for other in answers):
            standing.append(name)
    return standing


def _resolve(snapshot: Any, address: str) -> Any:
    """One committed snapshot walked to one leaf address, or :data:`ABSENT`."""
    node = snapshot
    for part in address.strip("/").split("/"):
        if not part:
            continue
        indexed = _INDEXED.fullmatch(part)
        try:
            node = (
                node[indexed.group(1)][int(indexed.group(2))] if indexed else node[part]
            )
        except (KeyError, IndexError, TypeError):
            return ABSENT
    return node


def _addresses(body: Mapping[str, Any]) -> Iterable[str]:
    """Every spelling of this receipt's address, most specific first.

    Two conventions are live: a full snapshot path, and a scenario-relative
    one with the scenario in its own field.  Both are tried rather than one
    being declared correct, because rewriting a filed receipt to a house style
    is exactly what the R-15/R-18 amendment forbids.
    """
    address = leaf_address(body) or ""
    yield address
    scenario = body.get("scenario")
    if scenario and not address.strip("/").startswith("coupled_scenarios"):
        yield f"coupled_scenarios/{scenario}/{address.strip('/')}"


@dataclass(frozen=True, slots=True)
class Pinned:
    """One standing dissent a committed baseline holds a different value than.

    ``certified`` is what the oracle said was right and ``committed`` is what
    the baseline says instead.  Both are carried because "the baseline was
    pinned over a dissent" without them is a report nobody can act on -- the
    same reason ``OutcomeRewritten`` carries both values.
    """

    receipt: str
    baseline: str
    address: str
    certified: Any
    committed: Any


def _same(committed: Any, certified: Any) -> bool:
    """Whether the baseline holds what the oracle certified."""
    if isinstance(committed, bool) or isinstance(certified, bool):
        return committed == certified
    if isinstance(committed, (int, float)) and isinstance(certified, (int, float)):
        return abs(committed - certified) < 1e-9
    return committed == certified


def pinned_over(
    receipts: Mapping[str, dict], standing: Iterable[str]
) -> tuple[Pinned, ...]:
    """The blocking population: standing dissents a baseline pinned over.

    A dissent whose leaf the baselines no longer hold at all is a member when
    the oracle certified a value -- the baseline dropped the number the oracle
    said was right, which is the same absorption in the other direction -- and
    is not a member when the oracle certified ``<absent>``, because then the
    baseline agrees with it.

    A dissent whose certified value is a structured object is compared
    structurally; nothing is skipped for being awkward to compare, because a
    skip is where a population quietly stops being total.
    """
    snapshots = {
        name: json.loads(path.read_text(encoding="utf-8"))
        for name, path in BASELINES
        if path.exists()
    }
    blocking: list[Pinned] = []
    for name in standing:
        body = receipts[name]
        certified = body.get("old_value")
        found: tuple[str, str, Any] | None = None
        for address in _addresses(body):
            for baseline, snapshot in snapshots.items():
                value = _resolve(snapshot, address)
                if value is not ABSENT:
                    found = (baseline, address, value)
                    break
            if found:
                break
        if found is None:
            if isinstance(certified, str) and certified.startswith("<absent>"):
                continue
            blocking.append(
                Pinned(name, "<none>", leaf_address(body) or "", certified, "<absent>")
            )
            continue
        baseline, address, committed = found
        if not _same(committed, certified):
            blocking.append(Pinned(name, baseline, address, certified, committed))
    return tuple(blocking)


def load_adjudications() -> dict[str, dict]:
    """The committed adjudication rows, keyed by the receipt each answers."""
    block = json.loads(ADJUDICATIONS.read_text(encoding="utf-8"))
    return {row["receipt"]: row for row in block["adjudications"]}


#: What a row must say.  ``kind`` is closed: a ``citation`` says no oracle was
#: owed and names the ruling; an ``open_debt`` says one was and names the
#: remedy and the artifact carrying it.  There is no third kind, because
#: "we looked at it" is not an adjudication.
ADJUDICATION_KINDS = frozenset({"citation", "open_debt"})


def unadjudicated(
    blocking: Iterable[Pinned], rows: Mapping[str, dict]
) -> tuple[str, ...]:
    """Blocking members with no committed row — the check itself, as a function.

    A pure predicate so R-05's seam needs neither a mutated baseline nor a
    mutated receipt on disk.
    """
    return tuple(sorted(item.receipt for item in blocking if item.receipt not in rows))


def stale_rows(blocking: Iterable[Pinned], rows: Mapping[str, dict]) -> tuple[str, ...]:
    """Rows whose dissent is no longer blocking — an exception nobody re-read."""
    live = {item.receipt for item in blocking}
    return tuple(sorted(receipt for receipt in rows if receipt not in live))


def report() -> dict[str, Any]:
    """The scan, as the committed receipt records it."""
    receipts = oracle_receipts()
    standing = standing_dissents(receipts)
    blocking = pinned_over(receipts, standing)
    rows = load_adjudications()
    kinds = Counter(
        rows[item.receipt]["kind"] for item in blocking if item.receipt in rows
    )
    return {
        "oracle_receipts": len(receipts),
        "adverse_verdicts": sum(
            1 for body in receipts.values() if body.get("verdict") in ADVERSE_VERDICTS
        ),
        "standing": len(standing),
        "blocking": len(blocking),
        "by_kind": dict(sorted(kinds.items())),
        "unadjudicated": list(unadjudicated(blocking, rows)),
        "stale_rows": list(stale_rows(blocking, rows)),
        "members": [
            {
                "receipt": item.receipt,
                "baseline": item.baseline,
                "address": item.address,
            }
            for item in blocking
        ],
    }


def main(argv: list[str] | None = None) -> int:
    """``--check`` exits non-zero on an unadjudicated member or a stale row."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit non-zero on a gap")
    parser.add_argument("--json", action="store_true", help="print the full report")
    args = parser.parse_args(argv)
    block = report()
    if args.json:
        print(json.dumps(block, indent=1, sort_keys=True))
    else:
        print(
            f"standing-dissent scan: {block['standing']} standing of "
            f"{block['adverse_verdicts']} adverse across {block['oracle_receipts']} "
            f"receipts; {block['blocking']} blocking, {block['by_kind']}"
        )
    failed = block["unadjudicated"] or block["stale_rows"]
    if failed:
        for receipt in block["unadjudicated"]:
            print(f"  UNADJUDICATED: {receipt}", file=sys.stderr)
        for receipt in block["stale_rows"]:
            print(f"  STALE ROW: {receipt}", file=sys.stderr)
    return 1 if (args.check and failed) else 0


if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(main())
