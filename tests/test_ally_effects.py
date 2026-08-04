"""Fail-closed contracts for cached ally item effects."""

from copy import deepcopy

import pytest

from src.calculator import item_effects
from src.calculator.ally_effects import resolve_ally_stat_effects
from src.calculator.data_fetcher import get_item_by_name


def _staff() -> dict:
    return deepcopy(get_item_by_name("Staff of Flowing Water"))


def test_staff_of_flowing_water_rapids_reads_typed_ap_and_cached_ally_stats():
    (effect,) = resolve_ally_stat_effects((_staff(),))

    assert effect.ability_power == pytest.approx(40.0)
    assert effect.ability_haste == pytest.approx(15.0)
    assert effect.duration == pytest.approx(6.0)


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("abilityPower", "abilityPower.flat"),
        ("abilityHaste", "abilityHaste.flat"),
    ],
)
def test_staff_rapids_missing_stat_fails_closed(field: str, message: str):
    item = _staff()
    item["passives"][0]["stats"].pop(field)

    with pytest.raises(ValueError, match=message):
        resolve_ally_stat_effects((item,))


def test_staff_rapids_non_numeric_stat_fails_closed():
    item = _staff()
    item["passives"][0]["stats"]["abilityHaste"]["flat"] = "unknown"

    with pytest.raises(ValueError, match="abilityHaste.flat must be numeric"):
        resolve_ally_stat_effects((item,))


def test_staff_rapids_missing_duration_fails_closed():
    item = _staff()
    item["passives"][0]["branches"] = [
        "Healing or shielding an ally grants ability power."
    ]

    with pytest.raises(ValueError, match="missing numeric duration"):
        resolve_ally_stat_effects((item,))


def test_staff_rapids_non_numeric_duration_fails_closed():
    item = _staff()
    item["passives"][0]["branches"] = [
        "Healing or shielding an ally grants ability power for unknown seconds."
    ]

    with pytest.raises(ValueError, match="missing numeric duration"):
        resolve_ally_stat_effects((item,))


def test_staff_rapids_missing_passive_fails_closed():
    item = _staff()
    item["passives"] = []

    with pytest.raises(ValueError, match="missing its Rapids passive"):
        resolve_ally_stat_effects((item,))


def test_staff_rapids_missing_typed_ap_value_fails_closed(monkeypatch):
    broken = dict(item_effects.ITEM_EFFECTS["Staff of Flowing Water"])
    broken.pop("rapids_bonus_ap")
    monkeypatch.setitem(item_effects.ITEM_EFFECTS, "Staff of Flowing Water", broken)

    with pytest.raises(KeyError, match="rapids_bonus_ap"):
        resolve_ally_stat_effects((_staff(),))
