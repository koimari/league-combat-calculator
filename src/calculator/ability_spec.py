"""The champion→engine ability-damage contract and the closed vocabularies.

An ability entry carries its damage arithmetic as a tuple of DamageParts;
the fight engine evaluates parts generically
(``fight.rotation.cast_parts._evaluate_cast_parts``) and never branches on
champion-specific keys. Champion-unique scaling math lives in the
champion module as a ``hp_scaled_damage`` closure on the part.

This module is a dependency-free leaf between the champion layer and the
fight engine: both import the contract, neither imports the other. That
is also why the campaign's four closed vocabularies live here —
``DamageClass``, ``AttackClass``, ``Disposition`` and ``Authority`` are
declared once, in the one module every layer may import, so no consumer
has to re-spell a member as a bare string.  ``ZeroPolicy`` sits with them
for the same reason: it is a ``Disposition`` and the receipt that goes
with it, and both the champion entry builders and ``item_behavior``'s
rule union declare one.

``quantity.py`` holds the algebra over that tag (D-72): ``Quantity`` is
``Measured | StructuralZero | Withheld | Starved``, ``Disposition`` is its
projection, and the campaign's propagation rule for aggregates is ``__add__``
on the type rather than a discipline each consumer maintains.  It reads the
tag from here, which is the one direction that keeps this module a leaf.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DamageClass(Enum):
    """Which resistance mitigates a number.

    The string values are the engine's own spellings, so
    ``part_damage_types()`` is the enum's projection rather than a second
    list that can drift from it.
    """

    MAGIC = "magic"
    PHYSICAL = "physical"
    TRUE = "true"

    @classmethod
    def named(cls, damage_type: str) -> "DamageClass | None":
        """The member spelled ``damage_type``, or ``None`` outside the vocabulary."""
        return _DAMAGE_CLASSES.get(damage_type)

    @property
    def is_mitigable(self) -> bool:
        """Whether a resistance answers for this class at all."""
        return self in _MITIGATING_RESISTANCE

    @property
    def resistance_name(self) -> str:
        """This class's resistance by combatant-stat name; raises when none answers."""
        name = _MITIGATING_RESISTANCE.get(self)
        if name is None:
            raise KeyError(
                f"{self.value!r} damage meets no resistance, so it has no "
                "resistance name"
            )
        return name

    def resistance_term(
        self, *, armor: float | None, magic_resistance: float | None
    ) -> float | None:
        """The caller's term for this class's resistance, ``None`` when none answers."""
        if self is DamageClass.PHYSICAL:
            return armor
        return magic_resistance if self is DamageClass.MAGIC else None


class AttackClass(Enum):
    """How a number was delivered, independent of what mitigates it.

    A damage-restricted mechanic declares both axes: Abyssal Mask's Unmake
    is ``{MAGIC}`` from every attack class ("from all sources"), while a
    basic-attack-only amplifier is every damage class from
    ``{BASIC_ATTACK}``. ``OTHER`` covers damage that is neither — item
    procs, burns and the environment.
    """

    BASIC_ATTACK = "basic_attack"
    ABILITY = "ability"
    OTHER = "other"


class Disposition(Enum):
    """What a numeric leaf *is* — the campaign's one invariant, as a type.

    A number the model did not compute must never be indistinguishable
    from a number the model computed as zero, so every serialized leaf is
    exactly one of these:

    * ``MEASURED`` — a rule ran against adequate inputs and produced this
      value, zero included.
    * ``STRUCTURAL_ZERO`` — a declaration says the mechanic does not apply
      here; zero is the answer and the declaration is the receipt.
    * ``WITHHELD`` — coverage refused to model it: a named receipt and no
      number.
    * ``STARVED`` — a projection could not answer the question a rule
      asked. A programming error.

    Each member's value is its own name, because these spellings are also
    receipt strings and reason prefixes: a symbol and its serialized form
    cannot drift when they are one string.
    """

    MEASURED = "MEASURED"
    STRUCTURAL_ZERO = "STRUCTURAL_ZERO"
    WITHHELD = "WITHHELD"
    STARVED = "STARVED"


@dataclass(frozen=True, slots=True)
class ZeroPolicy:
    """What a zero out of one producer *means*, declared rather than inferred.

    The campaign's invariant at producer granularity: a producer that can
    legitimately yield 0.0 says ``STRUCTURAL_ZERO`` and gives the reason that
    is then the receipt; one that computed zero from real inputs says
    ``MEASURED``.  Required with no default wherever a declaration carries it
    (D-24), because a defaulted disposition is the indistinguishable zero
    this campaign exists to remove.

    It lives here rather than beside the rule union because two unrelated
    layers declare one — ``item_behavior``'s ``BehaviorRule`` and the
    champion entry builders in ``champions/slotlib`` — and the second cannot
    import the first without inverting this leaf's dependency direction.
    """

    disposition: Disposition
    reason: str

    def __post_init__(self) -> None:
        """A disposition with no reason is a label, not a receipt."""
        if not self.reason.strip():
            raise ValueError("zero_policy needs a reason")


