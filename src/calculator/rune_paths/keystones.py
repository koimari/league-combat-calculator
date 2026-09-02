"""The keystones' compilers — row 0 of every path, in one table.

Decision 3 puts a rune's compiler one file per path; the keystones are the
declared exception. They share the ``_UNPRICED_KEYSTONES`` receipt table and
the ``_KEYSTONE_COMPILERS`` roster ``rune_effects.resolve_rune`` dispatches
on, and splitting them five ways would copy both into five files for two
runes each. So the sixteen compiled keystones live here, in the same two
mappings a path module declares — ``COMPILERS`` and (for these) ``NO_DAMAGE``,
the damageless table it builds compilers from.

Every number comes out of the cached ``data/runes.json`` record through the
typed accessors ``rune_effects`` exports, and a missing key raises naming the
rune and the key (CLAUDE.md rule 5). The effect *types* these compile into,
the accessors they read through and the resolver that dispatches on this
table all stay in ``rune_effects``: this module is the compilation and
nothing else.
"""

from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any

from ..ability_spec import Disposition, ZeroPolicy
from ..champions.inputs import champion_stat
from ..item_effects import DamageInputs
from ..rune_effects import (
    KeystoneAeryEffect,
    KeystoneAftershockEffect,
    KeystoneConquerorEffect,
    KeystoneDarkHarvestEffect,
    KeystoneDeathfireEffect,
    KeystoneFleetEffect,
    KeystoneGlacialEffect,
    KeystoneGraspEffect,
    KeystoneGuardianEffect,
    KeystoneHailOfBladesEffect,
    KeystoneLethalTempoEffect,
    KeystoneStormraiderEffect,
    RuneAbilityProcEffect,
    RuneEffect,
    RuneProcAmpEffect,
    RuneProcEffect,
    RuneValues,
    RuneWindowAmpEffect,
    at_level,
    breakdown_key,
    display_name,
    no_damage_compiler,
    pure_adaptive_type,
    ratio_adaptive_type,
    required_cooldown_by_level,
    required_level_table,
    required_leveling,
    required_pair,
    zero_receipts,
)

#: What a dedicated keystone publishes when a fight books it no row: the
#: disposition, the reason that becomes the receipt, and any further half
#: this engine refuses.  Their values are all sourced and compiled — this
#: says only what *this* fight could not do with them, which is why it
#: lives beside the compilers rather than in ``_NO_DAMAGE_KEYSTONES``.
_UNPRICED_KEYSTONES: Mapping[str, tuple[Disposition, str, tuple[str, ...]]] = (
    MappingProxyType(
        {
            "Glacial Augment": (
                Disposition.STRUCTURAL_ZERO,
                "its zones slow, and the damage reduction they apply protects "
                "the holder's allies while explicitly excluding the holder",
                (),
            ),
            "Stormraider's Surge": (
                Disposition.STRUCTURAL_ZERO,
                "it grants movement speed and slow resist, neither of which "
                "the engine's damage model reads",
                (
                    "Stormraider's Surge's zero is exact only while the "
                    "holder owns no Swiftmarch, whose passive converts "
                    "movement speed into adaptive force "
                    "(item_effects.swiftmarch_adaptive_force); that coupling "
                    "is disclosed, not modeled.",
                ),
            ),
            "Guardian": (
                Disposition.WITHHELD,
                "it shields the holder or a guarded ally against incoming "
                "damage, and this fight priced no shield for it",
                (),
            ),
            "Aftershock": (
                Disposition.WITHHELD,
                "its shockwave fires only after the holder immobilizes a "
                "champion, and no reviewed crowd-control event landed in "
                "this fight",
                (
                    "Aftershock's bonus resistances are withheld with it and "
                    "are defensive besides: the pair engine prices outgoing "
                    "damage.",
                ),
            ),
            "Dark Harvest": (
                Disposition.WITHHELD,
                "its reap fires only against a champion below a share of "
                "maximum health, and the target never fell below it in this "
                "fight",
                (
                    "Dark Harvest's soul count is unknowable in one fight and "
                    "is priced at the souls the request declares.",
                ),
            ),
        }
    )
)


