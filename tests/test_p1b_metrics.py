"""P1b beta-metrics contract tests.

Covers the anonymous funnel-event capture (POST /api/metrics/event), the
auth-gated scorecard endpoint (GET /api/metrics), the anonymous session id
recorded on builds/share links/feedback, the scorecard computation over
seeded rows, the 2-weeks-running PASS/FAIL gate, the schema backfill for
pre-existing databases, and the CLI's ``--json`` dashboard output.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import src.app as app_module

# The app imports its persistence layer as the top-level ``db`` module (src/
# is placed on sys.path by app.py), so tests reuse that same module instance.
import db

ROOT = Path(__file__).parents[1]

# Fixed beta timeline: 2 complete weeks, UTC-naive (storage convention).
BETA_START = datetime(2026, 7, 23, 0, 0, 0)
BETA_END = BETA_START + timedelta(days=14)
NOW = BETA_END
DAY = timedelta(days=1)
WEEK = timedelta(days=7)


@pytest.fixture
def sqlite_database(tmp_path, monkeypatch):
    """Point the app at an isolated SQLite file and reset the engine."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'p1b.sqlite3'}")
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


# ---------------------------------------------------------------------------
# Seeding helpers (direct ORM inserts with explicit timestamps)
# ---------------------------------------------------------------------------


def _add_build(db_module, session_id, created_at):
    with db_module.session() as s:
        s.add(
            db_module.Build(
                champion="Ahri",
                level=18,
                role="mid",
                items=[],
                item_options={},
                ability_ranks={},
                champion_options={},
                enemies=[],
                allies=[],
                fight_params={},
                session_id=session_id,
                created_at=created_at,
            )
        )
        s.commit()


def _add_share(db_module, session_id, build_id, created_at):
    with db_module.session() as s:
        s.add(
            db_module.ShareLink(
                token=db_module._generate_token(),
                build_id=build_id,
                slug=None,
                session_id=session_id,
                created_at=created_at,
            )
        )
        s.commit()


def _add_receipt(db_module, session_id, champion, delta, created_at, tdd=1000.0):
    with db_module.session() as s:
        s.add(
            db_module.ValidationFeedback(
                champion=champion,
                loadout={},
                expected={"tdd": tdd},
                actual={"tdd": tdd + delta},
                source="manual",
                matched=True,
                delta=delta,
                note=None,
                session_id=session_id,
                created_at=created_at,
            )
        )
        s.commit()


def _add_event(db_module, session_id, took_ms, created_at, event="quick_complete"):
    with db_module.session() as s:
        s.add(
            db_module.MetricsEvent(
                event=event,
                session_id=session_id,
                took_ms=took_ms,
                payload={},
                created_at=created_at,
            )
        )
        s.commit()


