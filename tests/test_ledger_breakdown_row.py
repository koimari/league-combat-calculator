"""What a fight breakdown row licenses its readers to assume.

``src/calculator/fight/ledger/breakdown.py`` is the one door onto
``state.breakdown``, the table every fight step writes its own rows into.
Two claims decide whether a converted site is a fix or a new crash: which
fields a row carries, re-derived here from the internal census corpus rather
than trusted, and what a reader does with a stamp no arithmetic produced.
"""

import json
import math
from pathlib import Path

import pytest

from src.calculator.fight.ledger.breakdown import (
    source_casts,
    source_damage_events,
    source_damage_per_hit,
    source_damage_type,
    source_event_phase,
    source_hit_count,
    source_total_damage,
    source_total_damage_is_malformed,
    source_total_raw,
)

CENSUS = Path("docs/receipts/internal-row-census.json")

PRICED = {"name": "Q", "total_damage": 240.5, "damage_type": "physical"}
INFORMATIONAL = {"name": "Ferocity", "informational": True}

NO_ARITHMETIC_MADE_THESE = (True, False, "240.5", None, [240.5])

#: Every reader the module publishes, the key it reads and a stamp of the
#: shape a producer writes.
READERS = (
    (source_total_damage, "total_damage", 240.5),
    (source_damage_type, "damage_type", "physical"),
    (source_casts, "casts", 3),
    (source_total_raw, "total_raw", 412.0),
    (source_damage_events, "damage_events", [{"time": 1.0, "damage": 40.0}]),
    (source_event_phase, "event_phase", "ability"),
    (source_hit_count, "count", 4),
    (source_damage_per_hit, "damage_per_hit", 60.125),
)


def _breakdown_census() -> dict:
    """The committed corpus for this row shape, one fight per champion."""
    return json.loads(CENSUS.read_text(encoding="utf-8"))["streams"]["breakdown"]


class TestThePopulationIsMeasuredNotAsserted:
    """``tests/test_internal_row_census.py`` holds the corpus against the
    engine; these hold the module's contract against the corpus."""

    def test_the_corpus_has_rows_to_measure(self):
        """A vacuous corpus would make every claim below pass by emptiness."""
        assert _breakdown_census()["rows"] > 500

    def test_the_name_is_the_only_field_every_row_carries(self):
        """Why every reader below is optional: no numeric field is universal,
        so a required reader of one is not licensed by anything."""
        assert _breakdown_census()["universal"] == ["name"]

    @pytest.mark.parametrize("key", [key for _reader, key, _stamp in READERS])
    def test_every_field_a_reader_takes_is_sometimes_absent(self, key):
        """The trap this file exists to stop: a field on nearly every row
        reads as universal to a skimmer and is not."""
        census = _breakdown_census()
        assert 0 < census["keys"].get(key, 0) < census["rows"], key


class TestEveryReaderAnswersNoneRatherThanASubstitute:
    """The other half of optional: what a reader does with a row that
    stamped nothing, which is what a converted call site now branches on."""

    @pytest.mark.parametrize(
        ("reader", "key", "stamp"),
        READERS,
        ids=[key for _reader, key, _stamp in READERS],
    )
    def test_a_stamped_field_reads_back_as_itself(self, reader, key, stamp):
        assert reader({"name": "Q", key: stamp}) == stamp

    @pytest.mark.parametrize(
        ("reader", "key", "stamp"),
        READERS,
        ids=[key for _reader, key, _stamp in READERS],
    )
    def test_an_unstamped_field_reads_as_none(self, reader, key, stamp):
        assert reader(INFORMATIONAL) is None

    def test_the_packet_list_is_the_row_s_own_list(self):
        """Not a copy: a caller that walks or edits it must see the row the
        fight step is still writing into."""
        row = {"name": "Q", "damage_events": [{"time": 1.0, "damage": 40.0}]}
        assert source_damage_events(row) is row["damage_events"]


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
