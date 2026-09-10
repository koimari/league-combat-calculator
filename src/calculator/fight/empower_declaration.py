"""What an `empowers_next_auto` payload declares, and where its swings landed."""

from dataclasses import dataclass
from typing import Any

from ..ability_atoms import ability_field


def _empower_hits(empower: Any) -> int:
    """Basic attacks one empowered-auto cast rides or forces.
    ``empowers_next_auto`` is ``True`` (one attack — Vayne Q) or a dict
    that may carry ``hits`` (Cho'Gath E empowers the next 3). Absent
    ``hits`` defaults to 1."""
    return (
        int(ability_field(empower, "hits", form="empower"))
        if isinstance(empower, dict)
        else 1
    )


def _empower_cooldown_delay(empower: Any) -> float:
    """Seconds an empowered burst runs BEFORE its cooldown starts.
    An ability whose ``empowers_next_auto`` declares
    ``cooldown_starts_after_hits`` begins its timer when the last empowered
    attack is consumed (Jayce's Hyper Charge), so the burst's duration is dead
    time on the cycle: it delays the recast, and those attacks cannot refund
    this ability's cooldown (Navori).  Zero for every other empowered auto."""
    if not isinstance(empower, dict):
        return 0.0
    if not empower.get("cooldown_starts_after_hits"):
        return 0.0
    rate = _empower_burst_attack_speed(empower)
    return _empower_hits(empower) / rate if rate > 0 else 0.0


def _empower_burst_attack_speed(empower: Any) -> float:
    """Rate the empowered swings fire at, or 0 when they ride the fight's.  An
    ``empowers_next_auto`` dict may declare ``attack_speed``, firing its hits at
    that rate (Jayce's Hyper Charge) and costing the fight only their span."""
    if not isinstance(empower, dict):
        return 0.0
    return float(ability_field(empower, "attack_speed", form="empower"))


def _empower_rides_scheduled_auto(empower: Any) -> bool:
    """Whether this empower waits for the stream's next swing to deliver it."""
    return (
        bool(empower.get("rides_scheduled_auto"))
        if isinstance(empower, dict)
        else False
    )


def _empower_authored_timing(empower: Any) -> tuple[float, float] | None:
    """Return module-authored first-hit delay and interval for a burst.

    The timing is used only when the ability must force its own attacks
    because no ambient auto stream exists. Timed fights with an auto stream
    keep those attacks on that stream; a champion module can mark that case
    as requiring explicit coupling before its timeline is certified.
    """
    if not isinstance(empower, dict):
        return None
    timing = empower.get("authored_timing")
    if not isinstance(timing, dict):
        return None
    first = float(ability_field(timing, "first_attack_delay", form="empower_timing"))
    interval = float(ability_field(timing, "attack_interval", form="empower_timing"))
    if first < 0 or interval < 0:
        raise ValueError("Empowered attack timing cannot be negative")
    return first, interval


@dataclass(frozen=True)
class BurstSwingSchedule:
    """Where a self-rated empowered burst lands its swings, and for how long.

    ``by_ability`` holds each empowering entry's own impacts — the swings
    it actually landed, which is not ``casts x hits`` once a cast starts
    too late for all of them. ``blocks`` are the merged ``[start, end)``
    spans those impacts occupy: the seconds the ordinary auto stream is
    not running, which is exactly what the auto count was charged for.
    """

    by_ability: dict[str, tuple[float, ...]]
    blocks: tuple[tuple[float, float], ...]

    @property
    def times(self) -> tuple[float, ...]:
        """Every burst impact in the fight, in clock order."""
        return tuple(sorted(t for hits in self.by_ability.values() for t in hits))

    @property
    def seconds(self) -> float:
        """Fight time the bursts occupy, overlaps counted once."""
        return sum(end - start for start, end in self.blocks)

    def landed(self, ability_key: str) -> int:
        """Swings this entry put on the stream (0 when it declares no burst)."""
        return len(self.by_ability.get(ability_key, ()))
