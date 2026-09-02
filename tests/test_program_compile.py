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
    pair_preview_mechanics,
    pair_program,
    walk_repriced_mechanics,
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
        assert frozenset() == program_compile._STAGED_RIDERS  # pylint: disable=W0212

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
        action = program_compile.grey_health_heal_action(
            2.5, "Grey Health", 40.0, 0, aidx=7
        )
        assert action.phase is TransitionRank.RECOVERY
        assert action.kind is ActionKind.HEAL
        assert (action.subject, action.attacker, action.aidx) == (0, 0, 7)
        assert action.amount == 40.0

    def test_its_event_id_is_the_published_grey_shape(self) -> None:
        from src.calculator.survival.actions import EVENT_SLOTS

        action = program_compile.grey_health_heal_action(1.0, "Warmog", 10.0, 3, aidx=0)
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
        for action, event in zip(actions, program.events, strict=False):
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


def engine_result(**overrides) -> dict:
    """One pair fight's engine ledger, in the shape the compiler reads."""
    result = {
        "breakdown": {},
        "cast_timeline": [{"time": 1.0, "slot": "Q", "ordinal": 1}],
        "damage_events": [
            {
                "time": 1.0,
                "sequence": 0,
                "source_key": "Q",
                "damage_type": "magic",
                "damage": 50.0,
            },
            {
                "time": 2.0,
                "sequence": 1,
                "source_key": "auto_attacks",
                "damage_type": "physical",
                "damage": 30.0,
            },
        ],
        "control_events": [],
        "self_healing_events": [],
        "timeline_coverage": {},
    }
    result.update(overrides)
    return result


def compile_result(result: dict, **kwargs) -> list:
    """*result* through the one compiler, as typed actions."""
    compiler = program_compile.WalkCompiler(0)
    compiler.add_engine_result(
        result,
        "enemy:Veigar",
        1,
        "main",
        defender_i=0,
        grievous_by_dtype={},
        duration=8.0,
        heal_dedup={},
        id_strings=[],
        **kwargs,
    )
    return compiler.actions


class TestTheCompilerDerivesTheDeliveryFacts:
    """The two facts an engine row does not always spell out.

    An armed damage modifier restricts itself by attack class and a spell
    shield groups a cast by its instance, so a packet that could not say
    which class it belongs to or which cast it came from prices differently
    from the same packet composed anywhere else.  Neither fact may depend on
    a caller having stamped the ledger first: the compiler that reads the row
    is the one that answers them.
    """

    def test_a_cast_row_is_an_ability_and_carries_its_cast_ordinal(self) -> None:
        cast = compile_result(engine_result())[0]
        assert cast.is_ability is True
        assert cast.ability_instance == "Q:1"

    def test_the_ordinary_auto_row_is_the_basic_attack_packet(self) -> None:
        auto = compile_result(engine_result())[1]
        assert auto.basic_attack is True
        assert auto.is_ability is False
        assert auto.ability_instance is None

    def test_a_cast_row_before_any_cast_falls_back_to_its_own_timestamp(self) -> None:
        """No cast to attribute it to is still one identity, not none."""
        result = engine_result(cast_timeline=[])
        assert compile_result(result)[0].ability_instance == "Q:1.0"


