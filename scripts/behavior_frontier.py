#!/usr/bin/env python3
"""The behaviour frontier — four counters, and the exclusions they stand on.

Phase 3 replaces item behaviour scattered across engines, and coverage prose
describing that code, with one closed union of declarations.  A migration
that size needs a number rather than an impression, so this is the
instrument: four counters over the tree, each with a definition stated here
so the figure is reproducible by anyone who reads it, and each with its
exclusions **committed beside it** in ``docs/behavior-frontier.json`` rather
than living only in this file (D-40).  An exclusion list a tool keeps to
itself is a counter that can be driven to zero by editing the tool.

Counter definitions
-------------------

The population for counters 1 and 2 is *every string literal in
``src/**/*.py``, found by glob and parsed with ``ast``, whose value is the
``name`` of an item in the cached item data*.  Occurrences, not distinct
names: one literal used twice is two sites.  Every site is classified by the
module it appears in, into exactly one of four classes:

``Class D`` — non-behavioural
    Committed module set, excluded from both counters.  Its members are
    overwhelmingly *collisions*: an ability display name, a stat-category
    label and a shield-source label that happen to spell an item's name, plus
    one certification matrix's sample builds.

``Class C`` — declarative homes
    Committed module set, excluded from both counters.  These are the places
    an item name is legitimately a key: the number registries themselves, the
    wiki parser's per-item configuration, the availability and legality
    tables, and Phase 2's capability registry.  A declaration keyed by an
    item name is the *destination* of this migration, not its subject.

``Class B`` — claim prose
    Committed module set; its sites are **counter 2**.  These are the hand
    registries that assert coverage rather than compute it.

default
    Everything else is **counter 1** — runtime item-name dispatch.  The
    default is deliberately the strictest class: a new module counts against
    counter 1 until somebody argues it into an exclusion set *in the
    committed receipt*, which is what makes "add a name-dispatch site in a
    new module and the counter rises" true rather than aspirational.

``Counter 3`` is undeclared registry **entries** — an ``ITEM_EFFECTS`` or
``ALLY_ITEM_EFFECTS`` entry that compiles to no ``BehaviorRule``.  Entries,
not owners: six owners hold one of each and each entry is its own obligation.

``Counter 4`` is declared ``(family, lane)`` pairs with no registered
interpreter, read from ``interpreters``' own declared lane table.  A pair is
"declared" by that table, not by what happens to be registered — otherwise an
empty registry would report full coverage.

Counters 5-7 are Phase 4's and live in ``docs/migration-frontier.json``;
nothing here reports them.

Usage::

    python scripts/behavior_frontier.py            # human summary
    python scripts/behavior_frontier.py --json     # the full receipt
    python scripts/behavior_frontier.py --write    # refresh the receipt
    python scripts/behavior_frontier.py --check    # the gate
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
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# pylint: disable=wrong-import-position
from src.calculator import interpreters  # noqa: E402
from src.calculator import item_behavior_catalog as catalog  # noqa: E402
from src.calculator import item_coverage  # noqa: E402
from src.calculator.data_fetcher import fetch_item_data  # noqa: E402

RECEIPT_PATH = ROOT / "docs" / "behavior-frontier.json"
SRC_ROOT = ROOT / "src"
SCHEMA_VERSION = 1

# ── the committed exclusion sets ─────────────────────────────────────────
#
# Declared here and written into the receipt by --write; the receipt is what
# is diff-gated, and tests/test_behavior_frontier.py asserts the two agree by
# set equality, so a quiet edit here shows up as a diff in a committed
# artifact (D-40).

CLASS_D_NON_BEHAVIOURAL: Mapping[str, str] = {
    "app.py": (
        'one `kind="Boots"` stat-category label that collides with the item '
        "literally named Boots — a name match, not a dispatch"
    ),
    "calculator/scenario.py": (
        'the same `kind="Boots"` stat-category label on the request-parsing ' "side"
    ),
    "calculator/champions/janna.py": (
        "an ability display-name default (`Zephyr` is Janna's W) that collides "
        "with an item name"
    ),
    "calculator/champions/viego.py": (
        "an ability display-name default (Viego's R is named after the item he "
        "steals) that collides with an item name"
    ),
    "calculator/shield_ledger.py": (
        "the shield-source label `Lifeline`, which names a mechanic class and "
        "collides with an item name"
    ),
    "calculator/rotation_resolver.py": (
        "three sample builds in the rotation certification matrix; they name "
        "builds to certify orders over and dispatch no behaviour"
    ),
}

CLASS_C_DECLARATIVE_HOMES: Mapping[str, str] = {
    "calculator/item_effects.py": (
        "the number registries themselves — ITEM_EFFECTS, ALLY_ITEM_EFFECTS and "
        "the static effect tables. An item name is the key of the home this "
        "phase reads through"
    ),
    "calculator/passive_parser.py": (
        "the wiki-text parser's per-item parse configuration; the names decide "
        "how a page is read, not how a fight is priced"
    ),
    "calculator/loadout_rules.py": (
        "build legality — uniques, boots and slot rules keyed by the item they "
        "constrain"
    ),
    "calculator/item_source.py": (
        "availability from the cached source data; the name is the identity of "
        "the row being decided, per CLAUDE.md rule 6"
    ),
    "calculator/role_quests.py": (
        "quest-item declarations keyed by the item that carries the quest"
    ),
    "calculator/trigger_stream.py": (
        'Phase 2\'s capability registry: `ItemOwner("…")` declares who owns a '
        "mechanic, which is the same kind of home as the number registry. "
        "**Not in the prior**: the module did not exist when the prior counts "
        "were taken, and its 38 sites are the whole Class C divergence"
    ),
}

CLASS_B_CLAIM_PROSE: Mapping[str, str] = {
    "calculator/item_coverage.py": (
        "the hand registries that assert coverage rather than compute it; 3.8 "
        "replaces them with a status derived from declarations"
    ),
    "calculator/bis.py": (
        "three name-keyed build-profile claims that ride the same flip"
    ),
}

# The prior counts this instrument replaces, carried beside the measurement
# with the cause of each divergence.  A prior is never a gate (runbook R-07);
# it is here so a reader can see what moved and why.
PRIORS: Mapping[str, Mapping[str, Any]] = {
    "counter_1": {
        "value": 282,
        "cause": (
            "measured over a tree without Phase 1's evidence corpus and "
            "without Phase 2's trigger_stream; item_support_effects also lost "
            "sites to 0B's corrections"
        ),
    },
    "counter_2": {
        "value": 191,
        "cause": (
            "item_coverage grew Phase 1's claim corpus (_SOURCE_REFS, "
            "_RULE_CLAIMS and the evidence tables), which is claim prose by "
            "this counter's definition and 3.8 retires with the rest"
        ),
    },
    "counter_3": {"value": 142, "cause": "unchanged"},
    "counter_4": {
        "value": None,
        "cause": "no producing tool before this script; the plan records n/a",
    },
    "class_c": {
        "value": 600,
        "cause": "trigger_stream.py did not exist when the prior was taken",
    },
    "class_d": {"value": 14, "cause": "unchanged"},
}


@dataclass(frozen=True, slots=True)
class Site:
    """One item-name literal in the tree, with the class it fell into."""

    module: str
    line: int
    name: str
    klass: str


@dataclass(slots=True)
class FrontierReport:
    """The four counters, their per-module tallies and their exclusions."""

    counter_1: int = 0
    counter_2: int = 0
    counter_3: int = 0
    counter_4: int = 0
    by_module: dict[str, dict[str, int]] = field(default_factory=dict)
    class_c_sites: int = 0
    class_d_sites: int = 0
    uninterpreted: tuple[str, ...] = ()

    def counters(self) -> dict[str, int]:
        """The four numbers, keyed the way the receipt keys them."""
        return {
            "counter_1": self.counter_1,
            "counter_2": self.counter_2,
            "counter_3": self.counter_3,
            "counter_4": self.counter_4,
        }


def item_names() -> frozenset[str]:
    """Every cached item name — read through the caching layer, never a list."""
    return frozenset(
        str(entry["name"])
        for entry in fetch_item_data().values()
        if isinstance(entry, Mapping) and entry.get("name")
    )


def classify(module: str) -> str:
    """Which class a module's item-name sites belong to.

    The default is ``counter_1``: strictest wins, so a module nobody has
    argued about counts against the migration rather than silently out of it.
    """
    if module in CLASS_D_NON_BEHAVIOURAL:
        return "class_d"
    if module in CLASS_C_DECLARATIVE_HOMES:
        return "class_c"
    if module in CLASS_B_CLAIM_PROSE:
        return "counter_2"
    return "counter_1"


def name_sites(root: Path, names: frozenset[str]) -> tuple[Site, ...]:
    """Every item-name string literal under *root*, classified by module."""
    sites: list[Site] = []
    for path in sorted(root.rglob("*.py")):
        module = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant):
                continue
            if not isinstance(node.value, str) or node.value not in names:
                continue
            sites.append(
                Site(
                    module=module,
                    line=node.lineno,
                    name=node.value,
                    klass=classify(module),
                )
            )
    return tuple(sites)


def scan(root: Path = SRC_ROOT) -> FrontierReport:
    """Measure all four counters on the tree rooted at *root*."""
    report = FrontierReport()
    for site in name_sites(root, item_names()):
        tally = report.by_module.setdefault(site.module, {})
        tally[site.klass] = tally.get(site.klass, 0) + 1
        if site.klass == "counter_1":
            report.counter_1 += 1
        elif site.klass == "counter_2":
            report.counter_2 += 1
        elif site.klass == "class_c":
            report.class_c_sites += 1
        else:
            report.class_d_sites += 1
    report.counter_3 = catalog.undeclared_entry_count()
    pairs = interpreters.uninterpreted_pairs()
    report.counter_4 = len(pairs)
    report.uninterpreted = tuple(
        f"{family.value}/{lane.value}" for family, lane in pairs
    )
    return report


def no_runtime_behavior_block() -> dict[str, Any]:
    """The reviewed-nothing ratchet: its members, and the ceiling they ride.

    Empty at 3.1 — nothing has been reviewed yet — and bounded by the size of
    the reviewed stats-only claim it replaces, measured on this commit.  The
    bound is what stops counter 3 being driven to zero by reviewing the
    backlog into silence: counter 3's target is
    ``declared >= entries - |NO_RUNTIME_BEHAVIOR|``.
    """
    return {
        "members": [],
        "ratchet_ceiling": len(item_coverage._REVIEWED_STATS_ONLY),  # noqa: SLF001
        "ceiling_source": (
            "len(item_coverage._REVIEWED_STATS_ONLY) on this commit — the "
            "reviewed no-modelled-effect claim this set replaces"
        ),
        "rule": (
            "|members| may never exceed the ceiling and may never grow once a "
            "slice has set it; every member carries a SourceReceipt and a "
            "reviewed reason"
        ),
    }


def build_receipt(report: FrontierReport) -> dict[str, Any]:
    """The committed frontier artifact."""
    return {
        "schema_version": SCHEMA_VERSION,
        "slice": "3.2",
        "counters": {
            "counter_1": {
                "counts": "runtime item-name dispatch sites",
                "value": report.counter_1,
                "provenance": "VERIFIED",
                "target": 0,
                "retires_at": "3.4-3.7",
            },
            "counter_2": {
                "counts": "claim-prose sites in name-keyed containers",
                "value": report.counter_2,
                "provenance": "VERIFIED",
                "target": "<= the reviewed NO_RUNTIME_BEHAVIOR reason count",
                "retires_at": "3.8",
            },
            "counter_3": {
                "counts": "undeclared ITEM_EFFECTS + ALLY_ITEM_EFFECTS entries",
                "value": report.counter_3,
                "provenance": "VERIFIED",
                "target": 0,
                "retires_at": "3.2-3.7",
            },
            "counter_4": {
                "counts": "declared (family, lane) pairs with no interpreter",
                "value": report.counter_4,
                "provenance": "VERIFIED",
                "target": "0 for PAIR_ENGINE and RECEIPT_WALK",
                "retires_at": "3.9",
                "pairs": list(report.uninterpreted),
            },
        },
        "exclusions": {
            "class_c_declarative_homes": {
                "sites": report.class_c_sites,
                "modules": dict(sorted(CLASS_C_DECLARATIVE_HOMES.items())),
            },
            "class_d_non_behavioural": {
                "sites": report.class_d_sites,
                "modules": dict(sorted(CLASS_D_NON_BEHAVIOURAL.items())),
            },
            "class_b_claim_prose": {
                "sites": report.counter_2,
                "modules": dict(sorted(CLASS_B_CLAIM_PROSE.items())),
            },
        },
        "by_module": {
            module: dict(sorted(tally.items()))
            for module, tally in sorted(report.by_module.items())
        },
        "no_runtime_behavior": no_runtime_behavior_block(),
        "h4_tags": {
            "dead": sorted(catalog.H4_DEAD_TAGS),
            "self_referential": sorted(catalog.H4_SELF_REFERENTIAL_TAGS),
            "families": {
                tag: catalog.TAG_FAMILY[tag].value
                for tag in sorted(
                    catalog.H4_DEAD_TAGS | catalog.H4_SELF_REFERENTIAL_TAGS
                )
            },
            "reasons": dict(sorted(catalog.H4_TAG_REASONS.items())),
        },
        "priors": dict(sorted(PRIORS.items())),
    }


def load_receipt() -> dict[str, Any]:
    """The committed receipt, or an empty mapping when it does not exist yet."""
    if not RECEIPT_PATH.exists():
        return {}
    return json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))


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
    failures: list[str] = []
    fresh = build_receipt(report)
    for key, value in fresh["counters"].items():
        recorded = committed.get("counters", {}).get(key, {}).get("value")
        if recorded != value["value"]:
            failures.append(
                f"{key}: receipt records {recorded}, tree measures {value['value']}"
            )
    for key in ("class_c_declarative_homes", "class_d_non_behavioural"):
        recorded_modules = set(
            committed.get("exclusions", {}).get(key, {}).get("modules", {})
        )
        fresh_modules = set(fresh["exclusions"][key]["modules"])
        if recorded_modules != fresh_modules:
            failures.append(
                f"{key}: committed exclusion set differs from the declared one "
                f"(committed-only={sorted(recorded_modules - fresh_modules)}, "
                f"declared-only={sorted(fresh_modules - recorded_modules)})"
            )
    ratchet = committed.get("no_runtime_behavior", {})
    members = ratchet.get("members", [])
    ceiling = ratchet.get("ratchet_ceiling")
    if isinstance(ceiling, int) and len(members) > ceiling:
        failures.append(
            f"NO_RUNTIME_BEHAVIOR holds {len(members)} members, above its "
            f"ratchet ceiling of {ceiling}"
        )
    return tuple(failures)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the scan, and write or gate the receipt."""
    parser = argparse.ArgumentParser(description="Phase 3 behaviour frontier")
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
            print(f"behavior frontier: {failure}", file=sys.stderr)
        if failures:
            return 1
        print(f"behavior frontier: {json.dumps(report.counters())}")
        return 0
    if not args.json and not args.write:
        print(json.dumps(report.counters()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
