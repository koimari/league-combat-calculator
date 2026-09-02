"""The front door for the resistance-shred interpreter — two models, one home.

The two stacking reductions in the registry are summed by two different
models, and before this slice each model's arithmetic sat beside its own
typed record with nothing saying which was which.  What is checked here is
therefore not "the numbers are right" — the golden baseline pins that — but
that each model *is what it says it is*: the Cesàro closed form reproduces the
constants the pair engine has always used, the exact model counts stacks one
at a time, and each refuses the other's question rather than answering it with
a plausible number.

``docs/math-foundations.md`` §2.3 calls re-tuning the Cesàro constant a
balance change.  The pins below are therefore deliberately written as the
arithmetic a reader can check by hand against the registry, so a re-tune shows
up here as a decision rather than as a diff nobody attributed.
"""

import pytest

from src.calculator.ability_spec import DamageClass
from src.calculator.interpreters import INTERPRETERS, resistance_shred
from src.calculator.item_behavior import (
    EngineLane,
    FightFacts,
    RampModel,
    Resistance,
    ResistanceShredRule,
    RuleFamily,
)
from src.calculator.item_behavior_catalog import (
    ASSUMED_CARVE_LEADING_ABILITY_HITS,
    NO_LEADING_STACKS,
    behavior_rules,
)
from src.calculator.item_effects import ITEM_EFFECTS

CARVE_HOLDER = "Black Cleaver"
VILE_DECAY_HOLDER = "Bloodletter's Curse"


def _slot(*owners: str, resistance: Resistance) -> "resistance_shred.ShredSlot | None":
    """Resolve one resistance's shred for a build."""
    return resistance_shred.resolve_slot(
        owners,
        resistance,
        facts=FightFacts(
            level=18,
            fight_duration_seconds=5.0,
            target_bonus_health=0.0,
            holder_is_melee=True,
        ),
    )


def _armor() -> "resistance_shred.ShredSlot":
    """The armour shred a Black Cleaver build declares."""
    slot = _slot(CARVE_HOLDER, resistance=Resistance.ARMOR)
    assert slot is not None
    return slot


def _magic() -> "resistance_shred.ShredSlot":
    """The magic-resistance shred a Bloodletter's Curse build declares."""
    slot = _slot(VILE_DECAY_HOLDER, resistance=Resistance.MAGIC_RESIST)
    assert slot is not None
    return slot


def test_both_shreds_are_declared_and_act_on_the_target() -> None:
    """A reduction moves the target's resistance; nothing else has one."""
    for owner in (CARVE_HOLDER, VILE_DECAY_HOLDER):
        rules = [
            rule
            for rule in behavior_rules(owner)
            if rule.family is RuleFamily.RESISTANCE_SHRED
        ]
        assert len(rules) == 1
        payload = rules[0].payload
        assert isinstance(payload, ResistanceShredRule)
        assert payload.subject.value == "target"


def test_the_two_summation_models_are_declared_not_inferred() -> None:
    """Which model a number came from is now readable off the declaration."""
    assert _armor()._payload.ramp.model is RampModel.CESARO_APPROX
    assert _magic()._payload.ramp.model is RampModel.EXACT


def test_the_carve_leading_hit_assumption_is_declared() -> None:
    """The pair model's belief about what preceded the auto stream is visible.

    It was a ``+ 4`` inside an averaging helper; a reader could not tell it
    from a wiki number.  An exactly-counted shred declares zero instead of
    inheriting a default.
    """
    assert ASSUMED_CARVE_LEADING_ABILITY_HITS.reason == "count"
    assert _armor().value(resistance_shred.SHRED_LEADING_STACKS_FIELD) == 4.0
    assert NO_LEADING_STACKS.value == 0.0
    assert _magic().value(resistance_shred.SHRED_LEADING_STACKS_FIELD) == 0.0