def _unpriced_receipts(name: str) -> tuple[str, ...]:
    """One keystone's no-row receipt, or none when it always books."""
    declaration = _UNPRICED_KEYSTONES.get(name)
    if declaration is None:
        return ()
    disposition, reason, disclosures = declaration
    return zero_receipts(name, ZeroPolicy(disposition, reason), disclosures)


def _compile_electrocute(entry: Mapping[str, Any]) -> RuneProcEffect:
    """Compile Electrocute: 3 stacks in 3s strike for leveled adaptive damage."""
    name = "Electrocute"
    effects = RuneValues(name, entry.get("effects", {}))
    base_by_level = required_leveling(name, effects)
    bonus_ad_ratio = effects.number("bonus_ad_ratio")
    ap_ratio = effects.number("ap_ratio")
    top = RuneValues(name, entry)

    def raw(inputs: DamageInputs) -> float:
        stats = inputs.champion_stats
        return (
            at_level(base_by_level, inputs.level)
            + bonus_ad_ratio * champion_stat(stats, "bonus_attack_damage")
            + ap_ratio * champion_stat(stats, "ability_power")
        )

    return RuneProcEffect(
        rune_name=name,
        breakdown_key=breakdown_key(name),
        display_name=display_name(name),
        stacks_required=int(effects.number("stacks_required")),
        stack_window_seconds=effects.number("stack_window_seconds"),
        cooldown_seconds=top.number("cooldown"),
        proc_delay_seconds=effects.number("proc_delay_seconds"),
        raw_damage=raw,
        damage_type=ratio_adaptive_type(bonus_ad_ratio, ap_ratio),
    )


def _compile_first_strike(entry: Mapping[str, Any]) -> RuneWindowAmpEffect:
    """Compile First Strike: 7% bonus true damage in a 3s opening window."""
    name = "First Strike"
    effects = RuneValues(name, entry.get("effects", {}))
    melee_ratio, ranged_ratio = required_pair(name, effects, "gold_conversion_ratios")
    return RuneWindowAmpEffect(
        rune_name=name,
        breakdown_key=breakdown_key(name),
        display_name=display_name(name),
        activation_gold=effects.number("flat_gold"),
        gold_conversion_melee=melee_ratio,
        gold_conversion_ranged=ranged_ratio,
    )


def _compile_press_the_attack(entry: Mapping[str, Any]) -> RuneProcAmpEffect:
    """Compile Press the Attack: 3 autos proc leveled damage plus a lasting amp."""
    name = "Press the Attack"
    effects = RuneValues(name, entry.get("effects", {}))
    base_by_level = required_leveling(name, effects)
    top = RuneValues(name, entry)

    def raw(inputs: DamageInputs) -> float:
        return at_level(base_by_level, inputs.level)

    return RuneProcAmpEffect(
        rune_name=name,
        breakdown_key=breakdown_key(name),
        display_name=display_name(name),
        stacks_required=int(effects.number("max_stacks")),
        stack_duration_seconds=effects.number("stack_duration_seconds"),
        cooldown_seconds=top.number("cooldown"),
        raw_damage=raw,
        damage_type=pure_adaptive_type,
    )


# Modeling assumption, not a wiki value: how far the average comet flies
# before landing. The wiki's damage table spans 0-750 units; 375 is a
# mid-range poke distance and sits exactly halfway up the table (+50%).
ARCANE_COMET_ASSUMED_TRAVEL_DISTANCE = 375.0


def _distance_amp_ratio(
    name: str, scaling: Mapping[str, Any], distance: float
) -> float:
    """Interpolate a distance-keyed percent table at one travel distance.

    The table's values are evenly spaced across ``distance_range``;
    distances beyond the span clamp to its ends.
    """
    values = [float(value) for value in scaling["values"]]
    span_start, span_end = (float(value) for value in scaling["distance_range"])
    if len(values) < 2 or span_end <= span_start:
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] distance_scaling is degenerate — "
            "wiki parse degraded; check rune_parser and data/runes.json"
        )
    fraction = min(1.0, max(0.0, (distance - span_start) / (span_end - span_start)))
    position = fraction * (len(values) - 1)
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    percent = values[lower] + (values[upper] - values[lower]) * (position - lower)
    return percent / 100.0


