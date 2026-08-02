"""Event-ordered combat for a selected main champion and roster.

The existing fight engine remains the authority for champion and item math.
This layer only composes its post-mitigation event ledgers, applies starting
shields and sourced self-heals in timestamp order, and reports who was alive
when damage landed.  It intentionally does not invent targeting, cooldown,
or crowd-control behavior that the packets do not provide.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from typing import Any, Iterable, Mapping

from .pipeline import FightParams, run_fight
from .scenario import ResolvedLoadout
from .timeline_coverage import combine_timeline_coverages
from .support_effects import derive_ally_effects


@dataclass(frozen=True, slots=True)
class Combatant:
    """One participant with its resolved stats and build."""

    participant_id: str
    team: str
    champion_data: dict[str, Any]
    level: int
    items: tuple[dict[str, Any], ...]
    stats: dict[str, float]
    defenses: Any
    request: Any = None


def _from_loadout(
    participant_id: str,
    team: str,
    loadout: ResolvedLoadout,
) -> Combatant:
    return Combatant(
        participant_id=participant_id,
        team=team,
        champion_data=loadout.champion_data,
        level=loadout.request.level,
        items=loadout.item_data,
        stats=loadout.stats,
        defenses=loadout.defenses,
        request=loadout.request,
    )


def _main_combatant(
    champion_data: dict[str, Any],
    level: int,
    items: list[dict[str, Any]],
    *,
    stats: dict[str, float],
    defenses: Any,
    params: FightParams,
) -> Combatant:
    return Combatant(
        participant_id="main",
        team="main",
        champion_data=champion_data,
        level=level,
        items=tuple(items),
        stats=stats,
        defenses=defenses,
        request=type(
            "MainRequest",
            (),
            {
                "role": params.role,
                "role_quest_complete": params.role_quest_complete,
                "ability_ranks": params.ability_ranks,
                "champion_options": params.champion_options,
            },
        )(),
    )


def _target_params(base: FightParams, defender: Combatant) -> FightParams:
    defenses = defender.defenses
    return replace(
        base,
        target_health=float(defender.stats.get("health", 0.0)),
        target_bonus_health=float(defender.stats.get("bonus_health", 0.0)),
        target_armor=float(defender.stats.get("armor", 0.0)),
        target_magic_resistance=float(defender.stats.get("magic_resistance", 0.0)),
        target_magic_shield=float(defenses.magic_shield),
        target_physical_shield=float(defenses.physical_shield),
        target_general_shield=float(defenses.general_shield),
        target_basic_damage_multiplier=float(defenses.basic_damage_multiplier),
        target_basic_damage_flat_reduction=float(defenses.basic_damage_flat_reduction),
        target_basic_damage_flat_reduction_cap=float(
            defenses.basic_damage_flat_reduction_cap
        ),
        target_critical_strike_damage_multiplier=float(
            defenses.critical_strike_damage_multiplier
        ),
        target_threshold_shield_amount=float(defenses.threshold_shield_amount),
        target_threshold_shield_health_ratio=float(
            defenses.threshold_shield_health_ratio
        ),
        target_threshold_shield_duration=float(defenses.threshold_shield_duration),
        target_threshold_shield_damage_type=str(defenses.threshold_shield_damage_type),
        target_threshold_health_bonus=float(defenses.threshold_health_bonus),
        target_threshold_health_heal=float(defenses.threshold_health_heal),
        target_threshold_health_ratio=float(defenses.threshold_health_ratio),
        target_threshold_health_duration=float(defenses.threshold_health_duration),
    )


def _actor_params(base: FightParams, actor: Combatant) -> FightParams:
    """Use a roster actor's role while preserving the selected fight window."""
    request = actor.request
    return replace(
        base,
        role=getattr(request, "role", "") or "",
        role_quest_complete=bool(getattr(request, "role_quest_complete", False)),
        # Roster rank/option controls are not yet part of the loadout schema;
        # omitted values intentionally stay None so each champion module uses
        # its sourced legal level-derived defaults.
        ability_ranks=getattr(request, "ability_ranks", None) or None,
        champion_options=getattr(request, "champion_options", None),
        ally_stat_bonuses=None,
    )


