"""The one ordered transition vocabulary, and the collapse it still carries.

``TransitionRank`` names what the walk's float ``phase`` always meant.  0A
introduced the names beside a byte-identical float projection; Phase 4 S2
deleted the projection, so a phase is a member of this enum everywhere the
tree writes, sorts, compares or dispatches on one.

What the float said that the ordinals do not is a *collapse*: two groups of
ranks shared one number and therefore resolved together.  ``ordering_slot``
is that collapse, named, and these tests pin its shape — which group, and
that every other read of a rank is invariant under it.

Phase 4 S6 split one of the two groups.  ``DEBUFF_ARM``/``RECOVERY``/
``UTILITY_ARM`` now resolve ``6 < 7 < 8`` at a shared timestamp instead of
tying, and the reorderings that follows from are pinned below by name.
``LATE_BARRIER``/``REACTIVE`` still share a slot, deliberately: that one is
a preserved defect S6 declined to touch, not an oversight.
"""

import ast
import json
from pathlib import Path
from typing import Iterable, Mapping, NamedTuple, Sequence

import pytest

from src.calculator.survival import actions as actions_module
from src.calculator.survival.actions import (
    SUPPORT_RANK_KEY,
    ActionKind,
    SurvivalAction,
    TransitionRank,
    action_key,
    classify_event_kind,
    compiled_damage_action,
    ordering_slot,
    support_transition_rank,
)

ROOT = Path(__file__).parents[1]
SURVIVAL = ROOT / "src" / "calculator" / "survival"
PROGRAM = ROOT / "src" / "calculator" / "program"
TIMELINE = ROOT / "src" / "calculator" / "participant_timeline.py"
ITEM_SUPPORT = ROOT / "src" / "calculator" / "item_support_effects.py"


def _population() -> tuple[Path, ...]:
    """Every file a phase can be written in.

    Three trees, not one: the kernel that consumes a rank, the timeline that
    composes a walk, and ``program/`` — which is where the one
    ``SurvivalAction`` constructor moved at Phase 4 S4, so a float written
    into a phase slot would land there and nowhere else.  Scanning only the
    kernel after that move would leave the guard pointed at a file the
    construction had left.
    """
    return (*sorted(SURVIVAL.glob("*.py")), *sorted(PROGRAM.rglob("*.py")), TIMELINE)


def test_the_ordering_fold_is_total_and_closed() -> None:
    """Every rank has a slot, and no rank can fall through a hole.

    The fold is a partial table read through a default of *itself*, so a
    member added without an entry orders as itself — which is what a rank
    sharing its slot with nothing means.  A total table would instead need
    an entry per member and would grow a hole the day one was forgotten.
    """
    slots = {rank: ordering_slot(rank) for rank in TransitionRank}
    assert set(slots) == set(TransitionRank)
    assert all(isinstance(slot, TransitionRank) for slot in slots.values())
    assert set(actions_module._ORDERING_SLOTS) < set(TransitionRank)


def test_one_collapsed_pair_survives_and_the_other_group_is_split() -> None:
    """Nine producing ranks resolve in eight ordering slots (D-06, S6).

    The float ladder S2 deleted gave ``LATE_BARRIER``/``REACTIVE`` one
    number and ``DEBUFF_ARM``/``RECOVERY``/``UTILITY_ARM`` another.  S6
    split the second group; the first still shares a slot, and this
    asserts *both* halves so the stage cannot be read as having split
    everything or nothing.
    """
    producing = [rank for rank in TransitionRank if rank is not TransitionRank.TERMINAL]
    assert len(producing) == 9
    assert len({ordering_slot(rank) for rank in producing}) == 8
    assert ordering_slot(TransitionRank.REACTIVE) is TransitionRank.LATE_BARRIER
    for rank in (
        TransitionRank.DEBUFF_ARM,
        TransitionRank.RECOVERY,
        TransitionRank.UTILITY_ARM,
    ):
        assert ordering_slot(rank) is rank
    alone = set(producing) - {TransitionRank.REACTIVE}
    assert all(ordering_slot(rank) is rank for rank in alone)


def test_the_fold_never_moves_a_rank_across_a_kernel_threshold() -> None:
    """Why only two reads consult the fold and the rest need not.

    The kernel compares a phase against ``DAMAGE`` and against the recovery
    slot.  A group that straddled either boundary would make every one of
    those comparisons fold-sensitive; none does, and this is the assertion
    that says so rather than a comment claiming it.
    """
    for rank in TransitionRank:
        for threshold in (TransitionRank.DAMAGE, TransitionRank.DEBUFF_ARM):
            assert (rank < threshold) == (ordering_slot(rank) < threshold)


