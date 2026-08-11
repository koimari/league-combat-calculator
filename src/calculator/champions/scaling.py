"""Resolve ability scaling from JSON unit strings to computed damage values.

Maps the wiki-scraped unit strings (e.g. ``"% AP"``, ``"% bonus AD"``,
``"% of target's maximum health"``) to actual stat lookups and computes
the scaled damage contribution.
"""

import re

from .inputs import scaling_input

# ---------------------------------------------------------------------------
# Unit string → stat key mapping
# ---------------------------------------------------------------------------

# Simple unit string → (stat_key, divisor)
# The value from JSON is multiplied by (stat_value / divisor).
# For "% AP" with value 50: damage = 50/100 * AP = 0.5 * AP
_SIMPLE_UNITS: dict[str, tuple[str, float]] = {
    "% AP": ("ability_power", 100.0),
    "% AD": ("attack_damage", 100.0),
    "% bonus AD": ("bonus_attack_damage", 100.0),
    "% total AD": ("attack_damage", 100.0),
    "% bonus health": ("bonus_health", 100.0),
    "% maximum health": ("health", 100.0),
    "% bonus armor": ("bonus_armor", 100.0),
    "% total armor": ("armor", 100.0),
    "% armor": ("armor", 100.0),
    "% bonus magic resistance": ("bonus_magic_resistance", 100.0),
    "% total magic resistance": ("magic_resistance", 100.0),
    "% magic resistance": ("magic_resistance", 100.0),
    "% maximum mana": ("max_mana", 100.0),
    "% bonus mana": ("bonus_mana", 100.0),
    "% base AD": ("base_attack_damage", 100.0),
    "% base health": ("base_health", 100.0),
    # Target health scaling
    "% of target's maximum health": ("target_max_health", 100.0),
    "% of target's current health": ("target_current_health", 100.0),
    "% of target's missing health": ("target_missing_health", 100.0),
    "% target's maximum health": ("target_max_health", 100.0),
}

# "per 100 stat" patterns: value scales per 100 of a stat
# e.g. "% per 100 AP" with value 2 means 2% per 100 AP = 0.02 * AP
_PER_100_UNITS: dict[str, str] = {
    "% per 100 AP": "ability_power",
    "% per 100 bonus AD": "bonus_attack_damage",
    "% per 100 bonus armor": "armor",
    "% per 100 bonus magic resistance": "magic_resistance",
    "% per 100 bonus health": "bonus_health",
    "% per 100 AD": "attack_damage",
}


def resolve_scaling(
    unit: str,
    value: float,
    champion_stats: dict[str, float] | None = None,
    target_stats: dict[str, float] | None = None,
) -> float:
    """Resolve a single scaling modifier to a damage value.

    Args:
        unit: The unit string from JSON (e.g. ``"% AP"``).
        value: The numeric value from JSON (e.g. ``50`` for 50% AP).
        champion_stats: Champion's calculated stats dict.
        target_stats: Target's stats dict (for %HP abilities).

    Returns:
        Computed damage contribution from this scaling modifier.
    """
    if not unit or unit.strip() == "":
        # Flat damage — the value IS the damage
        return value

    unit_clean = unit.strip()
    if champion_stats is None:
        champion_stats = {}
    if target_stats is None:
        target_stats = {}

    # Target stats take priority over champion stats on shared keys —
    # the same rule the old ``{**champion, **target}`` merge expressed,
    # without building a merged dict per modifier on the hot parse path.

    # Simple unit lookup
    simple = _SIMPLE_UNITS.get(unit_clean)
    if simple is not None:
        stat_key, divisor = simple
        if stat_key in target_stats:
            stat_value = target_stats[stat_key]
        else:
            stat_value = scaling_input(champion_stats, stat_key)
        return (value / divisor) * stat_value

    # Per-100 scaling
    per_100_key = _PER_100_UNITS.get(unit_clean)
    if per_100_key is not None:
        if per_100_key in target_stats:
            stat_value = target_stats[per_100_key]
        else:
            stat_value = scaling_input(champion_stats, per_100_key)
        return (value / 100.0) * (stat_value / 100.0) * 100.0
        # e.g. 2% per 100 AP with 300 AP = 2 * 3 = 6% = 6.0 (returned as flat)

    # Pure percentage (no stat scaling) — used for non-damage attributes
    if unit_clean == "%":
        return value  # Return as-is; caller decides meaning

    # Complex compound units with embedded formulas — rare enough that the
    # merged lookup dict is built only here.
    # e.g. "% (+ 1.5% per 100 AP) of target's maximum health"
    compound = _parse_compound_unit(
        unit_clean, value, {**champion_stats, **target_stats}
    )
    if compound is not None:
        return compound

    # Unrecognized unit — return 0 to avoid incorrect damage
    return 0.0


