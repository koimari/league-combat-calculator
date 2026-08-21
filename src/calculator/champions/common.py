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
    """Public scalar convenience for base + ratio × stat damage."""
    return base_damage + (scaling_ratio * scaling_stat)
