"""The stat-derivation family's front door: nine ways a stat block is built.

Every case pins a declaration's number against the same registry key the
engine's own accessor in ``item_effects`` reads, because this migration's
claim is that the declarations reproduce the stat fold exactly — nothing here
changes what a fight computes, and a test that proved only "a rule exists"
would not be able to tell those two apart.

The other half is ``availability``.  Three of these grants are conditional
buffs the resolver folds in whole and five exist only when the request's item
options say so, and until this family landed both facts lived in a docstring.
They are asserted here against the accessors that behave that way.
"""

from __future__ import annotations

import pytest

from src.calculator import item_behavior_catalog as catalog
from src.calculator import item_effects
from dataclasses import replace

from src.calculator.interpreters import INTERPRETERS
from src.calculator.interpreters import stat_derivation
from src.calculator.interpreters.stat_derivation import (
    PAIR_INTERPRETER,
    RESOLVER_INTERPRETER,
    StatDerivationInterpretationError,
    declared_stat_derivations,
    stat_derivation_rules,
    stat_slots,
)
from src.calculator.value_ref import LevelValueRef
from src.calculator.item_behavior import (
    ActiveWindowCastEconomyRule,
    DURABILITY_STATS,
    DerivedStat,
    EngineLane,
    FlatStatGrantRule,
    ManaflowRule,
    RuleFamily,
    StackedStatRule,
    StatAuraRule,
    StatAvailability,
    StatBasis,
    StatConversionRule,
    StatMultiplierRule,
    Subject,
    ThresholdRegenRule,
    UltimateRefundRule,
)

CONVERSION_HOLDER = "Muramana"
MULTIPLIER_HOLDER = "Rabadon's Deathcap"
MANAFLOW_HOLDER = "Archangel's Staff"
STACK_HOLDER = "Rod of Ages"
SPLIT_STACK_HOLDER = "Yun Tal Wildarrows"
GRANT_HOLDER = "Experimental Hexplate"
AURA_HOLDER = "Frozen Heart"
REGEN_HOLDER = "Warmog's Armor"
REFUND_HOLDER = "Axiom Arc"
CAST_ECONOMY_HOLDER = "Actualizer"

# The one entry of the family whose whole mechanic another family declares.
ELSEWHERE_HOLDER = "Phage"


def _slot(owner: str, payload_type: type, *, melee: bool = True):
    """The build's one declared derivation of a shape, at a mid-fight level."""
    slots = stat_slots(
        [owner],
        payload_type,
        level=13,
        fight_duration_seconds=5.0,
        target_bonus_health=0.0,
        holder_is_melee=melee,
    )
    assert len(slots) == 1, owner
    return slots[0]


def test_a_conversion_reads_the_ratio_the_stat_fold_reads() -> None:
    """Awe's declaration and ``muramana_bonus_ad``'s number are one number.

    The holder is Muramana and not Manamune deliberately: Awe is filed under
    Muramana's *on-hit* record and reaches this family through
    ``SECONDARY_KEY_FAMILY``, which is the case a tag-only routing would
    have compiled to nothing while the number kept moving builds.
    """
    slot = _slot(CONVERSION_HOLDER, StatConversionRule)
    assert slot.rule.payload.basis is StatBasis.MAX_MANA
    assert slot.granted is DerivedStat.ATTACK_DAMAGE
    assert slot.availability is StatAvailability.ALWAYS
    assert slot.value("ratio") == pytest.approx(
        item_effects.required_effect_value(CONVERSION_HOLDER, "max_mana_to_ad_ratio")
    )
    # And the engine's own accessor pays exactly that share of maximum mana.
    assert item_effects.muramana_bonus_ad(
        [{"name": CONVERSION_HOLDER}], 1000.0
    ) == pytest.approx(slot.value("ratio") * 1000.0)


def test_a_multiplier_names_the_stat_it_multiplies() -> None:
    """Magical Opus is a share of a total, not a rate per unit of something."""
    slot = _slot(MULTIPLIER_HOLDER, StatMultiplierRule)
    assert slot.granted is DerivedStat.ABILITY_POWER
    assert slot.value("share") == pytest.approx(
        item_effects.required_effect_value(MULTIPLIER_HOLDER, "ap_percent_increase")
    )
    assert item_effects.ap_multiplier([{"name": MULTIPLIER_HOLDER}]) == pytest.approx(
        1.0 + slot.value("share")
    )


