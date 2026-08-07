"""Endpoint parity for the shared scenario boundary (issue #138).

/ api / calculate, /api/optimize, and /api/bis must validate the same
scenario fields with the same 400/404 messages, run the same item coverage
gates, expose the same serializer key set (including the roster
``damage_events`` stream), and consult the deterministic result cache.
"""

import pytest

import src.app as app_module
from src.calculator.public_response import (
    _PUBLIC_FIELD_POLICIES,
    aggregate_public_results,
    serialize_fight_result,
)

app = app_module.app


@pytest.fixture(autouse=True)
def _isolate_app_config():
    """Keep these route tests off the shared rate-limit budget."""
    previous_testing = app.config.get("TESTING")
    previous_rate = app.config.get("RATE_LIMIT_ENABLED", True)
    app.config["TESTING"] = True
    app.config["RATE_LIMIT_ENABLED"] = False
    yield
    if previous_testing is None:
        app.config.pop("TESTING", None)
    else:
        app.config["TESTING"] = previous_testing
    app.config["RATE_LIMIT_ENABLED"] = previous_rate


def _client():
    return app.test_client()


def _ahri_payload(**overrides):
    """One mid Ahri build with an Aatrox enemy (the issue's repro shape)."""
    payload = {
        "champion": "Ahri",
        "level": 18,
        "items": [
            "Luden's Echo",
            "Rabadon's Deathcap",
            "Void Staff",
            "Zhonya's Hourglass",
            "Shadowflame",
        ],
        "boots": "Sorcerer's Shoes",
        "role": "mid",
        "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
        "target_health": 2400,
        "target_armor": 80,
        "target_mr": 70,
        "enemies": [{"champion": "Aatrox", "level": 18, "items": []}],
    }
    payload.update(overrides)
    return payload


def _bis_fields(payload):
    """Add the BIS-only request fields to a calculate-shaped payload."""
    return {
        **payload,
        "subject_team": "main",
        "subject_index": 0,
        "slot_index": 0,
        "slot_kind": "item",
    }


def _optimize_payload(payload):
    """Translate a calculate-shaped payload into the optimizer's shape.

    The optimizer owns its locked-build fields; the shared scenario fields
    (champion, level, role, ranks, options, roster, target stats) pass
    through so the shared boundary validates them identically.
    """
    return {
        "champion": payload["champion"],
        "level": payload["level"],
        "role": payload["role"],
        "ability_ranks": payload["ability_ranks"],
        "champion_options": payload.get("champion_options"),
        "enemies": payload.get("enemies", []),
        "allies": payload.get("allies", []),
        "target_health": payload.get("target_health"),
        "target_armor": payload.get("target_armor"),
        "target_mr": payload.get("target_mr"),
    }


# ---------------------------------------------------------------------------
# damage_events parity (the issue's direct reproduction)
# ---------------------------------------------------------------------------


def test_roster_calculate_preserves_damage_events():
    """A roster response must carry ``damage_events`` like the single-target
    response: the flattened per-target stream, each event stamped with its
    ``target_index`` and matching the per-target table 1:1."""
    client = _client()
    single = client.post("/api/calculate", json=_ahri_payload(enemies=[]))
    assert single.status_code == 200
    single_body = single.get_json()
    assert "damage_events" in single_body

    roster = client.post("/api/calculate", json=_ahri_payload())
    assert roster.status_code == 200
    roster_body = roster.get_json()
    assert "damage_events" in roster_body

    per_target = [
        (target_index, event)
        for target_index, target in enumerate(roster_body["targets"])
        for event in target["result"]["damage_events"]
    ]
    flattened = roster_body["damage_events"]
    assert len(flattened) == len(per_target)
    for (target_index, source), stamped in zip(per_target, flattened):
        assert stamped["target_index"] == target_index
        assert {
            key: value for key, value in stamped.items() if key != "target_index"
        } == source


def test_single_target_keys_are_subset_of_roster_keys():
    """The aggregate serializer emits every single-target key; the roster
    response only adds the documented roster-only keys."""
    client = _client()
    single = client.post("/api/calculate", json=_ahri_payload(enemies=[]))
    roster = client.post("/api/calculate", json=_ahri_payload())
    assert single.status_code == 200 and roster.status_code == 200

    single_keys = set(single.get_json())
    roster_keys = set(roster.get_json())
    assert single_keys - roster_keys == set()
    assert roster_keys - single_keys == {"allies", "scenario", "targets"}


