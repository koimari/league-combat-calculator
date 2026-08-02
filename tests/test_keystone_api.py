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
    assert by_name["Dark Harvest"]["implemented"] is False
    assert all(entry["icon"] for entry in keystones)
    # Paths arrive grouped in wiki order for direct picker rendering.
    paths = [entry["path"] for entry in keystones]
    assert paths.index("Precision") < paths.index("Domination") < paths.index("Sorcery")


def test_calculate_includes_electrocute_breakdown_row():
    client = app_module.app.test_client()
    with_keystone = client.post(
        "/api/calculate", json=_payload(keystone="Electrocute")
    )
    without_keystone = client.post("/api/calculate", json=_payload())

    assert with_keystone.status_code == 200
    result = with_keystone.get_json()
    row = result["breakdown"].get("keystone_Electrocute")
    assert row is not None
    assert row["name"] == "Electrocute (keystone)"
    assert row["total_damage"] > 0
    assert (
        result["total_damage"]
        == pytest.approx(
            without_keystone.get_json()["total_damage"] + row["total_damage"],
            rel=1e-6,
        )
    )


@pytest.mark.parametrize(
    "keystone",
    ["Dark Harvest", "Fake Rune", 42],
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
