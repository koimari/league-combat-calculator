"""Resolve's minor runes.

Resolve is the durability path, and durability is mostly the half the pair
engine holds no channel for: it prices one attacker's outgoing damage against
one target, so a shield, a heal and a damage reduction compile to a refusal
carrying the reason.

Some are not refusals. Overgrowth's stacks buy maximum health, which the
fight's stat block reads. Conditioning's and Unflinching's RESISTANCES land
in the same armor and magic-resistance fold an item's do, and a champion
scaling off bonus armor or bonus magic resistance prices more damage for
them: the grant reaches the fight through the scaling door. It does not reach
a durability one, because the holder's own damage taken carries no resistance
term, and both runes' disclosures say so.
"""

from collections.abc import Callable, Mapping
from typing import Any

from ..ability_spec import Disposition
from ..champions.inputs import champion_stat
from ..item_effects import DamageInputs
from ..rune_effects import (
    RuneEffect,
    RuneHealEffect,
    RuneHealTrigger,
    RuneOption,
    RunePlatingEffect,
    RuneProcEffect,
    RuneRegenerationEffect,
    RuneStat,
    RuneMultiStatGrantEffect,
    RuneOptionKind,
    RuneStatContext,
    RuneStatGrantEffect,
    RuneTrigger,
    RuneValues,
    at_level,
    breakdown_key,
    display_name,
    no_damage_compiler,
    pure_adaptive_type,
    required_leveling,
    stack_count_option,
)

#: Overgrowth's stacks are minions and monsters that died near the holder
#: over a game this one fight does not simulate, so the count is an option
#: whose default is the un-stacked state.
_STACKS = "stacks"


def _stack_threshold(name: str, effects: RuneValues) -> int:
    """The stack count a rune names as its own threshold."""
    threshold = int(effects.number("stack_threshold"))
    if threshold < 1:
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] stack_threshold is {threshold} and "
            "bounds nothing — wiki parse degraded"
        )
    return threshold


def _compile_overgrowth(entry: Mapping[str, Any]) -> RuneStatGrantEffect:
    """Compile Overgrowth: permanent maximum health, one share per stack."""
    name = "Overgrowth"
    effects = RuneValues(name, entry.get("effects", {}))
    per_stack = effects.number("bonus_health")
    threshold = _stack_threshold(name, effects)

    def amount(context: RuneStatContext) -> float:
        return per_stack * context.option(name, _STACKS, 0.0)

    return RuneStatGrantEffect(
        rune_name=name,
        stat=RuneStat.BONUS_HEALTH,
        amount=amount,
        disclosures=(
            f"{name} is priced at the count its {_STACKS!r} option names, "
            f"un-stacked by default and worth {per_stack:g} maximum health "
            "each: its stacks are minions and monsters that died near the "
            "holder over a game this one fight does not simulate, so the "
            "count is asked for rather than inferred.",
            f"{name}'s share of base and bonus health at {threshold} stacks "
            "is withheld: the grant is a percentage of the holder's own "
            "health and a rune stat grant is resolved without it. The rune "
            "stacks indefinitely in game; the option stops at the threshold "
            "its description names.",
        ),
    )


def _compile_font_of_life(entry: Mapping[str, Any]) -> RuneHealEffect:
    """Compile Font of Life: a heal for slowing or immobilizing a champion.

    Both halves it needed now exist and meet here: the impaired stream (read
    from the impairing side — the same reviewed marker Cheap Shot is paid
    off) and the rune heal channel. Its ally half stays withheld twice over,
    because the pair engine prices one attacker and has no ally to heal.
    """
    name = "Font of Life"
    effects = RuneValues(name, entry.get("effects", {}))
    melee = required_leveling(name, effects, "heal_melee_ranged_leveling", 0)
    ranged = required_leveling(name, effects, "heal_melee_ranged_leveling", 1)
    top = RuneValues(name, entry)

    def amount(inputs: DamageInputs) -> float:
        return at_level(melee if inputs.is_melee else ranged, inputs.level)

    return RuneHealEffect(
        rune_name=name,
        trigger=RuneHealTrigger.IMPAIRING_INSTANCES,
        cooldown_seconds=top.number("cooldown"),
        delay_seconds=0.0,
        amount=amount,
        disclosures=(
            f"{name} heals {at_level(melee, 1):g} at level 1 rising to "
            f"{at_level(melee, 18):g} at level 18 for a melee holder "
            f"({at_level(ranged, 1):g} to {at_level(ranged, 18):g} ranged), "
            f"once per {top.number('cooldown'):g}s, on the casts whose own "
            "reviewed parts slow or immobilize the target.",
            f"{name}'s ally half is withheld twice over: the pair engine "
            "prices one attacker and has no ally to heal.",
        ),
    )


