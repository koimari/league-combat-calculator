"""Certification tests for batch 51's exact champion binary roots."""

import pytest

from src.calculator.binary_roots import (
    calculation_coefficient,
    data_value,
    spell_object,
)


def test_ivern_daisy_ap_ratios_come_from_the_binary():
    from src.calculator.champions import ivern

    r = spell_object("Ivern", "IvernR")
    assert calculation_coefficient(r, "TotalDaisyAD") == pytest.approx(
        ivern._DAISY_AD_AP_RATIO
    )
    assert calculation_coefficient(r, "TotalShockwaveDamage") == pytest.approx(
        ivern._DAISY_SMASH_AP_RATIO
    )


def test_smolder_tier_three_burn_ratio_preserves_percent_units():
    from src.calculator.champions import smolder

    q = spell_object("Smolder", "SmolderQ")
    assert calculation_coefficient(q, "Tier3_Burn") * 10000.0 == pytest.approx(
        smolder._BURN_BONUS_AD_PER_100
    )


def test_nunu_passive_grants_come_from_the_binary():
    from src.calculator.champions import nunu_willump

    passive = spell_object("Nunu", "NunuPassive")
    assert data_value(passive, "ASIncrease") * 100.0 == pytest.approx(
        nunu_willump._P_BONUS_ATTACK_SPEED
    )
    assert data_value(passive, "MSIncrease") * 100.0 == pytest.approx(
        nunu_willump._P_BONUS_MOVEMENT_SPEED
    )


def test_velkoz_proc_ap_ratio_comes_from_the_binary():
    from src.calculator.champions import velkoz

    passive = spell_object("Vel'Koz", "VelkozPassive")
    assert calculation_coefficient(passive, "TotalDamage") == pytest.approx(
        velkoz._PROC_AP_RATIO
    )


def test_braum_already_stunned_ratio_comes_from_the_binary():
    from src.calculator.champions import braum

    passive = spell_object("Braum", "BraumPassive")
    assert data_value(passive, "AlreadyStunnedDamageAmp") == pytest.approx(
        braum._BONUS_AUTO_RATIO
    )
