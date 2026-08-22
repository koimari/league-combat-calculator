"""Regression coverage for coupled participant combat receipts."""

from dataclasses import replace

import pytest

from src.calculator.program.build import roster_program as _roster_program
from src.calculator.program.views.survival import survival as _survival_view
from src.calculator.program.views import LeafWriter, name_every_number
from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.pipeline import FightParams, run_fight
from src.calculator.defensive_effects import (
    StartingDefenses,
    resolve_starting_defenses,
)
from src.calculator.program.build import dropped_preview_mechanics
from src.calculator.scenario import (
    ChampionLoadout,
    parse_scenario_request,
    resolve_scenario,
)
from src.calculator.stats import calculate_total_stats
from src.app import app
import src.calculator.bis as bis_module
from src.calculator.bis import enemy_bis_rank_key, role_scoped_bis_candidates
from src.calculator.item_coverage import optimizer_supported_items
from src.calculator.optimizer import get_eligible_legendaries
from src.calculator.participant_timeline import (
    ActorRequest,
    Combatant,
    CoupledSearchContext,
    _actor_params,
    _owned_state_event_id,
    _schedule_authored_reactive_events,
    _schedule_thorns_events,
    _regeneration_windows,
    _simulate_survival,
    build_participant_timeline,
)
from src.calculator.program.build import roster_program
from src.calculator.program.views.survival import survival
from src.calculator.program.walk import walk as run_one_walk
from src.calculator.survival import (
    EVENT_SLOTS,
    SUPPORT_RANK_KEY,
    ActionKind,
    ScoreLedger,
    SurvivalAction,
    TransitionContext,
    TransitionRank,
    build_states,
    finalize_states,
    run_survival_walk,
)


def _simulated_rows(combatants, *args, **kwargs):
    """The published survival rows for one simulated walk.

    ``_simulate_survival`` returns the frozen walk result from S9 on, because
    the composition hands that one result to five views.  These tests read the
    published rows, so they project it through the survival view exactly as
    the composition does.
    """
    return _survival_view(
        _roster_program(combatants),
        _simulate_survival(combatants, *args, **kwargs),
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
        defenses=StartingDefenses(),
        request=ActorRequest(
            ability_ranks={},
            champion_options={},
            item_options={"Heartsteel": {"bonus_health": 700}},
        ),
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
        defenses=StartingDefenses(),
        request=ActorRequest(),
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
    assert survival["action_downtime"] == pytest.approx(4.0, abs=1e-3)
    assert survival["action_downtime_intervals"] == [
        {
            "recipient": "enemy:Aatrox",
            "kind": "death",
            "start": survival["first_death_time"],
            "end": survival["revive_time"],
            "source": "auto_attacks",
        }
    ]
    assert survival["terminal_phase"] == "revived"


def test_fimbulwinter_ahri_charm_arms_the_sourced_mana_gate():
    """Ahri's reviewed Charm arms Everlasting through the sourced mana gate."""
    main = get_champion("Ahri")
    loadout = ChampionLoadout(
        champion="Ahri", level=18, items=("Fimbulwinter",)
    ).resolve()
    enemy = ChampionLoadout(champion="Aatrox", level=18, items=()).resolve()
    params = FightParams.from_request(
        {
            "fight_mode": "one_rotation",
            "ability_ranks": {"Q": 0, "W": 0, "E": 1, "R": 0},
            "auto_attack_uptime": 0.0,
        },
        deterministic=True,
    )
    result = build_participant_timeline(
        main,
        18,
        list(loadout.item_data),
        params,
        main_stats=loadout.stats,
        main_defenses=resolve_starting_defenses(
            "Ahri", 18, loadout.stats, list(loadout.item_data)
        ),
        enemies=[enemy],
        allies=[],
    )

    # Everlasting's mana gate is sourced (rev 3984419; surface-area U11a),
    # so Ahri's reviewed Charm arms the shield at full mana instead of the
    # named authority denial main's tests expected.
    everlasting = [
        event
        for event in result["support_events"]
        if event["source"] == "Fimbulwinter — Everlasting"
    ]
    assert everlasting, result["item_denial_receipts"]
    assert "mana_gate_authority_unavailable" not in {
        event["reason"] for event in result["item_denial_receipts"]
    }


def test_fimbulwinter_denial_receipts_are_split_from_applied_support_events():
    """A ranged holder's slow never fires Everlasting and the rejection is
    a NAMED denial receipt in the timeline's public section — never an
    applied support event.

    Cassiopeia's R authors a typed ``slow`` control part when
    ``r_target_facing`` is off; Cassiopeia is ranged, so the CC-adjacent
    event is denied with ``ranged_slow``.
    """
    champion = get_champion("Cassiopeia")
    loadout = ChampionLoadout(
        champion="Cassiopeia", level=18, items=("Fimbulwinter",)
    ).resolve()
    enemy = ChampionLoadout(champion="Aatrox", level=18, items=()).resolve()
    params = FightParams.from_request(
        {
            "fight_mode": "one_rotation",
            "ability_ranks": {"Q": 0, "W": 0, "E": 0, "R": 1},
            "auto_attack_uptime": 0.0,
            "champion_options": {"r_target_facing": False},
        },
        deterministic=True,
    )
    result = build_participant_timeline(
        champion,
        18,
        list(loadout.item_data),
        params,
        main_stats=loadout.stats,
        main_defenses=resolve_starting_defenses(
            "Cassiopeia", 18, loadout.stats, list(loadout.item_data)
        ),
        enemies=[enemy],
        allies=[],
    )
    denials = [
        row
        for row in result["item_denial_receipts"]
        if row["source"] == "Fimbulwinter — Everlasting"
    ]
    assert denials, "the ranged-slow rejection must be receipted"
    assert all(row["reason"] == "ranged_slow" for row in denials)
    # Receipts never leak into the applied support stream.
    fimbulwinter_support = [
        event
        for event in result["support_events"]
        if event["source"] == "Fimbulwinter — Everlasting"
    ]
    assert fimbulwinter_support == []
    # The typed slow still certifies the CC dimension (every ability event
    # carries a typed cc_kind).
    assert result["timeline_coverage"]["complete"] is True


def test_fimbulwinter_holder_keeps_dict_rows_in_score_only_fights():
    """CC-trigger holders are excluded from the tuple-ledger fast path.

    A score-only fight for a Fimbulwinter holder must keep dict damage rows
    (the Everlasting scan reads the per-event CC metadata); a tuple ledger
    would silently starve the scan (P3-3B hardening).
    """
    champion = get_champion("Ahri")
    item = get_item_by_name("Fimbulwinter")
    stats = calculate_total_stats(champion, 18, [item])
    params = FightParams.from_request(
        {"fight_mode": "one_rotation", "auto_attack_uptime": 0.0},
        deterministic=True,
    )
    result = run_fight(champion, 18, [item], params, score_only=True)
    assert "damage_events_tuple" not in result
    assert result["damage_events"] and all(
        isinstance(event, dict) for event in result["damage_events"]
    )


def test_eclipse_holder_keeps_dict_rows_in_score_only_fights():
    """Eclipse's stack proc attaches its self shield to the damage events;
    a score-only tuple ledger cannot carry it, so an Eclipse holder keeps
    dict rows (P3-3C hardening; the compiled walk already fails closed)."""
    champion = get_champion("Ziggs")
    item = get_item_by_name("Eclipse")
    stats = calculate_total_stats(champion, 18, [item])
    params = FightParams.from_request(
        {
            "fight_mode": "one_rotation",
            "ability_ranks": {"Q": 1, "W": 0, "E": 0, "R": 0},
            "auto_attack_uptime": 0.0,
        },
        deterministic=True,
    )
    result = run_fight(champion, 18, [item], params, score_only=True)
    assert "damage_events_tuple" not in result
    assert result["damage_events"] and all(
        isinstance(event, dict) for event in result["damage_events"]
    )
    # The proc row and its shield receipt survive the score-only fight.
    row = result["breakdown"].get("proc_Eclipse")
    if row is not None:
        assert "self_shield_events" in row


def test_legacy_score_path_is_stasis_blind_while_coupled_combat_prices_it():
    """P3-3F named boundary: the one-way headline score (run_fight) has no
    timeline, so it never prices starting stasis; the coupled combat
    timeline does.  The two numbers are documented as different altitudes —
    the headline is stasis-invariant, the coupled receipt reflects it."""
    champion = get_champion("Ahri")
    item = get_item_by_name("Zhonya's Hourglass")
    params = FightParams.from_request(
        {
            "fight_mode": "one_rotation",
            "ability_ranks": {"Q": 1, "W": 0, "E": 0, "R": 0},
            "auto_attack_uptime": 1.0,
            "item_options": {"Zhonya's Hourglass": {"stasis_active_seconds": 2.0}},
        },
        deterministic=True,
    )
    plain = FightParams.from_request(
        {
            "fight_mode": "one_rotation",
            "ability_ranks": {"Q": 1, "W": 0, "E": 0, "R": 0},
            "auto_attack_uptime": 1.0,
        },
        deterministic=True,
    )
    with_stasis = run_fight(champion, 18, [item], params)
    without = run_fight(champion, 18, [item], plain)
    # The headline is stasis-invariant (no timeline to price the window).
    assert with_stasis["total_damage"] == pytest.approx(without["total_damage"])

    # The coupled timeline prices the same input.
    enemy = ChampionLoadout(champion="Aatrox", level=18, items=()).resolve()
    stats = calculate_total_stats(champion, 18, [item])
    result = build_participant_timeline(
        champion,
        18,
        [item],
        params,
        main_stats=stats,
        main_defenses=resolve_starting_defenses(
            "Ahri",
            18,
            stats,
            [item],
            item_options={"Zhonya's Hourglass": {"stasis_active_seconds": 2.0}},
        ),
        enemies=[enemy],
        allies=[],
    )
    survival = result["participants"][0]["survival"]
    assert survival["stasis_until"] == pytest.approx(2.0)
    assert float(survival["action_downtime"]) >= 2.0


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
    # Issue #159: both walks now share one Lifeline boundary.  The sourced
    # wording is damage that would reduce you *below* 30%, and the first tick
    # leaves this 200-HP target on exactly 60 — so it arms on the second tick,
    # not the first.  Tick two therefore lands at the price the pair engine
    # gave it; only tick three onward is repriced against the temporary
    # maximum health.  Before the fix the coupled walk armed a tick early
    # (``<=``) while the one-pair engine did not (``<``).
    assert [event["damage"] for event in q_events] == pytest.approx(
        [140.0, 4.0, 18.4, 18.4, 18.4]
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
    # The Ahri enemy's E9-2 Essence Theft passive heal is a separate
    # receipt; Decimate's own heal is the only main-owned one.
    assert len(heals) == 2
    assert [event["source"] for event in heals] == ["Decimate", "Essence Theft"]
    assert heals[0]["source"] == "Decimate"
    # The heal fires at Decimate's cast (t=0), so its missing-health
    # basis is the damage Darius has taken up to that cast — not the
    # whole window.  Annie's E4 Tibbers-attacks row carries authored
    # 0.58s+ pet timestamps, so it lands after the heal and must be
    # excluded from the basis (it still raises window damage_taken).
    tibbers = next(
        source["total_damage"]
        for item in receipt["breakdown"]
        if isinstance(item, dict) and item.get("participant_id") == "enemy:Annie"
        for source in item.get("sources", [])
        if source.get("name") == "Tibbers Attacks"
    )
    heal_basis = main_survival["damage_taken"] - tibbers
    assert heals[0]["raw_amount"] == pytest.approx(heal_basis * 0.34, abs=0.1)
    assert main_survival["healing_received"] == pytest.approx(
        heals[0]["applied_amount"]
    )
    assert fast["participants"] == legacy["participants"]
    assert fast["breakdown"] == legacy["breakdown"]


def test_vladimir_hemoplague_keeps_one_heal_per_target_in_both_walks():
    """Hemoplague heals per infected champion: full for the first, reduced
    for later targets, each preserved with its own trigger receipt."""
    champion = get_champion("Vladimir")
    params = FightParams.from_request(
        {
            "fight_mode": "time_based",
            "fight_duration": 10,
            "include_auto_attacks": True,
            "auto_attack_uptime": 0.3,
            "ability_ranks": {"Q": 1, "W": 1, "E": 1, "R": 3},
        },
        deterministic=True,
    )
    stats = calculate_total_stats(champion, 18, [])
    defenses = resolve_starting_defenses("Vladimir", 18, stats, [])
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
    heals = [
        event for event in receipt["healing_events"] if event["source"] == "Hemoplague"
    ]
    assert len(heals) == 2
    assert sorted(event["amount"] for event in heals) == pytest.approx([140.0, 350.0])
    # Simultaneous same-source heals from different trigger targets must not
    # collapse: each keeps its own event id, trigger receipt, and target.
    assert len({event["event_id"] for event in heals}) == 2
    assert len({event["trigger_event_id"] for event in heals}) == 2
    assert {event["trigger_target"] for event in heals} == {
        "enemy:Annie",
        "enemy:Ahri",
    }
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
            "ability_ranks": {"Q": 5, "W": 5, "E": 0, "R": 3},
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
    # Ahri's Essence Theft passive heal (95, 20% AP) lands first at t=0,
    # so the item heal's missing-health component re-prices from the
    # already-healed live health. Ahri is ranged, so Lightshield Strike
    # heals 50% base AD.
    assert heal["raw_amount"] == pytest.approx(69.6)
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
            "ability_ranks": {"Q": 5, "W": 5, "E": 0, "R": 3},
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
    # Ahri's Essence Theft passive heal (107 with Dusk and Dawn's 60 AP) and
    # the item heal land at t=0 and t=1.5.
    assert main["survival"]["healing_received"] == 122.0


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
                    "champion": "Yuumi",
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


def test_a_module_self_shield_is_actor_wide_and_granted_once_per_roster():
    """One Mana Barrier against five enemies, not one per enemy pair.

    The payload is authored once per rotation and replayed by every pair
    fight, so the ``actor_wide`` flag ``slotlib.attach_self_shield`` stamps
    is what the composition de-duplicates on -- the same convention
    actor-wide heals use, rather than a per-module roster-index gate.
    """
    app.config["TESTING"] = True
    response = app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Blitzcrank",
            "level": 18,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 10,
            "include_auto_attacks": False,
            "deterministic": True,
            "enemies": [
                {"champion": name, "level": 18, "items": []}
                for name in ("Aphelios", "Ambessa", "Ashe", "Annie", "Akali")
            ],
        },
    )
    assert response.status_code == 200
    barriers = [
        event
        for event in response.get_json()["combat"]["support_events"]
        if event["source"] == "Mana Barrier"
    ]
    (barrier,) = barriers
    assert barrier["target"] == "main"
    # 35% of Blitzcrank's level-18 max mana, granted once.
    assert barrier["amount"] == pytest.approx(331.45, abs=0.01)


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


