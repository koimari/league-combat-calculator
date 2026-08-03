"""Regression coverage for coupled participant combat receipts."""

from types import SimpleNamespace

from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.pipeline import FightParams, run_fight
from src.app import _role_scoped_bis_candidates, app
from src.calculator.item_coverage import optimizer_supported_items
from src.calculator.optimizer import get_eligible_legendaries
from src.calculator.participant_timeline import Combatant, _simulate_survival


def _timed_params() -> FightParams:
    return FightParams.from_request(
        {
            "fight_mode": "time_based",
            "fight_duration": 10,
            "include_auto_attacks": True,
            "auto_attack_uptime": 0.3,
            "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
        }
    )


def test_aatrox_self_healing_is_post_mitigation_and_ordered():
    result = run_fight(get_champion("Aatrox"), 18, [], _timed_params())

    assert result["self_healing"] > 0
    assert result["self_healing_events"]
    assert any(
        event["source"] == "Deathbringer Stance"
        for event in result["self_healing_events"]
    )
    assert all(
        event["time"] >= 0 and event["amount"] > 0
        for event in result["self_healing_events"]
    )


def test_ambessa_self_healing_uses_public_execution_formula():
    result = run_fight(get_champion("Ambessa"), 18, [], _timed_params())

    assert result["self_healing"] > 0
    assert all(
        event["source"] == "Public Execution" for event in result["self_healing_events"]
    )


def test_warwick_and_irelia_use_explicit_wiki_heal_attributes():
    for champion, source in (
        ("Warwick", "Jaws of the Beast"),
        ("Irelia", "Bladesurge"),
    ):
        result = run_fight(get_champion(champion), 18, [], _timed_params())
        assert result["self_healing"] > 0
        assert any(event["source"] == source for event in result["self_healing_events"])


def test_mundo_regeneration_is_actor_wide_and_deduplicated_in_a_roster():
    app.config["TESTING"] = True
    response = app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Dr. Mundo",
            "level": 18,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 5,
            "include_auto_attacks": False,
            "enemies": [
                {"champion": "Aphelios", "level": 18, "items": []},
                {"champion": "Ambessa", "level": 18, "items": []},
            ],
        },
    )
    assert response.status_code == 200
    healing = [
        event
        for event in response.get_json()["combat"]["healing_events"]
        if event["source"] == "Maximum Dosage"
    ]
    # R is cast at 0.25s; the sourced 0.5s cadence yields nine ticks in a
    # five-second window, regardless of the number of enemy pairs.
    assert len(healing) == 9
    assert [event["time"] for event in healing] == [
        round(0.75 + index * 0.5, 3) for index in range(9)
    ]


def test_fight_result_promotes_the_same_ordered_damage_ledger_used_by_shields():
    result = run_fight(get_champion("Aatrox"), 18, [], _timed_params())

    assert result["damage_events"]
    assert all(
        {"source_key", "damage_type", "damage", "time"}.issubset(event)
        for event in result["damage_events"]
    )


def test_api_includes_enemy_output_and_main_effective_health():
    app.config["TESTING"] = True
    response = app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Aatrox",
            "level": 18,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 10,
            "include_auto_attacks": True,
            "auto_attack_uptime": 0.3,
            "enemies": [{"champion": "Ambessa", "level": 18, "items": []}],
        },
    )
    assert response.status_code == 200
    combat = response.get_json()["combat"]
    assert {row["champion"] for row in combat["breakdown"]} == {"Aatrox", "Ambessa"}
    assert all(
        {"incoming_damage", "effective_health", "survived_window"}.issubset(row)
        for row in combat["breakdown"]
    )
    main = next(
        row for row in combat["participants"] if row["participant_id"] == "main"
    )
    assert main["survival"]["effective_health"] >= main["survival"]["max_health"]


