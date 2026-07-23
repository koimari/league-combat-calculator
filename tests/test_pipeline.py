"""Tests for the shared stats -> abilities -> fight pipeline."""

import pytest

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
    ],
)
def test_fight_params_reject_invalid_shared_inputs(request_data, message):
    with pytest.raises(ValueError, match=message):
        FightParams.from_request(request_data)


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
