"""Outcome adapter — the write-once ledger the end-of-walk projection reads.

The third kernel-side ledger, beside :mod:`survival.score_state` and
:mod:`survival.receipt_state`, and the one the views eventually project
(D-64).  It is kernel-side rather than a ``program/`` type on purpose: the
walk writes into it inside the hot loop, and the phase's dependency runs
``program -> survival`` and never back.

What makes it different from the two adapters it sits beside is not what it
observes but what it *forbids*.  The receipt adapter's channel is the event
dict: the walk writes a field, a later transition writes it again, and the
serialized receipt shows whichever write came last.  That is how a receipt
and a score diverge without either one being wrong at any single line, and
it is the shape this campaign exists to remove.  So here:

* every field is **write-once**.  A second write of a field a transition
  already answered raises :class:`OutcomeRewritten`, naming the slot, the
  field and both values.  Writing the *same* value twice is still a rewrite:
  two rules answering one question happen to agree today and are one edit
  away from not agreeing, and a ledger that tolerates the agreement cannot
  see the disagreement coming.
* a later transition may still revise an earlier one, but only through
  :meth:`adjust`, only with a member of :class:`AdjustmentReason`, and only
  onto a field that was written.  The adjustment is kept in order beside the
  value, so the revision is a *record* rather than an overwrite: the original
  answer, the new one and the rule that changed its mind all survive.
* :class:`AdjustmentReason` has exactly one member, and no default.
  Knight's Vow's holder-health gate is the one live case in the tree -- a
  redirect child cancelled and its parent's damage restored after both were
  already priced -- so a second reason is a decision somebody argues for,
  not a value somebody passes.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .actions import NO_SLOT, SurvivalAction
from ..ability_spec import Measured, Quantity, Starved, StructuralZero
from ..trigger_stream import StarvedSignal

__all__ = [
    "Adjustment",
    "AdjustmentReason",
    "DuplicateApplied",
    "OUTCOME_FIELDS",
    "Outcome",
    "OutcomeLedger",
    "OutcomeRewritten",
    "UnwrittenAdjustment",
    "outcome_quantity",
]


def outcome_quantity(value: Any, skipped_reason: str | None) -> Quantity:
    """One outcome field's quantity, given the walk's verdict on its transition.

    The two answers a refusal makes different, written once so that the
    ledger and the projection that publishes the ledger's numbers cannot
    reach different conclusions about one transition:

    * the walk priced the transition, so a rule ran and produced this number
      — ``Measured``, zero included;
    * the walk refused it and named a reason, so the zero standing where the
      number would have been is the *declaration's* answer and the reason is
      its receipt — ``StructuralZero`` (D-24, D-72).

    The one case where both readings are available is a refused transition
    whose field still carries a number, and it resolves to ``Measured``
    deliberately.  That number was produced by the rule that priced the
    packet before a later gate refused to *deliver* it; calling it a
    declared zero would publish ``0.0`` where a computed value stands, and a
    disposition that moves a published number is a re-label with a value
    change hiding inside it.  Naming which of the two a leaf is may never
    change what the leaf says.

    A module-level function rather than a ledger method because its two
    callers hold the same fact in two shapes: the ledger holds an action
    slot's written fields, and the serialized receipt holds the event row
    the same transition wrote.  ``ReceiptLedger`` drives both from one
    ``skip``, so the reason either one reads is the same reason — but only
    one of them can be reached through a slot.
    """
    if skipped_reason is not None and not value:
        return StructuralZero(reason=str(skipped_reason))
    return Measured(amount=float(value or 0.0))


class AdjustmentReason(Enum):
    """Why a later transition is allowed to revise an earlier outcome.

    ``HOLDER_HEALTH_GATE`` is Knight's Vow: the direct share of a redirected
    packet is expanded and priced so its recipient can be repriced, and if
    the holder is already at or below the sacrifice threshold the walk
    cancels that child and restores the unredirected packet on the original
    target.  Both numbers were already written when the gate fires, which is
    exactly why the revision needs a name.
    """

    HOLDER_HEALTH_GATE = "holder_health_gate"


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

    A member of :class:`~trigger_stream.StarvedSignal` since the umbrella's
    Amendment G: two rules answered one question differently, so this record
    cannot answer it, and a leaf with no answer a rule computed is exactly
    what ``STARVED`` names.  Before the amendment this reached a request as a
    bare 500 — a failure with no receipt and no named field, which is the
    shape the boundary exists to prevent.
    """

    def __init__(self, slot: int, field: str, old: Any, new: Any) -> None:
        super().__init__(
            f"action slot {slot} already recorded {field}={old!r}; a second "
            f"write of {new!r} would replace an answer rather than revise it. "
            f"A revision goes through OutcomeLedger.adjust with an "
            f"AdjustmentReason.",
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
    """Two producers claimed the same applied contribution (D-62).

    "A sum may never mix views" forbids adding a pair-engine preview to a
    coupled delivery.  It does **not** forbid two *deliveries* of one
    mechanic to one subject on one event, which is the other half of the
    double count and the shape keeping ``_apply_command_amp`` alive beside a
    new coupled pricer would have: both contributions ``APPLIED``, both
    real, one of them counted twice with no symptom.

    So the ledger refuses at the second write.  The key is the criterion's
    own -- ``(mechanic, subject, event_id)`` -- read off the action as its
    packet source, its subject slot and its interned event slot.
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


class UnwrittenAdjustment(StarvedSignal):
    """An adjustment named a field no transition had produced a value for."""

    def __init__(self, slot: int, field: str) -> None:
        super().__init__(
            f"action slot {slot} has no recorded {field} to adjust; an "
            f"adjustment revises an answer and cannot invent one",
            field,
            f"action slot {slot}",
            (
                "the adjustment revises an answer this ledger never recorded, "
                "so there is no value for the revision to replace"
            ),
        )
        self.slot = slot


@dataclass(frozen=True, slots=True)
class Adjustment:
    """One reasoned revision of one already-written field.

    Attributes:
        slot: the action slot whose outcome is revised.
        field: which of :data:`OUTCOME_FIELDS` changes.
        value: the value that replaces the written one.
        reason: the named rule that changed its mind.  Required, and a
            member: a free-string reason is a comment with a colon in it.
    """

    slot: int
    field: str
    value: Any
    reason: AdjustmentReason

    def __post_init__(self) -> None:
        """A revision names a real field and a declared reason, or is not one."""
        if self.field not in OUTCOME_FIELDS:
            raise ValueError(
                f"{self.field!r} is not an outcome field; "
                f"one of {list(OUTCOME_FIELDS)} was expected"
            )
        if not isinstance(self.reason, AdjustmentReason):
            raise ValueError("Adjustment.reason must be an AdjustmentReason")


@dataclass(frozen=True, slots=True)
class Outcome:
    """What one transition did to one subject, as the projection reads it.

    ``applied`` is the amount the transition delivered; ``absorbed`` the part
    a barrier took; ``to_health`` the part that reached health; ``overkill``
    the part past zero.  ``skipped_reason`` is set exactly when the walk
    refused the transition, and then the four numbers are the refusal's
    zeros rather than computed ones.

    ``adjustments`` is the ordered revision log for this slot -- empty for
    the overwhelming majority of transitions, and the whole story for the one
    that was revised.
    """

    applied: float = 0.0
    absorbed: float = 0.0
    to_health: float = 0.0
    overkill: float = 0.0
    skipped_reason: str | None = None
    adjustments: tuple[Adjustment, ...] = ()

    @property
    def was_skipped(self) -> bool:
        """Whether the walk refused this transition rather than pricing it."""
        return self.skipped_reason is not None


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
        "annotating",
        "records_annotations",
        "_applied_by",
        "_fields",
        "_adjustments",
        "_status",
    )

    records_event_fields = True

    # The kernel's write kwargs are named for the event dict the receipt
    # adapter serializes.  This is the projection of those names onto the
    # four outcome fields -- one mapping, so a kernel rename is one edit and
    # an unmapped kwarg is ignored here rather than silently becoming a
    # fifth outcome field.
    #
    # ``live_damage`` is **not** here, and the omission is the ruling rather
    # than an oversight.  ``transitions`` writes it once, at the one
    # ``annotate`` call that also writes ``pair_damage``, and its own module
    # docstring lists the pair with ``overkill`` under *diagnostics*: it is
    # the packet's value after live re-pricing and **before** absorption,
    # while the applied outcome is what consumed shield and health, written
    # a few lines later as ``damage``.  The two are equal exactly when
    # nothing overkilled, which is why mapping both onto ``applied`` read as
    # harmless for as long as no walk drove this ledger -- and why it was a
    # question answered twice with two numbers the moment one did.
    # ``pair_damage``, the same annotation's other half, was already
    # unmapped; this is its sibling joining it.
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
        self._adjustments: dict[int, list[Adjustment]] = {}
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

        D-62's uniqueness, enforced where the contribution is written rather
        than checked afterwards: a second producer of an applied number for
        one ``(mechanic, subject, event_id)`` is a double count, and a double
        count that raises is one nobody has to notice.

        **An action carrying no event id is outside the rule, and says so.**
        The key's third component is the event the contribution is *for*, so
        an action at ``NO_SLOT`` has no "one event" for a second producer to
        contribute to twice, and two such actions are two events nobody
        numbered rather than one event priced twice.  Keying them all under
        the same absent id would make the second heal of a hand-authored
        fixture a double count -- a rule reporting a defect it invented.
        So they are left unclaimed rather than keyed under one absent id.
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

    # -- reasoned revision --------------------------------------------------
    def adjust(self, adjustment: Adjustment) -> None:
        """Revise one written field, keeping the revision in order.

        Raises:
            UnwrittenAdjustment: the field was never written, so there is no
                answer to revise.
        """
        recorded = self._fields.get(adjustment.slot)
        if recorded is None or adjustment.field not in recorded:
            raise UnwrittenAdjustment(adjustment.slot, adjustment.field)
        recorded[adjustment.field] = adjustment.value
        self._adjustments.setdefault(adjustment.slot, []).append(adjustment)

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
            adjustments=tuple(self._adjustments.get(action_slot, ())),
        )

    def quantity(self, action_slot: int, field: str) -> Quantity:
        """One outcome field as a :class:`Quantity` — where a leaf is born.

        The kernel holds raw floats; this is the boundary at which a number
        acquires a disposition (D-72), and the wrapping is pure: ``Measured``
        wraps the float :meth:`get` would have returned, unchanged.

        The three answers are the three things the ledger actually knows:

        * a transition wrote the field, so a rule ran and produced it —
          ``Measured``;
        * the walk refused the transition and named a reason, so zero is the
          answer and the reason is the receipt — ``StructuralZero``;
        * no transition wrote it and none refused it, so this ledger cannot
          answer the question at all — ``Starved``, which raises
          ``ProjectionStarvation`` when somebody reads it rather than
          returning a zero that would be indistinguishable from a computed
          one.  That third case is the campaign's invariant, at the boundary
          where the number is born.

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

        Most transitions produce one or two of the four — a heal writes
        ``applied`` and nothing else — so the rest come back ``Starved`` by
        the rule above.  That is the point rather than a rough edge: the
        ledger does not know which fields a given transition was supposed to
        produce, the projection does, and a projection that asks for a number
        no rule was ever going to write should hear about it.
        """
        return {
            field: self.quantity(action_slot, field)
            for field in OUTCOME_FIELDS
            if field != "skipped_reason"
        }

    def applied_contributions(self) -> Mapping[tuple[Any, ...], int]:
        """Every ``(mechanic, subject, event_id)`` that produced an applied
        number, mapped to the one action slot that produced it.

        Returned so the property is readable as well as enforced: a
        uniqueness rule whose only evidence is the absence of an exception is
        a rule nobody can count.
        """
        return dict(self._applied_by)

    def slots(self) -> Iterator[int]:
        """Every slot this ledger recorded anything for, in write order."""
        return iter(self._fields)

    def adjustments(self) -> tuple[Adjustment, ...]:
        """Every revision this walk made, slot by slot in write order."""
        return tuple(
            adjustment
            for slot in self._fields
            for adjustment in self._adjustments.get(slot, ())
        )
