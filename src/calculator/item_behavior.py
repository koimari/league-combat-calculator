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

from collections.abc import Callable, Mapping
from dataclasses import dataclass, is_dataclass
from dataclasses import fields as dataclass_fields
from enum import Enum
from typing import NamedTuple, get_args

from .ability_spec import (
    AttackClass,
    Authority,
    DamageClass,
    ZeroPolicy,
)
from .value_ref import VALUE_REF_TYPES, AnyValueRef, LevelValueRef, SourceReceipt


class BehaviorRuleError(ValueError):
    """A declaration is structurally impossible — checked without imports."""


# ── lanes and families ────────────────────────────────────────────────────


class EngineLane(Enum):
    """The engines a declared behaviour may have to be interpreted by.

    ``ClaimLane`` and ``EngineLane`` are two lane vocabularies answering
    different questions and neither is ever spelled ``Lane``: a claim lane
    says *who is claiming coverage*, an engine lane says *which engine has to
    run the rule*.

    This is the whole lane set, named once.  ``interpreters._FAMILY_LANES``
    says which of these owe each family an answer.
    """

    #: The one-attacker damage model.
    PAIR_ENGINE = "pair_engine"
    #: The coupled roster walk that serves receipts.
    RECEIPT_WALK = "receipt_walk"
    #: The compiled kernel the optimizer scores through.
    COMPILED_SCORE_WALK = "compiled_score_walk"
    #: The defensive-effects build, before any walk.
    DEFENSE_RESOLVER = "defense_resolver"
    #: The stat build, before any damage exists.
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


class UtilityDimension(Enum):
    """What an item changes about a fight besides the damage number.

    The single home of the outcome vocabulary.  Two surfaces read it and
    neither owns it: ``item_coverage`` publishes an item's dimensions in the
    coverage payload, and Phase 1's ``coverage_evidence.UTILITY_DIMENSIONS``
    is a projection of these values, so a claim and a payload cannot disagree
    about what a dimension is called.  It lives here rather than beside
    either reader because a vocabulary with two homes is two vocabularies.

    Closed, and closure is the point: a dimension that names no mechanism is
    a product label, and product labels drift into coverage claims.  A new
    member arrives with the claim that names the packet or the option
    producing it.

    Not to be confused with ``ActionKind``, and deliberately not a revival of
    the write-only survival field D-09 deleted in 0A — the deletion frontier
    still asserts that name absent from ``src/``, so this docstring does not
    spell it.  These are the *product-facing* outcome labels of a serialized
    coverage record, a different thing that happens to share a word.
    """

    ALLY_SUPPORT = "ally_support"
    ATTACK_SPEED_REDUCTION = "attack_speed_reduction"
    CLEANSE = "cleanse"
    COPIED_ON_HIT = "copied_on_hit"
    CRITICAL_MITIGATION = "critical_mitigation"
    DAMAGE_AMPLIFICATION = "damage_amplification"
    DEFENSE = "defense"
    ECONOMY = "economy"
    ENERGIZED = "energized"
    EXECUTE = "execute"
    HEALTH_STATE = "health_state"
    MOVEMENT = "movement"
    MULTI_TARGET = "multi_target"
    ON_HIT = "on_hit"
    PROGRESSION = "progression"
    QUEST = "quest"
    RANGE = "range"
    RESOURCE = "resource"
    REVIVE = "revive"
    SHIELD = "shield"
    SLOW = "slow"
    SLOW_RESISTANCE = "slow_resistance"
    SPELL_PROTECTION = "spell_protection"
    STASIS = "stasis"
    STAT_BUFF = "stat_buff"
    STAT_CONVERSION = "stat_conversion"
    SUSTAIN = "sustain"
    TAKEDOWN_STATE = "takedown_state"
    VISION = "vision"


# ── compilability (D-43) ──────────────────────────────────────────────────


class ReceiptScope(Enum):
    """*Which* of the compiled kernel's refusals a :class:`ReceiptOnly` is.

    "The compiled kernel cannot represent this" is three unrelated facts
    wearing one sentence, and folding them together is what made the
    per-owner answer unusable: an owner refused because its support template
    is a movement buff was indistinguishable from one refused because the
    score ledger cannot stage a spell shield, so the fold could answer only
    the union and no caller could ask about its own gate.  Each member below
    names one fail-closed clause in ``survival/compile.py`` and the
    population it refuses.

    ``SURVIVAL_LEDGER_TRANSITION``
        The compiled score ledger cannot *stage a state transition* the
        receipt walk authors — a consumed spell shield, a resurrection, a
        resistance reprice, deferred damage, a redirect.  This is the
        question ``uncompilable_item_receipt`` asks of a whole build, so it
        is the scope whose owners a build-level gate reads.

    ``SUPPORT_TEMPLATE_SHAPE``
        The template is a support packet the kernel stages nothing of:
        ``unrepresentable_template_receipt`` admits instantaneous shields and
        heals and refuses every other kind and every duration.

    ``SCORE_KERNEL_DAMAGE_MODIFIER``
        D-101 — a timed, typed damage modifier.  The kernel stages these
        now, so no live refusal carries this scope; it survives as the
        scope of ``item_behavior_catalog.COMPILED_KERNEL_CANNOT_AMP``, the
        one-symbol revert target for the compiled amp lane.
    """

    SURVIVAL_LEDGER_TRANSITION = "survival_ledger_transition"
    SUPPORT_TEMPLATE_SHAPE = "support_template_shape"
    SCORE_KERNEL_DAMAGE_MODIFIER = "score_kernel_damage_modifier"


@dataclass(frozen=True, slots=True)
class Compilable:
    """The compiled score kernel can represent this rule."""


@dataclass(frozen=True, slots=True)
class ReceiptOnly:
    """The compiled kernel cannot represent this rule, and here is why.

    ``reason`` is a citation, not policy: it is the sentence a fallback
    receipt prints when a build holding this rule declines to compile.
    ``scope`` is the policy half — the closed axis saying which of the
    kernel's refusals this is, so a caller can ask about its own gate
    instead of receiving the union of three.
    """

    reason: str
    scope: ReceiptScope

    def __post_init__(self) -> None:
        """A fallback with no stated cause is the silence this phase removes."""
        if not self.reason.strip():
            raise BehaviorRuleError("ReceiptOnly needs a reason")


Compilability = Compilable | ReceiptOnly

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


Activation = (
    Always
    | AbsoluteWindow
    | TriggerWindow
    | AfterTrigger
    | ExcludeTrigger
    | LivePredicate
)

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


Consumption = Persist | NextEventOnly | NEvents

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


class HolderStat(Enum):
    """A resolved stat of the holder a magnitude may scale with.

    Closed, and spelled the way the stat resolver spells it, so a magnitude
    naming one is asking for a stat that exists rather than for a key that
    silently resolves to nothing.  It is *not* :class:`Probe`: a probe reads
    a live pool mid-simulation and cannot be compiled, while a holder stat is
    fixed before the first event and is simply not a registry number.
    """

    BONUS_MANA = "bonus_mana"


@dataclass(frozen=True, slots=True)
class StatScaled:
    """A sourced base fraction plus a sourced rate per 100 units of a stat.

    Actualizer's Mana Made Real is 15% ability damage plus 0.5% per 100 bonus
    mana: two sourced numbers and one build fact that is neither a registry
    value nor a fight configuration.  The stat is *named* rather than
    resolved here — the reading is handed in at use, the same asymmetry
    :class:`LivePredicate` carries for a live pool — because an interpreter
    that resolved the holder's stat block would be a second stat resolver.
    """

    base: AnyValueRef
    per_hundred: AnyValueRef
    stat: HolderStat


Magnitude = (
    Fixed
    | RampPerSecond
    | TargetBonusHealthScaled
    | RampPerStack
    | MeleeRangedSplit
    | StatScaled
)

MAGNITUDE_TYPES: tuple[type, ...] = (
    Fixed,
    RampPerSecond,
    TargetBonusHealthScaled,
    RampPerStack,
    MeleeRangedSplit,
    StatScaled,
)


# ── the remaining policy axes ─────────────────────────────────────────────