def test_a_declared_absence_publishes_no_field_at_all() -> None:
    """The optional half of the reference tables, asserted on both sides.

    Tear of the Goddess runs the same charge ledger as Archangel's Staff and
    never transforms, so its declaration carries ``None`` where the other
    carries a reference — and the interpreter must emit *no field*, because a
    published zero ceiling is a ceiling a reader would cap against.
    """
    transforming = _slot(MANAFLOW_HOLDER, ManaflowRule)
    plain = _slot("Tear of the Goddess", ManaflowRule)
    assert transforming.value("transform_bonus_mana") > 0.0
    assert transforming.value("max_charges") > 0.0
    assert plain.rule.payload.transform_bonus_mana is None
    with pytest.raises(StatDerivationInterpretationError, match="declares no"):
        plain.value("transform_bonus_mana")


def test_a_manaflow_ledger_missing_half_its_keys_is_a_stop() -> None:
    """A charge ledger is claimed whole or not at all."""
    entry = dict(item_effects.ITEM_EFFECTS[MANAFLOW_HOLDER])
    with pytest.raises(catalog.BehaviorCatalogError, match="claimed whole"):
        catalog._manaflow_rule(  # noqa: SLF001
            MANAFLOW_HOLDER,
            "ITEM_EFFECTS",
            frozenset(entry) - {"manaflow_bonus_mana_max"},
        )


def test_a_stacked_stat_declares_both_of_its_ceilings() -> None:
    """Yun Tal's crit conversion is bounded by a stack count *and* a cap."""
    slot = _slot(SPLIT_STACK_HOLDER, StackedStatRule)
    assert slot.granted is DerivedStat.CRITICAL_STRIKE_CHANCE
    assert slot.availability is StatAvailability.BUILD_OPTION
    assert slot.value("cap") == pytest.approx(
        item_effects.required_effect_value(SPLIT_STACK_HOLDER, "crit_chance_cap")
    )
    assert slot.value("max_stacks") == pytest.approx(
        item_effects.required_effect_value(SPLIT_STACK_HOLDER, "crit_stack_max_melee")
    )


def test_a_melee_ranged_rate_follows_the_holders_range_class() -> None:
    """Both halves are declared, and the build picks one — never a default."""
    melee = _slot(SPLIT_STACK_HOLDER, StackedStatRule, melee=True)
    ranged = _slot(SPLIT_STACK_HOLDER, StackedStatRule, melee=False)
    assert melee.value("per_stack") == pytest.approx(
        item_effects.required_effect_value(
            SPLIT_STACK_HOLDER, "crit_chance_per_stack_melee"
        )
    )
    assert ranged.value("per_stack") == pytest.approx(
        item_effects.required_effect_value(
            SPLIT_STACK_HOLDER, "crit_chance_per_stack_ranged"
        )
    )
    assert melee.value("per_stack") != ranged.value("per_stack")


def test_one_entry_may_declare_three_stacked_stats() -> None:
    """Timeless grows health, mana and ability power, and says so three times."""
    slots = stat_slots(
        [STACK_HOLDER],
        StackedStatRule,
        level=13,
        fight_duration_seconds=5.0,
        target_bonus_health=0.0,
        holder_is_melee=True,
    )
    assert {slot.granted for slot in slots} == {
        DerivedStat.ABILITY_POWER,
        DerivedStat.HEALTH,
        DerivedStat.MANA,
    }


def test_an_assumed_active_grant_says_so_rather_than_looking_unconditional() -> None:
    """The field this migration exists to add, on the accessor that needs it.

    ``passive_attack_speed_bonus`` folds Overdrive in whole with no event to
    arm it from, which was a docstring.  The declaration says it, and the
    number is still the registry's own.
    """
    grants = {
        slot.granted: slot
        for slot in stat_slots(
            [GRANT_HOLDER],
            FlatStatGrantRule,
            level=13,
            fight_duration_seconds=5.0,
            target_bonus_health=0.0,
            holder_is_melee=True,
        )
    }
    assert grants[DerivedStat.ULTIMATE_HASTE].availability is StatAvailability.ALWAYS
    attack_speed = grants[DerivedStat.ATTACK_SPEED_PERCENT]
    assert attack_speed.availability is StatAvailability.ASSUMED_ACTIVE
    assert attack_speed.value("amount") == pytest.approx(
        item_effects.required_effect_value(GRANT_HOLDER, "bonus_attack_speed_melee")
    )
    assert item_effects.passive_attack_speed_bonus(
        [{"name": GRANT_HOLDER}], True
    ) == pytest.approx(attack_speed.value("amount"))


def test_an_aura_is_the_one_shape_whose_subject_is_the_enemy() -> None:
    """Winter's Caress lands on the target and benefits the holder."""
    slot = _slot(AURA_HOLDER, StatAuraRule)
    assert slot.rule.payload.subject is Subject.TARGET
    assert slot.value("reduction") == pytest.approx(
        item_effects.required_effect_value(AURA_HOLDER, "attack_speed_reduction")
    )
    assert slot.value("radius") > 0.0


