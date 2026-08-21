"""Phase 4 S1 — the kernel's four event references, as integer slots.

``SurvivalAction`` carried four ``str | None`` reference fields: the packet's
own event id, its trigger's, its deferral batch's and its Defy trigger's.
Every consumer asked an identity question of them and answered it by string
comparison inside the walk, and the walk had to rebuild id strings by hand
whenever it authored a derived packet.

S1 replaces the strings with slots into one process-wide registry.  This
suite pins the three things that makes true: the registry is a bijection,
``NO_SLOT`` is the one spelling of "names no reference", and the action type
holds no ``str | None`` reference field any more (criterion 6).
"""

import ast
from pathlib import Path

from src.calculator.program.compile import action_from_event
from src.calculator.survival.actions import (
    EVENT_SLOTS,
    NO_SLOT,
    TransitionRank,
    EventSlots,
    SurvivalAction,
)

ROOT = Path(__file__).parents[1]
SRC_ROOT = ROOT / "src" / "calculator"

# The four fields as they were spelled before S1, and their slot successors.
RETIRED_REFERENCE_FIELDS = ("trigger_event_id", "deferred_batch_id", "defy_trigger_id")
SLOT_FIELDS = (
    "trigger_slot",
    "deferred_batch_slot",
    "event_slot",
    "defy_trigger_slot",
)


class TestTheRegistryIsABijection:
    """A slot stands for exactly one id string, and gives it back."""

    def test_the_same_text_always_gets_the_same_slot(self) -> None:
        slots = EventSlots()
        first = slots.slot("main:enemy:0")
        assert slots.slot("main:enemy:0") == first

    def test_different_texts_get_different_slots(self) -> None:
        slots = EventSlots()
        assigned = {slots.slot(f"main:enemy:{index}") for index in range(50)}
        assert len(assigned) == 50

    def test_text_round_trips(self) -> None:
        slots = EventSlots()
        for text in ("main:enemy:0", "", "ally:1:heal:2:enemy:0", "main:grey:Q:3"):
            assert slots.text(slots.slot(text)) == text

    def test_the_empty_id_is_a_slot_of_its_own(self) -> None:
        """An event carrying ``_event_id: ""`` had an id; it was not absent.

        The old builder used ``is not None`` here, so the walk keyed that
        packet's applied status by the empty string.  Conflating it with
        "no reference" would silently merge every such packet into one.
        """
        slots = EventSlots()
        assert slots.slot("") != NO_SLOT

    def test_no_slot_reads_back_as_the_empty_string(self) -> None:
        """What every consumer already wrote for a missing reference."""
        assert EventSlots().text(NO_SLOT) == ""

    def test_length_counts_distinct_ids(self) -> None:
        slots = EventSlots()
        slots.slot("a")
        slots.slot("a")
        slots.slot("b")
        assert len(slots) == 2


class TestThereIsOneRegistry:
    """A second numbering is the failure the class exists to prevent."""

    def test_src_constructs_no_second_registry(self) -> None:
        """``EVENT_SLOTS`` is the only ``EventSlots()`` in the tree.

        Two registries would hand two numberings to actions that meet inside
        one walk -- two events answering to one integer, with no symptom.
        The construction is counted rather than reviewed, and the one call
        that builds the module singleton is the only one allowed.
        """
        constructions = []
        for path in sorted(SRC_ROOT.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "EventSlots"
                ):
                    constructions.append(path.relative_to(ROOT).as_posix())
        assert constructions == ["src/calculator/survival/actions.py"], (
            "the one construction is the module singleton EVENT_SLOTS -- "
            f"found {constructions}"
        )


class TestTheActionHoldsNoReferenceStrings:
    """Criterion 6: zero ``str | None`` reference fields on the kernel tuple."""

    def test_the_four_slot_fields_exist_and_default_to_no_slot(self) -> None:
        action = SurvivalAction()
        for field in SLOT_FIELDS:
            assert getattr(action, field) == NO_SLOT, field

    def test_the_retired_string_fields_are_gone(self) -> None:
        for field in RETIRED_REFERENCE_FIELDS:
            assert field not in SurvivalAction._fields, field

    def test_no_field_is_annotated_str_or_none(self) -> None:
        """The type, not the names: a fifth reference cannot arrive as text."""
        annotations = SurvivalAction.__annotations__
        assert [
            name
            for name, annotation in annotations.items()
            if str(annotation).replace(" ", "") == "str|None"
        ] == []


class TestTheBuilderInternsWhatThePacketDeclares:
    """A pre-walk author writes id text; the kernel receives a slot."""

    def test_the_packet_id_and_its_trigger_resolve_to_slots(self) -> None:
        action = action_from_event(
            {
                "kind": "damage",
                "_event_id": "main:enemy:0",
                "_trigger_event_id": "main:enemy:0",
                "time": 0.0,
            },
            TransitionRank.DAMAGE,
            0,
            {},
        )
        assert action.event_slot == EVENT_SLOTS.slot("main:enemy:0")
        assert action.trigger_slot == action.event_slot

    def test_an_absent_reference_is_no_slot(self) -> None:
        action = action_from_event({"kind": "damage"}, TransitionRank.DAMAGE, 0, {})
        for field in SLOT_FIELDS:
            assert getattr(action, field) == NO_SLOT, field

    def test_the_deferral_batch_resolves_to_its_parent_packet(self) -> None:
        """The batch id *is* the parent packet's id, so it is that slot."""
        action = action_from_event(
            {
                "kind": "damage",
                "_deferred": True,
                "_deferred_batch_id": "main:enemy:4",
                "_event_id": "main:enemy:4:deferred:1",
            },
            TransitionRank.DAMAGE,
            0,
            {},
        )
        assert action.deferred_batch_slot == EVENT_SLOTS.slot("main:enemy:4")
        assert action.event_slot == EVENT_SLOTS.slot("main:enemy:4:deferred:1")

    def test_the_defy_link_arrives_as_a_slot_the_walk_already_holds(self) -> None:
        """The one reference the walk authors rather than reads.

        ``trigger_defy`` stamps the slot it is already holding, so this key
        carries an integer where the other three carry text -- and slot ``0``
        is a real slot, which is why the builder tests it against ``None``
        rather than for truth.
        """
        action = action_from_event(
            {"kind": "heal", "_defy_trigger_slot": 0},
            TransitionRank.RECOVERY,
            0,
            {},
        )
        assert action.defy_trigger_slot == 0
