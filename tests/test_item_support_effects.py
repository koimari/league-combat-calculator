"""Typed cross-participant item packets and explicit trigger contracts."""

import ast
import re
from collections import Counter, defaultdict
from contextlib import contextmanager
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import get_args, get_type_hints

import pytest

from src.app import app
from src.calculator import item_behavior_catalog as catalog
from src.calculator import (
    item_support_effects,
    ledger_projection,
    pipeline,
    trigger_stream,
)
from src.calculator.ability_spec import AttackClass, Authority, DamageClass
from src.calculator.data_fetcher import get_item_by_name
from src.calculator.item_behavior import PacketKind, Persistence
from src.calculator.item_effects import (
    ITEM_EFFECTS,
    ally_item_effect_value,
    ally_item_level_value,
)
from src.calculator.item_source import effect_entries, effect_text
from src.calculator.item_support_effects import (
    _declared_authorities,
    derive_item_support_effects,
    producer_item,
    schedule_knights_vow,
)
from src.calculator.program.views import ViewTag
from src.calculator.roster_composition import ActorRequest
from src.calculator.trigger_stream import CAPABILITIES

pytestmark = pytest.mark.usefixtures("authorized_fimbulwinter_mana_gate")


def _capability(mechanic: str, packet_source: str):
    """A synthetic seventh cross-participant producer, declared."""
    return trigger_stream.MechanicCapability(
        mechanic=mechanic,
        owner=trigger_stream.ItemOwner("Synthetic Seventh"),
        engine=trigger_stream.Engine.WALK,
        reads=frozenset(),
        needs=frozenset(),
        authority=Authority.COUPLED_ONLY,
        pairing=trigger_stream.Pairing.SOLO,
        pair_of=None,
        divergence_ref=None,
        impl="item_support_effects.derive_item_support_effects",
        packet_source=packet_source,
        view_tags=MappingProxyType({trigger_stream.Engine.WALK: ViewTag.APPLIED}),
        holder_stacking=None,
    )


