"""Unit tests for the typed champion→engine damage contract.

Exercises damage._evaluate_cast_parts directly with a stub FightState:
the evaluator owns HP-threading, per-part mitigation, and reduced-
effectiveness crit — champion files own only the closures.  Also pins the
four closed vocabularies the leaf declares, member for member.
"""

import ast
import importlib.util
import sys
from enum import Enum
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.calculator import ability_spec, trigger_stream
from src.calculator.ability_spec import (
    AttackClass,
    Authority,
    DamageClass,
    DamagePart,
    Disposition,
    part_damage_types,
)
from src.calculator.damage import _evaluate_cast_parts
from src.calculator.resistance import apply_resistance


def _stub_state(
    *,
    target_health: float = 1000.0,
    effective_armor: float = 50.0,
    magic_amp: float = 1.0,
    crit_chance: float = 0.0,
    crit_multiplier: float = 2.0,
) -> SimpleNamespace:
    return SimpleNamespace(
        target_health=target_health,
        magic_amp=magic_amp,
        crit_chance=crit_chance,
        crit_multiplier=crit_multiplier,
        resists=SimpleNamespace(effective_armor=effective_armor),
    )


def _module_tree() -> ast.Module:
    return ast.parse(Path(ability_spec.__file__).read_text(encoding="utf-8"))


class TestClosedVocabularies:
    """The four vocabularies every later phase spells by symbol, not by string."""

    def test_damage_class_is_the_three_mitigation_types(self) -> None:
        assert [member.name for member in DamageClass] == [
            "MAGIC",
            "PHYSICAL",
            "TRUE",
        ]
        assert [member.value for member in DamageClass] == [
            "magic",
            "physical",
            "true",
        ]

    def test_attack_class_is_the_three_delivery_types(self) -> None:
        assert [member.name for member in AttackClass] == [
            "BASIC_ATTACK",
            "ABILITY",
            "OTHER",
        ]

    def test_disposition_is_the_campaign_invariant(self) -> None:
        assert [member.name for member in Disposition] == [
            "MEASURED",
            "STRUCTURAL_ZERO",
            "WITHHELD",
            "STARVED",
        ]

    def test_authority_names_all_five_engines_of_ownership(self) -> None:
        assert [member.name for member in Authority] == [
            "PAIR_ONLY",
            "SPLIT",
            "COUPLED_AUTHORITATIVE",
            "COUPLED_AUTHORITATIVE_WITH_PAIR_PREVIEW",
            "COUPLED_ONLY",
        ]

    @pytest.mark.parametrize("vocabulary", [Disposition, Authority])
    def test_receipt_spellings_equal_their_symbols(
        self, vocabulary: type[Enum]
    ) -> None:
        # These members are serialized as receipt strings and reason
        # prefixes, so symbol and spelling must be one string.
        for member in vocabulary:
            assert member.value == member.name

    @pytest.mark.parametrize(
        "vocabulary", [DamageClass, AttackClass, Disposition, Authority]
    )
    def test_vocabulary_is_closed(self, vocabulary: type[Enum]) -> None:
        with pytest.raises(ValueError):
            vocabulary("not_a_declared_member")

    def test_part_damage_types_is_the_damage_class_projection(self) -> None:
        assert part_damage_types() == frozenset(member.value for member in DamageClass)

    def test_every_damage_class_builds_a_part(self) -> None:
        for member in DamageClass:
            assert DamagePart(member.value, 10.0).damage_type == member.value

    def test_the_damage_type_strings_have_exactly_one_home(self) -> None:
        """No literal spelling of the three types survives outside the enum."""
        tree = _module_tree()
        declaration = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef) and node.name == "DamageClass"
        )
        declared = {id(node) for node in ast.walk(declaration)}
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and node.value in {"magic", "physical", "true"}
                and id(node) not in declared
            ):
                raise AssertionError(
                    f"{node.value!r} is spelled at ability_spec.py:{node.lineno} "
                    "outside DamageClass; the vocabulary has one home"
                )

    def test_the_vocabulary_leaf_imports_no_sibling_module(self) -> None:
        """Authority lives here because every layer can import this module.

        The property is that importing this module loads no sibling, so no
        layer can be caught in a cycle by depending on the vocabulary.  Every
        module-scope import is therefore checked, and the *one* deferred
        import the leaf is allowed is pinned by name below rather than
        admitted as a category.
        """
        tree = _module_tree()
        deferred = {
            id(node)
            for function in ast.walk(tree)
            if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
            for node in ast.walk(function)
            if isinstance(node, (ast.Import, ast.ImportFrom))
        }
        for node in ast.walk(tree):
            if id(node) in deferred:
                continue
            if isinstance(node, ast.ImportFrom):
                assert node.level == 0 and not str(node.module).startswith(
                    "src.calculator"
                ), f"ability_spec.py:{node.lineno} imports a sibling module"
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("src.calculator")

    def test_the_leaf_defers_exactly_one_sibling_import_and_it_is_named(self) -> None:
        """``Starved.read`` raises ``ProjectionStarvation``, whose home is not here.

        D-72 puts the ``Quantity`` algebra in this leaf and D-25 keeps
        ``ProjectionStarvation`` in ``trigger_stream`` — which imports this
        module.  A module-scope import would be a cycle, so the raise fetches
        the class at raise time, the repo's own idiom for the same collision
        (``champions/engine.py`` defers ``slotlib``).  One exception, pinned by
        name and by the function it sits in, so the allowance cannot widen
        into a category.
        """
        tree = _module_tree()
        deferred = [
            (function.name, node)
            for function in ast.walk(tree)
            if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
            for node in ast.walk(function)
            if isinstance(node, (ast.Import, ast.ImportFrom))
        ]
        assert len(deferred) == 1
        owner, node = deferred[0]
        assert owner == "_projection_starvation"
        assert isinstance(node, ast.ImportFrom)
        assert (node.level, node.module) == (1, "trigger_stream")
        assert [alias.name for alias in node.names] == ["ProjectionStarvation"]

    def test_the_leaf_loads_with_no_package_around_it(self) -> None:
        """The property the AST rules stand for, checked by execution.

        The file is executed on its own, with no package to resolve a
        relative import against.  It loads and its vocabulary works, which is
        what "dependency-free leaf" means and what an AST rule can only
        approximate — the deferred import is deferred in fact, not merely in
        indentation.
        """
        spec = importlib.util.spec_from_file_location(
            "ability_spec_standalone", ability_spec.__file__
        )
        assert spec is not None and spec.loader is not None
        standalone = importlib.util.module_from_spec(spec)
        # ``dataclasses`` resolves a field's annotations through
        # ``sys.modules[cls.__module__]``, so the module has to be registered
        # for the duration of its own execution; nothing else about the
        # package is present, which is the point of the probe.
        sys.modules[spec.name] = standalone
        try:
            spec.loader.exec_module(standalone)
        finally:
            del sys.modules[spec.name]
        assert standalone.Measured(amount=2.0).read() == 2.0
        assert [member.name for member in standalone.Disposition] == [
            member.name for member in Disposition
        ]


