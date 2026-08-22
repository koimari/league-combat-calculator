"""Issue #46 acceptance: opening mitigation, spell shields, and Lifeline.

Every in-scope item must (a) resolve in a /api/calculate fight with a
sourced shield/reduction receipt and (b) certify in /api/bis for a fitting
champion (appear in the certified candidate list with complete sourced
event order), or be a documented exclusion.

Scope:
- Annul spell shields (Banshee's Veil, Edge of Night, Verdant Barrier).
- Celestial Opposition (Blessing of the Mountain incoming-damage reduction).
- Armored Advance (Plating basic-damage multiplier + Noxian reactive shield).
- Bloodthirster (Ichorshield starting state and overshield conversion).
- Sterak's Gage / Maw of Malmortius (Lifeline threshold shields) plus the
  Maw Lifeline omnivamp toggle.

Documented exclusion:
- Verdant Barrier is a tier-2 epic component of Banshee's Veil
  (data/items.json rank=EPIC, tier=2, buildsInto=Banshee's Veil).  The BIS
  candidate pool ranks only legendary items and boots, so Verdant Barrier
  can never be a BIS candidate; its Annul mechanic is covered by the
  /api/calculate ledger tests below.
"""

import pytest

from src import app as app_module
from tests.app_config import app_config

_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}

_AMBLESSA = {
    "champion": "Ambessa",
    "level": 18,
    "items": [],
    "role": "top",
    "ability_ranks": _RANKS,
}


@pytest.fixture(autouse=True)
def _disable_rate_limits():
    with app_config(RATE_LIMIT_ENABLED=False):
        yield


def _calculate(payload: dict) -> dict:
    response = app_module.app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def _bis(payload: dict) -> dict:
    response = app_module.app.test_client().post("/api/bis", json=payload)
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def _enemy(champion: str, **overrides) -> dict:
    enemy = {
        "champion": champion,
        "level": 18,
        "items": [],
        "role": "top",
        "ability_ranks": _RANKS,
    }
    enemy.update(overrides)
    return enemy


def _timed_bis(
    champion: str,
    role: str,
    *,
    slot_kind: str = "item",
    role_quest_complete: bool = False,
) -> dict:
    return _bis(
        {
            "champion": champion,
            "level": 18,
            "items": [],
            "boots": "",
            "role": role,
            "role_quest_complete": role_quest_complete,
            "ability_ranks": _RANKS,
            "champion_options": {},
            "fight_mode": "time_based",
            "fight_duration": 10,
            "include_auto_attacks": True,
            "auto_attack_uptime": 0.3,
            "subject_team": "main",
            "subject_index": 0,
            "slot_index": 0,
            "slot_kind": slot_kind,
            "enemies": [_AMBLESSA],
        }
    )


def _certified_names(body: dict) -> set[str]:
    return {row["name"] for row in body.get("candidates", [])}


# ── Annul spell shields ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("item", "blocked_source"),
    [
        ("Banshee's Veil", "Banshee's Veil — Annul"),
        ("Edge of Night", "Edge of Night — Annul"),
        ("Verdant Barrier", "Verdant Barrier — Annul"),
    ],
)
def test_annul_spell_shield_is_ready_and_blocks_one_typed_ability(item, blocked_source):
    """The shield is ready at fight start and consumes exactly one ability."""
    body = _calculate(
        {
            "champion": "Ziggs",
            "level": 18,
            "enemies": [_enemy("Kai'Sa", items=[item])],
        }
    )
    target = body["targets"][0]
    assert target["target"]["starting_defenses"]["spell_shield"] == {
        "ready": True,
        "source": blocked_source,
    }
    kaisa = next(
        row for row in body["combat"]["participants"] if row["champion"] == "Kai'Sa"
    )
    assert kaisa["survival"]["spell_shield_used"] is True
    blocked = [
        event
        for event in body["combat"]["events"]
        if event.get("skipped_reason") == "spell_shield"
    ]
    assert len(blocked) == 1
    assert all(event["spell_shield_source"] == blocked_source for event in blocked)


@pytest.mark.parametrize("item", ["Banshee's Veil", "Edge of Night"])
def test_annul_items_certify_in_bis(item):
    """The spell-shield legendaries are certified candidates for fitting roles."""
    body = _timed_bis("Ahri" if item == "Banshee's Veil" else "Talon", "mid")
    assert item in _certified_names(body)
    candidate = next(row for row in body["candidates"] if row["name"] == item)
    assert candidate["timeline_coverage"]["complete"] is True