def _parse_compound_unit(
    unit: str,
    value: float,
    stats: dict[str, float],
) -> float | None:
    """Parse complex compound unit strings.

    Handles patterns like:
    ``"% (+ 1.5% per 100 AP) of target's maximum health"``
    ``"% (+ 0.2% per 100 bonus armor) (+ 0.2% per 100 bonus magic resistance)
      of target's maximum health"``

    Returns:
        Computed damage, or None if the pattern is not recognized.
    """
    # Check for "of [the] target's [current/maximum/missing] health" suffix
    target_hp_match = re.search(
        r"of\s+(?:the\s+)?target's\s+(maximum|current|missing)\s+health",
        unit,
        re.IGNORECASE,
    )
    if not target_hp_match:
        return None

    hp_type = target_hp_match.group(1).lower()
    # Map to the stat key convention used in target_stats
    hp_type_key = {"maximum": "max", "current": "current", "missing": "missing"}
    hp_key = f"target_{hp_type_key.get(hp_type, hp_type)}_health"
    target_hp = scaling_input(stats, hp_key)

    # Base percentage is the value itself
    total_percent = value

    # Find embedded "(+ N% per 100 STAT)" bonuses
    per_100_matches = re.findall(
        r"\+\s*(\d+(?:\.\d+)?)%\s+per\s+100\s+((?:bonus\s+)?(?:AP|AD|armor|"
        r"magic\s+resistance|health|mana))",
        unit,
        re.IGNORECASE,
    )
    for bonus_pct, stat_name in per_100_matches:
        bonus = float(bonus_pct)
        stat_key = _normalize_per_100_stat(stat_name)
        stat_val = scaling_input(stats, stat_key)
        total_percent += bonus * (stat_val / 100.0)

    return (total_percent / 100.0) * target_hp


def _normalize_per_100_stat(stat_name: str) -> str:
    """Normalize a stat name from a compound unit to a stats dict key."""
    name = stat_name.strip().lower()
    mapping = {
        "ap": "ability_power",
        "ad": "attack_damage",
        "bonus ad": "bonus_attack_damage",
        "armor": "armor",
        "bonus armor": "armor",
        "magic resistance": "magic_resistance",
        "bonus magic resistance": "magic_resistance",
        "health": "health",
        "bonus health": "bonus_health",
        "mana": "max_mana",
    }
    return mapping.get(name, name)


def is_flat_unit(unit: str) -> bool:
    """Check if a unit string represents flat (non-scaling) damage."""
    return not unit or unit.strip() == ""


def is_supported_scaling_unit(unit: str) -> bool:
    """Whether the generic resolver has an explicit rule for ``unit``.

    This is a certification predicate, not a damage calculation. It lets the
    public coverage report fail closed when cached Wiki data introduces a
    scaling expression that would otherwise resolve to zero.
    """
    unit_clean = (unit or "").strip()
    if not unit_clean or unit_clean == "%":
        return True
    if unit_clean in _SIMPLE_UNITS or unit_clean in _PER_100_UNITS:
        return True
    probe_stats = {
        "ability_power": 100.0,
        "attack_damage": 100.0,
        "bonus_attack_damage": 100.0,
        "armor": 100.0,
        "magic_resistance": 100.0,
        "bonus_health": 100.0,
        "health": 100.0,
        "max_mana": 100.0,
        "target_max_health": 100.0,
        "target_current_health": 100.0,
        "target_missing_health": 100.0,
    }
    return _parse_compound_unit(unit_clean, 1.0, probe_stats) is not None
