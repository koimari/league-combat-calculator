"""Best-in-slot application boundary and domain policy.

The BIS endpoint (/api/bis) is an objective selector over the coupled
participant event timeline, not a second stat-only optimizer.  Keeping the
objective contract, candidate orchestration, sorting, and receipt assembly in
this module means the API and any future consumer cannot silently disagree.
Flask owns only HTTP decoding, cache/rate policy, and error translation.

Every number in a receipt is published beside a disposition entry, so the
dispositions map walks the whole payload rather than two named leaves:
``components.*`` and the stat block are what the objective is folded from, and
naming only ``score`` and ``objective_value`` leaves them with no entry.  Every
member is re-written at the path it lives at, so each row stays byte-identical
and each entry is produced beside its leaf by ``serialize_leaf``.
``program.views.RankingWriter`` writes them, so a block a view opened
``THEORETICAL`` may not reach a ranking; the read half of that rule is
``program.views.refuse_previewed``, which ``bis_objective_score`` runs over
each candidate's combat map before folding a score out of it.
"""

import time
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import replace
from typing import Any

from .bis_candidates import (
    bis_candidate_pool,
    bis_main_request,
    bis_replaced_loadout,
    roster_target_coverage,
)
from .bis_objective import (
    BIS_UNMODELED_DEFENSIVE_EFFECTS,
    _bis_coverage_receipt,
    _bis_dispositions,
    _withheld_candidate,
    bis_defensive_effect_receipt,
    bis_objective_meta,
    bis_objective_score,
)
from .champion_loadout import MAX_LOADOUT_ITEMS
from .interpreters import survival_ledger_certifications
from .item_effects import validate_item_input_options
from .optimizer_candidates import item_gold
from .participant_timeline import CoupledSearchContext, build_participant_timeline
from .public_response import https_icon
from .request_parsing import request_int, request_string
from .role_quests import required_boots_tier
from .scenario import parse_scenario_request, resolve_scenario
from .timeline_coverage import applicability_exclusion_sources


