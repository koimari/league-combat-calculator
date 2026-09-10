"""Twisted Fate — E5-1 corrected slot map for the archetype engine.

Why each slot is non-generic:

- W (Pick a Card) is a card SELECTION, not the sum of all three cards:
  the wiki lists one "Magic Damage" leveling row per card (Blue Card =
  40 / 60 / 80 / 100 / 120 + 100% AD + 100% AP; Red Card = 30 / 45 /
  60 / 75 / 90 + 100% AD + 70% AP; Gold Card = 15 / 22.5 / 30 / 37.5 /
  45 + 100% AD + 50% AP).  The previous packet summed all three cards
  (3.0x AD + 2.2x AP in one hit).  The corrected parser prices exactly
  one selected card via the ``w_card`` option (0 = gold, 1 = red,
  2 = blue; default gold).
- Q (Wild Cards) is a plain "Magic Damage" read (60 / 105 / 150 / 195 /
  240 + 50% bonus AD + 85% AP) for one enemy-champion pass.
- E (Stacked Deck) rides the swing stream, not a cast: its "Bonus Attack
  Speed" row (15 / 25 / 35 / 45 / 55%) is a permanent innate grant, and
  its "Bonus Magic Damage" row (65 / 90 / 115 / 140 / 165 + 20% bonus AD
  + 40% AP) is the every-4th-attack on-hit (three stacking attacks, the
  fourth consumes them), priced by the engine's stack-acceleration on-hit
  the way Master Yi's Double Strike is.
- P (Loaded Dice) and R (Destiny) deal no enemy damage and are explicit
  no-damage slots.

All numeric values are read from the champion JSON data; nothing is
hardcoded.
"""

import re
from typing import Any

from ..ability_spec import DamagePart
from .contract_vocabulary import coverage
from .engine import BUFF, SlotCtx, build_parser
from .inputs import int_option
from .module_helpers import no_damage_parser, ranked_slot, steroid_entry
from .shared_mechanics import prose_numbers
from .slot_cc import CC_PER_PART
from .slot_control import with_control
from .slot_entries import damage_entry
from .slot_extract import (
    extract_cooldown,
    extract_named,
    extract_value,
    find_named_leveling,
    sum_modifiers,
)
from .slotlib import simple_damage
from .source_receipts import load_champion_sources

# Stacked Deck's cap lives only in the cached E prose ("stacking up to 3
# times"); the attack after the cap consumes the stacks, so the on-hit's
# period is the cap plus one.
_E_STACK_CAP_PROSE = re.compile(r"stacking up to (\d+) times", re.IGNORECASE)


