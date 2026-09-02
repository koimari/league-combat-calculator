"""The single survival transition kernel.

One semantic implementation per mechanic, consumed by both the receipt
adapter (:mod:`survival.receipt_state`) and the optimizer score adapter
(:mod:`survival.score_state`).  Arithmetic, operation order, and rounding
mirror the former authoritative ``_simulate_survival`` walk exactly; the
adapters differ only in representation and observation:

* the receipt ledger annotates the event dicts the public timeline
  serializes (``pair_damage``, ``live_damage``, ``overkill``,
  ``applied_amount``, ``skipped_reason``, ...) and can schedule
  walk-authored recovery packets (Maw omnivamp, Doran's Shield, Defy);
* the score ledger keeps parallel-array accumulation (``applied`` slots,
  trigger ``status``, per-attacker damage order) and never annotates.

``run_survival_walk`` is the one entry point: it applies every
precondition gate (window, expiry, trigger linkage, death) in the
authoritative order and dispatches each :class:`SurvivalAction` to the
single implementation of its mechanic against one per-participant state
dict.  That dispatch lives in the loop itself — there is exactly one
ladder here, so a mechanic cannot be routed two ways.  The plain-damage
hot-loop branch stays the first dispatch arm and reads none of the four
fields it cannot carry (trigger, live formula, Grievous pack, wound).

Ledger observation contract (the only adapter difference):

* ``ctx.ledger.write(action, **fields)`` — unconditional event writes the
  authoritative walk applies whether or not diagnostics are requested
  (``damage``, ``applied_amount``, ``skipped_reason``, ``expires_at``,
  threshold/reactive/execute receipts, ...);
* ``ctx.ledger.annotate(action, **fields)`` — the annotate-gated
  diagnostics (``pair_damage``, ``live_damage``, ``overkill``,
  ``raw_amount``, ``healing_reduction``, ``venom``, ...) that only the
  serialized receipt reads;
* ``ctx.ledger.restore(action, **fields)`` — an **input** the walk puts back
  onto a packet a later transition will price, not an outcome a transition
  produced.  Knight's Vow's holder gate is the one caller: it cancels the
  redirect child and puts the unredirected amount back on the parent so the
  damage transition prices it.  It rides ``write``'s wire on both adapters
  and changes nothing they do — the separation exists for the write-once
  outcome ledger, which otherwise sees the restored input and the priced
  outcome as two answers to one question and refuses the second;
* ``ctx.ledger.mark_applied`` / ``mark_blocked`` — trigger-linkage status;
* ``ctx.ledger.schedule_heal(event, recipient_id)`` — walk-authored
  recovery packets (receipt inserts beside the current action; score
  raises, because compilation rejects every mechanic that could author
  one).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass, field
from typing import Any, NamedTuple, Protocol

from .. import shield_ledger
from ..cleanse_eligibility import (
    CleanseEligibility,
    item_declaration,
    movement_entry,
    resolve_cleanse_item,
    resolve_excluded_kinds,
    truncate_intervals,
)
from ..crowd_control_eligibility import (
    KNOWN_CONTROL_KINDS,
    CrowdControlDecision,
    CrowdControlEligibility,
    classify_control,
    immunity_holder,
)
from ..delivery_eligibility import (
    SPELL_SHIELD_ONE_USE_RULE,
    DefenseWindow,
    SourceReceipt,
    SpellShieldComposition,
    SpellShieldEligibility,
    TriggeredHealRule,
    spell_shield_block_decision,
    spell_shield_group_key,
    stable_event_key,
)
from ..healing_reduction import (
    GRIEVOUS_WOUNDS_FACTOR,
    heal_and_shield_power_factor,
    matching_healing_reduction,
)
from ..resistance import apply_resistance
from . import pricing
from .actions import (
    EVENT_SLOTS,
    NO_SLOT,
    ActionKind,
    LiveProbe,
    SurvivalAction,
    TransitionRank,
    attack_class_of,
    damage_class_of,
    declared_modifier_classes,
)

#: The revive label used when a participant's resolved defenses arm a revive
#: without naming its own source.  Guardian Angel is the item-source carrier
#: of the shared revive interface, so the timeline authoring
#: (``participant_timeline`` / ``survival.compile``) already defaults to this
#: same label; the kernel mirrors it so the resurrection stasis and the
#: applied revive can never disagree about who owns the window.
_DEFAULT_REVIVE_SOURCE = "Guardian Angel (Rebirth)"


class SurvivalLedger(Protocol):
    """The observation adapter every walk drives.

    The module docstring above is the contract; this is its signature.
    All three implementations (receipt, score, outcome) satisfy it, so
    the kernel reads the capability flags directly instead of asking.
    """

    # pylint: disable=missing-function-docstring  # documented above

    # Verbosity, read once per walk onto ``TransitionContext``.
    records_annotations: bool
    records_event_fields: bool

    def write(self, action: SurvivalAction, **fields: Any) -> None: ...

    def annotate(self, action: SurvivalAction, **fields: Any) -> None: ...

    def restore(self, action: SurvivalAction, **fields: Any) -> None: ...

    def skip(
        self,
        action: SurvivalAction,
        reason: str,
        *,
        damage_phase: bool = False,
        preserve_reason: bool = False,
    ) -> None: ...

    def trigger_applied(self, action: SurvivalAction) -> bool: ...

    def mark_applied(self, action: SurvivalAction) -> None: ...

    def mark_blocked(self, action: SurvivalAction) -> None: ...

    def schedule_heal(self, heal_event: dict[str, Any], recipient_id: str) -> None: ...


def resolve_grievous(
    profiles: tuple[Any, ...], damage_type: str
) -> tuple[float, float, tuple[str, ...]] | None:
    """Pre-resolve one attacker's Grievous application for one damage type.

    The receipt adapter resolves profiles per event; the score compiler
    prebuilds one pack per (attacker, damage type) because both are fixed
    for a compiled action.  Returns (strongest factor, strongest duration,
    all matching source labels) exactly as the per-event derivation would.
    """
    matching = matching_healing_reduction(profiles, damage_type) if profiles else ()
    if not matching:
        return None
    strongest = min(matching, key=lambda profile: float(profile.get("factor", 1.0)))
    labels = tuple(
        f"{profile.get('item', '')} · {profile.get('source', '')}"
        for profile in matching
    )
    return (
        float(strongest.get("factor", 1.0)),
        float(strongest.get("duration", 0.0)),
        labels,
    )


def evaluate_live_raw_formula(
    raw_formula: Any,
    missing_ratio: float,
    target_max_health: float,
) -> float:
    """Evaluate a dynamic packet against the live target maximum health.

    A callback takes the missing-health ratio, optionally the max health too.
    """
    try:
        return max(0.0, float(raw_formula(missing_ratio, target_max_health)))
    except TypeError:
        return max(0.0, float(raw_formula(missing_ratio)))


def participant_pools(combatant: Any) -> shield_ledger.ShieldPools:
    """Stage one participant's starting health, shields, and Lifelines."""
    defenses = combatant.defenses
    # An authored starting health (roster ``current_health``) is the one way
    # a participant enters the fight below full health.  It is bounded to
    # (0, max health] by its parser, so a missing/None value is full health
    # rather than an unsourced guess -- and a participant with no request at
    # all (the kernel's own fixtures) authored none, which is the same fact.
    starting_health = getattr(
        getattr(combatant, "request", None), "current_health", None
    )
    return shield_ledger.build_pools(
        max(0.0, float(combatant.stats.get("health", 0.0))),
        starting_health=(
            None if starting_health is None else max(0.0, float(starting_health))
        ),
        magic_shield=float(defenses.magic_shield),
        physical_shield=float(defenses.physical_shield),
        general_shield=float(defenses.general_shield),
        threshold_shield_amount=max(0.0, float(defenses.threshold_shield_amount)),
        threshold_shield_health_ratio=max(
            0.0, float(defenses.threshold_shield_health_ratio)
        ),
        threshold_shield_duration=max(0.0, float(defenses.threshold_shield_duration)),
        threshold_shield_damage_type=str(defenses.threshold_shield_damage_type),
        threshold_health_bonus=max(0.0, float(defenses.threshold_health_bonus)),
        threshold_health_heal=max(0.0, float(defenses.threshold_health_heal)),
        threshold_health_ratio=max(0.0, float(defenses.threshold_health_ratio)),
        threshold_health_duration=max(0.0, float(defenses.threshold_health_duration)),
    )


class RegenerationWindow(NamedTuple):
    """One holder's regeneration window, compiled before the walk runs.

    The kernel's form of a ``sustain`` regeneration declaration: the five
    sourced numbers plus the owner whose name the scheduled ticks publish.
    ``survival`` may not reach a declaration itself — the dependency runs
    ``interpreters -> survival`` and never back — so the caller that builds
    the walk context compiles it and hands it over as data, which is the
    same device every other walk-lane number arrives by.

    ``None`` for a participant declaring none.  An absent window is an
    answer, and the alternative — five defaulted zeros — is a recovery that
    silently pays nothing.
    """

    owner: str
    total_melee: float
    total_reduced: float
    duration: float
    missing_health_cap: float
    tick_interval: float


class SubjectDefenseProfile(NamedTuple):
    """Per-event defense constants for one participant.

    The kernel consults these on every damage packet; they are fixed for a
    walk, so the context caches one profile per subject instead of re-reading
    the defense record and scanning items ~100 times per participant.
    """

    jak_interval: float
    jak_max: int
    jak_bonus_multiplier: float
    force_interval: float
    force_duration: float
    force_max: int
    force_immobilize_stacks: int
    force_bonus_magic_resistance: float
    has_stack_items: bool
    regeneration: RegenerationWindow | None


def _subject_defense_profile(
    combatant: Any, regeneration: RegenerationWindow | None
) -> SubjectDefenseProfile:
    """Extract one participant's fixed combat-state defense constants."""
    defenses = combatant.defenses
    jak_interval = max(0.0, float(defenses.jaksho_stack_interval))
    jak_max = max(0, int(defenses.jaksho_max_stacks))
    force_interval = max(0.0, float(defenses.force_stack_interval))
    force_duration = max(0.0, float(defenses.force_stack_duration))
    force_max = max(0, int(defenses.force_max_stacks))
    return SubjectDefenseProfile(
        jak_interval=jak_interval,
        jak_max=jak_max,
        jak_bonus_multiplier=float(defenses.jaksho_bonus_resistance_multiplier),
        force_interval=force_interval,
        force_duration=force_duration,
        force_max=force_max,
        force_immobilize_stacks=int(defenses.force_immobilize_stacks),
        force_bonus_magic_resistance=float(defenses.force_bonus_magic_resistance),
        has_stack_items=bool(
            (jak_interval > 0.0 and jak_max > 0)
            or (force_interval > 0.0 and force_max > 0)
        ),
        regeneration=regeneration,
    )


# ---------------------------------------------------------------------------
# Transition context — everything cross-participant the kernel reads
# ---------------------------------------------------------------------------


@dataclass
class TransitionContext:
    """Cross-participant inputs for one survival walk.

    ``states`` is the index-aligned per-participant state list; every
    :class:`SurvivalAction` carries participant *indices* so both adapters
    share one kernel.  ``venom_profiles``/``reduction_profiles`` are
    attacker-index-aligned Serpent's Fang packs and healing-reduction
    profiles (``None`` in score mode, where the compiler prebuilds the
    same data into each action's ``grievous`` field).

    ``regeneration_windows`` is participant-index-aligned and **required**,
    with no default: it is the compiled form of the ``sustain`` regeneration
    declarations this roster brings, and ``survival`` cannot reach a
    declaration to build it.  A default of ``None`` would make a context
    that forgot to compile them indistinguishable from a roster declaring
    none — a recovery that silently pays nothing, which is the failure this
    campaign exists to remove.
    """

    duration: float
    states: list[dict[str, Any]]
    combatants: Sequence[Any]
    index_of: Mapping[str, int]
    ledger: SurvivalLedger
    regeneration_windows: Sequence[RegenerationWindow | None]
    venom_profiles: list[tuple[float, float] | None] | None = None
    reduction_profiles: list[tuple[Any, ...]] | None = None
    # Keyed by event slot (Phase 4 S1): ``redirect_children`` maps a parent
    # packet's slot to the redirected child action, and the two sets hold the
    # slots the holder-health gate has judged and cancelled.
    redirect_children: MutableMapping[int, Any] = field(default_factory=dict)
    redirect_gate_checked: set[int] = field(default_factory=set)
    redirect_cancelled: set[int] = field(default_factory=set)
    shield_presence_at_time: dict[tuple[int, float], bool] = field(
        default_factory=dict, repr=False
    )
    # Derived per-walk speed fields.  The ledger capability
    # flags let the kernel skip building kwargs a no-op adapter would
    # drop, and ``_defense_profiles`` lazily caches each subject's
    # per-event defense constants so the hot loop never repeats a getattr
    # chain or item scan.
    records_annotations: bool = field(init=False)
    records_event_fields: bool = field(init=False)
    record_defy_damage: bool = field(init=False)
    stack_flags: list[bool] = field(init=False, repr=False)
    regeneration_flags: list[bool] = field(init=False, repr=False)
    _defense_profiles: list[SubjectDefenseProfile] = field(init=False, repr=False)
    # Every caster's heal-and-shield-power factor, resolved once per walk
    # so the recovery path never re-reads a stat dict per packet.
    _heal_power: list[float] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.records_annotations = bool(self.ledger.records_annotations)
        self.records_event_fields = bool(self.ledger.records_event_fields)
        # ``damage_records`` feeds only Defy (Death's Dance) takedown
        # attribution; with no defy holder in the fight the per-event
        # record append is dead weight and is skipped entirely.
        self.record_defy_damage = any(
            float(combatant.defenses.defy_window) > 0.0 for combatant in self.combatants
        )
        # Per-event gates read these plain lists directly (a method call per
        # damage packet is measurable at ~100k packets per request).
        if len(self.regeneration_windows) != len(self.combatants):
            raise ValueError(
                f"{len(self.regeneration_windows)} compiled regeneration "
                f"windows for {len(self.combatants)} participants; the "
                "sequence is participant-index-aligned, so a short one would "
                "give somebody else's window to the wrong subject"
            )
        profiles = [
            _subject_defense_profile(combatant, window)
            for combatant, window in zip(
                self.combatants, self.regeneration_windows, strict=False
            )
        ]
        self._defense_profiles = profiles
        self.stack_flags = [profile.has_stack_items for profile in profiles]
        self.regeneration_flags = [
            profile.regeneration is not None for profile in profiles
        ]
        self._heal_power = [
            heal_and_shield_power_factor(getattr(combatant, "stats", None))
            for combatant in self.combatants
        ]

    def defense_profile(self, subject: int) -> SubjectDefenseProfile:
        """The subject's cached per-event defense constants."""
        return self._defense_profiles[subject]

    # A packet with no attacker index (``-1``) was not authored by a
    # participant this walk holds, so nobody's stat may amplify it.
    def heal_power(self, caster: int) -> float:
        """One caster's heal-and-shield-power factor, 1.0 outside the roster."""
        if not 0 <= caster < len(self._heal_power):
            return 1.0
        return self._heal_power[caster]

    def reductions_for(self, attacker: int) -> tuple[Any, ...]:
        """One attacker's healing-reduction profiles, empty where it has none.

        Score mode carries no profile list, so an empty tuple is the honest
        answer for a missing list and for an attacker outside one alike.
        """
        if self.reduction_profiles is None or not (
            0 <= attacker < len(self.reduction_profiles)
        ):
            return ()
        return self.reduction_profiles[attacker]


def expire_temporary_health(state: dict[str, Any], event_time: float) -> bool:
    """Expire a temporary-health window at ``event_time``; return whether any
    bonus was removed.

    The clamp itself is ``shield_ledger.expire_temporary_max_health`` — the
    one implementation of the Wiki's maximum-health-decrease rule, shared
    with the ordered damage walk's Lifeline expiry.  What stays here is this
    walk's own bookkeeping: which window closed, and when.
    """
    if (
        state["temporary_health_amount"] <= 0.0
        or state["temporary_health_until"] <= 0.0
        or event_time < state["temporary_health_until"]
    ):
        return False
    shield_ledger.expire_temporary_max_health(
        state["pools"], state["temporary_health_amount"]
    )
    state["temporary_health_amount"] = 0.0
    state["temporary_health_expired_at"] = round(state["temporary_health_until"], 3)
    state["temporary_health_until"] = 0.0
    return True


# ---------------------------------------------------------------------------
# Combat-state stack ledgers (Force of Nature, Jak'Sho)
# ---------------------------------------------------------------------------


def update_combat_state(
    ctx: TransitionContext, action: SurvivalAction, state: dict[str, Any]
) -> None:
    """Advance sourced combat-state item stacks before one damage packet."""
    profile = ctx.defense_profile(action.subject)
    aftershock_active = state["aftershock_until"] > action.time
    if not profile.has_stack_items and not aftershock_active:
        # Neither Jak'Sho nor Force of Nature is armed: no stack can ever
        # accrue, and Aftershock has no active resistance window. The
        # dynamic resistance bonuses stay at their inert zero.
        state["dynamic_bonus_armor"] = 0.0
        state["dynamic_bonus_magic_resistance"] = 0.0
        return
    participant_id = ctx.combatants[action.subject].participant_id
    source_id = (
        ctx.combatants[action.attacker].participant_id
        if 0 <= action.attacker < len(ctx.combatants)
        else ""
    )
    if not source_id or source_id == participant_id:
        return
    if action.reactive or action.deferred:
        return
    if action.amount <= 0.0:
        return
    target_state = state

    # Jak'Sho is combat-time state: one stack per second, capped at the
    # sourced maximum. It multiplies bonus resistances only at cap.
    jak_interval = profile.jak_interval
    jak_max = profile.jak_max
    if jak_interval > 0.0 and jak_max > 0:
        stacks = min(jak_max, max(0, math.floor(action.time / jak_interval)))
        if stacks != target_state["jaksho_stacks"]:
            target_state["jaksho_stacks"] = stacks
            target_state["jaksho_stack_events"].append(
                {"time": round(action.time, 6), "stacks": stacks}
            )
            ctx.ledger.write(action, jaksho_stacks=stacks)

    # Force of Nature counts incoming champion magic-damage cast instances.
    # The packet may carry an immobilisation marker from a reviewed module;
    # absent that marker we do not guess the two-stack branch.  The
    # per-instance cadence is the sourced rule ("Once per cast instance,
    # each incoming basic attack, ability, or item effect can only generate
    # 1 stack ... every 1 second"): every cast instance carries its own
    # 1-second throttle, so DIFFERENT instances stack within a second and
    # the SAME instance re-stacks at 1s intervals (P3 package 3Q).
    force_interval = profile.force_interval
    force_duration = profile.force_duration
    force_max = profile.force_max
    if action.damage_type == "magic" and force_interval > 0.0 and force_max > 0:
        last_time = target_state["force_last_stack_time"]
        if (
            last_time is not None
            and force_duration > 0.0
            and action.time - float(last_time) >= force_duration
        ):
            target_state["force_stacks"] = 0
            target_state["force_last_stack_time"] = None
            target_state["force_cast_last_times"].clear()
        cast_key = str(
            action.ability_instance or f"{action.source_key}:{action.sequence or ''}"
        )
        last_for_cast = target_state["force_cast_last_times"].get(cast_key)
        elapsed = (
            float("inf")
            if last_for_cast is None
            else action.time - float(last_for_cast)
        )
        if elapsed + 1e-9 >= force_interval:
            increment = (
                max(1, profile.force_immobilize_stacks) if action.immobilized else 1
            )
            target_state["force_stacks"] = min(
                force_max, target_state["force_stacks"] + increment
            )
            target_state["force_cast_last_times"][cast_key] = action.time
            target_state["force_last_stack_time"] = action.time
            target_state["force_stacks_until"] = action.time + force_duration
            target_state["force_stack_events"].append(
                {
                    "time": round(action.time, 6),
                    "stacks": target_state["force_stacks"],
                    "immobilized": action.immobilized,
                    "cast": cast_key,
                }
            )
            ctx.ledger.write(action, force_stacks=target_state["force_stacks"])

    target_state["dynamic_bonus_armor"] = 0.0
    target_state["dynamic_bonus_magic_resistance"] = 0.0
    if (
        jak_max > 0
        and target_state["jaksho_stacks"] >= jak_max
        and profile.jak_bonus_multiplier > 0.0
    ):
        multiplier = profile.jak_bonus_multiplier
        target_state["dynamic_bonus_armor"] += target_state["bonus_armor"] * multiplier
        target_state["dynamic_bonus_magic_resistance"] += (
            target_state["bonus_magic_resistance"] * multiplier
        )
    if (
        force_max > 0
        and target_state["force_stacks"] >= force_max
        and profile.force_bonus_magic_resistance > 0.0
    ):
        target_state[
            "dynamic_bonus_magic_resistance"
        ] += profile.force_bonus_magic_resistance
    if aftershock_active:
        target_state["dynamic_bonus_armor"] += target_state["aftershock_bonus_armor"]
        target_state["dynamic_bonus_magic_resistance"] += target_state[
            "aftershock_bonus_magic_resistance"
        ]


