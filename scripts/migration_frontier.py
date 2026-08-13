#!/usr/bin/env python3
"""The migration frontier — Phase 4's three counters, and what they stand on.

Phase 4 replaces two hand-built ``SurvivalAction`` ladders with one compiler,
moves rounding out of the kernel into a presentation registry, and re-keys
every cache on a value derived from what it serves.  Each of those is a
migration, and a migration without a number is an impression, so this is the
instrument: three counters over the tree, each with its counting rule stated
here so the figure is reproducible by anyone who reads it, and each with its
exclusions **committed beside it** in ``docs/migration-frontier.json`` rather
than living only in this file (D-40).  An exclusion list a tool keeps to
itself is a counter that can be driven to zero by editing the tool.

Counters 1-4 are Phase 3's and live in ``docs/behavior-frontier.json``;
nothing here reports them.

Counter definitions
-------------------

``Counter 5`` — ``SurvivalAction`` construction expressions outside
``program/compile.py``.
    The population is every ``ast.Call`` under ``src/calculator`` whose callee
    spells ``SurvivalAction``.  *Expressions*, not files and not text: a bare
    ``grep -c "SurvivalAction("`` returns 11 because it also matches the class
    statement and a docstring, which is exactly the miscount R-29 warns about.
    Baseline 9, target 1 — the declared survivor is the issue-#171 fast
    constructor in ``survival/actions.py``, named in ``exclusions`` with the
    reason it survives, because criteria 2 and 17 are mutually exclusive
    without it.

``Counter 6`` — ``round(`` outside the precision registry.
    Two populations, gated differently, because D-71 scopes them differently.
    Within ``program/`` the count must be **0** outside
    ``program/precision.py``: rounding is presentation and the registry owns
    it.  Within ``survival/`` the count is a **non-increasing ratchet** from
    118, driven down by moving receipt-field rounding into the end-of-walk
    projection; gating the kernel at zero instead would force
    ``survival/ -> program/`` and invert this phase's one-way dependency.

    **The two populations are counted by different rules, deliberately,
    because they are asked different questions.**

    The kernel side answers "has the declared 118 come down?", so it counts
    **textual occurrences of** ``round(`` **in the file's source text** —
    the rule that reproduces D-71's figure exactly (transitions 72,
    receipt_state 38, compile 6, accumulate 1, score_state 1).  One of those
    118 is prose: ``score_state.py``'s comment explaining why the score
    ledger pays for no rounding.  Counting calls instead would read 117
    against a plan that says 118, and counting text is also what stops a
    comment deletion from being sold as progress — so the receipt records
    the AST call count per file *beside* the textual one and the gate
    compares both, which makes either moving a diff somebody explains.

    The ``program/`` side answers a different question — "does anything in
    this package round?" — so it counts **``round`` call expressions**.  A
    module that *names* the function it is forbidden to call is
    documentation, and a gate at zero that a docstring can trip is a gate
    people route around by not writing the docstring.

``Counter 7`` — ``id()``-keyed caches whose key is not derived from the
served value.
    The scanned trees are ``src/calculator/survival``,
    ``src/calculator/program`` and ``src/calculator/stats.py``, and the
    population is every ``ast.Call`` to the builtin ``id`` in them.  A site
    leaves the count only by entering the committed
    ``value_derived_cache_keys`` exclusion set — ``id()`` survives as a fast
    path in front of a value key, never as the key itself.  The baseline is
    **measured on this script's first run rather than typed**, because the
    naive count depends on whether an object-identity guard beside the value
    counts as a value key, and a typed baseline would have settled that
    question in prose.  Today every site re-verifies identity and none stands
    behind a value key, so all of them count.

    ``champions/``'s two modules are out of scope and named in
    ``out_of_scope`` with their measured site counts, so "out of scope" is a
    row with a number rather than a silence.

Beside the counters the receipt carries ``preserved_defects``: behaviour this
phase deliberately does not correct, each row naming the defect, the stage
that declined it and where the ruling lives.  A named defect on nobody's
schedule is at least a counted one.

Usage::

    python scripts/migration_frontier.py            # the counters
    python scripts/migration_frontier.py --json     # the full receipt
    python scripts/migration_frontier.py --write    # refresh the receipt
    python scripts/migration_frontier.py --check    # the gate
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "calculator"
RECEIPT_PATH = ROOT / "docs" / "migration-frontier.json"
SCHEMA_VERSION = 1

# ── counter 5 ──────────────────────────────────────────────────────────────

# The one construction expression allowed to survive outside the compiler,
# and why.  Criterion 2 names it; criterion 17 depends on it existing.
COUNTER_5_HOME = "calculator/program/compile.py"
COUNTER_5_TARGET = 1
COUNTER_5_DECLARED_SURVIVOR: Mapping[str, str] = {
    "calculator/survival/actions.py": (
        "the issue-#171 fast compiled-damage constructor: the declared "
        "performance fallback criterion 17 keeps if S4 cannot hold the "
        "allocation ratchet, so criteria 2 and 17 are mutually exclusive "
        "without it"
    ),
}

# ── counter 6 ──────────────────────────────────────────────────────────────

COUNTER_6_REGISTRY = "calculator/program/precision.py"
COUNTER_6_KERNEL_BASELINE = 118

# ── counter 7 ──────────────────────────────────────────────────────────────

COUNTER_7_TREES = (
    "survival",
    "program",
    "stats.py",
)
COUNTER_7_TARGET = 0

# Sites whose ``id()`` is a fast path in front of a key derived from the
# served value.  Empty today: every live site re-verifies identity against a
# strong reference, which proves the entry is not stale but does not make the
# key a value.  A site enters here by name, in the commit that gives it a
# value key.
VALUE_DERIVED_CACHE_KEYS: Mapping[str, str] = {}

# ``champions/`` is a different contract — its memos key on cached-JSON
# object identity supplied by ``data_fetcher``, which this phase does not
# touch — so it is out of scope, with its measured size recorded rather than
# waved at.
COUNTER_7_OUT_OF_SCOPE: tuple[str, ...] = (
    "calculator/champions/engine.py",
    "calculator/champions/slotlib.py",
)

# ── preserved defects ──────────────────────────────────────────────────────

PRESERVED_DEFECTS: tuple[Mapping[str, Any], ...] = (
    {
        "name": "LATE_BARRIER",
        "what": (
            "two shields ride the rank that resolves after damage while the "
            "ladder gives shields BARRIER_GRANT, so an Eclipse or Fimbulwinter "
            "barrier placed at a damage timestamp absorbs nothing at that "
            "timestamp"
        ),
        "declined_by": "P4-S6",
        "why": (
            "Phase 0A preserved the ordering byte-identically under this name; "
            "correcting it moves numbers and S6's diff is bounded by prediction "
            "to the four reorderings criterion 8 names, which this is not"
        ),
        "ruling": "docs/plans/phase-4-program-engine.md — LATE_BARRIER bullet",
        "tracker_issue": None,
    },
)


# ── measurement ────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Site:
    """One counted occurrence: where it is and, when a rule needs it, what."""

    path: str
    lineno: int


@dataclass(slots=True)
class FrontierReport:
    """Everything the three counters measured on one tree."""

    counter_5_sites: tuple[Site, ...] = ()
    round_text: dict[str, int] = field(default_factory=dict)
    round_calls: dict[str, int] = field(default_factory=dict)
    program_round_calls: dict[str, int] = field(default_factory=dict)
    counter_7_sites: tuple[Site, ...] = ()
    counter_7_out_of_scope: dict[str, int] = field(default_factory=dict)

    @property
    def counter_5(self) -> int:
        """Construction expressions outside the one compiler."""
        return len(self.counter_5_sites)

    @property
    def counter_6_kernel(self) -> int:
        """Textual ``round(`` occurrences under ``survival/``."""
        return sum(self.round_text.values())

    @property
    def counter_6_program(self) -> int:
        """``round`` call expressions under ``program/``, registry aside."""
        return sum(self.program_round_calls.values())

    @property
    def counter_7(self) -> int:
        """``id()`` cache-key sites with no value key behind them."""
        return len(self.counter_7_sites)

    def counters(self) -> dict[str, int]:
        """The three headline numbers, for the bare invocation."""
        return {
            "counter_5": self.counter_5,
            "counter_6_kernel": self.counter_6_kernel,
            "counter_6_program": self.counter_6_program,
            "counter_7": self.counter_7,
        }


def _repo_path(path: Path) -> str:
    """One spelling for a scanned file: repo-relative, posix, ``src/`` off."""
    return path.relative_to(ROOT / "src").as_posix()


def _python_files(root: Path) -> list[Path]:
    """Every ``*.py`` under *root*, or *root* itself when it is a file."""
    return sorted(root.rglob("*.py")) if root.is_dir() else [root]


def _construction_sites(tree: ast.AST, path: str, callee: str) -> list[Site]:
    """Every call expression in *tree* whose callee spells *callee*."""
    return [
        Site(path=path, lineno=node.lineno)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == callee
    ]


def scan() -> FrontierReport:
    """Measure all three counters against the working tree."""
    report = FrontierReport()
    counter_5: list[Site] = []
    for path in _python_files(SRC):
        repo = _repo_path(path)
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        if repo != COUNTER_5_HOME:
            counter_5.extend(_construction_sites(tree, repo, "SurvivalAction"))
        if repo.startswith("calculator/survival/"):
            count = text.count("round(")
            if count:
                report.round_text[repo] = count
                report.round_calls[repo] = len(_construction_sites(tree, repo, "round"))
        elif repo.startswith("calculator/program/") and repo != COUNTER_6_REGISTRY:
            calls = len(_construction_sites(tree, repo, "round"))
            if calls:
                report.program_round_calls[repo] = calls
    report.counter_5_sites = tuple(counter_5)

    counter_7: list[Site] = []
    for tree_name in COUNTER_7_TREES:
        for path in _python_files(SRC / tree_name):
            repo = _repo_path(path)
            for site in _construction_sites(
                ast.parse(path.read_text(encoding="utf-8")), repo, "id"
            ):
                if repo not in VALUE_DERIVED_CACHE_KEYS:
                    counter_7.append(site)
    report.counter_7_sites = tuple(counter_7)
    for repo in COUNTER_7_OUT_OF_SCOPE:
        path = ROOT / "src" / repo
        report.counter_7_out_of_scope[repo] = len(
            _construction_sites(ast.parse(path.read_text(encoding="utf-8")), repo, "id")
        )
    return report


def _by_file(sites: Sequence[Site]) -> dict[str, int]:
    """Site counts per file — the shape the receipt diffs by set equality."""
    tally: dict[str, int] = {}
    for site in sites:
        tally[site.path] = tally.get(site.path, 0) + 1
    return dict(sorted(tally.items()))


def build_receipt(report: FrontierReport) -> dict[str, Any]:
    """The committed receipt: counters, exclusions and preserved defects."""
    return {
        "schema_version": SCHEMA_VERSION,
        "counters": {
            "counter_5": {
                "what": (
                    "SurvivalAction construction expressions outside "
                    f"{COUNTER_5_HOME}"
                ),
                "value": report.counter_5,
                "target": COUNTER_5_TARGET,
                "by_file": _by_file(report.counter_5_sites),
            },
            "counter_6": {
                "what": (
                    "round outside the precision registry: 0 call expressions "
                    "within program/, a non-increasing textual ratchet "
                    "within survival/"
                ),
                "kernel_value": report.counter_6_kernel,
                "kernel_baseline": COUNTER_6_KERNEL_BASELINE,
                "program_value": report.counter_6_program,
                "program_target": 0,
                "kernel_by_file": dict(sorted(report.round_text.items())),
                "kernel_ast_calls_by_file": dict(sorted(report.round_calls.items())),
                "program_by_file": dict(sorted(report.program_round_calls.items())),
            },
            "counter_7": {
                "what": (
                    "id()-keyed cache sites whose key is not derived from the "
                    f"served value, over {', '.join(COUNTER_7_TREES)}"
                ),
                "value": report.counter_7,
                "target": COUNTER_7_TARGET,
                "by_file": _by_file(report.counter_7_sites),
            },
        },
        "exclusions": {
            "counter_5_declared_survivor": dict(
                sorted(COUNTER_5_DECLARED_SURVIVOR.items())
            ),
            "counter_6_registry": COUNTER_6_REGISTRY,
            "counter_7_value_derived_cache_keys": dict(
                sorted(VALUE_DERIVED_CACHE_KEYS.items())
            ),
            "counter_7_out_of_scope": dict(
                sorted(report.counter_7_out_of_scope.items())
            ),
        },
        "preserved_defects": [dict(row) for row in PRESERVED_DEFECTS],
    }


def load_receipt() -> dict[str, Any]:
    """The committed receipt, or an empty mapping when it does not exist yet."""
    if not RECEIPT_PATH.exists():
        return {}
    return json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))


def _counter_failures(
    committed: Mapping[str, Any], fresh: Mapping[str, Any]
) -> list[str]:
    """Every measured value the committed receipt does not agree with."""
    failures: list[str] = []
    numeric_keys = (
        ("counter_5", "value"),
        ("counter_6", "kernel_value"),
        ("counter_6", "program_value"),
        ("counter_7", "value"),
    )
    for counter, key in numeric_keys:
        recorded = committed.get("counters", {}).get(counter, {}).get(key)
        measured = fresh["counters"][counter][key]
        if recorded != measured:
            failures.append(
                f"{counter}.{key}: receipt records {recorded}, "
                f"tree measures {measured}"
            )
    for counter, key in (
        ("counter_5", "by_file"),
        ("counter_6", "kernel_by_file"),
        ("counter_6", "kernel_ast_calls_by_file"),
        ("counter_6", "program_by_file"),
        ("counter_7", "by_file"),
    ):
        recorded_map = committed.get("counters", {}).get(counter, {}).get(key, {})
        measured_map = fresh["counters"][counter][key]
        if recorded_map != measured_map:
            failures.append(
                f"{counter}.{key}: committed per-file tally differs from the "
                f"measured one (committed={json.dumps(recorded_map, sort_keys=True)}, "
                f"measured={json.dumps(measured_map, sort_keys=True)})"
            )
    return failures


def _ratchet_failures(fresh: Mapping[str, Any]) -> list[str]:
    """The two bounds a measurement may not cross, whatever the receipt says."""
    failures: list[str] = []
    counter_6 = fresh["counters"]["counter_6"]
    if counter_6["kernel_value"] > counter_6["kernel_baseline"]:
        failures.append(
            f"counter_6.kernel_value {counter_6['kernel_value']} is above its "
            f"non-increasing baseline of {counter_6['kernel_baseline']}"
        )
    if counter_6["program_value"] != 0:
        failures.append(
            f"counter_6.program_value is {counter_6['program_value']}; rounding "
            f"outside {COUNTER_6_REGISTRY} is zero within program/ by rule"
        )
    return failures


def _exclusion_failures(
    committed: Mapping[str, Any], fresh: Mapping[str, Any]
) -> list[str]:
    """D-40: an exclusion set moves in a diff or it does not move."""
    failures: list[str] = []
    for key in (
        "counter_5_declared_survivor",
        "counter_7_value_derived_cache_keys",
        "counter_7_out_of_scope",
    ):
        recorded = set(committed.get("exclusions", {}).get(key, {}))
        measured = set(fresh["exclusions"][key])
        if recorded != measured:
            failures.append(
                f"exclusions.{key}: committed set differs from the declared one "
                f"(committed-only={sorted(recorded - measured)}, "
                f"declared-only={sorted(measured - recorded)})"
            )
    if (
        committed.get("exclusions", {}).get("counter_6_registry")
        != fresh["exclusions"]["counter_6_registry"]
    ):
        failures.append("exclusions.counter_6_registry: committed home differs")
    return failures


def _preserved_defect_failures(
    committed: Mapping[str, Any], fresh: Mapping[str, Any]
) -> list[str]:
    """A preserved defect leaves the receipt in a commit, never in silence."""
    recorded = {row.get("name") for row in committed.get("preserved_defects", [])}
    declared = {row["name"] for row in fresh["preserved_defects"]}
    if recorded != declared:
        return [
            "preserved_defects: committed rows differ from the declared ones "
            f"(committed-only={sorted(recorded - declared)}, "
            f"declared-only={sorted(declared - recorded)})"
        ]
    return []


def check(
    report: FrontierReport, committed: Mapping[str, Any] | None = None
) -> tuple[str, ...]:
    """Differences between the committed receipt and this tree — the gate.

    ``committed`` is the seam the gate's own negative test drives (R-05); it
    defaults to the receipt on disk, which is what ``--check`` gates against.
    """
    committed = load_receipt() if committed is None else committed
    if not committed:
        return (f"{RECEIPT_PATH.name} is missing; run --write",)
    fresh = build_receipt(report)
    return tuple(
        _counter_failures(committed, fresh)
        + _ratchet_failures(fresh)
        + _exclusion_failures(committed, fresh)
        + _preserved_defect_failures(committed, fresh)
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the scan, and write or gate the receipt."""
    parser = argparse.ArgumentParser(description="Phase 4 migration frontier")
    parser.add_argument("--json", action="store_true", help="print the receipt")
    parser.add_argument("--write", action="store_true", help="refresh the receipt")
    parser.add_argument("--check", action="store_true", help="gate against the receipt")
    args = parser.parse_args(argv)
    report = scan()
    receipt = build_receipt(report)
    if args.write:
        RECEIPT_PATH.write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    if args.json:
        print(json.dumps(receipt, indent=2, sort_keys=True))
    if args.check:
        failures = check(report)
        for failure in failures:
            print(f"migration frontier: {failure}", file=sys.stderr)
        if failures:
            return 1
        print(f"migration frontier: {json.dumps(report.counters())}")
        return 0
    if not args.json and not args.write:
        print(json.dumps(report.counters()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
