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

from .engine import SlotCtx, build_parser
from .module_helpers import no_damage_parser
from .source_receipts import load_champion_sources
from .slotlib import (
    damage_entry,
    extract_cooldown,
    find_named_leveling,
    simple_damage,
    sum_modifiers,
    with_control,
)

# Pick a Card's three card branches, in the cycle order the game presents
# (gold -> red -> blue).  The wiki JSON stores the "Magic Damage" rows as
# three occurrences: 0 = Blue Card, 1 = Red Card, 2 = Gold Card.
_CARD_OCCURRENCES = (2, 1, 0)
_CARD_NAMES = ("Gold Card", "Red Card", "Blue Card")


def _card_parser(occurrence: int, name: str):
    """One selected card's magic damage (flat + 100% AD + AP ratio)."""

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        ability = ctx.ability()
        if ability is None:
            return None
        rank = ctx.rank_for()
        if rank < 1:
            return None
        leveling = find_named_leveling(ability, "Magic Damage", occurrence)
        if leveling is None:
            return None
        value = sum_modifiers(leveling, rank, ctx.stats, ctx.target)
        return damage_entry(name, rank, extract_cooldown(ability, rank), value, "magic")

    parse.phase = "damage"
    return parse


_CARDS = (
    with_control(
        _card_parser(_CARD_OCCURRENCES[0], _CARD_NAMES[0]),
        kind="stun",
        duration_attr="Stun Duration",
    ),
    _card_parser(_CARD_OCCURRENCES[1], _CARD_NAMES[1]),
    _card_parser(_CARD_OCCURRENCES[2], _CARD_NAMES[2]),
)


def _pick_a_card(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: exactly one selected card (w_card option, default gold)."""
    try:
        index = int(ctx.options.get("w_card", 0))
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

SOURCES = list(load_champion_sources("Twisted Fate"))

SLOTS = {
    "P": no_damage_parser(
        "P",
        "Loaded Dice is a gold/utility passive; no enemy damage.",
    ),
    "Q": simple_damage(attr="Magic Damage", dmg_type="magic"),
    "W": _pick_a_card,
    "E": simple_damage(attr="Bonus Magic Damage", dmg_type="magic"),
    "R": no_damage_parser(
        "R",
        "Destiny reveals and teleports; no enemy damage.",
    ),
}

MODULE_COVERAGE = {
    "P": "no_damage",
    "Q": "modeled",
    "W": "modeled",
    "E": "modeled",
    "R": "no_damage",
}

OPTIONS = [
    {
        "key": "w_card",
        "type": "int",
        "default": 0,
        "label": "Pick a Card selection",
        "min": 0,
        "max": 2,
    },
]

parse_abilities = build_parser(SLOTS, "Twisted Fate")
REVIEW_STATUS = "reviewed_module"
