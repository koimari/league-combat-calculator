"""The front door for the delta-amp interpreter — the chain, and its arithmetic.

Three things are checked here that nothing else can check.  The chain order
is pinned against a frozen literal, because it is the one property of
amplification that no individual amp's test can see and that every mixed
build's number depends on.  The fold is pinned as one spelling —
``1.0 + sum(f)``, the engine's own — because a running ``+=`` and
``math.fsum`` land on different floats once a slot has two occupants, and
this migration's whole claim is that no number moved.  And a magnitude shape
with no arithmetic raises instead of quietly contributing zero.
"""

import pytest

from src.calculator.interpreters import delta_amp
from src.calculator.item_behavior import (
    AMP_CHAIN_ORDER,
    AmpChainSlot,
    Fixed,
    RampModel,
    RampPerSecond,
    RampPerStack,
    RuleFamily,
    TargetBonusHealthScaled,
    chain_rank,
)
from src.calculator.item_behavior_catalog import behavior_rules, build_context
from src.calculator.item_effects import ITEM_EFFECTS
from src.calculator.value_ref import Const


def _slot(*owners: str) -> "delta_amp.AmpSlot | None":
    """Resolve the Hypershot chain slot for a build."""
    return delta_amp.resolve_slot(
        owners,
        AmpChainSlot.HYPERSHOT,
        level=18,
        fight_duration_seconds=5.0,
        target_bonus_health=0.0,
    )


def test_amp_chain_order_is_declared() -> None:
    """The seven slots, frozen: a refactor that reorders them fails here.

    These seven chain slots are **not** Phase 4's seven authority moves; the
    two sets overlap and neither contains the other.
    """
    assert AMP_CHAIN_ORDER == (
        AmpChainSlot.CINDERBLOOM,
        AmpChainSlot.EXPOSE_WEAKNESS,
        AmpChainSlot.OPENING_WINDOW,
        AmpChainSlot.LASTING_PROC_AMP,
        AmpChainSlot.WHOLE_TOTAL,
        AmpChainSlot.POST_IMMOBILIZE,
        AmpChainSlot.HYPERSHOT,
    )
    assert len(AMP_CHAIN_ORDER) == 7
    assert frozenset(AMP_CHAIN_ORDER) == frozenset(AmpChainSlot)


def test_every_slot_has_exactly_one_rank() -> None:
    """``lane_chain_rank`` has one producer, so two rules cannot disagree."""
    ranks = [chain_rank(slot) for slot in AMP_CHAIN_ORDER]
    assert ranks == list(range(len(AMP_CHAIN_ORDER)))


def test_a_declared_rule_carries_the_rank_of_its_slot() -> None:
    """The declaration and the chain agree because only one of them decides."""
    (rule,) = behavior_rules("Horizon Focus")
    assert rule.payload.lane_chain_rank == chain_rank(AmpChainSlot.HYPERSHOT)


def test_the_slot_resolves_to_the_sourced_multiplier() -> None:
    """The number comes from the registry through a reference, never a literal."""
    slot = _slot("Horizon Focus")
    assert slot is not None
    assert slot.multiplier == pytest.approx(1.10)
    assert slot.owner == "Horizon Focus"
    assert slot.sources() == (("Horizon Focus", pytest.approx(0.10)),)


def test_a_build_that_declares_no_holder_gets_no_slot() -> None:
    """``None`` is "no rule ran", which is a different answer from zero."""
    assert _slot("Boots") is None
    assert _slot() is None


def test_the_multiplier_is_one_plus_the_holders_sum() -> None:
    """The engine's own spelling, kept: not a running ``+=`` and not ``fsum``."""
    rules = delta_amp.slot_rules(["Horizon Focus"], AmpChainSlot.HYPERSHOT)
    # Not an arbitrary triple: these three fractions are one of the pairs on
    # which `1.0 + sum(f)` and a running `+=` land on different floats, which
    # is the whole reason the spelling is pinned rather than left to taste.
    slot = delta_amp.AmpSlot(
        slot=AmpChainSlot.HYPERSHOT, rules=rules * 3, fractions=(0.134, 0.16, 0.028)
    )
    assert slot.multiplier == 1.0 + sum(slot.fractions)
    running = 1.0
    for fraction in slot.fractions:
        running += fraction
    assert slot.multiplier != running
    single = delta_amp.AmpSlot(
        slot=AmpChainSlot.HYPERSHOT, rules=rules, fractions=(0.134,)
    )
    assert single.multiplier == 1.0 + 0.134  # one holder: every fold agrees


