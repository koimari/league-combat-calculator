"""Route-level contracts for shared fight request parsing."""

from dataclasses import replace

import pytest

import src.app as app_module


def test_calculate_and_optimize_share_fight_request_semantics(monkeypatch):
    captured = {}
    champion_data = {"name": "Ahri"}

    monkeypatch.setattr(app_module, "get_champion", lambda _name: champion_data)

    def fake_run_fight(data, level, items, params):
        captured["calculate"] = params
        return {
            "champion_stats": {},
            "breakdown": {},
            "total_damage": 0.0,
            "effective_mr": params.target_magic_resistance,
            "effective_armor": params.target_armor,
            "notes": [],
        }

    def fake_optimize_build(*, fight_params, **_kwargs):
        captured["optimize"] = fight_params
        return {"items": [], "total_damage": 0.0}

    monkeypatch.setattr(app_module, "run_fight", fake_run_fight)
    monkeypatch.setattr(app_module, "optimize_build", fake_optimize_build)

    payload = {
        "champion": "Ahri",
        "level": 18,
        "fight_mode": "auto_only",
        "fight_duration": 12,
        "include_auto_attacks": False,
        "auto_attack_uptime": 0.7,
        "auto_attacks_only": True,
        "target_health": 2400,
        "target_bonus_health": 600,
        "target_armor": 80,
        "target_mr": 70,
    }

    client = app_module.app.test_client()
    calculate_response = client.post("/api/calculate", json=payload)
    optimize_response = client.post("/api/optimize", json=payload)

    assert calculate_response.status_code == 200
    assert optimize_response.status_code == 200
    assert captured["calculate"].auto_attack_uptime == 0.7
    assert captured["calculate"] == replace(captured["optimize"], deterministic=False)


def test_config_exposes_all_request_defaults():
    response = app_module.app.test_client().get("/api/config")

    assert response.status_code == 200
    data = response.get_json()
    assert data["default_target"] == {
        "health": 1000.0,
        "bonus_health": 0.0,
        "armor": 100.0,
        "mr": 100.0,
    }
    assert data["fight_defaults"] == {
        "mode": "one_rotation",
        "duration_seconds": 8.0,
        "auto_attack_uptime": 0.8,
        "one_rotation_duration_seconds": 5.0,
    }


@pytest.mark.parametrize("slot_count", [1, 2, 3, 4, 5, 6])
def test_optimize_accepts_slot_counts_one_through_six(monkeypatch, slot_count):
    monkeypatch.setattr(app_module, "get_champion", lambda _name: {"name": "Ahri"})
    monkeypatch.setattr(
        app_module,
        "optimize_build",
        lambda **_kwargs: {"items": [], "total_damage": 0.0},
    )

    payload = {"champion": "Ahri", "level": 18, "max_legendary_slots": slot_count}
    response = app_module.app.test_client().post("/api/optimize", json=payload)

    assert response.status_code == 200


@pytest.mark.parametrize("slot_count", [0, 7, -1])
def test_optimize_rejects_slot_counts_outside_one_through_six(monkeypatch, slot_count):
    monkeypatch.setattr(app_module, "get_champion", lambda _name: {"name": "Ahri"})

    payload = {"champion": "Ahri", "level": 18, "max_legendary_slots": slot_count}
    response = app_module.app.test_client().post("/api/optimize", json=payload)

    assert response.status_code == 400
    assert "max_legendary_slots" in response.get_json()["error"]


def test_optimize_rejects_more_locked_items_than_slots(monkeypatch):
    monkeypatch.setattr(app_module, "get_champion", lambda _name: {"name": "Ahri"})

    payload = {
        "champion": "Ahri",
        "level": 18,
        "max_legendary_slots": 2,
        "locked_items": ["Luden's Echo", "Rabadon's Deathcap", "Shadowflame"],
    }
    response = app_module.app.test_client().post("/api/optimize", json=payload)

    assert response.status_code == 400
    assert "locked" in response.get_json()["error"].lower()


@pytest.mark.parametrize(
    "invalid_values",
    [
        {"cast_order": ["Q", "Q", "E", "R"]},
        {"ability_ranks": {"Q": 6}},
        {"ability_ranks": {"R": 4}},
    ],
)
def test_calculate_and_optimize_reject_the_same_invalid_fight_params(invalid_values):
    payload = {"champion": "Ahri", "level": 18, **invalid_values}
    client = app_module.app.test_client()

    calculate = client.post("/api/calculate", json=payload)
    optimize = client.post("/api/optimize", json=payload)

    assert calculate.status_code == 400
    assert optimize.status_code == 400
    assert calculate.get_json() == optimize.get_json()
