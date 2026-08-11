"""Item and keystone behaviour as a closed union of frozen declarations.

The campaign's diagnosis was that behaviour lived as code scattered across
engines, and coverage lived as prose describing that code.  Neither can be
checked against the other.  This module is the replacement vocabulary: a
:class:`BehaviorRule` is one mechanic, declared once, in a closed family, with
its numbers held as references (``value_ref``), its provenance held as a
receipt, and its legal-zero story declared rather than assumed.  What a
declaration cannot say is as load-bearing as what it can — an undeclared
behaviour is withheld with a named receipt, never priced as zero.

**This module is a leaf.**  It imports ``value_ref`` and ``ability_spec`` and
nothing else, so ``damage.py``, ``survival/*``, ``defensive_effects.py`` and
``item_support_effects.py`` may all depend on it without a cycle.  Two
consequences are deliberate and worth stating, because both look like
duplication until the constraint is remembered:

* :class:`TriggerEvent` is a local closed enum rather than a re-export of
  ``trigger_stream``'s ``Stream``.  It is not a second vocabulary: every
  member declares the stream it reads in :data:`TRIGGER_STREAM`, and
  ``tests/test_item_behavior.py`` asserts that projection lands inside
  ``Stream``'s own member names.
* :class:`KernelField` and :class:`BuildContext` — the ``interpreters/`` →
  ``survival/`` contract — live here, because this is the one module both
  packages may import and a name in a cross-package signature needs a home.

Naming: the unit is a **rule**, never an "atom" (D-44).  ``atomizer.Atom``,
``atomizer_domains`` and ``rotation_resolver``'s apply-atom keys are three
live meanings of that word already.
"""

from __future__ import annotations

from dataclasses import dataclass, fields as dataclass_fields, is_dataclass
from enum import Enum
from typing import NamedTuple, Union

from .ability_spec import (
    AttackClass,
    Authority,
    DamageClass,
    Disposition,
    ZeroPolicy,
)
from .value_ref import AnyValueRef, SourceReceipt, VALUE_REF_TYPES


class BehaviorRuleError(ValueError):
    """A declaration is structurally impossible — checked without imports."""


# ── lanes and families ────────────────────────────────────────────────────


class EngineLane(Enum):
    """The engines a declared behaviour may have to be interpreted by.

    Phase 1 exports ``ClaimLane`` and this phase exports ``EngineLane``
    (D-45): two lane vocabularies answering different questions must never
    both be spelled ``Lane``.  A claim lane says *who is claiming coverage*;
    an engine lane says *which engine has to run the rule*.
    """

    PAIR_ENGINE = "pair_engine"
    RECEIPT_WALK = "receipt_walk"
    COMPILED_SCORE_WALK = "compiled_score_walk"
    DEFENSE_RESOLVER = "defense_resolver"
    STAT_RESOLVER = "stat_resolver"


class RuleFamily(Enum):
    """The closed set of shapes an item or keystone behaviour can have.

    Closed at eighteen, and closure is a test rather than a convention: a new
    ``item_effects._KNOWN_EFFECT_TYPES`` member, a new ``ActionKind`` or a new
    ``DefenseSource`` construction fails collection until it is mapped
    (``item_behavior_catalog.validate_catalog``).  The four groups below are
    the reason the union is closable at all — every mechanic in the registry
    is a strike, a pricing rule, a defence, or one of the three that are
    none of those.
    """

    # strike — something happens when a hit or a cast lands
    ON_HIT_STRIKE = "on_hit_strike"
    CHARGED_STRIKE = "charged_strike"
    SPELLBLADE = "spellblade"
    CAST_PROC = "cast_proc"
    PERIODIC = "periodic"
    ACTIVE_CAST = "active_cast"
    SECONDARY_TARGET = "secondary_target"
    # pricing — the damage number itself is changed
    DELTA_AMP = "delta_amp"
    RESISTANCE_SHRED = "resistance_shred"
    CRIT_PROFILE = "crit_profile"
    DAMAGE_ROUTING = "damage_routing"
    # defence — the subject survives differently
    OPENING_DEFENSE = "opening_defense"
    THRESHOLD_DEFENSE = "threshold_defense"
    COMBAT_STATE = "combat_state"
    REACTIVE = "reactive"
    # rest
    SUSTAIN = "sustain"
    STAT_DERIVATION = "stat_derivation"
    ALLY_PACKET = "ally_packet"


RULE_FAMILY_COUNT = 18


# ── compilability (D-43) ──────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Compilable:
    """The compiled score kernel can represent this rule."""


@dataclass(frozen=True, slots=True)
class ReceiptOnly:
    """The compiled kernel cannot represent this rule, and here is why.

    ``reason`` is a citation, not policy: it is the sentence a fallback
    receipt prints when a build holding this rule declines to compile.
    """

    reason: str

    def __post_init__(self) -> None:
        """A fallback with no stated cause is the silence this phase removes."""
        if not self.reason.strip():
            raise BehaviorRuleError("ReceiptOnly needs a reason")


Compilability = Union[Compilable, ReceiptOnly]

COMPILABILITY_TYPES: tuple[type, ...] = (Compilable, ReceiptOnly)


# ── triggers ──────────────────────────────────────────────────────────────


class TriggerEvent(Enum):
    """What arms or gates a rule's window.

    Local to this leaf by necessity (see the module docstring) and joined to
    the trigger bus by :data:`TRIGGER_STREAM`.
    """

    IMMOBILIZE = "immobilize"
    ANY_CROWD_CONTROL = "any_crowd_control"
    CHAMPION_DAMAGE = "champion_damage"
    ABILITY_HIT = "ability_hit"
    BASIC_ATTACK_HIT = "basic_attack_hit"
    TAKEDOWN = "takedown"
    SUPPORT_TRIGGER = "support_trigger"


# Which bus stream each trigger reads.  The values are ``trigger_stream``
# ``Stream`` member *names*; the projection is asserted against the enum in
# the test front door, which is what keeps this from being a second
# vocabulary rather than a view of the one that exists.
TRIGGER_STREAM: dict[TriggerEvent, str] = {
    TriggerEvent.IMMOBILIZE: "CC",
    TriggerEvent.ANY_CROWD_CONTROL: "CC",
    TriggerEvent.CHAMPION_DAMAGE: "DAMAGE",
    TriggerEvent.ABILITY_HIT: "DAMAGE",
    TriggerEvent.BASIC_ATTACK_HIT: "DAMAGE",
    TriggerEvent.TAKEDOWN: "TAKEDOWN",
    TriggerEvent.SUPPORT_TRIGGER: "SUPPORT_TRIGGER",
}


