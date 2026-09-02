"""Typed mana resource ledger (roadmap P3 slice 1).

One account per participant and resource kind owns every mana transition:
current mana, maximum mana, maximum-mana growth, gain/restore, spend,
refund, regeneration, caps, stable same-time order, source ownership, and
public receipts.  Manaflow and Lost Chapter (Enlighten) are runtime
consumers; Catalyst's Eternity and Essence Reaver's Spellblade restores
ride the same account as external gain operations, and Eternity's
mana-spent heal is a pure projection of the account's accepted spend
receipts (``catalyst_eternity_heal_schedule``) — the cast-admission walk
in ``damage._apply_resource_limits`` is the only driver.

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
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, fields
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


# ---------------------------------------------------------------------------
# Manaflow (Tear of the Goddess and its four upgrades)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ManaflowDeclaration:
    """Sourced Manaflow rule; the holders share a shape and not a number."""

    item: str
    charge_interval: float
    max_charges: int
    bonus_mana_per_trigger: float
    bonus_mana_per_champion: float
    bonus_mana_max: float
    source_url: str
    source_revision_id: int
    atom: tuple[str, str]

    def __post_init__(self) -> None:
        if not self.item.strip():
            raise ValueError("ManaflowDeclaration.item must name the holder")
        for name, value in (
            ("charge_interval", self.charge_interval),
            ("bonus_mana_per_trigger", self.bonus_mana_per_trigger),
            ("bonus_mana_per_champion", self.bonus_mana_per_champion),
            ("bonus_mana_max", self.bonus_mana_max),
        ):
            if isinstance(value, bool) or not math.isfinite(float(value)):
                raise ValueError(f"ManaflowDeclaration.{name} must be finite")
            if float(value) <= 0.0:
                raise ValueError(f"ManaflowDeclaration.{name} must be positive")
        if self.max_charges < 1:
            raise ValueError(
                f"ManaflowDeclaration.max_charges must be an int >= 1, got "
                f"{self.max_charges!r}"
            )

    @property
    def source(self) -> str:
        return f"{self.item} — Manaflow"

    def public(self) -> dict[str, Any]:
        # Every declared field, so the receipt cannot fall behind the rule.
        published = {item.name: getattr(self, item.name) for item in fields(self)}
        published["atom"] = list(self.atom)
        return published


class ManaflowLedger:
    """Manaflow charge/hit state for one holder.

    A hit is only a PROVEN ACCEPTED ELIGIBLE HIT: the driver calls ``hit``
    exclusively for casts the resource ledger already admitted (a denied
    cast cannot spend or trigger Manaflow), and a missing ``hit_identity``
    fails closed with ``missing_hit_identity`` instead of treating every
    cast as a hit.  Same-time hits are ordered by the caller's
    ``(sequence, tier)`` and are deterministic.
    """

    def __init__(
        self,
        declaration: ManaflowDeclaration,
        *,
        owner: str,
        authored_bonus_mana: float = 0.0,
    ) -> None:
        if isinstance(authored_bonus_mana, bool) or not math.isfinite(
            float(authored_bonus_mana)
        ):
            raise ValueError(
                f"authored_bonus_mana must be finite, got {authored_bonus_mana!r}"
            )
        if float(authored_bonus_mana) < 0.0:
            raise ValueError(
                f"authored_bonus_mana must be non-negative, got "
                f"{authored_bonus_mana!r}"
            )
        self._declaration = declaration
        self._owner = owner
        self._bonus_total = min(float(authored_bonus_mana), declaration.bonus_mana_max)
        self._use_count = 0
        # The last time the flow was consulted; the stored-charge pool is
        # evaluated at this time (init 0.0 = the first charge's bank time).
        self._last_time = 0.0

    @property
    def owner(self) -> str:
        return self._owner

    @property
    def declaration(self) -> ManaflowDeclaration:
        return self._declaration

    @property
    def bonus_total(self) -> float:
        return self._bonus_total

    @property
    def use_count(self) -> int:
        return self._use_count

    @property
    def cap(self) -> float:
        return self._declaration.bonus_mana_max

    @property
    def stored_charges(self) -> int:
        """Charges stored right now (pool at the last consulted time)."""
        return self.charges_available_at(self._last_time)

    def charges_available_at(self, time: float) -> int:
        """Stored charges at ``time``, at most ``max_charges``.  The first
        banks at t=0, one more every ``charge_interval`` seconds after, and
        a time before 0 floors to 0."""
        if isinstance(time, bool) or not math.isfinite(float(time)):
            raise ValueError(f"time must be finite, got {time!r}")
        banked = 1 + int(float(time) // self._declaration.charge_interval)
        return max(0, min(self._declaration.max_charges, banked - self._use_count))

    def hit(
        self,
        *,
        time: float,
        hit_identity: str | None,
        target_kind: str = "champion",
        sequence: int = 0,
        tier: float = TIER_RESTORE,
    ) -> tuple[dict[str, Any], ResourceEvent | None]:
        """Consume one stored charge for a proven eligible hit.

        Returns ``(receipt, event)``: ``event`` is the OP_MAX_INCREASE
        ResourceEvent to apply to the same owner's mana account (None when
        nothing was granted).  The receipt is JSON-safe and always records
        the accepted state and a named reason.
        """
        if isinstance(time, bool) or not math.isfinite(float(time)):
            raise ValueError(f"time must be finite, got {time!r}")
        if float(time) < 0.0:
            raise ValueError(f"time must be non-negative, got {time!r}")
        self._last_time = max(self._last_time, float(time))
        if not hit_identity or not hit_identity.strip():
            return (
                self._receipt(
                    time=time,
                    hit_identity="",
                    target_kind=target_kind,
                    accepted=False,
                    reason="missing_hit_identity",
                    charge_consumed=False,
                    bonus_delta=0.0,
                ),
                None,
            )
        if target_kind not in {"champion", "minion"}:
            raise ValueError(
                f"unknown Manaflow target_kind {target_kind!r}; supported: "
                "champion, minion"
            )
        grant = (
            self._declaration.bonus_mana_per_champion
            if target_kind == "champion"
            else self._declaration.bonus_mana_per_trigger
        )
        room = self._declaration.bonus_mana_max - self._bonus_total
        if room <= _EPS:
            return (
                self._receipt(
                    time=time,
                    hit_identity=hit_identity,
                    target_kind=target_kind,
                    accepted=False,
                    reason="cap_reached",
                    charge_consumed=False,
                    bonus_delta=0.0,
                ),
                None,
            )
        if self.charges_available_at(time) <= 0:
            return (
                self._receipt(
                    time=time,
                    hit_identity=hit_identity,
                    target_kind=target_kind,
                    accepted=False,
                    reason="no_charge_available",
                    charge_consumed=False,
                    bonus_delta=0.0,
                ),
                None,
            )
        delta = min(grant, room)
        self._use_count += 1
        self._bonus_total += delta
        event = ResourceEvent(
            owner=self._owner,
            kind=RESOURCE_KIND_MANA,
            operation=OP_MAX_INCREASE,
            amount=delta,
            time=float(time),
            source=self._declaration.source,
            sequence=int(sequence),
            tier=float(tier),
            atoms=(self._declaration.atom,),
            detail={
                "hit_identity": hit_identity,
                "target_kind": target_kind,
                "charge_consumed": True,
                "use_count": self._use_count,
                "bonus_total": round(self._bonus_total, 9),
                "cap": self._declaration.bonus_mana_max,
            },
        )
        return (
            self._receipt(
                time=time,
                hit_identity=hit_identity,
                target_kind=target_kind,
                accepted=True,
                reason="charge_consumed",
                charge_consumed=True,
                bonus_delta=delta,
            ),
            event,
        )

    def _receipt(
        self,
        *,
        time: float,
        hit_identity: str,
        target_kind: str,
        accepted: bool,
        reason: str,
        charge_consumed: bool,
        bonus_delta: float,
    ) -> dict[str, Any]:
        return {
            "time": round(float(time), 9),
            "source": self._declaration.source,
            "accepted": accepted,
            "reason": reason,
            "target_kind": target_kind,
            "hit_identity": hit_identity,
            "charge_consumed": charge_consumed,
            "use_count": self._use_count,
            "bonus_total": round(self._bonus_total, 9),
            "bonus_delta": round(float(bonus_delta), 9),
            "cap": self._declaration.bonus_mana_max,
            "atom": self._declaration.atom,
        }


# ---------------------------------------------------------------------------
# Lost Chapter — Enlighten
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EnlightenDeclaration:
    """Sourced Enlighten rule declaration (wiki branch + typed accessors).

    The 20%-over-3-seconds restore is a rule declaration: the atom catalog
    holds no atom for it (verified by the P3S1 provenance audit); the
    item's flat mana atom is carried on the declaration as the mana-family
    reference.
    """

    restore_percent: float = 20.0
    duration_seconds: float = 3.0
    ticks: int = 3
    source_url: str = "https://wiki.leagueoflegends.com/en-us/Lost_Chapter"
    source_revision_id: int = 3989340
    atom: tuple[str, str] | None = ("stat.mana", "05327ad078be2bde")

    def __post_init__(self) -> None:
        for name, value in (
            ("restore_percent", self.restore_percent),
            ("duration_seconds", self.duration_seconds),
        ):
            if isinstance(value, bool) or not math.isfinite(float(value)):
                raise ValueError(f"EnlightenDeclaration.{name} must be finite")
            if float(value) <= 0.0:
                raise ValueError(f"EnlightenDeclaration.{name} must be positive")
        if self.ticks < 1:
            raise ValueError(
                f"EnlightenDeclaration.ticks must be an int >= 1, got {self.ticks!r}"
            )

    def public(self) -> dict[str, Any]:
        row: dict[str, Any] = {
            "restore_percent": self.restore_percent,
            "duration_seconds": self.duration_seconds,
            "ticks": self.ticks,
            "source_url": self.source_url,
            "source_revision_id": self.source_revision_id,
        }
        if self.atom is not None:
            row["atom"] = list(self.atom)
        return row


def enlighten_schedule(
    *,
    level_up_time: float,
    maximum_mana: float,
    declaration: EnlightenDeclaration,
    sequence: int = 0,
    owner: str = "",
) -> tuple[ResourceEvent, ...]:
    """Build the deterministic Enlighten restore events for one level-up.

    One gain event per tick at ``level_up_time + k * duration / ticks``
    (k = 1..ticks), each restoring ``maximum_mana * restore_percent /
    100 / ticks`` — the 20% total is spread evenly over the sourced
    duration, and the base is fixed at level-up time (resource changes
    from later events never retroactively resize these amounts).
    """
    if isinstance(level_up_time, bool) or not math.isfinite(float(level_up_time)):
        raise ValueError(f"level_up_time must be finite, got {level_up_time!r}")
    if float(level_up_time) < 0.0:
        raise ValueError(f"level_up_time must be non-negative, got {level_up_time!r}")
    if isinstance(maximum_mana, bool) or not math.isfinite(float(maximum_mana)):
        raise ValueError(f"maximum_mana must be finite, got {maximum_mana!r}")
    if float(maximum_mana) < 0.0:
        raise ValueError(f"maximum_mana must be non-negative, got {maximum_mana!r}")
    per_tick = (
        float(maximum_mana) * declaration.restore_percent / 100.0 / declaration.ticks
    )
    step = declaration.duration_seconds / declaration.ticks
    return tuple(
        ResourceEvent(
            owner=owner,
            kind=RESOURCE_KIND_MANA,
            operation=OP_GAIN,
            amount=per_tick,
            time=float(level_up_time) + k * step,
            source="Lost Chapter — Enlighten",
            sequence=int(sequence) + k,
            tier=TIER_RESTORE,
            atoms=tuple((declaration.atom,) if declaration.atom is not None else ()),
            detail={
                "tick": k,
                "ticks": declaration.ticks,
                "level_up_time": float(level_up_time),
            },
        )
        for k in range(1, declaration.ticks + 1)
    )


# ---------------------------------------------------------------------------
# Catalyst of Aeons — Eternity (P3 package 3A)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CatalystHealRow:
    """One Eternity heal projected from an accepted mana spend receipt.

    ``amount`` is the heal actually applied: ``min(cap_per_cast,
    heal_ratio * spend_amount, cap_per_second - bucket_total)`` where
    ``bucket_total`` is the heal already minted in the same one-second
    floor bucket (ordered by ledger receipt order).  A denied spend never
    appears; an accepted spend landing in an exhausted bucket yields no row
    (its heal is zero and emitting a zero-amount packet would be a
    duplicate-free no-op — the pipeline contract skips zero heals).
    """

    time: float
    amount: float
    slot: str
    ordinal: int  # 1-based cast ordinal within the slot
    spend_amount: float
    bucket: int  # one-second floor bucket that owned the heal budget

    def public(self) -> dict[str, Any]:
        """JSON-safe public heal row."""
        return {
            "time": round(float(self.time), 6),
            "amount": round(float(self.amount), 6),
            "slot": self.slot,
            "ordinal": int(self.ordinal),
            "spend_amount": round(float(self.spend_amount), 6),
            "per_second_bucket": int(self.bucket),
        }


def catalyst_eternity_heal_schedule(
    receipts: Iterable[ResourceReceipt],
    *,
    heal_ratio: float,
    cap_per_cast: float,
    cap_per_second: float,
) -> tuple[CatalystHealRow, ...]:
    """Project Eternity's mana-spent heal from accepted spend receipts.

    The typed mana account is the single authoritative record of which
    casts were ACCEPTED and how much mana each spent; this projection is
    the only place the mana-to-health conversion and its per-cast and
    per-second caps are applied (a denied spend receipt can never produce
    a heal row, and no other state is consulted).  ``receipts`` must be in
    ledger order (``ResourceLedger.run``'s deterministic ``(time, tier,
    sequence)`` order): the per-second bucket budget is consumed in that
    same order, which is identical to the engine's cast ordering at one
    timestamp (restore tier 0 before cast tier 1, casts in cast-order).

    ``heal_ratio``, ``cap_per_cast`` and ``cap_per_second`` come from the
    typed ``item_effects.catalyst_eternity_declaration`` accessors; the
    kernel never invents a number (AGENTS.md rule 5).
    """
    for value, name in (
        (heal_ratio, "heal_ratio"),
        (cap_per_cast, "cap_per_cast"),
        (cap_per_second, "cap_per_second"),
    ):
        if isinstance(value, bool) or not math.isfinite(float(value)):
            raise ValueError(
                f"catalyst_eternity_heal_schedule {name} must be a finite "
                f"number, got {value!r}"
            )
        if float(value) < 0.0:
            raise ValueError(
                f"catalyst_eternity_heal_schedule {name} must be non-negative, "
                f"got {value!r}"
            )
    rows: list[CatalystHealRow] = []
    healed_by_second: dict[int, float] = {}
    for receipt in receipts:
        if receipt.operation != OP_SPEND or not receipt.accepted:
            continue
        if receipt.amount <= 0.0:
            continue
        detail = receipt.detail if isinstance(receipt.detail, Mapping) else {}
        slot = str(detail.get("slot", ""))
        if not slot:
            # Only ability-cast spends carry a slot identity; a spend
            # without one has no cast receipt to attach a heal to.
            continue
        bucket = math.floor(receipt.time + _EPS)
        remaining = max(0.0, cap_per_second - healed_by_second.get(bucket, 0.0))
        amount = min(cap_per_cast, heal_ratio * receipt.amount, remaining)
        if amount <= 0.0:
            continue
        healed_by_second[bucket] = healed_by_second.get(bucket, 0.0) + amount
        rows.append(
            CatalystHealRow(
                time=receipt.time,
                amount=amount,
                slot=slot,
                ordinal=int(detail.get("ordinal", 1)),
                spend_amount=receipt.amount,
                bucket=bucket,
            )
        )
    return tuple(rows)
