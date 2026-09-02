"""The front door for the cast-proc interpreter.

Three registry tags reached the engine through three compilers, two of which
decided what an item carried by comparing its *name*: Eclipse's self-shield
and Malignance's magic-resistance shred were both ``if item_name == ...``
branches inside the number registry.  What is pinned here is that the sibling
mechanics come off the registry's schema instead, that a group is declared
whole or not at all, that Luden's charge split is still the same float, and
that the row an entry names for itself is still the row the engine publishes.
"""

import pytest

from src.calculator.interpreters import cast_proc
from src.calculator.item_behavior import (
    CooldownProcRule,
    EngineLane,
    ProcTrigger,
    RuleFamily,
    UltimateProcRule,
)
from src.calculator.item_behavior_catalog import behavior_rules, build_context
from src.calculator.item_effects import ITEM_EFFECTS, DamageInputs

CHARGED = "Luden's Echo"
THRESHOLD = "Stormsurge"
REFUNDING = "Scout's Slingshot"
FLAT = "Hextech Alternator"
SHIELDING = "Eclipse"
SHREDDING = "Malignance"
PLAIN_ULTIMATE = "Zeke's Convergence"


def _slots(*owners: str, is_melee: bool = True) -> cast_proc.CastProcSlots:
    """The cast-triggered procs a build of *owners* declares."""
    return cast_proc.resolve_slots(
        owners,
        level=18,
        fight_duration_seconds=5.0,
        target_bonus_health=0.0,
        holder_is_melee=is_melee,
    )


def _inputs(**stats: float) -> DamageInputs:
    """One event's readings for a compiled proc formula."""
    return DamageInputs(
        champion_stats=stats,
        level=18,
        is_melee=True,
        target_max_health=2000.0,
        target_current_health=2000.0,
    )


def test_every_cast_proc_entry_declares_exactly_one_rule() -> None:
    """Counter 3's half: three tags, one family, no engine code left over."""
    tags = frozenset({"proc", "ult_proc", "max_hp_proc"})
    for owner, entry in ITEM_EFFECTS.items():
        if entry.get("type") not in tags:
            continue
        rules = [
            rule
            for rule in behavior_rules(owner)
            if rule.family is RuleFamily.CAST_PROC
        ]
        assert len(rules) == 1, owner
        assert isinstance(rules[0].payload, (CooldownProcRule, UltimateProcRule))


def test_the_trigger_is_read_off_the_entry_and_defaults_to_the_coarse_row() -> None:
    """An entry naming no trigger is on the coarse scheduler, said out loud."""
    declared = {
        rule.owner: rule.payload.trigger
        for rule in cast_proc.cast_proc_rules(
            [THRESHOLD, REFUNDING, CHARGED, SHIELDING]
        )
        if isinstance(rule.payload, CooldownProcRule)
    }
    assert declared == {
        THRESHOLD: ProcTrigger.DAMAGE_THRESHOLD,
        REFUNDING: ProcTrigger.CHAMPION_DAMAGE,
        CHARGED: ProcTrigger.ABILITY_DAMAGE,
        SHIELDING: ProcTrigger.COARSE,
    }


def test_the_charge_split_multiplies_the_sum_and_not_a_share() -> None:
    """``(base + ratio x AP) x k`` is the registry compiler's own float."""
    (proc,) = _slots(CHARGED).cooldown_procs
    entry = ITEM_EFFECTS[CHARGED]
    base = float(entry["base_per_charge"])  # type: ignore[arg-type]
    ratio = float(entry["ap_ratio_per_charge"])  # type: ignore[arg-type]
    multiplier = float(entry["single_target_multiplier"])  # type: ignore[arg-type]
    charges = int(entry["charges"])  # type: ignore[arg-type]
    assert (
        proc.source.raw_damage(_inputs(ability_power=300.0))
        == (base + ratio * 300.0) * multiplier
    )
    assert proc.source.multi_target_charges == charges
    assert proc.source.single_target_multiplier == pytest.approx(multiplier)
    assert proc.source.repeated_target_multiplier == pytest.approx(
        (multiplier - 1.0) / (charges - 1)
    )


def test_a_proc_that_does_not_split_carries_the_engines_neutral_element() -> None:
    """No charges, and a multiplier of one on both targets."""
    (proc,) = _slots(FLAT).cooldown_procs
    assert proc.source.multi_target_charges == cast_proc.NO_CHARGES
    assert proc.source.single_target_multiplier == cast_proc.UNSPLIT_MULTIPLIER
    assert proc.source.repeated_target_multiplier == cast_proc.UNSPLIT_MULTIPLIER


