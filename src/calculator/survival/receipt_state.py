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
from .outcome_state import OutcomeLedger
from .transitions import participant_pools
from ..data_registry import data_version
from ..interaction_effects import (
    defense_composition,
    defense_eligibility,
    resolve_physical_damage_reduction,
    resolve_projectile_defense,
    resolve_spell_shield,
)
from ..delivery_eligibility import initial_full_block_uses

# The optimizer rebuilds every participant's state once per candidate
# evaluation, but the construction below derives from exactly seven values:
# the cache generation, the combatant's ``defenses`` record, the four
# resistance stats read at the bottom of the prototype, and the compiled
# below-half healing bonus.  Those seven are the key.
#
# The key is a value, so a hit needs no re-verification and no entry holds a
# combatant alive.  The memo stays bounded because its population is defence
# records rather than roster slots, and a long search meets many.
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

#: The two state fields :func:`build_state` writes per call instead of
#: cloning, because both derive from the combatant's **health** and health is
#: not in the key.  The prototype carries the slots — so a built state's field
#: order is the construction's — and never a health-derived value in them.
#:
#: Why this is a declaration and not a detail: two combatants whose defence
#: record and four resistances match now share one prototype, and one of them
#: may have 1000 health and the other 2500.  Sharing is correct **only**
#: because these two are overwritten on every call, and until S10 that was a
#: property of the write order rather than of the prototype — the health read
#: was inside the memoized construction, reached through
#: ``transitions.participant_pools`` rather than through ``combatant.stats``,
#: where the guard that checks the key covers every stat the prototype reads
#: structurally cannot see it.  Now the prototype does not read health at
#: all, so the key really is every input it has.
#:
#: The ten defence-contract fields joined for the same reason, and they are
#: this merge's own finding: the resolvers behind them read the combatant's
#: ``champion_data``, ``level``, ``request.champion_options`` and ``items``
#: — four inputs the value key structurally cannot see — so resolving them
#: inside the memoized construction would hand two combatants with one
#: defence record and four matching resistances the same Braum window, the
#: same Annul contract and the same Amumu reduction.  They are resolved per
#: call instead, beside the pools.
_PER_CALL_FIELDS = (
    "pools",
    "starting_shield",
    "projectile_defense",
    "projectile_defense_eligibility",
    "projectile_defense_composition",
    "projectile_defense_uses_remaining",
    "physical_damage_reduction",
    "spell_shield_eligibility",
    "spell_shield_composition",
    "spell_shield_uses_remaining",
    "spell_shield_cooldown_seconds",
    "spell_shield_cooldown_atom",
)


def _resolved_defence_contracts(combatant: Any) -> dict[str, Any]:
    """The ten :data:`_PER_CALL_FIELDS` a defence resolver decides.

    One home for the resolution, so the prototype declares the slots and
    this fills them.  ``None`` throughout is "this combatant holds no such
    contract", which is what every reader of these fields already tests for.
    """
    projectile_defense = resolve_projectile_defense(combatant)
    composition = defense_composition(projectile_defense)
    spell_shield = resolve_spell_shield(combatant)
    return {
        "projectile_defense": projectile_defense,
        "projectile_defense_eligibility": defense_eligibility(projectile_defense),
        "projectile_defense_composition": composition,
        "projectile_defense_uses_remaining": (
            initial_full_block_uses(composition) if composition is not None else None
        ),
        "physical_damage_reduction": resolve_physical_damage_reduction(combatant),
        "spell_shield_eligibility": (
            spell_shield.eligibility if spell_shield is not None else None
        ),
        "spell_shield_composition": (
            spell_shield.composition if spell_shield is not None else None
        ),
        "spell_shield_uses_remaining": (1 if spell_shield is not None else None),
        "spell_shield_cooldown_seconds": (
            spell_shield.cooldown_seconds if spell_shield is not None else None
        ),
        "spell_shield_cooldown_atom": (
            dict(spell_shield.cooldown_atom)
            if spell_shield is not None and spell_shield.cooldown_atom is not None
            else None
        ),
    }


def _state_proto_key(
    combatant: Any, below_half_healing_bonus: float
) -> tuple[Any, ...]:
    """The prototype's value key.

    ``defenses`` enters whole because ``Combatant`` admits only a frozen
    ``StartingDefenses``, which hashes and compares by field.  Hashing its
    fifty-five fields plus four stats, once per participant per evaluation,
    buys entries shared between combatants with identical defences.
    """
    stats = combatant.stats
    return (
        data_version(),
        combatant.defenses,
        below_half_healing_bonus,
        *(stats.get(field) for field in _STATE_KEY_STATS),
    )


