"""Phase 4 S4 — the two incident defects, asserted unconstructible.

``program/amp`` is the front door for amplification authorship.  Its claim is
stronger than "these defects are tested for": a pair-engine price that also
reaches its own holder, and a modifier with no declared class restriction,
cannot be **built**.  So every test below is a construction test, and the
negative ones assert a raise rather than a wrong number.
"""

import pytest

from src.calculator.ability_spec import AttackClass, DamageClass
from src.calculator.item_behavior import EngineLane
from src.calculator.program import amp
from src.calculator.trigger_stream import HolderStacking

MAGIC = frozenset({DamageClass.MAGIC})
ALL_ATTACKS = frozenset(AttackClass)


def provenance(**overrides):
    """A valid coupled-lane provenance, one field at a time overridden."""
    fields = {
        "holder": 2,
        "priced_by": EngineLane.RECEIPT_WALK,
        "applies_to": amp.AppliesTo.ALL,
        "damage_classes": MAGIC,
        "attack_classes": ALL_ATTACKS,
    }
    fields.update(overrides)
    return amp.Provenance(**fields)


class TestTheUntypedAmpIsUnconstructible:
    """D-04 at authoring time, not at application time."""

    def test_an_empty_damage_class_set_raises(self) -> None:
        with pytest.raises(ValueError, match="empty-means-all is banned"):
            provenance(damage_classes=frozenset())

    def test_an_empty_attack_class_set_raises(self) -> None:
        with pytest.raises(ValueError, match="empty-means-all is banned"):
            provenance(attack_classes=frozenset())

    def test_a_complete_declaration_constructs(self) -> None:
        assert provenance().damage_classes == MAGIC


class TestThePairPreviewCannotReachItsOwnHolder:
    """The double count, made unrepresentable rather than reviewed for."""

    def test_a_pair_priced_modifier_claiming_all_raises(self) -> None:
        with pytest.raises(ValueError, match="count the holder twice"):
            provenance(priced_by=EngineLane.PAIR_ENGINE, applies_to=amp.AppliesTo.ALL)

    def test_a_pair_priced_modifier_excluding_its_holder_constructs(self) -> None:
        record = provenance(
            priced_by=EngineLane.PAIR_ENGINE,
            applies_to=amp.AppliesTo.ALL_EXCEPT_HOLDER,
        )
        assert record.applies_to is amp.AppliesTo.ALL_EXCEPT_HOLDER

    def test_the_owner_skip_reads_a_slot_and_not_an_id_string(self) -> None:
        record = provenance(
            priced_by=EngineLane.PAIR_ENGINE,
            applies_to=amp.AppliesTo.ALL_EXCEPT_HOLDER,
            holder=2,
        )
        assert record.skips(2) is True
        assert record.skips(3) is False

    def test_a_coupled_modifier_reaches_its_holder(self) -> None:
        assert provenance(holder=2).skips(2) is False


class TestArmingDedupeIsDeclaredInBothDirections:
    """D-66: an aura arms once, a per-holder mechanic arms per holder."""

    def test_two_holders_of_an_aura_collide_on_one_key(self) -> None:
        first = amp.arm_key(4, "abyssal_mask.unmake", 0, HolderStacking.IDEMPOTENT_AURA)
        second = amp.arm_key(
            4, "abyssal_mask.unmake", 1, HolderStacking.IDEMPOTENT_AURA
        )
        assert first == second == (4, "abyssal_mask.unmake")

    def test_two_holders_of_a_per_holder_mechanic_do_not_collide(self) -> None:
        """The incident's own shape, refused: a second Mandate holder is priced."""
        first = amp.arm_key(4, "imperial_mandate.command", 0, HolderStacking.PER_HOLDER)
        second = amp.arm_key(
            4, "imperial_mandate.command", 1, HolderStacking.PER_HOLDER
        )
        assert first != second
        assert first == (4, "imperial_mandate.command", 0)

    def test_one_holder_arming_twice_collides_under_either_declaration(self) -> None:
        for stacking in HolderStacking:
            assert amp.arm_key(4, "m", 1, stacking) == amp.arm_key(4, "m", 1, stacking)

    def test_a_mechanic_with_no_declaration_raises(self) -> None:
        """No default to fall through to — that is what defaultless means."""
        with pytest.raises(TypeError, match="closed"):
            amp.arm_key(4, "m", 1, None)  # type: ignore[arg-type]


class TestTheStackingEnumLivesBesideTheRegistryItDeclares:
    """One home, so the field and its vocabulary cannot drift apart."""

    def test_it_is_exported_from_trigger_stream(self) -> None:
        from src.calculator import trigger_stream

        assert trigger_stream.HolderStacking is HolderStacking
        assert {member.value for member in HolderStacking} == {
            "idempotent_aura",
            "per_holder",
        }
