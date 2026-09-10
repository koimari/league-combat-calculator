"""What each adequacy condition demands of a build, and which reader serves it."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType

from .trigger_stream import MechanicOwner


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


_ITEM_HEAL_READER = "pipeline._item_self_healing_events"


_LIFESTEAL_READER = "fight.autos.on_hit_stream._add_lifesteal_events"


_OMNIVAMP_READER = "fight.autos.on_hit_stream._add_omnivamp_events"


_BASIC_ATTACK_READER = "fight.ledger.event_ledger._ordered_damage_events"


_SUPPORT_SCAN_READER = "item_support_effects.derive_item_support_effects"


_EXECUTE_READER = "fight.after.execute_display._add_execute_display"


_KEYSTONE_HEAL_READER = "pipeline._keystone_self_healing_events"


_INTERACTION_ROW_READER = "fight.ledger.event_ledger._ordered_damage_events"


_TAKEDOWN_READER = "trigger_stream.authored_triggers"


_HEALING_READER = "healing.derive_self_healing"


_THRESHOLD_READER = "fight.after.shield_outcome._resolve_starting_shield_outcome"


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
