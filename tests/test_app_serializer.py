"""Public fight-result serialization must not fabricate event timestamps."""

import math

import pytest

from src.calculator.public_response import serialize_fight_result


def _result(*, damage_events=(), self_healing_events=(), breakdown=None):
    return {
        "champion_stats": {},
        "ability_damage": 0.0,
        "auto_attack_damage": 0.0,
        "damage_by_type": {},
        "breakdown": breakdown or {},
        "damage_events": list(damage_events),
        "self_healing_events": list(self_healing_events),
    }


def test_serializer_preserves_non_damage_amount_receipts():
    response = serialize_fight_result(
        _result(
            breakdown={
                "mana_Essence Reaver": {
                    "name": "Essence Reaver (Manaflow)",
                    "count": 2,
                    "proc_times": [1.5, 3.0],
                    "amount_per_proc": 50.0,
                    "total_amount": 100.0,
                    "unit": "mana",
                }
            }
        )
    )

    row = response["breakdown"]["mana_Essence Reaver"]
    assert row["total_damage"] == 0.0
    assert row["total_amount"] == 100.0
    assert row["output_type"] == "mana"
    assert row["proc_times"] == [1.5, 3.0]


def test_serializer_preserves_valid_damage_and_healing_times():
    response = serialize_fight_result(
        _result(
            damage_events=[{"time": "1.25", "source_key": "Q", "damage": 10}],
            self_healing_events=[{"time": 2.5, "source": "Heal", "amount": 4}],
        )
    )

    assert response["damage_events"][0]["time"] == 1.25
    assert response["self_healing_events"][0]["time"] == 2.5


@pytest.mark.parametrize("bad_time", [None, "unknown", True, math.nan, math.inf])
def test_serializer_withholds_malformed_damage_event_times(bad_time):
    malformed = {"source_key": "bad", "damage": 10}
    if bad_time is not None:
        malformed["time"] = bad_time
    response = serialize_fight_result(
        _result(
            damage_events=[malformed, {"time": 1.0, "source_key": "good", "damage": 5}]
        )
    )

    assert [event["source"] for event in response["damage_events"]] == ["good"]


@pytest.mark.parametrize("bad_time", [None, "unknown", False, -math.inf])
def test_serializer_withholds_malformed_self_healing_event_times(bad_time):
    malformed = {"source": "bad", "amount": 10}
    if bad_time is not None:
        malformed["time"] = bad_time
    response = serialize_fight_result(
        _result(
            self_healing_events=[
                malformed,
                {"time": 2.0, "source": "good", "amount": 5},
            ]
        )
    )

    assert [event["source"] for event in response["self_healing_events"]] == ["good"]
