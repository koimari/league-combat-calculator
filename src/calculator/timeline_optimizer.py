"""Compiled optimizer context for coupled participant timelines.

This module owns the search-invariant roster panels and the score-only walk.
Public receipt serialization lives in ``timeline_receipts.py``.
"""

# The compiled walk keeps the legacy action shape and accepts the full search
# state. These checks keep the extracted module aligned with the source path.
# pylint: disable=protected-access,too-few-public-methods,too-many-arguments,too-many-branches,too-many-instance-attributes,too-many-locals,too-many-positional-arguments,too-many-statements

from __future__ import annotations

from collections import defaultdict
import importlib
from dataclasses import replace
from operator import itemgetter
from typing import TYPE_CHECKING, Any

from .healing import GREY_HEALTH_RULE_CHAMPIONS
from .healing_reduction import (
    champion_grievous_wound_sources,
    healing_reduction_profiles,
)
from .item_effects import ThornsEffect, serpents_fang_venom, thorns_effects
from .item_support_effects import has_event_view_support_items
from .pipeline import FightParams, run_fight
from .roster_composition import (
    Combatant,
    actor_params as _actor_params,
    defensive_signature as _defensive_signature,
    from_loadout as _from_loadout,
    target_overrides as _target_overrides,
    require_roster_fight_window_support,
)
from .survival import (
    ActionKind,
    ScoreLedger,
    SurvivalAction,
    TransitionContext,
    UncompilableActionError,
    WalkCompiler as _WalkCompiler,
    accumulate_support_values,
    accumulate_damage_totals,
    action_key as _action_key,
    assemble_survival_rows,
    build_states,
    coalesce_darius_q_heals,
    finalize_states,
    resolve_grievous as _grievous_pack,
    revive_candidate_actions,
    run_survival_walk,
    survival_action_from_event,
)
from .timeline_coverage import combine_timeline_coverages

if TYPE_CHECKING:
    from .scenario import ResolvedLoadout


def _timeline_module():
    """Load timeline-only composition helpers after module initialization."""
    return importlib.import_module(".participant_timeline", package=__package__)


class CoupledSearchContext:
    """Reusable composition state for one coupled optimizer search.

    Everything here is derived from the fixed request — the roster, the
    fight params, and per-defensive-signature panels of compiled invariant
    walk actions — so it must only ever be shared across evaluations of one
    ``optimize_build`` call.  It is pure speed: force-disabling it must
    reproduce identical results (pinned by the optimizer equivalence test).
    """

    __slots__ = (
        "panels",
        "roster_actors",
        "actor_params",
        "main_request",
        "index_of",
        "grievous_packs",
        "thorns_profiles",
        "main_pair_params",
        "roster_pair_params",
        "pair_id_strings",
        "base_compiler",
        "base_sorted",
        "base_heal_dedup",
        "validated_roster_window",
        # The main champion's wound-declaring sources are champion-fixed;
        # derived once per search instead of once per evaluation.
        "main_champion_wounds",
        # Issue #137: set when search-invariant compilation (roster pairs or
        # a signature panel) hit an unrepresentable transition; the compiled
        # path is then skipped for the rest of the search.
        "uncompilable",
    )

    def __init__(self) -> None:
        self.panels: dict[tuple[Any, ...], "_SignaturePanel"] = {}
        self.uncompilable = False
        self.roster_actors: list[Combatant] | None = None
        self.actor_params: dict[str, FightParams] = {}
        self.main_request: Any = None
        self.index_of: dict[str, int] = {}
        self.grievous_packs: dict[int, dict[str, Any]] = {}
        self.thorns_profiles: dict[int, tuple[ThornsEffect, ...]] = {}
        self.main_pair_params: list[tuple[Combatant, FightParams]] = []
        self.roster_pair_params: dict[tuple[str, str], FightParams] = {}
        self.pair_id_strings: dict[str, list[str]] = defaultdict(list)
        self.base_compiler: _WalkCompiler | None = None
        self.base_sorted: list[tuple[Any, ...]] = []
        self.base_heal_dedup: dict[int, dict[tuple[str, float], float]] = {}
        self.validated_roster_window = False
        self.main_champion_wounds: dict[str, Any] | None = None


