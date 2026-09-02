"""Phase 4 S1 — event identity, and the four id strings it must reproduce.

``program/identity`` is the front door for the logical layer's identity
vocabulary.  Its whole claim is a byte-identity claim: whatever grammar the
module names, :func:`event_id_text` must produce exactly the strings the four
legacy f-strings produce today, because those strings are public receipt
content and a trigger link is resolved by comparing them.

The suite therefore has two halves.  The first reproduces each legacy format
from the same inputs its producer uses and asserts equality.  The second
asserts the legacy formats are *still spelled that way in the tree* -- a
byte-identity test whose reference is a string typed into the test file goes
stale the moment a producer changes, and would then pass while the claim is
false, which is this campaign's own failure shape.
"""

from pathlib import Path

import pytest

from src.calculator.program import identity

ROOT = Path(__file__).parents[1]
TIMELINE_PATH = ROOT / "src" / "calculator" / "participant_timeline.py"
COMPILE_PATH = ROOT / "src" / "calculator" / "program" / "compile.py"


class TestTheFourLegacyFormats:
    """One test per ``Origin`` member, against its live producer's f-string."""

    def test_a_pair_fight_row_numbers_by_position(self) -> None:
        """``_pair_packet``'s ``f"{attacker_id}:{defender_id}:{index}"``."""
        attacker_id, defender_id, index = "main", "enemy:1", 7
        event = identity.EventId(identity.PairOrigin(attacker_id, defender_id), index)
        assert identity.event_id_text(event) == f"{attacker_id}:{defender_id}:{index}"

    def test_a_holder_authored_support_packet_names_its_mechanic(self) -> None:
        """The timeline's ``f"{participant_id}:warmog:{sequence}"`` shape.

        The same shape carries ``:heal:`` (engine self-heals) and ``:grey:``
        (grey-health regeneration); the label is the mechanic slug already
        published in the id, so one origin covers all three.
        """
        holder, sequence = "ally:2", 3
        event = identity.EventId(identity.SupportOrigin(holder, "warmog"), sequence)
        assert identity.event_id_text(event) == f"{holder}:warmog:{sequence}"

    def test_a_reactive_packet_numbers_within_its_trigger(self) -> None:
        """The timeline's ``f"{trigger_id}:reactive:{index}"``."""
        trigger = identity.EventId(identity.PairOrigin("enemy:0", "main"), 4)
        trigger_id = identity.event_id_text(trigger)
        event = identity.EventId(identity.ReactiveOrigin(trigger, "reactive"), 2)
        assert identity.event_id_text(event) == f"{trigger_id}:reactive:{2}"

    def test_a_fan_out_clone_is_its_parent_plus_a_role(self) -> None:
        """The timeline's ``f"{event['_event_id']}:redirect"``, unnumbered."""
        parent = identity.EventId(identity.PairOrigin("main", "enemy:0"), 11)
        parent_id = identity.event_id_text(parent)
        clone = identity.EventId(identity.DerivedOrigin(parent, "redirect"))
        assert identity.event_id_text(clone) == f"{parent_id}:redirect"

    def test_a_numbered_fan_out_clone_keeps_its_tick(self) -> None:
        """The deferral clone's ``f"{event['_event_id']}:deferred:{tick}"``."""
        parent = identity.EventId(identity.PairOrigin("main", "enemy:0"), 11)
        parent_id = identity.event_id_text(parent)
        tick = 3
        clone = identity.EventId(identity.DerivedOrigin(parent, "deferred"), tick)
        assert identity.event_id_text(clone) == f"{parent_id}:deferred:{tick}"

    def test_a_clone_of_a_clone_nests(self) -> None:
        """Maw's omnivamp heal hangs off a redirected packet just as well."""
        parent = identity.EventId(identity.PairOrigin("main", "enemy:0"), 1)
        redirect = identity.EventId(identity.DerivedOrigin(parent, "redirect"))
        omnivamp = identity.EventId(identity.DerivedOrigin(redirect, "maw-omnivamp"))
        assert (
            identity.event_id_text(omnivamp) == "main:enemy:0:1:redirect:maw-omnivamp"
        )