def apply_declared_price(
    ctx: TransitionContext, action: SurvivalAction, state: Mapping[str, Any]
) -> float | None:
    """Price one packet from its family's declaration, at the live resistance.

    The from-declaration counterpart of :func:`reprice_dynamic_resistance`
    below, and the reason the two sit together.  That one starts from a
    number the pair engine already mitigated and divides the mitigation back
    out to re-apply it, which it can only do where the fight published the
    baseline the number was priced at.  This one never divides — the
    declaration *is* the pre-mitigation side — so an armed resistance delta
    is simply part of the resistance the raw value meets.

    Returns the priced amount, or ``None`` when the packet went unpriced,
    having receipted why.  Never a silent zero: an unpriced declaration is a
    family's number missing from a roster total, which is the failure this
    stage exists to make visible rather than to cause.

    **A routed packet is receipted by its source and its route** (umbrella
    Amendment R, Ruling 3).  ``rule`` is the mechanic that declared the
    magnitude, which is what D-62 keys the applied contribution on, and the
    ``routing`` block beside it names the family that re-delivered it and the
    share it declared.  Provenance rather than a second number: without it a
    reader would see a source mechanic's magnitude paid twice under one name
    at two subjects and have nothing telling them the second was routed.

    Reached by every action whose packet carries a declaration
    (``action.declared``).
    """
    packet = action.declared
    price = pricing.price_declared_packet(
        packet,
        baseline_effective_armor=action.baseline_effective_armor,
        baseline_effective_mr=action.baseline_effective_mr,
        dynamic_bonus_armor=state.get("dynamic_bonus_armor", 0.0),
        dynamic_bonus_magic_resistance=state.get("dynamic_bonus_magic_resistance", 0.0),
    )
    if price.amount is None:
        ctx.ledger.write(
            action,
            declared_price_unavailable={
                "rule": packet.rule_id,
                "reason": price.unavailable,
                "damage_type": packet.damage_type,
            },
        )
        return None
    ctx.ledger.write(
        action,
        declared_price={
            "rule": packet.rule_id,
            "raw": round(float(packet.raw_amount), 6),
            # The declared amp term, published beside the raw value rather
            # than only inside the amount: a receipt that showed only the
            # product could not tell a big declaration from an amplified
            # one, and the whole reason the term rides the packet is that
            # somebody has to be able to see it (Amendment M, Ruling 1).
            # Unrounded, and the only unrounded number in this row: the
            # others are walk-accumulated damage, where six decimals is the
            # noise floor, while this is a build-time fold of two or three
            # sourced fractions that a reader compares against the
            # declaration itself.  Rounding it would also raise counter 6's
            # kernel ratchet, which is declared non-increasing (D-71).
            "holder_amp": float(packet.holder_amp),
            # ``None`` for true damage, which met no resistance — a receipt
            # that spelled that as 0.0 would read as "mitigated at zero
            # armour", a different and checkable claim.
            "resistance": (
                None if price.resistance is None else round(price.resistance, 6)
            ),
            "amount": round(price.amount, 6),
            # Absent on a packet that reached its subject directly.  A key
            # always present would publish "not routed" as a fact about every
            # packet in the model, which is a claim nobody made.
            **(
                {}
                if packet.routing is None
                else {
                    "routing": {
                        "router": packet.routing.router_rule_id,
                        "damage_share": float(packet.routing.damage_share),
                    }
                }
            ),
        },
    )
    return price.amount


def reprice_dynamic_resistance(
    ctx: TransitionContext, action: SurvivalAction, state: Mapping[str, Any]
) -> float | None:
    """Apply an armed target resistance delta to one post-mitigation packet.

    Returns the repriced amount (the damage flow re-reads it exactly like
    the authoritative walk re-read the mutated event), or ``None`` when no
    reprice applied.
    """
    if action.damage_type == "physical":
        delta = float(state.get("dynamic_bonus_armor", 0.0) or 0.0)
        label = "armor"
        baseline = action.baseline_effective_armor
    elif action.damage_type == "magic":
        delta = float(state.get("dynamic_bonus_magic_resistance", 0.0) or 0.0)
        label = "magic_resistance"
        baseline = action.baseline_effective_mr
    else:
        return None
    if delta <= 0.0:
        return None
    if baseline is None:
        # A source that did not expose an effective resistance is not
        # silently repriced; the packet remains visible and the receipt
        # explains why its dynamic state was unavailable.
        ctx.ledger.write(action, dynamic_resistance_unavailable=label)
        return None
    baseline_factor = apply_resistance(1.0, baseline)
    dynamic_factor = apply_resistance(1.0, baseline + delta)
    if not math.isfinite(baseline_factor) or baseline_factor <= 0.0:
        ctx.ledger.write(action, dynamic_resistance_unavailable=label)
        return None
    amount = max(0.0, action.amount)
    repriced = amount * dynamic_factor / baseline_factor
    ctx.ledger.write(
        action,
        dynamic_resistance={
            "type": label,
            "baseline_effective": round(baseline, 6),
            "delta": round(delta, 6),
            "effective": round(baseline + delta, 6),
            "factor": round(dynamic_factor / baseline_factor, 6),
        },
    )
    return repriced


# ---------------------------------------------------------------------------
# Embedded transitions (ActionKind members, invoked inside damage/heal)
# ---------------------------------------------------------------------------


def apply_ichorshield(
    ctx: TransitionContext, state: dict[str, Any], action: SurvivalAction, excess: float
) -> float:
    """Convert explicit lifesteal excess into Bloodthirster's shield."""
    if str(action.healing_category) != "vamp":
        return 0.0
    capacity = max(0.0, state["ichorshield_cap"] - state["ichorshield_current"])
    converted = min(max(0.0, float(excess)), capacity)
    if converted <= 0.0:
        return 0.0
    state["ichorshield_current"] += converted
    shield_ledger.grant(state["pools"], converted)
    state["support_shield_received"] += converted
    ctx.ledger.write(
        action,
        ichorshield_generated=round(converted, 6),
        ichorshield_total=round(state["ichorshield_current"], 6),
    )
    return converted


def apply_overheal_shield(
    ctx: TransitionContext,
    state: dict[str, Any],
    action: SurvivalAction,
    excess: float,
    event_time: float,
) -> float:
    """Convert sourced overheal into a timed shield (Aphelios Severum).

    Severum's wiki passive converts healing in excess of Aphelios'
    maximum health into a shield capped at the sourced per-level
    amount (10 : 160 by level + 6% maximum health) that lingers for
    up to 30 seconds.  The healing rule stamps its Severum heal
    events with ``overheal_to_shield``, ``overheal_shield_cap`` and
    ``overheal_shield_duration``; the kernel converts the excess (up to
    the cap) into a timed general shield at the heal's timestamp.
    """
    if not action.overheal_to_shield:
        return 0.0
    if action.overheal_shield_cap <= 0.0 or action.overheal_shield_duration <= 0.0:
        return 0.0
    converted = min(max(0.0, float(excess)), action.overheal_shield_cap)
    if converted <= 0.0:
        return 0.0
    shield_ledger.grant(
        state["pools"],
        converted,
        expires_at=event_time + action.overheal_shield_duration,
    )
    state["support_shield_received"] += converted
    ctx.ledger.write(
        action,
        overheal_shield_generated=round(converted, 6),
        overheal_shield_total=round(state["pools"].general_shield, 6),
    )
    return converted


def recovery_is_gated(
    state: Mapping[str, Any], action: SurvivalAction, event_time: float
) -> bool:
    """Return whether a combat-gated recovery must wait for idle time."""
    if action.requires_damage_free_seconds <= 0.0:
        return False
    last_damage = state.get("last_damage_time")
    if last_damage is None:
        return False
    return event_time - float(last_damage) < action.requires_damage_free_seconds - 1e-9


def live_healing_factor(state: Mapping[str, Any], event_time: float) -> float:
    """The defender's Grievous multiplier at *event_time*, read by every
    recovery this instant delivers."""
    if event_time >= state["healing_reduction_until"]:
        return 1.0
    return float(state["healing_reduction_factor"])


def recovery_multiplier(state: Mapping[str, Any], action: SurvivalAction) -> float:
    """Apply received-healing modifiers except to vamp stat packets.

    ``below_half_healing_bonus`` is the sourced share a declaration compiled
    at the walk's boundary; the half itself is the declaration's identity
    rather than a second number — the registry publishes the bonus under a
    key that spells its own gate and publishes no threshold beside it, so
    ``BelowHalfHealingRule`` is named after the boundary it is defined by.
    """
    if str(action.healing_category) == "vamp":
        return 1.0
    multiplier = float(state["healing_received_multiplier"])
    below_half_bonus = float(state.get("below_half_healing_bonus", 0.0) or 0.0)
    if (
        below_half_bonus > 0.0
        and state["pools"].max_health > 0.0
        and state["pools"].health <= state["pools"].max_health * 0.5 + 1e-9
    ):
        multiplier *= 1.0 + below_half_bonus
    return multiplier


def schedule_regeneration_recovery(
    ctx: TransitionContext, action: SurvivalAction, state: dict[str, Any]
) -> None:
    """Schedule a regeneration window only after a certified incoming hit.

    The window does not trigger from damage absorbed entirely by a shield;
    only health damage starts it (the caller supplies the applied-to-health
    amount through the action's event).

    Which subject has one, and every number the window pays, come from the
    compiled declaration the context was handed — never from an item name.
    """
    window = ctx.defense_profile(action.subject).regeneration
    if window is None:
        return
    event = action.event
    applied_to_health = (
        float(event.get("_applied_to_health", 0.0) or 0.0) if event is not None else 0.0
    )
    if applied_to_health <= 0.0:
        return
    combatant = ctx.combatants[action.subject]
    total_melee = window.total_melee
    total_reduced = window.total_reduced
    missing_cap = window.missing_health_cap
    duration_value = window.duration
    tick = window.tick_interval
    if missing_cap <= 0.0 or duration_value <= 0.0 or tick <= 0.0:
        return
    current_state = state
    missing_ratio = (
        max(
            0.0, 1.0 - current_state["pools"].health / current_state["pools"].max_health
        )
        if current_state["pools"].max_health > 0.0
        else 0.0
    )
    if missing_ratio <= 0.0:
        return
    source_key = action.source_key
    is_basic_or_on_hit = (
        action.basic_attack
        or source_key == "auto_attacks"
        or source_key.startswith(("on_hit_", "on_hit_once_"))
    )
    ranged = str(combatant.champion_data.get("attackType", "MELEE")).upper() != "MELEE"
    total_cap = total_reduced if ranged or not is_basic_or_on_hit else total_melee
    total = total_cap * min(1.0, missing_ratio / missing_cap)
    if total <= 0.0:
        return
    trigger_id = EVENT_SLOTS.text(action.event_slot)
    ticks = max(1, round(duration_value / tick))
    for tick_index in range(1, ticks + 1):
        heal_event = {
            "time": round(action.time + tick * tick_index, 6),
            # Enduring Focus is based on current missing health, not the
            # health state at the triggering hit.  Re-evaluate the
            # diminishing-return formula at every sourced tick.
            "amount": 0.0,
            "amount_formula": (
                lambda current_health, maximum_health, total_cap=total_cap, missing_cap=missing_cap, ticks=ticks: (  # noqa: E501 - lambda parameters do not wrap
                    total_cap
                    * min(
                        1.0,
                        max(
                            0.0,
                            (
                                1.0 - current_health / maximum_health
                                if maximum_health > 0.0
                                else 0.0
                            ),
                        )
                        / missing_cap,
                    )
                    / ticks
                )
            ),
            "source": f"{window.owner} (Enduring Focus)",
            "kind": "regen",
            "attacker": combatant.participant_id,
            "target": combatant.participant_id,
            "_event_id": f"{trigger_id}:doran-shield:{tick_index}",
            "_trigger_event_id": trigger_id,
            "sequence": tick_index - 1,
        }
        ctx.ledger.schedule_heal(heal_event, combatant.participant_id)


def trigger_defy(ctx: TransitionContext, target_id: str, event_time: float) -> None:
    """Trigger Defy for every allied holder that recently damaged target."""
    target = next(
        (
            combatant
            for combatant in ctx.combatants
            if combatant.participant_id == target_id
        ),
        None,
    )
    if target is None:
        return
    for holder_index, holder in enumerate(ctx.combatants):
        holder_state = ctx.states[holder_index]
        if holder.participant_id == target_id or holder.team == target.team:
            continue
        defenses = holder.defenses
        window = max(0.0, float(defenses.defy_window))
        if window <= 0.0 or holder_state["death_time"] is not None:
            continue
        matching = [
            record
            for record in holder_state["damage_records"]
            if record["target"] == target_id
            and event_time - record["time"] <= window + 1e-9
            and event_time >= record["time"] - 1e-9
        ]
        if not matching or holder_state["defy_triggered"]:
            continue
        holder_state["defy_triggered"] = True
        holder_state["defy_trigger_time"] = float(event_time)
        holder_state["defy_triggered_damage_ids"].update(
            record["event_slot"] for record in matching
        )
        cleared = sum(holder_state["deferred_batches"].values())
        holder_state["damage_deferral_cleared"] += cleared
        holder_state["damage_deferral_pending"] = 0.0
        holder_state["cleared_deferred_batches"].update(
            holder_state["deferred_batches"]
        )
        holder_state["deferred_batches"].clear()
        duration_value = max(0.0, float(defenses.defy_heal_duration))
        ticks = int(defenses.defy_heal_ticks)
        heal_ratio = max(0.0, float(defenses.defy_heal_bonus_ad_ratio))
        bonus_ad = max(0.0, float(holder.stats.get("bonus_attack_damage", 0.0)))
        if duration_value <= 0.0 or ticks <= 0 or heal_ratio <= 0.0 or bonus_ad <= 0.0:
            continue
        total_heal = bonus_ad * heal_ratio
        trigger_slot = matching[-1]["event_slot"]
        for tick in range(1, ticks + 1):
            heal_event = {
                "time": float(event_time) + duration_value * tick / ticks,
                "kind": "heal",
                "amount": total_heal / ticks,
                "source": "Death's Dance (Defy)",
                "source_key": "heal_Death's Dance",
                "attacker": holder.participant_id,
                "target": holder.participant_id,
                "_event_id": (
                    f"{holder.participant_id}:defy:{target_id}:"
                    f"{round(float(event_time), 9)}:{tick}"
                ),
                "_defy_trigger_slot": trigger_slot,
                "_defy_target_id": target_id,
                "_defy_window": window,
                "sequence": tick - 1,
            }
            ctx.ledger.schedule_heal(heal_event, holder.participant_id)


def schedule_maw_omnivamp_heal(
    ctx: TransitionContext,
    action: SurvivalAction,
    event_time: float,
    event_damage: float,
) -> None:
    """Author the one post-Lifeline omnivamp heal when Maw is active.

    Maw's post-Lifeline omnivamp is a temporary holder stat.  Apply it
    to the exact post-mitigation packet that follows the trigger; do not
    let reactive/deferred packets or true damage manufacture healing.
    """
    if action.attacker < 0 or action.attacker == action.subject:
        return
    holder_state = ctx.states[action.attacker]
    if (
        not holder_state["maw_lifeline_omnivamp_active"]
        or action.reactive
        or action.deferred
        or action.damage_type not in {"physical", "magic"}
        or event_damage <= 0.0
    ):
        return
    maw_heal = event_damage * (holder_state["maw_lifeline_omnivamp_percent"] / 100.0)
    if maw_heal <= 0.0:
        return
    attacker_id = ctx.combatants[action.attacker].participant_id
    heal_event = {
        "time": float(event_time),
        "amount": maw_heal,
        "source": "Maw of Malmortius (Lifeline omnivamp)",
        "kind": "heal",
        "healing_category": "vamp",
        "attacker": attacker_id,
        "target": attacker_id,
        # Every damage packet that can reach this branch carries an id (the
        # receipt composition stamps one on every engine row).  A packet
        # without one contributes nothing rather than interpolating ``None``.
        "_event_id": f"{EVENT_SLOTS.text(action.event_slot)}:maw-omnivamp",
        "_trigger_event_id": EVENT_SLOTS.text(action.event_slot),
        "sequence": int(action.sequence or 0) + 1,
    }
    ctx.ledger.schedule_heal(heal_event, attacker_id)


