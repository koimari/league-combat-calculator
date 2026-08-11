"""The ally-packet family's front door: declarations, slots and refusals.

The family has no arithmetic to test — an ally packet is an emission, and the
emissions themselves are pinned by ``tests/test_item_support_effects.py``.
What is testable here, and what the migration turns on, is the *contract*
between a declaration and the emitter that reads it: which producer a registry
record carries, which numbers it may read, which packets it may build, and
what happens when an emitter asks for something the declaration does not
carry.
"""

from __future__ import annotations

import pytest

from src.calculator import item_behavior_catalog as catalog
from src.calculator import trigger_stream as ts
from src.calculator.item_behavior import (
    AllyPacketRule,
    AllyProducer,
    Compilable,
    EngineLane,
    PacketKind,
    ReceiptOnly,
    RuleFamily,
)
from src.calculator.interpreters import INTERPRETERS
from src.calculator.interpreters.ally_packet import (
    AllyPacketInterpretationError,
    AllyPacketSlot,
    WALK_INTERPRETER,
    resolve_slots,
)


def _slot(producer: AllyProducer) -> AllyPacketSlot:
    """The one live slot for *producer*, resolved from its own owners."""
    slots = resolve_slots(catalog.owners_for(producer))
    return slots[producer][0]


class TestTheProducerVocabularyIsBoundToPhaseTwo:
    """One producer per walk capability that emits a packet — asserted."""

    @staticmethod
    def _packet_capabilities() -> frozenset[str]:
        return frozenset(
            capability.mechanic
            for capability in ts.CAPABILITIES.values()
            if capability.engine is ts.Engine.WALK
            and capability.packet_source is not None
        )

    def test_every_producer_names_a_declared_walk_capability(self) -> None:
        """A producer whose mechanic no capability declares is unreachable."""
        mechanics = {
            f"{catalog._mechanic_slug(owner)}.{producer.value}"  # noqa: SLF001
            for producer in AllyProducer
            for owner in catalog.owners_for(producer)
        }
        assert mechanics == self._packet_capabilities()

    def test_every_producer_is_carried_by_a_registry_record(self) -> None:
        """The inverse: a declaration against a record that does not exist."""
        for producer in AllyProducer:
            assert catalog.owners_for(producer), producer.value


class TestTheEntryShapeDecidesWhoCarriesAProducer:
    """Dispatch is on the record's value keys, never on the item's name."""

    def test_the_ally_registry_is_matched_exactly(self) -> None:
        """D-47: the hand-authored registry is refresh-inert, so exact is safe."""
        entry = dict(catalog.item_effects.ALLY_ITEM_EFFECTS["Cryptbloom"])
        assert catalog.producers_for("ALLY_ITEM_EFFECTS", entry) == (
            AllyProducer.LIFE_FROM_DEATH,
        )
        entry["life_from_death_second_thought"] = 1.0
        assert catalog.producers_for("ALLY_ITEM_EFFECTS", entry) == ()

    def test_the_item_registry_is_matched_on_a_signature(self) -> None:
        """A parsed record may grow keys; the signature survives that."""
        entry = dict(catalog.item_effects.ITEM_EFFECTS["Fimbulwinter"])
        entry["a_number_the_wiki_grew"] = 3.0
        assert AllyProducer.EVERLASTING in catalog.producers_for("ITEM_EFFECTS", entry)

    def test_a_partly_parsed_producer_is_a_stop(self) -> None:
        """A broken parse must not read as an item that emits nothing."""
        entry = dict(catalog.item_effects.ITEM_EFFECTS["Fimbulwinter"])
        del entry["everlasting_duration"]
        with pytest.raises(catalog.BehaviorCatalogError, match="partly-parsed"):
            catalog.producers_for("ITEM_EFFECTS", entry)

    def test_one_record_may_carry_two_producers(self) -> None:
        """Dream Maker's two bubbles are two mechanics on one record."""
        entry = catalog.item_effects.ALLY_ITEM_EFFECTS["Dream Maker"]
        assert set(catalog.producers_for("ALLY_ITEM_EFFECTS", entry)) == {
            AllyProducer.BLUE_BUBBLE,
            AllyProducer.PURPLE_BUBBLE,
        }


class TestASlotRefusesWhatItsDeclarationDoesNotCarry:
    """The declaration is load-bearing, which means it can say no."""

    def test_a_declared_value_reads_live_from_the_registry(self) -> None:
        slot = _slot(AllyProducer.CONSONANCE)
        assert slot.owner == "Diadem of Songs"
        assert slot.value("consonance_max_mana_ratio") == (
            catalog.item_effects.ally_item_effect_value(
                "Diadem of Songs", "consonance_max_mana_ratio"
            )
        )

    def test_an_undeclared_value_is_a_stop(self) -> None:
        with pytest.raises(AllyPacketInterpretationError, match="declares no"):
            _slot(AllyProducer.CONSONANCE).value("harmony_bonus_mana_ratio")

    def test_a_level_ramp_is_read_at_the_recipients_level(self) -> None:
        slot = _slot(AllyProducer.SOUL_SIPHON)
        assert slot.level_value("charge_cap_min", 1) < slot.level_value(
            "charge_cap_min", 18
        )

    def test_an_undeclared_packet_kind_is_a_stop(self) -> None:
        """The emitter cannot build a packet the producer never declared."""
        with pytest.raises(AllyPacketInterpretationError, match="declares no"):
            _slot(AllyProducer.CONSONANCE).declared(PacketKind.SHIELD)

    def test_two_holders_of_one_producer_are_a_stop(self) -> None:
        """Two ledgers with nothing saying how they combine."""
        from src.calculator.item_support_effects import _producer  # noqa: PLC0415

        slots = resolve_slots(catalog.owners_for(AllyProducer.SHARED_RICHES))
        assert AllyProducer.SHARED_RICHES not in slots  # not migrated yet
        doubled = {AllyProducer.CONSONANCE: _slot(AllyProducer.CONSONANCE)}
        doubled[AllyProducer.CONSONANCE] = (
            doubled[AllyProducer.CONSONANCE],
            doubled[AllyProducer.CONSONANCE],
        )
        with pytest.raises(ValueError, match="how two of them combine"):
            _producer(doubled, AllyProducer.CONSONANCE)


