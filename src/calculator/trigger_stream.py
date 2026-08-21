"""The typed trigger bus and the capability registry that projects it.

Two questions used to be answered by five hand-maintained name sets in
``item_support_effects``: "which raw event rows mean crowd control / damage
/ a takedown?" and "which holders read which of those streams?".  A set and
the branch it guards drift the moment one is edited without the other, and
the campaign this module belongs to exists because exactly that drift
priced Imperial Mandate's Command at zero without a single error.

So both questions get one home.  :func:`event_triggers` is the only place a
raw row is classified, and :data:`CAPABILITIES` is the only place a mechanic
declares which streams it consumes — every adequacy set the pipeline and the
timeline consult is a *projection* of that declaration rather than a second
list of names.

The module is a leaf on purpose: it imports exactly two intra-package
modules, ``ability_spec`` and ``program.views``, and both are import-free
vocabulary leaves — so the hot pipeline can ask a ledger-shape question
without loading the 52 KB packet compiler.  Registry validation is
structural only and reads no file (D-35) — item-name resolution lives in the
test that pins the projections.
"""

# The module is long because most of it is one declaration table; splitting
# the registry out would make every projection a cross-module round trip and
# duplicate the acyclicity proof, which is the trade this phase deliberately
# rejected.  The repo idiom (``rune_effects._KEYSTONE_COMPILERS``,
# ``item_source.ACKNOWLEDGED_SOURCE_CONFLICTS``) co-locates a frozen table
# with its reader for the same reason.
# pylint: disable=too-many-lines

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from functools import cache
from types import MappingProxyType
from typing import Any, NamedTuple

from .ability_spec import (
    CC_KIND_VOCABULARY,
    IMMOBILIZING_CC_KINDS,
    Authority,
    Disposition,
)

# The module's second intra-package import, and Phase 4 S7's own amendment to
# the "exactly one" clause Phase 2 shipped.  ``view_tags`` is a field of the
# declaration table below, so its vocabulary has to be nameable here, and the
# two properties that clause protects are re-asserted rather than relaxed:
# ``program.views`` imports nothing at all, so the package graph stays acyclic
# and importing the bus still reads no file.  That is also why the enum is
# admissible while ``EngineLane``'s home is not — importing ``item_behavior``
# opens ``data/items.json`` and ``data/runes.json`` at module scope, and a bus
# that reads ``data/`` is neither a leaf nor inside the caching layer (D-35).
from .program.views import ViewTag

__all__ = [
    "Authority",
    "CAPABILITIES",
    "CROSS_PARTICIPANT_AUTHORITIES",
    "CcClass",
    "ChampionSlotOwner",
    "DIVERGENCES",
    "DivergenceReceipt",
    "Engine",
    "EngineOwner",
    "Field",
    "HolderPacket",
    "ItemOwner",
    "MechanicCapability",
    "MechanicOwner",
    "Pairing",
    "ProjectionStarvation",
    "StarvedSignal",
    "RAW_STREAMS",
    "RiderDelivery",
    "RuneOwner",
    "Stream",
    "Trigger",
    "TriggerKind",
    "TriggerRegistryError",
    "authored_triggers",
    "cross_participant_packet_source",
    "delivery_reference",
    "enriched_view_items",
    "event_triggers",
    "holders_in",
    "is_immobilizing_event",
    "packet_source_literal",
    "pair_outcome_items",
    "streams_for",
    "tuple_incapable_items",
]


class TriggerKind(Enum):
    """What one bus row *is*.

    Three kinds, not four: ``SUPPORT_TRIGGER`` is declarable in a
    capability's ``reads`` but is built from authored ally heal/shield
    templates rather than parsed off a raw row, so it is a :class:`Stream`
    and never a ``TriggerKind``.
    """

    CC = "cc"
    DAMAGE = "damage"
    TAKEDOWN = "takedown"


class CcClass(Enum):
    """The one classification consumers branch on (D-32, D-33).

    ``cc_kind`` survives on :class:`Trigger` as an opaque receipt token; a
    consumer that compares it against a string is re-creating the divergence
    that let slows trigger Command.  Five members, because the live stream
    admits rows carrying only the bare ``crowd_control`` flag:

    * ``NONE`` — a reviewed statement that this row applies no control.
    * ``SLOW`` — real crowd control that is never an immobilize.
    * ``IMMOBILIZE`` — the Wiki's immobilizing class.
    * ``UNCLASSIFIED_CONTROL`` — control was authored but not narrowed, so
      an immobilize-only consumer must not fire and a control-any consumer
      must.
    * ``UNREVIEWED`` — nobody said anything.  Never a trigger, and never
      spelled ``NONE``: a silent absence and a reviewed "no control" are the
      two things this campaign refuses to conflate.
    """

    NONE = "none"
    SLOW = "slow"
    IMMOBILIZE = "immobilize"
    UNCLASSIFIED_CONTROL = "unclassified_control"
    UNREVIEWED = "unreviewed"


class Stream(Enum):
    """The declaration vocabulary — what a mechanic asks the bus to build.

    ``SUPPORT_TRIGGER`` is the ally heal/shield template stream.  It is
    declarable and parses no raw row, which is what lets the projections
    separate "reads ally templates" (Ardent Censer) from "reads no stream at
    all" (Cull, the support-quest items).
    """

    CC = "cc"
    DAMAGE = "damage"
    TAKEDOWN = "takedown"
    SUPPORT_TRIGGER = "support_trigger"


class Field(Enum):
    """A raw-row field a mechanic reads off a stream it declares.

    ``needs`` is about *raw* rows: a ``SUPPORT_TRIGGER``-only reader consumes
    authored templates rather than engine rows and therefore declares none.
    ``EVENT_ID`` and ``TARGET_ID`` are the two the pair path supplies only
    under its enriched per-event view, which is why
    :func:`enriched_view_items` is a projection of this field and not a list.
    """

    TIME = "time"
    TARGET_ID = "target_id"
    EVENT_ID = "event_id"
    ATTACKER_ID = "attacker_id"
    SOURCE_KEY = "source_key"
    SEQUENCE = "sequence"
    DAMAGE = "damage"
    RAW_DAMAGE = "raw_damage"
    DAMAGE_TYPE = "damage_type"
    IS_ABILITY = "is_ability"
    BASIC_ATTACK = "basic_attack"
    REACTIVE = "reactive"
    CC = "cc"
    ABILITY_INSTANCE = "ability_instance"


class Engine(Enum):
    """Which engine implements a mechanic — the pair fight or the roster walk."""

    PAIR = "pair"
    WALK = "walk"


class Pairing(Enum):
    """Whether a mechanic's two engine halves are declared and reconciled.

    ``UNPAIRED_KNOWN_DEFECT`` is the escape hatch, and it is asserted empty
    (D-92): the next divergence has to be a typed entry pointing at a
    :class:`DivergenceReceipt`, never a silent omission.
    """

    SOLO = "solo"
    PAIRED = "paired"
    UNPAIRED_KNOWN_DEFECT = "unpaired_known_defect"


class HolderStacking(Enum):
    """Whether a second holder of one mechanic arms a second modifier (D-66).

    The two answers are genuinely different mechanics, not two spellings of
    one.  Abyssal Mask's Unmake is an aura: two holders standing in range of
    one enemy curse it once, so the arm-time dedupe key is
    ``(subject, mechanic_id)`` and the second arming is dropped with a
    ``dedupe`` receipt row.  Imperial Mandate's Command is a per-holder
    pool: two Mandate holders each pay their own amplification, so the key
    keeps the holder and neither contribution is dropped.

    A single flat key would be the incident's own shape mandated by a rule —
    a second holder's number silently vanishing — which is why this is a
    required, defaultless declaration on every dual-sided mechanic rather
    than a policy the arming code picks.

    Declared here, beside :class:`Pairing` and :class:`Engine`, because it is
    a field of the same registry: giving it a module of its own would cost
    ``trigger_stream`` an intra-package import for no reader's benefit.
    Phase 4 owns it; ``program.amp.arm_key`` is its one consumer.
    """

    IDEMPOTENT_AURA = "idempotent_aura"
    PER_HOLDER = "per_holder"


# The three streams whose rows are parsed off an engine result.  A holder
# reading any of them cannot be handed the optimizer's positional 6-tuple
# ledger, which is exactly what ``tuple_incapable_items`` projects.  Public
# for the same reason ``CROSS_PARTICIPANT_AUTHORITIES`` is: the item scan's
# starvation tripwire has to say *which* stream a starved holder reads, and
# it reads CAPABILITIES through this constant rather than re-spelling the
# three members beside a second holder-to-stream table.
RAW_STREAMS = frozenset({Stream.CC, Stream.DAMAGE, Stream.TAKEDOWN})

# The two kinds one authored damage row can yield.  A takedown is its own
# receipt row and never comes off this ledger.
_ROW_KINDS = frozenset({TriggerKind.CC, TriggerKind.DAMAGE})

# The classifications that *are* control, and therefore fire a CC trigger.
# ``NONE`` is a reviewed "no control" statement and ``UNREVIEWED`` a silent
# absence; neither may ever trigger, which is the whole point of keeping
# them distinct.
_CONTROL_CLASSES = frozenset(
    {CcClass.SLOW, CcClass.IMMOBILIZE, CcClass.UNCLASSIFIED_CONTROL}
)

# The two fields the pair path supplies only under its enriched per-event
# view; needing either is what puts a holder in ``enriched_view_items``.
_ENRICHED_FIELDS = frozenset({Field.EVENT_ID, Field.TARGET_ID})

# The three ``Authority`` members a mechanic declares only when a second
# engine can see the mechanic.  ``COUPLED_AUTHORITATIVE`` is the ordinary
# statement that the walk owns its own packet; the three below each
# additionally say the pair engine sees it too.  Declaring one is *necessary*
# for a cross-participant producer and not sufficient — the sufficient
# reading is :func:`cross_participant_packet_source`, which additionally
# requires the half's delivery to reach *another* participant: a
# rider-delivered half amplifies its own holder's event, and a
# :class:`HolderPacket` half packets its own holder's damage, so neither
# modifies anybody else's (D-07, Amendment C; Amendment M, Ruling 3).  A
# producer is one the coupled golden baseline must
# hold a scenario for (R-12), and the instrument reads CAPABILITIES through
# that function rather than re-spelling either condition.
CROSS_PARTICIPANT_AUTHORITIES = frozenset(
    {
        Authority.SPLIT,
        Authority.COUPLED_ONLY,
        Authority.COUPLED_AUTHORITATIVE_WITH_PAIR_PREVIEW,
    }
)

_MECHANIC_SLUG = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")
_IMPL_PATH = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$")

_DAMAGE_TYPES = frozenset({"physical", "magic", "true"})


class TriggerRegistryError(RuntimeError):
    """A declaration is structurally invalid; raised at import of this module."""


