"""The front door for the on-hit strike interpreter.

The claim this slice makes is that eight items' on-hit damage is now a
declaration, and that the declaration reproduces the registry's own formula
ladder term for term.  So what is pinned here is the *arithmetic identity*:
each schema's number is recomputed from the registry entry by hand and
compared with what the declaration pays.
"""

import dataclasses

import pytest

from src.calculator.data_fetcher import get_item_by_name
from src.calculator.interpreters import on_hit_strike
from src.calculator.item_behavior import FightFacts, OnHitStrikeRule, RuleFamily
from src.calculator.item_behavior_catalog import (
    ON_HIT_FORMULA_TERMS,
    behavior_rules,
    build_context,
)
from src.calculator.item_effects import (
    ITEM_EFFECTS,
    DamageInputs,
    target_class_denials,
)
from src.calculator.item_source import effect_entries

STATS = {
    "ability_power": 200.0,
    "bonus_attack_damage": 100.0,
    "max_mana": 1500.0,
    "health": 2400.0,
}


def _inputs(is_melee: bool = True) -> DamageInputs:
    """A reading with every pool the on-hit schemas can read."""
    return DamageInputs(
        champion_stats=STATS,
        level=18,
        is_melee=is_melee,
        target_max_health=3000.0,
        target_current_health=1000.0,
    )


def _strike(owner: str) -> "on_hit_strike.PerHitEffect":  # type: ignore[name-defined]
    """The one on-hit strike an owner declares."""
    strikes = on_hit_strike.per_hit_effects(
        [owner],
        facts=FightFacts(
            level=18,
            fight_duration_seconds=5.0,
            target_bonus_health=0.0,
            holder_is_melee=True,
        ),
    )
    assert len(strikes) == 1
    return strikes[0]


def _on_hit_owners() -> tuple[str, ...]:
    """Every registry owner whose entry declares an on-hit strike."""
    return tuple(
        sorted(
            name
            for name, entry in ITEM_EFFECTS.items()
            if entry.get("type") == "on_hit"
        )
    )


def test_every_on_hit_entry_compiles_to_exactly_one_declared_rule() -> None:
    """Counter 3's half of the claim: no on-hit entry is still engine code."""
    owners = _on_hit_owners()
    assert owners
    for owner in owners:
        rules = [
            rule
            for rule in behavior_rules(owner)
            if rule.family is RuleFamily.ON_HIT_STRIKE
        ]
        assert len(rules) == 1, owner
        assert isinstance(rules[0].payload, OnHitStrikeRule)


def test_every_registry_schema_is_reached_by_some_owner() -> None:
    """A schema no entry uses is a branch nothing reaches (D-51)."""
    used = {str(ITEM_EFFECTS[owner]["formula"]) for owner in _on_hit_owners()}
    assert used == set(ON_HIT_FORMULA_TERMS)


@pytest.mark.parametrize(
    "owner",
    ["Recurve Bow", "Nashor's Tooth", "Terminus", "Muramana", "Titanic Hydra"],
)
def test_each_schema_reproduces_the_registrys_own_arithmetic(owner: str) -> None:
    """Recomputed by hand from the entry, so a drifted term shows up here."""
    entry = ITEM_EFFECTS[owner]
    expected = {
        "Recurve Bow": entry.get("base", 0.0),
        "Nashor's Tooth": entry.get("base", 0.0)
        + entry.get("ap_ratio", 0.0) * STATS["ability_power"],
        "Terminus": entry.get("base", 0.0)
        + entry.get("bonus_ad_ratio", 0.0) * STATS["bonus_attack_damage"]
        + entry.get("ap_ratio", 0.0) * STATS["ability_power"],
        "Muramana": entry.get("max_mana_ratio_on_hit", 0.0) * STATS["max_mana"],
        "Titanic Hydra": entry.get("max_hp_ratio_melee", 0.0) * STATS["health"],
    }[owner]
    assert _strike(owner).source.raw_damage(_inputs()) == pytest.approx(expected)


