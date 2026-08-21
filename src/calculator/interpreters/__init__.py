"""One reading per family per engine lane, and the gates over that map.

A declared behaviour is only worth something if some engine runs it.  This
package is where that is decided and, more importantly, where *not* deciding
it becomes visible: :func:`compilability_for` refuses to call an owner
compilable, for the refusal it is asked about, while any of its rules is
receipt-only in that scope, and :func:`reachability_report` names both a
declaration no reading reaches and a registered reading no declaration
reaches.  Both directions have live motivating cases, which is why neither is
dropped as theoretical.

Two tables.  :data:`INTERPRETERS` maps ``(family, lane)`` to the function that
compiles one rule's :class:`~..item_behavior.KernelField`s for that lane, and
:func:`compile_rule` is its dispatch.  :data:`RESOLVERS` maps the six defence
families to the function that resolves one rule against a subject, and
:func:`resolve_defense` is its dispatch.  A registry with no entry is a stop,
which is what makes "delete a family's reading and its items are withheld" a
property of the code instead of a claim about it.

**Readings run at build time.**  A walk-lane reading emits ``KernelField``s —
value-typed fields the kernel already understands — rather than being called
from inside the walk, so the dependency stays one-way: ``interpreters/`` may
read ``survival/``'s vocabulary and nothing under ``survival/`` imports this
package.  A source assertion in the test front door pins that, because a
reading that touched ``SurvivalAction`` and was called from
``survival/transitions.py`` would close exactly the cycle the leaf-ness of
``item_behavior`` does not cover.

There is one module per family and never a single dispatch file: an
eighteen-branch god module cannot carry eighteen test front doors, and the
derived front-door check is what would notice.
"""

# This module's length is one row per ``(family, lane)`` and one dated receipt
# per gap, and both sets are the campaign's own vocabulary: splitting the
# registry from the reasons would put the count in one file and the excuse in
# another, which is exactly the prose-outruns-code shape counter 4 exists to
# measure.  Same trade, same idiom, as ``trigger_stream``'s own table.
# pylint: disable=too-many-lines

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any

from ..ability_spec import Authority
from ..item_behavior import (
    BehaviorRule,
    BuildContext,
    Compilability,
    Compilable,
    CooldownProcRule,
    DamageDeferralRule,
    DefenseOutcome,
    DefenseSubject,
    EngineLane,
    ForcedCritRule,
    KernelField,
    ReceiptOnly,
    ReceiptScope,
    RuleFamily,
    SUBJECT_AUTHORITY,
    Subject,
    ThresholdRegenRule,
)
from ..item_behavior_catalog import behavior_rules, registry_entries, rule_owners
from ..trigger_stream import CAPABILITIES
from .stat_derivation import declared_stat_derivations
from . import (
    active_cast,
    ally_packet,
    cast_proc,
    charged_strike,
    combat_state,
    crit_profile,
    damage_routing,
    defense_state,
    delta_amp,
    on_hit_strike,
    opening_defense,
    periodic,
    reactive,
    resistance_shred,
    secondary_target,
    spellblade,
    stat_derivation,
    sustain,
    threshold_defense,
)


class InterpreterRegistryError(RuntimeError):
    """The (family, lane) map does not say what it claims to say."""


#: One rule's kernel fields for one lane.  Build-time only: the context
#: carries a level, an owner and a data version and deliberately carries no
#: walk state, and the lane is stamped onto every field emitted.
FieldsFn = Callable[[BehaviorRule, BuildContext, EngineLane], tuple[KernelField, ...]]

#: One declared defence, resolved against the subject it is defending.
ResolveFn = Callable[[BehaviorRule, DefenseSubject], DefenseOutcome]


