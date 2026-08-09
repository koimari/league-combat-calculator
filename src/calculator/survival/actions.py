"""Typed survival actions — the single state-transition interface (issue #137).

Every mechanic the coupled survival walks apply is expressed as one
:class:`SurvivalAction` carrying an :class:`ActionKind` and all typed fields
that mechanic reads.  The receipt walk and the optimizer's score walk both
consume this interface; the only thing that differs between them is the
ledger representation (event-annotating dicts vs parallel-array
accumulation) behind :func:`~survival.transitions.run_survival_walk`.

Ordering helpers (``action_key``, ``participant_order``, ``event_sequence``)
live here too because the sort key is part of the action's identity: the
walk consumes actions in exactly this total order, and both the receipt
composition and the score compiler build the same keys.
"""

from __future__ import annotations

from enum import Enum, IntEnum
from collections.abc import Iterable, Mapping
import math
from typing import Any, NamedTuple

from ..ability_spec import AttackClass, DamageClass

# ---------------------------------------------------------------------------
# Transition rank — the one ordered "when does this resolve" vocabulary
# ---------------------------------------------------------------------------


class TransitionRank(IntEnum):
    """When a transition resolves, relative to everything at its timestamp.

    Dense ordinals in ordering order: a lower rank resolves first.  This is
    the campaign's single phase vocabulary; the walk still sorts on the
    float :func:`legacy_phase` projects, so the names below say what each
    float *meant* without changing what it *is*.

    ``TERMINAL`` has no producer.  It exists so the published phase list
    keeps ``death_or_terminal_cutoff`` (a name the ledger publishes but no
    transition emits) and is declared last so ``legacy_phase`` stays
    non-decreasing while projecting it to ``math.inf``.

    **Declaration order says more than the float does.**  ``DEBUFF_ARM``,
    ``RECOVERY`` and ``UTILITY_ARM`` all project to 1.0, so their relative
    order changes nothing while ``legacy_phase`` is what the sort key
    consumes.  Ordering them 5 < 6 < 7 is nonetheless a decision — debuff
    arming resolves before healing, and both before utility — and it
    becomes the live tie-break the moment Phase 4 sorts on the rank
    itself.  ``LATE_BARRIER`` before ``REACTIVE`` is the same kind of
    currently-inert declaration at 0.5.  If either ordering is wrong, it
    is wrong here and not at the call sites.
    """

    STATE_GRANT = 0
    BARRIER_GRANT = 1
    DAMAGE = 2
    LATE_BARRIER = 3
    REACTIVE = 4
    DEBUFF_ARM = 5
    RECOVERY = 6
    UTILITY_ARM = 7
    TERMINAL = 8


# The projection is deliberately many-to-one: several ranks share a float
# because the float never carried the distinction.  ``LATE_BARRIER`` is a
# barrier an authored packet places *after* damage (Eclipse's self-shield,
# Fimbulwinter's Everlasting), which is why it is not ``BARRIER_GRANT``.
_LEGACY_PHASES: dict[TransitionRank, float] = {
    TransitionRank.STATE_GRANT: -2.0,
    TransitionRank.BARRIER_GRANT: -1.0,
    TransitionRank.DAMAGE: 0.0,
    TransitionRank.LATE_BARRIER: 0.5,
    TransitionRank.REACTIVE: 0.5,
    TransitionRank.DEBUFF_ARM: 1.0,
    TransitionRank.RECOVERY: 1.0,
    TransitionRank.UTILITY_ARM: 1.0,
    TransitionRank.TERMINAL: math.inf,
}


def legacy_phase(rank: TransitionRank) -> float:
    """The float ``phase`` one rank projects to, for today's sort keys.

    Total over the enum and non-decreasing over declaration order, with no
    member exempted: a rank added without a float raises here rather than
    falling through to a guessed number.  Deleted in Phase 4, when the sort
    key consumes the rank itself.
    """
    try:
        return _LEGACY_PHASES[rank]
    except KeyError:
        raise KeyError(f"TransitionRank.{rank.name} declares no legacy phase") from None