class WindowMerge(Enum):
    """What a second trigger does to a window the first one already opened."""

    EXTEND = "extend"
    REFRESH = "refresh"
    INDEPENDENT = "independent"


class WindowBoundary(Enum):
    """Whether an event exactly on a window's end is inside it (D-13)."""

    OPEN_CLOSED = "open_closed"
    CLOSED_CLOSED = "closed_closed"


class Isolation(Enum):
    """What an exclusion rule excludes.

    ``TRIGGER_SEQUENCE`` is wider than the other two on purpose: some buffs
    are armed by a *chain* of events — Bloodsong's Expose Weakness needs an
    ability cast, then the attack that consumes it, then the empowered proc —
    and everything in that chain lands before the buff is up.  Calling that
    "the trigger event" or "the trigger ability" would understate the
    exclusion by two events, and an amp priced over two events it should not
    have seen is a wrong number nobody could read off the declaration.
    """

    TRIGGER_ABILITY_ONLY = "trigger_ability_only"
    TRIGGER_EVENT_ONLY = "trigger_event_only"
    TRIGGER_SEQUENCE = "trigger_sequence"


class Probe(Enum):
    """A live pool a predicate may read mid-simulation."""

    TARGET_HEALTH_FRACTION = "target_health_fraction"
    HOLDER_HEALTH_FRACTION = "holder_health_fraction"


class Comparison(Enum):
    """How a live probe is compared against its threshold."""

    LT = "lt"
    LE = "le"
    GT = "gt"
    GE = "ge"


@dataclass(frozen=True, slots=True)
class Always:
    """The rule is armed for the whole fight."""


@dataclass(frozen=True, slots=True)
class AbsoluteWindow:
    """The rule is armed between two fixed times."""

    start: AnyValueRef
    end: AnyValueRef


@dataclass(frozen=True, slots=True)
class TriggerWindow:
    """A trigger opens a window of declared duration."""

    trigger: TriggerEvent
    duration: AnyValueRef
    merge: WindowMerge
    boundary: WindowBoundary


@dataclass(frozen=True, slots=True)
class AfterTrigger:
    """The rule applies to events after a trigger, with no window end."""

    trigger: TriggerEvent
    strict: bool


@dataclass(frozen=True, slots=True)
class ExcludeTrigger:
    """The rule applies to everything *except* the triggering event."""

    trigger: TriggerEvent
    isolation: Isolation


@dataclass(frozen=True, slots=True)
class LivePredicate:
    """A condition on a pool that only exists mid-simulation.

    Shadowflame's Cinderbloom is the one amp whose pool cannot be
    precomputed: it reads the target's live health at the moment of the hit.
    Forcing it into a window would make the algebra claim a certainty the
    mechanic does not have, so it gets its own activation shape and
    ``requires_live_pool`` is a property of that shape rather than a flag a
    caller may forget.
    """

    probe: Probe
    cmp: Comparison
    threshold: AnyValueRef

    @property
    def requires_live_pool(self) -> bool:
        """Always true — the field exists so interpreters can branch on it."""
        return True


Activation = Union[
    Always,
    AbsoluteWindow,
    TriggerWindow,
    AfterTrigger,
    ExcludeTrigger,
    LivePredicate,
]

ACTIVATION_TYPES: tuple[type, ...] = (
    Always,
    AbsoluteWindow,
    TriggerWindow,
    AfterTrigger,
    ExcludeTrigger,
    LivePredicate,
)


# ── consumption (Dream Maker's axis) ──────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Persist:
    """The rule stays armed for its whole activation."""


@dataclass(frozen=True, slots=True)
class NextEventOnly:
    """The rule is spent by the first event it applies to.

    Dream Maker's Blue Dream Bubble is the reason this axis exists at all:
    it is expressible in no activation shape without it.
    """


@dataclass(frozen=True, slots=True)
class NEvents:
    """The rule is spent after a declared number of events."""

    count: AnyValueRef


Consumption = Union[Persist, NextEventOnly, NEvents]

CONSUMPTION_TYPES: tuple[type, ...] = (Persist, NextEventOnly, NEvents)


# ── magnitude ─────────────────────────────────────────────────────────────


class RampModel(Enum):
    """How a per-stack ramp is summed.

    ``CESARO_APPROX`` is the closed-form average the pair engine already
    uses for Black Cleaver's Carve.  ``docs/math-foundations.md`` §2.3 calls
    re-tuning it a balance change, so this phase makes it *visible* and
    changes nothing about it.
    """

    EXACT = "exact"
    CESARO_APPROX = "cesaro_approx"


@dataclass(frozen=True, slots=True)
class Fixed:
    """One magnitude, constant for the rule's whole activation."""

    value: AnyValueRef


@dataclass(frozen=True, slots=True)
class RampPerSecond:
    """A magnitude that grows with time in the window, up to a cap.

    The value a fight sees is the ramp's *average* over the time it was
    building, not its end point — the closed form the pair engine has always
    used for this schema.  Both numbers are references, so a patch that
    re-tunes either moves the fight without touching a declaration.
    """

    per_second: AnyValueRef
    maximum: AnyValueRef


@dataclass(frozen=True, slots=True)
class TargetBonusHealthScaled:
    """A magnitude that reaches ``maximum`` at ``bonus_health_cap``.

    Two fields, not three: the live schema has no additive base, and a
    declared ``base`` of zero would be a number nobody sourced sitting in a
    frozen declaration.  The scaling is on the *target's* bonus health, never
    the holder's — the distinction the registry's own accessor carried in its
    signature and this shape carries in its name.
    """

    maximum: AnyValueRef
    bonus_health_cap: AnyValueRef


