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
from .item_source import is_ordinary_sr_item
from .loadout_rules import (
    ITEM_EXCLUSIVITY_GROUPS,
    ITEM_TO_EXCLUSIVITY_GROUPS,
    conflicts_with_groups,
    exclusivity_groups,
    occupied_groups,
    inventory_capacity,
    role_quest_legal_items,
    role_scoped_shop_items,
    validate_resolved_loadout,
)
from .pipeline import FightParams, run_fight
from .defensive_effects import resolve_starting_defenses
from .participant_timeline import CoupledSearchContext, build_participant_timeline
from .stats import calculate_total_stats
from .timeline_coverage import (
    applicability_exclusion_sources,
    combine_timeline_coverages,
)

# Item exclusivity groups — at most one item from each group per build
# (e.g. Spellblade items are mutually exclusive in-game). This table is
# the single source of truth: the frontend fetches it via /api/config
# (see exclusivity_groups() below) instead of keeping its own copy.
# Keep the old name for test imports.
_SPELLBLADE_ITEMS = ITEM_EXCLUSIVITY_GROUPS["Spellblade"]


def _ordinary_sr_items() -> list[dict[str, Any]]:
    """Every cached item an ordinary Summoner's Rift build can hold.

    Availability comes from the cached source data — map/mode table, champion
    restriction, acquisition — through ``item_source``, so an ARAM starter or
    a champion-granted item leaves the pool because the sources say so, not
    because someone remembered to add its name to a list.
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
    """Evaluate a build, reusing this search's score for an exact repeat.

    Hill climbing re-proposes builds the greedy phase already scored (a swap
    trial that reverses an earlier improvement recreates a scored build).
    Scoring is deterministic for an identical ordered item list, so a repeat
    replays the recorded score and its ordering-audit contribution instead of
    re-simulating the roster.  The public receipts are byte-identical.
    """
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
        )
    memo_key = tuple(item["name"] for item in items)
    hit = score_memo.get(memo_key)
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
            champion_data["name"],
            level,
            stats,
            items,
            item_options=base_params.item_options,
        )
        try:
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
                # ``stats`` above used this exact configuration; the claim
                # only holds when no external ally bonuses were folded in,
                # because pair fights strip those.
                reuse_main_stats=not base_params.ally_stat_bonuses,
            )
        except ValueError as exc:
            # A candidate can introduce a target-state interaction that is
            # deliberately fail-closed by the fight engine (for example,
            # Protoplasm's temporary maximum-health expiry combined with an
            # enemy max-health ability).  That makes this candidate ineligible
            # for this exact search; it must not abort every other legal build.
            # Keep unrelated validation errors visible to the API caller.
            if "Protoplasm Harness" not in str(exc):
                raise
            if timeline_audit is not None:
                coverage = {
                    "complete": False,
                    "certification": "partial_candidate_event_order",
                    "exact_sources": [],
                    "coarse_sources": ["target_Protoplasm Harness"],
                    "note": "Candidate rejected by a target-state interaction.",
                }
                timeline_audit["evaluations"] += 1
                timeline_audit["partial_evaluations"] += 1
                timeline_audit["coarse_sources"].add("target_Protoplasm Harness")
                timeline_audit.setdefault("withheld_builds", {})[
                    _build_receipt_key(items)
                ] = _public_build_receipt(
                    items, coverage, "candidate_rejected_target_state"
                )
            return float("-inf")
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
                timeline_audit.setdefault("withheld_builds", {})[
                    _build_receipt_key(items)
                ] = _public_build_receipt(items, coverage, "partial_event_order")
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
        # decision.  Use the timeline's own effective-health receipt as an
        # infinitesimal tie-break only; it cannot change a material damage
        # ordering or the public rounded score.  This prevents an unrelated
        # AP item from winning merely because it appeared earlier in the
        # candidate list when the target was already dead at the first event.
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
            return primary_score + effective_health * 1e-9
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
            timeline_audit.setdefault("withheld_builds", {})[
                _build_receipt_key(items)
            ] = _public_build_receipt(items, coverage, "partial_event_order")
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


def _build_receipt_key(items: list[dict[str, Any]]) -> tuple[str, ...]:
    """Identify one evaluated build in the search receipt cache.

    The optimizer's score memo uses the ordered item list (boots first when
    present), so the coverage receipt must use that same identity.  Keeping
    this key local to the optimizer avoids exposing internal candidate state
    in the public response.
    """
    return tuple(str(item.get("name", "")) for item in items)


def _public_build_receipt(
    items: list[dict[str, Any]],
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


def _public_search_timeline_coverage(audit: dict[str, Any]) -> dict[str, Any]:
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


_LEGAL_LOCKED_RANKS = {"BASIC", "EPIC", "LEGENDARY", "STARTER"}


def _legal_locked_shop_item(item: dict[str, Any]) -> bool:
    """Return whether an item may be locked in an optimizer inventory.

    Ordinary-shop availability is not enough: consumables (POTION,
    CONSUMABLE) are buyable in the shop but are not final-build items.
    """
    if not is_ordinary_sr_item(item):
        return False
    ranks = {str(rank).upper() for rank in item.get("rank", []) or []}
    return bool(ranks & _LEGAL_LOCKED_RANKS)


def _required_item_gold(item: dict[str, Any]) -> int:
    """Return sourced total price, failing closed instead of making an item free."""
    name = str(item.get("name") or "Unknown item")
    prices = item.get("shop", {}).get("prices", {})
    if "total" not in prices:
        raise KeyError(f"{name}: shop.prices.total")
    price = int(prices["total"])
    if price <= 0:
        raise ValueError(f"{name}: shop.prices.total must be positive")
    return price


def get_purchase_items(role: str = "") -> list[dict[str, Any]]:
    """Return ordinary modeled singles for the one/two-purchase search.

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


