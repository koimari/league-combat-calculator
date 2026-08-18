"""Event-certification and sourced-cadence tests for Fizz's module.

Wave 1B: Seastone Trident's burn must be event-certified in timed fights —
the W row authors its active hit and the sourced 6-tick 0.5s ledger, and
the ledger sum-reconciles to the row total exactly.
"""

import pytest

from src.calculator.calculate import calculate_payload
from src.calculator.data_fetcher import get_champion
from src.calculator.pipeline import FightParams, run_fight
from src.calculator.scenario import load_public_champion

_W_TICKS = 6
_W_TICK_INTERVAL = 0.5


def _timed_params(**overrides):
    request = {
        "fight_mode": "time_based",
        "fight_duration": 10,
        "include_auto_attacks": True,
        "auto_attack_uptime": 0.8,
        "target_health": 1000,
        "target_armor": 100,
        "target_mr": 100,
    }
    request.update(overrides)
    return FightParams.from_request(request, deterministic=True)


def test_timed_payload_probe_certifies_full_timeline():
    """The campaign probe: bare-kit timed Fizz has no coarse sources."""
    result = calculate_payload(
        {
            "champion": "Fizz",
            "level": 18,
            "items": [],
            "fight_mode": "timed",
            "include_auto_attacks": True,
        }
    )
    coverage = result["timeline_coverage"]
    assert coverage["complete"] is True
    assert coverage["coarse_sources"] == []
    assert "W" in coverage["exact_sources"]


def test_timed_w_ledger_sums_and_ticks_at_the_sourced_cadence():
    result = run_fight(load_public_champion("Fizz"), 18, [], _timed_params())
    coverage = result["timeline_coverage"]
    assert coverage["complete"] is True
    assert coverage["certification"] == "event_order_certified"

    row = result["breakdown"]["W"]
    events = row["damage_events"]
    casts = row["casts"]
    # One active hit plus the six sourced burn ticks per cast.
    assert len(events) == casts * (1 + _W_TICKS)
    assert sum(event["damage"] for event in events) == pytest.approx(
        row["total_damage"]
    )
    assert not any(event.get("event_precision") == "cast_boundary" for event in events)
    # The first cast lands at t=0: its active hit at the cast instant and
    # its ticks every 0.5s through 3.0s.
    tick_times = sorted(
        event["time"] for event in events if event.get("event_precision") == "exact"
    )[:_W_TICKS]
    assert tick_times == pytest.approx(
        [_W_TICK_INTERVAL * step for step in range(1, _W_TICKS + 1)]
    )


def test_timed_auto_stream_keeps_its_swings_when_w_rides_it():
    """With an ambient stream, W's empowered attack is one of its swings.

    The auto row keeps every swing (W no longer consumes them onto its own
    row), and its per-swing receipts still reconcile.
    """
    result = run_fight(load_public_champion("Fizz"), 18, [], _timed_params())
    auto = result["breakdown"]["auto_attacks"]
    assert "incl. basic attack" not in str(result["breakdown"]["W"].get("detail", ""))
    assert sum(event["damage"] for event in auto["damage_events"]) == pytest.approx(
        auto["total_damage"]
    )


def test_one_rotation_w_still_forces_the_empowered_swing():
    """Without an ambient stream the cast forces its attack, as before."""
    result = run_fight(
        load_public_champion("Fizz"),
        18,
        [],
        FightParams.from_request(
            {
                "fight_mode": "one_rotation",
                "target_health": 1000,
                "target_armor": 0,
                "target_mr": 0,
            },
            deterministic=True,
        ),
    )
    row = result["breakdown"]["W"]
    # Active + ticks + the forced 100% AD swing, all authored and summing.
    assert row["damage_by_type"]["physical"] > 0
    assert sum(event["damage"] for event in row["damage_events"]) == pytest.approx(
        row["total_damage"]
    )
    assert result["timeline_coverage"]["complete"] is True


def test_w_tick_count_and_cadence_are_sourced_from_the_cache():
    """The 6x0.5s ledger is the cached wiki data's, not an invention."""
    ability = get_champion("Fizz")["abilities"]["W"][0]
    effects = ability["effects"]
    leveling = {
        row["attribute"]: row["modifiers"]
        for effect in effects
        for row in effect.get("leveling", [])
    }
    totals = leveling["Total Passive Magic Damage"]
    per_tick = leveling["Passive Magic Damage per Tick"]
    for rank in range(5):
        assert totals[0]["values"][rank] == pytest.approx(
            per_tick[0]["values"][rank] * _W_TICKS
        )
        # The per-tick AP ratio is wiki-rounded (4.17% x 6 = 25.02% vs 25%).
        assert totals[1]["values"][rank] == pytest.approx(
            per_tick[1]["values"][rank] * _W_TICKS, rel=2e-3
        )
    passive_text = effects[0]["description"]
    assert "every 0.5 seconds over 3 seconds" in passive_text
