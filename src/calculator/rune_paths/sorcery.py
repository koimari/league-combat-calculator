"""Sorcery's minor runes.

Two of the three shapes a minor rune takes are here: Absolute Focus grants a
stat, Scorch prices a proc. Sorcery's remaining eight runes land beside them.
"""

from typing import Any, Mapping

from ..rune_effects import (
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
    required_level_table,
    required_leveling,
    stated_type,
)

#: Absolute Focus's gate is the holder's own health share, and the pair
#: engine prices outgoing damage without tracking the holder's health — so
#: it is an option with a disclosed default rather than an inferred
#: constant (decision 5). The default is "the gate holds", which is the
#: state the rune is picked for and the one the wiki's own damage tables
#: assume.
_ABOVE_THRESHOLD = "above_health_threshold"


def _compile_absolute_focus(entry: Mapping[str, Any]) -> RuneStatGrantEffect:
    """Compile Absolute Focus: leveled adaptive force while above a health share."""
    name = "Absolute Focus"
    effects = RuneValues(name, entry.get("effects", {}))
    force_by_level = required_level_table(name, effects, "adaptive_force_leveling")
    gate = str(effects.value("self_health_gate"))
    threshold = effects.number("self_health_gate_ratio")
    if gate != "self_above":
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] states a {gate!r} health gate and this "
            "compiler prices the 'above' one — wiki description reordered"
        )

    def amount(context: RuneStatContext) -> float:
        if not context.option(name, _ABOVE_THRESHOLD, 1.0):
            return 0.0
        return at_level(force_by_level, context.level)

    return RuneStatGrantEffect(
        rune_name=name,
        stat=RuneStat.ADAPTIVE_FORCE,
        amount=amount,
        disclosures=(
            f"{name} is priced with the holder above "
            f"{threshold * 100:g}% of maximum health, its default: the pair "
            "engine prices outgoing damage and carries no holder health, so "
            f"the gate is the {_ABOVE_THRESHOLD!r} option, not an inference.",
        ),
    )


def _compile_scorch(entry: Mapping[str, Any]) -> RuneProcEffect:
    """Compile Scorch: the first ability hit each cooldown burns for leveled damage.

    Ability damage sets the target alight; basic attacks never trigger it,
    so the stream is damaging ability casts alone. The burn lands after the
    cached delay and the rune goes on its cached cooldown, which is what
    gates the next one.
    """
    name = "Scorch"
    effects = RuneValues(name, entry.get("effects", {}))
    base_by_level = required_leveling(name, effects)
    top = RuneValues(name, entry)
    delay = effects.number("proc_delay_seconds")

    def raw(inputs) -> float:
        return at_level(base_by_level, inputs.level)

    return RuneProcEffect(
        rune_name=name,
        breakdown_key=breakdown_key(name),
        display_name=display_name(name),
        stacks_required=1,
        stack_window_seconds=None,
        cooldown_seconds=top.number("cooldown"),
        proc_delay_seconds=delay,
        raw_damage=raw,
        damage_type=stated_type("magic"),
        trigger=RuneTrigger.DAMAGING_CASTS,
        disclosures=(
            f"{name} burns on the first damaging ability cast of each "
            f"cooldown window and lands {delay:g}s later; the cache states no "
            "ratios for it, so the damage is its level table alone.",
        ),
    )


COMPILERS = {
    "Absolute Focus": _compile_absolute_focus,
    "Scorch": _compile_scorch,
}

OPTIONS: dict[str, tuple[RuneOption, ...]] = {
    "Absolute Focus": (
        RuneOption(
            key=_ABOVE_THRESHOLD,
            label="Above the health threshold",
            default=1.0,
            bounds=(0.0, 1.0),
            disclosure=(
                "1 prices Absolute Focus with the holder above the health "
                "share its description names; 0 turns the grant off."
            ),
        ),
    ),
}
