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
from typing import Iterable, Mapping, NamedTuple, Sequence

import pytest

from src.calculator.survival import actions as actions_module
from src.calculator.survival.actions import (
    SUPPORT_RANK_KEY,
    ActionKind,
    SurvivalAction,
    TransitionRank,
    compiled_damage_action,
    legacy_phase,
    support_transition_rank,
)

ROOT = Path(__file__).parents[1]
SURVIVAL = ROOT / "src" / "calculator" / "survival"
TIMELINE = ROOT / "src" / "calculator" / "participant_timeline.py"
ITEM_SUPPORT = ROOT / "src" / "calculator" / "item_support_effects.py"


def _population() -> tuple[Path, ...]:
    """Every file a phase can be written in: the kernel plus the timeline."""
    return (*sorted(SURVIVAL.glob("*.py")), TIMELINE)


def test_legacy_phase_is_total_over_the_enum() -> None:
    """Every rank projects to a float — no member falls through a hole."""
    assert [legacy_phase(rank) for rank in TransitionRank] == [
        -2.0,
        -1.0,
        -0.5,
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
    """Nine producing names collapse onto six distinct floats (D-06).

    Eight onto five at 0A; C4's ``AURA_ARM`` is the ninth name and the
    sixth float, and it is the only member whose float no producer wrote
    before it existed.
    """
    producing = [rank for rank in TransitionRank if rank is not TransitionRank.TERMINAL]
    assert len(producing) == 9
    assert len({legacy_phase(rank) for rank in producing}) == 6
    assert legacy_phase(TransitionRank.AURA_ARM) == -0.5
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
#   2. the positional argument a definition in the population names
#      ``phase`` — ``action_key(t, 0.5, ...)`` and friends;
#   3. element 1 of a sort-key tuple, in every shape the tree writes one: a
#      ``sort_key=`` keyword, an assignment to a name ``sort_key``, the body
#      of a ``lambda`` handed to a ``key=`` argument, and a tuple handed
#      positionally to the argument a definition names ``sort_key``;
#   4. the constant side of a comparison whose other side is ``phase`` or
#      ``<something>.phase``;
#   5. the *default* of a class field named ``phase``.  A default is a slot
#      every constructor that omits the field fills, which makes it the
#      widest one in the tree rather than the narrowest:
#      ``compiled_damage_action`` deliberately assigns no phase, so
#      ``SurvivalAction``'s class default is where every compiled damage
#      action in the hot path gets its phase from.
#
# **Shapes 2 and 3 read their positions from the definitions, never from a
# list of names.**  The first version of this guard typed out five callee
# names and asserted the tree was clean; ``compiled_damage_action`` was not
# among them, so the two hot-path sort keys ``compile.py`` hands it
# positionally were counted as absent by the very rule that existed to find
# them.  A guard whose population is enumerated by its own blind spot is
# green over nothing — the campaign's own failure shape, one level down.
# ``_slot_rules`` therefore derives the index of a ``phase`` parameter and of
# a ``sort_key`` parameter from every ``def`` and every NamedTuple field
# list in the population, so a positional call is a slot whether or not
# anybody remembered the callee's name.
#
# A slot filled by a bare name is resolved through one level of assignment,
# because ``priority = -1.0 if ... else 1.0`` followed by ``phase=priority``
# is the same literal wearing a variable's clothes — that spelling is exactly
# how the compiled support branch kept its own float ladder after the first
# migration pass.  Resolution spans the whole population rather than one
# file, so a constant that hides a literal cannot be laundered through an
# import.


class _SlotRules(NamedTuple):
    """Where a phase can sit, read from the scanned population itself."""

    phase_arg: Mapping[str, int]  # callee name -> index of its ``phase`` argument
    sort_key_arg: Mapping[str, int]  # callee name -> index of its ``sort_key``
    bound: Mapping[str, list[ast.expr]]  # name -> what the population assigns it


def _positional_names(node: ast.AST) -> list[str]:
    """The positional parameter names of one definition, callee order.

    A ``def`` contributes its signature; a class contributes its annotated
    field order, which is what a NamedTuple accepts positionally.  ``self``
    is dropped so a method's indices match how the method is called.
    """
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        names = [arg.arg for arg in node.args.posonlyargs + node.args.args]
        return names[1:] if names and names[0] in ("self", "cls") else names
    if isinstance(node, ast.ClassDef):
        return [
            stmt.target.id
            for stmt in node.body
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
        ]
    return []


def _slot_rules(trees: Sequence[ast.AST]) -> _SlotRules:
    """Derive shapes 2 and 3's positions, plus the one-level name binding."""
    phase_arg: dict[str, int] = {}
    sort_key_arg: dict[str, int] = {}
    bound: dict[str, list[ast.expr]] = {}
    for tree in trees:
        for node in ast.walk(tree):
            names = _positional_names(node)
            if "phase" in names:
                phase_arg[node.name] = names.index("phase")
            if "sort_key" in names:
                sort_key_arg[node.name] = names.index("sort_key")
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        bound.setdefault(target.id, []).append(node.value)
    return _SlotRules(phase_arg, sort_key_arg, bound)


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


def _slot_offends(node: ast.expr, bound: Mapping[str, list[ast.expr]]) -> bool:
    """Whether the expression filling a phase slot carries a literal."""
    if isinstance(node, ast.Name):
        return any(_holds_number(value) for value in bound.get(node.id, ()))
    return _holds_number(node)


def _sort_key_tuples(tree: ast.AST, rules: _SlotRules) -> list[tuple[ast.Tuple, str]]:
    """Every tuple literal the tree builds as a sort key (shape 3 above).

    Four spellings: the ``sort_key=`` keyword, an assignment to a name
    ``sort_key``, a ``key=lambda`` body, and a tuple handed positionally to
    whatever index a definition puts ``sort_key`` at.
    """
    found: list[tuple[ast.Tuple, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg == "sort_key" and isinstance(keyword.value, ast.Tuple):
                    found.append((keyword.value, "sort_key[1]"))
                if keyword.arg == "key" and isinstance(keyword.value, ast.Lambda):
                    if isinstance(keyword.value.body, ast.Tuple):
                        found.append((keyword.value.body, "sort_key[1]"))
            index = rules.sort_key_arg.get(_callee_name(node.func), -1)
            if 0 <= index < len(node.args) and isinstance(node.args[index], ast.Tuple):
                found.append((node.args[index], "sort_key[1] (positional)"))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id == "sort_key"
                    and isinstance(node.value, ast.Tuple)
                ):
                    found.append((node.value, "sort_key[1]"))
    return found


def _is_phase_operand(node: ast.expr) -> bool:
    """``phase`` or ``<x>.phase`` — the reader side of a comparison."""
    if isinstance(node, ast.Name):
        return node.id == "phase"
    if isinstance(node, ast.Attribute):
        return node.attr == "phase"
    return False


def phase_literals(
    path: Path, rules: _SlotRules | None = None
) -> list[tuple[str, int, str]]:
    """Every numeric literal still reaching a phase slot in one file.

    ``rules`` carries the positions and name bindings derived from the whole
    population; a caller that omits it gets the ones this file alone
    declares, which is what the guard's own red fixture wants.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    rules = rules if rules is not None else _slot_rules([tree])
    bound = rules.bound
    offenders: list[tuple[str, int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            callee = _callee_name(node.func)
            for keyword in node.keywords:
                if keyword.arg == "phase" and _slot_offends(keyword.value, bound):
                    offenders.append((path.name, keyword.value.lineno, "phase="))
            index = rules.phase_arg.get(callee, -1)
            if 0 <= index < len(node.args) and _slot_offends(node.args[index], bound):
                offenders.append(
                    (path.name, node.args[index].lineno, f"{callee}(,{index})")
                )
        elif isinstance(node, ast.Compare):
            operands = [node.left, *node.comparators]
            if any(_is_phase_operand(side) for side in operands) and any(
                _holds_number(side) for side in operands
            ):
                offenders.append((path.name, node.lineno, "phase comparison"))
        elif isinstance(node, ast.ClassDef):
            for stmt in node.body:
                if (
                    isinstance(stmt, ast.AnnAssign)
                    and isinstance(stmt.target, ast.Name)
                    and stmt.target.id == "phase"
                    and stmt.value is not None
                    and _slot_offends(stmt.value, bound)
                ):
                    offenders.append(
                        (path.name, stmt.lineno, f"{node.name}.phase default")
                    )
    for tup, slot in _sort_key_tuples(tree, rules):
        if len(tup.elts) > 1 and _slot_offends(tup.elts[1], bound):
            offenders.append((path.name, tup.elts[1].lineno, slot))
    return sorted(offenders)


def _population_rules(paths: Iterable[Path]) -> _SlotRules:
    """The slot positions and name bindings the whole population declares."""
    return _slot_rules([ast.parse(path.read_text(encoding="utf-8")) for path in paths])


def test_the_positional_phase_slots_are_read_from_the_definitions() -> None:
    """Shapes 2 and 3 are a derivation over the tree, not a list of names.

    Pinning the derived map is what makes the guard's population auditable:
    a new callable that takes a ``phase`` or builds a ``sort_key`` shows up
    here, so it can never be scanned by a rule that has not heard of it.
    """
    rules = _population_rules(_population())
    assert dict(rules.phase_arg) == {
        "SurvivalAction": 2,
        "_classify_prefetched": 1,
        "action_key": 1,
        "classify_event_kind": 1,
        "survival_action_from_event": 1,
    }
    assert dict(rules.sort_key_arg) == {
        "SurvivalAction": 0,
        "compiled_damage_action": 0,
    }


def test_no_float_literal_reaches_a_phase_slot() -> None:
    """Phases are named ranks, not floats an author picked at the call site.

    The population is every phase slot in the kernel package and the
    timeline — action construction, sort-key tuples in all four spellings,
    the phase argument of every definition that takes one, and the
    comparisons that read a phase back — not just the
    ``SurvivalAction(phase=)`` keyword, which is one spelling of many and
    the one a migration notices first.
    """
    paths = _population()
    rules = _population_rules(paths)
    offenders: list[tuple[str, int, str]] = []
    for path in paths:
        offenders.extend(phase_literals(path, rules))
    assert offenders == []


def test_the_compiled_hot_path_arms_at_the_damage_rank() -> None:
    """The widest phase slot: a class default nothing overwrites.

    ``compiled_damage_action`` assigns no phase — there is no ``_I_PHASE``
    index — so every damage action the optimizer compiles takes
    :class:`SurvivalAction`'s class default.  Asserting both halves is what
    keeps that shortcut honest: if the default ever stops being the damage
    rank, this fails instead of the compiled score path quietly arming its
    damage somewhere the receipt walk does not.
    """
    action = compiled_damage_action(
        (0.0, legacy_phase(TransitionRank.DAMAGE), 0),
        0.0,
        ActionKind.PLAIN_DAMAGE,
        0,
        1,
        0,
        10.0,
        "physical",
        None,
        10.0,
        None,
        None,
        "source_key",
        "Source",
        "event:1",
        0,
    )
    assert action.phase == legacy_phase(TransitionRank.DAMAGE)
    assert SurvivalAction().phase == legacy_phase(TransitionRank.DAMAGE)


def test_the_phase_slot_guard_sees_every_spelling(tmp_path: Path) -> None:
    """The guard's own red: each shape it claims to cover, made to fail."""
    sample = tmp_path / "sample.py"
    sample.write_text(
        "\n".join(
            (
                # The definitions shapes 2 and 3 read their positions from.
                "def action_key(event_time, phase, participant_id, event):\n    pass",
                "def compiled_damage_action(sort_key, time, kind):\n    pass",
                "SurvivalAction(phase=1.0)",
                "action_key(t, 0.5, who, event)",
                "SurvivalAction(sort_key=(t, 1.0, s))",
                "sort_key = (t, 0.5, s)",
                "sorted(rows, key=lambda row: (row.t, -1.0, row.id))",
                "compiled_damage_action((t, 0.0, seq), time, kind)",
                "if phase == -1:\n    pass",
                "priority = -1.0 if kind == 'shield' else 1.0",
                "SurvivalAction(phase=priority)",
                "class Action(NamedTuple):\n    phase: float = 0.0",
            )
        ),
        encoding="utf-8",
    )
    slots = [slot for _, _, slot in phase_literals(sample)]
    assert sorted(set(slots)) == [
        "Action.phase default",
        "action_key(,1)",
        "phase comparison",
        "phase=",
        "sort_key[1]",
        "sort_key[1] (positional)",
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


def test_the_packet_authors_that_declare_a_rank_are_exactly_four() -> None:
    """The population that used to write an open float, now named.

    Three at 0A; C4 adds Abyssal Mask's Unmake, the one persistent
    cross-participant modifier, which declares ``AURA_ARM`` because the
    kind ladder would otherwise arm an aura like a triggered debuff.
    """
    declared = _declared_ranks(ITEM_SUPPORT) + _declared_ranks(TIMELINE)
    assert sorted(declared) == [
        ("item_support_effects.py", "AURA_ARM"),
        ("item_support_effects.py", "DAMAGE"),
        ("item_support_effects.py", "LATE_BARRIER"),
        ("participant_timeline.py", "LATE_BARRIER"),
    ]