def test_enemy_hits_off_composes_zero_enemy_damage():
    """enemies_attack=false is the Enemy Hits constraint unchecked: the
    coupled receipt carries no enemy-authored event at all — pair fights,
    autos, and Thornmail strike-backs included — while the main champion's
    own output is composed exactly as before."""
    app.config["TESTING"] = True
    payload = {
        "champion": "Akali",
        "level": 12,
        "role": "mid",
        "fight_mode": "time_based",
        "fight_duration": 6,
        "include_auto_attacks": True,
        "auto_attack_uptime": 0.5,
        "ability_ranks": {"Q": 3, "W": 1, "E": 2, "R": 1},
        "enemies": [
            {
                "champion": "Orianna",
                "level": 12,
                "role": "mid",
                "items": ["Thornmail"],
                "ability_ranks": {"Q": 3, "W": 1, "E": 2, "R": 1},
            }
        ],
    }
    client = app.test_client()
    on = client.post("/api/calculate", json=payload).get_json()["combat"]
    off = client.post(
        "/api/calculate", json={**payload, "enemies_attack": False}
    ).get_json()["combat"]

    assert any(event["attacker"] == "enemy:Orianna" for event in on["events"])
    assert all(event["attacker"] != "enemy:Orianna" for event in off["events"])

    # A never-attacking enemy either has no breakdown row at all or a zero
    # one; it must still exist as a participant (it is being fought).
    assert all(
        row["total_damage"] == 0.0
        for row in off["breakdown"]
        if row["participant_id"] == "enemy:Orianna"
    )
    assert any(row["participant_id"] == "enemy:Orianna" for row in off["participants"])
    main_row = next(row for row in off["breakdown"] if row["participant_id"] == "main")
    assert main_row["total_damage"] > 0.0
    main = next(row for row in off["participants"] if row["participant_id"] == "main")
    assert main["survival"]["damage_taken"] == 0.0
    assert main["survival"]["survived_window"] is True


def _shadowflame_scenario(items):
    """The enemy-hits-off coupled fight this packet is measured on."""
    app.config["TESTING"] = True
    return app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Syndra",
            "level": 11,
            "role": "mid",
            "role_quest_complete": True,
            "items": items,
            "boots": "Spellslinger's Shoes",
            "fight_mode": "time_based",
            "fight_duration": 30,
            "include_auto_attacks": True,
            "ability_ranks": {"Q": 5, "W": 3, "E": 1, "R": 2},
            "champion_options": {"splinters": 100, "r_spheres": 3},
            "enemies_attack": False,
            "enemies": [
                {
                    "champion": "Ryze",
                    "level": 11,
                    "role": "mid",
                    "role_quest_complete": True,
                    "items": [
                        "Rod of Ages",
                        "Seraph's Embrace",
                        "Doran's Ring",
                        "Dark Seal",
                    ],
                    "boots": "Chainlaced Crushers",
                    "item_options": {
                        "Rod of Ages": {"timeless_stacks": 3},
                        "Dark Seal": {"glory_stacks": 5},
                    },
                    "ability_ranks": {"Q": 5, "W": 1, "E": 3, "R": 2},
                }
            ],
        },
    )


def test_cinderbloom_is_priced_by_the_walk_not_as_a_coupled_source_row():
    """Cinderbloom is a dropped preview: the walk rides it, no row carries it.

    ``trigger_stream`` declares ``shadowflame.cinderbloom`` as a walk item
    delivered by ``RiderDelivery`` at ``survival.transitions._apply_live_amp``,
    and ``shadowflame.cinderbloom_preview`` as the pair-only,
    ``ViewTag.THEORETICAL`` half at ``damage._add_shadowflame_cinderbloom``.
    ``program.build.dropped_preview_mechanics`` therefore names the mechanic,
    and a roster-composed fight skips computing the preview row entirely --
    the predicate reads the target's health under the whole roster's fire, so
    a one-attacker row would be the wrong number to place on a shared clock.

    The bonus is not lost by being unnamed: it amplifies the packets it rides,
    which is what the two runs below measure.
    """
    with_flame = _shadowflame_scenario(
        ["Doran's Ring", "Blackfire Torch", "Shadowflame"]
    )
    without = _shadowflame_scenario(
        ["Doran's Ring", "Blackfire Torch", "Verdant Barrier"]
    )
    assert with_flame.status_code == 200 and without.status_code == 200

    assert "shadowflame.cinderbloom" in dropped_preview_mechanics()
    combat = with_flame.get_json()["combat"]
    assert not [
        event
        for event in combat["events"]
        if event.get("source") == "shadowflame_Shadowflame"
    ]

    def death_time(response):
        rows = response.get_json()["combat"]["participants"]
        return next(row for row in rows if row["team"] == "enemy")["survival"][
            "death_time"
        ]

    armed, bare = death_time(with_flame), death_time(without)
    assert armed is not None and bare is not None
    assert armed < bare


def test_cinderbloom_preview_keeps_one_packet_per_trigger_time():
    """The pair surface -- where the preview IS the answer -- stays timed.

    The row's bonus packets each keep the timestamp of the hit they rode, so
    a consumer that stops at a boundary (participant death, a window sum) can
    stop the late ones and keep the early ones.  They ride the row's own
    ``damage_events`` because that is the only key the ledger reconstruction
    reads: under any other name it synthesizes ONE coarse packet at the last
    ability time, which is the same total placed at the wrong instant.
    """
    request = parse_scenario_request(
        {
            "champion": "Syndra",
            "level": 11,
            "role": "mid",
            "role_quest_complete": True,
            "items": ["Doran's Ring", "Blackfire Torch", "Shadowflame"],
            "boots": "Spellslinger's Shoes",
            "fight_mode": "timed",
            "fight_duration": 30,
            "include_auto_attacks": True,
            "ability_ranks": {"Q": 5, "W": 3, "E": 1, "R": 2},
            "champion_options": {"splinters": 100, "r_spheres": 3},
        },
        deterministic=True,
    )
    resolved = resolve_scenario(request)
    result = run_fight(
        resolved.champion_data,
        request.level,
        list(resolved.items),
        resolved.fight_params,
    )
    key = next(k for k in result["breakdown"] if k.startswith("shadowflame_"))
    row = result["breakdown"][key]
    packets = [
        event
        for event in result["damage_events"]
        if isinstance(event, dict) and event.get("source_key") == key
    ]
    assert len(packets) == len(row["damage_events"])
    assert sum(event["damage"] for event in packets) == pytest.approx(
        row["total_damage"]
    )
    # Many instants, not one lump at the end of the rotation.
    assert len({round(event["time"], 6) for event in packets}) > 1
    assert min(event["time"] for event in packets) < max(
        event["time"] for event in packets
    )


def test_syndra_100_stack_r_executes_in_the_coupled_timeline():
    app.config["TESTING"] = True
    response = app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Syndra",
            "level": 11,
            "role": "mid",
            "role_quest_complete": True,
            "items": ["Doran's Ring", "Blackfire Torch", "Shadowflame"],
            "boots": "Spellslinger's Shoes",
            "fight_mode": "time_based",
            "fight_duration": 30,
            "include_auto_attacks": False,
            "ability_ranks": {"Q": 5, "W": 3, "E": 1, "R": 2},
            "champion_options": {"splinters": 100, "r_spheres": 3},
            "enemies_attack": False,
            # Level 12: the depth2 atom corpus regen raised Syndra's Q/W/E
            # burst enough that a level-11 Ryze died outright to ordinary
            # damage before R landed (overkill via normal HP clipping),
            # never reaching the execute_threshold_ratio branch. Level 12
            # gives Ryze enough HP/MR that the burst lands him just above
            # the 15% execute band and R's own hit crosses it, exercising
            # the actual "Unleashed Power" execute path this test targets.
            "enemies": [{"champion": "Ryze", "level": 12, "items": []}],
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["rotation"]["cast_order"][-1] == "R"
    target = next(
        row for row in payload["combat"]["participants"] if row["team"] == "enemy"
    )
    r_event = next(
        event
        for event in payload["combat"]["events"]
        if event["attacker"] == "main" and event["source"] == "R"
    )
    other_damage_events = [
        event
        for event in payload["combat"]["events"]
        if event["attacker"] == "main" and event["source"] in {"Q", "Q2", "W", "E"}
    ]

    assert all(event["sequence"] < r_event["sequence"] for event in other_damage_events)
    assert target["survival"]["execute_source"] == "Unleashed Power"
    assert target["survival"]["execute_time"] == pytest.approx(r_event["time"])
    assert r_event["execute_triggered"] is True


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


def test_api_exposes_native_utility_dimensions_without_converting_them_to_tdd():
    app.config["TESTING"] = True
    response = app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Ahri",
            "level": 18,
            "items": [],
            "fight_mode": "timed",
            "fight_duration": 5,
            "enemies": [{"champion": "Annie", "level": 18, "items": []}],
            "allies": [
                {
                    "champion": "Lulu",
                    "level": 18,
                    "items": ["Shurelya's Battlesong"],
                    "item_options": {"Shurelya's Battlesong": {"active_seconds": 1.0}},
                    "ally_effects_enabled": True,
                }
            ],
        },
    )
    assert response.status_code == 200
    combat = response.get_json()["combat"]
    utility = combat["utility_outcomes"]["participants"]["ally:Lulu"]
    assert utility["contract"] == "utility_outcomes_v1"
    assert utility["movement"]["event_count"] > 0
    assert utility["movement"]["speed_percent_seconds"] == pytest.approx(240.0)
    assert "movement" in utility["applied_dimensions"]
    assert "no cross-unit utility score" in utility["metric_note"]


def test_api_exposes_stridebreaker_slow_and_movement_receipts():
    app.config["TESTING"] = True
    response = app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Ahri",
            "level": 18,
            "items": ["Stridebreaker"],
            "item_options": {"Stridebreaker": {"active_seconds": 1.0}},
            "fight_mode": "timed",
            "fight_duration": 5,
            "enemies": [{"champion": "Annie", "level": 18, "items": []}],
        },
    )
    assert response.status_code == 200
    combat = response.get_json()["combat"]
    utility = combat["utility_outcomes"]["participants"]["main"]
    assert utility["slow"]["event_count"] == 1
    assert utility["slow"]["percent_seconds"] == pytest.approx(105.0)
    assert utility["movement"]["event_count"] == 1
    assert utility["movement"]["speed_percent_seconds"] == pytest.approx(105.0)
    assert {"slow", "movement"} <= set(utility["applied_dimensions"])
    slow = next(event for event in combat["support_events"] if event["kind"] == "slow")
    assert slow["slow_percent"] == pytest.approx(35.0)


