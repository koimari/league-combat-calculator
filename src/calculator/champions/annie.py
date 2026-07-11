"""Annie ability parsing and damage calculation.

Custom module needed because:
- P (Pyromania): Stun mechanic only, no damage — skipped.
- Q (Disintegrate): Standard magic damage — parsed from JSON.
- W (Incinerate): Standard magic damage — parsed from JSON.
- E (Molten Shield): Shield + retaliation damage — not modeled.
- R (Summon: Tibbers): Three components:
    1. Passive % magic penetration (applied before other abilities).
    2. Initial burst magic damage (parsed from JSON).
    3. Tibbers aura damage (NOT in JSON — hardcoded from wiki).
  The magic penetration is processed FIRST so Q and W benefit from it
  in the fight engine's stats_context.

All numeric values are read from the champion JSON data except Tibbers
aura tick damage, which is not present in the JSON (pet stats are not
scraped from the wiki).
"""

from typing import Any

from .common import (
    build_stats_context,
    extract_leveling_damage,
    extract_leveling_value,
    make_rank_fn,
)
from .generic_parser import extract_cooldown


# HARDCODED: verify on patch updates — pet stats are not in the JSON.
# Tibbers aura tick damage comes from the LoL Wiki directly:
# https://wiki.leagueoflegends.com/en-us/Annie
# Aura ticks every 0.25 seconds.
# Base damage per tick: 2 / 3 / 4 at R rank 1/2/3.
# AP ratio per tick: 1% AP (0.01).
_TIBBERS_AURA_BASE_PER_TICK = [2.0, 3.0, 4.0]
_TIBBERS_AURA_AP_RATIO_PER_TICK = 0.01
_TIBBERS_AURA_TICK_INTERVAL = 0.25


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
    """Parse Annie's abilities and calculate damage.

    Args:
        champion_data: Annie's champion data dictionary from JSON.
        level: Champion level (1-18).
        total_ability_power: Total AP after items and multipliers.
        ability_ranks: Optional dict of ability key -> rank override.
        champion_options: Champion-specific options. Supports:
            ``{"tibbers_aura_seconds": float}`` — seconds of Tibbers
            aura damage to include (default 5.0).
        champion_stats: Champion's calculated stats (for AD scaling).
        target_stats: Target stats (unused for Annie).

    Returns:
        Dictionary with ability key -> damage information.
    """
    abilities_data = champion_data.get("abilities", {})
    results: dict[str, dict[str, Any]] = {}

    tibbers_aura_seconds = 5.0
    if champion_options and "tibbers_aura_seconds" in champion_options:
        tibbers_aura_seconds = float(
            champion_options["tibbers_aura_seconds"],
        )

    stats_context = build_stats_context(champion_stats, total_ability_power)
    rank_for = make_rank_fn("Annie", ability_ranks, level)

    # ── R: Summon: Tibbers ─────────────────────────────────────────────
    # Process R FIRST so the passive magic penetration is applied to
    # stats_context before Q and W are calculated.
    r_rank = rank_for("R")
    if r_rank > 0:
        r_ability_list = abilities_data.get("R", [])
        if r_ability_list:
            r_ability = r_ability_list[0]

            # R passive: % magic penetration (effect[0])
            magic_pen = extract_leveling_value(
                r_ability, "Magic Penetration", r_rank,
            )
            stats_context["magic_penetration_percent"] = (
                stats_context.get("magic_penetration_percent", 0.0)
                + magic_pen
            )

            # R active: initial burst damage (effect[1])
            r_burst = extract_leveling_damage(
                r_ability, "Initial Magic Damage", r_rank, stats_context,
            )
            r_cooldown = extract_cooldown(r_ability, r_rank)

            # Tibbers aura damage (not in JSON — wiki values)
            aura_base = _TIBBERS_AURA_BASE_PER_TICK[
                min(r_rank - 1, len(_TIBBERS_AURA_BASE_PER_TICK) - 1)
            ]
            aura_per_tick = (
                aura_base
                + _TIBBERS_AURA_AP_RATIO_PER_TICK * total_ability_power
            )
            total_ticks = tibbers_aura_seconds / _TIBBERS_AURA_TICK_INTERVAL
            aura_total = aura_per_tick * total_ticks

            total_r_damage = r_burst + aura_total

            results["R"] = {
                "name": r_ability.get("name", "Summon: Tibbers"),
                "rank": r_rank,
                "cooldown": r_cooldown,
                "damage_type": "magic",
                "magic_damage": total_r_damage,
                "total_raw": total_r_damage,
                "initial_burst": r_burst,
                "tibbers_aura": {
                    "damage_per_tick": aura_per_tick,
                    "total_ticks": total_ticks,
                    "magic_damage": aura_total,
                },
                "stat_buff": {
                    "magic_penetration_percent": magic_pen,
                },
            }

    # ── P: Pyromania (stun only, no damage) ────────────────────────────
    passive_list = abilities_data.get("P", [])
    if passive_list:
        results["P"] = {
            "name": passive_list[0].get("name", "Pyromania"),
            "rank": 0,
            "cooldown": 0.0,
            "damage_type": "magic",
            "magic_damage": 0.0,
            "total_raw": 0.0,
        }

    # ── Q: Disintegrate ────────────────────────────────────────────────
    q_rank = rank_for("Q")
    if q_rank > 0:
        q_ability_list = abilities_data.get("Q", [])
        if q_ability_list:
            q_ability = q_ability_list[0]
            q_damage = extract_leveling_damage(
                q_ability, "Magic Damage", q_rank, stats_context,
            )
            q_cooldown = extract_cooldown(q_ability, q_rank)

            results["Q"] = {
                "name": q_ability.get("name", "Disintegrate"),
                "rank": q_rank,
                "cooldown": q_cooldown,
                "damage_type": "magic",
                "magic_damage": q_damage,
                "total_raw": q_damage,
            }

    # ── W: Incinerate ──────────────────────────────────────────────────
    w_rank = rank_for("W")
    if w_rank > 0:
        w_ability_list = abilities_data.get("W", [])
        if w_ability_list:
            w_ability = w_ability_list[0]
            w_damage = extract_leveling_damage(
                w_ability, "Magic Damage", w_rank, stats_context,
            )
            w_cooldown = extract_cooldown(w_ability, w_rank)

            results["W"] = {
                "name": w_ability.get("name", "Incinerate"),
                "rank": w_rank,
                "cooldown": w_cooldown,
                "damage_type": "magic",
                "magic_damage": w_damage,
                "total_raw": w_damage,
            }

    # E: Molten Shield — shield/retaliation only, not modeled
    e_rank = rank_for("E")
    if e_rank > 0:
        e_ability_list = abilities_data.get("E", [])
        if e_ability_list:
            results["E"] = {
                "name": e_ability_list[0].get("name", "Molten Shield"),
                "rank": e_rank,
                "cooldown": extract_cooldown(e_ability_list[0], e_rank),
                "damage_type": "magic",
                "magic_damage": 0.0,
                "total_raw": 0.0,
            }

    return results