def _certify_comet_leveling_order(
    name: str,
    effects: "RuneValues",
    base_by_level: list[float],
    scaling: Mapping[str, Any],
) -> None:
    """Certify leveling[0] is the minimum-damage table, not the max-range one.

    The comet is the first rune with two level tables, chosen by sentence
    order — a reworded wiki description leading with the max-range table
    would silently double every proc. The wiki prices maximum-range damage
    at exactly (1 + full amp) × minimum, which also certifies folding one
    multiplier over base and ratios together.
    """
    leveling = effects.value("leveling")
    span_end = float(scaling["distance_range"][1])
    full_amp = _distance_amp_ratio(name, scaling, span_end)
    max_by_level = [float(value) for value in leveling[1]] if len(leveling) > 1 else []
    if len(max_by_level) != len(base_by_level) or any(
        abs(max_value - base_value * (1.0 + full_amp)) > 1e-6
        for base_value, max_value in zip(base_by_level, max_by_level, strict=False)
    ):
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] leveling tables are not minimum then "
            "maximum-range damage (max = min × (1 + full amp)) — wiki parse "
            "degraded or description reordered; check data/runes.json"
        )


def _compile_arcane_comet(entry: Mapping[str, Any]) -> RuneAbilityProcEffect:
    """Compile Arcane Comet: ability casts hurl a leveled adaptive comet.

    The wiki prices the comet as a minimum-damage formula amplified by
    travel distance (up to +100% at 750 units); base and ratios grow
    together, so one multiplier at the assumed distance covers both.
    """
    name = "Arcane Comet"
    effects = RuneValues(name, entry.get("effects", {}))
    base_by_level = required_leveling(name, effects)
    bonus_ad_ratio = effects.number("bonus_ad_ratio")
    ap_ratio = effects.number("ap_ratio")
    scaling = effects.value("distance_scaling")
    amp_ratio = _distance_amp_ratio(name, scaling, ARCANE_COMET_ASSUMED_TRAVEL_DISTANCE)
    _certify_comet_leveling_order(name, effects, base_by_level, scaling)

    def raw(inputs: DamageInputs) -> float:
        stats = inputs.champion_stats
        return (
            at_level(base_by_level, inputs.level)
            + bonus_ad_ratio * champion_stat(stats, "bonus_attack_damage")
            + ap_ratio * champion_stat(stats, "ability_power")
        ) * (1.0 + amp_ratio)

    return RuneAbilityProcEffect(
        rune_name=name,
        breakdown_key=breakdown_key(name),
        display_name=display_name(name),
        cooldown_by_level=required_cooldown_by_level(name, entry),
        proc_delay_seconds=effects.number("proc_delay_seconds"),
        assumed_travel_distance=ARCANE_COMET_ASSUMED_TRAVEL_DISTANCE,
        distance_amp_ratio=amp_ratio,
        raw_damage=raw,
        damage_type=ratio_adaptive_type(bonus_ad_ratio, ap_ratio),
    )


def _compile_summon_aery(entry: Mapping[str, Any]) -> KeystoneAeryEffect:
    """Compile Summon Aery's sourced damage and shielding tables."""
    name = "Summon Aery"
    effects = RuneValues(name, entry.get("effects", {}))
    leveling = effects.value("leveling")
    if not isinstance(leveling, list) or len(leveling) < 2:
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] leveling must contain damage and shield "
            "tables — wiki parse degraded; check rune_parser and data/runes.json"
        )
    damage_by_level = tuple(float(value) for value in leveling[0])
    shield_by_level = tuple(float(value) for value in leveling[1])
    if len(damage_by_level) < 20 or len(shield_by_level) < 20:
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] leveling tables must cover 20 levels — "
            "wiki parse degraded; check rune_parser and data/runes.json"
        )
    bonus_ad_ratio = effects.number("bonus_ad_ratio")
    ap_ratio = effects.number("ap_ratio")

    return KeystoneAeryEffect(
        rune_name=name,
        breakdown_key=breakdown_key(name),
        display_name=display_name(name),
        damage_by_level=damage_by_level,
        shield_by_level=shield_by_level,
        bonus_ad_ratio=bonus_ad_ratio,
        ap_ratio=ap_ratio,
        damage_flight_seconds=effects.number("damage_flight_seconds"),
        shield_flight_seconds=effects.number("shield_flight_seconds"),
        shield_duration_seconds=effects.number("shield_duration_seconds"),
        linger_seconds=effects.number("linger_seconds"),
        damage_type=ratio_adaptive_type(bonus_ad_ratio, ap_ratio),
    )