def test_api_includes_sourced_lulu_ally_shield_in_main_ehp():
    app.config["TESTING"] = True
    response = app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Aatrox",
            "level": 18,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 10,
            "include_auto_attacks": True,
            "auto_attack_uptime": 0.3,
            "enemies": [{"champion": "Ambessa", "level": 18, "items": []}],
            "allies": [
                {"champion": "Lulu", "level": 18, "items": [], "role": "support"}
            ],
        },
    )
    assert response.status_code == 200
    combat = response.get_json()["combat"]
    assert any(
        event["source"].startswith("Help, Pix!") for event in combat["support_events"]
    )
    main = next(
        row for row in combat["participants"] if row["participant_id"] == "main"
    )
    assert main["survival"]["support_shield_received"] > 0
    assert combat["objective"]["main_team_effective_health"] > 0


def test_main_support_targets_selected_ally_and_uses_requested_rank():
    app.config["TESTING"] = True
    response = app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Lulu",
            "level": 18,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 10,
            "include_auto_attacks": False,
            "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
            "allies": [
                {
                    "champion": "Jinx",
                    "level": 18,
                    "items": [],
                    "ally_effects_enabled": True,
                }
            ],
            "enemies": [{"champion": "Ambessa", "level": 18, "items": []}],
        },
    )
    assert response.status_code == 200
    combat = response.get_json()["combat"]
    shield = next(
        event
        for event in combat["support_events"]
        if event["attacker"] == "main" and event["source"].startswith("Help, Pix!")
    )
    assert shield["target"] == "ally:Jinx"
    assert shield["target_policy"] == "first_selected_teammate"
    assert shield["amount"] == 230.0
    assert shield["applied_amount"] == 230.0
    jinx = next(
        row for row in combat["participants"] if row["participant_id"] == "ally:Jinx"
    )
    assert jinx["survival"]["support_shield_received"] == 230.0


def test_enemy_self_shield_is_present_in_the_coupled_timeline():
    app.config["TESTING"] = True
    response = app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Aatrox",
            "level": 18,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 10,
            "include_auto_attacks": False,
            "enemies": [
                {
                    "champion": "Orianna",
                    "level": 6,
                    "items": [],
                    "ability_ranks": {"Q": 3, "W": 1, "E": 1, "R": 1},
                }
            ],
        },
    )
    assert response.status_code == 200
    combat = response.get_json()["combat"]
    shield = next(
        event
        for event in combat["support_events"]
        if event["attacker"] == "enemy:Orianna"
        and event["source"].startswith("Command: Protect")
    )
    assert shield["target"] == "enemy:Orianna"
    assert shield["target_policy"] == "self"
    assert shield["amount"] == 55.0


def test_coupled_timeline_stops_output_after_main_champion_is_defeated():
    app.config["TESTING"] = True
    response = app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Aatrox",
            "level": 1,
            "items": [],
            "fight_mode": "one_rotation",
            "enemies": [{"champion": "Ambessa", "level": 18, "items": []}],
        },
    )
    assert response.status_code == 200
    combat = response.get_json()["combat"]
    main = next(
        row for row in combat["participants"] if row["participant_id"] == "main"
    )
    assert main["survival"]["survived_window"] is False
    assert main["survival"]["death_time"] is not None
    # The enemy's later event stream is not counted as if Aatrox remained
    # alive for the whole rotation.
    assert (
        next(row for row in combat["breakdown"] if row["participant_id"] == "main")[
            "total_damage"
        ]
        <= 138.5
    )


def test_coupled_timeline_reprices_current_health_damage_for_each_attacker():
    """A second Mundo Q must see the damage already dealt by the first one."""
    app.config["TESTING"] = True
    response = app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Dr. Mundo",
            "level": 6,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 3.5,
            "include_auto_attacks": False,
            "ability_ranks": {"Q": 3, "W": 1, "E": 1, "R": 1},
            "enemies": [{"champion": "Aphelios", "level": 6, "items": []}],
            "allies": [
                {
                    "champion": "Dr. Mundo",
                    "level": 6,
                    "items": [],
                    "ally_effects_enabled": False,
                    "ability_ranks": {"Q": 3, "W": 1, "E": 1, "R": 1},
                }
            ],
        },
    )
    assert response.status_code == 200
    events = [
        event
        for event in response.get_json()["combat"]["events"]
        if event["target"] == "enemy:Aphelios" and event["source"] == "Q"
    ]
    main_q = next(event for event in events if event["attacker"] == "main")
    ally_q = next(event for event in events if event["attacker"] == "ally:Dr. Mundo")
    assert main_q["damage"] > ally_q["damage"]
    assert main_q["pair_damage"] == ally_q["pair_damage"]
    assert ally_q["damage"] < ally_q["pair_damage"]


