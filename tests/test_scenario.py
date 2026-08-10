"""Contracts for champion-derived ally and enemy loadouts."""

import pytest

from src.calculator.calculate import calculate_payload
from src.calculator.data_fetcher import get_champion
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
    assert loadout.defenses.coverage == "modeled_starting_defenses"


def test_unmodeled_starting_defense_is_labeled_base_and_items_only():
    loadout = ChampionLoadout(champion="Kai'Sa", level=14).resolve()

    assert loadout.defenses.coverage == "base_and_items_only"


def test_kaenic_adds_ready_max_health_magic_shield():
    loadout = ChampionLoadout(
        champion="Kai'Sa", level=14, items=("Kaenic Rookern",)
    ).resolve()

    assert loadout.defenses.magic_shield == pytest.approx(
        loadout.stats["health"] * 0.15
    )
    assert "previous 15 seconds" in loadout.defenses.assumptions[0]
    assert loadout.defenses.sources[0].revision_id == 3984971


def test_spirit_visage_amplifies_champion_and_kaenic_shields():
    without_visage = ChampionLoadout(
        champion="Galio", level=12, items=("Kaenic Rookern",)
    ).resolve()
    with_visage = ChampionLoadout(
        champion="Galio",
        level=12,
        items=("Kaenic Rookern", "Spirit Visage"),
    ).resolve()

    # Spirit Visage itself adds health, so compare against the two shield
    # formulas evaluated from the final build rather than the other loadout.
    galio_percent = 7.5 + (13.5 - 7.5) * 11 / 17
    expected_before_amp = with_visage.stats["health"] * (galio_percent / 100 + 0.15)
    assert with_visage.defenses.magic_shield == pytest.approx(
        expected_before_amp * 1.25
    )
    assert with_visage.defenses.magic_shield > without_visage.defenses.magic_shield
    assert with_visage.defenses.sources[-1].revision_id == 4016166


def test_target_items_resolve_sourced_incoming_damage_modifiers():
    loadout = ChampionLoadout(
        champion="Galio",
        level=12,
        items=("Warden's Mail", "Randuin's Omen"),
        boots="Plated Steelcaps",
    ).resolve()

    assert loadout.defenses.basic_damage_multiplier == pytest.approx(0.90)
    assert loadout.defenses.basic_damage_flat_reduction == 15
    assert loadout.defenses.basic_damage_flat_reduction_cap == pytest.approx(0.20)
    assert loadout.defenses.critical_strike_damage_multiplier == pytest.approx(0.70)
    assert [source.revision_id for source in loadout.defenses.sources[-3:]] == [
        4022248,
        3987228,
        4021798,
    ]

    public = loadout.defenses.public_summary()["incoming_damage"]
    assert public == {
        "basic_damage_multiplier": 0.9,
        "basic_damage_flat_reduction": 15.0,
        "basic_damage_flat_reduction_cap": 0.2,
        "critical_strike_damage_multiplier": 0.7,
    }


def test_shieldbow_resolves_level_scaled_threshold_shield():
    level_eight = ChampionLoadout(
        champion="Kai'Sa", level=8, items=("Immortal Shieldbow",)
    ).resolve()
    level_nine = ChampionLoadout(
        champion="Kai'Sa", level=9, items=("Immortal Shieldbow",)
    ).resolve()
    level_eighteen = ChampionLoadout(
        champion="Kai'Sa", level=18, items=("Immortal Shieldbow",)
    ).resolve()

    assert level_eight.defenses.threshold_shield_amount == 400
    assert level_nine.defenses.threshold_shield_amount == 430
    assert level_eighteen.defenses.threshold_shield_amount == 700
    assert level_eighteen.defenses.threshold_shield_health_ratio == pytest.approx(0.30)
    assert level_eighteen.defenses.threshold_shield_duration == 3
    assert level_eighteen.defenses.sources[-1].revision_id == 4030401


def test_spirit_visage_amplifies_shieldbow_lifeline():
    loadout = ChampionLoadout(
        champion="Kai'Sa",
        level=18,
        items=("Immortal Shieldbow", "Spirit Visage"),
    ).resolve()

    assert loadout.defenses.threshold_shield_amount == pytest.approx(875)


