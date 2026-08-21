"""Score adapter — the parallel-array ledger for the optimizer path.

Drives the same shared walk (:func:`~survival.transitions.run_survival_walk`)
and the same canonical state dicts as the receipt adapter, but observes
transitions into parallel arrays: per-action ``applied`` slots and the
write-once trigger ``status`` bytearray.  It never annotates events, and it
schedules a walk-authored recovery packet only when its wiring handed it the
live actions list and the one action builder (P3 package 3T: Maw's
post-Lifeline omnivamp heals); wiring that did not is an assertion, never a
dropped heal.

The kernel's applied-amount observation is the only write the score ledger
records: ``write(action, damage=...)`` for damage actions and
``write(action, applied_amount=...)`` for heals and shields, each assigning
``applied[aidx]`` without duplicating any arithmetic.  The per-attacker
damage-order lists and support entries live on the compilers, and
:mod:`survival.accumulate` sums them in a fixed float-addition order.
"""

from __future__ import annotations

from typing import Any
from collections.abc import Callable, Mapping

from .actions import SurvivalAction, TransitionRank, action_key


class ScoreLedger:
    """Parallel-array observation of the shared kernel.

    ``applied[aidx]`` holds each action's applied amount, which the
    accumulator sums per attacker, and ``status[aidx]`` is the write-once
    trigger marker.  Holding the live actions list lets the ledger grow both
    arrays for a walk-authored heal, matching the receipt adapter.
    """

    __slots__ = (
        "n_actions",
        "applied",
        "status",
        "actions",
        "index_of",
        "current_index",
        "compile_event",
    )

    # Ledger capability flags: the kernel's hot loop skips building
    # annotate()/event-field kwargs entirely when the ledger would drop them,
    # instead of paying for round() calls a no-op absorbs.
    records_annotations = False
    records_event_fields = False

    def __init__(
        self,
        n_actions: int,
        *,
        actions: list | None = None,
        index_of: Mapping | None = None,
        compile_event: Callable[..., SurvivalAction] | None = None,
    ) -> None:
        """The arrays, plus the builder this adapter may not reach for itself.

        The one ``SurvivalAction`` constructor lives in ``program/compile.py``,
        which ``survival/`` may not import, so ``compile_event`` is injected.
        A ledger that schedules no walk-authored heal never needs one; one that
        does raises in :meth:`schedule_heal` rather than dropping the recovery.
        """
        self.n_actions = n_actions
        self.applied: list[float] = [0.0] * n_actions
        self.status = bytearray(n_actions)
        self.actions: list | None = actions
        self.index_of: Mapping | None = index_of
        self.current_index: int = -1
        self.compile_event: Callable[..., SurvivalAction] | None = compile_event

    # -- observation ---------------------------------------------------------
    # pylint: disable=unused-argument  # protocol-shaped no-op
    def write(self, action: SurvivalAction, **fields: Any) -> None:
        """Record the applied amounts the kernel observes; nothing else."""
        if "damage" in fields:
            self._record(action, fields["damage"])
        elif "applied_amount" in fields:
            self._record(action, fields["applied_amount"])

    def restore(self, action: SurvivalAction, **fields: Any) -> None:
        """A packet input put back; one slot, last writer wins, so it is a write."""
        self.write(action, **fields)

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
        preserve_reason: bool = False,
    ) -> None:
        """A skipped action leaves its applied slot at zero, before any mutation."""
        # ``preserve_reason`` is accepted because the shared kernel sends it,
        # and an adapter answering a narrower protocol crashes on first use.
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
        """Score mode has no blocked-state consumer; compilation rejects those."""
        # A blocked action never gets the applied marker, failing the same gate.
        return None

    # -- walk-authored scheduling (P3 package 3T) ----------------------------
    def schedule_heal(self, heal_event: dict[str, Any], recipient_id: str) -> None:
        """Insert a walk-authored recovery packet beside the current action,
        mirroring the receipt adapter (Maw's post-Lifeline omnivamp heals).

        The compiled walk drives the identical kernel, so a trigger-time
        heal must land at the same timestamp with the same amount; the
        parallel arrays grow by one slot for the inserted action.
        """
        if self.actions is None or self.index_of is None or self.compile_event is None:
            raise AssertionError(
                "score ledger cannot schedule walk-authored heals without "
                "the live actions list, index_of and compile_event "
                "(compiler wiring)"
            )
        heal_event["_sk"] = action_key(
            float(heal_event.get("time", 0.0)),
            TransitionRank.RECOVERY,
            recipient_id,
            heal_event,
        )
        aidx = self.n_actions
        self.n_actions += 1
        self.applied.append(0.0)
        self.status.append(0)
        action = self.compile_event(
            heal_event,
            TransitionRank.RECOVERY,
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
