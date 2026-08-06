"""E1-b1 sourced self-heal rules (Aphelios, Camille, Fiddlesticks, Hecarim,
Swain, Trundle, Xin Zhao).

Each test drives a /api/calculate fight through the app test client and
asserts the heal event amount against a value sourced from
data/champions.json (leveling arrays / effect descriptions).

Deliberately not implemented:
- Bel'Veth: her only self-heal (Endless Banquet's True Form heal) fires when
  consuming a Void Coral, which requires a champion takedown — an event the
  1v1 fight model does not produce.
- Trundle P (King's Tribute): heals on a nearby enemy champion's DEATH; no
  death occurs inside the fight model.

The response rounds event damage/raw_damage and heal amounts to one decimal,
so assertions use a tolerance that covers that rounding.
"""

import json
from pathlib import Path

import pytest

from src import app as app_module
from src.calculator.champions.slotlib import (
    extract_named,
    find_named_leveling,
    sum_modifiers,
)

_ENEMY_NAMES = ["Ahri", "Annie", "Orianna"]

_DATA = json.loads(
    Path(__file__)
    .resolve()
    .parents[1]
    .joinpath("data", "champions.json")
    .read_text(encoding="utf-8")
)


def _fight(
    champion: str,
    *,
    level: int = 18,
    ranks: dict | None = None,
    ap_item: str | None = None,
    lifesteal_item: str | None = None,
    champion_options: dict | None = None,
    role: str = "top",
) -> dict:
    items = []
    if ap_item:
        items.append(ap_item)
    if lifesteal_item:
        items.append(lifesteal_item)
    payload = {
        "champion": champion,
        "level": level,
        "items": items,
        "role": role,
        "ability_ranks": ranks or {"Q": 5, "W": 5, "E": 5, "R": 3},
        "fight_mode": "time_based",
        "fight_duration": 10,
        "include_auto_attacks": True,
        "champion_options": champion_options or {},
        "enemies": [
            {
                "champion": _ENEMY_NAMES[0],
                "level": 18,
                "items": [],
                "role": "mid",
                "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
            }
        ],
    }
    app_module.app.config["TESTING"] = True
    response = app_module.app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200
    return response.get_json()


def _main_heals(data: dict, source: str) -> list[dict]:
    return [
        event
        for event in data["combat"]["healing_events"]
        if event.get("attacker") == "main" and event.get("source") == source
    ]


def _main_events(data: dict) -> dict[str, dict]:
    return {
        event["event_id"]: event
        for event in data["combat"]["events"]
        if event.get("attacker") == "main"
    }


def test_aphelios_severum_heals_sourced_percent_of_post_mitigation_damage():
    """Severum on-hit: per-level % of post-mitigation damage, weapon-gated."""
    # Severum's attacks heal a per-level percent of the POST-mitigation
    # damage dealt (data P[2]: "2% : 7.1% (based on level) ... increased to
    # 5% : 17.75% (based on level) for attacks from abilities").
    data = _fight(
        "Aphelios",
        role="mid",
        champion_options={"aphelios_main_weapon": "severum"},
    )
    heals = _main_heals(data, "Severum")
    assert heals, "Severum heal missing"
    events = _main_events(data)

    severum = next(
        entry
        for entry in _DATA["Aphelios"]["abilities"]["P"]
        if entry.get("name") == "Severum"
    )
    level = 18
    basic_ratio = (
        sum_modifiers(
            find_named_leveling(severum, "Per-Level Scaling", 0), level, {}, {}
        )
        / 100.0
    )
    ability_ratio = (
        sum_modifiers(
            find_named_leveling(severum, "Per-Level Scaling", 1), level, {}, {}
        )
        / 100.0
    )
    assert basic_ratio == pytest.approx(0.071)
    assert ability_ratio == pytest.approx(0.1775)
    for heal in heals:
        event = events[heal["trigger_event_id"]]
        ratio = ability_ratio if event["source"] == "Q" else basic_ratio
        assert heal["amount"] == pytest.approx(ratio * event["damage"], abs=0.11)
    # The heal is weapon-gated: a non-Severum main weapon heals nothing.
    calibrum = _fight(
        "Aphelios",
        role="mid",
        champion_options={"aphelios_main_weapon": "calibrum"},
    )
    assert not _main_heals(calibrum, "Severum")


def test_fiddlesticks_bountiful_harvest_heals_portion_of_pre_mitigation_damage():
    """Bountiful Harvest drains: rank-scaled % of pre-mitigation damage."""
    # Bountiful Harvest "heals itself for a portion of the pre-mitigation
    # damage dealt"; the Champion Heal Portion at W rank 5 is 55%.
    data = _fight("Fiddlesticks")
    heals = _main_heals(data, "Bountiful Harvest")
    assert heals, "Bountiful Harvest heal missing"
    events = _main_events(data)
    w_ability = _DATA["Fiddlesticks"]["abilities"]["W"][0]
    portion = extract_named(w_ability, "Champion Heal Portion", 5, {}, {}) / 100.0
    assert portion == pytest.approx(0.55)
    for heal in heals:
        event = events[heal["trigger_event_id"]]
        assert event["source"] == "W"
        assert heal["amount"] == pytest.approx(portion * event["raw_damage"], abs=0.11)


