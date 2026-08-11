"""The front door for the charged-strike interpreter.

Four registry tags, four compilers, and two of them decided what an item
carried by comparing its name: Voltaic Cyclosword's temporary lethality was an
``item_name == ...`` branch and Fiendhunter Bolts' empowered-attack window was
assembled inline in the projection loop.  What is pinned here is that all four
shapes are declarations; that "this fires once" is stated rather than being
the value a missing key falls through to; that Kraken Slayer's level-stepped
base and missing-health scaling reproduce the registry compiler's own floats
at every boundary; and that a dropped sibling number raises.
"""

import pytest

from src.calculator.ability_spec import Disposition
from src.calculator.interpreters import charged_strike
from src.calculator.item_behavior import (
    EmpoweredAutoBuffRule,
    EmpoweredHitRule,
    RepeatingStrikeRule,
    RuleFamily,
    ShapedChargeRule,
)
from src.calculator.item_behavior_catalog import behavior_rules, build_context
from src.calculator.item_effects import ITEM_EFFECTS, DamageInputs

ENERGIZED = "Stormrazor"
FIRES_ONCE = "Dead Man's Plate"
MULTI_PROC = "Statikk Shiv"
LETHALITY_WINDOW = "Voltaic Cyclosword"
FLAT_REPEAT = "Hullbreaker"
STEPPED_REPEAT = "Kraken Slayer"
SHAPED = "Bastionbreaker"
BUFF = "Fiendhunter Bolts"


def _slots(*owners: str, level: int = 18, is_melee: bool = True):
    """The charged strikes a build of *owners* declares."""
    return charged_strike.resolve_slots(
        owners,
        level=level,
        fight_duration_seconds=5.0,
        target_bonus_health=0.0,
        holder_is_melee=is_melee,
    )


def _inputs(
    level: int = 18,
    is_melee: bool = True,
    max_health: float = 2000.0,
    current_health: float = 2000.0,
    **stats: float,
) -> DamageInputs:
    """One event's readings for a compiled charged-strike formula."""
    return DamageInputs(
        champion_stats=stats,
        level=level,
        is_melee=is_melee,
        target_max_health=max_health,
        target_current_health=current_health,
    )


def test_every_charged_strike_entry_declares_exactly_one_rule() -> None:
    """Counter 3's half: four tags, one family, no engine code left over."""
    tags = frozenset(
        {"on_hit_once", "on_hit_stacking", "shaped_charge", "ult_empowered_autos"}
    )
    shapes = (
        EmpoweredHitRule,
        RepeatingStrikeRule,
        ShapedChargeRule,
        EmpoweredAutoBuffRule,
    )
    for owner, entry in ITEM_EFFECTS.items():
        if entry.get("type") not in tags:
            continue
        rules = [
            rule
            for rule in behavior_rules(owner)
            if rule.family is RuleFamily.CHARGED_STRIKE
        ]
        assert len(rules) == 1, owner
        assert isinstance(rules[0].payload, shapes)


def test_firing_once_is_declared_rather_than_inherited_from_an_absence() -> None:
    """A count is a statement about the mechanic, not a missing key."""
    (once,) = charged_strike.charged_strike_rules([FIRES_ONCE])
    assert once.payload.max_procs.get() == 1.0
    (several,) = charged_strike.charged_strike_rules([MULTI_PROC])
    assert several.payload.max_procs.get() == pytest.approx(
        float(ITEM_EFFECTS[MULTI_PROC]["empowered_auto_count"])  # type: ignore[arg-type]
    )


def test_the_optional_mechanics_are_declared_records_or_declared_absences() -> None:
    """Energized stacks, the lethality window and the arc, each said or not."""
    (plain,) = charged_strike.charged_strike_rules([FIRES_ONCE])
    assert plain.payload.energized is None
    assert plain.payload.temporary_lethality is None
    assert plain.payload.chain_targets is None
    (voltaic,) = charged_strike.charged_strike_rules([LETHALITY_WINDOW])
    assert voltaic.payload.energized is not None
    assert voltaic.payload.energized.abilities_also_charge is True
    assert voltaic.payload.temporary_lethality is not None
    (statikk,) = charged_strike.charged_strike_rules([MULTI_PROC])
    assert statikk.payload.chain_targets is not None
    assert statikk.payload.energized.abilities_also_charge is False


def test_a_dropped_lethality_number_raises_rather_than_granting_zero() -> None:
    """The fail-closed contract the item-name branch used to buy."""
    broken = dict(ITEM_EFFECTS[LETHALITY_WINDOW])
    broken.pop("temporary_lethality_duration")
    with pytest.MonkeyPatch.context() as patcher:
        patcher.setitem(ITEM_EFFECTS, LETHALITY_WINDOW, broken)
        with pytest.raises(KeyError, match="temporary_lethality_duration"):
            _slots(LETHALITY_WINDOW)


def test_the_stepped_base_is_flat_below_its_level_and_steps_above_it() -> None:
    """The registry compiler's arithmetic, reproduced at every boundary."""
    entry = ITEM_EFFECTS[STEPPED_REPEAT]
    base = float(entry["base_melee"])  # type: ignore[arg-type]
    per_level = float(entry["per_level_melee"])  # type: ignore[arg-type]
    start = int(entry["scaling_start_level"])  # type: ignore[arg-type]
    for level, expected in (
        (start - 1, base),
        (start, base + per_level),
        (start + 1, base + per_level * 2),
        (18, base + per_level * (18 - start + 1)),
    ):
        (strike,) = _slots(STEPPED_REPEAT, level=level).stacking_on_hits
        assert strike.source.raw_damage(_inputs(level=level)) == pytest.approx(expected)