def test_protoplasm_is_exposed_as_temporary_health_and_healing():
    loadout = ChampionLoadout(
        champion="Shen", level=7, items=("Protoplasm Harness",)
    ).resolve()

    assert loadout.defenses.threshold_health_bonus == pytest.approx(170.588235)
    assert loadout.defenses.threshold_health_heal == pytest.approx(205.882353)
    public = loadout.defenses.public_summary()
    assert public["threshold_health"] == {
        "bonus_health": 170.6,
        "healing": 205.9,
        "health_ratio": 0.3,
        "duration": 5.0,
    }


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
        ["Sheen", "Trinity Force"],
        ["Dark Seal", "Mejai's Soulstealer"],
        ["Bami's Cinder", "Sunfire Aegis"],
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


def test_loadout_allows_tier_three_boots_after_mid_quest_completion():
    loadout = ChampionLoadout(
        champion="Ziggs",
        level=12,
        boots="Spellslinger's Shoes",
        role="mid",
        role_quest_complete=True,
    ).resolve()

    assert loadout.item_data[0]["name"] == "Spellslinger's Shoes"
    assert loadout.stats["magic_penetration_flat"] == 18.0


def test_loadout_rejects_tier_two_boots_after_mid_quest_completion():
    with pytest.raises(ValueError, match="requires tier-3 boots"):
        ChampionLoadout(
            champion="Ziggs",
            level=12,
            boots="Sorcerer's Shoes",
            role="mid",
            role_quest_complete=True,
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
    "item_name",
    [
        "Celestial Opposition",
        "Dream Maker",
        "Zaz'Zak's Realmspike",
        "Solstice Sleigh",
        "Bloodsong",
    ],
)
def test_completed_support_quest_allows_one_upgraded_support_item(item_name):
    loadout = ChampionLoadout(
        champion="Nami",
        level=12,
        items=(item_name,),
        boots="Ionian Boots of Lucidity",
        role="support",
        role_quest_complete=True,
    ).resolve()

    assert item_name in [item["name"] for item in loadout.item_data]


def test_support_quest_blocks_upgraded_item_until_completion():
    with pytest.raises(ValueError, match="complete the support quest"):
        ChampionLoadout(
            champion="Nami",
            level=12,
            items=("Dream Maker",),
            boots="Ionian Boots of Lucidity",
            role="support",
            role_quest_complete=False,
        ).resolve()


def test_support_quest_rejects_support_item_for_non_support_role():
    with pytest.raises(ValueError, match="require the support role"):
        ChampionLoadout(
            champion="Nami",
            level=12,
            items=("Dream Maker",),
            boots="Ionian Boots of Lucidity",
            role="mid",
            role_quest_complete=False,
        ).resolve()


def test_support_quest_allows_only_one_support_item():
    with pytest.raises(ValueError, match="at most one support quest item"):
        ChampionLoadout(
            champion="Nami",
            level=12,
            items=("Dream Maker", "Bloodsong"),
            boots="Ionian Boots of Lucidity",
            role="support",
            role_quest_complete=True,
        ).resolve()


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


def test_roster_preserves_authored_ranks_and_champion_options():
    roster = parse_roster(
        {
            "allies": [
                {
                    "champion": "Vayne",
                    "level": 18,
                    "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
                    "champion_options": {"condemn_wall": False},
                    "cast_order": ["R", "Q", "W", "E"],
                }
            ]
        },
        "allies",
        maximum=4,
    )

    assert roster[0].ability_ranks == {"Q": 5, "W": 5, "E": 5, "R": 3}
    assert roster[0].champion_options == {"condemn_wall": False}
    assert roster[0].cast_order == ["R", "Q", "W", "E"]


def test_roster_rejects_unknown_champion_options():
    with pytest.raises(ValueError, match="unknown option"):
        ChampionLoadout.from_request(
            {
                "champion": "Vayne",
                "level": 18,
                "champion_options": {"not_declared": True},
            },
            field="allies[0]",
        )


