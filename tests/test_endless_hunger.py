"""Focused tests for Endless Hunger's parser-backed Famine conversion."""

from typing import cast

import pytest

from src.calculator import item_effects
from src.calculator.data_fetcher import fetch_item_data, get_item_by_name
from src.calculator.item_effects import endless_hunger_ability_haste
from src.calculator.passive_parser import parse_item_effect
from src.calculator.stats import calculate_total_stats


def test_famine_parser_sources_base_and_melee_ranged_ratios() -> None:
    """Famine's cached branch yields 5 AH and its split AD ratios."""
    parsed = parse_item_effect("Endless Hunger", fetch_item_data())
    if parsed is None:
        pytest.fail("Endless Hunger parser returned no values")
    values = cast("dict[str, float]", parsed)

    assert values.get("famine_base_ability_haste") == pytest.approx(5.0)
    assert values.get("famine_bonus_ad_to_ability_haste_melee") == pytest.approx(0.13)
    assert values.get("famine_bonus_ad_to_ability_haste_ranged") == pytest.approx(0.10)


@pytest.mark.parametrize(
    ("is_melee", "expected"),
    [(True, 13.45), (False, 11.5)],
)
def test_famine_ability_haste_uses_typed_split(is_melee: bool, expected: float) -> None:
    """Bonus AD converts through Famine's melee/ranged parser values."""
    assert endless_hunger_ability_haste(
        [{"name": "Endless Hunger"}],
        bonus_attack_damage=65.0,
        is_melee=is_melee,
    ) == pytest.approx(expected)


def test_endless_hunger_ability_haste_enters_total_stats(ahri_data: dict) -> None:
    """The stat pipeline applies Famine on top of the item's 65 AD."""
    stats = calculate_total_stats(
        ahri_data,
        18,
        [get_item_by_name("Endless Hunger")],
    )

    assert stats["ability_haste"] == pytest.approx(11.5)


def test_famine_missing_parser_value_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing parser-owned Famine value names the item and key."""
    broken = dict(item_effects.ITEM_EFFECTS["Endless Hunger"])
    broken.pop("famine_base_ability_haste")
    monkeypatch.setitem(item_effects.ITEM_EFFECTS, "Endless Hunger", broken)

    with pytest.raises(KeyError, match=r"Endless Hunger.*famine_base_ability_haste"):
        endless_hunger_ability_haste(
            [{"name": "Endless Hunger"}],
            bonus_attack_damage=65.0,
            is_melee=True,
        )
