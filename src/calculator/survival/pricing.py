"""A declared packet's price, computed by the walk that pays it.

The coupled walk consumes the one-pair engine's **post-mitigation** rows, and
where the subject's resistance moves mid-fight it recovers the pre-mitigation
side by ratio (``transitions.reprice_dynamic_resistance``).  A family whose
interpreter hands the walk its *declaration* brings a raw value and no
mitigation to divide back out, so it has nowhere to hand its price under that
ratio.  This module is where a raw declared value becomes a mitigated one, in
two levels because two callers want different halves:

* :func:`mitigate_declared` is the arithmetic: one raw amount at one
  resistance, with true damage bypassing it.  The strike-back the coupled
  timeline schedules (``survival.compile.thorns_return_damage``) reads this
  function, so the tree holds one from-raw home rather than two.
* :func:`price_declared_packet` is the walk's own reading.  It resolves the
  resistance the packet meets *at the moment it resolves*, the fight's
  published effective resistance plus whatever delta the walk has armed since,
  and mitigates the declaration against it.  Nothing is divided, so the armed
  delta is part of the resistance the raw value meets rather than a second
  factor applied to a mitigated one.

A :class:`DeclaredPacket` transports three terms the pair engine applies and
the walk must reproduce.  Each is stamped on the declaration by the authored
ledger rather than resolved again here, because what the walk owes is the term
*this packet* met and not the term the fight settled at.

``holder_amp``
    The holder's static, pair-local amplifiers, composed by
    ``interpreters.delta_amp.resolve_static_holder_amps`` and applied
    **pre-mitigation**, so the composed value is mitigated once instead of a
    mitigated number being re-multiplied.
``effective_resistance``
    The resistance this packet's own event met.  A fight publishes one
    effective armour and one effective magic resistance, and the pair engine
    prices past both when it re-prices packets it already authored:
    ``damage._apply_temporary_lethality_windows`` rescales later physical
    packets inside a Firmament window, and ``damage._apply_liandry_reprice``
    folds a raised maximum health back onto a burn's own ticks.  ``None``
    prices at the fight's published baseline, which is correct only for a
    packet no window touched.
``swing``
    The crit blend and the target's capped flat subtraction a packet delivered
    as a basic-attack swing met in ``damage._mitigate_basic_attack_swing``.

**A routing family declares no magnitude.**  A packet may reach a subject
because some *other* family's packet was re-delivered there: Wind's Fury's bolt
carries a declared share of the swing that fired it, and the attack's on-hit
effects are copied onto the bolt's target.  ``secondary_target`` is such a
router, so :func:`route_declared_packet` builds the routed packet from the
**source** family's own declaration scaled by the router's declared share.  It
keeps the source mechanic as its ``rule_id``, which attributes it at
``(source mechanic, secondary subject, event_id)`` with the subject keeping
that key clear of the same mechanic's primary delivery, and records the route
as :class:`RoutingProvenance`.  How a packet reached a subject is provenance
and never a second number, because one number has one producer.

Every family in ``program.build.walk_repriced_mechanics()`` hands the walk a
:class:`DeclaredPacket`; the pair engine's timed rows are re-spelled here, not
re-priced.
"""

from __future__ import annotations

from typing import NamedTuple

from ..resistance import apply_resistance


