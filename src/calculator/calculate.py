"""Pure application orchestration for the public calculate payload.

Flask owns HTTP decoding, caching, rate limiting, and error translation.
This module owns scenario resolution, fight execution, comparison curves, and
the stable JSON-safe payload returned to every in-process consumer.
"""

from collections.abc import Mapping
from dataclasses import replace

from .champions import (
    engine_registration_kind,
    get_comparison_curve_unavailable_reason,
)
from .defensive_effects import resolve_starting_defenses
from .item_coverage import require_certified_target_timeline
from .participant_timeline import build_participant_timeline
from .pipeline import ONE_ROTATION_DURATION, run_fight
from .public_response import (
    aggregate_public_results,
    public_engine_mode,
    public_loadout_summary,
    serialize_fight_result,
)
from .role_quests import role_quest_meta
from .scenario import (
    VERIFIED_CHAMPIONS as _VERIFIED_CHAMPIONS,
    ResolvedScenario,
    ScenarioRequest,
    parse_scenario_request,
    resolve_scenario,
)
from .stats import calculate_total_stats


def _loadout_summary(loadout) -> dict:
    """Render one resolved loadout through the public certification boundary."""
    return public_loadout_summary(loadout, _VERIFIED_CHAMPIONS)


def _comparison_curve(
    request: ScenarioRequest, resolved: ResolvedScenario
) -> list[dict]:
    """Score the resolved build through six continuous timed windows."""
    points: list[dict] = []
    for rotation in range(1, 7):
        duration = ONE_ROTATION_DURATION * rotation
        if not resolved.enemies:
            params = replace(
                resolved.fight_params,
                fight_duration_seconds=duration,
                one_rotation=False,
            )
            result = serialize_fight_result(
                run_fight(
                    resolved.champion_data, request.level, list(resolved.items), params
                )
            )
        else:
            target_results: list[dict] = []
            for enemy, target_params in zip(
                resolved.enemies, resolved.target_fight_params
            ):
                params = replace(
                    target_params,
                    fight_duration_seconds=duration,
                    one_rotation=False,
                )
                target_result = run_fight(
                    resolved.champion_data,
                    request.level,
                    list(resolved.items),
                    params,
                )
                require_certified_target_timeline(
                    list(enemy.item_data), target_result.get("timeline_coverage", {})
                )
                target_results.append(serialize_fight_result(target_result))
            result = aggregate_public_results(target_results)
        total = float(result["total_damage"])
        points.append(
            {
                "rotation": rotation,
                "seconds": duration,
                "total_damage": round(total, 1),
                "dps": round(total / duration, 1),
                "ability_damage": round(float(result["ability_damage"]), 1),
                "auto_attack_damage": round(float(result["auto_attack_damage"]), 1),
            }
        )
    return points


def _add_comparison_curve(
    response: dict, request: ScenarioRequest, resolved: ResolvedScenario
) -> None:
    """Attach crossover windows or an explicit fail-closed receipt."""
    reason = get_comparison_curve_unavailable_reason(resolved.champion_data["name"])
    if reason:
        response["comparison_curve"] = []
        response["comparison_curve_status"] = {"available": False, "reason": reason}
        return
    try:
        response["comparison_curve"] = _comparison_curve(request, resolved)
    except ValueError as exc:
        response["comparison_curve"] = []
        response["comparison_curve_status"] = {
            "available": False,
            "reason": str(exc),
        }
        return
    response["comparison_curve_status"] = {"available": True}


def _engine_receipt(champion_name: str) -> dict:
    """Return the stable engine registration and certification receipt."""
    return {
        "registration": engine_registration_kind(champion_name),
        "certified": champion_name in _VERIFIED_CHAMPIONS,
        "mode": public_engine_mode(champion_name),
    }


