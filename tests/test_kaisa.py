"""Reference, event-order, and timed-mode tests for Kai'Sa."""

import math
import re

import pytest

from src import app as app_module
from src.calculator.calculate import calculate_payload
from src.calculator.data_fetcher import get_item_by_name
from src.calculator.champions import (
    get_champion_cast_order,
    get_champion_options_meta,
    get_comparison_curve_unavailable_reason,
    get_supported_fight_modes,
    get_unsupported_fight_mode_reason,
    parse_champion_abilities,
)
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.optimizer import _evaluate_build
from src.calculator.pipeline import DEFAULT_AUTO_ATTACK_UPTIME, FightParams, run_fight

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
    luden = run_fight(kaisa_data, 12, [get_item_by_name("Luden's Echo")], params)
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
    assert "2 successive" in bloodthirster["breakdown"]["passive_plasma"]["detail"]


def test_temporary_ap_amp_cannot_unlock_w_evolution(kaisa_data):
    params = FightParams.from_request(
        {"champion_options": {"q_evolved": "auto", "w_evolved": "auto"}}
    )
    result = run_fight(kaisa_data, 12, [get_item_by_name("Blackfire Torch")], params)

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
    base_score = _evaluate_build(kaisa_data, 12, [item], forced_base, "total_damage")
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
    assert (
        result["breakdown"]["Q"]["damage_events"][0]["time"]
        > result["breakdown"]["W"]["damage_events"][0]["time"]
    )


def _timed_payload(duration, *, champion_options=None, include_autos=True):
    """The criterion-3 probe shape: timed calculate_payload, no items."""
    request = {
        "champion": "Kai'Sa",
        "level": 18,
        "items": [],
        "fight_mode": "timed",
        "include_auto_attacks": include_autos,
        "fight_duration": duration,
    }
    if champion_options:
        request["champion_options"] = champion_options
    return calculate_payload(request)


def _plasma_counts(payload):
    """(applications, ruptures) quoted from the plasma row's engine detail."""
    detail = payload["breakdown"]["passive_plasma"]["detail"]
    match = re.search(r"(\d+) stack applications, (\d+) ruptures", detail)
    assert match is not None, detail
    return int(match.group(1)), int(match.group(2))


def test_timed_plasma_ruptures_recur_across_the_window():
    short = _timed_payload(6)
    long = _timed_payload(20)

    _, short_ruptures = _plasma_counts(short)
    long_applications, long_ruptures = _plasma_counts(long)

    assert short_ruptures >= 1
    assert long_ruptures > short_ruptures
    for payload in (short, long):
        coverage = payload["timeline_coverage"]
        assert coverage["complete"] is True
        assert coverage["coarse_sources"] == []
        assert coverage["certification"] == "event_order_certified"

    plasma = long["breakdown"]["passive_plasma"]
    plasma_events = [
        event for event in long["damage_events"] if event["source"] == "passive_plasma"
    ]
    assert plasma["total_damage"] > 0
    assert len(plasma_events) == long_applications + long_ruptures
    assert sum(event["damage"] for event in plasma_events) == pytest.approx(
        plasma["total_damage"], rel=1e-3
    )


@pytest.mark.parametrize(
    "items",
    ([], ["Kraken Slayer"], ["Nashor's Tooth", "Rabadon's Deathcap"]),
)
def test_timed_plasma_stream_reconciles_with_the_engine_timeline(items):
    """The module's walked application stream is the engine's own cadence:
    one stack per real swing plus 2 (3 evolved) per real Void Seeker cast."""
    payload = calculate_payload(
        {
            "champion": "Kai'Sa",
            "level": 18,
            "items": items,
            "fight_mode": "timed",
            "include_auto_attacks": True,
            "fight_duration": 20,
        }
    )
    applications, _ = _plasma_counts(payload)
    per_w_hit = 3 if payload["champion_stats"]["evolution_ability_power"] >= 100 else 2
    assert applications == (
        payload["breakdown"]["auto_attacks"]["count"]
        + payload["breakdown"]["W"]["casts"] * per_w_hit
    )


