"""Integration tests for authored control and projectile-defense atoms."""

import pytest

from src.app import app
from src.calculator.champions import parse_champion_abilities
from src.calculator.data_fetcher import get_champion
from src.calculator.interaction_effects import resolve_physical_damage_reduction
from src.calculator.stats import calculate_total_stats


def _calculate(payload: dict) -> dict:
    app.config["TESTING"] = True
    response = app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200, response.get_data(as_text=True)[:500]
    return response.get_json()["combat"]


def _events(combat: dict, *, attacker: str, target: str, source: str) -> list[dict]:
    return [
        event
        for event in combat["events"]
        if event.get("attacker") == attacker
        and event.get("target") == target
        and event.get("source") == source
    ]


def _survival(combat: dict, participant_id: str) -> dict:
    return next(
        row["survival"]
        for row in combat["participants"]
        if row["participant_id"] == participant_id
    )


def test_amumu_tantrum_resolves_ranked_atoms_and_exposes_receipts():
    champion_data = get_champion("Amumu")
    combatant = type(
        "AmumuTarget",
        (),
        {
            "champion_data": champion_data,
            "level": 18,
            "stats": {"bonus_armor": 100.0, "bonus_magic_resistance": 50.0},
            "request": type("Request", (), {"ability_ranks": {"E": 5}})(),
        },
    )()

    reduction = resolve_physical_damage_reduction(combatant)

    assert reduction is not None
    assert reduction.flat_amount == pytest.approx(17.5)
    assert reduction.per_instance_cap == pytest.approx(0.5)
    assert [atom["source"] for atom in reduction.source_atoms] == [
        "Amumu.E[0].effects[0].leveling[0].modifiers[0]",
        "Amumu.E[0].effects[0].leveling[0].modifiers[1]",
        "Amumu.E[0].effects[0].leveling[0].modifiers[2]",
        "Amumu.E[0].effects[0].description",
    ]


def test_amumu_tantrum_reduction_reaches_the_survival_receipt():
    combat = _calculate(
        {
            "champion": "Ezreal",
            "level": 18,
            "items": [],
            "fight_mode": "one_rotation",
            "include_auto_attacks": False,
            "ability_ranks": {"Q": 5, "W": 0, "E": 0, "R": 0},
            "enemies": [
                {
                    "champion": "Amumu",
                    "level": 18,
                    "items": [],
                    "ability_ranks": {"Q": 0, "W": 0, "E": 5, "R": 0},
                }
            ],
        }
    )

    reduction = _survival(combat, "enemy:Amumu")["physical_damage_reduction"]
    assert reduction["source"] == "Amumu E · Tantrum"
    assert reduction["per_instance_cap"] == pytest.approx(0.5)
    assert reduction["source_atoms"][-1]["source"] == (
        "Amumu.E[0].effects[0].description"
    )


def test_braum_e_blocks_one_selected_skillshot_then_reduces_later_hits():
    combat = _calculate(
        {
            "champion": "Ezreal",
            "level": 18,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 4,
            "include_auto_attacks": False,
            "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
            "enemies": [
                {
                    "champion": "Braum",
                    "level": 18,
                    "items": [],
                    "champion_options": {
                        "e_active": True,
                        "e_active_seconds": 4.0,
                        "e_blocked_skillshots": ["Q"],
                    },
                }
            ],
        }
    )

    q_events = _events(combat, attacker="main", target="enemy:Braum", source="Q")
    assert len(q_events) >= 2
    q_events.sort(key=lambda event: event["time"])
    first, later = q_events[:2]
    assert first["skillshot"] is True
    assert first["damage"] == pytest.approx(0.0)
    assert first["projectile_defense"]["mode"] == "full_block"
    assert later["damage"] > 0.0
    assert later["projectile_defense"]["mode"] == "reduced"
    assert later["projectile_defense"]["reduction"] == pytest.approx(0.55)
    assert [
        atom["source"]
        for atom in _survival(combat, "enemy:Braum")["projectile_defense"][
            "source_atoms"
        ]
    ] == [
        "Braum.E[0].effects[0].leveling[1].modifiers[0]",
        "Braum.E[0].effects[0].leveling[0].modifiers[0]",
    ]

    survival = _survival(combat, "enemy:Braum")
    assert survival["projectile_defense"]["until"] == pytest.approx(4.0)
    assert survival["projectile_defense_blocked"] == [
        {"time": first["time"], "source": "Q", "mode": "full_block"}
    ]