def _compile_guardian(entry: Mapping[str, Any]) -> KeystoneGuardianEffect:
    """Compile Guardian's threshold, paired shield, and cooldown tables."""
    name = "Guardian"
    effects = RuneValues(name, entry.get("effects", {}))
    leveling = effects.value("leveling")
    if not isinstance(leveling, list) or len(leveling) < 2:
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] leveling must contain threshold and shield "
            "tables — wiki parse degraded; check rune_parser and data/runes.json"
        )
    threshold_by_level = tuple(float(value) for value in leveling[0])
    shield_by_level = tuple(float(value) for value in leveling[1])
    if len(threshold_by_level) < 20 or len(shield_by_level) < 20:
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] leveling tables must cover 20 levels — "
            "wiki parse degraded; check rune_parser and data/runes.json"
        )
    return KeystoneGuardianEffect(
        rune_name=name,
        breakdown_key=breakdown_key(name),
        display_name=display_name(name),
        threshold_by_level=threshold_by_level,
        shield_by_level=shield_by_level,
        cooldown_by_level=required_cooldown_by_level(name, entry),
        ap_ratio=effects.number("ap_ratio"),
        bonus_health_ratio=effects.number("bonus_health_ratio"),
        trigger_window_seconds=effects.number("trigger_window_seconds"),
        unpriced_receipts=_unpriced_receipts(name),
        shield_duration_seconds=effects.number("shield_duration_seconds"),
    )


def _compile_aftershock(entry: Mapping[str, Any]) -> KeystoneAftershockEffect:
    """Compile Aftershock's resistance cap and delayed shockwave tables."""
    name = "Aftershock"
    effects = RuneValues(name, entry.get("effects", {}))
    leveling = effects.value("leveling")
    if not isinstance(leveling, list) or len(leveling) < 2:
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] leveling must contain resistance cap and "
            "shockwave tables — wiki parse degraded; check rune_parser and "
            "data/runes.json"
        )
    cap_by_level = tuple(float(value) for value in leveling[0])
    shockwave_by_level = tuple(float(value) for value in leveling[1])
    if len(cap_by_level) < 20 or len(shockwave_by_level) < 20:
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] leveling tables must cover 20 levels — "
            "wiki parse degraded; check rune_parser and data/runes.json"
        )
    return KeystoneAftershockEffect(
        rune_name=name,
        breakdown_key=breakdown_key(name),
        display_name=display_name(name),
        resistance_cap_by_level=cap_by_level,
        shockwave_damage_by_level=shockwave_by_level,
        cooldown_seconds=RuneValues(name, entry).number("cooldown"),
        flat_armor=effects.number("flat_armor"),
        flat_magic_resistance=effects.number("flat_magic_resistance"),
        bonus_armor_ratio=effects.number("bonus_armor_ratio"),
        bonus_magic_resistance_ratio=effects.number("bonus_magic_resistance_ratio"),
        bonus_health_ratio=effects.number("bonus_health_ratio"),
        duration_seconds=effects.number("resistance_duration_seconds"),
        shockwave_radius=effects.number("shockwave_radius"),
        unpriced_receipts=_unpriced_receipts(name),
    )


def _compile_grasp(entry: Mapping[str, Any]) -> KeystoneGraspEffect:
    """Compile Grasp's timed stacks and maximum-health attack rider."""
    name = "Grasp of the Undying"
    effects = RuneValues(name, entry.get("effects", {}))
    return KeystoneGraspEffect(
        rune_name=name,
        breakdown_key=breakdown_key(name),
        display_name=display_name(name),
        damage_melee_ranged_ratios=required_pair(
            name, effects, "grasp_damage_melee_ranged_ratios"
        ),
        heal_melee_ranged_ratios=required_pair(
            name, effects, "grasp_heal_melee_ranged_ratios"
        ),
        bonus_health_melee_ranged=required_pair(
            name, effects, "grasp_bonus_health_melee_ranged"
        ),
        stack_cadence_seconds=effects.number("combat_stack_cadence_seconds"),
        stack_generation_seconds=effects.number("combat_stack_generation_seconds"),
        max_stacks=int(effects.number("max_stacks")),
        ready_window_seconds=effects.number("ready_window_seconds"),
    )


