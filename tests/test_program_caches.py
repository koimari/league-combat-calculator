"""Phase 4 S4 — a cache key is a value, and every cache says what stales it.

``program/caches`` is the front door for the layer's cache discipline.  The
three properties under test are the ones an ``id()``-keyed memo cannot have:
a key that *moves* when the object it stands for is mutated, a declaration
naming ``data_version`` so a patch-day refresh cannot leave a derived number
cached behind it, and — the half a declaration alone never proves — that the
declared key fields **cover every field the served value reads**.

That last one is checked in two directions, because one of them was empty.

The first reads the two functions' own source: for every key field that is
also a parameter of the value's producer, every attribute the producer takes
off it must be an attribute the key function takes off it too.  That caught a
live defect — ``program_key`` keyed on the roster and the pass while
``compile_program`` read the events — but it can only ever see parameters the
two functions **share a name for**, and where they are written in two
vocabularies it compares nothing and passes.  It did, for the ``program``
cache, whose key function takes fingerprints and whose producer takes
participants and pair fights.

The second closes that: the population is the producer's whole signature.
Every parameter is declared as determined by named key fields, or declared
not to reach the value at all — and an empty declaration is pinned by a test
that varies the parameter and asserts the value does not move, never by the
declaration alone.  It was live too: ``build_program``'s ``patch`` is stored
on the ``Program`` it returns and was in no key field, so two builds whose
overrides differed were one entry for two unequal programs.
"""

import ast
import dataclasses
import inspect
import textwrap
from collections.abc import Callable
from typing import Any

import pytest

from src.calculator.data_registry import data_version
from src.calculator.item_behavior import ReceiptOnly, ReceiptScope
from src.calculator.program import build, caches
from src.calculator.program import compile as program_compile
from src.calculator.program.build import ParamPatch, Program, Projection
from src.calculator.program.events import Damage, RoutedEvent
from src.calculator.program.identity import EventId, PairOrigin
from src.calculator.survival.actions import TransitionRank
from src.calculator.trigger_stream import HolderStacking

# Which function keys each declared cache, and which function produces the
# value that cache serves.  A mapping in the test rather than a callable on
# the frozen declaration — but asserted set-equal to ``CACHES`` below, so a
# third cache cannot arrive without a row here and be checked by nothing.
CACHE_FUNCTIONS: dict[str, tuple[Callable[..., Any], Callable[..., Any]]] = {
    "program": (caches.program_inputs_fingerprint, build.build_program),
    "compiled_actions": (program_compile.program_key, program_compile.compile_program),
}

# Every ``(cache, producer parameter)`` declared inert — an empty tuple in
# ``producer_inputs``, meaning the parameter does not reach the served value.
# Listed here rather than derived, so a new empty declaration fails
# ``test_every_inert_input_has_a_behavioural_test`` until somebody writes the
# test that varies it.  A claim about what a function ignores is the one
# claim its own source cannot make.
_INERT_PRODUCER_INPUTS = {("program", "caps")}

# One engine result and two capability views, for the inertness pin below.
_ENGINE_RESULT = {
    "damage_events": [
        {
            "time": 0.0,
            "sequence": 0,
            "damage": 100.0,
            "damage_type": "magic",
            "source_key": "q",
        }
    ]
}
_CAPS = build.CapabilityView(mechanics={})
_RICH_CAPS = build.CapabilityView(
    mechanics={
        "amp": build.MechanicView(
            ReceiptOnly("no timed amp", ReceiptScope.SCORE_KERNEL_DAMAGE_MODIFIER),
            {"amp": "APPLIED"},
            HolderStacking.PER_HOLDER,
        )
    }
)