@dataclass(frozen=True, slots=True)
class RampPerStack:
    """A magnitude that grows per stack, summed by a declared model.

    ``seconds_per_stack`` is the engine's assumed cadence for a stack the
    fight model does not simulate individually.  It is declared rather than
    hidden inside the arithmetic because it is an *assumption*, and an
    assumption a reader cannot see is the prose this phase replaces.
    """

    per_stack: AnyValueRef
    max_stacks: AnyValueRef
    seconds_per_stack: AnyValueRef
    model: RampModel


@dataclass(frozen=True, slots=True)
class MeleeRangedSplit:
    """Two sourced magnitudes, chosen by the holder's own range class.

    A handful of registry schemas pay a melee holder more than a ranged one
    — Bloodsong's Expose Weakness is 8% against 5% — and that choice is made
    once per build, from a stat, before any event exists.  It is a magnitude
    question rather than a typing one: ``Typing.attack_classes`` says how a
    *number was delivered*, which is a property of the damage and not of the
    champion holding the item.

    Both references are required.  A schema that supplied one and defaulted
    the other would price a whole class of holders at zero with nothing in
    the declaration saying so.
    """

    melee: AnyValueRef
    ranged: AnyValueRef


Magnitude = Union[
    Fixed,
    RampPerSecond,
    TargetBonusHealthScaled,
    RampPerStack,
    MeleeRangedSplit,
]

MAGNITUDE_TYPES: tuple[type, ...] = (
    Fixed,
    RampPerSecond,
    TargetBonusHealthScaled,
    RampPerStack,
    MeleeRangedSplit,
)


# ── the remaining policy axes ─────────────────────────────────────────────


class Pool(Enum):
    """Which events a rule is allowed to price."""

    ALL_EVENTS = "all_events"
    CERTIFIED_ONLY = "certified_only"
    COARSE_ROW = "coarse_row"
    OWN_CAST_ONLY = "own_cast_only"


class Attribution(Enum):
    """Who the rule's contribution is credited to in the receipt."""

    HOLDER = "holder"
    DAMAGE_SOURCE = "damage_source"


class BonusTyping(Enum):
    """What damage type an amplifier's own bonus lands as.

    A separate question from :class:`Typing`, which says which events a rule
    is allowed to price.  Most amps hand back more of what they amplified;
    First Strike hands back true damage whatever it amplified, and that
    difference lived as a hard-coded ``"damage_type": "true"`` inside one
    engine function where no declaration could see it.
    """

    SAME_AS_SOURCE = "same_as_source"
    TRUE = "true"


class Subject(Enum):
    """Whose numbers the rule acts on.

    The roster-scoped members are what make an authority claim checkable:
    a rule reading any roster attacker cannot belong to a ``PAIR_ONLY``
    mechanic, and :data:`SUBJECT_AUTHORITY` is where that is stated.
    """

    HOLDER = "holder"
    TARGET = "target"
    ALLY = "ally"
    ANY_ATTACKER = "any_attacker"


# Which authorities each subject is compatible with.  A pair-local subject
# is compatible with every authority; a roster-scoped one is compatible with
# none of the pair-local ones, because the pair engine cannot see it.
SUBJECT_AUTHORITY: dict[Subject, frozenset[Authority]] = {
    Subject.HOLDER: frozenset(Authority),
    Subject.TARGET: frozenset(Authority),
    Subject.ALLY: frozenset(Authority) - {Authority.PAIR_ONLY},
    Subject.ANY_ATTACKER: frozenset(Authority) - {Authority.PAIR_ONLY},
}


@dataclass(frozen=True, slots=True)
class Typing:
    """The damage restriction a rule applies under (D-04).

    Both sets are required and neither may be empty: "empty means all" is a
    silent default in a campaign whose thesis is that silent defaults kill,
    and ``attack_classes`` is the only place "from all sources" becomes
    something a declaration *says* rather than something it omits.

    It is a record rather than an enum for exactly that reason — the ruling
    fixes two frozensets, and no single enum member can carry both.
    """

    damage_classes: frozenset[DamageClass]
    attack_classes: frozenset[AttackClass]

    def __post_init__(self) -> None:
        """Reject the empty-means-all spelling D-04 bans."""
        if not self.damage_classes:
            raise BehaviorRuleError(
                "Typing.damage_classes must name every class the rule applies "
                "to; empty-means-all is banned (D-04)"
            )
        if not self.attack_classes:
            raise BehaviorRuleError(
                "Typing.attack_classes must name every class the rule applies "
                "to; empty-means-all is banned (D-04)"
            )


# ``ZeroPolicy`` is re-exported from ``ability_spec``: the champion entry
# builders declare one too, and they cannot import this module without
# inverting the vocabulary leaf's dependency direction (D-24).


# ── payloads ──────────────────────────────────────────────────────────────


class AmpChainSlot(Enum):
    """The seven ordered positions of the damage-amplifier chain.

    Amplification is not commutative: each slot multiplies a total the
    slots before it already moved, so the order *is* part of every mixed
    build's number.  Today that order is an accident of the call sequence in
    ``damage.py`` and nothing stops a refactor changing it.  Naming the seven
    positions makes the order a declaration, and
    :func:`chain_rank` is the only place a rule's ``lane_chain_rank`` comes
    from.

    A slot is a *position*, not a mechanic: several mechanics share
    ``WHOLE_TOTAL``, which is the one slot whose occupants are additive among
    themselves before the chain multiplies.  These seven are also **not**
    Phase 4's seven authority moves — the two sets overlap and neither
    contains the other.
    """

    CINDERBLOOM = "cinderbloom"
    EXPOSE_WEAKNESS = "expose_weakness"
    OPENING_WINDOW = "opening_window"
    LASTING_PROC_AMP = "lasting_proc_amp"
    WHOLE_TOTAL = "whole_total"
    POST_IMMOBILIZE = "post_immobilize"
    HYPERSHOT = "hypershot"


# The compiled sequence, frozen.  Declared as its own tuple rather than
# derived from the enum's declaration order: a tuple somebody can diff is the
# artifact a reordering shows up in, and ``tuple(AmpChainSlot)`` would pin
# nothing because it is true by construction.
AMP_CHAIN_ORDER: tuple[AmpChainSlot, ...] = (
    AmpChainSlot.CINDERBLOOM,
    AmpChainSlot.EXPOSE_WEAKNESS,
    AmpChainSlot.OPENING_WINDOW,
    AmpChainSlot.LASTING_PROC_AMP,
    AmpChainSlot.WHOLE_TOTAL,
    AmpChainSlot.POST_IMMOBILIZE,
    AmpChainSlot.HYPERSHOT,
)


