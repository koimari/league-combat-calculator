"""The stamped-field read the cast, damage and heal row readers share."""

import pytest

from src.calculator.event_row_field import required_field


def test_a_stamped_field_is_read_back_as_written():
    row = {"time": 2.0, "amount": 45.0}
    assert required_field(row, "amount", kind="heal event", stamper="the walk") == 45.0


def test_an_absent_field_is_refused_naming_the_row_and_its_stamper():
    row = {"time": 2.0}
    with pytest.raises(ValueError, match="cast event carries no 'slot'") as caught:
        required_field(row, "slot", kind="cast event", stamper="ability_rotation")
    assert "ability_rotation stamps it" in str(caught.value)
    assert "['time']" in str(caught.value)
