"""The cast-event row's contract, and the refusal for a row that breaks it.

``fight.rotation.ability_rotation`` stamps ``time``, ``slot``, ``name``,
``ordinal``, ``cast_id``, ``target_id`` and ``resource_cost`` on every
``cast_events`` row it builds, unconditionally. Four modules read those
fields, and every read carried a literal default: ``time`` fell back to
``0.0`` and ``slot`` to ``""``.

Neither default could fire while the producer was whole, which is why they
survived review. They are still the rule-5 failure shape: the day the
producer stopped stamping one, a cast would be placed at the fight's own
origin, or attributed to no slot, and nothing would say so (ER5).
"""

import pytest

from src.calculator.cast_event_row import cast_ordinal, cast_slot, cast_time

STAMPED = {
    "time": 3.25,
    "slot": "Q",
    "name": "Rampage",
    "ordinal": 2,
    "cast_id": "Q:2",
    "target_id": "target:0",
    "resource_cost": 30.0,
}


class TestAStampedRowReadsItsOwnFields:
    def test_each_accessor_returns_the_producer_s_value(self):
        assert cast_time(STAMPED) == 3.25
        assert cast_slot(STAMPED) == "Q"
        assert cast_ordinal(STAMPED) == 2

    def test_a_cast_at_the_fight_s_own_origin_is_a_real_cast(self):
        """The distinction the ``0.0`` default erased.

        ``t=0`` is where the opening cast of most rotations lands, so the
        default was indistinguishable from the most common real value.
        """
        assert cast_time({**STAMPED, "time": 0.0}) == 0.0


class TestAnUnstampedRowIsRefused:
    @pytest.mark.parametrize(
        ("field", "reader"),
        [("time", cast_time), ("slot", cast_slot), ("ordinal", cast_ordinal)],
    )
    def test_a_missing_field_raises_and_names_itself(self, field, reader):
        row = {key: value for key, value in STAMPED.items() if key != field}
        with pytest.raises(ValueError, match=field):
            reader(row)

    def test_the_refusal_reports_what_the_row_does_carry(self):
        """So a reader can tell a broken producer from a foreign row."""
        with pytest.raises(ValueError, match=r"'name'.*'ordinal'"):
            cast_time({"name": "Rampage", "ordinal": 1})


def test_the_producer_still_stamps_every_field_this_module_reads():
    """The contract is checked against the producer, not against memory.

    A field ``ability_rotation`` stopped stamping would turn this red here,
    naming it, rather than turning every consumer red at once.
    """
    from pathlib import Path

    source = Path("src/calculator/fight/rotation/ability_rotation.py").read_text(
        encoding="utf-8"
    )
    # To the comprehension's own `for`, not to the first "),": the row
    # literal contains one, and cutting there hid every field after it.
    block = source.split("result.cast_events = sorted(", 1)[1].split(
        "for ability_key, times in", 1
    )[0]
    for field in ("time", "slot", "name", "ordinal", "cast_id"):
        assert f'"{field}":' in block, field