def _participant_defenses(defenses: Any) -> dict[str, float]:
    return {
        "magic_shield": max(0.0, float(defenses.magic_shield)),
        "physical_shield": max(0.0, float(defenses.physical_shield)),
        "general_shield": max(0.0, float(defenses.general_shield)),
    }


def _support_target_ids(
    attacker: Combatant,
    effect: Mapping[str, Any],
    all_actors: list[Combatant],
) -> tuple[list[str], str]:
    """Resolve a sourced support packet to selected teammates.

    Target selection is intentionally explicit.  The packet supplies whether
    an effect is self-cast, area-wide, or one-teammate; for the latter the
    first selected teammate is the deterministic scenario target.  This keeps
    the model reproducible without pretending that an unspecified cursor
    choice was observed.
    """
    if effect.get("target_self") or effect.get("target_scope") == "self":
        return [attacker.participant_id], "self"
    # ``main`` and ``ally`` are separate UI buckets but they are one allied
    # side in the fight.  Comparing the raw labels would make a main Lulu
    # unable to target an ally (and an ally unable to target the main).
    attacker_side = "main" if attacker.team in {"main", "ally"} else attacker.team
    teammates = [
        actor
        for actor in all_actors
        if ("main" if actor.team in {"main", "ally"} else actor.team)
        == attacker_side
        and actor.participant_id != attacker.participant_id
    ]
    if not teammates:
        return [], "no_selected_teammate"
    if effect.get("target_scope") == "all_teammates":
        return [actor.participant_id for actor in teammates], "all_selected_teammates"
    return [teammates[0].participant_id], "first_selected_teammate"


def _attach_support_effects(
    attacker: Combatant,
    result: Mapping[str, Any],
    all_actors: list[Combatant],
    support_effects: dict[str, list[dict[str, Any]]],
) -> None:
    """Attach one actor's sourced shield/heal packets exactly once."""
    if attacker.team == "ally" and not getattr(attacker.request, "ally_effects_enabled", False):
        return
    request = attacker.request
    effects = derive_ally_effects(
        attacker.champion_data,
        attacker.level,
        result.get("champion_stats", attacker.stats),
        list(result.get("cast_timeline", [])),
        ability_ranks=getattr(request, "ability_ranks", None),
    )
    for effect in effects:
        target_ids, target_policy = _support_target_ids(attacker, effect, all_actors)
        for target_id in target_ids:
            support_effects[target_id].append(
                {
                    **effect,
                    "attacker": attacker.participant_id,
                    "target": target_id,
                    "target_policy": target_policy,
                }
            )


