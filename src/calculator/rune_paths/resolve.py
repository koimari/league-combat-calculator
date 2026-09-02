"""Resolve's minor runes.

Resolve is the durability path, and durability is the half the pair engine
holds no channel for: it prices one attacker's outgoing damage against one
target, so a shield, a heal, a resistance and a damage reduction all compile
to a refusal carrying the reason. Overgrowth is the exception — its stacks
buy maximum health, which the fight's stat block does read.
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
    RuneProcEffect,
    RuneStat,
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
    bonus_health_ratio = effects.number("bonus_health_ratio")
    shield_ratio = effects.number("shield_amount_ratio")

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


#: The Resolve runes that book no damage: disposition, the reason that
#: becomes the receipt, and any further half this engine refuses.
_NO_DAMAGE: dict[str, tuple[Disposition, str, tuple[str, ...]]] = {
    # Demolish's damage is real and sourced; its target is not a champion.
    "Demolish": (
        Disposition.WITHHELD,
        "its empowered attack damages turrets, and the pair engine prices "
        "one attacker against one champion",
        (
            "Demolish's damage share of the holder's maximum health is "
            "withheld with it; the cache carries its melee and ranged split "
            "unclassified, so no number of it is priced either way.",
        ),
    ),
    "Conditioning": (
        Disposition.WITHHELD,
        "it grants armor and magic resistance after a time, and the pair "
        "engine prices the holder's outgoing damage",
        (),
    ),
    "Second Wind": (
        Disposition.WITHHELD,
        "it regenerates a share of the holder's *missing* health after taking "
        "damage, and the pair engine prices the damage the holder deals: it "
        "carries neither the holder's health nor a stream of damage received",
        (),
    ),
    "Bone Plating": (
        Disposition.WITHHELD,
        "it reduces the damage the holder receives, and the pair engine "
        "prices the damage the holder deals",
        (),
    ),
    "Revitalize": (
        Disposition.WITHHELD,
        "it grants heal and shield power, which every heal and shield the "
        "holder applies now reads — but the rune stat block has no channel "
        "for that stat, so a page's grant would have nowhere to land, and "
        "neither number survives the parse",
        (
            "Revitalize's second half — more healing and shielding on "
            "targets below a share of their maximum health — is withheld "
            "with it, and neither number survives the parse.",
        ),
    ),
    "Unflinching": (
        Disposition.WITHHELD,
        "it grants armor and magic resistance while the holder is crowd "
        "controlled, and the pair engine prices the holder's outgoing damage",
        (),
    ),
}


COMPILERS: dict[str, Callable[[Mapping[str, Any]], RuneEffect]] = {
    "Font of Life": _compile_font_of_life,
    "Overgrowth": _compile_overgrowth,
    "Shield Bash": _compile_shield_bash,
    **{
        name: no_damage_compiler(name, *declaration)
        for name, declaration in _NO_DAMAGE.items()
    },
}

OPTIONS: dict[str, tuple[RuneOption, ...]] = {
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