@contextmanager
def _grown_registry(mechanic: str, capability):
    """Read the producer table off a registry carrying one more capability.

    P2c moved the table off this module's own ``_packet`` call sites and
    onto ``trigger_stream.CAPABILITIES``, so a seventh producer is now
    expressed as a declaration rather than as source text — which is the
    only way to test that the table follows the registry.
    """
    grown = MappingProxyType({**CAPABILITIES, mechanic: capability})
    item_support_effects.CAPABILITIES = grown
    item_support_effects._declared_authorities.cache_clear()
    try:
        yield grown
    finally:
        item_support_effects.CAPABILITIES = CAPABILITIES
        item_support_effects._declared_authorities.cache_clear()


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
        request=ActorRequest(
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
    # "{{pp|50 to 230 for 13|1;7 to 18|type=your level}}": Going Sledding's
    # ramp is the *holder's* level, so the level-12 ally receives the same
    # bonus health the level-18 holder does.  The emitter used to read each
    # recipient's own level and hand the ally 131.8.
    assert [p["amount"] for p in solstice] == pytest.approx([230.0, 230.0])


def test_fimbulwinter_everlasting_withholds_unspecified_nearby_enemy_multiplier():
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

    shields = [
        p
        for p in packets
        if p["source"] == "Fimbulwinter — Everlasting" and p["kind"] == "shield"
    ]
    assert [p["time"] for p in shields] == [pytest.approx(1.0), pytest.approx(9.0)]
    assert shields[0]["current_mana"] == pytest.approx(900.0)
    assert shields[0]["nearby_enemy_count"] is None
    assert shields[0]["nearby_enemy_range_units"] == pytest.approx(1200.0)
    assert shields[0]["range_input_status"] == "spatial_input_unavailable"
    assert shields[0]["multi_target_multiplier"] == pytest.approx(1.0)
    assert shields[0]["amount"] == pytest.approx(100.0 + 0.045 * 900.0)
    assert shields[0]["duration"] == pytest.approx(3.0)
    assert shields[0]["cooldown_until"] == pytest.approx(9.0)
    # Accepted base shields report the unavailable spatial multiplier.  The
    # in-flight t=5 trigger remains a named cooldown denial.
    denials = [
        p
        for p in packets
        if p["source"] == "Fimbulwinter — Everlasting" and p["kind"] == "item_denial"
    ]
    assert [(p["time"], p["reason"]) for p in denials] == [
        (pytest.approx(1.0), "nearby_enemy_spatial_input_unavailable"),
        (pytest.approx(5.0), "cooldown"),
        (pytest.approx(9.0), "nearby_enemy_spatial_input_unavailable"),
    ]


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
    # No shield for the ranged slow; the rejection is now a NAMED receipt.
    assert not [
        p
        for p in slow_only
        if p["source"] == "Fimbulwinter — Everlasting" and p["kind"] == "shield"
    ]
    denials = [
        p
        for p in slow_only
        if p["source"] == "Fimbulwinter — Everlasting" and p["kind"] == "item_denial"
    ]
    assert [(p["reason"], p["time"]) for p in denials] == [
        ("ranged_slow", pytest.approx(1.0))
    ]

    immobilize = derive_item_support_effects(
        ranged,
        {
            "damage_events": [
                {
                    "time": 1.0,
                    "target": enemy.participant_id,
                    "ability_instance": "Q:1",
                    "cc_kind": "immobilize",
                }
            ]
        },
        [ranged, enemy],
    )
    shield = next(
        p
        for p in immobilize
        if p["source"] == "Fimbulwinter — Everlasting" and p["kind"] == "shield"
    )
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
    assert not [
        p
        for p in packets
        if p["source"] == "Fimbulwinter — Everlasting" and p["kind"] == "shield"
    ]
    # The mana-gate rejection is now a NAMED receipt (exact 20% boundary).
    denials = [
        p
        for p in packets
        if p["source"] == "Fimbulwinter — Everlasting" and p["kind"] == "item_denial"
    ]
    assert [(p["reason"], p["time"]) for p in denials] == [
        ("mana_gate", pytest.approx(1.0))
    ]


def test_fimbulwinter_control_only_packets_arm_the_shield():
    """Control-ONLY CC events (Darius E / Elise E style) arm Everlasting.

    The trigger scan reads both the damage stream and the ``control_events``
    stream; the same control packet is never double-fired when the coupled
    pair enrichment merged it into the per-event view.
    """
    holder = _actor("main:Ahri", "main", ("Fimbulwinter",))
    holder.stats.update({"is_melee": True})
    enemy = _actor("enemy:Aatrox", "enemy", ())
    packets = derive_item_support_effects(
        holder,
        {
            "cast_timeline": [{"time": 1.0, "resource_after": 900.0}],
            "control_events": [
                {
                    "time": 1.0,
                    "target": enemy.participant_id,
                    "source_key": "E",
                    "ability_instance": "E:1",
                    "cc_kind": "airborne",
                    "damage": 0.0,
                }
            ],
        },
        [holder, enemy],
    )
    shields = [
        p
        for p in packets
        if p["source"] == "Fimbulwinter — Everlasting" and p["kind"] == "shield"
    ]
    assert len(shields) == 1
    assert shields[0]["trigger_kind"] == "immobilize"
    assert shields[0]["time"] == pytest.approx(1.0)


def test_fimbulwinter_same_control_packet_in_both_streams_fires_once():
    """The damage/control stream dedupe keeps exactly one copy per packet.

    The coupled pair enrichment merges control-only rows into the per-event
    view, so a control packet present in BOTH streams must arm the shield
    once and produce exactly one denial-free shield (no spurious
    duplicate_instance receipts).
    """
    holder = _actor("main:Ahri", "main", ("Fimbulwinter",))
    holder.stats.update({"is_melee": True})
    enemy = _actor("enemy:Aatrox", "enemy", ())
    control = {
        "time": 1.0,
        "target": enemy.participant_id,
        "source_key": "E",
        "ability_instance": "E:1",
        "cc_kind": "immobilize",
        "damage": 0.0,
    }
    packets = derive_item_support_effects(
        holder,
        {
            "cast_timeline": [{"time": 1.0, "resource_after": 900.0}],
            "damage_events": [dict(control)],
            "control_events": [dict(control)],
        },
        [holder, enemy],
    )
    shields = [
        p
        for p in packets
        if p["source"] == "Fimbulwinter — Everlasting" and p["kind"] == "shield"
    ]
    assert len(shields) == 1
    denials = [
        p
        for p in packets
        if p["source"] == "Fimbulwinter — Everlasting" and p["kind"] == "item_denial"
    ]
    assert [row["reason"] for row in denials] == [
        "nearby_enemy_spatial_input_unavailable"
    ]


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


def _damage_modifier_call_sites() -> dict[str, str]:
    """Every ``kind="damage_modifier"`` ``_packet`` site's source and authority.

    The static half of the binding P2c installs: the module used to *derive*
    its authority table from these call sites, and now the table is
    ``trigger_stream.CAPABILITIES`` and these call sites are checked against
    it.  Returns ``{source literal: Authority member name}``; a site naming
    neither literally is a failure here rather than a hole in the table.
    """
    body = Path(item_support_effects.__file__).read_text(encoding="utf-8")
    declared: dict[str, str] = {}
    for node in ast.walk(ast.parse(body)):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_packet"
        ):
            continue
        kind = _packet_keyword(node, "kind")
        if not _is_packet_kind_node(kind, "damage_modifier"):
            continue
        source = _packet_keyword(node, "source")
        no_literal = (
            f"the damage_modifier packet at line {node.lineno} names no literal "
            "source; the registry cannot be checked against an expression"
        )
        assert isinstance(source, ast.Constant), no_literal
        assert isinstance(source.value, str), no_literal
        authority = _packet_keyword(node, "authority")
        no_member = (
            f"{source.value} declares no literal Authority.<member> at line "
            f"{node.lineno}; one of "
            f"{sorted(member.value for member in Authority)} is required (D-07)"
        )
        assert isinstance(authority, ast.Attribute), no_member
        assert isinstance(authority.value, ast.Name), no_member
        assert authority.value.id == "Authority", no_member
        assert authority.attr in Authority.__members__, no_member
        declared[source.value] = authority.attr
    return declared


