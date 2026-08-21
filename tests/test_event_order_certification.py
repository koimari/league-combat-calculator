"""Regression tests for champion-owned event-order receipts."""

import pytest

from src.calculator.scenario import load_public_champion as _load_public_champion
from src.app import app
from src.calculator.champions import (
    get_champion_options_meta,
    get_supported_fight_modes,
    get_unsupported_fight_mode_reason,
)
from src.calculator.champions.slotlib import extract_cooldown
from src.calculator.pipeline import FightParams, run_fight


def _timed_params():
    return FightParams.from_request(
        {
            "fight_mode": "time_based",
            "fight_duration": 8,
            "include_auto_attacks": True,
            "auto_attack_uptime": 0.8,
            "target_health": 1000,
            "target_armor": 100,
            "target_mr": 100,
        },
        deterministic=True,
    )


def test_briar_and_darius_empowered_auto_receipts_match_aggregates():
    for champion in ("Briar", "Darius"):
        result = run_fight(_load_public_champion(champion), 18, [], _timed_params())
        assert result["timeline_coverage"]["complete"] is True
        auto = result["breakdown"]["auto_attacks"]
        assert sum(event["damage"] for event in auto["damage_events"]) == pytest.approx(
            auto["total_damage"]
        )


@pytest.mark.parametrize("champion", ("Briar", "Darius"))
def test_stack_dot_receipts_mark_sourced_tick_cadence_exact(champion):
    result = run_fight(_load_public_champion(champion), 18, [], _timed_params())
    key = "stacking_dot_passive"
    events = result["breakdown"][key]["damage_events"]
    assert events
    assert {event["event_precision"] for event in events} == {"exact"}


def test_akshan_passive_and_double_shot_follow_the_auto_ledger():
    result = run_fight(_load_public_champion("Akshan"), 18, [], _timed_params())
    assert result["timeline_coverage"]["complete"] is True
    passive = result["breakdown"]["passive"]
    assert passive["count"] == 1  # five swings yield one complete 3-stack proc
    assert passive["damage_events"]
    double_shot = result["breakdown"]["double_shot"]
    assert len(double_shot["damage_events"]) == double_shot["count"]
    assert sum(
        event["damage"] for event in double_shot["damage_events"]
    ) == pytest.approx(double_shot["total_damage"])


def test_ziggs_short_fuse_uses_cached_cooldown_and_cast_refunds():
    result = run_fight(_load_public_champion("Ziggs"), 18, [], _timed_params())
    assert result["timeline_coverage"]["complete"] is True
    passive = result["breakdown"]["passive"]
    assert passive["event_phase"] == "auto"
    assert len(passive["damage_events"]) == passive["count"]
    assert passive["damage_events"][0]["time"] == pytest.approx(0.0)
    assert [event["event_precision"] for event in passive["damage_events"]] == [
        "exact"
    ] * passive["count"]
    assert sum(event["damage"] for event in passive["damage_events"]) == pytest.approx(
        passive["total_damage"]
    )


def test_braum_concussive_blows_emits_exact_stack_and_immunity_events():
    result = run_fight(_load_public_champion("Braum"), 18, [], _timed_params())
    assert result["timeline_coverage"]["complete"] is True
    passive = result["breakdown"]["passive"]
    assert passive["damage_events"]
    assert sum(event["damage"] for event in passive["damage_events"]) == pytest.approx(
        passive["total_damage"]
    )


def test_diana_moonsilver_cleave_is_placed_on_every_third_auto():
    result = run_fight(_load_public_champion("Diana"), 18, [], _timed_params())
    assert result["timeline_coverage"]["complete"] is True
    cleave = result["breakdown"]["auto_attacks_moonsilver_cleave"]
    assert cleave["count"] == len(cleave["damage_events"])
    assert sum(event["damage"] for event in cleave["damage_events"]) == pytest.approx(
        cleave["total_damage"]
    )


def test_soraka_equinox_emits_the_delayed_eruption_hit():
    result = run_fight(_load_public_champion("Soraka"), 18, [], _timed_params())
    assert result["timeline_coverage"]["complete"] is True
    eruption = result["breakdown"]["E"]["damage_events"]
    # E8d: Astral Infusion (W) is now a zero-damage support cast that joins
    # the rotation, so Equinox casts at t=0.5 instead of t=0.25 and its
    # eruption lands at t=2.0 (initial hit + 1.5s).
    assert [round(event["time"], 2) for event in eruption] == [0.5, 2.0]
    assert {event["event_precision"] for event in eruption} == {"exact"}


