"""Fight setup: resolve resistances, amps and attack timing into a `FightState`."""

import math
from collections.abc import Mapping, Sequence
from typing import Any

from ... import item_effects, rune_effects
from ...ability_spec import AttackClass
from ...interpreters import (
    active_cast,
    cast_proc,
    charged_strike,
    on_hit_strike,
    part_amp,
    periodic,
    rearmed_swings,
    resistance_shred,
    secondary_target,
    stat_derivation,
)
from ...interpreters.spellblade import resolve_slot as resolve_spellblade_slot
from ...interpreters.sustain import saturating_stat_percent
from ...item_behavior import (
    ActiveWindowCastEconomyRule,
    FightFacts,
    Resistance,
    SustainStat,
)
from ..cast_slots import DEFAULT_CAST_ORDER
from ..config import FightConfig
from ..declarations import BuildDeclarations
from ..resists import Resists
from ..state import FightState


def _shred_slot(
    items: Sequence[Mapping[str, Any]],
    resistance: Resistance,
    config: FightConfig,
    *,
    level: int,
    is_melee: bool,
) -> "resistance_shred.ShredSlot | None":
    """The declared shred this build brings to one of the target's resistances.
    ``None`` means no item the build holds declares a shred of it — an
    answer, not a zero.  Owners are passed as names because a declaration is
    keyed by whatever owns it; the engine never spells one.  The fight facts
    are the build context's required fields: no shred's magnitude reads them
    today, and passing a placeholder for one would be the silent default the
    context's requiredness exists to prevent.
    """
    return resistance_shred.resolve_slot(
        [item_effects.resolved_item_name(item) for item in items],
        resistance,
        facts=FightFacts(
            level=level,
            fight_duration_seconds=config.fight_duration_seconds,
            target_bonus_health=max(0.0, config.target_bonus_health),
            holder_is_melee=is_melee,
        ),
    )


def _part_amp(
    owners: Sequence[str],
    attack_class: AttackClass,
    *,
    armed: bool,
    facts: FightFacts,
    holder_stats: Mapping[str, float],
) -> tuple[float, str]:
    """The per-part amp for one attack class: its multiplier and its holder.

    ``armed`` is the scenario's answer to whether the amp's activation is up
    at all — an item active nobody triggered amplifies nothing — and an
    unarmed build, or one holding no such amp, gets ``(1.0, "")``: a
    multiplier that changes no number, and no holder to file a row under.
    That pairing is deliberate, so a breakdown row can never be attributed to
    an item whose amp did not run.
    """
    if not armed:
        return 1.0, ""
    amp = part_amp.resolve_part_amp(
        owners,
        attack_class,
        facts=facts,
    )
    if amp is None:
        return 1.0, ""
    return amp.multiplier(holder_stats), amp.owner


# A keystone compiled to one of these carries its OWN certified model — the
# ``_add_keystone_*`` steps here, which schedule swings, stacks and cadences
# the generic page walk cannot express, and the three defensive ones the
# coupled ``participant_timeline`` walk owns.  Every other rune, keystone or
# minor, is priced by the compiled page.  The split is declared once here so
# a rune is priced in exactly one place.
_DEDICATED_KEYSTONE_MODELS: "tuple[type, ...]" = (
    rune_effects.KeystoneAeryEffect,
    rune_effects.KeystoneAftershockEffect,
    rune_effects.KeystoneConquerorEffect,
    rune_effects.KeystoneDarkHarvestEffect,
    rune_effects.KeystoneDeathfireEffect,
    rune_effects.KeystoneFleetEffect,
    rune_effects.KeystoneGlacialEffect,
    rune_effects.KeystoneGraspEffect,
    rune_effects.KeystoneGuardianEffect,
    rune_effects.KeystoneHailOfBladesEffect,
    rune_effects.KeystoneLethalTempoEffect,
    rune_effects.KeystoneStormraiderEffect,
)


