"""Shared trigger and state-lifecycle kernel (roadmap P1).

One dependency-light leaf owns the small typed contracts every stateful
mechanic needs: trigger predicates, stack gain/loss, caps, durations,
expiry/refresh rules, cooldowns (global and per-target), charge pools,
lockout windows, and reset rules.  Consumers (Eclipse, Fimbulwinter,
Conqueror, Force of Nature, Ashe Focus, Rengar Ferocity) replace their
bespoke timer loops with kernel calls; their damage/shield/heal formulas
stay where they are.

Design rules (HANDOVER §11):

- Numerical values come from the data cache through the consumer's typed
  accessors and are attached to a :class:`SourceReceipt`; the kernel never
  invents a number.
- Categorical rules are small frozen declarations with public receipts.
- Deterministic event ordering is mandatory: every transition is recorded
  with ``(time, tier, sequence, insertion_order)`` and the receipt walk
  sorts with the same total order the survival/damage walks use
  (``(time, phase, sequence)``; expiry precedes gain at one timestamp,
  gain precedes cooldown start, cooldown readiness is inclusive).
- Public receipts expose every transition: gain, refresh, extend,
  replace, expire, consume, reset, cooldown start, lockout start/end,
  charge gain/spend, and explicit denials.
- Missing sourced values raise naming the state and attribute; an
  unsourced live mechanic the model lacks is documented by the consumer,
  never guessed here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Literal, Mapping

from .ability_spec import ACTION_BLOCKING_CC_KINDS

# Floating-point tolerance shared with the damage/survival walks.  All
# kernel comparisons use the same 1e-9 convention as the engine receipts.
_EPS = 1e-9


# ---------------------------------------------------------------------------
# Source receipts
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SourceReceipt:
    """One reviewed provenance record for a kernel declaration.

    ``revision_id`` 0 with a cache-backed ``revision_timestamp`` marks a
    value reviewed from the local data cache rather than a pinned wiki
    revision (the same convention ``defensive_effects`` uses for its
    cache-backed defense sources).
    """

    label: str
    url: str
    revision_id: int = 0
    revision_timestamp: str = "cached data (patch cache)"
    key: str | None = None

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any]) -> "SourceReceipt":
        """Adapt the two receipt spellings used in this codebase.

        Item option rows publish ``source_url``/``source_revision_id``;
        champion and defense sources publish ``label``/``url``/
        ``revision_id``/``revision_timestamp``.
        """
        url = str(
            mapping.get("source_url")
            or mapping.get("url")
            or "https://wiki.leagueoflegends.com"
        )
        return cls(
            label=str(mapping.get("label") or mapping.get("item") or url),
            url=url,
            revision_id=int(mapping.get("source_revision_id", 0) or 0),
            revision_timestamp=str(
                mapping.get("revision_timestamp") or "cached data (patch cache)"
            ),
        )

    def public(self) -> dict[str, Any]:
        """JSON-safe public receipt for this source record."""
        row: dict[str, Any] = {
            "label": self.label,
            "url": self.url,
            "revision_id": self.revision_id,
            "revision_timestamp": self.revision_timestamp,
        }
        if self.key is not None:
            row["key"] = self.key
        return row


# ---------------------------------------------------------------------------
# Transitions and deterministic ordering
# ---------------------------------------------------------------------------

# Ordered tiers mirror the survival walk's phase ordering at one timestamp:
# scheduled expiry applies before readiness unlocks, readiness before new
# state, consume/reset after the gains they depend on, and cooldown start
# after the proc that triggers it.  A lower tier sorts first.
TIER_EXPIRE = -2.0
TIER_READY = -1.0
TIER_GAIN = 0.0
TIER_CONSUME = 0.5
TIER_COOLDOWN_START = 1.0

TransitionKind = Literal[
    "gain",
    "refresh",
    "extend",
    "replace",
    "expire",
    "consume",
    "consume_denied",
    "reset",
    "gain_denied",
    "proc",
    "cooldown_start",
    "trigger_skipped",
    "charge_gain",
    "charge_spend",
    "charge_denied",
    "lockout_start",
    "lockout_end",
    "combat_freeze",
]


@dataclass(frozen=True, slots=True)
class Transition:
    """One timestamped state transition in the kernel's total order."""

    time: float
    kind: TransitionKind
    sequence: int
    tier: float
    detail: Mapping[str, Any] = field(default_factory=dict)

    def public(self) -> dict[str, Any]:
        """JSON-safe receipt; ``detail`` rides under its own key so the
        top-level ``time``/``kind``/``sequence``/``tier`` stay stable."""
        return {
            "time": self.time,
            "kind": self.kind,
            "sequence": self.sequence,
            "tier": self.tier,
            "detail": dict(self.detail),
        }


