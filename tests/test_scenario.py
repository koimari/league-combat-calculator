"""Contracts for champion-derived ally and enemy loadouts."""

import pytest

from src.calculator.scenario import ChampionLoadout, parse_roster


def test_loadout_resolves_level_items_and_health_components():
    loadout = ChampionLoadout(
        champion="Galio",
        level=12,
        items=("Hollow Radiance",),
    ).resolve()

    assert loadout.stats["health"] == 2240
    assert loadout.stats["base_health"] == 1840
    assert loadout.stats["bonus_health"] == 400
    assert loadout.stats["magic_resistance"] == 92
    assert loadout.stats["bonus_magic_resistance"] == 40
    assert loadout.stats["health"] == (
        loadout.stats["base_health"] + loadout.stats["bonus_health"]
    )
    assert loadout.defenses.magic_shield == pytest.approx(254.95, abs=0.1)
    assert loadout.defenses.sources[0].revision_id == 3990299
    assert loadout.defenses.coverage == "modeled_starting_passive"


def test_unmodeled_starting_defense_is_labeled_base_and_items_only():
    loadout = ChampionLoadout(champion="Kai'Sa", level=14).resolve()

    assert loadout.defenses.coverage == "base_and_items_only"


def test_loadout_level_changes_derived_stats():
    level_one = ChampionLoadout(champion="Ziggs", level=1).resolve()
    level_twelve = ChampionLoadout(champion="Ziggs", level=12).resolve()

    assert level_twelve.stats["health"] > level_one.stats["health"]
    assert level_twelve.stats["attack_damage"] > level_one.stats["attack_damage"]
    assert level_twelve.stats["armor"] > level_one.stats["armor"]


def test_loadout_applies_stateful_item_options():
    loadout = ChampionLoadout.from_request(
        {
            "champion": "Ziggs",
            "level": 12,
            "items": ["Dark Seal"],
            "item_options": {"Dark Seal": {"glory_stacks": 10}},
        },
        field="loadout",
    ).resolve()

    assert loadout.stats["ability_power"] == 55


@pytest.mark.parametrize(
    "items",
    [
        ["Lich Bane", "Trinity Force"],
        ["Dark Seal", "Mejai's Soulstealer"],
    ],
)
def test_loadout_rejects_mutually_exclusive_items(items):
    with pytest.raises(ValueError, match="cannot be equipped together"):
        ChampionLoadout(champion="Ziggs", level=12, items=tuple(items)).resolve()


def test_loadout_rejects_tier_three_boots_without_mid_quest():
    with pytest.raises(ValueError, match="requires tier-2 boots"):
        ChampionLoadout(
            champion="Ziggs", level=12, boots="Spellslinger's Shoes"
        ).resolve()


def test_bottom_role_quest_allows_seven_combat_slots():
    loadout = ChampionLoadout(
        champion="Ziggs",
        level=18,
        items=(
            "Rabadon's Deathcap",
            "Shadowflame",
            "Luden's Echo",
            "Stormsurge",
            "Zhonya's Hourglass",
            "Banshee's Veil",
        ),
        boots="Sorcerer's Shoes",
        role="bottom",
        role_quest_complete=True,
    ).resolve()

    assert len(loadout.item_data) == 7


@pytest.mark.parametrize(
    ("roster", "message"),
    [
        ([{"champion": "Galio", "level": 0}], "level must be between"),
        ([{"champion": "Galio", "level": True}], "level must be an integer"),
        ([{"champion": "Galio", "items": "Hollow Radiance"}], "items must be a list"),
        (
            [
                {"champion": "Galio", "level": 12},
                {"champion": "galio", "level": 11},
            ],
            "must not contain duplicate champions",
        ),
    ],
)
def test_parse_roster_rejects_invalid_loadouts(roster, message):
    with pytest.raises(ValueError, match=message):
        parse_roster({"enemies": roster}, "enemies", maximum=5)


def test_parse_roster_enforces_team_size():
    roster = [{"champion": f"Champion {index}"} for index in range(6)]

    with pytest.raises(ValueError, match="at most 5 champions"):
        parse_roster({"enemies": roster}, "enemies", maximum=5)
