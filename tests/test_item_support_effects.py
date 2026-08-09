"""Typed cross-participant item packets and explicit trigger contracts."""

from collections import defaultdict
from types import SimpleNamespace

import pytest

from src.calculator.item_effects import ally_item_effect_value
from src.calculator.item_effects import ally_item_level_value
from src.calculator.item_support_effects import (
    derive_item_support_effects,
    schedule_knights_vow,
)


def _actor(
    participant_id: str,
    team: str,
    item_names: tuple[str, ...],
    *,
    level: int = 18,
    item_options: dict | None = None,
    ally_effects_enabled: bool = True,
):
    return SimpleNamespace(
        participant_id=participant_id,
        team=team,
        level=level,
        items=tuple({"name": name} for name in item_names),
        stats={"mana": 1000.0, "max_mana": 1000.0, "is_melee": False},
        request=SimpleNamespace(
            item_options=item_options or {},
            ally_effects_enabled=ally_effects_enabled,
        ),
    )


def test_ally_item_accessor_fails_loudly_for_missing_source_key():
    with pytest.raises(KeyError, match="sanctify_duration"):
        ally_item_effect_value("Ardent Censer", "sanctify_duration_missing")


def test_level_scaling_honors_sourced_breakpoints():
    assert ally_item_level_value(
        "Locket of the Iron Solari", "shield_min", "shield_max", 9
    ) == pytest.approx(290.0)
    assert ally_item_level_value(
        "Locket of the Iron Solari", "shield_min", "shield_max", 18
    ) == pytest.approx(360.0)
    assert ally_item_level_value(
        "Solstice Sleigh", "temporary_health_min", "temporary_health_max", 6
    ) == pytest.approx(50.0)


def test_ardent_and_moonstone_use_the_authored_heal_or_shield_target():
    holder = _actor("ally:Lulu", "ally", ("Ardent Censer", "Moonstone Renewer"))
    first = _actor("main:Ahri", "main", ())
    second = _actor("ally:Nami", "ally", ())
    trigger = {
        "time": 1.0,
        "kind": "shield",
        "target": first.participant_id,
        "amount": 200.0,
        "duration": 2.0,
    }

    packets = derive_item_support_effects(
        holder,
        {"damage_events": []},
        [holder, first, second],
        trigger_effects=[trigger],
    )

    sanctify = [p for p in packets if p["source"] == "Ardent Censer — Sanctify"]
    assert {p["target"] for p in sanctify} == {
        holder.participant_id,
        first.participant_id,
    }
    chain = next(
        p for p in packets if p["source"] == "Moonstone Renewer — Starlit Grace"
    )
    assert chain["target"] == second.participant_id
    assert chain["amount"] == pytest.approx(70.0)
    assert chain["chain_fraction"] == pytest.approx(0.35)


def test_cryptbloom_requires_an_explicit_takedown_receipt():
    holder = _actor("ally:Lulu", "ally", ("Cryptbloom",))
    target = _actor("main:Ahri", "main", ())
    assert (
        derive_item_support_effects(holder, {"damage_events": []}, [holder, target])
        == []
    )

    packets = derive_item_support_effects(
        holder,
        {"takedown_events": [{"time": 3.0, "target": "enemy:Aatrox"}]},
        [holder, target],
    )
    heals = [p for p in packets if p["source"] == "Cryptbloom — Life From Death"]
    assert {p["target"] for p in heals} == {
        holder.participant_id,
        target.participant_id,
    }
    assert all(p["amount"] == pytest.approx(100.0) for p in heals)
    assert all(p["duration"] == pytest.approx(1.75) for p in heals)


def test_explicit_locket_active_has_no_implicit_t_zero_cast():
    holder = _actor(
        "ally:Lulu",
        "ally",
        ("Locket of the Iron Solari",),
        item_options={"Locket of the Iron Solari": {"active_seconds": 2.5}},
    )
    target = _actor("main:Ahri", "main", ())
    packets = derive_item_support_effects(holder, {}, [holder, target])

    shields = [p for p in packets if p["kind"] == "shield"]
    assert {p["target"] for p in shields} == {
        holder.participant_id,
        target.participant_id,
    }
    assert all(p["time"] == pytest.approx(2.5) for p in shields)
    assert all(p["amount"] == pytest.approx(360.0) for p in shields)

    no_cast = _actor(
        "ally:Lulu",
        "ally",
        ("Locket of the Iron Solari",),
    )
    assert derive_item_support_effects(no_cast, {}, [no_cast, target]) == []


