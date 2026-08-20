"""Full-coverage census gate for the full-coverage campaign.

Sweeps every champion x fight mode, every champion x legally-slotted item,
every champion x keystone, every certified-timeline item x enemy champion
(including a window long enough to outlive a Lifeline), every item on an
enemy, every comparison curve, and a named BIS sample — all through the real
pure payload boundaries (`calculate_payload`, `bis_payload`). Every refusal,
withhold, coarse source, or crash the sweep can reach is a frontier entry.

The campaign closes when the frontier is empty. Until then the receipt pins
the shrinking frontier.

A frontier entry the campaign cannot close without inventing data is
acknowledged in ``docs/coverage-residue.json`` instead — one row per
(champion, source), carrying the cached sentence that describes the hits and
what that sentence fails to say. The gate then fails two ways: on an entry no
row acknowledges, and on a row whose entry no longer reproduces, so the list
can neither grow in silence nor outlive its cause.

Usage:
    python scripts/coverage_census.py run                     # sweep + summary
    python scripts/coverage_census.py run --output docs/coverage-census.json
    python scripts/coverage_census.py check docs/coverage-census.json
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.calculator import item_coverage, item_source  # noqa: E402
from src.calculator.bis import bis_payload  # noqa: E402
from src.calculator.calculate import calculate_payload  # noqa: E402
from src.calculator.role_quests import (  # noqa: E402
    SUPPORT_QUEST_UPGRADED_STAGE,
    support_quest_item_stage,
)
from src.calculator.rune_effects import keystone_catalog, resolve_keystone  # noqa: E402

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


def _slot_payload(record, role_default=""):
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


def run_census():
    """Sweep every axis and return the frontier receipt."""
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
    keystones = [k["name"] for k in keystone_catalog()]
    compiled = []
    unmodeled = []
    for name in keystones:
        try:
            resolve_keystone(name)
            compiled.append(name)
        except ValueError:
            unmodeled.append(name)
    certified_items = sorted(
        str(r.get("name"))
        for r in records
        if item_coverage.certified_target_mechanics(str(r.get("name")))
    )

    frontier = {
        "mode_refusals": {},
        "attacker_kit_coarse": {},
        "item_pair_failures": {},
        "item_pair_coarse": {},
        "keystone_unmodeled": sorted(unmodeled),
        "keystone_failures": {},
        "certified_enemy_withholds": {},
        "expiry_refusals": {},
        "enemy_item_entries": {},
        "crossover_unavailable": {},
        "bis_errors": {},
    }

    def timed_payload(champ, **extra):
        return {
            "champion": champ,
            "level": LEVEL,
            "items": [],
            "fight_mode": "timed",
            "include_auto_attacks": True,
            **extra,
        }

    # 1. champion x mode, and a bare-kit baseline for every window the item
    #    axis will use.
    baselines = {}
    window_baselines = {}
    for champ in champions:
        for mode in MODES:
            r = _probe(
                calculate_payload,
                {
                    "champion": champ,
                    "level": LEVEL,
                    "items": [],
                    "fight_mode": mode,
                    "include_auto_attacks": True,
                },
            )
            if not r["ok"]:
                frontier["mode_refusals"][f"{champ}|{mode}"] = r["error"]
            elif mode == "timed":
                baselines[champ] = _coarse(r)
                if baselines[champ]:
                    frontier["attacker_kit_coarse"][champ] = sorted(baselines[champ])
        for mode, autos in ITEM_WINDOWS:
            r = _probe(
                calculate_payload,
                {
                    "champion": champ,
                    "level": LEVEL,
                    "items": [],
                    "fight_mode": mode,
                    "include_auto_attacks": autos,
                },
            )
            window_baselines[(champ, mode, autos)] = _coarse(r)

    # 2. champion x legally-slotted item, across every window the interface can
    #    ask for.  A single mode with autos on is not "all modes with all
    #    items": an item can be coarse in one rotation and clean in a timed
    #    window, and turning the auto stream off changes which sources are
    #    active at all.  Each cell is compared against that champion's bare kit
    #    IN THE SAME WINDOW, so the entry is the item's contribution.
    for champ in champions:
        for mode, autos in ITEM_WINDOWS:
            base = window_baselines[(champ, mode, autos)]
            for record in records:
                slotted = _slot_payload(record)
                if slotted is None:
                    continue
                payload = {
                    "champion": champ,
                    "level": LEVEL,
                    "items": [],
                    "fight_mode": mode,
                    "include_auto_attacks": autos,
                    **slotted,
                }
                r = _probe(calculate_payload, payload)
                key = f"{champ}|{record.get('name')}|{mode}|autos={autos}"
                if not r["ok"]:
                    frontier["item_pair_failures"][key] = r["error"]
                else:
                    extra = sorted(_coarse(r) - base)
                    if extra:
                        frontier["item_pair_coarse"][key] = extra

    # 3. champion x compiled keystone.
    for champ in champions:
        base = baselines.get(champ, set())
        for keystone in compiled:
            r = _probe(calculate_payload, timed_payload(champ, keystone=keystone))
            key = f"{champ}|{keystone}"
            if not r["ok"]:
                frontier["keystone_failures"][key] = r["error"]
            else:
                extra = sorted(_coarse(r) - base)
                if extra:
                    frontier["keystone_failures"][key] = f"coarse: {extra}"

    # 4. certified-timeline item on every enemy champion; plus the expiry window.
    for item in certified_items:
        for champ in champions:
            r = _probe(
                calculate_payload,
                timed_payload(
                    "Ziggs",
                    enemies=[{"champion": champ, "level": LEVEL, "items": [item]}],
                ),
            )
            if not r["ok"]:
                frontier["certified_enemy_withholds"][f"{champ}|{item}"] = r["error"]
        r = _probe(
            calculate_payload,
            timed_payload(
                "Ziggs",
                fight_duration=EXPIRY_DURATION,
                enemies=[{"champion": "Shen", "level": LEVEL, "items": [item]}],
            ),
        )
        if not r["ok"]:
            frontier["expiry_refusals"][item] = r["error"]

    # 5. every item on an enemy, legally slotted.
    for record in records:
        slotted = _slot_payload(record)
        if slotted is None:
            continue
        enemy = {"champion": "Shen", "level": LEVEL, **slotted}
        r = _probe(calculate_payload, timed_payload("Ziggs", enemies=[enemy]))
        name = str(record.get("name"))
        if not r["ok"]:
            frontier["enemy_item_entries"][name] = r["error"]
        else:
            extra = sorted(
                _coarse(r)
                - baselines.get("Ziggs", set())
                - baselines.get("Shen", set())
            )
            if extra:
                frontier["enemy_item_entries"][name] = f"coarse: {extra}"

    # 6. comparison curve per champion.
    for champ in champions:
        r = _probe(
            calculate_payload,
            {"champion": champ, "level": LEVEL, "items": [], "include_crossover": True},
        )
        if not r["ok"]:
            frontier["crossover_unavailable"][champ] = r["error"]
        else:
            status = r["resp"].get("comparison_curve_status") or {}
            if not r["resp"].get("comparison_curve") and not status.get(
                "available", True
            ):
                frontier["crossover_unavailable"][champ] = str(
                    status.get("reason", "curve absent")
                )

    # 7. BIS sample, both windows.
    for champ in BIS_SAMPLE:
        for mode in ("one_rotation", "timed"):
            r = _probe(
                bis_payload,
                {
                    "champion": champ,
                    "level": LEVEL,
                    "items": [],
                    "fight_mode": mode,
                    "include_auto_attacks": mode == "timed",
                },
            )
            if not r["ok"]:
                frontier["bis_errors"][f"{champ}|{mode}"] = r["error"]

    counts = {key: len(value) for key, value in frontier.items()}
    counts["total"] = sum(counts.values())
    return {
        "audit": "full_coverage_census",
        "champions": len(champions),
        "items_swept": len(records),
        "keystones": {"compiled": sorted(compiled), "unmodeled": sorted(unmodeled)},
        "certified_items": certified_items,
        "bis_sample": list(BIS_SAMPLE),
        "counts": counts,
        "frontier": frontier,
    }


RESIDUE_PATH = REPO_ROOT / "docs" / "coverage-residue.json"


def _residue_rows():
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


def reconcile_residue(receipt):
    """Split the frontier into acknowledged rows and unacknowledged entries.

    Two failures, not one. An entry nothing acknowledges is the frontier
    proper — the campaign's own work, unfinished. A row whose entry no longer
    reproduces is an acknowledgement that outlived its cause, which is how a
    list of known gaps quietly becomes a list of forgotten ones.
    """
    rows = _residue_rows()
    acknowledged = {(row["champion"], row["source"]) for row in rows}
    live = _frontier_pairs(receipt["frontier"])
    return {
        "acknowledged_rows": len(rows),
        "unacknowledged": sorted(f"{c}|{s}" for c, s in live - acknowledged),
        "stale_acknowledgements": sorted(f"{c}|{s}" for c, s in acknowledged - live),
    }


def main(argv):
    """CLI: ``run [--output PATH]`` or ``check PATH``; exit 1 on any frontier."""
    if argv and argv[0] in {"-h", "--help"}:
        print(__doc__)
        return 0
    if not argv or argv[0] not in {"run", "check"}:
        print(__doc__)
        return 2
    receipt = run_census()
    total = receipt["counts"]["total"]
    if argv[0] == "run":
        out_index = argv.index("--output") + 1 if "--output" in argv else None
        if out_index:
            path = Path(argv[out_index])
            path.write_text(
                json.dumps(receipt, indent=1, sort_keys=True) + "\n", encoding="utf-8"
            )
            print(f"receipt -> {path}")
    else:
        pinned = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
        if pinned != receipt:
            print("STALE: committed receipt does not match a fresh census run")
            return 1
    for key, count in receipt["counts"].items():
        if key != "total":
            print(f"{key}: {count}")
    print(f"frontier total: {total}")

    residue = reconcile_residue(receipt)
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
