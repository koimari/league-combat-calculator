"""Who priced an amplification, what it reaches, and whether it arms twice.

Imperial Mandate's Command priced **zero** for a stunning champion while six
layers each reported success.  Two of those six live here as types rather
than as review rules.

:class:`Provenance` is the first.  It is an *authoring* invariant, not a
runtime record: its construction rules make two of the incident's defects
unconstructible.  A modifier the pair engine priced must exclude its own
holder — the pair engine already charged the holder's own damage, so applying
it again is a double count — and a modifier with no declared class
restriction cannot be built at all, which is D-04's empty-means-all ban
enforced at the moment of authoring instead of at the moment of application.
The record compiles to flat kernel fields (``SurvivalAction.holder`` and the
two class sets); it never travels into the hot tuple, because an invariant
belongs where it can be violated and the hot loop cannot violate it.

:func:`arm_key` is the second.  Two holders of one mechanic either arm one
modifier on a subject or two, and *which* is a per-mechanic fact the
:class:`~..trigger_stream.HolderStacking` declaration answers.  Both branches
are written because both are live: Abyssal Mask is an aura and Imperial
Mandate is per-holder, and a signature that could only express the aura key
would silently drop a second Mandate holder's contribution — the incident's
own shape, mandated by a rule.

:func:`live_amp_riders` is the third, and the one this package's docstring
calls the coupled-lane interpreter of Phase 3's ``delta_amp`` declarations.
It answers one question — which of a holder's declared amplifiers cannot be
resolved to a number before the walk runs — and hands each of them to the
kernel as a :class:`~..survival.actions.LiveAmp` value the walk evaluates by
tag.  It is derived from the declarations rather than keyed on a slot name,
so a second live-predicate amp joins the walk on the commit that declares
one.

**What is not here.**  ``modifier_events`` — the compiler from Phase 3's
declared ``DeltaAmpRule`` to armed :class:`~.events.DamageModifier` events —
is a separate compiler for the amps that *do* resolve to a number up front,
and no authority move has needed it yet: Bloodsong's arrives through
``item_support_effects``' own packets and Shadowflame's is a rider, not a
packet.  Naming it here with an empty body would be a declaration that
outruns its implementation, which is the failure this campaign exists to
remove; the sentence is the marker instead.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum

from ..ability_spec import AttackClass, DamageClass
from ..interpreters import delta_amp
from ..item_behavior import (
    AMP_CHAIN_ORDER,
    Comparison,
    EngineLane,
    LivePredicate,
    Probe,
    Subject,
)
from ..survival.actions import LiveAmp, LiveProbe
from ..trigger_stream import HolderStacking
from .identity import MechanicId, PIdx


class AppliesTo(Enum):
    """Which participants a priced modifier's number is allowed to reach.

    ``ALL_EXCEPT_HOLDER`` is not a routing decision — routing is
    :mod:`program.route`'s — it is a statement about *what the number
    already contains*.  A pair-engine figure has the holder's own damage
    baked in, so a coupled pass that applied it to the holder as well would
    count it twice with no symptom.
    """

    ALL = "all"
    ALL_EXCEPT_HOLDER = "all_except_holder"


@dataclass(frozen=True, slots=True)
class Provenance:
    """Who priced one modifier, what it reaches, and what it may amplify.

    Frozen and validated at construction: the two defects below are not
    "checked" anywhere, they are unconstructible.

    * A ``PAIR_ENGINE`` price that claims ``ALL`` — the double count.
    * An empty ``damage_classes`` or ``attack_classes`` — the untyped amp
      that multiplied a holder's true damage with a magic-only curse (D-04).

    ``holder`` is a :class:`~.identity.PIdx` here and a plain ``int`` in the
    kernel field it compiles into.  That asymmetry is the phase's one-way
    dependency: ``survival/`` may not name a ``program/`` type, so the
    narrowing lives on this side of the boundary and the slot crosses it.
    """

    holder: PIdx
    priced_by: EngineLane
    applies_to: AppliesTo
    damage_classes: frozenset[DamageClass]
    attack_classes: frozenset[AttackClass]

    def __post_init__(self) -> None:
        """Reject the two authoring shapes the incident was made of."""
        if not self.damage_classes or not self.attack_classes:
            raise ValueError(
                "a damage modifier must declare both damage_classes and "
                "attack_classes; empty-means-all is banned (D-04), and an "
                "untyped amplifier is what multiplied true damage with a "
                "magic-only curse "
                f"(damage_classes={sorted(c.name for c in self.damage_classes)}, "
                f"attack_classes={sorted(c.name for c in self.attack_classes)})"
            )
        if (
            self.priced_by is EngineLane.PAIR_ENGINE
            and self.applies_to is not AppliesTo.ALL_EXCEPT_HOLDER
        ):
            raise ValueError(
                "a pair-engine-priced modifier already contains the holder's "
                "own contribution, so it applies to ALL_EXCEPT_HOLDER; "
                f"{self.applies_to.name} would count the holder twice"
            )

    def skips(self, subject: PIdx) -> bool:
        """Whether this modifier declines to reach *subject*.

        The owner skip, as one question with one answer.  It reads the
        roster slot rather than a participant id string, which is what makes
        it an integer comparison in the walk and what made the string
        version silently false whenever an id was spelled two ways.
        """
        return self.applies_to is AppliesTo.ALL_EXCEPT_HOLDER and int(subject) == int(
            self.holder
        )


ArmKey = tuple


def arm_key(
    subject: PIdx,
    mechanic: MechanicId,
    holder: PIdx,
    stacking: HolderStacking,
) -> ArmKey:
    """The exactly-once dedupe key for arming one mechanic on one subject.

    ``IDEMPOTENT_AURA`` drops the holder from the key, so a second holder's
    arming collides with the first and is dropped — with a ``dedupe`` receipt
    row, never in silence.  ``PER_HOLDER`` keeps it, so two holders arm two
    modifiers, which is the live path: Command's stacking is human-blocked
    and fails closed to ``PER_HOLDER``.

    This is the only arming dedupe in ``src/``.  A second one would be a
    second answer to "did this already arm?", and the two would disagree on
    exactly the roster that has two holders.
    """
    if stacking is HolderStacking.IDEMPOTENT_AURA:
        return (int(subject), str(mechanic))
    if stacking is HolderStacking.PER_HOLDER:
        return (int(subject), str(mechanic), int(holder))
    raise TypeError(
        f"{stacking!r} is not a HolderStacking; the enum is closed "
        "(IDEMPOTENT_AURA | PER_HOLDER) and a mechanic without a declaration "
        "must fail to construct rather than inherit a guess (D-66)"
    )


@dataclass(frozen=True, slots=True)
class ArmingDrop:
    """One arming that collided with an earlier one, and why it was dropped.

    A receipt, not a log line.  The campaign's invariant is that a number the
    model did not compute must never be indistinguishable from one it
    computed as zero, and an arming silently discarded on a collision is that
    failure at the point where the number is *born*.  So the drop is a value
    the composition publishes, carrying the holder that got there first.
    """

    mechanic: MechanicId
    stacking: HolderStacking
    first_holder: int

    def receipt(self) -> dict[str, object]:
        """The published row — one dropped arming, in its own words."""
        return {
            "reason": "dedupe",
            "mechanic": str(self.mechanic),
            "holder_stacking": self.stacking.value,
            "first_holder": self.first_holder,
        }


class ArmingLedger:
    """The one arming dedupe in ``src/``.

    One instance per composed fight, holding every key that has already
    armed.  A second one would be a second answer to "did this already arm?",
    and the two would disagree on exactly the roster that has two holders —
    which is the only roster where the question is asked at all.

    The ledger decides nothing on its own: :func:`arm_key` decides, from the
    mechanic's own :class:`~..trigger_stream.HolderStacking` declaration, and
    a packet whose source names no dual-sided mechanic is admitted without a
    key ever being built.  That asymmetry is deliberate — a mechanic with no
    declared stacking has no arming-dedupe question, and inventing one for it
    would be a policy where a declaration belongs.
    """

    def __init__(
        self, stacking_of: Mapping[str, tuple[MechanicId, HolderStacking]]
    ) -> None:
        self._stacking_of = stacking_of
        self._armed: dict[ArmKey, int] = {}

    def admit(
        self, packet_source: str, subject: PIdx, holder: PIdx
    ) -> ArmingDrop | None:
        """Whether this arming stands, or the receipt saying it did not.

        ``None`` means it armed.  Returning the drop rather than raising is
        the point: two Abyssal Mask holders cursing one enemy is a legal
        roster and the second curse is genuinely redundant, so the answer is
        a receipt, never an error and never a silence.

        **A collision is only ever between two *holders*.**  A key already
        held by the same holder is a *re-arm*, not a duplicate: Carve arms
        one modifier per damage event and Expose Weakness one per spellblade
        proc, and a ledger that collapsed those would be answering a
        question — "may one holder arm this twice over time?" — that no
        mechanic here declares.  ``PER_HOLDER`` keeps the holder in the key
        precisely so its keys can never collide across holders, so this
        clause is what makes the two declarations do the whole job between
        them and leaves no third policy hiding in the ledger.
        """
        declared = self._stacking_of.get(packet_source)
        if declared is None:
            return None
        mechanic, stacking = declared
        key = arm_key(subject, mechanic, holder, stacking)
        first = self._armed.setdefault(key, int(holder))
        if first == int(holder):
            return None
        return ArmingDrop(mechanic=mechanic, stacking=stacking, first_holder=first)


# The one live probe the kernel can read, joined to the one declaration
# shape that means it.  A pair, not a lookup with a fallback: a probe or a
# comparison absent from here is a rule the walk cannot price, and the join
# below raises instead of returning a rider that quietly amplifies nothing.
_KERNEL_PROBES: Mapping[tuple[Probe, Comparison], LiveProbe] = {
    (Probe.TARGET_HEALTH_FRACTION, Comparison.LT): LiveProbe.HEALTH_BELOW_RATIO,
}


@dataclass(frozen=True, slots=True)
class LiveAmpRider:
    """One holder's live amplifier, ready to ride that holder's own packets.

    Two parts, because the walk asks two different questions of it.
    :attr:`amp` is what the kernel evaluates at the instant of the hit;
    :attr:`damage_types` is what the *composition* asks before stamping it,
    since a rule that crits magic and true damage has no business riding a
    physical packet and the kernel should never be handed one to decline.
    """

    amp: LiveAmp
    damage_types: frozenset[str]

    def rides(self, damage_type: str) -> bool:
        """Whether this amplifier's declared typing admits *damage_type*."""
        return damage_type in self.damage_types


