"""Best-in-slot domain policy (objective definitions and candidate scoring).

The BIS endpoint (/api/bis) is an objective selector over the coupled
participant event timeline, not a second stat-only optimizer.  Keeping the
objective contract and candidate-scoring rules in this module (instead of the
web layer) means the API receipt and any future consumer cannot silently
disagree about direction or units.  The Flask route in ``src/app.py`` owns
request parsing, per-candidate orchestration, sorting, and response assembly.
"""

from dataclasses import replace
import math
from collections.abc import Mapping
from typing import Any

from .loadout_rules import role_quest_legal_items, role_scoped_shop_items
from .optimizer import (
    get_eligible_boots,
    get_eligible_legendaries,
    optimizer_supported_items,
)
from .pipeline import DEFAULT_FIGHT_DURATION
from .scenario import MAX_LOADOUT_ITEMS, ChampionLoadout, ScenarioRequest
from .item_coverage import target_build_coverage


def bis_main_request(
    request: ScenarioRequest, data: Mapping[str, object]
) -> ChampionLoadout:
    """Rebuild the actual main champion loadout for focused BIS requests.

    The shared scenario boundary already validated every loadout field, so
    this only reassembles the typed ``ChampionLoadout`` (plus the BIS-only
    ``ally_effects_enabled`` toggle) from the validated request.
    """
    ally_effects_enabled = data.get("ally_effects_enabled", True)
    if not isinstance(ally_effects_enabled, bool):
        raise ValueError("ally_effects_enabled must be true or false")
    return ChampionLoadout(
        champion=request.champion,
        level=request.level,
        items=request.items,
        boots=request.boots,
        item_options=dict(request.fight_params.item_options or {}),
        role=request.fight_params.role,
        role_quest_complete=request.fight_params.role_quest_complete,
        ally_effects_enabled=ally_effects_enabled,
        # Focused BIS must use the same authored rank allocation as the
        # ordinary calculate/optimize paths.  Omitting this field makes
        # ChampionLoadout silently fall back to level-derived ranks.
        ability_ranks=dict(request.fight_params.ability_ranks or {}),
        champion_options=dict(request.fight_params.champion_options or {}),
        cast_order=request.fight_params.cast_order,
    )


def bis_replaced_loadout(
    loadout: ChampionLoadout,
    *,
    slot_index: int,
    slot_kind: str,
    candidate_name: str,
    candidate_item_options: dict[str, int | float] | None = None,
) -> ChampionLoadout:
    """Replace one ordinary or boots slot while preserving sourced options."""
    item_options = dict(loadout.item_options or {})
    if candidate_item_options:
        item_options[candidate_name] = dict(candidate_item_options)
    if slot_kind == "boots":
        return replace(loadout, boots=candidate_name, item_options=item_options)
    items = list(loadout.items)
    if slot_index < 0 or slot_index > MAX_LOADOUT_ITEMS - 1:
        raise ValueError("slot_index must be between 0 and 5")
    if slot_index >= len(items):
        # Empty browser slots are not serialized as placeholder items; the
        # next completed candidate therefore occupies the next legal slot.
        items.append(candidate_name)
    else:
        items[slot_index] = candidate_name
    # The browser represents empty slots as absent request entries.  A
    # candidate is therefore the only item introduced for a previously empty
    # slot; duplicate validation remains owned by ChampionLoadout.resolve.
    return replace(loadout, items=tuple(items), item_options=item_options)


def role_scoped_bis_candidates(
    candidates: list[dict],
    *,
    role: str,
) -> list[dict]:
    """Keep roster BIS candidates within the selected role's sourced shop scope.

    The item cache carries Riot's shop tags for each completed item.  A roster
    role is an explicit scenario input, so using those tags here prevents a
    support-only item from being recommended to a top/mid enemy and prevents a
    support ally's BIS from collapsing into raw-health tank items.  This is a
    candidate-legality boundary, not a champion archetype or damage heuristic;
    the surviving candidates are still scored by the coupled event timeline.
    """
    return role_scoped_shop_items(candidates, role)


def bis_candidate_pool(
    slot_kind: str,
    *,
    boots_tier: int,
    role: str = "",
    role_quest_complete: bool = False,
) -> list[dict]:
    """Return the sorted legal candidate pool for one ranked slot.

    Boots use the role's eligible tier; ordinary slots use the optimizer's
    supported legendaries scoped to the role's sourced shop tags and the
    support quest's legal-item contract.
    """
    legal = (
        get_eligible_boots(tier=boots_tier)
        if slot_kind == "boots"
        else get_eligible_legendaries()
    )
    supported = optimizer_supported_items(legal)
    scoped = (
        supported
        if slot_kind == "boots"
        else role_scoped_bis_candidates(supported, role=role)
    )
    if slot_kind != "boots":
        scoped = role_quest_legal_items(
            scoped, role=role, role_quest_complete=role_quest_complete
        )
    return sorted(scoped, key=lambda item: item.get("name", ""))


