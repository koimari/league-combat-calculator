"""Scoring one candidate build through the same run_fight the manual path uses."""

from collections.abc import Iterable, Mapping
from typing import Any

from .build_receipts import _public_build_receipt
from .defensive_effects import resolve_starting_defenses
from .fight_params import FightParams
from .optimizer_candidates import _build_gold
from .participant_timeline import build_participant_timeline
from .pipeline import run_fight
from .timeline_coverage import (
    aggregate_timeline_coverage,
    applicability_exclusion_sources,
)
from .work_counters import WorkCounterSink


def evaluate_build(
    champion_data: dict[str, Any],
    level: int,
    items: list[dict[str, Any]],
    fight_params: FightParams | tuple[FightParams, ...],
    *,
    objective: str,
    gold_budget: int | None = None,
    timeline_audit: dict[str, Any] | None = None,
    require_complete_timeline: bool = False,
    combat_context: dict[str, Any] | None = None,
    work_counters: WorkCounterSink | None = None,
) -> float:
    """Evaluate a build, reusing this search's score for an exact repeat.

    Hill climbing re-proposes builds the greedy phase already scored (a swap
    trial that reverses an earlier improvement recreates a scored build).
    Scoring is deterministic for an identical ordered item list, so a repeat
    replays the recorded score and its ordering-audit contribution instead of
    re-simulating the roster.  The public receipts are byte-identical.

    This is also the campaign's proposal counter (runbook R-24): every
    candidate any regime proposes arrives here.  The memo *misses* are
    counted one layer down, in the function that pays for them.
    """
    if work_counters is not None:
        work_counters.measured_proposals += 1
    score_memo = combat_context.get("score_memo") if combat_context else None
    if score_memo is None:
        return _evaluate_build_uncached(
            champion_data,
            level,
            items,
            fight_params,
            objective=objective,
            gold_budget=gold_budget,
            timeline_audit=timeline_audit,
            require_complete_timeline=require_complete_timeline,
            combat_context=combat_context,
            work_counters=work_counters,
        )
    memo_key = tuple(item["name"] for item in items)
    hit = score_memo.get(memo_key)
    # An entry recorded without an audit (the purchase baseline scores the
    # current loadout outside the candidate audit) carries no delta and no
    # withheld-build row; serving it to an audited caller would drop the
    # candidate from the receipts silently.  Re-evaluate instead — line
    # below overwrites the entry with a real delta.
    if hit is not None and timeline_audit is not None and hit[1] is None:
        hit = None
    if hit is not None:
        score, audit_delta = hit
        if timeline_audit is not None and audit_delta is not None:
            timeline_audit["evaluations"] += audit_delta["evaluations"]
            timeline_audit["partial_evaluations"] += audit_delta["partial_evaluations"]
            timeline_audit["excluded_evaluations"] += audit_delta[
                "excluded_evaluations"
            ]
            timeline_audit["exact_sources"].update(audit_delta["exact_sources"])
            timeline_audit["coarse_sources"].update(audit_delta["coarse_sources"])
            timeline_audit["excluded_sources"].update(audit_delta["excluded_sources"])
        return score
    audit_before = (
        None
        if timeline_audit is None
        else (
            timeline_audit["evaluations"],
            timeline_audit["partial_evaluations"],
            timeline_audit["excluded_evaluations"],
            set(timeline_audit["exact_sources"]),
            set(timeline_audit["coarse_sources"]),
            set(timeline_audit["excluded_sources"]),
        )
    )
    score = _evaluate_build_uncached(
        champion_data,
        level,
        items,
        fight_params,
        objective=objective,
        gold_budget=gold_budget,
        timeline_audit=timeline_audit,
        require_complete_timeline=require_complete_timeline,
        combat_context=combat_context,
        work_counters=work_counters,
    )
    audit_delta = None
    if audit_before is not None:
        audit_delta = {
            "evaluations": timeline_audit["evaluations"] - audit_before[0],
            "partial_evaluations": (
                timeline_audit["partial_evaluations"] - audit_before[1]
            ),
            "excluded_evaluations": (
                timeline_audit["excluded_evaluations"] - audit_before[2]
            ),
            "exact_sources": timeline_audit["exact_sources"] - audit_before[3],
            "coarse_sources": timeline_audit["coarse_sources"] - audit_before[4],
            "excluded_sources": (timeline_audit["excluded_sources"] - audit_before[5]),
        }
    score_memo[memo_key] = (score, audit_delta)
    return score


