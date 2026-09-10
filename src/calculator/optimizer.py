"""Build optimizer using multi-start greedy search with hill climbing.

Finds the item build that maximizes a chosen damage objective (total,
physical, or magic damage) for a given champion/level/target configuration.
"""

import math
import time
from dataclasses import replace
from typing import Any

from . import build_evaluation, build_receipts, item_coverage, optimizer_candidates
from .application_errors import NoCompleteEventOrder
from .build_evaluation import _build_receipt_key
from .build_search import _greedy_fill, _hill_climb, _score_with_swap
from .champion_loadout import ResolvedLoadout
from .data_fetcher import get_item_by_name
from .fight_params import FightParams
from .item_coverage import (
    require_optimizer_item_coverage,
)
from .loadout_rules import (
    role_quest_legal_items,
    role_scoped_shop_items,
    validate_resolved_loadout,
)
from .optimizer_candidates import (
    _build_gold,
    _conflicts_with_build,
    _get_occupied_groups,
    _legal_locked_shop_item,
    item_gold,
)
from .participant_timeline import CoupledSearchContext
from .program.views.leaf import RankingWriter, name_every_number
from .work_counters import WorkCounterSink

# Item exclusivity groups — at most one item from each group per build
# (e.g. Spellblade items are mutually exclusive in-game).  The table in
# ``loadout_rules`` is the single source of truth: the frontend fetches it
# via /api/config (see exclusivity_groups() below) instead of keeping its
# own copy.


def _optimize_dispositions(payload: dict[str, Any]) -> dict[str, dict[str, object]]:
    """Name every number in the whole optimize payload, as the ranking it is."""
    return name_every_number(payload, RankingWriter())


