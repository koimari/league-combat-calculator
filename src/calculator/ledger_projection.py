"""Which narrowing of a pair fight's result its readers can still be served.

A score-only fight is allowed to return less than a full one: the damage
ledger may come back as positional 6-tuples instead of dict rows, and the
one-pair shield outcome may be skipped entirely.  Both narrowings are
**projections** of the same fight, and both are safe only while every reader
the fight arms can still answer its question off what the projection keeps.

Each clause is an :class:`AdequacyCondition` with a declared reader, the stat
fields it is derived from, and the reason it exists.  A projection declares
which conditions it **cannot** serve, and satisfaction is the question "does
this fight arm a reader my projection would starve".  A conjunction spelled
at the call sites would compute the same answer while naming no reader, so a
clause deleted by accident would price a heal at zero and say nothing.  Both
call sites read the answer from here and hold no clause of their own.

Three properties are asserted at import rather than reviewed:

* every condition has exactly one declaration and exactly one probe;
* the two projections' unserved sets cover every condition, and overlap on
  exactly :attr:`AdequacyCondition.TARGET_THRESHOLD_HEAL` — the one clause
  both gates read, which is now one function called twice rather than one
  sentence written twice;
* a probe that reads a champion stat reads it through
  :meth:`LedgerInputs.raw_stat`, which refuses any field the condition did
  not declare in ``requires_fields``.

This module is a leaf on purpose.  It imports the interpreters, the
capability projections and the rune compiler the two gates already consumed,
and nothing else, so both the pipeline (above the engine) and the damage
engine itself can ask it without a cycle.  In particular it never imports the
champion healing registry: ``healing.self_heal_rule_owner`` hands it a typed
:class:`~.trigger_stream.ChampionSlotOwner` instead, which is also what makes
the champion half of the answer a declaration rather than a name set.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, NamedTuple, Protocol

from .interpreters import cast_proc, periodic, spellblade, sustain
from .interpreters.damage_routing import declared_execution
from .interpreters.sustain import declared_sustain
from .interpreters.threshold_defense import threshold_health_owner
from .item_behavior import ManaSpentHealRule, OnHitHealRule, SustainStat
from .rune_effects import (
    KeystoneConquerorEffect,
    KeystoneFleetEffect,
    RunePage,
    resolve_rune,
)
from .trigger_stream import (
    ChampionSlotOwner,
    EngineOwner,
    ItemOwner,
    MechanicOwner,
    pair_outcome_items,
    tuple_incapable_items,
)


class ResultProjection(Enum):
    """One shape a pair fight's result may be returned in.

    Four members and two questions.  The ledger pair answers "may this
    fight's damage events be positional tuples"; the shield pair answers "may
    the one-pair shield outcome be skipped".  Naming the wide member of each
    pair rather than treating it as "not the narrow one" is what lets
    :data:`_UNSERVED` be total over the enum: a projection that serves every
    reader declares an empty unserved set, which is a statement, where an
    absent entry would be a hole.
    """

    LIGHT_TUPLE_LEDGER = "light_tuple_ledger"
    DICT_ROW_LEDGER = "dict_row_ledger"
    SKIPPED_SHIELD_OUTCOME = "skipped_shield_outcome"
    RESOLVED_SHIELD_OUTCOME = "resolved_shield_outcome"


class LightRow(NamedTuple):
    """One positional row of the light tuple ledger, by name.

    The light ledger is one of the two shapes
    :attr:`ResultProjection.LIGHT_TUPLE_LEDGER` names, and this is the
    whole of what it carries.  Declared here, beside the projection that
    decides when a fight may be served in it, so the engine that writes
    the rows, the compiler that walks them and a test that compares them
    against the dict shape all read one statement of the layout rather
    than three agreeing sets of indices.

    A tuple subclass on purpose: ``LightRow._make(row)`` names the
    positions without building a dict, which the compiler does tens of
    thousands of times per request.
    """

    sort_key: tuple[Any, ...]
    damage: float
    damage_type: str
    source_key: str
    raw_formula: Any
    raw_damage: float
    declared: Any


#: The light row fields a dict row spells the same way.  A reader holding
#: both shapes compares exactly these; everything else is either the dict
#: row's receipt metadata or the light row's packed sort key.
SHARED_ROW_FIELDS: tuple[str, ...] = (
    "damage",
    "damage_type",
    "source_key",
    "raw_damage",
)


class AdequacyCondition(Enum):
    """One declared reason a fight cannot be served a narrowed result.

    The declaration order is the order the two conjunctions this replaced
    evaluated their clauses in, and both projection functions preserve it, so
    a caller that only wants the projection does the same work in the same
    sequence the ``and`` chain did.
    """

    TARGET_THRESHOLD_HEAL = "target_threshold_heal"
    CHAMPION_SELF_HEAL_RULE = "champion_self_heal_rule"
    ITEM_SELF_HEAL_PACKETS = "item_self_heal_packets"
    ITEM_HEALTH_REGEN = "item_health_regen"
    LIFESTEAL_STAT = "lifesteal_stat"
    OMNIVAMP_STAT = "omnivamp_stat"
    SATURATING_OMNIVAMP = "saturating_omnivamp"
    KEYSTONE_SELF_HEAL = "keystone_self_heal"
    EMPOWERED_BASIC_ATTACK = "empowered_basic_attack"
    RAW_ROW_STREAM_HOLDER = "raw_row_stream_holder"
    EXECUTE_THRESHOLD_STAMP = "execute_threshold_stamp"
    ORDERED_INTERACTION_METADATA = "ordered_interaction_metadata"
    SELF_SHIELD_PROC = "self_shield_proc"
    PAIR_OUTCOME_STREAM = "pair_outcome_stream"


@dataclass(frozen=True, slots=True)
class AdequacyDeclaration:
    """What one condition reads, who would starve without it, and why.

    ``requires_fields`` is the champion-stat fields the condition is derived
    from, and it is load-bearing rather than documentation:
    :meth:`LedgerInputs.raw_stat` refuses a field the condition did not
    declare, so a probe that grows a second stat read fails instead of
    quietly widening the gate.  It is empty for every condition derived from
    items, parameters or ability data rather than from the stat block.
    """

    condition: AdequacyCondition
    reader: str
    requires_fields: frozenset[str]
    reason: str


@dataclass(frozen=True, slots=True)
class LedgerDemand:
    """One reader this fight arms that a narrowed result would starve.

    The receipt shape: which condition fired, who owns the mechanic that
    fired it, which code would have read the missing rows, and the sentence
    saying why the narrowing is unsafe.  ``owner`` is an
    :class:`~.trigger_stream.ItemOwner` or
    :class:`~.trigger_stream.ChampionSlotOwner` wherever the declaration
    knows a name, and an :class:`~.trigger_stream.EngineOwner` naming the
    deriving function where the mechanic genuinely has none.
    """

    condition: AdequacyCondition
    owner: MechanicOwner
    reader: str
    reason: str


class UndeclaredStatRead(KeyError):
    """A probe read a champion stat its condition did not declare."""

    def __init__(self, condition: AdequacyCondition, field: str) -> None:
        super().__init__(
            f"{condition.value} reads champion stat {field!r}, which is not in "
            "its declared requires_fields; a condition derived from a stat it "
            "does not declare is a gate nobody can audit"
        )
        self.condition = condition
        self.field = field


class _ThresholdHealFacts(Protocol):  # pylint: disable=too-few-public-methods
    """The one fact both gates' shared condition is derived from.

    A structural type rather than a base class: the two input records below
    are independent and neither should inherit from the other, but the probe
    they share must be *one function*, so what it accepts is the field it
    reads and nothing more.
    """

    target_threshold_health_heal: float


class _HeldItemFacts(Protocol):  # pylint: disable=too-few-public-methods
    """The held build, as the name list every item-keyed projection reads."""

    item_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ShieldOutcomeInputs:
    """The facts the one-pair shield outcome's readers are decided by.

    Deliberately narrower than :class:`LedgerInputs`: the damage engine holds
    no champion name and no self-heal declaration at the point it decides
    whether to resolve the shield outcome, and a record with fields it could
    only fill with a placeholder would make an unrelated condition answer
    "no demand" for the wrong reason.
    """

    item_names: tuple[str, ...]
    target_threshold_health_heal: float


@dataclass(frozen=True, slots=True)
class LedgerInputs:  # pylint: disable=too-many-instance-attributes
    """The facts the damage ledger's readers are decided by.

    ``self_heal_rule`` is the champion half of the answer, supplied as a
    typed owner by ``healing.self_heal_rule_owner`` rather than as a name
    this module checks against a set: the registry that knows which champions
    declare a rule is the registry that should say so, and it imports the
    champion package, which this leaf must not.  It is also the only champion
    fact here, so a bare ``champion_name`` beside it would be a field with no
    reader.
    """

    self_heal_rule: ChampionSlotOwner | None
    item_names: tuple[str, ...]
    stats: Mapping[str, Any]
    damage_effects: Any
    ability_damages: Mapping[str, Any]
    rune_page: RunePage
    fight_duration_seconds: float
    is_melee: bool
    target_threshold_health_heal: float

    # Uncoerced: the regen condition treats an unparseable stat as a demand
    # and the vamp conditions treat it as no demand, so a shared coercion
    # here would silently pick one of them.
    def raw_stat(self, condition: AdequacyCondition, field: str) -> Any:
        """One declared champion stat, uncoerced, or a refusal."""
        if field not in DECLARATIONS[condition].requires_fields:
            raise UndeclaredStatRead(condition, field)
        return self.stats.get(field, 0.0)


_ITEM_HEAL_READER = "pipeline._item_self_healing_events"
_LIFESTEAL_READER = "damage._add_lifesteal_events"
_OMNIVAMP_READER = "damage._add_omnivamp_events"
_BASIC_ATTACK_READER = "damage._ordered_damage_events"
_SUPPORT_SCAN_READER = "item_support_effects.derive_item_support_effects"
_EXECUTE_READER = "damage._add_execute_display"
_KEYSTONE_HEAL_READER = "pipeline._keystone_self_healing_events"
_INTERACTION_ROW_READER = "damage._ordered_damage_events"
_TAKEDOWN_READER = "trigger_stream.authored_triggers"
_HEALING_READER = "healing.derive_self_healing"
_THRESHOLD_READER = "damage._resolve_starting_shield_outcome"


_DECLARATIONS: tuple[AdequacyDeclaration, ...] = (
    AdequacyDeclaration(
        condition=AdequacyCondition.TARGET_THRESHOLD_HEAL,
        reader=_THRESHOLD_READER,
        requires_fields=frozenset(),
        reason=(
            "the target arms a threshold-health heal, whose trigger is read "
            "off the resolved shield outcome and whose coverage downgrade "
            "names the item that armed it"
        ),
    ),
    AdequacyDeclaration(
        condition=AdequacyCondition.CHAMPION_SELF_HEAL_RULE,
        reader=_HEALING_READER,
        requires_fields=frozenset(),
        reason=(
            "the champion declares a reviewed self-heal rule, which derives "
            "its receipts from the fight's dict damage rows"
        ),
    ),
    AdequacyDeclaration(
        condition=AdequacyCondition.ITEM_SELF_HEAL_PACKETS,
        reader=_ITEM_HEAL_READER,
        requires_fields=frozenset(),
        reason=(
            "the build arms an item-owned self-heal packet (spellblade heal, "
            "periodic strike heal, on-hit heal, first-crit heal or a "
            "mana-spent heal), which is authored against the dict rows"
        ),
    ),
    AdequacyDeclaration(
        condition=AdequacyCondition.ITEM_HEALTH_REGEN,
        reader=_ITEM_HEAL_READER,
        requires_fields=frozenset(
            {"health_regen_per_five", "base_health_regen_per_five"}
        ),
        reason=(
            "items raise health regeneration above the champion's base, so "
            "the fight authors timestamped regeneration ticks"
        ),
    ),
    AdequacyDeclaration(
        condition=AdequacyCondition.LIFESTEAL_STAT,
        reader=_LIFESTEAL_READER,
        requires_fields=frozenset({"lifesteal_percent"}),
        reason=(
            "the build carries life steal, whose packets are derived from the "
            "exact physical attack events"
        ),
    ),
    AdequacyDeclaration(
        condition=AdequacyCondition.OMNIVAMP_STAT,
        reader=_OMNIVAMP_READER,
        requires_fields=frozenset({"omnivamp_percent"}),
        reason=(
            "the build carries omnivamp, whose packets are derived from every "
            "damage event the fight authored"
        ),
    ),
    AdequacyDeclaration(
        condition=AdequacyCondition.SATURATING_OMNIVAMP,
        reader=_OMNIVAMP_READER,
        requires_fields=frozenset(),
        reason=(
            "a ramp-armed omnivamp grant tops out inside this fight's window, "
            "so the fight carries omnivamp the resolved stat block does not"
        ),
    ),
    AdequacyDeclaration(
        condition=AdequacyCondition.KEYSTONE_SELF_HEAL,
        reader=_KEYSTONE_HEAL_READER,
        requires_fields=frozenset(),
        reason=(
            "the selected keystone emits its own timestamped self-heal row, "
            "which is materialized from the dict breakdown's heal events"
        ),
    ),
    AdequacyDeclaration(
        condition=AdequacyCondition.EMPOWERED_BASIC_ATTACK,
        reader=_BASIC_ATTACK_READER,
        requires_fields=frozenset(),
        reason=(
            "an ability empowers the next basic attack, and the basic-attack "
            "marker reactive defenders read rides the dict row"
        ),
    ),
    AdequacyDeclaration(
        condition=AdequacyCondition.RAW_ROW_STREAM_HOLDER,
        reader=_SUPPORT_SCAN_READER,
        requires_fields=frozenset(),
        reason=(
            "the build holds an item whose declared mechanics read a stream "
            "the bus parses off raw rows, which the positional schema cannot "
            "carry (D-01)"
        ),
    ),
    AdequacyDeclaration(
        condition=AdequacyCondition.EXECUTE_THRESHOLD_STAMP,
        reader=_EXECUTE_READER,
        requires_fields=frozenset(),
        reason=(
            "the build arms an execute threshold, whose per-event stamps the "
            "positional schema cannot carry, so the engine stays fail-closed "
            "for the item"
        ),
    ),
    AdequacyDeclaration(
        condition=AdequacyCondition.ORDERED_INTERACTION_METADATA,
        reader=_INTERACTION_ROW_READER,
        requires_fields=frozenset(),
        reason=(
            "an ability row carries interaction metadata — a skillshot flag, "
            "a control event, a crowd-control duration or an execute "
            "threshold — that the positional schema cannot carry, so the "
            "coupled walk would lose the interaction it applies"
        ),
    ),
    AdequacyDeclaration(
        condition=AdequacyCondition.SELF_SHIELD_PROC,
        reader=_INTERACTION_ROW_READER,
        requires_fields=frozenset(),
        reason=(
            "a cooldown proc attaches a self shield to the damage event it "
            "rides, and the positional row has no field for it, so the "
            "shield would be silently dropped"
        ),
    ),
    AdequacyDeclaration(
        condition=AdequacyCondition.PAIR_OUTCOME_STREAM,
        reader=_TAKEDOWN_READER,
        requires_fields=frozenset(),
        reason=(
            "the build holds an item whose takedown stream is synthesized "
            "from the one-pair shield outcome's target ending health"
        ),
    ),
)

DECLARATIONS: Mapping[AdequacyCondition, AdequacyDeclaration] = MappingProxyType(
    {declaration.condition: declaration for declaration in _DECLARATIONS}
)


# The owner is asked of the declaration catalog rather than spelled here,
# because the pair engine sees a defender's numbers and never its items.
def _threshold_heal_owners(inputs: _ThresholdHealFacts) -> tuple[MechanicOwner, ...]:
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
    effects = inputs.damage_effects
    names = inputs.item_names
    first_auto_crit = effects.first_auto_crit
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


def _pair_outcome_owners(inputs: _HeldItemFacts) -> tuple[MechanicOwner, ...]:
    """Every held item whose stream is synthesized from the shield outcome."""
    return _held(inputs.item_names, pair_outcome_items())


def _held(
    item_names: Sequence[str], projected: frozenset[str]
) -> tuple[MechanicOwner, ...]:
    """The held members of one capability projection, in the caller's order."""
    return tuple(ItemOwner(name) for name in item_names if name in projected)


