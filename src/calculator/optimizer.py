"""Build optimizer using multi-start greedy search with hill climbing.

Finds the item build that maximizes a chosen damage objective (total,
physical, or magic damage) for a given champion/level/target configuration.
"""

import math
import time
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import replace
from typing import Any

from .application_errors import NoCompleteEventOrder
from .data_fetcher import fetch_item_data, get_item_by_name
from .defensive_effects import resolve_starting_defenses
from .economy import (
    PurchasePlan,
    _item_by_id,
    apply_purchase_plan,
    combine_candidates,
    is_purchasable,
    is_stackable,
    item_total,
    plan_incomplete_combine,
    recipe_demand,
)
from .item_coverage import (
    optimizer_candidate_coverage,
    optimizer_supported_items,
    require_optimizer_item_coverage,
)
from .item_source import is_ordinary_sr_item
from .loadout_rules import (
    ITEM_TO_EXCLUSIVITY_GROUPS,
    conflicts_with_groups,
    inventory_capacity,
    occupied_groups,
    role_quest_legal_items,
    role_scoped_shop_items,
    validate_resolved_loadout,
)
from .participant_timeline import CoupledSearchContext, build_participant_timeline
from .pipeline import FightParams, run_fight
from .program.views import RankingWriter, name_every_number
from .scenario import ResolvedLoadout
from .timeline_coverage import (
    applicability_exclusion_sources,
    combine_timeline_coverages,
)
from .work_counters import WorkCounterSink

# Item exclusivity groups — at most one item from each group per build
# (e.g. Spellblade items are mutually exclusive in-game).  The table in
# ``loadout_rules`` is the single source of truth: the frontend fetches it
# via /api/config (see exclusivity_groups() below) instead of keeping its
# own copy.


def _ordinary_sr_items() -> list[dict[str, Any]]:
    """Every cached item an ordinary Summoner's Rift build can hold.

    ``item_source`` reads availability off the cached sources, so an ARAM
    starter leaves the pool because the data says so, not a name list.
    """
    return [
        item_data
        for item_data in fetch_item_data().values()
        if item_data.get("name") and is_ordinary_sr_item(item_data)
    ]


def get_eligible_legendaries() -> list[dict[str, Any]]:
    """Return all legendary items eligible for the optimizer."""
    return [
        item_data
        for item_data in _ordinary_sr_items()
        if "LEGENDARY" in item_data.get("rank", [])
        and "BOOTS" not in item_data.get("rank", [])
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
        for item_data in _ordinary_sr_items()
        if allowed_ranks.intersection(item_data.get("rank", []))
        and "BOOTS" not in item_data.get("rank", [])
    ]


def get_eligible_boots(tier: int | None = 2) -> list[dict[str, Any]]:
    """Return boots eligible for the requested role-quest tier.

    Ordinary builds use tier 2. Completed mid-lane quests use tier 3.
    Passing ``None`` returns both tiers for the role-aware manual picker.
    """
    return [
        item_data
        for item_data in _ordinary_sr_items()
        if "BOOTS" in item_data.get("rank", [])
        and item_data.get("tier", 0) >= 2
        and (tier is None or item_data.get("tier") == tier)
    ]


def _get_occupied_groups(items: Iterable[dict[str, Any]]) -> set[str]:
    """Return the set of exclusivity groups already occupied by *items*."""
    return occupied_groups(item.get("name", "") for item in items)


