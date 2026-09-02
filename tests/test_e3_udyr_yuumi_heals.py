"""E3 follow-up: Udyr W + Yuumi R heal streams (sourced from Total/Per-Tick)."""

import pytest

from src import app as app_module


def _fight(champion: str, ranks: dict, role: str) -> dict:
    payload = {
        "champion": champion,
        "level": 18,
        "items": [],
        "role": role,
        "fight_mode": "time_based",
        "fight_duration": 10,
        "include_auto_attacks": True,
        "enemies": [
            {
                "champion": "Ahri",
                "level": 18,
                "items": [],
                "role": "mid",
                "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
            }
        ],
    }
    if ranks:
        payload["ability_ranks"] = ranks
    resp = app_module.app.test_client().post("/api/calculate", json=payload)
    assert resp.status_code == 200
    return resp.get_json()["combat"]


def test_udyr_w_iron_mantle_heals_sixteen_ticks():
    combat = _fight("Udyr", {}, "top")
    heals = [
        e
        for e in combat.get("healing_events", [])
        if e.get("attacker") == "main" and e["source"] == "Iron Mantle"
    ]
    assert heals, "Iron Mantle heal missing"
    assert len(heals) >= 16
    # sourced: Heal per Tick x16 == Total Healing, resolved against the fight's stats
    assert all(abs(e["amount"] - heals[0]["amount"]) < 0.01 for e in heals)
    assert heals[0]["amount"] > 0


def test_yuumi_r_final_chapter_heals_five_waves():
    combat = _fight("Yuumi", {"Q": 1, "W": 1, "E": 1, "R": 3}, "support")
    heals = [
        e
        for e in combat.get("healing_events", [])
        if e.get("attacker") == "main" and e["source"] == "Final Chapter"
    ]
    assert heals, "Final Chapter heal missing"
    assert len(heals) >= 5
    assert sum(e["amount"] for e in heals) == pytest.approx(350.0, rel=0.01)