@ranked_slot
def _stacked_deck(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """E: the permanent attack speed, and the every-4th-attack on-hit."""
    cap = prose_numbers(ctx, "E", _E_STACK_CAP_PROSE)
    if cap is None or cap[0] is None:
        raise ValueError("Twisted Fate E: the Stacked Deck stack cap is missing")
    period = int(cap[0]) + 1
    bonus_as = extract_value(ability, "Bonus Attack Speed", rank)
    per_proc = extract_named(ability, "Bonus Magic Damage", rank, ctx.stats, ctx.target)
    return steroid_entry(
        ability,
        rank,
        {"bonus_attack_speed": bonus_as},
        f"+{bonus_as:g}% bonus attack speed (passive, no duration); every "
        f"{period}th basic attack deals {per_proc:g} bonus magic damage on-hit",
        dmg_type="magic",
        innate_grant=True,
        on_hit={
            "name": "Stacked Deck (on-hit)",
            "damage_per_hit": per_proc / period,
            "damage_type": "magic",
            "stacks_required": period,
        },
    )


_stacked_deck.phase = BUFF

# Pick a Card's three card branches, in the cycle order the game presents
# (gold -> red -> blue).  The wiki JSON stores the "Magic Damage" rows as
# three occurrences: 0 = Blue Card, 1 = Red Card, 2 = Gold Card.
#
# Each card's reviewed crowd control comes from its own cached bonus line,
# which is why W's answer rides its part rather than MODULE_CC: "Blue Card
# Bonus: Deals magic damage ... and restores mana" (no control), "Red Card
# Bonus: ... All targets hit are slowed for 2.5 seconds", "Gold Card
# Bonus: ... and stuns the target for a duration".
_CARD_OCCURRENCES = (2, 1, 0)
_CARD_NAMES = ("Gold Card", "Red Card", "Blue Card")
_CARD_CC = ("stun", "slow", "none")


def _card_parser(occurrence: int, name: str, cc_kind: str):
    """One selected card's magic damage (flat + 100% AD + AP ratio)."""

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        ranked = ctx.ranked()
        if ranked is None:
            return None
        ability, rank = ranked
        leveling = find_named_leveling(ability, "Magic Damage", occurrence)
        if leveling is None:
            return None
        value = sum_modifiers(leveling, rank, ctx.stats, ctx.target)
        entry = damage_entry(
            name, rank, extract_cooldown(ability, rank), value, "magic"
        )
        # One empowered basic attack, one blow — the row is a hit the
        # ledger can time, so the card's own answer reaches its readers.
        entry["parts"] = (DamagePart("magic", value, cc_kind=cc_kind),)
        entry["event_order_certified"] = "single_hit"
        return entry

    parse.phase = "damage"
    return parse


# The Gold Card's stun rides a cached rank array ("Stun Duration",
# 1 / 1.25 / 1.5 / 1.75 / 2 seconds), so its interval is sourced from the
# packet.  The Red Card's slow has no such row — its cached "Slow" leveling
# is the percentage, and the 2.5-second window lives in prose — so its part
# carries the reviewed kind without an interval rather than reading a
# percent as seconds.
_CARDS = (
    with_control(
        _card_parser(_CARD_OCCURRENCES[0], _CARD_NAMES[0], _CARD_CC[0]),
        kind="stun",
        duration_attr="Stun Duration",
    ),
    _card_parser(_CARD_OCCURRENCES[1], _CARD_NAMES[1], _CARD_CC[1]),
    _card_parser(_CARD_OCCURRENCES[2], _CARD_NAMES[2], _CARD_CC[2]),
)


def _pick_a_card(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: exactly one selected card (w_card option, default gold)."""
    try:
        index = int(ctx.option("w_card"))
    except (TypeError, ValueError):
        index = 0
    index = max(0, min(index, len(_CARDS) - 1))
    return _CARDS[index](ctx)


ASSUMPTIONS = [
    "W (Pick a Card) prices exactly one selected card; the default is the "
    "Gold Card (stun).  The other two cards are selectable via the w_card "
    "option.",
    "Q (Wild Cards) prices one enemy-champion pass.",
    "E (Stacked Deck) is a passive on the swing stream: its bonus attack "
    "speed is an innate grant the fight always holds (autos-only too), and "
    "its bonus magic damage rides every 4th basic attack (three stacking "
    "attacks, the fourth consumes them) through the engine's stack-"
    "acceleration on-hit, the Master Yi Double Strike convention: the proc "
    "is spread across the stacking hits, stacks start at zero (the "
    "respawn full-stack rule is not modeled), and only basic attacks stack.",
    "P and R deal no enemy damage and are explicit no-damage slots.",
]

SOURCES = load_champion_sources("Twisted Fate")

SLOTS = {
    "P": no_damage_parser(
        "P",
        "Loaded Dice is a gold/utility passive; no enemy damage.",
    ),
    # One card per pass ("Enemies can be damaged only once per pass"): the
    # row is one blow the ledger can time.
    "Q": simple_damage(
        attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
    ),
    "W": _pick_a_card,
    "E": _stacked_deck,
    "R": no_damage_parser(
        "R",
        "Destiny reveals and teleports; no enemy damage.",
    ),
}

MODULE_COVERAGE = coverage(no_damage="PR")

OPTIONS = [
    int_option("w_card", 0, minimum=0, maximum=2, label="Pick a Card selection"),
]

# Reviewed crowd control, read from the cached kit.  Q (Wild Cards)
# "throws a fan of three cards ... that each deal magic damage to enemies
# hit" and applies no control; E (Stacked Deck)'s consuming attack
# "deal[s] bonus magic damage" on-hit and applies none either.  W's answer
# is the selected card's and is authored on its part above.
MODULE_CC = {"Q": "none", "W": CC_PER_PART, "E": "none", "P": "none", "R": "none"}

parse_abilities = build_parser(SLOTS, "Twisted Fate", cc_kinds=MODULE_CC)
