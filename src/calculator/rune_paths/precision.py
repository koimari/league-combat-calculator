"""Precision's minor runes.

Precision is the path that pays for a long game. Row 1 rewards a takedown or
a kill, row 2 grows a stat with a game-long ``Legend`` counter, and row 3
amplifies damage behind a health gate. The pair engine simulates one fight,
so the counter is a declared option defaulting to no stacks (decision 5) and
the row-1 rewards are receipted refusals rather than invented events.

Row 3 is the conditional-damage row. Two of its runes gate on the *target's*
health and are one shape read off the same three cached keys — Coup de Grace
below a share, Cut Down above one. Last Stand gates on the *holder's* health,
which the pair engine does not track, so it is a flat amplifier whose gate is
a declared option.
"""

from typing import Any, Callable, Mapping, NamedTuple

from ..ability_spec import Disposition, ZeroPolicy
from ..rune_effects import (
    AmpCondition,
    RuneAmpContext,
    RuneConditionalAmpEffect,
    RuneEffect,
    RuneFlatAmpEffect,
    RuneNoDamageEffect,
    RuneOption,
    RuneOptionKind,
    RuneStat,
    RuneStatContext,
    RuneStatGrantEffect,
    RuneValues,
    breakdown_key,
    display_name,
    no_damage_compiler,
    rune_effect_value,
)

#: ``Legend`` stacks are earned across a whole game — takedowns, epic
#: monsters, minions — and one simulated fight earns none of them. The count
#: is therefore a declared option (decision 5) whose default is the
#: un-stacked state, never a typical value inferred from the fight.
_LEGEND_STACKS = "legend_stacks"


def _legend_stack_option(rune_name: str) -> RuneOption:
    """The stack-count option one Legend rune declares, bounded by its cache.

    The ceiling is the rune's own ``max_stacks`` — Alacrity and Haste cap at
    ten, Bloodline at fifteen — so the control refuses a count the rune could
    never reach instead of accepting one and quietly clamping it.
    """
    ceiling = rune_effect_value(rune_name, "max_stacks")
    return RuneOption(
        key=_LEGEND_STACKS,
        label="Legend stacks",
        kind=RuneOptionKind.COUNT,
        default=0.0,
        bounds=(0.0, ceiling),
        disclosure=(
            f"How many Legend stacks {rune_name} has banked when the fight "
            f"opens, 0 to {ceiling:g}. 0 is the un-stacked default: the "
            "engine simulates one fight and earns no stacks during it."
        ),
    )


def _compile_legend_alacrity(entry: Mapping[str, Any]) -> RuneStatGrantEffect:
    """Compile Legend: Alacrity: bonus attack speed, a base plus a per-stack step.

    Both halves are stated in one wiki sentence and both come out of the
    cache; the stack count that multiplies the step is the declared option,
    and the grant reaches the fight where every other attack-speed bonus does.
    """
    name = "Legend: Alacrity"
    effects = RuneValues(name, entry.get("effects", {}))
    base = effects.number("attack_speed_percent")
    per_stack = effects.number("attack_speed_percent_per_stack")
    ceiling = effects.number("max_stacks")

    def amount(context: RuneStatContext) -> float:
        return base + per_stack * context.option(name, _LEGEND_STACKS, 0.0)

    return RuneStatGrantEffect(
        rune_name=name,
        stat=RuneStat.ATTACK_SPEED_PERCENT,
        amount=amount,
        disclosures=(
            f"{name} grants {base:g}% bonus attack speed plus {per_stack:g}% "
            f"per Legend stack, {base + per_stack * ceiling:g}% at its "
            f"{ceiling:g}-stack maximum. The fight reads the "
            f"{_LEGEND_STACKS!r} option, whose default is no stacks.",
        ),
    )


def _compile_legend_bloodline(entry: Mapping[str, Any]) -> RuneStatGrantEffect:
    """Compile Legend: Bloodline: the bonus health its maximum stacks grant.

    Life steal is this rune's main half and the engine sums life steal from
    the build's items alone, so it is disclosed rather than estimated. The
    bonus health that arrives with the last stack *is* a channel the engine
    reads, and it is what this grant prices — all of it or none, exactly as
    the rune states it.
    """
    name = "Legend: Bloodline"
    effects = RuneValues(name, entry.get("effects", {}))
    health = effects.number("bonus_health")
    per_stack = effects.number("life_steal_percent_per_stack")
    ceiling = effects.number("max_stacks")

    def amount(context: RuneStatContext) -> float:
        stacks = context.option(name, _LEGEND_STACKS, 0.0)
        return health if stacks >= ceiling else 0.0

    return RuneStatGrantEffect(
        rune_name=name,
        stat=RuneStat.BONUS_HEALTH,
        amount=amount,
        disclosures=(
            f"{name} grants its {health:g} bonus health only at the "
            f"{ceiling:g}-stack maximum; the fight reads the "
            f"{_LEGEND_STACKS!r} option, whose default is no stacks.",
            f"{name}'s life steal ({per_stack:g}% per stack, "
            f"{per_stack * ceiling:g}% at maximum) is withheld: life steal is "
            "summed from the build's items and no rune grants into it.",
        ),
    )


