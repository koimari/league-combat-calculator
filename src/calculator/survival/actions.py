"""Typed survival actions: the single state-transition interface.

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

import math
from collections.abc import Iterable, Mapping
from enum import Enum, IntEnum
from threading import Lock
from typing import Any, NamedTuple

from ..ability_spec import AttackClass, DamageClass
from .pricing import DeclaredPacket

# ---------------------------------------------------------------------------
# Transition rank — the one ordered "when does this resolve" vocabulary
# ---------------------------------------------------------------------------


class TransitionRank(IntEnum):
    """When a transition resolves, relative to everything at its timestamp.

    Dense ordinals in ordering order: a lower rank resolves first.  This is
    the campaign's single phase vocabulary, and since Phase 4 S2 it is also
    the only one: the float projection that stood between these names and
    the walk is deleted, so a ``phase`` is a member of this enum everywhere
    one is written, sorted, compared or dispatched on.

    ``TERMINAL`` has no producer.  It exists so the published phase list
    keeps ``death_or_terminal_cutoff`` (a name the ledger publishes but no
    transition emits) and is declared last because it resolves after
    everything else at its timestamp.

    ``AURA_ARM`` is the one rank no producer wrote before C4.  A persistent
    aura is *already in force* when the fight opens — Abyssal Mask's Unmake
    curses every enemy in range from the first frame — so it must resolve
    before the damage at its own timestamp, not after it like a debuff some
    trigger armed.  ``DEBUFF_ARM`` put it after, which made the opening
    exchange the one exchange the aura did not price.

    **One group still resolves as one.**  ``LATE_BARRIER``/``REACTIVE`` rode
    one float before S2 and ride one :func:`ordering_slot` after it, so
    their relative declaration order still changes nothing.

    ``DEBUFF_ARM``/``RECOVERY``/``UTILITY_ARM`` rode the other float and no
    longer share anything: Phase 4 S6 split them, so ``6 < 7 < 8`` is now
    the live tie-break between two transitions authored at one timestamp —
    a debuff arms before a heal lands, and both before a utility effect
    resolves.  That is the ordering the collapsed float could not express
    and could not be asked about; if it is wrong, it is wrong here and not
    at the call sites.
    """

    STATE_GRANT = 0
    BARRIER_GRANT = 1
    AURA_ARM = 2
    DAMAGE = 3
    LATE_BARRIER = 4
    REACTIVE = 5
    DEBUFF_ARM = 6
    RECOVERY = 7
    UTILITY_ARM = 8
    TERMINAL = 9


# ``REACTIVE`` folds onto ``LATE_BARRIER`` wherever the walk *orders* by
# rank, so the two resolve as one.  ``LATE_BARRIER`` is a barrier an
# authored packet places *after* damage (Eclipse's self-shield,
# Fimbulwinter's Everlasting), which is why it is not ``BARRIER_GRANT``.
#
# The fold is a preserved defect and is named as one: a barrier resolving
# after the damage at its own timestamp absorbs nothing at that timestamp.
# The row lives on ``docs/migration-frontier.json`` under
# ``preserved_defects``, because correcting it reorders the walk and owes
# its own measurement.
#
# Which ranks the receipt adapter classifies as a recovery is spelled as
# itself, in ``_RECOVERY_CLASSIFIED_RANKS`` below, rather than as this
# fold's output.  Every other read of a rank is fold-invariant by
# construction: the kernel's comparisons are thresholds at a group
# boundary, and the surviving pair does not straddle one.
_ORDERING_SLOTS: dict[TransitionRank, TransitionRank] = {
    TransitionRank.REACTIVE: TransitionRank.LATE_BARRIER,
}


def ordering_slot(rank: TransitionRank) -> TransitionRank:
    """The rank a transition sorts *as*; identity for a rank that sorts alone."""
    return _ORDERING_SLOTS.get(rank, rank)


# The published phase a rank belongs to.  Many-to-one for a different reason
# than ``ordering_slot``: the public contract names the *kind* of transition,
# so a late barrier is still a barrier, and arming a debuff or a utility
# effect is still a state transition.
#
# ``AURA_ARM`` is the one arming rank that does *not* fold into
# ``state_transition``, and the reason is the list's own ordering.  The
# published list is the ledger's phases in ledger order, keeping each name's
# first appearance; ``state_transition`` already appears first, at
# ``STATE_GRANT``.  Folding the aura slot into it would publish nothing for
# the one phase that resolves between the barriers and the damage — a phase
# the ledger has and the contract does not name, which is this campaign's
# own failure shape in the public schema.  It is a seventh published name
# and ``CAPABILITY_SCHEMA_VERSION`` moves with it (D-63).
_PUBLIC_PHASES: dict[TransitionRank, str] = {
    TransitionRank.STATE_GRANT: "state_transition",
    TransitionRank.BARRIER_GRANT: "shield_or_temporary_health",
    TransitionRank.AURA_ARM: "persistent_aura_arming",
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

    ``capabilities`` derives ``PARTICIPANT_LEDGER_CONTRACT["phases"]`` from this
    by walking the enum in declaration order and keeping each name's first
    appearance, rather than from six hand-written strings.
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
    CROWD_CONTROL = "crowd_control"
    # P2 Slice 8: a passive IMMUNITY arm (Dr. Mundo Goes Where He
    # Pleases) — the next hostile immobilizing control is RESISTED before
    # it ever applies (never a truncation): the arm packet sorts before
    # same-timestamp controls and the resist gate sits inside
    # _apply_crowd_control after the spell-shield/Black-Shield gates.
    CROWD_CONTROL_RESIST = "crowd_control_resist"
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
# Live amplification — the one amp whose pool exists only inside the walk
# ---------------------------------------------------------------------------


class LiveProbe(Enum):
    """Which live pool a kernel-side amplifier reads, as a tag.

    Every other amplifier in the tree resolves to a number before the first
    event exists.  One does not: Shadowflame's Cinderbloom reads the
    *target's health at the instant of the hit*, under fire from a whole
    roster, so its threshold compiles and its reading arrives event by
    event.

    A tag rather than a predicate object, and a tag declared **here** rather
    than imported, because ``program/`` may name ``survival/`` types and
    never the reverse.  The kernel branches on the member and the meaning is
    the member's own: ``HEALTH_BELOW_RATIO`` is "the subject's current health
    is strictly below ``ratio`` times its maximum", which is exactly the
    ``LivePredicate(TARGET_HEALTH_FRACTION, LT)`` the declaration carries.
    :func:`~..program.amp.live_amp_riders` is where the two are joined, and
    it refuses any other probe or comparison rather than approximating one.
    """

    HEALTH_BELOW_RATIO = "health_below_ratio"


class LiveAmp(NamedTuple):
    """An amplification the walk can only price at the moment of the hit.

    It rides its host damage action rather than standing as an event of its
    own, and that is the whole mechanic: a rider dies with its host, so a
    spell-shielded, state-blocked or post-death trigger emits no bonus with
    nothing having to cancel it.  ``fraction`` is the sourced ratio the
    declaration compiled (0.2 for a 120% crit), never a multiplier, so a
    zero bonus is a measured zero and not a neutral 1.0 nobody can tell from
    an unarmed one.
    """

    probe: LiveProbe
    threshold: float
    fraction: float
    mechanic: str


# ---------------------------------------------------------------------------
# Event reference slots — the kernel's four references, as integers
# ---------------------------------------------------------------------------


# "This action names no such reference."  The integer spelling of the ``None``
# the four ``str | None`` reference fields carried before Phase 4 S1, and the
# same sentinel ``subject``/``attacker``/``trigger``/``holder`` already use.
NO_SLOT = -1


class EventSlots:
    """The one text-to-integer registry for the walk's event references.

    Four kernel fields carry event references: the packet's own id, its trigger's,
    its deferral batch's and its Defy trigger's.  Every use of them is an identity
    question, is this the packet that trigger applied? is this batch cleared?, and
    a slot answers it with an int compare rather than a string comparison inside
    the hot loop.

    A slot is a dense integer standing for exactly one id string.  The sets and
    dicts the walk keys by a reference become int-keyed, and :meth:`text` gives the
    string back at the one place that still authors a derived id.

    **The registry is process-wide, deliberately.**  Actions outlive the call that
    built them: a pair packet's typed actions ride the packet cache, a signature
    panel's compiled actions ride the search context, and both are replayed inside
    walks built later.  A per-call registry would give two such actions slots from
    two different numberings inside one walk, two different events answering to one
    integer, with no symptom.  One numbering for the process makes that
    unrepresentable.

    Growth is bounded rather than merely slow: every id is assembled from a closed
    vocabulary (roster slots ``main``/``ally:n``/``enemy:n``, mechanic labels, item
    names, source keys) and a small ordinal, so the distinct set converges instead
    of scaling with traffic.  Nothing is ever evicted, because a slot handed to a
    cached action must keep meaning the same event for as long as that action can
    be walked.
    """

    __slots__ = ("_by_text", "_lock", "_texts")

    def __init__(self) -> None:
        self._by_text: dict[str, int] = {}
        self._texts: list[str] = []
        self._lock = Lock()

    def slot(self, text: str) -> int:
        """The slot standing for *text*, assigning one on first sight.

        The hit path takes no lock -- a dict read is atomic and the mapping
        is append-only -- and the miss path re-checks under one, so two
        threads cannot hand two slots to one string.
        """
        known = self._by_text.get(text)
        if known is not None:
            return known
        with self._lock:
            known = self._by_text.get(text)
            if known is None:
                known = len(self._texts)
                self._texts.append(text)
                self._by_text[text] = known
            return known

    def text(self, slot: int) -> str:
        """The id string one slot stands for; ``""`` for :data:`NO_SLOT`."""
        if slot == NO_SLOT:
            return ""
        return self._texts[slot]

    def __len__(self) -> int:
        """How many distinct event ids this process has interned."""
        return len(self._texts)


# The one registry.  A second instance would be a second numbering, which is
# the failure the class docstring exists to prevent, so consumers reference
# this name rather than constructing their own.
EVENT_SLOTS = EventSlots()


# ---------------------------------------------------------------------------
# The typed action
# ---------------------------------------------------------------------------


class SurvivalAction(NamedTuple):
    """One typed state transition in the coupled survival walk.

    Both adapters consume exactly this interface.  ``event`` is the
    receipt adapter's observation target (the event dict the public
    timeline serializes); score-mode actions leave it ``None`` so the
    kernel never annotates what the optimizer does not read.

    ``phase`` is a :class:`TransitionRank`, and it defaults to the damage
    rank.  That default is not a formality: ``compiled_damage_action``
    deliberately assigns no phase, so it is where every compiled damage
    action in the hot path gets its phase from — the widest phase slot in
    the tree, not the narrowest.
    """

    # Ordering / routing
    sort_key: tuple = ()
    time: float = 0.0
    phase: TransitionRank = TransitionRank.DAMAGE
    kind: ActionKind = ActionKind.DAMAGE
    subject: int = -1
    attacker: int = -1
    # Ledger linkage
    aidx: int = -1
    trigger: int = -1
    # The four event references, as slots into EVENT_SLOTS (NO_SLOT for
    # "names none").  They were ``str | None`` id fields until Phase 4 S1;
    # every consumer compared them for identity, which is what a slot is.
    trigger_slot: int = NO_SLOT
    event: dict | None = None
    # Damage fields
    amount: float = 0.0
    damage_type: str = ""
    # The price this packet's family declared, for the walk to mitigate
    # itself (``transitions.apply_declared_price``).  ``None`` means "no
    # family declared one for this packet".  It is a value and not a float
    # defaulting to zero for the same reason ``live_amp`` is not a 1.0 — a
    # declaration nobody made and a declaration of nothing are different
    # answers, and only one of them may be paid.
    declared: DeclaredPacket | None = None
    raw_formula: Any = None
    raw_damage: float = 0.0
    grievous: Any = None
    wound: tuple | None = None
    reactive: bool = False
    # A live-predicate amplifier riding this packet, read before absorption
    # (``transitions._apply_live_packet_chain``).  ``None`` is "no holder
    # declared one for this packet" — an answer, not a neutral multiplier,
    # which is why the field is a value and not a float defaulting to 1.0.
    live_amp: LiveAmp | None = None
    execute_threshold_ratio: float = 0.0
    execute_source: str = ""
    deferred: bool = False
    deferred_batch_slot: int = NO_SLOT
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
    event_slot: int = NO_SLOT
    sequence: Any = None
    # The packet applied immobilizing crowd control: the trigger bus's answer
    # over the shared ``ability_spec.IMMOBILIZING_CC_KINDS`` vocabulary, or a
    # marker flag, never a set this module decides for itself.  Force of
    # Nature's Steadfast reads it for its two-stack branch.
    immobilized: bool = False
    cc_kind: str = ""
    cc_duration: float = 0.0
    skillshot: bool = False
    area_damage: bool = False
    damage_over_time: bool = False
    baseline_effective_armor: float | None = None
    baseline_effective_mr: float | None = None
    # Heal fields
    healing_category: str = ""
    #: Whether the caster's heal and shield power reaches this recovery.
    #: Stamped from the packet's own ``kind`` and ``healing_category``,
    #: which the kernel does not hold: health regeneration and the vamp
    #: family are drained rather than applied, and the game amplifies
    #: neither. Every other recovery is amplified, hence the default.
    amplified_recovery: bool = True
    amount_formula: Any = None
    requires_existing_shield: bool = False
    # P2 Slice 5: a self-cast that fires while the caster is crowd-
    # controlled (Gangplank W Remove Scurvy — game canCastWhileDisabled;
    # the QSS/Mercurial item precedent dispatches utility-kind cleanses
    # before the attacker gate).  The gate exempts HEAL kinds carrying
    # the flag from the crowd-control branch ONLY — stasis, invulnerable
    # and untargetable still block (the Cleanse atom: castable while
    # disabled, but not under suppression/stasis).
    cast_while_disabled: bool = False
    cast_blocked_by_attacker_control: bool = False
    # P2 Slice 7: the per-cast cleanse group (Milio R fan-out — one cast
    # authors one packet per recipient; the group is the shared one-use
    # latch key so all recipients of one cast consume ONE use).
    cleanse_group: str = ""
    # P3 package 3T: the compiled path pre-authors Maw's post-Lifeline
    # omnivamp heals with this gate; the kernel applies them only after
    # the threshold event armed the holder's omnivamp flag.
    requires_maw_lifeline_omnivamp: bool = False
    shield_gate_subject: int = -1
    shield_gate_time: float | None = None
    requires_holder_health_ratio: float = 0.0
    requires_damage_free_seconds: float = 0.0
    overheal_to_temporary_health: bool = False
    temporary_health_duration: float = 0.0
    overheal_to_shield: bool = False
    overheal_shield_cap: float = 0.0
    overheal_shield_duration: float = 0.0
    defy_trigger_slot: int = NO_SLOT
    # Timed / state kinds
    duration: float = 0.0
    # Revive windows: the sourced delay between the lethal hit and the
    # resurrection (the kernel re-anchors the window to the death time, so
    # a pre-lethal candidate never revives early).
    delay: float = 0.0
    health_ratio: float = 0.0
    on_block_heal_amount: float = 0.0
    on_block_heal_delay: float = 0.0
    on_block_heal_source: str = ""
    # Stat buff fields
    bonus_attack_speed_percent: float = 0.0
    bonus_armor: float = 0.0
    bonus_magic_resistance: float = 0.0
    bonus_health: float = 0.0
    ability_power: float = 0.0
    ability_haste: float = 0.0
    on_hit_magic_damage: float = 0.0
    shield_pool: str = ""
    crowd_control_immunity_while_shield: bool = False
    crowd_control_immunity_source: str = ""
    # Damage-modifier fields
    persistent: bool = False
    multiplier: float = 1.0
    damage_reduction: bool = False
    next_event_only: bool = False
    all_sources: bool = False
    armor_reduction_percent: float = 0.0
    mr_reduction_percent: float = 0.0
    resistance_type: str = ""
    # Which roster slot armed this modifier — the field the owner skip reads
    # (``Authority.SPLIT``'s machine-checked handshake).  A roster *index*,
    # like ``subject`` and ``attacker``, so the kernel never compares
    # participant id strings; ``-1`` is "this packet declares no holder", the
    # integer spelling of the empty owner string it replaces.  ``Provenance``
    # compiles into this field.
    holder: int = -1
    # The class restriction a damage-modifier packet declares (D-04).  Both
    # are required of such a packet and empty is banned, which is why the
    # class default is the empty set: a modifier action that reached the
    # walk without a declaration raises in ``declared_modifier_classes``
    # instead of quietly applying to everything.
    damage_classes: frozenset[DamageClass] = frozenset()
    attack_classes: frozenset[AttackClass] = frozenset()
    # A *restriction*, not a holder: the modifier applies only to damage
    # whose source is this participant (Aatrox's own curse amplifying only
    # his packets).  Distinct from ``holder`` above, which names who armed
    # it; a modifier may be armed by one participant and restricted to
    # another's damage.  ``""`` is "no source restriction".
    source_participant: str = ""
    # Utility fields
    # Which utility transition this packet is, when its kind classified as
    # ``ActionKind.UTILITY``.  The cleanse dispatch reads it (QSS/Mercurial
    # ride ``cleanse``-kind utility packets), which is why the field exists
    # again after the S-wave deleted it as unread.
    utility_kind: str = ""
    gold_amount: float = 0.0
    ward_uses: float = 0.0
    duration_set: bool = False

    @property
    def event_id(self) -> str:
        """This packet's id as text; ``""`` when it names none."""
        return EVENT_SLOTS.text(self.event_slot)

    # Cleanse-activation fields (item actives that remove crowd control).
    # ``cleanse`` marks a packet as a cleanse activation (Mikael's Purify
    # rides its heal packet with the marker; QSS/Mercurial ride cleanse-kind
    # utility packets); ``cleanse_item`` names the declaration item so the
    # walk can resolve the sourced eligibility without parsing display
    # labels.
    cleanse: bool = False
    cleanse_item: str = ""


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
_NO_CLASSES: frozenset = frozenset()
_CLASS_SETS: dict[frozenset, frozenset] = {}


