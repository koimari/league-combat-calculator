"""Shared delivery and interaction-eligibility kernel (roadmap P2).

One dependency-light leaf owns the typed contracts for how incoming
packets are delivered and which champion defenses may interact with
them.  Delivery type, defense eligibility, and mitigation/composition
are three orthogonal contracts:

- :data:`DELIVERY_DECLARATIONS` — typed delivery classes (projectile,
  hitscan, area, targeted, basic attack, damage over time), each with a
  source receipt; :func:`classify_delivery` maps one survival action to
  a :class:`DeliveryProfile` from its typed markers.  An event whose
  markers match no declared class is ``unknown`` and FAILS CLOSED when
  a defense needs a delivery decision (named ``unknown_delivery``
  receipt; :class:`UnknownDeliveryError` for the strict API).
- :class:`DefenseEligibility` — one declared acceptance rule (which
  delivery classes the defense accepts), an active window (start
  inclusive, end exclusive — the survival walk's convention), and a
  source/event selection; ``decide`` returns an
  :class:`EligibilityDecision` with a public receipt.
- Composition rules — :class:`UseBudget` (finite uses),
  :class:`FullBlockRule` (first-valid-hit / all), :class:`DestructionRule`,
  :class:`ReductionRule` (later-hit reduction, area reduction), grouped
  per defense in :class:`DefenseComposition`.  They decide WHAT happens
  to an eligible event; the survival walk keeps the exact applied
  semantics (first-block-then-reduce for Braum E, destroy for Yasuo W).

  P2 Slice 2 adds the SPELL-SHIELD lifecycle on the same contracts: one
  shield use blocks ONE hostile ability instance (:class:`UseBudget`
  ``consume="per_cast"`` — every packet of the same cast follows the
  same block decision without spending again), the eligibility path is
  :class:`SpellShieldEligibility` (window + acceptance: ability-only,
  control-only packets allowed, unknown deliveries fail closed), cast
  identity is kernel-owned (:func:`resolve_cast_identity`), and the
  blocked effect + triggered heal are declared in
  :class:`SpellShieldComposition` / :class:`TriggeredHealRule`.  The
  six lifecycle phases (arming, eligibility, cast grouping, use
  consumption, blocked effect, triggered heal) each have one typed
  kernel declaration; consumers never re-implement a decision.

  The seventh lifecycle phase is REARM (:class:`SpellShieldRearmClock`):
  a consumed shield comes back inside one fight when its sourced cooldown
  elapses, anchored by the cached "timer restarts upon taking damage from
  champions" clause to the later of the consumption instant and the last
  champion damage the holder took.  A shield with no sourced cooldown
  keeps the strict one-use-per-fight rule.

  SLICE BOUNDARY (documented follow-ups, deliberately NOT implemented):
  crowd-control immunity, cleanse, Morgana E, Mikael's Blessing,
  Quicksilver Sash, Mercurial Scimitar, and Nocturne W are separate P2
  defenses; item-effect packets and monster basic attacks
  (Sivir's notes list both as blockable) have no model tag, so the
  ability-only gate is a declared narrowing; damage-over-time tick
  blocking (already-applied DoTs are not blocked per tick in-game, but
  delayed-AoE effects are) needs the unstamped ``damage_over_time``
  marker and an application-vs-tick contract; Sivir's 0.25s heal delay
  has no catalog atom (prose-sourced SOURCE GAP).

Deterministic ordering mirrors the survival walk's total order
``(time, phase, sequence, participant order, participant id, event id,
source)``; the stable per-event identity used for first-hit bookkeeping
is :func:`stable_event_key` (``source_key:time:sequence``), the same key
the walk already uses for full-block events.

Design rules (HANDOVER §11): numeric values come from the data cache
through the consumer's typed accessors (atom receipts ride the
:class:`DefenseEligibility` source_atoms); categorical rules are small
frozen declarations with public receipts; missing values raise naming
the declaration; the kernel never invents a number.
"""

from __future__ import annotations

# pylint: disable=too-many-lines  # one dependency-light leaf owns the typed
# contracts; splitting it would create a second decision path.
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from .state_lifecycle import SourceReceipt

# Floating-point tolerance shared with the damage/survival walks.  All
# kernel comparisons use the same 1e-9 convention as the engine receipts.
_EPS = 1e-9

# ---------------------------------------------------------------------------
# Delivery declarations
# ---------------------------------------------------------------------------

DELIVERY_PROJECTILE = "projectile"
DELIVERY_HITSCAN = "hitscan"
DELIVERY_AREA = "area"
DELIVERY_TARGETED = "targeted"
DELIVERY_BASIC_ATTACK = "basic_attack"
DELIVERY_DAMAGE_OVER_TIME = "damage_over_time"

DeliveryClass = Literal[
    "projectile", "hitscan", "area", "targeted", "basic_attack", "damage_over_time"
]

