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


def data_value(spell_obj: dict[str, Any], value_name: str) -> float:
    """A spell's named DataValue, first entry of its rank row, finite or raise.

    Some rows legitimately carry no ``values`` key (the game leaves them
    unset); asking for one of those by name is a lookup error, not a zero.
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
                return value
            raise RuntimeError(
                f"DataValue {value_name!r}: present but carries no values row"
            )
    raise RuntimeError(f"DataValue {value_name!r} not found")
