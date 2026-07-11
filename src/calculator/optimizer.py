"""Build optimizer using multi-start greedy search with hill climbing.

Finds the item build that maximizes a chosen damage objective (total,
physical, or magic damage) for a given champion/level/target configuration.
"""

import copy
import time
from typing import Any

from . import item_effects
from .damage import calculate_fight_damage
from .data_fetcher import fetch_item_data, get_item_by_name
from .champions import parse_abilities
from .stats import calculate_total_stats


# Items unavailable on Summoner's Rift.
ITEM_BLOCKLIST = {
    "Anathema's Chains",
    "Atma's Reckoning",
    "Bandleglass Mirror",
    "Bounty of Worlds",
    "Ghostcrawlers",
    "Hellfire Hatchet",
    "Perplexity",
    "Rite of Ruin",
    "Spectral Cutlass",
    "Sword of Blossoming Dawn",
    "Wordless Promise",
    "Zephyr",
}

# Spellblade items are mutually exclusive in-game.
# Item exclusivity groups — at most one item from each group per build.
# Mirrors ITEM_EXCLUSIVITY_GROUPS in app.js.
_EXCLUSIVITY_GROUPS: dict[str, set[str]] = {
    "Spellblade": {
        "Trinity Force", "Lich Bane", "Essence Reaver",
        "Iceborn Gauntlet", "Bloodsong", "Dusk and Dawn",
    },
    "Hydra": {
        "Tiamat", "Profane Hydra", "Ravenous Hydra",
        "Stridebreaker", "Titanic Hydra",
    },
    "Blight": {
        "Blighting Jewel", "Bloodletter's Curse", "Cryptbloom",
        "Terminus", "Void Staff",
    },
    "Fatality": {
        "Last Whisper", "Black Cleaver", "Lord Dominik's Regards",
        "Mortal Reminder", "Serylda's Grudge", "Terminus",
    },
}

# Reverse lookup: item name -> set of group names it belongs to.
_ITEM_TO_GROUPS: dict[str, set[str]] = {}
for _group, _members in _EXCLUSIVITY_GROUPS.items():
    for _name in _members:
        _ITEM_TO_GROUPS.setdefault(_name, set()).add(_group)

# Keep the old name for test imports.
_SPELLBLADE_ITEMS = _EXCLUSIVITY_GROUPS["Spellblade"]


def get_eligible_legendaries() -> list[dict[str, Any]]:
    """Return all legendary items eligible for the optimizer."""
    items = fetch_item_data()
    return [
        item_data
        for item_data in items.values()
        if "LEGENDARY" in item_data.get("rank", [])
        and "BOOTS" not in item_data.get("rank", [])
        and item_data.get("name")
        and item_data["name"] not in ITEM_BLOCKLIST
    ]


def get_eligible_boots() -> list[dict[str, Any]]:
    """Return all tier-2+ boots eligible for the optimizer."""
    items = fetch_item_data()
    return [
        item_data
        for item_data in items.values()
        if "BOOTS" in item_data.get("rank", [])
        and item_data.get("tier", 0) >= 2
        and item_data.get("name")
        and item_data["name"] not in ITEM_BLOCKLIST
    ]


def _get_occupied_groups(items: list[dict[str, Any]]) -> set[str]:
    """Return the set of exclusivity groups already occupied by *items*."""
    occupied: set[str] = set()
    for item in items:
        groups = _ITEM_TO_GROUPS.get(item.get("name", ""))
        if groups:
            occupied |= groups
    return occupied


def _conflicts_with_build(
    candidate_name: str, occupied_groups: set[str],
) -> bool:
    """Return True if *candidate_name* would violate an exclusivity group."""
    groups = _ITEM_TO_GROUPS.get(candidate_name)
    if not groups:
        return False
    return bool(groups & occupied_groups)


