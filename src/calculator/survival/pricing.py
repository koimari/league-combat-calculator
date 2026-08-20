"""A declared packet's price, computed by the walk that pays it.

The coupled walk consumes the one-pair engine's **post-mitigation** rows.
Where the subject's resistance moves mid-fight it recovers the pre-mitigation
side by ratio (``transitions.reprice_dynamic_resistance``), and where the
packet published no resistance baseline to ratio against it refuses by name
rather than inventing one.  That is sound for a number some engine already
priced, and it cannot work at all for a number no engine has priced yet: a
family whose interpreter hands the walk its *declaration* brings a raw value
and no mitigation to divide back out, so under the ratio it has nowhere to
hand its price.

This module is where a raw declared value becomes a mitigated one, in two
levels because two callers want different halves:

* :func:`mitigate_declared` is the arithmetic — one raw amount at one
  resistance, with true damage bypassing it.  The strike-back the coupled
  timeline schedules (``survival.compile.thorns_return_damage``) is the one
  from-raw producer that predates this module, and it reads this function,
  so the tree holds one such home rather than a precedent and a successor.
* :func:`price_declared_packet` is the walk's own reading: it resolves the
  resistance the packet meets *at the moment it resolves* — the fight's
  published effective resistance plus whatever delta the walk has armed
  since — and mitigates the declaration against it.  Nothing is divided, so
  the armed delta is simply part of the resistance the raw value meets
  rather than a second factor applied to a mitigated one.

**The declared amp term.**  The pair engine applies the holder's own static,
pair-local amplifiers to the numbers it prices — ``damage._mitigate``
multiplies magic damage by the holder's magic amp, and the per-part amps
multiply the ability and basic-attack parts on top of it.  A walk that priced
a family's declaration without them would delete a measured contribution from
every total that holds it, which is worse than the ratio path it replaces
because that path at least refuses by name.  So a :class:`DeclaredPacket`
carries ``holder_amp``, composed at build time by
``interpreters.delta_amp.resolve_static_holder_amps`` and applied
**pre-mitigation**: the composed value is mitigated once rather than a
mitigated number being re-multiplied.  Umbrella Amendment M, Ruling 1
(2026-08-15), which is also this term's ordering.

**The per-packet resistance term.**  A fight publishes *one* effective
armour and one effective magic resistance, and the pair engine does not
price every packet at them: once the complete authored ledger exists it
re-prices packets it already authored — ``damage._apply_temporary_lethality_windows``
rescales later physical packets when a Firmament window opens, and
``damage._apply_liandry_reprice`` folds a raised maximum health back onto a
burn's own ticks.  A declaration priced at the fight's published baseline
would delete those windows from every total that holds one, which is a
behaviour change wearing a re-spelling's name.  So a :class:`DeclaredPacket`
carries ``effective_resistance``: the resistance **its own packet met**,
transported on the declaration from the authored ledger rather than resolved
again at the walk, and kept in step by every site that re-prices an authored
event.  Umbrella Amendment N, Ruling 1 (2026-08-16).

**The basic-attack swing composition.**  Every family retired so far reaches
its target through ``damage._mitigate`` and nothing else — a resistance and
the holder's own amps, which is exactly what the two terms above carry.  A
packet delivered as a *basic-attack swing* is priced by
``damage._mitigate_basic_attack_swing`` instead, which meets three further
terms on the target's side and then blends a crit branch against a non-crit
one.  Two of the three **fold**: the target's critical-strike damage
multiplier and the plating multiplier are pure factors on a linear
mitigation, so they compose into the declared magnitude and price to the
same real number.  Warden's Mail's Rock Solid never folds —
``min(flat, per_hit × cap)`` is a capped flat **subtraction**, applied to
each branch separately so the cap bites on one and not the other, and no
magnitude a declaration could state reproduces one.  So a
:class:`DeclaredPacket` may carry a :class:`BasicAttackSwing`: the blend and
the subtraction, transported on the declaration from the authored ledger
rather than resolved again at the walk, for the reason Amendment N gave for
the resistance — what the walk must reproduce is the term *this packet* met
and not the term the fight settled at.  A declaration no swing delivered
carries none and prices exactly as it prices today.  Umbrella Amendment R,
Ruling 1 (2026-08-16).

**A routing family declares no magnitude.**  A packet may also reach a subject
because some *other* family's packet was re-delivered there: Wind's Fury's
bolt carries a declared share of the swing that fired it, and the attack's
on-hit effects are copied onto the bolt's target.  ``secondary_target`` is a
**routing family** — it re-delivers source families' declared magnitudes at a
second subject and declares no magnitude of its own, because the magnitude
belongs to the family that declared it (D-60, one producer per number).  So a
routed packet is built by :func:`route_declared_packet` from the **source**
family's own declaration composed with the router's declared share; it keeps
the source mechanic as its ``rule_id``, so D-62 attributes it at
``(source mechanic, secondary subject, event_id)`` — the *subject* being what
keeps that key clear of the same source mechanic's primary delivery — and the
routing itself is recorded as :class:`RoutingProvenance`, which is where a
fact about *how* a packet reached a subject belongs and is not a second
number.  Umbrella Amendment R, Ruling 3 (2026-08-16).

**Who declares a price.**  Every family in
``program.build.walk_repriced_mechanics()`` hands the walk a
:class:`DeclaredPacket`; the pair engine's timed rows are re-spelled here,
not re-priced.
"""

