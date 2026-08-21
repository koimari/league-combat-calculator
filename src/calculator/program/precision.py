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

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any

__all__ = [
    "CutoffPolicy",
    "DuplicateSumMember",
    "ROUNDING",
    "ROUNDING_BY_VIEW",
    "SUM_PANELS",
    "SumPlan",
    "damage_cutoff",
    "digits_for",
    "round_field",
    "sum_plan",
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
    "permanent_bonus_health_received": 1,
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
    "crowd_control_until": 3,
    "crowd_control_immunity_until": 3,
    "action_downtime": 3,
    "guardian.cooldown_until": 3,
    "aftershock.until": 3,
    "force_of_nature.stacks_until": 3,
    # dynamic resistances, published at timestamp precision rather than
    # ratio precision because that is what the kernel did with them
    "force_of_nature.dynamic_bonus_magic_resistance": 3,
    "jaksho.dynamic_bonus_armor": 3,
    "jaksho.dynamic_bonus_magic_resistance": 3,
    "aftershock.bonus_armor": 3,
    "aftershock.bonus_magic_resistance": 3,
    # ratios and factors
    "ending_health_ratio": 6,
    "venom_factor": 6,
    "grey_health_stored": 6,
    "grey_health_consumed": 6,
}

# The survival row's CONDITIONAL receipt blocks -- a second table, and not
# more rows in the first, because the first table's keys are the leaves every
# row publishes.  These three blocks are emitted only when their mechanic
# fired (a cleanse activated, an immunity was granted, a spell shield was
# declared), and a reader that walked the survival table expecting to find
# each of its keys on any row would be reading a conditional absence as a
# missing leaf.  The precisions are the same registry either way: ``ROUNDING``
# is flat, so ``round_field`` resolves these exactly like the rest.
_SURVIVAL_RECEIPT_ROUNDING: dict[str, int] = {
    "crowd_control_immunity.active_until": 3,
    "spell_shield.triggered_heal.time": 3,
    "cleanse.downtime_after": 6,
    "spell_shield.triggered_heal.amount": 6,
    "spell_shield.triggered_heal.delay": 6,
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
    "events.cc_duration": 3,
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
    "support_events.raw_amount": 6,
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
    "support_events.bonus_armor": 6,
    "support_events.bonus_magic_resistance": 6,
    "support_events.bonus_health": 6,
    "support_events.permanent_bonus_health": 6,
    "support_events.slow_resist_percent": 6,
    "support_events.aftershock_duration": 6,
    "support_events.aftershock_cooldown": 6,
    "support_events.glacial_ray_count": 6,
    "support_events.glacial_zone_radius_units": 6,
    "support_events.glacial_zone_width_units": 6,
    "support_events.glacial_zone_duration": 6,
    "support_events.glacial_slow_percent": 6,
    "support_events.glacial_damage_reduction_ratio": 6,
    "support_events.stormraider_damage_threshold_ratio": 6,
    "support_events.stormraider_damage_window_seconds": 6,
    "support_events.stormraider_trigger_damage": 6,
    "support_events.stormraider_target_max_health": 6,
    "support_events.stormraider_cooldown_seconds": 6,
    "support_events.fleet_starting_charges": 6,
    "support_events.fleet_charge_cap": 6,
    "support_events.fleet_move_speed_duration_seconds": 6,
    "support_events.stacks_before": 6,
    "support_events.stacks_after": 6,
    "support_events.stacks_gained": 6,
    "support_events.max_stacks": 6,
    "support_events.adaptive_force": 6,
    "support_events.shield_gate_time": 6,
    "support_events.activation_delay": 6,
    "support_events.on_block_heal_amount": 6,
    "support_events.on_block_heal_delay": 6,
    "support_events.reduced_amount": 6,
    "support_events.overheal": 6,
    "support_events.healing_reduction_factor": 6,
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
        "survival_receipts": MappingProxyType(_SURVIVAL_RECEIPT_ROUNDING),
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
    _SURVIVAL_RECEIPT_ROUNDING,
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


# ---------------------------------------------------------------------------
# What a total sums, and in what order (D-65)
# ---------------------------------------------------------------------------

#: The receipt's three event panels, in the order a total that unions them
#: reads them.  The order is *declared* rather than incidental, and it is
#: also what attributes a shared id: the first panel to publish an id owns
#: it, so ``events`` before ``support_events`` means a support packet that
#: delivered damage is counted as damage.
SUM_PANELS: tuple[str, ...] = ("events", "healing_events", "support_events")


class DuplicateSumMember(ValueError):
    """One panel published one event id twice, so its own rows repeat.

    Named rather than generic because the failure it describes has no
    symptom: a total that counted one event twice is a plausible number.
    This is the unambiguous half — a *panel* repeating an id is a defect
    whatever the id means.  The cross-panel half is not a defect and is not
    refused; see :attr:`SumPlan.shared`.
    """


@dataclass(frozen=True, slots=True)
class SumPlan:
    """The event ids one published total sums, in the order it sums them.

    The receipt publishes three event panels and a reader that wants every
    event of a fight unions them.  Nothing said what that union should do
    with an id on two panels — D-65's own note is that three sources are
    unioned with only a comment preventing a double count — and the answer
    turns out to matter: a Redemption Intervention is published once on
    ``events`` as the damage it dealt and once on ``support_events`` as the
    support packet that dealt it, same id, same amount.  Summing the panels
    counts that 219.2 twice, and the wrong total is a perfectly ordinary
    number, which is this campaign's whole subject.

    A plan is that union made a value.  :attr:`members` is every published
    ``(panel, event_id)`` pair in declared order; :attr:`ids` is what a
    total sums — each event **once**, attributed to the first panel in
    :data:`SUM_PANELS` that published it.  So the double count is not
    tested for, it is unrepresentable: a caller folding over ``ids`` cannot
    reach the same event twice, which is the move ``Quantity.__add__``
    makes for propagation one layer up.

    **Ordering is declared, not incidental.**  Members arrive in
    :data:`SUM_PANELS` order and, within a panel, in walk order — the order
    the rows were published in.  That is a declaration rather than a
    detail because float addition is not associative: a total folded over a
    re-spelled ordering is a different number, and a plan whose order was
    "whatever the mapping iterated" would make it a different number for
    reasons no reader could see.

    **What is refused and what is recorded.**  One panel publishing one id
    twice is a defect with no benign reading, and it raises.  Two panels
    publishing one id is a support packet that delivered damage — refusing
    it would refuse to serve Redemption at all — so it is *recorded*, in
    :attr:`shared`, where a reader can see the events that would have been
    double-counted instead of inferring their absence.
    """

    members: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        """Refuse a panel that published one id twice."""
        # A ``dict`` rather than a ``set``: this type is reachable from the
        # receipt view, and criterion 3's purity walk follows an attribute
        # call into every class defining that name -- so ``seen.add(...)``
        # would enrol the damage engine's own ``add`` in a view's call
        # graph.  Membership in a dict answers the same question and
        # resolves to nothing.
        seen: dict[tuple[str, str], bool] = {}
        for member in self.members:
            if member in seen:
                raise DuplicateSumMember(
                    f"panel {member[0]!r} publishes event id {member[1]!r} twice; "
                    "its own rows would count that event twice"
                )
            seen[member] = True

    @property
    def ids(self) -> tuple[str, ...]:
        """What a total sums: every event once, in the plan's declared order.

        The deduplication is the plan's whole job, so it is a derivation and
        not a caller's discipline.  First panel wins, which is why
        :data:`SUM_PANELS` is an order rather than a set.
        """
        ordered: list[str] = []
        seen: dict[str, bool] = {}
        for _panel, event_id in self.members:
            if event_id not in seen:
                seen[event_id] = True
                ordered.append(event_id)
        return tuple(ordered)

    @property
    def shared(self) -> tuple[tuple[str, tuple[str, ...]], ...]:
        """The ids more than one panel published, with the panels, in order.

        Empty for almost every fight.  Non-empty is not an error: it is the
        list of events a naive union would have counted twice, named so a
        reader can see them rather than trust that they do not exist.
        """
        panels_by_id: dict[str, list[str]] = {}
        for panel, event_id in self.members:
            if event_id in panels_by_id:
                panels_by_id[event_id].append(panel)
            else:
                panels_by_id[event_id] = [panel]
        return tuple(
            (event_id, tuple(panels))
            for event_id, panels in panels_by_id.items()
            if len(panels) > 1
        )

    def of(self, panel: str) -> tuple[str, ...]:
        """Every id one panel published, in the plan's declared order."""
        return tuple(
            event_id for member_panel, event_id in self.members if member_panel == panel
        )


def sum_plan(panels: Mapping[str, Sequence[Mapping[str, Any]]]) -> SumPlan:
    """The plan over the receipt's published panels.

    Args:
        panels: the published rows per panel name.  Every key must be one of
            :data:`SUM_PANELS`; a row with no ``event_id`` contributes no
            member, because an unidentified row is not something a union
            over ids can double-count.

    Raises:
        DuplicateSumMember: one panel published one event id twice.
        KeyError: *panels* names a panel this registry does not declare —
            fail closed, because a fourth stream silently outside the plan
            is exactly the gap this exists to close.
    """
    unknown = sorted(panel for panel in panels if panel not in SUM_PANELS)
    if unknown:
        raise KeyError(
            f"{unknown} is not a declared sum panel; the declared panels are "
            f"{list(SUM_PANELS)}"
        )
    members: list[tuple[str, str]] = []
    for panel in SUM_PANELS:
        for row in panels.get(panel, ()):
            event_id = row.get("event_id")
            if event_id is not None:
                members.append((panel, str(event_id)))
    return SumPlan(members=tuple(members))