DELIVERY_CLASSES: tuple[str, ...] = (
    DELIVERY_PROJECTILE,
    DELIVERY_HITSCAN,
    DELIVERY_AREA,
    DELIVERY_TARGETED,
    DELIVERY_BASIC_ATTACK,
    DELIVERY_DAMAGE_OVER_TIME,
)


@dataclass(frozen=True, slots=True)
class DeliveryDeclaration:
    """One typed delivery class with its source receipt.

    ``marker`` names the typed event/action field that evidences the
    class at runtime ("" when the class has no runtime marker yet —
    hitscan and targeted are declared conventions; targeted is evidenced
    by the ABSENCE of every other marker on an ability packet).
    """

    delivery: DeliveryClass
    description: str
    marker: str = ""
    source: SourceReceipt | None = None

    def public_receipt(self) -> dict[str, Any]:
        """JSON-safe declaration receipt."""
        return {
            "delivery": self.delivery,
            "description": self.description,
            "marker": self.marker,
            "source": self.source.public() if self.source is not None else None,
        }


# The runtime markers are the engine's typed stamps: ``skillshot`` from
# the cached ability ``projectile`` field, ``area_damage`` from
# ``spellEffects`` aoe values, ``basic_attack`` from the damage ledger's
# attack rows, ``damage_over_time`` from the ledger's DoT rows (declared
# but not yet stamped by any authored packet — see module notes).
DELIVERY_DECLARATIONS: tuple[DeliveryDeclaration, ...] = (
    DeliveryDeclaration(
        DELIVERY_PROJECTILE,
        "Blockable projectile / skillshot: the cached ability row carries a projectile.",
        marker="skillshot",
        source=SourceReceipt(
            label="Local League Wiki cache — ability projectile field",
            url="https://wiki.leagueoflegends.com",
        ),
    ),
    DeliveryDeclaration(
        DELIVERY_HITSCAN,
        "Instant line delivery with no travel time (declared; no runtime marker yet).",
        marker="",
        source=SourceReceipt(
            label="LoL wiki terminology — hitscan ability delivery",
            url="https://wiki.leagueoflegends.com",
        ),
    ),
    DeliveryDeclaration(
        DELIVERY_AREA,
        "Area-of-effect delivery: the cached ability row's spellEffects mark aoe.",
        marker="area_damage",
        source=SourceReceipt(
            label="Local League Wiki cache — spellEffects aoe marker",
            url="https://wiki.leagueoflegends.com",
        ),
    ),
    DeliveryDeclaration(
        DELIVERY_TARGETED,
        "Direct champion-targeted ability: an ability packet with no projectile, "
        "area, dot, or basic-attack marker.",
        marker="",
        source=SourceReceipt(
            label="Local League Wiki cache — absence of delivery markers",
            url="https://wiki.leagueoflegends.com",
        ),
    ),
    DeliveryDeclaration(
        DELIVERY_BASIC_ATTACK,
        "Basic attack packet from the damage ledger's attack rows.",
        marker="basic_attack",
        source=SourceReceipt(
            label="Damage ledger basic-attack marker",
            url="https://wiki.leagueoflegends.com",
        ),
    ),
    DeliveryDeclaration(
        DELIVERY_DAMAGE_OVER_TIME,
        "Damage-over-time tick packet from the damage ledger's DoT rows.",
        marker="damage_over_time",
        source=SourceReceipt(
            label="Damage ledger damage_over_time marker (declared; unstamped today)",
            url="https://wiki.leagueoflegends.com",
        ),
    ),
)


def delivery_declarations_receipt() -> list[dict[str, Any]]:
    """JSON-safe receipt for every declared delivery class."""
    return [declaration.public_receipt() for declaration in DELIVERY_DECLARATIONS]


# ---------------------------------------------------------------------------
# Delivery classification (typed, deterministic, fail-closed)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DeliveryProfile:
    """One event's delivery classes plus its classification completeness.

    ``classes`` is the set of declared delivery classes evidenced by the
    event's typed markers.  ``unknown`` is True when the event carries no
    declared class and is not a declared targeted ability packet (an
    item proc, an on-hit packet, or a packet with undeclared markers).
    """

    classes: frozenset[DeliveryClass] = frozenset()
    unknown: bool = False
    unknown_markers: tuple[str, ...] = ()

    def has(self, delivery: str) -> bool:
        """Whether the profile includes one delivery class."""
        return delivery in self.classes

    def public_receipt(self) -> dict[str, Any]:
        """JSON-safe classification receipt."""
        return {
            "classes": sorted(self.classes),
            "unknown": self.unknown,
            "unknown_markers": list(self.unknown_markers),
        }


class UnknownDeliveryError(ValueError):
    """Raised when a strict delivery decision needs a class the model
    cannot classify.  Naming the event keeps the failure actionable."""


def _action_flag(action: Any, name: str) -> bool:
    """Read one typed marker, defaulting to False for absent fields."""
    return bool(getattr(action, name, False))