_LEDGER_PROBES: Mapping[
    AdequacyCondition, Callable[[Any], tuple[MechanicOwner, ...]]
] = MappingProxyType(
    {
        AdequacyCondition.TARGET_THRESHOLD_HEAL: _threshold_heal_owners,
        AdequacyCondition.CHAMPION_SELF_HEAL_RULE: _self_heal_rule_owners,
        AdequacyCondition.ITEM_SELF_HEAL_PACKETS: _item_self_heal_owners,
        AdequacyCondition.ITEM_HEALTH_REGEN: _item_health_regen_owners,
        AdequacyCondition.LIFESTEAL_STAT: _lifesteal_owners,
        AdequacyCondition.OMNIVAMP_STAT: _omnivamp_owners,
        AdequacyCondition.SATURATING_OMNIVAMP: _saturating_omnivamp_owners,
        AdequacyCondition.KEYSTONE_SELF_HEAL: _keystone_self_heal_owners,
        AdequacyCondition.EMPOWERED_BASIC_ATTACK: _empowered_auto_owners,
        AdequacyCondition.RAW_ROW_STREAM_HOLDER: _raw_row_stream_owners,
        AdequacyCondition.EXECUTE_THRESHOLD_STAMP: _execute_threshold_owners,
        AdequacyCondition.ORDERED_INTERACTION_METADATA: _ordered_interaction_owners,
        AdequacyCondition.SELF_SHIELD_PROC: _self_shield_proc_owners,
    }
)