def chain_rank(slot: AmpChainSlot) -> int:
    """*slot*'s position in the chain — the value ``lane_chain_rank`` carries."""
    return AMP_CHAIN_ORDER.index(slot)


def _validate_amp_chain() -> None:
    """The chain names every slot exactly once, checked at import."""
    if len(AMP_CHAIN_ORDER) != len(frozenset(AMP_CHAIN_ORDER)):
        raise BehaviorRuleError("AMP_CHAIN_ORDER holds a slot twice")
    if frozenset(AMP_CHAIN_ORDER) != frozenset(AmpChainSlot):
        missing = sorted(
            slot.value for slot in frozenset(AmpChainSlot) - frozenset(AMP_CHAIN_ORDER)
        )
        raise BehaviorRuleError(f"AMP_CHAIN_ORDER omits chain slots: {missing}")


_validate_amp_chain()


class Basis(Enum):
    """What one term of a damage formula is a share *of*.

    A strike's number is always a sum of shares: so much flat, so much of the
    holder's ability power, so much of the target's current health.  The
    registry has always said which by naming a formula — ``"flat_bonus_ad_ap"``
    — a string whose meaning lived in one ladder inside the number registry
    and nowhere else.  Naming the *bases* instead makes the vocabulary a
    dozen closed members rather than twenty-odd formula names, and makes a
    new schema a new combination instead of a new branch.

    The holder/target split is in the member names deliberately: a share of
    "max health" is a completely different mechanic depending on whose, and
    the registry's own key names could not say which.
    """

    FLAT = "flat"
    ABILITY_POWER = "ability_power"
    BASE_ATTACK_DAMAGE = "base_attack_damage"
    BONUS_ATTACK_DAMAGE = "bonus_attack_damage"
    TOTAL_ATTACK_DAMAGE = "total_attack_damage"
    LETHALITY = "lethality"
    HOLDER_MAX_HEALTH = "holder_max_health"
    HOLDER_MAX_MANA = "holder_max_mana"
    HOLDER_CRIT_FRACTION = "holder_crit_fraction"
    HOLDER_BONUS_HEALTH = "holder_bonus_health"
    TARGET_MAX_HEALTH = "target_max_health"
    TARGET_CURRENT_HEALTH = "target_current_health"
    TARGET_MISSING_HEALTH = "target_missing_health"
    PER_LEVEL = "per_level"


@dataclass(frozen=True, slots=True)
class Term:
    """One share of one basis: ``coefficient × basis``.

    ``coefficient`` is a sourced reference, or a :class:`MeleeRangedSplit`
    where the registry pays a melee holder differently — the same shape the
    amp chain uses, and for the same reason: the choice is made once per
    build from a stat, before any event exists.
    """

    coefficient: Union[AnyValueRef, MeleeRangedSplit]
    basis: Basis


@dataclass(frozen=True, slots=True)
class NoFloor:
    """The formula's sum stands as computed."""


@dataclass(frozen=True, slots=True)
class AtLeast:
    """The formula never pays less than a sourced minimum."""

    value: AnyValueRef


Floor = Union[NoFloor, AtLeast]

FLOOR_TYPES: tuple[type, ...] = (NoFloor, AtLeast)


@dataclass(frozen=True, slots=True)
class DamageFormula:
    """A sum of sourced shares, floored, landing as one damage class.

    Every strike family's number is one of these.  The union of *terms* is
    what replaces the registry's formula-name ladder, and ``floor`` is its own
    axis because "at least this much" is a mechanic (Blade of the Ruined
    King's minimum) rather than a term.
    """

    terms: tuple[Term, ...]
    floor: Floor
    damage_class: DamageClass

    def __post_init__(self) -> None:
        """A formula with no terms is a number nobody declared."""
        if not self.terms:
            raise BehaviorRuleError(
                "a DamageFormula names at least one term; a formula with no "
                "shares is an item that quietly deals nothing"
            )
        if not isinstance(self.floor, FLOOR_TYPES):
            raise BehaviorRuleError("a DamageFormula declares its floor")
        if not isinstance(self.damage_class, DamageClass):
            raise BehaviorRuleError("a DamageFormula declares what mitigates it")


@dataclass(frozen=True, slots=True)
class OnHitStrikeRule:
    """Damage added to every on-hit application of a basic attack.

    ``superseded_by_ability_proc`` is the Wiki's no-double-dip rule for items
    that *also* pay per ability hit: an ability that applies on-hit effects
    deals the ability-hit number instead of the on-hit one, never both.  It is
    a policy of the mechanic, so it is declared rather than inferred from the
    presence of a sibling key.
    """

    formula: DamageFormula
    superseded_by_ability_proc: bool


@dataclass(frozen=True, slots=True)
class SecondaryTargetRule:
    """A strike that also lands on targets the attack was not aimed at.

    The bolts are declared as a count and a share, not as a damage formula of
    their own: the number they carry is a share of *the attack that fired
    them*, which is why this family is separate from the strike families that
    own a formula.
    """

    max_targets: AnyValueRef
    damage_share: AnyValueRef
    applies_on_hit: bool


class Resistance(Enum):
    """Which of the target's two resistances a shred reduces.

    True damage has no resistance to reduce, which is why this is a
    two-member enum rather than a projection of :class:`DamageClass`: the
    question "what does this shred" and the question "what mitigates this
    number" have different answer sets, and collapsing them would make a
    true-damage shred expressible.
    """

    ARMOR = "armor"
    MAGIC_RESIST = "magic_resist"


@dataclass(frozen=True, slots=True)
class StackRamp:
    """A per-stack reduction accrued by a declared event, capped and summed.

    Four axes, because a stacking shred really does answer four separate
    questions and the engines answered them in four unrelated places: how
    deep one stack cuts (``per_stack``), how many can be held
    (``max_stacks``), what applies one (``accrual``), and how the fight's
    stack history is summed into one number (``model``).

    ``leading_stacks`` is the fifth and is an **assumption**, not a wiki
    number: an engine that counts only one event stream still has to say what
    it believes happened before that stream started.  Black Cleaver's pair
    model assumes four ability hits precede the auto stream, and that belief
    lived as a ``+ 4`` inside the arithmetic where no reader could challenge
    it.  A rule that counts every applying event exactly declares zero.
    """

    per_stack: AnyValueRef
    max_stacks: AnyValueRef
    accrual: TriggerEvent
    leading_stacks: AnyValueRef
    model: RampModel