def test_braum_e_blocks_control_with_the_projectile():
    combat = _calculate(
        {
            "champion": "Ahri",
            "level": 18,
            "items": [],
            "fight_mode": "one_rotation",
            "include_auto_attacks": False,
            "ability_ranks": {"Q": 0, "W": 0, "E": 5, "R": 0},
            "enemies": [
                {
                    "champion": "Braum",
                    "level": 18,
                    "items": [],
                    "champion_options": {
                        "e_active": True,
                        "e_active_seconds": 4.0,
                        "e_blocked_skillshots": ["E"],
                    },
                }
            ],
        }
    )

    charm = _events(combat, attacker="main", target="enemy:Braum", source="E")[0]
    assert charm["damage"] == pytest.approx(0.0)
    assert charm["cc_kind"] == "immobilize"
    assert charm["projectile_defense"]["mode"] == "full_block"
    assert _survival(combat, "enemy:Braum")["crowd_control_intervals"] == []


def test_yasuo_w_blocks_selected_skillshots_only_during_active_window():
    combat = _calculate(
        {
            "champion": "Ezreal",
            "level": 18,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 4,
            "include_auto_attacks": False,
            "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
            "enemies": [
                {
                    "champion": "Yasuo",
                    "level": 18,
                    "items": [],
                    "champion_options": {
                        "w_active": True,
                        "w_active_seconds": 1.0,
                        "w_blocked_skillshots": ["Q"],
                    },
                }
            ],
        }
    )

    q_events = _events(combat, attacker="main", target="enemy:Yasuo", source="Q")
    assert len(q_events) >= 2
    first = q_events[0]
    later = next(event for event in q_events if event["time"] >= 1.0)
    assert first["skipped_reason"] == "yasuo_wind_wall"
    assert first["projectile_defense"]["mode"] == "destroyed"
    assert later["damage"] > 0.0
    assert "projectile_defense" not in later

    survival = _survival(combat, "enemy:Yasuo")
    assert survival["projectile_defense"]["until"] == pytest.approx(1.0)
    assert survival["projectile_defense"]["source_atoms"][0]["source"] == (
        "Yasuo.W[0].effects[0].description"
    )
    assert survival["projectile_defense_blocked"] == [
        {"time": first["time"], "source": "Q", "mode": "destroyed"}
    ]


def test_sivir_e_blocks_one_effect_and_schedules_its_sourced_heal():
    combat = _calculate(
        {
            "champion": "Sivir",
            "level": 18,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 2.0,
            "include_auto_attacks": False,
            "cast_order": ["E", "Q", "R", "W"],
            "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
            "enemies": [
                {
                    "champion": "Ahri",
                    "level": 18,
                    "items": [],
                    "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
                }
            ],
        }
    )

    state_events = [
        event
        for event in combat["support_events"]
        if event.get("source") == "Spell Shield"
    ]
    assert len(state_events) == 1
    assert state_events[0]["kind"] == "spell_shield"
    assert state_events[0]["time"] == pytest.approx(0.0)
    assert state_events[0]["duration"] == pytest.approx(1.5)
    assert not any(
        event.get("source") == "Spell Shield · Heal"
        for event in combat["support_events"]
    )

    blocked = next(
        event
        for event in combat["events"]
        if event.get("attacker") == "enemy:Ahri"
        and event.get("target") == "main"
        and event.get("source") == "E"
    )
    assert blocked["skipped_reason"] == "spell_shield"
    assert blocked["spell_shield_source"] == "Spell Shield"
    heals = [
        event
        for event in combat["healing_events"]
        if event.get("source") == "Spell Shield · Heal"
    ]
    assert len(heals) == 1
    assert heals[0]["attacker"] == "main"
    assert heals[0]["time"] == pytest.approx(0.25)
    assert heals[0]["applied_amount"] > 0.0
    assert _survival(combat, "main")["spell_shield_heal_triggered"] is True