def test_a_damage_threshold_trigger_carries_its_share_and_window() -> None:
    """The two keys are one statement, and only that trigger may make it."""
    (burst,) = _slots(THRESHOLD).cooldown_procs
    entry = ITEM_EFFECTS[THRESHOLD]
    assert burst.trigger == ProcTrigger.DAMAGE_THRESHOLD.value
    assert burst.damage_threshold_ratio == pytest.approx(
        float(entry["damage_threshold_ratio"])  # type: ignore[arg-type]
    )
    assert burst.damage_threshold_window == pytest.approx(
        float(entry["damage_threshold_window"])  # type: ignore[arg-type]
    )
    assert burst.repeat_on_cooldown is False
    (flat,) = _slots(FLAT).cooldown_procs
    assert flat.damage_threshold_ratio == cast_proc.NO_SIBLING
    assert flat.damage_threshold_window == cast_proc.NO_SIBLING


def test_the_shield_group_is_declared_whole_and_only_where_it_exists() -> None:
    """Eclipse's five shield numbers arrive together; nobody else has them."""
    (rule,) = cast_proc.cast_proc_rules([SHIELDING])
    shield = rule.payload.self_shield
    assert shield is not None
    (gated,) = _slots(SHIELDING).cooldown_procs
    entry = ITEM_EFFECTS[SHIELDING]
    assert gated.self_shield_melee_base == pytest.approx(
        float(entry["shield_melee_base"])  # type: ignore[arg-type]
    )
    assert gated.self_shield_duration == pytest.approx(
        float(entry["shield_duration"])  # type: ignore[arg-type]
    )
    assert gated.stack_required == int(entry["stack_required"])  # type: ignore[arg-type]
    assert gated.late_phase is True
    (plain_rule,) = cast_proc.cast_proc_rules([FLAT])
    assert plain_rule.payload.self_shield is None
    assert plain_rule.payload.stacks is None


def test_a_dropped_shield_number_raises_rather_than_shielding_for_zero() -> None:
    """The fail-closed contract holds without the item-name branch."""
    broken = dict(ITEM_EFFECTS[SHIELDING])
    broken.pop("shield_melee_base")
    with pytest.MonkeyPatch.context() as patcher:
        patcher.setitem(ITEM_EFFECTS, SHIELDING, broken)
        with pytest.raises(KeyError, match="shield_melee_base"):
            _slots(SHIELDING)


def test_an_entry_that_names_its_own_row_keeps_it() -> None:
    """Registry-owned presentation survives; everything else is derived."""
    (gated,) = _slots(SHIELDING).cooldown_procs
    entry = ITEM_EFFECTS[SHIELDING]
    assert gated.source.breakdown_key == entry["breakdown_key"]
    assert gated.source.display_name == entry["display_name"]
    (flat,) = _slots(FLAT).cooldown_procs
    assert flat.source.breakdown_key == f"{cast_proc.PROC_BREAKDOWN_PREFIX}{FLAT}"
    assert flat.source.display_name == f"{FLAT} ({cast_proc.PROC_SUFFIX})"


def test_the_ultimate_procs_shred_is_a_declared_absence_where_it_has_none() -> None:
    """Malignance shreds; Zeke's does not, and says so rather than zeroing."""
    shredding, plain = _slots(SHREDDING, PLAIN_ULTIMATE).ultimate_procs
    assert shredding.mr_reduction == pytest.approx(
        float(ITEM_EFFECTS[SHREDDING]["mr_reduction"])  # type: ignore[arg-type]
    )
    assert plain.mr_reduction == cast_proc.NO_SIBLING
    (plain_rule,) = [
        rule
        for rule in cast_proc.cast_proc_rules([PLAIN_ULTIMATE])
        if isinstance(rule.payload, UltimateProcRule)
    ]
    assert plain_rule.payload.mr_reduction is None
    assert shredding.source.breakdown_key == (
        f"{cast_proc.ULTIMATE_PROC_BREAKDOWN_PREFIX}{SHREDDING}"
    )
    assert shredding.source.display_name == (
        f"{SHREDDING} ({cast_proc.ULTIMATE_PROC_SUFFIX})"
    )


def test_the_pair_interpreter_compiles_the_clock_each_shape_has() -> None:
    """A cooldown for one shape, a window for the other, both build-time."""
    for owner, key in ((FLAT, "cooldown"), (SHREDDING, "duration")):
        (rule,) = cast_proc.cast_proc_rules([owner])
        ctx = build_context(
            owner,
            18,
            fight_duration_seconds=5.0,
            target_bonus_health=0.0,
            holder_is_melee=True,
        )
        (field,) = cast_proc.proc_fields(rule, ctx, EngineLane.PAIR_ENGINE)
        assert field.name == cast_proc.PROC_COOLDOWN_FIELD
        assert field.value == pytest.approx(float(ITEM_EFFECTS[owner][key]))  # type: ignore[arg-type]


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
    with pytest.raises(cast_proc.CastProcInterpretationError):
        cast_proc.proc_fields(foreign, ctx, EngineLane.PAIR_ENGINE)
