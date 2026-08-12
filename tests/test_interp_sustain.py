"""The sustain family's front door: eight ways health comes back.

Six of them are the holder's own — a vampirism stat, a flat on-hit heal, a
share of damage dealt, a resource drain, a heal bought with mana, and a
regeneration window — the seventh multiplies everything the subject
receives, which is why the defensive resolver builds it after every shield,
and the eighth adds a share to what it receives once the fight has taken it
below half health, which is why the walk reads that one through its own lane.

The tests pin the numbers against the registry keys the retired name
branches read, because this migration's claim is that the declarations
reproduce them exactly.
"""

from __future__ import annotations

import pytest

from src.calculator import item_behavior_catalog as catalog
from src.calculator import item_effects
from src.calculator.defensive_effects import resolve_starting_defenses
from dataclasses import replace

from src.calculator.interpreters import INTERPRETERS, compilability_for
from src.calculator.interpreters import sustain
from src.calculator.interpreters.sustain import (
    PAIR_INTERPRETER,
    RESOLVER_INTERPRETER,
    WALK_INTERPRETER,
    SustainInterpretationError,
    declared_sustain,
    received_healing_multiplier,
    stat_grants,
    sustain_slot,
    walk_slot,
)
from src.calculator.value_ref import LevelValueRef, ValueRef
from src.calculator.item_behavior import (
    BelowHalfHealingRule,
    DefenseMechanic,
    EngineLane,
    ManaSpentHealRule,
    MeleeRangedSplit,
    OnHitHealRule,
    PostMitigationHealRule,
    ReceiptOnly,
    ReceiptScope,
    ReceivedHealingRule,
    RegenerationRule,
    ResourceDrainRule,
    RuleFamily,
    Subject,
    SustainStat,
    SustainStatRule,
)

DRAIN_HOLDER = "Doran's Ring"
HEAL_HOLDER = "Doran's Blade"
MANA_HOLDER = "Catalyst of Aeons"
REGEN_HOLDER = "Doran's Shield"
ON_HIT_HOLDER = "Cull"
LIFESTEAL_HOLDER = "Vampiric Scepter"
MULTIPLIER_HOLDER = "Spirit Visage"
BELOW_HALF_HOLDER = "Immortal Path"


def _slot(owner: str, payload_type: type):
    """The build's declared sustain of one shape, at a mid-fight level."""
    return sustain_slot(
        [owner],
        payload_type,
        level=13,
        fight_duration_seconds=5.0,
        target_bonus_health=0.0,
        holder_is_melee=True,
    )


def _rule(owner: str, payload_type: type):
    """The live rule *owner* declares with a payload of *payload_type*."""
    for rule in catalog.behavior_rules(owner):
        if isinstance(rule.payload, payload_type):
            return rule
    raise AssertionError(f"{owner} declares no {payload_type.__name__}")


def test_all_three_lanes_are_registered() -> None:
    """The pair engine prices the holder's own shapes, the resolver builds the
    received-healing multiplier, and the walk compiles what it pays out itself."""
    assert (
        INTERPRETERS[(RuleFamily.SUSTAIN, EngineLane.PAIR_ENGINE)] is PAIR_INTERPRETER
    )
    assert (
        INTERPRETERS[(RuleFamily.SUSTAIN, EngineLane.DEFENSE_RESOLVER)]
        is RESOLVER_INTERPRETER
    )
    assert (
        INTERPRETERS[(RuleFamily.SUSTAIN, EngineLane.RECEIPT_WALK)] is WALK_INTERPRETER
    )
    assert WALK_INTERPRETER.FAMILY is RuleFamily.SUSTAIN
    assert WALK_INTERPRETER.LANES == frozenset({EngineLane.RECEIPT_WALK})


def test_every_sustain_entry_declares_a_rule() -> None:
    """Every owner the family covers reaches a declaration."""
    for owner in (
        DRAIN_HOLDER,
        HEAL_HOLDER,
        MANA_HOLDER,
        REGEN_HOLDER,
        ON_HIT_HOLDER,
        LIFESTEAL_HOLDER,
        MULTIPLIER_HOLDER,
    ):
        families = [rule.family for rule in catalog.behavior_rules(owner)]
        assert RuleFamily.SUSTAIN in families
        assert owner not in catalog.undeclared_owners()


