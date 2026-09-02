"""Pure application orchestration for the public calculate payload.

Flask owns HTTP decoding, caching, rate limiting, and error translation.
This module owns scenario resolution, fight execution, comparison curves, and
the stable JSON-safe payload returned to every in-process consumer.
"""

import re
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from .champions import engine_registration_kind
from .defensive_effects import resolve_starting_defenses
from .item_coverage import require_certified_target_timeline
from .participant_timeline import build_participant_timeline
from .pipeline import ONE_ROTATION_DURATION, run_fight
from .program.views import LeafWriter, name_every_number
from .public_response import (
    aggregate_public_results,
    public_engine_mode,
    public_loadout_summary,
    serialize_fight_result,
)
from .role_quests import role_quest_meta
from .scenario import (
    ResolvedScenario,
    ScenarioRequest,
    parse_scenario_request,
    resolve_scenario,
)
from .validation_receipts import displayed_prediction


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
                resolved.enemies, resolved.target_fight_params, strict=False
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
    registration = engine_registration_kind(champion_name)
    return {
        "registration": registration,
        "certified": registration is not None,
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


#: One ``combat.breakdown`` row's ``dispositions`` keys, which carry its index.
_BREAKDOWN_ROW = re.compile(r"^breakdown\[(\d+)\]")


def _drop_unattributed_breakdown(combat: dict) -> None:
    """Withhold breakdown rows that no participant stands behind.

    A fight against a manual target has no coupled opponent, so the walk
    folds one outcome carrying no identity and no damage -- published, that
    is a blank row in the public shape.  Each row's ``dispositions`` entries
    are keyed by its index, so the survivors are renumbered with it.
    """
    rows = combat["breakdown"]
    renumbered = {
        old: new
        for new, old in enumerate(
            index for index, row in enumerate(rows) if row["participant_id"]
        )
    }
    if len(renumbered) == len(rows):
        return
    combat["breakdown"] = [rows[old] for old in renumbered]
    kept: dict[str, object] = {}
    for path, entry in combat["dispositions"].items():
        match = _BREAKDOWN_ROW.match(path)
        if match is None:
            kept[path] = entry
            continue
        target = renumbered.get(int(match.group(1)))
        if target is not None:
            kept[f"breakdown[{target}]{path[match.end():]}"] = entry
    combat["dispositions"] = kept


def _combat_receipt(
    resolved: ResolvedScenario, request: ScenarioRequest
) -> dict | None:
    """Build the coupled participant receipt when champion stats are available."""
    champion_data = resolved.champion_data
    if not isinstance(champion_data.get("stats"), Mapping):
        return None
    items = list(resolved.items)
    params = resolved.fight_params
    main_stats = params.pre_combat_stats(champion_data, request.level, items)
    combat = build_participant_timeline(
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
    _drop_unattributed_breakdown(combat)
    return combat


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
                    "allies": [public_loadout_summary(ally) for ally in allies],
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
    for enemy, target_params in zip(
        enemies, resolved.target_fight_params, strict=False
    ):
        result = run_fight(champion_data, request.level, items, target_params)
        if not params.one_rotation:
            require_certified_target_timeline(
                list(enemy.item_data), result.get("timeline_coverage", {})
            )
        target_rows.append(
            {
                "target": public_loadout_summary(enemy),
                "result": serialize_fight_result(result),
            }
        )
    response = aggregate_public_results([row["result"] for row in target_rows])
    response.update(
        {
            "targets": target_rows,
            "allies": [public_loadout_summary(ally) for ally in allies],
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


#: The response blocks that carry a parallel ``dispositions`` map of their
#: own.  ``combat`` is the five views' payload and the receipt view's writer
#: named every number in it at the path it lives at; re-describing those
#: leaves here would give each of them a *second* entry, and criterion 5 says
#: exactly one.  So the response holds one map per block that has one, every
#: numeric leaf is covered by exactly one of them, and neither map is a
#: second producer of the other's entries.
_BLOCKS_CARRYING_THEIR_OWN_MAP = frozenset({"combat"})


def _name_the_response(response: dict) -> None:
    """Give the response its own ``dispositions`` map, keyed by leaf path.

    ``combat`` is skipped because it carries a map of its own."""
    response["dispositions"] = name_every_number(
        response, LeafWriter(), skip=_BLOCKS_CARRYING_THEIR_OWN_MAP
    )


def calculate_payload(
    data: Mapping[str, object], *, deterministic: bool = False
) -> dict[str, Any]:
    """Return the complete JSON-safe calculate payload without Flask state.

    ``headline_total`` is the one published answer to "which number does this
    result headline": the attacker's own coupled combat row when the fight has
    one, else the rotation total.  The browser reads the leaf.
    """
    request = parse_scenario_request(data, deterministic=deterministic)
    resolved = resolve_scenario(request)
    response = _calculate_resolved(request, resolved)
    response["headline_total"] = displayed_prediction(response)[0]
    _name_the_response(response)
    return response


def compare_payload(data: Mapping[str, object]) -> dict[str, object]:
    """Calculate exactly two complete builds from one request body.

    The browser needs two complete results for a build comparison. Keeping
    both calculations behind one application boundary removes the client-side
    request fan-out and gives the server one cache and rate-limit decision.
    """
    raw_builds = data.get("builds")
    if not isinstance(raw_builds, list) or len(raw_builds) != 2:
        raise ValueError("builds must contain exactly 2 calculation objects")

    results: list[dict] = []
    for index, build in enumerate(raw_builds):
        if not isinstance(build, Mapping):
            raise ValueError(f"builds[{index}] must be an object")
        results.append(calculate_payload(build, deterministic=True))

    return {
        "results": results,
        "build_count": len(results),
        "request_count": 1,
        "mode": "deterministic",
    }