def bis_payload(
    data: Mapping[str, object],
    *,
    pair_result_cache: dict | None = None,
    search_context: CoupledSearchContext | None = None,
) -> dict[str, Any]:
    """Rank one slot and return the complete JSON-safe BIS receipt."""
    request = parse_scenario_request(data, deterministic=True, parse_crossover=False)
    subject_team = request_string(data, "subject_team", "main")
    if subject_team not in {"main", "ally", "enemy"}:
        raise ValueError("subject_team must be main, ally, or enemy")
    slot_index = request_int(
        data, "slot_index", 0, minimum=0, maximum=MAX_LOADOUT_ITEMS - 1
    )
    slot_kind = request_string(data, "slot_kind", "item")
    if slot_kind not in {"item", "boots"}:
        raise ValueError("slot_kind must be item or boots")
    subject_index = request_int(data, "subject_index", 0, minimum=0, maximum=4)
    objective_meta = bis_objective_meta(request_string(data, "objective", "overall"))
    objective_key = objective_meta["key"]
    max_item_gold = (
        request_int(data, "max_item_gold", 0, minimum=0, maximum=30_000)
        if data.get("max_item_gold") not in (None, "")
        else None
    )
    if subject_team == "ally" and subject_index >= len(request.allies):
        raise ValueError("subject_index is outside the selected ally roster")
    if subject_team == "enemy" and subject_index >= len(request.enemies):
        raise ValueError("subject_index is outside the selected enemy roster")

    resolved = resolve_scenario(request)
    main_request = bis_main_request(request, data)
    main_loadout = main_request.resolve()
    candidate_item_options = validate_item_input_options(
        data.get("candidate_item_options")
    )
    enemies = list(resolved.enemies)
    allies = list(resolved.allies)
    subject_base = (
        main_request
        if subject_team == "main"
        else (
            request.allies[subject_index]
            if subject_team == "ally"
            else request.enemies[subject_index]
        )
    )
    if subject_team != "main" and not subject_base.role:
        raise ValueError(
            f"{subject_team} role is required before roster BIS can be scored"
        )
    subject_id = (
        "main" if subject_team == "main" else f"{subject_team}:{subject_base.champion}"
    )
    role = subject_base.role
    candidates = bis_candidate_pool(
        slot_kind,
        boots_tier=required_boots_tier(role, subject_base.role_quest_complete),
        role=role,
        role_quest_complete=subject_base.role_quest_complete,
    )
    equipped_slot_item = (
        subject_base.boots
        if slot_kind == "boots"
        else (
            subject_base.items[slot_index]
            if slot_index < len(subject_base.items)
            else ""
        )
    )
    if equipped_slot_item:
        candidates = [
            candidate
            for candidate in candidates
            if candidate.get("name") != equipped_slot_item
        ]

    budget_excluded_count = 0
    if max_item_gold is not None:
        affordable = [item for item in candidates if item_gold(item) <= max_item_gold]
        budget_excluded_count = len(candidates) - len(affordable)
        candidates = affordable

    ranked: list[dict] = []
    withheld: list[dict[str, object]] = []
    target_filtered: list[dict[str, object]] = []
    fight_params = resolved.fight_params
    # The candidate receipt exposes survival, breakdown, and coverage only.
    # Reuse fixed roster packets across the candidate loop.  The compiled
    # walk is safe for a main-slot search because its roster stays fixed.  A
    # roster-slot search still gets the pair cache, whose key includes the
    # changing actor's full loadout signature.
    if pair_result_cache is None:
        pair_result_cache = {}
    # A candidate is ranked on the receipt's objective block, which the
    # compiled score projection does not carry, so BIS never creates a
    # search context of its own; one handed in by a caller still applies
    # only to a fixed-roster main-slot search.
    if candidate_item_options or subject_team != "main":
        search_context = None
    for candidate in candidates:
        try:
            candidate_params = fight_params
            candidate_options = candidate_item_options.get(candidate["name"])
            if candidate_options:
                candidate_params = replace(
                    fight_params,
                    item_options={
                        **(fight_params.item_options or {}),
                        candidate["name"]: candidate_options,
                    },
                )
            candidate_request = bis_replaced_loadout(
                subject_base,
                slot_index=slot_index,
                slot_kind=slot_kind,
                candidate_name=candidate["name"],
                candidate_item_options=candidate_options,
            )
            resolved_subject = candidate_request.resolve()
            candidate_main = (
                resolved_subject if subject_team == "main" else main_loadout
            )
            candidate_enemies = list(enemies)
            candidate_allies = list(allies)
            if subject_team == "enemy":
                candidate_enemies[subject_index] = resolved_subject
            elif subject_team == "ally":
                candidate_allies[subject_index] = resolved_subject
            blocked_targets = roster_target_coverage(
                [*candidate_enemies, *candidate_allies]
            )
            if blocked_targets:
                target_filtered.extend(blocked_targets)
                withheld.append(
                    _withheld_candidate(
                        candidate,
                        reason="target_coverage_blocked",
                        detail=None,
                        timeline_coverage={
                            "complete": False,
                            "certification": "target_coverage_blocked",
                            "exact_sources": [],
                            "coarse_sources": [],
                            "note": (
                                "Candidate was not evaluated because a selected "
                                "roster item is outside the sourced target model."
                            ),
                        },
                        target_coverage=blocked_targets,
                    )
                )
                continue
            focus_id = "main" if subject_team == "main" else subject_id
            combat = build_participant_timeline(
                candidate_main.champion_data,
                candidate_main.request.level,
                list(candidate_main.item_data),
                candidate_params,
                main_stats=candidate_main.stats,
                main_defenses=candidate_main.defenses,
                enemies=candidate_enemies,
                allies=candidate_allies,
                focus_participant_id=focus_id,
                pair_result_cache=pair_result_cache,
                reuse_main_stats=(
                    subject_team == "main" and not candidate_params.ally_stat_bonuses
                ),
                search_context=search_context,
            )
            coverage = combat.get("timeline_coverage", {})
            timing_exclusions = applicability_exclusion_sources(coverage)
            if timing_exclusions:
                names = ", ".join(timing_exclusions)
                withheld.append(
                    _withheld_candidate(
                        candidate,
                        reason="candidate_excluded_unresolved_timing",
                        exclusion_type="applicability",
                        excluded_sources=timing_exclusions,
                        detail=(
                            "Candidate was excluded before BIS ranking because "
                            f"{names} has no sourced hit boundary for this rotation."
                        ),
                        timeline_coverage=coverage,
                    )
                )
                continue
            objective = combat["objective"]
            focus = next(
                row
                for row in combat["participants"]
                if row["participant_id"] == focus_id
            )
            score, metric, components, rank_key = bis_objective_score(
                objective_key,
                subject_team=subject_team,
                focus_id=focus_id,
                combat=combat,
                objective=objective,
                focus=focus,
            )
            ranked.append(
                {
                    "name": candidate["name"],
                    "icon": https_icon(candidate.get("icon", "")),
                    "price": item_gold(candidate),
                    "score": round(score, 1),
                    "objective_value": round(score, 3),
                    "metric": metric,
                    "components": components,
                    "stats": candidate.get("stats", {}),
                    "survival": focus["survival"],
                    "defensive_effect_receipt": bis_defensive_effect_receipt(
                        candidate["name"], focus["survival"]
                    ),
                    "timeline_coverage": coverage,
                    "_sort_score": score,
                    **({"_rank_key": rank_key} if rank_key is not None else {}),
                }
            )
        except (KeyError, ValueError) as exc:
            withheld.append(
                _withheld_candidate(
                    candidate,
                    reason="candidate_loadout_unavailable",
                    detail=str(exc),
                    timeline_coverage={
                        "complete": False,
                        "certification": "candidate_not_evaluated",
                        "exact_sources": [],
                        "coarse_sources": [],
                        "note": "Candidate was withheld before timeline evaluation.",
                    },
                )
            )

    if objective_key == "overall" and subject_team == "enemy":
        ranked.sort(key=lambda row: row["_rank_key"], reverse=True)
    else:
        ranked.sort(
            key=lambda row: row["_sort_score"],
            reverse=objective_meta["direction"] == "higher",
        )
    for row in ranked:
        row.pop("_rank_key", None)
        row.pop("_sort_score", None)
    partial = [
        row for row in ranked if not row["timeline_coverage"].get("complete", False)
    ]
    certified = [
        row for row in ranked if row["timeline_coverage"].get("complete", False)
    ]
    coverage_receipt, target_note, timing_excluded = _bis_coverage_receipt(
        certified, partial, withheld, target_filtered
    )
    payload = {
        "objective": objective_meta,
        "defensive_effects": {
            "certified": dict(survival_ledger_certifications()),
            "withheld": BIS_UNMODELED_DEFENSIVE_EFFECTS,
        },
        "subject_team": subject_team,
        "subject_index": subject_index,
        "slot_index": slot_index,
        "slot_kind": slot_kind,
        "excluded_equipped_item": equipped_slot_item or None,
        "max_item_gold": max_item_gold,
        "budget_excluded_candidate_count": budget_excluded_count,
        "candidate_scope": (
            f"role-tagged:{role}" if role and slot_kind != "boots" else "all-supported"
        ),
        "candidates": certified,
        "partial_candidates": partial,
        "candidate_count": len(candidates),
        "certified_candidate_count": len(certified),
        "partial_candidate_count": len(partial),
        "withheld_candidate_count": len(withheld),
        "withheld_candidates": withheld,
        "coverage": coverage_receipt,
        "target_coverage_filtered": len(target_filtered),
        "target_coverage_note": target_note,
        "timing_excluded_candidate_count": len(timing_excluded),
    }
    payload["dispositions"] = _bis_dispositions(payload)
    return payload


