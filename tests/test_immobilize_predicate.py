"""One immobilize predicate, one home (C5, D-08).

Force of Nature's Steadfast counts *immobilizing* crowd control, and the
walk decided what that meant with its own five-member literal — a sixth of
the vocabulary the rest of the calculator already shared through
``ability_spec.IMMOBILIZING_CC_KINDS``.  A module authoring ``charm``,
``taunt`` or ``airborne`` armed Imperial Mandate's Command and Fimbulwinter's
Everlasting and left Steadfast counting one stack instead of two: the same
predicate, answered two ways, with no error anywhere.

The tests below show every effect of the widening.  All fifteen kinds grant
the immobilize stack count, a slow still grants exactly one, a reviewed
``none`` grants one, and two source assertions keep the answer in one home.
"""

import ast
from pathlib import Path

import pytest

from src.calculator import survival
from src.calculator.ability_spec import CC_KIND_VOCABULARY, IMMOBILIZING_CC_KINDS
from src.calculator.data_fetcher import get_item_by_name
from src.calculator.defensive_effects import resolve_starting_defenses
from src.calculator.item_effects import required_effect_value
from src.calculator.participant_timeline import Combatant, _simulate_survival
from src.calculator.survival.actions import survival_action_from_event

# The literal C5 retired: the five kinds the walk itself decided were
# immobilizing.  Pinned here, not read from the tree, because it is the
# thing that no longer exists — and because the widening's size is what
# makes these tests green over something (D-26).
RETIRED_WALK_LITERAL = frozenset(
    {"immobilize", "stun", "root", "knockup", "suppression"}
)

# Steadfast's own numbers, read from the sourced accessors (repo rule 5).
FORCE_IMMOBILIZE_STACKS = int(
    required_effect_value("Force of Nature", "steadfast_immobilize_stacks")
)
FORCE_MAX_STACKS = int(required_effect_value("Force of Nature", "steadfast_max_stacks"))

SURVIVAL_MODULES = tuple(sorted(Path(survival.__file__).parent.rglob("*.py")))


def _force_of_nature_target() -> Combatant:
    """A Steadfast holder with no other defensive item in play."""
    stats = {
        "health": 5000.0,
        "armor": 30.0,
        "magic_resistance": 40.0,
        "bonus_armor": 0.0,
        "bonus_magic_resistance": 0.0,
        "is_melee": False,
    }
    return Combatant(
        participant_id="target",
        team="enemy",
        champion_data={"name": "Ahri"},
        level=18,
        items=(get_item_by_name("Force of Nature"),),
        stats=stats,
        defenses=resolve_starting_defenses(
            "Ahri", 18, stats, [{"name": "Force of Nature"}]
        ),
    )


def _attacker() -> Combatant:
    from types import SimpleNamespace

    return Combatant(
        participant_id="source",
        team="main",
        champion_data={"name": "source"},
        level=1,
        items=(),
        stats={"health": 100.0},
        defenses=SimpleNamespace(
            magic_shield=0.0,
            physical_shield=0.0,
            general_shield=0.0,
            healing_received_multiplier=1.0,
        ),
    )


def _one_magic_cast(**markers) -> dict:
    """One champion magic packet into the Steadfast holder at ``t = 0``."""
    event = {
        "time": 0.0,
        "damage": 50.0,
        "damage_type": "magic",
        "attacker": "source",
        "target": "target",
        "source_key": "Q",
        "sequence": 0,
        "_event_id": "steadfast-0",
        "_baseline_effective_mr": 40.0,
    }
    event.update(markers)
    return event


def _stacks_after_one_cast(**markers) -> tuple[int, dict]:
    """Steadfast's stack count and its receipt row after one marked cast."""
    result = _simulate_survival(
        [_attacker(), _force_of_nature_target()],
        {"target": [_one_magic_cast(**markers)]},
        {},
        {},
        10.0,
    )
    force = result["target"]["force_of_nature"]
    return int(force["stacks"]), force["events"][-1]


def _string_collection_literals(tree: ast.AST) -> list[tuple[int, frozenset[str]]]:
    """Every set/list/tuple of string constants, with its line."""
    literals: list[tuple[int, frozenset[str]]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Set, ast.List, ast.Tuple)):
            continue
        members = {
            element.value
            for element in node.elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        }
        if members:
            literals.append((node.lineno, frozenset(members)))
    return literals


