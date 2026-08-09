"""Shared entry point for a complete champion fight calculation.

Consumers provide already-loaded champion and item data. This module owns the
cross-domain orchestration from stats through champion ability parsing into the
champion-agnostic fight engine; data fetching remains with each consumer.
"""

import math
from dataclasses import dataclass, replace
from collections.abc import Mapping
from typing import Any

from .champions import (
    RESERVED_OPTION_KEYS,
    get_champion_cast_order,
    get_custom_cast_order_unavailable_reason,
    get_supported_fight_modes,
    get_unsupported_fight_mode_reason,
    parse_champion_abilities,
    parse_synthetic_champion_abilities,
)
from .rotation_resolver import build_rotation_receipt, resolve_cast_order
from .champions.skill_orders import get_ability_rank
from .damage import (
    FightConfig,
    calculate_fight_damage,
    split_auto_vs_ability,
    split_by_damage_type,
)
from . import item_effects
from .item_effects import resolve_damage_effects, validate_item_input_options
from .healing import HEALING_RULE_CHAMPIONS, derive_self_healing
from .item_support_effects import has_event_scan_support_items
from .auto_attack_policy import (
    AUTO_ATTACK_UPTIME_MODE_CALCULATED,
    AUTO_ATTACK_UPTIME_MODE_EXPLICIT,
    AUTO_ATTACK_UPTIME_MODE_LEGACY,
    AUTO_ATTACK_UPTIME_MODES,
    resolve_auto_attack_policy,
)
from .role_quests import max_champion_level, validate_role
from .request_parsing import (
    request_bool as _request_bool,
    request_int as _request_int,
    request_number,
)
from .rune_effects import validate_keystone_request
from .stats import calculate_total_stats, get_item_stats

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
    item_names = {str(item.get("name", "")) for item in (items or ())}
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

    # Life Draining is a direct post-mitigation heal, not the old Doran's
    # Blade omnivamp stat.  Unknown ability scope is conservatively priced at
    # the sourced area/pet effectiveness rather than being promoted as full.
    if "Doran's Blade" in item_names:
        ratio = item_effects.sustain_effect_value(
            "Doran's Blade", "direct_heal_post_mitigation_ratio"
        )
        reduced = item_effects.sustain_effect_value(
            "Doran's Blade", "direct_heal_aoe_effectiveness"
        )
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
                    "source": "Doran's Blade (Life Draining)",
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
    if "Doran's Ring" in item_names:
        max_mana = float(stats.get("max_mana", 0.0) or 0.0)
        remaining = float(result.get("resource_remaining", 0.0) or 0.0)
        can_only_heal = max_mana <= 0.0 or remaining >= max_mana - 1e-9
        if can_only_heal and duration > 0.0:
            base_rate = item_effects.sustain_effect_value(
                "Doran's Ring", "drain_restoration_per_second"
            )
            combat_rate = item_effects.sustain_effect_value(
                "Doran's Ring", "drain_combat_restoration_per_second"
            )
            combat_window = item_effects.sustain_effect_value(
                "Doran's Ring", "drain_combat_duration"
            )
            conversion = item_effects.sustain_effect_value(
                "Doran's Ring", "drain_health_conversion"
            )
            tick = item_effects.sustain_effect_value(
                "Doran's Ring", "drain_tick_interval"
            )
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
                        "source": "Doran's Ring (Drain)",
                        "kind": "item_proc",
                        "actor_wide": True,
                        "_trigger_sequence": sequence,
                    }
                )
                sequence += 1
                time += tick

    # Catalyst's Eternity heal is tied to each accepted mana-spending cast.
    # The cast timeline is the only certified timestamp/resource receipt; an
    # aggregate resource total is deliberately not converted into a guessed
    # heal.  The sourced 20-per-second cap is applied in one-second buckets,
    # while each cast is independently capped at 20.
    if "Catalyst of Aeons" in item_names:
        cast_timeline = result.get("cast_timeline")
        if not isinstance(cast_timeline, list):
            cast_timeline = []
        heal_ratio = item_effects.sustain_effect_value(
            "Catalyst of Aeons", "mana_spent_heal_ratio"
        )
        cast_cap = item_effects.sustain_effect_value(
            "Catalyst of Aeons", "mana_spent_heal_cap_per_cast"
        )
        second_cap = item_effects.sustain_effect_value(
            "Catalyst of Aeons", "mana_spent_heal_cap_per_second"
        )
        healed_by_second: dict[int, float] = {}
        for cast in cast_timeline:
            if not isinstance(cast, Mapping):
                continue
            try:
                event_time = float(cast["time"])
            except (KeyError, TypeError, ValueError):
                continue
            if not math.isfinite(event_time):
                continue
            try:
                before = float(cast.get("resource_before", 0.0) or 0.0)
                after = float(cast.get("resource_after", 0.0) or 0.0)
                spent = max(0.0, before - after)
            except (TypeError, ValueError):
                spent = 0.0
            if spent <= 0.0:
                try:
                    spent = max(0.0, float(cast.get("resource_cost", 0.0) or 0.0))
                except (TypeError, ValueError):
                    spent = 0.0
            if spent <= 0.0:
                continue
            bucket = math.floor(event_time + 1e-9)
            remaining = max(0.0, second_cap - healed_by_second.get(bucket, 0.0))
            amount = min(cast_cap, heal_ratio * spent, remaining)
            if amount <= 0.0:
                continue
            healed_by_second[bucket] = healed_by_second.get(bucket, 0.0) + amount
            events.append(
                {
                    "time": event_time,
                    "amount": amount,
                    "source": "Catalyst of Aeons (Eternity)",
                    "kind": "item_proc",
                    "_trigger_source": str(cast.get("slot", "cast")),
                    "_trigger_time": event_time,
                    "_trigger_sequence": int(cast.get("ordinal", 1) or 1) - 1,
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


def _has_item_self_healing(
    effects: Any, items: list[Mapping[str, Any]] | None = None
) -> bool:
    """Whether an item build can emit timestamped self-heal packets.

    The score-only tuple ledger is safe only when both the champion and the
    item build are heal-free.  In particular, Dusk and Dawn's Spellblade heal
    and Unending Despair's periodic Anguish heal are item-owned packets that
    must remain in the full result even when the champion has no healing rule.
    """
    spellblade = effects.spellblade
    if spellblade is not None and (
        spellblade.self_heal_ap_ratio > 0.0
        or spellblade.self_heal_bonus_health_ratio > 0.0
    ):
        return True
    return (
        any(
            periodic.self_heal_post_mitigation_multiplier > 0.0
            for periodic in effects.periodic
        )
        or bool(effects.on_hit_heals)
        or (
            effects.first_auto_crit is not None
            and (
                effects.first_auto_crit.heal_base_ad_ratio > 0.0
                or effects.first_auto_crit.heal_missing_health_ratio > 0.0
            )
        )
        or any(
            str(item.get("name", "")) in {"Catalyst of Aeons"} for item in (items or ())
        )
    )


def _has_item_health_regen(stats: Mapping[str, Any]) -> bool:
    """Whether items contribute health regeneration to this build.

    Item flat/percent regen authors timestamped ``Health regeneration``
    ticks in ``_item_self_healing_events``; the score-only tuple ledger
    would silently drop them (issue #169).  Champion base regeneration
    alone authors nothing, so equality means the tuple ledger stays safe.
    """
    try:
        total = float(stats.get("health_regen_per_five", 0.0) or 0.0)
        base = float(stats.get("base_health_regen_per_five", 0.0) or 0.0)
    except (TypeError, ValueError):
        return True
    return math.isfinite(total) and math.isfinite(base) and total > base


def _has_lifesteal_stat(stats: Mapping[str, Any]) -> bool:
    """Return whether the fight needs the full ledger for life-steal events."""
    value = stats.get("lifesteal_percent", 0.0)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value)) and float(value) > 0.0


