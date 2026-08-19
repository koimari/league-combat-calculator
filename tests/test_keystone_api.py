"""Route-level contracts for keystone rune selection."""

import pytest

import src.app as app_module
from src.calculator import rune_effects


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


def test_config_serves_the_whole_keystone_roster_as_implemented():
    config = app_module.app.test_client().get("/api/config").get_json()

    keystones = config["keystones"]
    assert len(keystones) == 17
    by_name = {entry["name"]: entry for entry in keystones}
    assert by_name["Electrocute"]["path"] == "Domination"
    assert all(entry["implemented"] is True for entry in keystones)
    assert all(entry["icon"] for entry in keystones)
    # Paths arrive grouped in wiki order for direct picker rendering.
    paths = [entry["path"] for entry in keystones]
    assert paths.index("Precision") < paths.index("Domination") < paths.index("Sorcery")


def test_every_keystone_computes_through_the_calculate_route():
    """Criterion 5: no selection in the roster refuses."""
    client = app_module.app.test_client()
    keystones = [
        entry["name"] for entry in client.get("/api/config").get_json()["keystones"]
    ]
    for keystone in keystones:
        response = client.post(
            "/api/calculate",
            json=_payload(
                keystone=keystone,
                fight_mode="time_based",
                include_auto_attacks=True,
                fight_duration=10.0,
                auto_attack_uptime=1.0,
            ),
        )
        assert response.status_code == 200, keystone
        result = response.get_json()
        # Every keystone either books a row or publishes a receipt saying
        # why it did not; silence is the one answer that is not allowed.
        assert f"keystone_{keystone}" in result["breakdown"] or any(
            note.startswith(keystone) for note in result["notes"]
        ), keystone


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


@pytest.mark.parametrize("keystone", ["Fake Rune", 42])
def test_calculate_and_optimize_reject_unknown_keystones(keystone):
    client = app_module.app.test_client()
    for endpoint in ("/api/calculate", "/api/optimize"):
        response = client.post(endpoint, json=_payload(keystone=keystone))
        assert response.status_code == 400
        assert response.get_json()["error"]


def test_an_uncompiled_keystone_is_still_rejected(monkeypatch):
    """The withhold survives: a rune with no compiler still 400s."""
    monkeypatch.setitem(
        rune_effects.RUNE_EFFECTS, "Synthetic Keystone", {"name": "Synthetic"}
    )
    response = app_module.app.test_client().post(
        "/api/calculate", json=_payload(keystone="Synthetic Keystone")
    )
    assert response.status_code == 400
    assert "not modeled" in response.get_json()["error"]


@pytest.mark.parametrize(
    "keystone,expected_row",
    [
        ("Summon Aery", True),
        ("Hail of Blades", True),
        ("Grasp of the Undying", True),
        ("Lethal Tempo", True),
        ("Deathfire Touch", True),
        ("Dark Harvest", False),
        ("Conqueror", False),
        ("Fleet Footwork", False),
        ("Aftershock", False),
        ("Guardian", False),
        ("Glacial Augment", False),
        ("Stormraider's Surge", False),
        ("Unsealed Spellbook", False),
    ],
)
def test_the_thirteen_new_keystones_price_exactly_what_they_declare(
    keystone, expected_row
):
    """Each new keystone either adds its own row to the total, or nothing.

    A keystone that books damage adds exactly its row; one that books none
    leaves the total bit-identical to the same fight without it. Either way
    the receipt reaches the user through the notes.
    """
    fight = {
        "fight_mode": "time_based",
        "include_auto_attacks": True,
        "fight_duration": 10.0,
        "auto_attack_uptime": 1.0,
    }
    client = app_module.app.test_client()
    result = client.post(
        "/api/calculate", json=_payload(keystone=keystone, **fight)
    ).get_json()
    baseline = client.post("/api/calculate", json=_payload(**fight)).get_json()

    row = result["breakdown"].get(f"keystone_{keystone}")
    if expected_row:
        assert row is not None and row["total_damage"] > 0
        assert result["total_damage"] == pytest.approx(
            baseline["total_damage"] + row["total_damage"], rel=1e-6
        )
    else:
        assert row is None
        assert result["total_damage"] == pytest.approx(baseline["total_damage"])
    assert any(note.startswith(keystone) for note in result["notes"])


def test_empty_keystone_is_the_default():
    client = app_module.app.test_client()
    response = client.post("/api/calculate", json=_payload(keystone=""))
    assert response.status_code == 200
    assert "keystone_Electrocute" not in response.get_json()["breakdown"]
