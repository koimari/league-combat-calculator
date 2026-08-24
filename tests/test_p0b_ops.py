"""P0b closed-beta ops floor.

Covers the four operational deliverables:

- Sentry error tracking: lazy ``sentry_sdk`` initialisation behind
  ``SENTRY_DSN``, no-op without the DSN, ``capture_exception`` on route
  errors, and rate-limit 429s excluded from capture.
- Database backups: ``scripts/backup_db.py`` plans/dispatch/retention with a
  dry-run that never executes.
- Deep health monitoring: ``/api/health/deep`` db/cache/golden/engine checks
  (golden stale at >= 14 days) and the public (pre-auth) surface.
- Load sanity: ``scripts/load_sanity.py`` payloads, p95 budget assertions and
  warm-pass cache-hit-ratio assertion (the full concurrent run is executed
  manually against a local server, not inside pytest).
"""

import base64
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from werkzeug.exceptions import TooManyRequests

import src.app as app_module
import scripts.backup_db as backup_db
import scripts.load_sanity as load_sanity


@pytest.fixture(autouse=True)
def _isolate_app_config():
    """Restore shared app config (TESTING/PROPAGATE_EXCEPTIONS) after each test."""
    previous = {
        key: app_module.app.config.get(key)
        for key in ("TESTING", "PROPAGATE_EXCEPTIONS", "RATE_LIMIT_ENABLED")
    }
    yield
    for key, value in previous.items():
        if value is None:
            app_module.app.config.pop(key, None)
        else:
            app_module.app.config[key] = value


class _FakeSentry:
    """Minimal sentry_sdk stand-in recording init/capture calls."""

    def __init__(self):
        self.init_calls = []
        self.captured = []

    def init(self, **kwargs):
        self.init_calls.append(kwargs)

    def capture_exception(self, error):
        self.captured.append(error)


@pytest.fixture
def fake_sentry(monkeypatch):
    fake = _FakeSentry()
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake)
    monkeypatch.setattr(app_module, "_sentry", None)
    return fake


# ---------------------------------------------------------------------------
# Sentry error tracking
# ---------------------------------------------------------------------------


def test_sentry_noop_without_dsn(monkeypatch, fake_sentry):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    app_module._configure_sentry()
    assert app_module._sentry is None
    # The fake module was never initialised, and capture is a safe no-op.
    assert fake_sentry.init_calls == []
    app_module._capture_exception(RuntimeError("must not raise"))
    assert fake_sentry.captured == []


def test_sentry_lazy_init_uses_dsn(monkeypatch, fake_sentry):
    monkeypatch.setenv("SENTRY_DSN", "https://key@o0.ingest.sentry.io/42")
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "beta")
    app_module._configure_sentry()
    assert app_module._sentry is fake_sentry
    assert fake_sentry.init_calls == [
        {
            "dsn": "https://key@o0.ingest.sentry.io/42",
            "environment": "beta",
            "traces_sample_rate": 0.0,
            "send_default_pii": False,
        }
    ]


