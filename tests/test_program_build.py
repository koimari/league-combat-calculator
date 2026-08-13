"""Phase 4 S4 — the program is built before any representation choice.

``program/build`` is the front door for authoring.  Its load-bearing claim is
an ordering claim: a :class:`Projection` selects which **fields** the
compiler reads and never which **events exist**, because the Imperial Mandate
incident was an event dropped before compilation, where the compiler's own
fail-closed raise could no longer see it.  The suite asserts that as a
property of the two programs rather than as a comment.
"""

import pytest

from src.calculator.item_behavior import Compilable, ReceiptOnly, ReceiptScope
from src.calculator.program import build, events
from src.calculator.program.identity import PairOrigin
from src.calculator.survival.actions import TransitionRank

ORIGIN = PairOrigin("main", "enemy:0")


def engine_result(rows: int = 3) -> dict:
    """A minimal engine result: numbered damage rows with their sequences."""
    return {
        "damage_events": [
            {
                "time": float(index),
                "sequence": index,
                "damage": 100.0 + index,
                "damage_type": "magic",
                "source_key": "q",
            }
            for index in range(rows)
        ]
    }


def view(**mechanics: build.MechanicView) -> build.CapabilityView:
    return build.CapabilityView(mechanics=dict(mechanics))


COMPILABLE = build.MechanicView(Compilable(), {}, None)


class TestOnePairFightBecomesImmutableEvents:
    """Authoring, before anything knows who the roster is."""

    def test_every_damage_row_becomes_one_event_at_the_damage_rank(self) -> None:
        program = build.pair_program(engine_result(3), ORIGIN, view())
        assert len(program.events) == 3
        assert all(e.rank is TransitionRank.DAMAGE for e in program.events)
        assert all(isinstance(e.payload, events.Damage) for e in program.events)

    def test_ids_are_positional_and_belong_to_the_pair(self) -> None:
        program = build.pair_program(engine_result(2), ORIGIN, view())
        assert [e.id.ordinal for e in program.events] == [0, 1]
        assert all(e.id.origin == ORIGIN for e in program.events)

    def test_a_row_without_a_sequence_is_refused(self) -> None:
        """The tie-break would otherwise depend on event-id numbering."""
        result = engine_result(1)
        del result["damage_events"][0]["sequence"]
        with pytest.raises(ValueError, match="has no sequence"):
            build.pair_program(result, ORIGIN, view())

    def test_the_pair_program_is_frozen(self) -> None:
        program = build.pair_program(engine_result(1), ORIGIN, view())
        with pytest.raises(AttributeError):
            program.events = ()  # type: ignore[misc]


class TestRoutingHappensAtTheRosterAndNotBefore:
    """A pair program does not know an index; a program is nothing but."""

    def test_every_authored_event_reaches_the_pair_defender(self) -> None:
        pair = build.pair_program(engine_result(2), ORIGIN, view())
        program = build.build_program(
            ("main", "ally:1", "enemy:0"), [(pair, 0, 2)], view()
        )
        assert [e.subject for e in program.events] == [2, 2]
        assert [e.source for e in program.events] == [0, 0]

    def test_the_program_records_its_roster_and_pass(self) -> None:
        pair = build.pair_program(engine_result(1), ORIGIN, view())
        program = build.build_program(
            ("main", "enemy:0"), [(pair, 0, 1)], view(), pass_index=1
        )
        assert program.participants == ("main", "enemy:0")
        assert program.roster_size() == 2
        assert program.pass_index == 1


class TestAProjectionSelectsFieldsAndNeverEvents:
    """The incident's ordering, asserted."""

    def test_the_two_projections_are_the_whole_enum(self) -> None:
        assert {p.value for p in build.Projection} == {"score", "receipt"}

    def test_build_program_takes_no_projection_at_all(self) -> None:
        """The strongest form of the claim: the builder cannot consult one."""
        import inspect

        assert "projection" not in inspect.signature(build.build_program).parameters
        assert "projection" not in inspect.signature(build.pair_program).parameters


class TestTheCapabilityViewIsAFrozenProjection:
    """Three questions, and a refusal for a mechanic nobody declared."""

    def test_an_undeclared_mechanic_raises_rather_than_compiling(self) -> None:
        with pytest.raises(KeyError, match="declares no capability"):
            view().compilability_for("nobody.knows")

    def test_a_receipt_only_mechanic_makes_the_view_uncompilable(self) -> None:
        caps = view(
            fine=COMPILABLE,
            amp=build.MechanicView(
                ReceiptOnly(
                    "the compiled kernel cannot stage a timed amp",
                    ReceiptScope.SCORE_KERNEL_DAMAGE_MODIFIER,
                ),
                {},
                None,
            ),
        )
        assert caps.compilable() is False
        assert caps.refusals() == (
            ("amp", "the compiled kernel cannot stage a timed amp"),
        )

    def test_an_all_compilable_view_reports_no_refusals(self) -> None:
        caps = view(one=COMPILABLE, two=COMPILABLE)
        assert caps.compilable() is True
        assert caps.refusals() == ()


class TestProducerOrderIsDerived:
    """Not declared — a hand tier would be a fourth writer on the registry."""

    def test_an_independent_registry_orders_by_name(self) -> None:
        caps = view(beta=COMPILABLE, alpha=COMPILABLE)
        assert build.derivation_order(caps) == ("alpha", "beta")

    def test_a_declared_dependency_puts_the_parent_first(self) -> None:
        caps = view(alpha=COMPILABLE, beta=COMPILABLE)
        order = build.derivation_order(caps, depends_on={"alpha": ("beta",)})
        assert order.index("beta") < order.index("alpha")

    def test_a_cycle_raises_naming_its_members(self) -> None:
        caps = view(alpha=COMPILABLE, beta=COMPILABLE)
        with pytest.raises(build.DerivationCycle) as caught:
            build.derivation_order(
                caps, depends_on={"alpha": ("beta",), "beta": ("alpha",)}
            )
        assert set(caught.value.cycle) == {"alpha", "beta"}


class TestAPatchIsTheOnlyWayTwoPassesDiffer:
    """Frozen overrides plus a reason, never an in-place rewrite."""

    def test_a_patch_does_not_mutate_its_parameters(self) -> None:
        class Params:  # pylint: disable=too-few-public-methods
            fight_duration_seconds = 8.0

        params = Params()
        patch = build.ParamPatch({"fight_duration_seconds": 12.0}, "pass 2")
        assert patch.applied_to(params) == {"fight_duration_seconds": 12.0}
        assert params.fight_duration_seconds == 8.0

    def test_a_patch_is_frozen(self) -> None:
        patch = build.ParamPatch({"x": 1}, "why")
        with pytest.raises(AttributeError):
            patch.reason = "other"  # type: ignore[misc]