class TestTheLegacyFormatsAreStillSpelledThatWay:
    """The reference half: the producers still author what this suite pins.

    Text scans rather than parsed trees, because an f-string's *spelling* is
    what the byte-identity claim is about.  A producer that reformats its id
    fails here and is then either reproduced by ``event_id_text`` or
    escalated -- never silently diverged from.
    """

    def test_the_pair_format_has_exactly_one_producer(self) -> None:
        """One compiler authors it, for the score walk and the receipt alike.

        Spelled twice — once where the timeline enriches a pair packet and
        once where the score compiler rebuilds it — it would be the
        arrangement that makes every other field of an enriched event two
        facts wearing one name.
        """
        pair_format = 'f"{attacker_id}:{defender_id}:{index}"'
        assert pair_format in COMPILE_PATH.read_text(encoding="utf-8")
        assert pair_format not in TIMELINE_PATH.read_text(encoding="utf-8")

    @pytest.mark.parametrize(
        "spelling",
        [
            'f"{combatant.participant_id}:warmog:{sequence}"',
            'f"{trigger_id}:reactive:{index}"',
            "f\"{event.get('_event_id', '')}:redirect\"",
            "f\"{event.get('_event_id', '')}:deferred:{tick}\"",
        ],
    )
    def test_the_timeline_still_authors_each_shape(self, spelling: str) -> None:
        assert spelling in TIMELINE_PATH.read_text(encoding="utf-8")


class TestTheGrammarIsClosed:
    """What the type buys over four hand-spelled f-strings."""

    def test_two_origins_with_the_same_strings_are_different_origins(self) -> None:
        """Why the origins are dataclasses and not two-field NamedTuples.

        As NamedTuples these two would compare equal, and a support packet
        could silently answer a pair packet's trigger lookup.
        """
        assert identity.PairOrigin("a", "b") != identity.SupportOrigin("a", "b")
        assert identity.EventId(identity.PairOrigin("a", "b"), 0) != identity.EventId(
            identity.SupportOrigin("a", "b"), 0
        )

    def test_an_origin_outside_the_union_raises(self) -> None:
        """Fail closed: a fifth origin never renders as a stringified object."""
        with pytest.raises(TypeError, match="is not an Origin"):
            identity.origin_text("main:enemy:0")  # type: ignore[arg-type]

    def test_a_negative_ordinal_that_is_not_unnumbered_raises(self) -> None:
        """``-1`` means unnumbered; ``-2`` is a numbering bug, not an id."""
        origin = identity.PairOrigin("main", "enemy:0")
        with pytest.raises(ValueError, match="is negative but is not"):
            identity.event_id_text(identity.EventId(origin, -2))

    def test_an_unnumbered_id_appends_nothing(self) -> None:
        origin = identity.SupportOrigin("main", "grey")
        assert identity.EventId(origin).ordinal == identity.UNNUMBERED
        assert identity.event_id_text(identity.EventId(origin)) == "main:grey"

    def test_a_derived_origin_holds_its_parent_not_its_parent_text(self) -> None:
        """The invariant a suffix convention cannot express."""
        parent = identity.EventId(identity.PairOrigin("main", "enemy:0"), 2)
        derived = identity.DerivedOrigin(parent, "shield")
        assert derived.parent is parent
        assert identity.event_id_text(identity.EventId(derived)) == (
            "main:enemy:0:2:shield"
        )


def test_the_kernel_does_not_import_the_logical_identity_module() -> None:
    """``program -> survival`` is one-way; ``PIdx`` never enters ``survival/``.

    Criterion 6's second half, asserted where the alias is declared: the
    kernel stores roster indices as plain ints, and an annotation alone would
    invert the phase's own dependency rule.
    """
    survival = ROOT / "src" / "calculator" / "survival"
    for path in sorted(survival.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        assert "program.identity" not in text, path
        assert "PIdx" not in text, path
