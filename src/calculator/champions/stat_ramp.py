"""A stack level the fight builds, granting a stat that is not attack speed.

An attack-speed ramp has somewhere exact to go: it re-rates the very stream
that stacks it, one swing at a time (``interpreters/rearmed_swings``). A
ramp that grants attack damage or resistances has no such seam, because the
stat sheet is resolved once and every cast is priced against it.

This module serves the MEAN LEVEL THE STACKING EVENTS MET: each counted swing
or cast reads the stacks standing just before it.  Terminus' penetration makes
the same approximation (``item_effects.StackingPenEffect.average_pen``), and it
is stated rather than discovered: a burst at second one is priced at a level
the fight only reaches later.  Averaging over events, not wall time, keeps
empty seconds out of the price, so a longer fight never lowers what its
earlier events met.

The alternative is a stat sheet re-resolved per event, which is a different
engine. Until there is one, an option that states the level outright remains
the way to price a specific instant.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import partial
from typing import Any

from ..ability_atoms import declared_payload, required_declaration


@dataclass(frozen=True)
class StatRampRule:
    """One kit's stack ramp over a stat the swing walker cannot carry."""

    per_stack: Mapping[str, float]
    max_stacks: int
    stack_duration: float
    stacks_from_swings: bool = False
    stacks_from_ability_casts: bool = False
    #: Which slots stack it, where only some do (Graves' True Grit comes off
    #: casts of E alone). Empty means every cast the schedule places.
    arming_slots: frozenset[str] = frozenset()
    #: What a FILLED count multiplies the whole grant by, where a cache says
    #: one (Zaahen's Determination doubles at its twelfth stack). 1.0 is the
    #: ordinary case and never changes a number.
    filled_multiplier: float = 1.0
    requested: bool = False
    owner: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        if self.max_stacks < 1:
            raise ValueError(
                f"{self.owner or 'stat_ramp'}: max_stacks must be at least 1, "
                f"got {self.max_stacks}"
            )
        if not self.per_stack:
            raise ValueError(
                f"{self.owner or 'stat_ramp'}: stat_ramp grants nothing per "
                "stack, so the level it walks has no referent"
            )
        if not (self.stacks_from_swings or self.stacks_from_ability_casts):
            raise ValueError(
                f"{self.owner or 'stat_ramp'}: stat_ramp names no stream to "
                "stack it, so the level never leaves zero"
            )
        if self.stack_duration <= 0.0:
            raise ValueError(
                f"{self.owner or 'stat_ramp'}: stat_ramp declares no positive "
                "stack_duration; a stack with no life cannot be walked"
            )

    def grant(self, level: float) -> dict[str, float]:
        """The stat grant *level* stacks are worth."""
        # The fill multiplier applies at the cap and nowhere else, which is
        # where the cache states it: a mean below the cap has not filled.
        held = max(0.0, min(float(level), float(self.max_stacks)))
        scale = self.filled_multiplier if held >= self.max_stacks else 1.0
        return {stat: value * held * scale for stat, value in self.per_stack.items()}


def declared_rule(
    ability_damages: Mapping[str, Any],
) -> tuple[str, StatRampRule] | None:
    """The one stat ramp this kit declares, with its owner's name."""
    declared = declared_payload(
        ability_damages, "stat_ramp", one="one stack count carries one stat ramp"
    )
    if declared is None:
        return None
    owner, payload = declared
    required = partial(required_declaration, payload, owner=owner, mechanic="stat_ramp")
    multiplier = payload.get("filled_multiplier")
    return owner, StatRampRule(
        per_stack={
            str(stat): float(value)
            for stat, value in dict(required("per_stack")).items()
        },
        max_stacks=int(required("max_stacks")),
        stack_duration=float(required("stack_duration")),
        stacks_from_swings=bool(payload.get("stacks_from_swings")),
        stacks_from_ability_casts=bool(payload.get("stacks_from_ability_casts")),
        arming_slots=frozenset(
            () if payload.get("arming_slots") is None else payload["arming_slots"]
        ),
        filled_multiplier=1.0 if multiplier is None else float(multiplier),
        requested=bool(payload.get("requested")),
        owner=owner,
    )


def mean_stack_level(
    rule: StatRampRule,
    swing_times: Sequence[float],
    ability_cast_times: Sequence[float],
    duration_seconds: float,
) -> float:
    """The mean stack count the counted events inside ``[0, duration)`` met.

    Each event reads the stacks standing just before it, then banks its own
    for the declared seconds; the cap drops the oldest.  A fight with no
    counted event has no level, which is zero rather than one nobody held.
    """
    events: list[float] = []
    if rule.stacks_from_swings:
        events += [float(time) for time in swing_times]
    if rule.stacks_from_ability_casts:
        events += [float(time) for time in ability_cast_times]
    events = sorted(time for time in events if 0.0 <= time < duration_seconds)
    if not events:
        return 0.0
    met = [_held_at(rule, events[:index], time) for index, time in enumerate(events)]
    return sum(met) / len(met)


def _held_at(rule: StatRampRule, events: Sequence[float], instant: float) -> int:
    """How many stacks stand at *instant*, replaying the bank from the top.

    Replayed rather than carried, because the cap evicts the OLDEST stack and
    a count taken at one instant cannot be stepped to the next without it.
    """
    live: list[float] = []
    for time in events:
        if time > instant:
            break
        live = [expiry for expiry in live if expiry > time]
        if len(live) >= rule.max_stacks:
            live.pop(0)
        live.append(time + rule.stack_duration)
    return sum(1 for expiry in live if expiry > instant)
