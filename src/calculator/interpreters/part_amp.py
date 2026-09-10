"""The amps that multiply one damage part rather than a chain slot."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import partial
from typing import Any

from ..ability_spec import AttackClass, DamageClass
from ..item_behavior import (
    BehaviorRule,
    EngineLane,
    FightFacts,
    Fixed,
    KernelField,
    PartAmpRule,
    RuleFamily,
    StatScaled,
)
from ..item_behavior_catalog import behavior_rules, build_context
from ..reference_vocabulary import ValueRefError
from ..value_ref import resolve_flat
from .amp_magnitude import (
    AMP_BASE_FRACTION_FIELD,
    AMP_FRACTION_FIELD,
    AMP_PER_HUNDRED_STAT_FIELD,
    DeltaAmpInterpretationError,
    _declared_field,
    amp_fields,
)


@dataclass(frozen=True, slots=True)
class PartAmp:
    """A per-part amplifier, resolved for one build.

    The chain's :class:`AmpSlot` answers "what does the running total get
    multiplied by at position *n*".  This answers a different question — "what
    does each part I am allowed to price get multiplied by" — and it is a
    separate type because the two must never be summed into one another's
    fold.  Everything else is deliberately the same shape: rules and their
    compiled fields in build order, and the engine's own ``1.0 + sum`` fold.
    """

    attack_class: AttackClass
    rules: tuple[BehaviorRule, ...]
    fields: tuple[tuple[KernelField, ...], ...]

    def _terms(
        self, index: int, holder_stats: Mapping[str, float]
    ) -> tuple[float, ...]:
        """One holder's fraction, as the shares its magnitude is made of.

        Shares rather than one number because addition is not associative:
        the registry compiled a stat-scaled amp as ``1 + base + rate x`` and
        folding its two halves before the ``1`` lands on a different float.
        Every other magnitude has exactly one share, for which the two
        spellings coincide.

        A stat-scaled magnitude is read here rather than at build time, and
        the reading is *required*: a holder stat the caller did not supply is
        a caller that does not know what it is holding, which is a
        programming error and never a zero-mana Actualizer.
        """
        magnitude = self.rules[index].payload.magnitude
        declared = partial(_declared_field, self.rules[index], self.fields[index])
        if not isinstance(magnitude, StatScaled):
            return (declared(AMP_FRACTION_FIELD),)
        if magnitude.stat.value not in holder_stats:
            raise DeltaAmpInterpretationError(
                f"{self.rules[index].mechanic_id} scales with the holder's "
                f"{magnitude.stat.value}, which the caller did not supply; a "
                "missing stat is an unanswered question, not a zero"
            )
        reading = float(holder_stats[magnitude.stat.value])
        return (
            declared(AMP_BASE_FRACTION_FIELD),
            declared(AMP_PER_HUNDRED_STAT_FIELD) * (reading / 100.0),
        )

    def fractions(self, holder_stats: Mapping[str, float]) -> tuple[float, ...]:
        """Each holder's sourced fraction, in build order."""
        return tuple(
            sum(self._terms(index, holder_stats)) for index in range(len(self.rules))
        )

    def multiplier(self, holder_stats: Mapping[str, float]) -> float:
        """What the engine multiplies each priced part by.

        One running sum from ``1.0`` over every holder's shares, in build order.
        Holders are additive with each other, as the chain's occupants are.
        """
        total = 1.0
        for index in range(len(self.rules)):
            for term in self._terms(index, holder_stats):
                total += term
        return total

    @property
    def owner(self) -> str:
        """The holder the amp's breakdown row is filed under."""
        return self.rules[0].owner


EVERY_DAMAGE_CLASS: frozenset[DamageClass] = frozenset(DamageClass)


EVERY_ATTACK_CLASS: frozenset[AttackClass] = frozenset(AttackClass)