class Pool(Enum):
    """Which events a rule is allowed to price."""

    ALL_EVENTS = "all_events"
    CERTIFIED_ONLY = "certified_only"
    COARSE_ROW = "coarse_row"


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
    """The eight ordered positions of the damage-amplifier chain.

    Amplification is not commutative: each slot multiplies a total the
    slots before it already moved, so the order *is* part of every mixed
    build's number.  Today that order is an accident of the call sequence in
    ``damage.py`` and nothing stops a refactor changing it.  Naming the
    positions makes the order a declaration, and
    :func:`chain_rank` is the only place a rule's ``lane_chain_rank`` comes
    from.

    A slot is a *position*, not a mechanic: several mechanics share
    ``WHOLE_TOTAL``, which is the one slot whose occupants are additive among
    themselves before the chain multiplies, and ``TARGET_HEALTH_GATE`` holds
    the rune page's two target-health amplifiers, of which a legal page can
    select at most one.  These are also **not** Phase 4's seven authority
    moves — the two sets overlap and neither contains the other.
    """

    CINDERBLOOM = "cinderbloom"
    EXPOSE_WEAKNESS = "expose_weakness"
    OPENING_WINDOW = "opening_window"
    LASTING_PROC_AMP = "lasting_proc_amp"
    WHOLE_TOTAL = "whole_total"
    POST_IMMOBILIZE = "post_immobilize"
    HYPERSHOT = "hypershot"
    TARGET_HEALTH_GATE = "target_health_gate"


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
    AmpChainSlot.TARGET_HEALTH_GATE,
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

    base: AnyValueRef | MeleeRangedSplit
    per_level: AnyValueRef | MeleeRangedSplit
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

    coefficient: AnyValueRef | MeleeRangedSplit | LevelSteppedRate
    basis: Basis


@dataclass(frozen=True, slots=True)
class NoFloor:
    """The formula's sum stands as computed."""


@dataclass(frozen=True, slots=True)
class AtLeast:
    """The formula never pays less than a sourced minimum."""

    value: AnyValueRef


Floor = NoFloor | AtLeast

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


Scaling = NoScaling | TimesValue | TimesMissingHealth

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


@dataclass(frozen=True, slots=True)
class DecayingAttackStacks:
    """Bonus attack speed gained one stack per attack and expiring per stack.

    Each completed attack adds a stack that lives for ``stack_duration`` and
    then falls off on its own, so the bonus rises while the holder keeps
    attacking and decays the moment it stops.  ``per_stack`` is a *fraction*
    because that is the unit the registry states it in; the schedule scales it
    by the holder's attack-speed ratio like every other bonus percentage.
    """

    per_stack: AnyValueRef
    max_stacks: AnyValueRef
    stack_duration: AnyValueRef


@dataclass(frozen=True, slots=True)
class RefundedAttackWindow:
    """An attack-speed window the holder's own attacks re-arm early.

    The window opens for ``duration`` and then waits ``cooldown``; every
    attack after the first pays that cooldown down by ``refund_per_attack``
    plus ``refund_per_crit`` weighted by the holder's critical-strike chance.
    The refund is of *this window's* cooldown and of nothing else — it is not
    the crit family's ability-cooldown refund, which reads a different number
    off a different mechanic.
    """

    bonus_attack_speed_percent: AnyValueRef
    duration: AnyValueRef
    cooldown: AnyValueRef
    refund_per_attack: AnyValueRef
    refund_per_crit: AnyValueRef


@dataclass(frozen=True, slots=True)
class SwingScheduleRule:
    """The rate the holder's *own* basic attacks land at, attack by attack.

    The second member of this family that deals no damage of its own.  Where
    :class:`EmpoweredAutoBuffRule` re-rates a bounded run of attacks off an
    ultimate, this one re-rates the whole stream off the stream itself: a
    ramp the attacks build, a window the attacks re-arm, or both at once on a
    build holding two such items.  It lands in the strike family because that
    is where the auto stream's schedule already lives — the engine reads this
    and the empowered-auto window from one record and picks one schedule.

    Both mechanics are optional and at least one is present, checked rather
    than assumed: a schedule that schedules nothing is a parse that dropped a
    key group, not an item whose attacks land at the ordinary rate.

    ``schedules_single_rotation`` says whether a fight the request declared to
    be one rotation is scheduled by this mechanic at all.  It is the engine's
    long-standing gate, declared: a ramp was excluded from that fight and a
    re-armed window was not.  No sourced reading distinguishes the two, so
    what this field carries is the behaviour, named — the point being that a
    future correction is one edit against an axis rather than a rediscovery
    of two item names.
    """

    decaying_stacks: DecayingAttackStacks | None
    refunded_window: RefundedAttackWindow | None
    schedules_single_rotation: bool


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

    Which siblings an entry carries is decided by
    ``item_behavior_catalog``'s sibling groups: a group is declared whole or
    not at all, so a parse that dropped half of Essence Reaver's mana refund
    is a stop rather than a quietly weaker item, and no item name is compared.

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
    stack: Vile Decay reads magic damage only, declared here rather than
    compared inside the rotation loop.
    """

    resistance: Resistance
    ramp: StackRamp
    typing: Typing
    subject: Subject


@dataclass(frozen=True, slots=True)
class DeltaAmpRule:  # pylint: disable=too-many-instance-attributes
    """One amplification slot: which events, when, how much, and to whom.

    One field per independent question the amp chain asks; collapsing any
    two of them is what let a pair-side preview and a coupled number both
    call themselves the answer.  ``lane_chain_rank`` is an
    explicit integer: the chain slots are ordered, nothing in the
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
    typing: Typing
    bonus_typing: BonusTyping
    subject: Subject
    lane_chain_rank: int


@dataclass(frozen=True, slots=True)
class PartAmpRule:  # pylint: disable=too-many-instance-attributes
    """An amplifier that multiplies each part it prices, not the fight's total.

    Every :class:`AmpChainSlot` position acts on one running total,
    in an order that is part of every mixed build's number.  Two registry
    schemas are not in that chain at all: Actualizer amplifies each ability's
    own damage where the rotation prices it, and Hexoptics C44 amplifies each
    basic-damage part where the auto-attack path prices it.  Giving them a
    chain rank would claim an ordering against the chain that they do not
    have, so they carry the same policy axes with the rank deliberately
    absent — the one field whose meaning is "which position of the chain".

    ``typing.attack_classes`` is what tells the two apart and is how the
    engine asks for one: "the amplifier that prices basic attacks" is a
    question about damage, not about an item's name.
    """

    pool: Pool
    activation: Activation
    consumption: Consumption
    magnitude: Magnitude
    typing: Typing
    bonus_typing: BonusTyping
    subject: Subject


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


# ── damage routing ────────────────────────────────────────────────────────
#
# Three mechanics that change **where a damage packet goes** rather than how
# big it is: a threshold below which a strike finishes the target, a share of
# the target's shielding a strike passes through instead of being absorbed
# by, and a deferral that stores post-mitigation damage and pays it back over
# ticks.  None of them is an amplifier and none of them is a defence the
# holder keeps — which is why they are one family and why the deferral, whose
# registry entry is tagged as a starting defence, is filed here.


@dataclass(frozen=True, slots=True)
class ExecuteRule:
    """Below a sourced share of the target's health, the strike finishes it.

    The threshold is a *routing* fact rather than a magnitude: nothing about
    the damage changes, and what changes is whether the packet ends the
    fight.  ``typing`` says which damage may execute, so an item that only
    executes with basic attacks is expressible without a second field.
    """

    threshold: AnyValueRef
    typing: Typing
    subject: Subject


@dataclass(frozen=True, slots=True)
class ShieldBypassRule:
    """A share of the target's shielding a strike passes through, for a window.

    The share is a :class:`MeleeRangedSplit` because the registry pays melee
    and ranged holders differently, and that choice is made once per build
    from the holder's range class rather than per event.  ``duration`` is how
    long the window the trigger opens stays open.
    """

    fraction: MeleeRangedSplit
    duration: AnyValueRef
    trigger: TriggerEvent
    typing: Typing
    subject: Subject


@dataclass(frozen=True, slots=True)
class DamageDeferralRule:
    """Post-mitigation damage stored and repaid over declared ticks.

    Shaped like a defence — it carries a :class:`DefenseMechanic`, writes
    resolved defensive state and reads its numbers as references — because
    the resolver builds it at the opening with every other defence.  What it
    *is* is a routing rule: the damage is not reduced, it is moved in time,
    and filing it under a defence family would say the holder took less.
    """

    mechanic: DefenseMechanic
    writes: tuple[DefenseField, ...]
    exclusivity: DefenseExclusivity
    values: tuple[AnyValueRef, ...]


# ── sustain ───────────────────────────────────────────────────────────────
#
# Five shapes that all put health back, and share no arithmetic at all: a
# vampirism stat the build's stat block folds, a share of damage dealt paid
# straight back, a resource drain that only becomes health when there is no
# resource to fill, a heal bought with mana spent, and a regeneration window
# a hit opens.  The sixth is the multiplier on everything a subject
# *receives*, which is shaped like a defence because the resolver builds it
# after every shield it multiplies.


class SustainStat(Enum):
    """Which vampirism stat a grant contributes to.

    Two members, because the two really do behave differently — life steal
    reads basic-attack damage and omnivamp reads every source — and the
    registry pins them under two keys the build's stat fold reads separately.
    """

    LIFESTEAL_PERCENT = "lifesteal_percent"
    OMNIVAMP_PERCENT = "omnivamp_percent"


