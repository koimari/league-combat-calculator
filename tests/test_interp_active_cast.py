"""The front door for the active-cast interpreter.

Six items used to reach the fight engine through a three-branch formula
ladder inside the number registry.  What is pinned here is that the same rows
now come off declarations, term for term and float for float; that the
level-ramped active reproduces the registry compiler's own interpolation at
both ends of the span and above the cap; and that "this active inherits life
steal" and "this active has no life-steal sibling" are two different
declarations rather than one defaulted zero.
"""

import pytest

from src.calculator.interpreters import active_cast
from src.calculator.item_behavior import ActiveCastRule, RuleFamily
from src.calculator.item_behavior_catalog import behavior_rules, build_context
from src.calculator.item_effects import ITEM_EFFECTS, DamageInputs

LEVEL_RAMPED = "Hextech Gunblade"
LIFESTEALING = "Ravenous Hydra"
PLAIN = "Tiamat"
FLAT_AP = "Hextech Rocketbelt"


def _sources(*owners: str, level: int = 18) -> tuple:
    """The rows a build of *owners* declares."""
    return active_cast.active_sources(
        owners,
        level=level,
        fight_duration_seconds=5.0,
        target_bonus_health=0.0,
        holder_is_melee=True,
    )


def _inputs(level: int = 18, **stats: float) -> DamageInputs:
    """One event's readings for a compiled active formula."""
    return DamageInputs(
        champion_stats=stats,
        level=level,
        is_melee=True,
        target_max_health=2000.0,
        target_current_health=2000.0,
    )


def test_every_active_entry_declares_exactly_one_rule() -> None:
    """Counter 3's half: the tag is no longer engine code in the registry."""
    for owner, entry in ITEM_EFFECTS.items():
        if entry.get("type") != "active":
            continue
        rules = [
            rule
            for rule in behavior_rules(owner)
            if rule.family is RuleFamily.ACTIVE_CAST
        ]
        assert len(rules) == 1, owner
        assert isinstance(rules[0].payload, ActiveCastRule)


def test_a_flat_plus_ability_power_active_sums_its_declared_shares() -> None:
    """The two-term schema, reproduced share for share."""
    (source,) = _sources(FLAT_AP)
    entry = ITEM_EFFECTS[FLAT_AP]
    base = float(entry["base"])  # type: ignore[arg-type]
    ratio = float(entry["ap_ratio"])  # type: ignore[arg-type]
    assert source.raw_damage(_inputs(ability_power=400.0)) == pytest.approx(
        base + ratio * 400.0
    )


def test_the_level_ramp_reaches_both_ends_of_the_registry_span() -> None:
    """The ramp interpolates to the level cap, not to eighteen."""
    entry = ITEM_EFFECTS[LEVEL_RAMPED]
    low = float(entry["base_min"])  # type: ignore[arg-type]
    high = float(entry["base_max"])  # type: ignore[arg-type]
    at_one = _sources(LEVEL_RAMPED, level=1)[0]
    at_cap = _sources(LEVEL_RAMPED, level=20)[0]
    above_cap = _sources(LEVEL_RAMPED, level=25)[0]
    assert at_one.raw_damage(_inputs(level=1)) == pytest.approx(low)
    assert at_cap.raw_damage(_inputs(level=20)) == pytest.approx(high)
    assert above_cap.raw_damage(_inputs(level=25)) == pytest.approx(high)


def test_life_steal_inheritance_is_declared_and_its_absence_is_too() -> None:
    """A declared ``None`` and a sourced rate are different claims."""
    inheriting, plain = _sources(LIFESTEALING, PLAIN)
    declared = float(ITEM_EFFECTS[LIFESTEALING]["lifesteal_effectiveness"])  # type: ignore[arg-type]
    assert inheriting.lifesteal_effectiveness == pytest.approx(declared)
    assert plain.lifesteal_effectiveness == active_cast.NO_INHERITED_LIFESTEAL
    (rule,) = active_cast.active_rules([PLAIN])
    assert rule.payload.lifesteal_effectiveness is None


def test_rows_come_out_in_build_order_with_the_engine_s_own_keys() -> None:
    """Breakdown identity is unchanged by the migration."""
    rows = _sources(PLAIN, FLAT_AP)
    assert [row.item_name for row in rows] == [PLAIN, FLAT_AP]
    assert [row.breakdown_key for row in rows] == [
        f"{active_cast.ACTIVE_BREAKDOWN_PREFIX}{PLAIN}",
        f"{active_cast.ACTIVE_BREAKDOWN_PREFIX}{FLAT_AP}",
    ]
    assert rows[0].display_name == f"{PLAIN} ({active_cast.ACTIVE_SUFFIX})"


def test_the_pair_interpreter_compiles_the_cooldown_it_can_know() -> None:
    """A cooldown is a build-time number; a strike's damage is not."""
    (rule,) = active_cast.active_rules([PLAIN])
    ctx = build_context(
        PLAIN,
        18,
        fight_duration_seconds=5.0,
        target_bonus_health=0.0,
        holder_is_melee=True,
    )
    (field,) = active_cast.PAIR_INTERPRETER.compile(rule, ctx)
    assert field.name == active_cast.ACTIVE_COOLDOWN_FIELD
    assert field.value == pytest.approx(float(ITEM_EFFECTS[PLAIN]["cooldown"]))  # type: ignore[arg-type]
    assert field.rule_id == rule.mechanic_id


def test_a_rule_from_another_family_is_refused_rather_than_priced() -> None:
    """The interpreter refuses what it cannot read instead of returning zero."""
    (foreign,) = [
        rule
        for rule in behavior_rules("Runaan's Hurricane")
        if rule.family is RuleFamily.SECONDARY_TARGET
    ]
    ctx = build_context(
        "Runaan's Hurricane",
        18,
        fight_duration_seconds=5.0,
        target_bonus_health=0.0,
        holder_is_melee=False,
    )
    with pytest.raises(active_cast.ActiveCastInterpretationError):
        active_cast.PAIR_INTERPRETER.compile(foreign, ctx)