def test_verdant_barrier_bis_exclusion_is_documented():
    """Verdant Barrier is a tier-2 epic component, not a BIS legendary.

    data/items.json ranks it EPIC tier 2 and it builds into Banshee's Veil;
    the BIS candidate pool only ranks legendary items and boots, so it is
    excluded by construction rather than withheld for a coverage failure.
    """
    from src.calculator.data_fetcher import get_item_by_name

    data = get_item_by_name("Verdant Barrier")
    assert "EPIC" in data["rank"]
    assert data["tier"] == 2
    # buildsInto stores numeric ids; 3102 is Banshee's Veil in data/items.json.
    assert 3102 in data.get("buildsInto", [])
    body = _timed_bis("Ahri", "mid")
    assert "Verdant Barrier" not in _certified_names(body)
    assert "Verdant Barrier" not in {
        row.get("name") for row in body.get("withheld_candidates", [])
    }


# ── Celestial Opposition ─────────────────────────────────────────────────────


def test_celestial_opposition_blessed_reduction_resolves_in_ledger():
    body = _calculate(
        {
            "champion": "Ziggs",
            "level": 18,
            "role": "support",
            "role_quest_complete": True,
            "enemies": [
                _enemy(
                    "Galio",
                    role="support",
                    role_quest_complete=True,
                    items=["Celestial Opposition"],
                )
            ],
        }
    )
    target = body["targets"][0]
    incoming = target["target"]["starting_defenses"]["incoming_damage"]
    assert incoming["incoming_damage_multiplier"] == pytest.approx(0.65)
    assert incoming["source"] == "Celestial Opposition — Blessed"
    reduced = [
        event
        for event in body["combat"]["events"]
        if event.get("incoming_damage_multiplier") == pytest.approx(0.65)
        and event.get("target") == "enemy:Galio"
    ]
    assert reduced
    assert all(
        event["incoming_damage_source"] == "Celestial Opposition — Blessed"
        for event in reduced
    )


def test_celestial_opposition_certifies_in_bis_for_support():
    body = _timed_bis("Sona", "support", role_quest_complete=True)
    assert body["certified_candidate_count"] > 0
    assert "Celestial Opposition" in _certified_names(body)


# ── Armored Advance ──────────────────────────────────────────────────────────


def test_armored_advance_plating_and_noxian_reactive_shield_resolve():
    body = _calculate(
        {
            "champion": "Aatrox",
            "level": 18,
            "role": "mid",
            "role_quest_complete": True,
            "fight_mode": "timed",
            "fight_duration": 5,
            "include_auto_attacks": True,
            "enemies": [
                _enemy(
                    "Galio",
                    role="mid",
                    role_quest_complete=True,
                    boots="Armored Advance",
                )
            ],
        }
    )
    target = body["targets"][0]
    incoming = target["target"]["starting_defenses"]["incoming_damage"]
    assert incoming["basic_damage_multiplier"] == pytest.approx(0.9)
    reactive = target["target"]["starting_defenses"]["reactive_shield"]
    assert reactive["amount"] > 0
    assert reactive["damage_type"] == "physical"
    triggered = [
        event
        for event in body["combat"]["events"]
        if event.get("reactive_shield_triggered")
    ]
    assert triggered
    receipt = triggered[0]["reactive_shield_triggered"]
    assert receipt["source"] == "Armored Advance — Noxian"
    assert receipt["damage_type"] == "physical"
    assert receipt["amount"] == pytest.approx(200.0)


def test_armored_advance_reduces_basic_attacks_in_fight():
    """Plating's 10% basic-damage multiplier must lower auto-attack packets."""

    def fight(boots: str | None) -> dict:
        enemy = _enemy("Galio", role="mid", role_quest_complete=True)
        if boots:
            enemy["boots"] = boots
        return _calculate(
            {
                "champion": "Aatrox",
                "level": 18,
                "role": "mid",
                "role_quest_complete": True,
                "fight_mode": "timed",
                "fight_duration": 5,
                "include_auto_attacks": True,
                "enemies": [enemy],
            }
        )

    plain = fight(None)
    plated = fight("Armored Advance")
    autos_plain = [
        event["damage"]
        for event in plain["combat"]["events"]
        if event.get("source") == "auto_attacks"
        and event.get("target") == "enemy:Galio"
    ]
    autos_plated = [
        event["damage"]
        for event in plated["combat"]["events"]
        if event.get("source") == "auto_attacks"
        and event.get("target") == "enemy:Galio"
    ]
    assert autos_plain and autos_plated
    # Same first-auto pair: Plating + extra armor must strictly reduce.
    assert autos_plated[0] < autos_plain[0] * 0.9


def test_armored_advance_certifies_in_bis_boots_for_mid():
    body = _timed_bis("Ahri", "mid", slot_kind="boots", role_quest_complete=True)
    assert "Armored Advance" in _certified_names(body)