def grant_reactive_shield(
    ctx: TransitionContext,
    action: SurvivalAction,
    state: dict[str, Any],
    event_time: float,
    event_damage: float,
) -> None:
    """Grant a Noxian Endurance/Persistence typed shield after the hit.

    The shield is granted *after* the triggering champion hit and kept in
    the timed pool so it expires and is consumed in the same order as
    every other sourced barrier; the cooldown is explicit and never
    inferred from a second packet in the same cast.
    """
    if event_damage <= 0.0 or action.attacker < 0 or action.attacker == action.subject:
        return
    if action.reactive:
        return
    reactive_type = state["reactive_shield_damage_type"]
    if (
        reactive_type not in {"physical", "magic"}
        or action.damage_type != reactive_type
        or event_time < state["reactive_shield_cooldown_until"]
        or state["reactive_shield_amount"] <= 0.0
        or state["reactive_shield_duration"] <= 0.0
    ):
        return
    # ``resolve_starting_defenses`` applies Spirit Visage once when it
    # resolves this item-owned amount. Do not multiply it again at
    # trigger time.
    shield_amount = state["reactive_shield_amount"]
    if state["pools"].venom_factor < 1.0 and reactive_type != "magic":
        # Venom cuts non-magic shields the target gains; the reactive
        # barrier is granted by this same damaging hit, whose venom
        # was already applied above.
        shield_amount *= state["pools"].venom_factor
    expires_at = event_time + state["reactive_shield_duration"]
    shield_ledger.grant(
        state["pools"],
        shield_amount,
        pool=reactive_type,
        expires_at=expires_at,
        source=state["reactive_shield_source"],
    )
    state["support_shield_received"] += shield_amount
    state["reactive_shield_cooldown_until"] = (
        event_time + state["reactive_shield_cooldown"]
    )
    if ctx.records_annotations:
        ctx.ledger.annotate(
            action,
            reactive_shield_triggered={
                "amount": round(shield_amount, 6),
                "damage_type": reactive_type,
                "source": state["reactive_shield_source"],
                "expires_at": round(expires_at, 3),
                "cooldown_until": round(state["reactive_shield_cooldown_until"], 3),
            },
        )


# ---------------------------------------------------------------------------
# Per-kind transitions
# ---------------------------------------------------------------------------


def _actor_stasis_blocks(state: Mapping[str, Any], event_time: float) -> bool:
    """Whether an actor's stasis blocks the action it is authoring.

    Ordinary stasis (Zhonya's Time Stop, Bard's Tempered Fate) blocks.  The
    resurrection stasis authored by :func:`arm_revive_stasis` does NOT own
    the skip: it is exactly coextensive with the dead window, and the
    ``attacker_dead`` gate a few lines below is the specific, already-pinned
    reason for a dead holder's blocked packets.  Deferring to it keeps the
    explicit Rebirth stasis a pure state/receipt authoring — identical
    skip reasons, identical downtime, identical deferred-damage handling.

    The bypass is deliberately narrow: it applies only while the actor is
    dead AND the resurrection window is the operative ceiling of
    ``stasis_until``.  A longer ordinary stasis stacked on top of a
    resurrection window still blocks on its own terms, so this can never
    launder a real Time Stop into an unblocked action.
    """
    stasis_until = float(state["stasis_until"])
    if stasis_until <= event_time:
        return False
    revive_stasis_until = float(state["revive_stasis_until"])
    # The ``- 1e-9`` tolerance exists only to absorb float round-trip noise
    # (round() calls elsewhere on these same timestamps) when the revive
    # window is the ONLY thing that ever set stasis_until, so the two
    # values are the same timestamp computed twice.  It is not a grace
    # period: an ordinary stasis (Zhonya's/Time Stop) that genuinely
    # outlasts the revive window by more than 1e-9s must fail this
    # comparison and fall through to ``return True`` so it blocks on its
    # own terms, named "attacker_state_blocked" — not silently absorbed
    # into the revive bypass and misattributed to "attacker_dead".
    return not (
        state["death_time"] is not None
        and revive_stasis_until > event_time
        and revive_stasis_until >= stasis_until - 1e-09
    )


def arm_revive_stasis(state: dict[str, Any], event_time: float) -> bool:
    """Author the explicit resurrection stasis window at a lethal packet.

    Guardian Angel's Rebirth (and the champion revives that share the
    ``StartingDefenses`` revive interface — Anivia, Zac, Zilean) is a
    *Stasis*, not a plain death: the holder is untargetable, invulnerable
    and unable to act for the sourced delay, then restores.  P3 package
    3P authors that window explicitly instead of leaving it implicit in
    the dead state.

    The window is armed ONLY when a revive is genuinely pending: a sourced
    restore amount, a sourced delay, and an OPEN re-arm gate.  A lethal
    packet that finds the revive spent and still on cooldown is an
    ordinary death — no stasis, and (via the same gate in
    :func:`_apply_revive`) no delayed resurrection later.  That is the
    game rule: Rebirth triggers on the lethal hit or not at all.

    Returns whether the window was armed.  The dead-state gates already own
    the blocking (``target_dead`` / ``attacker_dead`` fire before the
    combat-state gates), so this authors state + receipt only and never
    appends a second downtime interval — the death interval it rides
    inside spans exactly the same seconds.
    """
    amount = float(state["revive_armed_amount"])
    delay = float(state["revive_delay"])
    if amount <= 0.0 or delay <= 0.0:
        return False
    if state["revive_used"]:
        cooldown = float(state["revive_cooldown"])
        # Fail closed: an absent/zero sourced cooldown never re-arms, so the
        # strict one-use rule stands rather than inventing a free re-use.
        if cooldown <= 0.0:
            return False
        if float(event_time) < float(state["revive_ready_at"]) - 1e-9:
            return False
    source = state["revive_armed_source"] or _DEFAULT_REVIVE_SOURCE
    until = float(event_time) + delay
    state["revive_stasis_until"] = until
    state["revive_stasis_death"] = float(event_time)
    state["stasis_until"] = max(float(state["stasis_until"]), until)
    state["stasis_started_at"] = float(event_time)
    state["stasis_source"] = source
    state["revive_stasis_windows"].append(
        {
            "start": round(float(event_time), 3),
            "end": round(until, 3),
            "duration": round(delay, 3),
            "source": source,
            "cooldown": round(float(state["revive_cooldown"]), 3),
            "resolved": False,
        }
    )
    return True


def _apply_revive(
    ctx: TransitionContext, action: SurvivalAction, state: dict[str, Any]
) -> None:
    """Revive is a state transition rather than healing: it is allowed to
    run after a lethal packet and restores a sourced resource amount."""
    if state["death_time"] is None:
        ctx.ledger.skip(action, "revive_not_available")
        return
    # The resurrection window is anchored to the lethal hit: the holder
    # stays dead for the full sourced delay after death.  Candidates
    # authored from PRE-lethal packets fire early and are skipped here;
    # the lethal packet's own candidate fires at exactly death + delay
    # (P3 package 3P, Guardian Angel Rebirth parity).
    delay = max(0.0, float(getattr(action, "delay", 0.0) or 0.0))
    if float(action.time) < float(state["death_time"]) + delay - 1e-9:
        ctx.ledger.skip(action, "revive_window_not_elapsed")
        return
    # Which gate owns "may this revive fire?" depends on whether the
    # participant carries a SOURCED revive interface (Guardian Angel's
    # Rebirth, or the champion revives that share the ``StartingDefenses``
    # revive fields).  Only a sourced revive has a cooldown to re-arm
    # against, so only a sourced revive is gated on the armed window.
    if float(state["revive_armed_amount"]) > 0.0 and float(state["revive_delay"]) > 0.0:
        # The lethal packet itself decides whether Rebirth fires: the death
        # transition arms the resurrection stasis only when the re-arm gate
        # is open (see :func:`arm_revive_stasis`).  A death that armed no
        # window is terminal — the sourced cooldown is the reason, and it is
        # named on the receipt rather than silently retried by a later
        # candidate.
        if float(state["revive_stasis_death"]) < float(state["death_time"]) - 1e-9:
            ctx.ledger.skip(
                action,
                (
                    "revive_on_cooldown"
                    if state["revive_used"] and float(state["revive_cooldown"]) > 0.0
                    else "revive_not_available"
                ),
            )
            return
    elif state["revive_used"]:
        # An AUTHORED revive action carrying its own amount/ratio with no
        # sourced arming behind it (synthetic and development fixtures).
        # There is no sourced cooldown to re-arm against, so the original
        # strict one-use rule stands unchanged — fail closed rather than
        # inventing a cooldown the source never declared.
        ctx.ledger.skip(action, "revive_not_available")
        return
    ratio = max(0.0, min(1.0, action.health_ratio))
    amount = max(0.0, action.amount)
    restore = amount if amount > 0.0 else state["pools"].max_health * ratio
    state["pools"].health = min(state["pools"].max_health, restore)
    state["death_time"] = None
    state["revive_time"] = float(action.time)
    state["revive_source"] = str(action.source or action.source_key or "Revive")
    state["revive_health_restored"] = float(state["pools"].health)
    state["revived"] = True
    state["revive_used"] = True
    # The wiki rule: Rebirth's cooldown starts AFTER the resurrection ends.
    # ``revive_ready_at`` is the re-arm timestamp; a zero sourced cooldown
    # parks it at infinity so the one-use gate is never re-opened.
    cooldown = float(state["revive_cooldown"])
    state["revive_ready_at"] = (
        float(action.time) + cooldown if cooldown > 0.0 else float("inf")
    )
    state["terminal_phase"] = "revived"
    if state["revive_stasis_windows"]:
        # ``[-1]`` relies on the one-armed-window-at-a-time invariant: today
        # only one revive_stasis_windows entry is ever unresolved at a given
        # time, because a lethal packet arms a window (arm_revive_stasis)
        # and the very next revive that resolves it targets that same
        # window before any other lethal packet on this actor can arm a
        # second one. A future multi-revive source (Zac/Zilean/Anivia
        # stacked with GA, or any interface that can arm two windows
        # concurrently) must NOT trust list position here — match the
        # window being resolved by ``revive_stasis_death``/event_time
        # against this action instead of indexing the tail.
        state["revive_stasis_windows"][-1]["resolved"] = True
        state["revive_stasis_windows"][-1]["ready_at"] = (
            round(state["revive_ready_at"], 3)
            if cooldown > 0.0
            else state["revive_ready_at"]
        )
    for interval in reversed(state["action_downtime_intervals"]):
        if (
            interval.get("kind") == "death"
            and float(interval.get("end", 0.0)) >= ctx.duration - 1e-9
        ):
            interval["end"] = float(action.time)
            break
    ctx.ledger.write(action, applied_amount=round(state["pools"].health, 6))


def _apply_combat_state_transition(
    ctx: TransitionContext, action: SurvivalAction, state: dict[str, Any]
) -> None:
    """Stasis / invulnerability / untargetable: extend the typed immunity
    window from the authored duration and keep the receipt's source label."""
    duration_value = max(0.0, action.duration)
    until_key = {
        ActionKind.STASIS: "stasis_until",
        ActionKind.INVULNERABLE: "invulnerable_until",
        ActionKind.UNTARGETABLE: "untargetable_until",
    }[action.kind]
    state[until_key] = max(state[until_key], action.time + duration_value)
    if action.kind is ActionKind.STASIS:
        state["stasis_started_at"] = float(action.time)
        state["stasis_source"] = str(action.source or action.source_key or "Stasis")
    if duration_value > 0.0:
        state["action_downtime_intervals"].append(
            {
                "kind": action.kind.value,
                "start": float(action.time),
                "end": float(action.time + duration_value),
                "source": str(action.source or action.source_key or action.kind.value),
            }
        )
    ctx.ledger.write(action, applied_amount=round(duration_value, 6))


def _apply_spell_shield(
    ctx: TransitionContext, action: SurvivalAction, state: dict[str, Any]
) -> None:
    """Arm (or refresh) a spell shield from the authored duration.

    The kernel contract is built here (the ARMG phase of the lifecycle):
    a timed window (start inclusive, end exclusive), the ability-only
    acceptance, and the one-use-per-cast composition with the sourced
    triggered heal when the packet carries one.  Annul shields are armed
    earlier, at state construction, with an infinite window.
    """
    duration_value = max(0.0, action.duration)
    if duration_value <= 0.0 or state["spell_shield_used"]:
        ctx.ledger.skip(action, "spell_shield_not_available")
        return
    state["spell_shield_until"] = max(
        state["spell_shield_until"], action.time + duration_value
    )
    state["spell_shield_source"] = str(
        action.source or action.source_key or "Spell Shield"
    )
    state["spell_shield_heal_amount"] = max(0.0, action.on_block_heal_amount)
    state["spell_shield_heal_delay"] = max(0.0, action.on_block_heal_delay)
    state["spell_shield_heal_source"] = str(
        action.on_block_heal_source
        or action.source
        or action.source_key
        or "Spell Shield"
    )
    state["spell_shield_heal_triggered"] = False
    source_atoms = tuple(
        dict(atom) for atom in ((action.event or {}).get("source_atoms") or ())
    )
    triggered_heal = (
        TriggeredHealRule(
            amount=state["spell_shield_heal_amount"],
            delay=state["spell_shield_heal_delay"],
            source=state["spell_shield_heal_source"],
            source_atoms=source_atoms,
        )
        if state["spell_shield_heal_amount"] > 0.0
        else None
    )
    state["spell_shield_eligibility"] = SpellShieldEligibility(
        name="spell_shield",
        window=DefenseWindow(
            start=float(action.time),
            until=float(action.time + duration_value),
            source_atoms=source_atoms,
        ),
        block_rule=SPELL_SHIELD_ONE_USE_RULE,
        source=SourceReceipt(
            label=str(action.source or action.source_key or "Spell Shield"),
            url="https://wiki.leagueoflegends.com",
        ),
    )
    state["spell_shield_composition"] = SpellShieldComposition(
        triggered_heal=triggered_heal
    )
    state["spell_shield_uses_remaining"] = 1
    ctx.ledger.write(action, applied_amount=round(duration_value, 6))


def _rearm_spell_shield(state: dict[str, Any], event_time: float) -> None:
    """Put a consumed shield back on its holder at ``event_time``.

    The kernel already decided the sourced cooldown elapsed
    (:meth:`SpellShieldRearmClock.rearmed_at`); this writes the state that
    decision implies and receipts the arithmetic behind it — the
    consumption instant, the champion-damage instant that restarted the
    timer, the cooldown, and the resulting ready instant — so a rearm is
    never an unexplained second block.

    The restored budget is READ from the composition's declared use budget
    rather than reset to one, for the reason every other number here comes
    from a declaration: a shield whose composition ever declares two uses
    must not silently come back with one.
    """
    clock = state["spell_shield_rearm"]
    consumed_at = state["spell_shield_consumed_at"]
    composition = state["spell_shield_composition"]
    spent_cast = state["spell_shield_blocked_cast"]
    state["spell_shield_rearm_events"].append(
        {
            "time": round(float(event_time), 3),
            "consumed_at": round(float(consumed_at), 3),
            "cooldown": round(float(clock.cooldown), 3),
            "restarts_on_champion_damage": bool(clock.restarts_on_champion_damage),
            "timer_started_at": round(
                clock.anchor(consumed_at, state["last_damage_time"]), 3
            ),
            "ready_at": round(
                clock.ready_at(consumed_at, state["last_damage_time"]), 3
            ),
            "spent_cast": (str(spent_cast[-1]) if spent_cast else None),
        }
    )
    state["spell_shield_used"] = False
    state["spell_shield_blocked_cast"] = None
    state["spell_shield_consumed_at"] = None
    state["spell_shield_uses_remaining"] = (
        composition.uses.initial_remaining() if composition is not None else None
    )


def _write_spell_shield_reduction_receipt(
    ctx: TransitionContext,
    action: SurvivalAction,
    state: Mapping[str, Any],
    attacker: Any,
) -> None:
    """Mirror a projectile defense's reduction receipt onto a packet the
    spell shield is about to block.

    Interaction order: a prior projectile defense that REDUCES (but does
    not destroy or fully block) a packet still lets the spell shield
    fully block it; the public receipt then shows both the reduction and
    the shield block.  Destroyed, full-blocked, and stasis-blocked
    packets never reach the shield gate, so no mirror is needed there.
    """
    defense = state.get("projectile_defense")
    pdef_eligibility = state.get("projectile_defense_eligibility")
    pdef_composition = state.get("projectile_defense_composition")
    if (
        defense is None
        or pdef_eligibility is None
        or pdef_composition is None
        or pdef_composition.destroy.enabled
        or _interaction_event_key(action)
        in state.get("projectile_defense_full_block_events", set())
        or (
            action.damage_type == "true"
            and not pdef_composition.reduction.applies_to_true_damage
        )
    ):
        return
    pdef_decision = pdef_eligibility.decide(action, attacker)
    if not pdef_decision.eligible:
        return
    before = max(0.0, float(action.amount))
    reduction = pdef_composition.reduction.reduction_for(action)
    after = before * max(0.0, 1.0 - reduction)
    ctx.ledger.write(
        action,
        projectile_defense={
            "source": defense.source,
            "mode": "reduced",
            "reduction": round(reduction, 6),
            "mitigated": round(before - after, 6),
            "delivery": pdef_decision.delivery.public_receipt(),
            "eligible": True,
            "remaining_uses": state["projectile_defense_uses_remaining"],
        },
    )


def _schedule_spell_shield_heal(
    ctx: TransitionContext, action: SurvivalAction, state: dict[str, Any]
) -> None:
    """Schedule one authored heal after a spell shield blocks an effect."""
    amount = max(0.0, state["spell_shield_heal_amount"])
    if amount <= 0.0 or state["spell_shield_heal_triggered"]:
        return
    state["spell_shield_heal_triggered"] = True
    event_time = action.time + max(0.0, state["spell_shield_heal_delay"])
    state["spell_shield_heal_time"] = event_time
    heal_event = {
        "time": event_time,
        "kind": "heal",
        "amount": amount,
        "attacker": ctx.combatants[action.subject].participant_id,
        "target": ctx.combatants[action.subject].participant_id,
        "source": state["spell_shield_heal_source"],
        "source_key": action.source_key,
        "healing_category": "champion",
        "_event_id": f"{EVENT_SLOTS.text(action.event_slot) or action.source_key}"
        f":spell_shield_heal",
        "spell_shield_triggered": True,
    }
    ctx.ledger.schedule_heal(heal_event, ctx.combatants[action.subject].participant_id)
    ctx.ledger.write(action, spell_shield_heal_scheduled=round(event_time, 3))


def _guardian_skip(ctx: TransitionContext, action: SurvivalAction, reason: str) -> None:
    """Record one Guardian candidate that did not activate."""
    ctx.ledger.skip(action, reason)


