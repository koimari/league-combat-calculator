"""Manaflow: one named passive, two trigger streams, one charge pool."""

from __future__ import annotations

import math
from dataclasses import dataclass, fields
from typing import Any

from .resource_events import (
    _EPS,
    OP_MAX_INCREASE,
    RESOURCE_KIND_MANA,
    TIER_RESTORE,
    ResourceEvent,
)

#: The two streams a Manaflow clause may spend its one charge pool from.
TRIGGER_ABILITY_CAST = "ability_cast"


TRIGGER_BASIC_ATTACK = "basic_attack"


MANAFLOW_TRIGGERS = frozenset({TRIGGER_ABILITY_CAST, TRIGGER_BASIC_ATTACK})


@dataclass(frozen=True, slots=True)
class ManaflowDeclaration:
    """Sourced Manaflow rule; the holders share a shape and not a number."""

    item: str
    charge_interval: float
    max_charges: int
    bonus_mana_per_trigger: float
    bonus_mana_per_champion: float
    bonus_mana_max: float
    on_hit_charge: bool
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
        trigger: str = TRIGGER_ABILITY_CAST,
        sequence: int = 0,
        tier: float = TIER_RESTORE,
    ) -> tuple[dict[str, Any], ResourceEvent | None]:
        """Consume one stored charge for a proven eligible hit.

        Returns ``(receipt, event)``: ``event`` is the OP_MAX_INCREASE
        ResourceEvent to apply to the same owner's mana account (None when
        nothing was granted).  The receipt is JSON-safe and always records
        the accepted state and a named reason.  Both streams spend the one
        charge pool, so a basic attack at 1.0 leaves a cast at 1.2 nothing
        to spend; a basic-attack trigger on a holder whose clause names no
        on-hit trigger raises rather than inventing one.
        """
        if trigger not in MANAFLOW_TRIGGERS:
            raise ValueError(
                f"unknown Manaflow trigger {trigger!r}; supported: "
                + ", ".join(sorted(MANAFLOW_TRIGGERS))
            )
        if trigger == TRIGGER_BASIC_ATTACK and not self._declaration.on_hit_charge:
            raise ValueError(
                f"{self._declaration.item} declares no on-hit Manaflow trigger"
            )
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
                    trigger=trigger,
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
                    trigger=trigger,
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
                    trigger=trigger,
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
                "trigger": trigger,
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
                trigger=trigger,
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
        trigger: str,
        charge_consumed: bool,
        bonus_delta: float,
    ) -> dict[str, Any]:
        return {
            "time": round(float(time), 9),
            "source": self._declaration.source,
            "accepted": accepted,
            "reason": reason,
            "target_kind": target_kind,
            "trigger": trigger,
            "hit_identity": hit_identity,
            "charge_consumed": charge_consumed,
            "use_count": self._use_count,
            "bonus_total": round(self._bonus_total, 9),
            "bonus_delta": round(float(bonus_delta), 9),
            "cap": self._declaration.bonus_mana_max,
            "atom": self._declaration.atom,
        }
