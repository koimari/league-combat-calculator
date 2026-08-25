"""Certification tests for batch 50's exact champion binary roots."""

import pytest

from src.calculator.binary_roots import (
    calculation_coefficient,
    calculation_coefficients,
    data_value,
    spell_object,
)


def test_taliyah_worked_ground_constants_come_from_the_binary():
    from src.calculator.champions import taliyah

    q = spell_object("Taliyah", "TaliyahQ")
    e = spell_object("Taliyah", "TaliyahE")
    assert data_value(e, "DelayBetweenRows") == pytest.approx(taliyah._E_ROW_INTERVAL)
    assert data_value(q, "BigRockManaCost") == pytest.approx(taliyah._Q_WORKED_COST)
    assert data_value(q, "WorkedGroundCDR") == pytest.approx(
        taliyah._Q_WORKED_COOLDOWN_MULTIPLIER
    )
    assert data_value(q, "MinimumWorkedGroundCD") == pytest.approx(
        taliyah._Q_WORKED_MINIMUM_COOLDOWN
    )


def test_jayce_transform_constants_come_from_the_binary():
    from src.calculator.champions import jayce

    stance = spell_object("Jayce", "JayceStanceHtG")
    field = spell_object("Jayce", "JayceStaticField")
    assert calculation_coefficient(stance, "Resists") == pytest.approx(
        jayce.HAMMER_RESISTS_BONUS_AD_RATIO
    )
    assert data_value(stance, "ADRatio") == pytest.approx(
        jayce.HAMMER_EMPOWERED_AUTO_BONUS_AD_RATIO
    )
    assert data_value(stance, "ShredDuration") == pytest.approx(
        jayce.CANNON_SHRED_DURATION
    )
    assert data_value(field, "Duration") == pytest.approx(
        jayce.LIGHTNING_FIELD_DURATION
    )


def test_rell_break_the_mold_ratios_keep_binary_stat_order():
    from src.calculator.champions import rell

    passive = spell_object("Rell", "RellP")
    assert calculation_coefficients(passive, "OnHitDamage") == pytest.approx(
        (rell._BREAK_THE_MOLD_ARMOR_RATIO, rell._BREAK_THE_MOLD_MR_RATIO)
    )


def test_aphelios_calibrum_mark_ratio_comes_from_the_binary():
    from src.calculator.champions import aphelios

    q = spell_object("Aphelios", "ApheliosCalibrumQ")
    assert calculation_coefficient(q, "BonusDamagePerMark") == pytest.approx(
        aphelios._CALIBRUM_MARK_BONUS_AD_RATIO
    )


def test_diana_cleave_cadence_comes_from_the_binary():
    from src.calculator.champions import diana

    passive = spell_object("Diana", "DianaPassive")
    assert data_value(passive, "AttackCount") == pytest.approx(
        diana._CLEAVE_EVERY_N_ATTACKS
    )
