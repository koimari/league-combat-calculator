"""Certification tests for batch 52's exact champion binary roots."""

import pytest

from src.calculator.binary_roots import (
    calculation_coefficient,
    calculation_stat_coefficient,
    data_value,
    spell_object,
)


def test_pantheon_binary_coefficients_preserve_module_units():
    from src.calculator.champions import pantheon

    q = spell_object("Pantheon", "PantheonQ")
    w = spell_object("Pantheon", "PantheonW")
    assert calculation_coefficient(q, "EmpoweredDamageCalc") == pytest.approx(
        pantheon._MORTAL_WILL_BONUS_AD_RATIO
    )
    assert calculation_stat_coefficient(
        w, "MaxHealthDamageCalc", 12
    ) * 10000.0 == pytest.approx(pantheon._W_BONUS_HEALTH_PER_100)


def test_pyke_r_scaling_uses_threshold_and_reduced_damage_binary_terms():
    from src.calculator.champions import pyke

    r = spell_object("Pyke", "PykeR")
    reduced = data_value(r, "ReducedDamage")
    threshold_ad = calculation_coefficient(r, "RADDamage")
    threshold_lethality = calculation_coefficient(r, "RLethalityDamage")
    assert threshold_ad == pytest.approx(pyke._R_THRESHOLD_BONUS_AD_RATIO)
    assert threshold_lethality == pytest.approx(pyke._R_THRESHOLD_PER_LETHALITY)
    assert reduced == pytest.approx(pyke._R_REDUCED_DAMAGE)
    assert threshold_ad * reduced == pytest.approx(pyke._R_DAMAGE_BONUS_AD_RATIO)
    assert threshold_lethality * reduced == pytest.approx(pyke._R_DAMAGE_PER_LETHALITY)


def test_vi_r_initial_speed_comes_from_the_binary():
    from src.calculator.champions import vi

    r = spell_object("Vi", "ViR")
    assert data_value(r, "RBaseSpeed") == pytest.approx(vi._R_INITIAL_SPEED)


def test_volibear_passive_attack_speed_terms_come_from_the_binary():
    from src.calculator.champions import volibear

    passive = spell_object("Volibear", "VolibearP")
    assert data_value(passive, "BounceCounterMax") == pytest.approx(
        volibear._RELENTLESS_STORM_MAX_STACKS
    )
    assert data_value(passive, "PAttackSpeed") * 100.0 == pytest.approx(
        volibear._STORM_AS_PER_STACK
    )
    assert calculation_coefficient(
        passive, "AttackSpeedCalc"
    ) * 10000.0 == pytest.approx(volibear._STORM_AS_PER_100_AP)