def _compile_hail_of_blades(entry: Mapping[str, Any]) -> KeystoneHailOfBladesEffect:
    """Compile Hail of Blades' sourced temporary swing window."""
    name = "Hail of Blades"
    effects = RuneValues(name, entry.get("effects", {}))
    return KeystoneHailOfBladesEffect(
        rune_name=name,
        breakdown_key=breakdown_key(name),
        display_name=display_name(name),
        damage_by_level=tuple(required_leveling(name, effects)),
        bonus_ad_ratio=effects.number("bonus_ad_ratio"),
        ap_ratio=effects.number("ap_ratio"),
        bonus_attack_speed_melee_ranged=required_pair(
            name, effects, "hail_bonus_attack_speed_melee_ranged"
        ),
        initial_stacks=int(effects.number("hail_initial_stacks")),
        stack_duration_seconds=effects.number("hail_stack_duration_seconds"),
        reset_stack_limit=int(effects.number("hail_reset_stack_limit")),
        cooldown_seconds=RuneValues(name, entry).number("cooldown"),
    )


def _compile_lethal_tempo(entry: Mapping[str, Any]) -> KeystoneLethalTempoEffect:
    """Compile Lethal Tempo's stacked attack schedule and bolt tables."""
    name = "Lethal Tempo"
    effects = RuneValues(name, entry.get("effects", {}))

    def level_table(key: str) -> tuple[float, ...]:
        return tuple(required_level_table(name, effects, key))

    return KeystoneLethalTempoEffect(
        rune_name=name,
        breakdown_key=breakdown_key(name),
        display_name=display_name(name),
        bolt_damage_melee_by_level=level_table(
            "lethal_tempo_bolt_damage_melee_by_level"
        ),
        bolt_damage_ranged_by_level=level_table(
            "lethal_tempo_bolt_damage_ranged_by_level"
        ),
        attack_speed_percent_melee_ranged=required_pair(
            name, effects, "lethal_tempo_attack_speed_percent_melee_ranged"
        ),
        bolt_damage_increase_ratio_melee_ranged=required_pair(
            name, effects, "lethal_tempo_bolt_damage_increase_ratio_melee_ranged"
        ),
        max_stacks=int(effects.number("max_stacks")),
        stack_duration_seconds=effects.number("lethal_tempo_stack_duration_seconds"),
        expiry_step_seconds=effects.number("lethal_tempo_expiry_step_seconds"),
        damage_type=pure_adaptive_type,
    )


def _compile_glacial(entry: Mapping[str, Any]) -> KeystoneGlacialEffect:
    """Compile Glacial Augment's sourced zone and reduction values."""
    name = "Glacial Augment"
    effects = RuneValues(name, entry.get("effects", {}))
    return KeystoneGlacialEffect(
        rune_name=name,
        breakdown_key=breakdown_key(name),
        display_name=display_name(name),
        cooldown_seconds=RuneValues(name, entry).number("cooldown"),
        ray_count=int(effects.number("glacial_ray_count")),
        zone_radius_units=effects.number("glacial_zone_radius_units"),
        zone_width_units=effects.number("glacial_zone_width_units"),
        zone_base_duration_seconds=effects.number("glacial_zone_base_duration_seconds"),
        zone_duration_cc_ratio=effects.number("glacial_zone_duration_cc_ratio"),
        slow_base_ratio=effects.number("glacial_slow_base_ratio"),
        slow_bonus_ad_ratio_per_100=effects.number(
            "glacial_slow_bonus_ad_ratio_per_100"
        ),
        slow_ap_ratio_per_100=effects.number("glacial_slow_ap_ratio_per_100"),
        slow_heal_shield_ratio_per_10=effects.number(
            "glacial_slow_heal_shield_ratio_per_10"
        ),
        damage_reduction_ratio=effects.number("glacial_damage_reduction_ratio"),
        unpriced_receipts=_unpriced_receipts(name),
    )