class StarvedSignal(RuntimeError):
    """A leaf has no value a rule computed, and saying so is the only answer.

    The class D-25's one boundary converts, named by the umbrella's
    Amendment G of 2026-08-14.  D-25's rule is about *where* a named refusal
    becomes a response — one place, allowlisted by source assertion, absorbed
    nowhere — and never a count of the exception types that one handler
    names.  Two conditions reach it, and they are the same disposition:

    * a projection cannot answer the question a consumer asked
      (:class:`ProjectionStarvation`);
    * a write-once record holds two answers to one question, or two applied
      contributions for one key, so it cannot answer either
      (``survival.outcome_state``'s three raises).

    Both are programming errors and in both the leaf has no computed value,
    which is the whole of what ``STARVED`` means — so the invariant table
    owes no fifth spelling.  Every member carries ``field``, ``producer`` and
    ``reason``, because the boundary publishes those three and a member that
    could not fill them would arrive as a 500 with a name and nothing else.

    Subclassing ``RuntimeError`` rather than replacing it: every member was
    one already, and a caller that catches ``RuntimeError`` today keeps
    catching it.
    """

    #: The campaign disposition every member of this class *is*, so the one
    #: boundary that converts one into a response reads the spelling off the
    #: exception rather than re-deriving which of the four states it is.
    disposition = Disposition.STARVED

    def __init__(self, message: str, field: str, producer: str, reason: str) -> None:
        """Name the leaf, who was asking for it, and why it has no answer."""
        super().__init__(message)
        self.field = field
        self.producer = producer
        self.reason = reason


class ProjectionStarvation(StarvedSignal):
    """A consumer asked a stream a question this result cannot answer.

    A projection and a consumer disagree, which is a programming error and
    not a data condition.  It is raised lazily, on the first read of an
    inadequate representation, and caught at exactly one boundary — the
    request boundary in ``src/app.py`` (D-25).  Everywhere else it
    propagates, because a named refusal that is silently absorbed is the
    zero this campaign exists to kill.
    """

    def __init__(self, field: str, producer: str, reason: str) -> None:
        super().__init__(
            f"STARVED: {producer or '<unnamed holder>'} asked for the "
            f"{field} stream — {reason}",
            field,
            producer,
            reason,
        )


# A row is seventeen facts; a record of seventeen fields is the honest
# shape for it, and collapsing them into sub-objects would put the bus's
# own vocabulary behind another indirection.
@dataclass(frozen=True, slots=True)
class Trigger:  # pylint: disable=too-many-instance-attributes
    """One authored event, classified once, read by both engines.

    Frozen and slotted with ``eq=True``/``order=False``: triggers are
    compared and hashed in dedupe keys but never sorted, because their order
    is the bus's own — emission order — and not a property of the value.

    Every construction violation raises ``ValueError`` naming the field.  A
    ``cc_kind`` outside ``CC_KIND_VOCABULARY`` in particular cannot enter the
    stream at all: a misspelled kind must never author a no-op stun.

    ``source_key`` is required on the **damage** stream and on it alone,
    because that is the stream consumers dispatch on: Phage's Rage reads
    ``"auto_attacks"`` and Bloodsong's Expose Weakness reads
    ``"spellblade_Bloodsong"``, so an unattributed damage row is a row those
    two would price wrong rather than skip.  Nothing dispatches on a control
    row's source — Everlasting identifies a control row by its
    ``ability_instance``, falling back to source-and-time — and requiring one
    there would reject authored control the legacy scanner accepted, which a
    refactor may not do.

    ``damage_type`` is enforced on that same stream and for the same reason.
    Carve dispatches on ``"physical"`` and Vile Decay on ``"magic"``, so a
    damage row typed outside the vocabulary is a row they would misprice;
    nothing dispatches on a control row's type, and the retired control
    scanner this classifier replaced accepted a control row carrying any
    type at all — including the
    ``"mixed"`` that ``damage._damage_type_fields`` really does emit.  On the
    control stream the field is therefore carried verbatim as a receipt of
    what the row said, exactly as ``source_key`` is.
    """

    kind: TriggerKind
    time: float
    source_key: str
    event_id: str
    attacker_id: str
    target_id: str
    sequence: int
    ability_instance: str
    damage: float
    raw_damage: float
    damage_type: str
    is_ability: bool
    basic_attack: bool
    reactive: bool
    cc: CcClass
    cc_kind: str
    cc_reviewed: bool

    def __post_init__(self) -> None:
        if not isinstance(self.kind, TriggerKind):
            raise ValueError("Trigger kind must be a TriggerKind member")
        if not isinstance(self.cc, CcClass):
            raise ValueError("Trigger cc must be a CcClass member")
        if not math.isfinite(self.time):
            raise ValueError(f"Trigger time must be finite, got {self.time!r}")
        if self.cc_kind and self.cc_kind not in CC_KIND_VOCABULARY:
            raise ValueError(
                f"Trigger cc_kind {self.cc_kind!r} is not in CC_KIND_VOCABULARY "
                f"({sorted(CC_KIND_VOCABULARY)}); a misspelled kind must never "
                "author a no-op stun"
            )
        if self.kind is TriggerKind.CC and self.cc is CcClass.NONE:
            raise ValueError(
                "Trigger cc must not be NONE on a CC trigger: NONE is a "
                "reviewed 'no control' statement and can never fire one (D-33)"
            )
        if self.kind is TriggerKind.DAMAGE and not self.source_key:
            raise ValueError(
                f"Trigger source_key is required on a {self.kind.value} trigger"
            )
        if (
            self.kind is TriggerKind.DAMAGE
            and self.damage_type
            and self.damage_type not in _DAMAGE_TYPES
        ):
            raise ValueError(
                f"Trigger damage_type {self.damage_type!r} is not one of "
                f"{sorted(_DAMAGE_TYPES)}"
            )
        for name in ("damage", "raw_damage"):
            value = getattr(self, name)
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(
                    f"Trigger {name} must be finite and non-negative, got {value!r}"
                )


@dataclass(frozen=True, slots=True)
class ItemOwner:
    """A mechanic an item grants."""

    name: str


@dataclass(frozen=True, slots=True)
class RuneOwner:
    """A mechanic a compiled keystone grants."""

    name: str


@dataclass(frozen=True, slots=True)
class ChampionSlotOwner:
    """A mechanic one champion's ability slot declares."""

    champion: str
    slot: str


@dataclass(frozen=True, slots=True)
class EngineOwner:
    """A mechanic the engine itself owns, with no item, rune or champion.

    The ``*Owner`` suffix is not decoration: :class:`Engine` is already the
    ``PAIR | WALK`` enum on the same dataclass, so the internal-producer
    variant needs its own name to sit beside it.
    """

    label: str


MechanicOwner = ItemOwner | RuneOwner | ChampionSlotOwner | EngineOwner


@dataclass(frozen=True, slots=True)
class DivergenceReceipt:
    """A reviewed, cited disagreement between two engines pricing one mechanic.

    Declared here because ``Pairing.UNPAIRED_KNOWN_DEFECT`` and
    ``divergence_ref`` are this module's, so the reference and its referent
    keep one home.  Phase 3 creates the one live instance (Bloodsong) and
    Phase 4 retires it; Phase 2 created none.
    Precedent: ``item_source.ACKNOWLEDGED_SOURCE_CONFLICTS``.

    A receipt is **not** the same statement as
    ``Pairing.UNPAIRED_KNOWN_DEFECT``, which says one half is missing.  Both
    of Bloodsong's halves exist and are declared; what they do not do is
    compute the same number.  That is a *paired* mechanic with a reviewed
    disagreement, and it is why ``divergence_ref`` is required for an
    unpaired defect and permitted — never required — for a paired one.
    """

    ref: str
    mechanic: str
    pair_reading: str
    walk_reading: str
    source_url: str
    revision_id: int
    issue_ref: int


# **Empty, and that is the end state.**  The campaign's one live divergence
# was Bloodsong's Expose Weakness: the pair engine amplified one coarse row
# once for the whole fight while the walk armed a timed modifier per
# spellblade proc, and the two were frozen behind a reviewed receipt until an
# engine could be named authoritative.  Phase 4 S7 named one -- the walk,
# because the pool of amplified damage is every roster attacker's damage
# inside a live window -- and the pair reading became a declared
# ``THEORETICAL`` preview instead of a rival answer.  A receipt records a
# disagreement *nobody has adjudicated*; once one side is the answer, keeping
# it would be filing a settled question as an open one.
#
# The type stays and this mapping is asserted empty (D-92).  The next
# divergence has to be a typed entry pointing at a receipt, never a silent
# omission.
DIVERGENCES: Mapping[str, DivergenceReceipt] = MappingProxyType({})


@dataclass(frozen=True, slots=True)
class RiderDelivery:
    """A walk half that delivers its number as a rider, not as a packet.

    Most walk halves hand the walk a support packet naming the participant
    whose damage they modify, and that packet's ``source`` literal is how
    every consumer finds it.  A few do not.  Shadowflame's Cinderbloom is an
    ``AmpBonus`` **rider stamped onto its own triggering damage event** and
    read before absorption, which is the phase's ruling and the whole fix for
    a spell-shielded or post-death trigger still emitting a bonus: a rider
    dies with its host.  A rider is not a packet, so such a half authors
    none.

    It still has a *delivery reference* — the rider stamp
    (``pair_preview_of`` on the pair side, the ``AmpBonus`` source on the
    walk side) — and that is what this type carries.  Declaring it as its own
    type inside the same field is what keeps two rules true at once:
    ``PAIRED`` still implies "name the delivery your pair half is paired
    against", and the cross-participant producer set stays keyed on D-07's
    own semantic — *every packet modifying another participant's damage* —
    rather than on "carries something in this field".  A rider amplifies the
    event it rides, and that event belongs to its own holder, so a
    rider-delivered half modifies no other participant's damage and is not a
    producer (:func:`cross_participant_packet_source`).

    Amendment C to D-07, 2026-08-13, recorded in the campaign umbrella.
    """

    #: The literal a rider's rows carry, verbatim — the counterpart of a
    #: packet's ``source`` and, like it, the string a reader greps for.
    stamp: str


@dataclass(frozen=True, slots=True)
class HolderPacket:
    """A walk half that packets a number onto **its own holder's** damage.

    The second self-scoped delivery, and the counterpart of
    :class:`RiderDelivery` on the other axis.  A rider is self-scoped because
    of *how* it travels — stamped on an event its holder already authored.
    This one travels as an ordinary walk packet, with a ``source`` literal
    like any other, and is self-scoped because of *whose damage it modifies*:
    a retired family's walk half prices the damage of the participant holding
    the item, so no second participant's number moves when it resolves.

    Declaring it as its own type inside the same field is what keeps D-07's
    semantic the thing the producer set is keyed on.  Amendment C settled
    that "carries something in ``packet_source``" may not stand in for
    "modifies another participant's damage", and keyed rider-delivery out of
    the set on that reasoning; the umbrella's **Amendment M, Ruling 3**
    (2026-08-15) rules the same semantic for packet-delivered halves, so that
    a family retiring off the pair engine does not enrol in the ruled six
    merely because its retirement slice had to declare a walk half.  A ruled
    count moved to satisfy a validator is the move both amendments refuse,
    from the two delivery shapes.

    Everything else a packet-delivered half is asked for still answers the
    same way: :func:`packet_source_literal` and :func:`delivery_reference`
    both return the literal, because this *is* a packet and consumers that
    arm on its source have to find it.  Only
    :func:`cross_participant_packet_source` — the one reading that asks
    *whose* damage — says no.
    """

    #: The ``source`` literal this half's packets carry, verbatim — the same
    #: string a cross-participant half would put in ``packet_source``.
    source: str


#: The two deliveries whose subject is the half's own holder.  Named once so
#: the three readings below branch on one set rather than on two ``isinstance``
#: pairs that could drift apart: a self-scoped delivery is the *semantic*
#: D-07 keys on (Amendment C for the rider, Amendment M, Ruling 3 for the
#: holder packet), and a third one would join here rather than at three sites.
SELF_SCOPED_DELIVERIES = (RiderDelivery, HolderPacket)


