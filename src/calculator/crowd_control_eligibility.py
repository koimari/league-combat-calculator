"""Typed crowd-control classification and immunity-eligibility kernel (roadmap P2 Slice 3).

One dependency-light leaf owns the typed contracts for crowd-control
classification and Black-Shield-style immunity, orthogonal to delivery
type (:mod:`delivery_eligibility`) and state lifecycle
(:mod:`state_lifecycle`).  Four orthogonal concerns:

- CONTROL CLASSIFICATION — ``ability_spec.ACTION_BLOCKING_CC_KINDS`` (the
  sourced hard set that adds action downtime) and its complement
  ``ability_spec.NON_BLOCKING_CC_KINDS``.  This module classifies with
  those two names rather than aliasing them: one classification, one
  name-pair.  The two partition :data:`KNOWN_CONTROL_KINDS`, which IS the
  authoring vocabulary ``ability_spec.CC_KIND_VOCABULARY`` — there is no
  second list of kinds.
  :func:`classify_control` is a deterministic pure function of the
  action's ``cc_kind``; a kind outside the known set is ``unknown`` and
  FAILS CLOSED with the named ``unknown_control`` reason
  (:class:`UnknownControlError` for the strict API).  A packet with no
  control markers is ``kind == ""`` and never reports a control block.
- IMMUNITY ELIGIBILITY — :class:`CrowdControlEligibility` (window from
  :class:`delivery_eligibility.DefenseWindow`, holder source, source
  receipt); ``decide`` returns a :class:`CrowdControlDecision` with a
  named reason: "" / ``outside_window`` / ``control_not_blocking`` /
  ``unknown_control`` / ``shield_not_held``.
- SHIELD OWNERSHIP — :func:`immunity_holder` returns the EXACT
  ``shield_ledger.TimedShield`` entry (source match, ``amount > 1e-9``,
  ``expires_at > event_time``).  That exact ledger entry is the ONLY
  immunity holder: another shield granted by a different source never
  keeps immunity active, and expiry or depletion clears it immediately.
- PACKET ORDERING — :func:`delivery_eligibility.stable_event_key`
  (``source_key:time:sequence``) is the decision identity; same-time
  packets resolve through the survival walk's total order (``action_key``),
  so decisions are deterministic.

SAME-HIT ORDERING (documented fail-closed): whether a packet whose own
damage fully depletes the shield still has its control blocked is the
walk's gate position, not a per-event decision.  The local caches carry
one prose statement (wiki notes: "negates crowd control effects before
any magic damage is absorbed; even if the shield is broken by an enemy
dealing enough damage, its associated disables will not apply") but no
second provenance (Riot tooltips say only "until it breaks"; game
scripts are not cached).  While the rule is single-provenance,
:func:`same_hit_ordering` FAILS CLOSED by raising
:class:`MissingSameHitRuleError` (``reason == "missing_same_hit_rule"``)
instead of certifying an unverified rule; the survival walk keeps its
pinned gate-before-absorb order (R6a) and the denial is the observable
receipt.  The shield-destroying exception ("Shield-destroying effects
bypass this...") and the allied-CC exclusion have no modeled source in
the calculator and are declared follow-ups.

Design rules (HANDOVER §11): categorical rules are small frozen
declarations with public receipts; missing values raise naming the
declaration; the kernel never invents a number or a policy the caches
do not evidence.
"""

from __future__ import annotations

# pylint: disable=too-many-lines,too-many-return-statements  # one
# dependency-light leaf owns the typed contracts; the decision path's named
# reasons map one-to-one onto returns, and splitting it would create a
# second decision path.
from dataclasses import dataclass
from typing import Any

from .ability_spec import (
    ACTION_BLOCKING_CC_KINDS,
    CC_KIND_VOCABULARY,
    NON_BLOCKING_CC_KINDS,
    NO_CONTROL_KIND,
)
from .delivery_eligibility import DefenseWindow, stable_event_key
from .shield_ledger import ShieldPools, TimedShield
from .state_lifecycle import SourceReceipt

# Floating-point tolerance shared with the damage/survival walks.  All
# kernel comparisons use the same 1e-9 convention as the engine receipts.
_EPS = 1e-9

# ---------------------------------------------------------------------------
# Control classification
# ---------------------------------------------------------------------------

#: Every kind the contract can classify: exactly what a champion module can
#: author (``ability_spec.CC_KIND_VOCABULARY`` less its reviewed "no
#: control" member, which reaches the classifier as the empty kind).
#: Derived, never listed — a second hand-written vocabulary here is what
#: left ``berserk``, ``cripple``, ``pull``, ``snare`` and ``stasis``
#: classifying ``unknown``, so every cleanse touching one failed closed.
#: Anything outside it is ``unknown`` and fails closed with the named
#: ``unknown_control`` reason.
KNOWN_CONTROL_KINDS: frozenset[str] = frozenset(CC_KIND_VOCABULARY) - {NO_CONTROL_KIND}


