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
from operator import itemgetter
from typing import Any, Iterable, Mapping

from .pipeline import FightParams, require_fight_mode_support, run_fight
from .scenario import ResolvedLoadout
from .timeline_coverage import combine_timeline_coverages
from .support_effects import derive_ally_effects
from .healing_reduction import (
    GRIEVOUS_WOUNDS_FACTOR,
    healing_reduction_profiles,
    matching_healing_reduction,
)
from .item_effects import ThornsEffect, thorns_effects
from .resistance import apply_magic_penetration, apply_resistance


def require_roster_fight_window_support(
    params: FightParams,
    *,
    enemies: Iterable[ResolvedLoadout] = (),
    allies: Iterable[ResolvedLoadout] = (),
) -> None:
    """Reject a fight window a selected roster member cannot join.

    The coupled timeline runs every selected ally and enemy as an attacker
    through the same certified fight pipeline as the main champion, so a
    member whose module supports only one rotation cannot join a timed
    window. Failing here names the member instead of crashing mid-timeline.
    """
    for side, roster in (("Enemy", enemies), ("Ally", allies)):
        for loadout in roster:
            name = str(loadout.champion_data.get("name", ""))
            try:
                require_fight_mode_support(params, name)
            except ValueError as exc:
                raise ValueError(
                    f"{side} {name} cannot join this fight window: {exc}"
                ) from exc


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


def _event_sequence(event: Mapping[str, Any]) -> int:
    """Return a stable source sequence for simultaneous event ordering."""
    value = event.get("sequence", event.get("_trigger_sequence", 0))
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _participant_order(participant_id: Any) -> tuple[int, str]:
    """Use a deterministic side order when sources share a timestamp."""
    text = str(participant_id or "")
    if text == "main":
        return (0, text)
    if text.startswith("ally:"):
        return (1, text)
    if text.startswith("enemy:"):
        return (2, text)
    return (3, text)


def _action_key(
    event_time: float,
    phase: float,
    participant_id: str,
    event: Mapping[str, Any],
) -> tuple[Any, ...]:
    """Order event phases without ever comparing payload dictionaries.

    This is the survival walk's total order.  Pair packets precompute it per
    event (``_sk``) because the walk re-sorts the same roster events for
    every optimizer candidate.
    """
    source_id = event.get("attacker", participant_id)
    return (
        float(event_time),
        float(phase),
        _event_sequence(event),
        *_participant_order(source_id),
        str(participant_id),
        str(event.get("_event_id", "")),
        str(event.get("source", event.get("source_key", ""))),
    )


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


def _target_overrides(defender: Combatant) -> dict[str, float | str]:
    """Everything a one-pair fight reads from its target, as replace() kwargs.

    This dict is also the pair-result cache signature for fights against a
    candidate main build: two candidates with equal overrides produce
    byte-identical incoming fights, so keeping the params and the signature
    in one place guarantees the cache can never ignore a field the engine
    reads.
    """
    defenses = defender.defenses
    return {
        "target_health": float(defender.stats.get("health", 0.0)),
        "target_bonus_health": float(defender.stats.get("bonus_health", 0.0)),
        "target_armor": float(defender.stats.get("armor", 0.0)),
        "target_magic_resistance": float(defender.stats.get("magic_resistance", 0.0)),
        "target_magic_shield": float(defenses.magic_shield),
        "target_physical_shield": float(defenses.physical_shield),
        "target_general_shield": float(defenses.general_shield),
        "target_basic_damage_multiplier": float(defenses.basic_damage_multiplier),
        "target_basic_damage_flat_reduction": float(
            defenses.basic_damage_flat_reduction
        ),
        "target_basic_damage_flat_reduction_cap": float(
            defenses.basic_damage_flat_reduction_cap
        ),
        "target_critical_strike_damage_multiplier": float(
            defenses.critical_strike_damage_multiplier
        ),
        "target_threshold_shield_amount": float(defenses.threshold_shield_amount),
        "target_threshold_shield_health_ratio": float(
            defenses.threshold_shield_health_ratio
        ),
        "target_threshold_shield_duration": float(defenses.threshold_shield_duration),
        "target_threshold_shield_damage_type": str(
            defenses.threshold_shield_damage_type
        ),
        "target_threshold_health_bonus": float(defenses.threshold_health_bonus),
        "target_threshold_health_heal": float(defenses.threshold_health_heal),
        "target_threshold_health_ratio": float(defenses.threshold_health_ratio),
        "target_threshold_health_duration": float(defenses.threshold_health_duration),
    }


