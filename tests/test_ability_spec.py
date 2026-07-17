"""Unit tests for the typed champion→engine damage contract.

Exercises damage._evaluate_cast_parts directly with a stub FightState:
the evaluator owns HP-threading, per-part mitigation, and reduced-
effectiveness crit — champion files own only the closures.
"""

from types import SimpleNamespace

import pytest

from src.calculator.ability_spec import DamagePart
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


class TestDamagePartValidation:
    def test_unknown_damage_type_raises(self) -> None:
        # A typo must never silently mitigate as magic.
        with pytest.raises(ValueError, match="phyiscal"):
            DamagePart("phyiscal", 100.0)

    def test_mixed_is_not_a_part_type(self) -> None:
        # "mixed" is an entry label; a mixed ability is two typed parts.
        with pytest.raises(ValueError, match="mixed"):
            DamagePart("mixed", 100.0)


class TestEvaluateCastParts:
    def test_single_magic_part_mitigated_and_amped(self) -> None:
        state = _stub_state(magic_amp=1.1)
        total, first = _evaluate_cast_parts(
            state, (DamagePart("magic", 200.0),), 1, 40.0, 0.0
        )
        expected = apply_resistance(200.0, 40.0) * 1.1
        assert total == pytest.approx(expected)
        assert first == pytest.approx(expected)

    def test_true_part_ignores_resists_and_amp(self) -> None:
        state = _stub_state(magic_amp=1.5)
        total, _ = _evaluate_cast_parts(
            state, (DamagePart("true", 100.0),), 1, 40.0, 0.0
        )
        assert total == 100.0

    def test_physical_part_uses_armor_without_magic_amp(self) -> None:
        state = _stub_state(effective_armor=100.0, magic_amp=2.0)
        total, _ = _evaluate_cast_parts(
            state, (DamagePart("physical", 100.0),), 1, 0.0, 0.0
        )
        assert total == pytest.approx(apply_resistance(100.0, 100.0))

    def test_count_multiplies_one_part(self) -> None:
        state = _stub_state()
        single, _ = _evaluate_cast_parts(
            state, (DamagePart("magic", 90.0),), 1, 0.0, 0.0
        )
        tripled, _ = _evaluate_cast_parts(
            state, (DamagePart("magic", 90.0, count=3),), 1, 0.0, 0.0
        )
        assert tripled == pytest.approx(single * 3)

    def test_second_part_sees_first_parts_damage(self) -> None:
        # Akali R shape: R2 interpolates on missing HP *after* R1 lands.
        state = _stub_state(target_health=1000.0)
        r1 = 300.0  # 0 resist in this test: mitigated == raw
        span = 400.0
        seen_ratios: list[float] = []

        def r2(missing_ratio: float) -> float:
            seen_ratios.append(missing_ratio)
            return 100.0 + span * missing_ratio

        total, _ = _evaluate_cast_parts(
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
        total, _ = _evaluate_cast_parts(
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
        _, first = _evaluate_cast_parts(
            state,
            (DamagePart("magic", 100.0), DamagePart("true", 40.0)),
            2,
            0.0,
            0.0,
        )
        assert first == pytest.approx(apply_resistance(100.0, 0.0))

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
