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

from collections.abc import Mapping
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
    :class:`DefenseMechanic` fails collection until it is mapped
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
class LevelSteppedRate:
    """A rate that starts growing per level once a declared level is reached.

    The third coefficient shape, beside a plain reference and a range split.
    It is not a level *ramp*: a ramp interpolates between two stated ends,
    while this one is flat below its threshold and adds a fixed amount per
    level from it upwards, which is a different mechanic and a different
    float.  Both halves may themselves be range splits, because the one
    schema that needs this pays a melee holder more at both ends.
    """

    base: Union[AnyValueRef, "MeleeRangedSplit"]
    per_level: Union[AnyValueRef, "MeleeRangedSplit"]
    from_level: AnyValueRef


@dataclass(frozen=True, slots=True)
class Term:
    """One share of one basis: ``coefficient × basis``.

    ``coefficient`` is a sourced reference, a :class:`MeleeRangedSplit` where
    the registry pays a melee holder differently — the same shape the amp
    chain uses, and for the same reason: the choice is made once per build
    from a stat, before any event exists — or a :class:`LevelSteppedRate`
    where it grows with the holder's level past a declared one.
    """

    coefficient: Union[AnyValueRef, MeleeRangedSplit, LevelSteppedRate]
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
class NoScaling:
    """The formula's sum stands as summed."""


@dataclass(frozen=True, slots=True)
class TimesValue:
    """The whole sum is multiplied by a sourced factor.

    A multiplier over the *sum* is not a share and cannot be folded into the
    terms: ``(base + ratio x AP) x 2`` and ``2 x base + 2 x ratio x AP`` are
    the same number in algebra and two different floats in a fight, and the
    registry's own compilers wrote the first.
    """

    factor: AnyValueRef


@dataclass(frozen=True, slots=True)
class TimesMissingHealth:
    """The sum grows towards a sourced bonus as the target's health falls.

    ``bonus_at_full_missing`` is what the strike gains against a target on
    one hit point; against a full-health target it gains nothing.  It is a
    factor over the whole sum and not a share, which is why it is a scaling
    rather than a term reading :data:`Basis.TARGET_MISSING_HEALTH`.
    """

    bonus_at_full_missing: AnyValueRef


Scaling = Union[NoScaling, TimesValue, TimesMissingHealth]

SCALING_TYPES: tuple[type, ...] = (NoScaling, TimesValue, TimesMissingHealth)


@dataclass(frozen=True, slots=True)
class DamageFormula:
    """A sum of sourced shares, scaled, floored, landing as one damage class.

    Every strike family's number is one of these.  The union of *terms* is
    what replaces the registry's formula-name ladder; ``scaling`` is a factor
    over the whole sum rather than a share of anything; and ``floor`` is its
    own axis because "at least this much" is a mechanic (Blade of the Ruined
    King's minimum) rather than a term.

    The order is stated because it is arithmetic and not style: the shares are
    summed, the sum is scaled, and the floor is the minimum on the number the
    mechanic finally pays.
    """

    terms: tuple[Term, ...]
    scaling: Scaling
    floor: Floor
    damage_class: DamageClass

    def __post_init__(self) -> None:
        """A formula with no terms is a number nobody declared."""
        if not self.terms:
            raise BehaviorRuleError(
                "a DamageFormula names at least one term; a formula with no "
                "shares is an item that quietly deals nothing"
            )
        if not isinstance(self.scaling, SCALING_TYPES):
            raise BehaviorRuleError("a DamageFormula declares its scaling")
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


@dataclass(frozen=True, slots=True)
class EnergizedCharge:
    """Stacks an item accrues from attacking, spent on one empowered hit."""

    max_stacks: AnyValueRef
    stacks_per_attack: AnyValueRef
    abilities_also_charge: bool


@dataclass(frozen=True, slots=True)
class TemporaryLethality:
    """Lethality an empowered hit grants its holder for a declared window."""

    melee: AnyValueRef
    ranged: AnyValueRef
    duration: AnyValueRef


@dataclass(frozen=True, slots=True)
class ChainTargets:
    """How many further enemies one empowered hit arcs to."""

    minimum: AnyValueRef
    maximum: AnyValueRef


@dataclass(frozen=True, slots=True)
class EmpoweredHitRule:
    """A strike that spends a charge on one hit rather than paying every hit.

    ``max_procs`` is always declared and is ``Const(1, "count")`` for the
    strikes that fire once: "this fires once" is a statement about the
    mechanic and reading it out of the *absence* of a key is how a second
    such strike would silently inherit somebody else's answer.

    The three optional records are mechanics only some of these strikes have:
    Energized stacks, Voltaic's temporary lethality, Statikk's arc.  Each is a
    declared ``None`` where the mechanic does not exist.
    """

    formula: DamageFormula
    max_procs: AnyValueRef
    basic_damage: bool
    energized: EnergizedCharge | None
    temporary_lethality: TemporaryLethality | None
    chain_targets: ChainTargets | None


@dataclass(frozen=True, slots=True)
class RepeatingStrikeRule:
    """A strike that lands on every Nth on-hit application."""

    formula: DamageFormula
    hits_required: AnyValueRef
    basic_damage: bool


@dataclass(frozen=True, slots=True)
class ShapedChargeRule:
    """A charge an ability arms, paid as true damage on a cooldown."""

    formula: DamageFormula
    cooldown: AnyValueRef


@dataclass(frozen=True, slots=True)
class EmpoweredAutoBuffRule:
    """An ultimate that empowers a declared number of the holder's attacks.

    The one strike-family member that deals no damage of its own: it changes
    how the holder's *own* attacks land — faster, guaranteed critical, with a
    reduced critical multiplier and a true-damage rider on natural criticals —
    so it carries five numbers and no formula.
    """

    bonus_attack_speed_percent: AnyValueRef
    empowered_auto_count: AnyValueRef
    duration: AnyValueRef
    reduced_crit_ratio: AnyValueRef
    natural_crit_true_damage_ratio: AnyValueRef


class ProcTrigger(Enum):
    """What arms a cooldown proc.

    The registry's own ``trigger`` vocabulary, closed.  It is deliberately not
    :class:`TriggerEvent`: that says which *bus stream* a pricing rule reads,
    while these say which of the engine's proc schedulers owns the mechanic —
    a coarse once-per-rotation row, a per-champion-damage counter, a
    per-ability-damage counter, or a rolling damage threshold.
    """

    COARSE = "coarse"
    CHAMPION_DAMAGE = "champion_damage"
    ABILITY_DAMAGE = "ability_damage"
    DAMAGE_THRESHOLD = "damage_threshold"


