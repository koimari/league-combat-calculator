"""Vladimir self-healing from sourced wiki formulas (WS4 atom recompose).

Q Transfusion: flat heal per cast, rank-scaled, + AP ratio.
W Sanguine Pool: 30% of damage dealt.
R Hemoplague: flat heal per infected champion, reduced for later targets.
"""

import pytest

from src import app as app_module

_ENEMY_NAMES = ["Ahri", "Annie", "Orianna"]


def _vladimir_fight(
    *,
    level: int = 18,
    ranks: dict | None = None,
    ap_item: str | None = None,
    enemies: int = 1
) -> dict:
    payload = {
        "champion": "Vladimir",
        "level": level,
        "items": [ap_item] if ap_item else [],
        "role": "mid",
        "ability_ranks": ranks or {"Q": 5, "W": 5, "E": 5, "R": 3},
        "fight_mode": "time_based",
        "fight_duration": 10,
        "include_auto_attacks": True,
        "enemies": [
            {
                "champion": _ENEMY_NAMES[index % len(_ENEMY_NAMES)],
                "level": 18,
                "items": [],
                "role": "mid",
                "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
            }
            for index in range(enemies)
        ],
    }
    response = app_module.app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200
    return response.get_json()["combat"]


def _main_heals(combat: dict) -> list[dict]:
    return [e for e in combat.get("healing_events", []) if e.get("attacker") == "main"]


def test_vladimir_transfusion_heals_rank_scaled_flat_value():
    combat = _vladimir_fight(ranks={"Q": 1, "W": 1, "E": 1, "R": 1})
    q_heals = [e for e in _main_heals(combat) if e["source"] == "Transfusion"]
    assert q_heals, "Transfusion heal missing"
    # rank 1 flat heal = 20 (no AP with no items)
    assert all(e["amount"] == pytest.approx(20.0) for e in q_heals)


def test_vladimir_transfusion_heal_scales_with_ap():
    combat = _vladimir_fight(
        ranks={"Q": 5, "W": 1, "E": 1, "R": 1}, ap_item="Rabadon's Deathcap"
    )
    q_heals = [e for e in _main_heals(combat) if e["source"] == "Transfusion"]
    assert q_heals
    # rank 5 flat 40 + 35% AP (Deathcap gives 120 AP)
    assert q_heals[0]["amount"] > 40.0


def test_vladimir_sanguine_pool_heals_thirty_percent_of_pre_mitigation_damage():
    # The wiki says 30% of PRE-mitigation damage dealt; the engine exposes
    # pre-mitigation as event["raw_damage"]. The heal must be larger than
    # 30% of the post-mitigation damage (which would under-heal).
    combat = _vladimir_fight(ranks={"Q": 1, "W": 5, "E": 1, "R": 1})
    w_damage = [
        e
        for e in combat.get("events", [])
        if e.get("attacker") == "main" and e.get("source") == "W"
    ]
    w_heals = [e for e in _main_heals(combat) if e["source"] == "Sanguine Pool"]
    assert w_damage
    assert w_heals
    event = w_damage[0]
    assert "raw_damage" in event, "engine must expose pre-mitigation raw_damage"
    assert event["raw_damage"] > event["damage"], "raw must exceed mitigated"
    assert w_heals[0]["amount"] == pytest.approx(0.30 * event["raw_damage"], rel=0.01)
    assert w_heals[0]["amount"] > 0.30 * event["damage"]


def test_vladimir_hemoplague_heals_flat_per_champion():
    combat = _vladimir_fight(ranks={"Q": 1, "W": 1, "E": 1, "R": 3}, enemies=2)
    r_heals = [e for e in _main_heals(combat) if e["source"] == "Hemoplague"]
    assert r_heals
    # rank 3 flat heal 350 + 70% AP (no AP); reduced heal 140 for the second target
    assert max(e["amount"] for e in r_heals) == pytest.approx(350.0)
    assert min(e["amount"] for e in r_heals) == pytest.approx(140.0)


def test_vladimir_tides_of_blood_has_no_heal_in_current_patch():
    combat = _vladimir_fight(ranks={"Q": 1, "W": 1, "E": 5, "R": 1})
    e_heals = [e for e in _main_heals(combat) if e["source"] == "Tides of Blood"]
    assert not e_heals