class TestTheWidenedPredicateReachesSteadfast:
    """Criterion 13's first half, one kind at a time."""

    @pytest.mark.parametrize("cc_kind", sorted(IMMOBILIZING_CC_KINDS))
    def test_every_immobilizing_kind_grants_the_immobilize_stack_count(self, cc_kind):
        """All fifteen, not the five the walk used to know."""
        stacks, row = _stacks_after_one_cast(cc_kind=cc_kind)
        assert stacks == FORCE_IMMOBILIZE_STACKS, (
            f"D-08: cc_kind {cc_kind!r} is in IMMOBILIZING_CC_KINDS, so "
            "Steadfast counts it as an immobilize like every other consumer"
        )
        assert row["immobilized"] is True

    def test_a_slow_still_grants_exactly_one_stack(self):
        """A slow is crowd control that was never an immobilize."""
        stacks, row = _stacks_after_one_cast(cc_kind="slow")
        assert stacks == 1
        assert row["immobilized"] is False

    def test_a_reviewed_no_cc_cast_still_grants_exactly_one_stack(self):
        """``none`` is a reviewed statement, not a missing marker."""
        stacks, row = _stacks_after_one_cast(cc_kind="none")
        assert stacks == 1
        assert row["immobilized"] is False

    def test_an_unmarked_cast_still_grants_exactly_one_stack(self):
        """The unmarked majority is where the baselines live."""
        stacks, row = _stacks_after_one_cast()
        assert stacks == 1
        assert row["immobilized"] is False

    def test_the_legacy_flags_still_mark_an_immobilize(self):
        """``immobilized`` / ``crowd_control`` / ``hard_cc`` are untouched."""
        for marker in ("immobilized", "crowd_control", "hard_cc"):
            stacks, row = _stacks_after_one_cast(**{marker: True})
            assert stacks == FORCE_IMMOBILIZE_STACKS, marker
            assert row["immobilized"] is True


class TestTheTypedActionCarriesTheAnswer:
    """The field the walk reads, without a walk in the way."""

    @pytest.mark.parametrize("cc_kind", sorted(CC_KIND_VOCABULARY))
    def test_the_action_marks_exactly_the_immobilizing_vocabulary(self, cc_kind):
        action = survival_action_from_event(
            {"time": 0.0, "damage": 10.0, "damage_type": "magic", "cc_kind": cc_kind},
            0.0,
            0,
            {},
        )
        assert action.immobilized is (cc_kind in IMMOBILIZING_CC_KINDS)

    def test_a_padded_kind_reads_like_the_shared_home_reads_it(self):
        """``champions/engine`` validates ``lower().strip()``; so does this.

        Every other consumer of the vocabulary strips before the membership
        test, so a module authoring ``" stun"`` armed Command and left
        Steadfast blind — the same divergence one character wide.
        """
        action = survival_action_from_event(
            {"time": 0.0, "damage": 10.0, "damage_type": "magic", "cc_kind": " Stun "},
            0.0,
            0,
            {},
        )
        assert action.immobilized is True


class TestOneHome:
    """Criterion 13's second half: no second immobilize literal in the walk."""

    def test_the_widening_is_ten_kinds_and_the_retired_five_are_a_subset(self):
        """D-26: the population this correction moved is not empty."""
        assert RETIRED_WALK_LITERAL < IMMOBILIZING_CC_KINDS
        assert len(IMMOBILIZING_CC_KINDS) == 15
        assert len(IMMOBILIZING_CC_KINDS - RETIRED_WALK_LITERAL) == 10

    def test_no_survival_module_holds_a_second_immobilize_kind_set(self):
        """A literal naming two of the kinds is the retired shape returning."""
        offenders = []
        for module in SURVIVAL_MODULES:
            tree = ast.parse(module.read_text(encoding="utf-8"))
            for lineno, members in _string_collection_literals(tree):
                if len(members & IMMOBILIZING_CC_KINDS) >= 2:
                    offenders.append(f"{module.name}:{lineno} {sorted(members)}")
        assert offenders == [], (
            "D-08: survival/ decides what an immobilize is again.  The one "
            "home is ability_spec.IMMOBILIZING_CC_KINDS"
        )

    def test_no_survival_module_tests_a_cc_kind_against_a_literal(self):
        """The only right-hand operand for a ``cc_kind`` test is the set."""
        offenders = []
        for module in SURVIVAL_MODULES:
            tree = ast.parse(module.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Compare):
                    continue
                if not any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops):
                    continue
                if "cc_kind" not in ast.unparse(node.left):
                    continue
                for comparator in node.comparators:
                    if not isinstance(comparator, ast.Name):
                        offenders.append(f"{module.name}:{node.lineno}")
                    elif comparator.id != "IMMOBILIZING_CC_KINDS":
                        offenders.append(f"{module.name}:{node.lineno}")
        assert offenders == [], (
            "D-08: a cc_kind membership test in survival/ names something "
            "other than ability_spec.IMMOBILIZING_CC_KINDS"
        )

    def test_actions_imports_the_shared_vocabulary(self):
        """The import is the handshake the two assertions above police."""
        body = Path(survival.actions.__file__).read_text(encoding="utf-8")
        assert "IMMOBILIZING_CC_KINDS" in body
