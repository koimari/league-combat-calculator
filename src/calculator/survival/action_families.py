"""The record an action is built as: the core, plus what its kinds' transitions read.

One family per group of :class:`ActionKind` members the walk treats alike.  A
family stores every field the walk reads on its kinds' path, read off the walk
stages below, so a field it does not store is one no transition of its kinds
reads and :class:`SurvivalAction` answers its neutral value.  Naming such a
field to a family's constructor or ``_replace`` raises.  ``FAMILY_OF`` is the
kind-to-record table every producer builds through.
"""

from __future__ import annotations

from collections import namedtuple

from .typed_action import ACTION_FIELDS, ActionKind, SurvivalAction

#: What every kind reads, and every record's leading fields, ``sort_key`` first.
CORE = (
    "sort_key",
    "time",
    "phase",
    "kind",
    "subject",
    "attacker",
    "aidx",
    "trigger",
    "trigger_slot",
    "event",
    "event_slot",
    "source_key",
    "source",
    "sequence",
    "amount",
    "redirected",
)

# The walk stages a kind passes, each named by the fields it reads.  Every
# kind the walk does not dispatch before its trigger gate meets ``_GATED``;
# ``_LATE`` is the deferral, reactive and cleanse gates after the utility
# dispatch; ``_DELIVERY`` is what the spell-shield and projectile gates read;
# ``_PACKET`` is the live packet chain and the resistance a price meets.
_GATED = frozenset(
    "rebinds_on_ability_hit defy_trigger_slot cast_blocked_by_attacker_control"
    " cast_while_disabled".split()
)
_LATE = frozenset(
    "deferred deferred_batch_slot reactive cleanse cleanse_item cleanse_group".split()
)
_DELIVERY = frozenset(
    "is_ability basic_attack ability_instance immobilized cc_kind"
    " skillshot area_damage damage_over_time".split()
)
_PACKET = frozenset(
    "damage_type declared live_amp baseline_effective_armor baseline_effective_mr".split()
)


def _record(name: str, kind: ActionKind, extras: frozenset[str]) -> type:
    """A namedtuple over the core and *extras*, every default the neutral value."""
    unknown = extras.difference(ACTION_FIELDS)
    if unknown:
        raise TypeError(f"{name} names undeclared fields {sorted(unknown)}")
    fields = CORE + tuple(f for f in ACTION_FIELDS if f in extras and f not in CORE)
    defaults = [kind if f == "kind" else getattr(SurvivalAction, f) for f in fields]
    return namedtuple(name, fields, defaults=defaults)


class DamageAction(
    _record(
        "DamageRecord",
        ActionKind.DAMAGE,
        _GATED
        | _LATE
        | _DELIVERY
        | _PACKET
        | frozenset(
            "raw_formula raw_damage grievous wound execute_threshold_ratio"
            " execute_source redirect_holder_health_ratio redirect_original_damage"
            " cc_duration".split()
        ),
    ),
    SurvivalAction,
):
    """A packet that lands as damage, with its execute, deferral and redirect facts."""

    __slots__ = ()
    kinds = frozenset(
        {
            ActionKind.PLAIN_DAMAGE,
            ActionKind.DAMAGE,
            ActionKind.EXECUTE,
            ActionKind.DEFER,
            ActionKind.REDIRECT,
        }
    )


class HealAction(
    _record(
        "HealRecord",
        ActionKind.HEAL,
        _GATED
        | _LATE
        | _DELIVERY
        | _PACKET
        | frozenset(
            "healing_category amplified_recovery amount_formula"
            " requires_existing_shield requires_maw_lifeline_omnivamp"
            " shield_gate_subject shield_gate_time requires_holder_health_ratio"
            " requires_damage_free_seconds overheal_to_temporary_health"
            " temporary_health_duration overheal_to_shield overheal_shield_cap"
            " overheal_shield_duration".split()
        ),
    ),
    SurvivalAction,
):
    """A recovery packet with its gates and what its overheal becomes."""

    __slots__ = ()
    kinds = frozenset(
        {ActionKind.HEAL, ActionKind.OVERHEAL_SHIELD, ActionKind.ICHOR_CONVERT}
    )


