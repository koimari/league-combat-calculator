"""An empowered basic attack the fight arms, counted by walking the plan.

A kit whose innate empowers a swing arms it in one of two ways, and both are
questions the fight already holds the answer to. Galio's Colossal Smash arms
on a timer, and every ability that hits a champion cuts three seconds off it.
Sylas' Petricite Burst arms on the cast itself, banking a stack per ability
and holding at most three for four seconds each.

Either way the count is a walk over two schedules the fight has: when the
casts land and when the swings do. A module states the rule with every number
sourced; nothing here knows a champion, and a rule that states neither an
arming timer nor a per-cast gain is refused rather than counted as zero.

The option a module keeps beside its rule stays an override, for the thing
neither schedule knows: whether the empowered swing actually reached the
target it was aimed at.
"""

from __future__ import annotations

import re
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

#: The sentence every stacking innate in this cache writes the same way:
#: "... apply a stack of <name> to <whom> for N seconds, refreshing ...
#: and stacking up to N times". The life and the cap are read from it, so
#: a module states which STREAMS stack and the cache states the rest.
_STACK_SENTENCE = re.compile(
    r"apply a stack of [^.]*?for (?P<seconds>\d+(?:\.\d+)?) seconds"
    r"[^.]*?stacking up to (?P<stacks>\d+) times",
    re.IGNORECASE,
)


def cached_stack_terms(ability: Mapping[str, Any], *, owner: str) -> tuple[float, int]:
    """One stacking innate's cached stack life and cap.

    Raises rather than answering a default: a cache that stops stating
    either number cannot be stood in for, and a counter with a guessed
    threshold prices a mechanic nobody reviewed.
    """
    effects = ability.get("effects")
    parts: list[str] = []
    for effect in effects if effects else ():
        description = effect.get("description")
        if description is not None:
            parts.append(str(description))
    description = " ".join(parts)
    match = _STACK_SENTENCE.search(description)
    if match is None:
        raise ValueError(
            f"{owner}: the cached innate no longer states its stack life and cap "
            "('apply a stack of ... for N seconds ... stacking up to N times')"
        )
    return float(match.group("seconds")), int(match.group("stacks"))


@dataclass(frozen=True)
class ArmedProcRule:
    """One kit's rule for arming an empowered basic attack.

    Three arms, and a rule carries at least one. ``cooldown`` arms one
    charge every so many seconds; ``per_cast`` banks one on each arming
    cast; ``hits_required`` counts HITS, from the swing stream or the
    ability stream or both, and procs on every Nth.
    ``cooldown_reduction_per_cast`` is Galio's shape, where a cast brings
    the timer forward rather than banking anything. ``stack_seconds``
    expires a banked charge, and ``max_stacks`` caps what may be held.
    """

    arming_slots: frozenset[str]
    max_stacks: int
    # True when the request named the count itself, which the module can
    # see and the fight cannot: the swing the schedules count may not have
    # reached its target, and only the reader knows that.
    requested: bool = False
    cooldown: float = 0.0
    cooldown_reduction_per_cast: float = 0.0
    per_cast: int = 0
    stack_seconds: float = 0.0
    armed_at_start: bool = True
    # The hit-counter arm: how many stacks a proc costs, which streams
    # apply one, and whether the application that completes the count
    # procs on the spot (Akshan, Ekko) or waits for a basic attack to
    # spend it (Talon).
    hits_required: int = 0
    stacks_from_swings: bool = False
    stacks_from_ability_hits: bool = False
    consumed_by_swing: bool = False
    # An ability hit spends a banked charge as well as a basic attack does
    # ("the next basic attack OR ability hit against enemies"), so the
    # spending stream is both.
    spent_by_ability_hits: bool = False

    def __post_init__(self) -> None:
        if self.max_stacks < 1:
            raise ValueError(
                f"ArmedProcRule max_stacks must be at least 1, got {self.max_stacks}"
            )
        if self.cooldown <= 0.0 and self.per_cast <= 0 and self.hits_required <= 0:
            raise ValueError(
                "ArmedProcRule states no cooldown, no per_cast gain and no "
                "hits_required, so nothing would ever arm the swing; a rule that "
                "arms nothing is a rule with no referent"
            )
        if self.hits_required > 0 and not (
            self.stacks_from_swings or self.stacks_from_ability_hits
        ):
            raise ValueError(
                "ArmedProcRule counts hits but names no stream to count them "
                "from; a counter with no input never reaches its threshold"
            )
        if self.hits_required > self.max_stacks:
            raise ValueError(
                f"ArmedProcRule needs {self.hits_required} stacks to proc but "
                f"holds at most {self.max_stacks}, so it never procs"
            )


