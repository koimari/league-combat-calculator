"""Fail-closed coverage labels for item mechanics used by BIS search.

Raw item stats are always sourced by :mod:`stats`.  This module answers the
separate question the optimiser needs: is every outgoing-damage mechanic on
this item represented by the current fight model?

Two declarations sit beside the classifiers and nothing in ``src`` reads
them: ``COVERAGE_EVIDENCE``, the typed claim behind every answer this module
gives, and ``FRONTIER``, the claims that are not backed yet and the issues
that track them.  They live here rather than in a module of their own
because a claim is *about* the container two hundred lines above it, and a
reader checking whether the two agree should not have to hold two files
open — pylint's line ceiling is a proxy for "more than one responsibility",
and this is one.
"""

# pylint: disable=too-many-lines

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from .coverage_evidence import (
    Claim,
    ClaimLane,
    CoverageClaimError,
    EffectKey,
    Evidence,
    OwnerPolicy,
    OptionSchema,
    PacketSource,
    PairedSides,
    SourceRef,
    SubjectKind,
    Symbol,
    SymbolRole,
    TestRef,
    validate_claim_table,
)
from .data_fetcher import get_item_by_name
from .interpreters import INTERPRETERS, lanes_for
from .item_behavior import (
    DURABILITY_STATS,
    BehaviorRule,
    DefenseExclusivity,
    DefenseMechanic,
    EngineLane,
    PacketKind,
    RuleFamily,
    Subject,
    SustainStatRule,
    UtilityDimension,
)
from .item_behavior_catalog import (
    EVENT_CERTIFIED_MECHANICS,
    STAT_CHANNEL_TAGS,
    behavior_rules,
    declares_runtime_behaviour,
    registry_entries,
)
from .item_effects import ALLY_ITEM_EFFECTS, ITEM_INPUT_OPTIONS
from .item_outcomes import UTILITY_OUTCOMES

# The attacker lane's five answers.  This vocabulary is a **user-visible label
# set**, not only a payload key: the browser prints the status verbatim with
# underscores turned into spaces (``static/js/app.js:3423``), so a member
# renamed here is text a player reads.  3.8's rename of ``blocked`` to
# ``withheld`` moved 91 attacker-lane chips and 90 target-lane ones for exactly
# that reason.
ItemCoverageStatus = Literal[
    "modeled_effect",
    "modeled_state",
    "stats_only",
    "withheld",
    "review_pending",
]

# The two answers that are refusals rather than classifications.  ``withheld``
# is the campaign's spelling for "coverage refused to model it — a named
# receipt and no number" (D-23); ``review_pending`` is the same refusal for a
# record that is not a shop item at all.  Neither is optimizer- or
# calculation-eligible, and no third status is a refusal.
_REFUSAL_STATUSES: frozenset[str] = frozenset({"withheld", "review_pending"})

# The three that classify, and the whitelist both eligibility gates read.
#
# Positive, deliberately.  The flip that computed status from declarations also
# rewrote eligibility as ``status not in _REFUSAL_STATUSES``, which is the same
# answer for all five members and the *opposite* answer for a sixth: a status
# added tomorrow would arrive optimizer- and calculation-eligible without
# anyone ruling that it should be, which is a fail-open default inside the
# campaign that exists to remove them.  Naming the eligible statuses instead
# makes an unclassified answer ineligible until someone classifies it.  A test
# asserts these two sets partition ``ItemCoverageStatus`` exactly, so "no third
# status is a refusal" and "no sixth status is silently eligible" cannot drift
# apart.
_ELIGIBLE_STATUSES: frozenset[str] = frozenset(
    {"modeled_effect", "modeled_state", "stats_only"}
)

# The target lane's own vocabulary, and its own positive whitelist.  Its three
# classifications are ``modeled``, ``modeled_event_certified`` — a defence the
# ladder proved the walk certifies event by event — and ``not_target_relevant``;
# its refusals are the attacker lane's two, passed through.  Same ruling, same
# reason: the durability question must not answer "eligible" for a status
# nobody has classified.  No ``Literal`` closes this vocabulary, so a test
# asserts the whitelist covers every status the ladder produces over the whole
# cache — which is how the certified members were caught missing here.
_TARGET_ELIGIBLE_STATUSES: frozenset[str] = frozenset(
    {"modeled", "modeled_event_certified", "not_target_relevant"}
)

# Families whose whole subject is the holder surviving rather than the holder
# dealing damage.  An item declaring nothing but these changes durability, and
# saying so on the attacker lane is the honest answer rather than a modelled
# claim about outgoing TDD.
_DEFENCE_FAMILIES: frozenset[RuleFamily] = frozenset(
    {
        RuleFamily.OPENING_DEFENSE,
        RuleFamily.THRESHOLD_DEFENSE,
        RuleFamily.COMBAT_STATE,
        RuleFamily.REACTIVE,
    }
)

# Families whose numbers come out of a progression or cross-participant state
# the shared ledger schedules rather than out of the pair engine's own
# rotation — which is exactly what ``modeled_state`` has always meant.
_STATE_FAMILIES: frozenset[RuleFamily] = frozenset(
    {RuleFamily.ALLY_PACKET, RuleFamily.STAT_DERIVATION}
)

# The lanes each public question needs answered.  ``needed`` is a real
# argument and not decoration: a family with no interpreter on a lane a caller
# depends on is the whole of ``withheld``, and a caller that never runs the
# compiled score walk must not be told its items are withheld because that
# lane has no interpreter yet.
#
# The three constants are three different questions, and they are meant to be:
#
# * ``ATTACKER_LANES`` — "can the pair engine price this item's outgoing
#   damage?"  It is what the shop and boots payloads publish, because the
#   browser asks what an item *is*, not what one search would do with it.
# * ``SCORING_LANES`` — "can BIS rank a build holding it?"  Ranking runs the
#   defence resolver too, so eligibility is the stricter question and the
#   refusals it produces are the ones that exclude a candidate.
# * ``TARGET_LANES`` — "can the passive-target model price what this item does
#   to the actor wearing it?"  That is the defence resolver's lane alone: a
#   target neither attacks nor casts in this model.
#
# The consequence is stated rather than left to be discovered: the day a
# family loses its defence-resolver interpreter, an item reads ``modeled_*``
# in the shop payload and is ``withheld`` from the optimizer in the same
# request.  That is the honest pair of answers to two different questions —
# the shop is not claiming the optimizer will score it — and it is latent
# today because ``unserved_lanes`` is empty for every cached item on every
# lane (asserted, not assumed).
ATTACKER_LANES: frozenset[EngineLane] = frozenset({EngineLane.PAIR_ENGINE})
SCORING_LANES: frozenset[EngineLane] = ATTACKER_LANES | frozenset(
    {EngineLane.DEFENSE_RESOLVER}
)
TARGET_LANES: frozenset[EngineLane] = frozenset({EngineLane.DEFENSE_RESOLVER})


@dataclass(frozen=True, slots=True)
class ItemCoverage:
    """One item's coverage answer, and the lanes it was answered for.

    A record rather than a dict because ``needed`` is part of the answer: the
    same item is modelled for a caller that prices only the pair engine and
    withheld for one that also needs a lane no interpreter serves, and a
    payload that did not carry the question could not be read back.

    ``as_payload`` is the only producer of the public shape, so the two
    serializing call sites in ``app.py`` cannot drift from the one the
    optimizer and the classification receipt read.
    """

    name: str
    status: ItemCoverageStatus
    reason: str
    outcome_dimensions: tuple[UtilityDimension, ...]
    review_issue_refs: tuple[int, ...]
    needed: frozenset[EngineLane]

    # The two gates below are two questions with one answer today, and that is
    # worth saying out loud because they used to have two.  Before the flip,
    # ``calculation_eligible`` carried an extra escape term — a named set of
    # blocked items an explicit request was still allowed to compute — while
    # ``optimizer_eligible`` never had one.  That set was empty, so deleting it
    # moved no answer, and the two collapsed onto the same expression.  They
    # stay two properties rather than one alias: the day BIS candidate
    # generation and an explicitly requested build should diverge again, the
    # divergence belongs here, in two expressions, and not in a caller.  A test
    # pins that they agree for every cached item today.

    @property
    def optimizer_eligible(self) -> bool:
        """Whether BIS search may generate candidates holding this item."""
        return self.status in _ELIGIBLE_STATUSES

    @property
    def calculation_eligible(self) -> bool:
        """Whether an explicit request naming this item may be calculated."""
        return self.status in _ELIGIBLE_STATUSES

    def as_payload(self) -> dict[str, Any]:
        """The public coverage dict — one producer, read by every consumer."""
        return {
            "name": self.name,
            "status": self.status,
            "optimizer_eligible": self.optimizer_eligible,
            "calculation_eligible": self.calculation_eligible,
            "outcome_dimensions": [
                dimension.value for dimension in self.outcome_dimensions
            ],
            "review_issue_refs": list(self.review_issue_refs),
            "reason": self.reason,
        }


# The eight retired registries are named in exactly one place in this tree, and
# these tombstones are deliberately not it: the absence gate that proves none of
# them survived — ``tests/test_coverage_claims.py``'s
# ``test_the_eight_retired_registries_have_no_occurrences_left`` — scans this
# package for whole identifiers, and prose that spells one is an occurrence it
# has to report.  Grepping a retired name lands on that assertion, which is the
# right destination for it; what stood where is described here instead.

# Three blocked-reason containers stood here — two dicts and a bare frozenset,
# the ones 3.8's first commit pinned.  All three were empty, and that commit
# asserted the emptiness.  An empty container makes ``name in`` false for every
# name that exists and every
# name that could, so those rungs decided nothing and the eligibility term added
# nothing: deleting them moves no answer.  A withheld item now has one producer
# — a cached record whose passive is unreviewed — instead of three that could
# disagree with each other.

# A stateful-items set stood here: twenty-one sentences saying an item's state
# was represented, checked by nothing.  It is gone.  ``modeled_state`` is now
# what the declared families say — an ally packet or a stat derivation is state
# the shared ledger schedules — or what ``ITEM_INPUT_OPTIONS`` says, and both
# are read out of a registry rather than asserted in prose here.


