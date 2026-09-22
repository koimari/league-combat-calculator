"""What a fight breakdown row licenses its readers to assume.

``src/calculator/fight/ledger/breakdown.py`` is the one door onto
``state.breakdown``, the table every fight step writes its own rows into. A
reader that coerced whatever it found would price a ``True`` at one point of
damage, so what it does with a stamp no arithmetic produced is measured here
rather than described.
"""

import math

import pytest

from src.calculator.fight.ledger.breakdown import (
    source_total_damage,
    source_total_damage_is_malformed,
)

PRICED = {"name": "Q", "total_damage": 240.5, "damage_type": "physical"}
INFORMATIONAL = {"name": "Ferocity", "informational": True}

NO_ARITHMETIC_MADE_THESE = (True, False, "240.5", None, [240.5])


class TestAStampNoArithmeticMadeIsRefused:
    """The reader's half of the fail-closed contract, driven both ways."""

    def test_a_priced_row_reads_as_its_number(self):
        assert source_total_damage(PRICED) == 240.5

    def test_a_row_that_priced_nothing_reads_as_none(self):
        assert source_total_damage(INFORMATIONAL) is None

    @pytest.mark.parametrize("stamp", NO_ARITHMETIC_MADE_THESE)
    def test_a_non_number_is_refused_by_name(self, stamp):
        """``float(True)`` is ``1.0`` and ``float("x")`` raises naming
        neither the row nor the key: both are why this refuses."""
        with pytest.raises(ValueError, match="total_damage"):
            source_total_damage({"name": "Q", "total_damage": stamp})

    @pytest.mark.parametrize("stamp", NO_ARITHMETIC_MADE_THESE)
    def test_the_predicate_answers_every_stamp_the_reader_refuses(self, stamp):
        """A caller that withholds its own item asks this first, so the two
        can never disagree about which stamps are a producer break."""
        assert source_total_damage_is_malformed({"name": "Q", "total_damage": stamp})

    def test_neither_a_priced_nor_an_unpriced_row_is_malformed(self):
        """Absent is a row shape the engine writes; a bad stamp is not."""
        assert not source_total_damage_is_malformed(PRICED)
        assert not source_total_damage_is_malformed(INFORMATIONAL)

    def test_a_non_finite_total_is_not_a_producer_break(self):
        """NaN is arithmetic: the reader hands it back, and the callers that
        cannot use one test ``math.isfinite`` for themselves."""
        row = {"name": "Q", "total_damage": float("nan")}
        assert not source_total_damage_is_malformed(row)
        assert math.isnan(source_total_damage(row))
