"""The option keys a champion defensive window is driven by, named once.

A champion module declares these rows and `projectile_defense` reads them,
so the key spelling is a contract between two files: it lives here, and
both sides import the name rather than repeating the string.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import NamedTuple


class DefenseWindowOptions(NamedTuple):
    """One slot's window: the toggle, the start time, the held duration."""

    active: str
    active_from: str
    active_seconds: str


def _window(slot: str) -> DefenseWindowOptions:
    key = slot.lower()
    return DefenseWindowOptions(
        f"{key}_active", f"{key}_active_from", f"{key}_active_seconds"
    )


W_WINDOW = _window("W")
E_WINDOW = _window("E")

#: The window a slot's options drive, for a reader holding the slot letter.
WINDOW_OPTIONS = MappingProxyType({"W": W_WINDOW, "E": E_WINDOW})

# Which incoming events a window is asked to stop. Each spelling is one
# champion's own, so the declaring module and its reader share this line.
W_BLOCKED_SKILLSHOTS = "w_blocked_skillshots"
W_BLOCKED_SOURCES = "w_blocked_sources"
W_BLOCKED_EVENT_IDS = "w_blocked_event_ids"
E_BLOCKED_SKILLSHOTS = "e_blocked_skillshots"
E_BLOCKED_EVENT_IDS = "e_blocked_event_ids"