# Three target-lane containers stood here — modelled reasons, event-certified
# reasons and blocked reasons: thirty-nine reviewed sentences answering "what
# does this item do to the actor wearing it" by looking the actor's item up by
# name.  The ladder above now
# asks the declarations, the certification is a property of the mechanic in
# the catalog, and the refusal is the attacker lane's own.  What the sentences
# carried that a declaration cannot — which symbol prices each item — is the
# evidence beside the claim, in ``_TARGET_MODELED_IMPLS`` and
# ``_TARGET_CERTIFIED_IMPLS`` below, where it is checked against the derived
# population rather than trusted.

# The per-item outcome-dimension table stood here too, and its contents are the
# one thing the collapse did not delete: an outcome label no declaration can
# derive.  It is ``item_outcomes.UTILITY_OUTCOMES`` now — a declaration in a
# home of declarations, read by the payload builder below.


# The one reviewed registry that survives the flip, and the reason it has to:
# "we read the cached page and there is no runtime behaviour" is a fact about
# an *absence*, and no declaration can carry an absence.  Every other container
# in this module asserted the presence of a model, which is what declarations
# now say instead.
#
# It is a ratchet and not an escape hatch (criterion 2).  Its membership is
# committed to ``docs/behavior-frontier.json``, diff-gated by set equality, and
# **non-increasing** from the size measured before the phase — otherwise
# counter 3's target could be reached by reviewing the backlog into silence.
# Each entry was reviewed against the cached Wiki passive/active description at
# the revision ``_SOURCE_REFS`` records for it.
#
# **No member may compile a ``BehaviorRule`` that declares runtime
# behaviour** (``item_behavior_catalog.declares_runtime_behaviour``), and that
# is asserted rather than
# intended.  A compiled rule *is* declared runtime behaviour, so an item
# holding one and sitting here would assert two contradictory things at once —
# which is what thirty-four of these entries did when the set was renamed from
# ``_REVIEWED_STATS_ONLY``.  That name said "stats only on the outgoing-damage
# lane", which is a smaller claim and was true of all of them; this name says
# there is nothing to run, which was false of Frozen Heart's aura, of Spirit
# Visage's healing multiplier, and of thirty-two more.  The rename widened the
# claim without re-reviewing it, the widened members were unreachable (the
# defence and state rungs answer them first), and an unreachable false claim
# is exactly the shape this campaign exists to remove.  The set is now the
# ones the review actually covers: an item with a described passive and no
# rule that runs it, where "we looked and there is nothing to model" is the
# only thing that can be said.  A member may hold a registry entry whose whole
# content is where one of its *cached stats* lands — two do — because that
# declaration schedules nothing and moves no number the block did not already
# hold; what the review found about the item's described passive is untouched
# by it.
NO_RUNTIME_BEHAVIOR: Mapping[str, str] = {
    "Doran's Helm": "Helping Hand's 5 bonus physical damage is restricted to minions; the "
    "full Wiki entry has no champion-facing sustain branch.",
    "Scorchclaw Pup": "The jungle companion and evolved Smite buff affect monsters, not the champion target model.",
    "Gustwalker Hatchling": "The jungle companion and evolved Smite buff affect monsters, not the champion target model.",
    "Mosstomper Seedling": "The jungle companion and evolved Smite buff affect monsters, not the champion target model.",
    "Refillable Potion": "Potion charges restore the holder's health; they add no outgoing target damage.",
    "Executioner's Calling": "Grievous Wounds reduces recipient healing; it adds no direct damage.",
    "Oblivion Orb": "Grievous Wounds reduces recipient healing; it adds no direct damage.",
    "Quicksilver Sash": "Quicksilver is defensive cleanse.",
    "Lost Chapter": "Enlighten restores mana on level-up; it adds no direct damage.",
    "Chempunk Chainsword": "Hackshorn applies sourced three-second Grievous Wounds in the coupled "
    "timeline; it does not add direct damage.",
    "Cosmic Drive": "Spelldance grants movement speed, not direct damage.",
    "Gluttonous Greaves": "Slay grants omnivamp, not outgoing damage.",
    "Morellonomicon": "Grievous Wounds reduces recipient healing in the coupled timeline; it "
    "does not add direct damage.",
    "Mortal Reminder": "Grievous Wounds reduces recipient healing in the coupled timeline; it "
    "does not add direct damage.",
    "Phantom Dancer": "Spectral Waltz grants ghosting.",
    "Rylai's Crystal Scepter": "Rimefrost slows without adding direct damage.",
    "Crimson Lucidity": "Its passives grant summoner haste and movement speed.",
    "Serylda's Grudge": "Bitter Cold slows without adding direct damage.",
    "Boots of Swiftness": "Fleetfooted grants slow resistance.",
    "Ionian Boots of Lucidity": "Ionian Insight grants summoner spell haste.",
    "Youmuu's Ghostblade": "Haunt and Wraith Step grant movement speed.",
}


# Concrete GitHub owners for source-backed gaps.  The full-entry audit exposes
# these references beside every withheld effect so a page review cannot end
# with an untracked prose note.  The umbrella #40 remains the release gate;
# child issues own the implementation family.
_REVIEW_ISSUE_REFS: dict[str, tuple[int, ...]] = {
    "Stridebreaker": (43,),
    "Voltaic Cyclosword": (43,),
    "Runaan's Hurricane": (43,),
    "Fimbulwinter": (44, 46),
    "Endless Hunger": (44, 45),
    "Whispering Circlet": (44,),
    "Archangel's Staff": (44,),
    "Manamune": (44,),
    "Winter's Approach": (44,),
    "Zeke's Convergence": (44,),
    "Axiom Arc": (44,),
    "Hubris": (44,),
    "Doran's Helm": (45,),
    "Actualizer": (45,),
    "Catalyst of Aeons": (45,),
    "Immortal Path": (45,),
    "Ardent Censer": (48,),
    "Bandlepipes": (48,),
    "Imperial Mandate": (48,),
    "Redemption": (48,),
    "Mikael's Blessing": (48,),
    "Locket of the Iron Solari": (46, 48),
}


def review_issue_refs(item_name: str) -> list[int]:
    """Return concrete child issues for a source-backed coverage gap."""
    return list(_REVIEW_ISSUE_REFS.get(str(item_name), (40,)))


def _has_described_effect(item: Mapping[str, Any]) -> bool:
    """Return whether cached Wiki data describes a passive or active."""
    return bool(item.get("passives") or item.get("active") or item.get("actives"))


def _cached_record(name: str) -> Mapping[str, Any]:
    """One cached item record, read through the caching layer (rule 2).

    A name the shop does not hold is a synthetic fixture, not an error: the
    last two rungs exist to tell those apart from real records, so a miss is an
    empty mapping rather than a raise.
    """
    try:
        return get_item_by_name(name)
    except KeyError:
        return {}


def _declared_families(name: str) -> frozenset[RuleFamily]:
    """Every family *name* declares — through a rule, or through its entry.

    Two sources and not one, deliberately.  A compiled ``BehaviorRule`` is the
    declaration proper; a registry entry whose family is not migrated yet
    compiles to no rule but is still an item whose behaviour the engines run.
    Reading only the rules would call every unmigrated item unmodelled, which
    is a refusal invented by the migration rather than by the model.

    One shape is deliberately *not* a family here: a declaration that only
    says where a **cached stat** lands.  Its number was already in the stat
    block before any declaration existed — the channel says which field of the
    block reads it, not that the item does something — so counting it would
    publish "damage-relevant effects are declared" for an item whose described
    passive is still nothing anyone modelled.  Read off the declaration and
    off the tag (:data:`~.item_behavior_catalog.STAT_CHANNEL_TAGS`), never off
    a name.
    """
    families = {
        family
        for _, family, entry in registry_entries(name)
        if str(entry.get("type", "")) not in STAT_CHANNEL_TAGS
    }
    families.update(
        rule.family for rule in behavior_rules(name) if declares_runtime_behaviour(rule)
    )
    return frozenset(families)


def unserved_lanes(name: str, needed: frozenset[EngineLane]) -> tuple[str, ...]:
    """Every ``(family, lane)`` *name* declares that no interpreter serves.

    This is the whole of ``withheld``: a declared family whose interpreter is
    missing on a lane the caller needs cannot be priced, and the honest answer
    is a named refusal rather than a number the missing interpreter would have
    changed.  Empty tuple is the pass condition, and it is empty for every
    cached item today — which is why the branch is proved on a synthetic
    declaration and on an emptiness assertion rather than by a real build
    (D-26).

    It folds over compiled **rules** and never over registry entries, and the
    difference is the whole correctness of the flip.  A family a registry entry
    names but no rule compiles is *unmigrated*, not uninterpreted: its
    behaviour is still live engine code, and withholding it would be a refusal
    the migration invented.  ``stat_derivation`` is exactly that today, and
    reading entries here would withhold Rabadon's Deathcap from BIS on the
    strength of a declaration nobody has written yet.
    """
    return tuple(
        sorted(
            f"{family.value}/{lane.value}"
            for family in {rule.family for rule in behavior_rules(name)}
            for lane in lanes_for(family) & needed
            if (family, lane) not in INTERPRETERS
        )
    )


def declares_only_defence(name: str) -> bool:
    """Everything this item declares is about surviving, not dealing."""
    families = _declared_families(name)
    return bool(families) and families <= _DEFENCE_FAMILIES


def declares_state(name: str) -> bool:
    """Declared behaviour whose numbers come out of supplied state."""
    families = _declared_families(name)
    if not families:
        return False
    return bool(name in ITEM_INPUT_OPTIONS or families & _STATE_FAMILIES)


