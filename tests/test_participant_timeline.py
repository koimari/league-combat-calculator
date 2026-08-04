"""Regression coverage for coupled participant combat receipts."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.pipeline import FightParams, run_fight
from src.calculator.defensive_effects import resolve_starting_defenses
from src.calculator.scenario import ChampionLoadout
from src.calculator.stats import calculate_total_stats
from src.app import _enemy_bis_rank_key, _role_scoped_bis_candidates, app
from src.calculator.item_coverage import optimizer_supported_items
from src.calculator.optimizer import get_eligible_legendaries
from src.calculator.participant_timeline import (
    Combatant,
    CoupledSearchContext,
    _actor_params,
    _schedule_authored_reactive_events,
    _schedule_thorns_events,
    _compiled_survival_walk,
    _simulate_survival,
    build_participant_timeline,
)


def test_roster_actor_without_cast_order_uses_module_default_not_main_override():
    base = FightParams.from_request(
        {
            "fight_mode": "time_based",
            "fight_duration": 3,
            "cast_order": ["R", "Q", "W", "E"],
            "item_options": {"Heartsteel": {"bonus_health": 500}},
        }
    )
    actor = Combatant(
        participant_id="ally:Taliyah",
        team="ally",
        champion_data={"name": "Taliyah"},
        level=18,
        items=(),
        stats={},
        defenses=None,
        request=type(
            "RosterRequest",
            (),
            {
                "role": "",
                "role_quest_complete": False,
                "ability_ranks": {},
                "champion_options": {},
                "item_options": {"Heartsteel": {"bonus_health": 700}},
            },
        )(),
    )

    assert _actor_params(base, actor).cast_order is None
    assert _actor_params(base, actor).item_options == {
        "Heartsteel": {"bonus_health": 700}
    }
    actor_without_options = Combatant(
        participant_id="ally:Vi",
        team="ally",
        champion_data={"name": "Vi"},
        level=18,
        items=(),
        stats={},
        defenses=None,
        request=type(
            "RosterRequestWithoutOptions",
            (),
            {"role": "", "role_quest_complete": False},
        )(),
    )
    assert _actor_params(base, actor_without_options).item_options is None


def test_frozen_heart_target_aura_reduces_main_swing_schedule():
    app.config["TESTING"] = True
    payload = {
        "champion": "Ahri",
        "level": 18,
        "items": [],
        "fight_mode": "auto_only",
        "fight_duration": 10,
        "auto_attacks_only": True,
        "include_auto_attacks": True,
        "auto_attack_uptime": 1.0,
        "enemies": [{"champion": "Aatrox", "level": 18, "items": []}],
    }
    baseline = app.test_client().post("/api/calculate", json=payload)
    payload["enemies"][0]["items"] = ["Frozen Heart"]
    crippled = app.test_client().post("/api/calculate", json=payload)

    assert baseline.status_code == crippled.status_code == 200
    baseline_events = [
        event
        for event in baseline.get_json()["combat"]["events"]
        if event["attacker"] == "main"
    ]
    crippled_events = [
        event
        for event in crippled.get_json()["combat"]["events"]
        if event["attacker"] == "main"
    ]
    assert len(crippled_events) < len(baseline_events)
    assert len(crippled_events) == 7


def test_guardian_angel_revives_target_after_first_lethal_packet():
    main = get_champion("Ahri")
    main_stats = calculate_total_stats(main, 18, [])
    params = FightParams.from_request(
        {
            "fight_mode": "auto_only",
            "fight_duration": 4.1,
            "auto_attacks_only": True,
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
        },
        deterministic=True,
    )
    enemy = ChampionLoadout(
        champion="Aatrox", level=18, items=("Guardian Angel",)
    ).resolve()
    enemy_stats = dict(enemy.stats)
    enemy_stats.update(
        health=100.0,
        base_health=200.0,
        bonus_health=0.0,
        armor=0.0,
        magic_resistance=0.0,
    )
    enemy = replace(enemy, stats=enemy_stats)

    result = build_participant_timeline(
        main,
        18,
        [],
        params,
        main_stats=main_stats,
        main_defenses=resolve_starting_defenses("Ahri", 18, main_stats, []),
        enemies=[enemy],
        allies=[],
    )

    survival = result["participants"][1]["survival"]
    assert survival["first_death_time"] is not None
    assert survival["revived"] is True
    assert survival["revive_time"] == pytest.approx(
        survival["first_death_time"] + 4.0, abs=1e-3
    )
    assert survival["revive_health_restored"] == pytest.approx(100.0)
    assert survival["terminal_phase"] == "revived"


def test_protoplasm_reprices_delayed_target_max_health_ticks_in_coupled_walk():
    """Galio's delayed Q ticks use the target's temporary live maximum health."""
    main = get_champion("Galio")
    main_stats = calculate_total_stats(main, 11, [])
    params = FightParams.from_request(
        {
            "fight_mode": "one_rotation",
            "ability_ranks": {"Q": 3, "W": 0, "E": 0, "R": 0},
            "champion_options": {
                "passive_procs": 0,
                "w_charge_seconds": 1.25,
                "e_dash_distance": 650.0,
            },
        },
        deterministic=True,
    )
    enemy = ChampionLoadout(
        champion="Shen", level=12, items=("Protoplasm Harness",)
    ).resolve()
    enemy_stats = dict(enemy.stats)
    enemy_stats.update(
        health=200.0,
        bonus_health=0.0,
        armor=0.0,
        magic_resistance=0.0,
    )
    enemy = replace(enemy, stats=enemy_stats)

    result = build_participant_timeline(
        main,
        11,
        [],
        params,
        main_stats=main_stats,
        main_defenses=resolve_starting_defenses("Galio", 11, main_stats, []),
        enemies=[enemy],
        allies=[],
    )

    survival = result["participants"][1]["survival"]
    q_events = [
        event
        for event in result["events"]
        if event["attacker"] == "main" and event["source"] == "Q"
    ]
    assert survival["threshold_health_triggered"] is True
    assert survival["max_health"] == pytest.approx(429.4)
    assert [event["damage"] for event in q_events] == pytest.approx(
        [140.0, 8.6, 18.4, 18.4, 18.4]
    )


def test_darius_decimate_self_heal_coalesces_targets_in_both_walks():
    """Decimate heals once per cast at 17% per target champion hit."""
    champion = get_champion("Darius")
    params = FightParams.from_request(
        {
            "fight_mode": "one_rotation",
            "ability_ranks": {"Q": 5, "W": 0, "E": 0, "R": 0},
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
        },
        deterministic=True,
    )
    stats = calculate_total_stats(champion, 18, [])
    defenses = resolve_starting_defenses("Darius", 18, stats, [])
    enemies = []
    for name in ("Annie", "Ahri"):
        loadout = ChampionLoadout(champion=name, level=18, items=()).resolve()
        enemy_stats = dict(loadout.stats)
        enemy_stats.update(health=5000.0, armor=0.0, magic_resistance=0.0)
        enemies.append(replace(loadout, stats=enemy_stats))

    def timeline(**kwargs):
        return build_participant_timeline(
            champion,
            18,
            [],
            params,
            main_stats=stats,
            main_defenses=defenses,
            enemies=enemies,
            allies=[],
            **kwargs,
        )

    receipt = timeline()
    legacy = timeline(include_receipt=False)
    fast = timeline(
        include_receipt=False,
        pair_result_cache={},
        search_context=CoupledSearchContext(),
    )
    main_survival = receipt["participants"][0]["survival"]
    heals = receipt["healing_events"]
    assert len(heals) == 1
    assert heals[0]["source"] == "Decimate"
    assert heals[0]["raw_amount"] == pytest.approx(
        main_survival["damage_taken"] * 0.34, abs=0.1
    )
    assert main_survival["healing_received"] == pytest.approx(
        heals[0]["applied_amount"]
    )
    assert fast["participants"] == legacy["participants"]
    assert fast["breakdown"] == legacy["breakdown"]


def test_sundered_sky_heal_uses_live_missing_health_in_both_walks():
    """Lightshield Strike resolves its missing-health component once."""
    champion = get_champion("Ahri")
    items = [get_item_by_name("Sundered Sky")]
    params = FightParams.from_request(
        {
            "fight_mode": "timed",
            "fight_duration": 4,
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
        },
        deterministic=True,
    )
    stats = calculate_total_stats(champion, 18, items)
    defenses = resolve_starting_defenses("Ahri", 18, stats, items)
    enemy = ChampionLoadout(champion="Annie", level=18, items=()).resolve()
    enemy_stats = dict(enemy.stats)
    enemy_stats.update(health=5000.0, armor=0.0, magic_resistance=0.0)
    enemy = replace(enemy, stats=enemy_stats)

    def timeline(**kwargs):
        return build_participant_timeline(
            champion,
            18,
            items,
            params,
            main_stats=stats,
            main_defenses=defenses,
            enemies=[enemy],
            allies=[],
            **kwargs,
        )

    receipt = timeline()
    legacy = timeline(include_receipt=False)
    fast = timeline(
        include_receipt=False,
        pair_result_cache={},
        search_context=CoupledSearchContext(),
    )
    heal = next(
        event
        for event in receipt["healing_events"]
        if event["source"] == "Sundered Sky (Lightshield Strike)"
    )
    assert heal["raw_amount"] > heal["amount"]
    assert heal["raw_amount"] == pytest.approx(118.0)
    assert fast["participants"] == legacy["participants"]
    assert fast["breakdown"] == legacy["breakdown"]


def _timed_params() -> FightParams:
    return FightParams.from_request(
        {
            "fight_mode": "time_based",
            "fight_duration": 10,
            "include_auto_attacks": True,
            "auto_attack_uptime": 0.3,
            "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
        }
    )


def test_aatrox_self_healing_is_post_mitigation_and_ordered():
    result = run_fight(get_champion("Aatrox"), 18, [], _timed_params())

    assert result["self_healing"] > 0
    assert result["self_healing_events"]
    assert any(
        event["source"] == "Deathbringer Stance"
        for event in result["self_healing_events"]
    )
    assert all(
        event["time"] >= 0 and event["amount"] > 0
        for event in result["self_healing_events"]
    )


def test_ambessa_self_healing_uses_public_execution_formula():
    result = run_fight(get_champion("Ambessa"), 18, [], _timed_params())

    assert result["self_healing"] > 0
    assert all(
        event["source"] == "Public Execution" for event in result["self_healing_events"]
    )


def test_warwick_and_irelia_use_explicit_wiki_heal_attributes():
    for champion, source in (
        ("Warwick", "Jaws of the Beast"),
        ("Irelia", "Bladesurge"),
    ):
        result = run_fight(get_champion(champion), 18, [], _timed_params())
        assert result["self_healing"] > 0
        assert any(event["source"] == source for event in result["self_healing_events"])


def test_dusk_and_dawn_self_heal_mutates_main_participant_health_ledger():
    """Spellblade self-heal is applied at its authored proc timestamp."""
    app.config["TESTING"] = True
    response = app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Ahri",
            "level": 18,
            "items": ["Dusk and Dawn"],
            "fight_mode": "timed",
            "fight_duration": 4,
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
            "enemies": [{"champion": "Aatrox", "level": 18, "items": []}],
        },
    )

    assert response.status_code == 200
    combat = response.get_json()["combat"]
    heals = [
        event
        for event in combat["healing_events"]
        if event["source"] == "Dusk and Dawn (self-heal)"
    ]
    assert [event["time"] for event in heals] == [1.5, 4.5]
    assert all(event["event_id"] for event in heals)
    assert heals[0]["applied_amount"] == 15.0
    assert heals[1]["skipped_reason"] == "outside_window"
    main = next(
        row for row in combat["participants"] if row["participant_id"] == "main"
    )
    assert main["survival"]["healing_received"] == 15.0


def test_life_steal_keeps_pair_target_attribution_at_shared_timestamps():
    """Multi-target life steal remains one packet per damage pair.

    Both enemy pair fights emit same-time auto/on-hit packets.  Their heals
    must retain the target that generated each packet rather than being
    collapsed by a source/time deduplication key.
    """
    app.config["TESTING"] = True
    response = app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Ahri",
            "level": 18,
            "items": ["Blade of the Ruined King"],
            "fight_mode": "timed",
            "fight_duration": 4,
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
            "enemies": [
                {"champion": "Aatrox", "level": 18, "items": []},
                {"champion": "Dr. Mundo", "level": 18, "items": []},
            ],
        },
    )

    assert response.status_code == 200
    heals = [
        event
        for event in response.get_json()["combat"]["healing_events"]
        if event["source"] == "Life steal (basic attacks and on-hit)"
    ]
    assert heals
    assert {event["trigger_target"] for event in heals} == {
        "enemy:Aatrox",
        "enemy:Dr. Mundo",
    }
    assert all(event["trigger_event_id"] for event in heals)
    assert len(
        {
            (event["time"], event["event_id"], event["trigger_event_id"])
            for event in heals
        }
    ) == len(heals)
    # At least one simultaneous timestamp has one packet for each enemy.
    by_time = {}
    for event in heals:
        by_time.setdefault(event["time"], []).append(event)
    assert any(
        {event["trigger_target"] for event in events}
        == {"enemy:Aatrox", "enemy:Dr. Mundo"}
        for events in by_time.values()
    )


def test_target_unending_despair_self_heal_is_wounded_in_receipt_order():
    """Target-side periodic item heals use the active wound at their timestamp.

    The item self-heal is authored by the enemy's incoming pair fight, so it
    must survive the coupled ledger with its source/event id intact.  Mortal
    Reminder's repeated physical hits keep Grievous Wounds active through both
    four-second Anguish ticks; a missing phase/receipt link would silently
    apply either tick at full value.
    """
    from src.calculator.defensive_effects import resolve_starting_defenses
    from src.calculator.scenario import ChampionLoadout
    from src.calculator.stats import calculate_total_stats

    params = FightParams.from_request(
        {
            "fight_mode": "time_based",
            "fight_duration": 8,
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
            "role": "top",
        },
        deterministic=True,
    )
    champion = get_champion("Aatrox")
    items = [get_item_by_name("Mortal Reminder")]
    stats = calculate_total_stats(champion, 18, items, role="top")
    defenses = resolve_starting_defenses(champion["name"], 18, stats, items)
    enemy = ChampionLoadout(
        champion="Aatrox",
        level=18,
        role="top",
        items=("Unending Despair", "Spirit Visage"),
    ).resolve()

    result = build_participant_timeline(
        champion,
        18,
        items,
        params,
        main_stats=stats,
        main_defenses=defenses,
        enemies=[enemy],
        allies=[],
    )

    heals = [
        event
        for event in result["healing_events"]
        if event["source"] == "Unending Despair (Anguish) (self-heal)"
    ]
    assert [event["time"] for event in heals] == [4.0, 8.0]
    assert all(event["event_id"].startswith("enemy:Aatrox:heal:") for event in heals)
    assert all(
        event["healing_reduction_factor"] == pytest.approx(0.6) for event in heals
    )
    assert all(
        event["reduced_amount"] == pytest.approx(event["raw_amount"] * 0.6, abs=0.1)
        for event in heals
    )
    assert all(
        event["raw_amount"] == pytest.approx(event["amount"] * 1.25, abs=0.1)
        for event in heals
    )

    enemy_survival = next(
        row["survival"]
        for row in result["participants"]
        if row["participant_id"] == "enemy:Aatrox"
    )
    assert any(
        "Mortal Reminder" in source
        for source in enemy_survival["healing_reduction_sources"]
    ) or any(
        "Mortal Reminder" in source
        for event in enemy_survival["healing_reduction_events"]
        for source in event["sources"]
    )


def test_compiled_walk_applies_spirit_visage_to_item_heals():
    """The optimized roster walk preserves received-heal amplification."""
    from src.calculator.defensive_effects import resolve_starting_defenses
    from src.calculator.participant_timeline import CoupledSearchContext
    from src.calculator.scenario import ChampionLoadout
    from src.calculator.stats import calculate_total_stats

    params = FightParams.from_request(
        {
            "fight_mode": "time_based",
            "fight_duration": 8,
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
            "role": "mid",
        },
        deterministic=True,
    )
    champion = get_champion("Ahri")
    main_items: list[dict] = []
    main_stats = calculate_total_stats(champion, 18, main_items, role="mid")
    enemy = ChampionLoadout(
        champion="Aatrox",
        level=18,
        role="top",
        items=("Unending Despair", "Spirit Visage"),
    ).resolve()
    main_defenses = resolve_starting_defenses(
        champion["name"], 18, main_stats, main_items
    )

    legacy = build_participant_timeline(
        champion,
        18,
        main_items,
        params,
        main_stats=main_stats,
        main_defenses=main_defenses,
        enemies=[enemy],
        allies=[],
        include_receipt=False,
    )
    fast = build_participant_timeline(
        champion,
        18,
        main_items,
        params,
        main_stats=main_stats,
        main_defenses=main_defenses,
        enemies=[enemy],
        allies=[],
        include_receipt=False,
        pair_result_cache={},
        search_context=CoupledSearchContext(),
    )

    assert fast == legacy
    enemy_row = next(
        row for row in fast["breakdown"] if row["participant_id"] == "enemy:Aatrox"
    )
    assert enemy_row["healing_received"] > 0


def test_target_unending_multitarget_heals_have_pair_receipts_and_dead_targets_skip():
    """One Anguish pulse emits one linked heal per live target packet.

    The target-side item fight is evaluated once per selected teammate.  Heal
    ids and trigger links therefore need pair-local identity; a dead teammate's
    skipped pulse must not still grant the defender a second self-heal.
    """
    app.config["TESTING"] = True
    response = app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Aatrox",
            "level": 18,
            "items": ["Mortal Reminder"],
            "fight_mode": "time_based",
            "fight_duration": 8,
            "include_auto_attacks": True,
            "auto_attack_uptime": 0.3,
            "role": "top",
            "enemies": [
                {
                    "champion": "Aatrox",
                    "level": 18,
                    "items": ["Unending Despair"],
                    "role": "top",
                }
            ],
            "allies": [
                {
                    "champion": "Lulu",
                    "level": 18,
                    "items": [],
                    "role": "support",
                    "ally_effects_enabled": True,
                }
            ],
        },
    )

    assert response.status_code == 200
    combat = response.get_json()["combat"]
    heals = [
        event
        for event in combat["healing_events"]
        if event["source"] == "Unending Despair (Anguish) (self-heal)"
    ]
    assert len(heals) == 4
    assert len({event["event_id"] for event in heals}) == len(heals)
    assert all(event.get("trigger_event_id") for event in heals)

    by_time = {
        time: [event for event in heals if event["time"] == time] for time in (4.0, 8.0)
    }
    assert all(event["applied_amount"] > 0 for event in by_time[4.0])
    assert sum(event.get("applied_amount", 0.0) > 0 for event in by_time[8.0]) == 1
    assert (
        sum(
            event.get("skipped_reason") == "trigger_event_skipped"
            for event in by_time[8.0]
        )
        == 1
    )


def test_mundo_regeneration_is_actor_wide_and_deduplicated_in_a_roster():
    app.config["TESTING"] = True
    response = app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Dr. Mundo",
            "level": 18,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 5,
            "include_auto_attacks": False,
            "enemies": [
                {"champion": "Aphelios", "level": 18, "items": []},
                {"champion": "Ambessa", "level": 18, "items": []},
            ],
        },
    )
    assert response.status_code == 200
    healing = [
        event
        for event in response.get_json()["combat"]["healing_events"]
        if event["source"] == "Maximum Dosage"
    ]
    assert [event["time"] for event in healing] == sorted(
        event["time"] for event in healing
    )
    # R is cast at 0.25s; the sourced 0.5s cadence yields nine ticks in a
    # five-second window, regardless of the number of enemy pairs.
    assert len(healing) == 9
    assert [event["time"] for event in healing] == [
        round(0.75 + index * 0.5, 3) for index in range(9)
    ]


def test_fight_result_promotes_the_same_ordered_damage_ledger_used_by_shields():
    result = run_fight(get_champion("Aatrox"), 18, [], _timed_params())

    assert result["damage_events"]
    assert all(
        {"source_key", "damage_type", "damage", "time"}.issubset(event)
        for event in result["damage_events"]
    )


def test_api_includes_enemy_output_and_main_effective_health():
    app.config["TESTING"] = True
    response = app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Aatrox",
            "level": 18,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 10,
            "include_auto_attacks": True,
            "auto_attack_uptime": 0.3,
            "enemies": [{"champion": "Ambessa", "level": 18, "items": []}],
        },
    )
    assert response.status_code == 200
    combat = response.get_json()["combat"]
    assert {row["champion"] for row in combat["breakdown"]} == {"Aatrox", "Ambessa"}
    assert all(
        {"incoming_damage", "effective_health", "survived_window"}.issubset(row)
        for row in combat["breakdown"]
    )
    main = next(
        row for row in combat["participants"] if row["participant_id"] == "main"
    )
    assert main["survival"]["effective_health"] >= main["survival"]["max_health"]


def test_coupled_akali_orianna_receipt_is_bidirectional():
    """The Akali/Orianna regression keeps both outgoing event streams."""
    app.config["TESTING"] = True
    response = app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Akali",
            "level": 12,
            "role": "mid",
            "fight_mode": "time_based",
            "fight_duration": 6,
            "include_auto_attacks": False,
            "ability_ranks": {"Q": 3, "W": 1, "E": 2, "R": 1},
            "enemies": [
                {
                    "champion": "Orianna",
                    "level": 12,
                    "role": "mid",
                    "items": [],
                    "ability_ranks": {"Q": 3, "W": 1, "E": 2, "R": 1},
                }
            ],
        },
    )

    assert response.status_code == 200
    combat = response.get_json()["combat"]
    assert {row["participant_id"] for row in combat["participants"]} == {
        "main",
        "enemy:Orianna",
    }
    events = combat["events"]
    assert any(
        event["attacker"] == "main" and event["target"] == "enemy:Orianna"
        for event in events
    )
    assert any(
        event["attacker"] == "enemy:Orianna" and event["target"] == "main"
        for event in events
    )


def test_coupled_tank_vs_tank_receipt_keeps_both_survival_rows():
    """A tank-vs-tank fight exposes outgoing and incoming state for both sides."""
    app.config["TESTING"] = True
    response = app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Dr. Mundo",
            "level": 13,
            "role": "top",
            "fight_mode": "time_based",
            "fight_duration": 6,
            "include_auto_attacks": True,
            "auto_attack_uptime": 0.5,
            "enemies": [
                {
                    "champion": "Alistar",
                    "level": 13,
                    "role": "support",
                    "items": [],
                }
            ],
        },
    )

    assert response.status_code == 200
    combat = response.get_json()["combat"]
    participant_ids = {row["participant_id"] for row in combat["participants"]}
    assert participant_ids == {"main", "enemy:Alistar"}
    assert {event["attacker"] for event in combat["events"]} == participant_ids
    assert {event["target"] for event in combat["events"]} == participant_ids
    for row in combat["breakdown"]:
        assert row["participant_id"] in participant_ids
        assert row["incoming_damage"] >= 0
        assert row["effective_health"] > 0
        assert "outgoing_damage_before_death" in row


def test_five_participant_coupled_receipt_has_every_outgoing_stream():
    """The five-participant regression preserves all selected event streams."""
    app.config["TESTING"] = True
    response = app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Aatrox",
            "level": 13,
            "role": "top",
            "fight_mode": "time_based",
            "fight_duration": 6,
            "include_auto_attacks": True,
            "auto_attack_uptime": 0.5,
            "allies": [
                {
                    "champion": "Lulu",
                    "level": 13,
                    "role": "support",
                    "items": [],
                    "ally_effects_enabled": True,
                }
            ],
            "enemies": [
                {"champion": "Ahri", "level": 13, "role": "mid", "items": []},
                {
                    "champion": "Jinx",
                    "level": 13,
                    "role": "bottom",
                    "items": [],
                },
                {
                    "champion": "Dr. Mundo",
                    "level": 13,
                    "role": "top",
                    "items": [],
                },
            ],
        },
    )

    assert response.status_code == 200
    combat = response.get_json()["combat"]
    participant_ids = {
        "main",
        "ally:Lulu",
        "enemy:Ahri",
        "enemy:Jinx",
        "enemy:Dr. Mundo",
    }
    assert {row["participant_id"] for row in combat["participants"]} == participant_ids
    assert {row["participant_id"] for row in combat["breakdown"]} == participant_ids
    assert {event["attacker"] for event in combat["events"]} == participant_ids
    for row in combat["breakdown"]:
        assert row["incoming_damage"] >= 0
        assert row["effective_health"] > 0
        assert row["survived_window"] in {True, False}


def test_api_includes_sourced_lulu_ally_shield_in_main_ehp():
    app.config["TESTING"] = True
    response = app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Aatrox",
            "level": 18,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 10,
            "include_auto_attacks": True,
            "auto_attack_uptime": 0.3,
            "enemies": [{"champion": "Ambessa", "level": 18, "items": []}],
            "allies": [
                {"champion": "Lulu", "level": 18, "items": [], "role": "support"}
            ],
        },
    )
    assert response.status_code == 200
    combat = response.get_json()["combat"]
    assert any(
        event["source"].startswith("Help, Pix!") for event in combat["support_events"]
    )
    main = next(
        row for row in combat["participants"] if row["participant_id"] == "main"
    )
    assert main["survival"]["support_shield_received"] > 0
    assert combat["objective"]["main_team_effective_health"] > 0


def test_public_damage_events_follow_ledger_time_order():
    app.config["TESTING"] = True
    response = app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Aatrox",
            "level": 18,
            "items": ["Bramble Vest"],
            "fight_mode": "time_based",
            "fight_duration": 10,
            "include_auto_attacks": True,
            "auto_attack_uptime": 0.3,
            "enemies": [{"champion": "Ambessa", "level": 18, "items": []}],
        },
    )
    assert response.status_code == 200
    events = response.get_json()["combat"]["events"]
    assert events
    assert [event["time"] for event in events] == sorted(
        event["time"] for event in events
    )
    assert all(event.get("event_id") for event in events)


def test_main_support_targets_selected_ally_and_uses_requested_rank():
    app.config["TESTING"] = True
    response = app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Lulu",
            "level": 18,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 10,
            "include_auto_attacks": False,
            "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
            "allies": [
                {
                    "champion": "Jinx",
                    "level": 18,
                    "items": [],
                    "ally_effects_enabled": True,
                }
            ],
            "enemies": [{"champion": "Ambessa", "level": 18, "items": []}],
        },
    )
    assert response.status_code == 200
    combat = response.get_json()["combat"]
    shield = next(
        event
        for event in combat["support_events"]
        if event["attacker"] == "main" and event["source"].startswith("Help, Pix!")
    )
    assert shield["target"] == "ally:Jinx"
    assert shield["recipient"] == "ally:Jinx"
    assert shield["event_id"].startswith("main:support:")
    assert shield["target_policy"] == "first_selected_teammate"
    assert shield["amount"] == 230.0
    assert shield["applied_amount"] == 230.0
    jinx = next(
        row for row in combat["participants"] if row["participant_id"] == "ally:Jinx"
    )
    assert jinx["survival"]["support_shield_received"] == 230.0


def test_sona_aria_supports_sona_and_the_selected_ally():
    """Sona W's self heal/shield and one wounded-ally packet are explicit."""
    app.config["TESTING"] = True
    response = app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Sona",
            "level": 18,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 3,
            "include_auto_attacks": False,
            "ability_ranks": {"Q": 0, "W": 5, "E": 0, "R": 0},
            "allies": [
                {
                    "champion": "Jinx",
                    "level": 18,
                    "items": [],
                    "ally_effects_enabled": True,
                }
            ],
            "enemies": [{"champion": "Ambessa", "level": 18, "items": []}],
        },
    )

    assert response.status_code == 200
    support = [
        event
        for event in response.get_json()["combat"]["support_events"]
        if event["attacker"] == "main"
        and event["source"].startswith("Aria of Perseverance")
    ]
    assert {event["target"] for event in support} == {"main", "ally:Jinx"}
    assert [event["time"] for event in support] == sorted(
        event["time"] for event in support
    )
    assert {event["target_scope"] for event in support} == {"self_and_one_teammate"}
    assert {event["target_policy"] for event in support} == {
        "self_and_first_selected_teammate"
    }


