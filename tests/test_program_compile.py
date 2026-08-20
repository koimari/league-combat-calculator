"""Phase 4 S4 — the one constructor, and what it refuses.

``program/compile`` is the front door for action construction.  Its claim is
a location claim first — every ``SurvivalAction(...)`` expression in ``src/``
is in this module, bar the one declared survivor, which
``tests/test_program_structure.py`` asserts over the tree — and a
fail-closed claim second: a program carrying a payload family the kernel
cannot stage raises with a named receipt rather than compiling a hole.

The behaviour of the two relocated builders is not re-tested here.  Their
bodies are unchanged and are already pinned by the suites that pinned them
before the move (``test_event_slots``, ``test_modifier_classes``,
``test_issue_137``, ``test_survival_kernel``, ``test_participant_timeline``),
and re-asserting them under a new name would be a second pin that can drift
from the first.  What is new is what is tested.
"""

import ast
import pathlib

import pytest

from src.calculator.program import compile as program_compile
from src.calculator.program import events
from src.calculator.program.build import (
    CapabilityView,
    Program,
    Projection,
    build_program,
    pair_program,
)
from src.calculator.program.identity import EventId, PairOrigin, event_id_text
from src.calculator.survival import compile as survival_compile
from src.calculator.survival.actions import ActionKind, TransitionRank, action_key

ORIGIN = PairOrigin("main", "enemy:0")
EMPTY_CAPS = CapabilityView(mechanics={})


def two_row_program() -> Program:
    """A two-participant roster with two magic hits on the defender."""
    result = {
        "damage_events": [
            {
                "time": float(index),
                "sequence": index,
                "damage": 100.0 + index,
                "damage_type": "magic",
                "source_key": "q",
            }
            for index in range(2)
        ]
    }
    pair = pair_program(result, ORIGIN, EMPTY_CAPS)
    return build_program(("main", "enemy:0"), [(pair, 0, 1)], EMPTY_CAPS)


def program_of(payload, riders: tuple = ()) -> Program:
    """One routed event carrying *payload* and *riders*, at the damage rank."""
    event = events.RoutedEvent(
        id=EventId(ORIGIN, 0),
        subject=1,
        source=0,
        time=0.0,
        sequence=0,
        rank=TransitionRank.DAMAGE,
        payload=payload,
        riders=riders,
    )
    return Program(participants=("main", "enemy:0"), events=(event,))


class TestAProgramCompilesToActions:
    """One routed event in, one kernel action out."""

    def test_every_event_becomes_one_action(self) -> None:
        actions = program_compile.compile_program(
            two_row_program(), projection=Projection.SCORE
        )
        assert len(actions) == 2
        assert [action.kind for action in actions] == [ActionKind.DAMAGE] * 2

    def test_the_action_carries_the_engine_numbers_unchanged(self) -> None:
        """The compiler places numbers; it does not re-price them."""
        actions = program_compile.compile_program(
            two_row_program(), projection=Projection.SCORE
        )
        assert [action.amount for action in actions] == [100.0, 101.0]
        assert all(action.damage_type == "magic" for action in actions)

    def test_the_sort_key_is_eight_elements_in_the_ruled_order(self) -> None:
        """D-67: participant order contributes two, so the shape is eight."""
        actions = program_compile.compile_program(
            two_row_program(), projection=Projection.SCORE
        )
        for action in actions:
            assert len(action.sort_key) == 8
            assert action.sort_key[1] is TransitionRank.DAMAGE

    def test_the_subject_and_source_are_roster_slots(self) -> None:
        actions = program_compile.compile_program(
            two_row_program(), projection=Projection.SCORE
        )
        assert {action.subject for action in actions} == {1}
        assert {action.attacker for action in actions} == {0}


class TestTheProjectionSelectsFieldsAndNotEvents:
    """The incident's ordering, at the compiler rather than at the builder."""

    def test_both_projections_compile_the_same_events(self) -> None:
        program = two_row_program()
        score = program_compile.compile_program(program, projection=Projection.SCORE)
        receipt = program_compile.compile_program(
            program, projection=Projection.RECEIPT
        )
        assert len(score) == len(receipt) == len(program.events)
        assert [a.amount for a in score] == [a.amount for a in receipt]

    def test_score_mode_carries_no_observation_dict(self) -> None:
        """The optimizer never reads one, so the compiler never builds one."""
        score = program_compile.compile_program(
            two_row_program(), projection=Projection.SCORE
        )
        assert all(action.event is None for action in score)

    def test_receipt_mode_carries_the_event_id_it_observes(self) -> None:
        receipt = program_compile.compile_program(
            two_row_program(), projection=Projection.RECEIPT
        )
        assert all(action.event is not None for action in receipt)


