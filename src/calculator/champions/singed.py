"""Singed: full-entry-reviewed packet module.

R (Insanity Potion) is the one slot whose grants the engine can price: one
cached "Bonus Stats" row that ability power, bonus armor, bonus magic resistance
and bonus movement speed all read, corroborated by the binary's ``StatAmount``.
The ability power is fed into the parse context as well as the fight engine,
because Q's poison ticks and E's fling both carry AP ratios, so the ultimate
amplifies Singed's own damage.  The movement speed rides the same row into the
shared ``stats.resolve_move_speed`` fold.  The health and mana regeneration has
no ``stat_buff`` key, this fixed-window engine consuming no regeneration, and
the Grievous Wounds R adds to Poison Trail is an enemy-healing effect a one-pair
fight has no target for.
P (Noxious Slipstream) and W (Mega Adhesive) stay emitted zero rows: neither
spell object carries a damage field at all, and W's slow and its ground are
crowd control the engine records only as a kind.  P's stacking movement speed
has a channel, the shared ``move_speed_percent`` fold, but no cached magnitude
to put in it.
"""

from typing import Any

from ..binary_roots import data_value, spell_object
from .contract_vocabulary import coverage
from .engine import BUFF, SlotCtx
from .module_helpers import buff_window_share, ranked_slot, steroid_entry
from .packet_module import build_packet_module
from .slot_extract import extract_value

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


@ranked_slot
def _insanity_potion(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """R: one Bonus Stats row granted as AP, resistances and move speed."""

    granted = extract_value(ability, "Bonus Stats", rank)
    bonus = granted * buff_window_share(ctx, _R_DURATION_SECONDS)
    # BUFF phase: Q's poison ticks and E's fling both carry AP ratios and
    # parse after this slot, so the ultimate amplifies its own kit.
    ctx.stats["ability_power"] = ctx.stat("ability_power") + bonus
    return steroid_entry(
        ability,
        rank,
        dict.fromkeys(_INSANITY_POTION_STATS, bonus),
        (
            f"+{granted:g} ability power, armour, magic resistance and movement "
            f"speed for {_R_DURATION_SECONDS:g}s ({bonus:g} over the fight "
            "window); the same row's health/mana regeneration has no stat_buff "
            "key, and its Grievous Wounds is an enemy-healing effect the "
            "one-pair fight cannot apply"
        ),
        dmg_type="magic",
    )


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
MODULE_CC = {"Q": "none", "E": "airborne", "P": "none", "W": "slow", "R": "none"}

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

ASSUMPTIONS = [
    *list(ASSUMPTIONS),
    "W (Mega Adhesive) stays out of MODULE_CC: its slow is sourced, 50/55/60/65/70%, "
    "but its window is not.",
    "The field lasts 3 seconds by the effect description alone.",
    "The only seconds atom the slot carries is the 0.375s landing delay.",
    "Reading that as the control window would understate the slow eightfold, so W is "
    "left unreviewed.",
    "R (Insanity Potion) grants the cached Bonus Stats row, 25/55/85, for the sourced "
    "25 seconds.",
    "The binary's InsanityPotion StatAmount DataValue corroborates it.",
    "It lands as ability power, bonus armour, bonus magic resist and movement speed, "
    "fight-share weighted.",
    "The ability power reaches the parse context before Q and E, so their AP ratios "
    "scale off it.",
    "The movement key is move_speed_flat, the resolve_move_speed fold's input, so it "
    "is soft-capped.",
    "Keying the displayed move_speed directly would skip the fold and publish an "
    "uncapped number.",
    "The row's 2.5/5.5/8.5 per 0.5s health/mana regeneration has no stat_buff key: "
    "nothing consumes regen.",
    "R's Grievous Wounds on Poison Trail cuts enemy healing, which the one-pair fight "
    "does not model.",
    "E (Fling) sources a second, conditional effect the engine does not arm.",
    "The target is rooted 1/1.25/1.5/1.75/2s only on landing in Mega Adhesive's area "
    "of effect.",
    "E's declared control is the unconditional displacement.",
    "E's root would need a W-field placement this fight does not model.",
    "P (Noxious Slipstream) is stacking movement speed and W (Mega Adhesive) a slow "
    "and a ground.",
    "Both are emitted zero-damage rows, and neither spell object carries a damage "
    "field in the binary.",
    "W's slow magnitude is blocked on the cache: its only seconds atom is the 0.375s "
    "landing delay.",
    "P (Noxious Slipstream) is not published as a move_speed_percent stat_buff: no "
    "cached row reads it.",
    "All three cached P effects carry an empty leveling array, so extract_value would "
    "return 0.0.",
    "The one number anywhere is the corpus' SingedP MSPercent 0.25, ambiguous between "
    "per-stack and total.",
    "The cached prose reads '25% bonus movement speed' per stack 'up to a maximum of "
    "625%'.",
    "625 == 25 x 25 is the 25-stack cap in the per-stack slot, a wiki-template "
    "substitution.",
    "A 25x span is not a rounding question, so the slot stays unwired.",
    "The stack count is unmodeled state: stacks need a sourced 8s PerTargetCD a "
    "one-pair fight cannot walk.",
]

# P and W are emitted and grant nothing the engine prices.
MODULE_COVERAGE = coverage(no_damage="PW")
