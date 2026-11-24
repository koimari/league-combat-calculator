"""A champion's stack walk runs only in that champion's own fight.

Two kits can declare the same option key: Irelia and K'Sante both read
``w_charge``.  Gating a walk on its option alone let K'Sante's Path Maker
publish a ``w`` resource ledger on an Irelia fight that set the key.
"""

from types import SimpleNamespace

import pytest

from src import app as app_module
from src.calculator.fight.stacks.account import walks_for


def _resource_ledger(champion: str, options: dict) -> dict:
    payload = {
        "champion": champion,
        "level": 18,
        "items": [],
        "role": "top",
        "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
        "fight_mode": "time_based",
        "fight_duration": 10,
        "include_auto_attacks": True,
        "champion_options": options,
        "enemies": [
            {
                "champion": "Ahri",
                "level": 18,
                "items": [],
                "role": "mid",
                "ability_ranks": {"Q": 5, "W": 5, "E": 0, "R": 3},
            }
        ],
    }
    response = app_module.app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200, response.get_json()
    return response.get_json()["targets"][0]["result"]["resource_ledger"]


def test_an_irelia_fight_setting_w_charge_publishes_no_path_maker_ledger():
    assert "w" not in _resource_ledger("Irelia", {"w_charge": 0.5})


def test_a_ksante_fight_setting_w_charge_keeps_its_path_maker_ledger():
    assert "w" in _resource_ledger("K'Sante", {"w_charge": 0.5})


@pytest.mark.parametrize(
    ("champion_name", "runs"),
    [("K'Sante", True), ("Irelia", False), (None, True)],
)
def test_the_gate_admits_the_owner_and_an_unnamed_fight(champion_name, runs):
    state = SimpleNamespace(champion_name=champion_name)
    assert walks_for(state, "K'Sante") is runs
