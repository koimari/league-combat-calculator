"""The front door for the spellblade interpreter.

Seven items share one mechanic.  The retired registry compiler told them
apart by a table of *item names* deciding which sibling mechanic each
carried and a ``values.get(key, 0.0)`` fallback for every other.  What is
pinned here is that the sibling groups come off the registry's schema instead
of that table, that a group is declared whole or not at all, that the fail
closed behaviour the name table bought survives the names being gone, and
that a build holding two spellblades still arms exactly one.
"""

import pytest

from src.calculator.interpreters import spellblade
from src.calculator.item_behavior import (
    EngineLane,
    RuleFamily,
    SpellbladeRule,
    validate_rule,
)
from src.calculator.item_behavior_catalog import behavior_rules, build_context
from src.calculator.item_effects import ITEM_EFFECTS, DamageInputs

PLAIN = "Sheen"
WITH_ABILITY_POWER = "Lich Bane"
WITH_CRIT = "Essence Reaver"
DOUBLE_ON_HIT = "Dusk and Dawn"
SECOND = "Trinity Force"


def _armed(*owners: str, is_melee: bool = True):
    """The spellblade a build of *owners* arms."""
    return spellblade.resolve_slot(
        owners,
        level=18,
        fight_duration_seconds=5.0,
        target_bonus_health=0.0,
        holder_is_melee=is_melee,
    )


def _inputs(**stats: float) -> DamageInputs:
    """One event's readings for a compiled spellblade formula."""
    return DamageInputs(
        champion_stats=stats,
        level=18,
        is_melee=True,
        target_max_health=2000.0,
        target_current_health=2000.0,
    )


def test_every_spellblade_entry_declares_exactly_one_rule() -> None:
    """Counter 3's half: the tag is not engine code in the registry."""
    for owner, entry in ITEM_EFFECTS.items():
        if entry.get("type") != "spellblade":
            continue
        rules = [
            rule
            for rule in behavior_rules(owner)
            if rule.family is RuleFamily.SPELLBLADE
        ]
        assert len(rules) == 1, owner
        assert isinstance(rules[0].payload, SpellbladeRule)


def test_the_three_formulas_sum_their_declared_shares() -> None:
    """Each schema, reproduced share for share and in the registry's order."""
    stats = {
        "base_attack_damage": 100.0,
        "ability_power": 200.0,
        "critical_strike_chance": 50.0,
    }
    plain, magical, critical = (
        _armed(PLAIN),
        _armed(WITH_ABILITY_POWER),
        _armed(WITH_CRIT),
    )
    assert plain is not None
    assert magical is not None
    assert critical is not None
    assert plain.source.raw_damage(_inputs(**stats)) == pytest.approx(
        float(ITEM_EFFECTS[PLAIN]["base_ad_ratio"]) * 100.0  # type: ignore[arg-type]
    )
    assert magical.source.raw_damage(_inputs(**stats)) == pytest.approx(
        float(ITEM_EFFECTS[WITH_ABILITY_POWER]["base_ad_ratio"]) * 100.0  # type: ignore[arg-type]
        + float(ITEM_EFFECTS[WITH_ABILITY_POWER]["ap_ratio"]) * 200.0  # type: ignore[arg-type]
    )
    assert critical.source.raw_damage(_inputs(**stats)) == pytest.approx(
        float(ITEM_EFFECTS[WITH_CRIT]["base_ad_ratio"]) * 100.0  # type: ignore[arg-type]
        + float(ITEM_EFFECTS[WITH_CRIT]["crit_bonus_max"]) * 0.5  # type: ignore[arg-type]
    )


def test_the_crit_share_is_capped_at_one_whole_critical_strike() -> None:
    """The basis caps the fraction, as the registry compiler's ``min`` did."""
    armed = _armed(WITH_CRIT)
    assert armed is not None
    over = armed.source.raw_damage(
        _inputs(base_attack_damage=0.0, critical_strike_chance=250.0)
    )
    exactly = armed.source.raw_damage(
        _inputs(base_attack_damage=0.0, critical_strike_chance=100.0)
    )
    assert over == pytest.approx(exactly)


