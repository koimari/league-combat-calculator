"""Default and per-champion skill leveling orders.

The skill order determines which ability gets leveled at each champion
level (1-18). R is always taken at 6, 11, 16. The remaining 15 levels
are distributed among Q, W, E.

Format: list of 18 strings, one per champion level.
"""

# Each table row is a level bracket (1-6 / 7-12 / 13-18) — keep the
# 6-per-line layout black would otherwise explode.
# fmt: off

# Default: Q max first, then W, then E. R at 6/11/16.
DEFAULT_SKILL_ORDER: list[str] = [
    "Q", "W", "E", "Q", "Q", "R",
    "Q", "W", "Q", "W", "R", "W",
    "W", "E", "E", "R", "E", "E",
]

# Per-champion overrides. Only champions with non-standard skill orders
# need entries here. The key is the champion display name.
# Common patterns:
#   Q max: Q>W>E (default)
#   W max: W>Q>E
#   E max: E>Q>W
_SKILL_ORDERS: dict[str, list[str]] = {
    # ── W max first ──
    "Singed": [
        "Q", "W", "E", "Q", "Q", "R",
        "Q", "E", "Q", "E", "R", "E",
        "E", "W", "W", "R", "W", "W",
    ],
    # ── W max first ──
    "Amumu": [
        "Q", "W", "E", "W", "W", "R",
        "W", "Q", "W", "Q", "R", "Q",
        "Q", "E", "E", "R", "E", "E",
    ],
    # ── Q max first, then E, then W ──
    "Dr. Mundo": [
        "Q", "W", "E", "Q", "Q", "R",
        "Q", "E", "Q", "E", "R", "E",
        "E", "W", "W", "R", "W", "W",
    ],
    # ── E max second ──
    "Anivia": [
        "Q", "E", "W", "Q", "Q", "R",
        "Q", "E", "Q", "E", "R", "E",
        "E", "W", "W", "R", "W", "W",
    ],
    "Aurelion Sol": [
        "Q", "W", "E", "Q", "Q", "R",
        "Q", "E", "Q", "E", "R", "E",
        "E", "W", "W", "R", "W", "W",
    ],
    "Aurora": [
        "Q", "E", "W", "Q", "Q", "R",
        "Q", "E", "Q", "E", "R", "E",
        "E", "W", "W", "R", "W", "W",
    ],
    "Camille": [
        "Q", "E", "W", "Q", "Q", "R",
        "Q", "E", "Q", "E", "R", "E",
        "E", "W", "W", "R", "W", "W",
    ],
    "Corki": [
        "Q", "E", "W", "Q", "Q", "R",
        "Q", "E", "Q", "E", "R", "E",
        "E", "W", "W", "R", "W", "W",
    ],
    "Jarvan IV": [
        "Q", "E", "W", "Q", "Q", "R",
        "Q", "E", "Q", "E", "R", "E",
        "E", "W", "W", "R", "W", "W",
    ],
    "Bel'Veth": [
        "Q", "E", "W", "Q", "Q", "R",
        "Q", "E", "Q", "E", "R", "E",
        "E", "W", "W", "R", "W", "W",
    ],
    # ── E max first (Twin Fang is the core spam spell), Q second ──
    "Cassiopeia": [
        "Q", "E", "W", "E", "E", "R",
        "E", "Q", "E", "Q", "R", "Q",
        "Q", "W", "W", "R", "W", "W",
    ],
    # ── W start, W max first (soldiers are the kit; standard since V13.7) ──
    "Azir": [
        "W", "Q", "E", "W", "W", "R",
        "W", "Q", "W", "Q", "R", "Q",
        "Q", "E", "E", "R", "E", "E",
    ],
    # ── W max first (Pillar of Flame is the damage ability) ──
    "Brand": [
        "Q", "W", "E", "W", "W", "R",
        "W", "Q", "W", "Q", "R", "Q",
        "Q", "E", "E", "R", "E", "E",
    ],
    # ── W max first (Blood Frenzy is the steroid; standard jungle order) ──
    "Briar": [
        "Q", "W", "E", "W", "W", "R",
        "W", "Q", "W", "Q", "R", "Q",
        "Q", "E", "E", "R", "E", "E",
    ],
    # ── W max first (standard pattern) ──
    "Kog'Maw": [
        "Q", "W", "E", "W", "W", "R",
        "W", "Q", "W", "Q", "R", "Q",
        "Q", "E", "E", "R", "E", "E",
    ],
    # ── Q max first, then W ──
    "Vayne": [
        "Q", "W", "E", "Q", "Q", "R",
        "Q", "W", "Q", "W", "R", "W",
        "W", "E", "E", "R", "E", "E",
    ],
}


def get_skill_order(champion_name: str) -> list[str]:
    """Return the skill leveling order for a champion.

    Args:
        champion_name: Display name of the champion.

    Returns:
        List of 18 ability keys (Q/W/E/R) representing what is leveled
        at each champion level.
    """
    return _SKILL_ORDERS.get(champion_name, DEFAULT_SKILL_ORDER)


def get_ability_rank(
    ability_key: str,
    champion_level: int,
    champion_name: str = "",
) -> int:
    """Calculate ability rank at a given champion level.

    Args:
        ability_key: One of ``"Q"``, ``"W"``, ``"E"``, ``"R"``.
        champion_level: Champion level (1-18).
        champion_name: Champion name for skill order lookup.

    Returns:
        Ability rank (1-5 for basic abilities, 1-3 for R).
    """
    order = get_skill_order(champion_name)
    rank = 0
    for i in range(min(champion_level, len(order))):
        if order[i] == ability_key:
            rank += 1
    return rank
# fmt: on
