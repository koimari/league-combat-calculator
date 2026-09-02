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
from src.calculator.interpreters import INTERPRETERS, RESOLVERS, resolve_defense
from src.calculator.interpreters.defense_state import (
    DefenseInterpretationError,
    compiled_shape,
)
from src.calculator.interpreters.reactive import (
    THORNS_FIELDS,
    resolve_reactive,
    thorns_effects,
    thorns_fields,
)
from src.calculator.item_behavior import (
    BehaviorRule,
    DefenseMechanic,
    DefenseSubject,
    EngineLane,
    FightFacts,
    RuleFamily,
    TriggerEvent,
)


def _ctx(owner: str):
    """A build context the walk boundary could not actually supply.

    Every reference a strike-back declares is flat, so the interpreter reads
    none of this; it is here because ``compile`` takes a context and a test
    that passed one carrying real fight facts would imply the walk has them.
    """
    return catalog.build_context(
        owner,
        FightFacts(
            level=18,
            fight_duration_seconds=0.0,
            target_bonus_health=0.0,
            holder_is_melee=True,
        ),
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
        is compiled_shape
    )
    assert RESOLVERS[RuleFamily.REACTIVE] is resolve_reactive


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
    assert outcome.fields == ()
    assert outcome.notes == ()
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

    with pytest.raises(KeyError, match=r"Thornmail.*bonus_armor_ratio"):
        thorns_effects(_build("Thornmail"))


def test_deleting_the_interpreter_withholds_rather_than_granting_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Criterion 11 for this family."""
    from src.calculator import interpreters

    remaining = {
        family: resolver
        for family, resolver in RESOLVERS.items()
        if family is not RuleFamily.REACTIVE
    }
    monkeypatch.setattr(interpreters, "RESOLVERS", remaining)
    with pytest.raises(interpreters.InterpreterRegistryError, match="withheld"):
        resolve_defense(
            _rule("Armored Advance", DefenseMechanic.NOXIAN_ENDURANCE), _subject()
        )


# ── the walk lane: the strike-back the coupled timeline compiles itself ────


def test_the_family_is_registered_on_the_walk_that_pays_the_strike_back() -> None:
    """Thorns is not staged from resolved state, so the walk owes an answer.

    ``participant_timeline`` compiles one profile per roster actor from this
    family's declaration and schedules a strike-back event from it; that is a
    walk-lane interpretation, and until this registration the lane was a gap
    whose dated receipt said the walks stage what the resolver built.
    """
    assert INTERPRETERS[(RuleFamily.REACTIVE, EngineLane.RECEIPT_WALK)] is thorns_fields


def test_the_walk_lane_compiles_the_three_numbers_a_strike_back_declares() -> None:
    """Every field is the declaration's own, stamped with the lane it serves."""
    rule = _rule("Thornmail", DefenseMechanic.THORNS)
    fields = thorns_fields(rule, _ctx(rule.owner), EngineLane.RECEIPT_WALK)
    assert [field.name for field in fields] == list(THORNS_FIELDS)
    assert all(field.lane is EngineLane.RECEIPT_WALK for field in fields)
    assert all(field.rule_id == rule.mechanic_id for field in fields)


def test_the_accessor_and_the_interpreter_share_one_arithmetic_home() -> None:
    """The timeline's packet is the interpreter's fields, not a second sum.

    Two producers of one number is the incident's own shape, so what is
    asserted is identity of the values rather than that both merely run.
    """
    rule = _rule("Thornmail", DefenseMechanic.THORNS)
    fields = {
        field.name: float(field.value)
        for field in thorns_fields(rule, _ctx(rule.owner), EngineLane.RECEIPT_WALK)
    }
    (packet,) = thorns_effects(_build("Thornmail"))
    assert packet.damage == fields["base"]
    assert packet.bonus_armor_ratio == fields["bonus_armor_ratio"]
    assert packet.grievous_duration == fields["grievous_duration"]


def test_the_walk_lane_refuses_a_reactive_shield_rather_than_pricing_it_twice() -> None:
    """The shields reach the walk as resolved state; asking here is a stop."""
    rule = _rule("Armored Advance", DefenseMechanic.NOXIAN_ENDURANCE)
    with pytest.raises(DefenseInterpretationError, match="price it twice"):
        thorns_fields(rule, _ctx(rule.owner), EngineLane.RECEIPT_WALK)