def test_terminal_is_declared_last_and_produced_by_nothing() -> None:
    """The one producer-less rank still closes the ladder."""
    assert list(TransitionRank)[-1] is TransitionRank.TERMINAL
    assert list(TransitionRank) == sorted(TransitionRank, key=int)
    assert ordering_slot(TransitionRank.TERMINAL) is TransitionRank.TERMINAL


def test_the_sort_key_carries_the_slot_and_not_the_rank() -> None:
    """Element 1 of the walk's total order is the fold's output.

    Since S6 the fold is the identity for every arming rank, so a heal and
    a debuff armed at one timestamp no longer tie on the phase component
    and no longer fall through to the tie-breaks after it.  A reactive
    strike-back still ties with a late barrier, which is the one pair the
    fold still holds.
    """
    event = {"sequence": 0, "attacker": "main", "_event_id": "e", "source": "s"}
    heal = action_key(1.0, TransitionRank.RECOVERY, "main", event)
    debuff = action_key(1.0, TransitionRank.DEBUFF_ARM, "main", event)
    utility = action_key(1.0, TransitionRank.UTILITY_ARM, "main", event)
    assert heal[1] is TransitionRank.RECOVERY
    assert debuff[1] is TransitionRank.DEBUFF_ARM
    assert utility[1] is TransitionRank.UTILITY_ARM
    assert debuff < heal < utility
    assert action_key(1.0, TransitionRank.DAMAGE, "main", event)[1] is (
        TransitionRank.DAMAGE
    )
    assert action_key(1.0, TransitionRank.REACTIVE, "main", event) == action_key(
        1.0, TransitionRank.LATE_BARRIER, "main", event
    )


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

    Subscript indices are skipped: the ``1`` in ``event["_sk"][1]`` is a
    tuple position, not a phase anybody chose, and a guard that cannot tell
    the two apart reports a sort-key read as an offending float.
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
    ending in ``sort_key``, a ``key=lambda`` body, and a tuple handed
    positionally to whatever index a definition puts ``sort_key`` at.  The
    name suffix rather than the bare name, so a key lifted into a local to
    be handed to two consumers stays in the population.
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
                    and target.id.endswith("sort_key")
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


def _folds_to_slot(node: ast.expr, bound: Mapping[str, list[ast.expr]]) -> bool:
    """Whether a sort-key element 1 is ``ordering_slot(...)``, name-resolved."""
    if isinstance(node, ast.Name):
        return any(_folds_to_slot(value, bound) for value in bound.get(node.id, ()))
    return isinstance(node, ast.Call) and _callee_name(node.func) == "ordering_slot"


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
        "action_from_event": 1,
        "action_key": 1,
        "classify_event_kind": 1,
        "classify_prefetched": 1,
    }
    assert dict(rules.sort_key_arg) == {
        "SurvivalAction": 0,
        "_enriched_damage_event": 13,
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
        (0.0, TransitionRank.DAMAGE, 0),
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
        None,
        None,
        False,
        False,
        None,
        None,
    )
    assert action.phase is TransitionRank.DAMAGE
    assert SurvivalAction().phase is TransitionRank.DAMAGE


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


def test_the_float_projection_is_deleted_from_the_tree() -> None:
    """``legacy_phase`` is gone, not merely unused (criterion 7).

    An AST scan rather than a text one: the survival package's docstring
    still tells the story of a name that left its ``__all__``, and a
    grep-shaped guard would have to be weakened to admit that sentence —
    which is how a guard stops being able to fail.
    """
    offenders: list[tuple[str, int]] = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            spellings = (
                getattr(node, "id", ""),
                getattr(node, "attr", ""),
                getattr(node, "name", ""),
                getattr(node, "asname", ""),
            )
            if "legacy_phase" in spellings:
                offenders.append((path.name, getattr(node, "lineno", 0)))
    assert offenders == []
    assert not hasattr(actions_module, "legacy_phase")


