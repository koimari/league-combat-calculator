"""The optimizer's work-counter seam: it counts, and it changes no number.

Three of the four counter families the campaign gates on had no producing
tool at all, so the numbers in the performance contract could not be
reproduced by anyone.  These tests pin the seam that produces them: that a
sink threaded onto the search sees every proposal, every memo miss, every
pair fight and every fallback rung; that the receipt walk can be forced from
the same entry point and still elects the same build; and that with no sink
installed the search is byte-identical.
"""

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from src.calculator import participant_timeline
from src.calculator.data_fetcher import get_champion
from src.calculator.optimizer import (
    _evaluate_build,
    optimize_build,
    optimize_purchase,
)
from src.calculator.participant_timeline import CoupledSearchContext
from src.calculator.pipeline import FightParams
from src.calculator.scenario import ChampionLoadout
from src.calculator.work_counters import Rung, record_rung

REPO_ROOT = Path(__file__).resolve().parent.parent

# One fully locked build, so the exact regime scores exactly one candidate:
# the counters are then small enough to state exactly rather than bound.
LOCKED_ITEMS = [
    "Rabadon's Deathcap",
    "Void Staff",
    "Stormsurge",
    "Rylai's Crystal Scepter",
    "Malignance",
]
LOCKED_BOOTS = "Sorcerer's Shoes"


@dataclass(slots=True)
class _Sink:
    """The five mutable fields ``WorkCounterSink`` asks for.

    ``walk_invocations`` is the odd one out and is here for the same reason
    the others are: Phase 4 S10 made "one walk per pass" a number a test can
    read rather than a call-site count, so the protocol asks for a field the
    kernel seam increments.  It is not a reported counter family.
    """

    measured_proposals: int = 0
    score_memo_misses: int = 0
    pair_run_fight_calls: int = 0
    walk_invocations: int = 0
    rungs: Counter = field(default_factory=Counter)
    rung_receipts: Counter = field(default_factory=Counter)


def _enemies(count: int = 1):
    """A small enemy roster — one pair fight per evaluation per enemy."""
    roster = [
        ChampionLoadout(
            champion="Alistar",
            level=13,
            role="support",
            boots="Plated Steelcaps",
            items=("Randuin's Omen",),
        ),
        ChampionLoadout(
            champion="Vayne",
            level=13,
            role="bottom",
            boots="Berserker's Greaves",
            items=("Kraken Slayer",),
        ),
    ]
    return [loadout.resolve() for loadout in roster[:count]]


def _single_candidate_search(**overrides):
    """One coupled ``optimize_build`` whose every slot is already locked."""
    arguments = {
        "champion_data": get_champion("Cassiopeia"),
        "level": 13,
        "fight_params": FightParams.from_request(
            {"fight_mode": "one_rotation", "role": "mid"}, deterministic=True
        ),
        "locked_items": list(LOCKED_ITEMS),
        "locked_boots": LOCKED_BOOTS,
        "max_legendary_slots": len(LOCKED_ITEMS),
        "require_complete_timeline": True,
        "enemy_loadouts": _enemies(),
    }
    arguments.update(overrides)
    return optimize_build(**arguments)


class TestCountersRideTheSearch:
    """Every family moves, and they agree with each other."""

    def test_one_locked_candidate_counts_one_proposal(self):
        sink = _Sink()
        result = _single_candidate_search(work_counters=sink)

        assert result["evaluations"] == 1
        assert sink.measured_proposals == 1
        assert sink.score_memo_misses == 1
        # One pair fight per (evaluation, enemy) is the floor; roster setup
        # and support-schedule fallbacks live above it.
        assert sink.pair_run_fight_calls >= 1

    def test_every_scored_candidate_lands_on_exactly_one_rung(self):
        sink = _Sink()
        _single_candidate_search(work_counters=sink)

        assert sum(sink.rungs.values()) == sink.score_memo_misses
        assert set(sink.rungs) <= {str(rung) for rung in Rung}

    def test_a_memo_hit_is_a_proposal_that_is_not_a_miss(self):
        sink = _Sink()
        combat_context = {
            "enemies": _enemies(),
            "allies": [],
            "pair_result_cache": {},
            "score_memo": {},
            "search_context": CoupledSearchContext(work_counters=sink),
        }
        arguments = {
            "champion_data": get_champion("Cassiopeia"),
            "level": 13,
            "items": [],
            "fight_params": FightParams.from_request(
                {"fight_mode": "one_rotation", "role": "mid"}, deterministic=True
            ),
            "objective": "total_damage",
            "combat_context": combat_context,
            "work_counters": sink,
        }
        first = _evaluate_build(**arguments)
        second = _evaluate_build(**arguments)

        assert first == second
        assert sink.measured_proposals == 2
        assert sink.score_memo_misses == 1

    def test_the_purchase_search_carries_the_same_sink(self):
        sink = _Sink()
        optimize_purchase(
            champion_data=get_champion("Cassiopeia"),
            level=13,
            available_gold=3000,
            fight_params=FightParams.from_request(
                {"fight_mode": "one_rotation", "role": "mid"}, deterministic=True
            ),
            locked_items=list(LOCKED_ITEMS[:3]),
            locked_boots=LOCKED_BOOTS,
            max_purchase_items=1,
            require_complete_timeline=True,
            enemy_loadouts=_enemies(),
            work_counters=sink,
        )

        assert sink.measured_proposals > 0
        assert sink.score_memo_misses > 0
        assert sink.pair_run_fight_calls > 0