def _conflicts_with_build(
    candidate_name: str,
    occupied: set[str],
) -> bool:
    """Return True if *candidate_name* would violate an exclusivity group."""
    return conflicts_with_groups(candidate_name, occupied)


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
    work_counters: WorkCounterSink | None = None,
) -> float:
    """Evaluate a build, reusing this search's score for an exact repeat.

    Hill climbing re-proposes builds the greedy phase already scored (a swap
    trial that reverses an earlier improvement recreates a scored build).
    Scoring is deterministic for an identical ordered item list, so a repeat
    replays the recorded score and its ordering-audit contribution instead of
    re-simulating the roster.  The public receipts are byte-identical.

    This is also the campaign's proposal counter (runbook R-24): every
    candidate any regime proposes arrives here.  The memo *misses* are
    counted one layer down, in the function that pays for them.
    """
    if work_counters is not None:
        work_counters.measured_proposals += 1
    score_memo = combat_context.get("score_memo") if combat_context else None
    if score_memo is None:
        return _evaluate_build_uncached(
            champion_data,
            level,
            items,
            fight_params,
            objective,
            gold_budget=gold_budget,
            timeline_audit=timeline_audit,
            require_complete_timeline=require_complete_timeline,
            combat_context=combat_context,
            work_counters=work_counters,
        )
    memo_key = tuple(item["name"] for item in items)
    hit = score_memo.get(memo_key)
    # An entry recorded without an audit (the purchase baseline scores the
    # current loadout outside the candidate audit) carries no delta and no
    # withheld-build row; serving it to an audited caller would drop the
    # candidate from the receipts silently.  Re-evaluate instead — line
    # below overwrites the entry with a real delta.
    if hit is not None and timeline_audit is not None and hit[1] is None:
        hit = None
    if hit is not None:
        score, audit_delta = hit
        if timeline_audit is not None and audit_delta is not None:
            timeline_audit["evaluations"] += audit_delta["evaluations"]
            timeline_audit["partial_evaluations"] += audit_delta["partial_evaluations"]
            timeline_audit["excluded_evaluations"] += audit_delta[
                "excluded_evaluations"
            ]
            timeline_audit["exact_sources"].update(audit_delta["exact_sources"])
            timeline_audit["coarse_sources"].update(audit_delta["coarse_sources"])
            timeline_audit["excluded_sources"].update(audit_delta["excluded_sources"])
        return score
    audit_before = (
        None
        if timeline_audit is None
        else (
            timeline_audit["evaluations"],
            timeline_audit["partial_evaluations"],
            timeline_audit["excluded_evaluations"],
            set(timeline_audit["exact_sources"]),
            set(timeline_audit["coarse_sources"]),
            set(timeline_audit["excluded_sources"]),
        )
    )
    score = _evaluate_build_uncached(
        champion_data,
        level,
        items,
        fight_params,
        objective,
        gold_budget=gold_budget,
        timeline_audit=timeline_audit,
        require_complete_timeline=require_complete_timeline,
        combat_context=combat_context,
        work_counters=work_counters,
    )
    audit_delta = None
    if audit_before is not None:
        audit_delta = {
            "evaluations": timeline_audit["evaluations"] - audit_before[0],
            "partial_evaluations": (
                timeline_audit["partial_evaluations"] - audit_before[1]
            ),
            "excluded_evaluations": (
                timeline_audit["excluded_evaluations"] - audit_before[2]
            ),
            "exact_sources": timeline_audit["exact_sources"] - audit_before[3],
            "coarse_sources": timeline_audit["coarse_sources"] - audit_before[4],
            "excluded_sources": (timeline_audit["excluded_sources"] - audit_before[5]),
        }
    score_memo[memo_key] = (score, audit_delta)
    return score