def test_the_action_carries_a_rank_and_not_a_float() -> None:
    """The phase field's type is the vocabulary, not a number.

    ``SurvivalAction`` is a NamedTuple under ``from __future__ import
    annotations``, so the annotation is the deferred source text — which is
    exactly what a reader greps for when asking what a phase *is*.
    """
    annotation = SurvivalAction.__annotations__["phase"]
    assert getattr(annotation, "__forward_arg__", annotation) == "TransitionRank"
    assert isinstance(SurvivalAction().phase, TransitionRank)


def test_the_inline_sort_tuples_fold_the_way_action_key_does() -> None:
    """The hand-written sort keys consume the same fold.

    ``program/compile.py`` writes ``action_key``'s output by hand for its hot
    loop, so element 1 must be an ``ordering_slot(...)`` — directly or
    through one bound name.  A bare rank there would sort a reactive
    strike-back after a late barrier that ``action_key`` ties, and only the
    compiled-vs-receipt equivalence suite could ever see it.

    ``program/compile.py`` is the only file that writes one by hand; the
    declared entry point ``compile_program`` calls ``action_key`` instead,
    which is the stronger version of this guard — a key that is never
    rebuilt cannot fold its rank the wrong way.
    """
    compile_py = PROGRAM / "compile.py"
    rules = _population_rules(_population())
    tuples = _sort_key_tuples(ast.parse(compile_py.read_text(encoding="utf-8")), rules)
    assert tuples, "the hot loop's hand-written keys left the population"
    for tup, slot in tuples:
        assert _folds_to_slot(tup.elts[1], rules.bound), (slot, tup.elts[1].lineno)


def test_an_arming_rank_still_classifies_as_a_recovery() -> None:
    """The 1.0 fall-through, preserved: a named set decides, not the fold.

    Every rank that shared the deleted 1.0 float still reaches the recovery
    branch, and a rank one slot earlier still reaches the damage path.
    S6 split the *ordering* of those three ranks and deliberately left
    their *classification* alone: an unlisted kind arming at
    ``UTILITY_ARM`` is the engine's own self-heal, and reclassifying it as
    a utility no-op would drop a heal — a second behaviour change with no
    fixture and no prediction.  Pinned here so that stays a decision.
    """
    event = {"kind": "champion_ability", "amount": 10.0}
    for rank in (
        TransitionRank.DEBUFF_ARM,
        TransitionRank.RECOVERY,
        TransitionRank.UTILITY_ARM,
    ):
        assert classify_event_kind(event, rank) is ActionKind.HEAL
    assert classify_event_kind(event, TransitionRank.LATE_BARRIER) is (
        ActionKind.PLAIN_DAMAGE
    )


def test_the_classified_ladder_reproduces_the_slots_it_replaced() -> None:
    """The three legacy branches — -2.0, -1.0 and the 1.0 fall-through.

    The fall-through is the load-bearing one: an unlisted kind still arms
    at the rank the open ``else 1.0`` gave it.  What S6 changed is that the
    three ranks the 1.0 covered no longer answer to one slot, so the kind
    ladder's answers are read one by one instead of as a single fold.
    """
    assert support_transition_rank({"kind": "stasis"}) is TransitionRank.STATE_GRANT
    assert support_transition_rank({"kind": "shield"}) is TransitionRank.BARRIER_GRANT
    by_kind = {
        "heal": TransitionRank.RECOVERY,
        "regen": TransitionRank.RECOVERY,
        "damage_modifier": TransitionRank.DEBUFF_ARM,
        "stat_buff": TransitionRank.DEBUFF_ARM,
        "movement": TransitionRank.UTILITY_ARM,
        "on_hit_magic": TransitionRank.UTILITY_ARM,
        "anything_unlisted": TransitionRank.UTILITY_ARM,
    }
    for kind, rank in by_kind.items():
        assert support_transition_rank({"kind": kind}) is rank
        assert ordering_slot(rank) is rank


def test_a_packet_may_declare_a_rank_but_not_an_ordering() -> None:
    """The declaration overrides the kind, and only enum members are legal."""
    late = {"kind": "shield", SUPPORT_RANK_KEY: TransitionRank.LATE_BARRIER}
    assert support_transition_rank(late) is TransitionRank.LATE_BARRIER
    assert ordering_slot(support_transition_rank(late)) is (TransitionRank.LATE_BARRIER)
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


