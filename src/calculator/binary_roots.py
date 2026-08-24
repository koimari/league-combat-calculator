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
from functools import lru_cache
from pathlib import Path
from typing import Any

_BIN_DIR = Path(__file__).resolve().parents[2] / "data" / "bin" / "characters"
_NONALNUM = re.compile(r"[^a-z0-9]")


def champion_key(name: str) -> str:
    """Lowercase, strip everything non-alphanumeric: ``Dr. Mundo`` -> ``drmundo``."""
    return _NONALNUM.sub("", str(name).lower())


@lru_cache(maxsize=None)
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


def record_value(root: dict[str, Any], field: str) -> float:
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


def _breakpoint_level(breakpoint: Any) -> float:
    """One breakpoint's sort key: its numeric ``mLevel``, or raise."""
    if isinstance(breakpoint, dict) and "mLevel" in breakpoint:
        level = breakpoint["mLevel"]
        if isinstance(level, (int, float)):
            return float(level)
    raise RuntimeError(
        f"calculation breakpoint row without a numeric mLevel: {breakpoint!r}"
    )


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
            for breakpoint in sorted(raw_breakpoints, key=_breakpoint_level):
                try:
                    current += float(breakpoint["mAdditionalBonusAtThisLevel"])
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


def data_value(spell_obj: dict[str, Any], value_name: str) -> float:
    """A spell's named DataValue, first entry of its rank row, finite or raise.

    Some rows legitimately carry no ``values`` key (the game leaves them
    unset); asking for one of those by name is a lookup error, not a zero.

    The dumps store IEEE-754 *float32*, so an authored ``0.7`` arrives as
    ``0.69999998807...``.  Riot authors these numbers at six significant
    digits or fewer, so the read snaps back through ``%.6g``: that restores
    the authored decimal exactly (0.7, 2.6, 360.0) while a genuine patch
    change moves digits beyond storage noise and snaps to a different
    number.  Without this, dividing by a stored percent drifts the ninth
    decimal of downstream damage and trips the byte-exact golden gate.
    """
    spell = spell_obj.get("mSpell") if isinstance(spell_obj, dict) else None
    rows = spell.get("DataValues") if isinstance(spell, dict) else None
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict) or row.get("name") != value_name:
                continue
            values = row.get("values")
            if isinstance(values, list) and values:
                try:
                    value = float(values[0])
                except (TypeError, ValueError) as exc:
                    raise RuntimeError(
                        f"DataValue {value_name!r}: unusable first value {values[0]!r}"
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
