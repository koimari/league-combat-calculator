"""The threshold-defence family's front door.

Five Lifelines with five different arithmetics, one temporary-health lifeline
and one resurrection.  The amounts are the amounts the retired
``_lifeline_defense`` ladder produced; what is new is that the *choice*
between them is a declaration rather than a chain of name comparisons, and
that a build holding two Lifelines resolves exactly one of them by a stated
rule rather than by whichever name a tuple listed first.
"""

from __future__ import annotations

import pytest

from src.calculator import item_behavior_catalog as catalog
from dataclasses import replace

from src.calculator.interpreters.defense_state import (
    DefenseInterpretationError,
    DefenseSlot,
    declared_defenses,
)
from src.calculator.interpreters import INTERPRETERS, resolve_defense
from src.calculator.interpreters.threshold_defense import (
    RESOLVER_INTERPRETER,
    THRESHOLD_HEALTH_MECHANIC,
    TICK_INTERVAL_KEY,
    threshold_health_coverage_source,
    threshold_health_owner,
    threshold_health_tick_interval,
)
from src.calculator.item_behavior import (
    BehaviorRule,
    DefenseExclusivity,
    DefenseMechanic,
    DefenseSubject,
    EngineLane,
    RuleFamily,
)


def _subject(level: int = 18, **stats: float) -> DefenseSubject:
    """A subject with the stats one Lifeline's arithmetic reads."""
    base: dict[str, float] = {"health": 2000.0, "is_melee": False}
    base.update(stats)
    return DefenseSubject(level=level, stats=base, options={})


def _rule(owner: str, mechanic: DefenseMechanic) -> BehaviorRule:
    """The live rule *owner* declares for *mechanic*."""
    for rule in catalog.behavior_rules(owner):
        if getattr(rule.payload, "mechanic", None) is mechanic:
            return rule
    raise AssertionError(f"{owner} declares no {mechanic.value} rule")


def _granted(outcome) -> dict[str, object]:
    """One outcome's fields, by the resolved field they write."""
    return {field.name: field.value for field in outcome.fields}


def test_the_family_is_registered_on_the_lane_that_builds_it() -> None:
    """A threshold defence is built before any walk."""
    assert (
        INTERPRETERS[(RuleFamily.THRESHOLD_DEFENSE, EngineLane.DEFENSE_RESOLVER)]
        is RESOLVER_INTERPRETER
    )


@pytest.mark.parametrize(
    ("owner", "mechanic", "stats", "expected"),
    [
        ("Immortal Shieldbow", DefenseMechanic.LIFELINE_SHIELDBOW, {}, 700.0),
        (
            "Hexdrinker",
            DefenseMechanic.LIFELINE_HEXDRINKER,
            {"is_melee": True},
            280.0,
        ),
        ("Hexdrinker", DefenseMechanic.LIFELINE_HEXDRINKER, {}, 210.0),
        (
            "Maw of Malmortius",
            DefenseMechanic.LIFELINE_MAW,
            {"is_melee": True, "bonus_attack_damage": 60.0},
            290.0,
        ),
        (
            "Maw of Malmortius",
            DefenseMechanic.LIFELINE_MAW,
            {"bonus_attack_damage": 60.0},
            217.5,
        ),
        (
            "Seraph's Embrace",
            DefenseMechanic.LIFELINE_SERAPH,
            {"max_mana": 2500.0},
            450.0,
        ),
        (
            "Sterak's Gage",
            DefenseMechanic.LIFELINE_STERAK,
            {"bonus_health": 500.0},
            300.0,
        ),
    ],
)
def test_each_lifeline_is_worth_what_its_own_shape_says(
    owner: str, mechanic: DefenseMechanic, stats: dict, expected: float
) -> None:
    """Five shapes for one word, each read off the declaration that carries it."""
    outcome = resolve_defense(_rule(owner, mechanic), _subject(**stats))

    assert _granted(outcome)["threshold_shield_amount"] == pytest.approx(expected)