# Thirteen fields: Phase 2's eleven plus the two Phase 4 writes here.  A
# declaration record is exactly as wide as the facts it declares.
@dataclass(frozen=True, slots=True)
class MechanicCapability:  # pylint: disable=too-many-instance-attributes
    """One mechanic's declared transport, authority and implementation site.

    Phase 2 writes the first eleven fields.  Phase 4 adds ``view_tags`` and
    ``holder_stacking``, both required with no default on the commit that
    adds them, so a later phase's field forces every declaration to be
    revisited instead of silently inheriting an empty value.  (Phase 3's
    ``values`` and ``compilability`` are declared per *rule*, on
    ``item_behavior.BehaviorRule``, which is where its rule union lives.)

    Attributes:
        mechanic: the registry key, ``<owner_slug>.<effect_slug>``.
        owner: who grants it — an item, a rune, a champion slot, or the
            engine itself (D-36).
        engine: which engine implements *this* half of it.
        reads: the bus streams this half consumes.  ``frozenset()`` is
            legal and meaningful: an option-only producer, a scenario-state
            receipt, or live state inside the walk reads no stream, and
            declaring that is what stops somebody unifying it onto the bus
            by accident (D-31).
        needs: raw-row fields it reads off those streams.
        authority: which engine owns the mechanic, per the campaign's
            authority rule.  ``COUPLED_AUTHORITATIVE`` is the ordinary
            statement that the walk owns its own packet; ``SPLIT``,
            ``COUPLED_ONLY`` and ``COUPLED_AUTHORITATIVE_WITH_PAIR_PREVIEW``
            each additionally say a second engine can see the mechanic, and
            are therefore declared only by cross-participant producers.
        pairing: whether both halves are declared and reconciled.
        pair_of: the ``Engine.PAIR`` capability this walk half pairs with.
            Required exactly when ``pairing is PAIRED``.
        divergence_ref: a :data:`DIVERGENCES` key.  Required exactly when
            ``pairing is UNPAIRED_KNOWN_DEFECT``.
        impl: the dotted path of the function that implements this half.
        packet_source: this half's **delivery reference** — the walk packet's
            ``source`` string verbatim for a half whose packet modifies
            another participant's damage, a :class:`HolderPacket` naming the
            same literal for one whose packet modifies its own holder's, a
            :class:`RiderDelivery` naming the rider stamp for a half whose
            number rides an event the walk already carries, and ``None`` for
            a half that delivers none of the three.  Read it through
            :func:`packet_source_literal`, :func:`delivery_reference` or
            :func:`cross_participant_packet_source` rather than directly:
            each names one of the three different questions the field is
            asked, and answering them by an ``is not None`` test is what let
            "carries something here" stand in for "modifies another
            participant's damage" (D-07, Amendment C; Amendment M, Ruling 3
            for the packet-delivered self-scoped half).
        view_tags: what this half's numbers *mean*, keyed by the engine that
            produces them — ``APPLIED`` for a number the coupled walk
            delivered, ``THEORETICAL`` for a pair-engine preview of one
            (D-62).  Keyed rather than bare because the tag is a fact about
            ``(mechanic, engine)`` and a mechanic's two halves can carry
            different tags; ``program.build.CapabilityView`` widens the key
            to ``EngineLane``, whose home reads ``data/`` and therefore
            cannot be named in this leaf.
        holder_stacking: whether a second holder of this mechanic arms a
            second modifier on one subject (D-66).  Required exactly on a
            dual-sided walk half — a ``PAIRED`` row — and ``None`` on every
            other, structurally validated at import the way ``pair_of`` is,
            so a dual-sided declaration that omits it fails to construct
            rather than inheriting a guess.
    """

    mechanic: str
    owner: MechanicOwner
    engine: Engine
    reads: frozenset[Stream]
    needs: frozenset[Field]
    authority: Authority
    pairing: Pairing
    pair_of: str | None
    divergence_ref: str | None
    impl: str
    packet_source: str | RiderDelivery | HolderPacket | None
    view_tags: Mapping[Engine, ViewTag]
    holder_stacking: HolderStacking | None


def packet_source_literal(capability: MechanicCapability) -> str | None:
    """The ``source`` literal this half's packets carry, or ``None``.

    ``None`` twice over: for a half that emits nothing, and for a
    rider-delivered one, whose number arrives stamped on an event somebody
    else authored and is therefore findable under no packet source.  A
    :class:`HolderPacket` half *is* packet-delivered and answers with its
    literal, because everything that arms on a packet source has to find it
    — self-scoped says whose damage moves, not whether a packet exists.
    """
    source = capability.packet_source
    if isinstance(source, HolderPacket):
        return source.source
    return source if isinstance(source, str) else None


def delivery_reference(capability: MechanicCapability) -> str | None:
    """The literal this half's number arrives under — packet or rider.

    The one reading that treats every delivery alike, and the one ``PAIRED``
    asks: a paired walk half has to name *some* delivery for its pair half to
    be paired against, and this is that name.
    """
    source = capability.packet_source
    if isinstance(source, RiderDelivery):
        return source.stamp
    if isinstance(source, HolderPacket):
        return source.source
    return source


def cross_participant_packet_source(capability: MechanicCapability) -> str | None:
    """The packet through which this half modifies ANOTHER participant's damage.

    D-07's semantic with one home (Amendment C, extended by Amendment M,
    Ruling 3): the producer set is a filter over this function rather than a
    hand list, so a seventh producer joins it on the commit that declares
    one.  Three conditions, each of which drops a half that modifies no other
    participant's damage — a pair half authors no walk packet; an authority
    outside :data:`CROSS_PARTICIPANT_AUTHORITIES` says no second engine sees
    the mechanic; and a **self-scoped delivery** modifies damage that belongs
    to its own holder.

    That third condition is the amendment, and it now reads the semantic
    rather than the delivery shape.  Amendment C wrote it as "not a rider",
    because a rider amplifies the event it rides and that event is its
    holder's.  Amendment M rules the same question for a *packet*-delivered
    half: a retired family's walk half prices its own holder's damage, so
    :class:`HolderPacket` drops out here for the reason
    :class:`RiderDelivery` does and not for a second reason.  Keying the set
    on "a walk half with a cross-participant authority that carries
    *anything* in ``packet_source``" would enrol Shadowflame's Cinderbloom —
    whose subject is the holder — the moment its walk half is declared, and
    would enrol every retiring family after it; either way a ruled count
    would have moved to satisfy a validator.
    """
    if capability.engine is not Engine.WALK:
        return None
    if capability.authority not in CROSS_PARTICIPANT_AUTHORITIES:
        return None
    if isinstance(capability.packet_source, SELF_SCOPED_DELIVERIES):
        return None
    return packet_source_literal(capability)


_SUPPORT_IMPL = "item_support_effects.derive_item_support_effects"
_KNIGHTS_VOW_IMPL = "item_support_effects.schedule_knights_vow"
# Where a retired family's walk half turns its declaration into a number: one
# pricing site for every such half, because "the family's numbers reach the
# walk through exactly one interpreter" is the property the retirement act
# discharges (umbrella Amendment K).
_DECLARED_PRICE_IMPL = "survival.transitions.apply_declared_price"


def _walk_item(  # pylint: disable=too-many-arguments
    mechanic: str,
    item: str,
    packet_source: str | RiderDelivery,
    *,
    holder_stacking: HolderStacking | None,
    reads: frozenset[Stream] = frozenset(),
    needs: frozenset[Field] = frozenset(),
    authority: Authority = Authority.COUPLED_AUTHORITATIVE,
    pairing: Pairing = Pairing.SOLO,
    pair_of: str | None = None,
    divergence_ref: str | None = None,
    impl: str = _SUPPORT_IMPL,
    view_tag: ViewTag = ViewTag.APPLIED,
) -> MechanicCapability:
    """One item-granted mechanic the participant walk implements.

    A constructor, not a default: every field the umbrella assigns Phase 2
    still has to be written for every row, and the keyword defaults here are
    the values that are true of the *majority* of walk packets — no stream,
    no raw field, the walk owns its own packet, no pair-side half, and a
    number the coupled walk delivered rather than previewed.  A row that
    differs states its difference at the call site, which is what makes the
    table readable as a table.

    ``packet_source`` is the half's **delivery reference**, and it is a
    :class:`RiderDelivery` for the one walk half that authors no packet:
    Shadowflame's Cinderbloom arrives stamped on the damage event it
    amplifies (Amendment C to D-07).  Same field, because a paired half
    still has to name the delivery its pair half is paired against; a
    different type, because only a *packet* can modify another
    participant's damage and the producer derivation reads the difference.

    ``holder_stacking`` is the one argument with no default at all, because
    it is the one whose majority answer would be a guess.  "Does a second
    holder arm a second modifier?" has no majority — it has a per-mechanic
    answer, and D-66 exists because a flat key silently drops one of them —
    so every row states it, ``None`` included, and adding this field is what
    forced every declaration below to be revisited rather than inherit one.
    """
    return MechanicCapability(
        mechanic=mechanic,
        owner=ItemOwner(item),
        engine=Engine.WALK,
        reads=reads,
        needs=needs,
        authority=authority,
        pairing=pairing,
        pair_of=pair_of,
        divergence_ref=divergence_ref,
        impl=impl,
        packet_source=packet_source,
        view_tags=MappingProxyType({Engine.WALK: view_tag}),
        holder_stacking=holder_stacking,
    )


def _pair_half(
    mechanic: str,
    owner: MechanicOwner,
    impl: str,
    *,
    authority: Authority,
    view_tag: ViewTag = ViewTag.APPLIED,
) -> MechanicCapability:
    """One pair-engine half — the target of a walk half's ``pair_of``.

    A pair half reads no bus stream: the pair engine walks its own ordered
    breakdown rather than the authored row ledger, so its ``reads`` is empty
    by construction and not by omission.  Its ``holder_stacking`` is ``None``
    for the same kind of reason: arming is a walk-side act, a pair half arms
    nothing, and the validator refuses a pair row that claims otherwise — so
    the constructor encodes a structural fact rather than supplying a
    default nobody looked at.
    """
    return MechanicCapability(
        mechanic=mechanic,
        owner=owner,
        engine=Engine.PAIR,
        reads=frozenset(),
        needs=frozenset(),
        authority=authority,
        pairing=Pairing.SOLO,
        pair_of=None,
        divergence_ref=None,
        impl=impl,
        packet_source=None,
        view_tags=MappingProxyType({Engine.PAIR: view_tag}),
        holder_stacking=None,
    )


#: How a retired family's pair half is named: the rule's own mechanic id with
#: this suffix.  One spelling, so the walk half can carry the catalog's id
#: verbatim — which is what ``damage``'s ``pair_preview_of`` stamp reads off
#: the declaration — and the preview it pairs against is derived rather than
#: typed twice.
PREVIEW_SUFFIX = "_preview"


class RetiredFamilyMechanic(NamedTuple):
    """One mechanic of a family whose numbers the coupled walk now prices.

    ``mechanic`` is the catalog's own rule id, because the pair engine stamps
    its row with exactly that (``pair_preview_of``) and a second spelling
    here would be the join failing silently.  It is also what the
    :class:`HolderPacket` names, and that is not redundancy: the walk reads a
    re-priced packet through the ``AuthoredDeclaration`` riding it, whose
    ``rule_id`` is this string, so the delivery reference is the identifier
    the number actually arrives under rather than a second one invented for
    the table.  ``pair_impl`` is the engine function that authors the row the
    declaration rides.
    """

    mechanic: str
    item: str
    pair_impl: str


