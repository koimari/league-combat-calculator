"""One champion stack resource's receipts, in the shape every kind publishes."""

from collections.abc import Mapping
from typing import Any, NamedTuple

from ..results import RotationResult


class StackEvent(NamedTuple):
    """One thing that happened to a champion stack resource, as receipted.

    ``accepted`` with an empty ``reason`` is the stream a ledger counts;
    a refusal names its reason and moves no count.  ``fields`` are extra
    columns the mechanic publishes beside the shared ones.
    """

    operation: str
    amount: float
    time: float
    source: str
    accepted: bool
    reason: str
    fields: Mapping[str, Any] | None = None


def _stack_receipt_row(
    kind: str,
    sequence: int,
    event: StackEvent,
    *,
    current_before: Any,
    current_after: Any,
    maximum: Any,
) -> dict[str, Any]:
    """One row of a champion stack ledger, in the shape every kind publishes.

    ``kind`` names the ledger sub-section the row belongs to; the caller owns
    the stack arithmetic and hands in the before/after it produced, so a
    published zero keeps the type its own mechanic gave it.
    """
    return {
        "owner": "main",
        "kind": kind,
        "operation": event.operation,
        "amount": event.amount,
        "time": round(float(event.time), 3),
        "source": event.source,
        "sequence": sequence,
        "tier": 0.0,
        "atoms": [],
        "current_before": current_before,
        "maximum_before": maximum,
        "current_after": current_after,
        "maximum_after": maximum,
        "accepted": event.accepted,
        "reason": event.reason,
        **(dict(event.fields) if event.fields else {}),
    }


class _StackAccount:
    """One champion stack resource's receipts: the count, its gains, the rows.

    An account that is not ``counting`` (K'Sante W, Heimerdinger W/E) rows
    its events without a count: accepted receipts leave the count alone.
    """

    def __init__(
        self, kind: str, seeded: Any, maximum: int, *, counting: bool = True
    ) -> None:
        self.kind = kind
        self.current = seeded
        self.maximum = maximum
        self.counting = counting
        self.gains = 0
        self.receipts: list[dict[str, Any]] = []

    def add(self, event: StackEvent) -> None:
        """Append one receipt, moving the count when it is accepted."""
        before = self.current
        if event.accepted and self.counting:
            self.current += event.amount
            self.gains += 1
        self.receipts.append(
            _stack_receipt_row(
                self.kind,
                len(self.receipts) + 1,
                event,
                current_before=before,
                current_after=self.current,
                maximum=self.maximum,
            )
        )

    def ledger_section(
        self, seeded: Any, transitions: list[dict[str, Any]], declaration: Any
    ) -> dict[str, Any]:
        """The account's ``resource_ledger_v1`` section."""
        return {
            "contract": "resource_ledger_v1",
            "owner": "main",
            "kind": self.kind,
            "opening_maximum": self.maximum,
            "opening_current": seeded,
            "closing_maximum": self.maximum,
            "closing_current": self.current,
            "base_maximum": self.maximum,
            "bonus_maximum": 0,
            "receipts": self.receipts,
            "threshold_transitions": transitions,
            "declaration": declaration,
        }


def _resource_ledger(rotation: RotationResult) -> dict[str, Any]:
    """The rotation's resource ledger, created when nothing wrote one yet."""
    ledger = rotation.resource_ledger
    if not isinstance(ledger, dict):
        ledger = {}
        rotation.resource_ledger = ledger
    return ledger