class TestCrossParticipantAuthorities:
    """One authority table, and the packets are bound to it."""

    def test_every_damage_modifier_packet_is_a_row(self):
        """One row per ``kind=PacketKind.DAMAGE_MODIFIER`` construction site."""
        body = Path(item_support_effects.__file__).read_text(encoding="utf-8")
        call_sites = len(
            re.findall(
                r"^\s*kind=PacketKind\.DAMAGE_MODIFIER\.value,$",
                body,
                flags=re.MULTILINE,
            )
        )
        assert call_sites == len(_declared_authorities())

    def test_dream_maker_is_a_producer(self):
        """The sixth producer sets no ``all_sources`` flag and is in anyway."""
        assert "Dream Maker — Blue Dream Bubble" in _declared_authorities()

    def test_every_producer_declares_one_of_the_five_members(self):
        """C2 fills the values: no producer is left without an owning engine."""
        declared = _declared_authorities()
        assert declared
        assert all(isinstance(value, Authority) for value in declared.values())

    def test_the_row_type_names_the_declared_vocabulary(self):
        """The value is an ``Authority``, with no undeclared spelling left."""
        hints = get_type_hints(_declared_authorities)
        key, value = get_args(hints["return"])
        assert key is str
        assert value is Authority

    def test_every_call_site_declares_what_the_registry_declares(self):
        """The construction sites and ``CAPABILITIES`` cannot drift apart.

        This is the static half of the check ``_check_cross_participant_
        authority`` runs per packet: every site names a literal source that
        the registry knows and a literal ``Authority`` member equal to the
        one the registry gives it.
        """
        table = _declared_authorities()
        sites = _damage_modifier_call_sites()
        assert sites
        for source, member in sites.items():
            assert source in table, (
                f"{source!r} is built as a damage_modifier packet but no "
                "capability declares it as a packet_source"
            )
            assert table[source] is Authority[member]
        assert frozenset(sites) == frozenset(table)

    def test_a_new_producer_joins_without_editing_a_list(self):
        """A seventh producer is a row the moment its capability parses."""
        seventh = _capability("synthetic.seventh", "Synthetic — Seventh")
        with _grown_registry("synthetic.seventh", seventh):
            assert (
                _declared_authorities()["Synthetic — Seventh"] is Authority.COUPLED_ONLY
            )

    def test_an_undeclared_producer_fails_on_its_first_packet(self):
        """The declaration is required, so a silent seventh cannot exist."""
        with pytest.raises(ValueError, match="Synthetic — Undeclared"):
            item_support_effects._packet(
                attacker=_actor("main:Annie", "main", ()),
                target=_actor("enemy:Aatrox", "enemy", ()),
                time=0.0,
                kind="damage_modifier",
                source="Synthetic — Undeclared",
                authority=Authority.COUPLED_ONLY,
                damage_classes=frozenset({DamageClass.MAGIC}),
                attack_classes=frozenset(AttackClass),
            )

    def test_a_call_site_may_not_disagree_with_the_declaration(self):
        """One mechanic has one owning engine, and the registry states it."""
        with pytest.raises(ValueError, match="declares SPLIT"):
            item_support_effects._packet(
                attacker=_actor("main:Annie", "main", ()),
                target=_actor("enemy:Aatrox", "enemy", ()),
                time=0.0,
                kind="damage_modifier",
                source="Abyssal Mask — Unmake",
                authority=Authority.COUPLED_ONLY,
                damage_classes=frozenset({DamageClass.MAGIC}),
                attack_classes=frozenset(AttackClass),
            )

    def test_no_hand_written_producer_list_exists(self):
        """A source assertion against the second home the derivation retires."""
        body = Path(item_support_effects.__file__).read_text(encoding="utf-8")
        derivation = body.split("def _declared_authorities")[1].split(
            "def _check_cross_participant_authority"
        )[0]
        for source in _declared_authorities():
            assert source not in derivation, (
                f"{source!r} is spelled inside the producer-table derivation; "
                "the table must be read from the capability registry"
            )

    def test_producer_item_names_the_item_a_scenario_must_equip(self):
        assert producer_item("Imperial Mandate — Command") == "Imperial Mandate"
        assert producer_item("Bloodletter's Curse — Vile Decay") == (
            "Bloodletter's Curse"
        )


