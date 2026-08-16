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

**Nothing declares a price yet.**  Every family still reaches the walk as the
pair engine's timed rows, and this path stays inert until a family's
retirement slice hands it a :class:`DeclaredPacket` — which is what keeps
this stage a re-spelling rather than a re-pricing.  The amp term is armed on
the same terms: it reaches whatever the first retiring family hands it, and
nothing before that.
"""

from __future__ import annotations

from typing import NamedTuple

from ..resistance import apply_resistance


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
    """

    raw_amount: float
    damage_type: str
    rule_id: str
    holder_amp: float = 1.0

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

    A refusal is returned rather than raised, because an unpriceable packet
    is a fact about the fight the walk receipts and goes on from, not a
    programming error.
    """
    damage_type = packet.damage_type
    if damage_type == "true":
        return DeclaredPrice(
            mitigate_declared(packet.amped_raw, damage_type, 0.0), None
        )
    if damage_type not in MITIGATED_DAMAGE_TYPES:
        return DeclaredPrice(None, None, UNPRICEABLE_DAMAGE_TYPE)
    if damage_type == "physical":
        baseline, delta = baseline_effective_armor, dynamic_bonus_armor
    else:
        baseline, delta = baseline_effective_mr, dynamic_bonus_magic_resistance
    if baseline is None:
        return DeclaredPrice(None, None, NO_RESISTANCE_PUBLISHED)
    resistance = float(baseline) + max(0.0, float(delta or 0.0))
    return DeclaredPrice(
        mitigate_declared(packet.amped_raw, damage_type, resistance), resistance
    )


__all__ = [
    "MITIGATED_DAMAGE_TYPES",
    "NO_RESISTANCE_PUBLISHED",
    "UNPRICEABLE_DAMAGE_TYPE",
    "DeclaredPacket",
    "DeclaredPrice",
    "mitigate_declared",
    "price_declared_packet",
]
