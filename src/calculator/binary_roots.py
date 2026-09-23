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


def _dig(obj: object, *keys: str, want: type | tuple[type, ...], label: str) -> Any:
    """Walk one JSON hop chain, raising on the hop that does not land.

    ``want`` types the last hop and ``label`` names the caller's lookup, so a
    refusal says what was asked for as well as where the walk died.
    """
    node: object = obj
    for key in keys:
        node = node.get(key) if isinstance(node, Mapping) else None
    if not isinstance(node, want):
        raise RuntimeError(f"{label}: {'.'.join(keys)} not found or unusable")
    return node


def _snapped(value: Any, label: str) -> float:
    """One binary number, finite and snapped to six significant digits."""
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{label}: unusable value {value!r}") from exc
    if not math.isfinite(number):
        raise RuntimeError(f"{label}: non-finite")
    return float(f"{number:.6g}")


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


def basic_attack_value(champion_name: str, field: str) -> float | None:
    """One field of the champion's ``basicAttack`` record, or None when the
    record leaves it at its class default."""
    attack = character_record_root(champion_name).get("basicAttack")
    if not isinstance(attack, Mapping):
        raise RuntimeError(f"{champion_name}: basicAttack record not found")
    if field not in attack:
        return None
    return _snapped(attack[field], f"{champion_name} basicAttack {field}")


def record_value(root: Mapping[str, Any], field: str) -> float:
    """One ModifiableFloat-style record field's ``baseValue``, snapped like
    :func:`data_value`; absent and unusable are distinct refusals."""
    entry = root.get(field)
    if not isinstance(entry, Mapping) or "baseValue" not in entry:
        raise RuntimeError(f"record field {field!r} not found")
    return _snapped(entry["baseValue"], f"record field {field!r} baseValue")


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
    for part in _formula_parts(spell_obj, calculation_name):
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
            label = f"calculation {calculation_name!r}"
            return tuple(_snapped(tier, label) for tier in tiers)
    raise RuntimeError(
        f"calculation {calculation_name!r}: no level-breakpoint formula part"
    )


def _formula_parts(spell_obj: dict[str, Any], calculation_name: str) -> list:
    """A calculation's non-empty ``mFormulaParts``, or raise naming its path."""
    parts = _dig(
        spell_obj,
        "mSpell",
        "mSpellCalculations",
        calculation_name,
        "mFormulaParts",
        want=list,
        label=f"calculation {calculation_name!r}",
    )
    if not parts:
        raise RuntimeError(f"calculation {calculation_name!r} has no formula parts")
    return parts


def calculation_interpolation(
    spell_obj: dict[str, Any], calculation_name: str
) -> tuple[float, float]:
    """A calculation's finite character-level interpolation endpoints."""
    parts = _formula_parts(spell_obj, calculation_name)
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
    label = f"calculation {calculation_name!r} interpolation"
    return (
        _snapped(matches[0]["mStartValue"], f"{label} start"),
        _snapped(matches[0]["mEndValue"], f"{label} end"),
    )


def _calculation_scalar(
    spell_obj: dict[str, Any], calculation_name: str, field: str, label: str
) -> float:
    """The one finite *field* among a calculation's parts, or raise if ambiguous."""
    parts = _formula_parts(spell_obj, calculation_name)
    matches = [part for part in parts if isinstance(part, dict) and field in part]
    if len(matches) != 1:
        raise RuntimeError(
            f"calculation {calculation_name!r}: expected one {label} part, "
            f"found {len(matches)}"
        )
    return _snapped(matches[0][field], f"calculation {calculation_name!r} {label}")


def calculation_coefficient(spell_obj: dict[str, Any], calculation_name: str) -> float:
    """A calculation's one finite scalar coefficient, or raise if ambiguous."""
    return _calculation_scalar(
        spell_obj, calculation_name, "mCoefficient", "coefficient"
    )


def calculation_constant(spell_obj: dict[str, Any], calculation_name: str) -> float:
    """A calculation's one finite ``mNumber`` formula part, or raise if ambiguous."""
    return _calculation_scalar(spell_obj, calculation_name, "mNumber", "number")


def calculation_stat_coefficient(
    spell_obj: dict[str, Any], calculation_name: str, stat: int
) -> float:
    """One calculation coefficient attached to an exact ``mStat`` part."""
    parts = _formula_parts(spell_obj, calculation_name)
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
    return _snapped(
        matches[0]["mCoefficient"],
        f"calculation {calculation_name!r} mStat {stat} coefficient",
    )


def calculation_coefficients(
    spell_obj: dict[str, Any], calculation_name: str
) -> tuple[float, ...]:
    """A calculation's ordered numeric ``mCoefficient`` formula parts.

    Some passive ratios are authored in ``mSpellCalculations`` rather than
    ``DataValues``. Every formula part in this accessor must expose a finite
    coefficient; missing or malformed coefficients fail closed instead of
    silently dropping a component.
    """
    coefficients = []
    for index, part in enumerate(_formula_parts(spell_obj, calculation_name)):
        label = f"calculation {calculation_name!r} formula part {index} coefficient"
        if not isinstance(part, Mapping) or "mCoefficient" not in part:
            raise RuntimeError(f"{label}: missing")
        coefficients.append(_snapped(part["mCoefficient"], label))
    return tuple(coefficients)


def _data_value_at_index(
    spell_obj: dict[str, Any], value_name: str, value_index: int, index_label: str
) -> float:
    """Read one finite, snapped entry from a named DataValue row."""
    label = f"DataValue {value_name!r}"
    for row in _dig(spell_obj, "mSpell", "DataValues", want=list, label=label):
        if not isinstance(row, Mapping) or row.get("name") != value_name:
            continue
        values = row.get("values")
        if not isinstance(values, list) or not values:
            raise RuntimeError(f"{label}: present but carries no values row")
        if value_index >= len(values):
            raise RuntimeError(
                f"{label}: {index_label} unavailable in {len(values)}-entry row"
            )
        return _snapped(values[value_index], f"{label} {index_label}")
    raise RuntimeError(f"{label} not found")


def data_value(spell_obj: dict[str, Any], value_name: str) -> float:
    """Read the first finite, snapped entry of a named DataValue rank row."""
    return _data_value_at_index(spell_obj, value_name, 0, "first value")


def data_value_at_rank(spell_obj: dict[str, Any], value_name: str, rank: int) -> float:
    """A named ranked DataValue using the game's one-based spell rank index."""
    if isinstance(rank, bool) or rank < 1:
        raise RuntimeError(f"DataValue {value_name!r}: rank must be a positive integer")
    return _data_value_at_index(spell_obj, value_name, rank, f"rank {rank}")
