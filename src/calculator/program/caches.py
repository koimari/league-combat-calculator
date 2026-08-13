"""What a cache is keyed on, and what makes its answer stale.

Eleven memos across the serving path key on ``id()`` — the address of a
mutable object — and each one re-verifies identity against a strong reference
so an address reused after a collection cannot serve somebody else's value.
That guard makes them *safe*; it does not make them *correct*.  An address is
not derived from the value it stands for, so an object mutated in place keeps
its key and keeps its cached answer, and the answer is now a number no rule
computed against the inputs it claims.

Two rules close that, and this module is where they are written down.

1. **A cache key is a value derived from the object the cache serves**, and
   the served value is immutable.  ``id()`` survives only as a fast path in
   front of a value key — never as the key itself.
2. **Every cache declares what invalidates it**, including ``data_version``,
   because a patch-day refresh that leaves a derived number cached is the
   stale literal CLAUDE.md rule 5 bans, one layer up.

The fingerprints below are the value keys the program layer uses.  They are
tuples of primitives, so equality is structural and a mutation moves the key
rather than surviving it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any

from ..data_registry import data_version


class Invalidator(Enum):
    """What can make a cached answer wrong.

    ``DATA_VERSION`` is on every declaration in this module and is not
    optional: a cache that does not name it is a cache that survives a patch
    refresh, which is the one invalidation the calculator's own data layer
    guarantees will happen.
    """

    DATA_VERSION = "data_version"
    ROSTER = "roster"
    ACTOR_STATS = "actor_stats"
    PARAMS = "params"
    PROJECTION = "projection"


@dataclass(frozen=True, slots=True)
class CacheDeclaration:
    """One cache, its key fields, and everything that invalidates it.

    ``key_fields`` is the reader's half — the fields the key is derived
    from, named so a test can assert the declared set covers every field the
    served value reads.  ``invalidated_by`` is the writer's half.  A
    declaration with a field in neither is the silent staleness this module
    exists to remove.
    """

    name: str
    key_fields: tuple[str, ...]
    invalidated_by: frozenset[Invalidator]

    def __post_init__(self) -> None:
        """Every cache is invalidated by the data version, without exception."""
        if Invalidator.DATA_VERSION not in self.invalidated_by:
            raise ValueError(
                f"cache {self.name!r} does not declare DATA_VERSION as an "
                "invalidator; a derived number that survives a patch refresh "
                "is a stale literal with a cache in front of it"
            )
        if not self.key_fields:
            raise ValueError(
                f"cache {self.name!r} declares no key fields; a key derived "
                "from nothing is an identity key with extra steps"
            )


def roster_fingerprint(participant_ids: Sequence[str]) -> tuple:
    """The roster's value key: who is in the fight, in order.

    Order is part of the key because every kernel field that names a
    participant names a roster *index*: the same five participants in two
    orders are two different index spaces, and serving one's cached actions
    to the other would hand a state to the wrong subject.
    """
    return (data_version(), tuple(str(pid) for pid in participant_ids))


def actor_fingerprint(actor: Any, fields: Iterable[str]) -> tuple:
    """One actor's value key over the named stat fields.

    ``fields`` is passed rather than discovered so the key is *declared*: a
    cache that fingerprinted every attribute it could reach would silently
    grow a key whenever the actor grew a field, and shrink one whenever a
    field moved.
    """
    stats = getattr(actor, "stats", {}) or {}
    return (
        str(getattr(actor, "participant_id", "")),
        tuple((field, stats.get(field)) for field in sorted(fields)),
    )


def params_fingerprint(params: Any, fields: Iterable[str]) -> tuple:
    """The request parameters a cached program depends on, as a value key."""
    return tuple((field, getattr(params, field, None)) for field in sorted(fields))


def program_fingerprint(
    roster: tuple, actors: Sequence[tuple], params: tuple, pass_index: int
) -> tuple:
    """The whole program's value key — roster, actors, params and pass.

    ``pass_index`` is in the key because a cross-pass dependency rebuilds the
    program with a parameter patch: pass 2 is a different program, and
    serving pass 1's compiled actions for it would silently discard the
    patch that was the whole reason for the second pass.
    """
    return (roster, tuple(actors), params, int(pass_index))


# The declarations this layer's caches carry.  A registry rather than a
# docstring per cache, because "every cache declares ``invalidated_by``" is a
# property something has to be able to iterate.
CACHES: Mapping[str, CacheDeclaration] = {
    "program": CacheDeclaration(
        name="program",
        key_fields=("roster", "actors", "params", "pass_index"),
        invalidated_by=frozenset(
            {
                Invalidator.DATA_VERSION,
                Invalidator.ROSTER,
                Invalidator.ACTOR_STATS,
                Invalidator.PARAMS,
            }
        ),
    ),
    "compiled_actions": CacheDeclaration(
        name="compiled_actions",
        key_fields=("program", "projection"),
        invalidated_by=frozenset(
            {
                Invalidator.DATA_VERSION,
                Invalidator.ROSTER,
                Invalidator.ACTOR_STATS,
                Invalidator.PARAMS,
                Invalidator.PROJECTION,
            }
        ),
    ),
}


__all__ = [
    "CACHES",
    "CacheDeclaration",
    "Invalidator",
    "actor_fingerprint",
    "params_fingerprint",
    "program_fingerprint",
    "roster_fingerprint",
]