def _part_amps(owners: Sequence[str]) -> tuple[BehaviorRule, ...]:
    """Every per-part amp *owners* bring, in build order, whatever it prices."""
    return tuple(
        rule
        for owner in owners
        for rule in behavior_rules(owner)
        if rule.family is RuleFamily.DELTA_AMP and isinstance(rule.payload, PartAmpRule)
    )


def part_amp_rules(
    owners: Sequence[str], attack_class: AttackClass
) -> tuple[BehaviorRule, ...]:
    """Every per-part amp *owners* bring that prices *attack_class*.

    The selector is the damage the engine is about to price, never an item
    name.  A rule restricted to one *damage* class is not one of these — it
    is :func:`damage_class_amp_rules`', and both readings multiply."""
    return tuple(
        rule
        for rule in _part_amps(owners)
        if rule.payload.typing.damage_classes == EVERY_DAMAGE_CLASS
        and attack_class in rule.payload.typing.attack_classes
    )


def damage_class_amp_rules(
    owners: Sequence[str], damage_class: DamageClass
) -> tuple[BehaviorRule, ...]:
    """Every per-part amp *owners* bring that prices *damage_class*.

    Abyssal Mask's curse is the one today: it multiplies every magic packet
    however it arrived, which is the attack-class selector's dual and never
    its subset.
    """
    return tuple(
        rule
        for rule in _part_amps(owners)
        if rule.payload.typing.attack_classes == EVERY_ATTACK_CLASS
        and rule.payload.typing.damage_classes == frozenset({damage_class})
    )


def declared_magic_amp(owners: Sequence[str]) -> float:
    """What this build multiplies every magic packet by, from flat references:
    ``1.0`` plus each declared magic-class share, summed in build order — the
    running sum :meth:`PartAmp.multiplier` folds an attack-class amp with.
    """
    total = 1.0
    for rule in damage_class_amp_rules(owners, DamageClass.MAGIC):
        total += _flat_fraction(rule)
    return total


def _flat_fraction(rule: BehaviorRule) -> float:
    """One per-part amp's share, resolved with no fight context to resolve at."""
    magnitude = rule.payload.magnitude
    if not isinstance(magnitude, Fixed):
        raise DeltaAmpInterpretationError(
            f"{rule.mechanic_id} declares a {type(magnitude).__name__} magnitude "
            "and this accessor has no fight to resolve one against; read it "
            "through resolve_part_amp, which is handed a build context"
        )
    try:
        (fraction,) = resolve_flat((magnitude.value,))
    except ValueRefError as exc:
        raise DeltaAmpInterpretationError(
            f"{rule.mechanic_id} declares a reference that needs a level or a "
            "fight fact, and this accessor has neither"
        ) from exc
    return fraction


def resolve_part_amp(
    owners: Sequence[str],
    attack_class: AttackClass,
    *,
    facts: FightFacts,
    lane: EngineLane = EngineLane.PAIR_ENGINE,
) -> PartAmp | None:
    """The per-part amp for one attack class, or ``None`` if nobody has it.

    ``None`` is an answer and not a zero, exactly as it is for a chain slot:
    no holder declares a per-part amp for this damage, so no rule ran and
    there is no multiplier to report.

    ``lane`` names the engine asking, and is the only thing it changes: the
    values are identical and only the lane the fields carry differs, so the
    coupled walk's reading of an amp declaration is the pair engine's reading
    — which is the point, since the walk has to deliver the holder's amps
    itself without becoming a second place the amp is computed.
    """
    rules = part_amp_rules(owners, attack_class)
    if not rules:
        return None
    compiled = tuple(
        amp_fields(
            rule,
            build_context(rule.owner, facts),
            lane,
        )
        for rule in rules
    )
    return PartAmp(attack_class=attack_class, rules=rules, fields=compiled)


