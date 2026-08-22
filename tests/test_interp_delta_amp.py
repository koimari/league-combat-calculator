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

from src.calculator import interpreters
from src.calculator import item_effects as item_effects_module
from src.calculator.ability_spec import AttackClass
from src.calculator.interpreters import delta_amp
from src.calculator.item_behavior import (
    AMP_CHAIN_ORDER,
    AmpChainSlot,
    BuildContext,
    Comparison,
    Compilable,
    EngineLane,
    Fixed,
    KernelField,
    LivePredicate,
    Probe,
    RampModel,
    RampPerSecond,
    RampPerStack,
    ReceiptOnly,
    ReceiptScope,
    RuleFamily,
    TargetBonusHealthScaled,
    WindowBoundary,
    WindowMerge,
    chain_rank,
)
from src.calculator.item_behavior_catalog import (
    ACKNOWLEDGED_READING_DIVERGENCES,
    AMP_COMPILABILITY,
    BehaviorCatalogError,
    COMPILED_KERNEL_CANNOT_AMP,
    COMPILED_KERNEL_CAN_AMP,
    RUNE_AMP_SLOTS,
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
    """The eight slots, frozen: a refactor that reorders them fails here.

    These chain slots are **not** Phase 4's seven authority moves; the two
    sets overlap and neither contains the other.
    """
    assert AMP_CHAIN_ORDER == (
        AmpChainSlot.CINDERBLOOM,
        AmpChainSlot.EXPOSE_WEAKNESS,
        AmpChainSlot.OPENING_WINDOW,
        AmpChainSlot.LASTING_PROC_AMP,
        AmpChainSlot.WHOLE_TOTAL,
        AmpChainSlot.POST_IMMOBILIZE,
        AmpChainSlot.HYPERSHOT,
        AmpChainSlot.TARGET_HEALTH_GATE,
    )
    assert len(AMP_CHAIN_ORDER) == 8
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
    (field,) = delta_amp.amp_fields(rule, ctx, EngineLane.PAIR_ENGINE)
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


def test_a_second_immobilize_refreshes_the_window_rather_than_stacking() -> None:
    """D-12's policy, as the declaration now states it.

    The merged window's expiry is the *last* trigger plus one duration, and
    nothing about the first trigger survives in it except its start.  That is
    the whole content of ``REFRESH``, and it is what distinguishes the shipped
    reading from the additive one the Wiki's wording admits: additive would
    end at ``duration / 2 + duration + duration``, not at
    ``duration / 2 + duration``.
    """
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


def test_every_acknowledged_reading_divergence_names_a_live_declaration() -> None:
    """A divergence must qualify a rule that exists, and say what it ships.

    The failure mode this closes is the one
    ``item_source.test_acknowledgements_do_not_outlive_their_conflict``
    closes for its own table: an explanation that outlives the thing it
    explains hides the next real disagreement.  Here the referent is a
    ``mechanic_id``, so the check is that every key resolves to a declared
    rule — and, for Command, that the note's claim about what ships is the
    declaration's own word rather than a sentence beside it.
    """
    declared = {
        rule.mechanic_id for owner in rule_owners() for rule in behavior_rules(owner)
    }
    assert set(ACKNOWLEDGED_READING_DIVERGENCES) <= declared, (
        "a reading divergence names a mechanic_id no rule declares: "
        f"{sorted(set(ACKNOWLEDGED_READING_DIVERGENCES) - declared)}"
    )
    assert (
        ACKNOWLEDGED_READING_DIVERGENCES
    ), "the table is empty, so the gate above is green over nothing (D-26)"

    slot = _command_slot("Imperial Mandate")
    assert slot is not None
    rule = slot.rules[0]
    assert rule.mechanic_id in ACKNOWLEDGED_READING_DIVERGENCES
    note = ACKNOWLEDGED_READING_DIVERGENCES[rule.mechanic_id]
    assert rule.payload.activation.merge is WindowMerge.REFRESH, (
        "the note says REFRESH is the shipped reading; the declaration no "
        "longer agrees, so one of the two has moved without the other"
    )
    assert "REFRESH" in note and "EXTEND" in note, (
        "the note has to name both the reading that ships and the reading "
        "that stays open, or it records a decision without its alternative"
    )


def test_refresh_takes_the_last_trigger_and_not_the_running_total() -> None:
    """Three triggers inside one window still end one duration after the last.

    The arithmetic that separates a refresh from an extension is only visible
    once a third trigger lands: refresh ends at ``last + duration`` however
    many triggers preceded it, while the additive reading would have added a
    duration per trigger.
    """
    slot = _command_slot("Imperial Mandate")
    assert slot is not None
    duration = slot.value(delta_amp.WINDOW_DURATION_FIELD)
    triggers = [0.0, duration / 4.0, duration / 2.0]
    assert slot.trigger_windows(triggers) == ((0.0, triggers[-1] + duration),)


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

    ``EXTEND``/``INDEPENDENT`` and ``CLOSED_CLOSED`` are legal spellings no
    rule declares; writing arithmetic for a shape nothing reaches is the
    orphan branch D-51 forbids, so the interpreter stops instead.  ``EXTEND``
    is unreached *and* live as a question — it is the additive reading the
    Wiki's wording admits — so its refusal here is what keeps the additive
    answer from arriving as a silent default.
    """
    slot = _command_slot("Imperial Mandate")
    assert slot is not None
    declared = slot.rules[0].payload.activation
    for replacement in (
        dataclasses.replace(declared, merge=WindowMerge.EXTEND),
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
    """D-51: the two boundary comparisons are unreached and raise.

    ``LT`` and ``GT`` are both declared — Cinderbloom and Coup de Grace arm
    under a share of the target's health, Cut Down over one — and no rule
    says which side of the threshold *itself* is inside, so ``LE`` and ``GE``
    have no arithmetic.
    """
    slot = _cinderbloom_slot("Shadowflame")
    assert slot is not None
    declared = slot.rules[0].payload.activation
    for cmp_member in (Comparison.LE, Comparison.GE):
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
        names = {
            field.name
            for field in delta_amp.amp_fields(rule, ctx, EngineLane.PAIR_ENGINE)
        }
        assert names == {
            delta_amp.AMP_FRACTION_FIELD,
            delta_amp.LIVE_THRESHOLD_FIELD,
        }


def test_every_amp_declares_the_one_compiled_kernel_answer() -> None:
    """Phase 3 criterion 16, discharged by the declaration and never by absence.

    Every ``delta_amp`` rule — item and keystone alike — carries
    ``AMP_COMPILABILITY`` itself, so the assertion is identity against that
    single constant rather than a substring match: a per-rule copy of the
    answer would read the same and would be the sixteen-conservatism-notes
    failure again, and a rule holding its own verdict would move without the
    population the flip names.
    """
    amps = [
        rule
        for owner in sorted(rule_owners())
        for rule in behavior_rules(owner)
        if rule.family is RuleFamily.DELTA_AMP
    ]
    assert amps, "no delta_amp rule is declared, so this criterion proves nothing"
    assert {rule.owner for rule in amps} >= set(RUNE_AMP_SLOTS), (
        "the rune amps are delta_amp declarations too (CLAUDE.md rule 5); "
        "a criterion read over items only would miss four runtime amp "
        "producers"
    )
    for rule in amps:
        assert (
            rule.compilability is AMP_COMPILABILITY
        ), f"{rule.mechanic_id} does not carry the one compiled-kernel answer"


# ── D-98: the derivation beside the legacy set, and the asserted delta ────

# Every mechanic the H5 flip moves, enumerated before it moves them.  This is
# the delta R-31 requires an asserted set for: the flip is one symbol, so
# without a committed population its blast radius would be whatever the tree
# happened to contain on the day, discovered afterwards rather than declared.
#
# Fourteen of the sixteen are holder-side amps the pair engine prices into its
# own damage rows, which the compiled walk has always consumed already
# amplified; two author a cross-participant ``damage_modifier`` packet and are
# the reason the blanket refusal existed at all.  Both halves move together
# because one constant answered for both.
AMP_FLIP_POPULATION = frozenset(
    {
        "actualizer.ability_part_amp",
        "bloodsong.expose_weakness",
        "first_strike.opening_window_amp",
        "haunting_guise.whole_total_amp",
        "hexoptics_c44.basic_part_amp",
        "horizon_focus.hypershot",
        "immortal_path.whole_total_amp",
        "imperial_mandate.command",
        "liandrys_torment.whole_total_amp",
        "lord_dominiks_regards.whole_total_amp",
        "press_the_attack.lasting_proc_amp",
        "riftmaker.whole_total_amp",
        "shadowflame.cinderbloom",
        "spear_of_shojin.whole_total_amp",
        "coup_de_grace.target_health_gate",
        "cut_down.target_health_gate",
    }
)


def test_the_amp_flip_population_is_the_declared_one() -> None:
    """Which mechanics the one-symbol flip moves, asserted rather than found.

    D-98/R-31: a derivation lands beside the legacy declaration with an
    asserted delta, and only then does the flip land as its own revert unit.
    ``AMP_COMPILABILITY`` is that indirection; this is the delta.  A
    seventeenth amp declared without a line here fails on the commit that adds
    it, which is what stops the flip from silently taking a mechanic nobody
    scoped with it.
    """
    live = {
        rule.mechanic_id
        for owner in sorted(rule_owners())
        for rule in behavior_rules(owner)
        if rule.family is RuleFamily.DELTA_AMP
    }
    assert live == AMP_FLIP_POPULATION


def test_the_two_amp_answers_are_a_real_delta() -> None:
    """Both sides of the flip exist, and they say different things.

    A "derivation beside the legacy set" whose two sides were the same
    object, or the same verdict, would make the flip a no-op wearing a
    correction's clothes.  The scope is asserted on the refusal because that
    is the population H5's stage names (``ReceiptScope`` documents it), and
    the flip is asserted to be exactly one of the two.
    """
    assert isinstance(COMPILED_KERNEL_CANNOT_AMP, ReceiptOnly)
    assert isinstance(COMPILED_KERNEL_CAN_AMP, Compilable)
    assert COMPILED_KERNEL_CANNOT_AMP.scope is ReceiptScope.SCORE_KERNEL_DAMAGE_MODIFIER
    assert AMP_COMPILABILITY in (COMPILED_KERNEL_CANNOT_AMP, COMPILED_KERNEL_CAN_AMP)


def test_the_compiled_lane_is_declared_served_rather_than_assumed() -> None:
    """The successor to "declared empty, fallback receipted", after the flip.

    The claim the phase made was that the compiled lane's emptiness was
    *declared* rather than merely absent.  H5's stage did not relax that; it
    changed which declaration says so, and both halves are still asserted
    because either alone is the unstated absence the criterion forbids.

    Still no interpreter serves ``delta_amp`` on the compiled lane — the walk
    never reads an amp declaration, and registering one would be a second
    producer of a number the pair engine and the ``damage_modifier`` packet
    already deliver.  What changed is the excuse: every amp holder's
    per-owner fold now answers ``Compilable``, so the lane is excused by the
    dated row naming those two routes instead of by a per-rule refusal, and
    that row's presence is the second half here.
    """
    pair = (RuleFamily.DELTA_AMP, EngineLane.COMPILED_SCORE_WALK)
    assert pair not in interpreters.INTERPRETERS
    assert pair in interpreters.UNSERVED_LANE_RECEIPTS
    assert "neither of them the rule" in (
        interpreters.UNSERVED_LANE_RECEIPTS[pair].reason
    )
    holders = sorted(
        {
            rule.owner
            for owner in rule_owners()
            for rule in behavior_rules(owner)
            if rule.family is RuleFamily.DELTA_AMP
        }
    )
    assert holders, "no amp holder is declared, so this proves nothing"
    for holder in holders:
        verdict = interpreters.compilability_for(
            holder, ReceiptScope.SCORE_KERNEL_DAMAGE_MODIFIER
        )
        assert isinstance(verdict, Compilable), holder


# ── the two per-part amps (3.7-r2) ────────────────────────────────────────


def _part_amp(*owners: str, melee: bool, attack_class: AttackClass):
    """Resolve one attack class's per-part amp for a build."""
    return delta_amp.resolve_part_amp(
        owners,
        attack_class,
        level=18,
        fight_duration_seconds=5.0,
        target_bonus_health=0.0,
        holder_is_melee=melee,
    )


def test_no_holder_of_a_per_part_amp_is_none_and_not_a_zero() -> None:
    """A build declaring no per-part amp gets ``None``, never a 0.0 fraction."""
    assert _part_amp(melee=True, attack_class=AttackClass.ABILITY) is None
    assert (
        _part_amp(
            "Liandry's Torment", melee=True, attack_class=AttackClass.BASIC_ATTACK
        )
        is None
    )


def test_the_ability_amp_is_the_registry_base_plus_its_bonus_mana_rate() -> None:
    """Actualizer's declared magnitude, against the registry's own numbers.

    Read from ``ITEM_EFFECTS`` rather than typed, so a patch that re-tunes
    either number moves the expectation with the declaration instead of
    turning this test red for being right.
    """
    entry = ITEM_EFFECTS["Actualizer"]
    amp = _part_amp("Actualizer", melee=True, attack_class=AttackClass.ABILITY)
    assert amp is not None
    assert amp.owner == "Actualizer"
    assert amp.multiplier({"bonus_mana": 0.0}) == pytest.approx(1.0 + entry["base_amp"])
    assert amp.multiplier({"bonus_mana": 300.0}) == pytest.approx(
        1.0 + entry["base_amp"] + entry["amp_per_100_bonus_mana"] * 3.0
    )


def test_the_ability_amp_refuses_a_stat_reading_nobody_supplied() -> None:
    """A missing holder stat is an unanswered question, never a zero.

    The magnitude names the stat it scales with; a caller that omits it does
    not know what it is holding, and paying the base amp alone would be a
    number the model did not compute wearing a number it did.
    """
    amp = _part_amp("Actualizer", melee=True, attack_class=AttackClass.ABILITY)
    assert amp is not None
    with pytest.raises(delta_amp.DeltaAmpInterpretationError, match="bonus_mana"):
        amp.multiplier({})


def test_a_stat_scaled_magnitude_has_no_build_time_fraction() -> None:
    """``magnitude_fraction`` refuses the one shape it cannot answer alone."""
    rule = behavior_rules("Actualizer")[0]
    ctx = build_context(
        "Actualizer",
        18,
        fight_duration_seconds=5.0,
        target_bonus_health=0.0,
        holder_is_melee=True,
    )
    with pytest.raises(delta_amp.DeltaAmpInterpretationError, match="bonus_mana"):
        delta_amp.magnitude_fraction(rule.payload.magnitude, ctx)
    names = {
        field.name for field in delta_amp.amp_fields(rule, ctx, EngineLane.PAIR_ENGINE)
    }
    assert delta_amp.AMP_BASE_FRACTION_FIELD in names
    assert delta_amp.AMP_PER_HUNDRED_STAT_FIELD in names
    assert delta_amp.AMP_FRACTION_FIELD not in names


def test_the_basic_amp_declares_its_range_assumption_as_a_derivation() -> None:
    """Hexoptics C44's melee share is the sourced distance ratio, not a literal."""
    entry = ITEM_EFFECTS["Hexoptics C44"]
    ranged = _part_amp(
        "Hexoptics C44", melee=False, attack_class=AttackClass.BASIC_ATTACK
    )
    melee = _part_amp(
        "Hexoptics C44", melee=True, attack_class=AttackClass.BASIC_ATTACK
    )
    assert ranged is not None and melee is not None
    assert ranged.multiplier({}) == pytest.approx(1.0 + entry["max_amp"])
    assert melee.multiplier({}) == pytest.approx(
        1.0
        + entry["max_amp"]
        * (
            min(entry["melee_assumed_distance"], entry["max_distance"])
            / entry["max_distance"]
        )
    )


def test_a_per_part_amp_is_selected_by_the_damage_it_prices() -> None:
    """The engine asks by attack class; neither item's name is a selector.

    Actualizer prices abilities and Hexoptics basic attacks, and a build
    holding both must never hand one's multiplier to the other's damage.
    """
    build = ("Actualizer", "Hexoptics C44")
    ability = _part_amp(*build, melee=True, attack_class=AttackClass.ABILITY)
    basic = _part_amp(*build, melee=True, attack_class=AttackClass.BASIC_ATTACK)
    assert ability is not None and basic is not None
    assert [rule.owner for rule in ability.rules] == ["Actualizer"]
    assert [rule.owner for rule in basic.rules] == ["Hexoptics C44"]
    assert _part_amp(*build, melee=True, attack_class=AttackClass.OTHER) is None


def test_the_registry_no_longer_holds_a_per_part_amp_of_its_own() -> None:
    """Counter 3's two survivors are declarations now, not registry effects.

    The migration is only real if the old compiled effects are *gone*: a
    second producer of one multiplier is the shape this campaign exists to
    kill, and an accessor left behind is a second producer waiting for a
    caller.
    """
    assert not hasattr(item_effects_module, "AbilityAmplifierEffect")
    assert not hasattr(item_effects_module, "BasicAmplifierEffect")
    effects = item_effects_module.resolve_damage_effects(
        [{"name": "Actualizer"}, {"name": "Hexoptics C44"}]
    )
    assert not hasattr(effects, "ability_amp")
    assert not hasattr(effects, "basic_amp")
