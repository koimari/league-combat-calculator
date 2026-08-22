"""Domination's minor runes.

Nine runes across three rows. Row 1 is the combat row: Cheap Shot prices
bonus true damage on the impaired trigger stream, and its two row-mates
still wait on a channel — a heal with no rune entry point (Taste of Blood)
and a dash the fight's timeline never records (Sudden Impact). Row 2 buys
vision, trinket haste and gold, none of which is damage in any source. Row 3
pays on takedowns: two of the three buy nothing the fight reads, and
Ultimate Hunter grants ultimate haste.

The refusals that name a number are compiled rather than declared: a reader
who picks Taste of Blood should be told what the rune would have healed, not
merely that it dealt nothing.
"""

from typing import Any, Callable, Mapping

from ..champions.inputs import champion_stat
from ..ability_spec import Disposition
from ..item_effects import DamageInputs
from ..rune_effects import (
    RuneEffect,
    RuneHealEffect,
    RuneHealTrigger,
    RuneOption,
    RuneOptionKind,
    RuneProcEffect,
    RuneStat,
    RuneStatContext,
    RuneStatGrantEffect,
    RuneTrigger,
    RuneValues,
    armed_by_option,
    at_level,
    breakdown_key,
    display_name,
    no_damage_compiler,
    required_leveling,
    stack_count_option,
    stated_type,
)

#: The two levels a withheld damage table is quoted at: the fight's floor and
#: the level the wiki's own tables end on.
_QUOTED_LEVELS = (1, 18)


def _level_span(name: str, effects: RuneValues) -> tuple[float, float]:
    """One rune's first level table at levels 1 and 18, for its receipt.
    ``at_level`` clamps, so an eighteen-column table ends at its last row."""
    first, last = _QUOTED_LEVELS
    table = required_leveling(name, effects)
    return at_level(table, first), at_level(table, last)


def _compile_cheap_shot(entry: Mapping[str, Any]) -> RuneProcEffect:
    """Compile Cheap Shot: bonus true damage to a target under crowd control.

    Its trigger stream is the impaired one: a damaging cast whose own
    reviewed parts apply control, so the target is under it when the damage
    lands. The rune names eight control kinds and the stream's predicate is
    every class the bus calls control, which is that list — slows and blinds
    included, not the immobilizing subset.
    """
    name = "Cheap Shot"
    effects = RuneValues(name, entry.get("effects", {}))
    base_by_level = required_leveling(name, effects)
    top = RuneValues(name, entry)

    def raw(inputs: DamageInputs) -> float:
        return at_level(base_by_level, inputs.level)

    return RuneProcEffect(
        rune_name=name,
        breakdown_key=breakdown_key(name),
        display_name=display_name(name),
        stacks_required=1,
        stack_window_seconds=None,
        cooldown_seconds=top.number("cooldown"),
        # The bonus rides the damage that finds the target impaired; the
        # rune states no delay of its own.
        proc_delay_seconds=0.0,
        raw_damage=raw,
        damage_type=stated_type("true"),
        trigger=RuneTrigger.IMPAIRED_INSTANCES,
        disclosures=(
            f"{name} prices the casts whose own reviewed parts apply crowd "
            "control, one per cooldown. The engine carries no control "
            "*duration*, so the damage that lands inside a control an "
            "earlier cast applied is not counted and the proc count is a "
            "floor.",
            f"{name} reads the reviewed control marker a champion module "
            "authors, so a kit whose slots nobody reviewed procs nothing "
            "rather than being assumed to impair.",
        ),
    )


