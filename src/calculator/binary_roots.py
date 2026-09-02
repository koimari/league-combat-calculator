"""Shared runtime access to the tracked CommunityDragon character binaries.

The per-champion dumps under ``data/bin/characters/<key>.bin.json`` are the
game's own numeric layer (parsed from client 16.15.8024387; regenerable via
``scripts/decompose_binaries.py``, provenance-checked against
raw.communitydragon.org — see ``data/bin/README.md``).  Champion modules root
their priced constants here instead of hand-copied literals: a patch that
moves a number moves it once, in the dump, and every consumer sees it.

Fail-closed everywhere: a missing or malformed dump, a spell object that does
not exist, a DataValue without a usable first value — all raise
:class:`RuntimeError` naming the file and the lookup.  Nothing in this module
substitutes zero, skips, or falls back.
"""

import json
import math
import re
from collections.abc import Mapping
from functools import cache
from pathlib import Path
from typing import Any

_BIN_DIR = Path(__file__).resolve().parents[2] / "data" / "bin" / "characters"
_NONALNUM = re.compile(r"[^a-z0-9]")


def champion_key(name: str) -> str:
    """Lowercase, strip everything non-alphanumeric: ``Dr. Mundo`` -> ``drmundo``."""
    return _NONALNUM.sub("", str(name).lower())


@cache
def character_bin(champion_name: str) -> dict[str, Any]:
    """One champion's full parsed binary dump, keyed by object path."""
    path = _BIN_DIR / f"{champion_key(champion_name)}.bin.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RuntimeError(f"character binary unavailable: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"character binary is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"character binary is not an object: {path}")
    return payload


def spell_object(champion_name: str, script_name: str) -> dict[str, Any]:
    """The spell object whose ``mScriptName`` (or ``ObjectName``) matches.

    Matched case-insensitively on the exact name — ``AurelionSolQ``, not a
    substring — because a substring would silently bind to the wrong spell.
    """
    wanted = script_name.lower()
    for obj in character_bin(champion_name).values():
        if not isinstance(obj, dict):
            continue
        names = [
            value.lower()
            for key in ("mScriptName", "ObjectName")
            for value in (obj.get(key),)
            if isinstance(value, str)
        ]
        if any(name == wanted for name in names):
            return obj
    raise RuntimeError(
        f"{champion_name}: spell object {script_name!r} not found in its binary"
    )


def character_record_root(champion_name: str) -> dict[str, Any]:
    """A champion's ``CharacterRecords/Root`` block (base stats)."""
    payload = character_bin(champion_name)
    wanted = f"{champion_key(champion_name)}/characterrecords/root"
    for key, value in payload.items():
        if isinstance(value, dict) and key.lower().endswith(wanted):
            return value
    raise RuntimeError(
        f"{champion_name}: CharacterRecords/Root not found in its binary"
    )


def record_value(root: Mapping[str, Any], field: str) -> float:
    """One ModifiableFloat-style record field's ``baseValue``, snapped the
    same way :func:`data_value` snaps spell DataValues."""
    value = root.get(field)
    if isinstance(value, dict) and "baseValue" in value:
        try:
            number = float(value["baseValue"])
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                f"record field {field!r}: unusable baseValue {value['baseValue']!r}"
            ) from exc
        if not math.isfinite(number):
            raise RuntimeError(f"record field {field!r}: non-finite")
        snapped = float(f"{number:.6g}")
        if not math.isfinite(snapped):  # pragma: no cover - defensive
            raise RuntimeError(f"record field {field!r}: non-finite")
        return snapped
    raise RuntimeError(f"record field {field!r} not found")


def _breakpoint_level(step: Any) -> float:
    """One breakpoint's sort key: its numeric ``mLevel``, or raise."""
    if isinstance(step, dict) and "mLevel" in step:
        level = step["mLevel"]
        if isinstance(level, (int, float)):
            return float(level)
    raise RuntimeError(f"calculation breakpoint row without a numeric mLevel: {step!r}")


