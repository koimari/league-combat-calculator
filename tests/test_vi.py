"""Reference, ordering, multi-target, and timed-mode tests for Vi."""

import pytest

from src import app as app_module
from src.calculator.calculate import calculate_payload
from src.calculator.champions import (
    get_champion_cast_order,
    get_champion_options_meta,
    parse_champion_abilities,
    vi,
)
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.pipeline import FightParams, run_fight
from tests import cc_review


def _timed_payload(duration, *, include_autos=True, champion_options=None):
    """Timed-mode request through the real public pipeline."""
    data = {
        "champion": "Vi",
        "level": 18,
        "items": [],
        "fight_mode": "timed",
        "include_auto_attacks": include_autos,
        "fight_duration": duration,
    }
    if champion_options is not None:
        data["champion_options"] = champion_options
    return calculate_payload(data)


def _auto_only_payload(duration):
    """Autos-only request through the real public pipeline."""
    return calculate_payload(
        {
            "champion": "Vi",
            "level": 18,
            "items": [],
            "fight_mode": "auto_only",
            "auto_attacks_only": True,
            "include_auto_attacks": True,
            "fight_duration": duration,
        }
    )


RANKS = {"Q": 5, "W": 3, "E": 3, "R": 2}


def _stats() -> dict[str, float]:
    return {
        "armor_penetration_bonus_percent": 0.0,
        "move_speed": 0.0,
        "omnivamp_percent": 0.0,
        "resource_regen_per_second": 0.0,
        "ultimate_haste": 0.0,
        "health": 2000.0,
        "bonus_health": 0.0,
        "attack_damage": 200.0,
        "base_attack_damage": 100.0,
        "bonus_attack_damage": 100.0,
        "ability_power": 0.0,
        "armor": 50.0,
        "magic_resistance": 50.0,
        "attack_speed": 1.0,
        "attack_speed_ratio": 0.644,
        "critical_strike_chance": 0.0,
        "magic_penetration_flat": 0.0,
        "magic_penetration_percent": 0.0,
        "flat_armor_penetration": 0.0,
        "armor_penetration_percent": 0.0,
        "lethality": 0.0,
        "ability_haste": 0.0,
        "max_mana": 2000.0,
        "bonus_mana": 0.0,
        "basic_ability_haste": 0.0,
        "is_melee": True,
        "level": 18,
    }


def _abilities(vi_data, *, starting_stacks=0, target_index=0, charge=1.25):
    stats = _stats()
    return stats, parse_champion_abilities(
        vi_data,
        18,
        0.0,
        ability_ranks=RANKS,
        champion_stats=stats,
        target_stats={
            "target_max_health": 2500.0,
            "target_current_health": 2500.0,
            "roster_target_index": float(target_index),
            "roster_target_count": 2.0,
        },
        champion_options={
            "q_charge_seconds": charge,
            "q_dash_distance": 725.0,
            "denting_blows_starting_stacks": starting_stacks,
            "e_attack_delay": 0.25,
            "r_start_distance": 800.0,
        },
    )


def _fight(stats, abilities):
    return calculate_fight_damage(
        stats,
        abilities,
        [],
        FightConfig(
            target_health=2500.0,
            target_armor=100.0,
            target_magic_resistance=100.0,
            fight_duration_seconds=5.0,
            one_rotation=True,
            deterministic=True,
            enforce_resource_limits=True,
            cast_order=get_champion_cast_order("Vi"),
        ),
    )


def test_reference_formulas_and_full_charge(vi_data):
    stats, abilities = _abilities(vi_data, starting_stacks=2)

    # Q5 minimum is 120 + 60% bonus AD = 180; full charge multiplies
    # the complete minimum formula by 2.5 -> 450.
    assert abilities["Q"]["total_raw"] == pytest.approx(450.0)
    # E3 primary stores only its rider. The forced basic swing supplies
    # the other 100% AD: 50 + 10% AD = 70 rider, 270 modified attack.
    assert abilities["E"]["total_raw"] == pytest.approx(70.0)
    assert abilities["R"]["total_raw"] == pytest.approx(340.0)
    assert abilities["Q"]["parts"][0].time_offset == pytest.approx(
        1.25 + 725.0 / 1540.0
    )
    assert stats["attack_damage"] == 200.0


def test_q_charge_scales_continuously_and_clamps_range(vi_data):
    _, minimum = _abilities(vi_data, charge=0.0)
    _, half = _abilities(vi_data, charge=0.625)
    _, maximum = _abilities(vi_data, charge=1.25)

    assert minimum["Q"]["total_raw"] == pytest.approx(180.0)
    assert half["Q"]["total_raw"] == pytest.approx(315.0)
    assert maximum["Q"]["total_raw"] == pytest.approx(450.0)
    # At zero charge the requested 725 distance is capped to 250.
    assert minimum["Q"]["parts"][0].time_offset == pytest.approx(250 / 1450)


