"""The receipts and display splits attached to a finished fight."""

from collections.abc import Mapping
from typing import Any

from . import item_effects
from .cast_edge_markers import detect_aoe_cap
from .damage import split_auto_vs_ability, split_by_damage_type
from .fight_params import FightParams
from .healing_reduction import amplifies_recovery, heal_and_shield_power_factor
from .rune_sustain_events import _saturated_omnivamp_percent


def _attach_engine_receipts(
    result: dict[str, Any],
    params: "FightParams",
    items: list[dict[str, Any]],
    fight_stats: Mapping[str, Any],
    *,
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
    # The champion is its own caster here, so its heal and shield power
    # amplifies its self-heals — read through the one rule the survival
    # walk reads, so the published scalar and the walk cannot disagree.
    heal_power = heal_and_shield_power_factor(result.get("champion_stats"))
    result["self_healing"] = sum(
        float(event.get("amount", 0.0))
        * (
            heal_power
            if amplifies_recovery(
                str(event.get("kind", "")),
                str(event.get("healing_category", "")),
            )
            else 1.0
        )
        for event in result["self_healing_events"]
    )
    auto_damage, ability_damage = split_auto_vs_ability(result["breakdown"])
    result["auto_attack_damage"] = auto_damage
    result["ability_damage"] = ability_damage
    result["damage_by_type"] = split_by_damage_type(result["breakdown"])


def _annotate_deathfire_categories(
    ability_damages: Mapping[str, dict[str, Any]],
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
