"""Phase 4 S4 — the payload union is closed, and closure is the whole claim.

``program/events`` is the front door for the logical layer's event
vocabulary.  Its claim is not that eleven families are enough; it is that a
packet outside them **raises** rather than reaching the walk as a shape
nothing prices.  So the suite spends most of its length on the negative
half: every live kind classifies, and a packet that names none of them
produces an :class:`UnclassifiedEvent` naming what it did carry.
"""

import pytest

from src.calculator.program import events
from src.calculator.program.identity import PairOrigin
from src.calculator.program.route import PairDefender
from src.calculator.survival.actions import TransitionRank

ORIGIN = PairOrigin("main", "enemy:0")


class TestTheUnionIsClosed:
    """Eleven families and five riders, counted from the declaration."""

    def test_every_family_is_a_frozen_record(self) -> None:
        """A payload nothing can mutate after authoring, by construction."""
        assert len(events.PAYLOAD_FAMILIES) == 11
        for family in events.PAYLOAD_FAMILIES:
            assert family.__dataclass_params__.frozen, family.__name__

    def test_every_rider_is_a_frozen_record(self) -> None:
        assert len(events.RIDER_KINDS) == 5
        for rider in events.RIDER_KINDS:
            assert rider.__dataclass_params__.frozen, rider.__name__

    def test_no_family_carries_a_callable_typed_field(self) -> None:
        """The two engine hooks are values the engine supplied, not policy.

        ``live_formula`` and ``amount_formula`` hold the engine's own
        re-pricing callables, which the walk already carries; every *other*
        field of every family is a number, a string or a frozenset, so a
        family cannot become a place to hide behaviour.
        """
        engine_hooks = {"live_formula", "amount_formula"}
        for family in events.PAYLOAD_FAMILIES:
            for name, annotation in family.__annotations__.items():
                if name in engine_hooks:
                    continue
                assert "Callable" not in str(annotation), (family.__name__, name)


class TestEveryLiveKindClassifies:
    """One case per packet kind the tree authors today."""

    @pytest.mark.parametrize(
        "packet,family",
        [
            ({"kind": "revive", "amount": 800.0}, events.Revive),
            ({"kind": "stasis", "duration": 2.5}, events.CombatState),
            ({"kind": "invulnerability"}, events.CombatState),
            ({"kind": "untargetable"}, events.CombatState),
            ({"kind": "spell_shield"}, events.SpellShield),
            ({"kind": "shield", "amount": 300.0}, events.Barrier),
            ({"kind": "temporary_health", "amount": 150.0}, events.TemporaryHealth),
            ({"kind": "stat_buff", "ability_power": 40.0}, events.StatBuff),
            ({"kind": "damage_modifier", "multiplier": 1.07}, events.DamageModifier),
            ({"kind": "on_hit_magic", "on_hit_magic_damage": 15.0}, events.OnHitMagic),
            ({"kind": "movement"}, events.Utility),
            ({"kind": "cleanse"}, events.Utility),
            ({"kind": "slow"}, events.Utility),
            ({"kind": "economy", "gold_amount": 30.0}, events.Utility),
            ({"kind": "vision", "ward_uses": 1.0}, events.Utility),
            ({"kind": "heal", "amount": 90.0}, events.Recovery),
            ({"kind": "regen", "amount": 12.0}, events.Recovery),
            (
                {"kind": "damage", "damage_type": "magic", "damage": 200.0},
                events.Damage,
            ),
        ],
    )
    def test_the_kind_lands_in_its_family(self, packet: dict, family: type) -> None:
        assert isinstance(events.payload_from_packet(packet, origin=ORIGIN), family)

    def test_a_damage_row_keeps_its_engine_numbers(self) -> None:
        """The classifier reads, it does not re-price."""
        payload = events.payload_from_packet(
            {
                "kind": "damage",
                "damage_type": "physical",
                "damage": 412.5,
                "raw_damage": 500.0,
            },
            origin=ORIGIN,
        )
        assert payload == events.Damage(412.5, "physical", None, 500.0)


class TestAnUnclassifiedPacketRaises:
    """The half that makes the union closed rather than merely long."""

    def test_a_packet_naming_no_family_raises_with_its_keys(self) -> None:
        with pytest.raises(events.UnclassifiedEvent) as caught:
            events.payload_from_packet(
                {"kind": "teleport", "source": "Some Item", "range": 400},
                origin=ORIGIN,
            )
        assert caught.value.source == "Some Item"
        assert caught.value.fields_present == ("kind", "range", "source")
        assert "teleport" not in str(caught.value) or "range" in str(caught.value)

    def test_an_empty_packet_raises_rather_than_pricing_zero(self) -> None:
        """The campaign's invariant at the input boundary."""
        with pytest.raises(events.UnclassifiedEvent):
            events.payload_from_packet({}, origin=ORIGIN)


class TestRidersTravelWithTheirHost:
    """Riders are an axis, not eleven more families."""

    def test_an_execute_marker_becomes_a_rider(self) -> None:
        riders = events.riders_from_packet(
            {"execute_threshold_ratio": 0.05, "execute_source": "Bastionbreaker"}
        )
        assert riders == (events.Execute(0.05, "Bastionbreaker"),)

    def test_a_wound_marker_becomes_a_rider_with_its_source(self) -> None:
        riders = events.riders_from_packet(
            {"grievous_duration": 3.0, "_wound_source": "Katarina R"}
        )
        assert riders == (events.Wound(3.0, "Katarina R"),)

    def test_a_packet_with_no_markers_carries_no_riders(self) -> None:
        assert events.riders_from_packet({"kind": "damage"}) == ()

    def test_riders_come_out_in_declared_order_not_key_order(self) -> None:
        """A rider tuple is compared by a cache key; dict order is an accident."""
        packet = {
            "grievous_duration": 3.0,
            "execute_threshold_ratio": 0.05,
            "execute_source": "x",
        }
        assert [type(r) for r in events.riders_from_packet(packet)] == [
            events.Execute,
            events.Wound,
        ]


class TestTheTwoEventShapes:
    """Authored and routed are the same event before and after routing."""

    def test_a_routed_event_carries_no_policy(self) -> None:
        """The policy answered its question; a second answer could disagree."""
        assert "route" not in events.RoutedEvent.__annotations__
        assert "route" in events.PairEvent.__annotations__

    def test_both_shapes_are_frozen(self) -> None:
        pair = events.PairEvent(
            id=None,
            time=1.0,
            sequence=0,
            rank=TransitionRank.DAMAGE,
            payload=events.Damage(10.0, "magic"),
            route=PairDefender(),
        )
        with pytest.raises(AttributeError):
            pair.time = 2.0  # type: ignore[misc]