def test_q_triggered_w_uses_old_armor_then_shreds_later_hits(vi_data):
    stats, abilities = _abilities(vi_data, starting_stacks=2)
    result = _fight(stats, abilities)

    # At 100 armor: Q 225, W 118.75. W then reduces armor to 80, so
    # E is 270/1.8=150 and R is 340/1.8=188.8889.
    assert result["breakdown"]["Q"]["total_damage"] == pytest.approx(225.0)
    assert result["breakdown"]["passive_proc_W"]["total_damage"] == pytest.approx(
        118.75
    )
    assert result["breakdown"]["E"]["total_damage"] == pytest.approx(150.0)
    assert result["breakdown"]["R"]["total_damage"] == pytest.approx(188.888889)
    assert result["total_damage"] == pytest.approx(682.638889)
    assert result["effective_armor"] == pytest.approx(80.0)


def test_e_triggered_w_shreds_only_r(vi_data):
    stats, abilities = _abilities(vi_data, starting_stacks=1)
    result = _fight(stats, abilities)

    assert result["breakdown"]["Q"]["total_damage"] == pytest.approx(225.0)
    assert result["breakdown"]["E"]["total_damage"] == pytest.approx(135.0)
    assert result["breakdown"]["passive_proc_W"]["total_damage"] == pytest.approx(
        118.75
    )
    assert result["breakdown"]["R"]["total_damage"] == pytest.approx(188.888889)
    assert result["total_damage"] == pytest.approx(667.638889)
    assert result["effective_armor"] == pytest.approx(80.0)
    assert result["breakdown"]["passive_proc_W"]["damage_events"][0][
        "time"
    ] == pytest.approx(result["breakdown"]["E"]["damage_events"][0]["time"])


def test_incomplete_w_cycle_deals_no_fractional_proc(vi_data):
    stats, abilities = _abilities(vi_data, starting_stacks=0)
    result = _fight(stats, abilities)

    assert "passive_proc_W" not in result["breakdown"]
    assert result["total_damage"] == pytest.approx(530.0)
    assert result["effective_armor"] == pytest.approx(100.0)


def test_secondary_e_is_cone_damage_without_attack_or_w_stack(vi_data):
    stats, abilities = _abilities(vi_data, starting_stacks=1, target_index=1)
    result = _fight(stats, abilities)

    assert abilities["E"].get("empowers_next_auto") is None
    assert abilities["E"].get("applies_item_on_hits") is None
    assert "secondary cone target" in abilities["E"]["detail"]
    assert "passive_proc_W" not in result["breakdown"]
    assert result["breakdown"]["E"]["total_damage"] == pytest.approx(135.0)
    assert result["total_damage"] == pytest.approx(530.0)


def test_rotation_is_event_order_certified_and_resource_legal(vi_data):
    stats, abilities = _abilities(vi_data, starting_stacks=2)
    result = _fight(stats, abilities)

    assert result["resource_spent"] == pytest.approx(228.0)
    assert result["resource_remaining"] == pytest.approx(1772.0)
    assert result["timeline_coverage"]["complete"] is True
    assert result["timeline_coverage"]["certification"] == "event_order_certified"
    assert result["timeline_coverage"]["exact_sources"] == [
        "E",
        "Q",
        "R",
        "passive_proc_W",
    ]


def test_w_max_health_scaling_is_repriced_for_protoplasm(vi_data):
    params = FightParams(
        target_health=500.0,
        target_armor=0.0,
        target_magic_resistance=0.0,
        fight_duration_seconds=5.0,
        one_rotation=True,
        ability_ranks={"Q": 5, "W": 1, "E": 3, "R": 1},
        champion_options={"denting_blows_starting_stacks": 2},
        target_threshold_health_bonus=200.0,
        target_threshold_health_heal=300.0,
        target_threshold_health_ratio=0.3,
        target_threshold_health_duration=5.0,
    )

    result = run_fight(vi_data, 10, [], params)

    assert result["threshold_health_triggered"] is True
    assert result["target_effective_max_health"] == pytest.approx(700.0)
    assert result["target_healing_received"] > 0.0
    # The target-side heal authors its cadence now, so the fight stays
    # certified; the reprice above is what the lifeline is measured by.
    assert result["timeline_coverage"]["complete"] is True
    assert (
        "target_Protoplasm Harness" not in result["timeline_coverage"]["coarse_sources"]
    )


