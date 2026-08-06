"""E8 follow-up tests: coordinator-applied engine hooks.

The E8d agent documented six missing engine hooks; this file pins the
coordinator's implementations:
1. Champion revives (Anivia Rebirth, Zac Cell Division, Zilean Chronoshift)
   flow through resolve_starting_defenses into the participant ledger with
   the champion's own source label (not Guardian Angel).
2. Taric Q prose heal emits via the module-heal registry (1 charge).
3. Bard W emits the fully-charged Maximum Heal row.
4. Yuumi E targets the attached anchor (one_teammate).
5. Rakan P Fancy Footwork self-shield rides the first damaging cast.
"""

import json

import pytest

from src import app as app_module
from src.calculator.defensive_effects import resolve_starting_defenses
from src.calculator.support_effects import derive_ally_effects


@pytest.fixture(scope="module")
def champion_data():
    return json.load(open("data/champions.json"))


def _resolve(champ: str, level: int = 18, *, items=(), **stats):
    return resolve_starting_defenses(
        champ,
        level,
        {"health": 2000.0, "ability_power": 0.0, **stats},
        items=items,
    )


def test_anivia_rebirth_starting_defense(champion_data):
    d = _resolve("Anivia")
    assert d.revive_health_amount == pytest.approx(2000.0)
    assert d.revive_delay == pytest.approx(6.0)
    assert d.revive_cooldown == pytest.approx(240.0)
    assert d.revive_source == "Rebirth"


def test_zac_cell_division_starting_defense(champion_data):
    d = _resolve("Zac")
    assert d.revive_health_amount == pytest.approx(1000.0)  # 50% max HP
    assert d.revive_delay == pytest.approx(4.0)
    assert d.revive_cooldown == pytest.approx(300.0)
    assert d.revive_source == "Cell Division"


def test_zilean_chronoshift_starting_defense(champion_data):
    d = _resolve("Zilean")
    assert d.revive_health_amount == pytest.approx(1100.0)  # R rank 3 heal
    assert d.revive_delay == pytest.approx(3.0)
    assert d.revive_cooldown == pytest.approx(60.0)
    assert d.revive_source == "Chronoshift"


def test_non_revive_champion_fails_closed(champion_data):
    d = _resolve("Ahri")
    assert d.revive_health_amount == 0.0
    assert d.revive_source == ""


def test_guardian_angel_keeps_item_source(champion_data):
    from src.calculator.scenario import get_item_by_name

    d = _resolve(
        "Ahri",
        base_health=1500.0,
        items=[get_item_by_name("Guardian Angel")],
    )
    assert d.revive_health_amount == pytest.approx(750.0)
    assert d.revive_source == "Guardian Angel (Rebirth)"


def test_taric_q_prose_heal_emits(champion_data):
    casts = [{"slot": "Q", "time": 1.0, "ability_name": "Starlight's Touch"}]
    eff = derive_ally_effects(
        champion_data["Taric"], 18, {"ability_power": 0.0, "health": 2000.0}, casts
    )
    heals = [e for e in eff if e["kind"] == "heal" and e["slot"] == "Q"]
    assert heals, "Taric Q prose heal missing"
    assert heals[0]["amount"] == pytest.approx(45.0)  # 25 + 1% max HP
    assert heals[0]["target_scope"] == "self_and_all_teammates"


def test_bard_w_fully_charged_shrine_emits(champion_data):
    casts = [{"slot": "W", "time": 1.0, "ability_name": "Caretaker's Shrine"}]
    eff = derive_ally_effects(
        champion_data["Bard"], 18, {"ability_power": 0.0, "health": 2000.0}, casts
    )
    heals = [e for e in eff if e["kind"] == "heal" and e["slot"] == "W"]
    assert heals, "Bard W shrine heal missing"
    assert heals[0]["amount"] == pytest.approx(200.0)  # Maximum Heal rank 5
    assert "Maximum Heal" in heals[0]["source"]


def test_yuumi_e_targets_anchor(champion_data):
    casts = [{"slot": "E", "time": 1.0, "ability_name": "Zoomies"}]
    eff = derive_ally_effects(
        champion_data["Yuumi"], 18, {"ability_power": 0.0, "health": 2000.0}, casts
    )
    shields = [e for e in eff if e["kind"] == "shield" and e["slot"] == "E"]
    assert shields, "Yuumi E shield missing"
    assert shields[0]["amount"] == pytest.approx(165.0)
    assert shields[0]["target_scope"] == "one_teammate"


def test_rakan_p_shield_rides_q(champion_data):
    from src.calculator.champions.rakan import parse_abilities

    out = parse_abilities(
        champion_data["Rakan"], 18, 0.0, {}, {},
        {"health": 2000.0, "ability_power": 0.0}, {},
    )
    q = out.get("Q", {})
    payload = q.get("self_shield_events")
    assert payload, "Rakan P self-shield payload missing on Q"
    assert payload[0]["amount"] == pytest.approx(247.94)  # level-18 base
    assert payload[0]["source"] == "Fey Feathers"
