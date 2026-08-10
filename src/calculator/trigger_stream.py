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

The module is a leaf on purpose: its only intra-package import is
``ability_spec``, the dependency-free vocabulary module, so the hot pipeline
can ask a ledger-shape question without loading the 52 KB packet compiler.
Registry validation is structural only and reads no file (D-35) — item-name
resolution lives in the test that pins the projections.
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
from typing import Any

from .ability_spec import (
    CC_KIND_VOCABULARY,
    IMMOBILIZING_CC_KINDS,
    Authority,
    Disposition,
)

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
    "ItemOwner",
    "MechanicCapability",
    "MechanicOwner",
    "Pairing",
    "ProjectionStarvation",
    "RAW_STREAMS",
    "RuneOwner",
    "Stream",
    "Trigger",
    "TriggerKind",
    "TriggerRegistryError",
    "authored_triggers",
    "enriched_view_items",
    "event_triggers",
    "holders_in",
    "is_immobilizing_event",
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

# The three ``Authority`` members a mechanic declares only when it modifies
# some *other* participant's damage.  ``COUPLED_AUTHORITATIVE`` is the
# ordinary statement that the walk owns its own packet; the three below each
# additionally say a second engine can see the same mechanic, which is the
# property that makes a mechanic a cross-participant producer.  A walk half
# declaring one of these and carrying a ``packet_source`` is therefore a
# producer the coupled golden baseline must hold a scenario for (R-12), and
# this constant is where that reading lives — the baseline instrument reads
# CAPABILITIES through it rather than re-spelling the three members.
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


class ProjectionStarvation(RuntimeError):
    """A consumer asked a stream a question this result cannot answer.

    This is the campaign's ``STARVED`` disposition as a control-flow signal:
    a projection and a consumer disagree, which is a programming error and
    not a data condition.  It is raised lazily, on the first read of an
    inadequate representation, and caught at exactly one boundary — the
    request boundary in ``src/app.py`` (D-25).  Everywhere else it
    propagates, because a named refusal that is silently absorbed is the
    zero this campaign exists to kill.
    """

    #: The campaign disposition this signal *is*, so the one boundary that
    #: converts it into a response reads the spelling off the exception
    #: rather than re-deriving which of the four states a starvation is.
    disposition = Disposition.STARVED

    def __init__(self, field: str, producer: str, reason: str) -> None:
        super().__init__(
            f"STARVED: {producer or '<unnamed holder>'} asked for the "
            f"{field} stream — {reason}"
        )
        self.field = field
        self.producer = producer
        self.reason = reason


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
    nothing dispatches on a control row's type, and the retired ``_cc_triggers``
    accepted a control row carrying any type at all — including the
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
    Phase 4 retires it; Phase 2 creates none, and A8 asserts the set empty.
    Precedent: ``item_source.ACKNOWLEDGED_SOURCE_CONFLICTS``.
    """

    ref: str
    mechanic: str
    pair_reading: str
    walk_reading: str
    source_url: str
    revision_id: int
    issue_ref: int


DIVERGENCES: Mapping[str, DivergenceReceipt] = MappingProxyType({})


# Eleven fields, and the umbrella's field-ownership table adds four more
# in later phases: a declaration record is exactly as wide as the facts
# it declares.
@dataclass(frozen=True, slots=True)
class MechanicCapability:  # pylint: disable=too-many-instance-attributes
    """One mechanic's declared transport, authority and implementation site.

    Phase 2 writes every field below.  Phase 3 adds ``values`` and
    ``compilability``, Phase 4 adds ``view_tags`` and ``holder_stacking`` —
    all four required with no default on the commit that adds them, so a
    later phase's field forces every declaration to be revisited instead of
    silently inheriting an empty value.

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
        packet_source: the walk packet's ``source`` string, verbatim, or
            ``None`` for a half that emits no packet.
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
    packet_source: str | None


_SUPPORT_IMPL = "item_support_effects.derive_item_support_effects"
_KNIGHTS_VOW_IMPL = "item_support_effects.schedule_knights_vow"