def _attribute_reads(function: Callable[..., Any], parameter: str) -> frozenset[str]:
    """Every attribute name *function* reads off its parameter *parameter*."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
    return frozenset(
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == parameter
        and isinstance(node.ctx, ast.Load)
    )


def _damage_event(ordinal: int, amount: float) -> RoutedEvent:
    """One routed damage event, the shape ``compile_program`` stages."""
    return RoutedEvent(
        id=EventId(PairOrigin("main", "enemy:1"), ordinal),
        subject=1,
        source=0,
        time=float(ordinal),
        sequence=ordinal,
        rank=TransitionRank.DAMAGE,
        payload=Damage(amount, "physical"),
    )


def _sample_program() -> Program:
    """A program with every field carrying a value worth moving off."""
    return Program(
        participants=("main", "enemy:1"),
        events=(_damage_event(0, 100.0), _damage_event(1, 60.0)),
        pass_index=0,
        patch=ParamPatch(overrides={"time_budget_ms": 1000}, reason="pass 2"),
    )


# One replacement per ``Program`` field, each a value the sample does not
# already carry.  Keyed by field name so the mutation test iterates
# ``dataclasses.fields`` and fails on a field nobody supplied a move for —
# a field added to ``Program`` cannot slip past the key unexamined.
_PROGRAM_FIELD_MOVES: dict[str, Any] = {
    "participants": ("main", "enemy:2"),
    "events": (_damage_event(0, 100.0),),
    "pass_index": 1,
    "patch": None,
}

# The two fields the compiler never reads.  ``actors`` and ``focus`` exist so
# the five views take exactly ``(Program, WalkResult)``: they name *whom* a
# published row is about and which participant the receipt is focused on, and
# ``compile_program`` reads neither -- it stages payloads onto roster indices.
# Naming them here rather than widening the key is the honest half of the same
# discipline ``('program', 'caps')`` follows: a field in a cache key that the
# value does not read makes every request a miss, and a field the value *does*
# read that is missing from the key is a wrong answer.  The behavioural half is
# the test below, which varies both and asserts the compiled actions do not
# move.
_PUBLICATION_ONLY_PROGRAM_FIELDS = frozenset({"actors", "focus"})


class Actor:
    """A stand-in for a combatant: an identity plus a mutable stat dict."""

    def __init__(self, participant_id: str, **stats: float) -> None:
        self.participant_id = participant_id
        self.stats = dict(stats)


class TestAKeyIsDerivedFromTheValue:
    """The property ``id()`` cannot have, stated as a mutation test."""

    def test_mutating_an_actor_moves_its_fingerprint(self) -> None:
        actor = Actor("main", ability_power=100.0)
        before = caches.actor_fingerprint(actor, ("ability_power",))
        actor.stats["ability_power"] = 140.0
        assert caches.actor_fingerprint(actor, ("ability_power",)) != before

    def test_two_actors_with_equal_stats_share_a_fingerprint(self) -> None:
        """Equality is structural, so two equal inputs are one cache entry."""
        first = Actor("main", ability_power=100.0)
        second = Actor("main", ability_power=100.0)
        fields = ("ability_power",)
        assert caches.actor_fingerprint(first, fields) == caches.actor_fingerprint(
            second, fields
        )

    def test_the_declared_field_set_bounds_the_key(self) -> None:
        """A key over "every attribute" would grow whenever the actor did."""
        actor = Actor("main", ability_power=100.0, armor=50.0)
        narrow = caches.actor_fingerprint(actor, ("ability_power",))
        actor.stats["armor"] = 90.0
        assert caches.actor_fingerprint(actor, ("ability_power",)) == narrow

    def test_the_roster_key_is_order_sensitive(self) -> None:
        """Two orders are two index spaces; one's actions are not the other's."""
        assert caches.roster_fingerprint(
            ("main", "ally:1")
        ) != caches.roster_fingerprint(("ally:1", "main"))

    def test_the_roster_key_carries_the_data_version(self) -> None:
        assert caches.roster_fingerprint(("main",))[0] == data_version()

    def test_two_passes_are_two_program_keys(self) -> None:
        """Which pass, as a key component."""
        roster = caches.roster_fingerprint(("main",))
        first = caches.program_inputs_fingerprint(roster, (), (), 0, None)
        second = caches.program_inputs_fingerprint(roster, (), (), 1, None)
        assert first != second

    def test_two_patches_are_two_program_inputs_keys(self) -> None:
        """How the pass differs, as a key component — the half that was missing.

        The pass index says *which* pass; the patch says how it differs, and
        ``build_program`` stores it on the ``Program`` it returns.  Keyed on
        the index alone, these two builds — same roster, same actors, same
        params, same pass, different overrides — were one cache entry for two
        unequal programs.
        """
        roster = caches.roster_fingerprint(("main",))
        first = ParamPatch(overrides={"x": 1}, reason="pass 2")
        second = ParamPatch(overrides={"x": 2}, reason="pass 2")
        assert caches.program_inputs_fingerprint(roster, (), (), 1, first) != (
            caches.program_inputs_fingerprint(roster, (), (), 1, second)
        )

    def test_no_patch_and_a_patch_are_two_program_inputs_keys(self) -> None:
        """Pass 1 is not pass 2 wearing the same key."""
        roster = caches.roster_fingerprint(("main",))
        patch = ParamPatch(overrides={"x": 1}, reason="pass 2")
        assert caches.program_inputs_fingerprint(roster, (), (), 1, None) != (
            caches.program_inputs_fingerprint(roster, (), (), 1, patch)
        )

    def test_two_patches_are_two_program_keys(self) -> None:
        """The patch is the only way pass 2 differs; a key blind to it serves
        pass 1's answer and discards the reason the pass existed."""
        roster = caches.roster_fingerprint(("main",))
        first = ParamPatch(overrides={"time_budget_ms": 1000}, reason="pass 2")
        second = ParamPatch(overrides={"time_budget_ms": 2000}, reason="pass 2")
        assert caches.program_fingerprint(roster, (), 1, first) != (
            caches.program_fingerprint(roster, (), 1, second)
        )

    def test_a_patch_key_is_insertion_order_independent(self) -> None:
        """Two dicts built in two orders are one patch, not two cache misses."""
        forward = ParamPatch(overrides={"a": 1, "b": 2}, reason="pass 2")
        backward = ParamPatch(overrides={"b": 2, "a": 1}, reason="pass 2")
        assert caches.patch_fingerprint(forward) == caches.patch_fingerprint(backward)

    def test_a_program_key_is_hashable(self) -> None:
        """It is a dict key or it is not a cache key."""
        assert isinstance(
            hash(program_compile.program_key(_sample_program(), Projection.SCORE)), int
        )