def _batch_replace_subject_slot(
    data: dict[str, object],
    *,
    subject_team: str,
    subject_index: int,
    slot: Mapping[str, object],
    candidate_name: str,
) -> None:
    """Apply one certified winner before the next batch slot is scored."""
    slot_index = int(slot["slot_index"])
    slot_kind = str(slot["slot_kind"])
    if subject_team == "main":
        loadout = data
    else:
        roster_key = "allies" if subject_team == "ally" else "enemies"
        roster = data.get(roster_key)
        if not isinstance(roster, list) or subject_index >= len(roster):
            return
        loadout = roster[subject_index]
        if not isinstance(loadout, dict):
            return
    if slot_kind == "boots":
        loadout["boots"] = candidate_name
        return
    items = loadout.get("items", [])
    if not isinstance(items, list):
        items = []
    if slot_index >= len(items):
        items.append(candidate_name)
    else:
        items[slot_index] = candidate_name
    loadout["items"] = items


def _bis_batch_result(result: Mapping[str, object]) -> dict[str, object]:
    """Keep only fields needed to apply a dependent browser slot."""
    return {
        key: result.get(key)
        for key in (
            "candidate_count",
            "certified_candidate_count",
            "partial_candidate_count",
            "withheld_candidate_count",
            "coverage",
            "target_coverage_filtered",
            "timing_excluded_candidate_count",
        )
    } | {
        "candidates": list(result.get("candidates", []))[:1],
    }