def test_morgana_black_shield_selects_one_ally_and_blocks_magic_cc():
    combat = _calculate(
        {
            "champion": "Morgana",
            "level": 18,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 6.0,
            "include_auto_attacks": False,
            "ability_ranks": {"Q": 0, "W": 0, "E": 5, "R": 0},
            "support_target_selections": {"shield:E:0": 1},
            "enemies": [
                {
                    "champion": "Ahri",
                    "level": 18,
                    "items": [],
                    "ability_ranks": {"Q": 0, "W": 0, "E": 5, "R": 0},
                }
            ],
            "allies": [
                {
                    "champion": "Jinx",
                    "level": 18,
                    "items": [],
                    "ally_effects_enabled": True,
                },
                {
                    "champion": "Lux",
                    "level": 18,
                    "items": [],
                    "ally_effects_enabled": True,
                },
            ],
        }
    )

    shield = next(
        event
        for event in combat["support_events"]
        if event.get("source") == "Black Shield · Magic Shield Strength"
    )
    assert shield["target"] == "ally:Lux"
    assert shield["target_selection_key"] == "shield:E:0"
    assert shield["shield_pool"] == "magic"
    assert shield["duration"] == pytest.approx(5.0)
    assert shield["crowd_control_immunity_while_shield"] is True

    charm = _events(
        combat,
        attacker="enemy:Ahri",
        target="ally:Lux",
        source="E",
    )[0]
    assert charm["damage"] > 0.0
    assert charm["crowd_control_blocked"]["source"] == "Black Shield"
    lux_survival = _survival(combat, "ally:Lux")
    assert lux_survival["health_damage"] == pytest.approx(0.0)
    assert lux_survival["crowd_control_intervals"] == []
    assert lux_survival["action_downtime"] == pytest.approx(0.0)
    assert lux_survival["crowd_control_immunity_until"] == pytest.approx(0.0)


def test_summon_aery_follows_the_selected_support_recipient():
    combat = _calculate(
        {
            "champion": "Sona",
            "level": 18,
            "items": [],
            "keystone": "Summon Aery",
            "fight_mode": "time_based",
            "fight_duration": 2.0,
            "include_auto_attacks": False,
            "support_target_selections": {
                "shield:W:0": 1,
                "heal:W:1": 1,
            },
            "enemies": [{"champion": "Aatrox", "level": 18, "items": []}],
            "allies": [
                {
                    "champion": "Jinx",
                    "level": 18,
                    "items": [],
                    "ally_effects_enabled": True,
                },
                {
                    "champion": "Lux",
                    "level": 18,
                    "items": [],
                    "ally_effects_enabled": True,
                },
            ],
        }
    )

    sona_support = [
        event for event in combat["support_events"] if event.get("attacker") == "main"
    ]
    selected_shield = next(
        event
        for event in sona_support
        if event.get("source") == "Aria of Perseverance · Shield Strength"
        and event.get("target") == "ally:Lux"
    )
    aery = next(
        event for event in sona_support if event.get("source") == "Summon Aery · Shield"
    )
    assert selected_shield["target_selection_key"] == "shield:W:0"
    assert aery["target"] == "ally:Lux"
    assert aery["time"] == pytest.approx(0.35)
    assert aery["duration"] == pytest.approx(2.0)
    assert aery["amount"] == pytest.approx(100.0)
    assert aery["applied_amount"] == pytest.approx(100.0)


def test_glacial_zone_reduces_only_the_immobilized_enemy_damage_to_allies():
    combat = _calculate(
        {
            "champion": "Morgana",
            "level": 18,
            "items": [],
            "keystone": "Glacial Augment",
            "fight_mode": "time_based",
            "fight_duration": 6.0,
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
            "ability_ranks": {"Q": 5, "W": 0, "E": 0, "R": 0},
            "enemies": [
                {
                    "champion": "Aatrox",
                    "level": 18,
                    "items": [],
                    "ability_ranks": {"Q": 0, "W": 0, "E": 0, "R": 0},
                }
            ],
            "allies": [
                {
                    "champion": "Jinx",
                    "level": 18,
                    "items": [],
                    "ally_effects_enabled": True,
                }
            ],
        }
    )

    zone = next(
        event
        for event in combat["support_events"]
        if event["source"] == "Glacial Augment · Icy zone"
    )
    assert zone["target"] == "enemy:Aatrox"
    assert zone["amount"] == pytest.approx(20.0)
    assert zone["duration"] == pytest.approx(6.0)
    assert zone["glacial_ray_count"] == pytest.approx(3.0)
    assert zone["glacial_zone_radius_units"] == pytest.approx(700.0)
    assert zone["glacial_zone_width_units"] == pytest.approx(80.0)

    reduction = next(
        event
        for event in combat["support_events"]
        if event["source"] == "Glacial Augment · Ally damage reduction"
    )
    assert reduction["target"] == "ally:Jinx"
    assert reduction["source_participant"] == "enemy:Aatrox"
    assert reduction["multiplier"] == pytest.approx(0.85)

    reduced_hits = [
        event
        for event in combat["events"]
        if event["attacker"] == "enemy:Aatrox"
        and event["target"] == "ally:Jinx"
        and event["time"] >= 3.0
        and event["damage"] > 0.0
    ]
    assert reduced_hits
    assert all(
        event["support_damage_multiplier"]["multiplier"] == pytest.approx(0.85)
        for event in reduced_hits
    )


