"""How a cached name and stat field are spelled in the atom contract: id fragment and unit."""

from __future__ import annotations

import re


def _stat_unit(field: str) -> str:
    """Map the cached stat field to the unit used by the atom contract.

    A field outside the four cached spellings raises rather than reading as flat.
    """
    units = {
        "flat": "flat",
        "perLevel": "per_level",
        "percent": "percent",
        "percentPerLevel": "percent_per_level",
    }
    if field not in units:
        raise KeyError(f"cached stat field {field!r} has no atom unit")
    return units[field]


def _snake(value: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower()
