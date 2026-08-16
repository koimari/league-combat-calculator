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

    Class C has a second, narrower arm the umbrella's **Amendment A**
    (2026-08-12) added: a committed set of **containers** inside a Class B
    module — Phase 1's authored claim-evidence corpus and
    ``_REVIEW_ISSUE_REFS``.  They are typed declarations the resolution tier
    resolves against the codebase on every ``pytest`` run, which is the
    cannot-drift-silently property counter 2 exists to enforce, so they are
    not the prose it is named for.  The arm is keyed by container rather than
    by module because the module holds both populations, and it is consulted
    only inside Class B, because a per-symbol exclusion reaching counter 1
    would be an escape hatch on the counter this receipt drives to zero.

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
empty registry would report full coverage.  Its *content* is carried beside
the number: every gap a declaration reaches is either a dated row in
``interpreters.UNSERVED_LANE_RECEIPTS`` — the route the number arrives by
instead, plus the stage that retires the row — or a compiled lane refused by
that rule's own ``ReceiptOnly``.  The receipt records both, so a reader meets
the reason where they meet the count and the gate diffs it by set equality;
the import-time gate in ``interpreters`` is what makes an *unreceipted* gap
impossible in the first place.

Counter 4 additionally carries **deferral rows** (umbrella criterion 7,
Amendment B): gaps Phase 3 cannot close because only Phase 4's S3 can, each
row naming the gap, its reason and that stage.  The lane targets are measured
net of them, which is the difference between a phase that says what it did
not do and one whose exit criterion is quietly false.

Counters 5-7 are Phase 4's and live in ``docs/migration-frontier.json``;
nothing here reports them.

Beside the counters the receipt carries the **targets** block: for each
counter the bound its exit criterion resolves to, the measured value, and the
gap.  ``--check`` compares the tree against the receipt *and* each counter
against its own target, ratcheting every gap so a counter cannot drift away
from a target it has not reached — the check the earlier gate had no clause
for, which let two exit criteria stand undischarged behind a green run.  It
records targets and never amends one.

Usage::

    python scripts/behavior_frontier.py            # human summary
    python scripts/behavior_frontier.py --json     # the full receipt
    python scripts/behavior_frontier.py --write    # refresh the receipt
    python scripts/behavior_frontier.py --check    # the gate