def test_camille_tactical_sweep_heals_outer_cone_additional_damage():
    """Tactical Sweep: 100% of the outer-cone bonus damage post-mitigation."""
    # "Camille is healed for 100% of this additional damage post-mitigation"
    # (data W effect[1]) — the outer-cone sweet spot. The W row is the
    # sourced base physical damage plus that outer amount; both parts share
    # one armor mitigation, so the post-mit outer heal is the raw surplus
    # over the base scaled by damage/raw.
    data = _fight("Camille")
    heals = _main_heals(data, "Tactical Sweep")
    assert heals, "Tactical Sweep heal missing"
    events = _main_events(data)
    w_ability = _DATA["Camille"]["abilities"]["W"][0]
    base_raw = extract_named(w_ability, "Physical Damage", 5, {}, {})
    assert base_raw == pytest.approx(160.0)
    for heal in heals:
        event = events[heal["trigger_event_id"]]
        assert event["source"] == "W"
        expected = (
            (event["raw_damage"] - base_raw) * event["damage"] / event["raw_damage"]
        )
        assert heal["amount"] == pytest.approx(expected, abs=0.11)


def test_hecarim_spirit_of_dread_heals_quarter_of_damage_while_active():
    """Spirit of Dread: 25% of post-mitigation damage while active (4s)."""
    # Spirit of Dread: "healed for 25% of the post-mitigation damage dealt
    # to enemies within the area from all sources" for 4 seconds per W cast
    # (data W effect[1]); the sourced cap applies only to minions/monsters.
    data = _fight("Hecarim")
    heals = _main_heals(data, "Spirit of Dread")
    assert heals, "Spirit of Dread heal missing"
    events = _main_events(data)
    for heal in heals:
        event = events[heal["trigger_event_id"]]
        assert 0.0 <= event["time"] <= 4.0
        assert heal["amount"] == pytest.approx(0.25 * event["damage"], abs=0.11)
    # Every in-window main event healed, and nothing outside the window did.
    window_events = [event for event in events.values() if 0.0 <= event["time"] <= 4.0]
    assert len(heals) == len(window_events)
    outside = [event for event in events.values() if event["time"] > 4.0]
    assert outside, "expected events outside the Spirit of Dread window"
    healed_ids = {heal["trigger_event_id"] for heal in heals}
    assert not any(event["event_id"] in healed_ids for event in outside)


def test_swain_demonic_ascension_heals_flat_per_tick():
    """Demonic Ascension: flat heal per drain tick, +2.5% AP."""
    # Demonic Ascension heals a flat amount per 0.5-second drain tick per
    # target (data R effect[1]): Heal per Tick 7.5/15/22.5 + 2.5% AP + 0.75%
    # of his bonus health. The "Reduced Heal per Tick" entry is the
    # 90%-reduced minion/monster variant. Rabadon's Deathcap supplies AP.
    data = _fight("Swain", ap_item="Rabadon's Deathcap")
    heals = _main_heals(data, "Demonic Ascension")
    assert heals, "Demonic Ascension heal missing"
    r_ability = _DATA["Swain"]["abilities"]["R"][0]
    stats = {
        "ability_power": data["champion_stats"]["ability_power"],
        "bonus_health": data["champion_stats"].get("bonus_health", 0.0),
    }
    heal_leveling = find_named_leveling(r_ability, "Heal per Tick")

    def swain_bonus_health(unit: str, value: float) -> float | None:
        if unit == "% of his bonus health":
            return value / 100.0 * stats.get("bonus_health", 0.0)
        return None

    expected = sum_modifiers(
        heal_leveling, 3, stats, {}, modifier_override=swain_bonus_health
    )
    assert expected > 22.5, "AP ratio must raise the rank-3 heal"
    for heal in heals:
        assert heal["amount"] == pytest.approx(expected, abs=0.11)


def test_trundle_subjugate_heals_same_amount_as_pre_mitigation_drain():
    """Subjugate heals the pre-mitigation drain amount (same as its damage)."""
    # Subjugate "deal[s] magic damage and heal[s] himself for the same
    # amount" (data R effect[0]); Total Healing equals Total Magic Damage,
    # both a % of the target's maximum health. The heal does not pass
    # through magic resistance, so it equals the R event's pre-mitigation
    # damage.
    data = _fight("Trundle")
    heals = _main_heals(data, "Subjugate")
    assert heals, "Subjugate heal missing"
    events = _main_events(data)
    for heal in heals:
        event = events[heal["trigger_event_id"]]
        assert event["source"] == "R"
        assert heal["amount"] == pytest.approx(event["raw_damage"], abs=0.11)


def test_xin_zhao_wind_becomes_lightning_heals_third_of_lifesteal():
    """W damage heals 33.3% of Xin Zhao's lifesteal."""
    # "Wind Becomes Lightning's damage heals Xin Zhao for 33.3% of his life
    # steal" (data W effect[1]) — W damage applies lifesteal at 33.3%
    # effectiveness. Bloodthirster supplies the 15% lifesteal.
    data = _fight("XinZhao", lifesteal_item="Bloodthirster")
    heals = _main_heals(data, "Wind Becomes Lightning")
    assert heals, "Wind Becomes Lightning heal missing"
    events = _main_events(data)
    lifesteal = data["champion_stats"]["lifesteal_percent"]
    assert lifesteal == pytest.approx(15.0)
    for heal in heals:
        event = events[heal["trigger_event_id"]]
        assert event["source"] == "W"
        assert heal["amount"] == pytest.approx(
            0.333 * event["damage"] * lifesteal / 100.0, abs=0.11
        )
    # Without a lifesteal source the W heal is zero and must not emit.
    plain = _fight("XinZhao")
    assert not _main_heals(plain, "Wind Becomes Lightning")


def test_belveth_void_coral_heal_is_out_of_scope():
    """Bel'Veth's only self-heal is takedown-gated; no rule is authored."""
    # Endless Banquet's only self-heal fires when Bel'Veth consumes a Void
    # Coral, which requires a champion takedown; the 1v1 fight model
    # produces no deaths, so no rule is authored and no heal appears.
    data = _fight("Belveth")
    assert not data["combat"]["healing_events"]
