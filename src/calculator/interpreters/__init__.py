"""One interpreter per family per engine lane, and the gates over that map.

A declared behaviour is only worth something if some engine runs it.  This
package is where that is decided and, more importantly, where *not* deciding
it becomes visible: :func:`compilability_for` refuses to call an owner
compilable, for the refusal it is asked about, while any of its rules is
receipt-only in that scope, and
:func:`reachability_report` names both a declaration no interpreter reaches
and an interpreter branch no declaration reaches (D-51).  Both directions
have live motivating cases, which is why neither is dropped as theoretical.

**Interpreters run at build time.**  A walk-lane interpreter emits
``KernelField``s — value-typed fields the kernel already understands — rather
than being called from inside the walk, so the dependency stays one-way:
``interpreters/`` may read ``survival/``'s vocabulary and nothing under
``survival/`` imports this package.  A source assertion in the test front
door pins that, because an interpreter that touched ``SurvivalAction`` and
was called from ``survival/transitions.py`` would close exactly the cycle the
leaf-ness of ``item_behavior`` does not cover.

There is one interpreter module per family and never a single dispatch file:
an eighteen-branch god module cannot carry eighteen test front doors, and the
derived front-door check (D-95) is what would notice.
"""

# This module's length is one row per ``(family, lane)`` and one dated receipt
# per gap, and both sets are the campaign's own vocabulary: splitting the
# registry from the reasons would put the count in one file and the excuse in
# another, which is exactly the prose-outruns-code shape counter 4 exists to
# measure.  Same trade, same idiom, as ``trigger_stream``'s own table.
# pylint: disable=too-many-lines

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

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


class Interpreter(Protocol):  # pylint: disable=too-few-public-methods
    """What every family's interpreter module exposes.

    ``compile`` is build-time only and returns value-typed fields; it is
    handed a :class:`~..item_behavior.BuildContext`, which carries a level, an
    owner and a data version and deliberately carries no walk state.
    """

    FAMILY: RuleFamily
    LANES: frozenset[EngineLane]

    def compile(self, rule: BehaviorRule, ctx: BuildContext) -> tuple[KernelField, ...]:
        """Emit this rule's kernel fields for the lanes this interpreter serves."""


# Which lanes must be able to answer for each family, declared rather than
# inferred from what happens to be registered — otherwise "every family is
# interpreted" would be true of an empty registry.  Counter 4 is the size of
# the gap between this table and INTERPRETERS.
#
#   PAIR_ENGINE          the one-attacker damage model
#   RECEIPT_WALK         the coupled roster walk that serves receipts
#   COMPILED_SCORE_WALK  the compiled kernel the optimizer scores through
#   DEFENSE_RESOLVER     the defensive-effects build, before any walk
#   STAT_RESOLVER        the stat build, before any damage exists
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
    # PAIR_ONLY, so the pair engine is this family's authoritative home, no
    # second engine prices it, and the walk lane it used to declare was a
    # schedule category error rather than a debt.  The compiled score walk is
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