def test_the_threshold_regeneration_declares_both_damage_cooldowns() -> None:
    """Two cooldowns and not one: a single 'damage cooldown' would pick one."""
    slot = _slot(REGEN_HOLDER, ThresholdRegenRule)
    assert slot.granted in DURABILITY_STATS
    for name in ("champion_damage_cooldown", "nonchampion_damage_cooldown"):
        assert slot.value(name) == pytest.approx(
            item_effects.required_effect_value(REGEN_HOLDER, f"heart_{name}")
        )
    assert slot.value("champion_damage_cooldown") != slot.value(
        "nonchampion_damage_cooldown"
    )


def test_the_refund_shape_grants_no_stat_and_says_so() -> None:
    """Flux moves a cooldown; naming a DerivedStat would invent one."""
    slot = _slot(REFUND_HOLDER, UltimateRefundRule)
    assert slot.granted is None
    assert slot.value("per_lethality_ratio") == pytest.approx(
        item_effects.required_effect_value(
            REFUND_HOLDER, "ultimate_refund_per_lethality_ratio"
        )
    )


def test_the_cast_economy_shape_grants_no_stat_and_carries_its_window() -> None:
    """The ninth shape: what an open active window costs the holder's casts.

    Like the refund it grants nothing — it moves a cost and a cooldown
    progression — and the window is carried on the rule rather than looked up,
    so a reader holding it can say how long the trade lasts without reaching
    into the amp declared from the same entry.
    """
    slot = _slot(CAST_ECONOMY_HOLDER, ActiveWindowCastEconomyRule)
    assert slot.granted is None
    assert slot.availability is StatAvailability.BUILD_OPTION
    for field, key in (
        ("resource_cost_multiplier", "mana_cost_multiplier"),
        ("basic_cooldown_progress_multiplier", "basic_cooldown_progress_multiplier"),
        ("window", "mana_made_real_duration"),
    ):
        assert slot.value(field) == pytest.approx(
            item_effects.required_effect_value(CAST_ECONOMY_HOLDER, key)
        )


def test_the_cast_economy_lands_beside_the_amp_declared_from_one_entry() -> None:
    """One registry entry, two mechanics, and the secondary-key table says so.

    The entry's tag names the amp, so without the key routing the trade into
    this family the two live multipliers would compile to nothing while their
    numbers kept moving every cast the rotation prices.
    """
    families = [rule.family for rule in catalog.behavior_rules(CAST_ECONOMY_HOLDER)]
    assert families == [RuleFamily.DELTA_AMP, RuleFamily.STAT_DERIVATION]
    assert (
        catalog.SECONDARY_KEY_FAMILY["ITEM_EFFECTS"]["mana_cost_multiplier"]
        is RuleFamily.STAT_DERIVATION
    )


def test_a_build_declaring_no_cast_economy_answers_none_not_a_multiplier() -> None:
    """``None`` is an answer: no window is open, so no cost was multiplied."""
    assert (
        stat_derivation.sole_declared_derivation(["Boots"], ActiveWindowCastEconomyRule)
        is None
    )
    slot = stat_derivation.sole_declared_derivation(
        [CAST_ECONOMY_HOLDER], ActiveWindowCastEconomyRule
    )
    assert slot is not None and slot.owner == CAST_ECONOMY_HOLDER


