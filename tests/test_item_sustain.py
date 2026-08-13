"""Full-entry sustain receipts for starter and defensive items."""

from types import SimpleNamespace

import pytest

from src.calculator.program.build import roster_program as _roster_program
from src.calculator.program.views.survival import survival as _survival_view
from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.pipeline import (
    FightParams,
    _item_self_healing_events,
    run_fight,
)
from src.calculator.champions import parse_champion_abilities
from src.calculator.damage import calculate_fight_damage
from src.calculator.participant_timeline import Combatant, _simulate_survival
from src.calculator.stats import calculate_total_stats, get_item_stats


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


def test_catalyst_heals_from_timestamped_mana_spent_with_sourced_caps():
    item = get_item_by_name("Catalyst of Aeons")
    result = {
        "champion_stats": {},
        "damage_events": [],
        "breakdown": {},
        "cast_timeline": [
            {
                "time": 0.1,
                "slot": "Q",
                "ordinal": 1,
                "resource_before": 500.0,
                "resource_after": 400.0,
                "resource_cost": 100.0,
            },
            {
                "time": 0.2,
                "slot": "W",
                "ordinal": 1,
                "resource_before": 400.0,
                "resource_after": 300.0,
                "resource_cost": 100.0,
            },
            {
                "time": 1.1,
                "slot": "E",
                "ordinal": 1,
                "resource_before": 300.0,
                "resource_after": 200.0,
                "resource_cost": 100.0,
            },
        ],
    }
    events = _item_self_healing_events(result, [item], 2.0)
    assert [event["amount"] for event in events if "Catalyst" in event["source"]] == [
        20.0,
        20.0,
    ]
    assert [event["time"] for event in events if "Catalyst" in event["source"]] == [
        0.1,
        1.1,
    ]


def test_catalyst_damage_taken_restore_reenters_ordered_resource_admission(
    ahri_data,
):
    """Eternity's pre-mitigation restore can pay for a later cast."""
    item = get_item_by_name("Catalyst of Aeons")
    stats = calculate_total_stats(ahri_data, 18, [item])
    abilities = parse_champion_abilities(
        ahri_data, 18, stats["ability_power"], champion_stats=stats
    )
    q = dict(abilities["Q"])
    q.update({"resource_type": "MANA", "resource_cost": 300.0, "cooldown": 1.0})
    stats.update(
        {
            "max_mana": 500.0,
            "resource_regen_per_second": 0.0,
        }
    )
    result = calculate_fight_damage(
        stats,
        {"Q": q},
        [item],
        FightParams(
            target_health=10000.0,
            target_armor=0.0,
            target_magic_resistance=0.0,
            fight_duration_seconds=4.0,
            one_rotation=False,
            enforce_resource_limits=True,
            cast_order=["Q"],
            resource_restore_events=((1.5, 200.0),),
        ),
    )
    assert result["breakdown"]["Q"]["casts"] == 2
    assert result["cast_timeline"][1]["resource_before"] == pytest.approx(400.0)
    assert result["resource_restore_events"] == [
        {
            "time": 1.5,
            "amount": 200.0,
            "source": "Catalyst of Aeons (Eternity)",
        }
    ]


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
    result = _simulated_rows([source, target], incoming, healing, {}, 1.0)
    assert result["target"]["healing_received"] == pytest.approx(22.5)
