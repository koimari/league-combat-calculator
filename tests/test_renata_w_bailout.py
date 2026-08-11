"""Focused Renata W Bailout source and runtime contract matrix.

Live tests pin the cached source, typed atoms, API validation, and Renata E
ally-support regressions. Unsupported W runtime behavior uses strict xfails.
"""

import json
from pathlib import Path

import pytest

from src import app as app_module
from src.calculator import ability_atoms
from src.calculator.ability_atoms import (
    AbilityAtomQuery,
    required_ability_atom,
    required_ranked_attribute_atom,
)
from src.calculator.champions import renata_glasc
from src.calculator.data_fetcher import get_champion
from src.calculator.defensive_effects import resolve_starting_defenses
from src.calculator.participant_timeline import build_participant_timeline
from src.calculator.pipeline import FightParams
from src.calculator.scenario import ChampionLoadout
from src.calculator.stats import calculate_total_stats
from src.calculator.support_effects import derive_ally_effects

CHAMPION = "Renata Glasc"
ATOM_CHAMPION = "Renata"
BAILOUT = "Bailout"
W_SOURCE = {
    "label": "Renata Glasc W ability entry",
    "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Renata_Glasc/W",
    "revision_id": 3394722,
    "revision_timestamp": "2022-02-02T01:32:47Z",
}
ROOT = Path(__file__).resolve().parents[1]


def awaiting(detail):
    return pytest.mark.xfail(reason=f"awaiting P1-Renata-W {detail}", strict=True)


def _w_ability():
    return get_champion(CHAMPION)["abilities"]["W"][0]


def _w_effects(*, ap=100.0):
    return derive_ally_effects(
        get_champion(CHAMPION),
        18,
        {"ability_power": ap, "bonus_attack_damage": 0.0, "health": 2000.0},
        [{"slot": "W", "time": 0.0}],
        ability_ranks={"W": 5},
    )


def _bailout_effect():
    return next(effect for effect in _w_effects() if BAILOUT in effect["source"])


def _calculate(payload):
    previous = app_module.app.config.get("TESTING")
    app_module.app.config["TESTING"] = True
    try:
        return app_module.app.test_client().post("/api/calculate", json=payload)
    finally:
        if previous is None:
            app_module.app.config.pop("TESTING", None)
        else:
            app_module.app.config["TESTING"] = previous


def _lethal_payload(*, duration=4.0, items=None):
    return {
        "champion": CHAMPION,
        "level": 1,
        "items": items or [],
        "fight_mode": "time_based",
        "fight_duration": duration,
        "include_auto_attacks": False,
        "ability_ranks": {"Q": 0, "W": 1, "E": 0, "R": 0},
        "enemies": [
            {
                "champion": "Caitlyn",
                "level": 18,
                "items": [
                    "Infinity Edge",
                    "The Collector",
                    "Bloodthirster",
                    "Phantom Dancer",
                    "Kraken Slayer",
                ],
                "ability_ranks": {"Q": 0, "W": 0, "E": 0, "R": 3},
            }
        ],
    }


def _combat(payload):
    response = _calculate(payload)
    assert response.status_code == 200, response.get_data(as_text=True)[:500]
    return response.get_json()["combat"]


def _main_survival(combat):
    return next(
        row["survival"]
        for row in combat["participants"]
        if row["participant_id"] == "main"
    )


def _bailout_public_events(combat):
    return [
        event
        for event in combat.get("support_events", [])
        if BAILOUT in str(event.get("source", ""))
    ]


def test_cached_w_source_pins_all_behavior_numbers_and_precedence():
    ability = _w_ability()
    active = ability["effects"][0]["description"]
    lethal = ability["effects"][1]["description"]
    assert ability["name"] == BAILOUT
    assert ability["targeting"] == "Unit"
    assert "for 5 seconds" in active
    assert "duration resets whenever the target scores a takedown" in active
    assert "restored to 100% of their maximum health" in lethal
    assert "10% of their maximum health every 0.264 seconds" in lethal
    assert "setting their current health to 20%" in lethal
    assert "only once per application" in lethal
    assert (
        "takes priority over all  resurrection and  zombie state effects"
        in ability["notes"]
    )