def test_serializer_schema_parity():
    """The schema table and both serializers agree on the public key set, so
    a key added to one serializer cannot silently vanish from the other."""
    result = {
        "champion_stats": {},
        "total_damage": 100.0,
        "health_damage": 100.0,
        "shield_absorbed": 0.0,
        "magic_shield_absorbed": 0.0,
        "physical_shield_absorbed": 0.0,
        "general_shield_absorbed": 0.0,
        "threshold_shield_absorbed": 0.0,
        "threshold_health_triggered": False,
        "threshold_health_bonus_gained": 0.0,
        "target_healing_received": 0.0,
        "target_ending_health": 0.0,
        "target_effective_max_health": 2000.0,
        "ability_damage": 100.0,
        "auto_attack_damage": 0.0,
        "damage_by_type": {"magic": 100.0},
        "breakdown": {},
        "effective_mr": 30.0,
        "effective_armor": 40.0,
        "notes": [],
        "cast_timeline": [],
        "rotation": {},
        "resource_spent": 0.0,
        "resource_remaining": 100.0,
        "timeline_coverage": {
            "complete": True,
            "certification": "event_order_certified",
            "exact_sources": [],
            "coarse_sources": [],
        },
        "auto_attack_policy": {},
        "auto_attack_schedule": {},
        "damage_events": [],
        "self_healing": 0.0,
        "self_healing_events": [],
    }
    single = serialize_fight_result(result)
    assert set(single) == set(_PUBLIC_FIELD_POLICIES)
    aggregated = aggregate_public_results([single, serialize_fight_result(result)])
    assert set(aggregated) == set(_PUBLIC_FIELD_POLICIES)
    assert aggregated["damage_events"] == []

    # Non-empty events flatten with a 1:1 target_index stamp.
    result["damage_events"] = [
        {
            "time": 1.0,
            "source_key": "Q",
            "damage_type": "magic",
            "damage": 5.0,
            "phase": "cast",
        }
    ]
    single = serialize_fight_result(result)
    aggregated = aggregate_public_results([single, single])
    assert [event["target_index"] for event in aggregated["damage_events"]] == [0, 1]
    assert [event["damage"] for event in aggregated["damage_events"]] == [5.0, 5.0]


# ---------------------------------------------------------------------------
# Shared coverage boundary
# ---------------------------------------------------------------------------


def test_calculate_optimize_bis_share_coverage_boundary_for_enemies():
    """An enemy carrying a calc-blocked item is a 400 with the identical
    message on every endpoint."""
    payload = _ahri_payload(
        enemies=[{"champion": "Aatrox", "level": 18, "items": ["Goredrinker"]}]
    )
    client = _client()
    responses = [
        client.post("/api/calculate", json=payload),
        client.post("/api/optimize", json=_optimize_payload(payload)),
        client.post("/api/bis", json=_bis_fields(payload)),
    ]
    for response in responses:
        assert response.status_code == 400
    messages = {response.get_json()["error"] for response in responses}
    assert len(messages) == 1
    assert "Enemy Aatrox item Goredrinker cannot be used in a calculation yet" in (
        messages.pop()
    )


def test_calculate_and_bis_share_coverage_boundary_for_main_build():
    """A main build carrying a calc-blocked item is rejected by calculate and
    BIS with the identical message; optimize rejects its locked equivalent
    through the optimizer's own gate."""
    payload = _ahri_payload(
        items=["Goredrinker"],
        enemies=[{"champion": "Aatrox", "level": 18, "items": []}],
    )
    client = _client()
    calculate = client.post("/api/calculate", json=payload)
    bis = client.post("/api/bis", json=_bis_fields(payload))
    assert calculate.status_code == 400
    assert bis.status_code == 400
    assert calculate.get_json() == bis.get_json()
    assert "Attacker item Goredrinker cannot be used in a calculation yet" in (
        calculate.get_json()["error"]
    )

    optimize_payload = _optimize_payload(payload)
    optimize_payload["locked_items"] = ["Goredrinker"]
    optimize = client.post("/api/optimize", json=optimize_payload)
    assert optimize.status_code == 400


def test_calculate_optimize_bis_share_coverage_boundary_for_allies():
    """An ally carrying a calc-blocked item is a 400 with the identical
    message on every endpoint (optimize previously failed deep in the
    optimizer instead)."""
    payload = _ahri_payload(
        allies=[
            {
                "champion": "Soraka",
                "level": 18,
                "items": ["Goredrinker"],
                "role": "support",
            }
        ]
    )
    client = _client()
    responses = [
        client.post("/api/calculate", json=payload),
        client.post("/api/optimize", json=_optimize_payload(payload)),
        client.post("/api/bis", json=_bis_fields(payload)),
    ]
    for response in responses:
        assert response.status_code == 400
    messages = {response.get_json()["error"] for response in responses}
    assert len(messages) == 1
    assert "Ally Soraka item Goredrinker cannot be used in a calculation yet" in (
        messages.pop()
    )


# ---------------------------------------------------------------------------
# Shared error classes and messages
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "endpoint",
    ["/api/calculate", "/api/optimize", "/api/bis"],
)
def test_unknown_champion_404s_identically(endpoint):
    payload = _ahri_payload(champion="Definitely Not A Champion")
    if endpoint == "/api/optimize":
        payload = _optimize_payload(payload)
    elif endpoint == "/api/bis":
        payload = _bis_fields(payload)
    response = _client().post(endpoint, json=payload)
    assert response.status_code == 404
    assert response.get_json() == {
        "error": "Champion 'Definitely Not A Champion' not found"
    }


