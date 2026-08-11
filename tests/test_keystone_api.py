"""Route-level contracts for keystone rune selection."""

import pytest

import src.app as app_module


@pytest.fixture(autouse=True)
def _disable_rate_limits():
    previous = app_module.app.config.get("RATE_LIMIT_ENABLED", True)
    app_module.app.config["RATE_LIMIT_ENABLED"] = False
    yield
    app_module.app.config["RATE_LIMIT_ENABLED"] = previous


def _payload(**overrides):
    payload = {
        "champion": "Ahri",
        "level": 9,
        "items": [],
        "fight_mode": "one_rotation",
    }
    payload.update(overrides)
    return payload


def test_config_serves_keystone_roster_with_coverage():
    config = app_module.app.test_client().get("/api/config").get_json()

    keystones = config["keystones"]
    assert len(keystones) == 17
    by_name = {entry["name"]: entry for entry in keystones}
    assert by_name["Electrocute"]["implemented"] is True
    assert by_name["Electrocute"]["path"] == "Domination"
    assert by_name["First Strike"]["implemented"] is True
    assert by_name["Press the Attack"]["implemented"] is True
    assert by_name["Arcane Comet"]["implemented"] is True
    assert by_name["Guardian"]["implemented"] is True
    assert by_name["Aftershock"]["implemented"] is True
    assert by_name["Grasp of the Undying"]["implemented"] is True
    assert by_name["Hail of Blades"]["implemented"] is True
    assert by_name["Lethal Tempo"]["implemented"] is True
    assert by_name["Dark Harvest"]["implemented"] is True
    assert by_name["Glacial Augment"]["implemented"] is True
    assert by_name["Stormraider's Surge"]["implemented"] is True
    assert by_name["Fleet Footwork"]["implemented"] is True
    assert by_name["Conqueror"]["implemented"] is True
    assert by_name["Deathfire Touch"]["implemented"] is True
    assert (
        config["keystone_options"]["Fleet Footwork"]["options"]["starting_charges"][
            "max"
        ]
        == 100
    )
    assert (
        config["keystone_options"]["Conqueror"]["options"]["starting_stacks"]["max"]
        == 12
    )
    assert all(entry["icon"] for entry in keystones)
    # Paths arrive grouped in wiki order for direct picker rendering.
    paths = [entry["path"] for entry in keystones]
    assert paths.index("Precision") < paths.index("Domination") < paths.index("Sorcery")


def test_calculate_includes_electrocute_breakdown_row():
    client = app_module.app.test_client()
    with_keystone = client.post("/api/calculate", json=_payload(keystone="Electrocute"))
    without_keystone = client.post("/api/calculate", json=_payload())

    assert with_keystone.status_code == 200
    result = with_keystone.get_json()
    row = result["breakdown"].get("keystone_Electrocute")
    assert row is not None
    assert row["name"] == "Electrocute (keystone)"
    assert row["total_damage"] > 0
    assert result["total_damage"] == pytest.approx(
        without_keystone.get_json()["total_damage"] + row["total_damage"],
        rel=1e-6,
    )


def test_calculate_includes_first_strike_breakdown_row():
    client = app_module.app.test_client()
    with_keystone = client.post(
        "/api/calculate", json=_payload(keystone="First Strike")
    )
    without_keystone = client.post("/api/calculate", json=_payload())

    assert with_keystone.status_code == 200
    result = with_keystone.get_json()
    baseline = without_keystone.get_json()
    row = result["breakdown"].get("keystone_First Strike")
    assert row is not None
    assert row["name"] == "First Strike (keystone)"
    assert row["total_damage"] > 0
    assert result["total_damage"] == pytest.approx(
        baseline["total_damage"] + row["total_damage"],
        rel=1e-6,
    )
    # The bonus is true damage: it lands in the typed split, and the
    # gold it generated reaches the user through the fight notes.
    assert result["damage_by_type"]["true"] == pytest.approx(
        baseline["damage_by_type"]["true"] + row["total_damage"],
        rel=1e-3,
    )
    assert any("First Strike" in note and "gold" in note for note in result["notes"])


