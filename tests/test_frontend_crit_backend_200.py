"""Issue #135 — 200% critical strikes at the public /api/calculate boundary.

Regression contract: the retired frontend engine priced autos at
``1 + (crit / 100) * 0.75`` (175%); the backend is the authority and
prices a critical hit at ``base * 2.0`` (``BASE_CRIT_MULTIPLIER = 2.0``
in ``src/calculator/damage.py``), i.e. autos deal ``base * (1 + crit)``
on average.

These tests drive 0% / 25% / 100% crit through ``/api/calculate`` against
an unarmored target and assert, from the response receipts alone
(participant stats + auto schedule + auto breakdown), that a non-crit
auto is priced at ``attack_damage`` and a crit at ``attack_damage * 2.0``.
"""

import pytest

import src.app as app_module
from src.calculator import damage as damage_module


@pytest.fixture(autouse=True)
def _disable_rate_limits_between_route_tests():
    """Only dedicated tests spend the production abuse-control budget."""
    previous = app_module.app.config.get("RATE_LIMIT_ENABLED", True)
    app_module.app.config["RATE_LIMIT_ENABLED"] = False
    yield
    app_module.app.config["RATE_LIMIT_ENABLED"] = previous


def _calculate_autos(items, monkeypatch=None, crit_roll=None):
    """POST /api/calculate and return the auto-attack receipts.

    ``crit_roll`` pins the engine's per-auto roll (``random.random()``)
    when a partial crit chance must be observed deterministically; the
    request still goes through the public route.
    """
    if crit_roll is not None:
        assert monkeypatch is not None
        monkeypatch.setattr(damage_module.random, "random", lambda: crit_roll)
    response = app_module.app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Caitlyn",
            "level": 18,
            "items": items,
            "fight_mode": "one_rotation",
            "auto_attack_uptime_mode": "calculated",
            "include_auto_attacks": True,
            "target_health": 10_000,
            "target_bonus_health": 0,
            "target_armor": 0,
            "target_mr": 0,
            "rotations": 1,
        },
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data.get("error") is None
    main = next(
        row for row in data["combat"]["participants"] if row["participant_id"] == "main"
    )
    stats = main["stats"]
    autos = int(data["auto_attack_schedule"]["expected_autos_total"])
    assert autos > 0
    auto_row = data["breakdown"]["auto_attacks"]
    return {
        "ad": float(stats["attack_damage"]),
        "crit": float(stats["critical_strike_chance"]),
        "autos": autos,
        "auto_damage": float(data["auto_attack_damage"]),
        "num_crits": int(auto_row.get("num_crits") or 0),
        "num_non_crits": int(auto_row.get("num_non_crits") or 0),
        "crit_damage_per_hit": auto_row.get("crit_damage_per_hit"),
        "non_crit_damage_per_hit": auto_row.get("non_crit_damage_per_hit"),
    }


def test_calculate_prices_zero_crit_autos_at_base_ad():
    result = _calculate_autos([])
    assert result["crit"] == 0.0
    # At 0% crit every roll is a non-crit: fully deterministic.
    assert result["num_crits"] == 0
    assert result["num_non_crits"] == result["autos"]
    assert result["non_crit_damage_per_hit"] == pytest.approx(result["ad"], abs=0.06)
    assert result["auto_damage"] == pytest.approx(
        result["autos"] * result["ad"], abs=0.06
    )


def test_calculate_prices_crits_at_2_0x_base_with_25_percent_crit(monkeypatch):
    # Pin the engine roll so the 25% case observes crits deterministically
    # (0.1 < 0.25 -> every auto crits); the request still flows through
    # /api/calculate and the receipts come from the response.
    result = _calculate_autos(
        ["Navori Flickerblade"], monkeypatch=monkeypatch, crit_roll=0.1
    )
    assert result["crit"] == pytest.approx(25.0)
    assert result["num_crits"] == result["autos"]
    assert result["crit_damage_per_hit"] == pytest.approx(result["ad"] * 2.0, abs=0.06)
    assert result["auto_damage"] == pytest.approx(
        result["autos"] * result["ad"] * 2.0, abs=0.06
    )
    # The retired 175% formula would have priced the crit at 1.75x AD.
    assert result["crit_damage_per_hit"] != pytest.approx(result["ad"] * 1.75, abs=0.06)


def test_calculate_prices_100_percent_crit_autos_at_2_0x_base():
    result = _calculate_autos(
        [
            "Phantom Dancer",
            "Navori Flickerblade",
            "Mortal Reminder",
            "Immortal Shieldbow",
        ]
    )
    assert result["crit"] == pytest.approx(100.0)
    # At 100% crit every roll is a crit: fully deterministic.
    assert result["num_crits"] == result["autos"]
    assert result["num_non_crits"] == 0
    assert result["crit_damage_per_hit"] == pytest.approx(result["ad"] * 2.0, abs=0.06)
    assert result["auto_damage"] == pytest.approx(
        result["autos"] * result["ad"] * 2.0, abs=0.06
    )
    # The retired 175% formula would have priced these at 1.75x, a 12.5% miss.
    assert result["auto_damage"] != pytest.approx(
        result["autos"] * result["ad"] * 1.75, abs=0.06
    )
