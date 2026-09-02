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
- E (Stacked Deck) is a plain "Bonus Magic Damage" read (65 / 90 / 115 /
  140 / 165 + 20% bonus AD + 40% AP) for the empowered attack.
- P (Loaded Dice) and R (Destiny) deal no enemy damage and are explicit
  no-damage slots.

All numeric values are read from the champion JSON data; nothing is
hardcoded.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import CC_PER_PART, SlotCtx, build_parser
from .inputs import int_option
from .module_contract import coverage
from .module_helpers import no_damage_parser
from .slotlib import (
    damage_entry,
    extract_cooldown,
    find_named_leveling,
    simple_damage,
    sum_modifiers,
    with_control,
)
from .source_receipts import load_champion_sources

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
    "E (Stacked Deck) prices the empowered attack's bonus magic damage.",
    "P and R deal no enemy damage and are explicit no-damage slots.",
]

SOURCES = load_champion_sources("Twisted Fate")

SLOTS = {
    "P": no_damage_parser(
        "P",
        "Loaded Dice is a gold/utility passive; no enemy damage.",
    ),
    # One card per pass ("Enemies can be damaged only once per pass") and
    # one empowered attack: each row is one blow the ledger can time.
    "Q": simple_damage(
        attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
    ),
    "W": _pick_a_card,
    "E": simple_damage(
        attr="Bonus Magic Damage",
        dmg_type="magic",
        event_order_certified="single_hit",
    ),
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
# hit" and applies no control; E (Stacked Deck)'s three-stack attack
# "deal[s] bonus magic damage" and applies none either.  W's answer is the
# selected card's and is authored on its part above.
MODULE_CC = {"Q": "none", "W": CC_PER_PART, "E": "none"}

parse_abilities = build_parser(SLOTS, "Twisted Fate", cc_kinds=MODULE_CC)
