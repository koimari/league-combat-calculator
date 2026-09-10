"""How a cached name and stat field are spelled in the atom contract: id fragment and unit."""

from __future__ import annotations

import re


def _stat_unit(field: str) -> str:
    """Map the cached stat field to the unit used by the atom contract."""
    return {
        "flat": "flat",
        "perLevel": "per_level",
        "percent": "percent",
        "percentPerLevel": "percent_per_level",
    }.get(field, "flat")


def _snake(value: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower()
