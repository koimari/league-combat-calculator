"""Build optimizer using multi-start greedy search with hill climbing.

Finds the item build that maximizes a chosen damage objective (total,
physical, or magic damage) for a given champion/level/target configuration.
"""

import time
from dataclasses import replace
from typing import Any

from .data_fetcher import fetch_item_data, get_item_by_name
from .pipeline import FightParams, run_fight

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

# Item exclusivity groups — at most one item from each group per build
# (e.g. Spellblade items are mutually exclusive in-game). This table is
# the single source of truth: the frontend fetches it via /api/config
# (see exclusivity_groups() below) instead of keeping its own copy.
_EXCLUSIVITY_GROUPS: dict[str, set[str]] = {
    "Spellblade": {
        "Trinity Force",
        "Lich Bane",
        "Essence Reaver",
        "Iceborn Gauntlet",
        "Bloodsong",
        "Dusk and Dawn",
    },
    "Hydra": {
        "Tiamat",
        "Profane Hydra",
        "Ravenous Hydra",
        "Stridebreaker",
        "Titanic Hydra",
    },
    "Blight": {
        "Blighting Jewel",
        "Bloodletter's Curse",
        "Cryptbloom",
        "Terminus",
        "Void Staff",
    },
    "Fatality": {
        "Last Whisper",
        "Black Cleaver",
        "Lord Dominik's Regards",
        "Mortal Reminder",
        "Serylda's Grudge",
        "Terminus",
    },
}

# Reverse lookup: item name -> set of group names it belongs to.
_ITEM_TO_GROUPS: dict[str, set[str]] = {}
for _group, _members in _EXCLUSIVITY_GROUPS.items():
    for _name in _members:
        _ITEM_TO_GROUPS.setdefault(_name, set()).add(_group)

# Keep the old name for test imports.
_SPELLBLADE_ITEMS = _EXCLUSIVITY_GROUPS["Spellblade"]


def exclusivity_groups() -> dict[str, list[str]]:
    """Return the item exclusivity groups as JSON-safe sorted lists.

    Served to the frontend (via /api/config) so the manual item picker
    enforces the same groups the optimizer does.
    """
    return {group: sorted(members) for group, members in _EXCLUSIVITY_GROUPS.items()}


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
    candidate_name: str,
    occupied_groups: set[str],
) -> bool:
    """Return True if *candidate_name* would violate an exclusivity group."""
    groups = _ITEM_TO_GROUPS.get(candidate_name)
    if not groups:
        return False
    return bool(groups & occupied_groups)


def _evaluate_build(
    champion_data: dict[str, Any],
    level: int,
    items: list[dict[str, Any]],
    fight_params: FightParams,
    objective: str,
) -> float:
    """Evaluate a build and return the damage score for the given objective.

    Creates fresh copies of mutable state to avoid cross-call contamination.
    """
    result = run_fight(champion_data, level, items, fight_params)

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

    # If a seed item is provided and there is room, add it first (if it
    # doesn't conflict). The seed occupies one of the slots to fill.
    if (
        seed_item
        and slots_to_fill > 0
        and seed_item["name"] not in {i["name"] for i in current}
    ):
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
                champion_data,
                level,
                trial_items,
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
                champion_data,
                level,
                trial_items,
                **eval_kwargs,
            )
            if score > best_score:
                best_score = score
                best_boots = candidate
        boots = best_boots

    # Final score
    final_items = ([boots] if boots else []) + current
    final_score = _evaluate_build(
        champion_data,
        level,
        final_items,
        **eval_kwargs,
    )
    return current, boots, final_score


def _hill_climb(
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
        champion_data,
        level,
        all_items,
        **eval_kwargs,
    )
    evals += 1

    for _ in range(max_iterations):
        improved = False

        # Try swapping each unlocked legendary slot
        for slot_idx in range(len(current)):
            if current[slot_idx]["name"] in locked_legendary_names:
                continue

            current_names = {i["name"] for j, i in enumerate(current) if j != slot_idx}
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
                    champion_data,
                    level,
                    trial_items,
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
                    champion_data,
                    level,
                    trial_items,
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
    champion_data: dict[str, Any],
    level: int,
    fight_params: FightParams | None = None,
    objective: str = "total_damage",
    locked_items: list[str] | None = None,
    locked_boots: str | None = None,
    max_legendary_slots: int = 5,
) -> dict[str, Any]:
    """Find the optimal item build for a champion.

    Args:
        champion_data: Raw champion data dict.
        level: Champion level (1-20).
        fight_params: Shared target, mode, ability, and champion configuration.
        objective: "total_damage", "physical_damage", or "magic_damage".
        locked_items: Item names already selected (optimizer won't change these).
        locked_boots: Boots name already selected (optimizer won't change).
        max_legendary_slots: Number of legendary item slots to fill (1-6).

    Returns:
        Dict with optimized build, damage, and metadata.
    """
    start_time = time.perf_counter()

    if fight_params is None:
        fight_params = FightParams.from_request({}, deterministic=True)
    elif not fight_params.deterministic:
        fight_params = replace(fight_params, deterministic=True)

    eval_kwargs = {
        "fight_params": fight_params,
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

    # How many legendary slots still need filling (locked items may already
    # fill every slot — never negative)
    slots_to_fill = max(0, max_legendary_slots - len(resolved_locked))
    fill_boots = not boots_locked

    # Filter pool to exclude already-locked items
    pool = [i for i in all_legendaries if i["name"] not in locked_names]
    boots_pool = all_boots if fill_boots else []

    total_evals = 0

    # === Multi-start greedy + hill climbing ===
    # Seed strategies: no seed, top AD item, top AP item. With no slots to
    # fill, every seeded start collapses to the unseeded one — skip them.
    seeds: list[dict[str, Any] | None] = [None]

    if slots_to_fill > 0:
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
            champion_data,
            level,
            resolved_locked,
            resolved_locked_boots,
            slots_to_fill,
            fill_boots,
            pool,
            boots_pool,
            eval_kwargs,
            seed_item=seed,
        )
        # Rough eval count estimate for greedy phase
        total_evals += len(pool) * slots_to_fill + len(boots_pool)

        legendaries, boots, hc_score, hc_evals = _hill_climb(
            champion_data,
            level,
            legendaries,
            boots,
            locked_names,
            boots_locked,
            pool,
            boots_pool,
            eval_kwargs,
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