@pytest.mark.parametrize(
    ("owner", "payload_type", "fields"),
    [
        (
            HEAL_HOLDER,
            PostMitigationHealRule,
            {
                "ratio": "direct_heal_post_mitigation_ratio",
                "area_effectiveness": "direct_heal_aoe_effectiveness",
            },
        ),
        (
            DRAIN_HOLDER,
            ResourceDrainRule,
            {
                "restoration_per_second": "drain_restoration_per_second",
                "combat_restoration_per_second": "drain_combat_restoration_per_second",
                "combat_window": "drain_combat_duration",
                "health_conversion": "drain_health_conversion",
                "tick_interval": "drain_tick_interval",
            },
        ),
        (
            MANA_HOLDER,
            ManaSpentHealRule,
            {
                "heal_ratio": "mana_spent_heal_ratio",
                "cap_per_cast": "mana_spent_heal_cap_per_cast",
                "cap_per_second": "mana_spent_heal_cap_per_second",
                "damage_taken_to_mana_ratio": "damage_taken_to_mana_ratio",
            },
        ),
        (
            REGEN_HOLDER,
            RegenerationRule,
            {
                "total_melee": "enduring_focus_total_melee",
                "total_reduced": "enduring_focus_total_reduced",
                "duration": "enduring_focus_duration",
                "missing_health_cap": "enduring_focus_missing_health_cap",
                "tick_interval": "health_regen_tick_interval",
            },
        ),
        (ON_HIT_HOLDER, OnHitHealRule, {"amount": "health_per_on_hit"}),
    ],
)
def test_each_shape_resolves_the_registry_keys_the_branch_read(
    owner, payload_type, fields
) -> None:
    """Every declared field is the registry number, read rather than carried."""
    slot = _slot(owner, payload_type)
    assert slot is not None
    assert slot.owner == owner
    for name, key in fields.items():
        assert slot.value(name) == pytest.approx(
            item_effects.required_effect_value(owner, key)
        )


def test_a_field_the_declaration_does_not_carry_is_a_stop() -> None:
    """A sustain rule answers the questions it declared and refuses the rest."""
    slot = _slot(DRAIN_HOLDER, ResourceDrainRule)
    assert slot is not None
    with pytest.raises(SustainInterpretationError, match="declares no"):
        slot.value("heal_ratio")


def test_nobody_sustaining_is_an_answer_not_a_zero() -> None:
    """A build with no drain gets ``None``, never a rate of zero."""
    assert _slot("Boots", ResourceDrainRule) is None


def test_a_stat_grant_says_which_stat_and_whether_it_corrects() -> None:
    """Life steal adds; the retired omnivamp is a correction and says so."""
    lifesteal = _rule(LIFESTEAL_HOLDER, SustainStatRule).payload
    assert lifesteal.stat is SustainStat.LIFESTEAL_PERCENT
    assert lifesteal.overrides_cached_stat is False
    override = _rule(HEAL_HOLDER, SustainStatRule).payload
    assert override.stat is SustainStat.OMNIVAMP_PERCENT
    assert override.overrides_cached_stat is True


def test_stat_grants_sum_across_holders() -> None:
    """Two life-steal items really do stack, so grants fold rather than refuse."""
    grants = stat_grants(
        [LIFESTEAL_HOLDER, "Mercurial Scimitar"], SustainStat.LIFESTEAL_PERCENT
    )
    assert {rule.owner for rule in grants} == {LIFESTEAL_HOLDER, "Mercurial Scimitar"}


def test_two_drains_stop_rather_than_compose_silently() -> None:
    """Nothing declares how two drains compose, so a second holder is a stop."""
    with pytest.raises(SustainInterpretationError, match="compose"):
        sustain_slot(
            [DRAIN_HOLDER, DRAIN_HOLDER],
            ResourceDrainRule,
            level=13,
            fight_duration_seconds=5.0,
            target_bonus_health=0.0,
            holder_is_melee=True,
        )