def classify_delivery(action: Any) -> DeliveryProfile:
    """Classify one survival action's delivery from its typed markers.

    Deterministic by construction: the classes are a pure function of the
    action's ``skillshot`` / ``area_damage`` / ``basic_attack`` /
    ``damage_over_time`` / ``is_ability`` fields.  An ability packet
    with no delivery marker is the declared ``targeted`` class; a
    non-ability packet with no marker is ``unknown`` (fail-closed).
    """
    classes: set[str] = set()
    if _action_flag(action, "basic_attack"):
        classes.add(DELIVERY_BASIC_ATTACK)
    if _action_flag(action, "damage_over_time"):
        classes.add(DELIVERY_DAMAGE_OVER_TIME)
    if _action_flag(action, "skillshot"):
        classes.add(DELIVERY_PROJECTILE)
    if _action_flag(action, "area_damage"):
        classes.add(DELIVERY_AREA)
    unknown_markers: tuple[str, ...] = ()
    if not classes:
        if _action_flag(action, "is_ability"):
            classes.add(DELIVERY_TARGETED)
        else:
            unknown_markers = ("no_declared_marker",)
    return DeliveryProfile(
        classes=frozenset(classes),
        unknown=bool(unknown_markers),
        unknown_markers=unknown_markers,
    )


def required_delivery_class(action: Any, accepted: frozenset[str]) -> str:
    """Return one accepted delivery class or fail closed.

    Raises :class:`UnknownDeliveryError` when the event's delivery cannot
    be classified into any accepted class.  This is the strict API for a
    decision that MUST resolve; the eligibility decision path uses the
    receipt form instead.
    """
    profile = classify_delivery(action)
    if profile.unknown:
        raise UnknownDeliveryError(
            f"unknown delivery for {getattr(action, 'source_key', '?')!r} "
            f"at t={getattr(action, 'time', 0.0)} (markers: "
            f"{sorted(profile.unknown_markers)})"
        )
    for delivery in sorted(profile.classes):
        if delivery in accepted:
            return delivery
    raise UnknownDeliveryError(
        f"delivery {sorted(profile.classes)} for "
        f"{getattr(action, 'source_key', '?')!r} is not accepted by "
        f"{sorted(accepted)}"
    )


# ---------------------------------------------------------------------------
# Eligibility: window, selection, acceptance
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DefenseWindow:
    """One sourced active window (start inclusive, end exclusive).

    The boundary convention mirrors the survival walk: an event at
    ``start`` is inside, an event at ``until`` is outside.
    """

    start: float
    until: float
    source_atoms: tuple[dict[str, Any], ...] = ()

    def active_at(self, event_time: float) -> bool:
        """Whether an event time falls inside the window."""
        return self.start <= event_time < self.until

    def public_receipt(self) -> dict[str, Any]:
        """JSON-safe window receipt."""
        return {
            "start": round(self.start, 3),
            "until": round(self.until, 3),
            "source_atoms": [dict(atom) for atom in self.source_atoms],
        }


def _attacker_name(attacker: Any) -> str:
    """Read the attacker display name from a combatant."""
    if attacker is None:
        return ""
    champion_data = getattr(attacker, "champion_data", {})
    if isinstance(champion_data, Mapping):
        return str(champion_data.get("name", "") or "")
    return str(getattr(attacker, "name", "") or "")


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

    def selects(self, action: Any, attacker: Any) -> tuple[bool, str]:
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

    def accepts(self, action: Any, profile: DeliveryProfile) -> tuple[bool, str]:
        """Return (accepted, reason) for one event's delivery profile.

        An unclassifiable delivery fails closed FIRST with the named
        ``unknown_delivery`` reason unless the defense declares
        ``accepts_unknown`` (Fiora's full block).  Then come the basic-attack
        block, area reduction, and the ``requires_skillshot`` filter.
        """
        if profile.unknown and not self.accepts_unknown:
            return False, "unknown_delivery"
        basic_attack = _action_flag(action, "basic_attack")
        area_damage = _action_flag(action, "area_damage")
        skillshot = _action_flag(action, "skillshot")
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

    def decide(self, action: Any, attacker: Any) -> EligibilityDecision:
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
    delivery: DeliveryProfile = DeliveryProfile()
    event_key: str = ""

    def public_receipt(self) -> dict[str, Any]:
        """JSON-safe decision receipt."""
        return {
            "eligible": self.eligible,
            "reason": self.reason,
            "delivery": self.delivery.public_receipt(),
            "event_key": self.event_key,
        }


def stable_event_key(action: Any) -> str:
    """One stable identity for an interaction packet.

    ``source_key:time:sequence`` — the exact key the survival walk uses
    for full-block bookkeeping, so kernel decisions and walk bookkeeping
    share one identity.
    """
    source_key = str(getattr(action, "source_key", "") or "")
    event_time = float(getattr(action, "time", 0.0) or 0.0)
    sequence = getattr(action, "sequence", 0)
    try:
        sequence = int(sequence or 0)
    except (TypeError, ValueError):
        sequence = 0
    return f"{source_key}:{round(event_time, 9)}:{sequence}"


