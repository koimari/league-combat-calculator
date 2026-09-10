"""How a stack is gained, refreshed, capped and expired, as one declaration."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from .state_timeline import SourceReceipt

RefreshPolicy = Literal["refresh", "extend", "replace", "none"]


ExpiryPolicy = Literal["all_at_once", "step_down"]


CapBehavior = Literal["noop", "refresh"]


@dataclass(frozen=True, slots=True)
class StackRule:
    """One typed stack declaration.

    Attributes:
        max_stacks: hard cap; gains at cap follow ``cap_behavior``.
        gain_per_application: stacks added per ordinary trigger.
        duration_seconds: stack duration.  With ``refresh="none"`` each
            stack owns its own duration from its own gain (Rengar
            Ferocity); otherwise the state keeps one shared deadline.
        refresh: ``"refresh"`` resets the shared deadline to the latest
            gain; ``"extend"`` moves it to at least gain+duration;
            ``"replace"`` sets the count absolutely; ``"none"`` uses
            per-stack timers and never refreshes.
        expiry: ``"all_at_once"`` clears the state at the deadline;
            ``"step_down"`` drains ``decay_stacks_per_step`` every
            ``expiry_step_seconds`` after the deadline (Ashe Focus).
        interval_seconds: per-instance gain cadence; a trigger whose
            instance already gained within the interval is denied.
            ``interval_key`` names the trigger field holding the
            instance identity; ``interval_gate_packets`` restricts the
            gate to those packet kinds (empty = gate every packet).
        gain_by_kind: per-trigger-kind gain override (Force of Nature's
            +2 on immobilize).
        cap_behavior: ``"noop"`` keeps the deadline unchanged on a
            capped gain (pinned for Ashe Focus); ``"refresh"`` still
            refreshes the deadline.
        combat_extension_seconds: >0 freezes expiry for that long after
            each gain or ``note_activity`` (Rengar's in-combat rule).
        payload: extra sourced rule data (e.g. Force of Nature's
            maximum-stack bonuses) attached to the declaration.
    """

    name: str
    max_stacks: int
    gain_per_application: int
    duration_seconds: float
    refresh: RefreshPolicy = "refresh"
    expiry: ExpiryPolicy = "all_at_once"
    expiry_step_seconds: float = 0.0
    decay_stacks_per_step: int = 1
    interval_seconds: float = 0.0
    interval_key: str | None = None
    interval_gate_packets: frozenset[str] = frozenset()
    gain_by_kind: Mapping[str, int] = field(default_factory=dict)
    cap_behavior: CapBehavior = "noop"
    combat_extension_seconds: float = 0.0
    payload: Mapping[str, Any] = field(default_factory=dict)

    @property
    def per_stack_timers(self) -> bool:
        """``refresh="none"``: every stack expires on its own clock."""
        return self.refresh == "none"

    source: SourceReceipt | None = None

    def validate(self) -> None:
        """Fail closed on an impossible declaration, naming state+source."""
        source = f" (source: {self.source.label})" if self.source is not None else ""
        if not self.name.strip():
            raise ValueError("StackRule requires a non-empty state name")
        if self.max_stacks < 1:
            raise ValueError(
                f"{self.name}: max_stacks must be >= 1, got {self.max_stacks}{source}"
            )
        if not math.isfinite(self.duration_seconds) or self.duration_seconds <= 0.0:
            raise ValueError(
                f"{self.name}: duration_seconds must be finite and > 0, got "
                f"{self.duration_seconds!r}{source}"
            )
        if self.refresh not in ("refresh", "extend", "replace", "none"):
            raise ValueError(
                f"{self.name}: unknown refresh policy {self.refresh!r}{source}"
            )
        if self.expiry not in ("all_at_once", "step_down"):
            raise ValueError(
                f"{self.name}: unknown expiry policy {self.expiry!r}{source}"
            )
        if self.expiry == "step_down" and (
            not math.isfinite(self.expiry_step_seconds)
            or self.expiry_step_seconds <= 0.0
        ):
            raise ValueError(
                f"{self.name}: step_down expiry needs positive "
                f"expiry_step_seconds{source}"
            )
        if self.decay_stacks_per_step < 1:
            raise ValueError(f"{self.name}: decay_stacks_per_step must be >= 1{source}")
        if self.gain_per_application < 1 and not self.gain_by_kind:
            raise ValueError(f"{self.name}: gain_per_application must be >= 1{source}")
        for kind, amount in self.gain_by_kind.items():
            if amount < 1:
                raise ValueError(
                    f"{self.name}: gain_by_kind[{kind!r}] must be >= 1{source}"
                )
        if not math.isfinite(self.interval_seconds) or self.interval_seconds < 0.0:
            raise ValueError(
                f"{self.name}: interval_seconds must be finite and >= 0{source}"
            )
        if self.interval_seconds > 0.0 and not self.interval_key:
            raise ValueError(
                f"{self.name}: interval_seconds > 0 requires interval_key{source}"
            )
        if self.cap_behavior not in ("noop", "refresh"):
            raise ValueError(
                f"{self.name}: unknown cap_behavior {self.cap_behavior!r}{source}"
            )
        if not math.isfinite(self.combat_extension_seconds) or (
            self.combat_extension_seconds < 0.0
        ):
            raise ValueError(
                f"{self.name}: combat_extension_seconds must be finite and "
                f">= 0{source}"
            )

    def public_receipt(self) -> dict[str, Any]:
        """JSON-safe declaration receipt (numbers + source)."""
        return {
            "name": self.name,
            "max_stacks": self.max_stacks,
            "gain_per_application": self.gain_per_application,
            "duration_seconds": self.duration_seconds,
            "refresh": self.refresh,
            "expiry": self.expiry,
            "expiry_step_seconds": self.expiry_step_seconds,
            "decay_stacks_per_step": self.decay_stacks_per_step,
            "interval_seconds": self.interval_seconds,
            "interval_key": self.interval_key,
            "interval_gate_packets": sorted(self.interval_gate_packets),
            "gain_by_kind": dict(self.gain_by_kind),
            "cap_behavior": self.cap_behavior,
            "combat_extension_seconds": self.combat_extension_seconds,
            "payload": dict(self.payload),
            "source": self.source.public() if self.source is not None else None,
        }
