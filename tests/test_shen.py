"""Reference, resource, and event-order tests for Shen's sourced module."""

import pytest

from src.app import app
from src.calculator.champions import (
    get_champion_module_meta,
    parse_champion_abilities,
    shen,
)
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.pipeline import FightParams, run_fight
from src.calculator.stats import calculate_total_stats
from tests import cc_review


def _stats(shen_data, level: int = 12) -> dict:
    stats = calculate_total_stats(shen_data, level, [])
    stats.update(
        {
            "health": stats["health"] + 1000.0,
            "bonus_health": 1000.0,
            "attack_damage": 100.0,
            "base_attack_damage": 100.0,
            "bonus_attack_damage": 0.0,
            "ability_power": 100.0,
            "attack_speed": 1.0,
            "attack_speed_ratio": 1.0,
            "move_speed": 340.0,
        }
    )
    return stats


def _parse(shen_data, *, enhanced=True, hits=3):
    stats = _stats(shen_data)
    abilities = parse_champion_abilities(
        shen_data,
        12,
        100.0,
        ability_ranks={"Q": 5, "W": 1, "E": 3, "R": 2},
        champion_stats=stats,
        target_stats={
            "target_max_health": 2500.0,
            "target_current_health": 2500.0,
            "target_missing_health": 0.0,
        },
        champion_options={
            "q_spirit_blade_hit": enhanced,
            "q_attacks_landed": hits,
            "q_first_attack_delay": 0.5,
            "e_dash_distance": 600.0,
        },
    )
    return stats, abilities


def test_reference_q_and_e_formulas(shen_data):
    """Level 12, rank-5 Q, 100 AP, 1,000 bonus HP, 2,500 target HP."""
    _, enhanced = _parse(shen_data)
    _, normal = _parse(shen_data, enhanced=False)

    # Level flat 29.4118 + enhanced (7% + 2% per 100 AP) max HP.
    assert enhanced["Q"]["total_raw"] == pytest.approx(763.235294)
    # Same flat + normal (4% + 1.5% per 100 AP) max HP.
    assert normal["Q"]["total_raw"] == pytest.approx(500.735294)
    # Rank-3 E: 110 + 11% of 1,000 bonus HP.
    assert enhanced["E"]["total_raw"] == pytest.approx(220.0)


def test_options_control_hit_count_timing_and_dash(shen_data):
    _, abilities = _parse(shen_data, hits=2)

    assert abilities["Q"]["total_raw"] == pytest.approx(508.823529)
    timing = abilities["Q"]["empowers_next_auto"]["authored_timing"]
    assert timing["first_attack_delay"] == pytest.approx(0.5)
    assert timing["attack_interval"] == pytest.approx(2.0 / 3.0)
    assert abilities["E"]["parts"][0].time_offset == pytest.approx(600 / 1140)
    assert abilities["E"]["cooldown"] == pytest.approx(14 + 600 / 1140)


def test_one_rotation_forces_and_orders_q_attacks(shen_data):
    stats, abilities = _parse(shen_data)
    result = calculate_fight_damage(
        stats,
        abilities,
        [],
        FightConfig(
            target_health=2500.0,
            target_armor=0.0,
            target_magic_resistance=0.0,
            fight_duration_seconds=5.0,
            one_rotation=True,
            deterministic=True,
            enforce_resource_limits=True,
            cast_order=("E", "Q"),
        ),
    )

    # E 220 + Q bonus 763.235 + three 100-AD attacks.
    assert result["total_damage"] == pytest.approx(1283.235294)
    assert result["breakdown"]["Q"]["total_damage"] == pytest.approx(1063.235294)
    assert result["breakdown"]["Q"]["damage_by_type"] == pytest.approx(
        {"magic": 763.235294, "physical": 300.0}
    )
    q_events = result["breakdown"]["Q"]["damage_events"]
    assert len(q_events) == 6
    assert sorted({event["time"] for event in q_events}) == pytest.approx(
        [0.5, 0.5 + 2.0 / 3.0, 0.5 + 4.0 / 3.0]
    )
    assert sum(event["damage"] for event in q_events) == pytest.approx(
        result["breakdown"]["Q"]["total_damage"]
    )
    assert result["resource_spent"] == pytest.approx(250.0)
    assert result["resource_remaining"] == pytest.approx(350.0)
    assert result["timeline_coverage"]["complete"] is True


def test_public_pipeline_splits_q_swing_from_magic_rider(shen_data):
    result = run_fight(
        shen_data,
        12,
        [],
        FightParams(
            target_health=2500.0,
            target_armor=0.0,
            target_magic_resistance=0.0,
            fight_duration_seconds=5.0,
            one_rotation=True,
            ability_ranks={"Q": 5, "W": 1, "E": 3, "R": 2},
            champion_options={
                "q_spirit_blade_hit": True,
                "q_attacks_landed": 3,
                "q_first_attack_delay": 0.5,
                "e_dash_distance": 600.0,
            },
        ),
    )

    assert result["damage_by_type"]["physical"] == pytest.approx(392.0)
    assert result["damage_by_type"]["magic"] == pytest.approx(613.235294)
    assert sum(result["damage_by_type"].values()) == pytest.approx(
        result["total_damage"]
    )


