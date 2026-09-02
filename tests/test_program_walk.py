"""Phase 4 S4 — one kernel call site, and a result nothing can rewrite.

``program/walk`` is the front door for the seam that makes "one engine prices
one mechanic" structural.  Two properties are under test here, and neither is
about arithmetic: the walk adds none of its own, and what it returns is
frozen, so a view is a projection of the result rather than a sixth producer
of numbers.

Repointing the timeline's two legacy call sites at :func:`walk` is Phase 4
S9's; what S4 owes is that the seam exists, runs the kernel exactly once, and
returns exactly what the kernel produced.
"""

from types import SimpleNamespace

import pytest

from src.calculator.defensive_effects import StartingDefenses
from src.calculator.program import rung
from src.calculator.program import walk as walk_module
from src.calculator.survival import (
    ScoreLedger,
    SurvivalAction,
    TransitionContext,
    TransitionRank,
    build_states,
)
from src.calculator.survival.actions import EVENT_SLOTS, ActionKind


def one_participant_context() -> tuple[TransitionContext, ScoreLedger]:
    """A single subject with 100 health and no defensive declarations."""
    combatants = [
        SimpleNamespace(
            participant_id="target",
            stats={"health": 100.0, "is_melee": True},
            defenses=StartingDefenses(
                magic_shield=0.0,
                physical_shield=0.0,
                general_shield=0.0,
                healing_received_multiplier=1.0,
            ),
        )
    ]
    ledger = ScoreLedger(1)
    ctx = TransitionContext(
        duration=5.0,
        states=build_states(combatants, (0.0,)),
        combatants=combatants,
        index_of={"target": 0},
        ledger=ledger,
        regeneration_windows=(None,),
    )
    return ctx, ledger


def damage_action(amount: float) -> SurvivalAction:
    """One plain damage packet at t=0 against the single subject."""
    return SurvivalAction(
        sort_key=(0.0, TransitionRank.DAMAGE, 0, 0, "", "target", "e", "s"),
        time=0.0,
        phase=TransitionRank.DAMAGE,
        kind=ActionKind.PLAIN_DAMAGE,
        subject=0,
        attacker=0,
        aidx=0,
        amount=amount,
        damage_type="true",
        source_key="s",
        source="s",
        event_slot=EVENT_SLOTS.slot("program-walk-fixture"),
        sequence=0,
    )


class TestTheSeamRunsTheKernelAndNothingElse:
    """A body of one call and one record."""

    def test_the_result_carries_exactly_the_actions_it_was_given(self) -> None:
        ctx, _ = one_participant_context()
        actions = [damage_action(30.0)]
        result = walk_module.walk(actions, ctx)
        assert result.actions == tuple(actions)

    def test_the_kernel_actually_ran(self) -> None:
        """The one number the fixture asserts: 30 damage was applied."""
        ctx, ledger = one_participant_context()
        walk_module.walk([damage_action(30.0)], ctx)
        assert ledger.applied == [30.0]

    def test_the_walk_does_not_reorder_what_it_was_handed(self) -> None:
        """Sorting twice by two rules is how two engines end up disagreeing."""
        ctx, _ = one_participant_context()
        later = damage_action(10.0)._replace(time=1.0, aidx=1)
        earlier = damage_action(20.0)
        result = walk_module.walk([later, earlier], ctx)
        assert [action.amount for action in result.actions] == [10.0, 20.0]


class TestTheResultIsFrozen:
    """A view projects the result; it may not become a second producer."""

    def test_the_record_rejects_assignment(self) -> None:
        ctx, _ = one_participant_context()
        result = walk_module.walk([damage_action(5.0)], ctx)
        with pytest.raises(AttributeError):
            result.rung = rung.CompiledFull()  # type: ignore[misc]

    def test_the_rung_rides_the_result_rather_than_the_caller(self) -> None:
        ctx, _ = one_participant_context()
        reason = "delta_amp is not representable in the score kernel"
        result = walk_module.walk(
            [damage_action(5.0)], ctx, rung=rung.ReceiptWalk(reason)
        )
        assert rung.reason_of(result.rung) == reason

    def test_the_states_come_back_as_a_tuple(self) -> None:
        ctx, _ = one_participant_context()
        result = walk_module.walk([damage_action(5.0)], ctx)
        assert isinstance(result.states, tuple)
        assert len(result.states) == 1


