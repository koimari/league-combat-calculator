"""The champion→engine ability-damage contract.

An ability entry carries its damage arithmetic as a tuple of DamageParts;
the fight engine evaluates parts generically
(``damage._evaluate_cast_parts``) and never branches on
champion-specific keys. Champion-unique scaling math lives in the
champion module as a ``hp_scaled_damage`` closure on the part.

This module is a dependency-free leaf between the champion layer and the
fight engine: both import the contract, neither imports the other.
"""

from collections.abc import Callable
from dataclasses import dataclass


_PART_DAMAGE_TYPES = frozenset({"magic", "physical", "true"})


@dataclass(frozen=True)
class DamagePart:
    """One mitigation unit of one ability cast.

    The engine evaluates parts in order, threading the target's running
    mitigated damage: a part's ``hp_scaled_damage`` sees the damage of
    parts (and casts) evaluated before it — Akali R2 scales off the HP
    remaining after R1.

    A "mixed" ability is never a mixed PART — it is two typed parts,
    with the triggering (magic) part FIRST: the evaluator's first-part
    return is the Horizon Focus trigger for mixed entries.

    Attributes:
        damage_type: "magic" | "physical" | "true" (anything else raises
            at construction — a typo must never mitigate as magic).
        amount: Raw damage when ``hp_scaled_damage`` is None.
        count: Times the part hits per cast (Fox-Fire subsequent ×2).
        hp_scaled_damage: missing_ratio (0..1) → raw damage for one hit;
            overrides ``amount``.
        crit_effectiveness: >0 — the part crits at this effectiveness
            (Akshan R: 0.3).
    """

    damage_type: str
    amount: float = 0.0
    count: int = 1
    hp_scaled_damage: Callable[[float], float] | None = None
    crit_effectiveness: float = 0.0

    def __post_init__(self) -> None:
        if self.damage_type not in _PART_DAMAGE_TYPES:
            raise ValueError(
                f"DamagePart damage_type must be one of "
                f"{sorted(_PART_DAMAGE_TYPES)}, got {self.damage_type!r}"
            )

    def __repr__(self) -> str:
        # Deterministic repr: the golden snapshot serializes entries via
        # repr(), and a closure's default repr embeds a memory address.
        hp_scaled = "yes" if self.hp_scaled_damage is not None else "no"
        return (
            f"DamagePart({self.damage_type}, amount={self.amount}, "
            f"count={self.count}, hp_scaled={hp_scaled}, "
            f"crit_effectiveness={self.crit_effectiveness})"
        )


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
