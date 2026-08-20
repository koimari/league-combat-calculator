"""Singed — CP10.7 full-entry-reviewed packet module.

R (Insanity Potion) is the one slot whose grants the engine can price:
"Singed empowers himself for 25 seconds with ability power, bonus armor,
bonus magic resistance, ..." — one cached "Bonus Stats" row (25/55/85)
that every one of those stats reads.  The ability power is fed into the
parse context as well as the fight engine, because Q's poison ticks and
E's fling both carry AP ratios, so the ultimate amplifies Singed's own
damage exactly as the census said it should.  Its movement speed and its
health/mana regeneration have no stat_buff key; the Grievous Wounds it
adds to Poison Trail is an enemy-healing effect the one-pair fight has
no target to apply to.

P (Noxious Slipstream) and W (Mega Adhesive) stay emitted zero rows:
stacking movement speed has no channel at all, and W's 50-70% slow is a
crowd-control magnitude the engine records only as a kind.
"""

from typing import Any

from .engine import BUFF, SlotCtx
from .module_helpers import buff_window_share
from .packet_module import build_packet_module
from .slotlib import (
    STEROID_ZERO,
    damage_entry,
    extract_cooldown,
    extract_value,
)

PACKET_SHA256 = "d6e04f1cd92d4f7ddd569c7ba4bb306cdd06c18e230c7ed2a57ef89ba45b3c9c"

# HARDCODED: verify on patch updates — Insanity Potion's window is cached
# R prose ("empowers himself for 25 seconds"); the magnitude is the
# JSON's one "Bonus Stats" row, shared by every stat the cast grants.
_R_DURATION_SECONDS = 25.0


def _insanity_potion(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: one Bonus Stats row granted as AP, armour and magic resist."""
    ability = ctx.ability("R")
    if ability is None:
        return None
    rank = ctx.rank_for("R")
    if rank < 1:
        return None

    granted = extract_value(ability, "Bonus Stats", rank)
    bonus = granted * buff_window_share(ctx, _R_DURATION_SECONDS)
    # BUFF phase: Q's poison ticks and E's fling both carry AP ratios and
    # parse after this slot, so the ultimate amplifies its own kit.
    ctx.stats["ability_power"] = ctx.stat("ability_power") + bonus
    entry = damage_entry(
        ability.get("name", "Insanity Potion"),
        rank,
        extract_cooldown(ability, rank),
        0.0,
        "magic",
        zero_policy=STEROID_ZERO,
    )
    entry["stat_buff"] = {
        "ability_power": bonus,
        "armor": bonus,
        "magic_resistance": bonus,
    }
    entry["detail"] = (
        f"+{granted:g} ability power, armour and magic resistance for "
        f"{_R_DURATION_SECONDS:g}s ({bonus:g} over the fight window); the "
        "cast's movement speed and health/mana regeneration have no "
        "stat_buff key, and its Grievous Wounds is an enemy-healing "
        "effect the one-pair fight cannot apply"
    )
    return entry


_insanity_potion.phase = BUFF


# Reviewed crowd control, read from the cached kit.  Q (Poison Trail)
# "inflicts poison to enemies within" and applies no control — the
# grounding slow belongs to W (Mega Adhesive), which deals no damage.  E
# (Fling) "flings the target enemy 550 units over himself over 0.693
# seconds, dealing magic damage" and its second clause calls that throw
# "the displacement"; the cached text names no narrower airborne kind, and
# the root it can follow with is conditional on landing in W's field.
MODULE_CC = {"Q": "none", "E": "airborne"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Singed",
    PACKET_SHA256,
    # The packet prices one poison tick per cast (base 5-15 at a 1s
    # cooldown), so the Q row is one part and one hit, same as E's fling.
    single_hit_slots=frozenset({"Q", "E"}),
    slot_parsers={
        "R": _insanity_potion,
    },
    cc_kinds=MODULE_CC,
)

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "R (Insanity Potion) grants the cached Bonus Stats row (25/55/85) as "
    "ability power, bonus armour and bonus magic resistance for the "
    "sourced 25 seconds, time-weighted by the share of the fight window "
    "the buff covers.  The ability power reaches the parse context "
    "before Q and E, so their AP ratios scale off it.  The same row's "
    "movement speed and health/mana regeneration have no stat_buff key, "
    "and the Grievous Wounds R adds to Poison Trail reduces enemy "
    "healing, which the one-pair fight does not model.",
    "P (Noxious Slipstream) is stacking movement speed and W (Mega "
    "Adhesive) a slow and a ground: both are emitted zero-damage rows, "
    "because the engine has no movement-speed axis and records crowd "
    "control as a kind without a magnitude.",
]

# P and W are emitted and grant nothing the engine prices.
MODULE_COVERAGE = {
    slot: ("no_damage" if slot in {"P", "W"} else "modeled") for slot in "PQWER"
}