def declared_class_set(value: Any, vocabulary: type) -> frozenset:
    """One packet's declared class set, failing closed to the empty set.

    An absent declaration is empty rather than guessed; a declaration
    spelled as anything but members of ``vocabulary`` raises, because a
    string that looks like a class is exactly the drift the enum retires.
    """
    if not value:
        return _NO_CLASSES
    members = frozenset(value if isinstance(value, Iterable) else (value,))
    if not all(isinstance(member, vocabulary) for member in members):
        raise TypeError(
            f"a packet declared {sorted(map(str, members))} where "
            f"{vocabulary.__name__} members are required"
        )
    return _CLASS_SETS.setdefault(members, members)


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


# --- Fast compiled-damage construction -------------------------------------
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
_I_EVENT_SLOT = _INDEX("event_slot")
_I_SEQUENCE = _INDEX("sequence")
_I_LIVE_AMP = _INDEX("live_amp")
_I_DECLARED = _INDEX("declared")
_I_IS_ABILITY = _INDEX("is_ability")
_I_BASIC_ATTACK = _INDEX("basic_attack")
_I_BASELINE_ARMOR = _INDEX("baseline_effective_armor")
_I_BASELINE_MR = _INDEX("baseline_effective_mr")
_I_IMMOBILIZED = _INDEX("immobilized")
_I_CC_KIND = _INDEX("cc_kind")
_I_CC_DURATION = _INDEX("cc_duration")
_I_SKILLSHOT = _INDEX("skillshot")
_I_DAMAGE_OVER_TIME = _INDEX("damage_over_time")
_I_AREA_DAMAGE = _INDEX("area_damage")
_I_ABILITY_INSTANCE = _INDEX("ability_instance")