@dataclass(frozen=True, slots=True)
class RampSaturation:
    """A per-second ramp, named by the two numbers that say when it tops out.

    Declared as the ramp rather than as the saturation *time* because the
    time is not a number the registry states: it is ``maximum / per_second``,
    and a declaration holding the quotient would be holding a number nobody
    sourced.  What arms on saturation is the sibling grant this record hangs
    off, never the ramp itself.
    """

    per_second: AnyValueRef
    maximum: AnyValueRef


@dataclass(frozen=True, slots=True)
class SustainStatRule:
    """A sourced vampirism percentage the build's stat fold sums.

    ``overrides_cached_stat`` is the honest half: a few item pages replaced a
    stat passive with a named effect, and the registry pins the correction
    under a ``stat_override_`` key that *wins over* the cached stat block
    rather than adding to it.  Declaring which of the two a grant is keeps
    "the wiki stat is wrong and here is the right one" from looking like
    "here is a second source of life steal".

    ``arms_at`` is the third thing a grant can be, and it is the reason this
    payload has three states rather than two: a grant the *stat block does
    not carry at all* until a ramp elsewhere on the same entry saturates.
    Riftmaker's Void Corruption is the live case — the omnivamp is a fight
    state, not a stat, which is why the engine adds it to a private copy of
    the resolved block partway through resolving the fight.  ``None`` is the
    declared absence: the grant is in the block from the first tick.

    ``percent`` may be a :class:`MeleeRangedSplit` because a saturating grant
    pays a melee holder more than a ranged one, and the choice is made once
    per build from a stat rather than per event.
    """

    stat: SustainStat
    percent: AnyValueRef | MeleeRangedSplit
    overrides_cached_stat: bool
    arms_at: RampSaturation | None
    subject: Subject


@dataclass(frozen=True, slots=True)
class PostMitigationHealRule:
    """A share of damage dealt, paid straight back as health.

    ``area_effectiveness`` is the conservative share paid where the damage's
    scope is not a single-target basic attack — an assumption, declared,
    because the model cannot tell an area ability from a single-target one
    for every champion and pricing the full share would overpay.
    """

    ratio: AnyValueRef
    area_effectiveness: AnyValueRef
    subject: Subject


@dataclass(frozen=True, slots=True)
class OnHitHealRule:
    """A flat amount of health one authored on-hit application restores.

    The plainest sustain there is, and it still declares its trigger: "on
    hit" is a stream the bus carries, and a heal that named no trigger would
    be a number with no event to attach it to.
    """

    amount: AnyValueRef
    trigger: TriggerEvent
    subject: Subject


@dataclass(frozen=True, slots=True)
class ResourceDrainRule:
    """A tick that restores resource first and heals only when it cannot.

    Five references because the drain answers five questions: the resting
    rate, the rate while recently in combat, how long "recently" lasts, what
    share of an unusable restore becomes health, and how often it ticks.
    """

    restoration_per_second: AnyValueRef
    combat_restoration_per_second: AnyValueRef
    combat_window: AnyValueRef
    health_conversion: AnyValueRef
    tick_interval: AnyValueRef
    subject: Subject


@dataclass(frozen=True, slots=True)
class ManaSpentHealRule:
    """A heal bought with mana spent, capped per cast and per second.

    ``damage_taken_to_mana_ratio`` is the other half of the same passive and
    is declared here rather than in a second rule: one entry, one mechanic,
    and the roster walk that reads the restore and the pair path that reads
    the heal are two readers of one declaration.
    """

    heal_ratio: AnyValueRef
    cap_per_cast: AnyValueRef
    cap_per_second: AnyValueRef
    damage_taken_to_mana_ratio: AnyValueRef
    subject: Subject


@dataclass(frozen=True, slots=True)
class RegenerationRule:
    """A regeneration window a qualifying hit opens, capped by missing health.

    ``total_melee`` and ``total_reduced`` are the whole window's amounts, not
    per-tick rates: the registry states what the window is worth and the
    tick interval says how it is paid out, which is the one arrangement that
    survives a patch changing either independently.
    """

    total_melee: AnyValueRef
    total_reduced: AnyValueRef
    duration: AnyValueRef
    missing_health_cap: AnyValueRef
    tick_interval: AnyValueRef
    subject: Subject


@dataclass(frozen=True, slots=True)
class BelowHalfHealingRule:
    """A bonus share on healing the holder receives while under half health.

    The sibling of :class:`ReceivedHealingRule`, and deliberately not the
    same shape: that one is a flat multiplier the defensive resolver builds
    into the opening state, and this one only exists once the fight has taken
    the holder below the boundary, so it is state the walk consults per
    recovery rather than a number resolved before the walk starts.

    Half is in the name because half is the mechanic.  The registry publishes
    the bonus under a key that spells its own gate
    (``health_state_healing_multiplier_below_half``, "while below 50% of your
    maximum health" on the source page) and publishes no threshold key, so
    the boundary is the declaration's identity rather than a number a
    declaration could carry.  A future item gated at another fraction is a
    new member here, not a defaulted field on this one — closure is the test,
    not the arity.
    """

    bonus: AnyValueRef
    subject: Subject


@dataclass(frozen=True, slots=True)
class ReceivedHealingRule:
    """A multiplier on every heal and shield the subject receives.

    Shaped like a defence — it carries a :class:`DefenseMechanic`, writes
    resolved defensive state and reads its numbers as references — because
    the resolver builds it, and it has to run *after* every shield it
    multiplies, which makes its position in the resolution order arithmetic
    rather than presentation.
    """

    mechanic: DefenseMechanic
    writes: tuple[DefenseField, ...]
    exclusivity: DefenseExclusivity
    values: tuple[AnyValueRef, ...]


# ── stat derivation ───────────────────────────────────────────────────────
#
# The shapes that all answer one question — what does this item put in the
# build's stat block, and where does the number come from — and share no
# arithmetic.  ``STAT_DERIVATION_REQUIRED_REFERENCES`` is the roster and the
# only count of it; each payload class below says what its own shape answers.
#
# They are one family because they are all resolved *before any damage
# exists*: the stat resolver folds them into the block every engine then
# reads, which is why this family's lanes are the resolver and the pair
# engine and not either walk.


class DerivedStat(Enum):
    """The stat a derivation produces.

    Named after the field of the build's stat block it feeds, so a reader
    can follow a declaration to the number it moves without a translation
    table in between.
    """

    ABILITY_POWER = "ability_power"
    ATTACK_DAMAGE = "attack_damage"
    HEALTH = "health"
    HEALTH_REGEN = "health_regen"
    MANA = "mana"
    HEAL_AND_SHIELD_POWER = "heal_and_shield_power"
    ADAPTIVE_FORCE = "adaptive_force"
    ABILITY_HASTE = "ability_haste"
    ULTIMATE_HASTE = "ultimate_haste"
    ATTACK_SPEED_PERCENT = "attack_speed_percent"
    CRITICAL_STRIKE_CHANCE = "critical_strike_chance"
    OMNIVAMP_PERCENT = "omnivamp_percent"
    ARMOR_PENETRATION_PERCENT = "armor_penetration_percent"
    ARMOR_PENETRATION_BONUS_PERCENT = "armor_penetration_bonus_percent"


class StatBasis(Enum):
    """The stat a conversion reads.

    Closed, and deliberately finer than :class:`DerivedStat`: a conversion
    that read "mana" would not say whether it means the bonus mana Awe
    converts or the maximum mana Muramana does, and those two are different
    numbers on every build that owns a mana item.
    """

    BONUS_MANA = "bonus_mana"
    MAX_MANA = "max_mana"
    BONUS_HEALTH = "bonus_health"
    BASE_ATTACK_DAMAGE = "base_attack_damage"
    BONUS_ATTACK_DAMAGE = "bonus_attack_damage"
    BONUS_MANA_REGEN_PERCENT = "bonus_mana_regen_percent"
    TOTAL_MOVE_SPEED = "total_move_speed"


class StatAvailability(Enum):
    """When a granted stat is in the block the engines read.

    The family's honesty axis, and the reason this migration is worth
    making: three of these grants are conditional buffs that the stat
    resolver folds in **whole**, because it has no event to arm them from —
    ``item_effects.passive_attack_speed_bonus`` calls them "assumed-active"
    in a docstring, and a docstring is exactly the kind of claim this
    campaign converts into a field.  Two more exist only when the request's
    item options say the window is open, which is a different thing again
    from an unconditional grant.
    """

    ALWAYS = "always"
    ASSUMED_ACTIVE = "assumed_active"
    BUILD_OPTION = "build_option"


