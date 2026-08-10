"""Front-door tests for public response serialization."""

from src.calculator.public_response import serialize_fight_result


def _result(events):
    return {
        "champion_stats": {},
        "ability_damage": 0.0,
        "auto_attack_damage": 0.0,
        "damage_by_type": {},
        "breakdown": {},
        "damage_events": events,
        "self_healing_events": [],
    }


def test_serializer_keeps_valid_event_times() -> None:
    response = serialize_fight_result(
        _result([{"time": "1.25", "source_key": "Q", "damage": 10.0}])
    )

    assert response["damage_events"][0]["time"] == 1.25


def test_serializer_withholds_an_event_without_a_valid_time() -> None:
    response = serialize_fight_result(
        _result(
            [
                {"source_key": "bad", "damage": 10.0},
                {"time": 1.0, "source_key": "good", "damage": 5.0},
            ]
        )
    )

    assert [event["source"] for event in response["damage_events"]] == ["good"]


def test_serializer_passes_the_whole_rotation_receipt_through() -> None:
    """The rotation receipt is copied, not projected onto a key list.

    Phase 5 adds ``dependencies`` to what ``build_rotation_receipt``
    returns, and this suite is the API's front door.  It holds no
    exact-key assertion on ``rotation`` — a fact worth an assertion
    rather than an absence, because an exact-key check here would have
    made a new ledger reach the engine and stop at the serializer, which
    is a receipt the model computed and the response withheld.
    """
    receipt = {
        "cast_order": ["Q", "E"],
        "order": ["Q", "E"],
        "rationale": "declared",
        "sources": ("sourced",),
        "setup": ["Q"],
        "consume": ["E"],
        "aoe": {"E": 5},
        "dependencies": {"active": ["Q -> E"], "conflicts": []},
    }
    result = _result([])
    result["rotation"] = receipt

    response = serialize_fight_result(result)

    assert response["rotation"] == receipt
    assert response["rotation"]["dependencies"] == receipt["dependencies"]