def test_module_and_api_expose_the_exact_w_source_receipt():
    assert W_SOURCE in renata_glasc.SOURCES
    previous = app_module.app.config.get("TESTING")
    app_module.app.config["TESTING"] = True
    try:
        metadata = app_module.app.test_client().get("/api/config").get_json()
    finally:
        if previous is None:
            app_module.app.config.pop("TESTING", None)
        else:
            app_module.app.config["TESTING"] = previous
    assert W_SOURCE in metadata["champion_options"][CHAMPION]["sources"]


@pytest.mark.parametrize(
    "attribute,modifier,rank_value,values,atom_hash",
    [
        ("Bonus Attack Speed", 0, 30.0, [10, 15, 20, 25, 30], "733a5a24f38dc26c"),
        ("Bonus Attack Speed", 1, 1.0, [1, 1, 1, 1, 1], "cfeff805cd148975"),
        (
            "Maximum Bonus Attack Speed",
            0,
            60.0,
            [20, 30, 40, 50, 60],
            "7f9f7776c16e680a",
        ),
        ("Maximum Bonus Attack Speed", 1, 2.0, [2, 2, 2, 2, 2], "2bdd5c756458eec6"),
        ("Bonus Movement Speed", 0, 20.0, [10, 12.5, 15, 17.5, 20], "99ba929b7fe59e56"),
        ("Bonus Movement Speed", 1, 1.0, [1, 1, 1, 1, 1], "a38082eea2c2d5bd"),
        (
            "Maximum Bonus Movement Speed",
            0,
            40.0,
            [20, 25, 30, 35, 40],
            "a401bc4135d356d9",
        ),
        ("Maximum Bonus Movement Speed", 1, 2.0, [2, 2, 2, 2, 2], "941ed3f7d59fe1b9"),
    ],
)
def test_ranked_w_atoms_have_exact_values_and_receipts(
    attribute, modifier, rank_value, values, atom_hash
):
    value, atom = required_ranked_attribute_atom(
        ATOM_CHAMPION,
        get_champion(CHAMPION),
        "W",
        attribute,
        5,
        modifier_index=modifier,
    )
    assert value == pytest.approx(rank_value)
    assert atom["values"] == values
    assert atom["evidence"] == [f"{attribute}@effects[0]"]
    assert atom["hash"] == atom_hash


def test_w_duration_atom_has_exact_source_and_hash():
    atom = required_ability_atom(
        ATOM_CHAMPION,
        get_champion(CHAMPION),
        "W",
        query=AbilityAtomQuery(
            source="Renata.W[0].effects[0].description",
            behavior="timing",
            evidence_prefix="active duration@",
        ),
    )
    assert atom["values"] == [5.0]
    assert atom["units"] == ["s"]
    assert atom["evidence"] == ["active duration@effects[0].description"]
    assert atom["hash"] == "17012927ccec19a4"


def test_module_fails_closed_on_the_local_burn_authority_conflict():
    authority = renata_glasc.BAILOUT_AUTHORITY
    assert authority["runtime_available"] is False
    assert authority["reason"] == "burn_authority_conflict"
    assert authority["wiki_burn_interval_seconds"] == pytest.approx(0.264)
    assert authority["gamefile_ticks_per_second"] == pytest.approx(4.0)
    assert authority["wiki_description_damage_class"] == "true"
    assert authority["wiki_notes_damage_class"] == "raw"
    assert authority["gamefile_path"] == "data/bin/characters/renata.bin.json"
    assert authority["gamefile_sha256"].startswith("9f6ffc8c07f63734")
    assert renata_glasc.MODULE_COVERAGE["W"] == "out_of_scope"


def test_game_binary_pins_the_conflicting_four_ticks_per_second():
    path = ROOT / renata_glasc.BAILOUT_AUTHORITY["gamefile_path"]
    if not path.exists():
        pytest.skip("local Renata game-file evidence is unavailable")
    payload = json.loads(path.read_text(encoding="utf-8"))
    spell = payload["Characters/Renata/Spells/RenataWAbility/RenataW"]["mSpell"]
    values = {entry["name"]: entry["values"] for entry in spell["DataValues"]}
    assert values["TicksPerSecond"] == [4.0] * 7
    assert values["TicksBeforeDeath"] == [10.0] * 7
    assert values["TriumphPercent"] == [20.0] * 7
    assert values["TagDuration"] == [6.0] * 7