# ---------------------------------------------------------------------------
# Composition rules — what happens to an eligible event (orthogonal to
# delivery type and eligibility)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UseBudget:
    """Finite-use declaration for one applied action.

    ``uses`` None means unlimited (Yasuo's destruction).  ``consume``
    ``"first_eligible"`` spends the budget on the first eligible event
    (Braum's single full block); ``"each_eligible"`` would spend per
    event; ``"per_cast"`` (the spell-shield lifecycle) spends once per
    cast identity — one shield use blocks ONE hostile ability instance,
    and every later packet of the same cast follows the same block
    decision without spending again.
    """

    action_mode: str
    uses: int | None = None
    consume: Literal["first_eligible", "each_eligible", "per_cast"] = "first_eligible"
    source: SourceReceipt | None = None

    def __post_init__(self) -> None:
        """Fail closed on an impossible budget declaration."""
        if self.uses is not None and self.uses < 1:
            raise ValueError(
                f"UseBudget for {self.action_mode!r}: uses must be >= 1 or "
                f"None (unlimited), got {self.uses!r}"
            )
        if self.consume not in ("first_eligible", "each_eligible", "per_cast"):
            raise ValueError(
                f"UseBudget for {self.action_mode!r}: unknown consume policy "
                f"{self.consume!r}"
            )

    def initial_remaining(self) -> int | None:
        """The starting remaining count (None = unlimited)."""
        return self.uses

    def public_receipt(self) -> dict[str, Any]:
        """JSON-safe budget receipt."""
        return {
            "action_mode": self.action_mode,
            "uses": self.uses,
            "consume": self.consume,
            "source": self.source.public() if self.source is not None else None,
        }


@dataclass(frozen=True, slots=True)
class FullBlockRule:
    """Full-block declaration: ``"first"`` (Braum) or ``"all"`` (Fiora,
    Pantheon, Jax).  ``blocks_true_damage`` is False for first-hit rules
    (Braum E does not block true damage) and True for all-hit rules.
    """

    mode: Literal["none", "first", "all"] = "none"
    blocks_true_damage: bool = False
    source: SourceReceipt | None = None

    def __post_init__(self) -> None:
        """Fail closed on an unknown full-block mode."""
        if self.mode not in ("none", "first", "all"):
            raise ValueError(
                f"FullBlockRule: unknown mode {self.mode!r} "
                "(must be 'none', 'first', or 'all')"
            )

    def public_receipt(self) -> dict[str, Any]:
        """JSON-safe rule receipt."""
        return {
            "mode": self.mode,
            "blocks_true_damage": self.blocks_true_damage,
            "source": self.source.public() if self.source is not None else None,
        }


@dataclass(frozen=True, slots=True)
class DestructionRule:
    """Projectile-destruction declaration (Yasuo W)."""

    enabled: bool = False
    source: SourceReceipt | None = None

    def public_receipt(self) -> dict[str, Any]:
        """JSON-safe rule receipt."""
        return {
            "enabled": self.enabled,
            "source": self.source.public() if self.source is not None else None,
        }


@dataclass(frozen=True, slots=True)
class ReductionRule:
    """Later-hit reduction (Braum E after the first full block) and the
    area-ability reduction (Jax Counter Strike).  ``applies_to_true_damage``
    False keeps true damage untouched (Braum).
    """

    later_hit_reduction: float = 0.0
    area_damage_reduction: float = 0.0
    applies_to_true_damage: bool = False
    source: SourceReceipt | None = None

    def reduction_for(self, action: Any) -> float:
        """A defense with no area rule reduces area-marked skillshots with its
        later-hit reduction: Braum's shield intercepts Trueshot Barrage in-game
        (wiki: "intercepts all incoming hostile projectiles")."""
        if self.area_damage_reduction > 0.0 and _action_flag(action, "area_damage"):
            return self.area_damage_reduction
        return self.later_hit_reduction

    def public_receipt(self) -> dict[str, Any]:
        """JSON-safe rule receipt."""
        return {
            "later_hit_reduction": round(self.later_hit_reduction, 6),
            "area_damage_reduction": round(self.area_damage_reduction, 6),
            "applies_to_true_damage": self.applies_to_true_damage,
            "source": self.source.public() if self.source is not None else None,
        }


@dataclass(frozen=True, slots=True)
class DefenseComposition:
    """The declared applied actions for one defense's eligible events.

    Kept separate from eligibility: an eligible event is destroyed
    (Yasuo), fully blocked (Braum first / Fiora, Pantheon, Jax all), or
    reduced (Braum later hits / Jax area).  The survival walk applies
    these exactly as today.
    """

    full_block: FullBlockRule = FullBlockRule()
    full_block_uses: UseBudget | None = None
    destroy: DestructionRule = DestructionRule()
    reduction: ReductionRule = ReductionRule()

    def public_receipt(self) -> dict[str, Any]:
        """JSON-safe composition receipt."""
        return {
            "full_block": self.full_block.public_receipt(),
            "full_block_uses": (
                self.full_block_uses.public_receipt()
                if self.full_block_uses is not None
                else None
            ),
            "destroy": self.destroy.public_receipt(),
            "reduction": self.reduction.public_receipt(),
        }


