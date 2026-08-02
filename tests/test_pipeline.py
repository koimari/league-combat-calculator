"""Tests for the shared stats -> abilities -> fight pipeline."""

from dataclasses import replace

import pytest

from src.calculator.data_fetcher import get_champion
from src.calculator.pipeline import FightParams, run_fight


@pytest.mark.parametrize(
    ("request_data", "expected_duration", "expected_uptime", "one_rotation"),
    [
        ({}, 5.0, 0.0, True),
        (
            {
                "fight_mode": "timed",
                "fight_duration": 10,
                "include_auto_attacks": True,
                "auto_attack_uptime": 0.7,
            },
            10.0,
            0.7,
            False,
        ),
        (
            {
                "fight_mode": "timed",
                "fight_duration": 10,
                "include_auto_attacks": False,
                "auto_attack_uptime": 0.7,
            },
            10.0,
            0.0,
            False,
        ),
        (
            {
                "fight_mode": "auto_only",
                "fight_duration": 10,
                "include_auto_attacks": False,
                "auto_attack_uptime": 0.7,
                "auto_attacks_only": True,
            },
            10.0,
            0.7,
            False,
        ),
    ],
)
def test_fight_params_resolve_modes(
    request_data, expected_duration, expected_uptime, one_rotation
):
    params = FightParams.from_request(request_data)

    assert params.fight_duration_seconds == expected_duration
    assert params.auto_attack_uptime == expected_uptime
    assert params.one_rotation is one_rotation


def test_request_defaults_have_one_canonical_home():
    params = FightParams.from_request({})

    assert params.target_health == 1000.0
    assert params.target_bonus_health == 0.0
    assert params.target_armor == 100.0
    assert params.target_magic_resistance == 100.0
    assert params.deterministic is False


@pytest.mark.parametrize(
    ("request_data", "message"),
    [
        ({"cast_order": ["Q", "Q", "E", "R"]}, "Cast order must"),
        ({"ability_ranks": {"Q": 6}}, "Q rank must be 0-5"),
        ({"ability_ranks": {"R": 4}}, "R rank must be 0-3"),
        (
            {"item_options": {"Dark Seal": {"glory_stacks": 11}}},
            "glory_stacks must be between 0 and 10",
        ),
        (
            {"item_options": {"Mejai's Soulstealer": {"glory_stacks": 1.5}}},
            "glory_stacks must be an integer",
        ),
        ({"role": "river"}, "role must be"),
        ({"role_quest_complete": "yes"}, "role_quest_complete must be true or false"),
        (
            {"role_quest_complete": True},
            "role is required when role_quest_complete is true",
        ),
    ],
)
def test_fight_params_reject_invalid_shared_inputs(request_data, message):
    with pytest.raises(ValueError, match=message):
        FightParams.from_request(request_data)


def test_fight_params_parse_role_quest_state():
    params = FightParams.from_request({"role": "Mid", "role_quest_complete": True})

    assert params.role == "mid"
    assert params.role_quest_complete is True


@pytest.mark.parametrize(
    ("level", "ranks", "message"),
    [
        (1, {"Q": 2, "W": 0, "E": 0, "R": 0}, "Q rank 2 requires"),
        (5, {"Q": 1, "W": 1, "E": 1, "R": 1}, "R rank 1 requires"),
        (
            6,
            {"Q": 3, "W": 2, "E": 1, "R": 1},
            "more skill points",
        ),
    ],
)
def test_rank_allocation_must_be_possible_at_champion_level(level, ranks, message):
    params = FightParams.from_request({"ability_ranks": ranks})

    with pytest.raises(ValueError, match=message):
        params.validate_for_champion("Ahri", level)


def test_manual_ranks_fail_closed_for_nonstandard_rank_kit():
    params = FightParams.from_request(
        {"ability_ranks": {"Q": 1, "W": 1, "E": 1, "R": 0}}
    )

    with pytest.raises(ValueError, match="level-derived ranks"):
        params.validate_for_champion("Jayce", 3)


def test_run_fight_builds_fresh_stats_and_abilities(ahri_data):
    params = FightParams.from_request({}, deterministic=True)

    result = run_fight(ahri_data, 18, [], params)

    assert result["total_damage"] > 0
    assert "Q" in result["breakdown"]
    assert result["champion_stats"]["ability_power"] == 0.0


def test_run_fight_includes_auto_vs_ability_split(ahri_data):
    # Consumers (the web layer) read the attribution off the result
    # instead of importing the fight engine's split function directly.
    params = FightParams.from_request({}, deterministic=True)

    result = run_fight(ahri_data, 18, [], params)

    assert result["auto_attack_damage"] >= 0.0
    assert result["ability_damage"] > 0.0
    # No amp/informational rows in an itemless fight: split sums to total.
    assert result["auto_attack_damage"] + result["ability_damage"] == pytest.approx(
        result["total_damage"]
    )


def test_run_fight_includes_damage_by_type_split(ahri_data):
    # The web layer reads the physical/magic/true attribution off the
    # result. Ahri Q is mixed (magic outgoing + true return), so an
    # itemless fight must attribute both buckets exactly.
    params = FightParams.from_request({}, deterministic=True)

    result = run_fight(ahri_data, 18, [], params)

    split = result["damage_by_type"]
    assert set(split) == {"physical", "magic", "true"}
    assert split["magic"] > 0.0
    assert split["true"] > 0.0
    assert sum(split.values()) == pytest.approx(result["total_damage"])


def test_starting_magic_shield_splits_tdd_from_health_damage(ahri_data):
    params = FightParams.from_request({}, deterministic=True)
    params = replace(params, target_magic_shield=100.0)

    result = run_fight(ahri_data, 18, [], params)

    assert result["total_damage"] > result["health_damage"]
    assert result["magic_shield_absorbed"] == pytest.approx(100.0)
    assert result["shield_absorbed"] == pytest.approx(100.0)


def test_timed_rotation_omits_casts_after_mana_is_exhausted():
    params = FightParams.from_request(
        {"fight_mode": "timed", "fight_duration": 10}, deterministic=True
    )

    result = run_fight(get_champion("Karthus"), 18, [], params)

    assert result["breakdown"]["Q"]["casts"] == 5
    assert result["breakdown"]["E"]["casts"] == 9
    assert any("insufficient resource" in note for note in result["notes"])
    timeline = result["cast_timeline"]
    assert [event["time"] for event in timeline] == sorted(
        event["time"] for event in timeline
    )
    assert result["resource_spent"] > 0
    assert result["resource_remaining"] >= 0
    assert all(event["resource_cost"] >= 0 for event in timeline)


def test_energy_regenerates_between_timed_casts():
    params = FightParams.from_request(
        {"fight_mode": "timed", "fight_duration": 10}, deterministic=True
    )

    result = run_fight(get_champion("Akali"), 18, [], params)

    assert result["breakdown"]["Q"]["casts"] == 5
    assert any("Q x1" in note for note in result["notes"])
    shroud = next(event for event in result["cast_timeline"] if event["slot"] == "W")
    assert shroud["resource_restored"] == 100
    assert shroud["resource_after"] > 200


def test_ambessa_passive_restores_energy_between_ability_casts():
    params = FightParams.from_request(
        {"fight_mode": "timed", "fight_duration": 10}, deterministic=True
    )

    result = run_fight(get_champion("Ambessa"), 18, [], params)

    assert result["breakdown"]["Q"]["casts"] == 2
    assert result["breakdown"]["Q2"]["casts"] == 2
    opening = result["cast_timeline"][:4]
    assert all(event["resource_restored"] == 70 for event in opening)
    assert result["resource_remaining"] >= 0
