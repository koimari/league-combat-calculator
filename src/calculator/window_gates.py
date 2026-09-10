"""The window stack gate, its two hit pair and its per-target cooldown."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .state_timeline import (
    _EPS,
    TIER_COOLDOWN_START,
    TIER_EXPIRE,
    TIER_GAIN,
    EventStamp,
    SourceReceipt,
    StateTimeline,
)


@dataclass(frozen=True, slots=True)
class WindowGateRule:
    """A stack-gated proc declaration (Eclipse Ever Rising Moon).

    ``stacks_required`` hits must land within ``window_seconds``; the
    completed pair fires the proc and starts the per-target cooldown.
    """

    name: str
    stacks_required: int
    window_seconds: float
    cooldown_seconds: float
    per_target: bool = True
    source: SourceReceipt | None = None

    def validate(self) -> None:
        """Fail closed on an impossible declaration."""
        source = f" (source: {self.source.label})" if self.source is not None else ""
        if self.stacks_required < 2:
            raise ValueError(
                f"{self.name}: stacks_required must be >= 2, got "
                f"{self.stacks_required}{source}"
            )
        if not math.isfinite(self.window_seconds) or self.window_seconds <= 0.0:
            raise ValueError(
                f"{self.name}: window_seconds must be finite and > 0{source}"
            )
        if not math.isfinite(self.cooldown_seconds) or self.cooldown_seconds < 0.0:
            raise ValueError(
                f"{self.name}: cooldown_seconds must be finite and >= 0{source}"
            )

    def public_receipt(self) -> dict[str, Any]:
        """JSON-safe public receipt."""
        return {
            "name": self.name,
            "stacks_required": self.stacks_required,
            "window_seconds": self.window_seconds,
            "cooldown_seconds": self.cooldown_seconds,
            "per_target": self.per_target,
            "source": self.source.public() if self.source is not None else None,
        }


@dataclass(frozen=True, slots=True)
class WindowProc:
    """One completed pair: the proc event the caller prices."""

    time: float
    sequence: int
    precision: str
    target: str


class WindowStackGate:
    """Eclipse's stack-window gate with per-target cooldown bookkeeping.

    Faithful port of the engine's pair walk: triggers on cooldown are
    skipped without touching the window; a trigger more than
    ``window_seconds`` after the window start restarts the window; a
    second trigger inside the window completes the pair, starts the
    per-target cooldown, and clears the window.
    """

    def __init__(self, rule: WindowGateRule) -> None:
        rule.validate()
        self.rule = rule
        self._timeline = StateTimeline()
        self._first_stack: dict[str, float] = {}
        self._ready_at: dict[str, float] = {}
        self._procs: list[WindowProc] = []

    @property
    def timeline(self) -> StateTimeline:
        """The transition log in walk order."""
        return self._timeline

    def feed(
        self,
        time: float,
        *,
        sequence: int = 0,
        precision: str = "exact",
        target: str | None = None,
    ) -> list[WindowProc]:
        """Process one trigger; return procs completed at this timestamp."""
        stamp = EventStamp(time, sequence)
        target = target or "default"
        ready_at = self._ready_at.get(target, float("-inf"))
        if time + _EPS < ready_at:
            self._timeline.record(
                stamp,
                "trigger_skipped",
                tier=TIER_GAIN,
                detail={
                    "state": self.rule.name,
                    "reason": "per_target_cooldown",
                    "target": target,
                    "cooldown_until": ready_at,
                    "stacks_before": 1 if target in self._first_stack else 0,
                    "stacks_after": 1 if target in self._first_stack else 0,
                },
            )
            return []
        first = self._first_stack.get(target)
        if first is None or time - first > self.rule.window_seconds + _EPS:
            if first is not None:
                self._timeline.record(
                    stamp,
                    "expire",
                    tier=TIER_EXPIRE,
                    detail={
                        "state": self.rule.name,
                        "reason": "window_lapse",
                        "target": target,
                        "stacks_before": 1,
                        "stacks_after": 0,
                        "expires_at": first + self.rule.window_seconds,
                    },
                )
            self._first_stack[target] = time
            self._timeline.record(
                stamp,
                "gain",
                tier=TIER_GAIN,
                detail={
                    "state": self.rule.name,
                    "target": target,
                    "stacks_before": 0,
                    "stacks_after": 1,
                    "expires_at": time + self.rule.window_seconds,
                },
            )
            return []
        proc = WindowProc(
            time=time, sequence=sequence, precision=precision, target=target
        )
        self._procs.append(proc)
        self._timeline.record(
            stamp,
            "proc",
            tier=TIER_GAIN,
            detail={
                "state": self.rule.name,
                "target": target,
                "window_start": first,
                "stacks_before": 2,
                "stacks_after": 0,
                "reset": True,
            },
        )
        cooldown_until = time + self.rule.cooldown_seconds
        self._ready_at[target] = cooldown_until
        self._timeline.record(
            stamp,
            "cooldown_start",
            tier=TIER_COOLDOWN_START,
            detail={
                "state": self.rule.name,
                "target": target,
                "cooldown_until": cooldown_until,
                "per_target": self.rule.per_target,
            },
        )
        self._first_stack.pop(target, None)
        return [proc]

    def procs(self) -> list[WindowProc]:
        """Completed proc events so far."""
        return list(self._procs)

    def public_receipt(self) -> dict[str, Any]:
        """JSON-safe public receipt."""
        return {
            "rule": self.rule.public_receipt(),
            "procs": [
                {
                    "time": proc.time,
                    "sequence": proc.sequence,
                    "precision": proc.precision,
                    "target": proc.target,
                }
                for proc in self._procs
            ],
            "transitions": self._timeline.public_receipt(),
        }