# Which lanes must be able to answer for each family, declared rather than
# inferred from what happens to be registered — otherwise "every family is
# interpreted" would be true of an empty registry.  Counter 4 is the size of
# the gap between this table and INTERPRETERS.  Lane spellings and their
# meanings live on :class:`~..item_behavior.EngineLane`.
_FAMILY_LANES: Mapping[RuleFamily, frozenset[EngineLane]] = {
    # Strike and pricing families produce damage, so all three damage lanes
    # owe an answer.
    RuleFamily.ON_HIT_STRIKE: frozenset(
        {
            EngineLane.PAIR_ENGINE,
            EngineLane.RECEIPT_WALK,
            EngineLane.COMPILED_SCORE_WALK,
        }
    ),
    RuleFamily.CHARGED_STRIKE: frozenset(
        {
            EngineLane.PAIR_ENGINE,
            EngineLane.RECEIPT_WALK,
            EngineLane.COMPILED_SCORE_WALK,
        }
    ),
    RuleFamily.SPELLBLADE: frozenset(
        {
            EngineLane.PAIR_ENGINE,
            EngineLane.RECEIPT_WALK,
            EngineLane.COMPILED_SCORE_WALK,
        }
    ),
    RuleFamily.CAST_PROC: frozenset(
        {
            EngineLane.PAIR_ENGINE,
            EngineLane.RECEIPT_WALK,
            EngineLane.COMPILED_SCORE_WALK,
        }
    ),
    RuleFamily.PERIODIC: frozenset(
        {
            EngineLane.PAIR_ENGINE,
            EngineLane.RECEIPT_WALK,
            EngineLane.COMPILED_SCORE_WALK,
        }
    ),
    RuleFamily.ACTIVE_CAST: frozenset(
        {
            EngineLane.PAIR_ENGINE,
            EngineLane.RECEIPT_WALK,
            EngineLane.COMPILED_SCORE_WALK,
        }
    ),
    # A second target only exists where there is a roster to hit; the
    # compiled kernel prices one pair and has nowhere to put it.
    RuleFamily.SECONDARY_TARGET: frozenset(
        {EngineLane.PAIR_ENGINE, EngineLane.RECEIPT_WALK}
    ),
    RuleFamily.DELTA_AMP: frozenset(
        {
            EngineLane.PAIR_ENGINE,
            EngineLane.RECEIPT_WALK,
            EngineLane.COMPILED_SCORE_WALK,
        }
    ),
    RuleFamily.RESISTANCE_SHRED: frozenset(
        {
            EngineLane.PAIR_ENGINE,
            EngineLane.RECEIPT_WALK,
            EngineLane.COMPILED_SCORE_WALK,
        }
    ),
    # The crit profile owes the receipt walk NOTHING, and that is a ruling
    # rather than an omission: umbrella Amendment O, Ruling 1 (2026-08-16)
    # reclassifies it under this campaign's own semantic-authority rule.  Every
    # one of its three declarations names ``Subject.HOLDER`` and none of them
    # authors a pair-engine row a total holds -- the crit bonus is a multiplier
    # folded into the champion's own ``auto_attacks`` row, the cooldown refund
    # authors no damage at all, and the forced crit authors one row stamped
    # ``informational`` that is summed into nothing.  All-pair-local inputs =>
    # PAIR_ONLY, so the pair engine is this family's authoritative home and no
    # second engine prices it.  The compiled score walk is
    # NOT reclassified with it: that lane has its own blocker (H5) and its own
    # row below.  What makes this legal where D-40 forbids editing a lane table
    # from inside the counter it moves is that the emptiness is measured
    # first and stays measured: ``scripts/receipt_walk_schedule.py`` re-runs
    # the pair engine over this family's covering population and over a probe
    # per owner on every check, and the day a mechanic of it authors a row the
    # gate goes red and this lane comes back.
    RuleFamily.CRIT_PROFILE: frozenset(
        {
            EngineLane.PAIR_ENGINE,
            EngineLane.COMPILED_SCORE_WALK,
        }
    ),
    # Routing is the one pricing family the defensive resolver also builds:
    # the deferral schedule is read at the opening with every other defence,
    # and the two target-side rules are priced by the pair engine.
    RuleFamily.DAMAGE_ROUTING: frozenset(
        {
            EngineLane.PAIR_ENGINE,
            EngineLane.RECEIPT_WALK,
            EngineLane.COMPILED_SCORE_WALK,
            EngineLane.DEFENSE_RESOLVER,
        }
    ),
    # Defence families are built by the defensive resolver and then have to
    # survive the compiled walk; the pair engine reads the resolver's output
    # rather than the rule.
    #
    # Three of them owe the RECEIPT WALK nothing, and that is a ruling rather
    # than an omission: umbrella Amendment Q (2026-08-16) corrects the
    # declaration for the three families the defence resolver feeds.  Their
    # walk-side need is satisfied THROUGH the lane they declare -- an
    # interpreter answers for ``defense_resolver``, and what the receipt walk
    # consumes is the state that interpreter built (``update_combat_state``
    # reads Steadfast's stack schedule; the ledger's pools read the lifeline
    # shields; the opening state carries the annuls and the stasis) -- so a
    # receipt-walk interpreter beside it would be a second producer of one
    # number, which D-60 and criterion 8 forbid.  One producer is what the
    # one-engine thesis demands, so the receipt-walk lane was a declaration
    # these families never owed.  The compiled score walk is NOT corrected
    # with them: that lane has its own blocker (H5) and its own rows below.
    #
    # What makes this legal where D-40 forbids editing a lane table from
    # inside the counter it moves is that the ground is measured before the
    # table moves and stays measured after it, in both directions:
    # ``scripts/receipt_walk_schedule.py`` joins what each family's resolver
    # interpreter writes to every read of those fields off a resolved
    # defences value in the source outside the resolver, and removes the
    # resolver interpreter to assert that every declaring owner then answers
    # ``withheld`` naming the missing pair rather than a silent zero.  The day
    # a mechanic of one of them authors a walk-priced row the resolver does
    # not feed, the gate goes red and the lane comes back.
    RuleFamily.OPENING_DEFENSE: frozenset(
        {
            EngineLane.DEFENSE_RESOLVER,
            EngineLane.COMPILED_SCORE_WALK,
        }
    ),
    RuleFamily.THRESHOLD_DEFENSE: frozenset(
        {
            EngineLane.DEFENSE_RESOLVER,
            EngineLane.COMPILED_SCORE_WALK,
        }
    ),
    RuleFamily.COMBAT_STATE: frozenset(
        {
            EngineLane.DEFENSE_RESOLVER,
            EngineLane.COMPILED_SCORE_WALK,
        }
    ),
    RuleFamily.REACTIVE: frozenset(
        {
            EngineLane.DEFENSE_RESOLVER,
            EngineLane.RECEIPT_WALK,
            EngineLane.COMPILED_SCORE_WALK,
        }
    ),
    # Sustain is the second family the defensive resolver also builds: the
    # received-healing multiplier scales state three earlier defences wrote,
    # so it is resolved with them rather than by whoever heals.
    RuleFamily.SUSTAIN: frozenset(
        {
            EngineLane.PAIR_ENGINE,
            EngineLane.RECEIPT_WALK,
            EngineLane.COMPILED_SCORE_WALK,
            EngineLane.DEFENSE_RESOLVER,
        }
    ),
    # A derived stat is resolved before any damage exists, and the pair
    # engine reads the resolved stat block.
    RuleFamily.STAT_DERIVATION: frozenset(
        {EngineLane.STAT_RESOLVER, EngineLane.PAIR_ENGINE}
    ),
    # An ally packet is a roster fact; the pair engine has no ally.
    RuleFamily.ALLY_PACKET: frozenset(
        {EngineLane.RECEIPT_WALK, EngineLane.COMPILED_SCORE_WALK}
    ),
}