class Authority(Enum):
    """Which engine owns a mechanic — the pair engine, the coupled walk, or both.

    Authority belongs to the smallest engine that can see every input the
    mechanic's rule reads: all-pair-local inputs are ``PAIR_ONLY``, and any
    roster input (another participant's damage, another holder's stacks,
    the subject's live HP under combined fire) is coupled-authoritative.

    * ``PAIR_ONLY`` — every input is pair-local.
    * ``SPLIT`` — the pair-local restriction of the rule is exactly the
      holder's own contribution, the two halves are provably disjoint, and
      the owner skip is machine-checked. This is the only member that
      carries an ``owner``.
    * ``COUPLED_AUTHORITATIVE`` — the coupled walk owns it outright.
    * ``COUPLED_AUTHORITATIVE_WITH_PAIR_PREVIEW`` — the walk owns the
      applied number and a pair-side preview survives, tagged theoretical
      so it is never summed into the coupled total.
    * ``COUPLED_ONLY`` — the walk owns it and no pair-side half exists at
      all.

    Declared here in 0A because 0B declares members on packets before
    ``trigger_stream`` — the eventual re-export home — exists.
    """

    PAIR_ONLY = "PAIR_ONLY"
    SPLIT = "SPLIT"
    COUPLED_AUTHORITATIVE = "COUPLED_AUTHORITATIVE"
    COUPLED_AUTHORITATIVE_WITH_PAIR_PREVIEW = "COUPLED_AUTHORITATIVE_WITH_PAIR_PREVIEW"
    COUPLED_ONLY = "COUPLED_ONLY"


# The enum's own lookup by spelling, so ``named()`` refuses an unknown
# string instead of raising the way ``DamageClass(value)`` does.
_DAMAGE_CLASSES = {member.value: member for member in DamageClass}

# Each class's resistance by combatant-stat name, which is also the walk's
# receipt label. TRUE is absent because no resistance answers for it, so
# each reader turns that absence into its own refusal.
_MITIGATING_RESISTANCE = {
    DamageClass.PHYSICAL: "armor",
    DamageClass.MAGIC: "magic_resistance",
}

# The projection every DamagePart is validated against, computed from the
# enum once at import: the vocabulary has one home (DamageClass) and this
# is its cached string view, not a second declaration of the same fact.
_PART_DAMAGE_TYPES = frozenset(_DAMAGE_CLASSES)


def part_damage_types() -> frozenset[str]:
    """The only string projection of ``DamageClass``, so the enum stays its one home."""
    return _PART_DAMAGE_TYPES


# The predicate that reads a raw event row against these classifications
# lives in ``trigger_stream``, not here: authoring vocabulary belongs
# beside ``DamagePart``, classification is transport.  This module keeps
# the vocabulary and nothing that reads an event with it.


