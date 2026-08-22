"""P6 database-layer contract tests.

Covers the PostgreSQL-ready persistence layer (SQLAlchemy 2.x) through its
SQLite fallback: build save/load, share-link round trips with view counting,
validation feedback write/read, result-cache set/get/TTL/invalidation, and
the unconfigured-DATABASE_URL fallback path.  Every test runs against an
isolated SQLite file; the layer itself is dialect-agnostic, so the same
models and helpers run against PostgreSQL in production.
"""

import threading
import time

import pytest
from sqlalchemy import event

import src.app as app_module

# The app imports its persistence layer as the top-level ``db`` module (src/
# is placed on sys.path by app.py).  ``import src.db`` would create a second
# module instance with its own engine, so tests must use the same ``db`` the
# app resolves.
from src import db
from tests.app_config import app_config


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
    with app_config(TESTING=True, RATE_LIMIT_ENABLED=False):
        yield


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

    # The share link is the only read path for a saved build.
    token = client.post("/api/share", json={"build_id": build_id}).get_json()["token"]
    loaded = client.get(f"/api/share/{token}")
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


class _RecordingLimiter:
    """A token bucket that records the scope of every spend."""

    def __init__(self, allowed=True):
        self.scopes = []
        self.allowed = allowed

    def consume(self, scope, **_kwargs):
        self.scopes.append(scope)
        return self.allowed, 2.0


def _budgeted(monkeypatch, limiter):
    monkeypatch.setattr(app_module, "_rate_limiter", limiter)
    monkeypatch.setitem(app_module.app.config, "TESTING", False)
    monkeypatch.setitem(app_module.app.config, "RATE_LIMIT_ENABLED", True)
    return _client()


def test_build_and_share_writes_spend_a_token(sqlite_database, monkeypatch):
    """Both persisting routes are budgeted, like every other public write."""
    limiter = _RecordingLimiter()
    client = _budgeted(monkeypatch, limiter)

    saved = client.post("/api/builds", json=_build_payload())
    assert saved.status_code == 201
    share = client.post("/api/share", json={"build_id": saved.get_json()["build_id"]})

    assert share.status_code == 201
    assert limiter.scopes == ["build_write", "build_write"]


def test_exhausted_build_budget_returns_a_labelled_429(sqlite_database, monkeypatch):
    client = _budgeted(monkeypatch, _RecordingLimiter(allowed=False))

    response = client.post("/api/builds", json=_build_payload())

    assert response.status_code == 429
    assert response.get_json() == {"error": "Build sharing is busy; retry shortly"}
    assert int(response.headers["Retry-After"]) >= 1


def test_malformed_build_write_does_not_spend_a_token(sqlite_database, monkeypatch):
    limiter = _RecordingLimiter()
    client = _budgeted(monkeypatch, limiter)

    assert client.post("/api/builds", json={}).status_code == 400
    assert client.post("/api/share", json={}).status_code == 400
    assert limiter.scopes == []


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


def test_feedback_read_filters(sqlite_database):
    """GET /api/feedback lists what the receipt writer stored, newest first.
    The only HTTP writer is POST /api/receipts (tests/test_p7_validation.py);
    rows are seeded through the persistence helper it calls."""
    client = _client()
    feedback_id = db.add_feedback(
        champion="Ahri",
        loadout={"items": ["Liandry's Torment"]},
        expected={"tdd": 2500.0},
        actual={"tdd": 2487.5},
        source="combat_log",
        matched=False,
        delta=-12.5,
        note="slightly under expected",
    )
    assert isinstance(feedback_id, int)

    listed = client.get("/api/feedback?champion=Ahri").get_json()
    assert listed["count"] == 1
    row = listed["feedback"][0]
    assert row["feedback_id"] == feedback_id
    assert row["source"] == "combat_log"
    assert row["matched"] is False
    assert row["actual"]["tdd"] == 2487.5
    assert "under expected" in row["note"]

    # Champion filter excludes other champions.
    db.add_feedback(champion="Darius", loadout={}, expected={}, actual={})
    assert client.get("/api/feedback?champion=Ahri").get_json()["count"] == 1
    assert client.get("/api/feedback?champion=Darius").get_json()["count"] == 1
    assert client.get("/api/feedback").get_json()["count"] == 2
    assert client.get("/api/feedback?source=combat_log").get_json()["count"] == 1


def test_feedback_query_strings_go_through_request_parsing(sqlite_database):
    """GET query strings use the shared public coercion policy: bounded
    integers and 100-char strings, rejected (400) rather than clamped."""
    client = _client()
    assert client.get("/api/feedback?limit=200").status_code == 200
    for bad in ("0", "201", "abc", "1.5"):
        response = client.get(f"/api/feedback?limit={bad}")
        assert response.status_code == 400, bad
        assert response.get_json()["error"].startswith("limit must be"), bad
    assert client.get("/api/feedback?champion=" + "x" * 101).status_code == 400
    assert client.get("/api/validation?limit=500").status_code == 400
    assert client.get("/api/certainty?champion=" + "x" * 101).status_code == 400


