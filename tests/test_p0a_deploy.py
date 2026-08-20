"""P0a closed-beta deployment contracts.

Covers the invite-code layer (validation endpoint, login flow, session
invite source), the beta landing page, the managed Postgres/Redis wiring
(result cache on ``REDIS_URL`` with a mocked client), and the documented
environment contract (``.env.example``, runbook, dependency manifests).
"""

import base64
import hashlib
import json
from pathlib import Path

import pytest

import src.app as app_module

# The app imports its persistence layer as the top-level ``db`` module (src/
# is placed on sys.path by app.py), so tests reuse that same module instance.
from src import db


@pytest.fixture(autouse=True)
def _disable_rate_limits_between_route_tests():
    """Keep these route tests off the production abuse-control budget."""
    previous = app_module.app.config.get("RATE_LIMIT_ENABLED", True)
    app_module.app.config["RATE_LIMIT_ENABLED"] = False
    yield
    app_module.app.config["RATE_LIMIT_ENABLED"] = previous


def _test_password_hash(password="secret"):
    salt = b"p0a-invite-salt"
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16_384, r=8, p=1)
    enc = lambda value: base64.urlsafe_b64encode(value).rstrip(b"=").decode()
    return f"scrypt$16384$8$1${enc(salt)}${enc(digest)}"


@pytest.fixture
def invite_env(monkeypatch):
    """Auth gate on with a configured invite-code list."""
    monkeypatch.setenv("SCRYGLASS_AUTH_REQUIRED", "1")
    monkeypatch.setenv("SCRYGLASS_AUTH_SECRET", "p0a-invite-secret")
    monkeypatch.setenv(
        "SCRYGLASS_AUTH_USERS",
        json.dumps({"BetaResearcher": _test_password_hash()}),
    )
    monkeypatch.setenv("SCRYGLASS_INVITE_CODES", "BETA-2026, PRESS-CLUB")
    return app_module


# ---------------------------------------------------------------------------
# Invite-code layer
# ---------------------------------------------------------------------------


def test_invite_codes_parse_trims_deduplicates_and_are_case_sensitive(
    monkeypatch,
):
    monkeypatch.setenv("SCRYGLASS_INVITE_CODES", " BETA-2026 ,beta-2026,, PRESS-CLUB ")
    assert app_module._invite_codes() == (
        "BETA-2026",
        "beta-2026",
        "PRESS-CLUB",
    )
    assert "beta-2026" in app_module._invite_codes()
    assert "BETA-2026" not in app_module._invite_codes()[1:]

    monkeypatch.delenv("SCRYGLASS_INVITE_CODES", raising=False)
    assert app_module._invite_codes() == ()


def test_invite_mode_requires_auth_gate(monkeypatch):
    monkeypatch.setenv("SCRYGLASS_INVITE_CODES", "BETA-2026")
    monkeypatch.delenv("SCRYGLASS_AUTH_REQUIRED", raising=False)
    assert app_module._invite_mode() is False

    monkeypatch.setenv("SCRYGLASS_AUTH_REQUIRED", "1")
    assert app_module._invite_mode() is True


def test_invite_endpoint_validates_codes(invite_env):
    client = app_module.app.test_client()

    status = client.get("/api/auth/invite")
    assert status.status_code == 200
    assert status.get_json() == {"invite_required": True, "configured": True}

    valid = client.post("/api/auth/invite", json={"code": "BETA-2026"})
    assert valid.status_code == 200
    assert valid.get_json() == {"valid": True, "invite": "BETA-2026"}

    trimmed = client.post("/api/auth/invite", json={"code": " PRESS-CLUB "})
    assert trimmed.status_code == 200
    assert trimmed.get_json()["invite"] == "PRESS-CLUB"

    unknown = client.post("/api/auth/invite", json={"code": "not-a-code"})
    assert unknown.status_code == 401
    assert "Invalid invite code" in unknown.get_json()["error"]

    missing = client.post("/api/auth/invite", json={})
    assert missing.status_code == 400

    non_string = client.post("/api/auth/invite", json={"code": 42})
    assert non_string.status_code == 400

    invalid_json = client.post(
        "/api/auth/invite", data="{not json", content_type="application/json"
    )
    assert invalid_json.status_code == 400