@dataclass(frozen=True)
class DamagePart:  # pylint: disable=too-many-instance-attributes
    """One mitigation unit of one ability cast.

    The attribute-count check is disabled because this is a data record and
    the fields *are* the vocabulary: every one is a declared, documented
    mitigation axis a champion module names by keyword, and collapsing any
    of them into an untyped bag is the silent-default shape this module
    exists to refuse.  Same reasoning as ``trigger_stream``'s builder.

    The engine evaluates parts in order, threading the target's running
    mitigated damage: a part's ``hp_scaled_damage`` sees the damage of
    parts (and casts) evaluated before it — Akali R2 scales off the HP
    remaining after R1.

    A "mixed" ability is never a mixed PART — it is two typed parts,
    with the triggering (magic) part FIRST: the evaluator's first-part
    return is the Horizon Focus trigger for mixed entries.

    Attributes:
        damage_type: one of ``part_damage_types()``, the string projection
            of ``DamageClass`` (anything else raises at construction — a
            typo must never mitigate as magic).
        amount: Raw damage when ``hp_scaled_damage`` is None.
        count: Times the part hits per cast (Fox-Fire subsequent ×2).
        hp_scaled_damage: missing_ratio (0..1) → raw damage for one hit;
            overrides ``amount``.
        crit_effectiveness: >0 — the part crits at this effectiveness
            (Akshan R: 0.3).
        basic_damage: the part is classified basic damage in-game (a
            forced basic-attack swing, Caitlyn's Headshot rider) —
            basic-damage amplifiers (Hexoptics C44) apply to it.
        bonus_ad_ratio: raw damage this part gains per point of bonus AD
            granted MID-FIGHT, on top of what ``amount`` already prices
            (Darius' Noxian Might). It is the part's derivative in bonus
            AD, so a total-AD scaling declares its total-AD ratio.
            Ignored unless the fight grants such a buff — ``amount``
            alone remains the whole story for every static build.
        dot_stack_scaled: the part hits once per stacking-DoT stack on
            the target when the cast lands (Darius R's per-stack bonus).
            The fight engine ALWAYS resolves the count from the fight's
            stack timeline — no timeline means no stacks, so the part
            deals nothing and ``count`` is ignored. A champion that
            wants a fixed stack count says so with a plain part.
        time_offset: authored seconds from cast start to the first hit.
            ``None`` means the source has not certified sub-cast timing.
        hit_interval: authored seconds between repeated hits. Required for
            a repeated part to emit an exact event timeline.
    """

    damage_type: str
    amount: float = 0.0
    count: int = 1
    hp_scaled_damage: Callable[[float], float] | None = None
    crit_effectiveness: float = 0.0
    basic_damage: bool = False
    bonus_ad_ratio: float = 0.0
    dot_stack_scaled: bool = False
    time_offset: float | None = None
    hit_interval: float | None = None
    # Explicit crowd-control provenance for ordered item triggers.  ``None``
    # means the module has not reviewed this part's control effect; ``none``
    # is an explicit reviewed no-CC result.  The engine never infers control
    # from an ability name or description at runtime.
    cc_kind: str | None = None
    # What a zero ``amount`` on this part *means* (D-24).  ``None`` is the
    # unreviewed state a raw construction leaves; every part the champion
    # entry builders emit carries the policy those builders declared.
    # Deliberately absent from ``__repr__``: this is a declaration Phase 4
    # publishes through ``serialize_leaf``, not a value the pair snapshot
    # serializes, and printing it would move every golden ability repr for
    # a field no engine reads.
    #
    # ``compare=False`` for the same reason, and it is not a cosmetic
    # choice: a field the repr hides but ``__eq__`` and ``__hash__`` read
    # makes two parts that print identically compare unequal and occupy two
    # slots in a set, so any future dedup would silently discriminate on an
    # invisible field.  The policy is a statement *about* the number, not
    # part of the number's identity, so repr and equality agree by saying
    # the same thing.
    zero_policy: "ZeroPolicy | None" = field(default=None, compare=False)
    # Authored control duration.  A zero value means that the module has
    # marked the control kind but has not supplied a usable downtime interval.
    cc_duration: float = 0.0
    # A blockable projectile or skillshot marker for target-side defensive
    # interactions such as Braum E and Yasuo W.
    skillshot: bool = False
    # Source receipt for a control duration read from the ability atom catalog.
    # The field stays empty for parts without authored control metadata.
    control_source_atoms: tuple[dict[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if self.damage_type not in part_damage_types():
            raise ValueError(
                f"DamagePart damage_type must be one of "
                f"{sorted(part_damage_types())}, got {self.damage_type!r}"
            )
        if self.time_offset is not None and self.time_offset < 0:
            raise ValueError("DamagePart time_offset cannot be negative")
        if self.hit_interval is not None and self.hit_interval < 0:
            raise ValueError("DamagePart hit_interval cannot be negative")
        if self.cc_duration < 0:
            raise ValueError("DamagePart cc_duration cannot be negative")

    def __repr__(self) -> str:
        # Deterministic repr: the golden snapshot serializes entries via
        # repr(), and a closure's default repr embeds a memory address.
        hp_scaled = "yes" if self.hp_scaled_damage is not None else "no"
        # Optional fields appear only when set, keeping the golden reprs
        # of every pre-existing part byte-identical.
        extras = ", basic_damage=yes" if self.basic_damage else ""
        if self.bonus_ad_ratio:
            extras += f", bonus_ad_ratio={self.bonus_ad_ratio}"
        if self.dot_stack_scaled:
            extras += ", dot_stack_scaled=yes"
        if self.time_offset is not None:
            extras += f", time_offset={self.time_offset}"
        if self.hit_interval is not None:
            extras += f", hit_interval={self.hit_interval}"
        if self.cc_kind is not None:
            extras += f", cc_kind={self.cc_kind!r}"
        if self.cc_duration:
            extras += f", cc_duration={self.cc_duration}"
        if self.skillshot:
            extras += ", skillshot=yes"
        if self.control_source_atoms:
            extras += ", control_source_atoms=yes"
        return (
            f"DamagePart({self.damage_type}, amount={self.amount}, "
            f"count={self.count}, hp_scaled={hp_scaled}, "
            f"crit_effectiveness={self.crit_effectiveness}{extras})"
        )