def test_the_minimum_is_a_floor_on_the_sum() -> None:
    """Blade of the Ruined King never pays less than its sourced minimum."""
    entry = ITEM_EFFECTS["Blade of the Ruined King"]
    strike = _strike("Blade of the Ruined King")
    healthy = strike.source.raw_damage(_inputs())
    assert healthy == pytest.approx(
        entry["current_hp_ratio_melee"] * 1000.0  # type: ignore[operator]
    )
    drained = dataclasses.replace(_inputs(), target_current_health=0.0)
    assert strike.source.raw_damage(drained) == pytest.approx(entry["min_damage"])


def test_the_range_split_is_paid_from_the_swings_own_range_class() -> None:
    """Both rates resolve at build time and the swing decides which is paid."""
    entry = ITEM_EFFECTS["Blade of the Ruined King"]
    strike = _strike("Blade of the Ruined King")
    melee = strike.source.raw_damage(_inputs(is_melee=True))
    ranged = strike.source.raw_damage(_inputs(is_melee=False))
    assert melee == pytest.approx(entry["current_hp_ratio_melee"] * 1000.0)  # type: ignore[operator]
    assert ranged == pytest.approx(entry["current_hp_ratio_ranged"] * 1000.0)  # type: ignore[operator]


def test_the_live_health_flag_is_derived_from_the_terms() -> None:
    """It was a formula-name comparison and is now a property of the shares."""
    assert _strike("Blade of the Ruined King").tracks_current_health
    assert not _strike("Recurve Bow").tracks_current_health


def test_the_no_double_dip_rule_is_declared_not_inferred() -> None:
    """Only the item that also pays per ability hit carries the rule."""
    assert _strike("Muramana").superseded_by_ability_proc
    assert not _strike("Terminus").superseded_by_ability_proc


def test_the_breakdown_row_keeps_the_key_it_replaces() -> None:
    """A migrated row must not rename itself out of every committed baseline."""
    strike = _strike("Terminus")
    assert strike.source.breakdown_key == "on_hit_Terminus"
    assert strike.source.display_name == "Terminus (on-hit)"
    assert strike.source.damage_type == ITEM_EFFECTS["Terminus"]["damage_type"]


def test_a_build_with_no_on_hit_item_declares_nothing() -> None:
    """An empty tuple here means no rule ran, which the engine then measures."""
    assert (
        on_hit_strike.per_hit_effects(
            ["Sheen"],
            facts=FightFacts(
                level=18,
                fight_duration_seconds=5.0,
                target_bonus_health=0.0,
                holder_is_melee=True,
            ),
        )
        == ()
    )


def test_a_rule_from_another_family_is_refused() -> None:
    """The interpreter checks the payload it was handed rather than assuming."""
    amp = behavior_rules("Horizon Focus")[0]
    ctx = build_context(
        "Horizon Focus",
        FightFacts(
            level=18,
            fight_duration_seconds=5.0,
            target_bonus_health=0.0,
            holder_is_melee=True,
        ),
    )
    with pytest.raises(on_hit_strike.OnHitStrikeInterpretationError):
        on_hit_strike.per_hit_effect(amp, ctx)


# ---------------------------------------------------------------------------
# Class-restricted on-hits: the declaration is the one home for the packet
# ---------------------------------------------------------------------------


def _restricted_owners() -> tuple[str, ...]:
    """Every registry owner declaring an on-hit restricted to a target class."""
    return tuple(
        sorted(
            name
            for name in ITEM_EFFECTS
            if on_hit_strike.class_restricted_packets([name])
        )
    )


def test_every_entry_carrying_the_channel_declares_the_packet() -> None:
    """Every channel holder routes the same registry key down the same channel.

    The holder set is not pinned: adjudication is per clause, so a third holder
    admits its Helping Hand clause and nothing else, and its other class
    clauses still refuse a minion-class fight on their own.
    """
    assert _restricted_owners()
    for owner in _restricted_owners():
        assert "helping_hand_minion_damage" in ITEM_EFFECTS[owner]
        assert "Helping Hand" in on_hit_strike.adjudicated_target_class_mechanics(owner)


def test_the_declared_amount_is_the_atom_checked_accessor() -> None:
    """The declaration resolves the same 5.0 the atom-backed accessor does."""
    from src.calculator.item_effects import dorans_helm_helping_hand_minion_damage

    effects = on_hit_strike.class_restricted_per_hit_effects(
        ["Doran's Helm"], target_class="minion"
    )
    assert len(effects) == 1
    assert effects[0].source.raw_damage(_inputs()) == pytest.approx(
        dorans_helm_helping_hand_minion_damage()
    )


