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
from types import ModuleType

import pytest

from src.calculator.champions import (
    _CUSTOM_CHAMPION_MODULES,
    get_champion_cast_dependencies,
    get_champion_module_contract,
)
from src.calculator.champions.module_contract import (
    ChampionModuleContractError,
    contract_from_module,
)
from src.calculator.champions.packet_module import build_packet_module
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


def _champion_module(**attributes) -> ModuleType:
    """The smallest module ``contract_from_module`` accepts, plus overrides."""
    module = ModuleType(attributes.pop("__name__", "synthetic_champion"))
    module.parse_abilities = lambda *args, **kwargs: {}
    module.SLOTS = {
        slot: (lambda ctx: None) for slot in ("P", "Q", "Q2", "W", "E", "R")
    }
    module.OPTIONS = []
    module.ASSUMPTIONS = ["A synthetic module for the contract gate."]
    module.SOURCES = [{"label": "synthetic", "url": SOURCE}]
    module.MODULE_COVERAGE = {slot: "modeled" for slot in "PQWER"}
    module.REVIEW_STATUS = "reviewed_module"
    for name, value in attributes.items():
        setattr(module, name, value)
    return module


class TestTheContractCarriesDeclarations:
    """``module_contract`` validates at import and publishes the result."""

    def test_a_declaring_module_lands_its_declarations_on_the_contract(self) -> None:
        module = _champion_module(CAST_DEPENDENCIES=(_dep(),))
        contract = contract_from_module("Synthetic", "synthetic", module)
        assert contract.cast_dependencies == (_dep(),)

    def test_a_non_declaring_module_carries_an_empty_tuple(self) -> None:
        contract = contract_from_module("Synthetic", "synthetic", _champion_module())
        assert contract.cast_dependencies == ()

    def test_the_parser_carries_the_declaration_when_the_module_does_not(self) -> None:
        """The PACKET_SPEC three-place lookup, for packet-compiled carriers."""
        module = _champion_module()
        module.parse_abilities.cast_dependencies = (_dep(),)
        contract = contract_from_module("Synthetic", "synthetic", module)
        assert contract.cast_dependencies == (_dep(),)

    def test_a_declaration_outside_the_modules_own_slots_fails_at_import(self) -> None:
        module = _champion_module(CAST_DEPENDENCIES=(_dep(requires="Z"),))
        with pytest.raises(UnknownSlotError):
            contract_from_module("Synthetic", "synthetic", module)

    def test_a_declaration_that_is_not_a_cast_dependency_fails_at_import(self) -> None:
        module = _champion_module(CAST_DEPENDENCIES=({"slot": "E"},))
        with pytest.raises(ChampionModuleContractError, match="CAST_DEPENDENCIES"):
            contract_from_module("Synthetic", "synthetic", module)

    def test_a_cast_order_contradicting_a_declaration_fails_at_import(self) -> None:
        """Jayce's shape: an order and a dependency that cannot both hold (P5-d)."""
        module = _champion_module(
            CAST_DEPENDENCIES=(_dep(),), CAST_ORDER=["E", "Q", "W", "R"]
        )
        with pytest.raises(CustomOrderViolatesDependencyError):
            contract_from_module("Synthetic", "synthetic", module)

    def test_a_cast_order_satisfying_its_declarations_passes(self) -> None:
        module = _champion_module(
            CAST_DEPENDENCIES=(_dep(),), CAST_ORDER=["Q", "E", "W", "R"]
        )
        contract = contract_from_module("Synthetic", "synthetic", module)
        assert contract.cast_dependencies == (_dep(),)

    def test_a_non_declaring_modules_cast_order_reaches_no_new_check(self) -> None:
        """D-85: the 170 non-declaring champions must be byte-identical.

        Jayce's live ``CAST_ORDER`` names ``Q2``, a slot his ``SLOTS`` does
        not have, so a slot check that ran for every module would fail his
        import today.  The guard is what keeps the migration diff-free.
        """
        module = _champion_module(CAST_ORDER=["Q", "Q2_absent", "W"])
        module.SLOTS = {slot: (lambda ctx: None) for slot in ("P", "Q", "W", "E", "R")}
        contract = contract_from_module("Synthetic", "synthetic", module)
        assert contract.cast_dependencies == ()


