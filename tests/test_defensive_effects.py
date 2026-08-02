"""Sourced target-defense formulas resolved before the fight engine runs."""

import pytest

from src.calculator.defensive_effects import resolve_starting_defenses


def _stats(**overrides):
    stats = {
        "health": 2000.0,
        "bonus_health": 0.0,
        "bonus_attack_damage": 0.0,
        "max_mana": 0.0,
        "is_melee": False,
    }
    stats.update(overrides)
    return stats


@pytest.mark.parametrize(
    ("level", "is_melee", "expected"),
    [
        (1, True, 110.0),
        (18, True, 280.0),
        (1, False, 82.5),
        (18, False, 210.0),
    ],
)
def test_hexdrinker_lifeline_scales_by_level_and_range_type(
    level, is_melee, expected
):
    defenses = resolve_starting_defenses(
        "Kai'Sa",
        level,
        _stats(is_melee=is_melee),
        [{"name": "Hexdrinker"}],
    )

    assert defenses.threshold_shield_amount == pytest.approx(expected)
    assert defenses.threshold_shield_damage_type == "magic"
    assert defenses.threshold_shield_duration == 2.5


@pytest.mark.parametrize(
    ("is_melee", "expected"),
    [(True, 290.0), (False, 217.5)],
)
def test_maw_lifeline_scales_from_bonus_ad_and_range_type(is_melee, expected):
    defenses = resolve_starting_defenses(
        "Aatrox",
        18,
        _stats(is_melee=is_melee, bonus_attack_damage=60.0),
        [{"name": "Maw of Malmortius"}],
    )

    assert defenses.threshold_shield_amount == pytest.approx(expected)
    assert defenses.threshold_shield_damage_type == "magic"
    assert defenses.threshold_shield_duration == 3.0


def test_seraph_lifeline_scales_from_maximum_mana():
    defenses = resolve_starting_defenses(
        "Orianna",
        18,
        _stats(max_mana=2500.0),
        [{"name": "Seraph's Embrace"}],
    )

    assert defenses.threshold_shield_amount == pytest.approx(450.0)
    assert defenses.threshold_shield_damage_type == "all"


def test_sterak_lifeline_scales_from_bonus_health_and_spirit_visage():
    defenses = resolve_starting_defenses(
        "Aatrox",
        18,
        _stats(is_melee=True, bonus_health=500.0),
        [{"name": "Sterak's Gage"}, {"name": "Spirit Visage"}],
    )

    assert defenses.threshold_shield_amount == pytest.approx(375.0)
    assert defenses.threshold_shield_duration == 4.5
    assert any("increases every modeled shield" in note for note in defenses.assumptions)


def test_lifeline_summary_carries_revision_backed_source():
    defenses = resolve_starting_defenses(
        "Kai'Sa", 18, _stats(), [{"name": "Hexdrinker"}]
    )

    summary = defenses.public_summary()
    assert summary["threshold_shield"] == {
        "amount": 210.0,
        "health_ratio": 0.3,
        "duration": 2.5,
        "damage_type": "magic",
    }
    assert summary["sources"][0]["revision_id"] == 3905721

