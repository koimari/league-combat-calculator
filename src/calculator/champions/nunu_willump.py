"""Nunu & Willump: full-entry-reviewed packet module.

Q (Consume) prices the "Champion Magic Damage" row, not the minion and monster
"Non-Champion True Damage" row beside it, which is the wrong basis for a
champion-combat calculator.  Its champion self-heal, empowered by half below
half maximum health, is authored by the healing rule.
E (Snowball Barrage) is the three-snowball volley, and W and R damage are
modeled.
P (Call of the Freljord) grants bonus attack speed and movement speed whenever
the duo damage an enemy champion, successive triggers extending the 4-second
window, so the attack-speed half rides a BUFF-phase ``stat_buff`` the fight's
own damage holds up.  Its movement speed has no key, and Willump's cone cleave
lands on secondary targets a duel does not have.  P is therefore modeled here
rather than the packet's zero-damage row.
"""

from typing import Any

from ..binary_roots import data_value, spell_object
from ..damage_event_row import event_time as _row_time
from ..healing_helpers import HealAnchor, ability_json, parsed_rank, trigger_fields
from .engine import BUFF, SlotCtx
from .healing_contract import SelfHealCtx, self_healing_rule
from .module_helpers import ability_slot, named_damage
from .packet_module import build_packet_module
from .slot_entries import STEROID_ZERO, damage_entry
from .slot_extract import ability_name, extract_named

# Call of the Freljord's grants are binary DataValues expressed as fractions;
# the module's stat-buff/detail contract uses percentage points.
_NUNU_PASSIVE_SPELL = spell_object("Nunu", "NunuPassive")
_P_BONUS_ATTACK_SPEED = data_value(_NUNU_PASSIVE_SPELL, "ASIncrease") * 100.0
_P_BONUS_MOVEMENT_SPEED = data_value(_NUNU_PASSIVE_SPELL, "MSIncrease") * 100.0


@ability_slot("P")
def _call_of_the_freljord(
    ctx: SlotCtx, ability: dict[str, Any]
) -> dict[str, Any] | None:
    """P: the 20% attack speed the duo's own damage keeps refreshed."""
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


# Q: Champion Magic Damage (60-220 + 65% AP + 5% bonus health).
_consume = named_damage(
    "Champion Magic Damage",
    "magic",
    # One bite, at the cast boundary — the claim that carries
    # MODULE_CC's reviewed answer for Q into the event ledger.
    event_order_certified="single_hit",
    detail="Champion Magic Damage basis (60-220 + 65% AP + 5% bonus "
    "health); the Non-Champion True Damage row (400-1200) is the "
    "minion/monster branch and is not priced in a champion duel.",
)


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
MODULE_CC = {"Q": "none", "W": "immobilize", "E": "slow", "R": "slow", "P": "none"}

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

ASSUMPTIONS = [
    *list(ASSUMPTIONS),
    "Q (Consume) prices the champion branch, 60 to 220 + 65% AP + 5% bonus health.",
    "The Non-Champion True Damage row of 400 to 1200 applies to minions and monsters "
    "only.",
    "Q's champion self-heal is 39 to 111 + 54% AP + 6% bonus health, +50% below half "
    "health.",
    "The healing rule re-prices the below-half empowerment at the heal timestamp.",
    "P (Call of the Freljord) grants 20% bonus attack speed (cached P prose; the JSON "
    "has no row).",
    "Its 4s window is held for the fight: every damaging cast and auto in the "
    "rotation extends it.",
    "The per-enemy re-trigger cooldown the cache calls 'a time' carries no number.",
    "The 10% move speed, the ally's copy and Willump's 30% AD cone cleave are named, "
    "not priced.",
]

# No MODULE_COVERAGE: every one of the five slots emits a priced row now
# (P's own attack-speed steroid replaces the packet's zero-damage row).


def derive_self_healing(ctx: SelfHealCtx) -> list[dict[str, Any]]:
    """Price Consume's champion heal, re-read at the heal's own timestamp.

    "Willump takes a bite ... healing himself" for the sourced Base
    Champion Heal, "increased by 50% if Willump is below 50% of his
    maximum health" — a live health test, so the amount is a formula the
    participant ledger evaluates when the heal lands rather than a number
    fixed at parse time.
    """
    base = extract_named(
        ability_json(ctx.champion_data, "Q"),
        "Base Champion Heal",
        parsed_rank(ctx.ability_damages, "Q"),
        ctx.champion_stats,
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

    return [
        {
            "time": _row_time(payment.event),
            "amount": 0.0,
            "amount_formula": consume_heal,
            "source": "Consume",
            "kind": "champion_ability",
            **trigger_fields(payment.event),
        }
        for payment in ctx.payments(HealAnchor.CAST, "Q")
    ]


SELF_HEALING_RULE = self_healing_rule("Nunu & Willump")(derive_self_healing)
