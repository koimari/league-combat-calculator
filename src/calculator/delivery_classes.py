"""The six classes a delivery is declared as, and how one action is classified into them.

:data:`DELIVERY_DECLARATIONS` carries one source receipt per class (projectile,
hitscan, area, targeted, basic attack, damage over time), and
:func:`classify_delivery` maps one survival action to a :class:`DeliveryProfile`
from its typed markers.  An action whose markers match no declared class is
``unknown`` and fails closed wherever a defense needs a delivery decision
(``unknown_delivery`` receipt; :class:`UnknownDeliveryError` for the strict API).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .delivery_facts import PacketFacts
from .state_timeline import SourceReceipt

DELIVERY_PROJECTILE = "projectile"


DELIVERY_HITSCAN = "hitscan"


DELIVERY_AREA = "area"


DELIVERY_TARGETED = "targeted"


DELIVERY_BASIC_ATTACK = "basic_attack"


DELIVERY_DAMAGE_OVER_TIME = "damage_over_time"


DeliveryClass = Literal[
    "projectile", "hitscan", "area", "targeted", "basic_attack", "damage_over_time"
]


DELIVERY_CLASSES: tuple[str, ...] = (
    DELIVERY_PROJECTILE,
    DELIVERY_HITSCAN,
    DELIVERY_AREA,
    DELIVERY_TARGETED,
    DELIVERY_BASIC_ATTACK,
    DELIVERY_DAMAGE_OVER_TIME,
)


@dataclass(frozen=True, slots=True)
class DeliveryDeclaration:
    """One typed delivery class with its source receipt.

    ``marker`` names the typed event/action field that evidences the
    class at runtime ("" when the class has no runtime marker yet —
    hitscan and targeted are declared conventions; targeted is evidenced
    by the ABSENCE of every other marker on an ability packet).
    """

    delivery: DeliveryClass
    description: str
    marker: str = ""
    source: SourceReceipt | None = None

    def public_receipt(self) -> dict[str, Any]:
        """JSON-safe declaration receipt."""
        return {
            "delivery": self.delivery,
            "description": self.description,
            "marker": self.marker,
            "source": self.source.public() if self.source is not None else None,
        }


# The runtime markers are the engine's typed stamps: ``skillshot`` from
# the cached ability ``projectile`` field, ``area_damage`` from
# ``spellEffects`` aoe values, ``basic_attack`` from the damage ledger's
# attack rows, ``damage_over_time`` from the ledger's DoT rows (declared
# but not yet stamped by any authored packet — see module notes).
DELIVERY_DECLARATIONS: tuple[DeliveryDeclaration, ...] = (
    DeliveryDeclaration(
        DELIVERY_PROJECTILE,
        "Blockable projectile / skillshot: the cached ability row carries a projectile.",
        marker="skillshot",
        source=SourceReceipt(
            label="Local League Wiki cache — ability projectile field",
            url="https://wiki.leagueoflegends.com",
        ),
    ),
    DeliveryDeclaration(
        DELIVERY_HITSCAN,
        "Instant line delivery with no travel time (declared; no runtime marker yet).",
        marker="",
        source=SourceReceipt(
            label="LoL wiki terminology — hitscan ability delivery",
            url="https://wiki.leagueoflegends.com",
        ),
    ),
    DeliveryDeclaration(
        DELIVERY_AREA,
        "Area-of-effect delivery: the cached ability row's spellEffects mark aoe.",
        marker="area_damage",
        source=SourceReceipt(
            label="Local League Wiki cache — spellEffects aoe marker",
            url="https://wiki.leagueoflegends.com",
        ),
    ),
    DeliveryDeclaration(
        DELIVERY_TARGETED,
        "Direct champion-targeted ability: an ability packet with no projectile, "
        "area, dot, or basic-attack marker.",
        marker="",
        source=SourceReceipt(
            label="Local League Wiki cache — absence of delivery markers",
            url="https://wiki.leagueoflegends.com",
        ),
    ),
    DeliveryDeclaration(
        DELIVERY_BASIC_ATTACK,
        "Basic attack packet from the damage ledger's attack rows.",
        marker="basic_attack",
        source=SourceReceipt(
            label="Damage ledger basic-attack marker",
            url="https://wiki.leagueoflegends.com",
        ),
    ),
    DeliveryDeclaration(
        DELIVERY_DAMAGE_OVER_TIME,
        "Damage-over-time tick packet from the damage ledger's DoT rows.",
        marker="damage_over_time",
        source=SourceReceipt(
            label="Damage ledger damage_over_time marker (declared; unstamped today)",
            url="https://wiki.leagueoflegends.com",
        ),
    ),
)


def delivery_declarations_receipt() -> list[dict[str, Any]]:
    """JSON-safe receipt for every declared delivery class."""
    return [declaration.public_receipt() for declaration in DELIVERY_DECLARATIONS]


@dataclass(frozen=True, slots=True)
class DeliveryProfile:
    """One event's delivery classes plus its classification completeness.

    ``classes`` is the set of declared delivery classes evidenced by the
    event's typed markers.  ``unknown`` is True when the event carries no
    declared class and is not a declared targeted ability packet (an
    item proc, an on-hit packet, or a packet with undeclared markers).
    """

    classes: frozenset[DeliveryClass] = frozenset()
    unknown: bool = False
    unknown_markers: tuple[str, ...] = ()

    def has(self, delivery: str) -> bool:
        """Whether the profile includes one delivery class."""
        return delivery in self.classes

    def public_receipt(self) -> dict[str, Any]:
        """JSON-safe classification receipt."""
        return {
            "classes": sorted(self.classes),
            "unknown": self.unknown,
            "unknown_markers": list(self.unknown_markers),
        }


class UnknownDeliveryError(ValueError):
    """Raised when a strict delivery decision needs a class the model
    cannot classify.  Naming the event keeps the failure actionable."""


def action_flag(action: PacketFacts, name: str) -> bool:
    """Read one typed marker, defaulting to False for absent fields."""
    return bool(getattr(action, name, False))


def classify_delivery(action: PacketFacts) -> DeliveryProfile:
    """Classify one survival action's delivery from its typed markers.

    Deterministic by construction: the classes are a pure function of the
    action's ``skillshot`` / ``area_damage`` / ``basic_attack`` /
    ``damage_over_time`` / ``is_ability`` fields.  An ability packet
    with no delivery marker is the declared ``targeted`` class; a
    non-ability packet with no marker is ``unknown`` (fail-closed).
    """
    classes: set[str] = set()
    if action_flag(action, "basic_attack"):
        classes.add(DELIVERY_BASIC_ATTACK)
    if action_flag(action, "damage_over_time"):
        classes.add(DELIVERY_DAMAGE_OVER_TIME)
    if action_flag(action, "skillshot"):
        classes.add(DELIVERY_PROJECTILE)
    if action_flag(action, "area_damage"):
        classes.add(DELIVERY_AREA)
    unknown_markers: tuple[str, ...] = ()
    if not classes:
        if action_flag(action, "is_ability"):
            classes.add(DELIVERY_TARGETED)
        else:
            unknown_markers = ("no_declared_marker",)
    return DeliveryProfile(
        classes=frozenset(classes),
        unknown=bool(unknown_markers),
        unknown_markers=unknown_markers,
    )


def required_delivery_class(action: PacketFacts, accepted: frozenset[str]) -> str:
    """Return one accepted delivery class or fail closed.

    Raises :class:`UnknownDeliveryError` when the event's delivery cannot
    be classified into any accepted class.  This is the strict API for a
    decision that MUST resolve; the eligibility decision path uses the
    receipt form instead.
    """
    profile = classify_delivery(action)
    if profile.unknown:
        raise UnknownDeliveryError(
            f"unknown delivery for {getattr(action, 'source_key', '?')!r} "
            f"at t={getattr(action, 'time', 0.0)} (markers: "
            f"{sorted(profile.unknown_markers)})"
        )
    for delivery in sorted(profile.classes):
        if delivery in accepted:
            return delivery
    raise UnknownDeliveryError(
        f"delivery {sorted(profile.classes)} for "
        f"{getattr(action, 'source_key', '?')!r} is not accepted by "
        f"{sorted(accepted)}"
    )