def _retired_family_halves(
    mechanics: tuple[RetiredFamilyMechanic, ...],
) -> tuple[MechanicCapability, ...]:
    """Both declared halves of every mechanic of one retired family.

    A retirement act is one slice carrying both halves at once (umbrella
    Amendment L, Ruling 1): the pair engine's row becomes a
    ``ViewTag.THEORETICAL`` preview and the coupled walk prices the family's
    own declaration.  Either half alone is worse than neither — the walk
    without the stamp prices the family twice into one roster total, the
    stamp without the walk deletes the family's number from every total that
    held it — so the two are generated from one row rather than written
    apart, and a mechanic cannot acquire one of them by itself.

    The walk half is a :class:`HolderPacket`: it prices the damage of the
    participant holding the item, so no second participant's number moves
    when it resolves and the mechanic is **not** a cross-participant producer
    (umbrella Amendment M, Ruling 3).  ``PER_HOLDER`` is the arming answer
    for the same reason — two roster members holding one item each pay their
    own packet, and an aura key would silently drop the second (D-66).

    ``impl`` on the walk half is the one pricing site every such half shares,
    which is the property the retirement discharges: the family's numbers
    reach the walk through exactly one interpreter, in the lane it declares
    (umbrella Amendment K).  Its pair half's ``impl`` is the engine function
    that authors the previewed row, so the two ends of the join are both
    resolvable against source.
    """
    halves: list[MechanicCapability] = []
    for entry in mechanics:
        preview = f"{entry.mechanic}{PREVIEW_SUFFIX}"
        halves.append(
            _pair_half(
                preview,
                ItemOwner(entry.item),
                entry.pair_impl,
                authority=Authority.COUPLED_AUTHORITATIVE_WITH_PAIR_PREVIEW,
                view_tag=ViewTag.THEORETICAL,
            )
        )
        halves.append(
            _walk_item(
                entry.mechanic,
                entry.item,
                HolderPacket(entry.mechanic),
                holder_stacking=HolderStacking.PER_HOLDER,
                authority=Authority.COUPLED_AUTHORITATIVE_WITH_PAIR_PREVIEW,
                pairing=Pairing.PAIRED,
                pair_of=preview,
                impl=_DECLARED_PRICE_IMPL,
            )
        )
    return tuple(halves)


# The six item actives, retired off the pair engine 2026-08-16.  One row per
# declared rule in ``item_behavior_catalog``'s ``active_cast`` family: the
# walk prices each from its own declaration and the pair engine's row is the
# honest single-attacker preview of it.
_ACTIVE_CAST_RETIREMENT: tuple[RetiredFamilyMechanic, ...] = tuple(
    RetiredFamilyMechanic(f"{slug}.active", item, "damage._add_item_active_damage")
    for slug, item in (
        ("hextech_gunblade", "Hextech Gunblade"),
        ("hextech_rocketbelt", "Hextech Rocketbelt"),
        ("profane_hydra", "Profane Hydra"),
        ("ravenous_hydra", "Ravenous Hydra"),
        ("stridebreaker", "Stridebreaker"),
        ("tiamat", "Tiamat"),
    )
)


# The eight cast-triggered procs, retired off the pair engine 2026-08-16.  One
# row per declared rule in ``item_behavior_catalog``'s ``cast_proc`` family.
# Both proc shapes author their rows in one engine function, so both name it:
# a cooldown proc's row and an ultimate proc's differ in how their events are
# timed and not in who writes them.
_CAST_PROC_RETIREMENT: tuple[RetiredFamilyMechanic, ...] = tuple(
    RetiredFamilyMechanic(mechanic, item, "damage._add_item_proc_damage")
    for mechanic, item in (
        ("eclipse.proc", "Eclipse"),
        ("hextech_alternator.proc", "Hextech Alternator"),
        ("ludens_echo.proc", "Luden's Echo"),
        ("malignance.ultimate_proc", "Malignance"),
        ("scouts_slingshot.proc", "Scout's Slingshot"),
        ("stormsurge.proc", "Stormsurge"),
        ("zazzaks_realmspike.proc", "Zaz'Zak's Realmspike"),
        ("zekes_convergence.ultimate_proc", "Zeke's Convergence"),
    )
)


# The eleven damaging charged strikes, retired off the pair engine
# 2026-08-16.  One row per declared rule in ``item_behavior_catalog``'s
# ``charged_strike`` family that authors a damage row, and the engine
# function that authors it: this family's rows come from five sites rather
# than one, because a charge is spent by an attack, by an ability, by an
# ultimate's empowered run or by every Nth on-hit application, and each of
# those is timed by a different part of the engine.
#
# The two ``swing_rate`` schedules are deliberately not here and are declared
# as ordinary applied pair halves below: a schedule authors no packet — it
# changes how often the holder swings — so there is no row to preview and no
# declaration for a walk to price.
_CHARGED_STRIKE_RETIREMENT: tuple[RetiredFamilyMechanic, ...] = tuple(
    RetiredFamilyMechanic(mechanic, item, pair_impl)
    for mechanic, item, pair_impl in (
        (
            "bastionbreaker.shaped_charge",
            "Bastionbreaker",
            "damage._add_shaped_charge_damage",
        ),
        (
            "dead_mans_plate.empowered_hit",
            "Dead Man's Plate",
            "damage._add_single_proc_on_hits",
        ),
        (
            "fiendhunter_bolts.empowered_autos",
            "Fiendhunter Bolts",
            "damage._simulate_auto_attacks",
        ),
        ("heartsteel.empowered_hit", "Heartsteel", "damage._add_single_proc_on_hits"),
        (
            "hullbreaker.repeating_strike",
            "Hullbreaker",
            "damage._add_single_proc_on_hits",
        ),
        (
            "kraken_slayer.repeating_strike",
            "Kraken Slayer",
            "damage._add_single_proc_on_hits",
        ),
        (
            "rapid_firecannon.empowered_hit",
            "Rapid Firecannon",
            "damage._add_single_proc_on_hits",
        ),
        (
            "statikk_shiv.empowered_hit",
            "Statikk Shiv",
            "damage._add_single_proc_on_hits",
        ),
        ("stormrazor.empowered_hit", "Stormrazor", "damage._add_single_proc_on_hits"),
        (
            "umbral_glaive.empowered_hit",
            "Umbral Glaive",
            "damage._add_single_proc_on_hits",
        ),
        (
            "voltaic_cyclosword.empowered_hit",
            "Voltaic Cyclosword",
            "damage._author_energized_ability_proc",
        ),
    )
)


# The eight on-hit strikes, retired off the pair engine 2026-08-16.  One row
# per declared rule in ``item_behavior_catalog``'s ``on_hit_strike`` family,
# and one authoring site for all of them: ``damage._layer_on_hit_effects``
# lays every declared strike onto the applications of the fight's swings,
# whether the strike's magnitude is fixed per application or re-read against
# the target's falling health.
#
# Three rows the committed triage lists for this family are deliberately
# absent, because no declaration of this family authors them: Titanic
# Crescent (``active_Titanic Hydra``) and Muramana's Shock on abilities
# (``muramana_ability``) are compiled out of the number registry rather than
# out of a rule, and ``on_hit_secondary_Runaan's Hurricane`` belongs to the
# ``secondary_target`` family, whose deferral still stands.  The triage
# measures a family's rows by removing the ITEM, which is conservative by
# construction and lists every mechanic that item holds.
_ON_HIT_STRIKE_RETIREMENT: tuple[RetiredFamilyMechanic, ...] = tuple(
    RetiredFamilyMechanic(f"{slug}.on_hit", item, "damage._layer_on_hit_effects")
    for slug, item in (
        ("blade_of_the_ruined_king", "Blade of the Ruined King"),
        ("guinsoos_rageblade", "Guinsoo's Rageblade"),
        ("muramana", "Muramana"),
        ("nashors_tooth", "Nashor's Tooth"),
        ("recurve_bow", "Recurve Bow"),
        ("terminus", "Terminus"),
        ("titanic_hydra", "Titanic Hydra"),
        ("wits_end", "Wit's End"),
    )
)


# The seven periodic strikes, retired off the pair engine 2026-08-16.  One row
# per declared rule in ``item_behavior_catalog``'s ``periodic`` family, and
# one authoring site for all three of its cadences: ``damage._add_burn_damage``
# prices a refreshed burn over the window the fight's casts stretched it to,
# an aura as a rate times the fight, and a fixed-interval strike as one packet
# per completed interval, and splits each aggregate into the ticks that carry
# the declaration's share.
#
# ``damage_amp_Liandry's Torment`` is deliberately not previewed here: the
# triage lists it because it ablates the ITEM, and the row belongs to
# ``liandrys_torment.whole_total_amp``, family ``delta_amp``, which retired on
# its own terms.  Liandry's Torment declares two rules in two families and
# only the burn is this one's.
_PERIODIC_RETIREMENT: tuple[RetiredFamilyMechanic, ...] = tuple(
    RetiredFamilyMechanic(mechanic, item, "damage._add_burn_damage")
    for mechanic, item in (
        ("bamis_cinder.continuous_aura", "Bami's Cinder"),
        ("blackfire_torch.refreshed_burn", "Blackfire Torch"),
        ("fated_ashes.refreshed_burn", "Fated Ashes"),
        ("hollow_radiance.continuous_aura", "Hollow Radiance"),
        ("liandrys_torment.refreshed_burn", "Liandry's Torment"),
        ("sunfire_aegis.continuous_aura", "Sunfire Aegis"),
        ("unending_despair.fixed_interval", "Unending Despair"),
    )
)


# The seven spellblades, retired off the pair engine 2026-08-17.  One row per
# declared rule in ``item_behavior_catalog``'s ``spellblade`` family, and one
# authoring site for all of them: ``damage._add_spellblade_damage`` prices the
# one spellblade a build arms — the mechanics are mutually exclusive in game
# and the engine arms the first the build carries — and lays its procs onto
# the weave schedule the fight's casts resolved.
#
# Two rows the committed triage lists for this family are deliberately absent,
# because no declaration of this family authors them.  ``expose_weakness_Bloodsong``
# is ``bloodsong.expose_weakness``, family ``ally_packet``, already a declared
# ``THEORETICAL`` preview under Phase 4 S7's authority move; the triage lists it
# because it measures a family's rows by removing the ITEM, which is
# conservative by construction and lists every mechanic that item holds.  And
# ``spellblade_<item>_true`` is the Camille Q2 conversion row, whose per-proc
# figure blends a true share against a mitigated one under a ratio a CHAMPION
# ability declares: one declaration cannot state two damage classes, and
# stamping it would file a champion's number under an item mechanic.
_SPELLBLADE_RETIREMENT: tuple[RetiredFamilyMechanic, ...] = tuple(
    RetiredFamilyMechanic(f"{slug}.spellblade", item, "damage._add_spellblade_damage")
    for slug, item in (
        ("bloodsong", "Bloodsong"),
        ("dusk_and_dawn", "Dusk and Dawn"),
        ("essence_reaver", "Essence Reaver"),
        ("iceborn_gauntlet", "Iceborn Gauntlet"),
        ("lich_bane", "Lich Bane"),
        ("sheen", "Sheen"),
        ("trinity_force", "Trinity Force"),
    )
)


