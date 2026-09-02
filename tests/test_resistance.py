"""Tests for resistance and penetration primitives (src.calculator.resistance).

Covers apply_resistance and apply_magic_penetration -- the mitigation math
every damage path funnels through (Lethality needs no conversion since
V14.1: it is 1:1 flat armor penetration, covered in test_stats.py) -- and the
MR ``damage.Resists`` serves once the rotation is over.
"""

import pytest

from src.calculator.damage import Resists
from src.calculator.interpreters import resistance_shred
from src.calculator.item_behavior import Resistance
from src.calculator.resistance import (
    apply_armor_penetration,
    apply_magic_penetration,
    apply_resistance,
)


class TestApplyResistance:
    """Tests for damage mitigation from armor/MR."""

    def test_zero_resistance(self) -> None:
        assert apply_resistance(100, 0) == 100.0

    def test_100_resistance_halves_damage(self) -> None:
        assert apply_resistance(100, 100) == 50.0

    def test_200_resistance(self) -> None:
        result = apply_resistance(300, 200)
        assert abs(result - 100.0) < 0.01

    def test_negative_resistance_amplifies(self) -> None:
        result = apply_resistance(100, -50)
        assert result > 100.0

    def test_zero_damage_returns_zero(self) -> None:
        assert apply_resistance(0, 100) == 0.0


class TestApplyMagicPenetration:
    """Tests for magic penetration calculations."""

    def test_no_penetration(self) -> None:
        assert apply_magic_penetration(100, 0, 0) == 100.0

    def test_flat_penetration_only(self) -> None:
        assert apply_magic_penetration(100, 12, 0) == 88.0

    def test_percent_penetration_only(self) -> None:
        result = apply_magic_penetration(100, 0, 0.40)
        assert abs(result - 60.0) < 0.01

    def test_combined_penetration_percent_first(self) -> None:
        # 100 MR -> 40% pen -> 60 -> -12 flat -> 48
        result = apply_magic_penetration(100, 12, 0.40)
        assert abs(result - 48.0) < 0.01

    def test_cannot_go_below_zero(self) -> None:
        result = apply_magic_penetration(10, 50, 0)
        assert result == 0.0


class TestApplyArmorPenetration:
    """Tests for armor penetration calculations (flat pen = lethality)."""

    def test_no_penetration(self) -> None:
        assert apply_armor_penetration(100, 0, 0) == 100.0

    def test_flat_penetration_only(self) -> None:
        assert apply_armor_penetration(100, 20, 0) == 80.0

    def test_combined_penetration_percent_first(self) -> None:
        # 100 armor -> 30% pen -> 70 -> -20 flat -> 50
        result = apply_armor_penetration(100, 20, 0.30)
        assert abs(result - 50.0) < 0.01

    def test_lethality_cannot_reduce_armor_below_zero(self) -> None:
        # 20 lethality vs 10 armor floors at 0 -- it must never produce
        # negative armor (which apply_resistance would amplify).
        assert apply_armor_penetration(10, 20, 0) == 0.0

    def test_negative_armor_from_reduction_survives_penetration(self) -> None:
        # A flat REDUCTION (Corki E) may take armor below zero; penetration
        # must neither undo it (percent) nor deepen it (flat).
        assert apply_armor_penetration(-8, 20, 0.30) == -8.0


class TestPenetrationOnNegativeResistance:
    """Reduction effects can go negative; penetration leaves them alone."""

    def test_negative_mr_survives_penetration(self) -> None:
        assert apply_magic_penetration(-8, 20, 0.40) == -8.0

    def test_zero_resistance_stays_zero(self) -> None:
        assert apply_magic_penetration(0, 20, 0.40) == 0.0
        assert apply_armor_penetration(0, 20, 0.40) == 0.0


class TestServedEffectiveMr:
    """``effective_mr`` is resolved from the whole rotation outcome, once.

    Bloodletter's Curse leaves Vile Decay stacks on the target and Terminus
    switches the remaining damage to auto pen.  Both land at the end of the
    rotation, and the served MR must be the same whichever order they land in.
    """

    @staticmethod
    def _resists() -> Resists:
        resists = Resists(
            magic_pen_flat=0.0,
            magic_pen_percent=0.30,
            armor_pen_percent=0.0,
            flat_armor_pen=0.0,
            has_terminus=True,
            terminus_stat_pen=0.10,
            terminus_avg_pen=0.20,
            target_armor=100.0,
            base_mr=60.0,
            reduced_mr=60.0,
            malignance_mr_reduction=0.0,
            bc_reduction=0.0,
            mr_shred=resistance_shred.resolve_slot(
                ["Bloodletter's Curse"],
                Resistance.MAGIC_RESIST,
                level=18,
                fight_duration_seconds=5.0,
                target_bonus_health=0.0,
                holder_is_melee=False,
            ),
        )
        resists.resolve_magic()
        return resists

    def test_the_auto_pen_switch_keeps_the_rotation_s_shred_stacks(self) -> None:
        unshredded = self._resists()
        unshredded.use_auto_pen()

        stacked = self._resists()
        stacked.apply_shred_stacks(6)
        stacked.use_auto_pen()

        assert stacked.effective_mr == pytest.approx(21.12)
        assert stacked.effective_mr < unshredded.effective_mr

    def test_the_served_mr_does_not_depend_on_which_lands_first(self) -> None:
        shred_first = self._resists()
        shred_first.apply_shred_stacks(6)
        shred_first.use_auto_pen()

        pen_first = self._resists()
        pen_first.use_auto_pen()
        pen_first.apply_shred_stacks(6)

        assert shred_first.effective_mr == pen_first.effective_mr

    def test_no_stacks_serves_the_plain_variant(self) -> None:
        resists = self._resists()
        resists.apply_shred_stacks(0)

        assert resists.effective_mr == resists.effective_mr_pre_ult
