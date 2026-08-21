"""Sorcery's minor runes.

Three of the shapes a minor rune takes are here: Absolute Focus grants a
stat, Scorch prices a proc, Axiom Arcanist amplifies one slot's damage.
Sorcery's remaining seven runes land beside them.
"""

from typing import Any, Mapping

from ..rune_effects import (
    ULTIMATE_SLOT,
    RuneAmpContext,
    RuneFlatAmpEffect,
    RuneOption,
    RuneOptionKind,
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


#: Which of Axiom Arcanist's two rates an ultimate is paid. The rune states
#: one for an area-of-effect ultimate and a higher one for the rest, and no
#: champion contract carries an area-of-effect marker to read it from — so
#: it is an option (decision 5), defaulted to the area-of-effect rate. That
#: default is the lower of the two the rune states: the engine understates
#: this rune rather than inventing damage a single-target reading would.
_AREA_OF_EFFECT_ULTIMATE = "area_of_effect_ultimate"


def _compile_axiom_arcanist(entry: Mapping[str, Any]) -> RuneFlatAmpEffect:
    """Compile Axiom Arcanist: the holder's ultimate hits harder.

    The one rune whose filter is a slot rather than a health share, which is
    why it is the flat kind: the ratio is constant over the fight and the
    condition is which ability dealt the damage. Only the ultimate's own
    ledger rows are amplified — an item proc an ultimate triggered is that
    item's damage, not the ability's.
    """
    name = "Axiom Arcanist"
    effects = RuneValues(name, entry.get("effects", {}))
    single_target = effects.number("ultimate_damage_amp_ratio")
    area = effects.number("ultimate_aoe_damage_amp_ratio")
    if area >= single_target:
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] states {area:g} as the area-of-effect "
            f"reduction of {single_target:g}, which is no reduction — wiki "
            "description reordered"
        )

    def amp_ratio(context: RuneAmpContext) -> float:
        if context.slot != ULTIMATE_SLOT:
            return 0.0
        if context.option(name, _AREA_OF_EFFECT_ULTIMATE, 1.0):
            return area
        return single_target

    return RuneFlatAmpEffect(
        rune_name=name,
        breakdown_key=breakdown_key(name),
        display_name=display_name(name),
        amp_ratio=amp_ratio,
        disclosures=(
            f"{name} amplifies the {ULTIMATE_SLOT} slot's own damage rows and "
            "nothing else; damage an ultimate triggered from an item or "
            "another rune belongs to that source and is not amplified.",
            f"{name} is priced at {area * 100:g}%, its area-of-effect rate: "
            "no champion contract states whether an ultimate is area of "
            f"effect, so the {_AREA_OF_EFFECT_ULTIMATE!r} option carries it "
            f"and its default takes the lower of the rune's two rates "
            f"({single_target * 100:g}% for a single-target ultimate).",
            f"{name}'s ultimate cooldown refund on takedown, and its "
            "amplified healing and shielding, are withheld: the fight has no "
            "takedown and the pair engine prices outgoing damage.",
        ),
    )


COMPILERS = {
    "Absolute Focus": _compile_absolute_focus,
    "Axiom Arcanist": _compile_axiom_arcanist,
    "Scorch": _compile_scorch,
}

OPTIONS: dict[str, tuple[RuneOption, ...]] = {
    "Axiom Arcanist": (
        RuneOption(
            key=_AREA_OF_EFFECT_ULTIMATE,
            label="Ultimate is area of effect",
            kind=RuneOptionKind.SWITCH,
            default=1.0,
            bounds=(0.0, 1.0),
            disclosure=(
                "1 prices Axiom Arcanist at the reduced rate its description "
                "gives area-of-effect ultimates, and is the default because "
                "no champion contract states which an ultimate is; 0 prices "
                "the single-target rate."
            ),
        ),
    ),
    "Absolute Focus": (
        RuneOption(
            key=_ABOVE_THRESHOLD,
            label="Above the health threshold",
            kind=RuneOptionKind.SWITCH,
            default=1.0,
            bounds=(0.0, 1.0),
            disclosure=(
                "1 prices Absolute Focus with the holder above the health "
                "share its description names; 0 turns the grant off."
            ),
        ),
    ),
}
