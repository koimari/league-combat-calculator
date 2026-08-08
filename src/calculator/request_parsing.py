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
