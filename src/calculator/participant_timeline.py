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
from collections.abc import Iterable, Mapping, MutableMapping
from typing import Any

from .pipeline import FightParams, require_fight_mode_support, run_fight
from .scenario import ResolvedLoadout
from .timeline_coverage import combine_timeline_coverages
from .item_coverage import item_model_coverage
from .capabilities import SUPPORT_TARGET_RESOLUTION_SCOPES
from .support_effects import derive_ally_effects
from .item_support_effects import (
    derive_item_support_effects,
    has_event_view_support_items,
    schedule_knights_vow,
)
from .champions.skill_orders import get_ability_rank
from .champions.slotlib import extract_named
from .healing import GREY_HEALTH_RULE_CHAMPIONS
from .healing_reduction import (
    champion_grievous_wound_sources,
    healing_reduction_profiles,
)
from .item_effects import (
    ThornsEffect,
    required_effect_value,
    serpents_fang_venom,
    sustain_effect_value,
    thorns_effects,
)
from .resistance import (
    apply_armor_penetration,
    apply_magic_penetration,
    apply_resistance,
)
from .survival import (
    ActionKind,
    ReceiptLedger,
    ScoreLedger,
    SurvivalAction,
    TransitionContext,
    UncompilableActionError,
    WalkCompiler,
    accumulate_damage_totals,
    accumulate_support_values,
    action_key as _action_key,
    assemble_survival_rows,
    build_states,
    coalesce_darius_q_heals,
    finalize_states,
    resolve_grievous as _grievous_pack,
    revive_candidate_actions,
    run_survival_walk,
    survival_action_from_event,
    uncompilable_item_receipt as _uncompilable_item_receipt,
)

# Issue #137: the survival kernel lives in ``src/calculator/survival``; the
# underscored name below is kept as an alias so the public surface of this
# module (and existing tests importing it here) stays stable.
_WalkCompiler = WalkCompiler


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


def _coalesce_darius_q_heals(
    healing: MutableMapping[str, list[dict[str, Any]]],
) -> None:
    """Combine Darius Q pair receipts into one live heal per cast.

    The kept copy is replaced, never mutated in place: a packet-cached
    typed action is keyed by the original dict's identity (issue #169),
    so an in-place formula swap would let a stale cached conversion win.
    """
    for events in healing.values():
        groups: dict[tuple[float, int], tuple[int, int]] = {}
        kept: list[dict[str, Any]] = []
        for event in events:
            marker = event.get("_darius_q_group")
            if not isinstance(marker, tuple) or len(marker) != 2:
                kept.append(event)
                continue
            key = (float(marker[0]), int(marker[1]))
            first = groups.get(key)
            if first is None:
                groups[key] = (len(kept), 1)
                kept.append(event)
            else:
                groups[key] = (first[0], first[1] + 1)
        for index, count in groups.values():
            kept[index] = {
                **kept[index],
                "amount_formula": (
                    lambda current_health, maximum_health, count=count: (
                        max(0.0, maximum_health - current_health)
                        * min(0.51, 0.17 * count)
                    )
                ),
            }
        events[:] = kept


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


def _has_catalyst(items: Iterable[Mapping[str, Any]]) -> bool:
    """Return whether a participant owns Catalyst's ordered resource passive."""
    return any(str(item.get("name", "")) == "Catalyst of Aeons" for item in items)


def _catalyst_resource_restores(
    actor: Combatant,
    incoming: Mapping[str, Iterable[Mapping[str, Any]]],
    duration: float,
) -> tuple[tuple[tuple[float, float], ...], bool]:
    """Derive Catalyst restores from complete incoming champion packets.

    Eternity uses pre-mitigation damage from champions.  The coupled ledger
    therefore accepts only packets with an explicit finite ``raw_damage`` and
    a timestamp inside the authored window.  Returning ``complete=False`` is
    the fail-closed signal; callers never substitute post-mitigation damage or
    an aggregate estimate.
    """
    if not _has_catalyst(actor.items):
        return (), True
    ratio = sustain_effect_value("Catalyst of Aeons", "damage_taken_to_mana_ratio")
    restores: list[tuple[float, float]] = []
    for event in incoming.get(actor.participant_id, ()):
        if not isinstance(event, Mapping):
            continue
        source_id = str(event.get("attacker", ""))
        if not source_id or source_id == actor.participant_id:
            continue
        if event.get("_reactive") or event.get("_deferred"):
            continue
        try:
            event_time = float(event.get("time", 0.0))
            raw_damage = float(event.get("raw_damage", 0.0) or 0.0)
        except (TypeError, ValueError):
            return (), False
        if (
            not math.isfinite(event_time)
            or not math.isfinite(raw_damage)
            or event_time < 0.0
            or event_time > duration + 1e-9
        ):
            return (), False
        if raw_damage <= 0.0:
            # Zero-damage/marker packets are not damage taken and therefore
            # do not mint mana.  They remain valid ledger rows.
            continue
        amount = raw_damage * ratio
        if amount > 0.0:
            restores.append((event_time, amount))
    restores.sort(key=lambda row: row[0])
    return tuple(restores), True


def _actor_params_with_resource_restores(
    base: FightParams,
    actor: Combatant,
    resource_restores: Mapping[str, tuple[tuple[float, float], ...]] | None,
) -> FightParams:
    """Attach one actor's typed external resource ledger to its fight params."""
    params = _actor_params(base, actor)
    if resource_restores is None:
        return params
    return replace(
        params,
        resource_restore_events=tuple(resource_restores.get(actor.participant_id, ())),
    )


def _defensive_signature(defender: Combatant) -> tuple[Any, ...]:
    """A hashable key equal exactly when ``_target_params`` would be equal."""
    return tuple(_target_overrides(defender).values())


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
    defender_index: int = 0,
    champion_data: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Enrich one pair fight's events exactly once.

    The coupled optimizer replays cached pair results for thousands of
    candidates, so everything derivable from the result alone — attacker and
    target ids, per-pair event ids, heal trigger links, and the survival
    walk's precomputed sort key — lives on templates here.  Applying a packet
    to one evaluation only shallow-copies each template, because the walk
    mutates its copy's top-level fields.

    ``defender_index`` is the defender's position in the attacker's ordered
    roster (the same slot the engine sees as ``roster_target_index``).  A
    sourced flat heal that pays a reduced amount to later targets (Vladimir's
    Hemoplague) carries that amount as an explicit receipt, and every
    defender past the first is re-priced here so each target keeps its own
    heal event instead of collapsing into one identical copy.

    ``champion_data`` supplies the attacker's reviewed champion module so a
    champion-applied Grievous Wounds hit (Katarina R, Varus E) can ride its
    damage event as the same ``grievous_duration``/``_wound_source`` receipt
    the survival walks consume — one event interface for item, reactive, and
    champion wounds.
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
    champion_wounds = (
        champion_grievous_wound_sources(champion_data)
        if champion_data is not None
        else ()
    )
    champion_wound_by_source = {
        str(packet.get("source_key", "")): packet for packet in champion_wounds
    }
    # The engine exposes the final effective resistances for this pair.
    # Preserve them on every packet so an ordered target state can re-price
    # the same post-mitigation event after adding its sourced resistance
    # delta.  A missing value is deliberately left absent: the survival
    # walk then refuses to invent a mitigation ratio for that packet.
    baseline_fields = []
    for field in ("effective_armor", "effective_mr"):
        try:
            baseline = float(result[field])
        except (KeyError, TypeError, ValueError):
            continue
        if math.isfinite(baseline):
            baseline_fields.append((f"_baseline_{field}", baseline))
    for index, event in enumerate(result.get("damage_events", [])):
        if "sequence" not in event:
            # See _action_key: pair-local event ids stay order-irrelevant
            # only while every engine event carries its per-fight sequence.
            raise ValueError(
                f"{attacker_id} damage event {event.get('source_key', '')!r} "
                "has no sequence; the walk's tie-break order would depend on "
                "event-id numbering"
            )
        source_key = str(event.get("source_key", ""))
        time_key = round(float(event.get("time", 0.0)), 9)
        enriched = {
            **event,
            "attacker": attacker_id,
            "target": defender_id,
            "_event_id": f"{attacker_id}:{defender_id}:{index}",
            "is_ability": _is_authored_ability_event(event),
            "ability_instance": _ability_instance_for_event(event, cast_timeline),
        }
        # A champion-applied Grievous Wounds hit (Katarina R, Varus E) rides
        # the damaging event as the same wound receipt the survival walks
        # consume: the patch-wide factor and a 3-second window, refreshed by
        # every hit (each Death Lotus dagger), sourced to the ability label.
        wound_packet = champion_wound_by_source.get(source_key)
        if wound_packet is not None and float(event.get("damage", 0.0) or 0.0) > 0.0:
            enriched["grievous_duration"] = float(wound_packet.get("duration", 0.0))
            enriched["_wound_source"] = str(
                wound_packet.get("source", "Grievous Wounds")
            )
        # Multi-target rows are authored on the engine breakdown. Carry the
        # same target-allocation receipt onto each ordered packet so the
        # coupled timeline can prove which roster slot received it instead of
        # displaying an unexplained aggregate secondary hit.
        source_row = result_breakdown.get(source_key, {})
        if isinstance(source_row, Mapping) and isinstance(
            source_row.get("targeting"), Mapping
        ):
            enriched["targeting"] = dict(source_row["targeting"])
        for baseline_key, baseline in baseline_fields:
            enriched[baseline_key] = baseline
        enriched["_sk"] = _action_key(
            float(event.get("time", 0.0)), 0.0, defender_id, enriched
        )
        events.append(enriched)
        event_ids_by_key[(source_key, time_key, int(event.get("sequence", 0) or 0))] = (
            enriched["_event_id"]
        )
        event_ids_by_source_time[(source_key, time_key)].append(enriched["_event_id"])
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
        # Per-champion flat heals (Hemoplague) pay the reduced amount to
        # every infected champion after the first.  The engine authors each
        # pair copy at the full value because a pair fight cannot see the
        # roster; re-price the copy whose defender is a later target here so
        # the public receipt shows one full and one reduced event.
        later_amount = event.get("_later_target_amount")
        if defender_index > 0 and later_amount is not None:
            enriched_heal["amount"] = max(0.0, float(later_amount))
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