def _has_omnivamp_stat(stats: Mapping[str, Any]) -> bool:
    """Return whether the fight needs explicit omnivamp event receipts."""
    value = stats.get("omnivamp_percent", 0.0)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value)) and float(value) > 0.0


def _has_riftmaker_max_stack_omnivamp(
    items: list[dict[str, Any]],
    fight_duration_seconds: float,
    *,
    is_melee: bool = True,
) -> bool:
    """Return whether the fight reaches Riftmaker's conditional heal state."""
    if not any(item.get("name") == "Riftmaker" for item in items):
        return False
    return (
        item_effects.riftmaker_max_stack_omnivamp(
            fight_duration_seconds=fight_duration_seconds,
            is_melee=is_melee,
        )
        > 0.0
    )


def _bounded_request_float(
    data: Mapping[str, Any],
    key: str,
    default: float | None,
    *,
    allow_none: bool = False,
) -> float | None:
    """Parse one finite public number inside its UI-supported range."""
    value = data.get(key, default)
    if allow_none and value is None:
        return None
    minimum, maximum = PUBLIC_INPUT_LIMITS[key]
    return request_number(data, key, default, minimum, maximum)


@dataclass(frozen=True)
class FightParams(FightConfig):
    """FightConfig plus the parse-layer inputs the engine never sees.

    The engine's typed contract is :class:`FightConfig`; ``run_fight``
    passes a ``FightParams`` straight through because it IS one.
    """

    ability_ranks: dict[str, int] | None = None
    champion_options: dict[str, Any] | None = None
    item_options: dict[str, dict[str, int]] | None = None
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
        auto_attacks_only = _request_bool(data, "auto_attacks_only", False)
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
        keystone = validate_keystone_request(data.get("keystone"))
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
            keystone=keystone,
            role=role,
            role_quest_complete=role_quest_complete,
            enemies_attack=_request_bool(data, "enemies_attack", True),
            deterministic=deterministic,
        )
        params._validate_request_values()
        return params

    def _validate_request_values(self) -> None:
        """Reject malformed cast orders and ability ranks for every consumer."""
        if self.cast_order is not None:
            if not isinstance(self.cast_order, list) or any(
                not isinstance(key, str) for key in self.cast_order
            ):
                raise ValueError("Cast order must be a permutation of Q, W, E, R")
            if sorted(self.cast_order) != ["E", "Q", "R", "W"]:
                raise ValueError("Cast order must be a permutation of Q, W, E, R")

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

    def validate_for_champion(self, champion_name: str, level: int) -> None:
        """Reject a rank allocation that cannot exist at ``level``.

        Rank-free requests use the champion's sourced default order. Manual
        allocations are accepted only for the standard five-rank basic and
        three-rank ultimate layout. Transformation and auto-levelled kits fail
        closed until their individual allocation rules are represented.
        """
        if level > max_champion_level(self.role, self.role_quest_complete):
            raise ValueError(f"Level {level} requires the completed top role quest")
        require_fight_mode_support(self, champion_name)

        custom_order_reason = get_custom_cast_order_unavailable_reason(champion_name)
        if self.cast_order is not None and custom_order_reason is not None:
            raise ValueError(custom_order_reason)

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