def _write_staleness_report(path, checked_at, patch="16.15"):
    """Write a minimal patch-regression report at an explicit checked_at."""
    Path(path).write_text(
        json.dumps(
            {
                "patch": patch,
                "checked_at": checked_at.replace(tzinfo=timezone.utc).isoformat(),
                "champions": {"Ahri": {"stale": False}},
                "items": {},
            }
        ),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Event recording
# ---------------------------------------------------------------------------


def test_metrics_event_records_and_mints_anon_session(sqlite_database):
    client = _client()
    first = client.post(
        "/api/metrics/event", json={"event": "quick_complete", "took_ms": 500}
    )
    assert first.status_code == 201
    body = first.get_json()
    assert isinstance(body["event_id"], int)
    assert body["event"] == "quick_complete"

    # The anonymous session cookie was minted and persists across requests.
    anon_cookie = client.get_cookie("scryglass_anon")
    assert anon_cookie is not None
    anon = anon_cookie.value
    assert len(anon) >= 20

    second = client.post(
        "/api/metrics/event", json={"event": "quick_complete", "took_ms": 900}
    )
    assert second.status_code == 201

    events = db.list_metric_events()
    assert len(events) == 2
    assert {row["took_ms"] for row in events} == {500, 900}
    assert {row["session_id"] for row in events} == {anon}
    assert all(row["event"] == "quick_complete" for row in events)


def test_metrics_event_validation(sqlite_database):
    client = _client()
    cases = [
        ({"event": "nope", "took_ms": 10}, "event must be one of"),
        ({"took_ms": 10}, "event is required"),
        ({"event": "quick_complete", "took_ms": "fast"}, "took_ms must be an integer"),
        ({"event": "quick_complete", "took_ms": -1}, "took_ms must be between"),
        ({"event": "quick_complete", "took_ms": 3_600_001}, "took_ms must be between"),
        ({}, "event is required"),
    ]
    for payload, fragment in cases:
        response = client.post("/api/metrics/event", json=payload)
        assert response.status_code == 400, payload
        assert fragment in response.get_json()["error"], payload
    assert client.post("/api/metrics/event", data="not json").status_code == 400


def test_metrics_event_rate_limited(sqlite_database, monkeypatch):
    """The funnel endpoint shares the token-bucket guard like every API."""

    class Denied:
        @staticmethod
        def consume(scope, *, capacity, refill_per_second, now=None):
            assert scope == "metrics_event"
            return False, 7.0

    class Allowed:
        @staticmethod
        def consume(scope, *, capacity, refill_per_second, now=None):
            return True, 0.0

    monkeypatch.setattr(app_module, "_rate_limiter", Denied())
    app_module.app.config["TESTING"] = False
    app_module.app.config["RATE_LIMIT_ENABLED"] = True
    client = _client()
    denied = client.post(
        "/api/metrics/event", json={"event": "quick_complete", "took_ms": 100}
    )
    assert denied.status_code == 429
    assert denied.headers["Retry-After"] == "7"
    assert "Metrics is busy" in denied.get_json()["error"]

    monkeypatch.setattr(app_module, "_rate_limiter", Allowed())
    allowed = client.post(
        "/api/metrics/event", json={"event": "quick_complete", "took_ms": 100}
    )
    assert allowed.status_code == 201


# ---------------------------------------------------------------------------
# Anonymous (pre-auth) event capture + auth-gated scorecard
# ---------------------------------------------------------------------------


def _test_password_hash(password="secret"):
    import base64
    import hashlib

    salt = b"p1b-invite-salt"
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16_384, r=8, p=1)
    enc = lambda value: base64.urlsafe_b64encode(value).rstrip(b"=").decode()
    return f"scrypt$16384$8$1${enc(salt)}${enc(digest)}"


@pytest.fixture
def invite_env(monkeypatch):
    """Auth gate on, exactly like the production closed beta."""
    monkeypatch.setenv("SCRYGLASS_AUTH_REQUIRED", "1")
    monkeypatch.setenv("SCRYGLASS_AUTH_SECRET", "p1b-metrics-secret")
    monkeypatch.setenv(
        "SCRYGLASS_AUTH_USERS",
        json.dumps({"BetaResearcher": _test_password_hash()}),
    )
    monkeypatch.setenv("SCRYGLASS_INVITE_CODES", "BETA-2026")
    return app_module


def test_metrics_event_is_pre_auth(invite_env, sqlite_database):
    """Funnel events must be collectable without an approved session."""
    client = _client()
    response = client.post(
        "/api/metrics/event", json={"event": "quick_complete", "took_ms": 250}
    )
    assert response.status_code == 201
    assert len(db.list_metric_events()) == 1


def test_metrics_scorecard_is_auth_gated(invite_env, sqlite_database):
    client = _client()
    anonymous = client.get("/api/metrics")
    assert anonymous.status_code == 302
    assert "/auth/login" in anonymous.headers["Location"]

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

    scorecard = client.get("/api/metrics")
    assert scorecard.status_code == 200
    body = scorecard.get_json()
    assert set(body) >= {"generated_at", "beta", "criteria", "gate"}
    assert set(body["criteria"]) == {
        "activation",
        "retention",
        "receipts",
        "bias",
        "staleness",
    }
    assert body["gate"]["status"] in {"pass", "pending", "fail"}


# ---------------------------------------------------------------------------
# Anonymous session id on product rows
# ---------------------------------------------------------------------------


