"""Receipt adapter — the annotating ledger for the public timeline.

Builds the canonical per-participant state dicts, drives the shared
:func:`~survival.transitions.run_survival_walk` loop with an event-
annotating ledger, and assembles the survival rows the serialized receipt
returns.  The only difference from :mod:`survival.score_state` is
representation and observation: this adapter annotates the event dicts the
public timeline serializes and schedules walk-authored recovery packets.
"""

from __future__ import annotations

from typing import Any, Mapping, MutableMapping, Sequence

from .actions import SurvivalAction, action_key, survival_action_from_event
from .transitions import participant_defenses
from ..item_effects import sustain_effect_value


def build_state(combatant: Any) -> dict[str, Any]:
    """One participant's canonical survival state (issue #137).

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
    shield_pools = participant_defenses(combatant.defenses)
    return {
        "health": max(0.0, float(combatant.stats.get("health", 0.0))),
        "max_health": max(0.0, float(combatant.stats.get("health", 0.0))),
        "shields": dict(shield_pools),
        "starting_shield": sum(shield_pools.values()),
        "damage_taken": 0.0,
        "overkill": 0.0,
        "health_damage": 0.0,
        "shield_absorbed": 0.0,
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
        "immortal_path_below_half_healing_multiplier": (
            sustain_effect_value(
                "Immortal Path", "health_state_healing_multiplier_below_half"
            )
            if any(
                str(item.get("name", "")) == "Immortal Path" for item in combatant.items
            )
            else 0.0
        ),
        "threshold_shield": max(
            0.0, float(getattr(defenses, "threshold_shield_amount", 0.0) or 0.0)
        ),
        "threshold_shield_threshold": max(
            0.0,
            float(getattr(defenses, "threshold_shield_health_ratio", 0.0) or 0.0),
        )
        * max(0.0, float(combatant.stats.get("health", 0.0))),
        "threshold_shield_duration": max(
            0.0,
            float(getattr(defenses, "threshold_shield_duration", 0.0) or 0.0),
        ),
        "threshold_shield_damage_type": str(
            getattr(defenses, "threshold_shield_damage_type", "all") or "all"
        ),
        "threshold_shield_triggered": False,
        "threshold_shield_expired_at": None,
        "threshold_health_bonus": max(
            0.0, float(getattr(defenses, "threshold_health_bonus", 0.0) or 0.0)
        ),
        "threshold_health_heal": max(
            0.0, float(getattr(defenses, "threshold_health_heal", 0.0) or 0.0)
        ),
        "threshold_health_ratio": max(
            0.0, float(getattr(defenses, "threshold_health_ratio", 0.0) or 0.0)
        ),
        "threshold_health_duration": max(
            0.0, float(getattr(defenses, "threshold_health_duration", 0.0) or 0.0)
        ),
        "threshold_health_triggered": False,
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


def build_states(combatants: Sequence[Any]) -> list[dict[str, Any]]:
    """Index-aligned canonical state list for a participant roster."""
    return [build_state(combatant) for combatant in combatants]


class ReceiptLedger:
    """The annotating adapter: event-observation writes, trigger-linkage
    status by event id, and walk-authored recovery scheduling."""

    __slots__ = (
        "annotating",
        "damage_event_status",
        "actions",
        "current_index",
        "index_of",
        "expanded_healing",
        "healing",
        "annotations_written",
    )

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
        remaining_shields = sum(state["shields"].values())
        result[participant_id] = {
            "max_health": round(state["max_health"], 1),
            "ending_health": round(state["health"], 1),
            "ending_health_ratio": round(
                (
                    state["health"] / state["max_health"]
                    if state["max_health"] > 0.0
                    else 0.0
                ),
                6,
            ),
            "damage_taken": round(state["damage_taken"], 1),
            "overkill": round(state["overkill"], 1),
            "health_damage": round(state["health_damage"], 1),
            "shield_absorbed": round(state["shield_absorbed"], 1),
            "healing_received": round(state["healing_received"], 1),
            "overhealing": round(state["overhealing"], 1),
            "healing_reduced": round(state["healing_reduced"], 1),
            "support_shield_received": round(state["support_shield_received"], 1),
            "support_shield_expired": round(state["support_shield_expired"], 1),
            "temporary_health_received": round(state["temporary_health_received"], 1),
            "temporary_health_until": round(state["temporary_health_until"], 3),
            "temporary_health_expired_at": state["temporary_health_expired_at"],
            "temporary_health_source": state["temporary_health_source"],
            "effective_health": round(
                state["max_health"]
                + state["starting_shield"]
                + state["support_shield_received"]
                - state["support_shield_expired"]
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
            "venom_factor": round(state["venom_factor"], 6),
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
            "invulnerable_until": round(state["invulnerable_until"], 3),
            "untargetable_until": round(state["untargetable_until"], 3),
            "spell_shield_used": bool(state["spell_shield_used"]),
            "spell_shield_source": state["spell_shield_source"],
            "spell_shield_until": (
                None
                if state["spell_shield_until"] == float("inf")
                else round(state["spell_shield_until"], 3)
            ),
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
            "threshold_shield_triggered": bool(state["threshold_shield_triggered"]),
            "threshold_shield_expired_at": state["threshold_shield_expired_at"],
            "threshold_health_triggered": bool(state["threshold_health_triggered"]),
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
    return result


__all__ = [
    "ReceiptLedger",
    "assemble_survival_rows",
    "build_state",
    "build_states",
]