@dataclass(frozen=True, slots=True)
class DamageThreshold:
    """A proc armed once a share of the target's health is dealt in a window."""

    share_of_max_health: AnyValueRef
    window_seconds: AnyValueRef


@dataclass(frozen=True, slots=True)
class ChargedSplash:
    """A proc that fires several charges, all of which may land on one target.

    ``single_target_multiplier`` is what one target takes when every charge
    hits it; the engine spreads the rest across a roster.  Both numbers are
    sourced, and the *distribution* between them is arithmetic the interpreter
    does rather than a third declared number.
    """

    charges: AnyValueRef
    single_target_multiplier: AnyValueRef


@dataclass(frozen=True, slots=True)
class StackGate:
    """A proc that needs several qualifying hits inside a rolling window."""

    required: AnyValueRef
    window_seconds: AnyValueRef


@dataclass(frozen=True, slots=True)
class SelfShield:
    """A shield a proc grants its holder when it completes."""

    melee_base: AnyValueRef
    ranged_base: AnyValueRef
    melee_bonus_ad_ratio: AnyValueRef
    ranged_bonus_ad_ratio: AnyValueRef
    duration: AnyValueRef


@dataclass(frozen=True, slots=True)
class CooldownProcRule:  # pylint: disable=too-many-instance-attributes
    """Damage a trigger arms and a cooldown re-arms.

    The family's biggest payload, and every optional field is a mechanic some
    proc has and most do not: Scout's Slingshot refunds cooldown per attack
    windup, Luden's Echo splits into charges, Eclipse needs a pair of hits and
    pays a shield for it.  Each is a declared ``None`` where it does not
    exist, because a zero refund and no refund at all are different claims.

    ``late_phase`` and ``is_ability_damage`` are shape rather than magnitude:
    they say when in the fight's ordering the row is stamped and whether the
    damage counts as ability damage for everything downstream.
    """

    formula: DamageFormula
    cooldown: AnyValueRef
    trigger: ProcTrigger
    repeat_on_cooldown: bool
    is_ability_damage: bool
    basic_damage: bool
    late_phase: bool
    threshold: DamageThreshold | None
    attack_cooldown_refund: AnyValueRef | None
    charged: ChargedSplash | None
    stacks: StackGate | None
    self_shield: SelfShield | None


@dataclass(frozen=True, slots=True)
class UltimateProcRule:
    """Damage an ultimate cast arms, spread over one declared duration.

    ``mr_reduction`` is Malignance's sibling and a declared ``None``
    everywhere else: an ultimate proc that shreds nothing and one that shreds
    zero magic resistance are different claims about the item.
    """

    formula: DamageFormula
    duration: AnyValueRef
    mr_reduction: AnyValueRef | None


@dataclass(frozen=True, slots=True)
class SpellbladeRule:  # pylint: disable=too-many-instance-attributes
    """The empowered attack an ability cast arms.

    Nine fields because a spellblade really does answer nine questions, and
    the five that end in a declared ``None`` are the point rather than
    clutter: Lich Bane's attack-speed burst, Essence Reaver's mana refund and
    Dusk and Dawn's self-heal are *sibling mechanics of specific spellblades*,
    and the registry's own compiler decided which by comparing item names.

    Which siblings an entry carries is now decided by
    ``item_behavior_catalog``'s sibling groups: a group is declared whole or
    not at all, so a parse that dropped half of Essence Reaver's mana refund
    is a stop rather than a quietly weaker item — the fail-closed contract the
    name comparison used to carry, without the names.

    ``double_on_hit`` is a structural flag rather than a reference: it says
    whether the empowered attack applies on-hit effects twice, which is a
    shape of the mechanic and not a quantity anybody patches.
    """

    formula: DamageFormula
    cooldown: AnyValueRef
    weave_delay: AnyValueRef
    double_on_hit: bool
    bonus_attack_speed_percent: AnyValueRef | None
    mana_restore_base_ad_ratio: AnyValueRef | None
    mana_restore_crit_ratio: AnyValueRef | None
    self_heal_ap_ratio: AnyValueRef | None
    self_heal_bonus_health_ratio: AnyValueRef | None


class PeriodicCadence(Enum):
    """How a periodic strike spreads one item's damage over time.

    The three shapes really are different mechanics rather than three
    intervals: a burn is a *window* that every ability hit re-arms and that
    resolves in full past the fight's end; an aura pays a rate for as long as
    the fight lasts; a fixed-interval strike lands a whole packet every N
    seconds and lands nothing in between.  The registry said which by using
    three tags whose only shared vocabulary was the word "formula".
    """

    REFRESHED_BURN = "refreshed_burn"
    CONTINUOUS_AURA = "continuous_aura"
    FIXED_INTERVAL = "fixed_interval"


@dataclass(frozen=True, slots=True)
class PeriodicRule:
    """Damage an item deals on a clock rather than on an event.

    ``interval`` is the cadence the declaration's own ``cadence`` gives
    meaning to — a burn's tick, an aura's event spacing, a fixed strike's
    period — which is why it is one field rather than three optional ones.

    The three optional fields are declared absences, present exactly for the
    cadence that has them: only a burn has a ``duration`` (the window one
    application lasts), and only a fixed-interval strike has published a
    ``aoe_range_units`` targeting receipt or a ``self_heal_share``.  A zero in
    any of their places would claim the mechanic exists and pays nothing.
    """

    formula: DamageFormula
    cadence: PeriodicCadence
    interval: AnyValueRef
    duration: AnyValueRef | None
    aoe_range_units: AnyValueRef | None
    self_heal_share: AnyValueRef | None


@dataclass(frozen=True, slots=True)
class ActiveCastRule:
    """Damage the holder deals by pressing the item, once per fight.

    An active is the one strike family whose trigger is the *player* rather
    than an event the fight produces, which is why it carries a cooldown and
    no trigger: the engine casts it once, at the end of the rotation opener,
    and the cooldown is what says whether a second cast could exist.

    ``lifesteal_effectiveness`` is ``None`` — a declared absence — for every
    active that does not inherit life steal.  A zero would say the sibling
    exists and pays nothing, which is a different claim about the item, and
    exactly the claim this campaign exists to stop a declaration making by
    accident.
    """

    formula: DamageFormula
    cooldown: AnyValueRef
    lifesteal_effectiveness: AnyValueRef | None


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


# ── the critical-strike profile ───────────────────────────────────────────


