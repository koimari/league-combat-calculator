"""Full-entry sustain receipts for starter and defensive items."""

from types import SimpleNamespace

import pytest

from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.pipeline import FightParams, _item_self_healing_events, run_fight
from src.calculator.participant_timeline import Combatant, _simulate_survival
from src.calculator.stats import calculate_total_stats, get_item_stats


def test_doran_shield_uses_flat_hp5_and_exposes_total_regen(ahri_data):
    """Enduring Focus must not lose Doran's flat health-regeneration stat."""
    item = get_item_by_name("Doran's Shield")
    assert get_item_stats(item)["health_regen_flat"] == 4.0
    stats = calculate_total_stats(ahri_data, 18, [item])
    assert stats["health_regen_per_five"] == pytest.approx(
        stats["base_health_regen_per_five"] + 4.0
    )
    assert stats["health_regen_per_second"] == pytest.approx(
        stats["health_regen_per_five"] / 5.0
    )


def test_dorans_blade_direct_heal_uses_basic_and_reduced_effectiveness():
    """Life Draining follows post-mitigation damage and the area reduction."""
    item = get_item_by_name("Doran's Blade")
    result = {
        "champion_stats": {},
        "damage_events": [
            {
                "time": 0.1,
                "damage": 100.0,
                "source_key": "auto_attacks",
                "basic_attack": True,
            },
            {"time": 1.0, "damage": 100.0, "source_key": "Q"},
        ],
        "breakdown": {},
    }
    events = _item_self_healing_events(result, [item], 2.0)
    assert [event["amount"] for event in events] == pytest.approx([2.5, 2.5 * 0.333])
    assert all(event["source"] == "Doran's Blade (Life Draining)" for event in events)


def test_dorans_ring_converts_only_when_mana_cannot_be_gained():
    """Drain remains a mana restoration while the actor has resource room."""
    item = get_item_by_name("Doran's Ring")
    base = {
        "champion_stats": {"max_mana": 0.0},
        "damage_events": [{"time": 0.0, "damage": 100.0}],
        "breakdown": {},
    }
    healing = _item_self_healing_events(base, [item], 2.0)
    assert [event["amount"] for event in healing] == pytest.approx([0.9, 0.9])

    full_mana = {
        **base,
        "champion_stats": {"max_mana": 500.0},
        "resource_remaining": 499.0,
    }
    assert _item_self_healing_events(full_mana, [item], 2.0) == []


def test_dorans_blade_no_longer_reports_stale_omnivamp(ahri_data):
    """The current entry's Life Draining passive supersedes old cache text."""
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
    assert result["champion_stats"]["omnivamp_percent"] == 0.0
    assert any(
        event["source"] == "Doran's Blade (Life Draining)"
        for event in result["self_healing_events"]
    )


def test_spirit_visage_does_not_amplify_lifesteal_or_omnivamp():
    """Boundless Vitality amplifies direct heals, not vamp stat packets."""
    defenses = SimpleNamespace(
        magic_shield=0.0,
        physical_shield=0.0,
        general_shield=0.0,
        healing_received_multiplier=1.25,
    )
    source = Combatant(
        participant_id="source",
        team="main",
        champion_data={"name": "Ahri"},
        level=18,
        items=(),
        stats={"health": 100.0},
        defenses=defenses,
    )
    target = Combatant(
        participant_id="target",
        team="enemy",
        champion_data={"name": "Aatrox"},
        level=18,
        items=(),
        stats={"health": 100.0},
        defenses=defenses,
    )
    healing = {
        "target": [
            {
                "time": 0.0,
                "amount": 10.0,
                "kind": "heal",
                "healing_category": "vamp",
                "source": "Life steal",
            },
            {"time": 0.2, "amount": 10.0, "kind": "heal", "source": "Direct heal"},
        ]
    }
    # Put the target below max health before the healing stream.
    incoming = {
        "target": [
            {
                "time": 0.0,
                "damage": 50.0,
                "damage_type": "true",
                "attacker": "source",
                "target": "target",
                "source_key": "opening",
                "_event_id": "opening",
            }
        ]
    }
    result = _simulate_survival([source, target], incoming, healing, {}, 1.0)
    assert result["target"]["healing_received"] == pytest.approx(22.5)
