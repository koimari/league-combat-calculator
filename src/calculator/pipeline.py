"""Shared entry point for a complete champion fight calculation.

Consumers provide already-loaded champion and item data. This module owns the
cross-domain orchestration from stats through champion ability parsing into the
champion-agnostic fight engine; data fetching remains with each consumer.
"""

import math
import re
from dataclasses import dataclass, replace
from collections.abc import Mapping
from typing import Any

from .champions import (
    RESERVED_OPTION_KEYS,
    get_champion_cast_dependencies,
    get_champion_cast_order,
    get_champion_ultimate_recasts,
    get_custom_cast_order_unavailable_reason,
    parse_champion_abilities,
)
from .rotation_resolver import (
    build_rotation_receipt,
    detect_aoe_cap,
    resolve_cast_order,
)
from .champions.skill_orders import get_ability_rank
from .damage import (
    FightConfig,
    calculate_fight_damage,
    split_auto_vs_ability,
    split_by_damage_type,
)
from . import item_effects
from . import resource_ledger
from .interpreters import sustain
from .interpreters.sustain import declared_sustain
from .item_behavior import (
    PostMitigationHealRule,
    ResourceDrainRule,
    SustainStat,
)
from .item_effects import resolve_damage_effects, validate_item_input_options
from .healing import derive_self_healing, self_heal_rule_owner
from .ledger_projection import LedgerInputs, ResultProjection, ledger_projection
from .support_effects import derive_self_state_effects
from .auto_attack_policy import (
    AUTO_ATTACK_UPTIME_MODE_CALCULATED,
    AUTO_ATTACK_UPTIME_MODE_EXPLICIT,
    AUTO_ATTACK_UPTIME_MODE_LEGACY,
    AUTO_ATTACK_UPTIME_MODES,
    resolve_auto_attack_policy,
)
from .role_quests import max_champion_level, validate_role
from .request_parsing import (
    request_index_map,
    request_bool as _request_bool,
    request_int as _request_int,
    request_string,
)
from .rune_effects import (
    KeystoneConquerorEffect,
    KeystoneFleetEffect,
    RuneHealEffect,
    RuneHealTrigger,
    RunePage,
    resolve_rune,
    resolve_rune_page,
    validate_keystone_options,
    validate_rune_page,
)
from .stats import calculate_total_stats, get_item_stats
from .trigger_stream import applies_control
from .data_registry import data_version
from .cast_dependency import (
    BASE_CAST_SLOTS,
    check_order_satisfies_dependencies,
    expand_user_order,
    orderable_slots,
)

DEFAULT_TARGET: dict[str, float] = {
    "health": 1000.0,
    "bonus_health": 0.0,
    "armor": 100.0,
    "mr": 100.0,
}
DEFAULT_FIGHT_DURATION = 8.0
DEFAULT_AUTO_ATTACK_UPTIME = 0.8
DEFAULT_AUTO_ATTACK_UPTIME_MODE = AUTO_ATTACK_UPTIME_MODE_CALCULATED
DEFAULT_FIGHT_MODE = "one_rotation"
ONE_ROTATION_DURATION = 5.0
MAX_ROTATIONS = 6
# The roster bounds live beside the other public request bounds rather than in
# scenario.py, which composes the roster: a support packet's teammate index is
# checked here and the roster lists are parsed there, and one of the two would
# otherwise spell the other's limit as a literal.
MAX_ENEMIES = 5
MAX_ALLIES = 4
PUBLIC_INPUT_LIMITS: dict[str, tuple[float, float]] = {
    # The prototype exposes up to six five-second rotations, so a timed
    # request must be able to represent the complete sequential window.
    "fight_duration": (1.0, 30.0),
    "auto_attack_uptime": (0.0, 1.0),
    "target_health": (1.0, 10_000.0),
    "target_bonus_health": (0.0, 10_000.0),
    "target_armor": (0.0, 500.0),
    "target_bonus_armor": (0.0, 500.0),
    "target_mr": (0.0, 500.0),
}
_PUBLIC_FIGHT_MODES = frozenset({"one_rotation", "time_based", "timed", "auto_only"})
_NONSTANDARD_RANK_CHAMPIONS = frozenset({"Elise", "Jayce", "Karma", "Nidalee", "Udyr"})


def rank_allocation_contract() -> dict[str, object]:
    """Return the backend-owned rank allocation modes for public clients."""
    return {
        "default": "manual",
        "by_champion": {
            champion: "level_derived"
            for champion in sorted(_NONSTANDARD_RANK_CHAMPIONS)
        },
    }


