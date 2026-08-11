"""Defences armed by the subject's health crossing a declared fraction.

Seven mechanics and five different arithmetics for one word.  Every Lifeline
is a shield that fires below 30% maximum health, and the shields are worth a
level ramp, a range-split ramp, a base plus bonus attack damage, a share of
maximum mana and a share of bonus health respectively — which is exactly why
the retired resolver had a five-branch ladder keyed on item names inside a
helper called ``_lifeline_defense``.  The branches survive, keyed on the
mechanic each build declares rather than on the name it happens to spell.

Two mechanics are not Lifeline shields at all and are here because a health
threshold is what arms them: Protoplasm Harness grants temporary health and
a heal, and Guardian Angel's Rebirth arms on lethal damage rather than on a
fraction — the declared absence its payload carries as ``threshold=None``.
"""

from __future__ import annotations

from collections.abc import Mapping

from ..item_behavior import (
    BehaviorRule,
    BuildContext,
    DefenseField,
    DefenseMechanic,
    DefenseOutcome,
    DefenseSubject,
    EngineLane,
    KernelField,
    RuleFamily,
)
from . import defense_state
from .defense_state import DefenseInterpretationError, DefenseSlot

# The Lifeline sentence, in the two spellings the wiki's own damage typing
# produces: a magic-only Lifeline says so and a general one does not.
LIFELINE_NOTE = (
    "{owner}'s Lifeline is ready and triggers before{qualifier} damage "
    "that would leave the target below 30% maximum health."
)

MAGIC_QUALIFIER = " magic"

# Maw's temporary omnivamp is granted *after* its shield fires, which is a
# second statement about one mechanic and therefore a second note.
MAW_OMNIVAMP_NOTE = (
    "{owner} grants its sourced temporary omnivamp only "
    "after Lifeline triggers; the ordered ledger schedules that state."
)

NOTES: Mapping[DefenseMechanic, str] = {
    DefenseMechanic.LIFELINE_PROTOPLASM: (
        "{owner}'s Lifeline is ready. Before damage would leave "
        "the target below 30% maximum health, it grants temporary bonus "
        "health and begins its five-second heal."
    ),
    DefenseMechanic.REBIRTH: (
        "{owner}'s Rebirth is ready and restores 50% base health "
        "after four seconds of sourced resurrection stasis."
    ),
}

# The state-source label a resurrection publishes.  Its shape differs from
# every other state source in the resolver, and it differs because the wiki
# names the mechanic in parentheses rather than after a dash.
REBIRTH_SOURCE = "{owner} (Rebirth)"


class ThresholdDefenseResolverInterpreter:  # pylint: disable=too-few-public-methods
    """The defensive resolver's answer for the ``threshold_defense`` family."""

    FAMILY = RuleFamily.THRESHOLD_DEFENSE
    LANES = frozenset({EngineLane.DEFENSE_RESOLVER})

    def compile(self, rule: BehaviorRule, ctx: BuildContext) -> tuple[KernelField, ...]:
        """The shape a threshold defence compiles to, at build time."""
        return defense_state.compiled_shape(rule, ctx.level)

    def resolve(self, rule: BehaviorRule, subject: DefenseSubject) -> DefenseOutcome:
        """One threshold defence, against the subject it is defending."""
        slot = DefenseSlot(rule)
        mechanic = slot.mechanic
        if mechanic is DefenseMechanic.LIFELINE_PROTOPLASM:
            return _protoplasm(slot, subject)
        if mechanic is DefenseMechanic.REBIRTH:
            return _rebirth(slot, subject)
        if mechanic in _LIFELINE_SHIELDS:
            return _lifeline_shield(slot, subject)
        raise DefenseInterpretationError(
            f"{rule.mechanic_id} declares threshold_defense and this "
            "interpreter has no branch for it; a defence with no arithmetic "
            "is a mechanic that would silently grant nothing"
        )


RESOLVER_INTERPRETER = ThresholdDefenseResolverInterpreter()

_LIFELINE_SHIELDS = frozenset(
    {
        DefenseMechanic.LIFELINE_SHIELDBOW,
        DefenseMechanic.LIFELINE_HEXDRINKER,
        DefenseMechanic.LIFELINE_MAW,
        DefenseMechanic.LIFELINE_SERAPH,
        DefenseMechanic.LIFELINE_STERAK,
    }
)