def test_a_magic_lifeline_says_so_and_a_general_one_does_not() -> None:
    """The published sentence is qualified by what the shield stands in front of."""
    magic = resolve_defense(
        _rule("Hexdrinker", DefenseMechanic.LIFELINE_HEXDRINKER), _subject()
    )
    general = resolve_defense(
        _rule("Immortal Shieldbow", DefenseMechanic.LIFELINE_SHIELDBOW), _subject()
    )

    assert "triggers before magic damage" in magic.notes[0]
    assert _granted(magic)["threshold_shield_damage_type"] == "magic"
    assert "triggers before damage" in general.notes[0]
    assert _granted(general)["threshold_shield_damage_type"] == "all"


def test_maws_omnivamp_is_a_second_statement_about_one_mechanic() -> None:
    """The temporary stat is granted after the shield, and says so."""
    outcome = resolve_defense(
        _rule("Maw of Malmortius", DefenseMechanic.LIFELINE_MAW), _subject()
    )

    assert _granted(outcome)["maw_lifeline_omnivamp_percent"] == pytest.approx(10.0)
    assert len(outcome.notes) == 2
    assert "only after Lifeline triggers" in outcome.notes[1]


def test_protoplasms_heal_reads_the_subjects_own_resistances() -> None:
    """A lifeline that grants health rather than a shield, and heals with it."""
    outcome = resolve_defense(
        _rule("Protoplasm Harness", DefenseMechanic.LIFELINE_PROTOPLASM),
        _subject(level=7, bonus_armor=20.0, bonus_magic_resistance=30.0),
    )

    granted = _granted(outcome)
    assert granted["threshold_health_bonus"] == pytest.approx(170.588235)
    assert granted["threshold_health_heal"] == pytest.approx(293.382353)
    assert granted["threshold_health_ratio"] == pytest.approx(0.30)


def test_rebirth_restores_a_share_of_base_health_and_names_its_source() -> None:
    """The one threshold defence armed by death rather than by a fraction."""
    outcome = resolve_defense(
        _rule("Guardian Angel", DefenseMechanic.REBIRTH), _subject(base_health=1800.0)
    )

    granted = _granted(outcome)
    assert granted["revive_health_amount"] == pytest.approx(900.0)
    assert granted["revive_delay"] == pytest.approx(4.0)
    assert granted["revive_source"] == "Guardian Angel (Rebirth)"


def test_two_lifelines_resolve_to_the_registrys_own_first() -> None:
    """Exclusivity, declared: the game's unique-passive rule, tie-break stated.

    Immortal Shieldbow's entry precedes Sterak's Gage's in the number
    registry, which is the order the retired ladder's tuple of item names
    spelled and the order this reproduces without naming one.
    """
    both = declared_defenses(frozenset({"Sterak's Gage", "Immortal Shieldbow"}))

    assert DefenseMechanic.LIFELINE_SHIELDBOW in both
    assert DefenseMechanic.LIFELINE_STERAK not in both
    assert all(
        rule.payload.exclusivity is DefenseExclusivity.LIFELINE
        for mechanic, rule in both.items()
        if mechanic is DefenseMechanic.LIFELINE_SHIELDBOW
    )


def test_protoplasm_is_not_in_the_lifeline_exclusivity_group() -> None:
    """It is called a Lifeline and it stacks with one, which is why it is NONE."""
    both = declared_defenses(frozenset({"Protoplasm Harness", "Hexdrinker"}))

    assert DefenseMechanic.LIFELINE_PROTOPLASM in both
    assert DefenseMechanic.LIFELINE_HEXDRINKER in both


def test_a_missing_typing_key_fails_loud_with_item_and_key() -> None:
    """Rule 5's discipline, at the moment the declaration is compiled."""
    from src.calculator import item_effects

    broken = dict(item_effects.ITEM_EFFECTS["Immortal Shieldbow"])
    broken.pop("damage_type")
    original = item_effects.ITEM_EFFECTS["Immortal Shieldbow"]
    item_effects.ITEM_EFFECTS["Immortal Shieldbow"] = broken
    try:
        with pytest.raises(KeyError, match="Immortal Shieldbow.*damage_type"):
            catalog.behavior_rules("Immortal Shieldbow")
    finally:
        item_effects.ITEM_EFFECTS["Immortal Shieldbow"] = original