def roster_target_coverage(loadouts: list[ChampionLoadout]) -> list[dict[str, object]]:
    """Return unsupported target mechanics for the coupled roster.

    Roster BIS candidates are later used as passive targets by the main
    champion's event timeline. Do not apply a candidate whose target-side
    item effect is outside the sourced target model; that would either fail
    the next main optimization late or silently ignore the mechanic.
    """
    blocked: list[dict[str, object]] = []
    for loadout in loadouts:
        coverage = target_build_coverage(list(loadout.item_data))
        for entry in coverage.get("blocked", []):
            blocked.append(
                {
                    "champion": loadout.champion_data.get(
                        "name", loadout.request.champion
                    ),
                    "name": entry.get("name", ""),
                    "reason": entry.get("reason", ""),
                }
            )
    return blocked


def enemy_bis_rank_key(
    objective: Mapping[str, object],
    survival: Mapping[str, object],
    *,
    duration: float,
) -> tuple[float, ...]:
    """Order enemy candidates by a survival-gated, event-derived objective.

    A roster enemy must remain a live participant before its outgoing damage
    can be useful, but surviving builds should not all collapse to a health
    race.  The first components are a hard event gate (alive through the
    requested window) and survival time, followed by damage dealt before
    defeat (the timeline's TTD-truncated threat).  Effective health and
    recovery actually applied by the timeline are deterministic tie-breakers.
    This is deliberately champion/event based: it does not infer a role or
    assign a damage/tank archetype from the champion name.
    """
    death_time = survival.get("death_time")
    survival_time = float(duration if death_time is None else death_time)
    threat = float(objective.get("focus_damage_before_death", 0.0))
    effective_health = float(survival.get("effective_health", 0.0))
    healing = float(survival.get("healing_received", 0.0))
    support_shield = float(survival.get("support_shield_received", 0.0))
    shield_absorbed = float(survival.get("shield_absorbed", 0.0))
    # Survival is a gate, not an archetype prior.  Survival time still
    # separates candidates that both die before the window; once candidates
    # live equally long, modeled threat is the first discriminator.  Remaining
    # event-derived durability/recovery fields only break ties.
    survived_window = 1.0 if death_time is None else 0.0
    return (
        survived_window,
        survival_time,
        threat,
        effective_health,
        healing,
        support_shield,
        shield_absorbed,
    )


# Best-in-slot is an objective selector, not a second stat-only optimizer.
# Keep the definitions in one place so the API receipt and the browser filter
# cannot silently disagree about direction or units.
BIS_OBJECTIVES: dict[str, dict[str, str]] = {
    "overall": {
        "label": "Overall",
        "direction": "higher",
        "metric": "event-ordered team-fight value",
    },
    "kill": {
        "label": "Kill pressure",
        "direction": "lower",
        "metric": "time to first target defeat",
    },
    "survival": {
        "label": "Survival",
        "direction": "higher",
        "metric": "effective health (event-applied)",
    },
    "damage": {
        "label": "Damage",
        "direction": "higher",
        "metric": "damage before focus defeat",
    },
    "utility": {
        "label": "Utility",
        "direction": "higher",
        "metric": "healing, shields, and support value",
    },
}

BIS_CERTIFIED_DEFENSIVE_EFFECTS: dict[str, str] = {
    "Eclipse": (
        "Ever Rising Moon's two-hit trigger creates a timestamped self shield "
        "with its sourced melee/ranged amount and two-second expiry."
    ),
    "Death's Dance": (
        "Ignore Pain splits post-mitigation physical/magic damage into sourced "
        "true-damage ticks; Defy clears the remaining store and heals on a "
        "qualifying takedown."
    ),
    "Sundered Sky": (
        "Lightshield Strike's first-hit heal is timestamped and included in "
        "the participant survival/eHP ledger; any sourced temporary-health "
        "overheal is applied through the same ordered heal event."
    ),
}

# Retained as an explicit API field for clients that display the audit
# contract.  A non-empty entry means the candidate is withheld; CP6 now
# certifies Eclipse and Death's Dance through the ordered event walk.
BIS_UNMODELED_DEFENSIVE_EFFECTS: dict[str, str] = {}


def bis_defensive_effect_receipt(
    item_name: str, survival: Mapping[str, object]
) -> dict[str, object]:
    """Describe why a defensive item did or did not affect candidate eHP."""
    certified_note = BIS_CERTIFIED_DEFENSIVE_EFFECTS.get(item_name)
    if certified_note is None:
        return {"status": "no_special_defensive_effect", "sources": []}
    return {
        "status": "certified",
        "sources": [item_name],
        "note": certified_note,
        "evidence": {
            "healing_received": round(
                float(survival.get("healing_received", 0.0) or 0.0), 1
            ),
            "temporary_health_received": round(
                float(survival.get("temporary_health_received", 0.0) or 0.0), 1
            ),
            "effective_health": round(
                float(survival.get("effective_health", 0.0) or 0.0), 1
            ),
        },
    }


def bis_objective_meta(key: str) -> dict[str, str]:
    """Return a defensive copy of the API's objective contract."""
    meta = BIS_OBJECTIVES.get(key)
    if meta is None:
        raise ValueError(
            "objective must be one of: overall, kill, survival, damage, utility"
        )
    return {"key": key, **meta}