def _evaluate_build_uncached(
    champion_data: dict[str, Any],
    level: int,
    items: list[dict[str, Any]],
    fight_params: FightParams | tuple[FightParams, ...],
    objective: str,
    gold_budget: int | None = None,
    timeline_audit: dict[str, Any] | None = None,
    require_complete_timeline: bool = False,
    combat_context: dict[str, Any] | None = None,
    work_counters: WorkCounterSink | None = None,
) -> float:
    """Evaluate a build and return the damage score for the given objective.

    Creates fresh copies of mutable state to avoid cross-call contamination.

    This is the simulation the search pays for, so it is where a memo miss is
    counted (R-24) — one increment in the function that does the work, rather
    than one beside every branch that decides to call it.
    """
    if work_counters is not None:
        work_counters.score_memo_misses += 1
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
        stats = base_params.pre_combat_stats(champion_data, level, items)
        defenses = resolve_starting_defenses(
            champion_data["name"],
            level,
            stats,
            items,
            item_options=base_params.item_options,
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
            pair_result_cache=combat_context.get("pair_result_cache"),
            search_context=combat_context.get("search_context"),
            # Typed objectives score from the serialized events list
            # below, so they need the full receipt; total damage scores
            # from the breakdown row and can take the scoring subset.
            include_receipt=objective in ("physical_damage", "magic_damage"),
            # Nobody reads this payload.  A search evaluates thousands of
            # candidates and shows none of them, so the parallel
            # dispositions map would be a few hundred dict entries per
            # evaluation describing a payload that is compared and thrown
            # away -- which the phase's allocation gate measures and
            # refuses.  Said here, at the one call site it is true of,
            # rather than assumed inside a view on every caller's behalf.
            published=False,
            # ``stats`` above used this exact configuration; the claim
            # only holds when no external ally bonuses were folded in,
            # because pair fights strip those.
            reuse_main_stats=not base_params.ally_stat_bonuses,
        )
        coverage = combat.get("timeline_coverage", {})
        excluded_sources = (
            applicability_exclusion_sources(coverage)
            if require_complete_timeline
            else []
        )
        if timeline_audit is not None:
            timeline_audit["evaluations"] += 1
            timeline_audit["exact_sources"].update(coverage.get("exact_sources", []))
            # Coupled searches score through this full participant timeline.
            # Keep its receipt attached to the exact build so the public
            # ranked row cannot later substitute a raw pair-fight receipt.
            timeline_audit.setdefault("build_coverages", {})[
                _build_receipt_key(items)
            ] = dict(coverage)
            if excluded_sources:
                # These three item packets have correct aggregate damage but
                # no sourced hit boundary in a generic cast.  They are safe
                # to exclude before ranking, unlike an unknown partial source.
                # Keep the full coarse receipt on the candidate row while
                # keeping the search-level certification about scored builds.
                timeline_audit["excluded_evaluations"] += 1
                timeline_audit["excluded_sources"].update(excluded_sources)
                timeline_audit.setdefault("withheld_builds", {})[
                    _build_receipt_key(items)
                ] = _public_build_receipt(
                    items,
                    coverage,
                    "candidate_excluded_unresolved_timing",
                    exclusion_type="applicability",
                )
            else:
                timeline_audit["coarse_sources"].update(
                    coverage.get("coarse_sources", [])
                )
            if not coverage.get("complete", False) and not excluded_sources:
                timeline_audit["partial_evaluations"] += 1
                # The reason names the disposition: under a complete-timeline
                # requirement this candidate is dropped from ranking just
                # below, while otherwise it stays ranked with a partial
                # receipt.  One code per disposition, like its siblings.
                timeline_audit.setdefault("withheld_builds", {})[
                    _build_receipt_key(items)
                ] = _public_build_receipt(
                    items,
                    coverage,
                    (
                        "candidate_withheld_partial_event_order"
                        if require_complete_timeline
                        else "partial_event_order"
                    ),
                )
        if require_complete_timeline and not coverage.get("complete", False):
            # A coupled optimizer must never rank a candidate whose own
            # timeline is only phase-ordered.  Exclude it from the search and
            # let the caller apply the best fully ordered candidate instead of
            # withholding the entire main build because another candidate was
            # ineligible for exact scoring.
            return float("-inf")
        # A coupled roster may contain a sourced champion effect whose exact
        # sub-hit cadence is not yet certified.  Keep the candidate usable,
        # but preserve the partial receipt so the result cannot be presented
        # as a fully certified BIS claim.
        main_row = next(
            (
                row
                for row in combat.get("breakdown", [])
                if row.get("participant_id") == "main"
            ),
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
            cutoff = (
                base_params.fight_duration_seconds if death_time is None else death_time
            )
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
            cutoff = (
                base_params.fight_duration_seconds if death_time is None else death_time
            )
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
            # receipt component describing that survival window; it is not
            # part of the primary damage score.
            primary_score = float(main_row.get("total_damage", 0.0))
        else:
            primary_score = float(main_row.get("total_damage", 0.0))

        # Equal-damage coupled builds still need a deterministic, sourced
        # decision.  Damage is capped by a kill, so every build that clears
        # the roster inside the window deals the same total; rank those by
        # how much window remains after each enemy death (faster kill first)
        # and only then by the buyer's effective health.  Both terms are
        # infinitesimal against the 0.1-damage receipt rounding, and the
        # kill term dominates the health term — otherwise the tie-break
        # elects tank items on a mage the moment every candidate build
        # secures the kill (the Warmog's-on-Syndra regression).
        if timeline_audit is not None:
            main_survival = next(
                (
                    row.get("survival", {})
                    for row in combat.get("participants", [])
                    if row.get("participant_id") == "main"
                ),
                {},
            )
            effective_health = max(
                0.0, float(main_survival.get("effective_health", 0.0))
            )
            duration = base_params.fight_duration_seconds
            kill_margin = sum(
                duration - float(row["survival"]["death_time"])
                for row in combat.get("participants", [])
                if row.get("team") == "enemy"
                and row.get("survival", {}).get("death_time") is not None
            )
            return primary_score + kill_margin * 1e-4 + effective_health * 1e-9
        return primary_score
    results: list[dict[str, Any]] = []
    for target_params in targets:
        result = run_fight(champion_data, level, items, target_params)
        results.append(result)
    coverage = _combined_build_timeline_coverage(results)
    excluded_sources = (
        applicability_exclusion_sources(coverage) if require_complete_timeline else []
    )
    if timeline_audit is not None:
        timeline_audit["evaluations"] += 1
        timeline_audit["exact_sources"].update(coverage["exact_sources"])
        if excluded_sources:
            timeline_audit["excluded_evaluations"] += 1
            timeline_audit["excluded_sources"].update(excluded_sources)
            timeline_audit.setdefault("withheld_builds", {})[
                _build_receipt_key(items)
            ] = _public_build_receipt(
                items,
                coverage,
                "candidate_excluded_unresolved_timing",
                exclusion_type="applicability",
            )
        else:
            timeline_audit["coarse_sources"].update(coverage["coarse_sources"])
        if not coverage["complete"] and not excluded_sources:
            timeline_audit["partial_evaluations"] += 1
            # Same disposition split as the coupled path above: dropped from
            # ranking under a complete-timeline requirement, kept with a
            # partial receipt otherwise.
            timeline_audit.setdefault("withheld_builds", {})[
                _build_receipt_key(items)
            ] = _public_build_receipt(
                items,
                coverage,
                (
                    "candidate_withheld_partial_event_order"
                    if require_complete_timeline
                    else "partial_event_order"
                ),
            )
    if require_complete_timeline and not coverage["complete"]:
        return float("-inf")

    def included(entry: Mapping[str, Any]) -> bool:
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


def _build_receipt_key(items: Iterable[dict[str, Any]]) -> tuple[str, ...]:
    """Identify one evaluated build by the ordered list the score memo keys on."""
    return tuple(str(item.get("name", "")) for item in items)


def _public_build_receipt(
    items: Iterable[dict[str, Any]],
    coverage: dict[str, Any],
    reason: str,
    *,
    exclusion_type: str | None = None,
) -> dict[str, Any]:
    """Serialize one candidate withheld before ranking as an audit row."""
    boots = next(
        (
            str(item.get("name", ""))
            for item in items
            if "BOOTS" in item.get("rank", [])
        ),
        None,
    )
    receipt = {
        "items": [
            str(item.get("name", ""))
            for item in items
            if "BOOTS" not in item.get("rank", [])
        ],
        "boots": boots,
        "timeline_coverage": dict(coverage),
        "reason": str(reason),
    }
    if exclusion_type is not None:
        receipt["exclusion_type"] = str(exclusion_type)
    return receipt


def _public_search_timeline_coverage(audit: Mapping[str, Any]) -> dict[str, Any]:
    """Serialize precision across every candidate evaluation in this search."""
    evaluations = int(audit["evaluations"])
    partial_evaluations = int(audit["partial_evaluations"])
    excluded_evaluations = int(audit.get("excluded_evaluations", 0))
    coarse_sources = sorted(audit["coarse_sources"])
    exact_sources = sorted(set(audit["exact_sources"]) - set(coarse_sources))
    scored_evaluations = max(0, evaluations - excluded_evaluations)
    excluded_sources = sorted(audit.get("excluded_sources", set()))
    complete = scored_evaluations > 0 and partial_evaluations == 0
    if complete:
        note = f"All {scored_evaluations:,} scored candidate evaluations are event-ordered."
        if excluded_evaluations:
            names = ", ".join(excluded_sources) or "audited item timing"
            note += (
                f" {excluded_evaluations:,} candidate evaluations were excluded "
                f"before ranking ({names})."
            )
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
            (
                "candidate_event_order_certified_with_exclusions"
                if excluded_evaluations
                else "candidate_event_order_certified"
            )
            if complete
            else "partial_candidate_event_order"
        ),
        "evaluations": evaluations,
        "scored_evaluations": scored_evaluations,
        "excluded_evaluations": excluded_evaluations,
        "partial_evaluations": partial_evaluations,
        "exact_sources": exact_sources,
        "coarse_sources": coarse_sources,
        "excluded_sources": excluded_sources,
        "note": note,
    }


