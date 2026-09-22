"""The receipts and display splits attached to a finished fight."""

from collections.abc import Mapping
from functools import partial
from typing import Any

from . import item_effects
from .cast_edge_markers import detect_aoe_cap
from .damage import split_auto_vs_ability, split_by_damage_type
from .event_row_field import required_field
from .fight_params import FightParams
from .fight_result_row import result_breakdown
from .heal_event_row import healed_category
from .healing_reduction import amplifies_recovery, heal_and_shield_power_factor
from .rune_sustain_events import _saturated_omnivamp_percent

#: The stat block is one dict literal in ``stats.calculate_total_stats``, so
#: every name below is on every block: absent is a renamed producer key, and
#: reading it as zero is how a receipt publishes a build it never measured.
_fight_stat = partial(
    required_field, kind="champion stat block", stamper="stats.calculate_total_stats"
)


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
        is_melee=bool(_fight_stat(fight_stats, "is_melee")),
        bonus_health=float(_fight_stat(fight_stats, "bonus_health")),
        bonus_mana=float(_fight_stat(fight_stats, "bonus_mana")),
        max_mana=float(_fight_stat(fight_stats, "max_mana")),
        total_attack_damage=float(_fight_stat(fight_stats, "attack_damage")),
        total_move_speed=float(_fight_stat(fight_stats, "move_speed")),
        lethality=float(_fight_stat(fight_stats, "lethality")),
    )
    # The auto row is the one breakdown key that exists only when the fight
    # swung: absent is a rotation that never reached a basic attack.
    auto_row = result_breakdown(result).get("auto_attacks")
    auto_total = int(auto_row["count"]) if isinstance(auto_row, Mapping) else 0
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
        is_melee=bool(_fight_stat(fight_stats, "is_melee")),
    )
    if saturated_omnivamp:
        republished = dict(fight_stats)
        republished["omnivamp_percent"] = (
            _fight_stat(republished, "omnivamp_percent") + saturated_omnivamp
        )
        result["champion_stats"] = republished


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
        # Indexed: this iterates result["self_healing_events"], the stream
        # docs/receipts/internal-row-census.json measures at 443 rows over
        # all 173 champions with amount, kind, source and time on every one.
        # healing_category is NOT among them, so it reads through the one
        # optional accessor heal_event_row declares.
        float(event["amount"])
        * (
            heal_power
            if amplifies_recovery(str(event["kind"]), healed_category(event) or "")
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
