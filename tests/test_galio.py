"""Reference and event-order tests for Galio's sourced champion module."""

import pytest

from src.calculator.champions import parse_champion_abilities
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.pipeline import FightParams, run_fight
from src.calculator.stats import calculate_total_stats


def _stats(galio_data, level: int = 11) -> dict:
    stats = calculate_total_stats(galio_data, level, [])
    stats.update(
        {
            "attack_damage": 100.0,
            "ability_power": 200.0,
            "magic_resistance": stats["magic_resistance"] + 50.0,
            "bonus_magic_resistance": 50.0,
            "attack_speed": 1.0,
            "attack_speed_ratio": 1.0,
        }
    )
    return stats


def _parse(galio_data, *, options=None, ranks=None, target_health=2000.0):
    stats = _stats(galio_data)
    abilities = parse_champion_abilities(
        galio_data,
        11,
        200.0,
        ability_ranks=ranks or {"Q": 3, "W": 3, "E": 3, "R": 2},
        champion_stats=stats,
        target_stats={
            "target_max_health": target_health,
            "target_current_health": target_health,
            "target_missing_health": 0.0,
        },
        champion_options=options,
    )
    return stats, abilities


def test_reference_damage_formulas(galio_data):
    """Level 11, 200 AP, 50 bonus MR, 2,000 target HP."""
    _, abilities = _parse(galio_data)

    # Q: 140 + 70% AP gust, then four (2% + 2%) max-HP ticks.
    assert abilities["Q"]["total_raw"] == pytest.approx(600.0)
    # W rank 3: (40 + 30% AP) × 3 at a full 1.25s charge.
    assert abilities["W"]["total_raw"] == pytest.approx(300.0)
    assert abilities["E"]["total_raw"] == pytest.approx(370.0)
    assert abilities["R"]["total_raw"] == pytest.approx(440.0)


def test_charge_and_travel_options_author_hit_times(galio_data):
    _, abilities = _parse(
        galio_data,
        options={
            "passive_procs": 0,
            "w_charge_seconds": 0.32,
            "e_dash_distance": 250.0,
        },
    )

    assert abilities["W"]["total_raw"] == pytest.approx(150.0)
    assert abilities["W"]["parts"][0].time_offset == pytest.approx(0.32)
    assert abilities["W"]["cast_time"] == pytest.approx(0.72)
    assert abilities["E"]["parts"][0].time_offset == pytest.approx(0.4 + 250.0 / 2300.0)


def test_q_emits_five_ordered_damage_events(galio_data):
    stats, abilities = _parse(
        galio_data,
        options={
            "passive_procs": 0,
            "w_charge_seconds": 1.25,
            "e_dash_distance": 650.0,
        },
        ranks={"Q": 3, "W": 0, "E": 0, "R": 0},
    )
    result = calculate_fight_damage(
        stats,
        abilities,
        [],
        FightConfig(
            target_health=2000.0,
            target_armor=0.0,
            target_magic_resistance=0.0,
            fight_duration_seconds=5.0,
            one_rotation=True,
            deterministic=True,
        ),
    )

    events = result["breakdown"]["Q"]["damage_events"]
    assert [event["time"] for event in events] == pytest.approx(
        [0.25, 0.75, 1.25, 1.75, 2.25]
    )
    assert sum(event["damage"] for event in events) == pytest.approx(600.0)
    assert result["timeline_coverage"]["complete"] is True


def test_public_pipeline_passes_q_target_max_health(galio_data):
    params = FightParams(
        target_health=2000.0,
        target_armor=0.0,
        target_magic_resistance=0.0,
        fight_duration_seconds=5.0,
        one_rotation=True,
        ability_ranks={"Q": 3, "W": 0, "E": 0, "R": 0},
        champion_options={
            "passive_procs": 0,
            "w_charge_seconds": 1.25,
            "e_dash_distance": 650.0,
        },
    )

    result = run_fight(galio_data, 11, [], params)

    # 140 base gust + four 2%-max-HP ticks against 2,000 HP.
    assert result["breakdown"]["Q"]["total_damage"] == pytest.approx(300.0)


def test_colossal_smash_replaces_the_complete_auto_swing(galio_data):
    stats, abilities = _parse(
        galio_data,
        options={
            "passive_procs": 1,
            "w_charge_seconds": 1.25,
            "e_dash_distance": 650.0,
        },
        ranks={"Q": 0, "W": 0, "E": 0, "R": 0},
    )
    result = calculate_fight_damage(
        stats,
        abilities,
        [],
        FightConfig(
            target_health=2000.0,
            target_armor=100.0,
            target_magic_resistance=0.0,
            fight_duration_seconds=1.0,
            auto_attack_uptime=1.0,
            auto_attacks_only=True,
            deterministic=True,
        ),
    )

    passive = result["breakdown"]["on_hit_ability_passive"]
    # 73.82 level base + 100 AD + 80 AP + 30 bonus-MR scaling.
    assert passive["total_damage"] == pytest.approx(283.82, abs=0.02)
    assert result["breakdown"]["auto_attacks"]["total_damage"] == 0.0
    assert result["total_damage"] == pytest.approx(283.82, abs=0.02)


