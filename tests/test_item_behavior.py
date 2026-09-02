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
import re
from dataclasses import replace
from pathlib import Path
from typing import get_args

import pytest

from src.calculator.ability_spec import AttackClass, Authority, DamageClass, Disposition
from src.calculator.item_behavior import (
    PAYLOAD_FAMILY,
    POLICY_IDENTIFIER_FIELDS,
    RESTRICTED_CHANNEL_PACKETS,
    RULE_FAMILY_COUNT,
    SUBJECT_AUTHORITY,
    TRIGGER_STREAM,
    Always,
    BehaviorRule,
    BehaviorRuleError,
    BonusTyping,
    BuildContext,
    Compilable,
    DeltaAmpRule,
    EngineLane,
    Fixed,
    KernelField,
    Persist,
    Pool,
    ReceiptOnly,
    ReceiptScope,
    RestrictedChannel,
    RuleFamily,
    RulePayload,
    Subject,
    TriggerEvent,
    Typing,
    UtilityDimension,
    ZeroPolicy,
    is_value_reference,
    policy_values,
    policy_walk,
    validate_rule,
)
from src.calculator.item_behavior_catalog import behavior_rules, rule_owners
from src.calculator.trigger_stream import Stream
from src.calculator.value_ref import Const, SourceReceipt

MODULE_PATH = Path(__file__).parents[1] / "src" / "calculator" / "item_behavior.py"

RECEIPT = SourceReceipt("https://example.test/Item", 1, "2026-01-01T00:00:00Z")

# One refusal, said once: a reason and the closed scope it belongs to.
_AMP_REFUSAL = ("the kernel cannot amp", ReceiptScope.SCORE_KERNEL_DAMAGE_MODIFIER)