class BasicAttackSwing(NamedTuple):
    """The composition a packet delivered as a basic-attack swing is priced by.

    The pair engine prices a swing as two branches blended by the holder's crit
    chance, meeting three target-side terms on the way.  Two of the three fold into
    the declared magnitudes, because the target's critical-strike damage multiplier
    and the plating multiplier are pure factors on a linear mitigation, and the walk
    prices the same real number without knowing they exist.  This carries the half
    that cannot fold: the **blend**, which is two magnitudes rather than one, and
    Warden's Mail's **capped flat subtraction**, applied to each branch *before* the
    blend so its cap bites on the crit branch and not the non-crit one.

    ``crit_chance`` is the blend weight and ``crit_raw_amount`` the crit branch's
    own pre-mitigation magnitude with the folding factors already in it; the
    packet's ``raw_amount`` is the non-crit branch's.  The three reduction fields
    are named for the fight-state fields the pair engine reads them from, so the
    term census joins an engine field to the term carrying it by name match rather
    than by a table: ``basic_damage_flat_reduction`` and
    ``basic_damage_flat_reduction_cap`` are the two halves of
    ``min(flat, per_hit x cap)``, and ``instances`` is how many of them this
    declaration's packet consumed, one for one swing.

    A holder with no crit chance and a target with no Rock Solid still gets a
    faithful blend: the weight is zero and the subtraction is inert, which is a
    measured answer rather than a default nobody asked for.
    """

    crit_chance: float
    crit_raw_amount: float
    basic_damage_flat_reduction: float = 0.0
    basic_damage_flat_reduction_cap: float = 0.0
    instances: int = 1

    def less_flat_reduction(self, branch: float) -> float:
        """One mitigated branch, less the target's capped flat subtraction.

        ``damage._apply_target_basic_damage_reduction``'s arithmetic on one branch.
        A non-positive branch is returned untouched, because a flat defensive proc
        cannot be consumed by a negative algebraic modifier, which is the pair
        engine's reading and the reason this is not a plain ``max``.
        """
        flat = float(self.basic_damage_flat_reduction)
        cap = float(self.basic_damage_flat_reduction_cap)
        instances = int(self.instances)
        if branch <= 0.0 or flat <= 0.0 or cap <= 0.0 or instances <= 0:
            return branch
        per_instance = branch / instances
        return max(0.0, branch - min(flat, per_instance * cap) * instances)

    def blended(self, non_crit: float, crit: float) -> float:
        """The two priced branches, blended by the holder's clamped crit chance."""
        weight = min(1.0, max(0.0, float(self.crit_chance)))
        return weight * crit + (1.0 - weight) * non_crit


class RoutingProvenance(NamedTuple):
    """How a routed packet reached the subject it was paid at.

    A routing family re-delivers a source family's declared magnitude at a second
    subject.  What it contributes is the routing, stated here as the fact it is and
    **not as a number the walk adds**: the number is the source family's, and
    ``damage_share`` is applied to that family's own magnitude rather than declared
    beside it.

    ``router_rule_id`` is the mechanic that did the routing, carried for the
    receipt: a copied packet whose provenance named nobody would be a magnitude
    arriving at a subject with no account of how.
    """

    router_rule_id: str
    damage_share: float


class AuthoredDeclaration(NamedTuple):
    """One packet's declaration as the pair engine's authored ledger carries it.

    Six facts and no price: which rule authored the packet, the pre-mitigation
    magnitude that rule's interpreter compiled, the attack class the rule declares
    (which decides *which* of the holder's amplifiers the packet earns), the
    effective resistance the packet itself met, the basic-attack swing composition
    it was delivered through, and the route a routing family re-delivered it by.

    It rides the engine's own event, which is why it is a plain tuple on the wire
    and a named shape here: the ledger has two row spellings, a dict row and a
    positional light row, and a reader that unpacked the tuple by index in each
    would be two readers of one declaration.  This is the one home of what those
    six positions mean; ``program.compile.declared_packet_of`` composes the
    remaining term, the holder's own amps, on the walk's side.

    The two methods below keep the declaration in step: a site that re-prices an
    already-authored packet restates the declaration riding it, instead of leaving
    behind a magnitude or a mitigation the walk would then price the packet at.
    ``effective_resistance`` is ``None`` for a packet whose ledger published no
    resistance for its class, which is a refusal at the pricing stage and never a
    zero.  ``swing`` is ``None`` for a declaration no basic-attack swing delivered,
    priced through ``damage._mitigate`` alone.  ``routing`` is present exactly on a
    packet a routing family re-delivered at a second subject; ``rule_id`` stays the
    **source** mechanic's, and :func:`route_declared_packet` is the one place a
    share is applied.
    """

    rule_id: str
    raw_amount: float
    attack_class: str
    effective_resistance: float | None = None
    swing: tuple | None = None
    routing: tuple | None = None

    def swing_composition(self) -> "BasicAttackSwing | None":
        """This declaration's swing composition, or ``None`` if none rode it."""
        return None if self.swing is None else BasicAttackSwing(*self.swing)

    def routing_provenance(self) -> "RoutingProvenance | None":
        """This declaration's route, or ``None`` if it reached its subject directly."""
        return None if self.routing is None else RoutingProvenance(*self.routing)

    def routed_by(self, routing: "RoutingProvenance") -> "AuthoredDeclaration":
        """The same declaration, re-delivered at a second subject."""
        return self._replace(routing=tuple(routing))

    def delivered_as_a_swing(self, swing: BasicAttackSwing) -> "AuthoredDeclaration":
        """The same declaration, carrying the swing composition it met."""
        return self._replace(swing=tuple(swing))

    def repriced_at(self, effective_resistance: float) -> "AuthoredDeclaration":
        """The same declaration, met by a different resistance."""
        return self._replace(effective_resistance=float(effective_resistance))

    def rescaled_by(self, factor: float) -> "AuthoredDeclaration":
        """The same declaration, at a magnitude scaled by *factor*."""
        return self._replace(raw_amount=float(self.raw_amount) * float(factor))


