"""Kog'Maw ability parsing and damage calculation.

Custom module needed because:
- Q (Caustic Spittle): Active magic damage + passive bonus attack speed +
  resistance shred (champion option toggle) that reduces target armor and MR
  before all other damage calculations.
- W (Bio-Arcane Barrage): On-hit % max HP magic damage (champion option
  toggle). Purely an on-hit buff with no direct cast damage.
- E (Void Ooze): Standard magic damage.
- R (Living Artillery): Magic damage with dynamic missing HP scaling.
  Damage increases by 0-50% based on target missing health (linear up to
  60% missing), or by 100% if target is below 40% max HP.
- P (Icathian Surprise): Death passive, not modeled.

All numeric values are read from the champion JSON data; nothing is
hardcoded.
"""

from typing import Any

from .common import (
    build_stats_context,
    extract_leveling_damage,
    extract_leveling_value,
    make_rank_fn,
)
from .generic_parser import extract_cooldown


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------


def parse_abilities(
    champion_data: dict[str, Any],
    level: int,
    total_ability_power: float,
    ability_ranks: dict[str, int] | None = None,
    champion_options: dict[str, Any] | None = None,
    champion_stats: dict[str, float] | None = None,
    target_stats: dict[str, float] | None = None,
) -> dict[str, dict[str, Any]]:
    """Parse Kog'Maw's abilities and calculate damage.

    Args:
        champion_data: Kog'Maw's champion data dictionary from JSON.
        level: Champion level (1-18).
        total_ability_power: Total AP after items and multipliers.
        ability_ranks: Optional dict of ability key -> rank override.
        champion_options: Champion-specific options. Supports:
            ``{"q_shred": bool}`` -- if True (default), Q applies resistance
            shred to target armor and MR before all other damage.
            ``{"w_active": bool}`` -- if True (default), W adds on-hit
            % max HP magic damage to every auto attack.
        champion_stats: Champion's calculated stats (for AD scaling).
        target_stats: Target stats (for W %HP and R missing HP scaling).

    Returns:
        Dictionary with ability key -> damage information.
    """
    abilities_data = champion_data.get("abilities", {})
    results: dict[str, dict[str, Any]] = {}

    q_shred = True
    if champion_options and "q_shred" in champion_options:
        q_shred = bool(champion_options["q_shred"])

    w_active = True
    if champion_options and "w_active" in champion_options:
        w_active = bool(champion_options["w_active"])

    stats_context = build_stats_context(champion_stats, total_ability_power)
    rank_for = make_rank_fn("Kog'Maw", ability_ranks, level)

    # ── Q: Caustic Spittle (magic damage + AS buff + resistance shred) ──
    q_rank = rank_for("Q")
    if q_rank > 0:
        q_ability_list = abilities_data.get("Q", [])
        if q_ability_list:
            q_ability = q_ability_list[0]

            # Active damage
            q_damage = extract_leveling_damage(
                q_ability, "Magic Damage", q_rank, stats_context,
            )
            q_cooldown = extract_cooldown(q_ability, q_rank)

            # Passive: bonus attack speed
            bonus_as = extract_leveling_value(
                q_ability, "Bonus Attack Speed", q_rank,
            )

            # Resistance shred percentage
            shred_percent = extract_leveling_value(
                q_ability, "Resistances Reduction", q_rank,
            )

            q_result: dict[str, Any] = {
                "name": q_ability.get("name", "Caustic Spittle"),
                "rank": q_rank,
                "cooldown": q_cooldown,
                "damage_type": "magic",
                "magic_damage": q_damage,
                "total_raw": q_damage,
            }

            # Apply bonus AS as a stat buff so the fight engine
            # recalculates auto attacks with the extra attack speed.
            stat_buff: dict[str, float] = {}
            if bonus_as > 0:
                stat_buff["bonus_attack_speed"] = bonus_as

            if stat_buff:
                q_result["stat_buff"] = stat_buff

            # Resistance shred: reduce target armor and MR by a percentage.
            # Processed by damage.py before all other damage calculations.
            if q_shred and shred_percent > 0:
                q_result["target_debuff"] = {
                    "armor_reduction_percent": shred_percent,
                    "mr_reduction_percent": shred_percent,
                }

            results["Q"] = q_result

    # ── W: Bio-Arcane Barrage (on-hit % max HP magic damage) ────────────
    w_rank = rank_for("W")
    if w_rank > 0 and w_active:
        w_ability_list = abilities_data.get("W", [])
        if w_ability_list:
            w_ability = w_ability_list[0]
            w_cooldown = extract_cooldown(w_ability, w_rank)

            # Extract base % max HP from "Bonus Magic Damage" attribute
            base_percent = extract_leveling_value(
                w_ability, "Bonus Magic Damage", w_rank, modifier_index=0,
            )

            # AP scaling: 1.5% per 100 AP (second modifier)
            ap_ratio_per_100 = extract_leveling_value(
                w_ability, "Bonus Magic Damage", w_rank, modifier_index=1,
            )

            # Calculate on-hit damage vs target max health
            target_max_health = 0.0
            if target_stats:
                target_max_health = target_stats.get(
                    "target_max_health", 0.0,
                )

            ap = stats_context.get("ability_power", 0.0)
            # Formula: (base_percent/100 + ap * ap_ratio_per_100/100/100)
            #          * target_max_health
            on_hit_damage = (
                base_percent / 100.0
                + ap * ap_ratio_per_100 / 100.0 / 100.0
            ) * target_max_health

            results["W"] = {
                "name": w_ability.get("name", "Bio-Arcane Barrage"),
                "rank": w_rank,
                "cooldown": w_cooldown,
                "damage_type": "magic",
                "total_raw": 0.0,
                "magic_damage": 0.0,
                "on_hit": {
                    "name": "Bio-Arcane Barrage (on-hit)",
                    "damage_per_hit": on_hit_damage,
                    "damage_type": "magic",
                },
            }

    # ── E: Void Ooze (standard magic damage) ────────────────────────────
    e_rank = rank_for("E")
    if e_rank > 0:
        e_ability_list = abilities_data.get("E", [])
        if e_ability_list:
            e_ability = e_ability_list[0]
            e_damage = extract_leveling_damage(
                e_ability, "Magic Damage", e_rank, stats_context,
            )
            e_cooldown = extract_cooldown(e_ability, e_rank)

            if e_damage > 0:
                results["E"] = {
                    "name": e_ability.get("name", "Void Ooze"),
                    "rank": e_rank,
                    "cooldown": e_cooldown,
                    "damage_type": "magic",
                    "magic_damage": e_damage,
                    "total_raw": e_damage,
                }

    # ── R: Living Artillery (magic damage + missing HP scaling) ─────────
    r_rank = rank_for("R")
    if r_rank > 0:
        r_ability_list = abilities_data.get("R", [])
        if r_ability_list:
            r_ability = r_ability_list[0]

            # Base (minimum) damage with bonus AD and AP scaling
            r_min_damage = extract_leveling_damage(
                r_ability, "Minimum Magic Damage", r_rank, stats_context,
            )
            r_cooldown = extract_cooldown(r_ability, r_rank)

            results["R"] = {
                "name": r_ability.get("name", "Living Artillery"),
                "rank": r_rank,
                "cooldown": r_cooldown,
                "damage_type": "magic",
                "magic_damage": r_min_damage,
                "total_raw": r_min_damage,
                "missing_hp_scaling": True,
                "r_base_damage": r_min_damage,
            }

    return results
