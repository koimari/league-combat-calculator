"""The mana event vocabulary: the operations a row states, their tiers, and each one's receipt."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

# Floating-point tolerance shared with the engine walks (1e-9).
_EPS = 1e-9


RESOURCE_KIND_MANA = "mana"


OP_MAX_INCREASE = "max_increase"


OP_GAIN = "gain"


OP_SPEND = "spend"


OP_REFUND = "refund"


OP_REGEN = "regen"


OP_CLAMP = "clamp"


_OPERATIONS = frozenset(
    {OP_MAX_INCREASE, OP_GAIN, OP_SPEND, OP_REFUND, OP_REGEN, OP_CLAMP}
)


# Same-timestamp ordering tiers (mirror the engine's phase convention:
# external restores/regen sort before a simultaneous cast).
TIER_RESTORE = 0.0


TIER_CAST = 1.0


@dataclass(frozen=True, slots=True)
class ResourceEvent:
    """One authored resource transition before the ledger applies it."""

    owner: str
    kind: str = RESOURCE_KIND_MANA
    operation: str = OP_GAIN
    amount: float = 0.0
    time: float = 0.0
    source: str = ""
    sequence: int = 0
    tier: float = TIER_RESTORE
    atoms: tuple[tuple[str, str], ...] = ()
    detail: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ResourceReceipt:
    """One applied ledger transition with before/after state."""

    owner: str
    kind: str
    operation: str
    amount: float
    time: float
    source: str
    sequence: int
    tier: float
    atoms: tuple[tuple[str, str], ...]
    current_before: float
    maximum_before: float
    current_after: float
    maximum_after: float
    accepted: bool
    reason: str
    detail: Mapping[str, Any] = field(default_factory=dict)

    def public(self) -> dict[str, Any]:
        """JSON-safe public receipt."""
        row: dict[str, Any] = {
            "owner": self.owner,
            "kind": self.kind,
            "operation": self.operation,
            "amount": round(float(self.amount), 9),
            "time": round(float(self.time), 9),
            "source": self.source,
            "sequence": int(self.sequence),
            "tier": float(self.tier),
            "atoms": [list(atom) for atom in self.atoms],
            "current_before": round(float(self.current_before), 9),
            "maximum_before": round(float(self.maximum_before), 9),
            "current_after": round(float(self.current_after), 9),
            "maximum_after": round(float(self.maximum_after), 9),
            "accepted": bool(self.accepted),
            "reason": self.reason,
        }
        if self.detail:
            row["detail"] = dict(self.detail)
        return row


def _validate_event_shape(event: ResourceEvent, *, owner: str, kind: str) -> None:
    """Fail closed on any malformed authored event."""
    if event.owner != owner:
        raise ValueError(
            f"resource event owner {event.owner!r} does not match account "
            f"owner {owner!r}"
        )
    if event.kind != kind:
        raise ValueError(
            f"resource event kind {event.kind!r} does not match account kind "
            f"{kind!r}"
        )
    if event.operation not in _OPERATIONS:
        raise ValueError(
            f"unknown resource operation {event.operation!r}; supported: "
            f"{sorted(_OPERATIONS)}"
        )
    if isinstance(event.amount, bool) or not math.isfinite(float(event.amount)):
        raise ValueError(
            f"{event.operation} amount must be a finite number, got {event.amount!r}"
        )
    if float(event.amount) < 0.0:
        raise ValueError(
            f"{event.operation} amount must be non-negative, got {event.amount!r}"
        )
    if event.operation == OP_CLAMP and float(event.amount) != 0.0:
        raise ValueError(
            f"{OP_CLAMP} amount must be 0.0 (the clamp pins current into "
            f"[0, maximum]), got {event.amount!r}"
        )
    if isinstance(event.time, bool) or not math.isfinite(float(event.time)):
        raise ValueError(
            f"resource event time must be a finite number, got {event.time!r}"
        )
    if float(event.time) < 0.0:
        raise ValueError(
            f"resource event time must be non-negative, got {event.time!r}"
        )
