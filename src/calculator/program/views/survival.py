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
no arithmetic at all: the three numbers the settled state *implies* --
``remaining_shield``, ``ending_health_ratio`` and ``effective_health`` -- are
folded by :func:`~..walk.survival_folds` at the moment the walk settles and
arrive here as leaves.  Every number below is therefore something a rule
already computed, re-rounded at its declared precision and published.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ...interaction_effects import public_physical_damage_reduction
from ..build import Program
from ..precision import round_field
from ..walk import SurvivalFold, WalkResult
from . import LeafBlock, LeafWriter

__all__ = ["participant_paths", "survival", "survival_leaves"]


def participant_paths(program: Program) -> tuple[str, ...]:
    """Where each participant's survival row lives, so the ``dispositions`` key
    set and the payload's leaf set are the same strings.
    """
    return tuple(
        f"participants[{index}].survival" for index in range(len(program.actors))
    )


def _optional_time(field: str, value: float | None) -> float | None:
    """A published timestamp, or ``None`` where the walk recorded none: not zero."""
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
    inner.structure("events", list(state["force_stack_events"]))
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
    inner.structure("events", list(state["jaksho_stack_events"]))
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


def _rune_state_blocks(
    state: dict[str, Any], row: dict[str, Any], leaf: LeafBlock
) -> None:
    """The two rune lifecycle sub-blocks (Guardian, Aftershock).

    Their own block rather than part of :func:`_combat_state_blocks`, because
    the two answer different questions: those are item stack ledgers whose
    leaf names collide, these are rune windows whose names do not.
    """
    guardian: dict[str, Any] = {}
    row["guardian"] = guardian
    inner = leaf.nested(guardian, "guardian")
    inner.measured(
        "cooldown_until",
        round_field("guardian.cooldown_until", state["guardian_cooldown_until"]),
    )
    inner.structure("trigger_events", list(state["guardian_trigger_events"]))
    aftershock: dict[str, Any] = {}
    row["aftershock"] = aftershock
    inner = leaf.nested(aftershock, "aftershock")
    inner.measured("until", round_field("aftershock.until", state["aftershock_until"]))
    inner.measured(
        "bonus_armor",
        round_field("aftershock.bonus_armor", float(state["aftershock_bonus_armor"])),
    )
    inner.measured(
        "bonus_magic_resistance",
        round_field(
            "aftershock.bonus_magic_resistance",
            float(state["aftershock_bonus_magic_resistance"]),
        ),
    )
    inner.structure("trigger_events", list(state["aftershock_trigger_events"]))


def _cleanse_receipt(
    state: dict[str, Any], fold: SurvivalFold, participant_id: str
) -> dict[str, Any]:
    """One recipient row's published cleanse receipt.

    The decision fields (removed/rejected controls, downtime before) were
    frozen at activation; ``intervals_after`` and ``downtime_after`` name the
    FINAL interval ledger instead, so a control landing after the activation
    -- a cleanse creates no immunity -- is visible in the receipt rather than
    implied by its absence.  The union itself is the walk's
    (:attr:`~..walk.SurvivalFold.crowd_control_downtime`); this only names it.
    """
    receipt = dict(state["cleanse"])
    # The walk-level intervals mirror the survival row's interval shape
    # (kind/start/end/source + recipient), so naming them here keeps them
    # identical to ``crowd_control_intervals`` by construction.
    receipt["intervals_after"] = [
        {"recipient": participant_id, **event}
        for event in state["crowd_control_intervals"]
    ]
    receipt["downtime_after"] = round_field(
        "cleanse.downtime_after", fold.crowd_control_downtime
    )
    return receipt


# The champion-authored state blocks the walk writes only when the mechanic
# fired: Dr. Mundo's passive lifecycle and Olaf's Ragnarok window.  An absent
# key means "this never happened", which is why nothing publishes a neutral
# row for them -- a reader must ask with a membership check rather than a
# ``.get(..., {})`` that cannot tell the two apart.
_CONDITIONAL_STATE_BLOCKS = (
    "passive_cost",
    "canister",
    "pickup",
    "passive_cooldown",
    "passive_state",
    "ragnarok_immunity",
)