def _lifeline_amount(slot: DefenseSlot, subject: DefenseSubject) -> float:
    """How much shield one Lifeline is worth, by the mechanic's own shape."""
    mechanic = slot.mechanic
    prefix = "melee" if subject.is_melee else "ranged"
    if mechanic is DefenseMechanic.LIFELINE_SHIELDBOW:
        return slot.late_ramp("shield_base", subject.level)
    if mechanic is DefenseMechanic.LIFELINE_HEXDRINKER:
        return slot.ramp(f"shield_{prefix}_min", subject.level)
    if mechanic is DefenseMechanic.LIFELINE_MAW:
        return slot.value(f"shield_{prefix}_base") + slot.value(
            f"shield_{prefix}_bonus_ad_ratio"
        ) * subject.stat("bonus_attack_damage")
    if mechanic is DefenseMechanic.LIFELINE_SERAPH:
        return slot.value("shield_max_mana_ratio") * subject.stat("max_mana")
    return slot.value("shield_bonus_health_ratio") * subject.stat("bonus_health")


def _lifeline_shield(slot: DefenseSlot, subject: DefenseSubject) -> DefenseOutcome:
    """One Lifeline's shield, its threshold, its duration and its typing."""
    absorbs = defense_state.payload(slot.rule).absorbs
    qualifier = MAGIC_QUALIFIER if absorbs.value == "magic" else ""
    fields = [
        slot.grant(
            DefenseField.THRESHOLD_SHIELD_AMOUNT, _lifeline_amount(slot, subject)
        ),
        slot.grant(DefenseField.THRESHOLD_SHIELD_HEALTH_RATIO, slot.threshold()),
        slot.grant(DefenseField.THRESHOLD_SHIELD_DURATION, slot.duration()),
        slot.grant(DefenseField.THRESHOLD_SHIELD_DAMAGE_TYPE, absorbs.value),
    ]
    notes = [LIFELINE_NOTE.format(owner=slot.owner, qualifier=qualifier)]
    if slot.mechanic is DefenseMechanic.LIFELINE_MAW:
        fields.append(
            slot.grant(
                DefenseField.MAW_LIFELINE_OMNIVAMP_PERCENT,
                slot.value("lifeline_omnivamp_percent"),
            )
        )
        notes.append(MAW_OMNIVAMP_NOTE.format(owner=slot.owner))
    return DefenseOutcome(fields=tuple(fields), notes=tuple(notes))


def _protoplasm(slot: DefenseSlot, subject: DefenseSubject) -> DefenseOutcome:
    """Temporary bonus health and a heal that reads the subject's resistances."""
    heal = (
        slot.ramp("heal_min", subject.level)
        + slot.value("heal_bonus_armor_ratio") * subject.stat("bonus_armor")
        + slot.value("heal_bonus_mr_ratio") * subject.stat("bonus_magic_resistance")
    )
    return DefenseOutcome(
        fields=(
            slot.grant(
                DefenseField.THRESHOLD_HEALTH_BONUS,
                slot.ramp("bonus_health_min", subject.level),
            ),
            slot.grant(DefenseField.THRESHOLD_HEALTH_HEAL, heal),
            slot.grant(DefenseField.THRESHOLD_HEALTH_RATIO, slot.threshold()),
            slot.grant(DefenseField.THRESHOLD_HEALTH_DURATION, slot.duration()),
        ),
        notes=(NOTES[slot.mechanic].format(owner=slot.owner),),
    )


def _rebirth(slot: DefenseSlot, subject: DefenseSubject) -> DefenseOutcome:
    """A resurrection worth a sourced share of the subject's base health."""
    return DefenseOutcome(
        fields=(
            slot.grant(
                DefenseField.REVIVE_HEALTH_AMOUNT,
                subject.stat("base_health") * slot.value("revive_health_ratio"),
            ),
            slot.grant(DefenseField.REVIVE_DELAY, slot.value("revive_delay")),
            slot.grant(DefenseField.REVIVE_COOLDOWN, slot.value("revive_cooldown")),
            slot.grant(
                DefenseField.REVIVE_SOURCE, REBIRTH_SOURCE.format(owner=slot.owner)
            ),
        ),
        notes=(NOTES[slot.mechanic].format(owner=slot.owner),),
    )


__all__ = [
    "LIFELINE_NOTE",
    "MAGIC_QUALIFIER",
    "MAW_OMNIVAMP_NOTE",
    "NOTES",
    "REBIRTH_SOURCE",
    "RESOLVER_INTERPRETER",
    "ThresholdDefenseResolverInterpreter",
]