def build_state(combatant: Any, below_half_healing_bonus: float) -> dict[str, Any]:
    """One participant's canonical survival state.

    Clones the memoized prototype for this combatant's defence record: fresh
    shield pools, fresh containers, shared scalars, field-for-field identical
    to an uncached construction.

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
    memo = _STATE_PROTO_MEMO.get(memo_key)
    if memo is None:
        proto = _build_state_uncached(combatant, below_half_healing_bonus)
        container_keys = [
            key for key, value in proto.items() if value.__class__ in (list, set, dict)
        ]
        if len(_STATE_PROTO_MEMO) > _STATE_PROTO_MEMO_LIMIT:
            _STATE_PROTO_MEMO.clear()
        _STATE_PROTO_MEMO[memo_key] = (proto, container_keys)
    else:
        proto, container_keys = memo
    # The prototype itself is never handed out: the walk mutates its state,
    # so every caller gets a clone with its own pools and containers.  The
    # :data:`_PER_CALL_FIELDS` are filled here and nowhere else — this
    # combatant's health, and the defence contracts resolved from inputs the
    # memo key cannot see, neither of which the shared prototype may hold.
    pools = participant_pools(combatant)
    state = dict(proto)
    state["pools"] = pools
    state["starting_shield"] = sum(
        (pools.magic_shield, pools.physical_shield, pools.general_shield)
    )
    state.update(_resolved_defence_contracts(combatant))
    for key in container_keys:
        state[key] = proto[key].copy()
    return state


def _build_state_uncached(
    combatant: Any, below_half_healing_bonus: float
) -> dict[str, Any]:
    """The canonical state construction the prototype memo clones.

    Every stat it reads is named in :data:`_STATE_KEY_STATS`; a read added
    here without joining that tuple is an input the key cannot see.  That
    sentence is why the two :data:`_PER_CALL_FIELDS` below are left empty
    rather than built: they derive from health, health is not in the key,
    and a memoized construction that read it would be filed under inputs
    that do not determine it — legal only because :func:`build_state`
    happens to overwrite both, which is a fact about the caller and not
    about the prototype.

    Ported from the former authoritative walk's state initialisation, less
    those two fields; the score adapter arms the same shape so both adapters
    share one kernel.  Every combat-state field is inert unless an authored
    packet or armed defense field supplies its trigger/timing — the
    simulator never guesses an item's trigger from a name alone.
    """
    defenses = combatant.defenses
    starting_stasis_duration = max(0.0, float(defenses.starting_stasis_duration))
    base_armor = max(0.0, float(combatant.stats.get("armor", 0.0) or 0.0))
    base_magic_resistance = max(
        0.0, float(combatant.stats.get("magic_resistance", 0.0) or 0.0)
    )
    return {
        # Every shield and health transition rides shield_ledger; this is the
        # one place this participant's absorbing state lives.
        # Both are :data:`_PER_CALL_FIELDS`: the slots are declared here so a
        # built state's field order is this construction's, and the values
        # are the caller's because they are derived from health.
        "pools": None,
        "starting_shield": 0.0,
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
        "permanent_bonus_health_received": 0.0,
        "permanent_bonus_health_events": [],
        "healing_reduction_until": 0.0,
        "healing_reduction_factor": 1.0,
        "healing_reduction_window_sources": set(),
        "healing_reduction_events": [],
        # Serpent's Fang venom: shields the target gains are cut by the
        # sourced fraction while a venom window is active.  The factor is
        # the surviving shield share (1.0 = no venom).
        "venom_until": 0.0,
        "venom_factor": 1.0,
        "venom_events": [],
        "death_time": None,
        "action_downtime_intervals": (
            [
                {
                    "kind": "stasis",
                    "start": 0.0,
                    "end": starting_stasis_duration,
                    "source": str(
                        getattr(defenses, "starting_stasis_source", "") or ""
                    ),
                }
            ]
            if starting_stasis_duration > 0.0
            else []
        ),
        "crowd_control_until": 0.0,
        "crowd_control_intervals": [],
        "crowd_control_immunity_until": 0.0,
        "crowd_control_immunity_source": "",
        # The typed crowd-control immunity ledger.  The exact Black Shield
        # ``shield_ledger.TimedShield`` entry is the ONLY immunity holder; the
        # projection fields above carry the pinned public rows and are
        # re-derived from the ledger.
        "crowd_control_immunity_grants": [],
        "crowd_control_immunity_blocked": [],
        "crowd_control_immunity_decisions": [],
        "crowd_control_immunity_eligibility": None,
        # P2 Slice 4: the typed item-cleanse ledger.  ``cleanse_uses`` is
        # the per-item one-use-per-fight latch on the HOLDER row;
        # ``cleanse_use`` is its public receipt; ``cleanse`` is the
        # recipient's last processed activation receipt; ``cleanse_denied``
        # lists spent-use denials.
        "cleanse_uses": {},
        "cleanse_use": None,
        "cleanse": None,
        "cleanse_denied": [],
        "execute_time": None,
        "execute_source": "",
        # Combat-state mechanics are event-driven.  These fields are
        # deliberately inert unless an authored event supplies the
        # corresponding duration/transition; the simulator never guesses
        # an item's trigger or timing from a name alone.
        "stasis_until": starting_stasis_duration,
        "stasis_started_at": 0.0 if starting_stasis_duration > 0.0 else None,
        "stasis_source": str(defenses.starting_stasis_source),
        "invulnerable_until": 0.0,
        "untargetable_until": 0.0,
        "spell_shield_until": (
            float("inf") if bool(defenses.spell_shield_ready) else 0.0
        ),
        "spell_shield_source": str(defenses.spell_shield_source),
        "spell_shield_used": False,
        "spell_shield_blocked_cast": None,
        "spell_shield_heal_amount": 0.0,
        "spell_shield_heal_delay": 0.0,
        "spell_shield_heal_source": "",
        "spell_shield_heal_triggered": False,
        "spell_shield_heal_time": None,
        # The kernel spell-shield contract (P2 Slice 2).  Annul shields
        # resolve from the starting defenses and the held item; Sivir's timed
        # shield is armed later by the walk's SPELL_SHIELD action.  These
        # five and the four projectile-defence slots below are
        # :data:`_PER_CALL_FIELDS` — declared here, filled by
        # :func:`_resolved_defence_contracts`.
        "spell_shield_eligibility": None,
        "spell_shield_composition": None,
        "spell_shield_uses_remaining": None,
        "spell_shield_blocked_packets": [],
        "spell_shield_decisions": [],
        "spell_shield_cooldown_seconds": None,
        "spell_shield_cooldown_atom": None,
        "projectile_defense": None,
        "projectile_defense_eligibility": None,
        "projectile_defense_composition": None,
        "projectile_defense_uses_remaining": None,
        "projectile_defense_full_block_events": set(),
        "projectile_defense_blocked": [],
        "projectile_defense_event_id_matches": set(),
        "physical_damage_reduction": None,
        "ichorshield_cap": max(
            0.0,
            float(defenses.bloodthirster_shield_cap),
        ),
        "ichorshield_current": max(
            0.0,
            float(defenses.bloodthirster_starting_shield),
        ),
        "reactive_shield_amount": max(0.0, float(defenses.reactive_shield_amount)),
        "reactive_shield_damage_type": str(defenses.reactive_shield_damage_type),
        "reactive_shield_duration": max(0.0, float(defenses.reactive_shield_duration)),
        "reactive_shield_cooldown": max(0.0, float(defenses.reactive_shield_cooldown)),
        "reactive_shield_source": str(defenses.reactive_shield_source),
        "reactive_shield_cooldown_until": 0.0,
        # Guardian is an owner-side threshold ledger.  The holder keeps the
        # damage window and the paired shield activation so either protected
        # participant can trigger the same sourced cooldown.
        "guardian_cooldown_until": 0.0,
        "guardian_damage_history": [],
        "guardian_pending_shields": {},
        "guardian_trigger_events": [],
        # Aftershock snapshots its two resistance bonuses on an accepted
        # immobilize and keeps them active for the sourced 2.5-second window.
        "aftershock_bonus_armor": 0.0,
        "aftershock_bonus_magic_resistance": 0.0,
        "aftershock_until": 0.0,
        "aftershock_trigger_events": [],
        "incoming_damage_multiplier": max(
            0.0, float(defenses.incoming_damage_multiplier)
        ),
        "incoming_damage_linger": max(0.0, float(defenses.incoming_damage_linger)),
        "incoming_damage_cooldown": max(0.0, float(defenses.incoming_damage_cooldown)),
        "incoming_damage_source": str(defenses.incoming_damage_source),
        "incoming_damage_until": (
            float("inf") if float(defenses.incoming_damage_multiplier) < 1.0 else 0.0
        ),
        "incoming_damage_cooldown_until": 0.0,
        "healing_received_multiplier": max(
            1.0,
            float(defenses.healing_received_multiplier),
        ),
        "maw_lifeline_omnivamp_percent": max(
            0.0,
            float(defenses.maw_lifeline_omnivamp_percent),
        ),
        "maw_lifeline_omnivamp_active": False,
        "below_half_healing_bonus": below_half_healing_bonus,
        "first_death_time": None,
        "revive_time": None,
        "revive_source": "",
        "revive_health_restored": 0.0,
        "revived": False,
        "revive_used": False,
        # P3-3P (Guardian Angel Rebirth, and the champion revives that share
        # the interface): the armed revive is carried into the kernel so the
        # death transition can author the explicit resurrection stasis, and
        # so the sourced cooldown — not a one-shot boolean — is the re-arm
        # gate.  Every value comes from the resolved defenses (which read the
        # typed item/champion registries); a zero cooldown NEVER re-arms
        # (fail-closed: an unsourced cooldown keeps the one-use rule).
        "revive_armed_amount": max(
            0.0, float(getattr(defenses, "revive_health_amount", 0.0) or 0.0)
        ),
        "revive_delay": max(0.0, float(getattr(defenses, "revive_delay", 0.0) or 0.0)),
        "revive_cooldown": max(
            0.0, float(getattr(defenses, "revive_cooldown", 0.0) or 0.0)
        ),
        "revive_armed_source": str(getattr(defenses, "revive_source", "") or ""),
        # ``revive_ready_at`` is the re-arm timestamp: 0.0 while the revive
        # has never fired, then ``revive_time + revive_cooldown`` (the wiki
        # rule: the cooldown starts after the resurrection ends).
        "revive_ready_at": 0.0,
        # The explicit resurrection stasis window (start/end/source), armed
        # at the lethal packet and closed by the revive.  The public row
        # carries it as ``rebirth_stasis`` beside the stasis_* projection.
        "revive_stasis_until": 0.0,
        # The death timestamp whose lethal packet armed the window above.
        # ``-inf`` means "no death has armed a resurrection": the applied
        # revive refuses to fire for a death that never entered stasis.
        "revive_stasis_death": float("-inf"),
        "revive_stasis_windows": [],
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
        "force_cast_last_times": {},
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
        "outcomes",
        "next_aidx",
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

        ``compile_event`` has no default because the one ``SurvivalAction``
        constructor lives in ``program/compile.py``, which ``survival/`` may
        not import.  A default would let a caller that forgot it schedule
        nothing and look like a fight where no trigger authored a heal.

        ``outcomes`` is the write-once companion.  An event dict takes the
        last write, so a field two rules answer differently serializes as
        whichever ran second; the companion refuses the second write, names
        both values, and refuses a second ``applied`` contribution for one
        ``(mechanic, subject, event_id)``.  It is built here because every
        write already passes through this object, and a ledger a caller must
        remember to attach would hold only over the walks somebody wired.
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
        self.outcomes = OutcomeLedger(annotating=annotating)
        # Walk-authored recovery is compiled after the composition allocated
        # its slots, so the counter continues where the composition stopped.
        # Derived rather than passed: a slot number handed in beside the list
        # it indexes is two facts that can disagree.
        self.next_aidx = len(actions)

    # -- observation -------------------------------------------------------
    def write(self, action: SurvivalAction, **fields: Any) -> None:
        """Unconditional packet writes the authoritative walk always makes."""
        self.outcomes.write(action, **fields)
        if action.event is not None:
            action.event.update(fields)

    def restore(self, action: SurvivalAction, **fields: Any) -> None:
        """Put an input back on a packet; an input is not an outcome, so no ledger."""
        if action.event is not None:
            action.event.update(fields)

    def annotate(self, action: SurvivalAction, **fields: Any) -> None:
        """Annotate-gated diagnostics only the serialized receipt reads."""
        self.outcomes.annotate(action, **fields)
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

        The refusal reaches the companion ledger before the early return,
        because an action with no event dict is still an action the walk
        refused: the receipt has nowhere to put that fact and the outcome
        ledger does.
        """
        self.outcomes.skip(
            action,
            reason,
            damage_phase=damage_phase,
            preserve_reason=preserve_reason,
        )
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
            aidx=self.next_aidx,
        )
        self.next_aidx += 1
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
