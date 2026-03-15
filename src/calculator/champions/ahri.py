"""Ahri ability parsing and damage calculation.

Data sources:
- Base damages and ratios: https://wiki.leagueoflegends.com/en-us/Ahri
- Fox-Fire subsequent flames deal 40% of initial damage (wiki-verified;
  the CDN data shows 30% which is outdated).
"""

from typing import Any

from .common import calculate_ability_damage


# Standard Ahri skill order: Q > W > E, R at 6/11/16
# Level:  1  2  3  4  5  6  7  8  9 10 11 12 13 14 15 16 17 18
# Skill:  Q  W  E  Q  Q  R  Q  W  Q  W  R  W  W  E  E  R  E  E
SKILL_ORDER: list[str] = [
    "Q", "W", "E", "Q", "Q", "R",
    "Q", "W", "Q", "W", "R", "W",
    "W", "E", "E", "R", "E", "E",
]

# Base cooldowns per rank (index 0 = rank 1)
COOLDOWNS: dict[str, list[float]] = {
    "Q": [7.0, 7.0, 7.0, 7.0, 7.0],
    "W": [10.0, 9.0, 8.0, 7.0, 6.0],
    "E": [12.0, 12.0, 12.0, 12.0, 12.0],
}


def get_ability_rank(ability_key: str, champion_level: int) -> int:
    """Determine ability rank based on standard Ahri skill order: Q > W > E.

    R is taken at levels 6, 11, 16.

    Args:
        ability_key: One of 'Q', 'W', 'E', 'R'.
        champion_level: Champion's current level (1-18).

    Returns:
        Ability rank (1-5 for basic abilities, 1-3 for R).
    """
    rank = 0
    for i in range(min(champion_level, 18)):
        if SKILL_ORDER[i] == ability_key:
            rank += 1
    return rank


def get_effective_cooldown(
    ability_key: str,
    rank: int,
    ability_haste: float = 0.0,
) -> float:
    """Calculate effective cooldown for an Ahri ability after ability haste.

    Formula: base_cd * 100 / (100 + ability_haste)

    Args:
        ability_key: One of 'Q', 'W', 'E'.
        rank: Ability rank (1-5).
        ability_haste: Total ability haste.

    Returns:
        Effective cooldown in seconds.
    """
    if ability_key not in COOLDOWNS or rank < 1:
        return 0.0
    base_cd = COOLDOWNS[ability_key][rank - 1]
    return base_cd * (100.0 / (100.0 + ability_haste))


def parse_abilities(
    champion_data: dict[str, Any],  # noqa: ARG001
    level: int,
    total_ability_power: float,
    ability_ranks: dict[str, int] | None = None,
) -> dict[str, dict[str, Any]]:
    """Parse Ahri's abilities and calculate damage at current rank and AP.

    Each ability entry includes a ``cooldown`` field so the fight engine
    can compute cast counts without champion-specific knowledge.

    Args:
        champion_data: Ahri's champion data dictionary (reserved for
            future use with generic champion parsing).
        level: Champion level (1-18).
        total_ability_power: Total AP after items and multipliers.
        ability_ranks: Optional dict of ability key -> rank override.
            e.g. {"Q": 5, "W": 3, "E": 1, "R": 2}. If None, ranks
            are auto-calculated from champion level using standard
            Ahri skill order.

    Returns:
        Dictionary with ability key -> damage information.
    """
    _ = champion_data  # Will be used for generic champion parsing
    results: dict[str, dict[str, Any]] = {}

    def rank_for(key: str) -> int:
        if ability_ranks and key in ability_ranks:
            return ability_ranks[key]
        return get_ability_rank(key, level)

    # Q - Orb of Deception: magic outgoing, true returning
    q_rank = rank_for("Q")
    if q_rank > 0:
        q_base_values = [40, 65, 90, 115, 140]
        q_ap_ratio = 0.50
        q_base = q_base_values[q_rank - 1]
        q_damage_per_pass = calculate_ability_damage(q_base, q_ap_ratio, total_ability_power)
        results["Q"] = {
            "name": "Orb of Deception",
            "rank": q_rank,
            "cooldown": COOLDOWNS["Q"][q_rank - 1],
            "magic_damage": q_damage_per_pass,
            "true_damage": q_damage_per_pass,
            "total_raw": q_damage_per_pass * 2,
            "damage_type": "mixed",
        }

    # W - Fox-Fire: 3 flames, subsequent = 40% of initial (wiki-verified)
    w_rank = rank_for("W")
    if w_rank > 0:
        w_base_values = [40, 60, 80, 100, 120]
        w_ap_ratio = 0.40
        w_base = w_base_values[w_rank - 1]
        w_initial = calculate_ability_damage(w_base, w_ap_ratio, total_ability_power)
        w_subsequent = w_initial * 0.40
        results["W"] = {
            "name": "Fox-Fire",
            "rank": w_rank,
            "cooldown": COOLDOWNS["W"][w_rank - 1],
            "initial_damage": w_initial,
            "subsequent_damage": w_subsequent,
            "total_raw": w_initial + (w_subsequent * 2),
            "damage_type": "magic",
        }

    # E - Charm
    e_rank = rank_for("E")
    if e_rank > 0:
        e_base_values = [80, 120, 160, 200, 240]
        e_ap_ratio = 0.85
        e_base = e_base_values[e_rank - 1]
        e_damage = calculate_ability_damage(e_base, e_ap_ratio, total_ability_power)
        results["E"] = {
            "name": "Charm",
            "rank": e_rank,
            "cooldown": COOLDOWNS["E"][e_rank - 1],
            "magic_damage": e_damage,
            "total_raw": e_damage,
            "damage_type": "magic",
        }

    # R - Spirit Rush: 3 dashes per activation
    r_rank = rank_for("R")
    if r_rank > 0:
        r_base_values = [75, 125, 175]
        r_ap_ratio = 0.35
        r_base = r_base_values[r_rank - 1]
        r_damage_per_cast = calculate_ability_damage(r_base, r_ap_ratio, total_ability_power)
        results["R"] = {
            "name": "Spirit Rush",
            "rank": r_rank,
            "damage_per_cast": r_damage_per_cast,
            "total_casts": 3,
            "total_raw": r_damage_per_cast * 3,
            "damage_type": "magic",
        }

    return results