def _walk_item(  # pylint: disable=too-many-arguments
    mechanic: str,
    item: str,
    packet_source: str,
    *,
    reads: frozenset[Stream] = frozenset(),
    needs: frozenset[Field] = frozenset(),
    authority: Authority = Authority.COUPLED_AUTHORITATIVE,
    pairing: Pairing = Pairing.SOLO,
    pair_of: str | None = None,
    impl: str = _SUPPORT_IMPL,
) -> MechanicCapability:
    """One item-granted mechanic the participant walk implements.

    A constructor, not a default: every field the umbrella assigns Phase 2
    still has to be written for every row, and the keyword defaults here are
    the values that are true of the *majority* of walk packets — no stream,
    no raw field, the walk owns its own packet, no pair-side half.  A row
    that differs states its difference at the call site, which is what makes
    the table readable as a table.
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
        divergence_ref=None,
        impl=impl,
        packet_source=packet_source,
    )


def _pair_half(
    mechanic: str,
    owner: MechanicOwner,
    impl: str,
    *,
    authority: Authority,
) -> MechanicCapability:
    """One pair-engine half — the target of a walk half's ``pair_of``.

    A pair half reads no bus stream: the pair engine walks its own ordered
    breakdown rather than the authored row ledger, so its ``reads`` is empty
    by construction and not by omission.
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
    )