def test_coupled_timeline_caps_overkill_and_skips_post_death_events():
    app.config["TESTING"] = True
    response = app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Ziggs",
            "level": 18,
            "items": [
                "Luden's Echo",
                "Rabadon's Deathcap",
                "Shadowflame",
                "Void Staff",
                "Stormsurge",
            ],
            "fight_mode": "time_based",
            "fight_duration": 10,
            "include_auto_attacks": False,
            "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
            "enemies": [{"champion": "Aphelios", "level": 1, "items": []}],
        },
    )
    assert response.status_code == 200
    combat = response.get_json()["combat"]
    enemy = next(row for row in combat["participants"] if row["team"] == "enemy")
    main_row = next(
        row for row in combat["breakdown"] if row["participant_id"] == "main"
    )
    assert enemy["survival"]["survived_window"] is False
    assert enemy["survival"]["overkill"] > 0
    assert main_row["total_damage"] <= enemy["survival"]["max_health"]
    assert any(
        event.get("skipped_reason") == "target_dead" for event in combat["events"]
    )


def _bis_request(subject_team: str) -> dict:
    return {
        "champion": "Aatrox",
        "level": 18,
        "items": ["Infinity Edge", "Bloodthirster"],
        "boots": "Plated Steelcaps",
        "role": "top",
        "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
        "fight_mode": "time_based",
        "fight_duration": 10,
        "include_auto_attacks": True,
        "auto_attack_uptime": 0.3,
        "subject_team": subject_team,
        "subject_index": 0,
        "slot_index": 0,
        "slot_kind": "item",
        "enemies": [
            {
                "champion": "Ambessa",
                "level": 18,
                "items": [],
                "role": "top",
                "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
            }
        ],
        "allies": [
            {
                "champion": "Lulu",
                "level": 18,
                "items": [],
                "role": "support",
                "ally_effects_enabled": True,
                "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
            }
        ],
    }


def test_bis_endpoint_scores_main_from_damage_and_effective_health():
    app.config["TESTING"] = True
    response = app.test_client().post("/api/bis", json=_bis_request("main"))
    assert response.status_code == 200
    body = response.get_json()
    assert body["candidate_count"] > 0
    assert body["candidates"]
    top = body["candidates"][0]
    assert top["metric"] == "main TTD (survival-coupled)"
    assert top["components"]["effective_health"] > 0


def test_bis_endpoint_keeps_ally_and_enemy_in_the_same_timeline():
    app.config["TESTING"] = True
    client = app.test_client()
    ally = client.post("/api/bis", json=_bis_request("ally"))
    enemy = client.post("/api/bis", json=_bis_request("enemy"))
    assert ally.status_code == enemy.status_code == 200
    ally_top = ally.get_json()["candidates"][0]
    enemy_top = enemy.get_json()["candidates"][0]
    assert "main_team_damage_before_death" in ally_top["components"]
    assert "effective_health" in ally_top["components"]
    assert enemy_top["metric"] == "enemy survival first · threat before defeat"
    assert enemy_top["components"]["effective_health"] > 0


def test_enemy_bis_prioritizes_event_survival_before_outgoing_threat(monkeypatch):
    """A high-damage enemy that dies early cannot beat a surviving build."""

    def fake_timeline(*_args, **kwargs):
        enemy = kwargs["enemies"][0]
        item_names = {item["name"] for item in enemy.item_data}
        glass_cannon = "Luden's Echo" in item_names
        survival = {
            "max_health": 1_000.0 if glass_cannon else 2_000.0,
            "effective_health": 1_000.0 if glass_cannon else 2_000.0,
            "healing_received": 0.0,
            "shield_absorbed": 0.0,
            "death_time": 2.0 if glass_cannon else None,
            "survived_window": not glass_cannon,
        }
        focus_id = kwargs["focus_participant_id"]
        return {
            "duration": 10.0,
            "participants": [
                {"participant_id": focus_id, "survival": survival},
            ],
            "breakdown": [
                {
                    "participant_id": focus_id,
                    "team": "enemy",
                    "total_damage": 5_000.0 if glass_cannon else 500.0,
                }
            ],
            "objective": {
                "focus_damage_before_death": 5_000.0 if glass_cannon else 500.0,
                "focus_support_value": 0.0,
                "focus_healing": 0.0,
                "main_team_damage_before_death": 0.0,
            },
            "timeline_coverage": {
                "complete": True,
                "exact_sources": [],
                "coarse_sources": [],
            },
        }

    monkeypatch.setattr("src.app.build_participant_timeline", fake_timeline)
    response = app.test_client().post("/api/bis", json=_bis_request("enemy"))

    assert response.status_code == 200
    body = response.get_json()
    assert body["candidates"]
    top = body["candidates"][0]
    assert top["name"] != "Luden's Echo"
    assert top["metric"] == "enemy survival first · threat before defeat"
    assert top["components"]["survival_time"] == 10.0
    assert top["components"]["effective_health"] == 2_000.0


