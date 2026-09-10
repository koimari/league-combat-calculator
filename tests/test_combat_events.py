"""Authored casts retain time, recipient and resource boundaries."""

import pytest

from src.calculator.calculate import calculate_payload
from src.calculator.combat_events import parse_combat_events


def event(slot="E", time=2.0, recipient="enemy:Malphite", id="cast-1", caster="main"):
    return {
        "id": id,
        "time": time,
        "caster_id": caster,
        "slot": slot,
        "recipient_id": recipient,
    }


def payload(events):
    return calculate_payload(
        {
            "champion": "Lulu",
            "level": 18,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 20,
            "combat_events": events,
            "enemies": [
                {"champion": "Garen", "level": 18, "items": []},
                {"champion": "Malphite", "level": 18, "items": []},
            ],
            "allies": [
                {"champion": "Garen", "level": 18, "items": []},
                {"champion": "Ashe", "level": 18, "items": []},
            ],
        },
        deterministic=True,
    )


def test_selected_second_enemy_receives_the_cast():
    result = payload([event()])
    damage = [
        row
        for row in result["combat"]["events"]
        if row.get("attacker") == "main" and row.get("damage", 0) > 0
    ]
    assert len(damage) == 1
    assert damage[0]["target"] == "enemy:Malphite"
    assert damage[0]["time"] == 2
    assert result["combat"]["support_events"] == []
    assert result["cast_timeline"][0]["authored_event_id"] == "cast-1"


def test_repeated_e_switches_from_ally_to_enemy():
    result = payload([event(recipient="ally:Ashe"), event(time=12, id="cast-2")])
    shields = result["combat"]["support_events"]
    assert [(row["target"], row["time"]) for row in shields] == [("ally:Ashe", 2)]
    damage = [
        row
        for row in result["combat"]["events"]
        if row.get("attacker") == "main" and row.get("damage", 0) > 0
    ]
    assert [(row["target"], row["time"]) for row in damage] == [("enemy:Malphite", 12)]
    assert result["resource_spent"] == 160


def test_e_can_shield_the_caster():
    result = payload([event(recipient="main")])
    assert result["combat"]["support_events"][0]["target"] == "main"
    assert result["combat"]["support_events"][0]["amount"] == 230


def test_w_polymorphs_the_explicit_second_enemy():
    result = payload([event(slot="W")])
    rows = [
        row for row in result["combat"]["events"] if row.get("cc_kind") == "polymorph"
    ]
    assert len(rows) == 1
    assert rows[0]["target"] == "enemy:Malphite"
    assert rows[0]["time"] == 2


def test_empty_events_casts_no_spells():
    assert payload([])["cast_timeline"] == []


@pytest.mark.parametrize(
    "events, message",
    [
        ([event(), event(time=3, id="cast-2")], "cooldown"),
        ([event(time=20)], "fight end"),
        ([event(recipient="missing")], "must exist"),
        ([event(caster="missing")], "must exist"),
        ([event(), event(id="cast-1", time=12)], "unique"),
        ([event(time=float("nan"))], "finite"),
        ([event(time=True)], "finite"),
    ],
)
def test_invalid_authored_events_fail_closed(events, message):
    with pytest.raises(ValueError, match=message):
        payload(events)


def test_absence_keeps_the_derived_schedule_contract():
    assert parse_combat_events(None) is None
    assert parse_combat_events([]) == ()


def attack_payload(events):
    return calculate_payload(
        {
            "champion": "Lulu",
            "level": 18,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 20,
            "include_auto_attacks": True,
            "auto_attack_uptime_mode": "explicit",
            "auto_attack_uptime": 1,
            "combat_events": events,
            "enemies": [
                {
                    "champion": "Garen",
                    "level": 18,
                    "items": [],
                    "include_auto_attacks": False,
                }
            ],
            "allies": [
                {
                    "champion": "Ashe",
                    "level": 18,
                    "items": [],
                    "include_auto_attacks": True,
                    "auto_attack_uptime_mode": "explicit",
                    "auto_attack_uptime": 1,
                }
            ],
        },
        deterministic=True,
    )


