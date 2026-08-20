"""The declared cast-dependency vocabulary leaf.

Phase 5's leaf lands before anything consumes it, so these tests cover the
module on its own terms: that it stays a leaf, that its two vocabularies
are closed and disjoint, that every import-time failure has a negative
test which reaches it, and that the two order functions Phase 0B's C6
consumes behave. The precedence table and the resolver merge belong to
``rotation_resolver`` and are tested with it.
"""

import ast
import itertools
import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import ModuleType

import pytest

from src import app as app_module
from src.calculator.champions import (
    _CHAMPION_MODULES,
    get_champion_cast_dependencies,
    get_champion_module_contract,
    get_champion_option_rotation,
)
from src.calculator.data_fetcher import get_champion
from src.calculator.pipeline import FightParams, run_fight
from src.calculator.champions import module_contract
from src.calculator.champions.module_contract import (
    ChampionModuleContractError,
    contract_from_module,
)
from src.calculator.champions.packet_module import PacketSlotMap, build_packet_module
from src.calculator.rotation_resolver import _DIRECT_EDGE_KIND
from src.calculator.cast_dependency import (
    BASE_CAST_SLOTS,
    DEPENDENCY_KINDS,
    INFERRED_EDGE_KINDS,
    CastDependency,
    CastDependencyError,
    ConflictingInferenceError,
    CustomOrderViolatesDependencyError,
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
RESOLVER = ROOT / "src" / "calculator" / "rotation_resolver.py"
CONTRACT = ROOT / "src" / "calculator" / "champions" / "module_contract.py"
PACKET = ROOT / "src" / "calculator" / "champions" / "packet_module.py"
PIPELINE = ROOT / "src" / "calculator" / "pipeline.py"

_VALIDATORS = ("validate_cast_dependencies", "validate_cast_order_declaration")

SOURCE = "https://wiki.leagueoflegends.com/en-us/Syndra@4024662"
SURFACE = {"P", "Q", "Q2", "W", "E", "R"}


def _function(path: Path, name: str) -> ast.FunctionDef:
    """The named top-level function of *path*, as an AST node."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{path.name} declares no {name}")


def _detector_edge_kinds() -> tuple[set[str], int]:
    """Every edge kind ``detect_setup_consume_edges`` can emit, from source.

    ``add(setup, consume, kind, cite)`` is the detector's one edge
    constructor, so its third positional argument is the whole emittable
    vocabulary.  Returns the literal kinds and the number of call sites
    whose kind is computed rather than written down.
    """
    detector = _function(RESOLVER, "detect_setup_consume_edges")
    kinds: set[str] = set()
    dynamic = 0
    for node in ast.walk(detector):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != "add":
            continue
        assert len(node.args) == 4, f"unexpected add() arity at line {node.lineno}"
        kind = node.args[2]
        if isinstance(kind, ast.Constant):
            kinds.add(str(kind.value))
        else:
            dynamic += 1
    return kinds, dynamic


def _emptiness_guard_line(function: ast.FunctionDef, name: str) -> int:
    """The line of the ``if not <name>: return`` guard that opens *function*.

    D-85's shape: nothing below the guard runs for a champion that
    declares nothing.
    """
    for node in function.body:
        if (
            isinstance(node, ast.If)
            and isinstance(node.test, ast.UnaryOp)
            and isinstance(node.test.op, ast.Not)
            and isinstance(node.test.operand, ast.Name)
            and node.test.operand.id == name
            and len(node.body) == 1
            and isinstance(node.body[0], ast.Return)
        ):
            return node.lineno
    raise AssertionError(f"{function.name} has no `if not {name}: return` guard")


def _validator_calls(node: ast.AST) -> list[ast.Call]:
    """Every call to a cast-dependency validator inside *node*."""
    return [
        child
        for child in ast.walk(node)
        if isinstance(child, ast.Call)
        and isinstance(child.func, ast.Name)
        and child.func.id in _VALIDATORS
    ]


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

    def test_it_equals_what_the_detector_can_emit(self) -> None:
        """Set equality against the source, not membership over a roster.

        The vocabulary was moved verbatim from ``detect_setup_consume_edges``
        and nothing re-derives it, so a kind that stops being emitted — or
        one emitted under a name the leaf never heard of — is invisible to
        a roster walk: an edge that no champion produces asserts nothing.
        This reads the third positional argument of every ``add(...)`` call
        in the detector out of the AST and asserts the two sets are equal.
        """
        emitted, dynamic = _detector_edge_kinds()
        assert emitted == set(INFERRED_EDGE_KINDS)
        assert dynamic == 1, (
            "a second dynamically-computed edge kind entered the detector; "
            "its value population needs the assertion below"
        )

    def test_the_one_dynamic_kind_stays_inside_the_vocabulary(self) -> None:
        """The detector's single non-constant kind is a verbatim pass-through.

        A module OPTIONS rotation declaration carrying ``setup_slot`` hands
        its own ``kind`` straight to ``add(...)``, so the emittable set is
        not statically closed — the roster is what closes it.  Every
        declaration across the registry, plus the fallback table the
        pass-through falls back to, must name a kind the leaf knows.
        """
        assert set(_DIRECT_EDGE_KIND.values()) <= INFERRED_EDGE_KINDS
        assert "mark_consume" in INFERRED_EDGE_KINDS
        outside = {}
        for name in _CHAMPION_MODULES:
            for key, decl in get_champion_option_rotation(name).items():
                if not decl or not decl.get("setup_slot"):
                    continue
                kind = decl.get("kind")
                if kind is not None and kind not in INFERRED_EDGE_KINDS:
                    outside[f"{name}.{key}"] = kind
        assert outside == {}

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


class TestRecastParentageHasOneAuthority:
    """The resolver reads ``recast_of``; no table restates it (D-11).

    The retired ``_PARENT_SLOT`` map answered "whose rows describe this
    slot?" from the slot's *name*, which linked three synthetic slots
    that are not recasts at all to a parent the wiki never gave them.
    """

    def test_the_hand_parent_table_is_gone_from_the_resolver(self) -> None:
        source = RESOLVER.read_text(encoding="utf-8")
        assert "_PARENT_SLOT" not in source

    def test_no_name_based_recast_edge_survives(self) -> None:
        """The Q→Q2 fallback masked every unstamped recast slot."""
        source = RESOLVER.read_text(encoding="utf-8")
        assert 'add("Q", "Q2"' not in source
        assert "add('Q', 'Q2'" not in source

    def test_a_recast_slot_reads_its_parents_wiki_rows(self) -> None:
        """Syndra's Q2 has no row of its own and keeps Q's AoE cap."""
        from src.calculator.data_fetcher import fetch_champion_data
        from src.calculator.rotation_resolver import detect_aoe_cap

        champion = {data.get("name"): data for data in fetch_champion_data().values()}[
            "Syndra"
        ]
        assert detect_aoe_cap(champion, "Q") == 5
        assert detect_aoe_cap(champion, "Q2", recast_of="Q") == 5

    def test_an_unstamped_synthetic_slot_borrows_nothing(self) -> None:
        """Riven's R_buff is a module row, not a recast: it caps at one.

        The hand table published a five-champion AoE cap for a
        zero-damage buff slot no wiki row describes; with the table gone
        the receipt says one, which is what the data supports.
        """
        from src.calculator.data_fetcher import fetch_champion_data
        from src.calculator.rotation_resolver import detect_aoe_cap

        champions = {data.get("name"): data for data in fetch_champion_data().values()}
        assert detect_aoe_cap(champions["Riven"], "R_buff") == 1
        assert detect_aoe_cap(champions["Briar"], "W_frenzy") == 1


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


class TestNonDeclaringChampionsReachNoNewCode:
    """D-85 asserted at source level, in the ``test_issue_158`` idiom.

    "The 170 non-declaring champions are byte-identical" is what makes
    the migration provably diff-free, and a behavioural test can only
    show it for the modules that exist today.  These read the source and
    assert the *shape*: every raise and every validator call on the
    cast-dependency path is unreachable when no carrier declares
    anything, so a future edit that hoists one above its guard fails
    here rather than at some champion's import.
    """

    def test_the_contract_gates_every_failure_behind_its_guard(self) -> None:
        for function_name, guarded in (
            ("_declared_cast_dependencies", "declared"),
            ("_cast_dependencies", "dependencies"),
        ):
            function = _function(CONTRACT, function_name)
            guard = _emptiness_guard_line(function, guarded)
            gated = [
                node.lineno
                for node in ast.walk(function)
                if isinstance(node, ast.Raise)
            ]
            gated += [call.lineno for call in _validator_calls(function)]
            assert gated, f"{function_name} has no raise or validator call to gate"
            assert min(gated) > guard, (
                f"{function_name} can raise before its emptiness guard at "
                f"line {guard}"
            )

    def test_the_merge_gates_every_failure_behind_its_guard(self) -> None:
        """A non-declaring champion reaches the merge and returns from it.

        ``merge_declared_edges`` is the one place an inferred edge meets a
        declaration, so both resolve-time failures live in it; the
        emptiness guard is the first statement, and nothing above it can
        raise.
        """
        function = _function(RESOLVER, "merge_declared_edges")
        guard = _emptiness_guard_line(function, "declarations")
        raises = [
            node.lineno for node in ast.walk(function) if isinstance(node, ast.Raise)
        ]
        assert len(raises) == 2, "the merge's two resolve-time failures"
        assert min(raises) > guard

    def test_the_derivation_gates_its_cycle_failure_on_a_declaration(self) -> None:
        """A cycle raises for a declarer and falls back for everyone else.

        The fallback is the pre-campaign behaviour and the 170 keep it;
        the raise is reachable only from inside a branch that tested the
        declarations, which this reads out of the AST rather than trusting.
        """
        function = _function(RESOLVER, "derive_champion_rule")
        raises = [node for node in ast.walk(function) if isinstance(node, ast.Raise)]
        assert len(raises) == 1, "the derivation has exactly one failure"
        guarded = [
            node
            for node in ast.walk(function)
            if isinstance(node, ast.If)
            and any(
                isinstance(name, ast.Name) and name.id == "declarations"
                for name in ast.walk(node.test)
            )
            and any(raises[0] in ast.walk(statement) for statement in node.body)
        ]
        assert guarded, "the cycle raise is not gated on a declaration (D-85)"

    def test_the_packet_compiler_gates_its_validation_behind_a_declaration(
        self,
    ) -> None:
        function = _function(PACKET, "build_packet_module")
        calls = _validator_calls(function)
        assert len(calls) == 1
        guards = [
            node
            for node in ast.walk(function)
            if isinstance(node, ast.If)
            and isinstance(node.test, ast.Name)
            and node.test.id == "cast_dependencies"
        ]
        assert len(guards) == 1
        inside = {
            id(call)
            for statement in guards[0].body
            for call in _validator_calls(statement)
        }
        assert id(calls[0]) in inside

    def test_the_guards_are_written_where_a_reader_finds_them(self) -> None:
        contract_source = CONTRACT.read_text(encoding="utf-8")
        assert "if not declared:\n        return ()" in contract_source
        assert "if not dependencies:\n        return ()" in contract_source
        packet_source = PACKET.read_text(encoding="utf-8")
        assert (
            "if cast_dependencies:\n        validate_cast_dependencies("
            in packet_source
        )

    def test_only_declaring_modules_reach_a_validator(self, monkeypatch) -> None:
        """The behavioural half, over the whole live registry.

        The registry is resolved *before* the spies go in — building a
        contract lazily would itself reach the validator and count twice.
        """
        registry = [
            (name, get_champion_module_contract(name)) for name in _CHAMPION_MODULES
        ]
        seen: list[tuple[str, str]] = []

        def spy(name):
            original = getattr(module_contract, name)

            def record(*args, **kwargs):
                seen.append((name, kwargs["module"]))
                return original(*args, **kwargs)

            return record

        for validator in _VALIDATORS:
            monkeypatch.setattr(module_contract, validator, spy(validator))

        for champion, contract in registry:
            contract_from_module(champion, contract.module_name, contract.module)

        assert len(registry) == 173
        declaring = {module for _, module in seen}
        assert declaring == {
            "src.calculator.champions.brand",
            "src.calculator.champions.syndra",
            "src.calculator.champions.zed",
        }
        assert [name for name, _ in seen] == ["validate_cast_dependencies"] * 3


class _SlotMap(dict):
    """A slot map that carries a declaration, as ``PacketSlotMap`` does."""

    def __init__(self, slots, cast_dependencies):
        super().__init__(slots)
        self.cast_dependencies = cast_dependencies


class TestAnEmptyCarrierShadowsNothing:
    """A present-but-empty carrier may not discard a declaration.

    ``getattr(a, x, getattr(b, y, ()))`` evaluates its default *eagerly*,
    so a chain of them lets ``CAST_DEPENDENCIES = ()`` on the module win
    over a non-empty parser declaration and throw it away with no error.
    A packet champion would lose its declared ordering rules silently —
    the exact failure class this campaign exists to kill.
    """

    def test_an_empty_module_attribute_keeps_the_parsers_declaration(self) -> None:
        module = _champion_module(CAST_DEPENDENCIES=())
        module.parse_abilities.cast_dependencies = (_dep(),)
        contract = contract_from_module("Synthetic", "synthetic", module)
        assert contract.cast_dependencies == (_dep(),)

    def test_a_none_module_attribute_keeps_the_parsers_declaration(self) -> None:
        module = _champion_module(CAST_DEPENDENCIES=None)
        module.parse_abilities.cast_dependencies = (_dep(),)
        contract = contract_from_module("Synthetic", "synthetic", module)
        assert contract.cast_dependencies == (_dep(),)

    def test_an_empty_parser_attribute_keeps_the_slot_maps_declaration(self) -> None:
        module = _champion_module()
        module.SLOTS = _SlotMap(module.SLOTS, (_dep(),))
        module.parse_abilities.cast_dependencies = ()
        contract = contract_from_module("Synthetic", "synthetic", module)
        assert contract.cast_dependencies == (_dep(),)

    def test_every_carrier_empty_is_still_no_declaration(self) -> None:
        module = _champion_module(CAST_DEPENDENCIES=())
        module.SLOTS = _SlotMap(module.SLOTS, ())
        module.parse_abilities.cast_dependencies = ()
        contract = contract_from_module("Synthetic", "synthetic", module)
        assert contract.cast_dependencies == ()

    def test_carriers_that_agree_are_one_declaration(self) -> None:
        module = _champion_module(CAST_DEPENDENCIES=(_dep(),))
        module.parse_abilities.cast_dependencies = (_dep(),)
        contract = contract_from_module("Synthetic", "synthetic", module)
        assert contract.cast_dependencies == (_dep(),)

    def test_carriers_that_disagree_stop_the_import(self) -> None:
        """No carrier quietly wins a real disagreement."""
        module = _champion_module(CAST_DEPENDENCIES=(_dep(),))
        module.parse_abilities.cast_dependencies = (_dep(requires="W"),)
        with pytest.raises(ChampionModuleContractError, match="disagree"):
            contract_from_module("Synthetic", "synthetic", module)

    def test_the_disagreement_names_both_carriers(self) -> None:
        module = _champion_module(CAST_DEPENDENCIES=(_dep(),))
        module.SLOTS = _SlotMap(module.SLOTS, (_dep(requires="W"),))
        with pytest.raises(ChampionModuleContractError) as caught:
            contract_from_module("Synthetic", "synthetic", module)
        assert "module CAST_DEPENDENCIES" in str(caught.value)
        assert "SLOTS.cast_dependencies" in str(caught.value)

    def test_a_malformed_carrier_is_named_in_the_failure(self) -> None:
        module = _champion_module()
        module.parse_abilities.cast_dependencies = ({"slot": "E"},)
        with pytest.raises(
            ChampionModuleContractError, match=r"parse_abilities\.cast_dependencies"
        ):
            contract_from_module("Synthetic", "synthetic", module)

    def test_no_registered_champion_carries_a_shadowing_carrier(self) -> None:
        """The population this correction was measured against (R-20)."""
        shadowed = []
        for name in _CHAMPION_MODULES:
            contract = get_champion_module_contract(name)
            carriers = (
                (contract.module, "CAST_DEPENDENCIES"),
                (contract.parse_abilities, "cast_dependencies"),
                (contract.slots, "cast_dependencies"),
            )
            present = [
                bool(getattr(carrier, attribute))
                for carrier, attribute in carriers
                if hasattr(carrier, attribute)
            ]
            if any(present) and not all(present):
                shadowed.append(name)
        assert shadowed == []


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
        for name in _CHAMPION_MODULES:
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

    def test_the_slot_maps_positional_signature_did_not_move(self) -> None:
        """The carrier is keyword-only: the positional pair is unchanged."""
        assert PacketSlotMap({}, "0" * 64).cast_dependencies == ()
        with pytest.raises(TypeError):
            PacketSlotMap({}, "0" * 64, (_dep(),))

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
        slots_block = module.split("SLOTS = {", 1)[1].split("\n}", 1)[0]
        w_declaration = slots_block.split('"W":', 1)[1].split('"E":', 1)[0]
        assert 'attr="Increased Damage"' in w_declaration
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
            name for name in _CHAMPION_MODULES if get_champion_cast_dependencies(name)
        }
        assert declaring == {"Syndra", "Zed", "Brand"}


def _fight_params(**overrides):
    """A one-rotation ``FightParams``, field-overridable."""
    config = {
        "target_health": 1000.0,
        "target_bonus_health": 0.0,
        "target_armor": 0.0,
        "target_magic_resistance": 0.0,
        "fight_duration_seconds": 5.0,
        "auto_attack_uptime": 0.0,
        "one_rotation": True,
        "include_actives": True,
        "cast_order": None,
        "auto_attacks_only": False,
        "ability_ranks": None,
        "champion_options": None,
        "deterministic": True,
    }
    config.update(overrides)
    return FightParams(**config)


def _refused(champion: str, order: list[str]) -> CustomOrderViolatesDependencyError:
    """The refusal ``run_fight`` raises for *order*, or an assertion failure."""
    with pytest.raises(CustomOrderViolatesDependencyError) as caught:
        run_fight(get_champion(champion), 18, [], _fight_params(cast_order=order))
    return caught.value


def _is_refused(champion_data: dict, order: list[str]) -> bool:
    """Whether this parsed champion refuses *order* — the fight is discarded."""
    try:
        run_fight(champion_data, 18, [], _fight_params(cast_order=order))
    except CustomOrderViolatesDependencyError:
        return True
    return False


def _pipeline_check_calls(run: ast.FunctionDef) -> list[ast.Call]:
    """Every ``check_order_satisfies_dependencies`` call inside ``run_fight``.

    Takes the function node rather than re-parsing, so a caller may compare
    the calls it finds against other nodes of the same tree by identity.
    """
    return [
        node
        for node in ast.walk(run)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "check_order_satisfies_dependencies"
    ]


class TestTheRequestBoundaryRefusesAnImpossibleOrder:
    """D-86 — a custom order inverting an active declaration is rejected.

    A declared dependency states impossibility, not preference. Casting
    Syndra's E before her Q has the engine author a ``cc_kind="stun"``
    that cannot exist, and Imperial Mandate's Command then amplifies off a
    stun that never happened — the incident this campaign is named after,
    reached through a public request parameter. So the refusal quotes the
    declaration's own ``reason`` and ``source``: the caller is told which
    mechanic forbids the order, not which rule caught it.

    The question is asked at the one call site that has a parse, because
    which slots are live — Syndra's second charge exists only at 40
    splinters — is a property of the parse and of nothing else.
    """

    def test_e_before_q_is_refused(self) -> None:
        declared = get_champion_cast_dependencies("Syndra")
        assert _refused("Syndra", ["E", "Q", "W", "R"]).dependency in declared

    def test_the_refusal_quotes_the_mechanic_and_its_revision(self) -> None:
        """The 4xx text is the declaration's, not the checker's."""
        refusal = _refused("Syndra", ["E", "Q", "W", "R"])
        assert refusal.dependency.reason in str(refusal)
        assert refusal.dependency.source in str(refusal)
        assert "wiki.leagueoflegends.com" in str(refusal)

    def test_the_order_it_names_is_the_order_that_would_have_run(self) -> None:
        """Expanded, not requested: the recast is part of the schedule.

        ``expand_user_order`` folds Syndra's live second charge in after
        its parent, so the order the engine would cast holds a slot the
        request never named. Checking the requested order instead would
        let a declaration whose ``requires`` is a recast slot be inverted
        by an expansion nobody checked.
        """
        assert _refused("Syndra", ["E", "Q", "W", "R"]).order == (
            "E",
            "Q",
            "Q2",
            "W",
            "R",
        )

    def test_below_forty_splinters_only_the_live_declaration_speaks(self) -> None:
        """The parse decides which declarations are active (the dynamic tier).

        Syndra's second charge exists only at 40 splinters, so at 39 the
        ``E requires Q2`` declaration constrains nothing and there is no
        recast to fold in: the same request is refused for one reason
        instead of two, over an order that is exactly what was asked.
        """
        with pytest.raises(CustomOrderViolatesDependencyError) as caught:
            run_fight(
                get_champion("Syndra"),
                18,
                [],
                _fight_params(
                    cast_order=["E", "Q", "W", "R"],
                    champion_options={"splinters": 39},
                ),
            )
        assert caught.value.dependency.requires == "Q"
        assert caught.value.order == ("E", "Q", "W", "R")

    def test_the_api_refuses_with_a_400_carrying_the_declaration(self) -> None:
        """D-86's body clause: the reason and source reach the response."""
        app_module.app.config["TESTING"] = True
        response = app_module.app.test_client().post(
            "/api/calculate",
            json={
                "champion": "Syndra",
                "level": 18,
                "items": [],
                "cast_order": ["E", "Q", "W", "R"],
            },
        )
        assert response.status_code == 400
        error = response.get_json()["error"]
        declared = get_champion_cast_dependencies("Syndra")[0]
        assert declared.reason in error
        assert declared.source in error

    def test_a_satisfying_order_still_runs_whole(self) -> None:
        """C6's recast, re-asserted: the check refuses, it does not filter."""
        result = run_fight(
            get_champion("Syndra"),
            18,
            [],
            _fight_params(cast_order=["Q", "W", "E", "R"]),
        )
        assert result["breakdown"]["Q2"]["casts"] == 1
        assert result["rotation"]["order"][:5] == ["Q", "Q2", "W", "E", "R"]

    def test_a_partial_order_naming_one_endpoint_is_unconstrained(self) -> None:
        """E alone declares nothing about a Q the request never asked for."""
        result = run_fight(
            get_champion("Syndra"), 18, [], _fight_params(cast_order=["E", "W"])
        )
        assert set(result["breakdown"]) >= {"E", "W"}
        assert "Q" not in result["breakdown"]

    def test_a_non_declaring_champion_may_still_be_told_anything(self) -> None:
        """D-85 at the request boundary: 170 modules reach no new failure."""
        assert not get_champion_cast_dependencies("Ahri")
        result = run_fight(
            get_champion("Ahri"), 18, [], _fight_params(cast_order=["E", "Q", "W", "R"])
        )
        assert result["rotation"]["order"] == ["E", "Q", "W", "R"]

    def test_the_derived_path_is_never_asked(self) -> None:
        """A resolved order already merged the declarations that made it.

        ``resolve_cast_order`` folds the declarations over its inferred
        edges before it orders anything (D-82/D-85), so re-checking its
        output would assert the resolver against itself. The check lives in
        the branch a *caller* supplied an order to, and this is that shape
        read off the tree rather than off the request.
        """
        run = _function(PIPELINE, "run_fight")
        branch = next(
            node
            for node in ast.walk(run)
            if isinstance(node, ast.If)
            and isinstance(node.test, ast.Compare)
            and ast.unparse(node.test) == "params.cast_order is None"
        )
        calls = _pipeline_check_calls(run)
        assert len(calls) == 1
        assert calls[0] in [
            child for statement in branch.orelse for child in ast.walk(statement)
        ]

    def test_the_checked_order_is_the_order_the_engine_is_handed(self) -> None:
        """One name, expanded once, checked and then cast — not two lists."""
        run = _function(PIPELINE, "run_fight")
        checked = _pipeline_check_calls(run)[0].args[0]
        assert isinstance(checked, ast.Name)
        expansions = [
            node
            for node in ast.walk(run)
            if isinstance(node, ast.Assign)
            and [target.id for target in node.targets if isinstance(target, ast.Name)]
            == [checked.id]
        ]
        assert len(expansions) == 1
        assert ast.unparse(expansions[0].value).startswith("expand_user_order(")
        handed = [
            node
            for node in ast.walk(run)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_params_with_cast_order"
        ]
        assert checked.id in {
            argument.id
            for call in handed
            for argument in call.args
            if isinstance(argument, ast.Name)
        }

    def test_the_declarations_come_from_the_validated_contract(self) -> None:
        """Never a module attribute: an unvalidated declaration is not one."""
        call = _pipeline_check_calls(_function(PIPELINE, "run_fight"))[0]
        assert ast.unparse(call.args[1]).startswith("get_champion_cast_dependencies(")

    def test_the_newly_refused_population_is_measured_not_assumed(self) -> None:
        """How much of the request space this closes, per champion.

        A new 4xx on a public parameter deserves a number rather than an
        adjective. Every permutation of the four base slots is sent through
        ``run_fight`` for each declaring champion and for one that declares
        nothing: Syndra refuses the twelve that place E before Q, Zed the
        sixteen that do not open on the Shadow (W before both Q and E leaves
        eight), Brand the twelve that place W before Q, and Ahri — like the
        other 169 non-declaring modules — refuses none of the twenty-four.
        """
        refused = {}
        for champion in ("Syndra", "Zed", "Brand", "Ahri"):
            data = get_champion(champion)
            refused[champion] = sum(
                1
                for order in itertools.permutations(("Q", "W", "E", "R"))
                if _is_refused(data, list(order))
            )
        assert refused == {"Syndra": 12, "Zed": 16, "Brand": 12, "Ahri": 0}