def test_stormraider_authors_target_window_movement_and_slow_resistance():
    combat = _calculate(
        {
            "champion": "Ahri",
            "level": 18,
            "items": [],
            "keystone": "Stormraider's Surge",
            "fight_mode": "time_based",
            "fight_duration": 6.0,
            "include_auto_attacks": False,
            "target_health": 1000.0,
            "target_armor": 0.0,
            "target_mr": 0.0,
            "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
            "enemies": [
                {
                    "champion": "Aatrox",
                    "level": 18,
                    "items": [],
                    "ability_ranks": {"Q": 0, "W": 0, "E": 0, "R": 0},
                }
            ],
        }
    )

    burst = next(
        event
        for event in combat["support_events"]
        if event["source"] == "Stormraider's Surge · Movement burst"
    )
    assert burst["target"] == "main"
    assert burst["amount"] == pytest.approx(36.0)
    assert burst["bonus_move_speed_percent"] == pytest.approx(36.0)
    assert burst["slow_resist_percent"] == pytest.approx(50.0)
    assert burst["duration"] == pytest.approx(4.0)
    assert burst["stormraider_damage_threshold_ratio"] == pytest.approx(0.25)
    assert burst["stormraider_damage_window_seconds"] == pytest.approx(3.0)
    assert (
        burst["stormraider_trigger_damage"]
        >= burst["stormraider_target_max_health"] * 0.25
    )
    utility = combat["utility_outcomes"]["focus"]
    assert utility["applied_dimensions"] == ["movement", "slow_resistance"]
    assert utility["slow_resistance"]["event_count"] == 1


@pytest.mark.parametrize(
    ("defender", "slot", "source_key", "mode", "reason"),
    [
        ("Samira", "W", "w_blocked_skillshots", "destroyed", "samira_blade_whirl"),
        ("Gwen", "W", "w_blocked_skillshots", "destroyed", "gwen_hallowed_mist"),
        (
            "Pantheon",
            "E",
            "e_blocked_skillshots",
            "full_block",
            "pantheon_aegis_assault",
        ),
        ("Fiora", "W", "w_blocked_sources", "full_block", "fiora_riposte"),
    ],
)
def test_additional_defensive_windows_use_selected_sources_and_expire(
    defender: str, slot: str, source_key: str, mode: str, reason: str
):
    option = {
        "w_active": True,
        "w_active_seconds": 0.75,
        source_key: ["Q"],
    }
    if slot == "E":
        option = {
            "e_active": True,
            "e_active_seconds": 1.0,
            source_key: ["Q"],
        }
    combat = _calculate(
        {
            "champion": "Ezreal",
            "level": 18,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 4,
            "include_auto_attacks": False,
            "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
            "enemies": [
                {
                    "champion": defender,
                    "level": 18,
                    "items": [],
                    "champion_options": option,
                }
            ],
        }
    )
    q_events = _events(combat, attacker="main", target=f"enemy:{defender}", source="Q")
    assert len(q_events) >= 2
    first = q_events[0]
    later = next(
        event
        for event in q_events
        if event["time"]
        >= option.get("w_active_seconds", option.get("e_active_seconds", 0.0))
    )
    assert first["damage"] == pytest.approx(0.0)
    assert first["projectile_defense"]["mode"] == mode
    if mode == "destroyed":
        assert first["skipped_reason"] == reason
    assert later["damage"] > 0.0

    survival = _survival(combat, f"enemy:{defender}")
    until = option.get("w_active_seconds", option.get("e_active_seconds", 0.0))
    assert survival["projectile_defense"]["until"] == pytest.approx(until)
    assert survival["projectile_defense_blocked"] == [
        {"time": first["time"], "source": "Q", "mode": mode}
    ]


