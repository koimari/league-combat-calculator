"""Ashe ability parsing and damage calculation.

Custom module needed because:
- P (Frost Shot): Unique crit mechanic — critical strikes deal no bonus damage.
  Instead, crit chance converts to bonus physical damage on every auto attack.
  Auto damage = total_AD * (1 + crit_chance) instead of the normal total_AD.
- Q (Ranger's Focus): Empowered autos that deal a flurry of damage at a
  modified AD ratio. Passive crit bonus applies on top of flurry ratio.
  Also grants bonus attack speed.

All numeric values are read from the champion JSON data; nothing is
hardcoded.
"""

from typing import Any

from .generic_parser import extract_cooldown
from .scaling import is_flat_unit, resolve_scaling
from .skill_orders import get_ability_rank


# ---------------------------------------------------------------------------
# JSON extraction helpers
# ---------------------------------------------------------------------------


def _extract_leveling_damage(
    ability: dict[str, Any],
    attribute_name: str,
    rank: int,
    stats_context: dict[str, float] | None = None,
) -> float:
    """Extract damage for a specific attribute name from ability JSON."""
    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute", "") != attribute_name:
                continue

            total = 0.0
            for modifier in leveling.get("modifiers", []):
                values = modifier.get("values", [])
                units = modifier.get("units", [])
                if not values:
                    continue

                idx = min(rank - 1, len(values) - 1)
                value = float(values[idx])
                unit = units[idx] if idx < len(units) else ""

                if is_flat_unit(unit):
                    total += value
                else:
                    total += resolve_scaling(
                        unit, value, stats_context, None,
                    )
            return total

    return 0.0


