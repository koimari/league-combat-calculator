"""Greedy fill and hill climbing over legendary slots."""

from collections.abc import Collection, Iterable
from typing import Any

from . import build_evaluation
from .loadout_rules import ITEM_TO_EXCLUSIVITY_GROUPS
from .optimizer_candidates import _conflicts_with_build, _get_occupied_groups


def _greedy_fill(
    champion_data: dict[str, Any],
    level: int,
    locked_legendaries: list[dict[str, Any]],
    locked_boots: dict[str, Any] | None,
    *,
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

            score = build_evaluation.evaluate_build(
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
            score = build_evaluation.evaluate_build(
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
    final_score = build_evaluation.evaluate_build(
        champion_data,
        level,
        final_items,
        **eval_kwargs,
    )
    return current, boots, final_score


def _score_with_swap(
    champion_data: dict[str, Any],
    level: int,
    base: list[dict[str, Any]],
    index: int,
    *,
    candidate: dict[str, Any],
    boots: dict[str, Any] | None,
    eval_kwargs: dict[str, Any],
) -> tuple[list[dict[str, Any]], float]:
    """*base* with *candidate* in slot *index*, and that build's score."""
    trial = list(base)
    trial[index] = candidate
    trial_items = ([boots] if boots else []) + trial
    return trial, build_evaluation.evaluate_build(
        champion_data, level, trial_items, **eval_kwargs
    )


def _hill_climb(
    champion_data: dict[str, Any],
    level: int,
    legendaries: list[dict[str, Any]],
    boots: dict[str, Any] | None,
    *,
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
        best_score = build_evaluation.evaluate_build(
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

                trial, score = _score_with_swap(
                    champion_data,
                    level,
                    current,
                    slot_idx,
                    candidate=candidate,
                    boots=current_boots,
                    eval_kwargs=eval_kwargs,
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
                score = build_evaluation.evaluate_build(
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