@pytest.mark.parametrize(
    "endpoint",
    ["/api/calculate", "/api/optimize", "/api/bis"],
)
def test_unknown_item_404s_identically(endpoint):
    payload = _ahri_payload(items=["Definitely Not An Item"])
    if endpoint == "/api/optimize":
        payload = _optimize_payload(payload)
        payload["locked_items"] = ["Definitely Not An Item"]
    elif endpoint == "/api/bis":
        payload = _bis_fields(payload)
    response = _client().post(endpoint, json=payload)
    assert response.status_code == 404
    assert response.get_json() == {"error": "Item 'Definitely Not An Item' not found"}


@pytest.mark.parametrize(
    "endpoint",
    ["/api/calculate", "/api/optimize", "/api/bis"],
)
def test_bad_level_400s_identically(endpoint):
    payload = _ahri_payload(level=0)
    if endpoint == "/api/optimize":
        payload = _optimize_payload(payload)
    elif endpoint == "/api/bis":
        payload = _bis_fields(payload)
    response = _client().post(endpoint, json=payload)
    assert response.status_code == 400
    assert response.get_json()["error"] == "level must be between 1 and 20"


@pytest.mark.parametrize(
    "endpoint",
    ["/api/calculate", "/api/optimize", "/api/bis"],
)
def test_unknown_champion_option_400s_identically(endpoint):
    payload = _ahri_payload(champion_options={"not_declared": True})
    if endpoint == "/api/optimize":
        payload = _optimize_payload(payload)
    elif endpoint == "/api/bis":
        payload = _bis_fields(payload)
    response = _client().post(endpoint, json=payload)
    assert response.status_code == 400
    assert (
        response.get_json()["error"]
        == "champion_options contains unknown option not_declared"
    )


@pytest.mark.parametrize(
    "endpoint",
    ["/api/calculate", "/api/optimize", "/api/bis"],
)
def test_unknown_enemy_champion_404s_identically(endpoint):
    payload = _ahri_payload(
        enemies=[{"champion": "Definitely Not A Champion", "level": 18, "items": []}]
    )
    if endpoint == "/api/optimize":
        payload = _optimize_payload(payload)
    elif endpoint == "/api/bis":
        payload = _bis_fields(payload)
    response = _client().post(endpoint, json=payload)
    assert response.status_code == 404
    # get_champion raises KeyError("Champion 'X' not found in data"); the
    # roster resolution boundary wraps exc.args[0] the same way as before.
    assert response.get_json() == {
        "error": "Scenario data 'Champion 'Definitely Not A Champion' not found "
        "in data' not found"
    }


# ---------------------------------------------------------------------------
# Optimize result caching (deterministic)
# ---------------------------------------------------------------------------


def test_optimize_consults_and_populates_cache(monkeypatch):
    """Optimize now consults and populates the deterministic result cache
    like calculate and BIS; a repeated identical request short-circuits."""
    calls = {"get": [], "set": []}

    def fake_get(key):
        calls["get"].append(key)
        return None

    def fake_set(key, payload):
        calls["set"].append((key, payload))

    monkeypatch.setattr(app_module, "_result_cache_enabled", lambda: True)
    monkeypatch.setattr(app_module, "cache_get", fake_get)
    monkeypatch.setattr(app_module, "cache_set", fake_set)

    payload = {
        "champion": "Ahri",
        "level": 11,
        "role": "mid",
        "locked_items": ["Luden's Echo"],
        "target_health": 2000,
    }
    client = _client()
    first = client.post("/api/optimize", json=payload)
    assert first.status_code == 200
    assert len(calls["get"]) == 1
    assert len(calls["set"]) == 1
    key, cached_body = calls["set"][0]
    assert key == calls["get"][0]
    assert len(key) == 64  # sha256 hex digest over the "optimize" namespace + body
    assert cached_body == first.get_json()

    # Second identical request: cache hit short-circuits before the optimizer.
    monkeypatch.setattr(
        app_module,
        "cache_get",
        lambda key: (calls["get"].append(key) or first.get_json()),
    )
    second = client.post("/api/optimize", json=payload)
    assert second.status_code == 200
    assert second.get_json() == first.get_json()
    assert len(calls["get"]) == 2
    assert len(calls["set"]) == 1  # no second write


# ---------------------------------------------------------------------------
# Pinned parity symptom (issue #138 §4b, pre-existing optimizer behavior)
# ---------------------------------------------------------------------------


def test_optimize_ally_only_failure_is_pinned():
    """Optimize with allies but no enemy currently fails with the coupled
    optimizer's ``no_complete_event_order`` receipt, while calculate handles
    the same roster.  Pinned so a follow-up fix has a harness."""
    payload = _ahri_payload(
        enemies=[],
        allies=[{"champion": "Soraka", "level": 18, "items": [], "role": "support"}],
    )
    client = _client()
    calculate = client.post("/api/calculate", json=payload)
    assert calculate.status_code == 200
    assert "combat" in calculate.get_json()

    optimize = client.post("/api/optimize", json=_optimize_payload(payload))
    assert optimize.status_code == 400
    assert optimize.get_json().get("error_code") == "no_complete_event_order"
