"""What an event is: its damage and attack class, the modifier classes it declares, and its rank.

Two questions share this vocabulary.  A damage packet *belongs to* exactly one
damage class and one attack class, resolved by the two ``*_of`` readers.  A
damage-modifier packet *declares the set* of classes it applies to, and that
declaration rides the action into the armed modifier.  Applicability is then set
membership, in one place (``transitions._modifier_applies``), instead of an
untyped multiply.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from enum import Enum
from typing import Any

from ..ability_spec import AttackClass, DamageClass
from .phases import TransitionRank
from .typed_action import ActionKind, SurvivalAction

_DAMAGE_CLASS_BY_TYPE = {member.value: member for member in DamageClass}


def damage_class_of(action: SurvivalAction) -> DamageClass | None:
    """Which resistance mitigates this packet, or ``None`` if it names none."""
    return _DAMAGE_CLASS_BY_TYPE.get(action.damage_type)


def attack_class_of(action: SurvivalAction) -> AttackClass:
    """How this packet was delivered, independent of what mitigates it.

    Basic attacks are read first: ``source_key == "auto_attacks"`` marks the
    engine's auto-attack rows, which carry an ability flag when one empowered it.
    """
    if action.basic_attack or action.source_key == "auto_attacks":
        return AttackClass.BASIC_ATTACK
    if action.is_ability:
        return AttackClass.ABILITY
    return AttackClass.OTHER


def declared_modifier_classes(
    action: SurvivalAction,
) -> tuple[frozenset[DamageClass], frozenset[AttackClass]]:
    """The class restriction a damage-modifier action carries (D-04).

    Both sets are required and empty-means-all is banned, so an absent or
    empty declaration raises here — at the moment the modifier would arm —
    naming the packet.  A silent default is what this campaign exists to
    kill: an untyped modifier multiplies every damage class alike, which is
    how the walk amplified a holder's true damage with a magic-only curse.
    """
    if not action.damage_classes or not action.attack_classes:
        raise ValueError(
            f"{action.source or 'damage_modifier'} arms a damage modifier "
            "without a complete class declaration "
            f"(damage_classes={sorted(c.name for c in action.damage_classes)}, "
            f"attack_classes={sorted(c.name for c in action.attack_classes)}); "
            "both are required and empty-means-all is banned (D-04)"
        )
    return action.damage_classes, action.attack_classes


# Every distinct class set an enum vocabulary can spell, shared.  A set of
# enum members is immutable and content-addressed, so two packets declaring
# the same classes may hold one object -- and a vocabulary of N members can
# only spell 2**N of them, which is what bounds this table.  ``frozenset()``
# is not a CPython singleton the way ``()`` is, so the empty set gets its own
# name: an absent declaration is the common case and it allocated per action.
_NO_CLASSES: frozenset[Enum] = frozenset()


_CLASS_SETS: dict[frozenset[Enum], frozenset[Enum]] = {}


def declared_class_set(value: object, vocabulary: type[Enum]) -> frozenset[Enum]:
    """One packet's declared class set, failing closed to the empty set.

    An absent declaration is empty rather than guessed; a declaration
    spelled as anything but members of ``vocabulary`` raises, because a
    string that looks like a class is exactly the drift the enum retires.
    """
    if not value:
        return _NO_CLASSES
    declared = frozenset(value if isinstance(value, Iterable) else (value,))
    members = frozenset(item for item in declared if isinstance(item, vocabulary))
    if len(members) != len(declared):
        raise TypeError(
            f"a packet declared {sorted(map(str, declared))} where "
            f"{vocabulary.__name__} members are required"
        )
    return _CLASS_SETS.setdefault(members, members)


_HEAL_KINDS = frozenset({"heal", "regen"})


# The utility transitions, by packet kind.  Public because the one
# constructor that stamps ``SurvivalAction.utility_kind`` lives in
# ``program.compile`` and this is the vocabulary it stamps from; the walk's
# cleanse dispatch then compares against a member of this set rather than a
# display label.
UTILITY_KINDS = frozenset(
    {"on_hit_magic", "movement", "cleanse", "slow", "economy", "vision"}
)


# The support ladder, by packet kind.  A sourced barrier arms before damage
# and a sourced heal recovers after it; they must not share one rank merely
# because both are support effects.
_STATE_GRANT_KINDS = frozenset(
    {
        "stasis",
        "invulnerability",
        "untargetable",
        "spell_shield",
        # A passive resist arm is a state grant for the same reason the four
        # above are: it is in force before anything at its own timestamp.
        # A hostile *control* is not -- it is something that happens TO the
        # subject, and it must resolve after the barrier that can block it
        # (Morgana's Black Shield grants its immunity at ``BARRIER_GRANT``).
        # It classifies from its kind like every other packet, which lands
        # it at ``UTILITY_ARM``, where an unrecognised kind falls through.
        "crowd_control_resist",
    }
)


# Public because the published support receipt orders barriers ahead of
# everything else too, and one spelling of "which kinds are barriers"
# is the point of this module.
BARRIER_GRANT_KINDS = frozenset({"shield", "temporary_health"})


# A ``damage_modifier`` a trigger armed is a debuff and resolves after the
# damage at its own timestamp; a *persistent* one is an aura that was
# already in force, and arms at ``AURA_ARM`` instead.  The kind alone
# cannot tell the two apart, so the aura declares its rank on the packet
# and ``item_support_effects._packet`` refuses a persistent modifier that
# does not (C4).
_DEBUFF_ARM_KINDS = frozenset({"damage_modifier", "stat_buff"})


# The key a packet author uses to declare its own rank.  Underscored because
# it is transport between the author and the walk; the public receipt
# serializes an explicit key list and never sees it.
#
# This replaced the open ordering float, and the *shape* changed with the
# name: the value stored on a packet dict is now a ``TransitionRank``
# member, not a number.  Anything that read the old key off a packet reads
# nothing here.  The type is closed but the wire value is not enum-only —
# ``support_transition_rank`` coerces through ``TransitionRank(declared)``,
# so a bare ordinal 0-8 is accepted and anything else raises.
SUPPORT_RANK_KEY = "_rank"


def support_transition_rank(event: Mapping[str, Any]) -> TransitionRank:
    """When one sourced support packet arms, as a named rank.

    A packet may declare its own rank when its kind does not decide it:
    Eclipse's self-shield and Fimbulwinter's Everlasting are barriers placed
    *after* the damage that triggered them, so they declare ``LATE_BARRIER``
    where the kind alone would say ``BARRIER_GRANT``; Abyssal Mask's Unmake is
    a persistent aura, so it declares ``AURA_ARM`` where the kind alone would
    say ``DEBUFF_ARM``.  The declaration must be a member of
    :class:`TransitionRank`, so an author picks a rank but cannot invent one.

    Every other packet classifies from its kind, and the classification is
    **not total**: an unrecognised kind falls through to ``UTILITY_ARM``.
    """
    declared = event.get(SUPPORT_RANK_KEY)
    if declared is not None:
        return TransitionRank(declared)
    kind = str(event.get("kind", ""))
    if kind in _STATE_GRANT_KINDS:
        return TransitionRank.STATE_GRANT
    if kind in BARRIER_GRANT_KINDS:
        return TransitionRank.BARRIER_GRANT
    if kind in _HEAL_KINDS:
        return TransitionRank.RECOVERY
    if kind in _DEBUFF_ARM_KINDS:
        return TransitionRank.DEBUFF_ARM
    return TransitionRank.UTILITY_ARM


def _classify_heal(event: Mapping[str, Any]) -> ActionKind:
    """Heal-kind classification with the sourced transition markers."""
    if event.get("overheal_to_shield"):
        return ActionKind.OVERHEAL_SHIELD
    if event.get("healing_category"):
        return ActionKind.ICHOR_CONVERT
    return ActionKind.HEAL


# The fixed-kind dispatch table for classification; the phase-gated and
# damage-path branches below cannot ride a flat lookup.
_STANDALONE_KINDS = {
    "revive": ActionKind.REVIVE,
    "stasis": ActionKind.STASIS,
    "invulnerability": ActionKind.INVULNERABLE,
    "untargetable": ActionKind.UNTARGETABLE,
    "spell_shield": ActionKind.SPELL_SHIELD,
    "crowd_control": ActionKind.CROWD_CONTROL,
    "crowd_control_resist": ActionKind.CROWD_CONTROL_RESIST,
    "shield": ActionKind.SHIELD,
    "stat_buff": ActionKind.STAT_BUFF,
    "damage_modifier": ActionKind.DAMAGE_MODIFIER,
    "on_hit_magic": ActionKind.ON_HIT_MAGIC,
    "movement": ActionKind.UTILITY,
    "cleanse": ActionKind.UTILITY,
    "slow": ActionKind.UTILITY,
    "economy": ActionKind.UTILITY,
    "vision": ActionKind.UTILITY,
}


# Which ranks the recovery branch below accepts — a *classification*
# question, and a different one from which rank resolves first.
#
# Until Phase 4 S6 it was spelled ``ordering_slot(phase) is DEBUFF_ARM``:
# the three ranks shared one ordering slot, so the slot happened to be this
# set as well.  S6 split the slot, and this set is what the split must not
# move — a packet arming at ``UTILITY_ARM`` with an unlisted kind is the
# engine's own self-heal (``champion_ability`` and friends) and classifying
# it as a utility no-op would drop a heal, which is a second behaviour
# change with no fixture and no prediction.  Written down here so the two
# questions have two answers instead of one accident.
_RECOVERY_CLASSIFIED_RANKS = frozenset(
    {
        TransitionRank.DEBUFF_ARM,
        TransitionRank.RECOVERY,
        TransitionRank.UTILITY_ARM,
    }
)


def classify_prefetched(
    event: Mapping[str, Any],
    phase: TransitionRank,
    kind: str,
    execute_ratio_raw: float | None,
    *,
    deferred_raw: bool | None,
    redirected_raw: bool | None,
    raw_formula: Callable[..., float] | None,
    raw_damage: float,
    grievous_duration: float,
) -> ActionKind:
    """The one classification implementation, over prefetched hot fields."""
    standalone = _STANDALONE_KINDS.get(kind)
    if standalone is not None:
        return standalone
    if phase is TransitionRank.BARRIER_GRANT and kind == "temporary_health":
        return ActionKind.TEMP_HEALTH
    if phase is TransitionRank.BARRIER_GRANT and kind in _HEAL_KINDS:
        return _classify_heal(event)
    if phase in _RECOVERY_CLASSIFIED_RANKS:
        # The authoritative walk's recovery branch heals every remaining
        # packet unconditionally (the kind gate exists only at
        # ``BARRIER_GRANT``); engine self-heals may carry arbitrary kind
        # strings such as ``champion_ability``.  All three arming ranks
        # reach it, which is why the set is named rather than read off the
        # ordering fold — see :data:`_RECOVERY_CLASSIFIED_RANKS`.
        return _classify_heal(event)
    if phase < TransitionRank.DAMAGE:
        # Kinds arming before damage but outside the enumerated support
        # transitions are silent no-ops in the authoritative walk; every
        # kind authored today is classified above.
        return ActionKind.UTILITY
    # Damage path.  The plain-damage marker mirrors the compiler: no live
    # health formula, no Grievous pack, no wound.
    if execute_ratio_raw is not None:
        return ActionKind.EXECUTE
    if deferred_raw:
        return ActionKind.DEFER
    if redirected_raw:
        return ActionKind.REDIRECT
    if grievous_duration <= 0.0 and not (callable(raw_formula) and raw_damage > 0):
        return ActionKind.PLAIN_DAMAGE
    return ActionKind.DAMAGE


def classify_event_kind(event: Mapping[str, Any], phase: TransitionRank) -> ActionKind:
    """Map one receipt event (dict + phase) to its typed action kind.

    Mirrors the authoritative walk's dispatch precedence exactly: revive,
    combat-state transitions, spell shield, shield, stat buff, damage
    modifier, utility kinds, then the phase-gated recovery branches, then
    damage (with execute/deferred/redirect markers and the plain-damage
    fast-branch classification).
    """
    get = event.get
    return classify_prefetched(
        event,
        phase,
        str(get("kind", "")),
        get("execute_threshold_ratio"),
        deferred_raw=get("_deferred"),
        redirected_raw=get("_redirected"),
        raw_formula=get("raw_formula"),
        raw_damage=float(get("raw_damage", 0.0) or 0.0),
        grievous_duration=float(get("grievous_duration", 0.0) or 0.0),
    )
