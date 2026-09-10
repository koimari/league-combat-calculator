"""Participant attack controls survive parsing and change the combat walk."""

import pytest

from src.calculator.calculate import calculate_payload
from src.calculator.scenario import ChampionLoadout


@pytest.mark.parametrize(
    "field,value",
    [
        ("include_auto_attacks", 1),
        ("auto_attack_uptime_mode", "manual"),
        ("auto_attack_uptime", 1.1),
        ("auto_attack_uptime", True),
    ],
)
def test_roster_rejects_invalid_attack_controls(field, value):
    with pytest.raises(ValueError):
        ChampionLoadout.from_request(
            {"champion": "Ashe", field: value}, field="enemies[0]"
        )


def test_each_actor_can_disable_its_own_attacks():
    zero = {"Q": 0, "W": 0, "E": 0, "R": 0}

    def actor(champion, enabled):
        return {
            "champion": champion,
            "level": 1,
            "items": [],
            "ability_ranks": zero,
            "include_auto_attacks": enabled,
            "auto_attack_uptime_mode": "calculated",
        }

    def run(main_enabled, ally_enabled, enemy_enabled):
        return calculate_payload(
            {
                **actor("Ashe", main_enabled),
                "fight_mode": "time_based",
                "fight_duration": 2,
                "allies": [actor("Ashe", ally_enabled)],
                "enemies": [actor("Ashe", enemy_enabled)],
            }
        )["combat"]["events"]

    for enabled_id, switches in [
        ("main", (True, False, False)),
        ("ally:Ashe", (False, True, False)),
        ("enemy:Ashe", (False, False, True)),
    ]:
        events = run(*switches)
        attacks = [event for event in events if event["source"] == "auto_attacks"]
        assert attacks
        assert {event["attacker"] for event in attacks} == {enabled_id}


def test_roster_explicit_uptime_changes_only_that_actor():
    zero = {"Q": 0, "W": 0, "E": 0, "R": 0}

    def run(uptime):
        return calculate_payload(
            {
                "champion": "Ashe",
                "level": 1,
                "ability_ranks": zero,
                "include_auto_attacks": False,
                "fight_mode": "time_based",
                "fight_duration": 8,
                "enemies": [
                    {
                        "champion": "Ashe",
                        "level": 1,
                        "ability_ranks": zero,
                        "include_auto_attacks": False,
                    }
                ],
                "allies": [
                    {
                        "champion": "Ashe",
                        "level": 1,
                        "ability_ranks": zero,
                        "include_auto_attacks": True,
                        "auto_attack_uptime_mode": "explicit",
                        "auto_attack_uptime": uptime,
                    }
                ],
            }
        )["combat"]["events"]

    def attacks(uptime):
        return [event for event in run(uptime) if event["source"] == "auto_attacks"]

    assert attacks(0) == []
    assert len(attacks(1)) > len(attacks(0.25)) > 0
    assert {event["attacker"] for event in attacks(1)} == {"ally:Ashe"}
