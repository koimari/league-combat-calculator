"""Typed item-cleanse eligibility and action-downtime truncation kernel
(roadmap P2 Slice 4).

One dependency-light leaf owns the typed contracts for item actives that
remove crowd-control debuffs — Mikael's Blessing (Purify), Quicksilver Sash
and Mercurial Scimitar (Quicksilver) — orthogonal to delivery type
(:mod:`delivery_eligibility`), crowd-control classification and immunity
(:mod:`crowd_control_eligibility`), and state lifecycle
(:mod:`state_lifecycle`).  The sourced tooltips those declarations are built
from live in :mod:`cleanse_declarations` and :mod:`champion_cleanses`, and the
span algebra the truncation runs on in :mod:`control_intervals`.  Nine
separation concerns:

- CONTROL CLASSIFICATION — reused from :mod:`crowd_control_eligibility`
  (:data:`KNOWN_CONTROL_KINDS`, :func:`classify_control`); unknown kinds
  fail closed with the named ``unknown_control`` reason.
- CLEANSE ELIGIBILITY — one sourced declaration per item
  (:data:`cleanse_declarations.ITEM_CLEANSE_DECLARATIONS`);
  ``CleanseEligibility.decide`` is a pure function of the activation and the
  recipient's ACTIVE control intervals at activation.
- ACTIVATION TIME — the walk's total order (``action_key``) resolves
  same-time packets; the decision identity is
  :func:`delivery_facts.stable_event_key`.
- TARGET SELECTION — each item declares its target scope
  (``self`` / ``explicit_selected_ally``); a packet whose recipient does
  not match the scope fails closed with ``target_not_selected``.
- USE CONSUMPTION — one use per item per fight (per-fight latch, the
  spell-shield precedent); a second activation fails closed with
  ``use_spent``; the sourced cooldown is receipted
  (:data:`ITEMS` cache carries ``cooldown: null`` for all three actives —
  :attr:`CleanseDeclaration.cooldown_source_gap` names the gap; the local
  client binaries carry 120 s (Mikael's) / 90 s (Mercurial) / 90-vs-0
  conflicting (QSS) — binary-cache-only values are receipted, never
  enforced).
- INTERVAL TRUNCATION — :func:`control_intervals.truncate_intervals` is a
  pure function: historical downtime before activation REMAINS; an active
  interval ENDS
  at activation (end clamped); a control landing AT activation (same-time
  packets resolve before the cleanse in the walk's total order) is removed
  entirely; controls landing AFTER activation are untouched (a cleanse
  creates NO immunity).
- HEAL — Mikael's Purify heals the target 100-250 by target level, sourced
  from the wiki atom ``heal.flat`` cf9fe930ebd40602.  The heal is a SEPARATE
  effect (its own packet and receipt entry) that fires even when no control
  is active.
- MOVEMENT UTILITY — Mercurial's 50% bonus total movement speed for 2 s,
  sourced from the wiki atom ``control.movement_speed`` 5e5f100f08a793f9,
  is a SEPARATE utility effect (its own packet and receipt entry).
- RECEIPTS — decision/recipient/use receipts with the exact field sets
  pinned by the acceptance matrix.

CASTABILITY (sourced): the wiki Cleanse atom
(``data/wiki-atoms/crowd-control-mobility.json``) and the local client
binaries (``data/bin/items.bin.json``, 16.15.8024387) evidence that
QSS/Mercurial self-casts are castable while disabled
(``canCastWhileDisabled: true``) but NOT under suppression
(``cannotBeSuppressed: true``; the atom: "castable while disabled, but not
under suppression/stasis"); Mikael's ``3222Active`` carries neither flag
so its cast stays gated by the walk's attacker crowd-control gate.  The
kernel encodes the self-scope castability rule as the named
``caster_control_blocks_cleanse`` denial; Mikael's gating is the walk's
pinned attacker-state gate (receipt ``attacker_state_blocked``).

Design rules (HANDOVER section 11): categorical mechanics are small typed
declarations with public receipts; missing values raise naming the
declaration; the kernel never invents a number or policy the caches do
not evidence.
"""

from __future__ import annotations

# pylint: disable=too-many-return-statements  # the decision path's named
# reasons map one-to-one onto returns.
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .cleanse_declarations import CleanseActivation
from .control_intervals import (
    _interval_bounds,
    _interval_kind,
    interval_active,
    merged_interval_duration,
    truncate_intervals,
)
from .control_spec import DISPLACEMENT_CC_KINDS
from .crowd_control_eligibility import KNOWN_CONTROL_KINDS
from .delivery_facts import stable_event_key
from .state_timeline import SourceReceipt

