"""Item schedules on the account's receipts: Lost Chapter's Enlighten, Catalyst's Eternity."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .resource_events import (
    _EPS,
    OP_GAIN,
    OP_SPEND,
    RESOURCE_KIND_MANA,
    TIER_RESTORE,
    ResourceEvent,
    ResourceReceipt,
)


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
