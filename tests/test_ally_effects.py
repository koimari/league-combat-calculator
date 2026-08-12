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


def test_staff_rapids_missing_declared_value_fails_closed(monkeypatch):
    """A key the declaration needs is gone, so the buff stops rather than vanishes.

    Re-pointed from ``ITEM_EFFECTS['rapids_bonus_ap']`` when this path moved
    onto ``staff_of_flowing_water.rapids``, whose references are
    ``ALLY_ITEM_EFFECTS``' — the same three the walk's ``stat_buff`` emitter
    reads.  A missing key means the catalog compiles no producer at all, and
    the presence check is what turns that into a named refusal instead of a
    silently absent ally buff.
    """
    broken = dict(item_effects.ALLY_ITEM_EFFECTS["Staff of Flowing Water"])
    broken.pop("bonus_ability_power")
    monkeypatch.setitem(
        item_effects.ALLY_ITEM_EFFECTS, "Staff of Flowing Water", broken
    )

    with pytest.raises(ValueError, match="no rapids producer is declared"):
        resolve_ally_stat_effects((_staff(),))


def test_a_cached_record_that_outran_the_declaration_is_a_named_stop():
    """Patch day's divergence stops instead of becoming a number one engine sees.

    Before this path read the declaration, the cached ability haste *was* the
    number here while the walk's packet used the declared one — so a wiki
    bump moved one surface and not the other, with no symptom.  Now the two
    read one registry and the record they cite is checked against it.
    """
    item = _staff()
    item["passives"][0]["stats"]["abilityHaste"]["flat"] = 20.0

    with pytest.raises(ValueError, match="bonus_ability_haste=15.0"):
        resolve_ally_stat_effects((item,))


def test_an_ally_producer_of_another_shape_does_not_reach_this_path():
    """Redemption declares an ally packet and grants the attacker no stats."""
    assert resolve_ally_stat_effects((get_item_by_name("Redemption"),)) == ()