@dataclass(frozen=True, slots=True)
class ResistanceShredRule:
    """One stacking resistance reduction: what it cuts, on what, how deep.

    Reduction is not penetration.  A shred moves the *target's* resistance
    before penetration is applied and may take it negative, which is why the
    subject is the target and why this is its own family rather than a
    magnitude on somebody's damage.  ``typing`` says which damage applies a
    stack — Vile Decay reads magic damage only — and is the declaration's
    answer to a comparison that used to live inside the rotation loop.
    """

    resistance: Resistance
    ramp: StackRamp
    typing: Typing
    subject: Subject


@dataclass(frozen=True, slots=True)
class DeltaAmpRule:  # pylint: disable=too-many-instance-attributes
    """One amplification slot: which events, when, how much, and to whom.

    Nine fields because the amp chain has nine independent questions and
    collapsing any two of them is what let a pair-side preview and a coupled
    number both call themselves the answer.  ``lane_chain_rank`` is an
    explicit integer: the seven chain slots are ordered, nothing in the
    engine stops a refactor reordering them, and every mixed build's number
    moves when they do.  It is :func:`chain_rank` of the rule's
    :class:`AmpChainSlot` and is validated against the chain's length.
    ``typing`` says which events the rule may price and ``bonus_typing`` what
    its own bonus lands as — one amp really does answer those differently.
    """

    pool: Pool
    activation: Activation
    consumption: Consumption
    magnitude: Magnitude
    attribution: Attribution
    typing: Typing
    bonus_typing: BonusTyping
    subject: Subject
    lane_chain_rank: int


class AllyProducer(Enum):
    """The closed set of cross-participant packet producers.

    An ally packet is the one family whose mechanics share no arithmetic:
    Redemption heals a radius and Phage grants move speed, and nothing but
    the *shape of the emission* is common to them.  So the family's policy is
    "which producer is this, what does it emit, to whom, and when" — and this
    enum is the first of those four.

    It is deliberately **not** an item name.  A member's value is the *effect*
    half of the mechanic id Phase 2's capability registry already uses, and
    which registry entry carries it is decided by that entry's own value keys
    (``item_behavior_catalog``'s shape table), never by a literal.  That is
    what lets the whole ally-packet compiler be name-free while still
    dispatching one branch per mechanic — and it makes the correspondence
    checkable: one producer per walk capability carrying a ``packet_source``,
    asserted rather than asserted-by-convention.
    """

    # heals and shields
    EVERLASTING = "everlasting"
    LIFE_FROM_DEATH = "life_from_death"
    STARLIT_GRACE = "starlit_grace"
    SOUL_SIPHON = "soul_siphon"
    CONSONANCE = "consonance"
    GOING_SLEDDING = "going_sledding"
    SACRIFICE = "sacrifice"
    # stat buffs and cross-participant modifiers
    SANCTIFY = "sanctify"
    RAPIDS = "rapids"
    FANFARE = "fanfare"
    UNMAKE = "unmake"
    EXPOSE_WEAKNESS = "expose_weakness"
    CARVE = "carve"
    VILE_DECAY = "vile_decay"
    BLUE_BUBBLE = "blue_bubble"
    PURPLE_BUBBLE = "purple_bubble"
    COMMAND = "command"
    # utility and quest
    REAP = "reap"
    RAGE = "rage"
    SHARED_RICHES = "shared_riches"
    WARD = "ward"
    # explicit actives
    DEVOTION = "devotion"
    PURIFY = "purify"
    INTERVENTION = "intervention"
    INSPIRING_SPEECH = "inspiring_speech"
    BREAKING_SHOCKWAVE = "breaking_shockwave"


class PacketKind(Enum):
    """The kinds a cross-participant packet may be built with.

    Closed over ``item_support_effects``' ``kind=`` arguments, which is what
    makes D-50 checkable: Moonstone Renewer used to compute its kind at
    runtime from the trigger it chained off, and a kind computed at runtime
    can be resolved by no static reader — not Phase 1's ``PacketSource``, not
    a family assignment, not this union.  It declares both instead.
    """

    HEAL = "heal"
    SHIELD = "shield"
    TEMPORARY_HEALTH = "temporary_health"
    STAT_BUFF = "stat_buff"
    MOVEMENT = "movement"
    ECONOMY = "economy"
    VISION = "vision"
    SLOW = "slow"
    DAMAGE = "damage"
    DAMAGE_MODIFIER = "damage_modifier"
    ON_HIT_MAGIC = "on_hit_magic"


class PacketTrigger(Enum):
    """What makes a producer emit.

    The walk's own event vocabulary, at the granularity the emitters branch
    on.  It is not :class:`TriggerEvent`: that says which *bus stream* a
    pricing rule reads, and several producers here fire off things the bus
    carries no stream for — an explicit active timestamp, or the fight's own
    start.
    """

    FIGHT_START = "fight_start"
    BASIC_ATTACK = "basic_attack"
    CROWD_CONTROL = "crowd_control"
    DAMAGE_DEALT = "damage_dealt"
    TAKEDOWN = "takedown"
    ALLY_HEAL_OR_SHIELD = "ally_heal_or_shield"
    ALLY_DAMAGE_DEALT = "ally_damage_dealt"
    ITEM_ACTIVE = "item_active"


class Recipients(Enum):
    """Whose ledger a packet lands on.

    The roster classes the emitters actually select, named once.  ``SELF`` and
    the ``HOLDER_AND_*`` members are distinct on purpose: "the holder, and one
    ally" is two packets and "the holder" is one, and a declaration that
    collapsed them could not say which.
    """

    SELF = "self"
    SELECTED_ALLY = "selected_ally"
    OTHER_ALLY = "other_ally"
    TRIGGERING_ALLY = "triggering_ally"
    HOLDER_AND_ALLIES = "holder_and_allies"
    HOLDER_AND_SELECTED_ALLY = "holder_and_selected_ally"
    HOLDER_AND_TRIGGERING_ALLY = "holder_and_triggering_ally"
    ENEMIES = "enemies"
    TRIGGERING_ENEMY = "triggering_enemy"