# The registry itself.  One entry per family per lane; every remaining gap is
# counted by the frontier's counter 4 rather than being an absence nobody
# measures.  Two lanes sharing one function is the normal case — a lane is
# stamped onto the fields, not baked into the body — and the four families
# whose two lanes disagree about what they emit say so with two functions.
INTERPRETERS: Mapping[tuple[RuleFamily, EngineLane], FieldsFn] = {
    (RuleFamily.ACTIVE_CAST, EngineLane.PAIR_ENGINE): active_cast.active_fields,
    (RuleFamily.ACTIVE_CAST, EngineLane.RECEIPT_WALK): active_cast.active_fields,
    (RuleFamily.ALLY_PACKET, EngineLane.RECEIPT_WALK): ally_packet.packet_fields,
    (RuleFamily.CAST_PROC, EngineLane.PAIR_ENGINE): cast_proc.proc_fields,
    (RuleFamily.CAST_PROC, EngineLane.RECEIPT_WALK): cast_proc.proc_fields,
    (RuleFamily.CHARGED_STRIKE, EngineLane.PAIR_ENGINE): charged_strike.strike_fields,
    (RuleFamily.CHARGED_STRIKE, EngineLane.RECEIPT_WALK): charged_strike.strike_fields,
    (
        RuleFamily.COMBAT_STATE,
        EngineLane.DEFENSE_RESOLVER,
    ): defense_state.compiled_shape,
    (RuleFamily.CRIT_PROFILE, EngineLane.PAIR_ENGINE): crit_profile.crit_fields,
    (
        RuleFamily.DAMAGE_ROUTING,
        EngineLane.DEFENSE_RESOLVER,
    ): defense_state.compiled_shape,
    (RuleFamily.DAMAGE_ROUTING, EngineLane.PAIR_ENGINE): damage_routing.pair_fields,
    (RuleFamily.DAMAGE_ROUTING, EngineLane.RECEIPT_WALK): damage_routing.walk_fields,
    (RuleFamily.DELTA_AMP, EngineLane.PAIR_ENGINE): delta_amp.amp_fields,
    (RuleFamily.DELTA_AMP, EngineLane.RECEIPT_WALK): delta_amp.amp_fields,
    (RuleFamily.ON_HIT_STRIKE, EngineLane.PAIR_ENGINE): on_hit_strike.strike_fields,
    (RuleFamily.ON_HIT_STRIKE, EngineLane.RECEIPT_WALK): on_hit_strike.strike_fields,
    (
        RuleFamily.OPENING_DEFENSE,
        EngineLane.DEFENSE_RESOLVER,
    ): defense_state.compiled_shape,
    (RuleFamily.PERIODIC, EngineLane.PAIR_ENGINE): periodic.cadence_fields,
    (RuleFamily.PERIODIC, EngineLane.RECEIPT_WALK): periodic.cadence_fields,
    (RuleFamily.REACTIVE, EngineLane.DEFENSE_RESOLVER): defense_state.compiled_shape,
    (RuleFamily.REACTIVE, EngineLane.RECEIPT_WALK): reactive.thorns_fields,
    (RuleFamily.RESISTANCE_SHRED, EngineLane.PAIR_ENGINE): resistance_shred.ramp_fields,
    (
        RuleFamily.RESISTANCE_SHRED,
        EngineLane.RECEIPT_WALK,
    ): resistance_shred.ramp_fields,
    (
        RuleFamily.SECONDARY_TARGET,
        EngineLane.PAIR_ENGINE,
    ): secondary_target.routing_fields,
    (
        RuleFamily.SECONDARY_TARGET,
        EngineLane.RECEIPT_WALK,
    ): secondary_target.routing_fields,
    (RuleFamily.SPELLBLADE, EngineLane.PAIR_ENGINE): spellblade.spellblade_fields,
    (RuleFamily.SPELLBLADE, EngineLane.RECEIPT_WALK): spellblade.spellblade_fields,
    (
        RuleFamily.STAT_DERIVATION,
        EngineLane.PAIR_ENGINE,
    ): stat_derivation.reference_fields,
    (
        RuleFamily.STAT_DERIVATION,
        EngineLane.STAT_RESOLVER,
    ): stat_derivation.reference_fields,
    (RuleFamily.SUSTAIN, EngineLane.DEFENSE_RESOLVER): defense_state.compiled_shape,
    (RuleFamily.SUSTAIN, EngineLane.PAIR_ENGINE): sustain.sustain_fields,
    (RuleFamily.SUSTAIN, EngineLane.RECEIPT_WALK): sustain.walk_fields,
    (
        RuleFamily.THRESHOLD_DEFENSE,
        EngineLane.DEFENSE_RESOLVER,
    ): defense_state.compiled_shape,
}


# The defence resolver's other half.  Compiling a defence is uniform — the
# shape is all that lane can prove at build time — but resolving one against a
# subject is each family's own arithmetic, so it is keyed by family alone.
RESOLVERS: Mapping[RuleFamily, ResolveFn] = {
    RuleFamily.COMBAT_STATE: combat_state.resolve_combat_state,
    RuleFamily.DAMAGE_ROUTING: damage_routing.resolve_deferral,
    RuleFamily.OPENING_DEFENSE: opening_defense.resolve_opening_defense,
    RuleFamily.REACTIVE: reactive.resolve_reactive,
    RuleFamily.SUSTAIN: sustain.resolve_received_healing,
    RuleFamily.THRESHOLD_DEFENSE: threshold_defense.resolve_threshold_defense,
}


def compile_rule(
    rule: BehaviorRule, ctx: BuildContext, lane: EngineLane
) -> tuple[KernelField, ...]:
    """One rule's kernel fields for *lane*, through the registered reading.

    The registry *is* the dispatch: deleting a family's reading for a lane
    stops every rule of that family on it with this error rather than letting
    the engine quietly compile nothing.
    """
    fields = INTERPRETERS.get((rule.family, lane))
    if fields is None:
        raise InterpreterRegistryError(
            f"{rule.mechanic_id} declares {rule.family.value} and no "
            f"interpreter serves the {lane.value} lane, so its numbers are "
            "withheld rather than compiled"
        )
    return fields(rule, ctx, lane)


