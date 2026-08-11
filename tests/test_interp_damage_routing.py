"""The routing family's front door: packets moved, not resized.

Three mechanics that share one question — where does this damage end up? —
and nothing else.  Two are priced by the pair engine against the target; the
third is built by the defensive resolver at the opening, because that is
where a deferral schedule has to exist before the first packet lands.

The deferral is the interesting case: its registry entry is tagged as a
*starting defence*, and until this slice it was the last mechanic in
`defensive_effects` still matched by item name. The tests below pin that the
resolved state it produces is the one the retired branch produced, field for
field.
"""

from __future__ import annotations

import pytest

from src.calculator import item_behavior_catalog as catalog
from src.calculator import item_effects
from src.calculator.defensive_effects import resolve_starting_defenses
from src.calculator.interpreters import INTERPRETERS
from src.calculator.interpreters.damage_routing import (
    DamageRoutingInterpretationError,
    EXECUTE_THRESHOLD_FIELD,
    PAIR_INTERPRETER,
    RESOLVER_INTERPRETER,
    resolve_execution,
    resolve_shield_bypass,
)
from src.calculator.item_behavior import (
    DamageDeferralRule,
    DefenseMechanic,
    EngineLane,
    ExecuteRule,
    RuleFamily,
    ShieldBypassRule,
    Subject,
)

EXECUTE_HOLDER = "The Collector"
BYPASS_HOLDER = "Serpent's Fang"
DEFERRAL_HOLDER = "Death's Dance"

SUBJECT_STATS = {
    "health": 2000.0,
    "bonus_health": 500.0,
    "armor": 100.0,
    "magic_resistance": 60.0,
    "attack_damage": 200.0,
    "bonus_attack_damage": 100.0,
}


def _defenses(*names: str, is_melee: bool = True):
    """The opening defensive state of a build, at a mid-fight level."""
    stats = dict(SUBJECT_STATS, is_melee=is_melee)
    return resolve_starting_defenses(
        "Garen", 13, stats, [{"name": name} for name in names]
    )


def _rule(owner: str, payload_type: type):
    """The live rule *owner* declares with a payload of *payload_type*."""
    for rule in catalog.behavior_rules(owner):
        if isinstance(rule.payload, payload_type):
            return rule
    raise AssertionError(f"{owner} declares no {payload_type.__name__}")


def test_both_lanes_are_registered() -> None:
    """The family is built in two places and says so in the lane table."""
    assert (
        INTERPRETERS[(RuleFamily.DAMAGE_ROUTING, EngineLane.PAIR_ENGINE)]
        is PAIR_INTERPRETER
    )
    assert (
        INTERPRETERS[(RuleFamily.DAMAGE_ROUTING, EngineLane.DEFENSE_RESOLVER)]
        is RESOLVER_INTERPRETER
    )


def test_every_routing_entry_declares_a_rule() -> None:
    """All three mechanics reach a declaration, including the tagged defence."""
    for owner in (EXECUTE_HOLDER, BYPASS_HOLDER, DEFERRAL_HOLDER):
        families = [rule.family for rule in catalog.behavior_rules(owner)]
        assert RuleFamily.DAMAGE_ROUTING in families
        assert owner not in catalog.undeclared_owners()


def test_the_execution_is_the_registry_threshold() -> None:
    """The Collector's share of maximum health, read rather than carried."""
    execution = resolve_execution(
        [EXECUTE_HOLDER],
        level=13,
        fight_duration_seconds=5.0,
        target_bonus_health=0.0,
        holder_is_melee=True,
    )
    assert execution is not None
    assert execution.owner == EXECUTE_HOLDER
    assert execution.threshold == pytest.approx(
        item_effects.required_effect_value(EXECUTE_HOLDER, "threshold")
    )


def test_nobody_executing_is_an_answer_not_a_zero() -> None:
    """A build with no execution gets ``None``, never a threshold of zero."""
    assert (
        resolve_execution(
            ["Boots"],
            level=13,
            fight_duration_seconds=5.0,
            target_bonus_health=0.0,
            holder_is_melee=True,
        )
        is None
    )