def test_every_packet_author_declares_a_named_rank() -> None:
    """The population that used to write an open float, now named.

    Four of these were named before the last author converted (three at 0A,
    plus C4's Abyssal Mask Unmake); the rest are the retired ``_priority``
    floats, each carrying the rank
    ``survival.actions._rank_from_legacy_float`` translated its float into,
    so the walk's total order is unchanged and only the spelling moved.  The
    census is pinned rather than counted because a *new* declaration is a
    reordering somebody must argue for, and a rank that appears here without
    one is the argument going missing.
    """
    declared = _declared_ranks(ITEM_SUPPORT) + _declared_ranks(TIMELINE)
    assert sorted(declared) == [
        # Abyssal Mask's Unmake aura, Tear's Manaflow grant, Fimbulwinter's
        # denial receipt and its late self shield.
        ("item_support_effects.py", "AURA_ARM"),
        ("item_support_effects.py", "BARRIER_GRANT"),
        ("item_support_effects.py", "DAMAGE"),
        ("item_support_effects.py", "DAMAGE"),
        ("item_support_effects.py", "LATE_BARRIER"),
        # Guardian's reactive shield and Glacial Augment's ally reduction;
        # Glacial's icy zone and Stormraider's surge; Aftershock's
        # resistances; Grasp's permanent health; Eclipse's self shield and
        # Thick Skin's grey-health press (both barriers a packet already
        # landed pays for, so both arm after the damage).
        ("participant_timeline.py", "AURA_ARM"),
        ("participant_timeline.py", "AURA_ARM"),
        ("participant_timeline.py", "BARRIER_GRANT"),
        ("participant_timeline.py", "BARRIER_GRANT"),
        ("participant_timeline.py", "DAMAGE"),
        ("participant_timeline.py", "DEBUFF_ARM"),
        ("participant_timeline.py", "LATE_BARRIER"),
        ("participant_timeline.py", "LATE_BARRIER"),
    ]


# ---------------------------------------------------------------------------
# Phase 4 S6 — the split, named reordering by named reordering
#
# S6's diff is bounded by prediction (criterion 8): same-timestamp arming
# reorderings only, each with a fixture that names it.  The four below are
# that enumeration.  Two of them were *measured* on the pre-edit tree before
# the baselines were read — the population S6c1's commit body declares — and
# they carry the scenario and the source that produced them, so a reader can
# find the same pair again rather than trust the sentence.
# ---------------------------------------------------------------------------


def _armed_at(rank: TransitionRank, source: str, time: float = 0.0):
    """One authored packet's sort key at *rank*, all tie-breaks held equal.

    Everything after element 1 is identical between two calls with the same
    *source*, which is exactly the position the collapsed slot used to push
    the decision down to.
    """
    event = {
        "sequence": 0,
        "attacker": "main",
        "_event_id": f"{source}:{rank.name}",
        "source": source,
    }
    return action_key(time, rank, "main", event)


def test_s6_reorders_a_stat_buff_ahead_of_a_same_timestamp_utility() -> None:
    """The ``syndra_mandate_3champ`` shape: Bandlepipes — Fanfare at t=0.

    Measured on the pre-edit tree: 8 of that scenario's 775 walks held this
    exact inversion — the Fanfare utility packet resolving before the
    Fanfare stat buff, because both rode ``DEBUFF_ARM``'s slot and the
    decision fell through to the components after it.  A stat buff is a
    state change the packets at its timestamp read; it arms first now.
    """
    source = "Bandlepipes — Fanfare"
    stat_buff = _armed_at(TransitionRank.DEBUFF_ARM, source)
    utility = _armed_at(TransitionRank.UTILITY_ARM, source)
    assert support_transition_rank({"kind": "stat_buff"}) is TransitionRank.DEBUFF_ARM
    assert support_transition_rank({"kind": "movement"}) is TransitionRank.UTILITY_ARM
    assert stat_buff[1] is TransitionRank.DEBUFF_ARM
    assert utility[1] is TransitionRank.UTILITY_ARM
    assert stat_buff < utility


def test_s6_reorders_a_debuff_ahead_of_a_same_timestamp_recovery() -> None:
    """The ``cassiopeia_5champ`` shape: Vile Decay against Twin Fang's heal.

    Measured on the pre-edit tree: 3 of that scenario's 967 walks held this
    inversion — the Twin Fang heal resolving before the Bloodletter's Curse
    ``damage_modifier`` armed at the same timestamp.  The debuff arms
    first now, which is the ordering the class docstring states and the
    collapsed float could not express.
    """
    debuff = _armed_at(TransitionRank.DEBUFF_ARM, "Bloodletter's Curse — Vile Decay")
    heal = _armed_at(TransitionRank.RECOVERY, "Bloodletter's Curse — Vile Decay")
    assert (
        support_transition_rank({"kind": "damage_modifier"})
        is TransitionRank.DEBUFF_ARM
    )
    assert support_transition_rank({"kind": "heal"}) is TransitionRank.RECOVERY
    assert debuff < heal