def test_cp20_progression_items_emit_typed_economy_vision_and_movement_receipts():
    holder = _actor(
        "main:Ahri",
        "main",
        ("Cull", "Phage", "World Atlas"),
        item_options={
            "Cull": {"reap_minion_kills": 100},
            "World Atlas": {"shared_riches_gold": 400, "ward_uses": 3},
        },
    )
    target = _actor("enemy:Aatrox", "enemy", ())
    packets = derive_item_support_effects(
        holder,
        {
            "damage_events": [
                {"time": 0.0, "source_key": "auto_attacks", "damage": 10.0},
                {"time": 1.0, "source_key": "auto_attacks", "damage": 10.0},
            ]
        },
        [holder, target],
    )

    reap = next(packet for packet in packets if packet["source"] == "Cull — Reap")
    assert reap["gold_amount"] == pytest.approx(450.0)
    assert reap["completion_granted"] is True
    atlas_gold = next(
        packet
        for packet in packets
        if packet["source"] == "World Atlas — Shared Riches"
    )
    assert atlas_gold["gold_amount"] == pytest.approx(400.0)
    wards = next(
        packet for packet in packets if packet["source"] == "World Atlas — Ward"
    )
    assert wards["ward_uses"] == pytest.approx(3.0)
    rage = [packet for packet in packets if packet["source"] == "Phage — Rage"]
    assert [packet["time"] for packet in rage] == [0.0, 1.0]
    assert all(
        packet["bonus_move_speed_percent"] == pytest.approx(10.0) for packet in rage
    )


def test_stridebreaker_active_emits_sourced_slow_and_movement_packets():
    """Breaking Shockwave records both utility siblings for each hit target."""
    holder = _actor(
        "main:Ahri",
        "main",
        ("Stridebreaker",),
        item_options={"Stridebreaker": {"active_seconds": 1.5}},
    )
    enemy = _actor("enemy:Annie", "enemy", ())

    packets = derive_item_support_effects(holder, {}, [holder, enemy])

    slow = [p for p in packets if p["kind"] == "slow"]
    movement = [p for p in packets if p["kind"] == "movement"]
    assert len(slow) == 1
    assert slow[0]["target"] == enemy.participant_id
    assert slow[0]["amount"] == pytest.approx(35.0)
    assert slow[0]["duration"] == pytest.approx(3.0)
    assert slow[0]["range_assumption"] == "within_450_units"
    assert slow[0]["cast_geometry"] == "100_unit_front_offset"
    assert len(movement) == 1
    assert movement[0]["target"] == holder.participant_id
    assert movement[0]["bonus_move_speed_percent"] == pytest.approx(35.0)
    assert movement[0]["champion_hit_target"] == enemy.participant_id


def test_cc_only_packets_require_an_authored_immobilize_marker():
    holder = _actor("ally:Lulu", "ally", ("Bandlepipes", "Imperial Mandate"))
    target = _actor("main:Ahri", "main", ())
    enemy = _actor("enemy:Aatrox", "enemy", ())
    no_marker = derive_item_support_effects(
        holder,
        {"damage_events": [{"time": 1.0, "target": "enemy:Aatrox"}]},
        [holder, target, enemy],
    )
    assert no_marker == []

    marked = derive_item_support_effects(
        holder,
        {
            "damage_events": [
                {
                    "time": 1.0,
                    "target": "enemy:Aatrox",
                    "immobilized": True,
                }
            ]
        },
        [holder, target, enemy],
    )
    assert any(p["source"] == "Bandlepipes — Fanfare" for p in marked)
    mandate = next(p for p in marked if p["source"] == "Imperial Mandate — Command")
    assert mandate["multiplier"] == pytest.approx(1.07)
    # The holder's own pair engine prices Command (damage.py); the packet
    # exists for every other participant, so the walk must skip the owner.
    assert mandate["owner"] == holder.participant_id