def test_calculate_includes_press_the_attack_rows():
    # Press the Attack stacks only on basic attacks, so the fight must
    # simulate autos (the ability-only one-rotation default never procs).
    fight = {
        "fight_mode": "time_based",
        "include_auto_attacks": True,
        "fight_duration": 8.0,
        "auto_attack_uptime": 1.0,
    }
    client = app_module.app.test_client()
    with_keystone = client.post(
        "/api/calculate", json=_payload(keystone="Press the Attack", **fight)
    )
    without_keystone = client.post("/api/calculate", json=_payload(**fight))

    assert with_keystone.status_code == 200
    result = with_keystone.get_json()
    baseline = without_keystone.get_json()
    proc_row = result["breakdown"].get("keystone_Press the Attack")
    amp_row = result["breakdown"].get("keystone_Press the Attack amp")
    assert proc_row is not None
    assert proc_row["name"] == "Press the Attack (keystone)"
    assert proc_row["total_damage"] > 0
    assert amp_row is not None
    assert amp_row["name"] == "Press the Attack amp (keystone)"
    assert amp_row["total_damage"] > 0
    assert result["total_damage"] == pytest.approx(
        baseline["total_damage"] + proc_row["total_damage"] + amp_row["total_damage"],
        rel=1e-6,
    )
    # The amp preserves each source's damage type — unlike First Strike,
    # Press the Attack never converts anything to true damage. The
    # tolerance only absorbs the route's 0.1 per-type rounding; the
    # engine-level exclusion test carries the exact assertion.
    assert result["damage_by_type"]["true"] == pytest.approx(
        baseline["damage_by_type"]["true"], abs=0.11
    )


def test_calculate_includes_arcane_comet_breakdown_row():
    client = app_module.app.test_client()
    with_keystone = client.post(
        "/api/calculate", json=_payload(keystone="Arcane Comet")
    )
    without_keystone = client.post("/api/calculate", json=_payload())

    assert with_keystone.status_code == 200
    result = with_keystone.get_json()
    row = result["breakdown"].get("keystone_Arcane Comet")
    assert row is not None
    assert row["name"] == "Arcane Comet (keystone)"
    assert row["total_damage"] > 0
    assert result["total_damage"] == pytest.approx(
        without_keystone.get_json()["total_damage"] + row["total_damage"],
        rel=1e-6,
    )
    # The assumed flight distance reaches the user through the notes.
    assert any("Arcane Comet" in note and "375" in note for note in result["notes"])


def test_calculate_includes_dark_harvest_breakdown_row():
    client = app_module.app.test_client()
    response = client.post(
        "/api/calculate",
        json=_payload(
            keystone="Dark Harvest",
            target_health=1000,
            target_mr=0,
        ),
    )

    assert response.status_code == 200
    result = response.get_json()
    row = result["breakdown"].get("keystone_Dark Harvest")
    assert row is not None
    assert row["name"] == "Dark Harvest (keystone)"
    assert row["total_damage"] == pytest.approx(30.0)
    assert any("Dark Harvest" in note and "50%" in note for note in result["notes"])


def test_calculate_guardian_shields_main_and_selected_ally_once():
    client = app_module.app.test_client()
    response = client.post(
        "/api/calculate",
        json=_payload(
            champion="Lulu",
            level=18,
            keystone="Guardian",
            fight_mode="time_based",
            fight_duration=6.0,
            allies=[
                {
                    "champion": "Jinx",
                    "level": 18,
                    "items": [],
                    "ally_effects_enabled": True,
                },
                {
                    "champion": "Soraka",
                    "level": 18,
                    "items": [],
                    "ally_effects_enabled": True,
                },
            ],
            enemies=[{"champion": "Aatrox", "level": 18, "items": []}],
            support_target_selections={"guardian:target": 1},
        ),
    )

    assert response.status_code == 200
    combat = response.get_json()["combat"]
    applied = [
        event
        for event in combat["support_events"]
        if event["source"] == "Guardian · Shield" and event["applied_amount"] > 0
    ]
    assert {event["target"] for event in applied} == {"main", "ally:Soraka"}
    assert all(event["amount"] == pytest.approx(150.0) for event in applied)
    assert all(event["target_selection_key"] == "guardian:target" for event in applied)
    guard_row = next(
        row for row in combat["participants"] if row["participant_id"] == "main"
    )
    assert len(guard_row["survival"]["guardian"]["trigger_events"]) == 1
    assert guard_row["survival"]["guardian"]["cooldown_until"] > 0.0


