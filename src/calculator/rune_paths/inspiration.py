"""Inspiration's minor runes.

Inspiration is the path whose runes buy things the fight model has no axis
for — biscuits, boots, elixirs, summoner-spell swaps, gold back. All nine
compile to the same shape Cosmic Insight showed: selectable, and receipted
as a refusal rather than a silent zero. Two of them are refused for what
the engine cannot reach rather than for what the rune does not do, and say
which: Jack Of All Trades grants two stats at once off a count of the
build's own item stats, and Biscuit Delivery's health is earned over a game.
"""

from typing import Any, Callable, Mapping

from ..ability_spec import Disposition
from ..rune_effects import RuneEffect, RuneOption, no_damage_compiler

#: The Inspiration runes that book no damage: disposition, the reason that
#: becomes the receipt, and any further half this engine refuses.
_NO_DAMAGE: dict[str, tuple[Disposition, str, tuple[str, ...]]] = {
    # Cosmic Insight's haste is real and reaches nothing this engine reads.
    # Summoner spells are outside the damage model entirely, and an item
    # active is priced once per fight (``damage._add_item_active_damage``)
    # whatever its cooldown, so item haste changes no number either. That
    # makes it withheld — the number exists and is refused — rather than a
    # structural zero, and it is *not* a stat grant: ability haste, the one
    # haste the engine reads, is not what this rune grants.
    "Cosmic Insight": (
        Disposition.WITHHELD,
        "it grants summoner-spell haste and item haste, and the engine "
        "reads neither — summoner spells are outside the damage model, "
        "and an item active is priced once per fight whatever its cooldown",
        (
            "Cosmic Insight grants no ability haste, so nothing in the "
            "fight's cooldowns is understated by withholding it.",
        ),
    ),
    "Hextech Flashtraption": (
        Disposition.STRUCTURAL_ZERO,
        "it replaces Flash with a charged blink while Flash is on cooldown, "
        "and no source states a combat number for it",
        (),
    ),
    "Magical Footwear": (
        Disposition.WITHHELD,
        "it grants free boots on a clock and flat bonus movement speed, and "
        "the engine buys no item on a clock and reads no movement speed in "
        "any damage row",
        (
            "Magical Footwear's boots are the request's own to hold: a build "
            "that means to wear them lists them, and the rune's saved gold "
            "is not a fight number.",
        ),
    ),
    "Cash Back": (
        Disposition.STRUCTURAL_ZERO,
        "it refunds a share of every legendary item's gold cost, and gold "
        "never joins the fight's damage total",
        (),
    ),
    "Biscuit Delivery": (
        Disposition.WITHHELD,
        "its biscuits restore health and mana and each one consumed raises "
        "maximum health permanently, and the engine has no rune healing "
        "channel",
        (
            "Biscuit Delivery's permanent maximum health is earned biscuit "
            "by biscuit at fixed game minutes, over a game this one fight "
            "does not simulate; the cache carries the biscuit's sale price "
            "and not the health it grants.",
        ),
    ),
    "Time Warp Tonic": (
        Disposition.WITHHELD,
        "it adds a share of a consumed potion's restoration as an immediate "
        "heal, and the engine has no rune healing channel",
        (
            "Time Warp Tonic prices nothing even where a heal channel "
            "existed: the fight model consumes no potions.",
        ),
    ),
    "Triple Tonic": (
        Disposition.WITHHELD,
        "it grants three elixirs at fixed champion levels, and the engine "
        "prices no consumable — a build that means to hold one lists it",
        (),
    ),
    "Approach Velocity": (
        Disposition.WITHHELD,
        "it grants bonus movement speed toward impaired enemy champions, and "
        "no damage row reads movement speed",
        (),
    ),
    # Two things stop this one, and both are engine reach rather than a
    # missing number. Its stacks are the distinct stat types the build's
    # own items grant, which the rune stat context does not carry; and it
    # grants ability haste *and* adaptive force, where a rune grants one
    # channel. Its adaptive halves do not survive the parse either.
    "Jack Of All Trades": (
        Disposition.WITHHELD,
        "its stacks count the distinct stat types the build's items grant "
        "and the rune stat context carries no item stats, and it grants two "
        "stat channels where a rune stat grant names one",
        (
            "Jack Of All Trades' ability haste per stack is cached and its "
            "adaptive force at five and ten stacks is not: the three "
            "adaptive figures its description states conflict in the parse "
            "and are dropped, so even the reachable half would be a floor.",
        ),
    ),
}

COMPILERS: dict[str, Callable[[Mapping[str, Any]], RuneEffect]] = {
    name: no_damage_compiler(name, *declaration)
    for name, declaration in _NO_DAMAGE.items()
}

OPTIONS: dict[str, tuple[RuneOption, ...]] = {}