def _required(payload: Mapping[str, Any], key: str, owner: str) -> Any:
    value = payload.get(key)
    if value is None:
        raise ValueError(
            f"{owner}: armed_procs declares no {key!r}; every number of the rule "
            "is sourced by the module, and a missing one cannot be guessed"
        )
    return value


def _optional(payload: Mapping[str, Any], key: str) -> float:
    """One number a rule may leave out, as the zero that means "no such arm"."""
    value = payload.get(key)
    return 0.0 if value is None else float(value)


def declared_rule(
    ability_damages: Mapping[str, Any],
) -> tuple[str, ArmedProcRule] | None:
    """The one armed-proc rule this kit declares, with its owner's name."""
    found: list[tuple[str, Mapping[str, Any]]] = []
    for key, info in ability_damages.items():
        if not isinstance(info, Mapping):
            continue
        payload = info.get("armed_procs")
        if payload:
            found.append((str(info.get("name", key)), payload))
    if not found:
        return None
    if len(found) > 1:
        raise ValueError(
            "Two slots declare armed_procs ("
            + ", ".join(name for name, _ in found)
            + "); one swing stream has one empowering innate"
        )
    owner, payload = found[0]
    return owner, ArmedProcRule(
        arming_slots=frozenset(_required(payload, "arming_slots", owner)),
        max_stacks=int(_required(payload, "max_stacks", owner)),
        requested=bool(_required(payload, "requested", owner)),
        hits_required=int(_optional(payload, "hits_required")),
        stacks_from_swings=bool(payload.get("stacks_from_swings")),
        stacks_from_ability_hits=bool(payload.get("stacks_from_ability_hits")),
        consumed_by_swing=bool(payload.get("consumed_by_swing")),
        spent_by_ability_hits=bool(payload.get("spent_by_ability_hits")),
        cooldown=_optional(payload, "cooldown"),
        cooldown_reduction_per_cast=_optional(payload, "cooldown_reduction_per_cast"),
        per_cast=int(_optional(payload, "per_cast")),
        stack_seconds=_optional(payload, "stack_seconds"),
        armed_at_start=bool(_required(payload, "armed_at_start", owner)),
    )


def counted_hit_times(
    rule: ArmedProcRule,
    swing_times: Sequence[float],
    ability_hit_times: Sequence[float],
) -> tuple[float, ...]:
    """WHEN the hit counter completes a cycle, over the streams it counts.

    A stack lands on each hit from a counted stream and expires on its own
    clock. The application that completes the count either procs where it
    lands, which is what "the third stack consumes them all" says, or waits
    for the next basic attack to spend it, which is what "the next basic
    attack against an enemy with 3 stacks" says. A stream a rule does not
    count still REFRESHES what is banked, the way a basic attack refreshes
    Talon's Wound without applying one.
    """
    events: list[tuple[float, bool]] = []
    if rule.stacks_from_swings:
        events += [(time, True) for time in swing_times]
    elif rule.consumed_by_swing:
        # Counted for the spending, and for the refresh, but not for a stack.
        events += [(time, False) for time in swing_times]
    if rule.stacks_from_ability_hits:
        events += [(time, True) for time in ability_hit_times]
    stacks: deque[float] = deque()
    procs: list[float] = []
    for time, applies in sorted(events, key=lambda row: row[0]):
        while stacks and stacks[0] < time:
            stacks.popleft()
        if applies:
            if len(stacks) >= rule.max_stacks:
                stacks.popleft()
            stacks.append(
                time + rule.stack_seconds if rule.stack_seconds > 0.0 else float("inf")
            )
        elif stacks and rule.stack_seconds > 0.0:
            # A refreshing hit renews what is banked without adding to it.
            stacks = deque(time + rule.stack_seconds for _ in stacks)
        spends = (not rule.consumed_by_swing) or (not applies)
        if spends and len(stacks) >= rule.hits_required:
            procs.append(time)
            stacks.clear()
    return tuple(procs)