class Persistence(Enum):
    """How long one emitted packet is in force.

    Three members rather than a duration reference, because the question the
    compiled score kernel asks is categorical: it stages a support template
    only when the template is instantaneous
    (``survival/compile.unrepresentable_template_receipt`` refuses any
    ``duration > 0``), and an aura already in force at ``t = 0`` is a third
    thing again — it arms at :class:`~.survival.actions.TransitionRank`'s
    ``AURA_ARM`` rather than after the damage at its own timestamp.
    """

    SINGLE_MOMENT = "single_moment"
    TIMED_WINDOW = "timed_window"
    PERSISTENT_AURA = "persistent_aura"


@dataclass(frozen=True, slots=True)
class PacketSpec:
    """One packet a producer emits: its kind, and whose ledger it lands on."""

    kind: PacketKind
    recipients: Recipients


@dataclass(frozen=True, slots=True)
class AllyPacketRule:
    """One cross-participant producer, declared.

    ``secondary_target`` is D-50's: a producer that reaches a *second* roster
    class carries the class it reaches.  Redemption's Intervention is the
    motivating case — one active, one ``source=`` literal, and two packets,
    one healing every ally in the radius and one dealing true damage to every
    enemy in it — so a reader of the declaration alone could not otherwise
    tell that the second half exists.  It is ``None`` exactly when every
    declared packet lands on one class, which :func:`validate_rule` checks
    rather than trusting.

    ``values`` is every number the producer may read, held as references.  The
    emitter resolves them through the rule, so a key the declaration does not
    carry is a stop rather than a silent registry read — which is what makes
    the declaration load-bearing instead of descriptive.
    """

    producer: AllyProducer
    trigger: PacketTrigger
    packets: tuple[PacketSpec, ...]
    secondary_target: Recipients | None
    persistence: Persistence
    redirects_incoming_damage: bool
    values: tuple[AnyValueRef, ...]


RulePayload = Union[
    AllyPacketRule,
    DeltaAmpRule,
    OnHitStrikeRule,
    ResistanceShredRule,
    SecondaryTargetRule,
]

# Which family each payload type belongs to.  One entry per payload; each
# migration slice adds its family's payload here, so a rule can never carry
# a payload its family does not name.
PAYLOAD_FAMILY: dict[type, RuleFamily] = {
    AllyPacketRule: RuleFamily.ALLY_PACKET,
    DeltaAmpRule: RuleFamily.DELTA_AMP,
    OnHitStrikeRule: RuleFamily.ON_HIT_STRIKE,
    ResistanceShredRule: RuleFamily.RESISTANCE_SHRED,
    SecondaryTargetRule: RuleFamily.SECONDARY_TARGET,
}


# ── the rule ──────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class BehaviorRule:
    """One declared behaviour: the unit this phase replaces prose with."""

    family: RuleFamily
    owner: str
    mechanic_id: str
    payload: RulePayload
    compilability: Compilability
    receipt: SourceReceipt
    zero_policy: ZeroPolicy


def validate_rule(rule: BehaviorRule) -> None:
    """Structural validation of one rule — no imports, no ``data/`` read.

    It answers only the question a load gate can answer: is this declaration
    *shaped* like something that could be true?  Whether the owner exists,
    whether an interpreter is registered and whether the numbers resolve are
    later tiers' questions, deliberately not asked here.
    """
    if not isinstance(rule, BehaviorRule):
        raise BehaviorRuleError(f"{rule!r} is not a BehaviorRule")
    if not isinstance(rule.family, RuleFamily):
        raise BehaviorRuleError(f"{rule.owner!r}: family must be a RuleFamily")
    if not rule.owner.strip():
        raise BehaviorRuleError("a BehaviorRule names an owner")
    if not rule.mechanic_id.strip():
        raise BehaviorRuleError(f"{rule.owner!r}: a BehaviorRule names a mechanic_id")
    declared = PAYLOAD_FAMILY.get(type(rule.payload))
    if declared is None:
        raise BehaviorRuleError(
            f"{rule.mechanic_id}: {type(rule.payload).__name__} is not a declared "
            "payload type; add it to PAYLOAD_FAMILY in the slice that migrates "
            "its family"
        )
    if declared is not rule.family:
        raise BehaviorRuleError(
            f"{rule.mechanic_id}: payload {type(rule.payload).__name__} belongs to "
            f"{declared.value}, not {rule.family.value}"
        )
    if not isinstance(rule.compilability, COMPILABILITY_TYPES):
        raise BehaviorRuleError(f"{rule.mechanic_id}: compilability is not declared")
    if not isinstance(rule.receipt, SourceReceipt):
        raise BehaviorRuleError(f"{rule.mechanic_id}: receipt is not a SourceReceipt")
    if not isinstance(rule.zero_policy, ZeroPolicy):
        raise BehaviorRuleError(
            f"{rule.mechanic_id}: zero_policy is required and has no default (D-24)"
        )
    _validate_payload(rule)


def _validate_payload(rule: BehaviorRule) -> None:
    """Per-payload structure, kept out of :func:`validate_rule`'s ladder."""
    payload = rule.payload
    if isinstance(payload, AllyPacketRule):
        _validate_ally_packet(rule, payload)
        return
    if isinstance(payload, OnHitStrikeRule):
        _validate_formula(rule, payload.formula)
        return
    if isinstance(payload, SecondaryTargetRule):
        _validate_secondary_target(rule, payload)
        return
    if isinstance(payload, ResistanceShredRule):
        _validate_shred_payload(rule, payload)
        return
    if not isinstance(payload, DeltaAmpRule):
        return
    if not isinstance(payload.activation, ACTIVATION_TYPES):
        raise BehaviorRuleError(f"{rule.mechanic_id}: activation is not in the union")
    if not isinstance(payload.consumption, CONSUMPTION_TYPES):
        raise BehaviorRuleError(f"{rule.mechanic_id}: consumption is not in the union")
    if not isinstance(payload.magnitude, MAGNITUDE_TYPES):
        raise BehaviorRuleError(f"{rule.mechanic_id}: magnitude is not in the union")
    if not isinstance(payload.typing, Typing):
        raise BehaviorRuleError(f"{rule.mechanic_id}: typing is not declared (D-04)")
    if not isinstance(payload.bonus_typing, BonusTyping):
        raise BehaviorRuleError(
            f"{rule.mechanic_id}: bonus_typing must say what the bonus lands as"
        )
    if isinstance(payload.lane_chain_rank, bool) or not isinstance(
        payload.lane_chain_rank, int
    ):
        raise BehaviorRuleError(f"{rule.mechanic_id}: lane_chain_rank must be an int")
    if not 0 <= payload.lane_chain_rank < len(AMP_CHAIN_ORDER):
        raise BehaviorRuleError(
            f"{rule.mechanic_id}: lane_chain_rank {payload.lane_chain_rank} names no "
            "slot in AMP_CHAIN_ORDER"
        )


