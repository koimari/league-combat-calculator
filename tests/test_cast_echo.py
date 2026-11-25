"""A basic cast that finds the Echo cap spends it and lands twice."""

import pytest

from src.calculator.champions.cast_echo import CastEcho, echoed_casts

_ECHO = CastEcho(
    slots=("Q", "W", "E"), stacks_to_echo=2, starts_full=True, delay_seconds=0.033
)


def test_a_full_opening_echoes_the_first_cast_then_every_third():
    flags = echoed_casts(
        _ECHO, {"Q": (0.0, 3.0, 6.0), "W": (1.0,), "E": (2.0, 5.0)}, "QWER"
    )
    # Time order: Q0 (echo), W1, E2, Q3 (echo), E5, Q6.
    assert flags == {"Q": (True, True, False), "W": (False,), "E": (False, False)}


def test_an_empty_opening_banks_two_casts_first():
    empty = CastEcho(
        slots=("Q",), stacks_to_echo=2, starts_full=False, delay_seconds=0.0
    )
    assert echoed_casts(empty, {"Q": (0.0, 1.0, 2.0, 3.0)}, "Q") == {
        "Q": (False, False, True, False)
    }


def test_casts_at_one_instant_follow_the_rotation_order():
    flags = echoed_casts(_ECHO, {"Q": (0.0,), "E": (0.0,)}, "EQ")
    assert flags == {"Q": (False,), "W": (), "E": (True,)}


def test_slots_outside_the_rule_never_bank_or_echo():
    assert echoed_casts(_ECHO, {"R": (0.0,), "Q": (1.0,)}, "RQ")["Q"] == (True,)


@pytest.mark.parametrize(
    "bad", [dict(slots=()), dict(stacks_to_echo=0), dict(delay_seconds=-1.0)]
)
def test_a_rule_no_cast_could_satisfy_is_refused(bad):
    fields = dict(slots=("Q",), stacks_to_echo=2, starts_full=True, delay_seconds=0.0)
    with pytest.raises(ValueError):
        CastEcho(**{**fields, **bad})