def stack_levels_for_casts(
    rule: ArmedProcRule,
    cast_times: Sequence[float],
    swing_times: Sequence[float],
    ability_hit_times: Sequence[float],
) -> tuple[int, ...]:
    """The stack level each cast's own window collects, in cast order.

    A charge that attaches on the cast counts the hits that land on the
    target while it holds: every stream the rule stacks from, inside
    ``stack_seconds`` of the cast, capped at ``max_stacks``. The cast that
    places the charge does not stack it; the hits after it do, which is the
    cached reading ("attacks against the target increase its damage").
    """
    hits: list[float] = []
    if rule.stacks_from_swings:
        hits += list(swing_times)
    if rule.stacks_from_ability_hits:
        hits += list(ability_hit_times)
    hits.sort()
    levels: list[int] = []
    for cast in cast_times:
        end = cast + rule.stack_seconds if rule.stack_seconds > 0.0 else float("inf")
        landed = sum(1 for hit in hits if cast < hit <= end)
        levels.append(min(landed, rule.max_stacks))
    return tuple(levels)


def armed_swing_times(
    rule: ArmedProcRule,
    cast_times: Sequence[tuple[str, float]],
    swing_times: Sequence[float],
    ability_hit_times: Sequence[float] = (),
) -> tuple[float, ...]:
    """WHICH swings land empowered, walking the two schedules together.

    The walk is the game's order of events: a cast arms (or brings the timer
    forward) at the instant it lands, and a swing spends whatever is armed at
    the instant it swings. A tie goes to the cast, because a swing that
    lands with a cast is the swing the cast empowered.

    The timestamps are the answer, not their count: a row that authors an
    event per proc needs to know which swing carried it, and a row that only
    counts takes the length.
    """
    casts = sorted(((time, slot) for slot, time in cast_times), key=lambda row: row[0])
    stacks: deque[float] = deque()  # expiry times of banked charges
    ready_at = 0.0 if rule.armed_at_start else rule.cooldown
    cast_index = 0
    empowered: list[float] = []

    spends = list(swing_times)
    if rule.spent_by_ability_hits:
        spends += list(ability_hit_times)
    for swing in sorted(spends):
        while cast_index < len(casts) and casts[cast_index][0] <= swing:
            time, slot = casts[cast_index]
            cast_index += 1
            if slot not in rule.arming_slots:
                continue
            if rule.cooldown_reduction_per_cast > 0.0:
                # The timer comes forward, never behind the cast itself.
                ready_at = max(time, ready_at - rule.cooldown_reduction_per_cast)
            if rule.per_cast > 0:
                for _ in range(rule.per_cast):
                    if len(stacks) >= rule.max_stacks:
                        stacks.popleft()
                    stacks.append(
                        time + rule.stack_seconds
                        if rule.stack_seconds > 0.0
                        else float("inf")
                    )
        while stacks and stacks[0] < swing:
            stacks.popleft()
        if rule.cooldown > 0.0 and swing >= ready_at:
            empowered.append(swing)
            ready_at = swing + rule.cooldown
            continue
        if stacks:
            stacks.popleft()
            empowered.append(swing)
    return tuple(empowered)


def armed_swing_count(
    rule: ArmedProcRule,
    cast_times: Sequence[tuple[str, float]],
    swing_times: Sequence[float],
    ability_hit_times: Sequence[float] = (),
) -> int:
    """How many swings land empowered; the length of the walk's answer."""
    return len(armed_swing_times(rule, cast_times, swing_times, ability_hit_times))