@dataclass(frozen=True, slots=True)
class UnservedLane:
    """Why a declared ``(family, lane)`` has no interpreter, and by what route.

    Counter 4 is the *size* of the gap between the lane table and the
    registry; this is the gap's content.  Every entry is a lane that some
    declaration reaches and no interpreter serves, with the engine's own
    reason for it — so the absence is evidence a reader can check against the
    code rather than a number nobody can read back.

    A row is not a permit to price zero.  It is a claim that the lane's
    number arrives by another route, and the row says which route; the
    registrations gate below refuses any unserved lane that has neither a row
    here nor a per-rule ``ReceiptOnly`` on the compiled lane, and equally
    refuses a row here that no declaration reaches (D-92 — a set pinned at a
    state the tree has left is born stale).

    ``via`` is that route as a **declaration** rather than as a sentence.
    ``reason`` says in prose which interpreter the number comes from instead;
    ``via`` names the same lanes as data, and the gate below checks them
    against the registry.  Without it the route is unverified prose beside a
    verified count — coverage claimed and nothing checking the claim against
    code, which is failure four of the incident this campaign exists to end.

    **What a row does not carry is when it retires.**  Both fields above are
    facts about this tree, checkable here at import.  The stage that retires a
    row is neither: it is campaign bookkeeping, ruled and re-dated by
    amendment (K, 2026-08-15), read by no runtime caller.  It lives once, in
    ``docs/receipts/campaign-stages.json``, where exactly one stage record may
    declare itself the ``creditor_of`` a lane's debt; ``behavior_frontier``
    resolves each row's stage from that claim.  Declared here as well it was
    declared twice — a ruling had to edit a runtime module to land, and the
    copies could disagree with only a gate clause between them.
    """

    reason: str
    via: tuple[EngineLane, ...]


# The four routes a declared family's number reaches an engine by when that
# engine has no interpreter of its own, written once and shared by the rows
# that stand on them.  One sentence per route rather than per pair: thirty
# copies of one fact is how sixteen conservatism notes became indistinguishable
# from sixteen representability facts.
_PACKET_FED = (
    "both walks consume this family as the pair engine's timed rows — "
    "participant_timeline._pair_run_fight prices the pair and "
    "survival/compile.py stages the resulting packets — so the declaration "
    "reaches them through the pair interpreter rather than through one of "
    "its own"
)
# For a family whose receipt-walk half reads the declaration itself: the
# compiled lane alone stages the pair engine's packets, so a row saying "both
# walks" would contradict the tree it excuses.
_COMPILED_PACKET_FED = (
    "the compiled score walk consumes this family as the pair engine's timed "
    "rows — participant_timeline._pair_run_fight prices the pair and "
    "survival/compile.py stages the resulting packets — so the declaration "
    "reaches it through the pair interpreter rather than through one of its "
    "own; the receipt walk reads the declaration itself since this family "
    "retired"
)
# For a family RECLASSIFIED pair-only: the compiled lane stages the pair
# engine's packets, and the receipt walk is owed nothing at all, not because
# it reads the declaration itself but because the family authors no pair row
# and its numbers never leave the holder's own.
_COMPILED_PACKET_FED_PAIR_ONLY = (
    "the compiled score walk consumes this family as the pair engine's timed "
    "rows — participant_timeline._pair_run_fight prices the pair and "
    "survival/compile.py stages the resulting packets — so the declaration "
    "reaches it through the pair interpreter rather than through one of its "
    "own; the receipt walk is owed nothing by this family, whose declarations "
    "author no pair row and fold only into the holder's own"
)
_RESOLVER_FED = (
    "the walks stage what the defence resolver already built, so the "
    "declaration reaches them through the resolver interpreter; a walk-lane "
    "interpreter here would be a second producer of one number"
)
# For a family that declares no receipt-walk lane: the compiled lane stages
# what the resolver built, and the receipt walk is not a lane this family
# declares at all.  It cannot keep the shared sentence, which opens "the
# walks" and would describe a lane the table does not hold.
_COMPILED_RESOLVER_FED = (
    "the compiled score walk stages what the defence resolver already built, "
    "so the declaration reaches it through the resolver interpreter; a "
    "walk-lane interpreter here would be a second producer of one number, "
    "which is why the receipt walk no longer declares a lane for this family "
    "at all"
)
_TEMPLATE_FED = (
    "the compiled kernel stages support templates from the packets "
    "item_support_effects emits, not from the declaration; the packet kinds "
    "it cannot stage are refused per rule by compilability_for"
)
_PROFILE_FED = (
    "the two reactive shields reach the compiled ledger as the resolved "
    "defensive state the resolver granted, and the strike-back reaches it as "
    "the profile participant_timeline compiled through this family's walk "
    "interpreter — survival/compile.py prices it against the striker's own "
    "resistances — so neither half arrives as the rule"
)
_COMPILED_PAIR_PRICED_OR_PACKET_FED = (
    "the compiled score walk reads no amp declaration: a holder-side amp "
    "reaches it already priced inside the pair engine's damage rows, and a "
    "cross-participant one as the damage_modifier packet item_support_effects "
    "emits, which survival/transitions stages as an ActionKind.DAMAGE_MODIFIER"
    " — two routes, neither of them the rule"
)

# One row per unserved pair a declaration reaches — see UnservedLane.
# ``delta_amp``'s compiled lane is all that stands between that lane and an
# unreceipted zero, since every amp rule is compilable.  Its receipt-walk twin
# has no row: the walk reads the amp declaration through ``delta_amp``'s own
# registration.
_AMP_LANE = UnservedLane(_COMPILED_PAIR_PRICED_OR_PACKET_FED, (EngineLane.PAIR_ENGINE,))

