"""Tryndamere: slot map for the archetype engine.

Q (Bloodlust) is a heal, NOT damage: its cached leveling rows are Maximum Bonus
Attack Damage, Bonus Attack Damage per 1% missing health, Minimum Heal, Heal Per
1 Fury and Maximum Heal, with no enemy-damage attribute anywhere.  The heal is
authored by the healing rule from the Q cast timeline off the same cache.
E (Spinning Slash) is a plain "Physical Damage" read.
P (Battle Fury), W (Mocking Shout) and R (Undying Rage) deal no enemy damage and
are explicit no-damage slots.
"""

from typing import Any

from .. import healing_helpers as _healing
from .contract_vocabulary import coverage
from .engine import build_parser
from .healing_contract import SelfHealCtx, self_healing_rule
from .module_helpers import no_damage_parser
from .slot_cc import CC_PER_PART
from .slot_extract import extract_named
from .slotlib import simple_damage
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


def derive_self_healing(ctx: SelfHealCtx) -> list[dict[str, Any]]:
    """Resolve Tryndamere self-healing events from its authored packet."""
    healing = []
    q_rank = _healing.parsed_rank(ctx.ability_damages, "Q")
    amount = extract_named(
        _healing.ability_json(ctx.champion_data, "Q"),
        "Minimum Heal",
        q_rank,
        ctx.champion_stats,
    )
    healing.extend(
        {
            "time": cast_time,
            "amount": amount,
            "source": "Bloodlust",
            "kind": "champion_ability",
            "actor_wide": True,
        }
        for cast_time in _healing.cast_slot_times(ctx.cast_timeline, "Q")
    )
    return healing


SELF_HEALING_RULE = self_healing_rule("Tryndamere")(derive_self_healing)
