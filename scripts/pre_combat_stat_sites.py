"""One pre-combat stat recipe, and every surface that reaches it.

The pre-combat stat surface once had three recipes: a roster card resolved
without `external_stat_bonuses`, the coupled capture without `rune_page`, and
the request path with both, so every omission read as a default rather than
as a decision.  The recipe has one home and the read off a request has one
home, and three rules hold the tree to them:

* every `calculate_total_stats` site is the recipe itself or a declared
  narrower surface, keyed on the callee so a caller that supplies no keyword
  at all is counted rather than defined away;
* a declared narrower surface stays narrow, passing none of the five build
  context keywords;
* the `FightParams` read answers every input of the recipe, so the recipe
  naming all five cannot be satisfied one call deeper by silence.

`scripts/` is scanned beside `src/calculator` because the drift this guards
against happened there: `golden_snapshot._coupled_receipt` calls itself a
mirror of the request path's composition, and a src-only scan is exactly the
reading under which it stayed one while missing an input.

    python scripts/pre_combat_stat_sites.py

`tests/test_architecture.py` calls this.
"""

from __future__ import annotations

import ast
import sys
from collections.abc import Mapping
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lint_report import report

ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = ROOT / "src" / "calculator"


# SC9: the pre-combat stat surface had three recipes -- a roster card
# resolved without `external_stat_bonuses`, the coupled capture without
# `rune_page`, the request path with both -- and every omission read as a
# default rather than as a decision.  The recipe now has one home and the
# read off a request has one home; these two names are what the guards below
# hold the tree to.
PRE_COMBAT_RECIPE_HOME = "calculator.stats.resolve_pre_combat_stats"
PRE_COMBAT_PARAMS_READ = "calculator.fight_params.FightParams.pre_combat_stats"

# The inputs that make a stat block a *build's* rather than a champion's.
BUILD_CONTEXT_KEYWORDS = frozenset(
    {
        "item_options",
        "role",
        "role_quest_complete",
        "external_stat_bonuses",
        "rune_page",
    }
)

# Every `calculate_total_stats` site that is deliberately NOT a participant's
# pre-combat surface, with the reason it is narrower.  Declared, because the
# first version of this guard counted a site only if it passed one of the five
# keywords -- under which a caller that omitted all five was definitionally
# invisible, and omitting inputs is precisely SC9's failure.  The guard below
# is keyed on the callee instead and is total: every site is the one recipe or
# is entered here.
#
# What these five share is that no request stands behind them.  Each is a
# reference parse over a fixed matrix or over champion data alone -- cached or
# captured on `(champion, data version)` with the level and build written into
# the harness -- so an input added to the participant recipe must NOT reach
# them: it would invalidate a cache key that never mentions a request, and
# move the golden's champion-baseline section on a change about neither.
NARROWER_STAT_SURFACES: Mapping[str, str] = {
    "calculator.ability_dps_matrix._matrix_dps_rows": (
        "the reference DPS matrix, cached on (champion, data version) and "
        "explicitly independent of the request's level and build"
    ),
    "calculator.champion_rotation_rule._canonical_kit_parse": (
        "the canonical full-kit parse the derived cast order is read off: "
        "level 11, no items, by construction"
    ),
    "cast_dependency_audit._parse": (
        "one cell of the audit's fixed MATRIX_LEVELS x MATRIX_BUILDS sweep"
    ),
    "golden_snapshot._parse_abilities_fresh": (
        "the ability parse of the golden's champion-baseline section, whose "
        "level and items are the section's own constants"
    ),
    "golden_snapshot.snapshot_champion_baselines": (
        "the golden's champion-baseline stats at levels 1/11/18 with no items"
    ),
    "swing_stream_audit.scan": (
        "the swing-stream gate's fixed parse: level 18, full ranks, no items"
    ),
}

# Every surface that composes a participant's stats as combat begins, and the
# helper it reaches the recipe through: the module function directly when it
# holds no request, the FightParams read when it does.
PRE_COMBAT_SURFACES: Mapping[str, str] = {
    "calculator.champion_loadout.ChampionLoadout.resolve": "resolve_pre_combat_stats",
    "calculator.calculate._combat_receipt": "pre_combat_stats",
    "calculator.build_evaluation._evaluate_build_uncached": "pre_combat_stats",
    "calculator.pipeline.run_fight": "pre_combat_stats",
    "golden_snapshot._coupled_receipt": "pre_combat_stats",
}