class TestTheSeamChangesNoNumber:
    """Observation and routing may cost time; they may not move an answer."""

    def test_an_uninstrumented_search_matches_an_instrumented_one(self):
        instrumented = _single_candidate_search(work_counters=_Sink())
        bare = _single_candidate_search()

        instrumented.pop("optimization_time_ms")
        bare.pop("optimization_time_ms")
        assert instrumented == bare

    def test_forcing_the_receipt_walk_elects_the_same_build_and_score(self):
        compiled_sink = _Sink()
        walked_sink = _Sink()
        compiled = _single_candidate_search(work_counters=compiled_sink)
        walked = _single_candidate_search(
            work_counters=walked_sink, use_compiled_walk=False
        )

        compiled.pop("optimization_time_ms")
        walked.pop("optimization_time_ms")
        assert compiled == walked
        assert compiled_sink.rungs[str(Rung.COMPILED)] > 0
        assert walked_sink.rungs == Counter({str(Rung.RECEIPT_WALK_GATE): 1})


class TestRungLadder:
    """Four rungs, and a poisoned search reads as poisoned, not as a retry."""

    def test_record_rung_is_inert_without_a_sink(self):
        record_rung(None, Rung.COMPILED)  # must not raise

    def test_the_poisoned_receipt_is_named_once(self):
        source = (REPO_ROOT / "src/calculator/participant_timeline.py").read_text(
            encoding="utf-8"
        )
        assert source.count('"context_marked_uncompilable"') == 1, (
            "the poisoned-context receipt is read back by the rung ladder; "
            "spelling it twice lets the two copies drift"
        )

    def test_every_pair_fight_goes_through_the_counted_wrapper(self):
        """R-24: the residual is only a property of this module if every
        pair fight is counted, and the only way to guarantee that is for
        there to be exactly one call to ``run_fight`` in the file."""
        source = (REPO_ROOT / "src/calculator/participant_timeline.py").read_text(
            encoding="utf-8"
        )
        assert source.count("run_fight(") == source.count("_pair_run_fight(") + 1

    def test_the_wrapper_counts_without_a_search_context(self):
        assert participant_timeline._pair_run_fight is not None
        sink = _Sink()
        context = CoupledSearchContext(work_counters=sink)
        assert context.work_counters is sink
        assert context.compiled_walk_enabled is True


def test_the_counter_sink_declares_the_field_a_reason_goes_in() -> None:
    """The sink has somewhere to put the cause of a fallback.

    ``rungs`` is keyed by one of four published labels and cannot hold a
    sentence; ``rung_receipts`` is that somewhere, asserted as an exact field
    set so a seventh member is a decision somebody makes rather than one that
    arrives.
    """
    from src.calculator.work_counters import WorkCounterSink

    assert set(WorkCounterSink.__annotations__) == {
        "measured_proposals",
        "score_memo_misses",
        "pair_run_fight_calls",
        "walk_invocations",
        "rungs",
        "rung_receipts",
    }


def test_the_published_report_carries_the_causes_beside_the_histogram() -> None:
    """And it reaches a reader: the bench harness publishes the counter.

    A field on a protocol nothing serialized would be the same defect one
    layer further out, so the receipts are asserted riding beside the
    histogram in the shape ``as_dict`` publishes.
    """
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location(
        "bench_coupled_optimizer", REPO_ROOT / "scripts" / "bench_coupled_optimizer.py"
    )
    bench = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("bench_coupled_optimizer", bench)
    spec.loader.exec_module(bench)

    from src.calculator.program.rung import ReceiptWalk, counter_entry

    counters = bench.WorkCounters()
    record_rung(counters, *counter_entry(ReceiptWalk("Imperial Mandate - Command")))
    published = counters.as_dict()
    assert published["rungs"] == {"receipt_walk_candidate": 1}
    assert published["rung_receipts"] == {"Imperial Mandate - Command": 1}