def initial_full_block_uses(composition: DefenseComposition) -> int | None:
    """The defense's starting full-block budget (None = unlimited)."""
    if composition.full_block_uses is None:
        return None
    return composition.full_block_uses.initial_remaining()


# ---------------------------------------------------------------------------
# Spell-shield lifecycle (P2 Slice 2): arming, eligibility, cast grouping,
# use consumption, blocked effect, triggered heal
# ---------------------------------------------------------------------------

# The sourced categorical rules of the spell-shield lifecycle.  Each rule
# is a typed declaration with its cache receipt; the kernel never invents
# a policy the cache does not evidence (HANDOVER section 11).
SPELL_SHIELD_ONE_USE_RULE = (
    "One shield use blocks ONE hostile ability instance; every packet of "
    "the same cast follows the same block decision without spending again."
)
SPELL_SHIELD_CONTROL_ONLY_RULE = (
    "A control-only hostile ability packet consumes the shield: Sivir E "
    "blocks 'a hostile effect' (no damage requirement; the notes list any "
    "blocked effect, including champion abilities), and each Annul item "
    "'blocks the next hostile ability'."
)
SPELL_SHIELD_BASIC_ATTACK_RULE = (
    "Champion basic attacks do not consume the shield.  The cached Sivir "
    "notes list only monster basic attacks ('Dragon's basic attacks') as "
    "blockable effects; the model has no monster-AA tag, so the gate "
    "stays ability-only (declared narrowing, recorded as follow-up)."
)
SPELL_SHIELD_PRIOR_DISPOSAL_RULE = (
    "A prior defense that destroys or fully blocks an incoming packet "
    "must NOT spend the spell shield (walk order: stasis and "
    "invulnerability, then projectile destroy/full block, then the spell "
    "shield gate)."
)
SPELL_SHIELD_REARM_RULE = (
    "A consumed shield rearms inside one modeled fight only once its "
    "sourced cooldown has fully elapsed ('40 second cooldown, timer "
    "restarts upon taking damage from champions' — Banshee's Veil / Edge "
    "of Night; 60 seconds — Verdant Barrier), and that restart clause "
    "anchors the clock to the later of the consumption instant and the "
    "last champion damage the holder took.  A shield whose cooldown is "
    "not sourced never rearms."
)
_SPELL_SHIELD_WIKI = SourceReceipt(
    label="Local League Wiki cache — Sivir E and Annul item descriptions",
    url="https://wiki.leagueoflegends.com",
)


@dataclass(frozen=True, slots=True)
class SpellShieldRuleDeclaration:
    """One sourced categorical rule of the spell-shield lifecycle."""

    rule: str
    source: SourceReceipt = _SPELL_SHIELD_WIKI

    def public_receipt(self) -> dict[str, Any]:
        """JSON-safe rule receipt."""
        return {"rule": self.rule, "source": self.source.public()}


def spell_shield_rules_receipt() -> list[dict[str, Any]]:
    """JSON-safe receipt for every declared spell-shield rule."""
    return [
        SpellShieldRuleDeclaration(SPELL_SHIELD_ONE_USE_RULE).public_receipt(),
        SpellShieldRuleDeclaration(SPELL_SHIELD_CONTROL_ONLY_RULE).public_receipt(),
        SpellShieldRuleDeclaration(SPELL_SHIELD_BASIC_ATTACK_RULE).public_receipt(),
        SpellShieldRuleDeclaration(SPELL_SHIELD_PRIOR_DISPOSAL_RULE).public_receipt(),
        SpellShieldRuleDeclaration(SPELL_SHIELD_REARM_RULE).public_receipt(),
    ]


def _control_only_packet(action: Any) -> bool:
    """Whether one ability packet carries control but no damage."""
    try:
        amount = float(getattr(action, "amount", 0.0) or 0.0)
    except (TypeError, ValueError):
        amount = 0.0
    return amount <= 0.0


