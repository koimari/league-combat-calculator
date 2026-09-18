"""Sorcery's minor runes.

Every shape a minor rune takes is here: Absolute Focus, Waterwalking and
Gathering Storm grant adaptive force behind an explicit option, Transcendence
and Celerity grant a stat outright, Manaflow Band grants one behind a stack
count the request states, Scorch prices a proc, Axiom Arcanist amplifies one
slot's damage on the flat-amp kind, and the one rune whose halves this engine
holds no channel for compiles to a refusal with the reason.
"""

from collections.abc import Callable, Mapping
from typing import Any

from ..ability_spec import Disposition
from ..rune_effects import (
    ULTIMATE_SLOT,
    RuneAmpContext,
    RuneEffect,
    RuneFlatAmpEffect,
    RuneOption,
    RuneOptionKind,
    RuneProcEffect,
    RuneStat,
    RuneStatContext,
    RuneStatGrantEffect,
    RuneTrigger,
    RuneValues,
    adaptive_force_attack_damage_ratio,
    at_level,
    breakdown_key,
    cached_effects,
    display_name,
    keyed_columns,
    no_damage_compiler,
    option_gated_level_grant,
    required_level_table,
    required_leveling,
    required_pair,
    stated_type,
    threshold_gates,
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

    amount = option_gated_level_grant(name, force_by_level, _ABOVE_THRESHOLD, 1.0)

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


#: Waterwalking's river and Gathering Storm's clock are both facts about
#: where and when the fight happens, and the request carries neither.
_IN_RIVER = "in_river"
_GAME_MINUTE = "game_minute"

#: Manaflow Band's stacks are permanent progress earned one ability at a
#: time over a game the engine simulates no part of, so the count is the
#: request's to state and zero is the un-stacked state a fresh page is in.
_MANAFLOW_STACKS = "manaflow_band_stacks"


def _compile_manaflow_band(entry: Mapping[str, Any]) -> RuneStatGrantEffect:
    """Compile Manaflow Band: maximum mana per banked stack, to its ceiling.

    The old receipt named the gap exactly — "no rune stat channel carries
    mana" — and named what would read it if one did: Muramana and
    Archangel's Staff. Both halves were true, and neither was a missing
    capability. The channel is now a member of the closed stat set, the two
    numbers came out of prose the parser had no rule for, and the grant
    lands in the same pool an item's mana lands in, ahead of the
    conversions that read it.
    """
    name = "Manaflow Band"
    effects = RuneValues(name, entry.get("effects", {}))
    per_stack, cap = effects.numbers("max_mana_per_stack", "max_mana_cap")
    if per_stack <= 0 or cap < per_stack:
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] states {per_stack:g} mana per stack "
            f"against a {cap:g} ceiling, which stacks to nothing — wiki "
            "parse degraded"
        )

    def amount(context: RuneStatContext) -> float:
        stacks = context.option(name, _MANAFLOW_STACKS, 0.0)
        return min(stacks * per_stack, cap)

    return RuneStatGrantEffect(
        rune_name=name,
        stat=RuneStat.MAX_MANA,
        amount=amount,
        disclosures=(
            f"{name} grants {per_stack:g} maximum mana per banked stack up "
            f"to {cap:g}, read from the {_MANAFLOW_STACKS!r} option: a stack "
            "is one ability that has affected an enemy champion, earned over "
            "a game the fight model simulates no part of, so its default is "
            "the un-stacked zero.",
            f"{name}'s mana reaches damage only through an item that reads "
            "it: Manamune and Muramana buy bonus attack damage from maximum "
            "mana and Muramana's Shock prices its rows off the same total, "
            "Archangel's Staff buys ability power from bonus mana. A build "
            "holding none of them sees the stat card move and no damage row "
            "with it.",
            f"{name}'s second half — restoring a share of missing mana every "
            "five seconds once the ceiling is reached — is withheld: the "
            "fight's rotation is not gated by a resource, so nothing it "
            "refills would buy another cast.",
        ),
    )


def _compile_transcendence(entry: Mapping[str, Any]) -> RuneStatGrantEffect:
    """Compile Transcendence: ability haste at the levels the rune names.

    Both halves of each gate are read: the haste and the level that arms
    it. Below the first level the rune grants nothing, which is the state a
    level-1 request is in.
    """
    name = "Transcendence"
    effects = RuneValues(name, entry.get("effects", {}))
    gates = threshold_gates(name, effects, "ability_haste_level_gates")
    granted = ", ".join(f"{bonus:g} at level {level}" for level, bonus in gates)

    def amount(context: RuneStatContext) -> float:
        # float, not int: a published zero's type decides its disposition entry.
        return float(sum(bonus for level, bonus in gates if context.level >= level))

    return RuneStatGrantEffect(
        rune_name=name,
        stat=RuneStat.ABILITY_HASTE,
        amount=amount,
        disclosures=(
            f"{name} grants ability haste {granted}, and nothing below the "
            "first of those levels.",
            f"{name}'s last gate — a takedown refunding a share of the basic "
            "abilities' current cooldowns — is withheld: the fight model has "
            "no takedowns to spend, and the cache carries the level but not "
            "the share.",
        ),
    )