def test_feedback_has_no_client_supplied_writer(sqlite_database):
    """A client may not write expected/actual/matched verbatim into the table
    that drives the /api/validation bias flag; the receipt route derives them."""
    client = _client()
    assert client.post("/api/feedback", json={"champion": "Ahri"}).status_code == 405
    assert client.get("/api/feedback?source=spreadsheet").status_code == 400


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


def _statements_touching_cached_results(action):
    """Run ``action`` and return every SQL statement it aimed at the table."""
    engine = db.get_engine()
    seen = []

    def record(_conn, _cursor, statement, *_rest):
        if "cached_results" in statement:
            seen.append(" ".join(statement.split()))

    event.listen(engine, "after_cursor_execute", record)
    try:
        action()
    finally:
        event.remove(engine, "after_cursor_execute", record)
    return seen


def test_cache_set_writes_one_upsert_statement(sqlite_database):
    """One statement decides the row, so no reader-writer gap exists to lose."""
    key = db.stable_cache_key("calculate", {"champion": "Ahri"})
    statements = _statements_touching_cached_results(
        lambda: db.cache_set(key, {"total_damage": 1.0})
    )
    assert len(statements) == 1, statements
    assert statements[0].upper().startswith("INSERT INTO CACHED_RESULTS")
    assert "ON CONFLICT" in statements[0].upper()


def test_concurrent_cache_set_on_one_key_never_raises(sqlite_database):
    """Two writers racing on one cache_key: neither may raise.

    A barrier armed on the engine's SELECT against ``cached_results`` forces a
    select-then-insert implementation into its losing interleave — both writers
    read no row, both INSERT, and the loser breaks the UNIQUE constraint out of
    ``commit()``.  An upsert issues no such SELECT, so nothing waits.
    """
    key = db.stable_cache_key("calculate", {"champion": "Ahri", "level": 18})
    engine = db.get_engine()
    barrier = threading.Barrier(2, timeout=10)

    def hold_after_existence_check(_conn, _cursor, statement, *_rest):
        if "cached_results" in statement and statement.lstrip()[:6].upper() == "SELECT":
            try:
                barrier.wait()
            except threading.BrokenBarrierError:
                pass

    errors = []

    def writer(index):
        try:
            db.cache_set(key, {"total_damage": float(index)})
        except Exception as exc:  # noqa: BLE001 - the raise under test
            errors.append(exc)

    event.listen(engine, "after_cursor_execute", hold_after_existence_check)
    threads = [threading.Thread(target=writer, args=(index,)) for index in range(2)]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
    finally:
        event.remove(engine, "after_cursor_execute", hold_after_existence_check)

    assert errors == []
    assert db.cache_get(key) in ({"total_damage": 0.0}, {"total_damage": 1.0})
    assert db.cache_stats()["cached_entries"] == 1


def test_cache_consulted_by_calculate_when_configured(sqlite_database, monkeypatch):
    """With DATABASE_URL set and TESTING off, /api/calculate serves the
    second identical request from CachedResult (hit) after computing and
    storing on the first (miss)."""
    monkeypatch.setitem(app_module.app.config, "TESTING", False)
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

    cache = client.get("/api/health/deep").get_json()["checks"]["cache"]
    assert cache["enabled"] is True
    assert cache["hits"] == 1
    assert cache["misses"] == 1
    assert cache["cached_entries"] == 1

    # A different request is a separate key.
    payload["rotations"] = 2
    assert client.post("/api/calculate", json=payload).status_code == 200
    cache = client.get("/api/health/deep").get_json()["checks"]["cache"]
    assert cache["misses"] == 2


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
    cache = client.get("/api/health/deep").get_json()["checks"]["cache"]
    assert cache["enabled"] is False
    assert cache["hits"] == 0
    assert cache["misses"] == 0


# ---------------------------------------------------------------------------
# Staleness + fallback
# ---------------------------------------------------------------------------


def test_sqlite_fallback_without_database_url(monkeypatch, tmp_path):
    """With DATABASE_URL unset the layer still works on a local SQLite file
    (the dev fallback), while is_configured reports False so the result
    cache stays off."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db.reset()
    try:
        assert db.is_configured() is False
        build_id = db.save_build({"champion": "Ahri", "level": 18})
        token = db.create_share_link(build_id)["token"]
        assert db.get_share_link(token)["champion"] == "Ahri"
    finally:
        db.reset()