def item_gold(item: Mapping[str, Any]) -> int:
    """Return the sourced total shop price, failing closed on a broken record.

    ``shop.prices.total`` is cache-owned; a literal default here would make
    an item free the moment the parser stopped writing its price.
    """
    name = str(item.get("name") or "Unknown item")
    prices = item.get("shop", {}).get("prices", {})
    if "total" not in prices:
        raise KeyError(f"{name}: shop.prices.total")
    price = int(prices["total"])
    if price <= 0:
        raise ValueError(f"{name}: shop.prices.total must be positive")
    return price


def _build_gold(items: Iterable[dict[str, Any]]) -> int:
    """Return total shop price for a resolved build."""
    return sum(item_gold(item) for item in items)


def _greedy_fill(
    champion_data: dict[str, Any],
    level: int,
    locked_legendaries: list[dict[str, Any]],
    locked_boots: dict[str, Any] | None,
    slots_to_fill: int,
    fill_boots: bool,
    pool: Iterable[dict[str, Any]],
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
    build_groups = _get_occupied_groups(current)

    while len(current) < len(locked_legendaries) + slots_to_fill:
        best_score = -1.0
        best_item = None

        for candidate in pool:
            name = candidate["name"]
            if name in used_names:
                continue
            # Enforce exclusivity groups
            if _conflicts_with_build(name, build_groups):
                continue

            trial_items = [*current, candidate]
            if boots:
                trial_items = [boots, *trial_items]

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
        build_groups.update(ITEM_TO_EXCLUSIVITY_GROUPS.get(best_item["name"], ()))

    # Fill boots if needed
    if fill_boots and boots_pool:
        best_score = -1.0
        best_boots = None
        for candidate in boots_pool:
            trial_items = [candidate, *current]
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
    locked_legendary_names: Collection[str],
    locked_boots: bool,
    pool: Iterable[dict[str, Any]],
    boots_pool: list[dict[str, Any]],
    eval_kwargs: dict[str, Any],
    max_iterations: int = 10,
    initial_score: float | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, float, int]:
    """Iteratively swap items to improve the build. Returns (legendaries, boots, score, evals)."""
    current = list(legendaries)
    current_boots = boots
    evals = 0

    all_items = ([current_boots] if current_boots else []) + current
    if initial_score is None:
        best_score = _evaluate_build(
            champion_data,
            level,
            all_items,
            **eval_kwargs,
        )
        evals += 1
    else:
        # Greedy fill already evaluated this exact ordered build. Reuse its
        # score; no state is mutated by scoring, so this only removes a
        # duplicate coupled timeline evaluation.
        best_score = initial_score

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
                trial_items = [candidate, *current]
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


