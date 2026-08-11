"""The front door for ``item_behavior`` — the closed unions and their leaf-ness.

Two things are load-bearing here and neither is obvious from reading the
module.  First, ``item_behavior`` is a *leaf*: it imports ``value_ref`` and
``ability_spec`` and nothing else, which is what lets ``damage``,
``survival/*``, ``defensive_effects`` and ``item_support_effects`` all depend
on it.  Second, being a leaf forced :class:`TriggerEvent` to be declared here
rather than re-exported from the trigger bus, so this suite is where that
local enum is proved to be a *view* of ``trigger_stream.Stream`` rather than
a second vocabulary.
"""

import ast
from pathlib import Path

import pytest

from src.calculator.ability_spec import AttackClass, Authority, DamageClass, Disposition
from src.calculator.item_behavior import (
    Always,
    Attribution,
    BehaviorRule,
    BehaviorRuleError,
    BuildContext,
    Compilable,
    DeltaAmpRule,
    EngineLane,
    Fixed,
    KernelField,
    Persist,
    Pool,
    RULE_FAMILY_COUNT,
    ReceiptOnly,
    RuleFamily,
    SUBJECT_AUTHORITY,
    Subject,
    TRIGGER_STREAM,
    TriggerEvent,
    Typing,
    ZeroPolicy,
    is_value_reference,
    policy_values,
    validate_rule,
)
from src.calculator.trigger_stream import Stream
from src.calculator.value_ref import Const, SourceReceipt

MODULE_PATH = Path(__file__).parents[1] / "src" / "calculator" / "item_behavior.py"

RECEIPT = SourceReceipt("https://example.test/Item", 1, "2026-01-01T00:00:00Z")


def _rule(**overrides: object) -> BehaviorRule:
    """A minimal valid delta-amp rule, for the negatives to break one field of."""
    payload = DeltaAmpRule(
        pool=Pool.ALL_EVENTS,
        activation=Always(),
        consumption=Persist(),
        magnitude=Fixed(Const(1, "unit_scale")),
        attribution=Attribution.HOLDER,
        typing=Typing(frozenset(DamageClass), frozenset(AttackClass)),
        subject=Subject.HOLDER,
        lane_chain_rank=1,
    )
    fields: dict[str, object] = {
        "family": RuleFamily.DELTA_AMP,
        "owner": "Test Item",
        "mechanic_id": "test_item.amp",
        "payload": payload,
        "compilability": Compilable(),
        "receipt": RECEIPT,
        "zero_policy": ZeroPolicy(Disposition.MEASURED, "a formula produced it"),
    }
    fields.update(overrides)
    return BehaviorRule(**fields)  # type: ignore[arg-type]


def test_the_family_union_is_closed_at_eighteen() -> None:
    """Closed means counted: a nineteenth member is a decision, not a commit."""
    assert len(RuleFamily) == RULE_FAMILY_COUNT == 18
    assert len({family.value for family in RuleFamily}) == 18


def test_the_engine_lane_vocabulary_is_not_spelled_lane() -> None:
    """D-45: Phase 1 owns ClaimLane, Phase 3 owns EngineLane."""
    assert {lane.name for lane in EngineLane} == {
        "PAIR_ENGINE",
        "RECEIPT_WALK",
        "COMPILED_SCORE_WALK",
        "DEFENSE_RESOLVER",
        "STAT_RESOLVER",
    }


def test_item_behavior_is_a_leaf() -> None:
    """The whole dependency argument rests on this one import list."""
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    intra_package = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module
    }
    assert intra_package == {"ability_spec", "value_ref"}


def test_every_trigger_names_a_stream_the_bus_carries() -> None:
    """The local enum is a view of Phase 2's Stream, not a second vocabulary."""
    assert frozenset(TRIGGER_STREAM) == frozenset(TriggerEvent)
    assert set(TRIGGER_STREAM.values()) <= {stream.name for stream in Stream}


def test_a_roster_scoped_subject_is_incompatible_with_pair_only() -> None:
    """The authority rule, as a table a validator can read."""
    assert Authority.PAIR_ONLY not in SUBJECT_AUTHORITY[Subject.ANY_ATTACKER]
    assert Authority.PAIR_ONLY not in SUBJECT_AUTHORITY[Subject.ALLY]
    assert SUBJECT_AUTHORITY[Subject.HOLDER] == frozenset(Authority)
    assert frozenset(SUBJECT_AUTHORITY) == frozenset(Subject)


def test_the_typing_axis_bans_empty_means_all() -> None:
    """D-04: both class sets are required and neither may be empty."""
    with pytest.raises(BehaviorRuleError, match="damage_classes"):
        Typing(frozenset(), frozenset(AttackClass))
    with pytest.raises(BehaviorRuleError, match="attack_classes"):
        Typing(frozenset(DamageClass), frozenset())


def test_a_zero_policy_is_required_and_carries_a_reason() -> None:
    """D-24: the invariant at rule granularity, with no default to fall through."""
    with pytest.raises(BehaviorRuleError, match="reason"):
        ZeroPolicy(Disposition.STRUCTURAL_ZERO, "   ")
    with pytest.raises(BehaviorRuleError):
        ZeroPolicy("STRUCTURAL_ZERO", "a string is not a disposition")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        _rule_without_zero_policy()


def _rule_without_zero_policy() -> BehaviorRule:
    """Constructing a rule with no zero_policy is a TypeError, not a default."""
    return BehaviorRule(  # type: ignore[call-arg]
        family=RuleFamily.DELTA_AMP,
        owner="Test Item",
        mechanic_id="test_item.amp",
        payload=_rule().payload,
        compilability=Compilable(),
        receipt=RECEIPT,
    )


def test_a_valid_rule_validates() -> None:
    """The positive case, so every negative below is about one broken field."""
    validate_rule(_rule())


def test_a_payload_may_not_wear_another_familys_name() -> None:
    """A family and its payload type are one fact declared in one table."""
    with pytest.raises(BehaviorRuleError, match="belongs to"):
        validate_rule(_rule(family=RuleFamily.SUSTAIN))


def test_an_undeclared_payload_type_is_refused() -> None:
    """A payload PAYLOAD_FAMILY does not know is a family nobody assigned."""
    with pytest.raises(BehaviorRuleError, match="not a declared"):
        validate_rule(_rule(payload=object()))


def test_a_receipt_only_rule_states_its_cause() -> None:
    """A fallback with no reason is the silence this phase removes."""
    validate_rule(_rule(compilability=ReceiptOnly("the kernel cannot amp")))
    with pytest.raises(BehaviorRuleError, match="reason"):
        ReceiptOnly("  ")


def test_no_policy_field_is_a_callable_dict_or_open_string() -> None:
    """Criterion 6, over the one payload that exists at the skeleton."""
    for value in policy_values(_rule()):
        assert not callable(value) or isinstance(value, type)
        assert not isinstance(value, dict)
        assert not isinstance(value, str)


def test_every_magnitude_in_a_declaration_is_a_reference() -> None:
    """A frozen declaration may hold references, never numbers."""
    magnitude = _rule().payload.magnitude
    assert is_value_reference(magnitude.value)
    assert not is_value_reference(1.0)


def test_the_kernel_contract_carries_no_program_type() -> None:
    """A KernelField is value-typed; that is what keeps the dependency one-way."""
    field = KernelField(
        name="amp", value=0.07, lane=EngineLane.RECEIPT_WALK, rule_id="x"
    )
    assert isinstance(field.value, (float, int, bool, str))
    context = BuildContext(level=18, owner="Test Item", data_version=3)
    assert context.data_version == 3