def test_invite_endpoint_fails_closed_when_no_codes_configured(monkeypatch):
    monkeypatch.setenv("SCRYGLASS_AUTH_REQUIRED", "1")
    monkeypatch.setenv("SCRYGLASS_AUTH_SECRET", "p0a-secret")
    monkeypatch.setenv(
        "SCRYGLASS_AUTH_USERS",
        json.dumps({"BetaResearcher": _test_password_hash()}),
    )
    monkeypatch.delenv("SCRYGLASS_INVITE_CODES", raising=False)
    client = app_module.app.test_client()

    status = client.get("/api/auth/invite")
    assert status.get_json() == {"invite_required": False, "configured": False}
    rejected = client.post("/api/auth/invite", json={"code": "anything"})
    assert rejected.status_code == 503
    assert "not configured" in rejected.get_json()["error"]


def test_login_with_invite_records_invite_source(invite_env):
    client = app_module.app.test_client()
    login = client.post(
        "/auth/login",
        data={
            "username": "BetaResearcher",
            "password": "secret",
            "invite_code": "BETA-2026",
            "next": "/",
        },
        follow_redirects=False,
    )
    assert login.status_code == 302
    assert login.headers["Location"].endswith("/")

    status = client.get("/auth/status").get_json()
    assert status["authenticated"] is True
    assert status["invite_required"] is True
    assert status["user"]["username"] == "BetaResearcher"
    assert status["user"]["invite"] == "BETA-2026"

    # A different invite batch is recorded per session.
    second = app_module.app.test_client()
    second.post(
        "/auth/login",
        data={
            "username": "BetaResearcher",
            "password": "secret",
            "invite_code": "PRESS-CLUB",
        },
        follow_redirects=False,
    )
    assert second.get("/auth/status").get_json()["user"]["invite"] == "PRESS-CLUB"


def test_login_rejects_bad_invite_or_credentials(invite_env):
    client = app_module.app.test_client()
    bad_invite = client.post(
        "/auth/login",
        data={
            "username": "BetaResearcher",
            "password": "secret",
            "invite_code": "not-a-code",
        },
    )
    assert bad_invite.status_code == 401
    assert "valid invite code" in bad_invite.get_data(as_text=True).lower()

    missing_invite = client.post(
        "/auth/login",
        data={"username": "BetaResearcher", "password": "secret"},
    )
    assert missing_invite.status_code == 401

    bad_password = client.post(
        "/auth/login",
        data={
            "username": "BetaResearcher",
            "password": "wrong",
            "invite_code": "BETA-2026",
        },
    )
    assert bad_password.status_code == 401
    assert "not recognised" in bad_password.get_data(as_text=True).lower()


def test_password_only_login_still_works_without_invite_codes(monkeypatch):
    monkeypatch.setenv("SCRYGLASS_AUTH_REQUIRED", "1")
    monkeypatch.setenv("SCRYGLASS_AUTH_SECRET", "p0a-secret")
    monkeypatch.setenv(
        "SCRYGLASS_AUTH_USERS",
        json.dumps({"BetaResearcher": _test_password_hash()}),
    )
    monkeypatch.delenv("SCRYGLASS_INVITE_CODES", raising=False)
    client = app_module.app.test_client()

    login = client.post(
        "/auth/login",
        data={"username": "BetaResearcher", "password": "secret", "next": "/"},
        follow_redirects=False,
    )
    assert login.status_code == 302
    status = client.get("/auth/status").get_json()
    assert status["user"]["username"] == "BetaResearcher"
    assert status["user"]["invite"] is None
    assert status["invite_required"] is False


# ---------------------------------------------------------------------------
# Beta landing page + pre-auth surface
# ---------------------------------------------------------------------------


