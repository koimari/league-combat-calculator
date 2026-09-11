"""How many times a summoned unit attacks inside the fight it was summoned in.

A pet's attack count is arithmetic on two numbers a module already sources:
how fast it attacks, and how long it is around for. Freezing that count at
one window's reading prices the same six Daisy swings in a five-second fight
and in a thirty-second one, which is wrong in both directions depending on
which fight the reader asked for.

So the count is derived from the fight's own clock, and the module's option
becomes an override for the thing the clock cannot know: whether the pet was
in range, alive and attacking the target the whole time. A request that names
the count gets the count it named.

The lifetime is the pet's own when the cache states one (a Thorn Spitter
"lasts for 8 seconds"); with no cached lifetime the fight window is the bound,
which is the conservative reading for a pet that is around until something
kills it.
"""

from __future__ import annotations

import math
from .slot_context import SlotCtx


def derived_attack_count(
    ctx: SlotCtx,
    option_key: str,
    *,
    attack_speed: float,
    fallback_window: float,
    lifetime: float | None = None,
    maximum: int,
) -> int:
    """The pet's attacks in this fight, or the count the request named.

    ``fallback_window`` is what a clockless parse reads: a direct
    ``parse_abilities`` call and a one-rotation fight carry no duration, and
    inventing one there would move every module-level reading.
    """
    requested = ctx.options.get(option_key)
    if requested is not None:
        return min(max(int(requested), 0), maximum)
    window = float(ctx.options.get("fight_duration_seconds") or fallback_window)
    if lifetime is not None:
        window = min(window, lifetime)
    if attack_speed <= 0.0 or window <= 0.0:
        return 0
    return min(int(math.floor(window * attack_speed)), maximum)


def window_detail(count: int, attack_speed: float, window: float) -> str:
    """The sentence a derived count owes its reader."""
    return (
        f"{count} attack(s): {attack_speed:.2f} attacks per second over "
        f"{window:g}s, derived from the fight window rather than declared"
    )


def pet_window_seconds(
    ctx: SlotCtx, *, fallback_window: float, lifetime: float | None = None
) -> float:
    """The seconds this pet is around for inside this fight."""
    window = float(ctx.options.get("fight_duration_seconds") or fallback_window)
    return min(window, lifetime) if lifetime is not None else window


def declared_override(ctx: SlotCtx, option_key: str) -> bool:
    """Whether the request named the count itself."""
    return ctx.options.get(option_key) is not None
