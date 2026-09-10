"""One packet, its combatants, a defense's armed window, and the key an event is booked under."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

# Floating-point tolerance shared with the damage/survival walks.  All
# kernel comparisons use the same 1e-9 convention as the engine receipts.
_EPS = 1e-9


class PacketIdentity(Protocol):  # pylint: disable=too-few-public-methods
    """The three fields :func:`stable_event_key` identifies a packet by."""

    time: float
    source_key: str
    sequence: int | None


class PacketFacts(PacketIdentity, Protocol):  # pylint: disable=too-few-public-methods
    """One survival action as the eligibility kernels read it.

    ``survival.actions.SurvivalAction`` is the one production packet; the
    survival package imports this module, so the kernels name its delivery
    markers and identity fields structurally.
    """

    source: str
    event_id: str
    ability_instance: str | None
    is_ability: bool
    basic_attack: bool
    skillshot: bool
    area_damage: bool
    damage_over_time: bool
    cc_kind: str


class RequestFacts(Protocol):  # pylint: disable=too-few-public-methods
    """The request fields the kernels read off a combatant."""

    current_health: float | None
    champion_options: Mapping[str, Any] | None
    ability_ranks: Mapping[str, int] | None


class ChampionFacts(Protocol):  # pylint: disable=too-few-public-methods
    """A champion record with its request and stats.

    What a roster ``Combatant`` and a pre-combat ``ResolvedLoadout`` share,
    so a target resolver can serve both.
    """

    champion_data: Mapping[str, Any]
    request: RequestFacts
    stats: Mapping[str, float]


class CombatantFacts(ChampionFacts, Protocol):  # pylint: disable=too-few-public-methods
    """A roster combatant as the kernels and the program layer read it.

    The structural face of ``roster_composition.Combatant`` for the modules
    the roster imports and which cannot import it back.  ``defenses`` is the
    holder's ``defensive_effects.StartingDefenses`` record, unnamed here
    because the declaration layer imports the survival package too.
    """

    defenses: Any
    participant_id: str
    team: str
    level: int
    items: Sequence[Mapping[str, Any]]


@dataclass(frozen=True, slots=True)
class DefenseWindow:
    """One sourced active window (start inclusive, end exclusive).

    The boundary convention mirrors the survival walk: an event at
    ``start`` is inside, an event at ``until`` is outside.
    """

    start: float
    until: float
    source_atoms: tuple[dict[str, Any], ...] = ()

    def active_at(self, event_time: float) -> bool:
        """Whether an event time falls inside the window."""
        return self.start <= event_time < self.until

    def public_receipt(self) -> dict[str, Any]:
        """JSON-safe window receipt."""
        return {
            "start": round(self.start, 3),
            "until": round(self.until, 3),
            "source_atoms": [dict(atom) for atom in self.source_atoms],
        }


def _attacker_name(attacker: CombatantFacts | None) -> str:
    """Read the attacker display name from a combatant."""
    if attacker is None:
        return ""
    champion_data = getattr(attacker, "champion_data", {})
    if isinstance(champion_data, Mapping):
        return str(champion_data.get("name", "") or "")
    return str(getattr(attacker, "name", "") or "")


def stable_event_key(action: PacketIdentity) -> str:
    """One stable identity for an interaction packet.

    ``source_key:time:sequence`` — the exact key the survival walk uses
    for full-block bookkeeping, so kernel decisions and walk bookkeeping
    share one identity.
    """
    source_key = str(getattr(action, "source_key", "") or "")
    event_time = float(getattr(action, "time", 0.0) or 0.0)
    sequence = getattr(action, "sequence", 0)
    try:
        sequence = int(sequence or 0)
    except (TypeError, ValueError):
        sequence = 0
    return f"{source_key}:{round(event_time, 9)}:{sequence}"