class BarrierAction(
    _record(
        "BarrierRecord",
        ActionKind.SHIELD,
        _GATED
        | _LATE
        | _DELIVERY
        | _PACKET
        | frozenset(
            "amount_formula duration shield_pool crowd_control_immunity_while_shield"
            " crowd_control_immunity_source".split()
        ),
    ),
    SurvivalAction,
):
    """A shield or temporary health grant, its pool and its lifetime."""

    __slots__ = ()
    kinds = frozenset({ActionKind.SHIELD, ActionKind.TEMP_HEALTH})


class StatBuffAction(
    _record(
        "StatBuffRecord",
        ActionKind.STAT_BUFF,
        _GATED
        | frozenset(
            "duration bonus_attack_speed_percent bonus_move_speed_percent"
            " bonus_armor bonus_magic_resistance bonus_health ability_power"
            " ability_haste on_hit_magic_damage".split()
        ),
    ),
    SurvivalAction,
):
    """A timed stat grant."""

    __slots__ = ()
    kinds = frozenset({ActionKind.STAT_BUFF})


class ModifierAction(
    _record(
        "ModifierRecord",
        ActionKind.DAMAGE_MODIFIER,
        _GATED
        | frozenset(
            "duration persistent multiplier damage_reduction next_event_only"
            " all_sources armor_reduction_percent mr_reduction_percent"
            " resistance_type holder damage_classes attack_classes"
            " source_participant".split()
        ),
    ),
    SurvivalAction,
):
    """An armed damage modifier, its classes and its holder."""

    __slots__ = ()
    kinds = frozenset({ActionKind.DAMAGE_MODIFIER})


class UtilityAction(
    _record(
        "UtilityRecord",
        ActionKind.UTILITY,
        _GATED
        | frozenset(
            "cleanse cleanse_item cleanse_group duration duration_set"
            " next_event_only utility_kind".split()
        ),
    ),
    SurvivalAction,
):
    """On-hit magic and the utility kinds, the cleanse activation among them."""

    __slots__ = ()
    kinds = frozenset({ActionKind.ON_HIT_MAGIC, ActionKind.UTILITY})


class ControlAction(
    _record(
        "ControlRecord",
        ActionKind.CROWD_CONTROL,
        _GATED
        | _LATE
        | _DELIVERY
        | frozenset(
            "damage_type baseline_effective_armor baseline_effective_mr"
            " cc_duration duration".split()
        ),
    ),
    SurvivalAction,
):
    """Crowd control landing on the subject, and the arm that resists it."""

    __slots__ = ()
    kinds = frozenset({ActionKind.CROWD_CONTROL, ActionKind.CROWD_CONTROL_RESIST})


class StateAction(
    _record(
        "StateRecord",
        ActionKind.STASIS,
        frozenset(
            "duration delay health_ratio on_block_heal_amount on_block_heal_delay"
            " on_block_heal_source".split()
        ),
    ),
    SurvivalAction,
):
    """The transitions the walk dispatches before its trigger gate."""

    __slots__ = ()
    kinds = frozenset(
        {
            ActionKind.REVIVE,
            ActionKind.STASIS,
            ActionKind.INVULNERABLE,
            ActionKind.UNTARGETABLE,
            ActionKind.SPELL_SHIELD,
        }
    )


class WideAction(
    _record("WideRecord", ActionKind.DAMAGE, frozenset(ACTION_FIELDS)), SurvivalAction
):
    """Every field, for the kinds no family record builds yet."""

    __slots__ = ()
    kinds = frozenset(ActionKind)


FAMILIES: tuple[type[SurvivalAction], ...] = (
    DamageAction,
    HealAction,
    ModifierAction,
    StateAction,
    BarrierAction,
)
FAMILY_OF: dict[ActionKind, type[SurvivalAction]] = {
    **dict.fromkeys(ActionKind, WideAction),
    **{kind: family for family in FAMILIES for kind in family.kinds},
}
