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

S9 gives it the ``(Program, WalkResult)`` signature the phase's five views
share: the roster comes off the program and the final state off the result,
which is what makes "score mode and receipt mode agree" a fact about the
inputs rather than about two callers passing matching arguments.  It re-runs
no arithmetic that the kernel did not already do -- the two sums below
(``remaining_shield`` and ``effective_health``) are the two the kernel itself
performed here, moved rather than introduced, and they are named in the
phase's view-purity criterion as the thing still owed to the walk result
rather than something this stage may quietly keep.
"""

from __future__ import annotations

from typing import Any

from ..precision import round_field
from . import LeafBlock, LeafWriter

__all__ = ["survival", "survival_leaves"]


def _optional_time(field: str, value: float | None) -> float | None:
    """A published timestamp, or ``None`` where the walk recorded none.

    ``None`` is not zero and is never rounded into one: an actor who did not
    die has no death time, which is a different published answer from dying
    at t=0.
    """
    return None if value is None else round_field(field, value)


def _combat_state_blocks(
    state: dict[str, Any], row: dict[str, Any], leaf: LeafBlock
) -> None:
    """The two stack-ledger sub-blocks, whose leaf names collide.

    ``dynamic_bonus_magic_resistance`` is published under both Force of
    Nature and Jak'Sho, which is why the precision registry keys these on
    ``block.name`` rather than on the bare leaf -- and why the two blocks get
    their own leaf paths in the ``dispositions`` map for the same reason.
    """
    force: dict[str, Any] = {}
    row["force_of_nature"] = force
    inner = leaf.nested(force, "force_of_nature")
    inner.raw("stacks", int(state["force_stacks"]))
    inner.measured(
        "stacks_until",
        round_field("force_of_nature.stacks_until", state["force_stacks_until"]),
    )
    inner.raw("events", list(state["force_stack_events"]))
    inner.measured(
        "dynamic_bonus_magic_resistance",
        round_field(
            "force_of_nature.dynamic_bonus_magic_resistance",
            float(state.get("dynamic_bonus_magic_resistance", 0.0) or 0.0),
        ),
    )
    jaksho: dict[str, Any] = {}
    row["jaksho"] = jaksho
    inner = leaf.nested(jaksho, "jaksho")
    inner.raw("stacks", int(state["jaksho_stacks"]))
    inner.raw("events", list(state["jaksho_stack_events"]))
    inner.measured(
        "dynamic_bonus_armor",
        round_field(
            "jaksho.dynamic_bonus_armor",
            float(state.get("dynamic_bonus_armor", 0.0) or 0.0),
        ),
    )
    inner.measured(
        "dynamic_bonus_magic_resistance",
        round_field(
            "jaksho.dynamic_bonus_magic_resistance",
            float(state.get("dynamic_bonus_magic_resistance", 0.0) or 0.0),
        ),
    )


def survival_leaves(
    program: Any, result: Any, writer: LeafWriter, prefix: str
) -> dict[str, dict[str, Any]]:
    """Project the walk's final state into one published row per participant.

    Shared row shape for both adapters: the score adapter builds the same
    rows from the same state and adds the per-event ``recipient`` prefix
    itself (the rows here carry it).

    ``program`` supplies the roster and ``result`` the state the walk left,
    which is the whole of this view's input surface -- criterion 3's "each
    view's inputs are exactly ``Program`` and ``WalkResult``".  The roster is
    read off ``program.actors`` and never off the result, because a
    participant is a champion at a level holding items and the walk records
    only what happened to it.
    """
    states = result.states
    combatants = program.actors
    rows: dict[str, dict[str, Any]] = {}
    grey = result.grey_health
    for index, state in enumerate(states):
        participant_id = combatants[index].participant_id
        pools = state["pools"]
        remaining_shields = sum(
            (pools.magic_shield, pools.physical_shield, pools.general_shield)
        )
        threshold_shield = pools.threshold_shield
        threshold_health = pools.threshold_health
        row: dict[str, Any] = {}
        rows[participant_id] = row
        leaf = writer.block(row, f"{prefix}.{participant_id}")
        leaf.measured("max_health", round_field("max_health", pools.max_health))
        leaf.measured("ending_health", round_field("ending_health", pools.health))
        leaf.measured(
            "ending_health_ratio",
            round_field(
                "ending_health_ratio",
                pools.health / pools.max_health if pools.max_health > 0.0 else 0.0,
            ),
        )
        leaf.measured("damage_taken", round_field("damage_taken", pools.damage_taken))
        leaf.measured("overkill", round_field("overkill", pools.overkill))
        leaf.measured(
            "health_damage", round_field("health_damage", pools.health_damage)
        )
        leaf.measured(
            "shield_absorbed", round_field("shield_absorbed", pools.shield_absorbed)
        )
        leaf.measured(
            "healing_received",
            round_field("healing_received", state["healing_received"]),
        )
        leaf.measured("overhealing", round_field("overhealing", state["overhealing"]))
        leaf.measured(
            "healing_reduced", round_field("healing_reduced", state["healing_reduced"])
        )
        leaf.measured(
            "support_shield_received",
            round_field("support_shield_received", state["support_shield_received"]),
        )
        leaf.measured(
            "support_shield_expired",
            round_field("support_shield_expired", pools.shield_expired),
        )
        leaf.measured(
            "temporary_health_received",
            round_field(
                "temporary_health_received", state["temporary_health_received"]
            ),
        )
        leaf.measured(
            "temporary_health_until",
            round_field("temporary_health_until", state["temporary_health_until"]),
        )
        leaf.raw("temporary_health_expired_at", state["temporary_health_expired_at"])
        leaf.raw("temporary_health_source", state["temporary_health_source"])
        leaf.measured(
            "effective_health",
            round_field(
                "effective_health",
                pools.max_health
                + state["starting_shield"]
                + state["support_shield_received"]
                - pools.shield_expired
                + state["healing_received"],
            ),
        )
        leaf.measured(
            "remaining_shield", round_field("remaining_shield", remaining_shields)
        )
        leaf.measured(
            "starting_shield", round_field("starting_shield", state["starting_shield"])
        )
        leaf.measured(
            "healing_reduction_until",
            round_field("healing_reduction_until", state["healing_reduction_until"]),
        )
        leaf.raw(
            "healing_reduction_sources", sorted(state["healing_reduction_sources"])
        )
        leaf.raw(
            "healing_reduction_events",
            [
                {"recipient": participant_id, **event}
                for event in state["healing_reduction_events"]
            ],
        )
        leaf.measured("venom_until", round_field("venom_until", state["venom_until"]))
        leaf.measured("venom_factor", round_field("venom_factor", pools.venom_factor))
        leaf.raw(
            "venom_events",
            [{"recipient": participant_id, **event} for event in state["venom_events"]],
        )
        leaf.raw("survived_window", state["death_time"] is None)
        leaf.optional_measured(
            "death_time", _optional_time("death_time", state["death_time"])
        )
        leaf.optional_measured(
            "first_death_time",
            _optional_time("first_death_time", state["first_death_time"]),
        )
        leaf.raw("revived", bool(state["revived"]))
        leaf.optional_measured(
            "revive_time", _optional_time("revive_time", state["revive_time"])
        )
        leaf.measured(
            "revive_health_restored",
            round_field("revive_health_restored", state["revive_health_restored"]),
        )
        leaf.raw("revive_source", state["revive_source"])
        leaf.raw("terminal_phase", state["terminal_phase"])
        leaf.optional_measured(
            "execute_time", _optional_time("execute_time", state["execute_time"])
        )
        leaf.raw("execute_source", state["execute_source"])
        leaf.measured(
            "stasis_until", round_field("stasis_until", state["stasis_until"])
        )
        leaf.raw("stasis_started_at", state["stasis_started_at"])
        leaf.raw("stasis_source", state["stasis_source"])
        leaf.measured(
            "invulnerable_until",
            round_field("invulnerable_until", state["invulnerable_until"]),
        )
        leaf.measured(
            "untargetable_until",
            round_field("untargetable_until", state["untargetable_until"]),
        )
        leaf.raw("spell_shield_used", bool(state["spell_shield_used"]))
        leaf.raw("spell_shield_source", state["spell_shield_source"])
        leaf.optional_measured(
            "spell_shield_until",
            (
                None
                if state["spell_shield_until"] == float("inf")
                else round_field("spell_shield_until", state["spell_shield_until"])
            ),
        )
        _combat_state_blocks(state, row, leaf)
        leaf.raw(
            "threshold_shield_triggered",
            bool(threshold_shield is not None and threshold_shield.triggered),
        )
        leaf.raw(
            "threshold_shield_expired_at",
            (threshold_shield.expired_at if threshold_shield is not None else None),
        )
        leaf.raw(
            "threshold_health_triggered",
            bool(threshold_health is not None and threshold_health.triggered),
        )
        leaf.measured(
            "damage_deferral_fraction",
            round_field(
                "damage_deferral_fraction",
                float(
                    getattr(combatants[index].defenses, "damage_deferral_fraction", 0.0)
                    or 0.0
                ),
            ),
        )
        leaf.measured(
            "damage_deferral_pending",
            round_field("damage_deferral_pending", state["damage_deferral_pending"]),
        )
        leaf.measured(
            "damage_deferral_cleared",
            round_field("damage_deferral_cleared", state["damage_deferral_cleared"]),
        )
        leaf.raw("defy_triggered", bool(state["defy_triggered"]))
        leaf.optional_measured(
            "defy_trigger_time",
            _optional_time("defy_trigger_time", state["defy_trigger_time"]),
        )
        leaf.measured(
            "defy_heal_received",
            round_field("defy_heal_received", state["defy_heal_received"]),
        )
        if index == 0 and grey is not None and grey.get("source"):
            # Grey health is the main champion's stored-then-consumed pool
            # (Mordekaiser), published on its own row.  Both composition
            # paths patched these three keys onto the row after projecting
            # it, in two copies that had to agree; the walk now carries the
            # summary and the projection publishes it once.  It is appended
            # rather than declared in the literal above because the key's
            # *absence* is the statement for every roster without one.
            leaf.measured(
                "grey_health_stored",
                round_field(
                    "grey_health_stored", float(grey.get("grey_health_stored", 0.0))
                ),
            )
            leaf.measured(
                "grey_health_consumed",
                round_field(
                    "grey_health_consumed",
                    float(grey.get("grey_health_consumed", 0.0)),
                ),
            )
            leaf.raw("grey_health_source", str(grey["source"]))
    return rows


def survival(program: Any, result: Any) -> dict[str, dict[str, Any]]:
    """The published rows on their own, for a caller that wants only them.

    The payload views call :func:`survival_leaves` with the payload's own
    writer, because one payload carries one ``dispositions`` map.  This is the
    view's front door and the shape criterion 3 checks: exactly
    ``(Program, WalkResult)`` in, published rows out.
    """
    return survival_leaves(program, result, LeafWriter(), "survival")
