"""Issue #135 — 200% critical strikes at the public /api/calculate boundary.

Regression contract: the retired frontend engine priced autos at
``1 + (crit / 100) * 0.75`` (175%); the backend is the authority and
prices a critical hit at ``base * 2.0`` (``BASE_CRIT_MULTIPLIER = 2.0``
in ``src/calculator/damage.py``), i.e. autos deal ``base * (1 + crit)``
on average.

These tests drive 0% / 25% / 100% crit through the deterministic
``/api/calculate`` boundary against an unarmored target and assert, from the
response receipts alone (participant stats + auto schedule + auto breakdown),
that the expected-value auto damage uses a 2.0x critical multiplier.
"""

import pytest

import src.app as app_module
from tests.app_config import app_config


@pytest.fixture(autouse=True)
def _disable_rate_limits_between_route_tests():
    """Only dedicated tests spend the production abuse-control budget."""
    with app_config(RATE_LIMIT_ENABLED=False):
        yield


def _calculate_autos(items):
    """POST /api/calculate and return the auto-attack receipts."""
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
        "damage_per_hit": float(auto_row["damage_per_hit"]),
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


def test_calculate_prices_expected_value_with_25_percent_crit():
    result = _calculate_autos(["Navori Flickerblade"])
    assert result["crit"] == pytest.approx(25.0)
    expected_per_hit = result["ad"] * 1.25
    assert result["damage_per_hit"] == pytest.approx(expected_per_hit, abs=0.06)
    assert result["auto_damage"] == pytest.approx(
        result["autos"] * expected_per_hit, abs=0.06
    )
    # The retired 175% formula would have priced the expected value at 1.1875x AD.
    assert result["damage_per_hit"] != pytest.approx(result["ad"] * 1.1875, abs=0.06)


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
    assert result["damage_per_hit"] == pytest.approx(result["ad"] * 2.0, abs=0.06)
    assert result["auto_damage"] == pytest.approx(
        result["autos"] * result["ad"] * 2.0, abs=0.06
    )
    # The retired 175% formula would have priced these at 1.75x, a 12.5% miss.
    assert result["auto_damage"] != pytest.approx(
        result["autos"] * result["ad"] * 1.75, abs=0.06
    )