def test_every_sustain_rule_acts_on_its_holder() -> None:
    """A heal aimed anywhere else is an ally packet, and the validator says so."""
    for owner, payload_type in (
        (HEAL_HOLDER, PostMitigationHealRule),
        (DRAIN_HOLDER, ResourceDrainRule),
        (MANA_HOLDER, ManaSpentHealRule),
        (REGEN_HOLDER, RegenerationRule),
        (ON_HIT_HOLDER, OnHitHealRule),
        (LIFESTEAL_HOLDER, SustainStatRule),
    ):
        assert _rule(owner, payload_type).payload.subject is Subject.HOLDER


def test_the_received_multiplier_is_read_off_its_declaration() -> None:
    """Spirit Visage's number comes from the rule, not from a name lookup."""
    rule = _rule(MULTIPLIER_HOLDER, ReceivedHealingRule)
    assert received_healing_multiplier(rule) == pytest.approx(
        item_effects.required_effect_value(
            MULTIPLIER_HOLDER, "shield_received_multiplier"
        )
    )


def test_the_multiplier_reaches_the_resolved_defensive_state() -> None:
    """The fold still happens where the ledger lives, from the declaration."""
    stats = {
        "health": 2000.0,
        "bonus_health": 500.0,
        "armor": 100.0,
        "magic_resistance": 60.0,
        "is_melee": True,
    }
    defenses = resolve_starting_defenses(
        "Garen", 13, stats, [{"name": MULTIPLIER_HOLDER}]
    )
    multiplier = item_effects.required_effect_value(
        MULTIPLIER_HOLDER, "shield_received_multiplier"
    )
    assert defenses.healing_received_multiplier == pytest.approx(multiplier)
    assert any(
        citation.mechanic is DefenseMechanic.BOUNDLESS_VITALITY
        and citation.owner == MULTIPLIER_HOLDER
        for citation in defenses.sources
    )


def test_the_published_share_is_interpolated_from_the_declared_number() -> None:
    """The note's percentage is derived, so prose cannot outrun the registry."""
    stats = {
        "health": 2000.0,
        "bonus_health": 500.0,
        "armor": 100.0,
        "magic_resistance": 60.0,
        "is_melee": True,
    }
    defenses = resolve_starting_defenses(
        "Garen", 13, stats, [{"name": MULTIPLIER_HOLDER}]
    )
    share = (
        item_effects.required_effect_value(
            MULTIPLIER_HOLDER, "shield_received_multiplier"
        )
        - 1.0
    )
    assert any(f"{share:.0%}" in note for note in defenses.assumptions)


def test_the_pair_interpreter_refuses_the_received_multiplier() -> None:
    """The multiplier is the resolver's; asking the pair lane is a stop."""
    rule = _rule(MULTIPLIER_HOLDER, ReceivedHealingRule)
    with pytest.raises(SustainInterpretationError, match="defensive"):
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


def test_a_flat_shape_resolves_without_inventing_a_fight() -> None:
    """The three shapes the pipeline and the roster ledger author from.

    Each is read where no fight context exists yet, and each number is the
    same one the retired ``sustain_effect_value("<item>", key)`` branch read
    — which is this migration's whole claim, so it is asserted against the
    registry rather than against a copy of itself.
    """
    for payload_type, owner, field, key in (
        (
            PostMitigationHealRule,
            "Doran's Blade",
            "ratio",
            "direct_heal_post_mitigation_ratio",
        ),
        (
            ResourceDrainRule,
            "Doran's Ring",
            "health_conversion",
            "drain_health_conversion",
        ),
        (
            ManaSpentHealRule,
            "Catalyst of Aeons",
            "damage_taken_to_mana_ratio",
            "damage_taken_to_mana_ratio",
        ),
    ):
        slot = declared_sustain([owner], payload_type)
        assert slot is not None
        assert slot.owner == owner
        assert slot.value(field) == item_effects.sustain_effect_value(owner, key)


def test_a_build_declaring_none_answers_none_rather_than_zero() -> None:
    """No holder restores health this way, so no rule ran."""
    assert declared_sustain(["Boots"], ManaSpentHealRule) is None


