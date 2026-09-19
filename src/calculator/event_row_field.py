"""One stamped field of a published event row, or a refusal naming the row."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def required_field(  # sightline-ok: 1 - key-typed read
    event: Mapping[str, Any], field: str, *, kind: str, stamper: str
) -> Any:
    """The field every *kind* row carries; absent is a producer break, never a default."""
    if field not in event:
        raise ValueError(
            f"a {kind} carries no {field!r}; {stamper} stamps it on every row it "
            f"builds, so this row ({sorted(event)}) is not a {kind} or its "
            "producer stopped stamping it"
        )
    return event[field]
