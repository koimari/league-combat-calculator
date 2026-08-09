"""Typed cross-participant item packets and explicit trigger contracts."""

import ast
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace
from typing import get_args, get_type_hints

import pytest

from src.app import app
from src.calculator import item_support_effects, pipeline
from src.calculator.ability_spec import Authority
from src.calculator.item_effects import ITEM_EFFECTS, ally_item_effect_value
from src.calculator.item_effects import ally_item_level_value
from src.calculator.item_support_effects import (
    cross_participant_authorities,
    derive_item_support_effects,
    producer_item,
    schedule_knights_vow,
)


@contextmanager
def _grown_module(extra_source: str):
    """Read the producer table off a copy of the module with one more packet.

    The derivation reads ``_MODULE_PATH``, so a seventh construction site is
    expressed as source text rather than as a monkeypatched table — which is
    the only way to test that the table follows the call sites.
    """
    original = item_support_effects._MODULE_PATH
    with tempfile.TemporaryDirectory() as scratch:
        grown = Path(scratch) / "grown.py"
        grown.write_text(
            original.read_text(encoding="utf-8") + extra_source, encoding="utf-8"
        )
        item_support_effects._MODULE_PATH = grown
        item_support_effects._declared_authorities.cache_clear()
        try:
            yield grown
        finally:
            item_support_effects._MODULE_PATH = original
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


class TestCrossParticipantAuthorities:
    """The producer set is derived from the packets, never tabulated."""

    def test_every_damage_modifier_packet_is_a_row(self):
        """One row per ``kind="damage_modifier"`` construction site."""
        body = Path(item_support_effects.__file__).read_text(encoding="utf-8")
        call_sites = len(
            re.findall(r'^\s*kind="damage_modifier",$', body, flags=re.MULTILINE)
        )
        assert call_sites == len(cross_participant_authorities())

    def test_dream_maker_is_a_producer(self):
        """The sixth producer sets no ``all_sources`` flag and is in anyway."""
        assert "Dream Maker — Blue Dream Bubble" in cross_participant_authorities()

    def test_every_producer_declares_one_of_the_five_members(self):
        """C2 fills the values: no producer is left without an owning engine."""
        declared = cross_participant_authorities()
        assert declared
        assert all(isinstance(value, Authority) for value in declared.values())

    def test_the_row_type_names_the_declared_vocabulary(self):
        """The value is an ``Authority``, with no undeclared spelling left."""
        hints = get_type_hints(cross_participant_authorities)
        key, value = get_args(hints["return"])
        assert key is str
        assert value is Authority

    def test_a_new_producer_joins_without_editing_a_list(self):
        """A seventh construction site is a member the moment it parses."""
        with _grown_module(
            "def _f():\n"
            "    _packet(attacker=a, target=t, time=0.0,\n"
            '            kind="damage_modifier", source="Synthetic — Seventh",\n'
            "            authority=Authority.COUPLED_ONLY)\n"
        ):
            assert (
                cross_participant_authorities()["Synthetic — Seventh"]
                is Authority.COUPLED_ONLY
            )

    def test_a_seventh_producer_without_an_authority_fails_to_resolve(self):
        """The declaration is required, so a silent seventh cannot exist."""
        with _grown_module(
            "def _g():\n"
            "    _packet(attacker=a, target=t, time=0.0,\n"
            '            kind="damage_modifier", source="Synthetic — Undeclared")\n'
        ):
            with pytest.raises(ValueError, match="Synthetic — Undeclared"):
                cross_participant_authorities()

    def test_two_call_sites_may_not_disagree_about_one_mechanic(self):
        """One mechanic has one owning engine, even split across branches."""
        with _grown_module(
            "def _h():\n"
            "    _packet(attacker=a, target=t, time=0.0,\n"
            '            kind="damage_modifier", source="Abyssal Mask — Unmake",\n'
            "            authority=Authority.COUPLED_ONLY)\n"
        ):
            with pytest.raises(ValueError, match="one mechanic has one owning engine"):
                cross_participant_authorities()

    def test_no_hand_written_producer_list_exists(self):
        """A source assertion against the second home the derivation retires."""
        body = Path(item_support_effects.__file__).read_text(encoding="utf-8")
        derivation = body.split("def _declared_authorities")[1].split(
            "def producer_item"
        )[0]
        for source in cross_participant_authorities():
            assert source not in derivation, (
                f"{source!r} is spelled inside the producer-table derivation; "
                "the table must be read from the _packet call sites"
            )

    def test_producer_item_names_the_item_a_scenario_must_equip(self):
        assert producer_item("Imperial Mandate — Command") == "Imperial Mandate"
        assert producer_item("Bloodletter's Curse — Vile Decay") == (
            "Bloodletter's Curse"
        )