def test_a_sibling_a_spellblade_does_not_have_is_a_declared_absence() -> None:
    """``None`` and a sourced rate are different claims about the item."""
    (plain,) = spellblade.spellblade_rules([PLAIN])
    assert plain.payload.bonus_attack_speed_percent is None
    assert plain.payload.mana_restore_base_ad_ratio is None
    assert plain.payload.self_heal_ap_ratio is None
    armed = _armed(PLAIN)
    assert armed is not None
    assert armed.bonus_attack_speed_percent == spellblade.NO_SIBLING
    assert armed.self_heal_ap_ratio == spellblade.NO_SIBLING


def test_each_sibling_group_is_declared_whole() -> None:
    """Both halves of a two-key sibling arrive together or not at all."""
    (essence,) = spellblade.spellblade_rules([WITH_CRIT])
    assert essence.payload.mana_restore_base_ad_ratio is not None
    assert essence.payload.mana_restore_crit_ratio is not None
    (dusk,) = spellblade.spellblade_rules([DOUBLE_ON_HIT])
    assert dusk.payload.self_heal_ap_ratio is not None
    assert dusk.payload.self_heal_bonus_health_ratio is not None
    assert dusk.payload.double_on_hit is True


def test_half_a_sibling_is_refused_at_validation() -> None:
    """A rule built past the group rule is a stop, not a weaker item."""
    (dusk,) = spellblade.spellblade_rules([DOUBLE_ON_HIT])
    halved = type(dusk)(
        family=dusk.family,
        owner=dusk.owner,
        mechanic_id=dusk.mechanic_id,
        payload=SpellbladeRule(
            formula=dusk.payload.formula,
            cooldown=dusk.payload.cooldown,
            weave_delay=dusk.payload.weave_delay,
            double_on_hit=dusk.payload.double_on_hit,
            bonus_attack_speed_percent=None,
            mana_restore_base_ad_ratio=None,
            mana_restore_crit_ratio=None,
            self_heal_ap_ratio=dusk.payload.self_heal_ap_ratio,
            self_heal_bonus_health_ratio=None,
        ),
        compilability=dusk.compilability,
        receipt=dusk.receipt,
        zero_policy=dusk.zero_policy,
    )
    with pytest.raises(Exception, match="declared whole or not at all"):
        validate_rule(halved)


def test_a_build_holding_two_spellblades_arms_exactly_one() -> None:
    """Build order decides, as the registry's own loop always did."""
    armed = _armed(SECOND, PLAIN)
    assert armed is not None
    assert armed.source.item_name == SECOND
    assert len(spellblade.spellblade_rules([SECOND, PLAIN])) == 2


def test_the_self_heal_question_reads_only_the_armed_spellblade() -> None:
    """An unarmed second spellblade heals nobody, so it must not count."""
    assert spellblade.declares_self_heal([DOUBLE_ON_HIT])
    assert not spellblade.declares_self_heal([PLAIN, DOUBLE_ON_HIT])
    assert not spellblade.declares_self_heal([])


def test_the_row_keeps_the_breakdown_key_the_engine_publishes() -> None:
    """Breakdown identity is unchanged by the migration."""
    armed = _armed(PLAIN)
    assert armed is not None
    assert (
        armed.source.breakdown_key == f"{spellblade.SPELLBLADE_BREAKDOWN_PREFIX}{PLAIN}"
    )
    assert armed.source.display_name == f"{PLAIN} ({spellblade.SPELLBLADE_SUFFIX})"
    assert armed.cooldown == pytest.approx(float(ITEM_EFFECTS[PLAIN]["cooldown"]))  # type: ignore[arg-type]
    assert armed.weave_delay == pytest.approx(
        float(ITEM_EFFECTS[PLAIN]["weave_delay"])  # type: ignore[arg-type]
    )


def test_the_pair_interpreter_compiles_the_cooldown_it_can_know() -> None:
    """A cooldown is a build-time number; the empowered attack's damage is not."""
    (rule,) = spellblade.spellblade_rules([PLAIN])
    ctx = build_context(
        PLAIN,
        18,
        fight_duration_seconds=5.0,
        target_bonus_health=0.0,
        holder_is_melee=True,
    )
    (field,) = spellblade.spellblade_fields(rule, ctx, EngineLane.PAIR_ENGINE)
    assert field.name == spellblade.SPELLBLADE_COOLDOWN_FIELD
    assert field.value == pytest.approx(float(ITEM_EFFECTS[PLAIN]["cooldown"]))  # type: ignore[arg-type]


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
    with pytest.raises(spellblade.SpellbladeInterpretationError):
        spellblade.spellblade_fields(foreign, ctx, EngineLane.PAIR_ENGINE)
