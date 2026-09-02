"""Outcome adapter: the write-once ledger the end-of-walk projection reads.

The third kernel-side ledger, beside :mod:`survival.score_state` and
:mod:`survival.receipt_state`, and the one the views project.  It is
kernel-side rather than a ``program/`` type because the walk writes into it
inside the hot loop, and the dependency runs ``program -> survival`` only.

What separates it from the two adapters beside it is what it forbids.  Every
field is write-once: a second write of a field a transition already answered
raises :class:`OutcomeRewritten`, naming the slot, the field and both values.
Writing the *same* value twice is still a rewrite, because two rules
answering one question happen to agree today and are one edit away from not
agreeing, and a ledger that tolerates the agreement cannot see the
disagreement coming.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from ..ability_spec import Measured, Quantity, Starved, StructuralZero
from ..trigger_stream import StarvedSignal
from .actions import NO_SLOT, SurvivalAction

__all__ = [
    "OUTCOME_FIELDS",
    "DuplicateApplied",
    "Outcome",
    "OutcomeLedger",
    "OutcomeRewritten",
    "outcome_quantity",
]


def outcome_quantity(value: float | None, skipped_reason: str | None) -> Quantity:
    """A refused zero is declared; any number a rule computed stays measured."""
    if skipped_reason is not None and not value:
        return StructuralZero(reason=str(skipped_reason))
    return Measured(amount=float(value or 0.0))


# The four numbers one transition produces about one subject, plus the
# receipt that stands in for them when it produced none.  ``skipped_reason``
# is in the record rather than beside it because a refused number and a
# number that came out zero are different answers, and a ledger that keeps
# the reason somewhere else is a ledger where they look the same.
OUTCOME_FIELDS: tuple[str, ...] = (
    "applied",
    "absorbed",
    "to_health",
    "overkill",
    "skipped_reason",
)


class OutcomeRewritten(StarvedSignal):
    """A transition answered a question another transition already answered.

    Carries the slot, the field and both values, because "a field was
    written twice" without them is a report nobody can act on.

    A :class:`~trigger_stream.StarvedSignal`, so the serving boundary turns it
    into a named 500 carrying a receipt: two rules answered one question
    differently, so this record holds no answer, which is what ``STARVED``
    names.
    """

    def __init__(self, slot: int, field: str, old: Any, new: Any) -> None:
        super().__init__(
            f"action slot {slot} already recorded {field}={old!r}; a second "
            f"write of {new!r} would replace an answer rather than revise it.",
            field,
            f"action slot {slot}",
            (
                f"two rules answered this field for one transition — {old!r} "
                f"and {new!r} — so the ledger holds no single answer to publish"
            ),
        )
        self.slot = slot
        self.old = old
        self.new = new


class DuplicateApplied(StarvedSignal):
    """Two producers claimed the same applied contribution.

    At most one applied contribution exists per ``(mechanic, subject,
    event_id)``.  Two deliveries of one mechanic to one subject on one event
    are both ``APPLIED`` and both real, so the double count has no symptom
    unless the ledger refuses at the second write.  The key is read off the
    action as its packet source, its subject slot and its interned event slot.
    """

    def __init__(self, key: tuple[Any, ...], first: int, second: int) -> None:
        """Name the contribution and both slots that claimed it."""
        mechanic, subject, event = key
        super().__init__(
            f"two applied contributions for mechanic {mechanic!r} on subject "
            f"{subject} at event {event}: action slots {first} and {second}. "
            "At most one applied contribution exists per "
            "(mechanic, subject, event_id) across all producers (D-62)",
            "applied",
            f"{mechanic!r} on subject {subject} at event {event}",
            (
                f"action slots {first} and {second} both claimed this "
                "contribution, so the applied number for the key is a double "
                "count rather than an answer"
            ),
        )
        self.key = key
        self.first = first
        self.second = second


@dataclass(frozen=True, slots=True)
class Outcome:
    """What one transition did to one subject, as the projection reads it.

    ``applied`` is the amount the transition delivered; ``absorbed`` the part
    a barrier took; ``to_health`` the part that reached health; ``overkill``
    the part past zero.  ``skipped_reason`` is set exactly when the walk
    refused the transition, and then the four numbers are the refusal's
    zeros rather than computed ones.
    """

    applied: float = 0.0
    absorbed: float = 0.0
    to_health: float = 0.0
    overkill: float = 0.0
    skipped_reason: str | None = None


class OutcomeLedger:
    """Write-once observation of the shared kernel, projected at end of walk.

    Implements the same adapter protocol :mod:`survival.transitions`
    documents, so it is a drop-in third ledger rather than a parallel
    channel: ``write``/``annotate``/``skip`` observe, ``trigger_applied`` /
    ``mark_applied`` / ``mark_blocked`` carry trigger linkage, and
    ``schedule_heal`` fails closed the way the score ledger's does.

    ``records_annotations`` and ``records_event_fields`` are verbosity flags
    rather than two different ledgers: the kernel skips building kwargs a
    ledger would drop, and this one drops annotations by default because an
    annotation is diagnostic text and an outcome is a number.
    """

    __slots__ = (
        "_applied_by",
        "_fields",
        "_status",
        "annotating",
        "records_annotations",
    )

    records_event_fields = True

    # The kernel's write kwargs are named for the event dict the receipt
    # adapter serializes.  This is the projection of those names onto the
    # four outcome fields: one mapping, so a kernel rename is one edit and
    # an unmapped kwarg is ignored here rather than silently becoming a
    # fifth outcome field.
    #
    # ``live_damage`` and ``pair_damage`` are deliberately absent.  Both are
    # diagnostics from the one ``annotate`` call: ``live_damage`` is the
    # packet's value after live re-pricing and before absorption, while the
    # applied outcome is what consumed shield and health.  The two are equal
    # exactly when nothing overkilled, so mapping either onto ``applied``
    # answers one question twice with two numbers.
    _WRITE_ALIASES: Mapping[str, str] = {
        "damage": "applied",
        "applied_amount": "applied",
        "_applied_to_health": "to_health",
        "overkill": "overkill",
        "shield_absorbed": "absorbed",
        "skipped_reason": "skipped_reason",
    }

    def __init__(self, *, annotating: bool = False) -> None:
        self.annotating = annotating
        self.records_annotations = annotating
        self._fields: dict[int, dict[str, Any]] = {}
        self._status: dict[int, str] = {}
        self._applied_by: dict[tuple[Any, ...], int] = {}

    # -- observation -------------------------------------------------------
    def write(self, action: SurvivalAction, **fields: Any) -> None:
        """Record this transition's outcome fields, each exactly once."""
        slot = action.aidx
        if slot == NO_SLOT:
            return
        recorded = self._fields.setdefault(slot, {})
        for name, value in fields.items():
            field = self._WRITE_ALIASES.get(name)
            if field is None:
                continue
            if field in recorded:
                raise OutcomeRewritten(slot, field, recorded[field], value)
            if field == "applied":
                self._claim_applied(action, slot)
            recorded[field] = value

    def _claim_applied(self, action: SurvivalAction, slot: int) -> None:
        """Record this slot as the one applied contribution for its key.

        An action at ``NO_SLOT`` has no event a second producer could
        contribute to, so it is left unclaimed rather than keyed under one
        absent id that would make two fixture heals a double count.
        """
        if action.event_slot == NO_SLOT:
            return
        key = (action.source_key, action.subject, action.event_slot)
        first = self._applied_by.setdefault(key, slot)
        if first != slot:
            raise DuplicateApplied(key, first, slot)

    # pylint: disable=unused-argument  # protocol shape
    def restore(self, action: SurvivalAction, **fields: Any) -> None:
        """An input, not an outcome.  Dropped, and that is the whole point."""

    def annotate(self, action: SurvivalAction, **fields: Any) -> None:
        """Diagnostics.  An outcome is a number, so these are dropped."""
        if self.annotating:
            self.write(action, **fields)

    # pylint: disable=unused-argument  # damage_phase is protocol shape
    def skip(
        self,
        action: SurvivalAction,
        reason: str,
        *,
        damage_phase: bool = False,
        preserve_reason: bool = False,
    ) -> None:
        """Record the walk's refusal to price this transition.

        ``preserve_reason`` keeps an earlier refusal, which is the one place
        a second ``skip`` on one action is legitimate: the holder-health gate
        stamps its reason on a child the redirect gate then skips again.
        ``damage_phase`` is the receipt adapter's presentation flag and is
        accepted so the protocol matches; the zeros it writes are this
        ledger's default, so it changes nothing here.
        """
        slot = action.aidx
        if slot == NO_SLOT:
            return
        recorded = self._fields.setdefault(slot, {})
        if "skipped_reason" in recorded:
            if preserve_reason:
                return
            raise OutcomeRewritten(
                slot, "skipped_reason", recorded["skipped_reason"], reason
            )
        recorded["skipped_reason"] = reason

    # -- trigger linkage ----------------------------------------------------
    def trigger_applied(self, action: SurvivalAction) -> bool:
        """Whether this action's trigger applied; no trigger passes."""
        if action.trigger_slot == NO_SLOT:
            return True
        return self._status.get(action.trigger_slot) == "applied"

    def mark_applied(self, action: SurvivalAction) -> None:
        """Mark this action's event as applied for trigger linkage."""
        if action.event_slot != NO_SLOT:
            self._status[action.event_slot] = "applied"

    def mark_blocked(self, action: SurvivalAction) -> None:
        """Mark this action's event as blocked for trigger linkage."""
        if action.event_slot != NO_SLOT:
            self._status[action.event_slot] = "blocked"

    # -- walk-authored scheduling (fail closed) -----------------------------
    def schedule_heal(self, heal_event: dict[str, Any], recipient_id: str) -> None:
        """Never: a walk-authored packet is an action, not an outcome."""
        raise AssertionError(
            f"the outcome ledger cannot schedule a walk-authored heal for "
            f"{recipient_id!r}; the packet ({heal_event.get('source_key', '')!r}) "
            f"belongs to the compiler, not to the projection"
        )

    # -- projection ---------------------------------------------------------
    def get(self, action_slot: int) -> Outcome:
        """This slot's outcome, as the end-of-walk projection reads it.

        A slot no transition wrote is a zero :class:`Outcome` with no
        ``skipped_reason``.  That is deliberate and is not a silent zero: an
        action the walk never reached produced no number and no refusal, and
        the disposition of *that* is decided by the projection which knows
        whether the slot was in the program at all.
        """
        recorded = self._fields.get(action_slot, {})
        return Outcome(
            applied=float(recorded.get("applied", 0.0) or 0.0),
            absorbed=float(recorded.get("absorbed", 0.0) or 0.0),
            to_health=float(recorded.get("to_health", 0.0) or 0.0),
            overkill=float(recorded.get("overkill", 0.0) or 0.0),
            skipped_reason=recorded.get("skipped_reason"),
        )

    def quantity(self, action_slot: int, field: str) -> Quantity:
        """One outcome field as a :class:`Quantity`, where a leaf is born.

        The kernel holds raw floats; this is the boundary at which a number
        acquires a disposition, and the wrapping is pure: ``Measured`` wraps
        the float :meth:`get` would have returned, unchanged.

        The three answers are the three things the ledger knows: a transition
        wrote the field, so ``Measured``; the walk refused it and named a
        reason, so ``StructuralZero``; neither happened, so ``Starved``, which
        raises ``ProjectionStarvation`` on read rather than returning a zero
        indistinguishable from a computed one.

        Raises:
            ValueError: *field* is not one of :data:`OUTCOME_FIELDS`.
        """
        if field not in OUTCOME_FIELDS or field == "skipped_reason":
            raise ValueError(
                f"{field!r} is not a numeric outcome field; one of "
                f"{[name for name in OUTCOME_FIELDS if name != 'skipped_reason']} "
                f"was expected"
            )
        recorded = self._fields.get(action_slot, {})
        if field in recorded:
            return outcome_quantity(recorded[field], None)
        skipped_reason = recorded.get("skipped_reason")
        if skipped_reason is not None:
            return outcome_quantity(0.0, skipped_reason)
        return Starved(
            field=field,
            producer=f"action slot {action_slot}",
            reason=(
                "the outcome ledger holds no write and no refusal for this "
                "slot, so it cannot say whether the rule ran"
            ),
        )

    def quantities(self, action_slot: int) -> dict[str, Quantity]:
        """Every numeric outcome field of one slot, each as a ``Quantity``.

        A field no transition wrote comes back ``Starved``: only the
        projection knows which fields a transition owed, so it hears about it.
        """
        return {
            field: self.quantity(action_slot, field)
            for field in OUTCOME_FIELDS
            if field != "skipped_reason"
        }

    def slots(self) -> Iterator[int]:
        """Every slot this ledger recorded anything for, in write order."""
        return iter(self._fields)
