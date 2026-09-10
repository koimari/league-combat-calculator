"""Cooldowns, trigger gates and instance cadence: when a stateful mechanic may fire again.

:class:`CooldownRule` and :class:`CooldownState` hold one cooldown, global or
per-target; :class:`TriggerGate` answers whether a trigger is armed at a time;
:class:`InstanceCadence` spaces repeat applications on one instance.

The rest of this kernel lives beside it, one concept per module: the transition
record, its stamp and the timeline in :mod:`state_timeline`, how a stack is
gained, refreshed, capped and expired in :mod:`stack_rules`, the timed stack
state that rule drives in :mod:`timed_stacks`, and the window gate's hit pair in
:mod:`window_gates`.

Design rules every one of them keeps: numbers come from the data cache through
the consumer's typed accessors and are attached to a :class:`SourceReceipt`, so
the kernel never invents one; categorical rules are small frozen declarations
with public receipts; every transition is recorded with
``(time, tier, sequence, insertion_order)`` and the receipt walk sorts with the
total order the survival and damage walks use (``(time, phase, sequence)``,
expiry before gain at one timestamp, gain before cooldown start, cooldown
readiness inclusive); a missing sourced value raises naming the state and the
attribute.
"""

from __future__ import annotations

import math
from collections.abc import Hashable, Mapping
from dataclasses import dataclass
from typing import Any

from .state_timeline import (
    _EPS,
    TIER_COOLDOWN_START,
    EventStamp,
    SourceReceipt,
    StateTimeline,
    Transition,
)

# ---------------------------------------------------------------------------
# Cooldowns (global and per-target)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CooldownRule:
    """One cooldown declaration.

    ``per_target=False`` is a global cooldown (Fimbulwinter Everlasting);
    ``per_target=True`` keeps one readiness clock per target (Eclipse's
    internal cooldown shape).
    """

    name: str
    cooldown_seconds: float
    per_target: bool = False
    source: SourceReceipt | None = None

    def validate(self) -> None:
        """Fail closed on an impossible declaration."""
        source = f" (source: {self.source.label})" if self.source is not None else ""
        if not math.isfinite(self.cooldown_seconds) or self.cooldown_seconds <= 0.0:
            raise ValueError(
                f"{self.name}: cooldown_seconds must be finite and > 0, got "
                f"{self.cooldown_seconds!r}{source}"
            )

    def public_receipt(self) -> dict[str, Any]:
        """JSON-safe public receipt."""
        return {
            "name": self.name,
            "cooldown_seconds": self.cooldown_seconds,
            "per_target": self.per_target,
            "source": self.source.public() if self.source is not None else None,
        }


class CooldownState:
    """Deterministic cooldown machine with public start receipts.

    Readiness at the exact ``cooldown_until`` boundary is inclusive
    (``time + EPS >= ready_at``), matching the survival walk's convention.
    """

    def __init__(self, rule: CooldownRule) -> None:
        rule.validate()
        self.rule = rule
        self._ready_at: dict[str, float] = {}
        self._timeline = StateTimeline()

    @property
    def timeline(self) -> StateTimeline:
        """The transition log in walk order."""
        return self._timeline

    def ready_at(self, target: str = "default") -> float:
        """The readiness timestamp for one target clock."""
        key = target if self.rule.per_target else "default"
        return self._ready_at.get(key, float("-inf"))

    def is_ready(self, time: float, *, target: str = "default") -> bool:
        """Inclusive readiness check at the cooldown boundary."""
        return time + _EPS >= self.ready_at(target)

    def start(
        self,
        stamp: EventStamp,
        *,
        target: str = "default",
        meta: Mapping[str, Any] | None = None,
    ) -> Transition:
        """Start the cooldown now; returns the start transition."""
        key = target if self.rule.per_target else "default"
        cooldown_until = stamp.time + self.rule.cooldown_seconds
        self._ready_at[key] = cooldown_until
        return self._timeline.record(
            stamp,
            "cooldown_start",
            tier=TIER_COOLDOWN_START,
            detail={
                "state": self.rule.name,
                "target": key,
                "cooldown_until": cooldown_until,
                "per_target": self.rule.per_target,
                "trigger_source": str((meta or {}).get("source") or "trigger"),
            },
        )

    def public_receipt(self) -> dict[str, Any]:
        """JSON-safe public receipt."""
        return {
            "state": self.rule.name,
            "rule": self.rule.public_receipt(),
            "ready_at": dict(self._ready_at),
            "transitions": self._timeline.public_receipt(),
        }


