"""Revision-backed formulas, state controls, and event order for Taliyah."""

import pytest

from src.calculator.ability_spec import parts_raw_total
from src.calculator.calculate import calculate_payload
from src.calculator.champions import (
    get_champion_cast_order,
    get_champion_options_meta,
    get_comparison_curve_unavailable_reason,
    get_custom_cast_order_unavailable_reason,
    get_supported_fight_modes,
    get_unsupported_fight_mode_reason,
    taliyah,
)
from tests import cc_review

RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}


def _parse(taliyah_data, parse_at, *, ground="normal", detonations=4, distance=800):
    return parse_at(
        taliyah_data,
        18,
        ap=200,
        ability_ranks=RANKS,
        champion_options={
            "q_ground": ground,
            "e_detonations": detonations,
            "q_target_distance": distance,
        },
    )


def _parse_roster_target(taliyah_data, parse_at, target_index):
    return parse_at(
        taliyah_data,
        18,
        ap=200,
        ability_ranks=RANKS,
        target_stats={
            "target_max_health": 2500.0,
            "roster_target_index": float(target_index),
            "roster_target_count": 2.0,
        },
        champion_options={
            "q_ground": "worked",
            "e_detonations": 4,
            "q_target_distance": 800,
        },
    )


def test_normal_volley_and_four_stone_combo_use_sourced_formulas(
    taliyah_data, parse_at
):
    _, abilities = _parse(taliyah_data, parse_at)

    # Q5 @ 200 AP: first 225, then 4 x 90 = 585.
    assert parts_raw_total(abilities["Q"]["parts"], "magic") == pytest.approx(585.0)
    assert len(abilities["Q"]["parts"]) == 5
    # E5 @ 200 AP: 360 initial + 145 x (1 + .75 + .5 + .25).
    assert parts_raw_total(abilities["E"]["parts"], "magic") == pytest.approx(722.5)
    assert abilities["W"]["parts"] == ()
    assert abilities["W"]["total_raw"] == 0.0


def test_stone_count_is_explicit_and_never_exceeds_four(taliyah_data, parse_at):
    _, none = _parse(taliyah_data, parse_at, detonations=0)
    _, two = _parse(taliyah_data, parse_at, detonations=2)
    _, clamped = _parse(taliyah_data, parse_at, detonations=99)

    assert parts_raw_total(none["E"]["parts"]) == pytest.approx(360.0)
    assert parts_raw_total(two["E"]["parts"]) == pytest.approx(360.0 + 145.0 * 1.75)
    assert parts_raw_total(clamped["E"]["parts"]) == pytest.approx(722.5)


def test_worked_ground_changes_damage_cost_cooldown_and_projectile(
    taliyah_data, parse_at
):
    _, normal = _parse(taliyah_data, parse_at, ground="normal", distance=1000)
    _, worked = _parse(taliyah_data, parse_at, ground="worked", distance=1000)

    assert parts_raw_total(worked["Q"]["parts"], "magic") == pytest.approx(405.0)
    assert worked["Q"]["resource_cost"] == pytest.approx(10.0)
    assert worked["Q"]["cooldown"] == pytest.approx(1.5)
    assert normal["Q"]["resource_cost"] == pytest.approx(75.0)
    assert normal["Q"]["cooldown"] == pytest.approx(3.0)
    assert len(worked["Q"]["parts"]) == 1
    assert worked["Q"]["parts"][0].time_offset == pytest.approx(1.225)


def test_worked_boulder_uses_primary_and_secondary_target_formulas(
    taliyah_data, parse_at
):
    _, primary = _parse_roster_target(taliyah_data, parse_at, 0)
    _, secondary = _parse_roster_target(taliyah_data, parse_at, 1)

    assert parts_raw_total(primary["Q"]["parts"]) == pytest.approx(405.0)
    assert parts_raw_total(secondary["Q"]["parts"]) == pytest.approx(225.0)
    assert "primary target" in primary["Q"]["detail"]
    assert "secondary target" in secondary["Q"]["detail"]