def test_seraphine_surround_sound_includes_caster_and_all_selected_allies():
    """Area support packets include the caster as well as every ally."""
    app.config["TESTING"] = True
    response = app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Seraphine",
            "level": 18,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 3,
            "include_auto_attacks": False,
            "ability_ranks": {"Q": 0, "W": 5, "E": 0, "R": 0},
            "allies": [
                {
                    "champion": "Jinx",
                    "level": 18,
                    "items": [],
                    "ally_effects_enabled": True,
                },
                {
                    "champion": "Lulu",
                    "level": 18,
                    "items": [],
                    "ally_effects_enabled": True,
                },
            ],
            "enemies": [{"champion": "Ambessa", "level": 18, "items": []}],
        },
    )

    assert response.status_code == 200
    support = [
        event
        for event in response.get_json()["combat"]["support_events"]
        if event["attacker"] == "main" and event["source"].startswith("Surround Sound")
    ]
    assert {event["target"] for event in support} == {
        "main",
        "ally:Jinx",
        "ally:Lulu",
    }
    assert {event["target_policy"] for event in support} == {
        "self_and_all_selected_teammates"
    }


def test_enemy_self_shield_is_present_in_the_coupled_timeline():
    app.config["TESTING"] = True
    response = app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Aatrox",
            "level": 18,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 10,
            "include_auto_attacks": False,
            "enemies": [
                {
                    "champion": "Orianna",
                    "level": 6,
                    "items": [],
                    "ability_ranks": {"Q": 3, "W": 1, "E": 1, "R": 1},
                }
            ],
        },
    )
    assert response.status_code == 200
    combat = response.get_json()["combat"]
    shield = next(
        event
        for event in combat["support_events"]
        if event["attacker"] == "enemy:Orianna"
        and event["source"].startswith("Command: Protect")
    )
    assert shield["target"] == "enemy:Orianna"
    assert shield["target_policy"] == "self"
    assert shield["amount"] == 55.0


