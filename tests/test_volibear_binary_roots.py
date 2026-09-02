"""Volibear W's Wounded damage constants are rooted in its character binary."""

import pytest

from src.calculator.binary_roots import data_value, spell_object


def test_volibear_w_wounded_damage_multiplier_comes_from_the_binary():
    from src.calculator.champions import volibear

    w = spell_object("Volibear", "VolibearW")
    assert data_value(w, "W2DamageMultiplier") - 1.0 == pytest.approx(
        volibear._WOUNDED_BONUS_BASE
    )


def test_volibear_w_wounded_bonus_ad_multiplier_comes_from_the_binary():
    from src.calculator.champions import volibear

    w = spell_object("Volibear", "VolibearW")
    assert data_value(w, "W2BonusADDamageMultiplier") * 100.0 == pytest.approx(
        volibear._WOUNDED_BONUS_PER_100_BONUS_AD
    )