# Wind's Fury, retired off the pair engine 2026-08-17 — the last of umbrella
# Amendment F's fourteen.  One row, because one declared rule in
# ``item_behavior_catalog``'s ``secondary_target`` family is the whole family,
# and one authoring site: ``damage._add_single_proc_on_hits`` authors both the
# bolt and the copied on-hit row inside one block.
#
# ONE STAMP, TWO ROWS, TWO PRODUCERS.  The pair half this generates previews
# both rows, because both are rows this family authors and neither survives
# into a roster total.  What differs is who declares the MAGNITUDE under each:
# the bolt is the router's own packet, so its declaration names the mechanic
# below, while the copied on-hit row re-delivers the source families' packets
# and each of its declarations names the mechanic that declared it, with the
# routing recorded as provenance (umbrella Amendment R, Ruling 3).  The walk
# half's ``HolderPacket`` names this mechanic either way: it is the delivery
# reference for the packets this family hands the walk, not a claim about who
# declared their sizes.
_SECONDARY_TARGET_RETIREMENT: tuple[RetiredFamilyMechanic, ...] = (
    RetiredFamilyMechanic(
        "runaans_hurricane.secondary_target",
        "Runaan's Hurricane",
        "damage._add_single_proc_on_hits",
    ),
)


_DECLARATIONS: tuple[MechanicCapability, ...] = (
    # -- walk packets compiled by ``derive_item_support_effects`` ------------
    _walk_item("cull.reap", "Cull", "Cull — Reap", holder_stacking=None),
    _walk_item(
        "phage.rage",
        "Phage",
        "Phage — Rage",
        holder_stacking=None,
        reads=frozenset({Stream.DAMAGE}),
        needs=frozenset({Field.TIME, Field.SOURCE_KEY, Field.BASIC_ATTACK}),
    ),
    _walk_item(
        "world_atlas.shared_riches",
        "World Atlas",
        "World Atlas — Shared Riches",
        holder_stacking=None,
    ),
    _walk_item(
        "world_atlas.ward", "World Atlas", "World Atlas — Ward", holder_stacking=None
    ),
    _walk_item(
        "runic_compass.shared_riches",
        "Runic Compass",
        "Runic Compass — Shared Riches",
        holder_stacking=None,
    ),
    _walk_item(
        "runic_compass.ward",
        "Runic Compass",
        "Runic Compass — Ward",
        holder_stacking=None,
    ),
    _walk_item(
        "fimbulwinter.everlasting",
        "Fimbulwinter",
        "Fimbulwinter — Everlasting",
        holder_stacking=None,
        reads=frozenset({Stream.CC}),
        needs=frozenset(
            {
                Field.TIME,
                Field.EVENT_ID,
                Field.SOURCE_KEY,
                Field.ABILITY_INSTANCE,
                Field.CC,
            }
        ),
    ),
    _walk_item(
        "abyssal_mask.unmake",
        "Abyssal Mask",
        "Abyssal Mask — Unmake",
        holder_stacking=HolderStacking.IDEMPOTENT_AURA,
        authority=Authority.SPLIT,
        pairing=Pairing.PAIRED,
        pair_of="abyssal_mask.magic_amp",
    ),
    # Phase 4 S7's third authority move, and the one that retires the
    # campaign's only ``DivergenceReceipt``.  The amplified pool is every
    # attacker's damage inside a live window, which is a roster input, so the
    # walk owns the mechanic outright and prices the holder's own packets
    # too — there is no longer a pair-local half to skip, which is why this
    # row carries no ``owner``.  The pair engine's row survives as a declared
    # ``THEORETICAL`` preview: correct as a one-attacker figure, excluded from
    # every roster total.
    _walk_item(
        "bloodsong.expose_weakness",
        "Bloodsong",
        "Bloodsong — Expose Weakness",
        holder_stacking=HolderStacking.PER_HOLDER,
        reads=frozenset({Stream.DAMAGE}),
        needs=frozenset(
            {Field.TIME, Field.TARGET_ID, Field.EVENT_ID, Field.SOURCE_KEY}
        ),
        authority=Authority.COUPLED_AUTHORITATIVE_WITH_PAIR_PREVIEW,
        pairing=Pairing.PAIRED,
        pair_of="bloodsong.expose_weakness_preview",
    ),
    # Phase 4 S7's fourth authority move, and the last of the four that land.
    # Cinderbloom's predicate reads the target's health *at the instant of
    # the hit*, under a whole roster's fire — a roster input, so the walk is
    # the smallest engine that can see every input the rule reads and it owns
    # the mechanic.  The pair engine's lump-sum row is what one attacker
    # alone would have earned against a full-health target, which is a real
    # answer to a different question, so it survives as a ``THEORETICAL``
    # preview and is dropped from every roster total.
    #
    # This is the one walk half that authors **no packet**.  The bonus is a
    # rider on its own triggering damage event, read before absorption, and a
    # rider dies with its host: a spell-shielded, state-blocked or post-death
    # trigger emits none without anything having to cancel one.  So its
    # delivery reference is a ``RiderDelivery`` stamp (Amendment C to D-07),
    # and because a rider amplifies the event it rides — its holder's own —
    # it modifies no other participant's damage and joins no cross-participant
    # producer set.
    #
    # ``PER_HOLDER`` for a mechanic that arms nothing is the honest reading
    # rather than a formality: two Shadowflame holders each amplify their own
    # packets, so their contributions can never be the same one counted
    # twice, and that is exactly what the declaration says.  ``reads`` is
    # empty because the rider consumes no authored row ledger — it consumes
    # the walk's own live pools, which no bus stream carries.
    _walk_item(
        "shadowflame.cinderbloom",
        "Shadowflame",
        RiderDelivery("shadowflame.cinderbloom"),
        holder_stacking=HolderStacking.PER_HOLDER,
        authority=Authority.COUPLED_AUTHORITATIVE_WITH_PAIR_PREVIEW,
        pairing=Pairing.PAIRED,
        pair_of="shadowflame.cinderbloom_preview",
        impl="survival.transitions._apply_live_amp",
    ),
    # H1 — Carve's move to coupled-authoritative-with-preview is human-owned
    # and unanswered, so this row states the blocking id instead of a guessed
    # ruling: the stack ledger is a roster fact, but re-tuning the pair
    # engine's Cesàro approximation is a documented balance change
    # (docs/math-foundations.md §2.3).  ``PER_HOLDER`` is not a fall-through
    # here — two Black Cleaver holders each build their own stack ledger.
    _walk_item(
        "black_cleaver.carve",
        "Black Cleaver",
        "Black Cleaver — Carve",
        holder_stacking=HolderStacking.PER_HOLDER,
        reads=frozenset({Stream.DAMAGE}),
        needs=frozenset(
            {
                Field.TIME,
                Field.TARGET_ID,
                Field.EVENT_ID,
                Field.DAMAGE,
                Field.DAMAGE_TYPE,
            }
        ),
        authority=Authority.SPLIT,
        pairing=Pairing.PAIRED,
        pair_of="black_cleaver.armor_reduction",
    ),
    # H1 — Vile Decay is Carve's shape, magic- and ability-gated, and is
    # blocked by the same unanswered human decision.
    _walk_item(
        "bloodletters_curse.vile_decay",
        "Bloodletter's Curse",
        "Bloodletter's Curse — Vile Decay",
        holder_stacking=HolderStacking.PER_HOLDER,
        reads=frozenset({Stream.DAMAGE}),
        needs=frozenset(
            {
                Field.TIME,
                Field.TARGET_ID,
                Field.EVENT_ID,
                Field.DAMAGE,
                Field.DAMAGE_TYPE,
                Field.IS_ABILITY,
            }
        ),
        authority=Authority.SPLIT,
        pairing=Pairing.PAIRED,
        pair_of="bloodletters_curse.mr_reduction",
    ),
    _walk_item(
        "cryptbloom.life_from_death",
        "Cryptbloom",
        "Cryptbloom — Life From Death",
        holder_stacking=None,
        reads=frozenset({Stream.TAKEDOWN}),
        needs=frozenset({Field.TIME, Field.TARGET_ID}),
    ),
    _walk_item(
        "ardent_censer.sanctify",
        "Ardent Censer",
        "Ardent Censer — Sanctify",
        holder_stacking=None,
        reads=frozenset({Stream.SUPPORT_TRIGGER}),
    ),
    _walk_item(
        "staff_of_flowing_water.rapids",
        "Staff of Flowing Water",
        "Staff of Flowing Water — Rapids",
        holder_stacking=None,
        reads=frozenset({Stream.SUPPORT_TRIGGER}),
    ),
    _walk_item(
        "moonstone_renewer.starlit_grace",
        "Moonstone Renewer",
        "Moonstone Renewer — Starlit Grace",
        holder_stacking=None,
        reads=frozenset({Stream.SUPPORT_TRIGGER}),
    ),
    # The sixth cross-participant producer, and the one with no pair-side
    # pricer at all: Blue Dream Bubble shields an *ally* against the next hit
    # from anyone, so there is no pair-local half to skip (umbrella,
    # semantic authority).
    _walk_item(
        "dream_maker.blue_bubble",
        "Dream Maker",
        "Dream Maker — Blue Dream Bubble",
        holder_stacking=None,
        reads=frozenset({Stream.SUPPORT_TRIGGER}),
        authority=Authority.COUPLED_ONLY,
    ),
    _walk_item(
        "dream_maker.purple_bubble",
        "Dream Maker",
        "Dream Maker — Purple Dream Bubble",
        holder_stacking=None,
        reads=frozenset({Stream.SUPPORT_TRIGGER}),
    ),
    _walk_item(
        "echoes_of_helia.soul_siphon",
        "Echoes of Helia",
        "Echoes of Helia — Soul Siphon",
        holder_stacking=None,
        reads=frozenset({Stream.SUPPORT_TRIGGER, Stream.DAMAGE}),
        needs=frozenset({Field.DAMAGE, Field.RAW_DAMAGE}),
    ),
    _walk_item(
        "diadem_of_songs.consonance",
        "Diadem of Songs",
        "Diadem of Songs — Consonance",
        holder_stacking=None,
        reads=frozenset({Stream.SUPPORT_TRIGGER}),
    ),
    _walk_item(
        "bandlepipes.fanfare",
        "Bandlepipes",
        "Bandlepipes — Fanfare",
        holder_stacking=None,
        reads=frozenset({Stream.CC}),
        needs=frozenset({Field.TIME}),
    ),
    # Solstice Sleigh is tuple-incapable by declaration (D-02): its branch is
    # nested inside the cc loop, and its only protection today is a cached
    # ``healthRegen.percent`` coincidence.
    _walk_item(
        "solstice_sleigh.going_sledding",
        "Solstice Sleigh",
        "Solstice Sleigh — Going Sledding",
        holder_stacking=None,
        reads=frozenset({Stream.CC}),
        needs=frozenset({Field.TIME}),
    ),
    # H2 — Command's authority move waits on a sourced ``CcScope`` reading for
    # Syndra E, and the umbrella records the disposition as *deferred, default
    # shipped*.  So this row keeps ``SPLIT`` and states the blocking id, and
    # its ``PER_HOLDER`` is the written fail-closed value D-66 requires rather
    # than an absence: two Imperial Mandate holders each pay their own pool,
    # and a flat aura key would silently drop the second — the incident's own
    # shape mandated by a rule.
    _walk_item(
        "imperial_mandate.command",
        "Imperial Mandate",
        "Imperial Mandate — Command",
        holder_stacking=HolderStacking.PER_HOLDER,
        reads=frozenset({Stream.CC}),
        needs=frozenset({Field.TIME, Field.TARGET_ID, Field.CC}),
        authority=Authority.SPLIT,
        pairing=Pairing.PAIRED,
        pair_of="imperial_mandate.command_preview",
    ),
    _walk_item(
        "locket_of_the_iron_solari.devotion",
        "Locket of the Iron Solari",
        "Locket of the Iron Solari — Devotion",
        holder_stacking=None,
    ),
    _walk_item(
        "mikaels_blessing.purify",
        "Mikael's Blessing",
        "Mikael's Blessing — Purify",
        holder_stacking=None,
    ),
    _walk_item(
        "redemption.intervention",
        "Redemption",
        "Redemption — Intervention",
        holder_stacking=None,
    ),
    _walk_item(
        "shurelyas_battlesong.inspiring_speech",
        "Shurelya's Battlesong",
        "Shurelya's Battlesong — Inspiring Speech",
        holder_stacking=None,
    ),
    _walk_item(
        "stridebreaker.breaking_shockwave",
        "Stridebreaker",
        "Stridebreaker — Breaking Shockwave",
        holder_stacking=None,
    ),
    # -- the second walk packet compiler ------------------------------------
    _walk_item(
        "knights_vow.sacrifice",
        "Knight's Vow",
        "Knight's Vow — Sacrifice",
        holder_stacking=None,
        impl=_KNIGHTS_VOW_IMPL,
    ),
    # -- retired families: both halves of one packet ------------------------
    *_retired_family_halves(_ACTIVE_CAST_RETIREMENT),
    *_retired_family_halves(_CAST_PROC_RETIREMENT),
    *_retired_family_halves(_CHARGED_STRIKE_RETIREMENT),
    *_retired_family_halves(_ON_HIT_STRIKE_RETIREMENT),
    *_retired_family_halves(_PERIODIC_RETIREMENT),
    *_retired_family_halves(_SECONDARY_TARGET_RETIREMENT),
    *_retired_family_halves(_SPELLBLADE_RETIREMENT),
    # -- the retired ``damage_routing`` family: three riders, no packet -----
    #
    # The fifth family to retire off the pair engine (2026-08-16) and the
    # first whose walk half is not a price.  Umbrella Amendment P names its
    # delivery as the program rider system and the kernel state paths already
    # in the tree — a deferral moves damage in time, an execution ends a
    # fight, and a venom resizes a barrier — so each of these three is
    # ``RiderDelivery``-delivered, which Amendment C ruled legal for a walk
    # half whose number rides an event somebody else authored and which
    # carries no ``packet_source`` at all.  A rider amplifies the event it
    # rides, so none of the three is a cross-participant producer and D-07's
    # ruled six do not move (Amendment M, Ruling 3, from the other delivery
    # shape).
    #
    # ``SOLO`` and ``holder_stacking=None`` are measured rather than assumed:
    # the triage found this family authoring no priced pair-engine row
    # anywhere in its covering population, so there is no pair half for these
    # to be ``PAIRED`` against and nothing for a preview stamp to prevent.
    # That is the enumerated emptiness Amendment L, Ruling 1's first half is
    # discharged by here, exactly as ``delta_amp``'s was — never a step
    # skipped, which is why the rows are written out one by one instead of
    # being absent.
    #
    # ``COUPLED_AUTHORITATIVE`` for all three, by the campaign's own authority
    # rule: every one of them reads an input the pair engine cannot see.  The
    # execution reads the target's live health under combined fire, the venom
    # reads the shields that target gains from any granter on the roster, and
    # the deferral reads the holder's incoming damage from every roster
    # attacker at once.
    _walk_item(
        "deaths_dance.ignore_pain",
        "Death's Dance",
        RiderDelivery("deaths_dance.ignore_pain"),
        holder_stacking=None,
        authority=Authority.COUPLED_AUTHORITATIVE,
        impl="participant_timeline._simulate_survival",
    ),
    _walk_item(
        "the_collector.execute",
        "The Collector",
        RiderDelivery("the_collector.execute"),
        holder_stacking=None,
        authority=Authority.COUPLED_AUTHORITATIVE,
        impl="participant_timeline._simulate_survival",
    ),
    _walk_item(
        "serpents_fang.shield_bypass",
        "Serpent's Fang",
        RiderDelivery("serpents_fang.shield_bypass"),
        holder_stacking=None,
        authority=Authority.COUPLED_AUTHORITATIVE,
        impl="participant_timeline._simulate_survival",
    ),
    # -- pair-engine halves -------------------------------------------------
    # The two swing schedules of the retired ``charged_strike`` family.  They
    # sit here rather than among the retirement's paired halves because they
    # author no packet: a schedule decides how often the holder swings, the
    # pair engine applies it while building the swing stream that every later
    # site reads, and nothing about it is a preview of a number the coupled
    # walk owns.  ``APPLIED`` is that measured, and ``PAIR_ONLY`` says the
    # schedule is a pair-local fact rather than one a second engine sees.
    _pair_half(
        "guinsoos_rageblade.swing_rate",
        ItemOwner("Guinsoo's Rageblade"),
        "damage._auto_attack_timestamps",
        authority=Authority.PAIR_ONLY,
        view_tag=ViewTag.APPLIED,
    ),
    _pair_half(
        "yun_tal_wildarrows.swing_rate",
        ItemOwner("Yun Tal Wildarrows"),
        "damage._auto_attack_timestamps",
        authority=Authority.PAIR_ONLY,
        view_tag=ViewTag.APPLIED,
    ),
    _pair_half(
        "abyssal_mask.magic_amp",
        ItemOwner("Abyssal Mask"),
        "damage._mitigate",
        authority=Authority.SPLIT,
    ),
    _pair_half(
        "bloodsong.expose_weakness_preview",
        ItemOwner("Bloodsong"),
        "damage._add_expose_weakness",
        authority=Authority.COUPLED_AUTHORITATIVE_WITH_PAIR_PREVIEW,
        view_tag=ViewTag.THEORETICAL,
    ),
    _pair_half(
        "black_cleaver.armor_reduction",
        ItemOwner("Black Cleaver"),
        "damage._resolve_combat_state",
        authority=Authority.SPLIT,
    ),
    _pair_half(
        "bloodletters_curse.mr_reduction",
        ItemOwner("Bloodletter's Curse"),
        "damage._resolve_combat_state",
        authority=Authority.SPLIT,
    ),
    _pair_half(
        "imperial_mandate.command_preview",
        ItemOwner("Imperial Mandate"),
        "damage._apply_command_amp",
        authority=Authority.SPLIT,
    ),
    # -- pair-only mechanics the umbrella's authority table rules ------------
    # Hypershot is Phase 4 S7's canary: the first of the seven authority moves
    # and the one that is expected to move nothing.  Its exclusion set — which
    # abilities in a rotation the amp declines to reach — is a pair-local
    # rotation fact, so ``PAIR_ONLY`` is the answer the authority rule gives
    # and its number is what the one pair fight delivered, not a preview of a
    # coupled one.  A canary that moved a number would mean the two new
    # capability fields had a live consumer nobody declared.
    _pair_half(
        "horizon_focus.hypershot",
        ItemOwner("Horizon Focus"),
        "damage._apply_damage_amplifiers",
        authority=Authority.PAIR_ONLY,
        view_tag=ViewTag.APPLIED,
    ),
    _pair_half(
        "shadowflame.cinderbloom_preview",
        ItemOwner("Shadowflame"),
        "damage._add_shadowflame_cinderbloom",
        authority=Authority.COUPLED_AUTHORITATIVE_WITH_PAIR_PREVIEW,
        view_tag=ViewTag.THEORETICAL,
    ),
    # Axiom Arc's takedown is a scenario state receipt and Defy is live state
    # inside the walk, so neither reads the takedown stream.  Both are
    # declared with ``reads=frozenset()`` precisely so nobody unifies them
    # onto the bus by accident (D-31).
    _pair_half(
        "axiom_arc.flux",
        ItemOwner("Axiom Arc"),
        "item_effects.axiom_arc_ultimate_refund_fraction",
        authority=Authority.PAIR_ONLY,
    ),
    MechanicCapability(
        mechanic="deaths_dance.defy",
        owner=ItemOwner("Death's Dance"),
        engine=Engine.WALK,
        reads=frozenset(),
        needs=frozenset(),
        authority=Authority.COUPLED_AUTHORITATIVE,
        pairing=Pairing.SOLO,
        pair_of=None,
        divergence_ref=None,
        impl="survival.transitions.trigger_defy",
        packet_source=None,
        view_tags=MappingProxyType({Engine.WALK: ViewTag.APPLIED}),
        holder_stacking=None,
    ),
    # Steadfast's stack ledger keys on any roster attacker's magic damage and
    # CC, which is a roster input: the coupled walk owns it outright.  It
    # reads no bus stream — ``update_combat_state`` consumes the walk's own
    # ordered actions, not the pair result's authored rows.
    MechanicCapability(
        mechanic="force_of_nature.steadfast",
        owner=ItemOwner("Force of Nature"),
        engine=Engine.WALK,
        reads=frozenset(),
        needs=frozenset(),
        authority=Authority.COUPLED_AUTHORITATIVE,
        pairing=Pairing.SOLO,
        pair_of=None,
        divergence_ref=None,
        impl="survival.transitions.update_combat_state",
        packet_source=None,
        view_tags=MappingProxyType({Engine.WALK: ViewTag.APPLIED}),
        holder_stacking=None,
    ),
    # -- non-item owners (D-36) ---------------------------------------------
    *(
        MechanicCapability(
            mechanic=f"{slug}.rune",
            owner=RuneOwner(rune),
            engine=Engine.PAIR,
            reads=frozenset(),
            needs=frozenset(),
            authority=Authority.PAIR_ONLY,
            pairing=Pairing.SOLO,
            pair_of=None,
            divergence_ref=None,
            impl="rune_effects.resolve_rune",
            packet_source=None,
            view_tags=MappingProxyType({Engine.PAIR: ViewTag.APPLIED}),
            holder_stacking=None,
        )
        # Every rune ``rune_effects`` compiles — the keystone table here and
        # each path module's ``COMPILERS`` — spelled here rather than derived
        # from them: this module is a data-free leaf (D-35) and
        # ``rune_effects`` reads ``data/runes.json`` at import. The two
        # tables are pinned equal by test_trigger_stream, which is where a
        # cache-reading join belongs.
        for slug, rune in (
            ("electrocute", "Electrocute"),
            ("first_strike", "First Strike"),
            ("press_the_attack", "Press the Attack"),
            ("arcane_comet", "Arcane Comet"),
            ("summon_aery", "Summon Aery"),
            ("hail_of_blades", "Hail of Blades"),
            ("grasp_of_the_undying", "Grasp of the Undying"),
            ("lethal_tempo", "Lethal Tempo"),
            ("deathfire_touch", "Deathfire Touch"),
            ("dark_harvest", "Dark Harvest"),
            ("conqueror", "Conqueror"),
            ("fleet_footwork", "Fleet Footwork"),
            ("aftershock", "Aftershock"),
            ("guardian", "Guardian"),
            ("glacial_augment", "Glacial Augment"),
            ("stormraiders_surge", "Stormraider's Surge"),
            ("unsealed_spellbook", "Unsealed Spellbook"),
            # -- minor runes, by path --
            ("coup_de_grace", "Coup de Grace"),
            ("absolute_focus", "Absolute Focus"),
            ("scorch", "Scorch"),
            ("cosmic_insight", "Cosmic Insight"),
            # Sorcery
            ("manaflow_band", "Manaflow Band"),
            ("nimbus_cloak", "Nimbus Cloak"),
            ("transcendence", "Transcendence"),
            ("celerity", "Celerity"),
            ("waterwalking", "Waterwalking"),
            ("gathering_storm", "Gathering Storm"),
            # Resolve
            ("demolish", "Demolish"),
            ("font_of_life", "Font of Life"),
            ("shield_bash", "Shield Bash"),
            ("conditioning", "Conditioning"),
            ("second_wind", "Second Wind"),
            ("bone_plating", "Bone Plating"),
            ("overgrowth", "Overgrowth"),
            ("revitalize", "Revitalize"),
            ("unflinching", "Unflinching"),
            # Inspiration
            ("hextech_flashtraption", "Hextech Flashtraption"),
            ("magical_footwear", "Magical Footwear"),
            ("cash_back", "Cash Back"),
            ("triple_tonic", "Triple Tonic"),
            ("time_warp_tonic", "Time Warp Tonic"),
            ("biscuit_delivery", "Biscuit Delivery"),
            ("approach_velocity", "Approach Velocity"),
            ("jack_of_all_trades", "Jack Of All Trades"),
        )
    ),
    *(
        MechanicCapability(
            mechanic=f"{champion.lower()}_{slot.lower()}.grievous_wounds",
            owner=ChampionSlotOwner(champion, slot),
            engine=Engine.WALK,
            reads=frozenset(),
            needs=frozenset(),
            authority=Authority.COUPLED_AUTHORITATIVE,
            pairing=Pairing.SOLO,
            pair_of=None,
            divergence_ref=None,
            impl="healing_reduction.champion_grievous_wound_sources",
            packet_source=None,
            view_tags=MappingProxyType({Engine.WALK: ViewTag.APPLIED}),
            holder_stacking=None,
        )
        for champion, slot in (("Katarina", "R"), ("Varus", "E"))
    ),
    MechanicCapability(
        mechanic="support_effects.ally_packets",
        owner=EngineOwner("support_effects.derive_ally_effects"),
        engine=Engine.WALK,
        reads=frozenset(),
        needs=frozenset(),
        authority=Authority.COUPLED_AUTHORITATIVE,
        pairing=Pairing.SOLO,
        pair_of=None,
        divergence_ref=None,
        impl="support_effects.derive_ally_effects",
        packet_source=None,
        view_tags=MappingProxyType({Engine.WALK: ViewTag.APPLIED}),
        holder_stacking=None,
    ),
    MechanicCapability(
        mechanic="participant_timeline.ally_heal_clone",
        owner=EngineOwner("participant_timeline.ally_heal_clone"),
        engine=Engine.WALK,
        reads=frozenset(),
        needs=frozenset(),
        authority=Authority.COUPLED_AUTHORITATIVE,
        pairing=Pairing.SOLO,
        pair_of=None,
        divergence_ref=None,
        impl="participant_timeline.build_participant_timeline",
        packet_source=None,
        view_tags=MappingProxyType({Engine.WALK: ViewTag.APPLIED}),
        holder_stacking=None,
    ),
    MechanicCapability(
        mechanic="ally_effects.stat_grants",
        owner=EngineOwner("ally_effects.AllyStatEffect"),
        engine=Engine.PAIR,
        reads=frozenset(),
        needs=frozenset(),
        authority=Authority.PAIR_ONLY,
        pairing=Pairing.SOLO,
        pair_of=None,
        divergence_ref=None,
        impl="ally_effects.resolve_ally_stat_effects",
        packet_source=None,
        view_tags=MappingProxyType({Engine.PAIR: ViewTag.APPLIED}),
        holder_stacking=None,
    ),
)