@pytest.mark.parametrize(
    ("is_melee", "key"),
    [(True, "shield_reduction_melee"), (False, "shield_reduction_ranged")],
)
def test_the_bypass_share_follows_the_holders_range(is_melee, key) -> None:
    """Melee and ranged holders are paid the shares the registry states."""
    bypass = resolve_shield_bypass(
        [BYPASS_HOLDER],
        level=13,
        fight_duration_seconds=5.0,
        target_bonus_health=0.0,
        holder_is_melee=is_melee,
    )
    assert bypass is not None
    assert bypass.fraction == pytest.approx(
        item_effects.required_effect_value(BYPASS_HOLDER, key)
    )
    assert bypass.duration == pytest.approx(
        item_effects.required_effect_value(BYPASS_HOLDER, "venom_duration")
    )


def test_the_deferral_resolves_the_state_the_name_branch_produced() -> None:
    """Every field the retired Ignore Pain branch wrote, from the declaration."""
    defenses = _defenses(DEFERRAL_HOLDER)
    for attribute, key in (
        ("damage_deferral_fraction", "damage_deferral_melee"),
        ("damage_deferral_duration", "damage_deferral_duration"),
        ("damage_deferral_ticks", "damage_deferral_ticks"),
        ("defy_window", "defy_window"),
        ("defy_heal_bonus_ad_ratio", "defy_heal_bonus_ad_ratio"),
        ("defy_heal_duration", "defy_heal_duration"),
        ("defy_heal_ticks", "defy_heal_ticks"),
    ):
        assert getattr(defenses, attribute) == pytest.approx(
            item_effects.required_effect_value(DEFERRAL_HOLDER, key)
        )


def test_the_deferral_reads_the_ranged_share_for_a_ranged_subject() -> None:
    """Which of the two shares is read is a property of the subject."""
    ranged = _defenses(DEFERRAL_HOLDER, is_melee=False)
    assert ranged.damage_deferral_fraction == pytest.approx(
        item_effects.required_effect_value(DEFERRAL_HOLDER, "damage_deferral_ranged")
    )


def test_the_deferral_cites_its_own_declaration() -> None:
    """The published citation is the rule's receipt, not a typed record."""
    defenses = _defenses(DEFERRAL_HOLDER)
    citations = [
        citation
        for citation in defenses.sources
        if citation.mechanic is DefenseMechanic.IGNORE_PAIN
    ]
    assert len(citations) == 1
    assert citations[0].owner == DEFERRAL_HOLDER
    assert citations[0].receipt == _rule(DEFERRAL_HOLDER, DamageDeferralRule).receipt


def test_a_build_without_the_deferral_defers_nothing() -> None:
    """No holder, no schedule — and the absence is a zero nobody wrote."""
    assert _defenses("Boots").damage_deferral_fraction == 0.0
    assert _defenses("Boots").defy_window == 0.0


def test_the_two_pair_rules_act_on_the_target() -> None:
    """A routing rule moves damage on the target and declares no other subject."""
    assert _rule(EXECUTE_HOLDER, ExecuteRule).payload.subject is Subject.TARGET
    assert _rule(BYPASS_HOLDER, ShieldBypassRule).payload.subject is Subject.TARGET


def test_the_pair_interpreter_refuses_the_deferral() -> None:
    """The deferral is built by the resolver; asking the pair lane is a stop."""
    rule = _rule(DEFERRAL_HOLDER, DamageDeferralRule)
    with pytest.raises(DamageRoutingInterpretationError, match="defensive resolver"):
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


def test_the_compiled_execute_field_is_the_one_engines_ask_for() -> None:
    """A field a caller cannot name is a number nobody can read."""
    rule = _rule(EXECUTE_HOLDER, ExecuteRule)
    fields = PAIR_INTERPRETER.compile(
        rule,
        catalog.build_context(
            rule.owner,
            13,
            fight_duration_seconds=5.0,
            target_bonus_health=0.0,
            holder_is_melee=True,
        ),
    )
    assert [field.name for field in fields] == [EXECUTE_THRESHOLD_FIELD]
    assert all(field.rule_id == rule.mechanic_id for field in fields)
