"""Focused tests for the explicitly eligible omnivamp event bridge."""

import pytest

from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.pipeline import FightParams, run_fight


def test_omnivamp_follows_explicit_primary_attack_packets(attacker_stats, fight):
    """Doran-style omnivamp heals from authored auto/on-hit damage only."""
    stats = attacker_stats(omnivamp_percent=10.0)
    result = fight(
        stats,
        include_actives=False,
        auto_attack_uptime=1.0,
        one_rotation=False,
        fight_duration_seconds=3.0,
    )

    auto_events = result["breakdown"]["auto_attacks"]["damage_events"]
    ordered_auto_events = [
        event
        for event in result["damage_events"]
        if event["source_key"] == "auto_attacks"
    ]
    heal = result["breakdown"]["heal_omnivamp"]
    assert auto_events
    assert all(event["omnivamp_effectiveness"] == 1.0 for event in ordered_auto_events)
    assert heal["count"] == len(auto_events)
    assert heal["total_amount"] == pytest.approx(
        sum(event["damage"] for event in auto_events) * 0.10
    )


def test_omnivamp_is_materialized_as_ordered_self_healing():
    """The public pipeline carries the same heal rows into the timeline."""
    params = FightParams.from_request(
        {
            "fight_mode": "timed",
            "fight_duration": 3,
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
        }
    )
    result = run_fight(
        get_champion("Ahri"),
        18,
        [get_item_by_name("Doran's Blade")],
        params,
    )

    events = [
        event
        for event in result["self_healing_events"]
        if event["source"] == "Omnivamp (explicit single-target attacks and on-hit)"
    ]
    assert events
    assert result["self_healing"] >= sum(event["amount"] for event in events)