_SHIELD_PROBES: Mapping[
    AdequacyCondition, Callable[[Any], tuple[MechanicOwner, ...]]
] = MappingProxyType(
    {
        AdequacyCondition.TARGET_THRESHOLD_HEAL: _threshold_heal_owners,
        AdequacyCondition.PAIR_OUTCOME_STREAM: _pair_outcome_owners,
    }
)

# Declaration order is evaluation order, so a caller that stops at the first
# demand always does the same work in the same order.
LEDGER_CONDITIONS: tuple[AdequacyCondition, ...] = tuple(_LEDGER_PROBES)
SHIELD_OUTCOME_CONDITIONS: tuple[AdequacyCondition, ...] = tuple(_SHIELD_PROBES)

_UNSERVED: Mapping[ResultProjection, frozenset[AdequacyCondition]] = MappingProxyType(
    {
        ResultProjection.LIGHT_TUPLE_LEDGER: frozenset(LEDGER_CONDITIONS),
        ResultProjection.DICT_ROW_LEDGER: frozenset(),
        ResultProjection.SKIPPED_SHIELD_OUTCOME: frozenset(SHIELD_OUTCOME_CONDITIONS),
        ResultProjection.RESOLVED_SHIELD_OUTCOME: frozenset(),
    }
)


class ProjectionRegistryError(RuntimeError):
    """A projection or condition declaration is structurally invalid."""