def test_yasuo_q3_carries_knockup_duration_into_target_downtime():
    combat = _calculate(
        {
            "champion": "Yasuo",
            "level": 18,
            "items": [],
            "fight_mode": "one_rotation",
            "include_auto_attacks": False,
            "ability_ranks": {"Q": 5, "W": 0, "E": 0, "R": 0},
            "champion_options": {"q_gathering_storm": 2},
            "enemies": [{"champion": "Aatrox", "level": 18, "items": []}],
        }
    )

    q_event = _events(combat, attacker="main", target="enemy:Aatrox", source="Q")[0]
    assert q_event["cc_kind"] == "knockup"
    assert q_event["cc_duration"] == pytest.approx(0.9)
    assert q_event["crowd_control"] == {
        "kind": "knockup",
        "duration": pytest.approx(0.9),
        "until": pytest.approx(0.9),
    }
    assert _survival(combat, "enemy:Aatrox")["action_downtime"] == pytest.approx(0.9)


def test_jax_e_blocks_basic_attacks_only_during_the_sourced_window():
    combat = _calculate(
        {
            "champion": "Ezreal",
            "level": 18,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 3.0,
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
            "ability_ranks": {"Q": 0, "W": 0, "E": 0, "R": 0},
            "enemies": [
                {
                    "champion": "Jax",
                    "level": 18,
                    "items": [],
                    "ability_ranks": {"Q": 0, "W": 0, "E": 5, "R": 0},
                    "champion_options": {
                        "e_active": True,
                        "e_active_seconds": 1.0,
                    },
                }
            ],
        }
    )

    autos = [
        event
        for event in combat["events"]
        if event.get("attacker") == "main"
        and event.get("target") == "enemy:Jax"
        and event.get("source") == "auto_attacks"
    ]
    assert len(autos) >= 2
    first = autos[0]
    later = next(event for event in autos if event["time"] >= 1.0)
    assert first["damage"] == pytest.approx(0.0)
    assert first["projectile_defense"]["mode"] == "full_block"
    assert later["damage"] > 0.0
    assert "projectile_defense" not in later

    survival = _survival(combat, "enemy:Jax")
    assert survival["projectile_defense"]["until"] == pytest.approx(1.0)
    assert survival["projectile_defense"]["blocks_basic_attacks"] is True
    assert survival["projectile_defense"]["source_atoms"][0]["source"] == (
        "Jax.E[0].effects[0].description"
    )


def test_jax_e_reduces_marked_area_ability_damage_during_the_sourced_window():
    combat = _calculate(
        {
            "champion": "Brand",
            "level": 18,
            "items": [],
            "fight_mode": "one_rotation",
            "include_auto_attacks": False,
            "ability_ranks": {"Q": 0, "W": 5, "E": 0, "R": 0},
            "enemies": [
                {
                    "champion": "Jax",
                    "level": 18,
                    "items": [],
                    "ability_ranks": {"Q": 0, "W": 0, "E": 5, "R": 0},
                    "champion_options": {
                        "e_active": True,
                        "e_active_seconds": 1.0,
                    },
                }
            ],
        }
    )

    w_event = _events(combat, attacker="main", target="enemy:Jax", source="W")[0]
    assert w_event["area_damage"] is True
    assert w_event["projectile_defense"]["mode"] == "reduced"
    assert w_event["projectile_defense"]["reduction"] == pytest.approx(0.25)


def test_control_only_ability_is_an_ordered_survival_action():
    combat = _calculate(
        {
            "champion": "Veigar",
            "level": 18,
            "items": [],
            "fight_mode": "one_rotation",
            "include_auto_attacks": False,
            "ability_ranks": {"Q": 0, "W": 0, "E": 5, "R": 0},
            "enemies": [{"champion": "Aatrox", "level": 18, "items": []}],
        }
    )

    controls = _events(
        combat,
        attacker="main",
        target="enemy:Aatrox",
        source="E",
    )
    assert len(controls) == 1
    assert controls[0]["damage"] == pytest.approx(0.0)
    assert controls[0]["cc_kind"] == "stun"
    assert controls[0]["cc_duration"] == pytest.approx(2.5)
    assert controls[0]["crowd_control"]["until"] == pytest.approx(
        controls[0]["time"] + 2.5
    )
    assert _survival(combat, "enemy:Aatrox")["action_downtime"] == pytest.approx(2.5)