def _compile_taste_of_blood(entry: Mapping[str, Any]) -> RuneHealEffect:
    """Compile Taste of Blood: a heal on damaging a champion, once per cooldown.

    Its trigger is one the engine already walks — damaging a champion on a
    cooldown — so what was missing was only the destination, and the rune
    heal channel is that: its packets join the self-healing ledger beside
    the ones item sustain writes.
    """
    name = "Taste of Blood"
    effects = RuneValues(name, entry.get("effects", {}))
    base_by_level = required_leveling(name, effects)
    bonus_ad_ratio = effects.number("bonus_ad_ratio")
    ap_ratio = effects.number("ap_ratio")
    top = RuneValues(name, entry)
    first, last = _level_span(name, effects)

    def amount(inputs: DamageInputs) -> float:
        stats = inputs.champion_stats
        return (
            at_level(base_by_level, inputs.level)
            + bonus_ad_ratio * champion_stat(stats, "bonus_attack_damage")
            + ap_ratio * champion_stat(stats, "ability_power")
        )

    return RuneHealEffect(
        rune_name=name,
        trigger=RuneHealTrigger.DAMAGE_DEALT,
        cooldown_seconds=top.number("cooldown"),
        delay_seconds=0.0,
        amount=amount,
        disclosures=(
            f"{name} heals {first:g} at level 1 rising to {last:g} at level "
            f"18, plus {bonus_ad_ratio * 100:g}% bonus AD and "
            f"{ap_ratio * 100:g}% AP, once per {top.number('cooldown'):g}s "
            "cooldown on the fight's own damage events.",
            f"{name} does not trigger at full health, and the pair engine "
            "carries no holder health — so every window that lands damage is "
            "priced, which is a ceiling on the heal rather than a floor.",
        ),
    )


#: Sudden Impact is armed by a dash, a blink or an exit from stealth, and
#: the fight's timeline carries damage rather than movement — so whether one
#: happened is a declared switch (decision 5) whose default is the
#: un-triggered state, never an inference from a champion who owns a dash.
_DASHED = "dashed"


def _compile_sudden_impact(entry: Mapping[str, Any]) -> RuneProcEffect:
    """Compile Sudden Impact: true damage armed by a dash, blink or stealth exit.

    The whole trigger is the option: with it off the rune walks no stream
    at all, and with it on the holder is taken to open the fight with one
    movement, so the first damage instance carries the bonus. One arming
    event is one proc — a second would need a second dash the option does
    not state — which is why the rune's own cooldown gates nothing here and
    is quoted instead.
    """
    name = "Sudden Impact"
    effects = RuneValues(name, entry.get("effects", {}))
    base_by_level = required_leveling(name, effects)
    window = effects.number("arming_window_seconds")
    top = RuneValues(name, entry)

    def raw(inputs: DamageInputs) -> float:
        return at_level(base_by_level, inputs.level)

    return RuneProcEffect(
        rune_name=name,
        breakdown_key=breakdown_key(name),
        display_name=display_name(name),
        stacks_required=1,
        stack_window_seconds=None,
        # One arming event is one proc: re-arming needs another dash, and
        # the option states one. The rune's own cooldown is quoted below.
        cooldown_seconds=float("inf"),
        proc_delay_seconds=0.0,
        raw_damage=raw,
        damage_type=stated_type("true"),
        armed=armed_by_option(name, _DASHED),
        disclosures=(
            f"{name} is priced with the holder opening the fight with a "
            f"dash, a blink or a stealth exit — its {_DASHED!r} option, "
            "whose default is that none happened: the fight's timeline "
            "carries damage rather than movement, so the arming event is "
            "asked for rather than inferred.",
            f"{name} prices exactly one empowered instance, the fight's "
            f"first, which is inside the {window:g}s window the rune states "
            "for an opening movement. A second proc would need a second "
            f"dash the option does not state, so its {top.number('cooldown'):g}s "
            "cooldown gates nothing here and the count is a floor of one.",
        ),
    )


#: Ultimate Hunter's stacks are unique enemy champions taken down over a
#: whole game, and one simulated fight scores none — so the count is a
#: declared option (decision 5) whose default is the un-stacked state. Its
#: base grant is unconditional and lands whatever the count says.
_HUNTER_STACKS = "hunter_stacks"


