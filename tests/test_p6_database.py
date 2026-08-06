"""P6 database-layer contract tests.

Covers the PostgreSQL-ready persistence layer (SQLAlchemy 2.x) through its
SQLite fallback: build save/load, share-link round trips with view counting,
validation feedback write/read, result-cache set/get/TTL/invalidation, and
the unconfigured-DATABASE_URL fallback path.  Every test runs against an
isolated SQLite file; the layer itself is dialect-agnostic, so the same
models and helpers run against PostgreSQL in production.
"""

import time

import pytest

import src.app as app_module

# The app imports its persistence layer as the top-level ``db`` module (src/
# is placed on sys.path by app.py).  ``import src.db`` would create a second
# module instance with its own engine, so tests must use the same ``db`` the
# app resolves.
import db


@pytest.fixture
def sqlite_database(tmp_path, monkeypatch):
    """Point the app at an isolated SQLite file and reset the engine."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'p6.sqlite3'}")
    db.reset()
    yield db
    db.reset()


@pytest.fixture(autouse=True)
def _isolate_app_config():
    """Keep these route tests off the shared rate-limit budget."""
    previous_testing = app_module.app.config.get("TESTING")
    previous_rate = app_module.app.config.get("RATE_LIMIT_ENABLED", True)
    app_module.app.config["TESTING"] = True
    app_module.app.config["RATE_LIMIT_ENABLED"] = False
    yield
    if previous_testing is None:
        app_module.app.config.pop("TESTING", None)
    else:
        app_module.app.config["TESTING"] = previous_testing
    app_module.app.config["RATE_LIMIT_ENABLED"] = previous_rate


def _client():
    return app_module.app.test_client()


def _build_payload(**overrides):
    payload = {
        "champion": "Ahri",
        "level": 18,
        "role": "mid",
        "items": ["Liandry's Torment", "Shadowflame"],
        "item_options": {"Liandry's Torment": {"mythic": False}},
        "ability_ranks": {"Q": 5, "W": 3, "E": 3, "R": 2},
        "champion_options": {"q_max": True},
        "enemies": [{"champion": "Darius", "level": 16, "items": []}],
        "allies": [{"champion": "Lulu", "level": 16, "items": []}],
        "boots": "Sorcerer's Shoes",
        "target_health": 1000,
        "rotations": 1,
        "fight_mode": "one_rotation",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Builds
# ---------------------------------------------------------------------------


def test_save_and_load_build_round_trip(sqlite_database):
    client = _client()
    response = client.post("/api/builds", json=_build_payload())
    assert response.status_code == 201
    build_id = response.get_json()["build_id"]
    assert isinstance(build_id, int)

    loaded = client.get(f"/api/builds/{build_id}")
    assert loaded.status_code == 200
    payload = loaded.get_json()
    assert payload["champion"] == "Ahri"
    assert payload["level"] == 18
    assert payload["role"] == "mid"
    assert payload["items"] == ["Liandry's Torment", "Shadowflame"]
    assert payload["ability_ranks"]["Q"] == 5
    assert payload["enemies"][0]["champion"] == "Darius"
    # Boots and fight settings ride in fight_params and are reconstructed
    # into a full calculate-style request.
    assert payload["fight_params"]["boots"] == "Sorcerer's Shoes"
    assert payload["request"]["boots"] == "Sorcerer's Shoes"
    assert payload["request"]["champion"] == "Ahri"
    assert payload["request"]["rotations"] == 1
    assert payload["created_at"].endswith("Z")


def test_get_build_404(sqlite_database):
    assert _client().get("/api/builds/999999").status_code == 404


def test_save_build_validation(sqlite_database):
    client = _client()
    assert client.post("/api/builds", json={}).status_code == 400
    assert (
        client.post("/api/builds", json=_build_payload(items="not-a-list")).status_code
        == 400
    )
    assert (
        client.post(
            "/api/builds", json=_build_payload(ability_ranks="nope")
        ).status_code
        == 400
    )
    assert client.post("/api/builds", json=_build_payload(level=99)).status_code == 400


# ---------------------------------------------------------------------------
# Share links
# ---------------------------------------------------------------------------


def test_share_link_round_trip_and_view_increment(sqlite_database):
    client = _client()
    build_id = client.post("/api/builds", json=_build_payload()).get_json()["build_id"]
    created = client.post("/api/share", json={"build_id": build_id, "slug": "ahri"})
    assert created.status_code == 201
    token = created.get_json()["token"]
    assert len(token) >= 20
    assert created.get_json()["url"] == f"/api/share/{token}"

    first = client.get(f"/api/share/{token}")
    assert first.status_code == 200
    assert first.get_json()["champion"] == "Ahri"
    assert first.get_json()["share"]["views"] == 1

    second = client.get(f"/api/share/{token}")
    assert second.status_code == 200
    assert second.get_json()["share"]["views"] == 2
    # Build payload is intact on every view.
    assert second.get_json()["items"] == ["Liandry's Torment", "Shadowflame"]


def test_share_link_unknown_token_and_missing_build(sqlite_database):
    client = _client()
    assert client.get("/api/share/does-not-exist").status_code == 404
    assert client.post("/api/share", json={"build_id": 424242}).status_code == 404


def test_share_link_slug_validation(sqlite_database):
    client = _client()
    build_id = client.post("/api/builds", json=_build_payload()).get_json()["build_id"]
    ok = client.post(
        "/api/share", json={"build_id": build_id, "slug": "ahri-vs-darius_1"}
    )
    assert ok.status_code == 201
    bad = client.post("/api/share", json={"build_id": build_id, "slug": "bad slug!"})
    assert bad.status_code == 400


def test_share_links_are_unique_per_build(sqlite_database):
    client = _client()
    build_id = client.post("/api/builds", json=_build_payload()).get_json()["build_id"]
    first = client.post("/api/share", json={"build_id": build_id}).get_json()["token"]
    second = client.post("/api/share", json={"build_id": build_id}).get_json()["token"]
    assert first != second


# ---------------------------------------------------------------------------
# Validation feedback
# ---------------------------------------------------------------------------


def test_feedback_write_and_read(sqlite_database):
    client = _client()
    created = client.post(
        "/api/feedback",
        json={
            "champion": "Ahri",
            "loadout": {"items": ["Liandry's Torment"]},
            "expected": {"total_damage": 2500.0},
            "actual": {"total_damage": 2487.5},
            "source": "combat_log",
            "matched": False,
            "note": "slightly under expected",
        },
    )
    assert created.status_code == 201
    feedback_id = created.get_json()["feedback_id"]
    assert isinstance(feedback_id, int)

    listed = client.get("/api/feedback?champion=Ahri").get_json()
    assert listed["count"] == 1
    row = listed["feedback"][0]
    assert row["feedback_id"] == feedback_id
    assert row["source"] == "combat_log"
    assert row["matched"] is False
    assert row["actual"]["total_damage"] == 2487.5
    assert "under expected" in row["note"]

    # Champion filter excludes other champions.
    client.post(
        "/api/feedback",
        json={"champion": "Darius", "expected": {}, "actual": {}},
    )
    assert client.get("/api/feedback?champion=Ahri").get_json()["count"] == 1
    assert client.get("/api/feedback?champion=Darius").get_json()["count"] == 1
    assert client.get("/api/feedback").get_json()["count"] == 2


def test_feedback_source_validation(sqlite_database):
    client = _client()
    bad = client.post(
        "/api/feedback", json={"champion": "Ahri", "source": "spreadsheet"}
    )
    assert bad.status_code == 400
    missing = client.post("/api/feedback", json={"expected": {}, "actual": {}})
    assert missing.status_code == 400
    not_bool = client.post("/api/feedback", json={"champion": "Ahri", "matched": "yes"})
    assert not_bool.status_code == 400


# ---------------------------------------------------------------------------
# Result cache
# ---------------------------------------------------------------------------


def test_cache_set_get_round_trip(sqlite_database):
    key = db.stable_cache_key("calculate", {"champion": "Ahri", "level": 18})
    assert len(key) == 64
    assert key != db.stable_cache_key("calculate", {"champion": "Ahri", "level": 17})
    assert key != db.stable_cache_key("bis", {"champion": "Ahri", "level": 18})

    assert db.cache_get(key) is None
    db.cache_set(key, {"total_damage": 1234.5})
    assert db.cache_get(key) == {"total_damage": 1234.5}

    stats = db.cache_stats()
    assert stats["hits"] == 1
    assert stats["misses"] == 1
    assert stats["cached_entries"] == 1


def test_cache_ttl_expiry(sqlite_database):
    key = db.stable_cache_key("calculate", {"champion": "Ahri"})
    db.cache_set(key, {"total_damage": 1.0}, ttl_seconds=1)
    assert db.cache_get(key) == {"total_damage": 1.0}
    time.sleep(1.1)
    assert db.cache_get(key) is None
    assert db.cache_stats()["cached_entries"] == 0


def test_cache_invalidation_clears_everything(sqlite_database):
    key = db.stable_cache_key("calculate", {"champion": "Ahri"})
    db.cache_set(key, {"total_damage": 1.0})
    db.cache_set(db.stable_cache_key("bis", {"champion": "Ahri"}), {"ranked": []})
    assert db.cache_stats()["cached_entries"] == 2
    removed = db.cache_delete_all()
    assert removed == 2
    assert db.cache_stats()["cached_entries"] == 0
    assert db.cache_get(key) is None


def test_cache_consulted_by_calculate_when_configured(sqlite_database):
    """With DATABASE_URL set and TESTING off, /api/calculate serves the
    second identical request from CachedResult (hit) after computing and
    storing on the first (miss)."""
    app_module.app.config["TESTING"] = False
    client = _client()
    payload = {
        "champion": "Ahri",
        "level": 18,
        "items": ["Liandry's Torment"],
        "boots": "Sorcerer's Shoes",
        "target_health": 1000,
        "target_armor": 50,
        "target_mr": 40,
        "fight_mode": "one_rotation",
        "fight_duration": 5,
        "include_auto_attacks": False,
        "auto_attack_uptime": 0,
        "rotations": 1,
        "role": "mid",
        "enemies": [],
        "allies": [],
    }
    cold = client.post("/api/calculate", json=payload)
    assert cold.status_code == 200
    warm = client.post("/api/calculate", json=payload)
    assert warm.status_code == 200
    assert cold.get_json() == warm.get_json()

    status = client.get("/api/cache-status").get_json()
    assert status["cache_enabled"] is True
    assert status["hits"] == 1
    assert status["misses"] == 1
    assert status["cached_entries"] == 1

    # A different request is a separate key.
    payload["rotations"] = 2
    assert client.post("/api/calculate", json=payload).status_code == 200
    assert client.get("/api/cache-status").get_json()["misses"] == 2


def test_cache_bypassed_in_testing_mode(sqlite_database):
    """TESTING bypasses the result cache even with DATABASE_URL configured."""
    client = _client()
    payload = {
        "champion": "Ahri",
        "level": 18,
        "items": [],
        "enemies": [],
        "allies": [],
    }
    payload.update(
        {
            "target_health": 1000,
            "target_armor": 50,
            "target_mr": 40,
            "fight_mode": "one_rotation",
            "rotations": 1,
        }
    )
    first = client.post("/api/calculate", json=payload)
    assert first.status_code == 200
    assert client.post("/api/calculate", json=payload).status_code == 200
    status = client.get("/api/cache-status").get_json()
    assert status["cache_enabled"] is False
    assert status["hits"] == 0
    assert status["misses"] == 0


# ---------------------------------------------------------------------------
# Staleness + fallback
# ---------------------------------------------------------------------------


def test_staleness_state_round_trip(sqlite_database):
    db.staleness_set("25.7", {"verified": True, "diffs": []})
    row = db.staleness_get("25.7")
    assert row["payload"]["verified"] is True
    assert row["checked_at"].endswith("Z")
    db.staleness_set("25.7", {"verified": False, "diffs": ["Q recast"]})
    assert db.staleness_get("25.7")["payload"]["diffs"] == ["Q recast"]
    assert db.staleness_get("24.5") is None


def test_sqlite_fallback_without_database_url(monkeypatch, tmp_path):
    """With DATABASE_URL unset the layer still works on a local SQLite file
    (the dev fallback), while is_configured reports False so the result
    cache stays off."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db.reset()
    try:
        assert db.is_configured() is False
        build_id = db.save_build({"champion": "Ahri", "level": 18})
        loaded = db.get_build(build_id)
        assert loaded["champion"] == "Ahri"
    finally:
        db.reset()