def live_amp_riders(
    owners: Sequence[str],
    *,
    level: int,
    fight_duration_seconds: float,
    target_bonus_health: float,
    holder_is_melee: bool,
) -> tuple[LiveAmpRider, ...]:
    """Every live-predicate amplifier *owners* declare, as kernel riders.

    The coupled-lane interpreter of a ``delta_amp`` rule whose activation is
    a :class:`~..item_behavior.LivePredicate`.  Such a rule is the one shape
    the pair engine can only answer for a single attacker: its predicate
    reads a pool that exists solely inside a simulation, and in a roster
    that pool is under everyone's fire.  So the *threshold* and the
    *fraction* are compiled here, from the same declaration and the same
    resolved fields the pair engine reads, and the *reading* is left to the
    walk.

    Derived, never keyed on a slot name: every chain slot is asked, and a
    rule qualifies by declaring a live predicate rather than by being
    Cinderbloom.  Three refusals rather than three silent skips —

    * a probe or comparison the kernel has no tag for,
    * a subject other than the holder, since a rider rides its own holder's
      event and a rule about somebody else's damage would ride the wrong
      one,
    * a rule whose declaration compiles no threshold or fraction, which
      :class:`~..interpreters.delta_amp.AmpSlot` already raises for —

    because an amplifier the interpreter declined to build is a rule that
    did not run, and this campaign exists because one of those was
    indistinguishable from a bonus of zero.
    """
    riders: list[LiveAmpRider] = []
    for slot_name in AMP_CHAIN_ORDER:
        slot = delta_amp.resolve_slot(
            owners,
            slot_name,
            level=level,
            fight_duration_seconds=fight_duration_seconds,
            target_bonus_health=target_bonus_health,
            holder_is_melee=holder_is_melee,
        )
        if slot is None:
            continue
        for index, rule in enumerate(slot.rules):
            activation = rule.payload.activation
            if not isinstance(activation, LivePredicate):
                continue
            riders.append(_rider_for(slot, rule, index, activation))
    return tuple(riders)


