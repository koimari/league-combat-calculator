"""Golden snapshot harness for the July 2026 refactor campaign (Phase 0).

Captures the numeric behavior of the full calculation pipeline (stats ->
ability parsing -> fight damage) across every champion and item, so later
refactor phases can prove numeric equivalence. Fight scenarios enter through
``pipeline.run_fight`` just like the app and optimizer, with
``deterministic=True``. Fights cover both a
one-rotation burst (no autos) and, for registered champions, a sustained
scenario with auto_attack_uptime=1.0 so auto-attack and on-hit item paths
(Statikk, Voltaic, BorK, Kraken, Rageblade phantom hits, spellblade,
energized procs, Vayne W) are locked too; the item sweep runs with
auto_attack_uptime=1.0 for the same reason.

Compare contract: every float is rounded to 2 decimals before writing, and
``compare`` recomputes the snapshot with identical rounding — so "equal to
2 decimals" is plain equality.  ``compare`` prints each differing path as
``path: old -> new`` and exits 1 on any difference, 0 when identical.  The
provenance keys in ``COMPARE_EXCLUDED_PROVENANCE`` are excluded from the
comparison (they change per commit or per data pull); nothing else is.
Exceptions raised by the pipeline are captured as {"error": "Type: msg"}
snapshot values — a refactor turning a crash into a number (or vice versa)
shows up as a diff.

Two baselines, two jurisdictions (runbook R-11).  ``capture``/``compare``
own the **pair engine**: every scenario enters through ``pipeline.run_fight``,
so this snapshot proves no pair-engine leak and nothing about the coupled
roster walk.  ``capture-coupled``/``compare`` own the **roster path**: those
scenarios enter through ``scenario.resolve_scenario`` and
``participant_timeline.build_participant_timeline``, which is where item
support packets, cross-participant damage modifiers and the coupled ledger
live.  A slice touching those cites the coupled baseline, never this one.

Usage:
    python scripts/golden_snapshot.py capture <outfile.json>
    python scripts/golden_snapshot.py compare <baseline.json> [--report <path>]
    python scripts/golden_snapshot.py capture-coupled <outfile.json> [--exact]
    python scripts/golden_snapshot.py fingerprint <snapshot.json>
"""

import argparse
import copy
import json
import math
import subprocess
import sys
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.calculator.champions import (
    parse_champion_abilities,
    registered_champion_names,
)
from src.calculator.data_fetcher import fetch_champion_data, fetch_item_data
from src.calculator.defensive_effects import resolve_starting_defenses
from src.calculator.item_support_effects import (
    cross_participant_authorities,
    producer_item,
)
from src.calculator.participant_timeline import (
    CoupledSearchContext,
    build_participant_timeline,
)
from src.calculator.pipeline import FightParams, ONE_ROTATION_DURATION, run_fight
from src.calculator.public_response import serialize_fight_result
from src.calculator.scenario import parse_scenario_request, resolve_scenario
from src.calculator.stats import calculate_total_stats

FINGERPRINTS_PATH = REPO_ROOT / "docs" / "receipts" / "campaign-fingerprints.json"

# Metadata keys ``compare`` ignores.  ``git_head`` moves every commit, the
# ``src`` tree sha moves on a comment-only edit, and the two fetch stamps move
# on every data pull — without one named home for them, "zero diffs on a pure
# refactor" is false for every commit and the strongest gate in the campaign
# gets routinely waived (R-14).
COMPARE_EXCLUDED_PROVENANCE: frozenset[str] = frozenset(
    {"git_head", "src_tree_sha", "champions_fetched_at", "items_fetched_at"}
)

# ``fingerprint``'s domain is the numeric sections; ``metadata`` is excluded
# whole, because it carries exactly the provenance above plus counts derived
# from the sections themselves — counting it makes the published figure wrong
# on its first run.
FINGERPRINT_EXCLUDED_SECTIONS: frozenset[str] = frozenset({"metadata"})

STAT_LEVELS = (1, 11, 18)
ABILITY_LEVEL = 11
FIGHT_LEVELS = (11, 18)
PHYSICAL_BUILD = ["Kraken Slayer", "Infinity Edge", "Lord Dominik's Regards"]
MAGIC_BUILD = ["Luden's Echo", "Shadowflame", "Rabadon's Deathcap"]
# Spellblade + crit + attack speed: the only sweep build that exercises
# the spellblade proc path and champion riders on it (Corki's Hextech
# Munitions true damage). Without it those live on unit tests alone —
# the blind spot that hid the timed-burn bug.
SPELLBLADE_BUILD = ["Trinity Force", "Infinity Edge", "Berserker's Greaves"]
# Deliberately non-default regression scenario; product defaults live in pipeline.py.
SNAPSHOT_TARGET_HEALTH = 2000.0
SNAPSHOT_TARGET_ARMOR = 50.0
SNAPSHOT_TARGET_MR = 40.0


