"""The timed stack state a stack rule drives."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .stack_rules import StackRule
from .state_timeline import (
    _EPS,
    TIER_CONSUME,
    TIER_EXPIRE,
    TIER_GAIN,
    EventStamp,
    StateTimeline,
    Transition,
    TransitionKind,
)


@dataclass(frozen=True, slots=True)
class _StackEntry:
    """One live stack: when it was gained and by what trigger kind."""

    gained_at: float
    source_tag: str


class TimedStackState:
    """Deterministic timed-stack machine with public transition receipts.

    Feed timestamped triggers through :meth:`apply_gain` in the same
    ``(time, sequence)`` total order the fight walk uses; the machine
    materializes expiries at the trigger timestamp, applies the interval
    gate, refreshes per the rule, and records every transition.
    """

    def __init__(
        self,
        rule: StackRule,
        *,
        starting_stacks: int = 0,
        starting_time: float = 0.0,
        timeline: StateTimeline | None = None,
    ) -> None:
        rule.validate()
        self.rule = rule
        self._timeline = timeline if timeline is not None else StateTimeline()
        seed = max(0, min(int(starting_stacks), rule.max_stacks))
        self._entries: list[_StackEntry] = [
            _StackEntry(starting_time, "option") for _ in range(seed)
        ]
        self._last_gain_time: float | None = starting_time if seed else None
        self._shared_deadline: float | None = (
            starting_time + rule.duration_seconds if seed else None
        )
        self._decay_steps_applied = 0
        self._instances: dict[str, float] = {}
        self._freeze_until: float | None = None
        if seed:
            self._timeline.record(
                EventStamp(starting_time),
                "gain",
                tier=TIER_GAIN,
                detail={
                    "state": rule.name,
                    "trigger_kind": "option",
                    "trigger_source": "option",
                    "stacks_before": 0,
                    "stacks_after": seed,
                    "expires_at": self._expires_at(),
                },
            )

    # -- state queries -----------------------------------------------------

    @property
    def stacks(self) -> int:
        """Live stack count after the last processed timestamp."""
        return len(self._entries)

    @property
    def timeline(self) -> StateTimeline:
        """The transition log in walk order."""
        return self._timeline

    def _expires_at(self) -> float | None:
        if self.rule.per_stack_timers:
            if not self._entries:
                return None
            return min(entry.gained_at for entry in self._entries) + (
                self.rule.duration_seconds
            )
        return self._shared_deadline

    def _is_frozen(self, time: float) -> bool:
        return self._freeze_until is not None and time < self._freeze_until - _EPS

    # -- expiry materialization --------------------------------------------

    def _materialize_expiries(self, stamp: EventStamp) -> list[Transition]:
        """Apply expiry at the stamp's time and record every transition."""
        out: list[Transition] = []
        if self._is_frozen(stamp.time) or not self._entries:
            return out
        if self.rule.per_stack_timers:
            # Per-stack timers: each stack dies 1 duration after its own
            # gain, oldest first.
            while self._entries:
                entry = self._entries[0]
                if stamp.time + _EPS < entry.gained_at + self.rule.duration_seconds:
                    break
                self._entries.pop(0)
                out.append(
                    self._timeline.record(
                        stamp,
                        "expire",
                        tier=TIER_EXPIRE,
                        detail={
                            "state": self.rule.name,
                            "stacks_before": len(self._entries) + 1,
                            "stacks_after": len(self._entries),
                            "expires_at": entry.gained_at + self.rule.duration_seconds,
                            "source_tag": entry.source_tag,
                            "decayed": 1,
                        },
                    )
                )
            return out
        deadline = self._shared_deadline
        if deadline is None:
            return out
        if stamp.time + _EPS < deadline:
            return out
        if self.rule.expiry == "all_at_once":
            if not self._entries:
                return out
            before = len(self._entries)
            self._entries.clear()
            self._last_gain_time = None
            self._shared_deadline = None
            out.append(
                self._timeline.record(
                    stamp,
                    "expire",
                    tier=TIER_EXPIRE,
                    detail={
                        "state": self.rule.name,
                        "stacks_before": before,
                        "stacks_after": 0,
                        "expires_at": deadline,
                    },
                )
            )
            return out
        # step_down: drain decay_stacks_per_step every expiry_step_seconds
        # starting AT the deadline ("stacks expire one by one every second
        # when the duration ends").
        step = self.rule.expiry_step_seconds
        while self._entries:
            step_index = self._decay_steps_applied + 1
            step_time = deadline + (step_index - 1) * step
            if stamp.time + _EPS < step_time:
                break
            before = len(self._entries)
            remove = min(self.rule.decay_stacks_per_step, before)
            for _ in range(remove):
                self._entries.pop(0)
            self._decay_steps_applied += 1
            out.append(
                self._timeline.record(
                    stamp,
                    "expire",
                    tier=TIER_EXPIRE,
                    detail={
                        "state": self.rule.name,
                        "stacks_before": before,
                        "stacks_after": len(self._entries),
                        "expires_at": step_time,
                        "decayed": remove,
                    },
                )
            )
            if len(self._entries) == 0:
                self._last_gain_time = None
                self._shared_deadline = None
        return out

    # -- gains -------------------------------------------------------------

    def apply_gain(
        self,
        stamp: EventStamp,
        *,
        kind: str = "",
        packet: str = "",
        instance: str | None = None,
        meta: Mapping[str, Any] | None = None,
    ) -> list[Transition]:
        """Process one trigger at the stamp's time; return its transitions.

        Expiry at the trigger timestamp materializes first (recorded),
        then the interval gate, then the gain/refresh per the rule.
        ``meta`` may carry the rule's ``interval_key`` field when
        ``instance`` is not given.
        """
        time = stamp.time
        if not math.isfinite(time) or time < 0.0:
            raise ValueError(
                f"{self.rule.name}: trigger time must be finite and >= 0, "
                f"got {time!r}"
            )
        out = self._materialize_expiries(stamp)

        # Combat freeze: dealing damage (a gain trigger) re-arms the
        # expiry freeze when the rule declares one.
        if self.rule.combat_extension_seconds > 0.0:
            self._freeze_until = max(
                self._freeze_until if self._freeze_until is not None else float("-inf"),
                time + self.rule.combat_extension_seconds,
            )
            out.append(
                self._timeline.record(
                    stamp,
                    "combat_freeze",
                    tier=TIER_GAIN,
                    detail={
                        "state": self.rule.name,
                        "freeze_until": self._freeze_until,
                        "stacks_before": self.stacks,
                        "stacks_after": self.stacks,
                    },
                )
            )

        # Per-instance interval gate.
        interval = self.rule.interval_seconds
        if interval > 0.0 and (
            not self.rule.interval_gate_packets
            or packet in self.rule.interval_gate_packets
        ):
            key = (
                instance
                if instance is not None
                else (
                    str(meta.get(self.rule.interval_key, ""))
                    if meta is not None and self.rule.interval_key
                    else ""
                )
            )
            if key:
                last = self._instances.get(key)
                if last is not None and time - last < interval - _EPS:
                    out.append(
                        self._timeline.record(
                            stamp,
                            "gain_denied",
                            tier=TIER_GAIN,
                            detail={
                                "state": self.rule.name,
                                "reason": "interval_gate",
                                "gate_key": key,
                                "gate_until": last + interval,
                                "stacks_before": self.stacks,
                                "stacks_after": self.stacks,
                            },
                        )
                    )
                    return out
                self._instances[key] = time

        amount = int(self.rule.gain_by_kind.get(kind, self.rule.gain_per_application))
        if amount < 1:
            raise ValueError(
                f"{self.rule.name}: trigger kind {kind!r} resolves to a "
                f"non-positive gain"
            )

        before = self.stacks
        expires_at: float | None = None
        if before >= self.rule.max_stacks:
            if self.rule.cap_behavior == "noop":
                out.append(
                    self._timeline.record(
                        stamp,
                        "gain_denied",
                        tier=TIER_GAIN,
                        detail={
                            "state": self.rule.name,
                            "reason": "at_cap",
                            "stacks_before": before,
                            "stacks_after": before,
                            "expires_at": self._expires_at(),
                        },
                    )
                )
                return out
            # cap_behavior == "refresh": deadline refreshes, count stays.
            self._last_gain_time = time
            self._shared_deadline = time + self.rule.duration_seconds
            self._decay_steps_applied = 0
            out.append(
                self._timeline.record(
                    stamp,
                    "refresh",
                    tier=TIER_GAIN,
                    detail={
                        "state": self.rule.name,
                        "stacks_before": before,
                        "stacks_after": before,
                        "expires_at": self._shared_deadline,
                    },
                )
            )
            return out

        if self.rule.refresh == "replace":
            self._entries = [
                _StackEntry(time, kind or "trigger") for _ in range(amount)
            ]
            self._last_gain_time = time
            self._shared_deadline = time + self.rule.duration_seconds
            self._decay_steps_applied = 0
            after = self.stacks
            expires_at = self._shared_deadline
            transition_kind: TransitionKind = "replace"
        elif self.rule.per_stack_timers:
            self._entries.append(_StackEntry(time, kind or "trigger"))
            self._last_gain_time = time
            after = self.stacks
            expires_at = time + self.rule.duration_seconds
            transition_kind = "gain"
        else:
            if self.rule.refresh == "extend":
                self._shared_deadline = max(
                    self._shared_deadline or float("-inf"),
                    time + self.rule.duration_seconds,
                )
                transition_kind = "extend" if before > 0 else "gain"
            else:  # refresh
                self._shared_deadline = time + self.rule.duration_seconds
                transition_kind = "refresh" if before > 0 else "gain"
            self._entries = [
                *self._entries,
                *[_StackEntry(time, kind or "trigger") for _ in range(amount)],
            ]
            self._last_gain_time = time
            after = self.stacks
            expires_at = self._shared_deadline
            self._decay_steps_applied = 0

        out.append(
            self._timeline.record(
                stamp,
                transition_kind,
                tier=TIER_GAIN,
                detail={
                    "state": self.rule.name,
                    "trigger_kind": kind,
                    "trigger_source": str(
                        (meta or {}).get("source") or kind or "trigger"
                    ),
                    "stacks_before": before,
                    "stacks_after": after,
                    "expires_at": expires_at,
                    "refreshed": transition_kind == "refresh",
                    "extended": transition_kind == "extend",
                    "replaced": transition_kind == "replace",
                },
            )
        )
        return out

    def materialize_expiries(self, time: float, sequence: int = 0) -> list[Transition]:
        """Close a stack state at the fight end, for the walk consumers."""
        return self._materialize_expiries(EventStamp(time, sequence))

    def note_activity(
        self,
        stamp: EventStamp,
        *,
        kind: str = "",
    ) -> Transition | None:
        """Re-arm the combat-expiry freeze from a damage event."""
        if self.rule.combat_extension_seconds <= 0.0:
            return None
        self._freeze_until = max(
            self._freeze_until if self._freeze_until is not None else float("-inf"),
            stamp.time + self.rule.combat_extension_seconds,
        )
        return self._timeline.record(
            stamp,
            "combat_freeze",
            tier=TIER_GAIN,
            detail={
                "state": self.rule.name,
                "trigger_kind": kind,
                "freeze_until": self._freeze_until,
                "stacks_before": self.stacks,
                "stacks_after": self.stacks,
            },
        )

    # -- consume / reset ---------------------------------------------------

    def consume(
        self,
        stamp: EventStamp,
        *,
        meta: Mapping[str, Any] | None = None,
    ) -> Transition | None:
        """Consume all stacks when at cap; return the transition or None.

        Below cap the machine records a denial and returns None so the
        caller can decide what the trigger does (the champion module
        prices the base ability).  Expiries at the consume timestamp are
        materialized and recorded first.
        """
        self._materialize_expiries(stamp)
        if self.stacks < self.rule.max_stacks:
            self._timeline.record(
                stamp,
                "consume_denied",
                tier=TIER_CONSUME,
                detail={
                    "state": self.rule.name,
                    "reason": "below_cap",
                    "stacks_before": self.stacks,
                    "stacks_after": self.stacks,
                },
            )
            return None
        before = self._wipe()
        return self._timeline.record(
            stamp,
            "consume",
            tier=TIER_CONSUME,
            detail={
                "state": self.rule.name,
                "stacks_before": before,
                "stacks_after": 0,
                "empowered": True,
                "expires_at": None,
                "trigger_source": str((meta or {}).get("source") or "consume"),
            },
        )

    def _wipe(self) -> int:
        """Drop every entry and timer; returns the stack count they held."""
        before = self.stacks
        self._entries.clear()
        self._last_gain_time = None
        self._shared_deadline = None
        self._decay_steps_applied = 0
        self._instances.clear()
        return before

    def reset(
        self,
        time: float,
        *,
        to: int = 0,
        sequence: int = 0,
        reason: str = "reset",
    ) -> Transition | None:
        """Reset the state to *to*; a no-op reset is silent (idempotent)."""
        to = max(0, min(int(to), self.rule.max_stacks))
        if self.stacks == to and reason != "reset":
            return None
        before = self._wipe()
        if before == to:
            return None
        return self._timeline.record(
            EventStamp(time, sequence),
            "reset",
            tier=TIER_CONSUME,
            detail={
                "state": self.rule.name,
                "reason": reason,
                "stacks_before": before,
                "stacks_after": to,
            },
        )

    # -- receipts ----------------------------------------------------------

    def public_receipt(self) -> dict[str, Any]:
        """JSON-safe state snapshot plus the full transition receipt."""
        return {
            "state": self.rule.name,
            "stacks": self.stacks,
            "rule": self.rule.public_receipt(),
            "freeze_until": self._freeze_until,
            "expires_at": self._expires_at(),
            "transitions": self._timeline.public_receipt(),
        }