@dataclass(frozen=True, slots=True)
class StatConversionRule:
    """One stat derived from another by a sourced ratio.

    ``basis_unit`` is the size of one unit of the basis where the registry
    states the rate per unit rather than per point — Dawncore pays its AP per
    100% of base mana regeneration, and folding that 100 into the ratio would
    make a patch that changed the unit unreadable.  ``flat_base`` is the part
    of the grant that does not scale at all.  Both are declared absences
    rather than zeros where the conversion has neither.
    """

    basis: StatBasis
    granted: DerivedStat
    ratio: AnyValueRef | MeleeRangedSplit
    basis_unit: AnyValueRef | None
    flat_base: AnyValueRef | None
    availability: StatAvailability
    subject: Subject


@dataclass(frozen=True, slots=True)
class StatMultiplierRule:
    """A sourced share by which a total stat is increased.

    Distinct from a conversion because the basis *is* the granted stat: what
    Rabadon's does to ability power cannot be said as "so much AP per unit of
    something else" without inventing a basis the item does not have.
    """

    granted: DerivedStat
    share: AnyValueRef
    availability: StatAvailability
    subject: Subject


@dataclass(frozen=True, slots=True)
class PenetrationChannelRule:
    """Which half of a resistance a holder's percentage penetration reaches.

    The only stat derivation that carries no number of its own, and it is a
    declaration for exactly that reason: the percentage is a cached stat the
    block already reads, and what the cache does not say is whether it cuts
    total armour or bonus armour alone.  Declaring it means a new such item
    states its channel instead of being routed to the ordinary one by silence.

    ``granted`` names the stat-block field the cached percentage lands in, so
    the two channels are two members of the same closed enum rather than a
    boolean somebody has to remember the polarity of.
    """

    granted: DerivedStat
    availability: StatAvailability
    subject: Subject


class RestrictedChannel(Enum):
    """A channel a sourced item number reaches that no stat block holds.

    The champion-versus-champion stat block is not a member, and that is the
    point: a number declared here is real and sourced, and what the
    declaration says is that it lands somewhere the block does not — so
    reading it into an ability haste pool or a champion-class on-hit packet
    would be the silent mis-channelling this enum refuses.

    A member either runs nowhere this model reaches at all, or runs only for
    a fight whose own target class selects it; which of the two is
    :data:`RESTRICTED_CHANNEL_PACKETS`, not a reader's memory.
    """

    SUMMONER_SPELL_HASTE = "summoner_spell_haste"
    MINION_CLASS_ON_HIT = "minion_class_on_hit"


@dataclass(frozen=True, slots=True)
class RestrictedPacket:
    """The damage row a restricted channel becomes when its class is the fight's.

    Declared beside the channel rather than on the rule, because it is the
    *channel's* shape: every entry routing a number down one channel pays the
    same row, and a copy on each rule would be that many chances to disagree.
    It says the row's target class, its damage class and the passive it
    previews — never its number, which stays the rule's own ``amount``.
    """

    target_class: str
    damage_class: DamageClass
    mechanic: str


# Which channels are a real packet, and what that packet is.  Total over the
# enum — a member with no packet says ``None`` out loud — because "does this
# channel arm anything" decided by a lookup miss is how a sourced number
# starts riding a fight nobody declared it for.
RESTRICTED_CHANNEL_PACKETS: dict[RestrictedChannel, RestrictedPacket | None] = {
    RestrictedChannel.SUMMONER_SPELL_HASTE: None,
    RestrictedChannel.MINION_CLASS_ON_HIT: RestrictedPacket(
        target_class="minion",
        damage_class=DamageClass.PHYSICAL,
        mechanic="Helping Hand",
    ),
}


@dataclass(frozen=True, slots=True)
class RestrictedChannelRule:
    """Where a sourced number lands when no stat block holds its channel.

    The sibling of :class:`PenetrationChannelRule`: both say only *which
    channel* a number reaches and neither puts anything in the block, which
    is why neither counts as runtime behaviour there.  The difference is that
    a penetration channel picks between two stat-block fields, and here the
    channel is outside the block entirely — Ionian Insight's haste pays
    summoner spells and Helping Hand's bonus damage pays minions.

    ``amount`` is carried rather than dropped so the sourced number has a
    declared home with its receipt, instead of living only in a sentence
    beside the entry.  Whether the channel is armed by any fight at all, and
    what row it becomes there, is the channel's own answer in
    :data:`RESTRICTED_CHANNEL_PACKETS`.
    """

    channel: RestrictedChannel
    amount: AnyValueRef
    availability: StatAvailability
    subject: Subject


@dataclass(frozen=True, slots=True)
class ResourceRestoreRule:
    """A share of the holder's maximum resource restored over a sourced window.

    Three references because the mechanic answers three questions: what share
    of the maximum it restores, over how long, and in how many ticks.  The
    tick count is declared rather than divided out of the duration, because
    the registry states it and a derived count would silently re-time the
    schedule whenever either of the other two moved.
    """

    granted: DerivedStat
    share_of_maximum: AnyValueRef
    duration: AnyValueRef
    ticks: AnyValueRef
    availability: StatAvailability
    subject: Subject


@dataclass(frozen=True, slots=True)
class ManaflowRule:
    """The charge ledger that accrues permanent bonus mana.

    Both ceilings are optional and they are not the same ceiling: a charge
    cap says how many charges the ledger banks, and ``transform_bonus_mana``
    says the mana at which the item becomes another item.  Tear of the
    Goddess carries the first and not the second — it banks four charges and
    transforms into nothing — so the refusal is one-way: a transform with no
    charge cap is a parse that dropped a key, while a cap with no transform
    is an ordinary component ledger.
    """

    granted: DerivedStat
    charge_interval: AnyValueRef
    bonus_mana_per_trigger: AnyValueRef
    bonus_mana_per_champion: AnyValueRef
    bonus_mana_max: AnyValueRef
    max_charges: AnyValueRef | None
    transform_bonus_mana: AnyValueRef | None
    availability: StatAvailability
    subject: Subject


@dataclass(frozen=True, slots=True)
class StackedStatRule:
    """A stat that grows per stack, with the ceiling the registry states.

    ``max_stacks`` and ``cap`` are two different ceilings and both exist:
    Yun Tal's crit conversion is bounded by a stack count *and* by a share of
    critical strike chance, and a declaration carrying only one of them would
    over-pay every ranged holder.  ``flat_base`` is the part granted at zero
    stacks and ``duration`` the window a stack survives, both declared
    absences where the mechanic has neither.
    """

    granted: DerivedStat
    per_stack: AnyValueRef | MeleeRangedSplit
    max_stacks: AnyValueRef | MeleeRangedSplit | None
    cap: AnyValueRef | None
    flat_base: AnyValueRef | None
    duration: AnyValueRef | None
    grants_level_at_max: AnyValueRef | None
    availability: StatAvailability
    subject: Subject


@dataclass(frozen=True, slots=True)
class FlatStatGrantRule:
    """A sourced amount of one stat, granted whole.

    The shape whose ``availability`` carries the weight: the same record
    describes Hexplate's unconditional ultimate haste and the attack speed
    the resolver folds in on an assumption, and the field is what keeps
    those two apart in a payload that is otherwise identical.
    """

    granted: DerivedStat
    amount: AnyValueRef | MeleeRangedSplit
    duration: AnyValueRef | None
    cooldown: AnyValueRef | None
    trigger_window: AnyValueRef | None
    availability: StatAvailability
    subject: Subject


@dataclass(frozen=True, slots=True)
class StatAuraRule:
    """A stat reduced on everyone inside a sourced radius.

    The one member of the family whose subject is not the holder, and the
    reason ``subject`` is a field rather than an assumption: the number lands
    on the enemy and the *benefit* lands on the holder, which is what makes
    it a durability mechanic on the target lane.
    """

    granted: DerivedStat
    reduction: AnyValueRef
    radius: AnyValueRef
    availability: StatAvailability
    subject: Subject


@dataclass(frozen=True, slots=True)
class ThresholdRegenRule:
    """A regeneration a bonus-health threshold unlocks and damage suspends.

    Five references because the mechanic answers five questions: how much
    bonus health arms it, what share of maximum health a tick pays, how often
    it ticks, and how long champion and non-champion damage hold it shut.
    Two cooldowns and not one: they are different numbers and a single
    "damage cooldown" would silently pick one.
    """

    granted: DerivedStat
    bonus_health_threshold: AnyValueRef
    share_of_max_health: AnyValueRef
    tick_interval: AnyValueRef
    champion_damage_cooldown: AnyValueRef
    nonchampion_damage_cooldown: AnyValueRef
    availability: StatAvailability
    subject: Subject


