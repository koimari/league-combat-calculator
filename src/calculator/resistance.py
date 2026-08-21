"""Resistance and penetration calculations for League of Legends damage.

These pure functions compute post-mitigation damage and effective
resistances. They are used by the fight engine (damage.py), champion
ability modules, and item effect calculations.
"""


def apply_resistance(raw_damage: float, resistance: float) -> float:
    """Post-mitigation damage: ``raw * 100/(100 + R)``, extended below zero as
    ``raw * (2 - 100/(100 - R))`` so negative resistance amplifies, saturating at 2x.
    """
    if resistance >= 0:
        return raw_damage * (100.0 / (100.0 + resistance))
    return raw_damage * (2.0 - 100.0 / (100.0 - resistance))


def reduce_resistance(
    resistance: float,
    reduction_percent: float = 0.0,
    reduction_flat: float = 0.0,
) -> float:
    """Reduce a resistance: flat first, then percent of what remains. Reduction
    has no floor, and the percent share only bites positive resistance, so it
    never protects an already-negative target.
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
    """Effective magic resistance after penetration: percent first, then flat.

    Penetration floors at 0 and leaves an already-negative MR untouched.
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
    """Effective armor after penetration and lethality: percent first, then flat.

    Penetration floors at 0, so lethality above the target's armor is wasted
    rather than turned into damage-amplifying negative armor. Only reduction
    effects take armor negative, and they apply before this function.

    Percent BONUS penetration (the Last Whisper family, K'Sante's All Out) bites
    only the bonus share: ``base*(1 - p) + bonus*(1 - p)*(1 - p_bonus)``. A
    target declaring total armor with no split reads as total penetration.
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