@pytest.mark.parametrize("champion,source", (("Shen", "Q"),))
def test_empowered_attack_packets_certify_their_authored_swing_ledger(champion, source):
    """Wave 1B: Shen Q's bonus hits carry authored swing timing."""
    result = run_fight(_load_public_champion(champion), 18, [], _timed_params())
    assert result["timeline_coverage"]["complete"] is True
    assert source in result["timeline_coverage"]["exact_sources"]
    events = result["breakdown"][source]["damage_events"]
    assert events
    assert {event["event_precision"] for event in events} == {"exact"}


def test_belveth_ability_carried_ramping_on_hit_has_authored_carrier_times():
    result = run_fight(_load_public_champion("Bel'Veth"), 18, [], _timed_params())
    assert result["timeline_coverage"]["complete"] is True
    assert "on_hit_ability_R_onhit" in result["timeline_coverage"]["exact_sources"]
    events = result["breakdown"]["on_hit_ability_R_onhit"]["damage_events"]
    assert events
    assert all("time" in event for event in events)


@pytest.mark.parametrize("champion,source", (("Wukong", "R"), ("Qiyana", "R")))
def test_multi_stage_ultimates_use_authored_subhit_cadence(champion, source):
    result = run_fight(_load_public_champion(champion), 18, [], _timed_params())
    assert result["timeline_coverage"]["complete"] is True
    assert source in result["timeline_coverage"]["exact_sources"]


@pytest.mark.parametrize("champion,source", (("Ornn", "W"), ("Kalista", "W")))
def test_multi_hit_or_ally_mark_packets_are_certified_or_explicitly_non_damage(
    champion, source
):
    result = run_fight(_load_public_champion(champion), 18, [], _timed_params())
    assert result["timeline_coverage"]["complete"] is True
    assert source not in result["timeline_coverage"]["coarse_sources"]


@pytest.mark.parametrize(
    "champion,source",
    (("Shen", "Q"),),
)
def test_calculate_api_surfaces_certified_empowered_attack_timeline(champion, source):
    """Wave 1B: the public API no longer reports Shen Q as coarse."""
    app.config["RATE_LIMIT_ENABLED"] = False
    with app.test_client() as client:
        response = client.post(
            "/api/calculate",
            json={
                "champion": champion,
                "level": 18,
                "fight_mode": "time_based",
                "fight_duration": 8,
                "include_auto_attacks": True,
                "auto_attack_uptime": 0.8,
            },
        )
    assert response.status_code == 200
    coverage = response.get_json()["timeline_coverage"]
    assert coverage["complete"] is True
    assert coverage["certification"] == "event_order_certified"
    assert coverage["coarse_sources"] == []
    assert source in coverage["exact_sources"]


def test_calculate_api_soraka_exposes_exact_delayed_equinox_receipt():
    app.config["RATE_LIMIT_ENABLED"] = False
    with app.test_client() as client:
        response = client.post(
            "/api/calculate",
            json={
                "champion": "Soraka",
                "level": 18,
                "fight_mode": "time_based",
                "fight_duration": 8,
                "include_auto_attacks": False,
                "auto_attack_uptime": 0,
            },
        )
    assert response.status_code == 200
    payload = response.get_json()
    coverage = payload["timeline_coverage"]
    assert coverage["certification"] == "event_order_certified"
    assert coverage["complete"] is True
    assert "E" in coverage["exact_sources"]


#: The four modules whose persistent state once withheld every timed window.
#: Each now models its own mechanic on the shared timeline — Denting Blows on
#: the merged stream, Plasma across the window, Defile until mana runs dry,
#: Worked Ground between casts — so the window they refused is the window they
#: serve.  Each mechanic's own behaviour is pinned in its champion test file;
#: what belongs here is that no fight mode is refused and no source is coarse.
FORMERLY_ONE_ROTATION_ONLY = ("Vi", "Kai'Sa", "Karthus", "Taliyah")


@pytest.mark.parametrize("champion", FORMERLY_ONE_ROTATION_ONLY)
def test_persistent_state_champions_validate_for_every_fight_window(champion):
    _timed_params().validate_for_champion(champion, 18)


