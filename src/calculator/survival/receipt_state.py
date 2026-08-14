"""Receipt adapter — the annotating ledger for the public timeline.

Builds the canonical per-participant state dicts, drives the shared
:func:`~survival.transitions.run_survival_walk` loop with an event-
annotating ledger, and assembles the survival rows the serialized receipt
returns.  The only difference from :mod:`survival.score_state` is
representation and observation: this adapter annotates the event dicts the
public timeline serializes and schedules walk-authored recovery packets.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, MutableMapping, Sequence
from typing import Any

from .actions import NO_SLOT, SurvivalAction, TransitionRank, action_key
from .transitions import participant_pools
from ..data_registry import data_version

# The optimizer rebuilds every participant's state once per candidate
# evaluation, but the construction below derives from exactly seven values:
# the cache generation (D-49), the combatant's ``defenses`` record, the four
# resistance stats read at the bottom of the prototype, and the compiled
# below-half healing bonus.  Those seven **are** the key (Phase 4's cache
# rule, migration frontier counter 7): the memo used to key on
# ``id(combatant)`` with a strong-reference recycling guard, which is safe
# and is not a value — an address says nothing about the state it stands
# for, so a combatant mutated in place kept its entry, and two candidates
# whose defenses were identical each paid for their own construction.
#
# The key is a value, so no re-verification is needed on a hit and no entry
# holds a combatant alive.  The memo stays bounded because the population is
# now defence records rather than roster slots and a long search meets many.
_STATE_PROTO_MEMO: dict[tuple[Any, ...], tuple[dict[str, Any], list[str]]] = {}
_STATE_PROTO_MEMO_LIMIT = 512

#: The stat fields the prototype reads, in key order.  Named once: a field
#: the construction starts reading without joining this tuple is a value the
#: key cannot see, which is the one way a value key goes wrong.
_STATE_KEY_STATS = (
    "armor",
    "magic_resistance",
    "bonus_armor",
    "bonus_magic_resistance",
)


def _state_proto_key(
    combatant: Any, below_half_healing_bonus: float
) -> tuple[Any, ...] | None:
    """The prototype's value key, or ``None`` when this combatant has none.

    ``defenses`` carries the key's weight and enters it whole, which is legal
    only because it is a frozen dataclass: those hash and compare by field,
    which is what makes an object a value.  Anything else — a namespace a
    unit fixture built, a stub — hashes by identity, and keying on that would
    be ``id()`` wearing a better name, so such a combatant is not memoized at
    all rather than filed under an address.

    **What that costs, stated rather than discovered.**  ``id(combatant)``
    was one machine word; this key hashes a frozen ``StartingDefenses`` —
    fifty-five fields — plus four stats, once per participant per
    evaluation.  It buys a hit rate the address key could not have (two
    combatants with identical defences now share an entry, and a mutated
    record moves its key instead of keeping it), and it is paid for on the
    bench, but "it hits more" is only half the trade and the other half
    belongs in the docstring rather than in a profile.
    """
    defenses = combatant.defenses
    params = getattr(type(defenses), "__dataclass_params__", None)
    if params is None or not params.frozen:
        return None
    stats = combatant.stats
    return (
        data_version(),
        defenses,
        below_half_healing_bonus,
        *(stats.get(field) for field in _STATE_KEY_STATS),
    )


def build_state(combatant: Any, below_half_healing_bonus: float) -> dict[str, Any]:
    """One participant's canonical survival state (issue #137).

    Clones the memoized prototype for this combatant's defence record:
    fresh shield pools, fresh containers, shared scalars — field-for-field
    identical to an uncached construction (issue #171).

    ``below_half_healing_bonus`` is the compiled form of this participant's
    declared below-half healing bonus, and it is a **parameter** rather than
    a read: ``survival`` may not reach a declaration — the dependency runs
    ``interpreters -> survival`` and never back — so the boundary that builds
    the walk compiles it and hands it over, the same device the regeneration
    windows arrive by.  ``0.0`` means no holder declares one; the walk gates
    on the bonus being positive, so an absent bonus and a declared zero are
    the same number and the same answer.
    """
    memo_key = _state_proto_key(combatant, below_half_healing_bonus)
    memo = None if memo_key is None else _STATE_PROTO_MEMO.get(memo_key)
    if memo is None:
        proto = _build_state_uncached(combatant, below_half_healing_bonus)
        container_keys = [
            key for key, value in proto.items() if value.__class__ in (list, set, dict)
        ]
        if memo_key is not None:
            if len(_STATE_PROTO_MEMO) > _STATE_PROTO_MEMO_LIMIT:
                _STATE_PROTO_MEMO.clear()
            _STATE_PROTO_MEMO[memo_key] = (proto, container_keys)
    else:
        proto, container_keys = memo
    # The prototype itself is never handed out: the walk mutates its state,
    # so every caller gets a clone with its own pools and containers.
    pools = participant_pools(combatant)
    state = dict(proto)
    state["pools"] = pools
    state["starting_shield"] = sum(
        (pools.magic_shield, pools.physical_shield, pools.general_shield)
    )
    for key in container_keys:
        state[key] = proto[key].copy()
    return state


def _build_state_uncached(
    combatant: Any, below_half_healing_bonus: float
) -> dict[str, Any]:
    """The canonical state construction the prototype memo clones.

    Every stat it reads is named in :data:`_STATE_KEY_STATS`; a read added
    here without joining that tuple is an input the key cannot see.

    Ported verbatim from the former authoritative walk's state
    initialisation; the score adapter arms the same shape so both adapters
    share one kernel.  Every combat-state field is inert unless an authored
    packet or armed defense field supplies its trigger/timing — the
    simulator never guesses an item's trigger from a name alone.
    """
    defenses = combatant.defenses
    starting_stasis_duration = max(
        0.0, float(getattr(defenses, "starting_stasis_duration", 0.0) or 0.0)
    )
    base_armor = max(0.0, float(combatant.stats.get("armor", 0.0) or 0.0))
    base_magic_resistance = max(
        0.0, float(combatant.stats.get("magic_resistance", 0.0) or 0.0)
    )
    pools = participant_pools(combatant)
    return {
        # Every shield and health transition rides shield_ledger; this is the
        # one place this participant's absorbing state lives (issue #159).
        "pools": pools,
        "starting_shield": sum(
            (pools.magic_shield, pools.physical_shield, pools.general_shield)
        ),
        # Combat regeneration is gated against the last sourced damage
        # timestamp.  The fight starts in combat, so a Warmog packet at
        # t=0 cannot immediately claim an unknown pre-fight idle window.
        "last_damage_time": 0.0,
        "healing_received": 0.0,
        "overhealing": 0.0,
        "healing_reduced": 0.0,
        "support_shield_received": 0.0,
        "support_shield_expired": 0.0,
        # Cross-participant item packets are kept as explicit live state
        # rather than folded into a starting stat guess.  The receipt
        # records each activation and the damage walk consumes only the
        # still-active entries.
        "support_buffs": [],
        "active_damage_modifiers": [],
        "active_on_hit_magic": [],
        "timed_shields": [],
        "temporary_health_received": 0.0,
        "temporary_health_amount": 0.0,
        "temporary_health_until": 0.0,
        "temporary_health_expired_at": None,
        "temporary_health_source": "",
        "healing_reduction_until": 0.0,
        "healing_reduction_factor": 1.0,
        "healing_reduction_sources": set(),
        "healing_reduction_events": [],
        # Serpent's Fang venom: shields the target gains are cut by the
        # sourced fraction while a venom window is active.  The factor is
        # the surviving shield share (1.0 = no venom).
        "venom_until": 0.0,
        "venom_factor": 1.0,
        "venom_events": [],
        "death_time": None,
        "execute_time": None,
        "execute_source": "",
        # Combat-state mechanics are event-driven.  These fields are
        # deliberately inert unless an authored event supplies the
        # corresponding duration/transition; the simulator never guesses
        # an item's trigger or timing from a name alone.
        "stasis_until": starting_stasis_duration,
        "stasis_started_at": 0.0 if starting_stasis_duration > 0.0 else None,
        "stasis_source": str(getattr(defenses, "starting_stasis_source", "") or ""),
        "invulnerable_until": 0.0,
        "untargetable_until": 0.0,
        "spell_shield_until": (
            float("inf")
            if bool(getattr(defenses, "spell_shield_ready", False))
            else 0.0
        ),
        "spell_shield_source": str(getattr(defenses, "spell_shield_source", "") or ""),
        "spell_shield_used": False,
        "spell_shield_blocked_cast": None,
        "ichorshield_cap": max(
            0.0,
            float(getattr(defenses, "bloodthirster_shield_cap", 0.0) or 0.0),
        ),
        "ichorshield_current": max(
            0.0,
            float(getattr(defenses, "bloodthirster_starting_shield", 0.0) or 0.0),
        ),
        "reactive_shield_amount": max(
            0.0, float(getattr(defenses, "reactive_shield_amount", 0.0) or 0.0)
        ),
        "reactive_shield_damage_type": str(
            getattr(defenses, "reactive_shield_damage_type", "") or ""
        ),
        "reactive_shield_duration": max(
            0.0, float(getattr(defenses, "reactive_shield_duration", 0.0) or 0.0)
        ),
        "reactive_shield_cooldown": max(
            0.0, float(getattr(defenses, "reactive_shield_cooldown", 0.0) or 0.0)
        ),
        "reactive_shield_source": str(
            getattr(defenses, "reactive_shield_source", "") or ""
        ),
        "reactive_shield_cooldown_until": 0.0,
        "incoming_damage_multiplier": max(
            0.0, float(getattr(defenses, "incoming_damage_multiplier", 1.0) or 1.0)
        ),
        "incoming_damage_linger": max(
            0.0, float(getattr(defenses, "incoming_damage_linger", 0.0) or 0.0)
        ),
        "incoming_damage_cooldown": max(
            0.0, float(getattr(defenses, "incoming_damage_cooldown", 0.0) or 0.0)
        ),
        "incoming_damage_source": str(
            getattr(defenses, "incoming_damage_source", "") or ""
        ),
        "incoming_damage_until": (
            float("inf")
            if float(getattr(defenses, "incoming_damage_multiplier", 1.0) or 1.0) < 1.0
            else 0.0
        ),
        "incoming_damage_cooldown_until": 0.0,
        "healing_received_multiplier": max(
            1.0,
            float(getattr(defenses, "healing_received_multiplier", 1.0) or 1.0),
        ),
        "maw_lifeline_omnivamp_percent": max(
            0.0,
            float(getattr(defenses, "maw_lifeline_omnivamp_percent", 0.0) or 0.0),
        ),
        "maw_lifeline_omnivamp_active": False,
        "below_half_healing_bonus": below_half_healing_bonus,
        "first_death_time": None,
        "revive_time": None,
        "revive_source": "",
        "revive_health_restored": 0.0,
        "revived": False,
        "revive_used": False,
        "terminal_phase": "alive",
        "damage_deferral_pending": 0.0,
        "damage_deferral_cleared": 0.0,
        "deferred_batches": {},
        "cleared_deferred_batches": set(),
        "damage_records": [],
        "defy_triggered": False,
        "defy_trigger_time": None,
        "defy_heal_received": 0.0,
        "defy_triggered_damage_ids": set(),
        # Force of Nature and Jak'Sho are target-side combat states. Their
        # stack ledgers are kept per participant and begin at zero; the
        # ordered walk adds only source-backed resistance deltas.
        "force_stacks": 0,
        "force_stacks_until": 0.0,
        "force_last_stack_time": None,
        "force_last_cast_key": None,
        "force_stack_events": [],
        "jaksho_stacks": 0,
        "jaksho_stack_events": [],
        "base_armor": base_armor,
        "base_magic_resistance": base_magic_resistance,
        "bonus_armor": max(0.0, float(combatant.stats.get("bonus_armor", 0.0) or 0.0)),
        "bonus_magic_resistance": max(
            0.0,
            float(combatant.stats.get("bonus_magic_resistance", 0.0) or 0.0),
        ),
    }


def build_states(
    combatants: Sequence[Any], below_half_healing_bonuses: Sequence[float]
) -> list[dict[str, Any]]:
    """Index-aligned canonical state list for a participant roster.

    ``below_half_healing_bonuses`` is participant-index-aligned and required
    with no default, for the reason the regeneration windows are: a default
    would make a caller that forgot to compile the declarations
    indistinguishable from a roster declaring none, and a length mismatch
    would hand somebody else's bonus to the wrong subject.
    """
    if len(below_half_healing_bonuses) != len(combatants):
        raise ValueError(
            f"{len(below_half_healing_bonuses)} compiled below-half healing "
            f"bonuses for {len(combatants)} participants; the sequence is "
            "participant-index-aligned, so a short one would give somebody "
            "else's bonus to the wrong subject"
        )
    return [
        build_state(combatant, bonus)
        for combatant, bonus in zip(combatants, below_half_healing_bonuses)
    ]


class ReceiptLedger:
    """The annotating adapter: event-observation writes, trigger-linkage
    status by event id, and walk-authored recovery scheduling."""

    __slots__ = (
        "annotating",
        "records_annotations",
        "damage_event_status",
        "actions",
        "current_index",
        "index_of",
        "expanded_healing",
        "healing",
        "annotations_written",
        "compile_event",
    )

    # Event writes always persist on this adapter; annotations only when
    # the receipt was requested (``records_annotations`` mirrors
    # ``annotating`` so the kernel can skip building dropped kwargs).
    records_event_fields = True

    def __init__(
        self,
        *,
        actions: list[SurvivalAction],
        index_of: Mapping[str, int],
        compile_event: Callable[..., SurvivalAction],
        annotating: bool = True,
        expanded_healing: MutableMapping[str, list[dict[str, Any]]] | None = None,
        healing: MutableMapping[str, list[dict[str, Any]]] | None = None,
    ) -> None:
        """The ledger, plus the builder it may not reach for itself.

        ``compile_event`` is required with no default, and the reason is the
        phase's one-way dependency: the one ``SurvivalAction`` constructor
        lives in ``program/compile.py`` and ``survival/`` may not import
        ``program/``, so the boundary that builds the walk hands the builder
        over -- the same device ``build_state``'s below-half healing bonus
        and ``TransitionContext``'s regeneration windows arrive by.  A
        default would let a caller that forgot it schedule nothing and look
        like a fight in which no trigger authored a heal.
        """
        self.compile_event = compile_event
        self.annotating = annotating
        self.records_annotations = annotating
        self.damage_event_status: dict[int, str] = {}
        self.actions = actions
        self.current_index = -1
        self.index_of = index_of
        self.expanded_healing = expanded_healing
        self.healing = healing

    # -- observation -------------------------------------------------------
    def write(self, action: SurvivalAction, **fields: Any) -> None:
        """Unconditional packet writes the authoritative walk always makes."""
        if action.event is not None:
            action.event.update(fields)

    def annotate(self, action: SurvivalAction, **fields: Any) -> None:
        """Annotate-gated diagnostics only the serialized receipt reads."""
        if action.event is not None and self.annotating:
            action.event.update(fields)

    def skip(
        self,
        action: SurvivalAction,
        reason: str,
        *,
        damage_phase: bool = False,
        preserve_reason: bool = False,
    ) -> None:
        """Skip one action with the authoritative receipt's annotations.

        ``preserve_reason`` keeps an earlier ``skipped_reason`` (the
        Knight's Vow gate stamps ``holder_health_gate`` on the cancelled
        child before its own skip).
        """
        if action.event is None:
            return
        if damage_phase:
            if self.annotating:
                action.event.setdefault(
                    "pair_damage", float(action.event.get("damage", 0.0) or 0.0)
                )
                action.event["live_damage"] = 0.0
                action.event["overkill"] = 0.0
            action.event["damage"] = 0.0
        action.event["applied_amount"] = 0.0
        if preserve_reason:
            action.event.setdefault("skipped_reason", reason)
        else:
            action.event["skipped_reason"] = reason

    # -- trigger linkage ----------------------------------------------------
    def trigger_applied(self, action: SurvivalAction) -> bool:
        """Whether the action's trigger packet was applied (no trigger
        passes; a skipped trigger fails closed, never silently applies)."""
        if action.trigger_slot == NO_SLOT:
            return True
        return self.damage_event_status.get(action.trigger_slot) == "applied"

    def mark_applied(self, action: SurvivalAction) -> None:
        """Mark this action's event applied, so its dependants may fire."""
        if action.event_slot != NO_SLOT:
            self.damage_event_status[action.event_slot] = "applied"

    def mark_blocked(self, action: SurvivalAction) -> None:
        """Mark this action's event blocked, so its dependants fail closed."""
        if action.event_slot != NO_SLOT:
            self.damage_event_status[action.event_slot] = "blocked"

    # -- walk-authored scheduling -------------------------------------------
    def schedule_heal(self, heal_event: dict[str, Any], recipient_id: str) -> None:
        """Insert a recovery packet authored by a just-applied trigger
        beside the current action (receipt adapter observation)."""
        heal_event["_sk"] = action_key(
            float(heal_event.get("time", 0.0)),
            TransitionRank.RECOVERY,
            recipient_id,
            heal_event,
        )
        if self.expanded_healing is not None:
            self.expanded_healing.setdefault(recipient_id, []).append(heal_event)
            if self.healing is not None:
                self.healing[recipient_id] = self.expanded_healing[recipient_id]
        action = self.compile_event(
            heal_event,
            TransitionRank.RECOVERY,
            self.index_of[recipient_id],
            self.index_of,
            subject_id=recipient_id,
        )
        insertion = max(self.current_index + 1, 0)
        while (
            insertion < len(self.actions)
            and self.actions[insertion].sort_key <= action.sort_key
        ):
            insertion += 1
        self.actions.insert(insertion, action)


__all__ = [
    "ReceiptLedger",
    "build_state",
    "build_states",
]