CAPABILITIES: Mapping[str, MechanicCapability] = MappingProxyType(
    {capability.mechanic: capability for capability in _DECLARATIONS}
)


def _validate_registry() -> None:
    """Structural cross-check of :data:`CAPABILITIES`, at import.

    Structural only, and no file is read (D-35): slug shape, unique ids,
    ``pair_of`` resolving to an ``Engine.PAIR`` capability, ``PAIRED``
    implying a delivery reference — a ``packet_source`` or a
    ``RiderDelivery`` — ``UNPAIRED_KNOWN_DEFECT`` implying a
    ``divergence_ref`` that resolves in :data:`DIVERGENCES`, a takedown
    reader needing a target id, and Phase 4's two fields — one view tag for
    the engine this half runs on, and a ``HolderStacking`` exactly where the
    mechanic is dual-sided.  Item-name resolution belongs to the test that
    pins the projections, because a leaf that touches ``data/`` is neither a
    leaf nor inside the caching layer (repo rule 2).
    """
    counts = Counter(capability.mechanic for capability in _DECLARATIONS)
    duplicates = sorted(name for name, count in counts.items() if count > 1)
    if duplicates:
        raise TriggerRegistryError(f"duplicate mechanic ids: {duplicates}")
    for mechanic, capability in CAPABILITIES.items():
        if not _MECHANIC_SLUG.match(mechanic):
            raise TriggerRegistryError(
                f"{mechanic!r} is not a <owner_slug>.<effect_slug> mechanic id"
            )
        if not isinstance(
            capability.owner, (ItemOwner, RuneOwner, ChampionSlotOwner, EngineOwner)
        ):
            raise TriggerRegistryError(f"{mechanic} declares no MechanicOwner")
        if not _IMPL_PATH.match(capability.impl):
            raise TriggerRegistryError(
                f"{mechanic} declares impl={capability.impl!r}, which is not a "
                "dotted path to the function implementing it"
            )
        if (
            isinstance(capability.packet_source, SELF_SCOPED_DELIVERIES)
            and not (delivery_reference(capability) or "").strip()
        ):
            raise TriggerRegistryError(
                f"{mechanic} declares a "
                f"{type(capability.packet_source).__name__} naming nothing; a "
                "delivery with an empty literal is a number no reader can "
                "trace back to the mechanic that authored it"
            )
        _validate_pairing(mechanic, capability)
        _validate_view_semantics(mechanic, capability)
        if Stream.TAKEDOWN in capability.reads and Field.TARGET_ID not in (
            capability.needs
        ):
            raise TriggerRegistryError(
                f"{mechanic} reads the takedown stream and does not need "
                "TARGET_ID; a takedown with no target cannot be attributed"
            )
        if capability.needs - _row_fields(capability.reads):
            raise TriggerRegistryError(
                f"{mechanic} needs raw-row fields "
                f"{sorted(f.value for f in capability.needs)} while declaring "
                f"reads={sorted(s.value for s in capability.reads)}; a field is "
                "only readable off a stream the mechanic declares"
            )


