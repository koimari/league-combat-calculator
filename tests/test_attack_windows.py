"""Temporary attack speed preserves progress across each expiry boundary."""

import pytest

from src.calculator.attack_windows import AttackSpeedWindow, attack_times_for_windows


def test_mid_interval_buff_changes_rate_without_resetting_attack_progress():
    windows = (AttackSpeedWindow("cast", "main", 0.5, 1.5, 100),)
    times = attack_times_for_windows(
        windows, attack_speed=1, ratio=1, duration=3, uptime=1
    )
    assert times == pytest.approx((0, 0.75, 1.25, 2))


def test_repeated_whimsy_does_not_stack_its_rate():
    windows = (
        AttackSpeedWindow("one", "main", 0, 2, 100),
        AttackSpeedWindow("two", "main", 1, 3, 100),
    )
    times = attack_times_for_windows(
        windows, attack_speed=1, ratio=1, duration=3, uptime=1
    )
    assert times == pytest.approx((0, 0.5, 1, 1.5, 2, 2.5))


def test_distinct_additive_windows_stack_then_expire_independently():
    windows = (
        AttackSpeedWindow("q", "main", 0, 4, 100, "champion_active"),
        AttackSpeedWindow("w", "main", 2, 6, 50),
    )
    times = attack_times_for_windows(
        windows, attack_speed=1, ratio=1, duration=8, uptime=1
    )
    assert times == pytest.approx(
        (0, 0.5, 1, 1.5, 2, 2.4, 2.8, 3.2, 3.6, 4, 4 + 2 / 3, 5 + 1 / 3, 6, 7)
    )


def test_champion_phase_boundaries_preserve_the_existing_attack_start():
    windows = (AttackSpeedWindow("q", "main", 0.25, 2.25, 100, "champion_active"),)
    times = attack_times_for_windows(
        windows, attack_speed=1, ratio=1, duration=4.25, uptime=1, reset_at=(0.25, 2.25)
    )
    assert times == pytest.approx((0.25, 0.75, 1.25, 1.75, 2.25, 3.25))
