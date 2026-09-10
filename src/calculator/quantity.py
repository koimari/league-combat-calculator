"""What a published number is: measured, a structural zero, withheld, or starved."""

from dataclasses import dataclass

from .ability_spec import Disposition


class WithheldHasNoValue(ValueError):
    """A caller asked a withheld quantity for the number it refused to give.

    Distinct from ``ProjectionStarvation`` on purpose.  A withheld leaf is a
    *modelled* refusal — coverage declined to price the mechanic and named a
    receipt — so the payload omits the number and publishes the receipt, and a
    consumer reaching for the number anyway has misread the contract.  A
    starved one is a programming error, which is why it raises the campaign's
    one lazily-raised exception instead.
    """


class StarvedSignal(RuntimeError):
    """A leaf has no value a rule computed, and saying so is the only answer.

    One boundary converts a member of this class into a response (the
    ``src/app.py`` catch); everywhere else it propagates, because a named
    refusal that is silently absorbed is a zero nobody computed.  Every
    member carries ``field``, ``producer`` and ``reason``, the three facts
    that boundary publishes.  A ``RuntimeError``, so a caller catching that
    keeps catching it.
    """

    #: The disposition every member of this class *is*, so the boundary reads
    #: the spelling off the exception rather than re-deriving it.
    disposition = Disposition.STARVED

    def __init__(
        self, message: str, field_name: str, producer: str, reason: str
    ) -> None:
        """Name the leaf, who was asking for it, and why it has no answer."""
        super().__init__(message)
        self.field = field_name
        self.producer = producer
        self.reason = reason


class ProjectionStarvation(StarvedSignal):
    """A consumer asked a stream a question this result cannot answer.

    A projection and a consumer disagree, which is a programming error and
    not a data condition; it is raised lazily, on the first read of an
    inadequate representation.
    """


def projection_starvation(
    field_name: str, producer: str, reason: str
) -> ProjectionStarvation:
    """The signal for *producer* asking the *field_name* stream it cannot answer."""
    return ProjectionStarvation(
        f"STARVED: {producer or '<unnamed holder>'} asked for the "
        f"{field_name} stream — {reason}",
        field_name,
        producer,
        reason,
    )


class _QuantityAlgebra:
    """The fold shared by all four dispositions.

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
        """Fold two quantities; the clause order below is the rule.

        1. a ``Starved`` operand raises, because folding it is reading it and
           a total that swallowed a programming error is what starvation
           exists to catch;
        2. otherwise any ``Withheld`` operand makes the sum ``Withheld``,
           naming every receipt it swallowed, deduplicated, in first-seen
           order;
        3. otherwise both sides are ``Measured``/``StructuralZero`` and fold
           to ``Measured``, a structural zero contributing 0.0.

        Two structural zeros fold to ``Measured(0.0)`` rather than a third
        structural zero: the summation itself ran over adequate inputs, and
        ``StructuralZero`` carries one reason with no way to merge two.
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
        raise projection_starvation(self.field, self.producer, self.reason)


# The four dispositions as a value type (D-72).  ``Disposition`` survives as
# this union's tag projection rather than as a parallel annotation, which is
# what makes "every leaf carries exactly one disposition" a property of the
# type instead of a discipline maintained by tests.
Quantity = Measured | StructuralZero | Withheld | Starved