def test_secondary_packets_use_the_selected_roster_index_and_are_certified():
    app.config["TESTING"] = True
    response = app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Ahri",
            "level": 18,
            "items": ["Runaan's Hurricane"],
            "fight_mode": "auto_only",
            "fight_duration": 5,
            "auto_attacks_only": True,
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
            "enemies": [
                {"champion": "Annie", "level": 18, "items": []},
                {"champion": "Jinx", "level": 18, "items": []},
            ],
        },
    )
    assert response.status_code == 200
    combat = response.get_json()["combat"]
    allocation = combat["target_allocation"]
    assert allocation["complete"] is True
    assert allocation["secondary_packet_count"] > 0
    assert (
        allocation["allocated_secondary_packet_count"]
        == allocation["secondary_packet_count"]
    )
    bolts = [
        event
        for event in combat["events"]
        if event.get("source") == "secondary_Runaan's Hurricane"
    ]
    assert bolts
    assert all(event["targeting"]["allocated_target_index"] == 1 for event in bolts)


def test_redemption_active_emits_sourced_area_true_damage_and_heal_packets():
    app.config["TESTING"] = True
    response = app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Ahri",
            "level": 18,
            "items": [],
            "fight_mode": "timed",
            "fight_duration": 5,
            "enemies": [
                {"champion": "Annie", "level": 18, "items": []},
                {"champion": "Jinx", "level": 18, "items": []},
            ],
            "allies": [
                {
                    "champion": "Lulu",
                    "level": 18,
                    "items": ["Redemption"],
                    "item_options": {"Redemption": {"active_seconds": 1.0}},
                    "ally_effects_enabled": True,
                }
            ],
        },
    )
    assert response.status_code == 200
    combat = response.get_json()["combat"]
    damage = [
        event
        for event in combat["events"]
        if event["source"] == "Redemption — Intervention"
    ]
    assert {event["target"] for event in damage} == {"enemy:Annie", "enemy:Jinx"}
    assert all(event["damage_type"] == "true" for event in damage)
    assert all(event["event_precision"] == "exact" for event in damage)
    support = [
        event
        for event in combat["support_events"]
        if event["source"] == "Redemption — Intervention"
    ]
    assert any(event["kind"] == "heal" for event in support)
    assert all(event["range_assumption"] == "within_5500_units" for event in support)


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
    shields = [
        event
        for event in combat["support_events"]
        if event["attacker"] == "main" and event["source"].startswith("Help, Pix!")
    ]
    shield = shields[0]
    assert shield["target"] == "ally:Jinx"
    assert shield["recipient"] == "ally:Jinx"
    assert shield["event_id"].startswith("main:support:")
    assert shield["target_policy"] == "first_selected_teammate"
    assert shield["amount"] == 230.0
    assert shield["applied_amount"] == 230.0
    jinx = next(
        row for row in combat["participants"] if row["participant_id"] == "ally:Jinx"
    )
    # Every cast the window fits shields once; how many that is belongs to
    # the cooldown, not to this receipt.
    assert jinx["survival"]["support_shield_received"] == 230.0 * len(shields)


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


def _run_four_champion_issue_18_cp11_probe(
    *,
    lulu_e_rank: int,
    orianna_e_rank: int,
    mondo_r_rank: int,
):
    """Issue-18 CP11 probe for ordered, multi-participant ranked inputs."""
    payload = {
        "champion": "Aatrox",
        "level": 18,
        "items": ["Morellonomicon"],
        "fight_mode": "time_based",
        "fight_duration": 8,
        "include_auto_attacks": True,
        "auto_attack_uptime": 0.8,
        "ability_ranks": {"Q": 3, "W": 1, "E": 3, "R": 1},
        "allies": [
            {
                "champion": "Lulu",
                "level": 18,
                "role": "support",
                "items": [],
                "ally_effects_enabled": True,
                "ability_ranks": {"Q": 0, "W": 0, "E": lulu_e_rank, "R": 0},
            }
        ],
        "enemies": [
            {
                "champion": "Orianna",
                "level": 18,
                "role": "mid",
                "items": [],
                "ability_ranks": {"Q": 0, "W": 0, "E": orianna_e_rank, "R": 0},
            },
            {
                "champion": "Dr. Mundo",
                "level": 18,
                "role": "top",
                "items": [],
                "ability_ranks": {"Q": 0, "W": 0, "E": 0, "R": mondo_r_rank},
            },
        ],
    }
    response = app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200
    return response.get_json()["combat"]


def _extract_issue_18_cp11_event_by_label(
    combat: dict,
    events_key: str,
    attendee: str,
    source_prefix: str,
    *,
    exact_target: str | None = None,
):
    """Pick support/heal/events entries and fail-closed when shape is missing."""
    events = [
        event
        for event in combat.get(events_key, [])
        if event.get("attacker") == attendee
        and event.get("source", "").startswith(source_prefix)
    ]
    if exact_target is not None:
        events = [event for event in events if event.get("target") == exact_target]
    if not events:
        expected_target = "any" if exact_target is None else exact_target
        pytest.fail(
            f"BLOCKER: missing expected {source_prefix} packet on {events_key} for "
            f"{attendee} -> {expected_target} in four-champion contract probe"
        )
    return events


def test_issue_18_four_champion_cp11_contract_probe_records_ranked_packets_and_target_policies():
    """Issue-18: ranked support packets and explicit target policies stay ordered."""
    low = _run_four_champion_issue_18_cp11_probe(
        lulu_e_rank=1,
        orianna_e_rank=1,
        mondo_r_rank=1,
    )
    high = _run_four_champion_issue_18_cp11_probe(
        lulu_e_rank=5,
        orianna_e_rank=3,
        mondo_r_rank=3,
    )

    low_support = _extract_issue_18_cp11_event_by_label(
        low,
        "support_events",
        "ally:Lulu",
        "Help, Pix!",
        exact_target="main",
    )
    high_support = _extract_issue_18_cp11_event_by_label(
        high,
        "support_events",
        "ally:Lulu",
        "Help, Pix!",
        exact_target="main",
    )
    low_protect = _extract_issue_18_cp11_event_by_label(
        low,
        "support_events",
        "enemy:Orianna",
        "Command: Protect",
    )
    high_protect = _extract_issue_18_cp11_event_by_label(
        high,
        "support_events",
        "enemy:Orianna",
        "Command: Protect",
    )

    if low_support[0].get("target_policy") != "first_selected_teammate":
        pytest.fail("BLOCKER: expected Lulu policy first_selected_teammate")
    if low_protect[0].get("target_policy") not in {
        "self",
        "first_selected_teammate",
    }:
        pytest.fail(
            "BLOCKER: expected Orianna protect policy to be self or first_selected_teammate"
        )

    assert sum(event["amount"] for event in low_support) < sum(
        event["amount"] for event in high_support
    )
    assert sum(event["amount"] for event in low_protect) < sum(
        event["amount"] for event in high_protect
    )


def test_issue_18_four_champion_cp11_contract_probe_tracks_regen_ranking_and_simultaneous_cutoffs():
    """Issue-18: max-dosage rank scaling, anti-heal, and simultaneous multi-party events."""
    low = _run_four_champion_issue_18_cp11_probe(
        lulu_e_rank=4,
        orianna_e_rank=3,
        mondo_r_rank=1,
    )
    high = _run_four_champion_issue_18_cp11_probe(
        lulu_e_rank=4,
        orianna_e_rank=3,
        mondo_r_rank=3,
    )

    low_heals = [
        event
        for event in low["healing_events"]
        if event.get("attacker") == "enemy:Dr. Mundo"
        and event.get("source") == "Maximum Dosage"
    ]
    high_heals = [
        event
        for event in high["healing_events"]
        if event.get("attacker") == "enemy:Dr. Mundo"
        and event.get("source") == "Maximum Dosage"
    ]
    if not low_heals or not high_heals:
        pytest.fail(
            "BLOCKER: maximum dosage healing did not emit in four-champion probe"
        )

    if any("time" not in event for event in low_heals + high_heals):
        pytest.fail("BLOCKER: missing time field on maximum dosage packets")

    low_sum = sum(event["amount"] for event in low_heals)
    high_sum = sum(event["amount"] for event in high_heals)
    if not high_sum > low_sum:
        pytest.fail("BLOCKER: Maximum Dosage rank did not increase total healing")

    if any("healing_reduction_factor" not in event for event in high_heals):
        pytest.fail("BLOCKER: healing_reduction_factor missing from anti-heal packet")
    if all(event["healing_reduction_factor"] >= 1 for event in high_heals):
        pytest.fail(
            "BLOCKER: Morellonomicon anti-heal did not reduce any maximum dosage healing"
        )

    timeline = (
        [event for event in low.get("events", []) if event.get("time") is not None]
        + [
            event
            for event in low.get("support_events", [])
            if event.get("time") is not None
        ]
        + [
            event
            for event in low.get("healing_events", [])
            if event.get("time") is not None
        ]
    )
    by_time: dict[float, set[str]] = {}
    for event in timeline:
        by_time.setdefault(event["time"], set()).add(event["attacker"])
    if not any(len(attacker_ids) >= 2 for attacker_ids in by_time.values()):
        pytest.fail("BLOCKER: no simultaneous packets observed across participants")

    participant_ids = {row["participant_id"] for row in low["participants"]}
    if participant_ids != {"main", "ally:Lulu", "enemy:Orianna", "enemy:Dr. Mundo"}:
        pytest.fail(
            f"BLOCKER: expected four participants and got {sorted(participant_ids)}"
        )


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
                "champion": "Yuumi",
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


def test_bis_utility_objective_uses_candidate_item_options():
    payload = _bis_request("main")
    payload["objective"] = "utility"
    payload["candidate_item_options"] = {"Stridebreaker": {"active_seconds": 1.0}}
    body = app.test_client().post("/api/bis", json=payload).get_json()

    row = next(row for row in body["candidates"] if row["name"] == "Stridebreaker")
    assert row["components"]["support_value"] > 0


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


def test_bis_certifies_eclipse_and_deaths_dance_defenses():
    payload = _bis_request("main")
    payload["objective"] = "survival"
    body = app.test_client().post("/api/bis", json=payload).get_json()
    candidates = {row["name"]: row for row in body["candidates"]}
    for name in ("Eclipse", "Death's Dance"):
        assert name in candidates
        assert candidates[name]["timeline_coverage"]["complete"] is True
        assert candidates[name]["defensive_effect_receipt"]["status"] == "certified"
        assert name in candidates[name]["defensive_effect_receipt"]["sources"]
    assert not {
        row["name"]
        for row in body["withheld_candidates"]
        if row["name"] in {"Eclipse", "Death's Dance"}
    }


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


def _named_like_the_real_timeline(payload):
    """A fake timeline payload, carrying the map the real one publishes.

    ``build_participant_timeline`` names every number it publishes, and the
    BIS objective refuses to rank a number no entry names (D-62): a payload
    with bare numbers is a payload nobody can ask what its numbers mean.  So
    a fake that returned one would be a fake of a shape the tree no longer
    has.  The map is built through the same writer the views use rather than
    hand-listed, which is what keeps the fake honest as the writer changes.
    """
    payload["dispositions"] = name_every_number(payload, LeafWriter())
    return payload


def _naming(fake):
    """One fake timeline, wrapped so its payload names its own numbers."""

    def wrapped(*args, **kwargs):
        return _named_like_the_real_timeline(fake(*args, **kwargs))

    return wrapped


