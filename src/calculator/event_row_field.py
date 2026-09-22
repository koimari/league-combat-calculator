"""One stamped field of a published event row, or a refusal naming the row.

:func:`required_field` is for a field every producer of that row stamps, so
absence is a break.  :func:`optional_field` is for a field only some of them
stamp, so absence is a producer that stamped none and the caller says what it
does without one; no reader here ever substitutes a value of its own.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
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


def optional_field[T](
    event: Mapping[str, Any], field: str, read: Callable[[Any], T]
) -> T | None:
    """The field only some producers of this row stamp, ``None`` where none did."""
    return None if (value := event.get(field)) is None else read(value)
