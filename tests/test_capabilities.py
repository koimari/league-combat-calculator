"""Front-door tests for the public capability contract."""

import ast
from pathlib import Path

import pytest

from src.calculator.capabilities import (
    CAPABILITY_SCHEMA_VERSION,
    PARTICIPANT_LEDGER_CONTRACT,
    _ledger_phases,
    public_capability_contract,
)
from src.calculator.survival.actions import (
    ActionKind,
    TransitionRank,
    public_phase,
    support_transition_rank,
)

ROOT = Path(__file__).parents[1]
ACTIONS = ROOT / "src" / "calculator" / "survival" / "actions.py"

# The six names the API publishes today, byte for byte.  The derivation must
# reproduce this list; it does not get to define it.
PUBLISHED_PHASES = [
    "state_transition",
    "shield_or_temporary_health",
    "damage_and_mitigation",
    "reactive_effect",
    "healing_and_regeneration",
    "death_or_terminal_cutoff",
]


def test_capability_contract_exposes_named_participant_and_catalogue_fields() -> None:
    contract = public_capability_contract(
        input_limits={"level": (1.0, 18.0)},
        max_rotations=6,
        champion_option_count=2,
        item_option_count=3,
    )

    assert contract["schema_version"] == 1
    assert contract["participants"]["main"]["fields"]["champion"]["supported"]
    assert contract["catalogs"]["champion_options"]["count"] == 2
    assert contract["catalogs"]["item_options"]["count"] == 3


def test_the_published_phase_list_is_derived_from_the_transition_ladder() -> None:
    """Six hand-written strings become one projection of the enum."""
    assert PARTICIPANT_LEDGER_CONTRACT["phases"] == PUBLISHED_PHASES
    assert _ledger_phases() == PUBLISHED_PHASES
    assert PARTICIPANT_LEDGER_CONTRACT["phases"] == _ledger_phases()


def test_the_derivation_does_not_move_the_schema_version() -> None:
    """Deriving an identical payload is not a change clients can see."""
    assert CAPABILITY_SCHEMA_VERSION == 1


def test_public_phase_is_total_over_the_ladder() -> None:
    """Every rank publishes under a name; none silently drops out."""
    assert {public_phase(rank) for rank in TransitionRank} == set(PUBLISHED_PHASES)
    for rank in TransitionRank:
        assert public_phase(rank) in PUBLISHED_PHASES


def test_the_producer_less_rank_carries_the_name_no_transition_emits() -> None:
    """``death_or_terminal_cutoff`` is published by ``TERMINAL`` alone."""
    assert public_phase(TransitionRank.TERMINAL) == "death_or_terminal_cutoff"
    carriers = [
        rank
        for rank in TransitionRank
        if public_phase(rank) == "death_or_terminal_cutoff"
    ]
    assert carriers == [TransitionRank.TERMINAL]


def test_no_producer_emits_the_terminal_rank() -> None:
    """``TERMINAL`` is a published name, never a transition a walk applies.

    Two halves: no module outside the ladder's own declaration names it, and
    the one classifier that turns an authored packet into a rank cannot
    return it for any kind in the action vocabulary — including kinds it has
    never seen.
    """
    namers = sorted(
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "src").rglob("*.py")
        if "TransitionRank.TERMINAL" in path.read_text(encoding="utf-8")
    )
    assert namers == [ACTIONS.relative_to(ROOT).as_posix()]

    kinds = [kind.value for kind in ActionKind] + [
        "heal",
        "regen",
        "invulnerability",
        "unlisted_kind",
        "",
    ]
    for kind in kinds:
        assert support_transition_rank({"kind": kind}) is not TransitionRank.TERMINAL


def test_the_ladder_declares_terminal_last_and_only_as_a_published_name() -> None:
    """Inside the ladder, TERMINAL appears only as a projection-table key."""
    tree = ast.parse(ACTIONS.read_text(encoding="utf-8"))
    mentions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        if getattr(node.value, "id", "") == "TransitionRank"
        if node.attr == "TERMINAL"
    ]
    # One key in the legacy-float table, one in the published-name table.
    assert len(mentions) == 2
    assert list(TransitionRank)[-1] is TransitionRank.TERMINAL


def test_a_rank_without_a_published_name_raises(monkeypatch) -> None:
    """A new rank must be published deliberately, not defaulted."""
    from src.calculator.survival import actions as actions_module

    published = dict(actions_module._PUBLIC_PHASES)
    del published[TransitionRank.REACTIVE]
    monkeypatch.setattr(actions_module, "_PUBLIC_PHASES", published)
    with pytest.raises(KeyError, match="REACTIVE"):
        public_phase(TransitionRank.REACTIVE)