def test_s6_reorders_a_recovery_ahead_of_a_same_timestamp_on_hit_magic() -> None:
    """The third pair: an on-hit magic packet arms at ``UTILITY_ARM``.

    No baseline scenario holds this collision today, which is exactly why
    it needs a fixture: an ordering nothing exercises is an ordering that
    changes silently the first time something does.
    """
    heal = _armed_at(TransitionRank.RECOVERY, "Nashor's Tooth")
    on_hit = _armed_at(TransitionRank.UTILITY_ARM, "Nashor's Tooth")
    assert support_transition_rank({"kind": "on_hit_magic"}) is (
        TransitionRank.UTILITY_ARM
    )
    assert heal < on_hit


def test_s6_leaves_the_aura_and_the_late_barrier_exactly_where_c4_put_them() -> None:
    """The two orderings S6 must *not* touch, asserted rather than assumed.

    ``AURA_ARM`` resolves before the damage at its timestamp (C4's
    correction) and ``LATE_BARRIER``/``REACTIVE`` still share a slot.
    """
    assert _armed_at(TransitionRank.AURA_ARM, "Abyssal Mask — Unmake") < _armed_at(
        TransitionRank.DAMAGE, "Abyssal Mask — Unmake"
    )
    assert (
        _armed_at(TransitionRank.REACTIVE, "Thornmail")[1]
        is _armed_at(TransitionRank.LATE_BARRIER, "Thornmail")[1]
        is TransitionRank.LATE_BARRIER
    )


def test_s6_publishes_no_new_phase_name_and_bumps_no_schema() -> None:
    """Payload neutrality, asserted (stage table, criterion 5).

    All three split ranks keep the published name they had, so the derived
    phase list is byte-identical across the split and D-63's chain does not
    advance: S6 takes no version.  (S9 took 4, the rune page took 5 and the
    survival row's certification fields took 6; none of them is S6's, which
    is the point — the pin moves when *another* change publishes something,
    never when this one does.)
    """
    from src.calculator.capabilities import (
        CAPABILITY_SCHEMA_VERSION,
        PARTICIPANT_LEDGER_CONTRACT,
    )
    from src.calculator.survival.actions import public_phase

    assert public_phase(TransitionRank.DEBUFF_ARM) == "state_transition"
    assert public_phase(TransitionRank.UTILITY_ARM) == "state_transition"
    assert public_phase(TransitionRank.RECOVERY) == "healing_and_regeneration"
    assert PARTICIPANT_LEDGER_CONTRACT["phases"] == [
        "state_transition",
        "shield_or_temporary_health",
        "persistent_aura_arming",
        "damage_and_mitigation",
        "reactive_effect",
        "healing_and_regeneration",
        "death_or_terminal_cutoff",
    ]
    # 8 is the stat-surface labels, which touch no phase name.
    assert CAPABILITY_SCHEMA_VERSION == 8


def test_s6_moved_the_ordering_and_not_the_classification() -> None:
    """The one behaviour the split deliberately holds still.

    ``classify_prefetched`` read the ordering fold to decide which arming
    ranks classify as a recovery.  Splitting the fold would have silently
    reclassified every ``UTILITY_ARM`` engine self-heal as a utility no-op
    — a dropped heal with no fixture and no prediction — so the set is
    named in the module instead, and this is the assertion that the two
    questions now have two answers.
    """
    assert actions_module._RECOVERY_CLASSIFIED_RANKS == frozenset(
        {
            TransitionRank.DEBUFF_ARM,
            TransitionRank.RECOVERY,
            TransitionRank.UTILITY_ARM,
        }
    )
    # ...and it is no longer expressible as the fold's output, which is what
    # makes naming it load-bearing rather than stylistic.
    assert {
        rank
        for rank in TransitionRank
        if ordering_slot(rank) is TransitionRank.DEBUFF_ARM
    } == {TransitionRank.DEBUFF_ARM}
