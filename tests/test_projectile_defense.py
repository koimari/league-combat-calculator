"""The seven champion defensive windows, from the option that arms one to its public shape.

The front door for :mod:`src.calculator.projectile_defense`: every number below
is the cached ability's own atom, so a parse that stops sourcing one of them
fails here rather than in a fight total.
"""

from dataclasses import dataclass, field
from typing import Any

import pytest

from src.calculator.data_fetcher import get_champion
from src.calculator.projectile_defense import (
    defense_composition,
    defense_eligibility,
    public_defense,
    resolve_projectile_defense,
)


@dataclass(frozen=True)
class _Request:
    """The two request fields the resolver reads off a scenario."""

    champion_options: dict[str, Any] = field(default_factory=dict)
    ability_ranks: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class _Combatant:
    """A roster combatant as the resolver reads one."""

    champion_data: dict[str, Any]
    request: _Request
    level: int = 11


def _defense(champion: str, **options: Any):
    return resolve_projectile_defense(
        _Combatant(get_champion(champion), _Request(dict(options)))
    )


ARMED = (
    ("Braum", "e_active", "braum_unbreakable", 3.0),
    ("Yasuo", "w_active", "yasuo_wind_wall", 4.0),
    ("Fiora", "w_active", "fiora_riposte", 0.75),
    ("Jax", "e_active", "jax_counter_strike", 2.0),
    ("Samira", "w_active", "samira_blade_whirl", 0.75),
    ("Pantheon", "e_active", "pantheon_aegis_assault", 1.5),
    ("Gwen", "w_active", "gwen_hallowed_mist", 4.0),
)


@pytest.mark.parametrize(("champion", "option", "kind", "duration"), ARMED)
def test_each_declared_window_resolves_from_its_own_cached_atom(
    champion: str, option: str, kind: str, duration: float
) -> None:
    """The window opens at 0 and its length is the ability's sourced duration."""
    defense = _defense(champion, **{option: True})
    assert defense is not None
    assert defense.kind == kind
    assert defense.start == 0.0
    assert defense.duration == pytest.approx(duration)
    assert defense.until == pytest.approx(duration)
    assert defense.source_atoms, "a window with no atom cites nothing"


@pytest.mark.parametrize(("champion", "option", "kind", "duration"), ARMED)
def test_a_window_nobody_armed_is_withheld(
    champion: str, option: str, kind: str, duration: float
) -> None:
    """The option is the only thing that arms one, so an empty request has none."""
    assert _defense(champion) is None


def test_braum_unbreakable_blocks_the_first_hit_and_reduces_the_rest() -> None:
    """Rank 1 Unbreakable: one full block, then 35% off later projectiles."""
    defense = _defense("Braum", e_active=True)
    assert defense.full_block_first is True
    assert defense.damage_reduction == pytest.approx(0.35)
    composition = defense_composition(defense).public_receipt()
    assert composition["full_block"]["mode"] == "first"
    assert composition["full_block_uses"]["uses"] == 1
    assert composition["reduction"]["later_hit_reduction"] == pytest.approx(0.35)


def test_riposte_accepts_every_delivery_and_counter_strike_only_two() -> None:
    """Acceptance is what each defense declares, not what the walk offers it."""
    riposte = defense_eligibility(_defense("Fiora", w_active=True))
    assert riposte.acceptance.accepts_unknown is True
    assert riposte.acceptance.accepts_deliveries() == (
        "projectile",
        "hitscan",
        "area",
        "targeted",
        "basic_attack",
        "damage_over_time",
    )
    counter_strike = defense_eligibility(_defense("Jax", e_active=True))
    assert counter_strike.acceptance.accepts_unknown is False
    assert counter_strike.acceptance.accepts_deliveries() == ("basic_attack", "area")
    assert counter_strike.acceptance.area_damage_reduction == pytest.approx(0.25)


def test_wind_wall_destroys_and_riposte_blocks_true_damage() -> None:
    """Two full-block shapes: destruction, and a block that ignores damage type."""
    wind_wall = defense_composition(_defense("Yasuo", w_active=True)).public_receipt()
    assert wind_wall["destroy"]["enabled"] is True
    assert wind_wall["full_block"]["mode"] == "none"
    riposte = defense_composition(_defense("Fiora", w_active=True)).public_receipt()
    assert riposte["full_block"]["mode"] == "all"
    assert riposte["full_block"]["blocks_true_damage"] is True


def test_the_public_shape_carries_the_window_the_acceptance_and_the_atoms() -> None:
    """One receipt a reader can check a fight's block against."""
    receipt = public_defense(_defense("Pantheon", e_active=True))
    assert receipt["kind"] == "pantheon_aegis_assault"
    assert receipt["source"] == "Pantheon E · Aegis Assault"
    assert receipt["until"] == pytest.approx(1.5)
    assert receipt["acceptance"]["accepts_deliveries"] == ["projectile"]
    assert receipt["composition"]["full_block"]["mode"] == "all"
    assert [atom["atom_id"] for atom in receipt["source_atoms"]] == [
        "timing.active_duration"
    ]


def test_no_defense_publishes_nothing_rather_than_an_empty_shape() -> None:
    """Every public reader answers ``None`` for a combatant with no window."""
    assert public_defense(None) is None
    assert defense_eligibility(None) is None
    assert defense_composition(None) is None