def test_a_champion_class_fight_arms_no_restricted_packet() -> None:
    """No declaration names the champion class, so it arms nothing."""
    assert (
        on_hit_strike.class_restricted_per_hit_effects(
            _restricted_owners(), target_class="champion"
        )
        == ()
    )


def test_the_minion_row_is_named_after_the_declaration() -> None:
    """Row key, label and damage class all follow the channel's packet."""
    effects = on_hit_strike.class_restricted_per_hit_effects(
        ["Doran's Helm", "Tear of the Goddess"], target_class="minion"
    )
    assert [effect.source.breakdown_key for effect in effects] == [
        "on_hit_minion_Doran's Helm",
        "on_hit_minion_Tear of the Goddess",
    ]
    for effect in effects:
        assert effect.target_class == "minion"
        assert effect.source.damage_type == "physical"
        assert effect.source.display_name.endswith("(Helping Hand vs minions)")


# ---------------------------------------------------------------------------
# Target-class adjudication: per clause, never per item (issue #236)
# ---------------------------------------------------------------------------


def _cached_mechanics(owner: str) -> set[object]:
    """Every clause name *owner*'s cached record carries."""
    return {entry.get("name") for _, entry in effect_entries(get_item_by_name(owner))}


def _minion_denials(owner: str, reader) -> tuple[str, ...]:
    """What a minion-class fight holding *owner* alone refuses, through *reader*."""
    return target_class_denials(
        [{"name": owner}], "minion", adjudicated_mechanics=reader
    )


def test_a_channel_holders_every_clause_is_adjudicated() -> None:
    """Neither Helping Hand holder is refused, clause by clause.

    Doran's Helm carries the one clause the packet prices; Tear carries that
    clause and Manaflow, whose ledger is handed the fight's own class.
    """
    reader = on_hit_strike.adjudicated_target_class_mechanics
    for owner in _restricted_owners():
        assert _minion_denials(owner, reader) == ()
        assert (
            target_class_denials(
                [{"name": owner}], "champion", adjudicated_mechanics=reader
            )
            == ()
        )


def test_an_unpriced_clause_does_not_ride_in_on_a_priced_sibling() -> None:
    """The issue itself: a holder whose OTHER clause is unpriced is refused.

    Tear stands in for the third Helping Hand holder — the reader admits its
    Helping Hand clause only, so Manaflow's champion split is refused on its
    own and the priced clause is not named.
    """
    denials = _minion_denials(
        "Tear of the Goddess", lambda _: frozenset({"Helping Hand"})
    )
    assert len(denials) == 1
    assert "'Manaflow'" in denials[0]
    assert "champion" in denials[0]
    assert "minions" not in denials[0]


def test_every_reviewed_class_reading_key_names_a_declared_clause() -> None:
    """The reviewed table is held to the tree it names.

    Each key is a mechanic id exactly one registry entry declares, and each
    value is a clause that entry's cached record carries — so a renamed
    declaration or a re-parsed clause fails here rather than silently
    admitting nothing.
    """
    for mechanic_id, mechanic in on_hit_strike.CLASS_READING_MECHANICS.items():
        owners = [
            name
            for name in ITEM_EFFECTS
            for rule in behavior_rules(name)
            if rule.mechanic_id == mechanic_id
        ]
        assert len(owners) == 1
        assert mechanic in _cached_mechanics(owners[0])


def test_an_unreviewed_manaflow_holder_still_refuses_a_minion_fight() -> None:
    """Only Tear's Manaflow ledger reads the fight's class.

    Every other Manaflow entry declares the same champion split and none is
    paid one, so their clause is refused rather than paid the champion amount.
    """
    others = sorted(
        name
        for name in ITEM_EFFECTS
        if name != "Tear of the Goddess" and "Manaflow" in _cached_mechanics(name)
    )
    assert others
    reader = on_hit_strike.adjudicated_target_class_mechanics
    for owner in others:
        assert any("'Manaflow'" in denial for denial in _minion_denials(owner, reader))
