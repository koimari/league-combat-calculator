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

**What this registry is not.**  A rounded number nobody publishes is not
presentation and does not belong here.  The one live instance is the
tolerance a trigger *lookup* keys on: the compiler writes a self-heal's
trigger index under a normalized timestamp and the kernel reads it back
under the same one, so the two must agree exactly or the link silently stops
matching.  Its reader is ``survival.compile.heal_trigger_key``, on the far
side of a dependency that runs ``program -> survival`` and never back, so
``TRIGGER_TIME_KEY_DIGITS`` and ``trigger_time_key`` live *there*, beside
that reader, and ``program/compile.py`` imports them.  A copy here would be
one tolerance with two spellings on opposite sides of a boundary only one of
them can cross — which is the failure this module exists to prevent, not a
tidier filing of it.

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
    "ROUNDING_BY_VIEW",
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
_SURVIVAL_ROUNDING: dict[str, int] = {
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
    "grey_health_stored": 6,
    "grey_health_consumed": 6,
}

# The breakdown view's own leaves.  A second table rather than more rows in
# the first, because "which view publishes this leaf" is a question the
# registry should answer: the survival table is a transcription of what the
# kernel did, and a leaf added to it by a reader who only meant to publish a
# breakdown number would silently join the survival row's pinned key order.
_BREAKDOWN_ROUNDING: dict[str, int] = {
    "total_damage": 1,
    "outgoing_damage_before_death": 1,
    "incoming_damage": 1,
    "support_value": 1,
    "healing_output": 1,
}

# The receipt view's own leaves, one table per published block.  The block
# prefix is load-bearing rather than decorative: ``amount`` is published at
# one digit on a healing row and at six on a support row, and
# ``grey_health_stored`` at one on a damage row and at six on a survival row.
# A flat registry would have had to guess which caller meant which, so the
# key is the leaf's path in the payload and the collision check below is what
# turns a future guess into an import error.
_EVENTS_ROUNDING: dict[str, int] = {
    "events.time": 3,
    "events.damage": 1,
    "events.raw_damage": 1,
    "events.pair_damage": 1,
    "events.overkill": 1,
    "events.maw_lifeline_omnivamp_activated": 3,
    "events.threshold_shield_expires_at": 3,
    "events.redirected_amount": 1,
    "events.redirect_fraction": 6,
    "events.incoming_damage_multiplier": 3,
    "events.incoming_damage_reduction": 1,
    "events.wound_duration": 3,
    "events.wound_until": 3,
    "events.grey_health_stored": 1,
    "events.live_amp_bonus": 1,
}

_HEALING_EVENTS_ROUNDING: dict[str, int] = {
    "healing_events.time": 3,
    "healing_events.amount": 1,
    "healing_events.raw_amount": 1,
    "healing_events.applied_amount": 1,
    "healing_events.overheal": 1,
    "healing_events.temporary_health": 1,
    "healing_events.temporary_health_expires_at": 3,
    "healing_events.reduced_amount": 1,
    "healing_events.healing_reduction_factor": 3,
    "healing_events.ichorshield_generated": 1,
    "healing_events.ichorshield_total": 1,
}

_SUPPORT_EVENTS_ROUNDING: dict[str, int] = {
    "support_events.time": 3,
    "support_events.amount": 6,
    "support_events.applied_amount": 6,
    "support_events.duration": 3,
    "support_events.expires_at": 3,
    "support_events.bonus_attack_speed_percent": 6,
    "support_events.on_hit_magic_damage": 6,
    "support_events.ability_power": 6,
    "support_events.ability_haste": 6,
    "support_events.bonus_move_speed_percent": 6,
    "support_events.slow_percent": 6,
    "support_events.chain_fraction": 6,
    "support_events.multiplier": 6,
    "support_events.cooldown": 6,
    "support_events.charges_consumed": 6,
    "support_events.beam_delay": 6,
    "support_events.armor_reduction_percent": 6,
    "support_events.mr_reduction_percent": 6,
    "support_events.stack_count": 6,
    "support_events.current_mana": 6,
    "support_events.mana_threshold": 6,
    "support_events.nearby_enemy_count": 6,
    "support_events.multi_target_multiplier": 6,
    "support_events.cooldown_until": 6,
    "support_events.gold_amount": 6,
    "support_events.ward_uses": 6,
    "support_events.quest_threshold": 6,
    "support_events.minion_kills": 6,
}

# The TDD view's leaves -- the objective block's totals.
_OBJECTIVE_ROUNDING: dict[str, int] = {
    "objective.main_team_damage_before_death": 1,
    "objective.enemy_team_damage_before_death": 1,
    "objective.focus_damage_before_death": 1,
    "objective.focus_support_value": 1,
    "objective.focus_healing": 1,
    "objective.main_team_effective_health": 1,
    "objective.enemy_team_effective_health": 1,
    "objective.total_support_value": 1,
    "objective.total_healing_reduced": 1,
}


ROUNDING_BY_VIEW: Mapping[str, Mapping[str, int]] = MappingProxyType(
    {
        "survival": MappingProxyType(_SURVIVAL_ROUNDING),
        "breakdown": MappingProxyType(_BREAKDOWN_ROUNDING),
        "receipt": MappingProxyType(
            {**_EVENTS_ROUNDING, **_HEALING_EVENTS_ROUNDING, **_SUPPORT_EVENTS_ROUNDING}
        ),
        "tdd": MappingProxyType(_OBJECTIVE_ROUNDING),
    }
)

# One flat lookup for :func:`digits_for`, asserted disjoint at import: two
# views declaring one leaf name at two precisions would make the flat answer
# depend on merge order, which is a coin toss wearing a registry's name.
_TABLES = (
    _SURVIVAL_ROUNDING,
    _BREAKDOWN_ROUNDING,
    _EVENTS_ROUNDING,
    _HEALING_EVENTS_ROUNDING,
    _SUPPORT_EVENTS_ROUNDING,
    _OBJECTIVE_ROUNDING,
)
_FLAT: dict[str, int] = {}
for _table in _TABLES:
    _COLLISIONS = set(_FLAT) & set(_table)
    if _COLLISIONS:  # pragma: no cover - a declaration defect, not a runtime one
        raise ValueError(
            "two views declare a precision for the same leaf: "
            + ", ".join(sorted(_COLLISIONS))
        )
    _FLAT.update(_table)

ROUNDING: Mapping[str, int] = MappingProxyType(_FLAT)


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
        return ROUNDING[field]
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
