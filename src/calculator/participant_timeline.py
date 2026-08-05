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
import math
from operator import itemgetter
from typing import Any, Iterable, Mapping, MutableMapping

from .pipeline import FightParams, require_fight_mode_support, run_fight
from .scenario import ResolvedLoadout
from .timeline_coverage import combine_timeline_coverages
from .item_coverage import item_model_coverage
from .support_effects import derive_ally_effects
from .item_support_effects import (
    derive_item_support_effects,
    has_ordered_item_team_effects,
    schedule_knights_vow,
)
from .healing_reduction import (
    GRIEVOUS_WOUNDS_FACTOR,
    healing_reduction_profiles,
    matching_healing_reduction,
)
from .item_effects import (
    ThornsEffect,
    required_effect_value,
    sustain_effect_value,
    thorns_effects,
)
from .resistance import (
    apply_armor_penetration,
    apply_magic_penetration,
    apply_resistance,
)
from .stats import get_item_stats


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


def _evaluate_live_raw_formula(
    raw_formula: Any,
    missing_ratio: float,
    target_max_health: float,
) -> float:
    """Evaluate a dynamic packet against the live target maximum health.

    Existing champion callbacks accept only the live missing-health ratio.
    New target-maximum-health packets may also accept the temporary maximum
    health as a second argument; the one-argument fallback keeps older
    reviewed callbacks bit-for-bit compatible.
    """
    try:
        return max(0.0, float(raw_formula(missing_ratio, target_max_health)))
    except TypeError:
        return max(0.0, float(raw_formula(missing_ratio)))


def _coalesce_darius_q_heals(
    healing: MutableMapping[str, list[dict[str, Any]]],
) -> None:
    """Combine Darius Q pair receipts into one live heal per cast."""
    for events in healing.values():
        groups: dict[tuple[float, int], tuple[dict[str, Any], int]] = {}
        kept: list[dict[str, Any]] = []
        for event in events:
            marker = event.get("_darius_q_group")
            if not isinstance(marker, tuple) or len(marker) != 2:
                kept.append(event)
                continue
            key = (float(marker[0]), int(marker[1]))
            first = groups.get(key)
            if first is None:
                groups[key] = (event, 1)
                kept.append(event)
            else:
                groups[key] = (first[0], first[1] + 1)
        for event, count in groups.values():
            event["amount_formula"] = (
                lambda current_health, maximum_health, count=count: (
                    max(0.0, maximum_health - current_health) * min(0.51, 0.17 * count)
                )
            )
        events[:] = kept


def _coalesce_compiled_darius_q_heals(
    actions: Iterable[tuple[Any, ...]],
) -> list[tuple[Any, ...]]:
    """Coalesce compiled Decimate heals across pair packets."""
    groups: dict[tuple[int, float, int, str], tuple[int, int]] = {}
    kept: list[tuple[Any, ...]] = []
    for action in actions:
        if action[_A_KIND] != _KIND_HEAL or action[0][-1] != "Decimate":
            kept.append(action)
            continue
        key = (
            int(action[_A_ATTACKER]),
            float(action[_A_TIME]),
            int(action[0][2]),
            str(action[0][-1]),
        )
        first = groups.get(key)
        if first is None:
            groups[key] = (len(kept), 1)
            kept.append(action)
            continue
        first_index, count = first
        groups[key] = (first_index, count + 1)
    for first_index, count in groups.values():
        action = kept[first_index]
        formula = action[_A_RAW_FORMULA]
        if not callable(formula):
            continue

        def coalesced(current_health, maximum_health, formula=formula, count=count):
            return max(0.0, float(formula(current_health, maximum_health))) * min(
                3, count
            )

        kept[first_index] = (
            action[:_A_RAW_FORMULA] + (coalesced,) + action[_A_RAW_FORMULA + 1 :]
        )
    return kept


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

    The ``_event_id`` component is a dead tie-break for engine damage
    events: ``sequence`` is unique per pair fight, and events from
    different pairs already differ at the source/participant components.
    ``_pair_packet``'s pair-local event numbering depends on that — if an
    engine event ever arrived without its sequence, the id string would
    start deciding order, so the packet builder rejects that instead of
    letting numbering become order-relevant.
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
                "cast_order": params.cast_order,
                "item_options": params.item_options,
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
    attack_speed_multiplier = 1.0
    if any(item.get("name") == "Frozen Heart" for item in defender.items):
        attack_speed_multiplier = 1.0 - float(
            required_effect_value("Frozen Heart", "attack_speed_reduction")
        )
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
        "attacker_attack_speed_multiplier": attack_speed_multiplier,
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
        "target_revive_health_amount": float(defenses.revive_health_amount),
        "target_revive_delay": float(defenses.revive_delay),
        "target_revive_cooldown": float(defenses.revive_cooldown),
    }


def _target_params(base: FightParams, defender: Combatant) -> FightParams:
    return replace(base, **_target_overrides(defender))


def _defensive_signature(defender: Combatant) -> tuple[Any, ...]:
    """A hashable key equal exactly when ``_target_params`` would be equal."""
    return tuple(_target_overrides(defender).values())


def _has_stateful_defense(defenses: Any) -> bool:
    """Whether a defense requires the event walk rather than compiled score.

    The optimized panel intentionally contains only static shields and damage
    mitigation. Threshold lifelines and temporary-health transitions depend on
    the live health boundary, so routing them through the panel would silently
    erase a state change. The caller falls back to the authoritative event
    walk when any such field is armed.
    """
    return (
        any(
            float(getattr(defenses, field, 0.0) or 0.0) > 0.0
            for field in (
                "threshold_shield_amount",
                "threshold_health_bonus",
                "threshold_health_heal",
                "revive_health_amount",
                "reactive_shield_amount",
            )
        )
        or bool(getattr(defenses, "spell_shield_ready", False))
        or float(getattr(defenses, "incoming_damage_multiplier", 1.0) or 1.0) < 1.0
    )


def _has_ordered_item_defense(items: Iterable[Mapping[str, Any]]) -> bool:
    """Return whether a loadout needs the full ordered item event walk."""
    return any(
        str(item.get("name", ""))
        in {
            "Eclipse",
            "Death's Dance",
            "Armored Advance",
            "Chainlaced Crushers",
            "Celestial Opposition",
            "Bloodthirster",
            "Fimbulwinter",
            "Force of Nature",
            "Jak'Sho, The Protean",
            "Zhonya's Hourglass",
            "Seeker's Armguard",
        }
        for item in items
    )


def _has_ordered_item_sustain(
    items: Iterable[Mapping[str, Any]], *, include_warmog: bool = True
) -> bool:
    """Return whether item healing/regen needs the authoritative event walk.

    The compiled optimizer walk intentionally stores only numeric heal
    amounts.  It cannot carry the source category needed for Spirit Visage
    (lifesteal/omnivamp are stat conversions, while direct heals and regen
    are received-healing packets), nor can it author Warmog/Doran trigger
    state.  Route those builds through the same ordered path as the visible
    participant receipt.
    """
    stateful_names = {
        "Doran's Blade",
        "Doran's Ring",
        "Doran's Shield",
    }
    for item in items:
        name = str(item.get("name", ""))
        if name == "Warmog's Armor" and not include_warmog:
            continue
        if include_warmog and name == "Warmog's Armor":
            return True
        if name in stateful_names:
            return True
        try:
            stats = get_item_stats(dict(item))
        except (TypeError, ValueError, KeyError):
            # A malformed cached item must not be made more permissive by
            # the optimizer shortcut; the normal path will surface its
            # source/schema error.
            return True
        if any(
            float(stats[key]) > 0.0
            for key in (
                "lifesteal_percent",
                "omnivamp_percent",
            )
        ):
            return True
    return False


def _has_active_warmog(loadout: ResolvedLoadout) -> bool:
    """Whether a roster loadout can arm Warmog's combat regen gate."""
    if not any(
        str(item.get("name", "")) == "Warmog's Armor" for item in loadout.item_data
    ):
        return False
    try:
        threshold = sustain_effect_value(
            "Warmog's Armor", "heart_bonus_health_threshold"
        )
    except (KeyError, TypeError, ValueError):
        return True
    return float(loadout.stats.get("bonus_health", 0.0)) >= threshold


def _is_authored_ability_event(event: Mapping[str, Any]) -> bool:
    """Identify a champion cast without treating passive/proc rows as casts.

    Champion modules use the canonical Q/W/E/R source keys for cast packets.
    A packet may override this marker when a future source-backed mechanic
    supplies a more precise cast classification; absent that receipt, item
    procs and passive rows remain eligible to land normally.
    """
    if "is_ability" in event:
        return bool(event["is_ability"])
    return str(event.get("source_key", "")) in {"Q", "W", "E", "R"}


def _ability_instance_for_event(
    event: Mapping[str, Any], cast_timeline: Iterable[Mapping[str, Any]]
) -> str | None:
    """Attach a cast ordinal so multi-packet abilities share one shield use."""
    if not _is_authored_ability_event(event):
        return None
    slot = str(event.get("source_key", ""))
    try:
        event_time = float(event.get("time", 0.0))
    except (TypeError, ValueError):
        return None
    candidates = [
        cast
        for cast in cast_timeline
        if str(cast.get("slot", "")) == slot
        and float(cast.get("time", 0.0)) <= event_time
    ]
    if not candidates:
        return f"{slot}:{round(event_time, 9)}"
    cast = max(candidates, key=lambda row: float(row.get("time", 0.0)))
    ordinal = cast.get("ordinal")
    return (
        f"{slot}:{ordinal}"
        if ordinal is not None
        else f"{slot}:{round(float(cast.get('time', 0.0)), 9)}"
    )


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
    cast_timeline = result.get("cast_timeline", [])
    if not isinstance(cast_timeline, list):
        cast_timeline = []
    event_ids_by_key: dict[tuple[str, float, int], str] = {}
    event_ids_by_source_time: dict[tuple[str, float], list[str]] = defaultdict(list)
    result_breakdown = result.get("breakdown", {})
    if not isinstance(result_breakdown, Mapping):
        result_breakdown = {}
    for index, event in enumerate(result.get("damage_events", [])):
        if "sequence" not in event:
            # See _action_key: pair-local event ids stay order-irrelevant
            # only while every engine event carries its per-fight sequence.
            raise ValueError(
                f"{attacker_id} damage event {event.get('source_key', '')!r} "
                "has no sequence; the walk's tie-break order would depend on "
                "event-id numbering"
            )
        enriched = {
            **event,
            "attacker": attacker_id,
            "target": defender_id,
            "_event_id": f"{attacker_id}:{defender_id}:{index}",
            "is_ability": _is_authored_ability_event(event),
            "ability_instance": _ability_instance_for_event(event, cast_timeline),
        }
        # Multi-target rows are authored on the engine breakdown. Carry the
        # same target-allocation receipt onto each ordered packet so the
        # coupled timeline can prove which roster slot received it instead of
        # displaying an unexplained aggregate secondary hit.
        source_row = result_breakdown.get(str(event.get("source_key", "")), {})
        if isinstance(source_row, Mapping) and isinstance(
            source_row.get("targeting"), Mapping
        ):
            enriched["targeting"] = dict(source_row["targeting"])
        # The engine exposes the final effective resistances for this pair.
        # Preserve them on every packet so an ordered target state can re-price
        # the same post-mitigation event after adding its sourced resistance
        # delta.  A missing value is deliberately left absent: the survival
        # walk then refuses to invent a mitigation ratio for that packet.
        for field in ("effective_armor", "effective_mr"):
            try:
                baseline = float(result[field])
            except (KeyError, TypeError, ValueError):
                continue
            if math.isfinite(baseline):
                enriched[f"_baseline_{field}"] = baseline
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
        event_ids_by_source_time[
            (str(event.get("source_key", "")), round(float(event.get("time", 0.0)), 9))
        ].append(enriched["_event_id"])
    heals: list[dict[str, Any]] = []
    for heal_index, event in enumerate(result.get("self_healing_events", [])):
        original_event_id = event.get("_event_id")
        if original_event_id is None:
            original_event_id = f"{attacker_id}:heal:{heal_index}"
        # Engine self-heal ids are local to one pair fight.  Include the
        # defender in the coupled id so a multi-target defender packet cannot
        # publish duplicate receipts for the same attacker/timestamp.
        enriched_heal = {
            **event,
            "attacker": attacker_id,
            "_event_id": f"{original_event_id}:{defender_id}",
        }
        trigger_id = event_ids_by_key.get(
            (
                str(event.get("_trigger_source", "")),
                round(float(event.get("_trigger_time", 0.0)), 9),
                int(event.get("_trigger_sequence", 0) or 0),
            )
        )
        if trigger_id is not None:
            enriched_heal["_trigger_event_id"] = trigger_id
        else:
            trigger_candidates = event_ids_by_source_time.get(
                (
                    str(event.get("_trigger_source", "")),
                    round(float(event.get("_trigger_time", 0.0)), 9),
                ),
                [],
            )
            if len(trigger_candidates) == 1:
                enriched_heal["_trigger_event_id"] = trigger_candidates[0]
        # Triggered self-heals are authored by this attacker/defender pair.
        # Keep the damage target explicit in the public receipt: the heal's
        # ``attacker`` is its recipient, while ``trigger_target`` identifies
        # which roster target generated the life-steal/on-hit packet.  Do not
        # add this to actor-wide regeneration, whose copies are intentionally
        # deduplicated across pair fights.
        if "_trigger_source" in event:
            enriched_heal["trigger_target"] = defender_id
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
            source: {
                "name": entry.get("name", source),
                "total_damage": 0.0,
                **(
                    {"targeting": dict(entry["targeting"])}
                    if isinstance(entry.get("targeting"), Mapping)
                    else {}
                ),
            }
            for source, entry in result_breakdown.items()
            if isinstance(entry, Mapping)
        },
    }