@dataclass(frozen=True, slots=True)
class ControlProfile:
    """One event's control classification.

    ``kind`` is the lowercased authored ``cc_kind`` ("" for a packet with
    no control markers — a plain damage packet).  ``blocking`` is True
    for ``ability_spec.ACTION_BLOCKING_CC_KINDS``; ``unknown`` is True for
    kinds outside :data:`KNOWN_CONTROL_KINDS` (fail-closed marker).  A
    packet with no control markers is never unknown.
    """

    kind: str = ""
    blocking: bool = False
    unknown: bool = False
    unknown_markers: tuple[str, ...] = ()

    def public_receipt(self) -> dict[str, Any]:
        """JSON-safe classification receipt."""
        return {
            "kind": self.kind,
            "blocking": self.blocking,
            "unknown": self.unknown,
            "unknown_markers": list(self.unknown_markers),
        }


class UnknownControlError(ValueError):
    """Raised when a strict classification needs a kind the contract does
    not know.  Naming the event keeps the failure actionable."""

    reason = "unknown_control"


def _action_cc_kind(action: Any) -> str:
    """Read the typed control-kind marker, defaulting to ""."""
    return str(getattr(action, "cc_kind", "") or "").strip().lower()


def classify_control(action: Any) -> ControlProfile:
    """Classify one action's crowd control from its typed ``cc_kind``.

    Deterministic by construction: the profile is a pure function of the
    action's ``cc_kind``.  "" means no control markers (a plain damage
    packet — never a control block); a kind outside
    :data:`KNOWN_CONTROL_KINDS` is ``unknown`` (fail-closed).
    """
    kind = _action_cc_kind(action)
    if not kind:
        return ControlProfile(kind="", blocking=False, unknown=False)
    if kind in ACTION_BLOCKING_CC_KINDS:
        return ControlProfile(kind=kind, blocking=True, unknown=False)
    if kind in NON_BLOCKING_CC_KINDS:
        return ControlProfile(kind=kind, blocking=False, unknown=False)
    return ControlProfile(
        kind=kind,
        blocking=False,
        unknown=True,
        unknown_markers=("unknown_control_kind",),
    )


def required_control_class(action: Any) -> str:
    """Return one known control kind or fail closed.

    Raises :class:`UnknownControlError` when the action carries a kind
    outside :data:`KNOWN_CONTROL_KINDS` or no kind at all.  This is the
    strict API for a decision that MUST resolve to a known control; the
    eligibility decision path uses the receipt form instead.
    """
    profile = classify_control(action)
    if not profile.kind or profile.unknown:
        raise UnknownControlError(
            f"unknown control kind {profile.kind!r} for "
            f"{getattr(action, 'source_key', '?')!r} at "
            f"t={getattr(action, 'time', 0.0)}"
        )
    return profile.kind


# ---------------------------------------------------------------------------
# Shield ownership — the exact ledger entry is the only immunity holder
# ---------------------------------------------------------------------------


def immunity_holder(
    pools: ShieldPools, holder_source: str, event_time: float = 0.0
) -> TimedShield | None:
    """The exact immunity-holding shield ledger entry, or None.

    The holder is the :class:`shield_ledger.TimedShield` whose ``source``
    equals ``holder_source``, whose remaining ``amount`` is above ``1e-9``,
    and whose ``expires_at`` is strictly after ``event_time``.  Depletion and
    expiry each clear immunity at once, and no other shield ever matches:
    the exact Black Shield entry is the only immunity holder.
    """
    if not holder_source:
        return None
    for shield in pools.timed:
        if shield.source == holder_source:
            if shield.amount > _EPS and shield.expires_at > event_time + _EPS:
                return shield
            return None
    return None


def active_until(entry: TimedShield | None) -> float:
    """The immunity window's end for one holder entry (0.0 when absent)."""
    if entry is None:
        return 0.0
    return float(entry.expires_at)