def autos_for(result, actor):
    return [
        row
        for row in result["combat"]["events"]
        if row["attacker"] == actor and row["source"] == "auto_attacks"
    ]


def test_w_increases_only_the_selected_allies_attack_cadence():
    baseline = attack_payload([])
    buffed = attack_payload([event(slot="W", recipient="ally:Ashe")])
    assert len(autos_for(baseline, "ally:Ashe")) == 19
    assert len(autos_for(buffed, "ally:Ashe")) == 20
    assert [row["time"] for row in autos_for(buffed, "main")] == [
        row["time"] for row in autos_for(baseline, "main")
    ]
    assert [row["time"] for row in autos_for(buffed, "ally:Ashe")[:2]] == [
        row["time"] for row in autos_for(baseline, "ally:Ashe")[:2]
    ]
    support = buffed["combat"]["support_events"][0]
    assert support["bonus_attack_speed_percent"] == 30
    assert support["expires_at"] == 6


def test_r_grants_temporary_health_to_the_chosen_ally():
    result = attack_payload([event(slot="R", recipient="ally:Ashe")])
    support = result["combat"]["support_events"][0]
    assert support["kind"] == "temporary_health"
    assert support["target"] == "ally:Ashe"
    assert support["amount"] == 575
    assert support["expires_at"] == 9


def test_r_rejects_an_enemy_recipient():
    with pytest.raises(ValueError, match="friendly recipient"):
        payload([event(slot="R")])


def test_a_disabled_lulu_cannot_grant_an_attack_speed_window():
    body = {
        "champion": "Lulu",
        "level": 18,
        "items": [],
        "fight_mode": "time_based",
        "fight_duration": 10,
        "include_auto_attacks": True,
        "auto_attack_uptime_mode": "explicit",
        "auto_attack_uptime": 1,
        "allies": [
            {
                "champion": "Ashe",
                "level": 18,
                "items": [],
                "include_auto_attacks": True,
                "auto_attack_uptime_mode": "explicit",
                "auto_attack_uptime": 1,
            }
        ],
        "enemies": [
            {
                "champion": "Lulu",
                "level": 18,
                "items": [],
                "include_auto_attacks": False,
            }
        ],
    }
    disable = event(
        slot="W", time=0, recipient="main", caster="enemy:Lulu", id="disable"
    )
    baseline = calculate_payload(
        {**body, "combat_events": [disable]}, deterministic=True
    )
    attempted = calculate_payload(
        {
            **body,
            "combat_events": [disable, event(slot="W", time=1, recipient="ally:Ashe")],
        },
        deterministic=True,
    )
    assert (
        attempted["combat"]["support_events"][0]["skipped_reason"]
        == "attacker_state_blocked"
    )
    assert [row["time"] for row in autos_for(attempted, "ally:Ashe")] == [
        row["time"] for row in autos_for(baseline, "ally:Ashe")
    ]


def test_a_dead_lulu_cannot_grant_a_buff():
    result = calculate_payload(
        {
            "champion": "Ashe",
            "level": 18,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 10,
            "include_auto_attacks": True,
            "auto_attack_uptime_mode": "explicit",
            "auto_attack_uptime": 1,
            "allies": [
                {
                    "champion": "Lulu",
                    "level": 18,
                    "items": [],
                    "current_health": 1,
                    "ally_effects_enabled": True,
                    "include_auto_attacks": False,
                }
            ],
            "enemies": [
                {
                    "champion": "Garen",
                    "level": 18,
                    "items": [],
                    "include_auto_attacks": True,
                    "auto_attack_uptime_mode": "explicit",
                    "auto_attack_uptime": 1,
                }
            ],
            "combat_events": [event(slot="W", recipient="main", caster="ally:Lulu")],
        },
        deterministic=True,
    )
    assert result["combat"]["support_events"][0]["skipped_reason"] == "attacker_dead"