def test_calculate_aftershock_authors_resistance_window_and_shockwave():
    client = app_module.app.test_client()
    response = client.post(
        "/api/calculate",
        json=_payload(
            champion="Ahri",
            level=18,
            keystone="Aftershock",
            fight_mode="time_based",
            fight_duration=6.0,
            enemies=[{"champion": "Aatrox", "level": 18, "items": []}],
        ),
    )

    assert response.status_code == 200
    result = response.get_json()
    row = result["breakdown"].get("keystone_Aftershock")
    assert row is not None
    assert row["total_damage"] > 0.0
    combat = result["combat"]
    resistance_events = [
        event
        for event in combat["support_events"]
        if event["source"] == "Aftershock · Resistance"
    ]
    assert len(resistance_events) == 1
    event = resistance_events[0]
    assert event["bonus_armor"] == pytest.approx(45.0)
    assert event["bonus_magic_resistance"] == pytest.approx(45.0)
    assert event["aftershock"]["until"] == pytest.approx(2.5)
    main = next(
        participant
        for participant in combat["participants"]
        if participant["participant_id"] == "main"
    )
    assert len(main["survival"]["aftershock"]["trigger_events"]) == 1


def test_calculate_grasp_authors_self_heal_and_permanent_health():
    client = app_module.app.test_client()
    response = client.post(
        "/api/calculate",
        json=_payload(
            champion="Ahri",
            level=18,
            keystone="Grasp of the Undying",
            fight_mode="time_based",
            include_auto_attacks=True,
            fight_duration=9.0,
            auto_attack_uptime=1.0,
            target_mr=0.0,
            enemies=[{"champion": "Aatrox", "level": 18, "items": []}],
        ),
    )

    assert response.status_code == 200
    result = response.get_json()
    row = result["breakdown"].get("keystone_Grasp of the Undying")
    assert row is not None
    assert row["total_damage"] > 0.0
    combat = result["combat"]
    grasp_heals = [
        event
        for event in combat["healing_events"]
        if "Grasp of the Undying" in str(event.get("source"))
    ]
    assert len(grasp_heals) == 1
    health_events = [
        event
        for event in combat["support_events"]
        if event["source"] == "Grasp of the Undying · Permanent health"
    ]
    assert len(health_events) == 1
    assert health_events[0]["bonus_health"] == pytest.approx(2.0)
    main = next(
        participant
        for participant in combat["participants"]
        if participant["participant_id"] == "main"
    )
    assert main["survival"]["permanent_bonus_health_received"] == pytest.approx(2.0)


def test_calculate_hail_of_blades_authors_timed_true_damage_rider():
    client = app_module.app.test_client()
    response = client.post(
        "/api/calculate",
        json=_payload(
            champion="Ahri",
            level=18,
            keystone="Hail of Blades",
            fight_mode="time_based",
            include_auto_attacks=True,
            fight_duration=9.0,
            auto_attack_uptime=1.0,
            target_armor=0.0,
            target_mr=0.0,
            enemies=[{"champion": "Aatrox", "level": 18, "items": []}],
        ),
    )

    assert response.status_code == 200
    result = response.get_json()
    row = result["breakdown"].get("keystone_Hail of Blades")
    assert row is not None
    assert row["count"] == 2
    assert row["total_damage"] > 0.0
    assert result["damage_by_type"]["true"] >= row["total_damage"]


def test_calculate_lethal_tempo_authors_max_stack_bolts():
    client = app_module.app.test_client()
    response = client.post(
        "/api/calculate",
        json=_payload(
            champion="Ahri",
            level=18,
            keystone="Lethal Tempo",
            fight_mode="time_based",
            fight_duration=10.0,
            include_auto_attacks=True,
            auto_attack_uptime=1.0,
            enemies=[{"champion": "Aatrox", "level": 18, "items": []}],
        ),
    )

    assert response.status_code == 200
    row = response.get_json()["breakdown"].get("keystone_Lethal Tempo")
    assert row is not None
    assert row["count"] > 0