def _validate_formula(rule: BehaviorRule, formula: DamageFormula) -> None:
    """A formula's terms are sourced shares of declared bases."""
    if not isinstance(formula, DamageFormula):
        raise BehaviorRuleError(f"{rule.mechanic_id}: payload declares no formula")
    for term in formula.terms:
        if not isinstance(term, Term):
            raise BehaviorRuleError(f"{rule.mechanic_id}: a formula holds Terms")
        if not isinstance(term.basis, Basis):
            raise BehaviorRuleError(
                f"{rule.mechanic_id}: a term says what it is a share of"
            )
        if not isinstance(term.coefficient, (*VALUE_REF_TYPES, MeleeRangedSplit)):
            raise BehaviorRuleError(
                f"{rule.mechanic_id}: a term's coefficient is a sourced "
                "reference, never a number in the declaration"
            )


def _validate_secondary_target(
    rule: BehaviorRule, payload: SecondaryTargetRule
) -> None:
    """A secondary-target rule names a count and a share, both sourced."""
    for field_name in ("max_targets", "damage_share"):
        if not isinstance(getattr(payload, field_name), VALUE_REF_TYPES):
            raise BehaviorRuleError(
                f"{rule.mechanic_id}: {field_name} is a sourced reference"
            )
    if not isinstance(payload.applies_on_hit, bool):
        raise BehaviorRuleError(
            f"{rule.mechanic_id}: a secondary target says whether it carries "
            "on-hit effects; there is no default answer"
        )


def _validate_ally_packet(rule: BehaviorRule, payload: AllyPacketRule) -> None:
    """A producer names its packets, their recipients and its numbers.

    The ``secondary_target`` clause is the load-bearing one (D-50): a producer
    reaching two roster classes must *say so*, and a producer reaching one may
    not claim it does.  Both halves are checked, because a field that is only
    ever checked in one direction is a field a second producer can quietly
    stop filling in.
    """
    if not isinstance(payload.producer, AllyProducer):
        raise BehaviorRuleError(f"{rule.mechanic_id}: producer is not an AllyProducer")
    if not isinstance(payload.trigger, PacketTrigger):
        raise BehaviorRuleError(
            f"{rule.mechanic_id}: an ally packet says what fires it"
        )
    if not isinstance(payload.persistence, Persistence):
        raise BehaviorRuleError(
            f"{rule.mechanic_id}: an ally packet says how long it is in force"
        )
    if not isinstance(payload.redirects_incoming_damage, bool):
        raise BehaviorRuleError(
            f"{rule.mechanic_id}: redirects_incoming_damage is a declared bool; "
            "a producer that re-routes another participant's damage is not "
            "representable by the compiled kernel and must not default"
        )
    if not payload.packets:
        raise BehaviorRuleError(
            f"{rule.mechanic_id}: a producer that emits no packet is an item "
            "that quietly does nothing"
        )
    kinds: list[PacketKind] = []
    for spec in payload.packets:
        if not isinstance(spec, PacketSpec):
            raise BehaviorRuleError(f"{rule.mechanic_id}: packets holds PacketSpecs")
        if not isinstance(spec.kind, PacketKind) or not isinstance(
            spec.recipients, Recipients
        ):
            raise BehaviorRuleError(
                f"{rule.mechanic_id}: a packet names a kind and its recipients"
            )
        if spec.kind in kinds:
            raise BehaviorRuleError(
                f"{rule.mechanic_id}: declares {spec.kind.value} twice; one kind "
                "is one declared packet"
            )
        kinds.append(spec.kind)
    _validate_secondary_recipients(rule, payload)
    if not payload.values:
        raise BehaviorRuleError(
            f"{rule.mechanic_id}: a producer declares the numbers it reads"
        )
    for reference in payload.values:
        if not isinstance(reference, VALUE_REF_TYPES):
            raise BehaviorRuleError(
                f"{rule.mechanic_id}: values holds sourced references, never "
                "numbers in the declaration"
            )


def _validate_secondary_recipients(rule: BehaviorRule, payload: AllyPacketRule) -> None:
    """``secondary_target`` is present exactly when a second class is reached."""
    primary = payload.packets[0].recipients
    others = {
        spec.recipients for spec in payload.packets if spec.recipients is not primary
    }
    if len(others) > 1:
        raise BehaviorRuleError(
            f"{rule.mechanic_id}: reaches {len(others) + 1} recipient classes and "
            "secondary_target names one; a third class needs its own declared axis"
        )
    if not others:
        if payload.secondary_target is not None:
            raise BehaviorRuleError(
                f"{rule.mechanic_id}: every packet lands on {primary.value} and "
                "the rule still declares a secondary_target"
            )
        return
    (second,) = others
    if payload.secondary_target is not second:
        raise BehaviorRuleError(
            f"{rule.mechanic_id}: emits to {second.value} beside {primary.value} "
            f"and declares secondary_target={payload.secondary_target}; the "
            "second class a producer reaches is declared, never inferred (D-50)"
        )