"""

from __future__ import annotations

import argparse
import ast
import functools
import json
import re
import subprocess
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
from src.calculator.item_behavior import ReceiptOnly, ReceiptScope  # noqa: E402

# The one refusal the hand set answers, so the one the derivation reads.
LEDGER_SCOPE = ReceiptScope.SURVIVAL_LEDGER_TRANSITION

RECEIPT_PATH = ROOT / "docs" / "behavior-frontier.json"
SRC_ROOT = ROOT / "src"
SCHEMA_VERSION = 2

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
    "calculator/item_outcomes.py": (
        "the reviewed outcome-dimension declaration and nothing else — one "
        "mapping, no function, no branch, asserted by "
        "tests/test_item_outcomes.py.  Twenty of its items compile to no rule "
        "at all, so what an item changes about a fight besides the damage "
        "number is a product fact whose key is the item it is about"
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
        "the reviewed no-runtime-behaviour set NO_RUNTIME_BEHAVIOR, the one "
        "name-keyed container 3.8's collapse left standing here: 'we looked "
        "and there is nothing' is a fact no declaration can carry, so it is "
        "reviewed prose by construction and criterion 2 keeps it as a "
        "non-increasing ratchet rather than retiring it.  Its members are "
        "counter 2's whole population *and* the count counter 2 is bounded "
        "by, which is what makes 'at or below the reviewed reason count' the "
        "end state rather than zero"
    ),
}
# The class was argued for a module that asserted coverage in hand registries
# instead of computing it, and that argument retired with 3.8: the classifier
# now reads declarations and the eight derived registries are gone.  What is
# written above is the argument that replaced it, not a refreshed spelling of
# the old one — a class description outliving its own module is the
# prose-outruns-code shape this counter exists to measure, and it may not
# survive inside the instrument measuring it.  Excluding the survivor instead
# would read as tidier and would be worse: counter 2 would measure nothing and
# its bound would bound nothing.
# ``calculator/bis.py`` was the second member until its three certification
# claims became `interpreters.survival_ledger_certifications`.  It leaves the
# set rather than staying as a zero-site entry, because Class B is an argument
# about a module and the argument no longer holds: the module now falls into
# the default class, so a name site added there tomorrow counts against
# counter 1 — the strictest class — instead of the class this receipt is
# allowed to carry sites in.

# The second arm of Class C, added by the umbrella's dated **Amendment A**
# (2026-08-12, criterion 7).  Class C above is a module set, and that
# granularity could not express the measured contradiction: a Class B module
# holds both the claim prose this counter is named for *and* Phase 1's
# authored claim-evidence corpus, which is neither prose nor retirable.
# Deriving the corpus from the registries it describes would make Phase 1's
# resolution check agree with them by construction — the failure that module
# exists to catch — and Phase 1 mandates the corpus, so it can only be
# excluded.  ``_REVIEW_ISSUE_REFS`` joins it as the second blessed survivor of
# Phase 3's criterion 14: an issue reference is not a coverage claim.
#
# Keyed by module and then by the **top-level binding** the site sits inside,
# so the exclusion is as narrow as the argument for it.  Only Class B modules
# may appear — a container key elsewhere would quietly excuse counter 1, which
# is the escape hatch this whole receipt exists to close.
CLASS_C_CLAIM_EVIDENCE_CONTAINERS: Mapping[str, Mapping[str, str]] = {
    "calculator/item_coverage.py": {
        "_SOURCE_REFS": (
            "the wiki revision each claim's evidence was read from; a claim "
            "with no source is the sentence this phase deletes, so the table "
            "is mandated rather than retirable"
        ),
        "_ATTACKER_STATE_HOMES": (
            "the attacker lane's authored claims: where a modelled state "
            "actually comes from, resolved against the symbol it names"
        ),
        "_ISSUE_REF_ONLY_ITEMS": (
            "the two items whose only claim carrier is their tracked review, "
            "authored so the ref rides a claim instead of being published by "
            "nothing"
        ),
        "_TARGET_MODELED_IMPLS": (
            "the target lane's authored claims, each naming the implementation "
            "the resolver resolves it against"
        ),
        "_TARGET_CERTIFIED_IMPLS": (
            "the target lane's certified half, same shape and same resolution"
        ),
        "_SUPPORT_PACKET_CLAIMS": (
            "the support-packet lane's authored claims, each quoting the packet "
            "source the totality check reads back"
        ),
        "_UTILITY_HOMES": (
            "the utility lane's authored evidence: the module and symbol a "
            "utility outcome is delivered by"
        ),
        "_DUAL_SIDED_MECHANICS": (
            "the evidence member naming the mechanic a dual-sided claim's two "
            "halves belong to, and the handshake policy its packet declares, "
            "both resolved against the pairing registry"
        ),
        "_RULE_CLAIMS": (
            "one claim per precedence rung, for the five rungs whose membership "
            "is recomputed from data/ and therefore cannot carry a per-item "
            "claim"
        ),
        "_REVIEW_ISSUE_REFS": (
            "criterion 14's own blessed survivor: tracked review issues per "
            "item, routed onto a claim at import.  An issue reference states no "
            "coverage, so it is not the prose counter 2 is named for"
        ),
    },
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
            "_RULE_CLAIMS and the evidence tables), which the prior counted as "
            "claim prose; the umbrella's Amendment A (2026-08-12) rules that "
            "corpus and _REVIEW_ISSUE_REFS into Class C, so the measurement is "
            "net of them and is not comparable to the prior term for term"
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
    container: str = ""


@dataclass(slots=True)
class FrontierReport:
    """The four counters, their per-module tallies and their exclusions."""

    counter_1: int = 0
    counter_2: int = 0
    counter_3: int = 0
    counter_4: int = 0
    by_module: dict[str, dict[str, int]] = field(default_factory=dict)
    class_c_sites: int = 0
    class_c_claim_evidence_sites: int = 0
    class_d_sites: int = 0
    uninterpreted: tuple[str, ...] = ()
    claim_evidence_by_container: dict[str, dict[str, int]] = field(default_factory=dict)

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


def classify(module: str, container: str = "") -> str:
    """Which class an item-name site belongs to, by module and container.

    The default is ``counter_1``: strictest wins, so a module nobody has
    argued about counts against the migration rather than silently out of it.

    *container* is the top-level binding the site sits inside, and it is
    consulted **only** inside a Class B module (Amendment A).  A container
    exclusion that could reach counter 1 would be a per-symbol escape hatch on
    the counter this receipt exists to drive to zero.
    """
    if module in CLASS_D_NON_BEHAVIOURAL:
        return "class_d"
    if module in CLASS_C_DECLARATIVE_HOMES:
        return "class_c"
    if module in CLASS_B_CLAIM_PROSE:
        if container in CLASS_C_CLAIM_EVIDENCE_CONTAINERS.get(module, {}):
            return "class_c_claim_evidence"
        return "counter_2"
    return "counter_1"


def top_level_bindings(tree: ast.Module) -> dict[int, str]:
    """Node id to the top-level binding whose value the node sits inside.

    Only module-level assignments, because that is the granularity a
    container exclusion is argued at: ``_SOURCE_REFS`` is a declaration a
    reader can go and look at, while "the third dict in this function" is not.
    """
    owners: dict[int, str] = {}
    for statement in tree.body:
        if isinstance(statement, ast.Assign):
            targets = [
                target.id
                for target in statement.targets
                if isinstance(target, ast.Name)
            ]
        elif isinstance(statement, ast.AnnAssign) and isinstance(
            statement.target, ast.Name
        ):
            targets = [statement.target.id]
        else:
            continue
        if not targets:
            continue
        for node in ast.walk(statement):
            owners[id(node)] = targets[0]
    return owners


def name_sites(root: Path, names: frozenset[str]) -> tuple[Site, ...]:
    """Every item-name string literal under *root*, classified in place."""
    sites: list[Site] = []
    for path in sorted(root.rglob("*.py")):
        module = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        owners = top_level_bindings(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant):
                continue
            if not isinstance(node.value, str) or node.value not in names:
                continue
            container = owners.get(id(node), "")
            sites.append(
                Site(
                    module=module,
                    line=node.lineno,
                    name=node.value,
                    klass=classify(module, container),
                    container=container,
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
        elif site.klass == "class_c_claim_evidence":
            report.class_c_claim_evidence_sites += 1
            per_module = report.claim_evidence_by_container.setdefault(site.module, {})
            per_module[site.container] = per_module.get(site.container, 0) + 1
        else:
            report.class_d_sites += 1
    report.counter_3 = catalog.undeclared_entry_count()
    pairs = interpreters.uninterpreted_pairs()
    report.counter_4 = len(pairs)
    report.uninterpreted = tuple(
        f"{family.value}/{lane.value}" for family, lane in pairs
    )
    return report


def unserved_lane_block() -> dict[str, Any]:
    """Counter 4's content: why each declared lane has no interpreter.

    Two populations, because they are excused by two different things and
    collapsing them would hide which.  ``dated`` are the rows
    ``interpreters.UNSERVED_LANE_RECEIPTS`` carries — a reason and a ``via``
    route each, the second being the lanes whose registered interpreters
    produce the number instead, checked against the registry at import and
    diff-gated here — joined to the retiring stage its lane's debt is owed to,
    which the engine does not declare and this reads from the one record that
    claims it.  ``per_rule_receipted`` are the compiled-lane gaps no row
    names because every declaration reaching them carries its own
    ``ReceiptOnly``, which is the stronger form: ``delta_amp`` is that whole
    population today (D-101).

    A gap in neither cannot exist — ``validate_registrations`` refuses to
    import a tree holding one — so an empty ``unreceipted`` here is a
    consequence of the import gate rather than a claim this script makes.
    """
    dated = {
        f"{family.value}/{lane.value}": {
            "reason": row.reason,
            "retires_at": creditor_stage(f"counter_4/{lane.value}"),
            "via": [route.value for route in row.via],
        }
        for (family, lane), row in interpreters.UNSERVED_LANE_RECEIPTS.items()
    }
    per_rule: set[str] = set()
    unreceipted: set[str] = set()
    for owner in sorted(catalog.rule_owners()):
        for rule in catalog.behavior_rules(owner):
            for lane in interpreters.lanes_for(rule.family):
                pair = (rule.family, lane)
                key = f"{rule.family.value}/{lane.value}"
                if pair in interpreters.INTERPRETERS or key in dated:
                    continue
                if lane.value == "compiled_score_walk" and isinstance(
                    rule.compilability, ReceiptOnly
                ):
                    per_rule.add(key)
                else:  # pragma: no cover - the import gate forbids this state
                    unreceipted.add(key)
    return {
        "dated": dict(sorted(dated.items())),
        "per_rule_receipted": sorted(per_rule),
        "unreceipted": sorted(unreceipted),
        "gate": (
            "interpreters.validate_registrations refuses an unserved lane that "
            "is in neither population, and refuses a dated row no declaration "
            "reaches (D-92)"
        ),
    }


def compiled_walk_refusals() -> dict[str, Any]:
    """Which owners the compiled score walk refuses, and which family says so.

    The successor to this block's own earlier shape.  Until 3.9 it carried a
    derivation *beside* the hand set ``COMPILED_WALK_UNREPRESENTABLE_ITEMS``
    with the difference committed, because the two disagreed and pretending
    otherwise would have been the prose-outruns-code failure inside the
    instrument that measures it.  They stopped disagreeing, the flip deleted
    the hand set, and what is left to record is the answer itself.

    Read **in one scope** — ``ReceiptScope.SURVIVAL_LEDGER_TRANSITION`` —
    because that is the question the build-level gate asks: whether the score
    ledger can stage the state transitions a build's items author, never
    whether a support template is instantaneous or an amp representable.
    Folding all three refusals into one verdict was what made this set
    twenty-eight items long while the hand set held sixteen; the two were
    never measuring the same thing.

    Gated by set equality against the committed receipt rather than by a
    count, so a declaration that changes which builds fall back shows up as a
    diff in a committed artifact (D-40).
    """
    refusals: dict[str, list[str]] = {}
    for owner in sorted(item_names()):
        verdict = interpreters.compilability_for(owner, LEDGER_SCOPE)
        if not isinstance(verdict, ReceiptOnly):
            continue
        # The families that made the fold refuse.  An owner with a registry
        # entry and no rule at all refuses for a different reason and gets the
        # empty list, which is the honest rendering of "nothing models it yet".
        refusals[owner] = sorted(
            {
                rule.family.value
                for rule in catalog.behavior_rules(owner)
                if isinstance(rule.compilability, ReceiptOnly)
                and rule.compilability.scope is LEDGER_SCOPE
            }
        )
    return {
        "symbol": "interpreters.compilability_for",
        "scope": LEDGER_SCOPE.value,
        "consumed_by": "interpreters.uncompilable_item_receipt",
        "refused": dict(sorted(refusals.items())),
        "undeclared_base": _undeclared_base_blocker(),
    }


def _undeclared_base_blocker() -> tuple[str, ...]:
    """Counter 3's blocker, naming the owners that hold it above zero.

    Empty when counter 3 is 0, so the clause disappears with the condition
    rather than having to be remembered — and while it stands it names the
    owners from :func:`catalog.undeclared_owners` instead of a family
    somebody typed, which is how the retired version came to describe a
    migration that had already happened.
    """
    undeclared = sorted(catalog.undeclared_owners())
    if not undeclared:
        return ()
    return (
        f"counter_3 is not yet 0: {', '.join(undeclared)} carry a registry "
        "entry no family declares, so the declaration base this fold reads is "
        "knowingly incomplete.",
    )


# ── the exit targets, and how far each counter still is from its own ─────
#
# ``--check`` compared the receipt against the tree and never a counter
# against its **target**, so a phase exit criterion could stand undischarged
# behind a green gate — a gate blind to the thing it is named for, which is
# this campaign's own failure shape wearing the campaign's badge.
#
# What follows is a **ratchet on the gap, never a ruling about the target**.
# It moves no target, relaxes none and dates none.  Per target it records the
# bound the target resolves to (derived, never typed), the measured value,
# whether the tree meets it, and who the *tree* says owes the remainder — an
# empty owner where nothing in the tree names one, because "nobody here says
# who finishes this" is a fact worth committing rather than a blank to fill
# in with a guess.  The gate then refuses a gap that grew, a verdict that
# disagrees with the tree, and a target the receipt has lost.

# Counter 4's target is per lane, so the two lanes it names are two targets.
COUNTER_4_TARGET_LANES: tuple[str, ...] = ("pair_engine", "receipt_walk")

# ── counter 4's deferrals (umbrella criterion 7, Amendment B, 2026-08-12) ──
#
# Eight now, and the rows that left are why the count is written as a derived
# length rather than restated in prose anywhere below.  ``delta_amp`` retired
# on 2026-08-15: umbrella Amendment M, Ruling 1 orders it first of the
# fourteen and rules its retiring act to be the walk-side delivery of the
# holder's static, pair-local amplifiers, and
# ``interpreters.delta_amp.WALK_INTERPRETER`` performs it.  ``active_cast``
# retired on 2026-08-16, in Amendment L, Ruling 1's whole shape: its six
# mechanics declare both halves, ``damage._add_item_active_damage`` stamps the
# row it authors as a preview and hands the walk the declaration under it, and
# ``interpreters.active_cast.WALK_INTERPRETER`` is the one interpreter that
# prices it.  ``cast_proc`` retired the same day and in the same shape, over
# its two authoring sites and its eight mechanics, and ``charged_strike`` the
# same day again, over five authoring sites and the eleven of its thirteen
# mechanics that author a damage row — the other two declare a swing schedule,
# which authors no packet for a walk to price and says so with an ``APPLIED``
# pair half of its own.  ``damage_routing`` retired on 2026-08-16 as well, and
# it is the first of the five whose interpreter hands the walk no *price* at
# all: umbrella Amendment P names its walk-side delivery as the program rider
# system and the kernel state paths already in the tree, so
# ``interpreters.damage_routing.WALK_INTERPRETER`` compiles a ``Defer`` rider,
# an ``Execute`` rider and the shield ledger's barrier-state adjustment, and
# the walk stages those instead of the ratio the pair engine used to stamp on
# its own events and the venom it used to read from the name-keyed effects
# registry.  ``on_hit_strike`` retired on 2026-08-16 as well, over one
# authoring site and its eight mechanics: ``damage._layer_on_hit_effects``
# lays every declared strike onto the fight's swing applications and now
# stamps each row it authors as a preview and hands the walk a declaration per
# application, which Blade of the Ruined King needs one of because its
# magnitude is re-read against the target's falling health and no two of its
# applications share a number.  In each case the receipt
# walk reads that family's declaration
# through its own lane, ``INTERPRETERS`` holds the ruled key, and a row
# deferring a gap the tree no longer holds would fail the gate below rather
# than pass it.  The debt is smaller because the tree changed, which is the
# only reason a deferral count may ever move.
#
# ``crit_profile`` left on 2026-08-16 and it did **not** retire, which is why
# it is recorded apart from the four above.  Umbrella Amendment O, Ruling 1
# reclassified the family ``PAIR_ONLY`` on a measurement: its three
# declarations all name ``Subject.HOLDER`` and none of them authors a
# pair-engine row a total holds, so the pair engine is its authoritative home,
# no second engine prices it, and the ``(family, receipt_walk)`` row it used
# to carry was a schedule category error rather than a debt.  ``_FAMILY_LANES``
# stopped declaring the lane, so the gap is gone and this row would fail the
# gate below if it stayed.  What makes that a correction rather than a
# re-count is that the emptiness is re-measured on every run of
# ``receipt_walk_schedule.py --check``, over the family's covering population
# and over a probe per owner, and the row comes back the day a mechanic of
# the family authors one.
#
# ``combat_state``, ``opening_defense`` and ``threshold_defense`` left on
# 2026-08-16 and they did **not** retire either, on a ground of their own.
# Umbrella Amendment Q corrected the lane DECLARATION: a family whose
# walk-side need is satisfied through its declared serving lane does not need,
# and must not declare, a receipt-walk interpreter lane, because one producer
# is what the one-engine thesis demands.  All three declare
# ``defense_resolver``, an interpreter answers for it, and what the receipt
# walk consumes for them is the state that interpreter built — so the
# receipt-walk lane was asking a second engine for a number the first one
# already produces, and the deferral row under it was counting the absence of
# a defect.  ``_FAMILY_LANES`` stopped declaring the lane, so the gap is gone
# and these rows would fail the gate below if they stayed.  What makes that a
# correction rather than a re-count is that the ground is measured in **both**
# directions on every run of ``receipt_walk_schedule.py --check``: what each
# family's resolver interpreter writes is joined to every read of those fields
# off a resolved defences value outside the resolver, and removing the
# resolver interpreter is asserted to flip every declaring owner to
# ``withheld`` naming the missing pair rather than to a silent zero.  The day
# a mechanic of one of them authors a walk-priced row the resolver does not
# feed, the lane comes back and the row with it.
#
# Declared ``(family, lane)`` pairs on the receipt walk that have no
# interpreter and cannot get one in this phase: their numbers arrive through
# the pair engine's timed rows today, and only Phase 4's S3 — one kernel, five
# views, with the ``OutcomeLedger`` and its end-of-walk projection — can move
# them.  Phase 3 cannot drive them to zero, and a phase exit that pretends
# otherwise is the undischarged criterion behind a green gate this block was
# built to stop.
#
# So they are **deferred, in writing, one row each**: the gap, the reason its
# number is not a silence (read from the tree, never restated here) and the
# stage that retires it.  The Phase-3 exit target is 0 *net of these rows* and
# Phase 4's exit re-asserts them retired.  A deferral is a promise with a
# creditor, which is why the gate refuses a row naming a gap the tree no
# longer holds, a row the tree's own receipt does not date to the recorded
# stage, and a gap deferred with no dated row behind it at all.
#
# The stage they name is no longer S3.  Amendment F measured that S3 cannot
# perform the retiring act at all — a row retires when ``INTERPRETERS`` holds
# its key, and projecting a ledger's quantities onto a payload leaf registers
# nothing — and umbrella Amendment K (2026-08-15) rules the act per lane and
# re-dates the rows to the closeout that ruled it.  Re-dating changes what
# these rows are overdue *against* and nothing about whether they are overdue:
# the closeout shipped and retired none of them, so all fourteen stay overdue
# with a blocker.  A re-dating that made them read as on schedule would be the
# debt getting smaller by being re-dated, which is the one thing it may not buy.
#
# Which stage they name is not spelled here either.  It is read from the stage
# record that declares itself their creditor, so re-dating them takes an edit
# to the ruled artifact rather than an edit to this dict — see
# ``deferral_creditor_stage`` below.
COUNTER_4_DEFERRAL_FAMILIES: tuple[str, ...] = (
    "periodic",
    "resistance_shred",
    "secondary_target",
    "spellblade",
)

# ── the stages the campaign has shipped, and what a passed stage owes ──────
#
# A deferral is a promise with a creditor and a due date.  The gate below
# already refuses a row whose gap the tree no longer holds and a row the
# tree's own receipt dates elsewhere; what it could not see is the third way a
# deferral goes wrong, which is the way this one did: **the stage arrives and
# the row does not retire.**  Phase 4 S3 shipped, then S4 through S10, then the
# phase boundary, and fourteen rows still record S3 as the stage that retires
# them.  Amendment B's second sentence -- "Phase 4's exit re-asserts them
# retired" -- was therefore unmet for the length of a whole phase with nothing
# saying so, which is a promise quietly turning into a habit.
#
# So every row recording a shipped stage is **overdue**: still deferred, still
# netted out of the counter, and now named as a debt with a blocker rather than
# a schedule.
#
# Neither half of that lives here.  The stage records are committed beside the
# counter at ``docs/receipts/campaign-stages.json`` (D-40 -- a counter's lists
# may not live inside the tool that measures it, and "this stage shipped" is
# the sole trigger of the rule), and shippedness is not declared even there:
# each record names the slice tag the campaign's commit subjects carry, and
# ``completed_stages`` reads the tree for it.  That is the difference between
# a rule that comes due on its own and a rule that comes due when somebody
# remembers to edit a dict -- the second is the failure shape this campaign is
# named after, one level up.
CAMPAIGN_STAGES = ROOT / "docs" / "receipts" / "campaign-stages.json"

#: The commit the campaign is measured from; the same base the sole-home scan
#: reads, so "the campaign range" means one range in both instruments.
CAMPAIGN_BASE = "584071e"

_SUBJECT_TAGS = re.compile(r"\(([^()]*)\)\s*$")


@functools.lru_cache(maxsize=None)
def declared_stages() -> Mapping[str, Mapping[str, str]]:
    """The committed stage records, keyed by the name a deferral spells.

    Read once per process.  Four call sites resolve against these records and
    two of them run per deferral row, so an uncached read parsed the ruled
    artifact fourteen times before ``import`` returned and thirty more times
    per ``--check`` — the same file, the same answer, and a reader of the
    module could not tell that from a single read.  The cache is on the I/O
    leaf and not on the derivations above it, so ``declared_stages`` stays the
    one seam a test may replace.
    """
    block = json.loads(CAMPAIGN_STAGES.read_text(encoding="utf-8"))
    return {row["stage"]: row for row in block["stages"]}


#: The debt whose creditor a stage record may declare itself.  Spelled the way
#: ``TARGET_CRITERIA`` spells the same counter and lane, because it is the same
#: counter and lane: counter 4's receipt-walk half, netted out by these rows.
CREDITOR_OF_COUNTER_4_DEFERRALS = "counter_4/receipt_walk"


def creditor_stage(debt: str) -> str:
    """The one stage the committed records declare the creditor of *debt*.

    Which stage retires an unserved lane is a ruling — Amendment K re-dated
    counter 4's fourteen receipt-walk rows off *Phase 4 S3 — one kernel, five
    views*, which Amendment F measured cannot perform the act — and a ruling's
    home is the committed stage record, not a literal in the tool that
    measures the counter (D-40) and not a field on the engine's own lane
    table.  This is the **only** home: ``interpreters.UnservedLane`` carries
    the two facts a reader can check against the tree, and nothing about when
    a row retires, so a re-dating is an edit to this artifact alone.

    A debt is spelled ``counter_4/<lane>``, exactly as ``TARGET_CRITERIA``
    spells the same counter and lane.

    The alternative that was live before this and is refused: dating the rows
    to *any* stage the records declare.  That resolves against a set of two,
    one of which is the stale stage the re-dating existed to leave, so the
    clause was satisfied by exactly the state it was meant to refuse.

    Raises:
        ValueError: no record declares it, or more than one does.  Fail
            closed both ways: no creditor leaves the rows dated to nothing,
            and two creditors let a re-dating leave the old claim standing
            beside the new one, which is the silence this derivation ends.
    """
    claimed = sorted(
        stage
        for stage, row in declared_stages().items()
        if row.get("creditor_of") == debt
    )
    if len(claimed) != 1:
        raise ValueError(
            f"{CAMPAIGN_STAGES.name} has {len(claimed)} stage record(s) "
            f"declaring themselves the creditor of "
            f"{debt} ({claimed}); exactly one may, "
            "because the stage that retires a deferral is what the row is "
            "overdue against"
        )
    return claimed[0]


def deferral_creditor_stage() -> str:
    """The ruled creditor of counter 4's receipt-walk half, by name."""
    return creditor_stage(CREDITOR_OF_COUNTER_4_DEFERRALS)