class TestDamagePartValidation:
    def test_unknown_damage_type_raises(self) -> None:
        # A typo must never silently mitigate as magic.
        with pytest.raises(ValueError, match="phyiscal"):
            DamagePart("phyiscal", 100.0)

    def test_mixed_is_not_a_part_type(self) -> None:
        # "mixed" is an entry label; a mixed ability is two typed parts.
        with pytest.raises(ValueError, match="mixed"):
            DamagePart("mixed", 100.0)

    @pytest.mark.parametrize("field", ["time_offset", "hit_interval"])
    def test_negative_timing_raises(self, field: str) -> None:
        with pytest.raises(ValueError, match=field):
            DamagePart("magic", 100.0, **{field: -0.1})


class TestEvaluateCastParts:
    def test_single_magic_part_mitigated_and_amped(self) -> None:
        state = _stub_state(magic_amp=1.1)
        total, first, _, _ = _evaluate_cast_parts(
            state, (DamagePart("magic", 200.0),), 1, 40.0, 0.0
        )
        expected = apply_resistance(200.0, 40.0) * 1.1
        assert total == pytest.approx(expected)
        assert first == pytest.approx(expected)

    def test_true_part_ignores_resists_and_amp(self) -> None:
        state = _stub_state(magic_amp=1.5)
        total, _, _, _ = _evaluate_cast_parts(
            state, (DamagePart("true", 100.0),), 1, 40.0, 0.0
        )
        assert total == 100.0

    def test_physical_part_uses_armor_without_magic_amp(self) -> None:
        state = _stub_state(effective_armor=100.0, magic_amp=2.0)
        total, _, _, _ = _evaluate_cast_parts(
            state, (DamagePart("physical", 100.0),), 1, 0.0, 0.0
        )
        assert total == pytest.approx(apply_resistance(100.0, 100.0))

    def test_count_multiplies_one_part(self) -> None:
        state = _stub_state()
        single, _, _, _ = _evaluate_cast_parts(
            state, (DamagePart("magic", 90.0),), 1, 0.0, 0.0
        )
        tripled, _, _, _ = _evaluate_cast_parts(
            state, (DamagePart("magic", 90.0, count=3),), 1, 0.0, 0.0
        )
        assert tripled == pytest.approx(single * 3)

    def test_authored_part_timing_emits_absolute_hit_events(self) -> None:
        state = _stub_state()
        _, _, _, events = _evaluate_cast_parts(
            state,
            (
                DamagePart("magic", 50.0, time_offset=0.25),
                DamagePart(
                    "magic",
                    20.0,
                    count=3,
                    time_offset=0.75,
                    hit_interval=0.5,
                ),
            ),
            1,
            0.0,
            0.0,
            cast_times=(2.0,),
        )

        assert [event["time"] for event in events] == [2.25, 2.75, 3.25, 3.75]
        assert [event["damage"] for event in events] == [50.0, 20.0, 20.0, 20.0]

    def test_second_part_sees_first_parts_damage(self) -> None:
        # Akali R shape: R2 interpolates on missing HP *after* R1 lands.
        state = _stub_state(target_health=1000.0)
        r1 = 300.0  # 0 resist in this test: mitigated == raw
        span = 400.0
        seen_ratios: list[float] = []

        def r2(missing_ratio: float) -> float:
            seen_ratios.append(missing_ratio)
            return 100.0 + span * missing_ratio

        total, _, _, _ = _evaluate_cast_parts(
            state,
            (DamagePart("magic", r1), DamagePart("magic", hp_scaled_damage=r2)),
            1,
            0.0,
            0.0,
        )
        assert seen_ratios == [pytest.approx(0.3)]  # 300 of 1000 missing
        assert total == pytest.approx(r1 + 100.0 + span * 0.3)

    def test_multi_cast_reevaluates_hp_per_cast(self) -> None:
        # Kog'Maw R shape: each cast reads HP left by the previous cast.
        state = _stub_state(target_health=1000.0)
        seen: list[float] = []

        def scaled(missing_ratio: float) -> float:
            seen.append(round(missing_ratio, 3))
            return 100.0

        _evaluate_cast_parts(
            state, (DamagePart("magic", hp_scaled_damage=scaled),), 3, 0.0, 0.0
        )
        assert seen == [0.0, 0.1, 0.2]

    def test_running_damage_offsets_missing_ratio(self) -> None:
        state = _stub_state(target_health=1000.0)
        seen: list[float] = []

        def scaled(missing_ratio: float) -> float:
            seen.append(missing_ratio)
            return 0.0

        _evaluate_cast_parts(
            state,
            (DamagePart("magic", hp_scaled_damage=scaled),),
            1,
            0.0,
            250.0,  # damage dealt earlier in the rotation
        )
        assert seen == [pytest.approx(0.25)]

    def test_crit_effectiveness_scales_raw(self) -> None:
        # Akshan R: raw × (1 + eff·cc + eff·(cm-2)·cc), physical.
        state = _stub_state(effective_armor=0.0, crit_chance=0.5, crit_multiplier=2.3)
        total, _, _, _ = _evaluate_cast_parts(
            state,
            (DamagePart("physical", 100.0, crit_effectiveness=0.3),),
            1,
            0.0,
            0.0,
        )
        expected = 100.0 * (1 + 0.3 * 0.5 + 0.3 * 0.3 * 0.5)
        assert total == pytest.approx(expected)

    def test_first_return_is_first_part_first_cast(self) -> None:
        state = _stub_state()
        _, first, _, _ = _evaluate_cast_parts(
            state,
            (DamagePart("magic", 100.0), DamagePart("true", 40.0)),
            2,
            0.0,
            0.0,
        )
        assert first == pytest.approx(apply_resistance(100.0, 0.0))

    def test_by_type_return_splits_mixed_parts(self) -> None:
        # Ahri Q shape: magic outgoing + true return, over 2 casts.
        state = _stub_state(magic_amp=1.1)
        total, _, by_type, _ = _evaluate_cast_parts(
            state,
            (DamagePart("magic", 100.0), DamagePart("true", 40.0)),
            2,
            50.0,
            0.0,
        )
        expected_magic = apply_resistance(100.0, 50.0) * 1.1 * 2
        assert by_type["magic"] == pytest.approx(expected_magic)
        assert by_type["true"] == pytest.approx(80.0)
        assert sum(by_type.values()) == pytest.approx(total)

    def test_zero_target_health_means_fully_missing(self) -> None:
        state = _stub_state(target_health=0.0)
        seen: list[float] = []

        def scaled(missing_ratio: float) -> float:
            seen.append(missing_ratio)
            return 0.0

        _evaluate_cast_parts(
            state, (DamagePart("magic", hp_scaled_damage=scaled),), 1, 0.0, 0.0
        )
        assert seen == [1.0]