def _actor_params(base: FightParams, actor: Combatant) -> FightParams:
    """Use a roster actor's role while preserving the selected fight window."""
    request = actor.request
    return replace(
        base,
        role=getattr(request, "role", "") or "",
        role_quest_complete=bool(getattr(request, "role_quest_complete", False)),
        # Roster controls are explicit scenario inputs.  An omitted cast order
        # must remain None so the actor's champion module supplies its own
        # declared order; only the synthetic main request carries the
        # top-level order.
        ability_ranks=getattr(request, "ability_ranks", None) or None,
        champion_options=getattr(request, "champion_options", None),
        cast_order=getattr(request, "cast_order", None),
        item_options=getattr(request, "item_options", None),
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
    target_scope = effect.get("target_scope")
    if target_scope == "self":
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
        if target_scope in {"self_and_all_teammates", "self_and_one_teammate"}:
            return [attacker.participant_id], "self_only_no_selected_teammate"
        if effect.get("target_self"):
            return [attacker.participant_id], "self"
        return [], "no_selected_teammate"
    if target_scope == "self_and_all_teammates":
        return [
            attacker.participant_id,
            *(actor.participant_id for actor in teammates),
        ], "self_and_all_selected_teammates"
    if target_scope == "self_and_one_teammate":
        return [
            attacker.participant_id,
            teammates[0].participant_id,
        ], "self_and_first_selected_teammate"
    if target_scope == "all_teammates":
        return [actor.participant_id for actor in teammates], "all_selected_teammates"
    return [teammates[0].participant_id], "first_selected_teammate"


def _support_effect_templates(
    attacker: Combatant,
    result: Mapping[str, Any],
    all_actors: list[Combatant],
    *,
    damage_events: Iterable[Mapping[str, Any]] | None = None,
    target_id: str | None = None,
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
    for effect_index, effect in enumerate(effects):
        target_ids, target_policy = _support_target_ids(attacker, effect, all_actors)
        for target_index, target_id in enumerate(target_ids):
            templates.append(
                {
                    **effect,
                    "attacker": attacker.participant_id,
                    "target": target_id,
                    "target_policy": target_policy,
                    "_event_id": str(
                        effect.get(
                            "_event_id",
                            f"{attacker.participant_id}:support:{effect_index}:{target_index}",
                        )
                    ),
                }
            )
    item_result = dict(result)
    if damage_events is not None:
        item_result["damage_events"] = list(damage_events)
        if (
            target_id
            and float(result.get("target_ending_health", 1.0) or 0.0) <= 0.0
            and item_result["damage_events"]
        ):
            kill_time = max(
                float(event.get("time", 0.0) or 0.0)
                for event in item_result["damage_events"]
                if isinstance(event, Mapping)
            )
            item_result["takedown_events"] = [
                {
                    "time": kill_time,
                    "target": target_id,
                    "attacker": attacker.participant_id,
                }
            ]
    templates.extend(
        derive_item_support_effects(
            attacker,
            item_result,
            all_actors,
            trigger_effects=templates,
        )
    )
    return templates


def _attach_support_effects(
    attacker: Combatant,
    result: Mapping[str, Any],
    all_actors: list[Combatant],
    support_effects: dict[str, list[dict[str, Any]]],
    outgoing: dict[str, list[dict[str, Any]]] | None = None,
    incoming: dict[str, list[dict[str, Any]]] | None = None,
) -> None:
    """Attach one actor's sourced shield/heal packets exactly once."""
    for template in _support_effect_templates(attacker, result, all_actors):
        packet = dict(template)
        support_effects[template["target"]].append(packet)
        if (
            template.get("kind") == "damage"
            and outgoing is not None
            and incoming is not None
        ):
            outgoing[template["attacker"]].append(packet)
            incoming[template["target"]].append(packet)


def _utility_outcome_receipt(
    actor: Combatant,
    support_events: Iterable[Mapping[str, Any]],
    outgoing_events: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Summarise authored non-TDD outcomes without inventing a conversion.

    Movement and cleanse are real event dimensions, but their units are not
    interchangeable with healing, shielding, or damage.  Keep them as
    separate receipts so the Utility objective can expose what was applied
    while refusing to turn a percent/second or a cleanse count into a made-up
    scalar score.  Item dimensions are sourced from the same full-entry
    coverage table used by the API picker.
    """
    support = [
        event
        for event in support_events
        if event.get("kind") != "damage"
        if float(event.get("applied_amount", event.get("amount", 0.0)) or 0.0) > 0.0
    ]
    movement = [event for event in support if event.get("kind") == "movement"]
    cleanse = [event for event in support if event.get("kind") == "cleanse"]
    slow = [event for event in support if event.get("kind") == "slow"]
    movement_speed_percent_seconds = sum(
        abs(
            float(
                event.get("bonus_move_speed_percent", event.get("amount", 0.0)) or 0.0
            )
        )
        * max(0.0, float(event.get("duration", 0.0) or 0.0))
        for event in movement
    )
    slow_percent_seconds = sum(
        abs(float(event.get("slow_percent", event.get("amount", 0.0)) or 0.0))
        * max(0.0, float(event.get("duration", 0.0) or 0.0))
        for event in slow
    )
    targeting = [
        event.get("targeting")
        for event in outgoing_events
        if isinstance(event.get("targeting"), Mapping)
    ]
    secondary = [
        row
        for row in targeting
        if str(row.get("kind", ""))
        in {
            "active_secondary",
            "chain_lightning",
            "chain_lightning_copied_on_hit",
            "cleave_secondary",
            "hydra_cleave",
            "runaan_bolt",
            "runaan_bolt_copied_on_hit",
        }
    ]
    coverage = [item_model_coverage(item) for item in actor.items]
    dimensions = sorted(
        {
            str(dimension)
            for entry in coverage
            for dimension in entry.get("outcome_dimensions", [])
        }
    )
    applied_dimensions = set()
    if movement:
        applied_dimensions.add("movement")
    if cleanse:
        applied_dimensions.add("cleanse")
    if slow:
        applied_dimensions.add("slow")
    if secondary:
        applied_dimensions.add("multi_target")
    return {
        "contract": "utility_outcomes_v1",
        "dimensions": dimensions,
        "applied_dimensions": sorted(applied_dimensions),
        "movement": {
            "event_count": len(movement),
            "speed_percent_seconds": round(movement_speed_percent_seconds, 6),
        },
        "cleanse": {"event_count": len(cleanse)},
        "slow": {
            "event_count": len(slow),
            "percent_seconds": round(slow_percent_seconds, 6),
        },
        "multi_target": {
            "packet_count": len(secondary),
            "allocated_packet_count": sum(
                1 for row in secondary if row.get("allocated_target_index") is not None
            ),
        },
        "scored_support_amount": round(
            sum(float(event.get("applied_amount", 0.0) or 0.0) for event in support),
            6,
        ),
        "item_coverage": [
            {
                "name": entry.get("name", ""),
                "status": entry.get("status", ""),
                "dimensions": list(entry.get("outcome_dimensions", [])),
                "reason": entry.get("reason", ""),
            }
            for entry in coverage
            if entry.get("outcome_dimensions")
        ],
        "metric_note": (
            "Movement and cleanse remain separate units; no cross-unit utility "
            "score is inferred. Healing, shielding, and applied support amounts "
            "remain event-derived values."
        ),
    }


def _target_allocation_receipt(
    public_events: Iterable[Mapping[str, Any]],
    target_count: int,
    breakdown_rows: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Prove roster allocation for every authored secondary-target packet."""
    rows = [
        event.get("targeting")
        for event in public_events
        if isinstance(event.get("targeting"), Mapping)
    ]
    rows.extend(
        row.get("targeting")
        for row in breakdown_rows
        if isinstance(row.get("targeting"), Mapping)
    )
    for row in breakdown_rows:
        sources = row.get("sources")
        if not isinstance(sources, list):
            continue
        rows.extend(
            source.get("targeting")
            for source in sources
            if isinstance(source, Mapping)
            and isinstance(source.get("targeting"), Mapping)
        )
    secondary = [
        row
        for row in rows
        if str(row.get("kind", ""))
        in {
            "active_secondary",
            "chain_lightning",
            "chain_lightning_copied_on_hit",
            "cleave_secondary",
            "hydra_cleave",
            "runaan_bolt",
            "runaan_bolt_copied_on_hit",
        }
    ]
    missing = [row for row in secondary if row.get("allocated_target_index") is None]
    return {
        "contract": "ordered_roster_target_allocation_v1",
        "target_count": max(0, int(target_count)),
        "secondary_packet_count": len(secondary),
        "allocated_secondary_packet_count": len(secondary) - len(missing),
        "complete": not missing,
        "policy": "roster_index_from_engine_targeting" if secondary else "none",
        "unallocated_reasons": (
            ["secondary packet is missing allocated_target_index"] if missing else []
        ),
    }


def _has_ordered_item_team_effects(
    items: Iterable[Mapping[str, Any]],
    enemies: Iterable[ResolvedLoadout] = (),
    allies: Iterable[ResolvedLoadout] = (),
) -> bool:
    """Return whether any participant needs the full item-team event walk."""
    if has_ordered_item_team_effects(items):
        return True
    return any(
        has_ordered_item_team_effects(loadout.item_data)
        for loadout in (*enemies, *allies)
    )


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
    # Bramble's fixed packet keeps a zero ratio.  Thornmail supplies an
    # authored bonus-armor ratio through ``ThornsEffect``; read it through a
    # compatibility default so cached Bramble packets remain unchanged while
    # the item layer rolls out the typed field.
    bonus_armor_ratio = max(
        0.0, float(getattr(profile, "bonus_armor_ratio", 0.0) or 0.0)
    )
    bonus_armor = max(0.0, float(wearer.stats.get("bonus_armor", 0.0) or 0.0))
    raw_damage = float(profile.damage) + bonus_armor_ratio * bonus_armor
    resistance = apply_magic_penetration(
        float(striker.stats.get("magic_resistance", 0.0)),
        float(wearer.stats.get("magic_penetration_flat", 0.0)),
        float(wearer.stats.get("magic_penetration_percent", 0.0)) / 100.0,
    )
    return apply_resistance(raw_damage, resistance)


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
            or bool(event.get("basic_attack"))
            if not any(
                bool(event.get(marker))
                for marker in (
                    "dodged",
                    "blocked",
                    "missed",
                    "blinded",
                    "blind",
                    "evaded",
                    "attack_missed",
                )
            )
            and str(event.get("skipped_reason", ""))
            not in {"dodged", "blocked", "missed", "blinded", "evaded"}
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
                    "_wound_until": float(strike.get("time", 0.0))
                    + float(profile.grievous_duration),
                }
                incoming.setdefault(striker.participant_id, []).append(event)
                outgoing.setdefault(wearer.participant_id, []).append(event)


def _schedule_authored_reactive_events(
    incoming: dict[str, list[dict[str, Any]]],
    outgoing: dict[str, list[dict[str, Any]]],
) -> None:
    """Schedule explicitly authored reactive packets on ledger events.

    A packet is accepted only when the trigger event names its eligible
    ``reactive_trigger`` (for example ``basic_attack``).  The resolver never
    infers an item's trigger, amount, target, or timing from a name.  This
    keeps Thornmail/redirect/defender packets source-owned while allowing the
    shared survival walk to apply their damage and Grievous window in order.
    """
    known_ids = {str(participant_id) for participant_id in incoming}
    for entries in incoming.values():
        known_ids.update(
            str(event.get("attacker", "")) for event in entries if event.get("attacker")
        )
        known_ids.update(
            str(event.get("target", "")) for event in entries if event.get("target")
        )
    for target_id, events in list(incoming.items()):
        for trigger in list(events):
            packets = trigger.get("reactive_packets")
            if not isinstance(packets, list):
                continue
            trigger_kind = str(trigger.get("trigger_kind", ""))
            trigger_id = trigger.get("_event_id")
            for index, packet in enumerate(packets):
                if not isinstance(packet, Mapping):
                    continue
                eligible = packet.get("reactive_trigger")
                if not isinstance(eligible, str) or eligible != trigger_kind:
                    continue
                target = str(packet.get("target", trigger.get("attacker", "")))
                if not target or target not in known_ids:
                    continue
                try:
                    amount = max(0.0, float(packet["damage"]))
                except (KeyError, TypeError, ValueError):
                    continue
                event = {
                    "time": float(packet.get("time", trigger.get("time", 0.0))),
                    "damage": amount,
                    "damage_type": str(packet.get("damage_type", "")),
                    "source_key": str(packet.get("source_key", "")),
                    "source": str(packet.get("source", packet.get("source_key", ""))),
                    "attacker": str(packet.get("attacker", target_id)),
                    "target": target,
                    "sequence": int(trigger.get("sequence", 0) or 0),
                    "event_precision": packet.get("event_precision", "exact"),
                    "_event_id": f"{trigger_id}:reactive:{index}",
                    "_trigger_event_id": trigger_id,
                    "_reactive": True,
                }
                if packet.get("grievous_duration") is not None:
                    event["grievous_duration"] = float(packet["grievous_duration"])
                    event["_wound_source"] = str(
                        packet.get("wound_source", event["source"])
                    )
                    event["_wound_until"] = event["time"] + event["grievous_duration"]
                incoming.setdefault(target, []).append(event)
                outgoing.setdefault(event["attacker"], []).append(event)


def _simulate_survival(
    combatants: Iterable[Combatant],
    incoming: Mapping[str, list[dict[str, Any]]],
    healing: Mapping[str, list[dict[str, Any]]],
    support_effects: Mapping[str, list[dict[str, Any]]],
    duration: float,
    annotate: bool = True,
    receipt_events: MutableMapping[str, list[dict[str, Any]]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Resolve damage, shields, healing, and death for every participant.

    ``annotate=False`` skips the per-event diagnostic fields that only the
    serialized public receipt reads (pair/live damage, overkill, healing
    receipts); every survival number and every field the breakdown sums —
    including each event's applied ``damage`` — is written either way.
    ``receipt_events`` is an optional outgoing ledger used only by receipt
    callers; when supplied, stateful redirect/deferred clones are mirrored
    beside their source packet without changing score-only inputs.
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
        defenses = combatant.defenses
        starting_stasis_duration = max(
            0.0, float(getattr(defenses, "starting_stasis_duration", 0.0) or 0.0)
        )
        base_armor = max(0.0, float(combatant.stats.get("armor", 0.0) or 0.0))
        base_magic_resistance = max(
            0.0, float(combatant.stats.get("magic_resistance", 0.0) or 0.0)
        )
        states[combatant.participant_id] = {
            "health": max(0.0, float(combatant.stats.get("health", 0.0))),
            "max_health": max(0.0, float(combatant.stats.get("health", 0.0))),
            "shields": _participant_defenses(combatant.defenses),
            "starting_shield": sum(_participant_defenses(combatant.defenses).values()),
            "damage_taken": 0.0,
            "overkill": 0.0,
            "health_damage": 0.0,
            "shield_absorbed": 0.0,
            # Combat regeneration is gated against the last sourced damage
            # timestamp.  The fight starts in combat, so a Warmog packet at
            # t=0 cannot immediately claim an unknown pre-fight idle window.
            "last_damage_time": 0.0,
            "healing_received": 0.0,
            "overhealing": 0.0,
            "healing_reduced": 0.0,
            "support_shield_received": 0.0,
            "support_shield_expired": 0.0,
            # Cross-participant item packets are kept as explicit live state
            # rather than folded into a starting stat guess.  The receipt
            # records each activation and the damage walk consumes only the
            # still-active entries.
            "support_buffs": [],
            "active_damage_modifiers": [],
            "active_on_hit_magic": [],
            "utility_effects": [],
            "timed_shields": [],
            "temporary_health_received": 0.0,
            "temporary_health_amount": 0.0,
            "temporary_health_until": 0.0,
            "temporary_health_expired_at": None,
            "temporary_health_source": "",
            "healing_reduction_until": 0.0,
            "healing_reduction_factor": 1.0,
            "healing_reduction_sources": set(),
            "healing_reduction_events": [],
            "death_time": None,
            "execute_time": None,
            "execute_source": "",
            # Combat-state mechanics are event-driven.  These fields are
            # deliberately inert unless an authored event supplies the
            # corresponding duration/transition; the simulator never
            # guesses an item's trigger or timing from a name alone.
            "stasis_until": starting_stasis_duration,
            "stasis_started_at": 0.0 if starting_stasis_duration > 0.0 else None,
            "stasis_source": str(getattr(defenses, "starting_stasis_source", "") or ""),
            "invulnerable_until": 0.0,
            "untargetable_until": 0.0,
            "spell_shield_until": (
                float("inf")
                if bool(getattr(defenses, "spell_shield_ready", False))
                else 0.0
            ),
            "spell_shield_source": str(
                getattr(defenses, "spell_shield_source", "") or ""
            ),
            "spell_shield_used": False,
            "spell_shield_blocked_cast": None,
            "ichorshield_cap": max(
                0.0,
                float(getattr(defenses, "bloodthirster_shield_cap", 0.0) or 0.0),
            ),
            "ichorshield_current": max(
                0.0,
                float(getattr(defenses, "bloodthirster_starting_shield", 0.0) or 0.0),
            ),
            "reactive_shield_amount": max(
                0.0, float(getattr(defenses, "reactive_shield_amount", 0.0) or 0.0)
            ),
            "reactive_shield_damage_type": str(
                getattr(defenses, "reactive_shield_damage_type", "") or ""
            ),
            "reactive_shield_duration": max(
                0.0, float(getattr(defenses, "reactive_shield_duration", 0.0) or 0.0)
            ),
            "reactive_shield_cooldown": max(
                0.0, float(getattr(defenses, "reactive_shield_cooldown", 0.0) or 0.0)
            ),
            "reactive_shield_source": str(
                getattr(defenses, "reactive_shield_source", "") or ""
            ),
            "reactive_shield_cooldown_until": 0.0,
            "incoming_damage_multiplier": max(
                0.0, float(getattr(defenses, "incoming_damage_multiplier", 1.0) or 1.0)
            ),
            "incoming_damage_linger": max(
                0.0, float(getattr(defenses, "incoming_damage_linger", 0.0) or 0.0)
            ),
            "incoming_damage_cooldown": max(
                0.0, float(getattr(defenses, "incoming_damage_cooldown", 0.0) or 0.0)
            ),
            "incoming_damage_source": str(
                getattr(defenses, "incoming_damage_source", "") or ""
            ),
            "incoming_damage_until": (
                float("inf")
                if float(getattr(defenses, "incoming_damage_multiplier", 1.0) or 1.0)
                < 1.0
                else 0.0
            ),
            "incoming_damage_cooldown_until": 0.0,
            "healing_received_multiplier": max(
                1.0,
                float(getattr(defenses, "healing_received_multiplier", 1.0) or 1.0),
            ),
            "threshold_shield": max(
                0.0, float(getattr(defenses, "threshold_shield_amount", 0.0) or 0.0)
            ),
            "threshold_shield_threshold": max(
                0.0,
                float(getattr(defenses, "threshold_shield_health_ratio", 0.0) or 0.0),
            )
            * max(0.0, float(combatant.stats.get("health", 0.0))),
            "threshold_shield_duration": max(
                0.0,
                float(getattr(defenses, "threshold_shield_duration", 0.0) or 0.0),
            ),
            "threshold_shield_damage_type": str(
                getattr(defenses, "threshold_shield_damage_type", "all") or "all"
            ),
            "threshold_shield_triggered": False,
            "threshold_shield_expired_at": None,
            "threshold_health_bonus": max(
                0.0, float(getattr(defenses, "threshold_health_bonus", 0.0) or 0.0)
            ),
            "threshold_health_heal": max(
                0.0, float(getattr(defenses, "threshold_health_heal", 0.0) or 0.0)
            ),
            "threshold_health_ratio": max(
                0.0, float(getattr(defenses, "threshold_health_ratio", 0.0) or 0.0)
            ),
            "threshold_health_duration": max(
                0.0, float(getattr(defenses, "threshold_health_duration", 0.0) or 0.0)
            ),
            "threshold_health_triggered": False,
            "first_death_time": None,
            "revive_time": None,
            "revive_source": "",
            "revive_health_restored": 0.0,
            "revived": False,
            "revive_used": False,
            "terminal_phase": "alive",
            "damage_deferral_pending": 0.0,
            "damage_deferral_cleared": 0.0,
            "deferred_batches": {},
            "cleared_deferred_batches": set(),
            "damage_records": [],
            "defy_triggered": False,
            "defy_trigger_time": None,
            "defy_heal_received": 0.0,
            "defy_triggered_damage_ids": set(),
            # Force of Nature and Jak'Sho are target-side combat states. Their
            # stack ledgers are kept per participant and begin at zero; the
            # ordered walk adds only source-backed resistance deltas.
            "force_stacks": 0,
            "force_stacks_until": 0.0,
            "force_last_stack_time": None,
            "force_last_cast_key": None,
            "force_stack_events": [],
            "jaksho_stacks": 0,
            "jaksho_stack_events": [],
            "base_armor": base_armor,
            "base_magic_resistance": base_magic_resistance,
            "bonus_armor": max(
                0.0, float(combatant.stats.get("bonus_armor", 0.0) or 0.0)
            ),
            "bonus_magic_resistance": max(
                0.0,
                float(combatant.stats.get("bonus_magic_resistance", 0.0) or 0.0),
            ),
        }

    # Normalize stateful packets before sorting.  Pair engines remain the
    # source of ordinary damage values; these transforms only consume
    # explicitly authored metadata on a packet and therefore fail closed
    # when a mechanic has no trigger/timing contract.
    expanded_incoming: dict[str, list[dict[str, Any]]] = defaultdict(list)
    expanded_healing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    redirect_children: dict[str, dict[str, Any]] = {}
    for participant_id, events in healing.items():
        expanded_healing[participant_id].extend(dict(event) for event in events)

    def _insert_receipt_clone(
        source_event: dict[str, Any], clone: dict[str, Any]
    ) -> None:
        """Insert a stateful clone beside its source in the outgoing receipt.

        ``incoming`` and ``outgoing`` share the same pair event objects in
        receipt mode.  The survival walk expands redirects/deferred ticks on
        the incoming side, so explicitly mirror those clones into the
        outgoing list for a complete public timeline.  Score-only callers do
        not pass ``receipt_events`` and retain the optimized event shape.
        """
        if receipt_events is None:
            return
        attacker = source_event.get("attacker")
        if attacker is None:
            return
        bucket = receipt_events.setdefault(str(attacker), [])
        try:
            index = bucket.index(source_event)
        except ValueError:
            bucket.append(clone)
            return
        # Keep multiple ticks in authored order, immediately following the
        # source packet, rather than appending them after unrelated attacks.
        while index + 1 < len(bucket):
            following = bucket[index + 1]
            source_id = str(source_event.get("_event_id", ""))
            following_id = str(following.get("_event_id", ""))
            if not source_id or not following_id.startswith(f"{source_id}:"):
                break
            index += 1
        bucket.insert(index + 1, clone)

    for participant_id, events in incoming.items():
        for original in events:
            event = original
            target_id = str(event.get("target", participant_id))
            try:
                redirect_fraction = float(event.get("redirect_fraction", 0.0) or 0.0)
            except (TypeError, ValueError):
                redirect_fraction = 0.0
            redirect_fraction = max(0.0, min(1.0, redirect_fraction))
            redirect_target = str(event.get("redirect_target", ""))
            if redirect_fraction > 0.0 and redirect_target in states:
                original_amount = max(0.0, float(event.get("damage", 0.0)))
                # Knight's Vow redirects pre-mitigation damage.  A pair event
                # may only expose its post-mitigation value, so recover the
                # authored raw amount from the event when present, otherwise
                # from its effective resistance receipt.  If neither exists,
                # fail closed instead of splitting a guessed post-mitigation
                # amount between targets with different resistances.
                raw_amount: float | None = None
                if event.get("redirect_pre_mitigation_required"):
                    try:
                        candidate = float(event.get("raw_damage", 0.0) or 0.0)
                    except (TypeError, ValueError):
                        candidate = 0.0
                    if candidate > 0.0 and math.isfinite(candidate):
                        raw_amount = candidate
                    else:
                        damage_type = str(event.get("damage_type", ""))
                        baseline_key = (
                            "_baseline_effective_armor"
                            if damage_type == "physical"
                            else (
                                "_baseline_effective_mr"
                                if damage_type == "magic"
                                else ""
                            )
                        )
                        try:
                            baseline = float(event[baseline_key])
                            baseline_factor = apply_resistance(1.0, baseline)
                            if baseline_factor <= 0.0 or not math.isfinite(
                                baseline_factor
                            ):
                                raise ValueError("invalid baseline mitigation factor")
                            raw_amount = original_amount / baseline_factor
                        except (KeyError, TypeError, ValueError, ZeroDivisionError):
                            raw_amount = None
                    if raw_amount is None or not math.isfinite(raw_amount):
                        event["redirect_skipped_reason"] = (
                            "pre_mitigation_receipt_unavailable"
                        )
                        event["redirect_fraction"] = 0.0
                        expanded_incoming[target_id].append(event)
                        continue

                    source = combatant_by_id.get(str(event.get("attacker", "")))
                    protected = combatant_by_id.get(target_id)
                    holder = combatant_by_id.get(redirect_target)
                    damage_type = str(event.get("damage_type", ""))
                    if source is None or protected is None or holder is None:
                        event["redirect_skipped_reason"] = (
                            "participant_receipt_unavailable"
                        )
                        event["redirect_fraction"] = 0.0
                        expanded_incoming[target_id].append(event)
                        continue

                    def _target_factor(target: Combatant) -> float | None:
                        if damage_type == "physical":
                            effective = apply_armor_penetration(
                                float(target.stats.get("armor", 0.0) or 0.0)
                                + float(
                                    states[target.participant_id].get(
                                        "dynamic_bonus_armor", 0.0
                                    )
                                    or 0.0
                                ),
                                float(
                                    source.stats.get("flat_armor_penetration", 0.0)
                                    or 0.0
                                ),
                                float(
                                    source.stats.get("armor_penetration_percent", 0.0)
                                    or 0.0
                                )
                                / 100.0,
                            )
                        elif damage_type == "magic":
                            effective = apply_magic_penetration(
                                float(target.stats.get("magic_resistance", 0.0) or 0.0)
                                + float(
                                    states[target.participant_id].get(
                                        "dynamic_bonus_magic_resistance", 0.0
                                    )
                                    or 0.0
                                ),
                                float(
                                    source.stats.get("magic_penetration_flat", 0.0)
                                    or 0.0
                                ),
                                float(
                                    source.stats.get("magic_penetration_percent", 0.0)
                                    or 0.0
                                )
                                / 100.0,
                            )
                        elif damage_type == "true":
                            return 1.0
                        else:
                            return None
                        factor = apply_resistance(1.0, effective)
                        if not math.isfinite(factor) or factor < 0.0:
                            return None
                        # Basic-damage defenses are post-mitigation and belong
                        # to the recipient of each split, not the Worthy.
                        if event.get("basic_attack") and damage_type != "true":
                            defenses = target.defenses
                            factor *= max(
                                0.0,
                                float(
                                    getattr(defenses, "basic_damage_multiplier", 1.0)
                                    or 1.0
                                ),
                            )
                            flat = max(
                                0.0,
                                float(
                                    getattr(
                                        defenses, "basic_damage_flat_reduction", 0.0
                                    )
                                    or 0.0
                                ),
                            )
                            cap = max(
                                0.0,
                                float(
                                    getattr(
                                        defenses,
                                        "basic_damage_flat_reduction_cap",
                                        0.0,
                                    )
                                    or 0.0
                                ),
                            )
                            if flat > 0.0 and cap > 0.0:
                                mitigated = raw_amount * factor
                                factor = max(
                                    0.0,
                                    (mitigated - min(flat, mitigated * cap))
                                    / raw_amount,
                                )
                        return factor

                    protected_factor = _target_factor(protected)
                    holder_factor = _target_factor(holder)
                    if protected_factor is None or holder_factor is None:
                        event["redirect_skipped_reason"] = (
                            "target_mitigation_receipt_unavailable"
                        )
                        event["redirect_fraction"] = 0.0
                        expanded_incoming[target_id].append(event)
                        continue
                    direct_amount = (
                        raw_amount * (1.0 - redirect_fraction) * protected_factor
                    )
                    redirected_amount = raw_amount * redirect_fraction * holder_factor
                else:
                    direct_amount = original_amount * (1.0 - redirect_fraction)
                    redirected_amount = original_amount * redirect_fraction
                redirected = {
                    **event,
                    "target": redirect_target,
                    "damage": redirected_amount,
                    "_redirected": True,
                    "_redirected_from": target_id,
                    "_redirect_fraction": redirect_fraction,
                    "_trigger_event_id": event.get("_event_id"),
                    "_event_id": f"{event.get('_event_id', '')}:redirect",
                }
                if event.get("redirect_pre_mitigation_required"):
                    redirected["raw_damage"] = raw_amount * redirect_fraction
                    redirected["redirect_pre_mitigation"] = True
                    redirected["redirect_attributed_to"] = str(
                        event.get("attacker", "")
                    )
                redirected["_sk"] = _action_key(
                    float(redirected.get("time", 0.0)),
                    0.5,
                    redirect_target,
                    redirected,
                )
                redirect_children[str(event.get("_event_id", ""))] = redirected
                expanded_incoming[redirect_target].append(redirected)
                _insert_receipt_clone(event, redirected)
                # The source packet's outgoing receipt represents the direct
                # share; the redirected clone carries the other share.  This
                # keeps public event damage additive without double counting.
                original["damage"] = direct_amount
                original["_redirect_original_damage"] = original_amount
                original["_redirected_amount"] = redirected_amount
                original["_redirect_fraction"] = redirect_fraction
                event = {
                    **event,
                    "target": target_id,
                    "damage": direct_amount,
                    "_redirect_original_damage": original_amount,
                    "_redirected_amount": redirected_amount,
                    "_redirect_fraction": redirect_fraction,
                }

            # Death's Dance receives post-mitigation physical and magic
            # packets.  Apply its typed defense metadata here, before the
            # shared split logic, so every authored source (abilities, autos,
            # item procs, and reactive packets) follows the same path.
            target_defenses = combatant_by_id.get(target_id)
            if (
                target_defenses is not None
                and not event.get("_deferred")
                and str(event.get("damage_type", "")) in {"physical", "magic"}
                and float(event.get("damage", 0.0) or 0.0) > 0.0
                and float(
                    getattr(target_defenses.defenses, "damage_deferral_fraction", 0.0)
                    or 0.0
                )
                > 0.0
                and "deferred_fraction" not in event
            ):
                event["deferred_fraction"] = float(
                    target_defenses.defenses.damage_deferral_fraction
                )
                event["deferred_duration"] = float(
                    target_defenses.defenses.damage_deferral_duration
                )
                event["deferred_ticks"] = int(
                    target_defenses.defenses.damage_deferral_ticks
                )

            # Deferred damage (for example a damage-deferral passive) is
            # represented only when the packet provides all timing fields.
            # It is split into deterministic equal true-damage ticks; no
            # hidden item-specific duration is introduced here.
            try:
                deferred_fraction = float(event.get("deferred_fraction", 0.0) or 0.0)
                deferred_duration = float(event.get("deferred_duration", 0.0) or 0.0)
                deferred_ticks = int(event.get("deferred_ticks", 0) or 0)
            except (TypeError, ValueError):
                deferred_fraction, deferred_duration, deferred_ticks = 0.0, 0.0, 0
            if (
                deferred_fraction > 0.0
                and deferred_duration > 0.0
                and deferred_ticks > 0
                and float(event.get("damage", 0.0)) > 0.0
            ):
                deferred_fraction = min(1.0, deferred_fraction)
                full_amount = float(event["damage"])
                immediate_amount = full_amount * (1.0 - deferred_fraction)
                if receipt_events is not None:
                    # Split the outgoing source event too; the deferred clones
                    # below then reconcile exactly to its original amount.
                    original["damage"] = immediate_amount
                    original["_deferred_total"] = full_amount * deferred_fraction
                event = {
                    **event,
                    "damage": immediate_amount,
                    "_deferred_total": full_amount * deferred_fraction,
                }
                tick_amount = full_amount * deferred_fraction / deferred_ticks
                batch_id = str(event.get("_event_id", ""))
                target_state = states[target_id]
                target_state["deferred_batches"][batch_id] = (
                    full_amount * deferred_fraction
                )
                target_state["damage_deferral_pending"] += (
                    full_amount * deferred_fraction
                )
                for tick in range(1, deferred_ticks + 1):
                    deferred = {
                        **event,
                        "time": float(event.get("time", 0.0))
                        + deferred_duration * tick / deferred_ticks,
                        "damage": tick_amount,
                        "damage_type": "true",
                        "source_key": f"deferred_{event.get('source_key', 'damage')}",
                        "source": f"{event.get('source', event.get('source_key', ''))} (deferred)",
                        "_event_id": f"{event.get('_event_id', '')}:deferred:{tick}",
                        "_deferred": True,
                        "_deferred_from": event.get("_event_id"),
                        "_deferred_batch_id": batch_id,
                    }
                    deferred["_sk"] = _action_key(
                        float(deferred.get("time", 0.0)),
                        0.0,
                        target_id,
                        deferred,
                    )
                    expanded_incoming[target_id].append(deferred)
                    _insert_receipt_clone(original, deferred)
            expanded_incoming[target_id].append(event)

    if isinstance(healing, MutableMapping):
        healing.clear()
        healing.update(expanded_healing)
    else:
        healing = expanded_healing

    # Guardian Angel's Rebirth is triggered by the first lethal packet, but
    # that trigger is only knowable during the live survival walk.  Author a
    # candidate revive after every incoming damage event; the walk applies the
    # earliest one only when the participant is actually dead, and ignores
    # the rest.  This preserves exact packet ordering without guessing which
    # packet becomes lethal before shields, overkill, or prior healing resolve.
    for participant_id, events in list(expanded_incoming.items()):
        defenses = combatant_by_id[participant_id].defenses
        revive_amount = max(
            0.0, float(getattr(defenses, "revive_health_amount", 0.0) or 0.0)
        )
        revive_delay = max(0.0, float(getattr(defenses, "revive_delay", 0.0) or 0.0))
        if revive_amount <= 0.0 or revive_delay <= 0.0:
            continue
        candidates: list[dict[str, Any]] = []
        for index, event in enumerate(events):
            if str(event.get("kind", "")) in {
                "heal",
                "regen",
                "shield",
                "temporary_health",
                "revive",
            }:
                continue
            damage = max(0.0, float(event.get("damage", 0.0) or 0.0))
            if damage <= 0.0:
                continue
            event_time = float(event.get("time", 0.0))
            candidates.append(
                {
                    "time": event_time + revive_delay,
                    "kind": "revive",
                    "amount": revive_amount,
                    "source": "Guardian Angel (Rebirth)",
                    "source_key": "revive_Guardian Angel",
                    "sequence": int(event.get("sequence", index) or index),
                    "_revive_candidate": True,
                }
            )
        expanded_incoming[participant_id].extend(candidates)
    incoming = expanded_incoming

    def _append_ordered_heal(participant_id: str, event: dict[str, Any]) -> None:
        """Add a sourced recovery event to the live healing mapping."""
        expanded_healing[participant_id].append(event)
        if isinstance(healing, MutableMapping):
            healing[participant_id] = expanded_healing[participant_id]

    # Warmog's Heart is a live combat-state gate.  Its amount is based on the
    # current maximum health at the moment each tick lands, while the
    # no-damage window is checked inside the ordered simulator against the
    # last applied incoming packet.  The 2,000 bonus-health threshold is
    # sourced from the item's full Wiki entry and is intentionally not
    # guessed for an unqualified loadout.
    for combatant in combatant_list:
        if not any(
            str(item.get("name", "")) == "Warmog's Armor" for item in combatant.items
        ):
            continue
        threshold = sustain_effect_value(
            "Warmog's Armor", "heart_bonus_health_threshold"
        )
        if float(combatant.stats.get("bonus_health", 0.0)) < threshold:
            continue
        ratio = sustain_effect_value(
            "Warmog's Armor", "heart_max_health_ratio_per_tick"
        )
        tick = sustain_effect_value("Warmog's Armor", "heart_tick_interval")
        gate = sustain_effect_value("Warmog's Armor", "heart_champion_damage_cooldown")
        if ratio <= 0.0 or tick <= 0.0:
            continue
        time_value = tick
        sequence = 0
        while time_value <= duration + 1e-9:
            _append_ordered_heal(
                combatant.participant_id,
                {
                    "time": round(time_value, 6),
                    "amount": 0.0,
                    "amount_formula": (
                        lambda _current_health, maximum_health, ratio=ratio: (
                            maximum_health * ratio
                        )
                    ),
                    "source": "Warmog's Armor (Warmog's Heart)",
                    "kind": "regen",
                    "actor_wide": True,
                    "requires_damage_free_seconds": gate,
                    "_event_id": f"{combatant.participant_id}:warmog:{sequence}",
                    "sequence": sequence,
                },
            )
            sequence += 1
            time_value += tick

    def _expire_timed_shields(state: dict[str, Any], event_time: float) -> None:
        """Remove unused timed shields before an event at their expiry."""
        remaining: list[dict[str, Any]] = []
        for shield in state["timed_shields"]:
            expires_at = float(shield.get("expires_at", 0.0) or 0.0)
            amount = max(0.0, float(shield.get("amount", 0.0) or 0.0))
            if expires_at <= event_time + 1e-9:
                if amount > 0.0:
                    shield_key = str(shield.get("shield_key", "general_shield"))
                    if shield_key not in state["shields"]:
                        shield_key = "general_shield"
                    state["shields"][shield_key] = max(
                        0.0, state["shields"][shield_key] - amount
                    )
                    state["support_shield_expired"] += amount
                continue
            remaining.append(shield)
        state["timed_shields"] = remaining

    def _consume_general_shield(state: dict[str, Any], amount: float) -> float:
        """Consume earliest-expiring timed shields before untimed general ones."""
        remaining = max(0.0, float(amount))
        absorbed = 0.0
        for shield in sorted(
            state["timed_shields"],
            key=lambda entry: float(entry.get("expires_at", float("inf"))),
        ):
            if str(shield.get("shield_key", "general_shield")) != "general_shield":
                continue
            available = max(0.0, float(shield.get("amount", 0.0) or 0.0))
            used = min(available, remaining)
            if used <= 0.0:
                continue
            shield["amount"] = available - used
            remaining -= used
            absorbed += used
            state["shields"]["general_shield"] = max(
                0.0, state["shields"]["general_shield"] - used
            )
            if remaining <= 1e-9:
                break
        if remaining > 0.0:
            used = min(state["shields"]["general_shield"], remaining)
            state["shields"]["general_shield"] -= used
            absorbed += used
        state["timed_shields"] = [
            shield
            for shield in state["timed_shields"]
            if float(shield.get("amount", 0.0) or 0.0) > 1e-9
        ]
        return absorbed

    def _consume_typed_shield(
        state: dict[str, Any], shield_key: str, amount: float
    ) -> float:
        """Consume a typed timed shield before the untimed typed pool."""
        remaining = max(0.0, float(amount))
        absorbed = 0.0
        for shield in sorted(
            state["timed_shields"],
            key=lambda entry: float(entry.get("expires_at", float("inf"))),
        ):
            if str(shield.get("shield_key", "general_shield")) != shield_key:
                continue
            available = max(0.0, float(shield.get("amount", 0.0) or 0.0))
            used = min(available, remaining)
            if used <= 0.0:
                continue
            shield["amount"] = available - used
            remaining -= used
            absorbed += used
            state["shields"][shield_key] = max(0.0, state["shields"][shield_key] - used)
            if remaining <= 1e-9:
                break
        if remaining > 0.0:
            used = min(state["shields"][shield_key], remaining)
            state["shields"][shield_key] -= used
            absorbed += used
        state["timed_shields"] = [
            shield
            for shield in state["timed_shields"]
            if float(shield.get("amount", 0.0) or 0.0) > 1e-9
        ]
        return absorbed

    current_action_index = -1

    def _trigger_defy(target_id: str, event_time: float) -> None:
        """Trigger Defy for every allied holder that recently damaged target."""
        target = combatant_by_id.get(target_id)
        if target is None:
            return
        for holder_id, holder in combatant_by_id.items():
            holder_state = states[holder_id]
            if holder_id == target_id or holder.team == target.team:
                continue
            defenses = holder.defenses
            window = max(0.0, float(getattr(defenses, "defy_window", 0.0) or 0.0))
            if window <= 0.0 or holder_state["death_time"] is not None:
                continue
            matching = [
                record
                for record in holder_state["damage_records"]
                if record["target"] == target_id
                and event_time - record["time"] <= window + 1e-9
                and event_time >= record["time"] - 1e-9
            ]
            if not matching or holder_state["defy_triggered"]:
                continue
            holder_state["defy_triggered"] = True
            holder_state["defy_trigger_time"] = float(event_time)
            holder_state["defy_triggered_damage_ids"].update(
                record["event_id"] for record in matching
            )
            cleared = sum(holder_state["deferred_batches"].values())
            holder_state["damage_deferral_cleared"] += cleared
            holder_state["damage_deferral_pending"] = 0.0
            holder_state["cleared_deferred_batches"].update(
                holder_state["deferred_batches"]
            )
            holder_state["deferred_batches"].clear()
            duration_value = max(
                0.0, float(getattr(defenses, "defy_heal_duration", 0.0) or 0.0)
            )
            ticks = int(getattr(defenses, "defy_heal_ticks", 0) or 0)
            heal_ratio = max(
                0.0,
                float(getattr(defenses, "defy_heal_bonus_ad_ratio", 0.0) or 0.0),
            )
            bonus_ad = max(0.0, float(holder.stats.get("bonus_attack_damage", 0.0)))
            if (
                duration_value <= 0.0
                or ticks <= 0
                or heal_ratio <= 0.0
                or bonus_ad <= 0.0
            ):
                continue
            total_heal = bonus_ad * heal_ratio
            trigger_id = matching[-1]["event_id"]
            for tick in range(1, ticks + 1):
                heal_event = {
                    "time": float(event_time) + duration_value * tick / ticks,
                    "kind": "heal",
                    "amount": total_heal / ticks,
                    "source": "Death's Dance (Defy)",
                    "source_key": "heal_Death's Dance",
                    "attacker": holder_id,
                    "target": holder_id,
                    "_event_id": (
                        f"{holder_id}:defy:{target_id}:"
                        f"{round(float(event_time), 9)}:{tick}"
                    ),
                    "_defy_trigger_id": trigger_id,
                    "_defy_target_id": target_id,
                    "_defy_window": window,
                    "sequence": tick - 1,
                }
                expanded_healing[holder_id].append(heal_event)
                if isinstance(healing, MutableMapping):
                    healing[holder_id] = expanded_healing[holder_id]
                action = (
                    _action_key(
                        float(heal_event["time"]),
                        1.0,
                        holder_id,
                        heal_event,
                    ),
                    holder_id,
                    heal_event,
                )
                insertion = max(current_action_index + 1, 0)
                while insertion < len(actions) and actions[insertion][0] <= action[0]:
                    insertion += 1
                actions.insert(insertion, action)

    actions: list[tuple[tuple[Any, ...], str, dict[str, Any]]] = []
    damage_event_status: dict[str, str] = {}

    def _insert_live_heal(event: dict[str, Any], recipient_id: str) -> None:
        """Insert a recovery packet authored by a just-applied trigger."""
        event["_sk"] = _action_key(
            float(event.get("time", 0.0)),
            1.0,
            recipient_id,
            event,
        )
        action = (event["_sk"], recipient_id, event)
        insertion = max(current_action_index + 1, 0)
        while insertion < len(actions) and actions[insertion][0] <= action[0]:
            insertion += 1
        actions.insert(insertion, action)

    def _schedule_doran_shield_recovery(
        participant_id: str, event: Mapping[str, Any], event_time: float
    ) -> None:
        """Schedule Enduring Focus only after a certified incoming hit."""
        combatant = combatant_by_id.get(participant_id)
        if combatant is None or not any(
            str(item.get("name", "")) == "Doran's Shield" for item in combatant.items
        ):
            return
        if float(event.get("damage", 0.0) or 0.0) <= 0.0:
            return
        total_melee = sustain_effect_value(
            "Doran's Shield", "enduring_focus_total_melee"
        )
        total_reduced = sustain_effect_value(
            "Doran's Shield", "enduring_focus_total_reduced"
        )
        missing_cap = sustain_effect_value(
            "Doran's Shield", "enduring_focus_missing_health_cap"
        )
        duration_value = sustain_effect_value(
            "Doran's Shield", "enduring_focus_duration"
        )
        tick = sustain_effect_value("Doran's Shield", "health_regen_tick_interval")
        if missing_cap <= 0.0 or duration_value <= 0.0 or tick <= 0.0:
            return
        current_state = states[participant_id]
        missing_ratio = (
            max(0.0, 1.0 - current_state["health"] / current_state["max_health"])
            if current_state["max_health"] > 0.0
            else 0.0
        )
        if missing_ratio <= 0.0:
            return
        source_key = str(event.get("source_key", ""))
        is_basic_or_on_hit = (
            bool(event.get("basic_attack"))
            or source_key
            in {
                "auto_attacks",
            }
            or source_key.startswith(("on_hit_", "on_hit_once_"))
        )
        ranged = (
            str(combatant.champion_data.get("attackType", "MELEE")).upper() != "MELEE"
        )
        total_cap = total_reduced if ranged or not is_basic_or_on_hit else total_melee
        total = total_cap * min(1.0, missing_ratio / missing_cap)
        if total <= 0.0:
            return
        trigger_id = str(event.get("_event_id", ""))
        ticks = max(1, int(round(duration_value / tick)))
        for tick_index in range(1, ticks + 1):
            heal_event = {
                "time": round(event_time + tick * tick_index, 6),
                "amount": total / ticks,
                "source": "Doran's Shield (Enduring Focus)",
                "kind": "regen",
                "attacker": participant_id,
                "target": participant_id,
                "_event_id": f"{trigger_id}:doran-shield:{tick_index}",
                "_trigger_event_id": trigger_id,
                "sequence": tick_index - 1,
            }
            expanded_healing[participant_id].append(heal_event)
            _insert_live_heal(heal_event, participant_id)

    def _recovery_is_gated(
        state: Mapping[str, Any], event: Mapping[str, Any], event_time: float
    ) -> bool:
        """Return whether a combat-gated recovery must wait for idle time."""
        try:
            gate = max(
                0.0, float(event.get("requires_damage_free_seconds", 0.0) or 0.0)
            )
        except (TypeError, ValueError):
            gate = 0.0
        if gate <= 0.0:
            return False
        last_damage = state.get("last_damage_time")
        if last_damage is None:
            return False
        return event_time - float(last_damage) < gate - 1e-9

    def _recovery_multiplier(
        state: Mapping[str, Any], event: Mapping[str, Any]
    ) -> float:
        """Apply received-healing modifiers except to vamp stat packets."""
        if str(event.get("healing_category", "")) == "vamp":
            return 1.0
        return float(state["healing_received_multiplier"])

    def _apply_ichorshield(
        state: dict[str, Any], event: MutableMapping[str, Any], excess: float
    ) -> float:
        """Convert explicit lifesteal excess into Bloodthirster's shield."""
        if str(event.get("healing_category", "")) != "vamp":
            return 0.0
        capacity = max(0.0, state["ichorshield_cap"] - state["ichorshield_current"])
        converted = min(max(0.0, float(excess)), capacity)
        if converted <= 0.0:
            return 0.0
        state["ichorshield_current"] += converted
        state["shields"]["general_shield"] += converted
        state["support_shield_received"] += converted
        event["ichorshield_generated"] = round(converted, 6)
        event["ichorshield_total"] = round(state["ichorshield_current"], 6)
        return converted

    def _update_combat_state(
        participant_id: str, event: MutableMapping[str, Any], event_time: float
    ) -> None:
        """Advance sourced combat-state item stacks before one damage packet."""
        target_state = states[participant_id]
        source_id = str(event.get("attacker", ""))
        if source_id not in states or source_id == participant_id:
            return
        if event.get("_reactive") or event.get("_deferred"):
            return
        try:
            packet_damage = max(0.0, float(event.get("damage", 0.0) or 0.0))
        except (TypeError, ValueError):
            packet_damage = 0.0
        if packet_damage <= 0.0:
            return

        defenses = combatant_by_id[participant_id].defenses
        damage_type = str(event.get("damage_type", ""))

        # Jak'Sho is combat-time state: one stack per second, capped at the
        # sourced maximum. It multiplies bonus resistances only at cap.
        jak_interval = max(
            0.0, float(getattr(defenses, "jaksho_stack_interval", 0.0) or 0.0)
        )
        jak_max = max(0, int(getattr(defenses, "jaksho_max_stacks", 0) or 0))
        if jak_interval > 0.0 and jak_max > 0:
            stacks = min(jak_max, max(0, int(math.floor(event_time / jak_interval))))
            if stacks != target_state["jaksho_stacks"]:
                target_state["jaksho_stacks"] = stacks
                target_state["jaksho_stack_events"].append(
                    {"time": round(event_time, 6), "stacks": stacks}
                )
                event["jaksho_stacks"] = stacks

        # Force of Nature counts incoming champion magic-damage cast instances.
        # The packet may carry an immobilisation marker from a reviewed module;
        # absent that marker we do not guess the two-stack branch.
        force_interval = max(
            0.0, float(getattr(defenses, "force_stack_interval", 0.0) or 0.0)
        )
        force_duration = max(
            0.0, float(getattr(defenses, "force_stack_duration", 0.0) or 0.0)
        )
        force_max = max(0, int(getattr(defenses, "force_max_stacks", 0) or 0))
        if damage_type == "magic" and force_interval > 0.0 and force_max > 0:
            last_time = target_state["force_last_stack_time"]
            if (
                last_time is not None
                and force_duration > 0.0
                and event_time - float(last_time) >= force_duration
            ):
                target_state["force_stacks"] = 0
                target_state["force_last_stack_time"] = None
                target_state["force_last_cast_key"] = None
            cast_key = str(
                event.get("ability_instance")
                or f"{event.get('source_key', '')}:{event.get('sequence', '')}"
            )
            same_cast = cast_key == target_state["force_last_cast_key"]
            elapsed = (
                float("inf")
                if target_state["force_last_stack_time"] is None
                else event_time - float(target_state["force_last_stack_time"])
            )
            if not same_cast and elapsed + 1e-9 >= force_interval:
                immobilized = bool(
                    event.get("immobilized")
                    or event.get("crowd_control")
                    or event.get("hard_cc")
                    or str(event.get("cc_kind", "")).lower()
                    in {"immobilize", "stun", "root", "knockup", "suppression"}
                )
                increment = (
                    max(1, int(getattr(defenses, "force_immobilize_stacks", 0) or 0))
                    if immobilized
                    else 1
                )
                target_state["force_stacks"] = min(
                    force_max, target_state["force_stacks"] + increment
                )
                target_state["force_last_stack_time"] = event_time
                target_state["force_last_cast_key"] = cast_key
                target_state["force_stacks_until"] = event_time + force_duration
                target_state["force_stack_events"].append(
                    {
                        "time": round(event_time, 6),
                        "stacks": target_state["force_stacks"],
                        "immobilized": immobilized,
                        "cast": cast_key,
                    }
                )
                event["force_stacks"] = target_state["force_stacks"]

        target_state["dynamic_bonus_armor"] = 0.0
        target_state["dynamic_bonus_magic_resistance"] = 0.0
        if (
            jak_max > 0
            and target_state["jaksho_stacks"] >= jak_max
            and float(
                getattr(defenses, "jaksho_bonus_resistance_multiplier", 0.0) or 0.0
            )
            > 0.0
        ):
            multiplier = float(defenses.jaksho_bonus_resistance_multiplier)
            target_state["dynamic_bonus_armor"] += (
                target_state["bonus_armor"] * multiplier
            )
            target_state["dynamic_bonus_magic_resistance"] += (
                target_state["bonus_magic_resistance"] * multiplier
            )
        if (
            force_max > 0
            and target_state["force_stacks"] >= force_max
            and float(getattr(defenses, "force_bonus_magic_resistance", 0.0) or 0.0)
            > 0.0
        ):
            target_state["dynamic_bonus_magic_resistance"] += float(
                defenses.force_bonus_magic_resistance
            )

    def _reprice_dynamic_resistance(
        participant_id: str,
        event: MutableMapping[str, Any],
    ) -> None:
        """Apply an armed target resistance delta to one post-mitigation packet."""
        target_state = states[participant_id]
        damage_type = str(event.get("damage_type", ""))
        if damage_type == "physical":
            delta = float(target_state.get("dynamic_bonus_armor", 0.0) or 0.0)
            field = "_baseline_effective_armor"
            label = "armor"
        elif damage_type == "magic":
            delta = float(
                target_state.get("dynamic_bonus_magic_resistance", 0.0) or 0.0
            )
            field = "_baseline_effective_mr"
            label = "magic_resistance"
        else:
            return
        if delta <= 0.0:
            return
        try:
            baseline = float(event[field])
        except (KeyError, TypeError, ValueError):
            # A source that did not expose an effective resistance is not
            # silently repriced; the packet remains visible and the receipt
            # explains why its dynamic state was unavailable.
            event["dynamic_resistance_unavailable"] = label
            return
        baseline_factor = apply_resistance(1.0, baseline)
        dynamic_factor = apply_resistance(1.0, baseline + delta)
        if not math.isfinite(baseline_factor) or baseline_factor <= 0.0:
            event["dynamic_resistance_unavailable"] = label
            return
        amount = max(0.0, float(event.get("damage", 0.0) or 0.0))
        event["damage"] = amount * dynamic_factor / baseline_factor
        event["dynamic_resistance"] = {
            "type": label,
            "baseline_effective": round(baseline, 6),
            "delta": round(delta, 6),
            "effective": round(baseline + delta, 6),
            "factor": round(dynamic_factor / baseline_factor, 6),
        }

    for participant_id, events in support_effects.items():
        for support_index, event in enumerate(events):
            event.setdefault("_event_id", f"{participant_id}:support:{support_index}")
            if event.get("kind") == "damage":
                # Damage packets are mirrored into the normal incoming/outgoing
                # ledgers below. Keep the support copy for the public receipt,
                # but do not schedule the same object a second time here.
                continue
            # A sourced ally shield is a pre-damage barrier.  A sourced heal
            # is a post-damage recovery event.  They must not share one
            # priority merely because both are support effects.
            kind = str(event.get("kind", ""))
            priority = (
                float(event.get("_priority", 0.0))
                if "_priority" in event
                else (
                    -2.0
                    if kind
                    in {"stasis", "invulnerability", "untargetable", "spell_shield"}
                    else (-1.0 if kind in {"shield", "temporary_health"} else 1.0)
                )
            )
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

    action_index = 0
    while action_index < len(actions):
        current_action_index = action_index
        action_key, participant_id, event = actions[action_index]
        action_index += 1
        event_time, phase = action_key[0], action_key[1]
        state = states[participant_id]
        trigger_id = event.get("_trigger_event_id")

        if event_time > duration:
            # The shared ledger is bounded by the authored fight window.  A
            # post-window revive, heal, or damage tick must remain visible in
            # the receipt but cannot alter terminal state or totals.
            if phase >= 0:
                if annotate:
                    event.setdefault("pair_damage", float(event.get("damage", 0.0)))
                    event["live_damage"] = 0.0
                    event["overkill"] = 0.0
                event["damage"] = 0.0
            event["applied_amount"] = 0.0
            event["skipped_reason"] = "outside_window"
            continue

        _expire_timed_shields(state, event_time)

        if (
            state["healing_reduction_until"] > 0.0
            and event_time >= state["healing_reduction_until"]
        ):
            # A new wound after expiry starts a fresh composition window; do
            # not carry the prior factor or source labels into its receipt.
            state["healing_reduction_factor"] = 1.0
            state["healing_reduction_sources"].clear()

        if (
            not state["threshold_shield_triggered"]
            and state["threshold_shield"] > 0.0
            and state["threshold_shield_duration"] > 0.0
            and event_time > state["threshold_shield_duration"]
            and state["threshold_shield_expired_at"] is None
        ):
            state["threshold_shield_expired_at"] = round(
                state["threshold_shield_duration"], 3
            )

        if (
            state["temporary_health_amount"] > 0.0
            and state["temporary_health_until"] > 0.0
            and event_time >= state["temporary_health_until"]
        ):
            expired = state["temporary_health_amount"]
            state["max_health"] = max(0.0, state["max_health"] - expired)
            state["health"] = min(state["health"], state["max_health"])
            state["temporary_health_amount"] = 0.0
            state["temporary_health_expired_at"] = round(
                state["temporary_health_until"], 3
            )
            state["temporary_health_until"] = 0.0

        kind = str(event.get("kind", ""))
        # Revive is a state transition rather than healing: it is allowed to
        # run after a lethal packet and restores a sourced resource amount.
        if kind == "revive":
            if state["death_time"] is None or state["revive_used"]:
                event["applied_amount"] = 0.0
                event["skipped_reason"] = "revive_not_available"
                continue
            ratio = max(0.0, min(1.0, float(event.get("health_ratio", 0.0) or 0.0)))
            amount = max(0.0, float(event.get("amount", 0.0) or 0.0))
            restore = amount if amount > 0.0 else state["max_health"] * ratio
            state["health"] = min(state["max_health"], restore)
            state["death_time"] = None
            state["revive_time"] = float(event_time)
            state["revive_source"] = str(
                event.get("source", event.get("source_key", "Revive"))
            )
            state["revive_health_restored"] = float(state["health"])
            state["revived"] = True
            state["revive_used"] = True
            state["terminal_phase"] = "revived"
            event["applied_amount"] = round(state["health"], 6)
            continue
        if kind in {"stasis", "invulnerability", "untargetable"}:
            duration_value = max(0.0, float(event.get("duration", 0.0) or 0.0))
            until_key = {
                "stasis": "stasis_until",
                "invulnerability": "invulnerable_until",
                "untargetable": "untargetable_until",
            }[kind]
            state[until_key] = max(state[until_key], float(event_time) + duration_value)
            if kind == "stasis":
                state["stasis_started_at"] = float(event_time)
                state["stasis_source"] = str(
                    event.get("source", event.get("source_key", "Stasis"))
                )
            event["applied_amount"] = round(duration_value, 6)
            continue
        if kind == "spell_shield":
            duration_value = max(0.0, float(event.get("duration", 0.0) or 0.0))
            if duration_value <= 0.0 or state["spell_shield_used"]:
                event["applied_amount"] = 0.0
                event["skipped_reason"] = "spell_shield_not_available"
            else:
                state["spell_shield_until"] = max(
                    state["spell_shield_until"], event_time + duration_value
                )
                state["spell_shield_source"] = str(
                    event.get("source", event.get("source_key", "Spell Shield"))
                )
                event["applied_amount"] = round(duration_value, 6)
            continue
        defy_trigger_id = event.get("_defy_trigger_id")
        if (
            defy_trigger_id is not None
            and str(defy_trigger_id) not in state["defy_triggered_damage_ids"]
        ):
            event["applied_amount"] = 0.0
            event["skipped_reason"] = "defy_not_triggered"
            continue
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
        if event.get("_redirect_cancelled"):
            if phase >= 1:
                event["applied_amount"] = 0.0
            else:
                if annotate:
                    event.setdefault("pair_damage", float(event.get("damage", 0.0)))
                    event["live_damage"] = 0.0
                    event["overkill"] = 0.0
                event["damage"] = 0.0
            event["applied_amount"] = 0.0
            event.setdefault("skipped_reason", "redirect_gate")
            continue
        # Knight's Vow's 30%-health condition is an ordered state gate.  The
        # direct share is expanded above so its recipient can be repriced; if
        # the holder is already at or below the threshold, cancel that child
        # and restore the unredirected packet on the Worthy target.
        if not event.get("_redirected"):
            child = redirect_children.get(str(event.get("_event_id", "")))
            if child is not None and not event.get("_redirect_gate_checked"):
                holder_id = str(child.get("target", ""))
                holder_state = states.get(holder_id)
                try:
                    required_ratio = float(
                        event.get("redirect_holder_health_ratio", 0.0) or 0.0
                    )
                except (TypeError, ValueError):
                    required_ratio = 0.0
                holder_ready = bool(holder_state) and (
                    holder_state["death_time"] is None
                    and (
                        required_ratio <= 0.0
                        or holder_state["max_health"] <= 0.0
                        or holder_state["health"]
                        > holder_state["max_health"] * required_ratio + 1e-9
                    )
                )
                event["_redirect_gate_checked"] = True
                child["_redirect_gate_checked"] = True
                if not holder_ready:
                    child["_redirect_cancelled"] = True
                    child["damage"] = 0.0
                    child["skipped_reason"] = "holder_health_gate"
                    restored = max(
                        0.0,
                        float(event.get("_redirect_original_damage", 0.0) or 0.0),
                    )
                    event["damage"] = restored
                    event["_redirected_amount"] = 0.0
                    event["_redirect_fraction"] = 0.0
                    event["redirect_skipped_reason"] = "holder_health_gate"
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
        if kind == "shield":
            amount = max(0.0, float(event.get("amount", 0.0) or 0.0))
            amount *= state["healing_received_multiplier"]
            duration_value = max(0.0, float(event.get("duration", 0.0) or 0.0))
            if amount <= 0.0:
                event["applied_amount"] = 0.0
                event["skipped_reason"] = "shield_not_available"
                continue
            state["shields"]["general_shield"] += amount
            state["support_shield_received"] += amount
            if duration_value > 0.0:
                expires_at = event_time + duration_value
                state["timed_shields"].append(
                    {"amount": amount, "expires_at": expires_at}
                )
                event["expires_at"] = round(expires_at, 3)
            event["applied_amount"] = round(amount, 6)
            continue
        if kind == "stat_buff":
            duration_value = max(0.0, float(event.get("duration", 0.0) or 0.0))
            if duration_value <= 0.0:
                event["applied_amount"] = 0.0
                event["skipped_reason"] = "stat_buff_not_available"
                continue
            buff = {
                "source": str(event.get("source", "Ally stat buff")),
                "until": event_time + duration_value,
                "bonus_attack_speed_percent": float(
                    event.get("bonus_attack_speed_percent", 0.0) or 0.0
                ),
                "ability_power": float(event.get("ability_power", 0.0) or 0.0),
                "ability_haste": float(event.get("ability_haste", 0.0) or 0.0),
                "on_hit_magic_damage": float(
                    event.get("on_hit_magic_damage", 0.0) or 0.0
                ),
            }
            state["support_buffs"].append(buff)
            if buff["on_hit_magic_damage"] > 0.0:
                state["active_on_hit_magic"].append(
                    {
                        "source": buff["source"],
                        "amount": buff["on_hit_magic_damage"],
                        "until": buff["until"],
                    }
                )
            event["expires_at"] = round(event_time + duration_value, 3)
            event["applied_amount"] = round(float(event.get("amount", 0.0)), 6)
            continue
        if kind == "damage_modifier":
            duration_value = max(0.0, float(event.get("duration", 0.0) or 0.0))
            persistent = bool(event.get("persistent"))
            if duration_value <= 0.0 and not persistent:
                event["applied_amount"] = 0.0
                event["skipped_reason"] = "damage_modifier_not_available"
                continue
            modifier = {
                "source": str(event.get("source", "Damage modifier")),
                "until": float("inf") if persistent else event_time + duration_value,
                "multiplier": float(event.get("multiplier", 1.0) or 1.0),
                "reduction": (
                    float(event.get("amount", 0.0) or 0.0)
                    if event.get("damage_reduction")
                    else 0.0
                ),
                "damage_reduction": bool(event.get("damage_reduction")),
                "next_event_only": bool(event.get("next_event_only")),
                "armor_reduction_percent": float(
                    event.get("armor_reduction_percent", 0.0) or 0.0
                ),
                "mr_reduction_percent": float(
                    event.get("mr_reduction_percent", 0.0) or 0.0
                ),
                "resistance_type": str(event.get("resistance_type", "")),
                "owner": str(event.get("owner", "")),
            }
            state["active_damage_modifiers"].append(modifier)
            if not persistent:
                event["expires_at"] = round(event_time + duration_value, 3)
            event["applied_amount"] = round(float(event.get("amount", 0.0)), 6)
            continue
        if kind in {"on_hit_magic", "movement", "cleanse", "slow"}:
            state["utility_effects"].append(
                {
                    "source": str(event.get("source", kind)),
                    "kind": kind,
                    "time": event_time,
                    "amount": float(event.get("amount", 0.0) or 0.0),
                    "duration": float(event.get("duration", 0.0) or 0.0),
                }
            )
            if kind == "on_hit_magic":
                duration_value = max(0.0, float(event.get("duration", 0.0) or 0.0))
                state["active_on_hit_magic"].append(
                    {
                        "source": str(event.get("source", "On-hit magic")),
                        "amount": float(event.get("amount", 0.0) or 0.0),
                        "until": event_time + duration_value,
                        "next_event_only": bool(event.get("next_event_only")),
                    }
                )
            event["applied_amount"] = round(float(event.get("amount", 0.0)), 6)
            if event.get("duration") is not None:
                event["expires_at"] = round(
                    event_time + float(event.get("duration", 0.0) or 0.0), 3
                )
            continue
        deferred_batch_id = event.get("_deferred_batch_id")
        if (
            deferred_batch_id is not None
            and str(deferred_batch_id) in state["cleared_deferred_batches"]
        ):
            if annotate:
                event.setdefault("pair_damage", float(event.get("damage", 0.0)))
                event["live_damage"] = 0.0
                event["overkill"] = 0.0
            event["damage"] = 0.0
            event["applied_amount"] = 0.0
            event["skipped_reason"] = "defy_cleared_deferred_damage"
            continue
        if phase >= 0 and (
            state["stasis_until"] > event_time
            or state["invulnerable_until"] > event_time
            or state["untargetable_until"] > event_time
        ):
            if annotate:
                event.setdefault("pair_damage", float(event.get("damage", 0.0)))
                event["live_damage"] = 0.0
                event["overkill"] = 0.0
            event["damage"] = 0.0
            event["applied_amount"] = 0.0
            event["skipped_reason"] = "target_state_blocked"
            continue
        cast_identity = event.get("ability_instance")
        if not cast_identity:
            cast_identity = (
                f"{event.get('source_key', '')}:" f"{round(float(event_time), 9)}"
            )
        cast_key = (str(cast_identity),)
        same_blocked_cast = state["spell_shield_blocked_cast"] == cast_key
        if (
            phase >= 0
            and event.get("is_ability")
            and state["spell_shield_until"] > event_time
            and (not state["spell_shield_used"] or same_blocked_cast)
        ):
            if not state["spell_shield_used"]:
                state["spell_shield_used"] = True
                state["spell_shield_blocked_cast"] = cast_key
            event_id = event.get("_event_id")
            if event_id is not None:
                damage_event_status[str(event_id)] = "blocked"
            if annotate:
                event.setdefault("pair_damage", float(event.get("damage", 0.0)))
                event["live_damage"] = 0.0
                event["overkill"] = 0.0
                event["spell_shield_source"] = state["spell_shield_source"]
            event["damage"] = 0.0
            event["applied_amount"] = 0.0
            event["skipped_reason"] = "spell_shield"
            continue
        source_id = event.get("attacker")
        if (
            phase >= 0
            and source_id in states
            and not event.get("_reactive")
            and (
                states[source_id]["stasis_until"] > event_time
                or states[source_id]["invulnerable_until"] > event_time
                or states[source_id]["untargetable_until"] > event_time
            )
        ):
            event_id = event.get("_event_id")
            if event_id is not None:
                damage_event_status[str(event_id)] = "blocked"
            if annotate:
                event.setdefault("pair_damage", float(event.get("damage", 0.0)))
                event["live_damage"] = 0.0
                event["overkill"] = 0.0
            event["damage"] = 0.0
            event["applied_amount"] = 0.0
            event["skipped_reason"] = "attacker_state_blocked"
            continue
        if (
            source_id in states
            and states[source_id]["death_time"] is not None
            and not event.get("_reactive")
            and not event.get("_deferred")
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
        _update_combat_state(participant_id, event, float(event_time))
        _reprice_dynamic_resistance(participant_id, event)
        # Apply live cross-participant modifiers after the pair engine's
        # sourced mitigation and before shields/health.  Flat Dream Maker
        # reduction is post-mitigation; Imperial-style all-source modifiers
        # multiply the remaining packet.  Both consume only an authored
        # duration/trigger and therefore never become permanent item stats.
        active_modifiers = [
            modifier
            for modifier in state["active_damage_modifiers"]
            if float(modifier.get("until", 0.0)) > event_time
        ]
        state["active_damage_modifiers"] = active_modifiers
        for modifier in list(active_modifiers):
            if modifier.get("owner") and modifier.get("owner") == source_id:
                # The originating holder's pair engine already priced its
                # own stack/amp.  The packet exists for every other eligible
                # participant in the coupled ledger.
                continue
            is_attack_or_spell = bool(
                event.get("is_ability")
                or event.get("basic_attack")
                or str(event.get("source_key", "")) == "auto_attacks"
            )
            resistance_key = str(modifier.get("resistance_type", ""))
            reduction_key = (
                "armor_reduction_percent"
                if resistance_key == "armor"
                else (
                    "mr_reduction_percent"
                    if resistance_key in {"mr", "magic_resistance"}
                    else ""
                )
            )
            if reduction_key:
                relevant_type = (
                    "physical" if reduction_key.startswith("armor") else "magic"
                )
                if event.get("damage_type") != relevant_type:
                    continue
                if not is_attack_or_spell:
                    continue
                baseline_key = (
                    "_baseline_effective_armor"
                    if reduction_key.startswith("armor")
                    else "_baseline_effective_mr"
                )
                try:
                    baseline = float(event[baseline_key])
                    percentage = max(
                        0.0,
                        min(1.0, float(modifier.get(reduction_key, 0.0) or 0.0)),
                    )
                except (KeyError, TypeError, ValueError):
                    event["support_resistance_reduction_unavailable"] = reduction_key
                    continue
                before = max(0.0, float(event.get("damage", 0.0) or 0.0))
                baseline_factor = apply_resistance(1.0, baseline)
                reduced_factor = apply_resistance(
                    1.0, max(0.0, baseline * (1.0 - percentage))
                )
                if baseline_factor > 0.0:
                    event["damage"] = before * reduced_factor / baseline_factor
                    event.setdefault("support_resistance_reduction", []).append(
                        {
                            "source": modifier["source"],
                            "type": reduction_key,
                            "fraction": round(percentage, 6),
                            "factor": round(reduced_factor / baseline_factor, 6),
                        }
                    )
                continue
            if not is_attack_or_spell:
                continue
            if modifier.get("damage_reduction"):
                before = max(0.0, float(event.get("damage", 0.0) or 0.0))
                reduction = min(before, max(0.0, float(modifier.get("reduction", 0.0))))
                event["damage"] = before - reduction
                event["support_damage_reduction"] = {
                    "source": modifier["source"],
                    "amount": round(reduction, 6),
                }
                if modifier.get("next_event_only"):
                    active_modifiers.remove(modifier)
            else:
                factor = max(0.0, float(modifier.get("multiplier", 1.0) or 1.0))
                before = max(0.0, float(event.get("damage", 0.0) or 0.0))
                event["damage"] = before * factor
                event["support_damage_multiplier"] = {
                    "source": modifier["source"],
                    "multiplier": round(factor, 6),
                }
        source_state = states.get(str(source_id))
        active_on_hit = [
            bonus
            for bonus in (source_state["active_on_hit_magic"] if source_state else [])
            if float(bonus.get("until", 0.0)) > event_time
        ]
        if source_state is not None:
            source_state["active_on_hit_magic"] = active_on_hit
        if source_state is not None and (
            event.get("basic_attack")
            or str(event.get("source_key", "")) == "auto_attacks"
            or event.get("is_ability")
        ):
            for bonus in list(active_on_hit):
                raw_bonus = max(0.0, float(bonus.get("amount", 0.0) or 0.0))
                if raw_bonus <= 0.0:
                    continue
                effective_mr = event.get("_baseline_effective_mr", 0.0)
                try:
                    effective_mr = float(effective_mr)
                except (TypeError, ValueError):
                    effective_mr = 0.0
                bonus_damage = apply_resistance(raw_bonus, effective_mr)
                event["damage"] = float(event.get("damage", 0.0) or 0.0) + bonus_damage
                event.setdefault("support_on_hit_magic", []).append(
                    {
                        "source": bonus["source"],
                        "raw": round(raw_bonus, 6),
                        "mitigated": round(bonus_damage, 6),
                    }
                )
                if bonus.get("next_event_only"):
                    active_on_hit.remove(bonus)
        # Celestial Opposition's Blessed reduction is a target-state modifier,
        # not a basic-attack modifier.  Apply it to authored champion damage
        # after the pair engine's resistance math and refresh the exact
        # lingering window from the hit timestamp.  Reactive item packets are
        # excluded so a shield or thorns return cannot manufacture a new
        # champion-hit window.
        incoming_damage_type = str(event.get("damage_type", ""))
        if (
            phase >= 0
            and source_id in states
            and source_id != participant_id
            and not event.get("_reactive")
            and incoming_damage_type in {"physical", "magic", "true"}
            and state["incoming_damage_multiplier"] < 1.0
            and event_time < state["incoming_damage_until"]
        ):
            reduction = state["incoming_damage_multiplier"]
            original_incoming = max(0.0, float(event.get("damage", 0.0) or 0.0))
            event["damage"] = original_incoming * reduction
            if annotate:
                event["incoming_damage_multiplier"] = round(reduction, 6)
                event["incoming_damage_source"] = state["incoming_damage_source"]
                event["incoming_damage_reduction"] = round(
                    original_incoming - event["damage"], 6
                )
            if state["incoming_damage_linger"] > 0.0:
                state["incoming_damage_until"] = (
                    event_time + state["incoming_damage_linger"]
                )
            if state["incoming_damage_cooldown"] > 0.0:
                state["incoming_damage_cooldown_until"] = max(
                    state["incoming_damage_cooldown_until"],
                    event_time + state["incoming_damage_cooldown"],
                )
        if phase == -1:
            kind = str(event.get("kind", ""))
            amount = max(0.0, float(event.get("amount", 0.0)))
            if kind == "temporary_health":
                duration_value = max(0.0, float(event.get("duration", 0.0) or 0.0))
                if amount <= 0.0 or duration_value <= 0.0:
                    event["applied_amount"] = 0.0
                    event["skipped_reason"] = "temporary_health_not_available"
                    continue
                state["max_health"] += amount
                state["health"] += amount
                state["temporary_health_received"] += amount
                state["temporary_health_amount"] += amount
                state["temporary_health_until"] = max(
                    state["temporary_health_until"], event_time + duration_value
                )
                state["temporary_health_source"] = str(
                    event.get("source", event.get("source_key", "Temporary Health"))
                )
                event["expires_at"] = round(event_time + duration_value, 3)
                event["applied_amount"] = round(amount, 6)
            elif kind in {"heal", "regen"}:
                try:
                    holder_ratio_gate = float(
                        event.get("requires_holder_health_ratio", 0.0) or 0.0
                    )
                except (TypeError, ValueError):
                    holder_ratio_gate = 0.0
                if (
                    holder_ratio_gate > 0.0
                    and state["max_health"] > 0.0
                    and state["health"]
                    <= state["max_health"] * holder_ratio_gate + 1e-9
                ):
                    event["applied_amount"] = 0.0
                    event["skipped_reason"] = "holder_health_gate"
                    continue
                if _recovery_is_gated(state, event, event_time):
                    event["applied_amount"] = 0.0
                    event["skipped_reason"] = "damage_free_window_not_ready"
                    continue
                amount_formula = event.get("amount_formula")
                if callable(amount_formula):
                    amount = max(
                        0.0,
                        float(amount_formula(state["health"], state["max_health"])),
                    )
                amount *= _recovery_multiplier(state, event)
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
                excess = max(0.0, reduced_amount - received)
                temporary_duration = max(
                    0.0,
                    float(event.get("temporary_health_duration", 0.0) or 0.0),
                )
                temporary_health = (
                    excess
                    if event.get("overheal_to_temporary_health")
                    and temporary_duration > 0.0
                    and excess > 0.0
                    else 0.0
                )
                ichor_converted = _apply_ichorshield(
                    state, event, excess - temporary_health
                )
                state["overhealing"] += excess - temporary_health - ichor_converted
                state["health"] += received
                state["healing_received"] += received
                if temporary_health > 0.0:
                    state["max_health"] += temporary_health
                    state["health"] += temporary_health
                    state["temporary_health_received"] += temporary_health
                    state["temporary_health_amount"] += temporary_health
                    state["temporary_health_until"] = max(
                        state["temporary_health_until"],
                        event_time + temporary_duration,
                    )
                    state["temporary_health_source"] = str(
                        event.get("source", event.get("source_key", "Temporary Health"))
                    )
                    event["temporary_health"] = round(temporary_health, 6)
                    event["temporary_health_expires_at"] = round(
                        event_time + temporary_duration, 3
                    )
                if annotate:
                    event["raw_amount"] = round(amount, 6)
                    event["reduced_amount"] = round(reduced_amount, 6)
                    event["healing_reduction_factor"] = round(reduction_factor, 6)
                    event["overheal"] = round(
                        excess - temporary_health - ichor_converted, 6
                    )
                event["applied_amount"] = round(received, 6)
                if event.get("_defy_trigger_id") is not None:
                    state["defy_heal_received"] += received
            continue
        if phase == 1:
            try:
                holder_ratio_gate = float(
                    event.get("requires_holder_health_ratio", 0.0) or 0.0
                )
            except (TypeError, ValueError):
                holder_ratio_gate = 0.0
            if (
                holder_ratio_gate > 0.0
                and state["max_health"] > 0.0
                and state["health"] <= state["max_health"] * holder_ratio_gate + 1e-9
            ):
                event["applied_amount"] = 0.0
                event["skipped_reason"] = "holder_health_gate"
                continue
            if _recovery_is_gated(state, event, event_time):
                event["applied_amount"] = 0.0
                event["skipped_reason"] = "damage_free_window_not_ready"
                continue
            amount = max(0.0, float(event.get("amount", 0.0)))
            amount_formula = event.get("amount_formula")
            if callable(amount_formula):
                amount = max(
                    0.0,
                    float(amount_formula(state["health"], state["max_health"])),
                )
            amount *= _recovery_multiplier(state, event)
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
            excess = max(0.0, reduced_amount - received)
            temporary_duration = max(
                0.0, float(event.get("temporary_health_duration", 0.0) or 0.0)
            )
            temporary_health = (
                excess
                if event.get("overheal_to_temporary_health")
                and temporary_duration > 0.0
                and excess > 0.0
                else 0.0
            )
            ichor_converted = _apply_ichorshield(
                state, event, excess - temporary_health
            )
            state["overhealing"] += excess - temporary_health - ichor_converted
            state["health"] += received
            state["healing_received"] += received
            if temporary_health > 0.0:
                state["max_health"] += temporary_health
                state["health"] += temporary_health
                state["temporary_health_received"] += temporary_health
                state["temporary_health_amount"] += temporary_health
                state["temporary_health_until"] = max(
                    state["temporary_health_until"], event_time + temporary_duration
                )
                state["temporary_health_source"] = str(
                    event.get("source", event.get("source_key", "Temporary Health"))
                )
                event["temporary_health"] = round(temporary_health, 6)
                event["temporary_health_expires_at"] = round(
                    event_time + temporary_duration, 3
                )
            if annotate:
                event["raw_amount"] = round(amount, 6)
                event["reduced_amount"] = round(reduced_amount, 6)
                event["healing_reduction_factor"] = round(reduction_factor, 6)
                event["overheal"] = round(
                    excess - temporary_health - ichor_converted, 6
                )
            event["applied_amount"] = round(received, 6)
            if event.get("_defy_trigger_id") is not None:
                state["defy_heal_received"] += received
            continue

        amount = max(0.0, float(event.get("damage", 0.0)))
        event_id = event.get("_event_id")
        if event_id is not None:
            damage_event_status[str(event_id)] = "applied"
        if event.get("_deferred"):
            batch_id = str(event.get("_deferred_batch_id", ""))
            if batch_id in state["deferred_batches"]:
                state["deferred_batches"][batch_id] = max(
                    0.0, state["deferred_batches"][batch_id] - amount
                )
                state["damage_deferral_pending"] = max(
                    0.0, state["damage_deferral_pending"] - amount
                )
                if state["deferred_batches"][batch_id] <= 1e-9:
                    del state["deferred_batches"][batch_id]
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
                live_raw = _evaluate_live_raw_formula(
                    raw_formula, missing_ratio, state["max_health"]
                )
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
            absorbed = _consume_typed_shield(state, key, amount)
            amount -= absorbed
            state["shield_absorbed"] += absorbed
            event_absorbed += absorbed
        # Lifeline-style threshold shields and temporary health are armed by
        # the post-starting-shield damage that would cross the authored
        # health threshold.  They expire on their sourced duration and never
        # trigger a second time in the same fight.
        threshold_due = (
            not state["threshold_shield_triggered"]
            and state["threshold_shield"] > 0.0
            and state["threshold_shield_threshold"] > 0.0
            and event_time <= state["threshold_shield_duration"]
            and state["health"] - amount <= state["threshold_shield_threshold"]
            and state["threshold_shield_damage_type"] in {"all", damage_type}
        )
        health_due = (
            not state["threshold_health_triggered"]
            and state["threshold_health_bonus"] > 0.0
            and state["threshold_health_ratio"] > 0.0
            and state["threshold_health_duration"] > 0.0
            and state["health"] - amount
            <= state["max_health"] * state["threshold_health_ratio"]
        )
        if threshold_due or health_due:
            if threshold_due:
                state["threshold_shield_triggered"] = True
                state["shields"]["general_shield"] += state["threshold_shield"]
                state["threshold_shield"] = 0.0
                event["threshold_shield_triggered"] = True
            if health_due:
                bonus = state["threshold_health_bonus"]
                state["max_health"] += bonus
                state["health"] += bonus
                heal = min(
                    state["threshold_health_heal"],
                    max(0.0, state["max_health"] - state["health"]),
                )
                state["health"] += heal
                state["healing_received"] += heal
                state["threshold_health_triggered"] = True
                event["threshold_health_triggered"] = True
        general_absorbed = _consume_general_shield(state, amount)
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
        if event["damage"] > 0.0:
            state["last_damage_time"] = float(event_time)
            _schedule_doran_shield_recovery(participant_id, event, float(event_time))
        # Noxian Endurance/Persistence grant their typed shield *after* the
        # triggering champion hit.  Keep the shield in the timed pool so it
        # expires and is consumed in the same order as every other sourced
        # barrier; the cooldown is explicit and never inferred from a second
        # packet in the same cast.
        reactive_type = state["reactive_shield_damage_type"]
        if (
            event["damage"] > 0.0
            and source_id in states
            and source_id != participant_id
            and not event.get("_reactive")
            and reactive_type in {"physical", "magic"}
            and damage_type == reactive_type
            and event_time >= state["reactive_shield_cooldown_until"]
            and state["reactive_shield_amount"] > 0.0
            and state["reactive_shield_duration"] > 0.0
        ):
            # ``resolve_starting_defenses`` applies Spirit Visage once when it
            # resolves this item-owned amount. Do not multiply it again at
            # trigger time.
            shield_amount = state["reactive_shield_amount"]
            state["shields"][f"{reactive_type}_shield"] += shield_amount
            expires_at = event_time + state["reactive_shield_duration"]
            state["timed_shields"].append(
                {
                    "amount": shield_amount,
                    "expires_at": expires_at,
                    "shield_key": f"{reactive_type}_shield",
                    "source": state["reactive_shield_source"],
                }
            )
            state["support_shield_received"] += shield_amount
            state["reactive_shield_cooldown_until"] = (
                event_time + state["reactive_shield_cooldown"]
            )
            if annotate:
                event["reactive_shield_triggered"] = {
                    "amount": round(shield_amount, 6),
                    "damage_type": reactive_type,
                    "source": state["reactive_shield_source"],
                    "expires_at": round(expires_at, 3),
                    "cooldown_until": round(state["reactive_shield_cooldown_until"], 3),
                }
        if (
            source_id in states
            and source_id != participant_id
            and not event.get("_deferred")
            and event["damage"] > 0.0
        ):
            states[str(source_id)]["damage_records"].append(
                {
                    "target": participant_id,
                    "time": float(event_time),
                    "event_id": str(event_id or ""),
                }
            )
        # The Collector is an authored terminal transition.  Its threshold
        # is carried by the attacker's event from the cached item effect; it
        # never contributes extra damage or fires from an aggregate row.
        try:
            execute_ratio = float(event.get("execute_threshold_ratio", 0.0) or 0.0)
        except (TypeError, ValueError):
            execute_ratio = 0.0
        if (
            execute_ratio > 0.0
            and applied_to_health > 0.0
            and state["health"] > 0.0
            and state["health"] <= state["max_health"] * execute_ratio
        ):
            state["health"] = 0.0
            state["execute_time"] = float(event_time)
            state["execute_source"] = str(event.get("execute_source", "The Collector"))
            state["death_time"] = min(float(duration), float(event_time))
            state["terminal_phase"] = "dead"
            event["execute_triggered"] = True
            event["execute_threshold"] = round(state["max_health"] * execute_ratio, 6)
            if state["first_death_time"] is None:
                state["first_death_time"] = float(event_time)
            _trigger_defy(participant_id, float(event_time))
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
            state["healing_reduction_events"].append(
                {
                    "time": round(event_time, 3),
                    "until": round(state["healing_reduction_until"], 3),
                    "factor": round(state["healing_reduction_factor"], 6),
                    "sources": sorted(state["healing_reduction_sources"]),
                }
            )
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
            state["healing_reduction_events"].append(
                {
                    "time": round(event_time, 3),
                    "until": round(state["healing_reduction_until"], 3),
                    "factor": round(state["healing_reduction_factor"], 6),
                    "sources": sorted(state["healing_reduction_sources"]),
                }
            )
        if state["health"] <= 0.0 and state["death_time"] is None:
            if state["first_death_time"] is None:
                state["first_death_time"] = float(event_time)
            _trigger_defy(participant_id, float(event_time))
            state["death_time"] = min(float(duration), event_time)
            state["terminal_phase"] = "dead"
            # A revive packet is intentionally scheduled by the caller.  A
            # dead participant remains terminal until that explicit event;
            # no item is inferred from the loadout here.

    for state in states.values():
        _expire_timed_shields(state, float(duration))
        if (
            state["temporary_health_amount"] > 0.0
            and state["temporary_health_until"] > 0.0
            and duration >= state["temporary_health_until"]
        ):
            expired = state["temporary_health_amount"]
            state["max_health"] = max(0.0, state["max_health"] - expired)
            state["health"] = min(state["health"], state["max_health"])
            state["temporary_health_amount"] = 0.0
            state["temporary_health_expired_at"] = round(
                state["temporary_health_until"], 3
            )
            state["temporary_health_until"] = 0.0

    result = {}
    for participant_id, state in states.items():
        remaining_shields = sum(state["shields"].values())
        result[participant_id] = {
            "max_health": round(state["max_health"], 1),
            "ending_health": round(state["health"], 1),
            "ending_health_ratio": round(
                (
                    state["health"] / state["max_health"]
                    if state["max_health"] > 0.0
                    else 0.0
                ),
                6,
            ),
            "damage_taken": round(state["damage_taken"], 1),
            "overkill": round(state["overkill"], 1),
            "health_damage": round(state["health_damage"], 1),
            "shield_absorbed": round(state["shield_absorbed"], 1),
            "healing_received": round(state["healing_received"], 1),
            "overhealing": round(state["overhealing"], 1),
            "healing_reduced": round(state["healing_reduced"], 1),
            "support_shield_received": round(state["support_shield_received"], 1),
            "support_shield_expired": round(state["support_shield_expired"], 1),
            "temporary_health_received": round(state["temporary_health_received"], 1),
            "temporary_health_until": round(state["temporary_health_until"], 3),
            "temporary_health_expired_at": state["temporary_health_expired_at"],
            "temporary_health_source": state["temporary_health_source"],
            "effective_health": round(
                state["max_health"]
                + state["starting_shield"]
                + state["support_shield_received"]
                - state["support_shield_expired"]
                + state["healing_received"],
                1,
            ),
            "remaining_shield": round(remaining_shields, 1),
            "starting_shield": round(state["starting_shield"], 1),
            "healing_reduction_until": round(state["healing_reduction_until"], 3),
            "healing_reduction_sources": sorted(state["healing_reduction_sources"]),
            "healing_reduction_events": [
                {"recipient": participant_id, **event}
                for event in state["healing_reduction_events"]
            ],
            "survived_window": state["death_time"] is None,
            "death_time": (
                round(state["death_time"], 3)
                if state["death_time"] is not None
                else None
            ),
            "first_death_time": (
                round(state["first_death_time"], 3)
                if state["first_death_time"] is not None
                else None
            ),
            "revived": bool(state["revived"]),
            "revive_time": (
                round(state["revive_time"], 3)
                if state["revive_time"] is not None
                else None
            ),
            "revive_health_restored": round(state["revive_health_restored"], 1),
            "revive_source": state["revive_source"],
            "terminal_phase": state["terminal_phase"],
            "execute_time": (
                round(state["execute_time"], 3)
                if state["execute_time"] is not None
                else None
            ),
            "execute_source": state["execute_source"],
            "stasis_until": round(state["stasis_until"], 3),
            "stasis_started_at": state["stasis_started_at"],
            "stasis_source": state["stasis_source"],
            "invulnerable_until": round(state["invulnerable_until"], 3),
            "untargetable_until": round(state["untargetable_until"], 3),
            "spell_shield_used": bool(state["spell_shield_used"]),
            "spell_shield_source": state["spell_shield_source"],
            "spell_shield_until": (
                None
                if math.isinf(state["spell_shield_until"])
                else round(state["spell_shield_until"], 3)
            ),
            "force_of_nature": {
                "stacks": int(state["force_stacks"]),
                "stacks_until": round(state["force_stacks_until"], 3),
                "events": list(state["force_stack_events"]),
                "dynamic_bonus_magic_resistance": round(
                    float(state.get("dynamic_bonus_magic_resistance", 0.0) or 0.0),
                    3,
                ),
            },
            "jaksho": {
                "stacks": int(state["jaksho_stacks"]),
                "events": list(state["jaksho_stack_events"]),
                "dynamic_bonus_armor": round(
                    float(state.get("dynamic_bonus_armor", 0.0) or 0.0), 3
                ),
                "dynamic_bonus_magic_resistance": round(
                    float(state.get("dynamic_bonus_magic_resistance", 0.0) or 0.0),
                    3,
                ),
            },
            "threshold_shield_triggered": bool(state["threshold_shield_triggered"]),
            "threshold_shield_expired_at": state["threshold_shield_expired_at"],
            "threshold_health_triggered": bool(state["threshold_health_triggered"]),
            "damage_deferral_fraction": round(
                float(
                    getattr(
                        combatant_by_id[participant_id].defenses,
                        "damage_deferral_fraction",
                        0.0,
                    )
                    or 0.0
                ),
                3,
            ),
            "damage_deferral_pending": round(state["damage_deferral_pending"], 1),
            "damage_deferral_cleared": round(state["damage_deferral_cleared"], 1),
            "defy_triggered": bool(state["defy_triggered"]),
            "defy_trigger_time": (
                round(state["defy_trigger_time"], 3)
                if state["defy_trigger_time"] is not None
                else None
            ),
            "defy_heal_received": round(state["defy_heal_received"], 1),
        }
    return result


# ---------------------------------------------------------------------------
# Compiled score walk — the coupled optimizer's fast path
# ---------------------------------------------------------------------------
# A coupled search walks the same roster events for thousands of candidates.
# Score mode therefore compiles every event into one flat action tuple —
# sort key, participant indices, trigger slot, pre-resolved Grievous pack —
# and keeps everything a candidate swap cannot change (roster pair fights,
# their heals and support packets, roster-strike thorns) in a presorted
# per-defensive-signature panel.  An evaluation compiles only the main
# champion's fresh outgoing fights, concatenates, re-sorts (a cheap two-run
# merge), and walks without copying or mutating a single event dict.  The
# walk reproduces ``_simulate_survival``'s arithmetic exactly — same
# operations, same order, same rounding — and the assembly replays both
# the legacy per-attacker float-addition order and its rounded
# death-time cutoff (an attacker's own event at the exact death instant
# is applied by the walk but excluded from the outgoing total whenever
# the true death time rounds down past it) — pinned by the equivalence
# tests in tests/test_participant_timeline.py.

_KIND_DAMAGE, _KIND_HEAL, _KIND_SHIELD, _KIND_PLAIN_DAMAGE = 0, 1, 2, 3
# _KIND_PLAIN_DAMAGE marks a damage action with no trigger link, no
# live-health repricing, no Grievous pack, and no wound — the walk
# skips those four branch reads.  Classified at compile time only.

# Positional layout of one compiled walk action (built by _WalkCompiler,
# consumed by _compiled_survival_walk).  Slot 0 is the sort key; every
# compiler site fills ``attacker`` with a real participant index, so the
# walk never sees a negative one.
_A_KIND, _A_SUBJECT, _A_ATTACKER, _A_TRIGGER, _A_AIDX = 1, 2, 3, 4, 5
_A_AMOUNT, _A_DTYPE, _A_RAW_FORMULA, _A_RAW_DAMAGE = 6, 7, 8, 9
_A_GRIEVOUS, _A_WOUND, _A_REACTIVE, _A_TIME = 10, 11, 12, 13
_DTYPE_CODES = {"physical": 0, "magic": 1}


def _heal_trigger_key(event: Mapping[str, Any]) -> tuple[str, float, int]:
    """The trigger identity carried by an engine self-heal event."""
    return (
        str(event.get("_trigger_source", "")),
        round(float(event.get("_trigger_time", 0.0)), 9),
        int(event.get("_trigger_sequence", 0) or 0),
    )


def _grievous_pack(
    profiles: tuple[Any, ...], damage_type: str
) -> tuple[float, float, tuple[str, ...]] | None:
    """Pre-resolve one attacker's Grievous application for one damage type.

    The legacy walk matches reduction profiles per event; the compiled walk
    does it once per (attacker, damage type) because both are fixed for a
    compiled action.  Returns (strongest factor, strongest duration, all
    matching source labels) exactly as the per-event code would derive them.
    """
    matching = matching_healing_reduction(profiles, damage_type) if profiles else ()
    if not matching:
        return None
    strongest = min(matching, key=lambda profile: float(profile.get("factor", 1.0)))
    labels = tuple(
        f"{profile.get('item', '')} · {profile.get('source', '')}"
        for profile in matching
    )
    return (
        float(strongest.get("factor", 1.0)),
        float(strongest.get("duration", 0.0)),
        labels,
    )


class _WalkCompiler:
    """Accumulates flat walk actions with stable per-action ids.

    One compiler builds the invariant panel (roster pairs), another builds
    an evaluation's fresh actions starting after the panel's id range so
    trigger references and the per-eval ``applied`` array stay aligned.

    Action tuple layout (walk-unpacked positionally):
    ``(sort_key, kind, subject_i, attacker_i, trigger_aidx, aidx, amount,
    dtype, raw_formula, raw_damage, grievous_pack, wound, reactive, time)``.
    ``trigger_aidx`` is -1 for none and -2 for a trigger id that cannot
    resolve (the legacy walk skips such an event; no current author emits
    one, but the semantics must not silently change if one appears).
    """

    __slots__ = (
        "actions",
        "damage_order",
        "thorns_order",
        "support_entries",
        "auto_strikes_into",
        "coverage",
        "next_aidx",
    )

    def __init__(self, first_aidx: int = 0) -> None:
        self.actions: list[tuple[Any, ...]] = []
        self.damage_order: dict[int, list[int]] = defaultdict(list)
        self.thorns_order: dict[int, list[int]] = defaultdict(list)
        self.support_entries: list[tuple[str, int, int, bool]] = []
        self.auto_strikes_into: dict[int, list[tuple[int, float, int, int]]] = (
            defaultdict(list)
        )
        self.coverage: list[dict[str, Any]] = []
        self.next_aidx = first_aidx

    def add_packet(
        self,
        packet: Mapping[str, Any],
        attacker_i: int,
        defender_i: int,
        grievous_by_dtype: Mapping[str, Any],
        duration: float,
        heal_dedup: dict[tuple[str, float], float],
    ) -> None:
        """Compile one pair packet's damage events and self-heals.

        ``heal_dedup`` spans the attacker's packets, replaying the legacy
        actor-wide heal deduplication across that attacker's pair fights.
        """
        actions_append = self.actions.append
        order_append = self.damage_order[attacker_i].append
        strikes_append = self.auto_strikes_into[defender_i].append
        heals = packet["heals"]
        aidx_by_key: dict[tuple[str, float, int], int] | None = {} if heals else None
        aidx_by_source_time: dict[tuple[str, float], list[int]] = defaultdict(list)
        aidx = self.next_aidx
        for event in packet["events"]:
            # Packet events are enriched engine-ledger rows: these fields
            # are written unconditionally, so index them directly.
            time_value = event["time"]
            damage_type = event["damage_type"]
            damage = event["damage"]
            raw_formula = event.get("raw_formula")
            raw_damage = float(event.get("raw_damage", 0.0) or 0.0)
            live_formula = (
                raw_formula if callable(raw_formula) and raw_damage > 0 else None
            )
            grievous = grievous_by_dtype.get(damage_type)
            actions_append(
                (
                    event["_sk"],
                    (
                        _KIND_PLAIN_DAMAGE
                        if live_formula is None and grievous is None
                        else _KIND_DAMAGE
                    ),
                    defender_i,
                    attacker_i,
                    -1,
                    aidx,
                    damage if damage > 0.0 else 0.0,
                    _DTYPE_CODES.get(damage_type, 2),
                    live_formula,
                    raw_damage,
                    grievous,
                    None,
                    False,
                    time_value,
                )
            )
            if time_value <= duration:
                order_append((aidx, time_value))
            if aidx_by_key is not None:
                aidx_by_key[
                    (event["source_key"], round(time_value, 9), event["sequence"])
                ] = aidx
                aidx_by_source_time[(event["source_key"], round(time_value, 9))].append(
                    aidx
                )
            if event["source_key"] == "auto_attacks" or event.get("basic_attack"):
                strikes_append((aidx, time_value, event["sequence"], attacker_i))
            aidx += 1
        self.next_aidx = aidx
        for event in heals:
            trigger = aidx_by_key.get(_heal_trigger_key(event), -1)
            if trigger < 0:
                candidates = aidx_by_source_time.get(
                    (
                        str(event.get("_trigger_source", "")),
                        round(float(event.get("_trigger_time", 0.0)), 9),
                    ),
                    [],
                )
                if len(candidates) == 1:
                    trigger = candidates[0]
            if event.get("actor_wide"):
                if "_trigger_source" in event:
                    # Cross-pair dedup below keeps the copy that compiled
                    # first; a trigger link would make copies
                    # pair-dependent, so fail closed instead of guessing.
                    raise ValueError(
                        "actor-wide self-heal carries a trigger link; "
                        "the panel compiler cannot deduplicate it"
                    )
                dedup_key = (
                    str(event.get("source", "")),
                    float(event.get("time", 0.0)),
                )
                amount = max(0.0, float(event.get("amount", 0.0)))
                kept = heal_dedup.get(dedup_key)
                if kept is not None:
                    if kept != amount:
                        # The dedup keeps one copy per (source, time); that
                        # is only sound while every copy is value-identical.
                        raise ValueError(
                            "actor-wide self-heal copies disagree across "
                            "pair fights; the compiled dedup cannot keep one"
                        )
                    continue
                heal_dedup[dedup_key] = amount
            aidx = self.next_aidx
            self.next_aidx += 1
            actions_append(
                (
                    event["_sk"],
                    _KIND_HEAL,
                    attacker_i,
                    attacker_i,
                    trigger,
                    aidx,
                    max(0.0, float(event.get("amount", 0.0))),
                    2,
                    event.get("amount_formula"),
                    0.0,
                    None,
                    (
                        max(
                            0.0,
                            float(event.get("temporary_health_duration", 0.0) or 0.0),
                        )
                        if event.get("overheal_to_temporary_health")
                        else None
                    ),
                    False,
                    float(event.get("time", 0.0)),
                )
            )
        self.coverage.append(packet["result"].get("timeline_coverage", {}))

    def add_engine_result(
        self,
        result: Mapping[str, Any],
        attacker_id: str,
        attacker_i: int,
        defender_id: str,
        defender_i: int,
        grievous_by_dtype: Mapping[str, Any],
        duration: float,
        heal_dedup: dict[tuple[str, float], float],
        id_strings: list[str],
    ) -> None:
        """Compile a fresh one-pair fight straight from the engine rows.

        Equivalent to ``_pair_packet`` + :meth:`add_packet` — identical sort
        keys, trigger linkage, and heal dedup — minus the per-event dict
        enrichment nothing in score mode ever reads.  The sort-key layout is
        ``_action_key``'s; both must change together.  ``id_strings`` is the
        search-lifetime cache of this pair's positional event-id strings.
        """
        actions_append = self.actions.append
        order_append = self.damage_order[attacker_i].append
        strikes_append = self.auto_strikes_into[defender_i].append
        source_order = _participant_order(attacker_id)
        order_a, order_b = source_order
        known_ids = len(id_strings)
        aidx = self.next_aidx
        if result.get("damage_events_tuple"):
            # The engine's light ledger rows: (sort_key, damage, damage_type,
            # source_key, raw_formula, raw_damage), guaranteed heal-free by
            # the pipeline's tuple-ledger predicate, so no trigger linkage
            # can exist.  Every field below reads the same engine value the
            # dict path would.
            for index, row in enumerate(result.get("damage_events", [])):
                key = row[0]
                time_value = key[0]
                source_key = row[3]
                raw_formula = row[4]
                raw_damage = row[5]
                if index < known_ids:
                    event_id = id_strings[index]
                else:
                    event_id = f"{attacker_id}:{defender_id}:{index}"
                    id_strings.append(event_id)
                    known_ids += 1
                live_formula = (
                    raw_formula if callable(raw_formula) and raw_damage > 0 else None
                )
                grievous = grievous_by_dtype.get(row[2])
                actions_append(
                    (
                        (
                            time_value,
                            0.0,
                            key[3],
                            order_a,
                            order_b,
                            defender_id,
                            event_id,
                            source_key,
                        ),
                        (
                            _KIND_PLAIN_DAMAGE
                            if live_formula is None and grievous is None
                            else _KIND_DAMAGE
                        ),
                        defender_i,
                        attacker_i,
                        -1,
                        aidx,
                        row[1],
                        _DTYPE_CODES.get(row[2], 2),
                        live_formula,
                        raw_damage,
                        grievous,
                        None,
                        False,
                        time_value,
                    )
                )
                if time_value <= duration:
                    order_append((aidx, time_value))
                # Light tuple ledgers intentionally omit per-event metadata;
                # only their explicit auto stream can trigger Thorns.
                if source_key == "auto_attacks":
                    strikes_append((aidx, time_value, key[3], attacker_i))
                aidx += 1
            self.next_aidx = aidx
            self.coverage.append(result.get("timeline_coverage", {}))
            return
        heals = result.get("self_healing_events", [])
        # The trigger-linkage index costs a key tuple per damage event, so
        # a fight with no self-heals (most candidates) never builds it.
        aidx_by_key: dict[tuple[str, float, int], int] | None = {} if heals else None
        aidx_by_source_time: dict[tuple[str, float], list[int]] = defaultdict(list)
        for index, event in enumerate(result.get("damage_events", [])):
            if "sequence" not in event:
                # See _action_key: pair-local event ids stay order-irrelevant
                # only while every engine event carries its per-fight sequence.
                raise ValueError(
                    f"{attacker_id} damage event {event.get('source_key', '')!r} "
                    "has no sequence; the walk's tie-break order would depend on "
                    "event-id numbering"
                )
            # The engine ledger writes these five fields unconditionally
            # (damage.add / add_declared_events), so index them directly.
            time_value = event["time"]
            sequence = event["sequence"]
            source_key = event["source_key"]
            damage_type = event["damage_type"]
            damage = event["damage"]
            raw_formula = event.get("raw_formula")
            raw_damage = float(event.get("raw_damage", 0.0) or 0.0)
            if index < known_ids:
                event_id = id_strings[index]
            else:
                event_id = f"{attacker_id}:{defender_id}:{index}"
                id_strings.append(event_id)
                known_ids += 1
            live_formula = (
                raw_formula if callable(raw_formula) and raw_damage > 0 else None
            )
            grievous = grievous_by_dtype.get(damage_type)
            actions_append(
                (
                    (
                        time_value,
                        0.0,
                        sequence,
                        order_a,
                        order_b,
                        defender_id,
                        event_id,
                        str(event.get("source", source_key)),
                    ),
                    (
                        _KIND_PLAIN_DAMAGE
                        if live_formula is None and grievous is None
                        else _KIND_DAMAGE
                    ),
                    defender_i,
                    attacker_i,
                    -1,
                    aidx,
                    damage if damage > 0.0 else 0.0,
                    _DTYPE_CODES.get(damage_type, 2),
                    live_formula,
                    raw_damage,
                    grievous,
                    None,
                    False,
                    time_value,
                )
            )
            if time_value <= duration:
                order_append((aidx, time_value))
            if aidx_by_key is not None:
                aidx_by_key[(source_key, round(time_value, 9), sequence)] = aidx
                aidx_by_source_time[(source_key, round(time_value, 9))].append(aidx)
            if source_key == "auto_attacks" or event.get("basic_attack"):
                strikes_append((aidx, time_value, sequence, attacker_i))
            aidx += 1
        self.next_aidx = aidx
        for heal_index, event in enumerate(heals):
            trigger = aidx_by_key.get(_heal_trigger_key(event), -1)
            if trigger < 0:
                candidates = aidx_by_source_time.get(
                    (
                        str(event.get("_trigger_source", "")),
                        round(float(event.get("_trigger_time", 0.0)), 9),
                    ),
                    [],
                )
                if len(candidates) == 1:
                    trigger = candidates[0]
            if event.get("actor_wide"):
                if "_trigger_source" in event:
                    # Same invariant as add_packet's dedup above.
                    raise ValueError(
                        "actor-wide self-heal carries a trigger link; "
                        "the panel compiler cannot deduplicate it"
                    )
                dedup_key = (
                    str(event.get("source", "")),
                    float(event.get("time", 0.0)),
                )
                amount = max(0.0, float(event.get("amount", 0.0)))
                kept = heal_dedup.get(dedup_key)
                if kept is not None:
                    if kept != amount:
                        raise ValueError(
                            "actor-wide self-heal copies disagree across "
                            "pair fights; the compiled dedup cannot keep one"
                        )
                    continue
                heal_dedup[dedup_key] = amount
            aidx = self.next_aidx
            self.next_aidx += 1
            time_value = float(event.get("time", 0.0))
            actions_append(
                (
                    (
                        time_value,
                        1.0,
                        _event_sequence(event),
                        *source_order,
                        attacker_id,
                        f"{attacker_id}:{defender_id}:heal:{heal_index}",
                        str(event.get("source", event.get("source_key", ""))),
                    ),
                    _KIND_HEAL,
                    attacker_i,
                    attacker_i,
                    trigger,
                    aidx,
                    max(0.0, float(event.get("amount", 0.0))),
                    2,
                    event.get("amount_formula"),
                    0.0,
                    None,
                    (
                        max(
                            0.0,
                            float(event.get("temporary_health_duration", 0.0) or 0.0),
                        )
                        if event.get("overheal_to_temporary_health")
                        else None
                    ),
                    False,
                    time_value,
                )
            )
        self.coverage.append(result.get("timeline_coverage", {}))

    def add_support_templates(
        self,
        templates: Iterable[Mapping[str, Any]],
        attacker_i: int,
        index_of: Mapping[str, int],
    ) -> None:
        """Compile one attacker's resolved support packets."""
        for template in templates:
            target_id = str(template["target"])
            subject_i = index_of[target_id]
            kind = str(template.get("kind", ""))
            priority = -1.0 if kind == "shield" else 1.0
            if template.get("_trigger_event_id") is not None:
                # No current support author emits a trigger link; resolving
                # one would need the same cross-pair id map as heals, so
                # fail closed instead of silently skipping what the legacy
                # walk might apply.
                raise ValueError(
                    "support template carries a trigger link; the compiled "
                    "walk cannot resolve it"
                )
            aidx = self.next_aidx
            self.next_aidx += 1
            time_value = float(template.get("time", 0.0))
            self.actions.append(
                (
                    _action_key(time_value, priority, target_id, template),
                    _KIND_SHIELD if kind == "shield" else _KIND_HEAL,
                    subject_i,
                    attacker_i,
                    -1,
                    aidx,
                    max(0.0, float(template.get("amount", 0.0))),
                    2,
                    None,
                    0.0,
                    None,
                    None,
                    False,
                    time_value,
                )
            )
            self.support_entries.append((target_id, attacker_i, aidx, kind == "heal"))

    def add_thorns(
        self,
        wearer: Combatant,
        wearer_i: int,
        strikes: Iterable[tuple[int, float, int, Combatant, str]],
        profiles: tuple[ThornsEffect, ...],
        grievous_by_dtype: Mapping[str, Any],
        duration: float,
        id_namespace: str,
    ) -> None:
        """Compile the wearer's strike-back events for a run of strikes.

        ``strikes`` carries ``(strike_aidx, time, sequence, striker,
        striker_i)`` in the legacy incoming-list order.  The synthetic
        event-id string participates only in the sort key, where every pair
        of distinct thorns events already differs at the sequence or
        participant component, so panel and fresh namespaces may number
        independently without affecting order.
        """
        actions = self.actions
        order = self.thorns_order[wearer_i]
        wearer_order = _participant_order(wearer.participant_id)
        return_damage: dict[tuple[str, int], float] = {}
        for index, (
            strike_aidx,
            strike_time,
            strike_sequence,
            striker,
            striker_i,
        ) in enumerate(strikes):
            for profile in profiles:
                damage_key = (profile.item_name, striker_i)
                damage = return_damage.get(damage_key)
                if damage is None:
                    damage = _thorns_return_damage(profile, wearer, striker)
                    return_damage[damage_key] = damage
                aidx = self.next_aidx
                self.next_aidx += 1
                sort_key = (
                    strike_time,
                    0.5,
                    strike_sequence,
                    *wearer_order,
                    striker.participant_id,
                    (
                        f"{wearer.participant_id}:{striker.participant_id}"
                        f":thorns:{profile.item_name}:{id_namespace}{index}"
                    ),
                    f"{profile.item_name} (Thorns)",
                )
                actions.append(
                    (
                        sort_key,
                        _KIND_DAMAGE,
                        striker_i,
                        wearer_i,
                        strike_aidx,
                        aidx,
                        max(0.0, damage),
                        _DTYPE_CODES.get(profile.damage_type, 2),
                        None,
                        0.0,
                        grievous_by_dtype.get(profile.damage_type),
                        (
                            (profile.grievous_duration, f"{profile.item_name} · Thorns")
                            if profile.grievous_duration > 0
                            else None
                        ),
                        True,
                        strike_time,
                    )
                )
                if strike_time <= duration:
                    order.append((aidx, strike_time))


class CoupledSearchContext:
    """Reusable composition state for one coupled optimizer search.

    Everything here is derived from the fixed request — the roster, the
    fight params, and per-defensive-signature panels of compiled invariant
    walk actions — so it must only ever be shared across evaluations of one
    ``optimize_build`` call.  It is pure speed: force-disabling it must
    reproduce identical results (pinned by the optimizer equivalence test).
    """

    __slots__ = (
        "panels",
        "roster_actors",
        "actor_params",
        "main_request",
        "index_of",
        "grievous_packs",
        "thorns_profiles",
        "main_pair_params",
        "roster_pair_params",
        "pair_id_strings",
        "base_compiler",
        "base_sorted",
        "base_heal_dedup",
        "validated_roster_window",
    )

    def __init__(self) -> None:
        self.panels: dict[tuple[Any, ...], "_SignaturePanel"] = {}
        self.roster_actors: list[Combatant] | None = None
        self.actor_params: dict[str, FightParams] = {}
        self.main_request: Any = None
        self.index_of: dict[str, int] = {}
        self.grievous_packs: dict[int, dict[str, Any]] = {}
        self.thorns_profiles: dict[int, tuple[ThornsEffect, ...]] = {}
        self.main_pair_params: list[tuple[Combatant, FightParams]] = []
        self.roster_pair_params: dict[tuple[str, str], FightParams] = {}
        self.pair_id_strings: dict[str, list[str]] = defaultdict(list)
        self.base_compiler: _WalkCompiler | None = None
        self.base_sorted: list[tuple[Any, ...]] = []
        self.base_heal_dedup: dict[int, dict[tuple[str, float], float]] = {}
        self.validated_roster_window = False


class _SignaturePanel:
    """The invariant walk actions for one main defensive signature.

    ``sig`` holds only the fights into this signature (enemies into the
    candidate main); everything signature-independent lives in the search
    context's base compiler.  ``sorted_actions`` is the presorted merge of
    both.
    """

    __slots__ = ("sig", "n_actions", "sorted_actions")

    def __init__(self, base_sorted: list[tuple[Any, ...]], sig: _WalkCompiler) -> None:
        self.sig = sig
        self.n_actions = sig.next_aidx
        merged = base_sorted + sorted(sig.actions, key=itemgetter(0))
        merged.sort(key=itemgetter(0))
        self.sorted_actions = merged


def _grievous_packs_for(
    context: CoupledSearchContext, actor_i: int, profiles: tuple[Any, ...]
) -> dict[str, Any]:
    """Per-damage-type Grievous packs for one attacker's fixed profiles."""
    packs = context.grievous_packs.get(actor_i)
    if packs is None:
        packs = {
            damage_type: _grievous_pack(profiles, damage_type)
            for damage_type in ("physical", "magic", "true")
        }
        context.grievous_packs[actor_i] = packs
    return packs


def _compiled_survival_walk(
    actions: list[tuple[Any, ...]],
    n_actions: int,
    max_healths: list[float],
    shield_triples: list[tuple[float, float, float]],
    duration: float,
    healing_received_multipliers: list[float],
) -> tuple[list[dict[str, Any]], list[float]]:
    """Run the flat-action survival walk.

    Arithmetic, operation order, and rounding mirror ``_simulate_survival``
    line for line; the only difference is representation — parallel arrays
    and one write-once ``applied`` array instead of mutated event dicts.
    """
    count = len(max_healths)
    max_healths = list(max_healths)
    health = list(max_healths)
    sh_physical = [triple[0] for triple in shield_triples]
    sh_magic = [triple[1] for triple in shield_triples]
    sh_general = [triple[2] for triple in shield_triples]
    damage_taken = [0.0] * count
    overkill = [0.0] * count
    health_damage = [0.0] * count
    shield_absorbed = [0.0] * count
    healing_received = [0.0] * count
    overhealing = [0.0] * count
    healing_reduced = [0.0] * count
    support_shield_received = [0.0] * count
    support_shield_expired = [0.0] * count
    temporary_health_received = [0.0] * count
    temporary_health_amount = [0.0] * count
    temporary_health_until = [0.0] * count
    temporary_health_expired_at: list[float | None] = [None] * count
    temporary_health_source = [""] * count
    hr_until = [0.0] * count
    hr_factor = [1.0] * count
    hr_sources: list[set[str]] = [set() for _ in range(count)]
    hr_events: list[list[dict[str, Any]]] = [[] for _ in range(count)]
    death: list[float | None] = [None] * count

    applied = [0.0] * n_actions
    status = bytearray(n_actions)

    # Hot loop: actions are read by index (see _WalkCompiler's tuple
    # layout) so the common skip paths never unpack the full row.  Plain
    # damage — no trigger, no repricing, no Grievous, no wound — is most
    # of the stream and takes the first branch without reading any of the
    # four fields it cannot carry.
    for action in actions:
        subject_i = action[_A_SUBJECT]
        time_value = action[_A_TIME]
        # The authoritative event walk keeps post-window packets visible in
        # receipts but never applies them.  The compiled score walk has no
        # receipt annotation, so skip them before any state mutation while
        # leaving their applied slot at zero.
        if time_value > duration:
            continue
        if time_value >= hr_until[subject_i] and hr_until[subject_i] > 0.0:
            hr_factor[subject_i] = 1.0
            hr_sources[subject_i].clear()
        if (
            temporary_health_amount[subject_i] > 0.0
            and temporary_health_until[subject_i] > 0.0
            and time_value >= temporary_health_until[subject_i]
        ):
            expired = temporary_health_amount[subject_i]
            max_healths[subject_i] = max(0.0, max_healths[subject_i] - expired)
            health[subject_i] = min(health[subject_i], max_healths[subject_i])
            temporary_health_amount[subject_i] = 0.0
            temporary_health_expired_at[subject_i] = round(
                temporary_health_until[subject_i], 3
            )
            temporary_health_until[subject_i] = 0.0
        kind = action[_A_KIND]
        if kind == _KIND_PLAIN_DAMAGE:
            if death[subject_i] is not None:
                continue
            attacker_i = action[_A_ATTACKER]
            if death[attacker_i] is not None:
                continue
            aidx = action[_A_AIDX]
            status[aidx] = 1
            amount = action[_A_AMOUNT]
            damage_taken[subject_i] += amount
            event_absorbed = 0.0
            dtype = action[_A_DTYPE]
            if dtype == 1:
                absorbed = min(sh_magic[subject_i], amount)
                sh_magic[subject_i] -= absorbed
                amount -= absorbed
                shield_absorbed[subject_i] += absorbed
                event_absorbed += absorbed
            elif dtype == 0:
                absorbed = min(sh_physical[subject_i], amount)
                sh_physical[subject_i] -= absorbed
                amount -= absorbed
                shield_absorbed[subject_i] += absorbed
                event_absorbed += absorbed
            general_absorbed = min(sh_general[subject_i], amount)
            sh_general[subject_i] -= general_absorbed
            amount -= general_absorbed
            shield_absorbed[subject_i] += general_absorbed
            event_absorbed += general_absorbed
            applied_to_health = min(amount, health[subject_i])
            overkill[subject_i] += max(0.0, amount - applied_to_health)
            health[subject_i] = max(0.0, health[subject_i] - applied_to_health)
            health_damage[subject_i] += applied_to_health
            applied[aidx] = round(event_absorbed + applied_to_health, 6)
            if health[subject_i] <= 0.0 and death[subject_i] is None:
                death[subject_i] = min(float(duration), action[_A_TIME])
            continue
        trigger = action[_A_TRIGGER]
        if trigger != -1 and (trigger < 0 or not status[trigger]):
            continue
        subject_i = action[_A_SUBJECT]
        if death[subject_i] is not None:
            continue
        attacker_i = action[_A_ATTACKER]
        if (
            attacker_i >= 0
            and death[attacker_i] is not None
            and not action[_A_REACTIVE]
        ):
            continue
        amount = action[_A_AMOUNT]
        if kind == _KIND_SHIELD:
            amount *= healing_received_multipliers[subject_i]
            sh_general[subject_i] += amount
            support_shield_received[subject_i] += amount
            applied[action[_A_AIDX]] = round(amount, 6)
            continue
        if kind == _KIND_HEAL:
            time_value = action[_A_TIME]
            amount_formula = action[_A_RAW_FORMULA]
            if callable(amount_formula):
                amount = max(
                    0.0,
                    float(amount_formula(health[subject_i], max_healths[subject_i])),
                )
            amount *= healing_received_multipliers[subject_i]
            factor = 1.0 if time_value >= hr_until[subject_i] else hr_factor[subject_i]
            reduced = amount * factor
            healing_reduced[subject_i] += max(0.0, amount - reduced)
            received = min(
                reduced, max(0.0, max_healths[subject_i] - health[subject_i])
            )
            excess = max(0.0, reduced - received)
            temporary_duration = max(0.0, float(action[_A_WOUND] or 0.0))
            temporary_health = (
                excess if temporary_duration > 0.0 and excess > 0.0 else 0.0
            )
            overhealing[subject_i] += excess - temporary_health
            health[subject_i] += received
            healing_received[subject_i] += received
            if temporary_health > 0.0:
                max_healths[subject_i] += temporary_health
                health[subject_i] += temporary_health
                temporary_health_received[subject_i] += temporary_health
                temporary_health_amount[subject_i] += temporary_health
                temporary_health_until[subject_i] = max(
                    temporary_health_until[subject_i],
                    time_value + temporary_duration,
                )
                temporary_health_source[subject_i] = str(action[0][-1])
            applied[action[_A_AIDX]] = round(received, 6)
            continue

        aidx = action[_A_AIDX]
        time_value = action[_A_TIME]
        status[aidx] = 1
        raw_formula = action[_A_RAW_FORMULA]
        if raw_formula is not None:
            subject_max = max_healths[subject_i]
            if subject_max > 0:
                missing_ratio = max(
                    0.0, min(1.0, 1.0 - health[subject_i] / subject_max)
                )
                raw_damage = action[_A_RAW_DAMAGE]
                try:
                    live_raw = _evaluate_live_raw_formula(
                        raw_formula, missing_ratio, subject_max
                    )
                except (TypeError, ValueError):
                    live_raw = raw_damage
                amount *= live_raw / raw_damage
        damage_taken[subject_i] += amount
        event_absorbed = 0.0
        dtype = action[_A_DTYPE]
        if dtype == 1:
            absorbed = min(sh_magic[subject_i], amount)
            sh_magic[subject_i] -= absorbed
            amount -= absorbed
            shield_absorbed[subject_i] += absorbed
            event_absorbed += absorbed
        elif dtype == 0:
            absorbed = min(sh_physical[subject_i], amount)
            sh_physical[subject_i] -= absorbed
            amount -= absorbed
            shield_absorbed[subject_i] += absorbed
            event_absorbed += absorbed
        general_absorbed = min(sh_general[subject_i], amount)
        sh_general[subject_i] -= general_absorbed
        amount -= general_absorbed
        shield_absorbed[subject_i] += general_absorbed
        event_absorbed += general_absorbed
        applied_to_health = min(amount, health[subject_i])
        event_overkill = max(0.0, amount - applied_to_health)
        health[subject_i] = max(0.0, health[subject_i] - applied_to_health)
        health_damage[subject_i] += applied_to_health
        overkill[subject_i] += event_overkill
        event_damage = round(event_absorbed + applied_to_health, 6)
        applied[aidx] = event_damage
        grievous = action[_A_GRIEVOUS]
        if grievous is not None and event_damage > 0:
            strongest_factor, strongest_duration, labels = grievous
            hr_until[subject_i] = max(
                hr_until[subject_i], time_value + strongest_duration
            )
            hr_factor[subject_i] = min(hr_factor[subject_i], strongest_factor)
            hr_sources[subject_i].update(labels)
            hr_events[subject_i].append(
                {
                    "time": round(time_value, 3),
                    "until": round(hr_until[subject_i], 3),
                    "factor": round(hr_factor[subject_i], 6),
                    "sources": sorted(hr_sources[subject_i]),
                }
            )
        wound = action[_A_WOUND]
        if wound is not None:
            wound_duration, wound_label = wound
            hr_until[subject_i] = max(hr_until[subject_i], time_value + wound_duration)
            hr_factor[subject_i] = min(hr_factor[subject_i], GRIEVOUS_WOUNDS_FACTOR)
            hr_sources[subject_i].add(wound_label)
            hr_events[subject_i].append(
                {
                    "time": round(time_value, 3),
                    "until": round(hr_until[subject_i], 3),
                    "factor": round(hr_factor[subject_i], 6),
                    "sources": sorted(hr_sources[subject_i]),
                }
            )
        if health[subject_i] <= 0.0 and death[subject_i] is None:
            death[subject_i] = min(float(duration), time_value)

    survival_rows = []
    for index in range(count):
        if (
            temporary_health_amount[index] > 0.0
            and temporary_health_until[index] > 0.0
            and duration >= temporary_health_until[index]
        ):
            expired = temporary_health_amount[index]
            max_healths[index] = max(0.0, max_healths[index] - expired)
            health[index] = min(health[index], max_healths[index])
            temporary_health_amount[index] = 0.0
            temporary_health_expired_at[index] = round(temporary_health_until[index], 3)
            temporary_health_until[index] = 0.0
        triple = shield_triples[index]
        starting_shield = triple[0] + triple[1] + triple[2]
        remaining_shields = sh_physical[index] + sh_magic[index] + sh_general[index]
        survival_rows.append(
            {
                "max_health": round(max_healths[index], 1),
                "ending_health": round(health[index], 1),
                "ending_health_ratio": round(
                    (
                        health[index] / max_healths[index]
                        if max_healths[index] > 0.0
                        else 0.0
                    ),
                    6,
                ),
                "damage_taken": round(damage_taken[index], 1),
                "overkill": round(overkill[index], 1),
                "health_damage": round(health_damage[index], 1),
                "shield_absorbed": round(shield_absorbed[index], 1),
                "healing_received": round(healing_received[index], 1),
                "overhealing": round(overhealing[index], 1),
                "healing_reduced": round(healing_reduced[index], 1),
                "support_shield_received": round(support_shield_received[index], 1),
                "support_shield_expired": round(support_shield_expired[index], 1),
                "effective_health": round(
                    max_healths[index]
                    + starting_shield
                    + support_shield_received[index]
                    - support_shield_expired[index]
                    + healing_received[index],
                    1,
                ),
                "remaining_shield": round(remaining_shields, 1),
                "starting_shield": round(starting_shield, 1),
                "healing_reduction_until": round(hr_until[index], 3),
                "healing_reduction_sources": sorted(hr_sources[index]),
                "survived_window": death[index] is None,
                "death_time": (
                    round(death[index], 3) if death[index] is not None else None
                ),
                # The compiled score walk currently has no state-transition
                # packets in its invariant panel.  Keep its public shape
                # aligned with the event walk; once a state packet enters a
                # search context the context is intentionally bypassed by the
                # caller rather than silently dropping the transition.
                "first_death_time": (
                    round(death[index], 3) if death[index] is not None else None
                ),
                "revived": False,
                "revive_time": None,
                "revive_health_restored": 0.0,
                "revive_source": "",
                "terminal_phase": "dead" if death[index] is not None else "alive",
                "execute_time": None,
                "execute_source": "",
                "stasis_until": 0.0,
                "stasis_started_at": None,
                "stasis_source": "",
                "force_of_nature": {
                    "stacks": 0,
                    "stacks_until": 0.0,
                    "events": [],
                    "dynamic_bonus_magic_resistance": 0.0,
                },
                "jaksho": {
                    "stacks": 0,
                    "events": [],
                    "dynamic_bonus_armor": 0.0,
                    "dynamic_bonus_magic_resistance": 0.0,
                },
                "invulnerable_until": 0.0,
                "untargetable_until": 0.0,
                "spell_shield_used": False,
                "spell_shield_source": "",
                "spell_shield_until": 0.0,
                "temporary_health_received": round(temporary_health_received[index], 1),
                "temporary_health_until": round(temporary_health_until[index], 3),
                "temporary_health_expired_at": temporary_health_expired_at[index],
                "temporary_health_source": temporary_health_source[index],
                "threshold_shield_triggered": False,
                "threshold_shield_expired_at": None,
                "threshold_health_triggered": False,
                "damage_deferral_fraction": 0.0,
                "damage_deferral_pending": 0.0,
                "damage_deferral_cleared": 0.0,
                "defy_triggered": False,
                "defy_trigger_time": None,
                "defy_heal_received": 0.0,
                "healing_reduction_events": list(hr_events[index]),
            }
        )
    return survival_rows, applied


def _context_setup(
    context: CoupledSearchContext,
    params: FightParams,
    enemies: list[ResolvedLoadout],
    allies: list[ResolvedLoadout],
    champion_name: str,
    level: int,
    pair_result_cache: dict[tuple[Any, ...], dict[str, Any]],
    all_actors_by_index: list[Combatant],
) -> None:
    """Derive the search-invariant roster state on the context's first use.

    Everything prebuilt here is per-pair, not per-candidate: actor and
    target fight params (with ``enforce_resource_limits`` pre-set so the
    engine's own forcing replace becomes a no-op), their one-time
    ``validate_for_champion`` runs, thorns profiles, and Grievous packs.
    """
    if context.roster_actors is not None:
        return
    if not context.validated_roster_window:
        require_roster_fight_window_support(params, enemies=enemies, allies=allies)
        context.validated_roster_window = True
    ally_actors = [
        _from_loadout(f"ally:{loadout.champion_data['name']}", "ally", loadout)
        for loadout in allies
    ]
    enemy_actors = [
        _from_loadout(f"enemy:{loadout.champion_data['name']}", "enemy", loadout)
        for loadout in enemies
    ]
    context.roster_actors = [*ally_actors, *enemy_actors]
    context.index_of = {"main": 0}
    for offset, actor in enumerate(context.roster_actors, start=1):
        context.index_of[actor.participant_id] = offset
        context.actor_params[actor.participant_id] = _actor_params(params, actor)
        context.thorns_profiles[offset] = thorns_effects(list(actor.items))
        _grievous_packs_for(context, offset, healing_reduction_profiles(actor.items))
    context.main_request = type(
        "MainRequest",
        (),
        {
            "role": params.role,
            "role_quest_complete": params.role_quest_complete,
            "ability_ranks": params.ability_ranks,
            "champion_options": params.champion_options,
            "cast_order": params.cast_order,
            "item_options": params.item_options,
        },
    )()
    main_params = _actor_params(
        params,
        Combatant(
            participant_id="main",
            team="main",
            champion_data={},
            level=0,
            items=(),
            stats={},
            defenses=None,
            request=context.main_request,
        ),
    )
    context.actor_params["main"] = main_params
    for defender in enemy_actors:
        pair_params = replace(
            main_params,
            enforce_resource_limits=True,
            **_target_overrides(defender),
        )
        pair_params.validate_for_champion(champion_name, level)
        context.main_pair_params.append((defender, pair_params))
    for attacker in context.roster_actors:
        attacker_params = context.actor_params[attacker.participant_id]
        attacker_params.validate_for_champion(
            str(attacker.champion_data.get("name", "")), attacker.level
        )
        defenders = enemy_actors if attacker.team == "ally" else ally_actors
        for defender in defenders:
            context.roster_pair_params[
                (attacker.participant_id, defender.participant_id)
            ] = replace(
                attacker_params,
                enforce_resource_limits=True,
                **_target_overrides(defender),
            )

    # The signature-independent pair fights — allies into enemies, enemies
    # into allies — compile once for the whole search.  Enemy attackers'
    # support packets and their fights into the candidate main are
    # signature-dependent and live in each signature's sig compiler.
    base = _WalkCompiler(0)
    context.base_heal_dedup = {
        context.index_of[actor.participant_id]: {} for actor in context.roster_actors
    }
    support_attached: set[str] = set()
    base_pairs = [
        (attacker, defender) for attacker in ally_actors for defender in enemy_actors
    ] + [(attacker, defender) for attacker in enemy_actors for defender in ally_actors]
    for attacker, defender in base_pairs:
        cache_key = (attacker.participant_id, defender.participant_id)
        packet = pair_result_cache.get(cache_key)
        if packet is None:
            packet = _pair_packet(
                run_fight(
                    attacker.champion_data,
                    attacker.level,
                    list(attacker.items),
                    context.roster_pair_params[cache_key],
                    validated=True,
                ),
                attacker.participant_id,
                defender.participant_id,
            )
            pair_result_cache[cache_key] = packet
        attacker_i = context.index_of[attacker.participant_id]
        base.add_packet(
            packet,
            attacker_i,
            context.index_of[defender.participant_id],
            context.grievous_packs[attacker_i],
            params.fight_duration_seconds,
            context.base_heal_dedup[attacker_i],
        )
        if attacker.team == "ally" and attacker.participant_id not in support_attached:
            support_templates = packet.get("support")
            if support_templates is None:
                support_templates = _support_effect_templates(
                    attacker,
                    packet["result"],
                    all_actors_by_index,
                    damage_events=packet.get("events", ()),
                )
                packet["support"] = support_templates
            base.add_support_templates(support_templates, attacker_i, context.index_of)
            support_attached.add(attacker.participant_id)
    for actor in context.roster_actors:
        wearer_i = context.index_of[actor.participant_id]
        profiles = context.thorns_profiles[wearer_i]
        if not profiles:
            continue
        strikes = [
            (aidx, time_value, sequence, all_actors_by_index[striker_i], striker_i)
            for aidx, time_value, sequence, striker_i in (
                base.auto_strikes_into.get(wearer_i, ())
            )
        ]
        if strikes:
            base.add_thorns(
                actor,
                wearer_i,
                strikes,
                profiles,
                context.grievous_packs[wearer_i],
                params.fight_duration_seconds,
                "base",
            )
    context.base_compiler = base
    context.base_sorted = sorted(base.actions, key=itemgetter(0))


def _build_signature_panel(
    context: CoupledSearchContext,
    main: Combatant,
    params: FightParams,
    pair_result_cache: dict[tuple[Any, ...], dict[str, Any]],
    signature: tuple[Any, ...],
    all_actors: list[Combatant],
) -> "_SignaturePanel":
    """Compile every roster pair fight for one main defensive signature.

    Pair packets come from (or land in) the shared ``pair_result_cache``
    with the same keys the legacy path uses, so both paths interoperate.
    Compilation order mirrors the legacy attack-group order with the main
    attacker's fresh pairs skipped: allies into enemies, then enemies into
    the main and allies.
    """
    duration = params.fight_duration_seconds
    base = context.base_compiler
    assert base is not None, "context setup must precede panel builds"
    sig = _WalkCompiler(base.next_aidx)
    roster = context.roster_actors or []
    enemy_actors = [actor for actor in roster if actor.team == "enemy"]
    for attacker in enemy_actors:
        cache_key = (attacker.participant_id, "main", signature)
        packet = pair_result_cache.get(cache_key)
        if packet is None:
            packet = _pair_packet(
                run_fight(
                    attacker.champion_data,
                    attacker.level,
                    list(attacker.items),
                    replace(
                        context.actor_params[attacker.participant_id],
                        enforce_resource_limits=True,
                        **_target_overrides(main),
                    ),
                    validated=True,
                ),
                attacker.participant_id,
                "main",
            )
            pair_result_cache[cache_key] = packet
        attacker_i = context.index_of[attacker.participant_id]
        # Actor-wide heals must dedup across this attacker's base pairs
        # too, but a sig build may never grow the shared base sets: a key
        # recorded by one signature would silently drop another
        # signature's only copy of that heal.
        sig.add_packet(
            packet,
            attacker_i,
            0,
            context.grievous_packs[attacker_i],
            duration,
            dict(context.base_heal_dedup.get(attacker_i) or {}),
        )
        support_templates = packet.get("support")
        if support_templates is None:
            support_templates = _support_effect_templates(
                attacker,
                packet["result"],
                all_actors,
                damage_events=packet.get("events", ()),
            )
            packet["support"] = support_templates
        sig.add_support_templates(support_templates, attacker_i, context.index_of)
    return _SignaturePanel(context.base_sorted, sig)


def _score_with_search_context(
    champion_data: dict[str, Any],
    level: int,
    items: list[dict[str, Any]],
    params: FightParams,
    *,
    main_stats: dict[str, float],
    main_defenses: Any,
    enemies: list[ResolvedLoadout],
    allies: list[ResolvedLoadout],
    pair_result_cache: dict[tuple[Any, ...], dict[str, Any]],
    context: CoupledSearchContext,
    reuse_main_stats: bool,
) -> dict[str, Any]:
    """Score one candidate through the compiled panel walk.

    Returns the exact score-only receipt ``build_participant_timeline``
    would produce — same fields, same rounding, same float-addition order,
    and the same rounded death-time cutoff on each attacker's outgoing
    total — while compiling only the main champion's fresh outgoing
    fights.
    """
    if context.roster_actors is None:
        setup_allies = [
            _from_loadout(f"ally:{loadout.champion_data['name']}", "ally", loadout)
            for loadout in allies
        ]
        setup_enemies = [
            _from_loadout(f"enemy:{loadout.champion_data['name']}", "enemy", loadout)
            for loadout in enemies
        ]
        placeholder = Combatant(
            participant_id="main",
            team="main",
            champion_data=champion_data,
            level=level,
            items=tuple(items),
            stats=main_stats,
            defenses=main_defenses,
            request=None,
        )
        _context_setup(
            context,
            params,
            enemies,
            allies,
            str(champion_data.get("name", "")),
            level,
            pair_result_cache,
            [placeholder, *setup_allies, *setup_enemies],
        )
    duration = params.fight_duration_seconds
    main = Combatant(
        participant_id="main",
        team="main",
        champion_data=champion_data,
        level=level,
        items=tuple(items),
        stats=main_stats,
        defenses=main_defenses,
        request=context.main_request,
    )
    roster = context.roster_actors or []
    all_actors = [main, *roster]
    signature = _defensive_signature(main)
    panel = context.panels.get(signature)
    if panel is None:
        panel = _build_signature_panel(
            context, main, params, pair_result_cache, signature, all_actors
        )
        context.panels[signature] = panel

    fresh = _WalkCompiler(panel.n_actions)
    main_profiles = healing_reduction_profiles(main.items)
    main_packs = {
        damage_type: _grievous_pack(main_profiles, damage_type)
        for damage_type in ("physical", "magic", "true")
    }
    reusable_stats = main.stats if reuse_main_stats else None
    heal_dedup: dict[tuple[str, float], float] = {}
    first_result = None
    enemy_actors = [actor for actor in roster if actor.team == "enemy"]
    for defender, pair_params in context.main_pair_params:
        result = run_fight(
            main.champion_data,
            main.level,
            list(main.items),
            pair_params,
            precomputed_stats=reusable_stats,
            validated=True,
            score_only=True,
        )
        if first_result is None:
            first_result = result
        fresh.add_engine_result(
            result,
            "main",
            0,
            defender.participant_id,
            context.index_of[defender.participant_id],
            main_packs,
            duration,
            heal_dedup,
            context.pair_id_strings[defender.participant_id],
        )
    if first_result is not None:
        fresh.add_support_templates(
            _support_effect_templates(main, first_result, all_actors),
            0,
            context.index_of,
        )
    # Thorns from this candidate's fresh strikes (enemy wearers), then the
    # candidate's own thorns items struck by the invariant roster autos.
    for defender in enemy_actors:
        wearer_i = context.index_of[defender.participant_id]
        profiles = context.thorns_profiles[wearer_i]
        if not profiles:
            continue
        strikes = [
            (aidx, time_value, sequence, main, 0)
            for aidx, time_value, sequence, _striker_i in (
                fresh.auto_strikes_into.get(wearer_i, ())
            )
        ]
        if strikes:
            fresh.add_thorns(
                defender,
                wearer_i,
                strikes,
                profiles,
                context.grievous_packs[wearer_i],
                duration,
                "fresh",
            )
    main_thorns = thorns_effects(list(main.items))
    if main_thorns:
        strikes = [
            (aidx, time_value, sequence, all_actors[striker_i], striker_i)
            for aidx, time_value, sequence, striker_i in (
                panel.sig.auto_strikes_into.get(0, ())
            )
        ]
        if strikes:
            fresh.add_thorns(
                main, 0, strikes, main_thorns, main_packs, duration, "fresh"
            )

    actions = panel.sorted_actions + sorted(fresh.actions, key=itemgetter(0))
    actions = _coalesce_compiled_darius_q_heals(actions)
    actions.sort(key=itemgetter(0))
    max_healths = [
        max(0.0, float(actor.stats.get("health", 0.0))) for actor in all_actors
    ]
    shield_triples = []
    healing_received_multipliers = []
    for actor in all_actors:
        defenses = _participant_defenses(actor.defenses)
        shield_triples.append(
            (
                defenses["physical_shield"],
                defenses["magic_shield"],
                defenses["general_shield"],
            )
        )
        healing_received_multipliers.append(
            max(
                1.0,
                float(
                    getattr(actor.defenses, "healing_received_multiplier", 1.0) or 1.0
                ),
            )
        )
    survival_rows, applied = _compiled_survival_walk(
        actions,
        fresh.next_aidx,
        max_healths,
        shield_triples,
        duration,
        healing_received_multipliers,
    )
    for index, actor in enumerate(all_actors):
        survival_rows[index]["healing_reduction_events"] = [
            {"recipient": actor.participant_id, **event}
            for event in survival_rows[index].get("healing_reduction_events", [])
        ]

    count = len(all_actors)
    base = context.base_compiler
    support_value = [0.0] * count
    healing_output = [0.0] * count
    # Legacy attach order — main (fresh), allies (base), enemies (sig) —
    # decides both target-key insertion and per-target list order.
    by_target: dict[str, list[tuple[int, int, bool]]] = {}
    for target_id, attacker_i, aidx, is_heal in fresh.support_entries:
        by_target.setdefault(target_id, []).append((attacker_i, aidx, is_heal))
    for target_id, attacker_i, aidx, is_heal in base.support_entries:
        by_target.setdefault(target_id, []).append((attacker_i, aidx, is_heal))
    for target_id, attacker_i, aidx, is_heal in panel.sig.support_entries:
        by_target.setdefault(target_id, []).append((attacker_i, aidx, is_heal))
    for entries in by_target.values():
        for attacker_i, aidx, is_heal in entries:
            amount = applied[aidx]
            support_value[attacker_i] += amount
            if is_heal:
                healing_output[attacker_i] += amount

    public_breakdown = []
    sig_damage_order = panel.sig.damage_order
    base_damage_order = base.damage_order
    fresh_damage_order = fresh.damage_order
    fresh_thorns_order = fresh.thorns_order
    base_thorns_order = base.thorns_order
    for index, actor in enumerate(all_actors):
        # Per-attacker float-sum order replays the legacy outgoing list:
        # pair fights in defender order (enemies hit the main first, then
        # allies), then thorns in strike order (fresh strikes precede the
        # roster's).  One running total over the ordered parts keeps the
        # exact same addition sequence without building a concat list.
        # A dead attacker's total also replays the legacy cutoff against
        # its ROUNDED death time: the walk applies an attacker's own
        # event at the exact death instant, but the legacy sum excludes
        # it whenever the true death time rounds down past it.
        death_cutoff = survival_rows[index]["death_time"]
        running = 0.0
        for order in (
            sig_damage_order.get(index),
            base_damage_order.get(index),
            fresh_damage_order.get(index),
            fresh_thorns_order.get(index),
            base_thorns_order.get(index),
        ):
            if order:
                if death_cutoff is None:
                    for aidx, _event_time in order:
                        running += applied[aidx]
                else:
                    for aidx, event_time in order:
                        if event_time <= death_cutoff:
                            running += applied[aidx]
        total = round(running, 1)
        actor_survival = survival_rows[index]
        public_breakdown.append(
            {
                "participant_id": actor.participant_id,
                "team": actor.team,
                "champion": actor.champion_data.get("name", ""),
                "total_damage": round(float(total), 1),
                "sources": [],
                "outgoing_damage_before_death": round(float(total), 1),
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
                "support_value": round(support_value[index], 1),
                "healing_output": round(healing_output[index], 1),
                "survived_window": bool(actor_survival.get("survived_window")),
                "death_time": actor_survival.get("death_time"),
            }
        )
    coverage_reports = fresh.coverage + base.coverage + panel.sig.coverage
    return {
        "duration": float(duration),
        "participants": [
            {
                "participant_id": actor.participant_id,
                "team": actor.team,
                "champion": actor.champion_data.get("name", ""),
                "level": actor.level,
                "survival": survival_rows[index],
            }
            for index, actor in enumerate(all_actors)
        ],
        "breakdown": public_breakdown,
        "timeline_coverage": combine_timeline_coverages(
            coverage_reports,
            target_count=len(coverage_reports),
        ),
    }


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
    search_context: CoupledSearchContext | None = None,
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

    ``search_context`` opts scoring into the compiled panel walk: the
    optimizer creates one :class:`CoupledSearchContext` per search (fixed
    params and roster) and every score-mode evaluation then replays the
    presorted invariant actions instead of re-enriching them.  Identical
    numbers by construction and by test; ignored outside score mode.
    """
    if (
        search_context is not None
        and not include_receipt
        and pair_result_cache is not None
        and enemies
        and not _has_stateful_defense(main_defenses)
        and not any(_has_stateful_defense(loadout.defenses) for loadout in enemies)
        and not any(_has_stateful_defense(loadout.defenses) for loadout in allies)
        and not healing_reduction_profiles(items)
        and not any(
            healing_reduction_profiles(loadout.item_data) for loadout in enemies
        )
        and not any(healing_reduction_profiles(loadout.item_data) for loadout in allies)
        # Eclipse and Death's Dance carry ordered self-state that the compact
        # panel cannot represent (timed shields, deferral, and Defy).
        and not _has_ordered_item_defense(items)
        # Vamp, stat regeneration, and trigger-gated sustain packets carry
        # source categories/live state that the flat panel does not retain.
        and not _has_ordered_item_sustain(items)
        and not any(
            _has_ordered_item_defense(loadout.item_data)
            for loadout in (*enemies, *allies)
        )
        and not any(
            _has_ordered_item_sustain(loadout.item_data, include_warmog=False)
            or _has_active_warmog(loadout)
            for loadout in (*enemies, *allies)
        )
        # Ally/team packets carry timestamped shields, heals, stat buffs, and
        # debuffs.  The compact optimizer panel cannot apply those state
        # transitions without silently dropping a recipient, so use the
        # authoritative event walk whenever one is equipped in the roster.
        and not _has_ordered_item_team_effects(items, enemies, allies)
        # Collector is a terminal target-state transition, not a score-only
        # damage effect; keep it on the authoritative event walk.
        and not any(item.get("name") == "The Collector" for item in items)
    ):
        return _score_with_search_context(
            champion_data,
            level,
            items,
            params,
            main_stats=main_stats,
            main_defenses=main_defenses,
            enemies=enemies,
            allies=allies,
            pair_result_cache=pair_result_cache,
            context=search_context,
            reuse_main_stats=reuse_main_stats,
        )
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
    ordered_item_support_ids: set[str] = set()
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
            for defender_index, defender in enumerate(defenders):
                # Secondary-target item branches are allocated against the
                # current attacker group, not the outer request's default
                # single-target fields.  The ordered roster index is explicit
                # and deterministic: index 0 is the primary defender and
                # later indices are eligible secondary recipients.
                pair_params = replace(
                    actor_params,
                    roster_target_index=defender_index,
                    roster_target_count=len(defenders),
                )
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
                            _target_params(pair_params, defender),
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
                    shield_payload = enriched.get("self_shield")
                    shield_event_id = str(enriched.get("_event_id", ""))
                    if (
                        isinstance(shield_payload, Mapping)
                        and shield_event_id
                        and shield_event_id not in ordered_item_support_ids
                    ):
                        try:
                            shield_amount = max(0.0, float(shield_payload["amount"]))
                            shield_duration = max(
                                0.0, float(shield_payload["duration"])
                            )
                        except (KeyError, TypeError, ValueError):
                            # An incomplete parser receipt cannot be turned
                            # into a guessed defensive event.
                            shield_amount = 0.0
                            shield_duration = 0.0
                        if shield_amount > 0.0 and shield_duration > 0.0:
                            support_effects[attacker.participant_id].append(
                                {
                                    "time": float(enriched.get("time", 0.0)),
                                    "kind": "shield",
                                    "amount": shield_amount,
                                    "duration": shield_duration,
                                    "source": str(
                                        shield_payload.get(
                                            "source", "Eclipse (Ever Rising Moon)"
                                        )
                                    ),
                                    "source_key": "shield_Eclipse",
                                    "attacker": attacker.participant_id,
                                    "target": attacker.participant_id,
                                    "target_scope": "self",
                                    "target_policy": "self",
                                    "_event_id": f"{shield_event_id}:shield",
                                    "_trigger_event_id": shield_event_id,
                                    "_priority": 0.5,
                                }
                            )
                            ordered_item_support_ids.add(shield_event_id)
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
                            attacker,
                            result,
                            all_actors,
                            damage_events=packet.get("events", ()),
                            target_id=defender.participant_id,
                        )
                        packet["support"] = support_templates
                    for template in support_templates:
                        packet_template = dict(template) if copy_templates else template
                        support_effects[template["target"]].append(packet_template)
                        if template.get("kind") == "damage":
                            outgoing[template["attacker"]].append(packet_template)
                            incoming[template["target"]].append(packet_template)
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
        _attach_support_effects(
            attacker,
            fallback,
            all_actors,
            support_effects,
            outgoing,
            incoming,
        )
        support_attached.add(attacker.participant_id)

    # Knight's Vow is the one ally packet whose trigger lives on the
    # recipient's incoming/outgoing ledgers rather than on a heal/shield cast.
    # Resolve its single explicit Worthy tether after all pair events exist so
    # the redirect and holder-heal receipts share the same event order.
    schedule_knights_vow(all_actors, incoming, outgoing, support_effects)

    _coalesce_darius_q_heals(healing)
    _schedule_thorns_events(all_actors, incoming, outgoing)
    _schedule_authored_reactive_events(incoming, outgoing)

    survival = _simulate_survival(
        all_actors,
        incoming,
        healing,
        support_effects,
        params.fight_duration_seconds,
        annotate=include_receipt,
        receipt_events=outgoing if include_receipt else None,
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

    utility_by_actor = {
        actor.participant_id: _utility_outcome_receipt(
            actor,
            support_effects.get(actor.participant_id, []),
            outgoing.get(actor.participant_id, []),
        )
        for actor in all_actors
    }
    public_breakdown = []
    support_by_attacker: dict[str, float] = defaultdict(float)
    healing_by_attacker: dict[str, float] = defaultdict(float)
    for events in support_effects.values():
        for event in events:
            attacker_id = str(event.get("attacker", ""))
            applied = float(event.get("applied_amount", 0.0))
            if event.get("kind") == "damage":
                continue
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
                **(
                    {"utility_outcomes": utility_by_actor[actor.participant_id]}
                    if include_receipt
                    else {}
                ),
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
    public_events = sorted(
        (event for events in outgoing.values() for event in events),
        key=lambda event: event.get("_sk")
        or _action_key(
            float(event.get("time", 0.0)),
            0.5 if event.get("_reactive") else 0.0,
            str(event.get("target", "")),
            event,
        ),
    )
    public_healing_events = sorted(
        (event for events in healing.values() for event in events),
        key=lambda event: event.get("_sk")
        or _action_key(
            float(event.get("time", 0.0)),
            1.0,
            str(event.get("attacker", "")),
            event,
        ),
    )
    public_support_events = sorted(
        (event for events in support_effects.values() for event in events),
        key=lambda event: (
            float(event.get("time", 0.0)),
            -1.0 if event.get("kind") in {"shield", "temporary_health"} else 1.0,
            str(event.get("target", "")),
            str(event.get("attacker", "")),
            str(event.get("_event_id", "")),
        ),
    )
    support_by_actor = {
        actor.participant_id: [
            event
            for event in public_support_events
            if event.get("attacker") == actor.participant_id
        ]
        for actor in all_actors
    }
    outgoing_by_actor = {
        actor.participant_id: [
            event
            for event in public_events
            if event.get("attacker") == actor.participant_id
        ]
        for actor in all_actors
    }
    utility_by_actor = {
        actor.participant_id: _utility_outcome_receipt(
            actor,
            support_by_actor[actor.participant_id],
            outgoing_by_actor[actor.participant_id],
        )
        for actor in all_actors
    }
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
                    {"event_id": str(event["_event_id"])}
                    if event.get("_event_id") is not None
                    else {}
                ),
                **(
                    {"trigger_event_id": str(event["_trigger_event_id"])}
                    if event.get("_trigger_event_id") is not None
                    else {}
                ),
                **(
                    {"sequence": int(event["sequence"])}
                    if event.get("sequence") is not None
                    else {}
                ),
                **({"reactive": True} if event.get("_reactive") else {}),
                **(
                    {"spell_shield_source": str(event["spell_shield_source"])}
                    if event.get("spell_shield_source")
                    else {}
                ),
                **(
                    {"threshold_shield_triggered": True}
                    if event.get("threshold_shield_triggered")
                    else {}
                ),
                **(
                    {"threshold_health_triggered": True}
                    if event.get("threshold_health_triggered")
                    else {}
                ),
                **(
                    {"execute_triggered": True}
                    if event.get("execute_triggered")
                    else {}
                ),
                **(
                    {"redirected_amount": round(float(event["_redirected_amount"]), 1)}
                    if event.get("_redirected_amount") is not None
                    else {}
                ),
                **(
                    {"redirected_from": str(event["_redirected_from"])}
                    if event.get("_redirected_from")
                    else {}
                ),
                **(
                    {"redirect_fraction": round(float(event["_redirect_fraction"]), 6)}
                    if event.get("_redirect_fraction") is not None
                    else {}
                ),
                **(
                    {"redirect_source": str(event["redirect_source"])}
                    if event.get("redirect_source")
                    else {}
                ),
                **(
                    {"redirect_pre_mitigation": True}
                    if event.get("redirect_pre_mitigation")
                    else {}
                ),
                **(
                    {"redirect_attributed_to": str(event["redirect_attributed_to"])}
                    if event.get("redirect_attributed_to")
                    else {}
                ),
                **(
                    {"redirect_range_units": int(event["redirect_range_units"])}
                    if event.get("redirect_range_units") is not None
                    else {}
                ),
                **(
                    {"redirect_skipped_reason": str(event["redirect_skipped_reason"])}
                    if event.get("redirect_skipped_reason")
                    else {}
                ),
                **(
                    {
                        "support_damage_multiplier": dict(
                            event["support_damage_multiplier"]
                        )
                    }
                    if event.get("support_damage_multiplier")
                    else {}
                ),
                **(
                    {
                        "support_damage_reduction": dict(
                            event["support_damage_reduction"]
                        )
                    }
                    if event.get("support_damage_reduction")
                    else {}
                ),
                **(
                    {
                        "support_resistance_reduction": list(
                            event["support_resistance_reduction"]
                        )
                    }
                    if event.get("support_resistance_reduction")
                    else {}
                ),
                **(
                    {"support_on_hit_magic": list(event["support_on_hit_magic"])}
                    if event.get("support_on_hit_magic")
                    else {}
                ),
                **(
                    {"targeting": dict(event["targeting"])}
                    if isinstance(event.get("targeting"), Mapping)
                    else {}
                ),
                **(
                    {"deferred_from": str(event["_deferred_from"])}
                    if event.get("_deferred_from")
                    else {}
                ),
                **(
                    {"wound_source": str(event["_wound_source"])}
                    if event.get("_wound_source")
                    else {}
                ),
                **(
                    {
                        "wound_duration": round(float(event["grievous_duration"]), 3),
                        "wound_until": round(
                            float(
                                event.get(
                                    "_wound_until",
                                    float(event.get("time", 0.0))
                                    + float(event["grievous_duration"]),
                                )
                            ),
                            3,
                        ),
                    }
                    if event.get("grievous_duration") is not None
                    else {}
                ),
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
            for event in public_events
        ],
        "healing_events": [
            {
                "time": round(float(event.get("time", 0.0)), 3),
                "attacker": event.get("attacker"),
                "source": event.get("source", ""),
                **(
                    {"event_id": str(event["_event_id"])}
                    if event.get("_event_id") is not None
                    else {}
                ),
                **(
                    {"trigger_event_id": str(event["_trigger_event_id"])}
                    if event.get("_trigger_event_id") is not None
                    else {}
                ),
                **(
                    {"trigger_target": str(event["trigger_target"])}
                    if event.get("trigger_target") is not None
                    else {}
                ),
                "amount": round(float(event.get("amount", 0.0)), 1),
                "raw_amount": round(
                    float(event.get("raw_amount", event.get("amount", 0.0))), 1
                ),
                "applied_amount": round(
                    float(event.get("applied_amount", event.get("amount", 0.0))), 1
                ),
                "overheal": round(
                    float(
                        event.get(
                            "overheal",
                            max(
                                0.0,
                                float(
                                    event.get(
                                        "reduced_amount", event.get("amount", 0.0)
                                    )
                                )
                                - float(
                                    event.get(
                                        "applied_amount", event.get("amount", 0.0)
                                    )
                                ),
                            ),
                        )
                    ),
                    1,
                ),
                "temporary_health": round(float(event.get("temporary_health", 0.0)), 1),
                **(
                    {
                        "temporary_health_expires_at": round(
                            float(event["temporary_health_expires_at"]), 3
                        )
                    }
                    if event.get("temporary_health_expires_at") is not None
                    else {}
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
            for event in public_healing_events
        ],
        "support_events": [
            {
                "time": round(float(event.get("time", 0.0)), 3),
                "attacker": event.get("attacker"),
                "target": event.get("target"),
                "recipient": event.get("target"),
                **(
                    {"event_id": str(event["_event_id"])}
                    if event.get("_event_id") is not None
                    else {}
                ),
                **(
                    {"trigger_event_id": str(event["_trigger_event_id"])}
                    if event.get("_trigger_event_id") is not None
                    else {}
                ),
                "source": event.get("source", ""),
                "kind": event.get("kind", ""),
                "amount": round(float(event.get("amount", 0.0)), 6),
                "applied_amount": round(
                    float(event.get("applied_amount", event.get("amount", 0.0))), 6
                ),
                "target_scope": event.get("target_scope", ""),
                "target_policy": event.get("target_policy", ""),
                **(
                    {
                        key: round(float(event[key]), 6)
                        for key in (
                            "bonus_attack_speed_percent",
                            "on_hit_magic_damage",
                            "ability_power",
                            "ability_haste",
                            "bonus_move_speed_percent",
                            "slow_percent",
                            "chain_fraction",
                            "multiplier",
                            "cooldown",
                            "charges_consumed",
                            "beam_delay",
                            "armor_reduction_percent",
                            "mr_reduction_percent",
                            "stack_count",
                        )
                        if event.get(key) is not None
                    }
                ),
                **(
                    {
                        key: bool(event[key])
                        for key in (
                            "damage_reduction",
                            "next_event_only",
                            "all_sources",
                            "cleanse",
                            "persistent",
                        )
                        if event.get(key) is not None
                    }
                ),
                **(
                    {"trigger": str(event["trigger"])}
                    if event.get("trigger") is not None
                    else {}
                ),
                **(
                    {
                        key: str(event[key])
                        for key in ("resistance_type", "owner", "range_assumption")
                        if event.get(key) is not None
                    }
                ),
                **(
                    {"duration": round(float(event["duration"]), 3)}
                    if event.get("duration") is not None
                    else {}
                ),
                **(
                    {"expires_at": round(float(event["expires_at"]), 3)}
                    if event.get("expires_at") is not None
                    else {}
                ),
                **(
                    {"skipped_reason": str(event["skipped_reason"])}
                    if event.get("skipped_reason")
                    else {}
                ),
            }
            for event in public_support_events
        ],
        "utility_outcomes": {
            "contract": "utility_outcomes_v1",
            "participants": {
                actor.participant_id: utility_by_actor[actor.participant_id]
                for actor in all_actors
            },
            "focus": utility_by_actor.get(focus_participant_id, {}),
            "metric_note": (
                "Utility dimensions are reported in their native units. The "
                "calculator does not convert movement, cleanse, vision, or "
                "economy into TDD or a guessed common scalar."
            ),
        },
        "target_allocation": _target_allocation_receipt(
            public_events, len(enemy_actors), public_breakdown
        ),
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
            "focus_utility_outcomes": utility_by_actor.get(focus_participant_id, {}),
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
