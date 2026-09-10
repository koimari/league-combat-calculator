"""The typed action the walk consumes: its kind, its live amplification, and its trigger linkage."""

from __future__ import annotations

from enum import Enum
from typing import Any, NamedTuple

from ..ability_spec import AttackClass, DamageClass
from .event_slots import EVENT_SLOTS, NO_SLOT
from .phases import TransitionRank
from .pricing import DeclaredPacket


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
    # A rider whose trigger is "the holder's next ability hit", which only
    # the walk can resolve: ``trigger_slot`` names one carrier packet chosen
    # by ordinal before the walk knew which packets land, and this flag lets
    # the kernel move the rider to the first ability packet that does land
    # (``transitions._rebind_self_shields``).  ``slotlib.attach_self_shield``
    # is what declares it; the Eclipse item's self-shield does not, and keeps
    # the one carrier it was authored on.
    rebinds_on_ability_hit: bool = False
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


class TriggerLinkage:
    """Trigger-linkage status by event slot, the protocol every ledger carries.

    ``trigger_status`` is the adapter's own dict; a slot is ``"applied"`` or
    ``"blocked"`` once its packet resolved and absent until then.
    """

    __slots__ = ()
    trigger_status: dict[int, str]

    def trigger_applied(self, action: SurvivalAction) -> bool:
        """Whether this action's trigger applied; no trigger passes, and a
        skipped trigger fails closed rather than silently applying."""
        if action.trigger_slot == NO_SLOT:
            return True
        return self.trigger_status.get(action.trigger_slot) == "applied"

    def mark_applied(self, action: SurvivalAction) -> None:
        """Mark this action's event as applied for trigger linkage."""
        self._mark(action, "applied")

    def mark_blocked(self, action: SurvivalAction) -> None:
        """Mark this action's event as blocked for trigger linkage."""
        self._mark(action, "blocked")

    def _mark(self, action: SurvivalAction, status: str) -> None:
        if action.event_slot != NO_SLOT:
            self.trigger_status[action.event_slot] = status