def optimize_purchase(
    champion_data: dict[str, Any],
    level: int,
    *,
    available_gold: int,
    fight_params: FightParams | None = None,
    objective: str = "total_damage",
    locked_items: list[str] | None = None,
    locked_boots: str | None = None,
    max_purchase_items: int = 2,
    target_fight_params: tuple[FightParams, ...] | None = None,
    boots_tier: int = 2,
    require_complete_timeline: bool = True,
    enemy_loadouts: list[Any] | None = None,
    ally_loadouts: list[Any] | None = None,
    include_boots: bool = True,
    candidate_cap: int = 2500,
    allow_sell: bool = False,
    max_sell_items: int = 1,
    combine_policy: str = "shop_combine",
    include_starters: bool = False,
    time_budget_ms: int = 12_000,
) -> dict[str, Any]:
    """Rank real-shop purchase plans (buy / combine / sell) by combat value.

    Every plan is priced by the shop model (list-price buys, explicit
    combine fees, 40%-refund-era exceptions replaced by the sourced 70% sell
    table) and scored on its *resolved final loadout* through the existing
    event-order-certified fight pipeline.  Owned items are preserved unless a
    plan sells them.

    Certification is scoped honestly: ``exhaustive_within_scope`` is true
    only when every generated plan was evaluated and both model and timeline
    coverage are complete; otherwise the claim downgrades to
    ``best_evaluated_plan``.
    """
    from .economy import (
        apply_purchase_plan,
        combine_candidates,
        is_purchasable,
        is_stackable,
        item_sell_value,
        item_total,
        validate_economy_loadout,
        _item_by_id,
    )

    if available_gold < 1:
        raise ValueError("available_gold must be at least 1")
    if max_purchase_items not in (1, 2):
        raise ValueError("max_purchase_items must be 1 or 2")
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
        _required_item_gold(item)
        owned.append(item)
    owned_boots = None
    if locked_boots:
        if not include_boots:
            raise ValueError("locked_boots cannot be used when include_boots is false")
        owned_boots = get_item_by_name(locked_boots)
        if not is_ordinary_sr_item(owned_boots):
            raise ValueError(f"{locked_boots} is not an ordinary shop item")
        require_optimizer_item_coverage(owned_boots)
        _required_item_gold(owned_boots)
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
    component_pool = [
        item for item in pool if {"BASIC", "EPIC"}.intersection(item.get("rank", []))
    ]
    boot_pool = []
    if include_boots and owned_boots is None:
        boot_pool = [
            item
            for item in optimizer_supported_items(get_eligible_boots(tier=boots_tier))
            if is_purchasable(item) and item["name"] not in owned_names
        ]

    # ---- plan shapes -------------------------------------------------------
    # (sell_name | None, buys: list[str], combine_name | None)
    sell_options: list[str | None] = [None]
    if allow_sell and max_sell_items >= 1:
        sell_options.extend(item["name"] for item in owned)
        if owned_boots is not None:
            sell_options.append(owned_boots["name"])

    buy_shapes: list[list[str]] = [[]]
    if max_purchase_items >= 1:
        buy_shapes.extend([item["name"]] for item in pool)
        buy_shapes.extend([boot["name"]] for boot in boot_pool)
    if max_purchase_items >= 2:
        for left_index, left in enumerate(component_pool):
            for right_index, right in enumerate(component_pool):
                if right_index < left_index:
                    continue
                if left_index == right_index and not is_stackable(left):
                    continue
                buy_shapes.append([left["name"], right["name"]])
        for item in pool:
            for boot in boot_pool:
                buy_shapes.append([item["name"], boot["name"]])

    raw_plans: list[tuple[str | None, list[str], str | None]] = []
    for sell_name in sell_options:
        for buys in buy_shapes:
            raw_plans.append((sell_name, buys, None))
    # Add combine completion plans for every inventory reachable by a shape.
    extended: list[tuple[str | None, list[str], str | None]] = []
    by_name = {item["name"]: item for item in [*owned, *pool, *boot_pool]}
    for sell_name, buys, _combine in raw_plans:
        extended.append((sell_name, buys, None))
        inventory = {}
        for item in owned:
            if item["name"] == sell_name:
                continue
            inventory[int(item["id"])] = inventory.get(int(item["id"]), 0) + 1
        for buy_name in buys:
            buy = by_name.get(buy_name)
            if buy is None:
                continue
            if "BOOTS" in {str(r).upper() for r in buy.get("rank", []) or []}:
                continue
            inventory[int(buy["id"])] = inventory.get(int(buy["id"]), 0) + 1
        for combine_id, _demand, _fee in combine_candidates(inventory, _item_by_id()):
            combine_name = _item_by_id()[combine_id]["name"]
            if combine_name not in {item["name"] for item in pool}:
                continue
            extended.append((sell_name, buys, combine_name))
    raw_plans = extended

    # ---- apply the shop model to every raw plan ----------------------------
    by_name_full = {item["name"]: item for item in [*owned, *pool, *boot_pool]}
    plan_rows: list[tuple[Any, int]] = []  # (plan, spend)
    for sell_name, buys, combine_name in raw_plans:
        sells = [by_name_full[sell_name]] if sell_name else None
        purchase_objs = [by_name_full[name] for name in buys if name in by_name_full]
        combine_objs = [by_name_full[combine_name]] if combine_name else None
        try:
            plan = apply_purchase_plan(
                owned,
                owned_boots,
                purchase_objs,
                available_gold,
                sell_items=sells,
                combine_items=combine_objs,
                combine_policy=combine_policy,
                role=role,
                role_quest_complete=role_quest_complete,
            )
        except (KeyError, ValueError, LookupError):
            continue
        try:
            validate_economy_loadout(
                plan,
                role=role,
                role_quest_complete=role_quest_complete,
            )
        except ValueError:
            continue
        plan_rows.append((plan, plan.spend))

    plan_rows.sort(key=lambda row: (row[1], _plan_key(row[0])))
    truncated = len(plan_rows) > candidate_cap
    plan_rows = plan_rows[:candidate_cap]

    if not plan_rows:
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
            "candidate_count": 0,
            "evaluations": 0,
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
                "search_context": CoupledSearchContext(),
            }
        )

    def current_loadout_score() -> float | None:
        current_items = ([owned_boots] if owned_boots else []) + owned
        if not current_items:
            return None
        return _evaluate_build(
            champion_data,
            level,
            current_items,
            fight_params=params,
            objective=objective,
            timeline_audit=timeline_audit,
            require_complete_timeline=require_complete_timeline,
            combat_context=combat_context,
        )

    current_score = current_loadout_score()

    scored: list[tuple[float, Any, int]] = []
    memo: dict[tuple[tuple[str, ...], str | None], float] = {}
    evaluations = 0
    for plan, spend in plan_rows:
        if time.perf_counter() - started > time_budget_ms / 1000:
            truncated = True
            break
        key = _plan_key(plan)
        if key in memo:
            score = memo[key]
        else:
            build_items = (
                [plan.final_boots] if plan.final_boots else []
            ) + plan.final_items
            score = _evaluate_build(
                champion_data,
                level,
                build_items,
                fight_params=params,
                objective=objective,
                timeline_audit=timeline_audit,
                require_complete_timeline=require_complete_timeline,
                combat_context=combat_context,
            )
            evaluations += 1
            memo[key] = score
        if math.isfinite(score):
            scored.append((score, plan, spend))
    if not scored:
        raise ValueError(
            "No complete legal event-ordered purchase fits the selected constraints"
        )
    scored.sort(key=lambda row: (-row[0], row[2], _plan_key(row[1])))

    coverage_pool = [
        item for item in [*pool, *boot_pool] if item["name"] not in owned_names
    ]
    candidate_coverage = optimizer_candidate_coverage(coverage_pool)
    search_coverage = _public_search_timeline_coverage(timeline_audit)
    exhaustive_within_scope = (
        not truncated and candidate_coverage["complete"] and search_coverage["complete"]
    )
    event_order_certified = search_coverage["complete"]

    best_score, best_plan, best_spend = scored[0]
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
    searched_space = (
        f"{'truncated ' if truncated else 'exhaustive '}"
        f"{{1-2 buys | 1 combine | {1 if allow_sell else 0} sell}} "
        f"within {available_gold:,} gold"
    )
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
        "candidate_count": len(plan_rows),
        "evaluations": evaluations,
        "optimization_time_ms": round((time.perf_counter() - started) * 1000, 1),
        "searched_space": searched_space,
        "exhaustive_within_scope": exhaustive_within_scope,
        "truncated": truncated,
        "certification": {
            "event_order": event_order_certified,
            "economy": True,
            "legality": True,
            "claim": (
                "certified_best_purchase_within_scope"
                if exhaustive_within_scope
                else "best_evaluated_plan"
            ),
        },
        "winner_event_order_certified": event_order_certified,
        "is_certified_best": exhaustive_within_scope,
        "search_guarantee": (
            "exhaustive_purchase_scope"
            if not truncated
            else "best_evaluated_plan_truncated"
        ),
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
    if len(plan.purchases) == 1:
        boots = plan.final_boots and not plan.final_items
        return "boots" if boots else "single_item"
    if len(plan.purchases) >= 2:
        return "component_set"
    return "single_item"


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
    }
    # Pairwise roster receipts that do not depend on the candidate main
    # build's offense are invariant across the search: roster-to-roster pairs
    # always, and fights into the candidate whenever its defensive signature
    # repeats.  The score memo replays exact repeated builds without
    # re-simulating.  Both caches live for this optimizer call only.
    if eval_kwargs["combat_context"] is not None:
        eval_kwargs["combat_context"]["pair_result_cache"] = {}
        eval_kwargs["combat_context"]["score_memo"] = {}
        eval_kwargs["combat_context"]["search_context"] = CoupledSearchContext()
    coupled_objective = bool(enemy_loadouts or ally_loadouts)

    # Build item pools.  Keep the complete legal lists for the public coverage
    # receipt, but only score candidates whose outgoing-damage mechanics are
    # represented by the fight model.
    legal_legendaries = get_eligible_legendaries()
    legal_boots = get_eligible_boots(tier=boots_tier)
    base_params = fight_params[0] if isinstance(fight_params, tuple) else fight_params
    # The main champion uses the same sourced role-shop boundary already used
    # by roster BIS.  Previously only /api/bis applied this filter, allowing a
    # top-lane main search to rank support-only items such as Shurelya's
    # Battlesong.  No archetype or stat heuristic is added here.
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
                _required_item_gold(item)
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
            f"constraints{constraint} for "
            f"{champion_data.get('name', 'the selected champion')}; this champion's current "
            "event package has no complete candidate timeline"
        )
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
