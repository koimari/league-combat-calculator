"""The per-champion level-by-build DPS matrix, and the ability ranking read off it."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .champions import parse_champion_abilities
from .data_fetcher import fetch_item_data
from .data_registry import data_version
from .stats import calculate_total_stats, effective_cooldown

# level x build reference matrix for the DPS-consistency gate (mirrors the
# golden snapshot's sweep builds)
_MATRIX_SPECS = (
    (1, ()),
    (11, ()),
    (18, ()),
    (18, ("Luden's Echo", "Shadowflame", "Rabadon's Deathcap")),
    (18, ("Kraken Slayer", "Infinity Edge", "Lord Dominik's Regards")),
    (18, ("Trinity Force", "Infinity Edge", "Berserker's Greaves")),
)


# per-(champion, data version) cache: matrix DPS rows at the reference points
_MATRIX_DPS_CACHE: dict[tuple[str, int], list[list[tuple[str, float]]]] = {}


def _matrix_dps_rows(
    champion_name: str, champion_data: Mapping[str, Any], aoe: Mapping[str, int]
) -> list[list[tuple[str, float]]]:
    """Per-rank DPS at the reference level/build matrix, cached.

    The matrix is a pure function of the champion's cached data — it never
    depends on the request's level or build — so it is computed once per
    (champion, data version) and reused by every fight until a refresh
    replaces the data it was computed from.
    """
    cache_key = (champion_name, data_version())
    cached = _MATRIX_DPS_CACHE.get(cache_key)
    if cached is not None:
        return cached

    items_by_name = {d["name"]: d for d in fetch_item_data().values()}
    target_stats = {
        "target_max_health": 2000.0,
        "target_current_health": 2000.0,
        "target_missing_health": 0.0,
    }
    rows: list[list[tuple[str, float]]] = []
    for level, build in _MATRIX_SPECS:
        items = [items_by_name[n] for n in build if n in items_by_name]
        stats = calculate_total_stats(dict(champion_data), level, items)
        parsed = parse_champion_abilities(
            dict(champion_data),
            level,
            stats["ability_power"],
            ability_ranks=None,
            champion_stats=stats,
            target_stats=target_stats,
            champion_options=None,
        )
        rows.append(rank_ability_dps(parsed, target_count=1, aoe=aoe))
    _MATRIX_DPS_CACHE[cache_key] = rows
    return rows


def rank_ability_dps(
    ability_damages: Mapping[str, Any],
    *,
    ability_haste: float = 0.0,
    target_count: int = 1,
    aoe: Mapping[str, int] | None = None,
) -> list[tuple[str, float, float, float]]:
    """Rank damaging abilities by per-rank DPS at the fight's stats.

    Signal (b) of the scoring model: ``total_raw`` divided by the effective
    per-rank cooldown read from the atomized ability rows.  Zero- or
    missing-cooldown rows (on-hits, procs, passives) are excluded, because they
    are not rotation casts.

    A slot listed in ``aoe`` hits up to ``aoe[slot]`` enemy champions, so its
    effective DPS is multiplied by ``min(target_count, cap)``: an ability that
    hits every enemy in a five-man roster outranks a single-target nuke of the
    same raw damage, which is how the optimal order stays optimal.

    Returns ``[(slot, dps, total_raw, cooldown)]`` sorted by DPS descending.
    """
    aoe = aoe or {}
    target_count = max(1, int(target_count))
    ranked: list[tuple[str, float, float, float]] = []
    for slot, info in ability_damages.items():
        if not isinstance(info, Mapping):
            continue
        cooldown = float(info.get("cooldown", 0.0) or 0.0)
        if cooldown <= 0:
            continue
        raw = float(info.get("total_raw", 0.0) or 0.0)
        if raw <= 0:
            continue
        effective = effective_cooldown(cooldown, ability_haste)
        targets = min(target_count, max(1, int(aoe.get(slot, 1))))
        ranked.append((slot, raw * targets / effective, raw, cooldown))
    ranked.sort(key=lambda row: (-row[1], row[0]))
    return ranked