def test_timed_w_proc_count_grows_with_duration_and_ambient_autos():
    """W procs ride the merged auto+Q stream, so a longer fight procs more.

    Engine output (level 18, no items, uptime 0.8): D=6 procs once at
    1.721s (autos at 0/1.449s plus the Q hit complete the third stack);
    D=18 procs five times at 1.721 / 5.794 / 8.971 / 13.037 / 16.221s
    (W row total 213.6 vs 42.9), interleaved with 12 ambient autos and
    Q casts at 0 / 7.25 / 14.5s.
    """
    short = _timed_payload(6)
    long = _timed_payload(18)

    short_row = short["breakdown"]["W"]
    long_row = long["breakdown"]["W"]
    assert short_row["count"] == 1
    assert long_row["count"] == 5
    assert long_row["count"] > short_row["count"]
    # Each proc is one authored event in the fight's shared ordered ledger,
    # interleaved with the auto/Q/E stream that built its stacks.
    long_procs = [event for event in long["damage_events"] if event["source"] == "W"]
    assert len(long_procs) == long_row["count"]
    times = [event["time"] for event in long_procs]
    assert times == sorted(times)
    assert long_row["total_damage"] > short_row["total_damage"]


def test_auto_only_w_procs_count_only_the_ambient_swings():
    """auto_only casts nothing, so Q must not feed the Denting Blows walk.

    Level 18, no items, 18s: the engine swings 12 ambient autos and casts
    zero abilities, so every third swing procs — 4 procs, not the merged
    stream's 5 (``test_timed_w_proc_count_grows_with_duration_and_ambient_autos``).
    """
    payload = _auto_only_payload(18)

    assert payload["breakdown"]["auto_attacks"]["count"] == 12
    for slot in ("Q", "E", "R"):
        assert payload["breakdown"][slot]["casts"] == 0
    row = payload["breakdown"]["W"]
    assert row["count"] == 4
    assert row["total_damage"] == pytest.approx(160.0)


def test_auto_only_w_is_silent_without_an_auto_stream():
    """No autos and no casts leaves nothing to apply a stack."""
    payload = calculate_payload(
        {
            "champion": "Vi",
            "level": 18,
            "items": [],
            "fight_mode": "auto_only",
            "auto_attacks_only": True,
            "auto_attack_uptime": 0,
            "auto_attack_uptime_mode": "explicit",
            "fight_duration": 18,
        }
    )

    assert "W" not in payload["breakdown"]


def test_timed_w_stacks_expire_without_a_carrier_stream():
    """With no ambient autos, Q/E hits alone sit >4s apart: stacks expire
    between applications and Denting Blows never completes a cycle."""
    payload = _timed_payload(18, include_autos=False)

    assert "W" not in payload["breakdown"]
    assert payload["total_damage"] > 0


def test_timed_starting_stacks_seed_the_counter():
    """`denting_blows_starting_stacks` seeds the walk: the first proc lands
    earlier and the window fits at least as many procs."""
    unseeded = _timed_payload(12)
    seeded = _timed_payload(12, champion_options={"denting_blows_starting_stacks": 2})

    unseeded_row = unseeded["breakdown"]["W"]
    seeded_row = seeded["breakdown"]["W"]
    assert seeded_row["count"] >= unseeded_row["count"]
    first_seeded = next(
        event["time"] for event in seeded["damage_events"] if event["source"] == "W"
    )
    first_unseeded = next(
        event["time"] for event in unseeded["damage_events"] if event["source"] == "W"
    )
    assert first_seeded < first_unseeded


def test_timed_shred_falls_back_to_e_when_q_is_unranked():
    """With Q unranked the walk still procs (autos alone reach the third
    stack), and E carries the shred windows: E recharges at 8s (rank 5),
    so casts at 0 / 8s cover 4 + 4 = 8s of a 12s fight and the 20% shred
    weights to 13.333%, pricing 100 armor as 86.7."""
    payload = calculate_payload(
        {
            "champion": "Vi",
            "level": 18,
            "items": [],
            "fight_mode": "timed",
            "include_auto_attacks": True,
            "fight_duration": 12,
            "ability_ranks": {"Q": 0, "W": 5, "E": 5, "R": 3},
            "target_health": 2500,
            "target_armor": 100,
        }
    )

    assert "Q" not in payload["breakdown"]
    assert payload["breakdown"]["W"]["count"] == 2
    assert payload["effective_armor"] == pytest.approx(
        round(100.0 - 20.0 * (8.0 / 12.0), 1)
    )


