"""Full-coverage census gate for the full-coverage campaign.

Sweeps every champion x fight mode, every champion x legally-slotted item,
every champion x keystone, every certified-timeline item x enemy champion
(including a window long enough to outlive a Lifeline), every item on an
enemy, every comparison curve, and a named BIS sample — all through the real
pure payload boundaries (`calculate_payload`, `bis_payload`). Every refusal,
withhold, coarse source, or crash the sweep can reach is a frontier entry.

The campaign closes when the frontier is empty. Until then the receipt pins
the shrinking frontier.

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

    # 1. champion x mode, and the bare-kit timed baseline.
    baselines = {}
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

    # 2. champion x legally-slotted item.
    for champ in champions:
        base = baselines.get(champ, set())
        for record in records:
            slotted = _slot_payload(record)
            if slotted is None:
                continue
            r = _probe(calculate_payload, timed_payload(champ, **slotted))
            key = f"{champ}|{record.get('name')}"
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


def main(argv):
    """CLI: ``run [--output PATH]`` or ``check PATH``; exit 1 on any frontier."""
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
    return 0 if total == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