# ---------------------------------------------------------------------------
# The Quantity algebra (D-72) — criterion 19's full member x member matrix
# ---------------------------------------------------------------------------


MEASURED = ability_spec.Measured(amount=3.0)
MEASURED_OTHER = ability_spec.Measured(amount=4.0)
STRUCTURAL = ability_spec.StructuralZero(reason="no immobilize in this rotation")
STRUCTURAL_OTHER = ability_spec.StructuralZero(reason="holder is not on this team")
WITHHELD = ability_spec.Withheld(receipts=("coverage: Bandlepipes is unmodelled",))
WITHHELD_OTHER = ability_spec.Withheld(
    receipts=("coverage: Dream Maker is unmodelled",)
)
STARVED = ability_spec.Starved(
    field="cc", producer="Imperial Mandate", reason="tuple ledger carries no cc stream"
)


def test_the_union_has_exactly_the_four_dispositions() -> None:
    """One member per ``Disposition``, and the tag projection is total."""
    members = (
        ability_spec.Measured,
        ability_spec.StructuralZero,
        ability_spec.Withheld,
        ability_spec.Starved,
    )
    assert set(ability_spec.Quantity.__args__) == set(members)
    assert {
        quantity.disposition for quantity in (MEASURED, STRUCTURAL, WITHHELD, STARVED)
    } == set(Disposition)