# ---------------------------------------------------------------------------
# Cleanse eligibility
# ---------------------------------------------------------------------------


#: Kinds a cleanse cannot be cast under (self-scope castability rule).
#: Sourced from the wiki Cleanse atom + client binary flags: QSS and
#: Mercurial carry canCastWhileDisabled and cannotBeSuppressed; Mikael's
#: 3222Active carries neither.  The atom's own wording — "castable while
#: disabled, but not under suppression/stasis" — names both, and the wiki
#: Stasis entry agrees: stasis "will prevent the activation of abilities
#: that would usually remove crowd control effects".
CAST_BLOCKING_CONTROL_KINDS: frozenset[str] = frozenset({"stasis", "suppression"})

#: Kinds no cleanse removes, whatever its item declares — the wiki Stasis
#: entry: "Cannot be removed by any means (except through death)".  This is
#: a property of the kind, not of the item, so it lives here once instead of
#: in every declaration's carve-out tuple.
#: https://wiki.leagueoflegends.com/en-us/Stasis
NEVER_CLEANSABLE_CONTROL_KINDS: frozenset[str] = frozenset({"stasis"})

#: Words an item tooltip carves out that no champion module can author, so
#: they never match an interval.  They stay in the declarations because the
#: declaration IS the sourced transcription of the tooltip; naming them here
#: is what keeps them from reading as a drifted kind
#: (tests/test_cc_kind_vocabulary.py).
TOOLTIP_ONLY_CONTROL_KINDS: frozenset[str] = frozenset({"disarm", "nearsight"})


def resolve_excluded_kinds(declared: Iterable[str]) -> frozenset[str]:
    """The kinds a declaration's carve-out protects — the ONE reader of
    ``excluded_control_kinds``, so the umbrella cannot resolve two ways.
    """
    kinds = frozenset(str(kind) for kind in declared)
    if kinds & DISPLACEMENT_CC_KINDS:
        kinds |= DISPLACEMENT_CC_KINDS
    return kinds | NEVER_CLEANSABLE_CONTROL_KINDS


def _control_entries(interval: Mapping[str, Any]) -> dict[str, Any]:
    """One receipt-shaped control entry from an interval row."""
    start, end = _interval_bounds(interval)
    return {
        "control_kind": _interval_kind(interval),
        "source": str(interval.get("source", "") or ""),
        "start": round(start, 9),
        "end": round(end, 9),
    }