# One Abyssal holder, one ally to price and one cursed enemy — the shape the
# coupled baseline's ``mandate_abyssal_curse_roster`` scenario uses, reduced to
# the one item this slice moves.
_ABYSSAL_ROSTER = {
    "champion": "Ahri",
    "level": 18,
    "items": ["Abyssal Mask"],
    "fight_mode": "time_based",
    "fight_duration": 8,
    "enemies": [{"champion": "Aatrox", "level": 18, "items": []}],
    "allies": [
        {
            "champion": "Pantheon",
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


class TestDreamMakerIsCoupledOnly:
    """The sixth producer has no pair-side half, so it declares no owner."""

    def test_blue_dream_bubble_declares_coupled_only(self):
        assert (
            cross_participant_authorities()["Dream Maker — Blue Dream Bubble"]
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
        """A second reader would be a pair-side half arriving unannounced."""
        registry = Path(item_support_effects.__file__).parent
        readers = {
            path.name
            for path in registry.rglob("*.py")
            if "blue_reduction" in path.read_text(encoding="utf-8")
        }
        assert readers == {"item_effects.py", "item_support_effects.py"}


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
        assert (
            cross_participant_authorities()["Abyssal Mask — Unmake"] is Authority.SPLIT
        )

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
        app.config["TESTING"] = True
        response = app.test_client().post("/api/calculate", json=_ABYSSAL_ROSTER)
        assert response.status_code == 200
        events = response.get_json()["combat"]["events"]
        amped = {
            event["attacker"]
            for event in events
            if (event.get("support_damage_multiplier") or {}).get("source")
            == "Abyssal Mask — Unmake"
        }
        assert amped == {"ally:Pantheon"}
        assert any(
            event["attacker"] == "main" and event["target"] == "enemy:Aatrox"
            for event in events
        )


class TestEventViewTupleGate:
    """One predicate answers the tuple question on both paths (D-01)."""

    def test_the_pipeline_tuple_gate_consults_the_event_view_predicate(self):
        """The score-only gate and the enriched-view gate name one predicate."""
        body = Path(pipeline.__file__).read_text(encoding="utf-8")
        assert "and not has_event_view_support_items(items)" in body
        assert "has_event_scan_support_items" not in body

    def test_the_scan_predicate_keeps_no_callers_in_src(self):
        """C1 leaves the callable; Phase 2's P2c deletes it."""
        callers = []
        for module in (Path(pipeline.__file__).parent).rglob("*.py"):
            tree = ast.parse(module.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "has_event_scan_support_items"
                ):
                    callers.append(f"{module.name}:{node.lineno}")
        assert callers == []
        assert callable(item_support_effects.has_event_scan_support_items)

    def test_solstice_sleigh_enters_by_derivation(self):
        """D-02: it is a crowd-control reader, so the set already holds it."""
        assert "Solstice Sleigh" in item_support_effects.CC_TRIGGER_ITEMS
        assert "Solstice Sleigh" in item_support_effects.EVENT_VIEW_SUPPORT_ITEMS
        # ...and the retired predicate never covered it, so its protection
        # today is the cached health-regen coincidence, not this membership.
        sleigh = [{"name": "Solstice Sleigh"}]
        assert not item_support_effects.has_event_scan_support_items(sleigh)
        assert item_support_effects.has_event_view_support_items(sleigh)

    def test_fimbulwinter_is_an_event_view_member_that_reads_event_id(self):
        """D-03: dropping it disarms a fail-closed raise downstream."""
        assert "Fimbulwinter" in item_support_effects.EVENT_VIEW_SUPPORT_ITEMS
        body = Path(item_support_effects.__file__).read_text(encoding="utf-8")
        everlasting = body.split('if "Fimbulwinter" in names:')[1].split("\n    if ")[0]
        assert '_trigger_event_id=event.get("_event_id")' in everlasting

    def test_every_event_view_holder_is_named_by_exactly_one_stream(self):
        """The stream map is the set's one home, so neither can drift."""
        streams = item_support_effects.EVENT_VIEW_STREAMS
        union = frozenset().union(*streams.values())
        assert union == item_support_effects.EVENT_VIEW_SUPPORT_ITEMS
        for item in union:
            owners = [name for name, holders in streams.items() if item in holders]
            assert owners == [next(iter(owners))], f"{item} reads {owners}"


class TestEventViewStarvation:
    """The tuple ledger is a projection the item scan cannot answer from."""

    TUPLE_RESULT = {
        "damage_events_tuple": True,
        "damage_events": [(0.0, 100.0, "Q"), (2.0, 80.0, "W")],
    }

    @pytest.mark.parametrize(
        ("item", "stream"),
        sorted(
            (item, stream)
            for stream, holders in item_support_effects.EVENT_VIEW_STREAMS.items()
            for item in holders
        ),
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