def test_timed_auto_stream_certifies_q_with_an_authored_swing_ledger(shen_data):
    """Q's bonus hits carry authored swing timing; the timeline certifies.

    Five ambient swings cap Q at one cast (three empowered attacks). The
    Q row's authored events are the three magic bonus hits at the module's
    swing schedule (0.5s first-attack delay, then the enhanced 1/1.5s
    cadence); the engine additionally shows the three consumed swings on
    the Q row, so the ledger reconciles as bonus events plus the swings
    priced at the auto row's per-hit value.
    """
    stats, abilities = _parse(shen_data)
    result = calculate_fight_damage(
        stats,
        abilities,
        [],
        FightConfig(
            target_health=2500.0,
            target_armor=0.0,
            target_magic_resistance=0.0,
            fight_duration_seconds=5.0,
            auto_attack_uptime=1.0,
            one_rotation=False,
            deterministic=True,
            cast_order=("E", "Q"),
        ),
    )

    coverage = result["timeline_coverage"]
    assert coverage["complete"] is True
    assert coverage["certification"] == "event_order_certified"
    assert coverage["coarse_sources"] == []
    assert "Q" in coverage["exact_sources"]

    q_row = result["breakdown"]["Q"]
    q_events = q_row["damage_events"]
    assert len(q_events) == 3 * q_row["casts"]
    assert {event["event_precision"] for event in q_events} == {"exact"}
    assert sorted(event["time"] for event in q_events) == pytest.approx(
        [0.5, 0.5 + 2.0 / 3.0, 0.5 + 4.0 / 3.0]
    )
    # Authored events are the magic bonus; the row total additionally
    # carries the consumed swings at the auto row's per-hit damage.
    auto_row = result["breakdown"]["auto_attacks"]
    swings = 3 * q_row["casts"]
    assert sum(event["damage"] for event in q_events) == pytest.approx(
        q_row["total_damage"] - swings * auto_row["damage_per_hit"]
    )
    assert sum(event["damage"] for event in q_events) == pytest.approx(
        q_row["casts"] * abilities["Q"]["total_raw"]
    )


def test_timed_payload_probe_certifies_full_timeline():
    """The campaign probe: bare-kit timed Shen has no coarse sources."""
    from src.calculator.calculate import calculate_payload

    result = calculate_payload(
        {
            "champion": "Shen",
            "level": 18,
            "items": [],
            "fight_mode": "timed",
            "include_auto_attacks": True,
        }
    )
    coverage = result["timeline_coverage"]
    assert coverage["complete"] is True
    assert coverage["coarse_sources"] == []
    assert "Q" in coverage["exact_sources"]


def test_target_max_health_change_is_repriced(shen_data):
    params = FightParams(
        target_health=500.0,
        target_armor=0.0,
        target_magic_resistance=0.0,
        fight_duration_seconds=5.0,
        one_rotation=True,
        ability_ranks={"Q": 5, "W": 1, "E": 3, "R": 2},
        champion_options={
            "q_spirit_blade_hit": True,
            "q_attacks_landed": 3,
            "q_first_attack_delay": 0.5,
            "e_dash_distance": 600.0,
        },
        target_threshold_health_bonus=200.0,
        target_threshold_health_heal=300.0,
        target_threshold_health_ratio=0.3,
        target_threshold_health_duration=5.0,
    )

    result = run_fight(shen_data, 12, [], params)

    assert result["threshold_health_triggered"] is True
    assert result["target_effective_max_health"] == pytest.approx(700.0)
    assert result["target_healing_received"] > 0.0
    # The target-side heal authors its cadence now, so the fight stays
    # certified; the reprice above is what the lifeline is measured by.
    assert result["timeline_coverage"]["complete"] is True
    assert (
        "target_Protoplasm Harness" not in result["timeline_coverage"]["coarse_sources"]
    )