@pytest.mark.parametrize(("low_rank", "high_rank"), [(1, 5), (2, 4)])
def test_ally_lulu_rank_changes_the_authored_help_pix_packet(low_rank, high_rank):
    """An ally's requested E rank changes its exact shield packet."""

    def shield_amount(rank: int) -> float:
        response = app.test_client().post(
            "/api/calculate",
            json={
                "champion": "Aatrox",
                "level": 18,
                "items": [],
                "fight_mode": "time_based",
                "fight_duration": 3,
                "include_auto_attacks": False,
                "allies": [
                    {
                        "champion": "Lulu",
                        "level": 18,
                        "items": [],
                        "ally_effects_enabled": True,
                        "ability_ranks": {"Q": 0, "W": 0, "E": rank, "R": 0},
                    }
                ],
                "enemies": [{"champion": "Ambessa", "level": 18, "items": []}],
            },
        )
        assert response.status_code == 200
        events = response.get_json()["combat"]["support_events"]
        return next(
            event["amount"]
            for event in events
            if event["source"].startswith("Help, Pix!") and event["target"] == "main"
        )

    assert shield_amount(low_rank) < shield_amount(high_rank)


@pytest.mark.parametrize(("low_rank", "high_rank"), [(1, 3), (2, 4)])
def test_enemy_orianna_rank_changes_the_authored_protect_packet(low_rank, high_rank):
    """An enemy's requested E rank changes its self-shield receipt."""

    def shield_amount(rank: int) -> float:
        response = app.test_client().post(
            "/api/calculate",
            json={
                "champion": "Aatrox",
                "level": 18,
                "items": [],
                "fight_mode": "time_based",
                "fight_duration": 3,
                "include_auto_attacks": False,
                "enemies": [
                    {
                        "champion": "Orianna",
                        "level": 18,
                        "items": [],
                        "ability_ranks": {"Q": 0, "W": 0, "E": rank, "R": 0},
                    }
                ],
            },
        )
        assert response.status_code == 200
        events = response.get_json()["combat"]["support_events"]
        return next(
            event["amount"]
            for event in events
            if event["source"].startswith("Command: Protect")
            and event["target"] == "enemy:Orianna"
        )

    assert shield_amount(low_rank) < shield_amount(high_rank)


@pytest.mark.parametrize(("low_rank", "high_rank"), [(1, 3), (2, 3)])
def test_enemy_mundo_rank_changes_authored_regeneration_packets(low_rank, high_rank):
    """An enemy's requested R rank changes each Maximum Dosage packet."""

    def regeneration_total(rank: int) -> float:
        response = app.test_client().post(
            "/api/calculate",
            json={
                "champion": "Aatrox",
                "level": 18,
                "items": [],
                "fight_mode": "time_based",
                "fight_duration": 3,
                "include_auto_attacks": False,
                "enemies": [
                    {
                        "champion": "Dr. Mundo",
                        "level": 18,
                        "items": [],
                        "ability_ranks": {"Q": 0, "W": 0, "E": 0, "R": rank},
                    }
                ],
            },
        )
        assert response.status_code == 200
        return sum(
            event["amount"]
            for event in response.get_json()["combat"]["healing_events"]
            if event["attacker"] == "enemy:Dr. Mundo"
            and event["source"] == "Maximum Dosage"
        )

    assert regeneration_total(low_rank) < regeneration_total(high_rank)


def test_aatrox_cast_order_changes_the_authored_cast_sequence():
    """The requested Aatrox cast order is preserved in the public timeline."""

    def cast_slots(order: list[str]) -> list[str]:
        response = app.test_client().post(
            "/api/calculate",
            json={
                "champion": "Aatrox",
                "level": 18,
                "items": [],
                "fight_mode": "one_rotation",
                "include_auto_attacks": False,
                "cast_order": order,
            },
        )
        assert response.status_code == 200
        return [event["slot"] for event in response.get_json()["cast_timeline"]]

    first = cast_slots(["Q", "W", "E", "R"])
    second = cast_slots(["R", "Q", "W", "E"])
    assert first[:2] == ["Q", "W"]
    assert second[:2] == ["R", "Q"]
    assert first != second


def test_coupled_timeline_stops_output_after_main_champion_is_defeated():
    app.config["TESTING"] = True
    response = app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Aatrox",
            "level": 1,
            "items": [],
            "fight_mode": "one_rotation",
            "enemies": [{"champion": "Ambessa", "level": 18, "items": []}],
        },
    )
    assert response.status_code == 200
    combat = response.get_json()["combat"]
    main = next(
        row for row in combat["participants"] if row["participant_id"] == "main"
    )
    assert main["survival"]["survived_window"] is False
    assert main["survival"]["death_time"] is not None
    # The enemy's later event stream is not counted as if Aatrox remained
    # alive for the whole rotation.
    assert (
        next(row for row in combat["breakdown"] if row["participant_id"] == "main")[
            "total_damage"
        ]
        <= 138.5
    )


def test_coupled_timeline_reprices_current_health_damage_for_each_attacker():
    """A second Mundo Q must see the damage already dealt by the first one."""
    app.config["TESTING"] = True
    response = app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Dr. Mundo",
            "level": 6,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 3.5,
            "include_auto_attacks": False,
            "ability_ranks": {"Q": 3, "W": 1, "E": 1, "R": 1},
            "enemies": [{"champion": "Aphelios", "level": 6, "items": []}],
            "allies": [
                {
                    "champion": "Dr. Mundo",
                    "level": 6,
                    "items": [],
                    "ally_effects_enabled": False,
                    "ability_ranks": {"Q": 3, "W": 1, "E": 1, "R": 1},
                }
            ],
        },
    )
    assert response.status_code == 200
    events = [
        event
        for event in response.get_json()["combat"]["events"]
        if event["target"] == "enemy:Aphelios" and event["source"] == "Q"
    ]
    main_q = next(event for event in events if event["attacker"] == "main")
    ally_q = next(event for event in events if event["attacker"] == "ally:Dr. Mundo")
    assert main_q["damage"] > ally_q["damage"]
    assert main_q["pair_damage"] == ally_q["pair_damage"]
    assert ally_q["damage"] < ally_q["pair_damage"]


def test_coupled_timeline_caps_overkill_and_skips_post_death_events():
    app.config["TESTING"] = True
    response = app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Ziggs",
            "level": 18,
            "items": [
                "Luden's Echo",
                "Rabadon's Deathcap",
                "Shadowflame",
                "Void Staff",
                "Stormsurge",
            ],
            "fight_mode": "time_based",
            "fight_duration": 10,
            "include_auto_attacks": False,
            "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
            "enemies": [{"champion": "Aphelios", "level": 1, "items": []}],
        },
    )
    assert response.status_code == 200
    combat = response.get_json()["combat"]
    enemy = next(row for row in combat["participants"] if row["team"] == "enemy")
    main_row = next(
        row for row in combat["breakdown"] if row["participant_id"] == "main"
    )
    assert enemy["survival"]["survived_window"] is False
    assert enemy["survival"]["overkill"] > 0
    assert main_row["total_damage"] <= enemy["survival"]["max_health"]
    assert any(
        event.get("skipped_reason") == "target_dead" for event in combat["events"]
    )


def _bis_request(subject_team: str) -> dict:
    return {
        "champion": "Aatrox",
        "level": 18,
        "items": ["Infinity Edge", "Bloodthirster"],
        "boots": "Plated Steelcaps",
        "role": "top",
        "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
        "fight_mode": "time_based",
        "fight_duration": 10,
        "include_auto_attacks": True,
        "auto_attack_uptime": 0.3,
        "subject_team": subject_team,
        "subject_index": 0,
        "slot_index": 0,
        "slot_kind": "item",
        "enemies": [
            {
                "champion": "Ambessa",
                "level": 18,
                "items": [],
                "role": "top",
                "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
            }
        ],
        "allies": [
            {
                "champion": "Lulu",
                "level": 18,
                "items": [],
                "role": "support",
                "ally_effects_enabled": True,
                "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
            }
        ],
    }


def test_bis_endpoint_scores_main_from_damage_and_effective_health():
    app.config["TESTING"] = True
    response = app.test_client().post("/api/bis", json=_bis_request("main"))
    assert response.status_code == 200
    body = response.get_json()
    assert body["candidate_count"] > 0
    assert body["candidates"]
    top = body["candidates"][0]
    assert top["metric"] == "main TTD (survival-coupled)"
    assert top["components"]["effective_health"] > 0


