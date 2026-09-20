"""Phase 4 S4 — the arming dedupe, asserted in both directions.

``program/amp`` is the front door for amplification authorship.  A second
holder of an aura arms nothing new and a second holder of a per-holder
mechanic arms its own copy, and which of the two a mechanic gets is its own
:class:`~src.calculator.trigger_stream.HolderStacking` declaration rather
than a policy in the ledger.
"""

import pytest

from src.calculator.program import amp
from src.calculator.trigger_stream import HolderStacking


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