def _validate_declarations() -> None:
    """Structural cross-check of this module's four tables, at import.

    Four claims, each of which a later edit could break silently: every
    condition is declared exactly once; every condition has exactly one
    probe across the two gates; the two gates' unserved sets cover the enum
    and overlap on exactly the shared clause; and that shared clause is
    literally one function object in both registries rather than two
    functions that happen to agree today.
    """
    if len(DECLARATIONS) != len(_DECLARATIONS):
        raise ProjectionRegistryError("two declarations name one condition")
    missing = set(AdequacyCondition) - set(DECLARATIONS)
    if missing:
        raise ProjectionRegistryError(
            "undeclared adequacy conditions: "
            + ", ".join(sorted(condition.value for condition in missing))
        )
    if set(_UNSERVED) != set(ResultProjection):
        raise ProjectionRegistryError("a projection declares no unserved set")
    probed = frozenset(LEDGER_CONDITIONS) | frozenset(SHIELD_OUTCOME_CONDITIONS)
    if probed != set(AdequacyCondition):
        raise ProjectionRegistryError(
            "every condition needs a probe on the gate that reads it"
        )
    shared = frozenset(LEDGER_CONDITIONS) & frozenset(SHIELD_OUTCOME_CONDITIONS)
    if shared != {AdequacyCondition.TARGET_THRESHOLD_HEAL}:
        raise ProjectionRegistryError(
            "the two gates share exactly the threshold-heal clause; "
            f"they now share {sorted(condition.value for condition in shared)}"
        )
    for condition in shared:
        if _LEDGER_PROBES[condition] is not _SHIELD_PROBES[condition]:
            raise ProjectionRegistryError(
                f"{condition.value} is read by two functions, not one; a "
                "mirrored clause is a clause that can diverge"
            )