def calculation_breakpoints(
    spell_obj: dict[str, Any], calculation_name: str
) -> tuple[float, ...]:
    """A ``mSpellCalculations`` level-breakpoint node as cumulative tiers.

    The game states many transform-stance numbers as ``mLevel1Value`` plus
    one ``mAdditionalBonusAtThisLevel`` per breakpoint level; this returns
    the cumulative value at each tier ``(tier0, tier1, ...)`` — the shape
    champion modules index by level band.  Snap and fail-closed rules match
    :func:`data_value`.
    """
    spell = spell_obj.get("mSpell") if isinstance(spell_obj, dict) else None
    calcs = spell.get("mSpellCalculations") if isinstance(spell, dict) else None
    node = calcs.get(calculation_name) if isinstance(calcs, dict) else None
    parts = node.get("mFormulaParts") if isinstance(node, dict) else None
    if not isinstance(parts, list):
        raise RuntimeError(
            f"calculation {calculation_name!r} not found or has no formula parts"
        )
    for part in parts:
        if isinstance(part, dict) and "mLevel1Value" in part:
            try:
                current = float(part["mLevel1Value"])
            except (TypeError, ValueError) as exc:
                raise RuntimeError(
                    f"calculation {calculation_name!r}: unusable mLevel1Value"
                ) from exc
            tiers = [current]
            raw_breakpoints = part.get("mBreakpoints")
            if raw_breakpoints is None:
                raw_breakpoints = ()
            if not isinstance(raw_breakpoints, list):
                raise RuntimeError(
                    f"calculation {calculation_name!r}: mBreakpoints is not a list"
                )
            for step in sorted(raw_breakpoints, key=_breakpoint_level):
                try:
                    current += float(step["mAdditionalBonusAtThisLevel"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise RuntimeError(
                        f"calculation {calculation_name!r}: unusable breakpoint row"
                    ) from exc
                tiers.append(current)
            snapped = tuple(float(f"{tier:.6g}") for tier in tiers)
            if not all(math.isfinite(tier) for tier in snapped):  # pragma: no cover
                raise RuntimeError(f"calculation {calculation_name!r}: non-finite")
            return snapped
    raise RuntimeError(
        f"calculation {calculation_name!r}: no level-breakpoint formula part"
    )


def calculation_interpolation(
    spell_obj: dict[str, Any], calculation_name: str
) -> tuple[float, float]:
    """A calculation's finite character-level interpolation endpoints."""
    spell = spell_obj.get("mSpell") if isinstance(spell_obj, dict) else None
    calcs = spell.get("mSpellCalculations") if isinstance(spell, dict) else None
    node = calcs.get(calculation_name) if isinstance(calcs, dict) else None
    parts = node.get("mFormulaParts") if isinstance(node, dict) else None
    if not isinstance(parts, list) or not parts:
        raise RuntimeError(
            f"calculation {calculation_name!r} not found or has no formula parts"
        )
    matches = [
        part
        for part in parts
        if isinstance(part, dict) and "mStartValue" in part and "mEndValue" in part
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"calculation {calculation_name!r}: expected one interpolation part, "
            f"found {len(matches)}"
        )
    try:
        start = float(matches[0]["mStartValue"])
        end = float(matches[0]["mEndValue"])
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            f"calculation {calculation_name!r}: unusable interpolation endpoints"
        ) from exc
    snapped = (float(f"{start:.6g}"), float(f"{end:.6g}"))
    if not all(math.isfinite(value) for value in snapped):
        raise RuntimeError(f"calculation {calculation_name!r}: non-finite endpoints")
    return snapped


def calculation_coefficient(spell_obj: dict[str, Any], calculation_name: str) -> float:
    """A calculation's one finite scalar coefficient, or raise if ambiguous."""
    spell = spell_obj.get("mSpell") if isinstance(spell_obj, dict) else None
    calcs = spell.get("mSpellCalculations") if isinstance(spell, dict) else None
    node = calcs.get(calculation_name) if isinstance(calcs, dict) else None
    parts = node.get("mFormulaParts") if isinstance(node, dict) else None
    if not isinstance(parts, list) or not parts:
        raise RuntimeError(
            f"calculation {calculation_name!r} not found or has no formula parts"
        )
    matches = [
        part for part in parts if isinstance(part, dict) and "mCoefficient" in part
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"calculation {calculation_name!r}: expected one coefficient part, "
            f"found {len(matches)}"
        )
    try:
        value = float(matches[0]["mCoefficient"])
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            f"calculation {calculation_name!r}: unusable coefficient"
        ) from exc
    snapped = float(f"{value:.6g}")
    if not math.isfinite(snapped):
        raise RuntimeError(f"calculation {calculation_name!r}: non-finite coefficient")
    return snapped


