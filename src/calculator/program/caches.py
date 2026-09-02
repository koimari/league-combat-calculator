"""What a cache is keyed on, and what makes its answer stale.

An ``id()`` key is the address of a mutable object.  Re-verifying it against a
strong reference makes such a memo safe, not correct: an address is not derived
from the value it stands for, so an object mutated in place keeps its key and
its cached answer, and that answer is a number no rule computed against the
inputs it claims.

Address-keyed sites survive outside ``program/``, ``survival/`` and
``stats.py``: ``pipeline.py``, ``support_effects.py``, and seven in
``champions/`` (``engine.py``, ``slotlib.py``).  Each is a row in
``data_registry``'s tables with an owner and a reason, and the three pairing an
address with the cache generation say ``OBJECT_IDENTITY`` beside
``DATA_VERSION`` rather than letting one key field stand for the whole key.

Three rules close the general case, and this module is where they are written
down.

1. **A cache key is a value derived from the object the cache serves**, and
   the served value is immutable.  ``id()`` survives only as a fast path in
   front of a value key — never as the key itself.
2. **Every cache declares what invalidates it**, including ``data_version``,
   because a patch-day refresh that leaves a derived number cached is the
   stale literal CLAUDE.md rule 5 bans, one layer up.
3. **Every cache declares what its value was computed from**, parameter by
   parameter, and every one of those is either determined by a key field or
   declared not to reach the value at all.  Rules 1 and 2 are both satisfied
   by a key that is a perfectly good value and simply omits an input: the
   entry is fresh, derived, correctly invalidated — and filed under inputs
   that do not determine it.

The fingerprints below are the value keys the program layer uses.  They are
tuples of primitives, so equality is structural and a mutation moves the key
rather than surviving it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from ..data_registry import GOVERNED_MEMOS, Invalidator, data_version
from ..delivery_eligibility import CombatantFacts
from .build import ParamPatch, RoutedEvent

#: The value keys below, named so a cache declaration can spell what it holds.
RosterFingerprint = tuple[int, tuple[str, ...]]
ActorFingerprint = tuple[str, tuple[tuple[str, float | None], ...]]
PatchFingerprint = tuple[()] | tuple[str, tuple[tuple[str, object], ...]]
ProgramInputsFingerprint = tuple[
    RosterFingerprint,
    tuple[ActorFingerprint, ...],
    tuple[object, ...],
    int,
    PatchFingerprint,
]
ProgramFingerprint = tuple[
    RosterFingerprint, tuple[RoutedEvent, ...], int, PatchFingerprint
]


@dataclass(frozen=True, slots=True)
class CacheDeclaration:
    """One cache, its key fields, its producer's inputs, and what stales it.

    ``key_fields`` is the reader's half — the fields the key is derived
    from.  ``invalidated_by`` is the writer's half.  A declaration with a
    field in neither is the silent staleness this module exists to remove.

    ``key_fields`` is spelled as the **parameter names of the cache's key
    function**, and that is what makes the assertion mechanical rather than
    editorial: ``tests/test_program_caches`` ties each declaration to its key
    function by signature, then reads — from the source of both — every
    attribute the value's *producer* takes off a key field and requires the
    key function to take it too.

    That comparison only ever sees the parameters the two functions share a
    name for.  Where a key function and a producer are written in two
    vocabularies the shared-name set can be empty, and the check then passes
    by comparing nothing.

    ``producer_inputs`` closes that direction by making the producer's whole
    signature the population.  Every parameter of the value's producer is a
    key of this mapping, and its value names the key fields that determine
    it:

    * a **non-empty** tuple is a derivation claim — the parameter is a
      function of exactly these key fields.  ``pairs`` is not itself a key
      field because the engine results are derived from the roster, the
      actors and the request parameters, and a cache keyed on the derived
      object would have to build the object before it could look it up.
    * an **empty** tuple is the stronger claim: the parameter does not reach
      the served value at all.  That one is not taken on trust: the test file
      varies it and asserts the produced value does not move, and a new empty
      declaration fails until it has such a test.

    Construction enforces that no producer parameter escapes the mapping and
    that every field it names is a declared key field.
    """

    name: str
    key_fields: tuple[str, ...]
    producer_inputs: Mapping[str, tuple[str, ...]]
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
        if not self.producer_inputs:
            raise ValueError(
                f"cache {self.name!r} names no producer inputs; a key whose "
                "declaration cannot say what the value was computed from "
                "cannot be checked for covering it"
            )
        undeclared = {
            field
            for fields in self.producer_inputs.values()
            for field in fields
            if field not in self.key_fields
        }
        if undeclared:
            raise ValueError(
                f"cache {self.name!r} derives a producer input from "
                f"{sorted(undeclared)}, which is not among its key fields "
                f"{list(self.key_fields)}; an input the key cannot see is an "
                "answer cached under inputs it no longer has"
            )


def roster_fingerprint(participant_ids: Sequence[str]) -> RosterFingerprint:
    """The roster's value key: who is in the fight, in kernel index order."""
    return (data_version(), tuple(str(pid) for pid in participant_ids))


