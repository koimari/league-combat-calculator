"""Score adapter — the parallel-array ledger for the optimizer path.

Drives the same shared walk (:func:`~survival.transitions.run_survival_walk`)
and the same canonical state dicts as the receipt adapter, but observes
transitions into parallel arrays: per-action ``applied`` slots and the
write-once trigger ``status`` bytearray.  It never annotates events and
never schedules walk-authored packets (compilation rejects every mechanic
that could author one, so ``schedule_heal`` fails closed).

The kernel's applied-amount observation is the only write the score ledger
records: ``write(action, damage=...)`` (damage actions) and
``write(action, applied_amount=...)`` (heals/shields) mirror the legacy
compiled walk's ``applied[aidx]`` assignment without duplicating any
arithmetic.  The per-attacker damage-order lists and support entries live
on the compilers; :mod:`survival.accumulate` replays them in the legacy
float-addition order.
"""

from __future__ import annotations

from typing import Any
from collections.abc import Mapping

from .actions import SurvivalAction


class ScoreLedger:
    """Parallel-array observation of the shared kernel.

    ``applied[aidx]`` holds each action's applied amount (the accumulator's
    per-attacker float-sum order replays it) and ``status[aidx]`` is the
    write-once trigger marker.  P3 package 3T: the ledger mirrors the
    receipt adapter's walk-authored heal insertion (Maw's post-Lifeline
    omnivamp heals) by holding the live actions list and growing the
    parallel arrays for each inserted action.
    """

    __slots__ = (
        "n_actions",
        "applied",
        "status",
        "actions",
        "index_of",
        "current_index",
    )

    # Ledger capability flags (issue #171): the kernel's hot loop skips
    # building annotate()/event-field kwargs entirely when the ledger
    # would drop them, instead of paying for round() calls a no-op absorbs.
    records_annotations = False
    records_event_fields = False

    def __init__(
        self,
        n_actions: int,
        *,
        actions: list | None = None,
        index_of: Mapping | None = None,
    ) -> None:
        self.n_actions = n_actions
        self.applied: list[float] = [0.0] * n_actions
        self.status = bytearray(n_actions)
        self.actions: list | None = actions
        self.index_of: Mapping | None = index_of
        self.current_index: int = -1

    # -- observation ---------------------------------------------------------
    # pylint: disable=unused-argument  # protocol-shaped no-op
    def write(self, action: SurvivalAction, **fields: Any) -> None:
        """Record the applied amounts the kernel observes; nothing else."""
        if "damage" in fields:
            self._record(action, fields["damage"])
        elif "applied_amount" in fields:
            self._record(action, fields["applied_amount"])

    def _record(self, action: SurvivalAction, amount: float) -> None:
        if 0 <= action.aidx < self.n_actions:
            self.applied[action.aidx] = amount

    # pylint: disable=unused-argument  # protocol-shaped no-op
    def annotate(self, action: SurvivalAction, **fields: Any) -> None:
        return None

    # pylint: disable=unused-argument  # protocol-shaped no-op
    def skip(
        self,
        action: SurvivalAction,
        reason: str,
        *,
        damage_phase: bool = False,
    ) -> None:
        # Skipped actions leave their applied slot at zero, exactly like the
        # legacy compiled walk's ``continue`` before any state mutation.
        return None

    # -- trigger linkage -----------------------------------------------------
    def trigger_applied(self, action: SurvivalAction) -> bool:
        if action.trigger < 0:
            return True
        return self.status[action.trigger] == 1

    def mark_applied(self, action: SurvivalAction) -> None:
        if 0 <= action.aidx < self.n_actions:
            self.status[action.aidx] = 1

    # pylint: disable=unused-argument  # protocol-shaped no-op
    def mark_blocked(self, action: SurvivalAction) -> None:
        # Score mode has no blocked-state consumer (compilation rejects the
        # mechanics that mark blocked); a blocked action never gets the
        # applied marker, which fails the same trigger gate.
        return None

    # -- walk-authored scheduling (P3 package 3T) ----------------------------
    def schedule_heal(self, heal_event: dict[str, Any], recipient_id: str) -> None:
        """Insert a walk-authored recovery packet beside the current action,
        mirroring the receipt adapter (Maw's post-Lifeline omnivamp heals).

        The compiled walk drives the identical kernel, so a trigger-time
        heal must land at the same timestamp with the same amount; the
        parallel arrays grow by one slot for the inserted action.
        """
        if self.actions is None or self.index_of is None:
            raise AssertionError(
                "score ledger cannot schedule walk-authored heals without "
                "the live actions list and index_of (compiler wiring)"
            )
        from .actions import action_key, survival_action_from_event

        heal_event["_sk"] = action_key(
            float(heal_event.get("time", 0.0)), 1.0, recipient_id, heal_event
        )
        aidx = self.n_actions
        self.n_actions += 1
        self.applied.append(0.0)
        self.status.append(0)
        action = survival_action_from_event(
            heal_event,
            1.0,
            self.index_of[recipient_id],
            self.index_of,
            subject_id=recipient_id,
            aidx=aidx,
        )
        insertion = max(self.current_index + 1, 0)
        while (
            insertion < len(self.actions)
            and self.actions[insertion].sort_key <= action.sort_key
        ):
            insertion += 1
        self.actions.insert(insertion, action)


__all__ = ["ScoreLedger"]
