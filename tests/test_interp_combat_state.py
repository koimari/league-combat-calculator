"""The combat-state family's front door.

Four mechanics worth nothing at ``t = 0``, which is the family's entire
claim.  What the resolver publishes for Force of Nature and Jak'Sho is a
*schedule* the ordered ledger arms; what it publishes for Annul and Time Stop
is a state that is spent rather than accrued.  Every case below is really the
same case: a defence that has not happened yet must be visible as metadata
and must not be paid in advance.
"""

from __future__ import annotations

import pytest

from src.calculator import item_behavior_catalog as catalog
from src.calculator.defensive_effects import option_reader
from src.calculator.interpreters import INTERPRETERS, RESOLVERS, resolve_defense
from src.calculator.interpreters.combat_state import resolve_combat_state
from src.calculator.interpreters.defense_state import compiled_shape, declared_defenses
from src.calculator.item_behavior import (
    BehaviorRule,
    DefenseMechanic,
    DefenseSubject,
    EngineLane,
    RuleFamily,
)


def _subject(options: dict | None = None) -> DefenseSubject:
    """A level-18 subject, with whatever scenario inputs a case supplies."""
    return DefenseSubject(
        level=18,
        stats={"health": 2000.0},
        options=options or {},
        option_value=option_reader(options or {}),
    )


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
    """A combat state's metadata is built before any walk."""
    assert (
        INTERPRETERS[(RuleFamily.COMBAT_STATE, EngineLane.DEFENSE_RESOLVER)]
        is compiled_shape
    )
    assert RESOLVERS[RuleFamily.COMBAT_STATE] is resolve_combat_state


def test_steadfast_publishes_a_schedule_and_pays_nothing_yet() -> None:
    """Eight stacks of magic resistance the holder has not earned."""
    outcome = resolve_defense(
        _rule("Force of Nature", DefenseMechanic.STEADFAST), _subject()
    )

    granted = _granted(outcome)
    assert granted["force_max_stacks"] == 8
    assert isinstance(granted["force_max_stacks"], int)
    assert granted["force_stack_duration"] == pytest.approx(7.0)
    assert granted["force_bonus_magic_resistance"] == pytest.approx(70.0)
    assert "starts at zero stacks" in outcome.notes[0]


def test_voidborn_publishes_its_multiplier_and_its_own_wording() -> None:
    """The one note the wiki writes with the item's short name."""
    outcome = resolve_defense(
        _rule("Jak'Sho, The Protean", DefenseMechanic.VOIDBORN_RESILIENCE), _subject()
    )

    granted = _granted(outcome)
    assert granted["jaksho_max_stacks"] == 5
    assert granted["jaksho_bonus_resistance_multiplier"] == pytest.approx(0.30)
    assert outcome.notes[0].startswith("Jak'Sho Voidborn Resilience")


@pytest.mark.parametrize(
    "owner", ["Banshee's Veil", "Edge of Night", "Verdant Barrier"]
)
def test_every_annul_publishes_the_item_that_granted_it(owner: str) -> None:
    """One mechanic, three items, three citations and three state sources."""
    outcome = resolve_defense(_rule(owner, DefenseMechanic.ANNUL), _subject())

    assert _granted(outcome) == {
        "spell_shield_ready": True,
        "spell_shield_source": f"{owner} — Annul",
    }


def test_two_annuls_resolve_to_the_registrys_own_first() -> None:
    """Exclusivity again, and the same stated tie-break."""
    both = declared_defenses(frozenset({"Edge of Night", "Banshee's Veil"}))

    rule = both[DefenseMechanic.ANNUL]
    assert rule.owner == "Banshee's Veil"


def test_a_spell_shield_the_registry_says_is_not_ready_declares_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fail-closed reading, moved from a ``.get(..., False)`` to a compiler."""
    from src.calculator import item_effects

    broken = dict(item_effects.ITEM_EFFECTS["Banshee's Veil"])
    broken["spell_shield_ready"] = False
    monkeypatch.setitem(item_effects.ITEM_EFFECTS, "Banshee's Veil", broken)

    assert catalog.behavior_rules("Banshee's Veil") == ()


def test_stasis_is_never_assumed_active_by_item_presence() -> None:
    """An hourglass says the holder could stop time, not that they did."""
    rule = _rule("Zhonya's Hourglass", DefenseMechanic.TIME_STOP)
    idle = resolve_defense(rule, _subject())
    active = resolve_defense(
        rule, _subject({"Zhonya's Hourglass": {"stasis_active_seconds": 1.5}})
    )

    assert idle.fields == ()
    assert idle.notes == ()
    assert _granted(active)["starting_stasis_duration"] == pytest.approx(1.5)
    assert (
        _granted(active)["starting_stasis_source"] == "Zhonya's Hourglass — Time Stop"
    )


def test_a_stasis_window_longer_than_the_sourced_duration_is_refused() -> None:
    """The request boundary owns the domain; the seam never sees an excess.

    ``DefenseSubject.option`` reads through ``item_effects``' typed accessor,
    so the sourced 2.5s Time Stop duration is the option's contract.  Nine
    seconds is refused by name rather than quietly capped.
    """
    rule = _rule("Zhonya's Hourglass", DefenseMechanic.TIME_STOP)

    with pytest.raises(ValueError, match=r"stasis_active_seconds must be between 0"):
        resolve_defense(
            rule, _subject({"Zhonya's Hourglass": {"stasis_active_seconds": 9.0}})
        )


def test_deleting_the_interpreter_withholds_rather_than_granting_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Criterion 11 for this family."""
    from src.calculator import interpreters

    remaining = {
        family: resolver
        for family, resolver in RESOLVERS.items()
        if family is not RuleFamily.COMBAT_STATE
    }
    monkeypatch.setattr(interpreters, "RESOLVERS", remaining)
    with pytest.raises(interpreters.InterpreterRegistryError, match="withheld"):
        resolve_defense(_rule("Force of Nature", DefenseMechanic.STEADFAST), _subject())
