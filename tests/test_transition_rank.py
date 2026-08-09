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
from src.calculator.survival.actions import (
    SUPPORT_RANK_KEY,
    TransitionRank,
    legacy_phase,
    support_transition_rank,
)

ROOT = Path(__file__).parents[1]
SURVIVAL = ROOT / "src" / "calculator" / "survival"
TIMELINE = ROOT / "src" / "calculator" / "participant_timeline.py"
ITEM_SUPPORT = ROOT / "src" / "calculator" / "item_support_effects.py"


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


# --- The support ladder: a rank, never an open float ------------------------


def test_the_open_priority_hatch_is_gone_from_the_source() -> None:
    """No producer can hand the walk an arbitrary ordering float."""
    holders = [
        path.relative_to(ROOT).as_posix()
        for path in sorted((ROOT / "src").rglob("*.py"))
        if "_priority" in path.read_text(encoding="utf-8")
    ]
    assert holders == []


def test_support_kinds_classify_to_their_ladder_rank() -> None:
    """Every support kind resolves to a named rank, none to a number."""
    by_kind = {
        "stasis": TransitionRank.STATE_GRANT,
        "invulnerability": TransitionRank.STATE_GRANT,
        "untargetable": TransitionRank.STATE_GRANT,
        "spell_shield": TransitionRank.STATE_GRANT,
        "shield": TransitionRank.BARRIER_GRANT,
        "temporary_health": TransitionRank.BARRIER_GRANT,
        "heal": TransitionRank.RECOVERY,
        "regen": TransitionRank.RECOVERY,
        "damage_modifier": TransitionRank.DEBUFF_ARM,
        "stat_buff": TransitionRank.DEBUFF_ARM,
        "movement": TransitionRank.UTILITY_ARM,
        "cleanse": TransitionRank.UTILITY_ARM,
        "economy": TransitionRank.UTILITY_ARM,
        "vision": TransitionRank.UTILITY_ARM,
    }
    for kind, rank in by_kind.items():
        assert support_transition_rank({"kind": kind}) is rank


def test_the_classified_ladder_reproduces_the_floats_it_replaced() -> None:
    """The three legacy branches — -2.0, -1.0 and the 1.0 fall-through."""
    assert legacy_phase(support_transition_rank({"kind": "stasis"})) == -2.0
    assert legacy_phase(support_transition_rank({"kind": "shield"})) == -1.0
    for kind in ("heal", "damage_modifier", "movement", "anything_unlisted"):
        assert legacy_phase(support_transition_rank({"kind": kind})) == 1.0


def test_a_packet_may_declare_a_rank_but_not_an_ordering() -> None:
    """The declaration overrides the kind, and only enum members are legal."""
    late = {"kind": "shield", SUPPORT_RANK_KEY: TransitionRank.LATE_BARRIER}
    assert support_transition_rank(late) is TransitionRank.LATE_BARRIER
    assert legacy_phase(support_transition_rank(late)) == 0.5
    with pytest.raises(ValueError):
        support_transition_rank({"kind": "shield", SUPPORT_RANK_KEY: 0.5})


def _rank_name(node: ast.expr) -> str:
    """``TransitionRank.X`` as ``"X"``, anything else as ``""``."""
    if isinstance(node, ast.Attribute) and getattr(node.value, "id", "") == (
        "TransitionRank"
    ):
        return node.attr
    return ""


def _declared_ranks(path: Path) -> list[tuple[str, str]]:
    """Every rank a packet author declares on a packet in one file.

    Two spellings, one meaning: the ``rank=`` keyword of a ``_packet`` call
    and a literal ``SUPPORT_RANK_KEY:`` dict entry.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg == "rank" and _rank_name(keyword.value):
                    found.append((path.name, _rank_name(keyword.value)))
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if getattr(key, "id", "") == "SUPPORT_RANK_KEY" and _rank_name(value):
                    found.append((path.name, _rank_name(value)))
    return found


def test_the_packet_authors_that_declare_a_rank_are_exactly_three() -> None:
    """The population that used to write an open float, now named."""
    declared = _declared_ranks(ITEM_SUPPORT) + _declared_ranks(TIMELINE)
    assert sorted(declared) == [
        ("item_support_effects.py", "DAMAGE"),
        ("item_support_effects.py", "LATE_BARRIER"),
        ("participant_timeline.py", "LATE_BARRIER"),
    ]
