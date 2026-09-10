"""The gold-constrained plan space: what one plan is, how it is enumerated and priced,
the two chain builders and the two searches over them."""

import math
import time
from collections.abc import Collection, Iterable, Sequence
from typing import Any

from . import build_evaluation
from .economy import (
    PurchasePlan,
    _item_by_id,
    apply_purchase_plan,
    combine_candidates,
    is_stackable,
    item_total,
    recipe_demand,
)
from .fight_params import FightParams
from .loadout_rules import validate_resolved_loadout
from .work_counters import WorkCounterSink


class PurchaseSearch:
    """Prices and scores candidate purchase plans for one optimization run.

    Pricing goes through the real shop model (component credit, combine
    cascade, sell refund) plus loadout legality, and scoring goes through the
    same event-ordered fight evaluation as every other optimizer.  ``record``
    keeps the best plan per distinct final loadout, so the exhaustive and
    local-search regimes rank from one shared candidate table.
    """

    # A search context is a deliberate value bag; splitting it would spread
    # one run's state across parallel argument lists.
    # pylint: disable=too-many-instance-attributes,too-many-arguments
    # pylint: disable=too-many-positional-arguments,too-many-locals

    def __init__(
        self,
        champion_data: dict[str, Any],
        level: int,
        owned: list[dict[str, Any]],
        owned_boots: dict[str, Any] | None,
        *,
        available_gold: int,
        max_buys: int,
        combine_policy: str,
        role: str,
        role_quest_complete: bool,
        params: FightParams | tuple[FightParams, ...],
        objective: str,
        timeline_audit: dict[str, Any],
        require_complete_timeline: bool,
        combat_context: dict[str, Any] | None,
        deadline: float,
        capacity: int,
        reserve_boot_slot: bool,
        work_counters: WorkCounterSink | None = None,
    ) -> None:
        self.champion_data = champion_data
        self.level = level
        self.owned = owned
        self.owned_boots = owned_boots
        self.available_gold = available_gold
        self.max_buys = max_buys
        self.combine_policy = combine_policy
        self.role = role
        self.role_quest_complete = role_quest_complete
        self.params = params
        self.objective = objective
        self.timeline_audit = timeline_audit
        self.require_complete_timeline = require_complete_timeline
        self.combat_context = combat_context
        self.deadline = deadline
        self.capacity = capacity
        self.reserve_boot_slot = reserve_boot_slot
        # The work-counter sink rides the search context itself rather than
        # a patched module attribute (runbook R-24), so the counters CI reads
        # come from the same object the search itself carries.
        self.work_counters = work_counters
        self.evaluations = 0
        self.candidates: dict[
            tuple[tuple[str, ...], str | None],
            tuple[float, PurchasePlan, int],
        ] = {}
        self._score_memo: dict[tuple[tuple[str, ...], str | None], float] = {}

    def expired(self) -> bool:
        """Whether the shared time budget for this search has run out."""
        return time.perf_counter() > self.deadline

    def price(
        self,
        sell: dict[str, Any] | None,
        buys: list[dict[str, Any]],
        combines: list[dict[str, Any]] | None = None,
    ) -> PurchasePlan | None:
        """Price one plan through the shop model, or None if illegal.

        Every rejection reason — gold, slots, duplicates, exclusivity,
        boots — is monotone in added buys, so callers may prune a whole
        subtree when a prefix fails.
        """
        non_boots = [item for item in buys if "BOOTS" not in item.get("rank", [])]
        if len(non_boots) > self.max_buys:
            return None
        try:
            plan = apply_purchase_plan(
                self.owned,
                self.owned_boots,
                buys,
                self.available_gold,
                sell_items=[sell] if sell else None,
                combine_items=combines,
                combine_policy=self.combine_policy,
                # Receipt-only shop scan, recomputed for the winner.
                flag_incomplete_combine=False,
            )
            # A recommendation must be a loadout the rest of the app accepts:
            # manual builds and /api/calculate validate with the strict rules
            # (no duplicates, even reviewed-stackable components), so the
            # search prices against that same gate — one legality authority.
            validate_resolved_loadout(
                plan.final_items,
                boots=plan.final_boots,
                role=self.role,
                role_quest_complete=self.role_quest_complete,
            )
        except (KeyError, ValueError, LookupError):
            return None
        if (
            self.reserve_boot_slot
            and plan.final_boots is None
            and len(plan.final_items) > self.capacity - 1
        ):
            # Boots are enabled, so the interface holds a slot for them; a
            # plan may not spend that slot on a sixth ordinary item.
            return None
        return plan

    def score_plan(self, plan: PurchasePlan) -> float:
        """Score a plan's resolved final loadout, once per distinct loadout."""
        key = _plan_key(plan)
        hit = self._score_memo.get(key)
        if hit is not None:
            return hit
        build_items = (
            [plan.final_boots] if plan.final_boots else []
        ) + plan.final_items
        score = build_evaluation.evaluate_build(
            self.champion_data,
            self.level,
            build_items,
            fight_params=self.params,
            objective=self.objective,
            timeline_audit=self.timeline_audit,
            require_complete_timeline=self.require_complete_timeline,
            combat_context=self.combat_context,
            work_counters=self.work_counters,
        )
        self.evaluations += 1
        self._score_memo[key] = score
        return score

    def record(self, plan: PurchasePlan, score: float) -> None:
        """Remember the best-scoring, then cheapest, plan per final loadout."""
        if not math.isfinite(score):
            return
        key = _plan_key(plan)
        previous = self.candidates.get(key)
        if (
            previous is None
            or score > previous[0]
            or (score == previous[0] and plan.spend < previous[2])
        ):
            self.candidates[key] = (score, plan, plan.spend)

    def evaluate(
        self,
        sell: dict[str, Any] | None,
        buys: list[dict[str, Any]],
        combines: list[dict[str, Any]] | None = None,
    ) -> float | None:
        """Price, score, and record one plan; None when the plan is illegal."""
        plan = self.price(sell, buys, combines)
        if plan is None:
            return None
        score = self.score_plan(plan)
        self.record(plan, score)
        return score

    def ranked(self) -> list[tuple[float, PurchasePlan, int]]:
        """All recorded candidates, best damage first, cheapest tie-break."""
        return sorted(
            self.candidates.values(),
            key=lambda row: (-row[0], row[2], _plan_key(row[1])),
        )


