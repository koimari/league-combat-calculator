"""What happened, as a closed union — never an open dictionary.

An authored packet is a ``dict`` today.  Every consumer asks it what it is by
probing for keys: a ``kind`` string here, a ``_deferred`` marker there, an
``execute_threshold_ratio`` that is ``None`` when absent and a float when
present.  Nothing names the set of shapes a packet may have, so a packet
whose shape nobody anticipated reaches the walk, matches no branch, and
contributes zero — which is the campaign's own invariant violated at the
input boundary rather than the output one.

This module names that set.  A payload is exactly one of **eleven families**,
a rider is exactly one of **five**, and a packet that determines neither
raises :class:`UnclassifiedEvent` naming the origin, the source and the keys
it actually carried.  There is no ``Any`` payload, no ``**kwargs`` and no
callable field: a family is a record of values, so "what is this event" is a
question with a type-level answer.

The two event types are the same event before and after routing.  A
:class:`PairEvent` is authored — it knows who produced it and under what
policy, but not yet who receives it.  A :class:`RoutedEvent` is what
compiles: its subject is resolved to a roster slot, and its policy is gone
because the question it answered has been answered.

**Riders travel with their host and die with it.**  That is the whole reason
they are a separate axis rather than eleven more families: an execute
threshold, a deferral, a redirect, a wound and an amp bonus all modify a
damage event without being one, and a rider on an event the walk never
applied is an effect that never happened.  A spell-shielded hit emits no
bonus because the bonus was never an event of its own.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..healing_reduction import amplifies_recovery
from ..survival.actions import TransitionRank
from .identity import EventId, PIdx
from .route import RoutePolicy

# ---------------------------------------------------------------------------
# The eleven payload families
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Damage:
    """Health taken off a subject, before any mitigation the walk applies.

    ``amount`` is the engine's pre-coupling number and ``damage_type`` is the
    class that decides which resistance mitigates it.  ``live_formula`` is
    the engine's re-pricing callable for packets whose amount depends on the
    subject's health at the moment of application; it is ``None`` for every
    packet the engine could price once, which is most of them.
    """

    amount: float
    damage_type: str
    live_formula: Any = None
    raw_amount: float = 0.0


@dataclass(frozen=True, slots=True)
class Recovery:
    """Health restored to a subject: a heal, a regeneration tick, a vamp."""

    amount: float
    healing_category: str = ""
    amount_formula: Any = None
    #: Whether the caster's heal and shield power reaches it: a
    #: regeneration tick and the vamp family are drained rather than
    #: applied, and the game amplifies neither.
    amplified: bool = True


@dataclass(frozen=True, slots=True)
class Barrier:
    """A shield pool placed on a subject, timed or permanent."""

    amount: float
    duration: float = 0.0


@dataclass(frozen=True, slots=True)
class TemporaryHealth:
    """Bonus health granted for a window — not a shield, and not a heal.

    Its own family rather than a flag on :class:`Barrier` because the walk
    stages it at a different rank and expires it by a different rule.
    """

    amount: float
    duration: float = 0.0


@dataclass(frozen=True, slots=True)
class Revive:
    """A candidate resurrection, priced only if the subject is actually dead."""

    amount: float
    delay: float = 0.0


@dataclass(frozen=True, slots=True)
class CombatState:
    """Stasis, invulnerability or untargetability for a window.

    ``state`` is the packet's own kind string because these three are one
    mechanic with three names in the live vocabulary; splitting them into
    three families would claim a distinction the walk does not make.
    """

    state: str
    duration: float = 0.0


@dataclass(frozen=True, slots=True)
class SpellShield:
    """One ability negated, consumed on use rather than expiring by amount."""

    duration: float = 0.0


@dataclass(frozen=True, slots=True)
class StatBuff:
    """Stats granted for a window — attack speed, ability power, haste."""

    bonus_attack_speed_percent: float = 0.0
    ability_power: float = 0.0
    ability_haste: float = 0.0
    duration: float = 0.0


@dataclass(frozen=True, slots=True)
class DamageModifier:
    """An amplification or reduction armed on a subject.

    The two class sets are required and empty is banned (D-04) for the same
    reason the kernel's action fields are: an untyped modifier multiplies
    every class alike, which is how a magic-only curse amplified a holder's
    true damage.  ``holder`` is the roster slot that armed it, so the owner
    skip is an integer comparison and never an id-string one.
    """

    multiplier: float
    damage_classes: frozenset
    attack_classes: frozenset
    holder: PIdx | None = None
    persistent: bool = False
    damage_reduction: bool = False
    next_event_only: bool = False


@dataclass(frozen=True, slots=True)
class OnHitMagic:
    """Magic damage added to the subject's own on-hit stream for a window."""

    amount: float
    duration: float = 0.0