def test_empty_overrides_preserves_the_learned_spell_schedule():
    body = {
        "champion": "Lulu",
        "level": 18,
        "items": [],
        "fight_mode": "time_based",
        "fight_duration": 10,
        "enemies": [{"champion": "Garen", "level": 18, "items": []}],
    }
    baseline = calculate_payload(body, deterministic=True)
    authored = calculate_payload(
        {**body, "combat_events": [], "combat_events_mode": "overrides"},
        deterministic=True,
    )
    assert authored["cast_timeline"] == baseline["cast_timeline"]
    assert authored["combat"]["events"] == baseline["combat"]["events"]


def test_overrides_preserves_other_casters_spells():
    result = calculate_payload(
        {
            "champion": "Lulu",
            "level": 18,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 10,
            "combat_events_mode": "overrides",
            "combat_events": [event(recipient="enemy:Garen")],
            "enemies": [{"champion": "Garen", "level": 18, "items": []}],
        },
        deterministic=True,
    )
    assert [(cast["slot"], cast["time"]) for cast in result["cast_timeline"]] == [
        ("E", 2)
    ]
    assert any(
        row["attacker"] == "enemy:Garen" and row["source"] != "auto_attacks"
        for row in result["combat"]["events"]
    )


def test_certified_nasus_w_targets_the_selected_enemy():
    result = calculate_payload(
        {
            "champion": "Nasus",
            "level": 18,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 10,
            "combat_events_mode": "overrides",
            "combat_events": [event(slot="W")],
            "enemies": [
                {"champion": "Garen", "level": 18, "items": []},
                {"champion": "Malphite", "level": 18, "items": []},
            ],
        },
        deterministic=True,
    )
    rows = [row for row in result["combat"]["events"] if row["attacker"] == "main"]
    assert [(row["target"], row["cc_kind"], row["time"]) for row in rows] == [
        ("enemy:Malphite", "slow", 2)
    ]


def test_uncertified_slots_fail_instead_of_ignoring_authored_time():
    with pytest.raises(ValueError, match="certification"):
        calculate_payload(
            {
                "champion": "Ashe",
                "level": 18,
                "items": [],
                "combat_events": [event(slot="Q")],
            },
            deterministic=True,
        )


@pytest.mark.parametrize("champion", ["Elise", "Rammus", "Zilean", "Vayne"])
def test_reviewed_single_target_slots_route_to_the_selected_enemy(champion):
    body = {
        "champion": champion,
        "level": 18,
        "items": [],
        "fight_mode": "time_based",
        "fight_duration": 10,
        "champion_options": {"condemn_wall": True} if champion == "Vayne" else {},
        "combat_events_mode": "overrides",
        "combat_events": [event()],
        "enemies": [
            {"champion": "Garen", "level": 18, "items": []},
            {"champion": "Malphite", "level": 18, "items": []},
        ],
    }
    result = calculate_payload(body, deterministic=True)
    rows = [row for row in result["combat"]["events"] if row["attacker"] == "main"]
    assert rows
    assert {row["target"] for row in rows} == {"enemy:Malphite"}
    assert any(row.get("cc_kind") for row in rows)
    with pytest.raises(ValueError, match="friendly-target"):
        calculate_payload(
            {**body, "combat_events": [event(recipient="main")]}, deterministic=True
        )