class TestEveryCacheDeclaresWhatStalesIt:
    """The registry half — a property something can iterate."""

    def test_every_declaration_names_the_data_version(self) -> None:
        for name, declaration in caches.CACHES.items():
            assert caches.Invalidator.DATA_VERSION in declaration.invalidated_by, name

    def test_a_declaration_without_it_cannot_be_constructed(self) -> None:
        with pytest.raises(ValueError, match="DATA_VERSION"):
            caches.CacheDeclaration(
                name="forgetful",
                key_fields=("roster",),
                producer_inputs={"roster": ("roster",)},
                invalidated_by=frozenset({caches.Invalidator.ROSTER}),
            )

    def test_a_declaration_with_no_key_fields_cannot_be_constructed(self) -> None:
        with pytest.raises(ValueError, match="no key fields"):
            caches.CacheDeclaration(
                name="keyless",
                key_fields=(),
                producer_inputs={"roster": ()},
                invalidated_by=frozenset({caches.Invalidator.DATA_VERSION}),
            )

    def test_a_declaration_with_no_producer_inputs_cannot_be_constructed(self) -> None:
        """A declaration that cannot say what the value was computed from."""
        with pytest.raises(ValueError, match="no producer inputs"):
            caches.CacheDeclaration(
                name="unsourced",
                key_fields=("roster",),
                producer_inputs={},
                invalidated_by=frozenset({caches.Invalidator.DATA_VERSION}),
            )

    def test_an_input_derived_from_a_non_key_field_cannot_be_constructed(self) -> None:
        """The ``patch`` defect, as a construction error.

        A producer input declared to be determined by something the key does
        not carry is an answer filed under inputs it no longer has — the
        shape ``build_program``'s ``patch`` had before this landed.
        """
        with pytest.raises(ValueError, match="not among its key fields"):
            caches.CacheDeclaration(
                name="leaky",
                key_fields=("roster",),
                producer_inputs={"participants": ("roster",), "patch": ("patch",)},
                invalidated_by=frozenset({caches.Invalidator.DATA_VERSION}),
            )

    def test_the_compiled_action_cache_declares_the_projection(self) -> None:
        """Score-mode and receipt-mode actions are not interchangeable."""
        declaration = caches.CACHES["compiled_actions"]
        assert caches.Invalidator.PROJECTION in declaration.invalidated_by


