"""Sums over the ability-damage contract that only tests take.

The engine never folds either one: it evaluates parts one at a time
against live stats, and a receipt aggregates quantities where it is
composed.  Both folds are how a test states the whole-cast claim in one
line, so they live beside the tests rather than in the contract.

This is a test helper, not a test module: it holds no assertions.
"""

from collections.abc import Iterable

from src.calculator.ability_spec import DamagePart, Measured, Quantity


def quantity_sum(quantities: Iterable[Quantity]) -> Quantity:
    """Fold a set of quantities through ``__add__``, propagation and all.

    An empty fold is ``Measured(0.0)``: summing nothing is a rule that ran, and
    the caller who had nothing to sum is the one who knows whether that is a
    structural zero.
    """
    total: Quantity = Measured(amount=0.0)
    for quantity in quantities:
        total = total + quantity
    return total


def parts_raw_total(
    parts: tuple[DamagePart, ...],
    damage_type: str | None = None,
) -> float:
    """Sum the raw per-cast damage of *parts*, optionally for one type.

    HP-scaled parts contribute their static ``amount`` (0.0 unless set) —
    their live value exists only at evaluation time.
    """
    return sum(
        part.amount * part.count
        for part in parts
        if damage_type is None or part.damage_type == damage_type
    )
