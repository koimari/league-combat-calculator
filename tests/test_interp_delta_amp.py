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

import dataclasses

import pytest

from src.calculator.interpreters import delta_amp
from src.calculator.item_behavior import (
    AMP_CHAIN_ORDER,
    AmpChainSlot,
    BuildContext,
    Comparison,
    EngineLane,
    Fixed,
    KernelField,
    LivePredicate,
    Probe,
    RampModel,
    RampPerSecond,
    RampPerStack,
    RuleFamily,
    TargetBonusHealthScaled,
    WindowBoundary,
    WindowMerge,
    chain_rank,
)
from src.calculator.item_behavior_catalog import (
    BehaviorCatalogError,
    behavior_rules,
    build_context,
    rule_owners,
)
from src.calculator.item_effects import ALLY_ITEM_EFFECTS, ITEM_EFFECTS
from src.calculator.value_ref import Const


def _slot(*owners: str) -> "delta_amp.AmpSlot | None":
    """Resolve the Hypershot chain slot for a build."""
    return delta_amp.resolve_slot(
        owners,
        AmpChainSlot.HYPERSHOT,
        level=18,
        fight_duration_seconds=5.0,
        target_bonus_health=0.0,
        holder_is_melee=True,
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


def _fixed_slot(*fractions: float) -> "delta_amp.AmpSlot":
    """A slot whose holders contribute exactly *fractions*, for fold tests."""
    rules = delta_amp.slot_rules(["Horizon Focus"], AmpChainSlot.HYPERSHOT)
    return delta_amp.AmpSlot(
        slot=AmpChainSlot.HYPERSHOT,
        rules=rules * len(fractions),
        fields=tuple(
            (
                KernelField(
                    delta_amp.AMP_FRACTION_FIELD,
                    fraction,
                    EngineLane.PAIR_ENGINE,
                    "test",
                ),
            )
            for fraction in fractions
        ),
    )


def test_the_multiplier_is_one_plus_the_holders_sum() -> None:
    """The engine's own spelling, kept: not a running ``+=`` and not ``fsum``."""
    # Not an arbitrary triple: these three fractions are one of the triples on
    # which `1.0 + sum(f)` and a running `+=` land on different floats, which
    # is the whole reason the spelling is pinned rather than left to taste.
    slot = _fixed_slot(0.134, 0.16, 0.028)
    assert slot.multiplier == 1.0 + sum(slot.fractions)
    running = 1.0
    for fraction in slot.fractions:
        running += fraction
    assert slot.multiplier != running
    assert _fixed_slot(0.134).multiplier == 1.0 + 0.134  # one holder: all agree


def test_asking_a_rule_for_a_field_it_does_not_compile_is_a_stop() -> None:
    """A window's end from a rule with no window is a bug, never a zero."""
    with pytest.raises(delta_amp.DeltaAmpInterpretationError, match="window_start"):
        _fixed_slot(0.1).window()


def test_a_bonus_that_follows_its_source_has_no_aggregate_type() -> None:
    """An aggregate row needs one type; a source-following amp has none."""
    slot = _fixed_slot(0.1)
    assert slot.bonus_damage_type("magic") == "magic"
    with pytest.raises(delta_amp.DeltaAmpInterpretationError, match="single"):
        slot.uniform_bonus_damage_type()


def test_the_opening_window_slot_declares_its_window_and_its_true_bonus() -> None:
    """First Strike's two numbers now have one home, and the bonus type is declared."""
    slot = delta_amp.resolve_slot(
        ["First Strike"],
        AmpChainSlot.OPENING_WINDOW,
        level=18,
        fight_duration_seconds=10.0,
        target_bonus_health=0.0,
        holder_is_melee=True,
    )
    assert slot is not None
    assert slot.window() == (0.0, 3.0)
    assert slot.fractions[0] == pytest.approx(0.07)
    assert slot.uniform_bonus_damage_type() == "true"
    assert slot.bonus_damage_type("physical") == "true"


def test_the_pair_interpreter_emits_one_value_typed_field() -> None:
    """A KernelField carries no program type — that is the one-way dependency."""
    (rule,) = behavior_rules("Horizon Focus")
    ctx = build_context(
        "Horizon Focus",
        18,
        fight_duration_seconds=5.0,
        target_bonus_health=0.0,
        holder_is_melee=True,
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
        holder_is_melee=True,
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
        holder_is_melee=True,
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
    assert families == [RuleFamily.PERIODIC, RuleFamily.DELTA_AMP]
    assert "damage_amp_per_second" in ITEM_EFFECTS["Liandry's Torment"]


# ---------------------------------------------------------------------------
# Command — one declaration, both engines (D-12, D-13)
# ---------------------------------------------------------------------------


def _command_slot(*owners: str) -> "delta_amp.AmpSlot | None":
    """Resolve the post-immobilize chain slot for a build."""
    return delta_amp.resolve_slot(
        owners,
        AmpChainSlot.POST_IMMOBILIZE,
        level=18,
        fight_duration_seconds=10.0,
        target_bonus_health=0.0,
        holder_is_melee=True,
    )


def test_command_compiles_its_sourced_fraction_and_window() -> None:
    """The two numbers the pair engine used to read through an accessor."""
    slot = _command_slot("Imperial Mandate")
    assert slot is not None
    assert slot.owner == "Imperial Mandate"
    assert slot.bonus_fraction == pytest.approx(0.07)
    assert slot.value(delta_amp.WINDOW_DURATION_FIELD) == pytest.approx(4.0)


def test_a_build_without_the_mandate_declares_no_command_slot() -> None:
    """``None`` is the answer "nobody in this build declares it", not a zero."""
    assert _command_slot("Wit's End") is None


@pytest.mark.parametrize("dropped", ["command_damage_amp", "command_duration"])
def test_a_missing_command_key_names_the_item_and_the_key(
    monkeypatch: pytest.MonkeyPatch, dropped: str
) -> None:
    """A half-parsed amplifier is a stop, not an item that amplifies nothing.

    The ally registry carries no effect tag, so key presence is what routes a
    record to this compiler.  That is exactly the shape in which a dropped
    key silently un-declares a mechanic — so the slot lists *all* of its keys
    and a record holding some of them raises, naming the item and the keys.
    """
    broken = dict(ALLY_ITEM_EFFECTS["Imperial Mandate"])
    broken.pop(dropped)
    monkeypatch.setitem(ALLY_ITEM_EFFECTS, "Imperial Mandate", broken)
    with pytest.raises(BehaviorCatalogError, match=f"Imperial Mandate.*{dropped}"):
        _command_slot("Imperial Mandate")


def test_a_second_immobilize_extends_the_window_rather_than_stacking() -> None:
    """D-12's policy, as the declaration now states it."""
    slot = _command_slot("Imperial Mandate")
    assert slot is not None
    duration = slot.value(delta_amp.WINDOW_DURATION_FIELD)
    assert slot.trigger_windows([0.0, duration / 2.0]) == (
        (0.0, duration / 2.0 + duration),
    )
    assert slot.trigger_windows([0.0, duration * 3.0]) == (
        (0.0, duration),
        (duration * 3.0, duration * 4.0),
    )


def test_the_expiry_boundary_is_open_closed() -> None:
    """D-13: the trigger instant is outside the window and the expiry is in."""
    slot = _command_slot("Imperial Mandate")
    assert slot is not None
    duration = slot.value(delta_amp.WINDOW_DURATION_FIELD)
    windows = slot.trigger_windows([1.0])
    assert not slot.window_holds(windows, 1.0)
    assert slot.window_holds(windows, 1.0 + duration)
    assert not slot.window_holds(windows, 1.0 + duration + 1e-6)


def test_a_rule_with_no_trigger_window_refuses_the_question() -> None:
    """Asking a windowless rule where its window is, is a programming error."""
    slot = _slot("Horizon Focus")
    assert slot is not None
    with pytest.raises(delta_amp.DeltaAmpInterpretationError, match="trigger window"):
        slot.trigger_windows([0.0])
    with pytest.raises(delta_amp.DeltaAmpInterpretationError, match="trigger window"):
        slot.window_holds(((0.0, 1.0),), 0.5)


def test_an_undeclared_merge_or_boundary_has_no_arithmetic() -> None:
    """R-05/D-51: the two unreached members raise rather than guessing.

    ``REFRESH``/``INDEPENDENT`` and ``CLOSED_CLOSED`` are legal spellings no
    rule declares; writing arithmetic for a shape nothing reaches is the
    orphan branch D-51 forbids, so the interpreter stops instead.
    """
    slot = _command_slot("Imperial Mandate")
    assert slot is not None
    declared = slot.rules[0].payload.activation
    for replacement in (
        dataclasses.replace(declared, merge=WindowMerge.REFRESH),
        dataclasses.replace(declared, merge=WindowMerge.INDEPENDENT),
    ):
        mutated = _with_activation(slot, replacement)
        with pytest.raises(delta_amp.DeltaAmpInterpretationError, match="window merge"):
            mutated.trigger_windows([0.0])
    closed = _with_activation(
        slot, dataclasses.replace(declared, boundary=WindowBoundary.CLOSED_CLOSED)
    )
    with pytest.raises(delta_amp.DeltaAmpInterpretationError, match="expiry boundary"):
        closed.window_holds(((0.0, 4.0),), 2.0)


def _with_activation(slot: "delta_amp.AmpSlot", activation) -> "delta_amp.AmpSlot":
    """The same resolved slot, with one holder's activation replaced."""
    rule = slot.rules[0]
    payload = dataclasses.replace(rule.payload, activation=activation)
    return dataclasses.replace(
        slot, rules=(dataclasses.replace(rule, payload=payload),)
    )


# ---------------------------------------------------------------------------
# Cinderbloom — the one amp whose pool cannot be precomputed
# ---------------------------------------------------------------------------


def _cinderbloom_slot(*owners: str) -> "delta_amp.AmpSlot | None":
    """Resolve the Cinderbloom chain slot for a build."""
    return delta_amp.resolve_slot(
        owners,
        AmpChainSlot.CINDERBLOOM,
        level=18,
        fight_duration_seconds=5.0,
        target_bonus_health=0.0,
        holder_is_melee=True,
    )


def test_cinderbloom_prices_the_multiplier_the_page_states_as_a_fraction() -> None:
    """The registry keeps 120%; the chain gets 0.2, by a declared subtraction."""
    slot = _cinderbloom_slot("Shadowflame")
    assert slot is not None
    multiplier = ITEM_EFFECTS["Shadowflame"]["crit_multiplier"]
    assert slot.bonus_fraction == multiplier - 1.0
    assert slot.value(delta_amp.LIVE_THRESHOLD_FIELD) == pytest.approx(
        ITEM_EFFECTS["Shadowflame"]["health_threshold"]
    )


def test_cinderbloom_crits_only_magic_and_true() -> None:
    """D-04: the excluded class is something the declaration says."""
    slot = _cinderbloom_slot("Shadowflame")
    assert slot is not None
    assert slot.prices_damage_type("magic")
    assert slot.prices_damage_type("true")
    assert not slot.prices_damage_type("physical")


def test_the_live_predicate_reads_a_pool_and_not_a_precomputed_ratio() -> None:
    """The comparison is ``value < scale * threshold``, the engine's own.

    A ratio would be a different float, and the whole point of the live
    predicate is that this migration moved no number.
    """
    slot = _cinderbloom_slot("Shadowflame")
    assert slot is not None
    threshold = slot.value(delta_amp.LIVE_THRESHOLD_FIELD)
    probe = Probe.TARGET_HEALTH_FRACTION
    assert not slot.live_predicate_holds(probe, 1000.0, 1000.0)
    assert not slot.live_predicate_holds(probe, 1000.0 * threshold, 1000.0)
    assert slot.live_predicate_holds(probe, 1000.0 * threshold - 1e-9, 1000.0)


def test_offering_the_wrong_pool_to_a_live_predicate_is_a_stop() -> None:
    """A rule that reads the target's health may not be handed the holder's."""
    slot = _cinderbloom_slot("Shadowflame")
    assert slot is not None
    with pytest.raises(
        delta_amp.DeltaAmpInterpretationError, match="the engine offered"
    ):
        slot.live_predicate_holds(Probe.HOLDER_HEALTH_FRACTION, 1.0, 1000.0)


def test_a_comparison_no_declaration_uses_has_no_branch() -> None:
    """D-51: three of the four comparisons are unreached and raise."""
    slot = _cinderbloom_slot("Shadowflame")
    assert slot is not None
    declared = slot.rules[0].payload.activation
    for cmp_member in (Comparison.LE, Comparison.GT, Comparison.GE):
        mutated = _with_activation(slot, dataclasses.replace(declared, cmp=cmp_member))
        with pytest.raises(delta_amp.DeltaAmpInterpretationError, match="comparison"):
            mutated.live_predicate_holds(Probe.TARGET_HEALTH_FRACTION, 1.0, 1000.0)


def test_no_interpreter_precomputes_a_live_predicate_pool() -> None:
    """Criterion: ``requires_live_pool`` means the pool is never a build value.

    Two halves.  The build context an interpreter may read carries no pool —
    it is level, owner, data version and three configuration facts fixed
    before the first event — so there is nothing to precompute *from*.  And
    the fields a live-predicate rule compiles to are exactly the sourced
    fraction and the sourced threshold: no reading, no crossing time, no
    pre-resolved answer.
    """
    context_fields = {field.name for field in dataclasses.fields(BuildContext)}
    assert not any(
        "health" in name for name in context_fields - {"target_bonus_health"}
    )

    live = [
        rule
        for owner in sorted(rule_owners())
        for rule in behavior_rules(owner)
        if isinstance(getattr(rule.payload, "activation", None), LivePredicate)
    ]
    assert live, "no rule declares a live predicate, so this test proves nothing"
    for rule in live:
        assert rule.payload.activation.requires_live_pool
        ctx = build_context(
            rule.owner,
            18,
            fight_duration_seconds=5.0,
            target_bonus_health=0.0,
            holder_is_melee=True,
        )
        names = {field.name for field in delta_amp.PAIR_INTERPRETER.compile(rule, ctx)}
        assert names == {
            delta_amp.AMP_FRACTION_FIELD,
            delta_amp.LIVE_THRESHOLD_FIELD,
        }