def _target_params(base: FightParams, defender: Combatant) -> FightParams:
    return replace(base, **_target_overrides(defender))


def _defensive_signature(defender: Combatant) -> tuple[Any, ...]:
    """A hashable key equal exactly when ``_target_params`` would be equal."""
    return tuple(_target_overrides(defender).values())


def _pair_packet(
    result: Mapping[str, Any],
    attacker_id: str,
    defender_id: str,
) -> dict[str, Any]:
    """Enrich one pair fight's events exactly once.

    The coupled optimizer replays cached pair results for thousands of
    candidates, so everything derivable from the result alone — attacker and
    target ids, per-pair event ids, heal trigger links, and the survival
    walk's precomputed sort key — lives on templates here.  Applying a packet
    to one evaluation only shallow-copies each template, because the walk
    mutates its copy's top-level fields.
    """
    events: list[dict[str, Any]] = []
    event_ids_by_key: dict[tuple[str, float, int], str] = {}
    for index, event in enumerate(result.get("damage_events", [])):
        enriched = {
            **event,
            "attacker": attacker_id,
            "target": defender_id,
            "_event_id": f"{attacker_id}:{defender_id}:{index}",
        }
        enriched["_sk"] = _action_key(
            float(event.get("time", 0.0)), 0.0, defender_id, enriched
        )
        events.append(enriched)
        event_ids_by_key[
            (
                str(event.get("source_key", "")),
                round(float(event.get("time", 0.0)), 9),
                int(event.get("sequence", 0) or 0),
            )
        ] = enriched["_event_id"]
    heals: list[dict[str, Any]] = []
    for event in result.get("self_healing_events", []):
        enriched_heal = {**event, "attacker": attacker_id}
        trigger_id = event_ids_by_key.get(
            (
                str(event.get("_trigger_source", "")),
                round(float(event.get("_trigger_time", 0.0)), 9),
                int(event.get("_trigger_sequence", 0) or 0),
            )
        )
        if trigger_id is not None:
            enriched_heal["_trigger_event_id"] = trigger_id
        enriched_heal["_sk"] = _action_key(
            float(event.get("time", 0.0)), 1.0, attacker_id, enriched_heal
        )
        heals.append(enriched_heal)
    return {
        "result": result,
        "events": events,
        "heals": heals,
        # Display-name rows for the attacker breakdown; never mutated (the
        # post-survival pass rebuilds source rows wholesale), so they are
        # shared across evaluations as-is.
        "source_names": {
            source: {"name": entry.get("name", source), "total_damage": 0.0}
            for source, entry in result.get("breakdown", {}).items()
        },
    }


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
        if ("main" if actor.team in {"main", "ally"} else actor.team) == attacker_side
        and actor.participant_id != attacker.participant_id
    ]
    if not teammates:
        return [], "no_selected_teammate"
    if effect.get("target_scope") == "all_teammates":
        return [actor.participant_id for actor in teammates], "all_selected_teammates"
    return [teammates[0].participant_id], "first_selected_teammate"