class CritOccurrence(Enum):
    """Which strike of a fight a forced critical strike lands on.

    One member today, and it is still an enum rather than a boolean: the
    registry tag is ``first_auto_crit`` and the engine's own test is
    ``i == 0``, so "which strike" is a question the model already asks and
    answers with an index nobody named.
    """

    FIRST_ATTACK = "first_attack"


@dataclass(frozen=True, slots=True)
class ForcedCritHeal:
    """The heal a forced critical strike pays, and where its excess goes.

    Declared as one record rather than four loose references because the
    four numbers are one mechanic: a melee and a ranged share of base attack
    damage, a share of the target's missing health, and the duration the
    overflow is held as bonus health.  An item that forces a crit without
    healing declares ``None`` rather than four zeroes — the declared-absence
    idiom, so "this crit heals nothing" and "this crit's heal resolved to
    zero" stay distinguishable.
    """

    base_ad_ratio: AnyValueRef
    base_ad_ratio_ranged: AnyValueRef
    missing_health_ratio: AnyValueRef
    temporary_health_duration: AnyValueRef


@dataclass(frozen=True, slots=True)
class CritDamageBonusRule:
    """A flat addition to the multiplier every critical strike pays.

    The base multiplier is the game's (CLAUDE.md: 200%) and belongs to the
    engine; what an item declares is the *bonus* on top of it.  ``typing``
    says which damage the bonus reaches, which is the declaration's answer to
    a question the engine answers by where in the formula the addition sits.
    """

    bonus: AnyValueRef
    typing: Typing
    subject: Subject


@dataclass(frozen=True, slots=True)
class ForcedCritRule:
    """One strike that crits whether or not the roll would have.

    ``reduced_ratio`` is a fraction of a full critical strike, not a
    multiplier: the forced crit *overrides* a natural one, so a build that
    would have critted anyway is made weaker by holding the item, and the
    ratio is what says by how much.  ``cooldown`` is how long before the next
    strike is forced again.
    """

    occurrence: CritOccurrence
    reduced_ratio: AnyValueRef
    cooldown: AnyValueRef
    heal: ForcedCritHeal | None
    typing: Typing
    subject: Subject


@dataclass(frozen=True, slots=True)
class AttackCooldownRefundRule:
    """A fraction of the holder's ability cooldowns refunded by an event.

    It lands in the crit family because that is what the registry tag says
    and where the mechanic lives: the refund rides a critical-strike item's
    passive, and the number is read from the same entry as every other crit
    modifier.  What it changes is a cooldown rather than a damage number,
    which is why it is its own payload and not a field on
    :class:`CritDamageBonusRule`.
    """

    refund_fraction: AnyValueRef
    trigger: TriggerEvent
    subject: Subject


# ── defence ───────────────────────────────────────────────────────────────


class DefenseMechanic(Enum):
    """Every defence the resolver may cite, in the order it applies them.

    A member is the identity of one defensive mechanic, and its citation is
    a ``SourceReceipt`` the catalog resolves — so a defence's provenance is
    the same kind of object as every other declaration's, rather than the
    hand-written record beside the behaviour that it replaced.

    **The declaration order below is the resolution order**, and that is
    arithmetic rather than presentation.  A later mechanic sees what an
    earlier one granted — Boundless Vitality multiplies shields that three
    earlier mechanics put there — and the published ``assumptions`` and
    ``sources`` lists come out in this order.  Two members carry one
    mechanic's two spellings only where the wiki does: Armored Advance's
    Noxian Endurance and Chainlaced Crushers' Noxian Persistence are the same
    shape with two names and two citations.
    """

    SHIELD_OF_DURAND = "shield_of_durand"
    NOXIAN_ENDURANCE = "noxian_endurance"
    NOXIAN_PERSISTENCE = "noxian_persistence"
    BLESSING_OF_THE_MOUNTAIN = "blessing_of_the_mountain"
    ICHORSHIELD = "ichorshield"
    EVERLASTING = "everlasting"
    ANNUL = "annul"
    MAGEBANE = "magebane"
    LIFELINE_SHIELDBOW = "lifeline_shieldbow"
    LIFELINE_HEXDRINKER = "lifeline_hexdrinker"
    LIFELINE_MAW = "lifeline_maw"
    LIFELINE_SERAPH = "lifeline_seraph"
    LIFELINE_STERAK = "lifeline_sterak"
    LIFELINE_PROTOPLASM = "lifeline_protoplasm"
    REBIRTH = "rebirth"
    IGNORE_PAIN = "ignore_pain"
    STEADFAST = "steadfast"
    VOIDBORN_RESILIENCE = "voidborn_resilience"
    TIME_STOP = "time_stop"
    BOUNDLESS_VITALITY = "boundless_vitality"
    PLATING = "plating"
    ROCK_SOLID = "rock_solid"
    RESILIENCE = "resilience"
    THORNS = "thorns"


