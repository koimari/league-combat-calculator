"""Observed combat-log parsing and validation-receipt arithmetic."""

import json
import math
import re
from collections.abc import Mapping
from typing import Any

VALIDATION_SOURCES = frozenset({"manual", "combat_log", "practice_tool"})
VALIDATION_RELATIVE_TOLERANCE = 0.10
VALIDATION_ABSOLUTE_TOLERANCE = 20.0
_SLOT_LETTERS = ("P", "Q", "W", "E", "R")


def receipt_tolerance(predicted_tdd: float) -> float:
    """Return the larger of the 10% relative band and 20 damage floor."""
    return max(
        VALIDATION_RELATIVE_TOLERANCE * abs(predicted_tdd),
        VALIDATION_ABSOLUTE_TOLERANCE,
    )


def validate_damage_number(value: Any, label: str) -> float:
    """Validate one finite, non-negative public damage amount."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number")
    number = float(value)
    if not math.isfinite(number) or number < 0 or number > 1e12:
        raise ValueError(f"{label} must be a finite non-negative number")
    return number


def normalize_observed_payload(
    payload: Mapping[str, Any], predicted_tdd: float | None = None
) -> dict[str, Any]:
    """Normalize an explicit or percentage-based observed receipt."""
    off_by = payload.get("off_by_percent")
    if off_by is not None:
        if predicted_tdd is None:
            raise ValueError("off_by_percent requires a model prediction")
        percent = validate_damage_number(off_by, "observed.off_by_percent")
        if percent > 1000:
            raise ValueError("observed.off_by_percent must be at most 1000")
        direction = str(payload.get("direction", "higher")).strip().lower()
        if direction not in {"higher", "lower"}:
            raise ValueError("observed.direction must be higher or lower")
        factor = (
            1.0 + percent / 100.0 if direction == "higher" else 1.0 - percent / 100.0
        )
        tdd = predicted_tdd * factor
        if tdd < 0:
            raise ValueError("observed.off_by_percent implies a negative total")
        return {"tdd": round(tdd, 2), "sources": {}}

    raw_tdd = payload.get("tdd")
    if raw_tdd is None:
        raw_tdd = payload.get("total_damage")
    if raw_tdd is None:
        raise ValueError("observed.tdd is required")
    tdd = validate_damage_number(raw_tdd, "observed.tdd")
    raw_sources = payload.get("sources")
    if raw_sources is None:
        raw_sources = {}
    if not isinstance(raw_sources, Mapping):
        raise ValueError("observed.sources must be an object")
    sources: dict[str, float] = {}
    for key, value in raw_sources.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError("observed.sources keys must be non-empty strings")
        sources[key.strip()] = validate_damage_number(value, "observed.sources")
    return {"tdd": tdd, "sources": sources}


# Parsing deliberately accepts several compact user-paste shapes.
# pylint: disable=too-many-branches
def parse_observed_paste(text: str) -> dict[str, Any]:
    """Parse JSON or tolerant slot/value combat-log text into a receipt."""
    text = text.strip()
    if not text:
        raise ValueError("observed paste is empty")
    if text.startswith("{") or text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("observed JSON paste is not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError("observed JSON paste must be an object")
        return normalize_observed_payload(parsed)

    total: float | None = None
    sources: dict[str, float] = {}
    slot_seen: set[str] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        number_match = re.search(r"\d+(?:[.,]\d+)?", line)
        if number_match is None:
            continue
        number = float(number_match.group(0).replace(",", ""))
        head = line[: number_match.start()].strip(" \t:=-\u2013\u2014>|")
        head_upper = head.upper()
        slot = next(
            (
                letter
                for letter in _SLOT_LETTERS
                if head_upper == letter or head_upper.startswith(letter + " ")
            ),
            None,
        )
        if slot is not None:
            if slot in slot_seen:
                raise ValueError(f"duplicate slot {slot} in paste")
            slot_seen.add(slot)
            sources[slot] = number
        elif "TOTAL" in head_upper or head_upper in {"TDD", "SUM", "DAMAGE"}:
            total = number
        else:
            sources.setdefault(head or "damage", number)
    if total is None and sources:
        total = sum(sources.values())
    if total is None:
        raise ValueError("no damage numbers found in paste")
    return {"tdd": total, "sources": sources}


def evaluate_validation_receipt(
    predicted_payload: Mapping[str, Any],
    observed_input: Mapping[str, Any] | str | None,
) -> dict[str, Any]:
    """Return public comparison fields plus the unrounded persistence delta."""
    predicted_tdd = validate_damage_number(
        predicted_payload.get("total_damage", 0.0), "predicted total_damage"
    )
    predicted_sources: dict[str, float] = {}
    breakdown = predicted_payload.get("breakdown", {})
    if isinstance(breakdown, Mapping):
        for key, row in breakdown.items():
            if isinstance(row, Mapping) and row.get("total_damage"):
                predicted_sources[str(key)] = validate_damage_number(
                    row["total_damage"], f"predicted breakdown.{key}"
                )
    if observed_input is None:
        observed = {"tdd": predicted_tdd, "sources": predicted_sources}
    elif isinstance(observed_input, str):
        observed = parse_observed_paste(observed_input)
    else:
        observed = normalize_observed_payload(
            observed_input, predicted_tdd=predicted_tdd
        )
    tolerance = receipt_tolerance(predicted_tdd)
    delta = observed["tdd"] - predicted_tdd
    return {
        "public": {
            "predicted": {"tdd": predicted_tdd, "sources": predicted_sources},
            "observed": observed,
            "delta": round(delta, 2),
            "tolerance": round(tolerance, 2),
            "matched": abs(round(delta, 2)) <= round(tolerance, 2),
        },
        "raw_delta": delta,
    }
