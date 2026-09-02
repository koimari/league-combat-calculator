"""On-hit strikes, interpreted: a declared formula becomes the engine's row.

Eight items add damage to every on-hit application of a basic attack.  The
number registry owns the numbers and the declaration owns the shape:
:func:`per_hit_effects` reads what a build declares and hands the fight
engine ``PerHitEffect`` records built from that declaration rather than from
a formula name.  Two facts ride the declaration instead of a name
comparison: whether the strike is re-priced as the target's health falls,
and whether an ability carrying the on-hit application pays this number or
the item's ability-hit number instead.

Nothing here is memoized, deliberately and for the same reason the catalog is
not: ``refresh_item_effects()`` has to move the answer, and a build projection
cached across a patch-day refresh is the stale literal one layer up.  The
amp chain resolves its slots per fight on exactly this basis.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ..item_behavior import (
    RESTRICTED_CHANNEL_PACKETS,
    BehaviorRule,
    BuildContext,
    EngineLane,
    FightFacts,
    KernelField,
    OnHitStrikeRule,
    RestrictedChannelRule,
    RestrictedPacket,
    RuleFamily,
)
from ..item_behavior_catalog import behavior_rules, build_context
from ..item_effects import PerHitEffect, damage_source
from ..value_ref import resolve
from . import damage_formula

# The field a strike rule compiles to for inspection: its term count.  A
# strike's *number* is not a build-time value — it depends on the target's
# live pools — so what the lane can compile is the formula's shape, and
# claiming otherwise would be a build-time number the mechanic cannot have.
STRIKE_TERM_COUNT_FIELD = "strike_terms"

# How an on-hit strike's breakdown row is named.  Presentation, kept beside
# the interpreter that builds the row rather than in the registry.
ON_HIT_SUFFIX = "on-hit"
ON_HIT_BREAKDOWN_PREFIX = "on_hit_"

# How a class-restricted on-hit row is named and labelled.  Both carry the
# packet's own target class, so the row of an item that has a champion-class
# strike as well can never collide with it, and a channel armed for another
# class would name that class rather than borrow this one's.
CLASS_RESTRICTED_BREAKDOWN_KEY = "{prefix}{target_class}_{owner}"
CLASS_RESTRICTED_SUFFIX = "{mechanic} vs {target_class}s"


class OnHitStrikeInterpretationError(ValueError):
    """A rule reached this interpreter that is not an on-hit strike."""


def strike_fields(
    rule: BehaviorRule, ctx: BuildContext, lane: EngineLane
) -> tuple[KernelField, ...]:
    """One on-hit strike's compiled numbers, stamped with *lane*.

    The shape a strike compiles to, and the proof its bases resolve.
    Compiling here is what makes a formula's *build-time* failures — a
    missing registry key, a basis with no reading — surface when the build
    is made rather than on whichever event first asks for the number.

    Registered for both the pair engine and the receipt walk: the lane is the
    only thing that differs between them, so one body is what makes "the walk
    reads the same declaration the pair engine reads" a property of the tree
    rather than a claim two functions could drift out of.
    """
    payload = rule.payload
    if not isinstance(payload, OnHitStrikeRule):
        raise OnHitStrikeInterpretationError(
            f"{rule.mechanic_id} is not an on-hit strike rule"
        )
    damage_formula.compile_formula(payload.formula, ctx)
    return (
        KernelField(
            name=STRIKE_TERM_COUNT_FIELD,
            value=len(payload.formula.terms),
            lane=lane,
            rule_id=rule.mechanic_id,
        ),
    )


# The mechanic slug a class-restricted on-hit row previews.  One prefix and
# the declaration's own target class, so the id follows the declaration
# instead of being a second spelling of it.
CLASS_RESTRICTED_MECHANIC_PREFIX = "class_restricted_on_hit"


def class_restricted_packets(
    owners: Sequence[str],
) -> tuple[tuple[BehaviorRule, RestrictedPacket], ...]:
    """Every declared on-hit packet *owners* pay only against one target class.

    Read off :class:`~..item_behavior.RestrictedChannelRule` — a stat
    derivation by family, because it answers where a sourced number goes, and
    interpreted here, because where this one goes is an on-hit row.  Every
    entry routing a number down the channel pays it, in build order.
    """
    return tuple(
        (rule, packet)
        for owner in owners
        for rule in behavior_rules(owner)
        if isinstance(rule.payload, RestrictedChannelRule)
        and (packet := RESTRICTED_CHANNEL_PACKETS[rule.payload.channel]) is not None
    )


# Which declaration prices its cached clause at the FIGHT's target class, and
# the clause it prices, named as the cache names it.  A restricted channel
# answers that from its own packet; this is the reviewed rest, where the class
# reading lives in a ledger no declaration can carry — a Manaflow ledger is
# handed the fight's class, so a minion is paid the trigger amount and not the
# champion one.  Keyed by mechanic id and not by payload type: each holder is
# reviewed on its own, and a holder joins only once the ledger runs every
# trigger its cached clause names (the three on-hit holders spend a charge on
# a basic attack too, and did not join until that stream ran).
CLASS_READING_MECHANICS: Mapping[str, str] = {
    "archangels_staff.mana_charge": "Manaflow",
    "manamune.mana_charge": "Manaflow",
    "tear_of_the_goddess.mana_charge": "Manaflow",
    "whispering_circlet.mana_charge": "Manaflow",
    "winters_approach.mana_charge": "Manaflow",
}


def adjudicated_target_class_mechanics(owner: str) -> frozenset[str]:
    """Every cached clause of *owner* the fight model prices at the fight's
    own target class, named as the cache names it.

    The reader ``item_effects.target_class_denials`` is handed.  Per clause,
    so an item's unpriced clause cannot ride in on a priced sibling's
    admission."""
    return frozenset(
        {packet.mechanic for _, packet in class_restricted_packets([owner])}
        | {
            mechanic
            for rule in behavior_rules(owner)
            if (mechanic := CLASS_READING_MECHANICS.get(rule.mechanic_id)) is not None
        }
    )


def class_restricted_per_hit_effects(
    owners: Sequence[str], *, target_class: str
) -> tuple[PerHitEffect, ...]:
    """The class-restricted on-hits a *target_class* fight arms, in build order.

    A champion-class fight arms nothing: no declaration names it, which is
    the enum's whole claim.  The amount is resolved from the declaration's
    own reference, so the registry stays the number's one home.
    """
    effects: list[PerHitEffect] = []
    for rule, packet in class_restricted_packets(owners):
        if packet.target_class != target_class:
            continue
        amount = resolve(rule.payload.amount)
        if amount <= 0.0:
            raise OnHitStrikeInterpretationError(
                f"{rule.mechanic_id} resolved a non-positive class-restricted "
                f"on-hit value {amount!r}"
            )
        effects.append(
            PerHitEffect(
                damage_source(
                    rule.owner,
                    packet.damage_class.value,
                    lambda _inputs, amount=amount: amount,
                    suffix=CLASS_RESTRICTED_SUFFIX.format(
                        mechanic=packet.mechanic, target_class=packet.target_class
                    ),
                    breakdown_key=CLASS_RESTRICTED_BREAKDOWN_KEY.format(
                        prefix=ON_HIT_BREAKDOWN_PREFIX,
                        target_class=packet.target_class,
                        owner=rule.owner,
                    ),
                ),
                target_class=packet.target_class,
            )
        )
    return tuple(effects)


def strike_mechanic_id(owner: str) -> str:
    """*owner*'s on-hit strike mechanic id, or a stop.

    What the pair engine needs to stamp the row it authors with the mechanic
    that row previews: ``damage._layer_on_hit_effects`` walks
    :class:`~..item_effects.PerHitEffect` records, which carry an item name
    and no rule id, and reading the id back off the declaration here is what
    keeps the stamp from being a second spelling of the mechanic slug inside
    the engine.

    A stop rather than a default: an unstamped on-hit row would keep the pair
    engine's number in every roster total *and* leave the walk pricing the
    declaration, which is the double count this family's retirement exists to
    make unrepresentable.
    """
    rules = strike_rules([owner])
    if rules:
        return rules[0].mechanic_id
    restricted = class_restricted_packets([owner])
    if restricted:
        # A class-restricted branch is armed only by a fight whose own target
        # class matches, never by the interpreter-owned strike stream, so it
        # can never be the double count the stop below exists to prevent.  Its
        # id is derived from the declaration rather than spelled here.
        return f"{CLASS_RESTRICTED_MECHANIC_PREFIX}.{restricted[0][1].target_class}"
    raise OnHitStrikeInterpretationError(
        f"{owner} authors an on-hit row and declares no on_hit_strike "
        "rule, so its pair row has no mechanic to be a preview of"
    )


def per_hit_effect(rule: BehaviorRule, ctx: BuildContext) -> PerHitEffect:
    """One declared strike as the record the fight engine consumes."""
    payload = rule.payload
    if not isinstance(payload, OnHitStrikeRule):
        raise OnHitStrikeInterpretationError(
            f"{rule.mechanic_id} is not an on-hit strike rule"
        )
    return PerHitEffect(
        damage_source(
            rule.owner,
            payload.formula.damage_type,
            damage_formula.compile_formula(payload.formula, ctx),
            suffix=ON_HIT_SUFFIX,
            breakdown_key=f"{ON_HIT_BREAKDOWN_PREFIX}{rule.owner}",
        ),
        tracks_current_health=damage_formula.reads_target_current_health(
            payload.formula
        ),
        superseded_by_ability_proc=payload.superseded_by_ability_proc,
    )


def strike_rules(owners: Sequence[str]) -> tuple[BehaviorRule, ...]:
    """Every on-hit strike *owners* declare, in build order."""
    return tuple(
        rule
        for owner in owners
        for rule in behavior_rules(owner)
        if rule.family is RuleFamily.ON_HIT_STRIKE
    )


def per_hit_effects(
    owners: Sequence[str],
    *,
    facts: FightFacts,
) -> tuple[PerHitEffect, ...]:
    """Every on-hit strike this build declares, in build order (purchase order,
    the registry's append order and the engine's breakdown-row order).  The
    facts are threaded, not defaulted, though no on-hit coefficient reads one:
    a placeholder would be the silent default the context refuses."""
    return tuple(
        per_hit_effect(rule, build_context(rule.owner, facts))
        for rule in strike_rules(owners)
    )


__all__ = [
    "CLASS_READING_MECHANICS",
    "CLASS_RESTRICTED_BREAKDOWN_KEY",
    "CLASS_RESTRICTED_MECHANIC_PREFIX",
    "CLASS_RESTRICTED_SUFFIX",
    "ON_HIT_BREAKDOWN_PREFIX",
    "ON_HIT_SUFFIX",
    "STRIKE_TERM_COUNT_FIELD",
    "OnHitStrikeInterpretationError",
    "adjudicated_target_class_mechanics",
    "class_restricted_packets",
    "class_restricted_per_hit_effects",
    "per_hit_effect",
    "per_hit_effects",
    "strike_fields",
    "strike_mechanic_id",
    "strike_rules",
]
