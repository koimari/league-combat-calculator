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

from src.calculator import item_behavior_catalog
from src.calculator.ability_spec import Disposition
from src.calculator.interpreters import charged_strike, rearmed_swings
from src.calculator.interpreters.rule_selection import rules_of
from src.calculator.item_behavior import (
    BehaviorRule,
    EmpoweredAutoBuffRule,
    EmpoweredHitRule,
    EngineLane,
    FightFacts,
    RepeatingStrikeRule,
    RuleFamily,
    ShapedChargeRule,
    SwingScheduleRule,
    validate_rule,
)
from src.calculator.item_behavior_catalog import (
    behavior_rules,
    build_context,
)
from src.calculator.item_effects import (
    ITEM_EFFECTS,
    DamageInputs,
    sustain_effect_value,
)

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
        facts=FightFacts(
            level=level,
            fight_duration_seconds=5.0,
            target_bonus_health=0.0,
            holder_is_melee=is_melee,
        ),
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
    (once,) = rules_of([FIRES_ONCE], RuleFamily.CHARGED_STRIKE)
    assert once.payload.max_procs.get() == 1.0
    (several,) = rules_of([MULTI_PROC], RuleFamily.CHARGED_STRIKE)
    assert several.payload.max_procs.get() == pytest.approx(
        sustain_effect_value(MULTI_PROC, "empowered_auto_count")
    )


def test_the_optional_mechanics_are_declared_records_or_declared_absences() -> None:
    """Energized stacks, the lethality window and the arc, each said or not."""
    (plain,) = rules_of([FIRES_ONCE], RuleFamily.CHARGED_STRIKE)
    assert plain.payload.energized is None
    assert plain.payload.temporary_lethality is None
    assert plain.payload.chain_targets is None
    (voltaic,) = rules_of([LETHALITY_WINDOW], RuleFamily.CHARGED_STRIKE)
    assert voltaic.payload.energized is not None
    assert voltaic.payload.energized.abilities_also_charge is True
    assert voltaic.payload.temporary_lethality is not None
    (statikk,) = rules_of([MULTI_PROC], RuleFamily.CHARGED_STRIKE)
    assert statikk.payload.chain_targets is not None
    assert statikk.payload.energized.abilities_also_charge is False


def test_a_dropped_lethality_number_raises_rather_than_granting_zero() -> None:
    """The fail-closed contract holds without an item-name branch."""
    broken = dict(ITEM_EFFECTS[LETHALITY_WINDOW])
    broken.pop("temporary_lethality_duration")
    with pytest.MonkeyPatch.context() as patcher:
        patcher.setitem(ITEM_EFFECTS, LETHALITY_WINDOW, broken)
        with pytest.raises(KeyError, match="temporary_lethality_duration"):
            _slots(LETHALITY_WINDOW)


def test_the_stepped_base_is_flat_below_its_level_and_steps_above_it() -> None:
    """The registry compiler's arithmetic, reproduced at every boundary."""
    base = sustain_effect_value(STEPPED_REPEAT, "base_melee")
    per_level = sustain_effect_value(STEPPED_REPEAT, "per_level_melee")
    start = int(sustain_effect_value(STEPPED_REPEAT, "scaling_start_level"))
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
    bonus = sustain_effect_value(STEPPED_REPEAT, "missing_hp_bonus_max")
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
    assert flat.hits_required == int(sustain_effect_value(FLAT_REPEAT, "hits_required"))


def test_the_shaped_charge_supplies_the_shape_its_entry_does_not_name() -> None:
    """Neither a formula name nor a damage type is in the entry, by design."""
    (charge,) = _slots(SHAPED).shaped_charges
    entry = ITEM_EFFECTS[SHAPED]
    assert "formula" not in entry
    assert "damage_type" not in entry
    assert charge.source.damage_type == "true"
    assert charge.cooldown == pytest.approx(sustain_effect_value(SHAPED, "cooldown"))
    assert charge.source.breakdown_key == (
        f"{charged_strike.SHAPED_CHARGE_BREAKDOWN_PREFIX}{SHAPED}"
    )
    assert charge.source.raw_damage(_inputs(lethality=20.0)) == pytest.approx(
        sustain_effect_value(SHAPED, "base_melee")
        + sustain_effect_value(SHAPED, "lethality_ratio_melee") * 20.0
    )


def test_the_empowered_auto_window_declares_five_numbers_and_no_damage() -> None:
    """The family's one member that changes attacks rather than adding a row."""
    buff = _slots(BUFF).empowered_auto_buff
    assert buff is not None
    assert buff.item_name == BUFF
    assert buff.empowered_auto_count == int(
        sustain_effect_value(BUFF, "empowered_auto_count")
    )
    assert buff.duration == pytest.approx(sustain_effect_value(BUFF, "duration"))
    assert buff.reduced_crit_ratio == pytest.approx(
        sustain_effect_value(BUFF, "reduced_crit_ratio")
    )
    (rule,) = rules_of([BUFF], RuleFamily.CHARGED_STRIKE)
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
    (rule,) = rules_of([FLAT_REPEAT], RuleFamily.CHARGED_STRIKE)
    ctx = build_context(
        FLAT_REPEAT,
        FightFacts(
            level=18,
            fight_duration_seconds=5.0,
            target_bonus_health=0.0,
            holder_is_melee=True,
        ),
    )
    (field,) = charged_strike.strike_fields(rule, ctx, EngineLane.PAIR_ENGINE)
    assert field.name == charged_strike.CHARGE_COUNT_FIELD
    assert field.value == pytest.approx(
        sustain_effect_value(FLAT_REPEAT, "hits_required")
    )


