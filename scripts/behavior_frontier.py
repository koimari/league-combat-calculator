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
empty registry would report full coverage.  Its *content* is carried beside
the number: every gap a declaration reaches is either a dated row in
``interpreters.UNSERVED_LANE_RECEIPTS`` — the route the number arrives by
instead, plus the stage that retires the row — or a compiled lane refused by
that rule's own ``ReceiptOnly``.  The receipt records both, so a reader meets
the reason where they meet the count and the gate diffs it by set equality;
the import-time gate in ``interpreters`` is what makes an *unreceipted* gap
impossible in the first place.

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
from src.calculator.item_behavior import ReceiptOnly, ReceiptScope  # noqa: E402
from src.calculator.survival import compile as compile_module  # noqa: E402

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


def unserved_lane_block() -> dict[str, Any]:
    """Counter 4's content: why each declared lane has no interpreter.

    Two populations, because they are excused by two different things and
    collapsing them would hide which.  ``dated`` are the rows
    ``interpreters.UNSERVED_LANE_RECEIPTS`` carries — a route and a retiring
    stage each.  ``per_rule_receipted`` are the compiled-lane gaps no row
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
            "retires_at": row.retires_at,
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


def compiled_walk_delta() -> dict[str, Any]:
    """D-98's derivation, landed beside ``COMPILED_WALK_UNREPRESENTABLE_ITEMS``.

    The hand set is the compiled score kernel's per-item capability report;
    :func:`interpreters.compilability_for` is the per-owner fold that succeeds
    it (D-43).  This block is the two answers side by side with the difference
    committed, because at 3.8 they are **not** set-equal and pretending
    otherwise would be the prose-outruns-code failure inside the instrument
    that measures it.

    ``legacy_only`` is the direction that blocks the flip.  A member here is an
    item the hand set withholds and the fold would let compile, so flipping
    today would silently drop a mechanic — the campaign's own incident shape.
    ``derived_only`` is the safe direction: the fold is more conservative than
    the hand set, and every member says which family made it so.

    Both are gated by set equality against the committed receipt rather than
    by a count, so a declaration that closes one of them shows up as a diff in
    a committed artifact (D-40).

    Both answers are read **in one scope** —
    ``ReceiptScope.SURVIVAL_LEDGER_TRANSITION`` — because that is the question
    the hand set answers: ``uncompilable_item_receipt`` asks a build whether
    the score ledger can stage the state transitions its items author, and
    never whether a support template is instantaneous or whether an amp is
    representable.  Folding all three refusals into one verdict is what made
    ``derived_only`` twenty-eight items long while the hand set held sixteen;
    the two sets were never measuring the same thing.

    ``flip_blocked_by`` is **derived** from the two difference directions
    rather than written out.  The hand-written version named
    ``stat_derivation`` as a cause and survived the slice that migrated it:
    the sentence stayed true in its first half and false in its second, inside
    the block whose whole job is to say why the flip is still blocked.  A
    blocker computed from the difference it describes cannot rot that way, and
    it disappears exactly when the flip becomes legal.
    """
    legacy = frozenset(compile_module.COMPILED_WALK_UNREPRESENTABLE_ITEMS)
    derived: dict[str, list[str]] = {}
    for owner in sorted(item_names() | legacy):
        verdict = interpreters.compilability_for(owner, LEDGER_SCOPE)
        if not isinstance(verdict, ReceiptOnly):
            continue
        # The families that made the fold refuse.  An owner with a registry
        # entry and no rule at all refuses for a different reason and gets the
        # empty list, which is the honest rendering of "nothing models it yet".
        derived[owner] = sorted(
            {
                rule.family.value
                for rule in catalog.behavior_rules(owner)
                if isinstance(rule.compilability, ReceiptOnly)
                and rule.compilability.scope is LEDGER_SCOPE
            }
        )
    legacy_only = sorted(legacy - set(derived))
    derived_only = sorted(set(derived) - legacy)
    return {
        "legacy_symbol": "survival.compile.COMPILED_WALK_UNREPRESENTABLE_ITEMS",
        "derived_symbol": "interpreters.compilability_for",
        "derived_scope": LEDGER_SCOPE.value,
        "legacy": sorted(legacy),
        "derived": dict(sorted(derived.items())),
        "legacy_only": legacy_only,
        "derived_only": derived_only,
        "flip_blocked_by": _flip_blockers(legacy_only, derived_only),
    }


def _flip_blockers(
    legacy_only: Sequence[str], derived_only: Sequence[str]
) -> tuple[str, ...]:
    """Why the one-symbol flip is still illegal, read off the difference.

    One clause per direction, each naming its own members, plus counter 3's
    if the declaration base is still incomplete.  All three are conditional,
    so an empty ``flip_blocked_by`` *is* the statement that D-98's flip may
    land — the receipt cannot say "blocked" while the sets agree, and cannot
    say "clear" while they do not.
    """
    clauses: list[str] = []
    if legacy_only:
        clauses.append(
            "the hand set withholds "
            + ", ".join(legacy_only)
            + " and the fold does not: every rule they compile to is Compilable "
            "in the survival-ledger scope, so flipping today would let a build "
            "the kernel cannot stage ride the compiled walk — the campaign's "
            "own incident shape.  Closing them is a migration, not a flip: a "
            "scoped ReceiptOnly on the rule the walk authors, or a new "
            "declaration where no rule models the mechanic at all."
        )
    if derived_only:
        clauses.append(
            "the fold withholds "
            + ", ".join(derived_only)
            + " and the hand set does not.  This direction is conservative "
            "rather than unsafe, but flipping it would fall builds back for a "
            "reason the build-level gate never owned, so it is a declared "
            "widening and not a substitution."
        )
    return tuple(clauses) + _undeclared_base_blocker()


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
        "declaring": sorted(name for name in members if catalog.behavior_rules(name)),
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
    return failures


def _compiled_walk_delta_failures(
    committed: Mapping[str, Any], fresh: Mapping[str, Any]
) -> list[str]:
    """The derivation-beside-legacy block, gated by set equality (D-40, D-98).

    Fails closed: a receipt with the section deleted is a failure and not a
    skipped check, so the gate cannot be disarmed by removing what it reads.
    """
    recorded = committed.get("compiled_walk_delta")
    if not isinstance(recorded, Mapping):
        failures = [
            "compiled-walk delta: the committed receipt has no "
            "compiled_walk_delta section; run --write"
        ]
        return failures
    measured = fresh["compiled_walk_delta"]
    failures = []
    for key in ("legacy", "legacy_only", "derived_only"):
        if set(recorded.get(key, ())) != set(measured[key]):
            failures.append(
                f"compiled-walk delta: {key} differs from the committed set "
                f"(committed-only={sorted(set(recorded.get(key, ())) - set(measured[key]))}, "
                f"measured-only={sorted(set(measured[key]) - set(recorded.get(key, ())))})"
            )
    if set(recorded.get("derived", {})) != set(measured["derived"]):
        failures.append(
            "compiled-walk delta: the derived owner set differs from the "
            "committed one"
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
        "compiled_walk_delta": compiled_walk_delta(),
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
    failures.extend(_unserved_lane_failures(committed, fresh))
    failures.extend(_zero_policy_failures(committed, fresh))
    failures.extend(_compiled_walk_delta_failures(committed, fresh))
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
        return 0
    if not args.json and not args.write:
        print(json.dumps(report.counters()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