def _support_effect_templates(
    attacker: Combatant,
    result: Mapping[str, Any],
    all_actors: list[Combatant],
) -> list[dict[str, Any]]:
    """Derive one actor's sourced shield/heal packets, resolved to targets.

    Returned templates are reusable across optimizer candidates (the roster
    and each cached pair result are fixed), so they ride the pair packet;
    application shallow-copies each one because the survival walk annotates
    its copy.
    """
    if attacker.team == "ally" and not getattr(
        attacker.request, "ally_effects_enabled", False
    ):
        return []
    request = attacker.request
    effects = derive_ally_effects(
        attacker.champion_data,
        attacker.level,
        result.get("champion_stats", attacker.stats),
        list(result.get("cast_timeline", [])),
        ability_ranks=getattr(request, "ability_ranks", None),
    )
    templates = []
    for effect in effects:
        target_ids, target_policy = _support_target_ids(attacker, effect, all_actors)
        for target_id in target_ids:
            templates.append(
                {
                    **effect,
                    "attacker": attacker.participant_id,
                    "target": target_id,
                    "target_policy": target_policy,
                }
            )
    return templates


def _attach_support_effects(
    attacker: Combatant,
    result: Mapping[str, Any],
    all_actors: list[Combatant],
    support_effects: dict[str, list[dict[str, Any]]],
) -> None:
    """Attach one actor's sourced shield/heal packets exactly once."""
    for template in _support_effect_templates(attacker, result, all_actors):
        support_effects[template["target"]].append(dict(template))


def _thorns_return_damage(
    profile: ThornsEffect,
    wearer: Combatant,
    striker: Combatant,
) -> float:
    """Price one thorns strike-back against the striker's resistances.

    Thorns damage benefits from the wearer's penetration and is mitigated
    by the striker like any other damage of its type.
    """
    if profile.damage_type != "magic":
        raise ValueError(
            f"{profile.item_name} thorns damage type "
            f"{profile.damage_type!r} is not supported"
        )
    resistance = apply_magic_penetration(
        float(striker.stats.get("magic_resistance", 0.0)),
        float(wearer.stats.get("magic_penetration_flat", 0.0)),
        float(wearer.stats.get("magic_penetration_percent", 0.0)) / 100.0,
    )
    return apply_resistance(profile.damage, resistance)


def _schedule_thorns_events(
    all_actors: list[Combatant],
    incoming: dict[str, list[dict[str, Any]]],
    outgoing: dict[str, list[dict[str, Any]]],
) -> None:
    """Emit reactive Thorns events from modeled incoming basic attacks.

    Every basic-attack swing that strikes a thorns wearer schedules one
    return-damage event onto the striker at the swing's own timestamp,
    linked to the strike so a skipped strike (dead striker or dead
    wearer) never retaliates. The event also carries the wound window the
    survival walk applies to the striker's healing.
    """
    combatant_by_id = {actor.participant_id: actor for actor in all_actors}
    for wearer in all_actors:
        profiles = thorns_effects(list(wearer.items))
        if not profiles:
            continue
        strikes = [
            event
            for event in incoming.get(wearer.participant_id, [])
            if event.get("source_key") == "auto_attacks"
        ]
        for index, strike in enumerate(strikes):
            striker = combatant_by_id.get(str(strike.get("attacker")))
            if striker is None:
                continue
            for profile in profiles:
                event = {
                    "time": float(strike.get("time", 0.0)),
                    "damage": _thorns_return_damage(profile, wearer, striker),
                    "damage_type": profile.damage_type,
                    "source_key": f"thorns_{profile.item_name}",
                    "source": f"{profile.item_name} (Thorns)",
                    "attacker": wearer.participant_id,
                    "target": striker.participant_id,
                    "sequence": int(strike.get("sequence", 0) or 0),
                    "event_precision": "exact",
                    "_event_id": (
                        f"{wearer.participant_id}:{striker.participant_id}"
                        f":thorns:{profile.item_name}:{index}"
                    ),
                    "_trigger_event_id": strike.get("_event_id"),
                    "_reactive": True,
                    "grievous_duration": profile.grievous_duration,
                    "_wound_source": f"{profile.item_name} · Thorns",
                }
                incoming.setdefault(striker.participant_id, []).append(event)
                outgoing.setdefault(wearer.participant_id, []).append(event)


