"""Domination's minor runes.

Nine runes, and not one of them books damage here. Rows 2 and 3 buy vision,
trinket haste, gold and out-of-combat movement — none of which is damage in
any source. Row 3's three combat runes each need an event this engine's
timeline does not carry: a target already under crowd control (Cheap Shot),
a dash, blink or exit from stealth (Sudden Impact), or a healing channel no
rune reaches (Taste of Blood).

Three of those refusals name a number, so they are compiled rather than
declared: a reader who picks Cheap Shot should be told what the rune would
have dealt, not merely that it dealt nothing.
"""

from typing import Any, Callable, Mapping

from ..ability_spec import Disposition, ZeroPolicy
from ..rune_effects import (
    RuneEffect,
    RuneNoDamageEffect,
    RuneOption,
    RuneOptionKind,
    RuneStat,
    RuneStatContext,
    RuneStatGrantEffect,
    RuneValues,
    at_level,
    no_damage_compiler,
    rune_effect_value,
)

#: The two levels a withheld damage table is quoted at: the fight's floor and
#: the level the wiki's own tables end on.
_QUOTED_LEVELS = (1, 18)


def _level_span(effects: RuneValues) -> tuple[float, float]:
    """One rune's first level table at levels 1 and 18, for its receipt.

    ``required_leveling`` is the door for a table a compiler *prices*, and it
    demands all twenty levels. These tables are quoted inside a refusal, and
    two of them are the wiki's 18-column default rather than twenty rows —
    rejecting them would cost the receipt its numbers to buy a strictness
    that guards no arithmetic. ``at_level`` clamps, so the last row is the
    last row.
    """
    table = [float(value) for value in effects.value("leveling")[0]]
    first, last = _QUOTED_LEVELS
    return at_level(table, first), at_level(table, last)


def _compile_cheap_shot(entry: Mapping[str, Any]) -> RuneNoDamageEffect:
    """Compile Cheap Shot: true damage to an impaired target, with no such stream.

    The engine does know crowd control — a champion module authors a
    reviewed ``cc_kind`` on the parts that apply it — but a rune reaches the
    fight through :class:`~..rune_effects.RuneTrigger`, whose three streams
    count damage instances, basic attacks and damaging casts and none of
    which reads that marker. Pricing this on any of them would book true
    damage against a target nothing had impaired.
    """
    name = "Cheap Shot"
    effects = RuneValues(name, entry.get("effects", {}))
    first, last = _level_span(effects)
    return RuneNoDamageEffect(
        rune_name=name,
        zero_policy=ZeroPolicy(
            Disposition.WITHHELD,
            "its bonus true damage lands only on a target already under one "
            "of the crowd-control kinds it names, and no rune trigger stream "
            "reads the crowd-control marker the fight's damage events carry",
        ),
        disclosures=(
            f"{name} would deal {first:g} bonus true damage at level 1 rising "
            f"to {last:g} at level 18, once per cooldown; the damage is "
            "cached and only the trigger is missing.",
        ),
    )


def _compile_taste_of_blood(entry: Mapping[str, Any]) -> RuneNoDamageEffect:
    """Compile Taste of Blood: a heal on damaging a champion, with no heal channel.

    Its trigger is one the engine walks perfectly well — damaging a champion
    on a cooldown — so what is missing is the destination, not the event: the
    self-healing ledger is fed by champion rules and item packets, and a rune
    has no entry into it.
    """
    name = "Taste of Blood"
    effects = RuneValues(name, entry.get("effects", {}))
    first, last = _level_span(effects)
    bonus_ad_ratio = effects.number("bonus_ad_ratio")
    ap_ratio = effects.number("ap_ratio")
    return RuneNoDamageEffect(
        rune_name=name,
        zero_policy=ZeroPolicy(
            Disposition.WITHHELD,
            "it heals rather than damages, and the self-healing ledger is fed "
            "by champion rules and item packets with no rune entry point",
        ),
        disclosures=(
            f"{name} would heal {first:g} at level 1 rising to {last:g} at "
            f"level 18, plus {bonus_ad_ratio * 100:g}% bonus AD and "
            f"{ap_ratio * 100:g}% AP, once per cooldown; withholding it "
            "understates survival, never the damage total.",
        ),
    )


def _compile_sudden_impact(entry: Mapping[str, Any]) -> RuneNoDamageEffect:
    """Compile Sudden Impact: true damage armed by a dash, blink or stealth exit.

    The fight's timeline carries damage, not movement: no event says a dash
    or a blink happened, and no cast is marked as leaving stealth. A proc
    cannot ask either — the raw-damage inputs a proc reads carry the build,
    the level and the target, and no rune options — so the arming condition
    can be neither read nor declared, and the rune is refused whole.
    """
    name = "Sudden Impact"
    effects = RuneValues(name, entry.get("effects", {}))
    first, last = _level_span(effects)
    return RuneNoDamageEffect(
        rune_name=name,
        zero_policy=ZeroPolicy(
            Disposition.WITHHELD,
            "its bonus true damage is armed by a dash, a blink or an exit "
            "from stealth within four seconds, and the fight's timeline "
            "carries no movement or stealth event to arm it with",
        ),
        disclosures=(
            f"{name} would deal {first:g} bonus true damage at level 1 rising "
            f"to {last:g} at level 18, once per cooldown, for a champion that "
            "opens with a dash, a blink or a stealth exit.",
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
            f"{name} shortens the ultimate's cooldown and nothing else, and "
            "the timed scheduler casts the ultimate exactly once whatever "
            "its cooldown is — so the grant reaches the stat card and no "
            "damage row. Every ultimate-haste source the engine carries is "
            "in that same position; the floor is the scheduler's, not this "
            "rune's.",
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
    "Ultimate Hunter": (
        RuneOption(
            key=_HUNTER_STACKS,
            label="Bounty Hunter stacks",
            kind=RuneOptionKind.COUNT,
            default=0.0,
            bounds=(
                0.0,
                rune_effect_value("Ultimate Hunter", "max_stacks"),
            ),
            disclosure=(
                "How many unique enemy champions Ultimate Hunter's holder "
                "has taken down when the fight opens. 0 is the default: the "
                "engine simulates one fight and scores no takedown in it."
            ),
        ),
    ),
}