class TriggerGate:
    """The acceptance gate a reactive author runs before it authors a row.

    One readiness clock plus the keys already answered, applied in the order
    every author applies them: a repeated key is refused without touching the
    clock, and a trigger inside the cooldown is refused without consuming the
    key.  :class:`CooldownState` is the receipted sibling; this one is for
    authors that publish no transition log of their own.

    ``inclusive`` is the boundary convention.  A trigger landing exactly on
    ``ready_at`` is accepted with the walk's 1e-9 tolerance (the survival
    convention) or refused without it; both are in the tree, they differ by
    one ulp of fight clock, so each author names its own rather than
    inheriting a default that would move its numbers.
    """

    __slots__ = ("_ready_at", "_seen", "cooldown_seconds", "inclusive")

    def __init__(self, cooldown_seconds: float = 0.0, *, inclusive: bool) -> None:
        self.cooldown_seconds = cooldown_seconds
        self.inclusive = inclusive
        self._ready_at = float("-inf")
        self._seen: set[Hashable] = set()

    @property
    def ready_at(self) -> float:
        """When the next trigger may be accepted."""
        return self._ready_at

    def accepts(self, time: float, key: Hashable | None = None) -> bool:
        """Whether this trigger authors.  An accepted key is consumed."""
        if key is not None and key in self._seen:
            return False
        if time + (_EPS if self.inclusive else 0.0) < self._ready_at:
            return False
        if key is not None:
            self._seen.add(key)
        return True

    def arm(self, time: float, *, cooldown: float | None = None) -> None:
        """Start the readiness clock from *time*."""
        self._ready_at = time + (
            self.cooldown_seconds if cooldown is None else cooldown
        )


# ---------------------------------------------------------------------------
# Per-cast-instance cadence
# ---------------------------------------------------------------------------


class InstanceCadence:
    """Per-instance trigger gating.

    Fimbulwinter uses ``once_only=True`` (one Everlasting shield per cast
    instance); interval cadences use ``interval_seconds`` with the first
    occurrence always allowed and repeats denied inside the window.
    """

    def public_receipt(self) -> dict[str, Any]:
        """JSON-safe cadence declaration."""
        return {
            "interval_seconds": self._interval,
            "once_only": self._once_only,
            "instances_seen": len(self._seen),
        }

    def __init__(
        self, *, interval_seconds: float = 0.0, once_only: bool = False
    ) -> None:
        if not math.isfinite(interval_seconds) or interval_seconds < 0.0:
            raise ValueError(
                f"InstanceCadence interval_seconds must be finite and >= 0, "
                f"got {interval_seconds!r}"
            )
        if interval_seconds > 0.0 and once_only:
            raise ValueError(
                "InstanceCadence cannot combine interval_seconds with once_only"
            )
        self._interval = interval_seconds
        self._once_only = once_only
        self._seen: dict[str, float] = {}

    def allow(self, time: float, instance: str | None) -> bool:
        """Whether a trigger for *instance* may proceed at *time*.

        An allowed instance is recorded here, so a repeat of it is judged
        against that record (Fimbulwinter's seen-casts consumption).
        """
        if instance is None:
            return True
        last = self._seen.get(instance)
        if last is not None:
            if self._once_only:
                return False
            if time - last < self._interval - _EPS:
                return False
        self._seen[instance] = time
        return True
