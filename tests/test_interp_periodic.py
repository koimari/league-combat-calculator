"""The front door for the periodic interpreter.

Three registry tags reach the engine as one declared family, not as three
unrelated typed records with no shared vocabulary.  What is pinned here is
that the family has three cadences; that each cadence's row keeps the
breakdown key and display name the engine has always published; that a burn
without a declared window is refused rather than priced; and that Anguish's
radius is read off its own declaration instead of being fetched by spelling
its item's name at the point of use.
"""

import pytest

from src.calculator.interpreters import periodic
from src.calculator.interpreters.rule_selection import rules_of
from src.calculator.item_behavior import (
    EngineLane,
    FightFacts,
    PeriodicCadence,
    PeriodicRule,
    RuleFamily,
    validate_rule,
)
from src.calculator.item_behavior_catalog import behavior_rules, build_context
from src.calculator.item_effects import (
    ITEM_EFFECTS,
    DamageInputs,
    sustain_effect_value,
)

BURN = "Blackfire Torch"
FLAT_BURN = "Fated Ashes"
MAX_HEALTH_BURN = "Liandry's Torment"
AURA = "Sunfire Aegis"
FLAT_AURA = "Bami's Cinder"
ANGUISH = "Unending Despair"


def _slots(*owners: str, level: int = 18) -> periodic.PeriodicSlots:
    """The periodic strikes a build of *owners* declares."""
    return periodic.resolve_slots(
        owners,
        facts=FightFacts(
            level=level,
            fight_duration_seconds=5.0,
            target_bonus_health=0.0,
            holder_is_melee=True,
        ),
    )


def _inputs(**stats: float) -> DamageInputs:
    """One event's readings for a compiled periodic formula."""
    return DamageInputs(
        champion_stats=stats,
        level=18,
        is_melee=True,
        target_max_health=2500.0,
        target_current_health=2500.0,
    )


def test_every_periodic_entry_declares_exactly_one_rule() -> None:
    """Counter 3's half: three tags, one family, no engine code left over."""
    tags = frozenset({"burn", "immolate", "periodic_aoe"})
    for owner, entry in ITEM_EFFECTS.items():
        if entry.get("type") not in tags:
            continue
        rules = [
            rule for rule in behavior_rules(owner) if rule.family is RuleFamily.PERIODIC
        ]
        assert len(rules) == 1, owner
        assert isinstance(rules[0].payload, PeriodicRule)


def test_each_tag_declares_the_cadence_that_matches_its_engine_record() -> None:
    """The tag is the registry's whole statement of the mechanic's shape."""
    declared = {
        rule.owner: rule.payload.cadence
        for rule in rules_of([BURN, AURA, ANGUISH], RuleFamily.PERIODIC)
    }
    assert declared == {
        BURN: PeriodicCadence.REFRESHED_BURN,
        AURA: PeriodicCadence.CONTINUOUS_AURA,
        ANGUISH: PeriodicCadence.FIXED_INTERVAL,
    }


def test_a_burn_carries_its_window_and_its_tick_from_the_registry() -> None:
    """The two clocks a burn has are two declared numbers, not one."""
    slots = _slots(BURN)
    (burn,) = slots.burns
    assert burn.duration == pytest.approx(sustain_effect_value(BURN, "duration"))
    assert burn.tick_interval == pytest.approx(
        sustain_effect_value(BURN, "tick_interval")
    )
    assert burn.source.breakdown_key == f"burn_{BURN}"
    assert burn.source.display_name == f"{BURN} (burn)"
    assert burn.source.raw_damage(_inputs(ability_power=200.0)) == pytest.approx(
        sustain_effect_value(BURN, "base_total")
        + sustain_effect_value(BURN, "ap_ratio_total") * 200.0
    )


def test_a_max_health_burn_is_a_share_of_the_targets_pool() -> None:
    """The holder/target split the registry's key names could not express."""
    (burn,) = _slots(MAX_HEALTH_BURN).burns
    ratio = sustain_effect_value(MAX_HEALTH_BURN, "max_hp_ratio_total")
    assert burn.source.raw_damage(_inputs()) == pytest.approx(ratio * 2500.0)