def test_morgana_q_root_uses_the_sourced_rank_duration():
    combat = _calculate(
        {
            "champion": "Morgana",
            "level": 18,
            "items": [],
            "fight_mode": "one_rotation",
            "include_auto_attacks": False,
            "ability_ranks": {"Q": 5, "W": 0, "E": 0, "R": 0},
            "enemies": [{"champion": "Aatrox", "level": 18, "items": []}],
        }
    )

    q_event = _events(combat, attacker="main", target="enemy:Aatrox", source="Q")[0]
    assert q_event["cc_kind"] == "root"
    assert q_event["cc_duration"] == pytest.approx(3.0)
    assert _survival(combat, "enemy:Aatrox")["action_downtime"] == pytest.approx(3.0)


def test_morgana_r_stun_is_attached_to_the_tether_break_hit():
    combat = _calculate(
        {
            "champion": "Morgana",
            "level": 18,
            "items": [],
            "fight_mode": "one_rotation",
            "include_auto_attacks": False,
            "ability_ranks": {"Q": 0, "W": 0, "E": 0, "R": 3},
            "enemies": [{"champion": "Aatrox", "level": 18, "items": []}],
        }
    )

    r_events = _events(combat, attacker="main", target="enemy:Aatrox", source="R")
    assert len(r_events) == 2
    assert r_events[0].get("cc_duration") in (None, 0.0)
    assert r_events[1]["time"] == pytest.approx(3.0)
    assert r_events[1]["cc_kind"] == "stun"
    assert r_events[1]["cc_duration"] == pytest.approx(2.0)


def test_nautilus_r_knockup_uses_the_primary_target_duration():
    combat = _calculate(
        {
            "champion": "Nautilus",
            "level": 18,
            "items": [],
            "fight_mode": "one_rotation",
            "include_auto_attacks": False,
            "ability_ranks": {"Q": 0, "W": 0, "E": 0, "R": 3},
            "enemies": [{"champion": "Aatrox", "level": 18, "items": []}],
        }
    )

    r_event = _events(combat, attacker="main", target="enemy:Aatrox", source="R")[0]
    assert r_event["cc_kind"] == "knockup"
    assert r_event["cc_duration"] == pytest.approx(2.0)
    assert _survival(combat, "enemy:Aatrox")["action_downtime"] == pytest.approx(2.0)


@pytest.mark.parametrize(
    ("champion", "slot", "kind", "duration"),
    [
        ("Braum", "R", "knockup", 2.0),
        ("Amumu", "Q", "stun", 1.0),
        ("Amumu", "R", "stun", 1.5),
        ("Elise", "E", "stun", 2.4),
        ("Jax", "E", "stun", 1.0),
        ("Rammus", "E", "taunt", 2.0),
        ("Poppy", "E", "stun", 2.0),
        ("Taric", "E", "stun", 1.5),
        ("Tristana", "R", "knockback", 0.7),
        ("Rakan", "R", "charm", 1.5),
        ("Lulu", "W", "polymorph", 2.0),
        ("Varus", "R", "root", 2.0),
        ("Vayne", "E", "stun", 1.5),
        ("Bel'Veth", "W", "knockup", 1.0),
        ("Singed", "E", "root", 2.0),
        ("Twisted Fate", "W", "stun", 2.0),
    ],
)
def test_structured_control_atoms_create_action_downtime(
    champion: str, slot: str, kind: str, duration: float
):
    ranks = {"Q": 0, "W": 0, "E": 0, "R": 0}
    ranks[slot] = 3 if slot == "R" else 5
    payload = {
        "champion": champion,
        "level": 18,
        "items": [],
        "fight_mode": "one_rotation",
        "include_auto_attacks": False,
        "enemies": [{"champion": "Aatrox", "level": 18, "items": []}],
    }
    if champion not in {"Elise"}:
        payload["ability_ranks"] = ranks
    combat = _calculate(payload)

    controls = [
        event
        for event in _events(
            combat, attacker="main", target="enemy:Aatrox", source=slot
        )
        if event.get("cc_kind") == kind
    ]
    assert len(controls) == 1
    assert controls[0]["cc_duration"] == pytest.approx(duration)
    assert controls[0]["control_source_atoms"]
    assert controls[0]["control_source_atoms"][0]["behavior"] in {
        "ability",
        "timing",
    }
    assert controls[0]["control_source_atoms"][0]["units"]
    assert all(
        str(unit).strip().lower() in {"seconds", "s"}
        for unit in controls[0]["control_source_atoms"][0]["units"]
    )
    assert _survival(combat, "enemy:Aatrox")["action_downtime"] == pytest.approx(
        duration
    )


