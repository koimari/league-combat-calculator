"""The four weekly criteria the beta contract sets, and the windows they are measured over."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, NamedTuple

from sqlalchemy import select

from src import db

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


class Window(NamedTuple):
    """One span every persisted row is counted inside, both ends included."""

    start: datetime
    end: datetime


def _week_windows(beta_start: datetime, weeks: int) -> list[Window]:
    """Return one :class:`Window` for each 7-day week of the beta."""
    return [
        Window(
            beta_start + timedelta(days=7 * index),
            beta_start + timedelta(days=7 * (index + 1)),
        )
        for index in range(weeks)
    ]


def _activity_rows(db_module: Any, window: Window) -> list[tuple[str | None, datetime]]:
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
                model.created_at >= window.start, model.created_at <= window.end
            )
            rows.extend(db_session.execute(statement).all())
    return rows


def _receipt_count(db_module: Any, window: Window) -> int:
    """Validation receipts (feedback rows carrying a signed delta)."""
    with db_module.session() as db_session:
        statement = select(db_module.ValidationFeedback.id).where(
            db_module.ValidationFeedback.delta.is_not(None),
            db_module.ValidationFeedback.created_at >= window.start,
            db_module.ValidationFeedback.created_at <= window.end,
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