def _compile_shield_bash(entry: Mapping[str, Any]) -> RuneProcEffect:
    """Compile Shield Bash: the attack after a self-shield hits harder.

    The one Resolve rune whose damage the pair engine can reach, now that a
    trigger stream watches the ``self_shield_events`` champion modules and
    the Eclipse item family publish. Two of its three terms are priced — the
    level table and its share of the holder's bonus health — and the third,
    a share of the shield's own amount, varies proc by proc while one
    breakdown row prices one number, so it is disclosed rather than
    averaged.
    """
    name = "Shield Bash"
    effects = RuneValues(name, entry.get("effects", {}))
    base_by_level = required_leveling(name, effects)
    bonus_health_ratio, shield_ratio = effects.numbers(
        "bonus_health_ratio", "shield_amount_ratio"
    )

    def raw(inputs: DamageInputs) -> float:
        bonus_health = champion_stat(inputs.champion_stats, "health") - champion_stat(
            inputs.champion_stats, "base_health"
        )
        return at_level(base_by_level, inputs.level) + bonus_health_ratio * max(
            0.0, bonus_health
        )

    return RuneProcEffect(
        rune_name=name,
        breakdown_key=breakdown_key(name),
        display_name=display_name(name),
        stacks_required=1,
        stack_window_seconds=None,
        # No cooldown of its own: each shield arms exactly one attack, and
        # the shield stream is what limits the count.
        cooldown_seconds=0.0,
        proc_delay_seconds=0.0,
        raw_damage=raw,
        damage_type=pure_adaptive_type,
        trigger=RuneTrigger.SELF_SHIELD_EVENTS,
        disclosures=(
            f"{name} empowers the first swing after each self-shield the "
            f"fight publishes, for its level table plus "
            f"{bonus_health_ratio * 100:g}% of the holder's bonus health; a "
            "shield with no attack after it empowers nothing and books "
            "nothing.",
            f"{name}'s third term — {shield_ratio * 100:g}% of the shield's "
            "own amount — is withheld: it differs from shield to shield and "
            "one breakdown row prices one number, so the row is a floor "
            "rather than an average of shields the fight happened to grant.",
        ),
    )


#: Conditioning's clock is a fact about when the fight happens, which the
#: request does not carry, so the minute is an option the way Gathering
#: Storm's is. Its own sentence names the one boundary that matters.
_GAME_MINUTE = "game_minute"
_CONDITIONING_MINUTE = 12.0
#: The game's own length has no cap the cache states; this is the range the
#: option accepts, wide enough to hold any Summoner's Rift game.
_MINUTE_BOUNDS = (0.0, 60.0)