class DeclaredPacket(NamedTuple):
    """One family's damage as its declaration states it: raw, unmitigated.

    ``rule_id`` is the declaring mechanic, carried for the refusal as much as for
    the receipt: a declaration the walk could not price has to be able to name what
    went unpaid, because the alternative reading of an unpriced packet is an
    anonymous zero nobody notices.

    ``holder_amp`` is the holder's static, pair-local amplifiers, composed for this
    packet's damage class and delivery by
    ``interpreters.delta_amp.StaticHolderAmps.factor_for``.  It rides on the packet
    rather than being folded into ``raw_amount`` by each family, because a family
    that pre-multiplied its own declaration would be an undeclared second producer
    of one number.  ``1.0`` is a holder with no amp armed, which is a measured
    answer: the amps are resolved for every priced packet, and a resolution that
    found none is what ``1.0`` means.

    ``effective_resistance`` is the resistance this packet's own pair-engine event
    met.  ``None`` is a declaration whose ledger transported none, priced at the
    fight's published baseline, which is correct for a packet no window re-priced
    and wrong for one a window did.

    ``swing`` is the crit blend and the target's capped flat subtraction the packet
    met on its way into the defender, and ``None`` a declaration no basic-attack
    swing delivered.

    ``routing`` is present exactly on a packet a routing family re-delivered at a
    second subject.  It records *how* rather than *how much*: the share it names is
    already applied to ``raw_amount`` by :func:`route_declared_packet`, and
    ``rule_id`` stays the **source** mechanic so the packet is attributed to the
    family that declared its magnitude.
    """

    raw_amount: float
    damage_type: str
    rule_id: str
    holder_amp: float = 1.0
    effective_resistance: float | None = None
    swing: BasicAttackSwing | None = None
    routing: RoutingProvenance | None = None

    @property
    def amped_raw(self) -> float:
        """The declaration composed with the holder's amps, still unmitigated."""
        return float(self.raw_amount) * float(self.holder_amp)

    @property
    def amped_crit_raw(self) -> float:
        """The crit branch's magnitude, composed with the same holder amps.

        Its own factors are already folded into ``swing.crit_raw_amount``.
        """
        swing = self.swing
        if swing is None:  # pragma: no cover - guarded by the caller
            return self.amped_raw
        return float(swing.crit_raw_amount) * float(self.holder_amp)


#: The damage classes a resistance answers for.  ``true`` is deliberately
#: outside it: true damage is *priced* (at no resistance), never refused, and
#: the branch below says so rather than leaning on a missing entry.
MITIGATED_DAMAGE_TYPES = frozenset({"physical", "magic"})

#: The fight published no effective resistance of the packet's class, so
#: there is nothing for the declaration to be mitigated against.  This is the
#: from-declaration path's only refusal, and it is the same fact the ratio
#: path refuses on — a packet whose source exposed no effective resistance.
NO_RESISTANCE_PUBLISHED = "no_effective_resistance_published"

#: The packet declares a damage class no resistance answers for.  Refused
#: rather than paid raw: an unrecognized class is a declaration nobody has
#: decided how to mitigate, and paying it in full would be that decision
#: taken by silence.
UNPRICEABLE_DAMAGE_TYPE = "unpriceable_damage_type"


class DeclaredPrice(NamedTuple):
    """What the walk's own pricing produced for one declared packet.

    ``amount`` is ``None`` exactly when ``unavailable`` names a reason, so a
    refusal cannot be read as a zero a caller may quietly add to a total.
    ``resistance`` is the value the raw amount was mitigated at and is
    ``None`` for true damage, which met none.
    """

    amount: float | None
    resistance: float | None
    unavailable: str = ""


def mitigate_declared(raw_amount: float, damage_type: str, resistance: float) -> float:
    """One raw declared amount, mitigated at one resistance.

    Floored at zero, because mitigating a negative declaration would heal.
    """
    raw = max(0.0, float(raw_amount))
    if damage_type == "true":
        return raw
    return apply_resistance(raw, resistance)