@dataclass(frozen=True, slots=True)
class SpellShieldAcceptance:
    """Which incoming packets one spell shield selects.

    ``requires_ability`` keeps the pinned runtime gate: only authored
    ability packets may consume a shield; basic attacks and unclassifiable
    packets pass through untouched.  ``blocks_basic_attacks`` is declared
    False for every current shield (no monster-AA tag exists).  A
    control-only ability packet (amount 0, crowd-control fields) is a
    hostile effect and consumes the shield when ``blocks_control_only``
    is True (every current shield declares True).  ``accepts_unknown``
    False fails closed on unclassifiable deliveries.
    """

    requires_ability: bool = True
    blocks_basic_attacks: bool = False
    blocks_control_only: bool = True
    accepts_unknown: bool = False

    def accepts(self, action: Any, profile: DeliveryProfile) -> tuple[bool, str]:
        """Return (accepted, reason) for one event's delivery profile.

        Unclassifiable deliveries fail closed FIRST with the named
        ``unknown_delivery`` reason; then the pinned ability gate
        (``not_an_ability``), the declared basic-attack gate
        (``basic_attack_not_blocked``), and the control-only gate
        (``control_only_not_blocked``).  Ineligible packets pass through
        the walk untouched — the receipt is the observable denial.
        """
        if profile.unknown and not self.accepts_unknown:
            return False, "unknown_delivery"
        if _action_flag(action, "basic_attack") and not self.blocks_basic_attacks:
            return False, "basic_attack_not_blocked"
        if self.requires_ability and not _action_flag(action, "is_ability"):
            return False, "not_an_ability"
        if not self.blocks_control_only and _control_only_packet(action):
            return False, "control_only_not_blocked"
        return True, ""

    def public_receipt(self) -> dict[str, Any]:
        """JSON-safe acceptance receipt."""
        return {
            "requires_ability": self.requires_ability,
            "blocks_basic_attacks": self.blocks_basic_attacks,
            "blocks_control_only": self.blocks_control_only,
            "accepts_unknown": self.accepts_unknown,
        }


def resolve_cast_identity(action: Any) -> tuple[str, str]:
    """One cast identity for spell-shield grouping.

    Returns ``(identity, kind)``: ``("sourced", instance)`` when the packet
    carries the upstream resolved ability instance, ``("derived",
    "source_key:time")`` when it does not, which still groups same-slot
    same-time packets of one cast, and ``("", "unknown")`` when no identity
    can be formed, on which the decision path fails closed and never spends
    the shield.
    """
    instance = getattr(action, "ability_instance", None)
    if instance is not None and str(instance):
        return str(instance), "sourced"
    source_key = str(getattr(action, "source_key", "") or "")
    raw_time = getattr(action, "time", None)
    if raw_time is None and not source_key:
        return "", "unknown"
    try:
        event_time = float(raw_time or 0.0)
    except (TypeError, ValueError):
        return "", "unknown"
    return f"{source_key}:{round(event_time, 9)}", "derived"


@dataclass(frozen=True, slots=True)
class SpellShieldEligibility:
    """One spell shield's eligibility contract (window + acceptance).

    ``name`` is the shield's typed kind (``spell_shield`` for Sivir E,
    ``annul`` for the three item shields).  ``block_rule`` is the sourced
    categorical rule text.  ``decide`` is a pure function of the event
    and attacker — same-time determinism comes from the walk's total
    order, which the kernel mirrors in :func:`stable_event_key`.
    """

    name: str
    window: DefenseWindow
    acceptance: SpellShieldAcceptance = SpellShieldAcceptance()
    block_rule: str = SPELL_SHIELD_ONE_USE_RULE
    source: SourceReceipt | None = None

    def decide(self, action: Any, _attacker: Any) -> SpellShieldDecision:
        """Decide eligibility for one event (deterministic, receipted).

        The attacker parameter mirrors :meth:`DefenseEligibility.decide`
        (spell shields select every hostile source, so it is not read
        here); the walk attacker-qualifies the grouping key separately.
        """
        profile = classify_delivery(action)
        event_key = stable_event_key(action)
        event_time = float(getattr(action, "time", 0.0) or 0.0)
        if not self.window.active_at(event_time):
            return SpellShieldDecision(
                eligible=False,
                reason="outside_window",
                delivery=profile,
                event_key=event_key,
            )
        accepted, acceptance_reason = self.acceptance.accepts(action, profile)
        if not accepted:
            return SpellShieldDecision(
                eligible=False,
                reason=acceptance_reason,
                delivery=profile,
                event_key=event_key,
            )
        cast_identity, cast_kind = resolve_cast_identity(action)
        if cast_kind == "unknown":
            return SpellShieldDecision(
                eligible=False,
                reason="unknown_cast_identity",
                delivery=profile,
                event_key=event_key,
                cast_identity="",
                cast_identity_kind="unknown",
            )
        return SpellShieldDecision(
            eligible=True,
            reason="",
            delivery=profile,
            event_key=event_key,
            cast_identity=cast_identity,
            cast_identity_kind=cast_kind,
        )

    def public_receipt(self) -> dict[str, Any]:
        """JSON-safe eligibility declaration receipt."""
        return {
            "name": self.name,
            "window": self.window.public_receipt(),
            "acceptance": self.acceptance.public_receipt(),
            "block_rule": self.block_rule,
            "source": self.source.public() if self.source is not None else None,
        }