def _compile_ultimate_hunter(entry: Mapping[str, Any]) -> RuneStatGrantEffect:
    """Compile Ultimate Hunter: ultimate haste, a base plus a per-stack step.

    Ultimate haste is a channel of its own in the fight's stat block — the
    engine shortens R's cooldown with it and Q/W/E's with a different one —
    so the grant lands where the rune's own sentence puts it rather than in
    the general haste every ability reads.
    """
    name = "Ultimate Hunter"
    effects = RuneValues(name, entry.get("effects", {}))
    base = effects.number("ultimate_haste")
    per_stack = effects.number("ultimate_haste_per_stack")
    ceiling = effects.number("max_stacks")

    def amount(context: RuneStatContext) -> float:
        return base + per_stack * context.option(name, _HUNTER_STACKS, 0.0)

    return RuneStatGrantEffect(
        rune_name=name,
        stat=RuneStat.ULTIMATE_HASTE,
        amount=amount,
        disclosures=(
            f"{name} grants {base:g} ultimate haste plus {per_stack:g} per "
            f"Bounty Hunter stack, {base + per_stack * ceiling:g} at its "
            f"{ceiling:g}-stack maximum. The fight reads the "
            f"{_HUNTER_STACKS!r} option, whose default is no stacks: a stack "
            "is a takedown against a champion this engine never scores.",
            f"{name} shortens the ultimate's cooldown and nothing else. "
            "The timed scheduler recasts the ultimate on its hasted "
            "cooldown only for modules that certify ULTIMATE_RECASTS; for "
            "every other kit the ultimate is cast exactly once, so there "
            "the grant reaches the stat card and no damage row.",
        ),
    )


#: Domination's utility runes: disposition, the reason that becomes the
#: receipt, and any further half this engine refuses.  A structural zero is a
#: rune with no combat damage in any source; a withheld one has a real number
#: this engine holds no channel for.
_NO_DAMAGE: dict[str, tuple[Disposition, str, tuple[str, ...]]] = {
    "Sixth Sense": (
        Disposition.STRUCTURAL_ZERO,
        "it tracks and reveals enemy wards, which no source prices as damage",
        (),
    ),
    "Grisly Mementos": (
        Disposition.WITHHELD,
        "it grants trinket haste, and the engine reads no trinket — the only "
        "haste it walks is the ability haste that shortens cooldowns",
        (
            "Grisly Mementos grants no ability haste, so nothing in the "
            "fight's cooldowns is understated by withholding it.",
        ),
    ),
    # The cached entry carries ``bonus_health: 1.0``: that is one point of
    # health on a *ward*, not on the holder, and wiring it into the bonus
    # health channel would hand the champion a stat the rune never grants.
    "Deep Ward": (
        Disposition.STRUCTURAL_ZERO,
        "it lengthens deep wards and toughens them by a point of health, and "
        "nothing it touches belongs to the champion the fight prices",
        (),
    ),
    "Treasure Hunter": (
        Disposition.WITHHELD,
        "it pays gold per unique champion takedown, the simulated fight "
        "scores none, and gold is not damage and never joins a total",
        (),
    ),
    "Relentless Hunter": (
        Disposition.STRUCTURAL_ZERO,
        "its bonus movement speed applies only while out of combat, and the "
        "fight prices combat",
        (),
    ),
}


COMPILERS: dict[str, Callable[[Mapping[str, Any]], RuneEffect]] = {
    "Cheap Shot": _compile_cheap_shot,
    "Taste of Blood": _compile_taste_of_blood,
    "Sudden Impact": _compile_sudden_impact,
    "Ultimate Hunter": _compile_ultimate_hunter,
    **{
        name: no_damage_compiler(name, *declaration)
        for name, declaration in _NO_DAMAGE.items()
    },
}

OPTIONS: dict[str, tuple[RuneOption, ...]] = {
    "Sudden Impact": (
        RuneOption(
            key=_DASHED,
            label="Opened with a dash, blink or stealth exit",
            kind=RuneOptionKind.SWITCH,
            default=0.0,
            bounds=(0.0, 1.0),
            disclosure=(
                "1 prices Sudden Impact with the holder opening the fight "
                "with a dash, a blink or an exit from stealth, which arms "
                "its bonus true damage; 0, its default, is the fight in "
                "which none happened."
            ),
        ),
    ),
    "Ultimate Hunter": (
        stack_count_option(
            "Ultimate Hunter",
            _HUNTER_STACKS,
            "Bounty Hunter stacks",
            "How many unique enemy champions Ultimate Hunter's holder has "
            "taken down when the fight opens; the engine simulates one fight "
            "and scores no takedown in it.",
        ),
    ),
}