from __future__ import annotations

from typing import NamedTuple

from ..resistance import apply_resistance


class BasicAttackSwing(NamedTuple):
    """The composition a packet delivered as a basic-attack swing is priced by.

    Umbrella Amendment R, Ruling 1.  The pair engine prices a swing as two
    branches blended by the holder's crit chance, and meets three target-side
    terms on the way; this carries the half of that a declared magnitude
    cannot.

    **What is here is what does not fold.**  The target's critical-strike
    damage multiplier and the plating multiplier are pure factors on a linear
    mitigation, so the declaring site folds them into the two branch
    magnitudes and the walk prices the same real number without knowing they
    exist.  What it cannot fold is the **blend** — two magnitudes, not one —
    and Warden's Mail's **capped flat subtraction**, which is not a factor at
    all and is applied to each branch *before* the blend, so its cap bites on
    the crit branch and not on the non-crit one.

    ``crit_chance`` is the blend weight and ``crit_raw_amount`` the crit
    branch's own pre-mitigation magnitude, factors already folded; the packet's
    ``raw_amount`` is the non-crit branch's.  The three reduction fields are
    named for the fight-state fields the pair engine reads them from, so the
    term census's join between an engine field and the term that carries it is
    a name match rather than a table: ``basic_damage_flat_reduction`` and
    ``basic_damage_flat_reduction_cap`` are the two halves of
    ``min(flat, per_hit × cap)``, and ``instances`` is how many of them this
    declaration's packet consumed — one, for one swing.

    A holder with no crit chance and a target with no Rock Solid still gets a
    faithful blend: the weight is zero and the subtraction is inert, which is
    a measured answer rather than a default nobody asked for.
    """

    crit_chance: float
    crit_raw_amount: float
    basic_damage_flat_reduction: float = 0.0
    basic_damage_flat_reduction_cap: float = 0.0
    instances: int = 1

    def less_flat_reduction(self, branch: float) -> float:
        """One mitigated branch, less the target's capped flat subtraction.

        ``damage._apply_target_basic_damage_reduction``'s own arithmetic, on
        one branch: the flat, capped at a share of what one instance of the
        branch is worth, taken once per instance and floored at zero.  A
        non-positive branch is returned untouched, because a flat defensive
        proc cannot be consumed by a negative algebraic modifier — the pair
        engine's reading, and the reason this is not a plain ``max``.
        """
        flat = float(self.basic_damage_flat_reduction)
        cap = float(self.basic_damage_flat_reduction_cap)
        instances = int(self.instances)
        if branch <= 0.0 or flat <= 0.0 or cap <= 0.0 or instances <= 0:
            return branch
        per_instance = branch / instances
        return max(0.0, branch - min(flat, per_instance * cap) * instances)

    def blended(self, non_crit: float, crit: float) -> float:
        """The deterministic blend of the two priced branches.

        The weight is the holder's crit chance, clamped to the unit interval
        it is a probability over: a declaration outside it would turn one
        branch into a negative contribution, which is a malformed declaration
        rather than a fight.  Clamping a value already inside the interval is
        the identity, so the blend stays bit-for-bit the pair engine's.
        """
        weight = min(1.0, max(0.0, float(self.crit_chance)))
        return weight * crit + (1.0 - weight) * non_crit