def _extract_leveling_raw_value(
    ability: dict[str, Any],
    attribute_name: str,
    rank: int,
    modifier_index: int = 0,
) -> float:
    """Extract a raw numeric value from a specific leveling attribute.

    Unlike ``_extract_leveling_damage``, this does NOT resolve scaling —
    it returns the raw value from the JSON (e.g. 110 for "110% AD").

    Args:
        ability: Ability dict from champion JSON.
        attribute_name: Exact attribute name to find.
        rank: Ability rank (1-indexed).
        modifier_index: Which modifier to read (default 0 = first).

    Returns:
        Raw numeric value at the given rank, or 0.0 if not found.
    """
    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute", "") != attribute_name:
                continue

            modifiers = leveling.get("modifiers", [])
            if modifier_index >= len(modifiers):
                return 0.0

            values = modifiers[modifier_index].get("values", [])
            if not values:
                return 0.0

            idx = min(rank - 1, len(values) - 1)
            return float(values[idx])

    return 0.0


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
    """Parse Ashe's abilities and calculate damage.

    Args:
        champion_data: Ashe's champion data dictionary from JSON.
        level: Champion level (1-18).
        total_ability_power: Total AP after items and multipliers.
        ability_ranks: Optional dict of ability key -> rank override.
        champion_options: Champion-specific options. Supports:
            ``{"q_active": bool}`` — if True (default), Q is active,
            granting bonus attack speed and flurry auto damage.
        champion_stats: Champion's calculated stats (for AD scaling).
        target_stats: Target stats.

    Returns:
        Dictionary with ability key -> damage information.
    """
    abilities_data = champion_data.get("abilities", {})
    results: dict[str, dict[str, Any]] = {}

    q_active = True
    if champion_options and "q_active" in champion_options:
        q_active = bool(champion_options["q_active"])

    # Build stats context for scaling
    stats_context: dict[str, float] = {}
    if champion_stats:
        stats_context = dict(champion_stats)
    stats_context["ability_power"] = total_ability_power

    def rank_for(key: str) -> int:
        if ability_ranks and key in ability_ranks:
            return ability_ranks[key]
        return get_ability_rank(key, level, "Ashe")

    # ── Q: Ranger's Focus (stat buff + auto modifier, no direct damage) ──
    q_rank = rank_for("Q")
    if q_rank > 0 and q_active:
        q_ability_list = abilities_data.get("Q", [])
        if q_ability_list:
            q_ability = q_ability_list[0]

            # Extract bonus attack speed from JSON
            bonus_as_pct = _extract_leveling_raw_value(
                q_ability, "Bonus Attack Speed", q_rank,
            )

            # Extract flurry AD ratio (e.g. 110 = 110% AD -> 1.10 ratio)
            flurry_pct = _extract_leveling_raw_value(
                q_ability, "Total Damage Per Flurry", q_rank,
            )
            flurry_ratio = flurry_pct / 100.0  # Convert 110% -> 1.10

            q_cooldown = extract_cooldown(q_ability, q_rank)

            # Apply bonus AS to stats_context
            as_ratio = stats_context.get("attack_speed_ratio", 0.625)
            stats_context["attack_speed"] = (
                stats_context.get("attack_speed", 0.0)
                + as_ratio * (bonus_as_pct / 100.0)
            )

            results["Q"] = {
                "name": q_ability.get("name", "Ranger's Focus"),
                "rank": q_rank,
                "cooldown": q_cooldown,
                "damage_type": "physical",
                "total_raw": 0.0,
                "physical_damage": 0.0,
                "stat_buff": {
                    "bonus_attack_speed": bonus_as_pct,
                },
                "auto_attack_override": {
                    "ad_ratio": flurry_ratio,
                    "crit_as_bonus": True,
                },
            }

    # ── Passive: Frost Shot (auto attack crit override) ──────────────────
    # The passive modifies auto attacks so crit chance converts to bonus
    # damage instead of crit strikes. This is communicated to damage.py
    # via auto_attack_override.
    passive_list = abilities_data.get("P", [])
    if passive_list:
        passive = passive_list[0]
        # If Q is not active or not ranked, the passive still applies with
        # base 1.0 AD ratio (normal auto attack)
        if "Q" not in results:
            results["passive"] = {
                "name": passive.get("name", "Frost Shot"),
                "total_raw": 0.0,
                "damage_type": "physical",
                "auto_attack_override": {
                    "ad_ratio": 1.0,
                    "crit_as_bonus": True,
                },
            }
        else:
            # Q is active — the Q entry already has the override with
            # the flurry ratio. We still record the passive for display.
            results["passive"] = {
                "name": passive.get("name", "Frost Shot"),
                "total_raw": 0.0,
                "damage_type": "physical",
            }

    # ── W: Volley (physical damage) ──────────────────────────────────────
    w_rank = rank_for("W")
    if w_rank > 0:
        w_ability_list = abilities_data.get("W", [])
        if w_ability_list:
            w_ability = w_ability_list[0]
            w_damage = _extract_leveling_damage(
                w_ability, "Physical Damage", w_rank, stats_context,
            )
            w_cooldown = extract_cooldown(w_ability, w_rank)

            results["W"] = {
                "name": w_ability.get("name", "Volley"),
                "rank": w_rank,
                "cooldown": w_cooldown,
                "damage_type": "physical",
                "physical_damage": w_damage,
                "total_raw": w_damage,
            }

    # E: Hawkshot — utility only, no damage. Skipped.

    # ── R: Enchanted Crystal Arrow (magic damage) ────────────────────────
    r_rank = rank_for("R")
    if r_rank > 0:
        r_ability_list = abilities_data.get("R", [])
        if r_ability_list:
            r_ability = r_ability_list[0]
            r_damage = _extract_leveling_damage(
                r_ability, "Magic Damage", r_rank, stats_context,
            )
            r_cooldown = extract_cooldown(r_ability, r_rank)

            results["R"] = {
                "name": r_ability.get("name", "Enchanted Crystal Arrow"),
                "rank": r_rank,
                "cooldown": r_cooldown,
                "damage_type": "magic",
                "magic_damage": r_damage,
                "total_raw": r_damage,
            }

    return results