def test_the_pair_interpreter_emits_one_value_typed_field() -> None:
    """A KernelField carries no program type — that is the one-way dependency."""
    (rule,) = behavior_rules("Horizon Focus")
    ctx = build_context(
        "Horizon Focus", 18, fight_duration_seconds=5.0, target_bonus_health=0.0
    )
    (field,) = delta_amp.PAIR_INTERPRETER.compile(rule, ctx)
    assert field.name == delta_amp.AMP_FRACTION_FIELD
    assert field.rule_id == "horizon_focus.hypershot"
    assert isinstance(field.value, float)


def _ctx(duration: float = 5.0, bonus_health: float = 0.0):
    """A build context for magnitude arithmetic, with the two fight facts."""
    return build_context(
        "Horizon Focus",
        18,
        fight_duration_seconds=duration,
        target_bonus_health=bonus_health,
    )


def test_every_magnitude_shape_has_arithmetic() -> None:
    """Four shapes, four branches, each reproducing the schema it models."""
    assert (
        delta_amp.magnitude_fraction(Fixed(Const(0.25, "unit_scale")), _ctx()) == 0.25
    )
    ramp = RampPerSecond(Const(0.02, "unit_scale"), Const(0.06, "unit_scale"))
    assert delta_amp.magnitude_fraction(ramp, _ctx(2.0)) == pytest.approx(0.02)
    assert delta_amp.magnitude_fraction(ramp, _ctx(5.0)) == pytest.approx(0.03)
    scaled = TargetBonusHealthScaled(Const(0.15, "unit_scale"), Const(1500.0, "cap"))
    assert delta_amp.magnitude_fraction(
        scaled, _ctx(bonus_health=750.0)
    ) == pytest.approx(0.075)
    assert delta_amp.magnitude_fraction(
        scaled, _ctx(bonus_health=9000.0)
    ) == pytest.approx(0.15)
    stacked = RampPerStack(
        Const(0.03, "unit_scale"),
        Const(4.0, "count"),
        Const(2.0, "unit_scale"),
        RampModel.EXACT,
    )
    assert delta_amp.magnitude_fraction(stacked, _ctx(1.0)) == pytest.approx(0.03)
    assert delta_amp.magnitude_fraction(stacked, _ctx(100.0)) == pytest.approx(0.12)


def test_a_magnitude_with_no_arithmetic_raises_rather_than_pricing_zero() -> None:
    """A new magnitude shape is a stop, not a slot that quietly contributes 0."""

    class _NotInTheUnion:  # pylint: disable=too-few-public-methods
        """A magnitude shape somebody added and nobody interpreted."""

    with pytest.raises(delta_amp.DeltaAmpInterpretationError, match="_NotInTheUnion"):
        delta_amp.magnitude_fraction(_NotInTheUnion(), _ctx())


def test_a_ramp_model_no_declaration_uses_has_no_branch() -> None:
    """D-51: arithmetic for a shape nothing reaches would be an orphan branch."""
    cesaro = RampPerStack(
        Const(0.03, "unit_scale"),
        Const(4.0, "count"),
        Const(2.0, "unit_scale"),
        RampModel.CESARO_APPROX,
    )
    with pytest.raises(delta_amp.DeltaAmpInterpretationError, match="cesaro_approx"):
        delta_amp.magnitude_fraction(cesaro, _ctx())


def test_a_non_positive_bonus_health_cap_is_a_registry_defect() -> None:
    """A zero cap would divide, and a full-strength amp would be the silent answer."""
    broken = TargetBonusHealthScaled(Const(0.15, "unit_scale"), Const(0.0, "cap"))
    with pytest.raises(delta_amp.DeltaAmpInterpretationError, match="positive"):
        delta_amp.magnitude_fraction(broken, _ctx(bonus_health=750.0))


def test_the_whole_total_slot_holds_every_declared_general_amp() -> None:
    """One slot, several mechanics, additive among themselves and in build order."""
    build = [
        "Liandry's Torment",
        "Riftmaker",
        "Lord Dominik's Regards",
        "Spear of Shojin",
    ]
    slot = delta_amp.resolve_slot(
        build,
        AmpChainSlot.WHOLE_TOTAL,
        level=18,
        fight_duration_seconds=4.0,
        target_bonus_health=750.0,
    )
    assert slot is not None
    assert [owner for owner, _ in slot.sources()] == build
    assert dict(slot.sources()) == pytest.approx(
        {
            "Liandry's Torment": 0.03,
            "Riftmaker": 0.04,
            "Lord Dominik's Regards": 0.075,
            "Spear of Shojin": 0.06,
        }
    )


def test_a_second_mechanic_on_one_entry_is_declared_rather_than_missed() -> None:
    """Liandry's is a burn that also amplifies; a tag alone cannot say that."""
    families = [rule.family for rule in behavior_rules("Liandry's Torment")]
    assert families == [RuleFamily.DELTA_AMP]
    assert "damage_amp_per_second" in ITEM_EFFECTS["Liandry's Torment"]
