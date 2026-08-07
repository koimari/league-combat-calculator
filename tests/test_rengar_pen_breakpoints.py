"""Tests for the shareable Rengar breakpoint calculator."""

import pytest

from scripts.rengar_pen_breakpoints import (
    Inputs,
    _standalone_model,
    evaluate,
    first_crossing,
)


def _fixture() -> Inputs:
    return Inputs(
        enemy_total_hp=2500.0,
        enemy_current_hp=2500.0,
        enemy_bonus_hp=1000.0,
        user_total_hp=1847.0,
        enemy_armor=200.0,
        enemy_mr=50.0,
        r_armor_reduction=20.0,
        one_auto=True,
        umbral_ready=True,
        cyclosword_lethality_for_true_procs=False,
    )


def test_fixture_matches_the_calibrated_level_14_rotation() -> None:
    triple, ldr = evaluate(_standalone_model(one_auto=True), _fixture())
    assert triple.packet_damage == pytest.approx(763.165487)
    assert ldr.packet_damage == pytest.approx(791.316384)
    assert triple.true_damage == pytest.approx(250.0)
    assert triple.cyclosword_raw == pytest.approx(225.0)


def test_cyclosword_lethality_toggle_changes_true_procs_only() -> None:
    model = _standalone_model(one_auto=True)
    base = _fixture()
    with_extra = Inputs(
        **{**base.__dict__, "cyclosword_lethality_for_true_procs": True}
    )
    triple_base, _ = evaluate(model, base)
    triple_extra, _ = evaluate(model, with_extra)
    assert triple_extra.true_damage - triple_base.true_damage == pytest.approx(45.0)
    assert triple_extra.cyclosword_raw == triple_base.cyclosword_raw


def test_first_crossing_refines_a_linear_root() -> None:
    root = first_crossing(lambda value: value - 12.5, 0.0, 100.0)
    assert root == pytest.approx(12.5)
