"""Full-coverage census gate for the full-coverage campaign.

Sweeps every champion x fight mode, every champion x legally-slotted item,
every champion x keystone, every certified-timeline item x enemy champion
(including a window long enough to outlive a Lifeline), every item on an
enemy, every comparison curve, and a named BIS sample — all through the real
pure payload boundaries (`calculate_payload`, `bis_payload`). Every refusal,
withhold, coarse source, or crash the sweep can reach is a frontier entry.

The campaign closes when the frontier is empty. Until then the receipt pins
the shrinking frontier.

A frontier entry that cannot be closed without inventing data is acknowledged
in ``docs/coverage-residue.json`` instead: one row per (champion, source),
carrying the cached sentence that describes the hits and what that sentence
fails to say. The gate then fails two ways, on an entry no row acknowledges
and on a row whose entry has stopped reproducing, so the list can neither grow
in silence nor outlive its cause.

The sweep is one champion per worker process (~180k payload cells; about a
minute on 16 cores, four on CI's).  ``--shard K/N`` sweeps every Nth champion
from K so CI can spread the job over N runners; ``check`` compares a shard
against the same cut of the committed receipt.

Usage:
    python scripts/coverage_census.py run                     # sweep + summary
    python scripts/coverage_census.py run --output docs/coverage-census.json
    python scripts/coverage_census.py check docs/coverage-census.json
    python scripts/coverage_census.py check docs/coverage-census.json --shard 1/4
"""

import argparse
import functools
import json
import multiprocessing
import sys
from collections.abc import Collection, Mapping
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.calculator import item_coverage, item_source
from src.calculator.bis import bis_payload
from src.calculator.calculate import calculate_payload
from src.calculator.role_quests import (
    SUPPORT_QUEST_UPGRADED_STAGE,
    support_quest_item_stage,
)
from src.calculator.rune_effects import resolve_rune, rune_catalog

LEVEL = 18
MODES = ("one_rotation", "time_based", "timed", "auto_only")
#: The windows the item axis crosses.  ``auto_only`` is covered by the
#: autos-off pair below rather than twice: with the flag set it casts
#: nothing, so its item surface is the auto stream's.
ITEM_WINDOWS = (
    ("timed", True),
    ("timed", False),
    ("one_rotation", True),
    ("time_based", True),
    ("auto_only", True),
)
#: The BIS axis is a named sample, not the full roster: one BIS request scores
#: the whole candidate pool, so the axis exists to catch endpoint-level crashes
#: and withhold notes, and a spread of archetypes reaches every scoring path.
BIS_SAMPLE = (
    "Vi",
    "Kai'Sa",
    "Karthus",
    "Taliyah",
    "Ahri",
    "Ashe",
    "Ziggs",
    "Vayne",
    "Darius",
    "Shen",
    "Yuumi",
    "Braum",
)
#: Fight long enough to outlive every Lifeline window after a mid-fight trigger.
EXPIRY_DURATION = 30.0


def _probe(fn, payload):
    try:
        return {"ok": True, "resp": fn(payload)}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 - a census records crashes, class apart
        return {"ok": False, "error": f"CRASH {type(exc).__name__}: {exc}"}


def _coverage(resp):
    cov = resp.get("timeline_coverage")
    if cov is None and resp.get("targets"):
        cov = resp["targets"][0]["result"].get("timeline_coverage")
    return cov or {}


def _coarse(result):
    if not result["ok"]:
        return set()
    return {str(s) for s in _coverage(result["resp"]).get("coarse_sources", [])}


def _slot_payload(
    record: Mapping[str, Any], role_default: str = ""
) -> dict[str, Any] | None:
    """Route one item into its legal slot and role state."""
    name = str(record.get("name", ""))
    payload = {"items": [name], "role": role_default}
    if "BOOTS" in record.get("rank", []):
        tier = int(record.get("tier", 0))
        if tier == 3:
            payload = {
                "boots": name,
                "items": [],
                "role": "mid",
                "role_quest_complete": True,
            }
        else:
            payload = {"boots": name, "items": [], "role": role_default}
        if tier not in (2, 3):
            return None  # tier-1 boots are unequippable by loadout design
    elif support_quest_item_stage(name) is not None:
        payload["role"] = "support"
        if support_quest_item_stage(name) == SUPPORT_QUEST_UPGRADED_STAGE:
            payload["role_quest_complete"] = True
    return payload