class TestTheRegistryAccessor:
    def test_an_unknown_champion_declares_nothing(self) -> None:
        assert get_champion_cast_dependencies("Not A Champion") == ()

    def test_it_reads_the_validated_contract(self) -> None:
        for name in ("Aatrox", "Jinx"):
            assert (
                get_champion_cast_dependencies(name)
                is get_champion_module_contract(name).cast_dependencies
            )

    def test_every_registered_champion_answers_the_accessor(self) -> None:
        for name in _CUSTOM_CHAMPION_MODULES:
            assert isinstance(get_champion_cast_dependencies(name), tuple)


class TestThePacketCompilerCarriesDeclarations:
    """``build_packet_module`` gates its declarations on the compiled surface."""

    SHA = "8e7f7c3e75ab1a7eb65ec2d5deb23878aa47b44ee0044807d13f064afc55cafd"

    def _packet_dependency(self) -> CastDependency:
        _, slots, _, _, _ = build_packet_module("Jinx", self.SHA)
        assert {"Q", "W", "E", "R"} <= set(slots)
        return _dep(slot="E", requires="Q", kind="damage_enabler")

    def test_it_attaches_to_both_carriers(self) -> None:
        dependency = self._packet_dependency()
        parser, slots, _, _, _ = build_packet_module(
            "Jinx", self.SHA, cast_dependencies=(dependency,)
        )
        assert parser.cast_dependencies == (dependency,)
        assert slots.cast_dependencies == (dependency,)

    def test_declaring_nothing_leaves_both_carriers_empty(self) -> None:
        parser, slots, _, _, _ = build_packet_module("Jinx", self.SHA)
        assert parser.cast_dependencies == ()
        assert slots.cast_dependencies == ()

    def test_a_slot_the_packet_never_compiled_fails_closed(self) -> None:
        with pytest.raises(UnknownSlotError):
            build_packet_module(
                "Jinx", self.SHA, cast_dependencies=(_dep(requires="Q2"),)
            )

    def test_the_digest_gate_still_fires_first(self) -> None:
        with pytest.raises(RuntimeError, match="packet evidence drifted"):
            build_packet_module("Jinx", "0" * 64, cast_dependencies=(_dep(),))


def _parsed_syndra(splinters: int = 120) -> dict:
    """Syndra's live parse at L18, the surface her declarations run against."""
    from src.calculator.champions import parse_champion_abilities
    from src.calculator.data_fetcher import fetch_champion_data

    champion = {data.get("name"): data for data in fetch_champion_data().values()}[
        "Syndra"
    ]
    return parse_champion_abilities(
        champion,
        18,
        600.0,
        ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
        champion_options={"splinters": splinters},
    )