class StateTimeline:
    """Append-only transition log with a deterministic total order.

    Sort key: ``(time, tier, sequence, insertion_order)``.  The caller
    feeds transitions in the same ``(time, sequence)`` order the
    survival/damage walks use; ties at one ``(time, sequence)`` are
    decided by tier (expiry before gain before cooldown start), and
    insertion order breaks the final tie deterministically.
    """

    def __init__(self) -> None:
        self._transitions: list[Transition] = []
        self._order = 0

    def record(
        self,
        time: float,
        kind: TransitionKind,
        *,
        sequence: int = 0,
        tier: float = TIER_GAIN,
        detail: Mapping[str, Any] | None = None,
    ) -> Transition:
        """Record one transition and return it."""
        transition = Transition(
            time=time,
            kind=kind,
            sequence=sequence,
            tier=tier,
            detail=dict(detail or {}),
        )
        self._transitions.append(transition)
        self._order += 1
        return transition

    def transitions(self) -> list[Transition]:
        """The deterministic total order over recorded transitions."""
        return sorted(
            self._transitions,
            key=lambda t: (
                t.time,
                t.tier,
                t.sequence,
                self._transitions.index(t),
            ),
        )

    def public_receipt(self) -> list[dict[str, Any]]:
        """JSON-safe ordered receipt for every transition."""
        return [transition.public() for transition in self.transitions()]

    def __len__(self) -> int:
        return len(self._transitions)


@dataclass(frozen=True, slots=True)
class CcTriggerRule:
    """Crowd-control trigger classification (Fimbulwinter Everlasting).

    Everlasting fires only from an explicitly authored immobilize, or a
    slow for a melee holder.  ``immobilize_kinds`` is the sourced
    action-blocking vocabulary (``ability_spec.ACTION_BLOCKING_CC_KINDS``);
    a bare ``crowd_control`` flag is intentionally NOT enough to
    distinguish the immobilize/slow branches.
    """

    name: str
    immobilize_kinds: frozenset[str] = field(
        default_factory=lambda: frozenset(ACTION_BLOCKING_CC_KINDS)
    )
    slow_kind: str = "slow"
    slow_melee_only: bool = True
    source: SourceReceipt | None = None

    def is_candidate(self, event: Mapping[str, Any]) -> bool:
        """Whether the event can carry a qualifying CC trigger at all."""
        kind = str(event.get("cc_kind", "")).lower().strip()
        if kind in self.immobilize_kinds or kind == self.slow_kind:
            return True
        return bool(
            event.get("immobilized")
            or event.get("hard_cc")
            or event.get("crowd_control")
            or event.get("slowed")
            or event.get("slow")
        )

    def match(self, event: Mapping[str, Any], *, is_melee: bool) -> str:
        """Return ``"immobilize"``, ``"slow"``, or ``""`` for one event."""
        kind = str(event.get("cc_kind", "")).lower().strip()
        if kind in self.immobilize_kinds:
            return "immobilize"
        if bool(event.get("immobilized")) or bool(event.get("hard_cc")):
            return "immobilize"
        if kind == self.slow_kind or bool(event.get("slowed") or event.get("slow")):
            if self.slow_melee_only and not is_melee:
                return ""
            return "slow"
        return ""

    def denial_reason(self, event: Mapping[str, Any], *, is_melee: bool) -> str | None:
        """Name why a CC-adjacent event cannot fire, or ``None``.

        ``None`` means either the event is NOT a CC candidate at all (no
        crowd-control metadata — nothing to deny, so no receipt) or it
        matched an eligible branch (accepted).  Denials are named so the
        consumer can receipt them fail-closed instead of silently skipping:

        - ``"unknown_cc_kind"``: a ``cc_kind`` string outside the sourced
          vocabulary (neither an action-blocking kind nor the slow kind);
        - ``"untyped_cc"``: only a bare ``crowd_control`` flag, which
          cannot distinguish the immobilize/slow branches;
        - ``"ranged_slow"``: a slow-classified event whose holder is not
          melee (``slow_melee_only``).

        The adjacency test is deliberately broader than
        :meth:`is_candidate`: an event carrying a ``cc_kind`` string
        OUTSIDE the sourced vocabulary is CC-adjacent (receipted as
        ``unknown_cc_kind``) even though it can never match a branch.
        """
        if self.match(event, is_melee=is_melee):
            return None
        kind = str(event.get("cc_kind", "")).lower().strip()
        has_kind = bool(kind)
        has_flag = bool(
            event.get("immobilized")
            or event.get("hard_cc")
            or event.get("crowd_control")
            or event.get("slowed")
            or event.get("slow")
        )
        if not has_kind and not has_flag:
            return None
        if has_kind and kind not in self.immobilize_kinds and kind != self.slow_kind:
            return "unknown_cc_kind"
        if kind == self.slow_kind or bool(event.get("slowed") or event.get("slow")):
            return "ranged_slow"
        return "untyped_cc"

    def public_receipt(self) -> dict[str, Any]:
        """JSON-safe public receipt."""
        return {
            "name": self.name,
            "immobilize_kinds": sorted(self.immobilize_kinds),
            "slow_kind": self.slow_kind,
            "slow_melee_only": self.slow_melee_only,
            "source": self.source.public() if self.source is not None else None,
        }