def _evaluate_build(
    champion_name: str,
    champion_data: dict[str, Any],
    level: int,
    items: list[dict[str, Any]],
    target_health: float,
    target_bonus_health: float,
    target_armor: float,
    target_mr: float,
    fight_duration: float,
    auto_attack_uptime: float,
    ability_haste_override: float | None,
    one_rotation: bool,
    include_actives: bool,
    cast_order: list[str] | None,
    auto_attacks_only: bool,
    ability_ranks: dict[str, int] | None,
    champion_options: dict[str, Any] | None,
    target_stats: dict[str, float] | None,
    objective: str,
) -> float:
    """Evaluate a build and return the damage score for the given objective.

    Creates fresh copies of mutable state to avoid cross-call contamination.
    """
    champion_stats = calculate_total_stats(champion_data, level, items)
    ability_haste = (
        ability_haste_override
        if ability_haste_override is not None
        else champion_stats.get("ability_haste", 0.0)
    )

    display_name = champion_data.get("name", champion_name)
    ability_damages = parse_abilities(
        display_name, champion_data, level,
        champion_stats["ability_power"],
        ability_ranks=ability_ranks,
        champion_stats=champion_stats,
        target_stats=target_stats,
        champion_options=champion_options,
    )

    # calculate_fight_damage mutates champion_stats (e.g. attack speed
    # buffs), so we pass a copy to keep our original clean.
    stats_copy = dict(champion_stats)

    result = calculate_fight_damage(
        champion_stats=stats_copy,
        ability_damages=ability_damages,
        target_health=target_health,
        target_bonus_health=target_bonus_health,
        target_armor=target_armor,
        target_magic_resistance=target_mr,
        fight_duration_seconds=fight_duration,
        auto_attack_uptime=auto_attack_uptime,
        ability_haste=ability_haste,
        items=items,
        one_rotation=one_rotation,
        include_actives=include_actives,
        cast_order=cast_order,
        auto_attacks_only=auto_attacks_only,
        deterministic=True,
    )

    if objective == "physical_damage":
        # Sum physical-type entries from breakdown
        total = 0.0
        for entry in result.get("breakdown", {}).values():
            if entry.get("damage_type") == "physical":
                total += entry.get("total_damage", 0.0)
        return total
    if objective == "magic_damage":
        total = 0.0
        for entry in result.get("breakdown", {}).values():
            if entry.get("damage_type") == "magic":
                total += entry.get("total_damage", 0.0)
        return total
    # Default: total damage
    return result.get("total_damage", 0.0)


def _greedy_fill(
    champion_name: str,
    champion_data: dict[str, Any],
    level: int,
    locked_legendaries: list[dict[str, Any]],
    locked_boots: dict[str, Any] | None,
    slots_to_fill: int,
    fill_boots: bool,
    pool: list[dict[str, Any]],
    boots_pool: list[dict[str, Any]],
    eval_kwargs: dict[str, Any],
    seed_item: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, float]:
    """Greedily fill empty slots one at a time, picking the best marginal item.

    Returns (legendaries, boots, best_score).
    """
    current = list(locked_legendaries)
    boots = locked_boots

    # If a seed item is provided, add it first (if it doesn't conflict)
    if seed_item and seed_item["name"] not in {i["name"] for i in current}:
        occupied = _get_occupied_groups(current)
        if not _conflicts_with_build(seed_item["name"], occupied):
            current.append(seed_item)

    used_names = {i["name"] for i in current}
    occupied_groups = _get_occupied_groups(current)

    while len(current) < len(locked_legendaries) + slots_to_fill:
        best_score = -1.0
        best_item = None

        for candidate in pool:
            name = candidate["name"]
            if name in used_names:
                continue
            # Enforce exclusivity groups
            if _conflicts_with_build(name, occupied_groups):
                continue

            trial_items = current + [candidate]
            if boots:
                trial_items = [boots] + trial_items

            score = _evaluate_build(
                champion_name, champion_data, level, trial_items,
                **eval_kwargs,
            )
            if score > best_score:
                best_score = score
                best_item = candidate

        if best_item is None:
            break
        current.append(best_item)
        used_names.add(best_item["name"])
        candidate_groups = _ITEM_TO_GROUPS.get(best_item["name"])
        if candidate_groups:
            occupied_groups |= candidate_groups

    # Fill boots if needed
    if fill_boots and boots_pool:
        best_score = -1.0
        best_boots = None
        for candidate in boots_pool:
            trial_items = [candidate] + current
            score = _evaluate_build(
                champion_name, champion_data, level, trial_items,
                **eval_kwargs,
            )
            if score > best_score:
                best_score = score
                best_boots = candidate
        boots = best_boots

    # Final score
    final_items = ([boots] if boots else []) + current
    final_score = _evaluate_build(
        champion_name, champion_data, level, final_items, **eval_kwargs,
    )
    return current, boots, final_score


