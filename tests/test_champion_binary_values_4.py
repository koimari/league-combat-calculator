"""Certification tests for batch 49's exact champion binary roots."""

import pytest

from src.calculator.binary_roots import (
    calculation_coefficient,
    data_value,
    data_value_at_rank,
    spell_object,
)


def test_neeko_r_shield_binary_constants_are_used():
    from src.calculator.champions import neeko

    r = spell_object("Neeko", "NeekoR")
    assert tuple(
        data_value_at_rank(r, "ShieldAmount", index) for index in (1, 3, 5)
    ) == pytest.approx(neeko._R_SHIELD_AMOUNT)
    assert tuple(
        data_value_at_rank(r, "ShieldPerChampion", rank) for rank in range(1, 4)
    ) == pytest.approx(neeko._R_SHIELD_PER_CHAMPION)
    assert calculation_coefficient(r, "BaseShield") == pytest.approx(
        neeko._R_SHIELD_AP_RATIO
    )
    assert calculation_coefficient(r, "ShieldMultiplier") == pytest.approx(
        neeko._R_SHIELD_PER_CHAMPION_AP_RATIO
    )
    assert data_value_at_rank(r, "ShieldDuration", 1) == pytest.approx(
        neeko._R_SHIELD_DURATION
    )


def test_darius_passive_bleed_ratio_comes_from_the_binary():
    from src.calculator.champions import darius

    passive = spell_object("Darius", "DariusHemoMarker")
    assert calculation_coefficient(passive, "BleedDamagePerStack") == pytest.approx(
        darius.P_BLEED_BONUS_AD_RATIO
    )


def test_kassadin_w_passive_terms_come_from_the_binary():
    from src.calculator.champions import kassadin

    w = spell_object("Kassadin", "NetherBlade")
    assert data_value(w, "PassiveBaseDamage") == pytest.approx(kassadin.PASSIVE_W_BASE)
    assert calculation_coefficient(w, "OnHitDamage") == pytest.approx(
        kassadin.PASSIVE_W_AP_RATIO
    )


def test_malphite_granite_shield_ratio_comes_from_the_binary():
    from src.calculator.champions import malphite

    passive = spell_object("Malphite", "MalphiteShield")
    assert calculation_coefficient(passive, "TotalShield") == pytest.approx(
        malphite.GRANITE_SHIELD_MAX_HP_RATIO
    )


def test_master_yi_double_strike_ratio_comes_from_the_binary():
    from src.calculator.champions import master_yi

    passive = spell_object("Master Yi", "MasterYiPassive")
    assert calculation_coefficient(passive, "TotalDamage") == pytest.approx(
        master_yi._SECOND_STRIKE_AD_RATIO
    )