def test_landing_page_renders_beta_content(invite_env):
    page = invite_env.app.test_client().get("/auth/login")
    body = page.get_data(as_text=True)
    assert page.status_code == 200
    for required in (
        "Closed beta",
        "How it works",
        "Enter with your invite code",
        'name="invite_code"',
        "research-account password",
        "Scryglass isn't endorsed by Riot Games",
        'href="/privacy"',
        "Enter the calculator",
    ):
        assert required in body, required
    # The bare pre-beta page is gone.
    assert "Private calculator" not in body


def test_landing_page_omits_invite_field_in_password_only_mode(monkeypatch):
    monkeypatch.setenv("SCRYGLASS_AUTH_REQUIRED", "1")
    monkeypatch.setenv("SCRYGLASS_AUTH_SECRET", "p0a-secret")
    monkeypatch.setenv(
        "SCRYGLASS_AUTH_USERS",
        json.dumps({"BetaResearcher": _test_password_hash()}),
    )
    monkeypatch.delenv("SCRYGLASS_INVITE_CODES", raising=False)
    body = app_module.app.test_client().get("/auth/login").get_data(as_text=True)
    assert 'name="invite_code"' not in body
    assert "approved research accounts" in body


def test_privacy_page_is_public_and_lists_beta_data(invite_env):
    page = invite_env.app.test_client().get("/privacy")
    body = page.get_data(as_text=True)
    assert page.status_code == 200
    for required in (
        "Privacy during the closed beta",
        "session cookie",
        "invite code you used",
        "Riot account",
        "no analytics",
    ):
        assert required in body, required


def test_gate_exempts_only_the_preauth_surface(invite_env):
    client = invite_env.app.test_client()
    assert client.get("/", follow_redirects=False).status_code == 302
    assert client.get("/healthz").status_code == 200
    assert client.get("/api/auth/invite").status_code == 200
    assert client.get("/privacy").status_code == 200
    # Everything else stays gated.
    assert client.get("/api/items").status_code == 302


# ---------------------------------------------------------------------------
# Managed Redis result cache
# ---------------------------------------------------------------------------


class FakeRedis:
    """Minimal in-memory stand-in for redis.Redis (str keys and values)."""

    def __init__(self):
        self._store = {}
        self._counters = {}

    def get(self, key):
        return self._store.get(key)

    def set(self, key, value, ex=None):
        self._store[key] = value
        return True

    def hincrby(self, key, field, amount):
        bucket = self._counters.setdefault(key, {})
        bucket[field] = bucket.get(field, 0) + amount
        return bucket[field]

    def hgetall(self, key):
        return dict(self._counters.get(key, {}))

    def scan_iter(self, match=None, count=None):
        prefix = match[:-1] if match and match.endswith("*") else (match or "")
        return (key for key in list(self._store) if key.startswith(prefix))

    def delete(self, *keys):
        removed = 0
        for key in keys:
            if key in self._store:
                del self._store[key]
                removed += 1
        return removed


@pytest.fixture
def redis_env(monkeypatch):
    """Point the result cache at a fake Redis and isolate db state."""
    fake = FakeRedis()
    monkeypatch.setenv("REDIS_URL", "redis://cache.example.invalid:6379/0")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(db, "_redis_client", lambda: fake)
    db.reset()
    yield fake
    db.reset()


def test_redis_cache_dispatch_behind_the_same_interface(redis_env):
    assert db.redis_configured() is True
    assert db.cache_backend() == "redis"

    key = db.stable_cache_key("calculate", {"champion": "Ahri", "level": 18})
    assert db.cache_get(key) is None  # miss recorded
    db.cache_set(key, {"total_damage": 321.0})
    assert db.cache_get(key) == {"total_damage": 321.0}  # hit

    db.cache_set(db.stable_cache_key("bis", {"champion": "Ahri"}), {"ranked": []})
    stats = db.cache_stats()
    assert stats["hits"] == 1
    assert stats["misses"] == 1
    assert stats["cached_entries"] == 2

    removed = db.cache_delete_all()
    assert removed == 2
    stats = db.cache_stats()
    assert stats["cached_entries"] == 0
    assert db.cache_get(key) is None