class DefenseField(Enum):
    """One field of the resolved defensive state a declaration may write.

    Total over ``defensive_effects.StartingDefenses``' own fields, less the
    three that are *about* the resolution rather than part of it
    (``assumptions``, ``sources``, ``coverage``).  The totality is a test
    rather than a comment, so a new defensive field cannot exist with no
    declaration able to fill it and no combine rule saying how two mechanics
    writing it agree.
    """

    MAGIC_SHIELD = "magic_shield"
    PHYSICAL_SHIELD = "physical_shield"
    GENERAL_SHIELD = "general_shield"
    REACTIVE_SHIELD_AMOUNT = "reactive_shield_amount"
    REACTIVE_SHIELD_DAMAGE_TYPE = "reactive_shield_damage_type"
    REACTIVE_SHIELD_DURATION = "reactive_shield_duration"
    REACTIVE_SHIELD_COOLDOWN = "reactive_shield_cooldown"
    REACTIVE_SHIELD_SOURCE = "reactive_shield_source"
    BLOODTHIRSTER_SHIELD_CAP = "bloodthirster_shield_cap"
    BLOODTHIRSTER_STARTING_SHIELD = "bloodthirster_starting_shield"
    SPELL_SHIELD_READY = "spell_shield_ready"
    SPELL_SHIELD_SOURCE = "spell_shield_source"
    BASIC_DAMAGE_MULTIPLIER = "basic_damage_multiplier"
    INCOMING_DAMAGE_MULTIPLIER = "incoming_damage_multiplier"
    INCOMING_DAMAGE_LINGER = "incoming_damage_linger"
    INCOMING_DAMAGE_COOLDOWN = "incoming_damage_cooldown"
    INCOMING_DAMAGE_SOURCE = "incoming_damage_source"
    BASIC_DAMAGE_FLAT_REDUCTION = "basic_damage_flat_reduction"
    BASIC_DAMAGE_FLAT_REDUCTION_CAP = "basic_damage_flat_reduction_cap"
    CRITICAL_STRIKE_DAMAGE_MULTIPLIER = "critical_strike_damage_multiplier"
    HEALING_RECEIVED_MULTIPLIER = "healing_received_multiplier"
    MAW_LIFELINE_OMNIVAMP_PERCENT = "maw_lifeline_omnivamp_percent"
    THRESHOLD_SHIELD_AMOUNT = "threshold_shield_amount"
    THRESHOLD_SHIELD_HEALTH_RATIO = "threshold_shield_health_ratio"
    THRESHOLD_SHIELD_DURATION = "threshold_shield_duration"
    THRESHOLD_SHIELD_DAMAGE_TYPE = "threshold_shield_damage_type"
    THRESHOLD_HEALTH_BONUS = "threshold_health_bonus"
    THRESHOLD_HEALTH_HEAL = "threshold_health_heal"
    THRESHOLD_HEALTH_RATIO = "threshold_health_ratio"
    THRESHOLD_HEALTH_DURATION = "threshold_health_duration"
    REVIVE_HEALTH_AMOUNT = "revive_health_amount"
    REVIVE_DELAY = "revive_delay"
    REVIVE_COOLDOWN = "revive_cooldown"
    REVIVE_SOURCE = "revive_source"
    DAMAGE_DEFERRAL_FRACTION = "damage_deferral_fraction"
    DAMAGE_DEFERRAL_DURATION = "damage_deferral_duration"
    DAMAGE_DEFERRAL_TICKS = "damage_deferral_ticks"
    DEFY_WINDOW = "defy_window"
    DEFY_HEAL_BONUS_AD_RATIO = "defy_heal_bonus_ad_ratio"
    DEFY_HEAL_DURATION = "defy_heal_duration"
    DEFY_HEAL_TICKS = "defy_heal_ticks"
    FORCE_STACK_DURATION = "force_stack_duration"
    FORCE_MAX_STACKS = "force_max_stacks"
    FORCE_STACK_INTERVAL = "force_stack_interval"
    FORCE_IMMOBILIZE_STACKS = "force_immobilize_stacks"
    FORCE_BONUS_MAGIC_RESISTANCE = "force_bonus_magic_resistance"
    FORCE_BONUS_MOVE_SPEED_PERCENT = "force_bonus_move_speed_percent"
    JAKSHO_STACK_INTERVAL = "jaksho_stack_interval"
    JAKSHO_MAX_STACKS = "jaksho_max_stacks"
    JAKSHO_BONUS_RESISTANCE_MULTIPLIER = "jaksho_bonus_resistance_multiplier"
    STARTING_STASIS_DURATION = "starting_stasis_duration"
    STARTING_STASIS_SOURCE = "starting_stasis_source"


class DefenseCombine(Enum):
    """How a field answers when a second mechanic writes the one before it.

    A property of the *field*, not of the mechanic that writes it: two boots
    both plate, so their multipliers compose, while two Lifelines are
    mutually exclusive and the second never gets to write at all.  Stating it
    once per field is what makes "a build holding two of these" a declared
    answer instead of whichever branch a name ladder tested last.
    """

    SET = "set"
    ADD = "add"
    MULTIPLY = "multiply"
    FILL_IF_EMPTY = "fill_if_empty"


# How each defensive field composes.  ``FILL_IF_EMPTY`` has exactly one
# member and it is a real rule rather than a convenience: a champion passive
# that already claimed the revive keeps its label when Guardian Angel is also
# held, because the resurrection is one event with one cause.
DEFENSE_FIELD_COMBINE: dict[DefenseField, DefenseCombine] = {
    DefenseField.MAGIC_SHIELD: DefenseCombine.ADD,
    DefenseField.PHYSICAL_SHIELD: DefenseCombine.ADD,
    DefenseField.GENERAL_SHIELD: DefenseCombine.ADD,
    DefenseField.REACTIVE_SHIELD_AMOUNT: DefenseCombine.SET,
    DefenseField.REACTIVE_SHIELD_DAMAGE_TYPE: DefenseCombine.SET,
    DefenseField.REACTIVE_SHIELD_DURATION: DefenseCombine.SET,
    DefenseField.REACTIVE_SHIELD_COOLDOWN: DefenseCombine.SET,
    DefenseField.REACTIVE_SHIELD_SOURCE: DefenseCombine.SET,
    DefenseField.BLOODTHIRSTER_SHIELD_CAP: DefenseCombine.SET,
    DefenseField.BLOODTHIRSTER_STARTING_SHIELD: DefenseCombine.SET,
    DefenseField.SPELL_SHIELD_READY: DefenseCombine.SET,
    DefenseField.SPELL_SHIELD_SOURCE: DefenseCombine.SET,
    DefenseField.BASIC_DAMAGE_MULTIPLIER: DefenseCombine.MULTIPLY,
    DefenseField.INCOMING_DAMAGE_MULTIPLIER: DefenseCombine.SET,
    DefenseField.INCOMING_DAMAGE_LINGER: DefenseCombine.SET,
    DefenseField.INCOMING_DAMAGE_COOLDOWN: DefenseCombine.SET,
    DefenseField.INCOMING_DAMAGE_SOURCE: DefenseCombine.SET,
    DefenseField.BASIC_DAMAGE_FLAT_REDUCTION: DefenseCombine.SET,
    DefenseField.BASIC_DAMAGE_FLAT_REDUCTION_CAP: DefenseCombine.SET,
    DefenseField.CRITICAL_STRIKE_DAMAGE_MULTIPLIER: DefenseCombine.MULTIPLY,
    DefenseField.HEALING_RECEIVED_MULTIPLIER: DefenseCombine.SET,
    DefenseField.MAW_LIFELINE_OMNIVAMP_PERCENT: DefenseCombine.SET,
    DefenseField.THRESHOLD_SHIELD_AMOUNT: DefenseCombine.SET,
    DefenseField.THRESHOLD_SHIELD_HEALTH_RATIO: DefenseCombine.SET,
    DefenseField.THRESHOLD_SHIELD_DURATION: DefenseCombine.SET,
    DefenseField.THRESHOLD_SHIELD_DAMAGE_TYPE: DefenseCombine.SET,
    DefenseField.THRESHOLD_HEALTH_BONUS: DefenseCombine.SET,
    DefenseField.THRESHOLD_HEALTH_HEAL: DefenseCombine.SET,
    DefenseField.THRESHOLD_HEALTH_RATIO: DefenseCombine.SET,
    DefenseField.THRESHOLD_HEALTH_DURATION: DefenseCombine.SET,
    DefenseField.REVIVE_HEALTH_AMOUNT: DefenseCombine.SET,
    DefenseField.REVIVE_DELAY: DefenseCombine.SET,
    DefenseField.REVIVE_COOLDOWN: DefenseCombine.SET,
    DefenseField.REVIVE_SOURCE: DefenseCombine.FILL_IF_EMPTY,
    DefenseField.DAMAGE_DEFERRAL_FRACTION: DefenseCombine.SET,
    DefenseField.DAMAGE_DEFERRAL_DURATION: DefenseCombine.SET,
    DefenseField.DAMAGE_DEFERRAL_TICKS: DefenseCombine.SET,
    DefenseField.DEFY_WINDOW: DefenseCombine.SET,
    DefenseField.DEFY_HEAL_BONUS_AD_RATIO: DefenseCombine.SET,
    DefenseField.DEFY_HEAL_DURATION: DefenseCombine.SET,
    DefenseField.DEFY_HEAL_TICKS: DefenseCombine.SET,
    DefenseField.FORCE_STACK_DURATION: DefenseCombine.SET,
    DefenseField.FORCE_MAX_STACKS: DefenseCombine.SET,
    DefenseField.FORCE_STACK_INTERVAL: DefenseCombine.SET,
    DefenseField.FORCE_IMMOBILIZE_STACKS: DefenseCombine.SET,
    DefenseField.FORCE_BONUS_MAGIC_RESISTANCE: DefenseCombine.SET,
    DefenseField.FORCE_BONUS_MOVE_SPEED_PERCENT: DefenseCombine.SET,
    DefenseField.JAKSHO_STACK_INTERVAL: DefenseCombine.SET,
    DefenseField.JAKSHO_MAX_STACKS: DefenseCombine.SET,
    DefenseField.JAKSHO_BONUS_RESISTANCE_MULTIPLIER: DefenseCombine.SET,
    DefenseField.STARTING_STASIS_DURATION: DefenseCombine.SET,
    DefenseField.STARTING_STASIS_SOURCE: DefenseCombine.SET,
}


