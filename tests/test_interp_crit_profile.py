"""The crit family's front door: three mechanics under one pair of tags.

A build's critical strikes are three separate questions the registry files
together — how much more a crit pays, whether one strike is *made* to crit,
and how much ability cooldown an attack refunds — and the family is the one
place a build turns into a single answer to all three.

The tests below pin what the retired accumulators inside ``item_effects``
used to compute, value for value, because this migration's claim is that the
declarations reproduce them exactly.
"""

from __future__ import annotations

import pytest

from src.calculator import item_behavior_catalog as catalog
from src.calculator import item_effects
from src.calculator.interpreters import INTERPRETERS
from src.calculator.interpreters.crit_profile import (
    COOLDOWN_REFUND_FIELD,
    CRIT_DAMAGE_BONUS_FIELD,
    CritProfileInterpretationError,
    crit_fields,
    resolve_profile,
)
from src.calculator.item_behavior import (
    AttackCooldownRefundRule,
    CritDamageBonusRule,
    CritOccurrence,
    EngineLane,
    ForcedCritRule,
    RuleFamily,
    Subject,
    TriggerEvent,
)

BONUS_HOLDER = "Infinity Edge"
REFUND_HOLDER = "Navori Flickerblade"
FORCED_HOLDER = "Sundered Sky"


def _profile(*owners: str):
    """The declared crit profile of a build, at a mid-fight level."""
    return resolve_profile(
        list(owners),
        level=13,
        fight_duration_seconds=5.0,
        target_bonus_health=1000.0,
        holder_is_melee=True,
    )


def _rule(owner: str, payload_type: type):
    """The live rule *owner* declares with a payload of *payload_type*."""
    for rule in catalog.behavior_rules(owner):
        if isinstance(rule.payload, payload_type):
            return rule
    raise AssertionError(f"{owner} declares no {payload_type.__name__}")


def test_the_family_is_registered_on_the_lane_that_prices_it() -> None:
    """A crit multiplier is priced where the one-attacker damage model runs."""
    assert (
        INTERPRETERS[(RuleFamily.CRIT_PROFILE, EngineLane.PAIR_ENGINE)] is crit_fields
    )
    assert (RuleFamily.CRIT_PROFILE, EngineLane.RECEIPT_WALK) not in INTERPRETERS


def test_every_crit_entry_declares_a_rule() -> None:
    """The three registry entries the family covers all reach a declaration."""
    for owner in (BONUS_HOLDER, REFUND_HOLDER, FORCED_HOLDER):
        families = [rule.family for rule in catalog.behavior_rules(owner)]
        assert RuleFamily.CRIT_PROFILE in families
        assert owner not in catalog.undeclared_owners()


def test_the_damage_bonus_is_the_registry_number() -> None:
    """Infinity Edge's bonus is read, never carried."""
    profile = _profile(BONUS_HOLDER)
    assert profile.damage_bonus == pytest.approx(
        item_effects.required_effect_value(BONUS_HOLDER, "bonus_crit_damage")
    )
    assert profile.forced_crit is None
    assert profile.cooldown_refund is None


def test_the_cooldown_refund_names_its_holder() -> None:
    """The refund carries the owner the retired ladder recorded beside it."""
    refund = _profile(REFUND_HOLDER).cooldown_refund
    assert refund is not None
    assert refund.owner == REFUND_HOLDER
    assert refund.fraction == pytest.approx(
        item_effects.required_effect_value(REFUND_HOLDER, "cd_refund_percent")
    )


def test_the_forced_crit_carries_its_heal() -> None:
    """Sundered Sky's ratio, cooldown and four heal numbers, all sourced."""
    forced = _profile(FORCED_HOLDER).forced_crit
    assert forced is not None
    assert forced.occurrence is CritOccurrence.FIRST_ATTACK
    for attribute, key in (
        ("reduced_ratio", "reduced_crit_ratio"),
        ("cooldown", "cooldown"),
        ("heal_base_ad_ratio", "heal_base_ad_ratio"),
        ("heal_base_ad_ratio_ranged", "heal_base_ad_ratio_ranged"),
        ("heal_missing_health_ratio", "heal_missing_health_ratio"),
        ("temporary_health_duration", "temporary_health_duration"),
    ):
        assert getattr(forced, attribute) == pytest.approx(
            item_effects.required_effect_value(FORCED_HOLDER, key)
        )
    assert forced.heals is True


