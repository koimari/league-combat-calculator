"""Nunu & Willump — CP10.5 packet module with the E9-1 Q gap fix.

E9-1 closes the remaining audit gap: Q (Consume) was priced from the
minion/monster "Non-Champion True Damage" row (400-1200) — the wrong
basis for a champion-combat calculator.  This module prices the
"Champion Magic Damage" row (60-220 + 65% AP + 5% bonus health)
instead, and the champion Q self-heal (Base Champion Heal 39-111 +
54% AP + 6% bonus health, 50% empowered below half maximum health) is
authored by healing.py's HEALING_RULE_CHAMPIONS rule.

E2 already fixed E (Snowball Barrage) to the 3-snowball volley; W and R
damage are modeled; P (Call of the Freljord) is documented out_of_scope.
"""

from typing import Any

from .engine import SlotCtx, build_parser
from .packet_module import build_packet_module
from .slotlib import damage_entry, extract_cooldown, extract_named


def _consume(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: Champion Magic Damage (60-220 + 65% AP + 5% bonus health)."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    damage = extract_named(
        ability, "Champion Magic Damage", rank, ctx.stats, ctx.target
    )
    entry = damage_entry(
        ability.get("name", "Consume"),
        rank,
        extract_cooldown(ability, rank),
        damage,
        "magic",
        # One bite, at the cast boundary — the claim that carries
        # MODULE_CC's reviewed answer for Q into the event ledger.
        event_order_certified="single_hit",
    )
    entry["detail"] = (
        "Champion Magic Damage basis (60-220 + 65% AP + 5% bonus "
        "health); the Non-Champion True Damage row (400-1200) is the "
        "minion/monster branch and is not priced in a champion duel."
    )
    return entry


PACKET_SHA256 = "a41876fad651b2f3fca034c6a2c1ba7e0bdab4d8874850a2decd86e65b420920"

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Nunu & Willump",
    PACKET_SHA256,
    packet_tick_fixes={
        "Snowball Barrage": {
            "base": [15.0, 22.5, 30.0, 37.5, 45.0],
            "ratios": [
                {
                    "stat": "ap",
                    "values": [0.12, 0.12, 0.12, 0.12, 0.12],
                }
            ],
            "count": 3,
            "first_tick": 0.0,
            "tick_interval": 0.2,
        }
    },
    # The snowball "explodes upon hitting an enemy champion ... dealing
    # magic damage to nearby enemies" once, and Absolute Zero's recast is
    # one blizzard explosion — the boundary claim that carries MODULE_CC's
    # reviewed answers into the event ledger.  E already authors its own
    # three-snowball timing above, and Q certifies its own bite.
    single_hit_slots=frozenset({"W", "R"}),
)
PACKET_SPEC = SLOTS.packet_spec
SLOTS["Q"] = _consume

# Cached kit review.  Q against the fight's champion target "deals magic
# damage and the heal is reduced to 60%" — its stun-and-pull devour fires
# only when the bite would kill a minion or a small/medium monster, so
# nothing lands on a champion.  W's explosion is "knocking them up for
# 0.5 : 0.75 ... and subsequently stunning them": two immobilize kinds in
# one cast, which is what the un-narrowed "immobilize" states.  E prices
# the three-snowball volley, and "enemies hit 3 times are slowed for 1
# second" (the snowbound root belongs to the unpriced delayed detonation).
# R's explosion leaves "affected enemies ... slowed".  P is absent: Call of
# the Freljord is an attack-speed buff with no damage row of its own.
MODULE_CC = {"Q": "none", "W": "immobilize", "E": "slow", "R": "slow"}

parse_abilities = build_parser(SLOTS, "Nunu & Willump", cc_kinds=MODULE_CC)

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "Q (Consume) prices the champion branch — Champion Magic Damage "
    "60-220 + 65% AP + 5% bonus health — instead of the "
    "Non-Champion True Damage row (400-1200), which applies to "
    "minions and monsters only.",
    "Q's champion self-heal (Base Champion Heal 39-111 + 54% AP + 6% "
    "bonus health, increased by 50% below 50% maximum health) is "
    "authored by the HEALING_RULE_CHAMPIONS rule in healing.py; the "
    "below-half empowerment is a live health formula re-priced at the "
    "heal timestamp.",
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "E", "R"} else "out_of_scope")
    for slot in "PQWER"
}

from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Nunu & Willump")