def test_two_holders_of_a_non_composing_shape_are_a_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing declares how two casting trades compose, so nothing picks one.

    Reached through a planted second holder rather than a real one, because
    the registry carries exactly one today — which is why the refusal needs a
    test at all: a branch no live build reaches is one nobody has run.
    """
    rule = stat_derivation_rules([CAST_ECONOMY_HOLDER], ActiveWindowCastEconomyRule)[0]
    monkeypatch.setattr(
        stat_derivation,
        "stat_derivation_rules",
        lambda owners, kind: (rule, replace(rule, owner="Second Holder")),
    )
    with pytest.raises(StatDerivationInterpretationError, match="how two of them"):
        stat_derivation.sole_declared_derivation(
            [CAST_ECONOMY_HOLDER], ActiveWindowCastEconomyRule
        )


def test_an_entry_whose_whole_mechanic_is_declared_elsewhere_compiles_nothing() -> None:
    """And that is an answer, not a silence: the table says which family has it."""
    rules = catalog.behavior_rules(ELSEWHERE_HOLDER)
    assert rules
    assert all(rule.family is not RuleFamily.STAT_DERIVATION for rule in rules)
    assert "rage_duration" in catalog.STAT_DERIVATION_DECLARED_ELSEWHERE


def test_an_entry_the_family_claims_with_no_signature_key_is_a_stop() -> None:
    """A derivation that derives nothing is a parse that failed."""
    with pytest.raises(catalog.BehaviorCatalogError, match="derives nothing"):
        catalog._compile_stat_derivation(  # noqa: SLF001
            RuleFamily.STAT_DERIVATION,
            "Long Sword",
            "ITEM_EFFECTS",
            {"type": "stat_conversion"},
        )


def test_every_deferred_and_elsewhere_key_is_one_a_live_entry_carries() -> None:
    """The rename guard on both tables of refusals.

    A key either table names and no entry carries would stop matching in
    silence — the elsewhere table would stop excusing an entry and the
    deferred table would date a mechanic nothing has, which is a receipt for
    nothing.
    """
    carried = {
        key
        for owner in catalog.registry_owners()
        for _registry, _family, entry in catalog.registry_entries(owner)
        for key in entry
    }
    for table in (
        catalog.STAT_DERIVATION_DECLARED_ELSEWHERE,
        catalog.STAT_DERIVATION_DEFERRED_MECHANICS,
    ):
        assert table
        for key, reason in table.items():
            assert key in carried, key
            assert reason.strip()


def test_both_lanes_are_registered_and_stamp_their_own_lane() -> None:
    """Two registrations, because a KernelField carries the lane it was built for."""
    for lane, interpreter in (
        (EngineLane.PAIR_ENGINE, PAIR_INTERPRETER),
        (EngineLane.STAT_RESOLVER, RESOLVER_INTERPRETER),
    ):
        assert INTERPRETERS[(RuleFamily.STAT_DERIVATION, lane)] is interpreter
        rule = stat_derivation_rules([MULTIPLIER_HOLDER], StatMultiplierRule)[0]
        fields = interpreter.compile(
            rule,
            catalog.build_context(
                rule.owner,
                13,
                fight_duration_seconds=5.0,
                target_bonus_health=0.0,
                holder_is_melee=True,
            ),
        )
        assert {field.lane for field in fields} == {lane}


def test_the_interpreter_refuses_a_payload_of_another_family() -> None:
    """Asking a stat interpreter for a sustain rule is a stop, not a zero."""
    rule = catalog.behavior_rules("Vampiric Scepter")[0]
    with pytest.raises(StatDerivationInterpretationError, match="not a stat"):
        PAIR_INTERPRETER.compile(
            rule,
            catalog.build_context(
                rule.owner,
                13,
                fight_duration_seconds=5.0,
                target_bonus_health=0.0,
                holder_is_melee=True,
            ),
        )


# ── the fight-free accessor (3.9) ─────────────────────────────────────────


def test_a_threshold_regeneration_resolves_without_inventing_a_fight() -> None:
    """The shape the participant timeline authors its regen ticks from.

    It runs before any walk, so it has no level and no target; every number
    is asserted against the registry key the retired
    ``sustain_effect_value("<item>", key)`` branch read, because reproducing
    those exactly is the migration's whole claim.
    """
    slots = declared_stat_derivations(["Warmog's Armor"], ThresholdRegenRule)
    assert len(slots) == 1
    slot = slots[0]
    assert slot.owner == "Warmog's Armor"
    for field, key in (
        ("bonus_health_threshold", "heart_bonus_health_threshold"),
        ("share_of_max_health", "heart_max_health_ratio_per_tick"),
        ("tick_interval", "heart_tick_interval"),
        ("champion_damage_cooldown", "heart_champion_damage_cooldown"),
    ):
        assert slot.value(field) == item_effects.sustain_effect_value(
            "Warmog's Armor", key
        )


def test_a_build_declaring_no_threshold_regeneration_answers_empty() -> None:
    """No holder regenerates on a threshold, so no rule ran."""
    assert declared_stat_derivations(["Boots"], ThresholdRegenRule) == ()


def test_a_level_ramped_derivation_is_refused_rather_than_guessed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R-05's red, and the reason the two families share one check.

    ``value_ref.resolve_flat`` is what decides "level-independent", so this
    refusal and the sustain family's are the same refusal — a ramp reaching
    a fight-free reader is a stop naming the accessor that has a context.
    """
    rule = next(
        rule for rule in stat_derivation_rules(["Warmog's Armor"], ThresholdRegenRule)
    )
    ramped = replace(
        rule,
        payload=replace(
            rule.payload,
            tick_interval=LevelValueRef(
                "ITEM_EFFECTS",
                rule.owner,
                "heart_tick_interval",
                "heart_tick_interval",
                "linear_1_18",
            ),
        ),
    )
    monkeypatch.setattr(
        stat_derivation, "stat_derivation_rules", lambda owners, kind: (ramped,)
    )
    with pytest.raises(StatDerivationInterpretationError, match="fight fact"):
        declared_stat_derivations(["Warmog's Armor"], ThresholdRegenRule)