#: Frontier buckets keyed ``<champion>|...`` (or by the champion alone),
#: swept one champion per worker; and the buckets no champion owns, swept
#: once.  A shard holds its champions' buckets and, for shard 0, the global
#: ones, so ``restrict`` can cut the pinned receipt to the same shape.
CHAMPION_BUCKETS = (
    "mode_refusals",
    "attacker_kit_coarse",
    "item_pair_failures",
    "item_pair_coarse",
    "keystone_failures",
    "certified_enemy_withholds",
    "crossover_unavailable",
    "bis_errors",
)
GLOBAL_BUCKETS = ("keystone_unmodeled", "expiry_refusals", "enemy_item_entries")


def _timed_payload(champ, **extra):
    return {
        "champion": champ,
        "level": LEVEL,
        "items": [],
        "fight_mode": "timed",
        "include_auto_attacks": True,
        **extra,
    }


@functools.cache
def _catalog():
    """The populations every axis sweeps, read once per process."""
    champions = sorted(
        str(entry.get("name"))
        for entry in json.loads(
            (REPO_ROOT / "data" / "champions.json").read_text(encoding="utf-8")
        ).values()
    )
    raw_items = json.loads(
        (REPO_ROOT / "data" / "items.json").read_text(encoding="utf-8")
    )
    records = sorted(
        (item for item in raw_items.values() if item_source.is_ordinary_sr_item(item)),
        key=lambda item: str(item.get("name")),
    )
    # The rune axis: every rune the catalog offers must compile (minor runes
    # and keystones alike are refused at the request boundary otherwise),
    # and every keystone is additionally swept through a fight per champion.
    # Minor runes price through the same walker and are pinned per compiler
    # in tests/test_rune_paths_*.py; sweeping 173 x 45 fights here would cost
    # an hour for no new classification.
    roster = rune_catalog()
    compiled, unmodeled = [], []
    for name in (k["name"] for k in roster):
        try:
            resolve_rune(name)
            compiled.append(name)
        except ValueError:
            unmodeled.append(name)
    return {
        "champions": champions,
        "records": records,
        "keystones": [
            k["name"] for k in roster if k["row"] == 0 and k["name"] in compiled
        ],
        "compiled": sorted(compiled),
        "unmodeled": sorted(unmodeled),
        "certified_items": sorted(
            str(r.get("name"))
            for r in records
            if item_coverage.certified_target_mechanics(str(r.get("name")))
        ),
    }


def _champion_cells(champ):
    """Every frontier entry one champion can own."""
    cat = _catalog()
    cells = {bucket: {} for bucket in CHAMPION_BUCKETS}

    # 1. champion x mode, and the bare-kit timed baseline.
    baseline = set()
    for mode in MODES:
        r = _probe(calculate_payload, _timed_payload(champ, fight_mode=mode))
        if not r["ok"]:
            cells["mode_refusals"][f"{champ}|{mode}"] = r["error"]
        elif mode == "timed":
            baseline = _coarse(r)
            if baseline:
                cells["attacker_kit_coarse"][champ] = sorted(baseline)

    # 2. champion x legally-slotted item, across every window the interface can
    #    ask for.  A single mode with autos on is not "all modes with all
    #    items": an item can be coarse in one rotation and clean in a timed
    #    window, and turning the auto stream off changes which sources are
    #    active at all.  Each cell is compared against that champion's bare kit
    #    IN THE SAME WINDOW, so the entry is the item's contribution.
    for mode, autos in ITEM_WINDOWS:
        window = _timed_payload(champ, fight_mode=mode, include_auto_attacks=autos)
        base = _coarse(_probe(calculate_payload, window))
        for record in cat["records"]:
            slotted = _slot_payload(record)
            if slotted is None:
                continue
            r = _probe(calculate_payload, {**window, **slotted})
            key = f"{champ}|{record.get('name')}|{mode}|autos={autos}"
            if not r["ok"]:
                cells["item_pair_failures"][key] = r["error"]
            else:
                extra = sorted(_coarse(r) - base)
                if extra:
                    cells["item_pair_coarse"][key] = extra

    # 3. champion x compiled keystone.
    for keystone in cat["keystones"]:
        r = _probe(calculate_payload, _timed_payload(champ, keystone=keystone))
        key = f"{champ}|{keystone}"
        if not r["ok"]:
            cells["keystone_failures"][key] = r["error"]
        else:
            extra = sorted(_coarse(r) - baseline)
            if extra:
                cells["keystone_failures"][key] = f"coarse: {extra}"

    # 4. every certified-timeline item on this champion as the enemy.
    for item in cat["certified_items"]:
        r = _probe(
            calculate_payload,
            _timed_payload(
                "Ziggs",
                enemies=[{"champion": champ, "level": LEVEL, "items": [item]}],
            ),
        )
        if not r["ok"]:
            cells["certified_enemy_withholds"][f"{champ}|{item}"] = r["error"]

    # 6. comparison curve.
    r = _probe(
        calculate_payload,
        {"champion": champ, "level": LEVEL, "items": [], "include_crossover": True},
    )
    if not r["ok"]:
        cells["crossover_unavailable"][champ] = r["error"]
    else:
        status = r["resp"].get("comparison_curve_status") or {}
        if not r["resp"].get("comparison_curve") and not status.get("available", True):
            cells["crossover_unavailable"][champ] = str(
                status.get("reason", "curve absent")
            )

    # 7. BIS sample, both windows.
    if champ in BIS_SAMPLE:
        for mode in ("one_rotation", "timed"):
            r = _probe(
                bis_payload,
                _timed_payload(
                    champ, fight_mode=mode, include_auto_attacks=mode == "timed"
                ),
            )
            if not r["ok"]:
                cells["bis_errors"][f"{champ}|{mode}"] = r["error"]
    return cells


