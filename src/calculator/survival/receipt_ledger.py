"""The receipt ledger a walk writes its outcomes into."""

from __future__ import annotations

from collections.abc import Callable, Mapping, MutableMapping
from typing import Any

from .actions import action_key
from .outcome_state import OutcomeLedger
from .phases import TransitionRank
from .typed_action import SurvivalAction, TriggerLinkage


class ReceiptLedger(TriggerLinkage):
    """The annotating adapter: event-observation writes, trigger-linkage
    status by event id, and walk-authored recovery scheduling."""

    __slots__ = (
        "actions",
        "annotating",
        "annotations_written",
        "compile_event",
        "current_index",
        "expanded_healing",
        "healing",
        "index_of",
        "next_aidx",
        "outcomes",
        "records_annotations",
        "trigger_status",
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
        self.trigger_status: dict[int, str] = {}
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