def test_colossal_smash_does_not_replace_later_ordinary_swings(galio_data):
    stats, abilities = _parse(
        galio_data,
        options={
            "passive_procs": 1,
            "w_charge_seconds": 1.25,
            "e_dash_distance": 650.0,
        },
        ranks={"Q": 0, "W": 0, "E": 0, "R": 0},
    )
    result = calculate_fight_damage(
        stats,
        abilities,
        [],
        FightConfig(
            target_health=2000.0,
            target_armor=100.0,
            target_magic_resistance=0.0,
            fight_duration_seconds=2.0,
            auto_attack_uptime=1.0,
            auto_attacks_only=True,
            deterministic=True,
        ),
    )

    assert result["breakdown"]["on_hit_ability_passive"]["count"] == 1
    assert result["breakdown"]["auto_attacks"]["count"] == 1
    assert result["breakdown"]["on_hit_ability_passive"][
        "total_damage"
    ] == pytest.approx(283.82, abs=0.02)
    assert result["breakdown"]["auto_attacks"]["total_damage"] == pytest.approx(50.0)
    assert result["total_damage"] == pytest.approx(333.82, abs=0.02)
    assert result["timeline_coverage"]["complete"] is True


def test_target_max_health_change_is_repriced(galio_data):
    params = FightParams(
        target_health=500.0,
        target_armor=0.0,
        target_magic_resistance=0.0,
        fight_duration_seconds=5.0,
        one_rotation=True,
        ability_ranks={"Q": 3, "W": 0, "E": 0, "R": 0},
        champion_options={
            "passive_procs": 0,
            "w_charge_seconds": 1.25,
            "e_dash_distance": 650.0,
        },
        target_threshold_health_bonus=200.0,
        target_threshold_health_heal=300.0,
        target_threshold_health_ratio=0.8,
        target_threshold_health_duration=5.0,
    )

    result = run_fight(galio_data, 11, [], params)

    assert result["threshold_health_triggered"] is True
    assert result["target_effective_max_health"] == pytest.approx(700.0)
    assert result["target_healing_received"] > 0.0
    # The target-side heal authors its cadence now, so the fight stays
    # certified; the reprice above is what the lifeline is measured by.
    assert result["timeline_coverage"]["complete"] is True
    assert (
        "target_Protoplasm Harness" not in result["timeline_coverage"]["coarse_sources"]
    )


# ---------------------------------------------------------------------------
# Reviewed crowd control (MODULE_CC, wave 4B)
# ---------------------------------------------------------------------------

# The Wiki's crowd-control vocabulary, as this module's review read it:
# https://wiki.leagueoflegends.com/en-us/Types_of_Crowd_Control
_CC_CONTROL_WORDS = (
    "airborne",
    "charm",
    "fear",
    "flee",
    "immobiliz",
    "knock",
    "pull",
    "root",
    "sleep",
    "slow",
    "snare",
    "stasis",
    "stun",
    "suppress",
    "taunt",
)
_CC_CHAMPION = "Galio"
_CC_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}


def _cc_slot_text(slot):
    """Every cached description of one slot, lowercased."""
    from src.calculator.data_fetcher import get_champion

    return " ".join(
        effect.get("description") or ""
        for ability in get_champion(_CC_CHAMPION)["abilities"].get(slot, [])
        for effect in ability.get("effects", [])
    ).lower()


def _cc_control_hits(slot):
    """The control vocabulary one slot's cached text actually uses."""
    text = _cc_slot_text(slot)
    return [word for word in _CC_CONTROL_WORDS if word in text]


def _cc_kinds(**options):
    """Result key -> the reviewed kinds the slot's parts actually carry."""
    from src.calculator.champions import parse_champion_abilities
    from src.calculator.data_fetcher import get_champion

    parsed = parse_champion_abilities(
        get_champion(_CC_CHAMPION),
        18,
        100.0,
        _CC_RANKS,
        champion_options=options or None,
    )
    carried = {
        key: sorted({part.cc_kind for part in entry.get("parts") or () if part.cc_kind})
        for key, entry in parsed.items()
    }
    return {key: kinds for key, kinds in carried.items() if kinds}


def _cc_timeline_coverage():
    """The campaign's control-token probe, through the public entry."""
    from src.calculator.calculate import calculate_payload

    return calculate_payload(
        {
            "champion": _CC_CHAMPION,
            "level": 18,
            "items": ["Fimbulwinter"],
            "fight_mode": "timed",
            "include_auto_attacks": True,
        }
    )["timeline_coverage"]


class TestReviewedCrowdControl:
    """Shield of Durand taunts, Justice Punch knocks up, R knocks back.

    A control-armed holder shield (Fimbulwinter's Everlasting) reads the
    reviewed ``cc_kind`` off authored damage events; an unreviewed ability
    packet makes the whole timed fight fall back to coarse ordering, so the
    probe below is the reason these declarations exist.
    """

    def test_module_cc_is_the_declaration_the_parser_wired(self):
        from src.calculator.champions import galio

        assert galio.MODULE_CC == {
            "Q": "none",
            "W": "taunt",
            "E": "knockup",
            "R": "knockback",
        }
        assert galio.parse_abilities.cc_kinds == galio.MODULE_CC

    def test_each_declared_kind_is_the_word_its_slot_text_uses(self):
        for slot, word in [["W", "taunt"], ["E", "knock"], ["R", "knock"]]:
            assert word in _cc_slot_text(slot), slot

    def test_control_free_slots_name_every_word_their_text_contains(self):
        for slot, expected in [["Q", ["slow"]]]:
            assert _cc_control_hits(slot) == list(expected), slot

    def test_every_reviewed_part_carries_its_kind(self):
        assert _cc_kinds() == {
            "Q": ["none"],
            "W": ["taunt"],
            "E": ["knockup"],
            "R": ["knockback"],
        }

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = _cc_timeline_coverage()

        assert coverage["complete"] is True
        assert coverage["certification"] == "event_order_certified"
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
