"""The opening-defence family's front door.

Six mechanics the retired ladder spelled as six ``if "<item name>" in names`` branches.
The numbers below are the numbers those branches produced — that is the
whole claim of a migration — so every case here is also a regression test on
the retired ladder, and the two that are not are the ones the ladder could
not state at all: that Bloodthirster's starting shield is an *input* rather
than an assumption, and that deleting the family's interpreter withholds its
defences instead of quietly granting nothing.
"""

from __future__ import annotations

import pytest

from src.calculator import item_behavior_catalog as catalog
from src.calculator.defensive_effects import option_reader
from src.calculator.interpreters import INTERPRETERS, RESOLVERS, resolve_defense
from src.calculator.interpreters.defense_state import (
    DefenseInterpretationError,
    compiled_shape,
)
from src.calculator.interpreters.opening_defense import resolve_opening_defense
from src.calculator.item_behavior import (
    BehaviorRule,
    DefenseMechanic,
    DefenseSubject,
    EngineLane,
    RuleFamily,
)


def _subject(**stats: float) -> DefenseSubject:
    """A level-18 subject with the stats a case cares about."""
    base = {"health": 2000.0, "bonus_health": 0.0, "is_melee": False}
    base.update(stats)
    options = base.pop("options", {})
    return DefenseSubject(
        level=int(base.pop("level", 18)),
        stats=base,
        options=options,
        option_value=option_reader(options),
    )


def _rule(owner: str, mechanic: DefenseMechanic) -> BehaviorRule:
    """The live rule *owner* declares for *mechanic*."""
    for rule in catalog.behavior_rules(owner):
        if getattr(rule.payload, "mechanic", None) is mechanic:
            return rule
    raise AssertionError(f"{owner} declares no {mechanic.value} rule")


def _granted(outcome) -> dict[str, object]:
    """One outcome's fields, by the resolved field they write."""
    return {field.name: field.value for field in outcome.fields}


def test_the_family_is_registered_on_the_lane_that_builds_it() -> None:
    """A defence is built before any walk, and the registry says so."""
    assert (
        INTERPRETERS[(RuleFamily.OPENING_DEFENSE, EngineLane.DEFENSE_RESOLVER)]
        is compiled_shape
    )
    assert RESOLVERS[RuleFamily.OPENING_DEFENSE] is resolve_opening_defense


def test_magebane_is_a_share_of_the_subjects_own_maximum_health() -> None:
    """The one opening shield whose size is a property of who is wearing it."""
    outcome = resolve_defense(
        _rule("Kaenic Rookern", DefenseMechanic.MAGEBANE), _subject(health=2400.0)
    )

    assert _granted(outcome) == {"magic_shield": pytest.approx(360.0)}
    assert outcome.notes == (
        "Magebane is ready because the target has not taken magic damage "
        "during the previous 15 seconds.",
    )


def test_the_two_mitigation_multipliers_are_one_sourced_number_each() -> None:
    """Plating and Resilience: the smallest declarations in the family."""
    plating = resolve_defense(
        _rule("Plated Steelcaps", DefenseMechanic.PLATING), _subject()
    )
    resilience = resolve_defense(
        _rule("Randuin's Omen", DefenseMechanic.RESILIENCE), _subject()
    )

    assert _granted(plating) == {"basic_damage_multiplier": pytest.approx(0.90)}
    assert _granted(resilience) == {
        "critical_strike_damage_multiplier": pytest.approx(0.70)
    }


def test_rock_solid_declares_its_cap_beside_its_reduction() -> None:
    """A flat reduction with no cap is a different mechanic."""
    outcome = resolve_defense(
        _rule("Warden's Mail", DefenseMechanic.ROCK_SOLID), _subject()
    )

    assert _granted(outcome) == {
        "basic_damage_flat_reduction": pytest.approx(15.0),
        "basic_damage_flat_reduction_cap": pytest.approx(0.20),
    }


def test_blessing_publishes_the_state_source_that_granted_it() -> None:
    """The published source names the item, read off the declaration."""
    outcome = resolve_defense(
        _rule("Celestial Opposition", DefenseMechanic.BLESSING_OF_THE_MOUNTAIN),
        _subject(),
    )

    granted = _granted(outcome)
    assert granted["incoming_damage_multiplier"] == pytest.approx(0.65)
    assert granted["incoming_damage_linger"] == pytest.approx(2.0)
    assert granted["incoming_damage_source"] == "Celestial Opposition — Blessed"


@pytest.mark.parametrize(
    ("level", "expected"), [(1, 165.0), (8, 165.0), (9, 180.0), (18, 315.0)]
)
def test_the_ichorshield_cap_is_a_late_level_ramp(level: int, expected: float) -> None:
    """Flat until the level the entry names, and its maximum at eighteen."""
    outcome = resolve_defense(
        _rule("Bloodthirster", DefenseMechanic.ICHORSHIELD),
        DefenseSubject(level=level, stats={"health": 2000.0}, options={}),
    )

    assert _granted(outcome)["bloodthirster_shield_cap"] == pytest.approx(expected)


def test_a_starting_ichorshield_is_an_input_and_never_an_assumption() -> None:
    """Excess life-steal healing before the exchange is not guessed."""
    rule = _rule("Bloodthirster", DefenseMechanic.ICHORSHIELD)
    empty = resolve_defense(rule, _subject())
    supplied = resolve_defense(
        rule,
        _subject(options={"Bloodthirster": {"starting_ichorshield": 315}}),
    )

    assert "general_shield" not in _granted(empty)
    assert "starts empty" in empty.notes[0]
    assert _granted(supplied)["general_shield"] == pytest.approx(315.0)
    assert "explicitly supplied" in supplied.notes[0]


def test_a_starting_ichorshield_above_the_sourced_maximum_is_refused() -> None:
    """Out-of-range input is rejected at the boundary, never clamped here.

    ``DefenseSubject.option`` reads through ``item_effects``' typed accessor,
    so the declared domain (0..315, the level-18 cap) is the option's
    contract.  A resolver that silently capped 400 would price an activation
    no request could have passed.
    """
    rule = _rule("Bloodthirster", DefenseMechanic.ICHORSHIELD)

    with pytest.raises(ValueError, match=r"starting_ichorshield must be between 0"):
        resolve_defense(
            rule,
            _subject(options={"Bloodthirster": {"starting_ichorshield": 400}}),
        )


def test_deleting_the_interpreter_withholds_rather_than_granting_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Criterion 11 for this family: the registry is the dispatch."""
    from src.calculator import interpreters

    remaining = {
        family: resolver
        for family, resolver in RESOLVERS.items()
        if family is not RuleFamily.OPENING_DEFENSE
    }
    monkeypatch.setattr(interpreters, "RESOLVERS", remaining)
    with pytest.raises(interpreters.InterpreterRegistryError, match="withheld"):
        resolve_defense(_rule("Kaenic Rookern", DefenseMechanic.MAGEBANE), _subject())


def test_a_defence_of_another_family_is_refused() -> None:
    """A resolver answers for its own family and says so."""
    with pytest.raises(DefenseInterpretationError, match="no branch for it"):
        resolve_opening_defense(
            _rule("Force of Nature", DefenseMechanic.STEADFAST), _subject()
        )
