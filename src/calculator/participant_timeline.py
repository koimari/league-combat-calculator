"""Event-ordered combat for a selected main champion and roster.

The existing fight engine remains the authority for champion and item math.
This layer only composes its post-mitigation event ledgers, applies starting
shields and sourced self-heals in timestamp order, and reports who was alive
when damage landed.  It intentionally does not invent targeting, cooldown,
or crowd-control behavior that the packets do not provide.

What stays here is the composition itself: the request record, the pass
driver, the pair-fight loop with the support templates it attaches, the
event schedulers, the survival walk and the compiled score lane.
``timeline/`` holds the records those steps write through, the grey-health
pool, the utility receipt and the published combat receipt.
"""

# pylint: disable=duplicate-code

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass, replace
from operator import itemgetter
from typing import Any, NamedTuple

from . import rune_effects
from .ability_spec import AttackClass, DamageClass
from .ally_packet_recipient import RETARGETABLE_SCOPES, repriced_for_recipient
from .attack_windows import AttackSpeedWindow
from .capabilities import SUPPORT_TARGET_RESOLUTION_SCOPES
from .cast_event_row import (
    cast_ordinal as _row_cast_ordinal,
)
from .cast_event_row import (
    cast_slot as _row_cast_slot,
)
from .cast_event_row import (
    cast_time as _row_cast_time,
)
from .champion_loadout import ResolvedLoadout
from .champions.lulu_events import derive_lulu_support_events
from .combat_events import certified_recipients
from .defensive_effects import armed_revive
from .fight_params import FightParams
from .healing import GREY_HEALTH_RULE_CHAMPIONS
from .healing_reduction import (
    champion_grievous_wound_sources,
    healing_reduction_profiles,
)
from .interpreters import uncompilable_item_receipt
from .interpreters.damage_routing import (
    walk_deferral,
    walk_execution,
    walk_venom,
)
from .interpreters.part_amp import StaticHolderAmps, resolve_static_holder_amps
from .interpreters.reactive import thorns_effects
from .interpreters.stat_derivation import (
    declared_stat_derivations,
)
from .interpreters.sustain import SustainSlot
from .interpreters.sustain import walk_slot as _sustain_walk_slot
from .item_behavior import (
    BelowHalfHealingRule,
    FightFacts,
    PacketKind,
    RegenerationRule,
    ThresholdRegenRule,
    is_denial_receipt,
)
from .item_effects import (
    ThornsEffect,
    actualizer_active_seconds,
)
from .item_support_effects import derive_item_support_effects, schedule_knights_vow
from .pipeline import run_fight
from .program import route as program_route

# The one ``SurvivalAction`` constructor.  Composition is above
# both layers, so this module is where the logical builder and the kernel it
# builds for meet; nothing under ``survival/`` reaches this way.
#
# This is the composition root's one eager edge into ``program/``, and it is
# transitive: importing ``program.compile`` imports ``events``, ``build``,
# ``route``, ``identity``, ``caches`` and ``precision`` on every process
# start.  Deliberate and checked -- none of the six does import-time I/O or
# registry validation, so the edge costs module objects and nothing else --
# but it is the reason S4's vocabulary commit could say "nothing in src/
# imports them yet" and the next commit could not.
from .program.amp import (
    AmpRiders,
    ArmingLedger,
    LiveAmpRider,
    live_amp_riders,
)
from .program.build import ParamPatch, roster_program
from .program.capability import arming_stacking, dropped_pair_previews
from .program.compile import (
    PairFight,
    PairView,
    WalkCompiler,
    WalkSlots,
    ability_instance_for_event,
    action_from_event,
    grey_health_heal_action,
    grey_health_shield_action,
    is_authored_ability_event,
    knights_vow_target_factor,
    modifier_delivery_receipt,
    pair_view,
    revive_candidate_actions,
    routed_declaration,
    stage_knights_vow_heals,
    stage_knights_vow_redirect_actions,
)
from .program.dependency import (
    CrossPassDependency,
    PassRequest,
    incomplete_dependency,
    run_passes,
)
from .program.identity import MechanicId, PIdx
from .program.rung import (
    CompiledFast,
    CompiledFull,
    FallbackScope,
    ReceiptWalk,
    SearchPoisoned,
    counter_entry,
    gate_rung,
)
from .program.views import breakdown as _breakdown_view
from .program.views import score as _score_view
from .program.views import survival as _survival_view
from .program.views.leaf import DISCARD, LeafWriter
from .program.walk import AttackerOutcome, WalkResult, walk
from .resistance import apply_resistance
from .roster_composition import (
    ActorRequest,
    Combatant,
    actor_params_with_resource_restores,
    defensive_signature,
    from_loadout,
    main_combatant,
    mana_spent_heal_slot,
    target_overrides,
    target_params,
)
from .roster_composition import (
    actor_params as _actor_params,
)
from .roster_composition import (
    coalesce_darius_q_heals as _coalesce_darius_q_heals,
)
from .roster_composition import (
    resource_restores as _declared_resource_restores,
)
from .starting_defenses import StartingDefenses
from .state_lifecycle import TriggerGate
from .support_effects import derive_ally_effects
from .support_event_view import resolve_knights_vow_tether
from .survival import (
    EVENT_SLOTS,
    SUPPORT_RANK_KEY,
    ActionKind,
    PlatingWindow,
    ReceiptLedger,
    RegenerationWindow,
    ScoreLedger,
    SurvivalAction,
    TransitionContext,
    TransitionRank,
    UncompilableActionError,
    accumulate_damage_totals,
    accumulate_support_values,
    action_key,
    build_states,
    coalesce_darius_q_heals,
    support_transition_rank,
    thorns_return_damage,
)
from .survival import (
    resolve_grievous as _grievous_pack,
)
from .timeline.grey_health import _apply_grey_health, _grey_health_receipts
from .timeline.receipt import _compose_receipt
from .timeline.records import (
    GreySubject,
    Ledgers,
    PairCacheKey,
    Roster,
    TimelineScene,
    Walked,
)
from .timeline.utility import _utility_outcome_receipt
from .timeline_coverage import combine_timeline_coverages
from .trigger_stream import (
    TriggerKind,
    enriched_view_items,
    event_triggers,
    holders_in,
    is_immobilizing_event,
)
from .work_counters import WorkCounterSink, record_rung

# The survival kernel's compiler, aliased here because importers reach it
# through this module.
_WalkCompiler = WalkCompiler

# The receipt an already-poisoned search context raises with.  A later
# evaluation's failure is the *first* one's cause, so the rung ladder reads
# it back rather than reporting every subsequent candidate as its own
# candidate-local fallback.
_CONTEXT_POISONED_RECEIPT = "context_marked_uncompilable"
# The reason a request whose *shape* excludes the compiled panel walk
# records.  A named constant rather than a literal at the call site because
# ``ReceiptWalk`` requires a reason and a reason spelled where it is used is
# a reason that can be spelled twice.
_GATE_REFUSAL_RECEIPT = (
    "the request shape excludes the compiled panel walk: no roster, receipt "
    "mode, Enemy Hits disabled, or a cross-pass patch"
)


def _pair_run_fight(
    work_counters: WorkCounterSink | None,
    champion_data: Mapping[str, Any],
    level: int,
    items: list[dict[str, Any]],
    *,
    params: FightParams,
    **kwargs: Any,
) -> dict[str, Any]:
    """Run one composed pair fight, counted on the search's work counters.

    One wrapper keeps the pair-fight count a property of this module, and
    is the one place that tells the engine its result will be composed.
    """
    if work_counters is not None:
        work_counters.pair_run_fight_calls += 1
    return run_fight(
        champion_data, level, items, replace(params, roster_composed=True), **kwargs
    )


# The compiled score lane prices no external resource ledger, so its cached
# packets sit under the empty one.  That is a property and not a hope: the
# request gate below refuses the compiled path for any pass carrying a
# cross-pass ParamPatch, so a patched pass never reaches these two sites.
_UNPATCHED_RESTORES: tuple[tuple[float, float], ...] = ()

# The one field a cross-pass patch of this composition overrides — the
# per-participant restore ledger pass 1 derives and pass 2 prices with.  One
# spelling, because the declaration names it, the patch keys on it and the
# pass reads it back, and three literals could disagree.
_RESOURCE_RESTORES = "resource_restores"


def _cross_pass_dependency(slot: SustainSlot) -> CrossPassDependency:
    """The two-pass declaration one mana-spent heal carries.

    Built from the slot rather than named by item: which item is the
    mana-spent heal is a question ``item_behavior`` already answers.
    """
    return CrossPassDependency(
        mechanic=MechanicId(slot.rule.mechanic_id),
        max_passes=2,
        reads=_RESOURCE_RESTORES,
    )


def _cross_pass_dependencies(
    items: Sequence[Mapping[str, Any]],
    enemies: Sequence[ResolvedLoadout],
    allies: Sequence[ResolvedLoadout],
) -> tuple[CrossPassDependency, ...]:
    """Every cross-pass dependency this roster's builds declare.

    The pass budget is sized from these declarations and never from what a
    pass asks for, so this list decides whether a second pass exists.
    """
    builds = [items, *(loadout.item_data for loadout in (*enemies, *allies))]
    slots = [
        slot for build in builds if (slot := mana_spent_heal_slot(build)) is not None
    ]
    return tuple(dict.fromkeys(_cross_pass_dependency(slot) for slot in slots))


def _compiled_lane_is_open(request: Composition, patch: ParamPatch | None) -> bool:
    """Whether this pass may be priced by the compiled panel walk.

    Seven clauses for five reasons: a cross-pass patch needs a resource
    ledger the compiled kernel does not stage; the search context holds the
    presorted invariant actions the lane replays; a displayed timeline needs
    the receipt walk; the panels are built over a pair cache and a non-empty
    enemy roster; Enemy Hits is enforced by the receipt walk's gates.  What
    the compiler cannot represent falls back to the walk.
    """
    return bool(
        patch is None
        and request.search_context is not None
        and request.search_context.compiled_walk_enabled
        and not request.include_receipt
        and request.pair_result_cache is not None
        and request.enemies
        and request.params.enemies_attack
    )


def _pair_cache_key(
    attacker_id: str,
    defender_id: str,
    defensive: tuple[float | str, ...],
    restores: tuple[tuple[float, float], ...],
) -> PairCacheKey:
    """Every input that priced one cached pair packet, restores included."""
    return (attacker_id, defender_id, defensive, restores)


def _stamp_ability_instances(result: MutableMapping[str, Any]) -> None:
    """Give one engine result's damage events their delivery facts in place.

    The *view* half of what :meth:`WalkCompiler._compile_pair` derives
    for the walk: the item support scan reads the enriched per-event copy,
    and a score-only result never passes through the pair enrichment that
    would otherwise supply it.  Same two derivers, one home.
    """
    cast_timeline = result.get("cast_timeline") or ()
    for event in result.get("damage_events", ()):
        if not isinstance(event, MutableMapping):
            continue
        if "ability_instance" not in event:
            instance = ability_instance_for_event(event, cast_timeline)
            if instance is not None:
                event["ability_instance"] = instance
        event.setdefault("is_ability", is_authored_ability_event(event))
        if str(event.get("source_key", "")) == "auto_attacks":
            event["basic_attack"] = True


def _holder_amps_of(
    attacker: Combatant, defender: Combatant, params: FightParams
) -> StaticHolderAmps:
    """*attacker*'s own static, pair-local amplifiers, resolved for this pair.

    The composition-site twin of :func:`_live_amps_of`, and it takes the same
    three inputs for the same reason: the attacker's owners and level, and
    the defender's bonus health, which a declared magnitude may be stated per
    hundred of.

    ``ability_amp_armed`` is read off the attacker's own resolved combat
    state rather than assumed, because the ability amp rides an item active
    and a build that never triggered it amplifies nothing — an amp armed by
    a default would be a number invented rather than delivered.
    """
    return resolve_static_holder_amps(
        list(attacker.items),
        holder_stats=attacker.stats,
        ability_amp_armed=(
            params.include_actives
            and actualizer_active_seconds(
                attacker.items,
                params.item_options,
                fight_duration_seconds=params.fight_duration_seconds,
            )
            > 0.0
        ),
        facts=FightFacts(
            level=attacker.level,
            fight_duration_seconds=params.fight_duration_seconds,
            target_bonus_health=max(
                0.0, float(defender.stats.get("bonus_health", 0.0))
            ),
            holder_is_melee=bool(attacker.stats.get("is_melee")),
        ),
    )


def _live_amps_of(
    attacker: Combatant, defender: Combatant, params: FightParams
) -> tuple[LiveAmpRider, ...]:
    """The live-predicate amplifiers *attacker*'s build declares, resolved.

    One reader of :func:`~.program.amp.live_amp_riders`, so every site
    resolves them from the same inputs: the attacker's owners and level, and
    the defender's bonus health.  The rider is a fact about one pair, which
    is why the defender is an argument.
    """
    return live_amp_riders(
        [str(item.get("name", "")) for item in attacker.items],
        facts=FightFacts(
            level=attacker.level,
            fight_duration_seconds=params.fight_duration_seconds,
            target_bonus_health=max(
                0.0, float(defender.stats.get("bonus_health", 0.0))
            ),
            holder_is_melee=bool(attacker.stats.get("is_melee")),
        ),
    )


def _regeneration_windows(
    combatants: Sequence[Combatant],
) -> tuple[RegenerationWindow | None, ...]:
    """Compile each participant's declared regeneration window for the walk.

    The walk schedules these recovery ticks and may not reach a declaration
    to price them — the dependency runs ``interpreters -> survival`` and
    never back — so the numbers are compiled here, where the context is
    built, and handed over as kernel data.  Index-aligned with *combatants*,
    ``None`` where a participant declares none.
    """
    windows: list[RegenerationWindow | None] = []
    for combatant in combatants:
        slot = _sustain_walk_slot(
            sorted({str(item.get("name", "")) for item in combatant.items}),
            RegenerationRule,
        )
        rune = _one_rune_walk_effect(combatant, rune_effects.RuneRegenerationEffect)
        if slot is None and rune is None:
            windows.append(None)
            continue
        windows.append(
            RegenerationWindow(
                owner="" if slot is None else slot.owner,
                total_melee=0.0 if slot is None else slot.value("total_melee"),
                total_reduced=0.0 if slot is None else slot.value("total_reduced"),
                duration=0.0 if slot is None else slot.value("duration"),
                missing_health_cap=(
                    0.0 if slot is None else slot.value("missing_health_cap")
                ),
                tick_interval=0.0 if slot is None else slot.value("tick_interval"),
                rune_owner="" if rune is None else rune.source,
                rune_missing_health_ratio=(
                    0.0 if rune is None else rune.missing_health_ratio
                ),
                rune_duration=0.0 if rune is None else rune.duration_seconds,
            )
        )
    return tuple(windows)


def _plating_windows(
    combatants: Sequence[Combatant],
) -> tuple[PlatingWindow | None, ...]:
    """Compile each participant's armed flat reduction for the walk.

    The sibling of :func:`_regeneration_windows` and compiled here for the
    same reason: the walk may not reach a rune declaration. The flat is
    resolved at the holder's own level, which does not change inside a
    walk.
    """
    windows: list[PlatingWindow | None] = []
    for combatant in combatants:
        plating = _one_rune_walk_effect(combatant, rune_effects.RunePlatingEffect)
        windows.append(
            None
            if plating is None
            else PlatingWindow(
                owner=plating.source,
                flat=rune_effects.at_level(plating.flat_by_level, combatant.level),
                hits=plating.hits,
                window=plating.window_seconds,
                cooldown=plating.cooldown_seconds,
            )
        )
    return tuple(windows)


def _one_rune_walk_effect(combatant: Combatant, kind: type) -> Any | None:
    """The one walk-lane effect of *kind* this participant's page declares.

    A roster card brings no page and every actor but the main champion
    answers ``None``. Two of one kind would be two windows on a lane that
    holds one, so a second is refused rather than silently dropped: no page
    in the game can select two, and a page that could would be a fact worth
    failing on.
    """
    page = combatant.request.rune_page
    if page is None:
        return None
    declared = [
        effect
        for effect in rune_effects.resolve_rune_page(page)
        if isinstance(effect, kind)
    ]
    if len(declared) > 1:
        raise ValueError(
            f"{combatant.participant_id} declares {len(declared)} "
            f"{kind.__name__} windows "
            f"({', '.join(effect.rune_name for effect in declared)}); the "
            "walk lane holds one per participant"
        )
    return declared[0] if declared else None


def _below_half_healing_bonuses(
    combatants: Sequence[Combatant],
) -> tuple[float, ...]:
    """Compile each participant's declared below-half healing bonus.

    The walk applies this bonus per recovery, once the fight has taken the
    holder under the boundary, and may not reach the declaration that states
    it — so it is compiled here beside the regeneration windows and handed to
    the state builder as kernel data.  Index-aligned with *combatants*, and
    ``0.0`` where a participant declares none: the walk multiplies by
    ``1 + bonus`` only while the bonus is positive, so nobody-declares-one and
    a sourced zero are the same answer and not a rule that failed to run.
    """
    return tuple(
        0.0 if slot is None else slot.value("bonus")
        for slot in (
            _sustain_walk_slot(
                sorted({str(item.get("name", "")) for item in combatant.items}),
                BelowHalfHealingRule,
            )
            for combatant in combatants
        )
    )


def _warmog_heart_tick_events(
    combatant: Combatant, duration: float
) -> list[dict[str, Any]]:
    """Author an active threshold-regeneration holder's tick events.

    A threshold regeneration is a live combat-state gate.  Each tick's amount
    is based on the current maximum health at the moment it lands, while the
    no-damage window is checked inside the survival walk against the last
    applied incoming packet.  The bonus-health threshold that arms it is a
    declared, sourced number and is intentionally not guessed for an
    unqualified loadout.  Both walks author through this one function: the
    receipt composition schedules the events per call, and the compiled base
    panel converts them into typed actions once per search.

    Read through the declaration rather than by item name, so the shape is
    what decides — a second item growing a threshold regeneration is
    authored here on the commit its declaration lands, not on the commit
    somebody remembers this branch.
    """
    slots = declared_stat_derivations(
        sorted({str(item.get("name", "")) for item in combatant.items}),
        ThresholdRegenRule,
    )
    if not slots:
        return []
    if len(slots) > 1:
        raise ValueError(
            f"{[slot.owner for slot in slots]} all declare a threshold "
            "regeneration and nothing declares how two of them tick together"
        )
    slot = slots[0]
    if float(combatant.stats.get("bonus_health", 0.0)) < slot.value(
        "bonus_health_threshold"
    ):
        return []
    ratio = slot.value("share_of_max_health")
    tick = slot.value("tick_interval")
    gate = slot.value("champion_damage_cooldown")
    if ratio <= 0.0 or tick <= 0.0:
        return []
    events: list[dict[str, Any]] = []
    time_value = tick
    sequence = 0
    while time_value <= duration + 1e-9:
        events.append(
            {
                "time": round(time_value, 6),
                "amount": 0.0,
                "amount_formula": (
                    lambda _current_health, maximum_health, ratio=ratio: (
                        maximum_health * ratio
                    )
                ),
                "source": f"{slot.owner} (Warmog's Heart)",
                "kind": "regen",
                "actor_wide": True,
                "requires_damage_free_seconds": gate,
                "_event_id": f"{combatant.participant_id}:warmog:{sequence}",
                "sequence": sequence,
            }
        )
        sequence += 1
        time_value += tick
    return events


def _routed_pair_defender_id(
    pair_defender_id: str | None, all_actors: Sequence[Combatant]
) -> str | None:
    """The pair fight a support scan's packets were priced in, resolved.

    The caller supplies the defender — it is the pair the engine result
    actually came from, which the caller has in hand — and this resolves it
    through :func:`program.route.resolve_route` under
    :class:`program.route.PairDefender`, so the subject is bounded against
    the roster and an id the roster does not hold raises
    ``program.route.unroutable_event`` instead of quietly addressing
    somebody else's state.

    It replaces a scan that re-derived the same fact independently, by
    walking the roster for the first enemy.  Two derivations of one fact
    that nothing forced to agree is exactly the shape this phase removes:
    the answer is unchanged, and it now has one source.

    ``None`` is the declared answer for an actor with no opponents — the
    composition's fallback pass, where no pair fight exists to name — and is
    the one case the policy has nothing to resolve.
    """
    if pair_defender_id is None:
        return None
    slots = {
        actor.participant_id: PIdx(index) for index, actor in enumerate(all_actors)
    }
    subject = slots.get(pair_defender_id)
    if subject is None:
        raise program_route.unroutable_event(
            program_route.PairDefender(),
            f"{pair_defender_id!r} is not a participant of this roster",
        )
    resolved = program_route.resolve_route(
        program_route.PairDefender(),
        program_route.RouteContext(
            author=subject, holder=subject, pair_defender=subject
        ),
        roster_size=len(all_actors),
    )
    return all_actors[int(resolved[0])].participant_id