def test_session_id_recorded_on_build_share_and_receipt(sqlite_database):
    client = _client()

    # The first product write mints the anon session cookie.
    build = client.post(
        "/api/builds",
        json={"champion": "Ahri", "level": 18, "items": []},
    )
    assert build.status_code == 201
    build_id = build.get_json()["build_id"]
    anon = client.get_cookie("scryglass_anon").value

    with db.session() as s:
        stored = s.get(db.Build, build_id)
        assert stored.session_id == anon

    share = client.post("/api/share", json={"build_id": build_id})
    assert share.status_code == 201
    token = share.get_json()["token"]
    with db.session() as s:
        share_row = s.execute(
            db.select(db.ShareLink).where(db.ShareLink.token == token)
        ).scalar_one()
        assert share_row.session_id == anon

    receipt = client.post(
        "/api/receipts",
        json={
            "champion": "Ahri",
            "loadout": {
                "champion": "Ahri",
                "level": 18,
                "items": ["Liandry's Torment", "Shadowflame"],
                "ability_ranks": {"Q": 5, "W": 3, "E": 3, "R": 2},
            },
            "observed": {"tdd": 0},
        },
    )
    # The prediction path runs the full engine; the session id is what we
    # assert, so tolerate any valid receipt outcome (matched or not).
    assert receipt.status_code == 201
    feedback_id = receipt.get_json()["feedback_id"]
    with db.session() as s:
        feedback = s.get(db.ValidationFeedback, feedback_id)
        assert feedback.session_id == anon


# ---------------------------------------------------------------------------
# Scorecard computation from seeded rows
# ---------------------------------------------------------------------------


def _seed_pass_scenario(db_module, tmp_path):
    """A beta that clears every criterion: gate PASS."""
    # 10 engaged sessions; 7 complete the funnel under 10s in each week.
    for index in range(1, 11):
        session = f"session-{index:02d}"
        _add_build(db_module, session, BETA_START + 2 * DAY)  # week 1 activity
        _add_build(db_module, session, BETA_START + 10 * DAY)  # week 2 activity
        if index <= 7:
            _add_event(db_module, session, 3_000, BETA_START + 2 * DAY)
            _add_event(db_module, session, 4_000, BETA_START + 10 * DAY)
        elif index == 8:
            # too slow to count toward the funnel
            _add_event(db_module, session, 15_000, BETA_START + 2 * DAY)
    # Retention: sessions 1-5 return within 7 days of first activity.
    for index in range(1, 6):
        _add_build(db_module, f"session-{index:02d}", BETA_START + 4 * DAY)
    # Receipts: 25 in week 1, 22 in week 2 (all small-bias except Zed).
    # Week-1 receipts come only from sessions 1-5 (the returners) at days
    # 3-6, and week-2 receipts from every session at days 10-13, so no
    # receipt creates an artificial "return" for sessions 6-10.
    for offset in range(25):
        day = BETA_START + 3 * DAY + (offset % 4) * DAY
        champion = "Zed" if offset < 5 else "Ahri" if offset < 10 else "Orianna"
        delta = 200.0 if champion == "Zed" else 50.0
        session = f"session-{offset % 5 + 1:02d}"
        _add_receipt(db_module, session, champion, delta, day)
    for offset in range(22):
        day = BETA_START + 10 * DAY + (offset % 4) * DAY
        champion = "Zed" if offset < 5 else "Ahri" if offset < 10 else "Orianna"
        delta = 200.0 if champion == "Zed" else 50.0
        session = f"session-{offset % 10 + 1:02d}"
        _add_receipt(db_module, session, champion, delta, day)
    _write_staleness_report(tmp_path / "staleness.json", NOW - DAY)
    return tmp_path / "staleness.json"