@pytest.mark.parametrize("case", ["missing", "empty", "malformed"])
def test_w_atom_access_fails_closed_for_missing_or_malformed_values(monkeypatch, case):
    query = AbilityAtomQuery(
        source="Renata.W[0].effects[0].leveling[0].modifiers[0]",
        behavior="ability",
        evidence_prefix="Bonus Attack Speed@",
    )
    if case == "missing":
        rows = {"W": ()}
        expected = KeyError
    else:
        atom = {
            "source": query.source,
            "behavior": query.behavior,
            "evidence": ["Bonus Attack Speed@effects[0]"],
            "values": [] if case == "empty" else ["30"],
            "units": [] if case == "empty" else ["%"],
        }
        rows = {"W": (atom,)}
        expected = ValueError if case == "empty" else TypeError
    monkeypatch.setattr(ability_atoms, "_ability_atoms", lambda *_args: rows)
    with pytest.raises(expected, match="ability atom"):
        required_ability_atom(ATOM_CHAMPION, {}, "W", query=query)


def test_existing_renata_e_ally_support_packet_remains_intact():
    effects = derive_ally_effects(
        get_champion(CHAMPION),
        18,
        {"ability_power": 100.0, "bonus_attack_damage": 0.0, "health": 2000.0},
        [{"slot": "E", "time": 1.0}],
        ability_ranks={"E": 5},
    )
    shield = next(event for event in effects if event["kind"] == "shield")
    assert shield["source"] == "Loyalty Program · Shield Strength"
    assert shield["amount"] == pytest.approx(160.0)
    assert shield["duration"] == pytest.approx(3.0)
    assert shield["target_scope"] == "all_teammates"


@pytest.mark.parametrize(
    "selections",
    [[], {"buff:W:0": "0"}, {"buff:W:0": 5}],
)
def test_api_rejects_malformed_support_target_selections(selections):
    payload = _lethal_payload()
    payload["support_target_selections"] = selections
    response = _calculate(payload)
    assert response.status_code == 400
    assert "support_target_selections" in response.get_json()["error"]


@awaiting("option and target admission")
def test_w_packet_admits_self_or_one_selected_ally():
    effect = _bailout_effect()
    assert effect["target_self"] is True
    assert effect["target_scope"] == "one_teammate"
    assert effect["target_selection_key"]


@awaiting("movement and attack speed buff packets")
def test_w_rank_five_at_100_ap_exposes_initial_and_maximum_buff_values():
    effect = _bailout_effect()
    assert effect["bonus_attack_speed_percent"] == pytest.approx(31.0)
    assert effect["maximum_bonus_attack_speed_percent"] == pytest.approx(62.0)
    assert effect["bonus_move_speed_percent"] == pytest.approx(21.0)
    assert effect["maximum_bonus_move_speed_percent"] == pytest.approx(42.0)


@awaiting("five-second duration and takedown refresh")
def test_w_packet_receipts_duration_and_takedown_refresh_rule():
    effect = _bailout_effect()
    assert effect["duration"] == pytest.approx(5.0)
    assert effect["refresh_duration"] == pytest.approx(5.0)
    assert effect["refresh_trigger"] == "takedown_within_6_seconds"


@awaiting("lethal trigger and sourced full-health restore")
def test_lethal_damage_triggers_bailout_and_restores_full_health():
    combat = _combat(_lethal_payload())
    survival = _main_survival(combat)
    assert _bailout_public_events(combat)
    assert survival["revived"] is True
    assert BAILOUT in survival["revive_source"]
    assert survival["revive_health_restored"] == pytest.approx(survival["max_health"])


@awaiting("0.264-second true-damage burn and failed-takedown death")
def test_failed_takedown_burns_ten_ticks_then_kills_the_target():
    combat = _combat(_lethal_payload())
    ticks = [
        event
        for event in combat["events"]
        if BAILOUT in str(event.get("source", ""))
        and float(event.get("damage", 0.0)) > 0.0
    ]
    assert [event["time"] for event in ticks] == pytest.approx(
        [0.264 * index for index in range(1, 11)], abs=1e-3
    )
    assert all(event["damage_type"] == "true" for event in ticks)
    assert all(event["damage"] == pytest.approx(54.5) for event in ticks)
    assert _main_survival(combat)["terminal_phase"] == "dead"