def _compile_conditioning(entry: Mapping[str, Any]) -> RuneStatGrantEffect:
    """Compile Conditioning: bonus resistances once the game is long enough.

    The flat halves land in the holder's own armor and magic resistance, and
    a champion scaling off bonus armor or bonus magic resistance prices more
    damage for them, so they are a stat. The percent half is disclosed rather
    than priced: it multiplies TOTAL resistances, and the stat fold has no
    percent-of-total resist channel for either an item or a rune to use.
    """
    name = "Conditioning"
    effects = RuneValues(name, entry.get("effects", {}))
    armor, magic_resist, total_share = effects.numbers(
        "flat_bonus_armor", "flat_bonus_magic_resistance", "total_resist_percent"
    )

    def amounts(context: RuneStatContext) -> dict[RuneStat, float]:
        minute = context.option(name, _GAME_MINUTE, _MINUTE_BOUNDS[0])
        if minute < _CONDITIONING_MINUTE:
            return {}
        return {RuneStat.ARMOR: armor, RuneStat.MAGIC_RESIST: magic_resist}

    return RuneMultiStatGrantEffect(
        rune_name=name,
        stats=(RuneStat.ARMOR, RuneStat.MAGIC_RESIST),
        amounts=amounts,
        disclosures=(
            f"{name} is priced at the game minute its {_GAME_MINUTE!r} option "
            f"names, minute {_MINUTE_BOUNDS[0]:g} by default, where it grants "
            f"nothing: it arms at minute {_CONDITIONING_MINUTE:g} and the "
            "fight model carries no clock, so the minute is asked for rather "
            "than inferred.",
            f"{name} grants {armor:g} bonus armor and {magic_resist:g} bonus "
            "magic resistance once armed. What reads them is the KIT: a "
            "champion scaling off bonus armor or bonus magic resistance "
            "prices more damage for them. What does not read them is the "
            "holder's own damage taken, which carries no resistance term, so "
            "this is priced through the scaling door and not a durability "
            "one.",
            f"{name}'s further {total_share:.0%} increase to TOTAL armor and "
            "magic resistance is withheld: it multiplies the resistances "
            "rather than adding to them, and the stat fold carries no "
            "percent-of-total resist channel for any source to grant into.",
        ),
    )


#: Unflinching's gate is whether enemies are holding the holder in crowd
#: control, which the fight decides inside its survival walk, after the stat
#: block that would carry the grant is already resolved. So it is a switch
#: with a disclosed default, the shape Absolute Focus's health gate uses.
_CROWD_CONTROLLED = "crowd_controlled"


def _compile_unflinching(entry: Mapping[str, Any]) -> RuneMultiStatGrantEffect:
    """Compile Unflinching: bonus resistances while enemies hold the holder.

    Same channel as Conditioning and the same reading of what it buys: a
    champion scaling off bonus armor or bonus magic resistance prices more
    damage for them, and the holder's own damage taken carries no resistance
    term either way.
    """
    name = "Unflinching"
    effects = RuneValues(name, entry.get("effects", {}))
    armor, magic_resist = effects.numbers(
        "flat_bonus_armor", "flat_bonus_magic_resistance"
    )

    def amounts(context: RuneStatContext) -> dict[RuneStat, float]:
        if not context.option(name, _CROWD_CONTROLLED, 0.0):
            return {}
        return {RuneStat.ARMOR: armor, RuneStat.MAGIC_RESIST: magic_resist}

    return RuneMultiStatGrantEffect(
        rune_name=name,
        stats=(RuneStat.ARMOR, RuneStat.MAGIC_RESIST),
        amounts=amounts,
        disclosures=(
            f"{name} grants {armor:g} bonus armor and {magic_resist:g} bonus "
            f"magic resistance while its {_CROWD_CONTROLLED!r} option says "
            "enemies are holding the holder, and nothing by default. The "
            "fight decides that inside its survival walk, after the stat "
            "block the grant would ride is resolved, so it is asked for "
            "rather than inferred.",
            f"{name} is priced as HELD for the whole window when the option "
            "is on: a rune stat grant is one scalar for the fight, and the "
            "rune's own 2-second lingering tail past the impairment is inside "
            "that reading rather than added to it.",
            f"{name} reaches the fight the way every rune resistance does, "
            "through a kit that scales off bonus armor or bonus magic "
            "resistance; the holder's own damage taken carries no resistance "
            "term, so this buys no durability.",
        ),
    )


