"""Resolve's minor runes.

Resolve is the durability path, and durability is the half the pair engine
holds no channel for: it prices one attacker's outgoing damage against one
target, so a shield, a heal, a resistance and a damage reduction all compile
to a refusal carrying the reason. Overgrowth is the exception — its stacks
buy maximum health, which the fight's stat block does read.
"""

from typing import Any, Callable, Mapping

from ..ability_spec import Disposition
from ..rune_effects import (
    RUNE_EFFECTS,
    RuneEffect,
    RuneOption,
    RuneOptionKind,
    RuneStat,
    RuneStatContext,
    RuneStatGrantEffect,
    RuneValues,
    no_damage_compiler,
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


def _cached_effects(name: str) -> RuneValues:
    """One rune's parsed effects block, for a declaration read at import.

    A compiler reads the record it is handed; an option's *bounds* are
    declared before any request exists, and the rune's own threshold is what
    bounds them — so the declaration reads the cache through the same
    fail-loud door.
    """
    return RuneValues(name, RUNE_EFFECTS.get(name, {}).get("effects", {}))


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
    "Font of Life": (
        Disposition.WITHHELD,
        "it heals the holder and the nearest wounded ally when the holder "
        "impairs a champion, and the engine has no rune healing channel",
        (
            "Font of Life's ally half is withheld twice over: the pair "
            "engine prices one attacker and has no ally to heal.",
        ),
    ),
    # The shield that arms Shield Bash is on the ledger — champion self
    # shields publish ``self_shield_events`` — but no rune trigger stream
    # reads it, and two of the three terms of its damage never parsed.
    "Shield Bash": (
        Disposition.WITHHELD,
        "its empowered attack is armed by the holder gaining a shield, and "
        "no rune trigger stream watches the fight's self-shield events",
        (
            "Shield Bash's damage would be understated even with the "
            "trigger: the cache carries its level table but neither its "
            "share of bonus health nor its share of the shield's own amount.",
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
        "it regenerates a share of the holder's missing health after taking "
        "damage, and the engine has no rune healing channel",
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
        "it increases the holder's outgoing healing and shielding, and the "
        "engine has no rune healing channel",
        (),
    ),
    "Unflinching": (
        Disposition.WITHHELD,
        "it grants armor and magic resistance while the holder is crowd "
        "controlled, and the pair engine prices the holder's outgoing damage",
        (),
    ),
}


COMPILERS: dict[str, Callable[[Mapping[str, Any]], RuneEffect]] = {
    "Overgrowth": _compile_overgrowth,
    **{
        name: no_damage_compiler(name, *declaration)
        for name, declaration in _NO_DAMAGE.items()
    },
}

OPTIONS: dict[str, tuple[RuneOption, ...]] = {
    "Overgrowth": (
        RuneOption(
            key=_STACKS,
            label="Overgrowth stacks",
            kind=RuneOptionKind.COUNT,
            default=0.0,
            bounds=(
                0.0,
                float(_stack_threshold("Overgrowth", _cached_effects("Overgrowth"))),
            ),
            disclosure=(
                "How many Overgrowth stacks the holder has earned; each is "
                "worth its share of maximum health, and the default is none."
            ),
        ),
    ),
}
