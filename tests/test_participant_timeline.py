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


def test_coupled_timeline_reprices_current_health_damage_for_each_attacker():
    """A second Mundo Q must see the damage already dealt by the first one."""
    app.config["TESTING"] = True
    response = app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Dr. Mundo",
            "level": 6,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 3.5,
            "include_auto_attacks": False,
            "ability_ranks": {"Q": 3, "W": 1, "E": 1, "R": 1},
            "enemies": [{"champion": "Aphelios", "level": 6, "items": []}],
            "allies": [
                {
                    "champion": "Dr. Mundo",
                    "level": 6,
                    "items": [],
                    "ally_effects_enabled": False,
                    "ability_ranks": {"Q": 3, "W": 1, "E": 1, "R": 1},
                }
            ],
        },
    )
    assert response.status_code == 200
    events = [
        event
        for event in response.get_json()["combat"]["events"]
        if event["target"] == "enemy:Aphelios" and event["source"] == "Q"
    ]
    main_q = next(event for event in events if event["attacker"] == "main")
    ally_q = next(event for event in events if event["attacker"] == "ally:Dr. Mundo")
    assert main_q["damage"] > ally_q["damage"]
    assert main_q["pair_damage"] == ally_q["pair_damage"]
    assert ally_q["damage"] < ally_q["pair_damage"]


def test_coupled_timeline_caps_overkill_and_skips_post_death_events():
    app.config["TESTING"] = True
    response = app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Ziggs",
            "level": 18,
            "items": [
                "Luden's Echo",
                "Rabadon's Deathcap",
                "Shadowflame",
                "Void Staff",
                "Stormsurge",
            ],
            "fight_mode": "time_based",
            "fight_duration": 10,
            "include_auto_attacks": False,
            "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
            "enemies": [{"champion": "Aphelios", "level": 1, "items": []}],
        },
    )
    assert response.status_code == 200
    combat = response.get_json()["combat"]
    enemy = next(row for row in combat["participants"] if row["team"] == "enemy")
    main_row = next(row for row in combat["breakdown"] if row["participant_id"] == "main")
    assert enemy["survival"]["survived_window"] is False
    assert enemy["survival"]["overkill"] > 0
    assert main_row["total_damage"] <= enemy["survival"]["max_health"]
    assert any(event.get("skipped_reason") == "target_dead" for event in combat["events"])


def _bis_request(subject_team: str) -> dict:
    return {
        "champion": "Aatrox",
        "level": 18,
        "items": ["Infinity Edge", "Bloodthirster"],
        "boots": "Plated Steelcaps",
        "role": "top",
        "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
        "fight_mode": "time_based",
        "fight_duration": 10,
        "include_auto_attacks": True,
        "auto_attack_uptime": 0.3,
        "subject_team": subject_team,
        "subject_index": 0,
        "slot_index": 0,
        "slot_kind": "item",
        "enemies": [
            {
                "champion": "Ambessa",
                "level": 18,
                "items": [],
                "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
            }
        ],
        "allies": [
            {
                "champion": "Lulu",
                "level": 18,
                "items": [],
                "role": "support",
                "ally_effects_enabled": True,
                "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
            }
        ],
    }


def test_bis_endpoint_scores_main_from_damage_and_effective_health():
    app.config["TESTING"] = True
    response = app.test_client().post("/api/bis", json=_bis_request("main"))
    assert response.status_code == 200
    body = response.get_json()
    assert body["candidate_count"] > 0
    assert body["candidates"]
    top = body["candidates"][0]
    assert top["metric"] == "main TTD + effective health"
    assert top["components"]["effective_health"] > 0


def test_bis_endpoint_keeps_ally_and_enemy_in_the_same_timeline():
    app.config["TESTING"] = True
    client = app.test_client()
    ally = client.post("/api/bis", json=_bis_request("ally"))
    enemy = client.post("/api/bis", json=_bis_request("enemy"))
    assert ally.status_code == enemy.status_code == 200
    ally_top = ally.get_json()["candidates"][0]
    enemy_top = enemy.get_json()["candidates"][0]
    assert "main_team_damage_before_death" in ally_top["components"]
    assert "effective_health" in ally_top["components"]
    assert enemy_top["metric"] == "enemy TTD + survival pool"
    assert enemy_top["components"]["effective_health"] > 0


def test_bis_withholds_partial_event_order_instead_of_labeling_it_certified():
    app.config["TESTING"] = True
    payload = {
        "champion": "Dr. Mundo",
        "level": 6,
        "items": [],
        "fight_mode": "time_based",
        "fight_duration": 3.5,
        "include_auto_attacks": False,
        "ability_ranks": {"Q": 3, "W": 1, "E": 1, "R": 1},
        "subject_team": "main",
        "subject_index": 0,
        "slot_index": 0,
        "slot_kind": "item",
        "enemies": [{"champion": "Aphelios", "level": 6, "items": []}],
    }
    response = app.test_client().post("/api/bis", json=payload)
    assert response.status_code == 200
    body = response.get_json()
    assert body["certified_candidate_count"] == 0
    assert body["candidates"] == []
    assert body["partial_candidates"]
    assert body["coverage"]["certification"] == "bis_withheld_partial_event_order"


def test_explicitly_disabled_ally_effects_are_not_injected_into_ehp():
    app.config["TESTING"] = True
    payload = _bis_request("main")
    payload["allies"][0]["ally_effects_enabled"] = False
    response = app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200
    assert not any(
        event["attacker"] == "ally:Lulu"
        for event in response.get_json()["combat"]["support_events"]
    )
