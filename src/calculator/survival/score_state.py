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

from .actions import SurvivalAction


class ScoreLedger:
    """Parallel-array observation of the shared kernel.

    ``applied[aidx]`` holds each action's applied amount (the accumulator's
    per-attacker float-sum order replays it) and ``status[aidx]`` is the
    write-once trigger marker.
    """

    __slots__ = ("n_actions", "applied", "status")

    # Ledger capability flags (issue #171): the kernel's hot loop skips
    # building annotate()/event-field kwargs entirely when the ledger
    # would drop them, instead of paying for round() calls a no-op absorbs.
    records_annotations = False
    records_event_fields = False

    def __init__(self, n_actions: int) -> None:
        self.n_actions = n_actions
        self.applied: list[float] = [0.0] * n_actions
        self.status = bytearray(n_actions)

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
        preserve_reason: bool = False,
    ) -> None:
        # Skipped actions leave their applied slot at zero, exactly like the
        # legacy compiled walk's ``continue`` before any state mutation.
        #
        # ``preserve_reason`` is accepted because the kernel passes it, and
        # this adapter keeps no reason to preserve.  It was absent while the
        # only caller passing it was the redirect-cancelled arm, which is
        # how a keyword the shared kernel sends came to be a ``TypeError``
        # the score walk had simply never reached: an adapter that answers a
        # narrower protocol than the one kernel sends is a crash waiting for
        # its first roster.
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

    # -- walk-authored scheduling (fail closed) -------------------------------
    def schedule_heal(self, heal_event: dict[str, Any], recipient_id: str) -> None:
        # Compilation rejects every mechanic that could author a
        # walk-time recovery (Maw omnivamp, Doran's Shield Enduring Focus,
        # Death's Dance Defy), so this must never fire in score mode.
        raise AssertionError(
            "score ledger cannot schedule walk-authored heals; "
            "the packet should have failed compilation"
        )


__all__ = ["ScoreLedger"]