def _global_cells():
    """The frontier entries no champion owns."""
    cat = _catalog()
    cells = {bucket: {} for bucket in GLOBAL_BUCKETS}
    cells["keystone_unmodeled"] = list(cat["unmodeled"])

    # 4b. the expiry window outlives every Lifeline.
    for item in cat["certified_items"]:
        r = _probe(
            calculate_payload,
            _timed_payload(
                "Ziggs",
                fight_duration=EXPIRY_DURATION,
                enemies=[{"champion": "Shen", "level": LEVEL, "items": [item]}],
            ),
        )
        if not r["ok"]:
            cells["expiry_refusals"][item] = r["error"]

    # 5. every item on an enemy, legally slotted.
    bare = _coarse(_probe(calculate_payload, _timed_payload("Ziggs"))) | _coarse(
        _probe(calculate_payload, _timed_payload("Shen"))
    )
    for record in cat["records"]:
        slotted = _slot_payload(record)
        if slotted is None:
            continue
        enemy = {"champion": "Shen", "level": LEVEL, **slotted}
        r = _probe(calculate_payload, _timed_payload("Ziggs", enemies=[enemy]))
        name = str(record.get("name"))
        if not r["ok"]:
            cells["enemy_item_entries"][name] = r["error"]
        else:
            extra = sorted(_coarse(r) - bare)
            if extra:
                cells["enemy_item_entries"][name] = f"coarse: {extra}"
    return cells


def _shard_champions(shard):
    index, count = shard
    return _catalog()["champions"][index::count]


def _receipt(frontier):
    cat = _catalog()
    counts = {key: len(value) for key, value in frontier.items()}
    counts["total"] = sum(counts.values())
    return {
        "audit": "full_coverage_census",
        "champions": len(cat["champions"]),
        "items_swept": len(cat["records"]),
        "keystones": {"compiled": cat["compiled"], "unmodeled": cat["unmodeled"]},
        "certified_items": cat["certified_items"],
        "bis_sample": list(BIS_SAMPLE),
        "counts": counts,
        "frontier": frontier,
    }


def run_census(
    shard: tuple[int, int] = (0, 1), workers: int | None = None
) -> dict[str, Any]:
    """Sweep every axis (or one shard of the champions) and return the receipt.

    Champions are swept one per worker process; the global buckets are swept
    by shard 0 only.
    """
    frontier = {bucket: {} for bucket in CHAMPION_BUCKETS + GLOBAL_BUCKETS}
    frontier["keystone_unmodeled"] = []
    with multiprocessing.Pool(workers) as pool:
        parts = pool.map(_champion_cells, _shard_champions(shard), chunksize=1)
    if shard[0] == 0:
        parts.append(_global_cells())
    for cells in parts:
        for bucket, entries in cells.items():
            if isinstance(entries, dict):
                frontier[bucket].update(entries)
            else:
                frontier[bucket].extend(entries)
    return _receipt(frontier)


