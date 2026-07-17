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
``path: old -> new`` and exits 1 on any difference, 0 when identical.
``metadata/git_head`` is excluded from comparison (it changes per commit).
Exceptions raised by the pipeline are captured as {"error": "Type: msg"}
snapshot values — a refactor turning a crash into a number (or vice versa)
shows up as a diff.

Usage:
    python scripts/golden_snapshot.py capture <outfile.json>
    python scripts/golden_snapshot.py compare <baseline.json>
"""

import argparse
import copy
import json
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.calculator.champions import _CHAMPION_MODULES, parse_champion_abilities
from src.calculator.data_fetcher import fetch_champion_data, fetch_item_data
from src.calculator.pipeline import FightParams, ONE_ROTATION_DURATION, run_fight
from src.calculator.stats import calculate_total_stats

STAT_LEVELS = (1, 11, 18)
ABILITY_LEVEL = 11
FIGHT_LEVELS = (11, 18)
PHYSICAL_BUILD = ["Kraken Slayer", "Infinity Edge", "Lord Dominik's Regards"]
MAGIC_BUILD = ["Luden's Echo", "Shadowflame", "Rabadon's Deathcap"]
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
    """Section 2: fights for the 12 registered champions, 3 builds x 2 levels.

    Each level holds the original one-rotation entries under the build keys,
    plus a "sustained" sibling (auto_attack_uptime=1.0, one_rotation=False,
    5s) that exercises auto-attack and on-hit item paths.
    """
    builds = {
        "no_items": [],
        "physical_build": _resolve_build(PHYSICAL_BUILD, items_by_name, substitutions),
        "magic_build": _resolve_build(MAGIC_BUILD, items_by_name, substitutions),
    }
    by_display_name = {data.get("name"): data for data in champions.values()}
    out = {}
    for display_name in sorted(_CHAMPION_MODULES):
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


def snapshot_metadata(champions, items, substitutions, sweep_error_count):
    """Section 4: patch, git HEAD, data-fetch timestamps, counts."""

    def meta_fetched_at(filename):
        meta_path = REPO_ROOT / "data" / f".{filename}.meta"
        return json.loads(meta_path.read_text(encoding="utf-8")).get("fetched_at")

    patches = {c.get("patchLastChanged") for c in champions.values()}
    patch = max(
        (p for p in patches if p),
        key=lambda p: [int(x) if x.isdigit() else -1 for x in p.split(".")],
        default=None,
    )
    git_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return {
        "patch_last_changed_max": patch,
        "git_head": git_head,
        "champions_fetched_at": meta_fetched_at("champions.json"),
        "items_fetched_at": meta_fetched_at("items.json"),
        "champion_count": len(champions),
        "registered_champion_count": len(_CHAMPION_MODULES),
        "item_count": len(items),
        "item_sweep_error_count": sweep_error_count,
        "build_substitutions": substitutions,
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
    return {
        "champion_baselines": snapshot_champion_baselines(champions),
        "registered_champion_fights": snapshot_registered_fights(
            champions, items_by_name, substitutions
        ),
        "item_sweep": item_sweep,
        "metadata": snapshot_metadata(champions, items, substitutions, sweep_errors),
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


def compare(baseline_path):
    baseline = json.loads(Path(baseline_path).read_text(encoding="utf-8"))
    current = build_snapshot()
    # git HEAD legitimately changes between commits; everything else must not.
    baseline.get("metadata", {}).pop("git_head", None)
    current.get("metadata", {}).pop("git_head", None)
    diffs = []
    diff_snapshots("", baseline, current, diffs)
    for line in diffs:
        print(line)
    if diffs:
        print(f"FAIL: {len(diffs)} difference(s) vs {baseline_path}")
        return 1
    print(f"OK: snapshot identical to {baseline_path}")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("capture").add_argument("outfile")
    commands.add_parser("compare").add_argument("baseline")
    args = parser.parse_args()
    if args.command == "capture":
        sys.exit(capture(args.outfile))
    sys.exit(compare(args.baseline))


if __name__ == "__main__":
    main()