def actor_fingerprint(actor: CombatantFacts, fields: Iterable[str]) -> ActorFingerprint:
    """One actor's value key over the named stat fields.

    ``fields`` is passed rather than discovered so the key is declared, and
    does not move whenever the actor grows or loses an attribute.
    """
    stats = getattr(actor, "stats", {}) or {}
    return (
        str(getattr(actor, "participant_id", "")),
        tuple((field, stats.get(field)) for field in sorted(fields)),
    )


def patch_fingerprint(patch: ParamPatch | None) -> PatchFingerprint:
    """A per-pass parameter patch as a value key; ``()`` means no patch.

    The overrides are a mapping, flattened in sorted field order: a ``dict``
    cannot be part of a hashable key, and two patches differing only in
    insertion order are one patch.  Both program keys read this one function,
    so there is one answer to "are these the same patch".
    """
    if patch is None:
        return ()
    overrides = getattr(patch, "overrides", {}) or {}
    return (
        str(getattr(patch, "reason", "")),
        tuple((str(field), overrides[field]) for field in sorted(overrides, key=str)),
    )


def program_inputs_fingerprint(
    roster: RosterFingerprint,
    actors: Sequence[ActorFingerprint],
    params: tuple[object, ...],
    pass_index: int,
    patch: ParamPatch | None,
) -> ProgramInputsFingerprint:
    """What a program was built from: roster, actors, params, pass, patch.

    The pass index says which pass and the patch says how it differs, and both
    are needed: an index alone files two programs differing in every override
    under one entry.  :func:`program_fingerprint` keys on what a program is
    rather than on what produced it.
    """
    return (
        roster,
        tuple(actors),
        params,
        int(pass_index),
        patch_fingerprint(patch),
    )


def program_fingerprint(
    roster: RosterFingerprint,
    events: Sequence[RoutedEvent],
    pass_index: int,
    patch: ParamPatch | None,
) -> ProgramFingerprint:
    """What a built program is: every field of it, the events included."""
    return (roster, tuple(events), int(pass_index), patch_fingerprint(patch))


# The declarations this layer's caches carry.  A registry rather than a
# docstring per cache, because "every cache declares ``invalidated_by``" is a
# property something has to be able to iterate.
#
# Each ``key_fields`` tuple is its key function's parameter list, in order:
# ``program`` is keyed by ``program_inputs_fingerprint`` and
# ``compiled_actions`` by ``compile.program_key``.  The test file asserts the
# tie by signature, so renaming a parameter without moving the declaration
# fails rather than leaving the declaration describing something else.
#
# Each ``producer_inputs`` mapping is the *other* function's parameter list —
# ``build.build_program`` and ``compile.compile_program`` respectively — with
# the key fields that determine each one.  The two lists are written in two
# vocabularies on purpose (a builder takes participants and pair fights; a
# key takes fingerprints of them), which is exactly why the population has to
# be the signature rather than the names the two happen to share.
CACHES: Mapping[str, CacheDeclaration] = {
    "program": CacheDeclaration(
        name="program",
        key_fields=("roster", "actors", "params", "pass_index", "patch"),
        producer_inputs={
            "participants": ("roster",),
            # The engine results a pass is built from: a function of who is
            # in the fight, their stats, and the request parameters — the
            # three request-side fingerprints — and not a key field of its
            # own, because a key over the pair events would have to build
            # them before it could look the built program up.
            "pairs": ("roster", "actors", "params"),
            # Inert: ``build_program`` takes the capability view and does not
            # read it (the capability-driven fan-out is S7's).  Declared
            # empty rather than omitted, and the test file varies it and
            # asserts the program does not move, so the day it starts
            # reaching the value the declaration goes red.
            "caps": (),
            "pass_index": ("pass_index",),
            "patch": ("patch",),
        },
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
        producer_inputs={"program": ("program",), "projection": ("projection",)},
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
    "every_declaration",
    "patch_fingerprint",
    "program_fingerprint",
    "program_inputs_fingerprint",
    "roster_fingerprint",
]


def every_declaration() -> dict[str, frozenset[Invalidator]]:
    """Every cache in the tree, and what stales it: one answer, one call.

    Two registries, one vocabulary.  ``data_registry`` owns the memos because
    it owns the counter that stales them and imports nothing; this module owns
    the program layer's caches because a declaration here also carries key
    fields and producer inputs, which a memo does not have.
    """
    declared: dict[str, frozenset[Invalidator]] = {
        f"program.{name}": declaration.invalidated_by
        for name, declaration in CACHES.items()
    }
    for name, governance in GOVERNED_MEMOS.items():
        declared[name] = governance.invalidated_by
    return declared
