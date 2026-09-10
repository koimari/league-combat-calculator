"""The crowd-control marker a declared entry carries, read by the ordered ledger."""

from collections.abc import Iterable, Mapping
from typing import Any

from ..ability_atoms import ability_field
from ..control_spec import ControlEvent, ControlScope


def _declared_cc_kind(parts: Iterable[Any]) -> str | None:
    """The reviewed control kind these parts declare, if any does."""
    for part in parts:
        kind = part.cc_kind
        if kind is not None:
            return str(kind)
    return None


def _entry_control_scope(info: Mapping[str, Any]) -> ControlScope | None:
    """Read an explicit cast scope or the shared scope of its control events."""
    authored = ability_field(info, "control_scope")
    if authored is not None:
        if not isinstance(authored, ControlScope):
            raise TypeError("control_scope must be a ControlScope")
        return authored
    scopes = {
        control.scope
        for control in ability_field(info, "control_events")
        if isinstance(control, ControlEvent)
    }
    return next(iter(scopes)) if len(scopes) == 1 else None


def _declared_cc_marker(
    info: Mapping[str, Any], *, roster_target_index: int | None = None
) -> dict[str, Any]:
    """The reviewed control kind an entry's parts declare, as an event marker
    on the swings an empowering entry forces."""
    kind = _declared_cc_kind(ability_field(info, "parts"))
    scope = _entry_control_scope(info)
    if (
        kind is not None
        and roster_target_index is not None
        and scope is not None
        and not scope.reaches(roster_target_index)
    ):
        return {"cc_reviewed": True}
    return {"cc_kind": kind, "cc_reviewed": True} if kind is not None else {}
