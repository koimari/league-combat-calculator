"""Unit tests for the typed champion→engine damage contract.

Exercises damage._evaluate_cast_parts directly with a stub FightState:
the evaluator owns HP-threading, per-part mitigation, and reduced-
effectiveness crit — champion files own only the closures.  Also pins the
four closed vocabularies the leaf declares, member for member.
"""

import ast
from enum import Enum
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.calculator import ability_spec
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
        """Authority lives here because every layer can import this module."""
        for node in ast.walk(_module_tree()):
            if isinstance(node, ast.ImportFrom):
                assert node.level == 0 and not str(node.module).startswith(
                    "src.calculator"
                ), f"ability_spec.py:{node.lineno} imports a sibling module"
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("src.calculator")


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