def test_the_cesaro_average_reproduces_the_engines_own_closed_form() -> None:
    """Below the cap the ramp is half the count; at it, the saturated mean."""
    entry = ITEM_EFFECTS[CARVE_HOLDER]
    per_stack = float(entry["reduction_per_stack"])
    cap = int(entry["max_stacks"])
    slot = _armor()
    # Zero autos still carries the four assumed leading ability hits.
    assert slot.average_reduction(0) == pytest.approx(per_stack * (4 / 2.0))
    # One auto reaches the cap, so the model switches to its saturated mean.
    assert slot.average_reduction(1) == pytest.approx(per_stack * cap * 0.8)
    assert slot.average_reduction(30) == pytest.approx(per_stack * cap * 0.8)


def test_the_exact_model_counts_stacks_one_at_a_time() -> None:
    """The cut at N stacks, in the percent unit the resistance arithmetic takes."""
    per_stack = float(ITEM_EFFECTS[VILE_DECAY_HOLDER]["mr_reduction_per_stack"])
    slot = _magic()
    assert slot.reduction_percent(0) == pytest.approx(0.0)
    assert slot.reduction_percent(3) == pytest.approx(per_stack * 3 * 100.0)
    assert slot.max_stacks == int(ITEM_EFFECTS[VILE_DECAY_HOLDER]["max_stacks"])


def test_each_model_refuses_the_other_models_question() -> None:
    """A model that answered both would be inventing one of the two answers."""
    with pytest.raises(resistance_shred.ResistanceShredInterpretationError):
        _armor().reduction_percent(3)
    with pytest.raises(resistance_shred.ResistanceShredInterpretationError):
        _magic().average_reduction(10)


def test_the_damage_that_applies_a_stack_is_the_declarations_typing() -> None:
    """Vile Decay reads magic damage, and a mixed ability is partly magic."""
    magic = _magic()
    assert magic.accrues_on("magic")
    assert magic.accrues_on("mixed")
    assert not magic.accrues_on("physical")
    assert not magic.accrues_on("true")
    carve = _armor()
    assert carve.accrues_on("physical")
    assert carve.accrues_on("mixed")
    assert not carve.accrues_on("magic")


def test_the_mixed_spelling_is_the_one_label_covering_two_classes() -> None:
    """Every other engine spelling is a DamageClass value, and this one is not."""
    assert resistance_shred.event_damage_classes("mixed") == frozenset(
        {DamageClass.MAGIC, DamageClass.PHYSICAL}
    )
    assert resistance_shred.event_damage_classes("true") == frozenset(
        {DamageClass.TRUE}
    )
    assert resistance_shred.event_damage_classes("healing") == frozenset()


def test_a_build_with_no_shred_resolves_to_none_not_to_zero() -> None:
    """No holder declares one, so no rule ran — an answer, not a measurement."""
    assert _slot("Sheen", resistance=Resistance.ARMOR) is None
    assert _slot(CARVE_HOLDER, resistance=Resistance.MAGIC_RESIST) is None


def test_two_shreds_of_one_resistance_stop_rather_than_pick_a_winner() -> None:
    """Nothing declares how two stacking reductions combine, so nothing guesses."""
    with pytest.raises(resistance_shred.ResistanceShredInterpretationError):
        _slot(CARVE_HOLDER, CARVE_HOLDER, resistance=Resistance.ARMOR)


def test_a_question_the_declaration_does_not_answer_raises() -> None:
    """A missing compiled field is a programming error, never a zero."""
    with pytest.raises(resistance_shred.ResistanceShredInterpretationError):
        _armor().value("window_end")


def test_both_lanes_read_the_one_ramp_body() -> None:
    """The pair engine and the walk are registered on the same function."""
    assert (
        INTERPRETERS[(RuleFamily.RESISTANCE_SHRED, EngineLane.PAIR_ENGINE)]
        is resistance_shred.ramp_fields
    )
    assert (
        INTERPRETERS[(RuleFamily.RESISTANCE_SHRED, EngineLane.RECEIPT_WALK)]
        is resistance_shred.ramp_fields
    )