def _compile_revitalize(entry: Mapping[str, Any]) -> RuneStatGrantEffect:
    """Compile Revitalize: heal and shield power on every recovery.

    The consumer was always there. ``healing_reduction`` builds one factor
    from ``heal_and_shield_power_percent`` and every heal and shield the
    holder applies is multiplied by it, so an item's grant already reached
    them; the rune stat set simply had no member to land in.
    """
    name = "Revitalize"
    effects = RuneValues(name, entry.get("effects", {}))
    power, low_amp, low_gate = effects.numbers(
        "heal_and_shield_power_percent",
        "low_health_recovery_amp_ratio",
        "low_health_recovery_gate_ratio",
    )

    def amount(context: RuneStatContext) -> float:  # pylint: disable=unused-argument
        return power

    return RuneStatGrantEffect(
        rune_name=name,
        stat=RuneStat.HEAL_AND_SHIELD_POWER,
        amount=amount,
        disclosures=(
            f"{name} grants {power:g}% heal and shield power, which joins the "
            "item and bonus terms in one champion stat, so the single factor "
            "healing_reduction builds amplifies every heal and shield the "
            "holder applies.",
            f"{name}'s second half, a further {low_amp:.0%} on targets below "
            f"{low_gate:.0%} of their maximum health, is withheld: the "
            "recovery channel carries no per-target health gate, and reading "
            "the share as always-on would credit it against a full-health "
            "target it never reaches.",
        ),
    )


#: The Resolve runes that book no damage: disposition, the reason that
#: becomes the receipt, and any further half this engine refuses.
_NO_DAMAGE: dict[str, tuple[Disposition, str, tuple[str, ...]]] = {
    # Demolish's damage is real and sourced; its target is not a champion.
    "Demolish": (
        Disposition.WITHHELD,
        "its empowered attack damages turrets, and the fight's whole target "
        "vocabulary is champion and minion (item_effects.TARGET_CLASSES): "
        "there is no structure class for a turret to be",
        (
            "Demolish's damage share of the holder's maximum health is "
            "withheld with it; the cache carries its melee and ranged split "
            "unclassified, so no number of it is priced either way.",
        ),
    ),
}


def _compile_bone_plating(entry: Mapping[str, Any]) -> RunePlatingEffect:
    """Compile Bone Plating: a flat cut off the next hits the holder takes.

    Its refusal named the direction of a channel, and the direction was
    only half of what was wrong with the fit. The item field it pointed at
    is one number read off a target and applied to every packet; this rune
    arms on a hit, pays a counted few after it, and then waits out a
    cooldown. None of that fits a target field, and all of it fits the
    survival walk, which holds the incoming packets in order with their
    times. So the rune is priced there and the item field is left alone.
    """
    name = "Bone Plating"
    effects = RuneValues(name, entry.get("effects", {}))
    top = RuneValues(name, entry)
    flat_by_level = required_leveling(name, effects)
    hits = int(effects.number("incoming_hits_reduced"))
    window = effects.number("incoming_reduction_window_seconds")
    cooldown = top.number("cooldown")
    if hits < 1 or window <= 0.0 or cooldown <= 0.0:
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] states {hits} hits over {window:g} "
            f"seconds on a {cooldown:g} second cooldown, which takes nothing "
            "off anything — wiki parse degraded"
        )
    return RunePlatingEffect(
        rune_name=name,
        flat_by_level=flat_by_level,
        hits=hits,
        window_seconds=window,
        cooldown_seconds=cooldown,
        disclosures=(
            f"{name} takes {at_level(flat_by_level, 1):g} off each of the "
            f"next {hits} hits at level 1, rising to "
            f"{at_level(flat_by_level, 18):g} at level 18, for {window:g} "
            f"seconds after the holder is hit and then not again for "
            f"{cooldown:g} seconds. The arming hit is not one of the reduced "
            "ones, as in game.",
            f"{name} is priced against every incoming packet the walk holds, "
            "whatever damage type it is and whatever cast authored it, "
            "because the rune reduces true damage too; a packet smaller than "
            "the reduction is taken to zero and not below it.",
            f"{name}'s one enemy is not read: in game the reduced hits must "
            "come from the champion that armed it, and the walk's incoming "
            "stream is one enemy unless the request rosters more. Against "
            f"several this prices the next {hits} hits from any of them, "
            "which is a ceiling.",
        ),
    )


