"""Which cast a spell shield blocks, and what the block does.

One shield use blocks ONE hostile ability instance (:class:`UseBudget`
``consume="per_cast"``, so every packet of the same cast follows the same block
decision without spending again).  The eligibility path is
:class:`SpellShieldEligibility` (window plus acceptance: ability only, control
only packets allowed, unknown deliveries fail closed), cast identity is
kernel-owned (:func:`resolve_cast_identity`), and the blocked effect and
triggered heal are declared in :class:`SpellShieldComposition` and
:class:`TriggeredHealRule`.  Each lifecycle phase has one typed kernel
declaration, so a consumer never re-implements a decision;
:mod:`spell_shield_rearm` owns the phase that brings a spent shield back.

Declared narrowings, none of them an omission: item-effect packets and monster
basic attacks (Sivir's notes list both as blockable) have no model tag, so the
ability-only gate is narrower than the game; damage-over-time tick blocking
needs the unstamped ``damage_over_time`` marker and an application-versus-tick
contract; Sivir's 0.25s heal delay has no catalog atom (prose-sourced SOURCE
GAP).  Crowd-control immunity, cleanse, Morgana E, Mikael's Blessing,
Quicksilver Sash, Mercurial Scimitar and Nocturne W are separate defenses with
their own modules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .defense_composition import FullBlockRule, UseBudget
from .delivery_classes import DeliveryProfile, action_flag, classify_delivery
from .delivery_facts import (
    CombatantFacts,
    DefenseWindow,
    PacketFacts,
    _attacker_name,
    stable_event_key,
)
from .spell_shield_rearm import SPELL_SHIELD_REARM_RULE, SpellShieldRearmClock
from .state_timeline import SourceReceipt

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

    def accepts(
        self, action: PacketFacts, profile: DeliveryProfile
    ) -> tuple[bool, str]:
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
        if action_flag(action, "basic_attack") and not self.blocks_basic_attacks:
            return False, "basic_attack_not_blocked"
        if self.requires_ability and not action_flag(action, "is_ability"):
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


def resolve_cast_identity(action: PacketFacts) -> tuple[str, str]:
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

    def decide(
        self, action: PacketFacts, _attacker: CombatantFacts | None
    ) -> SpellShieldDecision:
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
    delivery: DeliveryProfile = field(default_factory=DeliveryProfile)
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

    full_block: FullBlockRule = field(
        default_factory=lambda: FullBlockRule(mode="all", blocks_true_damage=True)
    )
    uses: UseBudget = field(
        default_factory=lambda: UseBudget(
            action_mode="spell_shield", uses=1, consume="per_cast"
        )
    )
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


def spell_shield_group_key(
    attacker: CombatantFacts | None, cast_identity: str
) -> tuple[str, ...]:
    """One per-attacker grouping key for a cast identity.

    Instances are stamped ``slot:ordinal`` WITHOUT the attacker, so Ahri E and
    Lux E both resolve to ``E:1``, and one shield use blocks one of them."""
    attacker_name = _attacker_name(attacker) if attacker is not None else ""
    if attacker_name:
        return (attacker_name, cast_identity)
    return (cast_identity,)


def spell_shield_block_decision(
    used: bool,
    blocked_cast: tuple[str, ...] | None,
    cast_identity: str,
    attacker: CombatantFacts | None = None,
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
