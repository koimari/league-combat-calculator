"""Phase 4 S4/S8 — a second pricing is a second pass, declared and bounded.

``program/dependency`` is the front door for cross-pass work.  What it has to
buy over the recursive path is boundedness and a type: a dependency declares
how many passes it needs, a pass budget that runs out raises
:class:`IncompleteDependency` rather than the untyped ``ValueError`` a caller
cannot tell from a malformed build, and passes are shared rather than summed.

S4 landed the declaration; S8 lands :func:`~.dependency.run_passes`, the
driver that consumes it, and the properties asserted of the driver are the
four D-70 rules: one call per pass, never a call from inside a pass, the
later pass differing from its predecessor only by a :class:`ParamPatch`, and
a budget that runs out raising rather than recursing.
"""

import pytest

from src.calculator.program import dependency


class Params:  # pylint: disable=too-few-public-methods
    """The one parameter a patch in these tests overrides."""

    catalyst_pool = 0.0


CATALYST = dependency.CrossPassDependency(
    mechanic="catalyst_of_aeons.overflow",
    max_passes=2,
    reads="catalyst_pool",
)


class TestADependencyIsBoundedByDeclaration:
    """Unbounded recursion replaced by a number a reviewer can see."""

    def test_a_single_pass_declaration_is_refused(self) -> None:
        with pytest.raises(ValueError, match="at least two passes"):
            dependency.CrossPassDependency(mechanic="m", max_passes=1, reads="x")

    def test_a_dependency_reading_nothing_is_refused(self) -> None:
        with pytest.raises(ValueError, match="reads nothing"):
            dependency.CrossPassDependency(mechanic="m", max_passes=2, reads="")

    def test_the_live_case_declares_two(self) -> None:
        assert CATALYST.max_passes == 2

    def test_a_declaration_is_frozen(self) -> None:
        with pytest.raises(AttributeError):
            CATALYST.max_passes = 3  # type: ignore[misc]


class TestPassesAreSharedNotSummed:
    """Two mechanics each needing two passes need two passes."""

    def test_no_dependency_means_one_pass(self) -> None:
        assert dependency.pass_count(()) == 1

    def test_two_two_pass_dependencies_still_need_two(self) -> None:
        second = dependency.CrossPassDependency(
            mechanic="other", max_passes=2, reads="pool"
        )
        assert dependency.pass_count((CATALYST, second)) == 2

    def test_the_maximum_wins(self) -> None:
        deeper = dependency.CrossPassDependency(
            mechanic="deep", max_passes=3, reads="pool"
        )
        assert dependency.pass_count((CATALYST, deeper)) == 3


class TestTheSecondPassDiffersOnlyByAPatch:
    """A named override, not an in-place rewrite of the first pass's inputs."""

    def test_the_patch_names_the_field_and_the_reason(self) -> None:
        patch = dependency.patch_for_pass(CATALYST, 375.0, 1)
        assert patch.overrides == {"catalyst_pool": 375.0}
        assert "catalyst_of_aeons.overflow" in patch.reason
        assert "pass 1 of 2" in patch.reason


class TestTheFailureIsTypedRatherThanUntyped:
    """A caller can tell "needs another pass" from "this build is malformed"."""

    def test_it_carries_the_dependency_and_the_passes_run(self) -> None:
        error = dependency.IncompleteDependency(CATALYST, 2)
        assert error.dependency is CATALYST
        assert error.passes_run == 2
        assert "catalyst_pool" in str(error)

    def test_it_is_not_a_bare_value_error(self) -> None:
        assert not issubclass(dependency.IncompleteDependency, ValueError)

    def test_a_detail_rides_along_without_replacing_the_declaration(self) -> None:
        error = dependency.IncompleteDependency(
            CATALYST, 1, detail="ally:Lulu exposes no finite pre-mitigation damage"
        )
        assert error.dependency is CATALYST
        assert "catalyst_pool" in str(error)
        assert "ally:Lulu" in str(error)


def _finishes(answer: str):
    """A pass function that never asks for another pass."""
    return lambda index, patch: answer


class TestTheDriverRunsEachPassOnceAndNeverFromInsideOne:
    """D-70's shape: rebuilt per pass, and the walk is never re-entered."""

    def test_one_pass_is_enough_when_nothing_is_requested(self) -> None:
        seen: list[tuple[int, object]] = []

        def run_pass(index, patch):
            seen.append((index, patch))
            return "composed"

        assert dependency.run_passes(run_pass, (CATALYST,)) == "composed"
        assert seen == [(1, None)]

    def test_a_request_buys_exactly_one_more_pass(self) -> None:
        seen: list[tuple[int, object]] = []

        def run_pass(index, patch):
            seen.append((index, patch))
            if index == 1:
                return dependency.PassRequest(CATALYST, 375.0)
            return "composed"

        assert dependency.run_passes(run_pass, (CATALYST,)) == "composed"
        assert [index for index, _ in seen] == [1, 2]

    def test_the_second_pass_differs_only_by_the_patch(self) -> None:
        patches: list[object] = []

        def run_pass(index, patch):
            patches.append(patch)
            if index == 1:
                return dependency.PassRequest(CATALYST, 375.0)
            return "composed"

        dependency.run_passes(run_pass, (CATALYST,))
        assert patches[0] is None
        assert patches[1].overrides == {"catalyst_pool": 375.0}
        assert "pass 2 of 2" in patches[1].reason


class TestTheBudgetRaisesRatherThanRecursing:
    """The whole point of a bound is that running out is an event."""

    def test_a_pass_that_keeps_asking_exhausts_the_budget(self) -> None:
        calls: list[int] = []

        def run_pass(index, patch):
            calls.append(index)
            return dependency.PassRequest(CATALYST, float(index))

        with pytest.raises(dependency.IncompleteDependency) as raised:
            dependency.run_passes(run_pass, (CATALYST,))
        assert calls == [1, 2]
        assert raised.value.passes_run == 2
        assert raised.value.dependency is CATALYST

    def test_an_undeclared_request_is_refused_by_name(self) -> None:
        """A roster that declared nothing gets one pass, and says so."""
        with pytest.raises(dependency.IncompleteDependency) as raised:
            dependency.run_passes(
                lambda index, patch: dependency.PassRequest(CATALYST, 1.0), ()
            )
        assert raised.value.passes_run == 1
        assert "declares no" in str(raised.value)

    def test_the_driver_returns_the_pass_result_untouched(self) -> None:
        """The driver folds passes; it does not fold numbers."""
        sentinel = object()
        assert dependency.run_passes(_finishes(sentinel), (CATALYST,)) is sentinel
