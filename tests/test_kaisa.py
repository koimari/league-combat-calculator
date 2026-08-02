"""Reference, event-order, and fail-closed tests for Kai'Sa."""

import pytest

from src import app as app_module
from src.calculator.data_fetcher import get_item_by_name
from src.calculator.champions import (
    get_champion_cast_order,
    get_champion_options_meta,
    parse_champion_abilities,
)
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.optimizer import _evaluate_build
from src.calculator.pipeline import FightParams, run_fight


RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}


def _stats(*, ap=100.0, attack_damage=200.0, bonus_ad=100.0):
    return {
        "health": 2000.0,
        "bonus_health": 0.0,
        "attack_damage": attack_damage,
        "base_attack_damage": attack_damage - bonus_ad,
        "bonus_attack_damage": bonus_ad,
        "ability_power": ap,
        "armor": 50.0,
        "magic_resistance": 50.0,
        "attack_speed": 1.0,
        "attack_speed_ratio": 0.644,
        "critical_strike_chance": 0.0,
        "magic_penetration_flat": 0.0,
        "magic_penetration_percent": 0.0,
        "flat_armor_penetration": 0.0,
        "armor_penetration_percent": 0.0,
        "lethality": 0.0,
        "ability_haste": 0.0,
        "max_mana": 2000.0,
        "bonus_mana": 0.0,
        "basic_ability_haste": 0.0,
        "is_melee": False,
        "level": 18,
    }


def _abilities(kaisa_data, *, q_evolved=False, w_evolved=False, stacks=0):
    stats = _stats()
    abilities = parse_champion_abilities(
        kaisa_data,
        18,
        stats["ability_power"],
        ability_ranks=RANKS,
        champion_stats=stats,
        target_stats={
            "target_max_health": 2500.0,
            "target_current_health": 2500.0,
        },
        champion_options={
            "q_evolved": q_evolved,
            "w_evolved": w_evolved,
            "plasma_starting_stacks": stacks,
            "w_target_distance": 700.0,
        },
    )
    return stats, abilities


def _fight(stats, abilities):
    return calculate_fight_damage(
        stats,
        abilities,
        [],
        FightConfig(
            target_health=2500.0,
            target_armor=0.0,
            target_magic_resistance=0.0,
            fight_duration_seconds=5.0,
            one_rotation=True,
            deterministic=True,
            enforce_resource_limits=True,
            cast_order=get_champion_cast_order("Kai'Sa"),
        ),
    )


def test_q_reference_formulas_and_evolution(kaisa_data):
    _, normal = _abilities(kaisa_data)
    _, evolved = _abilities(kaisa_data, q_evolved=True)

    # Q5: normal 225 + 123.75% bonus AD + 45% AP; evolved uses
    # 375 + 206.25% bonus AD + 75% AP.
    assert normal["Q"]["total_raw"] == pytest.approx(393.75)
    assert evolved["Q"]["total_raw"] == pytest.approx(656.25)
    assert normal["Q"]["parts"][1].count == 5
    assert evolved["Q"]["parts"][1].count == 11


def test_w_applies_successive_plasma_after_spell_damage(kaisa_data):
    stats, abilities = _abilities(kaisa_data, stacks=4)
    result = _fight(stats, abilities)

    # W5 = 130 + 130% total AD + 45% AP = 435. First Plasma application
    # at four prior stacks is 86; rupture then sees 521 missing health and
    # deals 21% of it = 109.41. W's excess second stack reapplies for 42.
    assert result["breakdown"]["W"]["total_damage"] == pytest.approx(435.0)
    assert result["breakdown"]["passive_plasma"]["total_damage"] == pytest.approx(
        237.41
    )
    assert result["breakdown"]["Q"]["total_damage"] == pytest.approx(393.75)
    assert result["total_damage"] == pytest.approx(1066.16)


def test_evolved_w_adds_three_plasma_applications(kaisa_data):
    _, normal = _abilities(kaisa_data)
    _, evolved = _abilities(kaisa_data, w_evolved=True)

    assert len(normal["W"]["post_hit_proc"]["parts"]) == 2
    assert len(evolved["W"]["post_hit_proc"]["parts"]) == 3
    assert "3 successive" in evolved["W"]["post_hit_proc"]["detail"]


def test_build_owned_stats_automatically_unlock_each_evolution(kaisa_data):
    params = FightParams.from_request(
        {"champion_options": {"q_evolved": "auto", "w_evolved": "auto"}}
    )
    empty = run_fight(kaisa_data, 12, [], params)
    luden = run_fight(
        kaisa_data, 12, [get_item_by_name("Luden's Echo")], params
    )
    bloodthirster = run_fight(
        kaisa_data, 12, [get_item_by_name("Bloodthirster")], params
    )

    assert empty["champion_stats"]["evolution_attack_damage"] < 100
    assert empty["champion_stats"]["evolution_ability_power"] == 0
    assert empty["breakdown"]["Q"]["detail"].startswith("6 missiles")
    assert "2 successive" in empty["breakdown"]["passive_plasma"]["detail"]

    assert luden["champion_stats"]["evolution_ability_power"] == 100
    assert "3 successive" in luden["breakdown"]["passive_plasma"]["detail"]
    assert "100.0/100 item AP" in luden["breakdown"]["passive_plasma"]["detail"]
    assert luden["breakdown"]["Q"]["detail"].startswith("6 missiles")

    assert bloodthirster["champion_stats"]["evolution_attack_damage"] > 100
    assert bloodthirster["breakdown"]["Q"]["detail"].startswith("12 missiles")
    assert "AD from items + growth" in bloodthirster["breakdown"]["Q"]["detail"]
    assert "2 successive" in bloodthirster["breakdown"]["passive_plasma"][
        "detail"
    ]