def survival_leaves(
    program: Program,
    result: WalkResult,
    writer: LeafWriter,
    prefixes: Sequence[str],
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

    ``prefixes`` is where each row's leaves live in the *caller's* payload,
    index-aligned with the roster: one payload embeds these rows under
    ``participants[i].survival`` and another under a ranked candidate, and
    the entry has to name the path the leaf is actually at.
    """
    if len(prefixes) != len(program.actors):
        raise ValueError(
            f"{len(prefixes)} leaf paths for {len(program.actors)} participants; "
            "a row published at a path nobody named is a leaf with no entry"
        )
    states = result.states
    combatants = program.actors
    folds = result.survival
    if len(folds) != len(states):
        raise ValueError(
            f"the walk settled {len(states)} states and folded {len(folds)} "
            "survival rows; a published row whose numbers the walk did not "
            "fold is a number this projection would have to invent"
        )
    rows: dict[str, dict[str, Any]] = {}
    grey = result.grey_health
    for index, state in enumerate(states):
        participant_id = combatants[index].participant_id
        pools = state["pools"]
        fold = folds[index]
        threshold_shield = pools.threshold_shield
        threshold_health = pools.threshold_health
        row: dict[str, Any] = {}
        rows[participant_id] = row
        leaf = writer.block(row, prefixes[index])
        leaf.measured("max_health", round_field("max_health", pools.max_health))
        leaf.measured("ending_health", round_field("ending_health", pools.health))
        leaf.measured(
            "ending_health_ratio",
            round_field("ending_health_ratio", fold.ending_health_ratio),
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
            "permanent_bonus_health_received",
            round_field(
                "permanent_bonus_health_received",
                state["permanent_bonus_health_received"],
            ),
        )
        leaf.structure(
            "permanent_bonus_health_events",
            [
                {"recipient": participant_id, **event}
                for event in state["permanent_bonus_health_events"]
            ],
        )
        leaf.measured(
            "effective_health",
            round_field("effective_health", fold.effective_health),
        )
        leaf.measured(
            "remaining_shield",
            round_field("remaining_shield", fold.remaining_shield),
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
        leaf.structure(
            "healing_reduction_events",
            [
                {"recipient": participant_id, **event}
                for event in state["healing_reduction_events"]
            ],
        )
        leaf.measured("venom_until", round_field("venom_until", state["venom_until"]))
        leaf.measured("venom_factor", round_field("venom_factor", pools.venom_factor))
        leaf.structure(
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
        # The explicit resurrection-stasis lifecycle: one entry per lethal
        # packet that actually armed a Rebirth window.  Emitted ONLY when a
        # window was armed, so a row that never entered stasis keeps its
        # pinned shape -- and a reader must ask with a membership check
        # (``"revive_stasis" in row``) rather than a ``.get(..., [])`` that
        # cannot tell "never armed" from "armed with no windows".
        if state["revive_stasis_windows"]:
            leaf.structure(
                "revive_stasis",
                [dict(window) for window in state["revive_stasis_windows"]],
            )
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
            "crowd_control_until",
            round_field("crowd_control_until", state["crowd_control_until"]),
        )
        leaf.measured(
            "crowd_control_immunity_until",
            round_field(
                "crowd_control_immunity_until", state["crowd_control_immunity_until"]
            ),
        )
        leaf.raw(
            "crowd_control_immunity_source", state["crowd_control_immunity_source"]
        )
        if fold.crowd_control_immunity is not None:
            leaf.structure(
                "crowd_control_immunity",
                {"recipient": participant_id, **fold.crowd_control_immunity},
            )
        leaf.structure(
            "crowd_control_intervals",
            [
                {"recipient": participant_id, **event}
                for event in state["crowd_control_intervals"]
            ],
        )
        if state.get("cleanse") is not None:
            leaf.structure("cleanse", _cleanse_receipt(state, fold, participant_id))
        if state.get("cleanse_use") is not None:
            leaf.structure("cleanse_use", dict(state["cleanse_use"]))
        if state.get("cleanse_denied"):
            leaf.structure(
                "cleanse_denied", [dict(entry) for entry in state["cleanse_denied"]]
            )
        if state.get("crowd_control_resisted"):
            leaf.structure(
                "crowd_control_resisted",
                [dict(entry) for entry in state["crowd_control_resisted"]],
            )
        for block in _CONDITIONAL_STATE_BLOCKS:
            if state.get(block) is not None:
                leaf.structure(block, dict(state[block]))
        leaf.measured(
            "action_downtime", round_field("action_downtime", fold.action_downtime)
        )
        leaf.structure(
            "action_downtime_intervals",
            [
                {"recipient": participant_id, **event}
                for event in state["action_downtime_intervals"]
            ],
        )
        leaf.structure("projectile_defense", fold.projectile_defense)
        leaf.raw(
            "projectile_defense_blocked", list(state["projectile_defense_blocked"])
        )
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
        leaf.raw(
            "spell_shield_heal_triggered", bool(state["spell_shield_heal_triggered"])
        )
        leaf.optional_measured(
            "spell_shield_until",
            (
                None
                if state["spell_shield_until"] == float("inf")
                else round_field("spell_shield_until", state["spell_shield_until"])
            ),
        )
        if fold.spell_shield is not None:
            leaf.structure("spell_shield", fold.spell_shield)
        _rune_state_blocks(state, row, leaf)
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
        physical_damage_reduction = state.get("physical_damage_reduction")
        if physical_damage_reduction is not None:
            leaf.structure(
                "physical_damage_reduction",
                public_physical_damage_reduction(physical_damage_reduction),
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


def survival(program: Program, result: WalkResult) -> dict[str, dict[str, Any]]:
    """The published rows on their own, for a caller that wants only them."""
    return survival_leaves(program, result, LeafWriter(), participant_paths(program))