def test_a_context_dependent_shape_is_refused_rather_than_guessed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R-05's red: the accessor cannot answer for a shape it cannot resolve.

    A level ramp needs a level and this accessor has none.  Returning the
    ramp's low end would be a number nobody asked for, so the refusal names
    the shape and points at ``sustain_slot``, which is handed a context.  The
    shape is fabricated because no live rule has one — which is exactly why
    the branch would otherwise never be exercised (D-26).
    """
    rule = _rule("Doran's Blade", PostMitigationHealRule)
    ramped = replace(
        rule,
        payload=replace(
            rule.payload,
            ratio=LevelValueRef(
                "ITEM_EFFECTS",
                rule.owner,
                "direct_heal_post_mitigation_ratio",
                "direct_heal_post_mitigation_ratio",
                "linear_1_18",
            ),
        ),
    )
    monkeypatch.setattr(sustain, "sustain_rules", lambda owners, kind: (ramped,))
    with pytest.raises(SustainInterpretationError, match="fight fact"):
        declared_sustain([rule.owner], PostMitigationHealRule)


def test_the_below_half_bonus_is_the_registry_number_the_walk_used_to_read() -> None:
    """The declaration reproduces the key ``receipt_state`` read by name.

    This migration's whole claim: the walk's below-half bonus is the same
    sourced number it always was, reached through a rule instead of through
    an item name and a registry accessor.
    """
    slot = walk_slot([BELOW_HALF_HOLDER], BelowHalfHealingRule)
    assert slot is not None
    assert slot.owner == BELOW_HALF_HOLDER
    assert slot.value("bonus") == item_effects.sustain_effect_value(
        BELOW_HALF_HOLDER, "health_state_healing_multiplier_below_half"
    )


def test_the_walk_accessor_and_the_walk_interpreter_are_one_answer() -> None:
    """``walk_slot`` is :meth:`SustainWalkInterpreter.compile`, field for field.

    Two entry points onto one arithmetic home, which is what stops the
    registered interpreter and the accessor the boundary calls from drifting
    into two answers for one declaration — the shape of failure this campaign
    exists to remove.
    """
    rule = _rule(BELOW_HALF_HOLDER, BelowHalfHealingRule)
    slot = walk_slot([BELOW_HALF_HOLDER], BelowHalfHealingRule)
    assert slot is not None
    assert slot.fields == WALK_INTERPRETER.compile(
        rule,
        catalog.build_context(
            rule.owner,
            13,
            fight_duration_seconds=5.0,
            target_bonus_health=0.0,
            holder_is_melee=True,
        ),
    )
    assert {field.lane for field in slot.fields} == {EngineLane.RECEIPT_WALK}


def test_the_walk_lane_answers_none_rather_than_zero_for_a_build_without_one() -> None:
    """No holder declares the shape, so no rule ran — an answer, not a zero."""
    assert walk_slot(["Boots"], BelowHalfHealingRule) is None


def test_the_below_half_rule_is_receipt_only_in_the_ledger_scope() -> None:
    """The score ledger cannot stage a boundary crossing it never simulates.

    The refusal is scoped: it is the *survival ledger* that cannot stage the
    transition, not the amp kernel, and folding the two scopes into one
    verdict would fall a build back for a reason the build-level gate does
    not own.
    """
    rule = _rule(BELOW_HALF_HOLDER, BelowHalfHealingRule)
    assert isinstance(rule.compilability, ReceiptOnly)
    assert rule.compilability.scope is ReceiptScope.SURVIVAL_LEDGER_TRANSITION
    assert isinstance(
        compilability_for(BELOW_HALF_HOLDER, ReceiptScope.SURVIVAL_LEDGER_TRANSITION),
        ReceiptOnly,
    )


# ── the grant a ramp arms ─────────────────────────────────────────────────
#
# The ninth shape and the last of this family the engines reached by name:
# `damage.py` asked `has_item(items, "Riftmaker")` before adding Void
# Corruption's omnivamp to a private copy of the resolved stats, and
# `pipeline.py` spelled the same name again to decide whether the light
# tuple ledger was adequate.  Both now ask the declarations which of the
# build's grants the *stat block does not already carry*.

SATURATING_HOLDER = "Riftmaker"


def _saturating_rule():
    """Riftmaker's ramp-armed omnivamp declaration."""
    (rule,) = [
        rule
        for rule in catalog.behavior_rules(SATURATING_HOLDER)
        if isinstance(rule.payload, SustainStatRule)
    ]
    return rule