def test_an_aura_pays_a_rate_and_publishes_its_own_event_spacing() -> None:
    """``event_interval`` is the aura's field and stays on its row."""
    slots = _slots(AURA, FLAT_AURA)
    assert [source.item_name for source in slots.auras] == [AURA, FLAT_AURA]
    scaling, flat = slots.auras
    assert scaling.event_interval == pytest.approx(
        sustain_effect_value(AURA, "event_interval")
    )
    assert scaling.breakdown_key == f"immolate_{AURA}"
    assert scaling.display_name == f"{AURA} (Immolate)"
    assert scaling.raw_damage(_inputs(bonus_health=1000.0)) == pytest.approx(
        sustain_effect_value(AURA, "base_per_second")
        + sustain_effect_value(AURA, "bonus_hp_ratio_per_second") * 1000.0
    )
    assert flat.raw_damage(_inputs(bonus_health=1000.0)) == pytest.approx(
        sustain_effect_value(FLAT_AURA, "base_per_second")
    )


def test_the_anguish_radius_comes_off_the_declaration_not_the_item_name() -> None:
    """The engine's one remaining periodic name site, retired."""
    slots = _slots(ANGUISH)
    (interval,) = slots.intervals
    assert slots.range_units == {
        interval.source.breakdown_key: pytest.approx(
            sustain_effect_value(ANGUISH, "range_units")
        )
    }
    assert interval.interval == pytest.approx(sustain_effect_value(ANGUISH, "interval"))
    assert interval.self_heal_post_mitigation_multiplier == pytest.approx(
        sustain_effect_value(ANGUISH, "self_heal_post_mitigation_multiplier")
    )
    assert interval.source.breakdown_key == f"periodic_{ANGUISH}"
    assert interval.source.display_name == f"{ANGUISH} (Anguish)"


def test_a_build_with_no_fixed_interval_strike_publishes_no_radius() -> None:
    """An absent radius is an empty map, never a zero standing in for one."""
    slots = _slots(BURN, AURA)
    assert slots.range_units == {}
    assert slots.intervals == ()


def test_the_self_heal_question_is_answered_from_declarations_alone() -> None:
    """The tuple ledger's adequacy read needs no fight to answer."""
    assert periodic.declares_self_heal([ANGUISH])
    assert not periodic.declares_self_heal([BURN, AURA, FLAT_BURN])
    assert not periodic.declares_self_heal([])


def test_a_burn_with_no_declared_window_is_refused_at_validation() -> None:
    """The cadence's required field is checked, not assumed."""
    (rule,) = rules_of([BURN], RuleFamily.PERIODIC)
    unwindowed = type(rule)(
        family=rule.family,
        owner=rule.owner,
        mechanic_id=rule.mechanic_id,
        payload=PeriodicRule(
            formula=rule.payload.formula,
            cadence=PeriodicCadence.REFRESHED_BURN,
            interval=rule.payload.interval,
            duration=None,
            aoe_range_units=None,
            self_heal_share=None,
        ),
        compilability=rule.compilability,
        receipt=rule.receipt,
        zero_policy=rule.zero_policy,
    )
    with pytest.raises(Exception, match="how long that window is"):
        validate_rule(unwindowed)


def test_a_cadence_may_not_carry_another_cadences_field() -> None:
    """Presence is checked in both directions, so neither move is silent."""
    (rule,) = rules_of([ANGUISH], RuleFamily.PERIODIC)
    misplaced = type(rule)(
        family=rule.family,
        owner=rule.owner,
        mechanic_id=rule.mechanic_id,
        payload=PeriodicRule(
            formula=rule.payload.formula,
            cadence=PeriodicCadence.CONTINUOUS_AURA,
            interval=rule.payload.interval,
            duration=None,
            aoe_range_units=rule.payload.aoe_range_units,
            self_heal_share=None,
        ),
        compilability=rule.compilability,
        receipt=rule.receipt,
        zero_policy=rule.zero_policy,
    )
    with pytest.raises(Exception, match="belongs to a different cadence"):
        validate_rule(misplaced)


def test_the_pair_interpreter_compiles_the_cadence_it_can_know() -> None:
    """A clock is a build-time number; the damage it carries is not."""
    (rule,) = rules_of([ANGUISH], RuleFamily.PERIODIC)
    ctx = build_context(
        ANGUISH,
        FightFacts(
            level=18,
            fight_duration_seconds=5.0,
            target_bonus_health=0.0,
            holder_is_melee=True,
        ),
    )
    (field,) = periodic.cadence_fields(rule, ctx, EngineLane.PAIR_ENGINE)
    assert field.name == periodic.PERIODIC_INTERVAL_FIELD
    assert field.value == pytest.approx(sustain_effect_value(ANGUISH, "interval"))
    assert field.rule_id == rule.mechanic_id