class DefenseExclusivity(Enum):
    """Which declared defences may not both be read on one build.

    The game's own unique-passive rule, declared.  A build can legally hold
    two Lifelines, two Annuls or both stasis items in this model, and exactly
    one of them is read: the one whose owner comes **first in the number
    registry**, which is the tie-break the retired name ladder spelled as a
    tuple of item names and this states without naming one.
    """

    NONE = "none"
    LIFELINE = "lifeline"
    ANNUL = "annul"
    STASIS = "stasis"


class DefenseOption(Enum):
    """The scenario inputs a defence refuses to infer from item presence.

    A starting Ichorshield and an active Time Stop are *states*, not
    properties of the build, so each names the input option that supplies it
    and pays nothing without one.  The values are the item registry's own
    option keys.
    """

    STARTING_ICHORSHIELD = "starting_ichorshield"
    STASIS_ACTIVE_SECONDS = "stasis_active_seconds"


class ShieldAbsorbs(Enum):
    """What a declared shield stands in front of.

    Not :class:`~.ability_spec.DamageClass`: a shield that absorbs
    *everything* is the common case and "all" is not a damage class, so
    reusing that enum would force every general shield to declare three
    members and would make the published ``damage_type`` field a join rather
    than a value.
    """

    ALL = "all"
    MAGIC = "magic"
    PHYSICAL = "physical"


@dataclass(frozen=True, slots=True)
class OpeningDefenseRule:
    """A defence already in force when the modeled exchange opens.

    ``writes`` is the resolved state this mechanic is allowed to change, and
    ``values`` every number it is allowed to read.  Both are closed on
    purpose: the resolver reaches the registry only through the declaration,
    so a mechanic cannot quietly grow a field or a key, and deleting the
    declaration takes the defence out of the fight with a named refusal
    rather than leaving a resolver reading numbers for a mechanic nothing
    declares.
    """

    mechanic: DefenseMechanic
    writes: tuple[DefenseField, ...]
    exclusivity: DefenseExclusivity
    option: DefenseOption | None
    values: tuple[AnyValueRef, ...]


@dataclass(frozen=True, slots=True)
class ThresholdDefenseRule:
    """A defence armed by the subject's health crossing a declared fraction.

    ``threshold`` and ``duration`` are ``None`` exactly where the mechanic
    has neither: Rebirth arms on lethal damage rather than on a fraction of
    health and lasts until it has resurrected, and a declared absence is a
    different statement from a reference that resolves to zero.
    """

    mechanic: DefenseMechanic
    writes: tuple[DefenseField, ...]
    exclusivity: DefenseExclusivity
    threshold: AnyValueRef | None
    duration: AnyValueRef | None
    absorbs: ShieldAbsorbs | None
    values: tuple[AnyValueRef, ...]


@dataclass(frozen=True, slots=True)
class CombatStateRule:
    """A defence that accrues, or is spent, while the fight is in progress.

    The three stacking states (Steadfast, Voidborn Resilience) and the two
    spent ones (Annul's spell shield, Time Stop's stasis) share a shape
    because what the resolver owes them is the same: the *metadata* the
    ordered ledger needs, with no stack assumed active at ``t = 0``.
    """

    mechanic: DefenseMechanic
    writes: tuple[DefenseField, ...]
    exclusivity: DefenseExclusivity
    option: DefenseOption | None
    values: tuple[AnyValueRef, ...]


@dataclass(frozen=True, slots=True)
class ReactiveRule:
    """A defence armed by an incoming event rather than by the clock.

    ``trigger`` is what arms it and ``damage_class`` is what it strikes back
    with — ``None`` for a mechanic that only shields, which is the difference
    between the Noxian boots and Thorns.  A reactive shield deliberately does
    not absorb the hit that armed it, which is why it is its own family and
    not an opening defence with a delay.
    """

    mechanic: DefenseMechanic
    writes: tuple[DefenseField, ...]
    exclusivity: DefenseExclusivity
    trigger: TriggerEvent
    absorbs: ShieldAbsorbs | None
    damage_class: DamageClass | None
    values: tuple[AnyValueRef, ...]


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
    ActiveCastRule,
    EmpoweredAutoBuffRule,
    EmpoweredHitRule,
    RepeatingStrikeRule,
    ShapedChargeRule,
    CooldownProcRule,
    UltimateProcRule,
    PeriodicRule,
    SpellbladeRule,
    AllyPacketRule,
    DeltaAmpRule,
    OnHitStrikeRule,
    ResistanceShredRule,
    SecondaryTargetRule,
    CritDamageBonusRule,
    ForcedCritRule,
    AttackCooldownRefundRule,
    OpeningDefenseRule,
    ThresholdDefenseRule,
    CombatStateRule,
    ReactiveRule,
]