class TestTheCompilerStagesAControlRow:
    """A standalone crowd-control interval, compiled as what it is.

    The engine publishes each control application as its own row.  It is not
    damage: it arms after everything that landed at its own timestamp, and it
    reaches the kernel's control branch rather than its damage branch.
    """

    @staticmethod
    def control_row(**overrides) -> dict:
        row = {
            "time": 1.0,
            "sequence": 1_000_001,
            "kind": "crowd_control",
            "cc_kind": "stun",
            "cc_duration": 1.5,
            "damage": 0.0,
            "damage_type": "",
            "source_key": "E",
            "source": "Event Horizon",
            "is_ability": True,
            "cast_id": "E:1",
            "application_id": "E:1",
        }
        row.update(overrides)
        return row

    def control_action(self, **overrides):
        result = engine_result(
            control_events=[self.control_row(**overrides)],
            effective_armor=100.0,
            effective_mr=50.0,
        )
        return compile_result(result)[-1]

    def test_it_compiles_as_control_and_arms_after_the_damage_it_shares(self) -> None:
        action = self.control_action()
        assert action.kind is ActionKind.CROWD_CONTROL
        assert action.phase is TransitionRank.DEBUFF_ARM
        assert (action.cc_kind, action.cc_duration) == ("stun", 1.5)

    def test_it_is_an_ability_even_when_the_row_forgot_to_say_so(self) -> None:
        """A control packet is a cast landing, whatever the row carries."""
        assert self.control_action(is_ability=False).is_ability is True

    def test_it_shares_the_casts_instance_so_one_block_costs_one_use(self) -> None:
        assert self.control_action().ability_instance == "E:1"

    def test_an_unstamped_control_derives_the_same_instance_spelling(self) -> None:
        """The engine's ``slot:ordinal`` and the derived one are one string."""
        derived = self.control_action(
            application_id=None, cast_id=None, source_key="Q", time=1.0
        )
        assert derived.ability_instance == "Q:1"

    def test_it_carries_the_fights_baseline_resistances(self) -> None:
        """The same stamp the damage rows of this fight carry.

        A packet the walk may re-price after a sourced resistance delta needs
        the figure the engine mitigated against; a control row that carried
        none would be the one row of its fight the walk could not place.
        """
        action = self.control_action()
        assert action.baseline_effective_armor == 100.0
        assert action.baseline_effective_mr == 50.0

    def test_a_control_row_with_no_sequence_is_refused(self) -> None:
        """The walk's tie-break order may not depend on id numbering."""
        row = self.control_row()
        del row["sequence"]
        with pytest.raises(ValueError, match="has no sequence"):
            compile_result(engine_result(control_events=[row]))