class TestReviewedCrowdControl:
    """Shen's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    Both rows already carry their authored dash/swing timing, so the
    declaration rides an event the ledger can see.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Shen")
        assert shen.MODULE_CC == {"E": "taunt", "Q": "slow"}
        assert "are slowed for the next 2 seconds" in cc_review.slot_text(data, "Q")
        assert "taunting them for 1.5 seconds" in cc_review.slot_text(data, "E")

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Shen") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Shen")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


# ---------------------------------------------------------------------------
# P/W/R disposition (Shen slot-closure session, 2026-08-20)
# ---------------------------------------------------------------------------


def test_p_ki_barrier_shield_is_sourced_and_attached_to_e(shen_data):
    """P has no cast of its own; its sourced shield rides E (the first
    ability to complete in the certified E-then-Q order)."""
    _, abilities = _parse(shen_data)

    (shield,) = abilities["E"]["self_shield_events"]
    # Level 12 flat 94.24 + 13% of 1,000 bonus health.
    assert shield["amount"] == pytest.approx(224.24)
    assert shield["duration"] == pytest.approx(2.5)
    assert shield["source"] == "Ki Barrier"
    assert "Ki Barrier" in abilities["E"]["detail"]


def test_p_ki_barrier_shield_scales_with_level_and_bonus_health(shen_data):
    stats = calculate_total_stats(shen_data, 1, [])
    stats.update(
        {
            "bonus_health": 0.0,
            "attack_damage": 100.0,
            "base_attack_damage": 100.0,
            "bonus_attack_damage": 0.0,
            "ability_power": 0.0,
            "attack_speed": 1.0,
            "attack_speed_ratio": 1.0,
            "move_speed": 340.0,
        }
    )
    abilities = parse_champion_abilities(
        shen_data,
        1,
        0.0,
        ability_ranks={"Q": 0, "W": 0, "E": 1, "R": 0},
        champion_stats=stats,
        target_stats={
            "target_max_health": 2500.0,
            "target_current_health": 2500.0,
            "target_missing_health": 0.0,
        },
        champion_options={"e_dash_distance": 600.0},
    )

    (shield,) = abilities["E"]["self_shield_events"]
    # Level 1 flat base, zero bonus health.
    assert shield["amount"] == pytest.approx(47.0)


def test_w_spirits_refuge_is_explicit_zero_damage_row(shen_data):
    """W carries no damage/heal/shield leveling row; it emits an explicit
    zero-damage state row (module_helpers.no_damage), not a silent absence."""
    _, abilities = _parse(shen_data)
    entry = abilities["W"]

    assert entry["name"] == "Spirit's Refuge"
    assert entry["total_raw"] == 0.0
    assert entry["parts"] == ()
    assert "no damage" in entry["detail"].lower()
    assert "block" in entry["detail"].lower()


def test_r_stand_united_is_a_zero_damage_cast_the_scanner_prices(shen_data):
    """R is wired as a support cast: the rotation casts it and the
    ally-support scanner prices the sourced shield floor, so the slot emits
    a row that deals no damage of its own."""
    _, abilities = _parse(shen_data)

    assert "R" in abilities
    assert abilities["R"]["total_raw"] == 0.0
    assert abilities["R"]["parts"] == ()
    assert "R" in get_champion_module_meta("Shen")["slots"]
    assert shen.CAST_ORDER == ["E", "Q", "R"]


def test_module_coverage_reflects_p_w_r_dispositions():
    """P's shield rides E and is modeled; W is an atoms-confirmed
    zero-damage state row; R's sourced ally shield is priced by the
    ally-support scanner off its "Minimum Shield Strength" floor."""
    coverage = get_champion_module_meta("Shen")["coverage"]

    assert coverage == {
        "P": "modeled",
        "Q": "modeled",
        "W": "no_damage",
        "E": "modeled",
        "R": "modeled",
    }


def test_sources_are_wiki_revision_receipts():
    """The reviewed pins live in ``static/champion-source-receipts.json``
    (one home), so the module states no revision of its own.

    MERGE: main's inline ``SOURCES`` list pinned Ki Barrier (3985839),
    Spirit's Refuge (3977238) and Stand United (4004939) beside Twilight
    Assault (4008038) and Shadow Dash (4007754).  All five now live in the
    receipt asset — every priced slot has its own revision receipt — so
    the set is pinned exactly rather than as a lower bound.
    """
    meta = get_champion_module_meta("Shen")

    assert {row["revision_id"] for row in meta["sources"]} == {
        3985839,  # Ki Barrier (P)
        4008038,  # Twilight Assault (Q)
        3977238,  # Spirit's Refuge (W)
        4007754,  # Shadow Dash (E)
        4004939,  # Stand United (R)
    }
    assert all(
        row["url"].startswith("https://wiki.leagueoflegends.com/")
        for row in meta["sources"]
    )


def _post_shen_fight(*, duration=6.0):
    response = app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Shen",
            "level": 12,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": duration,
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
            "ability_ranks": {"Q": 5, "W": 1, "E": 3, "R": 2},
            "champion_options": {
                "q_spirit_blade_hit": True,
                "q_attacks_landed": 3,
                "q_first_attack_delay": 0.5,
                "e_dash_distance": 600.0,
            },
            "enemies": [{"champion": "Aatrox", "level": 12, "items": []}],
        },
    )
    assert response.status_code == 200, response.get_data(as_text=True)[:500]
    return response.get_json()["combat"]


def test_api_ki_barrier_shield_absorbs_through_the_participant_ledger():
    """Live end-to-end check: the module-authored payload on E resolves
    through the shared self-shield ledger into a real absorbed shield,
    the same path exercised for Ambessa/Blitzcrank (E8c)."""
    combat = _post_shen_fight()

    rows = [
        event
        for event in combat.get("support_events", [])
        if event.get("kind") == "shield" and event.get("source") == "Ki Barrier"
    ]
    assert len(rows) == 1
    main = next(
        row for row in combat["participants"] if row["participant_id"] == "main"
    )["survival"]
    assert main["support_shield_received"] == pytest.approx(rows[0]["amount"], abs=0.06)
    assert main["shield_absorbed"] == pytest.approx(rows[0]["amount"], abs=0.06)
