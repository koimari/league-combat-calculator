"""optimize_purchase, the one gold-budget search the API calls."""

import math
import time
from dataclasses import replace
from typing import Any

from . import (
    build_evaluation,
    build_receipts,
    item_coverage,
    optimizer_candidates,
    purchase_plans,
)
from .application_errors import NoCompleteEventOrder
from .champion_loadout import ResolvedLoadout
from .data_fetcher import get_item_by_name
from .economy import is_purchasable, plan_incomplete_combine
from .fight_params import FightParams
from .item_coverage import (
    require_optimizer_item_coverage,
)
from .item_source import is_ordinary_sr_item
from .loadout_rules import role_scoped_shop_items, validate_resolved_loadout
from .optimizer_candidates import (
    _build_gold,
    _legal_locked_shop_item,
    item_gold,
)
from .participant_timeline import CoupledSearchContext
from .purchase_plans import (
    PurchaseSearch,
    plan_type,
    run_purchase_local_search,
    score_exhaustive_purchase_plans,
)
from .role_quests import inventory_capacity
from .work_counters import WorkCounterSink


def optimize_purchase(
    champion_data: dict[str, Any],
    level: int,
    *,
    available_gold: int,
    fight_params: FightParams | None = None,
    objective: str = "total_damage",
    locked_items: list[str] | None = None,
    locked_boots: str | None = None,
    max_purchase_items: int | None = None,
    target_fight_params: tuple[FightParams, ...] | None = None,
    boots_tier: int = 2,
    require_complete_timeline: bool = True,
    enemy_loadouts: list[ResolvedLoadout] | None = None,
    ally_loadouts: list[ResolvedLoadout] | None = None,
    include_boots: bool = True,
    candidate_cap: int = 2000,
    allow_sell: bool = False,
    max_sell_items: int = 1,
    combine_policy: str = "shop_combine",
    include_starters: bool = False,
    time_budget_ms: int = 12_000,
    work_counters: WorkCounterSink | None = None,
    use_compiled_walk: bool = True,
) -> dict[str, Any]:
    """Fill the empty inventory slots with the available gold.

    Every plan is priced by the shop model (list-price buys with component
    credit, explicit combine fees, the sourced 70% sell table) and scored on
    its *resolved final loadout* through the existing event-order-certified
    fight pipeline.  Owned items are preserved unless a plan sells them, and
    a plan may buy as many items as the empty slots and the gold allow
    (``max_purchase_items`` optionally caps the buy count).

    Two regimes, certified honestly: when every affordable plan fits under
    ``candidate_cap`` the search is exhaustive and ``is_certified_best`` is
    true; a larger plan space falls back to a budget-aware local search
    (greedy fill by marginal damage and by marginal damage per gold, then
    hill climbing) whose winner is still returned, labeled
    ``purchase_local_search``.
    """
    if available_gold < 1:
        raise ValueError("available_gold must be at least 1")
    if max_purchase_items is not None and not 1 <= max_purchase_items <= 7:
        raise ValueError("max_purchase_items must be between 1 and 7")
    if max_sell_items not in (0, 1):
        raise ValueError("max_sell_items must be 0 or 1")
    if objective not in ("total_damage", "physical_damage", "magic_damage"):
        raise ValueError("Invalid objective")
    if combine_policy not in {"shop_combine", "component_accumulate"}:
        raise ValueError(
            "combine_policy must be 'shop_combine' or 'component_accumulate'"
        )

    started = time.perf_counter()
    params: FightParams | tuple[FightParams, ...]
    if target_fight_params:
        target_count = len(target_fight_params)
        params = tuple(
            replace(
                target,
                deterministic=True,
                roster_target_index=index,
                roster_target_count=target_count,
            )
            for index, target in enumerate(target_fight_params)
        )
    else:
        base = fight_params or FightParams.from_request({}, deterministic=True)
        params = base if base.deterministic else replace(base, deterministic=True)
    base_params = params[0] if isinstance(params, tuple) else params
    role = base_params.role
    role_quest_complete = base_params.role_quest_complete

    allowed_legendary_names = {
        item["name"]
        for item in role_scoped_shop_items(
            item_coverage.optimizer_supported_items(
                optimizer_candidates.get_eligible_legendaries()
            ),
            role,
        )
    }
    owned = []
    for name in locked_items or []:
        item = get_item_by_name(name)
        if not _legal_locked_shop_item(item):
            raise ValueError(f"{name} is not an ordinary non-boots shop item")
        if "LEGENDARY" in item.get("rank", []) and name not in allowed_legendary_names:
            raise ValueError(f"{name} is not available in the selected role shop")
        require_optimizer_item_coverage(item)
        item_gold(item)
        owned.append(item)
    owned_boots = None
    if locked_boots:
        if not include_boots:
            raise ValueError("locked_boots cannot be used when include_boots is false")
        owned_boots = get_item_by_name(locked_boots)
        if not is_ordinary_sr_item(owned_boots):
            raise ValueError(f"{locked_boots} is not an ordinary shop item")
        require_optimizer_item_coverage(owned_boots)
        item_gold(owned_boots)
    validate_resolved_loadout(
        owned,
        boots=owned_boots,
        role=role,
        role_quest_complete=role_quest_complete,
    )

    capacity = inventory_capacity(role, role_quest_complete)
    owned_names = {item["name"] for item in owned}
    if owned_boots:
        owned_names.add(owned_boots["name"])

    pool = [
        item
        for item in optimizer_candidates.get_purchase_items(role)
        if is_purchasable(item, include_starters=include_starters)
        and item["name"] not in owned_names
    ]
    boot_pool = []
    if include_boots and owned_boots is None:
        boot_pool = [
            item
            for item in item_coverage.optimizer_supported_items(
                optimizer_candidates.get_eligible_boots(tier=boots_tier)
            )
            if is_purchasable(item) and item["name"] not in owned_names
        ]

    def completed_first(item: dict[str, Any]) -> int:
        ranks = set(item.get("rank", []))
        return 0 if "LEGENDARY" in ranks else (1 if "EPIC" in ranks else 2)

    # Completed items before their components: the shop model always
    # credits a buy's recipe from the inventory, so a component bought
    # before its legendary would be force-consumed and the hold-both
    # loadout would silently drop out of the exhaustive walk.
    buyables = [*sorted(pool, key=completed_first), *boot_pool]

    # Sell pivots: at most one owned piece may be sold to fund the plan.
    sell_options: list[dict[str, Any] | None] = [None]
    if allow_sell and max_sell_items >= 1:
        sell_options.extend(owned)
        if owned_boots is not None:
            sell_options.append(owned_boots)

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
    combat_context = (
        {"enemies": list(enemy_loadouts or ()), "allies": list(ally_loadouts or ())}
        if enemy_loadouts or ally_loadouts
        else None
    )
    if combat_context is not None:
        combat_context.update(
            {
                "pair_result_cache": {},
                "score_memo": {},
                "search_context": CoupledSearchContext(
                    work_counters=work_counters,
                    compiled_walk_enabled=use_compiled_walk,
                ),
            }
        )

    search = PurchaseSearch(
        champion_data,
        level,
        owned,
        owned_boots,
        available_gold=available_gold,
        max_buys=max_purchase_items or capacity,
        combine_policy=combine_policy,
        role=role,
        role_quest_complete=role_quest_complete,
        params=params,
        objective=objective,
        timeline_audit=timeline_audit,
        require_complete_timeline=require_complete_timeline,
        combat_context=combat_context,
        deadline=started + time_budget_ms / 1000,
        capacity=capacity,
        reserve_boot_slot=include_boots and owned_boots is None,
        work_counters=work_counters,
    )

    def current_loadout_score() -> float | None:
        current_items = ([owned_boots] if owned_boots else []) + owned
        if not current_items:
            return None
        # The current loadout is a comparison baseline, not a candidate;
        # keep it out of the candidate-evaluation audit.
        return build_evaluation.evaluate_build(
            champion_data,
            level,
            current_items,
            fight_params=params,
            objective=objective,
            timeline_audit=None,
            require_complete_timeline=require_complete_timeline,
            combat_context=combat_context,
        )

    current_score = current_loadout_score()

    # ---- choose the regime: exhaustive when the affordable plan space is
    # small enough to score completely, budget-aware local search otherwise.
    pool_names = {item["name"] for item in pool}
    shape_rows: list[tuple[dict[str, Any] | None, list[dict[str, Any]]]] = []
    exhaustive_complete = True
    for sell in sell_options:
        shapes, sell_complete = purchase_plans.enumerate_affordable_shapes(
            search, sell, buyables, candidate_cap, counted=len(shape_rows)
        )
        shape_rows.extend((sell, shape) for shape in shapes)
        if not sell_complete:
            exhaustive_complete = False
            break

    if exhaustive_complete:
        truncated = score_exhaustive_purchase_plans(search, shape_rows, pool_names)
    else:
        truncated = run_purchase_local_search(search, sell_options, buyables)

    if not search.candidates:
        message = "No complete legal purchase fits the selected constraints"
        if require_complete_timeline:
            raise NoCompleteEventOrder(
                message.replace("legal purchase", "legal event-ordered purchase"),
                champion=champion_data["name"],
            )
        raise ValueError(message)
    scored = search.ranked()
    best_score, best_plan, best_spend = scored[0]

    bought_nothing = (
        not best_plan.purchases and not best_plan.sell_items and best_plan.spend == 0
    )
    if (
        exhaustive_complete
        and not truncated
        and len(search.candidates) == 1
        and bought_nothing
    ):
        # Literally nothing was affordable: the empty plan is the only
        # candidate that priced and scored.  Any weaker state falls through
        # — a local-search or truncated run may not certify this claim, and
        # affordable-but-non-improving buys are reported as keep_gold, not
        # as "no affordable purchase".
        return {
            "optimization_scope": "purchase",
            "items": [item["name"] for item in owned],
            "boots": owned_boots["name"] if owned_boots else None,
            "purchase_items": [],
            "sell_items": [],
            "recommendation_type": "no_affordable_purchase",
            "spent_gold": 0,
            "sell_refund": 0,
            "remaining_gold": available_gold,
            "inventory_gold": _build_gold(
                ([owned_boots] if owned_boots else []) + owned
            ),
            "ranked_purchases": [],
            "candidate_count": len(search.candidates),
            "evaluations": search.evaluations,
            "optimization_time_ms": round((time.perf_counter() - started) * 1000, 1),
            "searched_space": "no affordable legal plan",
            "exhaustive_within_scope": True,
            "truncated": False,
            "certification": {
                "event_order": True,
                "economy": True,
                "legality": True,
                "claim": "no_affordable_purchase",
            },
            "winner_event_order_certified": True,
            "is_certified_best": True,
            "search_guarantee": "exhaustive_purchase_scope",
            "available_gold": available_gold,
            "objective": objective,
        }

    # Search pricing skipped the shop-wide recipe scan; restore the winner's
    # incomplete_combine receipt before it is serialized.
    best_plan.incomplete_combine = combine_policy == "shop_combine" and (
        plan_incomplete_combine(best_plan)
    )

    candidate_coverage = item_coverage.optimizer_candidate_coverage(buyables)
    search_coverage = build_receipts.public_search_timeline_coverage(timeline_audit)
    exhaustive_within_scope = (
        exhaustive_complete
        and not truncated
        and candidate_coverage["complete"]
        and search_coverage["complete"]
    )
    # With require_complete_timeline a candidate can only rank when its own
    # timeline is complete, so the winner is event-ordered by construction;
    # an incomplete aggregate only means some *other* candidate was partial.
    winner_event_order_certified = bool(
        require_complete_timeline or search_coverage["complete"]
    )
    if exhaustive_complete:
        search_guarantee = (
            "best_evaluated_plan_truncated"
            if truncated
            else "exhaustive_purchase_scope"
        )
    else:
        search_guarantee = "purchase_local_search"
    rank_count = min(3, len(scored))
    public_ranked = []
    for rank, (score, plan, spend) in enumerate(scored[:rank_count], start=1):
        build_items = (
            [plan.final_boots] if plan.final_boots else []
        ) + plan.final_items
        public_ranked.append(
            {
                "rank": rank,
                "purchase_items": [
                    *plan.purchases,
                    *[row.item for row in plan.price_rows if row.combined_charged],
                ],
                "sell_items": plan.sell_items,
                "recommendation_type": plan_type(plan),
                "spent_gold": spend,
                "sell_refund": plan.refund,
                "remaining_gold": plan.remaining,
                "total_damage": round(score, 1),
                "price_rows": [row.to_dict() for row in plan.price_rows],
                "timeline_coverage": build_evaluation.build_timeline_coverage(
                    champion_data, level, build_items, params
                ),
            }
        )

    purchase_names = [
        *best_plan.purchases,
        *[row.item for row in best_plan.price_rows if row.combined_charged],
    ]
    build_items = (
        [best_plan.final_boots] if best_plan.final_boots else []
    ) + best_plan.final_items
    resulting_total = round(best_score, 1)
    delta = (
        round(best_score - current_score, 1)
        if current_score is not None and math.isfinite(current_score)
        else None
    )
    if exhaustive_complete:
        searched_space = (
            f"{'truncated ' if truncated else 'exhaustive '}"
            f"{{slot-filling buys | combines | {1 if allow_sell else 0} sell}} "
            f"within {available_gold:,} gold"
        )
    else:
        searched_space = f"budget-aware local search within {available_gold:,} gold"
    return {
        "optimization_scope": "purchase",
        "items": [item["name"] for item in best_plan.final_items],
        "boots": best_plan.final_boots["name"] if best_plan.final_boots else None,
        "purchase_items": purchase_names,
        "sell_items": best_plan.sell_items,
        "recommendation_type": plan_type(best_plan),
        "spent_gold": best_spend,
        "sell_refund": best_plan.refund,
        "remaining_gold": best_plan.remaining,
        "inventory_gold": _build_gold(build_items),
        "resulting_total_damage": resulting_total,
        "damage_delta_vs_current": delta,
        "damage_per_100_gold": (
            round(resulting_total / best_spend * 100, 1) if best_spend else None
        ),
        "price_rows": [row.to_dict() for row in best_plan.price_rows],
        "incomplete_combine": best_plan.incomplete_combine,
        "ranked_purchases": public_ranked,
        "candidate_count": len(search.candidates),
        "evaluations": search.evaluations,
        "optimization_time_ms": round((time.perf_counter() - started) * 1000, 1),
        "searched_space": searched_space,
        "exhaustive_within_scope": exhaustive_within_scope,
        "truncated": truncated,
        "certification": {
            "event_order": winner_event_order_certified,
            "economy": True,
            "legality": True,
            "claim": (
                "certified_best_purchase_within_scope"
                if exhaustive_within_scope
                else (
                    "best_found_local_search"
                    if not exhaustive_complete
                    else "best_evaluated_plan"
                )
            ),
        },
        "winner_event_order_certified": winner_event_order_certified,
        "is_certified_best": exhaustive_within_scope,
        "search_guarantee": search_guarantee,
        "candidate_coverage": candidate_coverage,
        "search_timeline_coverage": search_coverage,
        "available_gold": available_gold,
        "objective": objective,
    }