class TestTheReceiptProjection:
    """``pair_view`` — the same compile, one representation over.

    Every field on an enriched event is a value the compiler decided for the
    action beside it.  What the receipt projection does *not* owe is the
    score walk's own bookkeeping: it stages no actions, it refuses no
    transition the receipt walk can stage, and it deduplicates no actor-wide
    heal (the composition owns that, over the copies published here).
    """

    def test_an_enriched_event_names_both_ends_of_the_pair(self) -> None:
        view = program_compile.pair_view(engine_result(), "enemy:Veigar", "main")
        assert [
            (event["attacker"], event["target"], event["_event_id"])
            for event in view.events
        ] == [
            ("enemy:Veigar", "main", "enemy:Veigar:main:0"),
            ("enemy:Veigar", "main", "enemy:Veigar:main:1"),
        ]

    def test_the_enriched_event_carries_the_compilers_own_facts(self) -> None:
        view = program_compile.pair_view(engine_result(), "enemy:Veigar", "main")
        actions = compile_result(engine_result())
        for event, action in zip(view.events, actions, strict=False):
            assert event["is_ability"] is action.is_ability
            assert event["ability_instance"] == action.ability_instance
            assert event["_sk"] == action.sort_key

    def test_a_field_the_fight_did_not_produce_stays_absent(self) -> None:
        """Absent is "nobody declared one"; present-and-zero is a measurement."""
        view = program_compile.pair_view(engine_result(), "enemy:Veigar", "main")
        cast = view.events[0]
        assert "basic_attack" not in cast
        assert "_live_amp" not in cast
        assert "_declared" not in cast
        assert "grievous_duration" not in cast

    def test_it_publishes_every_actor_wide_copy(self) -> None:
        """The composition dedups; the projection reports."""
        result = engine_result(
            self_healing_events=[
                {
                    "time": 3.0,
                    "sequence": 5,
                    "amount": 120.0,
                    "actor_wide": True,
                    "source": "Maximum Dosage",
                    "source_key": "P",
                }
            ]
        )
        for defender in ("main", "ally:Pantheon"):
            view = program_compile.pair_view(result, "enemy:Mundo", defender)
            assert len(view.heals) == 1

    def test_it_stages_a_transition_the_score_kernel_refuses(self) -> None:
        """The receipt walk is the fallback; it may not refuse what it stages."""
        result = engine_result(
            damage_events=[
                {
                    "time": 1.0,
                    "sequence": 0,
                    "source_key": "Q",
                    "damage_type": "magic",
                    "damage": 50.0,
                    "execute_threshold_ratio": 0.2,
                    "execute_source": "Chemtech Putrifier",
                }
            ]
        )
        with pytest.raises(survival_compile.UncompilableActionError):
            compile_result(result)
        view = program_compile.pair_view(result, "enemy:Veigar", "main")
        assert len(view.events) == 1

    def test_the_composed_result_has_the_previews_removed(self) -> None:
        """A ``THEORETICAL`` row is a preview of a number the walk owns.

        It stays on the engine's own result, where it is the honest
        single-attacker answer; it leaves the one the roster composes, or the
        walk's number and a preview of it would be in one total.
        """
        dropped = sorted(pair_preview_mechanics() - walk_repriced_mechanics())
        assert dropped, "the registry declares no dropped pair preview"
        result = engine_result(
            total_damage=140.0,
            breakdown={
                "Q": {"total_damage": 100.0},
                "preview_row": {"total_damage": 40.0, "pair_preview_of": dropped[0]},
            },
            damage_events=[
                {
                    "time": 1.0,
                    "sequence": 0,
                    "source_key": "Q",
                    "damage_type": "magic",
                    "damage": 100.0,
                },
                {
                    "time": 2.0,
                    "sequence": 1,
                    "source_key": "preview_row",
                    "damage_type": "magic",
                    "damage": 40.0,
                },
            ],
        )
        view = program_compile.pair_view(result, "enemy:Veigar", "main")
        assert view.result["total_damage"] == 100.0
        assert set(view.result["breakdown"]) == {"Q"}
        assert set(view.source_names) == {"Q"}
        assert [event["source_key"] for event in view.events] == ["Q"]
        assert result["total_damage"] == 140.0

    def test_a_light_ledger_has_no_receipt_projection(self) -> None:
        result = engine_result(damage_events_tuple=True, damage_events=[])
        with pytest.raises(ValueError, match="receipt projection"):
            program_compile.pair_view(result, "enemy:Veigar", "main")


class TestTheActorWideHealSkip:
    """The keep-first ``[main, *allies]`` rule (issue #169).

    An enemy attacker's ordered pair list starts at the main, so the walk
    always keeps its main-pair copy of an actor-wide heal.  The ally-pair
    copies must be skipped rather than deduplicated by value: the engine may
    price them differently per defender, and a value dedup would refuse the
    whole fight for copies that disagree.
    """

    @staticmethod
    def result_with_an_actor_wide_heal() -> dict:
        return engine_result(
            self_healing_events=[
                {
                    "time": 3.0,
                    "sequence": 5,
                    "amount": 120.0,
                    "actor_wide": True,
                    "source": "Maximum Dosage",
                    "source_key": "P",
                }
            ]
        )

    def test_the_copy_compiles_when_the_fight_is_the_kept_one(self) -> None:
        actions = compile_result(self.result_with_an_actor_wide_heal())
        assert [a.kind for a in actions].count(ActionKind.HEAL) == 1

    def test_the_ally_pair_copy_is_skipped_whole(self) -> None:
        actions = compile_result(
            self.result_with_an_actor_wide_heal(), suppress_actor_wide_heals=True
        )
        assert ActionKind.HEAL not in [a.kind for a in actions]