def _row_fields(reads: frozenset[Stream]) -> frozenset[Field]:
    """Every raw-row field the declared streams can supply.

    ``SUPPORT_TRIGGER`` contributes nothing: it carries authored ally
    templates, not engine rows, so a mechanic reading only it declares no
    ``needs``.
    """
    return frozenset(Field) if reads & RAW_STREAMS else frozenset()


def _validate_view_semantics(mechanic: str, capability: MechanicCapability) -> None:
    """Phase 4's two fields, as structural implications rather than review.

    Two rules, and each closes a way a declaration could be *shaped* like an
    answer without being one:

    * a half tags the engine it runs on, exactly once.  A tag on some other
      engine would be one half claiming what the other half's number means,
      which is how "the pair engine already priced this" became a sentence
      nobody could check;
    * ``holder_stacking`` is present exactly where the mechanic is
      dual-sided — a ``PAIRED`` walk half — and absent everywhere else.  The
      arm-time dedupe key is a question about a mechanic with a holder and a
      subject; asking it of a pair half (which arms nothing) or of a solo
      packet (which has no second holder to collide with) would be a value
      nobody reads, and a value nobody reads is a value that can be wrong.
    """
    tags = capability.view_tags
    if set(tags) != {capability.engine}:
        raise TriggerRegistryError(
            f"{mechanic} runs on {capability.engine.value} and declares "
            f"view_tags for {sorted(engine.value for engine in tags)}; a half "
            "tags the engine it runs on, exactly once, because a tag says "
            "what *this* half's numbers mean (D-62)"
        )
    if not all(isinstance(tag, ViewTag) for tag in tags.values()):
        raise TriggerRegistryError(
            f"{mechanic} declares a view tag that is not a ViewTag member"
        )
    dual_sided = capability.pairing is Pairing.PAIRED
    if dual_sided and not isinstance(capability.holder_stacking, HolderStacking):
        raise TriggerRegistryError(
            f"{mechanic} is dual-sided and declares "
            f"holder_stacking={capability.holder_stacking!r}; a mechanic two "
            "roster participants can hold has to say whether the second one "
            "arms a second modifier, and there is no default to inherit "
            "(D-66)"
        )
    if not dual_sided and capability.holder_stacking is not None:
        raise TriggerRegistryError(
            f"{mechanic} is {capability.pairing.value} and declares "
            f"holder_stacking={capability.holder_stacking.value}; only a "
            "dual-sided mechanic has an arming-dedupe question to answer"
        )


def _validate_pairing(mechanic: str, capability: MechanicCapability) -> None:
    """The three pairing implications, split out to keep the loop readable."""
    if capability.pairing is Pairing.PAIRED:
        if capability.pair_of is None:
            raise TriggerRegistryError(f"{mechanic} is PAIRED and declares no pair_of")
        partner = CAPABILITIES.get(capability.pair_of)
        if partner is None or partner.engine is not Engine.PAIR:
            raise TriggerRegistryError(
                f"{mechanic} pairs with {capability.pair_of!r}, which is not a "
                "declared Engine.PAIR capability"
            )
        if delivery_reference(capability) is None:
            raise TriggerRegistryError(
                f"{mechanic} is PAIRED and names no delivery — neither a "
                "packet_source nor a RiderDelivery; the walk half's delivery "
                "is what the pair half is paired against"
            )
    elif capability.pair_of is not None:
        raise TriggerRegistryError(
            f"{mechanic} is {capability.pairing.value} and carries "
            f"pair_of={capability.pair_of!r}"
        )
    if capability.pairing is Pairing.UNPAIRED_KNOWN_DEFECT:
        if capability.divergence_ref not in DIVERGENCES:
            raise TriggerRegistryError(
                f"{mechanic} is an unpaired known defect and its "
                f"divergence_ref {capability.divergence_ref!r} resolves in no "
                "DivergenceReceipt"
            )
    elif capability.divergence_ref is not None:
        # A paired mechanic may carry a receipt: both halves exist and the
        # reviewed fact is that they do not agree numerically.  Only SOLO is
        # nonsense — one engine cannot disagree with nobody.
        if capability.pairing is not Pairing.PAIRED:
            raise TriggerRegistryError(
                f"{mechanic} is {capability.pairing.value} and carries a "
                "divergence_ref; a disagreement needs two declared halves"
            )
        if capability.divergence_ref not in DIVERGENCES:
            raise TriggerRegistryError(
                f"{mechanic} carries divergence_ref "
                f"{capability.divergence_ref!r}, which resolves in no "
                "DivergenceReceipt"
            )


_validate_registry()