def test_disposition_survives_as_the_tag_projection() -> None:
    """D-72's "``Disposition`` survives as ``Quantity``'s tag projection"."""
    assert MEASURED.disposition is Disposition.MEASURED
    assert STRUCTURAL.disposition is Disposition.STRUCTURAL_ZERO
    assert WITHHELD.disposition is Disposition.WITHHELD
    assert STARVED.disposition is Disposition.STARVED


def test_reading_a_measured_quantity_returns_the_same_float() -> None:
    """The purity claim S3 rests on: ``Measured`` wraps, it does not transform."""
    assert ability_spec.Measured(amount=1234.5678).read() == 1234.5678


def test_reading_a_structural_zero_returns_zero_with_its_reason_intact() -> None:
    """A declared zero answers zero; the declaration is the receipt."""
    assert STRUCTURAL.read() == 0.0
    assert STRUCTURAL.reason


def test_a_structural_zero_with_no_reason_cannot_be_constructed() -> None:
    """Without the receipt it is an ordinary zero with a nicer name."""
    with pytest.raises(ValueError):
        ability_spec.StructuralZero(reason="  ")


def test_reading_a_withheld_quantity_raises_naming_its_receipts() -> None:
    """A withheld leaf has receipts instead of a number, and says so."""
    with pytest.raises(ability_spec.WithheldHasNoValue) as excinfo:
        WITHHELD.read()
    assert "Bandlepipes" in str(excinfo.value)


def test_a_withheld_quantity_with_no_receipt_cannot_be_constructed() -> None:
    """A refusal with no receipt is the blank this type exists to replace."""
    with pytest.raises(ValueError):
        ability_spec.Withheld(receipts=())
    with pytest.raises(ValueError):
        ability_spec.Withheld(receipts=("",))


def test_reading_a_starved_quantity_raises_projection_starvation() -> None:
    """D-25: lazily, on first read, carrying field/producer/reason."""
    with pytest.raises(trigger_stream.ProjectionStarvation) as excinfo:
        STARVED.read()
    message = str(excinfo.value)
    assert "cc" in message and "Imperial Mandate" in message
    assert "tuple ledger carries no cc stream" in message