# The registry itself.  One entry per family per lane, filled by the slice
# that migrates it; every remaining gap is counted by the frontier's counter
# 4 rather than being an absence nobody measures.  ``delta_amp`` serves the
# pair engine only — H5 is SCOPED, but the compiled-kernel extension it scopes
# lands as its own stage after Phase 4's S7, so until that stage's flip no amp
# is compilable — and the coupled walk never reads an amp declaration at all,
# which is its row's reason below rather than a gap waiting on an interpreter.
INTERPRETERS: Mapping[tuple[RuleFamily, EngineLane], Interpreter] = {
    (
        RuleFamily.ACTIVE_CAST,
        EngineLane.PAIR_ENGINE,
    ): active_cast.PAIR_INTERPRETER,
    (
        RuleFamily.ACTIVE_CAST,
        EngineLane.RECEIPT_WALK,
    ): active_cast.WALK_INTERPRETER,
    (
        RuleFamily.ALLY_PACKET,
        EngineLane.RECEIPT_WALK,
    ): ally_packet.WALK_INTERPRETER,
    (RuleFamily.CAST_PROC, EngineLane.PAIR_ENGINE): cast_proc.PAIR_INTERPRETER,
    (RuleFamily.CAST_PROC, EngineLane.RECEIPT_WALK): cast_proc.WALK_INTERPRETER,
    (
        RuleFamily.COMBAT_STATE,
        EngineLane.DEFENSE_RESOLVER,
    ): combat_state.RESOLVER_INTERPRETER,
    (
        RuleFamily.CHARGED_STRIKE,
        EngineLane.PAIR_ENGINE,
    ): charged_strike.PAIR_INTERPRETER,
    (
        RuleFamily.CHARGED_STRIKE,
        EngineLane.RECEIPT_WALK,
    ): charged_strike.WALK_INTERPRETER,
    (
        RuleFamily.CRIT_PROFILE,
        EngineLane.PAIR_ENGINE,
    ): crit_profile.PAIR_INTERPRETER,
    (
        RuleFamily.DAMAGE_ROUTING,
        EngineLane.DEFENSE_RESOLVER,
    ): damage_routing.RESOLVER_INTERPRETER,
    (
        RuleFamily.DAMAGE_ROUTING,
        EngineLane.PAIR_ENGINE,
    ): damage_routing.PAIR_INTERPRETER,
    (
        RuleFamily.DAMAGE_ROUTING,
        EngineLane.RECEIPT_WALK,
    ): damage_routing.WALK_INTERPRETER,
    (RuleFamily.DELTA_AMP, EngineLane.PAIR_ENGINE): delta_amp.PAIR_INTERPRETER,
    (RuleFamily.DELTA_AMP, EngineLane.RECEIPT_WALK): delta_amp.WALK_INTERPRETER,
    (
        RuleFamily.STAT_DERIVATION,
        EngineLane.PAIR_ENGINE,
    ): stat_derivation.PAIR_INTERPRETER,
    (
        RuleFamily.STAT_DERIVATION,
        EngineLane.STAT_RESOLVER,
    ): stat_derivation.RESOLVER_INTERPRETER,
    (
        RuleFamily.ON_HIT_STRIKE,
        EngineLane.PAIR_ENGINE,
    ): on_hit_strike.PAIR_INTERPRETER,
    (
        RuleFamily.OPENING_DEFENSE,
        EngineLane.DEFENSE_RESOLVER,
    ): opening_defense.RESOLVER_INTERPRETER,
    (
        RuleFamily.PERIODIC,
        EngineLane.PAIR_ENGINE,
    ): periodic.PAIR_INTERPRETER,
    (
        RuleFamily.REACTIVE,
        EngineLane.DEFENSE_RESOLVER,
    ): reactive.RESOLVER_INTERPRETER,
    (RuleFamily.REACTIVE, EngineLane.RECEIPT_WALK): reactive.WALK_INTERPRETER,
    (
        RuleFamily.RESISTANCE_SHRED,
        EngineLane.PAIR_ENGINE,
    ): resistance_shred.PAIR_INTERPRETER,
    (
        RuleFamily.SECONDARY_TARGET,
        EngineLane.PAIR_ENGINE,
    ): secondary_target.PAIR_INTERPRETER,
    (
        RuleFamily.SPELLBLADE,
        EngineLane.PAIR_ENGINE,
    ): spellblade.PAIR_INTERPRETER,
    (
        RuleFamily.SUSTAIN,
        EngineLane.DEFENSE_RESOLVER,
    ): sustain.RESOLVER_INTERPRETER,
    (RuleFamily.SUSTAIN, EngineLane.PAIR_ENGINE): sustain.PAIR_INTERPRETER,
    (RuleFamily.SUSTAIN, EngineLane.RECEIPT_WALK): sustain.WALK_INTERPRETER,
    (
        RuleFamily.THRESHOLD_DEFENSE,
        EngineLane.DEFENSE_RESOLVER,
    ): threshold_defense.RESOLVER_INTERPRETER,
}


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
# What is left of ``_PACKET_FED`` once a family's receipt-walk half has
# retired: the compiled lane alone still stages the pair engine's packets, and
# a row that went on saying "both walks" would contradict the tree it excuses.
_COMPILED_PACKET_FED = (
    "the compiled score walk consumes this family as the pair engine's timed "
    "rows — participant_timeline._pair_run_fight prices the pair and "
    "survival/compile.py stages the resulting packets — so the declaration "
    "reaches it through the pair interpreter rather than through one of its "
    "own; the receipt walk reads the declaration itself since this family "
    "retired"
)
# What is left of ``_PACKET_FED`` once a family's receipt-walk half has been
# RECLASSIFIED rather than retired: the compiled lane still stages the pair
# engine's packets, and the receipt walk is owed nothing at all — not because
# it reads the declaration itself, which is the retired shape, but because the
# family authors no pair row and its numbers never leave the holder's own.
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
# What is left of ``_RESOLVER_FED`` once a family's receipt-walk lane has been
# CORRECTED away: the compiled lane still stages what the resolver built, and
# the receipt walk is not a lane this family declares at all.  It could not
# keep the shared sentence, which opens "the walks" and would go on describing
# a lane the table no longer holds — the same contradiction that took
# ``delta_amp``'s and ``crit_profile``'s.
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