def test_command_requires_an_immobilize_not_a_slow():
    """Command triggers on the Wiki's immobilize class only — a slow marks
    nothing (unlike Solstice Sleigh, which triggers on slows too)."""
    holder = _actor("ally:Lulu", "ally", ("Imperial Mandate",))
    enemy = _actor("enemy:Aatrox", "enemy", ())
    slowed = derive_item_support_effects(
        holder,
        {"damage_events": [{"time": 1.0, "target": "enemy:Aatrox", "cc_kind": "slow"}]},
        [holder, enemy],
    )
    assert not any(p["source"] == "Imperial Mandate — Command" for p in slowed)
    stunned = derive_item_support_effects(
        holder,
        {"damage_events": [{"time": 1.0, "target": "enemy:Aatrox", "cc_kind": "stun"}]},
        [holder, enemy],
    )
    assert any(p["source"] == "Imperial Mandate — Command" for p in stunned)


def test_sourced_cc_packets_include_holder_movement_and_solstice_both_recipients():
    holder = _actor("ally:Lulu", "ally", ("Bandlepipes", "Solstice Sleigh"))
    target = _actor("main:Ahri", "main", (), level=12)
    enemy = _actor("enemy:Aatrox", "enemy", ())
    packets = derive_item_support_effects(
        holder,
        {
            "damage_events": [
                {
                    "time": 1.0,
                    "target": enemy.participant_id,
                    "cc_kind": "immobilize",
                }
            ]
        },
        [holder, target, enemy],
    )
    fanfare_move = next(
        p
        for p in packets
        if p["source"] == "Bandlepipes — Fanfare" and p["kind"] == "movement"
    )
    assert fanfare_move["target"] == holder.participant_id
    solstice = [p for p in packets if p["source"] == "Solstice Sleigh — Going Sledding"]
    assert {p["target"] for p in solstice} == {
        holder.participant_id,
        target.participant_id,
    }
    assert next(p for p in solstice if p["target"] == target.participant_id)[
        "amount"
    ] == pytest.approx(50.0 + (230.0 - 50.0) * 5.0 / 11.0)


def test_fimbulwinter_everlasting_uses_current_mana_and_nearby_enemy_multiplier():
    holder = _actor("main:Ahri", "main", ("Fimbulwinter",))
    holder.stats.update({"is_melee": True, "max_mana": 1000.0})
    enemy_one = _actor("enemy:Aatrox", "enemy", ())
    enemy_two = _actor("enemy:Galio", "enemy", ())
    packets = derive_item_support_effects(
        holder,
        {
            "cast_timeline": [{"time": 1.0, "resource_after": 900.0}],
            "damage_events": [
                {
                    "time": 1.0,
                    "target": enemy_one.participant_id,
                    "source_key": "E",
                    "ability_instance": "E:1",
                    "cc_kind": "slow",
                },
                {
                    "time": 5.0,
                    "target": enemy_one.participant_id,
                    "source_key": "E",
                    "ability_instance": "E:2",
                    "cc_kind": "slow",
                },
                {
                    "time": 9.0,
                    "target": enemy_one.participant_id,
                    "source_key": "E",
                    "ability_instance": "E:3",
                    "cc_kind": "slow",
                },
            ],
        },
        [holder, enemy_one, enemy_two],
    )

    shields = [p for p in packets if p["source"] == "Fimbulwinter — Everlasting"]
    assert [p["time"] for p in shields] == [pytest.approx(1.0), pytest.approx(9.0)]
    assert shields[0]["current_mana"] == pytest.approx(900.0)
    assert shields[0]["nearby_enemy_count"] == 2
    assert shields[0]["multi_target_multiplier"] == pytest.approx(1.8)
    assert shields[0]["amount"] == pytest.approx((100.0 + 0.045 * 900.0) * 1.8)
    assert shields[0]["duration"] == pytest.approx(3.0)
    assert shields[0]["cooldown_until"] == pytest.approx(9.0)


def test_fimbulwinter_requires_the_correct_melee_or_immobilize_branch():
    ranged = _actor("main:Ahri", "main", ("Fimbulwinter",))
    enemy = _actor("enemy:Aatrox", "enemy", ())
    slow_only = derive_item_support_effects(
        ranged,
        {
            "damage_events": [
                {
                    "time": 1.0,
                    "target": enemy.participant_id,
                    "cc_kind": "slow",
                }
            ]
        },
        [ranged, enemy],
    )
    assert not [p for p in slow_only if p["source"] == "Fimbulwinter — Everlasting"]

    immobilize = derive_item_support_effects(
        ranged,
        {
            "damage_events": [
                {
                    "time": 1.0,
                    "target": enemy.participant_id,
                    "cc_kind": "immobilize",
                }
            ]
        },
        [ranged, enemy],
    )
    shield = next(p for p in immobilize if p["source"] == "Fimbulwinter — Everlasting")
    assert shield["trigger_kind"] == "immobilize"