class TestAnUnstageableFamilyFailsClosed:
    """A hole in the program is a raise, never a neutral action."""

    @pytest.mark.parametrize(
        "payload",
        [
            events.Revive(800.0),
            events.CombatState("stasis", 2.0),
            events.SpellShield(),
            events.DamageModifier(1.07, frozenset(), frozenset()),
            events.Utility("movement"),
        ],
    )
    def test_the_family_raises_naming_itself(self, payload) -> None:
        with pytest.raises(Exception) as caught:
            program_compile.compile_program(
                program_of(payload), projection=Projection.SCORE
            )
        assert type(payload).__name__ in caught.value.receipt

    @pytest.mark.parametrize(
        ("payload", "staged"),
        [
            (
                events.Damage(50.0, "magic", None, 61.0),
                {
                    "kind": ActionKind.DAMAGE,
                    "amount": 50.0,
                    "damage_type": "magic",
                    "raw_damage": 61.0,
                },
            ),
            (
                events.Recovery(30.0, "lifesteal"),
                {
                    "kind": ActionKind.HEAL,
                    "amount": 30.0,
                    "healing_category": "lifesteal",
                },
            ),
            (
                events.Barrier(40.0, 2.5),
                {"kind": ActionKind.SHIELD, "amount": 40.0, "duration": 2.5},
            ),
            (
                events.TemporaryHealth(25.0, 4.0),
                {
                    "kind": ActionKind.TEMP_HEALTH,
                    "amount": 25.0,
                    "duration": 4.0,
                },
            ),
        ],
    )
    def test_a_stageable_family_stages_its_own_fields(self, payload, staged) -> None:
        """Each family fills its half of the union and no other."""
        (action,) = program_compile.compile_program(
            program_of(payload), projection=Projection.SCORE
        )
        neutral = {
            "damage_type": "",
            "raw_formula": None,
            "raw_damage": 0.0,
            "healing_category": "",
            "amount_formula": None,
            "duration": 0.0,
        }
        for name, value in {**neutral, **staged}.items():
            assert getattr(action, name) == value, name


class TestAnUnstageableRiderFailsClosed:
    """The second axis, held to the first one's rule.

    A rider modifies its host event's arithmetic — an execute threshold that
    kills below a ratio, a wound that halves healing, an amp bonus read
    before absorption — so a compiler that reads the payload and ignores the
    riders emits an action that is wrong rather than absent.  That is the
    fail-open shape one axis over from the one the payload table closes, and
    it is invisible to every equality gate until a rider-bearing packet
    reaches this entry point.
    """

    @pytest.mark.parametrize(
        "rider",
        [
            events.Execute(0.05, "Bastionbreaker"),
            events.Defer(EventId(ORIGIN, 4)),
            events.Redirect(0, 0.4, 120.0),
            events.Wound(3.0, "Katarina R"),
            events.AmpBonus(1.2, "shadowflame"),
        ],
    )
    def test_the_rider_raises_naming_its_family(self, rider) -> None:
        program = program_of(events.Damage(50.0, "magic"), riders=(rider,))
        with pytest.raises(survival_compile.UncompilableActionError) as caught:
            program_compile.compile_program(program, projection=Projection.SCORE)
        assert caught.value.receipt == f"rider_family={type(rider).__name__}"

    def test_every_declared_rider_family_is_covered(self) -> None:
        """The population is the declaration, so a sixth rider is not silent."""
        assert len(events.RIDER_KINDS) == 5
        assert program_compile._STAGED_RIDERS == frozenset()  # pylint: disable=W0212

    def test_a_rider_the_builder_attached_is_refused_end_to_end(self) -> None:
        """The live shape: ``pair_program`` reads riders off the packet.

        Not a hand-built event — the builder attaches ``riders_from_packet``
        to every routed event, so an engine row carrying an execute threshold
        already produces a rider-bearing program today.
        """
        result = {
            "damage_events": [
                {
                    "time": 0.0,
                    "sequence": 0,
                    "damage": 100.0,
                    "damage_type": "physical",
                    "source_key": "q",
                    "execute_threshold_ratio": 0.05,
                    "execute_source": "Bastionbreaker",
                }
            ]
        }
        pair = pair_program(result, ORIGIN, EMPTY_CAPS)
        program = build_program(("main", "enemy:0"), [(pair, 0, 1)], EMPTY_CAPS)
        assert program.events[0].riders != ()
        with pytest.raises(survival_compile.UncompilableActionError) as caught:
            program_compile.compile_program(program, projection=Projection.SCORE)
        assert caught.value.receipt == "rider_family=Execute"

    def test_a_rider_free_event_still_compiles(self) -> None:
        """The refusal is the riders', not a blanket one."""
        program = program_of(events.Damage(50.0, "magic"))
        actions = program_compile.compile_program(program, projection=Projection.SCORE)
        assert len(actions) == 1


class TestTheProgramCacheKeyIsAValue:
    """Never an ``id()``: a mutated roster misses rather than serving."""

    def test_two_projections_of_one_program_are_two_keys(self) -> None:
        program = two_row_program()
        assert program_compile.program_key(
            program, Projection.SCORE
        ) != program_compile.program_key(program, Projection.RECEIPT)

    def test_two_passes_of_one_program_are_two_keys(self) -> None:
        program = two_row_program()
        second = Program(
            participants=program.participants, events=program.events, pass_index=1
        )
        assert program_compile.program_key(
            program, Projection.SCORE
        ) != program_compile.program_key(second, Projection.SCORE)

    def test_two_equal_programs_share_a_key(self) -> None:
        assert program_compile.program_key(
            two_row_program(), Projection.SCORE
        ) == program_compile.program_key(two_row_program(), Projection.SCORE)


