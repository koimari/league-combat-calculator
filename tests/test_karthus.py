"""Revision-backed formulas, resources, and target rules for Karthus."""

import pytest

from src.calculator.calculate import calculate_payload
from src.calculator.champions import (
    get_champion_cast_order,
    get_champion_options_meta,
    karthus,
    parse_champion_abilities,
)
from src.calculator.stats import calculate_total_stats
from tests import cc_review
from tests.ability_math import parts_raw_total

RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}


def _parse(
    karthus_data,
    parse_at,
    *,
    wall=True,
    isolated=True,
    ticks=5,
    roster_count=1,
):
    return parse_at(
        karthus_data,
        18,
        ap=200,
        ability_ranks=RANKS,
        target_stats={
            "target_max_health": 2500.0,
            "roster_target_count": float(roster_count),
        },
        champion_options={
            "wall_contact": wall,
            "q_isolated": isolated,
            "e_ticks": ticks,
        },
    )


def test_alive_rotation_uses_isolated_q_selected_e_ticks_and_channelled_r(
    karthus_data, parse_at
):
    _, abilities = _parse(karthus_data, parse_at)

    # Q5 isolated @ 200 AP: 232 + 140 = 372.
    assert parts_raw_total(abilities["Q"]["parts"], "magic") == pytest.approx(372.0)
    # E5 per tick @ 200 AP: 27.5 + 10 = 37.5; five ticks.
    assert parts_raw_total(abilities["E"]["parts"], "magic") == pytest.approx(187.5)
    assert len(abilities["E"]["parts"]) == 5
    # R3 @ 200 AP: 500 + 140 = 640.
    assert parts_raw_total(abilities["R"]["parts"], "magic") == pytest.approx(640.0)
    assert abilities["R"]["parts"][0].time_offset == pytest.approx(3.75)


def test_q_isolation_fails_closed_for_a_multi_target_hit(karthus_data, parse_at):
    _, single = _parse(karthus_data, parse_at, roster_count=1)
    _, multiple = _parse(karthus_data, parse_at, roster_count=2)
    _, explicit_shared = _parse(karthus_data, parse_at, isolated=False)

    assert parts_raw_total(single["Q"]["parts"]) == pytest.approx(372.0)
    assert parts_raw_total(multiple["Q"]["parts"]) == pytest.approx(186.0)
    assert parts_raw_total(explicit_shared["Q"]["parts"]) == pytest.approx(186.0)
    assert "multi-target" in multiple["Q"]["detail"]


def test_wall_reduction_applies_before_every_damage_source(
    karthus_data, parse_at, fight
):
    stats, with_wall = _parse(karthus_data, parse_at, wall=True)
    _, without_wall = _parse(karthus_data, parse_at, wall=False)
    config = {
        "target_magic_resistance": 100,
        "cast_order": get_champion_cast_order("Karthus"),
        "enforce_resource_limits": True,
    }
    reduced = fight(stats, with_wall, **config)
    normal = fight(stats, without_wall, **config)

    assert reduced["effective_mr"] == pytest.approx(75.0)
    assert normal["effective_mr"] == pytest.approx(100.0)
    assert reduced["total_damage"] == pytest.approx(1199.5 / 1.75)
    assert normal["total_damage"] == pytest.approx(1199.5 / 2.0)


def test_defile_tick_count_controls_damage_time_and_mana(karthus_data, parse_at):
    _, zero = _parse(karthus_data, parse_at, ticks=0)
    _, five = _parse(karthus_data, parse_at, ticks=5)
    _, clamped = _parse(karthus_data, parse_at, ticks=999)

    assert zero["E"]["parts"] == ()
    assert zero["E"]["resource_cost"] == 0.0
    assert five["E"]["resource_cost"] == pytest.approx(78.0)
    assert five["E"]["parts"][-1].time_offset == pytest.approx(1.5)
    assert len(clamped["E"]["parts"]) == 40