# Which family each payload type belongs to.  One entry per payload; each
# migration slice adds its family's payload here, so a rule can never carry
# a payload its family does not name.
PAYLOAD_FAMILY: dict[type, RuleFamily] = {
    ActiveCastRule: RuleFamily.ACTIVE_CAST,
    EmpoweredAutoBuffRule: RuleFamily.CHARGED_STRIKE,
    EmpoweredHitRule: RuleFamily.CHARGED_STRIKE,
    RepeatingStrikeRule: RuleFamily.CHARGED_STRIKE,
    ShapedChargeRule: RuleFamily.CHARGED_STRIKE,
    CooldownProcRule: RuleFamily.CAST_PROC,
    UltimateProcRule: RuleFamily.CAST_PROC,
    PeriodicRule: RuleFamily.PERIODIC,
    SpellbladeRule: RuleFamily.SPELLBLADE,
    AllyPacketRule: RuleFamily.ALLY_PACKET,
    DeltaAmpRule: RuleFamily.DELTA_AMP,
    OnHitStrikeRule: RuleFamily.ON_HIT_STRIKE,
    ResistanceShredRule: RuleFamily.RESISTANCE_SHRED,
    SecondaryTargetRule: RuleFamily.SECONDARY_TARGET,
    CritDamageBonusRule: RuleFamily.CRIT_PROFILE,
    ForcedCritRule: RuleFamily.CRIT_PROFILE,
    AttackCooldownRefundRule: RuleFamily.CRIT_PROFILE,
    OpeningDefenseRule: RuleFamily.OPENING_DEFENSE,
    ThresholdDefenseRule: RuleFamily.THRESHOLD_DEFENSE,
    CombatStateRule: RuleFamily.COMBAT_STATE,
    ReactiveRule: RuleFamily.REACTIVE,
}

# The four defence payloads, as one tuple the validator and the resolver both
# read: every defence declaration answers "which mechanic, which state, which
# numbers" and the family it lands in says *when* rather than *what*.
DEFENSE_PAYLOAD_TYPES: tuple[type, ...] = (
    OpeningDefenseRule,
    ThresholdDefenseRule,
    CombatStateRule,
    ReactiveRule,
)


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
    if isinstance(payload, DEFENSE_PAYLOAD_TYPES):
        _validate_defense(rule, payload)
        return
    if isinstance(payload, AllyPacketRule):
        _validate_ally_packet(rule, payload)
        return
    if isinstance(payload, OnHitStrikeRule):
        _validate_formula(rule, payload.formula)
        return
    if isinstance(payload, EmpoweredHitRule):
        _validate_formula(rule, payload.formula)
        _validate_refs(rule, {"max_procs": payload.max_procs})
        return
    if isinstance(payload, RepeatingStrikeRule):
        _validate_formula(rule, payload.formula)
        _validate_refs(rule, {"hits_required": payload.hits_required})
        return
    if isinstance(payload, ShapedChargeRule):
        _validate_formula(rule, payload.formula)
        _validate_refs(rule, {"cooldown": payload.cooldown})
        return
    if isinstance(payload, EmpoweredAutoBuffRule):
        _validate_refs(
            rule,
            {
                "bonus_attack_speed_percent": payload.bonus_attack_speed_percent,
                "empowered_auto_count": payload.empowered_auto_count,
                "duration": payload.duration,
                "reduced_crit_ratio": payload.reduced_crit_ratio,
                "natural_crit_true_damage_ratio": (
                    payload.natural_crit_true_damage_ratio
                ),
            },
        )
        return
    if isinstance(payload, CooldownProcRule):
        _validate_cooldown_proc(rule, payload)
        return
    if isinstance(payload, UltimateProcRule):
        _validate_formula(rule, payload.formula)
        _validate_refs(rule, {"duration": payload.duration})
        _validate_refs(rule, {"mr_reduction": payload.mr_reduction}, optional=True)
        return
    if isinstance(payload, SpellbladeRule):
        _validate_spellblade(rule, payload)
        return
    if isinstance(payload, PeriodicRule):
        _validate_periodic(rule, payload)
        return
    if isinstance(payload, ActiveCastRule):
        _validate_formula(rule, payload.formula)
        _validate_refs(rule, {"cooldown": payload.cooldown})
        _validate_refs(
            rule,
            {"lifesteal_effectiveness": payload.lifesteal_effectiveness},
            optional=True,
        )
        return
    if isinstance(payload, SecondaryTargetRule):
        _validate_secondary_target(rule, payload)
        return
    if isinstance(payload, ResistanceShredRule):
        _validate_shred_payload(rule, payload)
        return
    if isinstance(payload, (CritDamageBonusRule, ForcedCritRule)):
        _validate_crit_profile(rule, payload)
        return
    if isinstance(payload, AttackCooldownRefundRule):
        _validate_refs(rule, {"refund_fraction": payload.refund_fraction})
        if not isinstance(payload.trigger, TriggerEvent):
            raise BehaviorRuleError(
                f"{rule.mechanic_id}: a cooldown refund names the event that "
                "refunds it"
            )
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


# Which optional field each periodic cadence is allowed — and required — to
# carry.  Presence is checked in both directions, because a field only ever
# checked one way is a field a second mechanic can quietly stop filling in.
PERIODIC_CADENCE_FIELDS: dict[PeriodicCadence, frozenset[str]] = {
    PeriodicCadence.REFRESHED_BURN: frozenset({"duration"}),
    PeriodicCadence.CONTINUOUS_AURA: frozenset(),
    PeriodicCadence.FIXED_INTERVAL: frozenset({"aoe_range_units", "self_heal_share"}),
}


