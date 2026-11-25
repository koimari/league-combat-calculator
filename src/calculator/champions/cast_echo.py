"""A kit whose basic casts bank stacks and echo the cast that spends them.

Seraphine's Echo: each basic ability cast banks a stack up to a cap, and the
basic cast that finds the cap spends it to cast again at no cost a beat
later. A module states the rule as :class:`CastEcho`; :func:`echoed_casts`
walks one fight's planned casts in time order and marks the ones that echo.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CastEcho:
    """Which casts bank stacks, how many make an echo, and when it lands.

    ``starts_full`` is the stacks a fight opens with at the cap, so its first
    basic cast echoes. The cast that spends the stacks banks none.
    """

    slots: tuple[str, ...]
    stacks_to_echo: int
    starts_full: bool
    delay_seconds: float

    def __post_init__(self) -> None:
        """Refuse a rule no cast could satisfy."""
        if not self.slots or self.stacks_to_echo < 1 or self.delay_seconds < 0.0:
            raise ValueError(
                f"CastEcho needs slots, a positive cap and a delay: {self}"
            )


def echoed_casts(
    echo: CastEcho,
    cast_times: Mapping[str, Sequence[float]],
    cast_order: Sequence[str],
) -> dict[str, tuple[bool, ...]]:
    """Per slot, whether each of its planned casts echoes.

    Casts are walked by time, and casts at one instant in the rotation's own
    ``cast_order``, the order the plan issues them in.
    """
    rank = {slot: index for index, slot in enumerate(cast_order)}
    timeline = sorted(
        (time, rank.get(slot, len(rank)), slot, ordinal)
        for slot in echo.slots
        for ordinal, time in enumerate(cast_times.get(slot, ()))
    )
    flags = {slot: [False] * len(cast_times.get(slot, ())) for slot in echo.slots}
    stacks = echo.stacks_to_echo if echo.starts_full else 0
    for _time, _rank, slot, ordinal in timeline:
        if stacks >= echo.stacks_to_echo:
            flags[slot][ordinal] = True
            stacks = 0
        else:
            stacks += 1
    return {slot: tuple(marks) for slot, marks in flags.items()}
