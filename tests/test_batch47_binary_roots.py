"""Certification tests for batch 47's exact champion binary roots."""

import pytest

from src.calculator.binary_roots import (
    calculation_coefficient,
    data_value,
    spell_object,
)


def test_senna_r_mist_shield_ratio_comes_from_the_binary():
    from src.calculator.champions import senna

    r = spell_object("Senna", "SennaR")
    assert calculation_coefficient(r, "TotalShield") == pytest.approx(
        senna._DAWNING_SHADOW_MIST_RATIO
    )


def test_xin_zhao_w_thrust_crit_amp_comes_from_the_binary():
    from src.calculator.champions import xin_zhao

    w = spell_object("Xin Zhao", "XinZhaoW")
    assert data_value(w, "CritChanceAmp") == pytest.approx(
        xin_zhao._W_THRUST_CRIT_CHANCE_AMP
    )


def test_zac_revive_cooldown_comes_from_the_binary():
    from src.calculator.champions import zac

    p = spell_object("Zac", "ZacPassiveChunkDrop")
    assert data_value(p, "ReviveCooldown") == pytest.approx(zac.REVIVE_COOLDOWN_SECONDS)


def test_zed_death_mark_duration_comes_from_the_binary():
    from src.calculator.champions import zed

    r = spell_object("Zed", "ZedR")
    assert data_value(r, "RDeathMarkDuration") == pytest.approx(
        zed._DEATH_MARK_DETONATION_DELAY
    )