_DECLARATIONS: tuple[MechanicCapability, ...] = (
    # -- walk packets compiled by ``derive_item_support_effects`` ------------
    _walk_item("cull.reap", "Cull", "Cull — Reap"),
    _walk_item(
        "phage.rage",
        "Phage",
        "Phage — Rage",
        reads=frozenset({Stream.DAMAGE}),
        needs=frozenset({Field.TIME, Field.SOURCE_KEY, Field.BASIC_ATTACK}),
    ),
    _walk_item(
        "world_atlas.shared_riches", "World Atlas", "World Atlas — Shared Riches"
    ),
    _walk_item("world_atlas.ward", "World Atlas", "World Atlas — Ward"),
    _walk_item(
        "runic_compass.shared_riches",
        "Runic Compass",
        "Runic Compass — Shared Riches",
    ),
    _walk_item("runic_compass.ward", "Runic Compass", "Runic Compass — Ward"),
    _walk_item(
        "fimbulwinter.everlasting",
        "Fimbulwinter",
        "Fimbulwinter — Everlasting",
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
        authority=Authority.SPLIT,
        pairing=Pairing.PAIRED,
        pair_of="abyssal_mask.magic_amp",
    ),
    _walk_item(
        "bloodsong.expose_weakness",
        "Bloodsong",
        "Bloodsong — Expose Weakness",
        reads=frozenset({Stream.DAMAGE}),
        needs=frozenset(
            {Field.TIME, Field.TARGET_ID, Field.EVENT_ID, Field.SOURCE_KEY}
        ),
        authority=Authority.SPLIT,
        pairing=Pairing.PAIRED,
        pair_of="bloodsong.expose_weakness_preview",
    ),
    _walk_item(
        "black_cleaver.carve",
        "Black Cleaver",
        "Black Cleaver — Carve",
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
    _walk_item(
        "bloodletters_curse.vile_decay",
        "Bloodletter's Curse",
        "Bloodletter's Curse — Vile Decay",
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
        reads=frozenset({Stream.TAKEDOWN}),
        needs=frozenset({Field.TIME, Field.TARGET_ID}),
    ),
    _walk_item(
        "ardent_censer.sanctify",
        "Ardent Censer",
        "Ardent Censer — Sanctify",
        reads=frozenset({Stream.SUPPORT_TRIGGER}),
    ),
    _walk_item(
        "staff_of_flowing_water.rapids",
        "Staff of Flowing Water",
        "Staff of Flowing Water — Rapids",
        reads=frozenset({Stream.SUPPORT_TRIGGER}),
    ),
    _walk_item(
        "moonstone_renewer.starlit_grace",
        "Moonstone Renewer",
        "Moonstone Renewer — Starlit Grace",
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
        reads=frozenset({Stream.SUPPORT_TRIGGER}),
        authority=Authority.COUPLED_ONLY,
    ),
    _walk_item(
        "dream_maker.purple_bubble",
        "Dream Maker",
        "Dream Maker — Purple Dream Bubble",
        reads=frozenset({Stream.SUPPORT_TRIGGER}),
    ),
    _walk_item(
        "echoes_of_helia.soul_siphon",
        "Echoes of Helia",
        "Echoes of Helia — Soul Siphon",
        reads=frozenset({Stream.SUPPORT_TRIGGER, Stream.DAMAGE}),
        needs=frozenset({Field.DAMAGE, Field.RAW_DAMAGE}),
    ),
    _walk_item(
        "diadem_of_songs.consonance",
        "Diadem of Songs",
        "Diadem of Songs — Consonance",
        reads=frozenset({Stream.SUPPORT_TRIGGER}),
    ),
    _walk_item(
        "bandlepipes.fanfare",
        "Bandlepipes",
        "Bandlepipes — Fanfare",
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
        reads=frozenset({Stream.CC}),
        needs=frozenset({Field.TIME}),
    ),
    _walk_item(
        "imperial_mandate.command",
        "Imperial Mandate",
        "Imperial Mandate — Command",
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
    ),
    _walk_item(
        "mikaels_blessing.purify", "Mikael's Blessing", "Mikael's Blessing — Purify"
    ),
    _walk_item("redemption.intervention", "Redemption", "Redemption — Intervention"),
    _walk_item(
        "shurelyas_battlesong.inspiring_speech",
        "Shurelya's Battlesong",
        "Shurelya's Battlesong — Inspiring Speech",
    ),
    _walk_item(
        "stridebreaker.breaking_shockwave",
        "Stridebreaker",
        "Stridebreaker — Breaking Shockwave",
    ),
    # -- the second walk packet compiler ------------------------------------
    _walk_item(
        "knights_vow.sacrifice",
        "Knight's Vow",
        "Knight's Vow — Sacrifice",
        impl=_KNIGHTS_VOW_IMPL,
    ),
    # -- pair-engine halves -------------------------------------------------
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
        authority=Authority.SPLIT,
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
    _pair_half(
        "horizon_focus.hypershot",
        ItemOwner("Horizon Focus"),
        "damage._apply_damage_amplifiers",
        authority=Authority.PAIR_ONLY,
    ),
    _pair_half(
        "shadowflame.cinderbloom",
        ItemOwner("Shadowflame"),
        "damage._add_shadowflame_cinderbloom",
        authority=Authority.COUPLED_AUTHORITATIVE_WITH_PAIR_PREVIEW,
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
    ),
    # -- non-item owners (D-36) ---------------------------------------------
    *(
        MechanicCapability(
            mechanic=f"{slug}.keystone",
            owner=RuneOwner(keystone),
            engine=Engine.PAIR,
            reads=frozenset(),
            needs=frozenset(),
            authority=Authority.PAIR_ONLY,
            pairing=Pairing.SOLO,
            pair_of=None,
            divergence_ref=None,
            impl="rune_effects.resolve_keystone",
            packet_source=None,
        )
        for slug, keystone in (
            ("electrocute", "Electrocute"),
            ("first_strike", "First Strike"),
            ("press_the_attack", "Press the Attack"),
            ("arcane_comet", "Arcane Comet"),
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
    ),
)


CAPABILITIES: Mapping[str, MechanicCapability] = MappingProxyType(
    {capability.mechanic: capability for capability in _DECLARATIONS}
)


def _validate_registry() -> None:
    """Structural cross-check of :data:`CAPABILITIES`, at import.

    Structural only, and no file is read (D-35): slug shape, unique ids,
    ``pair_of`` resolving to an ``Engine.PAIR`` capability, ``PAIRED``
    implying a ``packet_source``, ``UNPAIRED_KNOWN_DEFECT`` implying a
    ``divergence_ref`` that resolves in :data:`DIVERGENCES`, and a takedown
    reader needing a target id.  Item-name resolution belongs to the test
    that pins the projections, because a leaf that touches ``data/`` is
    neither a leaf nor inside the caching layer (repo rule 2).
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
        _validate_pairing(mechanic, capability)
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
        if capability.packet_source is None:
            raise TriggerRegistryError(
                f"{mechanic} is PAIRED and declares no packet_source; the "
                "walk half's packet is what the pair half is paired against"
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
        raise TriggerRegistryError(
            f"{mechanic} is {capability.pairing.value} and carries a " "divergence_ref"
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

    Fimbulwinter is a member because it carries
    ``_trigger_event_id=event.get("_event_id")`` onto its shield packet, and
    dropping it both changes a serialized receipt field and disarms the
    fail-closed ``support_trigger_link`` raise in the survival compiler
    (D-03).
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
