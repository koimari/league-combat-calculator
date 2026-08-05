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
        stats={"mana": 1000.0, "is_melee": False},
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
