"""Focused CP8 regression tests for the nine former withholdings."""

import pytest

from src.calculator.champions import parse_champion_abilities
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.stats import calculate_total_stats

FORMER_WITHHOLDINGS = [
    ("Akshan", "Akshan"),
    ("Belveth", "Bel'Veth"),
    ("Kalista", "Kalista"),
    ("Ornn", "Ornn"),
    ("Qiyana", "Qiyana"),
    ("Shyvana", "Shyvana"),
    ("TahmKench", "Tahm Kench"),
    ("MonkeyKing", "Wukong"),
    ("Ziggs", "Ziggs"),
]


def _fight(champion_data, *, options=None):
    items = [get_item_by_name("Shadowflame")]
    stats = calculate_total_stats(champion_data, 18, items)
    abilities = parse_champion_abilities(
        champion_data,
        18,
        stats.get("ability_power", 0.0),
        champion_stats=stats,
        target_stats={"target_max_health": 10_000.0},
        champion_options=options,
    )
    return abilities, calculate_fight_damage(
        stats,
        abilities,
        items,
        FightConfig(
            target_health=10_000.0,
            target_armor=0.0,
            target_magic_resistance=0.0,
            fight_duration_seconds=4.0,
            one_rotation=True,
            deterministic=True,
        ),
    )


@pytest.mark.parametrize(("data_key", "display_name"), FORMER_WITHHOLDINGS)
def test_former_withholding_has_a_complete_event_timeline(data_key, display_name):
    champion_data = get_champion(data_key)
    assert champion_data["name"] == display_name
    _, result = _fight(champion_data)
    assert result["timeline_coverage"]["complete"] is True
    assert result["timeline_coverage"]["coarse_sources"] == []


def test_multi_hit_and_state_packets_are_not_generated_single_hits():
    kalista = get_champion("Kalista")
    kalista_abilities, _ = _fight(
        kalista, options={"rend_stacks": 3, "soul_mark_proc": True}
    )
    assert kalista_abilities["E"]["detail"] == "3 Rend stack(s)"
    assert "W" in kalista_abilities

    ornn = get_champion("Ornn")
    ornn_abilities, _ = _fight(ornn)
    assert ornn_abilities["W"]["parts"][0].count == 5
    assert ornn_abilities["W"]["parts"][0].hit_interval == pytest.approx(0.15)

    wukong = get_champion("MonkeyKing")
    wukong_abilities, _ = _fight(wukong)
    assert wukong_abilities["R"]["parts"][0].count == 8
    assert wukong_abilities["R"]["parts"][0].hit_interval == pytest.approx(0.25)


def test_state_only_branches_do_not_become_direct_damage():
    qiyana_abilities, _ = _fight(get_champion("Qiyana"))
    assert qiyana_abilities["W"]["parts"] == ()
    tahm_abilities, _ = _fight(get_champion("TahmKench"))
    assert "E" not in tahm_abilities


def test_ability_carried_belveth_on_hit_is_timestamped():
    _, result = _fight(get_champion("Belveth"))
    row = result["breakdown"]["on_hit_ability_R_onhit"]
    assert row["damage_events"]
    assert len(row["damage_events"]) == row["count"]
