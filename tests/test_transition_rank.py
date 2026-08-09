"""The one ordered transition vocabulary and its legacy float projection.

``TransitionRank`` names what the walk's float ``phase`` always meant.  At
this stage the names are the only thing that is new: ``legacy_phase`` is a
byte-identical projection back onto today's floats, so these tests pin the
projection's *shape* (total, many-to-one, non-decreasing) rather than any
number the walk produces.
"""

import ast
import math
from pathlib import Path

import pytest

from src.calculator.survival import actions as actions_module
from src.calculator.survival.actions import TransitionRank, legacy_phase

ROOT = Path(__file__).parents[1]
SURVIVAL = ROOT / "src" / "calculator" / "survival"
TIMELINE = ROOT / "src" / "calculator" / "participant_timeline.py"


def test_legacy_phase_is_total_over_the_enum() -> None:
    """Every rank projects to a float — no member falls through a hole."""
    assert [legacy_phase(rank) for rank in TransitionRank] == [
        -2.0,
        -1.0,
        0.0,
        0.5,
        0.5,
        1.0,
        1.0,
        1.0,
        math.inf,
    ]


def test_legacy_phase_is_non_decreasing_over_declaration_order() -> None:
    """Declaration order is ordering order, with no member exempted."""
    floats = [legacy_phase(rank) for rank in TransitionRank]
    assert floats == sorted(floats)
    assert list(TransitionRank) == sorted(TransitionRank, key=int)


def test_terminal_is_declared_last_and_projects_to_infinity() -> None:
    """The one producer-less rank keeps the ladder monotonic."""
    assert list(TransitionRank)[-1] is TransitionRank.TERMINAL
    assert legacy_phase(TransitionRank.TERMINAL) == math.inf


def test_the_projection_is_many_to_one_at_this_stage() -> None:
    """Eight producing names collapse onto five distinct floats."""
    producing = [rank for rank in TransitionRank if rank is not TransitionRank.TERMINAL]
    assert len(producing) == 8
    assert len({legacy_phase(rank) for rank in producing}) == 5
    assert legacy_phase(TransitionRank.LATE_BARRIER) == legacy_phase(
        TransitionRank.REACTIVE
    )
    assert (
        legacy_phase(TransitionRank.DEBUFF_ARM)
        == legacy_phase(TransitionRank.RECOVERY)
        == legacy_phase(TransitionRank.UTILITY_ARM)
    )


def test_a_rank_without_a_float_raises_rather_than_guessing(monkeypatch) -> None:
    """An unprojected member fails loudly instead of taking a default."""
    projected = dict(actions_module._LEGACY_PHASES)
    del projected[TransitionRank.RECOVERY]
    monkeypatch.setattr(actions_module, "_LEGACY_PHASES", projected)
    with pytest.raises(KeyError, match="RECOVERY"):
        legacy_phase(TransitionRank.RECOVERY)


def _survival_action_phase_constants(path: Path) -> list[tuple[str, int]]:
    """Every ``SurvivalAction(phase=<literal>)`` still authored in one file."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offenders: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "id", "") != "SurvivalAction":
            continue
        for keyword in node.keywords:
            if keyword.arg == "phase" and isinstance(keyword.value, ast.Constant):
                offenders.append((path.name, node.lineno))
    return offenders


def test_no_action_is_built_with_a_float_phase_literal() -> None:
    """Phases are named ranks, not floats an author picked at the call site."""
    offenders: list[tuple[str, int]] = []
    for path in (*sorted(SURVIVAL.glob("*.py")), TIMELINE):
        offenders.extend(_survival_action_phase_constants(path))
    assert offenders == []