class TestTheWalkFoldsWhatItsStateImplies:
    """The three numbers the survival view must not add for itself.

    Criterion 3 forbids a view performing arithmetic on ledger values, and
    ``remaining_shield``, ``ending_health_ratio`` and ``effective_health``
    were three sums the projection ran over the settled pools.  They belong
    to the walk that settled them: what a view receives has to be a leaf, or
    the projection is a second producer of the number it claims to project.
    """

    def test_every_settled_state_is_folded(self) -> None:
        ctx, _ = one_participant_context()
        result = walk_module.walk([damage_action(30.0)], ctx)
        assert len(result.survival) == len(result.states)

    def test_the_ending_health_ratio_is_the_settled_pools_own(self) -> None:
        ctx, _ = one_participant_context()
        result = walk_module.walk([damage_action(30.0)], ctx)
        pools = result.states[0]["pools"]
        assert result.survival[0].ending_health_ratio == pools.health / pools.max_health

    def test_a_participant_with_no_maximum_health_reads_zero_not_a_raise(self) -> None:
        """Division by a zero pool is the one guarded case, and it stays."""
        ctx, _ = one_participant_context()
        result = walk_module.walk([damage_action(0.0)], ctx)
        result.states[0]["pools"].max_health = 0.0
        assert walk_module.survival_folds(result.states)[0].ending_health_ratio == 0.0

    def test_the_remaining_shield_is_the_three_pools_summed(self) -> None:
        ctx, _ = one_participant_context()
        result = walk_module.walk([damage_action(0.0)], ctx)
        pools = result.states[0]["pools"]
        pools.magic_shield, pools.physical_shield, pools.general_shield = (
            1.5,
            2.25,
            4.0,
        )
        assert walk_module.survival_folds(result.states)[0].remaining_shield == 7.75

    def test_the_effective_health_keeps_its_five_terms_in_order(self) -> None:
        """Float addition is not associative: a re-spelled sum is a new number."""
        ctx, _ = one_participant_context()
        result = walk_module.walk([damage_action(0.0)], ctx)
        state = result.states[0]
        pools = state["pools"]
        pools.max_health, pools.shield_expired = 0.1, 0.3
        state["starting_shield"] = 0.2
        state["support_shield_received"] = 0.4
        state["healing_received"] = 0.5
        assert walk_module.survival_folds([state])[0].effective_health == (
            0.1 + 0.2 + 0.4 - 0.3 + 0.5
        )

    def test_the_fold_is_the_walks_and_not_a_projection_a_caller_hands_back(
        self,
    ) -> None:
        """``projected`` names the folds a composition may supply; not this one."""
        ctx, _ = one_participant_context()
        result = walk_module.walk([damage_action(5.0)], ctx)
        with pytest.raises(TypeError, match="declares no fold named survival"):
            result.projected(survival=())


