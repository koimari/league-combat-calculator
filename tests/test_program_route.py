"""Phase 4 S4 — subject resolution is total, and an empty answer is a raise.

``program/route`` is the front door for delivery.  The property it exists to
buy is not "ten policies exist"; it is that a policy the context cannot
answer **raises** instead of returning an empty tuple that reads downstream
as "this reached nobody, so it contributed zero".  The first-defender scan
this replaces did exactly that, silently, for every crowd-control mark.
"""

import pytest

from src.calculator.program import route

ROSTER = 5
CTX = route.RouteContext(
    author=0,
    holder=0,
    pair_defender=3,
    teammates=(1, 2),
    opponents=(3, 4),
    trigger_subjects=(3, 4),
)


class TestResolutionIsTotal:
    """Every member of the closed union has a branch, and nothing else does."""

    def test_the_union_has_ten_members(self) -> None:
        assert len(route.ROUTE_POLICIES) == 10

    @pytest.mark.parametrize("policy_type", route.ROUTE_POLICIES)
    def test_every_policy_resolves_or_names_why_it_cannot(
        self, policy_type: type
    ) -> None:
        """No member falls through to a default — the failure mode being closed."""
        policy = (
            policy_type(1)
            if policy_type in (route.OneTeammate, route.SelfAndOneTeammate)
            else (
                policy_type((1, 2))
                if policy_type is route.ExplicitTargets
                else policy_type()
            )
        )
        assert isinstance(route.resolve_route(policy, CTX, roster_size=ROSTER), tuple)

    def test_a_type_outside_the_union_raises(self) -> None:
        with pytest.raises(TypeError, match="closed"):
            route.resolve_route(object(), CTX, roster_size=ROSTER)  # type: ignore[arg-type]


class TestEachPolicyDeliversWhatItNames:
    """One assertion per delivery shape, against one context."""

    @pytest.mark.parametrize(
        ("policy", "subjects"),
        [
            (route.SelfOnly(), (0,)),
            (route.Holder(), (0,)),
            (route.PairDefender(), (3,)),
            (route.AllOpponents(), (3, 4)),
            (route.AllTeammates(), (1, 2)),
            (route.SelfAndAllTeammates(), (0, 1, 2)),
            (route.OneTeammate(2), (2,)),
            (route.SelfAndOneTeammate(2), (0, 2)),
            (route.ExplicitTargets((4,)), (4,)),
            (route.TriggerTarget(), (3, 4)),
        ],
    )
    def test_the_policy_delivers_its_subjects(
        self, policy: route.RoutePolicy, subjects: tuple
    ) -> None:
        assert route.resolve_route(policy, CTX, roster_size=ROSTER) == subjects


class TestFailClosed:
    """The half the first-defender scan did not have."""

    def test_a_trigger_that_reached_nobody_routes_to_nobody_loudly(self) -> None:
        """Never roster slot zero, which is what the deleted scan returned."""
        ctx = route.RouteContext(author=0, holder=0, trigger_subjects=())
        with pytest.raises(route.UnroutableEvent) as caught:
            route.resolve_route(route.TriggerTarget(), ctx, roster_size=ROSTER)
        assert "roster slot zero" in caught.value.reason

    def test_a_pair_policy_with_no_pair_defender_raises(self) -> None:
        ctx = route.RouteContext(author=0, holder=0)
        with pytest.raises(route.UnroutableEvent):
            route.resolve_route(route.PairDefender(), ctx, roster_size=ROSTER)

    @pytest.mark.parametrize("slot", [-1, ROSTER, ROSTER + 3])
    def test_a_subject_outside_the_roster_raises(self, slot: int) -> None:
        """A stale index would otherwise read as somebody else's state."""
        with pytest.raises(route.UnroutableEvent, match="outside a roster"):
            route.resolve_route(route.ExplicitTargets((slot,)), CTX, roster_size=ROSTER)

    def test_an_empty_opponent_roster_is_a_legal_empty_answer(self) -> None:
        """Emptiness is legal only where the policy's own docstring says so."""
        ctx = route.RouteContext(author=0, holder=0, opponents=())
        assert route.resolve_route(route.AllOpponents(), ctx, roster_size=ROSTER) == ()


class TestAnnotationsCannotRoute:
    """A disclosure qualifies a number; it never decides who receives one."""

    def test_an_annotation_has_no_resolution_branch(self) -> None:
        assert route.RouteAnnotation not in route.ROUTE_POLICIES

    def test_annotations_ride_the_resolved_route(self) -> None:
        note = route.RouteAnnotation("aura_range", "assumes every enemy in range")
        ctx = route.RouteContext(
            author=0, holder=0, opponents=(3, 4), annotations=(note,)
        )
        resolved = route.resolve(route.AllOpponents(), ctx, roster_size=ROSTER)
        assert resolved.subjects == (3, 4)
        assert resolved.annotations == (note,)