def test_the_missing_health_scaling_multiplies_the_whole_sum() -> None:
    """Full health pays the base; one hit point pays the declared bonus."""
    entry = ITEM_EFFECTS[STEPPED_REPEAT]
    bonus = float(entry["missing_hp_bonus_max"])  # type: ignore[arg-type]
    (strike,) = _slots(STEPPED_REPEAT).stacking_on_hits
    full = strike.source.raw_damage(_inputs(max_health=2000.0, current_health=2000.0))
    nearly_dead = strike.source.raw_damage(
        _inputs(max_health=2000.0, current_health=0.0)
    )
    assert nearly_dead == pytest.approx(full * (1.0 + bonus))
    assert strike.tracks_target_health is True


def test_a_repeat_that_does_not_read_live_health_says_so() -> None:
    """The engine's re-pricing question is answered by the declaration."""
    (flat,) = _slots(FLAT_REPEAT).stacking_on_hits
    assert flat.tracks_target_health is False
    assert flat.hits_required == int(ITEM_EFFECTS[FLAT_REPEAT]["hits_required"])  # type: ignore[arg-type]


def test_the_shaped_charge_supplies_the_shape_its_entry_does_not_name() -> None:
    """Neither a formula name nor a damage type is in the entry, by design."""
    (charge,) = _slots(SHAPED).shaped_charges
    entry = ITEM_EFFECTS[SHAPED]
    assert "formula" not in entry
    assert "damage_type" not in entry
    assert charge.source.damage_type == "true"
    assert charge.cooldown == pytest.approx(float(entry["cooldown"]))  # type: ignore[arg-type]
    assert charge.source.breakdown_key == (
        f"{charged_strike.SHAPED_CHARGE_BREAKDOWN_PREFIX}{SHAPED}"
    )
    assert charge.source.raw_damage(_inputs(lethality=20.0)) == pytest.approx(
        float(entry["base_melee"])  # type: ignore[arg-type]
        + float(entry["lethality_ratio_melee"]) * 20.0  # type: ignore[arg-type]
    )


def test_the_empowered_auto_window_declares_five_numbers_and_no_damage() -> None:
    """The family's one member that changes attacks rather than adding a row."""
    buff = _slots(BUFF).empowered_auto_buff
    assert buff is not None
    entry = ITEM_EFFECTS[BUFF]
    assert buff.item_name == BUFF
    assert buff.empowered_auto_count == int(entry["empowered_auto_count"])  # type: ignore[arg-type]
    assert buff.duration == pytest.approx(float(entry["duration"]))  # type: ignore[arg-type]
    assert buff.reduced_crit_ratio == pytest.approx(
        float(entry["reduced_crit_ratio"])  # type: ignore[arg-type]
    )
    (rule,) = charged_strike.charged_strike_rules([BUFF])
    assert rule.zero_policy.disposition is Disposition.STRUCTURAL_ZERO


def test_a_build_with_no_charged_strike_gets_empty_slots_and_no_buff() -> None:
    """An absence is an answer, and it is not a zero standing in for a rule."""
    slots = _slots()
    assert slots.first_autos == ()
    assert slots.stacking_on_hits == ()
    assert slots.shaped_charges == ()
    assert slots.empowered_auto_buff is None


def test_rows_come_out_in_build_order_with_the_registrys_own_names() -> None:
    """Breakdown identity is unchanged by the migration."""
    slots = _slots(ENERGIZED, FIRES_ONCE)
    assert [row.source.item_name for row in slots.first_autos] == [
        ENERGIZED,
        FIRES_ONCE,
    ]
    assert slots.first_autos[0].source.breakdown_key == (
        ITEM_EFFECTS[ENERGIZED]["breakdown_key"]
    )
    assert slots.first_autos[0].source.display_name == (
        ITEM_EFFECTS[ENERGIZED]["display_name"]
    )


def test_the_pair_interpreter_compiles_the_count_each_shape_has() -> None:
    """A count is a build-time number; the damage it carries is not."""
    (rule,) = charged_strike.charged_strike_rules([FLAT_REPEAT])
    ctx = build_context(
        FLAT_REPEAT,
        18,
        fight_duration_seconds=5.0,
        target_bonus_health=0.0,
        holder_is_melee=True,
    )
    (field,) = charged_strike.PAIR_INTERPRETER.compile(rule, ctx)
    assert field.name == charged_strike.CHARGE_COUNT_FIELD
    assert field.value == pytest.approx(
        float(ITEM_EFFECTS[FLAT_REPEAT]["hits_required"])  # type: ignore[arg-type]
    )


def test_a_rule_from_another_family_is_refused_rather_than_priced() -> None:
    """The interpreter refuses what it cannot read instead of returning zero."""
    (foreign,) = [
        rule
        for rule in behavior_rules("Tiamat")
        if rule.family is RuleFamily.ACTIVE_CAST
    ]
    ctx = build_context(
        "Tiamat",
        18,
        fight_duration_seconds=5.0,
        target_bonus_health=0.0,
        holder_is_melee=True,
    )
    with pytest.raises(charged_strike.ChargedStrikeInterpretationError):
        charged_strike.PAIR_INTERPRETER.compile(foreign, ctx)