def gated_state_reason(name: str) -> str | None:
    """The defence-only branch's sub-question: is the defence *armed* by an input?

    A defence-only item is ``stats_only`` either way, so this decides only what
    the receipt beside that label says.  When a declared rule describes an
    exclusive state (``exclusivity``) that an explicit bounded option arms
    (``option``), the load-bearing fact is that gate — holding the item is not
    holding the state — and the family census, which says only that nothing
    declared here is offensive, is the weaker sentence.  It is also the false
    one for an item like this: an item whose active suppresses its own holder
    for the duration does touch outgoing damage, so "the mechanic changes
    durability, not outgoing TDD" is a claim the declaration does not support.

    Every part of the sentence is read off the declared rule — the mechanic
    names itself, the exclusivity names the state, and what is left of the
    option key after the state's own prefix names the control — so the rung
    stays a derivation and no item name enters this file.  ``None`` means the
    declaration carries no such gate and the family census stands.
    """
    for rule in behavior_rules(name):
        payload = rule.payload
        exclusivity = getattr(payload, "exclusivity", None)
        option = getattr(payload, "option", None)
        if option is None or exclusivity in (None, DefenseExclusivity.NONE):
            continue
        state = exclusivity.value
        control = option.value.removeprefix(f"{state}_").replace("_", "-")
        mechanic = payload.mechanic.value.replace("_", " ").title()
        return (
            f"{mechanic} is priced only from the explicit bounded {control} "
            f"scenario input; item presence alone never assumes {state}."
        )
    return None


def _state_reason(name: str, families: frozenset[RuleFamily]) -> str:
    """Why a declared item's damage-relevant state is supplied rather than run."""
    if name in ITEM_INPUT_OPTIONS:
        return (
            f"{name}'s damage-relevant state is supplied through an explicit "
            "bounded scenario control, and its declared behaviour reads it."
        )
    return (
        "The declared behaviour carries progression or cross-participant state "
        "that the shared participant ledger schedules: "
        + ", ".join(sorted(family.value for family in families & _STATE_FAMILIES))
        + "."
    )


def _declared_status(
    name: str, families: frozenset[RuleFamily]
) -> tuple[ItemCoverageStatus, str]:
    """The status of an item whose behaviour is declared, from its families."""
    if declares_only_defence(name):
        gated = gated_state_reason(name)
        if gated is not None:
            return "stats_only", gated
        return (
            "stats_only",
            "Every declared family on this item is a defence: the represented "
            "mechanic changes durability, not outgoing TDD.",
        )
    if declares_state(name):
        return "modeled_state", _state_reason(name, families)
    return (
        "modeled_effect",
        "Damage-relevant effects are declared and every declared family has an "
        "interpreter on the lanes this request needs.",
    )


def item_model_coverage(name: str, needed: frozenset[EngineLane]) -> ItemCoverage:
    """One item's coverage on the lanes a caller needs, computed from declarations.

    The ladder used to branch on the item's name eleven times.  It now asks
    four questions in order, and every one of them is answered by something the
    catalog or the registries say rather than by a sentence in this file:

    1. Does a declared family lack an interpreter on a needed lane?  Then the
       answer is ``withheld`` with the missing pair named — never a number.
    2. Is anything declared at all?  Then the families decide: all-defence is
       ``stats_only``, a state or ally family is ``modeled_state``, and the
       rest is ``modeled_effect``.  An all-defence item whose declaration
       gates an exclusive state behind a bounded option publishes that gate
       as its receipt rather than the family census.
    3. Does the item expose bounded state as a scenario control, or has a
       review found it has no runtime behaviour?  Then ``modeled_state`` and
       ``stats_only`` respectively — the second being the one reviewed registry
       that survives, because "we looked and there is nothing" is a fact no
       declaration can carry.
    4. Otherwise it has a cached passive nothing declares.  A real shop record
       is ``withheld``; anything else is a fixture and is ``review_pending``.
    """
    record = _cached_record(name)
    unserved = unserved_lanes(name, needed)
    if unserved:
        status: ItemCoverageStatus = "withheld"
        reason = (
            f"{name} declares {', '.join(unserved)} and no interpreter serves "
            "it there, so its contribution is withheld rather than priced as "
            "zero."
        )
    else:
        families = _declared_families(name)
        if families:
            status, reason = _declared_status(name, families)
        elif name in ITEM_INPUT_OPTIONS:
            status = "modeled_state"
            reason = "The item exposes its damage-relevant state as a scenario control."
        elif name in NO_RUNTIME_BEHAVIOR:
            status = "stats_only"
            reason = NO_RUNTIME_BEHAVIOR[name]
        elif not _has_described_effect(record):
            status = "stats_only"
            reason = (
                "The item has no separate passive or active in the cached Wiki data."
            )
        elif record.get("id") is not None or record.get("icon"):
            status = "withheld"
            reason = (
                "This cached passive or active is declared by no BehaviorRule "
                "and no registry entry; calculation is withheld."
            )
        else:
            status = "review_pending"
            reason = (
                "This passive or active has not yet been reviewed for outgoing TDD."
            )

    return ItemCoverage(
        name=name,
        status=status,
        reason=reason,
        outcome_dimensions=UTILITY_OUTCOMES.get(name, ()),
        review_issue_refs=(
            tuple(review_issue_refs(name)) if status in _REFUSAL_STATUSES else ()
        ),
        needed=needed,
    )


# ── the target lane, derived ──────────────────────────────────────────────

# A packet whose kind is one of these changes what its recipient survives;
# every other kind is a stat buff, a movement effect, vision or an economy
# payout, and none of those is durability.
_DURABILITY_PACKET_KINDS: frozenset[PacketKind] = frozenset(
    {PacketKind.HEAL, PacketKind.SHIELD, PacketKind.TEMPORARY_HEALTH}
)

# The payload fields a strike declares when its own hit heals or shields the
# holder.  Named fields rather than a substring test on field names: the
# ``self_shield`` on a cast proc and the ``heal`` on a forced crit *are* the
# mechanism, and a test asserts every name here is a field of some declared
# payload class, so a rename fails loudly rather than quietly emptying it.
_HOLDER_SURVIVAL_FIELDS: frozenset[str] = frozenset(
    {
        "heal",
        "self_heal_share",
        "self_heal_ap_ratio",
        "self_heal_bonus_health_ratio",
        "self_shield",
    }
)


def declared_defence(rule: BehaviorRule) -> DefenseMechanic | None:
    """The defence a rule declares, or ``None`` when it declares none.

    Every compiler builds ``mechanic_id`` as ``<owner slug>.<mechanic>``, so
    the suffix is the mechanic's own name; a suffix that names a
    :class:`~.item_behavior.DefenseMechanic` member is a defence the resolver
    builds.  Read off the identifier rather than off ``payload.mechanic``
    because one defence — Fimbulwinter's Everlasting — is declared as the ally
    packet that grants the shield and carries no ``mechanic`` field, and a
    reader that missed it would silently drop the item from the target lane.
    A test pins that the two agree wherever the payload has both.
    """
    try:
        return DefenseMechanic(rule.mechanic_id.rsplit(".", 1)[-1])
    except ValueError:
        return None


def _prices_holder_durability(rule: BehaviorRule) -> bool:
    """Whether *rule* changes what the actor holding it can survive.

    Five shapes, each read off the declaration and none off a name:

    1. it declares a :class:`~.item_behavior.DefenseMechanic` — the defence
       resolver's own closed vocabulary, and the target lane is that lane;
    2. it is a ``sustain`` rule that schedules a heal rather than granting a
       vampirism stat, because a stat is priced by the stat fold and only a
       scheduled heal enters the durability ledger;
    3. it is a ``stat_derivation`` rule granting one of
       :data:`~.item_behavior.DURABILITY_STATS`, or an aura whose subject is
       the enemy — the holder's benefit of a stat reduced on somebody else;
    4. its payload declares a holder heal or shield beside its own damage —
       the strike families whose hit pays health back;
    5. it emits a cross-participant packet that heals, shields or grants
       temporary health, or that redirects incoming damage away from its
       recipient.
    """
    if declared_defence(rule) is not None:
        return True
    payload = rule.payload
    if rule.family is RuleFamily.SUSTAIN and not isinstance(payload, SustainStatRule):
        return True
    if rule.family is RuleFamily.STAT_DERIVATION and (
        getattr(payload, "granted", None) in DURABILITY_STATS
        or getattr(payload, "subject", None) is Subject.TARGET
    ):
        return True
    if any(
        getattr(payload, field, None) is not None for field in _HOLDER_SURVIVAL_FIELDS
    ):
        return True
    if getattr(payload, "redirects_incoming_damage", False):
        return True
    return any(
        spec.kind in _DURABILITY_PACKET_KINDS
        for spec in getattr(payload, "packets", ()) or ()
    )


def target_lane_rules(name: str) -> tuple[BehaviorRule, ...]:
    """Every rule *name* declares that the passive-target model prices."""
    return tuple(
        rule for rule in behavior_rules(name) if _prices_holder_durability(rule)
    )


def certified_target_mechanics(name: str) -> tuple[DefenseMechanic, ...]:
    """The declared defences on *name* that need an exactly-timed ledger.

    The catalog declares the property per mechanic and this reads it, so the
    six Lifelines are one declaration rather than six reviewed sentences and a
    seventh item taking a Lifeline is certified the day it is declared.
    """
    return tuple(
        mechanic
        for rule in behavior_rules(name)
        if (mechanic := declared_defence(rule)) in EVENT_CERTIFIED_MECHANICS
        and mechanic is not None
    )


def _mechanic_list(rules: tuple[BehaviorRule, ...]) -> str:
    """The declared mechanics behind an answer, named as the wiki names them.

    The mechanic's own name and never the item's: the receipt says *what* is
    priced, and the item is already the subject of the sentence around it.
    """
    return ", ".join(
        sorted(
            {
                rule.mechanic_id.rsplit(".", 1)[-1].replace("_", " ").title()
                for rule in rules
            }
        )
    )