def _simulate_survival(
    combatants: Iterable[Combatant],
    incoming: Mapping[str, list[dict[str, Any]]],
    healing: Mapping[str, list[dict[str, Any]]],
    support_effects: Mapping[str, list[dict[str, Any]]],
    duration: float,
    annotate: bool = True,
) -> dict[str, dict[str, Any]]:
    """Resolve damage, shields, healing, and death for every participant.

    ``annotate=False`` skips the per-event diagnostic fields that only the
    serialized public receipt reads (pair/live damage, overkill, healing
    receipts); every survival number and every field the breakdown sums —
    including each event's applied ``damage`` — is written either way.
    """
    combatant_list = list(combatants)
    combatant_by_id = {
        combatant.participant_id: combatant for combatant in combatant_list
    }
    reduction_profiles = {
        participant_id: healing_reduction_profiles(combatant.items)
        for participant_id, combatant in combatant_by_id.items()
    }
    states: dict[str, dict[str, Any]] = {}
    for combatant in combatant_list:
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
            "healing_reduced": 0.0,
            "support_shield_received": 0.0,
            "healing_reduction_until": 0.0,
            "healing_reduction_factor": 1.0,
            "healing_reduction_sources": set(),
            "death_time": None,
        }

    actions: list[tuple[tuple[Any, ...], str, dict[str, Any]]] = []
    damage_event_status: dict[str, str] = {}
    for participant_id, events in support_effects.items():
        for event in events:
            # A sourced ally shield is a pre-damage barrier.  A sourced heal
            # is a post-damage recovery event.  They must not share one
            # priority merely because both are support effects.
            kind = str(event.get("kind", ""))
            priority = -1.0 if kind == "shield" else 1.0
            actions.append(
                (
                    _action_key(
                        float(event.get("time", 0.0)), priority, participant_id, event
                    ),
                    participant_id,
                    event,
                )
            )
    # Damage resolves before self-healing and sourced recovery at the same
    # timestamp, while shields remain before damage above. Reactive
    # strike-back damage (Thorns) resolves after the strikes that
    # triggered it but still before same-timestamp healing.  Pair packets
    # carry their precomputed key (``_sk``); events authored outside a
    # packet (thorns strike-backs) compute theirs here.
    for participant_id, events in incoming.items():
        actions.extend(
            (
                event.get("_sk")
                or _action_key(
                    float(event.get("time", 0.0)),
                    0.5 if event.get("_reactive") else 0.0,
                    participant_id,
                    event,
                ),
                participant_id,
                event,
            )
            for event in events
        )
    for participant_id, events in healing.items():
        actions.extend(
            (
                event.get("_sk")
                or _action_key(
                    float(event.get("time", 0.0)), 1.0, participant_id, event
                ),
                participant_id,
                event,
            )
            for event in events
        )
    actions.sort(key=itemgetter(0))

    for action_key, participant_id, event in actions:
        event_time, phase = action_key[0], action_key[1]
        state = states[participant_id]
        trigger_id = event.get("_trigger_event_id")
        if trigger_id is not None and (
            damage_event_status.get(str(trigger_id)) != "applied"
        ):
            # An effect whose trigger event was skipped (its target or
            # attacker was already dead) must not survive on its own —
            # neither a recovery tick nor a reactive strike-back.
            if phase >= 1:
                event["applied_amount"] = 0.0
            else:
                if annotate:
                    event.setdefault("pair_damage", float(event.get("damage", 0.0)))
                    event["live_damage"] = 0.0
                    event["overkill"] = 0.0
                event["damage"] = 0.0
            event["skipped_reason"] = "trigger_event_skipped"
            continue
        if state["death_time"] is not None:
            # Preserve the scheduled source in the receipt, but do not let
            # a dead target contribute post-death damage to TTD/BIS.
            if annotate:
                event.setdefault("pair_damage", float(event.get("damage", 0.0)))
                event["live_damage"] = 0.0
                event["overkill"] = 0.0
            event["damage"] = 0.0
            event["applied_amount"] = 0.0
            event["skipped_reason"] = "target_dead"
            continue
        source_id = event.get("attacker")
        if (
            source_id in states
            and states[source_id]["death_time"] is not None
            and not event.get("_reactive")
        ):
            # A dead actor cannot continue an already-scheduled rotation or
            # emit a support effect later in the shared window. Reactive
            # strike-back is exempt: its trigger linkage above already
            # proves the wearer was alive when struck (a killing blow
            # still takes the thorns with it).
            if annotate:
                event.setdefault("pair_damage", float(event.get("damage", 0.0)))
                event["live_damage"] = 0.0
                event["overkill"] = 0.0
            event["damage"] = 0.0
            event["applied_amount"] = 0.0
            event["skipped_reason"] = "attacker_dead"
            continue
        if phase == -1:
            kind = str(event.get("kind", ""))
            amount = max(0.0, float(event.get("amount", 0.0)))
            if kind == "shield":
                state["shields"]["general_shield"] += amount
                state["support_shield_received"] += amount
                event["applied_amount"] = round(amount, 6)
            elif kind == "heal":
                reduction_factor = (
                    1.0
                    if event_time >= state["healing_reduction_until"]
                    else state["healing_reduction_factor"]
                )
                reduced_amount = amount * reduction_factor
                state["healing_reduced"] += max(0.0, amount - reduced_amount)
                received = min(
                    reduced_amount,
                    max(0.0, state["max_health"] - state["health"]),
                )
                state["health"] += received
                state["healing_received"] += received
                if annotate:
                    event["raw_amount"] = round(amount, 6)
                    event["reduced_amount"] = round(reduced_amount, 6)
                    event["healing_reduction_factor"] = round(reduction_factor, 6)
                event["applied_amount"] = round(received, 6)
            continue
        if phase == 1:
            amount = max(0.0, float(event.get("amount", 0.0)))
            reduction_factor = (
                1.0
                if event_time >= state["healing_reduction_until"]
                else state["healing_reduction_factor"]
            )
            reduced_amount = amount * reduction_factor
            state["healing_reduced"] += max(0.0, amount - reduced_amount)
            received = min(
                reduced_amount,
                max(0.0, state["max_health"] - state["health"]),
            )
            state["health"] += received
            state["healing_received"] += received
            if annotate:
                event["raw_amount"] = round(amount, 6)
                event["reduced_amount"] = round(reduced_amount, 6)
                event["healing_reduction_factor"] = round(reduction_factor, 6)
            event["applied_amount"] = round(received, 6)
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
        if annotate:
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
        if annotate:
            event["overkill"] = round(overkill, 6)
        # The event's post-mitigation value is replaced with the amount that
        # actually consumed the target's shield/health.  Keep ``pair_damage``
        # and ``live_damage`` above for diagnostics without letting overkill
        # inflate team-fight TTD or BIS scores.
        event["damage"] = round(event_absorbed + applied_to_health, 6)
        attacker_profiles = reduction_profiles.get(str(source_id), ())
        matching_profiles = (
            matching_healing_reduction(attacker_profiles, damage_type)
            if attacker_profiles
            else ()
        )
        if matching_profiles and event["damage"] > 0:
            # Grievous Wounds sources do not stack; refresh the strongest
            # sourced window when another qualifying hit lands.
            strongest = min(
                matching_profiles,
                key=lambda profile: float(profile.get("factor", 1.0)),
            )
            state["healing_reduction_until"] = max(
                state["healing_reduction_until"],
                event_time + float(strongest.get("duration", 0.0)),
            )
            state["healing_reduction_factor"] = min(
                state["healing_reduction_factor"],
                float(strongest.get("factor", 1.0)),
            )
            for profile in matching_profiles:
                state["healing_reduction_sources"].add(
                    f"{profile.get('item', '')} · {profile.get('source', '')}"
                )
            if annotate:
                event["healing_reduction"] = {
                    "factor": round(state["healing_reduction_factor"], 6),
                    "until": round(state["healing_reduction_until"], 6),
                    "sources": sorted(state["healing_reduction_sources"]),
                }
        wound_duration = float(event.get("grievous_duration", 0.0) or 0.0)
        if wound_duration > 0:
            # A reactive wound (Thorns) rides its strike-back event and
            # lands on this event's target — the striker — even when the
            # return damage itself was fully absorbed by shields.
            state["healing_reduction_until"] = max(
                state["healing_reduction_until"],
                event_time + wound_duration,
            )
            state["healing_reduction_factor"] = min(
                state["healing_reduction_factor"],
                GRIEVOUS_WOUNDS_FACTOR,
            )
            state["healing_reduction_sources"].add(
                str(event.get("_wound_source", "Grievous Wounds"))
            )
            if annotate:
                event["healing_reduction"] = {
                    "factor": round(state["healing_reduction_factor"], 6),
                    "until": round(state["healing_reduction_until"], 6),
                    "sources": sorted(state["healing_reduction_sources"]),
                }
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
            "healing_reduced": round(state["healing_reduced"], 1),
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
            "healing_reduction_until": round(state["healing_reduction_until"], 3),
            "healing_reduction_sources": sorted(state["healing_reduction_sources"]),
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
    pair_result_cache: dict[tuple[Any, ...], dict[str, Any]] | None = None,
    include_receipt: bool = True,
    reuse_main_stats: bool = False,
) -> dict[str, Any]:
    """Compose all selected actors and return the coupled combat receipt.

    ``focus_participant_id`` is used by BIS candidate evaluation.  The
    visible calculate response keeps the default focus on the main champion,
    while ally/enemy slot optimization can score the selected roster member
    without creating a fake one-attacker scenario.

    ``include_receipt=False`` returns the scoring subset only — survival,
    per-actor breakdown, and the ordering receipt — with identical numbers;
    optimizer candidate evaluation uses it because nothing ever displays a
    candidate's serialized timeline.

    ``reuse_main_stats=True`` is a caller-owned claim that ``main_stats``
    was calculated with exactly the configuration a main pair fight would
    use (same role, item options, and no external ally bonuses), letting
    those fights skip one identical stat calculation per enemy.  Leave it
    False when the main stats came from a loadout whose role or options can
    differ from ``params`` (the roster BIS path).
    """
    require_roster_fight_window_support(params, enemies=enemies, allies=allies)
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
        lambda: {
            "participant_id": "",
            "team": "",
            "champion": "",
            "total_damage": 0.0,
            "sources": {},
        }
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
                # The coupled optimizer evaluates thousands of main candidates
                # against one fixed roster, so pair fights that cannot differ
                # between evaluations are cached.  Roster-to-roster pairs do
                # not depend on the candidate main build at all.  A fight INTO
                # the main candidate depends on it only through the target
                # fields ``_target_overrides`` feeds the engine, so its cache
                # key carries that defensive signature: a candidate swap that
                # changes no defensive stat replays the identical incoming
                # fights instead of re-simulating them.  Fights the candidate
                # attacks with are always recomputed.
                cacheable = attacker.participant_id != "main"
                if defender.participant_id == "main":
                    cache_key = (
                        attacker.participant_id,
                        defender.participant_id,
                        _defensive_signature(defender),
                    )
                else:
                    cache_key = (attacker.participant_id, defender.participant_id)
                packet = (
                    pair_result_cache.get(cache_key)
                    if cacheable and pair_result_cache is not None
                    else None
                )
                if packet is None:
                    reusable_stats = (
                        attacker.stats
                        if reuse_main_stats and attacker.participant_id == "main"
                        else None
                    )
                    packet = _pair_packet(
                        run_fight(
                            attacker.champion_data,
                            attacker.level,
                            list(attacker.items),
                            _target_params(actor_params, defender),
                            precomputed_stats=reusable_stats,
                        ),
                        attacker.participant_id,
                        defender.participant_id,
                    )
                    if cacheable and pair_result_cache is not None:
                        pair_result_cache[cache_key] = packet
                result = packet["result"]
                coverage_reports.append(result.get("timeline_coverage", {}))
                # A packet that lives in the cache serves later evaluations,
                # so this one only takes copies (the walk mutates its rows).
                # A single-use packet's rows are appended directly.
                copy_templates = cacheable and pair_result_cache is not None
                attacker_outgoing = outgoing[attacker.participant_id]
                defender_incoming = incoming[defender.participant_id]
                for template in packet["events"]:
                    enriched = dict(template) if copy_templates else template
                    attacker_outgoing.append(enriched)
                    defender_incoming.append(enriched)
                attacker_healing = healing[attacker.participant_id]
                for template in packet["heals"]:
                    if template.get("actor_wide"):
                        duplicate = any(
                            existing.get("actor_wide")
                            and existing.get("source") == template.get("source")
                            and float(existing.get("time", 0.0))
                            == float(template.get("time", 0.0))
                            for existing in attacker_healing
                        )
                        if duplicate:
                            continue
                    attacker_healing.append(
                        dict(template) if copy_templates else template
                    )
                if attacker.participant_id not in support_attached:
                    support_templates = packet.get("support")
                    if support_templates is None:
                        support_templates = _support_effect_templates(
                            attacker, result, all_actors
                        )
                        packet["support"] = support_templates
                    for template in support_templates:
                        support_effects[template["target"]].append(
                            dict(template) if copy_templates else template
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
                if include_receipt:
                    row_sources = row["sources"]
                    for source, template in packet["source_names"].items():
                        row_sources.setdefault(source, template)

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

    _schedule_thorns_events(all_actors, incoming, outgoing)

    survival = _simulate_survival(
        all_actors,
        incoming,
        healing,
        support_effects,
        params.fight_duration_seconds,
        annotate=include_receipt,
    )
    # An actor's damage after their death is not part of team-fight value.
    for actor in all_actors:
        death_time = survival[actor.participant_id]["death_time"]
        cutoff = params.fight_duration_seconds if death_time is None else death_time
        events = [
            event
            for event in outgoing[actor.participant_id]
            if float(event.get("time", 0.0)) <= cutoff
        ]
        row = breakdown[actor.participant_id]
        row["total_damage"] = round(
            sum(float(event.get("damage", 0.0)) for event in events), 1
        )
        if not include_receipt:
            # The scoring subset carries damage totals, not per-source rows.
            row["sources"] = {}
            continue
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
    support_by_attacker: dict[str, float] = defaultdict(float)
    healing_by_attacker: dict[str, float] = defaultdict(float)
    for events in support_effects.values():
        for event in events:
            attacker_id = str(event.get("attacker", ""))
            applied = float(event.get("applied_amount", 0.0))
            support_by_attacker[attacker_id] += applied
            if event.get("kind") == "heal":
                healing_by_attacker[attacker_id] += applied
    for actor in all_actors:
        row = breakdown.get(actor.participant_id) or {
            "participant_id": actor.participant_id,
            "team": actor.team,
            "champion": actor.champion_data.get("name", ""),
            "total_damage": 0.0,
            "sources": {},
        }
        actor_survival = survival[actor.participant_id]
        public_breakdown.append(
            {
                **row,
                "total_damage": round(float(row.get("total_damage", 0.0)), 1),
                "sources": list(row.get("sources", {}).values()),
                "outgoing_damage_before_death": round(
                    float(row.get("total_damage", 0.0)), 1
                ),
                "incoming_damage": round(
                    float(actor_survival.get("health_damage", 0.0))
                    + float(actor_survival.get("shield_absorbed", 0.0)),
                    1,
                ),
                "health_damage": actor_survival.get("health_damage", 0.0),
                "shield_absorbed": actor_survival.get("shield_absorbed", 0.0),
                "effective_health": actor_survival.get("effective_health", 0.0),
                "healing_received": actor_survival.get("healing_received", 0.0),
                "healing_reduced": actor_survival.get("healing_reduced", 0.0),
                "support_shield_received": actor_survival.get(
                    "support_shield_received", 0.0
                ),
                "support_value": round(support_by_attacker[actor.participant_id], 1),
                "healing_output": round(healing_by_attacker[actor.participant_id], 1),
                "survived_window": bool(actor_survival.get("survived_window")),
                "death_time": actor_survival.get("death_time"),
            }
        )
    if not include_receipt:
        # Optimizer scoring reads only the survival rows, the per-actor
        # damage breakdown, and the ordering receipt.  Skip the public
        # event/healing/support serialization for the thousands of candidate
        # evaluations that never show a timeline to anyone.
        return {
            "duration": float(params.fight_duration_seconds),
            "participants": [
                {
                    "participant_id": actor.participant_id,
                    "team": actor.team,
                    "champion": actor.champion_data.get("name", ""),
                    "level": actor.level,
                    "survival": survival[actor.participant_id],
                }
                for actor in all_actors
            ],
            "breakdown": public_breakdown,
            "timeline_coverage": combine_timeline_coverages(
                coverage_reports,
                target_count=len(coverage_reports),
            ),
        }

    focus_row = next(
        (
            row
            for row in public_breakdown
            if row["participant_id"] == focus_participant_id
        ),
        None,
    )
    focus_survival = survival.get(focus_participant_id)
    focus_support = sum(
        float(event.get("applied_amount", 0.0))
        for events in support_effects.values()
        for event in events
        if event.get("attacker") == focus_participant_id
    )
    focus_healing = sum(
        float(event.get("applied_amount", 0.0))
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
                    {"healing_reduction": dict(event["healing_reduction"])}
                    if event.get("healing_reduction")
                    else {}
                ),
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
                "raw_amount": round(
                    float(event.get("raw_amount", event.get("amount", 0.0))), 1
                ),
                "applied_amount": round(
                    float(event.get("applied_amount", event.get("amount", 0.0))), 1
                ),
                "reduced_amount": round(
                    float(event.get("reduced_amount", event.get("amount", 0.0))), 1
                ),
                "healing_reduction_factor": round(
                    float(event.get("healing_reduction_factor", 1.0)), 3
                ),
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
                "applied_amount": round(
                    float(event.get("applied_amount", event.get("amount", 0.0))), 1
                ),
                "target_policy": event.get("target_policy", ""),
                **(
                    {"skipped_reason": str(event["skipped_reason"])}
                    if event.get("skipped_reason")
                    else {}
                ),
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
                sum(
                    row["total_damage"]
                    for row in public_breakdown
                    if row["team"] == "enemy"
                ),
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
            "main_team_effective_health": round(
                sum(
                    float(survival[actor.participant_id]["effective_health"])
                    for actor in all_actors
                    if actor.team in {"main", "ally"}
                ),
                1,
            ),
            "enemy_team_effective_health": round(
                sum(
                    float(survival[actor.participant_id]["effective_health"])
                    for actor in all_actors
                    if actor.team == "enemy"
                ),
                1,
            ),
            "total_support_value": round(sum(support_by_attacker.values()), 1),
            "total_healing_reduced": round(
                sum(float(state["healing_reduced"]) for state in survival.values()),
                1,
            ),
        },
        "timeline_coverage": combine_timeline_coverages(
            coverage_reports,
            target_count=len(coverage_reports),
        ),
    }
