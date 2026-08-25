"""Binary-root certification for Akshan's Comeuppance cap."""

import pytest

from src.calculator.binary_roots import data_value, spell_object


def test_akshan_r_max_increase_certifies_missing_health_cap():
    """The binary's 3x endpoint is the sourced +200% bonus cap."""
    from src.calculator.champions import akshan

    r = spell_object("Akshan", "AkshanR")
    maximum_multiplier = data_value(r, "MaxIncrease")

    assert maximum_multiplier - 1.0 == pytest.approx(akshan._R_MISSING_HP_MAX_BONUS)