def called_name(node: ast.Call) -> str:
    """What one call expression spells, bare name or dotted attribute alike."""
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def calls_by_scope(path: Path, module: str) -> list[tuple[str, ast.Call]]:
    """Every call expression in one module, tagged with the def enclosing it."""
    found: list[tuple[str, ast.Call]] = []

    def visit(node: ast.AST, scope: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                visit(child, f"{scope}.{child.name}")
                continue
            if isinstance(child, ast.Call):
                found.append((scope, child))
            visit(child, scope)

    visit(ast.parse(path.read_text(encoding="utf-8")), module)
    return found


def scanned_scopes() -> list[tuple[str, ast.Call]]:
    """Calls in `src/calculator` and in the capture harnesses beside it.

    `scripts/` is scanned because the drift this guards against happened
    there: `golden_snapshot._coupled_receipt` calls itself a mirror of the
    request path's composition, and a src-only scan cannot see whether it
    is one.
    """
    scoped: list[tuple[str, ast.Call]] = []
    for path in sorted(SRC_ROOT.rglob("*.py"), key=lambda item: item.as_posix()):
        module = ".".join(path.relative_to(SRC_ROOT.parent).with_suffix("").parts)
        scoped.extend(calls_by_scope(path, module))
    for path in sorted((ROOT / "scripts").glob("*.py"), key=lambda item: item.name):
        scoped.extend(calls_by_scope(path, path.stem))
    return scoped


def stat_sites() -> dict[str, list[frozenset[str]]]:
    """Every `calculate_total_stats` site, by enclosing def, with its keywords.

    Keyed on the callee and nothing else, so a caller that supplies no
    keyword at all is counted rather than defined away.
    """
    sites: dict[str, list[frozenset[str]]] = {}
    for scope, call in scanned_scopes():
        if called_name(call) != "calculate_total_stats":
            continue
        supplied = frozenset(k.arg for k in call.keywords if k.arg)
        sites.setdefault(scope, []).append(supplied)
    return sites


def recipe_drift() -> list[str]:
    """Every stat composition that is neither the recipe nor declared."""
    sites = stat_sites()
    findings = []
    if sites.get(PRE_COMBAT_RECIPE_HOME) != [BUILD_CONTEXT_KEYWORDS]:
        findings.append(
            f"{PRE_COMBAT_RECIPE_HOME} composes "
            f"{sites.get(PRE_COMBAT_RECIPE_HOME)} rather than every input"
        )
    findings.extend(
        f"{scope} composes a stat block and is neither the recipe nor declared"
        for scope in sorted(set(sites) - {PRE_COMBAT_RECIPE_HOME})
        if scope not in NARROWER_STAT_SURFACES
    )
    findings.extend(
        f"{scope} is declared narrower but the tree no longer holds it"
        for scope in sorted(NARROWER_STAT_SURFACES)
        if scope not in sites
    )
    return findings


def widened_surfaces() -> list[str]:
    """Every declared narrower surface that has started taking build context."""
    sites = stat_sites()
    return [
        f"{scope} passes {sorted(supplied & BUILD_CONTEXT_KEYWORDS)}; "
        "it has stopped being a reference parse"
        for scope in sorted(NARROWER_STAT_SURFACES)
        for supplied in sites.get(scope, ())
        if supplied & BUILD_CONTEXT_KEYWORDS
    ]


def request_read_inputs() -> frozenset[str]:
    """The keywords the `FightParams` read hands the recipe."""
    reads = [
        call
        for scope, call in scanned_scopes()
        if scope == PRE_COMBAT_PARAMS_READ
        and called_name(call) == "resolve_pre_combat_stats"
    ]
    if len(reads) != 1:
        return frozenset()
    return frozenset(keyword.arg for keyword in reads[0].keywords)


def unrouted_surfaces() -> list[str]:
    """Every pre-combat surface that does not reach the recipe's helper."""
    routed: dict[str, set[str]] = {scope: set() for scope in PRE_COMBAT_SURFACES}
    for scope, call in scanned_scopes():
        if scope in routed:
            routed[scope].add(called_name(call))
    return [
        f"{scope} never calls {helper}"
        for scope, helper in PRE_COMBAT_SURFACES.items()
        if helper not in routed[scope]
    ]


def check() -> list[str]:
    """Every finding across the four rules."""
    findings = [*recipe_drift(), *widened_surfaces(), *unrouted_surfaces()]
    if request_read_inputs() != BUILD_CONTEXT_KEYWORDS:
        findings.append(
            f"{PRE_COMBAT_PARAMS_READ} hands the recipe "
            f"{sorted(request_read_inputs())}, not every input"
        )
    return findings


if __name__ == "__main__":
    raise SystemExit(report(check(), "OK: one pre-combat recipe, every surface on it"))
