"""Resistance and penetration calculations for League of Legends damage.

These pure functions compute post-mitigation damage and effective
resistances. They are used by the fight engine (damage.py), champion
ability modules, and item effect calculations.
"""


def apply_resistance(raw_damage: float, resistance: float) -> float:
    """Apply armor or magic resistance to reduce damage.

    Formula: damage * 100 / (100 + resistance)

    Theorem (effective-health identity): for resistance R >= 0 the multiplier
    m(R) = 100/(100+R) satisfies the round-trip
        post = raw * m(R)  <=>  raw = post * (1 + R/100),
    so a target with H0 health and R resists survives exactly H0*(1 + R/100)
    raw damage; m is the sigmoid family m(R) = 1/(1 + R/100)
    (see arXiv:1409.6896). For R < 0 the game extends m piecewise as
    m(R) = 2 - 100/(100-R): continuous at 0, saturating at 2x as R -> -inf.

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


def reduce_resistance(
    resistance: float,
    reduction_percent: float = 0.0,
    reduction_flat: float = 0.0,
) -> float:
    """Reduce a resistance: flat first, then percent of what remains.

    REDUCTION is not penetration, and the difference is the whole reason
    both live here:

    - Order — the game applies flat reduction, then percent reduction,
      then percent penetration, then flat penetration. This function owns
      the first half, ``apply_*_penetration`` the second.
    - Floor — reduction has none. Negative resistance is a real state
      that amplifies damage (``apply_resistance``); only penetration
      floors at 0.

    The percent share only bites into positive resistance: scaling an
    already-negative value moves it back toward zero, which would make a
    reduction effect *protect* the target.

    Args:
        resistance: Target's current armor or magic resistance.
        reduction_percent: Percent reduction (e.g. ``32`` for 32%).
        reduction_flat: Flat reduction (e.g. Corki E's 12-20).

    Returns:
        The reduced resistance, which may be negative.
    """
    resistance -= reduction_flat
    if reduction_percent and resistance > 0:
        resistance *= 1.0 - reduction_percent / 100.0
    return resistance


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
        Effective magic resistance (minimum 0), or the target's own
        already-negative MR untouched.
    """
    if target_magic_resistance <= 0:
        # Already below zero from a REDUCTION effect (Corki E's flat
        # shred) — penetration neither deepens nor undoes that.
        return target_magic_resistance
    effective = target_magic_resistance * (1.0 - percent_penetration)
    effective = effective - flat_penetration
    return max(0.0, effective)


def apply_armor_penetration(
    target_armor: float,
    flat_penetration: float,
    percent_penetration: float,
    percent_bonus_penetration: float = 0.0,
    bonus_armor: float | None = None,
) -> float:
    """Calculate effective armor after penetration and lethality.

    Penetration order: percent first, then flat (lethality). Penetration
    can never reduce armor below 0 — lethality exceeding the target's
    armor is wasted, not converted into negative (damage-amplifying)
    armor. Only armor *reduction* effects can take armor negative, and
    those apply before this function.

    Percent BONUS armor penetration (the Last Whisper family and K'Sante's
    All Out) applies only to the target's BONUS armor: with
    ``percent_bonus_penetration > 0`` and a supplied ``bonus_armor`` split,
    ``effective = base*(1 - p) + bonus*(1 - p)*(1 - p_bonus)``.  When the
    split is unknown (legacy quick-scenario targets that only declare total
    armor), the total-pen reading is preserved.

    Args:
        target_armor: Target's armor after any reduction effects.
        flat_penetration: Flat armor penetration (from lethality).
        percent_penetration: Percent armor penetration as decimal.
        percent_bonus_penetration: Percent BONUS armor penetration as decimal.
        bonus_armor: Target's bonus armor (None = split unknown).

    Returns:
        Effective armor (minimum 0), or the target's own already-negative
        armor untouched.
    """
    if target_armor <= 0:
        # Already below zero from a REDUCTION effect (Corki E's flat
        # shred) — penetration neither deepens nor undoes that.
        return target_armor
    if percent_bonus_penetration > 0.0 and bonus_armor is not None:
        bonus = min(max(0.0, bonus_armor), target_armor)
        base = target_armor - bonus
        effective = base * (1.0 - percent_penetration) + bonus * (
            1.0 - percent_penetration
        ) * (1.0 - percent_bonus_penetration)
    else:
        effective = target_armor * (1.0 - percent_penetration)
    effective = effective - flat_penetration
    return max(0.0, effective)