@dataclass(frozen=True, slots=True)
class CleanseEligibility:
    """One item's cleanse eligibility contract.

    ``declaration`` is the sourced item declaration
    (:data:`ITEM_CLEANSE_DECLARATIONS`); ``source`` is the provenance
    record the walk attaches.  ``decide`` is a pure function of the
    activation and the recipient's ACTIVE control intervals at activation
    (the walk passes them; kernel rows author them) — same-time
    determinism comes from the walk's total order, which the kernel
    mirrors in :func:`delivery_eligibility.stable_event_key`.
    """

    declaration: dict[str, Any]
    source: SourceReceipt | None = None

    # -- helpers -----------------------------------------------------------

    def _item(self) -> str:
        return str(self.declaration.get("item", ""))

    def _excluded(self) -> frozenset[str]:
        return resolve_excluded_kinds(
            self.declaration.get("excluded_control_kinds", ())
        )

    def _scope(self) -> str:
        return str(self.declaration.get("target_scope", ""))

    def public_receipt(self) -> dict[str, Any]:
        """JSON-safe eligibility declaration receipt."""
        return {
            "item": self._item(),
            "active_name": self.declaration.get("active_name"),
            "target_scope": self._scope(),
            "excluded_control_kinds": sorted(self._excluded()),
            "cooldown_seconds": self.declaration.get("cooldown_seconds"),
            "cooldown_source_gap": bool(self.declaration.get("cooldown_source_gap")),
            "source": self.source.public() if self.source is not None else None,
        }

    # -- decision ----------------------------------------------------------

    def decide(
        self,
        action: CleanseActivation,
        *,
        holder: Mapping[str, Any] | None = None,
    ) -> CleanseDecision:
        """Decide one cleanse activation (deterministic, receipted).

        ``holder`` is the item holder's live use state (the walk resolves
        it; kernel rows may omit it — a fresh one-use state is assumed).
        The action reads: ``time``, ``source_key``, ``sequence``,
        ``event_id``, ``target`` (recipient participant id), ``holder``
        (owner participant id; defaults to the target for self items) and
        ``active_controls`` (the recipient's control intervals at
        activation).
        """
        activation = float(getattr(action, "time", 0.0) or 0.0)
        event_key = stable_event_key(action)
        target = str(getattr(action, "target", "") or "")
        holder_id = str(getattr(action, "holder", "") or "") or target
        intervals = [
            dict(interval)
            for interval in (getattr(action, "active_controls", None) or ())
        ]
        holder_state = dict(holder or {})
        raw_uses = holder_state.get("uses_remaining", 1)
        uses_remaining = int(raw_uses) if raw_uses is not None else 1
        item_held = holder_state.get("item_held", True)
        if not isinstance(item_held, bool):
            item_held = True
        excluded = self._excluded()
        scope = self._scope()

        # -- activation-level gates (denials never consume the use) --------
        if scope == "self":
            if target != holder_id:
                return self._decision(
                    eligible=False,
                    reason="target_not_selected",
                    action=action,
                    intervals=intervals,
                    activation=activation,
                    use_consumed=False,
                    event_key=event_key,
                )
        elif scope == "self_and_all_teammates":
            # P2 Slice 7 (Milio R): the walk authors one packet per
            # recipient (the E8d fan-out roster — Milio + every selected
            # teammate), so any authored target is valid; an empty target
            # fails closed (identity missing).  The caster-CC gate is the
            # WALK's attacker gate (the heal+marker rides it — the whole
            # cast is blocked while the caster is crowd-controlled); each
            # recipient's OWN control intervals decide here.
            if not target:
                return self._decision(
                    eligible=False,
                    reason="target_not_selected",
                    action=action,
                    intervals=intervals,
                    activation=activation,
                    use_consumed=False,
                    event_key=event_key,
                )
        elif scope == "explicit_selected_ally" and (not target or target == holder_id):
            return self._decision(
                eligible=False,
                reason="target_not_selected",
                action=action,
                intervals=intervals,
                activation=activation,
                use_consumed=False,
                event_key=event_key,
            )
        if not item_held:
            return self._decision(
                eligible=False,
                reason="not_armed",
                action=action,
                intervals=intervals,
                activation=activation,
                use_consumed=False,
                event_key=event_key,
            )
        if uses_remaining <= 0:
            return self._decision(
                eligible=False,
                reason="use_spent",
                action=action,
                intervals=intervals,
                activation=activation,
                use_consumed=False,
                event_key=event_key,
            )

        # -- interval analysis (fail closed on unknown kinds) --------------
        unknown = [
            interval
            for interval in intervals
            if _interval_kind(interval) not in KNOWN_CONTROL_KINDS
        ]
        if unknown:
            return self._decision(
                eligible=False,
                reason="unknown_control",
                action=action,
                intervals=intervals,
                activation=activation,
                use_consumed=False,
                event_key=event_key,
            )

        active = [i for i in intervals if interval_active(i, activation)]

        # Self-scope castability: a QSS/Mercurial self-cast cannot be
        # performed while the caster is suppressed or in stasis (cleanse
        # atom + binary cannotBeSuppressed).  The denial keeps the use.
        if scope == "self":
            blocked = [
                i for i in active if _interval_kind(i) in CAST_BLOCKING_CONTROL_KINDS
            ]
            if blocked:
                return self._decision(
                    eligible=False,
                    reason="caster_control_blocks_cleanse",
                    action=action,
                    intervals=intervals,
                    activation=activation,
                    use_consumed=False,
                    event_key=event_key,
                )

        eligible_active = [i for i in active if _interval_kind(i) not in excluded]
        if not eligible_active:
            # Nothing removable: the activation still happens (the use is
            # consumed) but the receipt names the rule.  ``use_spent`` is
            # ONLY ever decided from the holder's live use state above —
            # a list of historical intervals (nothing active) is
            # ``control_not_active``, never a spent-use guess.
            if not active:
                reason = "control_not_active"
                use_consumed = True
            else:
                reason = "excluded_control_kind"
                use_consumed = True
            return self._decision(
                eligible=False,
                reason=reason,
                action=action,
                intervals=intervals,
                activation=activation,
                use_consumed=use_consumed,
                event_key=event_key,
            )

        eligible_kinds = frozenset(KNOWN_CONTROL_KINDS) - excluded
        kept, removed = truncate_intervals(intervals, activation, eligible_kinds)
        return self._decision(
            eligible=True,
            reason="",
            action=action,
            intervals=intervals,
            activation=activation,
            use_consumed=True,
            event_key=event_key,
            _kept=kept,
            _removed=removed,
        )

    def _decision(
        self,
        *,
        eligible: bool,
        reason: str,
        action: CleanseActivation,
        intervals: list[dict[str, Any]],
        activation: float,
        use_consumed: bool,
        event_key: str,
        _kept: list[dict[str, Any]] | None = None,
        _removed: list[dict[str, Any]] | None = None,
    ) -> CleanseDecision:
        """Build the decision receipt from the analysis outcome.

        Only an eligible outcome truncates: every denial
        (control_not_active / excluded_control_kind / unknown_control /
        target_not_selected / not_armed / use_spent /
        caster_control_blocks_cleanse) leaves the interval lists untouched
        — ``removed_controls`` is empty and ``intervals_after`` is the full
        input list.
        """
        if _kept is None:
            if eligible:
                eligible_kinds = frozenset(KNOWN_CONTROL_KINDS) - self._excluded()
                _kept, _removed = truncate_intervals(
                    intervals, activation, eligible_kinds
                )
            else:
                _kept, _removed = list(intervals), []
        active = [i for i in intervals if interval_active(i, activation)]
        excluded = self._excluded()
        if reason == "caster_control_blocks_cleanse":
            # The cast is denied (the caster is suppressed or in stasis):
            # every active control is rejected with the castability reason —
            # nothing was removed.
            rejected = list(active)
            rejected_reason = "caster_control_blocks_cleanse"
        else:
            rejected = [
                i
                for i in active
                if _interval_kind(i) not in KNOWN_CONTROL_KINDS
                or _interval_kind(i) in excluded
            ]
            rejected_reason = (
                "excluded_control_kind"
                if reason != "unknown_control"
                else "unknown_control"
            )
        return CleanseDecision(
            eligible=eligible,
            reason=reason,
            item=self._item(),
            activation_time=float(activation),
            target=str(getattr(action, "target", "") or ""),
            event_key=event_key,
            active_controls_before=[_control_entries(i) for i in active],
            removed_controls=[
                {
                    **_control_entries(i),
                    "reason": "",
                }
                for i in _removed
            ],
            rejected_controls=[
                {**_control_entries(i), "reason": rejected_reason} for i in rejected
            ],
            intervals_after=[_control_entries(i) for i in _kept],
            downtime_before=merged_interval_duration(intervals),
            downtime_after=merged_interval_duration(_kept),
            use_consumed=use_consumed,
            declaration=self.declaration,
        )