def test_public_metadata_keeps_the_certified_sequence():
    meta = get_champion_options_meta("Karthus")

    assert {option["key"] for option in meta["options"]} == {
        "wall_contact",
        "q_isolated",
        "e_ticks",
    }
    # The certified W -> Q -> E -> R sequence itself stays unreorderable.
    assert karthus.CAST_ORDER == ("W", "Q", "E", "R")
    assert karthus.CUSTOM_CAST_ORDER_UNAVAILABLE_REASON
    assert any("Death Defied" in note for note in meta["assumptions"])
    assert len(meta["sources"]) == 5


# ---------------------------------------------------------------------------
# Timed mode (campaign criterion 3): runtime probes through calculate_payload.
# ---------------------------------------------------------------------------


def _timed_payload(duration, **extra):
    """One real timed fight through the public payload path (no items)."""
    return calculate_payload(
        {
            "champion": "Karthus",
            "level": 18,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": float(duration),
            **extra,
        }
    )


def _defile_tick_count(payload):
    """Defile ticks in the public event ledger (4 per accepted pulse)."""
    return sum(1 for event in payload["damage_events"] if event["source"] == "E")


def test_defile_pulses_stop_at_mana_exhaustion():
    """Defile shuts off when the pool is dry, instead of scaling linearly.

    Level-18 Karthus, no items: mana 994 (467 + 31 x 17), regen 4.32/s
    ((8 + 0.8 x 17) per 5s).  On the shared resource timeline Defile
    drains 78 mana per pulse-second (E5) beside Q5 (40/cast, ~1.25s
    cadence), W (70, 15s) and R (100, once), which exhausts the pool
    around t~11.5s.  After that the regen trickle is always claimed by
    the cheaper Q casts that arrive every 1.25s, so a 78-mana pulse never
    fits again: the tick count at 20s equals the tick count at 30s.
    """
    ten = _timed_payload(10)
    twenty = _timed_payload(20)
    thirty = _timed_payload(30)

    ticks_10 = _defile_tick_count(ten)
    ticks_20 = _defile_tick_count(twenty)
    ticks_30 = _defile_tick_count(thirty)

    # 6 pulses land by t=10 (0.5, 4.0, 5.25, 6.5, 7.75, 9.0 — the shared
    # timeline holds pulses during R's channel), a 7th at t=10.25, and the
    # pool is dry before an 8th: 24 -> 28 -> 28 ticks, never 3 x 24.
    assert ticks_10 == 24
    assert ticks_20 > ticks_10  # still solvent through the tenth second
    assert ticks_20 == ticks_30 == 28  # exhaustion: no growth past 20s
    assert ticks_30 < 3 * ticks_10  # honest cutoff, not duration scaling
    # The engine names the dropped pulses in its receipt.
    assert any(
        "insufficient resource omitted" in note and "E" in note
        for note in thirty["notes"]
    )


def test_lay_waste_recasts_on_its_cooldown_across_the_window():
    """Q cast count grows with the window per its (hasted) cooldown."""
    five = _timed_payload(5)
    ten = _timed_payload(10)

    # 0.25s cast + 1.0s cooldown on one shared timeline: casts at 0.25,
    # then 3.75 and 5.0 once R's 3.25s channel releases the hands (3 in
    # 5s), continuing every 1.25s through 10.0 (7 in 10s).
    assert five["breakdown"]["Q"]["casts"] == 3
    assert ten["breakdown"]["Q"]["casts"] == 7


def test_timed_defile_ignores_the_one_rotation_tick_selector():
    """`e_ticks` is one-rotation-only; timed ticks come from the window."""
    default = _timed_payload(10)
    maxed = _timed_payload(
        10,
        champion_options={"wall_contact": True, "q_isolated": True, "e_ticks": 40},
    )

    assert _defile_tick_count(default) == _defile_tick_count(maxed)
    assert default["breakdown"]["E"]["total_damage"] == pytest.approx(
        maxed["breakdown"]["E"]["total_damage"]
    )


def test_timed_timeline_coverage_is_complete_with_no_coarse_sources():
    coverage = _timed_payload(10)["timeline_coverage"]

    assert coverage["complete"] is True
    assert coverage["coarse_sources"] == []