class _SignaturePanel:
    """The invariant walk actions for one main defensive signature.

    ``sig`` holds only the fights into this signature (enemies into the
    candidate main); everything signature-independent lives in the search
    context's base compiler.  ``sorted_actions`` is the presorted merge of
    both.
    """

    __slots__ = ("sig", "n_actions", "sorted_actions")

    def __init__(self, base_sorted: list[tuple[Any, ...]], sig: _WalkCompiler) -> None:
        self.sig = sig
        self.n_actions = sig.next_aidx
        merged = base_sorted + sorted(sig.actions, key=itemgetter(0))
        merged.sort(key=itemgetter(0))
        self.sorted_actions = merged


def _grievous_packs_for(
    context: CoupledSearchContext, actor_i: int, profiles: tuple[Any, ...]
) -> dict[str, Any]:
    """Per-damage-type Grievous packs for one attacker's fixed profiles."""
    packs = context.grievous_packs.get(actor_i)
    if packs is None:
        packs = {
            damage_type: _grievous_pack(profiles, damage_type)
            for damage_type in ("physical", "magic", "true")
        }
        context.grievous_packs[actor_i] = packs
    return packs


def _context_setup(
    context: CoupledSearchContext,
    params: FightParams,
    enemies: list[ResolvedLoadout],
    allies: list[ResolvedLoadout],
    champion_name: str,
    level: int,
    pair_result_cache: dict[tuple[Any, ...], dict[str, Any]],
    all_actors_by_index: list[Combatant],
) -> None:
    """Derive the search-invariant roster state on the context's first use.

    Everything prebuilt here is per-pair, not per-candidate: actor and
    target fight params (with ``enforce_resource_limits`` pre-set so the
    engine's own forcing replace becomes a no-op), their one-time
    ``validate_for_champion`` runs, thorns profiles, and Grievous packs.
    """
    if context.roster_actors is not None:
        return
    if not context.validated_roster_window:
        require_roster_fight_window_support(params, enemies=enemies, allies=allies)
        context.validated_roster_window = True
    # Issue #137: the roster is search-invariant, so a loadout the compiled
    # kernel cannot represent poisons the whole context.  Checked BEFORE any
    # pair fight runs so the fallback costs nothing beyond the capability
    # scan.  (Defense fields are already excluded by the dispatch
    # pre-check; this covers walk-authored item mechanics.)  Warmog's Heart
    # is exempt: the roster holder's ticks compile into the base panel
    # below (issue #169).
    for loadout in (*enemies, *allies):
        if loadout.is_practice_dummy:
            continue
        item_receipt = _timeline_module()._uncompilable_item_receipt(
            loadout.item_data,
            loadout_stats=loadout.stats,
            warmog_ticks_compiled=True,
        )
        if item_receipt is not None:
            raise UncompilableActionError(
                receipt=f"roster:{loadout.champion_data.get('name', '')}:{item_receipt}",
                source=str(loadout.champion_data.get("name", "")),
                invariant=True,
            )
    ally_actors = [
        _from_loadout(f"ally:{loadout.champion_data['name']}", "ally", loadout)
        for loadout in allies
    ]
    enemy_actors = [
        _from_loadout(f"enemy:{loadout.champion_data['name']}", "enemy", loadout)
        for loadout in enemies
    ]
    context.roster_actors = [*ally_actors, *enemy_actors]
    context.index_of = {"main": 0}
    for offset, actor in enumerate(context.roster_actors, start=1):
        context.index_of[actor.participant_id] = offset
        context.thorns_profiles[offset] = thorns_effects(list(actor.items))
        _grievous_packs_for(context, offset, healing_reduction_profiles(actor.items))
        if actor.is_practice_dummy:
            continue
        context.actor_params[actor.participant_id] = _actor_params(params, actor)
    context.main_request = type(
        "MainRequest",
        (),
        {
            "role": params.role,
            "role_quest_complete": params.role_quest_complete,
            "ability_ranks": params.ability_ranks,
            "champion_options": params.champion_options,
            "cast_order": params.cast_order,
            "item_options": params.item_options,
        },
    )()
    main_params = _actor_params(
        params,
        Combatant(
            participant_id="main",
            team="main",
            champion_data={},
            level=0,
            items=(),
            stats={},
            defenses=None,
            request=context.main_request,
        ),
    )
    context.actor_params["main"] = main_params
    # Every pair fight carries its legacy roster-target allocation: the
    # ordered defender lists are [*enemies] for main/ally attackers and
    # [main, *allies] for enemy attackers, exactly like the receipt
    # composition's attack groups.  Secondary-target item branches
    # (cleaves, actives) price against these fields, and both paths share
    # one pair cache, so the params must be identical (issue #169).
    for defender_index, defender in enumerate(enemy_actors):
        pair_params = replace(
            main_params,
            enforce_resource_limits=True,
            roster_target_index=defender_index,
            roster_target_count=len(enemy_actors),
            **_target_overrides(defender),
        )
        pair_params.validate_for_champion(champion_name, level)
        context.main_pair_params.append((defender, pair_params))
    for attacker in context.roster_actors:
        if attacker.is_practice_dummy:
            continue
        attacker_params = context.actor_params[attacker.participant_id]
        attacker_params.validate_for_champion(
            str(attacker.champion_data.get("name", "")), attacker.level
        )
        if attacker.team == "ally":
            ordered_defenders = list(enumerate(enemy_actors))
            defender_count = len(enemy_actors)
        else:
            ordered_defenders = [
                (1 + position, defender)
                for position, defender in enumerate(ally_actors)
            ]
            defender_count = 1 + len(ally_actors)
        for defender_index, defender in ordered_defenders:
            context.roster_pair_params[
                (attacker.participant_id, defender.participant_id)
            ] = replace(
                attacker_params,
                enforce_resource_limits=True,
                roster_target_index=defender_index,
                roster_target_count=defender_count,
                **_target_overrides(defender),
            )

    # The signature-independent pair fights — allies into enemies, enemies
    # into allies — compile once for the whole search.  Enemy attackers'
    # support packets and their fights into the candidate main are
    # signature-dependent and live in each signature's sig compiler.
    base = _WalkCompiler(0)
    context.base_heal_dedup = {
        context.index_of[actor.participant_id]: {} for actor in context.roster_actors
    }
    support_attached: set[str] = set()
    enemy_attackers = [actor for actor in enemy_actors if not actor.is_practice_dummy]
    base_pairs = [
        (attacker, defender) for attacker in ally_actors for defender in enemy_actors
    ] + [
        (attacker, defender) for attacker in enemy_attackers for defender in ally_actors
    ]
    # Roster position mirrors the legacy attack groups: enemies are indexed
    # from 0 for allied attackers, while an enemy attacker's ordered
    # defenders are [main, *allies], so the first ally sits at index 1.
    enemy_index = {
        defender.participant_id: index for index, defender in enumerate(enemy_actors)
    }
    ally_index = {
        defender.participant_id: index for index, defender in enumerate(ally_actors)
    }
    for attacker, defender in base_pairs:
        pair_param_key = (attacker.participant_id, defender.participant_id)
        cache_key = _timeline_module()._pair_cache_key(attacker, defender)
        defender_index = (
            enemy_index.get(defender.participant_id, 0)
            if attacker.team == "ally"
            else 1 + ally_index.get(defender.participant_id, -1)
        )
        packet = pair_result_cache.get(cache_key)
        if packet is None:
            packet = _timeline_module()._pair_packet(
                run_fight(
                    attacker.champion_data,
                    attacker.level,
                    list(attacker.items),
                    context.roster_pair_params[pair_param_key],
                    validated=True,
                ),
                attacker.participant_id,
                defender.participant_id,
                defender_index,
                champion_data=attacker.champion_data,
            )
            pair_result_cache[cache_key] = packet
        attacker_i = context.index_of[attacker.participant_id]
        base.add_packet(
            packet,
            attacker_i,
            context.index_of[defender.participant_id],
            context.grievous_packs[attacker_i],
            params.fight_duration_seconds,
            context.base_heal_dedup[attacker_i],
            # An enemy attacker's ordered pair list is [main, *allies], so
            # the legacy dedup always keeps its main-pair copy — which
            # lives in the signature panel, not here.  Skip the ally-pair
            # copies; the engine may price them differently per defender
            # (issue #169, Dr. Mundo's Maximum Dosage).
            suppress_actor_wide_heals=attacker.team == "enemy",
        )
        if attacker.team == "ally" and attacker.participant_id not in support_attached:
            support_templates = packet.get("support")
            if support_templates is None:
                support_templates = _timeline_module()._support_effect_templates(
                    attacker,
                    packet["result"],
                    all_actors_by_index,
                    damage_events=packet.get("events", ()),
                )
                packet["support"] = support_templates
            base.add_support_templates(support_templates, attacker_i, context.index_of)
            support_attached.add(attacker.participant_id)
    for actor in context.roster_actors:
        wearer_i = context.index_of[actor.participant_id]
        profiles = context.thorns_profiles[wearer_i]
        if not profiles:
            continue
        strikes = [
            (aidx, time_value, sequence, all_actors_by_index[striker_i], striker_i)
            for aidx, time_value, sequence, striker_i in (
                base.auto_strikes_into.get(wearer_i, ())
            )
        ]
        if strikes:
            base.add_thorns(
                actor,
                wearer_i,
                strikes,
                profiles,
                context.grievous_packs[wearer_i],
                params.fight_duration_seconds,
                "base",
            )
    # A roster holder's active Warmog's Heart ticks are search-invariant:
    # author the same events the receipt walk schedules and convert them
    # through the same typed-action constructor, once per search (issue
    # #169).  The candidate's own Warmog still falls back per evaluation.
    for actor in context.roster_actors:
        actor_i = context.index_of[actor.participant_id]
        for event in _timeline_module()._warmog_heart_tick_events(
            actor, params.fight_duration_seconds
        ):
            base.actions.append(
                survival_action_from_event(
                    event,
                    1.0,
                    actor_i,
                    context.index_of,
                    subject_id=actor.participant_id,
                )
            )
    context.base_compiler = base
    context.base_sorted = sorted(base.actions, key=itemgetter(0))


