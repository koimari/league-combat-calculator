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

# The three shapes 13 of the overrides share. Each is one maxing order; the
# first two differ only in the level-2 pick.
_Q_MAX_THEN_E: list[str] = [
    "Q", "W", "E", "Q", "Q", "R",
    "Q", "E", "Q", "E", "R", "E",
    "E", "W", "W", "R", "W", "W",
]
_Q_MAX_THEN_E_E_AT_TWO: list[str] = [
    "Q", "E", "W", "Q", "Q", "R",
    "Q", "E", "Q", "E", "R", "E",
    "E", "W", "W", "R", "W", "W",
]
_W_MAX_THEN_Q: list[str] = [
    "Q", "W", "E", "W", "W", "R",
    "W", "Q", "W", "Q", "R", "Q",
    "Q", "E", "E", "R", "E", "E",
]

# Per-champion overrides. Only champions with non-standard skill orders
# need entries here. The key is the champion display name.
# Common patterns:
#   Q max: Q>W>E (default)
#   W max: W>Q>E
#   E max: E>Q>W
_SKILL_ORDERS: dict[str, list[str]] = {
    "Singed": _Q_MAX_THEN_E,
    "Dr. Mundo": _Q_MAX_THEN_E,
    "Aurelion Sol": _Q_MAX_THEN_E,
    "Anivia": _Q_MAX_THEN_E_E_AT_TWO,
    "Aurora": _Q_MAX_THEN_E_E_AT_TWO,
    "Camille": _Q_MAX_THEN_E_E_AT_TWO,
    "Corki": _Q_MAX_THEN_E_E_AT_TWO,
    "Jarvan IV": _Q_MAX_THEN_E_E_AT_TWO,
    "Bel'Veth": _Q_MAX_THEN_E_E_AT_TWO,
    # ── Pillar of Flame, Blood Frenzy, Bio-Arcane Barrage, Despair ──
    "Amumu": _W_MAX_THEN_Q,
    "Brand": _W_MAX_THEN_Q,
    "Briar": _W_MAX_THEN_Q,
    "Kog'Maw": _W_MAX_THEN_Q,
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
    # ── NO "R" ON PURPOSE — do not "fix" this by adding one ──
    # Jayce starts with Transform at rank 1 and can never level it, so
    # all 18 skill points go to Q/W/E, which therefore have SIX ranks
    # each (the JSON values arrays confirm: 6 entries, not 5). An "R"
    # here would both steal a basic-ability rank and make
    # get_ability_rank("R", ...) return a rank Jayce cannot have.
    # ``jayce.py``'s R slot ignores rank entirely and keys off level.
    # Q max first (level 8), then W (13), then E (18).
    "Jayce": [
        "Q", "W", "E", "Q", "Q", "Q",
        "Q", "Q", "W", "W", "W", "W",
        "W", "E", "E", "E", "E", "E",
    ],
}


def get_ability_rank(
    ability_key: str,
    champion_level: int,
    champion_name: str = "",
) -> int:
    """*ability_key*'s rank at *champion_level*: 1-5 basic, 1-3 for R."""
    order = _SKILL_ORDERS.get(champion_name, DEFAULT_SKILL_ORDER)
    rank = 0
    for i in range(min(champion_level, len(order))):
        if order[i] == ability_key:
            rank += 1
    return rank
# fmt: on
