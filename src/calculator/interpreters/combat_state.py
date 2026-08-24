"""Defences that accrue, or are spent, while the fight is in progress.

Four mechanics that share one property and no arithmetic: none of them is
worth anything at ``t = 0``.  Force of Nature and Jak'Sho publish a *stack
schedule* the ordered ledger then arms, Annul publishes a spell shield the
first hostile ability consumes, and Time Stop publishes a stasis the
scenario has to say is running — so what this interpreter resolves is
metadata, and the zero every one of them starts at is a declared opening
state rather than a number that came out small.

That distinction is the reason the family exists.  A resolver that wrote
Steadfast's maximum-stack resistance into the opening state would be paying
a tank seventy magic resistance for standing still, and nothing in the
published payload would say where it came from.
"""

from __future__ import annotations

from collections.abc import Mapping

from ..item_behavior import (
    BehaviorRule,
    DefenseField,
    DefenseMechanic,
    DefenseOption,
    DefenseOutcome,
    DefenseSubject,
)
from .defense_state import DefenseInterpretationError, DefenseSlot

NOTES: Mapping[DefenseMechanic, str] = {
    DefenseMechanic.ANNUL: (
        "{owner}'s Annul spell shield is ready at the opening and "
        "consumes the first authored hostile ability; its sourced cooldown "
        "rearms the shield only once fully elapsed, and the timer restarts "
        "on champion damage."
    ),
    DefenseMechanic.STEADFAST: (
        "{owner} Steadfast starts at zero stacks; the ordered ledger "
        "arms one stack per eligible magic-damage cast instance per second "
        "and grants the sourced maximum-stack resistance bonus."
    ),
    DefenseMechanic.TIME_STOP: (
        "{owner} Time Stop is explicitly active for "
        "{seconds:g} seconds from the scenario input; "
        "it is never assumed active by item presence alone."
    ),
}

# Voidborn Resilience's sentence names the item by its short wiki name rather
# than by the registry's full one, so it is fixed text: interpolating the
# owner would publish "Jak'Sho, The Protean Voidborn Resilience", which is a
# sentence nobody wrote.
VOIDBORN_NOTE = (
    "Jak'Sho Voidborn Resilience starts at zero combat seconds and "
    "multiplies bonus armor and magic resistance by 30% after five "
    "seconds in champion combat."
)

# The two state-source labels these mechanics publish.
ANNUL_SOURCE = "{owner} — Annul"
TIME_STOP_SOURCE = "{owner} — Time Stop"

# Which resolved field each of Steadfast's and Voidborn's sourced keys lands
# in.  A pairing rather than a branch each: the schedule is metadata copied
# through, and a table says so in one place instead of six statements saying
# it six times.
_STACK_SCHEDULE: Mapping[DefenseMechanic, tuple[tuple[str, DefenseField], ...]] = {
    DefenseMechanic.STEADFAST: (
        ("steadfast_stack_duration", DefenseField.FORCE_STACK_DURATION),
        ("steadfast_max_stacks", DefenseField.FORCE_MAX_STACKS),
        ("steadfast_stack_interval", DefenseField.FORCE_STACK_INTERVAL),
        ("steadfast_immobilize_stacks", DefenseField.FORCE_IMMOBILIZE_STACKS),
        (
            "steadfast_bonus_magic_resistance",
            DefenseField.FORCE_BONUS_MAGIC_RESISTANCE,
        ),
        (
            "steadfast_bonus_move_speed_percent",
            DefenseField.FORCE_BONUS_MOVE_SPEED_PERCENT,
        ),
    ),
    DefenseMechanic.VOIDBORN_RESILIENCE: (
        ("voidborn_stack_interval", DefenseField.JAKSHO_STACK_INTERVAL),
        ("voidborn_max_stacks", DefenseField.JAKSHO_MAX_STACKS),
        (
            "voidborn_bonus_resistance_multiplier",
            DefenseField.JAKSHO_BONUS_RESISTANCE_MULTIPLIER,
        ),
    ),
}

# The two schedule fields the resolved state carries as whole stacks rather
# than as floats, because a stack count is a count.
_INTEGER_FIELDS = frozenset(
    {
        DefenseField.FORCE_MAX_STACKS,
        DefenseField.FORCE_IMMOBILIZE_STACKS,
        DefenseField.JAKSHO_MAX_STACKS,
    }
)


def resolve_combat_state(rule: BehaviorRule, subject: DefenseSubject) -> DefenseOutcome:
    """One combat state, against the subject it is defending."""
    slot = DefenseSlot(rule)
    mechanic = slot.mechanic
    if mechanic is DefenseMechanic.ANNUL:
        return _annul(slot)
    if mechanic is DefenseMechanic.TIME_STOP:
        return _time_stop(slot, subject)
    if mechanic in _STACK_SCHEDULE:
        return _stack_schedule(slot)
    raise DefenseInterpretationError(
        f"{rule.mechanic_id} declares combat_state and this family has no "
        "branch for it; a state with no arithmetic is a mechanic that would "
        "silently do nothing"
    )


def _annul(slot: DefenseSlot) -> DefenseOutcome:
    """A spell shield ready at the opening, and the item that granted it."""
    return DefenseOutcome(
        fields=(
            slot.grant(DefenseField.SPELL_SHIELD_READY, True),
            slot.grant(
                DefenseField.SPELL_SHIELD_SOURCE, ANNUL_SOURCE.format(owner=slot.owner)
            ),
        ),
        notes=(NOTES[slot.mechanic].format(owner=slot.owner),),
    )


def _time_stop(slot: DefenseSlot, subject: DefenseSubject) -> DefenseOutcome:
    """Stasis, and only for as many seconds as the scenario supplied.

    Nothing is granted without the input: an hourglass in the build says the
    holder *could* stop time, not that they did, and the difference is the
    whole reason the option exists.
    """
    supplied = subject.option(slot.owner, DefenseOption.STASIS_ACTIVE_SECONDS)
    if supplied <= 0.0:
        return DefenseOutcome(fields=(), notes=())
    seconds = min(slot.value("stasis_duration"), supplied)
    return DefenseOutcome(
        fields=(
            slot.grant(DefenseField.STARTING_STASIS_DURATION, seconds),
            slot.grant(
                DefenseField.STARTING_STASIS_SOURCE,
                TIME_STOP_SOURCE.format(owner=slot.owner),
            ),
        ),
        notes=(NOTES[slot.mechanic].format(owner=slot.owner, seconds=seconds),),
    )


def _stack_schedule(slot: DefenseSlot) -> DefenseOutcome:
    """The stack schedule the ordered ledger arms, copied through as metadata."""
    fields = tuple(
        slot.grant(
            field,
            int(slot.value(key)) if field in _INTEGER_FIELDS else slot.value(key),
        )
        for key, field in _STACK_SCHEDULE[slot.mechanic]
    )
    note = NOTES.get(slot.mechanic)
    return DefenseOutcome(
        fields=fields,
        notes=(note.format(owner=slot.owner) if note else VOIDBORN_NOTE,),
    )


__all__ = [
    "ANNUL_SOURCE",
    "NOTES",
    "TIME_STOP_SOURCE",
    "VOIDBORN_NOTE",
    "resolve_combat_state",
]