def _compile_celerity(entry: Mapping[str, Any]) -> RuneStatGrantEffect:
    """Compile Celerity: a flat share of bonus movement speed."""
    name = "Celerity"
    effects = RuneValues(name, entry.get("effects", {}))
    percent = effects.number("move_speed_percent")

    def amount(context: RuneStatContext) -> float:
        del context  # unconditional: no level, no gate, no option
        return percent

    return RuneStatGrantEffect(
        rune_name=name,
        stat=RuneStat.MOVE_SPEED_PERCENT,
        amount=amount,
        disclosures=(
            f"{name}'s {percent:g}% bonus movement speed reaches the stat "
            "card and Swiftmarch's conversion of movement speed into "
            "adaptive force, which prices the build's one published "
            "movement speed; no damage row reads movement speed itself.",
            f"{name}'s other half — every other movement-speed bonus made "
            "more effective — is withheld: it multiplies sources the rune "
            "stat block does not own, and the cache carries no share for it.",
        ),
    )


def _compile_waterwalking(entry: Mapping[str, Any]) -> RuneStatGrantEffect:
    """Compile Waterwalking: leveled adaptive force while in the river."""
    name = "Waterwalking"
    effects = RuneValues(name, entry.get("effects", {}))
    force_by_level = required_level_table(name, effects, "adaptive_force_leveling")

    amount = option_gated_level_grant(name, force_by_level, _IN_RIVER, 0.0)

    return RuneStatGrantEffect(
        rune_name=name,
        stat=RuneStat.ADAPTIVE_FORCE,
        amount=amount,
        disclosures=(
            f"{name} is priced wherever its {_IN_RIVER!r} option says the "
            "holder is, out of the river by default: the fight model carries "
            "no terrain, so the river is asked for rather than inferred, and "
            "the grant is nothing until it is set.",
            f"{name}'s river movement speed is withheld: it is a flat grant "
            "and the rune stat channels carry movement speed as a percent.",
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


def _certify_adaptive_rendering(
    name: str, effects: RuneValues, force_by_mark: tuple[float, ...]
) -> None:
    """Certify table 0 is table 1 rendered as attack damage, not a second table.

    Gathering Storm states one grant twice — as the bonus attack damage the
    adaptive force buys and as the ability power it buys — and only sentence
    order says which is which. ``Template:Adaptive``'s own conversion decides
    it without pinning either table, so a patch may move both freely and a
    reworded description still fails loudly.
    """
    rendered = keyed_columns(name, effects, "leveling", 0)
    ratio = adaptive_force_attack_damage_ratio()
    if len(rendered) != len(force_by_mark) or any(
        abs(attack_damage - ratio * force) > 1e-6
        for attack_damage, force in zip(rendered, force_by_mark, strict=False)
    ):
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] leveling is not the attack-damage "
            "rendering of the adaptive force followed by the force itself — "
            "wiki parse degraded or description reordered"
        )


def _minute_span(name: str, effects: RuneValues) -> tuple[float, float]:
    """The first and last game minute a rune's own table is keyed by."""
    first, last = required_pair(name, effects, "minutes_range")
    if last <= first:
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] minutes_range runs {first:g} to {last:g} "
            "and states no span — wiki parse degraded"
        )
    return first, last


#: Gathering Storm's option is bounded by its own table: the minutes it
#: states, no further. Read at import because bounds are declared before
#: any request exists.
_STORM_MINUTES = _minute_span("Gathering Storm", cached_effects("Gathering Storm"))