def _build_signature_panel(
    context: CoupledSearchContext,
    main: Combatant,
    params: FightParams,
    pair_result_cache: dict[tuple[Any, ...], dict[str, Any]],
    signature: tuple[Any, ...],
    all_actors: list[Combatant],
) -> "_SignaturePanel":
    """Compile every roster pair fight for one main defensive signature.

    Pair packets come from (or land in) the shared ``pair_result_cache``
    with the same keys the legacy path uses, so both paths interoperate.
    Compilation order mirrors the legacy attack-group order with the main
    attacker's fresh pairs skipped: allies into enemies, then enemies into
    the main and allies.
    """
    duration = params.fight_duration_seconds
    base = context.base_compiler
    assert base is not None, "context setup must precede panel builds"
    sig = _WalkCompiler(base.next_aidx)
    roster = context.roster_actors or []
    enemy_actors = [
        actor
        for actor in roster
        if actor.team == "enemy" and not actor.is_practice_dummy
    ]
    ally_count = sum(1 for actor in roster if actor.team == "ally")
    for attacker in enemy_actors:
        cache_key = _timeline_module()._pair_cache_key(attacker, main)
        packet = pair_result_cache.get(cache_key)
        if packet is None:
            packet = _timeline_module()._pair_packet(
                run_fight(
                    attacker.champion_data,
                    attacker.level,
                    list(attacker.items),
                    replace(
                        context.actor_params[attacker.participant_id],
                        enforce_resource_limits=True,
                        # The legacy attack group's ordered defenders for an
                        # enemy attacker are [main, *allies] (issue #169).
                        roster_target_index=0,
                        roster_target_count=1 + ally_count,
                        **_target_overrides(main),
                    ),
                    validated=True,
                ),
                attacker.participant_id,
                "main",
                champion_data=attacker.champion_data,
            )
            pair_result_cache[cache_key] = packet
        attacker_i = context.index_of[attacker.participant_id]
        # This main-pair packet carries the attacker's legacy-kept
        # actor-wide heal copies (the ally-pair copies were suppressed in
        # the base panel).  The dedup map is a per-signature copy: a sig
        # build may never grow the shared base sets, or a key recorded by
        # one signature would silently drop another signature's only copy.
        sig.add_packet(
            packet,
            attacker_i,
            0,
            context.grievous_packs[attacker_i],
            duration,
            dict(context.base_heal_dedup.get(attacker_i) or {}),
        )
        support_templates = packet.get("support")
        if support_templates is None:
            support_templates = _timeline_module()._support_effect_templates(
                attacker,
                packet["result"],
                all_actors,
                damage_events=packet.get("events", ()),
            )
            packet["support"] = support_templates
        sig.add_support_templates(support_templates, attacker_i, context.index_of)
    return _SignaturePanel(context.base_sorted, sig)


