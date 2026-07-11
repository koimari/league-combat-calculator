"""Ahri ability parsing and damage calculation.

Custom module needed because:
- Q (Orb of Deception): Mixed damage (magic outgoing + true returning),
  requires extracting "Damage Per Pass" attribute specifically.
- W (Fox-Fire): Multi-part damage (initial + 2 subsequent at reduced damage).
- R (Spirit Rush): Multi-dash (3 casts per activation).

All numeric values are read from the champion JSON data; nothing is
hardcoded.
"""

from typing import Any

from .common import build_stats_context, extract_leveling_damage, make_rank_fn
from .generic_parser import extract_cooldown, extract_damage


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------


def parse_abilities(
    champion_data: dict[str, Any],
    level: int,
    total_ability_power: float,
    ability_ranks: dict[str, int] | None = None,
    champion_options: dict[str, Any] | None = None,  # pylint: disable=unused-argument
    champion_stats: dict[str, float] | None = None,
    target_stats: dict[str, float] | None = None,
) -> dict[str, dict[str, Any]]:
    """Parse Ahri's abilities and calculate damage at current rank and AP.

    Args:
        champion_data: Ahri's champion data dictionary from JSON.
        level: Champion level (1-18).
        total_ability_power: Total AP after items and multipliers.
        ability_ranks: Optional dict of ability key -> rank override.
        champion_options: Champion-specific options (unused for Ahri).
        champion_stats: Champion's calculated stats (for scaling).
        target_stats: Target stats (for %HP abilities).

    Returns:
        Dictionary with ability key -> damage information.
    """
    abilities_data = champion_data.get("abilities", {})
    results: dict[str, dict[str, Any]] = {}

    stats_context = build_stats_context(champion_stats, total_ability_power)
    rank_for = make_rank_fn("Ahri", ability_ranks, level)

    # Q - Orb of Deception: magic outgoing, true returning
    q_rank = rank_for("Q")
    if q_rank > 0:
        q_ability_list = abilities_data.get("Q", [])
        if not q_ability_list:
            return results
        q_ability = q_ability_list[0]
        q_damage_per_pass = extract_leveling_damage(
            q_ability, "Damage Per Pass", q_rank, stats_context,
        )
        q_cooldown = extract_cooldown(q_ability, q_rank)
        results["Q"] = {
            "name": q_ability.get("name", "Orb of Deception"),
            "rank": q_rank,
            "cooldown": q_cooldown,
            "magic_damage": q_damage_per_pass,
            "true_damage": q_damage_per_pass,
            "total_raw": q_damage_per_pass * 2,
            "damage_type": "mixed",
        }

    # W - Fox-Fire: 3 flames, subsequent deal reduced damage
    w_rank = rank_for("W")
    if w_rank > 0:
        w_ability_list = abilities_data.get("W", [])
        if not w_ability_list:
            return results
        w_ability = w_ability_list[0]
        w_initial = extract_leveling_damage(
            w_ability, "Primary Magic Damage", w_rank, stats_context,
        )
        w_subsequent = extract_leveling_damage(
            w_ability, "Subsequent Magic Damage", w_rank, stats_context,
        )
        w_cooldown = extract_cooldown(w_ability, w_rank)
        results["W"] = {
            "name": w_ability.get("name", "Fox-Fire"),
            "rank": w_rank,
            "cooldown": w_cooldown,
            "initial_damage": w_initial,
            "subsequent_damage": w_subsequent,
            "total_raw": w_initial + (w_subsequent * 2),
            "damage_type": "magic",
        }

    # E - Charm
    e_rank = rank_for("E")
    if e_rank > 0:
        e_ability_list = abilities_data.get("E", [])
        if not e_ability_list:
            return results
        e_ability = e_ability_list[0]
        e_damage, _ = extract_damage(
            e_ability, e_rank, stats_context, target_stats,
        )
        e_cooldown = extract_cooldown(e_ability, e_rank)
        results["E"] = {
            "name": e_ability.get("name", "Charm"),
            "rank": e_rank,
            "cooldown": e_cooldown,
            "magic_damage": e_damage,
            "total_raw": e_damage,
            "damage_type": "magic",
        }

    # R - Spirit Rush: 3 dashes per activation
    r_rank = rank_for("R")
    if r_rank > 0:
        r_ability_list = abilities_data.get("R", [])
        if not r_ability_list:
            return results
        r_ability = r_ability_list[0]
        r_damage_per_cast, _ = extract_damage(
            r_ability, r_rank, stats_context, target_stats,
        )
        results["R"] = {
            "name": r_ability.get("name", "Spirit Rush"),
            "rank": r_rank,
            "damage_per_cast": r_damage_per_cast,
            "total_casts": 3,
            "total_raw": r_damage_per_cast * 3,
            "damage_type": "magic",
        }

    return results
