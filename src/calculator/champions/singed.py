"""Singed — CP10.7 full-entry-reviewed packet module.

R (Insanity Potion) is the one slot whose grants the engine can price:
"Singed empowers himself for 25 seconds with ability power, bonus armor,
bonus magic resistance, bonus movement speed" — one cached "Bonus Stats"
row (25/55/85, corroborated by the game binary's InsanityPotion
``StatAmount`` DataValue) that every one of those stats reads.  The
ability power is fed into the parse context as well as the fight engine,
because Q's poison ticks and E's fling both carry AP ratios, so the
ultimate amplifies Singed's own damage exactly as the census said it
should.  The movement speed rides the same row into the shared
``stats.resolve_move_speed`` fold, whose output is
``item_state_receipts``' ``total_move_speed`` input.  The health/mana
regeneration has no stat_buff key — this fixed-window burst engine
consumes no regen — and the Grievous Wounds R adds to Poison Trail is an
enemy-healing effect the one-pair fight has no target to apply to.

P (Noxious Slipstream) and W (Mega Adhesive) stay emitted zero rows.
Neither spell object carries a damage field at all — ``SingedP`` holds
only ``MSPercent``/``MSDuration``/``PerTargetCD``/``TriggerArea`` and
``MegaAdhesive`` only ``SlowPercent``/``WDuration``/``WRadius``/
``DelayExecute``/``Radius`` — and W's 50-70% slow and its ground are
crowd control the engine records only as a kind.  P's stacking movement
speed has a channel (the shared ``move_speed_percent`` fold) but no
cached magnitude to put in it — see the ASSUMPTIONS entry.
"""

from typing import Any

from .engine import BUFF, SlotCtx
from .module_helpers import buff_window_share
from .packet_module import build_packet_module
from .slotlib import (
    STEROID_ZERO,
    ability_name,
    damage_entry,
    extract_cooldown,
    extract_value,
)
from .module_contract import coverage
from ..binary_roots import data_value, spell_object

PACKET_SHA256 = "d6e04f1cd92d4f7ddd569c7ba4bb306cdd06c18e230c7ed2a57ef89ba45b3c9c"

# Rooted in Singed.InsanityPotion.Duration; the cached R prose corroborates
# the 25-second window. The magnitude remains the JSON's shared Bonus Stats
# row.
_R_DURATION_SECONDS = data_value(spell_object("Singed", "InsanityPotion"), "Duration")

# The one "Bonus Stats" row grants the same flat number to four stats at
# once.  Three of them have a consumer here: ability power (Q's poison
# ticks and E's fling both carry AP ratios), armour and magic resistance
# (the self-resist keys every other steroid module publishes — Braum,
# Briar, Gnar, Graves, Jayce, Olaf, Shyvana), and movement speed.  The
# row's health/mana regeneration has none, so it carries no key.
#
# The movement key is ``move_speed_flat``, the fold's INPUT, never the
# displayed ``move_speed`` it produces: writing the displayed stat
# directly skipped ``stats.resolve_move_speed`` and with it the soft
# caps, publishing an uncapped 430.0 where the fold gives 427.0 — and
# ``item_state_receipts`` reads that same displayed number as its
# ``total_move_speed`` input, so the miss reached Swiftmarch's adaptive
# force.
_INSANITY_POTION_STATS = (
    "ability_power",
    "armor",
    "magic_resistance",
    "move_speed_flat",
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
        ability_name(ability),
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
    "W (Mega Adhesive) stays out of MODULE_CC: its slow is sourced "
    "(the cached 'Slow' row, 50/55/60/65/70%) but its window is not. "
    "The field lasts 3 seconds by the effect description alone, and the "
    "only seconds atom the slot carries is the 0.375s landing delay -- "
    "reading that one as the control window would understate the slow "
    "eightfold, so the slot is left unreviewed rather than declared "
    "against the wrong number.",
    "R (Insanity Potion) grants the cached Bonus Stats row (25/55/85, "
    "corroborated by the game binary's InsanityPotion StatAmount "
    "DataValue) as ability power, bonus armour, bonus magic resistance "
    "and movement speed for the sourced 25 seconds, time-weighted by the "
    "share of the fight window the buff covers.  The ability power "
    "reaches the parse context before Q and E, so their AP ratios scale "
    "off it.  The movement key is move_speed_flat, the shared "
    "resolve_move_speed fold's INPUT, so the grant is soft-capped like "
    "every other movement term; keying the displayed move_speed directly "
    "skipped the fold and published an uncapped number.  The same row's "
    "health/mana regeneration (2.5/5.5/8.5 per "
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
    "Adhesive) a slow and a ground: both are emitted zero-damage rows. "
    "W's slow magnitude is blocked on the cache (its only seconds atom "
    "is the 0.375 landing delay).  Neither spell object carries a damage "
    "field in the game binary.",
    "P (Noxious Slipstream) is NOT published as a move_speed_percent "
    "stat_buff, unlike the other percent-movement grants: its magnitude "
    "has no cached row to read.  All three cached P effects carry an "
    "empty leveling array, so extract_value would return its "
    "missing-row 0.0, and the only number anywhere is the v2 atom "
    "corpus' SingedP MSPercent = 0.25, "
    "which is ambiguous between per-stack and total: the cached prose "
    "reads '25% bonus movement speed' per stack 'up to a maximum of "
    "625%', and 625 == 25 x 25 is the 25-stack cap multiplied into the "
    "per-stack slot, the signature of a wiki-template substitution.  A "
    "25x span is not a rounding question, so the slot stays unwired.  "
    "The stack count is unmodeled state on top: stacks come from moving "
    "past champions on a sourced 8s per-target cooldown (PerTargetCD), "
    "which a one-pair fight cannot walk.",
]

# P and W are emitted and grant nothing the engine prices.
MODULE_COVERAGE = coverage(no_damage="PW")
