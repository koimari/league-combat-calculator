"""Vayne ability parsing and damage calculation.

Custom module needed because:
- Q (Tumble): Empowered auto attack dealing bonus physical damage as a
  percentage of total AD plus AP scaling. One enhanced auto per cast.
- W (Silver Bolts): Passive 3-stack proc dealing true damage (% max HP)
  on every 3rd hit. Not a castable ability — procs are calculated from
  total auto attacks in the fight.
- E (Condemn): Single-target physical damage with conditional wall stun
  bonus damage (champion option toggle).
- R (Final Hour): Stat buff granting bonus AD (always active if ranked),
  plus Q cooldown reduction while active.

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
    """Parse Vayne's abilities and calculate damage.

    Args:
        champion_data: Vayne's champion data dictionary from JSON.
        level: Champion level (1-18).
        total_ability_power: Total AP after items and multipliers.
        ability_ranks: Optional dict of ability key -> rank override.
        champion_options: Champion-specific options. Supports:
            ``{"condemn_wall": bool}`` — if True (default), Condemn
            target hits a wall for bonus damage + stun.
        champion_stats: Champion's calculated stats (for AD scaling).
        target_stats: Target stats (for W %HP damage).

    Returns:
        Dictionary with ability key -> damage information.
    """
    abilities_data = champion_data.get("abilities", {})
    results: dict[str, dict[str, Any]] = {}

    condemn_wall = True
    if champion_options and "condemn_wall" in champion_options:
        condemn_wall = bool(champion_options["condemn_wall"])

    stats_context = build_stats_context(champion_stats, total_ability_power)
    rank_for = make_rank_fn("Vayne", ability_ranks, level)

    # ── R: Final Hour (stat buff, no damage) ──────────────────────────
    r_rank = rank_for("R")
    q_cd_reduction_percent = 0.0
    if r_rank > 0:
        r_ability_list = abilities_data.get("R", [])
        if r_ability_list:
            r_ability = r_ability_list[0]

            # Bonus AD (flat, not percentage)
            bonus_ad = extract_leveling_value(
                r_ability, "Bonus Attack Damage", r_rank,
            )

            # Q cooldown reduction percentage
            q_cd_reduction_percent = extract_leveling_value(
                r_ability, "Tumble Cooldown Reduction", r_rank,
            )

            # Apply R bonus AD to stats context for Q/E calculations
            stats_context["attack_damage"] = (
                stats_context.get("attack_damage", 0.0) + bonus_ad
            )
            stats_context["bonus_attack_damage"] = (
                stats_context.get("bonus_attack_damage", 0.0) + bonus_ad
            )

            r_cooldown = extract_cooldown(r_ability, r_rank)

            results["R"] = {
                "name": r_ability.get("name", "Final Hour"),
                "rank": r_rank,
                "cooldown": r_cooldown,
                "damage_type": "physical",
                "total_raw": 0.0,
                "physical_damage": 0.0,
                "stat_buff": {
                    "bonus_attack_damage": bonus_ad,
                },
            }

    # ── Q: Tumble (empowered auto, bonus physical damage) ────────────
    q_rank = rank_for("Q")
    if q_rank > 0:
        q_ability_list = abilities_data.get("Q", [])
        if q_ability_list:
            q_ability = q_ability_list[0]

            # Bonus Physical Damage scales as %AD + %AP
            q_damage = extract_leveling_damage(
                q_ability, "Bonus Physical Damage", q_rank, stats_context,
            )

            q_base_cooldown = extract_cooldown(q_ability, q_rank)

            # Apply R cooldown reduction to Q if R is active
            if q_cd_reduction_percent > 0:
                q_effective_cd = q_base_cooldown * (
                    1.0 - q_cd_reduction_percent / 100.0
                )
            else:
                q_effective_cd = q_base_cooldown

            results["Q"] = {
                "name": q_ability.get("name", "Tumble"),
                "rank": q_rank,
                "cooldown": q_effective_cd,
                "damage_type": "physical",
                "physical_damage": q_damage,
                "total_raw": q_damage,
            }

    # ── W: Silver Bolts (passive 3-stack true damage proc) ───────────
    # Modeled as on-hit with damage_per_hit = per_proc / 3 so the fight
    # engine integrates it with Rageblade phantom hits, Dusk & Dawn
    # double on-hit, etc.  Each auto contributes 1/3 of a proc's worth
    # of true damage on average.
    w_rank = rank_for("W")
    if w_rank > 0:
        w_ability_list = abilities_data.get("W", [])
        if w_ability_list:
            w_ability = w_ability_list[0]

            # % max HP true damage from effect[1].leveling[0]
            base_percent = extract_leveling_value(
                w_ability, "Bonus True Damage", w_rank, modifier_index=0,
            )

            # Minimum bonus damage from effect[1].leveling[1]
            minimum_damage = extract_leveling_value(
                w_ability, "Minimum Bonus Damage", w_rank, modifier_index=0,
            )

            # Calculate per-proc damage against target max health
            target_max_health = 0.0
            if target_stats:
                target_max_health = target_stats.get(
                    "target_max_health", 0.0,
                )

            hp_damage = (base_percent / 100.0) * target_max_health
            per_proc_damage = max(hp_damage, minimum_damage)
            stacks_required = 3
            damage_per_hit = per_proc_damage / stacks_required

            results["W"] = {
                "name": w_ability.get("name", "Silver Bolts"),
                "rank": w_rank,
                "damage_type": "true",
                "total_raw": 0.0,
                "true_damage": 0.0,
                "on_hit": {
                    "name": "Silver Bolts",
                    "damage_per_hit": damage_per_hit,
                    "damage_type": "true",
                    "stacks_required": stacks_required,
                },
            }

    # ── E: Condemn (physical damage, optional wall bonus) ─────────────
    e_rank = rank_for("E")
    if e_rank > 0:
        e_ability_list = abilities_data.get("E", [])
        if e_ability_list:
            e_ability = e_ability_list[0]

            if condemn_wall:
                # Use Total Physical Damage (base + wall bonus combined)
                e_damage = extract_leveling_damage(
                    e_ability, "Total Physical Damage", e_rank,
                    stats_context,
                )
            else:
                # Use base Physical Damage only (no wall hit)
                e_damage = extract_leveling_damage(
                    e_ability, "Physical Damage", e_rank, stats_context,
                )

            e_cooldown = extract_cooldown(e_ability, e_rank)

            results["E"] = {
                "name": e_ability.get("name", "Condemn"),
                "rank": e_rank,
                "cooldown": e_cooldown,
                "damage_type": "physical",
                "physical_damage": e_damage,
                "total_raw": e_damage,
            }

    return results


