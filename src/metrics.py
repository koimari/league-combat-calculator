"""Beta success scorecard + PASS/FAIL gate for the Scryglass closed beta.

Runtime home of ``compute_scorecard``: ``GET /api/metrics`` (src/app.py) and
the ``scripts/beta_metrics.py`` CLI both import this module so the endpoint
and the operator CLI share one definition of the gate (see
docs/beta-metrics.md).

The beta succeeds when the four PASS criteria hold across its 2-week run:

- 7-day retention >= 25% (sessions that return within 7 days of their
  first observed activity).
- Validation receipts >= 20 per week.
- The systematic-bias scan flags <= 2 champions (n >= 5 receipts,
  |bias| > 15%).
- No staleness flag older than 72 hours (patch-regression report fresh).

Because auth has no user table, every per-user metric is measured through
the anonymous session id recorded on builds, share links, feedback rows
and metrics events (see docs/beta-metrics.md for the data model).

Gate rule: FAIL = any criterion missed 2 weeks running; the overall gate
is ``pass`` only when every criterion passes, ``pending`` while data is
insufficient or a criterion has a single strike, ``fail`` otherwise.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

from sqlalchemy import select

from src import db

from .beta_gate import (
    _GATE_RULE,
    BETA_WINDOW_DAYS,
    BIAS_FLAGGED_MAX,
    BIAS_MAX_PERCENT,
    BIAS_MIN_RECEIPTS,
    RECEIPTS_PER_WEEK,
    RETENTION_THRESHOLD,
    STALE_MAX_HOURS,
    Window,
    _activity_rows,
    _bias_flagged_count,
    _checked_at_naive,
    _naive_utc,
    _receipt_count,
    _retention_metrics,
    _session_timeline,
    _stale_flag_count,
    _staleness_report,
    _staleness_week,
    _week_windows,
    _weekly_gate,
)

# Resolves to the repo root locally and to the package root in the deployed
# artifact (Vercel package root / Docker ``/app``); ``data/`` ships in every
# deployment shape, so the staleness report default resolves everywhere.
PACKAGE_ROOT = Path(__file__).resolve().parent.parent


# pylint: disable=too-many-locals,too-many-branches,too-many-statements
# The gate composes four independent weekly criteria into one scorecard; the
# verbatim computation is moved from the operator CLI (scripts/beta_metrics.py).


def _source_counts(db_module: Any, window: Window) -> dict[str, int]:
    """Row counts of every persisted source inside the window."""

    def _count_rows(model):
        with db_module.session() as db_session:
            statement = select(model.id).where(
                model.created_at >= window.start, model.created_at <= window.end
            )
            return len(db_session.execute(statement).scalars().all())

    return {
        "builds": _count_rows(db_module.Build),
        "shares": _count_rows(db_module.ShareLink),
        "feedback": _count_rows(db_module.ValidationFeedback),
        "metrics_events": _count_rows(db_module.MetricsEvent),
    }


def _retention_section(
    timeline: Any,
    windows: Sequence[Window],
    beta_start: datetime,
    effective_end: datetime,
    *,
    now: datetime,
) -> tuple[dict, list[dict], str]:
    """The retention criterion: overall metrics, its weekly rows and its gate."""
    overall = _retention_metrics(timeline, beta_start, effective_end, now)
    weeks = []
    for index, (wk_start, wk_end) in enumerate(windows, start=1):
        metrics = _retention_metrics(timeline, wk_start, wk_end, now)
        complete = now >= wk_end
        weeks.append(
            {
                "week": index,
                "complete": complete,
                "status": metrics["status"] if complete else "insufficient_data",
                "value": metrics["value"],
                "numerator": metrics["numerator"],
                "denominator": metrics["denominator"],
            }
        )
    status = overall["status"]
    gate = (
        "pass"
        if status == "pass"
        else "fail" if status == "fail" else "insufficient_data"
    )
    return overall, weeks, gate


def _receipt_weeks(
    db_module: Any, windows: Sequence[Window], now: datetime
) -> list[dict]:
    """Validation receipts per week against ``RECEIPTS_PER_WEEK``."""
    weeks = []
    for index, (wk_start, wk_end) in enumerate(windows, start=1):
        count = _receipt_count(db_module, Window(wk_start, min(now, wk_end)))
        complete = now >= wk_end
        weeks.append(
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
    return weeks


def _bias_weeks(db_module: Any, windows: Sequence[Window], now: datetime) -> list[dict]:
    """Champions the bias scan flags, per week, against ``BIAS_FLAGGED_MAX``."""
    weeks = []
    for index, (_wk_start, wk_end) in enumerate(windows, start=1):
        flagged = _bias_flagged_count(db_module, min(now, wk_end))
        complete = now >= wk_end
        weeks.append(
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
    return weeks


def _staleness_weeks(
    report: dict | None,
    checked_at: datetime | None,
    windows: Sequence[Window],
    now: datetime,
) -> list[dict]:
    """The staleness report's verdict per week."""
    weeks = []
    for index, (wk_start, wk_end) in enumerate(windows, start=1):
        complete = now >= wk_end
        # The final week is judged at the evaluation moment so a report
        # refreshed on the last day is not misread as post-beta.
        week_end = now if index == len(windows) else min(now, wk_end)
        result = _staleness_week(
            report, checked_at, wk_start, wk_end, effective_end=week_end
        )
        weeks.append(
            {
                "week": index,
                "complete": complete,
                "status": result["status"] if complete else "insufficient_data",
                "detail": result["detail"],
            }
        )
    return weeks