def _rounded(value):
    """Recursively round floats to 2 decimals and normalize containers."""
    if isinstance(value, bool) or value is None or isinstance(value, (int, str)):
        return value
    if isinstance(value, float):
        return round(value, 2)
    if isinstance(value, dict):
        return {str(k): _rounded(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_rounded(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_rounded(v) for v in value), key=str)
    return repr(value)


def _error_entry(exc):
    return {"error": f"{type(exc).__name__}: {exc}"}


def _default_target_stats():
    return {
        "target_max_health": SNAPSHOT_TARGET_HEALTH,
        "target_current_health": SNAPSHOT_TARGET_HEALTH,
        "target_missing_health": 0.0,
    }


def _parse_abilities_fresh(champion_data, level, items):
    """Mirror the app/optimizer pipeline up through parse_abilities.

    Deep-copies inputs (each web request re-reads data from disk, so every
    call sees fresh dicts) and returns (stats, ability_damages).
    """
    data = copy.deepcopy(champion_data)
    stats = calculate_total_stats(data, level, items)
    abilities = parse_champion_abilities(
        data,
        level,
        stats["ability_power"],
        ability_ranks=None,
        champion_stats=stats,
        target_stats=_default_target_stats(),
        champion_options=None,
    )
    return stats, abilities


def _run_fight(champion_data, level, items, auto_attack_uptime=0.0, one_rotation=True):
    """Fight at fixed regression target stats, mirroring _evaluate_build.

    Default is a one-rotation burst with no autos. Pass
    auto_attack_uptime=1.0 (and one_rotation=False for the sustained
    scenario) to exercise auto-attack and on-hit item paths.
    """
    items = copy.deepcopy(items)
    params = FightParams(
        target_health=SNAPSHOT_TARGET_HEALTH,
        target_bonus_health=0.0,
        target_armor=SNAPSHOT_TARGET_ARMOR,
        target_magic_resistance=SNAPSHOT_TARGET_MR,
        fight_duration_seconds=ONE_ROTATION_DURATION,
        auto_attack_uptime=auto_attack_uptime,
        one_rotation=one_rotation,
        include_actives=True,
        cast_order=None,
        auto_attacks_only=False,
        ability_ranks=None,
        champion_options=None,
        deterministic=True,
    )
    return run_fight(champion_data, level, items, params)


def _fight_summary(result):
    summary = {
        "total_damage": round(float(result.get("total_damage", 0.0)), 2),
        "breakdown_totals": {
            key: round(float(entry.get("total_damage", 0.0)), 2)
            for key, entry in result.get("breakdown", {}).items()
        },
    }
    if "dps" in result:
        summary["dps"] = round(float(result["dps"]), 2)
    return summary


def snapshot_champion_baselines(champions):
    """Section 1: stats at levels 1/11/18 and level-11 abilities, all champions."""
    out = {}
    for key in sorted(champions):
        data = champions[key]
        entry = {"stats": {}}
        for level in STAT_LEVELS:
            try:
                entry["stats"][str(level)] = _rounded(
                    calculate_total_stats(copy.deepcopy(data), level, [])
                )
            except Exception as exc:
                entry["stats"][str(level)] = _error_entry(exc)
        try:
            _, abilities = _parse_abilities_fresh(data, ABILITY_LEVEL, [])
            entry[f"abilities_level_{ABILITY_LEVEL}"] = _rounded(abilities)
        except Exception as exc:
            entry[f"abilities_level_{ABILITY_LEVEL}"] = _error_entry(exc)
        out[key] = entry
    return out


def _resolve_build(requested_names, items_by_name, substitutions):
    """Resolve build item names against cached data, logging missing names."""
    build = []
    for name in requested_names:
        used = name if name in items_by_name else None
        if used != name:
            substitutions.append({"requested": name, "used": used})
        if used is not None:
            build.append(items_by_name[used])
    return build


def snapshot_registered_fights(champions, items_by_name, substitutions):
    """Section 2: fights for every registered champion, 4 builds x 2 levels.

    Each level holds the original one-rotation entries under the build keys,
    plus a "sustained" sibling (auto_attack_uptime=1.0, one_rotation=False,
    5s) that exercises auto-attack and on-hit item paths.
    """
    builds = {
        "no_items": [],
        "physical_build": _resolve_build(PHYSICAL_BUILD, items_by_name, substitutions),
        "magic_build": _resolve_build(MAGIC_BUILD, items_by_name, substitutions),
        "spellblade_build": _resolve_build(
            SPELLBLADE_BUILD, items_by_name, substitutions
        ),
    }
    by_display_name = {data.get("name"): data for data in champions.values()}
    out = {}
    for display_name in registered_champion_names():
        levels = {}
        for level in FIGHT_LEVELS:
            fights = {"sustained": {}}
            for build_name, build_items in builds.items():
                champion_data = by_display_name[display_name]
                try:
                    fights[build_name] = _fight_summary(
                        _run_fight(champion_data, level, build_items)
                    )
                except Exception as exc:
                    fights[build_name] = _error_entry(exc)
                try:
                    fights["sustained"][build_name] = _fight_summary(
                        _run_fight(
                            champion_data,
                            level,
                            build_items,
                            auto_attack_uptime=1.0,
                            one_rotation=False,
                        )
                    )
                except Exception as exc:
                    fights["sustained"][build_name] = _error_entry(exc)
            levels[str(level)] = fights
        out[display_name] = levels
    return out


def snapshot_item_sweep(champions, items):
    """Section 3: every item, alone, at level 11, on Vayne and Ahri.

    Runs one-rotation with auto_attack_uptime=1.0 — most item effects
    (on-hit, energized, spellblade) only fire with autos, and this sweep
    exists to lock per-item behavior.
    """
    by_display_name = {data.get("name"): data for data in champions.values()}
    sweep_champions = [
        ("ahri", by_display_name["Ahri"]),
        ("vayne", by_display_name["Vayne"]),
    ]
    out = {}
    for item in sorted(items.values(), key=lambda i: i.get("name", "")):
        entry = {}
        for label, champion_data in sweep_champions:
            try:
                result = _run_fight(
                    champion_data, ABILITY_LEVEL, [item], auto_attack_uptime=1.0
                )
                entry[label] = {
                    "total_damage": round(float(result.get("total_damage", 0.0)), 2),
                    "breakdown_keys": sorted(result.get("breakdown", {})),
                }
            except Exception as exc:
                entry[label] = _error_entry(exc)
        out[item.get("name", "")] = entry
    return out


def _git(*args):
    """One git command's stdout, or "" when git rejects the request."""
    result = subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _meta_fetched_at(filename):
    meta_path = REPO_ROOT / "data" / f".{filename}.meta"
    return json.loads(meta_path.read_text(encoding="utf-8")).get("fetched_at")


def snapshot_provenance():
    """Exactly the keys ``compare`` excludes — one producer, one exclusion set."""
    return {
        "git_head": _git("rev-parse", "HEAD"),
        "src_tree_sha": _git("rev-parse", "HEAD:src"),
        "champions_fetched_at": _meta_fetched_at("champions.json"),
        "items_fetched_at": _meta_fetched_at("items.json"),
    }


def snapshot_metadata(champions, items, substitutions, sweep_error_count, sections):
    """Section 4: patch, provenance, counts, and the shape fingerprint.

    The fingerprint block is computed by ``fingerprint_counts`` over the
    numeric sections — the same function ``fingerprint`` prints — so the
    receipt figure and every consumer's figure are one number by
    construction.
    """
    patches = {c.get("patchLastChanged") for c in champions.values()}
    patch = max(
        (p for p in patches if p),
        key=lambda p: [int(x) if x.isdigit() else -1 for x in p.split(".")],
        default=None,
    )
    return {
        "patch_last_changed_max": patch,
        "snapshot_kind": PAIR_SNAPSHOT_KIND,
        **snapshot_provenance(),
        "champion_count": len(champions),
        "registered_champion_count": len(registered_champion_names()),
        "item_count": len(items),
        "item_sweep_error_count": sweep_error_count,
        "build_substitutions": substitutions,
        "fingerprint": fingerprint_counts(sections),
    }


def build_snapshot():
    """Compute the full golden snapshot as a plain-JSON-serializable dict."""
    champions = fetch_champion_data()
    items = fetch_item_data()
    items_by_name = {data["name"]: data for data in items.values()}
    substitutions = []
    item_sweep = snapshot_item_sweep(champions, items)
    sweep_errors = sum(
        1 for entry in item_sweep.values() for side in entry.values() if "error" in side
    )
    sections = {
        "champion_baselines": snapshot_champion_baselines(champions),
        "registered_champion_fights": snapshot_registered_fights(
            champions, items_by_name, substitutions
        ),
        "item_sweep": item_sweep,
    }
    return {
        **sections,
        "metadata": snapshot_metadata(
            champions, items, substitutions, sweep_errors, sections
        ),
    }


# ---------------------------------------------------------------------------
# Fingerprint — the one home of every golden shape figure
# ---------------------------------------------------------------------------

PAIR_SNAPSHOT_KIND = "pair"
COUPLED_SNAPSHOT_KIND = "coupled"

# The shape figures ``fingerprint`` publishes.  ``metadata['fingerprint']``
# carries exactly these, from this same function.
FINGERPRINT_COUNT_FIELDS = ("sections", "entries", "leaves", "numeric_leaves")


def numeric_sections(snapshot):
    """Every top-level section ``fingerprint`` counts — ``metadata`` excluded."""
    return {
        key: value
        for key, value in snapshot.items()
        if key not in FINGERPRINT_EXCLUDED_SECTIONS
    }


def _count_leaves(value):
    """(leaves, numeric_leaves) under one node; a leaf is any non-container."""
    if isinstance(value, Mapping):
        totals = [_count_leaves(item) for item in value.values()]
    elif isinstance(value, (list, tuple)):
        totals = [_count_leaves(item) for item in value]
    else:
        numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
        return 1, int(numeric)
    return sum(pair[0] for pair in totals), sum(pair[1] for pair in totals)


def fingerprint_counts(sections):
    """The shape figures for one set of numeric sections."""
    leaves, numeric = _count_leaves(sections)
    return {
        "sections": ",".join(sorted(sections)),
        "entries": sum(len(value) for value in sections.values()),
        "leaves": leaves,
        "numeric_leaves": numeric,
    }


def fingerprint(snapshot):
    """The leaf/entry counts plus ``src_tree_sha`` — the one source of those figures.

    Domain: the numeric sections only.  ``metadata`` is excluded, because it
    holds the provenance keys ``compare`` already pops plus the counts this
    function produced; counting them makes the published figure wrong on its
    first run.  ``excluded_metadata`` reports which provenance keys the
    snapshot actually carries, so a test can assert that set is exactly
    ``COMPARE_EXCLUDED_PROVENANCE`` and the two exclusions cannot drift apart.
    """
    metadata = snapshot.get("metadata", {})
    return {
        **fingerprint_counts(numeric_sections(snapshot)),
        "snapshot_kind": str(metadata.get("snapshot_kind", PAIR_SNAPSHOT_KIND)),
        "excluded_metadata": ",".join(
            sorted(set(metadata) & COMPARE_EXCLUDED_PROVENANCE)
        ),
        "src_tree_sha": str(metadata.get("src_tree_sha", "")),
    }


# ---------------------------------------------------------------------------
# Classified diffs — R-15's triage, not an eyeball
# ---------------------------------------------------------------------------

Transition = Literal[
    "value",
    "zero_to_value",
    "value_to_zero",
    "value_to_error",
    "error_to_value",
    "absent_to_value",
    "value_to_absent",
    "text_change",
]

# A leaf whose path names damage: the sections differ between the two
# baselines, so the rule is stated over the path rather than the section.
DAMAGE_LEAF_TOKENS = ("damage", "dps", "breakdown_totals")

# R-15's thresholds.
INVESTIGATION_PERCENT = 10.0
INVESTIGATION_DAMAGE_ABS_DELTA = 1.0
# A slice owes an investigator on its largest-|abs_delta| leaf per scenario
# once its differing-leaf count clears this fraction of the numeric leaves.
INVESTIGATION_LEAF_RATIO = 0.01


class _Absent:  # pylint: disable=too-few-public-methods
    """The sentinel a missing key compares as; never a snapshot value."""

    def __repr__(self):
        return "<absent>"


ABSENT = _Absent()


@dataclass(frozen=True, slots=True)
class LeafDiff:
    """One differing golden leaf, classified for triage."""

    path: str
    section: str
    old: float | str | None
    new: float | str | None
    abs_delta: float
    percent: float
    transition: Transition


def _is_error(value):
    return isinstance(value, Mapping) and set(value) == {"error"}


def _numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _classify(old, new):
    """(transition, abs_delta, percent) for one pair of differing leaf values."""
    if old is ABSENT:
        return "absent_to_value", 0.0, math.inf
    if new is ABSENT:
        return "value_to_absent", 0.0, math.inf
    if _is_error(new):
        return "value_to_error", 0.0, math.inf
    if _is_error(old):
        return "error_to_value", 0.0, math.inf
    if _numeric(old) and _numeric(new):
        delta = abs(float(new) - float(old))
        if float(old) == 0.0:
            return "zero_to_value", delta, math.inf
        if float(new) == 0.0:
            return "value_to_zero", delta, -100.0
        return "value", delta, (float(new) - float(old)) / abs(float(old)) * 100.0
    return "text_change", 0.0, math.inf


def _leaf_diffs(path, old, new, out):
    """Collect one LeafDiff per differing leaf, recursing through containers."""
    if _is_error(old) != _is_error(new):
        out.append(_leaf_diff(path, old, new))
        return
    if isinstance(old, Mapping) and isinstance(new, Mapping):
        for key in sorted(set(old) | set(new)):
            _leaf_diffs(
                f"{path}/{key}", old.get(key, ABSENT), new.get(key, ABSENT), out
            )
        return
    if isinstance(old, list) and isinstance(new, list):
        for index in range(max(len(old), len(new))):
            _leaf_diffs(
                f"{path}[{index}]",
                old[index] if index < len(old) else ABSENT,
                new[index] if index < len(new) else ABSENT,
                out,
            )
        return
    if old is ABSENT or new is ABSENT or old != new:
        # A container facing a scalar is a shape change, reported once at the
        # node rather than fanned out into leaves that have no counterpart.
        out.append(_leaf_diff(path, old, new))


def _leaf_diff(path, old, new):
    transition, abs_delta, percent = _classify(old, new)
    return LeafDiff(
        path=path,
        section=path.lstrip("/").split("/", 1)[0],
        old=None if old is ABSENT else _reportable(old),
        new=None if new is ABSENT else _reportable(new),
        abs_delta=abs_delta,
        percent=percent,
        transition=transition,
    )


def _reportable(value):
    """A JSON-safe rendering of one leaf value for the report."""
    if _numeric(value) or isinstance(value, str) or value is None:
        return value
    return _format_value(value)


def leaf_report(old, new):
    """Every difference as a LeafDiff, grouped by scenario, sorted by |percent|."""
    diffs = []
    _leaf_diffs("", old, new, diffs)
    return tuple(sorted(diffs, key=lambda d: (d.section, -abs(d.percent), d.path)))


def qualifies_for_investigation(diff):
    """R-15's threshold — the one predicate that decides an investigator is owed."""
    if diff.transition != "value":
        return True
    if abs(diff.percent) > INVESTIGATION_PERCENT:
        return True
    return diff.abs_delta > INVESTIGATION_DAMAGE_ABS_DELTA and any(
        token in diff.path for token in DAMAGE_LEAF_TOKENS
    )


def receipt_numeric_leaves(kind):
    """The numeric-leaf denominator R-15's ratio clause reads from the receipt.

    Never a figure written in a document: the receipt is the sole home of
    every golden shape count, and this returns ``None`` when it has not been
    captured yet rather than substituting one.
    """
    if not FINGERPRINTS_PATH.exists():
        return None
    receipt = json.loads(FINGERPRINTS_PATH.read_text(encoding="utf-8"))
    block = receipt.get("golden" if kind == PAIR_SNAPSHOT_KIND else "coupled_golden")
    value = (block or {}).get("numeric_leaves")
    if isinstance(value, Mapping):
        value = value.get("value")
    return value if isinstance(value, int) else None


# ---------------------------------------------------------------------------
# The coupled roster baseline — the jurisdiction golden cannot see (R-11, R-12)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CoupledScenario:
    """One roster request captured through the coupled path.

    ``score_mode`` selects the scoring subset (``include_receipt=False``),
    which is how the optimizer evaluates a candidate and the only way the
    snapshot reaches the *tuple* damage ledger; the receipt mode reaches the
    dict ledger.  Both ledger shapes are therefore covered by scenarios, not
    by assumption.
    """

    name: str
    request: Mapping[str, Any]
    score_mode: bool = False

    def equipped(self):
        """Every item name this scenario puts on any participant."""
        names = set()
        for loadout in (
            self.request,
            *self.request.get("enemies", ()),
            *self.request.get("allies", ()),
        ):
            names.update(str(name) for name in loadout.get("items", ()))
            if loadout.get("boots"):
                names.add(str(loadout["boots"]))
        return frozenset(names)


# The Syndra cast-order pin: one parameter set, three splinter counts.  The
# splinter count is load-bearing — Q's second charge arrives at 40 stacks and
# W's bonus true damage at 60 — so a pin without that axis is ambiguous.  This
# scenario definition is the ONE home of the parameter set; the totals live in
# the committed baseline, and every consumer runs the scenario by name and
# reads that file rather than retyping a figure.
SYNDRA_PIN_SPLINTERS = (39, 60, 120)
SYNDRA_PIN_ITEMS = (
    "Luden's Echo",
    "Shadowflame",
    "Banshee's Veil",
    "Zhonya's Hourglass",
    "Void Staff",
    "Mejai's Soulstealer",
)
# 600 ability power and 10 ability haste exactly, at level 18: the haste is
# what puts Q's recast at 5.0 s and W's at 7.273 s, and no covered build
# reaches 600 AP without Mejai's stack option carrying the last 65.
SYNDRA_PIN_ITEM_OPTIONS = {"Mejai's Soulstealer": {"glory_stacks": 13}}
SYNDRA_PIN_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
SYNDRA_CUSTOM_ORDER = ["Q", "W", "E", "R"]


def _syndra_pin_request(splinters, *, cast_order):
    """One Syndra pin request: level 18, 600 AP, 10 AH, 12 s, 10000 HP target.

    The ally carries the same request so the roster loadout's own cast-order
    validation is on the captured path too, not only the main champion's.
    """
    ally = {
        "champion": "Syndra",
        "level": 18,
        "items": [],
        "ability_ranks": dict(SYNDRA_PIN_RANKS),
        "champion_options": {"splinters": splinters},
        "ally_effects_enabled": True,
    }
    request = {
        "champion": "Syndra",
        "level": 18,
        "items": list(SYNDRA_PIN_ITEMS),
        "item_options": {
            item: dict(options) for item, options in SYNDRA_PIN_ITEM_OPTIONS.items()
        },
        "fight_mode": "time_based",
        "fight_duration": 12,
        "target_health": 10000,
        "target_armor": 0,
        "target_mr": 0,
        "ability_ranks": dict(SYNDRA_PIN_RANKS),
        "champion_options": {"splinters": splinters},
        "allies": [ally],
    }
    if cast_order is not None:
        request["cast_order"] = list(cast_order)
        ally["cast_order"] = list(cast_order)
    return request


def _syndra_pin_scenarios():
    """``syndra_custom_order`` and ``syndra_derived_order`` at each splinter count."""
    scenarios = []
    for splinters in SYNDRA_PIN_SPLINTERS:
        scenarios.append(
            CoupledScenario(
                f"syndra_custom_order_{splinters}",
                _syndra_pin_request(splinters, cast_order=SYNDRA_CUSTOM_ORDER),
            )
        )
        scenarios.append(
            CoupledScenario(
                f"syndra_derived_order_{splinters}",
                _syndra_pin_request(splinters, cast_order=None),
            )
        )
    return tuple(scenarios)


def _roster_request(champion, items, *, enemies, allies, **extra):
    """A time-based roster request with the fields every scenario shares."""
    request = {
        "champion": champion,
        "level": 18,
        "items": list(items),
        "fight_mode": "time_based",
        "fight_duration": 8,
        "enemies": [{"champion": name, "level": 18, "items": []} for name in enemies],
        "allies": [
            {
                "champion": name,
                "level": 18,
                "items": [],
                "ally_effects_enabled": True,
            }
            for name in allies
        ],
    }
    request.update(extra)
    return request


COUPLED_SCENARIOS = (
    # Three cross-participant producers on one holder, with an ally to price
    # and an authored charm to arm Command.
    CoupledScenario(
        "mandate_abyssal_curse_roster",
        _roster_request(
            "Ahri",
            ("Imperial Mandate", "Abyssal Mask", "Bloodletter's Curse"),
            enemies=("Aatrox",),
            allies=("Pantheon",),
        ),
    ),
    # The two stack-ledger producers: Carve reads physical damage, Expose
    # Weakness rides a spellblade proc, so this build attacks.
    CoupledScenario(
        "cleaver_bloodsong_roster",
        _roster_request(
            "Jax",
            ("Black Cleaver", "Bloodsong"),
            enemies=("Aatrox",),
            allies=("Lulu",),
            role="support",
            role_quest_complete=True,
            include_auto_attacks=True,
            auto_attack_uptime=1.0,
        ),
    ),
    # The sixth producer: Blue Dream Bubble rides the holder's own authored
    # shield onto an ally, and declares no owner.
    CoupledScenario(
        "dream_maker_roster",
        _roster_request(
            "Lulu",
            ("Dream Maker",),
            enemies=("Aatrox",),
            allies=("Jax",),
            role="support",
            role_quest_complete=True,
        ),
    ),
    # The cross-pass roster: Catalyst's Eternity restores are an external,
    # timestamped input the walk consumes on a second pass.
    CoupledScenario(
        "catalyst_roster",
        _roster_request(
            "Ahri",
            ("Catalyst of Aeons",),
            enemies=("Aatrox", "Malphite"),
            allies=("Pantheon",),
        ),
    ),
    # Both damage-ledger shapes, in score mode.  A score-only fight takes the
    # light positional *tuple* rows unless something held needs the enriched
    # dict view; the three scenarios below sit on either side of that gate and
    # on the seam between them.
    #
    # 1. Nothing held reads the event stream: tuple rows.
    CoupledScenario(
        "score_plain_tuple",
        _roster_request(
            "Annie",
            ("Luden's Echo",),
            enemies=("Aatrox",),
            allies=("Pantheon",),
        ),
        score_mode=True,
    ),
    # 2. A holder that scans the per-event *view* but not the damage stream.
    #    Today the gate does not notice, so its scan is handed tuple rows —
    #    the starvation C1 corrects, visible here as a coupled diff.
    CoupledScenario(
        "score_event_view_holder",
        _roster_request(
            "Annie",
            ("Luden's Echo", "Imperial Mandate"),
            enemies=("Aatrox",),
            allies=("Pantheon",),
        ),
        score_mode=True,
    ),
    # 3. A holder that scans the damage stream: dict rows, before and after.
    CoupledScenario(
        "score_event_scan_holder",
        _roster_request(
            "Annie",
            ("Luden's Echo", "Black Cleaver"),
            enemies=("Aatrox",),
            allies=("Pantheon",),
        ),
        score_mode=True,
    ),
    *_syndra_pin_scenarios(),
)


def _uncovered_producers(scenarios, producers):
    """Producers no scenario equips the item for — R-12's derived coverage."""
    equipped = frozenset().union(*(s.equipped() for s in scenarios))
    return tuple(sorted(p for p in producers if producer_item(p) not in equipped))


def _coupled_receipt(parsed, resolved, *, score_mode):
    """The coupled participant receipt, mirroring calculate's own composition."""
    params = resolved.fight_params
    main_stats = calculate_total_stats(
        resolved.champion_data,
        parsed.level,
        list(resolved.items),
        item_options=params.item_options,
        role=params.role,
        role_quest_complete=params.role_quest_complete,
        external_stat_bonuses=params.ally_stat_bonuses,
    )
    return build_participant_timeline(
        resolved.champion_data,
        parsed.level,
        list(resolved.items),
        params,
        main_stats=main_stats,
        main_defenses=resolve_starting_defenses(
            resolved.champion_data["name"],
            parsed.level,
            main_stats,
            list(resolved.items),
            item_options=params.item_options,
        ),
        enemies=list(resolved.enemies),
        allies=list(resolved.allies),
        include_receipt=not score_mode,
        # Score mode is the optimizer's own composition: a search context
        # opts the walk into the compiled panels, which is the only way a
        # snapshot reaches the tuple damage ledger.  A build the compiler
        # cannot represent falls back to the receipt walk and its dict rows,
        # which is the other ledger shape and not an error.
        search_context=CoupledSearchContext() if score_mode else None,
        pair_result_cache={} if score_mode else None,
    )


def coupled_entry(scenario):
    """One scenario's raw (unrounded) fights and coupled receipt."""
    parsed = parse_scenario_request(dict(scenario.request), deterministic=True)
    resolved = resolve_scenario(parsed)
    fights = {}
    if not resolved.enemies:
        fights["manual_target"] = serialize_fight_result(
            run_fight(
                resolved.champion_data,
                parsed.level,
                list(resolved.items),
                resolved.fight_params,
            )
        )
    else:
        for index, (enemy, target_params) in enumerate(
            zip(resolved.enemies, resolved.target_fight_params)
        ):
            fights[f"{index}:{enemy.champion_data['name']}"] = serialize_fight_result(
                run_fight(
                    resolved.champion_data,
                    parsed.level,
                    list(resolved.items),
                    target_params,
                )
            )
    return {
        "fights": fights,
        "combat": _coupled_receipt(parsed, resolved, score_mode=scenario.score_mode),
    }


def _exact_totals(entry):
    """Per-attacker totals at full precision — R-13's bit-exactness instrument.

    Golden equality is equality to two decimals, so a summation-order change
    under 0.005 per leaf is invisible to it.  These ``repr(float)`` strings
    are the only figures a bit-exactness claim may cite.
    """
    totals = {}
    for key, fight in entry["fights"].items():
        totals[f"fights/{key}"] = repr(float(fight.get("total_damage", 0.0)))
    for index, actor in enumerate(entry["combat"].get("breakdown", [])):
        # The index keeps the key unique for a roster-free scenario, whose
        # breakdown rows carry no participant id.
        participant = f"{index}:{actor.get('participant_id', '')}"
        totals[f"combat/{participant}/outgoing"] = repr(
            float(actor.get("total_damage", 0.0))
        )
        totals[f"combat/{participant}/incoming"] = repr(
            float(actor.get("incoming_damage", 0.0))
        )
    return totals


def capture_coupled(scenarios, *, producers, exact=False):
    """Roster snapshots through the coupled path, covering every producer.

    ``producers`` is read, never typed: it is
    ``item_support_effects.cross_participant_authorities()`` at 0A/0B and
    ``trigger_stream.CAPABILITIES`` from P2a (R-12), so a seventh
    ``damage_modifier`` producer with no covering scenario fails here rather
    than passing silently.  ``exact`` writes ``repr(float)`` per-attacker
    totals instead of the 2-decimal snapshot.
    """
    uncovered = _uncovered_producers(scenarios, producers)
    if uncovered:
        raise ValueError(
            "the coupled scenario set covers no holder of "
            + ", ".join(uncovered)
            + " — add a scenario equipping "
            + ", ".join(sorted({producer_item(p) for p in uncovered}))
            + " before capturing the baseline"
        )
    entries = {}
    for scenario in scenarios:
        raw = coupled_entry(scenario)
        entries[scenario.name] = _exact_totals(raw) if exact else _rounded(raw)
    sections = {"coupled_scenarios": entries}
    return {
        **sections,
        "metadata": {
            "snapshot_kind": COUPLED_SNAPSHOT_KIND,
            "exact": bool(exact),
            **snapshot_provenance(),
            "scenario_count": len(entries),
            "producer_count": len(producers),
            "fingerprint": fingerprint_counts(sections),
        },
    }


def _format_value(value):
    text = json.dumps(value, sort_keys=True, default=repr)
    return text if len(text) <= 120 else text[:117] + "..."


def diff_snapshots(path, old, new, diffs):
    """Recursively collect 'path: old -> new' strings for every difference."""
    if isinstance(old, dict) and isinstance(new, dict):
        for key in sorted(set(old) | set(new)):
            if key not in old:
                diffs.append(f"{path}/{key}: <absent> -> {_format_value(new[key])}")
            elif key not in new:
                diffs.append(f"{path}/{key}: {_format_value(old[key])} -> <absent>")
            else:
                diff_snapshots(f"{path}/{key}", old[key], new[key], diffs)
    elif isinstance(old, list) and isinstance(new, list):
        for index in range(max(len(old), len(new))):
            if index >= len(old):
                diffs.append(
                    f"{path}[{index}]: <absent> -> {_format_value(new[index])}"
                )
            elif index >= len(new):
                diffs.append(
                    f"{path}[{index}]: {_format_value(old[index])} -> <absent>"
                )
            else:
                diff_snapshots(f"{path}[{index}]", old[index], new[index], diffs)
    elif old != new:
        diffs.append(f"{path}: {_format_value(old)} -> {_format_value(new)}")


def capture(outfile):
    """Capture the pair-engine snapshot to ``outfile``."""
    started = time.perf_counter()
    snapshot = build_snapshot()
    Path(outfile).write_text(
        json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    meta = snapshot["metadata"]
    print(f"Captured snapshot -> {outfile}")
    print(
        f"  champions: {meta['champion_count']}  "
        f"registered: {meta['registered_champion_count']}  "
        f"items swept: {meta['item_count']}  "
        f"sweep errors: {meta['item_sweep_error_count']}"
    )
    print(f"  elapsed: {time.perf_counter() - started:.1f}s")
    return 0


def capture_coupled_file(outfile, *, exact=False):
    """Capture the coupled roster baseline (or its exact per-attacker totals)."""
    started = time.perf_counter()
    snapshot = capture_coupled(
        COUPLED_SCENARIOS, producers=cross_participant_authorities(), exact=exact
    )
    Path(outfile).write_text(
        json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    meta = snapshot["metadata"]
    print(f"Captured coupled snapshot -> {outfile}")
    print(
        f"  scenarios: {meta['scenario_count']}  "
        f"producers covered: {meta['producer_count']}  "
        f"exact: {meta['exact']}"
    )
    print(f"  elapsed: {time.perf_counter() - started:.1f}s")
    return 0


def rebuild_for(baseline):
    """Recompute the snapshot a baseline is a capture of, in its own mode."""
    metadata = baseline.get("metadata", {})
    if metadata.get("snapshot_kind") != COUPLED_SNAPSHOT_KIND:
        return build_snapshot()
    return capture_coupled(
        COUPLED_SCENARIOS,
        producers=cross_participant_authorities(),
        exact=bool(metadata.get("exact", False)),
    )


def _write_report(path, diffs, kind):
    """One LeafDiff per differing leaf, plus the ratio clause's own arithmetic."""
    qualifying = [diff for diff in diffs if qualifies_for_investigation(diff)]
    denominator = receipt_numeric_leaves(kind)
    report = {
        "snapshot_kind": kind,
        "differing_leaves": len(diffs),
        "qualifying_leaves": len(qualifying),
        "numeric_leaves": denominator,
        "leaf_ratio": (len(diffs) / denominator) if denominator else None,
        "ratio_clause_triggered": (
            bool(denominator) and len(diffs) > INVESTIGATION_LEAF_RATIO * denominator
        ),
        "largest_abs_delta_per_section": {
            section: max(
                (d for d in diffs if d.section == section),
                key=lambda d: d.abs_delta,
            ).path
            for section in sorted({d.section for d in diffs})
        },
        "diffs": [asdict(diff) for diff in diffs],
    }
    Path(path).write_text(
        json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8"
    )
    return report


def compare(baseline_path, report_path=None):
    """Recompute the baseline's own snapshot and report every differing leaf."""
    baseline = json.loads(Path(baseline_path).read_text(encoding="utf-8"))
    kind = baseline.get("metadata", {}).get("snapshot_kind", PAIR_SNAPSHOT_KIND)
    current = rebuild_for(baseline)
    # Provenance legitimately changes between commits; everything else must not.
    for snapshot in (baseline, current):
        for key in COMPARE_EXCLUDED_PROVENANCE:
            snapshot.get("metadata", {}).pop(key, None)
    diffs = leaf_report(baseline, current)
    for diff in diffs:
        old = "<absent>" if diff.old is None else _format_value(diff.old)
        new = "<absent>" if diff.new is None else _format_value(diff.new)
        print(f"{diff.path}: {old} -> {new}")
    if report_path:
        report = _write_report(report_path, diffs, kind)
        print(
            f"  report -> {report_path} "
            f"({report['qualifying_leaves']} qualifying for investigation)"
        )
    if diffs:
        print(f"FAIL: {len(diffs)} difference(s) vs {baseline_path}")
        return 1
    print(f"OK: snapshot identical to {baseline_path}")
    return 0


def print_fingerprint(snapshot_path):
    """Print one snapshot's shape figures — the sole home of those numbers."""
    snapshot = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
    print(json.dumps(fingerprint(snapshot), indent=2, sort_keys=True))
    return 0


def main():
    """CLI entry point: capture | compare | capture-coupled | fingerprint."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("capture").add_argument("outfile")
    compare_parser = commands.add_parser("compare")
    compare_parser.add_argument("baseline")
    compare_parser.add_argument(
        "--report",
        default=None,
        help="write the classified LeafDiff report to this path (R-15)",
    )
    coupled = commands.add_parser("capture-coupled")
    coupled.add_argument("outfile")
    coupled.add_argument(
        "--exact",
        action="store_true",
        help="write repr(float) per-attacker totals instead of the 2-dp snapshot",
    )
    commands.add_parser("fingerprint").add_argument("snapshot")
    args = parser.parse_args()
    if args.command == "capture":
        sys.exit(capture(args.outfile))
    if args.command == "capture-coupled":
        sys.exit(capture_coupled_file(args.outfile, exact=args.exact))
    if args.command == "fingerprint":
        sys.exit(print_fingerprint(args.snapshot))
    sys.exit(compare(args.baseline, report_path=args.report))


if __name__ == "__main__":
    main()
