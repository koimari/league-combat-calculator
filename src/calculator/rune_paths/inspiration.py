"""Inspiration's minor runes.

Inspiration is the path whose runes buy things the fight model has no axis
for — biscuits, boots, elixirs, summoner-spell swaps, gold back. Eight of
the nine compile to the same shape Cosmic Insight showed: selectable, and
receipted as a refusal rather than a silent zero. The ninth is Jack Of All
Trades, whose stacks are the build's own item stat types and whose two
channels are granted together.
"""

from collections.abc import Callable, Mapping
from typing import Any

from ..ability_spec import Disposition
from ..rune_effects import (
    RuneEffect,
    RuneMultiStatGrantEffect,
    RuneOption,
    RuneStat,
    RuneStatContext,
    RuneValues,
    no_damage_compiler,
    threshold_gates,
)

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
        "maximum health permanently, and the fight model consumes none: they "
        "arrive at fixed game minutes over a game one fight does not "
        "simulate",
        (
            "Biscuit Delivery's permanent maximum health is unknown as well "
            "as unearned: the cache carries the biscuit's sale price and not "
            "the health consuming one grants.",
        ),
    ),
    "Time Warp Tonic": (
        Disposition.WITHHELD,
        "it adds a share of a consumed potion's restoration as an immediate "
        "heal, and the fight model consumes no potions — the heal channel "
        "exists and there is nothing to pay it on",
        (),
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
}


def _compile_jack_of_all_trades(entry: Mapping[str, Any]) -> RuneMultiStatGrantEffect:
    """Compile Jack Of All Trades: ability haste per stack, adaptive at gates.

    Its stacks are a fact about the build rather than an option: the count
    of distinct stat types the build's items grant, which the stat context
    carries because the request already holds the build. Both channels are
    computed from that one count in one declaration, so the haste and the
    adaptive force can never read different stack totals.
    """
    name = "Jack Of All Trades"
    effects = RuneValues(name, entry.get("effects", {}))
    haste_per_stack = effects.number("ability_haste_per_stack")
    gates = threshold_gates(name, effects, "adaptive_force_stack_gates")
    granted = ", ".join(f"{force:g} at {stacks} stacks" for stacks, force in gates)

    def amounts(context: RuneStatContext) -> Mapping[RuneStat, float]:
        stacks = context.item_stat_types
        return {
            RuneStat.ABILITY_HASTE: haste_per_stack * stacks,
            RuneStat.ADAPTIVE_FORCE: float(
                sum(force for gate, force in gates if stacks >= gate)
            ),
        }

    return RuneMultiStatGrantEffect(
        rune_name=name,
        stats=(RuneStat.ABILITY_HASTE, RuneStat.ADAPTIVE_FORCE),
        amounts=amounts,
        disclosures=(
            f"{name} grants {haste_per_stack:g} ability haste per stack plus "
            f"adaptive force {granted}, and its stacks are counted off the "
            "build: one per distinct stat type the equipped items' stat "
            "blocks grant.",
            f"{name} counts the stat blocks alone: a stat an item passive "
            "grants conditionally is not one the build holds when the fight "
            "opens, so the stack count is a floor.",
        ),
    )


COMPILERS: dict[str, Callable[[Mapping[str, Any]], RuneEffect]] = {
    "Jack Of All Trades": _compile_jack_of_all_trades,
    **{
        name: no_damage_compiler(name, *declaration)
        for name, declaration in _NO_DAMAGE.items()
    },
}

OPTIONS: dict[str, tuple[RuneOption, ...]] = {}