_validate_declarations()


def unserved_conditions(
    projection: ResultProjection,
) -> frozenset[AdequacyCondition]:
    """The conditions ``projection`` cannot answer for its readers."""
    return _UNSERVED[projection]


def _demands(
    conditions: Sequence[AdequacyCondition],
    probes: Mapping[AdequacyCondition, Callable[[Any], tuple[MechanicOwner, ...]]],
    inputs: Any,
    *,
    stop_at_first: bool,
) -> tuple[LedgerDemand, ...]:
    """Every reader this fight arms among ``conditions``, in declared order."""
    found: list[LedgerDemand] = []
    for condition in conditions:
        declaration = DECLARATIONS[condition]
        for owner in probes[condition](inputs):
            found.append(
                LedgerDemand(
                    condition=condition,
                    owner=owner,
                    reader=declaration.reader,
                    reason=declaration.reason,
                )
            )
        if found and stop_at_first:
            break
    return tuple(found)


def ledger_demands(inputs: LedgerInputs) -> tuple[LedgerDemand, ...]:
    """Every damage-ledger reader this fight arms, as named receipts."""
    return _demands(LEDGER_CONDITIONS, _LEDGER_PROBES, inputs, stop_at_first=False)


def shield_outcome_demands(inputs: ShieldOutcomeInputs) -> tuple[LedgerDemand, ...]:
    """Every shield-outcome reader this fight arms, as named receipts."""
    return _demands(
        SHIELD_OUTCOME_CONDITIONS, _SHIELD_PROBES, inputs, stop_at_first=False
    )