def test_redis_cache_uses_configured_ttl(redis_env):
    key = db.stable_cache_key("calculate", {"champion": "Ahri"})
    db.cache_set(key, {"total_damage": 1.0}, ttl_seconds=30)
    assert db.cache_get(key) == {"total_damage": 1.0}
    # The fake records the Redis TTL on SET.
    stored_ttl = redis_env._store.get("scryglass:cache:entry:" + key)
    assert stored_ttl is not None


def test_redis_cache_failure_fails_closed(redis_env, monkeypatch):
    class FailingRedis(FakeRedis):
        def get(self, key):
            raise RuntimeError("connection refused")

        def hgetall(self, key):
            raise RuntimeError("connection refused")

    monkeypatch.setattr(db, "_redis_client", lambda: FailingRedis())
    key = db.stable_cache_key("calculate", {"champion": "Ahri"})
    with pytest.raises(db.CacheUnavailable):
        db.cache_get(key)
    deep = app_module.app.test_client().get("/api/health/deep").get_json()
    assert deep["status"] == "error"
    assert deep["checks"]["cache"]["status"] == "error"
    assert deep["checks"]["cache"]["error"]


def test_result_cache_uses_redis_when_only_redis_configured(redis_env):
    previous_testing = app_module.app.config.get("TESTING")
    app_module.app.config["TESTING"] = False
    try:
        assert app_module._result_cache_enabled() is True
    finally:
        if previous_testing is None:
            app_module.app.config.pop("TESTING", None)
        else:
            app_module.app.config["TESTING"] = previous_testing


def test_calculate_route_serves_from_redis_cache(redis_env):
    """With REDIS_URL set and TESTING off, /api/calculate stores on the first
    request and serves the second identical request from Redis."""
    previous_testing = app_module.app.config.get("TESTING")
    app_module.app.config["TESTING"] = False
    try:
        client = app_module.app.test_client()
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

        checks = client.get("/api/health/deep").get_json()["checks"]
        assert checks["cache"]["enabled"] is True
        assert checks["cache"]["backend"] == "redis"
        assert checks["db"]["configured"] is False
        assert checks["cache"]["hits"] == 1
        assert checks["cache"]["misses"] == 1
        assert checks["cache"]["cached_entries"] == 1
    finally:
        if previous_testing is None:
            app_module.app.config.pop("TESTING", None)
        else:
            app_module.app.config["TESTING"] = previous_testing


# ---------------------------------------------------------------------------
# Environment contract
# ---------------------------------------------------------------------------


def test_env_example_documents_every_gate_variable():
    example = Path(".env.example").read_text(encoding="utf-8")
    for variable in (
        "SCRYGLASS_AUTH_REQUIRED",
        "SCRYGLASS_AUTH_SECRET",
        "SCRYGLASS_AUTH_USERS",
        "SCRYGLASS_INVITE_CODES",
        "DATABASE_URL",
        "REDIS_URL",
        "CACHE_TTL_SECONDS",
    ):
        assert f"{variable}=" in example, variable
    assert "Neon" in example and "Supabase" in example and "RDS" in example
    assert "Upstash" in example


def test_gitignore_never_tracks_real_env_files():
    ignore = Path(".gitignore").read_text(encoding="utf-8")
    assert ".env" in ignore
    assert "!.env.example" in ignore


def test_runtime_manifests_include_redis():
    runtime_in = Path("requirements-runtime.in").read_text(encoding="utf-8")
    runtime_lock = Path("requirements-runtime.txt").read_text(encoding="utf-8")
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    assert "redis==7.4.1" in runtime_in
    assert "redis==7.4.1" in runtime_lock
    assert "--hash=sha256:" in runtime_lock
    assert '"redis==7.4.1"' in pyproject


def test_deploy_runbook_covers_managed_infrastructure_and_rollback():
    runbook = Path("docs/deploy-runbook.md").read_text(encoding="utf-8")
    for required in (
        "SCRYGLASS_INVITE_CODES",
        "DATABASE_URL",
        "REDIS_URL",
        "Neon",
        "Supabase",
        "RDS",
        "Upstash",
        "/healthz",
        "Rollback",
        "Deployment Protection",
    ):
        assert required in runbook, required