# ── the swing schedule ────────────────────────────────────────────────────
#
# The fifth shape, and the one the retired item-name reads reached: two call
# paths in ``damage.py`` — the auto-count block and the swing-time block —
# each asked whether the build held one of two items, and a third read the
# registry for one of those names to strip its window from the opening rate.
# What is pinned here is that the two mechanics are declarations, that the
# walk reproduces the schedule the retired helper produced, and that the
# one-rotation gate is a declared axis rather than an item comparison.

RAMP = "Guinsoo's Rageblade"
WINDOW = "Yun Tal Wildarrows"


def _schedule(*owners: str):
    """The swing schedule a build of *owners* declares."""
    return _slots(*owners).swing_schedule


def _swing_rule(owner: str):
    """*owner*'s one swing-schedule declaration."""
    (rule,) = [
        rule
        for rule in behavior_rules(owner)
        if isinstance(rule.payload, SwingScheduleRule)
    ]
    return rule


def test_the_two_swing_mechanics_are_declared_shapes() -> None:
    """A ramp the attacks build and a window the attacks re-arm."""
    ramp = _schedule(RAMP)
    assert ramp is not None
    assert ramp.window is None
    assert ramp.ramp == rearmed_swings.DecayingStackRamp(
        per_stack=sustain_effect_value(RAMP, "seething_attack_speed_per_stack"),
        max_stacks=int(sustain_effect_value(RAMP, "seething_max_stacks")),
        stack_duration=sustain_effect_value(RAMP, "seething_duration"),
    )
    window = _schedule(WINDOW)
    assert window is not None
    assert window.ramp is None
    assert window.window == rearmed_swings.RearmedWindow(
        bonus_percent=sustain_effect_value(WINDOW, "bonus_attack_speed_percent"),
        duration=sustain_effect_value(WINDOW, "duration"),
        cooldown=sustain_effect_value(WINDOW, "cooldown"),
        refund_per_attack=sustain_effect_value(WINDOW, "attack_refund_base"),
        refund_per_crit=sustain_effect_value(WINDOW, "attack_refund_crit"),
    )


def test_a_build_declaring_no_swing_mechanic_says_so_rather_than_zeroing() -> None:
    """``None`` is the instruction to rate the stream flat, not a zero rate."""
    assert _schedule() is None
    assert _schedule(FIRES_ONCE) is None


def test_two_declarations_merge_into_the_one_schedule_the_stream_has() -> None:
    """One attack stream, one schedule, both mechanics live on it."""
    merged = _schedule(RAMP, WINDOW)
    assert merged is not None
    assert merged.ramp == _schedule(RAMP).ramp
    assert merged.window == _schedule(WINDOW).window


def test_the_ramp_is_patch_sourced_and_capped() -> None:
    """8% per stack, four stacks = 32%, and nothing above the cap."""
    ramp = _schedule(RAMP).ramp
    assert ramp.bonus_percent(0) == 0.0
    assert ramp.bonus_percent(1) == pytest.approx(8.0)
    assert ramp.bonus_percent(4) == pytest.approx(32.0)
    assert ramp.bonus_percent(99) == pytest.approx(32.0)


def test_the_ramp_accelerates_the_stream_after_stacks() -> None:
    """Later intervals are shorter than the first, which carries no bonus.

    The first interval is the BARE rate: "basic attacks grant 8% bonus
    attack speed" is the attack granting it, so the attack that lands a
    stack cannot be rated by it. At one attack per second that is exactly
    1.0s, and the second interval carries the one stack the first attack
    left behind.
    """
    times = rearmed_swings.swing_times(
        _schedule(RAMP),
        attack_speed=1.0,
        attack_speed_ratio=1.0,
        duration_seconds=5.0,
    )
    assert times[0] == 0.0
    assert len(times) > 5
    assert times[1] - times[0] == pytest.approx(1.0)
    assert times[2] - times[1] == pytest.approx(1.0 / 1.08)
    assert times[2] - times[1] < times[1] - times[0]


def test_the_ramp_does_not_accumulate_stale_stacks() -> None:
    """At this rate each stack expires before the next hit, so NONE stays live.

    The bare interval is five seconds and a stack lives three, so every
    stack is gone before the attack that would have spent it and the stream
    never leaves its base rate.
    """
    times = rearmed_swings.swing_times(
        _schedule(RAMP),
        attack_speed=0.2,
        attack_speed_ratio=1.0,
        duration_seconds=12.0,
    )
    assert times[-1] - times[-2] == pytest.approx(5.0)