@dataclass(frozen=True, slots=True)
class UltimateRefundRule:
    """A share of the ultimate's cooldown refunded, bought with lethality.

    A derived stat rather than a proc: the number it produces is a property
    of the build's lethality, resolved once before the fight, and the window
    is the takedown window the refund is paid inside.
    """

    base_ratio: AnyValueRef
    per_lethality_ratio: AnyValueRef
    trigger_window: AnyValueRef
    availability: StatAvailability
    subject: Subject


@dataclass(frozen=True, slots=True)
class ActiveWindowCastEconomyRule:
    """What an item's own active window costs the holder's casting economy.

    The other half of an active that deals no damage: while its window is
    open the holder's abilities cost more resource and their cooldowns
    progress faster.  Both are multipliers on numbers the rotation already
    has, resolved once from the same registry entry that declares the window,
    which is why this is a derivation rather than a proc — and, like the
    ultimate refund, why it grants no :class:`DerivedStat`: it moves a cost
    and a cooldown, and naming a stat for either would invent one the block
    does not hold.

    ``window`` is the active's declared duration, the same reference the
    entry's amp declares its :class:`AbsoluteWindow` end from.  It is carried
    here rather than looked up so that a reader holding this rule can say how
    long the trade lasts without reaching into another declaration.
    """

    resource_cost_multiplier: AnyValueRef
    basic_cooldown_progress_multiplier: AnyValueRef
    window: AnyValueRef
    availability: StatAvailability
    subject: Subject


# Which granted stats make an item's holder harder to kill.  Read by
# ``item_coverage`` to decide whether a stat derivation belongs on the
# passive-target lane, so "does this change durability" is answered by the
# declaration rather than by an item name.
DURABILITY_STATS: frozenset[DerivedStat] = frozenset(
    {DerivedStat.HEALTH, DerivedStat.HEALTH_REGEN}
)


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
    UNDAUNTED = "undaunted"
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
    CHAMPION_DAMAGE_FLAT_REDUCTION = "champion_damage_flat_reduction"
    CHAMPION_DOT_DAMAGE_FLAT_REDUCTION = "champion_dot_damage_flat_reduction"
    CHAMPION_DAMAGE_FLAT_SOURCE = "champion_damage_flat_source"
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
    DefenseField.CHAMPION_DAMAGE_FLAT_REDUCTION: DefenseCombine.SET,
    DefenseField.CHAMPION_DOT_DAMAGE_FLAT_REDUCTION: DefenseCombine.SET,
    DefenseField.CHAMPION_DAMAGE_FLAT_SOURCE: DefenseCombine.SET,
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
    registry**, a tie-break that names no item.
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
    NIGHTSTALKER = "nightstalker"
    # explicit actives
    DEVOTION = "devotion"
    PURIFY = "purify"
    INTERVENTION = "intervention"
    INSPIRING_SPEECH = "inspiring_speech"
    BREAKING_SHOCKWAVE = "breaking_shockwave"