def _compile_stormraider(entry: Mapping[str, Any]) -> KeystoneStormraiderEffect:
    """Compile Stormraider's sourced threshold and movement burst."""
    name = "Stormraider's Surge"
    effects = RuneValues(name, entry.get("effects", {}))
    return KeystoneStormraiderEffect(
        rune_name=name,
        breakdown_key=breakdown_key(name),
        display_name=display_name(name),
        cooldown_by_level=required_cooldown_by_level(name, entry),
        damage_threshold_ratio=effects.number("stormraider_damage_threshold_ratio"),
        damage_window_seconds=effects.number("stormraider_damage_window_seconds"),
        bonus_move_speed_melee_ranged=required_pair(
            name, effects, "stormraider_bonus_move_speed_melee_ranged"
        ),
        slow_resist_ratio=effects.number("stormraider_slow_resist_ratio"),
        unpriced_receipts=_unpriced_receipts(name),
        duration_seconds=effects.number("stormraider_duration_seconds"),
    )


def _compile_fleet(entry: Mapping[str, Any]) -> KeystoneFleetEffect:
    """Compile Fleet Footwork's sourced heal and Energized window."""
    name = "Fleet Footwork"
    effects = RuneValues(name, entry.get("effects", {}))

    def level_table(key: str) -> tuple[float, ...]:
        return tuple(required_level_table(name, effects, key))

    return KeystoneFleetEffect(
        rune_name=name,
        breakdown_key=breakdown_key(name),
        display_name=display_name(name),
        heal_melee_by_level=level_table("fleet_heal_melee_by_level"),
        heal_ranged_by_level=level_table("fleet_heal_ranged_by_level"),
        bonus_ad_ratio_melee_ranged=required_pair(
            name, effects, "fleet_bonus_ad_ratio_melee_ranged"
        ),
        ap_ratio_melee_ranged=required_pair(
            name, effects, "fleet_ap_ratio_melee_ranged"
        ),
        bonus_move_speed_melee_ranged=required_pair(
            name, effects, "fleet_bonus_move_speed_melee_ranged"
        ),
        minion_heal_effectiveness=effects.number("fleet_minion_heal_effectiveness"),
        charge_cap=int(effects.number("fleet_charge_cap")),
        move_speed_duration_seconds=effects.number("fleet_move_speed_duration_seconds"),
    )


def _compile_conqueror(entry: Mapping[str, Any]) -> KeystoneConquerorEffect:
    """Compile Conqueror's adaptive-force stack and healing receipts."""
    name = "Conqueror"
    effects = RuneValues(name, entry.get("effects", {}))

    def level_table(key: str) -> tuple[float, ...]:
        return tuple(required_level_table(name, effects, key))

    return KeystoneConquerorEffect(
        rune_name=name,
        breakdown_key=breakdown_key(name),
        display_name=display_name(name),
        adaptive_force_by_level=level_table("conqueror_adaptive_force_by_level"),
        adaptive_force_max_by_level=level_table(
            "conqueror_adaptive_force_max_by_level"
        ),
        max_stacks=int(effects.number("max_stacks")),
        stacks_per_application=int(effects.number("conqueror_stacks_per_application")),
        stack_duration_seconds=effects.number("conqueror_stack_duration_seconds"),
        cast_instance_interval_seconds=effects.number(
            "conqueror_cast_instance_interval_seconds"
        ),
        heal_melee_ranged_ratios=required_pair(
            name, effects, "conqueror_heal_melee_ranged_ratios"
        ),
    )


