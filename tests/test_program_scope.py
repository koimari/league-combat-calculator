"""``program.scope`` — H2's shipped default, and what it refuses to answer.

The vocabulary exists so that "how many roster targets does this cone stun"
is a question the tree asks and answers in one named place, instead of a
question nobody asked whose answer fell out of roster order.  These tests pin
the three properties that make it that rather than a rename: the union is
closed and total, an unreviewed scope cannot yield a routing answer without
its disclosure, and the disclosure names the ability.
"""

from __future__ import annotations

import pytest

from src.calculator.program import route, scope


class TestTheVocabularyIsClosed:
    def test_every_member_of_the_union_is_in_the_registry(self):
        assert set(scope.CC_SCOPES) == {
            scope.SingleTarget,
            scope.MultiTarget,
            scope.Unreviewed,
        }

    def test_scope_policy_is_total_over_the_registry(self):
        """Every reviewed member resolves; the unreviewed one raises."""
        assert scope.scope_policy(scope.SingleTarget()) == route.PairDefender()
        assert scope.scope_policy(scope.MultiTarget(cap=3)) == route.AllOpponents()
        with pytest.raises(scope.UnscopedCrowdControl):
            scope.scope_policy(scope.Unreviewed(ability="Syndra E"))

    def test_a_policy_the_union_does_not_hold_raises_rather_than_resolving(self):
        with pytest.raises(TypeError) as excinfo:
            scope.scope_policy(object())  # type: ignore[arg-type]
        assert "the union is closed" in str(excinfo.value)

    def test_a_multi_target_scope_that_reaches_nobody_is_unconstructible(self):
        with pytest.raises(ValueError):
            scope.MultiTarget(cap=0)

    def test_an_unreviewed_scope_must_name_its_ability(self):
        with pytest.raises(ValueError):
            scope.Unreviewed(ability="   ")


class TestTheShippedDefault:
    """The umbrella's recorded H2 ruling: *deferred, default shipped*."""

    def test_unreviewed_reads_as_single_target_on_the_pair_defender(self):
        reviewed, _ = scope.reviewed_scope(scope.Unreviewed(ability="Syndra E"))
        assert reviewed == scope.SingleTarget()
        assert scope.scope_policy(reviewed) == route.PairDefender()

    def test_the_default_arrives_with_a_disclosure_naming_the_ability(self):
        _, disclosures = scope.reviewed_scope(scope.Unreviewed(ability="Syndra E"))
        assert len(disclosures) == 1
        assert disclosures[0].label == scope.UNREVIEWED_SCOPE_LABEL
        assert "Syndra E" in disclosures[0].reason
        assert "H2" in disclosures[0].reason

    def test_a_disclosure_cannot_change_who_receives_the_event(self):
        """It is a ``RouteAnnotation``, which has no resolution branch."""
        _, disclosures = scope.reviewed_scope(scope.Unreviewed(ability="Syndra E"))
        assert isinstance(disclosures[0], route.RouteAnnotation)
        assert not hasattr(disclosures[0], "targets")

    @pytest.mark.parametrize(
        "reviewed", [scope.SingleTarget(), scope.MultiTarget(cap=2)]
    )
    def test_a_scope_somebody_read_is_returned_unchanged_and_undisclosed(
        self, reviewed
    ):
        assert scope.reviewed_scope(reviewed) == (reviewed, ())


class TestTheMarkRidesTheTrigger:
    """Criterion 9's third clause, at the resolver rather than at a call site."""

    def _context(self, defender: int, opponents: tuple[int, ...]):
        return route.RouteContext(
            author=0, holder=0, pair_defender=defender, opponents=opponents
        )

    def test_a_single_target_scope_reaches_one_and_the_mark_reaches_that_one(self):
        reviewed, _ = scope.reviewed_scope(scope.Unreviewed(ability="Syndra E"))
        context = self._context(defender=2, opponents=(2, 3))
        reached = route.resolve_route(
            scope.scope_policy(reviewed), context, roster_size=4
        )
        assert reached == (2,)
        marked = route.resolve_route(
            route.TriggerTarget(),
            route.RouteContext(author=0, holder=0, trigger_subjects=reached),
            roster_size=4,
        )
        assert marked == (2,)

    def test_a_multi_target_scope_reaches_two_and_the_mark_reaches_both(self):
        """The property roster order could never have produced."""
        context = self._context(defender=2, opponents=(2, 3))
        reached = route.resolve_route(
            scope.scope_policy(scope.MultiTarget(cap=2)), context, roster_size=4
        )
        assert reached == (2, 3)
        marked = route.resolve_route(
            route.TriggerTarget(),
            route.RouteContext(author=0, holder=0, trigger_subjects=reached),
            roster_size=4,
        )
        assert marked == (2, 3)

    def test_a_mark_whose_trigger_reached_nobody_routes_to_nobody(self):
        with pytest.raises(route.UnroutableEvent):
            route.resolve_route(
                route.TriggerTarget(),
                route.RouteContext(author=0, holder=0, trigger_subjects=()),
                roster_size=4,
            )
