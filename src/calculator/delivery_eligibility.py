"""Which champion defense may interact with one incoming packet.

One declared rule per defense: the delivery classes it accepts
(:class:`DeliveryAcceptance`), the source and event it selects
(:class:`SourceSelection`) and the window it is armed in (start inclusive, end
exclusive, the survival walk's convention), together :class:`DefenseEligibility`.
``decide`` answers with an :class:`EligibilityDecision` carrying a public
receipt, and a packet whose delivery is ``unknown`` FAILS CLOSED here.

The rest of this kernel lives beside it, one concept per module: the packet and
combatant records in :mod:`delivery_facts`, the six delivery classes and their
classifier in :mod:`delivery_classes`, what happens to an accepted event in
:mod:`defense_composition`, and the spell shield's own lifecycle in
:mod:`spell_shield_eligibility` and :mod:`spell_shield_rearm`.

Deterministic ordering mirrors the survival walk's total order
``(time, phase, sequence, participant order, participant id, event id,
source)``; the stable per-event identity used for first-hit bookkeeping is
:func:`delivery_facts.stable_event_key` (``source_key:time:sequence``), the same
key the walk already uses for full-block events.

Numeric values come from the data cache through the consumer's typed accessors
(atom receipts ride the :class:`DefenseEligibility` source_atoms); categorical
rules are small frozen declarations with public receipts; a missing value raises
naming the declaration, and the kernel never invents a number.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .delivery_classes import (
    DELIVERY_AREA,
    DELIVERY_BASIC_ATTACK,
    DELIVERY_CLASSES,
    DELIVERY_PROJECTILE,
    DeliveryProfile,
    action_flag,
    classify_delivery,
)
from .delivery_facts import (
    CombatantFacts,
    DefenseWindow,
    PacketFacts,
    _attacker_name,
    stable_event_key,
)
from .state_timeline import SourceReceipt

# ---------------------------------------------------------------------------
# Eligibility: window, selection, acceptance
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SourceSelection:
    """Which incoming events the defense selects.

    ``blocked_sources`` selects by stable source slot (the exact matching
    semantics of the existing ``e_blocked_skillshots``: the event's
    ``source_key``, its ``source`` label, or ``attacker:source_key``,
    compared casefolded).  ``blocked_event_ids`` selects by the public
    per-fight event id (``attacker:defender:index``), exact match.  An
    empty selection selects everything.
    """

    blocked_sources: tuple[str, ...] = ()
    blocked_event_ids: tuple[str, ...] = ()

    def selects(
        self, action: PacketFacts, attacker: CombatantFacts | None
    ) -> tuple[bool, str]:
        """Whether one event is selected; returns (selected, reason)."""
        if not self.blocked_sources and not self.blocked_event_ids:
            return True, ""
        event_id = str(getattr(action, "event_id", "") or "")
        if self.blocked_event_ids and event_id and event_id in self.blocked_event_ids:
            return True, ""
        source_key = str(getattr(action, "source_key", "") or "")
        source = str(getattr(action, "source", "") or "")
        attacker_name = _attacker_name(attacker)
        candidates = {
            source_key.casefold(),
            source.casefold(),
            f"{attacker_name}:{source_key}".casefold(),
            f"{attacker_name} {source_key}".casefold(),
        }
        if any(
            str(selected).casefold() in candidates for selected in self.blocked_sources
        ):
            return True, ""
        return False, "source_not_selected"

    def public_receipt(self) -> dict[str, Any]:
        """JSON-safe selection receipt."""
        return {
            "blocked_sources": list(self.blocked_sources),
            "blocked_event_ids": list(self.blocked_event_ids),
        }


@dataclass(frozen=True, slots=True)
class DeliveryAcceptance:
    """One defense's declared delivery acceptance.

    Three gates: basic-attack blocks, area reduction (which routes area
    events away from full blocks), and the ``requires_skillshot`` filter.
    ``accepts_unknown`` declares that the defense needs no delivery decision
    for unmarked packets (Fiora's full block); False fails closed with a named
    ``unknown_delivery`` denial.
    """

    requires_skillshot: bool = True
    blocks_basic_attacks: bool = False
    area_damage_reduction: float = 0.0
    accepts_unknown: bool = False

    def accepts(
        self, action: PacketFacts, profile: DeliveryProfile
    ) -> tuple[bool, str]:
        """Return (accepted, reason) for one event's delivery profile.

        An unclassifiable delivery fails closed FIRST with the named
        ``unknown_delivery`` reason unless the defense declares
        ``accepts_unknown`` (Fiora's full block).  Then come the basic-attack
        block, area reduction, and the ``requires_skillshot`` filter.
        """
        if profile.unknown and not self.accepts_unknown:
            return False, "unknown_delivery"
        basic_attack = action_flag(action, "basic_attack")
        area_damage = action_flag(action, "area_damage")
        skillshot = action_flag(action, "skillshot")
        matches_basic = self.blocks_basic_attacks and basic_attack
        matches_area = self.area_damage_reduction > 0.0 and area_damage
        if (self.blocks_basic_attacks or self.area_damage_reduction > 0.0) and not (
            matches_basic or matches_area
        ):
            return False, "delivery_not_accepted"
        if (
            not matches_basic
            and not matches_area
            and self.requires_skillshot
            and not skillshot
        ):
            return False, "delivery_not_accepted"
        return True, ""

    def accepts_deliveries(self) -> tuple[str, ...]:
        """The declared delivery classes this defense accepts (summary).

        ``(projectile,)`` for the skillshot-only defenses (Braum E, Yasuo W,
        Samira W, Gwen W, Pantheon E); ``(basic_attack, area)`` for Jax
        Counter Strike; every class for Fiora Riposte's full block.
        """
        if (
            not self.requires_skillshot
            and not self.blocks_basic_attacks
            and self.area_damage_reduction <= 0.0
        ):
            return DELIVERY_CLASSES
        accepted: list[str] = []
        if self.blocks_basic_attacks:
            accepted.append(DELIVERY_BASIC_ATTACK)
        if self.area_damage_reduction > 0.0:
            accepted.append(DELIVERY_AREA)
        if not self.blocks_basic_attacks and self.area_damage_reduction <= 0.0:
            accepted.append(DELIVERY_PROJECTILE)
        return tuple(accepted)

    def public_receipt(self) -> dict[str, Any]:
        """JSON-safe acceptance receipt."""
        return {
            "requires_skillshot": self.requires_skillshot,
            "blocks_basic_attacks": self.blocks_basic_attacks,
            "area_damage_reduction": round(self.area_damage_reduction, 6),
            "accepts_unknown": self.accepts_unknown,
            "accepts_deliveries": list(self.accepts_deliveries()),
        }


@dataclass(frozen=True, slots=True)
class DefenseEligibility:
    """One defense's full eligibility contract (window + selection +
    delivery acceptance), with source receipts.

    ``name`` is the defense's typed kind (``braum_unbreakable``,
    ``yasuo_wind_wall``, ...).  ``decide`` is a pure function of the
    event and attacker — same-time determinism comes from the walk's
    total order, which the kernel mirrors in ``stable_event_key``.
    """

    name: str
    window: DefenseWindow
    selection: SourceSelection = SourceSelection()
    acceptance: DeliveryAcceptance = DeliveryAcceptance()
    source: SourceReceipt | None = None

    def decide(
        self, action: PacketFacts, attacker: CombatantFacts | None
    ) -> EligibilityDecision:
        """Decide eligibility for one event (deterministic, receipted)."""
        profile = classify_delivery(action)
        event_time = float(getattr(action, "time", 0.0) or 0.0)
        if not self.window.active_at(event_time):
            return EligibilityDecision(
                eligible=False,
                reason="outside_window",
                delivery=profile,
                event_key=stable_event_key(action),
            )
        selected, selection_reason = self.selection.selects(action, attacker)
        if not selected:
            return EligibilityDecision(
                eligible=False,
                reason=selection_reason,
                delivery=profile,
                event_key=stable_event_key(action),
            )
        accepted, delivery_reason = self.acceptance.accepts(action, profile)
        if not accepted:
            return EligibilityDecision(
                eligible=False,
                reason=delivery_reason,
                delivery=profile,
                event_key=stable_event_key(action),
            )
        return EligibilityDecision(
            eligible=True,
            reason="",
            delivery=profile,
            event_key=stable_event_key(action),
        )

    def public_receipt(self) -> dict[str, Any]:
        """JSON-safe eligibility declaration receipt."""
        return {
            "name": self.name,
            "window": self.window.public_receipt(),
            "selection": self.selection.public_receipt(),
            "acceptance": self.acceptance.public_receipt(),
            "source": self.source.public() if self.source is not None else None,
        }


@dataclass(frozen=True, slots=True)
class EligibilityDecision:
    """One eligibility decision with its public receipt.

    ``eligible`` False carries a named ``reason``: ``outside_window``,
    ``source_not_selected``, ``delivery_not_accepted``, or
    ``unknown_delivery`` (fail-closed).  Denied events pass through the
    walk untouched — the receipt is the observable denial.
    """

    eligible: bool
    reason: str = ""
    delivery: DeliveryProfile = field(default_factory=DeliveryProfile)
    event_key: str = ""

    def public_receipt(self) -> dict[str, Any]:
        """JSON-safe decision receipt."""
        return {
            "eligible": self.eligible,
            "reason": self.reason,
            "delivery": self.delivery.public_receipt(),
            "event_key": self.event_key,
        }


__all__ = [
    "DefenseEligibility",
    "DeliveryAcceptance",
    "EligibilityDecision",
    "SourceSelection",
]
