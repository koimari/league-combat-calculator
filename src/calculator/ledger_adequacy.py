"""Which owner holds a mechanic: one probe per declared condition."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from .interpreters import cast_proc, periodic, spellblade, sustain
from .interpreters.crit_profile import declared_crit_profile
from .interpreters.damage_routing import declared_execution
from .interpreters.sustain import declared_sustain
from .interpreters.threshold_defense import threshold_health_owner
from .item_behavior import ManaSpentHealRule, OnHitHealRule, SustainStat
from .ledger_declarations import (
    _BASIC_ATTACK_READER,
    _INTERACTION_ROW_READER,
    _ITEM_HEAL_READER,
    _KEYSTONE_HEAL_READER,
    _LIFESTEAL_READER,
    _OMNIVAMP_READER,
    AdequacyCondition,
)
from .ledger_inputs import HeldItemFacts, LedgerInputs, ThresholdHealFacts
from .rune_effects import KeystoneConquerorEffect, KeystoneFleetEffect, resolve_rune
from .trigger_stream import (
    EngineOwner,
    ItemOwner,
    MechanicOwner,
    pair_outcome_items,
    tuple_incapable_items,
)


# The owner is asked of the declaration catalog rather than spelled here,
# because the pair engine sees a defender's numbers and never its items.
def _threshold_heal_owners(inputs: ThresholdHealFacts) -> tuple[MechanicOwner, ...]:
    """The item arming a threshold-health heal on this fight's target."""
    if inputs.target_threshold_health_heal <= 0:
        return ()
    return (ItemOwner(threshold_health_owner()),)


def _self_heal_rule_owners(inputs: LedgerInputs) -> tuple[MechanicOwner, ...]:
    """The champion slot declaring a reviewed self-heal rule, if there is one."""
    if inputs.self_heal_rule is None:
        return ()
    return (inputs.self_heal_rule,)


def _item_self_heal_owners(inputs: LedgerInputs) -> tuple[MechanicOwner, ...]:
    """Whether this build can emit item-owned self-heal packets.

    Asked of the whole build in one question, exactly as the four
    declarations answer it: the spellblade reading is *of the spellblade the
    build arms*, so asking the declarations item by item to name a holder
    would change the answer for a build carrying two.  That is why this
    condition's owner is the deriving function rather than an item name.
    """
    names = inputs.item_names
    first_auto_crit = declared_crit_profile(names).forced_crit
    armed = (
        spellblade.declares_self_heal(names)
        or periodic.declares_self_heal(names)
        or declared_sustain(names, OnHitHealRule) is not None
        or (
            first_auto_crit is not None
            and (
                first_auto_crit.heal_base_ad_ratio > 0.0
                or first_auto_crit.heal_missing_health_ratio > 0.0
            )
        )
        or declared_sustain(names, ManaSpentHealRule) is not None
    )
    return (EngineOwner(_ITEM_HEAL_READER),) if armed else ()


def _item_health_regen_owners(inputs: LedgerInputs) -> tuple[MechanicOwner, ...]:
    """Whether items raise regeneration above the champion's own base.

    Fail-closed on an unreadable stat: a regen value that will not parse is a
    fight whose regeneration ticks cannot be ruled out, and the wide ledger
    is the answer that cannot lose them.
    """
    condition = AdequacyCondition.ITEM_HEALTH_REGEN
    try:
        total = float(inputs.raw_stat(condition, "health_regen_per_five") or 0.0)
        base = float(inputs.raw_stat(condition, "base_health_regen_per_five") or 0.0)
    except (TypeError, ValueError):
        return (EngineOwner(_ITEM_HEAL_READER),)
    if math.isfinite(total) and math.isfinite(base) and total > base:
        return (EngineOwner(_ITEM_HEAL_READER),)
    return ()