def _validate_cooldown_proc(rule: BehaviorRule, payload: CooldownProcRule) -> None:
    """A cooldown proc names a trigger, a clock and whichever siblings it has."""
    _validate_formula(rule, payload.formula)
    _validate_refs(rule, {"cooldown": payload.cooldown})
    _validate_refs(
        rule,
        {"attack_cooldown_refund": payload.attack_cooldown_refund},
        optional=True,
    )
    if not isinstance(payload.trigger, ProcTrigger):
        raise BehaviorRuleError(
            f"{rule.mechanic_id}: a cooldown proc says what arms it"
        )
    for name in (
        "repeat_on_cooldown",
        "is_ability_damage",
        "basic_damage",
        "late_phase",
    ):
        if not isinstance(getattr(payload, name), bool):
            raise BehaviorRuleError(
                f"{rule.mechanic_id}: {name} is a declared bool with no default"
            )
    if (payload.threshold is not None) != (
        payload.trigger is ProcTrigger.DAMAGE_THRESHOLD
    ):
        raise BehaviorRuleError(
            f"{rule.mechanic_id}: a damage-threshold trigger carries its share "
            "and window, and no other trigger may; the two are one statement"
        )


def _validate_spellblade(rule: BehaviorRule, payload: SpellbladeRule) -> None:
    """A spellblade names a formula, two clocks and whichever siblings it has."""
    _validate_formula(rule, payload.formula)
    _validate_refs(
        rule, {"cooldown": payload.cooldown, "weave_delay": payload.weave_delay}
    )
    _validate_refs(
        rule,
        {
            "bonus_attack_speed_percent": payload.bonus_attack_speed_percent,
            "mana_restore_base_ad_ratio": payload.mana_restore_base_ad_ratio,
            "mana_restore_crit_ratio": payload.mana_restore_crit_ratio,
            "self_heal_ap_ratio": payload.self_heal_ap_ratio,
            "self_heal_bonus_health_ratio": payload.self_heal_bonus_health_ratio,
        },
        optional=True,
    )
    if not isinstance(payload.double_on_hit, bool):
        raise BehaviorRuleError(
            f"{rule.mechanic_id}: double_on_hit is a declared bool; whether the "
            "empowered attack applies on-hit effects twice has no default answer"
        )
    for pair in (
        (payload.mana_restore_base_ad_ratio, payload.mana_restore_crit_ratio),
        (payload.self_heal_ap_ratio, payload.self_heal_bonus_health_ratio),
    ):
        if (pair[0] is None) != (pair[1] is None):
            raise BehaviorRuleError(
                f"{rule.mechanic_id}: a sibling mechanic is declared whole or "
                "not at all; half of one is a parse that dropped a number"
            )


def _validate_periodic(rule: BehaviorRule, payload: PeriodicRule) -> None:
    """A periodic strike names a cadence and only that cadence's fields."""
    if not isinstance(payload.cadence, PeriodicCadence):
        raise BehaviorRuleError(
            f"{rule.mechanic_id}: a periodic strike says how it spreads over time"
        )
    _validate_formula(rule, payload.formula)
    _validate_refs(rule, {"interval": payload.interval})
    allowed = PERIODIC_CADENCE_FIELDS[payload.cadence]
    optional = {
        "duration": payload.duration,
        "aoe_range_units": payload.aoe_range_units,
        "self_heal_share": payload.self_heal_share,
    }
    _validate_refs(rule, optional, optional=True)
    for name, value in optional.items():
        if value is not None and name not in allowed:
            raise BehaviorRuleError(
                f"{rule.mechanic_id}: a {payload.cadence.value} strike declares "
                f"{name}, which belongs to a different cadence"
            )
    if payload.cadence is PeriodicCadence.REFRESHED_BURN and payload.duration is None:
        raise BehaviorRuleError(
            f"{rule.mechanic_id}: a burn is a window one hit re-arms and has to "
            "say how long that window is"
        )