def test_sentry_captures_route_500(monkeypatch, fake_sentry):
    monkeypatch.setattr(app_module, "_sentry", fake_sentry)
    monkeypatch.setitem(app_module.app.config, "TESTING", False)
    app_module.app.config["PROPAGATE_EXCEPTIONS"] = False

    def _broken_loader(_champion_name):
        raise RuntimeError("p0b deliberate boom")

    # The shared scenario boundary owns champion loading for the
    # calculate path (issue #138), so the break is injected there.  The app
    # imports the canonical ``src.calculator`` package (issue #164), so that
    # module object is the one the route executes.
    import src.calculator.scenario as calculator_scenario

    monkeypatch.setattr(calculator_scenario, "load_public_champion", _broken_loader)
    payload = {
        "champion": "Ahri",
        "level": 18,
        "items": [],
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
    response = app_module.app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 500
    assert response.get_json() == {"error": "Internal server error"}
    assert len(fake_sentry.captured) == 1
    assert isinstance(fake_sentry.captured[0], RuntimeError)
    assert "p0b deliberate boom" in str(fake_sentry.captured[0])


def test_sentry_excludes_429_error_handler(monkeypatch, fake_sentry):
    """The 429 error handler returns JSON and never captures to Sentry."""
    monkeypatch.setattr(app_module, "_sentry", fake_sentry)
    with app_module.app.test_request_context("/"):
        response = app_module._rate_limited(TooManyRequests())
    assert response[0].get_json() == {"error": "Rate limit exceeded"}
    assert response[1] == 429
    assert fake_sentry.captured == []


def test_sentry_excludes_token_bucket_429_response(monkeypatch, fake_sentry):
    """The rate-limiter path returns a 429 response directly, never captured."""
    monkeypatch.setattr(app_module, "_sentry", fake_sentry)

    class Denied:
        @staticmethod
        def consume(scope, *, capacity, refill_per_second, now=None):
            return False, 7.0

    monkeypatch.setattr(app_module, "_rate_limiter", Denied())
    # The session holds TESTING on and the limiter no-ops under it, so this
    # test borrows it off.
    monkeypatch.setitem(app_module.app.config, "TESTING", False)
    app_module.app.config["RATE_LIMIT_ENABLED"] = True
    with app_module.app.test_request_context("/"):
        response = app_module._spend_rate_limit("calculate")
    assert response is not None
    assert response.status_code == 429
    assert response.get_json()["error"]
    assert fake_sentry.captured == []


def test_sentry_in_dependency_manifests():
    runtime_in = Path("requirements-runtime.in").read_text(encoding="utf-8")
    sentry_pin = next(
        line.strip()
        for line in runtime_in.splitlines()
        if line.startswith("sentry-sdk==")
    )
    for manifest in (
        "requirements.txt",
        "requirements-runtime.txt",
        "pyproject.toml",
    ):
        assert sentry_pin in Path(manifest).read_text(
            encoding="utf-8"
        ), manifest
    assert "--hash=sha256:" in Path("requirements-runtime.txt").read_text(
        encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Deep health monitoring
# ---------------------------------------------------------------------------


def test_deep_health_returns_all_checks():
    client = app_module.app.test_client()
    response = client.get("/api/health/deep")
    assert response.status_code == 200
    body = response.get_json()
    assert set(body["checks"]) == {"db", "cache", "golden", "engine"}
    assert body["status"] in {"ok", "degraded", "error"}
    assert "generated_at" in body

    db_check = body["checks"]["db"]
    assert db_check["status"] == "ok"
    assert db_check["backend"] == "sqlite"
    assert db_check["configured"] is False

    cache_check = body["checks"]["cache"]
    assert cache_check["status"] == "ok"
    assert cache_check["enabled"] is False
    assert cache_check["backend"] == "sqlite"
    assert "hits" in cache_check and "misses" in cache_check

    engine_check = body["checks"]["engine"]
    assert engine_check["status"] == "ok"
    assert engine_check["registered"] > 0


def test_deep_health_golden_stale_after_14_days(monkeypatch, tmp_path):
    report = tmp_path / "staleness.json"
    report.write_text(
        json.dumps({"patch": "16.15", "checked_at": "2026-07-01T00:00:00+00:00"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(app_module, "_staleness_path", lambda: report)
    body = app_module.app.test_client().get("/api/health/deep").get_json()
    golden = body["checks"]["golden"]
    assert golden["status"] == "stale"
    assert golden["patch"] == "16.15"
    assert golden["age_days"] >= 14.0
    assert golden["stale_threshold_days"] == 14
    assert body["status"] == "degraded"


def test_deep_health_golden_fresh_is_ok(monkeypatch, tmp_path):
    # Freshness is measured against the wall clock, so this fixture must be
    # relative to "now". A hardcoded date silently expires once it drifts past
    # the 14-day threshold and turns this into a false "stale" failure.
    checked_at = datetime.now(timezone.utc) - timedelta(days=1)
    report = tmp_path / "staleness.json"
    report.write_text(
        json.dumps({"patch": "16.15", "checked_at": checked_at.isoformat()}),
        encoding="utf-8",
    )
    monkeypatch.setattr(app_module, "_staleness_path", lambda: report)
    golden = (
        app_module.app.test_client()
        .get("/api/health/deep")
        .get_json()["checks"]["golden"]
    )
    assert golden["status"] == "ok"
    assert golden["age_days"] < 14.0


def test_deep_health_golden_missing_is_error(monkeypatch, tmp_path):
    missing = tmp_path / "does-not-exist.json"
    monkeypatch.setattr(app_module, "_staleness_path", lambda: missing)
    body = app_module.app.test_client().get("/api/health/deep").get_json()
    assert body["checks"]["golden"]["status"] == "missing"
    assert body["status"] == "degraded"


def test_deep_health_db_failure_is_error(monkeypatch):
    def _broken_session():
        raise RuntimeError("connection refused")

    monkeypatch.setattr(app_module, "session", _broken_session)
    body = app_module.app.test_client().get("/api/health/deep").get_json()
    assert body["checks"]["db"]["status"] == "error"
    assert body["status"] == "error"


def _test_password_hash(password="secret"):
    salt = b"p0b-ops-salt"
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16_384, r=8, p=1)
    enc = lambda value: base64.urlsafe_b64encode(value).rstrip(b"=").decode()
    return f"scrypt$16384$8$1${enc(salt)}${enc(digest)}"


def test_deep_health_is_public_under_auth_gate(monkeypatch):
    monkeypatch.setenv("SCRYGLASS_AUTH_REQUIRED", "1")
    monkeypatch.setenv("SCRYGLASS_AUTH_SECRET", "p0b-secret")
    monkeypatch.setenv(
        "SCRYGLASS_AUTH_USERS",
        json.dumps({"BetaResearcher": _test_password_hash()}),
    )
    client = app_module.app.test_client()
    assert client.get("/", follow_redirects=False).status_code == 302
    deep = client.get("/api/health/deep")
    assert deep.status_code == 200
    assert deep.get_json()["checks"]["engine"]["registered"] > 0


# ---------------------------------------------------------------------------
# Database backups
# ---------------------------------------------------------------------------


def test_backup_dry_run_plans_without_executing(monkeypatch, tmp_path, capsys):
    executed = []
    monkeypatch.setattr(
        backup_db.subprocess, "run", lambda *args, **kwargs: executed.append(args)
    )
    rc = backup_db.main(["--dry-run", "--out-dir", str(tmp_path), "--retention", "3"])
    assert rc == 0
    assert executed == []
    output = capsys.readouterr().out
    assert "dry-run" in output
    assert "sqlite3" in output


def test_backup_commands_dispatch_by_backend(tmp_path):
    pg = backup_db.build_commands(
        "postgresql://user:pass@host:5432/lcc", tmp_path, timestamp="20260806-023000"
    )
    assert pg[0].startswith("pg_dump --no-owner --no-privileges")
    assert "scryglass-db-20260806-023000.sql" in pg[0]

    sqlite = backup_db.build_commands(
        "sqlite:////tmp/some.db", tmp_path, timestamp="20260806-023000"
    )
    assert sqlite[0].startswith('sqlite3 "/tmp/some.db" ".backup ')
    assert "scryglass-db-20260806-023000.sqlite" in sqlite[0]

    fallback = backup_db.build_commands(None, tmp_path, timestamp="20260806-023000")
    assert fallback[0].startswith(
        'sqlite3 "/tmp/lol-calculator-fallback.sqlite3" ".backup '
    )

    with_redis = backup_db.build_commands(
        None,
        tmp_path,
        include_redis=True,
        redis_url="redis://cache:6379",
        timestamp="20260806-023000",
    )
    assert with_redis[-1].startswith('redis-cli -u "redis://cache:6379" SAVE')

    no_redis = backup_db.build_commands(
        None, tmp_path, include_redis=True, redis_url=None, timestamp="20260806-023000"
    )
    assert len(no_redis) == 1 and "redis-cli" not in no_redis[0]


def test_backup_retention_keeps_newest(tmp_path):
    for stamp in (
        "20260801-000000",
        "20260802-000000",
        "20260803-000000",
        "20260804-000000",
    ):
        (tmp_path / f"scryglass-db-{stamp}.sql").write_text("dump", encoding="utf-8")
    (tmp_path / "unrelated.txt").write_text("keep", encoding="utf-8")

    deleted = backup_db.apply_retention(tmp_path, 3)
    assert {p.name for p in deleted} == {"scryglass-db-20260801-000000.sql"}
    assert (tmp_path / "unrelated.txt").exists()
    remaining = {p.name for p in backup_db._backup_files(tmp_path)}
    assert remaining == {
        "scryglass-db-20260802-000000.sql",
        "scryglass-db-20260803-000000.sql",
        "scryglass-db-20260804-000000.sql",
    }

    # Dry-run reports the same deletions without touching the files.
    planned = backup_db.apply_retention(tmp_path, 2, dry_run=True)
    assert {p.name for p in planned} == {"scryglass-db-20260802-000000.sql"}
    assert backup_db._backup_files(tmp_path)[-1].name.endswith("20260802-000000.sql")


# ---------------------------------------------------------------------------
# Load sanity script
# ---------------------------------------------------------------------------


def test_load_sanity_payloads_have_required_contract():
    assert load_sanity.CALCULATE_PAYLOADS
    assert load_sanity.BIS_PAYLOADS
    for payload in load_sanity.CALCULATE_PAYLOADS:
        assert payload["champion"]
        assert payload["role"] in {"top", "jungle", "mid", "bottom", "support"}
        assert "enemies" in payload and "allies" in payload
    for payload in load_sanity.BIS_PAYLOADS:
        assert payload["subject_team"] == "main"
        assert payload["slot_kind"] in {"item", "boots"}
        assert payload["objective"]


def test_load_sanity_budgets_and_percentile():
    assert load_sanity._percentile([1.0, 2.0, 3.0, 4.0], 0.95) == 4.0
    assert load_sanity._percentile([], 0.95) == 0.0

    passing = {
        "failures": 0,
        "cache_hit_ratio": 0.99,
        "latencies": {
            "calculate": {"p95": 0.4},
            "bis": {"p95": 2.1},
        },
    }
    assert load_sanity._check_budgets(passing) is True

    slow_calculate = dict(passing)
    slow_calculate["latencies"] = {
        "calculate": {"p95": 2.5},
        "bis": {"p95": 1.0},
    }
    assert load_sanity._check_budgets(slow_calculate) is False

    slow_bis = dict(passing)
    slow_bis["latencies"] = {"calculate": {"p95": 0.5}, "bis": {"p95": 5.1}}
    assert load_sanity._check_budgets(slow_bis) is False

    cold_cache = dict(passing, cache_hit_ratio=0.5)
    assert load_sanity._check_budgets(cold_cache) is False

    failures = dict(passing, failures=3)
    assert load_sanity._check_budgets(failures) is False


def test_load_sanity_user_plan_interleaves_endpoints():
    plan = load_sanity._build_user_plan(2, 4)
    assert len(plan) == 8
    endpoints = {endpoint for endpoint, _payload in plan}
    assert endpoints == {"/api/calculate", "/api/bis"}


# ---------------------------------------------------------------------------
# Docs and environment contract
# ---------------------------------------------------------------------------


def test_backup_runbook_covers_backends_and_retention():
    runbook = Path("docs/backup-runbook.md").read_text(encoding="utf-8")
    for required in (
        "pg_dump",
        ".backup",
        "SAVE",
        "retention",
        "read-only replica",
        "restore",
        "cron",
    ):
        assert required in runbook, required


def test_monitoring_doc_covers_the_five_signals():
    doc = Path("docs/monitoring.md").read_text(encoding="utf-8")
    for required in (
        "error rate",
        "429",
        "BIS p95",
        "cache hit ratio",
        "staleness",
        "/api/health/deep",
        "load_sanity.py",
    ):
        assert required in doc.lower() or required in doc, required


def test_env_example_documents_sentry():
    example = Path(".env.example").read_text(encoding="utf-8")
    assert "SENTRY_DSN=" in example
    assert "SENTRY_ENVIRONMENT=" in example


def test_gitignore_ignores_backup_output():
    ignore = Path(".gitignore").read_text(encoding="utf-8")
    assert "backups/" in ignore