def _compile_deathfire(entry: Mapping[str, Any]) -> KeystoneDeathfireEffect:
    """Compile Deathfire Touch's typed burn tables and durations."""
    name = "Deathfire Touch"
    effects = RuneValues(name, entry.get("effects", {}))

    leveling = effects.value("leveling")
    if not isinstance(leveling, list) or len(leveling) < 2:
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] 'leveling' must contain base and amplified "
            "20-level burn tables — wiki parse degraded; check rune_parser and "
            "data/runes.json"
        )
    tables: list[tuple[float, ...]] = []
    for index, values in enumerate(leveling[:2]):
        if not isinstance(values, list) or len(values) < 20:
            raise KeyError(
                f"RUNE_EFFECTS[{name!r}] 'leveling[{index}]' must cover 20 levels "
                "— wiki parse degraded; check rune_parser and data/runes.json"
            )
        tables.append(tuple(float(value) for value in values))

    duration_values = effects.value("deathfire_duration_seconds")
    if not isinstance(duration_values, Mapping):
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] is missing typed burn duration categories "
            "— wiki parse degraded; check rune_parser and data/runes.json"
        )
    required_categories = (
        "spell_damage",
        "area_damage",
        "persistent_damage",
        "persistent_area_damage",
        "pet_damage",
    )
    durations: dict[str, float] = {}
    for category in required_categories:
        if category not in duration_values:
            raise KeyError(
                f"RUNE_EFFECTS[{name!r}] is missing burn duration {category!r} "
                "— wiki parse degraded; check rune_parser and data/runes.json"
            )
        durations[category] = float(duration_values[category])

    return KeystoneDeathfireEffect(
        rune_name=name,
        breakdown_key=breakdown_key(name),
        display_name=display_name(name),
        damage_by_level=tables[0],
        amplified_damage_by_level=tables[1],
        bonus_ad_ratios_by_state=required_pair(
            name, effects, "deathfire_bonus_ad_ratios_by_state"
        ),
        ap_ratios_by_state=required_pair(name, effects, "deathfire_ap_ratios_by_state"),
        tick_interval_seconds=effects.number("deathfire_tick_interval_seconds"),
        amp_delay_seconds=effects.number("deathfire_amp_delay_seconds"),
        amp_ratio=effects.number("deathfire_amp_ratio"),
        duration_by_category=durations,
    )


def _compile_dark_harvest(entry: Mapping[str, Any]) -> KeystoneDarkHarvestEffect:
    """Compile Dark Harvest's sourced threshold and Soul damage formula."""
    name = "Dark Harvest"
    effects = RuneValues(name, entry.get("effects", {}))
    top = RuneValues(name, entry)
    bonus_ad_ratio = effects.number("bonus_ad_ratio")
    ap_ratio = effects.number("ap_ratio")
    return KeystoneDarkHarvestEffect(
        rune_name=name,
        breakdown_key=breakdown_key(name),
        display_name=display_name(name),
        cooldown_seconds=top.number("cooldown"),
        health_threshold_ratio=effects.number("health_threshold_ratio"),
        base_damage=effects.number("base_damage"),
        soul_damage=effects.number("soul_damage"),
        bonus_ad_ratio=bonus_ad_ratio,
        ap_ratio=ap_ratio,
        proc_delay_seconds=effects.number("proc_delay_seconds"),
        takedown_reset_seconds=effects.number("takedown_reset_seconds"),
        unpriced_receipts=_unpriced_receipts(name),
        damage_type=ratio_adaptive_type(bonus_ad_ratio, ap_ratio),
    )


# The keystones that book no damage: disposition, the reason that becomes
# the receipt, and any further half this engine refuses. A table rather than
# a compiler each, because these differ only in their words — and a
# difference that is only words belongs in a table beside its reader, which
# is what ``COMPILERS`` itself is.
NO_DAMAGE: Mapping[str, tuple[Disposition, str, tuple[str, ...]]] = {
    "Unsealed Spellbook": (
        Disposition.STRUCTURAL_ZERO,
        "it swaps summoner spells out of combat: the holder picks the "
        "equipped and swapped spells, each summoner spell has its own "
        "effect, and no source states a combat number for the rune itself",
        (),
    ),
}


# The compiled keystone roster — this module's half of the resolver's
# table. Every name in ``data/runes.json`` not listed here fails closed in
# ``rune_effects.resolve_rune`` with a named reason.
COMPILERS: dict[str, Callable[[Mapping[str, Any]], RuneEffect]] = {
    "Electrocute": _compile_electrocute,
    "First Strike": _compile_first_strike,
    "Press the Attack": _compile_press_the_attack,
    "Arcane Comet": _compile_arcane_comet,
    "Summon Aery": _compile_summon_aery,
    "Guardian": _compile_guardian,
    "Aftershock": _compile_aftershock,
    "Grasp of the Undying": _compile_grasp,
    "Hail of Blades": _compile_hail_of_blades,
    "Lethal Tempo": _compile_lethal_tempo,
    "Glacial Augment": _compile_glacial,
    "Stormraider's Surge": _compile_stormraider,
    "Fleet Footwork": _compile_fleet,
    "Conqueror": _compile_conqueror,
    "Deathfire Touch": _compile_deathfire,
    "Dark Harvest": _compile_dark_harvest,
    **{
        name: no_damage_compiler(name, *declaration)
        for name, declaration in NO_DAMAGE.items()
    },
}