UNSERVED_LANE_RECEIPTS: Mapping[tuple[RuleFamily, EngineLane], UnservedLane] = {
    # The crit profile declares no receipt-walk lane: the family is PAIR_ONLY
    # on its measured emptiness.  It cannot keep the shared reason either,
    # whose sentence opens "both walks consume this family" when only one
    # asks.
    (RuleFamily.CRIT_PROFILE, EngineLane.COMPILED_SCORE_WALK): UnservedLane(
        _COMPILED_PACKET_FED_PAIR_ONLY, (EngineLane.PAIR_ENGINE,)
    ),
    # Eight families have no receipt-walk row: the walk reads each item
    # active, each cast-triggered proc, each charged strike, every routing
    # rule, every on-hit strike, every periodic cadence, every stacking
    # resistance shred and every spellblade from its own declaration, through
    # each family's own receipt-walk registration — so only the compiled lane
    # defers for them, and it says so in its own words rather than inheriting
    # a sentence about both walks.  Two of the eight hand the
    # walk no price and for two different reasons.  ``damage_routing``'s
    # delivery is the rider and kernel-state paths umbrella Amendment P names,
    # already in the tree.  ``resistance_shred``'s is the cross-participant
    # packet its owners' ``SPLIT`` partners already emit: a shred is not
    # damage — it moves the target's resistance before penetration — so what
    # retires that row is the walk reading the family's own ramp instead of
    # the ally-packet declaration's second copy of it.
    **{
        (family, EngineLane.COMPILED_SCORE_WALK): UnservedLane(
            _COMPILED_PACKET_FED, (EngineLane.PAIR_ENGINE,)
        )
        for family in (
            RuleFamily.ACTIVE_CAST,
            RuleFamily.CAST_PROC,
            RuleFamily.CHARGED_STRIKE,
            RuleFamily.DAMAGE_ROUTING,
            RuleFamily.ON_HIT_STRIKE,
            RuleFamily.PERIODIC,
            RuleFamily.RESISTANCE_SHRED,
            RuleFamily.SPELLBLADE,
        )
    },
    # ``secondary_target`` has no row on either lane.  It declares no
    # compiled-score-walk lane, because a second target only exists where
    # there is a roster to hit and the compiled kernel prices one pair.  A
    # family with no unserved lane is what the end of this table looks like.
    #
    # Sustain's receipt half is served: the walk reads its two walk-paid
    # shapes through the registered walk interpreter, so only the compiled
    # lane has a row, packet-fed like the strikes.
    (RuleFamily.SUSTAIN, EngineLane.COMPILED_SCORE_WALK): UnservedLane(
        _PACKET_FED, (EngineLane.PAIR_ENGINE,)
    ),
    # The three resolver-fed families declare no receipt-walk lane, because
    # what the receipt walk consumes for them it consumes from the lane they
    # do declare, so a second lane asking for the same number is the second
    # producer criterion 8 forbids.  Only the compiled lane defers for them,
    # and it says so in a sentence of its own.
    **{
        (family, EngineLane.COMPILED_SCORE_WALK): UnservedLane(
            reason=_COMPILED_RESOLVER_FED,
            via=(EngineLane.DEFENSE_RESOLVER,),
        )
        for family in (
            RuleFamily.OPENING_DEFENSE,
            RuleFamily.THRESHOLD_DEFENSE,
            RuleFamily.COMBAT_STATE,
        )
    },
    # Reactive's receipt half is served: the coupled timeline compiles the
    # strike-back declaration at its own boundary through the registered walk
    # interpreter, so only the compiled lane has a row, and
    # its route is that boundary rather than the resolver's.  Both halves are
    # named, because the reason names both.
    (RuleFamily.REACTIVE, EngineLane.COMPILED_SCORE_WALK): UnservedLane(
        reason=_PROFILE_FED,
        via=(EngineLane.DEFENSE_RESOLVER, EngineLane.RECEIPT_WALK),
    ),
    (RuleFamily.ALLY_PACKET, EngineLane.COMPILED_SCORE_WALK): UnservedLane(
        reason=_TEMPLATE_FED,
        via=(EngineLane.RECEIPT_WALK,),
    ),
    (RuleFamily.DELTA_AMP, EngineLane.COMPILED_SCORE_WALK): _AMP_LANE,
}


# The four families the defensive resolver builds.  Derived from the lane
# table rather than listed, so a family that stopped owing the resolver an
# answer would leave this set on the same commit.
DEFENSE_FAMILIES: frozenset[RuleFamily] = frozenset(
    family
    for family, lanes in _FAMILY_LANES.items()
    if EngineLane.DEFENSE_RESOLVER in lanes
)


def resolve_defense(rule: BehaviorRule, subject: DefenseSubject) -> DefenseOutcome:
    """One declared defence, resolved by the function registered for it.

    The registry *is* the dispatch: deleting a family's resolver stops every
    defence of that family with this error rather than letting the resolver
    quietly grant nothing.
    """
    resolver = RESOLVERS.get(rule.family)
    if resolver is None:
        raise InterpreterRegistryError(
            f"{rule.mechanic_id} declares {rule.family.value} and no "
            "interpreter serves the defense_resolver lane, so its defence is "
            "withheld rather than resolved"
        )
    return resolver(rule, subject)


def lanes_for(family: RuleFamily) -> frozenset[EngineLane]:
    """The lanes that owe *family* an interpreter."""
    lanes = _FAMILY_LANES.get(family)
    if lanes is None:
        raise InterpreterRegistryError(
            f"{family.value} declares no lanes; every family says which engines "
            "have to answer for it"
        )
    return lanes