# One Abyssal holder, one ally to price and one cursed enemy — the shape the
# coupled baseline's ``mandate_abyssal_curse_roster`` scenario uses, reduced to
# the one item these slices move.  The ally is an Ahri rather than the
# baseline's Pantheon because C3 types the curse: Pantheon's only damage into
# the cursed enemy after the arming timestamp is physical, so with a magic-only
# Unmake his rows carry no multiplier at all and the roster could no longer show
# an amped ally.  Ahri's Q lands magic *and* true damage into the same enemy at
# the same instant, which is the whole of C3 in one packet pair.
_ABYSSAL_ROSTER = {
    "champion": "Ahri",
    "level": 18,
    "items": ["Abyssal Mask"],
    "fight_mode": "time_based",
    "fight_duration": 8,
    "enemies": [{"champion": "Aatrox", "level": 18, "items": []}],
    "allies": [
        {
            "champion": "Ahri",
            "level": 18,
            "items": [],
            "ally_effects_enabled": True,
        }
    ],
}


class TestOwnerIsPresentIffSplit:
    """C2's machine check: the semantic decides, never the ``all_sources`` flag."""

    def _modifier(self, **overrides):
        holder = _actor("main", "main", ())
        enemy = _actor("enemy:Aatrox", "enemy", ())
        fields = {
            "attacker": holder,
            "target": enemy,
            "time": 0.0,
            "kind": "damage_modifier",
            "source": "Abyssal Mask — Unmake",
            "authority": Authority.SPLIT,
            "owner": holder.participant_id,
            "damage_classes": frozenset({DamageClass.MAGIC}),
            "attack_classes": frozenset(AttackClass),
        }
        fields.update(overrides)
        return item_support_effects._packet(**fields)

    def test_a_split_packet_carries_its_owner(self):
        assert self._modifier()["owner"] == "main"

    def test_a_split_packet_without_an_owner_raises(self):
        with pytest.raises(ValueError, match="declares SPLIT and carries no owner"):
            self._modifier(owner=None)

    def test_the_check_ignores_all_sources(self):
        """Criterion 9: ``all_sources=False`` does not excuse a missing owner."""
        with pytest.raises(ValueError, match="declares SPLIT and carries no owner"):
            self._modifier(owner=None, all_sources=False)

    def test_a_coupled_only_packet_may_not_carry_an_owner(self):
        with pytest.raises(ValueError, match="only SPLIT has a pair-side half"):
            self._modifier(
                source="Dream Maker — Blue Dream Bubble",
                authority=Authority.COUPLED_ONLY,
            )

    def test_a_packet_declaring_no_authority_raises(self):
        with pytest.raises(ValueError, match="names no Authority"):
            self._modifier(source="Synthetic — Unknown", authority=None, owner=None)

    def test_the_runtime_declaration_must_match_the_call_site(self):
        with pytest.raises(ValueError, match="but its packet declares SPLIT"):
            self._modifier(authority=Authority.COUPLED_AUTHORITATIVE)

    def test_a_non_modifier_packet_is_unaffected(self):
        """The check is scoped to the packets that reach another participant."""
        packet = self._modifier(kind="shield", authority=None, owner=None)
        assert packet["kind"] == "shield"

    def test_the_declaration_never_reaches_the_packet_payload(self):
        """R-17: a semantic commit may not move a serialized receipt's shape."""
        assert "authority" not in self._modifier()


def _is_packet_kind_node(node, kind: str) -> bool:
    """Whether a ``_packet(kind=...)`` node names ``PacketKind.<KIND>.value``.

    The kind used to be a bare string literal at every site; ER1 moved it
    onto the enum, so the three source walks below ask this one question
    instead of each matching a spelling.
    """
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "value"
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == kind.upper()
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "PacketKind"
    )


def _packet_keyword(call, name):
    """The value node of one keyword argument of a ``_packet(...)`` call.

    Moved out of ``item_support_effects`` at P2c.  The module used to walk
    its own source to derive an authority table; ``CAPABILITIES`` is that
    table now, so the walk over its construction sites is purely a
    test-side source assertion and lives with the assertions.
    """
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def declared_packet_keywords(*names):
    """Each ``damage_modifier`` call site's declared keywords, by source.

    Read from the construction sites and evaluated in the module's own
    namespace, so the test sees the declaration a reader sees rather than a
    packet a fixture happened to build.  A keyword the call site does not
    pass comes back ``None`` — absent and defaulted are the same thing to
    ``_packet`` and the caller decides what that means.

    Public, and the one AST walk over those call sites: the Phase 0
    sentinels in ``test_phase0_sentinels`` read the same declarations (their
    class sets and their expiries), and a second walk would be a second home
    for one fact.
    """
    module_source = Path(item_support_effects.__file__).read_text(encoding="utf-8")
    declared = {}
    for node in ast.walk(ast.parse(module_source)):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_packet"
        ):
            continue
        kind = _packet_keyword(node, "kind")
        if not _is_packet_kind_node(kind, "damage_modifier"):
            continue
        source = _packet_keyword(node, "source").value
        declared[source] = {
            name: _evaluate_declaration(_packet_keyword(node, name)) for name in names
        }
    return declared


