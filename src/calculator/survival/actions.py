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
from threading import Lock
from typing import Any, NamedTuple

from ..ability_spec import AttackClass, DamageClass
from ..trigger_stream import is_immobilizing_event

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


# One pair of ranks resolves as one, and this is the last of what the
# deleted float ladder meant that the ordinals do not.  That ladder gave
# ``LATE_BARRIER`` and ``REACTIVE`` one number (0.5), so the pair folds onto
# its first member wherever the walk *orders* by rank.  ``LATE_BARRIER`` is
# a barrier an authored packet places *after* damage (Eclipse's self-shield,
# Fimbulwinter's Everlasting), which is why it is not ``BARRIER_GRANT``.
#
# It is a preserved defect and is named as one: a barrier resolving after
# the damage at its own timestamp absorbs nothing at that timestamp.  The
# row lives on ``docs/migration-frontier.json`` under ``preserved_defects``,
# declined by S6 because correcting it is a different reordering from the
# one this stage predicted and bounded.
#
# The ladder's other number (1.0) was shared by ``DEBUFF_ARM``, ``RECOVERY``
# and ``UTILITY_ARM``.  **Phase 4 S6 split them**, so they resolve in
# declaration order at a shared timestamp and appear here no longer.  What
# the split does *not* touch is which ranks the receipt adapter classifies
# as a recovery: that set was spelled as this fold's output and is now
# spelled as itself, in ``_RECOVERY_CLASSIFIED_RANKS`` below.
#
# Every other read of a rank is fold-invariant by construction: the kernel's
# comparisons are thresholds at a group boundary, and the surviving pair
# does not straddle one.
_ORDERING_SLOTS: dict[TransitionRank, TransitionRank] = {
    TransitionRank.REACTIVE: TransitionRank.LATE_BARRIER,
}


def ordering_slot(rank: TransitionRank) -> TransitionRank:
    """The rank a transition sorts *as*.

    Ordering only, since Phase 4 S6: classification asks a separate
    question and reads :data:`_RECOVERY_CLASSIFIED_RANKS` for its answer.

    Identity for every rank that resolves alone, and the pair's first member
    for the two that do not.  The fold cannot develop a hole the way a total
    table could: a rank absent from :data:`_ORDERING_SLOTS` resolves as
    itself, which is what a rank sharing its slot with nothing means.
    """
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

    Four kernel fields used to be event-id *strings*: the packet's own id,
    its trigger's, its deferral batch's and its Defy trigger's.  Every use of
    them is an identity question -- is this the packet that trigger applied?
    is this batch cleared? -- answered by string comparison inside the hot
    loop, and answered on strings the walk also has to rebuild by hand when
    it authors a derived id.

    A slot is a dense integer standing for exactly one id string.  Identity
    becomes an int compare, the sets and dicts the walk keys by a reference
    become int-keyed, and :meth:`text` gives the string back at the one place
    that still authors a derived id.

    **The registry is process-wide, deliberately.**  Actions outlive the call
    that built them: a pair packet's typed actions ride the packet cache, a
    signature panel's compiled actions ride the search context, and both are
    replayed inside walks built later.  A per-call registry would give two
    such actions slots from two different numberings inside one walk -- two
    different events answering to one integer, with no symptom.  One
    numbering for the process makes that unrepresentable.

    Growth is bounded rather than merely slow: every id is assembled from a
    closed vocabulary (roster slots ``main``/``ally:n``/``enemy:n``, mechanic
    labels, item names, source keys) and a small ordinal, so the distinct set
    converges instead of scaling with traffic.  Nothing is ever evicted,
    because a slot handed to a cached action must keep meaning the same event
    for as long as that action can be walked.
    """

    __slots__ = ("_by_text", "_texts", "_lock")

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
        """The id string one slot stands for; ``""`` for :data:`NO_SLOT`.

        The empty string is what every caller of this already wrote for a
        missing reference (``action.event_id or ""``), so the sentinel maps
        to it rather than to ``None``.  Any other unknown slot is a
        numbering bug and raises through the list index.
        """
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
    # The packet applied immobilizing crowd control — the trigger bus's
    # answer over the shared ``ability_spec.IMMOBILIZING_CC_KINDS``
    # vocabulary, or a legacy marker flag, never a set this module decides
    # for itself (D-08).  Force of Nature's Steadfast reads it for its
    # two-stack branch.
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
    defy_trigger_slot: int = NO_SLOT
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


def declared_class_set(value: Any, vocabulary: type) -> frozenset:
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
_I_EVENT_SLOT = _INDEX("event_slot")
_I_SEQUENCE = _INDEX("sequence")
_I_LIVE_AMP = _INDEX("live_amp")


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
    event_slot: int,
    sequence: Any,
    live_amp: LiveAmp | None,
) -> SurvivalAction:
    """Build a compiler damage action without keyword-default parsing.

    Exactly ``SurvivalAction(**those seventeen fields)``: every other field
    keeps its class default, ``reactive=False`` and the phase included.
    The phase is the load-bearing one — this function has no ``_I_PHASE``
    because the class default *is* ``TransitionRank.DAMAGE``, which is what the
    compiler would pass for a damage packet anyway.  Read the rank at
    :class:`SurvivalAction`, not here.

    ``live_amp`` has no default, and that is deliberate for the one field
    here whose neutral value is indistinguishable from an unasked question:
    a compiler that forgot to pass it would score a build whose
    amplification it silently dropped, which is the incident.  Every call
    site states it, ``None`` included.
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
    return tuple.__new__(SurvivalAction, row)


def action_key(
    event_time: float,
    phase: TransitionRank,
    participant_id: str,
    event: Mapping[str, Any],
) -> tuple[Any, ...]:
    """Order event phases without ever comparing payload dictionaries.

    This is the survival walk's total order.  Pair packets precompute it per
    event (``_sk``) because the walk re-sorts the same roster events for
    every optimizer candidate.

    Element 1 is the rank's :func:`ordering_slot`, not the rank: one pair of
    ranks still resolves together, and folding it here is what keeps the
    inline sort tuples in ``compile.py`` comparable with this one.  Since
    Phase 4 S6 the fold is the identity for every other rank, so a debuff,
    a recovery and a utility arming authored at one timestamp now order
    ``6 < 7 < 8`` instead of tying and falling through to ``sequence``.

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
    *after* the damage that triggered them, not before it, so they declare
    ``LATE_BARRIER`` where the kind alone would say ``BARRIER_GRANT``; and
    Abyssal Mask's Unmake is a persistent aura rather than a triggered
    debuff, so it declares ``AURA_ARM`` where the kind alone would say
    ``DEBUFF_ARM``.  The declaration is a member of :class:`TransitionRank`
    and nothing else, so an author can choose a rank but cannot invent an
    ordering.

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
        get("_deferred"),
        get("_redirected"),
        get("raw_formula"),
        float(get("raw_damage", 0.0) or 0.0),
        float(get("grievous_duration", 0.0) or 0.0),
    )


# The two helpers above are public because the one constructor is no longer
# in this module: ``program.compile.action_from_event`` classifies over
# prefetched hot fields and resolves a packet's declared class sets, and a
# leading underscore on a name another layer must call is a boundary nobody
# can see.  The conversion itself moved with the constructor (Phase 4 S4);
# what stays here is the vocabulary it converts *into*.
__all__ = [
    "ActionKind",
    "EVENT_SLOTS",
    "EventSlots",
    "LiveAmp",
    "LiveProbe",
    "NO_SLOT",
    "SUPPORT_RANK_KEY",
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
