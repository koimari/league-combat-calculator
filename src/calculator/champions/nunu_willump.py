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
)
PACKET_SPEC = SLOTS.packet_spec
SLOTS["Q"] = _consume
parse_abilities = build_parser(SLOTS, "Nunu & Willump")

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
REVIEW_STATUS = "reviewed_module"