# ---------------------------------------------------------------------------
# Stack rules and timed stack state
# ---------------------------------------------------------------------------

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
                starting_time,
                "gain",
                sequence=0,
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
        if self.rule.refresh == "none":
            if not self._entries:
                return None
            return min(entry.gained_at for entry in self._entries) + (
                self.rule.duration_seconds
            )
        return self._shared_deadline

    def _is_frozen(self, time: float) -> bool:
        return self._freeze_until is not None and time < self._freeze_until - _EPS

    # -- expiry materialization --------------------------------------------

    def _materialize_expiries(self, time: float, sequence: int) -> list[Transition]:
        """Apply expiry at *time* and record every transition."""
        out: list[Transition] = []
        if self._is_frozen(time) or not self._entries:
            return out
        if self.rule.refresh == "none":
            # Per-stack timers: each stack dies 1 duration after its own
            # gain, oldest first.
            while self._entries:
                entry = self._entries[0]
                if time + _EPS < entry.gained_at + self.rule.duration_seconds:
                    break
                self._entries.pop(0)
                out.append(
                    self._timeline.record(
                        time,
                        "expire",
                        sequence=sequence,
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
        if time + _EPS < deadline:
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
                    time,
                    "expire",
                    sequence=sequence,
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
            if time + _EPS < step_time:
                break
            before = len(self._entries)
            remove = min(self.rule.decay_stacks_per_step, before)
            for _ in range(remove):
                self._entries.pop(0)
            self._decay_steps_applied += 1
            out.append(
                self._timeline.record(
                    time,
                    "expire",
                    sequence=sequence,
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
        time: float,
        *,
        kind: str = "",
        packet: str = "",
        instance: str | None = None,
        meta: Mapping[str, Any] | None = None,
        sequence: int = 0,
    ) -> list[Transition]:
        """Process one trigger at *time*; return its transitions.

        Expiry at the trigger timestamp materializes first (recorded),
        then the interval gate, then the gain/refresh per the rule.
        ``meta`` may carry the rule's ``interval_key`` field when
        ``instance`` is not given.
        """
        if not math.isfinite(time) or time < 0.0:
            raise ValueError(
                f"{self.rule.name}: trigger time must be finite and >= 0, "
                f"got {time!r}"
            )
        out = self._materialize_expiries(time, sequence)

        # Combat freeze: dealing damage (a gain trigger) re-arms the
        # expiry freeze when the rule declares one.
        if self.rule.combat_extension_seconds > 0.0:
            self._freeze_until = max(
                self._freeze_until if self._freeze_until is not None else float("-inf"),
                time + self.rule.combat_extension_seconds,
            )
            out.append(
                self._timeline.record(
                    time,
                    "combat_freeze",
                    sequence=sequence,
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
                            time,
                            "gain_denied",
                            sequence=sequence,
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
                        time,
                        "gain_denied",
                        sequence=sequence,
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
                    time,
                    "refresh",
                    sequence=sequence,
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
        elif self.rule.refresh == "none":
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
                time,
                transition_kind,
                sequence=sequence,
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
        """Public wrapper for :meth:`_materialize_expiries` (the walk
        consumers use it to close a stack state at the fight end)."""
        return self._materialize_expiries(time, sequence)

    def note_activity(
        self,
        time: float,
        *,
        kind: str = "",
        sequence: int = 0,
    ) -> Transition | None:
        """Re-arm the combat-expiry freeze from a damage event."""
        if self.rule.combat_extension_seconds <= 0.0:
            return None
        self._freeze_until = max(
            self._freeze_until if self._freeze_until is not None else float("-inf"),
            time + self.rule.combat_extension_seconds,
        )
        return self._timeline.record(
            time,
            "combat_freeze",
            sequence=sequence,
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
        time: float,
        *,
        sequence: int = 0,
        meta: Mapping[str, Any] | None = None,
    ) -> Transition | None:
        """Consume all stacks when at cap; return the transition or None.

        Below cap the machine records a denial and returns None so the
        caller can decide what the trigger does (the champion module
        prices the base ability).  Expiries at the consume timestamp are
        materialized and recorded first.
        """
        self._materialize_expiries(time, sequence)
        if self.stacks < self.rule.max_stacks:
            self._timeline.record(
                time,
                "consume_denied",
                sequence=sequence,
                tier=TIER_CONSUME,
                detail={
                    "state": self.rule.name,
                    "reason": "below_cap",
                    "stacks_before": self.stacks,
                    "stacks_after": self.stacks,
                },
            )
            return None
        before = self.stacks
        self._entries.clear()
        self._last_gain_time = None
        self._shared_deadline = None
        self._decay_steps_applied = 0
        self._instances.clear()
        transition = self._timeline.record(
            time,
            "consume",
            sequence=sequence,
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
        return transition

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
        before = self.stacks
        self._entries.clear()
        self._last_gain_time = None
        self._shared_deadline = None
        self._decay_steps_applied = 0
        self._instances.clear()
        if before == to:
            return None
        return self._timeline.record(
            time,
            "reset",
            sequence=sequence,
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


# ---------------------------------------------------------------------------
# Window stack gate (Eclipse's two-hit pair + per-target cooldown)
# ---------------------------------------------------------------------------


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
        target = target or "default"
        ready_at = self._ready_at.get(target, float("-inf"))
        if time + _EPS < ready_at:
            self._timeline.record(
                time,
                "trigger_skipped",
                sequence=sequence,
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
                    time,
                    "expire",
                    sequence=sequence,
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
                time,
                "gain",
                sequence=sequence,
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
            time,
            "proc",
            sequence=sequence,
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
            time,
            "cooldown_start",
            sequence=sequence,
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
        time: float,
        *,
        target: str = "default",
        sequence: int = 0,
        meta: Mapping[str, Any] | None = None,
    ) -> Transition:
        """Start the cooldown now; returns the start transition."""
        key = target if self.rule.per_target else "default"
        cooldown_until = time + self.rule.cooldown_seconds
        self._ready_at[key] = cooldown_until
        transition = self._timeline.record(
            time,
            "cooldown_start",
            sequence=sequence,
            tier=TIER_COOLDOWN_START,
            detail={
                "state": self.rule.name,
                "target": key,
                "cooldown_until": cooldown_until,
                "per_target": self.rule.per_target,
                "trigger_source": str((meta or {}).get("source") or "trigger"),
            },
        )
        return transition

    def public_receipt(self) -> dict[str, Any]:
        """JSON-safe public receipt."""
        return {
            "state": self.rule.name,
            "rule": self.rule.public_receipt(),
            "ready_at": dict(self._ready_at),
            "transitions": self._timeline.public_receipt(),
        }


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

        A consumed instance is recorded here; the caller must NOT retry
        the same instance later (matches Fimbulwinter's seen-casts
        consumption semantics).
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