def test_constructing_a_starved_quantity_raises_nothing() -> None:
    """Lazy is the whole design: a projection may hold one it never reads."""
    assert ability_spec.Starved(field="a", producer="b", reason="c").field == "a"


def test_reading_a_starved_tag_is_not_reading_its_value() -> None:
    """A serializer needs the disposition of a leaf it must not evaluate."""
    assert STARVED.disposition is Disposition.STARVED


# -- the propagation row, member x member -----------------------------------


def test_measured_folds_with_measured() -> None:
    """Row 1 of the matrix: two computed numbers make a computed number."""
    total = MEASURED + MEASURED_OTHER
    assert total == ability_spec.Measured(amount=7.0)


def test_measured_folds_with_structural_zero_which_contributes_zero() -> None:
    """The invariant table's "``STRUCTURAL_ZERO`` contributes 0.0"."""
    assert MEASURED + STRUCTURAL == ability_spec.Measured(amount=3.0)
    assert STRUCTURAL + MEASURED == ability_spec.Measured(amount=3.0)


def test_two_structural_zeros_fold_to_a_measured_zero() -> None:
    """The ruled reading of a case the invariant table leaves to the type.

    The *summation* is a rule that ran over adequate inputs, the members'
    declarations are their own receipts and not the total's, and
    ``StructuralZero`` carries one reason with no way to merge two.
    """
    assert STRUCTURAL + STRUCTURAL_OTHER == ability_spec.Measured(amount=0.0)


def test_a_withheld_member_makes_the_total_withheld_naming_it() -> None:
    """The incident at the aggregate, made unrepresentable rather than tested."""
    assert MEASURED + WITHHELD == WITHHELD
    assert WITHHELD + MEASURED == WITHHELD
    assert STRUCTURAL + WITHHELD == WITHHELD
    assert WITHHELD + STRUCTURAL == WITHHELD


def test_two_withheld_members_name_both_receipts_once_each() -> None:
    """A withheld total names every member it swallowed, deduplicated."""
    total = WITHHELD + WITHHELD_OTHER
    assert total.receipts == (
        "coverage: Bandlepipes is unmodelled",
        "coverage: Dream Maker is unmodelled",
    )
    assert (WITHHELD + WITHHELD).receipts == WITHHELD.receipts


def test_a_starved_member_raises_from_every_side_of_a_fold() -> None:
    """Folding is reading, and a starved read is a programming error."""
    for left, right in (
        (MEASURED, STARVED),
        (STARVED, MEASURED),
        (STRUCTURAL, STARVED),
        (STARVED, STRUCTURAL),
        (STARVED, STARVED),
    ):
        with pytest.raises(trigger_stream.ProjectionStarvation):
            _ = left + right


def test_starved_beats_withheld_in_both_orders() -> None:
    """The clause order is the ruling, so it is asserted rather than implied.

    A withheld total that quietly swallowed a programming error would be
    exactly the failure this campaign is named after, wearing a receipt.
    """
    with pytest.raises(trigger_stream.ProjectionStarvation):
        _ = WITHHELD + STARVED
    with pytest.raises(trigger_stream.ProjectionStarvation):
        _ = STARVED + WITHHELD


def test_the_matrix_is_covered_in_every_direction() -> None:
    """All sixteen ordered pairs resolve — no member pair is unruled."""
    members = (MEASURED, STRUCTURAL, WITHHELD, STARVED)
    seen = 0
    for left in members:
        for right in members:
            try:
                total = left + right
            except trigger_stream.ProjectionStarvation:
                assert ability_spec.Starved in (type(left), type(right))
            else:
                assert isinstance(total, (ability_spec.Measured, ability_spec.Withheld))
            seen += 1
    assert seen == 16


def test_folding_with_a_non_quantity_is_not_implemented() -> None:
    """A float is not a quantity; adding one is a type error, not a guess."""
    with pytest.raises(TypeError):
        _ = MEASURED + 1.0


