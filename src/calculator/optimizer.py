"""Build optimizer using multi-start greedy search with hill climbing.

Finds the item build that maximizes a chosen damage objective (total,
physical, or magic damage) for a given champion/level/target configuration.
"""

import math
import time
from dataclasses import replace
from typing import Any

from .data_fetcher import fetch_item_data, get_item_by_name
from .item_coverage import (
    optimizer_candidate_coverage,
    optimizer_supported_items,
    require_optimizer_item_coverage,
)
from .loadout_rules import (
    ITEM_EXCLUSIVITY_GROUPS,
    ITEM_TO_EXCLUSIVITY_GROUPS,
    conflicts_with_groups,
    exclusivity_groups,
    occupied_groups,
    validate_resolved_loadout,
)
from .pipeline import FightParams, run_fight
from .defensive_effects import resolve_starting_defenses
from .participant_timeline import build_participant_timeline
from .stats import calculate_total_stats
from .timeline_coverage import combine_timeline_coverages

# Items unavailable on Summoner's Rift.
ITEM_BLOCKLIST = {
    "Anathema's Chains",
    "Atma's Reckoning",
    "Bandleglass Mirror",
    "Bounty of Worlds",
    "Ghostcrawlers",
    "Hellfire Hatchet",
    "Multitool",
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
# Keep the old name for test imports.
_SPELLBLADE_ITEMS = ITEM_EXCLUSIVITY_GROUPS["Spellblade"]


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


def get_selectable_items() -> list[dict[str, Any]]:
    """Return ordinary Summoner's Rift build items for manual loadouts.

    The optimizer intentionally searches completed legendary items only.
    Manual scenario reconstruction also needs components and starters such as
    Ruby Crystal, Dark Seal, and Doran's Ring.
    """
    allowed_ranks = {"BASIC", "EPIC", "STARTER", "LEGENDARY"}
    return [
        item_data
        for item_data in fetch_item_data().values()
        if allowed_ranks.intersection(item_data.get("rank", []))
        and "BOOTS" not in item_data.get("rank", [])
        and item_data.get("name")
        and item_data["name"] not in ITEM_BLOCKLIST
    ]


def get_eligible_boots(tier: int | None = 2) -> list[dict[str, Any]]:
    """Return boots eligible for the requested role-quest tier.

    Ordinary builds use tier 2. Completed mid-lane quests use tier 3.
    Passing ``None`` returns both tiers for the role-aware manual picker.
    """
    items = fetch_item_data()
    return [
        item_data
        for item_data in items.values()
        if "BOOTS" in item_data.get("rank", [])
        and item_data.get("tier", 0) >= 2
        and (tier is None or item_data.get("tier") == tier)
        and item_data.get("name")
        and item_data["name"] not in ITEM_BLOCKLIST
    ]


def _get_occupied_groups(items: list[dict[str, Any]]) -> set[str]:
    """Return the set of exclusivity groups already occupied by *items*."""
    return occupied_groups(item.get("name", "") for item in items)


def _conflicts_with_build(
    candidate_name: str,
    occupied_groups: set[str],
) -> bool:
    """Return True if *candidate_name* would violate an exclusivity group."""
    return conflicts_with_groups(candidate_name, occupied_groups)


def _evaluate_build(
    champion_data: dict[str, Any],
    level: int,
    items: list[dict[str, Any]],
    fight_params: FightParams | tuple[FightParams, ...],
    objective: str,
    gold_budget: int | None = None,
    timeline_audit: dict[str, Any] | None = None,
    require_complete_timeline: bool = False,
    combat_context: dict[str, Any] | None = None,
) -> float:
    """Evaluate a build and return the damage score for the given objective.

    Creates fresh copies of mutable state to avoid cross-call contamination.
    """
    if gold_budget is not None and _build_gold(items) > gold_budget:
        return float("-inf")
    targets = fight_params if isinstance(fight_params, tuple) else (fight_params,)
    if combat_context is not None and (
        combat_context.get("enemies") or combat_context.get("allies")
    ):
        # Score the same event-ordered participant timeline exposed by
        # /api/calculate.  A candidate's outgoing damage after its own death
        # is excluded, so a glass-cannon build cannot win by living only on
        # paper.  No role/archetype weight is introduced here.
        base_params = targets[0]
        stats = calculate_total_stats(
            champion_data,
            level,
            items,
            item_options=base_params.item_options,
            role=base_params.role,
            role_quest_complete=base_params.role_quest_complete,
            external_stat_bonuses=base_params.ally_stat_bonuses,
        )
        defenses = resolve_starting_defenses(
            champion_data["name"], level, stats, items
        )
        combat = build_participant_timeline(
            champion_data,
            level,
            items,
            base_params,
            main_stats=stats,
            main_defenses=defenses,
            enemies=list(combat_context.get("enemies", [])),
            allies=list(combat_context.get("allies", [])),
        )
        coverage = combat.get("timeline_coverage", {})
        if timeline_audit is not None:
            timeline_audit["evaluations"] += 1
            timeline_audit["exact_sources"].update(coverage.get("exact_sources", []))
            timeline_audit["coarse_sources"].update(coverage.get("coarse_sources", []))
            if not coverage.get("complete", False):
                timeline_audit["partial_evaluations"] += 1
        # A coupled roster may contain a sourced champion effect whose exact
        # sub-hit cadence is not yet certified.  Keep the candidate usable,
        # but preserve the partial receipt so the result cannot be presented
        # as a fully certified BIS claim.
        main_row = next(
            (row for row in combat.get("breakdown", []) if row.get("participant_id") == "main"),
            None,
        )
        if main_row is None:
            return float("-inf")
        if objective == "physical_damage":
            death_time = next(
                row.get("survival", {}).get("death_time")
                for row in combat.get("participants", [])
                if row.get("participant_id") == "main"
            )
            cutoff = base_params.fight_duration_seconds if death_time is None else death_time
            return sum(
                float(event.get("damage", 0.0))
                for event in combat.get("events", [])
                if event.get("attacker") == "main"
                and event.get("damage_type") == "physical"
                and float(event.get("time", 0.0)) <= cutoff
            )
        if objective == "magic_damage":
            death_time = next(
                row.get("survival", {}).get("death_time")
                for row in combat.get("participants", [])
                if row.get("participant_id") == "main"
            )
            cutoff = base_params.fight_duration_seconds if death_time is None else death_time
            return sum(
                float(event.get("damage", 0.0))
                for event in combat.get("events", [])
                if event.get("attacker") == "main"
                and event.get("damage_type") == "magic"
                and float(event.get("time", 0.0)) <= cutoff
            )
        if objective == "total_damage":
            # The participant timeline already truncates the main actor's
            # output at its event-ordered death time.  Effective health is a
            # receipt component describing that survival window; adding it to
            # damage here double-counts the same defensive value and causes
            # glass-cannon candidates to lose to pure-health builds.
            return float(main_row.get("total_damage", 0.0))
        return float(main_row.get("total_damage", 0.0))
    results: list[dict[str, Any]] = []
    for target_params in targets:
        result = run_fight(champion_data, level, items, target_params)
        results.append(result)
    coverage = _combined_build_timeline_coverage(results)
    if timeline_audit is not None:
        timeline_audit["evaluations"] += 1
        timeline_audit["exact_sources"].update(coverage["exact_sources"])
        timeline_audit["coarse_sources"].update(coverage["coarse_sources"])
        if not coverage["complete"]:
            timeline_audit["partial_evaluations"] += 1
    if require_complete_timeline and not coverage["complete"]:
        return float("-inf")

    def included(entry: dict[str, Any]) -> bool:
        if objective == "physical_damage":
            return entry.get("damage_type") == "physical"
        if objective == "magic_damage":
            return entry.get("damage_type") == "magic"
        return True

    total = sum(
        entry.get("total_damage", 0.0)
        for result in results
        for entry in result.get("breakdown", {}).values()
        if included(entry)
    )
    if objective == "total_damage":
        # Informational rows are already excluded from result.total_damage,
        # whereas the breakdown can contain non-damage displays.
        total = sum(result.get("total_damage", 0.0) for result in results)

    return total


def _build_timeline_coverage(
    champion_data: dict[str, Any],
    level: int,
    items: list[dict[str, Any]],
    fight_params: FightParams | tuple[FightParams, ...],
) -> dict[str, Any]:
    """Return the target-combined ordering receipt for one ranked build."""
    targets = fight_params if isinstance(fight_params, tuple) else (fight_params,)
    results = [
        run_fight(champion_data, level, items, target_params)
        for target_params in targets
    ]
    return _combined_build_timeline_coverage(results)


def _combined_build_timeline_coverage(
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Combine targets and fail partial on post-ledger charged allocation."""
    return combine_timeline_coverages(
        (result.get("timeline_coverage", {}) for result in results),
        target_count=len(results),
    )


def _public_search_timeline_coverage(audit: dict[str, Any]) -> dict[str, Any]:
    """Serialize precision across every candidate evaluation in this search."""
    evaluations = int(audit["evaluations"])
    partial_evaluations = int(audit["partial_evaluations"])
    coarse_sources = sorted(audit["coarse_sources"])
    exact_sources = sorted(set(audit["exact_sources"]) - set(coarse_sources))
    complete = evaluations > 0 and partial_evaluations == 0
    if complete:
        note = f"All {evaluations:,} candidate evaluations are event-ordered."
    elif coarse_sources:
        note = (
            f"{partial_evaluations:,} of {evaluations:,} candidate evaluations use "
            "coarse phase ordering."
        )
    else:
        note = "Timeline coverage is unavailable for at least one candidate evaluation."
    return {
        "complete": complete,
        "certification": (
            "candidate_event_order_certified"
            if complete
            else "partial_candidate_event_order"
        ),
        "evaluations": evaluations,
        "partial_evaluations": partial_evaluations,
        "exact_sources": exact_sources,
        "coarse_sources": coarse_sources,
        "note": note,
    }


def _item_gold(item: dict[str, Any]) -> int:
    """Return the sourced total shop price for one item."""
    return int(item.get("shop", {}).get("prices", {}).get("total", 0))


def _build_gold(items: list[dict[str, Any]]) -> int:
    """Return total shop price for a resolved build."""
    return sum(_item_gold(item) for item in items)


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
        occupied_groups.update(ITEM_TO_EXCLUSIVITY_GROUPS.get(best_item["name"], ()))

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
    target_fight_params: tuple[FightParams, ...] | None = None,
    boots_tier: int = 2,
    gold_budget: int | None = None,
    require_complete_timeline: bool = False,
    enemy_loadouts: list[Any] | None = None,
    ally_loadouts: list[Any] | None = None,
    include_boots: bool = True,
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
        target_fight_params: Optional roster targets scored as summed TDD.
        boots_tier: 2 normally; 3 after the mid-lane role quest.
        require_complete_timeline: Withhold any build whose damage is not
            event-order certified. Public BIS requests enable this.

    Returns:
        Dict with optimized build, damage, and metadata.
    """
    start_time = time.perf_counter()

    if fight_params is None:
        fight_params = FightParams.from_request({}, deterministic=True)
    elif not fight_params.deterministic:
        fight_params = replace(fight_params, deterministic=True)

    if target_fight_params:
        target_count = len(target_fight_params)
        fight_params = tuple(
            replace(
                params,
                deterministic=True,
                roster_target_index=target_index,
                roster_target_count=target_count,
            )
            for target_index, params in enumerate(target_fight_params)
        )

    timeline_audit = {
        "evaluations": 0,
        "partial_evaluations": 0,
        "exact_sources": set(),
        "coarse_sources": set(),
    }
    eval_kwargs = {
        "fight_params": fight_params,
        "objective": objective,
        "gold_budget": gold_budget,
        "timeline_audit": timeline_audit,
        "require_complete_timeline": require_complete_timeline,
        "combat_context": (
            {"enemies": list(enemy_loadouts or ()), "allies": list(ally_loadouts or ())}
            if enemy_loadouts or ally_loadouts
            else None
        ),
    }
    coupled_objective = bool(enemy_loadouts or ally_loadouts)

    # Build item pools.  Keep the complete legal lists for the public coverage
    # receipt, but only score candidates whose outgoing-damage mechanics are
    # represented by the fight model.
    legal_legendaries = get_eligible_legendaries()
    legal_boots = get_eligible_boots(tier=boots_tier)
    all_legendaries = optimizer_supported_items(legal_legendaries)
    all_boots = optimizer_supported_items(legal_boots)

    # Resolve locked items
    resolved_locked = []
    locked_names = set()
    if locked_items:
        for name in locked_items:
            if name:
                item = get_item_by_name(name)
                require_optimizer_item_coverage(item)
                resolved_locked.append(item)
                locked_names.add(name)

    resolved_locked_boots = None
    boots_locked = False
    if locked_boots:
        if not include_boots:
            raise ValueError("locked_boots cannot be used when include_boots is false")
        resolved_locked_boots = get_item_by_name(locked_boots)
        require_optimizer_item_coverage(resolved_locked_boots)
        boots_locked = True

    validate_resolved_loadout(
        resolved_locked,
        boots=resolved_locked_boots,
        role=(
            fight_params[0].role
            if isinstance(fight_params, tuple)
            else fight_params.role
        ),
        role_quest_complete=(
            fight_params[0].role_quest_complete
            if isinstance(fight_params, tuple)
            else fight_params.role_quest_complete
        ),
    )
    locked_gold = _build_gold(
        ([resolved_locked_boots] if resolved_locked_boots else []) + resolved_locked
    )
    if gold_budget is not None and locked_gold > gold_budget:
        raise ValueError(
            f"Locked items cost {locked_gold:,} gold, above the {gold_budget:,} budget"
        )

    # How many legendary slots still need filling (locked items may already
    # fill every slot — never negative)
    slots_to_fill = max(0, max_legendary_slots - len(resolved_locked))
    fill_boots = include_boots and not boots_locked

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
    ranked_candidates: dict[
        tuple[tuple[str, ...], str | None],
        tuple[list[dict[str, Any]], dict[str, Any] | None, float],
    ] = {}

    def remember_candidate(
        legendaries: list[dict[str, Any]],
        boots: dict[str, Any] | None,
        score: float,
    ) -> None:
        if not math.isfinite(score):
            return
        key = (
            tuple(sorted(item["name"] for item in legendaries)),
            boots["name"] if boots else None,
        )
        previous = ranked_candidates.get(key)
        if previous is None or score > previous[2]:
            ranked_candidates[key] = (list(legendaries), boots, score)

    exact_mode = slots_to_fill <= 1
    if exact_mode:
        legendary_options = [list(resolved_locked)]
        if slots_to_fill == 1:
            occupied = _get_occupied_groups(resolved_locked)
            legendary_options = [
                [*resolved_locked, candidate]
                for candidate in pool
                if not _conflicts_with_build(candidate["name"], occupied)
            ]
        boot_options = (
            [resolved_locked_boots]
            if resolved_locked_boots is not None
            else list(boots_pool)
        )
        if not boot_options:
            boot_options = [None]
        for legendaries in legendary_options:
            for boots in boot_options:
                score = _evaluate_build(
                    champion_data,
                    level,
                    ([boots] if boots else []) + legendaries,
                    **eval_kwargs,
                )
                total_evals += 1
                remember_candidate(legendaries, boots, score)
                if score > best_score:
                    best_score = score
                    best_legendaries = legendaries
                    best_boots = boots
        seeds = []

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
        remember_candidate(legendaries, boots, hc_score)

        if hc_score > best_score:
            best_score = hc_score
            best_legendaries = legendaries
            best_boots = boots

    # Always return a genuinely different runner-up. Search every legal
    # one-slot alternative around the strongest build instead of echoing the
    # winner into both comparison columns.
    if best_legendaries is not None and not exact_mode:
        for slot_index, current_item in enumerate(best_legendaries):
            if current_item["name"] in locked_names:
                continue
            other_items = [
                item
                for index, item in enumerate(best_legendaries)
                if index != slot_index
            ]
            other_names = {item["name"] for item in other_items}
            other_groups = _get_occupied_groups(other_items)
            for candidate in pool:
                if candidate["name"] in other_names:
                    continue
                if _conflicts_with_build(candidate["name"], other_groups):
                    continue
                trial = list(best_legendaries)
                trial[slot_index] = candidate
                trial_items = ([best_boots] if best_boots else []) + trial
                score = _evaluate_build(
                    champion_data, level, trial_items, **eval_kwargs
                )
                total_evals += 1
                remember_candidate(trial, best_boots, score)

        if not boots_locked:
            for candidate in boots_pool:
                if best_boots and candidate["name"] == best_boots["name"]:
                    continue
                score = _evaluate_build(
                    champion_data,
                    level,
                    [candidate] + best_legendaries,
                    **eval_kwargs,
                )
                total_evals += 1
                remember_candidate(best_legendaries, candidate, score)

    elapsed = time.perf_counter() - start_time

    # Build final item name lists
    legendary_names = [i["name"] for i in best_legendaries] if best_legendaries else []
    boots_name = best_boots["name"] if best_boots else None
    ranked = sorted(
        ranked_candidates.values(), key=lambda value: value[2], reverse=True
    )
    if not ranked:
        constraint = f" within {gold_budget:,} gold" if gold_budget is not None else ""
        qualifier = " event-ordered" if require_complete_timeline else ""
        raise ValueError(
            f"No complete legal{qualifier} build fits the selected "
            f"constraints{constraint}"
        )
    duration = (
        fight_params[0].fight_duration_seconds
        if isinstance(fight_params, tuple)
        else fight_params.fight_duration_seconds
    )
    public_ranked = []
    for rank, (legendaries, boots, score) in enumerate(ranked[:2], start=1):
        build_items = ([boots] if boots else []) + legendaries
        public_ranked.append(
            {
                "rank": rank,
                "items": [item["name"] for item in legendaries],
                "boots": boots["name"] if boots else None,
                "total_damage": round(score, 1),
                "team_fight_value": round(score, 1) if coupled_objective else None,
                "dps": round(score / duration, 1),
                "gold": _build_gold(build_items),
                "timeline_coverage": _build_timeline_coverage(
                    champion_data,
                    level,
                    build_items,
                    fight_params,
                ),
            }
        )

    coverage_candidates = list(legal_legendaries)
    if not boots_locked:
        coverage_candidates.extend(legal_boots)
    candidate_coverage = optimizer_candidate_coverage(coverage_candidates)
    search_timeline_coverage = _public_search_timeline_coverage(timeline_audit)
    certified_best = (
        exact_mode
        and candidate_coverage["complete"]
        and search_timeline_coverage["complete"]
    )

    return {
        "items": legendary_names,
        "boots": boots_name,
        "total_damage": round(ranked[0][2], 1),
        "team_fight_value": round(ranked[0][2], 1) if coupled_objective else None,
        "objective": objective,
        "max_legendary_slots": max_legendary_slots,
        "optimization_time_ms": round(elapsed * 1000, 1),
        "evaluations": total_evals,
        "target_count": len(fight_params) if isinstance(fight_params, tuple) else 1,
        "ranked_builds": public_ranked,
        "timeline_coverage": public_ranked[0]["timeline_coverage"],
        "search_timeline_coverage": search_timeline_coverage,
        "search_guarantee": (
            (
                (
                    "exhaustive_event_ordered_candidates"
                    if require_complete_timeline
                    and timeline_audit["partial_evaluations"] > 0
                    else "exhaustive_legal_candidates"
                )
                if candidate_coverage["complete"]
                else "exhaustive_modeled_candidates"
            )
            if exact_mode
            else "local_search"
        ),
        "is_certified_best": certified_best,
        "candidate_coverage": candidate_coverage,
        "timeline_withheld_evaluations": (
            timeline_audit["partial_evaluations"]
            if require_complete_timeline
            else 0
        ),
        "gold_budget": gold_budget,
    }