@pytest.mark.parametrize(
    ("objective", "direction", "metric"),
    [
        ("overall", "higher", "main TTD (survival-coupled)"),
        ("kill", "lower", "time to first target defeat"),
        ("survival", "higher", "effective health (event-applied)"),
        ("damage", "higher", "damage before focus defeat"),
        ("utility", "higher", "healing, shields, and support value"),
    ],
)
def test_bis_objectives_have_an_explicit_direction_and_metric(
    objective, direction, metric
):
    payload = _bis_request("main")
    payload["objective"] = objective
    response = app.test_client().post("/api/bis", json=payload)
    assert response.status_code == 200
    body = response.get_json()
    assert body["objective"] == {
        "key": objective,
        "label": body["objective"]["label"],
        "direction": direction,
        "metric": body["objective"]["metric"],
    }
    assert body["candidates"]
    assert body["candidates"][0]["metric"] == metric
    scores = [row["objective_value"] for row in body["candidates"]]
    assert scores == sorted(scores, reverse=direction == "higher")


def test_bis_withholds_unmodelled_eclipse_and_deaths_dance_defenses():
    payload = _bis_request("main")
    payload["objective"] = "survival"
    body = app.test_client().post("/api/bis", json=payload).get_json()
    withheld = {row["name"]: row for row in body["withheld_candidates"]}
    assert "Eclipse" not in {row["name"] for row in body["candidates"]}
    assert "Death's Dance" not in {row["name"] for row in body["candidates"]}
    for name in ("Eclipse", "Death's Dance"):
        assert withheld[name]["reason"] == "objective_effect_unavailable"
        assert withheld[name]["timeline_coverage"]["complete"] is False
        assert name in withheld[name]["detail"]


def test_bis_receipts_certified_sundered_sky_ehp_inputs():
    payload = _bis_request("main")
    payload["objective"] = "survival"
    body = app.test_client().post("/api/bis", json=payload).get_json()
    row = next(
        candidate
        for candidate in body["candidates"]
        if candidate["name"] == "Sundered Sky"
    )
    receipt = row["defensive_effect_receipt"]
    assert receipt["status"] == "certified"
    assert "healing_received" in receipt["evidence"]
    assert (
        receipt["evidence"]["effective_health"] == row["survival"]["effective_health"]
    )


def test_bis_rejects_an_unknown_objective():
    payload = _bis_request("main")
    payload["objective"] = "critical_strike_luck"
    response = app.test_client().post("/api/bis", json=payload)
    assert response.status_code == 400
    assert "objective must be one of" in response.get_json()["error"]


def test_bis_reports_candidates_withheld_before_timeline_evaluation(monkeypatch):
    """A failed candidate remains visible in the per-candidate audit receipt."""

    candidates = [get_item_by_name("Luden's Echo"), get_item_by_name("Warmog's Armor")]
    monkeypatch.setattr(
        "src.app._bis_candidate_pool",
        lambda *_args, **_kwargs: candidates,
    )

    def fake_timeline(*args, **kwargs):
        items = args[2]
        if any(item["name"] == "Luden's Echo" for item in items):
            raise ValueError("Luden's Echo event packet is unavailable")
        return {
            "objective": {"focus_damage_before_death": 100.0},
            "participants": [
                {
                    "participant_id": "main",
                    "survival": {
                        "effective_health": 1_000.0,
                        "healing_received": 0.0,
                        "support_shield_received": 0.0,
                    },
                }
            ],
            "timeline_coverage": {
                "complete": True,
                "certification": "event_order_certified",
                "exact_sources": ["Q"],
                "coarse_sources": [],
            },
        }

    monkeypatch.setattr("src.app.build_participant_timeline", fake_timeline)
    response = app.test_client().post("/api/bis", json=_bis_request("main"))

    assert response.status_code == 200
    body = response.get_json()
    assert body["candidate_count"] == 2
    assert body["certified_candidate_count"] == 1
    assert body["withheld_candidate_count"] == 1
    assert body["coverage"]["complete"] is False
    assert body["coverage"]["certification"] == "bis_certified_subset_not_exhaustive"
    withheld = body["withheld_candidates"]
    assert withheld[0]["name"] == "Luden's Echo"
    assert withheld[0]["reason"] == "candidate_loadout_unavailable"
    assert withheld[0]["timeline_coverage"]["complete"] is False


def test_bis_excludes_audited_item_timing_before_ranking(monkeypatch):
    """Known item timing gaps stay visible without becoming partial BIS rows."""

    candidates = [
        get_item_by_name("Bastionbreaker"),
        get_item_by_name("Warmog's Armor"),
    ]
    monkeypatch.setattr(
        "src.app._bis_candidate_pool",
        lambda *_args, **_kwargs: candidates,
    )

    def fake_timeline(*args, **_kwargs):
        items = args[2]
        excluded = any(item["name"] == "Bastionbreaker" for item in items)
        return {
            "objective": {"focus_damage_before_death": 100.0},
            "participants": [
                {
                    "participant_id": "main",
                    "survival": {
                        "effective_health": 1_000.0,
                        "healing_received": 0.0,
                        "support_shield_received": 0.0,
                    },
                }
            ],
            "timeline_coverage": {
                "complete": not excluded,
                "certification": (
                    "partial_event_order" if excluded else "event_order_certified"
                ),
                "exact_sources": [],
                "coarse_sources": ["shaped_charge_Bastionbreaker"] if excluded else [],
            },
        }

    monkeypatch.setattr("src.app.build_participant_timeline", fake_timeline)
    response = app.test_client().post("/api/bis", json=_bis_request("main"))

    assert response.status_code == 200
    body = response.get_json()
    assert body["partial_candidates"] == []
    assert body["candidates"]
    assert body["coverage"]["complete"] is True
    assert body["coverage"]["certification"] == (
        "bis_event_order_certified_with_exclusions"
    )
    row = next(
        row for row in body["withheld_candidates"] if row["name"] == "Bastionbreaker"
    )
    assert row["reason"] == "candidate_excluded_unresolved_timing"
    assert row["exclusion_type"] == "applicability"
    assert row["excluded_sources"] == ["shaped_charge_Bastionbreaker"]


def test_bis_endpoint_keeps_ally_and_enemy_in_the_same_timeline():
    app.config["TESTING"] = True
    client = app.test_client()
    ally = client.post("/api/bis", json=_bis_request("ally"))
    enemy = client.post("/api/bis", json=_bis_request("enemy"))
    assert ally.status_code == enemy.status_code == 200
    ally_top = ally.get_json()["candidates"][0]
    enemy_top = enemy.get_json()["candidates"][0]
    assert "main_team_damage_before_death" in ally_top["components"]
    assert "effective_health" in ally_top["components"]
    assert enemy_top["metric"] == "enemy survival gate · threat before defeat"
    assert enemy_top["components"]["effective_health"] > 0


def test_enemy_bis_prioritizes_event_survival_before_outgoing_threat(monkeypatch):
    """A high-damage enemy that dies early cannot beat a surviving build."""

    def fake_timeline(*_args, **kwargs):
        enemy = kwargs["enemies"][0]
        item_names = {item["name"] for item in enemy.item_data}
        glass_cannon = "Luden's Echo" in item_names
        survival = {
            "max_health": 1_000.0 if glass_cannon else 2_000.0,
            "effective_health": 1_000.0 if glass_cannon else 2_000.0,
            "healing_received": 0.0,
            "shield_absorbed": 0.0,
            "death_time": 2.0 if glass_cannon else None,
            "survived_window": not glass_cannon,
        }
        focus_id = kwargs["focus_participant_id"]
        return {
            "duration": 10.0,
            "participants": [
                {"participant_id": focus_id, "survival": survival},
            ],
            "breakdown": [
                {
                    "participant_id": focus_id,
                    "team": "enemy",
                    "total_damage": 5_000.0 if glass_cannon else 500.0,
                }
            ],
            "objective": {
                "focus_damage_before_death": 5_000.0 if glass_cannon else 500.0,
                "focus_support_value": 0.0,
                "focus_healing": 0.0,
                "main_team_damage_before_death": 0.0,
            },
            "timeline_coverage": {
                "complete": True,
                "exact_sources": [],
                "coarse_sources": [],
            },
        }

    monkeypatch.setattr("src.app.build_participant_timeline", fake_timeline)
    response = app.test_client().post("/api/bis", json=_bis_request("enemy"))

    assert response.status_code == 200
    body = response.get_json()
    assert body["candidates"]
    top = body["candidates"][0]
    assert top["name"] != "Luden's Echo"
    assert top["metric"] == "enemy survival gate · threat before defeat"
    assert top["components"]["survival_time"] == 10.0
    assert top["components"]["effective_health"] == 2_000.0


def test_enemy_bis_uses_threat_after_survival_gate(monkeypatch):
    """A live damage item beats pure health, but an early death does not."""

    monkeypatch.setattr(
        "src.app._bis_candidate_pool",
        lambda *_args, **_kwargs: [
            {"name": "Luden's Echo", "icon": "", "stats": {}},
            {"name": "Warmog's Armor", "icon": "", "stats": {}},
        ],
    )

    def fake_timeline(*_args, **kwargs):
        enemy = kwargs["enemies"][0]
        item_names = {item["name"] for item in enemy.item_data}
        damage_item = "Luden's Echo" in item_names
        survival = {
            "max_health": 1_000.0 if damage_item else 2_500.0,
            "effective_health": 1_000.0 if damage_item else 2_500.0,
            "healing_received": 0.0,
            "support_shield_received": 0.0,
            "shield_absorbed": 0.0,
            "death_time": None,
            "survived_window": True,
        }
        focus_id = kwargs["focus_participant_id"]
        threat = 1_000.0 if damage_item else 500.0
        return {
            "duration": 10.0,
            "participants": [{"participant_id": focus_id, "survival": survival}],
            "breakdown": [],
            "objective": {
                "focus_damage_before_death": threat,
                "focus_support_value": 0.0,
                "focus_healing": 0.0,
                "main_team_damage_before_death": 0.0,
            },
            "timeline_coverage": {
                "complete": True,
                "exact_sources": [],
                "coarse_sources": [],
            },
        }

    monkeypatch.setattr("src.app.build_participant_timeline", fake_timeline)
    response = app.test_client().post("/api/bis", json=_bis_request("enemy"))

    assert response.status_code == 200
    body = response.get_json()
    assert body["candidates"][0]["name"] == "Luden's Echo"
    assert body["candidates"][0]["components"]["threat_before_defeat"] == 1_000.0

    # The same damage item becomes ineligible once the event timeline records
    # an early death, even though its pre-defeat threat is much larger.
    def glass_cannon_timeline(*_args, **kwargs):
        result = fake_timeline(*_args, **kwargs)
        enemy = kwargs["enemies"][0]
        if enemy.item_data[0]["name"] == "Luden's Echo":
            result["participants"][0]["survival"].update(
                death_time=2.0,
                survived_window=False,
            )
            result["objective"]["focus_damage_before_death"] = 5_000.0
        return result

    monkeypatch.setattr("src.app.build_participant_timeline", glass_cannon_timeline)
    response = app.test_client().post("/api/bis", json=_bis_request("enemy"))
    assert response.status_code == 200
    assert response.get_json()["candidates"][0]["name"] == "Warmog's Armor"


def test_enemy_bis_rank_key_is_deterministic_and_event_derived():
    survived_damage = _enemy_bis_rank_key(
        {"focus_damage_before_death": 1_000.0},
        {
            "death_time": None,
            "effective_health": 1_000.0,
            "healing_received": 0.0,
            "support_shield_received": 0.0,
            "shield_absorbed": 0.0,
        },
        duration=10.0,
    )
    survived_health = _enemy_bis_rank_key(
        {"focus_damage_before_death": 500.0},
        {
            "death_time": None,
            "effective_health": 2_500.0,
            "healing_received": 0.0,
            "support_shield_received": 0.0,
            "shield_absorbed": 0.0,
        },
        duration=10.0,
    )
    early_glass = _enemy_bis_rank_key(
        {"focus_damage_before_death": 5_000.0},
        {
            "death_time": 2.0,
            "effective_health": 1_000.0,
            "healing_received": 0.0,
            "support_shield_received": 0.0,
            "shield_absorbed": 0.0,
        },
        duration=10.0,
    )
    later_death = _enemy_bis_rank_key(
        {"focus_damage_before_death": 100.0},
        {
            "death_time": 8.0,
            "effective_health": 2_500.0,
            "healing_received": 0.0,
            "support_shield_received": 0.0,
            "shield_absorbed": 0.0,
        },
        duration=10.0,
    )
    assert survived_damage > survived_health > later_death > early_glass


def test_roster_bis_requires_an_explicit_role_instead_of_guessing_item_class():
    app.config["TESTING"] = True
    payload = _bis_request("enemy")
    payload["enemies"][0].pop("role")
    response = app.test_client().post("/api/bis", json=payload)
    assert response.status_code == 400
    assert (
        response.get_json()["error"]
        == "enemy role is required before roster BIS can be scored"
    )


def test_roster_bis_uses_sourced_role_shop_scope_before_scoring_candidates():
    candidates = optimizer_supported_items(get_eligible_legendaries())
    support = {
        item["name"] for item in _role_scoped_bis_candidates(candidates, role="support")
    }
    top = {item["name"] for item in _role_scoped_bis_candidates(candidates, role="top")}

    assert "Locket of the Iron Solari" in support
    assert "Moonstone Renewer" in support
    assert "Warmog's Armor" not in support
    assert "Warmog's Armor" in top
    assert "Locket of the Iron Solari" not in top


