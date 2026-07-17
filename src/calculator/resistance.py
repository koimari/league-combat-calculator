"""Resistance and penetration calculations for League of Legends damage.

These pure functions compute post-mitigation damage and effective
resistances. They are used by the fight engine (damage.py), champion
ability modules, and item effect calculations.
"""


def apply_resistance(raw_damage: float, resistance: float) -> float:
    """Apply armor or magic resistance to reduce damage.

    Formula: damage * 100 / (100 + resistance)
    If resistance is negative, damage is amplified.

    Args:
        raw_damage: Pre-mitigation damage.
        resistance: Target's armor or magic resistance after penetration.

    Returns:
        Post-mitigation damage.
    """
    if resistance >= 0:
        return raw_damage * (100.0 / (100.0 + resistance))
    return raw_damage * (2.0 - 100.0 / (100.0 - resistance))


def apply_magic_penetration(
    target_magic_resistance: float,
    flat_penetration: float,
    percent_penetration: float,
) -> float:
    """Calculate effective magic resistance after penetration.

    Penetration order: percent first, then flat.

    Args:
        target_magic_resistance: Target's base magic resistance.
        flat_penetration: Flat magic penetration (e.g., from Sorcerer's Shoes).
        percent_penetration: Percent magic penetration as decimal (e.g., 0.40 for 40%).

    Returns:
        Effective magic resistance (minimum 0).
    """
    effective = target_magic_resistance * (1.0 - percent_penetration)
    effective = effective - flat_penetration
    return max(0.0, effective)


def apply_armor_penetration(
    target_armor: float,
    flat_penetration: float,
    percent_penetration: float,
) -> float:
    """Calculate effective armor after penetration and lethality.

    Penetration order: percent first, then flat (lethality). Penetration
    can never reduce armor below 0 — lethality exceeding the target's
    armor is wasted, not converted into negative (damage-amplifying)
    armor. Only armor *reduction* effects can take armor negative, and
    those apply before this function.

    Args:
        target_armor: Target's armor after any reduction effects.
        flat_penetration: Flat armor penetration (from lethality).
        percent_penetration: Percent armor penetration as decimal.

    Returns:
        Effective armor (minimum 0).
    """
    effective = target_armor * (1.0 - percent_penetration)
    effective = effective - flat_penetration
    return max(0.0, effective)