@pytest.mark.parametrize(
    ("champion", "slot", "kind", "duration"),
    [
        ("Cho'Gath", "W", "silence", 2.0),
        ("Malzahar", "Q", "silence", 2.0),
    ],
)
def test_silence_atoms_are_reported_without_full_action_downtime(
    champion: str, slot: str, kind: str, duration: float
):
    ranks = {"Q": 0, "W": 0, "E": 0, "R": 0}
    ranks[slot] = 5
    combat = _calculate(
        {
            "champion": champion,
            "level": 18,
            "items": [],
            "fight_mode": "one_rotation",
            "include_auto_attacks": False,
            "ability_ranks": ranks,
            "enemies": [{"champion": "Aatrox", "level": 18, "items": []}],
        }
    )
    event = next(
        event
        for event in _events(
            combat, attacker="main", target="enemy:Aatrox", source=slot
        )
        if event.get("cc_kind") == kind
    )
    assert event["cc_duration"] == pytest.approx(duration)
    assert _survival(combat, "enemy:Aatrox")["action_downtime"] == pytest.approx(0.0)


def test_zilean_q_second_bomb_emits_sourced_stun():
    combat = _calculate(
        {
            "champion": "Zilean",
            "level": 18,
            "items": [],
            "fight_mode": "one_rotation",
            "include_auto_attacks": False,
            "ability_ranks": {"Q": 5, "W": 0, "E": 0, "R": 0},
            "champion_options": {"q_second_bomb": True},
            "enemies": [{"champion": "Aatrox", "level": 18, "items": []}],
        }
    )
    event = next(
        event
        for event in _events(combat, attacker="main", target="enemy:Aatrox", source="Q")
        if event.get("cc_kind") == "stun"
    )
    assert event["time"] == pytest.approx(0.0)
    assert event["cc_duration"] == pytest.approx(1.5)
    assert _survival(combat, "enemy:Aatrox")["action_downtime"] == pytest.approx(1.5)


def test_delayed_control_atoms_keep_their_authored_hit_time():
    karma = _calculate(
        {
            "champion": "Karma",
            "level": 18,
            "items": [],
            "fight_mode": "one_rotation",
            "include_auto_attacks": False,
            "champion_options": {"w_tether_holds": True},
            "enemies": [{"champion": "Aatrox", "level": 18, "items": []}],
        }
    )
    root = next(
        event
        for event in _events(karma, attacker="main", target="enemy:Aatrox", source="W")
        if event.get("cc_kind") == "root"
    )
    assert root["time"] == pytest.approx(2.0)
    assert root["cc_duration"] == pytest.approx(2.0)
    assert _survival(karma, "enemy:Aatrox")["action_downtime"] == pytest.approx(2.0)


def test_evelynn_allure_requires_an_explicit_matured_mark_trigger_for_charm():
    combat = _calculate(
        {
            "champion": "Evelynn",
            "level": 18,
            "items": [],
            "fight_mode": "one_rotation",
            "include_auto_attacks": False,
            "ability_ranks": {"Q": 0, "W": 5, "E": 0, "R": 0},
            "champion_options": {
                "w_charmed": True,
                "w_charm_triggered": True,
            },
            "enemies": [{"champion": "Aatrox", "level": 18, "items": []}],
        }
    )
    charm = next(
        event
        for event in _events(combat, attacker="main", target="enemy:Aatrox", source="W")
        if event.get("cc_kind") == "charm"
    )
    assert charm["time"] == pytest.approx(2.5)
    assert charm["cc_duration"] == pytest.approx(2.25)
    assert _survival(combat, "enemy:Aatrox")["action_downtime"] == pytest.approx(2.25)


def test_soraka_e_root_is_a_delayed_control_only_event():
    combat = _calculate(
        {
            "champion": "Soraka",
            "level": 18,
            "items": [],
            "fight_mode": "one_rotation",
            "include_auto_attacks": False,
            "ability_ranks": {"Q": 0, "W": 0, "E": 5, "R": 0},
            "champion_options": {"e_second_hit": True},
            "enemies": [{"champion": "Aatrox", "level": 18, "items": []}],
        }
    )
    root = next(
        event
        for event in _events(combat, attacker="main", target="enemy:Aatrox", source="E")
        if event.get("cc_kind") == "root"
    )
    assert root["damage"] == pytest.approx(0.0)
    assert root["time"] == pytest.approx(1.5)
    assert root["cc_duration"] == pytest.approx(2.0)
    assert _survival(combat, "enemy:Aatrox")["action_downtime"] == pytest.approx(2.0)


