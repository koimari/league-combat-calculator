"""What a cache is keyed on, and what makes its answer stale.

Eleven memos across the serving path used to key on ``id()`` — the address of
a mutable object — each re-verifying identity against a strong reference so an
address reused after a collection could not serve somebody else's value.  That
guard makes them *safe*; it does not make them *correct*.  An address is not
derived from the value it stands for, so an object mutated in place keeps its
key and keeps its cached answer, and the answer is now a number no rule
computed against the inputs it claims.

**Where that stands at S10, because this file is the worst place to describe a
tree that no longer exists.**  Migration frontier counter 7 — ``id()``-keyed
caches whose key is not derived from the served value, over
``src/calculator/{survival,program}`` and ``stats.py`` — reads **0**.  It is a
scoped counter, and outside its trees ten address-keyed sites survive:
``pipeline.py:1001``, ``support_effects.py:183`` and ``:226``, and seven in
``champions/`` (``engine.py``, ``slotlib.py``).  Every one of them is a row in
``data_registry``'s tables with an owner and a reason, and the three that pair
an address with the cache generation say ``OBJECT_IDENTITY`` beside
``DATA_VERSION`` rather than letting the counter member stand for the whole
key — which is what "every cache declares ``invalidated_by``" has to mean if
a scoped zero is not to read as a global one.

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
from typing import Any

from ..data_registry import GOVERNED_MEMOS, Invalidator, data_version


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

    That comparison only ever sees the parameters the two functions **share a
    name for**, which is the half that was missing: where a key function and
    a producer are written in two vocabularies, the shared-name set can be
    empty and the check passes by comparing nothing.  It did, here, and the
    live consequence was a producer parameter — ``build_program``'s
    ``patch`` — that was stored on the served value and named in no key.

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
      the served value at all.  That one is not taken on trust — the test
      file varies it and asserts the produced value does not move, and a new
      empty declaration fails until it has such a test.

    What construction enforces is that **no producer parameter escapes the
    mapping** and that every field it names is a declared key field.  A
    parameter in neither place is exactly the defect above.
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


def patch_fingerprint(patch: Any) -> tuple:
    """A per-pass parameter patch as a value key; ``()`` means no patch.

    The overrides are a mapping, so they are flattened in sorted field order:
    a ``dict`` cannot be part of a hashable key, and two patches that differ
    only in insertion order are one patch.

    Read by both program keys — what a program was built from and what it is
    — because the patch is a field of the built object *and* an input to the
    builder, and two spellings of one flattening would be two answers to
    "are these the same patch".
    """
    if patch is None:
        return ()
    overrides = getattr(patch, "overrides", {}) or {}
    return (
        str(getattr(patch, "reason", "")),
        tuple((str(field), overrides[field]) for field in sorted(overrides, key=str)),
    )


def program_inputs_fingerprint(
    roster: tuple,
    actors: Sequence[tuple],
    params: tuple,
    pass_index: int,
    patch: Any,
) -> tuple:
    """What a program was *built from* — roster, actors, params, pass, patch.

    The key of the cache that serves a built ``Program``, so its fields are
    the request-side inputs the builder consumed.  ``pass_index`` **and**
    ``patch`` are both among them, and the second one is why this sentence
    is not "the pass index, because a cross-pass dependency rebuilds the
    program": the pass index says *which* pass, the patch says *how it
    differs*, and the patch is the only thing that makes pass 2 a different
    program.  ``build_program`` stores it on the ``Program`` it returns, so a
    key carrying the index alone files two programs that differ in every
    override under one entry — pass 1's answer served for pass 2 with the
    override silently discarded, which is the reason the second pass existed.

    Distinct from :func:`program_fingerprint`, which keys on what a program
    *is* rather than on what produced it.  Two functions because they answer
    two different questions and a cache that confused them would serve one
    program's actions under another's key.
    """
    return (
        roster,
        tuple(actors),
        params,
        int(pass_index),
        patch_fingerprint(patch),
    )


def program_fingerprint(
    roster: tuple, events: Sequence[Any], pass_index: int, patch: Any
) -> tuple:
    """What a built program *is* — every field of it, as one value key.

    Every field, not the ones a caller expects to matter.  The cache this
    keys serves compiled actions, and the compiler reads the events; a key
    that carried only the roster and the pass would hand two programs with
    the same roster and different events one entry, which is an answer
    computed from inputs it no longer has — the exact staleness an ``id()``
    key produces, reached by a shorter route.
    """
    return (roster, tuple(events), int(pass_index), patch_fingerprint(patch))


# The declarations this layer's caches carry.  A registry rather than a
# docstring per cache, because "every cache declares ``invalidated_by``" is a
# property something has to be able to iterate.
#
# Each ``key_fields`` tuple is its key function's parameter list, in order:
# ``program`` is keyed by ``program_inputs_fingerprint`` and
# ``compiled_actions`` by ``compile.program_key``.  The test file asserts the
# tie by signature, so renaming a parameter without moving the declaration
# fails rather than quietly leaving the declaration describing a function
# that no longer exists.
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
    "every_declaration",
    "actor_fingerprint",
    "params_fingerprint",
    "patch_fingerprint",
    "program_fingerprint",
    "program_inputs_fingerprint",
    "roster_fingerprint",
]


def every_declaration() -> dict[str, frozenset[Invalidator]]:
    """Every cache in the tree, and what stales it — one answer, one call.

    Phase 4 criterion 14 opens "every cache declares ``invalidated_by``",
    and until S10 that was a sentence about *this module*: the memos over
    ``data/``-derived values declared their governance in ``data_registry``,
    in a different language, so the criterion was true of two caches and
    unaskable of eighteen.  It is one language now — :class:`Invalidator`
    is declared beside ``data_version`` and imported here — and this is the
    reader that makes the criterion a question with one answer instead of
    a survey of two registries.

    Two registries and not one, deliberately.  ``data_registry`` owns the
    memos because it owns the counter that stales them and imports nothing;
    this module owns the program layer's caches because a declaration here
    also carries its key fields and its producer's inputs, which a memo
    does not have.  What was wrong was not that there were two populations
    but that there were two vocabularies.
    """
    declared: dict[str, frozenset[Invalidator]] = {
        f"program.{name}": declaration.invalidated_by
        for name, declaration in CACHES.items()
    }
    for name, governance in GOVERNED_MEMOS.items():
        declared[name] = governance.invalidated_by
    return declared