def _hill_climb(
    champion_name: str,
    champion_data: dict[str, Any],
    level: int,
    legendaries: list[dict[str, Any]],
    boots: dict[str, Any] | None,
    locked_legendary_names: set[str],
    locked_boots: bool,
    pool: list[dict[str, Any]],
    boots_pool: list[dict[str, Any]],
    eval_kwargs: dict[str, Any],
    max_iterations: int = 10,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, float, int]:
    """Iteratively swap items to improve the build. Returns (legendaries, boots, score, evals)."""
    current = list(legendaries)
    current_boots = boots
    evals = 0

    all_items = ([current_boots] if current_boots else []) + current
    best_score = _evaluate_build(
        champion_name, champion_data, level, all_items, **eval_kwargs,
    )
    evals += 1

    for _ in range(max_iterations):
        improved = False

        # Try swapping each unlocked legendary slot
        for slot_idx in range(len(current)):
            if current[slot_idx]["name"] in locked_legendary_names:
                continue

            current_names = {
                i["name"] for j, i in enumerate(current) if j != slot_idx
            }
            other_items = [i for j, i in enumerate(current) if j != slot_idx]
            other_groups = _get_occupied_groups(other_items)

            for candidate in pool:
                name = candidate["name"]
                if name in current_names:
                    continue
                if name == current[slot_idx]["name"]:
                    continue
                if _conflicts_with_build(name, other_groups):
                    continue

                trial = list(current)
                trial[slot_idx] = candidate
                trial_items = ([current_boots] if current_boots else []) + trial

                score = _evaluate_build(
                    champion_name, champion_data, level, trial_items,
                    **eval_kwargs,
                )
                evals += 1

                if score > best_score:
                    best_score = score
                    current = trial
                    improved = True
                    break  # restart inner loop with updated build

            if improved:
                break

        # Try swapping boots if not locked
        if not locked_boots and boots_pool and not improved:
            for candidate in boots_pool:
                if current_boots and candidate["name"] == current_boots["name"]:
                    continue
                trial_items = [candidate] + current
                score = _evaluate_build(
                    champion_name, champion_data, level, trial_items,
                    **eval_kwargs,
                )
                evals += 1
                if score > best_score:
                    best_score = score
                    current_boots = candidate
                    improved = True
                    break

        if not improved:
            break

    return current, current_boots, best_score, evals


