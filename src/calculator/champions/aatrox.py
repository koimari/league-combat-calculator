"""Aatrox ability parsing and damage calculation.

Custom module needed because:
- Q (The Darkin Blade): Three sequential casts with different damage each,
  plus sweetspot mechanic that amplifies damage (champion option toggle).
- P (Deathbringer Stance): On-hit magic damage (% target max health) with
  per-level scaling embedded in description text.
- R (World Ender): Grants bonus AD (% of total AD) — a stat buff that
  affects all ability and auto-attack damage, not a damage ability itself.

All numeric values are read from the champion JSON data; nothing is
hardcoded.
"""

from typing import Any

from .generic_parser import extract_cooldown, extract_damage
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
    """Extract damage for a specific attribute name from ability JSON.

    Searches all effects/leveling entries for a matching attribute and
    sums the flat base + scaling contributions at the given rank.

    Args:
        ability: Single ability dict from champion JSON.
        attribute_name: Exact attribute name to look for (e.g.
            ``"First Cast Damage"``).
        rank: Ability rank (1-indexed).
        stats_context: Champion stats for scaling resolution.

    Returns:
        Total raw damage for this attribute at the given rank.
    """
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


def _extract_r_bonus_ad_percent(
    ability: dict[str, Any],
    rank: int,
) -> float:
    """Extract R bonus AD percentage from ability JSON.

    Reads the ``"Bonus Attack Damage"`` leveling attribute which has
    values like ``[20, 30, 40]`` with units ``"% AD"``.

    Args:
        ability: R ability dict from champion JSON.
        rank: R rank (1-3).

    Returns:
        Bonus AD as a fraction (e.g. 0.20 for 20%).
    """
    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute", "") != "Bonus Attack Damage":
                continue

            for modifier in leveling.get("modifiers", []):
                values = modifier.get("values", [])
                if not values:
                    continue
                idx = min(rank - 1, len(values) - 1)
                return float(values[idx]) / 100.0

    return 0.0


