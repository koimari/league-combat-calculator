"""Keep the server credential confined to calculator operations."""

import time

import pytest
from flask import jsonify

import src.app as app_module
from src.service_auth import authorize_service_request
from tests.app_config import app_config

TOKEN = "test-calculator-service-credential-123456789"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("CALCULATOR_SERVICE_TOKEN", TOKEN)
    monkeypatch.setenv("SCRYGLASS_AUTH_REQUIRED", "1")
    monkeypatch.setenv("SCRYGLASS_AUTH_SECRET", "test-browser-cookie-secret")
    with app_config(TESTING=True, RATE_LIMIT_ENABLED=False):
        yield app_module.app.test_client()


def test_service_can_read_catalog_without_browser_session(client):
    response = client.get("/api/config", headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 200
    assert response.get_json()["capabilities"]["schema_version"] >= 1
    assert "CALCULATOR_SERVICE_TOKEN" not in response.get_data(as_text=True)
    assert TOKEN not in response.get_data(as_text=True)


@pytest.mark.parametrize("header", ["Bearer wrong", "Bearer", "Bearer " + "é" * 32])
def test_bad_bearer_returns_json_401(client, header):
    response = client.get("/api/config", headers={"Authorization": header})
    assert response.status_code == 401
    assert response.get_json()["error"] == "Calculator service authentication failed"
    assert response.headers["WWW-Authenticate"] == 'Bearer realm="calculator"'


def test_missing_bearer_preserves_browser_login(client):
    response = client.get("/api/config")
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]
    client.set_cookie(
        app_module._AUTH_COOKIE,
        app_module._pack_signed({"username": "reader", "exp": time.time() + 60}),
    )
    assert client.get("/api/config").status_code == 200
    assert (
        client.get("/api/config", headers={"Authorization": "Bearer wrong"}).status_code
        == 401
    )


@pytest.mark.parametrize("secret", ["", "short", "x" * 31])
def test_unconfigured_or_short_secret_rejects_bearer(client, monkeypatch, secret):
    monkeypatch.setenv("CALCULATOR_SERVICE_TOKEN", secret)
    response = client.get("/api/config", headers={"Authorization": f"Bearer {secret}"})
    assert response.status_code == 401


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/update-data"),
        ("GET", "/api/metrics"),
        ("POST", "/api/builds"),
        ("POST", "/api/share"),
        ("GET", "/api/share/example"),
        ("GET", "/auth/logout"),
        ("GET", "/"),
        ("POST", "/api/config"),
        ("HEAD", "/api/config"),
        ("GET", "/api/config/"),
        ("GET", "/static/reviewed-packets.json"),
    ],
)
def test_service_cannot_cross_its_route_boundary(client, method, path):
    response = client.open(
        path, method=method, headers={"Authorization": f"Bearer {TOKEN}"}
    )
    assert response.status_code == 401


def test_disabled_browser_gate_keeps_bearer_validation(client, monkeypatch):
    monkeypatch.setenv("SCRYGLASS_AUTH_REQUIRED", "0")
    assert client.get("/api/config").status_code == 200
    assert (
        client.get("/api/config", headers={"Authorization": "Bearer wrong"}).status_code
        == 401
    )
    assert (
        client.get(
            "/api/config", headers={"Authorization": f"Bearer {TOKEN}"}
        ).status_code
        == 200
    )


def test_compute_service_uses_existing_rate_policy(client, monkeypatch):
    calls = []

    def limited(scope):
        calls.append(scope)
        response = jsonify({"error": "busy"})
        response.status_code = 429
        response.headers["Retry-After"] = "7"
        return response

    monkeypatch.setattr(app_module, "_spend_rate_limit", limited)
    response = client.post(
        "/api/calculate",
        json={"champion": "Aatrox"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "7"
    assert calls == ["calculate"]


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/static/ability-catalog.json"),
        ("POST", "/api/bis/batch"),
        ("POST", "/api/loadout-stats"),
    ],
)
def test_service_scope_accepts_nested_compute_and_catalog_paths(method, path):
    assert (
        authorize_service_request(
            f"bearer {TOKEN}", method=method, path=path, configured_token=TOKEN
        )
        is True
    )
