"""The sustain family's front door: seven ways health comes back.

Six of them are the holder's own — a vampirism stat, a flat on-hit heal, a
share of damage dealt, a resource drain, a heal bought with mana, and a
regeneration window — and the seventh multiplies everything the subject
receives, which is why the defensive resolver builds it after every shield.

The tests pin the numbers against the registry keys the retired name
branches read, because this migration's claim is that the declarations
reproduce them exactly.
"""

from __future__ import annotations

import pytest

from src.calculator import item_behavior_catalog as catalog
from src.calculator import item_effects
from src.calculator.defensive_effects import resolve_starting_defenses
from src.calculator.interpreters import INTERPRETERS
from src.calculator.interpreters.sustain import (
    PAIR_INTERPRETER,
    RESOLVER_INTERPRETER,
    SustainInterpretationError,
    received_healing_multiplier,
    stat_grants,
    sustain_slot,
)
from src.calculator.item_behavior import (
    DefenseMechanic,
    EngineLane,
    ManaSpentHealRule,
    OnHitHealRule,
    PostMitigationHealRule,
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


def test_both_lanes_are_registered() -> None:
    """The holder's sustain is priced by the pair engine; the multiplier is not."""
    assert (
        INTERPRETERS[(RuleFamily.SUSTAIN, EngineLane.PAIR_ENGINE)] is PAIR_INTERPRETER
    )
    assert (
        INTERPRETERS[(RuleFamily.SUSTAIN, EngineLane.DEFENSE_RESOLVER)]
        is RESOLVER_INTERPRETER
    )


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