def test_rotation_is_resource_legal_and_event_order_certified(
    taliyah_data, parse_at, fight
):
    stats, abilities = _parse(taliyah_data, parse_at)
    result = fight(
        stats,
        abilities,
        target_magic_resistance=100,
        cast_order=get_champion_cast_order("Taliyah"),
        enforce_resource_limits=True,
    )

    assert get_champion_cast_order("Taliyah") == ["E", "W", "Q"]
    assert [event["slot"] for event in result["cast_timeline"]] == [
        "E",
        "W",
        "Q",
    ]
    assert result["resource_spent"] == pytest.approx(165.0)
    assert result["resource_remaining"] == pytest.approx(stats["max_mana"] - 165.0)
    assert result["total_damage"] == pytest.approx((722.5 + 585.0) / 2.0)
    assert result["timeline_coverage"]["complete"] is True
    assert result["timeline_coverage"]["certification"] == "event_order_certified"
    assert result["timeline_coverage"]["exact_sources"] == ["E", "Q"]


def test_public_metadata_exposes_state_without_mode_restriction():
    """Timed support means no restriction constants survive in the module."""
    meta = get_champion_options_meta("Taliyah")

    assert {option["key"] for option in meta["options"]} == {
        "q_ground",
        "e_detonations",
        "q_target_distance",
    }
    # No SUPPORTED_FIGHT_MODES restriction: the key is absent entirely.
    assert "supported_fight_modes" not in meta
    assert len(meta["sources"]) == 5
    assert get_supported_fight_modes("Taliyah") is None
    assert get_unsupported_fight_mode_reason("Taliyah") is None
    assert get_comparison_curve_unavailable_reason("Taliyah") is None
    # The certified E -> W -> Q sequence still refuses custom orders.
    assert get_custom_cast_order_unavailable_reason("Taliyah")


# ---------------------------------------------------------------------------
# Timed mode: the Worked Ground terrain walk (full-coverage criterion 3)
# ---------------------------------------------------------------------------

# Sourced Q numbers at rank 5 (data/champions.json): fresh volley 125 base
# (+50% AP) first shard, 50 (+20% AP) later shards; Worked Ground boulder is
# the wiki's "Empowered Damage" 180% row: 225 base (+90% AP). Cost 75 fresh,
# 10 worked; cooldown 3.0 fresh, halved (min 0.75) worked; 0.25s cast time.
_Q5_FRESH_CD = 3.0
_Q5_WORKED_CD = 1.5
_Q_CAST_TIME = 0.25
_WORKED_CADENCE = _Q_CAST_TIME + _Q5_WORKED_CD  # 1.75s between boulders


def _parse_timed(taliyah_data, parse_at, *, duration=10.0, ap=200, ground="normal"):
    return parse_at(
        taliyah_data,
        18,
        ap=ap,
        ability_ranks=RANKS,
        champion_options={
            "q_ground": ground,
            "e_detonations": 4,
            "q_target_distance": 800,
            "fight_duration_seconds": duration,
        },
    )


def test_timed_q_walks_the_worked_ground_terrain_state(taliyah_data, parse_at):
    """Cast 1 = full fresh volley; every later cast = the empowered boulder."""
    _, abilities = _parse_timed(taliyah_data, parse_at)
    q = abilities["Q"]

    # 10s at zero haste: casts start at 0, 3.25, 5.0, 6.75, 8.5 (next would
    # be 10.25 > 10) — one fresh volley plus four Worked Ground boulders.
    parts = q["parts"]
    assert len(parts) == 5 + 4
    assert [part.amount for part in parts[:5]] == pytest.approx(
        [225.0, 90.0, 90.0, 90.0, 90.0]
    )
    assert [part.amount for part in parts[5:]] == pytest.approx([405.0] * 4)
    # The sourced Worked Ground ratio: Empowered Damage = 180% of a shard.
    assert parts[5].amount / parts[0].amount == pytest.approx(1.8)
    assert q["total_raw"] == pytest.approx(585.0 + 4 * 405.0)
    # Mana walks the same terrain state: one fresh cast + 10 per boulder.
    assert q["resource_type"] == "MANA"
    assert q["resource_cost"] == pytest.approx(75.0 + 4 * 10.0)
    # The entry is the engine's cast-exactly-once idiom; the walk owns the
    # recast cadence, and each authored cast counts as an instance.
    assert q["cooldown"] == 0.0
    assert q["cast_instances"] == 5