@dataclass(frozen=True, slots=True)
class Utility:
    """A non-combat effect the survival model prices as utility, not health.

    ``dimension`` is the utility axis the packet declares (movement, cleanse,
    slow, economy, vision); one family with a named axis rather than five
    families, because the walk stages them identically and only the utility
    objective tells them apart.
    """

    dimension: str
    gold_amount: float = 0.0
    ward_uses: float = 0.0
    duration: float = 0.0


EventPayload = (
    Damage
    | Recovery
    | Barrier
    | TemporaryHealth
    | Revive
    | CombatState
    | SpellShield
    | StatBuff
    | DamageModifier
    | OnHitMagic
    | Utility
)

PAYLOAD_FAMILIES: tuple[type, ...] = (
    Damage,
    Recovery,
    Barrier,
    TemporaryHealth,
    Revive,
    CombatState,
    SpellShield,
    StatBuff,
    DamageModifier,
    OnHitMagic,
    Utility,
)


# ---------------------------------------------------------------------------
# The five riders
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Execute:
    """This damage kills outright below a health ratio, named by its source."""

    threshold_ratio: float
    source: str


@dataclass(frozen=True, slots=True)
class Defer:
    """This damage lands in a later batch rather than at its own timestamp."""

    batch: EventId


@dataclass(frozen=True, slots=True)
class Redirect:
    """A share of this damage is taken by another participant instead.

    ``holder_health_ratio`` is the gate the sharing holder must clear; the
    walk cancels the child when the holder cannot pay, which is why the
    original amount rides here rather than being recomputed.
    """

    holder: PIdx
    holder_health_ratio: float = 0.0
    original_amount: float = 0.0


@dataclass(frozen=True, slots=True)
class Wound:
    """Grievous Wounds applied by this hit, for a duration, from a source."""

    duration: float
    source: str


@dataclass(frozen=True, slots=True)
class AmpBonus:
    """Extra damage a live predicate adds to *this* hit, read before absorption.

    A rider rather than an event because it must die with its host: a
    spell-shielded, state-blocked or post-death trigger emits no bonus, and
    an independent event would have to be cancelled by hand to achieve that.
    """

    multiplier: float
    mechanic: str


Rider = Execute | Defer | Redirect | Wound | AmpBonus

RIDER_KINDS: tuple[type, ...] = (Execute, Defer, Redirect, Wound, AmpBonus)


# ---------------------------------------------------------------------------
# The two event shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PairEvent:
    """One authored event, before its subjects are resolved.

    ``sequence`` is **required**: the walk's sort key breaks ties on it, and
    every pair-local event id is numbered by position, so an event without
    one would make identity order-dependent.  The engine already refuses to
    author one; declaring the field required is that refusal, typed.
    """

    id: EventId
    time: float
    sequence: int
    rank: TransitionRank
    payload: EventPayload
    route: RoutePolicy
    riders: tuple[Rider, ...] = ()


@dataclass(frozen=True, slots=True)
class RoutedEvent:  # pylint: disable=too-many-instance-attributes
    """One event with its subject resolved — what the compiler consumes.

    No ``route`` field: the policy answered its question and keeping it would
    invite a second, later answer that disagrees with the first.
    """

    id: EventId
    subject: PIdx
    source: PIdx
    time: float
    sequence: int
    rank: TransitionRank
    payload: EventPayload
    riders: tuple[Rider, ...] = ()


class UnclassifiedEvent(ValueError):
    """A packet whose family the closed union cannot determine.

    Carries what a reader needs to fix it and nothing they would have to go
    looking for: where it came from, who authored it, and which keys it
    actually had.  The alternative — falling through to a neutral family — is
    the uncomputed number this campaign exists to make impossible.
    """

    def __init__(self, origin: Any, source: str, fields_present: tuple[str, ...]):
        super().__init__(
            f"{source or '<unnamed>'} authored a packet from {origin!r} whose "
            f"family the closed payload union cannot determine; it carries "
            f"{list(fields_present)}"
        )
        self.origin = origin
        self.source = source
        self.fields_present = fields_present


# The live packet vocabulary, family by family.  It is a table rather than a
# ladder of ``if``s because the mapping is data: a kind the engine starts
# authoring is one row here, and a kind nobody mapped raises instead of
# reaching a default.
_COMBAT_STATE_KINDS = frozenset({"stasis", "invulnerability", "untargetable"})
_RECOVERY_KINDS = frozenset({"heal", "regen"})
_UTILITY_PACKET_KINDS = frozenset({"movement", "cleanse", "slow", "economy", "vision"})