def ashe_q_body():
    return {
        "champion": "Ashe",
        "level": 18,
        "items": [],
        "ability_ranks": {"Q": 1, "W": 1, "E": 0, "R": 0},
        "fight_mode": "time_based",
        "fight_duration": 20,
        "include_auto_attacks": True,
        "auto_attack_uptime_mode": "explicit",
        "auto_attack_uptime": 1,
        "enemies_attack": False,
        "combat_events_mode": "overrides",
        "allies": [
            {
                "champion": "Lulu",
                "level": 18,
                "items": [],
                "ability_ranks": {"Q": 0, "W": 1, "E": 1, "R": 1},
                "ally_effects_enabled": True,
                "include_auto_attacks": False,
            }
        ],
        "enemies": [
            {"champion": "Garen", "level": 18, "items": []},
            {"champion": "Jinx", "level": 18, "items": []},
        ],
    }


def ashe_garen_autos(result):
    return [row for row in autos_for(result, "main") if row["target"] == "enemy:Garen"]


def test_ashe_q_and_whimsy_preserve_each_cast_window():
    body = ashe_q_body()
    baseline = calculate_payload(
        {
            **body,
            "combat_events": [
                event(slot="W", recipient="enemy:Garen", caster="ally:Lulu")
            ],
        },
        deterministic=True,
    )
    buffed = calculate_payload(
        {
            **body,
            "combat_events": [event(slot="W", recipient="main", caster="ally:Lulu")],
        },
        deterministic=True,
    )
    base_autos, buffed_autos = ashe_garen_autos(baseline), ashe_garen_autos(buffed)
    assert len(base_autos) == 19
    assert len(buffed_autos) == 20
    assert [
        (row["time"], row["pair_damage"]) for row in buffed_autos if row["time"] < 2
    ] == [(row["time"], row["pair_damage"]) for row in base_autos if row["time"] < 2]
    assert [
        (row["time"], row["pair_damage"]) for row in buffed_autos if row["time"] >= 6
    ] == [(row["time"], row["pair_damage"]) for row in base_autos if row["time"] >= 6]
    assert buffed["cast_timeline"] == baseline["cast_timeline"]


def test_whimsy_can_continue_after_ashe_q_expires():
    body = ashe_q_body()
    result = calculate_payload(
        {
            **body,
            "combat_events": [
                event(slot="W", time=5, recipient="main", caster="ally:Lulu")
            ],
        },
        deterministic=True,
    )
    rows = ashe_garen_autos(result)
    flurry = [row for row in rows if row["time"] < 6]
    after_q = [row for row in rows if 6 <= row["time"] < 8]
    after_w = [row for row in rows if row["time"] >= 8]
    assert flurry and len(after_q) >= 2 and len(after_w) >= 2
    assert flurry[-1]["pair_damage"] > after_q[0]["pair_damage"]
    assert after_q[0]["pair_damage"] == after_w[0]["pair_damage"]
    assert (
        after_q[1]["time"] - after_q[0]["time"]
        < after_w[1]["time"] - after_w[0]["time"]
    )


def test_a_blocked_whimsy_preserves_the_original_ashe_q_schedule():
    body = ashe_q_body()
    body["enemies_attack"] = True
    body["enemies"] = [
        {"champion": "Lulu", "level": 18, "items": [], "include_auto_attacks": False}
    ]
    disable = event(
        slot="W", time=0, recipient="ally:Lulu", caster="enemy:Lulu", id="disable"
    )
    later_shield = event(
        slot="E", time=9, recipient="ally:Lulu", caster="ally:Lulu", id="shield"
    )
    baseline = calculate_payload(
        {**body, "combat_events": [disable, later_shield]}, deterministic=True
    )
    blocked = calculate_payload(
        {
            **body,
            "combat_events": [
                disable,
                event(slot="W", time=1, recipient="main", caster="ally:Lulu"),
                later_shield,
            ],
        },
        deterministic=True,
    )
    assert [
        (row["time"], row["pair_damage"]) for row in autos_for(blocked, "main")
    ] == [(row["time"], row["pair_damage"]) for row in autos_for(baseline, "main")]
    support = next(
        row
        for row in blocked["combat"]["support_events"]
        if row["event_id"] == "authored:cast-1:support"
    )
    assert support["skipped_reason"] == "attacker_state_blocked"