def live_amp_for(riders: Sequence[LiveAmpRider], damage_type: str) -> LiveAmp | None:
    """The one live amplifier that rides a packet of *damage_type*.

    ``None`` is the ordinary answer and means no holder declared one for
    this class of damage.  Two claimants raise: a packet carries one rider
    field, so a second amplifier would have to be dropped, and dropping it
    silently is this campaign's own failure at the moment the number is
    born.  How two live amps compose is a modelling ruling nobody has made,
    and the raise is what makes somebody make it.
    """
    claiming = [rider for rider in riders if rider.rides(damage_type)]
    if not claiming:
        return None
    if len(claiming) > 1:
        raise ValueError(
            "two live amplifiers claim one "
            f"{damage_type} packet ("
            + ", ".join(rider.amp.mechanic for rider in claiming)
            + "); a packet carries one rider, and how two of them compose is "
            "undeclared"
        )
    return claiming[0].amp


def _rider_for(slot, rule, index: int, activation: LivePredicate) -> LiveAmpRider:
    """One declared live predicate, as the value the kernel evaluates."""
    probe = _KERNEL_PROBES.get((activation.probe, activation.cmp))
    if probe is None:
        raise ValueError(
            f"{rule.mechanic_id} declares a live predicate the walk cannot "
            f"read ({activation.probe.value} {activation.cmp.value}); the "
            "kernel evaluates by tag, and a declaration with no tag is a "
            "rule that would not run rather than an amplifier of zero"
        )
    if rule.payload.subject is not Subject.HOLDER:
        raise ValueError(
            f"{rule.mechanic_id} declares subject "
            f"{rule.payload.subject.value} and rides its holder's own "
            "damage events; a rider amplifies the event it rides, so a "
            "subject naming somebody else would amplify the wrong packets"
        )
    return LiveAmpRider(
        amp=LiveAmp(
            probe=probe,
            threshold=slot.value(delta_amp.LIVE_THRESHOLD_FIELD, index),
            fraction=slot.value(delta_amp.AMP_FRACTION_FIELD, index),
            mechanic=rule.mechanic_id,
        ),
        damage_types=frozenset(
            damage_class.value for damage_class in rule.payload.typing.damage_classes
        ),
    )


__all__ = [
    "AppliesTo",
    "ArmKey",
    "ArmingDrop",
    "ArmingLedger",
    "HolderStacking",
    "LiveAmpRider",
    "Provenance",
    "arm_key",
    "live_amp_for",
    "live_amp_riders",
]
