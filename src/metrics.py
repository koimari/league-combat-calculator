"""Beta success scorecard + PASS/FAIL gate for the Scryglass closed beta.

Runtime home of ``compute_scorecard``: ``GET /api/metrics`` (src/app.py) and
the ``scripts/beta_metrics.py`` CLI both import this module so the endpoint
and the operator CLI share one definition of the gate (see
docs/beta-metrics.md).

The beta succeeds when the four PASS criteria hold across its 2-week run:

- Activation >= 60% of engaged sessions complete champion -> role ->
  Best-next-item in under 10 seconds (``quick_complete`` events).
- 7-day retention >= 25% (sessions that return within 7 days of their
  first observed activity).
- Validation receipts >= 20 per week with the systematic-bias scan keeping
  flagged champions (n >= 5 receipts, |bias| > 15%) at <= 2.
- No staleness flag older than 72 hours (patch-regression report fresh).

Because auth has no user table, every per-user metric is measured through
the anonymous session id recorded on builds, share links, feedback rows
and metrics events (see docs/beta-metrics.md for the data model).

Gate rule: FAIL = any criterion missed 2 weeks running; the overall gate
is ``pass`` only when every criterion passes, ``pending`` while data is
insufficient or a criterion has a single strike, ``fail`` otherwise.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select

import db

# Resolves to the repo root locally and to the package root in the deployed
# artifact (Vercel package root / Docker ``/app``); ``data/`` ships in every
# deployment shape, so the staleness report default resolves everywhere.
PACKAGE_ROOT = Path(__file__).resolve().parent.parent

# Thresholds — the beta success contract (docs/beta-metrics.md).
ACTIVATION_THRESHOLD = 0.60
RETENTION_THRESHOLD = 0.25
RECEIPTS_PER_WEEK = 20
BIAS_FLAGGED_MAX = 2
STALE_MAX_HOURS = 72
QUICK_COMPLETE_MAX_MS = 10_000
RETENTION_WINDOW_DAYS = 7
BETA_WINDOW_DAYS = 14
BIAS_MIN_RECEIPTS = 5
BIAS_MAX_PERCENT = 15.0

_GATE_RULE = (
    "PASS = activation >= 60%, 7-day retention >= 25%, receipts >= 20/week, "
    "no stale > 72h across the 2-week beta; FAIL = any criterion missed "
    "2 weeks running"
)


def _naive_utc(value: datetime | None) -> datetime:
    """Normalize an aware/naive datetime to naive UTC (storage convention)."""
    if value is None:
        return datetime.now(timezone.utc).replace(tzinfo=None)
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _iso(value: datetime | None) -> str | None:
    """Serialize a naive-UTC datetime as an ISO-8601 string with a Z suffix."""
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def _week_windows(beta_start: datetime, weeks: int) -> list[tuple[datetime, datetime]]:
    """Return ``[(start, end), ...]`` for each 7-day week of the beta."""
    return [
        (
            beta_start + timedelta(days=7 * index),
            beta_start + timedelta(days=7 * (index + 1)),
        )
        for index in range(weeks)
    ]


def _activity_rows(
    db_module: Any, start: datetime, end: datetime
) -> list[tuple[str | None, datetime]]:
    """``(session_id, created_at)`` pairs from every instrumented source."""
    rows: list[tuple[str | None, datetime]] = []
    with db_module.session() as db_session:
        for model in (
            db_module.Build,
            db_module.ShareLink,
            db_module.ValidationFeedback,
            db_module.MetricsEvent,
        ):
            statement = select(model.session_id, model.created_at).where(
                model.created_at >= start, model.created_at <= end
            )
            rows.extend(db_session.execute(statement).all())
    return rows


def _quick_complete_rows(
    db_module: Any, start: datetime, end: datetime
) -> list[tuple[str | None, datetime, int | None]]:
    """``(session_id, created_at, took_ms)`` for quick_complete events."""
    with db_module.session() as db_session:
        statement = (
            select(
                db_module.MetricsEvent.session_id,
                db_module.MetricsEvent.created_at,
                db_module.MetricsEvent.took_ms,
            )
            .where(
                db_module.MetricsEvent.event == "quick_complete",
                db_module.MetricsEvent.created_at >= start,
                db_module.MetricsEvent.created_at <= end,
            )
            .order_by(db_module.MetricsEvent.created_at)
        )
        return list(db_session.execute(statement).all())


def _receipt_count(db_module: Any, start: datetime, end: datetime) -> int:
    """Validation receipts (feedback rows carrying a signed delta)."""
    with db_module.session() as db_session:
        statement = select(db_module.ValidationFeedback.id).where(
            db_module.ValidationFeedback.delta.is_not(None),
            db_module.ValidationFeedback.created_at >= start,
            db_module.ValidationFeedback.created_at <= end,
        )
        return len(db_session.execute(statement).scalars().all())


def _bias_flagged_count(db_module: Any, end: datetime) -> int:
    """Champions flagged by the systematic-bias scan (n>=5, |bias|>15%).

    Mirrors ``db.validation_summary`` semantics over every receipt stored up
    to ``end``, so the scorecard can re-derive the flag count at past week
    boundaries instead of only seeing the live state.
    """
    with db_module.session() as db_session:
        rows = db_session.execute(
            select(
                db_module.ValidationFeedback.champion,
                db_module.ValidationFeedback.delta,
                db_module.ValidationFeedback.expected,
            ).where(db_module.ValidationFeedback.created_at <= end)
        ).all()
    by_champion: dict[str, dict[str, float | int]] = {}
    for champion, delta, expected in rows:
        if delta is None:
            continue
        expected_tdd = None
        if isinstance(expected, dict):
            raw = expected.get("tdd")
            if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                expected_tdd = float(raw)
        if expected_tdd is None or expected_tdd <= 0:
            continue
        entry = by_champion.setdefault(champion, {"n": 0, "bias_sum": 0.0})
        entry["n"] += 1
        entry["bias_sum"] += delta / expected_tdd * 100.0
    return sum(
        1
        for entry in by_champion.values()
        if entry["n"] >= BIAS_MIN_RECEIPTS
        and abs(entry["bias_sum"] / entry["n"]) > BIAS_MAX_PERCENT
    )


def _staleness_report(staleness_path: str | Path) -> dict | None:
    """Load the patch-regression report, or None when missing/invalid."""
    path = Path(staleness_path)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (json.JSONDecodeError, OSError):
        return None


def _checked_at_naive(report: dict | None) -> datetime | None:
    """Naive-UTC ``checked_at`` from the report, or None."""
    raw = report.get("checked_at") if isinstance(report, dict) else None
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return _naive_utc(parsed)


def _stale_flag_count(report: dict | None) -> int:
    """Number of champions/items flagged stale in the report."""
    if not isinstance(report, dict):
        return 0
    count = 0
    for section in ("champions", "items"):
        entries = report.get(section)
        if not isinstance(entries, dict):
            continue
        count += sum(
            1
            for entry in entries.values()
            if isinstance(entry, dict) and entry.get("stale")
        )
    return count


def _session_timeline(
    rows: list[tuple[str | None, datetime]],
) -> dict[str, list[datetime]]:
    """Per-session sorted activity timestamps; NULL session ids are dropped."""
    timeline: dict[str, list[datetime]] = {}
    for session_id, created_at in rows:
        if not session_id:
            continue
        timeline.setdefault(session_id, []).append(created_at)
    for stamps in timeline.values():
        stamps.sort()
    return timeline


def _activation_metrics(db_module: Any, start: datetime, end: datetime) -> dict:
    """Activation over one range: quick completions / engaged sessions."""
    all_rows = _activity_rows(db_module, start, end)
    quick_rows = _quick_complete_rows(db_module, start, end)
    sessions = {session_id for session_id, _ in all_rows if session_id}
    quick_sessions = {
        session_id
        for session_id, _, took_ms in quick_rows
        if session_id and took_ms is not None and took_ms < QUICK_COMPLETE_MAX_MS
    }
    denominator = len(sessions)
    numerator = len(quick_sessions & sessions)
    if denominator == 0:
        return {
            "status": "insufficient_data",
            "value": None,
            "numerator": 0,
            "denominator": 0,
            "detail": "no engaged sessions in range",
        }
    value = numerator / denominator
    return {
        "status": "pass" if value >= ACTIVATION_THRESHOLD else "fail",
        "value": round(value, 4),
        "numerator": numerator,
        "denominator": denominator,
        "detail": (
            f"{numerator}/{denominator} sessions completed the funnel in "
            f"< {QUICK_COMPLETE_MAX_MS} ms"
        ),
    }


def _retention_metrics(
    timeline: dict[str, list[datetime]], start: datetime, end: datetime, now: datetime
) -> dict:
    """7-day retention for sessions whose first activity lands in range."""
    cohort = {
        session_id: stamps
        for session_id, stamps in timeline.items()
        if start <= stamps[0] < end
    }
    eligible = {
        session_id: stamps
        for session_id, stamps in cohort.items()
        if now - stamps[0] >= timedelta(days=RETENTION_WINDOW_DAYS)
    }
    if not eligible:
        return {
            "status": "insufficient_data",
            "value": None,
            "numerator": 0,
            "denominator": 0,
            "detail": (
                "no session in range has had 7 days to return yet; "
                "evaluate at beta end"
            ),
        }
    returned = {
        session_id
        for session_id, stamps in eligible.items()
        if any(
            1 <= (later.date() - stamps[0].date()).days <= RETENTION_WINDOW_DAYS
            for later in stamps[1:]
        )
    }
    numerator = len(returned)
    denominator = len(eligible)
    value = numerator / denominator
    return {
        "status": "pass" if value >= RETENTION_THRESHOLD else "fail",
        "value": round(value, 4),
        "numerator": numerator,
        "denominator": denominator,
        "detail": (
            f"{numerator}/{denominator} sessions first active in range returned "
            f"within {RETENTION_WINDOW_DAYS} days"
        ),
    }


def _staleness_week(
    report: dict | None,
    checked_at: datetime | None,
    wk_start: datetime,
    _wk_end: datetime,
    effective_end: datetime,
) -> dict:
    """Staleness verdict for one week window.

    ``effective_end`` is when the week is judged: the nominal week end for
    completed weeks, and ``now`` for the final/current week (the SLA is a
    continuous state — a report refreshed on the beta's last day is fresh
    at evaluation time even if it lands after the nominal week boundary).
    """
    if report is None:
        return {
            "status": "fail",
            "detail": "no staleness report on disk (run patch regression)",
        }
    if checked_at is None:
        return {"status": "fail", "detail": "staleness report missing checked_at"}
    if checked_at > effective_end:
        return {
            "status": "insufficient_data",
            "detail": "staleness check happened after the week ended",
        }
    if checked_at < wk_start:
        return {
            "status": "fail",
            "detail": (
                f"no staleness check during the week "
                f"(report checked {_iso(checked_at)})"
            ),
        }
    age_hours = (effective_end - checked_at).total_seconds() / 3600.0
    if age_hours > STALE_MAX_HOURS:
        return {
            "status": "fail",
            "detail": (
                f"staleness report {age_hours:.1f}h old at week end "
                f"(SLA {STALE_MAX_HOURS}h)"
            ),
        }
    return {
        "status": "pass",
        "detail": f"staleness report {age_hours:.1f}h old at week end",
    }


def _weekly_gate(week_results: list[dict]) -> str:
    """Gate status from per-week results: 2 misses -> fail, 1 -> at_risk.

    Only the last two COMPLETE weeks count (the 2-weeks-running rule); an
    in-progress week is never judged and a single miss is ``at_risk``, not
    yet a gate failure.  When there is no miss, the latest judged week
    decides: a pass passes the criterion even if older weeks lack evidence
    (e.g. a single fresh staleness report), while weeks with no data at
    all leave the criterion ``insufficient_data``.
    """
    judged = [
        result["status"]
        for result in week_results[-2:]
        if result.get("complete") and result["status"] in ("pass", "fail")
    ]
    misses = sum(1 for status in judged if status == "fail")
    if misses >= 2:
        return "fail"
    if misses == 1:
        return "at_risk"
    if judged and judged[-1] == "pass":
        return "pass"
    return "insufficient_data"


# pylint: disable=too-many-locals,too-many-branches,too-many-statements
# The gate composes five independent weekly criteria into one scorecard; the
# verbatim computation is moved from the operator CLI (scripts/beta_metrics.py).
def compute_scorecard(
    *,
    now: datetime | None = None,
    beta_start: datetime | None = None,
    weeks: int = 2,
    staleness_path: str | Path | None = None,
    db_module: Any = None,
) -> dict:
    """Compute the beta scorecard with the PASS/FAIL gate.

    ``now`` defaults to the current UTC time and ``beta_start`` to 14 days
    before it; both are normalized to naive UTC.  ``staleness_path``
    defaults to ``data/staleness.json`` (what ``/api/staleness`` serves).
    ``db_module`` exists so tests can inject the isolated SQLite-backed
    module; production callers omit it.
    """
    db_module = db_module or db
    now = _naive_utc(now)
    beta_start = (
        _naive_utc(beta_start)
        if beta_start is not None
        else now - timedelta(days=BETA_WINDOW_DAYS)
    )
    weeks = max(1, int(weeks))
    beta_end = beta_start + timedelta(days=7 * weeks)
    effective_end = min(now, beta_end)
    windows = _week_windows(beta_start, weeks)
    report_path = (
        Path(staleness_path)
        if staleness_path is not None
        else PACKAGE_ROOT / "data" / "staleness.json"
    )
    report = _staleness_report(report_path)
    checked_at = _checked_at_naive(report)

    # --- data sources -----------------------------------------------------
    all_rows = _activity_rows(db_module, beta_start, effective_end)
    timeline = _session_timeline(all_rows)
    rows_without_id = sum(1 for session_id, _ in all_rows if not session_id)

    def _count_rows(model, start, end):
        with db_module.session() as db_session:
            statement = select(model.id).where(
                model.created_at >= start, model.created_at <= end
            )
            return len(db_session.execute(statement).scalars().all())

    source_counts = {
        "builds": _count_rows(db_module.Build, beta_start, effective_end),
        "shares": _count_rows(db_module.ShareLink, beta_start, effective_end),
        "feedback": _count_rows(
            db_module.ValidationFeedback, beta_start, effective_end
        ),
        "metrics_events": _count_rows(
            db_module.MetricsEvent, beta_start, effective_end
        ),
    }
    receipts_total = _receipt_count(db_module, beta_start, effective_end)

    # --- activation -------------------------------------------------------
    activation_overall = _activation_metrics(db_module, beta_start, effective_end)
    activation_weeks = []
    for index, (wk_start, wk_end) in enumerate(windows, start=1):
        wk_end_eff = min(now, wk_end)
        metrics = _activation_metrics(db_module, wk_start, wk_end_eff)
        complete = now >= wk_end
        activation_weeks.append(
            {
                "week": index,
                "complete": complete,
                "status": metrics["status"] if complete else "insufficient_data",
                "value": metrics["value"],
                "numerator": metrics["numerator"],
                "denominator": metrics["denominator"],
            }
        )
    activation_gate = _weekly_gate(activation_weeks)

    # --- retention --------------------------------------------------------
    retention_overall = _retention_metrics(timeline, beta_start, effective_end, now)
    retention_weeks = []
    for index, (wk_start, wk_end) in enumerate(windows, start=1):
        metrics = _retention_metrics(timeline, wk_start, wk_end, now)
        complete = now >= wk_end
        retention_weeks.append(
            {
                "week": index,
                "complete": complete,
                "status": metrics["status"] if complete else "insufficient_data",
                "value": metrics["value"],
                "numerator": metrics["numerator"],
                "denominator": metrics["denominator"],
            }
        )
    retention_status = retention_overall["status"]
    retention_gate = (
        "pass"
        if retention_status == "pass"
        else "fail" if retention_status == "fail" else "insufficient_data"
    )

    # --- receipts ---------------------------------------------------------
    receipt_weeks = []
    for index, (wk_start, wk_end) in enumerate(windows, start=1):
        wk_end_eff = min(now, wk_end)
        count = _receipt_count(db_module, wk_start, wk_end_eff)
        complete = now >= wk_end
        receipt_weeks.append(
            {
                "week": index,
                "complete": complete,
                "count": count,
                "status": (
                    ("pass" if count >= RECEIPTS_PER_WEEK else "fail")
                    if complete
                    else "insufficient_data"
                ),
            }
        )
    receipts_gate = _weekly_gate(receipt_weeks)

    # --- bias -------------------------------------------------------------
    bias_weeks = []
    for index, (wk_start, wk_end) in enumerate(windows, start=1):
        wk_end_eff = min(now, wk_end)
        flagged = _bias_flagged_count(db_module, wk_end_eff)
        complete = now >= wk_end
        bias_weeks.append(
            {
                "week": index,
                "complete": complete,
                "flagged": flagged,
                "status": (
                    ("pass" if flagged <= BIAS_FLAGGED_MAX else "fail")
                    if complete
                    else "insufficient_data"
                ),
            }
        )
    bias_current = bias_weeks[-1]["flagged"] if bias_weeks else 0
    bias_gate = _weekly_gate(bias_weeks)

    # --- staleness --------------------------------------------------------
    staleness_weeks = []
    for index, (wk_start, wk_end) in enumerate(windows, start=1):
        complete = now >= wk_end
        # The final week is judged at the evaluation moment so a report
        # refreshed on the last day is not misread as post-beta.
        week_end = now if index == len(windows) else min(now, wk_end)
        result = _staleness_week(report, checked_at, wk_start, wk_end, week_end)
        staleness_weeks.append(
            {
                "week": index,
                "complete": complete,
                "status": result["status"] if complete else "insufficient_data",
                "detail": result["detail"],
            }
        )
    staleness_gate = _weekly_gate(staleness_weeks)

    # --- overall gate -----------------------------------------------------
    beta_complete = now >= beta_end
    gates = {
        "activation": activation_gate,
        "retention": retention_gate,
        "receipts": receipts_gate,
        "bias": bias_gate,
        "staleness": staleness_gate,
    }
    if "fail" in gates.values():
        gate_status = "fail"
    elif not beta_complete or any(
        status in {"at_risk", "insufficient_data"} for status in gates.values()
    ):
        gate_status = "pending"
    else:
        gate_status = "pass"

    # --- cache context ----------------------------------------------------
    cache = {}
    try:
        cache = db_module.cache_stats()
    except Exception:  # pylint: disable=broad-exception-caught
        cache = {"error": "cache stats unavailable"}

    age_hours = (
        round((now - checked_at).total_seconds() / 3600.0, 2)
        if checked_at is not None
        else None
    )
    if report is None:
        staleness_current_detail = "no staleness report on disk"
    elif checked_at is None:
        staleness_current_detail = "staleness report missing checked_at"
    elif age_hours is not None and age_hours <= STALE_MAX_HOURS:
        staleness_current_detail = f"staleness report {age_hours:.1f}h old"
    else:
        staleness_current_detail = (
            f"staleness report {age_hours:.1f}h old (SLA {STALE_MAX_HOURS}h)"
        )

    missed_weeks = {
        name: (
            sum(1 for week in activation_weeks if week["status"] == "fail")
            if name == "activation"
            else (
                sum(1 for week in receipt_weeks if week["status"] == "fail")
                if name == "receipts"
                else (
                    sum(1 for week in bias_weeks if week["status"] == "fail")
                    if name == "bias"
                    else sum(1 for week in staleness_weeks if week["status"] == "fail")
                )
            )
        )
        for name in ("activation", "receipts", "bias", "staleness")
    }

    scorecard = {
        "generated_at": _iso(now),
        "beta": {
            "start": _iso(beta_start),
            "end": _iso(beta_end),
            "weeks": weeks,
            "window_days": 7 * weeks,
            "complete": beta_complete,
        },
        "data_sources": {
            "sessions_observed": len(timeline),
            "sessions_without_id": rows_without_id,
            **source_counts,
            "receipts": receipts_total,
            "cache": cache,
        },
        "criteria": {
            "activation": {
                "status": activation_gate,
                "value": activation_overall["value"],
                "threshold": ACTIVATION_THRESHOLD,
                "numerator": activation_overall["numerator"],
                "denominator": activation_overall["denominator"],
                "detail": activation_overall["detail"],
                "weeks": activation_weeks,
            },
            "retention": {
                "status": retention_gate,
                "value": retention_overall["value"],
                "threshold": RETENTION_THRESHOLD,
                "numerator": retention_overall["numerator"],
                "denominator": retention_overall["denominator"],
                "detail": retention_overall["detail"],
                "weeks": retention_weeks,
            },
            "receipts": {
                "status": receipts_gate,
                "value": receipts_total,
                "threshold": RECEIPTS_PER_WEEK,
                "detail": "validation receipts (delta != NULL) per week",
                "weeks": receipt_weeks,
            },
            "bias": {
                "status": bias_gate,
                "value": bias_current,
                "threshold": BIAS_FLAGGED_MAX,
                "detail": (
                    "champions flagged by the systematic-bias scan "
                    f"(n>={BIAS_MIN_RECEIPTS}, |bias| > {BIAS_MAX_PERCENT:.0f}%)"
                ),
                "weeks": bias_weeks,
            },
            "staleness": {
                "status": staleness_gate,
                "value_hours": age_hours,
                "threshold_hours": STALE_MAX_HOURS,
                "detail": staleness_current_detail,
                "report": {
                    "exists": report is not None,
                    "patch": report.get("patch") if report else None,
                    "checked_at": _iso(checked_at),
                    "age_hours": age_hours,
                    "stale_flags": _stale_flag_count(report),
                },
                "weeks": staleness_weeks,
            },
        },
        "gate": {
            "status": gate_status,
            "rule": _GATE_RULE,
            "missed_weeks": missed_weeks,
            "verdict": {
                "pass": "PASS",
                "pending": "PENDING",
                "fail": "FAIL",
            }[gate_status],
        },
    }
    return scorecard
