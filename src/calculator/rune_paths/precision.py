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
from ..item_effects import DamageInputs
from ..rune_effects import (
    RuneAmpContext,
    RuneConditionalAmpEffect,
    RuneEffect,
    RuneFlatAmpEffect,
    RuneHealEffect,
    RuneHealTrigger,
    RuneMultiStatGrantEffect,
    RuneNoDamageEffect,
    RuneOption,
    RuneOptionKind,
    RuneStat,
    RuneStatContext,
    RuneStatGrantEffect,
    RuneValues,
    at_level,
    breakdown_key,
    display_name,
    no_damage_compiler,
    required_leveling,
    stack_count_option,
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
    return stack_count_option(
        rune_name,
        _LEGEND_STACKS,
        "Legend stacks",
        f"How many Legend stacks {rune_name} has banked when the fight "
        "opens; the engine simulates one fight and earns no stacks during it.",
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


def _compile_legend_bloodline(entry: Mapping[str, Any]) -> RuneMultiStatGrantEffect:
    """Compile Legend: Bloodline: life steal per stack, bonus health at the last.

    Both halves off one stack count, in one declaration, because that count
    is what could otherwise drift between them. The life steal lands in the
    channel the fight's own life-steal walk reads, so it becomes timed heal
    packets off the holder's physical attacks exactly as an item's does; the
    bonus health arrives whole or not at all, as the rune states it.
    """
    name = "Legend: Bloodline"
    effects = RuneValues(name, entry.get("effects", {}))
    health = effects.number("bonus_health")
    per_stack = effects.number("life_steal_percent_per_stack")
    ceiling = effects.number("max_stacks")

    def amounts(context: RuneStatContext) -> Mapping[RuneStat, float]:
        stacks = context.option(name, _LEGEND_STACKS, 0.0)
        return {
            RuneStat.LIFESTEAL_PERCENT: per_stack * stacks,
            RuneStat.BONUS_HEALTH: health if stacks >= ceiling else 0.0,
        }

    return RuneMultiStatGrantEffect(
        rune_name=name,
        stats=(RuneStat.LIFESTEAL_PERCENT, RuneStat.BONUS_HEALTH),
        amounts=amounts,
        disclosures=(
            f"{name} grants {per_stack:g}% life steal per Legend stack "
            f"({per_stack * ceiling:g}% at its {ceiling:g}-stack maximum), "
            "which the fight's life-steal walk turns into heal packets off "
            "the holder's own physical attack events.",
            f"{name} grants its {health:g} bonus health only at the "
            f"{ceiling:g}-stack maximum; the fight reads the "
            f"{_LEGEND_STACKS!r} option for both halves, and its default is "
            "no stacks.",
        ),
    )


def _compile_legend_haste(entry: Mapping[str, Any]) -> RuneStatGrantEffect:
    """Compile Legend: Haste: basic ability haste, one step per Legend stack.

    Its own channel, not the general one: the engine reads a
    ``basic_ability_haste`` stat for the Q/W/E cooldowns it walks and a
    separate ultimate haste for R, and granting this rune's haste into the
    general channel would shorten a cooldown it does not touch.
    """
    name = "Legend: Haste"
    effects = RuneValues(name, entry.get("effects", {}))
    per_stack = effects.number("basic_ability_haste_per_stack")
    ceiling = effects.number("max_stacks")

    def amount(context: RuneStatContext) -> float:
        return per_stack * context.option(name, _LEGEND_STACKS, 0.0)

    return RuneStatGrantEffect(
        rune_name=name,
        stat=RuneStat.BASIC_ABILITY_HASTE,
        amount=amount,
        disclosures=(
            f"{name} grants {per_stack:g} basic ability haste per Legend "
            f"stack, {per_stack * ceiling:g} at its {ceiling:g}-stack "
            f"maximum; the fight reads the {_LEGEND_STACKS!r} option, whose "
            "default is no stacks.",
            f"{name} shortens the basic abilities' cooldowns and nothing "
            "else, so it moves a number only in a fight long enough to "
            "recast one: a single rotation casts each ability once.",
        ),
    )


def _target_health_amp(name: str, entry: Mapping[str, Any]) -> RuneConditionalAmpEffect:
    """Compile one target-health-gated amplifier: the rune's identity, no more.

    Its share, its amplifier and which side of the threshold arms it are the
    amp chain's ``TARGET_HEALTH_GATE`` declaration.
    """
    del entry  # every number this rune prices is the chain's declaration
    return RuneConditionalAmpEffect(
        rune_name=name,
        breakdown_key=breakdown_key(name),
        display_name=display_name(name),
    )


#: Precision's row-1 rewards: disposition, the reason that becomes the
#: receipt, and any further half this engine refuses. Each pays out on an
#: event one simulated fight between two champions never produces, and two of
#: them pay in health there is no rune channel to receive.
_NO_DAMAGE: dict[str, tuple[Disposition, str, tuple[str, ...]]] = {
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


def _compile_absorb_life(entry: Mapping[str, Any]) -> RuneNoDamageEffect:
    """Compile Absorb Life: a heal on a kill the pair engine has nothing to make.

    Its amount is known — the wiki's piecewise progression parses — and its
    destination now exists, so what is left is the event: the fight is one
    champion against one champion, and a minion kill has neither an actor to
    kill nor a timestamp to place the heal at. A kill count would be a
    number with no moment, and a heal packet without a moment is the guessed
    timestamp the ledger refuses everywhere else.
    """
    name = "Absorb Life"
    effects = RuneValues(name, entry.get("effects", {}))
    by_level = required_leveling(name, effects)
    return RuneNoDamageEffect(
        rune_name=name,
        zero_policy=ZeroPolicy(
            Disposition.WITHHELD,
            "it heals on killing a minion or a monster, and the pair engine "
            "prices one champion against one champion — there is nothing to "
            "kill",
        ),
        disclosures=(
            f"{name} would heal {at_level(by_level, 1):g} at level 1 rising "
            f"to {at_level(by_level, 18):g} at level 18 and "
            f"{at_level(by_level, 20):g} at level 20, per kill; the amount is "
            "cached and only the kill is missing.",
            f"{name}'s heal has nowhere to land in time even as a count: a "
            "kill carries no timestamp, and the self-healing ledger takes "
            "packets with moments rather than totals.",
        ),
    )


def _compile_triumph(entry: Mapping[str, Any]) -> RuneHealEffect:
    """Compile Triumph: a share of maximum health on a champion takedown.

    Its takedown is not an option and not an invention: the fight scores one
    exactly when the target ends at or below zero health, and a fight the
    target survives pays nothing. What the pair engine still cannot supply
    is the *holder's* missing health, so that half of the heal is disclosed
    rather than estimated — and the gold is not damage and never joins a
    total.
    """
    name = "Triumph"
    effects = RuneValues(name, entry.get("effects", {}))
    max_health_ratio = effects.number("max_health_heal_ratio")
    missing_health_ratio = effects.number("missing_health_heal_ratio")
    gold = effects.number("flat_gold")

    def amount(inputs: DamageInputs) -> float:
        return max_health_ratio * inputs.champion_stats.get("health", 0.0)

    return RuneHealEffect(
        rune_name=name,
        trigger=RuneHealTrigger.TAKEDOWNS,
        # Every takedown pays; nothing gates a second one but a second kill.
        cooldown_seconds=0.0,
        delay_seconds=effects.number("proc_delay_seconds"),
        amount=amount,
        disclosures=(
            f"{name} heals {max_health_ratio * 100:g}% of the holder's "
            "maximum health on a takedown the fight actually scored — the "
            "target ending at or below zero health — and nothing on a fight "
            "the target survives. The takedown is dated at the window's last "
            "damage instance, which is at or after the one that crossed "
            "zero, so the heal arrives no earlier than it should.",
            f"{name}'s other half ({missing_health_ratio * 100:g}% of the "
            "holder's *missing* health) is withheld: the pair engine prices "
            f"outgoing damage and carries no holder health. Its {gold:g} gold "
            "is not damage and never joins a total.",
        ),
    )


def _compile_coup_de_grace(entry: Mapping[str, Any]) -> RuneConditionalAmpEffect:
    """Compile Coup de Grace: more damage to a champion below a health share."""
    return _target_health_amp("Coup de Grace", entry)


def _compile_cut_down(entry: Mapping[str, Any]) -> RuneConditionalAmpEffect:
    """Compile Cut Down: more damage to a champion above a health share."""
    return _target_health_amp("Cut Down", entry)


#: Last Stand's gate is the holder's own health, and the pair engine prices
#: outgoing damage without tracking it — so the health it reads is an option
#: with a disclosed default (decision 5). The default is full health, which
#: is the un-triggered state: at 100 the rune amplifies nothing, so a fight
#: with it selected is the fight priced without it.
_SELF_HEALTH_PERCENT = "self_health_percent"
#: The un-triggered default: full health, where Last Stand amplifies nothing.
_FULL_HEALTH_PERCENT = 100.0


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
        health = (
            context.option(name, _SELF_HEALTH_PERCENT, _FULL_HEALTH_PERCENT) / 100.0
        )
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
    "Absorb Life": _compile_absorb_life,
    "Triumph": _compile_triumph,
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
        for name in ("Legend: Alacrity", "Legend: Bloodline", "Legend: Haste")
    },
    "Last Stand": (
        RuneOption(
            key=_SELF_HEALTH_PERCENT,
            label="Holder's health (% of maximum)",
            kind=RuneOptionKind.COUNT,
            default=_FULL_HEALTH_PERCENT,
            bounds=(0.0, _FULL_HEALTH_PERCENT),
            disclosure=(
                "The share of maximum health Last Stand's holder is on for "
                "the fight it prices. 100 is full health, where the rune "
                "amplifies nothing; the amplifier arms and rises below the "
                "shares its description names."
            ),
        ),
    ),
}