def _compile_legend_haste(entry: Mapping[str, Any]) -> RuneNoDamageEffect:
    """Compile Legend: Haste: basic ability haste with no rune channel to land in.

    The haste is real and the engine does read a ``basic_ability_haste`` stat
    for the Q/W/E cooldowns it walks — but that stat is fed by items, and the
    rune stat channels carry general ability haste, which the ultimate reads
    too. Granting it there would shorten a cooldown this rune does not touch,
    so the number is refused rather than misplaced.
    """
    name = "Legend: Haste"
    effects = RuneValues(name, entry.get("effects", {}))
    per_stack = effects.number("basic_ability_haste_per_stack")
    ceiling = effects.number("max_stacks")
    return RuneNoDamageEffect(
        rune_name=name,
        zero_policy=ZeroPolicy(
            Disposition.WITHHELD,
            f"it grants {per_stack:g} basic ability haste per Legend stack "
            f"({per_stack * ceiling:g} at its {ceiling:g}-stack maximum), and "
            "the rune stat channels carry only general ability haste, which "
            "the ultimate reads as well",
        ),
        disclosures=(
            f"{name} shortens basic-ability cooldowns alone, so a timed "
            "rotation without it is a floor rather than a wrong total.",
        ),
    )


def _target_health_amp(
    name: str, entry: Mapping[str, Any], condition: AmpCondition
) -> RuneConditionalAmpEffect:
    """Compile one target-health-gated amplifier from its three cached keys.

    The gate is the target's *current* health against its maximum, so the
    engine decides per damage instance, walking its ordered ledger with the
    target's health falling by everything already dealt. Nothing about the
    gate is assumed here: the share, the amplifier, and which side of the
    threshold arms it all come out of the cached description, and a
    description stating the other side is refused rather than priced as the
    one the rune is known for.
    """
    effects = RuneValues(name, entry.get("effects", {}))
    stated = AmpCondition(str(effects.value("damage_amp_health_gate")))
    if stated is not condition:
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] states a {stated.value!r} gate and this "
            f"compiler prices the {condition.value!r} one — wiki description "
            "reordered"
        )
    health_ratio = effects.number("damage_amp_health_ratio")
    side = "below" if condition is AmpCondition.TARGET_BELOW else "above"
    return RuneConditionalAmpEffect(
        rune_name=name,
        breakdown_key=breakdown_key(name),
        display_name=display_name(name),
        condition=condition,
        health_ratio=health_ratio,
        amp_ratio=effects.number("damage_amp_ratio"),
        disclosures=(
            f"{name} amplifies exactly the instances that land while the "
            f"target is {side} {health_ratio * 100:g}% of its maximum health, "
            "read off the fight's own ordered ledger; damage the ledger "
            "cannot timestamp is never amplified, so the row is a floor.",
        ),
    )


#: Precision's row-1 rewards: disposition, the reason that becomes the
#: receipt, and any further half this engine refuses. Each pays out on an
#: event one simulated fight between two champions never produces, and two of
#: them pay in health there is no rune channel to receive.
_NO_DAMAGE: dict[str, tuple[Disposition, str, tuple[str, ...]]] = {
    "Absorb Life": (
        Disposition.WITHHELD,
        "it heals on killing a minion or a monster, and the pair engine "
        "prices one champion against one champion — there is nothing to kill, "
        "and no rune healing channel to receive the heal if there were",
        (
            "Absorb Life's heal is missing from the cache as well: its wiki "
            "formula is a piecewise per-level rule the rune parser cannot "
            "read, so the amount is unknown on top of being unpriced.",
        ),
    ),
    "Triumph": (
        Disposition.WITHHELD,
        "its heal and its gold both need a champion takedown, and the "
        "simulated fight scores none",
        (
            "Triumph's heal reads the holder's maximum and missing health, "
            "neither of which the pair engine tracks; its gold is not damage "
            "and would never join a total.",
        ),
    ),
    "Presence of Mind": (
        Disposition.WITHHELD,
        "it restores mana or energy, and the fight's rotation is not gated by "
        "a resource — nothing it refills would buy another cast",
        (
            "Presence of Mind's takedown refund is withheld for a second "
            "reason as well: the simulated fight scores no takedown.",
        ),
    ),
}


def _compile_coup_de_grace(entry: Mapping[str, Any]) -> RuneConditionalAmpEffect:
    """Compile Coup de Grace: more damage to a champion below a health share."""
    return _target_health_amp("Coup de Grace", entry, AmpCondition.TARGET_BELOW)


