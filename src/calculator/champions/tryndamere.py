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

from .. import healing_helpers as _healing
from .engine import CC_PER_PART, build_parser
from .healing_contract import self_healing_rule
from .module_contract import coverage
from .module_helpers import no_damage_parser
from .slotlib import extract_named, simple_damage
from .source_receipts import load_champion_sources

ASSUMPTIONS = [
    "Q (Bloodlust) is a heal; no enemy-damage leveling row exists for it "
    "(Maximum Bonus Attack Damage / Minimum Heal are state/heal terms). "
    "The heal is authored by healing.py from the Q cast timeline.",
    "E (Spinning Slash) prices one enemy-champion hit.",
    "P, W, and R deal no enemy damage and are explicit no-damage slots.",
]

SOURCES = load_champion_sources("Tryndamere")

SLOTS = {
    "P": no_damage_parser(
        "P",
        "Battle Fury is a fury/AD-while-missing state passive; no enemy damage.",
    ),
    "Q": no_damage_parser(
        "Q",
        "Bloodlust is a heal (Minimum Heal leveling row); no enemy damage.",
    ),
    "W": no_damage_parser(
        "W",
        "Mocking Shout reduces enemy AD and slows; no enemy damage.",
    ),
    # One dash, one blow ("dealing physical damage to enemies hit").
    "E": simple_damage(
        attr="Physical Damage",
        dmg_type="physical",
        event_order_certified="single_hit",
    ),
    "R": no_damage_parser(
        "R",
        "Undying Rage is a minimum-health/fury ultimate; no enemy damage.",
    ),
}

MODULE_COVERAGE = coverage(no_damage="PQWR")

OPTIONS: list[dict[str, Any]] = []

# Reviewed crowd control, read from the cached kit: E (Spinning Slash)
# "dashes to the target location, dealing physical damage to enemies hit"
# and applies no control.  It is the kit's only damaging slot — W (Mocking
# Shout) is where the slow lives ("they become slowed while facing in the
# opposite direction of Tryndamere"), and it deals no damage, so no part
# can carry that answer.
MODULE_CC = {"E": "none", "P": "none", "Q": "none", "W": CC_PER_PART, "R": "none"}

parse_abilities = build_parser(SLOTS, "Tryndamere", cc_kinds=MODULE_CC)


# pylint: disable=too-many-arguments,too-many-locals,too-many-positional-arguments,unused-argument
def derive_self_healing(
    champion_data: dict[str, Any],
    champion_stats: dict[str, float],
    ability_damages: dict[str, dict[str, Any]],
    damage_events: list[dict[str, Any]],
    cast_timeline: list[dict[str, Any]] | None = None,
    fight_duration_seconds: float | None = None,
) -> list[dict[str, Any]]:
    """Resolve Tryndamere self-healing events from its authored packet."""
    healing = []
    q_rank = _healing.parsed_rank(ability_damages, "Q")
    amount = extract_named(
        _healing.ability_json(champion_data, "Q"),
        "Minimum Heal",
        q_rank,
        champion_stats,
    )
    healing.extend(
        {
            "time": cast_time,
            "amount": amount,
            "source": "Bloodlust",
            "kind": "champion_ability",
            "actor_wide": True,
        }
        for cast_time in _healing.cast_slot_times(cast_timeline, "Q")
    )
    return healing


SELF_HEALING_RULE = self_healing_rule("Tryndamere")(derive_self_healing)