def _score_with_search_context(
    champion_data: dict[str, Any],
    level: int,
    items: list[dict[str, Any]],
    params: FightParams,
    *,
    main_stats: dict[str, float],
    main_defenses: Any,
    enemies: list[ResolvedLoadout],
    allies: list[ResolvedLoadout],
    pair_result_cache: dict[tuple[Any, ...], dict[str, Any]],
    context: CoupledSearchContext,
    reuse_main_stats: bool,
) -> dict[str, Any]:
    """Score one candidate through the compiled panel walk.

    Returns the exact score-only receipt ``build_participant_timeline``
    would produce — same fields, same rounding, same float-addition order,
    and the same rounded death-time cutoff on each attacker's outgoing
    total — while compiling only the main champion's fresh outgoing
    fights.
    """
    # Issue #137: a search-invariant compilation failure (roster pair or
    # signature panel) poisons the context; every later evaluation raises
    # immediately instead of re-attempting the compiled path.
    if getattr(context, "uncompilable", False):
        raise UncompilableActionError(
            receipt="context_marked_uncompilable",
            source=str(champion_data.get("name", "")),
        )
    # The main candidate's own loadout is candidate-dependent: a failure
    # here falls back per evaluation and never poisons the context.  Checked
    # before any pair fight so the fallback costs only the capability scan.
    main_item_receipt = _timeline_module()._uncompilable_item_receipt(items)
    if main_item_receipt is not None:
        raise UncompilableActionError(
            receipt=f"main:{main_item_receipt}",
            source=str(champion_data.get("name", "")),
        )
    if context.roster_actors is None:
        setup_allies = [
            _from_loadout(f"ally:{loadout.champion_data['name']}", "ally", loadout)
            for loadout in allies
        ]
        setup_enemies = [
            _from_loadout(f"enemy:{loadout.champion_data['name']}", "enemy", loadout)
            for loadout in enemies
        ]
        placeholder = Combatant(
            participant_id="main",
            team="main",
            champion_data=champion_data,
            level=level,
            items=tuple(items),
            stats=main_stats,
            defenses=main_defenses,
            request=None,
        )
        try:
            _context_setup(
                context,
                params,
                enemies,
                allies,
                str(champion_data.get("name", "")),
                level,
                pair_result_cache,
                [placeholder, *setup_allies, *setup_enemies],
            )
        except UncompilableActionError as exc:
            # Roster pair compilation is search-invariant: one failure means
            # the compiled path can never be used for this search.
            raise UncompilableActionError(
                receipt=exc.receipt, source=exc.source, invariant=True
            ) from exc
    duration = params.fight_duration_seconds
    main = Combatant(
        participant_id="main",
        team="main",
        champion_data=champion_data,
        level=level,
        items=tuple(items),
        stats=main_stats,
        defenses=main_defenses,
        request=context.main_request,
    )
    roster = context.roster_actors or []
    all_actors = [main, *roster]
    signature = _defensive_signature(main)
    panel = context.panels.get(signature)
    if panel is None:
        try:
            panel = _build_signature_panel(
                context, main, params, pair_result_cache, signature, all_actors
            )
        except UncompilableActionError as exc:
            # Signature-panel compilation is invariant per defensive
            # signature; mark the whole context so later evaluations skip
            # the compiled path instead of re-raising per candidate.
            raise UncompilableActionError(
                receipt=exc.receipt, source=exc.source, invariant=True
            ) from exc
        context.panels[signature] = panel

    fresh = _WalkCompiler(panel.n_actions)
    main_profiles = healing_reduction_profiles(main.items)
    main_packs = {
        damage_type: _grievous_pack(main_profiles, damage_type)
        for damage_type in ("physical", "magic", "true")
    }
    main_champion_wounds = context.main_champion_wounds
    if main_champion_wounds is None:
        main_champion_wounds = {
            str(packet.get("source_key", "")): packet
            for packet in champion_grievous_wound_sources(main.champion_data)
        }
        context.main_champion_wounds = main_champion_wounds
    reusable_stats = main.stats if reuse_main_stats else None
    heal_dedup: dict[tuple[str, float], float] = {}
    first_result = None
    enemy_actors = [actor for actor in roster if actor.team == "enemy"]
    for defender_index, (defender, pair_params) in enumerate(context.main_pair_params):
        result = run_fight(
            main.champion_data,
            main.level,
            list(main.items),
            pair_params,
            precomputed_stats=reusable_stats,
            validated=True,
            score_only=True,
        )
        if first_result is None:
            first_result = result
        fresh.add_engine_result(
            result,
            "main",
            0,
            defender.participant_id,
            context.index_of[defender.participant_id],
            main_packs,
            duration,
            heal_dedup,
            context.pair_id_strings[defender.participant_id],
            defender_index,
            champion_wounds=main_champion_wounds,
        )
    if first_result is not None:
        # The item support scan reads per-event target/id fields that only
        # pair enrichment adds (Black Cleaver Carve, Bloodsong), plus the
        # first pair's takedown synthesis.  Give it the same view the
        # receipt composition passes — a template it authors either
        # compiles or fails closed, never silently vanishes (issue #169).
        # A tuple-ledger fight needs none of this: the pipeline's tuple
        # predicate excludes every event-scanning holder.
        if first_result.get("damage_events_tuple") or not has_event_view_support_items(
            main.items
        ):
            # Tuple-ledger fights carry no scannable rows by construction,
            # and a holder with no event-view item never reads the enriched
            # per-event copy — both scan the plain engine result.
            support_templates = _timeline_module()._support_effect_templates(
                main, first_result, all_actors
            )
        else:
            first_defender_id = context.main_pair_params[0][0].participant_id
            support_scan_events = [
                {
                    **event,
                    "target": first_defender_id,
                    "_event_id": f"main:{first_defender_id}:{index}",
                }
                for index, event in enumerate(first_result.get("damage_events", []))
            ]
            support_templates = _timeline_module()._support_effect_templates(
                main,
                first_result,
                all_actors,
                damage_events=support_scan_events,
                target_id=first_defender_id,
            )
        fresh.add_support_templates(support_templates, 0, context.index_of)
    # Thorns from this candidate's fresh strikes (enemy wearers), then the
    # candidate's own thorns items struck by the invariant roster autos.
    for defender in enemy_actors:
        wearer_i = context.index_of[defender.participant_id]
        profiles = context.thorns_profiles[wearer_i]
        if not profiles:
            continue
        strikes = [
            (aidx, time_value, sequence, main, 0)
            for aidx, time_value, sequence, _striker_i in (
                fresh.auto_strikes_into.get(wearer_i, ())
            )
        ]
        if strikes:
            fresh.add_thorns(
                defender,
                wearer_i,
                strikes,
                profiles,
                context.grievous_packs[wearer_i],
                duration,
                "fresh",
            )
    main_thorns = thorns_effects(list(main.items))
    if main_thorns:
        strikes = [
            (aidx, time_value, sequence, all_actors[striker_i], striker_i)
            for aidx, time_value, sequence, striker_i in (
                panel.sig.auto_strikes_into.get(0, ())
            )
        ]
        if strikes:
            fresh.add_thorns(
                main, 0, strikes, main_thorns, main_packs, duration, "fresh"
            )

    # Grey-health consume heals (E8a) are compiled from the same incoming
    # (enemy -> main, plus enemy thorns) and outgoing (main) damage actions
    # the walk applies, with the candidate's own stats/ranks, so the
    # compiled score walk matches the ordered receipt's fixed amounts.
    grey_summary: dict[str, float] = {}
    if (
        str(champion_data.get("name", "")) in GREY_HEALTH_RULE_CHAMPIONS
        and enemy_actors
    ):
        sig_actions = panel.sig.actions
        # Auto-attack packets expose no ``raw_damage`` (the engine emits it
        # only for authored ability hits), so the compiled rows carry a zero
        # there; mirror the ordered ledger's ``raw_damage or damage``
        # fallback so both paths price Mordekaiser's pre-mitigation term
        # identically.
        in_records = [
            (
                float(action.time),
                float(action.amount),
                (
                    float(action.raw_damage)
                    if float(action.raw_damage) > 0.0
                    else float(action.amount)
                ),
            )
            for action in sig_actions
            if action.kind in (ActionKind.PLAIN_DAMAGE, ActionKind.DAMAGE)
            and action.subject == 0
            and float(action.time) <= duration
        ]
        in_records.extend(
            (
                float(action.time),
                float(action.amount),
                (
                    float(action.raw_damage)
                    if float(action.raw_damage) > 0.0
                    else float(action.amount)
                ),
            )
            for action in fresh.actions
            if action.kind in (ActionKind.PLAIN_DAMAGE, ActionKind.DAMAGE)
            and action.subject == 0
            and float(action.time) <= duration
        )
        out_records = [
            (
                float(action.time),
                float(action.amount),
                (
                    float(action.raw_damage)
                    if float(action.raw_damage) > 0.0
                    else float(action.amount)
                ),
            )
            for action in fresh.actions
            if action.kind in (ActionKind.PLAIN_DAMAGE, ActionKind.DAMAGE)
            and action.attacker == 0
            and float(action.time) <= duration
        ]
        main_cast_timeline = (
            list(first_result.get("cast_timeline", []))
            if first_result is not None
            else []
        )
        grey_heals, grey_summary = _timeline_module()._grey_health_receipts(
            str(champion_data.get("name", "")),
            champion_data,
            level,
            main.stats,
            in_records,
            out_records,
            main_cast_timeline,
            duration,
            len(enemy_actors),
            params.ability_ranks,
        )
        for index, (heal_time, source, amount) in enumerate(grey_heals):
            aidx = fresh.next_aidx
            fresh.next_aidx += 1
            event_id = f"main:grey:{source}:{index}"
            sort_key = _action_key(
                float(heal_time),
                1.0,
                "main",
                {"attacker": "main", "_event_id": event_id, "source": source},
            )
            fresh.actions.append(
                SurvivalAction(
                    sort_key=sort_key,
                    time=float(heal_time),
                    phase=1.0,
                    kind=ActionKind.HEAL,
                    subject=0,
                    attacker=0,
                    aidx=aidx,
                    amount=float(amount),
                    source_key=str(source),
                    source=str(source),
                    event_id=event_id,
                )
            )

    actions = panel.sorted_actions + sorted(fresh.actions, key=itemgetter(0))
    actions = coalesce_darius_q_heals(actions)
    # Sourced revives (champion passives) author one candidate per incoming
    # damaging packet, mirroring the receipt walk's pre-walk expansion; the
    # kernel applies the earliest one only when the participant is dead.
    revive_actions, n_actions = revive_candidate_actions(
        actions, all_actors, fresh.next_aidx
    )
    if revive_actions:
        actions = actions + revive_actions
    actions.sort(key=itemgetter(0))
    # Issue #137: the score adapter arms the same canonical state dicts as
    # the receipt walk and drives the identical kernel; the only difference
    # is the ledger's parallel-array observation below.
    states = build_states(all_actors)
    ledger = ScoreLedger(n_actions)
    venom_packs = [
        serpents_fang_venom(
            list(actor.items), is_melee=bool(actor.stats.get("is_melee", True))
        )
        for actor in all_actors
    ]
    ctx = TransitionContext(
        duration=duration,
        states=states,
        combatants=all_actors,
        index_of=context.index_of,
        ledger=ledger,
        venom_profiles=venom_packs,
    )
    run_survival_walk(actions, ctx)
    finalize_states(states, duration)
    rows_by_id = assemble_survival_rows(states, all_actors)
    survival_rows = [rows_by_id[actor.participant_id] for actor in all_actors]
    applied = ledger.applied
    if grey_summary.get("source"):
        survival_rows[0]["grey_health_stored"] = round(
            float(grey_summary.get("grey_health_stored", 0.0)), 6
        )
        survival_rows[0]["grey_health_consumed"] = round(
            float(grey_summary.get("grey_health_consumed", 0.0)), 6
        )
        survival_rows[0]["grey_health_source"] = str(grey_summary["source"])

    count = len(all_actors)
    base = context.base_compiler
    support_value, healing_output = accumulate_support_values(
        applied,
        fresh.support_entries,
        base.support_entries,
        panel.sig.support_entries,
        count,
    )

    public_breakdown = []
    sig_damage_order = panel.sig.damage_order
    base_damage_order = base.damage_order
    fresh_damage_order = fresh.damage_order
    fresh_thorns_order = fresh.thorns_order
    base_thorns_order = base.thorns_order
    totals = accumulate_damage_totals(
        survival_rows,
        applied,
        sig_damage_order=sig_damage_order,
        base_damage_order=base_damage_order,
        fresh_damage_order=fresh_damage_order,
        fresh_thorns_order=fresh_thorns_order,
        base_thorns_order=base_thorns_order,
        count=count,
    )
    for index, actor in enumerate(all_actors):
        # Per-attacker float-sum order replays the legacy outgoing list:
        # pair fights in defender order (enemies hit the main first, then
        # allies), then thorns in strike order (fresh strikes precede the
        # roster's).  One running total over the ordered parts keeps the
        # exact same addition sequence without building a concat list.
        # A dead attacker's total also replays the legacy cutoff against
        # its ROUNDED death time: the walk applies an attacker's own
        # event at the exact death instant, but the legacy sum excludes
        # it whenever the true death time rounds down past it.
        total = totals[index]
        actor_survival = survival_rows[index]
        public_breakdown.append(
            {
                "participant_id": actor.participant_id,
                "team": actor.team,
                "champion": actor.champion_data.get("name", ""),
                "total_damage": round(float(total), 1),
                "sources": [],
                "outgoing_damage_before_death": round(float(total), 1),
                "incoming_damage": round(
                    float(actor_survival.get("health_damage", 0.0))
                    + float(actor_survival.get("shield_absorbed", 0.0)),
                    1,
                ),
                "health_damage": actor_survival.get("health_damage", 0.0),
                "shield_absorbed": actor_survival.get("shield_absorbed", 0.0),
                "effective_health": actor_survival.get("effective_health", 0.0),
                "healing_received": actor_survival.get("healing_received", 0.0),
                "healing_reduced": actor_survival.get("healing_reduced", 0.0),
                "support_shield_received": actor_survival.get(
                    "support_shield_received", 0.0
                ),
                "support_value": round(support_value[index], 1),
                "healing_output": round(healing_output[index], 1),
                "survived_window": bool(actor_survival.get("survived_window")),
                "death_time": actor_survival.get("death_time"),
            }
        )
    coverage_reports = fresh.coverage + base.coverage + panel.sig.coverage
    focus_index = next(
        (
            index
            for index, actor in enumerate(all_actors)
            if actor.participant_id == "main"
        ),
        0,
    )
    focus_survival = survival_rows[focus_index]
    return {
        "duration": float(duration),
        "participants": [
            {
                "participant_id": actor.participant_id,
                "team": actor.team,
                "champion": actor.champion_data.get("name", ""),
                "level": actor.level,
                "survival": survival_rows[index],
            }
            for index, actor in enumerate(all_actors)
        ],
        "breakdown": public_breakdown,
        "objective": {
            "main_team_damage_before_death": round(
                sum(
                    row["total_damage"]
                    for row in public_breakdown
                    if row["team"] in {"main", "ally"}
                ),
                1,
            ),
            "enemy_team_damage_before_death": round(
                sum(
                    row["total_damage"]
                    for row in public_breakdown
                    if row["team"] == "enemy"
                ),
                1,
            ),
            "focus_participant_id": "main",
            "focus_damage_before_death": round(
                float(public_breakdown[focus_index]["total_damage"]), 1
            ),
            "focus_survival": focus_survival,
            "focus_support_value": round(support_value[focus_index], 1),
            "focus_healing": round(
                float(focus_survival.get("healing_received", 0.0)), 1
            ),
        },
        "timeline_coverage": combine_timeline_coverages(
            coverage_reports,
            target_count=len(coverage_reports),
        ),
    }