def optimize_build(
    champion_name: str,
    champion_data: dict[str, Any],
    level: int,
    target_health: float = 2000.0,
    target_bonus_health: float = 0.0,
    target_armor: float = 50.0,
    target_mr: float = 40.0,
    fight_mode: str = "one_rotation",
    fight_duration: float = 8.0,
    include_auto_attacks: bool = False,
    auto_attack_uptime: float = 0.8,
    auto_attacks_only: bool = False,
    ability_ranks: dict[str, int] | None = None,
    include_actives: bool = True,
    cast_order: list[str] | None = None,
    champion_options: dict[str, Any] | None = None,
    objective: str = "total_damage",
    locked_items: list[str] | None = None,
    locked_boots: str | None = None,
    max_legendary_slots: int = 5,
) -> dict[str, Any]:
    """Find the optimal item build for a champion.

    Args:
        champion_name: Champion display name.
        champion_data: Raw champion data dict.
        level: Champion level (1-20).
        target_health: Target max HP.
        target_bonus_health: Target bonus HP.
        target_armor: Target armor.
        target_mr: Target magic resistance.
        fight_mode: "one_rotation", "timed", or "auto_only".
        fight_duration: Fight length in seconds (for timed mode).
        include_auto_attacks: Whether to include auto attacks.
        auto_attack_uptime: Fraction of fight spent auto-attacking.
        auto_attacks_only: If True, only auto attacks (no abilities).
        ability_ranks: Optional ability rank overrides.
        include_actives: Whether to include item actives.
        cast_order: Ability cast order (permutation of Q, W, E, R).
        champion_options: Champion-specific config.
        objective: "total_damage", "physical_damage", or "magic_damage".
        locked_items: Item names already selected (optimizer won't change these).
        locked_boots: Boots name already selected (optimizer won't change).
        max_legendary_slots: 5 or 6 legendary item slots to fill.

    Returns:
        Dict with optimized build, damage, and metadata.
    """
    start_time = time.perf_counter()

    # Resolve fight parameters
    is_one_rotation = fight_mode == "one_rotation"
    if is_one_rotation:
        effective_duration = 5.0
        effective_uptime = 0.0
    elif auto_attacks_only:
        effective_duration = fight_duration
        effective_uptime = auto_attack_uptime
    else:
        effective_duration = fight_duration
        effective_uptime = auto_attack_uptime if include_auto_attacks else 0.0

    target_stats = {
        "target_max_health": target_health,
        "target_current_health": target_health,
        "target_missing_health": 0.0,
    }

    eval_kwargs = {
        "target_health": target_health,
        "target_bonus_health": target_bonus_health,
        "target_armor": target_armor,
        "target_mr": target_mr,
        "fight_duration": effective_duration,
        "auto_attack_uptime": effective_uptime,
        "ability_haste_override": None,
        "one_rotation": is_one_rotation,
        "include_actives": include_actives,
        "cast_order": cast_order,
        "auto_attacks_only": auto_attacks_only,
        "ability_ranks": ability_ranks,
        "champion_options": champion_options,
        "target_stats": target_stats,
        "objective": objective,
    }

    # Build item pools
    all_legendaries = get_eligible_legendaries()
    all_boots = get_eligible_boots()

    # Resolve locked items
    resolved_locked = []
    locked_names = set()
    if locked_items:
        for name in locked_items:
            if name:
                item = get_item_by_name(name)
                resolved_locked.append(item)
                locked_names.add(name)

    resolved_locked_boots = None
    boots_locked = False
    if locked_boots:
        resolved_locked_boots = get_item_by_name(locked_boots)
        boots_locked = True

    # How many legendary slots still need filling
    slots_to_fill = max_legendary_slots - len(resolved_locked)
    fill_boots = not boots_locked

    # Filter pool to exclude already-locked items
    pool = [i for i in all_legendaries if i["name"] not in locked_names]
    boots_pool = all_boots if fill_boots else []

    total_evals = 0

    # === Multi-start greedy + hill climbing ===
    # Seed strategies: no seed, top AD item, top AP item
    seeds: list[dict[str, Any] | None] = [None]

    # Find best raw-AD item as seed
    ad_items = sorted(
        pool,
        key=lambda i: i.get("stats", {}).get("attackDamage", {}).get("flat", 0),
        reverse=True,
    )
    if ad_items:
        seeds.append(ad_items[0])

    # Find best raw-AP item as seed
    ap_items = sorted(
        pool,
        key=lambda i: i.get("stats", {}).get("abilityPower", {}).get("flat", 0),
        reverse=True,
    )
    if ap_items and (not ad_items or ap_items[0]["name"] != ad_items[0]["name"]):
        seeds.append(ap_items[0])

    best_legendaries = None
    best_boots = None
    best_score = -1.0

    for seed in seeds:
        legendaries, boots, greedy_score = _greedy_fill(
            champion_name, champion_data, level,
            resolved_locked, resolved_locked_boots,
            slots_to_fill, fill_boots,
            pool, boots_pool, eval_kwargs,
            seed_item=seed,
        )
        # Rough eval count estimate for greedy phase
        total_evals += len(pool) * slots_to_fill + len(boots_pool)

        legendaries, boots, hc_score, hc_evals = _hill_climb(
            champion_name, champion_data, level,
            legendaries, boots,
            locked_names, boots_locked,
            pool, boots_pool, eval_kwargs,
        )
        total_evals += hc_evals

        if hc_score > best_score:
            best_score = hc_score
            best_legendaries = legendaries
            best_boots = boots

    elapsed = time.perf_counter() - start_time

    # Build final item name lists
    legendary_names = [i["name"] for i in best_legendaries] if best_legendaries else []
    boots_name = best_boots["name"] if best_boots else None

    return {
        "items": legendary_names,
        "boots": boots_name,
        "total_damage": round(best_score, 1),
        "objective": objective,
        "max_legendary_slots": max_legendary_slots,
        "optimization_time_ms": round(elapsed * 1000, 1),
        "evaluations": total_evals,
    }
