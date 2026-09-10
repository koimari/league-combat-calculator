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


def test_hud_rank_defaults_follow_engine_skill_orders():
    from src.calculator.champions.skill_orders import get_ability_rank

    champions = app_module.app.test_client().get("/api/champions").get_json()
    for name in ("Ashe", "Jayce", "Udyr"):
        champion = next(entry for entry in champions if entry["name"] == name)
        for level in (1, 6, 11, 18, 20):
            assert champion["rank_defaults_by_level"][str(level)] == {
                slot: get_ability_rank(slot, level, name)
                for slot in ("Q", "W", "E", "R")
            }


def test_hud_tooltip_preserves_all_cached_ability_branches():
    champions = app_module.app.test_client().get("/api/champions").get_json()
    ashe = next(entry for entry in champions if entry["name"] == "Ashe")
    tooltip = ashe["abilities"]["Q"]
    assert "Passive:" in tooltip["description"]
    assert "Active:" in tooltip["description"]
    assert "resets Ashe's basic attack timer" in tooltip["description"]
    attack_speed = next(
        row for row in tooltip["rank_values"] if row["label"] == "Bonus Attack Speed"
    )
    assert attack_speed["values"] == ["20%", "30%", "40%", "50%", "60%"]
    assert any(row["label"] == "Cost" for row in tooltip["rank_values"])