def _validate_shred_payload(rule: BehaviorRule, payload: ResistanceShredRule) -> None:
    """A shred names a resistance, a ramp and the damage that applies a stack."""
    if not isinstance(payload.resistance, Resistance):
        raise BehaviorRuleError(
            f"{rule.mechanic_id}: a shred says which resistance it reduces"
        )
    if not isinstance(payload.ramp, StackRamp):
        raise BehaviorRuleError(f"{rule.mechanic_id}: ramp is not a StackRamp")
    if not isinstance(payload.ramp.accrual, TriggerEvent):
        raise BehaviorRuleError(
            f"{rule.mechanic_id}: a shred says what event applies a stack"
        )
    if not isinstance(payload.ramp.model, RampModel):
        raise BehaviorRuleError(
            f"{rule.mechanic_id}: a shred says how its stack history is summed"
        )
    if not isinstance(payload.typing, Typing):
        raise BehaviorRuleError(f"{rule.mechanic_id}: typing is not declared (D-04)")
    if payload.subject is not Subject.TARGET:
        raise BehaviorRuleError(
            f"{rule.mechanic_id}: a resistance shred acts on the target's "
            "resistances; no other subject has any to reduce"
        )


# The ``str``-typed fields that are identifiers and citations rather than
# policy.  Criterion 6 requires them **named**, not waived on contact, so
# they are a constant the assertion reads and not a judgement it makes.
POLICY_IDENTIFIER_FIELDS: frozenset[str] = frozenset(
    {"owner", "mechanic_id", "reason", "url", "revision_id", "revision_timestamp"}
)


def _flatten_policy(value: object, out: list[object]) -> None:
    """Append *value* and, unless it is a reference, everything inside it."""
    out.append(value)
    if is_value_reference(value) or not is_dataclass(value) or isinstance(value, type):
        return
    for spec in dataclass_fields(value):
        if spec.name in POLICY_IDENTIFIER_FIELDS:
            continue
        _flatten_policy(getattr(value, spec.name), out)


def policy_values(rule: BehaviorRule) -> tuple[object, ...]:
    """Every policy value the rule carries, flattened for reflective checks.

    Criterion 6 is asserted over this: no policy field may be a callable, a
    ``dict``, ``Any`` or an open string.  It reaches *every* field of the
    rule, recursing through the frozen policy records and stopping at a
    value reference — whose own fields are the registry, owner and key that
    name a number rather than describing one.  The identifiers and citations
    are skipped by :data:`POLICY_IDENTIFIER_FIELDS`, which is what "named in
    the assertion" means: the exception is a list somebody can read, not a
    waiver somebody makes when the criterion first bites.
    """
    values: list[object] = []
    _flatten_policy(rule.family, values)
    _flatten_policy(rule.compilability, values)
    _flatten_policy(rule.payload, values)
    _flatten_policy(rule.receipt, values)
    _flatten_policy(rule.zero_policy, values)
    return tuple(values)


def is_value_reference(value: object) -> bool:
    """Whether *value* is one of the four reference shapes a declaration holds."""
    return isinstance(value, VALUE_REF_TYPES)


# ── the interpreters/ -> survival/ contract ───────────────────────────────


class KernelField(NamedTuple):
    """One value-typed field a build-time interpreter emits for the kernel.

    The compiled form of a rule, carrying no program type and no callable.
    This is what keeps the dependency one-way: walk-lane interpreters run at
    *build* time and hand the kernel fields it already understands, so
    nothing under ``survival/`` ever imports ``interpreters/``.
    """

    name: str
    value: float | int | bool | str
    lane: EngineLane
    rule_id: str


@dataclass(frozen=True, slots=True)
class BuildContext:
    """What an interpreter may read at build time.

    Level, the owner whose registry entry is being compiled, the
    ``data_registry.data_version()`` its memo keys on (D-49), and the two
    fight facts a magnitude may scale with.  No walk state and no
    ``SurvivalAction``: an interpreter that could see those would be running
    inside the walk, which is the cycle this contract prevents.

    ``fight_duration_seconds``, ``target_bonus_health`` and
    ``holder_is_melee`` are configuration, not walk state — all three are
    fixed before the first event — and they are here because a ramping,
    health-scaled or range-split magnitude cannot become a number without
    them.  Every field is required: a magnitude that silently read a
    defaulted zero duration is the campaign's own failure shape, and a
    defaulted ``holder_is_melee`` would silently pay every champion the
    ranged rate.
    """

    level: int
    owner: str
    data_version: int
    fight_duration_seconds: float
    target_bonus_health: float
    holder_is_melee: bool


__all__ = [
    "ACTIVATION_TYPES",
    "AMP_CHAIN_ORDER",
    "AbsoluteWindow",
    "Activation",
    "AfterTrigger",
    "AllyPacketRule",
    "AllyProducer",
    "Always",
    "AmpChainSlot",
    "AtLeast",
    "Attribution",
    "Basis",
    "BehaviorRule",
    "BehaviorRuleError",
    "BonusTyping",
    "BuildContext",
    "COMPILABILITY_TYPES",
    "CONSUMPTION_TYPES",
    "Comparison",
    "Compilability",
    "Compilable",
    "Consumption",
    "DamageFormula",
    "DeltaAmpRule",
    "EngineLane",
    "ExcludeTrigger",
    "FLOOR_TYPES",
    "Fixed",
    "Floor",
    "Isolation",
    "KernelField",
    "LivePredicate",
    "MAGNITUDE_TYPES",
    "Magnitude",
    "MeleeRangedSplit",
    "NEvents",
    "NextEventOnly",
    "NoFloor",
    "OnHitStrikeRule",
    "PAYLOAD_FAMILY",
    "POLICY_IDENTIFIER_FIELDS",
    "PacketKind",
    "PacketSpec",
    "PacketTrigger",
    "Persist",
    "Persistence",
    "Pool",
    "Probe",
    "RULE_FAMILY_COUNT",
    "RampModel",
    "RampPerSecond",
    "RampPerStack",
    "ReceiptOnly",
    "Recipients",
    "Resistance",
    "ResistanceShredRule",
    "RuleFamily",
    "RulePayload",
    "SUBJECT_AUTHORITY",
    "SecondaryTargetRule",
    "StackRamp",
    "Subject",
    "TRIGGER_STREAM",
    "TargetBonusHealthScaled",
    "Term",
    "TriggerEvent",
    "TriggerWindow",
    "Typing",
    "WindowBoundary",
    "WindowMerge",
    "ZeroPolicy",
    "chain_rank",
    "is_value_reference",
    "policy_values",
    "validate_rule",
]