def _parse_passive_on_hit(
    passive: dict[str, Any],
    level: int,
    target_stats: dict[str, float] | None = None,
) -> dict[str, Any] | None:
    """Parse Aatrox passive on-hit damage from JSON leveling data.

    The JSON now contains structured per-level data extracted from
    the wiki's ``data-bot-values`` attribute (20 values for levels
    1-20).  The passive deals a percentage of the target's max health
    as magic damage.

    Args:
        passive: Passive ability dict from champion JSON.
        level: Champion level (1-20).
        target_stats: Target stats (for target max health).

    Returns:
        On-hit data dict, or None if parsing fails.
    """
    # Find the "Max Health Damage" leveling entry
    for effect in passive.get("effects", []):
        for leveling in effect.get("leveling", []):
            attribute = leveling.get("attribute", "").lower()
            if "max health" not in attribute and "health damage" not in attribute:
                continue

            modifiers = leveling.get("modifiers", [])
            if not modifiers:
                continue

            values = modifiers[0].get("values", [])
            if not values:
                continue

            clamped_level = max(1, min(level, len(values)))
            percent = float(values[clamped_level - 1])

            target_max_health = 0.0
            if target_stats:
                target_max_health = target_stats.get(
                    "target_max_health", 0.0,
                )

            damage = (percent / 100.0) * target_max_health

            passive_name = passive.get("name", "Deathbringer Stance")
            return {
                "name": f"{passive_name} (on-hit)",
                "damage_per_hit": damage,
                "damage_type": "magic",
            }

    return None


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
    """Parse Aatrox's abilities and calculate damage.

    Args:
        champion_data: Aatrox's champion data dictionary from JSON.
        level: Champion level (1-18).
        total_ability_power: Total AP after items and multipliers.
        ability_ranks: Optional dict of ability key -> rank override.
        champion_options: Champion-specific options. Supports:
            ``{"sweetspot": bool}`` — if True (default), Q uses sweetspot
            damage values instead of normal cast damage.
        champion_stats: Champion's calculated stats (for AD scaling).
        target_stats: Target stats (for passive %HP damage).

    Returns:
        Dictionary with ability key -> damage information.
    """
    abilities_data = champion_data.get("abilities", {})
    results: dict[str, dict[str, Any]] = {}

    sweetspot = True
    if champion_options and "sweetspot" in champion_options:
        sweetspot = bool(champion_options["sweetspot"])

    # Build stats context for scaling
    stats_context: dict[str, float] = {}
    if champion_stats:
        stats_context = dict(champion_stats)
    stats_context["ability_power"] = total_ability_power

    def rank_for(key: str) -> int:
        if ability_ranks and key in ability_ranks:
            return ability_ranks[key]
        return get_ability_rank(key, level, "Aatrox")

    # ── R: World Ender (stat buff, no damage) ──────────────────────────
    r_rank = rank_for("R")
    if r_rank > 0:
        r_ability_list = abilities_data.get("R", [])
        if r_ability_list:
            r_ability = r_ability_list[0]
            bonus_ad_fraction = _extract_r_bonus_ad_percent(
                r_ability, r_rank,
            )

            # Apply R bonus AD to stats context for Q/W calculations
            base_ad = stats_context.get("attack_damage", 0.0)
            bonus_ad = base_ad * bonus_ad_fraction
            stats_context["attack_damage"] = base_ad + bonus_ad
            stats_context["bonus_attack_damage"] = (
                stats_context.get("bonus_attack_damage", 0.0) + bonus_ad
            )

            r_cooldown = extract_cooldown(r_ability, r_rank)

            results["R"] = {
                "name": r_ability.get("name", "World Ender"),
                "rank": r_rank,
                "cooldown": r_cooldown,
                "damage_type": "physical",
                "total_raw": 0.0,
                "physical_damage": 0.0,
                "stat_buff": {
                    "bonus_attack_damage": bonus_ad,
                },
            }

    # ── Q: The Darkin Blade (three casts) ──────────────────────────────
    q_rank = rank_for("Q")
    if q_rank > 0:
        q_ability_list = abilities_data.get("Q", [])
        if q_ability_list:
            q_ability = q_ability_list[0]

            if sweetspot:
                attr_names = [
                    "First Sweetspot Damage",
                    "Second Sweetspot Damage",
                    "Third Sweetspot Damage",
                ]
            else:
                attr_names = [
                    "First Cast Damage",
                    "Second Cast Damage",
                    "Third Cast Damage",
                ]

            total_q_damage = 0.0
            for attr_name in attr_names:
                total_q_damage += _extract_leveling_damage(
                    q_ability, attr_name, q_rank, stats_context,
                )

            q_cooldown = extract_cooldown(q_ability, q_rank)

            results["Q"] = {
                "name": q_ability.get("name", "The Darkin Blade"),
                "rank": q_rank,
                "cooldown": q_cooldown,
                "damage_type": "physical",
                "physical_damage": total_q_damage,
                "total_raw": total_q_damage,
            }

    # ── W: Infernal Chains (hits twice: initial + pull-back) ─────────
    w_rank = rank_for("W")
    if w_rank > 0:
        w_ability_list = abilities_data.get("W", [])
        if w_ability_list:
            w_ability = w_ability_list[0]
            # Use "Total Damage" attribute (initial + pull-back combined)
            # rather than "Physical Damage" (single hit only).
            w_damage = _extract_leveling_damage(
                w_ability, "Total Damage", w_rank, stats_context,
            )
            w_cooldown = extract_cooldown(w_ability, w_rank)

            if w_damage > 0:
                results["W"] = {
                    "name": w_ability.get("name", "Infernal Chains"),
                    "rank": w_rank,
                    "cooldown": w_cooldown,
                    "damage_type": "physical",
                    "physical_damage": w_damage,
                    "total_raw": w_damage,
                }

    # E: Umbral Dash — no damage, skipped

    # ── P: Deathbringer Stance (on-hit) ────────────────────────────────
    passive_list = abilities_data.get("P", [])
    if passive_list:
        on_hit = _parse_passive_on_hit(
            passive_list[0], level, target_stats,
        )
        if on_hit:
            results["passive"] = {
                "name": passive_list[0].get("name", "Deathbringer Stance"),
                "on_hit": on_hit,
            }

    return results