def _simulate_survival(
    combatants: Iterable[Combatant],
    incoming: Mapping[str, list[dict[str, Any]]],
    healing: Mapping[str, list[dict[str, Any]]],
    support_effects: Mapping[str, list[dict[str, Any]]],
    duration: float,
) -> dict[str, dict[str, Any]]:
    """Resolve damage, shields, healing, and death for every participant."""
    states: dict[str, dict[str, Any]] = {}
    for combatant in combatants:
        states[combatant.participant_id] = {
            "health": max(0.0, float(combatant.stats.get("health", 0.0))),
            "max_health": max(0.0, float(combatant.stats.get("health", 0.0))),
            "shields": _participant_defenses(combatant.defenses),
            "starting_shield": sum(_participant_defenses(combatant.defenses).values()),
            "damage_taken": 0.0,
            "overkill": 0.0,
            "health_damage": 0.0,
            "shield_absorbed": 0.0,
            "healing_received": 0.0,
            "support_shield_received": 0.0,
            "death_time": None,
        }

    actions: list[tuple[float, int, str, dict[str, Any]]] = []
    damage_event_status: dict[str, str] = {}
    for participant_id, events in support_effects.items():
        for event in events:
            # A sourced ally shield is a pre-damage barrier.  A sourced heal
            # is a post-damage recovery event.  They must not share one
            # priority merely because both are support effects.
            kind = str(event.get("kind", ""))
            priority = -1 if kind == "shield" else 1
            actions.append((float(event.get("time", 0.0)), priority, participant_id, event))
    # Damage resolves before self-healing and sourced recovery at the same
    # timestamp, while shields remain before damage above.
    for participant_id, events in incoming.items():
        actions.extend(
            (float(event.get("time", 0.0)), 0, participant_id, event)
            for event in events
        )
    for participant_id, events in healing.items():
        actions.extend(
            (float(event.get("time", 0.0)), 1, participant_id, event)
            for event in events
        )
    actions.sort(key=lambda row: (row[0], row[1]))

    for event_time, phase, participant_id, event in actions:
        state = states[participant_id]
        trigger_id = event.get("_trigger_event_id")
        if phase == 1 and trigger_id is not None:
            # A heal whose damage event was skipped because its target was
            # already dead must not survive as an unconnected recovery tick.
            if damage_event_status.get(str(trigger_id)) != "applied":
                event["skipped_reason"] = "trigger_event_skipped"
                continue
        if state["death_time"] is not None:
            # Preserve the scheduled source in the receipt, but do not let
            # a dead target contribute post-death damage to TTD/BIS.
            event.setdefault("pair_damage", float(event.get("damage", 0.0)))
            event["damage"] = 0.0
            event["live_damage"] = 0.0
            event["overkill"] = 0.0
            event["skipped_reason"] = "target_dead"
            continue
        source_id = event.get("attacker")
        if source_id in states and states[source_id]["death_time"] is not None:
            # A dead actor cannot continue an already-scheduled rotation or
            # emit a support effect later in the shared window.
            event.setdefault("pair_damage", float(event.get("damage", 0.0)))
            event["damage"] = 0.0
            event["live_damage"] = 0.0
            event["overkill"] = 0.0
            event["skipped_reason"] = "attacker_dead"
            continue
        if phase == -1:
            kind = str(event.get("kind", ""))
            amount = max(0.0, float(event.get("amount", 0.0)))
            if kind == "shield":
                state["shields"]["general_shield"] += amount
                state["support_shield_received"] += amount
            elif kind == "heal":
                received = min(amount, max(0.0, state["max_health"] - state["health"]))
                state["health"] += received
                state["healing_received"] += received
            continue
        if phase == 1:
            amount = max(0.0, float(event.get("amount", 0.0)))
            received = min(amount, max(0.0, state["max_health"] - state["health"]))
            state["health"] += received
            state["healing_received"] += received
            continue

        amount = max(0.0, float(event.get("damage", 0.0)))
        event_id = event.get("_event_id")
        if event_id is not None:
            damage_event_status[str(event_id)] = "applied"
        original_amount = amount
        raw_formula = event.get("raw_formula")
        raw_damage = float(event.get("raw_damage", 0.0) or 0.0)
        if callable(raw_formula) and raw_damage > 0 and state["max_health"] > 0:
            # The one-attacker engine prices a target-health formula against
            # that pair's full-health target.  Re-price only the sourced
            # health-dependent component here; all typed mitigation and item
            # amplifiers remain represented by the original damage/raw ratio.
            missing_ratio = max(
                0.0,
                min(1.0, 1.0 - state["health"] / state["max_health"]),
            )
            try:
                live_raw = max(0.0, float(raw_formula(missing_ratio)))
            except (TypeError, ValueError):
                live_raw = raw_damage
            amount *= live_raw / raw_damage
        event["pair_damage"] = round(original_amount, 6)
        event["live_damage"] = round(amount, 6)
        state["damage_taken"] += amount
        damage_type = str(event.get("damage_type", ""))
        event_absorbed = 0.0
        if damage_type in {"magic", "physical"}:
            key = f"{damage_type}_shield"
            absorbed = min(state["shields"][key], amount)
            state["shields"][key] -= absorbed
            amount -= absorbed
            state["shield_absorbed"] += absorbed
            event_absorbed += absorbed
        general_absorbed = min(state["shields"]["general_shield"], amount)
        state["shields"]["general_shield"] -= general_absorbed
        amount -= general_absorbed
        state["shield_absorbed"] += general_absorbed
        event_absorbed += general_absorbed
        # Damage beyond the remaining shield + health is overkill, not more
        # effective HP.  Keep the original pair value for diagnostics but
        # expose only applied damage to the team-fight breakdown.
        applied_to_health = min(amount, state["health"])
        overkill = max(0.0, amount - applied_to_health)
        state["health"] = max(0.0, state["health"] - applied_to_health)
        state["health_damage"] += applied_to_health
        state["overkill"] += overkill
        event["overkill"] = round(overkill, 6)
        # The event's post-mitigation value is replaced with the amount that
        # actually consumed the target's shield/health.  Keep ``pair_damage``
        # and ``live_damage`` above for diagnostics without letting overkill
        # inflate team-fight TTD or BIS scores.
        event["damage"] = round(event_absorbed + applied_to_health, 6)
        if state["health"] <= 0.0 and state["death_time"] is None:
            state["death_time"] = min(float(duration), event_time)

    result = {}
    for participant_id, state in states.items():
        remaining_shields = sum(state["shields"].values())
        result[participant_id] = {
            "max_health": round(state["max_health"], 1),
            "ending_health": round(state["health"], 1),
            "damage_taken": round(state["damage_taken"], 1),
            "overkill": round(state["overkill"], 1),
            "health_damage": round(state["health_damage"], 1),
            "shield_absorbed": round(state["shield_absorbed"], 1),
            "healing_received": round(state["healing_received"], 1),
            "support_shield_received": round(state["support_shield_received"], 1),
            "effective_health": round(
                state["max_health"]
                + state["starting_shield"]
                + state["support_shield_received"]
                + state["healing_received"],
                1,
            ),
            "remaining_shield": round(remaining_shields, 1),
            "starting_shield": round(state["starting_shield"], 1),
            "survived_window": state["death_time"] is None,
            "death_time": (
                round(state["death_time"], 3)
                if state["death_time"] is not None
                else None
            ),
        }
    return result


