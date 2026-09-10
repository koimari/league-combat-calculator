"""Typed mana resource ledger (roadmap P3 slice 1).

One account per participant and resource kind owns every mana transition:
current mana, maximum mana, maximum-mana growth, gain/restore, spend,
refund, regeneration, caps, stable same-time order, source ownership, and
public receipts.  The cast-admission walk in
``fight.rotation.resource_admission._apply_resource_limits`` is its only
runtime driver.

The sourced rules that transact on the account live beside it, one concept per
module: the event vocabulary, its operations and tiers in
:mod:`resource_events`, the one Manaflow passive in :mod:`manaflow_ledger`, and
Lost Chapter's Enlighten and Catalyst's Eternity in
:mod:`mana_item_schedules`.

Design rules (HANDOVER §11):

- Numerical values come from the consumer's typed accessors
  (``item_effects.required_effect_value``) and are attached to events as
  exact ``atoms`` (atom_id, hash) plus a source receipt on the typed
  declarations; the kernel never invents a number.  Manaflow's cadence and
  Enlighten's restore are rule declarations with source receipts (the atom
  catalog holds no atoms for them — verified by the P3S1 provenance audit).
- Categorical rules are small frozen declarations with public receipts.
- Deterministic ordering: :meth:`ResourceLedger.run` sorts events by
  ``(time, tier, sequence, insertion order)``; at one timestamp a lower
  tier applies first (restores/regen before casts), matching the engine's
  phase convention (restore phase 0, cast phase 1).
- Fail closed: unknown resource kind or operation, an event whose owner
  does not match the account, non-finite or negative authored amounts, and
  invalid clamp amounts all raise, naming the offending field.  Unclear
  runtime rules (an unproven Manaflow hit) become denial receipts, never
  guesses.

The empty string is a valid owner in standalone/kernel use (tests compose
kernel-generated events with one shared owner); the runtime driver always
keys accounts by a real participant owner (``FightConfig.resource_ledger_owner``,
default ``"main"``), so a production fight can never mint an anonymous
account.
"""

from __future__ import annotations

import math
from collections.abc import Iterable

from .resource_events import (
    _EPS,
    OP_GAIN,
    OP_MAX_INCREASE,
    OP_REFUND,
    OP_REGEN,
    OP_SPEND,
    RESOURCE_KIND_MANA,
    ResourceEvent,
    ResourceReceipt,
    _validate_event_shape,
)