def _evaluate_build_uncached(
    champion_data: dict[str, Any],
    level: int,
    items: list[dict[str, Any]],
    fight_params: FightParams | tuple[FightParams, ...],
    *,
    objective: str,
    gold_budget: int | None = None,
    timeline_audit: dict[str, Any] | None = None,
    require_complete_timeline: bool = False,
    combat_context: dict[str, Any] | None = None,
    work_counters: WorkCounterSink | None = None,
) -> float:
    """Evaluate a build and return the damage score for the given objective.

    Creates fresh copies of mutable state to avoid cross-call contamination.

    This is the simulation the search pays for, so it is where a memo miss is
    counted (R-24) — one increment in the function that does the work, rather
    than one beside every branch that decides to call it.
    """
    if work_counters is not None:
        work_counters.score_memo_misses += 1
    if gold_budget is not None and _build_gold(items) > gold_budget:
        return float("-inf")
    targets = fight_params if isinstance(fight_params, tuple) else (fight_params,)
    if combat_context is not None and (
        combat_context.get("enemies") or combat_context.get("allies")
    ):
        # Score the same event-ordered participant timeline exposed by
        # /api/calculate.  A candidate's outgoing damage after its own death
        # is excluded, so a glass-cannon build cannot win by living only on
        # paper.  No role/archetype weight is introduced here.
        base_params = targets[0]
        stats = base_params.pre_combat_stats(champion_data, level, items)
        defenses = resolve_starting_defenses(
            champion_data["name"],
            level,
            stats,
            items,
            item_options=base_params.item_options,
        )
        combat = build_participant_timeline(
            champion_data,
            level,
            items,
            base_params,
            main_stats=stats,
            main_defenses=defenses,
            enemies=list(combat_context.get("enemies", [])),
            allies=list(combat_context.get("allies", [])),
            pair_result_cache=combat_context.get("pair_result_cache"),
            search_context=combat_context.get("search_context"),
            # Typed objectives score from the serialized events list
            # below, so they need the full receipt; total damage scores
            # from the breakdown row and can take the scoring subset.
            include_receipt=objective in ("physical_damage", "magic_damage"),
            # Nobody reads this payload.  A search evaluates thousands of
            # candidates and shows none of them, so the parallel
            # dispositions map would be a few hundred dict entries per
            # evaluation describing a payload that is compared and thrown
            # away -- which the phase's allocation gate measures and
            # refuses.  Said here, at the one call site it is true of,
            # rather than assumed inside a view on every caller's behalf.
            published=False,
            # ``stats`` above used this exact configuration; the claim
            # only holds when no external ally bonuses were folded in,
            # because pair fights strip those.
            reuse_main_stats=not base_params.ally_stat_bonuses,
        )
        coverage = combat.get("timeline_coverage", {})
        excluded_sources = (
            applicability_exclusion_sources(coverage)
            if require_complete_timeline
            else []
        )
        if timeline_audit is not None:
            timeline_audit["evaluations"] += 1
            timeline_audit["exact_sources"].update(coverage.get("exact_sources", []))
            # Coupled searches score through this full participant timeline.
            # Keep its receipt attached to the exact build so the public
            # ranked row cannot later substitute a raw pair-fight receipt.
            timeline_audit.setdefault("build_coverages", {})[
                _build_receipt_key(items)
            ] = dict(coverage)
            if excluded_sources:
                # These three item packets have correct aggregate damage but
                # no sourced hit boundary in a generic cast.  They are safe
                # to exclude before ranking, unlike an unknown partial source.
                # Keep the full coarse receipt on the candidate row while
                # keeping the search-level certification about scored builds.
                timeline_audit["excluded_evaluations"] += 1
                timeline_audit["excluded_sources"].update(excluded_sources)
                timeline_audit.setdefault("withheld_builds", {})[
                    _build_receipt_key(items)
                ] = _public_build_receipt(
                    items,
                    coverage,
                    "candidate_excluded_unresolved_timing",
                    exclusion_type="applicability",
                )
            else:
                timeline_audit["coarse_sources"].update(
                    coverage.get("coarse_sources", [])
                )
            if not coverage.get("complete", False) and not excluded_sources:
                timeline_audit["partial_evaluations"] += 1
                # The reason names the disposition: under a complete-timeline
                # requirement this candidate is dropped from ranking just
                # below, while otherwise it stays ranked with a partial
                # receipt.  One code per disposition, like its siblings.
                timeline_audit.setdefault("withheld_builds", {})[
                    _build_receipt_key(items)
                ] = _public_build_receipt(
                    items,
                    coverage,
                    (
                        "candidate_withheld_partial_event_order"
                        if require_complete_timeline
                        else "partial_event_order"
                    ),
                )
        if require_complete_timeline and not coverage.get("complete", False):
            # A coupled optimizer must never rank a candidate whose own
            # timeline is only phase-ordered.  Exclude it from the search and
            # let the caller apply the best fully ordered candidate instead of
            # withholding the entire main build because another candidate was
            # ineligible for exact scoring.
            return float("-inf")
        # A coupled roster may contain a sourced champion effect whose exact
        # sub-hit cadence is not yet certified.  Keep the candidate usable,
        # but preserve the partial receipt so the result cannot be presented
        # as a fully certified BIS claim.
        main_row = next(
            (
                row
                for row in combat.get("breakdown", [])
                if row.get("participant_id") == "main"
            ),
            None,
        )
        if main_row is None:
            return float("-inf")
        if objective == "physical_damage":
            death_time = next(
                row.get("survival", {}).get("death_time")
                for row in combat.get("participants", [])
                if row.get("participant_id") == "main"
            )
            cutoff = (
                base_params.fight_duration_seconds if death_time is None else death_time
            )
            return sum(
                float(event.get("damage", 0.0))
                for event in combat.get("events", [])
                if event.get("attacker") == "main"
                and event.get("damage_type") == "physical"
                and float(event.get("time", 0.0)) <= cutoff
            )
        if objective == "magic_damage":
            death_time = next(
                row.get("survival", {}).get("death_time")
                for row in combat.get("participants", [])
                if row.get("participant_id") == "main"
            )
            cutoff = (
                base_params.fight_duration_seconds if death_time is None else death_time
            )
            return sum(
                float(event.get("damage", 0.0))
                for event in combat.get("events", [])
                if event.get("attacker") == "main"
                and event.get("damage_type") == "magic"
                and float(event.get("time", 0.0)) <= cutoff
            )
        if objective == "total_damage":
            # The participant timeline already truncates the main actor's
            # output at its event-ordered death time.  Effective health is a
            # receipt component describing that survival window; it is not
            # part of the primary damage score.
            primary_score = float(main_row.get("total_damage", 0.0))
        else:
            primary_score = float(main_row.get("total_damage", 0.0))

        # Equal-damage coupled builds still need a deterministic, sourced
        # decision.  Damage is capped by a kill, so every build that clears
        # the roster inside the window deals the same total; rank those by
        # how much window remains after each enemy death (faster kill first)
        # and only then by the buyer's effective health.  Both terms are
        # infinitesimal against the 0.1-damage receipt rounding, and the
        # kill term dominates the health term — otherwise the tie-break
        # elects tank items on a mage the moment every candidate build
        # secures the kill (the Warmog's-on-Syndra regression).
        if timeline_audit is not None:
            main_survival = next(
                (
                    row.get("survival", {})
                    for row in combat.get("participants", [])
                    if row.get("participant_id") == "main"
                ),
                {},
            )
            effective_health = max(
                0.0, float(main_survival.get("effective_health", 0.0))
            )
            duration = base_params.fight_duration_seconds
            kill_margin = sum(
                duration - float(row["survival"]["death_time"])
                for row in combat.get("participants", [])
                if row.get("team") == "enemy"
                and row.get("survival", {}).get("death_time") is not None
            )
            return primary_score + kill_margin * 1e-4 + effective_health * 1e-9
        return primary_score
    results: list[dict[str, Any]] = []
    for target_params in targets:
        result = run_fight(champion_data, level, items, target_params)
        results.append(result)
    coverage = aggregate_timeline_coverage(results)
    excluded_sources = (
        applicability_exclusion_sources(coverage) if require_complete_timeline else []
    )
    if timeline_audit is not None:
        timeline_audit["evaluations"] += 1
        timeline_audit["exact_sources"].update(coverage["exact_sources"])
        if excluded_sources:
            timeline_audit["excluded_evaluations"] += 1
            timeline_audit["excluded_sources"].update(excluded_sources)
            timeline_audit.setdefault("withheld_builds", {})[
                _build_receipt_key(items)
            ] = _public_build_receipt(
                items,
                coverage,
                "candidate_excluded_unresolved_timing",
                exclusion_type="applicability",
            )
        else:
            timeline_audit["coarse_sources"].update(coverage["coarse_sources"])
        if not coverage["complete"] and not excluded_sources:
            timeline_audit["partial_evaluations"] += 1
            # Same disposition split as the coupled path above: dropped from
            # ranking under a complete-timeline requirement, kept with a
            # partial receipt otherwise.
            timeline_audit.setdefault("withheld_builds", {})[
                _build_receipt_key(items)
            ] = _public_build_receipt(
                items,
                coverage,
                (
                    "candidate_withheld_partial_event_order"
                    if require_complete_timeline
                    else "partial_event_order"
                ),
            )
    if require_complete_timeline and not coverage["complete"]:
        return float("-inf")

    def included(entry: Mapping[str, Any]) -> bool:
        if objective == "physical_damage":
            return entry.get("damage_type") == "physical"
        if objective == "magic_damage":
            return entry.get("damage_type") == "magic"
        return True

    total = sum(
        entry.get("total_damage", 0.0)
        for result in results
        for entry in result.get("breakdown", {}).values()
        if included(entry)
    )
    if objective == "total_damage":
        # Informational rows are already excluded from result.total_damage,
        # whereas the breakdown can contain non-damage displays.
        total = sum(result.get("total_damage", 0.0) for result in results)

    return total


def build_timeline_coverage(
    champion_data: dict[str, Any],
    level: int,
    items: list[dict[str, Any]],
    fight_params: FightParams | tuple[FightParams, ...],
) -> dict[str, Any]:
    """Return the target-combined ordering receipt for one ranked build."""
    targets = fight_params if isinstance(fight_params, tuple) else (fight_params,)
    results = [
        run_fight(champion_data, level, items, target_params)
        for target_params in targets
    ]
    return aggregate_timeline_coverage(results)


def _build_receipt_key(items: Iterable[dict[str, Any]]) -> tuple[str, ...]:
    """Identify one evaluated build by the ordered list the score memo keys on."""
    return tuple(str(item.get("name", "")) for item in items)