def _item_self_healing_events(
    result: Mapping[str, Any],
    items: list[Mapping[str, Any]] | None = None,
    fight_duration_seconds: float | None = None,
) -> list[dict[str, Any]]:
    """Materialize only timestamp-certified item self-heal packets.

    Spellblade item rows carry their accepted proc times alongside the
    amount-per-proc.  Rows without that complete receipt remain summary-only
    and are deliberately omitted here rather than being assigned a guessed
    timestamp; the participant ledger can therefore apply only exact item
    healing while the damage breakdown still records the source row.
    """
    events: list[dict[str, Any]] = []
    item_names = sorted({str(item.get("name", "")) for item in (items or ())})
    stats = result.get("champion_stats")
    stats = stats if isinstance(stats, Mapping) else {}
    damage_events = result.get("damage_events")
    damage_events = damage_events if isinstance(damage_events, list) else []
    duration = fight_duration_seconds
    if duration is None:
        schedule = result.get("auto_attack_schedule")
        if isinstance(schedule, Mapping):
            try:
                duration = float(schedule.get("window_seconds", 0.0))
            except (TypeError, ValueError):
                duration = 0.0
        else:
            duration = max(
                (
                    float(event.get("time", 0.0))
                    for event in damage_events
                    if isinstance(event, Mapping)
                ),
                default=0.0,
            )
    duration = max(0.0, float(duration or 0.0))

    # A post-mitigation heal is a *shape*, not an item: a declared share of
    # damage this build already dealt, paid straight back.  Unknown ability
    # scope is conservatively priced at the declared area/pet effectiveness
    # rather than being promoted as full.
    post_mitigation = declared_sustain(item_names, PostMitigationHealRule)
    if post_mitigation is not None:
        ratio = post_mitigation.value("ratio")
        reduced = post_mitigation.value("area_effectiveness")
        heal_events: list[dict[str, Any]] = []
        for event in damage_events:
            if not isinstance(event, Mapping):
                continue
            try:
                amount = float(event.get("damage", 0.0))
                time = float(event.get("time", 0.0))
            except (TypeError, ValueError):
                continue
            if amount <= 0.0 or not math.isfinite(amount) or not math.isfinite(time):
                continue
            source_key = str(event.get("source_key", ""))
            full_effect = bool(event.get("basic_attack")) or source_key.startswith(
                ("auto_attacks", "on_hit_")
            )
            effectiveness = 1.0 if full_effect else reduced
            heal_events.append(
                {
                    "time": time,
                    "amount": amount * ratio * effectiveness,
                    "trigger_source": source_key,
                    "effectiveness": effectiveness,
                }
            )
        if heal_events:
            events.extend(
                {
                    "time": event["time"],
                    "amount": event["amount"],
                    "source": f"{post_mitigation.owner} (Life Draining)",
                    "kind": "item_proc",
                    "healing_modifier": True,
                    "_trigger_source": event["trigger_source"],
                    "_trigger_time": event["time"],
                    "_trigger_sequence": index,
                    "effectiveness": event["effectiveness"],
                }
                for index, event in enumerate(heal_events)
                if event["amount"] > 0.0
            )

    # Drain restores mana first and only heals when the actor cannot gain
    # mana.  The result carries the end-of-window resource receipt, so a
    # manaless/full-resource actor is the only state for which a health heal
    # can be certified without inventing a starting-mana assumption.
    drain = declared_sustain(item_names, ResourceDrainRule)
    if drain is not None:
        max_mana = float(stats.get("max_mana", 0.0) or 0.0)
        remaining = float(result.get("resource_remaining", 0.0) or 0.0)
        can_only_heal = max_mana <= 0.0 or remaining >= max_mana - 1e-9
        if can_only_heal and duration > 0.0:
            base_rate = drain.value("restoration_per_second")
            combat_rate = drain.value("combat_restoration_per_second")
            combat_window = drain.value("combat_window")
            conversion = drain.value("health_conversion")
            tick = drain.value("tick_interval")
            champion_hits: list[float] = []
            for event in damage_events:
                if not isinstance(event, Mapping):
                    continue
                try:
                    hit_time = float(event.get("time", 0.0))
                    hit_damage = float(event.get("damage", 0.0) or 0.0)
                except (TypeError, ValueError):
                    continue
                if hit_damage > 0.0 and math.isfinite(hit_time):
                    champion_hits.append(hit_time)
            time = tick
            sequence = 0
            while time <= duration + 1e-9:
                boosted = any(
                    0.0 <= time - hit <= combat_window for hit in champion_hits
                )
                rate = combat_rate if boosted else base_rate
                events.append(
                    {
                        "time": round(time, 6),
                        "amount": rate * conversion,
                        "source": f"{drain.owner} (Drain)",
                        "kind": "item_proc",
                        "actor_wide": True,
                        "_trigger_sequence": sequence,
                    }
                )
                sequence += 1
                time += tick

    # Catalyst's Eternity heal is a projection of the typed mana resource
    # ledger's ACCEPTED spend receipts (P3 package 3A): the ledger is the
    # single authoritative current/max mana account, and the per-cast and
    # per-second heal caps are applied exactly once there, at the cast
    # timestamp, so every consumer (receipt walk and score-only walk)
    # emits byte-identical heal packets.  The public resource_ledger.catalyst
    # section carries the typed declaration and the heal rows; a fight
    # without the typed account (energy or manaless resource, or resource
    # limits disabled) cannot certify a MANA-spent heal and emits none —
    # an aggregate resource total is never converted into a guessed heal.
    if "Catalyst of Aeons" in item_names:
        ledger_section = result.get("resource_ledger")
        # A catalyst section is only ever built on a mana account, so its
        # presence answers the question even when the ledger row carries no
        # ``kind`` (a unit-level ledger built without the fight's identity).
        mana_account = isinstance(ledger_section, Mapping) and (
            str(ledger_section.get("kind", "")) == resource_ledger.RESOURCE_KIND_MANA
            or isinstance(ledger_section.get("catalyst"), Mapping)
        )
        if not mana_account:
            # A holder who spends no mana has no Eternity to price.  The
            # fight publishes a resource ledger either way -- Rengar's is a
            # Ferocity account -- so "no catalyst section" means two
            # different things, and only one of them is a defect: a MANA
            # account without one is the ledger failing to build the heal,
            # while any other kind is the mechanic being structurally
            # absent.  Certifying the difference here is what keeps a
            # manaless holder from failing a window it simply does not have.
            notes = result.get("notes")
            if isinstance(notes, list):
                kind = (
                    str(ledger_section.get("kind", ""))
                    if isinstance(ledger_section, Mapping)
                    else ""
                )
                notes.append(
                    "Catalyst of Aeons (Eternity): the holder spends no mana"
                    + (f" ({kind} resource)" if kind else "")
                    + "; the mana-spent heal is structurally zero, not "
                    "withheld."
                )
        else:
            catalyst_section = ledger_section.get("catalyst")
            if not isinstance(catalyst_section, Mapping):
                raise ValueError(
                    "Catalyst of Aeons is equipped but the typed mana "
                    "resource ledger carries no catalyst section; the "
                    "Eternity heal cannot be certified."
                )
            heal_rows = catalyst_section.get("heals")
            if not isinstance(heal_rows, list):
                raise ValueError(
                    "Catalyst of Aeons resource ledger section has no heals "
                    "list; the Eternity heal cannot be certified."
                )
            for heal in heal_rows:
                if not isinstance(heal, Mapping):
                    continue
                try:
                    event_time = float(heal.get("time", 0.0))
                    amount = float(heal.get("amount", 0.0) or 0.0)
                except (TypeError, ValueError):
                    continue
                if (
                    not math.isfinite(event_time)
                    or not math.isfinite(amount)
                    or amount <= 0.0
                ):
                    continue
                events.append(
                    {
                        "time": event_time,
                        "amount": amount,
                        "source": "Catalyst of Aeons (Eternity)",
                        "kind": "item_proc",
                        "_trigger_source": str(heal.get("slot", "cast")),
                        "_trigger_time": event_time,
                        "_trigger_sequence": int(heal.get("ordinal", 1) or 1) - 1,
                    }
                )

    # Item-provided health regeneration is a timestamped stat contribution.
    # Keep champion base regeneration out of the item self-heal stream (the
    # public one-pair result has historically exposed only sourced packets),
    # while still applying every item's flat/percent contribution in the
    # coupled survival ledger.  The contribution is computed from typed item
    # accessors, not from a call-site literal.
    item_regen_flat = 0.0
    item_regen_percent = 0.0
    for item in items or ():
        # Pass the cached item dict itself: a defensive copy would defeat
        # get_item_stats' identity memo and re-validate the full stat map
        # on every optimizer evaluation.
        item_stats = get_item_stats(item if isinstance(item, dict) else dict(item))
        item_regen_flat += float(item_stats["health_regen_flat"])
        item_regen_percent += float(item_stats["health_regen_percent"])
    base_regen_per_second = (
        float(stats.get("base_health_regen_per_five", 0.0) or 0.0) / 5.0
    )
    item_regen = (
        (base_regen_per_second * (1.0 + item_regen_percent / 100.0))
        + item_regen_flat / 5.0
        - base_regen_per_second
    )
    if item_regen > 0.0 and duration > 0.0:
        time = 0.5
        sequence = 0
        while time <= duration + 1e-9:
            events.append(
                {
                    "time": round(time, 6),
                    "amount": item_regen * 0.5,
                    "source": "Health regeneration",
                    "kind": "regen",
                    "actor_wide": True,
                    "_trigger_sequence": sequence,
                }
            )
            sequence += 1
            time += 0.5

    breakdown = result.get("breakdown", {})
    if not isinstance(breakdown, Mapping):
        return events
    for source_key, row in breakdown.items():
        if not isinstance(source_key, str) or not isinstance(row, Mapping):
            continue
        # Periodic item packets may carry a sourced self-heal multiplier on
        # each exact post-mitigation damage event (Unending Despair/Anguish).
        # Malformed event rows are withheld rather than assigned a timestamp.
        if source_key.startswith("periodic_"):
            raw_multiplier = row.get("self_heal_post_mitigation_multiplier")
            damage_events = row.get("damage_events")
            if raw_multiplier is None or not isinstance(damage_events, list):
                continue
            try:
                multiplier = float(raw_multiplier)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(multiplier) or multiplier <= 0.0:
                continue
            source = str(row.get("name", source_key))
            for sequence, damage_event in enumerate(damage_events):
                if not isinstance(damage_event, Mapping):
                    continue
                try:
                    event_time = float(damage_event["time"])
                    damage = float(damage_event["damage"])
                except (KeyError, TypeError, ValueError):
                    continue
                if not math.isfinite(event_time) or not math.isfinite(damage):
                    continue
                amount = damage * multiplier
                if amount <= 0.0:
                    continue
                events.append(
                    {
                        "time": event_time,
                        "amount": amount,
                        "source": f"{source} (self-heal)",
                        "kind": "item_proc",
                        "_trigger_source": source_key,
                        "_trigger_time": event_time,
                        "_trigger_sequence": sequence,
                    }
                )
            continue
        if not source_key.startswith("heal_"):
            continue
        if row.get("unit") != "health":
            continue
        if row.get("owner") == "keystone":
            continue
        raw_heal_events = row.get("heal_events")
        if isinstance(raw_heal_events, list):
            source = str(row.get("name", source_key))
            for sequence, raw_event in enumerate(raw_heal_events):
                if not isinstance(raw_event, Mapping):
                    continue
                try:
                    event_time = float(raw_event["time"])
                    amount = float(raw_event["amount"])
                except (KeyError, TypeError, ValueError):
                    continue
                if (
                    not math.isfinite(event_time)
                    or not math.isfinite(amount)
                    or amount <= 0.0
                ):
                    continue
                materialized = {
                    "time": event_time,
                    "amount": amount,
                    "source": source,
                    "kind": "item_proc",
                    "_trigger_source": str(raw_event.get("trigger_source", source_key)),
                    "_trigger_time": event_time,
                    "_trigger_sequence": sequence,
                }
                if raw_event.get("healing_category"):
                    materialized["healing_category"] = raw_event["healing_category"]
                if raw_event.get("actor_wide"):
                    materialized["actor_wide"] = True
                amount_formula = raw_event.get("amount_formula")
                if callable(amount_formula):
                    materialized["amount_formula"] = amount_formula
                if raw_event.get("overheal_to_temporary_health"):
                    materialized["overheal_to_temporary_health"] = True
                    materialized["temporary_health_duration"] = max(
                        0.0,
                        float(raw_event.get("temporary_health_duration", 0.0) or 0.0),
                    )
                events.append(materialized)
            continue
        proc_times = row.get("proc_times")
        if not isinstance(proc_times, list):
            continue
        try:
            count = int(row["count"])
            amount = float(row["amount_per_proc"])
        except (KeyError, TypeError, ValueError):
            continue
        if count <= 0 or len(proc_times) != count or amount <= 0.0:
            continue
        parsed_times: list[float] = []
        for raw_time in proc_times:
            try:
                event_time = float(raw_time)
            except (TypeError, ValueError):
                parsed_times = []
                break
            if not math.isfinite(event_time):
                parsed_times = []
                break
            parsed_times.append(event_time)
        if len(parsed_times) != count:
            continue
        source = str(row.get("name", source_key))
        for sequence, event_time in enumerate(parsed_times):
            events.append(
                {
                    "time": event_time,
                    "amount": amount,
                    "source": source,
                    "kind": "item_proc",
                    "_trigger_source": source_key,
                    "_trigger_time": event_time,
                    "_trigger_sequence": sequence,
                }
            )
    events.sort(
        key=lambda event: (event["time"], event["source"], event["_trigger_sequence"])
    )
    return events