@dataclass(frozen=True, slots=True)
class SpellShieldDecision:
    """One spell-shield eligibility decision with its public receipt.

    ``eligible`` False carries a named ``reason``: ``outside_window``,
    ``not_an_ability``, ``basic_attack_not_blocked``,
    ``control_only_not_blocked``, ``unknown_delivery``, or
    ``unknown_cast_identity`` (fail-closed).  Denied events pass through
    the walk untouched — the receipt is the observable denial.  The
    one-use budget and cast grouping are decided separately by
    :func:`spell_shield_block_decision`.
    """

    eligible: bool
    reason: str = ""
    delivery: DeliveryProfile = DeliveryProfile()
    cast_identity: str = ""
    cast_identity_kind: str = "unknown"
    event_key: str = ""

    def public_receipt(self) -> dict[str, Any]:
        """JSON-safe decision receipt."""
        return {
            "eligible": self.eligible,
            "reason": self.reason,
            "delivery": self.delivery.public_receipt(),
            "cast_identity": self.cast_identity,
            "cast_identity_kind": self.cast_identity_kind,
            "event_key": self.event_key,
        }


@dataclass(frozen=True, slots=True)
class TriggeredHealRule:
    """One sourced on-block heal (Sivir E heals after a sourced delay
    when the shield blocks a hostile effect; Annul shields declare none).
    """

    amount: float
    delay: float
    source: str
    source_atoms: tuple[dict[str, Any], ...] = ()

    def public_receipt(self) -> dict[str, Any]:
        """JSON-safe triggered-heal receipt."""
        return {
            "amount": round(self.amount, 6),
            "delay": round(self.delay, 6),
            "source": self.source,
            "source_atoms": [dict(atom) for atom in self.source_atoms],
        }


@dataclass(frozen=True, slots=True)
class SpellShieldComposition:
    """The declared applied action for one shield's eligible cast.

    ``full_block`` blocks EVERY packet of the selected cast — damage,
    control, and true damage alike.  ``uses`` is a one-use per-cast
    budget (:class:`UseBudget` ``consume="per_cast"``): the first packet
    of the selected cast spends the use, later packets of the SAME cast
    follow the same block decision without spending again, and an
    eligible packet of a DIFFERENT cast after the use passes through
    (``use_consumed``).  ``triggered_heal`` fires once per consumed use.
    """

    full_block: FullBlockRule = FullBlockRule(mode="all", blocks_true_damage=True)
    uses: UseBudget = UseBudget(action_mode="spell_shield", uses=1, consume="per_cast")
    triggered_heal: TriggeredHealRule | None = None

    def public_receipt(self) -> dict[str, Any]:
        """JSON-safe composition receipt."""
        return {
            "full_block": self.full_block.public_receipt(),
            "uses": self.uses.public_receipt(),
            "triggered_heal": (
                self.triggered_heal.public_receipt()
                if self.triggered_heal is not None
                else None
            ),
        }


def spell_shield_group_key(attacker: Any, cast_identity: str) -> tuple[str, ...]:
    """One per-attacker grouping key for a cast identity.

    Instances are stamped ``slot:ordinal`` WITHOUT the attacker, so Ahri E and
    Lux E both resolve to ``E:1``, and one shield use blocks one of them."""
    attacker_name = _attacker_name(attacker) if attacker is not None else ""
    if attacker_name:
        return (attacker_name, cast_identity)
    return (cast_identity,)