def test_roster_bis_filters_items_with_unsupported_target_mechanics():
    """A roster BIS result must remain safe when reused as a passive target."""
    app.config["TESTING"] = True
    response = app.test_client().post("/api/bis", json=_bis_request("enemy"))
    assert response.status_code == 200
    body = response.get_json()
    names = {
        candidate["name"]
        for candidate in [*body["candidates"], *body["partial_candidates"]]
    }

    assert "Zhonya's Hourglass" not in names
    assert body["target_coverage_filtered"] > 0
    assert "target-side coverage filtered" in body["target_coverage_note"].lower()


def test_roster_bis_reports_actionable_target_coverage_for_blocked_mid_loadout():
    """A blocked enemy card must explain why no replacement build was applied."""
    app.config["TESTING"] = True
    payload = _bis_request("enemy")
    payload["enemies"][0]["role"] = "mid"
    payload["enemies"][0]["role_quest_complete"] = True
    payload["enemies"][0]["items"] = [
        "Heartsteel",
        "Banshee's Veil",
    ]
    payload["enemies"][0]["boots"] = "Armored Advance"

    response = app.test_client().post("/api/bis", json=payload)

    assert response.status_code == 200
    body = response.get_json()
    assert body["candidates"] == []
    assert body["coverage"]["complete"] is False
    assert body["target_coverage_filtered"] > 0
    assert "target-side coverage filtered" in body["coverage"]["note"].lower()
    assert any(
        name in body["target_coverage_note"]
        for name in ("Heartsteel", "Banshee's Veil", "Armored Advance")
    )


def test_bis_never_labels_partial_event_order_as_certified():
    app.config["TESTING"] = True
    payload = {
        # Ziggs' Short Fuse cadence is now sourced and event-certified.  The
        # assertion below remains an invariant: if any candidate is partial,
        # it must stay out of the certified list rather than being applied.
        "champion": "Ziggs",
        "level": 6,
        "items": [],
        "fight_mode": "time_based",
        "fight_duration": 3.5,
        "include_auto_attacks": True,
        "auto_attack_uptime": 1.0,
        "ability_ranks": {"Q": 3, "W": 1, "E": 1, "R": 1},
        "subject_team": "main",
        "subject_index": 0,
        "slot_index": 0,
        "slot_kind": "item",
        "enemies": [{"champion": "Aphelios", "level": 6, "items": []}],
    }
    response = app.test_client().post("/api/bis", json=payload)
    assert response.status_code == 200
    body = response.get_json()
    assert body["certified_candidate_count"] <= body["candidate_count"]
    assert all(
        candidate["timeline_coverage"]["complete"] for candidate in body["candidates"]
    )
    assert all(
        not candidate["timeline_coverage"]["complete"]
        for candidate in body["partial_candidates"]
    )
    assert body["partial_candidate_count"] == len(body["partial_candidates"])
    assert body["certified_candidate_count"] == len(body["candidates"])
    if not body["candidates"]:
        assert body["coverage"]["certification"] == "bis_no_certified_candidates"
    assert (
        body["partial_candidate_count"]
        + body["certified_candidate_count"]
        + body["withheld_candidate_count"]
        == body["candidate_count"]
    )


def test_explicitly_disabled_ally_effects_are_not_injected_into_ehp():
    app.config["TESTING"] = True
    payload = _bis_request("main")
    payload["allies"][0]["ally_effects_enabled"] = False
    response = app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200
    assert not any(
        event["attacker"] == "ally:Lulu"
        for event in response.get_json()["combat"]["support_events"]
    )


def _dummy_combatant(
    participant_id: str,
    team: str,
    health: float = 100.0,
    healing_received_multiplier: float = 1.0,
) -> Combatant:
    defenses = SimpleNamespace(
        magic_shield=0.0,
        physical_shield=0.0,
        general_shield=0.0,
        healing_received_multiplier=healing_received_multiplier,
    )
    return Combatant(
        participant_id=participant_id,
        team=team,
        champion_data={"name": participant_id},
        level=1,
        items=(),
        stats={"health": health},
        defenses=defenses,
    )


def test_simulator_amplifies_authored_support_shields_for_spirit_visage():
    source = _dummy_combatant("source", "ally")
    target = _dummy_combatant("target", "main", healing_received_multiplier=1.25)
    result = _simulate_survival(
        [source, target],
        {"target": []},
        {},
        {
            "target": [
                {
                    "time": 0.0,
                    "amount": 100.0,
                    "kind": "shield",
                    "attacker": "source",
                    "source": "authored support shield",
                }
            ]
        },
        1.0,
    )

    assert result["target"]["support_shield_received"] == 125.0


def test_simulator_orders_same_timestamp_events_without_comparing_payloads():
    target = _dummy_combatant("target", "enemy")
    source = _dummy_combatant("source", "main")
    result = _simulate_survival(
        [source, target],
        {
            "target": [
                {
                    "time": 0.0,
                    "damage": 40.0,
                    "damage_type": "physical",
                    "attacker": "source",
                    "sequence": 0,
                    "_event_id": "first",
                },
                {
                    "time": 0.0,
                    "damage": 40.0,
                    "damage_type": "physical",
                    "attacker": "source",
                    "sequence": 1,
                    "_event_id": "second",
                },
            ]
        },
        {},
        {},
        10.0,
    )
    assert result["target"]["damage_taken"] == 80.0


def test_simulator_scores_only_applied_support_and_healing_amounts():
    source = _dummy_combatant("source", "main")
    target = _dummy_combatant("target", "ally")
    dead_target = _dummy_combatant("dead", "ally", health=50.0)
    result = _simulate_survival(
        [source, target, dead_target],
        {
            "dead": [
                {
                    "time": 0.0,
                    "damage": 50.0,
                    "damage_type": "physical",
                    "attacker": "source",
                    "sequence": 0,
                    "_event_id": "kill",
                }
            ]
        },
        {
            "target": [
                {
                    "time": 0.0,
                    "amount": 50.0,
                    "attacker": "source",
                    "source": "already-full heal",
                }
            ]
        },
        {
            "dead": [
                {
                    "time": 1.0,
                    "amount": 50.0,
                    "kind": "shield",
                    "attacker": "source",
                    "source": "late shield",
                }
            ]
        },
        10.0,
    )
    assert result["target"]["healing_received"] == 0.0
    assert result["dead"]["support_shield_received"] == 0.0


def test_simulator_applies_sourced_grievous_wounds_to_healing_in_event_order():
    source = _dummy_combatant(
        "source",
        "main",
        health=100.0,
    )
    source = Combatant(
        participant_id=source.participant_id,
        team=source.team,
        champion_data=source.champion_data,
        level=source.level,
        items=(get_item_by_name("Morellonomicon"),),
        stats=source.stats,
        defenses=source.defenses,
    )
    target = _dummy_combatant("target", "enemy", health=200.0)
    result = _simulate_survival(
        [source, target],
        {
            "target": [
                {
                    "time": 0.0,
                    "damage": 50.0,
                    "damage_type": "magic",
                    "attacker": "source",
                    "sequence": 0,
                    "_event_id": "wound",
                }
            ]
        },
        {
            "target": [
                {
                    "time": 1.0,
                    "amount": 100.0,
                    "attacker": "target",
                    "source": "target heal",
                },
                {
                    "time": 4.0,
                    "amount": 100.0,
                    "attacker": "target",
                    "source": "post wound heal",
                },
            ]
        },
        {},
        10.0,
    )

    # The first heal is reduced to 60, but only 50 can fit in the missing
    # health; the post-window heal is correctly capped at full health.
    assert result["target"]["healing_received"] == 50.0
    assert result["target"]["healing_reduced"] == 40.0
    assert result["target"]["healing_reduction_until"] == 3.0
    assert result["target"]["healing_reduction_events"] == [
        {
            "recipient": "target",
            "time": 0.0,
            "until": 3.0,
            "factor": 0.6,
            "sources": ["Morellonomicon · Grievous Wounds"],
        }
    ]


def test_grievous_sources_reset_for_a_new_proc_after_expiry():
    """A later anti-heal hit starts a fresh source window after expiry."""
    first = _dummy_combatant(
        "first",
        "main",
        health=100.0,
    )
    first = Combatant(
        participant_id=first.participant_id,
        team=first.team,
        champion_data=first.champion_data,
        level=first.level,
        items=(get_item_by_name("Morellonomicon"),),
        stats=first.stats,
        defenses=first.defenses,
    )
    second = _dummy_combatant(
        "second",
        "main",
        health=100.0,
    )
    second = Combatant(
        participant_id=second.participant_id,
        team=second.team,
        champion_data=second.champion_data,
        level=second.level,
        items=(get_item_by_name("Mortal Reminder"),),
        stats=second.stats,
        defenses=second.defenses,
    )
    target = _dummy_combatant("target", "enemy", health=300.0)
    result = _simulate_survival(
        [first, second, target],
        {
            "target": [
                {
                    "time": 0.0,
                    "damage": 20.0,
                    "damage_type": "magic",
                    "attacker": "first",
                    "target": "target",
                    "sequence": 0,
                    "_event_id": "first-hit",
                },
                {
                    "time": 4.0,
                    "damage": 20.0,
                    "damage_type": "physical",
                    "attacker": "second",
                    "target": "target",
                    "sequence": 0,
                    "_event_id": "second-hit",
                },
            ]
        },
        {
            "target": [
                {"time": 1.0, "amount": 100.0, "attacker": "target"},
                {"time": 5.0, "amount": 100.0, "attacker": "target"},
            ]
        },
        {},
        10.0,
    )

    events = result["target"]["healing_reduction_events"]
    assert events[0]["sources"] == ["Morellonomicon · Grievous Wounds"]
    assert events[1]["sources"] == ["Mortal Reminder · Grievous Wounds"]


def _thorns_combatant(
    participant_id: str,
    team: str,
    *,
    health: float = 100.0,
    magic_resistance: float = 0.0,
    bonus_armor: float = 0.0,
    items: tuple = (),
) -> Combatant:
    defenses = SimpleNamespace(
        magic_shield=0.0,
        physical_shield=0.0,
        general_shield=0.0,
    )
    return Combatant(
        participant_id=participant_id,
        team=team,
        champion_data={"name": participant_id},
        level=1,
        items=items,
        stats={
            "health": health,
            "magic_resistance": magic_resistance,
            "bonus_armor": bonus_armor,
        },
        defenses=defenses,
    )


def _auto_strike(target_id, attacker_id, *, time, damage, event_id):
    return {
        "time": time,
        "damage": damage,
        "damage_type": "physical",
        "source_key": "auto_attacks",
        "attacker": attacker_id,
        "target": target_id,
        "sequence": 0,
        "_event_id": event_id,
    }


def test_thorns_strikes_back_and_wounds_the_attacker_from_incoming_autos():
    """A Bramble wearer returns mitigated magic damage per basic attack and
    Grievous-Wounds the striker's later healing."""
    striker = _thorns_combatant("source", "main", magic_resistance=100.0)
    wearer = _thorns_combatant(
        "target",
        "enemy",
        health=200.0,
        items=(get_item_by_name("Bramble Vest"),),
    )
    incoming = {
        "target": [
            _auto_strike("target", "source", time=0.0, damage=50.0, event_id="swing0")
        ],
    }
    outgoing = {"source": list(incoming["target"]), "target": []}
    _schedule_thorns_events([striker, wearer], incoming, outgoing)

    thorns_events = [
        event
        for event in incoming.get("source", [])
        if event.get("source_key") == "thorns_Bramble Vest"
    ]
    assert len(thorns_events) == 1
    assert thorns_events[0]["time"] == 0.0
    assert thorns_events[0]["damage_type"] == "magic"
    assert thorns_events[0]["_wound_until"] == 3.0
    assert thorns_events[0] in outgoing["target"]

    result = _simulate_survival(
        [striker, wearer],
        incoming,
        {
            "source": [
                {
                    "time": 1.0,
                    "amount": 20.0,
                    "attacker": "source",
                    "source": "striker heal",
                }
            ]
        },
        {},
        10.0,
    )
    # 10 magic vs 100 MR = 5 damage back to the striker.
    assert result["source"]["damage_taken"] == 5.0
    # The 20 heal is wounded to 12; only 5 health is missing, so 5 lands.
    assert result["source"]["healing_received"] == 5.0
    assert result["source"]["healing_reduced"] == 8.0
    assert result["source"]["healing_reduction_until"] == 3.0
    assert any(
        "Bramble Vest" in source
        for source in result["source"]["healing_reduction_sources"]
    )
    assert result["target"]["damage_taken"] == 50.0