# The read side of the projection.  The walk still receives a float and
# still branches on where that float sits relative to three boundaries;
# resolving them here once means a comparison names the rank it is asking
# about instead of restating a number, and means the hot walk pays a module
# attribute rather than a dict lookup per action.  Deleted with
# ``legacy_phase`` in Phase 4, when the walk compares ranks directly.
BARRIER_GRANT_PHASE = legacy_phase(TransitionRank.BARRIER_GRANT)
DAMAGE_PHASE = legacy_phase(TransitionRank.DAMAGE)
RECOVERY_PHASE = legacy_phase(TransitionRank.RECOVERY)


# The published phase a rank belongs to.  Many-to-one for a different reason
# than ``legacy_phase``: the public contract names the *kind* of transition,
# so a late barrier is still a barrier, and arming a debuff or a utility
# effect is still a state transition.
_PUBLIC_PHASES: dict[TransitionRank, str] = {
    TransitionRank.STATE_GRANT: "state_transition",
    TransitionRank.BARRIER_GRANT: "shield_or_temporary_health",
    TransitionRank.DAMAGE: "damage_and_mitigation",
    TransitionRank.LATE_BARRIER: "shield_or_temporary_health",
    TransitionRank.REACTIVE: "reactive_effect",
    TransitionRank.DEBUFF_ARM: "state_transition",
    TransitionRank.RECOVERY: "healing_and_regeneration",
    TransitionRank.UTILITY_ARM: "state_transition",
    TransitionRank.TERMINAL: "death_or_terminal_cutoff",
}


def public_phase(rank: TransitionRank) -> str:
    """The published phase name one rank belongs to.

    ``capabilities`` derives ``PARTICIPANT_LEDGER_CONTRACT["phases"]`` from
    this by walking the enum in declaration order and keeping each name's
    first appearance, so the published list is a vocabulary in ledger order
    rather than six hand-written strings no contract could notice going
    stale.  A rank with no published name raises rather than silently
    dropping one the API already publishes.
    """
    try:
        return _PUBLIC_PHASES[rank]
    except KeyError:
        raise KeyError(
            f"TransitionRank.{rank.name} declares no published phase"
        ) from None


# ---------------------------------------------------------------------------
# Action kinds
# ---------------------------------------------------------------------------


class ActionKind(Enum):
    """Every survival mechanic the kernel can transition, as one dispatch key.

    Standalone kinds are returned by :func:`classify_event_kind` and
    dispatched by :func:`~survival.transitions.run_survival_walk`.  The
    remaining members are *embedded* transitions — state changes authored
    *inside* a damage/heal application (lifeline thresholds, reactive
    barriers, Maw omnivamp, Defy, timed-shield expiry) — implemented as
    named kernel functions and listed here so the typed interface covers
    every mechanic without inventing artificial action boundaries.
    """

    # Damage (``PLAIN_DAMAGE`` is the hot-loop marker: no trigger link, no
    # live-health repricing, no Grievous pack, no wound — the walk reads
    # none of those four fields for it).
    PLAIN_DAMAGE = "plain_damage"
    DAMAGE = "damage"
    EXECUTE = "execute"
    DEFER = "defer"
    REDIRECT = "redirect"
    # Recovery / barriers
    HEAL = "heal"
    OVERHEAL_SHIELD = "overheal_shield"
    ICHOR_CONVERT = "ichor_convert"
    SHIELD = "shield"
    TEMP_HEALTH = "temporary_health"
    # Combat-state transitions
    REVIVE = "revive"
    STASIS = "stasis"
    INVULNERABLE = "invulnerable"
    UNTARGETABLE = "untargetable"
    SPELL_SHIELD = "spell_shield"
    STAT_BUFF = "stat_buff"
    DAMAGE_MODIFIER = "damage_modifier"
    ON_HIT_MAGIC = "on_hit_magic"
    UTILITY = "utility"
    # Timed-shield expiry, lifeline threshold triggers, reactive shields,
    # Maw omnivamp, and Defy are embedded transitions implemented as kernel
    # functions; they never appear as standalone actions.