def _evaluate_declaration(expression):
    """One declared keyword's value, or ``None`` when the site omits it."""
    if expression is None:
        return None
    return eval(  # noqa: S307 - evaluates the module's own declaration AST  # pylint: disable=eval-used
        compile(ast.Expression(expression), "<declaration>", "eval"),
        vars(item_support_effects),
    )


def declared_classes_by_producer():
    """Each ``damage_modifier`` call site's declared class sets, by source."""
    return declared_packet_keywords("damage_classes", "attack_classes")


def timed_cross_participant_producers():
    """Every ``damage_modifier`` producer whose declaration carries an expiry.

    Read from the Phase 3 declarations rather than from the ``duration=``
    expression at the call site: 3.6 moved the number behind the producer's
    own reference, so "does this modifier close" is now a declared axis
    (``Persistence``) instead of something a reader infers from whether one
    keyword happens to be passed.  The source literal comes back through the
    mechanic's capability, which is the one home for "which packet does this
    producer emit".
    """
    sources = set()
    for producer, declaration in catalog.ALLY_PACKET_DECLARATIONS.items():
        if declaration.persistence is not Persistence.TIMED_WINDOW:
            continue
        if not any(
            spec.kind is PacketKind.DAMAGE_MODIFIER for spec in declaration.packets
        ):
            continue
        for owner in catalog.owners_for(producer):
            mechanic = f"{catalog._mechanic_slug(owner)}.{producer.value}"
            sources.add(trigger_stream.CAPABILITIES[mechanic].packet_source)
    return sources


class TestDeclaredDamageAndAttackClasses:
    """C3's half of the same construction site: what a modifier applies to (D-04)."""

    def _modifier(self, **overrides):
        holder = _actor("main", "main", ())
        enemy = _actor("enemy:Aatrox", "enemy", ())
        fields = {
            "attacker": holder,
            "target": enemy,
            "time": 0.0,
            "kind": "damage_modifier",
            "source": "Abyssal Mask — Unmake",
            "authority": Authority.SPLIT,
            "owner": holder.participant_id,
            "damage_classes": frozenset({DamageClass.MAGIC}),
            "attack_classes": frozenset(AttackClass),
        }
        fields.update(overrides)
        return item_support_effects._packet(**fields)

    def test_the_declaration_reaches_the_packet(self):
        """Unlike ``authority``, the walk reads these per packet."""
        packet = self._modifier()
        assert packet["damage_classes"] == frozenset({DamageClass.MAGIC})
        assert packet["attack_classes"] == frozenset(AttackClass)

    @pytest.mark.parametrize("axis", ["damage_classes", "attack_classes"])
    def test_an_absent_declaration_raises(self, axis):
        with pytest.raises(ValueError, match=f"declares no {axis}"):
            self._modifier(**{axis: None})

    @pytest.mark.parametrize("axis", ["damage_classes", "attack_classes"])
    def test_an_empty_declaration_raises(self, axis):
        """Empty-means-all is banned: the ban is what makes the field required."""
        with pytest.raises(ValueError, match="empty-means-all is banned"):
            self._modifier(**{axis: frozenset()})

    def test_a_declaration_of_the_wrong_vocabulary_raises(self):
        with pytest.raises(ValueError, match="other than DamageClass members"):
            self._modifier(damage_classes=frozenset({"magic"}))

    def test_a_non_modifier_packet_needs_no_declaration(self):
        packet = self._modifier(
            kind="shield",
            authority=None,
            owner=None,
            damage_classes=None,
            attack_classes=None,
        )
        assert "damage_classes" not in packet

    def test_every_producer_declares_both_axes_at_its_call_site(self):
        """A seventh producer cannot ship undeclared even if it never runs.

        The runtime check in ``_packet`` only fires on a packet that is
        built; this reads the construction sites themselves, so a branch no
        fixture reaches still has to name both axes.
        """
        tree = ast.parse(
            Path(item_support_effects.__file__).read_text(encoding="utf-8")
        )
        sites = []
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "_packet"
            ):
                continue
            kind = _packet_keyword(node, "kind")
            if _is_packet_kind_node(kind, "damage_modifier"):
                sites.append(node)
        assert len(sites) == len(_declared_authorities())
        for node in sites:
            for axis in ("damage_classes", "attack_classes"):
                assert (
                    _packet_keyword(node, axis) is not None
                ), f"line {node.lineno} declares no {axis}"

    def test_the_declarations_agree_with_the_cached_wiki_text(self):
        """Every restriction is read off the cached entry, never assumed.

        The two axes read different phrases, which is the whole of D-04:
        "from all sources" says nothing about damage class — Unmake says it
        while restricting to magic — so it is the *attack* axis that phrase
        settles, and the damage axis is settled by the class or the
        resistance the text names.  The text comes from
        ``item_source.effect_text`` — every branch of the entry — as repo
        rule 6 requires.
        """
        damage_axis_phrases = {
            "increased magic damage": frozenset({DamageClass.MAGIC}),
            "armor reduction": frozenset({DamageClass.PHYSICAL}),
            "magic resistance reduction": frozenset({DamageClass.MAGIC}),
        }
        for source, declared in declared_classes_by_producer().items():
            item = get_item_by_name(producer_item(source))
            effect = source.split(" — ", 1)[1]
            # Two effects are named inside a larger passive rather than by
            # it: Expose Weakness lives in Bloodsong's Spellblade and the
            # Blue Bubble in Dream Maker's own passive, so the entry is the
            # one that names the effect, by title or in its text.
            text = next(
                effect_text(entry)
                for _kind, entry in effect_entries(item)
                if str(entry.get("name", "")) == effect or effect in effect_text(entry)
            )
            if "from all sources" in text:
                assert declared["attack_classes"] == frozenset(AttackClass), source
            if "attack or spell" in text:
                assert AttackClass.OTHER not in declared["attack_classes"], source
            named = [
                classes
                for phrase, classes in damage_axis_phrases.items()
                if phrase in text
            ]
            assert declared["damage_classes"] == (
                named[0] if named else frozenset(DamageClass)
            ), source

    def test_blue_dream_bubble_is_the_one_producer_restricted_to_attacks(self):
        """Its text says "the next attack or spell", and only its does."""
        declared = declared_classes_by_producer()
        narrow = {
            source
            for source, sets in declared.items()
            if sets["attack_classes"] != frozenset(AttackClass)
        }
        assert narrow == {"Dream Maker — Blue Dream Bubble"}
        assert declared["Dream Maker — Blue Dream Bubble"]["attack_classes"] == (
            frozenset({AttackClass.BASIC_ATTACK, AttackClass.ABILITY})
        )