def test_roster_bis_requires_an_explicit_role_instead_of_guessing_item_class():
    app.config["TESTING"] = True
    payload = _bis_request("enemy")
    payload["enemies"][0].pop("role")
    response = app.test_client().post("/api/bis", json=payload)
    assert response.status_code == 400
    assert (
        response.get_json()["error"]
        == "enemy role is required before roster BIS can be scored"
    )


def test_roster_bis_uses_sourced_role_shop_scope_before_scoring_candidates():
    candidates = optimizer_supported_items(get_eligible_legendaries())
    support = {
        item["name"] for item in _role_scoped_bis_candidates(candidates, role="support")
    }
    top = {item["name"] for item in _role_scoped_bis_candidates(candidates, role="top")}

    assert "Locket of the Iron Solari" in support
    assert "Moonstone Renewer" in support
    assert "Warmog's Armor" not in support
    assert "Warmog's Armor" in top
    assert "Locket of the Iron Solari" not in top


def test_roster_bis_filters_items_with_unsupported_target_mechanics():
    """A roster BIS result must remain safe when reused as a passive target."""
    app.config["TESTING"] = True
    response = app.test_client().post("/api/bis", json=_bis_request("enemy"))
    assert response.status_code == 200
    body = response.get_json()
    names = {
        candidate["name"]
        for candidate in [*body["candidates"], *body["partial_candidates"]]
    }

    assert "Zhonya's Hourglass" not in names
    assert body["target_coverage_filtered"] > 0
    assert "target-side coverage filtered" in body["target_coverage_note"].lower()


def test_roster_bis_reports_actionable_target_coverage_for_blocked_mid_loadout():
    """A blocked enemy card must explain why no replacement build was applied."""
    app.config["TESTING"] = True
    payload = _bis_request("enemy")
    payload["enemies"][0]["role"] = "mid"
    payload["enemies"][0]["role_quest_complete"] = True
    payload["enemies"][0]["items"] = [
        "Heartsteel",
        "Banshee's Veil",
    ]
    payload["enemies"][0]["boots"] = "Armored Advance"

    response = app.test_client().post("/api/bis", json=payload)

    assert response.status_code == 200
    body = response.get_json()
    assert body["candidates"] == []
    assert body["coverage"]["complete"] is False
    assert body["target_coverage_filtered"] > 0
    assert "target-side coverage filtered" in body["coverage"]["note"].lower()
    assert any(
        name in body["target_coverage_note"]
        for name in ("Heartsteel", "Banshee's Veil", "Armored Advance")
    )


def test_bis_withholds_partial_event_order_instead_of_labeling_it_certified():
    app.config["TESTING"] = True
    payload = {
        "champion": "Dr. Mundo",
        "level": 6,
        "items": [],
        "fight_mode": "time_based",
        "fight_duration": 3.5,
        "include_auto_attacks": True,
        "auto_attack_uptime": 1.0,
        "ability_ranks": {"Q": 3, "W": 1, "E": 1, "R": 1},
        "subject_team": "main",
        "subject_index": 0,
        "slot_index": 0,
        "slot_kind": "item",
        "enemies": [{"champion": "Aphelios", "level": 6, "items": []}],
    }
    response = app.test_client().post("/api/bis", json=payload)
    assert response.status_code == 200
    body = response.get_json()
    assert body["certified_candidate_count"] == 0
    assert body["candidates"] == []
    assert body["partial_candidates"]
    assert body["coverage"]["certification"] == "bis_withheld_partial_event_order"