def test_fimbulwinter_does_not_trigger_at_or_below_the_mana_gate():
    holder = _actor("main:Ahri", "main", ("Fimbulwinter",))
    enemy = _actor("enemy:Aatrox", "enemy", ())
    packets = derive_item_support_effects(
        holder,
        {
            "cast_timeline": [{"time": 1.0, "resource_after": 200.0}],
            "damage_events": [
                {
                    "time": 1.0,
                    "target": enemy.participant_id,
                    "ability_instance": "Q:1",
                    "cc_kind": "immobilize",
                }
            ],
        },
        [holder, enemy],
    )
    assert not [p for p in packets if p["source"] == "Fimbulwinter — Everlasting"]


def test_cross_participant_debuffs_are_typed_and_triggered_by_holder_packets():
    holder = _actor(
        "ally:Lulu",
        "ally",
        ("Abyssal Mask", "Black Cleaver", "Bloodletter's Curse", "Bloodsong"),
    )
    enemy = _actor("enemy:Aatrox", "enemy", ())
    damage = [
        {
            "time": 0.0,
            "target": enemy.participant_id,
            "damage": 10.0,
            "damage_type": "physical",
            "source_key": "auto_attacks",
            "is_ability": False,
        },
        {
            "time": 1.5,
            "target": enemy.participant_id,
            "damage": 10.0,
            "damage_type": "physical",
            "source_key": "spellblade_Bloodsong",
            "is_ability": False,
            "_event_id": "holder:spellblade",
        },
        {
            "time": 2.0,
            "target": enemy.participant_id,
            "damage": 10.0,
            "damage_type": "magic",
            "source_key": "Q",
            "is_ability": True,
        },
    ]
    packets = derive_item_support_effects(
        holder, {"damage_events": damage}, [holder, enemy]
    )
    sources = {p["source"] for p in packets}
    assert "Abyssal Mask — Unmake" in sources
    assert "Bloodsong — Expose Weakness" in sources
    assert "Black Cleaver — Carve" in sources
    assert "Bloodletter's Curse — Vile Decay" in sources
    carve = next(p for p in packets if p["source"] == "Black Cleaver — Carve")
    assert carve["armor_reduction_percent"] == pytest.approx(0.06)
    vile = next(p for p in packets if p["source"] == "Bloodletter's Curse — Vile Decay")
    assert vile["mr_reduction_percent"] == pytest.approx(0.075)


def test_knights_vow_attaches_typed_redirect_and_holder_heal_receipts():
    holder = _actor(
        "ally:Lulu",
        "ally",
        ("Knight's Vow",),
        item_options={"Knight's Vow": {"worthy_target_index": 0}},
    )
    worthy = _actor("main:Ahri", "main", ())
    enemy = _actor("enemy:Aatrox", "enemy", ())
    incoming = {
        worthy.participant_id: [
            {
                "time": 1.0,
                "attacker": enemy.participant_id,
                "target": worthy.participant_id,
                "damage": 100.0,
                "damage_type": "physical",
            }
        ]
    }
    outgoing = {
        worthy.participant_id: [
            {
                "time": 1.0,
                "attacker": worthy.participant_id,
                "target": enemy.participant_id,
                "damage": 200.0,
                "damage_type": "physical",
            }
        ]
    }
    support = defaultdict(list)

    schedule_knights_vow([holder, worthy, enemy], incoming, outgoing, support)

    assert incoming[worthy.participant_id][0]["redirect_fraction"] == pytest.approx(
        0.14
    )
    assert (
        incoming[worthy.participant_id][0]["redirect_target"] == holder.participant_id
    )
    assert incoming[worthy.participant_id][0]["redirect_source"] == (
        "Knight's Vow — Sacrifice"
    )
    heal = next(p for p in support[holder.participant_id] if p["kind"] == "heal")
    assert heal["target"] == holder.participant_id
    assert heal["amount"] == pytest.approx(24.0)