class TestTheDeclaredKeyCoversWhatTheValueReads:
    """The half a declaration alone never proves (criterion 14).

    ``invalidated_by`` says what *stales* an entry; ``key_fields`` says what
    the entry is *filed under*.  A cache can declare both correctly and still
    serve a wrong answer if the key omits an input the value was computed
    from — so these read the two functions' source and compare what each
    takes off the same object.
    """

    def test_every_declaration_has_a_key_function_and_a_producer(self) -> None:
        """A declaration nothing here names would be checked by nothing."""
        assert set(CACHE_FUNCTIONS) == set(caches.CACHES)

    def test_the_declared_fields_are_the_key_functions_parameters(self) -> None:
        """The tie that stops a declaration describing a vanished signature."""
        for name, (key_function, _) in CACHE_FUNCTIONS.items():
            parameters = tuple(inspect.signature(key_function).parameters)
            assert caches.CACHES[name].key_fields == parameters, name

    def test_the_key_reads_every_field_the_producer_reads(self) -> None:
        """Criterion 14's own sentence, as a source comparison.

        For each key field that the producer also takes, every attribute the
        producer reads off it must be one the key function reads off it too.
        Before this landed, ``compile_program`` read ``program.events`` and
        ``program_key`` did not, so two programs holding different events
        shared one key.
        """
        for name, (key_function, producer) in CACHE_FUNCTIONS.items():
            producer_parameters = inspect.signature(producer).parameters
            for field in caches.CACHES[name].key_fields:
                if field not in producer_parameters:
                    continue
                uncovered = _attribute_reads(producer, field) - _attribute_reads(
                    key_function, field
                )
                assert not uncovered, (name, field, sorted(uncovered))

    def test_the_producer_actually_reads_something(self) -> None:
        """A subset check over two empty sets would pass by reading nothing."""
        assert _attribute_reads(program_compile.compile_program, "program")

    def test_the_attribute_comparison_is_vacuous_for_the_program_cache(self) -> None:
        """Named, so the next reader does not mistake it for coverage.

        ``program_inputs_fingerprint`` and ``build_program`` are written in
        two vocabularies — fingerprints versus participants and pair fights —
        and every name they do share is a scalar the producer stores rather
        than reads.  So for this cache the comparison above is
        ``frozenset()`` minus ``frozenset()`` and asserts nothing.  That is
        not a bug in the comparison; it is its domain.  The tests below are
        what covers this cache, and this one fails the day a shared parameter
        acquires an attribute read — the day the comparison starts carrying
        weight and somebody should re-read which check is doing the work.
        """
        key_function, producer = CACHE_FUNCTIONS["program"]
        shared = set(inspect.signature(key_function).parameters) & set(
            inspect.signature(producer).parameters
        )
        assert shared, "the two signatures share no name at all"
        for parameter in shared:
            assert not _attribute_reads(producer, parameter), parameter

    def test_every_producer_parameter_is_declared(self) -> None:
        """The direction the attribute comparison cannot have.

        The population is the producer's **whole signature**, not the names
        it happens to share with the key function.  ``build_program``'s
        ``patch`` reached the served value — it is stored on the returned
        ``Program`` — and appeared in no key field and in no declaration; two
        builds whose overrides differed were one key for two unequal
        programs.  A parameter added to a producer now arrives here.
        """
        for name, (_, producer) in CACHE_FUNCTIONS.items():
            declared = set(caches.CACHES[name].producer_inputs)
            assert declared == set(inspect.signature(producer).parameters), name

    def test_every_declared_input_names_only_key_fields(self) -> None:
        """Construction enforces it; this is the property stated over the live rows."""
        for name, declaration in caches.CACHES.items():
            for parameter, fields in declaration.producer_inputs.items():
                assert set(fields) <= set(declaration.key_fields), (name, parameter)

    def test_every_inert_input_has_a_behavioural_test(self) -> None:
        """An empty tuple is the strong claim, so it may not be a bare claim.

        ``()`` says a producer parameter does not reach the served value at
        all.  Nothing in the source proves that, so each one is pinned by a
        test that varies it and asserts the value does not move — and a new
        empty declaration fails here until it has one.
        """
        inert = {
            (name, parameter)
            for name, declaration in caches.CACHES.items()
            for parameter, fields in declaration.producer_inputs.items()
            if not fields
        }
        assert inert == _INERT_PRODUCER_INPUTS

    def test_the_capability_view_does_not_reach_the_built_program(self) -> None:
        """``('program', 'caps')``'s behavioural half.

        ``build_program`` takes the capability view and discards it — the
        capability-driven fan-out is a later stage's — so it is declared
        inert rather than mapped to a key field.  Two views, one program: the
        day that stops being true, the declaration is wrong and this is what
        says so.
        """
        pair = build.pair_program(_ENGINE_RESULT, PairOrigin("main", "enemy:1"), _CAPS)
        empty = build.build_program(("main", "enemy:1"), [(pair, 0, 1)], _CAPS)
        declared = build.build_program(("main", "enemy:1"), [(pair, 0, 1)], _RICH_CAPS)
        assert empty == declared

    def test_every_program_field_moves_the_compiled_action_key(self) -> None:
        """Coverage stated over the value rather than over one call graph.

        ``dataclasses.fields`` is the population, so a field added to
        ``Program`` either enters the key or fails here — which is what makes
        "covers every field its value reads" hold for readers this test has
        never heard of.
        """
        program = _sample_program()
        base = program_compile.program_key(program, Projection.SCORE)
        for field in dataclasses.fields(Program):
            if field.name in _PUBLICATION_ONLY_PROGRAM_FIELDS:
                continue
            moved = dataclasses.replace(
                program, **{field.name: _PROGRAM_FIELD_MOVES[field.name]}
            )
            assert (
                program_compile.program_key(moved, Projection.SCORE) != base
            ), field.name

    def test_the_publication_fields_do_not_reach_the_compiled_actions(self) -> None:
        """``_PUBLICATION_ONLY_PROGRAM_FIELDS``'s behavioural half.

        ``actors`` and ``focus`` are read by the views and by nothing under
        the compiler, so they are excluded from the key above.  That is a
        claim about the value, and this is the test that makes it one: the
        same program compiled with and without a roster and a focus produces
        the identical action tuple.
        """
        program = _sample_program()
        published = dataclasses.replace(
            program,
            actors=tuple(
                Actor(participant_id) for participant_id in program.participants
            ),
            focus="main",
        )
        assert program_compile.compile_program(
            published, projection=Projection.SCORE
        ) == program_compile.compile_program(program, projection=Projection.SCORE)

    def test_a_data_refresh_moves_the_key(self, monkeypatch) -> None:
        """``DATA_VERSION`` is declared by every cache; here it is also true."""
        program = _sample_program()
        before = program_compile.program_key(program, Projection.SCORE)
        monkeypatch.setattr(caches, "data_version", lambda: "patch-99.9")
        assert program_compile.program_key(program, Projection.SCORE) != before
