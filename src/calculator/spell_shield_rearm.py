"""The spell shield's re-arm clock, and the sourced rule it runs on.

A consumed shield comes back inside one fight when its sourced cooldown
elapses, anchored by the cached "timer restarts upon taking damage from
champions" clause to the later of the consumption instant and the last
champion damage the holder took.  A shield with no sourced cooldown keeps the
strict one-use-per-fight rule.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .delivery_facts import _EPS

SPELL_SHIELD_REARM_RULE = (
    "A consumed shield rearms inside one modeled fight only once its "
    "sourced cooldown has fully elapsed ('40 second cooldown, timer "
    "restarts upon taking damage from champions' — Banshee's Veil / Edge "
    "of Night; 60 seconds — Verdant Barrier), and that restart clause "
    "anchors the clock to the later of the consumption instant and the "
    "last champion damage the holder took.  A shield whose cooldown is "
    "not sourced never rearms."
)


@dataclass(frozen=True, slots=True)
class SpellShieldRearmClock:
    """One consumed shield's fight-window-relative rearm clock.

    ``cooldown`` is the holder item's SOURCED cooldown in seconds and
    ``source_atom`` is the catalog atom that evidences it: a positive
    cooldown declared without its atom is refused, so the kernel can never
    rearm on a number no source backs.  ``0.0`` is the declared "no sourced
    cooldown" value and never rearms — that shield keeps the strict
    one-use-per-fight rule (Sivir's timed shield is the live case).

    ``restarts_on_champion_damage`` carries the cached clause every Annul
    branch spells out, so the timer is anchored to the LATER of the
    consumption instant and the last champion damage the holder took — not
    to the consumption instant alone, which would rearm the shield sooner
    than the source allows.
    """

    cooldown: float = 0.0
    restarts_on_champion_damage: bool = True
    source_atom: Mapping[str, Any] | None = None
    rule: str = SPELL_SHIELD_REARM_RULE

    def __post_init__(self) -> None:
        """Fail closed on an impossible or unsourced clock declaration."""
        if not self.cooldown >= 0.0:
            raise ValueError(
                "SpellShieldRearmClock: cooldown must be a number >= 0.0 "
                f"(0.0 = not sourced, never rearms), got {self.cooldown!r}"
            )
        if self.cooldown > 0.0 and self.source_atom is None:
            raise ValueError(
                "SpellShieldRearmClock: a positive cooldown needs the "
                f"catalog atom that sources it; {self.cooldown!r} arrived "
                "with none"
            )

    def sourced(self) -> bool:
        """Whether a sourced cooldown backs this clock."""
        return self.cooldown > 0.0

    def anchor(
        self, consumed_at: float, last_champion_damage_at: float | None = None
    ) -> float:
        """The instant this shield's cooldown timer last (re)started."""
        started = float(consumed_at)
        if self.restarts_on_champion_damage and last_champion_damage_at is not None:
            damaged_at = float(last_champion_damage_at)
            started = max(started, damaged_at)
        return started

    def ready_at(
        self, consumed_at: float, last_champion_damage_at: float | None = None
    ) -> float:
        """The fight-relative instant the shield rearms; ``inf`` never."""
        if not self.sourced():
            return float("inf")
        return self.anchor(consumed_at, last_champion_damage_at) + self.cooldown

    def rearmed_at(
        self,
        event_time: float,
        consumed_at: float,
        last_champion_damage_at: float | None = None,
    ) -> bool:
        """Whether the shield is back by ``event_time`` (start inclusive)."""
        ready = self.ready_at(consumed_at, last_champion_damage_at)
        if not math.isfinite(ready):
            return False
        return float(event_time) >= ready - _EPS

    def rearms_within(
        self,
        fight_until: float,
        consumed_at: float,
        last_champion_damage_at: float | None = None,
    ) -> bool:
        """Whether the rearm lands inside the fight window.

        End-exclusive, the walk's convention (:meth:`DefenseWindow.active_at`).
        """
        ready = self.ready_at(consumed_at, last_champion_damage_at)
        if not math.isfinite(ready):
            return False
        return ready < float(fight_until) - _EPS

    def public_receipt(self) -> dict[str, Any]:
        """JSON-safe rearm-clock receipt."""
        return {
            "cooldown": round(self.cooldown, 3),
            "sourced": self.sourced(),
            "restarts_on_champion_damage": self.restarts_on_champion_damage,
            "rule": self.rule,
            "source_atom": (
                dict(self.source_atom) if self.source_atom is not None else None
            ),
        }