def _classify_cc(row: Mapping[str, Any]) -> tuple[CcClass, str, bool]:
    """The only place ``cc_kind`` and the legacy control flags are read.

    Returns the classification consumers branch on, the opaque receipt token
    and whether a human reviewed it.  A ``cc_kind`` that *narrows* the class —
    an immobilize kind, or ``"slow"`` — is the answer; a bare
    ``crowd_control`` flag is control that nobody narrowed, which is
    ``UNCLASSIFIED_CONTROL`` and not ``NONE``; an unmarked row is
    ``UNREVIEWED`` and never ``NONE``.

    The ladder is *strongest evidence first*, and a ``cc_kind`` is evidence
    rather than an override: a reviewed ``"none"`` does not veto a row's
    legacy ``immobilized`` / ``hard_cc`` / ``slowed`` / ``slow`` booleans, it
    simply narrows nothing.  Read that way the bus predicate is exactly the
    ``ability_spec`` predicate this module retired — which OR'd the flags in
    — on every row, which is what a phase that may not move a number owes the
    consumers it repoints.  Which fact *ought* to win on a row asserting a
    reviewed "no control" and a legacy stun at once is a semantics question,
    and this phase rules none.
    """
    kind = str(row.get("cc_kind", "") or "").lower().strip()
    if kind and kind not in CC_KIND_VOCABULARY:
        raise ValueError(
            f"cc_kind {kind!r} is not in CC_KIND_VOCABULARY "
            f"({sorted(CC_KIND_VOCABULARY)}); a misspelled kind must never "
            "author a no-op stun"
        )
    reviewed = bool(kind) or bool(row.get("cc_reviewed"))
    if kind in IMMOBILIZING_CC_KINDS or row.get("immobilized") or row.get("hard_cc"):
        return CcClass.IMMOBILIZE, kind, reviewed
    if kind == "slow" or row.get("slowed") or row.get("slow"):
        return CcClass.SLOW, kind, reviewed
    if row.get("crowd_control"):
        return CcClass.UNCLASSIFIED_CONTROL, kind, reviewed
    return (CcClass.NONE if kind else CcClass.UNREVIEWED), kind, reviewed


def _float(value: Any) -> float:
    """A row field as a finite float, with an absent/garbage field as 0.0."""
    try:
        parsed = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return parsed if math.isfinite(parsed) else 0.0


def _sequence(value: Any) -> int:
    """A row's ordinal, with an absent, missing or unparsable one as -1.

    ``0`` is a real sequence and the commonest one there is: both of
    ``damage._ordered_damage_events``' builders number their rows from
    zero, so every ledger's first row carries it.  It therefore cannot
    share a spelling with the absent marker, which is what folding the
    parse through ``... or -1`` did.
    """
    if value is None:
        return -1
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return -1
    return int(parsed) if math.isfinite(parsed) else -1


def event_triggers(
    row: Mapping[str, Any], *, kinds: frozenset[TriggerKind] = _ROW_KINDS
) -> tuple[Trigger, ...]:
    """0-2 Triggers from one authored row — a stunning damage packet is both.

    The damage trigger is unconditional for an authored row *of the kinds
    asked for*, because the consumers disagree about which damage matters
    (Phage wants basic attacks, Echoes of Helia wants every raw number, the
    stack ledgers want non-reactive champion damage) and a bus that
    pre-filters would have to pick one of them.  The CC trigger exists
    exactly when the row carries real control: ``NONE`` and ``UNREVIEWED``
    never fire one.

    ``kinds`` is what makes D-30's lazy construction real rather than
    documented: a caller asking only for control never *builds* the damage
    trigger it would discard, so a control-only holder is neither charged
    for it nor judged by its stricter field contract.  Classification runs
    either way — the damage trigger carries the row's ``cc`` fields — so a
    misspelled ``cc_kind`` is rejected whichever kind was asked for.
    """
    if not isinstance(row, Mapping):
        return ()
    cc_class, cc_kind, cc_reviewed = _classify_cc(row)
    if not kinds & _ROW_KINDS:
        return ()
    shared = {
        "time": _float(row.get("time")),
        "source_key": str(row.get("source_key", "") or ""),
        "event_id": str(row.get("_event_id", "") or ""),
        "attacker_id": str(row.get("attacker", "") or ""),
        "target_id": str(row.get("target", "") or ""),
        "sequence": _sequence(row.get("sequence")),
        "ability_instance": str(row.get("ability_instance", "") or ""),
        "damage": max(0.0, _float(row.get("damage"))),
        "raw_damage": max(0.0, _float(row.get("raw_damage"))),
        "damage_type": str(row.get("damage_type", "") or ""),
        "is_ability": bool(row.get("is_ability")),
        "basic_attack": bool(row.get("basic_attack")),
        "reactive": bool(row.get("_reactive")),
        "cc": cc_class,
        "cc_kind": cc_kind,
        "cc_reviewed": cc_reviewed,
    }
    triggers: list[Trigger] = []
    if TriggerKind.DAMAGE in kinds:
        triggers.append(Trigger(kind=TriggerKind.DAMAGE, **shared))
    if TriggerKind.CC in kinds and cc_class in _CONTROL_CLASSES:
        triggers.append(Trigger(kind=TriggerKind.CC, **shared))
    return tuple(triggers)


def _takedown_trigger(row: Mapping[str, Any]) -> Trigger | None:
    """One explicit takedown receipt as a Trigger; never a kill inferred."""
    if not isinstance(row, Mapping):
        return None
    if row.get("time") is None or not str(row.get("target", "") or ""):
        return None
    return Trigger(
        kind=TriggerKind.TAKEDOWN,
        time=_float(row.get("time")),
        source_key=str(row.get("source_key", "") or ""),
        event_id=str(row.get("_event_id", "") or ""),
        attacker_id=str(row.get("attacker", "") or ""),
        target_id=str(row.get("target", "") or ""),
        sequence=-1,
        ability_instance="",
        damage=0.0,
        raw_damage=0.0,
        damage_type="",
        is_ability=False,
        basic_attack=False,
        reactive=False,
        cc=CcClass.UNREVIEWED,
        cc_kind="",
        cc_reviewed=False,
    )


_STREAM_OF_KIND: Mapping[TriggerKind, Stream] = MappingProxyType(
    {
        TriggerKind.CC: Stream.CC,
        TriggerKind.DAMAGE: Stream.DAMAGE,
        TriggerKind.TAKEDOWN: Stream.TAKEDOWN,
    }
)


def authored_triggers(
    result: Mapping[str, Any],
    *,
    streams: frozenset[Stream],
    holder: str = "",
) -> tuple[Trigger, ...]:
    """Flatten one engine result into the ordered bus, building only what is asked.

    Lazy by construction: a caller that declares no stream pays nothing, and
    a caller that declares ``{Stream.CC}`` never walks the damage ledger for
    a damage trigger it will discard.  That is what keeps the migration
    performance-neutral (D-30).

    Raises:
        ProjectionStarvation: the result carries the optimizer's positional
            6-tuple ledger and the caller asked for a stream parsed off dict
            rows.  A projection and a consumer disagree, which is a
            programming error — the pipeline's tuple gate is supposed to have
            kept dict rows for this holder.
    """
    wanted = streams & RAW_STREAMS
    if not wanted:
        return ()
    if result.get("damage_events_tuple"):
        asked = ", ".join(sorted(stream.value for stream in wanted))
        raise ProjectionStarvation(
            asked,
            holder,
            "the score-only tuple ledger carries positional rows no scan can "
            "read; the pipeline's tuple gate must keep dict rows for every "
            "holder tuple_incapable_items() names",
        )
    triggers: list[Trigger] = []
    row_kinds = frozenset(
        kind for kind in _ROW_KINDS if _STREAM_OF_KIND[kind] in wanted
    )
    if row_kinds:
        for row in result.get("damage_events", ()) or ():
            triggers.extend(event_triggers(row, kinds=row_kinds))
    if Stream.TAKEDOWN in wanted:
        for row in result.get("takedown_events", ()) or ():
            takedown = _takedown_trigger(row)
            if takedown is not None:
                triggers.append(takedown)
    return tuple(triggers)


def is_immobilizing_event(row: Mapping[str, Any]) -> bool:
    """The one immobilize predicate, for callers holding a row not a Trigger.

    Same answer as classifying the row and asking whether the class is
    ``IMMOBILIZE`` — stated as a function because four consumers hold a raw
    row and would otherwise each re-read ``cc_kind`` for themselves, which is
    the divergence that let a slow price Command.
    """
    return _classify_cc(row)[0] is CcClass.IMMOBILIZE


@cache
def tuple_incapable_items() -> frozenset[str]:
    """Holders whose scan cannot read the light 6-tuple ledger.

    Bandlepipes, Black Cleaver, Bloodletter's Curse, Bloodsong, Cryptbloom,
    Echoes of Helia, Fimbulwinter, Imperial Mandate, Phage, Solstice Sleigh
    (10).

    A holder is here exactly when one of its mechanics declares a stream that
    is parsed off raw rows.  This is the predicate the pipeline's score-only
    tuple gate consults, and the same predicate the participant timeline's
    enrichment gate is a subset of — one derivation, two gates, so they can
    never again disagree (D-01).
    """
    return _projected_items(lambda cap: bool(cap.reads & RAW_STREAMS))


@cache
def enriched_view_items() -> frozenset[str]:
    """Holders needing the pair path's per-event target/_event_id enrichment.

    Black Cleaver, Bloodletter's Curse, Bloodsong, Cryptbloom, Fimbulwinter,
    Imperial Mandate (6).

    Fimbulwinter is a member because it carries ``_trigger_event_id`` onto
    its shield packet — spelled ``event.event_id or None`` since P2b, where
    the plan's D-03 text still quotes the retired raw-row
    ``event.get("_event_id")`` — and dropping the enrichment both changes a
    serialized receipt field and strips the only trigger link any support
    author emits, which is the link the survival compiler's fail-closed
    ``support_trigger_link`` branch exists to refuse (D-03).
    """
    return _projected_items(
        lambda cap: bool(cap.reads & RAW_STREAMS) and bool(cap.needs & _ENRICHED_FIELDS)
    )


@cache
def pair_outcome_items() -> frozenset[str]:
    """Holders whose stream is synthesized from the one-pair shield outcome.

    Cryptbloom (1).

    The takedown stream has no authored producer: the receipt composition
    synthesizes it from the pair fight's ``target_ending_health``, so a
    score-only fight for these holders must keep that outcome rather than
    skip it.
    """
    return _projected_items(lambda cap: Stream.TAKEDOWN in cap.reads)


def _projected_items(
    predicate: Callable[[MechanicCapability], bool],
) -> frozenset[str]:
    """The item names of every declared mechanic satisfying ``predicate``."""
    return frozenset(
        capability.owner.name
        for capability in CAPABILITIES.values()
        if isinstance(capability.owner, ItemOwner) and predicate(capability)
    )


@cache
def streams_for(names: frozenset[str]) -> frozenset[Stream]:
    """Which streams a holder's declared mechanics consume.

    The lazy-build argument in one function: the bus builds exactly the
    streams this returns, so a mechanic that forgets to declare
    ``Stream.CC`` is handed an empty list and prices zero — which is why A9
    feeds every declared stream a synthetic marker and empties it again.
    """
    return frozenset(
        stream
        for capability in CAPABILITIES.values()
        if isinstance(capability.owner, ItemOwner) and capability.owner.name in names
        for stream in capability.reads
    )


def holders_in(items: Iterable[Mapping[str, Any]], names: frozenset[str]) -> bool:
    """Whether any held item is in a projected name set — the gate call shape."""
    return any(str(item.get("name", "")) in names for item in items)
