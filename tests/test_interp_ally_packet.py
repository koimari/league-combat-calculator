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
    LevelSubject,
    PacketKind,
    PacketTrigger,
    Recipients,
    ReceiptOnly,
    ReceiptScope,
    RuleFamily,
)
from src.calculator.interpreters import INTERPRETERS
from src.calculator.interpreters.ally_packet import (
    AllyPacketInterpretationError,
    AllyPacketSlot,
    packet_fields,
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
        """Walk halves that emit a *packet* an ally producer could author.

        Self-scoped deliveries are out, and for one reason in two shapes: an
        ally producer authors a packet *onto another participant*, so a half
        whose subject is its own holder is not one any producer could name.
        A rider-delivered half authors no packet at all; a retired family's
        holder packet is authored by the pair engine out of the holder's own
        build and merely re-priced here.  Requiring a producer for either
        would demand an ally template for a number no ally grants.
        """
        return frozenset(
            capability.mechanic
            for capability in ts.CAPABILITIES.values()
            if capability.engine is ts.Engine.WALK
            and not isinstance(capability.packet_source, ts.SELF_SCOPED_DELIVERIES)
            and ts.packet_source_literal(capability) is not None
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

    def test_a_level_ramp_rises_with_the_level_it_is_read_at(self) -> None:
        slot = _slot(AllyProducer.SOUL_SIPHON)
        assert slot.level_value("charge_cap_min", 1) < slot.level_value(
            "charge_cap_min", 18
        )

    def test_a_ramp_says_whose_level_reads_it(self) -> None:
        """Soul Siphon's cap is the *holder's*: the charges are the holder's."""
        assert (
            _slot(AllyProducer.SOUL_SIPHON).level_subject("charge_cap_min")
            is LevelSubject.HOLDER
        )
        assert (
            _slot(AllyProducer.PURIFY).level_subject("heal_min")
            is LevelSubject.RECIPIENT
        )

    def test_an_undeclared_ramp_has_no_subject_to_read(self) -> None:
        with pytest.raises(AllyPacketInterpretationError, match="declares no"):
            _slot(AllyProducer.SOUL_SIPHON).level_subject("charge_damage_ratio")

    def test_an_undeclared_packet_kind_is_a_stop(self) -> None:
        """The emitter cannot build a packet the producer never declared."""
        with pytest.raises(AllyPacketInterpretationError, match="declares no"):
            _slot(AllyProducer.CONSONANCE).declared(PacketKind.SHIELD)

    def test_two_holders_of_one_producer_are_a_stop(self) -> None:
        """Two ledgers with nothing saying how they combine."""
        from src.calculator.item_support_effects import _producer  # noqa: PLC0415

        slots = resolve_slots(catalog.owners_for(AllyProducer.SHARED_RICHES))
        assert (
            len(slots[AllyProducer.SHARED_RICHES]) == 2
        ), "the two support-quest stages are the live two-holder case"
        with pytest.raises(ValueError, match="how two of them combine"):
            _producer(slots, AllyProducer.SHARED_RICHES)


class TestTheEmissionShapeIsAskableWithoutNamingAnItem:
    """What arms a producer and who receives it, read off the declaration.

    The pair engine's control-certification gate is the live reader: it owes
    proof of a control event only for a shield the *holder* receives, and
    those three clauses are what it asks instead of spelling an item name.
    Each clause is checked here against a producer that satisfies the other
    two, because a predicate whose only fixture satisfies all three would
    pass with any two of them deleted.
    """

    def test_the_trigger_is_the_declarations_own(self) -> None:
        assert _slot(AllyProducer.EVERLASTING).trigger is PacketTrigger.CROWD_CONTROL
        assert _slot(AllyProducer.SACRIFICE).trigger is PacketTrigger.ALLY_DAMAGE_DEALT

    def test_a_declared_packet_shape_answers_yes(self) -> None:
        assert _slot(AllyProducer.EVERLASTING).emits(PacketKind.SHIELD, Recipients.SELF)

    def test_the_same_kind_to_somebody_else_answers_no(self) -> None:
        """Command delivers on the same trigger, to the triggering enemy."""
        command = _slot(AllyProducer.COMMAND)
        assert command.trigger is PacketTrigger.CROWD_CONTROL
        assert not command.emits(PacketKind.DAMAGE_MODIFIER, Recipients.SELF)
        assert command.emits(PacketKind.DAMAGE_MODIFIER, Recipients.TRIGGERING_ENEMY)

    def test_another_kind_to_the_holder_answers_no(self) -> None:
        """Fanfare is armed by the same trigger and delivers movement."""
        fanfare = _slot(AllyProducer.FANFARE)
        assert fanfare.trigger is PacketTrigger.CROWD_CONTROL
        assert fanfare.emits(PacketKind.MOVEMENT, Recipients.SELF)
        assert not fanfare.emits(PacketKind.SHIELD, Recipients.SELF)

    def test_only_one_producer_satisfies_all_three_clauses_today(self) -> None:
        """The gate's live population, derived rather than asserted by name."""
        armed = tuple(
            slot
            for producer in AllyProducer
            for slot in resolve_slots(catalog.owners_for(producer)).get(producer, ())
            if slot.trigger is PacketTrigger.CROWD_CONTROL
            and slot.emits(PacketKind.SHIELD, Recipients.SELF)
        )
        assert tuple(slot.producer for slot in armed) == (AllyProducer.EVERLASTING,)


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
        compilability = _slot(AllyProducer.DEVOTION).rule.compilability
        assert isinstance(compilability, ReceiptOnly)
        assert "support_duration" in compilability.reason

    def test_a_self_shield_is_refused_before_its_duration_is_reached(self) -> None:
        """The build-level gate answers first, and says so.

        Everlasting is both a self-shield and a timed one, and the kernel
        would stop it at the earlier gate: ``uncompilable_item_receipt``
        scans the build before any template is staged.  Reporting the
        duration clause would hand a caller a receipt for a gate that never
        ran, which is the wrong sentence and — because the build gate is the
        ledger scope — also the wrong scope.
        """
        compilability = _slot(AllyProducer.EVERLASTING).rule.compilability
        assert isinstance(compilability, ReceiptOnly)
        assert "self_shield_payload" in compilability.reason
        assert compilability.scope is ReceiptScope.SURVIVAL_LEDGER_TRANSITION

    def test_a_producer_that_reroutes_damage_is_derived_like_any_other(self) -> None:
        """Rerouting stopped being a refusal clause; the axes still decide.

        The compiled kernel now stages Knight's Vow itself
        (``stage_knights_vow_redirect_actions`` / ``stage_knights_vow_heals``),
        so ``redirects_incoming_damage`` is a declared fact the packet
        carries rather than a reason to withhold.  What is pinned here is
        that the verdict is still *derived* from the three kernel clauses —
        Sacrifice trips none of them — and not restored as a per-item note.
        """
        rule = _slot(AllyProducer.SACRIFICE).rule
        payload = rule.payload
        assert isinstance(payload, AllyPacketRule)
        assert payload.redirects_incoming_damage is True
        assert isinstance(rule.compilability, Compilable)

    def test_a_non_support_kind_names_the_kind_the_kernel_refuses(self) -> None:
        compilability = _slot(AllyProducer.GOING_SLEDDING).rule.compilability
        assert isinstance(compilability, ReceiptOnly)
        assert "temporary_health" in compilability.reason


class TestTheWalkInterpreterCompilesTheDeclaredNumbers:
    """One value-typed field per declared reference, and no walk state."""

    def test_the_family_is_served_on_the_walk_lane_only(self) -> None:
        assert INTERPRETERS[(RuleFamily.ALLY_PACKET, EngineLane.RECEIPT_WALK)] is (
            packet_fields
        )
        assert (RuleFamily.ALLY_PACKET, EngineLane.PAIR_ENGINE) not in INTERPRETERS

    def test_every_declared_reference_becomes_one_field(self) -> None:
        rule = _slot(AllyProducer.SOUL_SIPHON).rule
        payload = rule.payload
        assert isinstance(payload, AllyPacketRule)
        fields = packet_fields(
            rule,
            catalog.build_context(
                rule.owner,
                11,
                fight_duration_seconds=5.0,
                target_bonus_health=0.0,
                holder_is_melee=False,
            ),
            EngineLane.RECEIPT_WALK,
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
            packet_fields(
                rule,
                catalog.build_context(
                    rule.owner,
                    11,
                    fight_duration_seconds=5.0,
                    target_bonus_health=0.0,
                    holder_is_melee=False,
                ),
                EngineLane.RECEIPT_WALK,
            )


def test_every_producer_is_declared() -> None:
    """A producer with no declaration would be a packet silently dropped."""
    assert frozenset(catalog.ALLY_PACKET_DECLARATIONS) == frozenset(AllyProducer)