# ---------------------------------------------------------------------------
# Immunity eligibility
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CrowdControlEligibility:
    """One immunity source's eligibility contract (window + holder source).

    ``name`` is the typed immunity kind (``crowd_control_immunity`` for
    Black Shield).  ``window`` is the sourced shield lifetime (start
    inclusive, end exclusive — the survival walk's convention);
    ``holder_source`` names the exact ledger entry that holds immunity.
    ``decide`` is a pure function of the event and the holder entry —
    same-time determinism comes from the walk's total order, which the
    kernel mirrors in :func:`delivery_eligibility.stable_event_key`.
    """

    name: str
    window: DefenseWindow
    holder_source: str
    source: SourceReceipt | None = None

    def decide(
        self, action: Any, _attacker: Any = None, *, holder: TimedShield | None = None
    ) -> "CrowdControlDecision":
        """Decide eligibility for one event (deterministic, receipted).

        The attacker parameter mirrors the delivery-eligibility decision
        APIs (immunity selects every hostile control source; it is not
        read here).  ``holder`` is the exact ledger entry
        (:func:`immunity_holder`) — the walk resolves it against the
        live pools so depletion/expiry clear immunity immediately.
        """
        profile = classify_control(action)
        event_key = stable_event_key(action)
        event_time = float(getattr(action, "time", 0.0) or 0.0)
        if profile.unknown:
            return CrowdControlDecision(
                eligible=False,
                reason="unknown_control",
                control=profile,
                shield_source=self.holder_source,
                event_key=event_key,
            )
        if not profile.blocking:
            return CrowdControlDecision(
                eligible=False,
                reason="control_not_blocking",
                control=profile,
                shield_source=self.holder_source,
                event_key=event_key,
            )
        if not self.window.active_at(event_time):
            return CrowdControlDecision(
                eligible=False,
                reason="outside_window",
                control=profile,
                shield_source=self.holder_source,
                event_key=event_key,
            )
        if holder is None:
            return CrowdControlDecision(
                eligible=False,
                reason="shield_not_held",
                control=profile,
                shield_source=self.holder_source,
                event_key=event_key,
            )
        return CrowdControlDecision(
            eligible=True,
            reason="",
            control=profile,
            shield_source=self.holder_source,
            shield_amount_before=max(0.0, float(holder.amount)),
            active_until=active_until(holder),
            event_key=event_key,
        )

    def public_receipt(self) -> dict[str, Any]:
        """JSON-safe eligibility declaration receipt."""
        return {
            "name": self.name,
            "window": self.window.public_receipt(),
            "holder_source": self.holder_source,
            "source": self.source.public() if self.source is not None else None,
        }


@dataclass(frozen=True, slots=True)
class CrowdControlDecision:
    """One immunity decision with its public receipt.

    ``eligible`` True means the control is blocked (no action downtime
    added).  ``eligible`` False carries a named ``reason``:
    ``outside_window`` / ``control_not_blocking`` / ``unknown_control`` /
    ``shield_not_held`` (fail-closed).  Denied events apply their control
    through the walk untouched (except unknown kinds, which the model has
    no downtime semantics for — the decision receipt is the denial).
    """

    eligible: bool
    reason: str = ""
    control: ControlProfile = ControlProfile()
    shield_source: str = ""
    shield_amount_before: float = 0.0
    active_until: float = 0.0
    event_key: str = ""

    def public_receipt(self) -> dict[str, Any]:
        """JSON-safe decision receipt.

        Shield amounts report at the packet's public damage precision
        (1 decimal) — the convention the acceptance matrix pins for
        before/after parity; the active-until time stays at 6 decimals.
        """
        return {
            "eligible": self.eligible,
            "reason": self.reason,
            "control": self.control.public_receipt(),
            "shield_source": self.shield_source,
            "shield_amount_before": round(self.shield_amount_before, 1),
            "active_until": round(self.active_until, 6),
            "event_key": self.event_key,
        }


# ---------------------------------------------------------------------------
# Same-hit ordering (documented fail-closed; see module notes)
# ---------------------------------------------------------------------------


class MissingSameHitRuleError(ValueError):
    """Raised while the same-hit damage/control ordering is unverified.

    The local caches carry only ONE prose statement of the rule (the wiki
    notes); no Riot tooltip or cached game script states the ordering.  A
    single-provenance rule is not enough to certify: the contract fails
    closed with the named ``missing_same_hit_rule`` reason instead of
    inventing behavior.
    """

    reason = "missing_same_hit_rule"


def same_hit_ordering() -> tuple[str, SourceReceipt]:
    """The verified same-hit ordering rule and its receipt.

    Raises :class:`MissingSameHitRuleError` while the ordering is
    single-provenance: the wiki notes are the only local source, so the rule
    stays uncertified until a second provenance confirms it.
    """
    raise MissingSameHitRuleError(
        "same-hit damage/control ordering is unverified: the wiki notes "
        "state the gate-before-absorb rule but no second provenance "
        "(Riot tooltips say only 'until it breaks'; game scripts are not "
        "cached); the contract fails closed with the named "
        "missing_same_hit_rule reason"
    )


__all__ = [
    "CrowdControlDecision",
    "CrowdControlEligibility",
    "ControlProfile",
    "KNOWN_CONTROL_KINDS",
    "MissingSameHitRuleError",
    "UnknownControlError",
    "active_until",
    "classify_control",
    "immunity_holder",
    "required_control_class",
    "same_hit_ordering",
]