#: One deferral row per family, dated to the ruled creditor rather than to a
#: stage name written here.  Built once at import, like every other declared
#: set in this module, and fails closed if the records do not name a creditor:
#: resolving the claim is what makes ``import scripts.behavior_frontier`` raise
#: on a tree whose records name no creditor or two.  The claim is resolved
#: **once** and shared by the fourteen rows — it is one claim, and asking the
#: same question once per row said fourteen times what it says once.
_DEFERRAL_CREDITOR = deferral_creditor_stage()
COUNTER_4_DEFERRALS: Mapping[str, str] = {
    f"{family}/receipt_walk": _DEFERRAL_CREDITOR
    for family in COUNTER_4_DEFERRAL_FAMILIES
}


@functools.lru_cache(maxsize=None)
def _tag_first_seen(base: str = CAMPAIGN_BASE) -> Mapping[str, str]:
    """Every slice tag in the campaign range → the earliest sha carrying it.

    A subject's tag list is its trailing parenthetical, comma separated:
    ``feat(program): ... (P4-S9-ledger-join, 2/2b)``.  Earliest rather than
    latest because the earliest sha is stable — later commits do not move it,
    so a derived fact built on it does not churn the frontier receipt on every
    commit.

    Read once per process, for the same reason ``declared_stages`` is: the
    overdue clause runs per deferral row and each run spawned its own ``git
    log`` over the whole campaign range, fifteen subprocesses per ``--check``
    for one unchanging answer.

    Raises:
        RuntimeError: git is unavailable or the range does not resolve.  Fail
            closed: a stage-completion read that silently returns nothing
            would report every overdue row as on schedule, which is the
            silence this derivation exists to end.
    """
    try:
        completed = subprocess.run(
            ["git", "log", "--format=%h\x1f%s", f"{base}..HEAD"],
            capture_output=True,
            text=True,
            cwd=ROOT,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise RuntimeError(
            f"cannot read the campaign range {base}..HEAD: {error}"
        ) from error
    seen: dict[str, str] = {}
    for line in completed.stdout.splitlines():  # newest first
        sha, _, subject = line.partition("\x1f")
        match = _SUBJECT_TAGS.search(subject)
        if match is None:
            continue
        for tag in match.group(1).split(","):
            seen[tag.strip()] = sha
    return seen


def completed_stages() -> Mapping[str, str]:
    """Stage → why the **tree** says it shipped, for every declared stage.

    Two conjuncts, both read from commit subjects: the stage's own slice tag
    is present, and its declared successor's tag is too.  The first alone
    fires on the stage's opening commit, and a stage is not shipped while it
    is being shipped.
    """
    tags = _tag_first_seen()
    shipped: dict[str, str] = {}
    for stage, row in declared_stages().items():
        own, after = tags.get(row["slice_tag"]), tags.get(row["followed_by"])
        if own and after:
            shipped[stage] = (
                f"the campaign range carries the slice tag {row['slice_tag']!r} "
                f"from {own} and its declared successor {row['followed_by']!r} "
                f"from {after}, so the stage this row defers to has shipped and "
                "the campaign ran on past it"
            )
    return shipped


TARGET_CRITERIA: Mapping[str, str] = {
    "counter_1": "criterion 1: runtime item-name dispatch reaches zero",
    "counter_2": (
        "criterion 1: claim-prose sites at or below the reviewed "
        "NO_RUNTIME_BEHAVIOR reason count"
    ),
    "counter_3": (
        "criterion 2: every registry entry declares a rule or a reviewed "
        "NO_RUNTIME_BEHAVIOR"
    ),
    "counter_4/pair_engine": (
        "criterion 4: no declared family is uninterpreted on the pair engine"
    ),
    "counter_4/receipt_walk": (
        "criterion 4: no declared family is uninterpreted on the receipt walk"
    ),
}


def _uninterpreted_by_lane() -> dict[str, int]:
    """How many declared pairs each lane owes an interpreter for."""
    tally: dict[str, int] = {}
    for _family, lane in interpreters.uninterpreted_pairs():
        tally[lane.value] = tally.get(lane.value, 0) + 1
    return tally


def _lane_owed_to(lane: str) -> str:
    """What the ruled records say retires *lane*'s remaining gaps.

    Which gaps remain is read from ``UNSERVED_LANE_RECEIPTS``, so a lane the
    tree has closed stops being owed to anything without a second edit; which
    stage owes them is read from the record claiming that lane's debt, because
    the engine does not declare one.  No open gap at all is the empty string,
    which is the honest rendering of a lane nothing schedules — it is what
    ``counter_4/pair_engine`` says, and it says it because that lane is served.
    """
    open_gaps = any(
        pair_lane.value == lane and (family, pair_lane) not in interpreters.INTERPRETERS
        for family, pair_lane in interpreters.UNSERVED_LANE_RECEIPTS
    )
    return creditor_stage(f"counter_4/{lane}") if open_gaps else ""


def deferral_block() -> dict[str, Any]:
    """Counter 4's committed deferrals: the gap, its reason and its creditor.

    The reason is read from ``interpreters.UNSERVED_LANE_RECEIPTS`` and the
    recorded stage from the record that claims this lane's debt, so each fact
    is transcribed from its one home rather than said twice; what this module
    owns is the *decision* to defer, which is the part a receipt has to carry
    because no code implies it.  A row carries no second copy of its stage:
    ``retires_at`` used to ride beside ``recorded_stage`` because the two came
    from two homes and could disagree, and it left with the second home.
    """
    shipped = completed_stages()
    blockers = {
        stage: row.get("blocked_on", "") for stage, row in declared_stages().items()
    }
    rows: dict[str, dict[str, str]] = {}
    for key, stage in sorted(COUNTER_4_DEFERRALS.items()):
        row = next(
            (
                receipt
                for (
                    family,
                    lane,
                ), receipt in interpreters.UNSERVED_LANE_RECEIPTS.items()
                if f"{family.value}/{lane.value}" == key
            ),
            None,
        )
        rows[key] = {
            "recorded_stage": stage,
            "reason": row.reason if row is not None else "",
            "overdue": stage in shipped,
            "overdue_because": shipped.get(stage, ""),
            "blocked_on": blockers.get(stage, "") if stage in shipped else "",
        }
    return {
        "rule": (
            "umbrella criterion 7, Amendment B (2026-08-12): a declared "
            "(family, lane) gap Phase 3 cannot close is deferred in writing to "
            "the stage that can.  The Phase-3 exit target is 0 net of these "
            "rows; Phase 4's exit re-asserts them retired.  A row naming a gap "
            "the tree no longer holds, or a stage the tree's own receipt does "
            "not say, fails the gate"
        ),
        "rows": rows,
        "by_lane": _deferrals_by_lane(),
    }


def _deferrals_by_lane() -> dict[str, int]:
    """How many deferral rows each lane carries."""
    tally: dict[str, int] = {}
    for key in COUNTER_4_DEFERRALS:
        lane = key.split("/", 1)[1]
        tally[lane] = tally.get(lane, 0) + 1
    return tally


def _deferral_failures(
    committed: Mapping[str, Any], fresh: Mapping[str, Any]
) -> list[str]:
    """Amendment B's rows, gated by set equality and against the tree (D-40).

    Fails closed on a missing section.  Four substantive clauses: the
    committed rows equal the declared ones, every deferred gap is still an
    open gap in the tree, every deferred gap has the tree's own unserved-lane
    receipt behind it, and the **committed** receipt records the stage the
    ruled records claim today.  Without the first three a deferral would
    outlive the gap it excused, which is a counter driven to its target by a
    row nobody re-read.

    The last clause is where the old two-homes clause went.  While the stage
    was declared both on ``UnservedLane.retires_at`` and in the stage records,
    this compared the two and caught a re-dating that moved only one — at the
    price of making every ruled re-dating a ``src/`` commit.  With one home
    that comparison has nothing left to disagree about, so what is compared
    instead is the pair that still can: a re-dating lands in
    ``campaign-stages.json`` and the committed frontier receipt is stale until
    it is regenerated, and a stale receipt is now red rather than invisible.
    """
    recorded = committed.get("counters", {}).get("counter_4", {}).get("deferrals")
    if not isinstance(recorded, Mapping):
        return [
            "counter 4: the committed receipt records no deferral rows; run --write"
        ]
    failures: list[str] = []
    declared = fresh["counters"]["counter_4"]["deferrals"]["rows"]
    if set(recorded.get("rows", {})) != set(declared):
        failures.append(
            "counter 4: the committed deferral set differs from the declared "
            f"one (committed-only="
            f"{sorted(set(recorded.get('rows', {})) - set(declared))}, "
            f"declared-only={sorted(set(declared) - set(recorded.get('rows', {})))})"
        )
    open_gaps = set(fresh["counters"]["counter_4"]["pairs"])
    dated = fresh["counters"]["counter_4"]["receipts"]["dated"]
    for key, row in sorted(declared.items()):
        if key not in open_gaps:
            failures.append(
                f"counter 4: {key} is deferred and is not an open gap — a "
                "deferral that outlives its gap excuses a counter nobody re-read"
            )
            continue
        if key not in dated:
            failures.append(
                f"counter 4: {key} is deferred and no unserved-lane receipt "
                "dates it; a deferral needs the tree's own reason behind it"
            )
        committed_row = recorded.get("rows", {}).get(key)
        if (
            isinstance(committed_row, Mapping)
            and committed_row.get("recorded_stage") != row["recorded_stage"]
        ):
            failures.append(
                f"counter 4: {key} is committed as deferred to "
                f"{committed_row.get('recorded_stage')!r} and the record "
                f"claiming its debt says {row['recorded_stage']!r}; a "
                "re-dating that never reached the receipt is half-landed"
            )
        failures.extend(_overdue_failures(key, row, recorded.get("rows", {})))
    return failures


def _overdue_failures(
    key: str, row: Mapping[str, Any], committed_rows: Mapping[str, Any]
) -> list[str]:
    """A deferral whose stage has shipped is a debt, and must say so.

    Four clauses.  The first is the one that makes the other three come due on
    their own: a deferral may not name a stage no committed record declares,
    so the record exists before the row does and the tree — not an edit to
    this module — decides when the row goes overdue.  Then the row recording a
    completed stage must be declared overdue with a blocker a reader can open,
    an overdue claim on a live stage is refused, and the committed receipt must
    agree.  A row that quietly outlives its own due date is how "deferred to
    the stage that can close it" becomes "deferred".
    """
    stage = row["recorded_stage"]
    failures: list[str] = []
    if stage not in declared_stages():
        failures.append(
            f"counter 4: {key} is deferred to {stage!r}, which no row of "
            "docs/receipts/campaign-stages.json declares; a stage nothing "
            "records can never come due"
        )
    if stage in completed_stages():
        if not row["overdue"] or not row["blocked_on"]:
            failures.append(
                f"counter 4: {key} is deferred to {stage!r}, which has shipped, "
                "and is not declared overdue with a blocker"
            )
    elif row["overdue"]:
        failures.append(
            f"counter 4: {key} is declared overdue but {stage!r} is not a "
            "completed stage"
        )
    committed = committed_rows.get(key)
    if isinstance(committed, Mapping) and committed.get("overdue") != row["overdue"]:
        failures.append(
            f"counter 4: {key}'s committed receipt says overdue="
            f"{committed.get('overdue')!r} and the tree says {row['overdue']!r}"
        )
    return failures


def target_block(report: FrontierReport) -> dict[str, Any]:
    """Each counter's target, the bound it resolves to, and the gap left.

    Counter 4's two lane targets are measured **net of the committed deferral
    rows** (Amendment B): the gross gap and the deferred count ride the entry
    beside the net one, so the netting is arithmetic a reader can check rather
    than a smaller number with no derivation.
    """
    by_lane = _uninterpreted_by_lane()
    deferred = _deferrals_by_lane()
    measured: dict[str, tuple[int, int, str]] = {
        "counter_1": (0, report.counter_1, ""),
        # The bound is the reviewed set's live size, so reviewing an item in
        # or out moves the target the same commit it moves the set.
        "counter_2": (len(item_coverage.NO_RUNTIME_BEHAVIOR), report.counter_2, ""),
        "counter_3": (0, report.counter_3, ""),
        **{
            f"counter_4/{lane}": (
                0,
                by_lane.get(lane, 0) - deferred.get(lane, 0),
                _lane_owed_to(lane),
            )
            for lane in COUNTER_4_TARGET_LANES
        },
    }
    netting = {
        f"counter_4/{lane}": {
            "gross": by_lane.get(lane, 0),
            "deferred": deferred.get(lane, 0),
        }
        for lane in COUNTER_4_TARGET_LANES
    }
    return {
        "rule": (
            "a target's gap may not grow, a met target may not stay recorded "
            "outstanding, and a target the receipt has lost is a failure; the "
            "block records targets and never amends one.  Counter 4's lane "
            "targets are measured net of the committed deferral rows "
            "(Amendment B), and the gross and deferred halves ride the entry "
            "so the netting is checkable arithmetic"
        ),
        "targets": {
            key: {
                "criterion": TARGET_CRITERIA[key],
                "bound": bound,
                "measured": value,
                "gap": max(value - bound, 0),
                "met": value <= bound,
                "owed_to": owed,
                **netting.get(key, {}),
            }
            for key, (bound, value, owed) in sorted(measured.items())
        },
    }


def _target_failures(
    committed: Mapping[str, Any], fresh: Mapping[str, Any]
) -> list[str]:
    """The target ratchet: no growth, no disagreement, no lost target."""
    recorded_block = committed.get("targets")
    if not isinstance(recorded_block, Mapping):
        return ["targets: the committed receipt has no targets section; run --write"]
    recorded = recorded_block.get("targets", {})
    fresh_targets = fresh["targets"]["targets"]
    failures: list[str] = []
    lost = sorted(set(recorded) - set(fresh_targets))
    if lost:
        failures.append(f"targets: the tree no longer measures {lost}")
    for key, entry in sorted(fresh_targets.items()):
        was = recorded.get(key)
        if not isinstance(was, Mapping):
            failures.append(f"targets: {key} is not in the committed receipt")
            continue
        if entry["measured"] > was.get("measured", 0):
            failures.append(
                f"targets: {key} moved away from its target "
                f"({was.get('measured')} -> {entry['measured']}, bound "
                f"{entry['bound']})"
            )
        if entry["met"] != was.get("met"):
            failures.append(
                f"targets: {key} is met={entry['met']} in the tree and "
                f"met={was.get('met')} in the receipt"
            )
        if entry["bound"] != was.get("bound"):
            failures.append(
                f"targets: {key}'s bound moved from {was.get('bound')} to "
                f"{entry['bound']}; a target's bound changes deliberately or "
                "not at all"
            )
    return failures


# The pre-phase size of the reviewed no-modelled-effect claim, measured on the
# commit before 3.8's flip renamed it.  A literal rather than a live
# ``len(...)``: a ceiling read off the set it bounds is not a ratchet, it is a
# tautology, and the whole point is that the set may never grow past what the
# migration inherited.
NO_RUNTIME_BEHAVIOR_CEILING = 56


def no_runtime_behavior_block() -> dict[str, Any]:
    """The reviewed-nothing ratchet: its members, and the ceiling they ride.

    Empty at 3.1 — nothing has been reviewed yet — and bounded by the size of
    the reviewed stats-only claim it replaces, measured on this commit.  The
    bound is what stops counter 3 being driven to zero by reviewing the
    backlog into silence: counter 3's target is
    ``declared >= entries - |NO_RUNTIME_BEHAVIOR|``.
    """
    members = sorted(item_coverage.NO_RUNTIME_BEHAVIOR)
    return {
        "members": members,
        "sourced": sorted(
            name
            for name in members
            if name in item_coverage._SOURCE_REFS  # noqa: SLF001
        ),
        "declaring": sorted(
            name
            for name in members
            if any(
                catalog.declares_runtime_behaviour(rule)
                for rule in catalog.behavior_rules(name)
            )
        ),
        "ratchet_ceiling": NO_RUNTIME_BEHAVIOR_CEILING,
        "ceiling_source": (
            "the size of item_coverage._REVIEWED_STATS_ONLY measured before "
            "3.8, the reviewed no-modelled-effect claim this set is the rename "
            "of; the set is non-increasing from it"
        ),
        "rule": (
            "|members| may never exceed the ceiling and may never grow once a "
            "slice has set it; every member carries a SourceReceipt and a "
            "reviewed reason"
        ),
    }


# ── the zero-policy frontier (D-24) ──────────────────────────────────────
#
# ``damage_entry`` and ``simple_damage`` carry the champion tree's one
# declared ``zero_policy`` default, so their champion call sites are not
# edited.  That exception is only honest while the inputs those formulas
# read are wired: a stack count or option that never resolved, silently
# replaced by a literal, is a zero the default would stamp ``MEASURED``.
#
# So the guard has a forbidden half and a ratcheted half, and the split is
# the whole point.  Forbidden: a ``.get(key, <literal>)`` on one of the
# three champion *input* blocks — the build's stats, the target's stats,
# the user's options.  Those feed the damage formulas, and D-24 requires
# the shape to be refused there, not counted.  ``champions/inputs.py``
# holds the vocabularies and declared defaults that replaced them.
# Ratcheted: the same shape on a block a champion module *produced* — an
# emitted entry, a reviewed packet spec, an authored event row — which is
# not an unwired input and is pinned non-growing instead.

CHAMPIONS_ROOT = SRC_ROOT / "calculator" / "champions"

ZERO_POLICY_ISSUE = "issue #213"

# The builders that supply the declared default.  A champion entry built by
# hand instead of through one of these carries no policy at all.
ENTRY_BUILDERS = ("damage_entry", "simple_damage")

# Keys that make a dict literal an ability entry rather than any other
# mapping: the fight engine reads ``parts`` and the producer diagnostics
# carry ``total_raw``.
ENTRY_MARKER_KEYS = frozenset({"parts", "total_raw"})

# The names a champion *input* block is bound to.  A ``.get`` whose receiver
# expression mentions one of these reads an input, however it is wrapped
# (``ctx.options``, ``ctx.target or {}``, a ``stats_context`` parameter), and
# the fallback literal is forbidden there.  Everything else under
# ``champions/`` reads a value the tree itself produced.
INPUT_BLOCK_NAMES = frozenset(
    {
        "stats",
        "target",
        "options",
        "champion_stats",
        "target_stats",
        "champion_options",
        "stats_context",
    }
)


@dataclass(frozen=True, slots=True)
class ZeroPolicyFrontier:
    """The guard's three populations: one forbidden, two pinned.

    ``forbidden_input_fallbacks`` are ``x.get(key, <number>)`` reads whose
    receiver is a champion input block.  The set must be **empty** — this is
    D-24's source assertion, not a counter — and each member is reported as
    ``module:line  expression`` so a failure names the site.

    ``produced_fallbacks`` are the same shape on a block the champion tree
    produced rather than received, tallied by receiver.  ``hand_built_entries``
    are ability-entry dict literals that bypass both builders, tallied by
    module, and are therefore leaves carrying no policy at all.  Both are
    pinned non-growing per module, not merely in total.
    """

    forbidden_input_fallbacks: tuple[str, ...]
    produced_fallbacks: dict[str, int]
    hand_built_entries: dict[str, int]

    def totals(self) -> dict[str, int]:
        """The three populations as three numbers."""
        return {
            "forbidden_input_fallbacks": len(self.forbidden_input_fallbacks),
            "produced_fallbacks": sum(self.produced_fallbacks.values()),
            "hand_built_entries": sum(self.hand_built_entries.values()),
        }


def _literal_default(node: ast.AST) -> bool:
    """Whether a ``.get`` default is a bare number (or its negation)."""
    if isinstance(node, ast.Constant):
        return isinstance(node.value, (int, float)) and not isinstance(node.value, bool)
    if isinstance(node, ast.UnaryOp):
        return _literal_default(node.operand)
    return False


def _receiver(call: ast.Call) -> str:
    """The tail of the expression a ``.get`` is called on — ``ctx.options``.

    The receiver is the interesting half: ``options`` says a champion option
    is being defaulted, ``entry`` says a produced entry is.  Anything whose
    tail is itself a call is bucketed as ``chained`` rather than given a name
    a reader could not look up.
    """
    receiver = ast.unparse(call.func.value)  # type: ignore[attr-defined]
    tail = receiver.split(".")[-1].strip("() ")
    if not tail or "(" in tail or ")" in tail or " " in tail:
        return "chained"
    return tail


def _reads_an_input_block(call: ast.Call) -> bool:
    """Whether a ``.get``'s receiver is one of the three champion inputs.

    Structural rather than textual: the receiver expression is walked for a
    name or attribute in :data:`INPUT_BLOCK_NAMES`, so ``ctx.options``,
    ``(ctx.target or {})`` and a bare ``stats_context`` parameter all count
    while ``entry`` and ``ability_damages.get("R", {})`` do not.
    """
    receiver = call.func.value  # type: ignore[attr-defined]
    for node in ast.walk(receiver):
        if isinstance(node, ast.Attribute) and node.attr in INPUT_BLOCK_NAMES:
            return True
        if isinstance(node, ast.Name) and node.id in INPUT_BLOCK_NAMES:
            return True
    return False


def _policy_stamping_nodes(tree: ast.AST) -> set[int]:
    """Every node id inside ``damage_entry`` — the one policy-stamping body.

    Its own entry dict is not a bypass of itself, and counting it would make
    the population mean two different things.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "damage_entry":
            return {id(inner) for inner in ast.walk(node)}
    return set()


def zero_policy_frontier(root: Path = CHAMPIONS_ROOT) -> ZeroPolicyFrontier:
    """Measure the three populations over the champion tree."""
    forbidden: list[str] = []
    produced: dict[str, int] = {}
    entries: dict[str, int] = {}
    for path in sorted(root.rglob("*.py")):
        module = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        stamping = _policy_stamping_nodes(tree)
        for node in ast.walk(tree):
            if id(node) in stamping:
                continue
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and len(node.args) == 2
                and _literal_default(node.args[1])
            ):
                if _reads_an_input_block(node):
                    forbidden.append(f"{module}:{node.lineno}  {ast.unparse(node)}")
                else:
                    key = _receiver(node)
                    produced[key] = produced.get(key, 0) + 1
            if isinstance(node, ast.Dict) and ENTRY_MARKER_KEYS & {
                key.value
                for key in node.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            }:
                entries[module] = entries.get(module, 0) + 1
    return ZeroPolicyFrontier(
        forbidden_input_fallbacks=tuple(sorted(forbidden)),
        produced_fallbacks=dict(sorted(produced.items())),
        hand_built_entries=dict(sorted(entries.items())),
    )


def zero_policy_block(frontier: ZeroPolicyFrontier) -> dict[str, Any]:
    """The receipt's zero-policy section — one refusal and two ratchets."""
    return {
        "issue": ZERO_POLICY_ISSUE,
        "rule": (
            "a .get(key, <literal>) on a champion input block (stats, "
            "target, options) is forbidden outright — D-24's source "
            "assertion, and the guard the declared zero_policy default only "
            "holds with; the same shape on a block the tree produced is "
            "pinned non-growing per receiver, and hand-built ability entries "
            "per module, so neither can widen without a decision"
        ),
        "declared_default": (
            "champions/slotlib.MODULE_FORMULA_ZERO, supplied by damage_entry "
            "and simple_damage and overridable per call (D-24)"
        ),
        "input_vocabularies": (
            "src/calculator/champions/inputs.py — the declared defaults that "
            "replaced the forbidden literals, each with a reason and a "
            "producer its name is asserted against"
        ),
        "totals": frontier.totals(),
        "forbidden_input_fallbacks": list(frontier.forbidden_input_fallbacks),
        "produced_fallbacks_by_receiver": frontier.produced_fallbacks,
        "hand_built_entries_by_module": frontier.hand_built_entries,
    }


_RATCHETED_ZERO_POLICY_SECTIONS = {
    "produced_fallbacks_by_receiver": "receiver",
    "hand_built_entries_by_module": "module",
}


def _zero_policy_failures(
    committed: Mapping[str, Any], fresh: Mapping[str, Any]
) -> list[str]:
    """The zero-policy half of the gate: one refusal, two per-key ratchets.

    Fails closed on every path.  A receipt with the section deleted, a
    missing total, or a non-integer where a count belongs is a failure, not
    a skipped check — the earlier version read the committed numbers with
    chained ``.get``s and an ``isinstance`` guard, so deleting the section
    disabled the gate silently, which is the shape this campaign removes.
    """
    failures: list[str] = []
    committed_zero = committed.get("zero_policy_frontier")
    fresh_zero = fresh["zero_policy_frontier"]

    forbidden = fresh_zero["forbidden_input_fallbacks"]
    if forbidden:
        failures.append(
            "zero-policy frontier: "
            f"{len(forbidden)} champion-input .get(key, <literal>) "
            "fallback(s) — forbidden outright, because the declared "
            "zero_policy default would stamp the resulting zero MEASURED "
            f"(D-24, {ZERO_POLICY_ISSUE}); read them through "
            "champions/inputs.py instead: " + "; ".join(forbidden)
        )

    if not isinstance(committed_zero, Mapping):
        failures.append(
            "zero-policy frontier: the committed receipt has no "
            "zero_policy_frontier section; run --write"
        )
        return failures

    for population, measured in fresh_zero["totals"].items():
        recorded = committed_zero.get("totals", {}).get(population)
        if not isinstance(recorded, int):
            failures.append(
                f"zero-policy frontier: the receipt records no total for "
                f"{population}; run --write"
            )
        elif measured > recorded:
            failures.append(
                f"zero-policy frontier: {population} grew from {recorded} to "
                f"{measured}; the ruled default at champions/slotlib may not "
                f"cover a wider population ({ZERO_POLICY_ISSUE})"
            )

    # Per-key, not only per-total: a total-only ratchet lets a site removed
    # from one module pay for a site added to another.
    for section, unit in _RATCHETED_ZERO_POLICY_SECTIONS.items():
        recorded_section = committed_zero.get(section)
        if not isinstance(recorded_section, Mapping):
            failures.append(
                f"zero-policy frontier: the receipt records no {section}; "
                "run --write"
            )
            continue
        for key, measured in fresh_zero[section].items():
            recorded = recorded_section.get(key, 0)
            if not isinstance(recorded, int) or measured > recorded:
                failures.append(
                    f"zero-policy frontier: {section} for {unit} {key!r} "
                    f"grew from {recorded!r} to {measured} "
                    f"({ZERO_POLICY_ISSUE})"
                )
    return failures


def _unserved_lane_failures(
    committed: Mapping[str, Any], fresh: Mapping[str, Any]
) -> list[str]:
    """Counter 4's content, gated by set equality like its exclusions (D-40).

    Fails closed on a receipt with the section missing, because a gate that
    skips what it cannot find is the shape this campaign removes.  The
    ``unreceipted`` population is asserted empty here as well as at import:
    the two checks read the same tree by two routes, and a green count with a
    non-empty list would mean the import gate had been bypassed.
    """
    recorded = committed.get("counters", {}).get("counter_4", {}).get("receipts")
    measured = fresh["counters"]["counter_4"]["receipts"]
    if not isinstance(recorded, Mapping):
        return [
            "counter 4: the committed receipt records no unserved-lane "
            "receipts; run --write"
        ]
    failures: list[str] = []
    if measured["unreceipted"]:
        failures.append(
            "counter 4: "
            f"{measured['unreceipted']} are declared, unserved and named by no "
            "receipt at all"
        )
    for key in ("dated", "per_rule_receipted"):
        if set(recorded.get(key, ())) != set(measured[key]):
            failures.append(
                f"counter 4: the committed {key} set differs from the tree's "
                f"(committed-only={sorted(set(recorded.get(key, ())) - set(measured[key]))}, "
                f"measured-only={sorted(set(measured[key]) - set(recorded.get(key, ())))})"
            )
    failures.extend(_route_failures(recorded.get("dated", {}), measured["dated"]))
    return failures


def _route_failures(
    recorded: Mapping[str, Any], measured: Mapping[str, Any]
) -> list[str]:
    """The route each dated row claims, diff-gated like every other content.

    The key set alone would let a row silently change which interpreter it
    says produces its number — the one part of the row that is a claim about
    code rather than about a schedule.  ``interpreters`` checks the route
    against its registry at import; this checks it against the committed
    artifact, so moving a route is a diff a reader meets (D-40).
    """
    failures: list[str] = []
    for key in sorted(set(recorded) & set(measured)):
        was = list(recorded[key].get("via", ()))
        now = list(measured[key].get("via", ()))
        if was != now:
            failures.append(
                f"counter 4: {key} is recorded as routed through {was} and the "
                f"tree routes it through {now}"
            )
    return failures


def _claim_evidence_failures(
    committed: Mapping[str, Any], fresh: Mapping[str, Any]
) -> list[str]:
    """Amendment A's exclusion arm, gated the way Class C and D are (D-40).

    Four clauses.  Set equality against the receipt makes an edit a diff in a
    committed artifact.  A container key in a module that is not Class B would
    excuse counter 1 rather than counter 2, so it is refused outright.  A
    container that binds nothing in its module is a stale exclusion — it
    excludes no site and reads as though it does, which is the prose-outruns-
    code shape this phase deletes.  And the section may not be deleted: a gate
    that skips what it cannot find is not a gate.
    """
    recorded = committed.get("exclusions", {}).get("class_c_claim_evidence_containers")
    if not isinstance(recorded, Mapping):
        return [
            "class_c_claim_evidence_containers: the committed receipt has no "
            "claim-evidence exclusion section; run --write"
        ]
    failures: list[str] = []
    declared = fresh["exclusions"]["class_c_claim_evidence_containers"]["containers"]
    committed_containers = recorded.get("containers", {})
    if set(committed_containers) != set(declared):
        failures.append(
            "class_c_claim_evidence_containers: committed modules differ from "
            f"the declared ones (committed-only="
            f"{sorted(set(committed_containers) - set(declared))}, declared-only="
            f"{sorted(set(declared) - set(committed_containers))})"
        )
    for module, containers in sorted(declared.items()):
        was = set(committed_containers.get(module, {}))
        if was != set(containers):
            failures.append(
                f"class_c_claim_evidence_containers: {module}'s committed "
                f"container set differs from the declared one (committed-only="
                f"{sorted(was - set(containers))}, declared-only="
                f"{sorted(set(containers) - was)})"
            )
        if module not in CLASS_B_CLAIM_PROSE:
            failures.append(
                f"class_c_claim_evidence_containers: {module} is not a Class B "
                "module, so a container exclusion there would excuse counter 1"
            )
            continue
        path = SRC_ROOT / module
        bound = set(
            top_level_bindings(ast.parse(path.read_text(encoding="utf-8"))).values()
        )
        stale = sorted(set(containers) - bound)
        if stale:
            failures.append(
                f"class_c_claim_evidence_containers: {stale} are excluded in "
                f"{module} and bind nothing there — a stale exclusion reads as "
                "though it excused something"
            )
    return failures


def _compiled_walk_refusal_failures(
    committed: Mapping[str, Any], fresh: Mapping[str, Any]
) -> list[str]:
    """The compiled walk's refusal set, gated by set equality (D-40).

    Fails closed: a receipt with the section deleted is a failure and not a
    skipped check, so the gate cannot be disarmed by removing what it reads.
    """
    recorded = committed.get("compiled_walk_refusals")
    if not isinstance(recorded, Mapping):
        return [
            "compiled-walk refusals: the committed receipt has no "
            "compiled_walk_refusals section; run --write"
        ]
    measured = fresh["compiled_walk_refusals"]
    failures = []
    if set(recorded.get("refused", {})) != set(measured["refused"]):
        failures.append(
            "compiled-walk refusals: the refused owner set differs from the "
            "committed one (committed-only="
            f"{sorted(set(recorded.get('refused', {})) - set(measured['refused']))}, "
            f"measured-only={sorted(set(measured['refused']) - set(recorded.get('refused', {})))})"
        )
    for owner, families in sorted(measured["refused"].items()):
        if list(recorded.get("refused", {}).get(owner, ())) != families:
            failures.append(
                f"compiled-walk refusals: {owner} is refused by "
                f"{families}, and the receipt records "
                f"{list(recorded.get('refused', {}).get(owner, ()))}"
            )
    return failures


def _no_runtime_behavior_failures(
    committed: Mapping[str, Any], fresh: Mapping[str, Any]
) -> list[str]:
    """The reviewed-nothing ratchet: set-equal, bounded, and every member sourced.

    Four checks and not one.  Set equality against the receipt makes an edit
    a diff in a committed artifact (D-40); the ceiling makes the set
    non-increasing from what the migration inherited; requiring a
    ``SourceReceipt`` per member is what stops "we reviewed it" from being the
    same unbacked sentence this phase deletes everywhere else; and no member
    may compile a ``BehaviorRule``, because a compiled rule *is* declared
    runtime behaviour and an item asserting both says two contradictory
    things.  The fourth is what keeps the ratchet's ceiling meaningful: a set
    that may hold items with live rules bounds a population far larger than
    the one that can reach the rung it gates.
    """
    failures: list[str] = []
    recorded = committed.get("no_runtime_behavior")
    measured = fresh["no_runtime_behavior"]
    if not isinstance(recorded, Mapping):
        return [
            "NO_RUNTIME_BEHAVIOR: the committed receipt has no "
            "no_runtime_behavior section; run --write"
        ]
    if set(recorded.get("members", ())) != set(measured["members"]):
        failures.append(
            "NO_RUNTIME_BEHAVIOR: the committed member set differs from the "
            f"declared one (committed-only="
            f"{sorted(set(recorded.get('members', ())) - set(measured['members']))}, "
            f"declared-only="
            f"{sorted(set(measured['members']) - set(recorded.get('members', ())))})"
        )
    if len(measured["members"]) > NO_RUNTIME_BEHAVIOR_CEILING:
        failures.append(
            f"NO_RUNTIME_BEHAVIOR holds {len(measured['members'])} members, "
            f"above its ratchet ceiling of {NO_RUNTIME_BEHAVIOR_CEILING}"
        )
    declaring = sorted(measured.get("declaring", ()))
    if declaring:
        failures.append(
            f"NO_RUNTIME_BEHAVIOR: {declaring} compile a BehaviorRule — a "
            "declared rule is runtime behaviour, so the reviewed absence "
            "beside it is false"
        )
    unsourced = sorted(set(measured["members"]) - set(measured["sourced"]))
    if unsourced:
        failures.append(
            "NO_RUNTIME_BEHAVIOR: no wiki revision is recorded for "
            f"{unsourced} — a reviewed absence with no source is the sentence "
            "this phase deletes"
        )
    return failures


def build_receipt(report: FrontierReport) -> dict[str, Any]:
    """The committed frontier artifact."""
    return {
        "schema_version": SCHEMA_VERSION,
        "slice": "3.9",
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
                "receipts": unserved_lane_block(),
                "deferrals": deferral_block(),
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
            "class_c_claim_evidence_containers": {
                "sites": report.class_c_claim_evidence_sites,
                "amendment": (
                    "umbrella criterion 7, Amendment A (2026-08-12): Phase 1's "
                    "authored claim-evidence corpus and _REVIEW_ISSUE_REFS are "
                    "Class C, not claim prose; counter 2 is measured net of them"
                ),
                "containers": {
                    module: dict(sorted(containers.items()))
                    for module, containers in sorted(
                        CLASS_C_CLAIM_EVIDENCE_CONTAINERS.items()
                    )
                },
                "sites_by_container": {
                    module: dict(sorted(tally.items()))
                    for module, tally in sorted(
                        report.claim_evidence_by_container.items()
                    )
                },
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
        "targets": target_block(report),
        "compiled_walk_refusals": compiled_walk_refusals(),
        "no_runtime_behavior": no_runtime_behavior_block(),
        "zero_policy_frontier": zero_policy_block(zero_policy_frontier()),
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
    failures.extend(_claim_evidence_failures(committed, fresh))
    failures.extend(_target_failures(committed, fresh))
    failures.extend(_unserved_lane_failures(committed, fresh))
    failures.extend(_deferral_failures(committed, fresh))
    failures.extend(_zero_policy_failures(committed, fresh))
    failures.extend(_compiled_walk_refusal_failures(committed, fresh))
    failures.extend(_no_runtime_behavior_failures(committed, fresh))
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
        for key, entry in sorted(receipt["targets"]["targets"].items()):
            if not entry["met"]:
                print(
                    f"behavior frontier: {key} is {entry['gap']} above its "
                    f"target of {entry['bound']} — "
                    f"{entry['owed_to'] or 'no receipt in the tree names who retires it'}"
                )
            elif entry.get("deferred"):
                print(
                    f"behavior frontier: {key} is met net of "
                    f"{entry['deferred']} committed deferral row(s) of "
                    f"{entry['gross']} — {entry['owed_to']}"
                )
        return 0
    if not args.json and not args.write:
        print(json.dumps(report.counters()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