def test_quantity_sum_folds_a_whole_set_through_the_algebra() -> None:
    """The aggregate helper is the fold, not a second implementation of it."""
    assert ability_spec.quantity_sum(()) == ability_spec.Measured(amount=0.0)
    assert ability_spec.quantity_sum((MEASURED, MEASURED_OTHER, STRUCTURAL)) == (
        ability_spec.Measured(amount=7.0)
    )
    assert ability_spec.quantity_sum((MEASURED, WITHHELD, MEASURED_OTHER)) == WITHHELD


def test_five_measured_components_and_one_withheld_do_not_make_a_measured_total() -> (
    None
):
    """Criterion 19's motivating case, as the unit the roster fixture backs."""
    components = [
        ability_spec.Measured(amount=value) for value in (1.0, 2.0, 3.0, 4.0, 5.0)
    ]
    total = ability_spec.quantity_sum([*components, WITHHELD])
    assert total.disposition is Disposition.WITHHELD
    assert total.receipts == WITHHELD.receipts


def test_the_algebra_is_frozen_so_a_fold_cannot_mutate_its_operands() -> None:
    """Value type: every member is a frozen dataclass with slots."""
    for member in (MEASURED, STRUCTURAL, WITHHELD, STARVED):
        with pytest.raises(Exception):
            member.disposition = Disposition.MEASURED  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Criterion 19's source half: nothing folds a quantity outside the algebra
# ---------------------------------------------------------------------------

#: Every ``.read()`` on a quantity in ``src/``, by module, with why it is
#: there.  The population is small on purpose: reading a quantity is how a
#: disposition gets discarded, so each read is a place the propagation row
#: stops, and the set of those places is the check.
DECLARED_QUANTITY_READS: dict[str, int] = {
    # The algebra itself: one read per operand inside ``__add__``, plus the
    # two summed reads.  This is the only module allowed to read two
    # quantities into one arithmetic expression, because that expression *is*
    # the propagation row.
    "calculator/ability_spec.py": 3,
    # The total, after the fold: ``ranked_total`` folds first and reads the
    # answer, so a withheld member has already made the total withheld and
    # the read is what turns that into the caller's named refusal.
    "calculator/program/build.py": 1,
    # One leaf, at the moment it is published.  ``serialize_leaf`` is the one
    # producer of a payload number and its entry, so this is where a quantity
    # legitimately becomes a float.
    "calculator/program/views/__init__.py": 1,
}


def _quantity_read_sites() -> dict[str, list[int]]:
    """Every zero-argument ``.read()`` call under ``src/calculator``.

    ``data_updater``'s file-handle read is excluded by shape rather than by
    name: it takes a stream, not a quantity, and lives in a module that never
    imports the algebra, so the population is "modules that can hold a
    quantity" and the check cannot be dodged by renaming a file.
    """
    root = Path(__file__).resolve().parent.parent / "src"
    found: dict[str, list[int]] = {}
    for path in sorted((root / "calculator").rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        if "ability_spec import" not in source and path.name != "ability_spec.py":
            continue
        if not any(
            name in source for name in ("Quantity", "Measured", "Withheld", "Starved")
        ):
            continue
        lines = [
            node.lineno
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "read"
            and not node.args
            and not node.keywords
        ]
        if lines:
            found[path.relative_to(root).as_posix()] = lines
    return found


def test_every_quantity_read_in_src_is_one_of_the_declared_ones() -> None:
    """A fourth reader is a fourth place a disposition can be dropped."""
    measured = {module: len(lines) for module, lines in _quantity_read_sites().items()}
    assert measured == DECLARED_QUANTITY_READS


def test_only_the_algebra_folds_two_quantities_into_one_expression() -> None:
    """Criterion 19's source assertion, as the shape it forbids.

    A view or a ledger that adds two ``read()`` values has re-implemented
    ``__add__`` without the propagation row: five measured components and one
    withheld one would fold to a measured total that counted the withheld
    member as zero, which is the incident at the aggregate and is exactly what
    the type exists to make unrepresentable.
    """
    root = Path(__file__).resolve().parent.parent / "src"
    offenders: list[tuple[str, int]] = []
    for module in _quantity_read_sites():
        source = (root / module).read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, (ast.BinOp, ast.AugAssign)):
                continue
            reads = [
                child
                for child in ast.walk(node)
                if isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and child.func.attr == "read"
            ]
            if reads:
                offenders.append((module, node.lineno))
    assert [module for module, _ in offenders] == [
        "calculator/ability_spec.py"
    ], offenders