def _rule(**overrides: object) -> BehaviorRule:
    """A minimal valid delta-amp rule, for the negatives to break one field of."""
    payload = DeltaAmpRule(
        pool=Pool.ALL_EVENTS,
        activation=Always(),
        consumption=Persist(),
        magnitude=Fixed(Const(1, "unit_scale")),
        typing=Typing(frozenset(DamageClass), frozenset(AttackClass)),
        bonus_typing=BonusTyping.SAME_AS_SOURCE,
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
    with pytest.raises(ValueError, match="reason"):
        ZeroPolicy(Disposition.STRUCTURAL_ZERO, "   ")
    with pytest.raises(ValueError):
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


def test_the_payload_union_names_every_payload_a_family_claims() -> None:
    """``RulePayload`` and ``PAYLOAD_FAMILY`` are one roster, not two.

    ``PAYLOAD_FAMILY`` is what the validator enforces and ``RulePayload`` is
    what the type of ``BehaviorRule.payload`` says; a payload in one and not
    the other is a shape the runtime accepts and the annotation denies, so a
    reader and a checker disagree about what a rule may hold.
    """
    assert set(PAYLOAD_FAMILY) - {BehaviorRule} == set(get_args(RulePayload))


def test_every_restricted_channel_names_its_packet_or_none() -> None:
    """``RESTRICTED_CHANNEL_PACKETS`` is total over ``RestrictedChannel``.

    ``on_hit_strike`` indexes the map with a rule's channel; a member missing
    from it is a ``KeyError`` mid-fight instead of a refusal at declaration.
    """
    assert set(RESTRICTED_CHANNEL_PACKETS) == set(RestrictedChannel)


def test_a_receipt_only_rule_states_its_cause() -> None:
    """A fallback with no reason is the silence this phase removes."""
    validate_rule(_rule(compilability=ReceiptOnly(*_AMP_REFUSAL)))
    with pytest.raises(BehaviorRuleError, match="reason"):
        ReceiptOnly("  ", ReceiptScope.SCORE_KERNEL_DAMAGE_MODIFIER)


def test_no_policy_field_is_a_callable_dict_or_open_string() -> None:
    """Criterion 6, reaching every field of the rule rather than its surface."""
    values = policy_values(_rule(compilability=ReceiptOnly(*_AMP_REFUSAL)))
    assert len(values) > 10
    for value in values:
        assert not callable(value)
        assert not isinstance(value, dict)
        assert not isinstance(value, str)


def test_every_compiled_rule_of_every_owner_holds_no_open_policy_field() -> None:
    """Criterion 6's *breadth*: every field of every rule the catalog compiles.

    The test above is depth over one hand-made rule and proves the walk
    reaches inside a payload; it says nothing about the declarations that
    actually ship.  This one is the population — every owner
    ``rule_owners()`` names, items and keystones alike, so a family migrated
    tomorrow is covered by the criterion the day it compiles rather than the
    day somebody remembers to extend a fixture.
    """
    checked = 0
    for owner in sorted(rule_owners()):
        for rule in behavior_rules(owner):
            checked += 1
            for site, value in policy_walk(rule).sites:
                assert not callable(value), f"{rule.mechanic_id}: {site}"
                assert not isinstance(value, dict), f"{rule.mechanic_id}: {site}"
                assert not isinstance(value, str), f"{rule.mechanic_id}: {site}"

    assert checked > 100, "the catalog compiled almost nothing, so this proves little"


def test_the_criterion_six_exceptions_are_named_not_judged() -> None:
    """The identifiers and citations are a list a reader can check."""
    assert (
        frozenset(
            {
                "owner",
                "mechanic_id",
                "reason",
                "url",
                "revision_id",
                "revision_timestamp",
            }
        )
        == POLICY_IDENTIFIER_FIELDS
    )


def test_the_exceptions_taken_across_the_catalog_are_the_exceptions_named() -> None:
    """Which fields the walk actually skipped, pinned as ``(type, field)`` pairs.

    :data:`POLICY_IDENTIFIER_FIELDS` is a set of *names*, so it exempts a
    field called ``reason`` wherever one appears.  A payload that grew such a
    field would take the exception in silence — an open string admitted by a
    criterion written to forbid open strings.  Pinning the pairs the walk
    took over the whole catalog is what sees it: a new one is a diff here,
    with the type that introduced it named.
    """
    taken = {
        pair
        for owner in rule_owners()
        for rule in behavior_rules(owner)
        for pair in policy_walk(rule).identifiers
    }
    assert taken == {
        ("BehaviorRule", "owner"),
        ("BehaviorRule", "mechanic_id"),
        ("ReceiptOnly", "reason"),
        ("SourceReceipt", "url"),
        ("SourceReceipt", "revision_id"),
        ("SourceReceipt", "revision_timestamp"),
        ("ZeroPolicy", "reason"),
    }
    assert {field for _type, field in taken} <= POLICY_IDENTIFIER_FIELDS


def test_a_rule_with_an_open_string_policy_field_does_not_compile() -> None:
    """R-05's red for criterion 6, through ``validate_rule``'s own ladder.

    The criterion is a *mechanism* rather than a property of today's
    declarations: the compiler that builds a rule refuses it, so a family
    migrated later cannot put a ``dict`` or a bare string on a policy axis
    and discover it in review.  ``dataclasses.replace`` is the seam — the
    payload is frozen, and the point is a value that reached construction.
    """
    rule = _rule()
    open_string = replace(rule, payload=replace(rule.payload, pool="all events"))
    with pytest.raises(BehaviorRuleError, match=re.escape("payload.pool holds a str")):
        validate_rule(open_string)

    a_dict = replace(rule, payload=replace(rule.payload, bonus_typing={"true": 1.0}))
    with pytest.raises(
        BehaviorRuleError, match=re.escape("payload.bonus_typing holds a dict")
    ):
        validate_rule(a_dict)

    a_callable = replace(rule, payload=replace(rule.payload, magnitude=lambda: 0.07))
    with pytest.raises(
        BehaviorRuleError, match=re.escape("payload.magnitude holds a function")
    ):
        validate_rule(a_callable)


def test_the_open_string_refusal_reaches_inside_a_collection() -> None:
    """A ``frozenset[str]`` is an open string axis wearing a container.

    The walk descends into tuples and sets for exactly this reason: the
    typing axis holds frozensets of enum members, and a refactor that
    replaced the enum with its ``.value`` would otherwise pass a criterion
    written to forbid it.
    """
    rule = _rule()
    assert "payload.typing.damage_classes[]" in [
        site for site, _value in policy_walk(rule).sites
    ]

    stringly = replace(
        rule,
        payload=replace(
            rule.payload,
            typing=Typing(frozenset({"magic"}), frozenset({"ability"})),  # type: ignore[arg-type]
        ),
    )
    with pytest.raises(BehaviorRuleError, match=r"damage_classes\[\] holds a str"):
        validate_rule(stringly)


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
    context = BuildContext(
        level=18,
        owner="Test Item",
        data_version=3,
        fight_duration_seconds=5.0,
        target_bonus_health=0.0,
        holder_is_melee=True,
    )
    assert context.data_version == 3


def test_the_utility_vocabulary_is_the_single_home_both_readers_project() -> None:
    """The flip's other side: two readers, one home, asserted in both directions.

    ``item_outcomes.UTILITY_OUTCOMES`` now holds ``UtilityDimension`` members
    rather than open strings, and Phase 1's
    ``coverage_evidence.UTILITY_DIMENSIONS`` is asserted equal to this enum's
    values rather than to whatever the per-item declaration happens to
    contain.  The two readers can therefore only disagree with the home, never
    quietly with each other.

    Set equality, never a count: 43 items and 29 dimensions are two
    plausible-looking wrong answers for one population.
    """
    # Imported here rather than at module scope: the leaf-ness test above
    # asserts ``item_behavior`` itself imports nothing but ``value_ref`` and
    # ``ability_spec``, and these two readers depend on it, not the reverse.
    from src.calculator import item_outcomes
    from src.calculator.coverage_evidence import UTILITY_DIMENSIONS

    declared = {dimension.value for dimension in UtilityDimension}
    assigned = {
        dimension
        for dimensions in item_outcomes.UTILITY_OUTCOMES.values()
        for dimension in dimensions
    }

    assert declared == set(UTILITY_DIMENSIONS)
    assert assigned <= set(UtilityDimension)
    assert {dimension.value for dimension in assigned} == declared
    assert len(UtilityDimension) == len(declared), "two members share a value"


def test_every_utility_member_is_spelled_the_way_it_serializes() -> None:
    """The member name is the value upper-cased — no second spelling exists.

    The dimension strings are a public payload field.  An enum whose member
    name and value can drift would give a reader two names for one dimension,
    which is the drift the single-home ruling exists to stop.
    """
    for dimension in UtilityDimension:
        assert dimension.name == dimension.value.upper()


def test_the_packet_kind_enum_covers_every_kind_the_utility_census_reads() -> None:
    """ER1: the census's eight reads resolve to members, not to bare strings.

    ``participant_timeline._utility_outcome_receipt`` classified seven
    dimensions and the denial split by comparing ``event["kind"]`` against
    string literals, so a kind could be authored in one spelling and read in
    another with nothing to notice.  Both sides now go through
    :class:`PacketKind`; this pins that the enum actually spans the census.
    """
    from src.calculator.item_behavior import PacketKind, is_denial_receipt

    census_reads = {
        "movement",
        "cleanse",
        "slow",
        "economy",
        "vision",
        "damage_modifier",
        "resource",
        "item_denial",
    }
    assert census_reads <= {kind.value for kind in PacketKind}
    for kind in PacketKind:
        assert kind.name == kind.value.upper()

    assert is_denial_receipt({"kind": "item_denial"})
    assert not is_denial_receipt({"kind": "movement"})
    assert not is_denial_receipt({})


def test_no_utility_census_read_is_a_bare_string_literal() -> None:
    """The refactor's own guard: the census reads through the enum only."""
    import re
    from pathlib import Path

    from src.calculator import participant_timeline

    body = Path(participant_timeline.__file__).read_text(encoding="utf-8")
    census = body.split("def _utility_outcome_receipt(")[1].split("\ndef ")[0]
    bare = re.findall(
        r'\.get\("kind"\)\s*==\s*"(?:movement|cleanse|slow|economy|vision'
        r'|damage_modifier|resource|item_denial)"',
        census,
    )
    assert bare == []