def route_declared_packet(
    source: DeclaredPacket, routing: RoutingProvenance
) -> DeclaredPacket:
    """One source family's declared packet, re-delivered at a second subject.

    A routing family contributes a *share* and a *subject*, so this scales the
    source family's magnitude by the share and records the route.  Every other
    term rides across unchanged, and ``rule_id`` stays the source mechanic's:
    a router that declared the magnitude it routes would be a second producer
    of a number a source family already declares.

    A share outside ``[0, 1]`` is refused rather than clamped.  A router that
    re-delivered more than the packet it is routing has misread its own
    declaration, and paying the smaller number would decide a question the
    caller got wrong.
    """
    share = float(routing.damage_share)
    if not 0.0 <= share <= 1.0:
        raise ValueError(
            f"{routing.router_rule_id!r} routes {share!r} of "
            f"{source.rule_id!r}'s declared magnitude; a share is a fraction "
            "of the packet being re-delivered and this one is not"
        )
    routed = source.raw_amount * share
    swing = source.swing
    return source._replace(
        raw_amount=routed,
        routing=routing,
        swing=(
            None
            if swing is None
            else swing._replace(crit_raw_amount=swing.crit_raw_amount * share)
        ),
    )


def price_declared_packet(
    packet: DeclaredPacket,
    *,
    baseline_effective_armor: float | None,
    baseline_effective_mr: float | None,
    dynamic_bonus_armor: float = 0.0,
    dynamic_bonus_magic_resistance: float = 0.0,
) -> DeclaredPrice:
    """Price one declared packet against the resistance it actually meets.

    The two baselines are the fight's published effective armour and magic
    resistance; the two dynamic values are the deltas the walk armed from the
    subject's combat state before this packet resolved.  Their sum is the
    resistance the declaration meets, which is the whole difference between
    this and a ratio: there the delta re-prices an already-mitigated number,
    here it is part of the mitigation applied once.  A packet carrying its own
    ``effective_resistance`` outranks both, because a pair engine that
    re-priced it inside a penetration window priced it at a different one and
    paying the baseline would delete the window.

    A refusal is returned rather than raised: an unpriceable packet is a fact
    about the fight the walk receipts and goes on from, not a bug.
    """
    damage_type = packet.damage_type
    if damage_type == "true":
        return DeclaredPrice(_priced_at(packet, 0.0), None)
    if damage_type not in MITIGATED_DAMAGE_TYPES:
        return DeclaredPrice(None, None, UNPRICEABLE_DAMAGE_TYPE)
    if damage_type == "physical":
        baseline, delta = baseline_effective_armor, dynamic_bonus_armor
    else:
        baseline, delta = baseline_effective_mr, dynamic_bonus_magic_resistance
    if packet.effective_resistance is not None:
        baseline = packet.effective_resistance
    if baseline is None:
        return DeclaredPrice(None, None, NO_RESISTANCE_PUBLISHED)
    resistance = float(baseline) + max(0.0, float(delta or 0.0))
    return DeclaredPrice(_priced_at(packet, resistance), resistance)


def _priced_at(packet: DeclaredPacket, resistance: float) -> float:
    """One declared packet's amount at one resistance, swing terms and all.

    The whole of what the pricing stage does to a magnitude, in order: the
    holder's amps compose pre-mitigation, the composed value is mitigated once
    at the resistance the packet met, and a packet delivered as a basic-attack
    swing then meets its target-side terms per branch before they are blended.
    """
    swing = packet.swing
    if swing is None:
        return mitigate_declared(packet.amped_raw, packet.damage_type, resistance)
    return swing.blended(
        swing.less_flat_reduction(
            mitigate_declared(packet.amped_raw, packet.damage_type, resistance)
        ),
        swing.less_flat_reduction(
            mitigate_declared(packet.amped_crit_raw, packet.damage_type, resistance)
        ),
    )


__all__ = [
    "MITIGATED_DAMAGE_TYPES",
    "NO_RESISTANCE_PUBLISHED",
    "UNPRICEABLE_DAMAGE_TYPE",
    "AuthoredDeclaration",
    "BasicAttackSwing",
    "DeclaredPacket",
    "DeclaredPrice",
    "RoutingProvenance",
    "mitigate_declared",
    "price_declared_packet",
    "route_declared_packet",
]