def compiled_damage_action(
    sort_key: tuple,
    time: float,
    kind: ActionKind,
    subject: int,
    *,
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
    event_slot: int,
    sequence: Any,
    live_amp: LiveAmp | None,
    declared: DeclaredPacket | None,
    is_ability: bool,
    basic_attack: bool,
    baseline_effective_armor: float | None,
    baseline_effective_mr: float | None,
    immobilized: bool = False,
    cc_kind: str = "",
    cc_duration: float = 0.0,
    skillshot: bool = False,
    damage_over_time: bool = False,
    area_damage: bool = False,
    ability_instance: Any = None,
) -> SurvivalAction:
    """Build a compiler damage action without keyword-default parsing.

    Exactly ``SurvivalAction(**those twenty-eight fields)``: every other field
    keeps its class default, ``reactive=False`` and the phase included.  There is
    no ``_I_PHASE`` because the class default *is* ``TransitionRank.DAMAGE``; read
    the rank at :class:`SurvivalAction`, not here.

    Six parameters have no default, because each has a neutral value
    indistinguishable from an unasked question, and a compiler that forgot one
    would score a build silently missing a term:

    * ``live_amp`` is the amplification the packet earned.  Every call site
      states it, ``None`` included.
    * ``declared`` is the declaration the walk prices.  A compiler that omitted
      it would score the family at the pair engine's number after that row had
      left the total: priced twice on one path and not at all on the other.
    * ``is_ability`` and ``basic_attack`` are how a packet says it was delivered
      (:func:`attack_class_of`).  At their ``False`` default every compiled
      packet classifies as ``OTHER``, and a modifier declaring all three attack
      classes reaches only rows whose ``source_key`` is ``auto_attacks``.
    * The two resistance baselines are the pair fight's own final effective
      armour and magic resistance, which a resistance-reducing modifier re-prices
      its packet against.  ``None`` is the honest "this fight published no such
      figure", receipted as ``support_resistance_reduction_unavailable`` rather
      than as a made-up mitigation ratio.

    The delivery facts a certified packet carries (``immobilized``, ``cc_kind``,
    ``cc_duration``, ``skillshot``, ``damage_over_time``, ``area_damage``,
    ``ability_instance``) keep neutral defaults instead: they are the *absence* of
    a declaration rather than a number a compiler could forget, and each is inert.
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
    row[_I_EVENT_SLOT] = event_slot
    row[_I_SEQUENCE] = sequence
    row[_I_LIVE_AMP] = live_amp
    row[_I_DECLARED] = declared
    row[_I_IS_ABILITY] = is_ability
    row[_I_BASIC_ATTACK] = basic_attack
    row[_I_BASELINE_ARMOR] = baseline_effective_armor
    row[_I_BASELINE_MR] = baseline_effective_mr
    row[_I_IMMOBILIZED] = immobilized
    row[_I_CC_KIND] = cc_kind
    row[_I_CC_DURATION] = cc_duration
    row[_I_SKILLSHOT] = skillshot
    row[_I_DAMAGE_OVER_TIME] = damage_over_time
    row[_I_AREA_DAMAGE] = area_damage
    row[_I_ABILITY_INSTANCE] = ability_instance
    return tuple.__new__(SurvivalAction, row)


def action_key(
    event_time: float,
    phase: TransitionRank,
    participant_id: str,
    event: Mapping[str, Any],
) -> tuple[Any, ...]:
    """Order event phases without ever comparing payload dictionaries.

    The survival walk's total order.  Pair packets precompute it per event
    (``_sk``) because the walk re-sorts the same roster events for every
    optimizer candidate.

    Element 1 is the rank's :func:`ordering_slot`, not the rank: one pair of
    ranks resolves together, and folding it here keeps the inline sort tuples in
    ``compile.py`` comparable with this one.

    The ``_event_id`` component is a dead tie-break for engine damage events:
    ``sequence`` is unique per pair fight, and events from different pairs
    already differ at the source/participant components.  The compiler's
    pair-local event numbering depends on that, so an engine event arriving
    without its sequence is rejected rather than letting numbering become
    order-relevant.

    The timestamp must be **finite** here rather than at the one constructor:
    ``float()`` already rejects a malformed time, and NaN/inf is the one value
    it accepts that no total order can place.  Every action reaches this
    function, so one guard covers every author.
    """
    # Element 1 must be a rank on every key or the keys are not
    # comparable in one order: a caller holding a number would put its
    # ``0.0`` ahead of a ``BARRIER_GRANT`` that is spelled ``1``, which
    # is how a hostile control came to resolve before the Black Shield
    # that blocks it.  Every author now names a rank, so a non-member
    # is a defect rather than an older spelling to translate.
    if not isinstance(phase, TransitionRank):
        raise TypeError(
            f"action_key: phase must be a TransitionRank, got "
            f"{phase!r} (event_id={event.get('_event_id')!r})"
        )
    time_value = float(event_time)
    if not math.isfinite(time_value):
        raise ValueError(
            f"action_key: event time must be finite, got {event_time!r} "
            f"(event_id={event.get('_event_id')!r}); a non-finite timestamp "
            "cannot establish a stable total order"
        )
    source_id = event.get("attacker", participant_id)
    return (
        time_value,
        ordering_slot(phase),
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
    execute_ratio_raw: Any,
    *,
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


# The two helpers above are public because the one constructor lives in
# ``program.compile.action_from_event``, which classifies over prefetched
# hot fields and resolves a packet's declared class sets: a leading
# underscore on a name another layer must call is a boundary nobody can
# see.  What stays here is the vocabulary that constructor converts *into*.
__all__ = [
    "EVENT_SLOTS",
    "NO_SLOT",
    "SUPPORT_RANK_KEY",
    "UTILITY_KINDS",
    "ActionKind",
    "EventSlots",
    "LiveAmp",
    "LiveProbe",
    "SurvivalAction",
    "TransitionRank",
    "action_key",
    "attack_class_of",
    "classify_event_kind",
    "classify_prefetched",
    "damage_class_of",
    "declared_class_set",
    "declared_modifier_classes",
    "event_sequence",
    "ordering_slot",
    "participant_order",
    "public_phase",
    "support_transition_rank",
]
