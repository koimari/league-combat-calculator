"""The survival view — the walk's per-participant rows, projected at its end.

This is the end-of-walk projection S3 moves out of the kernel.  It was
``survival.receipt_state.assemble_survival_rows``, and every one of the 38
digit counts it publishes was spelled at its own call site inside
``survival/``.  Both facts are the same fact: rounding is presentation, and a
presentation decision made inside the kernel is a decision no layer can see.

Nothing about the numbers changes.  The rows are field-for-field what the
kernel produced, at the same precisions, and both baselines are the evidence
rather than the claim.  What changes is where the decision lives: every digit
count now comes from :mod:`program.precision`, so the count of ``round(``
under ``survival/`` falls by 38 (migration frontier counter 6) and no future
reader has to hunt a literal to learn what precision a published field has.

The walk's raw state is the input, because at S3 the walk still owns state:
S4 gives this view the ``(Program, WalkResult)`` signature the phase's five
views share, and S9 gives it the ``dispositions`` map.  It re-runs no
arithmetic that the kernel did not already do -- the two sums below
(``remaining_shield`` and ``effective_health``) are the two the kernel itself
performed here, moved rather than introduced, and they are named in the
phase's view-purity criterion as the thing S4 must relocate into the walk
result rather than something this stage may quietly keep.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ..precision import round_field

__all__ = ["survival_rows"]


def _optional_time(field: str, value: float | None) -> float | None:
    """A published timestamp, or ``None`` where the walk recorded none.

    ``None`` is not zero and is never rounded into one: an actor who did not
    die has no death time, which is a different published answer from dying
    at t=0.
    """
    return None if value is None else round_field(field, value)


def _combat_state_blocks(state: dict[str, Any]) -> dict[str, Any]:
    """The two stack-ledger sub-blocks, whose leaf names collide.

    ``dynamic_bonus_magic_resistance`` is published under both Force of
    Nature and Jak'Sho, which is why the precision registry keys these on
    ``block.name`` rather than on the bare leaf.
    """
    return {
        "force_of_nature": {
            "stacks": int(state["force_stacks"]),
            "stacks_until": round_field(
                "force_of_nature.stacks_until", state["force_stacks_until"]
            ),
            "events": list(state["force_stack_events"]),
            "dynamic_bonus_magic_resistance": round_field(
                "force_of_nature.dynamic_bonus_magic_resistance",
                float(state.get("dynamic_bonus_magic_resistance", 0.0) or 0.0),
            ),
        },
        "jaksho": {
            "stacks": int(state["jaksho_stacks"]),
            "events": list(state["jaksho_stack_events"]),
            "dynamic_bonus_armor": round_field(
                "jaksho.dynamic_bonus_armor",
                float(state.get("dynamic_bonus_armor", 0.0) or 0.0),
            ),
            "dynamic_bonus_magic_resistance": round_field(
                "jaksho.dynamic_bonus_magic_resistance",
                float(state.get("dynamic_bonus_magic_resistance", 0.0) or 0.0),
            ),
        },
    }


def survival_rows(
    states: Sequence[dict[str, Any]], combatants: Sequence[Any]
) -> dict[str, dict[str, Any]]:
    """Project the walk's final state into one published row per participant.

    Shared row shape for both adapters: the score adapter builds the same
    rows from the same state and adds the per-event ``recipient`` prefix
    itself (the rows here carry it).
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
        result[participant_id] = {
            "max_health": round_field("max_health", pools.max_health),
            "ending_health": round_field("ending_health", pools.health),
            "ending_health_ratio": round_field(
                "ending_health_ratio",
                pools.health / pools.max_health if pools.max_health > 0.0 else 0.0,
            ),
            "damage_taken": round_field("damage_taken", pools.damage_taken),
            "overkill": round_field("overkill", pools.overkill),
            "health_damage": round_field("health_damage", pools.health_damage),
            "shield_absorbed": round_field("shield_absorbed", pools.shield_absorbed),
            "healing_received": round_field(
                "healing_received", state["healing_received"]
            ),
            "overhealing": round_field("overhealing", state["overhealing"]),
            "healing_reduced": round_field("healing_reduced", state["healing_reduced"]),
            "support_shield_received": round_field(
                "support_shield_received", state["support_shield_received"]
            ),
            "support_shield_expired": round_field(
                "support_shield_expired", pools.shield_expired
            ),
            "temporary_health_received": round_field(
                "temporary_health_received", state["temporary_health_received"]
            ),
            "temporary_health_until": round_field(
                "temporary_health_until", state["temporary_health_until"]
            ),
            "temporary_health_expired_at": state["temporary_health_expired_at"],
            "temporary_health_source": state["temporary_health_source"],
            "effective_health": round_field(
                "effective_health",
                pools.max_health
                + state["starting_shield"]
                + state["support_shield_received"]
                - pools.shield_expired
                + state["healing_received"],
            ),
            "remaining_shield": round_field("remaining_shield", remaining_shields),
            "starting_shield": round_field("starting_shield", state["starting_shield"]),
            "healing_reduction_until": round_field(
                "healing_reduction_until", state["healing_reduction_until"]
            ),
            "healing_reduction_sources": sorted(state["healing_reduction_sources"]),
            "healing_reduction_events": [
                {"recipient": participant_id, **event}
                for event in state["healing_reduction_events"]
            ],
            "venom_until": round_field("venom_until", state["venom_until"]),
            "venom_factor": round_field("venom_factor", pools.venom_factor),
            "venom_events": [
                {"recipient": participant_id, **event}
                for event in state["venom_events"]
            ],
            "survived_window": state["death_time"] is None,
            "death_time": _optional_time("death_time", state["death_time"]),
            "first_death_time": _optional_time(
                "first_death_time", state["first_death_time"]
            ),
            "revived": bool(state["revived"]),
            "revive_time": _optional_time("revive_time", state["revive_time"]),
            "revive_health_restored": round_field(
                "revive_health_restored", state["revive_health_restored"]
            ),
            "revive_source": state["revive_source"],
            "terminal_phase": state["terminal_phase"],
            "execute_time": _optional_time("execute_time", state["execute_time"]),
            "execute_source": state["execute_source"],
            "stasis_until": round_field("stasis_until", state["stasis_until"]),
            "stasis_started_at": state["stasis_started_at"],
            "stasis_source": state["stasis_source"],
            "invulnerable_until": round_field(
                "invulnerable_until", state["invulnerable_until"]
            ),
            "untargetable_until": round_field(
                "untargetable_until", state["untargetable_until"]
            ),
            "spell_shield_used": bool(state["spell_shield_used"]),
            "spell_shield_source": state["spell_shield_source"],
            "spell_shield_until": (
                None
                if state["spell_shield_until"] == float("inf")
                else round_field("spell_shield_until", state["spell_shield_until"])
            ),
            **_combat_state_blocks(state),
            "threshold_shield_triggered": bool(
                threshold_shield is not None and threshold_shield.triggered
            ),
            "threshold_shield_expired_at": (
                threshold_shield.expired_at if threshold_shield is not None else None
            ),
            "threshold_health_triggered": bool(
                threshold_health is not None and threshold_health.triggered
            ),
            "damage_deferral_fraction": round_field(
                "damage_deferral_fraction",
                float(
                    getattr(combatants[index].defenses, "damage_deferral_fraction", 0.0)
                    or 0.0
                ),
            ),
            "damage_deferral_pending": round_field(
                "damage_deferral_pending", state["damage_deferral_pending"]
            ),
            "damage_deferral_cleared": round_field(
                "damage_deferral_cleared", state["damage_deferral_cleared"]
            ),
            "defy_triggered": bool(state["defy_triggered"]),
            "defy_trigger_time": _optional_time(
                "defy_trigger_time", state["defy_trigger_time"]
            ),
            "defy_heal_received": round_field(
                "defy_heal_received", state["defy_heal_received"]
            ),
        }
    return result
