"""The precision registry — rounding is presentation, and this is its home.

Rounding a number is a decision about how it is *shown*, not about what it
is, and until this module the decision was made 118 times inside the kernel:
72 in ``survival/transitions``, 38 in ``survival/receipt_state``, six in
``survival/compile``, one each in ``accumulate`` and ``score_state``.  A
digit count spelled at the call site is unverifiable — nothing can say what
the precision of a field *is*, only what one line happened to do to it — so
every ``(field, digits)`` pair the public projection uses lives here, in one
mapping, and :func:`round_field` is the only rounding this layer performs
(D-71).

The scope of that rule is ``program/``, deliberately.  Within ``program/``
the count of ``round(`` outside this module is **zero**, gated by migration
frontier counter 6.  Within ``survival/`` it is a non-increasing ratchet
rather than zero, because the kernel may not import this module: the phase's
one-way dependency runs ``program -> survival`` and gating the kernel at
zero would invert it.  The kernel's rounding leaves by the projection moving
out, never by the registry moving in.

Cutoffs are the other half.  A rounded number that is only displayed is
presentation; a rounded number that a *rule* then reads is a policy, and the
one live instance of that is the post-death damage cutoff.  It is named
here — :class:`CutoffPolicy` — rather than left as a comment beside the
comparison, because it is exactly the quirk a pure refactor loses silently:
``ROUNDED_DEATH_TIME`` includes an event landing in the sliver between the
walk's raw death time and its millisecond-rounded published one, and nothing
in the arithmetic says so.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from types import MappingProxyType

__all__ = [
    "CutoffPolicy",
    "ROUNDING",
    "damage_cutoff",
    "digits_for",
    "round_field",
]


# Every ``(field, digits)`` pair the end-of-walk survival projection uses.
# The key is the field's path in the published row: a bare name for a
# top-level field, ``block.name`` for one inside a published sub-block, so
# two blocks may hold the same leaf name at different precisions without the
# registry having to guess which one a caller meant.
#
# The digits are the ones the kernel used before the projection moved out,
# field for field.  That is the whole of why this table is a transcription
# and not a design: a stage labelled pure may relocate a decision but may not
# revise it, and the two published precisions (1 for a health-scale
# magnitude, 3 for a timestamp, 6 for a ratio or factor) are a convention
# this registry now makes visible rather than one it invents.
_ROUNDING: dict[str, int] = {
    # magnitudes on the health scale
    "max_health": 1,
    "ending_health": 1,
    "damage_taken": 1,
    "overkill": 1,
    "health_damage": 1,
    "shield_absorbed": 1,
    "healing_received": 1,
    "overhealing": 1,
    "healing_reduced": 1,
    "support_shield_received": 1,
    "support_shield_expired": 1,
    "temporary_health_received": 1,
    "effective_health": 1,
    "remaining_shield": 1,
    "starting_shield": 1,
    "revive_health_restored": 1,
    "damage_deferral_pending": 1,
    "damage_deferral_cleared": 1,
    "defy_heal_received": 1,
    # timestamps, to the millisecond
    "temporary_health_until": 3,
    "healing_reduction_until": 3,
    "venom_until": 3,
    "death_time": 3,
    "first_death_time": 3,
    "revive_time": 3,
    "execute_time": 3,
    "stasis_until": 3,
    "invulnerable_until": 3,
    "untargetable_until": 3,
    "spell_shield_until": 3,
    "defy_trigger_time": 3,
    "damage_deferral_fraction": 3,
    "force_of_nature.stacks_until": 3,
    # dynamic resistances, published at timestamp precision rather than
    # ratio precision because that is what the kernel did with them
    "force_of_nature.dynamic_bonus_magic_resistance": 3,
    "jaksho.dynamic_bonus_armor": 3,
    "jaksho.dynamic_bonus_magic_resistance": 3,
    # ratios and factors
    "ending_health_ratio": 6,
    "venom_factor": 6,
}

ROUNDING: Mapping[str, int] = MappingProxyType(_ROUNDING)


class UnregisteredField(KeyError):
    """A field asked this registry for a precision it never declared.

    Fail closed and by name.  The alternative — a default digit count — is
    the campaign's own failure shape one layer down: a field nobody decided
    the precision of would be published at some precision anyway, and no
    reader could tell that answer from a decided one.
    """


def digits_for(field: str) -> int:
    """The declared precision of *field*, or raise naming it.

    Args:
        field: the published field's path — a bare name, or ``block.name``
            for a field inside a published sub-block.

    Raises:
        UnregisteredField: *field* has no declared precision.
    """
    try:
        return _ROUNDING[field]
    except KeyError:
        raise UnregisteredField(
            f"{field!r} has no declared precision; add it to "
            f"program.precision.ROUNDING rather than rounding at the call site"
        ) from None


def round_field(field: str, value: float) -> float:
    """Round *value* at *field*'s declared precision.

    The only rounding ``program/`` performs.  ``None`` is not accepted: an
    absent value and a value rounded to zero are different answers, and the
    projection decides which one it has before it asks for a precision.
    """
    return round(float(value), digits_for(field))


class CutoffPolicy(Enum):
    """Which death time a post-death rule reads.

    A fight's breakdown drops each actor's damage after that actor died, and
    the death time it compares against is the **published, rounded** one, not
    the walk's raw float.  An event landing in the sliver between them is
    therefore counted.

    ``ROUNDED_DEATH_TIME`` is that behaviour, named.  Naming it is the whole
    point: the sliver is at most half a millisecond wide, no test that
    existed before this module could see it, and a refactor that reached for
    the raw death time — the obviously more correct number — would have
    changed a published total with nothing to say so.  A second member is
    what a decision to change it looks like; there is deliberately only one
    today, and no default.
    """

    ROUNDED_DEATH_TIME = "rounded_death_time"


def damage_cutoff(
    death_time: float | None,
    fight_duration_seconds: float,
    policy: CutoffPolicy,
) -> float:
    """The last timestamp an actor's damage still counts at.

    Args:
        death_time: the actor's published death time, or ``None`` when the
            actor survived the window.
        fight_duration_seconds: the window, which is the cutoff for a
            survivor.
        policy: which death time to read; required, with no default, because
            the choice is the decision this function exists to name.

    Raises:
        ValueError: *policy* is not a member of :class:`CutoffPolicy`.
    """
    if policy is not CutoffPolicy.ROUNDED_DEATH_TIME:
        raise ValueError(f"unknown cutoff policy {policy!r}")
    if death_time is None:
        return float(fight_duration_seconds)
    return float(death_time)
