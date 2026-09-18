"""Inspiration's minor runes.

Inspiration is the path whose runes buy things the fight model has no axis
for — biscuits, boots, elixirs, summoner-spell swaps, gold back. Four of
the nine compile to the same shape Hextech Flashtraption showed: selectable,
and receipted as a refusal rather than a silent zero. The other five grant a
stat: Jack Of All Trades, whose stacks are the build's own item stat types
and whose two channels are granted together, Approach Velocity, whose
movement speed reaches damage through Swiftmarch's conversion behind a
switch for the position the request does not carry, Magical Footwear,
whose flat boots grant rides the same conversion with no gate to ask for,
Cosmic Insight, whose item haste shortens the empowered-auto stream's own
cooldown, and Biscuit Delivery, whose permanent maximum health is kept per
biscuit the request says was consumed.
"""

from collections.abc import Callable, Mapping
from typing import Any

from ..ability_spec import Disposition
from ..rune_effects import (
    RuneEffect,
    RuneMultiStatGrantEffect,
    RuneOption,
    RuneOptionKind,
    RuneStat,
    RuneStatContext,
    RuneStatGrantEffect,
    RuneValues,
    cached_effects,
    no_damage_compiler,
    threshold_gates,
)

#: Biscuit Delivery's biscuits are drunk between fights, so how many the
#: holder has kept the health of is banked progress the request states.
_BISCUITS_CONSUMED = "biscuits_consumed"


def _biscuit_count() -> float:
    """How many biscuits the rune hands out, from its own cached count."""
    return cached_effects("Biscuit Delivery").number("consumable_deliveries")


#: Approach Velocity's gate is where the holder is standing and what the
#: enemy is suffering, and the request carries neither, so it is a switch
#: with a disclosed default the way Waterwalking's river is.
_NEAR_IMPAIRED = "near_impaired_enemy"