class TestDreamMakerIsCoupledOnly:
    """The sixth producer has no pair-side half, so it declares no owner."""

    def test_blue_dream_bubble_declares_coupled_only(self):
        assert (
            _declared_authorities()["Dream Maker — Blue Dream Bubble"]
            is Authority.COUPLED_ONLY
        )

    def test_no_pair_engine_pricer_for_blue_dream_bubble_exists(self):
        """The declaration cannot silently become wrong (criterion 10).

        ``ITEM_EFFECTS`` is the typed registry the pair engine's build
        projection reads: an entry there is what "the pair engine prices this"
        means.  Abyssal Mask is the positive control — it is ``SPLIT``
        precisely because it *has* such an entry — so a registry that stopped
        being the pricer's source would fail this test rather than pass it
        vacuously.
        """
        assert ITEM_EFFECTS["Abyssal Mask"]["type"] == "magic_damage_amp"
        assert "Dream Maker" not in ITEM_EFFECTS

    def test_only_the_coupled_producer_reads_the_blue_bubble_values(self):
        """A second reader would be a pair-side half arriving unannounced.

        Three names, not two, since 3.6: the catalog's ally-packet shape table
        *names* the bubble's keys, because naming a record's value keys is how
        a producer is identified without spelling its item.  That is a
        declarative home — it reads no number and prices nothing — and the
        claim this test makes is about pricers.
        """
        registry = Path(item_support_effects.__file__).parent
        readers = {
            path.name
            for path in registry.rglob("*.py")
            if "blue_reduction" in path.read_text(encoding="utf-8")
        }
        assert readers == {
            "item_behavior_catalog.py",
            "item_effects.py",
            "item_support_effects.py",
        }