def declared_pairs() -> frozenset[tuple[RuleFamily, EngineLane]]:
    """Every (family, lane) an interpreter is owed for."""
    return frozenset(
        (family, lane) for family in RuleFamily for lane in lanes_for(family)
    )


def uninterpreted_pairs() -> tuple[tuple[RuleFamily, EngineLane], ...]:
    """Counter 4's population: declared pairs with no registered interpreter."""
    return tuple(
        sorted(
            (pair for pair in declared_pairs() if pair not in INTERPRETERS),
            key=lambda pair: (pair[0].value, pair[1].value),
        )
    )


def compilability_for(owner: str, scope: ReceiptScope) -> Compilability:
    """One owner's answer for one of the kernel's refusals, folded.

    ``ReceiptOnly`` wins and its reasons concatenate in declaration order;
    ``Compilable`` only when every rule is.  An owner the registries know but
    no rule declares is **not** compilable under any scope: its behaviour is
    still engine code, so claiming the kernel can represent it would be a
    promise made by an absence.  An owner no registry knows has nothing to
    represent and is compilable.

    ``scope`` is required rather than defaulted, and that is the whole point
    of the parameter.  The kernel refuses three unrelated things
    (:class:`~..item_behavior.ReceiptScope`), and a fold over all three
    answers a question no gate asks: the build-level gate wants the owners
    whose *state transitions* it cannot stage, and reading it the amp holders
    as well would fall a build back for a reason that gate does not own.  A
    caller that wants the union asks for each scope and says so.
    """
    rules = behavior_rules(owner)
    if not rules:
        if registry_entries(owner):
            return ReceiptOnly(
                f"{owner}: the registry declares behaviour that no BehaviorRule "
                "models yet, so the compiled kernel has nothing to represent it "
                "with (Phase 3 migration frontier)",
                scope=scope,
            )
        return Compilable()
    reasons = [
        rule.compilability.reason
        for rule in rules
        if isinstance(rule.compilability, ReceiptOnly)
        and rule.compilability.scope is scope
    ]
    if reasons:
        return ReceiptOnly("; ".join(reasons), scope=scope)
    return Compilable()


def _threshold_regeneration_thresholds(
    names: Sequence[str],
) -> dict[str, float]:
    """Each declared threshold regeneration this build brings, by owner.

    The one *conditional* answer the build-level gate needs, because
    ``Compilability`` is per rule: an inactive holder is numerically identical
    in both walks and must not fall back.  An unreadable declaration raises.
    """
    return {
        slot.owner: slot.value("bonus_health_threshold")
        for slot in declared_stat_derivations(
            sorted(frozenset(names)), ThresholdRegenRule
        )
    }


def uncompilable_item_receipt(
    items: Iterable[Mapping[str, Any]],
    *,
    loadout_stats: Mapping[str, float] | None = None,
    threshold_ticks_compiled: bool = False,
) -> str | None:
    """Return a named receipt when a build cannot ride the compiled walk.

    :func:`compilability_for` asked of a whole loadout, in scope
    ``SURVIVAL_LEDGER_TRANSITION``: this gate asks whether the score ledger
    can stage the state transitions a build's items author, never whether an
    amp is representable.  It lives here rather than in ``survival/`` because
    the answer is a declaration and the dependency runs
    ``interpreters -> survival`` and never back.

    ``loadout_stats`` is the actor's resolved stats, required for a declared
    threshold regeneration so the check mirrors the receipt walk's own gate;
    ``None`` fails closed.  ``threshold_ticks_compiled`` is the
    search-invariant caller's claim that it authors the holder's ticks itself,
    so an active holder stops being a reason to fall back.

    Items are walked in build order and the first refusal wins, so the
    published receipt string is one build's one answer.
    """
    names = [str(item.get("name", "")) for item in items]
    conditional = _threshold_regeneration_thresholds(names)
    for name in names:
        if name in conditional:
            threshold = conditional[name]
            if threshold_ticks_compiled:
                continue
            if loadout_stats is None:
                return f"item_mechanic={name}"
            if float(loadout_stats.get("bonus_health", 0.0) or 0.0) >= threshold:
                return f"item_mechanic={name}"
            continue
        if isinstance(
            compilability_for(name, ReceiptScope.SURVIVAL_LEDGER_TRANSITION),
            ReceiptOnly,
        ):
            return f"item_mechanic={name}"
    return None


class SurvivalLedgerContribution(Enum):
    """How a declaration puts health back into its own holder's ledger.

    Three shapes, one per family that carries the mechanic as an *optional
    component* of a rule whose main subject is something else: a proc that
    also shields, a routing rule that repays what it deferred, and a forced
    strike that also heals.  None of the three is a defence family, which is
    why "does this candidate's defensive effect sit inside the effective
    health the ordered event walk produced" could not be read off a family and
    was answered by a hand-written table of item names instead.

    The enum is closed because the question is closed.  A fourth shape is a
    declaration somebody adds here, in the same commit as the payload field it
    reads — which is the difference between a derivation and a list of names
    that goes on saying what it said after the code underneath it moves.
    """

    SELF_SHIELD = "self_shield"
    DEFERRED_DAMAGE = "deferred_damage"
    STRIKE_HEAL = "strike_heal"


_LEDGER_CONTRIBUTION_NOTES: Mapping[SurvivalLedgerContribution, str] = {
    SurvivalLedgerContribution.SELF_SHIELD: (
        "{mechanic} declares a self shield on its proc; the ordered event walk "
        "stamps the shield, with its sourced amount and its declared expiry, "
        "into the holder's survival ledger."
    ),
    SurvivalLedgerContribution.DEFERRED_DAMAGE: (
        "{mechanic} declares post-mitigation damage stored and repaid as "
        "declared ticks; the ledger carries the deferral and its recovery "
        "rather than reducing the hit, so effective health counts both."
    ),
    SurvivalLedgerContribution.STRIKE_HEAL: (
        "{mechanic} declares a heal on its forced strike; the ordered event "
        "walk stamps the heal, and any declared temporary health it overflows "
        "into, onto the holder's survival ledger."
    ),
}


