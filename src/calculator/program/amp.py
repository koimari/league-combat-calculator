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

**What is not here.**  ``modifier_events`` — the compiler from Phase 3's
declared ``DeltaAmpRule`` to armed :class:`~.events.DamageModifier` events —
is Phase 4 S7's, landing with the authority moves that give it something to
interpret.  Naming it here with an empty body would be a declaration that
outruns its implementation, which is the failure this campaign exists to
remove; the sentence is the marker instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..ability_spec import AttackClass, DamageClass
from ..item_behavior import EngineLane
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


__all__ = [
    "AppliesTo",
    "ArmKey",
    "HolderStacking",
    "Provenance",
    "arm_key",
]