@pytest.mark.parametrize("champion", FORMERLY_ONE_ROTATION_ONLY)
def test_calculate_api_serves_persistent_state_champions_in_timed_windows(champion):
    app.config["RATE_LIMIT_ENABLED"] = False
    with app.test_client() as client:
        response = client.post(
            "/api/calculate",
            json={"champion": champion, "level": 18, "fight_mode": "time_based"},
        )
    assert response.status_code == 200
    coverage = response.get_json()["timeline_coverage"]
    assert coverage["complete"] is True
    assert coverage["coarse_sources"] == []


@pytest.mark.parametrize("champion", FORMERLY_ONE_ROTATION_ONLY)
def test_optimize_api_matches_calculate_for_persistent_state_champions(champion):
    app.config["RATE_LIMIT_ENABLED"] = False
    with app.test_client() as client:
        response = client.post(
            "/api/optimize",
            json={
                "champion": champion,
                "level": 18,
                "fight_mode": "time_based",
                "max_legendary_slots": 1,
            },
        )
    assert response.status_code == 200
    assert response.get_json()["items"] is not None


def test_optimize_api_certifies_tahm_kench_event_order():
    """Tahm's reviewed packet can participate in an event-ordered search."""
    app.config["RATE_LIMIT_ENABLED"] = False
    with app.test_client() as client:
        response = client.post(
            "/api/optimize",
            json={
                "champion": "Tahm Kench",
                "level": 18,
                "fight_mode": "time_based",
                "max_legendary_slots": 1,
            },
        )
    assert response.status_code == 200
    body = response.get_json()
    assert body["timeline_coverage"]["complete"] is True
    assert body["timeline_coverage"]["coarse_sources"] == []
    assert body["ranked_builds"]


def test_optimize_api_certifies_qiyana_multistage_ultimate():
    """Qiyana's reviewed multi-stage R can participate in a build search."""
    app.config["RATE_LIMIT_ENABLED"] = False
    with app.test_client() as client:
        response = client.post(
            "/api/optimize",
            json={
                "champion": "Qiyana",
                "level": 18,
                "fight_mode": "time_based",
                "max_legendary_slots": 1,
            },
        )
    assert response.status_code == 200
    body = response.get_json()
    assert body["timeline_coverage"]["complete"] is True
    assert body["timeline_coverage"]["coarse_sources"] == []
    assert body["ranked_builds"]


def test_optimize_api_certifies_shyvana_form_packets():
    """Shyvana's reviewed form-dependent packets can be searched."""
    app.config["RATE_LIMIT_ENABLED"] = False
    with app.test_client() as client:
        response = client.post(
            "/api/optimize",
            json={
                "champion": "Shyvana",
                "level": 18,
                "fight_mode": "time_based",
                "max_legendary_slots": 1,
            },
        )
    assert response.status_code == 200
    body = response.get_json()
    assert body["timeline_coverage"]["complete"] is True
    assert body["timeline_coverage"]["coarse_sources"] == []
    assert body["ranked_builds"]


def test_optimize_api_labels_partial_candidate_search_without_claiming_certified_best():
    """A complete winner cannot certify an exhaustive search with coarse candidates.

    Ahri's W and R carry no reviewed control kind (docs/coverage-residue.json),
    so her Fimbulwinter candidates are honestly coarse in every window.
    """
    app.config["RATE_LIMIT_ENABLED"] = False
    with app.test_client() as client:
        response = client.post(
            "/api/optimize",
            json={
                "champion": "Ahri",
                "level": 18,
                "fight_mode": "time_based",
                "max_legendary_slots": 1,
            },
        )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["timeline_coverage"]["complete"] is True
    assert payload["is_certified_best"] is False
    # MERGE: the label is coupled to search coverage (optimizer.py) - an
    # item-scope gap is only reported when the SEARCH covered everything.
    # These two searches carry coarse candidate evaluations (7 here), so
    # the partial label is the certification, and it is the same fact the
    # partial_evaluations assertion below states.
    assert payload["selection_certification"] == "partial_or_unexhaustive"
    # Coarse candidate evaluations make the SEARCH partial, which is the
    # certification the coverage block reports.
    assert (
        payload["search_timeline_coverage"]["certification"]
        == "partial_candidate_event_order"
    )
    assert payload["search_timeline_coverage"]["partial_evaluations"] > 0
    assert payload["candidate_coverage"]["complete"] is True
    assert payload["candidate_coverage"]["withheld_count"] == 0


