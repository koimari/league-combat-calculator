"""The game's own stat formulas, in the form the wiki states them."""

# Level cap — 20 is top-lane-only as of this season, so this is
# season-volatile. Single source of truth: the API guards and the UI
# slider (via the index template) both read this constant.
MAX_LEVEL = 20


def growth_multiplier(level: int) -> float:
    """The growth formula's progression term, ``0.7025 + 0.0175 * (level - 1)``."""
    if level < 1 or level > MAX_LEVEL:
        raise ValueError(f"Level must be between 1 and {MAX_LEVEL}, got {level}")
    return 0.7025 + 0.0175 * (level - 1)


def growth_stat(base: float, growth: float, level: int) -> float:
    """``base + growth * (level - 1) * (0.7025 + 0.0175 * (level - 1))``."""
    return base + growth * (level - 1) * growth_multiplier(level)


# The game clamps a unit's TOTAL attack speed to 3.003 (one basic attack
# per 0.333s); the floor is 0.2. See
# https://wiki.leagueoflegends.com/en-us/Attack_speed
# NOTE: ``calculate_attack_speed`` deliberately does NOT clamp — applying
# the cap fight-wide would move every attack-speed champion's numbers at
# once. Today only a burst that is *designed* to reach the cap reads it
# (Jayce's Hyper Charge: 360% on his 0.658 ratio lands at 3.027, which is
# why the in-game tooltip reads "maximum Attack Speed" and not a percent).
ATTACK_SPEED_CAP = 3.003


# base AS and the AS ratio are separate per-champion values.
# https://wiki.leagueoflegends.com/en-us/Attack_speed
def calculate_attack_speed(
    base_attack_speed: float,
    attack_speed_ratio: float,
    bonus_percent: float,
) -> float:
    """Attacks per second: ``base_AS + AS_ratio * (bonus_percent / 100)``."""
    return base_attack_speed + attack_speed_ratio * (bonus_percent / 100.0)


def resolve_move_speed(flat_total: float, percent_total: float) -> float:
    """The one fold from movement-speed components to a displayed number."""
    return apply_movement_speed_soft_caps(flat_total * (1.0 + percent_total / 100.0))


def apply_movement_speed_soft_caps(raw_speed: float) -> float:
    """Apply League's displayed movement-speed soft caps."""
    if raw_speed > 490:
        return raw_speed * 0.5 + 230
    if raw_speed > 415:
        return raw_speed * 0.8 + 83
    if raw_speed < 220:
        return raw_speed * 0.5 + 110
    return raw_speed


def effective_cooldown(base_cooldown: float, ability_haste: float) -> float:
    """Effective cooldown in seconds: ``base_cd * 100 / (100 + ability_haste)``."""
    if base_cooldown <= 0:
        return 0.0
    return base_cooldown * (100.0 / (100.0 + ability_haste))