def test_the_window_starts_after_the_first_attack() -> None:
    """The fight opens at the bare rate; the window is live from swing two."""
    times = rearmed_swings.swing_times(
        _schedule(WINDOW),
        attack_speed=1.0,
        attack_speed_ratio=1.0,
        duration_seconds=3.0,
    )
    assert times[0] == 0.0
    assert times[1] == pytest.approx(1.0)
    assert times[2] - times[1] < 1.0


def test_the_window_reads_the_registrys_numbers_and_not_a_literal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A moved registry number moves the schedule, per rule 5."""
    patched = dict(ITEM_EFFECTS[WINDOW])
    patched["bonus_attack_speed_percent"] = 60.0
    patched["duration"] = 2.0
    monkeypatch.setitem(ITEM_EFFECTS, WINDOW, patched)
    times = rearmed_swings.swing_times(
        _schedule(WINDOW),
        attack_speed=1.0,
        attack_speed_ratio=1.0,
        duration_seconds=3.0,
    )
    assert times[2] - times[1] == pytest.approx(1.0 / 1.6)


def test_the_refund_weights_the_crit_share_by_the_holders_chance() -> None:
    """The refund is this window's own cooldown, weighted and clamped."""
    window = _schedule(WINDOW).window
    assert window.refund(0.0) == pytest.approx(window.refund_per_attack)
    assert window.refund(1.0) == pytest.approx(
        window.refund_per_attack + window.refund_per_crit
    )
    assert window.refund(4.0) == pytest.approx(window.refund(1.0))


def test_the_one_rotation_gate_is_a_declared_axis() -> None:
    """The ramp is excluded from a one-rotation fight; the window is not."""
    assert _schedule(RAMP).schedules(one_rotation=False) is True
    assert _schedule(RAMP).schedules(one_rotation=True) is False
    assert _schedule(WINDOW).schedules(one_rotation=True) is True
    assert _schedule(RAMP, WINDOW).schedules(one_rotation=True) is True


def test_the_opening_rate_gives_back_exactly_what_the_walk_re_applies() -> None:
    """The panel carries the assumed-active window; the fight opens without it."""
    assert _schedule(WINDOW).opening_rate_bonus_percent == pytest.approx(
        sustain_effect_value(WINDOW, "bonus_attack_speed_percent")
    )
    assert _schedule(RAMP).opening_rate_bonus_percent == 0.0


def test_a_swing_schedule_compiles_to_its_ramp_ceiling_and_no_damage() -> None:
    """A schedule is not spent, so what it compiles to is the ramp's ceiling."""
    ctx = build_context(
        RAMP,
        FightFacts(
            level=18,
            fight_duration_seconds=5.0,
            target_bonus_health=0.0,
            holder_is_melee=True,
        ),
    )
    rule = _swing_rule(RAMP)
    (field,) = charged_strike.strike_fields(rule, ctx, EngineLane.PAIR_ENGINE)
    assert field.value == pytest.approx(
        sustain_effect_value(RAMP, "seething_max_stacks")
    )
    assert rule.zero_policy.disposition is Disposition.STRUCTURAL_ZERO


def test_a_window_only_schedule_compiles_to_the_no_sibling_spelling() -> None:
    """No ramp is a declared absence, not a stack count that measured zero."""
    ctx = build_context(
        WINDOW,
        FightFacts(
            level=18,
            fight_duration_seconds=5.0,
            target_bonus_health=0.0,
            holder_is_melee=True,
        ),
    )
    (field,) = charged_strike.strike_fields(
        _swing_rule(WINDOW), ctx, EngineLane.PAIR_ENGINE
    )
    assert field.value == charged_strike.NO_SIBLING


def test_a_schedule_that_schedules_nothing_is_refused() -> None:
    """A rule carrying neither mechanic raises rather than rating a stream."""
    live = _swing_rule(RAMP)
    with pytest.raises(ValueError, match="one that schedules neither"):
        validate_rule(
            BehaviorRule(
                family=RuleFamily.CHARGED_STRIKE,
                owner=RAMP,
                mechanic_id="synthetic.swing_rate",
                payload=SwingScheduleRule(None, None, False),
                compilability=live.compilability,
                receipt=live.receipt,
                zero_policy=live.zero_policy,
            )
        )


def test_a_half_declared_key_group_raises_naming_the_missing_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Half a schedule re-rates the stream with a number nobody sourced."""
    patched = {
        key: value
        for key, value in ITEM_EFFECTS[RAMP].items()
        if key != "seething_duration"
    }
    monkeypatch.setitem(ITEM_EFFECTS, RAMP, patched)
    monkeypatch.setattr(
        item_behavior_catalog,
        "_schema_keys",
        lambda source, entry: frozenset(entry),
    )
    with pytest.raises(RuntimeError, match="seething_duration"):
        behavior_rules(RAMP)