def enumerate_affordable_shapes(
    search: PurchaseSearch,
    sell: dict[str, Any] | None,
    buyables: Sequence[dict[str, Any]],
    cap: int,
    *,
    counted: int,
) -> tuple[list[list[dict[str, Any]]], bool]:
    """Depth-first walk of every priceable buy list, in pool order.

    A prefix that fails to price prunes its whole subtree (failure reasons
    are monotone in added buys), and any final loadout reachable through a
    buy-components-then-complete route is also reachable by buying the
    completed items directly, so pruning redundant routes loses no loadout.
    Returns (shapes, complete); complete is False when the cap stopped the
    walk before it finished.
    """
    shapes: list[list[dict[str, Any]]] = [[]]
    complete = True

    # O(1) affordability floor per child, checked before full shop pricing:
    # a buy can never cost less than its list price minus the credit its
    # recipe could draw, and the inventory can never credit more than its
    # own component value.  This keeps the walk's cost linear in *kept*
    # shapes instead of attempted children (full pricing per attempt burned
    # the whole time budget at low gold).  The floor only prunes plans full
    # pricing would also reject, so exhaustive certification is unaffected.
    by_id = _item_by_id()
    totals = [item_total(item) for item in buyables]
    recipe_values = [
        sum(
            item_total(by_id[component_id]) * count
            for component_id, count in recipe_demand(item).items()
            if component_id in by_id
        )
        for item in buyables
    ]
    component_ranks = {"BASIC", "EPIC"}
    credit_start = sum(
        item_total(item)
        for item in search.owned
        if component_ranks.intersection(item.get("rank", []))
    )
    if sell is not None and component_ranks.intersection(sell.get("rank", [])):
        # Selling removes exactly one copy from the creditable inventory.
        credit_start -= item_total(sell)
    base_plan = search.price(sell, [])

    def walk(
        start: int,
        prefix: list[dict[str, Any]],
        remaining: int,
        credit_pool: int,
    ) -> None:
        nonlocal complete
        for index in range(start, len(buyables)):
            if not complete:
                return
            if search.expired():
                # Enumeration must never eat the scoring budget; an
                # incomplete walk degrades to the local-search regime.
                complete = False
                return
            if totals[index] - min(recipe_values[index], credit_pool) > remaining:
                continue
            candidate = buyables[index]
            trial = [*prefix, candidate]
            plan = search.price(sell, trial)
            if plan is None:
                continue
            if counted + len(shapes) >= cap:
                complete = False
                return
            shapes.append(trial)
            # A consumed component would shrink the pool; keeping it is a
            # valid upper bound and stays conservative.
            grown_pool = credit_pool + (
                totals[index]
                if component_ranks.intersection(candidate.get("rank", []))
                else 0
            )
            walk(
                index if is_stackable(candidate) else index + 1,
                trial,
                plan.remaining,
                grown_pool,
            )

    walk(
        0,
        [],
        base_plan.remaining if base_plan is not None else search.available_gold,
        credit_start,
    )
    return shapes, complete


