"""The reactive family's front door: shields that arm, and thorns that strike.

Two mechanics that grant a shield *after* a typed champion hit lands, and one
that strikes the attacker back.  The family's name is the load-bearing part:
a reactive shield must not absorb the hit that armed it, which is why it is
not an opening defence with a delay, and Thorns writes no resolved defensive
state at all because what it produces is an event.

``thorns_effects`` moved here from the number registry with this slice.  The
record the coupled timeline consumes is unchanged; where its numbers come
from is not — the item's own declaration rather than a tag comparison inside
``item_effects``.
"""

from __future__ import annotations

import pytest

from src.calculator import item_behavior_catalog as catalog
from src.calculator.interpreters import INTERPRETERS, resolve_defense
from src.calculator.interpreters.reactive import RESOLVER_INTERPRETER, thorns_effects
from src.calculator.item_behavior import (
    BehaviorRule,
    DefenseMechanic,
    DefenseSubject,
    EngineLane,
    RuleFamily,
    TriggerEvent,
)


def _subject(**stats: float) -> DefenseSubject:
    """A level-18 subject with the stats a reactive shield reads."""
    base: dict[str, float] = {"health": 2000.0, "bonus_health": 0.0}
    base.update(stats)
    return DefenseSubject(level=18, stats=base, options={})


def _rule(owner: str, mechanic: DefenseMechanic) -> BehaviorRule:
    """The live rule *owner* declares for *mechanic*."""
    for rule in catalog.behavior_rules(owner):
        if getattr(rule.payload, "mechanic", None) is mechanic:
            return rule
    raise AssertionError(f"{owner} declares no {mechanic.value} rule")


def _granted(outcome) -> dict[str, object]:
    """One outcome's fields, by the resolved field they write."""
    return {field.name: field.value for field in outcome.fields}


def _build(*names: str) -> list[dict[str, str]]:
    """A build, in the order it was bought."""
    return [{"name": name} for name in names]


def test_the_family_is_registered_on_the_lane_that_builds_it() -> None:
    """A reactive defence's schedule is built before any walk."""
    assert (
        INTERPRETERS[(RuleFamily.REACTIVE, EngineLane.DEFENSE_RESOLVER)]
        is RESOLVER_INTERPRETER
    )


@pytest.mark.parametrize(
    ("owner", "mechanic", "damage_type"),
    [
        ("Armored Advance", DefenseMechanic.NOXIAN_ENDURANCE, "physical"),
        ("Chainlaced Crushers", DefenseMechanic.NOXIAN_PERSISTENCE, "magic"),
    ],
)
def test_both_noxian_boots_grant_a_typed_ramped_shield(
    owner: str, mechanic: DefenseMechanic, damage_type: str
) -> None:
    """One shape, two names, two citations — and two damage typings."""
    outcome = resolve_defense(_rule(owner, mechanic), _subject(bonus_health=500.0))

    granted = _granted(outcome)
    assert granted["reactive_shield_amount"] == pytest.approx(240.0)
    assert granted["reactive_shield_damage_type"] == damage_type
    assert granted["reactive_shield_duration"] == pytest.approx(5.0)
    assert granted["reactive_shield_cooldown"] == pytest.approx(15.0)
    assert granted["reactive_shield_source"] == f"{owner} — Noxian"
    assert f"after champion {damage_type} damage" in outcome.notes[0]


def test_only_the_boots_that_also_plate_declare_a_plating_multiplier() -> None:
    """The exclusion that tells the two Noxian mechanics apart."""
    endurance = resolve_defense(
        _rule("Armored Advance", DefenseMechanic.NOXIAN_ENDURANCE), _subject()
    )
    persistence = resolve_defense(
        _rule("Chainlaced Crushers", DefenseMechanic.NOXIAN_PERSISTENCE), _subject()
    )

    assert _granted(endurance)["basic_damage_multiplier"] == pytest.approx(0.90)
    assert "basic_damage_multiplier" not in _granted(persistence)


def test_a_reactive_shield_is_armed_by_an_event_and_says_which() -> None:
    """``trigger`` is the field that makes this family not an opening defence."""
    rule = _rule("Armored Advance", DefenseMechanic.NOXIAN_ENDURANCE)

    assert rule.payload.trigger is TriggerEvent.CHAMPION_DAMAGE


def test_thorns_writes_no_starting_state_because_it_is_an_event() -> None:
    """Declared with an empty ``writes``, which is the statement being made."""
    rule = _rule("Thornmail", DefenseMechanic.THORNS)
    outcome = resolve_defense(rule, _subject())

    assert rule.payload.writes == ()
    assert outcome.fields == () and outcome.notes == ()
    assert rule.payload.trigger is TriggerEvent.BASIC_ATTACK_HIT


def test_thorns_packets_are_built_from_the_declaration() -> None:
    """The record the coupled timeline reads, now sourced through the rule."""
    (bramble,) = thorns_effects(_build("Bramble Vest"))
    (thornmail,) = thorns_effects(_build("Thornmail"))

    assert bramble.item_name == "Bramble Vest"
    assert bramble.damage == pytest.approx(10.0)
    assert bramble.damage_type == "magic"
    assert bramble.grievous_duration == pytest.approx(3.0)
    assert bramble.bonus_armor_ratio == pytest.approx(0.0)
    assert thornmail.damage == pytest.approx(20.0)
    assert thornmail.bonus_armor_ratio == pytest.approx(0.10)


def test_thorns_packets_come_out_in_build_order_and_empty_without_one() -> None:
    """Build order is the published order; a build with no thorns has none."""
    both = thorns_effects(_build("Thornmail", "Bramble Vest"))

    assert [effect.item_name for effect in both] == ["Thornmail", "Bramble Vest"]
    assert thorns_effects(_build("Wit's End")) == ()


def test_a_missing_thorns_key_fails_loud_with_item_and_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rule 5's discipline: the declaration names where the number lives."""
    from src.calculator import item_effects

    broken = dict(item_effects.ITEM_EFFECTS["Thornmail"])
    broken.pop("bonus_armor_ratio")
    monkeypatch.setitem(item_effects.ITEM_EFFECTS, "Thornmail", broken)

    with pytest.raises(KeyError, match="Thornmail.*bonus_armor_ratio"):
        thorns_effects(_build("Thornmail"))


def test_deleting_the_interpreter_withholds_rather_than_granting_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Criterion 11 for this family."""
    from src.calculator import interpreters

    remaining = {
        key: value
        for key, value in INTERPRETERS.items()
        if key != (RuleFamily.REACTIVE, EngineLane.DEFENSE_RESOLVER)
    }
    monkeypatch.setattr(interpreters, "INTERPRETERS", remaining)
    with pytest.raises(interpreters.InterpreterRegistryError, match="withheld"):
        resolve_defense(
            _rule("Armored Advance", DefenseMechanic.NOXIAN_ENDURANCE), _subject()
        )
