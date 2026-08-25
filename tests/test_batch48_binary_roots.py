"""Certification tests for batch 48's exact champion binary roots."""

import pytest

from src.calculator.binary_roots import (
    calculation_coefficient,
    calculation_interpolation,
    data_value,
    spell_object,
)


def test_zeri_q_binary_constants_are_used():
    from src.calculator.champions import zeri

    q = spell_object("Zeri", "ZeriQ")
    assert calculation_coefficient(q, "MinDamage") == pytest.approx(zeri._ZAP_AP_RATIO)
    assert calculation_coefficient(q, "PassiveExecuteThreshold") == pytest.approx(
        zeri._ZAP_EXECUTE_AP_RATIO
    )
    assert data_value(q, "NumberOfMissiles") == pytest.approx(zeri._BURST_ROUNDS)


def test_yorick_passive_binary_constants_are_used():
    from src.calculator.champions import yorick

    passive = spell_object("Yorick", "YorickPassive")
    assert calculation_interpolation(
        passive, "YorickPassiveGhoulDamage"
    ) == pytest.approx(
        (yorick._MIST_WALKER_DAMAGE_START, yorick._MIST_WALKER_DAMAGE_END)
    )
    assert data_value(passive, "GhoulADRatio") == pytest.approx(
        yorick._MIST_WALKER_AD_RATIO
    )
    assert data_value(passive, "YorickPassiveGhoulMax") == pytest.approx(
        yorick._MIST_WALKER_MAX
    )


def test_zyra_passive_binary_constants_are_used():
    from src.calculator.champions import zyra

    passive = spell_object("Zyra", "ZyraP")
    assert calculation_interpolation(passive, "PlantDamage") == pytest.approx(
        (zyra._PLANT_DAMAGE_START, zyra._PLANT_DAMAGE_END)
    )
    assert data_value(passive, "APRatio") == pytest.approx(zyra._PLANT_AP_RATIO)