def _ally_effects_receipt(resolved: ResolvedScenario) -> dict:
    """Describe modeled and contextual-only allies for the public scenario."""
    return {
        "modeled": [effect.source for effect in resolved.ally_effects],
        "unmodeled": [ally.champion_data["name"] for ally in resolved.allies],
        "note": (
            "Allies are included as sourced context; outgoing ally buffs are "
            "applied only when an explicit tested effect exists."
        ),
    }


def _combat_receipt(
    resolved: ResolvedScenario, request: ScenarioRequest
) -> dict | None:
    """Build the coupled participant receipt when champion stats are available."""
    champion_data = resolved.champion_data
    if not isinstance(champion_data.get("stats"), Mapping):
        return None
    items = list(resolved.items)
    params = resolved.fight_params
    main_stats = calculate_total_stats(
        champion_data,
        request.level,
        items,
        item_options=params.item_options,
        role=params.role,
        role_quest_complete=params.role_quest_complete,
        external_stat_bonuses=params.ally_stat_bonuses,
    )
    return build_participant_timeline(
        champion_data,
        request.level,
        items,
        params,
        main_stats=main_stats,
        main_defenses=resolve_starting_defenses(
            champion_data["name"],
            request.level,
            main_stats,
            items,
            item_options=params.item_options,
        ),
        enemies=list(resolved.enemies),
        allies=list(resolved.allies),
    )


def _role_quest_receipt(resolved: ResolvedScenario) -> dict | None:
    """Return role-quest metadata only when a role was selected."""
    params = resolved.fight_params
    if not params.role:
        return None
    return role_quest_meta(params.role, params.role_quest_complete)


def _calculate_resolved(request: ScenarioRequest, resolved: ResolvedScenario) -> dict:
    """Execute one already parsed and resolved scenario."""
    champion_data = resolved.champion_data
    items = list(resolved.items)
    enemies = list(resolved.enemies)
    allies = list(resolved.allies)
    params = resolved.fight_params

    if not enemies:
        response = serialize_fight_result(
            run_fight(champion_data, request.level, items, params)
        )
        if request.include_crossover:
            _add_comparison_curve(response, request, resolved)
        response["role_quest"] = _role_quest_receipt(resolved)
        response["engine"] = _engine_receipt(champion_data["name"])
        if allies:
            response.update(
                {
                    "allies": [_loadout_summary(ally) for ally in allies],
                    "scenario": {
                        "target_count": 1,
                        "aggregation": "Manual target",
                        "primary_target": "Manual target",
                        "ally_effects": _ally_effects_receipt(resolved),
                    },
                }
            )
        combat = _combat_receipt(resolved, request)
        if combat is not None:
            response["combat"] = combat
        return response

    target_rows: list[dict] = []
    for enemy, target_params in zip(enemies, resolved.target_fight_params):
        result = run_fight(champion_data, request.level, items, target_params)
        if not params.one_rotation:
            require_certified_target_timeline(
                list(enemy.item_data), result.get("timeline_coverage", {})
            )
        target_rows.append(
            {
                "target": _loadout_summary(enemy),
                "result": serialize_fight_result(result),
            }
        )
    response = aggregate_public_results([row["result"] for row in target_rows])
    response.update(
        {
            "targets": target_rows,
            "allies": [_loadout_summary(ally) for ally in allies],
            "scenario": {
                "target_count": len(target_rows),
                "aggregation": "Same selected damage package landed on every target",
                "primary_target": target_rows[0]["target"]["champion"],
                "ally_effects": _ally_effects_receipt(resolved),
            },
            "role_quest": _role_quest_receipt(resolved),
            "engine": _engine_receipt(champion_data["name"]),
        }
    )
    combat = _combat_receipt(resolved, request)
    if combat is not None:
        response["combat"] = combat
    if request.include_crossover:
        _add_comparison_curve(response, request, resolved)
    return response


def calculate_payload(data: Mapping[str, object]) -> dict:
    """Return the complete JSON-safe calculate payload without Flask state."""
    request = parse_scenario_request(data)
    resolved = resolve_scenario(request)
    return _calculate_resolved(request, resolved)