class TestAbyssalMaskOwnerHandshake:
    """C2: the pair engine keeps ``magic_amp``; the walk stops re-amping the holder."""

    def _packets(self):
        holder = _actor("main", "main", ("Abyssal Mask",))
        enemy = _actor("enemy:Aatrox", "enemy", ())
        packets = derive_item_support_effects(holder, {}, [holder, enemy])
        return [
            packet for packet in packets if packet["source"] == "Abyssal Mask — Unmake"
        ]

    def test_unmake_declares_split(self):
        assert _declared_authorities()["Abyssal Mask — Unmake"] is Authority.SPLIT

    def test_the_walk_is_told_to_skip_the_holder(self):
        packets = self._packets()
        assert packets
        assert all(packet["owner"] == "main" for packet in packets)

    def test_the_pair_engine_keeps_its_own_amp(self):
        """Golden pins the pair half, so C2 removes the duplicate, not the amp."""
        assert ITEM_EFFECTS["Abyssal Mask"]["magic_amp"] == pytest.approx(
            ally_item_effect_value("Abyssal Mask", "magic_damage_amp")
        )

    def test_the_walk_amps_an_ally_and_no_longer_amps_the_holder(self):
        """The end-to-end shape: 1.12 squared on the holder becomes 1.12 once.

        The pair engine's ``magic_amp`` is invisible in this receipt — it is
        already inside every one of the holder's own damage numbers — so the
        observable is that no Unmake multiplier is *also* recorded against the
        holder, while an ally's damage into the same cursed enemy still
        carries one.
        """
        response = app.test_client().post("/api/calculate", json=_ABYSSAL_ROSTER)
        assert response.status_code == 200
        events = response.get_json()["combat"]["events"]
        amped = {
            event["attacker"]
            for event in events
            if (event.get("support_damage_multiplier") or {}).get("source")
            == "Abyssal Mask — Unmake"
        }
        assert amped == {"ally:Ahri"}
        assert any(
            event["attacker"] == "main" and event["target"] == "enemy:Aatrox"
            for event in events
        )

    def test_the_curse_amps_the_ally_s_magic_and_not_her_true_damage(self):
        """C3's correction end to end: one class in, two classes out.

        The ally's Q lands a magic and a true packet into the cursed enemy
        at one timestamp.  Unmake reads "12% increased *magic* damage from
        all sources", so exactly one of them carries the multiplier — while
        the untyped walk multiplied both.

        Every packet is read, the opening exchange included.  C3 wrote this
        test reading only ``t > 0`` because the curse then armed at
        ``DEBUFF_ARM`` and missed the packets at its own timestamp; C4 moved
        it to ``AURA_ARM``, so the restriction has nothing left to exclude
        and keeping it would hide the class rule on exactly the exchange
        that used to have no rule at all.
        """
        response = app.test_client().post("/api/calculate", json=_ABYSSAL_ROSTER)
        assert response.status_code == 200
        by_type = defaultdict(set)
        for event in response.get_json()["combat"]["events"]:
            if event["attacker"] != "ally:Ahri" or event["target"] != "enemy:Aatrox":
                continue
            source = (event.get("support_damage_multiplier") or {}).get("source")
            by_type[event["damage_type"]].add(source == "Abyssal Mask — Unmake")
        assert by_type["magic"] == {True}
        assert by_type["true"] == {False}