@dataclass(frozen=True, slots=True)
class SurvivalLedgerEntry:
    """One declared contribution to its holder's own survival ledger."""

    owner: str
    mechanic_id: str
    contribution: SurvivalLedgerContribution

    @property
    def note(self) -> str:
        """The published sentence, keyed by shape and filled by declaration."""
        return _LEDGER_CONTRIBUTION_NOTES[self.contribution].format(
            mechanic=self.mechanic_id
        )


def survival_ledger_contribution(
    rule: BehaviorRule,
) -> SurvivalLedgerContribution | None:
    """Which ledger shape *rule* declares, or ``None`` for a rule that declares none.

    Read from the payload's own declared-absence idiom rather than from the
    family: ``self_shield`` and ``heal`` are ``None`` on the procs and forced
    strikes that do not pay one, and a routing deferral is the whole rule.  A
    forced-strike heal counts only when the rule's subject is its holder — the
    ledger this answers about is the holder's.
    """
    payload = rule.payload
    if isinstance(payload, CooldownProcRule) and payload.self_shield is not None:
        return SurvivalLedgerContribution.SELF_SHIELD
    if isinstance(payload, DamageDeferralRule):
        return SurvivalLedgerContribution.DEFERRED_DAMAGE
    if (
        isinstance(payload, ForcedCritRule)
        and payload.heal is not None
        and payload.subject is Subject.HOLDER
    ):
        return SurvivalLedgerContribution.STRIKE_HEAL
    return None


def survival_ledger_entries(owner: str) -> tuple[SurvivalLedgerEntry, ...]:
    """Every declared contribution *owner* makes to its holder's ledger."""
    return tuple(
        SurvivalLedgerEntry(owner, rule.mechanic_id, contribution)
        for rule in behavior_rules(owner)
        if (contribution := survival_ledger_contribution(rule)) is not None
    )


def survival_ledger_note(owner: str) -> str | None:
    """*owner*'s certification sentence, or ``None`` when it declares none.

    ``None`` tells a caller to publish "no special defensive effect".
    """
    entries = survival_ledger_entries(owner)
    if not entries:
        return None
    return " ".join(entry.note for entry in entries)


def survival_ledger_certifications() -> Mapping[str, str]:
    """Every owner whose declaration is inside the effective health BIS ranks.

    Asked of the declarations rather than asserted beside them, so an item
    that stops declaring its shield stops being certified on that commit.
    """
    return {
        owner: note
        for owner in sorted(rule_owners())
        if (note := survival_ledger_note(owner)) is not None
    }


@dataclass(frozen=True, slots=True)
class ReachabilityReport:
    """D-51's two directions as data.

    ``unreached_declarations`` are rules whose (family, lane) no interpreter
    serves; ``orphan_branches`` are registered interpreters no declaration
    reaches.  Empty tuples are the pass condition, and both halves are real:
    one branch exists today that no champion reaches, and one packet spelling
    would orphan its enum if it changed.
    """

    unreached_declarations: tuple[str, ...]
    orphan_branches: tuple[str, ...]


def reachability_report(owners: frozenset[str] | None = None) -> ReachabilityReport:
    """Walk both directions between declarations and interpreters."""
    subjects = rule_owners() if owners is None else owners
    unreached: list[str] = []
    reached: set[tuple[RuleFamily, EngineLane]] = set()
    for owner in sorted(subjects):
        for rule in behavior_rules(owner):
            for lane in lanes_for(rule.family):
                pair = (rule.family, lane)
                if pair in INTERPRETERS:
                    reached.add(pair)
                else:
                    unreached.append(
                        f"{rule.mechanic_id} declares {rule.family.value} and no "
                        f"interpreter serves lane {lane.value}"
                    )
    orphans = [
        f"{family.value}/{lane.value} is registered and no declaration reaches it"
        for family, lane in sorted(
            INTERPRETERS, key=lambda pair: (pair[0].value, pair[1].value)
        )
        if (family, lane) not in reached
    ]
    return ReachabilityReport(
        unreached_declarations=tuple(unreached), orphan_branches=tuple(orphans)
    )


def _validate_declared_lanes() -> tuple[str, ...]:
    """No registration sits on a lane its family never declared."""
    return tuple(
        f"{family.value} declares no {lane.value} lane, so an interpreter "
        "registered there can never be reached"
        for family, lane in sorted(
            INTERPRETERS, key=lambda pair: (pair[0].value, pair[1].value)
        )
        if lane not in lanes_for(family)
    )


def _validate_authority_agreement(owners: frozenset[str]) -> tuple[str, ...]:
    """A rule's subject may not contradict its mechanic's declared authority.

    A roster-scoped subject on a ``PAIR_ONLY`` mechanic is the incident's own
    shape: the engine that owns the number cannot see the input the rule
    reads.  A rule with a roster-scoped subject and no capability at all is
    the same failure with the declaration missing entirely.
    """
    failures: list[str] = []
    for owner in sorted(owners):
        for rule in behavior_rules(owner):
            subject = getattr(rule.payload, "subject", None)
            if subject is None:
                continue
            allowed = SUBJECT_AUTHORITY[subject]
            capability = CAPABILITIES.get(rule.mechanic_id)
            if capability is None:
                if allowed != frozenset(Authority):
                    failures.append(
                        f"{rule.mechanic_id} acts on {subject.value} but declares "
                        "no MechanicCapability, so no engine has claimed its "
                        "roster inputs"
                    )
                continue
            if capability.authority not in allowed:
                failures.append(
                    f"{rule.mechanic_id} acts on {subject.value} under authority "
                    f"{capability.authority.value}, which cannot see it"
                )
    return tuple(failures)


