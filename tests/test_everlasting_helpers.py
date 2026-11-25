"""The two pure steps carved out of Fimbulwinter's Everlasting walk."""

from types import SimpleNamespace

import pytest

from src.calculator import item_support_everlasting as everlasting

_GATE = {
    "status": "script_authorized",
    "threshold_ratio": 0.3,
    "comparison": "current_mana > maximum_mana * ratio",
}


class TestAuthorizedManaThreshold:
    def test_an_authorized_gate_answers_its_ratio(self):
        assert everlasting._authorized_mana_threshold(_GATE) == pytest.approx(0.3)

    @pytest.mark.parametrize(
        ("field", "value", "message"),
        [
            ("status", "invented", "unsupported authority status"),
            ("threshold_ratio", None, "requires a valid threshold_ratio"),
            ("comparison", "current_mana >= 0", "exact comparison contract"),
        ],
    )
    def test_an_unusable_authority_raises_rather_than_denies(
        self, field, value, message
    ):
        with pytest.raises(ValueError, match=message):
            everlasting._authorized_mana_threshold(dict(_GATE, **{field: value}))


class TestRangeMultiplier:
    _AUTHORITY = {"range_units": 1200.0, "multiplier": 2.0, "minimum_enemy_count": 2}

    def _call(self, monkeypatch, count, reason):
        monkeypatch.setattr(
            everlasting,
            "enemies_within_range",
            lambda holder, actors, units: (count, reason),
        )
        return everlasting._range_multiplier(SimpleNamespace(), (), self._AUTHORITY)

    def test_enough_nearby_enemies_take_the_sourced_multiplier(self, monkeypatch):
        assert self._call(monkeypatch, 2, None) == (2, None, 2.0)

    def test_too_few_nearby_enemies_keep_the_base_shield(self, monkeypatch):
        assert self._call(monkeypatch, 1, None) == (1, None, 1.0)

    def test_an_unreadable_spatial_input_counts_none_and_keeps_the_base(
        self, monkeypatch
    ):
        assert self._call(monkeypatch, 3, "missing_holder_position") == (
            0,
            "missing_holder_position",
            1.0,
        )
