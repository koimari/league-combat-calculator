"""A number and the view it was produced for, and the one way tagged numbers fold."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from ..item_behavior import EngineLane
from ..quantity import Quantity
from .views.view_tag import UnrankableNumber, ViewTag


class MixedViewFold(TypeError):
    """Two numbers meaning different things were added together.

    A ``TypeError`` and not a ``ValueError``, because the operands are not
    the same *kind* of number: one is what the coupled walk delivered and the
    other is what a single pair fight would have produced.  Their sum is not
    a wrong total, it is not a total.
    """

    def __init__(self, left: ViewTag, right: ViewTag) -> None:
        """Name both meanings, because the fix depends on which is wrong."""
        super().__init__(
            f"a {left.value} quantity may not be folded with a {right.value} "
            "one; a sum may never mix views (D-62)"
        )
        self.left = left
        self.right = right


@dataclass(frozen=True, slots=True)
class Tagged:
    """A quantity and what it means — the only thing a fold may add.

    ``Quantity.__add__`` (D-72) propagates *dispositions* through a sum: a
    withheld member makes the total withheld, a structural zero folds as
    zero.  It says nothing about views, because a disposition answers "did a
    rule produce this" and a tag answers "which engine's answer is it".  Both
    have to survive a sum, and the second is the one Imperial Mandate got
    wrong: the pair engine's preview and the coupled walk's delivery are both
    ``MEASURED``, both real, and adding them counts the mechanic twice.

    So the tag rides the quantity through the algebra, and a fold of two
    different tags raises rather than producing a number.  That is what
    "folding differently-tagged sources is a construction error" means:
    unrepresentable, not merely tested for.
    """

    quantity: Quantity
    tag: ViewTag

    def __add__(self, other: object) -> Tagged:
        """Fold two quantities that mean the same thing, or refuse."""
        if not isinstance(other, Tagged):
            return NotImplemented
        if other.tag is not self.tag:
            raise MixedViewFold(self.tag, other.tag)
        return Tagged(quantity=self.quantity + other.quantity, tag=self.tag)


def fold_tagged(parts: Iterable[Tagged]) -> Tagged:
    """Add every part, propagating both the disposition and the view.

    Raises:
        MixedViewFold: two parts carry different tags.
        ValueError: there are no parts.  An empty fold has no view to carry,
            and answering ``Measured(0.0)`` would invent one -- which is the
            zero-versus-absent confusion the whole campaign is about, at the
            aggregate.
    """
    total: Tagged | None = None
    for part in parts:
        total = part if total is None else total + part
    if total is None:
        raise ValueError(
            "an empty fold has no view tag to carry; a total over nothing is "
            "not a measured zero"
        )
    return total


def ranked_total(parts: Iterable[Tagged], *, surface: str) -> float:
    """Fold parts into the number a ranking reads, or refuse to produce one.

    A total folded entirely from previews is well-typed and still not a score.
    """
    total = fold_tagged(parts)
    if total.tag is not ViewTag.APPLIED:
        raise UnrankableNumber(surface, f"a {total.tag.value} total", ["<fold>"])
    return total.quantity.read()


def tag_for(view_tags: Mapping[EngineLane, ViewTag], lane: EngineLane) -> ViewTag:
    """What a declared mechanic's number means in *lane*, or a named refusal.

    Raises rather than defaulting: a lane nobody declared a tag for has no
    declared meaning, and answering ``APPLIED`` there is how a pair-authored
    preview gets summed into a coupled total with no symptom.  Both readers go
    through it, so "what does this number mean" has one implementation.
    """
    try:
        return view_tags[lane]
    except KeyError:
        raise KeyError(
            f"no view tag is declared for {lane.value}; a number with no "
            "declared meaning may not be folded into a total"
        ) from None