def test_calculate_fleet_footwork_uses_explicit_starting_charges():
    client = app_module.app.test_client()
    response = client.post(
        "/api/calculate",
        json=_payload(
            champion="Ahri",
            level=18,
            keystone="Fleet Footwork",
            keystone_options={"starting_charges": 100},
            fight_mode="time_based",
            fight_duration=5.0,
            include_auto_attacks=True,
            auto_attack_uptime=1.0,
            enemies=[{"champion": "Aatrox", "level": 18, "items": []}],
        ),
    )

    assert response.status_code == 200
    result = response.get_json()
    row = result["breakdown"]["heal_Fleet Footwork"]
    assert row["total_amount"] == pytest.approx(78.0)
    healing = [
        event
        for event in result["self_healing_events"]
        if event["source"].startswith("Fleet Footwork")
    ]
    assert len(healing) == 1
    movement = [
        event
        for event in result["combat"]["support_events"]
        if event["source"] == "Fleet Footwork · Energized movement speed"
    ]
    assert len(movement) == 1
    assert movement[0]["amount"] == pytest.approx(15.0)
    assert movement[0]["duration"] == pytest.approx(1.0)


def test_calculate_conqueror_records_stacks_and_max_stack_heals():
    client = app_module.app.test_client()
    response = client.post(
        "/api/calculate",
        json=_payload(
            champion="Ahri",
            level=18,
            keystone="Conqueror",
            keystone_options={"starting_stacks": 10},
            fight_mode="time_based",
            fight_duration=5.0,
            include_auto_attacks=True,
            auto_attack_uptime=1.0,
            enemies=[{"champion": "Aatrox", "level": 18, "items": []}],
        ),
    )

    assert response.status_code == 200
    result = response.get_json()
    stack_events = [
        event
        for event in result["combat"]["support_events"]
        if event["source"] == "Conqueror · stack"
    ]
    assert stack_events
    assert max(event["stacks_after"] for event in stack_events) == 12
    assert all(event["adaptive_force"] >= 0 for event in stack_events)
    heal_row = result["breakdown"].get("heal_Conqueror")
    assert heal_row is not None
    assert heal_row["total_amount"] > 0
    healing = [
        event
        for event in result["self_healing_events"]
        if event["source"] == "Conqueror · max-stack heal"
    ]
    assert len(healing) == heal_row["count"]


def test_calculate_deathfire_exposes_typed_burn_receipt():
    client = app_module.app.test_client()
    response = client.post(
        "/api/calculate",
        json=_payload(
            champion="Ahri",
            level=18,
            keystone="Deathfire Touch",
            target_mr=0.0,
        ),
    )

    assert response.status_code == 200
    result = response.get_json()
    row = result["breakdown"].get("keystone_Deathfire Touch")
    assert row is not None
    assert row["duration_by_category"] == {
        "spell_damage": 4.0,
        "area_damage": 2.0,
        "persistent_damage": 1.0,
        "persistent_area_damage": 1.0,
        "pet_damage": 1.0,
    }
    assert row["trigger_events"]
    burn_events = [
        event
        for event in result["damage_events"]
        if event["source"] == "keystone_Deathfire Touch"
    ]
    assert burn_events
    assert {event["damage_type"] for event in burn_events} == {"magic"}
    assert all("deathfire_category" in event for event in burn_events)


@pytest.mark.parametrize(
    "keystone",
    ["Unsealed Spellbook", "Fake Rune", 42],
)
def test_calculate_and_optimize_reject_unmodeled_keystones(keystone):
    client = app_module.app.test_client()
    for endpoint in ("/api/calculate", "/api/optimize"):
        response = client.post(endpoint, json=_payload(keystone=keystone))
        assert response.status_code == 400
        assert response.get_json()["error"]


def test_empty_keystone_is_the_default():
    client = app_module.app.test_client()
    response = client.post("/api/calculate", json=_payload(keystone=""))
    assert response.status_code == 200
    assert "keystone_Electrocute" not in response.get_json()["breakdown"]