def _derived_target_status(name: str) -> tuple[str, str]:
    """The target-lane status of an item whose behaviour is declared."""
    certified = certified_target_mechanics(name)
    priced = target_lane_rules(name)
    if certified:
        return (
            "modeled_event_certified",
            f"{_mechanic_list(priced)} is scheduled from the exactly-timed "
            f"damage ledger — "
            + "; ".join(
                sorted(EVENT_CERTIFIED_MECHANICS[mechanic] for mechanic in certified)
            )
            + " — so an uncertified timed fight is withheld rather than mis-timed.",
        )
    if priced:
        return (
            "modeled",
            f"{_mechanic_list(priced)} changes what this actor survives, and "
            "every rule behind it has an interpreter on the target lane.",
        )
    return (
        "not_target_relevant",
        "Nothing this item declares changes incoming damage, durability or "
        "combat healing in the passive-target model.",
    )


def is_unreviewed_fixture(item: Mapping[str, Any]) -> bool:
    """Whether *item* is a supplied record the shop does not hold.

    The one question on the target lane that is asked of the caller's record
    rather than of the cache: a name the shop has never sold, carrying a
    described passive, is a synthetic or unknown fixture, and answering it
    ``not_target_relevant`` would be a review nobody performed.
    """
    return not _cached_record(str(item.get("name", ""))) and _has_described_effect(item)


def target_calculation_eligible(status: str) -> bool:
    """Whether a target-lane status permits calculating what the actor survives.

    The target lane's counterpart to :attr:`ItemCoverage.calculation_eligible`,
    and a named predicate rather than an inline expression for the same reason
    that one is a property: it is the question a fail-closed whitelist has to
    be able to answer for a status nobody has classified yet.
    """
    return status in _TARGET_ELIGIBLE_STATUSES


def target_item_model_coverage(item: dict[str, Any]) -> dict[str, Any]:
    """Classify one item for use on a passive enemy target, from declarations.

    Three rungs, in this order:

    1. **The attacker ladder's refusal, passed through.**  A cached record
       whose described passive no rule and no registry entry declares is
       withheld there, and the same absence is a refusal here: an unreviewed
       passive may as easily be a defence as an attack, and calling it "no
       reviewed effect changes durability" claims a review nobody performed.
    2. **What the item declares**, through :func:`_derived_target_status` — a
       certified defence, a durability mechanic, or nothing.
    3. **A record the shop does not hold, carrying a described passive**: a
       synthetic or unknown fixture, which is ``review_pending``.  Rung 1
       cannot answer this one — it reads the *cached* record by name and there
       is none — so the question is asked of the supplied record here.  Both
       rungs fail closed; they differ only in which record holds the passive.
    """
    name = str(item.get("name", ""))
    refusal = item_model_coverage(name, TARGET_LANES)
    if refusal.status in _REFUSAL_STATUSES:
        status, reason = refusal.status, refusal.reason
    elif is_unreviewed_fixture(item):
        status = "review_pending"
        reason = "This passive or active has not been reviewed for target durability."
    else:
        status, reason = _derived_target_status(name)
    return {
        "name": name,
        "status": status,
        "calculation_eligible": target_calculation_eligible(status),
        "outcome_dimensions": [
            dimension.value for dimension in UTILITY_OUTCOMES.get(name, ())
        ],
        "review_issue_refs": (
            review_issue_refs(name) if status in _REFUSAL_STATUSES else []
        ),
        "reason": reason,
    }