def build_participant_timeline(
    champion_data: dict[str, Any],
    level: int,
    items: list[dict[str, Any]],
    params: FightParams,
    *,
    main_stats: dict[str, float],
    main_defenses: Any,
    enemies: list[ResolvedLoadout],
    allies: list[ResolvedLoadout],
    focus_participant_id: str = "main",
) -> dict[str, Any]:
    """Compose all selected actors and return the coupled combat receipt.

    ``focus_participant_id`` is used by BIS candidate evaluation.  The
    visible calculate response keeps the default focus on the main champion,
    while ally/enemy slot optimization can score the selected roster member
    without creating a fake one-attacker scenario.
    """
    main = _main_combatant(
        champion_data,
        level,
        items,
        stats=main_stats,
        defenses=main_defenses,
        params=params,
    )
    enemy_actors = [
        _from_loadout(f"enemy:{loadout.champion_data['name']}", "enemy", loadout)
        for loadout in enemies
    ]
    ally_actors = [
        _from_loadout(f"ally:{loadout.champion_data['name']}", "ally", loadout)
        for loadout in allies
    ]
    all_actors = [main, *ally_actors, *enemy_actors]
    outgoing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    incoming: dict[str, list[dict[str, Any]]] = defaultdict(list)
    healing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    support_effects: dict[str, list[dict[str, Any]]] = defaultdict(list)
    support_attached: set[str] = set()
    breakdown: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"participant_id": "", "team": "", "champion": "", "total_damage": 0.0, "sources": {}}
    )
    coverage_reports: list[dict[str, Any]] = []

    teams = {"main": [main], "ally": ally_actors, "enemy": enemy_actors}
    attack_groups = (
        ("main", [*enemy_actors]),
        ("ally", [*enemy_actors]),
        ("enemy", [main, *ally_actors]),
    )
    for attacker_team, defenders in attack_groups:
        attackers = teams[attacker_team]
        for attacker in attackers:
            if not defenders:
                continue
            actor_params = _actor_params(params, attacker)
            for defender in defenders:
                result = run_fight(
                    attacker.champion_data,
                    attacker.level,
                    list(attacker.items),
                    _target_params(actor_params, defender),
                )
                coverage_reports.append(dict(result.get("timeline_coverage", {})))
                result_events = list(result.get("damage_events", []))
                for event in result_events:
                    enriched = {
                        **event,
                        "attacker": attacker.participant_id,
                        "target": defender.participant_id,
                    }
                    event_index = len(outgoing[attacker.participant_id])
                    enriched["_event_id"] = (
                        f"{attacker.participant_id}:{defender.participant_id}:{event_index}"
                    )
                    outgoing[attacker.participant_id].append(enriched)
                    incoming[defender.participant_id].append(enriched)
                event_ids_by_key = {
                    (
                        str(event.get("source_key", "")),
                        round(float(event.get("time", 0.0)), 9),
                        int(event.get("sequence", 0) or 0),
                    ): event.get("_event_id")
                    for event in outgoing[attacker.participant_id]
                    if event.get("target") == defender.participant_id
                }
                for event in result.get("self_healing_events", []):
                    enriched_heal = {**event, "attacker": attacker.participant_id}
                    trigger_key = (
                        str(event.get("_trigger_source", "")),
                        round(float(event.get("_trigger_time", 0.0)), 9),
                        int(event.get("_trigger_sequence", 0) or 0),
                    )
                    trigger_id = event_ids_by_key.get(trigger_key)
                    if trigger_id is not None:
                        enriched_heal["_trigger_event_id"] = trigger_id
                    if event.get("actor_wide"):
                        duplicate = any(
                            existing.get("actor_wide")
                            and existing.get("source") == event.get("source")
                            and float(existing.get("time", 0.0))
                            == float(event.get("time", 0.0))
                            for existing in healing[attacker.participant_id]
                        )
                        if duplicate:
                            continue
                    healing[attacker.participant_id].append(enriched_heal)
                if attacker.participant_id not in support_attached:
                    _attach_support_effects(
                        attacker,
                        result,
                        all_actors,
                        support_effects,
                    )
                    support_attached.add(attacker.participant_id)
                row = breakdown[attacker.participant_id]
                row.update(
                    {
                        "participant_id": attacker.participant_id,
                        "team": attacker.team,
                        "champion": attacker.champion_data.get("name", ""),
                    }
                )
                row["total_damage"] += float(result.get("total_damage", 0.0))
                for source, entry in result.get("breakdown", {}).items():
                    row["sources"].setdefault(
                        source,
                        {"name": entry.get("name", source), "total_damage": 0.0},
                    )

    # A support source still has a cast schedule when no opposing target was
    # selected (for example, a main champion with allies but an empty enemy
    # roster).  Resolve that schedule once so ally/enemy support packets are
    # not silently dropped merely because the pairwise damage loop had no row.
    for attacker in all_actors:
        if attacker.participant_id in support_attached:
            continue
        actor_params = _actor_params(params, attacker)
        fallback = run_fight(
            attacker.champion_data,
            attacker.level,
            list(attacker.items),
            actor_params,
        )
        _attach_support_effects(attacker, fallback, all_actors, support_effects)
        support_attached.add(attacker.participant_id)

    survival = _simulate_survival(
        all_actors,
        incoming,
        healing,
        support_effects,
        params.fight_duration_seconds,
    )
    # An actor's damage after their death is not part of team-fight value.
    for actor in all_actors:
        death_time = survival[actor.participant_id]["death_time"]
        cutoff = params.fight_duration_seconds if death_time is None else death_time
        events = [event for event in outgoing[actor.participant_id] if float(event.get("time", 0.0)) <= cutoff]
        row = breakdown[actor.participant_id]
        row["total_damage"] = round(sum(float(event.get("damage", 0.0)) for event in events), 1)
        source_totals: dict[str, float] = defaultdict(float)
        for event in events:
            source_totals[str(event.get("source_key", ""))] += float(
                event.get("damage", 0.0)
            )
        row["sources"] = {
            source: {
                "name": row["sources"].get(source, {}).get("name", source),
                "total_damage": round(total, 1),
            }
            for source, total in source_totals.items()
            if total > 0
        }

    public_breakdown = []
    for actor in all_actors:
        row = breakdown.get(actor.participant_id) or {
            "participant_id": actor.participant_id,
            "team": actor.team,
            "champion": actor.champion_data.get("name", ""),
            "total_damage": 0.0,
            "sources": {},
        }
        public_breakdown.append(
            {
                **row,
                "total_damage": round(float(row.get("total_damage", 0.0)), 1),
                "sources": list(row.get("sources", {}).values()),
            }
        )
    focus_row = next(
        (row for row in public_breakdown if row["participant_id"] == focus_participant_id),
        None,
    )
    focus_survival = survival.get(focus_participant_id)
    focus_support = sum(
        float(event.get("amount", 0.0))
        for events in support_effects.values()
        for event in events
        if event.get("attacker") == focus_participant_id
    )
    focus_healing = sum(
        float(event.get("amount", 0.0))
        for event in healing.get(focus_participant_id, [])
    )
    return {
        "duration": float(params.fight_duration_seconds),
        "participants": [
            {
                "participant_id": actor.participant_id,
                "team": actor.team,
                "champion": actor.champion_data.get("name", ""),
                "level": actor.level,
                "stats": dict(actor.stats),
                "items": [item.get("name", "") for item in actor.items],
                "survival": survival[actor.participant_id],
            }
            for actor in all_actors
        ],
        "breakdown": public_breakdown,
        "events": [
            {
                "time": round(float(event.get("time", 0.0)), 3),
                "attacker": event.get("attacker"),
                "target": event.get("target"),
                "source": event.get("source_key", ""),
                "damage_type": event.get("damage_type", ""),
                "damage": round(float(event.get("damage", 0.0)), 1),
                "pair_damage": round(
                    float(event.get("pair_damage", event.get("damage", 0.0))), 1
                ),
                "overkill": round(float(event.get("overkill", 0.0)), 1),
                "event_precision": event.get("event_precision", "exact"),
                **(
                    {"skipped_reason": str(event["skipped_reason"])}
                    if event.get("skipped_reason")
                    else {}
                ),
            }
            for events in outgoing.values()
            for event in events
        ],
        "healing_events": [
            {
                "time": round(float(event.get("time", 0.0)), 3),
                "attacker": event.get("attacker"),
                "source": event.get("source", ""),
                "amount": round(float(event.get("amount", 0.0)), 1),
                **(
                    {"skipped_reason": str(event["skipped_reason"])}
                    if event.get("skipped_reason")
                    else {}
                ),
            }
            for events in healing.values()
            for event in events
        ],
        "support_events": [
            {
                "time": round(float(event.get("time", 0.0)), 3),
                "attacker": event.get("attacker"),
                "target": event.get("target"),
                "source": event.get("source", ""),
                "kind": event.get("kind", ""),
                "amount": round(float(event.get("amount", 0.0)), 1),
                "target_policy": event.get("target_policy", ""),
            }
            for events in support_effects.values()
            for event in events
        ],
        "objective": {
            "main_team_damage_before_death": round(
                sum(
                    row["total_damage"]
                    for row in public_breakdown
                    if row["team"] in {"main", "ally"}
                ),
                1,
            ),
            "enemy_team_damage_before_death": round(
                sum(row["total_damage"] for row in public_breakdown if row["team"] == "enemy"),
                1,
            ),
            "surviving_main_team": sum(
                1
                for actor in all_actors
                if actor.team in {"main", "ally"}
                and survival[actor.participant_id]["survived_window"]
            ),
            "focus_participant_id": focus_participant_id,
            "focus_damage_before_death": round(
                float(focus_row.get("total_damage", 0.0)) if focus_row else 0.0,
                1,
            ),
            "focus_survival": focus_survival,
            "focus_support_value": round(focus_support, 1),
            "focus_healing": round(focus_healing, 1),
        },
        "timeline_coverage": combine_timeline_coverages(
            coverage_reports,
            target_count=len(coverage_reports),
        ),
    }