# One row per unserved pair a declaration reaches, carrying no stage — see
# UnservedLane.  ``delta_amp``'s compiled lane is all that stands between that
# lane and an unreceipted zero since H5's stage made those rules compilable
# (D-101, D-92).  Its receipt-walk twin is gone — Amendment M, Ruling 1 rules
# this family first of the fourteen and its act to be the walk-side delivery
# of the holder's static amps, which ``DeltaAmpWalkInterpreter`` performs —
# and the shared reason went with it, since it opened "neither walk reads an
# amp declaration" and a row leaving that behind would contradict the tree.
_AMP_LANE = UnservedLane(_COMPILED_PAIR_PRICED_OR_PACKET_FED, (EngineLane.PAIR_ENGINE,))

UNSERVED_LANE_RECEIPTS: Mapping[tuple[RuleFamily, EngineLane], UnservedLane] = {
    **{
        (family, lane): UnservedLane(
            reason=_PACKET_FED,
            via=(EngineLane.PAIR_ENGINE,),
        )
        for family in (
            RuleFamily.ON_HIT_STRIKE,
            RuleFamily.SPELLBLADE,
            RuleFamily.PERIODIC,
            RuleFamily.RESISTANCE_SHRED,
        )
        for lane in (EngineLane.RECEIPT_WALK, EngineLane.COMPILED_SCORE_WALK)
    },
    # The crit profile's receipt-walk twin is gone and it did not retire: the
    # lane table above no longer declares that lane at all, because umbrella
    # Amendment O, Ruling 1 reclassified this family PAIR_ONLY on its measured
    # emptiness.  It could not keep the shared reason either, for the same
    # kind of contradiction that took delta_amp's: the sentence opens "both
    # walks consume this family", and one of them no longer asks.
    (RuleFamily.CRIT_PROFILE, EngineLane.COMPILED_SCORE_WALK): UnservedLane(
        _COMPILED_PACKET_FED_PAIR_ONLY, (EngineLane.PAIR_ENGINE,)
    ),
    # Four families' receipt-walk twins are gone — the walk reads each item
    # active, each cast-triggered proc, each charged strike and every routing
    # rule from its own declaration, through ``ActiveCastWalkInterpreter``,
    # ``CastProcWalkInterpreter``, ``ChargedStrikeWalkInterpreter`` and
    # ``DamageRoutingWalkInterpreter``, which is Amendment F's act in the lane
    # Amendment K rules — so only the compiled lane defers for them, and it
    # says so in its own words rather than inheriting a sentence about both
    # walks.  ``damage_routing`` is the one of the four whose interpreter
    # hands the walk no price: umbrella Amendment P names its delivery as the
    # rider and kernel-state paths already in the tree, so what retires the
    # row is the walk reading the declaration rather than the walk paying it.
    **{
        (family, EngineLane.COMPILED_SCORE_WALK): UnservedLane(
            _COMPILED_PACKET_FED, (EngineLane.PAIR_ENGINE,)
        )
        for family in (
            RuleFamily.ACTIVE_CAST,
            RuleFamily.CAST_PROC,
            RuleFamily.CHARGED_STRIKE,
            RuleFamily.DAMAGE_ROUTING,
        )
    },
    (RuleFamily.SECONDARY_TARGET, EngineLane.RECEIPT_WALK): UnservedLane(
        _PACKET_FED, (EngineLane.PAIR_ENGINE,)
    ),
    # Sustain's receipt half is no longer a gap — the walk reads its two
    # walk-paid shapes through the registered walk interpreter — so only the
    # compiled lane has a row, packet-fed like the strikes.
    (RuleFamily.SUSTAIN, EngineLane.COMPILED_SCORE_WALK): UnservedLane(
        _PACKET_FED, (EngineLane.PAIR_ENGINE,)
    ),
    # The three resolver-fed families' receipt-walk twins are gone and none of
    # them retired: the lane table above no longer declares that lane, because
    # umbrella Amendment Q corrected a declaration these families never owed —
    # what the receipt walk consumes for them, it consumes from the lane they
    # declare, so a second lane asking for the same number is the second
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
    # Reactive's receipt half is no longer a gap — the coupled timeline
    # compiles the strike-back declaration at its own boundary through the
    # registered walk interpreter — so only the compiled lane has a row, and
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
    """One declared defence, resolved by the interpreter registered for it.

    The registry *is* the dispatch: deleting a family's defensive
    interpreter stops every defence of that family with this error rather
    than letting the resolver quietly grant nothing, which is what makes
    "delete an interpreter and its items are withheld" a property of the
    code instead of a claim about it.
    """
    interpreter = INTERPRETERS.get((rule.family, EngineLane.DEFENSE_RESOLVER))
    if interpreter is None:
        raise InterpreterRegistryError(
            f"{rule.mechanic_id} declares {rule.family.value} and no "
            "interpreter serves the defense_resolver lane, so its defence is "
            "withheld rather than resolved"
        )
    return interpreter.resolve(rule, subject)


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
    """One owner's answer for one of the kernel's refusals, folded (D-43).

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
    whose *state transitions* it cannot stage, and reading it the amp
    holders as well would fall a build back for a reason that gate does not
    own.  A caller that genuinely wants the union asks for each scope and
    says so.

    This is the successor to the per-item hand set the compiled walk used to
    carry — a per-item question needs a per-item answer, which is why the fold
    lives here rather than being left to each caller.
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
) -> dict[str, float | None]:
    """Each declared threshold regeneration this build brings, by owner.

    The one *conditional* answer the build-level gate needs: a threshold
    regeneration's ticks are authored inside the event walk, but only once
    the holder's bonus health passes the declared threshold, so an inactive
    holder is numerically identical in both walks and must not fall back.
    Conditionality is not something ``Compilability`` can express — it is
    ``Compilable | ReceiptOnly``, per rule and not per build — so it lives
    here, keyed by the declared shape rather than by the one item that
    happens to carry it today.

    ``None`` for an owner that declares one whose number cannot be read: a
    threshold nobody can resolve is a reason to fall back, not a threshold of
    zero and not a crashed request.  Resolved per owner so one unreadable
    declaration cannot decide the answer for the rest of the build.
    """
    thresholds: dict[str, float | None] = {}
    for name in sorted(frozenset(names)):
        try:
            for slot in declared_stat_derivations([name], ThresholdRegenRule):
                thresholds[slot.owner] = slot.value("bonus_health_threshold")
        except (KeyError, TypeError, ValueError):
            thresholds[name] = None
    return thresholds


def uncompilable_item_receipt(
    items: Iterable[Mapping[str, Any]],
    *,
    loadout_stats: Mapping[str, float] | None = None,
    threshold_ticks_compiled: bool = False,
) -> str | None:
    """Return a named receipt when a build cannot ride the compiled walk.

    :func:`compilability_for` asked of a whole loadout, and the successor to
    the sixteen-item hand set ``survival/compile.py`` used to carry: those
    hand-written per-item notes are gone, and every one of them is now the fold
    over that owner's own rules in the scope the question is about —
    ``SURVIVAL_LEDGER_TRANSITION``, because what this gate asks is whether the
    score ledger can stage the state transitions a build's items author, never
    whether an amp is representable.  It lives here rather than in
    ``survival/`` because the answer is a declaration and the dependency runs
    ``interpreters -> survival`` and never back.

    ``loadout_stats`` is the actor's resolved stats, required for a declared
    threshold regeneration so the check mirrors the receipt walk's own gate;
    ``None`` fails closed.  ``threshold_ticks_compiled`` is the
    search-invariant caller's claim that it authors the holder's ticks itself
    (the roster scan; issue #169), so an active holder stops being a reason to
    fall back.

    Items are walked in build order and the first refusal wins, which is what
    keeps the published receipt string identical to the one the hand set
    produced for the same build.
    """
    names = [str(item.get("name", "")) for item in items]
    conditional = _threshold_regeneration_thresholds(names)
    for name in names:
        if name in conditional:
            threshold = conditional[name]
            if threshold_ticks_compiled:
                continue
            if loadout_stats is None or threshold is None:
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

    ``None`` is the honest answer for an item with no such declaration, and it
    is what tells a caller to publish "no special defensive effect" instead of
    a certification nothing backs.
    """
    entries = survival_ledger_entries(owner)
    if not entries:
        return None
    return " ".join(entry.note for entry in entries)


def survival_ledger_certifications() -> Mapping[str, str]:
    """Every owner whose declaration is inside the effective health BIS ranks.

    The successor to the hand-written certification table the BIS receipt used
    to carry: same question, asked of the declarations instead of asserted
    beside them, so an item that stops declaring its shield stops being
    certified on the same commit rather than on the day somebody re-reads the
    prose.
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


def _validate_registry_keys() -> tuple[str, ...]:
    """Every registration's key agrees with the interpreter's own declaration."""
    failures: list[str] = []
    for (family, lane), interpreter in INTERPRETERS.items():
        if getattr(interpreter, "FAMILY", None) is not family:
            failures.append(
                f"{family.value}/{lane.value} is registered under a family its "
                "interpreter does not claim"
            )
        if lane not in getattr(interpreter, "LANES", frozenset()):
            failures.append(
                f"{family.value}/{lane.value} is registered on a lane its "
                "interpreter does not serve"
            )
        if lane not in lanes_for(family):
            failures.append(
                f"{family.value} declares no {lane.value} lane, so an "
                "interpreter registered there can never be reached"
            )
    return tuple(failures)


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


def validate_registrations() -> None:
    """Totality, authority agreement and no orphan branch — or raise."""
    owners = rule_owners()
    failures = list(_validate_registry_keys())
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
    "UNSERVED_LANE_RECEIPTS",
    "UnservedLane",
    "Interpreter",
    "InterpreterRegistryError",
    "ReachabilityReport",
    "compilability_for",
    "declared_pairs",
    "uncompilable_item_receipt",
    "lanes_for",
    "reachability_report",
    "resolve_defense",
    "uninterpreted_pairs",
    "validate_registrations",
]