def _greedy_purchase_chain(
    search: PurchaseSearch,
    sell: dict[str, Any] | None,
    buyables: Iterable[dict[str, Any]],
    per_gold: bool,
    *,
    start: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], float] | None:
    """Add the best affordable buy one slot at a time until nothing improves.

    ``per_gold`` ranks each step by marginal damage per gold spent instead
    of raw marginal damage — the start that prefers four efficient cheap
    items over three expensive ones.
    """
    chain = list(start or [])
    plan = search.price(sell, chain)
    if plan is None:
        return None
    best_score = search.score_plan(plan)
    search.record(plan, best_score)
    best_spend = plan.spend
    # Like the exhaustive loop, the deadline never blanks the search: the
    # first fill step always completes a full argmax scan, so an expired
    # clock degrades to the best single buy — never to the first pool item
    # that happened to beat the baseline.
    first_step = True
    while first_step or not search.expired():
        full_scan = first_step
        first_step = False
        step_metric = 0.0
        step_score = 0.0
        step_spend = 0
        step_candidate: dict[str, Any] | None = None
        for candidate in buyables:
            if not full_scan and search.expired() and step_candidate is not None:
                break
            trial_plan = search.price(sell, [*chain, candidate])
            if trial_plan is None:
                continue
            score = search.score_plan(trial_plan)
            search.record(trial_plan, score)
            if not score > best_score:
                continue
            gain = score - best_score if math.isfinite(best_score) else score
            metric = gain / max(1, trial_plan.spend - best_spend) if per_gold else gain
            if step_candidate is None or metric > step_metric:
                step_metric, step_score = metric, score
                step_spend, step_candidate = trial_plan.spend, candidate
        if step_candidate is None:
            break
        chain.append(step_candidate)
        best_score, best_spend = step_score, step_spend
    return chain, best_score


def _improve_purchase_chain(
    search: PurchaseSearch,
    sell: dict[str, Any] | None,
    buyables: list[dict[str, Any]],
    chain: list[dict[str, Any]],
    best_score: float,
    *,
    max_rounds: int = 3,
) -> tuple[list[dict[str, Any]], float]:
    """Hill-climb a purchase chain: swap single buys, then respend leftovers."""
    # pylint: disable=too-many-arguments  # one climb needs its whole context
    for _ in range(max_rounds):
        improved = False
        for index in range(len(chain)):
            for candidate in buyables:
                if search.expired():
                    return chain, best_score
                trial = [*chain[:index], candidate, *chain[index + 1 :]]
                plan = search.price(sell, trial)
                if plan is None:
                    continue
                score = search.score_plan(plan)
                search.record(plan, score)
                if score > best_score:
                    chain, best_score = trial, score
                    improved = True
                    break
            if improved:
                break
        extended = _greedy_purchase_chain(
            search, sell, buyables, per_gold=False, start=chain
        )
        if extended is not None and extended[1] > best_score:
            chain, best_score = extended
            improved = True
        if not improved:
            break
    return chain, best_score