@dataclass(frozen=True, slots=True)
class CleanseDecision:
    """One cleanse activation decision with its public receipts.

    ``eligible`` True means at least one active control was removed.
    ``eligible`` False carries a named ``reason``: ``control_not_active`` /
    ``excluded_control_kind`` / ``unknown_control`` /
    ``target_not_selected`` / ``not_armed`` / ``use_spent`` /
    ``caster_control_blocks_cleanse`` (fail-closed).  ``use_consumed`` is
    True only when the activation actually happened (the item's one use is
    spent even when there was nothing removable).
    """

    eligible: bool
    reason: str = ""
    item: str = ""
    activation_time: float = 0.0
    target: str = ""
    event_key: str = ""
    active_controls_before: list[dict[str, Any]] = field(default_factory=list)
    removed_controls: list[dict[str, Any]] = field(default_factory=list)
    rejected_controls: list[dict[str, Any]] = field(default_factory=list)
    intervals_after: list[dict[str, Any]] = field(default_factory=list)
    downtime_before: float = 0.0
    downtime_after: float = 0.0
    use_consumed: bool = False
    declaration: dict[str, Any] = field(default_factory=dict)

    def public_receipt(self) -> dict[str, Any]:
        """JSON-safe decision receipt (the matrix's exact field set)."""
        return {
            "eligible": self.eligible,
            "reason": self.reason,
            "item": self.item,
            "activation_time": round(self.activation_time, 6),
            "target": self.target,
            "active_controls_before": [
                dict(entry) for entry in self.active_controls_before
            ],
            "removed_controls": [dict(entry) for entry in self.removed_controls],
            "rejected_controls": [dict(entry) for entry in self.rejected_controls],
            "intervals_after": [dict(entry) for entry in self.intervals_after],
            "downtime_before": round(self.downtime_before, 6),
            "downtime_after": round(self.downtime_after, 6),
            "use_consumed": self.use_consumed,
        }


__all__ = [
    "CAST_BLOCKING_CONTROL_KINDS",
    "CleanseDecision",
    "CleanseEligibility",
    "resolve_excluded_kinds",
]
