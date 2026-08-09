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


# --- The phase slot: every way a float can still reach one ------------------
#
# The guard below is positional, not name-based: it finds the *slots* that
# carry a phase and rejects a numeric literal anywhere inside the expression
# filling one.  The counting rule is stated here so the population is
# reproducible rather than judged (R-29's idiom).  A phase slot is:
#
#   1. the ``phase=`` keyword of any call;
#   2. positional argument 1 of ``action_key``, ``_action_key``,
#      ``survival_action_from_event``, ``classify_event_kind`` and
#      ``_classify_prefetched`` — every function whose second parameter is
#      literally named ``phase``;
#   3. element 1 of a sort-key tuple, in the three shapes the tree writes
#      one: a ``sort_key=`` keyword, an assignment to a name ``sort_key``,
#      and the body of a ``lambda`` handed to a ``key=`` argument;
#   4. the constant side of a comparison whose other side is ``phase`` or
#      ``<something>.phase``.
#
# A slot filled by a bare local name is resolved through one level of
# assignment inside the enclosing function, because ``priority = -1.0 if
# ... else 1.0`` followed by ``phase=priority`` is the same literal wearing
# a variable's clothes — that spelling is exactly how the compiled support
# branch kept its own float ladder after the first migration pass.

_PHASE_ARG1_CALLS = frozenset(
    {
        "action_key",
        "_action_key",
        "survival_action_from_event",
        "classify_event_kind",
        "_classify_prefetched",
    }
)


def _callee_name(node: ast.expr) -> str:
    """The bare name of a call target, however it was spelled."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _holds_number(node: ast.AST) -> bool:
    """Whether an expression carries a numeric literal as a *value*.

    Subscript indices are skipped: ``float(event["_sk"][1])`` reads the
    phase back out of a sort key that was itself built from a rank, so its
    ``1`` is a tuple position and not a phase anybody chose.
    """
    if isinstance(node, ast.Constant):
        return isinstance(node.value, (int, float)) and not isinstance(node.value, bool)
    if isinstance(node, ast.Subscript):
        return _holds_number(node.value)
    return any(_holds_number(child) for child in ast.iter_child_nodes(node))


def _local_assignments(tree: ast.AST) -> dict[str, list[ast.expr]]:
    """Every ``name = <expr>`` in the module, by name.

    One level is enough: the tree never routes a phase through two hops,
    and a deeper chain would be flagged by the reader rather than hidden.
    """
    bound: dict[str, list[ast.expr]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    bound.setdefault(target.id, []).append(node.value)
    return bound


def _slot_offends(node: ast.expr, bound: dict[str, list[ast.expr]]) -> bool:
    """Whether the expression filling a phase slot carries a literal."""
    if isinstance(node, ast.Name):
        return any(_holds_number(value) for value in bound.get(node.id, ()))
    return _holds_number(node)


def _sort_key_tuples(tree: ast.AST) -> list[ast.Tuple]:
    """Every tuple literal the tree builds as a sort key (shape 3 above)."""
    found: list[ast.Tuple] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg == "sort_key" and isinstance(keyword.value, ast.Tuple):
                    found.append(keyword.value)
                if keyword.arg == "key" and isinstance(keyword.value, ast.Lambda):
                    if isinstance(keyword.value.body, ast.Tuple):
                        found.append(keyword.value.body)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id == "sort_key"
                    and isinstance(node.value, ast.Tuple)
                ):
                    found.append(node.value)
    return found


def _is_phase_operand(node: ast.expr) -> bool:
    """``phase`` or ``<x>.phase`` — the reader side of a comparison."""
    if isinstance(node, ast.Name):
        return node.id == "phase"
    if isinstance(node, ast.Attribute):
        return node.attr == "phase"
    return False


def phase_literals(path: Path) -> list[tuple[str, int, str]]:
    """Every numeric literal still reaching a phase slot in one file."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    bound = _local_assignments(tree)
    offenders: list[tuple[str, int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            callee = _callee_name(node.func)
            for keyword in node.keywords:
                if keyword.arg == "phase" and _slot_offends(keyword.value, bound):
                    offenders.append((path.name, keyword.value.lineno, "phase="))
            if callee in _PHASE_ARG1_CALLS and len(node.args) > 1:
                if _slot_offends(node.args[1], bound):
                    offenders.append((path.name, node.args[1].lineno, f"{callee}(,1)"))
        elif isinstance(node, ast.Compare):
            operands = [node.left, *node.comparators]
            if any(_is_phase_operand(side) for side in operands) and any(
                _holds_number(side) for side in operands
            ):
                offenders.append((path.name, node.lineno, "phase comparison"))
    for tup in _sort_key_tuples(tree):
        if len(tup.elts) > 1 and _slot_offends(tup.elts[1], bound):
            offenders.append((path.name, tup.elts[1].lineno, "sort_key[1]"))
    return sorted(offenders)


def test_no_float_literal_reaches_a_phase_slot() -> None:
    """Phases are named ranks, not floats an author picked at the call site.

    The population is every phase slot in the kernel package and the
    timeline — action construction, sort-key tuples, the ``action_key``
    family's phase argument, and the comparisons that read a phase back —
    not just the ``SurvivalAction(phase=)`` keyword, which is one spelling
    of five and the one a migration notices first.
    """
    offenders: list[tuple[str, int, str]] = []
    for path in (*sorted(SURVIVAL.glob("*.py")), TIMELINE):
        offenders.extend(phase_literals(path))
    assert offenders == []


def test_the_phase_slot_guard_sees_every_spelling(tmp_path: Path) -> None:
    """The guard's own red: each shape it claims to cover, made to fail."""
    sample = tmp_path / "sample.py"
    sample.write_text(
        "\n".join(
            (
                "SurvivalAction(phase=1.0)",
                "action_key(t, 0.5, who, event)",
                "SurvivalAction(sort_key=(t, 1.0, s))",
                "sort_key = (t, 0.5, s)",
                "sorted(rows, key=lambda row: (row.t, -1.0, row.id))",
                "if phase == -1:\n    pass",
                "priority = -1.0 if kind == 'shield' else 1.0",
                "SurvivalAction(phase=priority)",
            )
        ),
        encoding="utf-8",
    )
    slots = [slot for _, _, slot in phase_literals(sample)]
    assert sorted(set(slots)) == [
        "action_key(,1)",
        "phase comparison",
        "phase=",
        "sort_key[1]",
    ]
    assert slots.count("phase=") == 2  # the literal and the aliased ladder


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
