"""Nunu & Willump — CP10.5 packet module with the E9-1 Q gap fix.

E9-1 closes the remaining audit gap: Q (Consume) was priced from the
minion/monster "Non-Champion True Damage" row (400-1200) — the wrong
basis for a champion-combat calculator.  This module prices the
"Champion Magic Damage" row (60-220 + 65% AP + 5% bonus health)
instead, and the champion Q self-heal (Base Champion Heal 39-111 +
54% AP + 6% bonus health, 50% empowered below half maximum health) is
authored by healing.py's HEALING_RULE_CHAMPIONS rule.

E2 already fixed E (Snowball Barrage) to the 3-snowball volley; W and R
damage are modeled.  P (Call of the Freljord) grants "20% bonus attack
speed and 10% bonus movement speed" whenever the duo damage an enemy
champion, and successive triggers extend the 4-second window — so the
attack-speed half rides a BUFF-phase ``stat_buff`` the fight's own
damage holds up.  Its movement speed has no stat_buff key, and Willump's
cone cleave lands on secondary targets a 1v1 does not have.  P is
therefore *modeled*, not the packet's zero-damage row: this module
replaces that slot.
"""

from typing import Any

from ..healing_helpers import (
    HealAnchor,
    ability_json,
    payments,
    parsed_rank,
    trigger_fields,
)
from .engine import BUFF, SlotCtx
from .healing_contract import self_healing_rule
from .packet_module import build_packet_module
from .slotlib import (
    STEROID_ZERO,
    ability_name,
    damage_entry,
    extract_cooldown,
    extract_named,
)

# HARDCODED: verify on patch updates — Call of the Freljord's grants are
# cached P prose only ("Gain 20% bonus attack speed and 10% bonus
# movement speed"); the JSON carries no leveling row for the passive.
_P_BONUS_ATTACK_SPEED = 20.0
_P_BONUS_MOVEMENT_SPEED = 10.0


def _call_of_the_freljord(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: the 20% attack speed the duo's own damage keeps refreshed."""
    ability = ctx.ability("P")
    if ability is None:
        return None
    entry = damage_entry(
        ability_name(ability),
        ctx.level,
        0.0,
        0.0,
        "physical",
        zero_policy=STEROID_ZERO,
    )
    entry["stat_buff"] = {"bonus_attack_speed": _P_BONUS_ATTACK_SPEED}
    entry["detail"] = (
        f"+{_P_BONUS_ATTACK_SPEED:g}% bonus attack speed, refreshed by "
        "every damaging cast and auto against the target; the "
        f"+{_P_BONUS_MOVEMENT_SPEED:g}% movement speed, the ally copy of "
        "the buff and Willump's secondary-target cleave have no channel"
    )
    return entry


_call_of_the_freljord.phase = BUFF


def _consume(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: Champion Magic Damage (60-220 + 65% AP + 5% bonus health)."""
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked

    damage = extract_named(
        ability, "Champion Magic Damage", rank, ctx.stats, ctx.target
    )
    entry = damage_entry(
        ability_name(ability),
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
    slot_parsers={
        "Q": _consume,
        "P": _call_of_the_freljord,
    },
    cc_kinds=MODULE_CC,
)

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
    "P (Call of the Freljord) grants 20% bonus attack speed (cached P "
    "prose; the JSON has no leveling row) and the fight engine applies "
    "it to the auto count.  The 4-second window is treated as held for "
    "the fight, because every damaging cast and auto in the modeled "
    "rotation extends it; the per-enemy re-trigger cooldown the cache "
    "calls 'a time' carries no number.  The 10% movement speed, the "
    "nearby ally's copy of the buff, and Willump's 30% AD cone cleave "
    "on secondary targets are named rather than priced.",
]

# No MODULE_COVERAGE: every one of the five slots emits a priced row now
# (P's own attack-speed steroid replaces the packet's zero-damage row).


# pylint: disable=too-many-arguments,too-many-positional-arguments
def derive_self_healing(
    champion_data: dict[str, Any],
    champion_stats: dict[str, float],
    ability_damages: dict[str, dict[str, Any]],
    damage_events: list[dict[str, Any]],
    cast_timeline: list[dict[str, Any]] | None = None,
    fight_duration_seconds: float | None = None,
) -> list[dict[str, Any]]:
    """Price Consume's champion heal, re-read at the heal's own timestamp.

    "Willump takes a bite ... healing himself" for the sourced Base
    Champion Heal, "increased by 50% if Willump is below 50% of his
    maximum health" — a live health test, so the amount is a formula the
    participant ledger evaluates when the heal lands rather than a number
    fixed at parse time.
    """
    del fight_duration_seconds
    base = extract_named(
        ability_json(champion_data, "Q"),
        "Base Champion Heal",
        parsed_rank(ability_damages, "Q"),
        champion_stats,
        {},
    )

    def consume_heal(
        current_health: float,
        maximum_health: float,
        base_amount: float = base,
    ) -> float:
        if maximum_health > 0.0 and current_health < maximum_health * 0.5:
            return base_amount * 1.5
        return base_amount

    healing = [
        {
            "time": float(payment.event.get("time", 0.0)),
            "amount": 0.0,
            "amount_formula": consume_heal,
            "source": "Consume",
            "kind": "champion_ability",
            **trigger_fields(payment.event),
        }
        for payment in payments(HealAnchor.CAST, "Q", damage_events, cast_timeline)
    ]
    return healing


SELF_HEALING_RULE = self_healing_rule("Nunu & Willump")(derive_self_healing)