class TestSyndraDeclaresHerStun:
    """The conversion candidate: both declarations ship (D-83)."""

    def test_she_declares_exactly_the_two_documented_pairs(self) -> None:
        declared = get_champion_cast_dependencies("Syndra")
        assert [(dep.slot, dep.requires) for dep in declared] == [
            ("E", "Q"),
            ("E", "Q2"),
        ]
        assert {dep.kind for dep in declared} == {"cc_enabler"}

    def test_both_cite_the_revision_her_module_publishes(self) -> None:
        from src.calculator.champions import syndra

        receipt = syndra.SOURCES[0]
        expected = f"{receipt['url']}@{receipt['revision_id']}"
        for dep in get_champion_cast_dependencies("Syndra"):
            assert dep.source == expected

    def test_each_nests_exactly_one_reverse_cc_setup_suppression(self) -> None:
        for dep in get_champion_cast_dependencies("Syndra"):
            assert len(dep.suppresses) == 1
            suppression = dep.suppresses[0]
            assert (suppression.setup, suppression.consume) == (
                dep.slot,
                dep.requires,
            )
            assert suppression.kind == "cc_setup"

    def test_only_the_recast_suppression_is_latent(self) -> None:
        """D-84's deleted test exception, moved where the audit can see it."""
        by_pair = {
            dep.requires: dep.suppresses[0]
            for dep in get_champion_cast_dependencies("Syndra")
        }
        assert by_pair["Q"].latent_reason is None
        assert "cooldown" in (by_pair["Q2"].latent_reason or "")

    def test_the_latent_claim_is_true_of_this_tree(self) -> None:
        """The suppression it opposes exists for Q and does not for Q2.

        A latent_reason nobody checks is the prose-outruns-code shape this
        campaign exists to kill, so the claim is asserted against the
        detector rather than believed.
        """
        from src.calculator.rotation_resolver import detect_setup_consume_edges
        from src.calculator.data_fetcher import fetch_champion_data

        champion = {data.get("name"): data for data in fetch_champion_data().values()}[
            "Syndra"
        ]
        parsed = _parsed_syndra()
        edges = {
            (edge.setup, edge.consume, edge.kind)
            for edge in detect_setup_consume_edges("Syndra", parsed, champion, {})
        }
        assert ("E", "Q", "cc_setup") in edges
        assert ("E", "Q2", "cc_setup") not in edges

    def test_the_recast_declaration_is_inactive_below_forty_splinters(self) -> None:
        declared = get_champion_cast_dependencies("Syndra")
        assert "Q2" not in _parsed_syndra(splinters=39)
        assert [dep.requires for dep in active_dependencies(declared, {"Q", "E"})] == [
            "Q"
        ]

    def test_both_are_active_once_the_second_charge_exists(self) -> None:
        parsed = _parsed_syndra(splinters=40)
        assert "Q2" in parsed
        declared = get_champion_cast_dependencies("Syndra")
        assert len(active_dependencies(declared, set(parsed))) == 2

    def test_a_custom_order_putting_e_first_is_refused(self) -> None:
        """The refusal quotes her own mechanic, not the rule that caught it."""
        declared = get_champion_cast_dependencies("Syndra")
        with pytest.raises(CustomOrderViolatesDependencyError) as caught:
            check_order_satisfies_dependencies(
                ["E", "Q", "W", "R"], declared, {"Q", "E", "W", "R"}
            )
        assert "stun" in str(caught.value)
        assert "wiki.leagueoflegends.com" in str(caught.value)


class TestHeadOnlyDeclarations:
    """Zed and Brand declare their heads and keep their seeds (D-89)."""

    def test_zed_declares_the_shadow_placement_and_nothing_else(self) -> None:
        declared = get_champion_cast_dependencies("Zed")
        assert [(dep.slot, dep.requires) for dep in declared] == [
            ("Q", "W"),
            ("E", "W"),
        ]
        assert {dep.kind for dep in declared} == {"damage_enabler"}

    def test_zed_declares_nothing_about_death_mark(self) -> None:
        """The wiki casts R first, this module prices it last: no honest edge."""
        for dep in get_champion_cast_dependencies("Zed"):
            assert "R" not in (dep.slot, dep.requires)

    def test_brand_declares_one_edge_for_the_ablaze_opener(self) -> None:
        declared = get_champion_cast_dependencies("Brand")
        assert [(dep.slot, dep.requires) for dep in declared] == [("W", "Q")]
        assert declared[0].kind == "damage_enabler"

    def test_brand_names_the_row_its_own_module_prices(self) -> None:
        """The declaration and the slot map must be about one number.

        W's declaration exists because the module reads the Ablaze-only
        row; if that read ever changes to the base "Magic Damage", the
        dependency stops being true and this pairing is what says so.
        """
        module = (ROOT / "src" / "calculator" / "champions" / "brand.py").read_text(
            encoding="utf-8"
        )
        assert '"W": simple_damage(attr="Increased Damage"' in module
        assert "Increased Damage" in get_champion_cast_dependencies("Brand")[0].reason

    def test_neither_declares_a_suppression(self) -> None:
        """Their detectors infer nothing, so a suppression would be dead."""
        for name in ("Zed", "Brand"):
            for dep in get_champion_cast_dependencies(name):
                assert dep.suppresses == ()

    def test_both_cite_the_revision_their_module_publishes(self) -> None:
        from src.calculator.champions import brand, zed

        for module, name in ((zed, "Zed"), (brand, "Brand")):
            parent = next(
                row for row in module.SOURCES if "Template:" not in row["url"]
            )
            expected = f"{parent['url']}@{parent['revision_id']}"
            for dep in get_champion_cast_dependencies(name):
                assert dep.source == expected

    def test_exactly_three_champions_declare_anything(self) -> None:
        """The migration is provably diff-free because 170 modules do not."""
        declaring = {
            name
            for name in _CUSTOM_CHAMPION_MODULES
            if get_champion_cast_dependencies(name)
        }
        assert declaring == {"Syndra", "Zed", "Brand"}