def _support_target_ids(
    attacker: Combatant,
    effect: Mapping[str, Any],
    all_actors: Iterable[Combatant],
) -> tuple[list[str], str]:
    """Resolve a sourced support packet to selected allies.

    Target selection is intentionally explicit.  The packet supplies whether
    an effect is self-cast, area-wide, or one-teammate; for the latter the
    first selected teammate is the deterministic scenario target.  This keeps
    the model reproducible without pretending that an unspecified cursor
    choice was observed.
    """
    target_scope = effect.get("target_scope")
    # Fail closed BEFORE any team/roster branching.  An unrecognized,
    # missing or structurally invalid scope raises rather than redirecting
    # the packet, which is the published ``fail_closed: True`` contract.
    # Main, ally and enemy actors must fail identically, so this check runs
    # before the no-teammate block.
    if target_scope not in SUPPORT_TARGET_RESOLUTION_SCOPES:
        raise ValueError(
            "Unsupported support target_scope "
            f"{target_scope!r} for {attacker.participant_id} "
            f"({attacker.champion_data.get('name', '')}) from source "
            f"{effect.get('source', '')!r}; supported scopes: "
            f"{sorted(SUPPORT_TARGET_RESOLUTION_SCOPES)}"
        )
    if target_scope == "self":
        return [attacker.participant_id], "self"
    # ``main`` and ``ally`` are separate UI buckets but they are one allied
    # side in the fight.  Comparing the raw labels would make a main Lulu
    # unable to target an ally (and an ally unable to target the main).
    attacker_side = "main" if attacker.team in {"main", "ally"} else attacker.team
    allies = [
        actor
        for actor in all_actors
        if ("main" if actor.team in {"main", "ally"} else actor.team) == attacker_side
        and actor.participant_id != attacker.participant_id
    ]
    if not allies:
        if target_scope in {"self_and_all_teammates", "self_and_one_teammate"}:
            return [attacker.participant_id], "self_only_no_selected_teammate"
        if effect.get("target_self"):
            return [attacker.participant_id], "self"
        return [], "no_selected_teammate"
    if target_scope == "self_and_all_teammates":
        return [
            attacker.participant_id,
            *(actor.participant_id for actor in allies),
        ], "self_and_all_selected_teammates"
    if target_scope == "self_and_one_teammate":
        selected_index, selected_explicit = _support_selection(attacker, effect)
        if not selected_explicit:
            return [
                attacker.participant_id,
                allies[0].participant_id,
            ], "self_and_first_selected_teammate"
        if selected_index >= len(allies):
            raise ValueError(
                f"Support target index {selected_index} is outside the teammate "
                f"roster for {attacker.participant_id} from "
                f"{effect.get('source', '')!r}"
            )
        policy = (
            "self_and_selected_teammate"
            if selected_explicit
            else "self_and_first_selected_teammate"
        )
        return [
            attacker.participant_id,
            allies[selected_index].participant_id,
        ], policy
    if target_scope == "all_teammates":
        return [actor.participant_id for actor in allies], "all_selected_teammates"
    if target_scope == "one_teammate":
        # The one-teammate scope (Karma E, Orianna E, Yuumi E, Lulu E, the
        # self-or-target default) is an explicit branch, which is what lets
        # the terminal default be an unreachable exhaustiveness guard.
        selected_index, selected_explicit = _support_selection(attacker, effect)
        if not selected_explicit:
            return [allies[0].participant_id], "first_selected_teammate"
        if selected_index >= len(allies):
            raise ValueError(
                f"Support target index {selected_index} is outside the teammate "
                f"roster for {attacker.participant_id} from "
                f"{effect.get('source', '')!r}"
            )
        return [allies[selected_index].participant_id], "selected_teammate"
    raise AssertionError(
        f"unhandled support target_scope {target_scope!r} — the closed "
        "resolution vocabulary and this branch list have drifted"
    )


def _support_selection(
    attacker: Combatant, effect: Mapping[str, Any]
) -> tuple[int, bool]:
    """Return the selected ally index and whether it was authored."""
    selections = getattr(attacker.request, "support_target_selections", None)
    if not isinstance(selections, Mapping):
        return 0, False
    key = str(effect.get("target_selection_key", ""))
    value = selections.get(key)
    if value is None:
        value = selections.get(str(effect.get("source", "")))
    if isinstance(value, bool) or not isinstance(value, int):
        return 0, False
    return max(0, value), True


def _apply_item_support_selection(
    attacker: Combatant,
    template: Mapping[str, Any],
    all_actors: Iterable[Combatant],
) -> dict[str, Any]:
    """Apply an authored recipient choice to a one-target item packet.

    The choice moves the packet's amount with it: a row the emitter priced at
    its default ally's level (Mikael's Purify is "100 to 250 by target's
    level") is re-read at the chosen ally's, through the emitter's own ramp
    declaration rather than a second copy of the formula.
    """
    kind = str(template.get("kind", ""))
    scope = str(template.get("target_scope", ""))
    if kind not in {"shield", "heal"} or scope not in RETARGETABLE_SCOPES:
        return dict(template)
    selected_index, selected_explicit = _support_selection(attacker, template)
    if not selected_explicit:
        return dict(template)
    attacker_side = "main" if attacker.team in {"main", "ally"} else attacker.team
    allies = [
        actor
        for actor in all_actors
        if ("main" if actor.team in {"main", "ally"} else actor.team) == attacker_side
        and actor.participant_id != attacker.participant_id
    ]
    if selected_index >= len(allies):
        raise ValueError(
            f"Support target index {selected_index} is outside the teammate "
            f"roster for {attacker.participant_id} from "
            f"{template.get('source', '')!r}"
        )
    return repriced_for_recipient(
        {
            **template,
            "target": allies[selected_index].participant_id,
            "target_policy": "selected_teammate",
        },
        allies[selected_index],
    )


def _guardian_target(
    holder: Combatant, all_actors: Iterable[Combatant]
) -> tuple[Combatant, str] | None:
    """Resolve Guardian's one explicit protected teammate."""
    if holder.team == "ally" and not getattr(
        holder.request, "ally_effects_enabled", False
    ):
        return None
    holder_side = "main" if holder.team in {"main", "ally"} else holder.team
    allies = [
        actor
        for actor in all_actors
        if ("main" if actor.team in {"main", "ally"} else actor.team) == holder_side
        and actor.participant_id != holder.participant_id
    ]
    if not allies:
        return None
    selection = _guardian_selection_template()
    selected_index, selected_explicit = _support_selection(holder, selection)
    if selected_index >= len(allies):
        raise ValueError(
            f"Support target index {selected_index} is outside the teammate "
            f"roster for {holder.participant_id} from 'Guardian'"
        )
    policy = "selected_teammate" if selected_explicit else "first_selected_teammate"
    return allies[selected_index], policy


def _guardian_selection_template() -> dict[str, Any]:
    """Return the public selection contract for Guardian's Guard target."""
    return {
        "source": "Guardian · Guard target",
        "target_selection_key": "guardian:target",
    }


def _keystone_holder[KeystoneEffect](
    all_actors: Iterable[Combatant],
    keystone_name: str,
    name: str,
    effect_type: type[KeystoneEffect],
) -> tuple[Combatant, KeystoneEffect] | None:
    """The opening every keystone scheduler shares: the selected keystone, its
    compiled effect, and the one holder that carries a rune page.

    The request carries one selected keystone for the main loadout, so roster
    actors have no separate rune-page input and cannot hold a keystone here.
    """
    if keystone_name != name:
        return None
    effect = rune_effects.resolve_keystone(name)
    if not isinstance(effect, effect_type):
        return None
    return next(
        ((actor, effect) for actor in all_actors if actor.participant_id == "main"),
        None,
    )


def _reactive_candidate(
    *,
    holder: Combatant,
    recipient: str,
    keystone: str,
    label: str,
    kind: str,
    time: float,
    rank: TransitionRank,
    event_id: str,
    trigger_id: str,
    sequence: int,
    amount: float = 0.0,
    target_scope: str = "self",
    target_policy: str = "self",
    reactive: bool = True,
    sort_key: bool = True,
    **fields: Any,
) -> dict[str, Any]:
    """One keystone-authored support candidate on its shared frame.

    Who authored it, who receives it, which trigger it answers and where it
    sorts are the same fields in every scheduler below; only the mechanic's
    own payload is spelled at the call site.  ``sort_key`` stamps the walk's
    precomputed transition key, and ``reactive`` marks a row that dies with a
    skipped trigger — the zone rows a control leaves behind are neither.
    """
    candidate: dict[str, Any] = {
        "time": time,
        "kind": kind,
        "amount": amount,
        "source": f"{keystone} · {label}",
        "source_key": f"rune_{keystone}",
        "attacker": holder.participant_id,
        "target": recipient,
        "target_scope": target_scope,
        "target_policy": target_policy,
        "sequence": sequence,
        "event_precision": "exact",
        "_event_id": event_id,
        "_trigger_event_id": trigger_id,
        SUPPORT_RANK_KEY: rank,
        **fields,
    }
    if reactive:
        candidate["_reactive"] = True
    if sort_key:
        candidate["_sk"] = action_key(time, rank, recipient, candidate)
    return candidate


def _schedule_guardian_events(
    scene: TimelineScene,
    *,
    keystone_name: str,
) -> None:
    """Author Guardian candidates for each selected Guard relationship.

    The candidates live in the support ledger and sort before their matching
    incoming hit.  The survival kernel decides whether the current hit or
    the recent 2.5-second window reaches the sourced threshold.
    """
    resolved = _keystone_holder(
        scene.all_actors, keystone_name, "Guardian", rune_effects.KeystoneGuardianEffect
    )
    if resolved is None:
        return
    holder, effect = resolved
    combatant_by_id = {actor.participant_id: actor for actor in scene.all_actors}
    selected = _guardian_target(holder, scene.all_actors)
    if selected is None:
        return
    guarded, target_policy = selected
    protected = (holder, guarded)
    protected_ids = tuple(actor.participant_id for actor in protected)
    shield_amount = effect.shield_amount(holder.level, holder.stats)
    threshold = effect.threshold_at(holder.level)
    cooldown = effect.cooldown_at(holder.level)
    for trigger_target_id in protected_ids:
        events = scene.incoming.get(trigger_target_id, [])
        for event_index, trigger in enumerate(events):
            attacker = combatant_by_id.get(str(trigger.get("attacker", "")))
            if attacker is None or attacker.team == holder.team:
                continue
            trigger_amount = float(trigger.get("damage", 0.0) or 0.0)
            if trigger_amount <= 0.0:
                continue
            trigger_id = str(
                trigger.get(
                    "_event_id",
                    f"{attacker.participant_id}:{trigger_target_id}:guardian:{event_index}",
                )
            )
            owners = trigger.setdefault("_guardian_owner_ids", [])
            if holder.participant_id not in owners:
                owners.append(holder.participant_id)
            activation_id = f"{holder.participant_id}:{trigger_id}"
            for recipient in protected:
                is_holder = recipient.participant_id == holder.participant_id
                scene.support_effects[recipient.participant_id].append(
                    _reactive_candidate(
                        holder=holder,
                        recipient=recipient.participant_id,
                        keystone="Guardian",
                        label="Shield",
                        kind="shield",
                        time=float(trigger.get("time", 0.0) or 0.0),
                        rank=TransitionRank.AURA_ARM,
                        event_id=(
                            f"{holder.participant_id}:guardian:{trigger_id}:"
                            f"{recipient.participant_id}"
                        ),
                        trigger_id=trigger_id,
                        sequence=trigger.get("sequence", event_index),
                        amount=shield_amount,
                        target_scope="self" if is_holder else "explicit_selected_ally",
                        target_policy="self" if is_holder else target_policy,
                        duration=effect.shield_duration_seconds,
                        target_selection_key="guardian:target",
                        _guardian_reactive=True,
                        _guardian_owner_id=holder.participant_id,
                        _guardian_activation_id=activation_id,
                        _guardian_trigger_event_id=trigger_id,
                        _guardian_trigger_target=trigger_target_id,
                        _guardian_trigger_amount=trigger_amount,
                        _guardian_threshold=threshold,
                        _guardian_window_seconds=effect.trigger_window_seconds,
                        _guardian_cooldown_seconds=cooldown,
                    )
                )


#: The bus stream a control reader asks for.  Damage triggers ride the same
#: row and are nobody's business here.
_CONTROL_TRIGGER_ONLY = frozenset({TriggerKind.CC})


def _immobilizing_controls(
    events: Iterable[Mapping[str, Any]],
) -> list[tuple[Mapping[str, Any], str, float]]:
    """One holder's immobilizing control rows, in walk order, with their kind.

    Both rune schedulers below are sourced on the same word: Aftershock and
    Glacial Augment each say *immobilizing* an enemy champion, so both read
    the one immobilize predicate rather than comparing ``cc_kind`` against a
    set of their own -- the divergence ``trigger_stream`` exists to prevent,
    and the one that let a slow price Command.  The normalized token comes
    back off the bus's ``Trigger`` too, so nothing here parses the row.
    """
    rows: list[tuple[Mapping[str, Any], str, float]] = []
    for event in events:
        if not is_immobilizing_event(event):
            continue
        duration = max(0.0, float(event.get("cc_duration", 0.0) or 0.0))
        if duration <= 0.0:
            continue
        controls = event_triggers(event, kinds=_CONTROL_TRIGGER_ONLY)
        kind = controls[0].cc_kind if controls else ""
        if not kind:
            # An immobilize flag with no authored kind names no control
            # this row could republish.
            continue
        rows.append((event, kind, duration))
    rows.sort(key=lambda row: _sequence_reading_order(row[0]))
    return rows


def _sequence_reading_order(event: Mapping[str, Any]) -> tuple[float, int, str]:
    """One reading order for rows no rank applies to.

    Time, then sequence, then event id.  NOT a transition sort key:
    ``action_key`` is that, and the two answer different questions.
    """
    return (
        float(event.get("time", 0.0) or 0.0),
        int(event.get("sequence", 0) or 0),
        str(event.get("_event_id", "")),
    )


def _trigger_reading_order(
    event: Mapping[str, Any], holder_id: str
) -> tuple[float, int, str]:
    """The same reading order with the holder's own triggers read last.

    Aery chains off an ally's trigger before the holder's at one
    timestamp, and that is a reading order too: no rank takes part.
    """
    return (
        float(event.get("time", 0.0) or 0.0),
        0 if str(event.get("target", "")) != holder_id else 1,
        str(event.get("_event_id", "")),
    )


def _schedule_aftershock_events(
    scene: TimelineScene,
    *,
    keystone_name: str,
) -> None:
    """Author Aftershock's resistance snapshot after an accepted control."""
    resolved = _keystone_holder(
        scene.all_actors,
        keystone_name,
        "Aftershock",
        rune_effects.KeystoneAftershockEffect,
    )
    if resolved is None:
        return
    holder, effect = resolved
    armor_bonus = effect.resistance_bonus(holder.level, holder.stats, "armor")
    magic_resistance_bonus = effect.resistance_bonus(
        holder.level, holder.stats, "magic_resistance"
    )
    gate = TriggerGate(effect.cooldown_seconds, inclusive=True)
    for event, cc_kind, _duration in _immobilizing_controls(
        scene.outgoing.get(holder.participant_id, [])
    ):
        trigger_time = float(event.get("time", 0.0) or 0.0)
        key = (str(event.get("source_key", "")), round(trigger_time, 9), cc_kind)
        if not gate.accepts(trigger_time, key):
            continue
        trigger_id = str(event.get("_event_id", ""))
        scene.support_effects[holder.participant_id].append(
            _reactive_candidate(
                holder=holder,
                recipient=holder.participant_id,
                keystone="Aftershock",
                label="Resistance",
                kind="stat_buff",
                time=trigger_time + 1e-9,
                rank=TransitionRank.DAMAGE,
                event_id=f"{holder.participant_id}:aftershock:{trigger_id}",
                trigger_id=trigger_id,
                sequence=int(event.get("sequence", 0) or 0),
                duration=effect.duration_seconds,
                bonus_armor=armor_bonus,
                bonus_magic_resistance=magic_resistance_bonus,
                _aftershock=True,
                aftershock_trigger_kind=cc_kind,
                aftershock_duration=effect.duration_seconds,
                aftershock_cooldown=effect.cooldown_seconds,
            )
        )
        gate.arm(trigger_time)


def _schedule_grasp_events(
    scene: TimelineScene,
    *,
    keystone_name: str,
) -> None:
    """Author Grasp's permanent health gain after each accepted proc."""
    resolved = _keystone_holder(
        scene.all_actors,
        keystone_name,
        "Grasp of the Undying",
        rune_effects.KeystoneGraspEffect,
    )
    if resolved is None:
        return
    holder, effect = resolved
    proc_events = sorted(
        (
            event
            for event in scene.outgoing.get(holder.participant_id, [])
            if str(event.get("source_key", "")) == effect.breakdown_key
        ),
        key=_sequence_reading_order,
    )
    gate = TriggerGate(inclusive=False)
    bonus_health = effect.bonus_health(bool(holder.stats.get("is_melee", True)))
    for event in proc_events:
        trigger_time = float(event.get("time", 0.0) or 0.0)
        if not gate.accepts(trigger_time, trigger_time):
            continue
        trigger_id = str(event.get("_event_id", ""))
        scene.support_effects[holder.participant_id].append(
            _reactive_candidate(
                holder=holder,
                recipient=holder.participant_id,
                keystone="Grasp of the Undying",
                label="Permanent health",
                kind="stat_buff",
                time=trigger_time + 1e-9,
                rank=TransitionRank.DEBUFF_ARM,
                event_id=f"{holder.participant_id}:grasp:{trigger_id}",
                trigger_id=trigger_id,
                sequence=int(event.get("sequence", 0) or 0),
                bonus_health=bonus_health,
                _grasp_permanent_health=True,
                grasp_bonus_health=bonus_health,
            )
        )


def _schedule_glacial_events(
    scene: TimelineScene,
    *,
    keystone_name: str,
) -> None:
    """Author Glacial's zones from the holder's reviewed control events."""
    resolved = _keystone_holder(
        scene.all_actors,
        keystone_name,
        "Glacial Augment",
        rune_effects.KeystoneGlacialEffect,
    )
    if resolved is None:
        return
    holder, effect = resolved
    actor_by_id = {actor.participant_id: actor for actor in scene.all_actors}
    allied_targets = [
        actor
        for actor in scene.all_actors
        if actor.participant_id != holder.participant_id
        and ("main" if actor.team in {"main", "ally"} else actor.team) == "main"
    ]
    slow_percent = effect.slow_ratio(holder.stats) * 100.0
    gate = TriggerGate(effect.cooldown_seconds, inclusive=True)
    for event, cc_kind, cc_duration in _immobilizing_controls(
        scene.outgoing.get(holder.participant_id, [])
    ):
        target_id = str(event.get("target", ""))
        target_actor = actor_by_id.get(target_id)
        if target_actor is None or target_actor.team != "enemy":
            continue
        trigger_time = float(event.get("time", 0.0) or 0.0)
        key = (str(event.get("source_key", "")), round(trigger_time, 9), cc_kind)
        if not gate.accepts(trigger_time, key):
            continue
        trigger_id = str(event.get("_event_id", ""))
        activation_time = trigger_time + 1e-9
        sequence = int(event.get("sequence", 0) or 0)
        zone_duration = effect.zone_duration(cc_duration)
        zone_id = f"{holder.participant_id}:glacial:{trigger_id}"
        zone_fields = {
            "glacial_ray_count": effect.ray_count,
            "glacial_zone_radius_units": effect.zone_radius_units,
            "glacial_zone_width_units": effect.zone_width_units,
            "glacial_zone_duration": zone_duration,
            "glacial_slow_percent": slow_percent,
            "glacial_damage_reduction_ratio": effect.damage_reduction_ratio,
        }
        # The zone outlives the control that dropped it, so its rows are not
        # reactive republishes and the walk sorts them itself.
        scene.support_effects[target_id].append(
            _reactive_candidate(
                holder=holder,
                recipient=target_id,
                keystone="Glacial Augment",
                label="Icy zone",
                kind=PacketKind.SLOW.value,
                time=activation_time,
                rank=TransitionRank.BARRIER_GRANT,
                event_id=f"{zone_id}:slow",
                trigger_id=trigger_id,
                sequence=sequence,
                amount=slow_percent,
                target_scope="enemy_champion",
                target_policy="immobilized_target",
                reactive=False,
                sort_key=False,
                slow_percent=slow_percent,
                duration=zone_duration,
                _glacial_zone=dict(zone_fields),
                **zone_fields,
            )
        )
        for ally in allied_targets:
            scene.support_effects[ally.participant_id].append(
                _reactive_candidate(
                    holder=holder,
                    recipient=ally.participant_id,
                    keystone="Glacial Augment",
                    label="Ally damage reduction",
                    kind=PacketKind.DAMAGE_MODIFIER.value,
                    time=activation_time,
                    rank=TransitionRank.AURA_ARM,
                    event_id=f"{zone_id}:reduction:{ally.participant_id}",
                    trigger_id=trigger_id,
                    sequence=sequence,
                    amount=effect.damage_reduction_ratio,
                    target_scope="ally_champion",
                    target_policy="glacial_zone",
                    reactive=False,
                    sort_key=False,
                    duration=zone_duration,
                    multiplier=1.0 - effect.damage_reduction_ratio,
                    all_sources=True,
                    # The zone reduces "damage dealt" with no carve-out
                    # in the sourced prose, so every damage and attack class
                    # is the full declaration - never an empty one.
                    damage_classes=frozenset(DamageClass),
                    attack_classes=frozenset(AttackClass),
                    source_participant=target_id,
                    _glacial_zone=dict(zone_fields),
                    **zone_fields,
                )
            )
        gate.arm(trigger_time)