def _apply_guardian_shield(
    ctx: TransitionContext, action: SurvivalAction, state: dict[str, Any]
) -> bool:
    """Apply one side of a Guardian paired shield.

    Candidate shield packets are sorted before their triggering damage.  The
    owner ledger prices the current hit against the prior 2.5-second damage
    window and opens one shared cooldown.  The paired candidate then applies
    the same shield to the other protected participant.
    """
    event = action.event or {}
    owner_id = str(event.get("_guardian_owner_id", ""))
    owner_index = ctx.index_of.get(owner_id)
    if owner_index is None:
        _guardian_skip(ctx, action, "guardian_owner_unavailable")
        return False
    owner_state = ctx.states[owner_index]
    if owner_state["death_time"] is not None:
        _guardian_skip(ctx, action, "guardian_owner_dead")
        return False

    activation_id = str(event.get("_guardian_activation_id", ""))
    if not activation_id:
        _guardian_skip(ctx, action, "guardian_activation_unavailable")
        return False
    recipient_id = ctx.combatants[action.subject].participant_id
    pending = owner_state["guardian_pending_shields"].get(activation_id)
    if pending is not None:
        applied_targets = pending["applied_targets"]
        if recipient_id in applied_targets:
            _guardian_skip(ctx, action, "guardian_peer_already_shielded")
            return False
    else:
        if action.time < owner_state["guardian_cooldown_until"] - 1e-9:
            _guardian_skip(ctx, action, "guardian_cooldown")
            return False
        threshold = max(0.0, float(event.get("_guardian_threshold", 0.0) or 0.0))
        current_damage = max(
            0.0, float(event.get("_guardian_trigger_amount", 0.0) or 0.0)
        )
        window = max(0.0, float(event.get("_guardian_window_seconds", 0.0) or 0.0))
        cutoff = action.time - window
        prior_damage = sum(
            float(record.get("amount", 0.0) or 0.0)
            for record in owner_state["guardian_damage_history"]
            if cutoff - 1e-9 <= float(record.get("time", 0.0)) <= action.time + 1e-9
        )
        target_pools = state["pools"]
        current_shields = sum(
            (
                target_pools.magic_shield,
                target_pools.physical_shield,
                target_pools.general_shield,
            )
        )
        lethal = current_damage >= target_pools.health + current_shields - 1e-9
        if prior_damage + current_damage < threshold - 1e-9 and not lethal:
            _guardian_skip(ctx, action, "guardian_threshold_not_met")
            return False
        pending = {
            "applied_targets": set(),
            "trigger_time": float(action.time),
            "trigger_event_id": str(event.get("_guardian_trigger_event_id", "")),
        }
        owner_state["guardian_pending_shields"][activation_id] = pending
        cooldown = max(0.0, float(event.get("_guardian_cooldown_seconds", 0.0) or 0.0))
        owner_state["guardian_cooldown_until"] = action.time + cooldown
        owner_state["guardian_trigger_events"].append(
            {
                "time": round(float(action.time), 3),
                "trigger_event_id": str(event.get("_guardian_trigger_event_id", "")),
                "trigger_target": str(event.get("_guardian_trigger_target", "")),
                "damage_window": round(prior_damage + current_damage, 6),
                "threshold": round(threshold, 6),
                "lethal": bool(lethal),
                "cooldown_until": round(owner_state["guardian_cooldown_until"], 3),
            }
        )
    amount = (
        max(0.0, action.amount)
        * ctx.heal_power(action.attacker)
        * state["healing_received_multiplier"]
    )
    if state["pools"].venom_factor < 1.0:
        amount *= state["pools"].venom_factor
        ctx.ledger.annotate(
            action,
            venom={
                "factor": round(state["pools"].venom_factor, 6),
                "until": round(state["venom_until"], 6),
            },
        )
    if amount <= 0.0:
        _guardian_skip(ctx, action, "guardian_shield_not_available")
        return False
    expires_at = action.time + max(0.0, action.duration)
    shield_ledger.grant(state["pools"], amount, expires_at=expires_at)
    state["support_shield_received"] += amount
    pending["applied_targets"].add(recipient_id)
    ctx.ledger.write(
        action,
        applied_amount=round(amount, 6),
        expires_at=round(expires_at, 3),
        guardian_triggered={
            "owner": owner_id,
            "trigger_event_id": str(event.get("_guardian_trigger_event_id", "")),
            "activation_id": activation_id,
            "cooldown_until": round(owner_state["guardian_cooldown_until"], 3),
        },
    )
    ctx.ledger.mark_applied(action)
    return True


def _record_guardian_damage(
    ctx: TransitionContext,
    action: SurvivalAction,
    event_time: float,
    event_damage: float,
) -> None:
    """Keep applied enemy damage for each Guardian holder's sourced window."""
    if event_damage <= 0.0 or action.event is None:
        return
    owners = action.event.get("_guardian_owner_ids")
    if not isinstance(owners, list):
        return
    for owner_id in owners:
        owner_index = ctx.index_of.get(str(owner_id))
        if owner_index is None:
            continue
        ctx.states[owner_index]["guardian_damage_history"].append(
            {
                "time": float(event_time),
                "amount": max(0.0, float(action.amount)),
                "target": ctx.combatants[action.subject].participant_id,
                "event_id": EVENT_SLOTS.text(action.event_slot),
            }
        )


def _apply_shield(
    ctx: TransitionContext, action: SurvivalAction, state: dict[str, Any]
) -> None:
    """A sourced shield lands before damage at its timestamp.  Serpent's
    Fang venom cuts shields the target gains while its window is active."""
    if action.event is not None and action.event.get("_guardian_reactive"):
        _apply_guardian_shield(ctx, action, state)
        return
    amount = max(0.0, action.amount)
    if callable(action.amount_formula):
        amount = max(
            0.0,
            float(
                action.amount_formula(state["pools"].health, state["pools"].max_health)
            ),
        )
    amount *= ctx.heal_power(action.attacker) * state["healing_received_multiplier"]
    if state["pools"].venom_factor < 1.0:
        amount *= state["pools"].venom_factor
        ctx.ledger.annotate(
            action,
            venom={
                "factor": round(state["pools"].venom_factor, 6),
                "until": round(state["venom_until"], 6),
            },
        )
    if amount <= 0.0:
        ctx.ledger.skip(action, "shield_not_available")
        return
    pool = action.shield_pool or shield_ledger.GENERAL
    if pool not in {
        shield_ledger.GENERAL,
        shield_ledger.MAGIC,
        shield_ledger.PHYSICAL,
    }:
        ctx.ledger.skip(action, "unsupported_shield_pool")
        return
    expires_at = action.time + action.duration if action.duration > 0.0 else None
    source = str(action.source or action.source_key or "Shield")
    shield_source = str(
        action.crowd_control_immunity_source
        if action.crowd_control_immunity_while_shield
        and action.crowd_control_immunity_source
        else source
    )
    shield_ledger.grant(
        state["pools"],
        amount,
        pool=pool,
        expires_at=expires_at,
        source=shield_source,
    )
    state["support_shield_received"] += amount
    if expires_at is not None:
        ctx.ledger.write(action, expires_at=round(expires_at, 3))
    ctx.ledger.write(action, shield_pool=pool)
    if action.crowd_control_immunity_while_shield and expires_at is not None:
        # The immunity contract is tied to the EXACT ledger entry granted
        # below.  The single-slot projection
        # (``crowd_control_immunity_until`` / ``_source``) serves the pinned
        # public rows; the grant ledger is the authority the contract's
        # ``immunity_holder`` reads.
        state["crowd_control_immunity_until"] = max(
            state["crowd_control_immunity_until"], expires_at
        )
        state["crowd_control_immunity_source"] = shield_source
        source_atoms = tuple(
            dict(atom)
            for atom in (
                (action.event or {}).get("source_atom"),
                (action.event or {}).get("duration_atom"),
            )
            if atom is not None
        )
        state["crowd_control_immunity_grants"].append(
            {
                "source": shield_source,
                "granted_at": float(action.time),
                "expires_at": float(expires_at),
                "amount": float(amount),
                "source_atoms": source_atoms,
                "ended_reason": None,
            }
        )
        state["crowd_control_immunity_eligibility"] = CrowdControlEligibility(
            name="crowd_control_immunity",
            window=DefenseWindow(
                start=float(action.time),
                until=float(expires_at),
                source_atoms=source_atoms,
            ),
            holder_source=shield_source,
            source=SourceReceipt(
                label=str(action.source or action.source_key or "Black Shield"),
                url="https://wiki.leagueoflegends.com",
            ),
        )
        ctx.ledger.write(
            action,
            crowd_control_immunity={
                "source": shield_source,
                "until": round(expires_at, 3),
            },
        )
    ctx.ledger.write(action, applied_amount=round(amount, 6))
    ctx.ledger.mark_applied(action)


def _apply_stat_buff(
    ctx: TransitionContext, action: SurvivalAction, state: dict[str, Any]
) -> None:
    """A timed ally stat buff; on-hit-magic components arm the source's
    live on-hit ledger so later attacks by that source are amplified."""
    permanent_health = max(0.0, action.bonus_health)
    if action.duration <= 0.0 and permanent_health <= 0.0:
        ctx.ledger.skip(action, "stat_buff_not_available")
        return
    if permanent_health > 0.0:
        state["pools"].max_health += permanent_health
        state["permanent_bonus_health_received"] += permanent_health
        state["permanent_bonus_health_events"].append(
            {
                "time": round(action.time, 3),
                "amount": round(permanent_health, 3),
                "source": str(action.source or action.source_key),
                "trigger_event_id": EVENT_SLOTS.text(action.trigger_slot),
            }
        )
    buff = {
        "source": str(action.source or "Ally stat buff"),
        "until": (
            action.time + action.duration if action.duration > 0.0 else float("inf")
        ),
        "bonus_attack_speed_percent": action.bonus_attack_speed_percent,
        "bonus_armor": action.bonus_armor,
        "bonus_magic_resistance": action.bonus_magic_resistance,
        "bonus_health": permanent_health,
        "ability_power": action.ability_power,
        "ability_haste": action.ability_haste,
        "on_hit_magic_damage": action.on_hit_magic_damage,
    }
    state["support_buffs"].append(buff)
    if buff["on_hit_magic_damage"] > 0.0:
        state["active_on_hit_magic"].append(
            {
                "source": buff["source"],
                "amount": buff["on_hit_magic_damage"],
                "until": buff["until"],
            }
        )
    if action.event is not None and action.event.get("_aftershock"):
        state["aftershock_bonus_armor"] = max(0.0, action.bonus_armor)
        state["aftershock_bonus_magic_resistance"] = max(
            0.0, action.bonus_magic_resistance
        )
        state["aftershock_until"] = action.time + action.duration
        trigger_event = {
            "time": round(action.time, 3),
            "until": round(action.time + action.duration, 3),
            "bonus_armor": round(action.bonus_armor, 3),
            "bonus_magic_resistance": round(action.bonus_magic_resistance, 3),
            "trigger_event_id": EVENT_SLOTS.text(action.trigger_slot),
            "source": str(action.source or action.source_key),
        }
        state["aftershock_trigger_events"].append(trigger_event)
        ctx.ledger.write(action, aftershock=trigger_event)
    fields: dict[str, Any] = {"applied_amount": round(action.amount, 6)}
    if action.duration > 0.0:
        fields["expires_at"] = round(action.time + action.duration, 3)
    if permanent_health > 0.0:
        fields["permanent_bonus_health"] = round(permanent_health, 6)
    ctx.ledger.write(action, **fields)
    ctx.ledger.mark_applied(action)


def _apply_damage_modifier(
    ctx: TransitionContext, action: SurvivalAction, state: Mapping[str, Any]
) -> None:
    """Arm a timed (or persistent) cross-participant damage modifier."""
    # The declaration is read before the availability gate: a packet that
    # restricts nothing is a bug whether or not this one arms (D-04).
    damage_classes, attack_classes = declared_modifier_classes(action)
    persistent = action.persistent
    if action.duration <= 0.0 and not persistent:
        ctx.ledger.skip(action, "damage_modifier_not_available")
        return
    modifier = {
        "source": str(action.source or "Damage modifier"),
        "until": float("inf") if persistent else action.time + action.duration,
        "multiplier": action.multiplier,
        "reduction": action.amount if action.damage_reduction else 0.0,
        "damage_reduction": action.damage_reduction,
        "next_event_only": action.next_event_only,
        "all_sources": action.all_sources,
        "armor_reduction_percent": action.armor_reduction_percent,
        "mr_reduction_percent": action.mr_reduction_percent,
        "resistance_type": action.resistance_type,
        "holder": action.holder,
        "armed_by": action.attacker,
        "damage_classes": damage_classes,
        "attack_classes": attack_classes,
        # A *source* restriction, not the holder: this modifier applies only
        # to damage whose source is this participant.  Empty is "no source
        # restriction", which is every modifier that is not one.
        "source_participant": action.source_participant,
    }
    replaced = _refresh_live_modifier(state["active_damage_modifiers"], modifier)
    if replaced is None:
        state["active_damage_modifiers"].append(modifier)
    else:
        ctx.ledger.write(action, refresh=replaced)
    if not persistent:
        ctx.ledger.write(action, expires_at=round(action.time + action.duration, 3))
    ctx.ledger.write(action, applied_amount=round(action.amount, 6))


def _refresh_live_modifier(
    armed: list[dict[str, Any]], modifier: Mapping[str, Any]
) -> dict[str, Any] | None:
    """Refresh one holder's live modifier in place, or ``None`` if it is new.

    **One holder's one mechanic on one subject is one debuff.**  A second
    trigger refreshes the window the first opened rather than arming a copy
    beside it, which would multiply every packet in the overlap twice.

    Identity is ``(source, armed_by)``, the slot that *authored* the packet,
    deliberately not ``holder``, which is ``-1`` for exactly the
    coupled-authoritative mechanics that need this most.  Two **different**
    holders keep both modifiers; ``HolderStacking`` rules whether they should.

    The surviving window is the later expiry, which ``WindowMerge.REFRESH``
    names.  The replaced expiry is unrounded: rounding is presentation.
    """
    for index, live in enumerate(armed):
        if (
            live["source"] != modifier["source"]
            or live["armed_by"] != modifier["armed_by"]
        ):
            continue
        previous = float(live["until"])
        armed[index] = {**modifier, "until": max(previous, float(modifier["until"]))}
        return {
            "reason": "refresh",
            "source": str(modifier["source"]),
            "previous_expires_at": previous if math.isfinite(previous) else None,
        }
    return None


def _apply_utility(
    ctx: TransitionContext, action: SurvivalAction, state: dict[str, Any]
) -> None:
    """Utility dimensions (on-hit magic, movement, cleanse, slow, economy,
    vision) are receipted in their native units; the calculator never
    converts them into damage.  On-hit magic is the one kind the walk's
    arithmetic reads, and it arms the subject's live ledger here."""
    if action.kind is ActionKind.ON_HIT_MAGIC:
        state["active_on_hit_magic"].append(
            {
                "source": str(action.source or "On-hit magic"),
                "amount": action.amount,
                "until": action.time + action.duration,
                "next_event_only": action.next_event_only,
            }
        )
    ctx.ledger.write(action, applied_amount=round(action.amount, 6))
    if action.duration_set:
        ctx.ledger.write(action, expires_at=round(action.time + action.duration, 3))
    if action.utility_kind == "cleanse":
        # A cleanse-kind packet (QSS/Mercurial self-cast) applies the typed
        # cleanse contract: interval truncation + receipts (P2 Slice 4).
        _apply_cleanse(ctx, action, state)


def _apply_cleanse(
    ctx: TransitionContext, action: SurvivalAction, state: dict[str, Any]
) -> None:
    """Apply one item-cleanse activation through the typed kernel.

    The cleanse contract (P2 Slice 4, :mod:`cleanse_eligibility`) resolves
    the sourced item declaration from the packet's marker/source, decides
    eligibility against the recipient's ACTIVE control intervals at the
    activation time, truncates BOTH the crowd-control ledger and the
    action-downtime ledger with ONE kernel operation, and writes the
    recipient ``cleanse`` and caster ``cleanse_use`` receipts.  A cleanse
    removes ONLY eligible control active at its activation; historical
    downtime before activation remains counted; the active interval ends
    at activation; future control packets are untouched (no immunity).

    The packet's event dict keeps the existing ``applied_amount``
    observation; the receipts live on the survival rows (the acceptance
    matrix pins no per-event annotation).
    """
    item = resolve_cleanse_item(action.cleanse_item or action.source_key)
    declaration = item_declaration(item)
    holder_index = (
        action.attacker if 0 <= action.attacker < len(ctx.states) else action.subject
    )
    holder_state = ctx.states[holder_index]
    holder_id = ctx.combatants[holder_index].participant_id
    target_id = ctx.combatants[action.subject].participant_id
    use = holder_state.setdefault("cleanse_uses", {}).setdefault(
        item,
        {
            "uses_remaining": 1,
            "activations": 0,
            "last_activation": None,
            "last_cleanse_group": None,
        },
    )
    eligibility = CleanseEligibility(
        declaration=declaration,
        source=SourceReceipt(
            label="Local League Wiki cache — " + item,
            url="https://wiki.leagueoflegends.com",
        ),
    )
    # ``item_held`` is True by construction: the packet authoring layer
    # (derive_item_support_effects) only emits cleanse packets for items
    # the holder actually equips, and timeline fixtures author the packet
    # directly.  The kernel keeps the ``not_armed`` denial for explicit
    # holder mappings that prove otherwise.
    #
    # P2 Slice 7: a multi-recipient cast (Milio R fan-out) shares ONE use
    # per GROUP — the first recipient of a group consumes it, every
    # same-group recipient sees the use still available for its own
    # interval decision without re-consuming; a SECOND cast (a new group)
    # fails closed with use_spent for all of its recipients.
    group = str(action.cleanse_group or "")
    same_group = bool(group) and group == use.get("last_cleanse_group")
    decision = eligibility.decide(
        _cleanse_action_view(action, item, target_id, holder_id, state),
        holder={
            "uses_remaining": 1 if same_group else int(use["uses_remaining"]),
            "item_held": True,
        },
    )
    if not same_group:
        use["activations"] += 1
        if decision.use_consumed:
            use["uses_remaining"] = max(0, int(use["uses_remaining"]) - 1)
            use["last_activation"] = float(action.time)
            use["last_cleanse_group"] = group
    fired_while_cc = (
        float(holder_state.get("crowd_control_until", 0.0) or 0.0)
        > float(action.time) + 1e-9
    )
    holder_state["cleanse_use"] = _cleanse_use_receipt(
        item, declaration, use, fired_while_crowd_controlled=fired_while_cc
    )
    if decision.reason == "use_spent":
        state.setdefault("cleanse_denied", []).append(
            {"time": round(float(action.time), 6), "reason": "use_spent"}
        )
        return
    if not decision.eligible:
        # Denied outcomes (control_not_active / excluded_control_kind /
        # unknown_control / target_not_selected / not_armed /
        # caster_control_blocks_cleanse) never touch the interval ledgers;
        # the receipt is the observable denial.
        state["cleanse"] = {
            **decision.public_receipt(),
            "decision": decision.public_receipt(),
            "heal": _cleanse_heal_entry(action, declaration),
            "movement": movement_entry(declaration),
        }
        return
    # One kernel truncation on BOTH ledgers.  The cc entries are identical;
    # the action-downtime ledger also carries death rows, whose kind is
    # outside the known control set, and stasis rows, which the carve-out
    # resolver protects because no cleanse removes a stasis.  That resolver
    # is the only reader of the carve-out, so the Airborne umbrella cannot
    # mean one thing here and another to the decision above.
    eligible_kinds = frozenset(KNOWN_CONTROL_KINDS) - resolve_excluded_kinds(
        declaration.get("excluded_control_kinds", ())
    )
    kept_downtime, _ = truncate_intervals(
        state["action_downtime_intervals"], float(action.time), eligible_kinds
    )
    state["action_downtime_intervals"] = kept_downtime
    kept_cc, _removed_cc = truncate_intervals(
        state["crowd_control_intervals"], float(action.time), eligible_kinds
    )
    state["crowd_control_intervals"] = kept_cc
    state["crowd_control_until"] = max(
        (float(interval.get("end", 0.0) or 0.0) for interval in kept_cc),
        default=0.0,
    )
    heal_entry = _cleanse_heal_entry(action, declaration)
    movement_receipt = movement_entry(declaration)
    state["cleanse"] = {
        **decision.public_receipt(),
        "decision": decision.public_receipt(),
        "heal": heal_entry,
        "movement": movement_receipt,
    }


