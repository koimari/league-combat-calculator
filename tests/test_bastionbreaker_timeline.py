"""Focused tests for Bastionbreaker's authored ability trigger ledger."""

from types import SimpleNamespace

from src.calculator.ability_spec import DamagePart
from src.calculator.damage import (
    RotationResult,
    _shaped_charge_proc_receipts,
)


def _state() -> SimpleNamespace:
    return SimpleNamespace(
        ability_damages={
            "Q": {"parts": (DamagePart("magic", 100.0),)},
            "W": {"parts": (DamagePart("magic", 0.0),)},
        },
        breakdown={},
        cast_order=None,
    )


def _proc_times(state, rotation, cooldown) -> list[float] | None:
    receipts = _shaped_charge_proc_receipts(state, rotation, cooldown)
    if receipts is None:
        return None
    return [float(receipt["time"]) for receipt in receipts]


def test_shaped_charge_times_follow_next_damaging_ability_cooldown() -> None:
    """Only damaging casts at least 20s apart consume Shaped Charge."""
    rotation = RotationResult(
        cast_events=[
            {"slot": "Q", "time": 0.0},
            {"slot": "W", "time": 7.0},
            {"slot": "Q", "time": 20.0},
            {"slot": "Q", "time": 21.0},
        ]
    )

    assert _proc_times(_state(), rotation, 20.0) == [0.0, 20.0]


def test_shaped_charge_withholds_malformed_cast_receipt() -> None:
    """A malformed cast timestamp cannot invent a proc boundary."""
    rotation = RotationResult(cast_events=[{"slot": "Q", "time": "0"}])

    assert _proc_times(_state(), rotation, 20.0) is None


def test_shaped_charge_prefers_authored_ability_hit_time() -> None:
    """A sourced ability packet replaces the cast-boundary fallback."""
    state = _state()
    state.breakdown = {
        "Q": {
            "damage_events": [
                {"time": 0.25, "damage": 100.0, "event_precision": "exact"}
            ]
        }
    }
    rotation = RotationResult(cast_events=[{"slot": "Q", "time": 0.0}])

    assert _proc_times(state, rotation, 20.0) == [0.25]