def target_build_coverage(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarise whether a target inventory is safe to calculate."""
    entries = [target_item_model_coverage(item) for item in items]
    withheld = [entry for entry in entries if not entry["calculation_eligible"]]
    return {
        "complete": not withheld,
        "model": "passive_target",
        "items": entries,
        "withheld": withheld,
        "note": (
            "Every equipped item is supported by the passive-target model."
            if not withheld
            else "Calculation is withheld until the named target mechanic is modelled."
        ),
    }


def require_target_item_coverage(items: list[dict[str, Any]]) -> None:
    """Reject target inventories that would silently omit a defense."""
    coverage = target_build_coverage(items)
    if coverage["withheld"]:
        withheld = coverage["withheld"][0]
        raise ValueError(
            f"Enemy item {withheld['name']} is not supported yet: "
            f"{withheld['reason']}"
        )


def require_certified_target_timeline(
    items: list[dict[str, Any]], timeline_coverage: dict[str, Any]
) -> None:
    """Withhold a computed fight that cannot price a conditional defense.

    Conditional defenses are priced from the ordered damage ledger, so a
    coarse source would mis-time the trigger.  This runs after the fight so
    the error can name the exact uncertified sources instead of guessing.
    """
    if bool(timeline_coverage.get("complete", False)):
        return
    conditional = next(
        (
            str(item.get("name", ""))
            for item in items
            if certified_target_mechanics(str(item.get("name", "")))
        ),
        None,
    )
    if conditional is None:
        return
    coarse = [str(source) for source in timeline_coverage.get("coarse_sources", [])]
    named = ", ".join(coarse) if coarse else "at least one damage source"
    verb = "is" if len(coarse) <= 1 else "are"
    raise ValueError(
        f"Result withheld: enemy item {conditional} needs a "
        f"certified event timeline, but {named} {verb} not event-certified."
    )


def optimizer_candidate_coverage(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarise which legal item candidates can be scored without omission.

    D-23's published half.  A withheld candidate is **excluded from candidate
    generation** by :func:`optimizer_supported_items` and **named here**, and
    the per-request exclusion count is published as ``withheld_count`` so a
    request that quietly lost a legal build says so in its own response rather
    than only in a log.  It is never scored as zero, which is the outcome this
    campaign exists to make unrepresentable.
    """
    classified = [
        item_model_coverage(str(item.get("name", "")), SCORING_LANES) for item in items
    ]
    included = [entry for entry in classified if entry.optimizer_eligible]
    withheld = [entry for entry in classified if not entry.optimizer_eligible]
    return {
        "eligible_candidates": len(classified),
        "scored_candidates": len(included),
        "withheld_count": len(withheld),
        "complete": not withheld,
        "withheld": [entry.as_payload() for entry in withheld],
        "note": (
            "Every legal candidate is fully modelled."
            if not withheld
            else (
                f"{len(withheld)} legal item candidate"
                f"{' is' if len(withheld) == 1 else 's are'} withheld because "
                "a damage-relevant mechanic is not yet modelled."
            )
        ),
    }


def optimizer_supported_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return candidates whose outgoing TDD can be scored without omission.

    The exclusion half of D-23: a withheld item never reaches candidate
    generation, so no build is ranked on a zero standing in for a mechanic
    nobody ran.
    """
    return [
        item
        for item in items
        if item_model_coverage(
            str(item.get("name", "")), SCORING_LANES
        ).optimizer_eligible
    ]


def require_optimizer_item_coverage(item: dict[str, Any]) -> None:
    """Reject a locked item whose damage-relevant mechanics are incomplete."""
    coverage = item_model_coverage(str(item.get("name", "")), SCORING_LANES)
    if not coverage.optimizer_eligible:
        raise ValueError(
            f"{coverage.name} cannot be locked into BIS search yet: "
            f"{coverage.reason}"
        )


def require_calculation_item_coverage(
    items: list[dict[str, Any]],
    *,
    participant: str,
    allow_ally_effects: bool = False,
) -> None:
    """Reject a participant loadout whose outgoing effects are incomplete.

    Manual calculations and coupled roster fights are calculation entry paths,
    not only optimiser requests.  Reusing the same per-item contract here
    prevents an incomplete item from being accepted by ``/api/calculate``
    while remaining selectable in the browser.
    """
    for item in items:
        coverage = item_model_coverage(str(item.get("name", "")), SCORING_LANES)
        if (
            allow_ally_effects
            and coverage.status == "withheld"
            and coverage.name in ALLY_ITEM_EFFECTS
        ):
            # CP17's cross-participant packet layer is the authoritative
            # calculation path for support items.  They remain withheld from
            # ordinary BIS ranking until every holder-side sibling is
            # modeled, but an explicitly rostered support item is safe to
            # calculate because its item-team effects are timestamped and
            # fail closed when their trigger is absent.
            continue
        if coverage.calculation_eligible:
            continue
        raise ValueError(
            f"{participant} item {coverage.name} cannot be used in a "
            f"calculation yet: {coverage.reason}"
        )


# ── the claim corpus ──────────────────────────────────────────────────────

# Every answer this module gives used to be backed by a sentence.  One of them
# went on describing both halves of Imperial Mandate's Command long after only
# one half existed, and nothing checked the sentence against the code.  These
# are the claims that replace the sentences: one per ``(item, lane)`` for every
# entry in the seven non-empty containers above and one per item that emits a
# walk packet — each carrying typed evidence the resolution tier resolves
# against this tree on every ``pytest`` run.
#
# The *evidence* is authored and the assembly is mechanical, in that order and
# never the other way round.  A table that read its own evidence out of the
# registries it describes would agree with them by construction, which is the
# failure mode this module exists to catch; so every symbol path, packet
# source, option control, registry key, wiki revision and node id below is
# written down, and only the loop that turns them into ``Claim`` records is
# code.  ``Claim.status`` is a **pinned expectation, never an authority**: the
# classifier above stays the only answer to "what is this item's coverage",
# the resolution tier asserts the two agree for every cached item, and no
# ``src`` module reads the corpus at all.

# The umbrella issue every unrouted review gap falls back to.
_UMBRELLA_ISSUE = 40

# The two H4 reasons stood here, one for each half of the ten tags no engine
# dispatched on.  The stat-derivation migration gave the last three of them a
# real dispatch, so the frontier holds no ``tag:`` claim at all and neither
# reason has a claim left to carry.  Whether the *tags* are then deleted or
# kept is still umbrella decision H4's, the human's — the record of which four
# were dead and which six self-referential is
# ``item_behavior_catalog.H4_DEAD_TAGS`` / ``H4_SELF_REFERENTIAL_TAGS``, with a
# reason each, which is where H4 reads its population.

# Two items appear in ``_REVIEW_ISSUE_REFS`` and in no other container.  Their
# refs still need exactly one claim to carry them, so they get the claim their
# rung implies — ``ITEM_EFFECTS`` membership — rather than a home invented for
# the purpose.
# The status is pinned per item rather than shared, because the rung an
# ``ITEM_EFFECTS`` member lands on depends on what it declares: Zeke's
# Convergence also grants ultimate haste, which is a stat derivation, and the
# ladder answers ``modeled_state`` before ``modeled_effect`` for a state
# family.  A shared constant here would have made that a test failure with no
# way to record the true answer.
_ISSUE_REF_ONLY_ITEMS: Mapping[str, ItemCoverageStatus] = {
    "Catalyst of Aeons": "modeled_effect",
    "Voltaic Cyclosword": "modeled_effect",
    "Zeke's Convergence": "modeled_state",
}

_SOURCE_REFS: Mapping[str, tuple[str, int]] = {
    "Abyssal Mask": ("https://wiki.leagueoflegends.com/en-us/Abyssal_Mask", 3984960),
    "Armored Advance": (
        "https://wiki.leagueoflegends.com/en-us/Armored_Advance",
        4013702,
    ),
    "Banshee's Veil": (
        "https://wiki.leagueoflegends.com/en-us/Banshee's_Veil",
        3957919,
    ),
    "Blasting Wand": ("https://wiki.leagueoflegends.com/en-us/Blasting_Wand", 4022947),
    "Bloodthirster": ("https://wiki.leagueoflegends.com/en-us/Bloodthirster", 4025103),
    "Boots of Swiftness": (
        "https://wiki.leagueoflegends.com/en-us/Boots_of_Swiftness",
        4022244,
    ),
    "Celestial Opposition": (
        "https://wiki.leagueoflegends.com/en-us/Celestial_Opposition",
        4028004,
    ),
    "Chainlaced Crushers": (
        "https://wiki.leagueoflegends.com/en-us/Chainlaced_Crushers",
        4013705,
    ),
    "Chempunk Chainsword": (
        "https://wiki.leagueoflegends.com/en-us/Chempunk_Chainsword",
        4000212,
    ),
    "Cosmic Drive": ("https://wiki.leagueoflegends.com/en-us/Cosmic_Drive", 4005389),
    "Crimson Lucidity": (
        "https://wiki.leagueoflegends.com/en-us/Crimson_Lucidity",
        4030440,
    ),
    "Cryptbloom": ("https://wiki.leagueoflegends.com/en-us/Cryptbloom", 3989109),
    "Death's Dance": ("https://wiki.leagueoflegends.com/en-us/Death's_Dance", 4015383),
    "Diadem of Songs": (
        "https://wiki.leagueoflegends.com/en-us/Diadem_of_Songs",
        3993317,
    ),
    "Doran's Helm": ("https://wiki.leagueoflegends.com/en-us/Doran's_Helm", 4034679),
    "Doran's Ring": ("https://wiki.leagueoflegends.com/en-us/Doran's_Ring", 4026377),
    "Doran's Shield": (
        "https://wiki.leagueoflegends.com/en-us/Doran's_Shield",
        4026378,
    ),
    "Dream Maker": ("https://wiki.leagueoflegends.com/en-us/Dream_Maker", 4030400),
    "Echoes of Helia": (
        "https://wiki.leagueoflegends.com/en-us/Echoes_of_Helia",
        4046489,
    ),
    "Edge of Night": ("https://wiki.leagueoflegends.com/en-us/Edge_of_Night", 4013389),
    "Executioner's Calling": (
        "https://wiki.leagueoflegends.com/en-us/Executioner's_Calling",
        3985491,
    ),
    "Force of Nature": (
        "https://wiki.leagueoflegends.com/en-us/Force_of_Nature",
        4016272,
    ),
    "Frozen Heart": ("https://wiki.leagueoflegends.com/en-us/Frozen_Heart", 4025104),
    "Gluttonous Greaves": (
        "https://wiki.leagueoflegends.com/en-us/Gluttonous_Greaves",
        4030444,
    ),
    "Guardian Angel": (
        "https://wiki.leagueoflegends.com/en-us/Guardian_Angel",
        4001358,
    ),
    "Gunmetal Greaves": (
        "https://wiki.leagueoflegends.com/en-us/Gunmetal_Greaves",
        4013706,
    ),
    "Gustwalker Hatchling": (
        "https://wiki.leagueoflegends.com/en-us/Gustwalker_Hatchling",
        4041864,
    ),
    "Immortal Shieldbow": (
        "https://wiki.leagueoflegends.com/en-us/Immortal_Shieldbow",
        4030401,
    ),
    "Ionian Boots of Lucidity": (
        "https://wiki.leagueoflegends.com/en-us/Ionian_Boots_of_Lucidity",
        4022246,
    ),
    "Jak'Sho, The Protean": (
        "https://wiki.leagueoflegends.com/en-us/Jak'Sho,_The_Protean",
        3984950,
    ),
    "Kaenic Rookern": (
        "https://wiki.leagueoflegends.com/en-us/Kaenic_Rookern",
        3984971,
    ),
    "Knight's Vow": ("https://wiki.leagueoflegends.com/en-us/Knight's_Vow", 4023793),
    "Locket of the Iron Solari": (
        "https://wiki.leagueoflegends.com/en-us/Locket_of_the_Iron_Solari",
        4022957,
    ),
    "Lost Chapter": ("https://wiki.leagueoflegends.com/en-us/Lost_Chapter", 3989340),
    "Maw of Malmortius": (
        "https://wiki.leagueoflegends.com/en-us/Maw_of_Malmortius",
        3984424,
    ),
    "Mercurial Scimitar": (
        "https://wiki.leagueoflegends.com/en-us/Mercurial_Scimitar",
        3984461,
    ),
    "Mikael's Blessing": (
        "https://wiki.leagueoflegends.com/en-us/Mikael's_Blessing",
        3984364,
    ),
    "Moonstone Renewer": (
        "https://wiki.leagueoflegends.com/en-us/Moonstone_Renewer",
        4022988,
    ),
    "Morellonomicon": (
        "https://wiki.leagueoflegends.com/en-us/Morellonomicon",
        3985490,
    ),
    "Mortal Reminder": (
        "https://wiki.leagueoflegends.com/en-us/Mortal_Reminder",
        4023637,
    ),
    "Mosstomper Seedling": (
        "https://wiki.leagueoflegends.com/en-us/Mosstomper_Seedling",
        4041862,
    ),
    "Oblivion Orb": ("https://wiki.leagueoflegends.com/en-us/Oblivion_Orb", 3985489),
    "Phantom Dancer": (
        "https://wiki.leagueoflegends.com/en-us/Phantom_Dancer",
        4047301,
    ),
    "Plated Steelcaps": (
        "https://wiki.leagueoflegends.com/en-us/Plated_Steelcaps",
        4022248,
    ),
    "Protoplasm Harness": (
        "https://wiki.leagueoflegends.com/en-us/Protoplasm_Harness",
        4045616,
    ),
    "Quicksilver Sash": (
        "https://wiki.leagueoflegends.com/en-us/Quicksilver_Sash",
        3729899,
    ),
    "Randuin's Omen": (
        "https://wiki.leagueoflegends.com/en-us/Randuin's_Omen",
        4021798,
    ),
    "Refillable Potion": (
        "https://wiki.leagueoflegends.com/en-us/Refillable_Potion",
        3971312,
    ),
    "Rylai's Crystal Scepter": (
        "https://wiki.leagueoflegends.com/en-us/Rylai's_Crystal_Scepter",
        3984377,
    ),
    "Scorchclaw Pup": (
        "https://wiki.leagueoflegends.com/en-us/Scorchclaw_Pup",
        4041863,
    ),
    "Seeker's Armguard": (
        "https://wiki.leagueoflegends.com/en-us/Seeker's_Armguard",
        3837259,
    ),
    "Serylda's Grudge": (
        "https://wiki.leagueoflegends.com/en-us/Serylda's_Grudge",
        3984392,
    ),
    "Shurelya's Battlesong": (
        "https://wiki.leagueoflegends.com/en-us/Shurelya's_Battlesong",
        3984368,
    ),
    "Solstice Sleigh": (
        "https://wiki.leagueoflegends.com/en-us/Solstice_Sleigh",
        4028003,
    ),
    "Spirit Visage": ("https://wiki.leagueoflegends.com/en-us/Spirit_Visage", 4016166),
    "Umbral Glaive": ("https://wiki.leagueoflegends.com/en-us/Umbral_Glaive", 4013390),
    "Verdant Barrier": (
        "https://wiki.leagueoflegends.com/en-us/Verdant_Barrier",
        3957920,
    ),
    "Youmuu's Ghostblade": (
        "https://wiki.leagueoflegends.com/en-us/Youmuu's_Ghostblade",
        4013388,
    ),
    "Zhonya's Hourglass": (
        "https://wiki.leagueoflegends.com/en-us/Zhonya's_Hourglass",
        3902922,
    ),
}

_ATTACKER_STATE_HOMES: Mapping[str, tuple[str, str]] = {
    "Actualizer": (
        "item_effects.item_state_receipts",
        "option:mana_made_real_active_seconds",
    ),
    "Archangel's Staff": (
        "item_effects.item_state_receipts",
        "option:manaflow_bonus_mana",
    ),
    "Ardent Censer": (
        "item_support_effects.derive_item_support_effects",
        "packet:Ardent Censer — Sanctify",
    ),
    "Axiom Arc": (
        "item_effects.axiom_arc_ultimate_refund_fraction",
        "key:ultimate_refund_base_ratio",
    ),
    "Bandlepipes": (
        "item_support_effects.derive_item_support_effects",
        "packet:Bandlepipes — Fanfare",
    ),
    "Cull": ("item_effects.item_state_receipts", "option:reap_minion_kills"),
    "Endless Hunger": (
        "item_effects.item_state_receipts",
        "option:feast_active_seconds",
    ),
    "Fimbulwinter": (
        "item_support_effects.derive_item_support_effects",
        "packet:Fimbulwinter — Everlasting",
    ),
    "Hubris": ("item_effects.item_state_receipts", "option:eminence_stacks"),
    "Immortal Path": ("item_effects.item_state_receipts", "option:slay_stacks"),
    "Imperial Mandate": (
        "item_support_effects.derive_item_support_effects",
        "packet:Imperial Mandate — Command",
    ),
    "Manamune": ("item_effects.item_state_receipts", "option:manaflow_bonus_mana"),
    "Phage": (
        "item_support_effects.derive_item_support_effects",
        "packet:Phage — Rage",
    ),
    "Runic Compass": ("item_effects.item_state_receipts", "option:shared_riches_gold"),
    "Tear of the Goddess": (
        "item_effects.item_state_receipts",
        "option:manaflow_bonus_mana",
    ),
    "Umbral Glaive": ("item_effects.item_state_receipts", "option:nightstalker_ready"),
    "Whispering Circlet": (
        "item_effects.item_state_receipts",
        "option:manaflow_bonus_mana",
    ),
    "Winter's Approach": (
        "item_effects.item_state_receipts",
        "option:manaflow_bonus_mana",
    ),
    "World Atlas": ("item_effects.item_state_receipts", "option:shared_riches_gold"),
}

# The claim population for the target lane's two modelled statuses, and the
# symbol each item's durability is priced by.  Since 3.8's flip the *status*
# is derived and this table is the evidence beside it: a resolution test
# asserts the derived answer and the claim agree for every cached item, so an
# entry that stopped being modelled fails rather than sitting here unread.
_TARGET_MODELED_IMPLS: Mapping[str, str] = {
    "Armored Advance": "defensive_effects.resolve_starting_defenses",
    "Banshee's Veil": "defensive_effects.resolve_starting_defenses",
    "Bloodthirster": "defensive_effects.resolve_starting_defenses",
    "Bramble Vest": "interpreters.reactive.thorns_effects",
    "Celestial Opposition": "defensive_effects.resolve_starting_defenses",
    "Chainlaced Crushers": "defensive_effects.resolve_starting_defenses",
    "Catalyst of Aeons": "interpreters.sustain.sustain_slot",
    "Cryptbloom": "item_support_effects.derive_item_support_effects",
    "Cull": "item_support_effects.derive_item_support_effects",
    "Death's Dance": "interpreters.damage_routing.DamageRoutingResolverInterpreter",
    "Diadem of Songs": "item_support_effects.derive_item_support_effects",
    "Doran's Blade": "interpreters.sustain.sustain_slot",
    "Doran's Ring": "interpreters.sustain.sustain_slot",
    "Doran's Shield": "survival.transitions.schedule_regeneration_recovery",
    "Dusk and Dawn": "damage._add_spellblade_damage",
    "Echoes of Helia": "item_support_effects.derive_item_support_effects",
    "Eclipse": "interpreters.cast_proc.cooldown_proc_effect",
    "Edge of Night": "defensive_effects.resolve_starting_defenses",
    "Frozen Heart": "roster_composition.target_overrides",
    "Rod of Ages": "item_effects.input_option_stat_bonuses",
    "Guardian Angel": "defensive_effects.resolve_starting_defenses",
    "Immortal Path": "survival.transitions.recovery_multiplier",
    "Kaenic Rookern": "defensive_effects.resolve_starting_defenses",
    "Knight's Vow": "item_support_effects.schedule_knights_vow",
    "Locket of the Iron Solari": "item_support_effects.derive_item_support_effects",
    "Mikael's Blessing": "item_support_effects.derive_item_support_effects",
    "Moonstone Renewer": "item_support_effects.derive_item_support_effects",
    "Plated Steelcaps": "defensive_effects.resolve_starting_defenses",
    "Randuin's Omen": "defensive_effects.resolve_starting_defenses",
    "Redemption": "item_support_effects.derive_item_support_effects",
    "Seeker's Armguard": "defensive_effects.resolve_starting_defenses",
    "Solstice Sleigh": "item_support_effects.derive_item_support_effects",
    "Spirit Visage": "defensive_effects.resolve_starting_defenses",
    "Sundered Sky": "damage._add_first_auto_healing",
    "Thornmail": "interpreters.reactive.thorns_effects",
    "Unending Despair": "damage._add_burn_damage",
    "Verdant Barrier": "defensive_effects.resolve_starting_defenses",
    "Warden's Mail": "defensive_effects.resolve_starting_defenses",
    "Warmog's Armor": "participant_timeline._warmog_heart_tick_events",
    "Winter's Approach": "item_effects.mana_to_health_bonus",
    "Zhonya's Hourglass": "defensive_effects.resolve_starting_defenses",
}

_TARGET_CERTIFIED_IMPLS: Mapping[str, str] = {
    "Fimbulwinter": "item_support_effects.derive_item_support_effects",
    "Force of Nature": "survival.transitions.update_combat_state",
    "Hexdrinker": "interpreters.threshold_defense._lifeline_shield",
    "Immortal Shieldbow": "interpreters.threshold_defense._lifeline_shield",
    "Jak'Sho, The Protean": "survival.transitions.update_combat_state",
    "Maw of Malmortius": "interpreters.threshold_defense._lifeline_shield",
    "Protoplasm Harness": "interpreters.threshold_defense._protoplasm",
    "Seraph's Embrace": "interpreters.threshold_defense._lifeline_shield",
    "Sterak's Gage": "interpreters.threshold_defense._lifeline_shield",
}

_UTILITY_HOMES: Mapping[str, tuple[str, str]] = {
    "Axiom Arc": (
        "item_effects.axiom_arc_ultimate_refund_fraction",
        "key:ultimate_refund_base_ratio",
    ),
    "Bandlepipes": (
        "item_support_effects.derive_item_support_effects",
        "packet:Bandlepipes — Fanfare",
    ),
    "Banshee's Veil": ("defensive_effects.resolve_starting_defenses", "effects"),
    "Boots of Swiftness": ("", "source"),
    "Cosmic Drive": ("", "source"),
    "Cull": ("item_support_effects.derive_item_support_effects", "packet:Cull — Reap"),
    "Edge of Night": ("defensive_effects.resolve_starting_defenses", "effects"),
    "Force of Nature": ("survival.transitions.update_combat_state", "effects"),
    "Frozen Heart": ("roster_composition.target_overrides", "effects"),
    "Guardian Angel": ("defensive_effects.resolve_starting_defenses", "effects"),
    "Gunmetal Greaves": ("", "source"),
    "Heartsteel": ("item_effects.item_state_receipts", "option:bonus_health"),
    "Horizon Focus": ("item_effects._resolve_damage_effects_uncached", "effects"),
    "Hubris": ("item_effects.item_state_receipts", "option:eminence_stacks"),
    "Locket of the Iron Solari": (
        "item_support_effects.derive_item_support_effects",
        "packet:Locket of the Iron Solari — Devotion",
    ),
    "Mejai's Soulstealer": ("item_effects.item_state_receipts", "option:glory_stacks"),
    "Mercurial Scimitar": ("", "source"),
    "Mikael's Blessing": (
        "item_support_effects.derive_item_support_effects",
        "packet:Mikael's Blessing — Purify",
    ),
    "Phage": (
        "item_support_effects.derive_item_support_effects",
        "packet:Phage — Rage",
    ),
    "Phantom Dancer": ("", "source"),
    "Profane Hydra": ("item_effects._resolve_damage_effects_uncached", "effects"),
    "Randuin's Omen": ("defensive_effects.resolve_starting_defenses", "effects"),
    "Rapid Firecannon": ("item_effects._resolve_damage_effects_uncached", "effects"),
    "Ravenous Hydra": ("item_effects._resolve_damage_effects_uncached", "effects"),
    "Redemption": (
        "item_support_effects.derive_item_support_effects",
        "packet:Redemption — Intervention",
    ),
    "Rod of Ages": ("item_effects.item_state_receipts", "option:timeless_stacks"),
    "Runaan's Hurricane": ("item_effects._resolve_damage_effects_uncached", "effects"),
    "Runic Compass": (
        "item_support_effects.derive_item_support_effects",
        "packet:{} — Shared Riches",
    ),
    "Rylai's Crystal Scepter": ("", "source"),
    "Serylda's Grudge": ("", "source"),
    "Shurelya's Battlesong": (
        "item_support_effects.derive_item_support_effects",
        "packet:Shurelya's Battlesong — Inspiring Speech",
    ),
    "Solstice Sleigh": (
        "item_support_effects.derive_item_support_effects",
        "packet:Solstice Sleigh — Going Sledding",
    ),
    "Statikk Shiv": ("item_effects._resolve_damage_effects_uncached", "effects"),
    "Stormrazor": ("item_effects._resolve_damage_effects_uncached", "effects"),
    "Stridebreaker": (
        "item_support_effects.derive_item_support_effects",
        "packet:Stridebreaker — Breaking Shockwave",
    ),
    "Swiftmarch": ("item_effects.swiftmarch_adaptive_force", "effects"),
    "Tear of the Goddess": (
        "item_effects.item_state_receipts",
        "option:manaflow_bonus_mana",
    ),
    "The Collector": ("item_effects._resolve_damage_effects_uncached", "effects"),
    "Titanic Hydra": ("item_effects._resolve_damage_effects_uncached", "effects"),
    "Umbral Glaive": ("", "source"),
    "World Atlas": (
        "item_support_effects.derive_item_support_effects",
        "packet:{} — Shared Riches",
    ),
    "Youmuu's Ghostblade": ("", "source"),
    "Zhonya's Hourglass": ("defensive_effects.resolve_starting_defenses", "effects"),
}
# The walk packets an item emits, the builder that emits them, and one focused
# test that exercises the behaviour.  A packet whose source the builder composes
# with an f-string is written the way the builder renders it -- ``{} — Ward``,
# not ``World Atlas — Ward`` -- because the interpolated part is not in the
# source at all and a member spelling the item name there could never resolve.  Seven more items own a walk packet and have
# no such test; they are on ``FRONTIER`` rather than here, because a claim backed
# by "some test file mentions this string" is the prose this corpus replaces.
_SUPPORT_PACKET_CLAIMS: Mapping[str, tuple[str, tuple[str, ...], str]] = {
    "Abyssal Mask": (
        "item_support_effects.derive_item_support_effects",
        ("Abyssal Mask — Unmake",),
        "tests/test_item_support_effects.py::TestAbyssalMaskOwnerHandshake"
        "::test_unmake_declares_split",
    ),
    "Ardent Censer": (
        "item_support_effects.derive_item_support_effects",
        ("Ardent Censer — Sanctify",),
        "tests/test_item_support_effects.py"
        "::test_ardent_and_moonstone_use_the_authored_heal_or_shield_target",
    ),
    "Bandlepipes": (
        "item_support_effects.derive_item_support_effects",
        ("Bandlepipes — Fanfare",),
        "tests/test_item_support_effects.py"
        "::test_cc_only_packets_require_an_authored_immobilize_marker",
    ),
    "Black Cleaver": (
        "item_support_effects.derive_item_support_effects",
        ("Black Cleaver — Carve",),
        "tests/test_item_support_effects.py"
        "::test_cross_participant_debuffs_are_typed_and_triggered_by_holder_packets",
    ),
    "Bloodletter's Curse": (
        "item_support_effects.derive_item_support_effects",
        ("Bloodletter's Curse — Vile Decay",),
        "tests/test_item_support_effects.py"
        "::test_cross_participant_debuffs_are_typed_and_triggered_by_holder_packets",
    ),
    "Bloodsong": (
        "item_support_effects.derive_item_support_effects",
        ("Bloodsong — Expose Weakness",),
        "tests/test_item_support_effects.py"
        "::test_cross_participant_debuffs_are_typed_and_triggered_by_holder_packets",
    ),
    "Cryptbloom": (
        "item_support_effects.derive_item_support_effects",
        ("Cryptbloom — Life From Death",),
        "tests/test_item_support_effects.py"
        "::test_cryptbloom_requires_an_explicit_takedown_receipt",
    ),
    "Cull": (
        "item_support_effects.derive_item_support_effects",
        ("Cull — Reap",),
        "tests/test_item_support_effects.py"
        "::test_cp20_progression_items_emit_typed_economy_vision_and_movement_receipts",
    ),
    "Dream Maker": (
        "item_support_effects.derive_item_support_effects",
        ("Dream Maker — Blue Dream Bubble",),
        "tests/test_item_support_effects.py::TestCrossParticipantAuthorities"
        "::test_dream_maker_is_a_producer",
    ),
    "Fimbulwinter": (
        "item_support_effects.derive_item_support_effects",
        ("Fimbulwinter — Everlasting",),
        "tests/test_item_support_effects.py"
        "::test_fimbulwinter_everlasting_uses_current_mana_and_nearby_enemy_multiplier",
    ),
    "Imperial Mandate": (
        "item_support_effects.derive_item_support_effects",
        ("Imperial Mandate — Command",),
        "tests/test_item_support_effects.py"
        "::test_command_requires_an_immobilize_not_a_slow",
    ),
    "Knight's Vow": (
        "item_support_effects.schedule_knights_vow",
        ("Knight's Vow — Sacrifice",),
        "tests/test_item_support_effects.py"
        "::test_knights_vow_attaches_typed_redirect_and_holder_heal_receipts",
    ),
    "Moonstone Renewer": (
        "item_support_effects.derive_item_support_effects",
        ("Moonstone Renewer — Starlit Grace",),
        "tests/test_item_support_effects.py"
        "::test_ardent_and_moonstone_use_the_authored_heal_or_shield_target",
    ),
    "Phage": (
        "item_support_effects.derive_item_support_effects",
        ("Phage — Rage",),
        "tests/test_item_support_effects.py"
        "::test_cp20_progression_items_emit_typed_economy_vision_and_movement_receipts",
    ),
    "Redemption": (
        "item_support_effects.derive_item_support_effects",
        ("Redemption — Intervention",),
        "tests/test_participant_timeline.py"
        "::test_redemption_active_emits_sourced_area_true_damage_and_heal_packets",
    ),
    "Solstice Sleigh": (
        "item_support_effects.derive_item_support_effects",
        ("Solstice Sleigh — Going Sledding",),
        "tests/test_item_support_effects.py"
        "::test_sourced_cc_packets_include_holder_movement_and_solstice_both_recipients",
    ),
    "Staff of Flowing Water": (
        "item_support_effects.derive_item_support_effects",
        ("Staff of Flowing Water — Rapids",),
        "tests/test_app.py"
        "::test_enabled_ally_staff_buff_changes_attacker_stats_and_damage",
    ),
    "World Atlas": (
        "item_support_effects.derive_item_support_effects",
        ("{} — Shared Riches", "{} — Ward"),
        "tests/test_item_support_effects.py"
        "::test_cp20_progression_items_emit_typed_economy_vision_and_movement_receipts",
    ),
}

# The five dual-sided mechanics, by holder, each with the handshake its
# packet declares.  The claim names the mechanic and the policy; the registry
# is what says both halves exist and pair back, which is the check the
# incident's hand list could not perform.  Authored rather than derived: a
# claim computed from the registry it describes would make the resolution
# check tautological, which is the failure this module exists to catch.
#
# Four are ``SPLIT`` and skip the holder, whose own pair engine prices him.
# Bloodsong is not: Phase 4 S7 gave the walk the whole mechanic — the pool of
# amplified damage is every roster attacker's — so the packet carries no
# ``owner`` and the holder is priced by the walk like everybody else.
_DUAL_SIDED_MECHANICS: Mapping[str, tuple[str, OwnerPolicy]] = {
    "Abyssal Mask": ("abyssal_mask.unmake", "owner_skips_holder"),
    "Black Cleaver": ("black_cleaver.carve", "owner_skips_holder"),
    "Bloodletter's Curse": ("bloodletters_curse.vile_decay", "owner_skips_holder"),
    "Bloodsong": ("bloodsong.expose_weakness", "holder_priced_by_walk"),
    "Imperial Mandate": ("imperial_mandate.command", "owner_skips_holder"),
}

# Which of an item's claims carries its tracked review issues.
# ``review_issue_refs`` publishes one list per item and a claim's
# ``issue_refs`` has to be that list, so exactly one claim per item may carry
# it.  *Which* one is **assembly, not evidence**: the choice asserts nothing
# about the tree, which is why it may be derived where the evidence beside it
# may not (``_corpus``).  So the lanes are ranked once here and the item's own
# lanes are read off the very containers ``_corpus`` builds its claims from —
# the same source, in the same order — which makes "exactly one carrier"
# structural rather than an answer maintained per item.  A negative claim
# carries its refs on its ``Absence`` instead, so no lane below is one.
_CLAIM_LANE_SOURCES: tuple[tuple[ClaimLane, tuple[Mapping[str, Any], ...]], ...] = (
    ("attacker", (_ATTACKER_STATE_HOMES, NO_RUNTIME_BEHAVIOR, _ISSUE_REF_ONLY_ITEMS)),
    ("target", (_TARGET_MODELED_IMPLS, _TARGET_CERTIFIED_IMPLS)),
    ("support_packet", (_SUPPORT_PACKET_CLAIMS,)),
    ("utility", (UTILITY_OUTCOMES,)),
)


def _issue_ref_lane(item: str) -> ClaimLane | None:
    """The one lane whose claim about *item* carries its review issues."""
    for lane, containers in _CLAIM_LANE_SOURCES:
        if any(item in container for container in containers):
            return lane
    return None


def _validate_issue_ref_routing() -> None:
    """Every tracked review rides a claim, or the module does not import.

    The hand table this replaced could route a ref to a lane the item had no
    claim on, and the ref would then be published by ``review_issue_refs`` and
    carried by nothing — a tracked gap with no receipt, which is the shape the
    corpus exists to make impossible.  Structural, so it belongs in the load
    tier (D-20): a set check over two module-level tables, no import and no
    ``data/`` read.
    """
    unrouted = sorted(
        item for item in _REVIEW_ISSUE_REFS if _issue_ref_lane(item) is None
    )
    if unrouted:
        raise CoverageClaimError(
            f"{unrouted} carry tracked review issues and no claim on any lane, "
            "so review_issue_refs would publish a ref no claim carries"
        )


def _test_ref(function: str, subject: str) -> TestRef:
    """The parametrized node in the claim suite that exercises *subject*.

    The node id is composed rather than written out once per claim: the
    parametrization id is the subject verbatim, so composing it keeps two
    hundred claims from carrying two hundred near-identical strings, and the
    resolver still has to find the node in what pytest actually collected.
    """
    return TestRef(node_id=f"tests/test_coverage_claims.py::{function}[{subject}]")


def _source_ref(item: str) -> SourceRef:
    """The wiki revision the item's full-entry review was read from."""
    url, revision_id = _SOURCE_REFS[item]
    return SourceRef(url=url, revision_id=revision_id)


def _state_home(item: str, home: str) -> Evidence:
    """The member naming where a ``modeled_state`` claim's state comes from.

    Three spellings, one per route the classifier reaches that status by: an
    ``option:`` control, a ``packet:`` the ledger schedules, or a ``key:`` the
    engine reads out of the registry.
    """
    kind, _, value = home.partition(":")
    if kind == "option":
        return OptionSchema(item=item, option=value)
    if kind == "packet":
        return PacketSource(source=value)
    return EffectKey(registry="ITEM_EFFECTS", item=item, key=value)


def _issue_refs(item: str, lane: ClaimLane) -> tuple[int, ...]:
    """The tracked review issues, on the one lane derived to carry them."""
    if item not in _REVIEW_ISSUE_REFS or _issue_ref_lane(item) != lane:
        return ()
    return tuple(_REVIEW_ISSUE_REFS[item])


def _attacker_state_claim(item: str) -> Claim:
    """One stateful item: the state, and the named home it comes from."""
    path, home = _ATTACKER_STATE_HOMES[item]
    role: SymbolRole = (
        "walk_packet_builder" if home.startswith("packet:") else "value_accessor"
    )
    return Claim(
        subject_kind="item",
        subject=item,
        lane="attacker",
        status="modeled_state",
        evidence=(
            Symbol(path=path, role=role),
            _state_home(item, home),
            _test_ref(
                "test_a_stateful_item_supplies_its_state_from_a_named_home", item
            ),
        ),
        dimensions=(),
        issue_refs=_issue_refs(item, "attacker"),
    )


def _stats_only_claim(item: str) -> Claim:
    """One ``NO_RUNTIME_BEHAVIOR`` entry: a review, and the revision it read."""
    return Claim(
        subject_kind="item",
        subject=item,
        lane="attacker",
        status="stats_only",
        evidence=(
            _source_ref(item),
            _test_ref("test_a_reviewed_stats_only_item_adds_no_outgoing_damage", item),
        ),
        dimensions=(),
        issue_refs=_issue_refs(item, "attacker"),
    )


def _item_effects_claim(item: str) -> Claim:
    """An ``ITEM_EFFECTS`` member whose refs need a home of their own."""
    return Claim(
        subject_kind="item",
        subject=item,
        lane="attacker",
        status=_ISSUE_REF_ONLY_ITEMS[item],
        evidence=(
            Symbol(
                path="item_effects._resolve_damage_effects_uncached", role="tag_handler"
            ),
            _test_ref(
                "test_an_item_effects_member_names_a_dispatched_or_frontiered_tag", item
            ),
            # A state answer is the stricter claim and carries both the
            # accessor that folds the state in and the registry key it reads:
            # an item lands on that rung because it declares a stat
            # derivation, and ``resolve_stat_effects`` sums ``ultimate_haste``
            # into the build's block from that key.
            *(
                (
                    Symbol(
                        path="item_effects.resolve_stat_effects",
                        role="value_accessor",
                    ),
                    EffectKey(registry="ITEM_EFFECTS", item=item, key="ultimate_haste"),
                )
                if _ISSUE_REF_ONLY_ITEMS[item] == "modeled_state"
                else ()
            ),
        ),
        dimensions=(),
        issue_refs=_issue_refs(item, "attacker"),
    )


def _target_modeled_claim(item: str) -> Claim:
    """One derived target-modelled item and the code that admits it."""
    return Claim(
        subject_kind="item",
        subject=item,
        lane="target",
        status="modeled",
        evidence=(
            Symbol(path=_TARGET_MODELED_IMPLS[item], role="walk_packet_builder"),
            _test_ref(
                "test_a_target_modeled_item_is_admitted_by_the_target_model", item
            ),
        ),
        dimensions=(),
        issue_refs=_issue_refs(item, "target"),
    )


def _target_certified_claim(item: str) -> Claim:
    """One conditional defense, plus the guard that withholds an uncertified fight."""
    return Claim(
        subject_kind="item",
        subject=item,
        lane="target",
        status="modeled_event_certified",
        evidence=(
            Symbol(path=_TARGET_CERTIFIED_IMPLS[item], role="walk_packet_builder"),
            Symbol(
                path="item_coverage.require_certified_target_timeline",
                role="certification_guard",
            ),
            _test_ref(
                "test_a_target_event_certified_item_needs_a_certified_timeline", item
            ),
        ),
        dimensions=(),
        issue_refs=_issue_refs(item, "target"),
    )


def _utility_claim(item: str) -> Claim:
    """One ``UTILITY_OUTCOMES`` entry and the home of what the model prices.

    A utility claim is about outcome *dimensions*, and the model prices some
    of them and none of others.  ``modeled_effect`` and ``modeled_state`` name
    the home of the dimension it does price; ``stats_only`` is the honest
    answer where it prices none of them, and then the claim cites the review
    that says so rather than pointing at code that is about something else.
    """
    path, home = _UTILITY_HOMES[item]
    dimensions = tuple(dimension.value for dimension in UTILITY_OUTCOMES[item])
    node = _test_ref("test_a_utility_item_publishes_its_declared_dimensions", item)
    refs = _issue_refs(item, "utility")
    if home == "source":
        return Claim(
            subject_kind="item",
            subject=item,
            lane="utility",
            status="stats_only",
            evidence=(_source_ref(item), node),
            dimensions=dimensions,
            issue_refs=refs,
        )
    if home == "effects":
        return Claim(
            subject_kind="item",
            subject=item,
            lane="utility",
            status="modeled_effect",
            evidence=(Symbol(path=path, role="tag_handler"), node),
            dimensions=dimensions,
            issue_refs=refs,
        )
    role: SymbolRole = (
        "walk_packet_builder" if home.startswith("packet:") else "value_accessor"
    )
    return Claim(
        subject_kind="item",
        subject=item,
        lane="utility",
        status="modeled_state",
        evidence=(
            Symbol(path=path, role=role),
            _state_home(item, home),
            node,
        ),
        dimensions=dimensions,
        issue_refs=refs,
    )


def _support_packet_claim(item: str) -> Claim:
    """One holder's walk packets, its builder, and its dual-sided handshake."""
    impl, packets, node_id = _SUPPORT_PACKET_CLAIMS[item]
    declared = _DUAL_SIDED_MECHANICS.get(item)
    sides = (
        (PairedSides(mechanic=declared[0], owner_policy=declared[1]),)
        if declared
        else ()
    )
    return Claim(
        subject_kind="item",
        subject=item,
        lane="support_packet",
        status="modeled_effect",
        evidence=(
            Symbol(path=impl, role="walk_packet_builder"),
            *(PacketSource(source=packet) for packet in packets),
            *sides,
            TestRef(node_id=node_id),
        ),
        dimensions=(),
        issue_refs=(),
    )


def _corpus() -> dict[tuple[SubjectKind, str, ClaimLane], Claim]:
    """Every claim, keyed the way the load gate reads it.

    Built once at import from the tables above.  The *evidence* is authored --
    a table that derived its own evidence from the registries it describes
    would agree with them by construction, which is the failure this module
    exists to catch -- and only the assembly is mechanical.
    """
    _validate_issue_ref_routing()
    claims = [
        *(_attacker_state_claim(item) for item in _ATTACKER_STATE_HOMES),
        *(_stats_only_claim(item) for item in NO_RUNTIME_BEHAVIOR),
        *(_item_effects_claim(item) for item in _ISSUE_REF_ONLY_ITEMS),
        *(_target_modeled_claim(item) for item in _TARGET_MODELED_IMPLS),
        *(_target_certified_claim(item) for item in _TARGET_CERTIFIED_IMPLS),
        *(_utility_claim(item) for item in UTILITY_OUTCOMES),
        *(_support_packet_claim(item) for item in _SUPPORT_PACKET_CLAIMS),
    ]
    return {(claim.subject_kind, claim.subject, claim.lane): claim for claim in claims}


COVERAGE_EVIDENCE: Mapping[tuple[SubjectKind, str, ClaimLane], Claim] = _corpus()

# Claim key -> why it is not backed yet.  It shrinks by edit and never grows:
# a new member arrives only with the reason it cannot be a claim, and every
# reason carries the issue that tracks it.
#
# Three key shapes: ``item:<name>@<lane>`` is a claim nobody may file yet,
# ``tag:<name>`` an effect tag with no live handler, and ``packet:<source>``
# one walk packet of an item whose claim exists but does not reach that
# packet.  The third exists because ``PacketSource`` proves only that a
# quoted packet is emitted; the totality check
# (``coverage_resolver.unquoted_packet_sources``) asks the other direction --
# every literal the builder emits is quoted by a claim or withheld here --
# and a per-item key cannot answer it for an item that is already claimed.
#
# No attacker or target key may appear here at all.  The rule is that a
# frontier which can absorb a damage or durability claim is the escape hatch
# this campaign closes, and "no such lane, ever" is the version of that rule a
# test can check without deciding what "prices damage" means.
FRONTIER: Mapping[str, str] = {
    "item:Diadem of Songs@support_packet": (
        "Consonance emits a walk packet no focused test exercises; #48 tracks "
        "the support-item authoring debt."
    ),
    "item:Echoes of Helia@support_packet": (
        "Soul Siphon emits a walk packet no focused test exercises; #48 tracks "
        "the support-item authoring debt."
    ),
    "item:Locket of the Iron Solari@support_packet": (
        "Devotion emits a walk packet no focused test exercises; #46 and #48 "
        "track the shield and the support-item authoring debt."
    ),
    "item:Mikael's Blessing@support_packet": (
        "Purify emits a walk packet no focused test exercises; #48 tracks the "
        "support-item authoring debt."
    ),
    "item:Runic Compass@support_packet": (
        "Shared Riches and Ward emit walk packets no focused test exercises; "
        "#40 tracks the review."
    ),
    "item:Shurelya's Battlesong@support_packet": (
        "Inspiring Speech emits a walk packet no focused test exercises; #40 "
        "tracks the review."
    ),
    "item:Stridebreaker@support_packet": (
        "Breaking Shockwave emits a walk packet no focused test exercises; #43 "
        "tracks the multi-target authoring debt."
    ),
    "packet:Dream Maker — Purple Dream Bubble": (
        "Dream Maker's second walk packet: the item's support_packet claim "
        "quotes Blue Dream Bubble, and the Purple bubble's magic on-hit is "
        "exercised by no focused test; #48 tracks the support-item authoring "
        "debt."
    ),
}

validate_claim_table(COVERAGE_EVIDENCE)

__all__ = [
    "ATTACKER_LANES",
    "COVERAGE_EVIDENCE",
    "FRONTIER",
    "ItemCoverage",
    "NO_RUNTIME_BEHAVIOR",
    "SCORING_LANES",
    "item_model_coverage",
    "optimizer_candidate_coverage",
    "optimizer_supported_items",
    "require_calculation_item_coverage",
    "require_certified_target_timeline",
    "require_optimizer_item_coverage",
    "require_target_item_coverage",
    "review_issue_refs",
    "target_build_coverage",
    "target_item_model_coverage",
]