def _schedule_stormraider_events(
    scene: TimelineScene,
    *,
    keystone_name: str,
) -> None:
    """Author Stormraider's movement burst from exact damage windows."""
    resolved = _keystone_holder(
        scene.all_actors,
        keystone_name,
        "Stormraider's Surge",
        rune_effects.KeystoneStormraiderEffect,
    )
    if resolved is None:
        return
    holder, effect = resolved
    actors_by_id = {actor.participant_id: actor for actor in scene.all_actors}
    events_by_target: dict[str, list[tuple[float, int, dict[str, Any], float]]] = (
        defaultdict(list)
    )
    for event_index, event in enumerate(scene.outgoing.get(holder.participant_id, [])):
        target_id = str(event.get("target", ""))
        target = actors_by_id.get(target_id)
        if target is None or target.team != "enemy":
            continue
        try:
            event_time = float(event.get("time", 0.0) or 0.0)
            damage = float(event.get("damage", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(event_time) or not math.isfinite(damage) or damage <= 0.0:
            continue
        events_by_target[target_id].append((event_time, event_index, event, damage))

    trigger_candidates: list[tuple[float, int, str, dict[str, Any], float]] = []
    for target_id, target_events in events_by_target.items():
        target_events.sort(key=lambda row: (row[0], row[1]))
        target = actors_by_id[target_id]
        threshold = effect.damage_threshold_ratio * max(
            0.0, float(target.stats.get("health", 0.0) or 0.0)
        )
        if threshold <= 0.0:
            continue
        window_damage = 0.0
        left = 0
        for index, (event_time, event_index, event, damage) in enumerate(target_events):
            window_damage += damage
            while (
                left < index
                and target_events[left][0]
                < event_time - effect.damage_window_seconds - 1e-9
            ):
                window_damage -= target_events[left][3]
                left += 1
            if window_damage + 1e-9 >= threshold:
                trigger_candidates.append(
                    (event_time, event_index, target_id, event, window_damage)
                )

    trigger_candidates.sort(key=lambda row: (row[0], row[1], row[2]))
    gate = TriggerGate(effect.cooldown_at(holder.level), inclusive=True)
    move_speed = effect.bonus_move_speed_percent(
        bool(holder.stats.get("is_melee", True))
    )
    slow_resist_percent = effect.slow_resist_ratio * 100.0
    for (
        trigger_time,
        event_index,
        target_id,
        trigger,
        window_damage,
    ) in trigger_candidates:
        trigger_id = str(
            trigger.get(
                "_event_id",
                f"{holder.participant_id}:{target_id}:stormraider:{event_index}",
            )
        )
        if not gate.accepts(trigger_time, trigger_id):
            continue
        scene.support_effects[holder.participant_id].append(
            _reactive_candidate(
                holder=holder,
                recipient=holder.participant_id,
                keystone="Stormraider's Surge",
                label="Movement burst",
                kind=PacketKind.MOVEMENT.value,
                time=trigger_time + 1e-9,
                rank=TransitionRank.BARRIER_GRANT,
                event_id=f"{holder.participant_id}:stormraider:{trigger_id}",
                trigger_id=trigger_id,
                sequence=int(trigger.get("sequence", event_index) or event_index),
                amount=move_speed,
                bonus_move_speed_percent=move_speed,
                slow_resist_percent=slow_resist_percent,
                duration=effect.duration_seconds,
                stormraider_damage_threshold_ratio=effect.damage_threshold_ratio,
                stormraider_damage_window_seconds=effect.damage_window_seconds,
                stormraider_trigger_damage=window_damage,
                stormraider_target_max_health=actors_by_id[target_id].stats.get(
                    "health", 0.0
                ),
                stormraider_cooldown_seconds=effect.cooldown_at(holder.level),
                _stormraider=True,
            )
        )
        gate.arm(trigger_time)


def _aery_support_templates(
    attacker: Combatant,
    result: Mapping[str, Any],
    trigger_effects: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Turn the first accepted ally heal or shield signal into Aery's shield."""
    if str(result.get("keystone", "")) != "Summon Aery":
        return []
    effect = rune_effects.resolve_keystone("Summon Aery")
    if not isinstance(effect, rune_effects.KeystoneAeryEffect):
        return []
    stats = result.get("champion_stats", attacker.stats)
    if not isinstance(stats, Mapping):
        raise ValueError(
            f"Summon Aery support receipt for {attacker.participant_id} "
            "is missing participant stats"
        )
    templates: list[dict[str, Any]] = []
    gate = TriggerGate(inclusive=False)
    ordered = sorted(
        (event for event in trigger_effects if isinstance(event, Mapping)),
        key=lambda event: _trigger_reading_order(event, attacker.participant_id),
    )
    for trigger_index, trigger in enumerate(ordered):
        if str(trigger.get("kind", "")) not in {"heal", "shield"}:
            continue
        try:
            trigger_time = float(trigger.get("time", 0.0) or 0.0)
            trigger_amount = float(trigger.get("amount", 0.0) or 0.0)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Summon Aery trigger for {attacker.participant_id} "
                "has invalid time or amount"
            ) from exc
        if not math.isfinite(trigger_time) or not math.isfinite(trigger_amount):
            raise ValueError(
                f"Summon Aery trigger for {attacker.participant_id} "
                "has non-finite time or amount"
            )
        if (
            trigger_amount <= 0.0 and not callable(trigger.get("amount_formula"))
        ) or not gate.accepts(trigger_time):
            continue
        target = str(trigger.get("target", ""))
        if not target:
            raise ValueError(
                f"Summon Aery trigger for {attacker.participant_id} "
                "is missing its resolved target"
            )
        source_event_id = str(
            trigger.get(
                "_event_id", f"{attacker.participant_id}:support:{trigger_index}"
            )
        )
        templates.append(
            {
                "time": trigger_time + effect.shield_flight_seconds,
                "kind": "shield",
                "amount": effect.shield_amount(attacker.level, stats),
                "duration": effect.shield_duration_seconds,
                "source": "Summon Aery · Shield",
                "source_key": "rune_Summon Aery",
                "attacker": attacker.participant_id,
                "target": target,
                "target_scope": (
                    "self"
                    if target == attacker.participant_id
                    else "explicit_selected_ally"
                ),
                "target_policy": trigger.get("target_policy", "affected_ally"),
                "_event_id": f"{attacker.participant_id}:aery:{trigger_index}",
                "_trigger_event_id": source_event_id,
                "aery_trigger_source": str(trigger.get("source", "")),
            }
        )
        # Return travel has no fixed source duration.  The same lower-bound
        # cadence as the offensive Aery path uses the sourced linger window:
        # Aery flies, lands, and lingers there.
        gate.arm(
            trigger_time + effect.shield_flight_seconds,
            cooldown=effect.linger_seconds,
        )
    return templates


def _owned_state_event_id(
    participant_id: str, effect: Mapping[str, Any], state_index: int
) -> str:
    """Re-key a self-state packet's id to its owner, once, at the fold.

    Modules and keystones author champion-local ids (``self_state:R:0:0``),
    so two actors holding one mechanic collide on a panel and cross-link as
    walk join keys; an id already naming this actor is left verbatim.
    """
    authored = effect.get("_event_id")
    if authored is None:
        return f"{participant_id}:state:{state_index}"
    text = str(authored)
    prefix = f"{participant_id}:"
    return text if text.startswith(prefix) else f"{prefix}{text}"


#: Stamped on a support template whose amount was priced off its RECIPIENT's
#: build (Taric W's Bastion).  An optimizer candidate changes that build, so
#: a list carrying one is derived per evaluation instead of being served from
#: the per-search pair-view cache.
RECIPIENT_SCALED_KEY = "_recipient_scaled"


def _support_effect_templates(
    attacker: Combatant,
    result: Mapping[str, Any],
    all_actors: list[Combatant],
    *,
    pair_defender_id: str | None,
    damage_events: Iterable[Mapping[str, Any]] | None = None,
    target_id: str | None = None,
    denial_receipts: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Derive one actor's sourced shield/heal packets, resolved to targets.

    Returned templates are reusable across optimizer candidates (the roster
    and each cached pair result are fixed), so they ride the pair packet;
    application shallow-copies each one because the survival walk annotates
    its copy.  ``item_denial`` receipts are split out of the returned list
    and appended to ``denial_receipts`` when a collector is provided.

    ``pair_defender_id`` is required and has no default: it names the pair
    fight ``result`` was priced in, which every caller already knows, and the
    heal fan-out below needs it to rebuild the pair-enriched id of the
    attacker's applied self-heal copy.  ``None`` is the honest answer for an
    actor with no opponents, which is why the annotation is optional while
    the argument is not.
    """
    if attacker.team == "ally" and not attacker.request.ally_effects_enabled:
        return []
    request = attacker.request
    effects = derive_ally_effects(
        attacker.champion_data,
        attacker.level,
        result.get("champion_stats", attacker.stats),
        list(result.get("cast_timeline", [])),
        ability_ranks=request.ability_ranks,
        champion_options=request.champion_options,
    )
    if "combat_events" in result and attacker.champion_data["name"] == "Lulu":
        effects.extend(
            derive_lulu_support_events(
                attacker.champion_data,
                attacker.level,
                result.get("champion_stats", attacker.stats),
                list(result.get("cast_timeline", [])),
                ability_ranks=request.ability_ranks,
            )
        )
    templates = []
    state_events = [
        *result.get("self_state_events", []),
        *result.get("keystone_state_events", []),
    ]
    for state_index, effect in enumerate(state_events):
        if not isinstance(effect, Mapping):
            continue
        templates.append(
            {
                **effect,
                "attacker": attacker.participant_id,
                "target": attacker.participant_id,
                "target_scope": "self",
                "target_policy": "self",
                "_event_id": _owned_state_event_id(
                    attacker.participant_id, effect, state_index
                ),
            }
        )
    if attacker.team == "ally" and not getattr(
        attacker.request, "ally_effects_enabled", False
    ):
        return templates
    for effect_index, effect in enumerate(effects):
        if "combat_events" in result:
            authored = next(
                (
                    event
                    for event in result["combat_events"]
                    if event["slot"] == effect.get("slot")
                    and abs(event["time"] - float(effect.get("time", 0))) < 0.00051
                ),
                None,
            )
            if authored is None:
                continue
            recipient = next(
                actor
                for actor in all_actors
                if actor.participant_id == authored["recipient_id"]
            )
            if (recipient.team == "enemy") != (attacker.team == "enemy"):
                continue
            # The packet's sourced scope, not the named recipient, decides
            # who a whole-team cast reaches: Seraphine W and Soraka R cover
            # the side whoever the author named, Sona W and Taric W cover
            # the caster and the one ally named, and every other cast lands
            # on the recipient alone.
            scope = str(effect.get("target_scope", ""))
            if scope in {"all_teammates", "self_and_all_teammates"}:
                target_ids, target_policy = _support_target_ids(
                    attacker, effect, all_actors
                )
                target_policy = f"authored_cast_{target_policy}"
            elif scope == "self_and_one_teammate":
                target_ids = [attacker.participant_id]
                if recipient.participant_id != attacker.participant_id:
                    target_ids.append(recipient.participant_id)
                target_policy = "authored_cast_recipient_and_self"
            else:
                target_ids, target_policy = [
                    recipient.participant_id
                ], "authored_cast_recipient"
        else:
            target_ids, target_policy = _support_target_ids(
                attacker, effect, all_actors
            )
        for target_index, ally_target_id in enumerate(target_ids):
            resolved_effect = dict(effect)
            if resolved_effect.get("shield_gate_target") == "attacker":
                resolved_effect["shield_gate_target"] = attacker.participant_id
            resolved_template = {
                **resolved_effect,
                "attacker": attacker.participant_id,
                "target": ally_target_id,
                "target_policy": target_policy,
                "_event_id": str(
                    effect.get(
                        "_event_id",
                        f"{attacker.participant_id}:support:{effect_index}:{target_index}",
                    )
                ),
            }
            if "combat_events" in result:
                resolved_template["_event_id"] = (
                    f"authored:{authored['id']}:support"
                    + (f":{target_index}" if len(target_ids) > 1 else "")
                )
                resolved_template["cast_blocked_by_attacker_control"] = True
            # P1-Renata-W: a champion-authored fail-closed denial (Bailout's
            # withheld lethal-damage half) is a RECEIPT, not an applied
            # packet — it rides the same split the item scan already uses so
            # the survival walk can never misread it as a shield or heal.
            if is_denial_receipt(resolved_template):
                if denial_receipts is not None:
                    denial_receipts.append(resolved_template)
                continue
            ratio = resolved_template.pop("recipient_max_health_ratio", None)
            if ratio is not None and ally_target_id != attacker.participant_id:
                # Taric W's Bastion pays each recipient a share of their OWN
                # maximum health, and only here is that recipient in hand.
                # The mark is what keeps the priced packet off the
                # per-search template cache: an optimizer candidate moves
                # the recipient's maximum health under it.
                recipient = next(
                    actor
                    for actor in all_actors
                    if actor.participant_id == ally_target_id
                )
                resolved_template["amount"] = max(
                    0.0, float(ratio) * float(recipient.stats.get("health", 0.0) or 0.0)
                )
                resolved_template[RECIPIENT_SCALED_KEY] = True
                if resolved_template["amount"] <= 0.0:
                    continue
            templates.append(resolved_template)
    # Fan out champion-owned heal events (authored by the E1 self-heal rule
    # for slots in ``_MODULE_AUTHORED_HEAL_SLOTS``, Taric Q today) to the
    # attacker's selected allies.  The self copy stays in the attacker's
    # healing ledger at its original event id; each ally copy is one support
    # heal template with the same time/amount/source/kind,
    # ``_event_id = f"{self_id}:ally:{i}"`` and ``_source_event_id`` = the
    # self copy's id, so the receipt can prove one formula priced every
    # recipient.  The clones are added BEFORE item support effects so item
    # passives that trigger off ally heals/shields (Moonstone Renewer) see
    # them.
    applied_pair_defender = _routed_pair_defender_id(pair_defender_id, all_actors)
    for heal_index, heal_event in enumerate(result.get("self_healing_events", [])):
        if not isinstance(heal_event, Mapping):
            continue
        if str(heal_event.get("target_scope", "")) not in {
            "self_and_all_teammates",
            "self_and_one_teammate",
        }:
            continue
        resolved_heal_event = dict(heal_event)
        if not resolved_heal_event.get("target_selection_key"):
            resolved_heal_event["target_selection_key"] = (
                f"heal:{resolved_heal_event.get('source', 'ability')}:{heal_index}"
            )
        target_ids, target_policy = _support_target_ids(
            attacker, resolved_heal_event, all_actors
        )
        # An authored cast names the one ally a self-and-one heal reaches
        # (Sona W); a whole-side heal keeps the roster it already resolved.
        if (
            "combat_events" in result
            and str(heal_event.get("target_scope", "")) == "self_and_one_teammate"
        ):
            # A heal row names its ability, not its slot; the cast names
            # its slot, so the kit's slot names join the two.
            slot_names = {
                slot: entries[0].get("name")
                for slot, entries in attacker.champion_data.get("abilities", {}).items()
                if entries and isinstance(entries[0], Mapping)
            }
            authored_heal = next(
                (
                    authored
                    for authored in result["combat_events"]
                    if slot_names.get(authored["slot"]) == heal_event.get("source")
                    and abs(authored["time"] - float(heal_event.get("time", 0)))
                    < 0.00051
                ),
                None,
            )
            if authored_heal is not None:
                target_ids = [attacker.participant_id]
                if authored_heal["recipient_id"] != attacker.participant_id:
                    target_ids.append(authored_heal["recipient_id"])
                target_policy = "authored_cast_recipient_and_self"
        raw_id = heal_event.get("_event_id") or (
            f"{attacker.participant_id}:heal:{heal_index}"
        )
        applied_self_id = (
            f"{raw_id}:{applied_pair_defender}"
            if applied_pair_defender
            else str(raw_id)
        )
        for ally_index, heal_target_id in enumerate(target_ids):
            if heal_target_id == attacker.participant_id:
                continue
            templates.append(
                {
                    **{
                        key: value
                        for key, value in resolved_heal_event.items()
                        if key != "_sk"
                    },
                    # The clone is a support heal packet (like the scanner
                    # packet it replaces), so it rides the heal application
                    # phase and counts toward the attacker's healing output.
                    "kind": "heal",
                    "attacker": attacker.participant_id,
                    "target": heal_target_id,
                    "target_policy": target_policy,
                    "_event_id": f"{applied_self_id}:ally:{ally_index}",
                    "_source_event_id": applied_self_id,
                }
            )
    if damage_events is None:
        # No per-event override: the item scan reads the engine result as-is
        # (it never mutates it), so skip the per-candidate dict copy.
        item_result: Mapping[str, Any] = result
    else:
        item_result = dict(result)
        item_result["damage_events"] = list(damage_events)
        if (
            target_id
            and float(result.get("target_ending_health", 1.0) or 0.0) <= 0.0
            and item_result["damage_events"]
        ):
            kill_time = max(
                float(event.get("time", 0.0) or 0.0)
                for event in item_result["damage_events"]
                if isinstance(event, Mapping)
            )
            item_result["takedown_events"] = [
                {
                    "time": kill_time,
                    "target": target_id,
                    "attacker": attacker.participant_id,
                }
            ]
    item_templates = derive_item_support_effects(
        attacker,
        item_result,
        all_actors,
        trigger_effects=templates,
    )
    # Fail-closed item denials (Fimbulwinter Everlasting: ranged_slow,
    # mana_gate, cooldown, duplicate_instance, untyped_cc, unknown_cc_kind)
    # are RECEIPTS, not applied packets: they never ride the applied support
    # stream (the survival walk, compiled panels, and public support events
    # would misread them as shields).  When the caller provides a collector
    # they are routed there for the public denial-receipt section; otherwise
    # they are dropped from the applied stream entirely.
    for template in item_templates:
        if is_denial_receipt(template):
            if denial_receipts is not None:
                denial_receipts.append(dict(template))
            continue
        templates.append(_apply_item_support_selection(attacker, template, all_actors))
    # The champion-cast cleanse (Gangplank W Remove Scurvy).
    #  Every W cast is a cleanse activation at the cast time — the game's
    #  W is a heal+cleanse cast, NOT an optional toggle (no user option;
    #  W rank 0 -> no cast -> no packet).  The packet rides the
    #  item-cleanse kernel (per-fight one-use latch, interval truncation,
    #  named denials); the heal is the separate E1 self-heal receipt.
    champion_name = str(attacker.champion_data.get("name", ""))
    if champion_name == "Gangplank":
        for cast_index, cast in enumerate(result.get("cast_timeline", ())):
            if str(_row_cast_slot(cast)) != "W":
                continue
            cast_time = float(_row_cast_time(cast))
            templates.append(
                {
                    "kind": PacketKind.CLEANSE.value,
                    "time": cast_time,
                    "amount": 1.0,
                    "target_scope": "self",
                    "target_policy": "self",
                    "cleanse_item": "Gangplank W",
                    "source_key": "Gangplank W",
                    "utility_kind": "cleanse",
                    "source": "Gangplank W — Remove Scurvy",
                    "attacker": attacker.participant_id,
                    "target": attacker.participant_id,
                    "_event_id": (f"{attacker.participant_id}:cleanse:W:{cast_index}"),
                }
            )
    elif champion_name == "Rengar":
        # The EMPOWERED-W cleanse (Rengar Battle Roar).  The
        # condition is the 3V Ferocity walk's LIVE per-cast flag —
        # breakdown["ferocity"]["stack_events"] (slot + ordinal matched to
        # the cast_timeline W row) — NEVER the seeded p_ferocity alone (a
        # Q-first rotation consumes the cap so the seed-4 W@0 cast stays
        # BASE).  Non-empowered W casts author NOTHING (absence — the same
        # authoring gate as W rank 0).  The E8a grey-health heal stays the
        # separate authored heal per cast.
        w_casts = [
            cast
            for cast in result.get("cast_timeline", ())
            if str(_row_cast_slot(cast)) == "W"
        ]
        if w_casts:
            ferocity_row = (result.get("breakdown") or {}).get("ferocity") or {}
            stack_events = ferocity_row.get("stack_events")
            if not isinstance(stack_events, list):
                raise KeyError(
                    "Rengar breakdown has no ferocity stack_events row — "
                    "the empowered-W cleanse cannot author without the "
                    "live per-cast flags"
                )
            empowered_by_ordinal = {
                int(event.get("ordinal", 0) or 0): bool(event.get("empowered"))
                for event in stack_events
                if str(event.get("slot", "")) == "W"
            }
            for cast_index, cast in enumerate(w_casts):
                if not empowered_by_ordinal.get(
                    int(_row_cast_ordinal(cast) or 0), False
                ):
                    continue
                cast_time = float(_row_cast_time(cast))
                templates.append(
                    {
                        "kind": PacketKind.CLEANSE.value,
                        "time": cast_time,
                        "amount": 1.0,
                        "target_scope": "self",
                        "target_policy": "self",
                        "cleanse_item": "Rengar W",
                        "source_key": "Rengar W",
                        "utility_kind": "cleanse",
                        "source": "Rengar W — Battle Roar",
                        "attacker": attacker.participant_id,
                        "target": attacker.participant_id,
                        "_event_id": (
                            f"{attacker.participant_id}:cleanse:W:{cast_index}"
                        ),
                    }
                )
    elif champion_name == "Milio":
        for cast_index, cast in enumerate(result.get("cast_timeline", ())):
            if str(_row_cast_slot(cast)) != "R":
                continue
            cast_time = float(_row_cast_time(cast))
            group = f"{attacker.participant_id}:milio:r:{cast_index}"
            recipients, _target_policy = _support_target_ids(
                attacker,
                {"target_scope": "self_and_all_teammates"},
                all_actors,
            )
            templates.extend(
                {
                    "kind": PacketKind.CLEANSE.value,
                    "time": cast_time,
                    "amount": 1.0,
                    "target_scope": "self_and_all_teammates",
                    "target_policy": "self_and_all_selected_teammates",
                    "cleanse_item": "Milio R",
                    "cleanse_group": group,
                    "cast_blocked_by_attacker_control": True,
                    "source_key": "Milio R",
                    "utility_kind": "cleanse",
                    "source": "Milio R — Breath of Life",
                    "attacker": attacker.participant_id,
                    "target": recipient_id,
                    "_event_id": (
                        f"{attacker.participant_id}:cleanse:R:"
                        f"{cast_index}:{recipient_index}"
                    ),
                }
                for recipient_index, recipient_id in enumerate(recipients)
            )
    elif champion_name in ("DrMundo", "Dr. Mundo"):
        # Goes Where He Pleases — the passive IMMUNITY arm.
        #  One arm packet per fight at t=0 (self scope, pre-damage
        #  priority -2.0, so it sorts before same-timestamp hostile
        #  controls); the kernel resists the next hostile immobilizing
        #  control (4%-current-health cost + canister drop receipt; the
        #  pickup heal / enemy destruction are named unsupported
        #  timings).  NO user toggle — the passive is always armed.
        templates.append(
            {
                "kind": "crowd_control_resist",
                "time": 0.0,
                "amount": 0.0,
                "target_scope": "self",
                "target_policy": "self",
                "source_key": "Dr. Mundo P",
                "source": "Dr. Mundo P — Goes Where He Pleases",
                "attacker": attacker.participant_id,
                "target": attacker.participant_id,
                "_event_id": f"{attacker.participant_id}:mundo_p:arm",
            }
        )
    elif champion_name == "Olaf":
        # The R rank comes from the request's ability ranks (the result's
        # ability_damages entry may not carry the rank).
        request_ranks = getattr(
            getattr(attacker, "request", None), "ability_ranks", None
        )
        r_rank = 1
        if isinstance(request_ranks, dict):
            r_rank = max(1, min(3, int(request_ranks.get("R", 1) or 1)))
        olaf_r_bonus_resists = (10.0, 15.0, 20.0)[r_rank - 1]
        olaf_r_first_second_ms = (20.0, 45.0, 70.0)[r_rank - 1]
        # Ragnarok: the R cast IS the activation (no toggle,
        # no typed option) — one cast authors FOUR separate receipts: the
        # cast-time CLEANSE (the displacement family
        # excluded — the notes' blink/dash carve-out), the 3s IMMUNITY
        # window (duration-armed crowd_control_resist — blocks new
        # hostile blocking controls, end-exclusive), the armor/MR stat
        # buffs (3s, receipted never consumed by mitigation), and the
        # first-second movement-speed utility packet.  The AD + 10% size
        # + 2.5s duration-extension are receipted named-unsupported (no
        # kernel fields) via the module constants; the MS facing/2000-
        # unit condition is prose-only.
        for cast in result.get("cast_timeline", ()):
            if str(_row_cast_slot(cast)) != "R":
                continue
            cast_time = float(_row_cast_time(cast))
            cast_index = int(_row_cast_ordinal(cast) or 0)
            templates.append(
                {
                    "kind": PacketKind.CLEANSE.value,
                    "time": cast_time,
                    "amount": 1.0,
                    "target_scope": "self",
                    "target_policy": "self",
                    "cleanse_item": "Olaf R",
                    "source_key": "Olaf R",
                    "utility_kind": "cleanse",
                    "source": "Olaf R — Ragnarok",
                    "attacker": attacker.participant_id,
                    "target": attacker.participant_id,
                    "_event_id": f"{attacker.participant_id}:olaf:r:cleanse:{cast_index}",
                }
            )
            templates.append(
                {
                    "kind": "crowd_control_resist",
                    "time": cast_time,
                    "amount": 0.0,
                    "duration": 3.0,
                    "target_scope": "self",
                    "target_policy": "self",
                    "source_key": "Olaf R",
                    "source": "Olaf R — Ragnarok",
                    "attacker": attacker.participant_id,
                    "target": attacker.participant_id,
                    "_event_id": f"{attacker.participant_id}:olaf:r:immunity:{cast_index}",
                }
            )
            templates.append(
                {
                    "kind": "stat_buff",
                    "time": cast_time,
                    "amount": 0.0,
                    "duration": 3.0,
                    "bonus_armor": olaf_r_bonus_resists,
                    "bonus_magic_resistance": olaf_r_bonus_resists,
                    "target_scope": "self",
                    "target_policy": "self",
                    "source": "Olaf R — Ragnarok",
                    "source_key": "Olaf R",
                    "attacker": attacker.participant_id,
                    "target": attacker.participant_id,
                    "_event_id": f"{attacker.participant_id}:olaf:r:stats:{cast_index}",
                }
            )
            templates.append(
                {
                    "kind": PacketKind.MOVEMENT.value,
                    "time": cast_time,
                    "amount": olaf_r_first_second_ms,
                    "duration": 1.0,
                    "target_scope": "self",
                    "target_policy": "self",
                    "source": "Olaf R — Ragnarok",
                    "source_key": "Olaf R",
                    "attacker": attacker.participant_id,
                    "target": attacker.participant_id,
                    "_event_id": f"{attacker.participant_id}:olaf:r:ms:{cast_index}",
                }
            )
    templates.extend(_aery_support_templates(attacker, result, templates))
    return templates


def _attached_support_templates(
    view: PairView,
    attacker: Combatant,
    all_actors: list[Combatant],
    *,
    pair_defender_id: str | None,
    damage_events: Iterable[Mapping[str, Any]] | None = None,
    target_id: str | None = None,
    denial_receipts: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """One attacker's support templates, cached on the pair view when they can be.

    The one home of that decision, for all three composition paths.  A list
    holding a packet priced off a RECIPIENT's build cannot be served from
    the per-search cache — the next optimizer candidate moves that
    recipient's maximum health under it — so it is rebuilt per evaluation
    and everything else keeps riding the pair packet.
    """
    if view.support is not None:
        if denial_receipts is not None:
            denial_receipts.extend(dict(row) for row in view.support_denials or ())
        return view.support
    denials: list[dict[str, Any]] = []
    templates = _support_effect_templates(
        attacker,
        view.result,
        all_actors,
        pair_defender_id=pair_defender_id,
        damage_events=damage_events,
        target_id=target_id,
        denial_receipts=denials,
    )
    if denial_receipts is not None:
        denial_receipts.extend(dict(row) for row in denials)
    if not any(template.get(RECIPIENT_SCALED_KEY) for template in templates):
        view.support = templates
        view.support_denials = denials
    return templates


def _attach_support_effects(
    attacker: Combatant,
    result: Mapping[str, Any],
    all_actors: list[Combatant],
    support_effects: Mapping[str, list[dict[str, Any]]],
    *,
    outgoing: dict[str, list[dict[str, Any]]] | None = None,
    incoming: dict[str, list[dict[str, Any]]] | None = None,
    denial_receipts: list[dict[str, Any]] | None = None,
) -> None:
    """Attach one actor's sourced shield/heal packets exactly once.

    The one caller is the composition's fallback pass — an actor whose
    support schedule resolved with no opposing target selected — so there is
    no pair fight to name and ``pair_defender_id`` is ``None`` by fact
    rather than by omission.

    Fail-closed item denials (``kind == "item_denial"``) are collected into
    ``denial_receipts`` when provided and never enter the applied support
    stream.
    """
    for template in _support_effect_templates(
        attacker,
        result,
        all_actors,
        pair_defender_id=None,
        denial_receipts=denial_receipts,
    ):
        packet = dict(template)
        support_effects[template["target"]].append(packet)
        if (
            template.get("kind") == "damage"
            and outgoing is not None
            and incoming is not None
        ):
            outgoing[template["attacker"]].append(packet)
            incoming[template["target"]].append(packet)


def _roster_actors(loadouts: Sequence[ResolvedLoadout], team: str) -> list[Combatant]:
    """Every loadout on one team, as combatants carrying unique ids.

    The id rule lives here and nowhere else, because it is load-bearing
    rather than cosmetic: ``index_of`` maps participant id to walk slot, so
    two actors sharing an id would share a slot, and every packet aimed at
    either would land on one of them.

    A champion appearing once keeps ``team:Name``, the id every golden,
    receipt and UI selector holds.  Only a repeat is suffixed, counting from
    2 in roster order.
    """
    seen: dict[str, int] = {}
    actors: list[Combatant] = []
    for loadout in loadouts:
        base = f"{team}:{loadout.champion_data['name']}"
        seen[base] = seen.get(base, 0) + 1
        occurrence = seen[base]
        actors.append(
            from_loadout(
                base if occurrence == 1 else f"{base}:{occurrence}", team, loadout
            )
        )
    return actors


def _schedule_thorns_events(
    scene: TimelineScene,
) -> None:
    """Emit reactive Thorns events from modeled incoming basic attacks.

    Every basic-attack swing that strikes a thorns holder schedules one
    return-damage event onto the striker at the swing's own timestamp,
    linked to the strike so a skipped strike (dead striker or dead
    holder) never retaliates. The event also carries the wound window the
    survival walk applies to the striker's healing.
    """
    combatant_by_id = {actor.participant_id: actor for actor in scene.all_actors}
    for holder in scene.all_actors:
        profiles = thorns_effects(list(holder.items))
        if not profiles:
            continue
        strikes = [
            event
            for event in scene.incoming.get(holder.participant_id, [])
            if event.get("source_key") == "auto_attacks"
            or bool(event.get("basic_attack"))
            if not any(
                bool(event.get(marker))
                for marker in (
                    "dodged",
                    "blocked",
                    "missed",
                    "blinded",
                    "blind",
                    "evaded",
                    "attack_missed",
                )
            )
            and str(event.get("skipped_reason", ""))
            not in {"dodged", "blocked", "missed", "blinded", "evaded"}
        ]
        for index, strike in enumerate(strikes):
            striker = combatant_by_id.get(str(strike.get("attacker")))
            if striker is None:
                continue
            for profile in profiles:
                event = {
                    "time": float(strike.get("time", 0.0)),
                    "damage": thorns_return_damage(profile, holder, striker),
                    "damage_type": profile.damage_type,
                    "source_key": f"thorns_{profile.item_name}",
                    "source": f"{profile.item_name} (Thorns)",
                    "attacker": holder.participant_id,
                    "target": striker.participant_id,
                    "sequence": int(strike.get("sequence", 0) or 0),
                    "event_precision": "exact",
                    "_event_id": (
                        f"{holder.participant_id}:{striker.participant_id}"
                        f":thorns:{profile.item_name}:{index}"
                    ),
                    "_trigger_event_id": strike.get("_event_id"),
                    "_reactive": True,
                    "grievous_duration": profile.grievous_duration,
                    "_wound_source": f"{profile.item_name} · Thorns",
                    "_wound_until": float(strike.get("time", 0.0))
                    + float(profile.grievous_duration),
                }
                scene.incoming.setdefault(striker.participant_id, []).append(event)
                scene.outgoing.setdefault(holder.participant_id, []).append(event)


def _schedule_authored_reactive_events(
    incoming: dict[str, list[dict[str, Any]]],
    outgoing: dict[str, list[dict[str, Any]]],
) -> None:
    """Schedule explicitly authored reactive packets on ledger events.

    A packet is accepted only when the trigger event names its eligible
    ``reactive_trigger`` (for example ``basic_attack``).  The resolver never
    infers an item's trigger, amount, target, or timing from a name.  This
    keeps Thornmail/redirect/defender packets source-owned while allowing the
    shared survival walk to apply their damage and Grievous window in order.
    """
    known_ids = {str(participant_id) for participant_id in incoming}
    for entries in incoming.values():
        known_ids.update(
            str(event.get("attacker", "")) for event in entries if event.get("attacker")
        )
        known_ids.update(
            str(event.get("target", "")) for event in entries if event.get("target")
        )
    for target_id, events in list(incoming.items()):
        for trigger in list(events):
            packets = trigger.get("reactive_packets")
            if not isinstance(packets, list):
                continue
            trigger_kind = str(trigger.get("trigger_kind", ""))
            trigger_id = trigger.get("_event_id")
            for index, packet in enumerate(packets):
                if not isinstance(packet, Mapping):
                    continue
                eligible = packet.get("reactive_trigger")
                if not isinstance(eligible, str) or eligible != trigger_kind:
                    continue
                target = str(packet.get("target", trigger.get("attacker", "")))
                if not target or target not in known_ids:
                    continue
                try:
                    amount = max(0.0, float(packet["damage"]))
                except (KeyError, TypeError, ValueError):
                    continue
                event = {
                    "time": float(packet.get("time", trigger.get("time", 0.0))),
                    "damage": amount,
                    "damage_type": str(packet.get("damage_type", "")),
                    "source_key": str(packet.get("source_key", "")),
                    "source": str(packet.get("source", packet.get("source_key", ""))),
                    "attacker": str(packet.get("attacker", target_id)),
                    "target": target,
                    "sequence": int(trigger.get("sequence", 0) or 0),
                    "event_precision": packet.get("event_precision", "exact"),
                    "_event_id": f"{trigger_id}:reactive:{index}",
                    "_trigger_event_id": trigger_id,
                    "_reactive": True,
                }
                if packet.get("grievous_duration") is not None:
                    event["grievous_duration"] = float(packet["grievous_duration"])
                    event["_wound_source"] = str(
                        packet.get("wound_source", event["source"])
                    )
                    event["_wound_until"] = event["time"] + event["grievous_duration"]
                incoming.setdefault(target, []).append(event)
                outgoing.setdefault(event["attacker"], []).append(event)


def _routing_build(
    combatant: Combatant, duration: float
) -> tuple[list[str], FightFacts]:
    """One participant's item names and the fight facts a routing rule reads,
    assembled once for the three walk-lane resolvers.  A routing rule moves a
    packet rather than scaling one, so ``target_bonus_health`` is 0.
    """
    return [str(item.get("name", "")) for item in combatant.items], FightFacts(
        level=int(combatant.stats.get("level", 1) or 1),
        fight_duration_seconds=duration,
        target_bonus_health=0.0,
        holder_is_melee=bool(combatant.stats.get("is_melee", True)),
    )


def _venom_profile(combatant: Combatant, duration: float) -> tuple[float, float] | None:
    """The ``(keep, duration)`` pair the kernel's shield ledger reads."""
    owners, facts = _routing_build(combatant, duration)
    venom = walk_venom(owners, facts=facts)
    return None if venom is None else (venom.keep, venom.duration)


def _execution_rider(combatant: Combatant, duration: float) -> Any:
    """The Execute rider this participant's own declarations arm, or ``None``."""
    owners, facts = _routing_build(combatant, duration)
    return walk_execution(owners, facts=facts)


def _simulate_survival(
    combatants: Iterable[Combatant],
    incoming: Mapping[str, list[dict[str, Any]]],
    healing: Mapping[str, list[dict[str, Any]]],
    support_effects: Mapping[str, list[dict[str, Any]]],
    duration: float,
    *,
    annotate: bool = True,
    receipt_events: MutableMapping[str, list[dict[str, Any]]] | None = None,
    work_counters: WorkCounterSink | None = None,
) -> WalkResult:
    """Resolve damage, shields, healing, and death for every participant.

    Returns the frozen :class:`~.program.walk.WalkResult` rather than the
    published rows.  The rows are a *projection* of that result and the
    survival view is the one thing that makes them, so a composition that
    took rows here could not also hand its walk to the other four views --
    which is how the score path and the receipt path came to assemble two
    payloads from two shapes of the same walk.

    ``annotate=False`` skips the per-event diagnostic fields that only the
    serialized public receipt reads (pair/live damage, overkill, healing
    receipts); every survival number and every field the breakdown sums —
    including each event's applied ``damage`` — is written either way.
    ``receipt_events`` is an optional outgoing ledger used only by receipt
    callers; when supplied, stateful redirect/deferred clones are mirrored
    beside their source packet without changing score-only inputs.
    ``work_counters`` is the search's sink, threaded so this pass's one entry
    into the kernel is counted (criterion 1); ``None`` outside a search.
    """
    combatant_list = list(combatants)
    combatant_by_id = {
        combatant.participant_id: combatant for combatant in combatant_list
    }
    reduction_profiles = {
        participant_id: healing_reduction_profiles(combatant.items)
        for participant_id, combatant in combatant_by_id.items()
    }
    # Serpent's Fang venom is attacker-owned: a participant whose build
    # holds the item wounds every target it damages for ``venom_duration``
    # seconds, cutting shields that target gains.  ``None`` fails closed.
    #
    # Read from the declaration through this family's own walk interpreter,
    # so the walk's barrier-state adjustment has one declared producer.
    venom_profiles = {
        participant_id: _venom_profile(combatant, duration)
        for participant_id, combatant in combatant_by_id.items()
    }
    states_list = build_states(
        combatant_list, _below_half_healing_bonuses(combatant_list)
    )
    states: dict[str, dict[str, Any]] = {
        combatant.participant_id: states_list[index]
        for index, combatant in enumerate(combatant_list)
    }
    index_of: dict[str, int] = {
        combatant.participant_id: index
        for index, combatant in enumerate(combatant_list)
    }

    # Normalize stateful packets before sorting.  Pair engines remain the
    # source of ordinary damage values; these transforms only consume
    # explicitly authored metadata on a packet and therefore fail closed
    # when a mechanic has no trigger/timing contract.
    expanded_incoming: dict[str, list[dict[str, Any]]] = defaultdict(list)
    expanded_healing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    redirect_children: dict[str, dict[str, Any]] = {}
    for participant_id, events in healing.items():
        expanded_healing[participant_id].extend(dict(event) for event in events)

    def _insert_receipt_clone(
        source_event: dict[str, Any], clone: dict[str, Any]
    ) -> None:
        """Insert a stateful clone beside its source in the outgoing receipt.

        ``incoming`` and ``outgoing`` share the same pair event objects in
        receipt mode.  The survival walk expands redirects/deferred ticks on
        the incoming side, so explicitly mirror those clones into the
        outgoing list for a complete public timeline.  Score-only callers do
        not pass ``receipt_events`` and retain the optimized event shape.
        """
        if receipt_events is None:
            return
        attacker = source_event.get("attacker")
        if attacker is None:
            return
        bucket = receipt_events.setdefault(str(attacker), [])
        try:
            index = bucket.index(source_event)
        except ValueError:
            bucket.append(clone)
            return
        # Keep multiple ticks in authored order, immediately following the
        # source packet, rather than appending them after unrelated attacks.
        while index + 1 < len(bucket):
            following = bucket[index + 1]
            source_id = str(source_event.get("_event_id", ""))
            following_id = str(following.get("_event_id", ""))
            if not source_id or not following_id.startswith(f"{source_id}:"):
                break
            index += 1
        bucket.insert(index + 1, clone)

    # Only a declared deferral holder can stamp deferral metadata; resolving
    # the holders once keeps the per-event loop below to plain marker checks.
    #
    # The rider is read from the declaration through this family's own walk
    # interpreter.  The resolver builds the same schedule and publishes it as
    # the holder's opening defensive state, which is the block a receipt
    # reader sees; this is the rider on the events the walk stages, a
    # different consumer of one declaration rather than a second producer of
    # one number.  A participant whose resolved state arms a deferral no
    # declaration produces is a stop rather than an unstamped packet.
    deferral_riders: dict[str, Any] = {}
    for participant_id, combatant in combatant_by_id.items():
        if float(combatant.defenses.damage_deferral_fraction) <= 0.0:
            continue
        owners, facts = _routing_build(combatant, duration)
        rider = walk_deferral(owners, facts=facts)
        if rider is None:
            raise ValueError(
                f"{participant_id} resolves a damage deferral and declares no "
                "damage_routing rule that produces one; the walk would defer "
                "damage no declaration priced"
            )
        deferral_riders[participant_id] = rider
    # The Execute rider, read from the attacker's own declaration through
    # this family's walk interpreter.  Resolved once per attacker, then
    # written onto every packet that attacker authored -- and *removed* from
    # packets whose attacker declares none, so a stamp the pair engine leaves
    # behind cannot decide a roster execution.
    #
    # This rider owns the ITEM execute only.  An ability execute belongs to
    # the cast that authored it -- a champion module states it on its own
    # entry (Syndra's Unleashed Power at 100 Splinters) and the pair engine
    # stamps it onto that cast's events alone -- so clearing every stamp
    # here would delete a threshold no item declaration was ever the source
    # of.  The two are reconciled the way ``damage.py`` reconciles them: an
    # item threshold applies to every packet, an ability threshold to its
    # own cast, and when both reach one packet the larger wins.
    execution_riders = {
        participant_id: _execution_rider(combatant, duration)
        for participant_id, combatant in combatant_by_id.items()
    }
    for participant_id, events in incoming.items():
        for original in events:
            event = original
            attacker_id = str(event.get("attacker", "") or "")
            if attacker_id in execution_riders:
                execution = execution_riders[attacker_id]
                by_cast = bool(original.get("execute_declared_by_cast"))
                stamped = float(original.get("execute_threshold_ratio", 0.0) or 0.0)
                if execution is None:
                    if not by_cast:
                        original.pop("execute_threshold_ratio", None)
                        original.pop("execute_source", None)
                elif execution.threshold >= stamped:
                    original["execute_threshold_ratio"] = execution.threshold
                    original["execute_source"] = execution.owner
                    original.pop("execute_declared_by_cast", None)
            target_id = str(event.get("target", participant_id))
            if "redirect_fraction" not in event:
                redirect_fraction = 0.0
                redirect_target = ""
            else:
                try:
                    redirect_fraction = float(
                        event.get("redirect_fraction", 0.0) or 0.0
                    )
                except (TypeError, ValueError):
                    redirect_fraction = 0.0
                redirect_fraction = max(0.0, min(1.0, redirect_fraction))
                redirect_target = str(event.get("redirect_target", ""))
            if redirect_fraction > 0.0 and redirect_target in states:
                original_amount = max(0.0, float(event.get("damage", 0.0)))
                # Knight's Vow redirects pre-mitigation damage.  A pair event
                # may only expose its post-mitigation value, so recover the
                # authored raw amount from the event when present, otherwise
                # from its effective resistance receipt.  If neither exists,
                # fail closed instead of splitting a guessed post-mitigation
                # amount between targets with different resistances.
                raw_amount: float | None = None
                if event.get("redirect_pre_mitigation_required"):
                    try:
                        candidate = float(event.get("raw_damage", 0.0) or 0.0)
                    except (TypeError, ValueError):
                        candidate = 0.0
                    if candidate > 0.0 and math.isfinite(candidate):
                        raw_amount = candidate
                    else:
                        damage_type = str(event.get("damage_type", ""))
                        baseline_key = (
                            "_baseline_effective_armor"
                            if damage_type == "physical"
                            else (
                                "_baseline_effective_mr"
                                if damage_type == "magic"
                                else ""
                            )
                        )
                        try:
                            baseline = float(event[baseline_key])
                            baseline_factor = apply_resistance(1.0, baseline)
                            if baseline_factor <= 0.0 or not math.isfinite(
                                baseline_factor
                            ):
                                raise ValueError("invalid baseline mitigation factor")
                            raw_amount = original_amount / baseline_factor
                        except (KeyError, TypeError, ValueError, ZeroDivisionError):
                            raw_amount = None
                    if raw_amount is None or not math.isfinite(raw_amount):
                        event["redirect_skipped_reason"] = (
                            "pre_mitigation_receipt_unavailable"
                        )
                        event["redirect_fraction"] = 0.0
                        expanded_incoming[target_id].append(event)
                        continue

                    source = combatant_by_id.get(str(event.get("attacker", "")))
                    protected = combatant_by_id.get(target_id)
                    holder = combatant_by_id.get(redirect_target)
                    damage_type = str(event.get("damage_type", ""))
                    if source is None or protected is None or holder is None:
                        event["redirect_skipped_reason"] = (
                            "participant_receipt_unavailable"
                        )
                        event["redirect_fraction"] = 0.0
                        expanded_incoming[target_id].append(event)
                        continue

                    declared = event.get("_declared")
                    if declared is not None and declared.routing is not None:
                        # A packet another family already re-delivered carries
                        # one route and one share; splitting it again would
                        # either lose that provenance or pay a share of a
                        # share nobody declared.
                        event["redirect_skipped_reason"] = "packet_already_routed"
                        event["redirect_fraction"] = 0.0
                        expanded_incoming[target_id].append(event)
                        continue

                    split = {
                        "damage_type": damage_type,
                        "basic_attack": bool(event.get("basic_attack")),
                        "damage_over_time": bool(event.get("damage_over_time")),
                        "source": source,
                        "raw_amount": raw_amount,
                    }
                    protected_share = knights_vow_target_factor(
                        target=protected, **split
                    )
                    holder_share = knights_vow_target_factor(target=holder, **split)
                    if protected_share is None or holder_share is None:
                        event["redirect_skipped_reason"] = (
                            "target_mitigation_receipt_unavailable"
                        )
                        event["redirect_fraction"] = 0.0
                        expanded_incoming[target_id].append(event)
                        continue
                    direct_amount = (
                        raw_amount * (1.0 - redirect_fraction) * protected_share.factor
                    )
                    redirected_amount = (
                        raw_amount * redirect_fraction * holder_share.factor
                    )
                else:
                    direct_amount = original_amount * (1.0 - redirect_fraction)
                    redirected_amount = original_amount * redirect_fraction
                redirected = {
                    **event,
                    "target": redirect_target,
                    "damage": redirected_amount,
                    "_redirected": True,
                    "_redirected_from": target_id,
                    "_redirect_fraction": redirect_fraction,
                    "_trigger_event_id": event.get("_event_id"),
                    "_event_id": f"{event.get('_event_id', '')}:redirect",
                }
                if event.get("redirect_pre_mitigation_required"):
                    redirected["raw_damage"] = raw_amount * redirect_fraction
                    redirected["redirect_pre_mitigation"] = True
                    redirected["redirect_attributed_to"] = str(
                        event.get("attacker", "")
                    )
                    redirected["_redirect_original_damage"] = original_amount
                    # The redirected share met the HOLDER's resistance: its
                    # own baseline, and its own share of any declaration the
                    # source family handed the walk.  Inheriting the Worthy's
                    # baseline and the whole declaration made the walk price
                    # this share a second time, at the wrong resistance.
                    if holder_share.effective_resistance is not None:
                        redirected.pop("_baseline_effective_armor", None)
                        redirected.pop("_baseline_effective_mr", None)
                        redirected[
                            (
                                "_baseline_effective_armor"
                                if damage_type == "physical"
                                else "_baseline_effective_mr"
                            )
                        ] = holder_share.effective_resistance
                    if declared is not None:
                        redirected["_declared"] = routed_declaration(
                            declared, redirect_fraction
                        )
                        original["_declared"] = routed_declaration(
                            declared, 1.0 - redirect_fraction
                        )
                redirected["_sk"] = action_key(
                    float(redirected.get("time", 0.0)),
                    TransitionRank.REACTIVE,
                    redirect_target,
                    redirected,
                )
                redirect_children[str(event.get("_event_id", ""))] = redirected
                expanded_incoming[redirect_target].append(redirected)
                _insert_receipt_clone(event, redirected)
                # The source packet's outgoing receipt represents the direct
                # share; the redirected clone carries the other share.  This
                # keeps public event damage additive without double counting.
                #
                # Written onto the packet the walk goes on to apply, which is
                # the same object the outgoing receipt publishes.  A second
                # dict carrying the same split would have to be kept in step
                # with every later write, and the walk's own restore is the
                # one that never was: the holder-health gate puts the whole
                # packet back on the Worthy, and a copy the publisher does
                # not hold went on showing the retracted direct share.
                event.update(
                    target=target_id,
                    damage=direct_amount,
                    _redirect_original_damage=original_amount,
                    _redirected_amount=redirected_amount,
                    _redirect_fraction=redirect_fraction,
                )

            # A declared deferral receives post-mitigation physical and magic
            # packets.  Apply its rider here, before the shared split logic,
            # so every authored source (abilities, autos, item procs, and
            # reactive packets) follows the same path.
            deferral = deferral_riders.get(target_id) if deferral_riders else None
            if (
                deferral is not None
                and not event.get("_deferred")
                and str(event.get("damage_type", "")) in {"physical", "magic"}
                and float(event.get("damage", 0.0) or 0.0) > 0.0
                and "deferred_fraction" not in event
            ):
                event["deferred_fraction"] = deferral.fraction
                event["deferred_duration"] = deferral.duration
                event["deferred_ticks"] = deferral.ticks

            # Deferred damage (for example a damage-deferral passive) is
            # represented only when the packet provides all timing fields.
            # It is split into deterministic equal true-damage ticks; no
            # hidden item-specific duration is introduced here.
            if "deferred_fraction" not in event:
                deferred_fraction, deferred_duration, deferred_ticks = 0.0, 0.0, 0
            else:
                try:
                    deferred_fraction = float(
                        event.get("deferred_fraction", 0.0) or 0.0
                    )
                    deferred_duration = float(
                        event.get("deferred_duration", 0.0) or 0.0
                    )
                    deferred_ticks = int(event.get("deferred_ticks", 0) or 0)
                except (TypeError, ValueError):
                    deferred_fraction, deferred_duration, deferred_ticks = 0.0, 0.0, 0
            if (
                deferred_fraction > 0.0
                and deferred_duration > 0.0
                and deferred_ticks > 0
                and float(event.get("damage", 0.0)) > 0.0
            ):
                deferred_fraction = min(1.0, deferred_fraction)
                full_amount = float(event["damage"])
                immediate_amount = full_amount * (1.0 - deferred_fraction)
                if receipt_events is not None:
                    # Split the outgoing source event too; the deferred clones
                    # below then reconcile exactly to its original amount.
                    original["damage"] = immediate_amount
                    original["_deferred_total"] = full_amount * deferred_fraction
                event = {
                    **event,
                    "damage": immediate_amount,
                    "_deferred_total": full_amount * deferred_fraction,
                }
                tick_amount = full_amount * deferred_fraction / deferred_ticks
                # The batch is the parent packet's own identity, so the
                # ledger of open batches is keyed by its slot -- the same
                # integer the deferred clones' ``_deferred_batch_id`` resolves
                # to when the walk builds their actions.
                batch_id = str(event.get("_event_id", ""))
                target_state = states[target_id]
                target_state["deferred_batches"][EVENT_SLOTS.slot(batch_id)] = (
                    full_amount * deferred_fraction
                )
                target_state["damage_deferral_pending"] += (
                    full_amount * deferred_fraction
                )
                for tick in range(1, deferred_ticks + 1):
                    deferred = {
                        **event,
                        "time": float(event.get("time", 0.0))
                        + deferred_duration * tick / deferred_ticks,
                        "damage": tick_amount,
                        "damage_type": "true",
                        "source_key": f"deferred_{event.get('source_key', 'damage')}",
                        "source": f"{event.get('source', event.get('source_key', ''))} (deferred)",
                        "_event_id": f"{event.get('_event_id', '')}:deferred:{tick}",
                        "_deferred": True,
                        "_deferred_from": event.get("_event_id"),
                        "_deferred_batch_id": batch_id,
                    }
                    deferred["_sk"] = action_key(
                        float(deferred.get("time", 0.0)),
                        TransitionRank.DAMAGE,
                        target_id,
                        deferred,
                    )
                    expanded_incoming[target_id].append(deferred)
                    _insert_receipt_clone(original, deferred)
            expanded_incoming[target_id].append(event)

    if isinstance(healing, MutableMapping):
        healing.clear()
        healing.update(expanded_healing)
    else:
        healing = expanded_healing

    # Guardian Angel's Rebirth is triggered by the first lethal packet, but
    # that trigger is only knowable during the live survival walk.  Author a
    # candidate revive after every incoming damage event; the walk applies the
    # earliest one only when the participant is actually dead, and ignores
    # the rest.  This preserves exact packet ordering without guessing which
    # packet becomes lethal before shields, overkill, or prior healing resolve.
    for participant_id, events in list(expanded_incoming.items()):
        revive = armed_revive(combatant_by_id[participant_id].defenses)
        if revive is None:
            continue
        revive_amount, revive_delay, revive_source, revive_key = revive
        candidates: list[dict[str, Any]] = []
        for index, event in enumerate(events):
            if str(event.get("kind", "")) in {
                "heal",
                "regen",
                "shield",
                "temporary_health",
                "revive",
            }:
                continue
            damage = max(0.0, float(event.get("damage", 0.0) or 0.0))
            if damage <= 0.0:
                continue
            event_time = float(event.get("time", 0.0))
            candidates.append(
                {
                    "time": event_time + revive_delay,
                    "kind": "revive",
                    "amount": revive_amount,
                    "source": revive_source,
                    "source_key": revive_key,
                    "sequence": int(event.get("sequence", index) or index),
                    "delay": revive_delay,
                    "_revive_candidate": True,
                }
            )
        expanded_incoming[participant_id].extend(candidates)
    incoming = expanded_incoming

    def _append_ordered_heal(participant_id: str, event: dict[str, Any]) -> None:
        """Add a sourced recovery event to the live healing mapping."""
        expanded_healing[participant_id].append(event)
        if isinstance(healing, MutableMapping):
            healing[participant_id] = expanded_healing[participant_id]

    # Warmog's Heart is a live combat-state gate; the shared author below
    # builds the exact tick events for any active holder.
    for combatant in combatant_list:
        for event in _warmog_heart_tick_events(combatant, duration):
            _append_ordered_heal(combatant.participant_id, event)

    actions: list[SurvivalAction] = []
    # One ledger per composed fight: whether a second holder of one mechanic
    # arms a second modifier on one subject is a per-mechanic declaration
    # and this is the single place ``src/`` asks it.  Abyssal Mask's
    # Unmake is the live aura — two holders in range curse an enemy once —
    # while every other dual-sided mechanic is a per-holder pool whose second
    # holder must keep its own contribution.
    arming = ArmingLedger(arming_stacking())
    for participant_id, events in support_effects.items():
        for support_index, event in enumerate(events):
            event.setdefault("_event_id", f"{participant_id}:support:{support_index}")
            if event.get("kind") == "damage":
                # Damage packets are mirrored into the normal incoming/outgoing
                # ledgers below. Keep the support copy for the public receipt,
                # but do not schedule the same object a second time here.
                continue
            dropped = arming.admit(
                str(event.get("source", "")),
                index_of[participant_id],
                index_of.get(str(event.get("attacker", "")), -1),
            )
            if dropped is not None:
                # The packet stays in the public receipt carrying its own
                # reason and an applied amount of zero, because an arming
                # that vanished leaves a reader unable to tell "the aura
                # was already up" from "nothing was ever armed here".
                event["dedupe"] = dropped.receipt()
                event["applied_amount"] = 0.0
                continue
            arm_rank = support_transition_rank(event)
            actions.append(
                action_from_event(
                    event,
                    arm_rank,
                    index_of[participant_id],
                    index_of,
                    subject_id=participant_id,
                )
            )
    # Damage resolves before self-healing and sourced recovery at the same
    # timestamp, while shields remain before damage above. Reactive
    # strike-back damage (Thorns) resolves after the strikes that
    # triggered it but still before same-timestamp healing.  Every event
    # converts here, once.
    for participant_id, events in incoming.items():
        subject = index_of[participant_id]
        for event in events:
            phase = (
                TransitionRank.REACTIVE
                if event.get("_reactive")
                else TransitionRank.DAMAGE
            )
            actions.append(
                action_from_event(
                    event,
                    phase,
                    subject,
                    index_of,
                    subject_id=participant_id,
                )
            )
    for participant_id, events in healing.items():
        subject = index_of[participant_id]
        actions.extend(
            action_from_event(
                event,
                TransitionRank.RECOVERY,
                subject,
                index_of,
                subject_id=participant_id,
            )
            for event in events
        )
    actions.sort(key=itemgetter(0))
    # Ledger slots, allocated once the total order is fixed.  The score
    # adapter has always carried them (its parallel arrays *are* indexed by
    # them); the receipt adapter left every action at ``NO_SLOT`` because the
    # event dict it annotates is addressed by identity instead.  That made
    # the receipt walk unaddressable to any slot-keyed observer, and the
    # write-once outcome ledger is exactly such an observer — it silently
    # recorded nothing, inside the record built to refuse exactly that.
    # Allocating after the sort keeps
    # the slot in walk order, so a reader can put a refusal back where the
    # walk made it.  Stamped in place rather than into a second list: an
    # action is 93 slots wide, and a comprehension holds the original and
    # the replacement together, doubling the array at the walk's peak.
    for slot, action in enumerate(actions):
        actions[slot] = action._replace(aidx=slot)

    # Knight's Vow's holder gate keys the child (redirected) action by its
    # parent's event id — the clone's ``_trigger_event_id`` — so the shared
    # walk can cancel it beside the direct share.
    redirect_children_actions = {
        EVENT_SLOTS.slot(str(child.event["_trigger_event_id"])): child
        for child in actions
        if child.redirected
        and child.event is not None
        and child.event.get("_trigger_event_id") is not None
    }
    ledger = ReceiptLedger(
        actions=actions,
        index_of=index_of,
        compile_event=action_from_event,
        annotating=annotate,
        expanded_healing=expanded_healing,
        healing=healing if isinstance(healing, MutableMapping) else None,
    )
    ctx = TransitionContext(
        duration=duration,
        states=states_list,
        combatants=combatant_list,
        index_of=index_of,
        ledger=ledger,
        regeneration_windows=_regeneration_windows(combatant_list),
        plating_windows=_plating_windows(combatant_list),
        venom_profiles=[
            venom_profiles.get(combatant.participant_id) for combatant in combatant_list
        ],
        reduction_profiles=[
            reduction_profiles.get(combatant.participant_id)
            for combatant in combatant_list
        ],
        redirect_children=redirect_children_actions,
    )
    # One kernel, two adapters.  This walk is the receipt adapter
    # (annotating events, scheduling walk-authored recovery); the optimizer
    # score path drives the identical kernel through ``ScoreLedger`` with no
    # annotations and parallel-array accumulation.  Both enter through
    # ``program.walk.walk``, the one call site in ``src/``, so one walk per
    # pass is a number a counter reads rather than two composition bodies
    # agreeing by hand.
    return walk(actions, ctx, counters=work_counters)


class CoupledSearchContext:
    """Reusable composition state for one coupled optimizer search.

    Everything here is derived from the fixed request — the roster, the
    fight params, and per-defensive-signature panels of compiled invariant
    walk actions — so it must only ever be shared across evaluations of one
    ``optimize_build`` call.  It is pure speed: force-disabling it must
    reproduce identical results (pinned by the optimizer equivalence test).
    """

    __slots__ = (
        "actor_params",
        "base_compiler",
        "base_heal_dedup",
        "base_sorted",
        "compiled_walk_enabled",
        "grievous_packs",
        "index_of",
        # Knight's Vow: the redirected child action for each parent damage
        # action the base panel split, keyed by the parent's event slot.
        # The kernel cancels the child beside its parent, so the map has to
        # travel with the panel that staged the split.
        "kv_redirect_children",
        # The main champion's wound-declaring sources are champion-fixed;
        # derived once per search instead of once per evaluation.
        "main_champion_wounds",
        "main_pair_params",
        "main_request",
        "pair_id_strings",
        # The panels' own positional event-id strings, keyed by the whole
        # pair: ``pair_id_strings`` is the main attacker's, so its defender
        # key alone would collide across roster attackers.
        "panel_id_strings",
        "panels",
        "roster_actors",
        # Each roster attacker's wound-declaring sources, champion-fixed and
        # derived once per search like the main's.
        "roster_champion_wounds",
        "roster_pair_params",
        "thorns_profiles",
        # Set when search-invariant compilation (roster pairs or a signature
        # panel) hit an unrepresentable transition; the compiled path is then
        # skipped for the rest of the search.
        "uncompilable",
        # The benchmark harness's counter sink, and its switch for forcing
        # every evaluation onto the receipt walk.
        # Both are inert unless a caller installs them, and neither can
        # change a number: the two walks are pinned equivalent.
        "work_counters",
    )

    def __init__(
        self,
        *,
        work_counters: WorkCounterSink | None = None,
        compiled_walk_enabled: bool = True,
    ) -> None:
        self.panels: dict[tuple[Any, ...], _SignaturePanel] = {}
        self.uncompilable = False
        self.work_counters = work_counters
        self.compiled_walk_enabled = compiled_walk_enabled
        self.roster_actors: list[Combatant] | None = None
        self.actor_params: dict[str, FightParams] = {}
        self.main_request: ActorRequest = ActorRequest()
        self.index_of: dict[str, int] = {}
        self.grievous_packs: dict[int, dict[str, Any]] = {}
        self.thorns_profiles: dict[int, tuple[ThornsEffect, ...]] = {}
        self.main_pair_params: list[tuple[Combatant, FightParams]] = []
        self.roster_pair_params: dict[tuple[str, str], FightParams] = {}
        self.pair_id_strings: dict[str, list[str]] = defaultdict(list)
        self.panel_id_strings: dict[tuple[str, str], list[str]] = defaultdict(list)
        self.roster_champion_wounds: dict[str, dict[str, Any]] = {}
        self.base_compiler: _WalkCompiler | None = None
        self.base_sorted: list[tuple[Any, ...]] = []
        self.base_heal_dedup: dict[int, dict[tuple[str, float], float]] = {}
        self.kv_redirect_children: dict[int, SurvivalAction] = {}
        self.main_champion_wounds: dict[str, Any] | None = None


class _SignaturePanel:  # pylint: disable=too-few-public-methods
    """The invariant walk actions for one main defensive signature.

    ``sig`` holds only the fights into this signature (enemies into the
    candidate main); everything signature-independent lives in the search
    context's base compiler.  ``sorted_actions`` is the presorted merge of
    both.
    """

    __slots__ = ("kv_redirect_children", "n_actions", "sig", "sorted_actions")

    def __init__(
        self,
        base_sorted: list[tuple[Any, ...]],
        sig: _WalkCompiler,
        *,
        kv_redirect_children: dict[int, SurvivalAction] | None = None,
    ) -> None:
        self.sig = sig
        self.kv_redirect_children = kv_redirect_children or {}
        self.n_actions = sig.next_aidx
        merged = base_sorted + sorted(sig.actions, key=itemgetter(0))
        merged.sort(key=itemgetter(0))
        self.sorted_actions = merged


def _champion_wounds_of(champion_data: Mapping[str, Any]) -> dict[str, Any]:
    """One champion's wound-declaring sources, keyed by the source they ride.

    Katarina R and Varus E ride the wound receipt an item's wound carries.
    """
    return {
        str(packet.get("source_key", "")): packet
        for packet in champion_grievous_wound_sources(champion_data)
    }


def _roster_champion_wounds(
    context: CoupledSearchContext, actor: Combatant
) -> dict[str, Any]:
    """*actor*'s wound sources, derived once per search."""
    wounds = context.roster_champion_wounds.get(actor.participant_id)
    if wounds is None:
        wounds = _champion_wounds_of(actor.champion_data)
        context.roster_champion_wounds[actor.participant_id] = wounds
    return wounds


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
    *,
    champion_name: str,
    level: int,
    pair_result_cache: dict[PairCacheKey, PairView],
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
    # The roster is search-invariant, so a loadout the compiled kernel
    # cannot represent poisons the whole context.  Checked BEFORE any pair
    # fight runs so the fallback costs nothing beyond the capability scan.
    # (Defense fields are already excluded by the dispatch pre-check; this
    # covers walk-authored item mechanics.)  Warmog's Heart is exempt: the
    # roster holder's ticks compile into the base panel below.
    for loadout in (*enemies, *allies):
        if loadout.is_practice_dummy:
            continue
        item_receipt = uncompilable_item_receipt(
            loadout.item_data,
            loadout_stats=loadout.stats,
            threshold_ticks_compiled=True,
        )
        if item_receipt is not None:
            raise UncompilableActionError(
                receipt=f"roster:{loadout.champion_data.get('name', '')}:{item_receipt}",
                source=str(loadout.champion_data.get("name", "")),
                invariant=True,
            )
    ally_actors = _roster_actors(allies, "ally")
    enemy_actors = _roster_actors(enemies, "enemy")
    context.roster_actors = [*ally_actors, *enemy_actors]
    context.index_of = {"main": 0}
    for offset, actor in enumerate(context.roster_actors, start=1):
        context.index_of[actor.participant_id] = offset
        context.thorns_profiles[offset] = thorns_effects(list(actor.items))
        _grievous_packs_for(context, offset, healing_reduction_profiles(actor.items))
        if actor.is_practice_dummy:
            continue
        context.actor_params[actor.participant_id] = _actor_params(params, actor)
    context.main_request = ActorRequest.of_params(params)
    main_params = _actor_params(
        params,
        Combatant(
            participant_id="main",
            team="main",
            champion_data={},
            level=0,
            items=(),
            stats={},
            defenses=StartingDefenses(),
            request=context.main_request,
        ),
    )
    context.actor_params["main"] = main_params
    # Every pair fight carries its roster-target allocation: the ordered
    # defender lists are [*enemies] for main/ally attackers and
    # [main, *allies] for enemy attackers, exactly like the receipt
    # composition's attack groups.  Secondary-target item branches (cleaves,
    # actives) price against these fields, and both paths share one pair
    # cache, so the params must be identical.
    for defender_index, defender in enumerate(enemy_actors):
        pair_params = replace(
            main_params,
            enforce_resource_limits=True,
            roster_target_index=defender_index,
            roster_target_count=len(enemy_actors),
            **target_overrides(defender),
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
                **target_overrides(defender),
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
    # Roster position mirrors the receipt composition's attack groups:
    # enemies are indexed from 0 for allied attackers, while an enemy
    # attacker's ordered defenders are [main, *allies], so the first ally
    # sits at index 1.
    enemy_index = {
        defender.participant_id: index for index, defender in enumerate(enemy_actors)
    }
    ally_index = {
        defender.participant_id: index for index, defender in enumerate(ally_actors)
    }
    for attacker, defender in base_pairs:
        pair_id = (attacker.participant_id, defender.participant_id)
        cache_key = _pair_cache_key(*pair_id, (), _UNPATCHED_RESTORES)
        defender_index = (
            enemy_index.get(defender.participant_id, 0)
            if attacker.team == "ally"
            else 1 + ally_index.get(defender.participant_id, -1)
        )
        wounds = _roster_champion_wounds(context, attacker)
        view = pair_result_cache.get(cache_key)
        if view is None:
            view = pair_view(
                _pair_run_fight(
                    context.work_counters,
                    attacker.champion_data,
                    attacker.level,
                    list(attacker.items),
                    params=context.roster_pair_params[pair_id],
                    validated=True,
                ),
                attacker.participant_id,
                defender.participant_id,
                defender_index,
                champion_wounds=wounds,
                amps=AmpRiders(
                    _live_amps_of(attacker, defender, params),
                    _holder_amps_of(attacker, defender, params),
                ),
            )
            pair_result_cache[cache_key] = view
        attacker_i = context.index_of[attacker.participant_id]
        base.add_engine_result(
            PairFight(
                view.engine,
                attacker.participant_id,
                defender.participant_id,
                defender_index,
                champion_wounds=wounds,
                amps=view.amps,
            ),
            WalkSlots(
                attacker_i,
                context.index_of[defender.participant_id],
                context.grievous_packs[attacker_i],
                params.fight_duration_seconds,
                context.base_heal_dedup[attacker_i],
                context.panel_id_strings[pair_id],
                # An enemy attacker's ordered pair list is [main, *allies],
                # so the dedup always keeps its main-pair copy, which lives
                # in the signature panel, not here.  Skip the ally-pair
                # copies; the engine may price them differently per defender
                # (Dr. Mundo's Maximum Dosage).
                attacker.team == "enemy",
            ),
        )
        if attacker.team == "ally" and attacker.participant_id not in support_attached:
            base.add_support_templates(
                _attached_support_templates(
                    view,
                    attacker,
                    all_actors_by_index,
                    # ``support_attached`` admits one pair per attacker, so
                    # this is the first of ``base_pairs``' defenders for it —
                    # the pair ``view.result`` was priced in, taken from the
                    # loop rather than re-derived from the roster.
                    pair_defender_id=defender.participant_id,
                    damage_events=view.events,
                ),
                attacker_i,
                context.index_of,
            )
            support_attached.add(attacker.participant_id)
    for actor in context.roster_actors:
        holder_i = context.index_of[actor.participant_id]
        profiles = context.thorns_profiles[holder_i]
        if not profiles:
            continue
        strikes = [
            (aidx, time_value, sequence, all_actors_by_index[striker_i], striker_i)
            for aidx, time_value, sequence, striker_i in (
                base.auto_strikes_into.get(holder_i, ())
            )
        ]
        if strikes:
            base.add_thorns(
                actor,
                holder_i,
                strikes,
                profiles,
                grievous_by_dtype=context.grievous_packs[holder_i],
                duration=params.fight_duration_seconds,
                id_namespace="base",
            )
    # A roster holder's active Warmog's Heart ticks are search-invariant:
    # author the same events the receipt walk schedules and convert them
    # through the same typed-action constructor, once per search (issue
    # #169).  The candidate's own Warmog still falls back per evaluation.
    for actor in context.roster_actors:
        actor_i = context.index_of[actor.participant_id]
        base.actions.extend(
            action_from_event(
                event,
                TransitionRank.RECOVERY,
                actor_i,
                context.index_of,
                subject_id=actor.participant_id,
            )
            for event in _warmog_heart_tick_events(actor, params.fight_duration_seconds)
        )
    # Knight's Vow (P3 package 3S): stage the receipt scheduler's Sacrifice
    # split + holder heals onto the search-invariant base panel once, so the
    # compiled path prices the same redirect the receipt walk does.
    kv_children: dict[int, SurvivalAction] = {}
    base_aidx = base.next_aidx
    for kv_holder in all_actors_by_index:
        kv_tether = resolve_knights_vow_tether(kv_holder, all_actors_by_index)
        if kv_tether is None:
            continue
        base_aidx = stage_knights_vow_redirect_actions(
            base, all_actors_by_index, kv_tether, kv_children, next_aidx=base_aidx
        )
        base_aidx = stage_knights_vow_heals(
            base, all_actors_by_index, kv_tether, base_aidx
        )
    base.next_aidx = base_aidx
    context.kv_redirect_children = kv_children
    context.base_compiler = base
    context.base_sorted = sorted(base.actions, key=itemgetter(0))


def _build_signature_panel(
    context: CoupledSearchContext,
    main: Combatant,
    params: FightParams,
    pair_result_cache: dict[PairCacheKey, PairView],
    *,
    signature: tuple[float | str, ...],
    all_actors: list[Combatant],
) -> _SignaturePanel:
    """Compile every roster pair fight for one main defensive signature.

    Pair packets come from (or land in) the shared ``pair_result_cache``
    under the same keys the receipt composition uses, so the two interoperate.
    Compilation order mirrors the attack-group order with the main attacker's
    fresh pairs skipped: allies into enemies, then enemies into the main and
    allies.
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
        cache_key = _pair_cache_key(
            attacker.participant_id, "main", signature, _UNPATCHED_RESTORES
        )
        wounds = _roster_champion_wounds(context, attacker)
        view = pair_result_cache.get(cache_key)
        if view is None:
            view = pair_view(
                _pair_run_fight(
                    context.work_counters,
                    attacker.champion_data,
                    attacker.level,
                    list(attacker.items),
                    params=replace(
                        context.actor_params[attacker.participant_id],
                        enforce_resource_limits=True,
                        # An enemy attacker's ordered defenders are
                        # [main, *allies].
                        roster_target_index=0,
                        roster_target_count=1 + ally_count,
                        **target_overrides(main),
                    ),
                    validated=True,
                ),
                attacker.participant_id,
                "main",
                champion_wounds=wounds,
                amps=AmpRiders(
                    _live_amps_of(attacker, main, params),
                    _holder_amps_of(attacker, main, params),
                ),
            )
            pair_result_cache[cache_key] = view
        attacker_i = context.index_of[attacker.participant_id]
        # This main-pair fight carries the attacker's kept actor-wide heal
        # copies; the ally-pair copies are suppressed in the base panel.  The
        # dedup map is a per-signature copy: a sig build may never grow the
        # shared base sets, or a key recorded by one signature would silently
        # drop another signature's only copy.
        sig.add_engine_result(
            PairFight(
                view.engine,
                attacker.participant_id,
                "main",
                champion_wounds=wounds,
                amps=view.amps,
            ),
            WalkSlots(
                attacker_i,
                0,
                context.grievous_packs[attacker_i],
                duration,
                dict(context.base_heal_dedup.get(attacker_i) or {}),
                context.panel_id_strings[(attacker.participant_id, "main")],
            ),
        )
        sig.add_support_templates(
            _attached_support_templates(
                view,
                attacker,
                all_actors,
                # The signature panel prices every enemy attacker against the
                # candidate main and nobody else (the ``"main"`` defender
                # above), so the pair this result came from is that one.
                pair_defender_id=main.participant_id,
                damage_events=view.events,
            ),
            attacker_i,
            context.index_of,
        )
    # The enemy->main fights live here rather than on the base panel, so the
    # Sacrifice split for a holder whose Worthy ally IS the candidate main
    # has to be staged against this panel's actions.
    sig_children: dict[int, SurvivalAction] = {}
    sig_aidx = sig.next_aidx
    for kv_holder in context.roster_actors:
        kv_tether = resolve_knights_vow_tether(kv_holder, all_actors)
        if kv_tether is None or kv_tether["target"].participant_id != "main":
            continue
        sig_aidx = stage_knights_vow_redirect_actions(
            sig, all_actors, kv_tether, sig_children, next_aidx=sig_aidx
        )
    sig.next_aidx = sig_aidx
    return _SignaturePanel(context.base_sorted, sig, kv_redirect_children=sig_children)


def _score_with_search_context(
    champion_data: dict[str, Any],
    level: int,
    items: list[dict[str, Any]],
    params: FightParams,
    *,
    main_stats: dict[str, float],
    main_defenses: StartingDefenses,
    enemies: list[ResolvedLoadout],
    allies: list[ResolvedLoadout],
    pair_result_cache: dict[PairCacheKey, PairView],
    context: CoupledSearchContext,
    reuse_main_stats: bool,
    published: bool,
) -> dict[str, Any]:
    """Score one candidate through the compiled panel walk.

    Returns the exact score-only receipt ``build_participant_timeline``
    would produce — same fields, same rounding, same float-addition order,
    and the same rounded death-time cutoff on each attacker's outgoing
    total — while compiling only the main champion's fresh outgoing
    fights.
    """
    # A search-invariant compilation failure (roster pair or signature
    # panel) poisons the context; every later evaluation raises immediately
    # instead of re-attempting the compiled path.
    if context.uncompilable:
        raise UncompilableActionError(
            receipt=_CONTEXT_POISONED_RECEIPT,
            source=str(champion_data.get("name", "")),
        )
    # The main candidate's own loadout is candidate-dependent: a failure
    # here falls back per evaluation and never poisons the context.  Checked
    # before any pair fight so the fallback costs only the capability scan.
    main_item_receipt = uncompilable_item_receipt(items)
    if main_item_receipt is not None:
        raise UncompilableActionError(
            receipt=f"main:{main_item_receipt}",
            source=str(champion_data.get("name", "")),
        )
    if context.roster_actors is None:
        setup_allies = _roster_actors(allies, "ally")
        setup_enemies = _roster_actors(enemies, "enemy")
        placeholder = Combatant(
            participant_id="main",
            team="main",
            champion_data=champion_data,
            level=level,
            items=tuple(items),
            stats=main_stats,
            defenses=main_defenses,
        )
        try:
            _context_setup(
                context,
                params,
                enemies,
                allies,
                champion_name=str(champion_data.get("name", "")),
                level=level,
                pair_result_cache=pair_result_cache,
                all_actors_by_index=[placeholder, *setup_allies, *setup_enemies],
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
    signature = defensive_signature(main)
    panel = context.panels.get(signature)
    # Which of the two compiled rungs this evaluation takes, decided where
    # the difference between them actually happens.  ``CompiledFull`` is the
    # evaluation that had to *build* this defensive signature's panel — it
    # compiled the roster's actions rather than cloning a cached set — and
    # every later evaluation on the same signature is ``CompiledFast``.  The
    # two share one published label, so this split moves no counter; what it
    # buys is that the residual has a decision to name when panel
    # reuse stops happening, instead of a histogram still reading 100%
    # compiled.
    compiled_rung = CompiledFast() if panel is not None else CompiledFull()
    if panel is None:
        try:
            panel = _build_signature_panel(
                context,
                main,
                params,
                pair_result_cache,
                signature=signature,
                all_actors=all_actors,
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
        main_champion_wounds = _champion_wounds_of(main.champion_data)
        context.main_champion_wounds = main_champion_wounds
    reusable_stats = main.stats if reuse_main_stats else None
    heal_dedup: dict[tuple[str, float], float] = {}
    first_result = None
    # The defender ``first_result`` was priced against, captured beside it
    # in the loop that produces it, so nothing has to index back into
    # ``context.main_pair_params`` from a branch far from the loop.
    first_defender: Combatant | None = None
    enemy_actors = [actor for actor in roster if actor.team == "enemy"]
    for defender_index, (defender, pair_params) in enumerate(context.main_pair_params):
        result = _pair_run_fight(
            context.work_counters,
            main.champion_data,
            main.level,
            list(main.items),
            params=pair_params,
            precomputed_stats=reusable_stats,
            validated=True,
            score_only=True,
        )
        if first_result is None:
            first_result = result
            first_defender = defender
        # The compiler derives its own delivery facts; this stamps them onto
        # the ledger the *item support scan* below reads, which is the one
        # consumer of this result that is not the compiler.
        _stamp_ability_instances(result)
        fresh.add_engine_result(
            PairFight(
                result,
                "main",
                defender.participant_id,
                defender_index,
                champion_wounds=main_champion_wounds,
                amps=AmpRiders(
                    _live_amps_of(main, defender, params),
                    _holder_amps_of(main, defender, params),
                ),
            ),
            WalkSlots(
                0,
                context.index_of[defender.participant_id],
                main_packs,
                duration,
                heal_dedup,
                context.pair_id_strings[defender.participant_id],
            ),
        )
    if first_result is not None and first_defender is not None:
        # The item support scan reads per-event target/id fields that only
        # pair enrichment adds (Black Cleaver Carve, Bloodsong), plus the
        # first pair's takedown synthesis.  Give it the same view the
        # receipt composition passes: a template it authors either compiles
        # or fails closed, never silently vanishes.
        # ``enriched_view_items()`` is the projection of which holders
        # declare one of those two fields in ``needs``, so the copy is made
        # for a holder that reads it and for nobody else.
        if first_result.get("damage_events_tuple") or not holders_in(
            main.items, enriched_view_items()
        ):
            # Tuple-ledger fights carry no scannable rows by construction,
            # and a holder with no event-view item never reads the enriched
            # per-event copy — both scan the plain engine result.
            support_templates = _support_effect_templates(
                main,
                first_result,
                all_actors,
                pair_defender_id=first_defender.participant_id,
            )
        else:
            first_defender_id = first_defender.participant_id
            # The same preview skip the compiler makes, on the same rows, so
            # the scan and the walk see one stream.  A pair-engine row the
            # registry declares THEORETICAL is a preview of a number the
            # coupled walk owns, and a preview row IS a damage event:
            # Carve arms one stack per damage event, so scanning it armed an
            # eleventh stack the walk never armed.
            #
            # ``continue`` rather than a filtered comprehension, exactly as
            # in the compiler: ``index`` is the per-pair event id and
            # re-numbering the survivors would move every id after the first
            # preview.
            scan_previewed = dropped_pair_previews(first_result.get("breakdown") or {})
            support_scan_events = []
            for index, event in enumerate(first_result.get("damage_events", [])):
                if str(event.get("source_key", "")) in scan_previewed:
                    continue
                support_scan_events.append(
                    {
                        **event,
                        "target": first_defender_id,
                        "_event_id": f"main:{first_defender_id}:{index}",
                    }
                )
            support_templates = _support_effect_templates(
                main,
                first_result,
                all_actors,
                pair_defender_id=first_defender_id,
                damage_events=support_scan_events,
                target_id=first_defender_id,
            )
        fresh.add_support_templates(support_templates, 0, context.index_of)
    # Thorns from this candidate's fresh strikes (enemy holders), then the
    # candidate's own thorns items struck by the invariant roster autos.
    for defender in enemy_actors:
        holder_i = context.index_of[defender.participant_id]
        profiles = context.thorns_profiles[holder_i]
        if not profiles:
            continue
        strikes = [
            (aidx, time_value, sequence, main, 0)
            for aidx, time_value, sequence, _striker_i in (
                fresh.auto_strikes_into.get(holder_i, ())
            )
        ]
        if strikes:
            fresh.add_thorns(
                defender,
                holder_i,
                strikes,
                profiles,
                grievous_by_dtype=context.grievous_packs[holder_i],
                duration=duration,
                id_namespace="fresh",
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
                main,
                0,
                strikes,
                main_thorns,
                grievous_by_dtype=main_packs,
                duration=duration,
                id_namespace="fresh",
            )

    # Grey-health consume heals (E8a) are compiled from the same incoming
    # (enemy -> main, plus enemy thorns) and outgoing (main) damage actions
    # the walk applies, with the candidate's own stats/ranks, so the
    # compiled score walk matches the ordered receipt's fixed amounts.
    grey_summary: dict[str, float | str] = {}
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
        grey_heals, grey_shields, grey_summary = _grey_health_receipts(
            str(champion_data.get("name", "")),
            champion_data,
            level,
            main.stats,
            incoming=in_records,
            outgoing=out_records,
            cast_timeline=main_cast_timeline,
            duration=duration,
            enemy_count=len(enemy_actors),
            ability_ranks=params.ability_ranks,
            champion_options=params.champion_options,
        )
        for index, (heal_time, source, amount) in enumerate(grey_heals):
            aidx = fresh.next_aidx
            fresh.next_aidx += 1
            fresh.actions.append(
                grey_health_heal_action(heal_time, source, amount, index, aidx=aidx)
            )
        for index, (grant_time, source, amount, window) in enumerate(grey_shields):
            aidx = fresh.next_aidx
            fresh.next_aidx += 1
            fresh.actions.append(
                grey_health_shield_action(
                    grant_time, source, amount, window, index=index, aidx=aidx
                )
            )

    # An armed damage modifier restricts itself by attack class, and the
    # engine's light tuple ledger carries no per-packet delivery metadata to
    # evaluate that against.  The two halves can land in different compilers
    # — an ally's curse in the invariant panel, the packets it amplifies in
    # the candidate's own fresh result — so the question is asked of the
    # assembled set, once, here (H5).
    delivery_receipt = modifier_delivery_receipt(
        (fresh, context.base_compiler, panel.sig)
    )
    if delivery_receipt is not None:
        raise UncompilableActionError(
            receipt=delivery_receipt, source="damage_modifier"
        )
    # Knight's Vow (P3 package 3S): the candidate main's own outgoing packets
    # are compiled fresh each evaluation, so a holder whose Worthy ally is
    # the main stages its Sacrifice holder-heals here (the redirect onto the
    # main's incoming damage lives in the signature panel).
    kv_fresh_aidx = fresh.next_aidx
    for kv_holder in all_actors:
        kv_tether = resolve_knights_vow_tether(kv_holder, all_actors)
        if kv_tether is None or kv_tether["target"].participant_id != "main":
            continue
        kv_fresh_aidx = stage_knights_vow_heals(
            fresh, all_actors, kv_tether, kv_fresh_aidx
        )
    fresh.next_aidx = kv_fresh_aidx

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
    # The score adapter arms the same canonical state dicts as the receipt
    # walk and drives the identical kernel; the only difference is the
    # ledger's parallel-array observation below.
    states = build_states(all_actors, _below_half_healing_bonuses(all_actors))
    # The kernel authors Maw's post-Lifeline omnivamp heals mid-walk through
    # ``ledger.schedule_heal``, which needs the same three injections the
    # receipt ledger takes; without them the score path could not stage the
    # mechanic at all.  One compiler for both adapters, so a heal the receipt
    # walk schedules is a heal the score walk schedules.
    ledger = ScoreLedger(
        n_actions,
        actions=actions,
        index_of=context.index_of,
        compile_event=action_from_event,
    )
    # One producer for both adapters: the score walk reads the same walk-lane
    # interpreter the receipt walk does, so a venom that moved would move in
    # both or in neither.  Two reads of two different producers is how a score
    # and a receipt come to disagree about one declaration.
    venom_packs = [_venom_profile(actor, duration) for actor in all_actors]
    ctx = TransitionContext(
        duration=duration,
        states=states,
        combatants=all_actors,
        index_of=context.index_of,
        ledger=ledger,
        regeneration_windows=_regeneration_windows(all_actors),
        plating_windows=_plating_windows(all_actors),
        venom_profiles=venom_packs,
        # Both panels may have split a parent damage action; the kernel
        # cancels a child beside its parent, so it needs every split this
        # evaluation is walking, keyed by the parent's event slot.
        redirect_children={
            **context.kv_redirect_children,
            **panel.kv_redirect_children,
        },
    )
    base = context.base_compiler
    coverage_reports = fresh.coverage + base.coverage + panel.sig.coverage
    program = roster_program(all_actors)
    walk_result = walk(
        actions, ctx, counters=context.work_counters, rung=compiled_rung
    ).projected(
        grey_health=grey_summary or None,
        timeline_coverage=combine_timeline_coverages(
            coverage_reports,
            target_count=len(coverage_reports),
        ),
    )
    # The compiled rungs are recorded here rather than by the caller because
    # this is the only frame that knows *which* of the two it took, and the
    # decision rides on the walk result that priced the evaluation rather
    # than being spelled a second time beside it.  The caller records the
    # fallback rungs, which are the ones it knows: one rung per evaluation
    # either way, because a return from here and an exception out of here
    # are exclusive.
    record_rung(context.work_counters, *counter_entry(walk_result.rung))
    # ``DISCARD``: these rows are the composition's own working copy.  The
    # score view re-projects them for the payload it returns and the receipt
    # view for the one it returns; recording a third map here would be a
    # map describing rows nobody serializes, on the optimizer's hot path.
    rows_by_id = _survival_view.survival_leaves(
        program, walk_result, DISCARD, _survival_view.participant_paths(program)
    )
    survival_rows = [rows_by_id[actor.participant_id] for actor in all_actors]
    applied = ledger.applied

    count = len(all_actors)
    support_value, healing_output = accumulate_support_values(
        applied,
        fresh.support_entries,
        base.support_entries,
        panel.sig.support_entries,
        count=count,
    )
    totals = accumulate_damage_totals(
        survival_rows,
        applied,
        sig_damage_order=panel.sig.damage_order,
        base_damage_order=base.damage_order,
        fresh_damage_order=fresh.damage_order,
        fresh_thorns_order=fresh.thorns_order,
        base_thorns_order=base.thorns_order,
        count=count,
    )
    # Per-attacker float-sum order replays the receipt composition's
    # outgoing list: pair fights in defender order (enemies hit the main
    # first, then allies), then thorns in strike order (fresh strikes precede
    # the roster's).  One running total over the ordered parts keeps the
    # exact same addition sequence without building a concat list.  A dead
    # attacker's total is cut against its ROUNDED death time: the walk
    # applies an attacker's own event at the exact death instant, and the sum
    # excludes it whenever the true death time rounds down past it.
    return _score_view.score_leaves(
        program,
        walk_result.projected(
            outcomes=[
                _attacker_outcome(
                    {
                        "participant_id": actor.participant_id,
                        "team": actor.team,
                        "champion": actor.champion_data.get("name", ""),
                    },
                    totals[index],
                    survival_rows[index],
                    support_value[index],
                    healing_output[index],
                )
                for index, actor in enumerate(all_actors)
            ]
        ),
        LeafWriter() if published else DISCARD,
    )


def _attacker_outcome(
    identity: Mapping[str, Any],
    total_damage: float,
    survival_row: Mapping[str, Any],
    support_value: float,
    healing_output: float,
    *,
    sources: Sequence[Mapping[str, Any]] = (),
    utility_outcomes: Mapping[str, Any] | None = None,
) -> AttackerOutcome:
    """Fold one attacker's published numbers, once, for both paths.

    The two composition paths reach these numbers differently — the compiled
    score path off the score ledger's parallel arrays, the receipt path off
    its annotated event streams — and this is where both stop being
    ingredients and become the answer a view publishes.  ``incoming_damage``
    is summed *here* rather than in the breakdown view for exactly that
    reason: a view that adds is a view that can disagree with the walk it
    claims to project.

    ``identity`` is the published participant/team/champion triple, taken
    from whatever the caller's own breakdown row carries.  It is a parameter
    rather than a roster read because the receipt path fills those strings
    inside its attacker loop and leaves them empty for a participant who
    dealt no damage -- a preserved defect this stage may relocate but, being
    pure, may not correct.
    """
    return AttackerOutcome(
        participant_id=str(identity.get("participant_id", "")),
        team=str(identity.get("team", "")),
        champion=str(identity.get("champion", "")),
        total_damage=float(total_damage),
        incoming_damage=float(survival_row.get("health_damage", 0.0))
        + float(survival_row.get("shield_absorbed", 0.0)),
        health_damage=survival_row.get("health_damage", 0.0),
        shield_absorbed=survival_row.get("shield_absorbed", 0.0),
        effective_health=survival_row.get("effective_health", 0.0),
        healing_received=survival_row.get("healing_received", 0.0),
        healing_reduced=survival_row.get("healing_reduced", 0.0),
        support_shield_received=survival_row.get("support_shield_received", 0.0),
        support_value=float(support_value),
        healing_output=float(healing_output),
        survived_window=bool(survival_row.get("survived_window")),
        death_time=survival_row.get("death_time"),
        sources=tuple(sources),
        utility_outcomes=utility_outcomes,
    )


@dataclass(frozen=True)
class Composition:
    """Everything one roster composition is priced from.

    Fixed for the pass that reads it.  The combat-event driver in
    ``build_participant_timeline`` rebinds the whole record rather than any
    one field, so no step can read half of one pass and half of the next.
    """

    champion_data: dict[str, Any]
    level: int
    items: list[dict[str, Any]]
    params: FightParams
    main_stats: dict[str, float]
    main_defenses: StartingDefenses
    enemies: list[ResolvedLoadout]
    allies: list[ResolvedLoadout]
    focus_participant_id: str
    pair_result_cache: dict[PairCacheKey, PairView] | None
    include_receipt: bool
    reuse_main_stats: bool
    search_context: CoupledSearchContext | None
    published: bool

    @property
    def work_counters(self) -> WorkCounterSink | None:
        """The search's counter sink, or none outside a search."""
        return self.search_context.work_counters if self.search_context else None


def build_participant_timeline(
    champion_data: dict[str, Any],
    level: int,
    items: list[dict[str, Any]],
    params: FightParams,
    *,
    main_stats: dict[str, float],
    main_defenses: StartingDefenses,
    enemies: list[ResolvedLoadout],
    allies: list[ResolvedLoadout],
    focus_participant_id: str = "main",
    pair_result_cache: dict[PairCacheKey, PairView] | None = None,
    include_receipt: bool = True,
    reuse_main_stats: bool = False,
    search_context: CoupledSearchContext | None = None,
    published: bool = True,
) -> dict[str, Any]:
    """Compose all selected actors and return the coupled combat receipt.

    One composition, driven across as many passes as this roster's builds
    declare.  A build carrying a mana-spent heal declares two, because its
    restore ledger is a function of the damage the fight itself produces.

    ``focus_participant_id`` scores the selected roster member, so ally and
    enemy slot optimization needs no fake one-attacker scenario.

    ``include_receipt=False`` returns the scoring subset with identical
    numbers, for candidates whose timeline nothing displays.

    ``reuse_main_stats=True`` claims ``main_stats`` was calculated with the
    configuration a main pair fight uses (same role and item options, no
    external ally bonuses).  The roster BIS path cannot claim it.

    ``published=False`` says nobody will read the payload, so the view skips
    the ``dispositions`` map the optimizer would build and throw away.

    ``search_context`` replays one search's presorted invariant actions in
    the compiled panel walk.  Ignored outside score mode.
    """
    request = Composition(
        champion_data=champion_data,
        level=level,
        items=items,
        params=params,
        main_stats=main_stats,
        main_defenses=main_defenses,
        enemies=enemies,
        allies=allies,
        focus_participant_id=focus_participant_id,
        pair_result_cache=pair_result_cache,
        include_receipt=include_receipt,
        reuse_main_stats=reuse_main_stats,
        search_context=search_context,
        published=published,
    )

    def compose(pass_index: int, patch: ParamPatch | None) -> Any:
        """One pass of this composition, patched by its predecessor."""
        return _compose_pass(request, patch=patch, pass_index=pass_index)

    if params.combat_events is None:
        return run_passes(compose, _cross_pass_dependencies(items, enemies, allies))
    # Buff receipts determine which source casts survived the walk. A later
    # pass prices only those windows. Since buffs change future attacks, at
    # most one pass per authored cast propagates their causal consequences.
    # `compose` closes over `request` rather than binding it, because the loop
    # rebinds it: a bind taken here would freeze what the first pass saw.
    request = replace(
        request,
        params=replace(params, event_attack_speed_windows=()),
        pair_result_cache=None,
        include_receipt=True,
        search_context=None,
    )
    for _ in range(len(params.combat_events) + 2):
        receipt = run_passes(compose, _cross_pass_dependencies(items, enemies, allies))
        windows = tuple(
            AttackSpeedWindow(
                event_id=str(event["event_id"]),
                recipient_id=str(event["target"]),
                start=float(event["time"]),
                end=float(event["time"]) + float(event["duration"]),
                bonus_percent=float(event["bonus_attack_speed_percent"]),
            )
            for event in receipt.get("support_events", ())
            if str(event.get("event_id", "")).startswith("authored:")
            and float(event.get("bonus_attack_speed_percent", 0)) > 0
            and not event.get("skipped_reason")
        )
        if windows == request.params.event_attack_speed_windows:
            return receipt
        request = replace(
            request,
            params=replace(request.params, event_attack_speed_windows=windows),
        )
    raise ValueError("Authored support casts did not reach a stable causal timeline")


def _compose_pass(
    request: Composition, *, patch: ParamPatch | None, pass_index: int
) -> Any:
    """Compose the roster once, or ask for one more pass.

    Returns the finished combat receipt, or a
    :class:`~.program.dependency.PassRequest` carrying the restore ledger
    this pass derived and the next pass must be priced with.  Asking is a
    return value rather than a recursive call: a walk that can call the
    thing that called it has no single invocation to count and no single
    result for a view to project.
    """
    restores = patch.overrides[_RESOURCE_RESTORES] if patch is not None else None
    if restores is not None:
        request = replace(
            request,
            params=replace(
                request.params,
                resource_restore_events=tuple(restores.get("main", ())),
            ),
        )
    scored = _compiled_lane_pass(request, patch)
    if scored is not None:
        return scored
    roster = _compose_roster(request)
    _refuse_uncertified_casts(request.params, roster)
    ledgers = Ledgers.empty()
    _compose_pair_fights(request, roster, ledgers, restores)
    if patch is None:
        pending = _resource_restore_request(request, roster, ledgers, pass_index)
        if pending is not None:
            return pending
    _schedule_composed_events(request, roster, ledgers)
    grey_summary = _apply_grey_health(_grey_subject(request, roster), ledgers)
    walked = _walk_composition(request, roster, ledgers, grey_summary)
    if not request.include_receipt:
        # Optimizer scoring reads only the survival rows, the per-actor
        # damage breakdown, and the ordering receipt.  Skip the public
        # event/healing/support serialization for the thousands of candidate
        # evaluations that never show a timeline to anyone.  It is the *same*
        # projection the compiled score path returns, which is what makes
        # "score mode and receipt mode agree" a property of the layering
        # rather than of two assemblies kept in step by hand.
        return _score_view.score_leaves(
            walked.program,
            walked.result,
            LeafWriter() if request.published else DISCARD,
        )
    return _compose_receipt(request.focus_participant_id, roster, ledgers, walked)


def _grey_subject(request: Composition, roster: Roster) -> GreySubject:
    """The grey-health subject this pass's main champion is."""
    return GreySubject(
        str(request.champion_data.get("name", "")),
        request.champion_data,
        request.level,
        request.main_stats,
        request.params,
        len(roster.enemy_actors),
    )


def _compiled_lane_pass(request: Composition, patch: ParamPatch | None) -> Any | None:
    """This pass's compiled panel score, or ``None`` to price the walk.

    Every fall-through records its own rung and the compiled lane records
    its own, so the four-state histogram accounts for 100% of evaluations.
    """
    work_counters = request.work_counters
    if _compiled_lane_is_open(request, patch):
        try:
            scored = _score_with_search_context(
                request.champion_data,
                request.level,
                request.items,
                request.params,
                main_stats=request.main_stats,
                main_defenses=request.main_defenses,
                enemies=request.enemies,
                allies=request.allies,
                pair_result_cache=request.pair_result_cache,
                context=request.search_context,
                reuse_main_stats=request.reuse_main_stats,
                published=request.published,
            )
        except UncompilableActionError as exc:
            # A transition the score kernel cannot represent must never be
            # silently dropped.  Mark search-invariant failures so later
            # evaluations skip the compiled path; candidate-local failures
            # fall back per evaluation.
            if exc.invariant:
                request.search_context.uncompilable = True
            # The rung is a *decision* with a reason, and the published
            # histogram key is only its label.  ``counter_entry`` hands the
            # sink both, so the reason the exception carried reaches a reader
            # instead of stopping at this frame: ``rung_receipts`` is keyed
            # by the declaration that refused, and its total is the fallback
            # count.  Recording the label alone is what left the reason
            # travelling exactly one expression, until the sink grew the
            # field to carry it.
            decision = (
                SearchPoisoned(exc.receipt)
                if exc.invariant or exc.receipt == _CONTEXT_POISONED_RECEIPT
                else ReceiptWalk(exc.receipt, FallbackScope.CANDIDATE)
            )
            record_rung(work_counters, *counter_entry(decision))
        else:
            # No rung recorded here: ``_score_with_search_context`` already
            # recorded the compiled one it took, which is the only frame
            # that can tell ``CompiledFast`` from ``CompiledFull``.
            return scored
    elif patch is None:
        # One rung per evaluation, recorded by that evaluation's first pass.
        # A later pass is the same evaluation priced again, not a second
        # one, so recording its gate refusal would enter one evaluation in
        # the four-state histogram twice and break the property that the
        # histogram accounts for 100% of evaluations.
        # ``gate_rung`` rather than the ``ReceiptWalk(..., REQUEST_GATE)`` it
        # returns: the builder exists for exactly this decision, and spelling
        # it out here would be the second spelling of one decision that the
        # bridge in ``program/rung`` exists to prevent.
        record_rung(work_counters, *counter_entry(gate_rung(_GATE_REFUSAL_RECEIPT)))
    return None


def _compose_roster(request: Composition) -> Roster:
    """The main champion and both teams, composed once for this pass."""
    main = main_combatant(
        request.champion_data,
        request.level,
        request.items,
        stats=request.main_stats,
        defenses=request.main_defenses,
        params=request.params,
    )
    enemy_actors = _roster_actors(request.enemies, "enemy")
    enemy_attackers = [actor for actor in enemy_actors if not actor.is_practice_dummy]
    ally_actors = _roster_actors(request.allies, "ally")
    return Roster(
        main,
        ally_actors,
        enemy_actors,
        enemy_attackers,
        [main, *ally_actors, *enemy_actors],
    )


def _refuse_uncertified_casts(params: FightParams, roster: Roster) -> None:
    """Refuse an authored cast this roster cannot certify."""
    if params.combat_events is None:
        return
    actors_by_id = {actor.participant_id: actor for actor in roster.all_actors}
    for event in params.combat_events:
        if (
            event.caster_id not in actors_by_id
            or event.recipient_id not in actors_by_id
        ):
            raise ValueError(
                f"Cast {event.id}: caster and recipient must exist in the roster"
            )
        caster, recipient = (
            actors_by_id[event.caster_id],
            actors_by_id[event.recipient_id],
        )
        if caster.is_practice_dummy or (
            caster.team == "enemy" and not params.enemies_attack
        ):
            raise ValueError(f"Cast {event.id}: this caster cannot act")
        friendly = (caster.team == "enemy") == (recipient.team == "enemy")
        recipient_kind = (
            "self"
            if recipient.participant_id == caster.participant_id
            else "ally" if friendly else "enemy"
        )
        allowed = certified_recipients(caster.champion_data["name"], event.slot)
        if allowed is None or recipient_kind not in allowed:
            raise ValueError(
                f"Cast {event.id}: {caster.champion_data['name']} {event.slot} "
                f"cannot name {recipient_kind!r} as its recipient; certified "
                f"recipients: {list(allowed or ())}"
            )
        if (
            caster.team == "ally"
            and friendly
            and not caster.request.ally_effects_enabled
        ):
            raise ValueError(f"Cast {event.id}: enable ally effects for this caster")


class _Pair(NamedTuple):
    """One attacker against one defender, at its index in that roster.

    ``cacheable`` is the roster-to-roster half: those fights do not depend on
    the candidate main build at all, while fights the candidate attacks with
    are always recomputed.
    """

    attacker: Combatant
    defender: Combatant
    defender_index: int
    defender_count: int
    actor_params: FightParams

    @property
    def cacheable(self) -> bool:
        """Whether this pair's view can serve a later candidate evaluation."""
        return self.attacker.participant_id != "main"


class _PairCtx(NamedTuple):
    """What one pair fold reads and writes.

    The three sets are the one-activation bookkeeping carried across pairs:
    an ``actor_wide`` self-shield payload is authored once per rotation but
    replayed by every enemy pair, and one attacker's support templates are
    attached by whichever pair reaches them first.
    """

    request: Composition
    roster: Roster
    ledgers: Ledgers
    ordered_item_support_ids: set[str]
    actor_wide_shield_keys: set[tuple[str, str, float]]
    support_attached: set[str]

    @classmethod
    def over(cls, request: Composition, roster: Roster, ledgers: Ledgers) -> _PairCtx:
        """One pass's pair context, with empty bookkeeping."""
        return cls(request, roster, ledgers, set(), set(), set())


def _compose_pair_fights(
    request: Composition,
    roster: Roster,
    ledgers: Ledgers,
    restores: Mapping[str, tuple[tuple[float, float], ...]] | None,
) -> None:
    """Run every pair fight this roster composes and fold it into the books.

    A support source still has a cast schedule when no opposing target was
    selected (a main champion with allies but an empty enemy roster, say).
    The tail resolves that schedule once, so ally and enemy support packets
    are not dropped merely because the pairwise damage loop had no row.
    """
    params = request.params
    ctx = _PairCtx.over(request, roster, ledgers)
    teams = {
        "main": [roster.main],
        "ally": roster.ally_actors,
        "enemy": roster.enemy_attackers,
    }
    attack_groups = (
        ("main", [*roster.enemy_actors]),
        ("ally", [*roster.enemy_actors]),
        # The Enemy Hits constraint: with enemies_attack off, the enemy team
        # gets no defenders, so none of its pair fights are ever composed.
        ("enemy", [roster.main, *roster.ally_actors] if params.enemies_attack else []),
    )
    for attacker_team, defenders in attack_groups:
        for attacker in teams[attacker_team]:
            if not defenders:
                continue
            actor_params = actor_params_with_resource_restores(
                params, attacker, restores
            )
            for defender_index, defender in enumerate(defenders):
                pair = _Pair(
                    attacker, defender, defender_index, len(defenders), actor_params
                )
                _fold_pair_view(ctx, pair, _pair_fight_view(ctx, pair))
    for attacker in roster.all_actors:
        if attacker.is_practice_dummy:
            ctx.support_attached.add(attacker.participant_id)
            continue
        if attacker.participant_id in ctx.support_attached:
            continue
        fallback = _pair_run_fight(
            request.work_counters,
            attacker.champion_data,
            attacker.level,
            list(attacker.items),
            params=actor_params_with_resource_restores(params, attacker, restores),
        )
        _attach_support_effects(
            attacker,
            fallback,
            roster.all_actors,
            ledgers.support_effects,
            outgoing=ledgers.outgoing,
            incoming=ledgers.incoming,
            denial_receipts=ledgers.item_denial_receipts,
        )
        ctx.support_attached.add(attacker.participant_id)


def _pair_fight_view(ctx: _PairCtx, pair: _Pair) -> PairView:
    """One pair fight's view, served from the cache when it cannot differ.

    The coupled optimizer evaluates thousands of main candidates against one
    fixed roster, so pair fights that cannot differ between evaluations are
    cached.  A fight INTO the main candidate depends on it only through the
    target fields ``target_overrides`` feeds the engine, so its cache key
    carries that defensive signature: a candidate swap that changes no
    defensive stat replays the identical incoming fights.
    """
    request = ctx.request
    # Secondary-target item branches are allocated against the current
    # attacker group, not the outer request's default single-target fields.
    # The ordered roster index is explicit and deterministic: index 0 is the
    # primary defender and later indices are eligible secondary recipients.
    pair_params = replace(
        pair.actor_params,
        roster_target_index=pair.defender_index,
        roster_target_count=pair.defender_count,
    )
    cache = request.pair_result_cache if pair.cacheable else None
    cache_key = _pair_cache_key(
        pair.attacker.participant_id,
        pair.defender.participant_id,
        (
            defensive_signature(pair.defender)
            if pair.defender.participant_id == "main"
            else ()
        ),
        # Read off the params this fight is actually priced with, never off
        # the pass number: a key derived from the same object the pricer
        # reads cannot disagree with it.
        pair.actor_params.resource_restore_events,
    )
    cached = cache.get(cache_key) if cache is not None else None
    if cached is not None:
        return cached
    view = pair_view(
        _pair_run_fight(
            request.work_counters,
            pair.attacker.champion_data,
            pair.attacker.level,
            list(pair.attacker.items),
            params=target_params(pair_params, pair.defender),
            precomputed_stats=(
                pair.attacker.stats
                if request.reuse_main_stats and pair.attacker.participant_id == "main"
                else None
            ),
        ),
        pair.attacker.participant_id,
        pair.defender.participant_id,
        pair.defender_index,
        champion_wounds=_champion_wounds_of(pair.attacker.champion_data),
        amps=AmpRiders(
            _live_amps_of(pair.attacker, pair.defender, request.params),
            _holder_amps_of(pair.attacker, pair.defender, request.params),
        ),
    )
    if cache is not None:
        cache[cache_key] = view
    if pair.attacker.participant_id == "main" and not ctx.ledgers.main_cast_timeline:
        ctx.ledgers.main_cast_timeline.extend(view.result.get("cast_timeline", []))
    return view


def _fold_pair_view(ctx: _PairCtx, pair: _Pair, view: PairView) -> None:
    """Fold one pair view's events, heals and support packets into the books."""
    ledgers, result = ctx.ledgers, view.result
    ledgers.coverage_reports.append(result.get("timeline_coverage", {}))
    # A view that lives in the cache serves later evaluations, so this one
    # only takes copies (the walk mutates its rows).  A single-use fight's
    # rows are appended directly.
    copy_templates = pair.cacheable and ctx.request.pair_result_cache is not None
    attacker_outgoing = ledgers.outgoing[pair.attacker.participant_id]
    defender_incoming = ledgers.incoming[pair.defender.participant_id]
    for template in view.events:
        enriched = dict(template) if copy_templates else template
        attacker_outgoing.append(enriched)
        defender_incoming.append(enriched)
        _fold_self_shield(ctx, pair.attacker, enriched)
    attacker_healing = ledgers.healing[pair.attacker.participant_id]
    for template in view.heals:
        if template.get("actor_wide"):
            duplicate = any(
                existing.get("actor_wide")
                and existing.get("source") == template.get("source")
                and float(existing.get("time", 0.0)) == float(template.get("time", 0.0))
                for existing in attacker_healing
            )
            if duplicate:
                continue
        attacker_healing.append(dict(template) if copy_templates else template)
    if pair.attacker.participant_id not in ctx.support_attached:
        support_templates = _attached_support_templates(
            view,
            pair.attacker,
            ctx.roster.all_actors,
            pair_defender_id=pair.defender.participant_id,
            damage_events=view.events,
            target_id=pair.defender.participant_id,
            denial_receipts=ledgers.item_denial_receipts,
        )
        for template in support_templates:
            packet_template = dict(template) if copy_templates else template
            ledgers.support_effects[template["target"]].append(packet_template)
            if template.get("kind") == "damage":
                ledgers.outgoing[template["attacker"]].append(packet_template)
                ledgers.incoming[template["target"]].append(packet_template)
        ctx.support_attached.add(pair.attacker.participant_id)
    row = ledgers.breakdown[pair.attacker.participant_id]
    row.update(
        {
            "participant_id": pair.attacker.participant_id,
            "team": pair.attacker.team,
            "champion": pair.attacker.champion_data.get("name", ""),
        }
    )
    row["total_damage"] += float(result.get("total_damage", 0.0))
    if ctx.request.include_receipt:
        row_sources = row["sources"]
        for source, template in view.source_names.items():
            row_sources.setdefault(source, template)


def _fold_self_shield(
    ctx: _PairCtx, attacker: Combatant, enriched: MutableMapping[str, Any]
) -> None:
    """Author the self-shield one damage packet carries, once per activation.

    An ``actor_wide`` payload is authored once per rotation but replayed by
    every enemy pair, so the first pair to carry it keeps it and the rest
    are dropped.  Keyed the way actor-wide heals are keyed: holder, source,
    timestamp.
    """
    shield_payload = enriched.get("self_shield")
    shield_event_id = str(enriched.get("_event_id", ""))
    if not isinstance(shield_payload, Mapping) or not shield_event_id:
        return
    shield_key = (
        (
            attacker.participant_id,
            str(shield_payload.get("source", "")),
            float(enriched.get("time", 0.0) or 0.0),
        )
        if shield_payload.get("actor_wide")
        else None
    )
    if (
        shield_event_id in ctx.ordered_item_support_ids
        or shield_key in ctx.actor_wide_shield_keys
    ):
        return
    try:
        shield_amount = max(0.0, float(shield_payload["amount"]))
        shield_duration = max(0.0, float(shield_payload["duration"]))
    except (KeyError, TypeError, ValueError):
        # An incomplete parser receipt cannot be turned into a guessed
        # defensive event.
        ctx.ledgers.item_denial_receipts.append(
            {
                "time": round(float(enriched.get("time", 0.0) or 0.0), 3),
                "kind": PacketKind.ITEM_DENIAL.value,
                "source": str(
                    shield_payload.get("source", "Eclipse (Ever Rising Moon)")
                ),
                "reason": "self_shield_payload_unreadable",
                "attacker": attacker.participant_id,
                "target": attacker.participant_id,
                "event_id": shield_event_id,
            }
        )
        return
    if shield_amount <= 0.0 or shield_duration <= 0.0:
        return
    ctx.ledgers.support_effects[attacker.participant_id].append(
        {
            "time": float(enriched.get("time", 0.0)),
            "kind": "shield",
            "amount": shield_amount,
            "duration": shield_duration,
            "source": str(shield_payload.get("source", "Eclipse (Ever Rising Moon)")),
            "source_key": "shield_Eclipse",
            "attacker": attacker.participant_id,
            "target": attacker.participant_id,
            "target_scope": "self",
            "target_policy": "self",
            "_event_id": f"{shield_event_id}:shield",
            "_trigger_event_id": shield_event_id,
            # This row is a *rider*: it was bound to one already-chosen
            # carrier packet (the ordinal-aligned event
            # ``fight.ledger.event_rows._damage_event_row`` copied the
            # payload onto), before the walk knew which packets land.  The
            # marker is what ``_self_shield_carrier_denials`` reads to audit
            # that binding; see D-VI-1.
            "_self_shield_rider": True,
            # Whether the payload's own trigger lets the walk move that
            # binding to the first ability packet the holder lands.
            "_rebind_on_ability_hit": bool(shield_payload.get("rebind_on_ability_hit")),
            # A barrier the triggering damage placed: it arms after that
            # damage, not before.
            SUPPORT_RANK_KEY: TransitionRank.LATE_BARRIER,
        }
    )
    ctx.ordered_item_support_ids.add(shield_event_id)
    if shield_key is not None:
        ctx.actor_wide_shield_keys.add(shield_key)


def _resource_restore_request(
    request: Composition, roster: Roster, ledgers: Ledgers, pass_index: int
) -> PassRequest | None:
    """The restore ledger a second pass must price, when one is declared.

    A mana-spent heal's restore is the one sustain branch whose state
    changes future ability admission.  This pass supplies the complete
    incoming champion ledger; the next one prices the same fights with those
    exact (time, pre-mitigation-damage x declared ratio) restores attached
    to each holder that declares the shape.  Asking is a return value: the
    driver rebuilds the composition with the patch, so the two passes are
    siblings rather than a call inside a call.
    """
    resource_restores: dict[str, tuple[tuple[float, float], ...]] = {}
    for actor in roster.all_actors:
        restores, complete = _declared_resource_restores(
            actor, ledgers.incoming, request.params.fight_duration_seconds
        )
        if not complete:
            raise incomplete_dependency(
                _cross_pass_dependency(mana_spent_heal_slot(actor.items)),
                pass_index,
                detail=(
                    f"the restore ledger is unavailable for "
                    f"{actor.participant_id}: an incoming champion packet "
                    "does not expose finite pre-mitigation damage"
                ),
            )
        if restores:
            resource_restores[actor.participant_id] = restores
    if not resource_restores:
        return None
    requester = next(
        actor
        for actor in roster.all_actors
        if actor.participant_id in resource_restores
    )
    return PassRequest(
        _cross_pass_dependency(mana_spent_heal_slot(requester.items)),
        resource_restores,
    )


def _schedule_composed_events(
    request: Composition, roster: Roster, ledgers: Ledgers
) -> None:
    """Author every cross-pair event the composed books now support.

    Knight's Vow is the one ally packet whose trigger lives on the
    recipient's incoming/outgoing ledgers rather than on a heal/shield cast.
    Its single explicit Worthy tether resolves after all pair events exist,
    so the redirect and holder-heal receipts share one event order.
    """
    schedule_knights_vow(
        roster.all_actors, ledgers.incoming, ledgers.outgoing, ledgers.support_effects
    )
    scene = ledgers.scene(roster.all_actors)
    _coalesce_darius_q_heals(ledgers.healing)
    _schedule_thorns_events(scene)
    _schedule_authored_reactive_events(ledgers.incoming, ledgers.outgoing)
    keystone_name = str(getattr(request.params, "keystone", "") or "")
    _schedule_guardian_events(scene, keystone_name=keystone_name)
    _schedule_aftershock_events(scene, keystone_name=keystone_name)
    _schedule_glacial_events(scene, keystone_name=keystone_name)
    _schedule_stormraider_events(scene, keystone_name=keystone_name)
    _schedule_grasp_events(scene, keystone_name=keystone_name)
    if request.params.enemies_attack:
        return
    # The Enemy Hits constraint promises exactly zero enemy damage. Enemy
    # pair fights were never composed above; this sweep also drops every
    # event an enemy authors reactively off our own strikes: thorns
    # strike-backs, authored reactive packets, redirect retaliation.
    enemy_ids = {actor.participant_id for actor in roster.enemy_actors}
    for ledger in (ledgers.incoming, ledgers.outgoing):
        for participant_id, events in list(ledger.items()):
            ledger[participant_id] = [
                event
                for event in events
                if str(event.get("attacker", "")) not in enemy_ids
            ]


def _walk_composition(
    request: Composition,
    roster: Roster,
    ledgers: Ledgers,
    grey_summary: Mapping[str, float | str],
) -> Walked:
    """Walk the composed books and fold every attacker's published totals."""
    program = roster_program(roster.all_actors, focus=request.focus_participant_id)
    include_receipt = request.include_receipt
    walk_result = _simulate_survival(
        roster.all_actors,
        ledgers.incoming,
        ledgers.healing,
        ledgers.support_effects,
        request.params.fight_duration_seconds,
        annotate=include_receipt,
        receipt_events=ledgers.outgoing if include_receipt else None,
        work_counters=request.work_counters,
    ).projected(
        grey_health=grey_summary or None,
        timeline_coverage=combine_timeline_coverages(
            ledgers.coverage_reports,
            target_count=len(ledgers.coverage_reports),
        ),
    )
    survival = _survival_view.survival_leaves(
        program, walk_result, DISCARD, _survival_view.participant_paths(program)
    )
    # An actor's damage after their death is not part of team-fight value.
    for actor in roster.all_actors:
        death_time = survival[actor.participant_id]["death_time"]
        cutoff = (
            request.params.fight_duration_seconds if death_time is None else death_time
        )
        events = [
            event
            for event in ledgers.outgoing[actor.participant_id]
            if float(event.get("time", 0.0)) <= cutoff
        ]
        row = ledgers.breakdown[actor.participant_id]
        row["total_damage"] = round(
            sum(float(event.get("damage", 0.0)) for event in events), 1
        )
        if not include_receipt:
            # The scoring subset carries damage totals, not per-source rows.
            row["sources"] = {}
            continue
        source_totals: dict[str, float] = defaultdict(float)
        for event in events:
            source_totals[str(event.get("source_key", ""))] += float(
                event.get("damage", 0.0)
            )
        row["sources"] = {
            source: {
                "name": row["sources"].get(source, {}).get("name", source),
                "total_damage": round(total, 1),
            }
            for source, total in source_totals.items()
            if total > 0
        }

    utility_by_actor = {
        actor.participant_id: _utility_outcome_receipt(
            actor,
            ledgers.support_effects.get(actor.participant_id, []),
            ledgers.outgoing.get(actor.participant_id, []),
        )
        for actor in roster.all_actors
    }
    support_by_attacker: dict[str, float] = defaultdict(float)
    healing_by_attacker: dict[str, float] = defaultdict(float)
    for events in ledgers.support_effects.values():
        for event in events:
            attacker_id = str(event.get("attacker", ""))
            applied = float(event.get("applied_amount", 0.0))
            if event.get("kind") == "damage":
                continue
            support_by_attacker[attacker_id] += applied
            if event.get("kind") == "heal":
                healing_by_attacker[attacker_id] += applied
    walk_result = walk_result.projected(
        outcomes=[
            _attacker_outcome(
                ledgers.breakdown.get(actor.participant_id)
                or {
                    "participant_id": actor.participant_id,
                    "team": actor.team,
                    "champion": actor.champion_data.get("name", ""),
                },
                float(
                    (ledgers.breakdown.get(actor.participant_id) or {}).get(
                        "total_damage", 0.0
                    )
                ),
                survival[actor.participant_id],
                support_by_attacker[actor.participant_id],
                healing_by_attacker[actor.participant_id],
                sources=list(
                    (ledgers.breakdown.get(actor.participant_id) or {})
                    .get("sources", {})
                    .values()
                ),
                utility_outcomes=(
                    utility_by_actor[actor.participant_id] if include_receipt else None
                ),
            )
            for actor in roster.all_actors
        ]
    )
    return Walked(
        program,
        walk_result,
        survival,
        _breakdown_view.breakdown(program, walk_result),
        support_by_attacker,
    )
