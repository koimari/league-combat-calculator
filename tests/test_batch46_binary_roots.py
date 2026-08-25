"""Certification tests for batch 46's exact champion binary roots."""

import pytest

from src.calculator.binary_roots import (
    calculation_coefficient,
    data_value,
    spell_object,
)


def test_rammus_w_flat_thorns_damage_comes_from_the_binary():
    from src.calculator.champions import rammus

    w = spell_object("Rammus", "DefensiveBallCurl")
    assert data_value(w, "FlatDamageReturn") == pytest.approx(rammus._THORNS_BASE)


def test_rengar_ferocity_cap_comes_from_the_binary():
    from src.calculator.champions import rengar

    p = spell_object("Rengar", "RengarPassive")
    assert int(data_value(p, "MaxFerocity")) == rengar._FEROCITY_MAX


def test_sett_right_punch_bonus_ad_ratio_comes_from_the_binary():
    from src.calculator.champions import sett

    p = spell_object("Sett", "SettPassive")
    assert calculation_coefficient(p, "RightPunchBonus") == pytest.approx(
        sett._RIGHT_PUNCH_BONUS_AD_RATIO
    )


def test_teemo_r_debuff_duration_comes_from_the_binary():
    from src.calculator.champions import teemo

    r = spell_object("Teemo", "TeemoR")
    assert data_value(r, "DebuffDuration") == pytest.approx(teemo._R_DOT_SECONDS)


def test_viego_q_second_attack_ad_ratio_comes_from_the_binary():
    from src.calculator.champions import viego

    q = spell_object("Viego", "ViegoQ")
    assert calculation_coefficient(q, "SecondAttackDamage") == pytest.approx(
        viego._Q_SECOND_STRIKE_AD_RATIO
    )
