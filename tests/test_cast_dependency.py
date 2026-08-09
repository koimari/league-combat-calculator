"""The declared cast-dependency vocabulary leaf.

Phase 5's leaf lands before anything consumes it, so these tests cover the
module on its own terms: that it stays a leaf, that its two vocabularies
are closed and disjoint, that every import-time failure has a negative
test which reaches it, and that the two order functions Phase 0B's C6
consumes behave. The precedence table and the resolver merge belong to
``rotation_resolver`` and are tested with it.
"""

import ast
import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from src.calculator.cast_dependency import (
    BASE_CAST_SLOTS,
    DEPENDENCY_KINDS,
    INFERRED_EDGE_KINDS,
    CastDependency,
    CastDependencyError,
    ConflictingInferenceError,
    CustomOrderViolatesDependencyError,
    DeadSuppressionError,
    DeclaredCycleError,
    DuplicateDependencyError,
    MissingLatentReasonError,
    ResolvedCycleError,
    SelfDependencyError,
    SuppressedInference,
    SuppressionScopeError,
    UnknownDependencyKindError,
    UnknownInferredKindError,
    UnknownSlotError,
    UnreachableDependencyError,
    UnsourcedDependencyError,
    active_dependencies,
    check_order_satisfies_dependencies,
    expand_user_order,
    orderable_slots,
    validate_cast_dependencies,
    validate_cast_order_declaration,
)

ROOT = Path(__file__).resolve().parent.parent
LEAF = ROOT / "src" / "calculator" / "cast_dependency.py"

SOURCE = "https://wiki.leagueoflegends.com/en-us/Syndra@4024662"
SURFACE = {"P", "Q", "Q2", "W", "E", "R"}


def _dep(slot: str = "E", requires: str = "Q", **overrides) -> CastDependency:
    """A well-formed declaration, one field at a time overridden."""
    fields = {
        "slot": slot,
        "requires": requires,
        "kind": "cc_enabler",
        "reason": "Scatter the Weak stuns only through a scattered sphere",
        "source": SOURCE,
    }
    fields.update(overrides)
    return CastDependency(**fields)


def _suppression(**overrides) -> SuppressedInference:
    """The reverse ``cc_setup`` inference of ``_dep()``."""
    fields = {
        "setup": "E",
        "consume": "Q",
        "kind": "cc_setup",
        "reason": "the stun is the consumer of the sphere, not its setup",
    }
    fields.update(overrides)
    return SuppressedInference(**fields)


def _validate(deps, surface=None, module="synthetic") -> None:
    """``validate_cast_dependencies`` with the fixture surface."""
    validate_cast_dependencies(
        deps, slot_surface=surface if surface is not None else SURFACE, module=module
    )