class RoutingProvenance(NamedTuple):
    """How a routed packet reached the subject it was paid at.

    Umbrella Amendment R, Ruling 3.  A routing family re-delivers a source
    family's declared magnitude at a second subject; what it contributes is
    the routing, and this is that routing stated as the fact it is.  It is
    **not a number the walk adds** — the number is the source family's, and
    the share below is applied to the source family's own magnitude rather
    than declared beside it.

    ``router_rule_id`` is the mechanic that did the routing and is carried for
    the receipt: a copied packet whose provenance named nobody would be a
    magnitude arriving at a subject with no account of how, which is the
    silence this campaign exists to remove.  ``damage_share`` is the share the
    router declares, and it is the only number a routing family states about a
    packet's size.
    """

    router_rule_id: str
    damage_share: float


class AuthoredDeclaration(NamedTuple):
    """One packet's declaration as the pair engine's authored ledger carries it.

    Six facts and no price: which rule authored the packet, the
    pre-mitigation magnitude that rule's own interpreter compiled, the attack
    class the rule declares — which decides *which* of the holder's
    amplifiers the packet earns — the effective resistance the packet itself
    met, the basic-attack swing composition it was delivered through, and the
    route a routing family re-delivered it by.

    It rides the engine's own event, which is why it is a plain tuple on the
    wire and a named shape here: the ledger has two row spellings (a dict row
    and a positional light row) and one declaration, and a reader that
    unpacked the tuple by index in each of them would be two readers of one
    declaration.  This is the one home of what those six positions mean;
    ``program.compile.declared_packet_of`` composes the remaining term, the
    holder's own amps, on the walk's side.

    ``effective_resistance`` is the term umbrella Amendment N, Ruling 1 adds,
    and the two methods below are the *kept in step* half of that ruling: a
    site that re-prices an already-authored packet restates the declaration
    riding it, instead of leaving a magnitude or a mitigation behind that the
    walk would then price the packet at.  ``None`` is a packet whose ledger
    published no resistance for its class, which is a refusal at the pricing
    stage and never a zero.

    ``swing`` is the term umbrella Amendment R, Ruling 1 adds: the branch
    blend and the capped flat subtraction a packet delivered as a
    basic-attack swing met, transported the same way and for the same reason.
    ``None`` is a declaration no swing delivered, which is every declaration
    priced through ``damage._mitigate`` alone, and it prices exactly as it
    priced before the term existed.  It rides as a plain tuple beside the
    other four because the ledger's positional row spelling carries the whole
    declaration as one tuple; :meth:`swing_composition` is the one reader of
    what that position means.

    ``routing`` is the fact umbrella Amendment R, Ruling 3 adds: present
    exactly on a packet a **routing family** re-delivered at a second
    subject, and absent on one that reached its subject directly.  It rides
    the declaration rather than being resolved at the walk for the reason the
    resistance and the swing do — what the walk must reproduce is how *this*
    packet travelled — and it is a fact rather than a magnitude: the
    ``rule_id`` above stays the **source** mechanic's, and
    :func:`route_declared_packet` is still the one place a share is applied.
    """

    rule_id: str
    raw_amount: float
    attack_class: str
    effective_resistance: float | None = None
    swing: tuple | None = None
    routing: tuple | None = None

    def swing_composition(self) -> "BasicAttackSwing | None":
        """This declaration's swing composition, or ``None`` if none rode it.

        The one place the wire tuple becomes the named shape, so a reader
        that unpacked it by index would be a second reader of one term.
        """
        return None if self.swing is None else BasicAttackSwing(*self.swing)

    def routing_provenance(self) -> "RoutingProvenance | None":
        """This declaration's routing, or ``None`` if it reached its subject directly.

        :meth:`swing_composition`'s reason one position over: the ledger
        carries the whole declaration as one tuple, and a reader that
        unpacked this position by index would be a second reader of one fact.
        """
        return None if self.routing is None else RoutingProvenance(*self.routing)

    def routed_by(self, routing: "RoutingProvenance") -> "AuthoredDeclaration":
        """The same declaration, re-delivered at a second subject.

        What a routing family stamps on the events it authors: the source
        family's magnitude and mitigation are unchanged — they are facts
        about the packet, not about how it travelled — and the route is now
        transported with it rather than left for the walk to guess at.
        """
        return self._replace(routing=tuple(routing))

    def delivered_as_a_swing(self, swing: BasicAttackSwing) -> "AuthoredDeclaration":
        """The same declaration, carrying the swing composition it met.

        What a family whose packet is delivered as a basic-attack swing
        stamps on its own authored event: the magnitude and the mitigation
        are unchanged, and the target-side terms the swing met are now
        transported with it rather than left behind for the walk to guess at.
        """
        return self._replace(swing=tuple(swing))

    def repriced_at(self, effective_resistance: float) -> "AuthoredDeclaration":
        """The same declaration, met by a different resistance.

        What a temporary penetration window does to a packet it already
        authored: the magnitude is unchanged and the mitigation is not.
        """
        return self._replace(effective_resistance=float(effective_resistance))

    def rescaled_by(self, factor: float) -> "AuthoredDeclaration":
        """The same declaration, at a magnitude scaled by *factor*.

        What a max-health reprice does to a burn tick it already authored:
        the mitigation is unchanged and the magnitude is not.  The scale is
        the ratio the site applied to the priced packet, so the declaration
        moves by exactly what the packet moved by.
        """
        return self._replace(raw_amount=float(self.raw_amount) * float(factor))