def test_bis_reports_candidates_withheld_before_timeline_evaluation(monkeypatch):
    """A failed candidate remains visible in the per-candidate audit receipt."""

    candidates = [get_item_by_name("Luden's Echo"), get_item_by_name("Warmog's Armor")]
    monkeypatch.setattr(
        bis_module,
        "bis_candidate_pool",
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

    monkeypatch.setattr(
        bis_module, "build_participant_timeline", _naming(fake_timeline)
    )
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
        bis_module,
        "bis_candidate_pool",
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

    monkeypatch.setattr(
        bis_module, "build_participant_timeline", _naming(fake_timeline)
    )
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

    monkeypatch.setattr(
        bis_module, "build_participant_timeline", _naming(fake_timeline)
    )
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
        bis_module,
        "bis_candidate_pool",
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

    monkeypatch.setattr(
        bis_module, "build_participant_timeline", _naming(fake_timeline)
    )
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

    monkeypatch.setattr(
        bis_module, "build_participant_timeline", _naming(glass_cannon_timeline)
    )
    response = app.test_client().post("/api/bis", json=_bis_request("enemy"))
    assert response.status_code == 200
    assert response.get_json()["candidates"][0]["name"] == "Warmog's Armor"


def test_enemy_bis_rank_key_is_deterministic_and_event_derived():
    survived_damage = enemy_bis_rank_key(
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
    survived_health = enemy_bis_rank_key(
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
    early_glass = enemy_bis_rank_key(
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
    later_death = enemy_bis_rank_key(
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
        item["name"] for item in role_scoped_bis_candidates(candidates, role="support")
    }
    top = {item["name"] for item in role_scoped_bis_candidates(candidates, role="top")}

    assert "Locket of the Iron Solari" in support
    assert "Moonstone Renewer" in support
    assert "Warmog's Armor" not in support
    assert "Warmog's Armor" in top
    # 26.15 role-scope rule: SUPPORT-tagged items with another lane class
    # (TANK/MAGE/...) stay available to that lane (patch 16.15.1 added the
    # SUPPORT tag to Whispering Circlet, a MAGE item).
    assert "Locket of the Iron Solari" in top
    assert "Abyssal Mask" in top
    assert "Morellonomicon" in top
    assert "Whispering Circlet" in top
    assert "Shurelya's Battlesong" not in top
    assert "Ardent Censer" not in top
    assert "Redemption" not in top


def test_roster_bis_includes_event_certified_target_defenses():
    """Event-certified target defenses no longer disappear from the BIS pool."""
    app.config["TESTING"] = True
    response = app.test_client().post("/api/bis", json=_bis_request("enemy"))
    assert response.status_code == 200
    body = response.get_json()
    names = {
        candidate["name"]
        for candidate in [*body["candidates"], *body["partial_candidates"]]
    }

    assert "Zhonya's Hourglass" in names
    assert body["target_coverage_filtered"] == 0
    assert body["target_coverage_note"] == ""


def test_roster_bis_keeps_supported_mid_boot_target_in_the_candidate_pool():
    """A modeled mid-lane boot must not blank the entire target BIS panel."""
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
    assert body["candidates"]
    assert body["coverage"]["complete"] is False
    assert body["target_coverage_filtered"] == 0
    assert "Armored Advance" not in body["target_coverage_note"]


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
    items: tuple[dict, ...] = (),
) -> Combatant:
    defenses = StartingDefenses(
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
        items=items,
        stats={"health": health},
        defenses=defenses,
    )


def test_simulator_amplifies_authored_support_shields_for_spirit_visage():
    source = _dummy_combatant("source", "ally")
    target = _dummy_combatant("target", "main", healing_received_multiplier=1.25)
    result = _simulated_rows(
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


def test_simulator_reprices_damage_inside_aftershock_resistance_window():
    source = _dummy_combatant("source", "main", health=1000.0)
    target = _dummy_combatant("target", "enemy", health=1000.0)
    source.stats.update(
        {
            "armor": 50.0,
            "magic_resistance": 50.0,
            "bonus_armor": 0.0,
            "bonus_magic_resistance": 0.0,
        }
    )
    target.stats.update({"armor": 50.0, "magic_resistance": 50.0})
    control = {
        "time": 0.0,
        "kind": "crowd_control",
        "cc_kind": "stun",
        "cc_duration": 1.0,
        "damage": 0.0,
        "attacker": "source",
        "target": "target",
        "source_key": "Q",
        "source": "Test stun",
        "sequence": 0,
        "_event_id": "control",
    }
    hit = {
        "time": 1.5,
        "kind": "damage",
        "damage": 100.0,
        "damage_type": "physical",
        "attacker": "target",
        "target": "source",
        "source_key": "auto_attacks",
        "source": "Test hit",
        "sequence": 1,
        "_event_id": "hit",
        "_baseline_effective_armor": 50.0,
    }
    aftershock = {
        "time": 1e-9,
        "kind": "stat_buff",
        "amount": 0.0,
        "duration": 2.5,
        "bonus_armor": 45.0,
        "bonus_magic_resistance": 45.0,
        "attacker": "source",
        "target": "source",
        "source_key": "rune_Aftershock",
        "source": "Aftershock · Resistance",
        "_aftershock": True,
        "_trigger_event_id": "control",
        "_event_id": "aftershock",
        SUPPORT_RANK_KEY: TransitionRank.DAMAGE,
    }
    result = _simulated_rows(
        [source, target],
        {"source": [hit], "target": [control]},
        {},
        {"source": [aftershock]},
        3.0,
    )
    baseline_factor = 100.0 / 150.0
    aftershock_factor = 100.0 / 195.0
    assert result["source"]["health_damage"] == pytest.approx(
        100.0 * aftershock_factor / baseline_factor, abs=0.05
    )
    assert result["source"]["aftershock"]["bonus_armor"] == pytest.approx(45.0)
    assert result["source"]["aftershock"]["until"] == pytest.approx(2.5)


def test_simulator_orders_same_timestamp_events_without_comparing_payloads():
    target = _dummy_combatant("target", "enemy")
    source = _dummy_combatant("source", "main")
    result = _simulated_rows(
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
    result = _simulated_rows(
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
    result = _simulated_rows(
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
    result = _simulated_rows(
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


def test_overlapping_grievous_sources_share_one_sourced_reduction_window():
    """Concurrent anti-heal sources are recorded together without stacking.

    The patch rule applies the strongest active Grievous Wounds factor once;
    source provenance still lists every qualifying attacker item so the event
    ledger remains auditable for multi-item and multi-participant fights.
    """
    source = _dummy_combatant("source", "main", health=100.0)
    source = Combatant(
        participant_id=source.participant_id,
        team=source.team,
        champion_data=source.champion_data,
        level=source.level,
        items=(
            get_item_by_name("Morellonomicon"),
            get_item_by_name("Oblivion Orb"),
        ),
        stats=source.stats,
        defenses=source.defenses,
    )
    target = _dummy_combatant("target", "enemy", health=200.0)
    result = _simulated_rows(
        [source, target],
        {
            "target": [
                {
                    "time": 0.0,
                    "damage": 100.0,
                    "damage_type": "magic",
                    "attacker": "source",
                    "target": "target",
                    "sequence": 0,
                    "_event_id": "overlap",
                }
            ]
        },
        {
            "target": [
                {
                    "time": 1.0,
                    "amount": 100.0,
                    "attacker": "target",
                    "source": "overlapping anti-heal test",
                }
            ]
        },
        {},
        10.0,
    )

    assert result["target"]["healing_received"] == pytest.approx(60.0)
    assert result["target"]["healing_reduced"] == pytest.approx(40.0)
    assert result["target"]["healing_reduction_until"] == pytest.approx(3.0)
    assert result["target"]["healing_reduction_events"][0]["factor"] == pytest.approx(
        0.6
    )
    assert result["target"]["healing_reduction_events"][0]["sources"] == [
        "Morellonomicon · Grievous Wounds",
        "Oblivion Orb · Grievous Wounds",
    ]


def _thorns_combatant(
    participant_id: str,
    team: str,
    *,
    health: float = 100.0,
    magic_resistance: float = 0.0,
    bonus_armor: float = 0.0,
    items: tuple = (),
) -> Combatant:
    defenses = StartingDefenses(
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

    result = _simulated_rows(
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

    result = _simulated_rows([striker, wearer], incoming, {}, {}, 10.0)
    assert result["target"]["survived_window"] is False
    # Only the killing blow's thorns lands: 10 magic vs 100 MR = 5.
    assert result["source"]["damage_taken"] == 5.0


def test_survival_walk_applies_explicit_deferred_damage_in_equal_ticks():
    source = _dummy_combatant("source", "main", health=100.0)
    target = _dummy_combatant("target", "enemy", health=100.0)
    result = _simulated_rows(
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


def test_deaths_dance_defers_damage_and_defy_clears_remaining_ticks():
    from src.calculator.defensive_effects import resolve_starting_defenses

    stats = {"health": 100.0, "bonus_attack_damage": 100.0, "is_melee": True}
    holder = Combatant(
        participant_id="main",
        team="main",
        champion_data={"name": "Aatrox"},
        level=18,
        items=(get_item_by_name("Death's Dance"),),
        stats=stats,
        defenses=resolve_starting_defenses(
            "Aatrox", 18, stats, [{"name": "Death's Dance"}]
        ),
    )
    enemy = _dummy_combatant("enemy", "enemy", health=100.0)
    incoming = {
        "main": [
            {
                "time": 0.0,
                "damage": 50.0,
                "damage_type": "physical",
                "attacker": "enemy",
                "target": "main",
                "sequence": 0,
                "_event_id": "incoming",
            }
        ],
        "enemy": [
            {
                "time": 1.0,
                "damage": 100.0,
                "damage_type": "true",
                "attacker": "main",
                "target": "enemy",
                "sequence": 0,
                "_event_id": "takedown",
            }
        ],
    }
    healing = {}
    result = _simulated_rows([holder, enemy], incoming, healing, {}, 5.0)

    assert result["main"]["damage_deferral_fraction"] == pytest.approx(0.30)
    assert result["main"]["damage_deferral_cleared"] == pytest.approx(15.0)
    assert result["main"]["damage_deferral_pending"] == pytest.approx(0.0)
    assert result["main"]["defy_triggered"] is True
    assert result["main"]["defy_trigger_time"] == pytest.approx(1.0)
    assert result["main"]["defy_heal_received"] == pytest.approx(35.0)
    assert sum(event["amount"] for event in healing["main"]) == pytest.approx(75.0)


def test_maw_lifeline_enables_post_trigger_omnivamp():
    holder = Combatant(
        participant_id="main",
        team="main",
        champion_data={"name": "Aatrox"},
        level=18,
        items=(get_item_by_name("Maw of Malmortius"),),
        stats={"health": 100.0, "is_melee": True},
        defenses=StartingDefenses(
            threshold_shield_amount=20.0,
            threshold_shield_health_ratio=0.30,
            threshold_shield_duration=3.0,
            threshold_shield_damage_type="magic",
            maw_lifeline_omnivamp_percent=10.0,
        ),
    )
    enemy = _dummy_combatant("enemy", "enemy", health=100.0)
    incoming = {
        "main": [
            {
                "time": 0.0,
                "damage": 90.0,
                "damage_type": "magic",
                "attacker": "enemy",
                "target": "main",
                "sequence": 0,
                "_event_id": "lifeline",
            }
        ],
        "enemy": [
            {
                "time": 1.0,
                "damage": 20.0,
                "damage_type": "physical",
                "attacker": "main",
                "target": "enemy",
                "basic_attack": True,
                "source_key": "auto_attacks",
                "sequence": 0,
                "_event_id": "followup",
            }
        ],
    }
    result = _simulated_rows([holder, enemy], incoming, {}, {}, 2.0)
    assert result["main"]["threshold_shield_triggered"] is True
    assert result["main"]["healing_received"] == pytest.approx(2.0)


def test_immortal_path_below_half_amplifies_non_vamp_recovery():
    holder = Combatant(
        participant_id="main",
        team="main",
        champion_data={"name": "Aatrox"},
        level=18,
        items=(get_item_by_name("Immortal Path"),),
        stats={"health": 100.0},
        defenses=StartingDefenses(
            magic_shield=0.0,
            physical_shield=0.0,
            general_shield=0.0,
            healing_received_multiplier=1.0,
        ),
    )
    enemy = _dummy_combatant("enemy", "enemy", health=100.0)
    result = _simulated_rows(
        [holder, enemy],
        {
            "main": [
                {
                    "time": 0.0,
                    "damage": 60.0,
                    "damage_type": "true",
                    "attacker": "enemy",
                    "target": "main",
                    "_event_id": "hit",
                }
            ]
        },
        {
            "main": [
                {
                    "time": 1.0,
                    "amount": 10.0,
                    "kind": "heal",
                    "source": "direct",
                }
            ]
        },
        {},
        2.0,
    )
    assert result["main"]["healing_received"] == pytest.approx(11.2)


def test_deaths_dance_defy_starts_heal_at_delayed_takedown_once():
    from src.calculator.defensive_effects import resolve_starting_defenses

    stats = {"health": 100.0, "bonus_attack_damage": 100.0, "is_melee": True}
    holder = Combatant(
        participant_id="main",
        team="main",
        champion_data={"name": "Aatrox"},
        level=18,
        items=(get_item_by_name("Death's Dance"),),
        stats=stats,
        defenses=resolve_starting_defenses(
            "Aatrox", 18, stats, [{"name": "Death's Dance"}]
        ),
    )
    enemy = _dummy_combatant("enemy", "enemy", health=100.0)
    incoming = {
        "main": [
            {
                "time": 0.0,
                "damage": 50.0,
                "damage_type": "physical",
                "attacker": "enemy",
                "target": "main",
                "sequence": 0,
                "_event_id": "incoming",
            }
        ],
        "enemy": [
            {
                "time": 0.0,
                "damage": 10.0,
                "damage_type": "true",
                "attacker": "main",
                "target": "enemy",
                "sequence": 0,
                "_event_id": "poke",
            },
            {
                "time": 2.5,
                "damage": 90.0,
                "damage_type": "true",
                "attacker": "main",
                "target": "enemy",
                "sequence": 1,
                "_event_id": "takedown",
            },
        ],
    }
    healing = {}
    result = _simulated_rows([holder, enemy], incoming, healing, {}, 5.0)

    defy_heals = [
        event for event in healing["main"] if event["source"] == "Death's Dance (Defy)"
    ]
    assert [event["time"] for event in defy_heals] == [3.5, 4.5]
    assert sum(event["amount"] for event in defy_heals) == pytest.approx(75.0)
    assert result["main"]["defy_trigger_time"] == pytest.approx(2.5)
    assert result["main"]["defy_heal_received"] == pytest.approx(45.0)
    assert result["main"]["damage_deferral_cleared"] == pytest.approx(5.0)


def test_eclipse_self_shield_is_triggered_and_expires_in_order():
    source = _dummy_combatant("source", "main")
    target = _dummy_combatant("target", "enemy")
    support = {
        "source": [
            {
                "time": 1.0,
                "kind": "shield",
                "amount": 80.0,
                "duration": 2.0,
                "attacker": "source",
                "target": "source",
                "source": "Eclipse (Ever Rising Moon)",
                "_event_id": "proc:shield",
                "_trigger_event_id": "proc",
                SUPPORT_RANK_KEY: TransitionRank.LATE_BARRIER,
            }
        ]
    }
    incoming = {
        "target": [
            {
                "time": 1.0,
                "damage": 1.0,
                "damage_type": "true",
                "attacker": "source",
                "target": "target",
                "sequence": 0,
                "_event_id": "proc",
            }
        ],
        "source": [
            {
                "time": 3.5,
                "damage": 80.0,
                "damage_type": "true",
                "attacker": "target",
                "target": "source",
                "sequence": 0,
                "_event_id": "late-hit",
            }
        ],
    }
    result = _simulated_rows([source, target], incoming, {}, support, 4.0)

    assert result["source"]["support_shield_received"] == pytest.approx(80.0)
    assert result["source"]["support_shield_expired"] == pytest.approx(80.0)
    assert result["source"]["shield_absorbed"] == pytest.approx(0.0)
    assert result["source"]["health_damage"] == pytest.approx(80.0)


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
    _simulated_rows(
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
    result = _simulated_rows(
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


def test_knights_vow_redirect_reprices_pre_mitigation_damage_for_holder_resistance():
    source = replace(
        _dummy_combatant("source", "enemy"),
        stats={
            "health": 100.0,
            "flat_armor_penetration": 0.0,
            "armor_penetration_percent": 0.0,
            "magic_penetration_flat": 0.0,
            "magic_penetration_percent": 0.0,
        },
    )
    protected = replace(
        _dummy_combatant("protected", "main"),
        stats={"health": 100.0, "armor": 0.0},
    )
    holder = replace(
        _dummy_combatant("holder", "main"),
        stats={"health": 100.0, "armor": 100.0},
    )
    event = {
        "time": 0.0,
        "damage": 100.0,
        "damage_type": "physical",
        "attacker": "source",
        "target": "protected",
        "sequence": 0,
        "_event_id": "kv-premit",
        "redirect_fraction": 0.14,
        "redirect_target": "holder",
        "redirect_pre_mitigation_required": True,
        "redirect_holder_health_ratio": 0.30,
        "_baseline_effective_armor": 0.0,
    }
    result = _simulated_rows(
        [source, protected, holder],
        {"protected": [event]},
        {},
        {},
        10.0,
    )
    # 86 raw reaches the unarmoured Worthy; 14 raw is mitigated by 100 armor.
    assert result["protected"]["health_damage"] == pytest.approx(86.0)
    assert result["holder"]["health_damage"] == pytest.approx(7.0)


def test_knights_vow_cancels_redirect_when_holder_falls_below_health_gate():
    source = _dummy_combatant("source", "enemy")
    protected = _dummy_combatant("protected", "main")
    holder = _dummy_combatant("holder", "main")
    incoming = {
        "holder": [
            {
                "time": 0.0,
                "damage": 90.0,
                "damage_type": "true",
                "attacker": "source",
                "target": "holder",
                "sequence": 0,
                "_event_id": "holder-hit",
            }
        ],
        "protected": [
            {
                "time": 1.0,
                "damage": 40.0,
                "damage_type": "physical",
                "attacker": "source",
                "target": "protected",
                "sequence": 1,
                "_event_id": "kv-gated",
                "redirect_fraction": 0.14,
                "redirect_target": "holder",
                "redirect_pre_mitigation_required": True,
                "redirect_holder_health_ratio": 0.30,
                "_baseline_effective_armor": 0.0,
            }
        ],
    }
    result = _simulated_rows([source, protected, holder], incoming, {}, {}, 10.0)
    assert result["protected"]["health_damage"] == pytest.approx(40.0)
    assert result["holder"]["health_damage"] == pytest.approx(90.0)


def test_thorns_does_not_fire_for_missed_or_blocked_basic_attack_receipts():
    striker = _thorns_combatant("source", "main")
    wearer = _thorns_combatant(
        "target", "enemy", items=(get_item_by_name("Bramble Vest"),)
    )
    incoming = {
        "target": [
            {
                **_auto_strike(
                    "target", "source", time=0.0, damage=0.0, event_id="miss"
                ),
                "missed": True,
            },
            {
                **_auto_strike(
                    "target", "source", time=1.0, damage=0.0, event_id="block"
                ),
                "blocked": True,
            },
        ]
    }
    outgoing = {"source": list(incoming["target"]), "target": []}
    _schedule_thorns_events([striker, wearer], incoming, outgoing)
    assert not any(
        event.get("source_key") == "thorns_Bramble Vest"
        for event in incoming.get("source", [])
    )


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
    _simulated_rows(
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
    result = _simulated_rows(
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


def test_standalone_crowd_control_blocks_actions_and_merges_downtime():
    source = _dummy_combatant("source", "enemy")
    target = _dummy_combatant("target", "main")
    outgoing = [
        {
            "time": 1.5,
            "kind": "damage",
            "damage": 10.0,
            "raw_damage": 10.0,
            "damage_type": "physical",
            "attacker": "target",
            "target": "source",
            "source": "AA",
            "source_key": "basic_attack",
            "sequence": 0,
            "_event_id": "blocked-by-cc",
        },
        {
            "time": 3.0,
            "kind": "damage",
            "damage": 10.0,
            "raw_damage": 10.0,
            "damage_type": "physical",
            "attacker": "target",
            "target": "source",
            "source": "AA",
            "source_key": "basic_attack",
            "sequence": 1,
            "_event_id": "after-cc",
        },
    ]
    incoming = {
        "target": [
            {
                "time": 0.0,
                "kind": "crowd_control",
                "damage": 0.0,
                "cc_kind": "stun",
                "cc_duration": 2.0,
                "attacker": "source",
                "target": "target",
                "source": "Q",
                "source_key": "Q",
                "sequence": 0,
                "_event_id": "first-cc",
            },
            {
                "time": 1.0,
                "kind": "crowd_control",
                "damage": 0.0,
                "cc_kind": "root",
                "cc_duration": 2.0,
                "attacker": "source",
                "target": "target",
                "source": "W",
                "source_key": "W",
                "sequence": 1,
                "_event_id": "overlapping-cc",
            },
        ],
        "source": outgoing,
    }
    # MERGE: the walk returns its frozen result now, so the published rows
    # come from the survival view exactly as the composition builds them.
    result = _simulated_rows(
        [source, target],
        incoming,
        {},
        {},
        4.0,
        receipt_events={"source": outgoing},
    )

    assert result["target"]["action_downtime"] == pytest.approx(3.0)
    assert result["target"]["crowd_control_until"] == pytest.approx(3.0)
    assert len(result["target"]["crowd_control_intervals"]) == 2
    assert outgoing[0]["skipped_reason"] == "attacker_state_blocked"
    assert "skipped_reason" not in outgoing[1]


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
    result = _simulated_rows([source, target], damage, {}, support, 10.0)
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
    _simulated_rows(
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


def _collector_execute_event() -> dict:
    """One packet that leaves the target inside The Collector's threshold.

    It carries the pair engine's own stamp, because that is what the walk
    used to read and what this pair of tests is about.
    """
    return {
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


def test_survival_walk_applies_collector_execute_as_terminal_state():
    """The Collector threshold kills without adding synthetic damage."""
    source = _dummy_combatant(
        "source", "main", health=100.0, items=({"name": "The Collector"},)
    )
    target = _dummy_combatant("target", "enemy", health=100.0)
    execute_event = _collector_execute_event()
    result = _simulated_rows(
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


def test_the_walk_executes_off_the_declaration_and_not_off_the_pair_stamp():
    """The equivalence fixture for The Collector, and the mutation behind it.

    ``damage_routing`` retired off the pair engine (umbrella Amendment P), so
    the walk reads the Execute rider from the attacker's own declaration
    rather than from the ratio ``damage.py`` stamped on its own events.  The
    same packet, carrying the same stamp, against an attacker whose build
    declares no execution: the threshold does not fire, and the target lives
    on the four health the previous test executes it out of.

    That is the whole property the retirement bought, and it is unprovable
    from the covering scenario -- no committed coupled roster holds The
    Collector -- which is why Amendment P asks for a fixture per owner.
    """
    source = _dummy_combatant("source", "main", health=100.0)
    target = _dummy_combatant("target", "enemy", health=100.0)
    execute_event = _collector_execute_event()
    result = _simulated_rows(
        [source, target],
        {"target": [execute_event]},
        {},
        {},
        10.0,
    )

    assert result["target"]["ending_health"] == 4.0
    assert result["target"]["execute_source"] == ""
    assert "execute_threshold_ratio" not in execute_event


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
        defenses=StartingDefenses(
            magic_shield=0.0,
            physical_shield=0.0,
            general_shield=0.0,
            threshold_shield_amount=30.0,
            threshold_shield_health_ratio=0.3,
            threshold_shield_duration=3.0,
            threshold_shield_damage_type="all",
        ),
    )
    result = _simulated_rows(
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


def test_threshold_shield_stays_armed_past_duration_until_matching_type_hit():
    """The Lifeline duration is the granted shield's expiry, not a trigger
    window: an unmatched-type hit after the nominal duration must not
    consume the shield or mark it expired."""
    source = _dummy_combatant("source", "enemy", health=100.0)
    target = Combatant(
        participant_id="target",
        team="main",
        champion_data={"name": "target"},
        level=1,
        items=(),
        stats={"health": 100.0},
        defenses=StartingDefenses(
            magic_shield=0.0,
            physical_shield=0.0,
            general_shield=0.0,
            threshold_shield_amount=30.0,
            threshold_shield_health_ratio=0.3,
            threshold_shield_duration=3.0,
            threshold_shield_damage_type="magic",
        ),
    )
    result = _simulated_rows(
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
    assert result["target"]["threshold_shield_expired_at"] is None
    assert result["target"]["shield_absorbed"] == 0.0


def test_threshold_shield_triggers_on_late_matching_type_hit_and_expires_after_duration():
    """A magic Lifeline must arm on a magic hit at any fight time, grant the
    sourced shield, and expire exactly ``duration`` seconds after trigger."""
    source = _dummy_combatant("source", "enemy", health=100.0)
    target = Combatant(
        participant_id="target",
        team="main",
        champion_data={"name": "target"},
        level=1,
        items=(),
        stats={"health": 100.0},
        defenses=StartingDefenses(
            magic_shield=0.0,
            physical_shield=0.0,
            general_shield=0.0,
            threshold_shield_amount=30.0,
            threshold_shield_health_ratio=0.3,
            threshold_shield_duration=3.0,
            threshold_shield_damage_type="magic",
        ),
    )
    result = _simulated_rows(
        [source, target],
        {
            "target": [
                {
                    "time": 4.0,
                    "damage": 80.0,
                    "damage_type": "magic",
                    "attacker": "source",
                    "_event_id": "late-lifeline",
                }
            ]
        },
        {},
        {},
        10.0,
    )
    assert result["target"]["threshold_shield_triggered"] is True
    assert result["target"]["threshold_shield_expired_at"] == pytest.approx(7.0)
    assert result["target"]["shield_absorbed"] == 30.0
    assert result["target"]["ending_health"] == 50.0


def test_threshold_shield_trigger_is_preserved_on_damage_receipt():
    source = _dummy_combatant("source", "enemy", health=100.0)
    target = Combatant(
        participant_id="target",
        team="main",
        champion_data={"name": "target"},
        level=1,
        items=(),
        stats={"health": 100.0},
        defenses=StartingDefenses(
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
    _simulated_rows(
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
    result = _simulated_rows(
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
    result = _simulated_rows([source, target], {"target": events}, {}, {}, 10.0)

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
    _simulated_rows(
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
    result = _simulated_rows(
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
    result = _simulated_rows(
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


def test_force_of_nature_stacks_and_reprices_the_maximum_stack_packet():
    stats = {
        "health": 5000.0,
        "armor": 30.0,
        "magic_resistance": 40.0,
        "bonus_armor": 0.0,
        "bonus_magic_resistance": 0.0,
        "is_melee": False,
    }
    target = Combatant(
        participant_id="target",
        team="enemy",
        champion_data={"name": "Ahri"},
        level=18,
        items=(get_item_by_name("Force of Nature"),),
        stats=stats,
        defenses=resolve_starting_defenses(
            "Ahri", 18, stats, [{"name": "Force of Nature"}]
        ),
    )
    source = _dummy_combatant("source", "main")
    events = [
        {
            "time": float(index),
            "damage": 50.0,
            "damage_type": "magic",
            "attacker": "source",
            "target": "target",
            "source_key": "Q",
            "sequence": index,
            "_event_id": f"force-{index}",
            "_baseline_effective_mr": 40.0,
        }
        for index in range(8)
    ]

    result = _simulated_rows([source, target], {"target": events}, {}, {}, 10.0)

    assert result["target"]["force_of_nature"]["stacks"] == 8
    assert result["target"]["force_of_nature"]["dynamic_bonus_magic_resistance"] == 70.0
    assert events[-1]["dynamic_resistance"]["effective"] == 110.0
    assert events[-1]["damage"] == pytest.approx(33.333333, rel=1e-6)


def test_jaksho_multiplies_bonus_resistances_after_five_combat_seconds():
    stats = {
        "health": 5000.0,
        "armor": 100.0,
        "magic_resistance": 100.0,
        "bonus_armor": 60.0,
        "bonus_magic_resistance": 60.0,
        "is_melee": False,
    }
    target = Combatant(
        participant_id="target",
        team="enemy",
        champion_data={"name": "Ahri"},
        level=18,
        items=(get_item_by_name("Jak'Sho, The Protean"),),
        stats=stats,
        defenses=resolve_starting_defenses(
            "Ahri", 18, stats, [{"name": "Jak'Sho, The Protean"}]
        ),
    )
    source = _dummy_combatant("source", "main")
    events = [
        {
            "time": 0.0,
            "damage": 50.0,
            "damage_type": "magic",
            "attacker": "source",
            "target": "target",
            "source_key": "Q",
            "sequence": 0,
            "_event_id": "jaksho-0",
            "_baseline_effective_mr": 100.0,
        },
        {
            "time": 5.0,
            "damage": 50.0,
            "damage_type": "magic",
            "attacker": "source",
            "target": "target",
            "source_key": "Q",
            "sequence": 1,
            "_event_id": "jaksho-5",
            "_baseline_effective_mr": 100.0,
        },
    ]

    result = _simulated_rows([source, target], {"target": events}, {}, {}, 10.0)

    assert result["target"]["jaksho"]["stacks"] == 5
    assert result["target"]["jaksho"]["dynamic_bonus_magic_resistance"] == 18.0
    assert events[1]["dynamic_resistance"]["effective"] == 118.0
    assert events[1]["damage"] < events[0]["damage"]


def test_explicit_time_stop_input_starts_stasis_and_blocks_until_expiry():
    stats = {"health": 100.0, "armor": 0.0, "magic_resistance": 0.0}
    target = Combatant(
        participant_id="target",
        team="enemy",
        champion_data={"name": "Ahri"},
        level=18,
        items=(get_item_by_name("Zhonya's Hourglass"),),
        stats=stats,
        defenses=resolve_starting_defenses(
            "Ahri",
            18,
            stats,
            [{"name": "Zhonya's Hourglass"}],
            item_options={"Zhonya's Hourglass": {"stasis_active_seconds": 2.5}},
        ),
    )
    source = _dummy_combatant("source", "main")
    incoming = {
        "target": [
            {
                "time": 1.0,
                "damage": 30.0,
                "damage_type": "magic",
                "attacker": "source",
                "target": "target",
                "sequence": 0,
                "_event_id": "stasis-blocked",
            },
            {
                "time": 3.0,
                "damage": 30.0,
                "damage_type": "magic",
                "attacker": "source",
                "target": "target",
                "sequence": 1,
                "_event_id": "stasis-live",
            },
        ]
    }

    result = _simulated_rows([source, target], incoming, {}, {}, 5.0)

    assert result["target"]["damage_taken"] == pytest.approx(30.0)
    assert result["target"]["stasis_until"] == pytest.approx(2.5)
    assert result["target"]["stasis_source"] == "Zhonya's Hourglass — Time Stop"
    assert result["target"]["action_downtime"] == pytest.approx(2.5)
    assert result["target"]["action_downtime_intervals"] == [
        {
            "recipient": "target",
            "kind": "stasis",
            "start": 0.0,
            "end": 2.5,
            "source": "Zhonya's Hourglass — Time Stop",
        }
    ]


def test_invulnerability_and_untargetability_receipts_expose_expiry_boundaries():
    holder = _dummy_combatant("holder", "main", health=100.0)
    support = {
        "holder": [
            {"time": 0.5, "kind": "invulnerability", "duration": 1.25},
            {"time": 1.0, "kind": "untargetable", "duration": 2.0},
        ]
    }
    result = _simulated_rows(
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
    result = _simulated_rows([source, target], {}, healing, {}, 10.0)
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
    result = _simulated_rows([early, late, target], incoming, healing, {}, 10.0)
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
    result = _simulated_rows(
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
    result = _simulated_rows([source, target], {"target": []}, healing, {}, 5.0)
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
    """The score adapter (parallel-array ledger) and the receipt adapter
    share one kernel: an overheal-to-temporary-health heal arms the window
    in the score walk exactly like the annotated walk."""

    combatants = [
        Combatant(
            participant_id="target",
            team="enemy",
            champion_data={"name": "target"},
            level=1,
            items=(),
            stats={"health": 100.0, "is_melee": True},
            defenses=StartingDefenses(
                magic_shield=0.0,
                physical_shield=0.0,
                general_shield=0.0,
                healing_received_multiplier=1.0,
            ),
        )
    ]
    action = SurvivalAction(
        sort_key=(
            0.0,
            TransitionRank.DEBUFF_ARM,
            0,
            0,
            0,
            "target",
            "heal",
            "Sundered Sky",
        ),
        time=0.0,
        phase=TransitionRank.RECOVERY,
        kind=ActionKind.HEAL,
        subject=0,
        attacker=0,
        aidx=0,
        amount=50.0,
        overheal_to_temporary_health=True,
        temporary_health_duration=2.0,
        source_key="heal",
        source="Sundered Sky (Lightshield Strike)",
        event_slot=EVENT_SLOTS.slot("heal"),
        sequence=0,
    )
    states = build_states(combatants, (0.0,) * len(combatants))
    ledger = ScoreLedger(1)
    ctx = TransitionContext(
        duration=5.0,
        states=states,
        combatants=combatants,
        index_of={"target": 0},
        ledger=ledger,
        # No participant declares a regeneration window; the sequence is
        # required rather than defaulted so "none declared" and "nobody
        # compiled them" cannot be the same context.
        regeneration_windows=(None,) * len(combatants),
    )
    rows = survival(roster_program(combatants), run_one_walk([action], ctx))
    assert ledger.applied == [0.0]
    assert rows["target"]["temporary_health_received"] == 50.0
    assert rows["target"]["temporary_health_expired_at"] == 2.0
    assert rows["target"]["max_health"] == 100.0
    assert rows["target"]["ending_health"] == 100.0


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


def test_pair_cache_reuse_survives_redirect_expansion():
    """Knight's Vow rewrites incoming packets during the survival
    composition; a served pair view's receipts must stay byte-identical
    to a fresh no-cache computation across every rewrite."""
    from src.calculator.defensive_effects import resolve_starting_defenses
    from src.calculator.scenario import ChampionLoadout
    from src.calculator.stats import calculate_total_stats

    params = FightParams.from_request(
        {
            "fight_mode": "time_based",
            "fight_duration": 12,
            "role": "mid",
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
        },
        deterministic=True,
    )
    champion = get_champion("Ahri")
    enemies = [ChampionLoadout(champion="Janna", level=18, role="support").resolve()]
    allies = [
        ChampionLoadout(
            champion="Ashe", level=18, role="bottom", items=("Knight's Vow",)
        ).resolve()
    ]
    items = [get_item_by_name("Infinity Edge")]
    stats = calculate_total_stats(champion, 18, items, role="mid")
    defenses = resolve_starting_defenses("Ahri", 18, stats, items)

    def timeline(**kwargs):
        return build_participant_timeline(
            champion,
            18,
            items,
            params,
            main_stats=stats,
            main_defenses=defenses,
            enemies=enemies,
            allies=allies,
            **kwargs,
        )

    fresh = timeline()
    cache: dict = {}
    assert timeline(pair_result_cache=cache) == fresh
    assert timeline(pair_result_cache=cache) == fresh


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


def test_noxian_reactive_shield_is_granted_after_matching_damage_only():
    source = _dummy_combatant("source", "enemy", health=1000.0)
    target = Combatant(
        participant_id="target",
        team="main",
        champion_data={"name": "target"},
        level=18,
        items=(),
        stats={"health": 1000.0},
        defenses=StartingDefenses(
            magic_shield=0.0,
            physical_shield=0.0,
            general_shield=0.0,
            healing_received_multiplier=1.0,
            reactive_shield_amount=200.0,
            reactive_shield_damage_type="physical",
            reactive_shield_duration=5.0,
            reactive_shield_cooldown=15.0,
            reactive_shield_source="Armored Advance — Noxian",
        ),
    )
    physical = {
        "time": 0.0,
        "damage": 100.0,
        "damage_type": "physical",
        "attacker": "source",
        "target": "target",
        "_event_id": "physical-hit",
    }
    magic = {
        "time": 0.1,
        "damage": 100.0,
        "damage_type": "magic",
        "attacker": "source",
        "target": "target",
        "_event_id": "magic-hit",
    }
    result = _simulated_rows(
        [source, target],
        {
            "target": [
                physical,
                {**physical, "time": 0.1, "_event_id": "physical-second"},
                magic,
            ]
        },
        {},
        {},
        10.0,
    )

    assert physical["reactive_shield_triggered"]["amount"] == pytest.approx(200.0)
    assert "reactive_shield_triggered" not in magic
    assert result["target"]["shield_absorbed"] == pytest.approx(100.0)
    assert result["target"]["ending_health"] == pytest.approx(800.0)


def test_celestial_opposition_reduction_lingers_two_seconds():
    source = _dummy_combatant("source", "enemy", health=1000.0)
    target = Combatant(
        participant_id="target",
        team="main",
        champion_data={"name": "target"},
        level=1,
        items=(),
        stats={"health": 1000.0},
        defenses=StartingDefenses(
            magic_shield=0.0,
            physical_shield=0.0,
            general_shield=0.0,
            healing_received_multiplier=1.0,
            incoming_damage_multiplier=0.65,
            incoming_damage_linger=2.0,
            incoming_damage_cooldown=20.0,
            incoming_damage_source="Celestial Opposition — Blessed",
        ),
    )
    first = {
        "time": 0.0,
        "damage": 100.0,
        "damage_type": "magic",
        "attacker": "source",
        "target": "target",
        "_event_id": "first",
    }
    second = {**first, "time": 1.0, "_event_id": "second"}
    third = {**first, "time": 3.1, "_event_id": "third"}
    _simulated_rows(
        [source, target],
        {"target": [first, second, third]},
        {},
        {},
        10.0,
    )

    assert first["damage"] == pytest.approx(65.0)
    assert second["damage"] == pytest.approx(65.0)
    assert third["damage"] == pytest.approx(100.0)


def test_bloodthirster_converts_explicit_lifesteal_excess_to_uncapped_duration_shield():
    source = _dummy_combatant("source", "enemy", health=1000.0)
    target = Combatant(
        participant_id="target",
        team="main",
        champion_data={"name": "target"},
        level=18,
        items=(),
        stats={"health": 100.0},
        defenses=StartingDefenses(
            magic_shield=0.0,
            physical_shield=0.0,
            general_shield=0.0,
            healing_received_multiplier=1.0,
            bloodthirster_shield_cap=315.0,
            bloodthirster_starting_shield=0.0,
        ),
    )
    damage = {
        "time": 0.0,
        "damage": 20.0,
        "damage_type": "physical",
        "attacker": "source",
        "target": "target",
        "_event_id": "opening-hit",
    }
    heal = {
        "time": 1.0,
        "amount": 100.0,
        "kind": "heal",
        "healing_category": "vamp",
        "source": "Life steal",
        "attacker": "target",
        "target": "target",
    }
    result = _simulated_rows(
        [source, target], {"target": [damage]}, {"target": [heal]}, {}, 10.0
    )

    assert result["target"]["remaining_shield"] == pytest.approx(80.0)
    assert result["target"]["support_shield_received"] == pytest.approx(80.0)


def test_search_context_keeps_item_heals_and_ignores_post_window_packets():
    """Compiled scoring matches the event walk for item-owned healing.

    The Dusk-and-Dawn Spellblade heal path runs alongside Ahri's E9-2
    Essence Theft passive heal (107 with the item's 60 AP); the second
    proc is timestamped at 4.5s while the authored fight window ends at
    4s and must not affect the score-only survival walk.
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
            "ability_ranks": {"Q": 5, "W": 5, "E": 0, "R": 3},
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
    # 107 Essence Theft (60 AP from Dusk and Dawn) + 15 item heal.
    assert main["survival"]["healing_received"] == 122.0


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
    that set would silently drop the champion's packets.  The gate is now
    the union of the two declared lookup tuples, so what this asserts is
    that the profile still reads THOSE tuples — an inline literal would
    reopen the gap the union closes.
    """
    import inspect
    import re as re_module

    from src.calculator import support_effects

    source = inspect.getsource(support_effects._support_profile)
    lookups = re_module.findall(r"_first_attribute\(ability, (\w+)\)", source)
    assert sorted(lookups) == ["_HEAL_ATTRIBUTES", "_SHIELD_ATTRIBUTES"]
    assert set(support_effects._SUPPORT_ATTRIBUTES) == set(
        support_effects._SHIELD_ATTRIBUTES
    ) | set(support_effects._HEAL_ATTRIBUTES)


def test_healing_rule_champions_matches_the_dispatch_source():
    """Every healing name has a declaration in its champion module.

    The scoring fast path reads the same exported set as the public healing
    entrypoint. A missing local declaration would make the import fail before
    a fight can silently skip the rule.
    """
    import importlib

    from src.calculator import healing
    from src.calculator.champions import _CHAMPION_MODULES
    from src.calculator.champions.healing_contract import ChampionHealingRule

    for name in healing.HEALING_RULE_CHAMPIONS:
        module = importlib.import_module(
            f"src.calculator.champions.{_CHAMPION_MODULES[name]}"
        )
        declaration = getattr(module, "SELF_HEALING_RULE", None)
        assert isinstance(declaration, ChampionHealingRule)
        assert declaration.champion_name == name


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


# ── the regeneration window, compiled from the declaration (3.9) ─────────


def _regen_combatant(*item_names: str) -> Combatant:
    """A participant carrying only the items the window compiler reads."""
    return Combatant(
        participant_id="target",
        team="enemy",
        champion_data={"name": "Garen", "attackType": "MELEE"},
        level=9,
        items=tuple({"name": name} for name in item_names),
        stats={"health": 1500.0},
        defenses=StartingDefenses(),
    )


def test_the_regeneration_window_compiles_the_declarations_own_numbers():
    """Every number the walk pays is the key the retired branch read.

    Asserted against ``sustain_effect_value`` rather than literals: this
    migration claims the declaration reproduces the five hand reads, and a
    literal would still pass on the commit that broke the reference.
    """
    from src.calculator.item_effects import sustain_effect_value

    (window,) = _regeneration_windows([_regen_combatant("Doran's Shield")])

    assert window is not None
    assert window.owner == "Doran's Shield"
    for field_name, key in (
        ("total_melee", "enduring_focus_total_melee"),
        ("total_reduced", "enduring_focus_total_reduced"),
        ("duration", "enduring_focus_duration"),
        ("missing_health_cap", "enduring_focus_missing_health_cap"),
        ("tick_interval", "health_regen_tick_interval"),
    ):
        assert getattr(window, field_name) == sustain_effect_value(
            "Doran's Shield", key
        )


def test_a_participant_declaring_no_regeneration_compiles_none():
    """An absent window is an answer; five defaulted zeros would not be."""
    assert _regeneration_windows([_regen_combatant("Ruby Crystal")]) == (None,)


def test_a_short_window_sequence_stops_rather_than_misaligning():
    """R-05's red: the sequence is participant-index-aligned or it is wrong."""
    combatants = [_regen_combatant("Doran's Shield"), _regen_combatant()]

    with pytest.raises(ValueError, match="participant-index-aligned"):
        TransitionContext(
            duration=5.0,
            # The alignment check runs before any state is read, which is the
            # point: a misaligned context must not get as far as a walk.
            states=[],
            combatants=combatants,
            index_of={"target": 0},
            ledger=ScoreLedger(0),
            regeneration_windows=(None,),
        )


def test_a_ledger_without_the_capability_flags_is_refused():
    """The kernel reads ``SurvivalLedger``'s flags directly, never by default.

    A silent ``True`` default let a stand-in ledger buy full observation it
    never declared; the read now names the missing attribute.
    """

    class Bare:  # pylint: disable=too-few-public-methods
        """A ledger-shaped object that declares no capability flags."""

    with pytest.raises(AttributeError, match="records_annotations"):
        TransitionContext(
            duration=5.0,
            states=[],
            combatants=[],
            index_of={},
            ledger=Bare(),
            regeneration_windows=(),
        )


def test_the_below_half_bonus_compiles_the_declarations_own_number():
    """The walk's bonus is the key ``receipt_state`` read by item name.

    Asserted against ``sustain_effect_value`` rather than a literal, for the
    reason the regeneration window is: this migration's claim is that the
    declaration reproduces the hand read exactly, and a literal would still
    pass on the commit that broke the reference.
    """
    from src.calculator.item_effects import sustain_effect_value
    from src.calculator.participant_timeline import _below_half_healing_bonuses

    assert _below_half_healing_bonuses([_regen_combatant("Immortal Path")]) == (
        sustain_effect_value(
            "Immortal Path", "health_state_healing_multiplier_below_half"
        ),
    )


def test_a_participant_declaring_no_below_half_bonus_compiles_zero():
    """Nobody declares one, so the walk multiplies by nothing.

    Zero rather than ``None`` here and ``None`` for the regeneration window,
    because the two absences are different: a window is five numbers the walk
    would otherwise have to invent, and this is one share the walk adds only
    while it is positive — so an absent bonus and a sourced zero are the same
    arithmetic and the same answer.
    """
    from src.calculator.participant_timeline import _below_half_healing_bonuses

    assert _below_half_healing_bonuses([_regen_combatant("Ruby Crystal")]) == (0.0,)


def test_a_short_bonus_sequence_stops_rather_than_misaligning():
    """R-05's red: the state builder's sequence is aligned or it is wrong."""
    from src.calculator.survival import build_states

    combatants = [_regen_combatant("Immortal Path"), _regen_combatant()]

    with pytest.raises(ValueError, match="participant-index-aligned"):
        build_states(combatants, (0.0,))


class TestThePairCacheKeyCarriesEveryInputThatPricedIt:
    """Phase 4 S8 — one key function, and the resource ledger is in it.

    A cached pair packet is replayed for every later evaluation whose key
    matches, so a priced-in input missing from the key is a stale packet
    served as a fresh one.  The cross-pass ledger is the input a second pass
    changes, and it is the reason the recursive repass gives itself an empty
    cache today.
    """

    def test_two_passes_of_one_pair_do_not_share_a_key(self):
        from src.calculator.participant_timeline import _pair_cache_key

        pass_one = _pair_cache_key("ally:Lulu", "enemy:Aatrox", (), ())
        pass_two = _pair_cache_key(
            "ally:Lulu", "enemy:Aatrox", (), ((1.5, 40.0), (3.0, 55.0))
        )
        assert pass_one != pass_two

    def test_an_unpatched_pass_keys_identically_across_both_lanes(self):
        """The compiled panel and the receipt walk share one cache.

        Their docstrings say they interoperate; this is that claim as a
        test rather than a sentence, and it is what makes the constant the
        compiled lane passes checkable instead of assumed.
        """
        from src.calculator.participant_timeline import (
            _UNPATCHED_RESTORES,
            _pair_cache_key,
        )

        assert _pair_cache_key(
            "enemy:Aatrox", "ally:Jax", (), _UNPATCHED_RESTORES
        ) == _pair_cache_key("enemy:Aatrox", "ally:Jax", (), ())

    def test_the_defensive_signature_still_separates_main_candidates(self):
        from src.calculator.participant_timeline import _pair_cache_key

        thin = _pair_cache_key("enemy:Aatrox", "main", (60.0, 30.0), ())
        thick = _pair_cache_key("enemy:Aatrox", "main", (140.0, 30.0), ())
        assert thin != thick

    def test_a_defended_main_never_collides_with_a_roster_defender(self):
        """The two key shapes the widening unified may not fold together."""
        from src.calculator.participant_timeline import _pair_cache_key

        assert _pair_cache_key(
            "enemy:Aatrox", "main", (60.0, 30.0), ()
        ) != _pair_cache_key("enemy:Aatrox", "main", (), ())


class TestCatalystIsTwoPassesAndNotARecursion:
    """Phase 4 S8 — D-70's four clauses, over the live mana-spent heal.

    Catalyst of Aeons' Eternity restore is a function of the incoming damage
    the fight itself produces, so the composition has to be priced twice.
    Doing that by re-entering the composer from inside itself is what made
    the path unrepresentable: a walk that can call the thing that called it
    has no single invocation to count and no single result to project a view
    from.
    """

    @staticmethod
    def _catalyst_roster():
        """Ahri holding Catalyst, two enemies who hit her, one ally."""
        main = ChampionLoadout(
            champion="Ahri", level=13, role="mid", items=("Catalyst of Aeons",)
        ).resolve()
        enemies = [
            ChampionLoadout(champion=name, level=13, role="top").resolve()
            for name in ("Aatrox", "Malphite")
        ]
        allies = [ChampionLoadout(champion="Pantheon", level=13).resolve()]
        return main, enemies, allies

    @classmethod
    def _timeline(cls, **overrides):
        main, enemies, allies = cls._catalyst_roster()
        params = FightParams.from_request(
            {"fight_mode": "one_rotation", "role": "mid"}, deterministic=True
        )
        arguments = dict(
            main_stats=main.stats,
            main_defenses=main.defenses,
            enemies=enemies,
            allies=allies,
        )
        arguments.update(overrides)
        return build_participant_timeline(
            main.champion_data,
            main.request.level,
            list(main.item_data),
            params,
            **arguments,
        )

    def test_the_composer_never_calls_itself(self):
        """Criterion 13's first clause, read off source rather than claimed."""
        import ast
        from pathlib import Path

        source = Path("src/calculator/participant_timeline.py").read_text(
            encoding="utf-8"
        )
        calls = [
            node
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "build_participant_timeline"
        ]
        assert calls == []

    def test_a_catalyst_roster_declares_two_passes(self):
        from src.calculator.participant_timeline import _cross_pass_dependencies

        main, enemies, allies = self._catalyst_roster()
        declared = _cross_pass_dependencies(list(main.item_data), enemies, allies)

        assert [dep.max_passes for dep in declared] == [2]
        assert declared[0].reads == "resource_restores"
        assert "mana_spent_heal" in declared[0].mechanic

    def test_a_roster_without_one_declares_nothing(self):
        """One pass, and therefore zero cost, for every other roster."""
        from src.calculator.participant_timeline import _cross_pass_dependencies

        plain = ChampionLoadout(
            champion="Ahri", level=13, role="mid", items=("Luden's Echo",)
        ).resolve()
        assert _cross_pass_dependencies(list(plain.item_data), [], []) == ()

    def test_the_second_pass_prices_the_restores_the_first_derived(self):
        """Two passes, and the second differs from the first only by a patch.

        Spying on the pass function rather than on a heal amount, because
        the property under test is the shape -- pass 2 exists, it runs once,
        and everything it knows that pass 1 did not arrived in a declared
        ``ParamPatch`` under the dependency's own ``reads`` field.
        """
        from src.calculator import participant_timeline as timeline

        seen = []
        original = timeline._compose_pass

        def spy(*args, **kwargs):
            seen.append((kwargs["pass_index"], kwargs["patch"]))
            return original(*args, **kwargs)

        timeline._compose_pass = spy
        try:
            combat = self._timeline()
        finally:
            timeline._compose_pass = original

        assert [index for index, _ in seen] == [1, 2]
        assert seen[0][1] is None
        assert set(seen[1][1].overrides) == {"resource_restores"}
        assert seen[1][1].overrides["resource_restores"]["main"]
        assert [
            event
            for event in combat["healing_events"]
            if "Catalyst of Aeons" in str(event.get("source", ""))
        ]

    def test_the_second_pass_keeps_the_search_context_and_its_counters(self):
        """Criterion 13's "caches and search context live" clause.

        The recursive repass passed ``search_context=None``, which put every
        pair fight of the second pricing outside the work counters -- a
        measurement hole that read as a cheaper request than it was.
        """
        from collections import Counter
        from dataclasses import dataclass, field

        @dataclass(slots=True)
        class Sink:
            measured_proposals: int = 0
            score_memo_misses: int = 0
            pair_run_fight_calls: int = 0
            walk_invocations: int = 0
            rungs: Counter = field(default_factory=Counter)
            rung_receipts: Counter = field(default_factory=Counter)

        two_pass = Sink()
        self._timeline(search_context=CoupledSearchContext(work_counters=two_pass))

        one_pass = Sink()
        main = ChampionLoadout(
            champion="Ahri", level=13, role="mid", items=("Luden's Echo",)
        ).resolve()
        params = FightParams.from_request(
            {"fight_mode": "one_rotation", "role": "mid"}, deterministic=True
        )
        _, enemies, allies = self._catalyst_roster()
        build_participant_timeline(
            main.champion_data,
            main.request.level,
            list(main.item_data),
            params,
            main_stats=main.stats,
            main_defenses=main.defenses,
            enemies=enemies,
            allies=allies,
            search_context=CoupledSearchContext(work_counters=one_pass),
        )

        assert two_pass.pair_run_fight_calls > one_pass.pair_run_fight_calls
        # ...and one evaluation still lands on exactly one rung, because the
        # rung belongs to the evaluation and not to the pass.
        assert sum(two_pass.rungs.values()) == sum(one_pass.rungs.values()) == 1

    def test_both_passes_share_the_callers_one_cache(self):
        """The other half of "caches live": one dict, two passes, no collision.

        The recursive repass handed itself a fresh dict, so pass 2 re-priced
        every pair fight in the roster.  The key now carries the ledger that
        priced a packet, so the two passes share the caller's cache: the
        fights whose inputs the patch did not change are *served* from pass
        1, and only the holder's own fights get a second entry under their
        own ledger.  An ally holds the Catalyst here so both halves of that
        split are visible in one cache.
        """
        main = ChampionLoadout(
            champion="Ahri", level=13, role="mid", items=("Luden's Echo",)
        ).resolve()
        _, enemies, _ = self._catalyst_roster()
        holder = ChampionLoadout(
            champion="Pantheon", level=13, items=("Catalyst of Aeons",)
        ).resolve()
        cache: dict = {}
        build_participant_timeline(
            main.champion_data,
            main.request.level,
            list(main.item_data),
            FightParams.from_request(
                {"fight_mode": "one_rotation", "role": "mid"}, deterministic=True
            ),
            main_stats=main.stats,
            main_defenses=main.defenses,
            enemies=enemies,
            allies=[holder],
            pair_result_cache=cache,
        )

        repriced = {key[:2] for key in cache if key[3]}
        served = {key[:2] for key in cache if not key[3]}
        assert repriced == {
            ("ally:Pantheon", "enemy:Aatrox"),
            ("ally:Pantheon", "enemy:Malphite"),
        }
        assert repriced <= served, "pass 2 re-priced a fight pass 1 never priced"
        assert served - repriced, "pass 2 re-priced fights the patch did not change"

    def test_an_unanswerable_ledger_raises_the_typed_failure(self):
        """Criterion 13's third clause: not an untyped ValueError.

        A caller could not previously tell "this needs another pass" from
        "this request is malformed" -- both arrived as ValueError, and
        /api/calculate turned both into a 400.
        """
        from src.calculator.program.dependency import IncompleteDependency
        from src.calculator import participant_timeline as timeline

        assert not issubclass(IncompleteDependency, ValueError)

        broken = lambda actor, incoming, duration: ((), False)
        original = timeline._declared_resource_restores
        timeline._declared_resource_restores = broken
        try:
            with pytest.raises(IncompleteDependency) as raised:
                self._timeline()
        finally:
            timeline._declared_resource_restores = original

        assert "mana_spent_heal" in raised.value.dependency.mechanic
        assert "restore ledger is unavailable" in str(raised.value)

    def test_the_compiled_lane_is_closed_to_a_patched_pass(self):
        """Criterion 13's fourth clause: the Compilability did not flip.

        The declaration still refuses the compiled kernel, so the second
        pass takes the receipt walk by declaration rather than by the
        accident of a null search context.
        """
        from src.calculator.item_behavior import ReceiptOnly
        from src.calculator.roster_composition import mana_spent_heal_slot

        slot = mana_spent_heal_slot([{"name": "Catalyst of Aeons"}])
        assert isinstance(slot.rule.compilability, ReceiptOnly)
        assert "second pass" in slot.rule.compilability.reason


class TestThePublishedReceiptFieldsHaveOneProducer:
    """Two fields the receipt view used to compute for itself (criterion 3).

    Both were spelled as a *default* behind ``event.get(...)``, which is the
    least visible way for a published number to acquire a second producer:
    the walk annotates the field on the paths it reaches, and the projection
    quietly answered for the paths it does not.  The composition answers for
    both now, and the view reads the key by name.
    """

    def test_a_skipped_recovery_is_given_the_overheal_it_publishes(self) -> None:
        from src.calculator.participant_timeline import _annotate_overheal

        skipped = {"amount": 31.5, "applied_amount": 0.0, "skipped_reason": "x"}
        _annotate_overheal([skipped])
        assert skipped["overheal"] == 31.5

    def test_a_reduced_recovery_overheals_only_what_it_did_not_apply(self) -> None:
        from src.calculator.participant_timeline import _annotate_overheal

        event = {"amount": 40.0, "reduced_amount": 24.0, "applied_amount": 10.0}
        _annotate_overheal([event])
        assert event["overheal"] == 14.0

    def test_the_walks_own_annotation_is_never_overwritten(self) -> None:
        """The applied path's overheal is a different, narrower quantity."""
        from src.calculator.participant_timeline import _annotate_overheal

        event = {"amount": 40.0, "applied_amount": 10.0, "overheal": 0.0}
        _annotate_overheal([event])
        assert event["overheal"] == 0.0

    def test_a_recovery_that_applied_everything_overheals_nothing(self) -> None:
        from src.calculator.participant_timeline import _annotate_overheal

        event = {"amount": 12.0, "applied_amount": 30.0}
        _annotate_overheal([event])
        assert event["overheal"] == 0.0

    def test_the_receipt_view_reads_overheal_rather_than_deriving_it(self) -> None:
        """A healing row with no annotated overheal is a composition bug."""
        from src.calculator.program.views import LeafWriter
        from src.calculator.program.views import receipt as receipt_view

        with pytest.raises(KeyError):
            # pylint: disable-next=protected-access
            receipt_view._healing_event_rows(
                [{"time": 0.0, "amount": 5.0}], LeafWriter(), "healing_events"
            )

    def test_the_receipt_view_reads_the_wound_window_rather_than_closing_it(
        self,
    ) -> None:
        """A wounded damage row with no annotated window is a composition bug."""
        from src.calculator.program.views import LeafWriter
        from src.calculator.program.views import receipt as receipt_view

        with pytest.raises(KeyError):
            # pylint: disable-next=protected-access
            receipt_view._damage_event_rows(
                [{"time": 1.0, "grievous_duration": 3.0}], LeafWriter(), "events"
            )

    def test_a_champion_wound_publishes_the_instant_its_window_closes(self) -> None:
        """Varus E is the third arming site, and it now annotates like the others."""
        app.config["TESTING"] = True
        response = app.test_client().post(
            "/api/calculate",
            json={
                "champion": "Varus",
                "level": 18,
                "items": [],
                "fight_mode": "time_based",
                "fight_duration": 10,
                "enemies": [{"champion": "Aatrox", "level": 18, "items": []}],
            },
        )
        assert response.status_code == 200
        wounded = [
            event
            for event in response.get_json()["combat"]["events"]
            if event.get("wound_duration")
        ]
        assert wounded, "Varus E arms no wound; the fixture no longer covers the site"
        for event in wounded:
            assert event["wound_until"] == pytest.approx(
                event["time"] + event["wound_duration"], abs=1e-3
            )


class TestSelfStateEventIdsNameTheirOwner:
    """A self-state packet's published id names the actor that cast it.

    A champion module authors its self-state ids out of what a champion
    knows -- slot, cast ordinal, packet ordinal, so Alistar R is always
    ``self_state:R:0:0`` -- and a keystone authors its own against the
    fight's own actor.  Neither knows which roster slot the pair fight was
    priced for, so every actor holding the mechanic authors the *same* id.
    The roster fold is the first place the owner exists, and it re-keys
    there, exactly as ``_pair_packet`` already does for damage and control
    packets.

    Without the re-key a roster holding one champion twice publishes one id
    twice on one panel, which ``precision.SumPlan`` refuses at construction
    (``DuplicateSumMember``) -- and refusing it is right twice over, because
    an event id is also the walk's join key, so a shared id cross-links two
    actors' riders as well as double-counting one panel.
    """

    @staticmethod
    def _duplicate_alistar_roster() -> dict:
        """The live ``cassiopeia_5champ`` shape, reduced to what breaks it.

        Alistar is the ally support *and* the enemy support; both cast R.
        Cross-team is the only reachable duplicate-champion roster -- the
        scenario boundary refuses duplicates *within* a team -- so this is
        the shape, not a shape.
        """
        return {
            "champion": "Cassiopeia",
            "level": 13,
            "fight_mode": "one_rotation",
            "role": "mid",
            "ally_effects_enabled": True,
            "allies": [
                {"champion": "Alistar", "level": 13, "role": "support", "items": []}
            ],
            "enemies": [
                {"champion": "Alistar", "level": 13, "role": "support", "items": []},
                {"champion": "Dr. Mundo", "level": 13, "role": "top", "items": []},
            ],
        }

    def test_two_alistars_publish_two_distinct_owner_named_ids(self) -> None:
        """The regression: one panel, two R packets, two ids."""
        app.config["TESTING"] = True
        response = app.test_client().post(
            "/api/calculate", json=self._duplicate_alistar_roster()
        )
        # A served 200 is itself half the assertion: the receipt builds a
        # ``SumPlan`` over its three panels, so a duplicated id raises out
        # of ``/api/calculate`` rather than serving repeated rows.
        assert response.status_code == 200
        support_events = response.get_json()["combat"]["support_events"]
        unbreakable = [
            event
            for event in support_events
            if str(event.get("source", "")).startswith("Unbreakable Will")
        ]
        assert len(unbreakable) == 2, "the fixture no longer casts R on both Alistars"
        assert sorted(event["event_id"] for event in unbreakable) == [
            "ally:Alistar:self_state:R:0:0",
            "enemy:Alistar:self_state:R:0:0",
        ]
        # Each packet is self-targeted, so the owner in the id is the owner
        # in the packet -- the re-key names the caster, not the recipient.
        for event in unbreakable:
            assert event["event_id"].startswith(f"{event['attacker']}:")
            assert event["target"] == event["attacker"]

    def test_every_published_panel_id_is_unique_within_its_panel(self) -> None:
        """The invariant the fold exists to hold, over all three panels."""
        app.config["TESTING"] = True
        response = app.test_client().post(
            "/api/calculate", json=self._duplicate_alistar_roster()
        )
        assert response.status_code == 200
        combat = response.get_json()["combat"]
        for panel in ("events", "healing_events", "support_events"):
            ids = [
                event["event_id"]
                for event in combat[panel]
                if event.get("event_id") is not None
            ]
            assert ids, f"panel {panel} publishes no identified rows"
            duplicated = sorted({one for one in ids if ids.count(one) > 1})
            assert (
                not duplicated
            ), f"panel {panel} publishes {duplicated} more than once"

    def test_an_id_that_already_names_this_actor_is_left_verbatim(self) -> None:
        """A keystone authors ``main:...`` against the fight's own actor.

        That id already names its owner, so ``main`` keeps the published
        spelling rather than gaining ``main:main:``; a second actor holding
        the same keystone gains its own prefix and is distinct.
        """
        authored = {"_event_id": "main:conqueror:stack:0"}
        assert _owned_state_event_id("main", authored, 0) == "main:conqueror:stack:0"
        assert (
            _owned_state_event_id("enemy:Alistar", authored, 0)
            == "enemy:Alistar:main:conqueror:stack:0"
        )
        # A prefix match is on the whole participant id plus its separator,
        # so a participant whose id is a prefix of another's is not read as
        # already-owned.
        assert (
            _owned_state_event_id("main_2", authored, 0)
            == "main_2:main:conqueror:stack:0"
        )

    def test_an_unauthored_packet_is_named_by_owner_and_ordinal(self) -> None:
        """No authored id: the fold names the owner and the packet ordinal."""
        assert _owned_state_event_id("ally:Alistar", {}, 3) == "ally:Alistar:state:3"