def _validate_unserved_lanes(owners: frozenset[str]) -> tuple[str, ...]:
    """Every declared lane is served, receipted per rule, or dated — or a stop.

    This is the totality half of the gate, and it is the half that decides
    whether counter 4 is a measurement or an alibi.  A declaration whose lane
    has no interpreter is priced by nobody; the only honest states are

    * the compiled lane, refused by that rule's own ``ReceiptOnly`` — the
      per-rule form, which is what every ``delta_amp`` carries (D-101); or
    * a dated row in :data:`UNSERVED_LANE_RECEIPTS` naming the route the
      number arrives by instead.

    Anything else raises rather than reaching a payload as a zero.  The
    reverse direction is checked with it: a row no declaration reaches is
    stale and fails, so the table cannot become the graveyard that a
    hand-maintained exception list turns into (D-92).
    """
    failures: list[str] = []
    reached: set[tuple[RuleFamily, EngineLane]] = set()
    for owner in sorted(owners):
        for rule in behavior_rules(owner):
            for lane in lanes_for(rule.family):
                pair = (rule.family, lane)
                if pair in INTERPRETERS:
                    continue
                if lane is EngineLane.COMPILED_SCORE_WALK and isinstance(
                    rule.compilability, ReceiptOnly
                ):
                    continue
                if pair in UNSERVED_LANE_RECEIPTS:
                    reached.add(pair)
                    continue
                failures.append(
                    f"{rule.mechanic_id} declares {rule.family.value} and no "
                    f"interpreter serves lane {lane.value}; neither the rule's "
                    "own compilability nor UNSERVED_LANE_RECEIPTS names the "
                    "gap, so its contribution would be an unreceipted zero"
                )
    failures.extend(
        f"UNSERVED_LANE_RECEIPTS names {family.value}/{lane.value}, which no "
        "declaration reaches — a dated gap for a lane nobody asks about is a "
        "receipt for nothing"
        for family, lane in sorted(
            set(UNSERVED_LANE_RECEIPTS) - reached,
            key=lambda pair: (pair[0].value, pair[1].value),
        )
    )
    return tuple(failures)


def _validate_unserved_routes() -> tuple[str, ...]:
    """Every dated row's route is a lane the registry actually serves.

    A row says the number arrives by another of its family's lanes.  That is
    the whole excuse for the gap, and until it is checked it is a sentence: a
    route naming a lane no interpreter serves reads exactly like a route
    naming one that does, which is how the pair-engine half of Command came to
    be documented and absent.  Three clauses, structural over the table
    itself, so a row is refused whether or not a declaration reaches it:

    * a row with no route claims nothing and excuses nothing;
    * a route lane the family does not declare is a lane that owes it no
      answer, so it cannot be where the answer comes from;
    * a route lane no interpreter serves is the failure this exists to catch,
      and a row routed to its own lane is that failure written in a circle.
    """
    failures: list[str] = []
    for (family, lane), row in sorted(
        UNSERVED_LANE_RECEIPTS.items(),
        key=lambda item: (item[0][0].value, item[0][1].value),
    ):
        pair = f"{family.value}/{lane.value}"
        if not row.via:
            failures.append(
                f"UNSERVED_LANE_RECEIPTS[{pair}] names no route, so its reason "
                "is a sentence and the gap is excused by nothing"
            )
            continue
        declared = lanes_for(family)
        for route in row.via:
            if route is lane:
                failures.append(
                    f"UNSERVED_LANE_RECEIPTS[{pair}] routes the lane to itself"
                )
            elif route not in declared:
                failures.append(
                    f"UNSERVED_LANE_RECEIPTS[{pair}] routes to {route.value}, "
                    f"which {family.value} does not declare"
                )
            elif (family, route) not in INTERPRETERS:
                failures.append(
                    f"UNSERVED_LANE_RECEIPTS[{pair}] routes to {route.value}, "
                    "which no interpreter serves — the route is a claim about "
                    "a number nobody produces"
                )
    return tuple(failures)


def _validate_resolvers() -> tuple[str, ...]:
    """The two defence tables name the same families, in both directions."""
    failures = [
        f"{family.value} declares the defense_resolver lane and no resolver "
        "answers for it, so its defence would be withheld at every build"
        for family in sorted(
            DEFENSE_FAMILIES - frozenset(RESOLVERS), key=lambda f: f.value
        )
    ]
    failures.extend(
        f"RESOLVERS answers for {family.value}, which declares no "
        "defense_resolver lane, so nothing ever calls it"
        for family in sorted(
            frozenset(RESOLVERS) - DEFENSE_FAMILIES, key=lambda f: f.value
        )
    )
    return tuple(failures)


def validate_registrations() -> None:
    """Totality, authority agreement and no orphan branch — or raise."""
    owners = rule_owners()
    failures = list(_validate_declared_lanes())
    failures.extend(_validate_resolvers())
    failures.extend(_validate_unserved_lanes(owners))
    failures.extend(_validate_unserved_routes())
    failures.extend(_validate_authority_agreement(owners))
    failures.extend(reachability_report(owners).orphan_branches)
    if failures:
        raise InterpreterRegistryError("; ".join(failures))


validate_registrations()


__all__ = [
    "DEFENSE_FAMILIES",
    "INTERPRETERS",
    "RESOLVERS",
    "UNSERVED_LANE_RECEIPTS",
    "FieldsFn",
    "InterpreterRegistryError",
    "ReachabilityReport",
    "ResolveFn",
    "UnservedLane",
    "compilability_for",
    "compile_rule",
    "declared_pairs",
    "lanes_for",
    "reachability_report",
    "resolve_defense",
    "uncompilable_item_receipt",
    "uninterpreted_pairs",
    "validate_registrations",
]