def _validate_refs(
    rule: BehaviorRule,
    fields: Mapping[str, object],
    *,
    optional: bool = False,
) -> None:
    """Each named field holds a sourced reference — or, if optional, ``None``.

    ``None`` is a *declared absence*: the mechanic has no such sibling at all.
    It is deliberately distinguishable from a reference that resolves to zero,
    which would say the sibling exists and pays nothing.
    """
    for name, value in fields.items():
        if optional and value is None:
            continue
        if not isinstance(value, VALUE_REF_TYPES):
            raise BehaviorRuleError(
                f"{rule.mechanic_id}: {name} is a sourced reference, never a "
                "number in the declaration"
                + (" (or None where the mechanic has none)" if optional else "")
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
        if not isinstance(
            term.coefficient,
            (*VALUE_REF_TYPES, MeleeRangedSplit, LevelSteppedRate),
        ):
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


def _validate_defense(rule: BehaviorRule, payload: RulePayload) -> None:
    """A defence names its mechanic, the state it writes and sourced numbers.

    The three clauses are the three ways a defence declaration can be a lie:
    a mechanic outside the closed set, a field nobody can combine, and a
    number sitting in the declaration instead of a reference into the
    registry that owns it.
    """
    if not isinstance(payload.mechanic, DefenseMechanic):
        raise BehaviorRuleError(
            f"{rule.mechanic_id}: a defence names one DefenseMechanic"
        )
    for field in payload.writes:
        if field not in DEFENSE_FIELD_COMBINE:
            raise BehaviorRuleError(
                f"{rule.mechanic_id}: {field!r} is not a defensive field with a "
                "declared combine rule"
            )
    for index, reference in enumerate(payload.values):
        if not isinstance(reference, VALUE_REF_TYPES):
            raise BehaviorRuleError(
                f"{rule.mechanic_id}: value {index} is a sourced reference, "
                "never a number in the declaration"
            )
    if isinstance(payload, ThresholdDefenseRule):
        _validate_refs(
            rule,
            {"threshold": payload.threshold, "duration": payload.duration},
            optional=True,
        )
    if isinstance(payload, ReactiveRule) and not isinstance(
        payload.trigger, TriggerEvent
    ):
        raise BehaviorRuleError(
            f"{rule.mechanic_id}: a reactive defence says what arms it"
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


def _validate_crit_profile(
    rule: BehaviorRule, payload: CritDamageBonusRule | ForcedCritRule
) -> None:
    """A crit profile names its typing and, if it forces one, which strike.

    The holder is the only legal subject: a critical strike is the holder's
    own roll, so a crit profile filed against the target or an ally would be
    a rule reading a number no engine gives it.
    """
    if not isinstance(payload.typing, Typing):
        raise BehaviorRuleError(f"{rule.mechanic_id}: typing is not declared (D-04)")
    if payload.subject is not Subject.HOLDER:
        raise BehaviorRuleError(
            f"{rule.mechanic_id}: a crit profile changes the holder's own "
            "critical strikes and has no other subject"
        )
    if isinstance(payload, CritDamageBonusRule):
        _validate_refs(rule, {"bonus": payload.bonus})
        return
    if not isinstance(payload.occurrence, CritOccurrence):
        raise BehaviorRuleError(
            f"{rule.mechanic_id}: a forced crit says which strike it lands on"
        )
    _validate_refs(
        rule,
        {"reduced_ratio": payload.reduced_ratio, "cooldown": payload.cooldown},
    )
    if payload.heal is None:
        return
    if not isinstance(payload.heal, ForcedCritHeal):
        raise BehaviorRuleError(f"{rule.mechanic_id}: heal is not a ForcedCritHeal")
    _validate_refs(
        rule,
        {
            "heal.base_ad_ratio": payload.heal.base_ad_ratio,
            "heal.base_ad_ratio_ranged": payload.heal.base_ad_ratio_ranged,
            "heal.missing_health_ratio": payload.heal.missing_health_ratio,
            "heal.temporary_health_duration": payload.heal.temporary_health_duration,
        },
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


@dataclass(frozen=True, slots=True)
class DefenseSubject:
    """What a defence resolver may read about the subject it is defending.

    The defensive counterpart of :class:`BuildContext`, and separate from it
    for the reason that context exists at all: a defence reads the *holder's*
    own resolved stats and the scenario's input options, and neither is a
    fight fact a damage interpreter has any business seeing.  Nothing here is
    walk state — every field is fixed before the first event.
    """

    level: int
    stats: Mapping[str, float]
    options: Mapping[str, Mapping[str, int | float]]

    def stat(self, name: str) -> float:
        """One of the subject's resolved stats, absent meaning zero.

        Absent-means-zero is correct here and only here: the stat block is
        built by the stat resolver for every champion, so a missing key means
        the champion has none of that stat (no mana, no bonus armour) rather
        than that a rule failed to run.
        """
        return float(self.stats.get(name, 0.0))

    def max_health(self) -> float:
        """The subject's maximum health, which every subject has.

        Deliberately not :meth:`stat`: a champion with no maximum health is a
        stat block that failed to build, so this raises rather than defaulting
        — the one reading whose absence could not mean "none of that stat".
        """
        return float(self.stats["health"])

    @property
    def is_melee(self) -> bool:
        """Whether the subject pays the melee rate of a range-split defence."""
        return bool(self.stats.get("is_melee", False))

    def option(self, owner: str, option: DefenseOption) -> float:
        """One declared input option, zero when the scenario supplied none."""
        supplied = self.options.get(owner) or {}
        return float(supplied.get(option.value, 0.0))


@dataclass(frozen=True, slots=True)
class DefenseOutcome:
    """One resolved defence: the state it writes and what it disclosed.

    ``fields`` are :class:`KernelField`s like every other interpreter's
    output — value-typed, carrying the rule that produced them — so the
    resolver folds them by :data:`DEFENSE_FIELD_COMBINE` without knowing
    which mechanic wrote which.  ``notes`` are the published assumptions the
    mechanic's own interpreter phrases, kept out of the declaration because a
    sentence is presentation and criterion 6 admits no open string as policy.
    """

    fields: tuple["KernelField", ...]
    notes: tuple[str, ...]


__all__ = [
    "ACTIVATION_TYPES",
    "AMP_CHAIN_ORDER",
    "AbsoluteWindow",
    "Activation",
    "ActiveCastRule",
    "AfterTrigger",
    "AllyPacketRule",
    "AllyProducer",
    "Always",
    "AmpChainSlot",
    "AtLeast",
    "AttackCooldownRefundRule",
    "Attribution",
    "Basis",
    "BehaviorRule",
    "BehaviorRuleError",
    "BonusTyping",
    "BuildContext",
    "COMPILABILITY_TYPES",
    "CONSUMPTION_TYPES",
    "ChainTargets",
    "ChargedSplash",
    "CombatStateRule",
    "Comparison",
    "Compilability",
    "Compilable",
    "Consumption",
    "CooldownProcRule",
    "CritDamageBonusRule",
    "CritOccurrence",
    "DEFENSE_FIELD_COMBINE",
    "DEFENSE_PAYLOAD_TYPES",
    "DamageFormula",
    "DamageThreshold",
    "DefenseCombine",
    "DefenseExclusivity",
    "DefenseField",
    "DefenseMechanic",
    "DefenseOption",
    "DefenseOutcome",
    "DefenseSubject",
    "DeltaAmpRule",
    "EmpoweredAutoBuffRule",
    "EmpoweredHitRule",
    "EnergizedCharge",
    "EngineLane",
    "ExcludeTrigger",
    "FLOOR_TYPES",
    "Fixed",
    "Floor",
    "ForcedCritHeal",
    "ForcedCritRule",
    "Isolation",
    "KernelField",
    "LevelSteppedRate",
    "LivePredicate",
    "MAGNITUDE_TYPES",
    "Magnitude",
    "MeleeRangedSplit",
    "NEvents",
    "NextEventOnly",
    "NoFloor",
    "NoScaling",
    "OnHitStrikeRule",
    "OpeningDefenseRule",
    "PAYLOAD_FAMILY",
    "PERIODIC_CADENCE_FIELDS",
    "POLICY_IDENTIFIER_FIELDS",
    "PacketKind",
    "PacketSpec",
    "PacketTrigger",
    "PeriodicCadence",
    "PeriodicRule",
    "Persist",
    "Persistence",
    "Pool",
    "Probe",
    "ProcTrigger",
    "RULE_FAMILY_COUNT",
    "RampModel",
    "RampPerSecond",
    "RampPerStack",
    "ReactiveRule",
    "ReceiptOnly",
    "Recipients",
    "RepeatingStrikeRule",
    "Resistance",
    "ResistanceShredRule",
    "RuleFamily",
    "RulePayload",
    "SCALING_TYPES",
    "SUBJECT_AUTHORITY",
    "Scaling",
    "SecondaryTargetRule",
    "SelfShield",
    "ShapedChargeRule",
    "ShieldAbsorbs",
    "SpellbladeRule",
    "StackGate",
    "StackRamp",
    "Subject",
    "TRIGGER_STREAM",
    "TargetBonusHealthScaled",
    "TemporaryLethality",
    "Term",
    "ThresholdDefenseRule",
    "TimesMissingHealth",
    "TimesValue",
    "TriggerEvent",
    "TriggerWindow",
    "Typing",
    "UltimateProcRule",
    "WindowBoundary",
    "WindowMerge",
    "ZeroPolicy",
    "chain_rank",
    "is_value_reference",
    "policy_values",
    "validate_rule",
]