class TestTheLeafIsALeaf:
    def test_it_imports_no_sibling_module(self) -> None:
        """The rotation-side sibling of ability_spec: stdlib only."""
        tree = ast.parse(LEAF.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.level == 0 and not str(node.module).startswith(
                    "src.calculator"
                ), f"cast_dependency.py:{node.lineno} imports a sibling module"
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("src.calculator")

    def test_loading_it_pulls_in_no_calculator_module(self) -> None:
        """Loaded by path in a fresh interpreter it adds no src.calculator entry.

        Imported through the package it would drag in ``__init__``'s whole
        tree, which says nothing about the module; loading the file itself
        is what proves the dependency set is empty.
        """
        code = (
            "import importlib.util, sys\n"
            "spec = importlib.util.spec_from_file_location('leaf', r'%s')\n"
            "module = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(module)\n"
            "leaked = [m for m in sys.modules if m.startswith('src.calculator')]\n"
            "assert not leaked, f'leaf pulled in {leaked}'\n"
            "assert len(module.INFERRED_EDGE_KINDS) == 12\n"
            "print('leaf ok')\n" % LEAF
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        assert result.returncode == 0, result.stderr
        assert "leaf ok" in result.stdout


class TestVocabularies:
    def test_base_cast_slots(self) -> None:
        assert BASE_CAST_SLOTS == ("P", "Q", "W", "E", "R")

    def test_dependency_kinds_are_four(self) -> None:
        assert DEPENDENCY_KINDS == frozenset(
            {"cc_enabler", "damage_enabler", "resource_enabler", "recast_of"}
        )

    def test_inferred_edge_kinds_are_twelve(self) -> None:
        assert len(INFERRED_EDGE_KINDS) == 12

    def test_the_two_vocabularies_are_disjoint(self) -> None:
        """One vocabulary would blur which surface owns a claim (D-80)."""
        assert not DEPENDENCY_KINDS & INFERRED_EDGE_KINDS

    def test_every_error_is_a_cast_dependency_error(self) -> None:
        """One base, so a boundary catches the family and keeps its 4xx."""
        for error in (
            UnknownSlotError,
            SelfDependencyError,
            DuplicateDependencyError,
            UnknownDependencyKindError,
            UnsourcedDependencyError,
            SuppressionScopeError,
            UnknownInferredKindError,
            MissingLatentReasonError,
            DeclaredCycleError,
            ConflictingInferenceError,
            ResolvedCycleError,
            UnreachableDependencyError,
            DeadSuppressionError,
            CustomOrderViolatesDependencyError,
        ):
            assert issubclass(error, CastDependencyError)
        assert issubclass(CastDependencyError, ValueError)


class TestDeclarationsAreFrozen:
    def test_a_dependency_cannot_be_mutated(self) -> None:
        with pytest.raises(FrozenInstanceError):
            _dep().slot = "W"

    def test_a_suppression_cannot_be_mutated(self) -> None:
        with pytest.raises(FrozenInstanceError):
            _suppression().kind = "amp"

    def test_a_declaration_carries_no_suppression_by_default(self) -> None:
        assert _dep().suppresses == ()


class TestImportGate:
    def test_a_well_formed_declaration_passes(self) -> None:
        _validate([_dep(suppresses=(_suppression(),))])

    def test_no_declarations_passes(self) -> None:
        """The 170 non-declaring champions must reach no new failure (D-85)."""
        _validate([])

    def test_an_unknown_slot_raises(self) -> None:
        with pytest.raises(UnknownSlotError, match="Z"):
            _validate([_dep(slot="Z")])

    def test_an_unknown_required_slot_raises(self) -> None:
        with pytest.raises(UnknownSlotError, match="requires="):
            _validate([_dep(requires="Z")])

    def test_a_synthetic_slot_the_module_declares_is_legal(self) -> None:
        """Validation never consults a global slot list (active-slot tier 1)."""
        _validate([_dep(slot="E", requires="Q2")])

    def test_a_self_dependency_raises(self) -> None:
        with pytest.raises(SelfDependencyError):
            _validate([_dep(slot="E", requires="E")])

    def test_a_repeated_pair_raises(self) -> None:
        with pytest.raises(DuplicateDependencyError):
            _validate([_dep(), _dep()])

    def test_the_same_slot_may_require_two_others(self) -> None:
        _validate([_dep(requires="Q"), _dep(requires="Q2")])

    def test_an_unknown_kind_raises(self) -> None:
        with pytest.raises(UnknownDependencyKindError, match="stack_consume"):
            _validate([_dep(kind="stack_consume")])

    def test_an_inferred_kind_is_not_a_declarable_kind(self) -> None:
        for kind in sorted(INFERRED_EDGE_KINDS):
            with pytest.raises(UnknownDependencyKindError):
                _validate([_dep(kind=kind)])

    def test_an_empty_reason_raises(self) -> None:
        with pytest.raises(UnsourcedDependencyError, match="no reason"):
            _validate([_dep(reason="   ")])

    def test_an_empty_source_raises(self) -> None:
        with pytest.raises(UnsourcedDependencyError):
            _validate([_dep(source="")])

    @pytest.mark.parametrize(
        "source",
        [
            "the wiki says so",
            "https://wiki.leagueoflegends.com/en-us/Syndra",
            "https://wiki.leagueoflegends.com/en-us/Syndra@",
            "https://wiki.leagueoflegends.com/en-us/Syndra@latest",
            "@4024662",
            "wiki.leagueoflegends.com/en-us/Syndra@4024662",
        ],
    )
    def test_a_source_that_is_not_url_at_revision_raises(self, source: str) -> None:
        """Prose checked only for non-emptiness would let the seed come back."""
        with pytest.raises(UnsourcedDependencyError, match="revision_id"):
            _validate([_dep(source=source)])

    def test_a_declared_cycle_raises(self) -> None:
        with pytest.raises(DeclaredCycleError, match="cyclic"):
            _validate([_dep(slot="E", requires="Q"), _dep(slot="Q", requires="E")])

    def test_a_longer_declared_cycle_raises(self) -> None:
        with pytest.raises(DeclaredCycleError):
            _validate(
                [
                    _dep(slot="E", requires="Q"),
                    _dep(slot="W", requires="E"),
                    _dep(slot="Q", requires="W"),
                ]
            )

    def test_a_diamond_is_not_a_cycle(self) -> None:
        _validate(
            [
                _dep(slot="W", requires="Q"),
                _dep(slot="E", requires="Q"),
                _dep(slot="R", requires="W"),
                _dep(slot="R", requires="E"),
            ]
        )


class TestSuppressionCannotBroaden:
    def test_the_exact_reverse_pair_is_accepted(self) -> None:
        _validate([_dep(suppresses=(_suppression(),))])

    @pytest.mark.parametrize(
        "setup,consume",
        [("E", "W"), ("W", "Q"), ("Q", "E"), ("R", "R")],
    )
    def test_anything_but_the_reverse_pair_raises(
        self, setup: str, consume: str
    ) -> None:
        """From E-requires-Q it must be impossible to express E->W (D-81)."""
        with pytest.raises(SuppressionScopeError, match="exact reverse pair"):
            _validate([_dep(suppresses=(_suppression(setup=setup, consume=consume),))])

    def test_an_unknown_inferred_kind_raises(self) -> None:
        with pytest.raises(UnknownInferredKindError, match="cc_enabler"):
            _validate([_dep(suppresses=(_suppression(kind="cc_enabler"),))])

    def test_a_suppression_with_no_reason_raises(self) -> None:
        with pytest.raises(UnsourcedDependencyError, match="no reason"):
            _validate([_dep(suppresses=(_suppression(reason=""),))])

    def test_a_blank_latent_reason_raises(self) -> None:
        """Present-but-empty is the half the leaf can see; the merge owns the rest."""
        with pytest.raises(MissingLatentReasonError, match="latent_reason"):
            _validate([_dep(suppresses=(_suppression(latent_reason=" "),))])

    def test_a_stated_latent_reason_is_accepted(self) -> None:
        _validate(
            [
                _dep(
                    requires="Q2",
                    suppresses=(
                        _suppression(
                            consume="Q2",
                            latent_reason=(
                                "Q2 carries the cast-exactly-once cooldown, so "
                                "_castable() never emits the reverse edge"
                            ),
                        ),
                    ),
                )
            ]
        )

    def test_a_repeated_suppression_triple_raises(self) -> None:
        with pytest.raises(DuplicateDependencyError, match="twice"):
            _validate([_dep(suppresses=(_suppression(), _suppression()))])

    def test_two_kinds_of_the_same_pair_are_distinct_suppressions(self) -> None:
        _validate(
            [_dep(suppresses=(_suppression(), _suppression(kind="mark_applier")))]
        )


class TestCastOrderDeclaration:
    def test_a_subset_permutation_passes(self) -> None:
        validate_cast_order_declaration(
            ["R", "Q", "Q2", "W", "E"], [], slot_surface=SURFACE, module="jayce"
        )

    def test_a_short_order_passes(self) -> None:
        validate_cast_order_declaration(
            ("W", "Q"), [], slot_surface=SURFACE, module="kaisa"
        )

    def test_a_slot_outside_the_surface_raises(self) -> None:
        with pytest.raises(UnknownSlotError, match="CAST_ORDER"):
            validate_cast_order_declaration(
                ["Q", "Z"], [], slot_surface=SURFACE, module="synthetic"
            )

    def test_a_repeated_slot_raises(self) -> None:
        with pytest.raises(DuplicateDependencyError, match="repeats"):
            validate_cast_order_declaration(
                ["Q", "W", "Q"], [], slot_surface=SURFACE, module="synthetic"
            )

    def test_an_order_contradicting_its_own_declaration_raises(self) -> None:
        """Fail at import, not surprise at runtime (P5-d)."""
        with pytest.raises(CustomOrderViolatesDependencyError):
            validate_cast_order_declaration(
                ["E", "Q", "W", "R"],
                [_dep()],
                slot_surface=SURFACE,
                module="synthetic",
            )

    def test_an_order_omitting_an_endpoint_is_unconstrained(self) -> None:
        validate_cast_order_declaration(
            ["E", "W"], [_dep()], slot_surface=SURFACE, module="synthetic"
        )


class TestActiveDependencies:
    def test_both_endpoints_live(self) -> None:
        dep = _dep()
        assert active_dependencies([dep], {"Q", "E", "W"}) == (dep,)

    def test_an_absent_endpoint_constrains_nothing(self) -> None:
        """Syndra's Q2 declaration below 40 splinters is inactive, not a failure."""
        assert active_dependencies([_dep(requires="Q2")], {"Q", "E"}) == ()

    def test_a_mapping_of_parsed_entries_is_a_live_slot_set(self) -> None:
        dep = _dep()
        assert active_dependencies([dep], {"Q": {}, "E": {}}) == (dep,)


class TestOrderableSlots:
    def test_the_base_surface(self) -> None:
        surface = {"P": {}, "Q": {}, "W": {}, "E": {}, "R": {}}
        assert orderable_slots(surface) == ("Q", "W", "E", "R")

    def test_a_recast_slot_is_not_orderable(self) -> None:
        surface = {"P": {}, "Q": {}, "Q2": {"recast_of": "Q"}, "W": {}}
        assert orderable_slots(surface) == ("Q", "W")

    def test_the_result_does_not_depend_on_parse_order(self) -> None:
        assert orderable_slots({"R": {}, "E": {}, "Q": {}}) == ("Q", "E", "R")

    def test_an_unstamped_synthetic_slot_raises(self) -> None:
        """No hand parent-slot table: the stamp is the one authority (D-11)."""
        with pytest.raises(UnknownSlotError, match="recast_of"):
            orderable_slots({"Q": {}, "Q2": {}})

    def test_a_blank_stamp_does_not_count_as_stamped(self) -> None:
        with pytest.raises(UnknownSlotError):
            orderable_slots({"Q": {}, "R_buff": {"recast_of": ""}})


class TestExpandUserOrder:
    def test_a_live_recast_is_reinserted_after_its_parent(self) -> None:
        live = {"Q": {}, "Q2": {"recast_of": "Q"}, "W": {}, "E": {}, "R": {}}
        assert expand_user_order(["Q", "W", "E", "R"], live) == [
            "Q",
            "Q2",
            "W",
            "E",
            "R",
        ]

    def test_a_recast_follows_its_parent_wherever_the_parent_is(self) -> None:
        live = {"Q": {}, "Q2": {"recast_of": "Q"}, "W": {}, "E": {}, "R": {}}
        assert expand_user_order(["W", "E", "Q", "R"], live) == [
            "W",
            "E",
            "Q",
            "Q2",
            "R",
        ]

    def test_a_dead_recast_is_not_inserted(self) -> None:
        """Below 40 splinters Q2 does not exist and must not be scheduled."""
        live = {"Q": {}, "W": {}, "E": {}, "R": {}}
        assert expand_user_order(["Q", "W", "E", "R"], live) == ["Q", "W", "E", "R"]

    def test_an_explicitly_named_recast_is_not_duplicated(self) -> None:
        live = {"Q": {}, "Q2": {"recast_of": "Q"}, "W": {}}
        assert expand_user_order(["Q", "Q2", "W"], live) == ["Q", "Q2", "W"]

    def test_a_recast_chain_is_expanded_transitively(self) -> None:
        live = {"Q": {}, "Q2": {"recast_of": "Q"}, "Q3": {"recast_of": "Q2"}}
        assert expand_user_order(["Q"], live) == ["Q", "Q2", "Q3"]

    def test_two_recasts_of_one_parent_are_deterministic(self) -> None:
        live = {"R": {}, "R_onhit": {"recast_of": "R"}, "R_buff": {"recast_of": "R"}}
        assert expand_user_order(["R"], live) == ["R", "R_buff", "R_onhit"]


class TestCheckOrderSatisfiesDependencies:
    def test_a_satisfying_order_passes(self) -> None:
        check_order_satisfies_dependencies(
            ["Q", "Q2", "E", "W", "R"], [_dep()], {"Q", "Q2", "E", "W", "R"}
        )

    def test_an_inverted_order_raises(self) -> None:
        with pytest.raises(CustomOrderViolatesDependencyError):
            check_order_satisfies_dependencies(
                ["E", "Q", "W", "R"], [_dep()], {"Q", "E", "W", "R"}
            )

    def test_the_refusal_quotes_the_declaration_reason_and_source(self) -> None:
        """The refusal names the mechanic, not the rule that caught it (D-86)."""
        dep = _dep()
        with pytest.raises(CustomOrderViolatesDependencyError) as caught:
            check_order_satisfies_dependencies(["E", "Q"], [dep], {"Q", "E"})
        message = str(caught.value)
        assert dep.reason in message
        assert dep.source in message
        assert caught.value.dependency is dep
        assert caught.value.order == ("E", "Q")

    def test_an_inactive_dependency_does_not_reject_an_order(self) -> None:
        check_order_satisfies_dependencies(
            ["E", "Q"], [_dep(requires="Q2")], {"Q", "E"}
        )

    def test_a_dependency_whose_endpoint_is_unordered_is_unconstrained(self) -> None:
        check_order_satisfies_dependencies(["E"], [_dep()], {"Q", "E"})

    def test_no_declarations_never_rejects(self) -> None:
        check_order_satisfies_dependencies(["E", "Q", "W", "R"], [], {"Q", "E", "W"})