def restrict(receipt: Mapping[str, Any], shard: tuple[int, int]) -> dict[str, Any]:
    """The part of a full receipt that ``run_census(shard)`` reproduces."""
    mine = set(_shard_champions(shard))
    frontier = {
        bucket: {
            key: value
            for key, value in receipt["frontier"][bucket].items()
            if key.split("|", 1)[0] in mine
        }
        for bucket in CHAMPION_BUCKETS
    }
    for bucket in GLOBAL_BUCKETS:
        whole = receipt["frontier"][bucket]
        frontier[bucket] = whole if shard[0] == 0 else type(whole)()
    return _receipt(frontier)


RESIDUE_PATH = REPO_ROOT / "docs" / "coverage-residue.json"


def _residue_rows() -> list[dict[str, str]]:
    """The committed acknowledgements, or none if the file is absent."""
    if not RESIDUE_PATH.exists():
        return []
    return json.loads(RESIDUE_PATH.read_text(encoding="utf-8"))["acknowledged"]


def _frontier_pairs(frontier):
    """Every (champion, coarse source) the sweep still reports."""
    pairs = set()
    for key, sources in frontier["item_pair_coarse"].items():
        champion = key.split("|", 1)[0]
        for source in sources:
            pairs.add((champion, source))
    return pairs


def reconcile_residue(
    receipt: Mapping[str, Any], champions: Collection[str] | None = None
) -> dict[str, int | list[str]]:
    """Split the frontier into acknowledged rows and unacknowledged entries.

    Two failures, not one. An entry nothing acknowledges is the frontier
    proper, work still open. A row whose entry has stopped reproducing is an
    acknowledgement that outlived its cause, which is how a list of known gaps
    quietly becomes a list of forgotten ones.  A shard's receipt is judged
    against the rows for its ``champions`` only.
    """
    rows = _residue_rows()
    if champions is not None:
        rows = [row for row in rows if row["champion"] in champions]
    acknowledged = {(row["champion"], row["source"]) for row in rows}
    live = _frontier_pairs(receipt["frontier"])
    return {
        "acknowledged_rows": len(rows),
        "unacknowledged": sorted(f"{c}|{s}" for c, s in live - acknowledged),
        "stale_acknowledgements": sorted(f"{c}|{s}" for c, s in acknowledged - live),
    }


def _shard(text):
    index, count = (int(part) for part in text.split("/"))
    if not 0 <= index < count:
        raise argparse.ArgumentTypeError(f"shard {text} is not K/N with 0 <= K < N")
    return index, count


def main(argv: list[str]) -> int:
    """CLI: ``run [--output PATH]`` or ``check PATH``; exit 1 on any frontier."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("command", choices=("run", "check"))
    parser.add_argument("path", nargs="?", type=Path, help="receipt to check")
    parser.add_argument("--output", type=Path, help="write the receipt here")
    parser.add_argument(
        "--shard",
        type=_shard,
        default=(0, 1),
        metavar="K/N",
        help="sweep only every Nth champion from K (shard 0 also sweeps the "
        "global buckets); check compares against the same cut of the receipt",
    )
    parser.add_argument("--workers", type=int, help="processes (default: all CPUs)")
    args = parser.parse_args(argv)
    if args.command == "check" and args.path is None:
        parser.error("check needs the receipt path")

    receipt = run_census(args.shard, args.workers)
    total = receipt["counts"]["total"]
    if args.command == "run":
        if args.output:
            args.output.write_text(
                json.dumps(receipt, indent=1, sort_keys=True) + "\n", encoding="utf-8"
            )
            print(f"receipt -> {args.output}")
    else:
        pinned = json.loads(args.path.read_text(encoding="utf-8"))
        if restrict(pinned, args.shard) != receipt:
            print("STALE: committed receipt does not match a fresh census run")
            return 1
    if args.shard != (0, 1):
        print(f"shard {args.shard[0]}/{args.shard[1]}")
    for key, count in receipt["counts"].items():
        if key != "total":
            print(f"{key}: {count}")
    print(f"frontier total: {total}")

    residue = reconcile_residue(receipt, set(_shard_champions(args.shard)))
    print(f"acknowledged residue rows: {residue['acknowledged_rows']}")
    for entry in residue["unacknowledged"]:
        print(f"UNACKNOWLEDGED: {entry}")
    for entry in residue["stale_acknowledgements"]:
        print(f"STALE ACKNOWLEDGEMENT (no longer reproduces): {entry}")
    if residue["unacknowledged"] or residue["stale_acknowledgements"]:
        return 1
    other = total - sum(
        len(sources) for sources in receipt["frontier"]["item_pair_coarse"].values()
    )
    return 0 if other == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