def test_temporary_ap_amp_cannot_unlock_w_evolution(kaisa_data):
    params = FightParams.from_request(
        {"champion_options": {"q_evolved": "auto", "w_evolved": "auto"}}
    )
    result = run_fight(
        kaisa_data, 12, [get_item_by_name("Blackfire Torch")], params
    )

    assert result["champion_stats"]["ability_power"] == 83
    assert result["champion_stats"]["evolution_ability_power"] == 80
    assert "2 successive" in result["breakdown"]["passive_plasma"]["detail"]


def test_evolution_attack_speed_counts_items_and_level_growth(kaisa_data):
    params = FightParams.from_request(
        {"champion_options": {"q_evolved": "auto", "w_evolved": "auto"}}
    )
    result = run_fight(
        kaisa_data,
        12,
        [
            get_item_by_name("Nashor's Tooth"),
            get_item_by_name("Wit's End"),
        ],
        params,
    )

    assert result["champion_stats"]["evolution_attack_speed_percent"] > 100


def test_optimizer_evaluator_resolves_evolution_per_candidate(kaisa_data):
    auto = FightParams.from_request(
        {"champion_options": {"q_evolved": "auto", "w_evolved": "auto"}},
        deterministic=True,
    )
    forced_base = FightParams.from_request(
        {"champion_options": {"q_evolved": "base", "w_evolved": "base"}},
        deterministic=True,
    )
    forced_evolved = FightParams.from_request(
        {
            "champion_options": {
                "q_evolved": "base",
                "w_evolved": "evolved",
            }
        },
        deterministic=True,
    )
    item = get_item_by_name("Luden's Echo")

    auto_score = _evaluate_build(kaisa_data, 12, [item], auto, "total_damage")
    base_score = _evaluate_build(
        kaisa_data, 12, [item], forced_base, "total_damage"
    )
    evolved_score = _evaluate_build(
        kaisa_data, 12, [item], forced_evolved, "total_damage"
    )

    assert auto_score == pytest.approx(evolved_score)
    assert auto_score > base_score


def test_explicit_override_and_legacy_boole_remain_supported(kaisa_data):
    no_items = []
    forced = run_fight(
        kaisa_data,
        12,
        no_items,
        FightParams.from_request(
            {
                "champion_options": {
                    "q_evolved": "evolved",
                    "w_evolved": "evolved",
                }
            }
        ),
    )
    legacy = app_module.app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Kai'Sa",
            "level": 12,
            "champion_options": {"q_evolved": True, "w_evolved": False},
        },
    )

    assert forced["breakdown"]["Q"]["detail"].startswith("12 missiles")
    assert "3 successive" in forced["breakdown"]["passive_plasma"]["detail"]
    assert legacy.status_code == 200
    assert legacy.get_json()["breakdown"]["Q"]["detail"].startswith("12 missiles")


def test_rotation_is_event_order_certified_and_resource_legal(kaisa_data):
    stats, abilities = _abilities(kaisa_data, stacks=4)
    result = _fight(stats, abilities)

    assert result["resource_spent"] == pytest.approx(130.0)
    assert result["resource_remaining"] == pytest.approx(1870.0)
    assert result["timeline_coverage"]["complete"] is True
    assert result["timeline_coverage"]["certification"] == "event_order_certified"
    assert result["timeline_coverage"]["exact_sources"] == [
        "Q",
        "W",
        "passive_plasma",
    ]
    assert result["breakdown"]["passive_plasma"]["damage_events"][0][
        "time"
    ] == pytest.approx(result["breakdown"]["W"]["damage_events"][0]["time"])
    assert result["breakdown"]["Q"]["damage_events"][0]["time"] > result[
        "breakdown"
    ]["W"]["damage_events"][0]["time"]


def test_timed_and_auto_only_requests_fail_closed():
    client = app_module.app.test_client()
    for fight_mode in ("time_based", "auto_only"):
        response = client.post(
            "/api/calculate",
            json={"champion": "Kai'Sa", "level": 12, "fight_mode": fight_mode},
        )
        assert response.status_code == 400
        assert "Time-based Kai'Sa calculations are withheld" in response.get_json()[
            "error"
        ]

    reordered = client.post(
        "/api/calculate",
        json={
            "champion": "Kai'Sa",
            "level": 12,
            "fight_mode": "one_rotation",
            "cast_order": ["Q", "W", "E", "R"],
        },
    )
    assert reordered.status_code == 400
    assert "certified W -> Q sequence" in reordered.get_json()["error"]


def test_sources_options_and_mode_are_public_revision_receipts():
    meta = get_champion_options_meta("Kai'Sa")

    assert len(meta["options"]) == 4
    assert meta["supported_fight_modes"] == ["one_rotation"]
    assert {row["revision_id"] for row in meta["sources"]} == {
        4046579,
        4038389,
        4034696,
        4038391,
        4034697,
    }
    assert all(
        row["url"].startswith("https://wiki.leagueoflegends.com/")
        for row in meta["sources"]
    )
