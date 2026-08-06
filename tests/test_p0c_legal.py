"""P0c closed-beta legal pages.

Covers the public terms-of-use and Riot Games disclaimer pages, their
routing (both reachable with the auth gate on and off), the links to all
three legal pages from the beta landing and the main-page footer, and the
gate-exemption of the legal surface.
"""

import base64
import hashlib
import json

import pytest

import src.app as app_module


@pytest.fixture(autouse=True)
def _disable_rate_limits_between_route_tests():
    """Keep these route tests off the production abuse-control budget."""
    previous = app_module.app.config.get("RATE_LIMIT_ENABLED", True)
    app_module.app.config["RATE_LIMIT_ENABLED"] = False
    yield
    app_module.app.config["RATE_LIMIT_ENABLED"] = previous


def _test_password_hash(password="secret"):
    salt = b"p0c-legal-salt"
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16_384, r=8, p=1)
    enc = lambda value: base64.urlsafe_b64encode(value).rstrip(b"=").decode()
    return f"scrypt$16384$8$1${enc(salt)}${enc(digest)}"


@pytest.fixture
def invite_env(monkeypatch):
    """Auth gate on with a configured invite-code list."""
    monkeypatch.setenv("SCRYGLASS_AUTH_REQUIRED", "1")
    monkeypatch.setenv("SCRYGLASS_AUTH_SECRET", "p0c-legal-secret")
    monkeypatch.setenv(
        "SCRYGLASS_AUTH_USERS",
        json.dumps({"BetaResearcher": _test_password_hash()}),
    )
    monkeypatch.setenv("SCRYGLASS_INVITE_CODES", "BETA-2026, PRESS-CLUB")
    return app_module


# ---------------------------------------------------------------------------
# Terms of use
# ---------------------------------------------------------------------------


def test_terms_page_renders_usage_terms(invite_env):
    page = invite_env.app.test_client().get("/terms")
    body = page.get_data(as_text=True)
    assert page.status_code == 200
    for required in (
        "Terms of use",
        "closed beta",
        "invite code",
        "Beta access",
        "Invite-code responsibility",
        "No warranty on calculations",
        "Acceptable use",
        '"as is"',
    ):
        assert required in body, required


def test_terms_page_renders_without_auth_gate():
    page = app_module.app.test_client().get("/terms")
    assert page.status_code == 200
    assert "Terms of use" in page.get_data(as_text=True)


# ---------------------------------------------------------------------------
# Riot Games disclaimer
# ---------------------------------------------------------------------------


def test_riot_disclaimer_page_renders(invite_env):
    page = invite_env.app.test_client().get("/riot-disclaimer")
    body = page.get_data(as_text=True)
    assert page.status_code == 200
    for required in (
        "Riot Games disclaimer",
        "isn't endorsed by Riot Games",
        "not affiliated with Riot",
        "trademarks or registered trademarks of Riot Games",
        "League of Legends Wiki",
        "CC-BY-SA",
        "Game files",
        "Community Dragon",
        "Riot API",
        "is not an official Riot",
    ):
        assert required in body, required


def test_riot_disclaimer_page_renders_without_auth_gate():
    page = app_module.app.test_client().get("/riot-disclaimer")
    assert page.status_code == 200
    assert "Riot Games disclaimer" in page.get_data(as_text=True)


# ---------------------------------------------------------------------------
# Legal links from the beta landing and the main-page footer
# ---------------------------------------------------------------------------


def test_beta_landing_links_all_three_legal_pages(invite_env):
    body = invite_env.app.test_client().get("/auth/login").get_data(as_text=True)
    for href in ("/privacy", "/terms", "/riot-disclaimer"):
        assert f'href="{href}"' in body, href


def test_main_page_footer_links_all_three_legal_pages(invite_env):
    client = invite_env.app.test_client()
    login = client.post(
        "/auth/login",
        data={
            "username": "BetaResearcher",
            "password": "secret",
            "invite_code": "BETA-2026",
            "next": "/",
        },
        follow_redirects=False,
    )
    assert login.status_code == 302
    body = client.get("/").get_data(as_text=True)
    assert 'class="site-footer"' in body
    for href in ("/privacy", "/terms", "/riot-disclaimer"):
        assert f'href="{href}"' in body, href
    assert "Not endorsed by Riot Games" in body


def test_main_page_footer_rendered_only_after_login(invite_env):
    client = invite_env.app.test_client()
    gated = client.get("/", follow_redirects=False)
    assert gated.status_code == 302
    assert "/auth/login" in gated.headers["Location"]


# ---------------------------------------------------------------------------
# Gate exemption
# ---------------------------------------------------------------------------


def test_legal_pages_are_gate_exempt(invite_env):
    client = invite_env.app.test_client()
    for path in ("/privacy", "/terms", "/riot-disclaimer"):
        assert client.get(path).status_code == 200, path
    # The rest of the UI stays gated.
    assert client.get("/", follow_redirects=False).status_code == 302
    assert client.get("/api/items").status_code == 302