def test_thornmail_thorns_scales_from_wearer_bonus_armor():
    striker = _thorns_combatant("source", "main", magic_resistance=0.0)
    wearer = _thorns_combatant(
        "target",
        "enemy",
        health=200.0,
        bonus_armor=100.0,
        items=(get_item_by_name("Thornmail"),),
    )
    incoming = {
        "target": [
            _auto_strike("target", "source", time=0.0, damage=50.0, event_id="swing0")
        ],
    }
    outgoing = {"source": list(incoming["target"]), "target": []}
    _schedule_thorns_events([striker, wearer], incoming, outgoing)
    thorns_events = [
        event
        for event in incoming["source"]
        if event.get("source_key") == "thorns_Thornmail"
    ]
    assert len(thorns_events) == 1
    assert thorns_events[0]["damage"] == 30.0


def test_thorns_from_a_skipped_strike_never_fires():
    """A strike that lands after the wearer died is skipped, and its thorns
    must not survive as an unconnected retaliation tick; the killing blow's
    thorns still fires (the wearer was alive when struck)."""
    striker = _thorns_combatant("source", "main", magic_resistance=100.0)
    wearer = _thorns_combatant(
        "target",
        "enemy",
        health=50.0,
        items=(get_item_by_name("Bramble Vest"),),
    )
    incoming = {
        "target": [
            _auto_strike("target", "source", time=0.0, damage=60.0, event_id="kill"),
            _auto_strike(
                "target", "source", time=1.0, damage=40.0, event_id="post-death"
            ),
        ],
    }
    outgoing = {"source": list(incoming["target"]), "target": []}
    _schedule_thorns_events([striker, wearer], incoming, outgoing)

    result = _simulate_survival([striker, wearer], incoming, {}, {}, 10.0)
    assert result["target"]["survived_window"] is False
    # Only the killing blow's thorns lands: 10 magic vs 100 MR = 5.
    assert result["source"]["damage_taken"] == 5.0


def test_survival_walk_applies_explicit_deferred_damage_in_equal_ticks():
    source = _dummy_combatant("source", "main", health=100.0)
    target = _dummy_combatant("target", "enemy", health=100.0)
    result = _simulate_survival(
        [source, target],
        {
            "target": [
                {
                    "time": 0.0,
                    "damage": 50.0,
                    "damage_type": "physical",
                    "attacker": "source",
                    "sequence": 0,
                    "_event_id": "deferred",
                    "deferred_fraction": 0.4,
                    "deferred_duration": 3.0,
                    "deferred_ticks": 3,
                }
            ]
        },
        {},
        {},
        10.0,
    )
    # 30 lands immediately and 20 true damage is reconciled at 1s, 2s, 3s.
    assert result["target"]["damage_taken"] == 50.0
    assert result["target"]["ending_health"] == 50.0
    assert result["target"]["death_time"] is None


def test_deferred_ticks_are_mirrored_into_the_public_outgoing_receipt():
    source = _dummy_combatant("source", "main", health=100.0)
    target = _dummy_combatant("target", "enemy", health=100.0)
    event = {
        "time": 0.0,
        "damage": 50.0,
        "damage_type": "physical",
        "attacker": "source",
        "target": "target",
        "sequence": 0,
        "_event_id": "deferred-receipt",
        "deferred_fraction": 0.4,
        "deferred_duration": 3.0,
        "deferred_ticks": 3,
    }
    outgoing = {"source": [event]}
    _simulate_survival(
        [source, target],
        {"target": [event]},
        {},
        {},
        10.0,
        receipt_events=outgoing,
    )
    receipt = outgoing["source"]
    assert [row["_event_id"] for row in receipt] == [
        "deferred-receipt",
        "deferred-receipt:deferred:1",
        "deferred-receipt:deferred:2",
        "deferred-receipt:deferred:3",
    ]
    assert [row["damage"] for row in receipt] == pytest.approx(
        [30.0, 20.0 / 3, 20.0 / 3, 20.0 / 3]
    )
    assert sum(row["damage"] for row in receipt) == pytest.approx(50.0)
    assert all(row["_deferred_from"] == "deferred-receipt" for row in receipt[1:])


def test_survival_walk_redirects_an_authored_damage_fraction_to_holder():
    source = _dummy_combatant("source", "enemy", health=100.0)
    protected = _dummy_combatant("protected", "main", health=100.0)
    holder = _dummy_combatant("holder", "main", health=100.0)
    result = _simulate_survival(
        [source, protected, holder],
        {
            "protected": [
                {
                    "time": 0.0,
                    "damage": 40.0,
                    "damage_type": "physical",
                    "attacker": "source",
                    "target": "protected",
                    "sequence": 0,
                    "_event_id": "redirected",
                    "redirect_fraction": 0.5,
                    "redirect_target": "holder",
                }
            ]
        },
        {},
        {},
        10.0,
    )
    assert result["protected"]["health_damage"] == 20.0
    assert result["holder"]["health_damage"] == 20.0


def test_redirect_clone_is_mirrored_into_the_public_outgoing_receipt():
    source = _dummy_combatant("source", "enemy", health=100.0)
    protected = _dummy_combatant("protected", "main", health=100.0)
    holder = _dummy_combatant("holder", "main", health=100.0)
    event = {
        "time": 0.0,
        "damage": 40.0,
        "damage_type": "physical",
        "attacker": "source",
        "target": "protected",
        "sequence": 0,
        "_event_id": "redirect-receipt",
        "redirect_fraction": 0.5,
        "redirect_target": "holder",
    }
    outgoing = {"source": [event]}
    _simulate_survival(
        [source, protected, holder],
        {"protected": [event]},
        {},
        {},
        10.0,
        receipt_events=outgoing,
    )
    receipt = outgoing["source"]
    assert [row["_event_id"] for row in receipt] == [
        "redirect-receipt",
        "redirect-receipt:redirect",
    ]
    assert [row["target"] for row in receipt] == ["protected", "holder"]
    assert [row["damage"] for row in receipt] == pytest.approx([20.0, 20.0])
    assert sum(row["damage"] for row in receipt) == pytest.approx(40.0)
    assert receipt[1]["_redirected_from"] == "protected"


def test_survival_walk_blocks_stasis_damage_and_allows_explicit_revive():
    source = _dummy_combatant("source", "enemy", health=100.0)
    target = _dummy_combatant("target", "main", health=50.0)
    result = _simulate_survival(
        [source, target],
        {
            "target": [
                {
                    "time": 0.5,
                    "damage": 100.0,
                    "damage_type": "physical",
                    "attacker": "source",
                    "sequence": 0,
                    "_event_id": "blocked",
                },
                {
                    "time": 1.5,
                    "damage": 60.0,
                    "damage_type": "physical",
                    "attacker": "source",
                    "sequence": 1,
                    "_event_id": "kill",
                },
                {
                    "time": 3.0,
                    "damage": 60.0,
                    "damage_type": "physical",
                    "attacker": "source",
                    "sequence": 2,
                    "_event_id": "after-revive",
                },
            ]
        },
        {
            "target": [
                {
                    "time": 0.0,
                    "kind": "stasis",
                    "duration": 1.0,
                    "attacker": "target",
                    "source": "Time Stop",
                },
                {
                    "time": 2.0,
                    "kind": "revive",
                    "health_ratio": 0.5,
                    "attacker": "target",
                    "source": "Rebirth",
                },
            ]
        },
        {},
        10.0,
    )
    assert result["target"]["first_death_time"] == 1.5
    assert result["target"]["revived"] is True
    assert result["target"]["revive_time"] == 2.0
    assert result["target"]["revive_health_restored"] == 25.0
    assert result["target"]["revive_source"] == "Rebirth"
    assert result["target"]["terminal_phase"] == "dead"
    assert result["target"]["ending_health"] == 0.0


def test_revive_after_fight_window_cannot_change_terminal_state():
    source = _dummy_combatant("source", "enemy", health=100.0)
    target = _dummy_combatant("target", "main", health=50.0)
    damage = {
        "target": [
            {
                "time": 1.0,
                "damage": 60.0,
                "damage_type": "physical",
                "attacker": "source",
                "_event_id": "window-kill",
            }
        ]
    }
    support = {
        "target": [
            {
                "time": 11.0,
                "kind": "revive",
                "health_ratio": 0.5,
                "source": "Rebirth",
            }
        ]
    }
    result = _simulate_survival([source, target], damage, {}, support, 10.0)
    assert result["target"]["first_death_time"] == 1.0
    assert result["target"]["revived"] is False
    assert result["target"]["terminal_phase"] == "dead"
    assert support["target"][0]["skipped_reason"] == "outside_window"


def test_post_window_damage_receipt_preserves_pair_amount_and_skip_reason():
    source = _dummy_combatant("source", "main", health=100.0)
    target = _dummy_combatant("target", "enemy", health=100.0)
    event = {
        "time": 11.0,
        "damage": 60.0,
        "damage_type": "physical",
        "attacker": "source",
        "target": "target",
        "sequence": 0,
        "_event_id": "late-damage",
    }
    outgoing = {"source": [event]}
    _simulate_survival(
        [source, target],
        {"target": [event]},
        {},
        {},
        10.0,
        receipt_events=outgoing,
    )
    assert event["damage"] == 0.0
    assert event["pair_damage"] == 60.0
    assert event["skipped_reason"] == "outside_window"


def test_survival_walk_applies_collector_execute_as_terminal_state():
    """The Collector threshold kills without adding synthetic damage."""
    source = _dummy_combatant("source", "main", health=100.0)
    target = _dummy_combatant("target", "enemy", health=100.0)
    execute_event = {
        "time": 1.0,
        "damage": 96.0,
        "damage_type": "physical",
        "attacker": "source",
        "source": "The Collector",
        "execute_threshold_ratio": 0.05,
        "execute_source": "The Collector",
        "sequence": 0,
        "_event_id": "collector",
    }
    result = _simulate_survival(
        [source, target],
        {"target": [execute_event]},
        {},
        {},
        10.0,
    )

    assert result["target"]["ending_health"] == 0.0
    assert result["target"]["execute_time"] == 1.0
    assert result["target"]["execute_source"] == "The Collector"
    assert result["target"]["health_damage"] == 96.0
    assert execute_event["execute_triggered"] is True


def test_survival_walk_arms_threshold_shield_before_crossing_health_boundary():
    source = _dummy_combatant("source", "enemy", health=100.0)
    target = _dummy_combatant("target", "main", health=100.0)
    target = Combatant(
        participant_id=target.participant_id,
        team=target.team,
        champion_data=target.champion_data,
        level=target.level,
        items=target.items,
        stats=target.stats,
        defenses=SimpleNamespace(
            magic_shield=0.0,
            physical_shield=0.0,
            general_shield=0.0,
            threshold_shield_amount=30.0,
            threshold_shield_health_ratio=0.3,
            threshold_shield_duration=3.0,
            threshold_shield_damage_type="all",
        ),
    )
    result = _simulate_survival(
        [source, target],
        {
            "target": [
                {
                    "time": 0.0,
                    "damage": 80.0,
                    "damage_type": "physical",
                    "attacker": "source",
                    "sequence": 0,
                    "_event_id": "lifeline",
                }
            ]
        },
        {},
        {},
        10.0,
    )
    assert result["target"]["threshold_shield_triggered"] is True
    assert result["target"]["shield_absorbed"] == 30.0
    assert result["target"]["ending_health"] == 50.0
    assert result["target"]["ending_health_ratio"] == 0.5


def test_threshold_shield_receipt_marks_expiry_without_late_trigger():
    source = _dummy_combatant("source", "enemy", health=100.0)
    target = Combatant(
        participant_id="target",
        team="main",
        champion_data={"name": "target"},
        level=1,
        items=(),
        stats={"health": 100.0},
        defenses=SimpleNamespace(
            magic_shield=0.0,
            physical_shield=0.0,
            general_shield=0.0,
            threshold_shield_amount=30.0,
            threshold_shield_health_ratio=0.3,
            threshold_shield_duration=3.0,
            threshold_shield_damage_type="magic",
        ),
    )
    result = _simulate_survival(
        [source, target],
        {
            "target": [
                {
                    "time": 4.0,
                    "damage": 80.0,
                    "damage_type": "physical",
                    "attacker": "source",
                    "_event_id": "late-lifeline",
                }
            ]
        },
        {},
        {},
        10.0,
    )
    assert result["target"]["threshold_shield_triggered"] is False
    assert result["target"]["threshold_shield_expired_at"] == 3.0
    assert result["target"]["shield_absorbed"] == 0.0


def test_threshold_shield_trigger_is_preserved_on_damage_receipt():
    source = _dummy_combatant("source", "enemy", health=100.0)
    target = Combatant(
        participant_id="target",
        team="main",
        champion_data={"name": "target"},
        level=1,
        items=(),
        stats={"health": 100.0},
        defenses=SimpleNamespace(
            magic_shield=0.0,
            physical_shield=0.0,
            general_shield=0.0,
            threshold_shield_amount=30.0,
            threshold_shield_health_ratio=0.3,
            threshold_shield_duration=3.0,
            threshold_shield_damage_type="all",
        ),
    )
    event = {
        "time": 0.0,
        "damage": 80.0,
        "damage_type": "physical",
        "attacker": "source",
        "target": "target",
        "_event_id": "lifeline-receipt",
    }
    outgoing = {"source": [event]}
    _simulate_survival(
        [source, target], {"target": [event]}, {}, {}, 10.0, receipt_events=outgoing
    )
    assert event["threshold_shield_triggered"] is True


