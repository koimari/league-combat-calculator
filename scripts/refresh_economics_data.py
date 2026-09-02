"""Refresh data/economics-sourced.json from DDragon + wiki overrides.

The atomized economics tables (per-item sell refunds and combine fees) are
pinned to one DDragon release.  ``patch_update.py run`` invokes this script
right after the wiki pull so the economy engine prices the new patch; by
hand:

    python scripts/refresh_economics_data.py [--patch 16.15.1]

``--patch`` defaults to the release the pulled cache's champion icons pin.

Sources:
- DDragon ``data/en_US/item.json``: gold.total / gold.base / gold.sell / from
- Wiki overrides (documented below): support chain + jungle pets unsellable
  since V25.09 (wiki rev 4021809); Slightly Magical Footwear 30% note.

The output file is JSON with the same schema the loader expects; it fails
loudly if DDragon is unreachable or the sell/combine invariants break.
:func:`stale_reasons` is the one definition of "current" for the file: the
patch-day audit blocks on it and ``tests/test_refresh_economics_data.py``
holds the committed file to it.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.calculator.item_source import is_ordinary_sr_item

try:
    from patch_regression import extract_ddragon_version  # pylint: disable=import-error
except ImportError:  # imported as scripts.refresh_economics_data in tests
    from scripts.patch_regression import extract_ddragon_version

OUT = REPO_ROOT / "data" / "economics-sourced.json"

#: Cached shop totals that disagree with DDragon's, each reviewed against the
#: wiki page: ``name -> (cached total, DDragon total)``.  Any other
#: disagreement blocks patch day, and a row here that stops reproducing is
#: reported too, so neither source is ever silently preferred.
ACKNOWLEDGED_TOTAL_DIVERGENCES = {
    "Redemption": (2250, 2300),
}

# Wiki-override sell values (DDragon is stale for these since V25.09).
_UNSELLABLE = {
    "World Atlas",
    "Runic Compass",
    "Bounty of Worlds",
    "Black Mist Scythe",
    "Bulwark of the Mountain",
    "Celestial Opposition",
    "Dream Maker",
    "Solstice Sleigh",
    "Gustwalker Hatchling",
    "Mosstomper Seedling",
    "Scorchclaw Pup",
}
_UNSELLABLE_NOTE = "unsellable since V25.09 (wiki rev 4021809); DDragon stale"


def stale_reasons(
    tables: Mapping[str, Any],
    items_cache: Mapping[str, Any],
    ddragon_version: str | None,
) -> list[str]:
    """Why ``tables`` (the economics file) is not current for ``items_cache``.

    Empty means current: pinned to the cache's DDragon release, a sell row for
    every ordinary Summoner's Rift item (``economy.py`` prices from that row
    and fails closed without it), and every total that disagrees with the
    cached shop is an acknowledged divergence that still reproduces.
    """
    reasons = []
    pinned = tables["patch"]["ddragon"]
    if pinned != ddragon_version:
        reasons.append(
            f"pinned to DDragon {pinned} but the cache is at {ddragon_version}"
        )
    rows = {int(row["id"]): row for row in tables["per_item_sell"]}
    diverged = set()
    for item in items_cache.values():
        if not is_ordinary_sr_item(item):
            continue
        name = str(item["name"])
        row = rows.get(int(item["id"]))
        if row is None:
            reasons.append(f"{name}: in the cached shop but has no sourced sell row")
            continue
        divergence = (int(item["shop"]["prices"]["total"]), int(row["total"]))
        if divergence[0] == divergence[1]:
            continue
        diverged.add(name)
        if ACKNOWLEDGED_TOTAL_DIVERGENCES.get(name) != divergence:
            reasons.append(
                f"{name}: cached shop total {divergence[0]} != DDragon "
                f"{divergence[1]} (unacknowledged)"
            )
    reasons.extend(
        f"{name}: acknowledged total divergence no longer reproduces"
        for name in sorted(set(ACKNOWLEDGED_TOTAL_DIVERGENCES) - diverged)
    )
    return reasons


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--patch",
        default=None,
        help="DDragon release (default: the one the cached champion icons pin)",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="output file (default <repo>/data/economics-sourced.json)",
    )
    args = parser.parse_args()

    out_path = (Path(args.out) if args.out else OUT).resolve()
    if REPO_ROOT.resolve() not in out_path.parents:
        raise SystemExit(f"--out {out_path} is outside the repository ({REPO_ROOT})")

    # Scope to items the calculator's cache knows (data/items.json): rows for
    # Arena/mode variants or removed items are noise the loader must not see.
    cache_path = REPO_ROOT / "data" / "items.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    cache_by_id = {int(item_id): item for item_id, item in cache.items()}

    patch = args.patch or extract_ddragon_version(
        json.loads((REPO_ROOT / "data" / "champions.json").read_text(encoding="utf-8"))
    )
    if not patch:
        raise SystemExit("no DDragon release in the cached icons; pass --patch")
    url = f"https://ddragon.leagueoflegends.com/cdn/{patch}/data/en_US/item.json"
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    raw = response.json()["data"]

    # Preserve wiki tables the DDragon pass cannot rebuild.
    previous = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}

    per_item_sell = []
    combine_costs = []
    violations = []
    for item_id, item in raw.items():
        numeric_id = int(item_id)
        cached = cache_by_id.get(numeric_id)
        if cached is None:
            continue
        name = item.get("name", "")
        gold = item.get("gold", {})
        rank = list(cached.get("rank", []))
        total = int(gold.get("total", 0))
        base = int(gold.get("base", 0))
        sell = int(gold.get("sell", 0))
        components = [str(c) for c in (item.get("from") or [])]
        purchasable = bool(gold.get("purchasable", False))

        ratio = round(sell / total, 3) if total else 0.0
        if name in _UNSELLABLE:
            sell = 0
            ratio = 0.0
            note = _UNSELLABLE_NOTE
        else:
            note = ""
        per_item_sell.append(
            {
                "id": int(item_id),
                "name": name,
                "total": total,
                "cache_sell": None,
                "ddragon_sell": sell,
                "ratio": ratio,
                "rank": rank,
                "purchasable": purchasable,
                "wiki_note": note,
            }
        )
        if components:
            component_total = 0
            resolved = []
            for cid in components:
                comp = raw.get(cid)
                if comp is None:
                    violations.append(f"{name}: component {cid} missing")
                    continue
                component_total += int(comp.get("gold", {}).get("total", 0))
                resolved.append(comp.get("name", cid))
            derived = total - component_total
            if base != derived:
                violations.append(
                    f"{name}: DDragon base {base} != total - components {derived}"
                )
            combine_costs.append(
                {
                    "id": int(item_id),
                    "name": name,
                    "total": total,
                    "components": resolved,
                    "component_total": component_total,
                    "derived_combine": base,
                    "cache_combine": 0,
                }
            )

    if violations:
        print("INVARIANT VIOLATIONS:")
        for row in violations[:20]:
            print(" -", row)
        print(f"{len(violations)} total; refusing to write.")
        return 1

    out = {
        "generated": "refresh",
        "patch": {
            "cdragon": patch,
            "ddragon": patch,
            "repo_cache_fetched": None,
        },
        "groups_26_12": previous.get("groups_26_12", {}),
        "transforms": previous.get("transforms", {}),
        "sell_rule": {
            "default_ratio": 0.7,
            "rounding": "round half up (floor(x*ratio + 0.5))",
            "exceptions_40pct": [
                "All SR starters (Doran's x5, Cull, Dark Seal)",
                "Consumables (Health Potion, Refillable Potion, Control Ward, Elixir "
                "of Iron/Sorcery/Wrath)",
                "Guardian Angel",
                "Rejuvenation Bead",
                "Seeker's Armguard / Shattered Armguard",
            ],
            "exceptions_30pct": [
                "Slightly Magical Footwear (rune-granted, sells 90 of 300)"
            ],
            "exceptions_0pct": [
                "Jungle pets (no resell since V25.09)",
                "Support chain (World Atlas -> Bounty of Worlds, no resell since V25.09)",
                "Trinkets and distributed items (no shop value)",
            ],
            "wiki_corrections": (
                "Support chain and jungle pets set to 0% per wiki V25.09 rev 4021809 "
                "(DDragon stale); in-game adjudication recommended."
            ),
        },
        "per_item_sell": sorted(per_item_sell, key=lambda row: row["id"]),
        "combine_costs": sorted(combine_costs, key=lambda row: row["id"]),
        "revisions": previous.get("revisions", {"ddragon": patch}),
    }
    out["provenance"] = {
        "source_url": url,
        "patch": patch,
    }
    tmp = out_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(out_path)
    print(
        f"wrote {out_path} ({len(per_item_sell)} sell rows, {len(combine_costs)} combine rows)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
