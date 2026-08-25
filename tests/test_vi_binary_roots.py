"""Certification tests for Vi Q's binary-rooted range and damage fields."""

import pytest

from src.calculator.binary_roots import data_value, spell_object


def test_vi_q_min_dash_range_matches_module_constant():
    import src.calculator.champions.vi as vi

    q = spell_object("Vi", "ViQ")
    assert data_value(q, "MinDashRange") == pytest.approx(vi._Q_MIN_RANGE)


def test_vi_q_max_dash_range_matches_module_constant():
    import src.calculator.champions.vi as vi

    q = spell_object("Vi", "ViQ")
    assert data_value(q, "MinDashRange") + data_value(
        q, "ExtraDashRangeAtMaxCharge"
    ) == pytest.approx(vi._Q_MAX_RANGE)


def test_vi_q_max_damage_bonus_matches_module_constant():
    import src.calculator.champions.vi as vi

    q = spell_object("Vi", "ViQ")
    assert data_value(q, "MaxDamageMult") - 1.0 == pytest.approx(
        vi._Q_MAX_BONUS_MULTIPLIER
    )