def _float(packet: Mapping[str, Any], key: str, default: float = 0.0) -> float:
    """One packet field as a float: absent means *default*, unparseable raises."""
    value = packet.get(key)
    return default if value is None else float(value)


def payload_from_packet(  # pylint: disable=too-many-return-statements
    packet: Mapping[str, Any], *, origin: Any
) -> EventPayload:
    """Classify one authored packet into the closed union, or raise.

    The precedence mirrors the walk's own dispatch: named kinds first, then
    the damage path, which is the only family a packet reaches by carrying a
    ``damage_type`` rather than by naming itself.  Anything else raises
    :class:`UnclassifiedEvent` — there is no residual family and no default.
    """
    kind = str(packet.get("kind", ""))
    if kind == "revive":
        return Revive(
            amount=_float(packet, "amount"), delay=_float(packet, "revive_delay")
        )
    if kind in _COMBAT_STATE_KINDS:
        return CombatState(state=kind, duration=_float(packet, "duration"))
    if kind == "spell_shield":
        return SpellShield(duration=_float(packet, "duration"))
    if kind == "shield":
        return Barrier(
            amount=_float(packet, "amount"), duration=_float(packet, "duration")
        )
    if kind == "temporary_health":
        return TemporaryHealth(
            amount=_float(packet, "amount"), duration=_float(packet, "duration")
        )
    if kind == "stat_buff":
        return StatBuff(
            bonus_attack_speed_percent=_float(packet, "bonus_attack_speed_percent"),
            ability_power=_float(packet, "ability_power"),
            ability_haste=_float(packet, "ability_haste"),
            duration=_float(packet, "duration"),
        )
    if kind == "damage_modifier":
        return DamageModifier(
            multiplier=_float(packet, "multiplier", 1.0),
            damage_classes=frozenset(packet.get("damage_classes") or ()),
            attack_classes=frozenset(packet.get("attack_classes") or ()),
            persistent=bool(packet.get("persistent")),
            damage_reduction=bool(packet.get("damage_reduction")),
            next_event_only=bool(packet.get("next_event_only")),
        )
    if kind == "on_hit_magic":
        return OnHitMagic(
            amount=_float(packet, "on_hit_magic_damage"),
            duration=_float(packet, "duration"),
        )
    if kind in _UTILITY_PACKET_KINDS:
        return Utility(
            dimension=kind,
            gold_amount=_float(packet, "gold_amount"),
            ward_uses=_float(packet, "ward_uses"),
            duration=_float(packet, "duration"),
        )
    if kind in _RECOVERY_KINDS or "amount_formula" in packet:
        healing_category = str(packet.get("healing_category", ""))
        return Recovery(
            amount=_float(packet, "amount"),
            healing_category=healing_category,
            amount_formula=packet.get("amount_formula"),
            amplified=amplifies_recovery(kind, healing_category),
        )
    if packet.get("damage_type"):
        return Damage(
            amount=_float(packet, "damage", _float(packet, "amount")),
            damage_type=str(packet["damage_type"]),
            live_formula=packet.get("raw_formula"),
            raw_amount=_float(packet, "raw_damage"),
        )
    raise UnclassifiedEvent(
        origin,
        str(packet.get("source", packet.get("source_key", ""))),
        tuple(sorted(str(key) for key in packet)),
    )


def riders_from_packet(packet: Mapping[str, Any]) -> tuple[Rider, ...]:
    """Every rider one authored packet carries, in a stable declared order.

    Order is the declaration order of :data:`RIDER_KINDS` and not the
    packet's key order, because a rider tuple is compared for equality by
    the program cache key and a dict's iteration order is an authoring
    accident.
    """
    riders: list[Rider] = []
    threshold = packet.get("execute_threshold_ratio")
    if threshold is not None:
        riders.append(
            Execute(
                threshold_ratio=float(threshold),
                source=str(packet.get("execute_source", "")),
            )
        )
    wound_duration = _float(packet, "grievous_duration")
    if wound_duration > 0.0:
        riders.append(
            Wound(
                duration=wound_duration,
                source=str(packet.get("_wound_source", "Grievous Wounds")),
            )
        )
    return tuple(riders)


__all__ = [
    "PAYLOAD_FAMILIES",
    "RIDER_KINDS",
    "AmpBonus",
    "Barrier",
    "CombatState",
    "Damage",
    "DamageModifier",
    "Defer",
    "EventPayload",
    "Execute",
    "OnHitMagic",
    "PairEvent",
    "Recovery",
    "Redirect",
    "Revive",
    "Rider",
    "RoutedEvent",
    "SpellShield",
    "StatBuff",
    "TemporaryHealth",
    "UnclassifiedEvent",
    "Utility",
    "Wound",
    "payload_from_packet",
    "riders_from_packet",
]