def bis_time_to_target_defeat(
    combat: Mapping[str, object],
    *,
    subject_team: str,
    focus_id: str,
    duration: float,
) -> float:
    """Return an explicit event-derived kill-time objective in seconds.

    For a main/ally item, kill pressure means the first enemy defeat.  For an
    enemy item, it means how quickly the selected enemy is defeated.  An
    undefeated participant is assigned the requested window, never zero or a
    guessed extrapolation.
    """
    participants = combat.get("participants", [])
    if not isinstance(participants, list):
        participants = []
    if subject_team == "enemy":
        participant_ids = {focus_id}
    else:
        participant_ids = {
            str(row.get("participant_id", ""))
            for row in participants
            if isinstance(row, Mapping) and row.get("team") == "enemy"
        }
    times: list[float] = []
    for row in participants:
        if (
            not isinstance(row, Mapping)
            or str(row.get("participant_id", "")) not in participant_ids
        ):
            continue
        survival = row.get("survival", {})
        if not isinstance(survival, Mapping):
            continue
        death_time = survival.get("death_time")
        if death_time is None:
            continue
        try:
            parsed = float(death_time)
        except (TypeError, ValueError):
            continue
        if math.isfinite(parsed):
            times.append(max(0.0, min(duration, parsed)))
    return min(times, default=duration)


def bis_objective_score(
    objective_key: str,
    *,
    subject_team: str,
    focus_id: str,
    combat: Mapping[str, object],
    objective: Mapping[str, object],
    focus: Mapping[str, object],
) -> tuple[float, str, dict[str, float], tuple[float, ...] | None]:
    """Derive one candidate's selected objective from the shared timeline."""
    focus_survival = focus.get("survival", {})
    if not isinstance(focus_survival, Mapping):
        focus_survival = {}
    duration = float(combat.get("duration", 0.0) or 0.0)
    if duration <= 0.0:
        duration = DEFAULT_FIGHT_DURATION
    focus_damage = float(objective.get("focus_damage_before_death", 0.0) or 0.0)
    effective_health = float(focus_survival.get("effective_health", 0.0) or 0.0)
    healing = float(focus_survival.get("healing_received", 0.0) or 0.0)
    support_shield = float(focus_survival.get("support_shield_received", 0.0) or 0.0)
    support_value = float(objective.get("focus_support_value", 0.0) or 0.0)
    if objective_key == "overall":
        if subject_team == "main":
            score = focus_damage
            metric = "main TTD (survival-coupled)"
            components = {
                "damage_before_death": focus_damage,
                "effective_health": effective_health,
                "healing": healing,
                "support_shield_received": support_shield,
            }
            return score, metric, components, None
        if subject_team == "ally":
            team_damage = float(
                objective.get("main_team_damage_before_death", 0.0) or 0.0
            )
            score = team_damage + support_value + effective_health
            metric = "team damage + ally utility + effective health"
            components = {
                "main_team_damage_before_death": team_damage,
                "outgoing_support": support_value,
                "healing": float(objective.get("focus_healing", 0.0) or 0.0),
                "effective_health": effective_health,
            }
            return score, metric, components, None
        survival_time = bis_time_to_target_defeat(
            combat,
            subject_team=subject_team,
            focus_id=focus_id,
            duration=duration,
        )
        rank_key = enemy_bis_rank_key(objective, focus_survival, duration=duration)
        score = focus_damage
        metric = "enemy survival gate · threat before defeat"
        components = {
            "survival_time": survival_time,
            "effective_health": effective_health,
            "threat_before_defeat": focus_damage,
            "healing": healing,
            "shield_absorbed": float(focus_survival.get("shield_absorbed", 0.0) or 0.0),
        }
        return score, metric, components, rank_key

    if objective_key == "kill":
        score = bis_time_to_target_defeat(
            combat,
            subject_team=subject_team,
            focus_id=focus_id,
            duration=duration,
        )
        metric = BIS_OBJECTIVES[objective_key]["metric"]
        components = {
            "time_to_target_defeat": score,
            "damage_before_death": focus_damage,
        }
        return score, metric, components, None
    if objective_key == "survival":
        score = effective_health
        metric = BIS_OBJECTIVES[objective_key]["metric"]
        components = {
            "effective_health": effective_health,
            "healing": healing,
            "support_shield_received": support_shield,
        }
        return score, metric, components, None
    if objective_key == "damage":
        if subject_team == "ally":
            score = float(objective.get("main_team_damage_before_death", 0.0) or 0.0)
        else:
            score = focus_damage
        metric = BIS_OBJECTIVES[objective_key]["metric"]
        components = {
            "damage_before_death": score,
            "effective_health": effective_health,
        }
        return score, metric, components, None
    # Utility is intentionally an additive receipt of values that the event
    # walk actually applied.  It does not infer movement, range, or a value
    # for an unmodelled item tooltip.
    score = support_value + healing + support_shield
    metric = BIS_OBJECTIVES[objective_key]["metric"]
    components = {
        "support_value": support_value,
        "healing": healing,
        "support_shield_received": support_shield,
    }
    return score, metric, components, None
