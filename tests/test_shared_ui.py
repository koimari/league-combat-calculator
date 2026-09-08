"""Mount the shared interface while retaining saved roster workspaces."""

from bs4 import BeautifulSoup

import src.app as app_module
from tests.app_config import app_config


def test_home_mounts_shared_calculator_assets():
    with app_config(TESTING=True, RATE_LIMIT_ENABLED=False):
        response = app_module.app.test_client().get("/")
    assert response.status_code == 200
    soup = BeautifulSoup(response.get_data(as_text=True), "html.parser")
    assert soup.select_one("#calculator-app") is not None
    assert soup.select_one('script[src="/static/calculator/calculator.js"]')
    assert soup.select_one('link[href="/static/calculator/calculator.css"]')
    assert soup.select_one('a[href="/advanced"]')


def test_saved_share_links_keep_their_roster_workspace():
    with app_config(TESTING=True, RATE_LIMIT_ENABLED=False):
        response = app_module.app.test_client().get("/?share=existing-token")
    assert response.status_code == 200
    soup = BeautifulSoup(response.get_data(as_text=True), "html.parser")
    assert soup.select_one("#duelA") is not None
    assert soup.select_one("#calculator-app") is None


def test_advanced_workspace_remains_behind_browser_auth(monkeypatch):
    monkeypatch.setenv("SCRYGLASS_AUTH_REQUIRED", "1")
    with app_config(TESTING=True, RATE_LIMIT_ENABLED=False):
        response = app_module.app.test_client().get("/advanced")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/auth/login?next=/advanced")