class ResourceAccount:
    """One participant's account for one resource kind.

    ``current`` always stays within ``[0, maximum]``; over-restoration is
    receipted as CAPPED, and a spend beyond the current pool is denied with
    ``insufficient_resource``.  ``maximum`` is the opening maximum plus every
    accepted ``max_increase`` (Manaflow's bonus-mana growth); it never goes
    negative, and a max increase never moves ``current`` (the sourced
    Manaflow rule: the grant is MAX mana, not a restore).
    """

    def __init__(
        self,
        owner: str,
        *,
        kind: str = RESOURCE_KIND_MANA,
        maximum: float,
        current: float | None = None,
        regen_per_second: float = 0.0,
    ) -> None:
        if kind != RESOURCE_KIND_MANA:
            raise ValueError(
                f"unsupported resource kind {kind!r}; only "
                f"{RESOURCE_KIND_MANA!r} is certified in this slice"
            )
        if isinstance(maximum, bool) or not math.isfinite(float(maximum)):
            raise ValueError(
                f"resource account maximum must be finite, got {maximum!r}"
            )
        if float(maximum) < 0.0:
            raise ValueError(
                f"resource account maximum must be non-negative, got {maximum!r}"
            )
        if current is not None and (
            isinstance(current, bool) or not math.isfinite(float(current))
        ):
            raise ValueError(
                f"resource account current must be finite, got {current!r}"
            )
        opening_current = float(maximum) if current is None else float(current)
        if not (0.0 <= opening_current <= float(maximum) + _EPS):
            raise ValueError(
                f"resource account current {opening_current!r} is outside "
                f"[0, maximum={float(maximum)!r}]"
            )
        if isinstance(regen_per_second, bool) or not math.isfinite(
            float(regen_per_second)
        ):
            raise ValueError(
                f"regen_per_second must be finite, got {regen_per_second!r}"
            )
        self._owner = owner
        self._kind = kind
        self._base_maximum = float(maximum)
        self._maximum = float(maximum)
        self._current = min(opening_current, self._maximum)
        self._regen_per_second = float(regen_per_second)

    # ── read-only state ────────────────────────────────────────────────────
    @property
    def owner(self) -> str:
        return self._owner

    @property
    def kind(self) -> str:
        return self._kind

    @property
    def current(self) -> float:
        return self._current

    @property
    def maximum(self) -> float:
        return self._maximum

    @property
    def base_maximum(self) -> float:
        return self._base_maximum

    @property
    def bonus_maximum(self) -> float:
        return self._maximum - self._base_maximum

    # ── typed operations ───────────────────────────────────────────────────
    def apply(self, event: ResourceEvent) -> ResourceReceipt:
        """Apply one typed operation and return its receipt."""
        _validate_event_shape(event, owner=self._owner, kind=self._kind)
        amount = float(event.amount)
        before_current = self._current
        before_maximum = self._maximum
        accepted = True
        reason = "accepted"
        after_current = before_current
        after_maximum = before_maximum
        operation = event.operation

        if operation == OP_MAX_INCREASE:
            # Sourced Manaflow rule: bonus MAX mana growth does not move
            # current mana.
            after_maximum = before_maximum + amount
        elif operation in {OP_GAIN, OP_REGEN, OP_REFUND}:
            raised = before_current + amount
            if raised > before_maximum + _EPS:
                after_current = before_maximum
                reason = "CAPPED"
            else:
                after_current = raised
        elif operation == OP_SPEND:
            if amount > before_current + _EPS:
                accepted = False
                reason = "insufficient_resource"
            else:
                after_current = before_current - amount
        else:  # OP_CLAMP
            clamped = min(before_maximum, max(0.0, before_current))
            reason = "noop" if abs(clamped - before_current) <= _EPS else "clamped"
            after_current = clamped

        if accepted:
            self._current = after_current
            self._maximum = after_maximum
        return ResourceReceipt(
            owner=self._owner,
            kind=self._kind,
            operation=operation,
            amount=amount,
            time=float(event.time),
            source=event.source,
            sequence=int(event.sequence),
            tier=float(event.tier),
            atoms=tuple(event.atoms),
            current_before=before_current,
            maximum_before=before_maximum,
            current_after=after_current,
            maximum_after=after_maximum,
            accepted=accepted,
            reason=reason,
            detail=dict(event.detail),
        )


class ResourceLedger:
    """Append-only resource account plus its deterministic transition log."""

    def __init__(
        self,
        owner: str,
        *,
        kind: str = RESOURCE_KIND_MANA,
        maximum: float,
        current: float | None = None,
        regen_per_second: float = 0.0,
    ) -> None:
        self._account = ResourceAccount(
            owner,
            kind=kind,
            maximum=maximum,
            current=current,
            regen_per_second=regen_per_second,
        )
        self._receipts: list[ResourceReceipt] = []

    @property
    def account(self) -> ResourceAccount:
        return self._account

    def apply(self, event: ResourceEvent) -> ResourceReceipt:
        receipt = self._account.apply(event)
        self._receipts.append(receipt)
        return receipt

    def run(self, events: Iterable[ResourceEvent]) -> tuple[ResourceReceipt, ...]:
        """Apply events in the deterministic total order and return receipts.

        Sort key: ``(time, tier, sequence, insertion order)`` — the same
        convention the survival/damage walks use.  Ties at one
        ``(time, tier, sequence)`` are decided by insertion order (Python's
        stable sort), so a caller that feeds events in its own stable order
        gets a stable, rerunnable ledger.
        """
        ordered = sorted(
            events,
            key=lambda event: (
                float(event.time),
                float(event.tier),
                int(event.sequence),
            ),
        )
        return tuple(self.apply(event) for event in ordered)

    def receipts(self) -> tuple[ResourceReceipt, ...]:
        return tuple(self._receipts)
