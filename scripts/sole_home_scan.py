"""Criterion 4's second half, mechanised: receipts and commit bodies.

Umbrella criterion 4 says no campaign document, receipt or commit body states
a golden leaf or entry count of a committed baseline, because
``campaign-fingerprints.json`` is the sole home of every such figure.  It
names the check as two halves.  The first --- ``docs/plans/*.md`` --- has been
a gate since R-37: ``plan_audit.py``'s check 2, riding ``pytest``.  The second
--- ``docs/receipts/`` and the commit bodies over the campaign range --- was
specified as *the integration agent's scan at every barrier*, which is a
person or an agent reading, and a check nobody can fail on demand is
indistinguishable from a check that passes.  The campaign's closing report
found nine sites by running exactly that scan by hand, and nothing in the tree
would have noticed a tenth.

This is that scan as an instrument.  It is a separate script rather than a
fourth ``plan_audit`` check because R-37 rules that ``plan_audit.py`` runs
three checks over ``docs/plans/*.md``, and widening a ruled instrument's
jurisdiction to make a different criterion green is the kind of quiet
re-interpretation this campaign exists to stop.

**The detection rule is the plans' proximity prong, re-aimed.**  A bare value
match over receipts is useless: three of the live shape counts are small
integers that any receipt may legitimately hold for unrelated reasons.  So a
site is reported when a live shape count appears *near* something that makes
it a shape claim --- a ``/metadata/fingerprint/`` leaf path, the phrases
``leaf count``, ``entry count`` or ``numeric_leaves``, or one of the receipt's
own qualified field names read at run time (``golden.leaves``,
``coupled_golden.numeric_leaves``, ...) --- and carries no ``fingerprint:``
citation marker.  Everything else is out of reach by construction rather than
by the instrument being lax.

**Two kinds of allowance, and the difference is the point.**  A
``coincidence`` row says the value is not that figure at all.  A
``forced_restatement`` row says it *is* --- and that another rule made writing
it unavoidable: an oracle receipt must state the two values of the leaf it
adjudicates (R-19), an allowlist must state the expected old and new value of
each path it claims (R-17), and a baseline-move commit owes one line of cause
per moved value (R-34).  The ``/metadata/fingerprint/*`` leaves are themselves
leaves of the snapshot, so a receipt that adjudicates or allowlists one has to
restate it.  Those rows are criterion 4's open residue, not its discharge, and
the scan pins **how many** there are so the residue cannot grow in silence ---
which is the whole difference between a gap and a habit.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
RECEIPTS_DIR = REPO_ROOT / "docs" / "receipts"
FINGERPRINTS_PATH = RECEIPTS_DIR / "campaign-fingerprints.json"
ALLOWLIST_PATH = RECEIPTS_DIR / "golden-figure-sole-home.json"

#: The commit the campaign branched from.  Not a golden figure: it is the
#: left-hand end of the range criterion 4 binds, and the closing report names
#: the same one.
CAMPAIGN_BASE = "584071e"

#: Blocks of the fingerprints receipt whose integer members are shape counts.
GOLDEN_FINGERPRINT_BLOCKS = ("golden", "coupled_golden", "coupled_golden_exact")

#: Prose that is a shape claim wherever it appears, whatever the receipt is
#: about.  The bare word ``golden`` is deliberately **not** here: half the
#: receipts are named ``expected-golden-diff-*`` and every allowlist has a
#: ``"golden"`` key, so it marks nearly every integer in the corpus and a
#: check that reports nearly everything reports nothing.
SHAPE_CONTEXT_PHRASES = (
    "metadata/fingerprint",
    "leaf count",
    "entry count",
    "numeric_leaves",
)

#: The citation marker an integer in that neighbourhood may carry instead.
FINGERPRINT_MARKER = "fingerprint:"

#: How many whitespace tokens count as "near".  Wider than the plans' six
#: because a JSON receipt wraps a leaf path, an old value and a new value
#: across several quoted fields.
PROXIMITY_TOKENS = 12

_STANDALONE_INT = re.compile(r"(?<![\w.\-])(\d+)(?![\w.\-])")

#: Allowance kinds, closed.  ``forced_restatement`` is the residue criterion 4
#: has not discharged; ``coincidence`` is a value that is not the figure.
ALLOWANCE_KINDS = ("coincidence", "forced_restatement")


@dataclass(frozen=True, slots=True)
class Site:
    """One integer, where it is written, and which shape count it equals."""

    source: str
    value: int
    fields: tuple[str, ...]

    def key(self) -> tuple[str, int]:
        """What an allowance row matches on."""
        return (self.source, self.value)


@dataclass(frozen=True, slots=True)
class Allowance:
    """One committed row excusing one (source, value) pair."""

    source: str
    value: int
    kind: str
    reason: str

    def key(self) -> tuple[str, int]:
        """What this row admits."""
        return (self.source, self.value)


def live_counts(fingerprints: Mapping[str, Any]) -> dict[int, tuple[str, ...]]:
    """Every golden shape count in the receipt, keyed by value.

    Read at run time and never typed, for the same reason ``plan_audit`` reads
    them: the receipt is the sole home, so the gate forbidding restatement has
    to learn the figures from it rather than carry a second copy.
    """
    counts: dict[int, tuple[str, ...]] = {}
    for block in GOLDEN_FINGERPRINT_BLOCKS:
        for key, value in (fingerprints.get(block) or {}).items():
            if isinstance(value, int) and not isinstance(value, bool):
                counts[value] = counts.get(value, ()) + (f"{block}.{key}",)
    return counts


def shape_context(counts: Mapping[int, tuple[str, ...]]) -> re.Pattern[str]:
    """What marks a nearby integer as a shape claim.

    Half derived: every qualified field name the fingerprints receipt holds
    (``golden.leaves``, ``coupled_golden.numeric_leaves``, ...) is a context,
    read from the receipt so a block renamed there is renamed here with no
    second edit — the same reason the values themselves are read rather than
    typed.
    """
    fields = sorted({field for names in counts.values() for field in names})
    return re.compile(
        "|".join(
            [re.escape(phrase) for phrase in SHAPE_CONTEXT_PHRASES]
            + [re.escape(field) for field in fields]
        ),
        re.IGNORECASE,
    )


def scan_text(
    source: str, text: str, counts: Mapping[int, tuple[str, ...]]
) -> tuple[Site, ...]:
    """Every shape-count integer in *text* standing in a shape context.

    Zero is excluded: ``coupled_golden_exact.numeric_leaves`` is 0 because the
    exact snapshot holds only ``repr(float)`` strings, and a bare 0 is a diff
    count, an occurrence count or a float in every campaign artifact that has
    one.  Reporting it would drown the signal in its own noise.
    """
    context = shape_context(counts)
    words = list(re.finditer(r"\S+", text))
    tokens = [word.group() for word in words]
    contexts = [index for index, token in enumerate(tokens) if context.search(token)]
    if not contexts:
        return ()
    found: list[Site] = []
    for index, token in enumerate(tokens):
        match = _STANDALONE_INT.search(token)
        if match is None:
            continue
        value = int(match.group(1))
        if value == 0 or value not in counts:
            continue
        if not any(abs(index - hit) <= PROXIMITY_TOKENS for hit in contexts):
            continue
        window = tokens[max(0, index - PROXIMITY_TOKENS) : index + PROXIMITY_TOKENS + 1]
        if any(FINGERPRINT_MARKER in near for near in window):
            continue
        found.append(Site(source=source, value=value, fields=counts[value]))
    return tuple(found)


def receipt_sites(counts: Mapping[int, tuple[str, ...]]) -> tuple[Site, ...]:
    """Every site in ``docs/receipts/``, the sole home itself excepted."""
    found: list[Site] = []
    for path in sorted(RECEIPTS_DIR.glob("*")):
        if path.is_dir() or path == FINGERPRINTS_PATH or path == ALLOWLIST_PATH:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        found.extend(scan_text(path.name, text, counts))
    return tuple(found)


def commit_bodies(base: str = CAMPAIGN_BASE) -> tuple[tuple[str, str], ...]:
    """Every ``(sha, body)`` in the campaign range, newest first.

    Raises:
        RuntimeError: git is unavailable or the range does not resolve.  Fail
            closed: a scan that silently returns nothing over the half of
            criterion 4 nobody was checking would reproduce the gap it exists
            to close.
    """
    try:
        completed = subprocess.run(
            ["git", "log", "--format=%H%n%B%n<<<END>>>", f"{base}..HEAD"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise RuntimeError(
            f"cannot read the campaign range {base}..HEAD: {error}"
        ) from error
    out: list[tuple[str, str]] = []
    for chunk in completed.stdout.split("<<<END>>>"):
        chunk = chunk.strip()
        if not chunk:
            continue
        sha, _, body = chunk.partition("\n")
        out.append((sha, body))
    return tuple(out)


def commit_sites(
    counts: Mapping[int, tuple[str, ...]], bodies: Sequence[tuple[str, str]]
) -> tuple[Site, ...]:
    """Every site in a campaign commit body, sourced by short sha."""
    found: list[Site] = []
    for sha, body in bodies:
        found.extend(scan_text(sha[:8], body, counts))
    return tuple(found)


def load_allowlist(path: Path = ALLOWLIST_PATH) -> tuple[Allowance, ...]:
    """The committed allowlist, read rather than typed (criterion 7's shape)."""
    block = json.loads(path.read_text(encoding="utf-8"))
    rows = tuple(
        Allowance(
            source=row["source"],
            value=int(row["value"]),
            kind=row["kind"],
            reason=row["reason"],
        )
        for row in block["allowances"]
    )
    unknown = sorted({row.kind for row in rows} - set(ALLOWANCE_KINDS))
    if unknown:
        raise ValueError(f"unknown allowance kind(s): {unknown}")
    return rows


def unexplained(
    sites: Iterable[Site], allowances: Iterable[Allowance]
) -> tuple[Site, ...]:
    """The check itself, as a pure function — the seam R-05 requires."""
    admitted = {row.key() for row in allowances}
    seen: dict[tuple[str, int], Site] = {}
    for site in sites:
        if site.key() not in admitted:
            seen.setdefault(site.key(), site)
    return tuple(sorted(seen.values(), key=lambda site: (site.source, site.value)))


def stale(
    sites: Iterable[Site], allowances: Iterable[Allowance]
) -> tuple[Allowance, ...]:
    """Rows excusing a site the tree no longer holds.

    An allowance that outlives its site is how a list of exceptions becomes a
    list nobody re-reads — the same failure ``behavior_frontier``'s deferral
    gate refuses one counter over.
    """
    present = {site.key() for site in sites}
    return tuple(row for row in allowances if row.key() not in present)


def report(base: str = CAMPAIGN_BASE) -> dict[str, Any]:
    """The whole scan, as data."""
    counts = live_counts(json.loads(FINGERPRINTS_PATH.read_text(encoding="utf-8")))
    allowances = load_allowlist()
    sites = receipt_sites(counts) + commit_sites(counts, commit_bodies(base))
    forced = tuple(row for row in allowances if row.kind == "forced_restatement")
    return {
        "range": f"{base}..HEAD",
        "sites": len(sites),
        "unexplained": [
            {"source": site.source, "value": site.value, "fields": list(site.fields)}
            for site in unexplained(sites, allowances)
        ],
        "stale_allowances": [
            {"source": row.source, "value": row.value}
            for row in stale(sites, allowances)
        ],
        "forced_restatements": len(forced),
        "coincidences": len(allowances) - len(forced),
    }


def main(argv: Sequence[str] | None = None) -> int:
    """``--check`` exits non-zero on an unexplained site or a stale row."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 on a finding")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument("--base", default=CAMPAIGN_BASE, help="campaign base sha")
    args = parser.parse_args(argv)
    block = report(args.base)
    if args.json:
        print(json.dumps(block, indent=1))
    else:
        print(
            f"sole-home scan over {block['range']}: {block['sites']} site(s), "
            f"{len(block['unexplained'])} unexplained, "
            f"{block['forced_restatements']} forced restatement(s) "
            f"(criterion 4's open residue), "
            f"{block['coincidences']} coincidence(s)"
        )
        for row in block["unexplained"]:
            print(
                f"  {row['source']}: states {row['value']} = {', '.join(row['fields'])}"
            )
        for row in block["stale_allowances"]:
            print(f"  stale allowance: {row['source']} / {row['value']}")
    if args.check and (block["unexplained"] or block["stale_allowances"]):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
