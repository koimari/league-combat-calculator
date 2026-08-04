"""Fail-closed timestamp contracts for ally support packets."""

import math

import pytest

from src.calculator.data_fetcher import get_champion
from src.calculator.support_effects import _support_profile, derive_ally_effects


def _sona_effects(cast_timeline):
    return derive_ally_effects(
        get_champion("Sona"),
        18,
        {"ability_power": 0.0},
        cast_timeline,
    )


def test_support_packet_preserves_sourced_cast_time():
    effects = _sona_effects([{"slot": "W", "time": 2.5}])

    assert effects
    assert {effect["time"] for effect in effects} == {2.5}


def test_self_granted_shield_targets_the_caster_without_a_teammate():
    effects = derive_ally_effects(
        get_champion("Annie"),
        12,
        {"ability_power": 0.0},
        [{"slot": "E", "time": 0.0}],
    )

    assert effects == [
        {
            "time": 0.0,
            "kind": "shield",
            "amount": 60.0,
            "source": "Molten Shield · Shield Strength",
            "slot": "E",
            "target_self": True,
            "target_scope": "one_teammate",
            "rank": 1,
        }
    ]


@pytest.mark.parametrize(
    ("champion", "slot"),
    [("Janna", "E"), ("Milio", "E"), ("Zilean", "R")],
)
def test_self_or_target_support_packets_mark_caster_scope(champion, slot):
    ability = get_champion(champion)["abilities"][slot][0]

    _shield, _heal, target_self, target_scope = _support_profile(ability)

    assert target_self is True
    assert target_scope == "one_teammate"


@pytest.mark.parametrize("bad_time", [None, "unknown", True, math.inf, -math.inf])
def test_support_packet_missing_or_invalid_cast_time_fails_closed(bad_time):
    cast = {"slot": "W"}
    if bad_time is not None:
        cast["time"] = bad_time

    with pytest.raises(
        ValueError, match="Support cast W time|missing its sourced time"
    ):
        _sona_effects([cast])
