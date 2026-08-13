"""Phase 4 S4 — a second pricing is a second pass, declared and bounded.

``program/dependency`` is the front door for cross-pass work.  What it has to
buy over the recursive path is boundedness and a type: a dependency declares
how many passes it needs, a pass budget that runs out raises
:class:`IncompleteDependency` rather than the untyped ``ValueError`` a caller
cannot tell from a malformed build, and passes are shared rather than summed.
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

    def test_the_patch_leaves_the_first_pass_parameters_recoverable(self) -> None:
        params = Params()
        patch = dependency.patch_for_pass(CATALYST, 375.0, 1)
        assert patch.applied_to(params) == {"catalyst_pool": 375.0}
        assert params.catalyst_pool == 0.0


class TestTheFailureIsTypedRatherThanUntyped:
    """A caller can tell "needs another pass" from "this build is malformed"."""

    def test_it_carries_the_dependency_and_the_passes_run(self) -> None:
        error = dependency.IncompleteDependency(CATALYST, 2)
        assert error.dependency is CATALYST
        assert error.passes_run == 2
        assert "catalyst_pool" in str(error)

    def test_it_is_not_a_bare_value_error(self) -> None:
        assert not issubclass(dependency.IncompleteDependency, ValueError)