@pytest.mark.parametrize(
    ("champion", "slot", "kind", "duration"),
    [
        ("Anivia", "Q", "stun", 1.5),
        ("Bard", "Q", "stun", 1.8),
        ("Fiddlesticks", "Q", "fear", 2.0),
        ("Ivern", "Q", "root", 2.0),
        ("Jhin", "W", "root", 2.25),
        ("Lissandra", "W", "root", 1.65),
        ("Maokai", "W", "root", 1.4),
        ("Neeko", "E", "root", 1.5),
        ("Senna", "W", "root", 2.25),
        ("Seraphine", "E", "root", 1.5),
        ("Seraphine", "R", "charm", 1.75),
        ("Orianna", "R", "stun", 0.75),
        ("Camille", "E", "stun", 0.75),
        ("Brand", "Q", "stun", 1.75),
        ("Cassiopeia", "R", "stun", 2.0),
        ("Malphite", "R", "airborne", 1.5),
        ("Velkoz", "E", "knockup", 0.75),
        ("Zyra", "E", "root", 2.0),
    ],
)
def test_additional_structured_cc_rows_emit_typed_duration(
    champion: str, slot: str, kind: str, duration: float
):
    data = get_champion(champion)
    stats = calculate_total_stats(data, 18, [])
    parsed = parse_champion_abilities(
        data,
        18,
        stats["ability_power"],
        ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
        champion_stats=stats,
        target_stats={
            "target_max_health": 2000.0,
            "target_current_health": 2000.0,
        },
    )
    part = next(part for part in parsed[slot]["parts"] if part.cc_duration > 0.0)
    assert part.cc_kind == kind
    assert part.cc_duration == pytest.approx(duration)


@pytest.mark.parametrize(
    ("variant", "kind", "duration"),
    [(0, "fear", 1.5), (1, "root", 2.0)],
)
def test_hwei_torment_variants_emit_their_selected_control(
    variant: int, kind: str, duration: float
):
    data = get_champion("Hwei")
    stats = calculate_total_stats(data, 18, [])
    parsed = parse_champion_abilities(
        data,
        18,
        stats["ability_power"],
        ability_ranks={"Q": 0, "W": 0, "E": 5, "R": 0},
        champion_options={"e_variant": variant},
        champion_stats=stats,
        target_stats={
            "target_max_health": 2000.0,
            "target_current_health": 2000.0,
        },
    )
    part = next(part for part in parsed["E"]["parts"] if part.cc_duration > 0.0)
    assert part.cc_kind == kind
    assert part.cc_duration == pytest.approx(duration)


@pytest.mark.parametrize(
    ("champion", "slot", "kind", "duration", "options"),
    [
        ("Gnar", "R", "stun", 1.75, {"mega": True, "r_wall": True}),
        ("Nocturne", "E", "fear", 2.25, {"e_tether_holds": True}),
        ("Shaco", "W", "fear", 1.5, {}),
        ("Darius", "E", "airborne", 1.0, {}),
        ("Cassiopeia", "R", "stun", 2.0, {}),
        ("Xayah", "E", "root", 1.25, {"bladecaller_feathers": 3}),
    ],
)
def test_stateful_control_atoms_create_timed_downtime(
    champion: str,
    slot: str,
    kind: str,
    duration: float,
    options: dict,
):
    ranks = {"Q": 0, "W": 0, "E": 0, "R": 0}
    ranks[slot] = 3 if slot == "R" else 5
    combat = _calculate(
        {
            "champion": champion,
            "level": 18,
            "items": [],
            "fight_mode": "one_rotation",
            "include_auto_attacks": False,
            "ability_ranks": ranks,
            "champion_options": options,
            "enemies": [{"champion": "Aatrox", "level": 18, "items": []}],
        }
    )
    control = next(
        event
        for event in _events(
            combat, attacker="main", target="enemy:Aatrox", source=slot
        )
        if event.get("cc_kind") == kind
    )
    assert control["cc_duration"] == pytest.approx(duration)
    if champion == "Nocturne":
        assert control["time"] == pytest.approx(2.0)
    assert _survival(combat, "enemy:Aatrox")["action_downtime"] == pytest.approx(
        duration
    )