class TestEventViewTupleGate:
    """One predicate answers the tuple question on both paths (D-01)."""

    def test_the_pipeline_tuple_gate_consults_the_event_view_predicate(self):
        """The score-only gate and the enriched-view gate name one predicate.

        P2b re-pointed that predicate at its derivation: the gate reads
        ``tuple_incapable_items()``, whose membership is pinned item for
        item in ``tests/test_trigger_stream.py``.  It was asserted equal to
        the hand set ``EVENT_VIEW_SUPPORT_ITEMS`` until P2c deleted that set
        (D-98's flip).

        Phase 4's S5 moved the *site*, not the claim: the clause is now the
        ``RAW_ROW_STREAM_HOLDER`` adequacy condition, so ``pipeline`` holds no
        clause of its own and the derivation is read from one probe.  The
        pre-correction spelling stays forbidden in both files.
        """
        pipeline_body = Path(pipeline.__file__).read_text(encoding="utf-8")
        projection_body = Path(ledger_projection.__file__).read_text(encoding="utf-8")

        assert "holders_in" not in pipeline_body
        assert "tuple_incapable_items" not in pipeline_body
        assert "return _held(inputs.item_names, tuple_incapable_items())" in (
            projection_body
        )
        assert "has_event_scan_support_items" not in pipeline_body
        assert "has_event_scan_support_items" not in projection_body

    def test_the_scan_predicate_is_gone_from_src_entirely(self):
        """C1 left the callable with no callers; P2c deleted it.

        The stronger form of the claim: not "no caller" but "no symbol",
        checked over the whole package rather than over call nodes.
        """
        retired = frozenset(
            {
                "has_event_scan_support_items",
                "has_takedown_scan_support_items",
                "has_event_view_support_items",
                "EVENT_SCAN_SUPPORT_ITEMS",
                "TAKEDOWN_SCAN_SUPPORT_ITEMS",
                "CC_TRIGGER_ITEMS",
                "DAMAGE_TRIGGER_ITEMS",
                "EVENT_VIEW_SUPPORT_ITEMS",
            }
        )
        sites = []
        for module in (Path(pipeline.__file__).parent).rglob("*.py"):
            tree = ast.parse(module.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                name = ""
                if isinstance(node, ast.Name):
                    name = node.id
                elif isinstance(node, ast.Attribute):
                    name = node.attr
                elif isinstance(node, ast.alias):
                    name = node.name
                if name in retired:
                    sites.append(f"{module.name}:{node.lineno}")
        assert sites == []

    def test_solstice_sleigh_enters_by_derivation(self):
        """D-02: it is a crowd-control reader, so the projection holds it."""
        sleigh = trigger_stream.CAPABILITIES["solstice_sleigh.going_sledding"]
        assert trigger_stream.Stream.CC in sleigh.reads
        assert "Solstice Sleigh" in trigger_stream.tuple_incapable_items()
        # ...and health regen is not why it is protected: the reason is the
        # declaration above, which is what D-02 asked the test to pin.
        assert trigger_stream.holders_in(
            [{"name": "Solstice Sleigh"}], trigger_stream.tuple_incapable_items()
        )

    def test_fimbulwinter_is_an_event_view_member_that_reads_event_id(self):
        """D-03: dropping it disarms a fail-closed raise downstream."""
        assert "Fimbulwinter" in trigger_stream.enriched_view_items()
        body = Path(item_support_effects.__file__).read_text(encoding="utf-8")
        # 3.6 replaced the item-name guard with the declared producer; the
        # branch is found by the declaration it now reads rather than by the
        # name it used to spell.
        everlasting = body.split("if everlasting is not None:")[1].split("\n    if ")[0]
        # The claim is unchanged — the shield carries its trigger's event id,
        # and an unenriched shield carries an absent link rather than an empty
        # one.  The read is off the raw row again: the kernel trigger rule
        # this branch now uses also receipts the rows the bus does not carry
        # (untyped and unknown CC), and a denial must name the row it refused.
        assert '_trigger_event_id=event.get("_event_id")' in everlasting

    def test_every_event_view_holder_is_named_by_exactly_one_stream(self):
        """The registry is the map's one home, so neither can drift.

        The claim used to be checked against ``EVENT_VIEW_STREAMS``, the
        hand map P2c deleted; it is now read straight off the capability
        declarations, which is where "which holders read which stream" now
        lives and the only place it does.
        """
        holders = trigger_stream.tuple_incapable_items()
        pairs = item_support_effects._starved_streams(holders)
        assert frozenset(item for item, _ in pairs) == holders
        counted = Counter(item for item, _ in pairs)
        assert max(counted.values()) == 1, f"reads more than one stream: {counted}"
        assert all(stream.endswith("_events") for _, stream in pairs)


class TestEventViewStarvation:
    """The tuple ledger is a projection the item scan cannot answer from."""

    TUPLE_RESULT = {
        "damage_events_tuple": True,
        "damage_events": [(0.0, 100.0, "Q"), (2.0, 80.0, "W")],
    }

    # Generated from the capability registry rather than from a hand map:
    # P2c deleted ``EVENT_VIEW_STREAMS``, so the (holder, stream) pairs this
    # suite owes a fixture are read off the same projection the tripwire
    # itself reads.  The parametrized ids are unchanged by the move.
    @pytest.mark.parametrize(
        ("item", "stream"),
        item_support_effects._starved_streams(trigger_stream.tuple_incapable_items()),
    )
    def test_every_declared_holder_starves_by_name(self, item, stream):
        """The raise names the item and the stream, never just the failure."""
        holder = _actor("main:Annie", "main", (item,))
        ally = _actor("ally:Pantheon", "ally", ())
        with pytest.raises(
            item_support_effects.EventViewStarvationError,
            match=f"{re.escape(item)} reads {stream}",
        ):
            derive_item_support_effects(holder, self.TUPLE_RESULT, [holder, ally])

    def test_a_holder_with_no_event_view_item_reads_tuple_rows_unharmed(self):
        """Tuple rows are legal; starving a declared reader on them is not."""
        holder = _actor("ally:Lulu", "ally", ("Ardent Censer",))
        ally = _actor("main:Ahri", "main", ())
        assert (
            derive_item_support_effects(holder, self.TUPLE_RESULT, [holder, ally]) == []
        )

    def test_dict_rows_never_starve(self):
        """The raise keys on the ledger shape, not on the item alone."""
        holder = _actor("main:Annie", "main", ("Imperial Mandate",))
        ally = _actor("ally:Pantheon", "ally", ())
        assert (
            derive_item_support_effects(holder, {"damage_events": []}, [holder, ally])
            == []
        )

    def test_the_raise_is_the_named_error_and_not_an_attribute_error(self):
        """Echoes of Helia's missing guard was a latent ``AttributeError``."""
        holder = _actor("ally:Lulu", "ally", ("Echoes of Helia",))
        ally = _actor("main:Ahri", "main", ())
        with pytest.raises(item_support_effects.EventViewStarvationError) as raised:
            derive_item_support_effects(
                holder,
                self.TUPLE_RESULT,
                [holder, ally],
                trigger_effects=[
                    {
                        "time": 1.0,
                        "kind": "heal",
                        "target": ally.participant_id,
                        "amount": 100.0,
                    }
                ],
            )
        assert "STARVED" in str(raised.value)