def _compile_second_wind(entry: Mapping[str, Any]) -> RuneRegenerationEffect:
    """Compile Second Wind: a share of missing health, after an incoming hit.

    Its refusal was right about where the blocker was and wrong about how
    far it went. There was no rune trigger for damage TAKEN, and there was
    a lane: the survival walk holds the packets the holder received and
    already arms a regeneration window off one of them for Doran's Shield.
    What the rune vocabulary lacked was a kind that could be armed there,
    and the cache lacked both of the rune's numbers.

    The window is armed once and re-armed only after it has run out. A hit
    inside a running window refreshes it in game and restarts the clock on
    a share of the missing health the fight has grown since, which is more
    than this pays, so the reading is a FLOOR and its receipt says so.
    """
    name = "Second Wind"
    effects = RuneValues(name, entry.get("effects", {}))
    ratio, duration = effects.numbers(
        "missing_health_regen_ratio", "missing_health_regen_duration_seconds"
    )
    if ratio <= 0.0 or duration <= 0.0:
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] states a {ratio:g} share over "
            f"{duration:g} seconds, which regenerates nothing — wiki parse "
            "degraded"
        )
    return RuneRegenerationEffect(
        rune_name=name,
        missing_health_ratio=ratio,
        duration_seconds=duration,
        disclosures=(
            f"{name} regenerates {ratio * 100:g}% of the holder's missing "
            f"health over {duration:g} seconds, armed by the first champion "
            "damage the holder takes that reaches health: damage a shield "
            "absorbs whole arms nothing, which is the same certified hit "
            "Doran's Shield's window waits for.",
            f"{name}'s refresh is not replayed: a hit inside a running "
            "window restarts it in game against the larger missing health "
            "the fight has grown by then, so this reading is a floor. The "
            "window re-arms only once it has run out.",
            f"{name}'s share is priced against the missing health at each "
            "second of the window rather than at the hit that armed it, "
            "because no source states a regeneration cadence: the seconds "
            "decide when the health lands, not how much.",
        ),
    )


COMPILERS: dict[str, Callable[[Mapping[str, Any]], RuneEffect]] = {
    "Conditioning": _compile_conditioning,
    "Revitalize": _compile_revitalize,
    "Unflinching": _compile_unflinching,
    "Font of Life": _compile_font_of_life,
    "Overgrowth": _compile_overgrowth,
    "Shield Bash": _compile_shield_bash,
    "Second Wind": _compile_second_wind,
    "Bone Plating": _compile_bone_plating,
    **{
        name: no_damage_compiler(name, *declaration)
        for name, declaration in _NO_DAMAGE.items()
    },
}

OPTIONS: dict[str, tuple[RuneOption, ...]] = {
    "Conditioning": (
        RuneOption(
            key=_GAME_MINUTE,
            label="Game minute",
            kind=RuneOptionKind.COUNT,
            default=_MINUTE_BOUNDS[0],
            bounds=_MINUTE_BOUNDS,
            disclosure=(
                "Which minute of the game the fight happens in; "
                "Conditioning arms at minute 12 and grants nothing "
                "before it."
            ),
        ),
    ),
    "Unflinching": (
        RuneOption(
            key=_CROWD_CONTROLLED,
            label="Held in crowd control",
            kind=RuneOptionKind.SWITCH,
            default=0.0,
            bounds=(0.0, 1.0),
            disclosure=(
                "1 prices Unflinching with enemies holding the holder in "
                "crowd control, where its resistances are live; 0, its "
                "default, is the rest of the fight."
            ),
        ),
    ),
    "Overgrowth": (
        stack_count_option(
            "Overgrowth",
            _STACKS,
            "Overgrowth stacks",
            "How many Overgrowth stacks the holder has earned; each is worth "
            "its share of maximum health.",
            # Overgrowth stacks indefinitely in game and states no maximum;
            # the option stops at the threshold its description names.
            ceiling_key="stack_threshold",
        ),
    ),
}
