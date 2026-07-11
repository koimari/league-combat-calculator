"""Champion-agnostic damage math shared with the wider calculator.

The champion parse layer itself lives in ``engine.py`` (slot evaluation)
and ``slotlib.py`` (archetypes + JSON extraction core); this module only
keeps the two formula helpers that non-champion code (``damage.py``,
``calculator.__init__``) imports.
"""


def calculate_ability_damage(
    base_damage: float,
    scaling_ratio: float,
    scaling_stat: float,
) -> float:
    """Calculate raw ability damage before resistances.

    Formula: base_damage + (scaling_ratio * scaling_stat)

    Args:
        base_damage: Base damage at current rank.
        scaling_ratio: Scaling ratio as a decimal (e.g., 0.5 for 50%).
        scaling_stat: The stat value to scale with (e.g., total AP).

    Returns:
        Total raw ability damage.
    """
    return base_damage + (scaling_ratio * scaling_stat)


def effective_cooldown(base_cooldown: float, ability_haste: float) -> float:
    """Calculate effective cooldown after ability haste.

    Formula: base_cd * 100 / (100 + ability_haste)

    Args:
        base_cooldown: Base cooldown in seconds.
        ability_haste: Total ability haste.

    Returns:
        Effective cooldown in seconds.
    """
    if base_cooldown <= 0:
        return 0.0
    return base_cooldown * (100.0 / (100.0 + ability_haste))