def _packet_typed_actions(
    packet: dict[str, Any], index_of: Mapping[str, int]
) -> dict[int, SurvivalAction]:
    """The packet's events and heals as typed actions, compiled once.

    Issue #169: a cached pair packet serves every evaluation of a search,
    so its typed-action conversion happens here once and rides the packet
    (like the precomputed ``_sk`` sort keys) instead of being re-derived
    from the event dicts on every walk.  The map is keyed by template
    identity; consumers pair each cached action with that template's
    per-evaluation copy via ``_replace(event=...)``, which reproduces the
    per-event conversion exactly while the copy's contents are unchanged —
    and every composition step that changes an action-relevant field
    replaces the dict, which makes the lookup miss and the conversion run
    fresh.  The participant-index token is re-verified on every use (the
    ``resolve_damage_effects`` pattern), so a different roster order can
    never serve stale indices.
    """
    token = tuple(index_of.items())
    cached = packet.get("_typed")
    if cached is not None and cached[0] == token:
        return cached[1]
    by_template: dict[int, SurvivalAction] = {}
    for template in packet["events"]:
        subject_id = str(template.get("target", ""))
        subject = index_of.get(subject_id)
        if subject is None:
            continue
        by_template[id(template)] = survival_action_from_event(
            template, 0.0, subject, index_of, subject_id=subject_id
        )._replace(event=None)
    for template in packet["heals"]:
        subject_id = str(template.get("attacker", ""))
        subject = index_of.get(subject_id)
        if subject is None:
            continue
        by_template[id(template)] = survival_action_from_event(
            template, 1.0, subject, index_of, subject_id=subject_id
        )._replace(event=None)
    packet["_typed"] = (token, by_template)
    return by_template


def _warmog_heart_tick_events(
    combatant: Combatant, duration: float
) -> list[dict[str, Any]]:
    """Author an active Warmog's Heart holder's regen tick events.

    Warmog's Heart is a live combat-state gate.  Each tick's amount is based
    on the current maximum health at the moment it lands, while the no-damage
    window is checked inside the survival walk against the last applied
    incoming packet.  The 2,000 bonus-health threshold is sourced from the
    item's full Wiki entry and is intentionally not guessed for an
    unqualified loadout.  Both walks author through this one function: the
    receipt composition schedules the events per call, and the compiled base
    panel converts them into typed actions once per search (issue #169).
    """
    if not any(
        str(item.get("name", "")) == "Warmog's Armor" for item in combatant.items
    ):
        return []
    threshold = sustain_effect_value("Warmog's Armor", "heart_bonus_health_threshold")
    if float(combatant.stats.get("bonus_health", 0.0)) < threshold:
        return []
    ratio = sustain_effect_value("Warmog's Armor", "heart_max_health_ratio_per_tick")
    tick = sustain_effect_value("Warmog's Armor", "heart_tick_interval")
    gate = sustain_effect_value("Warmog's Armor", "heart_champion_damage_cooldown")
    if ratio <= 0.0 or tick <= 0.0:
        return []
    events: list[dict[str, Any]] = []
    time_value = tick
    sequence = 0
    while time_value <= duration + 1e-9:
        events.append(
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
            }
        )
        sequence += 1
        time_value += tick
    return events


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