def _write_gated_cleanse_use(
    _ctx: TransitionContext, action: SurvivalAction, holder_state: dict[str, Any]
) -> None:
    """Record the caster use receipt for a cleanse activation the walk
    gated (attacker_state_blocked) — the cast never happened, so the use is
    NOT consumed and ``fired_while_crowd_controlled`` is False."""
    try:
        item = resolve_cleanse_item(action.cleanse_item or action.source_key)
        declaration = item_declaration(item)
    except KeyError:
        # Unknown cleanse sources fail closed without inventing a receipt.
        return
    use = holder_state.setdefault("cleanse_uses", {}).setdefault(
        item,
        {
            "uses_remaining": 1,
            "activations": 0,
            "last_activation": None,
            "last_cleanse_group": None,
        },
    )
    # P2 Slice 7: a blocked multi-recipient cast writes its gated use
    # receipt ONCE per group (every fan-out packet hits the gate; the
    # first writes, the same-group rest skip).
    group = str(action.cleanse_group or "")
    if bool(group) and group == use.get("last_cleanse_group"):
        return
    use["activations"] += 1
    use["last_cleanse_group"] = group
    holder_state["cleanse_use"] = _cleanse_use_receipt(
        item, declaration, use, fired_while_crowd_controlled=False
    )


def _cleanse_action_view(
    action: SurvivalAction,
    item: str,
    target_id: str,
    holder_id: str,
    state: Mapping[str, Any],
) -> Any:
    """The kernel's typed view of one walk activation."""
    from types import SimpleNamespace

    return SimpleNamespace(
        time=action.time,
        source_key=action.source_key,
        sequence=action.sequence,
        event_id=EVENT_SLOTS.text(action.event_slot),
        item=item,
        target=target_id,
        holder=holder_id,
        cleanse_group=action.cleanse_group,
        active_controls=list(state["crowd_control_intervals"]),
    )


def _cleanse_use_receipt(
    item: str,
    declaration: Mapping[str, Any],
    use: Mapping[str, Any],
    *,
    fired_while_crowd_controlled: bool,
) -> dict[str, Any]:
    """The caster survival-row ``cleanse_use`` receipt."""
    return {
        "item": item,
        "uses_before": 1,
        "uses_after": int(use["uses_remaining"]),
        "cooldown_seconds": declaration.get("cooldown_seconds"),
        "cooldown_source_gap": bool(declaration.get("cooldown_source_gap", False)),
        "activations": int(use["activations"]),
        "fired_while_crowd_controlled": fired_while_crowd_controlled,
    }


def _cleanse_heal_entry(
    action: SurvivalAction, declaration: Mapping[str, Any]
) -> dict[str, Any] | None:
    """The heal entry attached to a Mikael's cleanse receipt (the heal is a
    SEPARATE effect with its own atoms; the amount is the packet's sourced
    level-scaled heal)."""
    heal = declaration.get("heal")
    if heal is None:
        return None
    return {
        "amount": max(0.0, float(action.amount)),
        "source": str(action.source or heal.get("source", "")),
        "source_atoms": [dict(atom) for atom in heal.get("source_atoms", ())],
    }


def _apply_temp_health(
    ctx: TransitionContext, action: SurvivalAction, state: dict[str, Any]
) -> None:
    """A sourced temporary-health grant raises maximum health for its
    authored duration; expiry clamps current health back down."""
    amount = max(0.0, action.amount)
    if amount <= 0.0 or action.duration <= 0.0:
        ctx.ledger.skip(action, "temporary_health_not_available")
        return
    state["pools"].max_health += amount
    state["pools"].health += amount
    state["temporary_health_received"] += amount
    state["temporary_health_amount"] += amount
    state["temporary_health_until"] = max(
        state["temporary_health_until"], action.time + action.duration
    )
    state["temporary_health_source"] = str(
        action.source or action.source_key or "Temporary Health"
    )
    ctx.ledger.write(
        action,
        expires_at=round(action.time + action.duration, 3),
        applied_amount=round(amount, 6),
    )


def _apply_heal(
    ctx: TransitionContext, action: SurvivalAction, state: dict[str, Any]
) -> None:
    """One heal/regen application: holder gates, live amount formula,
    received-healing modifiers (vamp carve-out), Grievous reduction, and
    the sourced excess conversions (temporary health, ichorshield,
    Severum overheal shield)."""
    event_time = action.time
    pools = state["pools"]
    if (
        action.requires_maw_lifeline_omnivamp
        and not state["maw_lifeline_omnivamp_active"]
    ):
        # P3 package 3T: the compiled walk pre-authors the post-Lifeline
        # omnivamp heals beside every outgoing damage packet; the kernel
        # gate keeps them inert until the threshold event arms the flag
        # (mirrors the receipt walk's trigger-time scheduling).
        ctx.ledger.skip(action, "maw_lifeline_not_active")
        return
    if (
        action.requires_holder_health_ratio > 0.0
        and pools.max_health > 0.0
        and pools.health
        <= pools.max_health * action.requires_holder_health_ratio + 1e-9
    ):
        ctx.ledger.skip(action, "holder_health_gate")
        return
    if action.requires_damage_free_seconds > 0.0 and recovery_is_gated(
        state, action, event_time
    ):
        ctx.ledger.skip(action, "damage_free_window_not_ready")
        return
    if action.requires_existing_shield:
        gate_subject = action.shield_gate_subject
        gate_time = (
            action.shield_gate_time
            if action.shield_gate_time is not None
            else event_time
        )
        shield_present = gate_subject >= 0 and ctx.shield_presence_at_time.get(
            (gate_subject, round(float(gate_time), 9)), False
        )
        if not shield_present:
            ctx.ledger.skip(action, "existing_shield_required")
            return
    amount = max(0.0, action.amount)
    amount_formula = action.amount_formula
    if callable(amount_formula):
        amount = max(0.0, float(amount_formula(pools.health, pools.max_health)))
    if action.amplified_recovery:
        # The CASTER's heal and shield power, not the recipient's: it
        # amplifies what this champion applies, its own self-heals
        # included. A caster without the stat factors 1.0 exactly.
        amount *= ctx.heal_power(action.attacker)
    if state["healing_received_multiplier"] != 1.0 or state["below_half_healing_bonus"]:
        # With no received-healing modifier armed, the multiplier is exactly
        # 1.0 for every category and the multiply is skipped bit-for-bit.
        amount *= recovery_multiplier(state, action)
    reduction_factor = live_healing_factor(state, event_time)
    reduced_amount = amount * reduction_factor
    state["healing_reduced"] += max(0.0, amount - reduced_amount)
    received = min(
        reduced_amount,
        max(0.0, pools.max_health - pools.health),
    )
    excess = max(0.0, reduced_amount - received)
    temporary_duration = max(0.0, action.temporary_health_duration)
    temporary_health = (
        excess
        if action.overheal_to_temporary_health
        and temporary_duration > 0.0
        and excess > 0.0
        else 0.0
    )
    leftover_excess = excess - temporary_health
    if leftover_excess > 0.0:
        ichor_converted = apply_ichorshield(ctx, state, action, leftover_excess)
        shield_converted = apply_overheal_shield(
            ctx,
            state,
            action,
            leftover_excess - ichor_converted,
            event_time,
        )
    else:
        ichor_converted = 0.0
        shield_converted = 0.0
    state["overhealing"] += (
        excess - temporary_health - ichor_converted - shield_converted
    )
    pools.health += received
    state["healing_received"] += received
    if temporary_health > 0.0:
        pools.max_health += temporary_health
        pools.health += temporary_health
        state["temporary_health_received"] += temporary_health
        state["temporary_health_amount"] += temporary_health
        state["temporary_health_until"] = max(
            state["temporary_health_until"], event_time + temporary_duration
        )
        state["temporary_health_source"] = str(
            action.source or action.source_key or "Temporary Health"
        )
        ctx.ledger.write(
            action,
            temporary_health=round(temporary_health, 6),
            temporary_health_expires_at=round(event_time + temporary_duration, 3),
        )
    if ctx.records_annotations:
        ctx.ledger.annotate(
            action,
            raw_amount=round(amount, 6),
            reduced_amount=round(reduced_amount, 6),
            healing_reduction_factor=round(reduction_factor, 6),
            overheal=round(
                excess - temporary_health - ichor_converted - shield_converted, 6
            ),
            **(
                {"overheal_shield": round(shield_converted, 6)}
                if shield_converted > 0.0
                else {}
            ),
        )
    ctx.ledger.write(action, applied_amount=round(received, 6))
    ctx.ledger.mark_applied(action)
    if action.defy_trigger_slot != NO_SLOT:
        state["defy_heal_received"] += received


def _apply_live_packet_chain(
    ctx: TransitionContext, action: SurvivalAction, state: dict[str, Any]
) -> float:
    """Port of the authoritative pre-phase packet repricing chain.

    Runs before the phase dispatch exactly like the receipt walk: combat-
    state stacks, dynamic-resistance repricing, cross-participant damage
    modifiers, source on-hit magic, and the Celestial Opposition incoming-
    damage multiplier.  Returns the evolving post-mitigation amount the
    damage section re-reads from the packet.
    """
    # The packet's damage is authoritative when the receipt adapter holds
    # the event: the Knight's Vow holder gate restores the direct share on
    # the event before this chain runs.
    event = action.event
    raw_amount = action.amount if event is None else event.get("damage", action.amount)
    amount = max(0.0, float(raw_amount or 0.0))
    if action.kind in _DAMAGE_KINDS and (
        ctx.stack_flags[action.subject]
        or state.get("aftershock_until", 0.0) > action.time
    ):
        update_combat_state(ctx, action, state)
    if action.declared is not None:
        # The packet's family declared its own price, so the walk mitigates
        # the raw value here instead of re-ratioing a number the pair engine
        # mitigated.  It reads the armed delta the line above may just have
        # written, and it replaces the reprice rather than preceding it: a
        # declaration priced at the live resistance has nothing left to
        # re-price.  Every family in ``walk_repriced_mechanics()`` declares one.
        priced = apply_declared_price(ctx, action, state)
        if priced is not None:
            amount = priced
    elif (
        state.get("dynamic_bonus_armor")
        or state.get("dynamic_bonus_magic_resistance")
        or state.get("aftershock_until", 0.0) > action.time
    ):
        # Only a combat-state stack holder ever arms a dynamic delta; the
        # reprice call is skipped while both deltas are absent or zero.
        repriced = reprice_dynamic_resistance(ctx, action, state)
        if repriced is not None:
            amount = repriced
    # Live cross-participant modifiers apply after the pair engine's
    # sourced mitigation and before shields/health.  Flat Dream Maker
    # reduction is post-mitigation; Imperial-style all-source modifiers
    # multiply the remaining packet.  Both consume only an authored
    # duration/trigger and therefore never become permanent item stats.
    # No armed modifiers is the overwhelmingly common walk state; skip the
    # per-packet list rebuild entirely then.
    if state["active_damage_modifiers"]:
        amount = _apply_cross_participant_modifiers(ctx, action, state, amount)
    attacker = action.attacker
    states = ctx.states
    source_state = states[attacker] if 0 <= attacker < len(states) else None
    if source_state is not None and source_state["active_on_hit_magic"]:
        amount = _apply_source_on_hit_magic(action, source_state, amount)
    amount = _apply_projectile_damage_defense(ctx, action, state, amount)
    # Celestial Opposition's Blessed reduction is a target-state modifier,
    # not a basic-attack modifier.  Apply it to authored champion damage
    # after the pair engine's resistance math and refresh the exact
    # lingering window from the hit timestamp.  Reactive item packets are
    # excluded so a shield or thorns return cannot manufacture a new
    # champion-hit window.
    if (
        state["incoming_damage_multiplier"] < 1.0
        and action.phase >= TransitionRank.DAMAGE
        and 0 <= attacker < len(ctx.combatants)
        and attacker != action.subject
        and not action.reactive
        and action.damage_type in {"physical", "magic", "true"}
        and action.time < state["incoming_damage_until"]
    ):
        reduction = state["incoming_damage_multiplier"]
        original_incoming = max(0.0, amount)
        amount = original_incoming * reduction
        if ctx.records_annotations:
            ctx.ledger.annotate(
                action,
                incoming_damage_multiplier=round(reduction, 6),
                incoming_damage_source=state["incoming_damage_source"],
                incoming_damage_reduction=round(original_incoming - amount, 6),
            )
        if state["incoming_damage_linger"] > 0.0:
            state["incoming_damage_until"] = (
                action.time + state["incoming_damage_linger"]
            )
        if state["incoming_damage_cooldown"] > 0.0:
            state["incoming_damage_cooldown_until"] = max(
                state["incoming_damage_cooldown_until"],
                action.time + state["incoming_damage_cooldown"],
            )
    if action.live_amp is not None and action.kind in _DAMAGE_KINDS:
        amount = _apply_live_amp(ctx, action, state, amount)
    return amount


def _interaction_event_key(action: SurvivalAction) -> str:
    """Build a stable identity for one projectile interaction packet."""
    return stable_event_key(action)


def _record_event_id_match(state: dict[str, Any], action: SurvivalAction) -> None:
    """Record one applied event whose id was selected by event id.

    Only exact event-id selections count; a source-slot match does not clear
    a selected id from the unmatched receipt.
    """
    eligibility = state.get("projectile_defense_eligibility")
    if eligibility is None or not eligibility.selection.blocked_event_ids:
        return
    event_id = EVENT_SLOTS.text(action.event_slot)
    if event_id in eligibility.selection.blocked_event_ids:
        state.setdefault("projectile_defense_event_id_matches", set()).add(event_id)


def _prepare_full_block(
    ctx: TransitionContext, action: SurvivalAction, state: dict[str, Any]
) -> None:
    """Apply a selected full-block defense before a spell shield gate.

    Eligibility is delegated to the delivery-eligibility kernel
    (window + selection + delivery acceptance); the composition rules
    declare the full-block mode and the finite use budget.  The applied
    semantics are unchanged: Braum's first selected hit is fully
    blocked and consumes the one-use budget; later selected hits fall
    through to the reduction path.
    """
    defense = state.get("projectile_defense")
    eligibility = state.get("projectile_defense_eligibility")
    composition = state.get("projectile_defense_composition")
    attacker = (
        ctx.combatants[action.attacker]
        if 0 <= action.attacker < len(ctx.combatants)
        else None
    )
    if (
        defense is None
        or eligibility is None
        or composition is None
        or composition.full_block.mode == "none"
        or (
            action.damage_type == "true"
            and not composition.full_block.blocks_true_damage
        )
        or (action.amount <= 0.0 and action.kind is not ActionKind.CROWD_CONTROL)
        or not eligibility.decide(action, attacker).eligible
        or (
            bool(getattr(action, "area_damage", False))
            and composition.reduction.area_damage_reduction > 0.0
        )
        or (
            composition.full_block.mode == "first"
            and (
                state["projectile_defense_uses_remaining"] is None
                or state["projectile_defense_uses_remaining"] <= 0
            )
        )
    ):
        return
    key = _interaction_event_key(action)
    if composition.full_block.mode == "first":
        remaining = state["projectile_defense_uses_remaining"]
        if remaining is not None:
            state["projectile_defense_uses_remaining"] = remaining - 1
    state["projectile_defense_full_block_events"].add(key)
    state["projectile_defense_blocked"].append(
        {
            "time": round(float(action.time), 3),
            "source": action.source_key,
            "mode": "full_block",
        }
    )
    _record_event_id_match(state, action)
    decision = eligibility.decide(action, attacker)
    ctx.ledger.write(
        action,
        projectile_defense={
            "source": defense.source,
            "mode": "full_block",
            "delivery": decision.delivery.public_receipt(),
            "eligible": True,
            "remaining_uses": state["projectile_defense_uses_remaining"],
        },
    )


def _apply_projectile_damage_defense(
    ctx: TransitionContext,
    action: SurvivalAction,
    state: dict[str, Any],
    amount: float,
) -> float:
    """Apply a selected projectile or parry defense after pair mitigation.

    The reduction value comes from the kernel composition rule:
    ``ReductionRule.reduction_for`` uses the defense's own area
    reduction only when one is declared (Jax), so Braum's later-hit
    reduction now also applies to area-marked skillshots (Trueshot
    Barrage is intercepted in-game) instead of emitting a misleading
    "reduced by 0.0" receipt.
    """
    defense = state.get("projectile_defense")
    eligibility = state.get("projectile_defense_eligibility")
    composition = state.get("projectile_defense_composition")
    attacker = (
        ctx.combatants[action.attacker]
        if 0 <= action.attacker < len(ctx.combatants)
        else None
    )
    if (
        defense is None
        or eligibility is None
        or composition is None
        or (
            action.damage_type == "true"
            and not composition.reduction.applies_to_true_damage
        )
        or not eligibility.decide(action, attacker).eligible
    ):
        return amount
    key = _interaction_event_key(action)
    if key in state["projectile_defense_full_block_events"]:
        return 0.0
    before = max(0.0, amount)
    reduction = composition.reduction.reduction_for(action)
    after = before * max(0.0, 1.0 - reduction)
    _record_event_id_match(state, action)
    ctx.ledger.write(
        action,
        projectile_defense={
            "source": defense.source,
            "mode": "reduced",
            "reduction": round(reduction, 6),
            "mitigated": round(before - after, 6),
            "delivery": eligibility.decide(action, attacker).delivery.public_receipt(),
            "eligible": True,
            "remaining_uses": state["projectile_defense_uses_remaining"],
        },
    )
    return after