class TestTheGreyHealthTickBuilder:
    """The one action shape neither relocated builder produces."""

    def test_it_arms_at_the_recovery_rank_on_the_main_slot(self) -> None:
        action = program_compile.grey_health_heal_action(2.5, "Grey Health", 40.0, 0, 7)
        assert action.phase is TransitionRank.RECOVERY
        assert action.kind is ActionKind.HEAL
        assert (action.subject, action.attacker, action.aidx) == (0, 0, 7)
        assert action.amount == 40.0

    def test_its_event_id_is_the_published_grey_shape(self) -> None:
        from src.calculator.survival.actions import EVENT_SLOTS

        action = program_compile.grey_health_heal_action(1.0, "Warmog", 10.0, 3, 0)
        assert EVENT_SLOTS.text(action.event_slot) == "main:grey:Warmog:3"


class TestTheTriggerTimeToleranceHasOneHome:
    """One tolerance, one spelling, across a one-way boundary.

    The compiler writes a self-heal's trigger index under a timestamp
    normalized to a declared number of digits, and the *kernel* reads it back
    with ``heal_trigger_key``.  ``program -> survival`` runs one way, so the
    kernel cannot import the logical layer: if each side spelled its own
    digit count, changing one would silently unlink every self-heal from the
    hit that caused it — a heal the walk then applies unconditionally, which
    is a wrong number and not an error.
    """

    def test_moving_the_digit_count_moves_both_sides(self, monkeypatch) -> None:
        """The property, not the arrangement: one constant, two readers."""
        event = {
            "_trigger_source": "Q",
            "_trigger_time": 1.2345678901234,
            "_trigger_sequence": 3,
        }
        monkeypatch.setattr(survival_compile, "TRIGGER_TIME_KEY_DIGITS", 3)
        assert survival_compile.heal_trigger_key(event)[1] == 1.235
        assert survival_compile.heal_trigger_key(event)[1] == (
            survival_compile.trigger_time_key(event["_trigger_time"])
        )

    def test_the_writer_and_the_reader_agree_on_one_timestamp(self) -> None:
        """The link itself: what the compiler files under, the kernel finds."""
        time_value = 2.0 / 3.0
        event = {
            "_trigger_source": "Q",
            "_trigger_time": time_value,
            "_trigger_sequence": 1,
        }
        written = ("Q", program_compile.trigger_time_key(time_value), 1)
        assert survival_compile.heal_trigger_key(event) == written

    def test_the_tolerance_is_defined_exactly_once_in_src(self) -> None:
        """A second definition is a second tolerance wearing one name."""
        root = pathlib.Path(__file__).resolve().parent.parent / "src" / "calculator"
        definitions: list[str] = []
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.FunctionDef)
                    and node.name == "trigger_time_key"
                ):
                    definitions.append(f"{path.name}:def")
                if isinstance(node, ast.Assign) and any(
                    isinstance(target, ast.Name)
                    and target.id == "TRIGGER_TIME_KEY_DIGITS"
                    for target in node.targets
                ):
                    definitions.append(f"{path.name}:digits")
        assert sorted(definitions) == ["compile.py:def", "compile.py:digits"]

    def test_the_compiler_spells_no_digit_count_of_its_own(self) -> None:
        """Counter 6's ``program/`` zero, read as the reason it exists."""
        root = pathlib.Path(__file__).resolve().parent.parent / "src" / "calculator"
        text = (root / "program" / "compile.py").read_text(encoding="utf-8")
        assert "trigger_time_key" in text
        assert "round(" not in text


class TestTheProgramEntryPointUsesTheOneSortKey:
    """No fourth spelling of the eight-element key (criterion 2, D-67).

    ``compile_program`` is the declared future entry point, so it is where a
    hand-rebuilt sort key would next take root -- and a hand-rebuilt sort key
    is what let a float phase live at one adapter and a rank at the other for
    three phases.  The key it emits is ``action_key``'s output, asserted
    element for element rather than by reading the call.
    """

    def test_every_compiled_key_is_action_keys_own_output(self) -> None:
        program = two_row_program()
        actions = program_compile.compile_program(program, projection=Projection.SCORE)
        for action, event in zip(actions, program.events):
            text = event_id_text(event.id)
            assert action.sort_key == action_key(
                event.time,
                event.rank,
                program.participants[int(event.subject)],
                {
                    "attacker": program.participants[int(event.source)],
                    "sequence": event.sequence,
                    "_event_id": text,
                },
            )

    def test_the_key_is_eight_elements_in_the_ruled_order(self) -> None:
        """D-67's shape, pinned: ``participant_order`` contributes two."""
        actions = program_compile.compile_program(
            two_row_program(), projection=Projection.SCORE
        )
        assert all(len(action.sort_key) == 8 for action in actions)