def require_fight_mode_support(params: "FightParams", champion_name: str) -> None:
    """Reject a fight mode the champion's certified module cannot run.

    The one home for the mode rule: ``validate_for_champion`` applies it to
    the main attacker, and the participant timeline applies it to every
    roster member it will run as an attacker.
    """
    supported_modes = get_supported_fight_modes(champion_name)
    requested_mode = (
        "one_rotation"
        if params.one_rotation
        else ("auto_only" if params.auto_attacks_only else "time_based")
    )
    if supported_modes is not None and requested_mode not in supported_modes:
        reason = get_unsupported_fight_mode_reason(champion_name)
        raise ValueError(
            reason or f"{requested_mode} is not certified for {champion_name}"
        )


# The optimizer replays the same frozen FightParams for thousands of
# candidate fights, and the resolved cast order for one champion is almost
# always identical across candidates.  Memoize the derived params by
# (params identity, order): frozen instances are safe to share, the strong
# reference guards ``id()`` recycling, and the bound keeps candidate churn
# from growing the memo without limit.
_CAST_ORDER_PARAMS_MEMO: dict[
    tuple[int, tuple[str, ...]], tuple["FightParams", "FightParams"]
] = {}
_CAST_ORDER_PARAMS_MEMO_LIMIT = 512