def test_optimize_api_darius_returns_visible_event_certified_build():
    """Browser-facing Darius optimization succeeds without overclaiming search."""
    app.config["RATE_LIMIT_ENABLED"] = False
    with app.test_client() as client:
        response = client.post(
            "/api/optimize",
            json={
                "champion": "Darius",
                "level": 18,
                "fight_mode": "time_based",
                "max_legendary_slots": 1,
            },
        )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["total_damage"] > 0
    assert payload["ranked_builds"]
    assert payload["timeline_coverage"]["certification"] == "event_order_certified"
    assert payload["timeline_coverage"]["coarse_sources"] == []
    assert payload["is_certified_best"] is False
    # MERGE: the label is coupled to search coverage (optimizer.py) - an
    # item-scope gap is only reported when the SEARCH covered everything.
    # These two searches carry coarse candidate evaluations (7 here), so
    # the partial label is the certification, and it is the same fact the
    # partial_evaluations assertion below states.
    assert payload["selection_certification"] == "partial_or_unexhaustive"


def test_optimize_api_certifies_ziggs_minefield_cadence():
    """Ziggs's reviewed minefield cadence can participate in a build search."""
    app.config["RATE_LIMIT_ENABLED"] = False
    with app.test_client() as client:
        response = client.post(
            "/api/optimize",
            json={
                "champion": "Ziggs",
                "level": 18,
                "fight_mode": "time_based",
                "max_legendary_slots": 1,
            },
        )
    assert response.status_code == 200
    body = response.get_json()
    assert body["timeline_coverage"]["complete"] is True
    assert body["timeline_coverage"]["coarse_sources"] == []
    assert body["ranked_builds"]


@pytest.mark.parametrize("champion", FORMERLY_ONE_ROTATION_ONLY)
def test_persistent_state_champions_publish_every_fight_mode(champion):
    assert get_supported_fight_modes(champion) is None
    assert get_unsupported_fight_mode_reason(champion) is None


def test_shyvana_multi_form_e_and_w_have_certified_sources():
    result = run_fight(_load_public_champion("Shyvana"), 18, [], _timed_params())
    assert result["timeline_coverage"]["complete"] is True
    assert {"E", "W"}.issubset(set(result["timeline_coverage"]["exact_sources"]))


@pytest.mark.parametrize("champion", ("Akshan", "Braum", "Diana", "Ziggs"))
def test_complete_receipts_use_the_public_certification_label(champion):
    result = run_fight(_load_public_champion(champion), 18, [], _timed_params())
    coverage = result["timeline_coverage"]
    assert coverage["complete"] is True
    assert coverage["certification"] == "event_order_certified"
    assert coverage["coarse_sources"] == []


@pytest.mark.parametrize("champion", ("Bel'Veth", "Wukong", "Ornn"))
def test_reviewed_receipts_claim_public_exact_certification(champion):
    coverage = run_fight(_load_public_champion(champion), 18, [], _timed_params())[
        "timeline_coverage"
    ]
    assert coverage["complete"] is True
    assert coverage["certification"] == "event_order_certified"
    assert coverage["coarse_sources"] == []


def test_garen_demacian_justice_is_a_single_dynamic_health_hit():
    result = run_fight(_load_public_champion("Garen"), 18, [], _timed_params())
    assert result["timeline_coverage"]["complete"] is True
    ultimate = result["breakdown"]["R"]
    assert len(ultimate["damage_events"]) == 1
    assert ultimate["damage_events"][0]["event_precision"] == "exact"