def test_roster_rejects_malformed_cast_order():
    # The roster path's shape check is champion-agnostic after C6: a repeated
    # slot is malformed for every champion, while *which* slots exist is
    # answered against the parsed kit in ``validate_for_champion`` (D-11).
    with pytest.raises(ValueError, match="cast_order must not repeat an ability slot"):
        ChampionLoadout.from_request(
            {
                "champion": "Vayne",
                "level": 18,
                "cast_order": ["Q", "Q", "E", "R"],
            },
            field="allies[0]",
        )


def test_level_20_requires_a_completed_top_quest():
    base = {"champion": "Galio", "level": 20}
    for extra in (
        {},
        {"role": "mid", "role_quest_complete": True},
        {"role": "top", "role_quest_complete": False},
    ):
        with pytest.raises(ValueError, match="top"):
            ChampionLoadout.from_request({**base, **extra}, field="enemies[0]")

    accepted = ChampionLoadout.from_request(
        {**base, "role": "top", "role_quest_complete": True}, field="enemies[0]"
    )
    assert accepted.level == 20


def test_level_21_is_rejected_even_with_a_completed_top_quest():
    with pytest.raises(ValueError, match="level must be between"):
        ChampionLoadout.from_request(
            {
                "champion": "Galio",
                "level": 21,
                "role": "top",
                "role_quest_complete": True,
            },
            field="enemies[0]",
        )


def test_level_20_base_health_follows_the_growth_formula():
    loadout = ChampionLoadout.from_request(
        {"champion": "Galio", "level": 20, "role": "top", "role_quest_complete": True},
        field="loadout",
    ).resolve()

    health = get_champion("Galio")["stats"]["health"]
    expected = health["flat"] + health["perLevel"] * 19 * (0.7025 + 0.0175 * 19)
    assert loadout.stats["base_health"] == pytest.approx(expected, abs=0.5)


def test_practice_dummy_preserves_exact_decimal_stat_overrides_and_has_no_abilities():
    loadout = ChampionLoadout.from_request(
        {
            "kind": "practice_dummy",
            "items": [],
            "target_stats": {"armor": 85.7, "ability_power": 956},
        },
        field="enemies[0]",
    ).resolve()

    assert loadout.is_practice_dummy
    assert loadout.stats["armor"] == 85.7
    assert loadout.stats["ability_power"] == 956.0
    assert loadout.champion_data["abilities"] == {
        slot: [] for slot in ("P", "Q", "W", "E", "R")
    }
    assert loadout.public_summary()["kind"] == "practice_dummy"


def test_practice_dummy_keeps_item_stats_when_a_field_has_no_override():
    loadout = ChampionLoadout.from_request(
        {
            "kind": "practice_dummy",
            "items": ["Rabadon's Deathcap"],
            "target_stats": {"armor": 85.7},
        },
        field="enemies[0]",
    ).resolve()

    assert loadout.stats["armor"] == 85.7
    assert loadout.stats["ability_power"] > 0


def test_practice_dummy_is_passive_in_the_coupled_timeline():
    payload = calculate_payload(
        {
            "champion": "Ziggs",
            "level": 12,
            "items": [],
            "enemies": [
                {
                    "kind": "practice_dummy",
                    "items": [],
                    "target_stats": {"armor": 85.7, "ability_power": 956},
                }
            ],
        }
    )

    target = payload["targets"][0]["target"]
    assert target["stats"]["armor"] == 85.7
    assert target["stats"]["ability_power"] == 956.0
    assert all(
        not str(event.get("attacker", "")).startswith("enemy:")
        for event in payload["combat"]["events"]
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("target_stats", {"unknown": 1}, "unknown stat"),
        ("target_stats", {"armor": True}, "must be a number"),
        ("target_stats", {"ability_power": 100001}, "must be between"),
        ("ability_ranks", {"Q": 1}, "no abilities"),
    ],
)
def test_practice_dummy_rejects_unsupported_or_invalid_controls(field, value, message):
    with pytest.raises(ValueError, match=message):
        ChampionLoadout.from_request(
            {"kind": "practice_dummy", field: value}, field="enemies[0]"
        )


def test_practice_dummy_is_restricted_to_the_enemy_roster():
    with pytest.raises(ValueError, match="only available as an enemy"):
        parse_roster({"allies": [{"kind": "practice_dummy"}]}, "allies", maximum=4)