def test_timed_q_cadence_uses_fresh_then_worked_cooldowns(taliyah_data, parse_at):
    """Boulders repeat on the halved cooldown; the first waits the full one."""
    _, abilities = _parse_timed(taliyah_data, parse_at)
    parts = abilities["Q"]["parts"]

    boulder_travel = 750.0 / 2000.0  # (800 - 50 origin offset) / worked speed
    boulder_times = [part.time_offset for part in parts[5:]]
    # Cast 2 waits out the FULL fresh-cast cooldown (0.25 cast + 3.0s).
    assert boulder_times[0] == pytest.approx(
        (_Q_CAST_TIME + _Q5_FRESH_CD) + _Q_CAST_TIME + boulder_travel
    )
    deltas = [b - a for a, b in zip(boulder_times, boulder_times[1:])]
    assert deltas == pytest.approx([_WORKED_CADENCE] * 3)


def test_timed_q_cast_count_grows_with_fight_duration(taliyah_data, parse_at):
    """The walk adds boulders on the worked (short) cooldown as time grows."""
    _, at_10 = _parse_timed(taliyah_data, parse_at, duration=10.0)
    _, at_20 = _parse_timed(taliyah_data, parse_at, duration=20.0)

    assert len(at_10["Q"]["parts"]) == 5 + 4
    # Ten more seconds on the 1.75s worked cadence buys six more boulders.
    assert len(at_20["Q"]["parts"]) == 5 + 10
    assert at_20["Q"]["resource_cost"] == pytest.approx(75.0 + 10 * 10.0)


def test_timed_q_derives_terrain_and_ignores_the_one_rotation_select(
    taliyah_data, parse_at
):
    """q_ground is a one-rotation input; timed mode owns the terrain state."""
    _, normal = _parse_timed(taliyah_data, parse_at, ground="normal")
    _, worked = _parse_timed(taliyah_data, parse_at, ground="worked")

    assert normal["Q"]["parts"] == worked["Q"]["parts"]
    assert normal["Q"]["resource_cost"] == worked["Q"]["resource_cost"]


def test_timed_q_boulders_use_secondary_formula_off_the_primary_target(
    taliyah_data, parse_at
):
    _, abilities = parse_at(
        taliyah_data,
        18,
        ap=0,
        ability_ranks=RANKS,
        target_stats={
            "target_max_health": 2500.0,
            "roster_target_index": 1.0,
            "roster_target_count": 2.0,
        },
        champion_options={
            "q_ground": "normal",
            "e_detonations": 4,
            "q_target_distance": 800,
            "fight_duration_seconds": 10.0,
        },
    )
    parts = abilities["Q"]["parts"]
    # Secondary Target Damage row (125 base at rank 5), not the 225 boulder.
    assert [part.amount for part in parts[5:]] == pytest.approx([125.0] * 4)
    assert "secondary" in abilities["Q"]["detail"]


def test_timed_haste_shortens_the_worked_cadence(taliyah_data, parse_at):
    """Ability haste compresses both cooldowns, buying extra boulders."""
    from src.calculator.data_fetcher import get_item_by_name

    _, unhasted = _parse_timed(taliyah_data, parse_at)
    _, hasted = parse_at(
        taliyah_data,
        18,
        items=[get_item_by_name("Cosmic Drive")],
        ap=200,
        ability_ranks=RANKS,
        champion_options={
            "q_ground": "normal",
            "e_detonations": 4,
            "q_target_distance": 800,
            "fight_duration_seconds": 10.0,
        },
    )

    assert len(hasted["Q"]["parts"]) > len(unhasted["Q"]["parts"])
    hasted_deltas = [
        b.time_offset - a.time_offset
        for a, b in zip(hasted["Q"]["parts"][5:], hasted["Q"]["parts"][6:])
    ]
    assert all(delta < _WORKED_CADENCE for delta in hasted_deltas)


# --- Runtime probes through calculate_payload (pinned engine output) -------


def _timed_payload(duration):
    return calculate_payload(
        {
            "champion": "Taliyah",
            "level": 18,
            "fight_mode": "time_based",
            "fight_duration": duration,
            "ability_ranks": RANKS,
        }
    )