def test_custom_order_requests_still_fail_closed():
    reordered = app_module.app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Vi",
            "level": 10,
            "fight_mode": "one_rotation",
            "cast_order": ["E", "Q", "W", "R"],
        },
    )

    assert reordered.status_code == 400
    assert "certified Q -> E -> R sequence" in reordered.get_json()["error"]


def test_timed_timeline_coverage_is_complete_with_no_coarse_sources():
    """The unlocked timed model authors or cast-orders every active row."""
    payload = _timed_payload(18)

    coverage = payload["timeline_coverage"]
    assert coverage["complete"] is True
    assert coverage["coarse_sources"] == []
    assert coverage["certification"] == "event_order_certified"
    assert "W" in coverage["exact_sources"]


def test_timed_w_procs_shred_armor_for_later_hits():
    """The walk's procs carry the 20% shred: 4s windows at Q's cast times
    (0 / 7.25 / 14.5s over an 18s fight; the last clips at the fight end,
    so 4 + 4 + 3.5 = 11.5s covered) weight the shred to 20% x 11.5/18 =
    12.778%, so 100 armor prices as 87.222 (87.2 in the rounded payload)."""
    payload = calculate_payload(
        {
            "champion": "Vi",
            "level": 18,
            "items": [],
            "fight_mode": "timed",
            "include_auto_attacks": True,
            "fight_duration": 18,
            "target_health": 2500,
            "target_armor": 100,
        }
    )

    assert "W" in payload["breakdown"]
    assert payload["effective_armor"] == pytest.approx(
        round(100.0 - 20.0 * (11.5 / 18.0), 1)
    )


def test_comparison_curve_returns_populated_points():
    response = app_module.app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Vi",
            "level": 10,
            "fight_mode": "one_rotation",
            "include_crossover": True,
            "ability_ranks": {"Q": 5, "W": 1, "E": 3, "R": 1},
            "champion_options": {"denting_blows_starting_stacks": 2},
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["total_damage"] > 0
    assert payload["comparison_curve_status"]["available"] is True
    curve = payload["comparison_curve"]
    assert len(curve) == 6
    assert all(point["total_damage"] > 0 for point in curve)
    assert curve[-1]["total_damage"] > curve[0]["total_damage"]


def test_public_bis_returns_two_distinct_event_ordered_builds():
    response = app_module.app.test_client().post(
        "/api/optimize",
        json={
            "champion": "Vi",
            "level": 10,
            "fight_mode": "one_rotation",
            "target_health": 2500,
            "target_armor": 100,
            "target_mr": 50,
            "max_legendary_slots": 1,
            "ability_ranks": {"Q": 5, "W": 1, "E": 3, "R": 1},
            "champion_options": {"denting_blows_starting_stacks": 2},
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    ranked = payload["ranked_builds"]
    assert len(ranked) == 2
    assert (ranked[0]["items"], ranked[0]["boots"]) != (
        ranked[1]["items"],
        ranked[1]["boots"],
    )
    assert all(build["timeline_coverage"]["complete"] for build in ranked)
    # Vi's kit is reviewed slot by slot, and E's forced attack carries its
    # declared marker without an auto stream, so no one-rotation candidate
    # is withheld and the exhaustive opening is certified best in slot.
    assert payload["timeline_withheld_evaluations"] == 0
    assert payload["is_certified_best"] is True


def test_sources_and_options_are_public_revision_receipts():
    meta = get_champion_options_meta("Vi")

    assert len(meta["options"]) == 5
    assert {row["revision_id"] for row in meta["sources"]} == {
        3986701,
        3921391,
        3932548,
        3986710,
        4004943,
    }
    assert all(
        row["url"].startswith("https://wiki.leagueoflegends.com/")
        for row in meta["sources"]
    )


class TestReviewedCrowdControl:
    """Vi's whole kit is reviewed: Q knocks back, R knocks up, E does neither.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    """

    def test_module_cc_is_the_declaration_the_parser_wired(self):
        assert vi.MODULE_CC == {
            "Q": "knockback",
            "E": "none",
            "R": "knockup",
            "W": "none",
        }
        assert vi.parse_abilities.cc_kinds == vi.MODULE_CC

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Vi")
        q_text = cc_review.slot_text(data, "Q")
        assert "she stops upon hitting an enemy champion, knocking them back" in q_text
        assert "pull all non-champions hit towards her" in q_text
        assert "knocking them up for 1.3 seconds" in cc_review.slot_text(data, "R")
        assert cc_review.control_words(cc_review.slot_text(data, "E")) == []

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Vi") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Vi")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
