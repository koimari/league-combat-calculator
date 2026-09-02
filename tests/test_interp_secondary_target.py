"""The front door for the secondary-target interpreter.

Wind's Fury is reached through its declaration, not by spelling its item's
name (a ``has_item(items, "Runaan's Hurricane")`` test in the fight engine
and two accessors carrying the name as a default argument).  What is pinned
here is that the two numbers come off a declaration, that the main target is
excluded from the bolt count, and that a build with no holder gets an
answer rather than a zero.
"""

import pytest

from src.calculator.interpreters import secondary_target
from src.calculator.item_behavior import FightFacts, RuleFamily, SecondaryTargetRule
from src.calculator.item_behavior_catalog import behavior_rules
from src.calculator.item_effects import ITEM_EFFECTS

HOLDER = "Runaan's Hurricane"


def _slot(*owners: str) -> "secondary_target.SecondaryTargetSlot | None":
    """The secondary-target strike a build declares."""
    return secondary_target.resolve_slot(
        owners,
        facts=FightFacts(
            level=18,
            fight_duration_seconds=5.0,
            target_bonus_health=0.0,
            holder_is_melee=False,
        ),
    )


def test_the_holder_declares_exactly_one_secondary_target_rule() -> None:
    """Counter 3's half: the entry is one rule, not engine code plus accessors."""
    rules = [
        rule
        for rule in behavior_rules(HOLDER)
        if rule.family is RuleFamily.SECONDARY_TARGET
    ]
    assert len(rules) == 1
    assert isinstance(rules[0].payload, SecondaryTargetRule)


def test_the_bolt_count_excludes_the_target_the_attack_was_aimed_at() -> None:
    """The cardinality the engine has always used, now read off the rule."""
    slot = _slot(HOLDER)
    assert slot is not None
    cap = int(ITEM_EFFECTS[HOLDER]["max_secondary_targets"])  # type: ignore[arg-type]
    assert slot.bolt_count(1) == 0
    assert slot.bolt_count(2) == 1
    assert slot.bolt_count(2 + cap) == cap


def test_one_bolt_is_the_declared_share_of_the_attack() -> None:
    """The bolt's number is a share of the swing, not a formula of its own."""
    slot = _slot(HOLDER)
    assert slot is not None
    ratio = float(ITEM_EFFECTS[HOLDER]["secondary_ad_ratio"])  # type: ignore[arg-type]
    assert slot.bolt_damage(200.0) == pytest.approx(200.0 * ratio)


def test_whether_a_bolt_carries_on_hit_effects_is_declared() -> None:
    """There is no default answer to "does this bolt apply on-hit"."""
    slot = _slot(HOLDER)
    assert slot is not None
    assert slot.applies_on_hit is bool(ITEM_EFFECTS[HOLDER]["applies_on_hit"])
    assert slot.owner == HOLDER


def test_a_build_with_no_holder_resolves_to_none_not_to_zero() -> None:
    """The attack hits what it was aimed at and no rule had anything to add."""
    assert _slot("Sheen") is None


def test_a_missing_share_fails_loud_naming_the_item_and_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rule 5's no-stale-literal discipline, reached through the declaration."""
    broken = dict(ITEM_EFFECTS[HOLDER])
    broken.pop("secondary_ad_ratio")
    monkeypatch.setitem(ITEM_EFFECTS, HOLDER, broken)
    with pytest.raises(KeyError, match="secondary_ad_ratio"):
        _slot(HOLDER)


def test_two_bolt_sets_stop_rather_than_pick_a_winner() -> None:
    """Nothing declares how two secondary-target strikes combine."""
    with pytest.raises(secondary_target.SecondaryTargetInterpretationError):
        _slot(HOLDER, HOLDER)


def test_a_question_the_declaration_does_not_answer_raises() -> None:
    """A missing compiled field is a programming error, never a zero."""
    slot = _slot(HOLDER)
    assert slot is not None
    with pytest.raises(secondary_target.SecondaryTargetInterpretationError):
        slot.value("amp_fraction")