def _sync_crowd_control_immunity(state: dict[str, Any], event_time: float) -> None:
    """Re-derive the single-slot immunity projection and the ended reason.

    The exact ledger entry (via :func:`immunity_holder`) is the only
    authority: expiry or depletion clears the projection immediately and
    records the named ended reason ("expired" / "drained").
    """
    grants = state.get("crowd_control_immunity_grants", ())
    if grants:
        latest = grants[-1]
        if latest.get("ended_reason") is None:
            holder = immunity_holder(state["pools"], latest["source"], event_time)
            if holder is None:
                latest["ended_reason"] = (
                    "expired"
                    if float(latest["expires_at"]) <= event_time + 1e-9
                    else "drained"
                )
        holder = immunity_holder(state["pools"], latest["source"], event_time)
        if holder is None:
            state["crowd_control_immunity_until"] = 0.0
            state["crowd_control_immunity_source"] = ""
        else:
            state["crowd_control_immunity_until"] = max(
                state["crowd_control_immunity_until"], float(holder.expires_at)
            )
            state["crowd_control_immunity_source"] = latest["source"]
        return
    state["crowd_control_immunity_until"] = 0.0
    state["crowd_control_immunity_source"] = ""


# P2 Slice 8 — the sourced passive values (Dr. Mundo Goes Where He
# Pleases): 4% CURRENT health cost, 4% MAX health pickup heal, 15s
# pickup cooldown refund, 525-unit canister range, 7s canister lifetime,
# 115-unit pickup radius (game DrMundoP DataValues; the wiki prose
# corroborates the 4%/525/7 values).  The trigger scope (hostile
# immobilizing effect), the enemy-destroy rule and the respawn reset are
# wiki-prose-only (scripted in the uncached game Lua).
_MUNDO_P_ITEM = "Dr. Mundo P"
_MUNDO_P_HEALTH_COST_RATIO = 0.04
_MUNDO_P_PICKUP_HEAL_RATIO = 0.04
_MUNDO_P_COOLDOWN_REFUND_SECONDS = 15.0
_MUNDO_P_CANISTER_RANGE = 525.0
_MUNDO_P_CANISTER_LIFETIME = 7.0
_MUNDO_P_COOLDOWN_ROW = (60.0, 15.0)


def _apply_mundo_p_resist(
    ctx: TransitionContext,
    action: SurvivalAction,
    state: dict[str, Any],
    profile: Any,
) -> None:
    """Resist one hostile immobilizing control through the armed passive.

    The control never applies: no interval, no downtime, no
    ``crowd_control_until`` change — an IMMUNITY, never a truncation
    (removed_controls [] and downtime_before == downtime_after == 0).
    The 4%-CURRENT-health cost is paid with the shared lethal
    bookkeeping; the canister drop is receipted (525 units / 7s lifetime
    / 115 pickup radius / 15s pickup refund); the pickup heal + the
    enemy-destroy timing are NAMED unsupported (no movement simulation —
    no auto-pickup, no user toggle).  The latch disarms; same-cast-
    instance follow-up controls are blocked with a receipt and no second
    cost (the wiki notes: immunity to additional immobilizing effects
    from the same cast instance).
    """
    pools = state["pools"]
    current_health = max(0.0, float(pools.health))
    cost = min(current_health, _MUNDO_P_HEALTH_COST_RATIO * current_health)
    pools.health = max(0.0, float(pools.health) - cost)
    event_time = float(action.time)
    if pools.health <= 0.0 and state["death_time"] is None:
        if state["first_death_time"] is None:
            state["first_death_time"] = float(event_time)
        trigger_defy(
            ctx, ctx.combatants[action.subject].participant_id, float(event_time)
        )
        state["death_time"] = min(float(ctx.duration), event_time)
        state["terminal_phase"] = "dead"
        state["action_downtime_intervals"].append(
            {
                "kind": "death",
                "start": float(event_time),
                "end": float(ctx.duration),
                "source": str(action.source or action.source_key or "Death"),
            }
        )
        arm_revive_stasis(state, float(event_time))
    resist = state["mundo_p_resist"]
    resist["armed"] = False
    resist["last_ability_instance"] = action.ability_instance
    resist["activated"] = True
    subject_name = (
        ctx.combatants[action.subject].participant_id
        if 0 <= action.subject < len(ctx.combatants)
        else ""
    )
    attacker_name = (
        ctx.combatants[action.attacker].participant_id
        if 0 <= action.attacker < len(ctx.combatants)
        else ""
    )
    max_health = max(0.0, float(pools.max_health))
    decision = {
        "eligible": True,
        "reason": "",
        "item": _MUNDO_P_ITEM,
        "activation_time": round(event_time, 3),
        "target": subject_name,
        "active_controls_before": [],
        "removed_controls": [],
        "rejected_controls": [],
        "intervals_after": [dict(i) for i in state["crowd_control_intervals"]],
        "downtime_before": 0.0,
        "downtime_after": 0.0,
        "use_consumed": True,
    }
    state["cleanse"] = {
        **decision,
        "decision": decision,
        "heal": None,
        "movement": None,
    }
    state["cleanse_use"] = {
        "item": _MUNDO_P_ITEM,
        "uses_before": 1,
        "uses_after": 0,
        "cooldown_seconds": list(_MUNDO_P_COOLDOWN_ROW),
        "cooldown_source_gap": False,
        "activations": 1,
        "fired_while_crowd_controlled": False,
    }
    state["passive_cost"] = {
        "percent": _MUNDO_P_HEALTH_COST_RATIO * 100.0,
        "amount": round(cost, 6),
        "health_before": round(current_health, 6),
        "health_after": round(max(0.0, float(pools.health)), 6),
    }
    state["canister"] = {
        "time": round(event_time, 3),
        "distance": _MUNDO_P_CANISTER_RANGE,
        "lifetime": _MUNDO_P_CANISTER_LIFETIME,
        "source": _MUNDO_P_ITEM,
        "destruction": {
            "supported": False,
            "reason": "enemy movement not modeled",
        },
    }
    state["pickup"] = {
        "supported": False,
        "reason": (
            "the canister pickup needs Mundo's movement (no auto-pickup, "
            "no user toggle)"
        ),
        "heal_percent": _MUNDO_P_PICKUP_HEAL_RATIO * 100.0,
        "heal_amount": round(_MUNDO_P_PICKUP_HEAL_RATIO * max_health, 6),
        "cooldown_refund": _MUNDO_P_COOLDOWN_REFUND_SECONDS,
    }
    resisted_row = {
        "time": round(event_time, 3),
        "attacker": attacker_name,
        "source_key": str(action.source_key or ""),
        "control_kind": str(profile.kind),
        "health_cost": round(cost, 6),
        "canister": dict(state["canister"]),
    }
    state.setdefault("crowd_control_resisted", []).append(resisted_row)
    ctx.ledger.write(
        action,
        crowd_control_resisted=dict(resisted_row),
        health_cost=round(cost, 6),
        canister=dict(state["canister"]),
        pickup=dict(state["pickup"]),
    )


def _apply_crowd_control_resist(
    ctx: TransitionContext, action: SurvivalAction, state: dict[str, Any]
) -> None:
    """Arm Dr. Mundo's passive immunity (one-shot per fight).

    The cooldown 60 -> 15 (wiki row; the game's step function agrees at
    levels 1 and 18 — flagged) is receipted, never enforced; the 15s
    pickup refund likewise.  A second arm in one fight is a no-op
    receipt (the cooldown is longer than any fight window).
    """
    duration = max(0.0, float(action.duration or 0.0))
    if duration > 0.0:
        # P2 Slice 9 (Olaf Ragnarok): the duration-armed immunity window
        # [cast, cast + duration) — blocks EVERY hostile blocking control
        # inside the window (no cost, no latch-off — the window is the
        # state); the cleanse + stat receipts are separate packets.
        event_time = float(action.time)
        state["ragnarok_immunity"] = {
            "source": "Olaf R — Ragnarok",
            "start": round(event_time, 6),
            "until": round(event_time + duration, 6),
            "blocked": [],
            "decisions": [],
            "ended_reason": None,
        }
        ctx.ledger.write(
            action,
            ragnarok_immunity_armed=True,
            until=round(event_time + duration, 6),
        )
        return
    resist = state.get("mundo_p_resist")
    if resist is not None:
        ctx.ledger.write(
            action,
            crowd_control_resist_armed=False,
            reason="already_armed_or_spent",
        )
        return
    level = 1
    if 0 <= action.subject < len(ctx.combatants):
        level = max(1, int(getattr(ctx.combatants[action.subject], "level", 1) or 1))
    cooldown_seconds = (
        _MUNDO_P_COOLDOWN_ROW[level - 1]
        if 0 <= level - 1 < len(_MUNDO_P_COOLDOWN_ROW)
        else _MUNDO_P_COOLDOWN_ROW[-1]
    )
    state["mundo_p_resist"] = {
        "armed": True,
        "activated": False,
        "last_ability_instance": None,
        "cooldown_seconds": cooldown_seconds,
    }
    state["passive_state"] = {"armed": True}
    state["passive_cooldown"] = {
        "seconds": cooldown_seconds,
        "affected_by_cdr": False,
        "refund_on_pickup": _MUNDO_P_COOLDOWN_REFUND_SECONDS,
        "row": list(_MUNDO_P_COOLDOWN_ROW),
        "note": "the wiki row interpolates 60 -> 15 linearly; the game "
        "step function (60/51/42/33/24/15 by level 1/4/7/10/13/16) "
        "agrees at levels 1 and 18 — receipted, never enforced",
    }
    ctx.ledger.write(
        action,
        crowd_control_resist_armed=True,
        passive_cooldown=dict(state["passive_cooldown"]),
    )


def _apply_crowd_control(
    ctx: TransitionContext,
    action: SurvivalAction,
    state: dict[str, Any],
    applied_amount: float,
) -> None:
    """Arm the target's action lock from an authored control packet.

    The immunity gate is the typed crowd-control eligibility contract
    (P2 Slice 3): ONE decision for damage-attached AND control-only
    packets, tied to the exact Black Shield ledger entry.  A blocked
    control adds NO action downtime; the extended
    ``crowd_control_blocked`` receipt carries the decision and the
    shield amount before (and, after absorption, the amount after).  A
    denied decision (outside window / holder drained / holder expired)
    falls through to the pinned downtime application; an unknown kind is
    receipted as the denial but never applied (the model has no downtime
    semantics for it).
    """
    profile = classify_control(action)
    if not profile.kind:
        return
    duration = max(0.0, float(action.cc_duration))
    if duration <= 0.0:
        return
    # A *damage* packet mitigated to nothing carries no control with it; a
    # control-ONLY packet declares no damage in the first place and is not
    # the same case.  The guard reads the packet's own declaration to tell
    # them apart, because the coupled walk classifies a zero-damage control
    # as a plain damage action (its authored kind is empty) and a bare
    # ``applied_amount <= 0`` test silently dropped every one of them --
    # Lulu's Whimsy against a Black Shield among them.
    if applied_amount <= 0.0 and action.amount > 0.0:
        return
    if not profile.blocking and not profile.unknown:
        # A known soft control (slow, silence, ...): no action-downtime
        # model — pinned pass-through, never an immunity decision.
        return
    grants = state.get("crowd_control_immunity_grants", ())
    if grants:
        grant = grants[-1]
        eligibility = state.get("crowd_control_immunity_eligibility")
        holder = immunity_holder(state["pools"], grant["source"], action.time)
        decision = (
            eligibility.decide(action, holder=holder)
            if eligibility is not None
            else CrowdControlDecision(
                eligible=False,
                reason="shield_not_held",
                control=profile,
                shield_source=grant["source"],
                event_key=stable_event_key(action),
            )
        )
        state.setdefault("crowd_control_immunity_decisions", []).append(
            decision.public_receipt()
        )
        _sync_crowd_control_immunity(state, action.time)
        if decision.eligible:
            state.setdefault("crowd_control_immunity_blocked", []).append(
                {
                    "time": round(float(action.time), 3),
                    "source": action.source_key,
                    "control_kind": profile.kind,
                    "shield_amount_before": decision.public_receipt()[
                        "shield_amount_before"
                    ],
                    "shield_amount_after": (
                        decision.public_receipt()["shield_amount_before"]
                        if action.amount <= 0.0
                        else None
                    ),
                    "active_until": round(decision.active_until, 6),
                    "event_key": decision.event_key,
                }
            )
            ctx.ledger.write(
                action,
                crowd_control_blocked={
                    "source": grant["source"],
                    "until": round(decision.active_until, 6),
                    "decision": decision.public_receipt(),
                    "shield_amount_after": (
                        decision.public_receipt()["shield_amount_before"]
                        if action.amount <= 0.0
                        else None
                    ),
                },
            )
            ctx.ledger.mark_applied(action)
            return
        # Denied with a named reason: the decision receipt is the
        # observable denial.  Unknown kinds never apply (pinned); the
        # in-window denials (outside_window / shield_not_held) apply the
        # control below exactly like an unshielded packet.
        ctx.ledger.annotate(
            action, crowd_control_immunity_decision=decision.public_receipt()
        )
        if decision.reason == "unknown_control":
            return
    # P2 Slice 8 (Dr. Mundo Goes Where He Pleases): the passive IMMUNITY
    # gate — an armed resist consumes the NEXT hostile immobilizing
    # control BEFORE it applies (no interval, no downtime, no until
    # change — never a truncation).  Spell shield / Black Shield take
    # priority (the grants block above ran first).  The 4%-current-
    # health cost + the canister drop are receipted; the pickup /
    # destruction timings are named unsupported (no movement model).
    # P2 Slice 9 (Olaf Ragnarok): the 3s immunity window — blocks every
    # hostile BLOCKING control inside [start, until) (the end-exclusive
    # Slice 3 convention), including the displacement family (Trait_
    # CCImmune); the cleanse's displacement carve-out applies only to
    # already-active controls, not new ones.
    ragnarok = state.get("ragnarok_immunity")
    if (
        ragnarok
        and profile.blocking
        and not profile.unknown
        and float(action.time) < float(ragnarok.get("until", 0.0))
    ):
        attacker_team = ""
        subject_team = ""
        if 0 <= action.attacker < len(ctx.combatants):
            attacker_team = str(getattr(ctx.combatants[action.attacker], "team", ""))
        if 0 <= action.subject < len(ctx.combatants):
            subject_team = str(getattr(ctx.combatants[action.subject], "team", ""))
        hostile = bool(attacker_team) and attacker_team != subject_team
        if hostile:
            blocked_row = {
                "time": round(float(action.time), 3),
                "source_key": str(action.source_key or ""),
                "control_kind": str(profile.kind),
            }
            ragnarok.setdefault("blocked", []).append(blocked_row)
            ctx.ledger.write(action, ragnarok_blocked=dict(blocked_row))
            ctx.ledger.mark_applied(action)
            return
    resist = state.get("mundo_p_resist")
    if resist and resist.get("armed") and profile.blocking and not profile.unknown:
        attacker_team = ""
        subject_team = ""
        if 0 <= action.attacker < len(ctx.combatants):
            attacker_team = str(getattr(ctx.combatants[action.attacker], "team", ""))
        if 0 <= action.subject < len(ctx.combatants):
            subject_team = str(getattr(ctx.combatants[action.subject], "team", ""))
        hostile = bool(attacker_team) and attacker_team != subject_team
        if hostile:
            _apply_mundo_p_resist(ctx, action, state, profile)
            ctx.ledger.mark_applied(action)
            return
    until = float(action.time + duration)
    state["crowd_control_until"] = max(state["crowd_control_until"], until)
    state["crowd_control_intervals"].append(
        {
            "kind": action.cc_kind or "crowd_control",
            "start": float(action.time),
            "end": until,
            "source": str(action.source or action.source_key or "Crowd control"),
        }
    )
    state["action_downtime_intervals"].append(
        {
            "kind": action.cc_kind or "crowd_control",
            "start": float(action.time),
            "end": until,
            "source": str(action.source or action.source_key or "Crowd control"),
        }
    )
    ctx.ledger.write(
        action,
        crowd_control={
            "kind": action.cc_kind or "crowd_control",
            "duration": round(duration, 6),
            "until": round(until, 6),
        },
    )
    ctx.ledger.mark_applied(action)


def _apply_live_amp(
    ctx: TransitionContext,
    action: SurvivalAction,
    state: Mapping[str, Any],
    amount: float,
) -> float:
    """Price a live-predicate amplifier on this packet, before absorption.

    Last in the chain, which is the ruling: the predicate reads the
    subject's health as it stands *before* this packet is absorbed, and
    the bonus amplifies the packet as everything else in the chain has
    already left it.  A rider, not an event — so it never arrives at a
    subject its host did not reach: a spell-shielded, state-blocked or
    post-death packet never enters the damage branch at all, and the bonus
    dies with it because it is a field on the packet rather than a
    transition of its own.

    The tag carries the meaning (:class:`~.actions.LiveProbe`).  An
    unrecognised probe raises rather than declining to amplify, because a
    kernel that quietly skipped an amplifier it did not recognise is a
    number the model never computed wearing a measured zero's clothes.
    """
    live = action.live_amp
    if live.probe is not LiveProbe.HEALTH_BELOW_RATIO:
        raise ValueError(
            f"{live.mechanic} rides a {live.probe!r} the walk cannot read; "
            "the kernel evaluates a live amplifier by tag and a tag it does "
            "not know is a rule that did not run, never a bonus of zero"
        )
    pools = state["pools"]
    if not pools.health < pools.max_health * live.threshold:
        return amount
    bonus = amount * live.fraction
    # Unrounded, both of them: rounding is presentation and its one home is
    # ``program/precision`` (D-71).  The receipt projection rounds what it
    # publishes, and the kernel's own rounding-site count is frontier
    # counter 6, which this stage may not push up.
    ctx.ledger.write(action, live_amp_bonus=bonus, live_amp_source=live.mechanic)
    if ctx.records_annotations:
        ctx.ledger.annotate(
            action,
            live_amp={
                "mechanic": live.mechanic,
                "fraction": live.fraction,
                "threshold": live.threshold,
                "health_ratio": (
                    pools.health / pools.max_health if pools.max_health else 0.0
                ),
                "bonus": bonus,
            },
        )
    return amount + bonus


def _modifier_applies(
    modifier: Mapping[str, Any], action: SurvivalAction, source_id: str
) -> bool:
    """Whether one armed cross-participant modifier prices this packet.

    The one predicate every modifier branch consults.  Four clauses:

    * the **owner skip**: the originating holder's pair engine already
      priced its own half, so the packet exists for every other source;
    * the **declared class match**: a magic-only curse does not amplify a
      true-damage ability, which is what ``damage_classes`` says;
    * the **source restriction**: ``source_participant`` prices, ``holder`` arms;
    * the **delivery gate**: attacks and spells only, unless the modifier
      declared ``all_sources``.  Not ``attack_classes``: a modifier declaring
      all three classes still leaves ``AttackClass.OTHER`` unpriced.
    """
    holder = modifier["holder"]
    if holder >= 0 and holder == action.attacker:
        return False
    source_participant = str(modifier.get("source_participant", ""))
    if source_participant and source_participant != source_id:
        return False
    if damage_class_of(action) not in modifier["damage_classes"]:
        return False
    if not modifier.get("all_sources") and not (
        action.is_ability or action.basic_attack or action.source_key == "auto_attacks"
    ):
        return False
    return attack_class_of(action) in modifier["attack_classes"]