def test_the_ramp_armed_grant_is_declared_with_the_ramp_that_arms_it() -> None:
    """The arming time is never sourced: it is the ramp's own two numbers."""
    payload = _saturating_rule().payload
    assert payload.stat is SustainStat.OMNIVAMP_PERCENT
    assert payload.overrides_cached_stat is False
    assert payload.arms_at.per_second == ValueRef(
        "ITEM_EFFECTS", SATURATING_HOLDER, "amp_per_second"
    )
    assert payload.arms_at.maximum == ValueRef(
        "ITEM_EFFECTS", SATURATING_HOLDER, "amp_max"
    )
    assert payload.percent == MeleeRangedSplit(
        melee=ValueRef("ITEM_EFFECTS", SATURATING_HOLDER, "max_stack_omnivamp"),
        ranged=ValueRef("ITEM_EFFECTS", SATURATING_HOLDER, "max_stack_omnivamp_ranged"),
    )


def test_an_ordinary_grant_declares_no_ramp_rather_than_an_instant_one() -> None:
    """``None`` says the stat block already holds it, from the first tick."""
    ordinary = [
        rule.payload
        for owner in ("Vampiric Scepter", "Doran's Blade")
        for rule in catalog.behavior_rules(owner)
        if isinstance(rule.payload, SustainStatRule)
    ]
    assert ordinary
    assert all(payload.arms_at is None for payload in ordinary)


def test_the_grant_pays_only_a_fight_long_enough_to_saturate_the_ramp() -> None:
    """2% per second to an 8% ceiling is four seconds, melee and ranged."""
    entry = item_effects.ITEM_EFFECTS[SATURATING_HOLDER]
    for is_melee, key in (
        (True, "max_stack_omnivamp"),
        (False, "max_stack_omnivamp_ranged"),
    ):
        assert (
            sustain.saturating_stat_percent(
                [SATURATING_HOLDER],
                SustainStat.OMNIVAMP_PERCENT,
                fight_duration_seconds=3.99,
                holder_is_melee=is_melee,
            )
            == 0.0
        )
        assert sustain.saturating_stat_percent(
            [SATURATING_HOLDER],
            SustainStat.OMNIVAMP_PERCENT,
            fight_duration_seconds=4.0,
            holder_is_melee=is_melee,
        ) == pytest.approx(entry[key])


def test_the_grants_the_stat_block_already_holds_are_not_summed_again() -> None:
    """Filtering on the declared axis is what stops the fold double-counting."""
    assert (
        sustain.saturating_stat_percent(
            ["Vampiric Scepter", "Doran's Blade"],
            SustainStat.OMNIVAMP_PERCENT,
            fight_duration_seconds=30.0,
            holder_is_melee=True,
        )
        == 0.0
    )
    assert (
        sustain.saturating_stat_percent(
            [SATURATING_HOLDER],
            SustainStat.LIFESTEAL_PERCENT,
            fight_duration_seconds=30.0,
            holder_is_melee=True,
        )
        == 0.0
    )


def test_a_moved_ramp_number_moves_the_moment_the_grant_arms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The refresh proof's shape: the declaration holds references, not floats."""
    patched = dict(item_effects.ITEM_EFFECTS[SATURATING_HOLDER])
    patched["amp_max"] = 0.02
    monkeypatch.setitem(item_effects.ITEM_EFFECTS, SATURATING_HOLDER, patched)
    assert sustain.saturating_stat_percent(
        [SATURATING_HOLDER],
        SustainStat.OMNIVAMP_PERCENT,
        fight_duration_seconds=1.0,
        holder_is_melee=True,
    ) == pytest.approx(patched["max_stack_omnivamp"])


def test_a_grant_missing_the_ramp_that_arms_it_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The grant and its ramp are claimed together or the parse dropped one."""
    patched = {
        key: value
        for key, value in item_effects.ITEM_EFFECTS[SATURATING_HOLDER].items()
        if key != "amp_max"
    }
    monkeypatch.setitem(item_effects.ITEM_EFFECTS, SATURATING_HOLDER, patched)
    monkeypatch.setattr(
        catalog, "_schema_keys", lambda owner, registry, entry: frozenset(entry)
    )
    with pytest.raises(catalog.BehaviorCatalogError, match="amp_max"):
        catalog.behavior_rules(SATURATING_HOLDER)