@dataclass(frozen=True, slots=True)
class SpellShieldRearmClock:
    """One consumed shield's fight-window-relative rearm clock.

    ``cooldown`` is the holder item's SOURCED cooldown in seconds and
    ``source_atom`` is the catalog atom that evidences it: a positive
    cooldown declared without its atom is refused, so the kernel can never
    rearm on a number no source backs.  ``0.0`` is the declared "no sourced
    cooldown" value and never rearms — that shield keeps the strict
    one-use-per-fight rule (Sivir's timed shield is the live case).

    ``restarts_on_champion_damage`` carries the cached clause every Annul
    branch spells out, so the timer is anchored to the LATER of the
    consumption instant and the last champion damage the holder took — not
    to the consumption instant alone, which would rearm the shield sooner
    than the source allows.
    """

    cooldown: float = 0.0
    restarts_on_champion_damage: bool = True
    source_atom: Mapping[str, Any] | None = None
    rule: str = SPELL_SHIELD_REARM_RULE

    def __post_init__(self) -> None:
        """Fail closed on an impossible or unsourced clock declaration."""
        if not self.cooldown >= 0.0:
            raise ValueError(
                "SpellShieldRearmClock: cooldown must be a number >= 0.0 "
                f"(0.0 = not sourced, never rearms), got {self.cooldown!r}"
            )
        if self.cooldown > 0.0 and self.source_atom is None:
            raise ValueError(
                "SpellShieldRearmClock: a positive cooldown needs the "
                f"catalog atom that sources it; {self.cooldown!r} arrived "
                "with none"
            )

    def sourced(self) -> bool:
        """Whether a sourced cooldown backs this clock."""
        return self.cooldown > 0.0

    def anchor(
        self, consumed_at: float, last_champion_damage_at: float | None = None
    ) -> float:
        """The instant this shield's cooldown timer last (re)started."""
        started = float(consumed_at)
        if self.restarts_on_champion_damage and last_champion_damage_at is not None:
            damaged_at = float(last_champion_damage_at)
            started = max(started, damaged_at)
        return started

    def ready_at(
        self, consumed_at: float, last_champion_damage_at: float | None = None
    ) -> float:
        """The fight-relative instant the shield rearms; ``inf`` never."""
        if not self.sourced():
            return float("inf")
        return self.anchor(consumed_at, last_champion_damage_at) + self.cooldown

    def rearmed_at(
        self,
        event_time: float,
        consumed_at: float,
        last_champion_damage_at: float | None = None,
    ) -> bool:
        """Whether the shield is back by ``event_time`` (start inclusive)."""
        ready = self.ready_at(consumed_at, last_champion_damage_at)
        if not math.isfinite(ready):
            return False
        return float(event_time) >= ready - _EPS

    def rearms_within(
        self,
        fight_until: float,
        consumed_at: float,
        last_champion_damage_at: float | None = None,
    ) -> bool:
        """Whether the rearm lands inside the fight window.

        End-exclusive, the walk's convention (:meth:`DefenseWindow.active_at`).
        """
        ready = self.ready_at(consumed_at, last_champion_damage_at)
        if not math.isfinite(ready):
            return False
        return ready < float(fight_until) - _EPS

    def public_receipt(self) -> dict[str, Any]:
        """JSON-safe rearm-clock receipt."""
        return {
            "cooldown": round(self.cooldown, 3),
            "sourced": self.sourced(),
            "restarts_on_champion_damage": self.restarts_on_champion_damage,
            "rule": self.rule,
            "source_atom": (
                dict(self.source_atom) if self.source_atom is not None else None
            ),
        }


def spell_shield_block_decision(
    used: bool,
    blocked_cast: tuple[str, ...] | None,
    cast_identity: str,
    attacker: Any = None,
    *,
    rearm: SpellShieldRearmClock | None = None,
    event_time: float | None = None,
    consumed_at: float | None = None,
    last_champion_damage_at: float | None = None,
) -> tuple[bool, str]:
    """Whether one eligible cast may still be blocked by the shield.

    ``(True, "same_cast")`` groups every packet of an already-blocked cast
    without spending another use; ``(True, "rearmed")`` answers a different
    cast that arrives after the sourced cooldown brought the shield back
    inside the fight; ``(False, "use_consumed")`` answers a different cast
    arriving while the one use is still spent.

    The rearm clock is optional and fails closed in every direction: no
    clock, an unsourced clock, or a missing consumption/event timestamp all
    keep the strict one-use-per-fight rule rather than inventing a rearm.
    """
    key = spell_shield_group_key(attacker, cast_identity)
    if not used:
        return True, ""
    if blocked_cast == key:
        return True, "same_cast"
    if (
        rearm is not None
        and event_time is not None
        and consumed_at is not None
        and rearm.rearmed_at(event_time, consumed_at, last_champion_damage_at)
    ):
        return True, "rearmed"
    return False, "use_consumed"


__all__ = [
    "DELIVERY_AREA",
    "DELIVERY_BASIC_ATTACK",
    "DELIVERY_CLASSES",
    "DELIVERY_DAMAGE_OVER_TIME",
    "DELIVERY_DECLARATIONS",
    "DELIVERY_HITSCAN",
    "DELIVERY_PROJECTILE",
    "DELIVERY_TARGETED",
    "SPELL_SHIELD_BASIC_ATTACK_RULE",
    "SPELL_SHIELD_CONTROL_ONLY_RULE",
    "SPELL_SHIELD_ONE_USE_RULE",
    "SPELL_SHIELD_PRIOR_DISPOSAL_RULE",
    "SPELL_SHIELD_REARM_RULE",
    "DefenseComposition",
    "DefenseEligibility",
    "DefenseWindow",
    "DeliveryAcceptance",
    "DeliveryDeclaration",
    "DeliveryProfile",
    "DestructionRule",
    "EligibilityDecision",
    "FullBlockRule",
    "ReductionRule",
    "SourceSelection",
    "SpellShieldAcceptance",
    "SpellShieldComposition",
    "SpellShieldDecision",
    "SpellShieldEligibility",
    "SpellShieldRearmClock",
    "SpellShieldRuleDeclaration",
    "TriggeredHealRule",
    "UnknownDeliveryError",
    "UseBudget",
    "classify_delivery",
    "delivery_declarations_receipt",
    "initial_full_block_uses",
    "required_delivery_class",
    "resolve_cast_identity",
    "spell_shield_block_decision",
    "spell_shield_group_key",
    "spell_shield_rules_receipt",
    "stable_event_key",
]
