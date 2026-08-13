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

# The names the API publishes, byte for byte, in ledger order.  The
# derivation must reproduce this list; it does not get to define it.
#
# Six at 0A.  C4 inserted ``persistent_aura_arming`` third — the ledger slot
# between the barriers and the damage, where an aura already in force is
# armed — and that is the change version 2 named.
PUBLISHED_PHASES = [
    "state_transition",
    "shield_or_temporary_health",
    "persistent_aura_arming",
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

    assert contract["schema_version"] == 4
    assert contract["participants"]["main"]["fields"]["champion"]["supported"]
    assert contract["catalogs"]["champion_options"]["count"] == 2
    assert contract["catalogs"]["item_options"]["count"] == 3


def test_the_published_phase_list_is_derived_from_the_transition_ladder() -> None:
    """Six hand-written strings become one projection of the enum."""
    assert PARTICIPANT_LEDGER_CONTRACT["phases"] == PUBLISHED_PHASES
    assert _ledger_phases() == PUBLISHED_PHASES
    assert PARTICIPANT_LEDGER_CONTRACT["phases"] == _ledger_phases()


def test_the_aura_rank_publishes_its_own_name_in_ledger_order() -> None:
    """C4's seventh name, and the reason it is not folded into an existing one.

    The list keeps each name's first appearance in declaration order, so
    folding the aura slot into ``state_transition`` — which ``STATE_GRANT``
    already published first — would leave the one phase that resolves
    between the barriers and the damage published nowhere.
    """
    assert public_phase(TransitionRank.AURA_ARM) == "persistent_aura_arming"
    assert PUBLISHED_PHASES.index("persistent_aura_arming") == 2
    assert PUBLISHED_PHASES[1] == public_phase(TransitionRank.BARRIER_GRANT)
    assert PUBLISHED_PHASES[3] == public_phase(TransitionRank.DAMAGE)
    assert public_phase(TransitionRank.AURA_ARM) != public_phase(
        TransitionRank.DEBUFF_ARM
    )


def test_the_published_list_moved_the_schema_version_with_it() -> None:
    """D-63: the version names a change to the payload, and only that.

    0A derived the list at version 1 with the payload byte-identical; C4
    published a seventh name and took version 2; Phase 3's 3.8 coverage flip
    took 3 for a different published payload — the coverage record, whose
    refusal is now spelled ``withheld`` and whose status is computed from
    declarations.  Every value in the chain has exactly one owning commit,
    which is why the phase list is still seven names at version 3.
    """
    assert CAPABILITY_SCHEMA_VERSION == 4
    assert len(PARTICIPANT_LEDGER_CONTRACT["phases"]) == 7


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
    # One key, in the published-name table.  It was two until Phase 4 S2
    # deleted the float projection whose table held the other.
    assert len(mentions) == 1
    assert list(TransitionRank)[-1] is TransitionRank.TERMINAL


def test_a_rank_without_a_published_name_raises(monkeypatch) -> None:
    """A new rank must be published deliberately, not defaulted."""
    from src.calculator.survival import actions as actions_module

    published = dict(actions_module._PUBLIC_PHASES)
    del published[TransitionRank.REACTIVE]
    monkeypatch.setattr(actions_module, "_PUBLIC_PHASES", published)
    with pytest.raises(KeyError, match="REACTIVE"):
        public_phase(TransitionRank.REACTIVE)