def test_payload_second_q_occurrence_prices_the_worked_ground_profile():
    """Criterion 3(a): cast 1 is the fresh volley, cast 2 the 180% boulder.

    No items, 0 AP, default 100 MR target: fresh first shard 125 raw ->
    62.5 mitigated, later shards 50 -> 25.0; the second Q occurrence is
    one boulder at the sourced Empowered Damage row 225 -> 112.5.
    """
    payload = _timed_payload(10.0)
    q_events = [e for e in payload["damage_events"] if e["source"] == "Q"]

    assert [event["damage"] for event in q_events[:5]] == pytest.approx(
        [62.5, 25.0, 25.0, 25.0, 25.0]
    )
    assert q_events[5]["damage"] == pytest.approx(112.5)
    # Cast 1 != cast 2, by exactly the sourced 180% Worked Ground ratio.
    assert q_events[5]["damage"] / q_events[0]["damage"] == pytest.approx(1.8)


def test_payload_q_casts_grow_with_duration_on_the_worked_cooldown():
    """Criterion 3(b): more window, more boulders, spaced 1.75s apart."""
    ten = [e for e in _timed_payload(10.0)["damage_events"] if e["source"] == "Q"]
    twenty = [e for e in _timed_payload(20.0)["damage_events"] if e["source"] == "Q"]

    assert len(ten) == 5 + 4
    assert len(twenty) == 5 + 10
    boulder_times = [event["time"] for event in ten[5:]]
    # Q is scheduled at 0.5 (after E and W casts); boulders land at
    # 0.5 + start + 0.25 cast + 0.375 travel on the worked cadence.
    assert boulder_times == pytest.approx([4.375, 6.125, 7.875, 9.625], abs=2e-3)


def test_payload_timed_timeline_is_complete_with_no_coarse_sources():
    """Criterion 3(c): full certification through the real pipeline."""
    payload = _timed_payload(10.0)
    coverage = payload["timeline_coverage"]

    assert coverage["complete"] is True
    assert coverage["coarse_sources"] == []
    assert coverage["certification"] == "event_order_certified"
    assert coverage["exact_sources"] == ["E", "Q"]
    # The walk's mana is paid on the shared resource timeline: E 90 + two
    # W casts at rank-5 cost 0 + Q's 75 fresh + 4 x 10 worked = 205.
    assert payload["resource_spent"] == pytest.approx(205.0)
    assert not any("insufficient resource" in note for note in payload["notes"])
    # Engine total 838.75 (Q 612.5 + E 226.25), rounded by the payload.
    assert payload["total_damage"] == pytest.approx(838.75, abs=0.05)


class TestReviewedCrowdControl:
    """Taliyah's reviewed crowd control, authored per part.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    Neither damaging slot has one answer for the whole cast — Q's fresh
    shards control nothing while its Worked Ground boulders slow, and E's
    eruption slows while its stone detonations stun — so each part carries
    its own reviewed kind instead of a per-slot MODULE_CC entry.
    """

    def test_the_kit_has_no_single_per_slot_answer_to_declare(self):
        data = cc_review.kit("Taliyah")
        assert not hasattr(taliyah, "MODULE_CC")
        assert "slowing all targets hit for 1.5 seconds" in cc_review.slot_text(
            data, "Q"
        )
        assert "slow enemies within the area by 20%" in cc_review.slot_text(data, "E")
        assert "becoming stunned for 0.75 seconds" in cc_review.slot_text(data, "E")

    def test_each_part_carries_the_kind_its_own_cached_branch_gives(self):
        results = taliyah.parse_abilities(
            cc_review.kit("Taliyah"),
            18,
            0.0,
            champion_options={"q_ground": "worked", "e_detonations": 4},
        )
        assert [part.cc_kind for part in results["Q"]["parts"]] == ["slow"]
        assert [part.cc_kind for part in results["E"]["parts"]] == [
            "slow",
            "stun",
            "stun",
            "stun",
            "stun",
        ]
        fresh = taliyah.parse_abilities(
            cc_review.kit("Taliyah"),
            18,
            0.0,
            champion_options={"q_ground": "normal", "e_detonations": 0},
        )
        assert {part.cc_kind for part in fresh["Q"]["parts"]} == {"none"}
        assert [part.cc_kind for part in fresh["E"]["parts"]] == ["slow"]

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Taliyah") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Taliyah")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
