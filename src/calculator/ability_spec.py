"""The champion→engine ability-damage contract and the closed vocabularies.

An ability entry carries its damage arithmetic as a tuple of DamageParts;
the fight engine evaluates parts generically
(``damage._evaluate_cast_parts``) and never branches on
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

``Quantity`` — ``Measured | StructuralZero | Withheld | Starved`` — sits
beside ``Disposition`` for the same reason again, and turns it from a label
into an algebra (D-72): ``Disposition`` survives as the union's tag
projection, and the campaign's propagation rule for aggregates is
``__add__`` on the type rather than a discipline each consumer maintains.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum


class DamageClass(Enum):
    """Which resistance mitigates a number.

    The string values are the engine's own spellings, so
    ``part_damage_types()`` is the enum's projection rather than a second
    list that can drift from it.
    """

    MAGIC = "magic"
    PHYSICAL = "physical"
    TRUE = "true"


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


class WithheldHasNoValue(ValueError):
    """A caller asked a withheld quantity for the number it refused to give.

    Distinct from ``ProjectionStarvation`` on purpose.  A withheld leaf is a
    *modelled* refusal — coverage declined to price the mechanic and named a
    receipt — so the payload omits the number and publishes the receipt, and a
    consumer reaching for the number anyway has misread the contract.  A
    starved one is a programming error, which is why it raises the campaign's
    one lazily-raised exception instead.
    """


def _projection_starvation() -> type[Exception]:
    """``ProjectionStarvation``'s class, fetched at raise time.

    Its home is ``trigger_stream`` (the campaign's shared-names table), and
    ``trigger_stream`` imports *this* module — so a module-scope import here
    would be a cycle, and would make the dependency-free vocabulary leaf
    depend on the trigger bus.  A starved read is not a hot path (it raises),
    so the deferred lookup costs nothing that matters and the exception keeps
    its one home.
    """
    # pylint: disable-next=import-outside-toplevel,cyclic-import
    from .trigger_stream import ProjectionStarvation

    return ProjectionStarvation


class _QuantityAlgebra:
    """The fold shared by all four dispositions — the propagation row (D-72).

    Subclasses are the four members of :data:`Quantity`; this class holds
    nothing but ``__add__``, because propagation is arithmetic on the value
    type rather than a behaviour every consumer re-implements.  A total is
    also a leaf, and the natural implementation of a total contributes 0.0 for
    a withheld member — the incident re-created at the aggregate, fully
    compliant with every per-leaf rule.  Defining the fold here makes that
    failure unrepresentable rather than merely tested for.
    """

    __slots__ = ()

    def __add__(self, other: object) -> "Quantity":
        """Fold two quantities; the clause order below is the ruling.

        1. a ``Starved`` operand **raises**, because folding it is reading it,
           and a withheld total that quietly swallowed a programming error is
           the failure this campaign is named after;
        2. otherwise any ``Withheld`` operand makes the sum ``Withheld``,
           naming every receipt it swallowed, deduplicated, in first-seen
           order;
        3. otherwise both sides are ``Measured``/``StructuralZero`` and fold
           to ``Measured`` of the two values, a structural zero contributing
           0.0.

        Clause 3 makes a sum of two structural zeros ``Measured(0.0)`` rather
        than a third structural zero, deliberately: the *summation* is a rule
        that ran over adequate inputs, the members' declarations are their own
        receipts and not the total's, and ``StructuralZero`` carries one reason
        with no way to merge two.
        """
        if not isinstance(other, _QuantityAlgebra):
            return NotImplemented
        operands = (self, other)
        for operand in operands:
            if isinstance(operand, Starved):
                operand.read()
        receipts: list[str] = []
        for operand in operands:
            if isinstance(operand, Withheld):
                receipts.extend(
                    receipt for receipt in operand.receipts if receipt not in receipts
                )
        if receipts:
            return Withheld(receipts=tuple(receipts))
        return Measured(amount=self.read() + other.read())

    def read(self) -> float:
        """The number this quantity stands for, or the refusal it stands for."""
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class Measured(_QuantityAlgebra):
    """A rule ran against adequate inputs and produced this value, zero included."""

    amount: float

    @property
    def disposition(self) -> Disposition:
        """This quantity's tag — ``Disposition`` as a projection (D-72)."""
        return Disposition.MEASURED

    def read(self) -> float:
        """The number the rule produced."""
        return float(self.amount)


@dataclass(frozen=True, slots=True)
class StructuralZero(_QuantityAlgebra):
    """A declaration says the mechanic does not apply here; zero is the answer.

    ``reason`` is the receipt and it is required: a structural zero without one
    is an ordinary zero with a nicer name.
    """

    reason: str

    def __post_init__(self) -> None:
        """A declared zero with no declaration is not one."""
        if not self.reason.strip():
            raise ValueError("StructuralZero needs a reason; it is the receipt")

    @property
    def disposition(self) -> Disposition:
        """This quantity's tag."""
        return Disposition.STRUCTURAL_ZERO

    def read(self) -> float:
        """Zero — and the declaration above is why that is the answer."""
        return 0.0


@dataclass(frozen=True, slots=True)
class Withheld(_QuantityAlgebra):
    """Coverage refused to model this: named receipts and **no number**.

    ``receipts`` is a tuple rather than one string because a withheld total
    names every withheld member it swallowed, which is the propagation row's
    whole content.
    """

    receipts: tuple[str, ...]

    def __post_init__(self) -> None:
        """A refusal with no receipt is the blank this type exists to replace."""
        if not self.receipts or not all(receipt.strip() for receipt in self.receipts):
            raise ValueError("Withheld needs at least one non-empty receipt")

    @property
    def disposition(self) -> Disposition:
        """This quantity's tag."""
        return Disposition.WITHHELD

    def read(self) -> float:
        """Never: a withheld leaf carries receipts instead of a number."""
        raise WithheldHasNoValue(
            f"withheld quantity has no value; its receipts are {list(self.receipts)}"
        )


@dataclass(frozen=True, slots=True)
class Starved(_QuantityAlgebra):
    """A projection could not answer the question a rule asked.

    A programming error rather than a data condition: a consumer and a
    projection disagree about what the projection can represent.  Reading it
    raises ``ProjectionStarvation`` — lazily, on the *first read* rather than
    at construction, so the failure surfaces where the question was asked
    (D-25).  Exactly one handler catches it, at the request boundary in
    ``src/app.py``.
    """

    field: str
    producer: str
    reason: str

    @property
    def disposition(self) -> Disposition:
        """This quantity's tag.  Reading the tag is not reading the value."""
        return Disposition.STARVED

    def read(self) -> float:
        """Never returns: the campaign's one lazily-raised failure."""
        raise _projection_starvation()(self.field, self.producer, self.reason)


# The four dispositions as a value type (D-72).  ``Disposition`` survives as
# this union's tag projection rather than as a parallel annotation, which is
# what makes "every leaf carries exactly one disposition" a property of the
# type instead of a discipline maintained by tests.
Quantity = Measured | StructuralZero | Withheld | Starved


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
        if not isinstance(self.disposition, Disposition):
            raise ValueError("zero_policy.disposition must be a Disposition")
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


# The projection every DamagePart is validated against, computed from the
# enum once at import: the vocabulary has one home (DamageClass) and this
# is its cached string view, not a second declaration of the same fact.
_PART_DAMAGE_TYPES = frozenset(damage_class.value for damage_class in DamageClass)


def part_damage_types() -> frozenset[str]:
    """The string projection of ``DamageClass``.

    The engine and the champion layer speak damage types as strings; this
    is the only place those strings come from, so a fourth damage class is
    added to the enum and nowhere else.
    """
    return _PART_DAMAGE_TYPES


# The ``cc_kind`` values that count as an immobilize — the Wiki's
# "Immobilizing" crowd-control class (airborne, forced actions, root,
# sleep, stasis, stun, suppression), the trigger for Imperial Mandate's
# Command and Fimbulwinter's non-melee Everlasting. A slow is crowd
# control but not an immobilize.
# https://wiki.leagueoflegends.com/en-us/Types_of_Crowd_Control
IMMOBILIZING_CC_KINDS = frozenset(
    {
        "immobilize",  # generic reviewed immobilize (kind not narrowed)
        "airborne",
        "charm",
        "fear",
        "flee",
        "knockback",
        "knockup",
        "pull",
        "root",
        "sleep",
        "snare",
        "stasis",
        "stun",
        "suppression",
        "taunt",
    }
)

# Crowd control that is neither an immobilize nor a slow. Each is real
# control a reviewer read off the Wiki, and none of them arms Command or
# Everlasting, so they narrow a part to "reviewed, and it triggers nothing".
# They exist because the alternative for Malphite's Ground Slam cripple,
# Malzahar's Call of the Void silence and Teemo's Blinding Dart blind was to
# call them "slow" or "none", and both of those are false.
NON_IMMOBILIZING_CC_KINDS = frozenset({"slow", "cripple", "silence", "blind"})

# Every value a module may author as a part's ``cc_kind``. "none" is an
# explicit reviewed no-CC result. Anything else is a typo the engine rejects —
# a misspelled kind must never author a no-op stun.
CC_KIND_VOCABULARY = (
    IMMOBILIZING_CC_KINDS | NON_IMMOBILIZING_CC_KINDS | frozenset({"none"})
)


# The predicate that reads a raw row against the two constants above lives
# in ``trigger_stream``, not here: authoring vocabulary belongs beside
# ``DamagePart``, classification is transport.  This module keeps the
# vocabulary and nothing that reads an event with it.


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
        if self.cc_kind is not None and not isinstance(self.cc_kind, str):
            raise ValueError("DamagePart cc_kind must be a string or None")

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
        return (
            f"DamagePart({self.damage_type}, amount={self.amount}, "
            f"count={self.count}, hp_scaled={hp_scaled}, "
            f"crit_effectiveness={self.crit_effectiveness}{extras})"
        )