class TestOneWalkPerPassAtRuntime:
    """Criterion 1's two runtime clauses, which source counting cannot see.

    One ``run_survival_walk(`` call expression in ``src/`` says a second
    engine has not been *written*.  It says nothing about a composition that
    enters the one engine twice per pass under two names, which is the shape
    the incident actually had -- so the property is read at runtime, off the
    same threaded sink every other work counter uses (R-24), and never off a
    monkey-patched module attribute.

    The pass count is the roster's own: ``pass_count`` over the declared
    cross-pass dependencies, one for almost every roster and two for a build
    whose restore ledger is a function of the fight it is in.
    """

    @staticmethod
    def _sink():
        """A counter sink shaped exactly like the harness's own."""
        from scripts.bench_coupled_optimizer import WorkCounters

        return WorkCounters()

    def test_one_candidate_evaluation_enters_the_kernel_once_per_pass(self) -> None:
        from src.calculator import participant_timeline as timeline_module
        from src.calculator.data_fetcher import get_item_by_name
        from src.calculator.participant_timeline import CoupledSearchContext
        from src.calculator.program.dependency import pass_count
        from tests.test_participant_timeline import _coupled_fixture

        sink = self._sink()
        timeline = _coupled_fixture()
        items = [get_item_by_name("Rabadon's Deathcap")]
        timeline(
            items,
            include_receipt=False,
            search_context=CoupledSearchContext(work_counters=sink),
        )
        passes = pass_count(
            timeline_module._cross_pass_dependencies(  # pylint: disable=W0212
                items, (), ()
            )
        )
        assert passes == 1
        assert sink.walk_invocations == passes

    def test_a_two_pass_roster_prices_its_fight_once_inside_its_two_passes(
        self,
    ) -> None:
        """The declared pass budget is a ceiling the composition does not spend.

        Criterion 1 asks for ``len(passes)`` invocations, and a Catalyst
        roster runs two passes and enters the kernel **once** -- which is
        stronger than the criterion, not weaker, and is worth a test rather
        than a discovery.  S8's first pass exists to derive the restore
        ledger the second is priced with: it composes the roster, reads the
        incoming champion damage, and returns a ``PassRequest`` *before* the
        walk, so the fight is walked once, by the pass that knows the
        restores.  The recursion this replaced walked the same fight from
        inside a call to itself, where the count could not be taken at all.

        The bound is what is asserted, so a pass that started walking
        speculatively would fail here even though it would still be one walk
        per pass.
        """
        from src.calculator import participant_timeline as timeline_module
        from src.calculator.participant_timeline import (
            CoupledSearchContext,
            build_participant_timeline,
        )
        from src.calculator.pipeline import FightParams
        from src.calculator.program.dependency import pass_count
        from src.calculator.scenario import ChampionLoadout

        main = ChampionLoadout(
            champion="Ahri", level=13, role="mid", items=("Catalyst of Aeons",)
        ).resolve()
        enemies = [
            ChampionLoadout(champion=name, level=13, role="top").resolve()
            for name in ("Aatrox", "Malphite")
        ]
        composed: list[int] = []
        original = timeline_module._compose_pass  # pylint: disable=W0212

        def spy(*args, **kwargs):
            composed.append(kwargs["pass_index"])
            return original(*args, **kwargs)

        sink = self._sink()
        timeline_module._compose_pass = spy  # pylint: disable=W0212
        try:
            build_participant_timeline(
                main.champion_data,
                main.request.level,
                list(main.item_data),
                FightParams.from_request(
                    {"fight_mode": "one_rotation", "role": "mid"}, deterministic=True
                ),
                main_stats=main.stats,
                main_defenses=main.defenses,
                enemies=enemies,
                allies=[],
                search_context=CoupledSearchContext(work_counters=sink),
            )
        finally:
            timeline_module._compose_pass = original  # pylint: disable=W0212

        budget = pass_count(
            timeline_module._cross_pass_dependencies(  # pylint: disable=W0212
                list(main.item_data), enemies, []
            )
        )
        assert composed == [1, 2]
        assert budget == 2
        assert sink.walk_invocations == 1
        assert sink.walk_invocations <= budget

    def test_the_compiled_routing_also_enters_the_kernel_once_per_pass(self) -> None:
        """The counter is threaded into both routings; both are fixtured.

        ``_score_with_search_context`` passes ``context.work_counters`` to
        the seam exactly as the composition path does, so the compiled lane
        has the same one-walk-per-pass obligation -- and a counter that is
        threaded but never read on one of two routings is a counter nobody
        would notice losing.  The rung assertion is what makes the walk
        count mean anything here: without it a fallback to the receipt walk
        would satisfy ``walk_invocations == 1`` while measuring the routing
        this test does not name.
        """
        from src.calculator.data_fetcher import get_champion, get_item_by_name
        from src.calculator.defensive_effects import resolve_starting_defenses
        from src.calculator.participant_timeline import (
            CoupledSearchContext,
            build_participant_timeline,
        )
        from src.calculator.pipeline import FightParams
        from src.calculator.scenario import ChampionLoadout
        from src.calculator.stats import calculate_total_stats
        from src.calculator.work_counters import Rung

        champion = get_champion("Ahri")
        items = [get_item_by_name("Luden's Echo")]
        stats = calculate_total_stats(champion, 13, items, role="mid")
        enemies = [ChampionLoadout(champion="Aatrox", level=13, role="top").resolve()]
        sink = self._sink()
        build_participant_timeline(
            champion,
            13,
            items,
            FightParams.from_request(
                {"fight_mode": "one_rotation", "role": "mid"}, deterministic=True
            ),
            main_stats=stats,
            main_defenses=resolve_starting_defenses("Ahri", 13, stats, items),
            enemies=enemies,
            allies=[],
            include_receipt=False,
            pair_result_cache={},
            search_context=CoupledSearchContext(work_counters=sink),
        )
        assert sink.rungs[str(Rung.COMPILED)] == 1
        assert sink.walk_invocations == 1

    def test_with_no_sink_installed_the_counter_costs_one_is_none_test(self) -> None:
        """R-24's other half: the seam is inert when nobody is measuring."""
        ctx, _ = one_participant_context()
        walk_module.walk([damage_action(1.0)], ctx)  # no sink; must not raise

    def test_the_sink_the_harness_ships_carries_the_field(self) -> None:
        """A counter the protocol declares and the concrete sink lacks is not one."""
        sink = self._sink()
        assert sink.walk_invocations == 0
        from src.calculator.work_counters import record_walk

        record_walk(sink)
        assert sink.walk_invocations == 1

    def test_the_walk_count_is_not_one_of_the_reported_counter_families(self) -> None:
        """The runbook pins the report's shape at four families; this is a fifth."""
        assert "walk_invocations" not in self._sink().as_dict()