_LEGAL_LOCKED_RANKS = {"BASIC", "EPIC", "LEGENDARY", "STARTER"}


def _legal_locked_shop_item(item: dict[str, Any]) -> bool:
    """Whether an item may be locked in an optimizer inventory.  Shop
    availability is not enough, since a consumable is buyable and is not a
    final-build item.
    """
    if not is_ordinary_sr_item(item):
        return False
    ranks = {str(rank).upper() for rank in item.get("rank", []) or []}
    return bool(ranks & _LEGAL_LOCKED_RANKS)


def get_purchase_items(role: str = "") -> list[dict[str, Any]]:
    """Return ordinary modeled singles for the purchase search.

    Components (BASIC/EPIC) plus role-scoped legendaries.  Boots stay in a
    separate pool and transformation items are excluded by ``is_purchasable``
    at the search site, never by this helper.
    """
    supported = optimizer_supported_items(_ordinary_sr_items())
    components = [
        item
        for item in supported
        if {"BASIC", "EPIC"}.intersection(item.get("rank", []))
        and "BOOTS" not in item.get("rank", [])
    ]
    legendaries = role_scoped_shop_items(
        [
            item
            for item in supported
            if "LEGENDARY" in item.get("rank", [])
            and "BOOTS" not in item.get("rank", [])
        ],
        role,
    )
    return components + legendaries