def test_explicitly_disabled_ally_effects_are_not_injected_into_ehp():
    app.config["TESTING"] = True
    payload = _bis_request("main")
    payload["allies"][0]["ally_effects_enabled"] = False
    response = app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200
    assert not any(
        event["attacker"] == "ally:Lulu"
        for event in response.get_json()["combat"]["support_events"]
    )


def _dummy_combatant(
    participant_id: str, team: str, health: float = 100.0
) -> Combatant:
    defenses = SimpleNamespace(
        magic_shield=0.0,
        physical_shield=0.0,
        general_shield=0.0,
    )
    return Combatant(
        participant_id=participant_id,
        team=team,
        champion_data={"name": participant_id},
        level=1,
        items=(),
        stats={"health": health},
        defenses=defenses,
    )


def test_simulator_orders_same_timestamp_events_without_comparing_payloads():
    target = _dummy_combatant("target", "enemy")
    source = _dummy_combatant("source", "main")
    result = _simulate_survival(
        [source, target],
        {
            "target": [
                {
                    "time": 0.0,
                    "damage": 40.0,
                    "damage_type": "physical",
                    "attacker": "source",
                    "sequence": 0,
                    "_event_id": "first",
                },
                {
                    "time": 0.0,
                    "damage": 40.0,
                    "damage_type": "physical",
                    "attacker": "source",
                    "sequence": 1,
                    "_event_id": "second",
                },
            ]
        },
        {},
        {},
        10.0,
    )
    assert result["target"]["damage_taken"] == 80.0


def test_simulator_scores_only_applied_support_and_healing_amounts():
    source = _dummy_combatant("source", "main")
    target = _dummy_combatant("target", "ally")
    dead_target = _dummy_combatant("dead", "ally", health=50.0)
    result = _simulate_survival(
        [source, target, dead_target],
        {
            "dead": [
                {
                    "time": 0.0,
                    "damage": 50.0,
                    "damage_type": "physical",
                    "attacker": "source",
                    "sequence": 0,
                    "_event_id": "kill",
                }
            ]
        },
        {
            "target": [
                {
                    "time": 0.0,
                    "amount": 50.0,
                    "attacker": "source",
                    "source": "already-full heal",
                }
            ]
        },
        {
            "dead": [
                {
                    "time": 1.0,
                    "amount": 50.0,
                    "kind": "shield",
                    "attacker": "source",
                    "source": "late shield",
                }
            ]
        },
        10.0,
    )
    assert result["target"]["healing_received"] == 0.0
    assert result["dead"]["support_shield_received"] == 0.0


def test_simulator_applies_sourced_grievous_wounds_to_healing_in_event_order():
    source = _dummy_combatant(
        "source",
        "main",
        health=100.0,
    )
    source = Combatant(
        participant_id=source.participant_id,
        team=source.team,
        champion_data=source.champion_data,
        level=source.level,
        items=(get_item_by_name("Morellonomicon"),),
        stats=source.stats,
        defenses=source.defenses,
    )
    target = _dummy_combatant("target", "enemy", health=200.0)
    result = _simulate_survival(
        [source, target],
        {
            "target": [
                {
                    "time": 0.0,
                    "damage": 50.0,
                    "damage_type": "magic",
                    "attacker": "source",
                    "sequence": 0,
                    "_event_id": "wound",
                }
            ]
        },
        {
            "target": [
                {
                    "time": 1.0,
                    "amount": 100.0,
                    "attacker": "target",
                    "source": "target heal",
                },
                {
                    "time": 4.0,
                    "amount": 100.0,
                    "attacker": "target",
                    "source": "post wound heal",
                },
            ]
        },
        {},
        10.0,
    )

    # The first heal is reduced to 60, but only 50 can fit in the missing
    # health; the post-window heal is correctly capped at full health.
    assert result["target"]["healing_received"] == 50.0
    assert result["target"]["healing_reduced"] == 40.0
    assert result["target"]["healing_reduction_until"] == 3.0