def test_a_build_declaring_nothing_gets_a_declared_zero() -> None:
    """No holder is an answer: a zero bonus and two absent slots, not a gap."""
    profile = _profile("Boots")
    assert profile.damage_bonus == 0.0
    assert profile.forced_crit is None
    assert profile.cooldown_refund is None


def test_the_three_mechanics_compose_in_one_build() -> None:
    """Holding all three resolves all three, each to its own registry number."""
    profile = _profile(BONUS_HOLDER, REFUND_HOLDER, FORCED_HOLDER)
    assert profile.damage_bonus > 0.0
    assert profile.cooldown_refund is not None
    assert profile.forced_crit is not None


def test_two_forced_crits_stop_rather_than_pick_a_winner() -> None:
    """No rule declares which forced crit a strike pays, so two is a stop."""
    with pytest.raises(CritProfileInterpretationError, match="both force"):
        _profile(FORCED_HOLDER, FORCED_HOLDER)


def test_two_refunds_stop_rather_than_compose_silently() -> None:
    """Two refunds have no declared fold, so the build is refused."""
    with pytest.raises(CritProfileInterpretationError, match="both declare"):
        _profile(REFUND_HOLDER, REFUND_HOLDER)


def test_two_bonuses_sum_because_the_multiplier_is_additive() -> None:
    """Crit damage really does add, so two holders are folded rather than refused."""
    single = _profile(BONUS_HOLDER).damage_bonus
    assert _profile(BONUS_HOLDER, BONUS_HOLDER).damage_bonus == pytest.approx(
        2 * single
    )


def test_each_payload_says_who_it_acts_on_and_what_arms_it() -> None:
    """The declared subject is the holder, and the refund names its trigger."""
    assert _rule(BONUS_HOLDER, CritDamageBonusRule).payload.subject is Subject.HOLDER
    refund = _rule(REFUND_HOLDER, AttackCooldownRefundRule).payload
    assert refund.subject is Subject.HOLDER
    assert refund.trigger is TriggerEvent.BASIC_ATTACK_HIT
    assert _rule(FORCED_HOLDER, ForcedCritRule).payload.subject is Subject.HOLDER


def test_the_interpreter_refuses_a_rule_of_another_family() -> None:
    """A payload the family does not own is a stop, never an empty field set."""
    other = next(
        rule
        for rule in catalog.behavior_rules("Black Cleaver")
        if rule.family is RuleFamily.RESISTANCE_SHRED
    )
    with pytest.raises(CritProfileInterpretationError):
        crit_fields(
            other,
            catalog.build_context(
                other.owner,
                13,
                fight_duration_seconds=5.0,
                target_bonus_health=0.0,
                holder_is_melee=True,
            ),
            EngineLane.PAIR_ENGINE,
        )


def test_the_compiled_field_names_are_what_the_engines_ask_for() -> None:
    """A field a caller cannot name is a number nobody can read."""
    rule = _rule(BONUS_HOLDER, CritDamageBonusRule)
    fields = crit_fields(
        rule,
        catalog.build_context(
            rule.owner,
            13,
            fight_duration_seconds=5.0,
            target_bonus_health=0.0,
            holder_is_melee=True,
        ),
        EngineLane.PAIR_ENGINE,
    )
    assert [field.name for field in fields] == [CRIT_DAMAGE_BONUS_FIELD]
    assert all(field.lane is EngineLane.PAIR_ENGINE for field in fields)
    assert all(field.rule_id == rule.mechanic_id for field in fields)
    refund_rule = _rule(REFUND_HOLDER, AttackCooldownRefundRule)
    refund_fields = crit_fields(
        refund_rule,
        catalog.build_context(
            refund_rule.owner,
            13,
            fight_duration_seconds=5.0,
            target_bonus_health=0.0,
            holder_is_melee=True,
        ),
        EngineLane.PAIR_ENGINE,
    )
    assert [field.name for field in refund_fields] == [COOLDOWN_REFUND_FIELD]