class _PurchaseSearch:
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
                role=self.role,
                role_quest_complete=self.role_quest_complete,
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
        score = _evaluate_build(
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


def _enumerate_affordable_shapes(
    search: _PurchaseSearch,
    sell: dict[str, Any] | None,
    buyables: Sequence[dict[str, Any]],
    cap: int,
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
    search: _PurchaseSearch,
    sell: dict[str, Any] | None,
    buyables: Iterable[dict[str, Any]],
    per_gold: bool,
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
    search: _PurchaseSearch,
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


def _score_exhaustive_purchase_plans(
    search: _PurchaseSearch,
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


def _run_purchase_local_search(
    search: _PurchaseSearch,
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
            optimizer_supported_items(get_eligible_legendaries()), role
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
        for item in get_purchase_items(role)
        if is_purchasable(item, include_starters=include_starters)
        and item["name"] not in owned_names
    ]
    boot_pool = []
    if include_boots and owned_boots is None:
        boot_pool = [
            item
            for item in optimizer_supported_items(get_eligible_boots(tier=boots_tier))
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

    search = _PurchaseSearch(
        champion_data,
        level,
        owned,
        owned_boots,
        available_gold,
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
        return _evaluate_build(
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
        shapes, sell_complete = _enumerate_affordable_shapes(
            search, sell, buyables, candidate_cap, len(shape_rows)
        )
        shape_rows.extend((sell, shape) for shape in shapes)
        if not sell_complete:
            exhaustive_complete = False
            break

    if exhaustive_complete:
        truncated = _score_exhaustive_purchase_plans(search, shape_rows, pool_names)
    else:
        truncated = _run_purchase_local_search(search, sell_options, buyables)

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

    candidate_coverage = optimizer_candidate_coverage(buyables)
    search_coverage = _public_search_timeline_coverage(timeline_audit)
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
                "recommendation_type": _plan_type(plan),
                "spent_gold": spend,
                "sell_refund": plan.refund,
                "remaining_gold": plan.remaining,
                "total_damage": round(score, 1),
                "price_rows": [row.to_dict() for row in plan.price_rows],
                "timeline_coverage": _build_timeline_coverage(
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
        "recommendation_type": _plan_type(best_plan),
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


def _plan_key(plan: Any) -> tuple[tuple[str, ...], str | None]:
    """Canonical final-loadout key for score memoization."""
    names = tuple(sorted(item["name"] for item in plan.final_items))
    return (names, plan.final_boots["name"] if plan.final_boots else None)


def _plan_type(plan: Any) -> str:
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


def _optimize_dispositions(payload: dict[str, Any]) -> dict[str, dict[str, object]]:
    """Name every number in the whole optimize payload, as the ranking it is."""
    return name_every_number(payload, RankingWriter())


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
    legal_legendaries = get_eligible_legendaries()
    legal_boots = get_eligible_boots(tier=boots_tier)
    base_params = fight_params[0] if isinstance(fight_params, tuple) else fight_params
    # The main champion uses the same sourced role-shop boundary as roster BIS,
    # so a top-lane main search cannot rank a support-only item such as
    # Shurelya's Battlesong.  No archetype or stat heuristic is added here.
    all_legendaries = role_quest_legal_items(
        role_scoped_shop_items(
            optimizer_supported_items(legal_legendaries), base_params.role
        ),
        base_params.role,
        base_params.role_quest_complete,
    )
    all_boots = optimizer_supported_items(legal_boots)

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
                or _build_timeline_coverage(
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
    candidate_coverage = optimizer_candidate_coverage(coverage_candidates)
    search_timeline_coverage = _public_search_timeline_coverage(timeline_audit)
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