def test_scorecard_pass_gate_from_seeded_rows(sqlite_database, tmp_path):
    report = _seed_pass_scenario(db, tmp_path)
    scorecard = __import__("metrics", fromlist=["compute_scorecard"]).compute_scorecard(
        now=NOW, beta_start=BETA_START, weeks=2, staleness_path=report
    )

    assert scorecard["beta"]["complete"] is True
    assert scorecard["data_sources"]["sessions_observed"] == 10
    assert scorecard["data_sources"]["receipts"] == 47

    activation = scorecard["criteria"]["activation"]
    assert activation["status"] == "pass"
    assert activation["value"] == pytest.approx(0.70)
    assert activation["numerator"] == 7
    assert activation["denominator"] == 10
    assert [w["status"] for w in activation["weeks"]] == ["pass", "pass"]

    retention = scorecard["criteria"]["retention"]
    assert retention["status"] == "pass"
    assert retention["value"] == pytest.approx(0.50)
    assert retention["numerator"] == 5
    assert retention["denominator"] == 10

    receipts = scorecard["criteria"]["receipts"]
    assert receipts["status"] == "pass"
    assert [w["count"] for w in receipts["weeks"]] == [25, 22]
    assert all(w["status"] == "pass" for w in receipts["weeks"])

    bias = scorecard["criteria"]["bias"]
    assert bias["status"] == "pass"
    assert bias["value"] == 1  # Zed only: n>=5 with |bias|>15%
    assert all(w["status"] == "pass" for w in bias["weeks"])

    staleness = scorecard["criteria"]["staleness"]
    assert staleness["status"] == "pass"
    assert staleness["value_hours"] == pytest.approx(24.0)
    assert staleness["report"]["exists"] is True
    assert staleness["report"]["patch"] == "16.15"

    assert scorecard["gate"]["status"] == "pass"
    assert scorecard["gate"]["verdict"] == "PASS"
    assert scorecard["gate"]["missed_weeks"] == {
        "activation": 0,
        "receipts": 0,
        "bias": 0,
        "staleness": 0,
    }


def test_scorecard_fail_gate_two_weeks_running(sqlite_database, tmp_path):
    """Every hard criterion missed in BOTH weeks -> gate FAIL."""
    # 10 sessions, only 4 quick completions per week (40% < 60%).
    for index in range(1, 11):
        session = f"session-{index:02d}"
        _add_build(db_module=db, session_id=session, created_at=BETA_START + 2 * DAY)
        _add_build(db_module=db, session_id=session, created_at=BETA_START + 10 * DAY)
        if index <= 4:
            _add_event(db, session, 2_000, BETA_START + 2 * DAY)
            _add_event(db, session, 2_000, BETA_START + 10 * DAY)
    # Retention: only one session returns within 7 days.
    _add_build(db, "session-01", BETA_START + 4 * DAY)
    # Receipts: 10 in week 2 only (below the 20/week floor in both weeks;
    # week 1 has zero).  Placed at days 10-13 so no receipt creates an
    # artificial same-week "return" for the retention cohort.
    for offset in range(10):
        day = BETA_START + 10 * DAY + (offset % 4) * DAY
        session = f"session-{offset % 10 + 1:02d}"
        _add_receipt(db, session, "Zed", 200.0, day)
    # Staleness: report predates the beta -> no check in either week.
    report = tmp_path / "staleness.json"
    _write_staleness_report(report, BETA_START - 3 * DAY)

    scorecard = __import__("metrics", fromlist=["compute_scorecard"]).compute_scorecard(
        now=NOW, beta_start=BETA_START, weeks=2, staleness_path=report
    )
    criteria = scorecard["criteria"]
    assert criteria["activation"]["status"] == "fail"
    assert criteria["retention"]["status"] == "fail"
    assert criteria["receipts"]["status"] == "fail"
    assert criteria["staleness"]["status"] == "fail"
    assert criteria["bias"]["status"] == "pass"  # 1 flagged champion <= 2

    assert scorecard["gate"]["status"] == "fail"
    assert scorecard["gate"]["verdict"] == "FAIL"
    assert scorecard["gate"]["missed_weeks"] == {
        "activation": 2,
        "receipts": 2,
        "bias": 0,
        "staleness": 2,
    }


