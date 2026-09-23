"""The one constructor, and what it refuses.

``program/compile`` is the front door for action construction.  Its first
claim is location: every expression building an action record in ``src/`` is
in this module, which ``tests/test_program_structure.py`` asserts over the
tree.  Its second is fail-closed: an engine row the kernel cannot stage
raises with a named receipt rather than compiling a hole.

The behaviour of the relocated builders is pinned by the suites that own them
(``test_event_slots``, ``test_modifier_classes``,
``test_state_transition_engine``, ``test_survival_kernel``,
``test_participant_timeline``), and re-asserting it here would be a second
pin that can drift from the first.
"""

import ast
import pathlib

import pytest

from src.calculator.program import compile as program_compile
from src.calculator.program.capability import (
    pair_preview_mechanics,
    walk_repriced_mechanics,
)
from src.calculator.survival import compile as survival_compile
from src.calculator.survival.phases import TransitionRank
from src.calculator.survival.typed_action import ActionKind


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
        from src.calculator.survival.event_slots import EVENT_SLOTS

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


def compile_result(
    result: dict, suppress_actor_wide_heals: bool = False, **kwargs
) -> list:
    """*result* through the one compiler, as typed actions."""
    compiler = program_compile.WalkCompiler(0)
    compiler.add_engine_result(
        program_compile.PairFight(result, "enemy:Veigar", "main", **kwargs),
        program_compile.WalkSlots(
            1, 0, {}, 8.0, {}, [], suppress_actor_wide_heals=suppress_actor_wide_heals
        ),
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
    """The keep-first ``[main, *allies]`` rule.

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


class TestTheCompiledHealCarriesItsGateFields:
    """A heal's own answers to the walk's gates, on the compiled action.

    ``action_from_event`` stamps both off the same event, so a heal only one
    builder stamps is a heal one walk applies and the other drops: without
    ``cast_while_disabled`` the compiled walk blocks Gangplank's Remove
    Scurvy exactly when the receipt walk applies it, and without the cleanse
    pair a heal that rides a cleanse loses the truncation.
    """

    @staticmethod
    def compiled_heal(**heal_fields):
        (action,) = [
            action
            for action in compile_result(
                engine_result(
                    self_healing_events=[
                        {
                            "time": 3.0,
                            "sequence": 5,
                            "amount": 120.0,
                            "source": "Remove Scurvy",
                            "source_key": "W",
                            **heal_fields,
                        }
                    ]
                )
            )
            if action.kind is ActionKind.HEAL
        ]
        return action

    def test_the_declared_cast_while_disabled_exemption_is_stamped(self) -> None:
        assert self.compiled_heal(cast_while_disabled=True).cast_while_disabled is True

    def test_a_heal_that_declares_nothing_stays_gated(self) -> None:
        heal = self.compiled_heal()
        assert heal.cast_while_disabled is False
        assert heal.cleanse is False
        assert heal.cleanse_item == ""

    def test_a_heal_that_rides_a_cleanse_keeps_the_marker_pair(self) -> None:
        heal = self.compiled_heal(cleanse=True, cleanse_item="Mikael's Blessing")
        assert heal.cleanse is True
        assert heal.cleanse_item == "Mikael's Blessing"


class TestTheEventBuilderFillsTheCoreByName:
    """``action_from_event`` hands the core positionally, so each is pinned by name."""

    def test_every_core_field_lands_on_its_own_name(self) -> None:
        from src.calculator.survival.event_slots import EVENT_SLOTS

        event = {
            "_sk": ("sort", "key"),
            "time": 4.5,
            "kind": "heal",
            "attacker": "ally:Lulu",
            "_trigger_event_id": "trigger:1",
            "_event_id": "event:1",
            "source_key": "W",
            "source": "Whimsy",
            "sequence": 9,
            "amount": 30.0,
            "_redirected": True,
        }
        action = program_compile.action_from_event(
            event,
            TransitionRank.RECOVERY,
            2,
            {"ally:Lulu": 1},
            aidx=7,
        )
        expected = {
            "sort_key": ("sort", "key"),
            "time": 4.5,
            "phase": TransitionRank.RECOVERY,
            "kind": ActionKind.HEAL,
            "subject": 2,
            "attacker": 1,
            "aidx": 7,
            "trigger": -1,
            "trigger_slot": EVENT_SLOTS.slot("trigger:1"),
            "event_slot": EVENT_SLOTS.slot("event:1"),
            "source_key": "W",
            "source": "Whimsy",
            "sequence": 9,
            "amount": 30.0,
            "redirected": True,
        }
        assert {name: getattr(action, name) for name in expected} == expected
        assert action.event is event