def test_comparison_curve_returns_populated_windows():
    payload = calculate_payload(
        {
            "champion": "Karthus",
            "level": 18,
            "items": [],
            "include_crossover": True,
        }
    )

    assert payload["comparison_curve_status"] == {"available": True}
    curve = payload["comparison_curve"]
    assert [point["rotation"] for point in curve] == [1, 2, 3, 4, 5, 6]
    totals = [point["total_damage"] for point in curve]
    assert all(total > 0 for total in totals)
    # Solvent early windows grow; strict monotonicity is not promised
    # (Wall of Pain's shred is time-weighted over the window, so a longer
    # post-exhaustion window can dilute it slightly).
    assert totals[1] > totals[0]
    assert totals[-1] > totals[0]


def test_timed_defile_pulse_prices_the_sourced_drain_and_fixed_cadence(
    karthus_data,
):
    """One pulse = the sourced DPS row, drain/s, and a haste-proof 1s beat."""
    stats = calculate_total_stats(karthus_data, 18, [])

    def parse_e(haste):
        parse_stats = dict(stats)
        parse_stats["ability_haste"] = haste
        return parse_champion_abilities(
            karthus_data,
            18,
            200.0,
            champion_stats=parse_stats,
            ability_ranks=RANKS,
            champion_options={
                "fight_duration_seconds": 10.0,
                "auto_attack_uptime": 0.0,
            },
        )["E"]

    no_haste = parse_e(0.0)
    hasted = parse_e(50.0)

    # E5 @ 200 AP: per tick 27.5 + 10 = 37.5; one 4-tick pulse-second is
    # exactly the sourced "Damage Per Second" row (110 + 40 = 150).
    assert no_haste["total_raw"] == pytest.approx(150.0)
    assert parts_raw_total(no_haste["parts"], "magic") == pytest.approx(150.0)
    assert no_haste["resource_cost"] == pytest.approx(78.0)  # sourced drain/s
    assert no_haste["dot_tick_interval"] == pytest.approx(0.25)
    # The declared cooldown counter-scales ability haste so the engine's
    # division (cd x 100 / (100 + haste)) lands back on the fixed 1s
    # toggle cadence — the drain is not haste-accelerated.
    assert no_haste["cooldown"] == pytest.approx(1.0)
    assert hasted["cooldown"] == pytest.approx(1.5)


class TestReviewedCrowdControl:
    """Lay Waste and Requiem control nothing; Defile's timed branch withholds."""

    def test_module_cc_is_the_declaration_the_parser_wired(self):
        assert karthus.MODULE_CC == {"Q": "none", "E": "none", "R": "none"}
        assert karthus.parse_abilities.cc_kinds == karthus.MODULE_CC

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Karthus")
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert cc_review.control_words(cc_review.slot_text(data, "R")) == []

    def test_the_only_control_in_the_kit_damages_nothing(self):
        """Wall of Pain slows, but it authors no damage part to stamp."""
        data = cc_review.kit("Karthus")
        assert "become slowed for 5 seconds" in cc_review.slot_text(data, "W")
        assert "W" not in karthus.MODULE_CC

    def test_defiles_timed_pulse_authors_the_cached_tick_beat(self):
        """Defile's aura controls nothing, and both branches say so on their
        own parts: the pulse ticks on the cache's own 0.25-second beat."""
        data = cc_review.kit("Karthus")
        assert (
            "karthus surrounds himself in a necrotic aura that deals magic "
            "damage every 0.25 seconds to all nearby enemies"
            in cc_review.slot_text(data, "E")
        )
        assert cc_review.control_words(cc_review.slot_text(data, "E")) == []
        assert karthus.MODULE_CC["E"] == "none"

        entry = parse_champion_abilities(
            data,
            18,
            200.0,
            champion_stats=calculate_total_stats(data, 18, []),
            ability_ranks=RANKS,
            champion_options={
                "fight_duration_seconds": 10.0,
                "auto_attack_uptime": 0.0,
            },
        )["E"]
        (part,) = entry["parts"]
        assert part.count == 4
        assert part.time_offset == 0.0
        assert part.hit_interval == pytest.approx(0.25)
        assert part.cc_kind == "none"

    def test_every_ability_event_is_now_reviewed(self):
        assert cc_review.unreviewed_ability_slots("Karthus") == []
        coverage = cc_review.fimbulwinter_coverage("Karthus")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