def _compile_gathering_storm(entry: Mapping[str, Any]) -> RuneStatGrantEffect:
    """Compile Gathering Storm: adaptive force by how long the game has run.

    The rune's table is keyed by game minute, one column per ten of them,
    and the fight model carries no clock — so the minute is an option whose
    default is the table's own first column, where the rune grants nothing.
    """
    name = "Gathering Storm"
    effects = RuneValues(name, entry.get("effects", {}))
    force_by_mark = keyed_columns(name, effects, "leveling", 1)
    _certify_adaptive_rendering(name, effects, force_by_mark)
    first_minute, last_minute = _minute_span(name, effects)
    minutes_per_mark = (last_minute - first_minute) / (len(force_by_mark) - 1)

    def amount(context: RuneStatContext) -> float:
        minute = context.option(name, _GAME_MINUTE, first_minute)
        marks = int((minute - first_minute) // minutes_per_mark)
        return at_level(force_by_mark, marks + 1)

    return RuneStatGrantEffect(
        rune_name=name,
        stat=RuneStat.ADAPTIVE_FORCE,
        amount=amount,
        disclosures=(
            f"{name} is priced at the game minute its {_GAME_MINUTE!r} "
            f"option names, minute {first_minute:g} by default — where it "
            "grants nothing: the fight model carries no clock, so the minute "
            "is asked for rather than inferred.",
            f"{name} grows every {minutes_per_mark:g} minutes and its table "
            f"ends at minute {last_minute:g}; the rune keeps growing past it "
            "in game, and minutes beyond the table are refused by the option "
            "rather than extrapolated.",
        ),
    )


#: The Sorcery runes that book no damage: disposition, the reason that
#: becomes the receipt, and any further half this engine refuses.
_NO_DAMAGE: dict[str, tuple[Disposition, str, tuple[str, ...]]] = {
    # Nimbus Cloak's table is keyed by summoner-spell cooldown, not level —
    # and the fight casts no summoner spells at all, so no column of it is
    # ever reached.
    "Nimbus Cloak": (
        Disposition.WITHHELD,
        "its movement speed follows a summoner spell, and the fight model "
        "casts none",
        (
            "Nimbus Cloak deals no damage of its own, so nothing in the "
            "damage total is understated by withholding it.",
        ),
    ),
}


COMPILERS: dict[str, Callable[[Mapping[str, Any]], RuneEffect]] = {
    "Absolute Focus": _compile_absolute_focus,
    "Axiom Arcanist": _compile_axiom_arcanist,
    "Celerity": _compile_celerity,
    "Gathering Storm": _compile_gathering_storm,
    "Manaflow Band": _compile_manaflow_band,
    "Scorch": _compile_scorch,
    "Transcendence": _compile_transcendence,
    "Waterwalking": _compile_waterwalking,
    **{
        name: no_damage_compiler(name, *declaration)
        for name, declaration in _NO_DAMAGE.items()
    },
}


def _manaflow_stack_ceiling() -> float:
    """How many stacks Manaflow Band's own ceiling allows, from the cache.

    The wiki states the ceiling in mana and the step in mana; the count is
    their quotient, which is a reading of the two rather than a constant of
    its own. A ceiling that is not a whole number of steps would mean one
    of the two numbers has drifted, so it is refused rather than rounded.
    """
    name = "Manaflow Band"
    per_stack, cap = cached_effects(name).numbers("max_mana_per_stack", "max_mana_cap")
    stacks = cap / per_stack
    if stacks != int(stacks):
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] caps at {cap:g} mana in steps of "
            f"{per_stack:g}, which is not a whole number of stacks — wiki "
            "parse degraded"
        )
    return float(int(stacks))


OPTIONS: dict[str, tuple[RuneOption, ...]] = {
    "Manaflow Band": (
        RuneOption(
            key=_MANAFLOW_STACKS,
            label="Manaflow Band stacks",
            kind=RuneOptionKind.COUNT,
            default=0.0,
            bounds=(0.0, _manaflow_stack_ceiling()),
            disclosure=(
                "How many stacks Manaflow Band has banked when the fight "
                "opens; one is one ability that has affected an enemy "
                "champion, and the engine simulates one fight and banks none "
                f"during it. The count runs 0 to {_manaflow_stack_ceiling():g}"
                ", 0 by default."
            ),
        ),
    ),
    "Gathering Storm": (
        RuneOption(
            key=_GAME_MINUTE,
            label="Game minute",
            kind=RuneOptionKind.COUNT,
            default=_STORM_MINUTES[0],
            bounds=_STORM_MINUTES,
            disclosure=(
                "Which minute of the game the fight happens in; Gathering "
                "Storm grows one step every ten of them and grants nothing "
                "at its default."
            ),
        ),
    ),
    "Waterwalking": (
        RuneOption(
            key=_IN_RIVER,
            label="In the river",
            kind=RuneOptionKind.SWITCH,
            default=0.0,
            bounds=(0.0, 1.0),
            disclosure=(
                "1 prices Waterwalking with the holder in the river, where "
                "its adaptive force is live; 0, its default, is the rest of "
                "the map."
            ),
        ),
    ),
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