def test_authored_reactive_packet_requires_trigger_and_wounds_striker():
    incoming = {
        "wearer": [
            {
                "time": 0.0,
                "damage": 20.0,
                "damage_type": "physical",
                "source_key": "auto_attacks",
                "attacker": "striker",
                "target": "wearer",
                "trigger_kind": "basic_attack",
                "sequence": 0,
                "_event_id": "swing",
                "reactive_packets": [
                    {
                        "reactive_trigger": "basic_attack",
                        "damage": 10.0,
                        "damage_type": "magic",
                        "source_key": "thornmail_thorns",
                        "source": "Thornmail (Thorns)",
                        "grievous_duration": 3.0,
                        "wound_source": "Thornmail · Thorns",
                    }
                ],
            }
        ],
        "striker": [],
    }
    outgoing = {"wearer": list(incoming["wearer"]), "striker": []}
    _schedule_authored_reactive_events(incoming, outgoing)
    [packet] = [
        event
        for event in incoming["striker"]
        if event.get("source_key") == "thornmail_thorns"
    ]
    assert packet["_reactive"] is True
    assert packet["_trigger_event_id"] == "swing"
    assert packet["grievous_duration"] == 3.0
    assert packet in outgoing["wearer"]


def test_authored_reactive_packet_with_wrong_trigger_is_ignored():
    incoming = {
        "wearer": [
            {
                "time": 0.0,
                "damage": 20.0,
                "attacker": "striker",
                "target": "wearer",
                "trigger_kind": "ability",
                "_event_id": "spell",
                "reactive_packets": [
                    {
                        "reactive_trigger": "basic_attack",
                        "damage": 10.0,
                        "damage_type": "magic",
                        "source_key": "thornmail_thorns",
                    }
                ],
            }
        ],
        "striker": [],
    }
    outgoing = {"wearer": list(incoming["wearer"]), "striker": []}
    _schedule_authored_reactive_events(incoming, outgoing)
    assert incoming["striker"] == []


def test_spell_shield_consumes_one_authored_ability_but_not_auto_attack():
    source = _dummy_combatant("source", "enemy", health=100.0)
    target = _dummy_combatant("target", "main", health=100.0)
    result = _simulate_survival(
        [source, target],
        {
            "target": [
                {
                    "time": 0.5,
                    "damage": 40.0,
                    "damage_type": "magic",
                    "attacker": "source",
                    "target": "target",
                    "is_ability": True,
                    "sequence": 0,
                    "_event_id": "spell",
                },
                {
                    "time": 1.0,
                    "damage": 20.0,
                    "damage_type": "physical",
                    "attacker": "source",
                    "target": "target",
                    "source_key": "auto_attacks",
                    "sequence": 1,
                    "_event_id": "auto",
                },
            ]
        },
        {},
        {
            "target": [
                {
                    "time": 0.0,
                    "kind": "spell_shield",
                    "duration": 2.0,
                    "attacker": "target",
                    "source": "Annul",
                }
            ]
        },
        10.0,
    )
    assert result["target"]["damage_taken"] == 20.0
    assert result["target"]["spell_shield_used"] is True
    assert result["target"]["spell_shield_source"] == "Annul"
    assert result["target"]["spell_shield_until"] == 2.0


def test_opening_annul_from_item_blocks_first_canonical_ability():
    source = _dummy_combatant("source", "enemy", health=100.0)
    target = Combatant(
        participant_id="target",
        team="main",
        champion_data={"name": "target"},
        level=1,
        items=(),
        stats={"health": 100.0},
        defenses=resolve_starting_defenses(
            "Ahri", 18, {"health": 100.0}, [{"name": "Banshee's Veil"}]
        ),
    )
    events = [
        {
            "time": 0.0,
            "damage": 40.0,
            "damage_type": "magic",
            "source_key": "Q",
            "is_ability": True,
            "attacker": "source",
            "target": "target",
            "sequence": 0,
            "_event_id": "q",
        },
        {
            "time": 0.0,
            "damage": 15.0,
            "damage_type": "true",
            "source_key": "Q",
            "is_ability": True,
            "attacker": "source",
            "target": "target",
            "sequence": 1,
            "_event_id": "q-recast",
        },
        {
            "time": 0.5,
            "damage": 20.0,
            "damage_type": "physical",
            "source_key": "auto_attacks",
            "attacker": "source",
            "target": "target",
            "sequence": 2,
            "_event_id": "auto",
        },
    ]
    result = _simulate_survival([source, target], {"target": events}, {}, {}, 10.0)

    assert result["target"]["damage_taken"] == 20.0
    assert result["target"]["spell_shield_used"] is True
    assert result["target"]["spell_shield_source"] == "Banshee's Veil — Annul"
    assert result["target"]["spell_shield_until"] is None


def test_spell_shield_block_receipt_preserves_authored_source():
    source = _dummy_combatant("source", "enemy", health=100.0)
    target = _dummy_combatant("target", "main", health=100.0)
    event = {
        "time": 0.5,
        "damage": 40.0,
        "damage_type": "magic",
        "attacker": "source",
        "target": "target",
        "is_ability": True,
        "sequence": 0,
        "_event_id": "spell-source",
    }
    outgoing = {"source": [event]}
    _simulate_survival(
        [source, target],
        {"target": [event]},
        {},
        {
            "target": [
                {
                    "time": 0.0,
                    "kind": "spell_shield",
                    "duration": 2.0,
                    "source": "Annul",
                }
            ]
        },
        10.0,
        receipt_events=outgoing,
    )
    assert event["skipped_reason"] == "spell_shield"
    assert event["spell_shield_source"] == "Annul"


def test_stasis_blocks_the_stasis_holder_outgoing_packet_until_expiry():
    holder = _dummy_combatant("holder", "main", health=100.0)
    target = _dummy_combatant("target", "enemy", health=100.0)
    result = _simulate_survival(
        [holder, target],
        {
            "target": [
                {
                    "time": 0.5,
                    "damage": 30.0,
                    "damage_type": "magic",
                    "attacker": "holder",
                    "target": "target",
                    "is_ability": True,
                    "sequence": 0,
                    "_event_id": "blocked-cast",
                },
                {
                    "time": 2.0,
                    "damage": 30.0,
                    "damage_type": "magic",
                    "attacker": "holder",
                    "target": "target",
                    "is_ability": True,
                    "sequence": 1,
                    "_event_id": "live-cast",
                },
            ]
        },
        {},
        {
            "holder": [
                {
                    "time": 0.0,
                    "kind": "stasis",
                    "duration": 1.0,
                    "attacker": "holder",
                    "source": "Time Stop",
                }
            ]
        },
        10.0,
    )
    assert result["target"]["damage_taken"] == 30.0


def test_stasis_receipt_carries_authored_source_and_start_time():
    holder = _dummy_combatant("holder", "main", health=100.0)
    target = _dummy_combatant("target", "enemy", health=100.0)
    result = _simulate_survival(
        [holder, target],
        {},
        {},
        {
            "holder": [
                {
                    "time": 0.25,
                    "kind": "stasis",
                    "duration": 2.5,
                    "attacker": "holder",
                    "source": "Tempered Fate",
                }
            ]
        },
        10.0,
    )
    assert result["holder"]["stasis_started_at"] == 0.25
    assert result["holder"]["stasis_until"] == 2.75
    assert result["holder"]["stasis_source"] == "Tempered Fate"


def test_invulnerability_and_untargetability_receipts_expose_expiry_boundaries():
    holder = _dummy_combatant("holder", "main", health=100.0)
    support = {
        "holder": [
            {"time": 0.5, "kind": "invulnerability", "duration": 1.25},
            {"time": 1.0, "kind": "untargetable", "duration": 2.0},
        ]
    }
    result = _simulate_survival(
        [holder],
        {},
        {},
        support,
        10.0,
    )
    assert result["holder"]["invulnerable_until"] == 1.75
    assert result["holder"]["untargetable_until"] == 3.0
    assert [event["_event_id"] for event in support["holder"]] == [
        "holder:support:0",
        "holder:support:1",
    ]


def test_healing_receipt_separates_applied_amount_from_overheal():
    source = _dummy_combatant("source", "main", health=100.0)
    target = _dummy_combatant("target", "main", health=100.0)
    healing = {
        "target": [
            {
                "time": 0.0,
                "amount": 50.0,
                "attacker": "source",
                "source": "authored sustain",
            }
        ]
    }
    result = _simulate_survival([source, target], {}, healing, {}, 10.0)
    assert result["target"]["healing_received"] == 0.0
    assert result["target"]["overhealing"] == 50.0
    assert healing["target"][0]["overheal"] == 50.0


def test_grievous_window_expiry_clears_stale_source_composition():
    early = _dummy_combatant("early", "enemy", health=100.0)
    late = _dummy_combatant("late", "enemy", health=100.0)
    target = _dummy_combatant("target", "main", health=100.0)
    incoming = {
        "target": [
            {
                "time": 0.0,
                "damage": 10.0,
                "damage_type": "magic",
                "attacker": "early",
                "target": "target",
                "grievous_duration": 3.0,
                "_wound_source": "Early Wound",
                "_event_id": "early-wound",
            },
            {
                "time": 4.0,
                "damage": 10.0,
                "damage_type": "magic",
                "attacker": "late",
                "target": "target",
                "grievous_duration": 3.0,
                "_wound_source": "Late Wound",
                "_event_id": "late-wound",
            },
        ]
    }
    healing = {
        "target": [
            {
                "time": 4.1,
                "amount": 10.0,
                "attacker": "target",
                "source": "post-expiry heal",
            }
        ]
    }
    result = _simulate_survival([early, late, target], incoming, healing, {}, 10.0)
    assert result["target"]["healing_received"] == 6.0
    assert result["target"]["healing_reduction_events"][-1]["sources"] == ["Late Wound"]


def test_authored_temporary_health_support_expires_and_clamps_health():
    source = _dummy_combatant("source", "main", health=100.0)
    target = _dummy_combatant("target", "main", health=100.0)
    support_effects = {
        "target": [
            {
                "time": 0.0,
                "kind": "temporary_health",
                "amount": 50.0,
                "duration": 2.0,
                "attacker": "source",
                "source": "Solstice Sleigh",
            }
        ]
    }
    result = _simulate_survival(
        [source, target],
        {
            "target": [
                {
                    "time": 1.0,
                    "damage": 120.0,
                    "damage_type": "physical",
                    "attacker": "source",
                    "target": "target",
                    "sequence": 0,
                    "_event_id": "damage",
                }
            ]
        },
        {},
        support_effects,
        10.0,
    )
    assert result["target"]["temporary_health_received"] == 50.0
    assert result["target"]["temporary_health_until"] == 0.0
    assert result["target"]["temporary_health_expired_at"] == 2.0
    assert result["target"]["temporary_health_source"] == "Solstice Sleigh"
    assert result["target"]["max_health"] == 100.0
    assert result["target"]["ending_health"] == 30.0
    assert support_effects["target"][0]["expires_at"] == 2.0


def test_heal_overflow_can_become_temporary_health_and_expires():
    source = _dummy_combatant("source", "main")
    target = _dummy_combatant("target", "enemy")
    healing = {
        "target": [
            {
                "time": 0.0,
                "amount": 50.0,
                "kind": "item_proc",
                "attacker": "target",
                "source": "Sundered Sky (Lightshield Strike)",
                "overheal_to_temporary_health": True,
                "temporary_health_duration": 2.0,
            }
        ]
    }
    result = _simulate_survival([source, target], {"target": []}, healing, {}, 5.0)
    event = healing["target"][0]
    assert result["target"]["healing_received"] == 0.0
    assert result["target"]["overhealing"] == 0.0
    assert result["target"]["temporary_health_received"] == 50.0
    assert result["target"]["temporary_health_expired_at"] == 2.0
    assert result["target"]["max_health"] == 100.0
    assert result["target"]["ending_health"] == 100.0
    assert event["temporary_health"] == 50.0
    assert event["overheal"] == 0.0


def test_compiled_heal_overflow_matches_temporary_health_expiry():
    action = (
        (0.0, 1.0, 0, 0, 0, "target", "heal", "Sundered Sky"),
        1,
        0,
        0,
        -1,
        0,
        50.0,
        2,
        None,
        0.0,
        None,
        2.0,
        False,
        0.0,
    )
    rows, applied = _compiled_survival_walk(
        [action], 1, [100.0], [(0.0, 0.0, 0.0)], 5.0, [1.0]
    )
    assert applied == [0.0]
    assert rows[0]["temporary_health_received"] == 50.0
    assert rows[0]["temporary_health_expired_at"] == 2.0
    assert rows[0]["max_health"] == 100.0
    assert rows[0]["ending_health"] == 100.0