def _params_with_cast_order(
    params: "FightParams", declared_order: list[str]
) -> "FightParams":
    """``replace(params, cast_order=declared_order)`` with an identity memo."""
    key = (id(params), tuple(declared_order))
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
    synthetic: bool = False,
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

    ``synthetic=True`` is reserved for explicit engine/development fixtures.
    Production callers omit it and must resolve a validated named module.
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
        )
    )

    # Reserved option keys are pipeline-owned: strip whatever the caller
    # sent, then hand timed fights the fight window and auto uptime so
    # duration/timeline-driven champion mechanics (Aurelion Sol's
    # continuous Q channel, Braum's passive stack cycle) can scale with
    # them. One-rotation mode keeps the per-cast ability models.
    champion_options = dict(params.champion_options or {})
    for reserved_key in RESERVED_OPTION_KEYS:
        champion_options.pop(reserved_key, None)
    if not params.one_rotation:
        champion_options["fight_duration_seconds"] = params.fight_duration_seconds
        champion_options["auto_attack_uptime"] = params.auto_attack_uptime

    # Champion mechanics priced in crit at parse time (Caitlyn's Headshot
    # rider) need the build's bonus crit damage above the 2.0 base
    # (Infinity Edge's +0.3). It lives in the items' DamageEffects — the
    # same value the fight engine folds into its crit multiplier — so
    # surface it to the parse context only, keeping the reported
    # champion_stats panel item-stats-only.
    parse_stats = dict(champion_stats)
    item_damage_effects = resolve_damage_effects(items)
    parse_stats["crit_damage_bonus"] = item_damage_effects.crit_damage_bonus

    parse_kit = (
        parse_synthetic_champion_abilities if synthetic else parse_champion_abilities
    )
    ability_damages = parse_kit(
        champion_data,
        level,
        champion_stats["ability_power"],
        ability_ranks=params.ability_ranks,
        champion_stats=parse_stats,
        target_stats=params.target_stats(),
        champion_options=champion_options,
    )
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
        )
        params = _params_with_cast_order(params, declared_order)
        resolved_rotation_rule = combo_rule
        resolved_certified_order = (
            combo_rule.order
            if combo_rule is not None and not combo_rule.derived
            else None
        )
    else:
        resolved_user_order = list(params.cast_order)
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
            ability_damages = parse_kit(
                champion_data,
                level,
                champion_stats["ability_power"],
                ability_ranks=params.ability_ranks,
                champion_stats=parse_stats,
                target_stats=params.target_stats(),
                champion_options=champion_options,
            )
    tuple_ledger = (
        score_only
        and params.target_threshold_health_heal <= 0
        and champion_data.get("name", "") not in HEALING_RULE_CHAMPIONS
        and not _has_item_self_healing(item_damage_effects, items)
        and not _has_item_health_regen(fight_stats)
        and not _has_lifesteal_stat(fight_stats)
        and not _has_omnivamp_stat(fight_stats)
        and not _has_riftmaker_max_stack_omnivamp(
            items,
            params.fight_duration_seconds,
            is_melee=bool(fight_stats.get("is_melee", True)),
        )
        # Forced/empowered basic attacks are authored on ability rows. Keep
        # the dict ledger so reactive defenders (Bramble/Thornmail) retain
        # the basic-attack marker instead of losing it in the light tuple
        # schema.
        and not any(
            ability.get("empowers_next_auto")
            for ability in ability_damages.values()
            if isinstance(ability, dict)
        )
        # Items that derive support packets by scanning the damage/takedown
        # stream (Black Cleaver Carve, Phage Rage, ...) cannot read the
        # positional tuple rows; keep dict rows so their scan sees the same
        # events the receipt path enriches (issue #169).
        and not has_event_scan_support_items(items)
        # The Collector's execute rides per-event threshold stamps that the
        # tuple schema cannot carry; the engine stays fail-closed for the
        # item by keeping dict rows, whose stamps the compiled walk then
        # rejects with a named receipt (issue #169).
        and item_damage_effects.execute is None
    )
    result = calculate_fight_damage(
        fight_stats,
        ability_damages,
        items,
        (
            params
            if params.enforce_resource_limits
            else replace(params, enforce_resource_limits=True)
        ),
        score_only=score_only,
        tuple_ledger=tuple_ledger,
        item_options=params.item_options,
    )
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
    if _has_riftmaker_max_stack_omnivamp(
        items,
        params.fight_duration_seconds,
        is_melee=bool(fight_stats.get("is_melee", True)),
    ):
        result["champion_stats"] = dict(fight_stats)
        result["champion_stats"]["omnivamp_percent"] = result["champion_stats"].get(
            "omnivamp_percent", 0.0
        ) + item_effects.riftmaker_max_stack_omnivamp(
            fight_duration_seconds=params.fight_duration_seconds,
            is_melee=bool(fight_stats.get("is_melee", True)),
        )
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
        + _item_self_healing_events(result, items, params.fight_duration_seconds),
        key=lambda event: (
            float(event.get("time", 0.0)),
            str(event.get("kind", "")),
            str(event.get("source", "")),
            int(event.get("_trigger_sequence", 0)),
        ),
    )
    if score_only:
        return result
    result["self_healing"] = sum(
        float(event.get("amount", 0.0)) for event in result["self_healing_events"]
    )
    auto_damage, ability_damage = split_auto_vs_ability(result["breakdown"])
    result["auto_attack_damage"] = auto_damage
    result["ability_damage"] = ability_damage
    result["damage_by_type"] = split_by_damage_type(result["breakdown"])
    return result