def _gate_status(gates: Mapping[str, str], beta_complete: bool) -> str:
    """fail beats pending beats pass; pending until the beta is over."""
    if "fail" in gates.values():
        return "fail"
    if not beta_complete or any(
        status in {"at_risk", "insufficient_data"} for status in gates.values()
    ):
        return "pending"
    return "pass"


def _staleness_detail(
    report: dict | None, checked_at: datetime | None, age_hours: float | None
) -> str:
    """The one-line reading of the staleness report's age."""
    if report is None:
        return "no staleness report on disk"
    if checked_at is None:
        return "staleness report missing checked_at"
    if age_hours is not None and age_hours <= STALE_MAX_HOURS:
        return f"staleness report {age_hours:.1f}h old"
    return f"staleness report {age_hours:.1f}h old (SLA {STALE_MAX_HOURS}h)"


def _cache_context(db_module: Any) -> dict:
    """The result cache's stats, or the reason they are unavailable."""
    try:
        return db_module.cache_stats()
    except Exception:  # pylint: disable=broad-exception-caught
        return {"error": "cache stats unavailable"}


def compute_scorecard(
    *,
    now: datetime | None = None,
    beta_start: datetime | None = None,
    weeks: int = 2,
    staleness_path: str | Path | None = None,
    db_module: ModuleType | None = None,
) -> dict[str, Any]:
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

    beta_window = Window(beta_start, effective_end)
    all_rows = _activity_rows(db_module, beta_window)
    timeline = _session_timeline(all_rows)
    rows_without_id = sum(1 for session_id, _ in all_rows if not session_id)
    source_counts = _source_counts(db_module, beta_window)
    receipts_total = _receipt_count(db_module, beta_window)

    retention_overall, retention_weeks, retention_gate = _retention_section(
        timeline, windows, beta_start, effective_end, now=now
    )
    receipt_weeks = _receipt_weeks(db_module, windows, now)
    bias_weeks = _bias_weeks(db_module, windows, now)
    staleness_weeks = _staleness_weeks(report, checked_at, windows, now)
    gates = {
        "retention": retention_gate,
        "receipts": _weekly_gate(receipt_weeks),
        "bias": _weekly_gate(bias_weeks),
        "staleness": _weekly_gate(staleness_weeks),
    }
    beta_complete = now >= beta_end
    gate_status = _gate_status(gates, beta_complete)

    cache = _cache_context(db_module)
    age_hours = (
        round((now - checked_at).total_seconds() / 3600.0, 2)
        if checked_at is not None
        else None
    )
    missed_weeks = {
        name: sum(1 for week in week_rows if week["status"] == "fail")
        for name, week_rows in (
            ("receipts", receipt_weeks),
            ("bias", bias_weeks),
            ("staleness", staleness_weeks),
        )
    }

    return {
        "generated_at": db.serialize_datetime(now),
        "beta": {
            "start": db.serialize_datetime(beta_start),
            "end": db.serialize_datetime(beta_end),
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
                "status": gates["receipts"],
                "value": receipts_total,
                "threshold": RECEIPTS_PER_WEEK,
                "detail": "validation receipts (delta != NULL) per week",
                "weeks": receipt_weeks,
            },
            "bias": {
                "status": gates["bias"],
                "value": bias_weeks[-1]["flagged"] if bias_weeks else 0,
                "threshold": BIAS_FLAGGED_MAX,
                "detail": (
                    "champions flagged by the systematic-bias scan "
                    f"(n>={BIAS_MIN_RECEIPTS}, |bias| > {BIAS_MAX_PERCENT:.0f}%)"
                ),
                "weeks": bias_weeks,
            },
            "staleness": {
                "status": gates["staleness"],
                "value_hours": age_hours,
                "threshold_hours": STALE_MAX_HOURS,
                "detail": _staleness_detail(report, checked_at, age_hours),
                "report": {
                    "exists": report is not None,
                    "patch": report.get("patch") if report else None,
                    "checked_at": db.serialize_datetime(checked_at),
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