def score_exhaustive_purchase_plans(
    search: PurchaseSearch,
    shape_rows: Iterable[tuple[dict[str, Any] | None, list[dict[str, Any]]]],
    pool_names: Collection[str],
) -> bool:
    """Score every enumerated shape plus its combine completions.

    Returns whether the deadline truncated scoring.  The deadline never
    blanks the result: at least one real purchase plan is scored before
    truncation is honored, so the caller always gets a best-found plan
    instead of an empty error.
    """
    raw_plans: list[
        tuple[dict[str, Any] | None, list[dict[str, Any]], dict[str, Any] | None]
    ] = []
    by_id = _item_by_id()
    for sell, buys in shape_rows:
        raw_plans.append((sell, buys, None))
        # Combine completions for every inventory reachable by a shape.
        # A combine is gold-identical to a credited direct buy except where
        # the sourced combine table disagrees with cache arithmetic — that
        # divergence is why this pass exists.
        inventory: dict[int, int] = {}
        for item in search.owned:
            if sell is not None and item["name"] == sell["name"]:
                continue
            inventory[int(item["id"])] = inventory.get(int(item["id"]), 0) + 1
        for buy in buys:
            if "BOOTS" in {str(r).upper() for r in buy.get("rank", []) or []}:
                continue
            inventory[int(buy["id"])] = inventory.get(int(buy["id"]), 0) + 1
        for combine_id, _demand, _fee in combine_candidates(inventory, by_id):
            combine = by_id[combine_id]
            if combine["name"] not in pool_names:
                continue
            raw_plans.append((sell, buys, combine))
    progressed = False
    for sell, buys, combine in raw_plans:
        if search.expired() and progressed:
            return True
        score = search.evaluate(sell, buys, [combine] if combine else None)
        if score is not None and math.isfinite(score) and (buys or sell):
            progressed = True
    return False


def run_purchase_local_search(
    search: PurchaseSearch,
    sell_options: Iterable[dict[str, Any] | None],
    buyables: list[dict[str, Any]],
) -> bool:
    """Greedy-fill each sell pivot from two angles, then climb the best.

    Returns whether the deadline truncated the search.
    """
    best_sell: dict[str, Any] | None = None
    best_chain: list[dict[str, Any]] | None = None
    best_score = float("-inf")
    for sell in sell_options:
        for per_gold in (False, True):
            outcome = _greedy_purchase_chain(search, sell, buyables, per_gold)
            if outcome is None:
                continue
            chain, chain_score = outcome
            if best_chain is None or chain_score > best_score:
                best_sell, best_chain, best_score = sell, chain, chain_score
    if best_chain is not None:
        _improve_purchase_chain(search, best_sell, buyables, best_chain, best_score)
    return search.expired()


def _plan_key(plan: Any) -> tuple[tuple[str, ...], str | None]:
    """Canonical final-loadout key for score memoization."""
    names = tuple(sorted(item["name"] for item in plan.final_items))
    return (names, plan.final_boots["name"] if plan.final_boots else None)


def plan_type(plan: PurchasePlan) -> str:
    """Human recommendation type for a priced plan."""
    if plan.sell_items:
        return "sell_pivot"
    combined = [
        row.item
        for row in plan.price_rows
        if row.combined_charged or row.components_consumed
    ]
    if combined:
        return "recipe_completion"
    if not plan.purchases:
        # The search ran and doing nothing won: buys exist but none improve
        # the objective.
        return "keep_gold"
    if len(plan.purchases) == 1:
        boots = plan.final_boots and not plan.final_items
        return "boots" if boots else "single_item"
    if len(plan.purchases) >= 2:
        return "component_set"
    return "single_item"
