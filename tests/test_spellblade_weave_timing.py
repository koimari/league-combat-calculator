"""When a spellblade charge is consumed, and by what.

The weave delay is the walk-up to an auto attack.  An ability that applies
item on-hit effects is itself the attack that takes the charge (Ezreal Q,
Senna Q), so its proc lands at that ability's own authored hit time; a kit
with no such ability still walks the delay (Ahri).
"""

from types import SimpleNamespace

import pytest

from src.calculator.champions import parse_champion_abilities
from src.calculator.damage import (
    AbilityItemApplication,
    FightConfig,
    RotationResult,
    _spellblade_proc_times,
    calculate_fight_damage,
)
from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.stats import calculate_total_stats

TRINITY = "Trinity Force"


def _proc_times(champion: str) -> list[float]:
    """The Trinity Force proc timestamps *champion* authors, through the engine."""
    champ = get_champion(champion)
    item = get_item_by_name(TRINITY)
    stats = calculate_total_stats(champ, 18, [item])
    abilities = parse_champion_abilities(
        champ, 18, stats["ability_power"], champion_stats=stats
    )
    fight = calculate_fight_damage(
        dict(stats),
        abilities,
        [item],
        FightConfig(
            target_health=3000.0,
            target_armor=60.0,
            target_magic_resistance=60.0,
            fight_duration_seconds=5.0,
            one_rotation=True,
            deterministic=True,
            auto_attack_uptime=1.0,
        ),
    )
    row = fight["breakdown"][f"spellblade_{TRINITY}"]
    return [float(event["time"]) for event in row["damage_events"]]


@pytest.mark.parametrize("champion", ["Ezreal", "Senna"])
def test_an_on_hit_applying_ability_takes_the_charge_at_its_own_hit(champion):
    """Q applies on-hit at 0.0, so the first proc is at 0.0, not the walked 1.5."""
    assert _proc_times(champion) == pytest.approx([0.0, 3.0])


def test_a_kit_with_no_on_hit_ability_still_walks_the_weave_delay():
    """Ahri's control: nothing but an auto can take the charge."""
    assert _proc_times("Ahri") == pytest.approx([1.5, 4.5])


def test_the_charge_waits_for_an_on_hit_ability_it_can_reach():
    """An on-hit hit before the charge is armed cannot take it."""
    effect = SimpleNamespace(cooldown=1.5, weave_delay=1.5)
    rotation = RotationResult(
        cast_events=[{"slot": "Q", "time": 4.0}],
        ability_item_applications=[
            AbilityItemApplication(
                effectiveness=1.0,
                target_hp=3000.0,
                on_hit=True,
                on_attack=False,
                time=1.0,
            )
        ],
    )

    assert _spellblade_proc_times(rotation, effect, 1) == [5.5]