def _timestamped_damage_events(result: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """The fight's damage rows that carry a usable time and amount."""
    usable: list[Mapping[str, Any]] = []
    for row in result.get("damage_events") or ():
        if not isinstance(row, Mapping):
            continue
        try:
            time = float(row.get("time", 0.0))
            damage = float(row.get("damage", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        if damage > 0.0 and math.isfinite(time):
            usable.append(row)
    return sorted(usable, key=lambda row: float(row.get("time", 0.0)))


def _rune_heal_times(result: Mapping[str, Any], effect: RuneHealEffect) -> list[float]:
    """When one healing rune is paid, from the stream it declares.

    The rune names the stream and the engine owns what is in it — the same
    division the damage-side trigger streams keep. Neither stream invents an
    event: a fight that lands no damage pays no Taste of Blood, and a fight
    the target survives pays no Triumph.
    """
    rows = _timestamped_damage_events(result)
    if effect.trigger is RuneHealTrigger.IMPAIRING_INSTANCES:
        # Whether a row applies control is the bus's answer, never a
        # ``cc_kind`` compared against a string here — the same predicate
        # the damage side's impaired stream asks.
        rows = [row for row in rows if applies_control(row)]
    if not rows:
        return []
    if effect.trigger is RuneHealTrigger.TAKEDOWNS:
        # The fight scored a takedown exactly when the target ended at or
        # below zero health, dated at the window's last damage instance —
        # the rule the coupled walk's own takedown synthesis reads. That is
        # at or after the instance that crossed zero, so a heal placed there
        # arrives no earlier than it should.
        if float(result.get("target_ending_health", 1.0) or 0.0) > 0.0:
            return []
        return [float(rows[-1].get("time", 0.0)) + effect.delay_seconds]
    times: list[float] = []
    ready_at = 0.0
    for row in rows:
        time = float(row.get("time", 0.0))
        if time < ready_at:
            continue
        times.append(time + effect.delay_seconds)
        ready_at = time + effect.cooldown_seconds
    return times


def _rune_self_healing_events(
    result: Mapping[str, Any], rune_page: RunePage | None
) -> list[dict[str, Any]]:
    """Materialize the heal packets the page's healing runes earned.

    The sibling of :func:`_item_self_healing_events`, in the same shape and
    folded into the same ledger: a rune heal is not a different kind of
    heal, only a different owner.  Each rune declares the stream it is paid
    on and the fight supplies the timestamps, so no number here is the
    engine's and no timestamp there is the rune's.
    """
    if rune_page is None:
        return []
    effects = [
        effect
        for effect in resolve_rune_page(rune_page)
        if isinstance(effect, RuneHealEffect)
    ]
    if not effects:
        return []
    stats = result.get("champion_stats")
    stats = stats if isinstance(stats, Mapping) else {}
    inputs = item_effects.DamageInputs(
        champion_stats=stats,
        level=int(stats.get("level", 1) or 1),
        is_melee=bool(stats.get("is_melee", True)),
        target_max_health=float(result.get("target_effective_max_health", 0.0) or 0.0),
        target_current_health=float(result.get("target_ending_health", 0.0) or 0.0),
    )
    events: list[dict[str, Any]] = []
    for effect in effects:
        amount = effect.amount(inputs)
        if not math.isfinite(amount) or amount <= 0.0:
            continue
        for sequence, time in enumerate(_rune_heal_times(result, effect)):
            events.append(
                {
                    "time": time,
                    "amount": amount,
                    "source": effect.source,
                    "kind": "rune_proc",
                    "_trigger_time": time,
                    "_trigger_sequence": sequence,
                }
            )
    return events


def _keystone_self_healing_events(
    result: Mapping[str, Any], params: "FightParams"
) -> list[dict[str, Any]]:
    """Materialize timestamped self-heals emitted by a typed keystone row."""
    if params.keystone not in {"Fleet Footwork", "Conqueror"}:
        return []
    row = result.get("breakdown", {}).get(f"heal_{params.keystone}")
    if not isinstance(row, Mapping) or not isinstance(row.get("heal_events"), list):
        return []
    source = (
        "Fleet Footwork · Energized heal"
        if params.keystone == "Fleet Footwork"
        else "Conqueror · max-stack heal"
    )
    effect = resolve_rune(params.keystone)
    if params.keystone == "Fleet Footwork" and not isinstance(
        effect, KeystoneFleetEffect
    ):
        return []
    if params.keystone == "Conqueror" and not isinstance(
        effect, KeystoneConquerorEffect
    ):
        return []
    slug = "fleet-footwork" if params.keystone == "Fleet Footwork" else "conqueror"
    events: list[dict[str, Any]] = []
    for index, event in enumerate(row["heal_events"]):
        if not isinstance(event, Mapping):
            continue
        events.append(
            {
                **event,
                "source": source,
                "kind": "keystone",
                "healing_category": "direct",
                "actor_wide": True,
                "_event_id": event.get(
                    "_event_id",
                    f"main:{slug}:heal:{index}",
                ),
            }
        )
    return events


def _saturated_omnivamp_percent(
    items: list[dict[str, Any]],
    fight_duration_seconds: float,
    *,
    is_melee: bool = True,
) -> float:
    """The omnivamp this fight's length arms that the stat block does not hold.

    A ramp-armed grant is a fight state, not a stat, so it decides both whether
    the light tuple ledger is adequate and what the published effective stats
    say.  Both read the declaration, so a second such item needs no predicate.
    """
    return sustain.saturating_stat_percent(
        [str(item.get("name", "")) for item in items],
        SustainStat.OMNIVAMP_PERCENT,
        fight_duration_seconds=fight_duration_seconds,
        holder_is_melee=is_melee,
    )


def ledger_inputs(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    params: "FightParams",
    champion_data: dict[str, Any],
    items: list[dict[str, Any]],
    item_damage_effects: Any,
    fight_stats: Mapping[str, Any],
    ability_damages: Mapping[str, Any],
) -> LedgerInputs:
    """One fight's facts, as the ledger projection's readers are decided by.

    The one place ``run_fight``'s locals become the projection's declared
    inputs, so the derivation's fixtures and the engine's live call build the
    same record from the same fields.
    """
    return LedgerInputs(
        self_heal_rule=self_heal_rule_owner(str(champion_data.get("name", ""))),
        item_names=tuple(str(item.get("name", "")) for item in items),
        stats=fight_stats,
        damage_effects=item_damage_effects,
        ability_damages=ability_damages,
        rune_page=params.rune_page,
        fight_duration_seconds=params.fight_duration_seconds,
        is_melee=bool(fight_stats.get("is_melee", True)),
        target_threshold_health_heal=params.target_threshold_health_heal,
    )


def _attach_engine_receipts(
    result: dict[str, Any],
    params: "FightParams",
    items: list[dict[str, Any]],
    fight_stats: Mapping[str, Any],
    auto_attack_policy: Mapping[str, Any],
) -> None:
    """Decorate a finished engine result with the receipts this module owns.

    Everything here is descriptive metadata over values the engine already
    computed — the auto-attack policy and schedule, the stateful-item receipt,
    and the effective stat block a ramp-armed grant republishes.  Kept beside
    ``run_fight`` rather than inside it so the entry point reads as its own
    pipeline: stats, abilities, engine, receipts.
    """
    result["auto_attack_policy"] = auto_attack_policy
    # Every stateful item shares one typed, inspectable receipt.  The receipt
    # is descriptive metadata over the same accessors the engine consumed;
    # it is returned on manual, optimizer, and roster paths so a caller can
    # distinguish authored state from an implicit always-on assumption.
    result["item_state_receipts"] = item_effects.item_state_receipts(
        items,
        params.item_options,
        fight_duration_seconds=params.fight_duration_seconds,
        is_melee=bool(fight_stats.get("is_melee", True)),
        bonus_health=float(fight_stats.get("bonus_health", 0.0) or 0.0),
        bonus_mana=float(fight_stats.get("bonus_mana", 0.0) or 0.0),
        max_mana=float(fight_stats.get("max_mana", 0.0) or 0.0),
        total_attack_damage=float(fight_stats.get("attack_damage", 0.0) or 0.0),
        total_move_speed=float(fight_stats.get("move_speed", 0.0) or 0.0),
        lethality=float(fight_stats.get("lethality", 0.0) or 0.0),
    )
    auto_row = result.get("breakdown", {}).get("auto_attacks", {})
    auto_total = (
        int(auto_row.get("count", 0) or 0) if isinstance(auto_row, Mapping) else 0
    )
    rotation_count = max(1, int(params.rotation_count))
    result["auto_attack_schedule"] = {
        "status": (
            "known" if auto_attack_policy.get("status") != "unknown" else "unknown"
        ),
        "rotation_count": rotation_count,
        "expected_autos_per_rotation": round(auto_total / rotation_count, 6),
        "expected_autos_total": auto_total,
        "window_seconds": round(params.fight_duration_seconds, 3),
        "semantics": (
            "sequential timed window; cooldowns, resources, cast lockouts, and "
            "item events follow the engine ledger"
        ),
    }
    if auto_attack_policy.get("status") == "unknown":
        result.setdefault("notes", []).append(
            "Auto attacks withheld: calculated uptime is unavailable for one or "
            "more cast-time sources."
        )
    saturated_omnivamp = _saturated_omnivamp_percent(
        items,
        params.fight_duration_seconds,
        is_melee=bool(fight_stats.get("is_melee", True)),
    )
    if saturated_omnivamp:
        result["champion_stats"] = dict(fight_stats)
        result["champion_stats"]["omnivamp_percent"] = (
            result["champion_stats"].get("omnivamp_percent", 0.0) + saturated_omnivamp
        )


def _attach_display_splits(result: dict[str, Any]) -> None:
    """The totals only a full result carries — self-heal, auto/ability, type.

    Score-only callers return before this: every field here is a display
    split of numbers already present, and computing them for a candidate
    nobody renders is work the optimizer pays per fight.
    """
    result["self_healing"] = sum(
        float(event.get("amount", 0.0)) for event in result["self_healing_events"]
    )
    auto_damage, ability_damage = split_auto_vs_ability(result["breakdown"])
    result["auto_attack_damage"] = auto_damage
    result["ability_damage"] = ability_damage
    result["damage_by_type"] = split_by_damage_type(result["breakdown"])


def _annotate_deathfire_categories(
    ability_damages: dict[str, dict[str, Any]],
    champion_data: Mapping[str, Any],
) -> None:
    """Attach conservative typed damage categories for Deathfire Touch."""
    for slot, info in ability_damages.items():
        if not isinstance(info, dict) or not info.get("parts"):
            continue
        if info.get("deathfire_category"):
            continue
        if float(info.get("total_raw", 0.0) or 0.0) <= 0.0:
            continue
        persistent = bool(info.get("dot_duration") or info.get("dot_tick_interval"))
        area = detect_aoe_cap(champion_data, slot) > 1
        if persistent and area:
            category = "persistent_area_damage"
        elif persistent:
            category = "persistent_damage"
        elif area:
            category = "area_damage"
        else:
            category = "spell_damage"
        info["deathfire_category"] = category


def _bounded_request_float(
    data: Mapping[str, Any],
    key: str,
    default: float | None,
    *,
    allow_none: bool = False,
) -> float | None:
    """Parse one finite public number inside its UI-supported range.

    The one home for the public number policy, kept here rather than beside
    its integer and string siblings in :mod:`request_parsing`: every number
    the public API accepts is a key of ``PUBLIC_INPUT_LIMITS``, so its range
    is read from that table by name and can never be passed in, and a caller
    has nowhere to spell a second range for the same field.
    """
    value = data.get(key, default)
    if allow_none and value is None:
        return None
    minimum, maximum = PUBLIC_INPUT_LIMITS[key]
    if isinstance(value, bool):
        raise ValueError(f"{key} must be a number")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be a number") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{key} must be finite")
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{key} must be between {minimum:g} and {maximum:g}")
    return parsed


def validate_cast_order_shape(cast_order: Any, *, field: str) -> None:
    """Reject a requested cast order no champion could satisfy.

    Champion-agnostic on purpose: a cast order is a non-empty list of distinct
    ability slots.  Which slots a champion actually offers is a property of its
    parsed kit, checked once against ``cast_dependency.orderable_slots`` in
    :meth:`FightParams.validate_for_champion`, so no slot set is spelled here.
    """
    if cast_order is None:
        return
    if not isinstance(cast_order, list) or any(
        not isinstance(slot, str) for slot in cast_order
    ):
        raise ValueError(f"{field} must be a list of ability slots")
    if not cast_order:
        raise ValueError(f"{field} must name at least one ability slot")
    if len(set(cast_order)) != len(cast_order):
        raise ValueError(f"{field} must not repeat an ability slot")


# How the cast vocabulary spells a castable slot: a base slot letter, plus an
# optional charge index for a second or third cast of the same ability.  The
# letters come from BASE_CAST_SLOTS rather than a second hand list, and "P" is
# excluded because the passive is not castable and has its own spellings.
CAST_SLOT_SPELLING = re.compile(
    "^[" + "".join(slot for slot in BASE_CAST_SLOTS if slot != "P") + "][0-9]*$"
)


def cast_slot_surface(
    ability_damages: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    """The parsed rows a cast order schedules, keyed as the cast vocabulary spells them.

    The parse publishes the passive as ``"passive"`` and the cast vocabulary as
    ``"P"``, and both spellings occur across the roster.  Cast slots are told
    apart from rider rows (``W_frenzy``, ``R_onhit``) by spelling, never by the
    ``recast_of`` stamp: reading the stamp here would filter an unstamped ``Q2``
    out as a rider and silently drop it from a requested order, which is what
    ``cast_dependency.orderable_slots`` fails closed on downstream.
    """
    surface: dict[str, Mapping[str, Any]] = {}
    for slot, entry in ability_damages.items():
        if not isinstance(entry, Mapping):
            continue
        if slot in ("P", "passive"):
            surface["P"] = entry
        elif CAST_SLOT_SPELLING.match(slot):
            surface[slot] = entry
    return surface


def _request_target_class(data: Mapping[str, Any]) -> str:
    """Read the public target-class selector, failing closed.

    Omitting the key selects the champion-class fight.  A supplied value must
    match a :data:`item_effects.TARGET_CLASSES` spelling exactly, with no case
    folding and no plurals, so the request layer and ``FightConfig``'s own guard
    share one spelling contract rather than the request layer widening what the
    kernel accepts.
    """
    value = request_string(data, "target_class", item_effects.DEFAULT_TARGET_CLASS)
    if value not in item_effects.TARGET_CLASSES:
        raise ValueError(
            "target_class must be "
            + " or ".join(item_effects.TARGET_CLASSES)
            + f"; got {value!r}"
        )
    return value


@dataclass(frozen=True)
class FightParams(FightConfig):
    """FightConfig plus the parse-layer inputs the engine never sees.

    The engine's typed contract is :class:`FightConfig`; ``run_fight``
    passes a ``FightParams`` straight through because it IS one.
    """

    ability_ranks: dict[str, int] | None = None
    champion_options: dict[str, Any] | None = None
    item_options: dict[str, dict[str, int | float]] | None = None
    support_target_selections: dict[str, int] | None = None
    role: str = ""
    role_quest_complete: bool = False
    ally_stat_bonuses: dict[str, float] | None = None
    # The Enemy Hits constraint. False composes no enemy pair fights in the
    # coupled timeline and suppresses every enemy-authored event (thorns,
    # authored reactives) — enemies deal exactly zero damage. The one-pair
    # engine never reads this; participant_timeline owns the semantics.
    enemies_attack: bool = True

    @classmethod
    def from_request(
        cls,
        data: Mapping[str, Any],
        *,
        deterministic: bool = False,
    ) -> "FightParams":
        """Parse request-shaped values and resolve fight-mode semantics once."""
        fight_mode = data.get("fight_mode", DEFAULT_FIGHT_MODE)
        if not isinstance(fight_mode, str) or fight_mode not in _PUBLIC_FIGHT_MODES:
            raise ValueError(
                "fight_mode must be one_rotation, time_based, timed, or auto_only"
            )
        one_rotation = fight_mode == "one_rotation"
        # ``auto_only`` is a public fight mode and says exactly what the flag
        # says, so it sets it.  Validating the name and then dropping it served
        # a full rotation — abilities, summons and all — to anyone who asked
        # for autos alone, and made the mode indistinguishable from time_based.
        # No cast means no cast: an ability stat grant (Tristana Q, Olaf R,
        # Lulu W/R, Warwick W) is bought with the cast that grants it, so
        # autos-only earns none of them and reports the unbuffed attack speed.
        # The full rotation stays in ``cast_order`` for the breakdown's slot
        # rows; ``damage._apply_stat_buff_ultimates`` is what reads the mode,
        # and it names every grant it withheld in the fight notes.
        auto_attacks_only = (
            _request_bool(data, "auto_attacks_only", False) or fight_mode == "auto_only"
        )
        requested_duration = _bounded_request_float(
            data, "fight_duration", DEFAULT_FIGHT_DURATION
        )
        requested_uptime = _bounded_request_float(
            data, "auto_attack_uptime", DEFAULT_AUTO_ATTACK_UPTIME
        )
        rotation_count = _request_int(data, "rotations", 1, 1, MAX_ROTATIONS)
        uptime_mode = data.get(
            "auto_attack_uptime_mode", AUTO_ATTACK_UPTIME_MODE_LEGACY
        )
        if (
            not isinstance(uptime_mode, str)
            or uptime_mode not in AUTO_ATTACK_UPTIME_MODES
        ):
            raise ValueError(
                "auto_attack_uptime_mode must be legacy, explicit, or calculated"
            )

        if one_rotation:
            duration = ONE_ROTATION_DURATION
            uptime = (
                requested_uptime
                if uptime_mode == AUTO_ATTACK_UPTIME_MODE_EXPLICIT
                else 0.0
            )
        else:
            duration = requested_duration
            include_autos = _request_bool(data, "include_auto_attacks", False)
            uptime = (
                requested_uptime
                if (
                    include_autos
                    or auto_attacks_only
                    or uptime_mode == AUTO_ATTACK_UPTIME_MODE_CALCULATED
                )
                else 0.0
            )

        ability_ranks = data.get("ability_ranks")
        if ability_ranks is not None and not isinstance(ability_ranks, Mapping):
            raise ValueError("ability_ranks must be an object")
        champion_options = data.get("champion_options")
        if champion_options is not None and not isinstance(champion_options, Mapping):
            raise ValueError("champion_options must be an object")
        item_options = validate_item_input_options(data.get("item_options"))
        support_target_selections = request_index_map(
            data.get("support_target_selections"),
            field="support_target_selections",
            maximum_index=MAX_ALLIES - 1,
        )
        # One page validates the whole rune selection — keystone, minors,
        # shards and every rune's options — so a keystone-only validator is
        # not a second home for the same question.
        rune_page = validate_rune_page(
            data.get("keystone"),
            data.get("minor_runes"),
            data.get("stat_shards"),
            data.get("rune_options"),
        )
        # ``keystone_options`` is the older spelling of the keystone's own
        # entry in ``rune_options``.  It is validated against the page's
        # keystone and folded into the page, so every reader downstream asks
        # the page and a request may use either spelling without two homes
        # answering differently.
        requested_keystone_options = data.get("keystone_options")
        keystone_options = validate_keystone_options(
            requested_keystone_options, rune_page.keystone
        )
        if (
            isinstance(requested_keystone_options, Mapping)
            and requested_keystone_options
        ):
            rune_page = replace(
                rune_page,
                options={
                    **rune_page.options,
                    rune_page.keystone: {
                        **rune_page.options.get(rune_page.keystone, {}),
                        **{
                            key: float(value) for key, value in keystone_options.items()
                        },
                    },
                },
            )
        role = validate_role(data.get("role", ""))
        role_quest_complete = _request_bool(data, "role_quest_complete", False)
        if role_quest_complete and not role:
            raise ValueError("role is required when role_quest_complete is true")

        params = cls(
            target_health=_bounded_request_float(
                data, "target_health", DEFAULT_TARGET["health"]
            ),
            target_bonus_health=_bounded_request_float(
                data, "target_bonus_health", DEFAULT_TARGET["bonus_health"]
            ),
            target_armor=_bounded_request_float(
                data, "target_armor", DEFAULT_TARGET["armor"]
            ),
            target_bonus_armor=_bounded_request_float(
                data, "target_bonus_armor", None, allow_none=True
            ),
            target_magic_resistance=_bounded_request_float(
                data, "target_mr", DEFAULT_TARGET["mr"]
            ),
            fight_duration_seconds=duration,
            auto_attack_uptime=uptime,
            auto_attack_uptime_mode=uptime_mode,
            rotation_count=rotation_count,
            one_rotation=one_rotation,
            include_actives=_request_bool(data, "include_actives", True),
            cast_order=data.get("cast_order"),
            auto_attacks_only=auto_attacks_only,
            ability_ranks=dict(ability_ranks) if ability_ranks is not None else None,
            champion_options=(
                dict(champion_options) if champion_options is not None else None
            ),
            item_options=item_options or None,
            support_target_selections=support_target_selections or None,
            keystone=rune_page.keystone,
            minor_runes=rune_page.minor_runes,
            stat_shards=rune_page.stat_shards,
            rune_options=dict(rune_page.options) or None,
            keystone_options=keystone_options,
            target_class=_request_target_class(data),
            role=role,
            role_quest_complete=role_quest_complete,
            enemies_attack=_request_bool(data, "enemies_attack", True),
            deterministic=deterministic,
        )
        params._validate_request_values()
        return params

    def _validate_request_values(self) -> None:
        """Reject malformed cast orders and ability ranks for every consumer.

        The cast-order check here is deliberately champion-agnostic: a
        request is a non-empty list of distinct ability slots, and *which*
        slots a given champion may be told to cast is decided against its
        parsed kit in :meth:`validate_for_champion` (D-11).
        """
        validate_cast_order_shape(self.cast_order, field="Cast order")

        if not self.ability_ranks:
            return
        unknown_keys = set(self.ability_ranks) - {"Q", "W", "E", "R"}
        if unknown_keys:
            raise ValueError(
                f"Unknown ability rank keys: {', '.join(sorted(unknown_keys))}"
            )
        for key in ("Q", "W", "E"):
            value = self.ability_ranks.get(key, 0)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{key} rank must be an integer")
            if value < 0 or value > 5:
                raise ValueError(f"{key} rank must be 0-5")
        ultimate_rank = self.ability_ranks.get("R", 0)
        if isinstance(ultimate_rank, bool) or not isinstance(ultimate_rank, int):
            raise ValueError("R rank must be an integer")
        if ultimate_rank < 0 or ultimate_rank > 3:
            raise ValueError("R rank must be 0-3")

    def target_stats(self) -> dict[str, float]:
        """Build the champion-parser target context for a full-health target."""
        return {
            "target_max_health": self.target_health,
            "target_current_health": self.target_health,
            "target_missing_health": 0.0,
            "roster_target_index": float(self.roster_target_index),
            "roster_target_count": float(self.roster_target_count),
        }

    def validate_for_champion(
        self,
        champion_name: str,
        level: int,
        *,
        kit: Mapping[str, Any] | None = None,
    ) -> None:
        """Reject a rank allocation or a cast order this champion cannot run.

        Rank-free requests use the champion's sourced default order. Manual
        allocations are accepted only for the standard five-rank basic and
        three-rank ultimate layout. Transformation and auto-levelled kits fail
        closed until their individual allocation rules are represented.

        ``kit`` is the parsed ability package.  Which slots a request may
        name is a property of the parsed kit, not of the champion's name, so
        every caller that validates *before* the parse passes none, and the
        one caller that has a parse — ``run_fight``'s post-parse call site —
        asks :meth:`validate_cast_order_for_kit` directly instead of running
        this whole validator a second time.  Passing ``kit`` here is for a
        caller that wants both halves in one call.
        """
        if level > max_champion_level(self.role, self.role_quest_complete):
            raise ValueError(f"Level {level} requires the completed top role quest")

        custom_order_reason = get_custom_cast_order_unavailable_reason(champion_name)
        if self.cast_order is not None and custom_order_reason is not None:
            raise ValueError(custom_order_reason)
        if kit is not None:
            self.validate_cast_order_for_kit(champion_name, kit)

        if self.ability_ranks is None:
            return
        if champion_name in _NONSTANDARD_RANK_CHAMPIONS:
            raise ValueError(
                f"Manual ability ranks are unavailable for {champion_name}; "
                "use the level-derived ranks"
            )

        effective = {
            key: self.ability_ranks.get(
                key, get_ability_rank(key, level, champion_name)
            )
            for key in ("Q", "W", "E", "R")
        }
        for key in ("Q", "W", "E"):
            rank = effective[key]
            minimum_level = max(1, 2 * rank - 1) if rank else 0
            if rank and level < minimum_level:
                raise ValueError(
                    f"{key} rank {rank} requires champion level {minimum_level}"
                )
        ultimate_rank = effective["R"]
        minimum_ultimate_level = (0, 6, 11, 16)[ultimate_rank]
        if ultimate_rank and level < minimum_ultimate_level:
            raise ValueError(
                f"R rank {ultimate_rank} requires champion level "
                f"{minimum_ultimate_level}"
            )
        if sum(effective.values()) > min(level, 18):
            raise ValueError(
                "Ability ranks spend more skill points than the champion level allows"
            )

    def validate_cast_order_for_kit(
        self, champion_name: str, kit: Mapping[str, Any]
    ) -> None:
        """Every requested slot is one this champion's parse offers to a request.

        The one question a *parse* answers, on its own, so the post-parse
        call site can ask it without re-running the level, fight-mode and
        rank checks its caller already ran — or, for a caller that passed
        ``validated=True``, deliberately skipped.  A request with no cast
        order has nothing to check and returns.

        Recast slots are absent from the orderable set by construction: they
        ride their parent's casts, so naming one would schedule it twice.
        They are folded back in by ``expand_user_order`` instead of being
        silently dropped, which is the defect this check's other half fixes.

        Raises:
            ValueError: A requested slot is not orderable for this kit.
            cast_dependency.UnknownSlotError: The parse holds a cast slot
                that is neither a base slot nor stamped ``recast_of``, so
                nothing can say whether a request may name it (D-11).
        """
        if self.cast_order is None:
            return
        surface = cast_slot_surface(kit)
        orderable = orderable_slots(surface)
        # A base slot whose parse produced no damage row — Aatrox's dash E,
        # Aphelios's weapon-swap E — is still a slot the champion has, and
        # naming it stays legal and casts nothing, exactly as before. What
        # is refused is a slot the parse DOES hold and ``orderable_slots``
        # did not return: the passive, or a declared recast that rides its
        # parent instead of being scheduled on its own.
        unparsed_base = {slot for slot in BASE_CAST_SLOTS if slot != "P"} - set(surface)
        legal = set(orderable) | unparsed_base
        refused = [slot for slot in self.cast_order or () if slot not in legal]
        if refused:
            raise ValueError(
                f"Cast order names {', '.join(refused)}, which "
                f"{champion_name} cannot be told to cast; "
                f"orderable slots are {', '.join(orderable)}"
            )


# The optimizer replays the same frozen FightParams for thousands of
# candidate fights, and the resolved cast order for one champion is almost
# always identical across candidates.  Memoize the derived params by
# (params identity, order): frozen instances are safe to share, the strong
# reference guards ``id()`` recycling, the leading ``data_version()``
# retires every entry derived from a replaced cache (D-49), and the bound
# keeps candidate churn from growing the memo without limit.
_CAST_ORDER_PARAMS_MEMO: dict[
    tuple[int, int, tuple[str, ...]], tuple["FightParams", "FightParams"]
] = {}
_CAST_ORDER_PARAMS_MEMO_LIMIT = 512


def _params_with_cast_order(
    params: "FightParams", declared_order: list[str]
) -> "FightParams":
    """``replace(params, cast_order=declared_order)`` with an identity memo."""
    key = (data_version(), id(params), tuple(declared_order))
    memo = _CAST_ORDER_PARAMS_MEMO.get(key)
    if memo is not None and memo[0] is params:
        return memo[1]
    resolved = replace(params, cast_order=declared_order)
    if len(_CAST_ORDER_PARAMS_MEMO) > _CAST_ORDER_PARAMS_MEMO_LIMIT:
        _CAST_ORDER_PARAMS_MEMO.clear()
    _CAST_ORDER_PARAMS_MEMO[key] = (params, resolved)
    return resolved


def run_fight(
    champion_data: dict[str, Any],
    level: int,
    items: list[dict[str, Any]],
    params: FightParams,
    precomputed_stats: dict[str, float] | None = None,
    validated: bool = False,
    score_only: bool = False,
) -> dict[str, Any]:
    """Run stats, champion ability parsing, and fight damage as one pipeline.

    ``precomputed_stats`` lets a caller that already ran this exact stat
    calculation (same champion, level, items, options, role, and external
    bonuses) hand it over instead of repeating it; the fight itself never
    mutates it.  Callers own that equality claim.

    ``validated=True`` is the same kind of caller-owned claim for
    ``params.validate_for_champion(champion, level)``: the coupled search
    validates its fixed per-pair params once instead of on each of
    thousands of identical fights.

    ``score_only=True`` skips result fields no scoring consumer reads —
    the one-pair shield outcome (unless the Protoplasm coverage downgrade
    needs it) and the auto/ability/type display splits.  Every field that
    remains carries the identical value.  When the champion additionally
    has no self-heal rule and the target arms no threshold heal, the
    returned ``damage_events`` are the engine's light ledger rows
    (``damage_events_tuple`` is set) — same events, same order, no dict
    per event; only the scoring fast path consumes that shape.
    """
    if not validated:
        params.validate_for_champion(champion_data.get("name", ""), level)
    champion_stats = (
        precomputed_stats
        if precomputed_stats is not None
        else calculate_total_stats(
            champion_data,
            level,
            items,
            item_options=params.item_options,
            role=params.role,
            role_quest_complete=params.role_quest_complete,
            external_stat_bonuses=params.ally_stat_bonuses,
            rune_page=params.rune_page,
        )
    )

    # Reserved option keys are pipeline-owned: strip whatever the caller
    # sent, then hand timed fights the fight window, the auto uptime and
    # whether the engine casts anything at all, so duration/timeline-driven
    # champion mechanics (Aurelion Sol's continuous Q channel, Braum's
    # passive stack cycle) scale with the same fight the engine runs — an
    # autos-only window schedules zero casts, so a walk module that merges
    # ability hits into its stream has to be told. One-rotation mode keeps
    # the per-cast ability models.
    champion_options = dict(params.champion_options or {})
    for reserved_key in RESERVED_OPTION_KEYS:
        champion_options.pop(reserved_key, None)
    if not params.one_rotation:
        champion_options["fight_duration_seconds"] = params.fight_duration_seconds
        champion_options["auto_attack_uptime"] = params.auto_attack_uptime
        champion_options["auto_attacks_only"] = params.auto_attacks_only

    # Champion mechanics priced in crit at parse time (Caitlyn's Headshot
    # rider) need the build's bonus crit damage above the 2.0 base
    # (Infinity Edge's +0.3). It lives in the items' DamageEffects — the
    # same value the fight engine folds into its crit multiplier — so
    # surface it to the parse context only, keeping the reported
    # champion_stats panel item-stats-only.
    parse_stats = dict(champion_stats)
    item_damage_effects = resolve_damage_effects(items)
    parse_stats["crit_damage_bonus"] = item_damage_effects.crit_damage_bonus

    ability_damages = parse_champion_abilities(
        champion_data,
        level,
        champion_stats["ability_power"],
        ability_ranks=params.ability_ranks,
        champion_stats=parse_stats,
        target_stats=params.target_stats(),
        champion_options=champion_options,
    )
    if params.keystone == "Deathfire Touch":
        _annotate_deathfire_categories(ability_damages, champion_data)
    # The fight engine applies ability stat buffs (Mega Gnar's form
    # stats, Vayne/Aatrox R, ...) to this copy in place — report THESE
    # as the champion's stats so the UI panel shows the fight-effective
    # values, not the pre-buff base+items snapshot.
    fight_stats = dict(champion_stats)
    # F2: the optimal event-order engine derives the fight's cast order
    # from the atomized ability data + the per-champion combo table (see
    # rotation_resolver.py) — e.g. Cassiopeia opens with Q so the poison
    # is up for E-spam, Varus puts the Blight detonator Q first, Aatrox
    # casts R before its AD-amped damage. An explicit caller-supplied
    # order still wins; champions with no combo signal fall back to their
    # certified module order, then the engine default.
    resolved_rotation_rule = None
    resolved_certified_order = None
    resolved_user_order = None
    if params.cast_order is None:
        # F3: the algorithmic resolver derives the order for EVERY champion
        # from the atomized ability data (setup/consume edges + per-rank DPS),
        # falling back to the champion module's certified CAST_ORDER or the
        # engine default when the data shows a flat kit.  The hand-verified seeds
        # remain documented overrides inside the resolver.
        declared_order, combo_rule = resolve_cast_order(
            champion_data.get("name", ""),
            ability_damages,
            champion_data=champion_data,
            certified_order=get_champion_cast_order(champion_data.get("name", "")),
            champion_options=champion_options,
        )
        params = _params_with_cast_order(params, declared_order)
        resolved_rotation_rule = combo_rule
        resolved_certified_order = (
            combo_rule.order
            if combo_rule is not None and not combo_rule.derived
            else None
        )
    else:
        # The post-parse cast-order call site: the requested order is checked
        # against the slots this parse actually offers, then every live recast
        # slot is folded back in after its parent.  Before this, a requested
        # order was passed to the engine verbatim and every recast row it did
        # not name — Syndra's second Dark Sphere charge — silently vanished
        # from the damage breakdown (D-11).
        resolved_user_order = list(params.cast_order)
        params.validate_cast_order_for_kit(
            champion_data.get("name", ""), ability_damages
        )
        # A declared ordering prerequisite states impossibility, not
        # preference (D-86): casting Syndra's E before her Q would have the
        # engine author a stun that cannot happen, and an amplifier price
        # off it.  The order checked is the EXPANDED one, because that is
        # what the engine casts — a recast folded in after its parent can
        # satisfy a dependency the request never named, and could equally
        # invert one.  A champion that declares nothing gets an empty tuple
        # and reaches no new failure mode (D-85).
        expanded_order = expand_user_order(resolved_user_order, ability_damages)
        check_order_satisfies_dependencies(
            expanded_order,
            get_champion_cast_dependencies(champion_data.get("name", "")),
            ability_damages,
        )
        params = _params_with_cast_order(params, expanded_order)
    resolved_uptime, auto_attack_policy = resolve_auto_attack_policy(
        champion_data,
        ability_damages,
        cast_order=params.cast_order,
        duration_seconds=params.fight_duration_seconds,
        requested_uptime=params.auto_attack_uptime,
        mode=params.auto_attack_uptime_mode,
        one_rotation=params.one_rotation,
    )
    if params.auto_attack_uptime_mode == AUTO_ATTACK_UPTIME_MODE_CALCULATED:
        params = replace(params, auto_attack_uptime=resolved_uptime)
        if not params.one_rotation:
            # Timed champion mechanics (channels and passive cycles) consume
            # the same resolved policy; do not let their parse context retain
            # the pre-resolution placeholder zero.
            champion_options["fight_duration_seconds"] = params.fight_duration_seconds
            champion_options["auto_attack_uptime"] = resolved_uptime
            ability_damages = parse_champion_abilities(
                champion_data,
                level,
                champion_stats["ability_power"],
                ability_ranks=params.ability_ranks,
                champion_stats=parse_stats,
                target_stats=params.target_stats(),
                champion_options=champion_options,
            )
            if params.keystone == "Deathfire Touch":
                _annotate_deathfire_categories(ability_damages, champion_data)
    # ``score_only`` is the request for a narrowed result; whether the light
    # tuple ledger can serve it is projection satisfaction over the declared
    # adequacy conditions, not a conjunction kept here (D-38, criterion 15).
    tuple_ledger = score_only and (
        ledger_projection(
            ledger_inputs(
                params,
                champion_data,
                items,
                item_damage_effects,
                fight_stats,
                ability_damages,
            )
        )
        is ResultProjection.LIGHT_TUPLE_LEDGER
    )
    # Whether the timed scheduler may recast R is the champion module's
    # reviewed answer, not the request's: a silent module and an
    # unregistered name both keep the conservative one-cast rule (CF18).
    ultimate_recasts = get_champion_ultimate_recasts(champion_data.get("name", ""))
    engine_config = (
        params
        if params.enforce_resource_limits
        and params.ultimate_recasts == ultimate_recasts
        else replace(
            params,
            enforce_resource_limits=True,
            ultimate_recasts=ultimate_recasts,
        )
    )
    result = calculate_fight_damage(
        fight_stats,
        ability_damages,
        items,
        engine_config,
        score_only=score_only,
        tuple_ledger=tuple_ledger,
        item_options=params.item_options,
        champion_options=params.champion_options,
    )
    result["self_state_events"] = derive_self_state_effects(
        ability_damages,
        list(result.get("cast_timeline", [])),
    )
    keystone_state_events: list[dict[str, Any]] = []
    fleet_row = result.get("breakdown", {}).get("keystone_Fleet Footwork")
    if isinstance(fleet_row, Mapping) and isinstance(
        fleet_row.get("movement_events"), list
    ):
        keystone_state_events.extend(fleet_row["movement_events"])
    conqueror_row = result.get("breakdown", {}).get("keystone_Conqueror")
    if isinstance(conqueror_row, Mapping) and isinstance(
        conqueror_row.get("stack_events"), list
    ):
        keystone_state_events.extend(conqueror_row["stack_events"])
    result["keystone_state_events"] = keystone_state_events
    result["champion_stats"] = fight_stats
    # F2 rotation receipt: the optimal order + WHY it is optimal, for the
    # event-order panel. ``order`` is the engine's actual cooldown-aware
    # cast sequence; ``rationale`` explains the combo.
    result["rotation"] = build_rotation_receipt(
        champion_data.get("name", ""),
        cast_order=list(params.cast_order or []),
        cast_timeline=list(result.get("cast_timeline", [])),
        rule=resolved_rotation_rule,
        certified_order=(
            resolved_certified_order if resolved_rotation_rule is None else None
        ),
        user_order=resolved_user_order,
    )
    _attach_engine_receipts(result, params, items, fight_stats, auto_attack_policy)
    if tuple_ledger:
        # The predicate above IS derive_self_healing's dispatch gate, so
        # the empty list is the exact value the call would return.
        result["damage_events_tuple"] = True
        result["self_healing_events"] = []
        return result
    champion_healing = derive_self_healing(
        champion_data,
        fight_stats,
        ability_damages,
        list(result.get("damage_events", [])),
        list(result.get("cast_timeline", [])),
        params.fight_duration_seconds,
    )
    result["self_healing_events"] = sorted(
        champion_healing
        + _keystone_self_healing_events(result, params)
        + _item_self_healing_events(result, items, params.fight_duration_seconds)
        + _rune_self_healing_events(result, params.rune_page),
        key=lambda event: (
            float(event.get("time", 0.0)),
            str(event.get("kind", "")),
            str(event.get("source", "")),
            int(event.get("_trigger_sequence", 0)),
        ),
    )
    if score_only:
        return result
    _attach_display_splits(result)
    return result