# ── the mechanic's owner, derived rather than spelled (3.9) ───────────────


def test_the_temporary_health_lifelines_owner_comes_from_the_declaration() -> None:
    """The name two engines put in a receipt is read off the catalog.

    The pair engine sees a defender's resolved numbers and never its items,
    so both readers of this mechanic — the fight's coverage downgrade and
    the optimizer's candidate rejection — used to spell the item.  Asserted
    against the catalog rather than a literal, so the day another item grows
    the mechanic this stops rather than names the wrong one.
    """
    declared = {
        rule.owner
        for owner in catalog.declared_owners()
        for rule in catalog.behavior_rules(owner)
        if getattr(rule.payload, "mechanic", None) is THRESHOLD_HEALTH_MECHANIC
    }

    assert threshold_health_owner() in declared
    assert threshold_health_coverage_source() == f"target_{threshold_health_owner()}"


def test_the_heal_cadence_is_read_off_the_declaration_not_the_config() -> None:
    """The tick cadence reaches the walk the way the owner does.

    The walk that authors the heal holds resolved pools, which carry no
    build, so it asks the declaration.  Pinned against the catalog rather
    than a literal: the number is the item's, and moving it in the registry
    has to move this.
    """
    rule = next(
        rule
        for owner in catalog.declared_owners()
        for rule in catalog.behavior_rules(owner)
        if getattr(rule.payload, "mechanic", None) is THRESHOLD_HEALTH_MECHANIC
    )
    declared = DefenseSlot(rule).value(TICK_INTERVAL_KEY)

    assert threshold_health_tick_interval() == declared
    assert declared > 0.0


def test_a_declaration_without_the_cadence_key_stops_rather_than_guesses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The banned shape: a silent default cadence standing in for a number.

    Stripping the declared key must raise and name it, because a cadence
    quietly defaulting to some engine constant is exactly the stale-literal
    failure the registry rule exists to prevent.
    """
    from src.calculator.interpreters import threshold_defense

    real = threshold_defense.behavior_rules

    def stripped(owner: str):
        rules = real(owner)
        return tuple(
            (
                replace(
                    rule,
                    payload=replace(
                        rule.payload,
                        values=tuple(
                            reference
                            for reference in rule.payload.values
                            if getattr(reference, "key", "") != TICK_INTERVAL_KEY
                        ),
                    ),
                )
                if getattr(rule.payload, "mechanic", None) is THRESHOLD_HEALTH_MECHANIC
                else rule
            )
            for rule in rules
        )

    monkeypatch.setattr(threshold_defense, "behavior_rules", stripped)
    threshold_defense._THRESHOLD_HEALTH_TICK_MEMO.clear()  # noqa: SLF001
    with pytest.raises(DefenseInterpretationError) as excinfo:
        threshold_defense.threshold_health_tick_interval()
    threshold_defense._THRESHOLD_HEALTH_TICK_MEMO.clear()  # noqa: SLF001

    assert TICK_INTERVAL_KEY in str(excinfo.value)


def test_two_declared_temporary_health_lifelines_stop_rather_than_guess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R-05's red: the pools that raise carry no owner, so two is a stop.

    One item declares the mechanic today, so the second is planted.  A
    receipt naming the wrong holder is worse than a refusal, which is why
    the derivation refuses instead of taking the first sorted name.
    """
    from src.calculator.interpreters import threshold_defense

    real = threshold_defense.behavior_rules
    twin = tuple(
        replace(rule, owner="Cytoplasm Harness")
        for rule in real(threshold_health_owner())
    )
    monkeypatch.setattr(
        threshold_defense,
        "behavior_rules",
        lambda owner: twin if owner == "Recurve Bow" else real(owner),
    )
    # A throwaway memo rather than a cleared one: this generation's answer is
    # already memoized by the reads above and a hit would never reach the
    # derivation, while clearing the real dict would leave the planted twin's
    # verdict reachable by whatever runs next.
    monkeypatch.setattr(threshold_defense, "_THRESHOLD_HEALTH_OWNER_MEMO", {})

    with pytest.raises(DefenseInterpretationError, match="carry no owner"):
        threshold_health_owner()