@awaiting("successful takedown burn stop and 20-percent survival")
def test_successful_takedown_stops_burn_and_sets_twenty_percent_health():
    effect = _bailout_effect()
    assert effect["takedown_stops_burn"] is True
    assert effect["takedown_health_ratio"] == pytest.approx(0.20)


@awaiting("one lethal activation per Bailout application")
def test_one_application_can_trigger_the_restore_only_once():
    events = _bailout_public_events(_combat(_lethal_payload()))
    triggers = [event for event in events if event.get("trigger") == "lethal_damage"]
    assert len(triggers) == 1
    assert triggers[0]["activation_count"] == 1


@awaiting("resurrection precedence")
def test_bailout_takes_priority_over_guardian_angel_resurrection():
    combat = _combat(_lethal_payload(duration=3.2, items=["Guardian Angel"]))
    survival = _main_survival(combat)
    assert BAILOUT in survival["revive_source"]
    assert "Guardian Angel" not in survival["revive_source"]


@awaiting("zombie-state precedence")
def test_bailout_takes_priority_over_a_supported_zombie_state():
    payload = _lethal_payload()
    payload["champion"] = "Sion"
    payload["ability_ranks"] = {"Q": 0, "W": 0, "E": 0, "R": 0}
    payload["allies"] = [
        {
            "champion": CHAMPION,
            "level": 1,
            "items": [],
            "ally_effects_enabled": True,
            "ability_ranks": {"Q": 0, "W": 1, "E": 0, "R": 0},
        }
    ]
    combat = _combat(payload)
    assert any(event["target"] == "main" for event in _bailout_public_events(combat))
    assert BAILOUT in _main_survival(combat)["revive_source"]


@awaiting("roster target-current-health input")
def test_roster_loadout_accepts_a_bounded_target_current_health_input():
    loadout = ChampionLoadout.from_request(
        {"champion": "Caitlyn", "level": 1, "current_health": 100.0},
        field="enemies[0]",
    )
    assert loadout.current_health == pytest.approx(100.0)


@awaiting("target-health API validation")
def test_api_rejects_malformed_roster_target_current_health():
    payload = _lethal_payload()
    payload["enemies"][0]["current_health"] = "low"
    response = _calculate(payload)
    assert response.status_code == 400
    assert "current_health" in response.get_json()["error"]


@awaiting("W score-versus-receipt parity")
def test_w_score_path_matches_receipt_path_on_bailout_survival_fields():
    champion = get_champion(CHAMPION)
    stats = calculate_total_stats(champion, 1, [])
    params = FightParams.from_request(
        {
            "fight_mode": "time_based",
            "fight_duration": 4.0,
            "include_auto_attacks": False,
            "ability_ranks": {"Q": 0, "W": 1, "E": 0, "R": 0},
        },
        deterministic=True,
    )
    enemy = ChampionLoadout(
        champion="Caitlyn",
        level=18,
        items=("Infinity Edge", "The Collector", "Bloodthirster"),
        ability_ranks={"Q": 0, "W": 0, "E": 0, "R": 3},
    ).resolve()
    kwargs = {
        "main_stats": stats,
        "main_defenses": resolve_starting_defenses(CHAMPION, 1, stats, []),
        "enemies": [enemy],
        "allies": [],
    }
    receipt = build_participant_timeline(
        champion, 1, [], params, include_receipt=True, **kwargs
    )
    score = build_participant_timeline(
        champion, 1, [], params, include_receipt=False, **kwargs
    )
    receipt_survival = _main_survival(receipt)
    score_survival = _main_survival(score)
    assert BAILOUT in receipt_survival["revive_source"]
    for key in (
        "revived",
        "revive_health_restored",
        "revive_source",
        "first_death_time",
        "death_time",
        "terminal_phase",
    ):
        assert score_survival[key] == receipt_survival[key]