def _first_pair_defender_id(
    attacker: Combatant, all_actors: Iterable[Combatant]
) -> str | None:
    """The first defender in this attacker's ordered pair list.

    Mirrors the legacy attack groups (main/ally attack the enemies in
    roster order; an enemy attacks the main first).  Used to reconstruct
    the pair-enriched id of an attacker's applied self-heal copy so
    fan-out clones can link back to it (``_source_event_id``).
    """
    if attacker.team == "enemy":
        return "main"
    for actor in all_actors:
        if actor.team == "enemy":
            return actor.participant_id
    return None


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
    # Issue #142: fail closed BEFORE any team/roster branching.  Every
    # unrecognized / missing / structurally invalid scope used to land in the
    # terminal catch-all and silently redirect the packet to teammate zero
    # (or drop it entirely for an enemy attacker) — contradicting the
    # published ``fail_closed: True`` contract.  Main, ally, and enemy actors
    # must fail identically, so this check runs before the no-teammate block.
    if target_scope not in SUPPORT_TARGET_RESOLUTION_SCOPES:
        raise ValueError(
            "Unsupported support target_scope "
            f"{target_scope!r} for {attacker.participant_id} "
            f"({attacker.champion_data.get('name', '')}) from source "
            f"{effect.get('source', '')!r}; supported scopes: "
            f"{sorted(SUPPORT_TARGET_RESOLUTION_SCOPES)}"
        )
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
    if target_scope == "one_teammate":
        # The one-teammate scope (Karma E, Orianna E, Yuumi E, Lulu E — the
        # self-or-target default) used to be resolved ONLY by the terminal
        # catch-all.  It is now an explicit branch, so the terminal default
        # can be an unreachable exhaustiveness guard.
        return [teammates[0].participant_id], "first_selected_teammate"
    raise AssertionError(
        f"unhandled support target_scope {target_scope!r} — the closed "
        "resolution vocabulary and this branch list have drifted"
    )


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
    # Issue #143: fan out champion-owned heal events (authored by the E1
    # self-heal rule for slots in ``_MODULE_AUTHORED_HEAL_SLOTS`` — Taric Q
    # today) to the attacker's selected teammates.  The self copy stays in
    # the attacker's healing ledger at its original event id; each ally copy
    # is one support heal template with the same time/amount/source/kind,
    # ``_event_id = f"{self_id}:ally:{i}"`` and ``_source_event_id`` = the
    # self copy's id, so the receipt can prove one formula priced every
    # recipient.  The clones are added BEFORE item support effects so item
    # passives that trigger off ally heals/shields (Moonstone Renewer) see
    # them, exactly like the scanner packets they replace.
    first_defender_id = _first_pair_defender_id(attacker, all_actors)
    for heal_index, heal_event in enumerate(result.get("self_healing_events", [])):
        if not isinstance(heal_event, Mapping):
            continue
        if str(heal_event.get("target_scope", "")) not in {
            "self_and_all_teammates",
            "self_and_one_teammate",
        }:
            continue
        target_ids, target_policy = _support_target_ids(
            attacker, heal_event, all_actors
        )
        raw_id = heal_event.get("_event_id") or (
            f"{attacker.participant_id}:heal:{heal_index}"
        )
        applied_self_id = (
            f"{raw_id}:{first_defender_id}" if first_defender_id else str(raw_id)
        )
        for ally_index, target_id in enumerate(target_ids):
            if target_id == attacker.participant_id:
                continue
            templates.append(
                {
                    **{key: value for key, value in heal_event.items() if key != "_sk"},
                    # The clone is a support heal packet (like the scanner
                    # packet it replaces), so it rides the heal application
                    # phase and counts toward the attacker's healing output.
                    "kind": "heal",
                    "attacker": attacker.participant_id,
                    "target": target_id,
                    "target_policy": target_policy,
                    "_event_id": f"{applied_self_id}:ally:{ally_index}",
                    "_source_event_id": applied_self_id,
                }
            )
    if damage_events is None:
        # No per-event override: the item scan reads the engine result as-is
        # (it never mutates it), so skip the per-candidate dict copy.
        item_result: Mapping[str, Any] = result
    else:
        item_result = dict(result)
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
    economy = [event for event in support if event.get("kind") == "economy"]
    vision = [event for event in support if event.get("kind") == "vision"]
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
    if economy:
        applied_dimensions.add("economy")
    if vision:
        applied_dimensions.add("vision")
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
        "economy": {
            "event_count": len(economy),
            "gold": round(
                sum(
                    float(event.get("gold_amount", event.get("amount", 0.0)) or 0.0)
                    for event in economy
                ),
                6,
            ),
        },
        "vision": {
            "event_count": len(vision),
            "ward_uses": round(
                sum(
                    float(event.get("ward_uses", event.get("amount", 0.0)) or 0.0)
                    for event in vision
                ),
                6,
            ),
        },
        "multi_target": {
            "packet_count": len(secondary),
            "allocated_packet_count": sum(
                1 for row in secondary if row.get("allocated_target_index") is not None
            ),
        },
        "scored_support_amount": round(
            sum(
                float(event.get("applied_amount", 0.0) or 0.0)
                for event in support
                if event.get("kind") not in {"economy", "vision"}
            ),
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
            "Movement, cleanse, economy, and vision remain separate units; no "
            "cross-unit utility score is inferred. Healing, shielding, and "
            "applied support amounts remain event-derived values."
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


# ─────────────────────────────────────────────────────────────────────────
# Grey-health primitive (E8a)
# ─────────────────────────────────────────────────────────────────────────
# Grey-health champions store a sourced portion of post-mitigation damage
# TAKEN as a grey pool on their health bar and pay it back as a heal when
# their active consumes the pool.  The 1v1 heal derivation
# (``healing.derive_self_healing``) only sees the main's OUTGOING events,
# so the receipts are authored here against the incoming ledger: the
# main-as-defender's pair events accumulate the sourced percentage, and
# each consume heals the sourced portion.  Every ratio is pinned from
# data/champions.json prose or leveling rows (citations inline below); no
# value is invented.  The authored heals carry fixed sourced amounts (the
# pair engine's post-mitigation values) so the ordered walk and the
# compiled optimizer walk apply byte-identical numbers; walk-time state
# gates (spell shields, stasis, redirects) are documented boundaries that
# would require a stateful per-event pool, which the 1v1 receipt does not
# model.
#
# Pyke P (Gift of the Drowned Ones) — data/champions.json P prose only:
#   "Pyke stores 9% (+ 0.2% per 1 Lethality) of the post-mitigation damage
#   he takes from enemy champions as grey health ..., increased to 40%
#   (+ 0.4% per 1 Lethality) while there are two or more visible enemy
#   champions nearby. He can store up to 80 (+ 800% bonus AD) grey health,
#   with an upper cap of 55% of his maximum health."  "While Pyke is not
#   visible to enemies, he rapidly consumes his grey health to heal for the
#   same amount."  Out-of-vision is a boundary the 1v1 ledger does not
#   model, so the consume is documented, not authored as an in-window heal.
_PYKE_P_STORE_RATIO = 0.09
_PYKE_P_STORE_PER_LETHALITY = 0.002
_PYKE_P_STORE_MULTI_RATIO = 0.40
_PYKE_P_STORE_MULTI_PER_LETHALITY = 0.004
_PYKE_P_STORE_FLAT_CAP = 80.0
_PYKE_P_STORE_BONUS_AD_CAP_RATIO = 8.0  # "80 (+ 800% bonus AD)"
_PYKE_P_STORE_MAX_HEALTH_CAP_RATIO = 0.55
_PYKE_P_CONSUME_HEAL_RATIO = 1.0  # out-of-vision consume heals the pool
# Rengar W (Battle Roar) — data/champions.json W prose only (the W
# leveling rows carry the ability's magic damage, not a heal amount):
#   "Rengar stores 50% of the post-mitigation damage he has taken in the
#   last 1.5 seconds as grey health ... consuming his grey health to heal
#   for the same amount."  The active heals 100% of the stored pool, i.e.
#   50% of the post-mitigation damage taken in the 1.5 s before the cast.
#   A same-timestamp incoming packet resolves before the cast's heal (the
#   ledger's damage-before-heal phase order), so the window is inclusive.
_RENGAR_W_STORE_RATIO = 0.50
_RENGAR_W_STORE_WINDOW_SECONDS = 1.5
_RENGAR_W_CONSUME_HEAL_RATIO = 1.0
# Tahm Kench E (Thick Skin) — leveling rows:
#   "Damage Stored into Grey Health" 15/23/31/39/47 by E rank (1 enemy),
#   "Increased Damage Stored into Grey Health" 42/44/46/48/50 with 2+
#   visible enemies, pool cap "300% of his maximum health".  The heal is
#   the out-of-combat consume ("after 4 seconds without taking damage ...
#   restore 60% : 100% (based on level) of the amount") whose level row
#   "Max Health Damage" carries 60 : 100 (based on level).  The E ACTIVE
#   converts grey into a 2.5 s shield — a shield, not a heal — and stays
#   out of this primitive's scope (the module documents Thick Skin as
#   shield state).  The consume is modeled as one lump heal at the 4 s
#   boundary; the wiki's 10%-max-health-per-0.264 s tick delivery is a
#   rate detail with the same total, documented here.
_TAHM_E_STORE_RANK = (0.15, 0.23, 0.31, 0.39, 0.47)
_TAHM_E_STORE_MULTI_RANK = (0.42, 0.44, 0.46, 0.48, 0.50)
_TAHM_E_STORE_CAP_RATIO = 3.0
_TAHM_E_OUT_OF_COMBAT_SECONDS = 4.0
# Mordekaiser W (Indestructible) — data/champions.json W prose:
#   "stores 45% of the post-mitigation damage he deals and 7.5% of the
#   pre-mitigation damage he takes ... up to 30% of his maximum health."
#   Recast ("Indestructible can be recast after 0.5 seconds while the
#   shield is active ... consuming the remaining shield, healing for a
#   portion of the amount") pays the "Shield to Healing" leveling row
#   35/37.5/40/42.5/45 by W rank of the shield amount (the pool at the
#   first W cast; the model presses the recast at its earliest available
#   time — the exact moment is a player decision, documented boundary).
#   The Potential Shield decay and the active shield's exponential decay
#   are state, not modeled.
_MORDE_W_STORE_DEALT_RATIO = 0.45
_MORDE_W_STORE_TAKEN_PRE_RATIO = 0.075
_MORDE_W_STORE_CAP_RATIO = 0.30
_MORDE_W_SHIELD_TO_HEALING_RANK = (0.35, 0.375, 0.40, 0.425, 0.45)
_MORDE_W_RECAST_AVAILABLE_SECONDS = 0.5
# Locke W (Soul Ignition) — data/champions.json W prose:
#   "He also stores an amount of grey health on his health bar equal to
#   100% of the post-mitigation damage he takes from enemy champions, up
#   to a cap ... Recast: Locke ends Soul Ignition and consumes his grey
#   health to heal for the same amount."  The cap is the leveling row
#   "Damage taken grey health cap" (40/60/80/100/120 by W rank + 100%
#   AP); the storage window is the 6-second active ("ignites his soul
#   for 6 seconds").  The recast is available after 0.5 s and "does so
#   automatically afterwards" — the auto-recast at the 6 s boundary is
#   the deterministic consume.  The additional pool from Soul Ignition's
#   health cost and the missing-health bonus ("increased by up to
#   40 : 200 (based on level) (+ 20% AP) based on his missing health")
#   are dynamic self-state and remain documented boundaries, exactly as
#   the E1-b6 review scoped them.
_LOCKE_W_STORE_RATIO = 1.0
_LOCKE_W_STORE_WINDOW_SECONDS = 6.0
_LOCKE_W_AUTO_RECAST_SECONDS = 6.0
_LOCKE_W_CONSUME_HEAL_RATIO = 1.0


def _grey_leveling_values(ability: Mapping[str, Any], attribute: str) -> list[float]:
    """Read one leveling attribute's first modifier value array."""
    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute") != attribute:
                continue
            modifiers = leveling.get("modifiers", [])
            if not modifiers:
                continue
            values = modifiers[0].get("values", [])
            if values:
                return [float(value) for value in values]
    return []


def _grey_rank_ratio(
    ability: Mapping[str, Any],
    attribute: str,
    rank: int,
    default: float = 0.0,
) -> float:
    """One rank-indexed sourced percentage (a row of 5 values)."""
    values = _grey_leveling_values(ability, attribute)
    if not values:
        return default
    index = min(max(int(rank), 1) - 1, len(values) - 1)
    return float(values[index]) / 100.0


def _grey_level_ratio(ability: Mapping[str, Any], attribute: str, level: int) -> float:
    """One level-indexed sourced percentage (an 18+ entry row)."""
    values = _grey_leveling_values(ability, attribute)
    if not values:
        return 0.0
    index = min(max(int(level), 1) - 1, len(values) - 1)
    return float(values[index]) / 100.0


# pylint: disable=too-many-arguments,too-many-positional-arguments
# pylint: disable=too-many-locals,too-many-branches,too-many-statements
def _grey_health_receipts(
    champion_name: str,
    champion_data: Mapping[str, Any],
    level: int,
    stats: Mapping[str, float],
    incoming: list[tuple[float, float, float]],
    outgoing: list[tuple[float, float, float]],
    cast_timeline: Iterable[Mapping[str, Any]],
    duration: float,
    enemy_count: int,
    ability_ranks: Mapping[str, int] | None = None,
) -> tuple[list[tuple[float, str, float]], dict[str, float]]:
    """Author grey-health consume heals for one grey-health main champion.

    ``incoming``/``outgoing`` are ``(time, post_mitigation,
    pre_mitigation)`` damage records for damage the main TAKES (its
    defenders' pair packets) and DEALS within the fight window.  Returns
    ``(consume_heals, summary)`` where each heal is ``(time, source,
    amount)`` and the summary carries the ``grey_health_stored`` pool,
    the ``grey_health_consumed`` total, and a ``source`` label for the
    receipt.  The pool accumulates the sourced ratio of post-mitigation
    incoming damage (Mordekaiser also stores from pre-mitigation damage
    taken and from post-mitigation damage dealt), capped per champion.
    """
    name = str(champion_name)
    heals: list[tuple[float, str, float]] = []

    def _slot_rank(slot: str) -> int:
        if ability_ranks and slot in ability_ranks:
            return max(0, int(ability_ranks[slot] or 0))
        return max(0, int(get_ability_rank(slot, level, name)))

    if name == "Pyke":
        lethality = float(stats.get("lethality", 0.0) or 0.0)
        if enemy_count >= 2:
            ratio = _PYKE_P_STORE_MULTI_RATIO + (
                _PYKE_P_STORE_MULTI_PER_LETHALITY * lethality
            )
        else:
            ratio = _PYKE_P_STORE_RATIO + (_PYKE_P_STORE_PER_LETHALITY * lethality)
        max_health = max(0.0, float(stats.get("health", 0.0) or 0.0))
        bonus_ad = max(0.0, float(stats.get("bonus_attack_damage", 0.0) or 0.0))
        cap = min(
            _PYKE_P_STORE_FLAT_CAP + _PYKE_P_STORE_BONUS_AD_CAP_RATIO * bonus_ad,
            _PYKE_P_STORE_MAX_HEALTH_CAP_RATIO * max_health,
        )
        pool = min(cap, ratio * sum(post for _t, post, _pre in incoming))
        # Out-of-vision consume: vision is a boundary the 1v1 ledger does
        # not model, so the 100% heal is documented, not authored.
        return heals, {
            "grey_health_stored": pool,
            "grey_health_consumed": 0.0,
            "source": (
                "Gift of the Drowned Ones (9% + 0.2% per Lethality of "
                "post-mitigation damage taken; out-of-vision consume is a "
                "vision boundary, not modeled in-window)"
            ),
        }
    if name == "Rengar":
        w_casts = sorted(
            float(cast.get("time", 0.0))
            for cast in cast_timeline
            if str(cast.get("slot", "")) == "W"
        )
        consumed = 0.0
        for cast_time in w_casts:
            window = sum(
                post
                for event_time, post, _pre in incoming
                if cast_time - _RENGAR_W_STORE_WINDOW_SECONDS <= event_time <= cast_time
            )
            amount = _RENGAR_W_STORE_RATIO * _RENGAR_W_CONSUME_HEAL_RATIO * window
            if amount > 0.0 and cast_time <= duration:
                heals.append((cast_time, "Battle Roar (grey health)", amount))
                consumed += amount
        stored = _RENGAR_W_STORE_RATIO * sum(post for _t, post, _pre in incoming)
        return heals, {
            "grey_health_stored": stored,
            "grey_health_consumed": consumed,
            "source": (
                "Battle Roar (50% of post-mitigation damage taken in the "
                "last 1.5 seconds stored as grey health; the active heals "
                "the stored pool)"
            ),
        }
    if name == "Tahm Kench":
        e_rank = max(1, _slot_rank("E"))
        rank_row = _TAHM_E_STORE_MULTI_RANK if enemy_count >= 2 else _TAHM_E_STORE_RANK
        ratio = rank_row[min(e_rank, len(rank_row)) - 1]
        max_health = max(0.0, float(stats.get("health", 0.0) or 0.0))
        pool = min(
            _TAHM_E_STORE_CAP_RATIO * max_health,
            ratio * sum(post for _t, post, _pre in incoming),
        )
        consumed = 0.0
        if pool > 0.0 and incoming:
            last_damage_time = max(event_time for event_time, _post, _pre in incoming)
            consume_time = last_damage_time + _TAHM_E_OUT_OF_COMBAT_SECONDS
            if consume_time <= duration:
                ability = _grey_ability(champion_data, "E")
                restore = _grey_level_ratio(ability, "Max Health Damage", level)
                amount = restore * pool
                if amount > 0.0:
                    heals.append((consume_time, "Thick Skin (grey health)", amount))
                    consumed = amount
        return heals, {
            "grey_health_stored": pool,
            "grey_health_consumed": consumed,
            "source": (
                "Thick Skin (E-rank % of post-mitigation damage taken "
                "stored as grey health; the out-of-combat consume restores "
                "60% : 100% based on level of the pool after 4 seconds "
                "without damage)"
            ),
        }
    if name == "Mordekaiser":
        w_rank = max(1, _slot_rank("W"))
        heal_ratio = _MORDE_W_SHIELD_TO_HEALING_RANK[
            min(w_rank, len(_MORDE_W_SHIELD_TO_HEALING_RANK)) - 1
        ]
        max_health = max(0.0, float(stats.get("health", 0.0) or 0.0))
        cap = _MORDE_W_STORE_CAP_RATIO * max_health
        dealt_total = _MORDE_W_STORE_DEALT_RATIO * sum(
            post for _t, post, _pre in outgoing
        )
        taken_total = _MORDE_W_STORE_TAKEN_PRE_RATIO * sum(
            pre for _t, _post, pre in incoming
        )
        pool = min(cap, dealt_total + taken_total)
        w_casts = sorted(
            float(cast.get("time", 0.0))
            for cast in cast_timeline
            if str(cast.get("slot", "")) == "W"
        )
        consumed = 0.0
        if w_casts:
            w1_time = w_casts[0]
            dealt_up_to = _MORDE_W_STORE_DEALT_RATIO * sum(
                post for event_time, post, _pre in outgoing if event_time <= w1_time
            )
            taken_up_to = _MORDE_W_STORE_TAKEN_PRE_RATIO * sum(
                pre for event_time, _post, pre in incoming if event_time <= w1_time
            )
            shield_amount = min(cap, dealt_up_to + taken_up_to)
            recast_time = w1_time + _MORDE_W_RECAST_AVAILABLE_SECONDS
            amount = heal_ratio * shield_amount
            if amount > 0.0 and recast_time <= duration:
                heals.append((recast_time, "Indestructible (grey health)", amount))
                consumed = amount
        return heals, {
            "grey_health_stored": pool,
            "grey_health_consumed": consumed,
            "source": (
                "Indestructible (45% of post-mitigation damage dealt + "
                "7.5% of pre-mitigation damage taken stored as Potential "
                "Shield, capped at 30% of maximum health; the W recast "
                "heals the Shield-to-Healing % of the stored shield — the "
                "recast is modeled at its earliest available time, shield "
                "decay is state)"
            ),
        }
    if name == "Locke":
        # Soul Ignition (W): each W cast opens a 6-second storage window
        # during which 100% of the post-mitigation champion damage taken
        # accumulates as grey health, capped by the rank row; the
        # automatic recast at the 6 s boundary consumes the pool to heal
        # for the same amount (cached W prose, leveling row "Damage taken
        # grey health cap").  The health-cost and missing-health bonus
        # terms remain documented boundaries (dynamic self-state, per the
        # E1-b6 scope note).
        w_rank = max(1, _slot_rank("W"))
        cap = extract_named(
            _grey_ability(champion_data, "W"),
            "Damage taken grey health cap",
            w_rank,
            stats,
            {},
        )
        w_casts = sorted(
            float(cast.get("time", 0.0))
            for cast in cast_timeline
            if str(cast.get("slot", "")) == "W"
        )
        consumed = 0.0
        for cast_time in w_casts:
            window_start = cast_time
            window_end = cast_time + _LOCKE_W_STORE_WINDOW_SECONDS
            stored = min(
                cap,
                _LOCKE_W_STORE_RATIO
                * sum(
                    post
                    for event_time, post, _pre in incoming
                    if window_start <= event_time <= window_end
                ),
            )
            consume_time = cast_time + _LOCKE_W_AUTO_RECAST_SECONDS
            amount = _LOCKE_W_CONSUME_HEAL_RATIO * stored
            if amount > 0.0 and consume_time <= duration:
                heals.append((consume_time, "Soul Ignition (grey health)", amount))
                consumed += amount
        return heals, {
            "grey_health_stored": min(
                cap,
                _LOCKE_W_STORE_RATIO * sum(post for _t, post, _pre in incoming),
            ),
            "grey_health_consumed": consumed,
            "source": (
                "Soul Ignition (100% of post-mitigation damage taken from "
                "enemy champions during the 6s active stored as grey "
                "health, capped by the 'Damage taken grey health cap' row; "
                "the automatic recast at 6s heals the stored pool; the "
                "health-cost add and missing-health bonus remain dynamic "
                "self-state boundaries)"
            ),
        }
    if name == "Kled":
        # Skaarl's 400 : 1400 (based on level) health pool is the mounted
        # duo's damage sink; dismount at zero and the remount restore are a
        # revive-boundary pattern (like Aatrox's ghost atom) and are NOT
        # implemented.  No heal is authored; the module documents it.
        return heals, {
            "grey_health_stored": 0.0,
            "grey_health_consumed": 0.0,
            "source": (
                "Skaarl the Cowardly Lizard (the mounted duo's damage pool "
                "is a revive-boundary pattern; dismount/remount are not "
                "modeled)"
            ),
        }
    return heals, {
        "grey_health_stored": 0.0,
        "grey_health_consumed": 0.0,
        "source": "",
    }


def _grey_ability(champion_data: Mapping[str, Any], slot: str) -> dict[str, Any]:
    """Return one ability's first JSON entry for a slot (lists allowed)."""
    abilities = champion_data.get("abilities")
    if not isinstance(abilities, Mapping):
        return {}
    entry = abilities.get(slot)
    if isinstance(entry, list):
        entry = entry[0] if entry else None
    return dict(entry) if isinstance(entry, Mapping) else {}


def _grey_health_event_receipt(
    name: str,
    level: int,
    stats: Mapping[str, float],
    enemy_count: int,
    event: Mapping[str, Any],
    *,
    incoming: bool,
    ability_ranks: Mapping[str, int] | None = None,
) -> float | None:
    """One event's sourced grey-health contribution for the public receipt.

    ``incoming=True`` prices a packet the main TAKES, ``incoming=False`` a
    packet the main DEALS (Mordekaiser's dealt term).  Returns None when
    the champion authors no receipt for that direction.
    """
    if name == "Pyke":
        if not incoming:
            return None
        lethality = float(stats.get("lethality", 0.0) or 0.0)
        if enemy_count >= 2:
            ratio = _PYKE_P_STORE_MULTI_RATIO + (
                _PYKE_P_STORE_MULTI_PER_LETHALITY * lethality
            )
        else:
            ratio = _PYKE_P_STORE_RATIO + (_PYKE_P_STORE_PER_LETHALITY * lethality)
        return ratio * max(0.0, float(event.get("damage", 0.0) or 0.0))
    if name == "Rengar":
        if not incoming:
            return None
        return _RENGAR_W_STORE_RATIO * max(0.0, float(event.get("damage", 0.0) or 0.0))
    if name == "Tahm Kench":
        if not incoming:
            return None
        rank = max(1, int(ability_ranks.get("E", 0) or 0) if ability_ranks else 0)
        if rank == 0:
            rank = max(1, int(get_ability_rank("E", level, name)))
        rank_row = _TAHM_E_STORE_MULTI_RANK if enemy_count >= 2 else _TAHM_E_STORE_RANK
        ratio = rank_row[min(rank, len(rank_row)) - 1]
        return ratio * max(0.0, float(event.get("damage", 0.0) or 0.0))
    if name == "Mordekaiser":
        damage = max(0.0, float(event.get("damage", 0.0) or 0.0))
        if incoming:
            raw = max(0.0, float(event.get("raw_damage", damage) or 0.0))
            return _MORDE_W_STORE_TAKEN_PRE_RATIO * raw
        return _MORDE_W_STORE_DEALT_RATIO * damage
    if name == "Locke":
        if not incoming:
            return None
        return _LOCKE_W_STORE_RATIO * max(0.0, float(event.get("damage", 0.0) or 0.0))
    return None


def _simulate_survival(
    combatants: Iterable[Combatant],
    incoming: Mapping[str, list[dict[str, Any]]],
    healing: Mapping[str, list[dict[str, Any]]],
    support_effects: Mapping[str, list[dict[str, Any]]],
    duration: float,
    annotate: bool = True,
    receipt_events: MutableMapping[str, list[dict[str, Any]]] | None = None,
    typed_actions: Mapping[int, SurvivalAction] | None = None,
) -> dict[str, dict[str, Any]]:
    """Resolve damage, shields, healing, and death for every participant.

    ``annotate=False`` skips the per-event diagnostic fields that only the
    serialized public receipt reads (pair/live damage, overkill, healing
    receipts); every survival number and every field the breakdown sums —
    including each event's applied ``damage`` — is written either way.
    ``receipt_events`` is an optional outgoing ledger used only by receipt
    callers; when supplied, stateful redirect/deferred clones are mirrored
    beside their source packet without changing score-only inputs.
    ``typed_actions`` maps an event dict's identity to its packet-compiled
    :class:`SurvivalAction` (issue #169); a hit pairs the cached action
    with the live dict instead of re-deriving every typed field, and any
    event the expansion replaced or authored converts fresh.
    """
    combatant_list = list(combatants)
    combatant_by_id = {
        combatant.participant_id: combatant for combatant in combatant_list
    }
    reduction_profiles = {
        participant_id: healing_reduction_profiles(combatant.items)
        for participant_id, combatant in combatant_by_id.items()
    }
    # Serpent's Fang venom is attacker-owned: a participant whose build
    # holds the item wounds every target it damages for ``venom_duration``
    # seconds, cutting shields that target gains.  ``None`` fails closed.
    venom_profiles = {
        participant_id: serpents_fang_venom(
            combatant.items, is_melee=bool(combatant.stats.get("is_melee", True))
        )
        for participant_id, combatant in combatant_by_id.items()
    }
    states_list = build_states(combatant_list)
    states: dict[str, dict[str, Any]] = {
        combatant.participant_id: states_list[index]
        for index, combatant in enumerate(combatant_list)
    }
    index_of: dict[str, int] = {
        combatant.participant_id: index
        for index, combatant in enumerate(combatant_list)
    }

    # Normalize stateful packets before sorting.  Pair engines remain the
    # source of ordinary damage values; these transforms only consume
    # explicitly authored metadata on a packet and therefore fail closed
    # when a mechanic has no trigger/timing contract.
    expanded_incoming: dict[str, list[dict[str, Any]]] = defaultdict(list)
    expanded_healing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    redirect_children: dict[str, dict[str, Any]] = {}
    typed_lookup = dict(typed_actions) if typed_actions else None
    for participant_id, events in healing.items():
        bucket = expanded_healing[participant_id]
        for event in events:
            clone = dict(event)
            if typed_lookup is not None:
                cached_action = typed_lookup.get(id(event))
                if cached_action is not None:
                    typed_lookup[id(clone)] = cached_action
            bucket.append(clone)

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

    # Only a Death's Dance holder can stamp deferral metadata; resolving the
    # holders once keeps the per-event loop below to plain marker checks.
    deferral_holders = {
        participant_id: combatant
        for participant_id, combatant in combatant_by_id.items()
        if float(getattr(combatant.defenses, "damage_deferral_fraction", 0.0) or 0.0)
        > 0.0
    }
    for participant_id, events in incoming.items():
        for original in events:
            event = original
            target_id = str(event.get("target", participant_id))
            if "redirect_fraction" not in event:
                redirect_fraction = 0.0
                redirect_target = ""
            else:
                try:
                    redirect_fraction = float(
                        event.get("redirect_fraction", 0.0) or 0.0
                    )
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
            target_defenses = (
                deferral_holders.get(target_id) if deferral_holders else None
            )
            if (
                target_defenses is not None
                and not event.get("_deferred")
                and str(event.get("damage_type", "")) in {"physical", "magic"}
                and float(event.get("damage", 0.0) or 0.0) > 0.0
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
            if "deferred_fraction" not in event:
                deferred_fraction, deferred_duration, deferred_ticks = 0.0, 0.0, 0
            else:
                try:
                    deferred_fraction = float(
                        event.get("deferred_fraction", 0.0) or 0.0
                    )
                    deferred_duration = float(
                        event.get("deferred_duration", 0.0) or 0.0
                    )
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
        # E8d follow-up: the revive source is the champion's own passive when
        # the module declares one (Anivia Rebirth, Zac Cell Division, Zilean
        # Chronoshift); Guardian Angel remains the item-source label.
        revive_source = (
            str(getattr(defenses, "revive_source", "") or "")
            or "Guardian Angel (Rebirth)"
        )
        revive_key = (
            f"revive_{revive_source.replace(' ', '_')}"
            if revive_source != "Guardian Angel (Rebirth)"
            else "revive_Guardian Angel"
        )
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
                    "source": revive_source,
                    "source_key": revive_key,
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

    # Warmog's Heart is a live combat-state gate; the shared author below
    # builds the exact tick events for any active holder.
    for combatant in combatant_list:
        for event in _warmog_heart_tick_events(combatant, duration):
            _append_ordered_heal(combatant.participant_id, event)

    actions: list[SurvivalAction] = []
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
                survival_action_from_event(
                    event,
                    priority,
                    index_of[participant_id],
                    index_of,
                    subject_id=participant_id,
                )
            )
    # Damage resolves before self-healing and sourced recovery at the same
    # timestamp, while shields remain before damage above. Reactive
    # strike-back damage (Thorns) resolves after the strikes that
    # triggered it but still before same-timestamp healing.  Pair packets
    # carry their precomputed key (``_sk``) and their typed actions
    # (issue #169) — a cached conversion pairs with the live dict here;
    # events authored outside a packet (thorns strike-backs, redirect and
    # deferred clones, revive candidates) convert fresh.
    for participant_id, events in incoming.items():
        subject = index_of[participant_id]
        for event in events:
            cached = typed_lookup.get(id(event)) if typed_lookup is not None else None
            if cached is not None:
                actions.append(cached._replace(event=event))
                continue
            phase = 0.5 if event.get("_reactive") else 0.0
            actions.append(
                survival_action_from_event(
                    event,
                    phase,
                    subject,
                    index_of,
                    subject_id=participant_id,
                )
            )
    for participant_id, events in healing.items():
        subject = index_of[participant_id]
        for event in events:
            cached = typed_lookup.get(id(event)) if typed_lookup is not None else None
            if cached is not None:
                actions.append(cached._replace(event=event))
                continue
            actions.append(
                survival_action_from_event(
                    event,
                    1.0,
                    subject,
                    index_of,
                    subject_id=participant_id,
                )
            )
    actions.sort(key=itemgetter(0))

    # Knight's Vow's holder gate keys the child (redirected) action by its
    # parent's event id — the clone's ``_trigger_event_id`` — so the shared
    # walk can cancel it beside the direct share.
    redirect_children_actions = {
        str(child.event["_trigger_event_id"]): child
        for child in actions
        if child.redirected
        and child.event is not None
        and child.event.get("_trigger_event_id") is not None
    }
    ledger = ReceiptLedger(
        actions=actions,
        index_of=index_of,
        annotating=annotate,
        expanded_healing=expanded_healing,
        healing=healing if isinstance(healing, MutableMapping) else None,
    )
    ctx = TransitionContext(
        duration=duration,
        states=states_list,
        combatants=combatant_list,
        index_of=index_of,
        ledger=ledger,
        venom_profiles=[
            venom_profiles.get(combatant.participant_id) for combatant in combatant_list
        ],
        reduction_profiles=[
            reduction_profiles.get(combatant.participant_id)
            for combatant in combatant_list
        ],
        redirect_children=redirect_children_actions,
    )
    # Issue #137: one kernel, two adapters.  This walk is the receipt
    # adapter (annotating events, scheduling walk-authored recovery); the
    # optimizer score path drives the identical kernel through
    # ``ScoreLedger`` with no annotations and parallel-array accumulation.
    run_survival_walk(actions, ctx)
    finalize_states(states_list, duration)
    return assemble_survival_rows(states_list, combatant_list)


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
        # The main champion's wound-declaring sources are champion-fixed;
        # derived once per search instead of once per evaluation.
        "main_champion_wounds",
        # Issue #137: set when search-invariant compilation (roster pairs or
        # a signature panel) hit an unrepresentable transition; the compiled
        # path is then skipped for the rest of the search.
        "uncompilable",
    )

    def __init__(self) -> None:
        self.panels: dict[tuple[Any, ...], "_SignaturePanel"] = {}
        self.uncompilable = False
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
        self.main_champion_wounds: dict[str, Any] | None = None


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
    # Issue #137: the roster is search-invariant, so a loadout the compiled
    # kernel cannot represent poisons the whole context.  Checked BEFORE any
    # pair fight runs so the fallback costs nothing beyond the capability
    # scan.  (Defense fields are already excluded by the dispatch
    # pre-check; this covers walk-authored item mechanics.)  Warmog's Heart
    # is exempt: the roster holder's ticks compile into the base panel
    # below (issue #169).
    for loadout in (*enemies, *allies):
        item_receipt = _uncompilable_item_receipt(
            loadout.item_data,
            loadout_stats=loadout.stats,
            warmog_ticks_compiled=True,
        )
        if item_receipt is not None:
            raise UncompilableActionError(
                receipt=f"roster:{loadout.champion_data.get('name', '')}:{item_receipt}",
                source=str(loadout.champion_data.get("name", "")),
                invariant=True,
            )
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
    # Every pair fight carries its legacy roster-target allocation: the
    # ordered defender lists are [*enemies] for main/ally attackers and
    # [main, *allies] for enemy attackers, exactly like the receipt
    # composition's attack groups.  Secondary-target item branches
    # (cleaves, actives) price against these fields, and both paths share
    # one pair cache, so the params must be identical (issue #169).
    for defender_index, defender in enumerate(enemy_actors):
        pair_params = replace(
            main_params,
            enforce_resource_limits=True,
            roster_target_index=defender_index,
            roster_target_count=len(enemy_actors),
            **_target_overrides(defender),
        )
        pair_params.validate_for_champion(champion_name, level)
        context.main_pair_params.append((defender, pair_params))
    for attacker in context.roster_actors:
        attacker_params = context.actor_params[attacker.participant_id]
        attacker_params.validate_for_champion(
            str(attacker.champion_data.get("name", "")), attacker.level
        )
        if attacker.team == "ally":
            ordered_defenders = list(enumerate(enemy_actors))
            defender_count = len(enemy_actors)
        else:
            ordered_defenders = [
                (1 + position, defender)
                for position, defender in enumerate(ally_actors)
            ]
            defender_count = 1 + len(ally_actors)
        for defender_index, defender in ordered_defenders:
            context.roster_pair_params[
                (attacker.participant_id, defender.participant_id)
            ] = replace(
                attacker_params,
                enforce_resource_limits=True,
                roster_target_index=defender_index,
                roster_target_count=defender_count,
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
    # Roster position mirrors the legacy attack groups: enemies are indexed
    # from 0 for allied attackers, while an enemy attacker's ordered
    # defenders are [main, *allies], so the first ally sits at index 1.
    enemy_index = {
        defender.participant_id: index for index, defender in enumerate(enemy_actors)
    }
    ally_index = {
        defender.participant_id: index for index, defender in enumerate(ally_actors)
    }
    for attacker, defender in base_pairs:
        cache_key = (attacker.participant_id, defender.participant_id)
        defender_index = (
            enemy_index.get(defender.participant_id, 0)
            if attacker.team == "ally"
            else 1 + ally_index.get(defender.participant_id, -1)
        )
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
                defender_index,
                champion_data=attacker.champion_data,
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
            # An enemy attacker's ordered pair list is [main, *allies], so
            # the legacy dedup always keeps its main-pair copy — which
            # lives in the signature panel, not here.  Skip the ally-pair
            # copies; the engine may price them differently per defender
            # (issue #169, Dr. Mundo's Maximum Dosage).
            suppress_actor_wide_heals=attacker.team == "enemy",
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
    # A roster holder's active Warmog's Heart ticks are search-invariant:
    # author the same events the receipt walk schedules and convert them
    # through the same typed-action constructor, once per search (issue
    # #169).  The candidate's own Warmog still falls back per evaluation.
    for actor in context.roster_actors:
        actor_i = context.index_of[actor.participant_id]
        for event in _warmog_heart_tick_events(actor, params.fight_duration_seconds):
            base.actions.append(
                survival_action_from_event(
                    event,
                    1.0,
                    actor_i,
                    context.index_of,
                    subject_id=actor.participant_id,
                )
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
    ally_count = sum(1 for actor in roster if actor.team == "ally")
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
                        # The legacy attack group's ordered defenders for an
                        # enemy attacker are [main, *allies] (issue #169).
                        roster_target_index=0,
                        roster_target_count=1 + ally_count,
                        **_target_overrides(main),
                    ),
                    validated=True,
                ),
                attacker.participant_id,
                "main",
                champion_data=attacker.champion_data,
            )
            pair_result_cache[cache_key] = packet
        attacker_i = context.index_of[attacker.participant_id]
        # This main-pair packet carries the attacker's legacy-kept
        # actor-wide heal copies (the ally-pair copies were suppressed in
        # the base panel).  The dedup map is a per-signature copy: a sig
        # build may never grow the shared base sets, or a key recorded by
        # one signature would silently drop another signature's only copy.
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
    # Issue #137: a search-invariant compilation failure (roster pair or
    # signature panel) poisons the context; every later evaluation raises
    # immediately instead of re-attempting the compiled path.
    if getattr(context, "uncompilable", False):
        raise UncompilableActionError(
            receipt="context_marked_uncompilable",
            source=str(champion_data.get("name", "")),
        )
    # The main candidate's own loadout is candidate-dependent: a failure
    # here falls back per evaluation and never poisons the context.  Checked
    # before any pair fight so the fallback costs only the capability scan.
    main_item_receipt = _uncompilable_item_receipt(items)
    if main_item_receipt is not None:
        raise UncompilableActionError(
            receipt=f"main:{main_item_receipt}",
            source=str(champion_data.get("name", "")),
        )
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
        try:
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
        except UncompilableActionError as exc:
            # Roster pair compilation is search-invariant: one failure means
            # the compiled path can never be used for this search.
            raise UncompilableActionError(
                receipt=exc.receipt, source=exc.source, invariant=True
            ) from exc
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
        try:
            panel = _build_signature_panel(
                context, main, params, pair_result_cache, signature, all_actors
            )
        except UncompilableActionError as exc:
            # Signature-panel compilation is invariant per defensive
            # signature; mark the whole context so later evaluations skip
            # the compiled path instead of re-raising per candidate.
            raise UncompilableActionError(
                receipt=exc.receipt, source=exc.source, invariant=True
            ) from exc
        context.panels[signature] = panel

    fresh = _WalkCompiler(panel.n_actions)
    main_profiles = healing_reduction_profiles(main.items)
    main_packs = {
        damage_type: _grievous_pack(main_profiles, damage_type)
        for damage_type in ("physical", "magic", "true")
    }
    main_champion_wounds = context.main_champion_wounds
    if main_champion_wounds is None:
        main_champion_wounds = {
            str(packet.get("source_key", "")): packet
            for packet in champion_grievous_wound_sources(main.champion_data)
        }
        context.main_champion_wounds = main_champion_wounds
    reusable_stats = main.stats if reuse_main_stats else None
    heal_dedup: dict[tuple[str, float], float] = {}
    first_result = None
    enemy_actors = [actor for actor in roster if actor.team == "enemy"]
    for defender_index, (defender, pair_params) in enumerate(context.main_pair_params):
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
            defender_index,
            champion_wounds=main_champion_wounds,
        )
    if first_result is not None:
        # The item support scan reads per-event target/id fields that only
        # pair enrichment adds (Black Cleaver Carve, Bloodsong), plus the
        # first pair's takedown synthesis.  Give it the same view the
        # receipt composition passes — a template it authors either
        # compiles or fails closed, never silently vanishes (issue #169).
        # A tuple-ledger fight needs none of this: the pipeline's tuple
        # predicate excludes every event-scanning holder.
        if first_result.get("damage_events_tuple") or not has_event_view_support_items(
            main.items
        ):
            # Tuple-ledger fights carry no scannable rows by construction,
            # and a holder with no event-view item never reads the enriched
            # per-event copy — both scan the plain engine result.
            support_templates = _support_effect_templates(
                main, first_result, all_actors
            )
        else:
            first_defender_id = context.main_pair_params[0][0].participant_id
            support_scan_events = [
                {
                    **event,
                    "target": first_defender_id,
                    "_event_id": f"main:{first_defender_id}:{index}",
                }
                for index, event in enumerate(first_result.get("damage_events", []))
            ]
            support_templates = _support_effect_templates(
                main,
                first_result,
                all_actors,
                damage_events=support_scan_events,
                target_id=first_defender_id,
            )
        fresh.add_support_templates(support_templates, 0, context.index_of)
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

    # Grey-health consume heals (E8a) are compiled from the same incoming
    # (enemy -> main, plus enemy thorns) and outgoing (main) damage actions
    # the walk applies, with the candidate's own stats/ranks, so the
    # compiled score walk matches the ordered receipt's fixed amounts.
    grey_summary: dict[str, float] = {}
    if (
        str(champion_data.get("name", "")) in GREY_HEALTH_RULE_CHAMPIONS
        and enemy_actors
    ):
        sig_actions = panel.sig.actions
        # Auto-attack packets expose no ``raw_damage`` (the engine emits it
        # only for authored ability hits), so the compiled rows carry a zero
        # there; mirror the ordered ledger's ``raw_damage or damage``
        # fallback so both paths price Mordekaiser's pre-mitigation term
        # identically.
        in_records = [
            (
                float(action.time),
                float(action.amount),
                (
                    float(action.raw_damage)
                    if float(action.raw_damage) > 0.0
                    else float(action.amount)
                ),
            )
            for action in sig_actions
            if action.kind in (ActionKind.PLAIN_DAMAGE, ActionKind.DAMAGE)
            and action.subject == 0
            and float(action.time) <= duration
        ]
        in_records.extend(
            (
                float(action.time),
                float(action.amount),
                (
                    float(action.raw_damage)
                    if float(action.raw_damage) > 0.0
                    else float(action.amount)
                ),
            )
            for action in fresh.actions
            if action.kind in (ActionKind.PLAIN_DAMAGE, ActionKind.DAMAGE)
            and action.subject == 0
            and float(action.time) <= duration
        )
        out_records = [
            (
                float(action.time),
                float(action.amount),
                (
                    float(action.raw_damage)
                    if float(action.raw_damage) > 0.0
                    else float(action.amount)
                ),
            )
            for action in fresh.actions
            if action.kind in (ActionKind.PLAIN_DAMAGE, ActionKind.DAMAGE)
            and action.attacker == 0
            and float(action.time) <= duration
        ]
        main_cast_timeline = (
            list(first_result.get("cast_timeline", []))
            if first_result is not None
            else []
        )
        grey_heals, grey_summary = _grey_health_receipts(
            str(champion_data.get("name", "")),
            champion_data,
            level,
            main.stats,
            in_records,
            out_records,
            main_cast_timeline,
            duration,
            len(enemy_actors),
            params.ability_ranks,
        )
        for index, (heal_time, source, amount) in enumerate(grey_heals):
            aidx = fresh.next_aidx
            fresh.next_aidx += 1
            event_id = f"main:grey:{source}:{index}"
            sort_key = _action_key(
                float(heal_time),
                1.0,
                "main",
                {"attacker": "main", "_event_id": event_id, "source": source},
            )
            fresh.actions.append(
                SurvivalAction(
                    sort_key=sort_key,
                    time=float(heal_time),
                    phase=1.0,
                    kind=ActionKind.HEAL,
                    subject=0,
                    attacker=0,
                    aidx=aidx,
                    amount=float(amount),
                    source_key=str(source),
                    source=str(source),
                    event_id=event_id,
                )
            )

    actions = panel.sorted_actions + sorted(fresh.actions, key=itemgetter(0))
    actions = coalesce_darius_q_heals(actions)
    # Sourced revives (champion passives) author one candidate per incoming
    # damaging packet, mirroring the receipt walk's pre-walk expansion; the
    # kernel applies the earliest one only when the participant is dead.
    revive_actions, n_actions = revive_candidate_actions(
        actions, all_actors, fresh.next_aidx
    )
    if revive_actions:
        actions = actions + revive_actions
    actions.sort(key=itemgetter(0))
    # Issue #137: the score adapter arms the same canonical state dicts as
    # the receipt walk and drives the identical kernel; the only difference
    # is the ledger's parallel-array observation below.
    states = build_states(all_actors)
    ledger = ScoreLedger(n_actions)
    venom_packs = [
        serpents_fang_venom(
            list(actor.items), is_melee=bool(actor.stats.get("is_melee", True))
        )
        for actor in all_actors
    ]
    ctx = TransitionContext(
        duration=duration,
        states=states,
        combatants=all_actors,
        index_of=context.index_of,
        ledger=ledger,
        venom_profiles=venom_packs,
    )
    run_survival_walk(actions, ctx)
    finalize_states(states, duration)
    rows_by_id = assemble_survival_rows(states, all_actors)
    survival_rows = [rows_by_id[actor.participant_id] for actor in all_actors]
    applied = ledger.applied
    if grey_summary.get("source"):
        survival_rows[0]["grey_health_stored"] = round(
            float(grey_summary.get("grey_health_stored", 0.0)), 6
        )
        survival_rows[0]["grey_health_consumed"] = round(
            float(grey_summary.get("grey_health_consumed", 0.0)), 6
        )
        survival_rows[0]["grey_health_source"] = str(grey_summary["source"])

    count = len(all_actors)
    base = context.base_compiler
    support_value, healing_output = accumulate_support_values(
        applied,
        fresh.support_entries,
        base.support_entries,
        panel.sig.support_entries,
        count,
    )

    public_breakdown = []
    sig_damage_order = panel.sig.damage_order
    base_damage_order = base.damage_order
    fresh_damage_order = fresh.damage_order
    fresh_thorns_order = fresh.thorns_order
    base_thorns_order = base.thorns_order
    totals = accumulate_damage_totals(
        survival_rows,
        applied,
        sig_damage_order=sig_damage_order,
        base_damage_order=base_damage_order,
        fresh_damage_order=fresh_damage_order,
        fresh_thorns_order=fresh_thorns_order,
        base_thorns_order=base_thorns_order,
        count=count,
    )
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
        total = totals[index]
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
    _resource_restores: Mapping[str, tuple[tuple[float, float], ...]] | None = None,
    _resource_pass: bool = False,
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
    if _resource_restores is not None:
        params = replace(
            params,
            resource_restore_events=tuple(_resource_restores.get("main", ())),
        )

    if (
        search_context is not None
        and not include_receipt
        and pair_result_cache is not None
        and enemies
        # Issue #137: the dispatch no longer names items and no longer scans
        # defense objects — the kernel is one implementation, so a defense-
        # armed mechanic (threshold lifelines, reactive shields, stasis,
        # FoN/Jak'Sho stacks, deferral/Defy, ...) rides the compiled walk
        # exactly like the receipt walk.  Grievous Wounds builds ride it too
        # (issue #169): the panel compiles the candidate's and the roster's
        # packs from the same ``resolve_grievous`` the receipt walk resolves
        # per event.  Every unrepresentable mechanic fails closed INSIDE the
        # compiler, which raises UncompilableActionError and falls back
        # below.
    ):
        try:
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
        except UncompilableActionError as exc:
            # A transition the score kernel cannot represent must never be
            # silently dropped (issue #137).  Mark search-invariant failures
            # so later evaluations skip the compiled path; candidate-local
            # failures fall back per evaluation.
            if exc.invariant:
                search_context.uncompilable = True
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
    # Cached packets carry their typed actions (issue #169); the copies
    # composed below map back to them by identity so the survival walk
    # reuses each conversion instead of re-deriving it per evaluation.
    index_of = {actor.participant_id: i for i, actor in enumerate(all_actors)}
    typed_actions: dict[int, SurvivalAction] = {}
    outgoing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    incoming: dict[str, list[dict[str, Any]]] = defaultdict(list)
    healing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    support_effects: dict[str, list[dict[str, Any]]] = defaultdict(list)
    ordered_item_support_ids: set[str] = set()
    support_attached: set[str] = set()
    # The main champion's own cast timeline (from its first outgoing pair
    # fight) drives grey-health consume timing (Rengar W, Mordekaiser W).
    main_cast_timeline: list[dict[str, Any]] = []
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
            actor_params = _actor_params_with_resource_restores(
                params, attacker, _resource_restores
            )
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
                        defender_index,
                        champion_data=attacker.champion_data,
                    )
                    if cacheable and pair_result_cache is not None:
                        pair_result_cache[cache_key] = packet
                    if attacker.participant_id == "main" and not main_cast_timeline:
                        main_cast_timeline = packet["result"].get("cast_timeline", [])
                result = packet["result"]
                coverage_reports.append(result.get("timeline_coverage", {}))
                # A packet that lives in the cache serves later evaluations,
                # so this one only takes copies (the walk mutates its rows).
                # A single-use packet's rows are appended directly.
                copy_templates = cacheable and pair_result_cache is not None
                packet_typed = (
                    _packet_typed_actions(packet, index_of) if copy_templates else None
                )
                attacker_outgoing = outgoing[attacker.participant_id]
                defender_incoming = incoming[defender.participant_id]
                for template in packet["events"]:
                    enriched = dict(template) if copy_templates else template
                    if packet_typed is not None:
                        cached_action = packet_typed.get(id(template))
                        if cached_action is not None:
                            typed_actions[id(enriched)] = cached_action
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
                    heal_copy = dict(template) if copy_templates else template
                    if packet_typed is not None:
                        cached_action = packet_typed.get(id(template))
                        if cached_action is not None:
                            typed_actions[id(heal_copy)] = cached_action
                    attacker_healing.append(heal_copy)
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
        actor_params = _actor_params_with_resource_restores(
            params, attacker, _resource_restores
        )
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

    # Eternity's mana restore is the one sustain branch whose state changes
    # future ability admission.  The first pass supplies the complete
    # incoming champion ledger; rerun the pair fights once with those exact
    # (time, pre-mitigation-damage × typed ratio) restores attached to each
    # Catalyst holder.  A second cache is intentional: cached baseline
    # packets were priced without the external resource events.
    if not _resource_pass:
        resource_restores: dict[str, tuple[tuple[float, float], ...]] = {}
        for actor in all_actors:
            restores, complete = _catalyst_resource_restores(
                actor, incoming, params.fight_duration_seconds
            )
            if not complete:
                raise ValueError(
                    f"Catalyst of Aeons resource ledger is unavailable for "
                    f"{actor.participant_id}: an incoming champion packet "
                    "does not expose finite pre-mitigation damage."
                )
            if restores:
                resource_restores[actor.participant_id] = restores
        if resource_restores:
            return build_participant_timeline(
                champion_data,
                level,
                items,
                params,
                main_stats=main_stats,
                main_defenses=main_defenses,
                enemies=enemies,
                allies=allies,
                focus_participant_id=focus_participant_id,
                pair_result_cache={},
                include_receipt=include_receipt,
                reuse_main_stats=reuse_main_stats,
                search_context=None,
                _resource_restores=resource_restores,
                _resource_pass=True,
            )

    # Knight's Vow is the one ally packet whose trigger lives on the
    # recipient's incoming/outgoing ledgers rather than on a heal/shield cast.
    # Resolve its single explicit Worthy tether after all pair events exist so
    # the redirect and holder-heal receipts share the same event order.
    schedule_knights_vow(all_actors, incoming, outgoing, support_effects)

    _coalesce_darius_q_heals(healing)
    _schedule_thorns_events(all_actors, incoming, outgoing)
    _schedule_authored_reactive_events(incoming, outgoing)

    # Grey-health receipts (E8a): when the main is the defender and is a
    # grey-health champion, the incoming ledger accumulates the sourced %
    # of post-mitigation damage taken and the champion's active pays the
    # stored pool back as a heal.  Authored after every incoming source
    # (pair fights, thorns, reactive) exists so the receipts see the same
    # event set the walk applies; the consume heals carry fixed sourced
    # amounts and ride the ordinary heal application (Grievous, overheal
    # caps), matching the E1 ``_heal_from_damage`` plumbing.
    grey_summary: dict[str, float] = {}
    grey_heals: list[dict[str, Any]] = []
    main_name = str(champion_data.get("name", ""))
    if main_name in GREY_HEALTH_RULE_CHAMPIONS and enemy_actors:
        duration = params.fight_duration_seconds
        main_incoming = [
            event
            for event in incoming["main"]
            if float(event.get("time", 0.0)) <= duration
        ]
        main_outgoing = [
            event
            for event in outgoing["main"]
            if float(event.get("time", 0.0)) <= duration
        ]
        in_records = [
            (
                float(event.get("time", 0.0)),
                float(event.get("damage", 0.0) or 0.0),
                float(event.get("raw_damage", event.get("damage", 0.0)) or 0.0),
            )
            for event in main_incoming
        ]
        out_records = [
            (
                float(event.get("time", 0.0)),
                float(event.get("damage", 0.0) or 0.0),
                float(event.get("raw_damage", event.get("damage", 0.0)) or 0.0),
            )
            for event in main_outgoing
        ]
        grey_heals, grey_summary = _grey_health_receipts(
            main_name,
            champion_data,
            level,
            main_stats,
            in_records,
            out_records,
            main_cast_timeline,
            duration,
            len(enemy_actors),
            params.ability_ranks,
        )
        for index, (heal_time, source, amount) in enumerate(grey_heals):
            heal_event: dict[str, Any] = {
                "time": float(heal_time),
                "amount": float(amount),
                "source": source,
                "kind": "champion_ability",
                "attacker": "main",
                "_event_id": f"main:grey:{source}:{index}",
                "_grey_health": True,
            }
            heal_event["_sk"] = _action_key(float(heal_time), 1.0, "main", heal_event)
            healing["main"].append(heal_event)
        for event in main_incoming:
            receipt = _grey_health_event_receipt(
                main_name,
                level,
                main_stats,
                len(enemy_actors),
                event,
                incoming=True,
                ability_ranks=params.ability_ranks,
            )
            if receipt is not None and receipt > 0.0:
                event["grey_health_stored"] = round(receipt, 6)
        for event in main_outgoing:
            receipt = _grey_health_event_receipt(
                main_name,
                level,
                main_stats,
                len(enemy_actors),
                event,
                incoming=False,
                ability_ranks=params.ability_ranks,
            )
            if receipt is not None and receipt > 0.0:
                event["grey_health_stored"] = round(receipt, 6)

    survival = _simulate_survival(
        all_actors,
        incoming,
        healing,
        support_effects,
        params.fight_duration_seconds,
        annotate=include_receipt,
        receipt_events=outgoing if include_receipt else None,
        typed_actions=typed_actions,
    )
    if grey_summary.get("source"):
        survival["main"]["grey_health_stored"] = round(
            float(grey_summary.get("grey_health_stored", 0.0)), 6
        )
        survival["main"]["grey_health_consumed"] = round(
            float(grey_summary.get("grey_health_consumed", 0.0)), 6
        )
        survival["main"]["grey_health_source"] = str(grey_summary["source"])
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
                "raw_damage": round(
                    float(event.get("raw_damage", event.get("damage", 0.0))), 1
                ),
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
                    {
                        "reactive_shield_triggered": dict(
                            event["reactive_shield_triggered"]
                        )
                    }
                    if event.get("reactive_shield_triggered")
                    else {}
                ),
                **(
                    {
                        "maw_lifeline_omnivamp_activated": round(
                            float(event["maw_lifeline_omnivamp_activated"]), 3
                        )
                    }
                    if event.get("maw_lifeline_omnivamp_activated") is not None
                    else {}
                ),
                **(
                    {
                        "threshold_shield_expires_at": round(
                            float(event["threshold_shield_expires_at"]), 3
                        )
                    }
                    if event.get("threshold_shield_expires_at") is not None
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
                        "incoming_damage_multiplier": round(
                            float(event["incoming_damage_multiplier"]), 3
                        )
                    }
                    if event.get("incoming_damage_multiplier") is not None
                    else {}
                ),
                **(
                    {"incoming_damage_source": str(event["incoming_damage_source"])}
                    if event.get("incoming_damage_source")
                    else {}
                ),
                **(
                    {
                        "incoming_damage_reduction": round(
                            float(event["incoming_damage_reduction"]), 1
                        )
                    }
                    if event.get("incoming_damage_reduction") is not None
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
                    {"venom": dict(event["venom"])}
                    if event.get("venom") is not None
                    else {}
                ),
                **(
                    {"skipped_reason": str(event["skipped_reason"])}
                    if event.get("skipped_reason")
                    else {}
                ),
                **(
                    {"grey_health_stored": round(float(event["grey_health_stored"]), 1)}
                    if event.get("grey_health_stored") is not None
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
                **({"grey_health": True} if event.get("_grey_health") else {}),
                **(
                    {"charges": int(event["charges"])}
                    if event.get("charges") is not None
                    else {}
                ),
                **(
                    {
                        "ichorshield_generated": round(
                            float(event["ichorshield_generated"]), 1
                        )
                    }
                    if event.get("ichorshield_generated") is not None
                    else {}
                ),
                **(
                    {"ichorshield_total": round(float(event["ichorshield_total"]), 1)}
                    if event.get("ichorshield_total") is not None
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
                **(
                    {"source_event_id": str(event["_source_event_id"])}
                    if event.get("_source_event_id") is not None
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
                            "current_mana",
                            "mana_threshold",
                            "nearby_enemy_count",
                            "multi_target_multiplier",
                            "cooldown_until",
                            "gold_amount",
                            "ward_uses",
                            "quest_threshold",
                            "minion_kills",
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
                            "completion_granted",
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
                        for key in (
                            "resistance_type",
                            "owner",
                            "range_assumption",
                            "trigger_kind",
                            "source_url",
                        )
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
                    {"venom": dict(event["venom"])}
                    if event.get("venom") is not None
                    else {}
                ),
                **(
                    {"source_revision_id": int(event["source_revision_id"])}
                    if event.get("source_revision_id") is not None
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
