"""The defence machinery's front door: how a defence reaches the registry.

The four defence families share no arithmetic and one contract, and this is
the contract.  Every clause below is a *refusal*: a key the declaration does
not carry, a ramp asked for as a flat number, a field the mechanic never
said it writes.  Each of them used to be impossible to get wrong only
because the resolver read the registry directly, which is another way of
saying nothing checked it at all.
"""

from __future__ import annotations

import pytest

from src.calculator import item_behavior_catalog as catalog
from src.calculator.interpreters.defense_state import (
    DEFENSE_VALUE_COUNT_FIELD,
    DefenseInterpretationError,
    DefenseSlot,
    compiled_shape,
)
from src.calculator.item_behavior import (
    BehaviorRule,
    DefenseField,
    DefenseMechanic,
    EngineLane,
    RuleFamily,
)


def _rule(owner: str, mechanic: DefenseMechanic) -> BehaviorRule:
    """The live rule *owner* declares for *mechanic*."""
    for rule in catalog.behavior_rules(owner):
        if getattr(rule.payload, "mechanic", None) is mechanic:
            return rule
    raise AssertionError(f"{owner} declares no {mechanic.value} rule")


def test_a_slot_reads_only_the_numbers_its_declaration_names() -> None:
    """The whole point of the declaration: the resolver cannot reach past it."""
    slot = DefenseSlot(_rule("Kaenic Rookern", DefenseMechanic.MAGEBANE))

    assert slot.value("magic_shield_max_health_ratio") == pytest.approx(0.15)
    with pytest.raises(DefenseInterpretationError, match="declares no"):
        slot.value("shield_received_multiplier")


def test_a_ramp_is_one_number_with_two_ends() -> None:
    """A ramp is named by its low key and refuses a flat read."""
    slot = DefenseSlot(_rule("Immortal Shieldbow", DefenseMechanic.LIFELINE_SHIELDBOW))

    assert slot.late_ramp("shield_base", 18) == pytest.approx(700.0)
    with pytest.raises(DefenseInterpretationError, match="declares no"):
        slot.value("shield_base")
    with pytest.raises(DefenseInterpretationError, match="level ramp"):
        slot.ramp("shield_base", 18)


def test_a_defence_may_not_write_a_field_it_never_declared() -> None:
    """``writes`` is load-bearing, not documentation."""
    slot = DefenseSlot(_rule("Plated Steelcaps", DefenseMechanic.PLATING))

    granted = slot.grant(DefenseField.BASIC_DAMAGE_MULTIPLIER, 0.9)
    assert granted.name == "basic_damage_multiplier"
    assert granted.lane is EngineLane.DEFENSE_RESOLVER
    assert granted.rule_id == "plated_steelcaps.plating"
    with pytest.raises(DefenseInterpretationError, match="does not declare"):
        slot.grant(DefenseField.MAGIC_SHIELD, 100.0)


def test_a_policy_reference_a_mechanic_has_none_of_is_a_stop() -> None:
    """Rebirth arms on lethal damage, which is not a fraction of health."""
    slot = DefenseSlot(_rule("Guardian Angel", DefenseMechanic.REBIRTH))

    with pytest.raises(DefenseInterpretationError, match="declares no threshold"):
        slot.threshold()


def test_compiling_resolves_every_reference_at_build_time() -> None:
    """A missing registry key surfaces when the build is made, not mid-fight."""
    rule = _rule("Force of Nature", DefenseMechanic.STEADFAST)

    (field,) = compiled_shape(
        rule,
        catalog.build_context(
            rule.owner,
            18,
            fight_duration_seconds=5.0,
            target_bonus_health=0.0,
            holder_is_melee=True,
        ),
        EngineLane.DEFENSE_RESOLVER,
    )

    assert field.name == DEFENSE_VALUE_COUNT_FIELD
    assert field.value == len(rule.payload.values) == 6
    assert field.lane is EngineLane.DEFENSE_RESOLVER


def test_a_rule_of_another_family_is_refused() -> None:
    """The slot is a defence's accessor and says so rather than half-working."""
    (amp,) = [
        rule
        for rule in catalog.behavior_rules("Horizon Focus")
        if rule.family is RuleFamily.DELTA_AMP
    ]
    with pytest.raises(DefenseInterpretationError, match="not a defence rule"):
        DefenseSlot(amp)
