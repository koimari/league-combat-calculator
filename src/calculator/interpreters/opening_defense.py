"""Defences already in force when the modeled exchange opens.

Six mechanics, and until this module every one of them was an
``if "<item name>" in names`` branch inside the defensive resolver: a shield
read off the subject's own maximum health, two multipliers over incoming
basic damage, a flat reduction with a cap, a level-ramped shield the
scenario has to supply a starting value for, and a disclosure that says a
seventh mechanic is deliberately *not* resolved here.

What the branches decided by name, the declarations now decide by shape:
which numbers the mechanic may read, which resolved fields it may write, and
what it discloses.  The sentences are here rather than in the declaration
because a published assumption is presentation — criterion 6 admits no open
string as policy — and because keeping them beside the arithmetic that
qualifies them is what stops a note describing a branch that no longer runs.
"""

from __future__ import annotations

from collections.abc import Mapping

from ..item_behavior import (
    BehaviorRule,
    BuildContext,
    DefenseField,
    DefenseMechanic,
    DefenseOption,
    DefenseOutcome,
    DefenseSubject,
    EngineLane,
    KernelField,
    RuleFamily,
)
from . import defense_state
from .defense_state import DefenseInterpretationError, DefenseSlot

# One published sentence per mechanic, formatted with the owner the
# declaration named.  Two of them are fixed text because the wiki's own
# wording does not name the item; the rest interpolate, which is how the
# retired ladder's f-strings produced the same line for two Noxian boots.
NOTES: Mapping[DefenseMechanic, str] = {
    DefenseMechanic.MAGEBANE: (
        "Magebane is ready because the target has not taken magic damage "
        "during the previous 15 seconds."
    ),
    DefenseMechanic.BLESSING_OF_THE_MOUNTAIN: (
        "Blessing of the Mountain starts Blessed, reduces incoming champion "
        "damage by 35%, and lingers for two seconds after the last hit."
    ),
    DefenseMechanic.PLATING: "Plating reduces every non-true basic-damage instance.",
    DefenseMechanic.ROCK_SOLID: (
        "Rock Solid reduces the first post-mitigation basic-damage "
        "instance of each attack or cast."
    ),
    DefenseMechanic.RESILIENCE: "Resilience reduces damage from critical strikes.",
    DefenseMechanic.UNDAUNTED: (
        "Undaunted blocks a flat amount of every champion attack and "
        "ability, and a smaller flat amount of damage-over-time abilities."
    ),
}

# The Ichorshield's two disclosures: the scenario supplied a starting shield,
# or it did not and the model refuses to guess one from life steal.
ICHORSHIELD_SUPPLIED_NOTE = (
    "{owner}'s Ichorshield starting state is explicitly supplied "
    "by the scenario and capped at the sourced level maximum."
)
ICHORSHIELD_EMPTY_NOTE = (
    "{owner}'s Ichorshield starts empty unless an explicit starting "
    "shield input is supplied; excess lifesteal healing is not guessed."
)

# The one defence this resolver cites without granting: Everlasting's shield
# is the ally packet the same entry declares, and its trigger needs authored
# crowd-control metadata the model will not infer.
EVERLASTING_NOTE = (
    "{owner} Awe is applied through the typed stat conversion; "
    "Everlasting requires authored crowd-control metadata and is not inferred."
)

# The state-source label Blessing of the Mountain publishes.  A state source
# names the item that granted the state, which is a different string from the
# citation label naming the revision it was read from.
BLESSED_SOURCE = "{owner} — Blessed"

# The state-source label Undaunted publishes beside its two reductions.
UNDAUNTED_SOURCE = "{owner} — Undaunted"


class OpeningDefenseResolverInterpreter:  # pylint: disable=too-few-public-methods
    """The defensive resolver's answer for the ``opening_defense`` family."""

    FAMILY = RuleFamily.OPENING_DEFENSE
    LANES = frozenset({EngineLane.DEFENSE_RESOLVER})

    def compile(self, rule: BehaviorRule, ctx: BuildContext) -> tuple[KernelField, ...]:
        """The shape an opening defence compiles to, at build time."""
        return defense_state.compiled_shape(rule, ctx.level)

    def resolve(self, rule: BehaviorRule, subject: DefenseSubject) -> DefenseOutcome:
        """One opening defence, against the subject it is defending."""
        slot = DefenseSlot(rule)
        mechanic = slot.mechanic
        if mechanic is DefenseMechanic.MAGEBANE:
            return _magebane(slot, subject)
        if mechanic is DefenseMechanic.BLESSING_OF_THE_MOUNTAIN:
            return _blessing(slot)
        if mechanic is DefenseMechanic.ICHORSHIELD:
            return _ichorshield(slot, subject)
        if mechanic is DefenseMechanic.PLATING:
            return _one_multiplier(slot, DefenseField.BASIC_DAMAGE_MULTIPLIER)
        if mechanic is DefenseMechanic.ROCK_SOLID:
            return _rock_solid(slot)
        if mechanic is DefenseMechanic.UNDAUNTED:
            return _undaunted(slot)
        if mechanic is DefenseMechanic.RESILIENCE:
            return _one_multiplier(slot, DefenseField.CRITICAL_STRIKE_DAMAGE_MULTIPLIER)
        raise DefenseInterpretationError(
            f"{rule.mechanic_id} declares opening_defense and this interpreter "
            "has no branch for it; a defence with no arithmetic is a mechanic "
            "that would silently grant nothing"
        )


