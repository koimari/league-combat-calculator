"""Regression coverage for coupled participant combat receipts."""

from src.calculator.data_fetcher import get_champion
from src.calculator.pipeline import FightParams, run_fight
from src.app import app


def _timed_params() -> FightParams:
    return FightParams.from_request(
        {
            "fight_mode": "time_based",
            "fight_duration": 10,
            "include_auto_attacks": True,
            "auto_attack_uptime": 0.3,
            "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
        }
    )


def test_aatrox_self_healing_is_post_mitigation_and_ordered():
    result = run_fight(get_champion("Aatrox"), 18, [], _timed_params())

    assert result["self_healing"] > 0
    assert result["self_healing_events"]
    assert any(
        event["source"] == "Deathbringer Stance"
        for event in result["self_healing_events"]
    )
    assert all(
        event["time"] >= 0 and event["amount"] > 0
        for event in result["self_healing_events"]
    )


def test_ambessa_self_healing_uses_public_execution_formula():
    result = run_fight(get_champion("Ambessa"), 18, [], _timed_params())

    assert result["self_healing"] > 0
    assert all(
        event["source"] == "Public Execution"
        for event in result["self_healing_events"]
    )


def test_fight_result_promotes_the_same_ordered_damage_ledger_used_by_shields():
    result = run_fight(get_champion("Aatrox"), 18, [], _timed_params())

    assert result["damage_events"]
    assert all(
        {"source_key", "damage_type", "damage", "time"}.issubset(event)
        for event in result["damage_events"]
    )


def test_api_includes_enemy_output_and_main_effective_health():
    app.config["TESTING"] = True
    response = app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Aatrox",
            "level": 18,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 10,
            "include_auto_attacks": True,
            "auto_attack_uptime": 0.3,
            "enemies": [{"champion": "Ambessa", "level": 18, "items": []}],
        },
    )
    assert response.status_code == 200
    combat = response.get_json()["combat"]
    assert {row["champion"] for row in combat["breakdown"]} == {"Aatrox", "Ambessa"}
    main = next(row for row in combat["participants"] if row["participant_id"] == "main")
    assert main["survival"]["effective_health"] >= main["survival"]["max_health"]


def test_api_includes_sourced_lulu_ally_shield_in_main_ehp():
    app.config["TESTING"] = True
    response = app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Aatrox",
            "level": 18,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 10,
            "include_auto_attacks": True,
            "auto_attack_uptime": 0.3,
            "enemies": [{"champion": "Ambessa", "level": 18, "items": []}],
            "allies": [
                {"champion": "Lulu", "level": 18, "items": [], "role": "support"}
            ],
        },
    )
    assert response.status_code == 200
    combat = response.get_json()["combat"]
    assert any(
        event["source"].startswith("Help, Pix!")
        for event in combat["support_events"]
    )
    main = next(row for row in combat["participants"] if row["participant_id"] == "main")
    assert main["survival"]["support_shield_received"] > 0


def test_coupled_timeline_stops_output_after_main_champion_is_defeated():
    app.config["TESTING"] = True
    response = app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Aatrox",
            "level": 1,
            "items": [],
            "fight_mode": "one_rotation",
            "enemies": [{"champion": "Ambessa", "level": 18, "items": []}],
        },
    )
    assert response.status_code == 200
    combat = response.get_json()["combat"]
    main = next(row for row in combat["participants"] if row["participant_id"] == "main")
    assert main["survival"]["survived_window"] is False
    assert main["survival"]["death_time"] is not None
    # The enemy's later event stream is not counted as if Aatrox remained
    # alive for the whole rotation.
    assert next(row for row in combat["breakdown"] if row["participant_id"] == "main")["total_damage"] <= 138.5