def _dedicated_keystone(name: str) -> "rune_effects.RuneEffect | None":
    """The named keystone's own model, or ``None``, which leaves it to the page
    walk: an unmodeled name compiles to a receipt there, not to silence here."""
    effect = rune_effects.resolve_keystone(name)
    return effect if isinstance(effect, _DEDICATED_KEYSTONE_MODELS) else None


def _page_walk_runes(
    page: "rune_effects.RunePage", claimed: bool
) -> "rune_effects.RunePage":
    """The page the generic rune walk prices: minors, shards, and the keystone.

    The keystone is dropped exactly when :func:`_dedicated_keystone` claimed
    it, so the two rune engines never price the same rune twice.
    """
    if not claimed:
        return page
    return rune_effects.RunePage(
        keystone="",
        minor_runes=page.minor_runes,
        stat_shards=page.stat_shards,
        options=page.options,
    )


def _resolve_combat_state(
    champion_stats: dict[str, float],
    ability_damages: dict[str, dict[str, Any]],
    items: list[dict[str, Any]],
    config: FightConfig,
    *,
    item_options: Mapping[str, Mapping[str, int | float]] | None = None,
    champion_options: Mapping[str, Any] | None = None,
) -> FightState:
    """Resolve resistances, penetration, amplifiers and attack timing.

    Builds the ``FightState`` every later step operates on: effective
    armor/MR after penetration (with the Terminus ability/auto split and
    Malignance's pre/post-ult MR), Black Cleaver armor reduction, the
    fight's auto-attack count (including Fiendhunter Bolts' empowered-auto
    window), and the fight-wide damage amplifiers.
    """
    fight_duration_seconds = config.fight_duration_seconds
    auto_attack_uptime = config.auto_attack_uptime
    is_melee = champion_stats["is_melee"]
    saturated_omnivamp = saturating_stat_percent(
        [item_effects.resolved_item_name(item) for item in items],
        SustainStat.OMNIVAMP_PERCENT,
        fight_duration_seconds=fight_duration_seconds,
        holder_is_melee=bool(is_melee),
    )
    if saturated_omnivamp > 0.0:
        # The stat bundle carries whatever the resolved block already holds.
        # A grant a ramp arms is a fight-state transition rather than a stat,
        # so add it to a private copy before any healing path or score-only
        # fast-path decision reads the resolved stats.
        champion_stats = dict(champion_stats)
        champion_stats["omnivamp_percent"] = (
            champion_stats["omnivamp_percent"] + saturated_omnivamp
        )
    level = int(champion_stats["level"])
    damage_effects = item_effects.resolve_damage_effects(items)
    # The declared families this build brings.  Resolved before the
    # resistances, because Malignance's magic-resistance shred is one of the
    # numbers the resistance ladder is built from.
    owners = [item_effects.resolved_item_name(item) for item in items]
    facts = FightFacts(
        level=level,
        fight_duration_seconds=fight_duration_seconds,
        target_bonus_health=max(0.0, config.target_bonus_health),
        holder_is_melee=bool(is_melee),
    )
    item_cast_procs = cast_proc.resolve_slots(
        owners,
        facts=facts,
    )
    item_charged_strikes = charged_strike.resolve_slots(
        owners,
        facts=facts,
    )
    actualizer_active_until = (
        item_effects.actualizer_active_seconds(
            items,
            item_options,
            fight_duration_seconds=fight_duration_seconds,
        )
        if config.include_actives
        else 0.0
    )
    # What the open window does to a basic ability's cooldown, read off the
    # declaration hung on the same registry entry the amp above is declared
    # from.  ``actualizer_active_seconds`` already answers zero for a build
    # that does not hold the item, so an open window *is* the presence test
    # and the declaration is what supplies the number.
    cast_economy = stat_derivation.sole_declared_derivation(
        owners, ActiveWindowCastEconomyRule
    )
    actualizer_basic_cooldown_multiplier = (
        1.0 / cast_economy.value("basic_cooldown_progress_multiplier")
        if actualizer_active_until > 0.0 and cast_economy is not None
        else 1.0
    )
    # The other half of the same trade, resolved here rather than inside a
    # resource walk: both walks price a cast against ONE number, and 1.0 is
    # what a build with no open window multiplies by.
    actualizer_resource_cost_multiplier = (
        cast_economy.value("resource_cost_multiplier")
        if actualizer_active_until > 0.0 and cast_economy is not None
        else 1.0
    )

    # The two per-part amps, read off their declarations.  The engine asks by
    # the attack class it is about to price — "what amplifies an ability",
    # "what amplifies a basic attack" — because that is the question the
    # declaration's typing answers, and asking it that way is what keeps the
    # two item names out of this module.  The ability amp rides an item
    # active, so it is armed only for a scenario that authored the window.
    ability_part_amp = _part_amp(
        owners,
        AttackClass.ABILITY,
        armed=actualizer_active_until > 0.0,
        facts=facts,
        holder_stats=champion_stats,
    )
    basic_part_amp = _part_amp(
        owners,
        AttackClass.BASIC_ATTACK,
        armed=True,
        facts=facts,
        holder_stats=champion_stats,
    )

    magic_pen_flat = champion_stats["magic_penetration_flat"]
    magic_pen_percent = champion_stats["magic_penetration_percent"] / 100.0

    # Hatefog's flat reduction is the item's magnitude; whether it applies
    # is the rotation's R outcome (``Resists.ult_cast``): abilities before
    # the accepted R cast use base MR, and a window that never accepts one
    # — auto-only, a cast order without R, an R the budget refused — keeps
    # the pre-ult MR throughout.
    malignance_mr_reduction = sum(
        effect.mr_reduction for effect in item_cast_procs.ultimate_procs
    )

    base_mr = max(config.target_magic_resistance, 0)
    reduced_mr = max(config.target_magic_resistance - malignance_mr_reduction, 0)

    # Stacking MR reduction (Bloodletter's Curse Vile Decay), declared
    mr_shred = _shred_slot(
        items, Resistance.MAGIC_RESIST, config, level=level, is_melee=bool(is_melee)
    )

    # Armor penetration: percent pen + lethality (flat)
    armor_pen_percent = champion_stats["armor_penetration_percent"] / 100.0
    armor_pen_bonus_percent = champion_stats["armor_penetration_bonus_percent"] / 100.0
    flat_armor_pen = champion_stats["flat_armor_penetration"]

    as_ratio = champion_stats["attack_speed_ratio"]
    attack_speed = champion_stats["attack_speed"]
    attack_speed_multiplier = max(
        0.0, min(1.0, float(config.attacker_attack_speed_multiplier))
    )
    if attack_speed_multiplier != 1.0:
        # A total attack-speed cripple scales both the opening rate and the
        # ratio used by later temporary bonus-AS windows.  This keeps the
        # aura active for every authored swing, not only the first schedule.
        champion_stats = dict(champion_stats)
        attack_speed *= attack_speed_multiplier
        as_ratio *= attack_speed_multiplier
        champion_stats["attack_speed"] = attack_speed
        champion_stats["attack_speed_ratio"] = as_ratio
    # ``calculate_total_stats`` keeps every assumed-active attack-speed window
    # visible in the public stat panel, but the authored fight starts before
    # the holder has attacked.  Strip whatever the declared swing schedule
    # re-applies itself; the walk re-adds it after the first attack and
    # expires it on the sourced window and cooldown.
    swing_schedule = item_charged_strikes.swing_schedule
    if swing_schedule is not None and swing_schedule.window is not None:
        champion_stats = dict(champion_stats)
        attack_speed = max(
            0.0,
            attack_speed - as_ratio * swing_schedule.opening_rate_bonus_percent / 100.0,
        )
        champion_stats["attack_speed"] = attack_speed

    # ── Ultimate-triggered AS buffs (Fiendhunter Bolts) ──────
    # NOTE: Hexplate 50% bonus AS is now baked into champion stats (stats.py)
    ultimate_auto_buff = item_charged_strikes.empowered_auto_buff
    empowered_autos = 0

    if ultimate_auto_buff is not None and auto_attack_uptime > 0:
        buffed_as = attack_speed + as_ratio * (
            ultimate_auto_buff.bonus_attack_speed_percent / 100.0
        )

        # Fiendhunter: 3 empowered autos at buffed AS, then normal AS
        buff_dur = min(ultimate_auto_buff.duration, fight_duration_seconds)
        possible_in_window = math.floor(buffed_as * buff_dur * auto_attack_uptime)
        empowered_autos = min(
            ultimate_auto_buff.empowered_auto_count,
            possible_in_window,
        )
        if empowered_autos > 0 and buffed_as > 0:
            time_for_empowered = empowered_autos / (buffed_as * auto_attack_uptime)
        else:
            time_for_empowered = 0.0
        remaining_dur = fight_duration_seconds - time_for_empowered
        normal_autos = math.floor(
            attack_speed * max(0, remaining_dur) * auto_attack_uptime
        )
        num_auto_attacks = empowered_autos + normal_autos
    elif swing_schedule is not None and swing_schedule.schedules(
        one_rotation=config.one_rotation
    ):
        num_auto_attacks = len(
            rearmed_swings.swing_times(
                swing_schedule,
                attack_speed=attack_speed,
                attack_speed_ratio=as_ratio,
                duration_seconds=fight_duration_seconds,
                uptime=auto_attack_uptime,
                critical_chance=champion_stats["critical_strike_chance"] / 100.0,
            )
        )
    else:
        num_auto_attacks = math.floor(
            attack_speed * fight_duration_seconds * auto_attack_uptime
        )

    # Terminus Juxtaposition: stacking armor/magic pen every other auto.
    # The pen is displayed in champion stats at max stacks, but the fight
    # engine computes a weighted average pen across all autos (like Black
    # Cleaver) since stacks ramp up: 0%, 10%, 10%, 20%, 20%, 30%, 30%...
    # Terminus pen only applies to auto attacks, NOT abilities — see the
    # Resists docstring for the ability/auto pen split.
    stacking_pen = damage_effects.stacking_pen
    has_terminus = stacking_pen is not None
    terminus_avg_pen = 0.0
    terminus_stat_pen = 0.0
    if stacking_pen is not None:
        terminus_avg_pen = stacking_pen.average_pen(num_auto_attacks)
        terminus_stat_pen = stacking_pen.max_pen

    # Stacking armor reduction applies before penetration.
    armor_shred = _shred_slot(
        items, Resistance.ARMOR, config, level=level, is_melee=bool(is_melee)
    )
    bc_reduction = (
        armor_shred.average_reduction(num_auto_attacks)
        if armor_shred is not None
        else 0.0
    )

    resists = Resists(
        magic_pen_flat=magic_pen_flat,
        magic_pen_percent=magic_pen_percent,
        armor_pen_percent=armor_pen_percent,
        armor_pen_bonus_percent=armor_pen_bonus_percent,
        flat_armor_pen=flat_armor_pen,
        target_bonus_armor=config.target_bonus_armor,
        physical_damage_flat_reduction=(config.target_physical_damage_flat_reduction),
        physical_damage_flat_reduction_cap=(
            config.target_physical_damage_flat_reduction_cap
        ),
        has_terminus=has_terminus,
        terminus_stat_pen=terminus_stat_pen,
        terminus_avg_pen=terminus_avg_pen,
        target_armor=config.target_armor,
        base_mr=base_mr,
        reduced_mr=reduced_mr,
        malignance_mr_reduction=malignance_mr_reduction,
        bc_reduction=bc_reduction,
        mr_shred=mr_shred,
    )
    resists.resolve_magic()
    resists.resolve_armor()
    keystone_effect = _dedicated_keystone(config.keystone)

    return FightState(
        champion_stats=champion_stats,
        ability_damages=ability_damages,
        items=items,
        damage_effects=damage_effects,
        per_hit_strikes=on_hit_strike.per_hit_effects(
            owners,
            facts=facts,
        ),
        class_restricted_strikes=on_hit_strike.class_restricted_per_hit_effects(
            owners, target_class=config.target_class
        ),
        item_actives=active_cast.active_sources(
            owners,
            facts=facts,
        ),
        declared=BuildDeclarations(
            periodics=periodic.resolve_slots(
                owners,
                facts=facts,
            ),
            cast_procs=item_cast_procs,
            charged_strikes=item_charged_strikes,
            armor_shred=armor_shred,
            secondary_target_bolts=secondary_target.resolve_slot(
                owners,
                facts=facts,
            ),
        ),
        item_spellblade=resolve_spellblade_slot(
            owners,
            facts=facts,
        ),
        cast_order=(
            config.cast_order
            if config.cast_order is not None
            else list(DEFAULT_CAST_ORDER)
        ),
        target_health=config.target_health,
        target_bonus_health=config.target_bonus_health,
        fight_duration_seconds=fight_duration_seconds,
        auto_attack_uptime=auto_attack_uptime,
        item_options=item_options,
        champion_options=dict(champion_options or {}),
        actualizer_active_until=actualizer_active_until,
        actualizer_basic_cooldown_multiplier=actualizer_basic_cooldown_multiplier,
        actualizer_resource_cost_multiplier=actualizer_resource_cost_multiplier,
        ability_haste=champion_stats["ability_haste"],
        one_rotation=config.one_rotation,
        include_actives=config.include_actives,
        auto_attacks_only=config.auto_attacks_only,
        ultimate_recasts=config.ultimate_recasts,
        deterministic=config.deterministic,
        is_melee=is_melee,
        level=level,
        enforce_resource_limits=config.enforce_resource_limits,
        resource_restore_events=tuple(config.resource_restore_events),
        resource_ledger_owner=str(config.resource_ledger_owner),
        target_basic_damage_multiplier=config.target_basic_damage_multiplier,
        target_basic_damage_flat_reduction=(config.target_basic_damage_flat_reduction),
        target_basic_damage_flat_reduction_cap=(
            config.target_basic_damage_flat_reduction_cap
        ),
        target_champion_damage_flat_reduction=(
            config.target_champion_damage_flat_reduction
        ),
        target_champion_dot_damage_flat_reduction=(
            config.target_champion_dot_damage_flat_reduction
        ),
        target_critical_strike_damage_multiplier=(
            config.target_critical_strike_damage_multiplier
        ),
        roster_target_index=max(0, int(config.roster_target_index)),
        roster_target_count=max(1, int(config.roster_target_count)),
        target_class=config.target_class,
        resists=resists,
        magic_amp=part_amp.declared_magic_amp(
            [item_effects.resolved_item_name(item) for item in items]
        ),
        ability_amp=ability_part_amp[0],
        ability_amp_owner=ability_part_amp[1],
        basic_amp=basic_part_amp[0],
        basic_amp_owner=basic_part_amp[1],
        attack_speed=attack_speed,
        attack_speed_ratio=as_ratio,
        num_auto_attacks=num_auto_attacks,
        empowered_autos=empowered_autos,
        runes=rune_effects.resolve_rune_page(
            _page_walk_runes(config.rune_page, keystone_effect is not None)
        ),
        rune_options=config.rune_page.options,
        keystone_effect=keystone_effect,
        keystone_options=dict(config.keystone_options),
    )