def _vamp_stat_owners(
    inputs: LedgerInputs, condition: AdequacyCondition, field: str, reader: str
) -> tuple[MechanicOwner, ...]:
    """The shared reading of a percentage vamp stat.

    A non-numeric or boolean value is *not* a demand, the opposite of the
    regeneration reading above: vamp packets are authored from a percentage
    the engine multiplies, so a value that is not one authors nothing.
    """
    value = inputs.raw_stat(condition, field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return ()
    if math.isfinite(float(value)) and float(value) > 0.0:
        return (EngineOwner(reader),)
    return ()


def _lifesteal_owners(inputs: LedgerInputs) -> tuple[MechanicOwner, ...]:
    """Whether the build carries life steal the fight must receipt."""
    return _vamp_stat_owners(
        inputs,
        AdequacyCondition.LIFESTEAL_STAT,
        "lifesteal_percent",
        _LIFESTEAL_READER,
    )


def _omnivamp_owners(inputs: LedgerInputs) -> tuple[MechanicOwner, ...]:
    """Whether the build carries omnivamp the fight must receipt."""
    return _vamp_stat_owners(
        inputs,
        AdequacyCondition.OMNIVAMP_STAT,
        "omnivamp_percent",
        _OMNIVAMP_READER,
    )


def _saturating_omnivamp_owners(inputs: LedgerInputs) -> tuple[MechanicOwner, ...]:
    """Whether a ramp-armed omnivamp grant tops out inside this fight."""
    percent = sustain.saturating_stat_percent(
        inputs.item_names,
        SustainStat.OMNIVAMP_PERCENT,
        fight_duration_seconds=inputs.fight_duration_seconds,
        holder_is_melee=inputs.is_melee,
    )
    return (EngineOwner(_OMNIVAMP_READER),) if percent else ()


def _keystone_self_heal_owners(inputs: LedgerInputs) -> tuple[MechanicOwner, ...]:
    """Whether the selected keystone can emit a self-heal packet.

    Conqueror pays its heal at max stacks in every fight that reaches them,
    so selecting it is the demand.  Fleet Footwork's Energized heal needs the
    charges to already be held: a fight that starts below the cap cannot
    reach it inside the window the light ledger is offered for, which is the
    same reading the keystone's own materializer takes.
    """
    keystone = inputs.rune_page.keystone
    if not keystone:
        return ()
    effect = resolve_rune(keystone)
    if isinstance(effect, KeystoneConquerorEffect):
        return (EngineOwner(_KEYSTONE_HEAL_READER),)
    if not isinstance(effect, KeystoneFleetEffect):
        return ()
    options = inputs.rune_page.options.get(keystone, {})
    charges = int(options.get("starting_charges", 0) or 0)
    return (EngineOwner(_KEYSTONE_HEAL_READER),) if charges >= effect.charge_cap else ()


def _ordered_interaction_owners(inputs: LedgerInputs) -> tuple[MechanicOwner, ...]:
    """Whether an ability row carries interaction metadata a tuple would lose."""
    for entry in inputs.ability_damages.values():
        if not isinstance(entry, Mapping):
            continue
        # The ENTRY's ``skillshot`` is a kit fact the walk reads off the
        # parse, which both ledger shapes carry unchanged; only metadata
        # that rides an individual ROW is lost by the positional schema.
        # Reading the kit fact here refused every skillshot champion a
        # light ledger, plain build and all.
        if entry.get("control_events"):
            return (EngineOwner(_INTERACTION_ROW_READER),)
        if float(entry.get("execute_threshold_ratio", 0.0) or 0.0) > 0:
            return (EngineOwner(_INTERACTION_ROW_READER),)
        for part in entry.get("parts", ()):
            if getattr(part, "cc_duration", 0.0) > 0.0 or getattr(
                part, "skillshot", False
            ):
                return (EngineOwner(_INTERACTION_ROW_READER),)
        for event in entry.get("damage_events", ()):
            if isinstance(event, Mapping) and (
                event.get("cc_duration", 0.0) or event.get("skillshot")
            ):
                return (EngineOwner(_INTERACTION_ROW_READER),)
    return ()


# Asked of the declaration: reading resolved effects would need a level and a
# fight window this record does not carry.
def _self_shield_proc_owners(inputs: LedgerInputs) -> tuple[MechanicOwner, ...]:
    """Every held cast proc that attaches a self shield to its event."""
    return tuple(
        ItemOwner(owner) for owner in cast_proc.self_shield_owners(inputs.item_names)
    )


def _empowered_auto_owners(inputs: LedgerInputs) -> tuple[MechanicOwner, ...]:
    """Whether an ability empowers the next basic attack."""
    empowered = any(
        ability.get("empowers_next_auto")
        for ability in inputs.ability_damages.values()
        if isinstance(ability, dict)
    )
    return (EngineOwner(_BASIC_ATTACK_READER),) if empowered else ()


def _raw_row_stream_owners(inputs: LedgerInputs) -> tuple[MechanicOwner, ...]:
    """Every held item declaring a stream the bus parses off raw rows."""
    return _held(inputs.item_names, tuple_incapable_items())


def _execute_threshold_owners(inputs: LedgerInputs) -> tuple[MechanicOwner, ...]:
    """The item arming a per-event execute threshold, if the build holds one."""
    execute = declared_execution(inputs.item_names)
    if execute is None:
        return ()
    return (ItemOwner(execute.owner),)


def _pair_outcome_owners(inputs: HeldItemFacts) -> tuple[MechanicOwner, ...]:
    """Every held item whose stream is synthesized from the shield outcome."""
    return _held(inputs.item_names, pair_outcome_items())


def _held(
    item_names: Sequence[str], projected: frozenset[str]
) -> tuple[MechanicOwner, ...]:
    """The held members of one capability projection, in the caller's order."""
    return tuple(ItemOwner(name) for name in item_names if name in projected)