# Kinds a damage event may classify to; every one applies the shared damage
# kernel (the kind only drives observation and the fast-branch marker).
_DAMAGE_KINDS = frozenset(
    {
        ActionKind.PLAIN_DAMAGE,
        ActionKind.DAMAGE,
        ActionKind.EXECUTE,
        ActionKind.DEFER,
        ActionKind.REDIRECT,
    }
)


# ---------------------------------------------------------------------------
# The typed action
# ---------------------------------------------------------------------------


class SurvivalAction(NamedTuple):
    """One typed state transition in the coupled survival walk.

    Both adapters consume exactly this interface.  ``event`` is the
    receipt adapter's observation target (the event dict the public
    timeline serializes); score-mode actions leave it ``None`` so the
    kernel never annotates what the optimizer does not read.

    ``phase`` defaults to the damage rank rather than to a bare zero.
    That default is not a formality: ``compiled_damage_action``
    deliberately assigns no phase, so it is where every compiled damage
    action in the hot path gets its phase from — the widest phase slot in
    the tree, not the narrowest.
    """

    # Ordering / routing
    sort_key: tuple = ()
    time: float = 0.0
    phase: float = DAMAGE_PHASE
    kind: ActionKind = ActionKind.DAMAGE
    subject: int = -1
    attacker: int = -1
    # Ledger linkage
    aidx: int = -1
    trigger: int = -1
    trigger_event_id: str | None = None
    event: dict | None = None
    # Damage fields
    amount: float = 0.0
    damage_type: str = ""
    raw_formula: Any = None
    raw_damage: float = 0.0
    grievous: Any = None
    wound: tuple | None = None
    reactive: bool = False
    execute_threshold_ratio: float = 0.0
    execute_source: str = ""
    deferred: bool = False
    deferred_batch_id: str | None = None
    redirected: bool = False
    redirect_holder_health_ratio: float = 0.0
    redirect_original_damage: float = 0.0
    redirect_cancelled: bool = False
    # Attack metadata
    is_ability: bool = False
    basic_attack: bool = False
    ability_instance: Any = None
    source_key: str = ""
    source: str = ""
    event_id: str | None = None
    sequence: Any = None
    immobilized: bool = False
    cc_kind: str = ""
    baseline_effective_armor: float | None = None
    baseline_effective_mr: float | None = None
    # Heal fields
    healing_category: str = ""
    amount_formula: Any = None
    requires_holder_health_ratio: float = 0.0
    requires_damage_free_seconds: float = 0.0
    overheal_to_temporary_health: bool = False
    temporary_health_duration: float = 0.0
    overheal_to_shield: bool = False
    overheal_shield_cap: float = 0.0
    overheal_shield_duration: float = 0.0
    defy_trigger_id: str | None = None
    # Timed / state kinds
    duration: float = 0.0
    health_ratio: float = 0.0
    # Stat buff fields
    bonus_attack_speed_percent: float = 0.0
    ability_power: float = 0.0
    ability_haste: float = 0.0
    on_hit_magic_damage: float = 0.0
    # Damage-modifier fields
    persistent: bool = False
    multiplier: float = 1.0
    damage_reduction: bool = False
    next_event_only: bool = False
    armor_reduction_percent: float = 0.0
    mr_reduction_percent: float = 0.0
    resistance_type: str = ""
    owner: str = ""
    # The class restriction a damage-modifier packet declares (D-04).  Both
    # are required of such a packet and empty is banned, which is why the
    # class default is the empty set: a modifier action that reached the
    # walk without a declaration raises in ``declared_modifier_classes``
    # instead of quietly applying to everything.
    damage_classes: frozenset[DamageClass] = frozenset()
    attack_classes: frozenset[AttackClass] = frozenset()
    # Utility fields
    gold_amount: float = 0.0
    ward_uses: float = 0.0
    duration_set: bool = False


# ---------------------------------------------------------------------------
# Damage and attack classes — what a packet *is*, and what a modifier restricts
# ---------------------------------------------------------------------------
#
# Two different questions share this vocabulary.  A damage packet *belongs
# to* exactly one damage class and one attack class, resolved by the two
# ``*_of`` readers below.  A damage-modifier packet *declares the set* of
# classes it applies to, and that declaration rides the action into the
# armed modifier.  Applicability is then set membership, in one place
# (``transitions._modifier_applies``), instead of an untyped multiply.