class PacketKind(Enum):
    """The kinds a cross-participant packet may be built with.

    Closed over ``item_support_effects``' ``kind=`` arguments, so a static
    reader can resolve every kind.  Moonstone Renewer chains off two triggers
    and declares both kinds rather than computing one at runtime, which no
    static reader could follow.
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
    # The three the emitters built but the enum did not name until the
    # utility census stopped reading its eight kinds as bare strings.
    # ``ITEM_DENIAL`` is a packet the same way the others are — it is
    # built by the same emitter, in the same list — but it says a mechanic
    # was *withheld*, so it leaves the applied stream for a receipt.
    CLEANSE = "cleanse"
    RESOURCE = "resource"
    ITEM_DENIAL = "item_denial"


def is_packet_kind(packet: Mapping[str, object], kind: PacketKind) -> bool:
    """Whether *packet* was built with *kind*, read through the one vocabulary."""
    return packet.get("kind") == kind.value


def is_denial_receipt(packet: Mapping[str, object]) -> bool:
    """Whether *packet* is the fail-closed item-denial receipt."""
    return is_packet_kind(packet, PacketKind.ITEM_DENIAL)


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


class LevelSubject(Enum):
    """Whose level a support packet's level ramp is read at.

    The cached Wiki sentence *states* this, so the emitters read it rather
    than guess: a ramp read at the wrong level prices the four producers the
    source scales on the holder at whatever level the ally happens to be.
    Members are spelled the way the source spells them —
    ``{{pp|150 to 350|type=target's level}}`` against an unqualified
    ``{{pp|80 to 250}}``, whose bare "based on level" is the item owner's —
    so a declaration and the sentence it was read from compare without a
    translation table.
    """

    HOLDER = "your level"
    RECIPIENT = "target's level"


@dataclass(frozen=True, slots=True)
class DeclaredRamp:
    """A level ramp as an owner-free catalog table declares it.

    Two shapes for one fact, because the catalog's producer tables are
    owner-free by construction — two items carry the support quest and share
    one declaration — so a table entry can only name the registry *keys*.
    :class:`LevelRamp` is the same ramp once an owner binds it.
    """

    min_key: str
    max_key: str
    subject: LevelSubject


@dataclass(frozen=True, slots=True)
class LevelRamp:
    """One compiled level ramp: the reference that reads it, and whose level.

    The reference is the very object the rule's ``values`` carries, so the
    ramp and the number it scales cannot come apart, and the registry keys
    stay behind a value reference rather than becoming open strings on a
    policy axis.
    """

    reference: LevelValueRef
    subject: LevelSubject

    @property
    def min_key(self) -> str:
        """The ramp's low key — how every declaration and emitter names it."""
        return self.reference.min_key


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

    ``ramps`` is the same list's level-scaled half, restated with the one fact
    a :class:`~.value_ref.LevelValueRef` cannot carry: whose level reads it
    (:class:`LevelSubject`).  Every ramp in ``values`` appears here exactly
    once, which :func:`validate_rule` checks, so a producer cannot grow a
    ramp whose subject nothing states.
    """

    producer: AllyProducer
    trigger: PacketTrigger
    packets: tuple[PacketSpec, ...]
    secondary_target: Recipients | None
    persistence: Persistence
    redirects_incoming_damage: bool
    values: tuple[AnyValueRef, ...]
    ramps: tuple[LevelRamp, ...]


RulePayload = (
    ActiveCastRule
    | EmpoweredAutoBuffRule
    | EmpoweredHitRule
    | SwingScheduleRule
    | RepeatingStrikeRule
    | ShapedChargeRule
    | CooldownProcRule
    | UltimateProcRule
    | PeriodicRule
    | SpellbladeRule
    | AllyPacketRule
    | DeltaAmpRule
    | PartAmpRule
    | OnHitStrikeRule
    | ResistanceShredRule
    | SecondaryTargetRule
    | CritDamageBonusRule
    | ForcedCritRule
    | AttackCooldownRefundRule
    | ExecuteRule
    | ShieldBypassRule
    | DamageDeferralRule
    | SustainStatRule
    | OnHitHealRule
    | PostMitigationHealRule
    | ResourceDrainRule
    | ManaSpentHealRule
    | RegenerationRule
    | ReceivedHealingRule
    | BelowHalfHealingRule
    | StatConversionRule
    | StatMultiplierRule
    | PenetrationChannelRule
    | RestrictedChannelRule
    | ResourceRestoreRule
    | ManaflowRule
    | StackedStatRule
    | FlatStatGrantRule
    | StatAuraRule
    | ThresholdRegenRule
    | UltimateRefundRule
    | ActiveWindowCastEconomyRule
    | OpeningDefenseRule
    | ThresholdDefenseRule
    | CombatStateRule
    | ReactiveRule
)

# Which family each payload type belongs to.  One entry per payload; each
# migration slice adds its family's payload here, so a rule can never carry
# a payload its family does not name.
PAYLOAD_FAMILY: dict[type, RuleFamily] = {
    ActiveCastRule: RuleFamily.ACTIVE_CAST,
    EmpoweredAutoBuffRule: RuleFamily.CHARGED_STRIKE,
    EmpoweredHitRule: RuleFamily.CHARGED_STRIKE,
    RepeatingStrikeRule: RuleFamily.CHARGED_STRIKE,
    ShapedChargeRule: RuleFamily.CHARGED_STRIKE,
    SwingScheduleRule: RuleFamily.CHARGED_STRIKE,
    CooldownProcRule: RuleFamily.CAST_PROC,
    UltimateProcRule: RuleFamily.CAST_PROC,
    PeriodicRule: RuleFamily.PERIODIC,
    SpellbladeRule: RuleFamily.SPELLBLADE,
    AllyPacketRule: RuleFamily.ALLY_PACKET,
    DeltaAmpRule: RuleFamily.DELTA_AMP,
    PartAmpRule: RuleFamily.DELTA_AMP,
    OnHitStrikeRule: RuleFamily.ON_HIT_STRIKE,
    ResistanceShredRule: RuleFamily.RESISTANCE_SHRED,
    SecondaryTargetRule: RuleFamily.SECONDARY_TARGET,
    CritDamageBonusRule: RuleFamily.CRIT_PROFILE,
    ForcedCritRule: RuleFamily.CRIT_PROFILE,
    AttackCooldownRefundRule: RuleFamily.CRIT_PROFILE,
    ExecuteRule: RuleFamily.DAMAGE_ROUTING,
    ShieldBypassRule: RuleFamily.DAMAGE_ROUTING,
    DamageDeferralRule: RuleFamily.DAMAGE_ROUTING,
    SustainStatRule: RuleFamily.SUSTAIN,
    OnHitHealRule: RuleFamily.SUSTAIN,
    PostMitigationHealRule: RuleFamily.SUSTAIN,
    ResourceDrainRule: RuleFamily.SUSTAIN,
    ManaSpentHealRule: RuleFamily.SUSTAIN,
    RegenerationRule: RuleFamily.SUSTAIN,
    BelowHalfHealingRule: RuleFamily.SUSTAIN,
    ReceivedHealingRule: RuleFamily.SUSTAIN,
    StatConversionRule: RuleFamily.STAT_DERIVATION,
    StatMultiplierRule: RuleFamily.STAT_DERIVATION,
    PenetrationChannelRule: RuleFamily.STAT_DERIVATION,
    RestrictedChannelRule: RuleFamily.STAT_DERIVATION,
    ResourceRestoreRule: RuleFamily.STAT_DERIVATION,
    ManaflowRule: RuleFamily.STAT_DERIVATION,
    StackedStatRule: RuleFamily.STAT_DERIVATION,
    FlatStatGrantRule: RuleFamily.STAT_DERIVATION,
    StatAuraRule: RuleFamily.STAT_DERIVATION,
    ThresholdRegenRule: RuleFamily.STAT_DERIVATION,
    UltimateRefundRule: RuleFamily.STAT_DERIVATION,
    ActiveWindowCastEconomyRule: RuleFamily.STAT_DERIVATION,
    OpeningDefenseRule: RuleFamily.OPENING_DEFENSE,
    ThresholdDefenseRule: RuleFamily.THRESHOLD_DEFENSE,
    CombatStateRule: RuleFamily.COMBAT_STATE,
    ReactiveRule: RuleFamily.REACTIVE,
}

# The defence payloads, one union the validator, the resolver and the
# interpreter all read: every defence declaration answers "which mechanic,
# which state, which numbers" and the family it lands in says *when* rather
# than *what*.  DamageDeferralRule and ReceivedHealingRule are shaped like a
# defence and filed under another family: the resolver builds them at the
# opening with every other defence, and what they do with the damage is a
# different question from where they are built.
DefensePayload = (
    OpeningDefenseRule
    | ThresholdDefenseRule
    | CombatStateRule
    | ReactiveRule
    | DamageDeferralRule
    | ReceivedHealingRule
)
DEFENSE_PAYLOAD_TYPES: tuple[type[DefensePayload], ...] = get_args(DefensePayload)


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
    _validate_policy_types(rule)
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
    if isinstance(payload, SwingScheduleRule):
        _validate_swing_schedule(rule, payload)
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
    if isinstance(payload, SUSTAIN_VALUE_PAYLOADS):
        _validate_sustain(rule, payload)
        return
    if isinstance(payload, STAT_DERIVATION_PAYLOADS):
        _validate_stat_derivation(rule, payload)
        return
    if isinstance(payload, ExecuteRule):
        _validate_damage_routing(rule, payload)
        _validate_refs(rule, {"threshold": payload.threshold})
        return
    if isinstance(payload, ShieldBypassRule):
        _validate_damage_routing(rule, payload)
        if not isinstance(payload.fraction, MeleeRangedSplit):
            raise BehaviorRuleError(
                f"{rule.mechanic_id}: a shield bypass pays melee and ranged "
                "holders differently and declares both"
            )
        _validate_refs(
            rule,
            {
                "fraction.melee": payload.fraction.melee,
                "fraction.ranged": payload.fraction.ranged,
                "duration": payload.duration,
            },
        )
        if not isinstance(payload.trigger, TriggerEvent):
            raise BehaviorRuleError(
                f"{rule.mechanic_id}: a shield bypass says what opens its window"
            )
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


def _validate_swing_schedule(rule: BehaviorRule, payload: SwingScheduleRule) -> None:
    """A swing schedule declares at least one mechanic, each one whole.

    "At least one" is checked rather than assumed because the two records are
    optional for the honest reason — a build may hold either — and a rule
    carrying neither would be a key group the registry dropped, presented as
    an item whose attacks land at the ordinary rate.
    """
    stacks, window = payload.decaying_stacks, payload.refunded_window
    if stacks is None and window is None:
        raise BehaviorRuleError(
            f"{rule.mechanic_id}: a swing schedule declares a ramp, a re-armed "
            "window or both; one that schedules neither is a dropped key group "
            "rather than an item whose attacks land at the ordinary rate"
        )
    if stacks is not None:
        _validate_refs(
            rule,
            {
                "per_stack": stacks.per_stack,
                "max_stacks": stacks.max_stacks,
                "stack_duration": stacks.stack_duration,
            },
        )
    if window is not None:
        _validate_refs(
            rule,
            {
                "bonus_attack_speed_percent": window.bonus_attack_speed_percent,
                "duration": window.duration,
                "cooldown": window.cooldown,
                "refund_per_attack": window.refund_per_attack,
                "refund_per_crit": window.refund_per_crit,
            },
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
    _validate_ramp_subjects(rule, payload)


def _validate_ramp_subjects(rule: BehaviorRule, payload: AllyPacketRule) -> None:
    """Every level-scaled number says whose level reads it, and only those do.

    Both directions, because a ramp the emitter resolves and no declaration
    names would fall back to whichever level the call site happened to hold —
    the guess this axis replaces.
    """
    for ramp in payload.ramps:
        if not isinstance(ramp, LevelRamp) or not isinstance(
            ramp.subject, LevelSubject
        ):
            raise BehaviorRuleError(
                f"{rule.mechanic_id}: a level ramp names its two ends and "
                "whose level reads it"
            )
    declared = sorted(
        (ramp.reference.min_key, ramp.reference.max_key) for ramp in payload.ramps
    )
    scaled = sorted(
        (reference.min_key, reference.max_key)
        for reference in payload.values
        if isinstance(reference, LevelValueRef)
    )
    if declared != scaled:
        raise BehaviorRuleError(
            f"{rule.mechanic_id}: level ramps {declared} and level-scaled "
            f"values {scaled} disagree; a ramp with no declared subject is a "
            "number read at a guessed level"
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


# Which references each value-shaped sustain payload declares.  A table
# rather than five validator branches: every one of them answers "are all my
# numbers references", and the only thing that differs is which fields to
# ask for.
SUSTAIN_PAYLOAD_REFERENCES: dict[type, tuple[str, ...]] = {
    SustainStatRule: ("percent",),
    OnHitHealRule: ("amount",),
    PostMitigationHealRule: ("ratio", "area_effectiveness"),
    ResourceDrainRule: (
        "restoration_per_second",
        "combat_restoration_per_second",
        "combat_window",
        "health_conversion",
        "tick_interval",
    ),
    ManaSpentHealRule: (
        "heal_ratio",
        "cap_per_cast",
        "cap_per_second",
        "damage_taken_to_mana_ratio",
    ),
    RegenerationRule: (
        "total_melee",
        "total_reduced",
        "duration",
        "missing_health_cap",
        "tick_interval",
    ),
    BelowHalfHealingRule: ("bonus",),
}

SUSTAIN_VALUE_PAYLOADS: tuple[type, ...] = tuple(SUSTAIN_PAYLOAD_REFERENCES)


# Which references each stat-derivation payload must carry, and which it may
# declare absent.  Two tables rather than eight validator branches: every one
# of them answers "are all my numbers references", and the only thing that
# differs is which fields to ask for and which may honestly be ``None``.
STAT_DERIVATION_REQUIRED_REFERENCES: dict[type, tuple[str, ...]] = {
    StatConversionRule: ("ratio",),
    StatMultiplierRule: ("share",),
    # A channel carries no number: the percentage it routes is a cached stat
    # and the declaration says only where it lands.
    PenetrationChannelRule: (),
    # A restricted channel does carry its number, because no stat block holds
    # it: the declaration is the number's only home.
    RestrictedChannelRule: ("amount",),
    ResourceRestoreRule: ("share_of_maximum", "duration", "ticks"),
    ManaflowRule: (
        "charge_interval",
        "bonus_mana_per_trigger",
        "bonus_mana_per_champion",
        "bonus_mana_max",
    ),
    StackedStatRule: ("per_stack",),
    FlatStatGrantRule: ("amount",),
    StatAuraRule: ("reduction", "radius"),
    ThresholdRegenRule: (
        "bonus_health_threshold",
        "share_of_max_health",
        "tick_interval",
        "champion_damage_cooldown",
        "nonchampion_damage_cooldown",
    ),
    UltimateRefundRule: (
        "base_ratio",
        "per_lethality_ratio",
        "trigger_window",
    ),
    ActiveWindowCastEconomyRule: (
        "resource_cost_multiplier",
        "basic_cooldown_progress_multiplier",
        "window",
    ),
}

STAT_DERIVATION_OPTIONAL_REFERENCES: dict[type, tuple[str, ...]] = {
    StatConversionRule: ("basis_unit", "flat_base"),
    StatMultiplierRule: (),
    PenetrationChannelRule: (),
    RestrictedChannelRule: (),
    ResourceRestoreRule: (),
    ManaflowRule: ("max_charges", "transform_bonus_mana"),
    StackedStatRule: (
        "max_stacks",
        "cap",
        "flat_base",
        "duration",
        "grants_level_at_max",
    ),
    FlatStatGrantRule: ("duration", "cooldown", "trigger_window"),
    StatAuraRule: (),
    ThresholdRegenRule: (),
    UltimateRefundRule: (),
    ActiveWindowCastEconomyRule: (),
}

STAT_DERIVATION_PAYLOADS: tuple[type, ...] = tuple(STAT_DERIVATION_REQUIRED_REFERENCES)

# The one payload of the family whose number lands on somebody else.  Named
# rather than judged, so "an aura is the exception" is a constant a reader
# can check instead of a branch that grew.
STAT_DERIVATION_TARGET_PAYLOADS: tuple[type, ...] = (StatAuraRule,)

# The payloads that grant no stat at all: an ultimate cooldown refund moves a
# cooldown, an active window's cast economy moves a cost and a cooldown
# progression, and a restricted channel's number lands off the block
# altogether.  Naming a DerivedStat for any of them would invent a stat the
# block does not hold.  Named for the same reason as the row above.
STAT_DERIVATION_UNGRANTED_PAYLOADS: tuple[type, ...] = (
    UltimateRefundRule,
    ActiveWindowCastEconomyRule,
    RestrictedChannelRule,
)

# The payloads that only say where a number lands and schedule nothing.  The
# payload-level twin of ``item_behavior_catalog.STAT_CHANNEL_TAGS``, and what
# ``declares_runtime_behaviour`` reads: a channel schedules nothing itself —
# either the fight already holds its number as a cached stat, or only a fight
# whose own target class selects the channel arms it — so no champion-class
# fight gains runtime behaviour from an item whose whole entry is one.
STAT_CHANNEL_PAYLOADS: tuple[type, ...] = (
    PenetrationChannelRule,
    RestrictedChannelRule,
)


def _validate_stat_reference(
    rule: BehaviorRule, name: str, value: object, *, optional: bool
) -> None:
    """One stat-derivation number: a reference, a melee/ranged pair, or absent.

    The split is admitted everywhere in this family because four of its
    numbers really are paid at two rates — a melee holder converts more bonus
    AD into haste and stacks crit faster — and both halves are checked, so a
    schema that supplied one and defaulted the other is refused rather than
    pricing a whole class of holders at zero.
    """
    if optional and value is None:
        return
    if isinstance(value, MeleeRangedSplit):
        _validate_refs(
            rule, {f"{name}.melee": value.melee, f"{name}.ranged": value.ranged}
        )
        return
    _validate_refs(rule, {name: value}, optional=optional)


def _validate_stat_derivation(rule: BehaviorRule, payload: RulePayload) -> None:
    """A stat derivation says which stat, from where, and how it is available."""
    if not isinstance(payload.availability, StatAvailability):
        raise BehaviorRuleError(
            f"{rule.mechanic_id}: a stat derivation declares when the stat is "
            "in the block the engines read; an undeclared availability is the "
            "assumed-active claim this family exists to make visible"
        )
    expected = (
        Subject.TARGET
        if isinstance(payload, STAT_DERIVATION_TARGET_PAYLOADS)
        else Subject.HOLDER
    )
    if payload.subject is not expected:
        raise BehaviorRuleError(
            f"{rule.mechanic_id}: a stat derivation acts on {expected.value}; "
            "only an aura reduces a stat on somebody else"
        )
    if isinstance(payload, StatConversionRule) and not isinstance(
        payload.basis, StatBasis
    ):
        raise BehaviorRuleError(
            f"{rule.mechanic_id}: a conversion names the stat it reads"
        )
    if isinstance(payload, RestrictedChannelRule) and not isinstance(
        payload.channel, RestrictedChannel
    ):
        raise BehaviorRuleError(
            f"{rule.mechanic_id}: a restricted channel names the channel its "
            "number reaches; an unnamed one is the mis-channelling the "
            "declaration exists to refuse"
        )
    if not isinstance(payload, STAT_DERIVATION_UNGRANTED_PAYLOADS) and not isinstance(
        getattr(payload, "granted", None), DerivedStat
    ):
        raise BehaviorRuleError(
            f"{rule.mechanic_id}: a stat derivation names the stat it grants"
        )
    if (
        isinstance(payload, ManaflowRule)
        and payload.transform_bonus_mana is not None
        and payload.max_charges is None
    ):
        raise BehaviorRuleError(
            f"{rule.mechanic_id}: a manaflow ledger that transforms declares "
            "the charge ceiling it transforms at; a transform with no ceiling "
            "is a parse that dropped a key"
        )
    for name in STAT_DERIVATION_REQUIRED_REFERENCES[type(payload)]:
        _validate_stat_reference(rule, name, getattr(payload, name), optional=False)
    for name in STAT_DERIVATION_OPTIONAL_REFERENCES[type(payload)]:
        _validate_stat_reference(rule, name, getattr(payload, name), optional=True)


def _validate_sustain(rule: BehaviorRule, payload: RulePayload) -> None:
    """A sustain rule heals its holder and reads only sourced numbers."""
    if payload.subject is not Subject.HOLDER:
        raise BehaviorRuleError(
            f"{rule.mechanic_id}: a sustain rule puts health back on the holder "
            "and declares no other subject; a heal aimed elsewhere is an ally "
            "packet"
        )
    if isinstance(payload, SustainStatRule):
        if not isinstance(payload.stat, SustainStat):
            raise BehaviorRuleError(
                f"{rule.mechanic_id}: a stat grant says which vampirism stat it feeds"
            )
        _validate_saturating_grant(rule, payload)
        return
    _validate_refs(
        rule,
        {
            name: getattr(payload, name)
            for name in SUSTAIN_PAYLOAD_REFERENCES[type(payload)]
        },
    )


def _validate_saturating_grant(rule: BehaviorRule, payload: SustainStatRule) -> None:
    """A vampirism grant's share is sourced, and so is the ramp that arms it."""
    if isinstance(payload.percent, MeleeRangedSplit):
        _validate_refs(
            rule,
            {
                "percent.melee": payload.percent.melee,
                "percent.ranged": payload.percent.ranged,
            },
        )
    else:
        _validate_refs(rule, {"percent": payload.percent})
    if payload.arms_at is not None:
        _validate_refs(
            rule,
            {
                "arms_at.per_second": payload.arms_at.per_second,
                "arms_at.maximum": payload.arms_at.maximum,
            },
        )


def _validate_damage_routing(
    rule: BehaviorRule, payload: ExecuteRule | ShieldBypassRule
) -> None:
    """A routing rule names its typing and acts on the target it re-routes."""
    if not isinstance(payload.typing, Typing):
        raise BehaviorRuleError(f"{rule.mechanic_id}: typing is not declared (D-04)")
    if payload.subject is not Subject.TARGET:
        raise BehaviorRuleError(
            f"{rule.mechanic_id}: a routing rule changes where damage lands on "
            "the target and has no other subject"
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


class PolicyWalk(NamedTuple):
    """One rule's policy surface: the values it holds and the fields it skipped.

    ``sites`` pairs every policy value with the dotted field path it sits at,
    so a violation can name the field rather than only its type.
    ``identifiers`` records every ``(declaring type, field)`` the walk skipped
    as an identifier or a citation — the exception population *as taken*,
    which is a different and stronger thing than the exception population as
    listed: a payload that grew a field called ``reason`` would take the
    exception silently, and pinning what was taken is what sees it.
    """

    sites: tuple[tuple[str, object], ...]
    identifiers: tuple[tuple[str, str], ...]


def _walk_policy(
    value: object,
    path: str,
    sites: list[tuple[str, object]],
    identifiers: list[tuple[str, str]],
) -> None:
    """Descend into *value*, recording every policy value beneath it.

    A value reference is a leaf: its own fields are the registry, owner and
    key that *name* a number rather than describing one.  Containers are
    walked member by member — a ``frozenset[str]`` policy axis is an open
    string set wearing a collection's clothes — and every other non-dataclass
    is a leaf the caller has already recorded.
    """
    if is_value_reference(value):
        return
    if isinstance(value, (tuple, list, frozenset, set)):
        for member in value:
            sites.append((f"{path}[]", member))
            _walk_policy(member, f"{path}[]", sites, identifiers)
        return
    if not is_dataclass(value) or isinstance(value, type):
        return
    for spec in dataclass_fields(value):
        child = getattr(value, spec.name)
        site = f"{path}.{spec.name}" if path else spec.name
        if spec.name in POLICY_IDENTIFIER_FIELDS:
            identifiers.append((type(value).__name__, spec.name))
            continue
        sites.append((site, child))
        _walk_policy(child, site, sites, identifiers)


def policy_walk(rule: BehaviorRule) -> PolicyWalk:
    """Every policy value of *rule*, with the identifier fields it skipped.

    Starts at the rule itself, so it reaches every field, not the surface."""
    sites: list[tuple[str, object]] = []
    identifiers: list[tuple[str, str]] = []
    _walk_policy(rule, "", sites, identifiers)
    return PolicyWalk(tuple(sites), tuple(identifiers))


def policy_values(rule: BehaviorRule) -> tuple[object, ...]:
    """Every policy value the rule carries, flattened for reflective checks."""
    return tuple(value for _site, value in policy_walk(rule).sites)


def _validate_policy_types(rule: BehaviorRule) -> None:
    """Refuse a rule whose policy field holds a callable, dict or open string.

    Structural: it reads the declaration's own shape and nothing else.  It runs
    at load rather than only in a test, so a new family that puts a ``dict`` on
    a policy axis stops at the compiler that built it.
    """
    for site, value in policy_walk(rule).sites:
        if callable(value) or isinstance(value, (dict, str)):
            raise BehaviorRuleError(
                f"{rule.mechanic_id}: policy field {site} holds a "
                f"{type(value).__name__}; every policy axis is a closed union "
                "or a ValueRef, and the identifier and citation fields are the "
                f"named exceptions {sorted(POLICY_IDENTIFIER_FIELDS)}"
            )


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
    # The typed reader for a supplied option (bounds, step, finiteness are
    # the option's contract).  Injected by the caller that owns the item
    # data layer, so this declaration layer stays a leaf.
    option_value: Callable[[str, str], float] | None = None

    def stat(self, name: str) -> float:
        """One resolved stat; absent means the champion has none of it, so zero."""
        return float(self.stats.get(name, 0.0))

    def max_health(self) -> float:
        """Maximum health, which every subject has, so absence raises."""
        return float(self.stats["health"])

    @property
    def is_melee(self) -> bool:
        """Whether the subject pays the melee rate of a range-split defence."""
        return bool(self.stats.get("is_melee", False))

    def option(self, owner: str, option: DefenseOption) -> float:
        """One declared input option, validated, zero when none was supplied.

        Read through the typed accessor rather than off the mapping: the
        schema's bounds, step and finiteness are the option's contract, and a
        resolver that took the raw value would price an out-of-domain
        activation a request could never have passed.  A scenario that
        supplied nothing reads 0.0 — an absence, not a defaulted magnitude.
        """
        supplied = self.options.get(owner) or {}
        if option.value not in supplied:
            return 0.0
        if self.option_value is None:
            raise ValueError(
                f"{owner} option {option.value!r} was supplied but the subject "
                "carries no typed option reader"
            )
        return self.option_value(owner, option.value)


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

    fields: tuple[KernelField, ...]
    notes: tuple[str, ...]


__all__ = [
    "ACTIVATION_TYPES",
    "AMP_CHAIN_ORDER",
    "COMPILABILITY_TYPES",
    "CONSUMPTION_TYPES",
    "DEFENSE_FIELD_COMBINE",
    "DEFENSE_PAYLOAD_TYPES",
    "DURABILITY_STATS",
    "FLOOR_TYPES",
    "MAGNITUDE_TYPES",
    "PAYLOAD_FAMILY",
    "PERIODIC_CADENCE_FIELDS",
    "POLICY_IDENTIFIER_FIELDS",
    "RESTRICTED_CHANNEL_PACKETS",
    "RULE_FAMILY_COUNT",
    "SCALING_TYPES",
    "STAT_CHANNEL_PAYLOADS",
    "STAT_DERIVATION_OPTIONAL_REFERENCES",
    "STAT_DERIVATION_PAYLOADS",
    "STAT_DERIVATION_REQUIRED_REFERENCES",
    "STAT_DERIVATION_TARGET_PAYLOADS",
    "STAT_DERIVATION_UNGRANTED_PAYLOADS",
    "SUBJECT_AUTHORITY",
    "SUSTAIN_PAYLOAD_REFERENCES",
    "SUSTAIN_VALUE_PAYLOADS",
    "TRIGGER_STREAM",
    "AbsoluteWindow",
    "Activation",
    "ActiveCastRule",
    "ActiveWindowCastEconomyRule",
    "AfterTrigger",
    "AllyPacketRule",
    "AllyProducer",
    "Always",
    "AmpChainSlot",
    "AtLeast",
    "AttackCooldownRefundRule",
    "Basis",
    "BehaviorRule",
    "BehaviorRuleError",
    "BelowHalfHealingRule",
    "BonusTyping",
    "BuildContext",
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
    "DamageDeferralRule",
    "DamageFormula",
    "DamageThreshold",
    "DecayingAttackStacks",
    "DeclaredRamp",
    "DefenseCombine",
    "DefenseExclusivity",
    "DefenseField",
    "DefenseMechanic",
    "DefensePayload",
    "DefenseOption",
    "DefenseOutcome",
    "DefenseSubject",
    "DeltaAmpRule",
    "DerivedStat",
    "EmpoweredAutoBuffRule",
    "EmpoweredHitRule",
    "EnergizedCharge",
    "EngineLane",
    "ExcludeTrigger",
    "ExecuteRule",
    "Fixed",
    "FlatStatGrantRule",
    "Floor",
    "ForcedCritHeal",
    "ForcedCritRule",
    "HolderStat",
    "Isolation",
    "KernelField",
    "LevelRamp",
    "LevelSteppedRate",
    "LevelSubject",
    "LivePredicate",
    "Magnitude",
    "ManaSpentHealRule",
    "ManaflowRule",
    "MeleeRangedSplit",
    "NEvents",
    "NextEventOnly",
    "NoFloor",
    "NoScaling",
    "OnHitHealRule",
    "OnHitStrikeRule",
    "OpeningDefenseRule",
    "PacketKind",
    "PacketSpec",
    "PacketTrigger",
    "PartAmpRule",
    "PenetrationChannelRule",
    "PeriodicCadence",
    "PeriodicRule",
    "Persist",
    "Persistence",
    "PolicyWalk",
    "Pool",
    "PostMitigationHealRule",
    "Probe",
    "ProcTrigger",
    "RampModel",
    "RampPerSecond",
    "RampPerStack",
    "RampSaturation",
    "ReactiveRule",
    "ReceiptOnly",
    "ReceiptScope",
    "ReceivedHealingRule",
    "Recipients",
    "RefundedAttackWindow",
    "RegenerationRule",
    "RepeatingStrikeRule",
    "Resistance",
    "ResistanceShredRule",
    "ResourceDrainRule",
    "ResourceRestoreRule",
    "RestrictedChannel",
    "RestrictedChannelRule",
    "RestrictedPacket",
    "RuleFamily",
    "RulePayload",
    "Scaling",
    "SecondaryTargetRule",
    "SelfShield",
    "ShapedChargeRule",
    "ShieldAbsorbs",
    "ShieldBypassRule",
    "SpellbladeRule",
    "StackGate",
    "StackRamp",
    "StackedStatRule",
    "StatAuraRule",
    "StatAvailability",
    "StatBasis",
    "StatConversionRule",
    "StatMultiplierRule",
    "StatScaled",
    "Subject",
    "SustainStat",
    "SustainStatRule",
    "SwingScheduleRule",
    "TargetBonusHealthScaled",
    "TemporaryLethality",
    "Term",
    "ThresholdDefenseRule",
    "ThresholdRegenRule",
    "TimesMissingHealth",
    "TimesValue",
    "TriggerEvent",
    "TriggerWindow",
    "Typing",
    "UltimateProcRule",
    "UltimateRefundRule",
    "UtilityDimension",
    "WindowBoundary",
    "WindowMerge",
    "ZeroPolicy",
    "chain_rank",
    "is_denial_receipt",
    "is_packet_kind",
    "is_value_reference",
    "policy_values",
    "policy_walk",
    "validate_rule",
]