RESOLVER_INTERPRETER = OpeningDefenseResolverInterpreter()


def _magebane(slot: DefenseSlot, subject: DefenseSubject) -> DefenseOutcome:
    """A magic shield worth a sourced share of the subject's maximum health."""
    ratio = slot.value("magic_shield_max_health_ratio")
    return DefenseOutcome(
        fields=(slot.grant(DefenseField.MAGIC_SHIELD, subject.max_health() * ratio),),
        notes=(NOTES[slot.mechanic],),
    )


def _blessing(slot: DefenseSlot) -> DefenseOutcome:
    """A reduction on every incoming champion packet, lingering after the last."""
    return DefenseOutcome(
        fields=(
            slot.grant(
                DefenseField.INCOMING_DAMAGE_MULTIPLIER,
                slot.value("incoming_damage_multiplier"),
            ),
            slot.grant(
                DefenseField.INCOMING_DAMAGE_LINGER,
                slot.value("incoming_damage_linger"),
            ),
            slot.grant(
                DefenseField.INCOMING_DAMAGE_COOLDOWN,
                slot.value("incoming_damage_cooldown"),
            ),
            slot.grant(
                DefenseField.INCOMING_DAMAGE_SOURCE,
                BLESSED_SOURCE.format(owner=slot.owner),
            ),
        ),
        notes=(NOTES[slot.mechanic],),
    )


def _ichorshield(slot: DefenseSlot, subject: DefenseSubject) -> DefenseOutcome:
    """A level-ramped shield cap, and the starting shield only if supplied.

    The cap is always resolved and the starting shield never is unless the
    scenario says so: excess life-steal healing before the modeled exchange
    is a state the model refuses to invent, and the two notes are the two
    halves of saying so out loud.
    """
    cap = slot.late_ramp("ichorshield_min", subject.level)
    supplied = int(subject.option(slot.owner, DefenseOption.STARTING_ICHORSHIELD))
    fields = [slot.grant(DefenseField.BLOODTHIRSTER_SHIELD_CAP, cap)]
    if supplied > 0:
        starting = min(float(supplied), cap)
        fields.append(slot.grant(DefenseField.BLOODTHIRSTER_STARTING_SHIELD, starting))
        fields.append(slot.grant(DefenseField.GENERAL_SHIELD, starting))
        note = ICHORSHIELD_SUPPLIED_NOTE
    else:
        note = ICHORSHIELD_EMPTY_NOTE
    return DefenseOutcome(fields=tuple(fields), notes=(note.format(owner=slot.owner),))


def _one_multiplier(slot: DefenseSlot, field: DefenseField) -> DefenseOutcome:
    """A single sourced multiplier over one class of incoming damage."""
    return DefenseOutcome(
        fields=(slot.grant(field, slot.value(field.value)),),
        notes=(NOTES[slot.mechanic],),
    )


def _rock_solid(slot: DefenseSlot) -> DefenseOutcome:
    """A flat reduction on the first packet of each attack, with its cap."""
    return DefenseOutcome(
        fields=(
            slot.grant(
                DefenseField.BASIC_DAMAGE_FLAT_REDUCTION,
                slot.value("basic_damage_flat_reduction"),
            ),
            slot.grant(
                DefenseField.BASIC_DAMAGE_FLAT_REDUCTION_CAP,
                slot.value("basic_damage_flat_reduction_cap"),
            ),
        ),
        notes=(NOTES[slot.mechanic],),
    )


def _undaunted(slot: DefenseSlot) -> DefenseOutcome:
    """Two flat reductions over champion damage, and the state's source.

    Its own field pair rather than Rock Solid's: this reduction applies to
    every champion attack and ability, and its second number is a separate
    sourced amount for damage over time rather than a cap on the first.
    """
    return DefenseOutcome(
        fields=(
            slot.grant(
                DefenseField.CHAMPION_DAMAGE_FLAT_REDUCTION,
                slot.value("champion_damage_flat_reduction"),
            ),
            slot.grant(
                DefenseField.CHAMPION_DOT_DAMAGE_FLAT_REDUCTION,
                slot.value("champion_dot_damage_flat_reduction"),
            ),
            slot.grant(
                DefenseField.CHAMPION_DAMAGE_FLAT_SOURCE,
                UNDAUNTED_SOURCE.format(owner=slot.owner),
            ),
        ),
        notes=(NOTES[slot.mechanic],),
    )


__all__ = [
    "BLESSED_SOURCE",
    "UNDAUNTED_SOURCE",
    "EVERLASTING_NOTE",
    "ICHORSHIELD_EMPTY_NOTE",
    "ICHORSHIELD_SUPPLIED_NOTE",
    "NOTES",
    "OpeningDefenseResolverInterpreter",
    "RESOLVER_INTERPRETER",
]