def test_scorecard_pending_on_single_week_miss(sqlite_database, tmp_path):
    """One missed week is at_risk/pending, not FAIL (2-weeks-running rule)."""
    for index in range(1, 11):
        session = f"session-{index:02d}"
        _add_build(db, session, BETA_START + 2 * DAY)
        _add_build(db, session, BETA_START + 10 * DAY)
        # week 1: 8/10 quick; week 2: 4/10 quick
        week1_quick = index <= 8
        week2_quick = index <= 4
        if week1_quick:
            _add_event(db, session, 2_000, BETA_START + 2 * DAY)
        if week2_quick:
            _add_event(db, session, 2_000, BETA_START + 10 * DAY)
    # Retention passes (5/10).
    for index in range(1, 6):
        _add_build(db, f"session-{index:02d}", BETA_START + 4 * DAY)
    # Receipts: 25 in week 1 (days 0-6), 5 in week 2 (days 7-10), all from
    # existing sessions.
    for offset in range(25):
        _add_receipt(
            db,
            f"session-{offset % 10 + 1:02d}",
            "Orianna",
            30.0,
            BETA_START + (offset % 7) * DAY,
        )
    for offset in range(5):
        _add_receipt(
            db,
            f"session-{offset % 10 + 1:02d}",
            "Orianna",
            30.0,
            BETA_START + 7 * DAY + (offset % 4) * DAY,
        )
    report = tmp_path / "staleness.json"
    _write_staleness_report(report, NOW - DAY)

    scorecard = __import__("metrics", fromlist=["compute_scorecard"]).compute_scorecard(
        now=NOW, beta_start=BETA_START, weeks=2, staleness_path=report
    )
    assert scorecard["criteria"]["activation"]["status"] == "at_risk"
    assert scorecard["criteria"]["receipts"]["status"] == "at_risk"
    assert scorecard["criteria"]["retention"]["status"] == "pass"
    assert scorecard["criteria"]["staleness"]["status"] == "pass"
    assert scorecard["gate"]["status"] == "pending"
    assert scorecard["gate"]["verdict"] == "PENDING"


def test_scorecard_pending_while_beta_in_progress(sqlite_database, tmp_path):
    """Mid-beta the gate stays pending; in-progress weeks are not judged."""
    now = BETA_START + 9 * DAY  # week 2 is only 2 days old
    for index in range(1, 11):
        _add_build(db, f"session-{index:02d}", BETA_START + 2 * DAY)
        if index <= 8:
            _add_event(db, f"session-{index:02d}", 2_000, BETA_START + 2 * DAY)
    for offset in range(25):
        _add_receipt(
            db,
            f"session-{offset % 10 + 1:02d}",
            "Orianna",
            30.0,
            BETA_START + (offset % 7) * DAY,
        )
    report = tmp_path / "staleness.json"
    _write_staleness_report(report, now - timedelta(hours=6))

    scorecard = __import__("metrics", fromlist=["compute_scorecard"]).compute_scorecard(
        now=now, beta_start=BETA_START, weeks=2, staleness_path=report
    )
    assert scorecard["beta"]["complete"] is False
    # Week 1 (complete) judged; week 2 (in progress) never judged.
    weeks = scorecard["criteria"]["receipts"]["weeks"]
    assert weeks[0] == {"week": 1, "complete": True, "count": 25, "status": "pass"}
    assert weeks[1]["complete"] is False
    assert weeks[1]["status"] == "insufficient_data"
    assert scorecard["gate"]["status"] == "pending"


def test_scorecard_retention_insufficient_until_7_days_elapse(
    sqlite_database, tmp_path
):
    """A session that first appears < 7 days ago cannot be judged yet."""
    now = BETA_START + 8 * DAY
    _add_build(db, "brand-new", now - 2 * DAY)
    _add_build(db, "early-bird", BETA_START + 1 * DAY)
    _add_build(db, "early-bird", BETA_START + 3 * DAY)  # returned within 7d
    report = tmp_path / "staleness.json"
    _write_staleness_report(report, now - timedelta(hours=6))

    scorecard = __import__("metrics", fromlist=["compute_scorecard"]).compute_scorecard(
        now=now, beta_start=BETA_START, weeks=2, staleness_path=report
    )
    retention = scorecard["criteria"]["retention"]
    assert retention["numerator"] == 1
    assert retention["denominator"] == 1  # only the eligible session
    assert retention["value"] == pytest.approx(1.0)
    assert retention["status"] == "pass"