def bis_batch_payload(data: Mapping[str, object]) -> dict[str, Any]:
    """Score dependent BIS slots in one request with shared pair state.

    The browser's greedy roster path needs the winner from slot N before it
    can score slot N+1.  Keeping that loop in one process removes request
    overhead and allows the timeline caches to survive between slots.  The
    response keeps one winner row per slot because the browser does not show
    the full candidate tables on this path.
    """
    raw_slots = data.get("slots")
    if not isinstance(raw_slots, list) or not raw_slots:
        raise ValueError("slots must be a non-empty list")
    if len(raw_slots) > MAX_LOADOUT_ITEMS + 1:
        raise ValueError("slots may contain at most 7 entries")
    scenario = deepcopy(dict(data))
    scenario.pop("slots", None)
    subject_team = request_string(scenario, "subject_team", "main")
    subject_index = request_int(scenario, "subject_index", 0, minimum=0, maximum=4)
    pair_result_cache: dict = {}
    batch_search_context = None
    results: list[dict] = []
    selected: list[dict[str, object]] = []
    tested = 0
    started = time.perf_counter()
    for raw_slot in raw_slots:
        if not isinstance(raw_slot, Mapping):
            raise ValueError("each batch slot must be an object")
        slot_kind = request_string(raw_slot, "slot_kind", "item")
        if slot_kind not in {"item", "boots"}:
            raise ValueError("slot_kind must be item or boots")
        slot_index = request_int(
            raw_slot, "slot_index", 0, minimum=0, maximum=MAX_LOADOUT_ITEMS - 1
        )
        current = deepcopy(scenario)
        current["slot_kind"] = slot_kind
        current["slot_index"] = slot_index
        result = bis_payload(
            current,
            pair_result_cache=pair_result_cache,
            search_context=batch_search_context,
        )
        results.append(_bis_batch_result(result))
        tested += int(result.get("candidate_count", 0) or 0)
        winner = (
            result.get("candidates", [{}])[0]
            if result.get("coverage", {}).get("complete") and result.get("candidates")
            else None
        )
        if not isinstance(winner, Mapping):
            continue
        winner_name = str(winner.get("name", ""))
        if not winner_name:
            continue
        _batch_replace_subject_slot(
            scenario,
            subject_team=subject_team,
            subject_index=subject_index,
            slot={"slot_index": slot_index, "slot_kind": slot_kind},
            candidate_name=winner_name,
        )
        selected.append(
            {
                "slot_index": slot_index,
                "slot_kind": slot_kind,
                "name": winner_name,
            }
        )
    return {
        "results": results,
        "selected": selected,
        "tested": tested,
        "optimization_time_ms": round((time.perf_counter() - started) * 1000, 1),
    }