def optimize_build(
    champion_data: dict[str, Any],
    level: int,
    *,
    fight_params: FightParams | None = None,
    objective: str = "total_damage",
    locked_items: list[str] | None = None,
    locked_boots: str | None = None,
    max_legendary_slots: int = 5,
    target_fight_params: tuple[FightParams, ...] | None = None,
    boots_tier: int = 2,
    gold_budget: int | None = None,
    require_complete_timeline: bool = False,
    enemy_loadouts: list[ResolvedLoadout] | None = None,
    ally_loadouts: list[ResolvedLoadout] | None = None,
    include_boots: bool = True,
    work_counters: WorkCounterSink | None = None,
    use_compiled_walk: bool = True,
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
        work_counters: Optional benchmark sink for this search's proposal,
            memo, pair-fight and fallback-rung counts (runbook R-24).
        use_compiled_walk: False forces every coupled evaluation onto the
            receipt walk. The two walks are pinned equivalent, so this
            changes cost and never an answer (R-01 row 11).

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
        "excluded_evaluations": 0,
        "exact_sources": set(),
        "coarse_sources": set(),
        "excluded_sources": set(),
        "build_coverages": {},
        "withheld_builds": {},
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
        "work_counters": work_counters,
    }
    # Pairwise roster receipts that do not depend on the candidate main
    # build's offense are invariant across the search: roster-to-roster pairs
    # always, and fights into the candidate whenever its defensive signature
    # repeats.  The score memo replays exact repeated builds without
    # re-simulating.  Both caches live for this optimizer call only.
    if eval_kwargs["combat_context"] is not None:
        eval_kwargs["combat_context"]["pair_result_cache"] = {}
        eval_kwargs["combat_context"]["score_memo"] = {}
        eval_kwargs["combat_context"]["search_context"] = CoupledSearchContext(
            work_counters=work_counters,
            compiled_walk_enabled=use_compiled_walk,
        )
    coupled_objective = bool(enemy_loadouts or ally_loadouts)

    # Build item pools.  Keep the complete legal lists for the public coverage
    # receipt, but only score candidates whose outgoing-damage mechanics are
    # represented by the fight model.
    legal_legendaries = optimizer_candidates.get_eligible_legendaries()
    legal_boots = optimizer_candidates.get_eligible_boots(tier=boots_tier)
    base_params = fight_params[0] if isinstance(fight_params, tuple) else fight_params
    # The main champion uses the same sourced role-shop boundary as roster BIS,
    # so a top-lane main search cannot rank a support-only item such as
    # Shurelya's Battlesong.  No archetype or stat heuristic is added here.
    all_legendaries = role_quest_legal_items(
        role_scoped_shop_items(
            item_coverage.optimizer_supported_items(legal_legendaries), base_params.role
        ),
        base_params.role,
        base_params.role_quest_complete,
    )
    all_boots = item_coverage.optimizer_supported_items(legal_boots)

    # Resolve locked items
    resolved_locked = []
    locked_names = set()
    if locked_items:
        for name in locked_items:
            if name:
                item = get_item_by_name(name)
                if not _legal_locked_shop_item(item):
                    raise ValueError(f"{name} is not an ordinary non-boots shop item")
                require_optimizer_item_coverage(item)
                item_gold(item)
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

    if slots_to_fill > 0 and not coupled_objective:
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
                score = build_evaluation.evaluate_build(
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
            slots_to_fill=slots_to_fill,
            fill_boots=fill_boots,
            pool=pool,
            boots_pool=boots_pool,
            eval_kwargs=eval_kwargs,
            seed_item=seed,
        )
        # Rough eval count estimate for greedy phase
        total_evals += len(pool) * slots_to_fill + len(boots_pool)

        legendaries, boots, hc_score, hc_evals = _hill_climb(
            champion_data,
            level,
            legendaries,
            boots,
            locked_legendary_names=locked_names,
            locked_boots=boots_locked,
            pool=pool,
            boots_pool=boots_pool,
            eval_kwargs=eval_kwargs,
            max_iterations=3 if coupled_objective else 10,
            initial_score=greedy_score,
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
    # The coupled endpoint already spends its budget on survival-coupled
    # event receipts for the actual winner.  An exhaustive one-slot runner-up
    # sweep adds hundreds of duplicate roster simulations without changing
    # the applied Build A, so keep that comparison pass for the fast,
    # single-target optimizer only.
    if best_legendaries is not None and not exact_mode and not coupled_objective:
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
                trial, score = _score_with_swap(
                    champion_data,
                    level,
                    best_legendaries,
                    slot_index,
                    candidate=candidate,
                    boots=best_boots,
                    eval_kwargs=eval_kwargs,
                )
                total_evals += 1
                remember_candidate(trial, best_boots, score)

        if not boots_locked:
            for candidate in boots_pool:
                if best_boots and candidate["name"] == best_boots["name"]:
                    continue
                score = build_evaluation.evaluate_build(
                    champion_data,
                    level,
                    [candidate, *best_legendaries],
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
        message = (
            f"No complete legal{qualifier} build fits the selected "
            f"constraints{constraint} for "
            f"{champion_data.get('name', 'the selected champion')}; this champion's "
            "current event package has no complete candidate timeline"
        )
        if require_complete_timeline:
            raise NoCompleteEventOrder(message, champion=champion_data["name"])
        raise ValueError(message)
    duration = (
        fight_params[0].fight_duration_seconds
        if isinstance(fight_params, tuple)
        else fight_params.fight_duration_seconds
    )
    public_ranked = []
    for rank, (legendaries, boots, score) in enumerate(ranked[:2], start=1):
        build_items = ([boots] if boots else []) + legendaries
        coupled_receipt = (
            timeline_audit.get("build_coverages", {}).get(
                _build_receipt_key(build_items)
            )
            if coupled_objective
            else None
        )
        public_ranked.append(
            {
                "rank": rank,
                "items": [item["name"] for item in legendaries],
                "boots": boots["name"] if boots else None,
                "total_damage": round(score, 1),
                "team_fight_value": round(score, 1) if coupled_objective else None,
                "dps": round(score / duration, 1),
                "gold": _build_gold(build_items),
                "timeline_coverage": coupled_receipt
                or build_evaluation.build_timeline_coverage(
                    champion_data,
                    level,
                    build_items,
                    fight_params,
                ),
            }
        )

    # Keep the receipt over every legal item packet, including role-filtered
    # entries, so coverage never claims the unsearched shop scope is complete.
    coverage_candidates = list(legal_legendaries)
    if not boots_locked:
        coverage_candidates.extend(legal_boots)
    candidate_coverage = item_coverage.optimizer_candidate_coverage(coverage_candidates)
    search_timeline_coverage = build_receipts.public_search_timeline_coverage(
        timeline_audit
    )
    timeline_withheld_candidates = sorted(
        timeline_audit.get("withheld_builds", {}).values(),
        key=lambda row: (tuple(row.get("items", [])), row.get("boots") or ""),
    )
    certified_best = (
        exact_mode
        and candidate_coverage["complete"]
        and search_timeline_coverage["complete"]
    )
    if coupled_objective and require_complete_timeline and ranked:
        # Full-build optimization is a deterministic local search, not an
        # exhaustive BIS proof.  It is nevertheless safe to apply when every
        # candidate that contributed a score had a complete event timeline;
        # coarse candidates were rejected above rather than silently ranked.
        certified_best = True

    payload = {
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
                    "event_ordered_candidates_with_explicit_exclusions"
                    if require_complete_timeline
                    and timeline_audit["excluded_evaluations"] > 0
                    else (
                        "exhaustive_event_ordered_candidates"
                        if require_complete_timeline
                        and timeline_audit["partial_evaluations"] > 0
                        else "exhaustive_legal_candidates"
                    )
                )
                if candidate_coverage["complete"]
                else "exhaustive_modeled_candidates"
            )
            if exact_mode
            else "local_search"
        ),
        "is_certified_best": certified_best,
        "selection_certification": (
            "event_ordered_local_search"
            if coupled_objective and require_complete_timeline and ranked
            else (
                "exhaustive_event_ordered"
                if certified_best
                else (
                    "event_ordered_item_scope_gap"
                    if search_timeline_coverage["complete"]
                    else "partial_or_unexhaustive"
                )
            )
        ),
        "candidate_coverage": candidate_coverage,
        "timeline_withheld_evaluations": (
            timeline_audit["partial_evaluations"] if require_complete_timeline else 0
        ),
        "timeline_excluded_evaluations": (
            timeline_audit["excluded_evaluations"] if require_complete_timeline else 0
        ),
        "timeline_excluded_sources": sorted(timeline_audit["excluded_sources"]),
        "timeline_withheld_candidate_count": len(timeline_withheld_candidates),
        "timeline_withheld_candidates": timeline_withheld_candidates,
        "gold_budget": gold_budget,
    }
    payload["dispositions"] = _optimize_dispositions(payload)
    return payload