_DAMAGE_CLASS_BY_TYPE = {member.value: member for member in DamageClass}


def damage_class_of(action: SurvivalAction) -> DamageClass | None:
    """Which resistance mitigates this packet, or ``None`` if it names none.

    ``None`` is the honest answer for an action carrying no ``damage_type``
    (an arming or recovery transition), and it is not a member of any
    declared set, so such an action matches no restriction.
    """
    return _DAMAGE_CLASS_BY_TYPE.get(action.damage_type)


def attack_class_of(action: SurvivalAction) -> AttackClass:
    """How this packet was delivered, independent of what mitigates it.

    Basic attacks are read first because ``source_key == "auto_attacks"``
    marks the engine's own auto-attack rows, which also carry an ability
    flag when an ability empowered them; everything that is neither an
    attack nor a spell — item procs, burns, thorns returns — is ``OTHER``.
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


def _declared_class_set(value: Any, vocabulary: type) -> frozenset:
    """One packet's declared class set, failing closed to the empty set.

    An absent declaration is empty rather than guessed; a declaration
    spelled as anything but members of ``vocabulary`` raises, because a
    string that looks like a class is exactly the drift the enum retires.
    """
    if not value:
        return frozenset()
    members = frozenset(value if isinstance(value, Iterable) else (value,))
    if not all(isinstance(member, vocabulary) for member in members):
        raise TypeError(
            f"a packet declared {sorted(map(str, members))} where "
            f"{vocabulary.__name__} members are required"
        )
    return members


# ---------------------------------------------------------------------------
# Ordering helpers (shared by the receipt composition and the compiler)
# ---------------------------------------------------------------------------


def event_sequence(event: Mapping[str, Any]) -> int:
    """Return a stable source sequence for simultaneous event ordering."""
    value = event.get("sequence", event.get("_trigger_sequence", 0))
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def participant_order(participant_id: Any) -> tuple[int, str]:
    """Use a deterministic side order when sources share a timestamp."""
    text = str(participant_id or "")
    if text == "main":
        return (0, text)
    if text.startswith("ally:"):
        return (1, text)
    if text.startswith("enemy:"):
        return (2, text)
    return (3, text)


# --- Fast compiled-damage construction (issue #171) ------------------------
# The optimizer compiles tens of thousands of damage actions per request;
# the generated NamedTuple ``__new__`` costs ~1.5 us parsing 60+ keyword
# defaults per call.  Copying a default row and assigning the compiler's
# sixteen damage fields by index builds the identical tuple in under half
# that.  The indices derive from ``_fields`` at import time, so reordering
# or extending the NamedTuple cannot desynchronize them.
_ACTION_DEFAULT_ROW = list(SurvivalAction())
_INDEX = SurvivalAction._fields.index
_I_SORT_KEY = _INDEX("sort_key")
_I_TIME = _INDEX("time")
_I_KIND = _INDEX("kind")
_I_SUBJECT = _INDEX("subject")
_I_ATTACKER = _INDEX("attacker")
_I_AIDX = _INDEX("aidx")
_I_AMOUNT = _INDEX("amount")
_I_DAMAGE_TYPE = _INDEX("damage_type")
_I_RAW_FORMULA = _INDEX("raw_formula")
_I_RAW_DAMAGE = _INDEX("raw_damage")
_I_GRIEVOUS = _INDEX("grievous")
_I_WOUND = _INDEX("wound")
_I_SOURCE_KEY = _INDEX("source_key")
_I_SOURCE = _INDEX("source")
_I_EVENT_ID = _INDEX("event_id")
_I_SEQUENCE = _INDEX("sequence")


def compiled_damage_action(
    sort_key: tuple,
    time: float,
    kind: ActionKind,
    subject: int,
    attacker: int,
    aidx: int,
    amount: float,
    damage_type: str,
    raw_formula: Any,
    raw_damage: float,
    grievous: Any,
    wound: tuple | None,
    source_key: str,
    source: str,
    event_id: str,
    sequence: Any,
) -> SurvivalAction:
    """Build a compiler damage action without keyword-default parsing.

    Exactly ``SurvivalAction(**those sixteen fields)``: every other field
    keeps its class default, ``reactive=False`` and the phase included.
    The phase is the load-bearing one — this function has no ``_I_PHASE``
    because the class default *is* ``DAMAGE_PHASE``, which is what the
    compiler would pass for a damage packet anyway.  Read the rank at
    :class:`SurvivalAction`, not here.
    """
    row = _ACTION_DEFAULT_ROW.copy()
    row[_I_SORT_KEY] = sort_key
    row[_I_TIME] = time
    row[_I_KIND] = kind
    row[_I_SUBJECT] = subject
    row[_I_ATTACKER] = attacker
    row[_I_AIDX] = aidx
    row[_I_AMOUNT] = amount
    row[_I_DAMAGE_TYPE] = damage_type
    row[_I_RAW_FORMULA] = raw_formula
    row[_I_RAW_DAMAGE] = raw_damage
    row[_I_GRIEVOUS] = grievous
    row[_I_WOUND] = wound
    row[_I_SOURCE_KEY] = source_key
    row[_I_SOURCE] = source
    row[_I_EVENT_ID] = event_id
    row[_I_SEQUENCE] = sequence
    return tuple.__new__(SurvivalAction, row)


def action_key(
    event_time: float,
    phase: float,
    participant_id: str,
    event: Mapping[str, Any],
) -> tuple[Any, ...]:
    """Order event phases without ever comparing payload dictionaries.

    This is the survival walk's total order.  Pair packets precompute it per
    event (``_sk``) because the walk re-sorts the same roster events for
    every optimizer candidate.

    The ``_event_id`` component is a dead tie-break for engine damage
    events: ``sequence`` is unique per pair fight, and events from
    different pairs already differ at the source/participant components.
    ``_pair_packet``'s pair-local event numbering depends on that — if an
    engine event ever arrived without its sequence, the packet builder
    rejects that instead of letting numbering become order-relevant.
    """
    source_id = event.get("attacker", participant_id)
    return (
        float(event_time),
        float(phase),
        event_sequence(event),
        *participant_order(source_id),
        str(participant_id),
        str(event.get("_event_id", "")),
        str(event.get("source", event.get("source_key", ""))),
    )


# ---------------------------------------------------------------------------
# Event classification (receipt adapter)
# ---------------------------------------------------------------------------

_HEAL_KINDS = frozenset({"heal", "regen"})

# The support ladder, by packet kind.  A sourced barrier arms before damage
# and a sourced heal recovers after it; they must not share one rank merely
# because both are support effects.
_STATE_GRANT_KINDS = frozenset(
    {"stasis", "invulnerability", "untargetable", "spell_shield"}
)
# Public because the published support receipt orders barriers ahead of
# everything else too, and one spelling of "which kinds are barriers"
# is the point of this module.
BARRIER_GRANT_KINDS = frozenset({"shield", "temporary_health"})
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
    *after* the damage that triggered them, not before it, so they declare
    ``LATE_BARRIER`` where the kind alone would say ``BARRIER_GRANT``.  The
    declaration is a member of :class:`TransitionRank` and nothing else, so
    an author can choose a rank but cannot invent an ordering.

    Every other packet is classified from its kind.  The classification is
    **not total**: an unrecognised kind — a typo, a kind a later phase adds
    — falls through to ``UTILITY_ARM`` rather than raising.  That is the
    old ``else 1.0`` preserved deliberately, because 0A changes no
    behaviour; what closed here is the open *float*, not the open *kind*.
    Making the fall-through fail closed is a behaviour change and belongs
    to a correction slice that can price it.
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


def _classify_prefetched(
    event: Mapping[str, Any],
    phase: float,
    kind: str,
    execute_ratio_raw: Any,
    deferred_raw: Any,
    redirected_raw: Any,
    raw_formula: Any,
    raw_damage: float,
    grievous_duration: float,
) -> ActionKind:
    """The one classification implementation, over prefetched hot fields."""
    standalone = _STANDALONE_KINDS.get(kind)
    if standalone is not None:
        return standalone
    if phase == BARRIER_GRANT_PHASE and kind == "temporary_health":
        return ActionKind.TEMP_HEALTH
    if phase == BARRIER_GRANT_PHASE and kind in _HEAL_KINDS:
        return _classify_heal(event)
    if phase == RECOVERY_PHASE:
        # The authoritative walk's recovery branch heals every remaining
        # packet unconditionally (the kind gate exists only at
        # ``BARRIER_GRANT``); engine self-heals may carry arbitrary kind
        # strings such as ``champion_ability``.
        return _classify_heal(event)
    if phase < DAMAGE_PHASE:
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


def classify_event_kind(event: Mapping[str, Any], phase: float) -> ActionKind:
    """Map one receipt event (dict + phase) to its typed action kind.

    Mirrors the authoritative walk's dispatch precedence exactly: revive,
    combat-state transitions, spell shield, shield, stat buff, damage
    modifier, utility kinds, then the phase-gated recovery branches, then
    damage (with execute/deferred/redirect markers and the plain-damage
    fast-branch classification).
    """
    get = event.get
    return _classify_prefetched(
        event,
        phase,
        str(get("kind", "")),
        get("execute_threshold_ratio"),
        get("_deferred"),
        get("_redirected"),
        get("raw_formula"),
        float(get("raw_damage", 0.0) or 0.0),
        float(get("grievous_duration", 0.0) or 0.0),
    )


def survival_action_from_event(
    event: Mapping[str, Any],
    phase: float,
    subject_index: int,
    index_of: Mapping[str, int],
    *,
    subject_id: str = "",
    aidx: int = -1,
) -> SurvivalAction:
    """Build the typed action for one receipt event.

    The receipt composition converts its ``(sort_key, participant_id,
    event)`` triples through this function once per event; the kernel and
    the annotated ledger then consume the same typed interface the score
    compiler produces.  ``subject_id`` is the ledger bucket the event was
    authored into (the receipt walk's sort key uses it, not the event's
    target field).  Missing optional metadata fails closed to the field's
    neutral value, never to a guessed number.
    """
    get = event.get
    kind_str = str(get("kind", ""))
    execute_ratio_raw = get("execute_threshold_ratio")
    deferred_raw = get("_deferred")
    redirected_raw = get("_redirected")
    raw_formula = get("raw_formula")
    raw_damage = float(get("raw_damage", 0.0) or 0.0)
    grievous_duration = float(get("grievous_duration", 0.0) or 0.0)
    kind = _classify_prefetched(
        event,
        phase,
        kind_str,
        execute_ratio_raw,
        deferred_raw,
        redirected_raw,
        raw_formula,
        raw_damage,
        grievous_duration,
    )
    attacker_id = get("attacker")
    attacker_index = index_of.get(str(attacker_id), -1) if attacker_id else -1
    event_id = get("_event_id")
    time_value = float(get("time", 0.0))
    trigger_id = get("_trigger_event_id")
    batch_id = get("_deferred_batch_id")
    defy_id = get("_defy_trigger_id")
    baseline_armor = get("_baseline_effective_armor")
    baseline_mr = get("_baseline_effective_mr")
    cc_kind = str(get("cc_kind", ""))
    return SurvivalAction(
        sort_key=get("_sk")
        or action_key(
            time_value,
            phase,
            subject_id or str(get("target", "") or ""),
            event,
        ),
        time=time_value,
        phase=phase,
        kind=kind,
        subject=subject_index,
        attacker=attacker_index,
        aidx=aidx,
        trigger=-1,
        trigger_event_id=str(trigger_id) if trigger_id else None,
        event=event,
        amount=max(0.0, float(get("damage", get("amount", 0.0)) or 0.0)),
        damage_type=str(get("damage_type", "")),
        raw_formula=raw_formula,
        raw_damage=raw_damage,
        wound=(
            (grievous_duration, str(get("_wound_source", "Grievous Wounds")))
            if grievous_duration > 0.0
            else None
        ),
        reactive=bool(get("_reactive")),
        execute_threshold_ratio=max(0.0, float(execute_ratio_raw or 0.0)),
        execute_source=str(get("execute_source", "The Collector")),
        deferred=bool(deferred_raw),
        deferred_batch_id=str(batch_id) if batch_id else None,
        redirected=bool(redirected_raw),
        redirect_holder_health_ratio=max(
            0.0, float(get("redirect_holder_health_ratio", 0.0) or 0.0)
        ),
        redirect_original_damage=max(
            0.0, float(get("_redirect_original_damage", 0.0) or 0.0)
        ),
        redirect_cancelled=bool(get("_redirect_cancelled")),
        is_ability=bool(get("is_ability")),
        basic_attack=bool(get("basic_attack")),
        ability_instance=get("ability_instance"),
        source_key=str(get("source_key", "")),
        source=str(get("source", get("source_key", ""))),
        event_id=str(event_id) if event_id is not None else None,
        sequence=get("sequence"),
        immobilized=bool(
            get("immobilized")
            or get("crowd_control")
            or get("hard_cc")
            or cc_kind.lower()
            in {"immobilize", "stun", "root", "knockup", "suppression"}
        ),
        cc_kind=cc_kind,
        baseline_effective_armor=(
            float(baseline_armor) if baseline_armor is not None else None
        ),
        baseline_effective_mr=(float(baseline_mr) if baseline_mr is not None else None),
        healing_category=str(get("healing_category", "")),
        amount_formula=get("amount_formula"),
        requires_holder_health_ratio=max(
            0.0, float(get("requires_holder_health_ratio", 0.0) or 0.0)
        ),
        requires_damage_free_seconds=max(
            0.0, float(get("requires_damage_free_seconds", 0.0) or 0.0)
        ),
        overheal_to_temporary_health=bool(get("overheal_to_temporary_health")),
        temporary_health_duration=max(
            0.0, float(get("temporary_health_duration", 0.0) or 0.0)
        ),
        overheal_to_shield=bool(get("overheal_to_shield")),
        overheal_shield_cap=max(0.0, float(get("overheal_shield_cap", 0.0) or 0.0)),
        overheal_shield_duration=max(
            0.0, float(get("overheal_shield_duration", 0.0) or 0.0)
        ),
        defy_trigger_id=str(defy_id) if defy_id else None,
        duration=max(0.0, float(get("duration", 0.0) or 0.0)),
        health_ratio=max(0.0, float(get("health_ratio", 0.0) or 0.0)),
        bonus_attack_speed_percent=float(get("bonus_attack_speed_percent", 0.0) or 0.0),
        ability_power=float(get("ability_power", 0.0) or 0.0),
        ability_haste=float(get("ability_haste", 0.0) or 0.0),
        on_hit_magic_damage=float(get("on_hit_magic_damage", 0.0) or 0.0),
        persistent=bool(get("persistent")),
        multiplier=float(get("multiplier", 1.0) or 1.0),
        damage_reduction=bool(get("damage_reduction")),
        next_event_only=bool(get("next_event_only")),
        armor_reduction_percent=float(get("armor_reduction_percent", 0.0) or 0.0),
        mr_reduction_percent=float(get("mr_reduction_percent", 0.0) or 0.0),
        resistance_type=str(get("resistance_type", "")),
        owner=str(get("owner", "")),
        damage_classes=_declared_class_set(get("damage_classes"), DamageClass),
        attack_classes=_declared_class_set(get("attack_classes"), AttackClass),
        gold_amount=float(get("gold_amount", 0.0) or 0.0),
        ward_uses=float(get("ward_uses", 0.0) or 0.0),
        duration_set="duration" in event,
    )


# The heal amount lives in ``amount`` for recovery packets; the damage
# amount lives in ``damage``.  ``survival_action_from_event`` above merges
# both into one ``amount`` field; this alias documents that convention.
__all__ = [
    "ActionKind",
    "SUPPORT_RANK_KEY",
    "SurvivalAction",
    "TransitionRank",
    "action_key",
    "attack_class_of",
    "classify_event_kind",
    "damage_class_of",
    "declared_modifier_classes",
    "event_sequence",
    "legacy_phase",
    "participant_order",
    "public_phase",
    "support_transition_rank",
    "survival_action_from_event",
]
