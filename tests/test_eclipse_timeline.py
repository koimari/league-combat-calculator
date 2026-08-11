"""Precision receipts for Eclipse's two-hit, cooldown-gated passive."""

from src.calculator.ability_spec import DamagePart
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.scenario import load_public_champion as _load_public_champion
from src.calculator.data_fetcher import get_item_by_name
from src.calculator.pipeline import FightParams, run_fight


def _stats() -> dict:
    return {
        "attack_damage": 100,
        "ability_power": 0,
        "base_attack_damage": 100,
        "attack_speed": 1.0,
        "attack_speed_ratio": 0.625,
        "magic_penetration_flat": 0,
        "magic_penetration_percent": 0,
        "armor_penetration_percent": 0,
        "flat_armor_penetration": 0,
        "critical_strike_chance": 0,
        "is_melee": False,
        "level": 18,
    }


def _ability(
    name: str, cooldown: float = 5.0, time_offset: float | None = None
) -> dict:
    return {
        "name": name,
        "rank": 1,
        "cooldown": cooldown,
        "physical_damage": 100,
        "parts": (DamagePart("physical", 100, time_offset=time_offset),),
        "total_raw": 100,
        "damage_type": "physical",
    }


def _fight(abilities: dict, *, duration: float, **kwargs) -> dict:
    kwargs.setdefault("auto_attack_uptime", 0.0)
    return calculate_fight_damage(
        _stats(),
        abilities,
        [{"name": "Eclipse"}],
        FightConfig(
            target_health=2000,
            target_armor=0,
            target_magic_resistance=0,
            fight_duration_seconds=duration,
            **kwargs,
        ),
    )


def test_eclipse_arms_on_two_distinct_ability_casts() -> None:
    """Two same-time casts complete one Eclipse pair at the cast boundary."""
    fight = _fight(
        {"Q": _ability("Q"), "W": _ability("W")}, duration=1.0, one_rotation=True
    )

    row = fight["breakdown"]["proc_Eclipse"]
    assert row["count"] == 1
    assert row["damage_events"] == [
        {
            "time": 0.0,
            "damage": 80.0,
            "damage_type": "physical",
            "event_precision": "exact",
            "target_id": "target:0",
        }
    ]


def test_eclipse_prefers_authored_ability_hit_time() -> None:
    """An authored hit boundary makes the completed pair exact."""
    fight = _fight(
        {
            "Q": _ability("Q", time_offset=0.25),
            "W": _ability("W", time_offset=0.5),
        },
        duration=1.0,
        one_rotation=True,
    )

    row = fight["breakdown"]["proc_Eclipse"]
    assert row["damage_events"] == [
        {
            "time": 0.5,
            "damage": 80.0,
            "damage_type": "physical",
            "event_precision": "hit",
            "target_id": "target:0",
        }
    ]
    assert "proc_Eclipse" in fight["timeline_coverage"]["exact_sources"]


def test_eclipse_pairing_waits_for_cooldown_before_next_pair() -> None:
    """A second pair cannot proc until the six-second cooldown expires."""
    fight = _fight(
        {"Q": _ability("Q", cooldown=1.0), "W": _ability("W", cooldown=5.0)},
        duration=7.0,
        one_rotation=False,
    )

    row = fight["breakdown"]["proc_Eclipse"]
    assert row["count"] == 2
    assert [event["time"] for event in row["damage_events"]] == [0.0, 7.0]
    # The Q/W fixtures are certified single-hit casts (cast boundary IS the
    # hit), so both Eclipse triggers ride exact precision.
    assert all(event["event_precision"] == "exact" for event in row["damage_events"])


def test_eclipse_can_pair_an_ability_with_an_authored_auto_swing() -> None:
    """An ability and a separately authored same-time swing count twice."""
    fight = _fight(
        {"Q": _ability("Q")},
        duration=1.0,
        one_rotation=True,
        auto_attack_uptime=1.0,
    )

    row = fight["breakdown"]["proc_Eclipse"]
    assert row["count"] == 1
    assert row["damage_events"][0]["time"] == 0.0
    assert row["damage_events"][0]["event_precision"] == "exact"


def test_ziggs_reviewed_single_hit_packets_keep_eclipse_event_order_exact() -> None:
    """Ziggs' direct Q/W/E/R packets certify Eclipse's third trigger."""
    params = FightParams.from_request(
        {
            "fight_mode": "time_based",
            "fight_duration": 20,
            "rotations": 2,
            "include_auto_attacks": True,
            "auto_attack_uptime": 0,
            "auto_attack_uptime_mode": "calculated",
            "ability_ranks": {"Q": 4, "W": 3, "E": 3, "R": 2},
            "role": "mid",
            "role_quest_complete": True,
        },
        deterministic=True,
    )
    result = run_fight(
        _load_public_champion("Ziggs"),
        12,
        [get_item_by_name("Eclipse")],
        params,
    )

    row = result["breakdown"]["proc_Eclipse"]
    assert row["count"] >= 2
    assert all(event["event_precision"] == "exact" for event in row["damage_events"])
    assert "proc_Eclipse" in result["timeline_coverage"]["exact_sources"]
    assert result["timeline_coverage"]["complete"] is True