def _compile_cut_down(entry: Mapping[str, Any]) -> RuneConditionalAmpEffect:
    """Compile Cut Down: more damage to a champion above a health share.

    Coup de Grace's mirror, and the cached description is why it needs no
    kind of its own: the rune once compared the target's *maximum* health
    with the holder's, and now reads the target's current health like its
    row-mates do.
    """
    return _target_health_amp("Cut Down", entry, AmpCondition.TARGET_ABOVE)


#: Last Stand's gate is the holder's own health, and the pair engine prices
#: outgoing damage without tracking it — so the health it reads is an option
#: with a disclosed default (decision 5). The default is full health, which
#: is the un-triggered state: at 100 the rune amplifies nothing, so a fight
#: with it selected is the fight priced without it.
_SELF_HEALTH_PERCENT = "self_health_percent"


class _RampEnd(NamedTuple):
    """One end of a ramping amplifier: its gate, and what it pays there."""

    health: float
    ratio: float


def _ramp_end(name: str, effects: RuneValues, prefix: str) -> _RampEnd:
    """Read one end of a self-health-gated amplifier out of the cache."""
    gate = str(effects.value(f"{prefix}damage_amp_health_gate"))
    if gate != "self_below":
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] states a {gate!r} gate for its "
            f"{prefix or 'first'} end and this compiler prices the one that "
            "arms below a share of the holder's own health — wiki "
            "description reordered"
        )
    return _RampEnd(
        health=effects.number(f"{prefix}damage_amp_health_ratio"),
        ratio=effects.number(f"{prefix}damage_amp_ratio"),
    )


def _compile_last_stand(entry: Mapping[str, Any]) -> RuneFlatAmpEffect:
    """Compile Last Stand: more damage the lower the holder's own health.

    The wiki states the two ends and the direction between them — 5% on
    arming below 60% health, rising with missing health to 11% below 30% —
    and nothing about the shape of the rise. It is read as linear in the
    holder's remaining health, the one reading its two endpoints determine,
    and the rune discloses that.
    """
    name = "Last Stand"
    effects = RuneValues(name, entry.get("effects", {}))
    armed = _ramp_end(name, effects, "")
    peak = _ramp_end(name, effects, "escalated_")
    if peak.ratio <= armed.ratio or peak.health >= armed.health:
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] states {peak.ratio:g} at {peak.health:g} "
            f"maximum health as the escalated end of {armed.ratio:g} at "
            f"{armed.health:g}, which is not a rise toward lower health — "
            "wiki description reordered"
        )
    span = armed.health - peak.health

    def amp_ratio(context: RuneAmpContext) -> float:
        health = context.option(name, _SELF_HEALTH_PERCENT, 100.0) / 100.0
        if health >= armed.health:
            return 0.0
        if health <= peak.health:
            return peak.ratio
        return armed.ratio + (peak.ratio - armed.ratio) * (armed.health - health) / span

    return RuneFlatAmpEffect(
        rune_name=name,
        breakdown_key=breakdown_key(name),
        display_name=display_name(name),
        amp_ratio=amp_ratio,
        disclosures=(
            f"{name} reads the holder's own health, which the pair engine "
            f"does not track: it is priced from the {_SELF_HEALTH_PERCENT!r} "
            "option, whose default of 100 is the un-triggered state.",
            f"{name} pays {armed.ratio * 100:g}% on arming below "
            f"{armed.health * 100:g}% maximum health and "
            f"{peak.ratio * 100:g}% at {peak.health * 100:g}%; between those "
            "two ends the wiki states only that it rises with missing "
            "health, so the rise is read as linear in the holder's health.",
        ),
    )


COMPILERS: dict[str, Callable[[Mapping[str, Any]], RuneEffect]] = {
    **{
        name: no_damage_compiler(name, *declaration)
        for name, declaration in _NO_DAMAGE.items()
    },
    "Legend: Alacrity": _compile_legend_alacrity,
    "Legend: Haste": _compile_legend_haste,
    "Legend: Bloodline": _compile_legend_bloodline,
    "Coup de Grace": _compile_coup_de_grace,
    "Cut Down": _compile_cut_down,
    "Last Stand": _compile_last_stand,
}

OPTIONS: dict[str, tuple[RuneOption, ...]] = {
    **{
        name: (_legend_stack_option(name),)
        for name in ("Legend: Alacrity", "Legend: Bloodline")
    },
    "Last Stand": (
        RuneOption(
            key=_SELF_HEALTH_PERCENT,
            label="Holder's health (% of maximum)",
            kind=RuneOptionKind.COUNT,
            default=100.0,
            bounds=(0.0, 100.0),
            disclosure=(
                "The share of maximum health Last Stand's holder is on for "
                "the fight it prices. 100 is full health, where the rune "
                "amplifies nothing; the amplifier arms and rises below the "
                "shares its description names."
            ),
        ),
    ),
}