def _apply_cross_participant_modifiers(
    ctx: TransitionContext,
    action: SurvivalAction,
    state: dict[str, Any],
    amount: float,
) -> float:
    """Apply the armed cross-participant damage modifiers to one packet."""
    active_modifiers = [
        modifier
        for modifier in state["active_damage_modifiers"]
        if float(modifier.get("until", 0.0)) > action.time
    ]
    state["active_damage_modifiers"] = active_modifiers
    # Resolved only when some armed modifier actually restricts its source.
    # The restriction compares participant-id strings, so answering it costs
    # a roster read this function otherwise never makes -- and the walk's
    # own fixtures hand it a context that carries a ledger and nothing else.
    source_id = (
        ctx.combatants[action.attacker].participant_id
        if any(modifier.get("source_participant") for modifier in active_modifiers)
        and 0 <= action.attacker < len(ctx.combatants)
        else ""
    )
    for modifier in list(active_modifiers):
        if not _modifier_applies(modifier, action, source_id):
            continue
        resistance_key = str(modifier.get("resistance_type", ""))
        reduction_key = (
            "armor_reduction_percent"
            if resistance_key == "armor"
            else (
                "mr_reduction_percent"
                if resistance_key in {"mr", "magic_resistance"}
                else ""
            )
        )
        if reduction_key:
            # Which resistance the reduction touches is a separate fact from
            # the modifier's declared damage classes: a packet may restrict
            # itself to two classes and still reduce only one resistance.
            relevant_type = "physical" if reduction_key.startswith("armor") else "magic"
            if action.damage_type != relevant_type:
                continue
            baseline = (
                action.baseline_effective_armor
                if reduction_key.startswith("armor")
                else action.baseline_effective_mr
            )
            if baseline is None:
                ctx.ledger.write(
                    action, support_resistance_reduction_unavailable=reduction_key
                )
                continue
            percentage = max(
                0.0,
                min(1.0, float(modifier.get(reduction_key, 0.0) or 0.0)),
            )
            before = max(0.0, amount)
            baseline_factor = apply_resistance(1.0, baseline)
            reduced_factor = apply_resistance(
                1.0, max(0.0, baseline * (1.0 - percentage))
            )
            if baseline_factor > 0.0:
                amount = before * reduced_factor / baseline_factor
                if action.event is not None:
                    action.event.setdefault("support_resistance_reduction", []).append(
                        {
                            "source": modifier["source"],
                            "type": reduction_key,
                            "fraction": round(percentage, 6),
                            "factor": round(reduced_factor / baseline_factor, 6),
                        }
                    )
            continue
        if modifier.get("damage_reduction"):
            before = max(0.0, amount)
            reduction = min(before, max(0.0, float(modifier.get("reduction", 0.0))))
            amount = before - reduction
            ctx.ledger.write(
                action,
                support_damage_reduction={
                    "source": modifier["source"],
                    "amount": round(reduction, 6),
                },
            )
            if modifier.get("next_event_only"):
                active_modifiers.remove(modifier)
        else:
            factor = max(0.0, float(modifier.get("multiplier", 1.0) or 1.0))
            before = max(0.0, amount)
            amount = before * factor
            ctx.ledger.write(
                action,
                support_damage_multiplier={
                    "source": modifier["source"],
                    "multiplier": round(factor, 6),
                },
            )
    return amount


def _apply_source_on_hit_magic(
    action: SurvivalAction, source_state: dict[str, Any], amount: float
) -> float:
    """Add the attacker's armed on-hit magic bonuses to one packet."""
    active_on_hit = [
        bonus
        for bonus in source_state["active_on_hit_magic"]
        if float(bonus.get("until", 0.0)) > action.time
    ]
    source_state["active_on_hit_magic"] = active_on_hit
    if action.basic_attack or action.source_key == "auto_attacks" or action.is_ability:
        for bonus in list(active_on_hit):
            raw_bonus = max(0.0, float(bonus.get("amount", 0.0) or 0.0))
            if raw_bonus <= 0.0:
                continue
            effective_mr = action.baseline_effective_mr or 0.0
            bonus_damage = apply_resistance(raw_bonus, effective_mr)
            amount = max(0.0, amount) + bonus_damage
            if action.event is not None:
                action.event.setdefault("support_on_hit_magic", []).append(
                    {
                        "source": bonus["source"],
                        "raw": round(raw_bonus, 6),
                        "mitigated": round(bonus_damage, 6),
                    }
                )
            if bonus.get("next_event_only"):
                active_on_hit.remove(bonus)
    return amount


def _apply_damage(
    ctx: TransitionContext, action: SurvivalAction, state: dict[str, Any]
) -> None:
    """The full damage application: the shared packet chain first (combat
    stacks, repricing, modifiers, on-hit, incoming multiplier), then the
    shield/health resolution.  The plain-damage fast branch reads none of
    the four fields it cannot carry: trigger, live formula, Grievous pack,
    wound."""
    event_time = action.time
    event_slot = action.event_slot
    ledger = ctx.ledger
    pools = state["pools"]
    amount = _apply_live_packet_chain(ctx, action, state)
    ledger.mark_applied(action)
    _apply_crowd_control(ctx, action, state, amount)
    if action.deferred:
        batch_slot = action.deferred_batch_slot
        if batch_slot in state["deferred_batches"]:
            state["deferred_batches"][batch_slot] = max(
                0.0, state["deferred_batches"][batch_slot] - amount
            )
            state["damage_deferral_pending"] = max(
                0.0, state["damage_deferral_pending"] - amount
            )
            if state["deferred_batches"][batch_slot] <= 1e-9:
                del state["deferred_batches"][batch_slot]
    original_amount = amount
    if action.kind is not ActionKind.PLAIN_DAMAGE:
        raw_formula = action.raw_formula
        raw_damage = action.raw_damage
        if callable(raw_formula) and raw_damage > 0 and pools.max_health > 0:
            # The one-attacker engine prices a target-health formula against
            # that pair's full-health target.  Re-price only the sourced
            # health-dependent component here; all typed mitigation and item
            # amplifiers remain represented by the original damage/raw ratio.
            missing_ratio = max(
                0.0,
                min(1.0, 1.0 - pools.health / pools.max_health),
            )
            try:
                live_raw = evaluate_live_raw_formula(
                    raw_formula, missing_ratio, pools.max_health
                )
            except (TypeError, ValueError):
                live_raw = raw_damage
            amount *= live_raw / raw_damage
    if ctx.records_annotations:
        ctx.ledger.annotate(
            action,
            pair_damage=round(original_amount, 6),
            live_damage=round(amount, 6),
        )
    # Serpent's Fang venom rides every damaging hit: it applies before
    # any shield the same hit grants (threshold lifeline, reactive
    # barriers) and refreshes the window on each successive hit.
    venom_profiles = ctx.venom_profiles
    venom_profile = (
        venom_profiles[action.attacker]
        if venom_profiles is not None and 0 <= action.attacker < len(venom_profiles)
        else None
    )
    if venom_profile is not None and amount > 0.0:
        venom_keep, venom_duration = venom_profile
        state["venom_until"] = max(
            state["venom_until"], float(event_time) + venom_duration
        )
        pools.venom_factor = min(pools.venom_factor, venom_keep)
        state["venom_events"].append(
            {
                "time": round(float(event_time), 3),
                "until": round(state["venom_until"], 3),
                "factor": round(pools.venom_factor, 6),
            }
        )
        if ctx.records_annotations:
            ctx.ledger.annotate(
                action,
                venom={
                    "factor": round(pools.venom_factor, 6),
                    "until": round(state["venom_until"], 6),
                },
            )
    damage_type = action.damage_type
    # Absorption order, Lifeline arming, and the health transition are owned
    # by ``shield_ledger``; this kernel supplies the storage and the ledger
    # annotations, never a second copy of the semantics.
    outcome = shield_ledger.absorb(
        pools,
        amount,
        damage_type,
        event_time,
        live_healing_factor(state, event_time),
    )
    if state.get("crowd_control_immunity_grants"):
        _sync_crowd_control_immunity(state, event_time)
        _fill_blocked_shield_after(state, action, outcome.absorbed)
    event_absorbed = outcome.absorbed
    applied_to_health = outcome.applied_to_health
    if outcome.threshold_shield_triggered:
        ctx.ledger.write(action, threshold_shield_triggered=True)
        expires_at = outcome.threshold_shield_expires_at
        if expires_at is not None and math.isfinite(expires_at):
            ctx.ledger.write(action, threshold_shield_expires_at=round(expires_at, 3))
        if state["maw_lifeline_omnivamp_percent"] > 0.0:
            state["maw_lifeline_omnivamp_active"] = True
            ctx.ledger.write(
                action,
                maw_lifeline_omnivamp_activated=round(
                    state["maw_lifeline_omnivamp_percent"], 6
                ),
            )
    if outcome.threshold_health_triggered:
        # The kernel granted the temporary maximum health and delivered
        # whatever of the sourced heal the arming instant could take; this
        # walk has no over-time author for the remainder.  A wound live at
        # the arming instant already cut that heal inside the kernel.
        state["healing_received"] += outcome.threshold_health_healed
        state["healing_reduced"] += outcome.threshold_health_reduced
        ctx.ledger.write(action, threshold_health_triggered=True)
    if ctx.records_annotations:
        ctx.ledger.annotate(action, overkill=round(outcome.overkill, 6))
    # The packet's post-mitigation value is replaced with the amount that
    # actually consumed the target's shield/health.  Keep ``pair_damage``
    # and ``live_damage`` above for diagnostics without letting overkill
    # inflate team-fight TTD or BIS scores.
    event_damage = round(event_absorbed + applied_to_health, 6)
    if ctx.records_event_fields:
        ledger.write(
            action,
            damage=event_damage,
            _applied_to_health=round(applied_to_health, 6),
        )
    else:
        ledger.write(action, damage=event_damage)
    if event_damage > 0.0:
        state["last_damage_time"] = float(event_time)
        _record_guardian_damage(ctx, action, event_time, event_damage)
        if ctx.regeneration_flags[action.subject]:
            schedule_regeneration_recovery(ctx, action, state)
        if (
            action.attacker >= 0
            and ctx.states[action.attacker]["maw_lifeline_omnivamp_active"]
        ):
            schedule_maw_omnivamp_heal(ctx, action, event_time, event_damage)
        if state["reactive_shield_amount"] > 0.0:
            grant_reactive_shield(ctx, action, state, event_time, event_damage)
    if (
        ctx.record_defy_damage
        and 0 <= action.attacker < len(ctx.combatants)
        and action.attacker != action.subject
        and not action.deferred
        and event_damage > 0.0
    ):
        ctx.states[action.attacker]["damage_records"].append(
            {
                "target": ctx.combatants[action.subject].participant_id,
                "time": float(event_time),
                "event_slot": event_slot,
            }
        )
    # An execution is an authored terminal transition.  Both its threshold
    # and the name of whatever declared it are carried by the attacker's
    # packet; this walk names no item, and an execution never contributes
    # extra damage or fires from an aggregate row.
    if (
        action.execute_threshold_ratio > 0.0
        and applied_to_health > 0.0
        and pools.health > 0.0
        and pools.health <= pools.max_health * action.execute_threshold_ratio
    ):
        pools.health = 0.0
        state["execute_time"] = float(event_time)
        state["execute_source"] = str(action.execute_source)
        state["death_time"] = min(float(ctx.duration), float(event_time))
        state["terminal_phase"] = "dead"
        state["action_downtime_intervals"].append(
            {
                "kind": "death",
                "start": float(event_time),
                "end": float(ctx.duration),
                "source": str(action.source or action.source_key or "Death"),
            }
        )
        ctx.ledger.write(
            action,
            execute_triggered=True,
            execute_threshold=round(
                pools.max_health * action.execute_threshold_ratio, 6
            ),
        )
        if state["first_death_time"] is None:
            state["first_death_time"] = float(event_time)
        trigger_defy(
            ctx, ctx.combatants[action.subject].participant_id, float(event_time)
        )
        arm_revive_stasis(state, float(event_time))
    # Grievous Wounds sources do not stack; refresh the strongest
    # sourced window when another qualifying hit lands.
    if ctx.reduction_profiles is not None:
        attacker_profiles = ctx.reductions_for(action.attacker)
        pack = (
            resolve_grievous(attacker_profiles, damage_type)
            if attacker_profiles
            else None
        )
    else:
        pack = action.grievous
    if pack is not None and event_damage > 0:
        strongest_factor, strongest_duration, labels = pack
        state["healing_reduction_until"] = max(
            state["healing_reduction_until"],
            event_time + strongest_duration,
        )
        state["healing_reduction_factor"] = min(
            state["healing_reduction_factor"], strongest_factor
        )
        for label in labels:
            state["healing_reduction_window_sources"].add(label)
        if ctx.records_annotations:
            ctx.ledger.annotate(
                action,
                healing_reduction={
                    "factor": round(state["healing_reduction_factor"], 6),
                    "until": round(state["healing_reduction_until"], 6),
                    "sources": sorted(state["healing_reduction_window_sources"]),
                },
            )
        state["healing_reduction_events"].append(
            {
                "time": round(event_time, 3),
                "until": round(state["healing_reduction_until"], 3),
                "factor": round(state["healing_reduction_factor"], 6),
                "sources": sorted(state["healing_reduction_window_sources"]),
            }
        )
    if action.wound is not None:
        # A reactive wound (Thorns) rides its strike-back packet and
        # lands on this packet's target — the striker — even when the
        # return damage itself was fully absorbed by shields.
        wound_duration, wound_label = action.wound
        state["healing_reduction_until"] = max(
            state["healing_reduction_until"],
            event_time + wound_duration,
        )
        state["healing_reduction_factor"] = min(
            state["healing_reduction_factor"],
            GRIEVOUS_WOUNDS_FACTOR,
        )
        state["healing_reduction_window_sources"].add(wound_label)
        if ctx.records_annotations:
            ctx.ledger.annotate(
                action,
                healing_reduction={
                    "factor": round(state["healing_reduction_factor"], 6),
                    "until": round(state["healing_reduction_until"], 6),
                    "sources": sorted(state["healing_reduction_window_sources"]),
                },
            )
        state["healing_reduction_events"].append(
            {
                "time": round(event_time, 3),
                "until": round(state["healing_reduction_until"], 3),
                "factor": round(state["healing_reduction_factor"], 6),
                "sources": sorted(state["healing_reduction_window_sources"]),
            }
        )
    if pools.health <= 0.0 and state["death_time"] is None:
        if state["first_death_time"] is None:
            state["first_death_time"] = float(event_time)
        trigger_defy(
            ctx, ctx.combatants[action.subject].participant_id, float(event_time)
        )
        state["death_time"] = min(float(ctx.duration), event_time)
        state["terminal_phase"] = "dead"
        state["action_downtime_intervals"].append(
            {
                "kind": "death",
                "start": float(event_time),
                "end": float(ctx.duration),
                "source": str(action.source or action.source_key or "Death"),
            }
        )
        # A revive packet is intentionally scheduled by the caller.  A
        # dead participant remains terminal until that explicit packet;
        # no item is inferred from the loadout here.  The lethal packet DOES
        # decide whether a sourced revive fires at all: arming the explicit
        # resurrection stasis here is what makes the scheduled candidate
        # eligible, so a Rebirth still on cooldown is a plain death.
        arm_revive_stasis(state, float(event_time))


_DAMAGE_KINDS = frozenset(
    {
        ActionKind.PLAIN_DAMAGE,
        ActionKind.DAMAGE,
        ActionKind.EXECUTE,
        ActionKind.DEFER,
        ActionKind.REDIRECT,
    }
)