def _armed_part_multiplier(
    owners: Sequence[str],
    attack_class: AttackClass,
    *,
    armed: bool,
    holder_stats: Mapping[str, float],
    facts: FightFacts,
) -> tuple[float, str]:
    """The walk's reading of one part amp: its multiplier and its holder.

    ``armed`` is whether the amp's activation is up at all.  An unarmed build
    gets ``(1.0, "")``, so an amp is never reported against an item whose window
    did not run, which is ``fight.setup.combat_state._part_amp``'s convention for the pair engine.
    """
    if not armed:
        return 1.0, ""
    amp = resolve_part_amp(
        owners, attack_class, lane=EngineLane.RECEIPT_WALK, facts=facts
    )
    if amp is None:
        return 1.0, ""
    return amp.multiplier(holder_stats), amp.owner


@dataclass(frozen=True, slots=True)
class StaticHolderAmps:
    """The holder's own static, pair-local amplifiers, resolved for one build.

    Three numbers, all three :class:`PartAmpRule` declarations of this family
    and reached by two selectors, which is why this type exists instead of a
    bare float per caller.  ``ability`` and ``basic`` are selected by the
    attack class they price; ``magic`` is Abyssal Mask's Unmake, selected by
    the damage class it restricts and applied by ``fight.resists._mitigate`` on the
    defender's side.  Both readings meet here, once, because dropping either
    term is the exact deletion Amendment M, Ruling 1 forbids.

    "Static" and "pair-local" are the scope: these are the amplifiers the
    holder's own build brings to its own damage, resolved at build time and
    unchanging through the fight.  The timed, roster-wide modifiers a
    ``damage_modifier`` packet carries are a different thing, arrive through
    ``ActionKind.DAMAGE_MODIFIER``, and are not composed here.
    """

    magic: float = 1.0
    ability: float = 1.0
    basic: float = 1.0
    ability_owner: str = ""
    basic_owner: str = ""

    def factor_for(self, damage_type: str, attack_class: AttackClass) -> float:
        """What one packet of this class and this delivery is multiplied by.

        The pair engine's own order: ``fight.resists._mitigate`` multiplies magic damage by
        the magic amp whatever delivered it, and the part amp multiplies on top, by
        the ability amp or the basic amp.  ``AttackClass.OTHER`` takes neither.
        """
        factor = self.magic if damage_type == "magic" else 1.0
        if attack_class is AttackClass.ABILITY:
            factor *= self.ability
        elif attack_class is AttackClass.BASIC_ATTACK:
            factor *= self.basic
        return factor


def resolve_static_holder_amps(
    items: Sequence[Mapping[str, Any]],
    *,
    holder_stats: Mapping[str, float],
    ability_amp_armed: bool,
    facts: FightFacts,
) -> StaticHolderAmps:
    """One holder's three static amps, read from the declarations that produce them.

    The reading the **coupled walk** makes so it can deliver the holder's amps
    itself rather than receiving them pre-multiplied inside another engine's
    rows — Amendment M, Ruling 1's retiring act for this family, in one
    function.

    ``facts`` is :func:`resolve_part_amp`'s own fight facts, forwarded as one
    record rather than re-listed.

    ``ability_amp_armed`` is the caller's answer to whether the ability amp's
    window is up, because that amp rides an item active and a build that never
    triggered it amplifies nothing — the same question
    ``damage._resolve_combat_state`` answers from ``actualizer_active_until``.
    It is a required argument rather than a defaulted one: guessing it would
    arm an amp nobody triggered, which is a number invented rather than
    delivered.
    """
    owners = [str(item.get("name", "")) for item in items]
    ability, ability_owner = _armed_part_multiplier(
        owners,
        AttackClass.ABILITY,
        armed=ability_amp_armed,
        holder_stats=holder_stats,
        facts=facts,
    )
    basic, basic_owner = _armed_part_multiplier(
        owners,
        AttackClass.BASIC_ATTACK,
        armed=True,
        holder_stats=holder_stats,
        facts=facts,
    )
    return StaticHolderAmps(
        magic=declared_magic_amp(owners),
        ability=ability,
        basic=basic,
        ability_owner=ability_owner,
        basic_owner=basic_owner,
    )