def test_bramble_vest_retaliation_flows_through_the_calculate_pipeline():
    """Main with Bramble Vest: enemy autos generate thorns events attributed
    to main, and the enemy is Grievous-Wounded."""
    app.config["TESTING"] = True
    response = app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Ahri",
            "level": 18,
            "items": ["Bramble Vest"],
            "fight_mode": "time_based",
            "fight_duration": 5,
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
            "enemies": [{"champion": "Aatrox", "level": 18, "items": []}],
        },
    )
    assert response.status_code == 200
    combat = response.get_json()["combat"]
    thorns_events = [
        event for event in combat["events"] if event["source"] == "thorns_Bramble Vest"
    ]
    assert thorns_events
    assert all(event["attacker"] == "main" for event in thorns_events)
    assert all(event["target"] == "enemy:Aatrox" for event in thorns_events)
    assert all("sequence" in event for event in thorns_events)
    enemy = next(
        participant
        for participant in combat["participants"]
        if participant["participant_id"] == "enemy:Aatrox"
    )
    assert any(
        "Bramble Vest" in source
        for source in enemy["survival"]["healing_reduction_sources"]
    )


def test_bramble_vest_retaliates_against_forced_basic_attack_casts():
    """Empowered attacks carried by an ability row still trigger Thorns."""
    app.config["TESTING"] = True
    response = app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Blitzcrank",
            "level": 18,
            "fight_mode": "one_rotation",
            "include_auto_attacks": False,
            "cast_order": ["E", "Q", "W", "R"],
            "enemies": [{"champion": "Ahri", "level": 18, "items": ["Bramble Vest"]}],
        },
    )
    assert response.status_code == 200
    combat = response.get_json()["combat"]
    thorns_events = [
        event for event in combat["events"] if event["source"] == "thorns_Bramble Vest"
    ]
    assert thorns_events
    assert all(event["attacker"] == "enemy:Ahri" for event in thorns_events)
    assert all(event["target"] == "main" for event in thorns_events)


def _coupled_fixture():
    """One small coupled roster shared by the cache-equivalence tests."""
    from src.calculator.defensive_effects import resolve_starting_defenses
    from src.calculator.scenario import ChampionLoadout
    from src.calculator.stats import calculate_total_stats

    params = FightParams.from_request(
        {"fight_mode": "one_rotation", "role": "mid"}, deterministic=True
    )
    champion = get_champion("Cassiopeia")
    enemies = [
        ChampionLoadout(
            champion="Alistar",
            level=13,
            role="support",
            boots="Plated Steelcaps",
            items=("Randuin's Omen", "Bramble Vest"),
        ).resolve(),
        ChampionLoadout(
            champion="Dr. Mundo",
            level=13,
            role="top",
            boots="Mercury's Treads",
            items=("Kaenic Rookern", "Warmog's Armor"),
        ).resolve(),
    ]

    def timeline(items, **kwargs):
        stats = calculate_total_stats(champion, 13, items, role="mid")
        defenses = resolve_starting_defenses(champion["name"], 13, stats, items)
        return build_participant_timeline(
            champion,
            13,
            items,
            params,
            main_stats=stats,
            main_defenses=defenses,
            enemies=enemies,
            allies=[],
            **kwargs,
        )

    return timeline


def test_shared_pair_cache_replays_identical_coupled_receipts():
    """Cache hits and misses must reproduce the no-cache receipt exactly.

    Two offense-only builds share one defensive signature (the second is a
    pure cache hit for the incoming fights); the health item changes the
    signature and forces a miss.  Every cached receipt must deep-equal a
    fresh no-cache computation.
    """
    timeline = _coupled_fixture()
    cache: dict = {}
    builds = [
        [get_item_by_name("Rabadon's Deathcap")],
        [get_item_by_name("Void Staff")],
        [get_item_by_name("Rylai's Crystal Scepter")],
    ]
    for items in builds:
        cached = timeline(items, pair_result_cache=cache)
        fresh = timeline(items)
        assert cached == fresh
    assert cache, "the pair cache was never populated"


def test_score_only_receipt_matches_full_receipt_numbers():
    """include_receipt=False must change shape only, never a number."""
    timeline = _coupled_fixture()
    items = [get_item_by_name("Rabadon's Deathcap")]
    full = timeline(items)
    score_only = timeline(items, include_receipt=False)

    assert score_only["timeline_coverage"] == full["timeline_coverage"]
    full_rows = {row["participant_id"]: row for row in full["breakdown"]}
    for row in score_only["breakdown"]:
        assert row["total_damage"] == full_rows[row["participant_id"]]["total_damage"]
    full_survival = {
        participant["participant_id"]: participant["survival"]
        for participant in full["participants"]
    }
    for participant in score_only["participants"]:
        assert participant["survival"] == full_survival[participant["participant_id"]]


def test_search_context_score_walk_matches_legacy_score_receipts():
    """The compiled search-context walk is pure speed, never a number.

    Scoring through a CoupledSearchContext (per-signature compiled panel of
    invariant walk actions, no-copy flat walk) must deep-equal the legacy
    score-only composition for every candidate: signature repeats reuse the
    panel, a health item forces a new signature, and an exact build repeat
    replays both paths again.
    """
    from src.calculator.participant_timeline import CoupledSearchContext

    timeline = _coupled_fixture()
    cache: dict = {}
    context = CoupledSearchContext()
    builds = [
        [get_item_by_name("Rabadon's Deathcap")],
        [get_item_by_name("Void Staff")],
        [get_item_by_name("Rylai's Crystal Scepter")],
        [get_item_by_name("Rabadon's Deathcap")],
    ]
    for items in builds:
        fast = timeline(
            items,
            pair_result_cache=cache,
            search_context=context,
            include_receipt=False,
        )
        legacy = timeline(items, include_receipt=False)
        assert fast == legacy
    assert len(context.panels) == 2, "expected one shared and one new signature"


def test_search_context_keeps_item_heals_and_ignores_post_window_packets():
    """Compiled scoring matches the event walk for item-owned healing.

    Ahri has no champion healing rule, so this exercises the item-owned
    Dusk-and-Dawn Spellblade heal path.  The second proc is timestamped at
    4.5s while the authored fight window ends at 4s and must not affect the
    score-only survival walk.
    """
    from src.calculator.defensive_effects import resolve_starting_defenses
    from src.calculator.participant_timeline import CoupledSearchContext
    from src.calculator.scenario import ChampionLoadout
    from src.calculator.stats import calculate_total_stats

    params = FightParams.from_request(
        {
            "fight_mode": "time_based",
            "fight_duration": 4,
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
            "role": "mid",
        },
        deterministic=True,
    )
    champion = get_champion("Ahri")
    items = [get_item_by_name("Dusk and Dawn")]
    stats = calculate_total_stats(champion, 18, items, role="mid")
    defenses = resolve_starting_defenses(champion["name"], 18, stats, items)
    enemies = [ChampionLoadout(champion="Aatrox", level=18, role="top").resolve()]

    kwargs = {
        "main_stats": stats,
        "main_defenses": defenses,
        "enemies": enemies,
        "allies": [],
        "reuse_main_stats": True,
        "include_receipt": False,
    }
    legacy = build_participant_timeline(champion, 18, items, params, **kwargs)
    fast = build_participant_timeline(
        champion,
        18,
        items,
        params,
        pair_result_cache={},
        search_context=CoupledSearchContext(),
        **kwargs,
    )

    assert fast == legacy
    main = next(row for row in fast["participants"] if row["participant_id"] == "main")
    assert main["survival"]["healing_received"] == 15.0


def test_search_context_replays_the_rounded_death_cutoff():
    """A dead attacker's outgoing total cuts at its ROUNDED death time.

    The legacy composition filters each attacker's events by the survival
    row's death time, which is rounded to three decimals — so an attacker's
    own event landing at the exact death instant is applied by the walk but
    excluded from the total whenever the true death time rounds down past
    it.  A mirror matchup with equal attack speeds reproduces that
    coincidence deterministically: main Aatrox (no items) dies to an
    itemized enemy Aatrox mid-window with a same-instant auto of his own.
    """
    from src.calculator.defensive_effects import resolve_starting_defenses
    from src.calculator.participant_timeline import CoupledSearchContext
    from src.calculator.scenario import ChampionLoadout
    from src.calculator.stats import calculate_total_stats

    params = FightParams.from_request(
        {
            "fight_mode": "time_based",
            "fight_duration": 10,
            "include_auto_attacks": True,
            "auto_attack_uptime": 0.8,
            "role": "top",
        },
        deterministic=True,
    )
    champion = get_champion("Aatrox")
    enemies = [
        ChampionLoadout(
            champion="Aatrox",
            level=13,
            role="top",
            items=("Bloodthirster", "Infinity Edge"),
        ).resolve()
    ]
    stats = calculate_total_stats(champion, 13, [], role="top")
    defenses = resolve_starting_defenses(champion["name"], 13, stats, [])

    def timeline(**kwargs):
        return build_participant_timeline(
            champion,
            13,
            [],
            params,
            main_stats=stats,
            main_defenses=defenses,
            enemies=enemies,
            allies=[],
            reuse_main_stats=True,
            **kwargs,
        )

    fast = timeline(
        pair_result_cache={},
        search_context=CoupledSearchContext(),
        include_receipt=False,
    )
    legacy = timeline(include_receipt=False)
    main_survival = next(
        row["survival"]
        for row in legacy["participants"]
        if row["participant_id"] == "main"
    )
    assert (
        main_survival["death_time"] is not None
    ), "the fixture must kill the main mid-window to exercise the cutoff"
    assert fast == legacy


def test_support_attributes_match_the_profile_lookup_source():
    """The support-candidate gate must cover exactly the profile lookups.

    ``derive_ally_effects`` skips champions via ``_SUPPORT_ATTRIBUTES``;
    an attribute added to ``_support_profile``'s lookups without extending
    that set would silently drop the champion's packets, so the set is
    pinned to the ``_first_attribute`` tuples actually in the source.
    """
    import inspect
    import re as re_module

    from src.calculator import support_effects

    source = inspect.getsource(support_effects._support_profile)
    lookups = re_module.findall(r"_first_attribute\(\s*ability,\s*\(([^)]*)\)", source)
    assert lookups, "expected _first_attribute lookups in _support_profile"
    named = set()
    for group in lookups:
        named.update(re_module.findall(r'"([^"]+)"', group))
    assert named == set(support_effects._SUPPORT_ATTRIBUTES)


def test_healing_rule_champions_matches_the_dispatch_source():
    """The scoring fast path skips heal derivation via HEALING_RULE_CHAMPIONS.

    A heal rule added to ``derive_self_healing``'s name dispatch without
    extending that set would be silently skipped in scoring, so the set is
    pinned to the dispatch branches actually present in the source.
    """
    import inspect
    import re as re_module

    from src.calculator import healing

    source = inspect.getsource(healing.derive_self_healing)
    dispatched = set(re_module.findall(r'name == "([^"]+)"', source))
    assert dispatched == set(healing.HEALING_RULE_CHAMPIONS)


def test_search_context_walk_matches_receipts_with_thorns_support_and_heals():
    """The compiled walk must survive every coupled mechanic at once.

    A timed fight with auto attacks exercises the paths the one-rotation
    fixture cannot: Bramble thorns strike-backs and their Grievous window on
    the main attacker, sourced enemy self-healing, an opt-in Lulu ally
    shield, target-current-health repricing (Dr. Mundo's own kit), and
    death cutoffs.  Fast and legacy score receipts must be deep-equal.
    """
    from src.calculator.defensive_effects import resolve_starting_defenses
    from src.calculator.participant_timeline import CoupledSearchContext
    from src.calculator.scenario import ChampionLoadout
    from src.calculator.stats import calculate_total_stats

    params = FightParams.from_request(
        {
            "fight_mode": "time_based",
            "fight_duration": 10,
            "include_auto_attacks": True,
            "auto_attack_uptime": 0.8,
            "role": "top",
        },
        deterministic=True,
    )
    champion = get_champion("Dr. Mundo")
    enemies = [
        ChampionLoadout(
            champion="Alistar",
            level=13,
            role="support",
            boots="Plated Steelcaps",
            items=("Bramble Vest",),
        ).resolve(),
        ChampionLoadout(
            champion="Aatrox",
            level=13,
            role="top",
            boots="Mercury's Treads",
            items=("Spirit Visage",),
        ).resolve(),
    ]
    allies = [
        ChampionLoadout(
            champion="Lulu",
            level=13,
            role="support",
            items=("Dead Man's Plate",),
            ally_effects_enabled=True,
        ).resolve(),
    ]

    def timeline(items, **kwargs):
        stats = calculate_total_stats(champion, 13, items, role="top")
        defenses = resolve_starting_defenses(champion["name"], 13, stats, items)
        return build_participant_timeline(
            champion,
            13,
            items,
            params,
            main_stats=stats,
            main_defenses=defenses,
            enemies=enemies,
            allies=allies,
            reuse_main_stats=True,
            **kwargs,
        )

    cache: dict = {}
    context = CoupledSearchContext()
    builds = [
        [get_item_by_name("Oblivion Orb")],
        [get_item_by_name("Warmog's Armor")],
    ]
    for items in builds:
        fast = timeline(
            items,
            pair_result_cache=cache,
            search_context=context,
            include_receipt=False,
        )
        legacy = timeline(items, include_receipt=False)
        assert fast == legacy
