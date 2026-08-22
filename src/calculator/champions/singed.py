"""Singed — CP10.7 full-entry-reviewed packet module.

R (Insanity Potion) is the one slot whose grants the engine can price:
"Singed empowers himself for 25 seconds with ability power, bonus armor,
bonus magic resistance, bonus movement speed" — one cached "Bonus Stats"
row (25/55/85, corroborated by the game binary's InsanityPotion
``StatAmount`` DataValue) that every one of those stats reads.  The
ability power is fed into the parse context as well as the fight engine,
because Q's poison ticks and E's fling both carry AP ratios, so the
ultimate amplifies Singed's own damage exactly as the census said it
should.  The movement speed rides the same row into
``item_state_receipts``' ``total_move_speed`` input.  The health/mana
regeneration has no stat_buff key — this fixed-window burst engine
consumes no regen — and the Grievous Wounds R adds to Poison Trail is an
enemy-healing effect the one-pair fight has no target to apply to.

P (Noxious Slipstream) and W (Mega Adhesive) stay emitted zero rows.
Neither spell object carries a damage field at all — ``SingedP`` holds
only ``MSPercent``/``MSDuration``/``PerTargetCD``/``TriggerArea`` and
``MegaAdhesive`` only ``SlowPercent``/``WDuration``/``WRadius``/
``DelayExecute``/``Radius`` — so P's stacking movement speed has no
channel at all, and W's 50-70% slow and its ground are crowd control the
engine records only as a kind.
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
from .module_contract import coverage

PACKET_SHA256 = "d6e04f1cd92d4f7ddd569c7ba4bb306cdd06c18e230c7ed2a57ef89ba45b3c9c"

# HARDCODED: verify on patch updates — Insanity Potion's window is cached
# R prose ("empowers himself for 25 seconds"); the magnitude is the
# JSON's one "Bonus Stats" row, shared by every stat the cast grants.
_R_DURATION_SECONDS = 25.0

# The one "Bonus Stats" row grants the same flat number to four stats at
# once.  Three of them have a consumer here: ability power (Q's poison
# ticks and E's fling both carry AP ratios), armour and magic resistance
# (the self-resist keys every other steroid module publishes — Braum,
# Briar, Gnar, Graves, Jayce, Olaf, Shyvana), and movement speed (read
# back out of ``champion_stats`` for ``item_state_receipts``'
# ``total_move_speed`` input).  The row's health/mana regeneration has
# none, so it carries no key.
_INSANITY_POTION_STATS = (
    "ability_power",
    "armor",
    "magic_resistance",
    "move_speed",
)


def _insanity_potion(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: one Bonus Stats row granted as AP, resistances and move speed."""
    ranked = ctx.ranked("R")
    if ranked is None:
        return None
    ability, rank = ranked

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
    entry["stat_buff"] = {stat_key: bonus for stat_key in _INSANITY_POTION_STATS}
    entry["detail"] = (
        f"+{granted:g} ability power, armour, magic resistance and movement "
        f"speed for {_R_DURATION_SECONDS:g}s ({bonus:g} over the fight "
        "window); the same row's health/mana regeneration has no stat_buff "
        "key, and its Grievous Wounds is an enemy-healing effect the "
        "one-pair fight cannot apply"
    )
    return entry


_insanity_potion.phase = BUFF


# Reviewed crowd control, read from the cached kit.  Q (Poison Trail)
# "inflicts poison to enemies within" and applies no control — the
# grounding slow belongs to W (Mega Adhesive), which deals no damage.  E
# (Fling) "flings the target enemy 550 units over himself over 0.693
# seconds, dealing magic damage" and its second clause calls that throw
# "the displacement"; the cached text names no narrower airborne kind.
# The root E can follow with is a SECOND cached effect gated on a
# condition the engine does not track — "If the target lands on Mega
# Adhesive's area of effect after the displacement, they are rooted"
# (Root Duration 1/1.25/1.5/1.75/2) — so the slot's one unconditional
# control is the displacement, not the root.
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
    "R (Insanity Potion) grants the cached Bonus Stats row (25/55/85, "
    "corroborated by the game binary's InsanityPotion StatAmount "
    "DataValue) as ability power, bonus armour, bonus magic resistance "
    "and movement speed for the sourced 25 seconds, time-weighted by the "
    "share of the fight window the buff covers.  The ability power "
    "reaches the parse context before Q and E, so their AP ratios scale "
    "off it.  The same row's health/mana regeneration (2.5/5.5/8.5 per "
    "0.5s by rank) has no stat_buff key because nothing in this "
    "fixed-window engine consumes regen, and the Grievous Wounds R adds "
    "to Poison Trail reduces enemy healing, which the one-pair fight "
    "does not model.",
    "E (Fling) sources a second, conditional effect the engine does not "
    "arm: the target is rooted (1/1.25/1.5/1.75/2s) only 'if the target "
    "lands on Mega Adhesive's area of effect after the displacement'.  "
    "The slot's declared control is the unconditional displacement; the "
    "root would need a W-field placement the fight does not track.",
    "P (Noxious Slipstream) is stacking movement speed and W (Mega "
    "Adhesive) a slow and a ground: both are emitted zero-damage rows, "
    "because the engine has no movement-speed axis and records crowd "
    "control as a kind without a magnitude.  Neither spell object "
    "carries a damage field in the game binary.",
]

# P and W are emitted and grant nothing the engine prices.
MODULE_COVERAGE = coverage(no_damage="PW")