def test_scorecard_activation_ten_second_boundary(sqlite_database, tmp_path):
    """took_ms < 10000 counts; took_ms >= 10000 does not."""
    _add_build(db, "fast", BETA_START + 1 * DAY)
    _add_build(db, "slow", BETA_START + 1 * DAY)
    _add_event(db, "fast", 9_999, BETA_START + 1 * DAY)
    _add_event(db, "slow", 10_000, BETA_START + 1 * DAY)
    report = tmp_path / "staleness.json"
    _write_staleness_report(report, NOW - timedelta(hours=6))

    scorecard = __import__("metrics", fromlist=["compute_scorecard"]).compute_scorecard(
        now=NOW, beta_start=BETA_START, weeks=2, staleness_path=report
    )
    activation = scorecard["criteria"]["activation"]
    assert activation["numerator"] == 1
    assert activation["denominator"] == 2
    assert activation["value"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Schema backfill for pre-existing databases
# ---------------------------------------------------------------------------


def test_metrics_schema_backfills_preexisting_tables(
    sqlite_database, monkeypatch, tmp_path
):
    """A database created before P1b gains session_id columns via ALTER."""
    import sqlalchemy as sa

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'legacy.sqlite3'}")
    db.reset()
    legacy = sa.create_engine(os.environ["DATABASE_URL"], future=True)
    with legacy.begin() as conn:
        conn.execute(
            sa.text(
                "CREATE TABLE builds (id INTEGER PRIMARY KEY, champion VARCHAR(100))"
            )
        )
        conn.execute(sa.text("CREATE TABLE share_links (id INTEGER PRIMARY KEY)"))
        conn.execute(
            sa.text("CREATE TABLE validation_feedback (id INTEGER PRIMARY KEY)")
        )
        conn.execute(sa.text("CREATE TABLE cached_results (id INTEGER PRIMARY KEY)"))
        conn.execute(sa.text("CREATE TABLE cache_counters (id INTEGER PRIMARY KEY)"))
        conn.execute(sa.text("CREATE TABLE staleness_state (id INTEGER PRIMARY KEY)"))

    engine = db.get_engine()
    inspector = sa.inspect(engine)
    for table in ("builds", "share_links", "validation_feedback"):
        columns = {column["name"] for column in inspector.get_columns(table)}
        assert "session_id" in columns, table
    assert "metrics_events" in inspector.get_table_names()

    # Re-running stays idempotent.
    db._ensure_metrics_schema(engine)
    db.reset()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_beta_metrics_cli_json(sqlite_database, tmp_path):
    report = _seed_pass_scenario(db, tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "beta_metrics.py"),
            "--json",
            "--now",
            NOW.isoformat(),
            "--beta-start",
            BETA_START.isoformat(),
            "--staleness-report",
            str(report),
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "DATABASE_URL": os.environ["DATABASE_URL"]},
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["gate"]["status"] == "pass"
    assert payload["criteria"]["activation"]["value"] == pytest.approx(0.70)

    # A failing gate exits non-zero so dashboards/CI can react.  Seed the
    # two-weeks-running FAIL scenario (its own stale report is written by
    # the helper into tmp_path) and re-run against the same database.
    fail_db = db
    for index in range(1, 11):
        session = f"session-{index:02d}"
        _add_build(fail_db, session, BETA_START + 2 * DAY)
        _add_build(fail_db, session, BETA_START + 10 * DAY)
        if index <= 4:
            _add_event(fail_db, session, 2_000, BETA_START + 2 * DAY)
            _add_event(fail_db, session, 2_000, BETA_START + 10 * DAY)
    _add_build(fail_db, "session-01", BETA_START + 4 * DAY)
    for offset in range(10):
        _add_receipt(
            fail_db,
            f"session-{offset % 10 + 1:02d}",
            "Zed",
            200.0,
            BETA_START + 10 * DAY + (offset % 4) * DAY,
        )
    stale_report = tmp_path / "staleness-fail.json"
    _write_staleness_report(stale_report, BETA_START - 3 * DAY)
    failing = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "beta_metrics.py"),
            "--json",
            "--now",
            NOW.isoformat(),
            "--beta-start",
            BETA_START.isoformat(),
            "--staleness-report",
            str(stale_report),
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "DATABASE_URL": os.environ["DATABASE_URL"]},
    )
    assert failing.returncode == 1
    assert json.loads(failing.stdout)["gate"]["verdict"] == "FAIL"


# ---------------------------------------------------------------------------
# Docs
# ---------------------------------------------------------------------------


def test_beta_metrics_docs_exist():
    doc = ROOT / "docs" / "beta-metrics.md"
    assert doc.exists(), "docs/beta-metrics.md is required (P1b deliverable)"
    text = doc.read_text(encoding="utf-8")
    for required in (
        "60%",
        "25%",
        "20",
        "72",
        "quick_complete",
        "metrics_events",
        "session_id",
    ):
        assert required in text, required

    schema_doc = ROOT / "docs" / "database-schema.md"
    assert schema_doc.exists()
    assert "metrics_events" in schema_doc.read_text(encoding="utf-8")