# ── Bloodthirster ────────────────────────────────────────────────────────────


def test_bloodthirster_ichorshield_starting_state_and_overshield():
    body = _calculate(
        {
            "champion": "Ziggs",
            "level": 18,
            "enemies": [
                _enemy(
                    "Kai'Sa",
                    items=["Bloodthirster"],
                    item_options={"Bloodthirster": {"starting_ichorshield": 200}},
                )
            ],
        }
    )
    target = body["targets"][0]
    shield = target["target"]["starting_defenses"]["ichorshield"]
    assert shield["cap"] == pytest.approx(315.0)
    assert shield["starting"] == pytest.approx(200.0)
    assert target["target"]["starting_defenses"]["general_shield"] == pytest.approx(
        200.0
    )


def test_bloodthirster_overshield_converts_lifesteal_excess():
    body = _calculate(
        {
            "champion": "Aatrox",
            "level": 18,
            "items": ["Bloodthirster", "Blade of the Ruined King"],
            "fight_mode": "timed",
            "fight_duration": 8,
            "include_auto_attacks": True,
            "enemies": [_enemy("Galio")],
        }
    )
    generated = [
        event
        for event in body["combat"]["healing_events"]
        if event.get("ichorshield_generated") not in (None, 0.0)
    ]
    assert generated
    main = next(
        row for row in body["combat"]["participants"] if row["participant_id"] == "main"
    )
    assert main["survival"]["support_shield_received"] > 0
    assert generated[-1]["ichorshield_total"] <= 315.0


def test_bloodthirster_certifies_in_bis():
    body = _timed_bis("Aatrox", "top")
    assert "Bloodthirster" in _certified_names(body)


# ── Sterak's Gage / Maw of Malmortius ────────────────────────────────────────


@pytest.mark.parametrize(
    ("item", "expected_absorbed"),
    [("Sterak's Gage", 240.0), ("Maw of Malmortius", 290.0)],
)
def test_lifeline_threshold_shield_triggers_on_late_crossing(item, expected_absorbed):
    """Lifeline must arm on the threshold crossing at any fight time, not
    only within the first ``duration`` seconds (issue #46 gap)."""
    body = _calculate(
        {
            "champion": "Ziggs",
            "level": 18,
            "items": ["Rabadon's Deathcap", "Shadowflame", "Liandry's Torment"],
            "fight_mode": "timed",
            "fight_duration": 10,
            "enemies": [_enemy("Galio", items=[item])],
        }
    )
    target = body["targets"][0]
    assert target["target"]["starting_defenses"]["threshold_shield"]["amount"] == (
        expected_absorbed
    )
    assert target["result"]["threshold_shield_absorbed"] == expected_absorbed
    triggered = [
        event
        for event in body["combat"]["events"]
        if event.get("threshold_shield_triggered")
    ]
    assert triggered
    assert triggered[0]["time"] > 0.0  # crossed after the opening burst
    galio = next(
        row for row in body["combat"]["participants"] if row["champion"] == "Galio"
    )
    assert galio["survival"]["threshold_shield_triggered"] is True
    duration = target["target"]["starting_defenses"]["threshold_shield"]["duration"]
    assert galio["survival"]["threshold_shield_expired_at"] == pytest.approx(
        triggered[0]["time"] + duration
    )


def test_maw_lifeline_omnivamp_toggle_arms_after_trigger():
    body = _calculate(
        {
            "champion": "Ziggs",
            "level": 18,
            "items": ["Rabadon's Deathcap", "Shadowflame", "Liandry's Torment"],
            "fight_mode": "timed",
            "fight_duration": 10,
            "enemies": [_enemy("Galio", items=["Maw of Malmortius"])],
        }
    )
    target = body["targets"][0]
    assert target["target"]["starting_defenses"][
        "maw_lifeline_omnivamp_percent"
    ] == pytest.approx(10.0)
    triggered = [
        event
        for event in body["combat"]["events"]
        if event.get("maw_lifeline_omnivamp_activated")
    ]
    assert triggered
    assert triggered[0]["maw_lifeline_omnivamp_activated"] == pytest.approx(10.0)
    galio = next(
        row for row in body["combat"]["participants"] if row["champion"] == "Galio"
    )
    # Galio's post-trigger outgoing damage must heal from the temporary vamp.
    assert galio["survival"]["healing_received"] > 0


@pytest.mark.parametrize("item", ["Sterak's Gage", "Maw of Malmortius"])
def test_lifeline_items_certify_in_bis(item):
    body = _timed_bis("Aatrox", "top")
    assert item in _certified_names(body)