#: The Inspiration runes that book no damage: disposition, the reason that
#: becomes the receipt, and any further half this engine refuses.
_NO_DAMAGE: dict[str, tuple[Disposition, str, tuple[str, ...]]] = {
    "Hextech Flashtraption": (
        Disposition.STRUCTURAL_ZERO,
        "it replaces Flash with a charged blink while Flash is on cooldown, "
        "and no source states a combat number for it",
        (),
    ),
    "Cash Back": (
        Disposition.STRUCTURAL_ZERO,
        "it refunds a share of every legendary item's gold cost, and gold "
        "never joins the fight's damage total",
        (),
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
}


def _compile_approach_velocity(entry: Mapping[str, Any]) -> RuneStatGrantEffect:
    """Compile Approach Velocity: movement speed near an impaired enemy.

    Movement speed is a stat the build publishes and Swiftmarch converts into
    adaptive force, so the grant reaches damage the way Celerity's does. The
    gate is the part the request cannot answer: whether a visible enemy
    champion is impaired within the rune's range, and whether the holder is
    facing them.
    """
    name = "Approach Velocity"
    effects = RuneValues(name, entry.get("effects", {}))
    percent = effects.number("move_speed_percent")

    def amount(context: RuneStatContext) -> float:
        return percent if context.option(name, _NEAR_IMPAIRED, 0.0) else 0.0

    return RuneStatGrantEffect(
        rune_name=name,
        stat=RuneStat.MOVE_SPEED_PERCENT,
        amount=amount,
        disclosures=(
            f"{name} grants {percent:g}% bonus total movement speed while its "
            f"{_NEAR_IMPAIRED!r} option says a visible enemy champion is "
            "impaired in range, and nothing by default: the fight model "
            "carries no position, so where the holder stands is asked for "
            "rather than inferred.",
            f"{name}'s movement speed reaches the stat card and Swiftmarch's "
            "conversion of movement speed into adaptive force, which prices "
            "the build's one published movement speed; no damage row reads "
            "movement speed itself.",
        ),
    )


def _compile_magical_footwear(entry: Mapping[str, Any]) -> RuneStatGrantEffect:
    """Compile Magical Footwear: flat bonus movement speed on boots.

    The rune's two halves split the way Conditioning's did: the free boots
    on a clock stay withheld — the engine buys no item on a clock, and a
    build that means to wear boots lists them — while the flat 10 bonus
    movement speed those boots grant rides the flat channel into the one
    published movement speed Swiftmarch converts into adaptive force. No
    gate is asked for: the +10 sentence carries no timing of its own, only
    the boots do, so the grant is priced as held the way Unflinching's is.
    """
    name = "Magical Footwear"
    effects = RuneValues(name, entry.get("effects", {}))
    flat = effects.number("flat_bonus_move_speed")

    def amount(context: RuneStatContext) -> float:
        del context  # unconditional: the boots half is withheld, this half held
        return flat

    return RuneStatGrantEffect(
        rune_name=name,
        stat=RuneStat.MOVE_SPEED_FLAT,
        amount=amount,
        disclosures=(
            f"{name} grants {flat:g} flat bonus movement speed, priced as "
            "held: its free boots arrive on a clock the fight model carries "
            "no clock for, so the boots are the request's own to list and "
            "the rune's saved gold is not a fight number.",
            f"{name}'s movement speed reaches the stat card and Swiftmarch's "
            "conversion of movement speed into adaptive force, which prices "
            "the build's one published movement speed; no damage row reads "
            "movement speed itself.",
        ),
    )


def _compile_cosmic_insight(entry: Mapping[str, Any]) -> RuneStatGrantEffect:
    """Compile Cosmic Insight: item haste into the empowered-auto stream.

    Its old receipt named the channel exactly — "no channel carries item
    haste" — and named what the channel would reach: the empowered-auto
    stream, which walks Titanic Crescent's declared cooldown and counts one
    proc per window. The member is now in the closed stat set and both
    numbers came out of prose the parser had no rule for, so the grant
    lands where the stream reads it. The summoner-spell half stays
    withheld: summoner spells are outside the damage model, the
    Ionian-Insight shape, and no request carries one.
    """
    name = "Cosmic Insight"
    effects = RuneValues(name, entry.get("effects", {}))
    item_haste = effects.number("item_haste")
    summoner_haste = effects.number("summoner_spell_haste")

    def amount(context: RuneStatContext) -> float:
        del context  # unconditional: haste is worn, not gated
        return item_haste

    return RuneStatGrantEffect(
        rune_name=name,
        stat=RuneStat.ITEM_HASTE,
        amount=amount,
        disclosures=(
            f"{name} grants {item_haste:g} item haste, which shortens the "
            "empowered-auto stream's own cooldown through the shared haste "
            "formula: that stream walks Titanic Crescent's declared cooldown "
            "and counts one proc per window, so a shorter cooldown is more "
            "procs in a window that holds the extra one. An item active "
            "priced once per fight is unmoved by its own cooldown, so that "
            "stream reads no haste of any kind.",
            f"{name}'s {summoner_haste:g} summoner-spell haste is withheld: "
            "summoner spells are outside the damage model and the fight "
            "casts none, so nothing it shortens would buy another cast. It "
            "grants no ability haste either, so no ability cooldown is "
            "understated by withholding that half.",
        ),
    )


def _compile_biscuit_delivery(entry: Mapping[str, Any]) -> RuneStatGrantEffect:
    """Compile Biscuit Delivery: permanent maximum health per biscuit consumed.

    Its refusal named two blockers and the first has gone: the cache carried
    the biscuit's sale price and not the health, and the parser now reads
    both the grant and the number of biscuits the rune hands out. The second
    is not a blocker but a question — how many have been drunk by the time
    the fight opens — and that is the shape every banked count on this page
    takes. The restore itself stays withheld: it happens out of the fight,
    on a clock the fight model has none of.
    """
    name = "Biscuit Delivery"
    effects = RuneValues(name, entry.get("effects", {}))
    per_biscuit = effects.number("max_health_per_consumable")
    biscuits = effects.number("consumable_deliveries")

    def amount(context: RuneStatContext) -> float:
        consumed = min(context.option(name, _BISCUITS_CONSUMED, 0.0), biscuits)
        return consumed * per_biscuit

    return RuneStatGrantEffect(
        rune_name=name,
        stat=RuneStat.BONUS_HEALTH,
        amount=amount,
        disclosures=(
            f"{name} grants {per_biscuit:g} permanent maximum health per "
            f"biscuit consumed, read from the {_BISCUITS_CONSUMED!r} option "
            f"and capped at the {biscuits:g} biscuits it hands out. The "
            "default is zero, the state a fight before the first delivery is "
            "in; the health is kept whether the biscuit is drunk or sold.",
            f"{name}'s restore — the health and mana one biscuit gives back "
            "when it is drunk — is withheld: the biscuits arrive at fixed "
            "game minutes and are consumed between fights, and the fight "
            "model carries no clock to place either on.",
        ),
    )


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
    "Approach Velocity": _compile_approach_velocity,
    "Magical Footwear": _compile_magical_footwear,
    "Biscuit Delivery": _compile_biscuit_delivery,
    "Cosmic Insight": _compile_cosmic_insight,
    "Jack Of All Trades": _compile_jack_of_all_trades,
    **{
        name: no_damage_compiler(name, *declaration)
        for name, declaration in _NO_DAMAGE.items()
    },
}

OPTIONS: dict[str, tuple[RuneOption, ...]] = {
    "Biscuit Delivery": (
        RuneOption(
            key=_BISCUITS_CONSUMED,
            label="Biscuits consumed",
            kind=RuneOptionKind.COUNT,
            default=0.0,
            bounds=(0.0, _biscuit_count()),
            disclosure=(
                "How many of Biscuit Delivery's biscuits have been consumed "
                "or sold before the fight opens; each one kept its maximum "
                f"health. The count runs 0 to {_biscuit_count():g}, 0 by "
                "default, which is a fight before the first delivery."
            ),
        ),
    ),
    "Approach Velocity": (
        RuneOption(
            key=_NEAR_IMPAIRED,
            label="Near an impaired enemy",
            kind=RuneOptionKind.SWITCH,
            default=0.0,
            bounds=(0.0, 1.0),
            disclosure=(
                "1 prices Approach Velocity with a visible enemy champion "
                "impaired in range and the holder facing them, where its "
                "movement speed is live; 0, its default, is the rest of the "
                "fight."
            ),
        ),
    ),
}
