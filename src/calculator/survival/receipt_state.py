"""Receipt adapter — the annotating ledger for the public timeline.

Builds the canonical per-participant state dicts, drives the shared
:func:`~survival.transitions.run_survival_walk` loop with an event-
annotating ledger, and assembles the survival rows the serialized receipt
returns.  The only difference from :mod:`survival.score_state` is
representation and observation: this adapter annotates the event dicts the
public timeline serializes and schedules walk-authored recovery packets.
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping, Sequence
from typing import Any

from .actions import SurvivalAction, action_key, survival_action_from_event
from .transitions import participant_pools
from ..item_effects import sustain_effect_value
from ..interaction_effects import (
    defense_composition,
    defense_eligibility,
    public_defense,
    public_physical_damage_reduction,
    resolve_physical_damage_reduction,
    resolve_projectile_defense,
    resolve_spell_shield,
)
from ..delivery_eligibility import (
    delivery_declarations_receipt,
    initial_full_block_uses,
    spell_shield_rules_receipt,
)

# The optimizer rebuilds every participant's state once per candidate
# evaluation, but the construction below derives only from the combatant's
# fixed defenses/stats/items.  The prototype memo is identity-keyed with a
# strong reference (the same recycling guard as the item-stats memo) and
# bounded because candidate combatants churn per evaluation.  Container
# keys are derived from the prototype itself, so a new mutable field can
# never be silently shared between clones.
_STATE_PROTO_MEMO: dict[int, tuple[Any, dict[str, Any], list[str]]] = {}
_STATE_PROTO_MEMO_LIMIT = 512


def build_state(combatant: Any) -> dict[str, Any]:
    """One participant's canonical survival state (issue #137).

    Clones the memoized prototype for this combatant: fresh shield pools,
    fresh containers, shared scalars — field-for-field identical to an
    uncached construction (issue #171).
    """
    memo = _STATE_PROTO_MEMO.get(id(combatant))
    if memo is None or memo[0] is not combatant:
        proto = _build_state_uncached(combatant)
        container_keys = [
            key for key, value in proto.items() if value.__class__ in (list, set, dict)
        ]
        if len(_STATE_PROTO_MEMO) > _STATE_PROTO_MEMO_LIMIT:
            _STATE_PROTO_MEMO.clear()
        _STATE_PROTO_MEMO[id(combatant)] = (combatant, proto, container_keys)
    else:
        proto, container_keys = memo[1], memo[2]
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


def _build_state_uncached(combatant: Any) -> dict[str, Any]:
    """The canonical state construction the prototype memo clones.

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
    projectile_defense = resolve_projectile_defense(combatant)
    eligibility = defense_eligibility(projectile_defense)
    composition = defense_composition(projectile_defense)
    spell_shield_contract = resolve_spell_shield(combatant)
    physical_damage_reduction = resolve_physical_damage_reduction(combatant)
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
        "utility_effects": [],
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
        "healing_reduction_sources": set(),
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
        # P2 Slice 3: the typed crowd-control immunity ledger.  The exact
        # Black Shield ``shield_ledger.TimedShield`` entry is the ONLY
        # immunity holder; the legacy projection fields above stay for
        # the pinned public rows and are re-derived from the ledger.
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
        "spell_shield_heal_amount": 0.0,
        "spell_shield_heal_delay": 0.0,
        "spell_shield_heal_source": "",
        "spell_shield_heal_triggered": False,
        "spell_shield_heal_time": None,
        # The kernel spell-shield contract (P2 Slice 2).  Annul shields
        # resolve here from the starting defenses; Sivir's timed shield is
        # armed later by the walk's SPELL_SHIELD action.
        "spell_shield_eligibility": (
            spell_shield_contract.eligibility
            if spell_shield_contract is not None
            else None
        ),
        "spell_shield_composition": (
            spell_shield_contract.composition
            if spell_shield_contract is not None
            else None
        ),
        "spell_shield_uses_remaining": (
            1 if spell_shield_contract is not None else None
        ),
        "spell_shield_blocked_packets": [],
        "spell_shield_decisions": [],
        "spell_shield_cooldown_seconds": (
            spell_shield_contract.cooldown_seconds
            if spell_shield_contract is not None
            else None
        ),
        "spell_shield_cooldown_atom": (
            dict(spell_shield_contract.cooldown_atom)
            if spell_shield_contract is not None
            and spell_shield_contract.cooldown_atom is not None
            else None
        ),
        "projectile_defense": projectile_defense,
        "projectile_defense_eligibility": eligibility,
        "projectile_defense_composition": composition,
        "projectile_defense_uses_remaining": (
            initial_full_block_uses(composition) if composition is not None else None
        ),
        "projectile_defense_full_block_events": set(),
        "projectile_defense_blocked": [],
        "projectile_defense_event_id_matches": set(),
        "physical_damage_reduction": physical_damage_reduction,
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
        "immortal_path_below_half_healing_multiplier": (
            sustain_effect_value(
                "Immortal Path", "health_state_healing_multiplier_below_half"
            )
            if any(
                str(item.get("name", "")) == "Immortal Path" for item in combatant.items
            )
            else 0.0
        ),
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


def build_states(combatants: Sequence[Any]) -> list[dict[str, Any]]:
    """Index-aligned canonical state list for a participant roster."""
    return [build_state(combatant) for combatant in combatants]


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
        annotating: bool = True,
        expanded_healing: MutableMapping[str, list[dict[str, Any]]] | None = None,
        healing: MutableMapping[str, list[dict[str, Any]]] | None = None,
    ) -> None:
        self.annotating = annotating
        self.records_annotations = annotating
        self.damage_event_status: dict[str, str] = {}
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
        if action.trigger_event_id is None:
            return True
        return self.damage_event_status.get(action.trigger_event_id) == "applied"

    def mark_applied(self, action: SurvivalAction) -> None:
        if action.event_id is not None:
            self.damage_event_status[action.event_id] = "applied"

    def mark_blocked(self, action: SurvivalAction) -> None:
        if action.event_id is not None:
            self.damage_event_status[action.event_id] = "blocked"

    # -- walk-authored scheduling -------------------------------------------
    def schedule_heal(self, heal_event: dict[str, Any], recipient_id: str) -> None:
        """Insert a recovery packet authored by a just-applied trigger
        beside the current action (receipt adapter observation)."""
        heal_event["_sk"] = action_key(
            float(heal_event.get("time", 0.0)), 1.0, recipient_id, heal_event
        )
        if self.expanded_healing is not None:
            self.expanded_healing.setdefault(recipient_id, []).append(heal_event)
            if self.healing is not None:
                self.healing[recipient_id] = self.expanded_healing[recipient_id]
        action = survival_action_from_event(
            heal_event,
            1.0,
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


def assemble_survival_rows(
    states: Sequence[dict[str, Any]], combatants: Sequence[Any]
) -> dict[str, dict[str, Any]]:
    """Assemble the receipt survival rows from canonical state.

    Shared row shape for both adapters: the score adapter builds the same
    rows from the same state and adds the per-event ``recipient`` prefix
    itself (the receipt adapter's rows carry it here).
    """
    result: dict[str, dict[str, Any]] = {}
    for index, state in enumerate(states):
        participant_id = combatants[index].participant_id
        pools = state["pools"]
        remaining_shields = sum(
            (pools.magic_shield, pools.physical_shield, pools.general_shield)
        )
        threshold_shield = pools.threshold_shield
        threshold_health = pools.threshold_health
        row = {
            "max_health": round(pools.max_health, 1),
            "ending_health": round(pools.health, 1),
            "ending_health_ratio": round(
                (pools.health / pools.max_health if pools.max_health > 0.0 else 0.0),
                6,
            ),
            "damage_taken": round(pools.damage_taken, 1),
            "overkill": round(pools.overkill, 1),
            "health_damage": round(pools.health_damage, 1),
            "shield_absorbed": round(pools.shield_absorbed, 1),
            "healing_received": round(state["healing_received"], 1),
            "overhealing": round(state["overhealing"], 1),
            "healing_reduced": round(state["healing_reduced"], 1),
            "support_shield_received": round(state["support_shield_received"], 1),
            "support_shield_expired": round(pools.shield_expired, 1),
            "temporary_health_received": round(state["temporary_health_received"], 1),
            "temporary_health_until": round(state["temporary_health_until"], 3),
            "temporary_health_expired_at": state["temporary_health_expired_at"],
            "temporary_health_source": state["temporary_health_source"],
            "permanent_bonus_health_received": round(
                state["permanent_bonus_health_received"], 1
            ),
            "permanent_bonus_health_events": [
                {"recipient": participant_id, **event}
                for event in state["permanent_bonus_health_events"]
            ],
            "effective_health": round(
                pools.max_health
                + state["starting_shield"]
                + state["support_shield_received"]
                - pools.shield_expired
                + state["healing_received"],
                1,
            ),
            "remaining_shield": round(remaining_shields, 1),
            "starting_shield": round(state["starting_shield"], 1),
            "healing_reduction_until": round(state["healing_reduction_until"], 3),
            "healing_reduction_sources": sorted(state["healing_reduction_sources"]),
            "healing_reduction_events": [
                {"recipient": participant_id, **event}
                for event in state["healing_reduction_events"]
            ],
            "venom_until": round(state["venom_until"], 3),
            "venom_factor": round(pools.venom_factor, 6),
            "venom_events": [
                {"recipient": participant_id, **event}
                for event in state["venom_events"]
            ],
            "survived_window": state["death_time"] is None,
            "death_time": (
                round(state["death_time"], 3)
                if state["death_time"] is not None
                else None
            ),
            "first_death_time": (
                round(state["first_death_time"], 3)
                if state["first_death_time"] is not None
                else None
            ),
            "revived": bool(state["revived"]),
            "revive_time": (
                round(state["revive_time"], 3)
                if state["revive_time"] is not None
                else None
            ),
            "revive_health_restored": round(state["revive_health_restored"], 1),
            "revive_source": state["revive_source"],
            # P3-3P: the explicit resurrection-stasis lifecycle.  One entry
            # per lethal packet that actually armed a Rebirth window
            # (start / end / sourced duration / source / sourced cooldown /
            # whether the restore resolved and when the re-arm opens).  The
            # key is emitted ONLY when a window was armed, so every row that
            # never entered stasis keeps its pinned shape byte-for-byte.
            **(
                {"revive_stasis": [dict(row) for row in state["revive_stasis_windows"]]}
                if state["revive_stasis_windows"]
                else {}
            ),
            "terminal_phase": state["terminal_phase"],
            "execute_time": (
                round(state["execute_time"], 3)
                if state["execute_time"] is not None
                else None
            ),
            "execute_source": state["execute_source"],
            "stasis_until": round(state["stasis_until"], 3),
            "stasis_started_at": state["stasis_started_at"],
            "stasis_source": state["stasis_source"],
            "crowd_control_until": round(state["crowd_control_until"], 3),
            "crowd_control_immunity_until": round(
                state["crowd_control_immunity_until"], 3
            ),
            "crowd_control_immunity_source": state["crowd_control_immunity_source"],
            **(
                {
                    "crowd_control_immunity": _public_crowd_control_immunity_row(
                        state, participant_id
                    )
                }
                if state.get("crowd_control_immunity_grants")
                else {}
            ),
            "crowd_control_intervals": [
                {"recipient": participant_id, **event}
                for event in state["crowd_control_intervals"]
            ],
            **(
                {"cleanse": _public_cleanse_receipt(state)}
                if state.get("cleanse") is not None
                else {}
            ),
            **(
                {"cleanse_use": dict(state["cleanse_use"])}
                if state.get("cleanse_use") is not None
                else {}
            ),
            **(
                {"cleanse_denied": [dict(entry) for entry in state["cleanse_denied"]]}
                if state.get("cleanse_denied")
                else {}
            ),
            # P2 Slice 8 (Dr. Mundo Goes Where He Pleases): the passive
            # immunity receipts — the resist decision, the 4%-current
            # health cost, the canister drop, the named-unsupported
            # pickup, the receipted cooldown and the armed state.
            **(
                {
                    "crowd_control_resisted": [
                        dict(e) for e in state["crowd_control_resisted"]
                    ]
                }
                if state.get("crowd_control_resisted")
                else {}
            ),
            **(
                {"passive_cost": dict(state["passive_cost"])}
                if state.get("passive_cost") is not None
                else {}
            ),
            **(
                {"canister": dict(state["canister"])}
                if state.get("canister") is not None
                else {}
            ),
            **(
                {"pickup": dict(state["pickup"])}
                if state.get("pickup") is not None
                else {}
            ),
            **(
                {"passive_cooldown": dict(state["passive_cooldown"])}
                if state.get("passive_cooldown") is not None
                else {}
            ),
            **(
                {"passive_state": dict(state["passive_state"])}
                if state.get("passive_state") is not None
                else {}
            ),
            # P2 Slice 9 (Olaf Ragnarok): the 3s immunity window row.
            **(
                {"ragnarok_immunity": dict(state["ragnarok_immunity"])}
                if state.get("ragnarok_immunity") is not None
                else {}
            ),
            "action_downtime": round(
                _merged_interval_duration(state["action_downtime_intervals"]),
                3,
            ),
            "action_downtime_intervals": [
                {"recipient": participant_id, **event}
                for event in state["action_downtime_intervals"]
            ],
            "projectile_defense": _public_defense_row(state),
            "projectile_defense_blocked": list(state["projectile_defense_blocked"]),
            "invulnerable_until": round(state["invulnerable_until"], 3),
            "untargetable_until": round(state["untargetable_until"], 3),
            "spell_shield_used": bool(state["spell_shield_used"]),
            "spell_shield_source": state["spell_shield_source"],
            "spell_shield_heal_triggered": bool(state["spell_shield_heal_triggered"]),
            "spell_shield_until": (
                None
                if state["spell_shield_until"] == float("inf")
                else round(state["spell_shield_until"], 3)
            ),
            **(
                {"spell_shield": _public_spell_shield_row(state)}
                if state.get("spell_shield_eligibility") is not None
                else {}
            ),
            "guardian": {
                "cooldown_until": round(state["guardian_cooldown_until"], 3),
                "trigger_events": list(state["guardian_trigger_events"]),
            },
            "aftershock": {
                "until": round(state["aftershock_until"], 3),
                "bonus_armor": round(float(state["aftershock_bonus_armor"]), 3),
                "bonus_magic_resistance": round(
                    float(state["aftershock_bonus_magic_resistance"]), 3
                ),
                "trigger_events": list(state["aftershock_trigger_events"]),
            },
            "force_of_nature": {
                "stacks": int(state["force_stacks"]),
                "stacks_until": round(state["force_stacks_until"], 3),
                "events": list(state["force_stack_events"]),
                "dynamic_bonus_magic_resistance": round(
                    float(state.get("dynamic_bonus_magic_resistance", 0.0) or 0.0),
                    3,
                ),
            },
            "jaksho": {
                "stacks": int(state["jaksho_stacks"]),
                "events": list(state["jaksho_stack_events"]),
                "dynamic_bonus_armor": round(
                    float(state.get("dynamic_bonus_armor", 0.0) or 0.0), 3
                ),
                "dynamic_bonus_magic_resistance": round(
                    float(state.get("dynamic_bonus_magic_resistance", 0.0) or 0.0),
                    3,
                ),
            },
            "threshold_shield_triggered": bool(
                threshold_shield is not None and threshold_shield.triggered
            ),
            "threshold_shield_expired_at": (
                threshold_shield.expired_at if threshold_shield is not None else None
            ),
            "threshold_health_triggered": bool(
                threshold_health is not None and threshold_health.triggered
            ),
            "damage_deferral_fraction": round(
                float(
                    getattr(
                        combatants[index].defenses,
                        "damage_deferral_fraction",
                        0.0,
                    )
                    or 0.0
                ),
                3,
            ),
            "damage_deferral_pending": round(state["damage_deferral_pending"], 1),
            "damage_deferral_cleared": round(state["damage_deferral_cleared"], 1),
            "defy_triggered": bool(state["defy_triggered"]),
            "defy_trigger_time": (
                round(state["defy_trigger_time"], 3)
                if state["defy_trigger_time"] is not None
                else None
            ),
            "defy_heal_received": round(state["defy_heal_received"], 1),
        }
        physical_damage_reduction = state.get("physical_damage_reduction")
        if physical_damage_reduction is not None:
            row["physical_damage_reduction"] = public_physical_damage_reduction(
                physical_damage_reduction
            )
        result[participant_id] = row
    return result


def _public_cleanse_receipt(state: dict[str, Any]) -> dict[str, Any]:
    """One recipient survival row's public cleanse receipt.

    The decision fields (removed/rejected controls, downtime before) are
    frozen at activation; ``intervals_after`` and ``downtime_after`` are
    re-derived from the FINAL interval ledger at assembly time, so a
    control landing after the activation (untouched — a cleanse creates no
    immunity) is visible in the receipt (the matrix's R11 parity pin).
    """
    receipt = dict(state["cleanse"])
    # The walk-level intervals mirror the survival row's interval shape
    # (kind/start/end/source + recipient) — the assembly-time refresh keeps
    # them identical to ``crowd_control_intervals`` by construction.
    receipt["intervals_after"] = [
        {"recipient": state.get("participant_id", ""), **event}
        for event in state["crowd_control_intervals"]
    ]
    receipt["downtime_after"] = round(
        _merged_interval_duration(state["crowd_control_intervals"]), 6
    )
    return receipt


def _public_crowd_control_immunity_row(
    state: dict[str, Any], participant_id: str
) -> dict[str, Any]:
    """One recipient survival row's public crowd-control immunity receipt.

    Shows the selected recipient, the holder source, the shield source
    atoms, the shield lifetime window (start inclusive, end exclusive),
    the active-until time, the reason immunity ended ("expired" /
    "drained" / "fight_end"), the eligibility declaration, every
    blocked control (with shield amounts before/after), and every
    per-packet decision — the named fail-closed record for denied
    controls (outside window / holder gone / unknown kind).
    """
    grants = state.get("crowd_control_immunity_grants", ())
    if not grants:
        return {
            "recipient": participant_id,
            "shield_source": "",
            "source_atoms": [],
            "window": None,
            "active_until": 0.0,
            "reason_immunity_ended": None,
            "eligibility": None,
            "blocked": [],
            "decisions": [],
        }
    latest = grants[-1]
    eligibility = state.get("crowd_control_immunity_eligibility")
    return {
        "recipient": participant_id,
        "shield_source": latest["source"],
        "source_atoms": [dict(atom) for atom in latest.get("source_atoms", ())],
        "window": (
            eligibility.window.public_receipt() if eligibility is not None else None
        ),
        "active_until": round(float(latest["expires_at"]), 3),
        "reason_immunity_ended": latest.get("ended_reason"),
        "eligibility": (
            eligibility.public_receipt() if eligibility is not None else None
        ),
        "blocked": [
            dict(entry) for entry in state.get("crowd_control_immunity_blocked", [])
        ],
        "decisions": [
            dict(entry) for entry in state.get("crowd_control_immunity_decisions", [])
        ],
    }


def _public_spell_shield_row(state: dict[str, Any]) -> dict[str, Any] | None:
    """One survival row's public spell-shield receipt.

    Extends the kernel declaration with the walk-observed lifecycle:
    the sourced window (an infinite Annul window maps ``until`` to
    None), the acceptance and block rule, the selected cast identity,
    the one-use budget before/after, the blocked packets (stable event
    keys), every eligibility decision, the triggered heal, the declared
    categorical rules, and the receipted cooldown.  The legacy flat
    fields (``spell_shield_used`` / ``source`` / ``heal_triggered`` /
    ``until``) stay untouched above.
    """
    eligibility = state.get("spell_shield_eligibility")
    if eligibility is None:
        return None
    window = eligibility.window.public_receipt()
    if window["until"] == float("inf"):
        window["until"] = None
    blocked_cast = state["spell_shield_blocked_cast"]
    row: dict[str, Any] = {
        "source": state["spell_shield_source"],
        "window": window,
        "acceptance": eligibility.acceptance.public_receipt(),
        "block_rule": eligibility.block_rule,
        "rules": spell_shield_rules_receipt(),
        "uses_before": 1,
        "uses_after": state.get("spell_shield_uses_remaining"),
        "selected_cast_identity": (str(blocked_cast[-1]) if blocked_cast else None),
        "blocked_packets": [
            dict(entry) for entry in state.get("spell_shield_blocked_packets", [])
        ],
        "decisions": [dict(entry) for entry in state.get("spell_shield_decisions", [])],
        "triggered_heal": (
            {
                "time": round(float(state["spell_shield_heal_time"]), 3),
                "amount": round(float(state["spell_shield_heal_amount"]), 6),
                "delay": round(float(state["spell_shield_heal_delay"]), 6),
                "source": state["spell_shield_heal_source"],
            }
            if state.get("spell_shield_heal_time") is not None
            else None
        ),
        "cooldown_seconds": state.get("spell_shield_cooldown_seconds"),
        "cooldown_atom": (
            dict(state["spell_shield_cooldown_atom"])
            if state.get("spell_shield_cooldown_atom") is not None
            else None
        ),
    }
    return row


def _public_defense_row(state: dict[str, Any]) -> dict[str, Any] | None:
    """One survival row's public projectile-defense receipt.

    Extends the static declaration (:func:`public_defense`) with the
    walk-observed state: the remaining full-block uses, the six typed
    delivery declarations, and (for event-id selections) the selected
    event ids that never matched an incoming event — the named
    fail-closed receipt for a positional selection that cannot be
    validated at option-parse time.
    """
    base = public_defense(state["projectile_defense"])
    if base is None:
        return None
    base["remaining_uses"] = state.get("projectile_defense_uses_remaining")
    base["delivery_declarations"] = delivery_declarations_receipt()
    eligibility = state.get("projectile_defense_eligibility")
    if eligibility is not None and eligibility.selection.blocked_event_ids:
        matched = state.get("projectile_defense_event_id_matches", set())
        base["blocked_event_ids_unmatched"] = [
            event_id
            for event_id in eligibility.selection.blocked_event_ids
            if event_id not in matched
        ]
    return base


def _merged_interval_duration(intervals: list[Mapping[str, Any]]) -> float:
    """Return the union length of authored inactive intervals."""
    ordered: list[tuple[float, float]] = []
    for interval in intervals:
        try:
            start = float(interval.get("start", 0.0))
            end = float(interval.get("end", 0.0))
        except (TypeError, ValueError):
            continue
        if end > start:
            ordered.append((start, end))
    ordered.sort()
    total = 0.0
    current_start = current_end = 0.0
    for start, end in ordered:
        if start > current_end:
            total += current_end - current_start
            current_start, current_end = start, end
        else:
            current_end = max(current_end, end)
    if ordered:
        total += current_end - current_start
    return max(0.0, total)


__all__ = [
    "ReceiptLedger",
    "assemble_survival_rows",
    "build_state",
    "build_states",
]
