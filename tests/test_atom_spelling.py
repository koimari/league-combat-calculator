"""The atom unit for a cached stat field: four spellings, and nothing else reads as flat."""

import pytest

from src.calculator.atom_spelling import _stat_unit


@pytest.mark.parametrize(
    ("field", "unit"),
    [
        ("flat", "flat"),
        ("perLevel", "per_level"),
        ("percent", "percent"),
        ("percentPerLevel", "percent_per_level"),
    ],
)
def test_each_cached_spelling_has_its_unit(field, unit):
    assert _stat_unit(field) == unit


def test_an_unknown_field_raises_instead_of_reading_as_flat():
    with pytest.raises(KeyError, match="percentBase"):
        _stat_unit("percentBase")
