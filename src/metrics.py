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

import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

from sqlalchemy import select

from src import db

# Resolves to the repo root locally and to the package root in the deployed
# artifact (Vercel package root / Docker ``/app``); ``data/`` ships in every
# deployment shape, so the staleness report default resolves everywhere.
PACKAGE_ROOT = Path(__file__).resolve().parent.parent

# Thresholds — the beta success contract (docs/beta-metrics.md).
RETENTION_THRESHOLD = 0.25
RECEIPTS_PER_WEEK = 20
BIAS_FLAGGED_MAX = 2
STALE_MAX_HOURS = 72
RETENTION_WINDOW_DAYS = 7
BETA_WINDOW_DAYS = 14
BIAS_MIN_RECEIPTS = 5
BIAS_MAX_PERCENT = 15.0

_GATE_RULE = (
    "PASS = 7-day retention >= 25%, receipts >= 20/week, <= 2 champions "
    "flagged by the bias scan, no stale > 72h across the 2-week beta; "
    "FAIL = any criterion missed 2 weeks running"
)


def _naive_utc(value: datetime | None) -> datetime:
    """Normalize an aware/naive datetime to naive UTC (storage convention)."""
    if value is None:
        return datetime.now(UTC).replace(tzinfo=None)
    if value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


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
        with Path(path).open(encoding="utf-8") as handle:
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
    rows: Iterable[tuple[str | None, datetime]],
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


def _retention_metrics(
    timeline: Mapping[str, list[datetime]],
    start: datetime,
    end: datetime,
    now: datetime,
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
    *,
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
                f"(report checked {db.serialize_datetime(checked_at)})"
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


def _weekly_gate(week_results: Sequence[dict]) -> str:
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
# The gate composes four independent weekly criteria into one scorecard; the
# verbatim computation is moved from the operator CLI (scripts/beta_metrics.py).


def _source_counts(db_module: Any, start: datetime, end: datetime) -> dict[str, int]:
    """Row counts of every persisted source inside the window."""

    def _count_rows(model):
        with db_module.session() as db_session:
            statement = select(model.id).where(
                model.created_at >= start, model.created_at <= end
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
    windows: Sequence[tuple[datetime, datetime]],
    beta_start: datetime,
    effective_end: datetime,
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
    db_module: Any, windows: Sequence[tuple[datetime, datetime]], now: datetime
) -> list[dict]:
    """Validation receipts per week against ``RECEIPTS_PER_WEEK``."""
    weeks = []
    for index, (wk_start, wk_end) in enumerate(windows, start=1):
        count = _receipt_count(db_module, wk_start, min(now, wk_end))
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


def _bias_weeks(
    db_module: Any, windows: Sequence[tuple[datetime, datetime]], now: datetime
) -> list[dict]:
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
    windows: Sequence[tuple[datetime, datetime]],
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

    all_rows = _activity_rows(db_module, beta_start, effective_end)
    timeline = _session_timeline(all_rows)
    rows_without_id = sum(1 for session_id, _ in all_rows if not session_id)
    source_counts = _source_counts(db_module, beta_start, effective_end)
    receipts_total = _receipt_count(db_module, beta_start, effective_end)

    retention_overall, retention_weeks, retention_gate = _retention_section(
        timeline, windows, beta_start, effective_end, now
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
