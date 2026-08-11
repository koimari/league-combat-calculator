"""Shared coercion policy for public request scalars and name lists.

Public integers accept JSON integers and canonical base-10 integer strings.
Public numbers additionally accept finite numeric strings. Booleans are never
numbers, and strings/collections are otherwise never implicitly coerced.
"""

import math
from collections.abc import Mapping


def request_string(
    data: Mapping[str, object],
    key: str,
    default: str = "",
    *,
    required: bool = False,
) -> str:
    """Read one trimmed public string with the shared length limit."""
    value = data.get(key, default)
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    parsed = value.strip()
    if required and not parsed:
        raise ValueError(f"{key} is required")
    if len(parsed) > 100:
        raise ValueError(f"{key} must be at most 100 characters")
    return parsed


def request_int(
    data: Mapping[str, object],
    key: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    """Read one bounded integer, accepting canonical integer strings."""
    value = data.get(key, default)
    if isinstance(value, bool):
        raise ValueError(f"{key} must be an integer")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = int(value)
        except ValueError as exc:
            raise ValueError(f"{key} must be an integer") from exc
    else:
        raise ValueError(f"{key} must be an integer")
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{key} must be between {minimum} and {maximum}")
    return parsed


def request_number(
    data: Mapping[str, object],
    key: str,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    """Read one bounded finite number, accepting finite numeric strings."""
    value = data.get(key, default)
    if isinstance(value, bool):
        raise ValueError(f"{key} must be a number")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be a number") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{key} must be finite")
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{key} must be between {minimum:g} and {maximum:g}")
    return parsed


def request_bool(data: Mapping[str, object], key: str, default: bool) -> bool:
    """Read one JSON boolean without truthiness coercion."""
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be true or false")
    return value


def request_string_list(
    data: Mapping[str, object], key: str, *, maximum: int
) -> list[str]:
    """Read a bounded list of unique, trimmed public strings."""
    value = data.get(key, [])
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list")
    if len(value) > maximum:
        raise ValueError(f"{key} may contain at most {maximum} entries")

    names: list[str] = []
    for entry in value:
        if not isinstance(entry, str):
            raise ValueError(f"{key} entries must be strings")
        name = entry.strip()
        if len(name) > 100:
            raise ValueError(f"{key} entries must be at most 100 characters")
        if name:
            names.append(name)
    if len(set(names)) != len(names):
        raise ValueError(f"{key} must not contain duplicates")
    return names


def request_index_map(
    value: object,
    *,
    field: str,
    maximum_index: int,
    maximum_entries: int = 64,
) -> dict[str, int]:
    """Read a bounded map from support packet keys to teammate indexes."""
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    if len(value) > maximum_entries:
        raise ValueError(f"{field} may contain at most {maximum_entries} entries")
    parsed: dict[str, int] = {}
    for key, index in value.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError(f"{field} keys must be non-empty strings")
        normalized_key = key.strip()
        if len(normalized_key) > 160:
            raise ValueError(f"{field} keys must be at most 160 characters")
        if isinstance(index, bool) or not isinstance(index, int):
            raise ValueError(f"{field}.{key} must be an integer")
        if not 0 <= index <= maximum_index:
            raise ValueError(f"{field}.{key} must be between 0 and {maximum_index}")
        if normalized_key in parsed:
            raise ValueError(f"{field} must not contain duplicate normalized keys")
        parsed[normalized_key] = index
    return parsed