class TestEveryViewOfOneRequestProjectsOneWalk:
    """Criterion 1's third clause: one walk, not two under new names.

    "One call site, one walk per pass" is satisfied by a composition that
    builds one program for the score projection and a second for the receipt
    projection -- two walks wearing one name.  What forbids that is
    identity: the record every view of one request reads has to be *the*
    walk the kernel produced, and not an equal one.

    **The criterion says "the same object (``is``)", and it is asserted on
    ``is``.**  What carries the identity is
    :class:`~src.calculator.program.walk.WalkOrigin`, minted once per entry
    into the kernel and carried unchanged by every descendant, because the
    *record* cannot be the object: ``WalkResult`` is frozen precisely so a
    view cannot be a sixth producer of numbers, so a fold added after the
    walk -- the attacker outcomes derived from the breakdown, the public
    event lists derived from the receipt composition -- can only arrive as
    ``replace``.  Three folds land between the first view and the last, so
    no two views can receive one *record* without the folds being computed
    before the views that produce them, which is circular.  The token is the
    part of the record that has no such obligation, and "one walk" is
    exactly what it says.

    Two independent readings, so neither carries it alone: every view input
    carries the kernel's own ``origin`` object by identity, and its own
    ``actions``, ``states`` and ``survival`` by identity too.  A second walk
    fails both; a re-projection fails neither, and a re-projection is not a
    second engine.
    """

    @staticmethod
    def _one_request(monkeypatch) -> tuple[list, dict[str, list]]:
        """The walks one calculate request ran, and what each view was given."""
        from src.calculator import participant_timeline as timeline_module
        from src.calculator.pipeline import FightParams
        from src.calculator.scenario import ChampionLoadout

        walked: list = []
        seen: dict[str, list] = {"breakdown": [], "receipt": [], "survival": []}

        original_walk = timeline_module._walk  # pylint: disable=W0212

        def walk_spy(*args, **kwargs):
            result = original_walk(*args, **kwargs)
            walked.append(result)
            return result

        monkeypatch.setattr(timeline_module, "_walk", walk_spy)

        for name, module, attribute in (
            ("breakdown", timeline_module._breakdown_view, "breakdown"),
            ("receipt", timeline_module._receipt_view, "receipt"),
            ("survival", timeline_module._survival_view, "survival_leaves"),
        ):
            original = getattr(module, attribute)

            def spy(*args, _name=name, _original=original, **kwargs):
                seen[_name].append(args[1])
                return _original(*args, **kwargs)

            monkeypatch.setattr(module, attribute, spy)

        main = ChampionLoadout(
            champion="Ahri", level=13, role="mid", items=("Luden's Echo",)
        ).resolve()
        enemies = [ChampionLoadout(champion="Aatrox", level=13, role="top").resolve()]
        timeline_module.build_participant_timeline(
            main.champion_data,
            main.request.level,
            list(main.item_data),
            FightParams.from_request(
                {"fight_mode": "one_rotation", "role": "mid"}, deterministic=True
            ),
            main_stats=main.stats,
            main_defenses=main.defenses,
            enemies=enemies,
            allies=[],
        )
        return walked, seen

    def test_the_request_ran_exactly_one_walk(self, monkeypatch) -> None:
        walked, seen = self._one_request(monkeypatch)
        assert len(walked) == 1
        assert [len(records) for records in seen.values()] == [1, 1, 1]

    def test_every_view_is_given_the_same_walk_object(self, monkeypatch) -> None:
        """The criterion's ``is``, on the object that can carry it."""
        walked, seen = self._one_request(monkeypatch)
        kernel = walked[0]
        for name, records in seen.items():
            assert records[0].origin is kernel.origin, name

    def test_every_view_reads_that_walks_own_actions_states_and_folds(
        self, monkeypatch
    ) -> None:
        walked, seen = self._one_request(monkeypatch)
        kernel = walked[0]
        for name, records in seen.items():
            given = records[0]
            assert given.actions is kernel.actions, name
            assert given.states is kernel.states, name
            assert given.survival is kernel.survival, name

    def test_a_projection_keeps_the_origin_it_descends_from(self) -> None:
        """``projected`` is a descendant of one walk, not a new one."""
        ctx, _ = one_participant_context()
        result = walk_module.walk([damage_action(5.0)], ctx)
        assert result.projected(damage_events=()).origin is result.origin

    def test_a_projection_may_not_re_mint_the_origin(self) -> None:
        """Otherwise a second walk could be laundered into a projection."""
        ctx, _ = one_participant_context()
        result = walk_module.walk([damage_action(5.0)], ctx)
        with pytest.raises(TypeError, match="declares no fold named origin"):
            result.projected(origin=walk_module.WalkOrigin())

    def test_a_second_walk_would_not_pass_that(self, monkeypatch) -> None:
        """R-05: the check ships with a red it can produce on demand.

        Two walks of the same fight are equal and are not identical, which
        is the whole reason the assertion is written on identity.  The
        origin is ``compare=False`` exactly so this fixture can be both at
        once: equal as a result, and a second entry into the kernel.
        """
        walked, _ = self._one_request(monkeypatch)
        kernel = walked[0]
        second = walk_module.WalkResult(
            actions=(*kernel.actions,),
            states=(*kernel.states,),
            coverage=kernel.coverage,
            rung=kernel.rung,
            duration=kernel.duration,
            survival=kernel.survival,
        )
        assert second == kernel
        assert second.actions is not kernel.actions
        assert second.origin is not kernel.origin

    def test_two_entries_into_the_kernel_mint_two_origins(self) -> None:
        """The token is per entry, so a second walk cannot borrow the first's."""
        first_ctx, _ = one_participant_context()
        second_ctx, _ = one_participant_context()
        first = walk_module.walk([damage_action(5.0)], first_ctx)
        second = walk_module.walk([damage_action(5.0)], second_ctx)
        assert first.origin is not second.origin
        assert first.origin != second.origin
