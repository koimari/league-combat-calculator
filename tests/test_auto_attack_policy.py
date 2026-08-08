"""Front-door tests for the sourced auto-attack uptime policy."""

from src.calculator.auto_attack_policy import (
    AUTO_ATTACK_UPTIME_MODE_CALCULATED,
    resolve_auto_attack_policy,
)


def test_calculated_policy_prices_sourced_cast_lockout() -> None:
    uptime, receipt = resolve_auto_attack_policy(
        {"abilities": {}},
        {"Q": {"cast_time": 1.0}, "W": {"cast_time": 0.5}},
        cast_order=["Q", "W"],
        duration_seconds=5.0,
        requested_uptime=0.7,
        mode=AUTO_ATTACK_UPTIME_MODE_CALCULATED,
        one_rotation=True,
    )

    assert uptime == 0.7
    assert receipt["status"] == "calculated"
    assert receipt["occupied_cast_seconds"] == 1.5
