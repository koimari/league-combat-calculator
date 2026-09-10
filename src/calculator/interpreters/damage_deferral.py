"""The post-mitigation damage a deferral stores and repays as ticks."""

from __future__ import annotations

from dataclasses import dataclass

from ..item_behavior import (
    BehaviorRule,
    DefenseField,
    DefenseMechanic,
    DefenseOutcome,
    DefenseSubject,
)
from .defense_state import DefenseInterpretationError, DefenseSlot

DEFER_FRACTION_FIELD = "defer_fraction"


DEFER_DURATION_FIELD = "defer_duration"


DEFER_TICKS_FIELD = "defer_ticks"


# Ignore Pain's own sentence, published beside the resolved state.  It names
# what the deferral does rather than the item that carries it, because the
# citation beside it already names the item.
IGNORE_PAIN_NOTE = (
    "{owner} Ignore Pain defers the sourced fraction of each "
    "post-mitigation physical or magic packet; Defy clears the "
    "remaining store and heals after a qualifying champion takedown."
)


# Which resolved field each of the deferral's sourced keys lands in, and
# which of them are counts.  A table rather than seven statements saying the
# same thing seven times — and the melee/ranged pair is deliberately absent,
# because which of the two is read is a property of the *subject* and is
# decided below.
_DEFERRAL_SCHEDULE: tuple[tuple[str, DefenseField], ...] = (
    ("damage_deferral_duration", DefenseField.DAMAGE_DEFERRAL_DURATION),
    ("damage_deferral_ticks", DefenseField.DAMAGE_DEFERRAL_TICKS),
    ("defy_window", DefenseField.DEFY_WINDOW),
    ("defy_heal_bonus_ad_ratio", DefenseField.DEFY_HEAL_BONUS_AD_RATIO),
    ("defy_heal_duration", DefenseField.DEFY_HEAL_DURATION),
    ("defy_heal_ticks", DefenseField.DEFY_HEAL_TICKS),
)


_INTEGER_FIELDS = frozenset(
    {DefenseField.DAMAGE_DEFERRAL_TICKS, DefenseField.DEFY_HEAL_TICKS}
)


def resolve_deferral(rule: BehaviorRule, subject: DefenseSubject) -> DefenseOutcome:
    """The deferral schedule, against the subject that will pay it."""
    slot = DefenseSlot(rule)
    if slot.mechanic is not DefenseMechanic.IGNORE_PAIN:
        raise DefenseInterpretationError(
            f"{rule.mechanic_id} declares damage_routing at the resolver and "
            "this family has no branch for it; a schedule with no arithmetic "
            "is a mechanic that would silently do nothing"
        )
    deferred_key = (
        "damage_deferral_melee" if subject.is_melee else "damage_deferral_ranged"
    )
    fields = [
        slot.grant(DefenseField.DAMAGE_DEFERRAL_FRACTION, slot.value(deferred_key))
    ]
    fields.extend(
        slot.grant(
            field,
            int(slot.value(key)) if field in _INTEGER_FIELDS else slot.value(key),
        )
        for key, field in _DEFERRAL_SCHEDULE
    )
    return DefenseOutcome(
        fields=tuple(fields),
        notes=(IGNORE_PAIN_NOTE.format(owner=slot.owner),),
    )


@dataclass(frozen=True, slots=True)
class Deferral:
    """One build's declared damage deferral, as the walk's Defer rider."""

    owner: str
    fraction: float
    duration: float
    ticks: int
