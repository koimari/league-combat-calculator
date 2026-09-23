"""The action records: every kind has one, and a record stores only its own fields."""

from collections import Counter

import pytest

from src.calculator.survival.action_families import (
    CORE,
    FAMILIES,
    FAMILY_OF,
    DamageAction,
    HealAction,
    StateAction,
)
from src.calculator.survival.typed_action import (
    ACTION_FIELDS,
    ActionKind,
    SurvivalAction,
)


def test_every_kind_is_claimed_by_exactly_one_record() -> None:
    claims = Counter(kind for family in FAMILIES for kind in family.kinds)
    assert claims == Counter(ActionKind)
    assert set(FAMILY_OF) == set(ActionKind)


def test_every_record_leads_with_the_core_and_every_field_has_a_record() -> None:
    assert all(family._fields[: len(CORE)] == CORE for family in FAMILIES)
    assert set().union(*(family._fields for family in FAMILIES)) == set(ACTION_FIELDS)


def test_a_field_the_record_does_not_store_reads_its_neutral_value() -> None:
    heal = HealAction(amount=40.0)
    assert "execute_threshold_ratio" not in HealAction._fields
    assert heal.execute_threshold_ratio == SurvivalAction.execute_threshold_ratio
    assert isinstance(heal, SurvivalAction)


def test_a_record_refuses_a_field_it_does_not_store() -> None:
    with pytest.raises(TypeError):
        StateAction(bonus_armor=10.0)
    with pytest.raises((TypeError, ValueError)):
        StateAction()._replace(bonus_armor=10.0)


def test_a_reschedule_keeps_the_record_its_slot_and_its_event() -> None:
    """The walk moves an action by ``_replace`` at a new time and sort key."""
    event = {"time": 1.0}
    action = DamageAction(sort_key=(1.0,), time=1.0, aidx=7, event=event)
    moved = action._replace(time=2.0, sort_key=(2.0,))
    assert type(moved) is DamageAction
    assert (moved.aidx, moved.time, moved.sort_key) == (7, 2.0, (2.0,))
    assert moved.event is event