def ledger_projection(inputs: LedgerInputs) -> ResultProjection:
    """The narrowest damage-ledger shape that still serves every reader.

    Stops at the first demand: one starved reader settles the projection.
    """
    starved = _demands(LEDGER_CONDITIONS, _LEDGER_PROBES, inputs, stop_at_first=True)
    if starved:
        return ResultProjection.DICT_ROW_LEDGER
    return ResultProjection.LIGHT_TUPLE_LEDGER


def shield_outcome_projection(inputs: ShieldOutcomeInputs) -> ResultProjection:
    """Whether the one-pair shield outcome may be skipped for this fight."""
    starved = _demands(
        SHIELD_OUTCOME_CONDITIONS, _SHIELD_PROBES, inputs, stop_at_first=True
    )
    if starved:
        return ResultProjection.RESOLVED_SHIELD_OUTCOME
    return ResultProjection.SKIPPED_SHIELD_OUTCOME


__all__ = [
    "AdequacyCondition",
    "AdequacyDeclaration",
    "DECLARATIONS",
    "LEDGER_CONDITIONS",
    "LedgerDemand",
    "LedgerInputs",
    "ProjectionRegistryError",
    "ResultProjection",
    "SHIELD_OUTCOME_CONDITIONS",
    "ShieldOutcomeInputs",
    "UndeclaredStatRead",
    "ledger_demands",
    "ledger_projection",
    "shield_outcome_demands",
    "shield_outcome_projection",
    "unserved_conditions",
]