def test_timed_plasma_stacks_expire_without_an_auto_stream():
    """Void Seeker alone cannot rupture: its recast outlasts the sourced 4s
    stack window, so the walk expires the chain instead of banking stacks."""
    applications, ruptures = _plasma_counts(_timed_payload(20, include_autos=False))

    assert applications > 0
    assert ruptures == 0


def test_timed_plasma_seeded_stacks_rupture_sooner():
    unseeded = _timed_payload(6)
    seeded = _timed_payload(6, champion_options={"plasma_starting_stacks": 4})

    assert _plasma_counts(seeded)[1] > _plasma_counts(unseeded)[1]
    assert (
        seeded["breakdown"]["passive_plasma"]["total_damage"]
        > unseeded["breakdown"]["passive_plasma"]["total_damage"]
    )


def test_supercharge_window_raises_timed_attack_speed_and_auto_cadence():
    timed = _timed_payload(20)
    rotation = calculate_payload({"champion": "Kai'Sa", "level": 18, "items": []})

    timed_as = timed["champion_stats"]["attack_speed"]
    assert timed_as > rotation["champion_stats"]["attack_speed"]
    assert (
        timed["champion_stats"]["bonus_attack_speed"]
        > rotation["champion_stats"]["bonus_attack_speed"]
    )

    autos = timed["breakdown"]["auto_attacks"]
    expected_swings = math.floor(timed_as * 20.0 * DEFAULT_AUTO_ATTACK_UPTIME)
    assert autos["count"] == expected_swings
    swing_events = [
        event for event in timed["damage_events"] if event["source"] == "auto_attacks"
    ]
    assert len(swing_events) == expected_swings


def test_timed_mode_drops_the_one_rotation_travel_wait():
    """The certified W -> Q wait is a one-rotation artifact; timed casts run
    on the real shared timeline (W occupies its 0.4s cast, Q volleys while
    Void Seeker is still in flight, R anchors the Plasma ledger once)."""
    payload = _timed_payload(20)

    q_first = min(
        event["time"] for event in payload["damage_events"] if event["source"] == "Q"
    )
    w_first = min(
        event["time"] for event in payload["damage_events"] if event["source"] == "W"
    )
    assert q_first < w_first

    timeline = payload["cast_timeline"]
    assert [event["slot"] for event in timeline[:2]] == ["W", "Q"]
    assert timeline[0]["time"] == pytest.approx(0.0)
    assert [event["slot"] for event in timeline].count("R") == 1


def test_evolved_void_seeker_refunds_its_timed_cooldown():
    base = _timed_payload(20, champion_options={"w_evolved": "base"})
    evolved = _timed_payload(20, champion_options={"w_evolved": "evolved"})

    assert evolved["breakdown"]["W"]["casts"] > base["breakdown"]["W"]["casts"]


def test_timed_and_auto_only_requests_now_compute():
    client = app_module.app.test_client()

    timed = client.post(
        "/api/calculate",
        json={"champion": "Kai'Sa", "level": 12, "fight_mode": "time_based"},
    )
    assert timed.status_code == 200
    assert timed.get_json()["total_damage"] > 0

    auto_only = client.post(
        "/api/calculate",
        json={
            "champion": "Kai'Sa",
            "level": 12,
            "fight_mode": "auto_only",
            "auto_attacks_only": True,
            "include_auto_attacks": True,
        },
    )
    assert auto_only.status_code == 200
    assert auto_only.get_json()["breakdown"]["auto_attacks"]["total_damage"] > 0


def test_custom_cast_orders_stay_refused():
    reordered = app_module.app.test_client().post(
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


def test_sources_options_and_unrestricted_modes_are_public_receipts():
    meta = get_champion_options_meta("Kai'Sa")

    assert len(meta["options"]) == 4
    assert "supported_fight_modes" not in meta
    assert get_supported_fight_modes("Kai'Sa") is None
    assert get_unsupported_fight_mode_reason("Kai'Sa") is None
    assert get_comparison_curve_unavailable_reason("Kai'Sa") is None
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