def calculation_stat_coefficient(
    spell_obj: dict[str, Any], calculation_name: str, stat: int
) -> float:
    """One calculation coefficient attached to an exact ``mStat`` part."""
    spell = spell_obj.get("mSpell") if isinstance(spell_obj, dict) else None
    calcs = spell.get("mSpellCalculations") if isinstance(spell, dict) else None
    node = calcs.get(calculation_name) if isinstance(calcs, dict) else None
    parts = node.get("mFormulaParts") if isinstance(node, dict) else None
    if not isinstance(parts, list) or not parts:
        raise RuntimeError(
            f"calculation {calculation_name!r} not found or has no formula parts"
        )
    matches = [
        part
        for part in parts
        if isinstance(part, dict)
        and part.get("mStat") == stat
        and "mCoefficient" in part
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"calculation {calculation_name!r}: expected one coefficient for "
            f"mStat {stat}, found {len(matches)}"
        )
    try:
        value = float(matches[0]["mCoefficient"])
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            f"calculation {calculation_name!r}: unusable mStat {stat} coefficient"
        ) from exc
    snapped = float(f"{value:.6g}")
    if not math.isfinite(snapped):
        raise RuntimeError(
            f"calculation {calculation_name!r}: mStat {stat} coefficient is non-finite"
        )
    return snapped


def calculation_coefficients(
    spell_obj: dict[str, Any], calculation_name: str
) -> tuple[float, ...]:
    """A calculation's ordered numeric ``mCoefficient`` formula parts.

    Some passive ratios are authored in ``mSpellCalculations`` rather than
    ``DataValues``. Every formula part in this accessor must expose a finite
    coefficient; missing or malformed coefficients fail closed instead of
    silently dropping a component.
    """
    spell = spell_obj.get("mSpell") if isinstance(spell_obj, dict) else None
    calcs = spell.get("mSpellCalculations") if isinstance(spell, dict) else None
    node = calcs.get(calculation_name) if isinstance(calcs, dict) else None
    parts = node.get("mFormulaParts") if isinstance(node, dict) else None
    if not isinstance(parts, list) or not parts:
        raise RuntimeError(
            f"calculation {calculation_name!r} not found or has no formula parts"
        )
    coefficients = []
    for index, part in enumerate(parts):
        if not isinstance(part, dict) or "mCoefficient" not in part:
            raise RuntimeError(
                f"calculation {calculation_name!r}: formula part {index} "
                "has no coefficient"
            )
        try:
            value = float(part["mCoefficient"])
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                f"calculation {calculation_name!r}: formula part {index} "
                "has an unusable coefficient"
            ) from exc
        if not math.isfinite(value):
            raise RuntimeError(
                f"calculation {calculation_name!r}: formula part {index} "
                "has a non-finite coefficient"
            )
        coefficients.append(float(f"{value:.6g}"))
    return tuple(coefficients)


def _data_value_at_index(
    spell_obj: dict[str, Any], value_name: str, value_index: int, index_label: str
) -> float:
    """Read one finite, snapped entry from a named DataValue row."""
    spell = spell_obj.get("mSpell") if isinstance(spell_obj, dict) else None
    rows = spell.get("DataValues") if isinstance(spell, dict) else None
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict) or row.get("name") != value_name:
                continue
            values = row.get("values")
            if isinstance(values, list) and values:
                if value_index >= len(values):
                    raise RuntimeError(
                        f"DataValue {value_name!r}: {index_label} unavailable "
                        f"in {len(values)}-entry row"
                    )
                try:
                    value = float(values[value_index])
                except (TypeError, ValueError) as exc:
                    raise RuntimeError(
                        f"DataValue {value_name!r}: unusable {index_label} "
                        f"{values[value_index]!r}"
                    ) from exc
                if not math.isfinite(value):
                    raise RuntimeError(f"DataValue {value_name!r}: non-finite")
                snapped = float(f"{value:.6g}")
                if not math.isfinite(snapped):  # pragma: no cover - defensive
                    raise RuntimeError(f"DataValue {value_name!r}: non-finite")
                return snapped
            raise RuntimeError(
                f"DataValue {value_name!r}: present but carries no values row"
            )
    raise RuntimeError(f"DataValue {value_name!r} not found")


def data_value(spell_obj: dict[str, Any], value_name: str) -> float:
    """Read the first finite, snapped entry of a named DataValue rank row."""
    return _data_value_at_index(spell_obj, value_name, 0, "first value")


def data_value_at_rank(spell_obj: dict[str, Any], value_name: str, rank: int) -> float:
    """A named ranked DataValue using the game's one-based spell rank index."""
    if isinstance(rank, bool) or rank < 1:
        raise RuntimeError(f"DataValue {value_name!r}: rank must be a positive integer")
    return _data_value_at_index(spell_obj, value_name, rank, f"rank {rank}")