class DeclaredPacket(NamedTuple):
    """One family's damage as its declaration states it: raw, unmitigated.

    ``rule_id`` is the declaring mechanic and is carried for the refusal as
    much as for the receipt: a declaration the walk could not price has to
    be able to name what went unpaid, because the alternative reading of an
    unpriced packet is an anonymous zero nobody notices.

    ``holder_amp`` is the **declared amp term** the umbrella's Amendment M,
    Ruling 1 adds to this stage: the holder's own static, pair-local
    amplifiers, composed for this packet's damage class and delivery by
    ``interpreters.delta_amp.StaticHolderAmps.factor_for`` and resolved at
    build time from the declarations that produce them.  It rides on the
    packet rather than being folded into ``raw_amount`` by each family,
    because a family that pre-multiplied its own declaration would be an
    undeclared second producer of one number (D-60).  ``1.0`` is a holder
    with no amp armed, which is a measured answer and not a default nobody
    asked for — the amps are resolved for every priced packet, and a
    resolution that found none is what ``1.0`` means.

    ``effective_resistance`` is the **per-packet resistance term** umbrella
    Amendment N, Ruling 1 adds: the resistance this packet's own pair-engine
    event met, transported here on the declaration from the authored ledger.
    ``None`` is a declaration whose ledger transported none, and the packet
    is then priced at the fight's published baseline — the reading that is
    correct for a packet no window re-priced and forbidden for one that a
    window did, which is why the transport stamps the term rather than
    leaving it to be inferred.

    ``swing`` is the **basic-attack swing composition** umbrella Amendment R,
    Ruling 1 adds: the crit blend and the target's capped flat subtraction the
    packet met on its way into the defender.  ``None`` is a declaration no
    basic-attack swing delivered — every family retired so far — and it is
    priced by the resistance and the amps alone, exactly as it was before the
    term existed.

    ``routing`` is the **routing provenance** umbrella Amendment R, Ruling 3
    adds: present exactly on a packet some routing family re-delivered at a
    second subject, and absent on one that reached its subject directly.  It
    records *how* rather than *how much* — the share it names has already been
    applied to ``raw_amount`` by :func:`route_declared_packet`, and
    ``rule_id`` stays the **source** mechanic so D-62 attributes the packet to
    the family that declared its magnitude.
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
        """The declaration composed with the holder's amps, still unmitigated.

        The composition is **pre-mitigation**, which is the ordering
        Amendment M, Ruling 1 rules and the reason the term rides here rather
        than being applied to the priced number: the composed value is
        mitigated once, instead of a mitigated number being re-multiplied by
        an amplifier the way a ratio path would have to do it.
        """
        return float(self.raw_amount) * float(self.holder_amp)

    @property
    def amped_crit_raw(self) -> float:
        """The crit branch's magnitude, composed with the same holder amps.

        The holder's amps are the holder's, so both branches earn them; what
        differs between the branches is the crit multiplier and the target's
        crit-damage reduction, and both of those are already folded into
        ``swing.crit_raw_amount`` by the site that declared it.
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

    The single arithmetic home for "a declaration became a number the walk
    can pay".  True damage meets no resistance and is returned whole; every
    other class goes through the one resistance formula, which already
    amplifies at a negative resistance.

    The floor is at zero because a declaration is a magnitude: a negative
    raw value is a malformed declaration, and mitigating one would turn it
    into a heal.
    """
    raw = max(0.0, float(raw_amount))
    if damage_type == "true":
        return raw
    return apply_resistance(raw, resistance)


def route_declared_packet(
    source: DeclaredPacket, routing: RoutingProvenance
) -> DeclaredPacket:
    """One source family's declared packet, re-delivered at a second subject.

    Umbrella Amendment R, Ruling 3's whole act, and it is deliberately small:
    a routing family contributes a *share* and a *subject*, so this scales the
    source family's own magnitude by the share and records the routing.  Every
    other term rides across unchanged — the resistance the source packet met,
    the holder's amps, the swing composition if the source was delivered as
    one — because they are facts about the packet and not about how it
    travelled.

    **What this deliberately does not do** is give the router a magnitude.
    ``rule_id`` stays the source mechanic's, so D-62 keys the routed
    contribution at ``(source mechanic, secondary subject, event_id)`` and the
    subject is what distinguishes it from that mechanic's primary delivery.  A
    routing family that declared the magnitude it routes would be a second
    producer of a number a source family already declares, which is exactly
    what criterion 8 forbids.

    A share outside ``[0, 1]`` is refused rather than clamped: a router that
    re-delivered more than the packet it is routing has misread its own
    declaration, and silently paying the smaller number would be this function
    deciding a question its caller got wrong.
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

    The two baselines are the fight's own published effective armour and
    magic resistance for this packet — the same figures the ratio path
    divides by — and the two dynamic values are the deltas the walk armed
    from the subject's combat state before this packet resolved.  Their sum
    is the resistance the declaration meets, which is the whole difference
    between this and a ratio: there the delta re-prices an already-mitigated
    number, here it is part of the mitigation applied once.

    **The packet's own resistance outranks the fight's** (umbrella
    Amendment N, Ruling 1).  The published baseline is the resistance the
    *fight* settled at, and a pair engine that re-prices a packet inside a
    temporary penetration window priced that packet at a different one; the
    declaration carries what its packet met, so paying the baseline for it
    would delete the window.  The baselines above are what a declaration
    that transported no such term is priced at, which is the same number for
    every packet no window touched.

    **A packet delivered as a basic-attack swing meets more than a
    resistance** (umbrella Amendment R, Ruling 1).  Where the declaration
    carries a :class:`BasicAttackSwing`, both branch magnitudes are mitigated
    at that one resistance, each branch then meets the target's capped flat
    subtraction on its own — which is why the term cannot be a factor on the
    blended number — and the two are blended by the holder's crit chance.
    The two target-side factors are not here because the declaring site
    folded them into the magnitudes, which prices to the same real number.

    A refusal is returned rather than raised, because an unpriceable packet
    is a fact about the fight the walk receipts and goes on from, not a
    programming error.
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

    The whole of what the pricing stage does to a magnitude, in the order
    umbrella Amendment R, Ruling 1 states it: the holder's amps compose
    pre-mitigation (Amendment M), the composed value is mitigated once at the
    resistance the packet met (Amendment N), and a packet delivered as a
    basic-attack swing then meets its target-side terms per branch before the
    branches are blended.

    A declaration carrying no swing composition is the whole of the tree
    today and takes the first line and no other, which is why adding the term
    moves no retired family's number.
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