def run_survival_walk(
    actions: Sequence[SurvivalAction], ctx: TransitionContext
) -> None:
    """The shared walk: every precondition gate in the authoritative order,
    then this loop's own dispatch to the one implementation per mechanic.

    Both adapters drive this exact loop; the ledger abstracts the skip
    annotations, trigger-linkage status, and walk-authored scheduling so
    the receipt and score representations never fork the semantics.
    """
    states = ctx.states
    ledger = ctx.ledger
    duration = ctx.duration
    # The receipt ledger inserts walk-authored recovery packets beside
    # the action being processed (``current_index`` is its slot).
    tracks_index = hasattr(ledger, "current_index")
    action_index = 0
    last_snapshot_time: float | None = None
    while action_index < len(actions):
        action = actions[action_index]
        action_index += 1
        if tracks_index:
            ledger.current_index = action_index - 1
        event_time = action.time
        phase = action.phase
        subject = action.subject
        state = states[subject]

        if event_time > duration:
            # The shared ledger is bounded by the authored fight window.  A
            # post-window revive, heal, or damage tick must remain visible in
            # the receipt but cannot alter terminal state or totals.
            ledger.skip(
                action, "outside_window", damage_phase=phase >= TransitionRank.DAMAGE
            )
            continue

        snapshot_time = round(float(event_time), 9)
        if last_snapshot_time != snapshot_time:
            for snapshot_index, snapshot_state in enumerate(states):
                snapshot_pools = snapshot_state["pools"]
                if snapshot_pools.timed:
                    shield_ledger.expire_timed(snapshot_pools, event_time)
                ctx.shield_presence_at_time[(snapshot_index, snapshot_time)] = (
                    snapshot_pools.magic_shield
                    + snapshot_pools.physical_shield
                    + snapshot_pools.general_shield
                    > 1e-9
                )
            last_snapshot_time = snapshot_time

        pools = state["pools"]
        if pools.timed:
            shield_ledger.expire_timed(pools, event_time)
        if (
            state["healing_reduction_until"] > 0.0
            and event_time >= state["healing_reduction_until"]
        ):
            # A new wound after expiry starts a fresh composition window; do
            # not carry the prior factor or source labels into its receipt.
            state["healing_reduction_factor"] = 1.0
            state["healing_reduction_window_sources"].clear()
        if state["venom_until"] > 0.0 and event_time >= state["venom_until"]:
            # A new venom application after expiry starts a fresh window;
            # expired venom must not keep cutting shields.
            pools.venom_factor = 1.0
        if state["temporary_health_amount"] > 0.0:
            expire_temporary_health(state, event_time)
        if pools.threshold_health is not None:
            shield_ledger.expire_threshold_health(pools, event_time)

        kind = action.kind
        # Revive is a state transition rather than healing: it is allowed to
        # run after a lethal packet and restores a sourced resource amount.
        if kind is ActionKind.REVIVE:
            _apply_revive(ctx, action, state)
            continue
        if kind in (
            ActionKind.STASIS,
            ActionKind.INVULNERABLE,
            ActionKind.UNTARGETABLE,
        ):
            _apply_combat_state_transition(ctx, action, state)
            continue
        if kind is ActionKind.SPELL_SHIELD:
            _apply_spell_shield(ctx, action, state)
            continue
        if (
            action.defy_trigger_slot != NO_SLOT
            and action.defy_trigger_slot not in state["defy_triggered_damage_ids"]
        ):
            ledger.skip(action, "defy_not_triggered")
            continue
        guardian_reactive = bool(
            action.event is not None and action.event.get("_guardian_reactive")
        )
        if (
            not guardian_reactive
            and (action.trigger >= 0 or action.trigger_slot != NO_SLOT)
        ) and not ledger.trigger_applied(action):
            # An effect whose trigger packet was skipped (its target or
            # attacker was already dead) must not survive on its own —
            # neither a recovery tick nor a reactive strike-back.  An action
            # with no trigger linkage at all passes both adapters trivially,
            # so the ledger is only consulted when a link exists.
            #
            # ``DEBUFF_ARM`` is a *threshold*, not the debuff rank: every
            # rank below it resolves before any arming does, and the three
            # arming ranks sit at or above it.  That was true when they
            # shared one ordering slot and is still true now that Phase 4 S6
            # has split them, which is why the split moved no comparison
            # here (see ``actions.ordering_slot``).
            # ``preserve_reason`` for the same reason the redirect-cancelled
            # arm below carries it, and it was missing here only because this
            # arm runs first.  A redirect child Knight's Vow already cancelled
            # arrives with ``holder_health_gate`` stamped on it, and its
            # trigger is skipped precisely *because* of that cancellation --
            # so overwriting the stamp published the consequence in place of
            # the cause, and the specific reason the walk refused this action
            # was lost to the generic one that followed from it.
            ledger.skip(
                action,
                "trigger_event_skipped",
                damage_phase=phase < TransitionRank.DEBUFF_ARM,
                preserve_reason=True,
            )
            continue
        if action.redirect_cancelled or (
            action.event_slot != NO_SLOT and action.event_slot in ctx.redirect_cancelled
        ):
            ledger.skip(
                action,
                "redirect_gate",
                damage_phase=phase < TransitionRank.DEBUFF_ARM,
                preserve_reason=True,
            )
            continue
        # Knight's Vow's 30%-health condition is an ordered state gate.  The
        # direct share is expanded above so its recipient can be repriced; if
        # the holder is already at or below the threshold, cancel that child
        # and restore the unredirected packet on the Worthy target.
        if ctx.redirect_children and not action.redirected:
            child = ctx.redirect_children.get(action.event_slot)
            if child is not None and (
                action.event_slot == NO_SLOT
                or action.event_slot not in ctx.redirect_gate_checked
            ):
                holder_state = states[child.subject]
                holder_ready = bool(holder_state) and (
                    holder_state["death_time"] is None
                    and (
                        action.redirect_holder_health_ratio <= 0.0
                        or holder_state["pools"].max_health <= 0.0
                        or holder_state["pools"].health
                        > holder_state["pools"].max_health
                        * action.redirect_holder_health_ratio
                        + 1e-9
                    )
                )
                if action.event_slot != NO_SLOT:
                    ctx.redirect_gate_checked.add(action.event_slot)
                    ctx.redirect_gate_checked.add(child.event_slot)
                if not holder_ready:
                    if child.event_slot != NO_SLOT:
                        ctx.redirect_cancelled.add(child.event_slot)
                    ctx.ledger.write(child, damage=0.0)
                    ctx.ledger.write(child, skipped_reason="holder_health_gate")
                    restored = max(0.0, action.redirect_original_damage)
                    ctx.ledger.restore(
                        action,
                        damage=restored,
                        _redirected_amount=0.0,
                        _redirect_fraction=0.0,
                        redirect_skipped_reason="holder_health_gate",
                    )
                    # The redirect did not happen, so the Worthy meets the
                    # whole packet: the direct share goes back to the
                    # pre-split amount and the declaration back to the share
                    # the router took from it.  Put both on the action, not
                    # only on the event the receipt adapter holds -- a
                    # compiled action has no event, and a restore only one
                    # lane can read is how the same cancelled redirect came
                    # to charge the Worthy two different numbers.
                    action = action._replace(
                        amount=restored,
                        declared=pricing.unroute_declared_packet(action.declared),
                    )
        if state["death_time"] is not None:
            # Preserve the scheduled source in the receipt, but do not let
            # a dead target contribute post-death damage to TTD/BIS.
            ledger.skip(action, "target_dead", damage_phase=True)
            continue
        if kind is ActionKind.SHIELD:
            _apply_shield(ctx, action, state)
            continue
        if kind is ActionKind.STAT_BUFF:
            _apply_stat_buff(ctx, action, state)
            continue
        if kind is ActionKind.DAMAGE_MODIFIER:
            _apply_damage_modifier(ctx, action, state)
            continue
        if (
            kind is ActionKind.UTILITY
            and (action.cleanse or action.cleanse_item)
            and action.cast_blocked_by_attacker_control
            and 0 <= action.attacker < len(states)
            and states[action.attacker]["crowd_control_until"] > event_time
        ):
            _write_gated_cleanse_use(ctx, action, states[action.attacker])
            ledger.mark_blocked(action)
            ledger.skip(action, "attacker_state_blocked", damage_phase=True)
            continue
        if kind in (ActionKind.ON_HIT_MAGIC, ActionKind.UTILITY):
            _apply_utility(ctx, action, state)
            continue
        if (
            action.deferred
            and action.deferred_batch_slot != NO_SLOT
            and action.deferred_batch_slot in state["cleared_deferred_batches"]
        ):
            ledger.skip(action, "defy_cleared_deferred_damage", damage_phase=True)
            continue
        if phase >= TransitionRank.DAMAGE and (
            state["stasis_until"] > event_time
            or state["invulnerable_until"] > event_time
            or state["untargetable_until"] > event_time
        ):
            ledger.skip(action, "target_state_blocked", damage_phase=True)
            continue
        if (
            phase >= TransitionRank.DAMAGE
            and state.get("projectile_defense_eligibility") is not None
        ):
            defense = state.get("projectile_defense")
            eligibility = state.get("projectile_defense_eligibility")
            composition = state.get("projectile_defense_composition")
            attacker = (
                ctx.combatants[action.attacker]
                if 0 <= action.attacker < len(ctx.combatants)
                else None
            )
            decision = eligibility.decide(action, attacker)
            if (
                defense is not None
                and composition is not None
                and composition.destroy.enabled
                and decision.eligible
            ):
                state["projectile_defense_blocked"].append(
                    {
                        "time": round(float(event_time), 3),
                        "source": action.source_key,
                        "mode": "destroyed",
                    }
                )
                ledger.mark_blocked(action)
                _record_event_id_match(state, action)
                ctx.ledger.write(
                    action,
                    projectile_defense={
                        "source": defense.source,
                        "mode": "destroyed",
                        "delivery": decision.delivery.public_receipt(),
                        "eligible": True,
                        "remaining_uses": state["projectile_defense_uses_remaining"],
                    },
                )
                ledger.skip(action, defense.kind, damage_phase=True)
                continue
            if composition is not None and composition.full_block.mode != "none":
                _prepare_full_block(ctx, action, state)
        if (
            phase >= TransitionRank.DAMAGE
            and state.get("spell_shield_eligibility") is not None
        ):
            # The kernel-owned spell-shield lifecycle (P2 Slice 2): one
            # eligibility decision per packet, one use per hostile cast,
            # cast grouping for same-cast multi-part packets.
            eligibility = state.get("spell_shield_eligibility")
            composition = state.get("spell_shield_composition")
            attacker = (
                ctx.combatants[action.attacker]
                if 0 <= action.attacker < len(ctx.combatants)
                else None
            )
            event_key = stable_event_key(action)
            if event_key in state.get("projectile_defense_full_block_events", set()):
                # Interaction order: a prior full-block defense already
                # disposed of this packet (destroyed and stasis-blocked
                # packets never reach this gate), so the shield must NOT
                # spend its use.  The packet falls through to the damage
                # application, which zeroes full-blocked packets.
                ctx.ledger.write(
                    action,
                    spell_shield={
                        "source": state["spell_shield_source"],
                        "decision": "prior_defense_fully_blocked",
                        "event_key": event_key,
                    },
                )
            else:
                decision = eligibility.decide(action, attacker)
                state["spell_shield_decisions"].append(decision.public_receipt())
                if decision.eligible:
                    # REARM: the kernel clock decides, this walk only supplies
                    # the three instants it reads.  ``spell_shield_consumed_at``
                    # is ``None`` until a use is spent and ``spell_shield_rearm``
                    # is ``None`` for a shield that carries no clock at all
                    # (Sivir's timed shield) — either one keeps the strict
                    # one-use-per-fight rule, since the kernel fails closed on a
                    # missing argument rather than assuming an instant.
                    block, block_reason = spell_shield_block_decision(
                        state["spell_shield_used"],
                        state["spell_shield_blocked_cast"],
                        decision.cast_identity,
                        attacker,
                        rearm=state["spell_shield_rearm"],
                        event_time=float(event_time),
                        consumed_at=state["spell_shield_consumed_at"],
                        # The restart anchor.  ``last_damage_time`` is the last
                        # instant damage from a modeled combatant landed on this
                        # holder, which is what the cached clause ("timer
                        # restarts upon taking damage from champions") measures.
                        last_champion_damage_at=state["last_damage_time"],
                    )
                    if block_reason == "rearmed":
                        _rearm_spell_shield(state, event_time)
                    if block:
                        uses_before = state["spell_shield_uses_remaining"]
                        if not state["spell_shield_used"]:
                            state["spell_shield_used"] = True
                            state["spell_shield_consumed_at"] = float(event_time)
                            state["spell_shield_blocked_cast"] = spell_shield_group_key(
                                attacker, decision.cast_identity
                            )
                            remaining = state["spell_shield_uses_remaining"]
                            if remaining is not None and remaining > 0:
                                state["spell_shield_uses_remaining"] = remaining - 1
                        state["spell_shield_blocked_packets"].append(
                            {
                                "event_key": event_key,
                                "time": round(float(event_time), 3),
                                "source": action.source_key,
                                "cast_identity": decision.cast_identity,
                                "cast_identity_kind": decision.cast_identity_kind,
                            }
                        )
                        ledger.mark_blocked(action)
                        _write_spell_shield_reduction_receipt(
                            ctx, action, state, attacker
                        )
                        ctx.ledger.write(
                            action,
                            spell_shield={
                                "source": state["spell_shield_source"],
                                "cast_identity": decision.cast_identity,
                                "cast_identity_kind": decision.cast_identity_kind,
                                "eligible": True,
                                "blocked": True,
                                "grouping": block_reason,
                                "use_before": uses_before,
                                "use_after": state["spell_shield_uses_remaining"],
                            },
                        )
                        ctx.ledger.annotate(
                            action, spell_shield_source=state["spell_shield_source"]
                        )
                        _schedule_spell_shield_heal(ctx, action, state)
                        ledger.skip(action, "spell_shield", damage_phase=True)
                        continue
                    # Eligible, but the one use is already spent on another
                    # cast: the packet lands; the receipt names the denial.
                    ctx.ledger.write(
                        action,
                        spell_shield={
                            **decision.public_receipt(),
                            "blocked": False,
                            "reason": block_reason,
                        },
                    )
                else:
                    # Ineligible (outside window / not an ability /
                    # unknown delivery / unknown cast identity): the
                    # packet lands; the decision receipt is the denial.
                    ctx.ledger.write(action, spell_shield=decision.public_receipt())
        heal_carry_exempt = kind in (
            ActionKind.HEAL,
            ActionKind.OVERHEAL_SHIELD,
            ActionKind.ICHOR_CONVERT,
        ) and (
            (
                (action.trigger >= 0 or action.trigger_slot != NO_SLOT)
                and ledger.trigger_applied(action)
            )
            or bool(action.cast_while_disabled)
        )
        # A packet whose source declared itself "not the caster's own action"
        # -- a pet, a summon, a persistent zone -- is exempt from the
        # attacker's crowd control for the same reason a cleanse cast while
        # disabled is: the control stops the champion acting, and the thing
        # that is acting is not the champion.  Zyra's plants keep attacking
        # while a charm holds her.  The exemption is narrow by construction:
        # it covers the crowd-control disjunct only, so an attacker in
        # stasis, invulnerable or untargetable still blocks every packet it
        # authored -- those describe who is being hit, not who is acting.
        control_exempt = heal_carry_exempt or bool(action.cast_while_disabled)
        if (
            phase >= TransitionRank.DAMAGE
            and 0 <= action.attacker < len(states)
            and not action.reactive
            and (
                _actor_stasis_blocks(states[action.attacker], event_time)
                or states[action.attacker]["invulnerable_until"] > event_time
                or states[action.attacker]["untargetable_until"] > event_time
                or (
                    states[action.attacker]["crowd_control_until"] > event_time
                    and not control_exempt
                )
            )
        ):
            if action.cleanse or action.cleanse_item:
                # A gated cleanse activation (Mikael's Purify while the
                # caster is crowd-controlled — the item's 3222Active
                # carries no canCastWhileDisabled flag) never fires: the
                # caster use receipt names the gate and the use is NOT
                # consumed.  QSS/Mercurial self-casts are utility-kind and
                # dispatch before this gate (canCastWhileDisabled).
                _write_gated_cleanse_use(ctx, action, states[action.attacker])
            ledger.mark_blocked(action)
            ledger.skip(action, "attacker_state_blocked", damage_phase=True)
            continue
        if (
            0 <= action.attacker < len(states)
            and states[action.attacker]["death_time"] is not None
            and not action.reactive
            and not action.deferred
        ):
            # A dead actor cannot continue an already-scheduled rotation or
            # emit a support effect later in the shared window. Reactive
            # strike-back is exempt: its trigger linkage above already
            # proves the wearer was alive when struck (a killing blow
            # still takes the thorns with it).
            ledger.skip(action, "attacker_dead", damage_phase=True)
            continue
        if kind is ActionKind.CROWD_CONTROL:
            if (
                _interaction_event_key(action)
                in state["projectile_defense_full_block_events"]
            ):
                defense = state.get("projectile_defense")
                ledger.skip(
                    action,
                    defense.kind if defense is not None else "projectile_defense",
                    damage_phase=True,
                )
            else:
                _apply_crowd_control(ctx, action, state, 1.0)
            continue
        if kind is ActionKind.CROWD_CONTROL_RESIST:
            _apply_crowd_control_resist(ctx, action, state)
            continue
        if kind is ActionKind.TEMP_HEALTH:
            # The shared packet chain runs for recovery packets too, exactly
            # like the authoritative walk (it is a no-op for them unless a
            # next-event-only modifier is armed); the recovered amount never
            # rides the packet's damage field.
            _apply_live_packet_chain(ctx, action, state)
            _apply_temp_health(ctx, action, state)
            continue
        if kind in (
            ActionKind.HEAL,
            ActionKind.OVERHEAL_SHIELD,
            ActionKind.ICHOR_CONVERT,
        ):
            _apply_live_packet_chain(ctx, action, state)
            _apply_heal(ctx, action, state)
            if action.cleanse or action.cleanse_item:
                # Mikael's Purify rides its heal packet with the cleanse
                # marker: the typed cleanse contract applies alongside the
                # sourced heal (P2 Slice 4).
                _apply_cleanse(ctx, action, state)
            continue
        if phase < TransitionRank.DAMAGE:
            # Pre-damage residue: the authoritative walk's branch for ranks
            # arming before damage ends with a bare continue (no state
            # change, no annotations).
            continue
        if _interaction_event_key(action) in state.get(
            "projectile_defense_full_block_events", set()
        ):
            # A prior full-block defense disposed of this packet (the
            # full-block prepare ran before the attacker-state gate, so a
            # state-skipped packet keeps its pinned skipped_reason).  The
            # spell-shield gate above never spent a use on it.
            defense = state.get("projectile_defense")
            ledger.skip(
                action,
                defense.kind if defense is not None else "projectile_defense",
                damage_phase=True,
            )
            continue
        _apply_damage(ctx, action, state)


def _fill_blocked_shield_after(
    state: Mapping[str, Any], action: SurvivalAction, absorbed: float
) -> None:
    """Fill a blocked-control receipt's post-absorption holder amount.

    The immunity gate runs BEFORE the same packet's absorption (the
    pinned same-hit order), so the blocked receipt's
    ``shield_amount_after`` is unknown at decision time; the walk writes
    it here, right after the ledger absorbs the packet's damage.  The
    public convention (pinned by the acceptance matrix) reports the
    after amount at the packet's public damage precision: ``before``
    minus the absorbed damage rounded to 1 decimal, floored at zero.  A
    control-only packet never absorbs and keeps before == after.
    """
    grants = state.get("crowd_control_immunity_grants", ())
    if not grants:
        return
    # The same formula on both adapters: before (the decision's holder
    # amount) minus this packet's absorbed damage rounded to 1 decimal,
    # floored at zero.  Receipt mode reads the decision from the event
    # annotation; score mode reads the blocked entry the walk recorded.
    before: float | None = None
    if action.event is not None:
        blocked = action.event.get("crowd_control_blocked")
        if isinstance(blocked, dict) and isinstance(blocked.get("decision"), dict):
            before = max(
                0.0, float(blocked["decision"].get("shield_amount_before", 0.0))
            )
            after = max(0.0, round(before - round(absorbed, 1), 6))
            blocked["shield_amount_after"] = after
    key = stable_event_key(action)
    for entry in state.get("crowd_control_immunity_blocked", ()):
        if entry.get("event_key") != key:
            continue
        if before is None:
            before = max(0.0, float(entry.get("shield_amount_before", 0.0) or 0.0))
            after = max(0.0, round(before - round(absorbed, 1), 6))
        entry["shield_amount_after"] = after
        break


def _finalize_crowd_control_immunity(state: dict[str, Any], duration: float) -> None:
    """Record the terminal immunity-ended reason and clear the single-slot
    projection at the fight edge."""
    grants = state.get("crowd_control_immunity_grants", ())
    if grants:
        latest = grants[-1]
        if latest.get("ended_reason") is None:
            latest["ended_reason"] = (
                "expired"
                if float(latest["expires_at"]) <= duration + 1e-9
                else "fight_end"
            )
        holder = immunity_holder(state["pools"], latest["source"], duration)
        if holder is None:
            state["crowd_control_immunity_until"] = 0.0
            state["crowd_control_immunity_source"] = ""
        else:
            state["crowd_control_immunity_until"] = max(
                state["crowd_control_immunity_until"], float(holder.expires_at)
            )
            state["crowd_control_immunity_source"] = latest["source"]
    else:
        state["crowd_control_immunity_until"] = 0.0
        state["crowd_control_immunity_source"] = ""


def finalize_states(states: Sequence[dict[str, Any]], duration: float) -> None:
    """Post-walk expiry: timed shields, temporary health and an armed
    temporary-health Lifeline at the window edge (the authoritative walk's
    final pass)."""
    for state in states:
        shield_ledger.expire_timed(state["pools"], float(duration))
        _finalize_crowd_control_immunity(state, float(duration))
        expire_temporary_health(state, float(duration))
        shield_ledger.expire_threshold_health(state["pools"], float(duration))


__all__ = [
    "TransitionContext",
    "apply_declared_price",
    "evaluate_live_raw_formula",
    "expire_temporary_health",
    "finalize_states",
    "participant_pools",
    "resolve_grievous",
    "run_survival_walk",
]