def test_poppy_hammer_shock_exports_both_authored_hits():
    # The certified fact is the pair: every cast authors its impact and the
    # sourced 1.0s aftershock. How many pairs fit the window is the
    # cooldown's business, so only the first cast's absolute time is pinned.
    result = run_fight(_load_public_champion("Poppy"), 18, [], _timed_params())
    assert result["timeline_coverage"]["complete"] is True
    hammer_shock = result["breakdown"]["Q"]
    times = [round(event["time"], 2) for event in hammer_shock["damage_events"]]
    assert times[0] == 0.0
    assert len(times) % 2 == 0
    assert [second - first for first, second in zip(times[::2], times[1::2])] == [
        pytest.approx(1.0)
    ] * (len(times) // 2)
    assert sum(
        event["damage"] for event in hammer_shock["damage_events"]
    ) == pytest.approx(hammer_shock["total_damage"])


def test_brand_pyroclasm_exports_the_sourced_bounce_clock():
    # F2: Brand's optimal rotation opens Q -> R, so Pyroclasm now casts
    # right after Q (t=0.25) instead of after the old fixed Q,W,E order
    # (t=0.75). The sourced bounce CLOCK (0.15s between bounces) is what
    # this test certifies; the absolute times follow the rotation.
    result = run_fight(_load_public_champion("Brand"), 18, [], _timed_params())
    assert result["timeline_coverage"]["complete"] is True
    pyroclasm = result["breakdown"]["R"]
    assert [round(event["time"], 2) for event in pyroclasm["damage_events"]] == [
        0.25,
        0.4,
        0.55,
    ]
    assert sum(
        event["damage"] for event in pyroclasm["damage_events"]
    ) == pytest.approx(pyroclasm["total_damage"])


def test_aurora_twofold_hex_exports_the_recast_delay():
    result = run_fight(_load_public_champion("Aurora"), 18, [], _timed_params())
    assert result["timeline_coverage"]["complete"] is True
    twofold_hex = result["breakdown"]["Q"]
    assert [round(event["time"], 2) for event in twofold_hex["damage_events"]] == [
        0.0,
        0.1,
        7.25,
        7.35,
    ]
    assert sum(
        event["damage"] for event in twofold_hex["damage_events"]
    ) == pytest.approx(twofold_hex["total_damage"])


def test_aurora_spirit_abjuration_on_hit_receipts_are_chronological():
    result = run_fight(_load_public_champion("Aurora"), 18, [], _timed_params())
    passive = result["breakdown"]["on_hit_ability_passive"]
    events = passive["damage_events"]
    times = [float(event["time"]) for event in events]
    assert times == sorted(times)
    assert sum(event["damage"] for event in events) == pytest.approx(
        passive["total_damage"]
    )


def test_warwick_jaws_of_the_beast_uses_the_sourced_bite_delay():
    # The bite delay is the certified fact; the recast lands one cached
    # cooldown later, read at the rank being cast rather than restated here.
    result = run_fight(_load_public_champion("Warwick"), 18, [], _timed_params())
    jaws = result["breakdown"]["Q"]
    cooldown = extract_cooldown(
        _load_public_champion("Warwick")["abilities"]["Q"][0], 5
    )
    assert [round(event["time"], 3) for event in jaws["damage_events"]] == [
        0.264,
        round(0.264 + cooldown, 3),
    ]
    assert sum(event["damage"] for event in jaws["damage_events"]) == pytest.approx(
        jaws["total_damage"]
    )


def test_viego_q_metadata_receipts_disclose_unmodeled_mark_consumption():
    assumptions = get_champion_options_meta("Viego")["assumptions"]
    assert any(
        "mark-consuming second strike" in assumption
        and "prior damaging ability" in assumption
        and "next marked basic attack" in assumption
        for assumption in assumptions
    )


def test_warwick_q_metadata_receipts_disclose_bite_delay():
    assumptions = get_champion_options_meta("Warwick")["assumptions"]
    assert any("0.264-second bite delay" in assumption for assumption in assumptions)


def test_poppy_q_metadata_receipts_disclose_hammer_shock_rupture():
    assumptions = get_champion_options_meta("Poppy")["assumptions"]
    assert any(
        "Hammer Shock field ruptures 1 second after impact" in assumption
        for assumption in assumptions
    )


def test_hwei_devastating_fire_uses_the_sourced_cast_boundary():
    result = run_fight(_load_public_champion("Hwei"), 18, [], _timed_params())
    fire = result["breakdown"]["Q"]
    # F3 derives R first (Q is a missing-health execute, cast after R's
    # burst), so Q's sourced cast boundary sits at 0.5s behind R's 0.25s
    # cast time instead of opening the rotation at 0.25s.
    assert [round(event["time"], 2) for event in fire["damage_events"]] == [0.5]
    assert sum(event["damage"] for event in fire["damage_events"]) == pytest.approx(
        fire["total_damage"]
    )


@pytest.mark.parametrize(
    "champion",
    (
        "Gragas",
        "Jax",
        "Jinx",
        "KogMaw",
        "Singed",
        "Sion",
        "Volibear",
        "Xin Zhao",
        "Yone",
        "Rek'Sai",
    ),
)
def test_single_hit_dynamic_packets_are_cast_boundary_certified(champion):
    result = run_fight(_load_public_champion(champion), 18, [], _timed_params())
    assert result["timeline_coverage"]["complete"] is True
