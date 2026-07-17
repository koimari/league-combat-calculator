"""Package-level compatibility helper for the public calculator API.

The champion parse layer itself lives in ``engine.py`` (slot evaluation)
and ``slotlib.py`` (archetypes + JSON extraction core); this module only
keeps the scalar helper that ``calculator.__init__`` re-exports. The
cooldown formula lives in ``damage.py`` (its only consumer).
"""


def calculate_ability_damage(
    base_damage: float,
    scaling_ratio: float,
    scaling_stat: float,
) -> float:
    """Public scalar convenience for base + ratio × stat damage.

    This package-level compatibility helper is intentionally separate from
    the champion JSON path, which resolves arbitrary modifier units through
    ``slotlib.sum_modifiers`` and ``scaling.resolve_scaling``.

    Formula: base_damage + (scaling_ratio * scaling_stat)

    Args:
        base_damage: Base damage at current rank.
        scaling_ratio: Scaling ratio as a decimal (e.g., 0.5 for 50%).
        scaling_stat: The stat value to scale with (e.g., total AP).

    Returns:
        Total raw ability damage.
    """
    return base_damage + (scaling_ratio * scaling_stat)