class TestDFiftysSecondTargetIsDeclaredNotInferred:
    """D-50: a producer reaching two roster classes says which."""

    def test_a_single_class_producer_declares_no_secondary(self) -> None:
        payload = _slot(AllyProducer.LIFE_FROM_DEATH).rule.payload
        assert isinstance(payload, AllyPacketRule)
        assert payload.secondary_target is None

    def test_starlit_grace_declares_both_kinds_it_chains(self) -> None:
        """The runtime-computed kind became two declared packets."""
        payload = _slot(AllyProducer.STARLIT_GRACE).rule.payload
        assert isinstance(payload, AllyPacketRule)
        assert {spec.kind for spec in payload.packets} == {
            PacketKind.HEAL,
            PacketKind.SHIELD,
        }


class TestTheCompiledLaneAnswerIsDerived:
    """Compilability comes from three declared axes, not a per-item note."""

    def test_an_instantaneous_heal_is_compilable(self) -> None:
        assert isinstance(_slot(AllyProducer.CONSONANCE).rule.compilability, Compilable)

    def test_a_timed_shield_names_the_kernel_clause_that_refuses_it(self) -> None:
        compilability = _slot(AllyProducer.EVERLASTING).rule.compilability
        assert isinstance(compilability, ReceiptOnly)
        assert "support_duration" in compilability.reason

    def test_a_producer_that_reroutes_damage_names_its_own_clause(self) -> None:
        compilability = _slot(AllyProducer.SACRIFICE).rule.compilability
        assert isinstance(compilability, ReceiptOnly)
        assert "re-routes" in compilability.reason

    def test_a_non_support_kind_names_the_kind_the_kernel_refuses(self) -> None:
        compilability = _slot(AllyProducer.GOING_SLEDDING).rule.compilability
        assert isinstance(compilability, ReceiptOnly)
        assert "temporary_health" in compilability.reason


class TestTheWalkInterpreterCompilesTheDeclaredNumbers:
    """One value-typed field per declared reference, and no walk state."""

    def test_the_family_is_served_on_the_walk_lane_only(self) -> None:
        assert INTERPRETERS[(RuleFamily.ALLY_PACKET, EngineLane.RECEIPT_WALK)] is (
            WALK_INTERPRETER
        )
        assert WALK_INTERPRETER.LANES == frozenset({EngineLane.RECEIPT_WALK})

    def test_every_declared_reference_becomes_one_field(self) -> None:
        rule = _slot(AllyProducer.SOUL_SIPHON).rule
        payload = rule.payload
        assert isinstance(payload, AllyPacketRule)
        fields = WALK_INTERPRETER.compile(
            rule,
            catalog.build_context(
                rule.owner,
                11,
                fight_duration_seconds=5.0,
                target_bonus_health=0.0,
                holder_is_melee=False,
            ),
        )
        assert len(fields) == len(payload.values)
        assert {field.name for field in fields} == {
            "charge_damage_ratio",
            "charge_cap_min",
        }
        assert all(field.lane is EngineLane.RECEIPT_WALK for field in fields)
        assert all(isinstance(field.value, float) for field in fields)

    def test_a_rule_of_another_family_is_refused(self) -> None:
        rule = catalog.behavior_rules("Horizon Focus")[0]
        with pytest.raises(AllyPacketInterpretationError, match="not an ally-packet"):
            WALK_INTERPRETER.compile(
                rule,
                catalog.build_context(
                    rule.owner,
                    11,
                    fight_duration_seconds=5.0,
                    target_bonus_health=0.0,
                    holder_is_melee=False,
                ),
            )


class TestWhatIsNotMigratedYetIsNamedRatherThanZeroed:
    """A partly-migrated family keeps its promises per producer."""

    def test_the_two_tables_partition_the_producers(self) -> None:
        assert frozenset(catalog.ALLY_PACKET_DECLARATIONS) | frozenset(
            catalog.ALLY_PACKET_UNMIGRATED_PRODUCERS
        ) == frozenset(AllyProducer)
        assert not frozenset(catalog.ALLY_PACKET_DECLARATIONS) & frozenset(
            catalog.ALLY_PACKET_UNMIGRATED_PRODUCERS
        )

    def test_every_remaining_producer_names_the_commit_that_retires_it(self) -> None:
        for reason in catalog.ALLY_PACKET_UNMIGRATED_PRODUCERS.values():
            assert reason.startswith("3.6")
