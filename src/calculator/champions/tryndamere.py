"""Tryndamere — E5-1 corrected slot map for the archetype engine.

Why each slot is non-generic:

- Q (Bloodlust) is a heal, NOT damage: the wiki leveling rows for Q are
  "Maximum Bonus Attack Damage", "Bonus Attack Damage per 1% missing
  health", "Minimum Heal", "Heal Per 1 Fury", and "Maximum Heal" — no
  enemy-damage attribute exists.  The previous packet emitted a spurious
  5 / 10 / 15 / 20 / 25 magic-damage row; it is removed.  The heal itself
  is authored by ``healing.py`` from the Q cast timeline using the same
  cache ("Minimum Heal" = 30 / 40 / 50 / 60 / 70 + 30% AP).
- E (Spinning Slash) is a plain "Physical Damage" read (80 / 120 / 160 /
  200 / 240 + 100% bonus AD + 80% AP).
- P (Battle Fury), W (Mocking Shout), and R (Undying Rage) deal no enemy
  damage and are explicit no-damage slots.

All numeric values are read from the champion JSON data; nothing is
hardcoded.
"""

from typing import Any

from .engine import SlotCtx, build_parser
from .source_receipts import load_champion_sources
from .slotlib import simple_damage


def _no_damage(slot: str, reason: str):
    """Emit an explicit zero-damage entry for a non-damaging slot."""

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        ability = ctx.ability()
        if ability is None:
            return None
        return {
            "name": ability.get("name", f"Ability {slot}"),
            "rank": ctx.rank_for(),
            "cooldown": 0.0,
            "damage_type": "magic",
            "total_raw": 0.0,
            "parts": (),
            "detail": reason,
        }

    parse.phase = "damage"
    return parse


ASSUMPTIONS = [
    "Q (Bloodlust) is a heal; no enemy-damage leveling row exists for it "
    "(Maximum Bonus Attack Damage / Minimum Heal are state/heal terms). "
    "The heal is authored by healing.py from the Q cast timeline.",
    "E (Spinning Slash) prices one enemy-champion hit.",
    "P, W, and R deal no enemy damage and are explicit no-damage slots.",
]

SOURCES = list(load_champion_sources("Tryndamere"))

SLOTS = {
    "P": _no_damage(
        "P",
        "Battle Fury is a fury/AD-while-missing state passive; no enemy damage.",
    ),
    "Q": _no_damage(
        "Q",
        "Bloodlust is a heal (Minimum Heal leveling row); no enemy damage.",
    ),
    "W": _no_damage(
        "W",
        "Mocking Shout reduces enemy AD and slows; no enemy damage.",
    ),
    "E": simple_damage(attr="Physical Damage", dmg_type="physical"),
    "R": _no_damage(
        "R",
        "Undying Rage is a minimum-health/fury ultimate; no enemy damage.",
    ),
}

MODULE_COVERAGE = {
    "P": "no_damage",
    "Q": "no_damage",
    "W": "no_damage",
    "E": "modeled",
    "R": "no_damage",
}

OPTIONS: list[dict[str, Any]] = []

parse_abilities = build_parser(SLOTS, "Tryndamere")
REVIEW_STATUS = "reviewed_module"
