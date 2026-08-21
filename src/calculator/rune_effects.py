"""Rune values and effect formulas — the whole page, not the keystone alone.

Mirrors ``item_effects`` ownership rules for runes: every numeric rune value
comes from ``data/runes.json`` (parsed from the League Wiki's rune data
templates) through typed accessors that raise, naming the rune and key, when
the parse degraded. No literal fallbacks.

This module is the public surface — resolve, validate, catalog, and the
effect types every compiler produces. The compilers themselves live in two
places: keystones here in ``_KEYSTONE_COMPILERS``, and one module per path
under ``rune_paths``, each exporting its own ``COMPILERS``. :func:`resolve_rune`
merges them into one vocabulary, so a minor rune and a keystone are the same
kind of thing to everything downstream.

Only a rune with a compile function is modeled; selecting any other rune
fails closed with a clear error, and :func:`rune_catalog` publishes the whole
roster with an ``implemented`` flag rather than hiding what it cannot price.

A compiled rune is not the same claim as a rune that deals damage. Some price
damage on a declared trigger stream; others have no combat number in any
source, or have halves this engine holds no channel for (a summoner-spell
haste, a heal, a shield, a crowd-control trigger). Those compile to a
:class:`RuneNoDamageEffect` carrying the disposition and the reason, which the
engine publishes — never a silent zero.
"""

from dataclasses import dataclass
from enum import Enum
from functools import cache
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence

from .ability_spec import Disposition, ZeroPolicy
from .data_fetcher import fetch_rune_data
from .item_effects import DamageInputs
from .request_parsing import request_positional_string_list, request_string_list
from .rune_parser import (
    ADAPTIVE_FORCE_KEY,
    DEFAULT_LEVEL_COUNT,
    RESERVED_CACHE_KEYS,
    SHARDS_KEY,
)
from .state_lifecycle import SourceReceipt, StackRule, TimedStackState


def _load_rune_cache() -> dict[str, Any]:
    """Read ``data/runes.json``; an absent cache means no runes.

    Copies the fetched mapping: the data layer serves its parsed-JSON
    cache by reference, and ``refresh_rune_effects`` clears these dicts in
    place — clearing the shared cache object would erase the source.
    """
    try:
        return dict(fetch_rune_data())
    except (FileNotFoundError, ValueError):
        return {}


def _split_cache(
    contents: Mapping[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any], dict[str, Any]]:
    """Split the cache into runes, the shard table, and the adaptive block."""
    runes = {
        name: entry
        for name, entry in contents.items()
        if name not in RESERVED_CACHE_KEYS
    }
    return (
        runes,
        dict(contents.get(SHARDS_KEY) or {}),
        dict(contents.get(ADAPTIVE_FORCE_KEY) or {}),
    )


#: Every rune the roster offers, keyed by name.
RUNE_EFFECTS: dict[str, dict[str, Any]]
#: The Rune page's stat-shard table: three slots, three options each.
RUNE_SHARDS: dict[str, Any]
#: ``Template:Adaptive``'s own conversion — what one point of adaptive force
#: is worth in bonus attack damage (ability power takes it at face value).
ADAPTIVE_FORCE: dict[str, Any]
RUNE_EFFECTS, RUNE_SHARDS, ADAPTIVE_FORCE = _split_cache(_load_rune_cache())


def at_level(values: "tuple[float, ...] | list[float]", level: int) -> float:
    """Read a per-level table at one champion level, clamped to its ends."""
    return values[max(1, min(level, len(values))) - 1]


def _slot_word(rune_name: str) -> str:
    """Whether the roster puts this rune in a keystone slot or a minor one."""
    row = RUNE_EFFECTS.get(rune_name, {}).get("row", 0)
    return "keystone" if int(row or 0) == 0 else "rune"


def breakdown_key(rune_name: str) -> str:
    """The ledger key for one rune's damage row.

    Keystone rows and minor-rune rows are told apart by their prefix, and
    which one a rune gets is read off the roster rather than spelled by each
    compiler — the slot is a fact about the rune, not about its formula.
    """
    return f"{_slot_word(rune_name)}_{rune_name}"


def display_name(rune_name: str) -> str:
    """The breakdown row's label for one rune."""
    return f"{rune_name} ({_slot_word(rune_name)})"


def refresh_rune_effects() -> None:
    """Re-read data/runes.json in place after a data update."""
    runes, shards, adaptive = _split_cache(_load_rune_cache())
    RUNE_EFFECTS.clear()
    RUNE_EFFECTS.update(runes)
    RUNE_SHARDS.clear()
    RUNE_SHARDS.update(shards)
    ADAPTIVE_FORCE.clear()
    ADAPTIVE_FORCE.update(adaptive)


def rune_effect_value(rune_name: str, key: str) -> float:
    """Return one required numeric rune value, failing loudly.

    The public read behind ``value_ref.ValueRef(registry="RUNE_EFFECTS", …)``:
    runes are runtime damage producers, so CLAUDE.md rule 5's no-literals
    discipline reaches them, and a declaration referencing a rune number needs
    the same fail-loud accessor items already have.  It reuses
    ``RuneValues`` rather than re-reading the registry, so "read a
    rune number" keeps one implementation.

    A rune record has two levels — the entry's own fields (``cooldown``) and
    the parser's ``effects`` block — and a reference names a number, not a
    level, so both are searched.  A key present in **both** raises rather
    than picking one: two numbers under one name is a parse defect, and
    silently preferring a level is how a declaration starts citing the wrong
    one.
    """
    entry = RUNE_EFFECTS.get(rune_name)
    if not isinstance(entry, Mapping):
        raise KeyError(f"RUNE_EFFECTS[{rune_name!r}] is missing")
    effects = entry.get("effects")
    effects = effects if isinstance(effects, Mapping) else {}
    top_level = entry.get(key) is not None
    if top_level and effects.get(key) is not None:
        raise KeyError(
            f"RUNE_EFFECTS[{rune_name!r}] holds {key!r} at both levels; two "
            "numbers under one name is a parse defect, not a preference"
        )
    if top_level:
        return RuneValues(rune_name, entry).number(key)
    return RuneValues(rune_name, effects).number(key)


class RuneTrigger(Enum):
    """Which of the fight's event streams a proc-class rune watches.

    The engine owns the timeline; a rune owns *which* of its events it
    counts. Naming the stream here keeps that a declared fact instead of a
    walker per rune.
    """

    #: Damaging ability casts and simulated auto swings, one counter.
    DAMAGE_INSTANCES = "damage_instances"
    #: Simulated auto swings alone — abilities never stack these.
    BASIC_ATTACKS = "basic_attacks"
    #: Accepted damaging ability casts alone — autos never trigger these.
    DAMAGING_CASTS = "damaging_casts"
    #: Damaging casts whose own authored parts apply crowd control, so the
    #: target is under it when the damage lands. A floor by construction:
    #: the engine carries no control *duration*, so damage landing later
    #: inside the same control is not in this stream.
    IMPAIRED_INSTANCES = "impaired_instances"
    #: The swings a self-shield armed: the first basic attack at or after
    #: each ``self_shield_events`` entry the fight publishes. Named for the
    #: arming event because that is what a rune watching it declares; what
    #: it *counts* is swings, because a shield with no attack after it
    #: empowers nothing and must book nothing.
    SELF_SHIELD_EVENTS = "self_shield_events"


def _always_armed(options: "Mapping[str, Mapping[str, float]]") -> bool:
    """The default arming rule: nothing the page declares gates this proc."""
    del options
    return True


ASSUMPTIONS: tuple[str, ...] = (
    "Unsealed Spellbook is the one keystone that books no damage. It is a "
    "summoner-spell selection state: the user chooses the equipped spells and "
    "each swap, and every summoner spell has its own effect (damage, shield, "
    "heal, movement, or CC). The cached wiki template (data/runes.json) "
    "carries empty 'effects' and a null 'cooldown', and its swap-cooldown "
    "sentences use unresolved {{#var:...}} placeholders, so the rune itself "
    "states no combat number. It compiles to a RuneNoDamageEffect with a "
    "STRUCTURAL_ZERO disposition: selectable, listed as implemented, and "
    "publishing its receipt in the fight notes rather than refusing at the "
    "API boundary.",
    "The compiler reads only keys a keystone's own template authored. Some "
    "registry entries carry mis-attributed generic-parse keys (Lethal Tempo "
    "and Conqueror record a 'deathfire_tick_interval_seconds' from the shared "
    "'every N seconds' prose; Arcane Comet records its max-range ratio pair "
    "under 'deathfire_*' keys). These are parser false positives: no compiler "
    "reads them, they must never be treated as sourced values, and fixing "
    "them belongs to rune_parser (generic regexes must be Deathfire-scoped).",
    "Arcane Comet's proc is priced at the assumed 375-unit travel distance "
    "(mid-range poke); every comet is assumed to land. Aery's return travel "
    "has no sourced duration, so the next signal uses the sourced linger "
    "boundary as a lower bound. First Strike assumes the user initiates "
    "combat. These assumptions are disclosed in the fight notes by the "
    "engine.",
    "Dark Harvest's sourced 1.75s delay is the Soul-reap delay; the wiki "
    "prices the damage as immediate on the triggering hit. The compiler "
    "stores the value generically as proc_delay_seconds, and any engine that "
    "lands the damage at trigger + delay is making an engine-side choice.",
)


def zero_receipts(
    rune_name: str, zero_policy: ZeroPolicy, disclosures: tuple[str, ...] = ()
) -> tuple[str, ...]:
    """The fight notes a rune publishes when it books nothing, verdict first."""
    verdict = (
        "deals no damage in any fight"
        if zero_policy.disposition is Disposition.STRUCTURAL_ZERO
        else "is not priced"
    )
    return (f"{rune_name} {verdict}: {zero_policy.reason}.",) + disclosures


@dataclass(frozen=True, slots=True)
class RuneProcEffect:
    """A stack-triggered rune proc with a cooldown (Electrocute-class).

    ``raw_damage`` prices one proc; ``damage_type`` resolves the adaptive
    physical/magic choice from the champion's stats. Stack accumulation and
    cooldown gating live in the fight engine, which owns the timeline.

    ``trigger`` names the event stream the stacks come from,
    ``stack_window_seconds`` is ``None`` for a rune whose stacks the cache
    gives no expiry for, and ``consumes_stacks`` is false where the rune
    keeps its stacks and empowers every later trigger (Lethal Tempo) rather
    than spending them (Electrocute). ``disclosures`` are the rune's own
    receipts — assumed cadences and withheld halves — which the engine
    publishes verbatim; the words belong with the rune.

    ``armed`` is how a proc reads the page's declared options — the one
    thing the raw-damage inputs cannot carry, because those are the item
    vocabulary and a rune option is not an item's. A rune whose whole
    trigger is an input the fight has no event for (Sudden Impact's dash)
    declares the option and answers here; every other rune keeps the
    default and is armed by its stream alone.
    """

    rune_name: str
    breakdown_key: str
    display_name: str
    stacks_required: int
    stack_window_seconds: float | None
    cooldown_seconds: float
    proc_delay_seconds: float
    raw_damage: Callable[[DamageInputs], float]
    damage_type: Callable[[Mapping[str, float]], str]
    trigger: RuneTrigger = RuneTrigger.DAMAGE_INSTANCES
    consumes_stacks: bool = True
    disclosures: tuple[str, ...] = ()
    armed: "Callable[[Mapping[str, Mapping[str, float]]], bool]" = _always_armed


class RuneHealTrigger(Enum):
    """Which of the fight's streams a rune heal is paid on.

    The heal side's :class:`RuneTrigger`: the rune names the stream and the
    engine owns what is in it, so a healing rune is walked by the same kind
    of declaration a damaging one is.
    """

    #: Every damage instance the holder lands on the target, gated by the
    #: rune's own cooldown (Taste of Blood).
    DAMAGE_DEALT = "damage_dealt"
    #: The instances that put the target under crowd control (Font of Life)
    #: — :attr:`RuneTrigger.IMPAIRED_INSTANCES` read from the other side:
    #: one rune is paid for landing damage on an impaired target and the
    #: other for doing the impairing, and both are the same reviewed marker.
    IMPAIRING_INSTANCES = "impairing_instances"
    #: The takedowns the fight actually scored — the target reaching zero
    #: health, at the instance that took it there (Triumph). None are
    #: invented: a fight the target survives pays nothing.
    TAKEDOWNS = "takedowns"


@dataclass(frozen=True, slots=True)
class RuneHealEffect:
    """A rune that heals its holder, priced into the self-healing ledger.

    The heal-side sibling of :class:`RuneProcEffect`, and deliberately the
    same shape: a declared stream, a cooldown the engine gates on, a delay
    the heal lands after, and one formula priced against the build. The
    packets it produces are the ones item sustain produces — a rune heal is
    not a different kind of heal, only a different owner.

    ``amount`` reads :class:`~.item_effects.DamageInputs` because that is
    already the shape every compiled rune formula is handed: the holder's
    stat block, level and range class, and the target's health. Nothing in
    it is damage-specific, and a second near-identical record for heals
    would be one more thing to keep in step.
    """

    rune_name: str
    trigger: RuneHealTrigger
    cooldown_seconds: float
    delay_seconds: float
    amount: Callable[[DamageInputs], float]
    disclosures: tuple[str, ...] = ()

    @property
    def source(self) -> str:
        """The ledger label for this rune's heal packets."""
        return display_name(self.rune_name)


@dataclass(frozen=True, slots=True)
class RuneNoDamageEffect:
    """A compiled rune that books no damage, and says why.

    Two dispositions reach here, and the difference is the receipt.
    ``STRUCTURAL_ZERO`` is a rune with no combat damage in any source —
    zero is the answer. ``WITHHELD`` is a real effect this engine has no
    channel for (a heal, a shield, a crowd-control trigger, a stat the
    fight does not read): the number exists and is refused, never estimated.

    Modelled on ``item_behavior_catalog``'s ``ZeroPolicy`` declarations so a
    rune that contributes nothing is *selectable and receipted* rather than
    a refusal at the API boundary.
    """

    rune_name: str
    zero_policy: ZeroPolicy
    disclosures: tuple[str, ...] = ()

    @property
    def receipts(self) -> tuple[str, ...]:
        """The fight notes this rune publishes, verdict first."""
        return zero_receipts(self.rune_name, self.zero_policy, self.disclosures)


@dataclass(frozen=True, slots=True)
class RuneWindowAmpEffect:
    """A combat-opening damage-window rune (First Strike-class).

    Post-mitigation damage dealt inside the opening window gains a sourced
    ratio as bonus true damage; activation grants flat gold plus a
    melee/ranged share of the bonus damage as gold. A continuous fight
    activates the buff exactly once, so the rune's out-of-combat cooldown
    never gates anything the engine models.

    **The window and the ratio are not here.** They are the amp chain's
    ``OPENING_WINDOW`` slot, declared as a ``BehaviorRule`` over
    ``RUNE_EFFECTS`` references, and one number with two homes is the drift
    this campaign exists to remove. What is left is the gold accounting and
    the receipt strings, which no amp declaration models: gold is not damage
    and never joins the total.
    """

    rune_name: str
    breakdown_key: str
    display_name: str
    activation_gold: float
    gold_conversion_melee: float
    gold_conversion_ranged: float

    def gold_conversion(self, is_melee: bool) -> float:
        """The share of bonus damage returned as gold for this range class."""
        return self.gold_conversion_melee if is_melee else self.gold_conversion_ranged


@dataclass(frozen=True, slots=True)
class RuneProcAmpEffect:
    """A stacked proc that then amplifies the rest of the fight (PTA-class).

    Basic attacks build stacks that expire ``stack_duration_seconds``
    after the last application; reaching ``stacks_required`` consumes
    them for ``raw_damage`` adaptive damage and turns on a lasting
    amplifier of all non-true damage. The buff ends only out of combat, so a
    continuous fight keeps it from first proc to the end. Stack walking lives
    in the fight engine, which owns the timeline.

    **The amplifier is not here.** Its ratio, the events it prices and the
    boundary that excludes the swing that armed it are the amp chain's
    ``LASTING_PROC_AMP`` slot, declared as a ``BehaviorRule`` over
    ``RUNE_EFFECTS`` references. What is left is the proc itself.
    """

    rune_name: str
    breakdown_key: str
    display_name: str
    stacks_required: int
    stack_duration_seconds: float
    cooldown_seconds: float
    raw_damage: Callable[[DamageInputs], float]
    damage_type: Callable[[Mapping[str, float]], str]

    @property
    def amp_breakdown_key(self) -> str:
        """Ledger key for the lasting-amp row, beside the proc row's key."""
        return f"{self.breakdown_key} amp"

    @property
    def amp_display_name(self) -> str:
        """Display name for the lasting-amp breakdown row."""
        return f"{self.rune_name} amp ({_slot_word(self.rune_name)})"


@dataclass(frozen=True, slots=True)
class RuneAbilityProcEffect:
    """An ability-cast-triggered proc on a leveled cooldown (Arcane Comet-class).

    Each damaging ability cast fires the proc when it is off cooldown;
    basic attacks never trigger it, and damage over time neither
    triggers nor extends anything (unlike the Liandry's burn family) —
    the trigger stream is ability casts alone. ``raw_damage`` prices one
    proc at the assumed travel distance: the wiki's damage grows with
    how far the comet flies (``distance_amp_ratio`` holds the resulting
    multiplier bonus), and every comet is assumed to land. Cast walking
    and cooldown gating live in the fight engine, which owns the
    timeline.
    """

    rune_name: str
    breakdown_key: str
    display_name: str
    cooldown_by_level: tuple[float, ...]
    proc_delay_seconds: float
    assumed_travel_distance: float
    distance_amp_ratio: float
    raw_damage: Callable[[DamageInputs], float]
    damage_type: Callable[[Mapping[str, float]], str]

    def cooldown_at(self, level: int) -> float:
        """The proc cooldown at one champion level, clamped to the table."""
        return at_level(self.cooldown_by_level, level)


class RuneStat(Enum):
    """The stat channels a rune may grant into.

    Named rather than free-form because a grant into a channel the engine
    does not read is a withheld effect, not a stat — the closed set is what
    makes that distinction checkable. ``ADAPTIVE_FORCE`` is the one channel
    that is not a stat by itself: it resolves to bonus attack damage or
    ability power at application time.
    """

    ADAPTIVE_FORCE = "adaptive_force"
    ATTACK_SPEED_PERCENT = "attack_speed_percent"
    ABILITY_HASTE = "ability_haste"
    #: Haste on the basic abilities alone (Q/W/E), the channel Spear of
    #: Shojin feeds. Separate from ``ABILITY_HASTE`` because the ultimate
    #: reads that one: granting Legend: Haste there would shorten a cooldown
    #: the rune does not touch.
    BASIC_ABILITY_HASTE = "basic_ability_haste"
    #: Haste on the ultimate alone, the channel Malignance and its siblings
    #: feed, and the mirror of the one above.
    ULTIMATE_HASTE = "ultimate_haste"
    #: Life steal, which the fight's own life-steal walk turns into timed
    #: heal packets off the holder's physical attack events — so a rune
    #: granting here reaches the heal ledger through the same door an item's
    #: life steal does, and needs no rune-shaped heal of its own.
    LIFESTEAL_PERCENT = "lifesteal_percent"
    MOVE_SPEED_PERCENT = "move_speed_percent"
    BONUS_HEALTH = "bonus_health"
    LETHALITY = "lethality"
    MAGIC_PENETRATION_FLAT = "magic_penetration_flat"


class RuneOptionKind(Enum):
    """What shape of number one rune option accepts.

    A rune's missing input is either a switch — the health gate held or it
    did not, the dash happened or it did not — or a count: Legend stacks,
    the game minute Gathering Storm reached. Naming which lets
    :meth:`RuneOption.validated` refuse the halves a range alone would
    accept, and lets the picker render the control from the declaration
    instead of from a coincidence.
    """

    SWITCH = "switch"
    COUNT = "count"


@dataclass(frozen=True, slots=True)
class RuneOption:
    """One explicit input a rune needs that the request does not carry.

    Decision 5's shape: a stack count, a game minute, whether a dash
    happened. Every one of them is a declared option with a default the
    rune discloses in its fight notes — never a constant inferred from the
    fight. ``bounds`` is inclusive on both ends, and every option is
    discrete: a half stack and a half-held gate are both nonsense.
    """

    key: str
    label: str
    kind: RuneOptionKind
    default: float
    bounds: tuple[float, float]
    disclosure: str

    def as_catalog_entry(self) -> dict[str, Any]:
        """The published shape, matching the champion-option catalog."""
        return {
            "key": self.key,
            "label": self.label,
            "kind": self.kind.value,
            "default": self.default,
            "minimum": self.bounds[0],
            "maximum": self.bounds[1],
            "disclosure": self.disclosure,
        }

    def validated(self, value: Any) -> float:
        """One requested value, or a refusal naming the option and its range."""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"rune option {self.key!r} must be a number")
        number = float(value)
        if number != int(number):
            raise ValueError(f"rune option {self.key!r} must be a whole number")
        low, high = self.bounds
        if not low <= number <= high:
            raise ValueError(
                f"rune option {self.key!r} must be between {low:g} and {high:g}"
            )
        return number


def _option_value(
    options: Mapping[str, Mapping[str, float]],
    rune_name: str,
    key: str,
    default: float,
) -> float:
    """One declared option of one rune, or its disclosed default.

    Shared by everything a rune formula reads an option through — the two
    contexts and the proc arming rule — so "what this option is worth" has
    one implementation whether a stat grant, an amplifier or a proc asks.
    """
    value = options.get(rune_name, {}).get(key)
    return default if value is None else float(value)


def armed_by_option(
    rune_name: str, key: str, default: float = 0.0
) -> Callable[[Mapping[str, Mapping[str, float]]], bool]:
    """A proc arming rule reading one declared switch off the page.

    The proc-side counterpart of ``RuneStatContext.option``: a rune whose
    trigger is an input the fight has no event for declares the switch and
    hands this to :class:`RuneProcEffect`, so the option is read in one
    place rather than by a walker branch per rune. The default is the
    un-triggered state, so a page that sets nothing prices nothing.
    """

    def armed(options: Mapping[str, Mapping[str, float]]) -> bool:
        return bool(_option_value(options, rune_name, key, default))

    return armed


@dataclass(frozen=True, slots=True)
class RuneStatContext:
    """What a stat grant is allowed to read when it resolves its amount.

    The build's own bonus attack damage and ability power are here because
    adaptive force asks which of them is larger; ``options`` carries the
    explicit inputs the request has no other home for (a stack count, a game
    minute), each with a default the rune discloses.

    ``item_stat_types`` is how many distinct stat types the build's items
    grant — a fact about the build rather than an option, because the build
    is in the request and nothing has to be assumed to count it. Jack Of All
    Trades is the one rune whose stacks *are* that count.
    """

    level: int
    is_melee: bool
    bonus_attack_damage: float
    ability_power: float
    options: Mapping[str, Mapping[str, float]]
    item_stat_types: int = 0

    def option(self, rune_name: str, key: str, default: float) -> float:
        """One declared option of one rune, or its disclosed default."""
        return _option_value(self.options, rune_name, key, default)


@dataclass(frozen=True, slots=True)
class RuneStatGrantEffect:
    """A rune that grants one stat, applied where item stats are applied.

    ``amount`` prices the grant for one build and level; ``stat`` names the
    channel it lands in. A grant that is conditional on something the request
    does not carry (a health share, a stack count) reads the condition
    through :class:`RuneStatContext`'s options and discloses the default it
    assumed — never an inferred constant.
    """

    rune_name: str
    stat: RuneStat
    amount: Callable[[RuneStatContext], float]
    disclosures: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RuneMultiStatGrantEffect:
    """A rune granting several channels at once, off one shared count.

    Its own kind rather than two of the sibling above, because these runes'
    channels are computed *together*: Jack Of All Trades pays ability haste
    per stack and adaptive force at two stack gates, and Legend: Bloodline
    pays life steal per stack and bonus health at its last one. Split into
    two single-channel effects, the halves could read different counts —
    which is exactly the drift one declaration prevents.

    ``stats`` is declared rather than derived from what ``amounts`` returns,
    for the reason the closed :class:`RuneStat` set exists at all: whether a
    rune grants into a channel the engine reads has to be checkable without
    running a fight. A channel ``amounts`` returns that ``stats`` does not
    declare is refused rather than applied.
    """

    rune_name: str
    stats: tuple[RuneStat, ...]
    amounts: Callable[[RuneStatContext], Mapping[RuneStat, float]]
    disclosures: tuple[str, ...] = ()

    def declared_amounts(self, context: RuneStatContext) -> Mapping[RuneStat, float]:
        """The grant, certified against the channels this rune declares."""
        amounts = self.amounts(context)
        undeclared = sorted(
            stat.value for stat in amounts if stat not in set(self.stats)
        )
        if undeclared:
            raise KeyError(
                f"rune {self.rune_name!r} granted into undeclared channels "
                f"{undeclared} — a stat rune's channels are declared, not "
                "discovered at apply time"
            )
        return amounts


#: The kinds the damage walk carries for their *words* alone. Each applies
#: its number somewhere else — a stat grant in ``stats.py`` before the fight,
#: a heal in the pipeline's self-healing ledger after it — so none writes a
#: damage row, and what the fight owes the reader is the assumption behind
#: the number rather than the number.
RUNE_RECEIPT_ONLY_KINDS = (
    RuneStatGrantEffect,
    RuneMultiStatGrantEffect,
    RuneHealEffect,
)


@dataclass(frozen=True, slots=True)
class KeystoneAeryEffect:
    """Summon Aery's damage and ally-shield packets.

    Aery has no cooldown field.  The fight timeline gates new signals until
    the sourced target linger ends.  Damage and shielding keep separate
    flight times because the wiki gives separate receipts for them.
    """

    rune_name: str
    breakdown_key: str
    display_name: str
    damage_by_level: tuple[float, ...]
    shield_by_level: tuple[float, ...]
    bonus_ad_ratio: float
    ap_ratio: float
    damage_flight_seconds: float
    shield_flight_seconds: float
    shield_duration_seconds: float
    linger_seconds: float
    damage_type: Callable[[Mapping[str, float]], str]
    # Halves this compiler does not price; empty means fully priced.
    unpriced_receipts: tuple[str, ...] = ()

    def raw_damage(self, inputs: DamageInputs) -> float:
        """Price one offensive signal from sourced level and stat tables."""
        stats = inputs.champion_stats
        return (
            at_level(self.damage_by_level, inputs.level)
            + self.bonus_ad_ratio * stats.get("bonus_attack_damage", 0.0)
            + self.ap_ratio * stats.get("ability_power", 0.0)
        )

    def raw_shield(self, inputs: DamageInputs) -> float:
        """Price one ally shield from sourced level and stat tables."""
        stats = inputs.champion_stats
        return (
            at_level(self.shield_by_level, inputs.level)
            + self.bonus_ad_ratio * stats.get("bonus_attack_damage", 0.0)
            + self.ap_ratio * stats.get("ability_power", 0.0)
        )

    def shield_amount(self, level: int, stats: Mapping[str, float]) -> float:
        """Price one ally shield from a participant result context."""
        return self.raw_shield(
            DamageInputs(
                champion_stats=stats,
                level=level,
                is_melee=False,
                target_max_health=0.0,
                target_current_health=0.0,
            )
        )


@dataclass(frozen=True, slots=True)
class KeystoneGuardianEffect:
    """Guardian's guarded-ally threshold shield.

    The participant timeline owns Guard selection, cumulative damage windows,
    and the paired shield application.  This object owns only the sourced
    level tables, ratios, and timing values.
    """

    rune_name: str
    breakdown_key: str
    display_name: str
    threshold_by_level: tuple[float, ...]
    shield_by_level: tuple[float, ...]
    cooldown_by_level: tuple[float, ...]
    ap_ratio: float
    bonus_health_ratio: float
    trigger_window_seconds: float
    shield_duration_seconds: float
    unpriced_receipts: tuple[str, ...] = ()

    def threshold_at(self, level: int) -> float:
        """Read the sourced post-mitigation trigger threshold."""
        return at_level(self.threshold_by_level, level)

    def cooldown_at(self, level: int) -> float:
        """Read the sourced cooldown after a shield trigger."""
        return at_level(self.cooldown_by_level, level)

    def shield_amount(self, level: int, stats: Mapping[str, float]) -> float:
        """Price both Guardian shields from the holder's stats."""
        return (
            at_level(self.shield_by_level, level)
            + self.ap_ratio * stats.get("ability_power", 0.0)
            + self.bonus_health_ratio * stats.get("bonus_health", 0.0)
        )


@dataclass(frozen=True, slots=True)
class KeystoneAftershockEffect:
    """Aftershock's immobilize-triggered resistance and shockwave packets."""

    rune_name: str
    breakdown_key: str
    display_name: str
    resistance_cap_by_level: tuple[float, ...]
    shockwave_damage_by_level: tuple[float, ...]
    cooldown_seconds: float
    flat_armor: float
    flat_magic_resistance: float
    bonus_armor_ratio: float
    bonus_magic_resistance_ratio: float
    bonus_health_ratio: float
    duration_seconds: float
    shockwave_radius: float
    unpriced_receipts: tuple[str, ...] = ()

    def resistance_bonus(
        self, level: int, stats: Mapping[str, float], resistance_type: str
    ) -> float:
        """Price one capped resistance bonus from trigger-time stats."""
        if resistance_type == "armor":
            base = self.flat_armor
            ratio = self.bonus_armor_ratio
            stat_key = "bonus_armor"
        elif resistance_type == "magic_resistance":
            base = self.flat_magic_resistance
            ratio = self.bonus_magic_resistance_ratio
            stat_key = "bonus_magic_resistance"
        else:
            raise ValueError(
                f"Aftershock has unknown resistance type {resistance_type!r}"
            )
        uncapped = base + ratio * stats.get(stat_key, 0.0)
        return min(uncapped, at_level(self.resistance_cap_by_level, level))

    def shockwave_raw_damage(self, level: int, stats: Mapping[str, float]) -> float:
        """Price the delayed magic shockwave from sourced level and health."""
        return at_level(
            self.shockwave_damage_by_level, level
        ) + self.bonus_health_ratio * stats.get("bonus_health", 0.0)


@dataclass(frozen=True, slots=True)
class KeystoneGraspEffect:
    """Grasp's timed combat stacks and empowered basic attack.

    The fight engine owns stack timing and the proc target. The participant
    timeline applies the sourced self-heal and permanent health receipt.
    """

    rune_name: str
    breakdown_key: str
    display_name: str
    damage_melee_ranged_ratios: tuple[float, float]
    heal_melee_ranged_ratios: tuple[float, float]
    bonus_health_melee_ranged: tuple[float, float]
    stack_cadence_seconds: float
    stack_generation_seconds: float
    max_stacks: int
    ready_window_seconds: float
    # Halves this compiler does not price; empty means fully priced.
    unpriced_receipts: tuple[str, ...] = ()

    @staticmethod
    def _select(values: tuple[float, float], is_melee: bool) -> float:
        """Select the sourced melee or ranged value."""
        return values[0 if is_melee else 1]

    def damage_ratio(self, is_melee: bool) -> float:
        """Return the maximum-health damage ratio for one attack class."""
        return self._select(self.damage_melee_ranged_ratios, is_melee)

    def heal_ratio(self, is_melee: bool) -> float:
        """Return the maximum-health self-heal ratio for one attack class."""
        return self._select(self.heal_melee_ranged_ratios, is_melee)

    def bonus_health(self, is_melee: bool) -> float:
        """Return the permanent health gain for one attack class."""
        return self._select(self.bonus_health_melee_ranged, is_melee)

    def raw_damage(self, stats: Mapping[str, float], is_melee: bool) -> float:
        """Price one empowered attack from maximum health."""
        return self.damage_ratio(is_melee) * stats.get("health", 0.0)

    def heal_amount(self, stats: Mapping[str, float], is_melee: bool) -> float:
        """Price one self-heal from maximum health."""
        return self.heal_ratio(is_melee) * stats.get("health", 0.0)


@dataclass(frozen=True, slots=True)
class KeystoneHailOfBladesEffect:
    """Hail of Blades' temporary attack-speed and true-damage packets.

    The fight engine owns the swing schedule and the limited reset-stack
    window. This object owns the sourced level table, ratios, and timing.
    """

    rune_name: str
    breakdown_key: str
    display_name: str
    damage_by_level: tuple[float, ...]
    bonus_ad_ratio: float
    ap_ratio: float
    bonus_attack_speed_melee_ranged: tuple[float, float]
    initial_stacks: int
    stack_duration_seconds: float
    reset_stack_limit: int
    cooldown_seconds: float
    # Halves this compiler does not price; empty means fully priced.
    unpriced_receipts: tuple[str, ...] = ()

    @staticmethod
    def _select(values: tuple[float, float], is_melee: bool) -> float:
        """Select the sourced melee or ranged value."""
        return values[0 if is_melee else 1]

    def bonus_attack_speed_percent(self, is_melee: bool) -> float:
        """Return Hail's temporary bonus attack speed percentage."""
        return self._select(self.bonus_attack_speed_melee_ranged, is_melee)

    def raw_damage(self, inputs: DamageInputs) -> float:
        """Price one bonus true-damage attack from level and ratios."""
        stats = inputs.champion_stats
        return (
            at_level(self.damage_by_level, inputs.level)
            + self.bonus_ad_ratio * stats.get("bonus_attack_damage", 0.0)
            + self.ap_ratio * stats.get("ability_power", 0.0)
        )


@dataclass(frozen=True, slots=True)
class KeystoneLethalTempoEffect:
    """Lethal Tempo's stacked attack speed and max-stack bolt."""

    rune_name: str
    breakdown_key: str
    display_name: str
    bolt_damage_melee_by_level: tuple[float, ...]
    bolt_damage_ranged_by_level: tuple[float, ...]
    attack_speed_percent_melee_ranged: tuple[float, float]
    bolt_damage_increase_ratio_melee_ranged: tuple[float, float]
    max_stacks: int
    stack_duration_seconds: float
    expiry_step_seconds: float
    damage_type: Callable[[Mapping[str, float]], str]
    # Halves this compiler does not price; empty means fully priced.
    unpriced_receipts: tuple[str, ...] = ()

    @staticmethod
    def _select(values: tuple[float, float], is_melee: bool) -> float:
        """Select the sourced melee or ranged value."""
        return values[0 if is_melee else 1]

    def attack_speed_percent(self, is_melee: bool, stacks: int) -> float:
        """Return the sourced bonus attack speed at one stack count."""
        return self._select(self.attack_speed_percent_melee_ranged, is_melee) * max(
            0, min(int(stacks), self.max_stacks)
        )

    def bolt_raw_damage(
        self, inputs: DamageInputs, is_melee: bool, stacks: int
    ) -> float:
        """Price one max-stack bolt, including its sourced AS increase."""
        table = (
            self.bolt_damage_melee_by_level
            if is_melee
            else self.bolt_damage_ranged_by_level
        )
        base = at_level(table, inputs.level)
        total_bonus_attack_speed = inputs.champion_stats.get(
            "bonus_attack_speed", 0.0
        ) + self.attack_speed_percent(is_melee, stacks)
        increase = self._select(self.bolt_damage_increase_ratio_melee_ranged, is_melee)
        return base * (1.0 + total_bonus_attack_speed * increase)


@dataclass(frozen=True, slots=True)
class KeystoneGlacialEffect:
    """Glacial Augment's control-triggered zones and ally damage reduction."""

    rune_name: str
    breakdown_key: str
    display_name: str
    cooldown_seconds: float
    ray_count: int
    zone_radius_units: float
    zone_width_units: float
    zone_base_duration_seconds: float
    zone_duration_cc_ratio: float
    slow_base_ratio: float
    slow_bonus_ad_ratio_per_100: float
    slow_ap_ratio_per_100: float
    slow_heal_shield_ratio_per_10: float
    damage_reduction_ratio: float
    unpriced_receipts: tuple[str, ...] = ()

    def zone_duration(self, cc_duration: float) -> float:
        """Return the sourced zone lifetime for one control event."""
        return self.zone_base_duration_seconds + self.zone_duration_cc_ratio * max(
            0.0, cc_duration
        )

    def slow_ratio(self, stats: Mapping[str, float]) -> float:
        """Return the sourced slow from the holder's current stats."""
        return (
            self.slow_base_ratio
            + self.slow_bonus_ad_ratio_per_100
            * max(0.0, stats.get("bonus_attack_damage", 0.0))
            / 100.0
            + self.slow_ap_ratio_per_100
            * max(0.0, stats.get("ability_power", 0.0))
            / 100.0
            + self.slow_heal_shield_ratio_per_10
            * max(0.0, stats.get("heal_and_shield_power_percent", 0.0))
            / 10.0
        )


@dataclass(frozen=True, slots=True)
class KeystoneStormraiderEffect:
    """Stormraider's Surge's damage-threshold movement burst."""

    rune_name: str
    breakdown_key: str
    display_name: str
    cooldown_by_level: tuple[float, ...]
    damage_threshold_ratio: float
    damage_window_seconds: float
    bonus_move_speed_melee_ranged: tuple[float, float]
    slow_resist_ratio: float
    duration_seconds: float
    unpriced_receipts: tuple[str, ...] = ()

    def cooldown_at(self, level: int) -> float:
        """Read the sourced cooldown at one champion level."""
        return at_level(self.cooldown_by_level, level)

    def bonus_move_speed_percent(self, is_melee: bool) -> float:
        """Select the sourced melee or ranged movement-speed percentage."""
        return self.bonus_move_speed_melee_ranged[0 if is_melee else 1]


@dataclass(frozen=True, slots=True)
class KeystoneFleetEffect:
    """Fleet Footwork's charged basic-attack heal and speed burst."""

    rune_name: str
    breakdown_key: str
    display_name: str
    heal_melee_by_level: tuple[float, ...]
    heal_ranged_by_level: tuple[float, ...]
    bonus_ad_ratio_melee_ranged: tuple[float, float]
    ap_ratio_melee_ranged: tuple[float, float]
    bonus_move_speed_melee_ranged: tuple[float, float]
    minion_heal_effectiveness: float
    charge_cap: int
    move_speed_duration_seconds: float
    # Halves this compiler does not price; empty means fully priced.
    unpriced_receipts: tuple[str, ...] = ()

    @staticmethod
    def _select(values: tuple[float, float], is_melee: bool) -> float:
        """Select the sourced melee or ranged value."""
        return values[0 if is_melee else 1]

    def heal_amount(
        self,
        level: int,
        stats: Mapping[str, float],
        is_melee: bool,
        *,
        against_minion: bool = False,
    ) -> float:
        """Price one Energized heal from the holder's current stats."""
        base = at_level(
            self.heal_melee_by_level if is_melee else self.heal_ranged_by_level,
            level,
        )
        amount = (
            base
            + self._select(self.bonus_ad_ratio_melee_ranged, is_melee)
            * stats.get("bonus_attack_damage", 0.0)
            + self._select(self.ap_ratio_melee_ranged, is_melee)
            * stats.get("ability_power", 0.0)
        )
        if against_minion:
            amount *= self.minion_heal_effectiveness
        return max(0.0, amount)

    def bonus_move_speed_percent(self, is_melee: bool) -> float:
        """Select the sourced Energized movement-speed percentage."""
        return self._select(self.bonus_move_speed_melee_ranged, is_melee)


@dataclass(frozen=True, slots=True)
class KeystoneConquerorEffect:
    """Conqueror's typed stack state and max-stack healing."""

    rune_name: str
    breakdown_key: str
    display_name: str
    adaptive_force_by_level: tuple[float, ...]
    adaptive_force_max_by_level: tuple[float, ...]
    max_stacks: int
    stacks_per_application: int
    stack_duration_seconds: float
    cast_instance_interval_seconds: float
    heal_melee_ranged_ratios: tuple[float, float]
    # Halves this compiler does not price; empty means fully priced.
    unpriced_receipts: tuple[str, ...] = ()

    def adaptive_force_at(self, level: int, stacks: int) -> float:
        """Return the sourced adaptive-force amount at a stack count."""
        clamped = max(0, min(int(stacks), self.max_stacks))
        return at_level(self.adaptive_force_by_level, level) * clamped

    def max_adaptive_force_at(self, level: int) -> float:
        """Return the source's explicit maximum-stack force table value."""
        return at_level(self.adaptive_force_max_by_level, level)

    def bonus_attack_damage_at(self, level: int, stacks: int) -> float:
        """Convert adaptive force to bonus AD for an AD adaptive page."""
        return self.adaptive_force_at(level, stacks) * 0.6

    def ability_power_at(self, level: int, stacks: int) -> float:
        """Convert adaptive force to AP for an AP adaptive page."""
        return self.adaptive_force_at(level, stacks)

    def heal_ratio(self, is_melee: bool) -> float:
        """Select the sourced melee or ranged max-stack healing ratio."""
        return self.heal_melee_ranged_ratios[0 if is_melee else 1]

    def heal_amount(self, post_mitigation_damage: float, is_melee: bool) -> float:
        """Price the max-stack heal from post-mitigation champion damage."""
        return max(0.0, float(post_mitigation_damage)) * self.heal_ratio(is_melee)


# Reviewed provenance for Conqueror's stack rule.  Every numeric field is
# parser-owned from ``data/runes.json`` (League Wiki rune data templates);
# the cache carries no per-rune revision, so the receipt follows the
# cache-backed convention used elsewhere in this codebase.
_CONQUEROR_SOURCE = SourceReceipt(
    label="data/runes.json (League Wiki rune data templates)",
    url="https://wiki.leagueoflegends.com/en-us/Conqueror",
    revision_id=0,
    revision_timestamp="cached data/runes.json",
)


def conqueror_stack_state(
    effect: "KeystoneConquerorEffect", *, starting_stacks: int = 0
) -> TimedStackState:
    """Build the kernel-owned Conqueror stack state.

    The sourced rule: stacks last ``stack_duration_seconds`` (5) and refresh
    on subsequent damage; the cap is ``max_stacks`` (12).  Basic-attack
    packets grant ``stacks_per_application`` (2, the flattened sourced
    value; the wiki's melee/ranged 2/1 on-hit split is not extracted by the
    rune parser and stays a documented approximation).  Ability-cast packets
    grant the same amount but only once per ``cast_instance_interval_seconds``
    (4) per ability — the audit's over-stack fix: our trigger walk emits one
    packet per cast, so the sourced "up to once every 4 seconds per cast
    instance" gate binds as a per-ability cadence on repeated casts.
    """
    rule = StackRule(
        name="Conqueror",
        max_stacks=int(effect.max_stacks),
        gain_per_application=int(effect.stacks_per_application),
        duration_seconds=float(effect.stack_duration_seconds),
        refresh="refresh",
        expiry="all_at_once",
        interval_seconds=float(effect.cast_instance_interval_seconds),
        interval_key="source_key",
        interval_gate_packets=frozenset({"ability_cast"}),
        source=_CONQUEROR_SOURCE,
    )
    return TimedStackState(rule, starting_stacks=starting_stacks)


@dataclass(frozen=True, slots=True)
class KeystoneDeathfireEffect:
    """Deathfire Touch's typed burn packets and duration categories."""

    rune_name: str
    breakdown_key: str
    display_name: str
    damage_by_level: tuple[float, ...]
    amplified_damage_by_level: tuple[float, ...]
    bonus_ad_ratios_by_state: tuple[float, float]
    ap_ratios_by_state: tuple[float, float]
    tick_interval_seconds: float
    amp_delay_seconds: float
    amp_ratio: float
    duration_by_category: Mapping[str, float]
    # Halves this compiler does not price; empty means fully priced.
    unpriced_receipts: tuple[str, ...] = ()

    def duration_for(self, category: str) -> float:
        """Return one authored duration category or fail closed."""
        try:
            return float(self.duration_by_category[category])
        except KeyError as exc:
            raise KeyError(
                f"RUNE_EFFECTS[{self.rune_name!r}] is missing burn duration "
                f"category {category!r}"
            ) from exc

    def raw_tick(
        self,
        level: int,
        stats: Mapping[str, float],
        *,
        amplified: bool = False,
    ) -> float:
        """Price one source-backed magic burn tick."""
        state = 1 if amplified else 0
        base = at_level(
            self.amplified_damage_by_level if amplified else self.damage_by_level,
            level,
        )
        return max(
            0.0,
            base
            + self.bonus_ad_ratios_by_state[state]
            * stats.get("bonus_attack_damage", 0.0)
            + self.ap_ratios_by_state[state] * stats.get("ability_power", 0.0),
        )


@dataclass(frozen=True, slots=True)
class KeystoneDarkHarvestEffect:
    """Dark Harvest's threshold-triggered adaptive damage.

    The engine owns the target-health walk and cooldown.  ``souls`` is the
    count held before the proc; the next Soul becomes available only after
    the sourced reap delay.  The wiki prices that delay on the Soul REAP —
    the damage is immediate on the triggering hit — while
    ``proc_delay_seconds`` stores the sourced delay generically; landing the
    damage at trigger + delay is an engine-side choice (see ``ASSUMPTIONS``).
    """

    rune_name: str
    breakdown_key: str
    display_name: str
    cooldown_seconds: float
    health_threshold_ratio: float
    base_damage: float
    soul_damage: float
    bonus_ad_ratio: float
    ap_ratio: float
    proc_delay_seconds: float
    takedown_reset_seconds: float
    damage_type: Callable[[Mapping[str, float]], str]
    unpriced_receipts: tuple[str, ...] = ()

    def raw_damage(self, inputs: DamageInputs, souls: int = 0) -> float:
        """Price one proc from the pre-reap Soul count and champion stats."""
        stats = inputs.champion_stats
        return (
            self.base_damage
            + self.soul_damage * max(0, int(souls))
            + self.bonus_ad_ratio * stats.get("bonus_attack_damage", 0.0)
            + self.ap_ratio * stats.get("ability_power", 0.0)
        )


class AmpCondition(Enum):
    """When a conditional amplifier is live, in the cache's own spelling.

    The values are what ``rune_parser`` records under
    ``damage_amp_health_gate``, so a compiler reads the condition instead of
    translating it — one fact, one spelling, no mapping table to drift.

    Only the gates the ledger walk can *evaluate* are members. The cache also
    records ``self_below`` (Last Stand's gate on the holder's own health),
    and it is deliberately absent: the pair engine prices outgoing damage
    and carries no holder-health track, so a compiler naming it fails here
    rather than compiling into a walker branch that would book nothing. That
    rune is a :class:`RuneFlatAmpEffect` instead, where the holder's health
    is a declared option rather than a track the fight does not have.
    """

    TARGET_BELOW = "target_below"
    TARGET_ABOVE = "target_above"


@dataclass(frozen=True, slots=True)
class RuneConditionalAmpEffect:
    """A damage amplifier gated on a health share (Coup de Grace-class).

    The engine walks its ordered damage ledger and amplifies exactly the
    instances that land while the condition holds, so the row is the real
    share of the fight the rune reached rather than a flat multiplier over
    the total.
    """

    rune_name: str
    breakdown_key: str
    display_name: str
    condition: AmpCondition
    health_ratio: float
    amp_ratio: float
    disclosures: tuple[str, ...] = ()


#: The cast-order key of the ultimate slot — the one slot a rune's filter
#: names today (Axiom Arcanist).  It lives beside :class:`RuneAmpContext`
#: because the context's ``slot`` is what a filter compares against; the
#: champion contract's own five slots are ``REQUIRED_CHAMPION_SLOTS``.
ULTIMATE_SLOT = "R"


@dataclass(frozen=True, slots=True)
class RuneAmpContext:
    """What a flat amplifier is allowed to read when it prices one instance.

    The union of every fact the three roster runes of this shape decide from:
    the holder's level and stat block, the target's maximum health (a rune
    that amplifies the bigger target compares the two), the page's declared
    options, and ``slot`` — the cast-order key of the ability whose ledger
    row is being priced, empty for a row no ability cast (an auto, an item
    proc, an earlier amplifier's delta).
    """

    level: int
    is_melee: bool
    champion_stats: Mapping[str, float]
    target_max_health: float
    options: Mapping[str, Mapping[str, float]]
    slot: str = ""

    def option(self, rune_name: str, key: str, default: float) -> float:
        """One declared option of one rune, or its disclosed default."""
        return _option_value(self.options, rune_name, key, default)


@dataclass(frozen=True, slots=True)
class RuneFlatAmpEffect:
    """A constant ratio over a filtered set of the fight's damage instances.

    The kind for an amplifier whose condition the ledger's health walk
    cannot express: Last Stand reads the *holder's* health (which the pair
    engine does not track, so it is a declared option), Axiom Arcanist reads
    which slot cast the damage. ``amp_ratio`` answers both halves at once —
    the ratio for the instances it amplifies, zero for the rest — so the
    filter and the number are one declaration instead of two that can
    disagree about which instances the number covers.

    The ratio must be the *same* for every instance the rune amplifies. One
    breakdown row publishes one multiplier, so a rune answering with two
    would make that row a fiction; the walker refuses it rather than
    picking one.
    """

    rune_name: str
    breakdown_key: str
    display_name: str
    amp_ratio: Callable[[RuneAmpContext], float]
    disclosures: tuple[str, ...] = ()


RuneEffect = (
    RuneProcEffect
    | RuneWindowAmpEffect
    | RuneProcAmpEffect
    | RuneAbilityProcEffect
    | RuneNoDamageEffect
    | RuneHealEffect
    | RuneStatGrantEffect
    | RuneMultiStatGrantEffect
    | RuneConditionalAmpEffect
    | RuneFlatAmpEffect
    | KeystoneAeryEffect
    | KeystoneGuardianEffect
    | KeystoneAftershockEffect
    | KeystoneGraspEffect
    | KeystoneHailOfBladesEffect
    | KeystoneLethalTempoEffect
    | KeystoneGlacialEffect
    | KeystoneStormraiderEffect
    | KeystoneFleetEffect
    | KeystoneConquerorEffect
    | KeystoneDeathfireEffect
    | KeystoneDarkHarvestEffect
)


class RuneValues:
    """Typed, contextual reads from one rune registry record."""

    def __init__(self, rune_name: str, values: Mapping[str, Any]) -> None:
        self.rune_name = rune_name
        self.values = values

    def value(self, key: str) -> Any:
        """Return one required value or raise with rune and key context."""
        if key not in self.values or self.values[key] is None:
            raise KeyError(
                f"RUNE_EFFECTS[{self.rune_name!r}] is missing {key!r} — "
                "wiki parse degraded; check rune_parser and data/runes.json"
            )
        return self.values[key]

    def number(self, key: str) -> float:
        """Return one required numeric value as a float."""
        return float(self.value(key))


#: The column count of a level table stating every level of the game's cap.
_FULL_LEVEL_COUNT = 20

#: The two widths the wiki's own rendering gives a level table. A formula
#: with an explicit ``1 to 20 by 1`` range states all twenty; a stepless
#: ``A to B`` (Sudden Impact's "20 to 80") renders Module:Ability
#: progression's ``defaultSize`` of eighteen with its endpoints anchored at
#: levels 1 and 18. Both are complete statements of what the wiki says, and
#: a table of any *other* width is a degraded parse — which is the check
#: this pair keeps: admitting the short rendering must not admit a
#: twenty-level table that lost two of its columns.
LEVEL_TABLE_SIZES = (DEFAULT_LEVEL_COUNT, _FULL_LEVEL_COUNT)


def _certified_level_table(name: str, key: str, values: Sequence[Any]) -> list[float]:
    """One per-level table, certified as a width the wiki renders."""
    if not isinstance(values, (list, tuple)):
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] {key} is not a table of per-level "
            "values — wiki parse degraded"
        )
    try:
        by_level = [float(value) for value in values]
    except (TypeError, ValueError) as exc:
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] {key} holds a non-numeric level "
            "value — wiki parse degraded"
        ) from exc
    if len(by_level) not in LEVEL_TABLE_SIZES:
        widths = " or ".join(str(size) for size in LEVEL_TABLE_SIZES)
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] {key} covers {len(by_level)} "
            f"levels; the wiki renders {widths} — wiki parse degraded"
        )
    return by_level


def _required_table(
    name: str, effects: RuneValues, key: str, index: int
) -> Sequence[Any]:
    """One table out of a rune's multi-table key, or a named refusal."""
    tables = effects.value(key)
    if not isinstance(tables, (list, tuple)):
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] {key} is not a list of tables — "
            "wiki parse degraded"
        )
    if index >= len(tables):
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] {key} holds {len(tables)} tables and "
            f"table {index} was required — wiki parse degraded"
        )
    return tables[index]


def cached_effects(rune_name: str) -> RuneValues:
    """One rune's parsed effects block, for a declaration read at import.

    A compiler reads the record it is handed; an option's *bounds* are
    declared before any request exists, and the rune's own table is what
    bounds them — so the declaration reads the cache through the same
    fail-loud door.
    """
    return RuneValues(rune_name, RUNE_EFFECTS.get(rune_name, {}).get("effects", {}))


def required_leveling(
    name: str,
    effects: RuneValues,
    key: str = "leveling",
    index: int = 0,
) -> list[float]:
    """Read one of a rune's per-level tables, at a width the wiki renders.

    ``key`` and ``index`` because a rune record states several tables under
    several names — a melee and a ranged one, a base and an escalated one —
    and every one of them is read through this same fail-loud door.
    """
    table = _required_table(name, effects, key, index)
    return _certified_level_table(name, key, table)


def required_level_table(name: str, effects: RuneValues, key: str) -> list[float]:
    """Read one flat per-level table, at a width the wiki renders.

    The sibling of :func:`required_leveling` for the keys the parser records
    as a single table rather than a list of them (``adaptive_force_leveling``).
    """
    return _certified_level_table(name, key, effects.value(key))


def keyed_columns(
    name: str, effects: RuneValues, key: str, index: int
) -> tuple[float, ...]:
    """Read one table whose columns are not champion levels.

    :func:`required_leveling` certifies a width the wiki renders *levels*
    at, which is the right door for a level table and the wrong one for a
    table keyed by game minutes: Gathering Storm states eight columns and
    would fail a level check that is not its rule.
    """
    table = _required_table(name, effects, key, index)
    try:
        columns = tuple(float(value) for value in table)
    except (TypeError, ValueError) as exc:
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] {key} table {index} holds a non-numeric "
            "column — wiki parse degraded"
        ) from exc
    if len(columns) < 2:
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] {key} table {index} holds {len(columns)} "
            "columns; a keyed table needs at least two to state its step — "
            "wiki parse degraded"
        )
    return columns


def threshold_gates(
    name: str, effects: RuneValues, key: str
) -> tuple[tuple[int, float], ...]:
    """Read a rune's ``level, bonus`` gates, requiring at least one."""
    gates = tuple((int(level), float(bonus)) for level, bonus in effects.value(key))
    if not gates:
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] {key} states no gates — wiki parse degraded"
        )
    return gates


def required_pair(name: str, effects: RuneValues, key: str) -> tuple[float, float]:
    """Read a rune's melee/ranged pair, in that order."""
    values = [float(value) for value in effects.value(key)]
    if len(values) != 2:
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] {key} holds {len(values)} values and is "
            "not a melee/ranged pair — wiki parse degraded"
        )
    return values[0], values[1]


def pure_adaptive_type(stats: Mapping[str, float]) -> str:
    """Adaptive damage type for a proc with no ratios of its own.

    The larger of bonus AD and AP decides. A tie follows the champion's
    adaptive type in game; the engine carries no adaptive type, so it
    defaults magic like Electrocute.
    """
    bonus_ad = stats.get("bonus_attack_damage", 0.0)
    return "physical" if bonus_ad > stats.get("ability_power", 0.0) else "magic"


def stated_type(damage_type: str) -> Callable[[Mapping[str, float]], str]:
    """A damage type the rune states outright, not an adaptive choice."""

    def stated(stats: Mapping[str, float]) -> str:
        del stats
        return damage_type

    return stated


def required_cooldown_by_level(
    name: str, entry: Mapping[str, Any]
) -> tuple[float, ...]:
    """Read a rune's per-level cooldown list, requiring all 20 levels."""
    cooldown = entry.get("cooldown")
    if not isinstance(cooldown, list) or len(cooldown) < 20:
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] cooldown is not a 20-level list — "
            "wiki parse degraded; check rune_parser and data/runes.json"
        )
    return tuple(float(value) for value in cooldown)


def ratio_adaptive_type(
    bonus_ad_ratio: float, ap_ratio: float
) -> Callable[[Mapping[str, float]], str]:
    """Adaptive damage type from ratio-weighted contributions.

    The larger contribution decides; a tie (or all-zero) defaults magic,
    matching the wiki's variable-damage rule.
    """

    def adaptive_type(stats: Mapping[str, float]) -> str:
        ad_contribution = bonus_ad_ratio * stats.get("bonus_attack_damage", 0.0)
        ap_contribution = ap_ratio * stats.get("ability_power", 0.0)
        return "physical" if ad_contribution > ap_contribution else "magic"

    return adaptive_type


#: What a dedicated keystone publishes when a fight books it no row: the
#: disposition, the reason that becomes the receipt, and any further half
#: this engine refuses.  Their values are all sourced and compiled — this
#: says only what *this* fight could not do with them, which is why it
#: lives beside the compilers rather than in ``_NO_DAMAGE_KEYSTONES``.
_UNPRICED_KEYSTONES: Mapping[str, tuple[Disposition, str, tuple[str, ...]]] = (
    MappingProxyType(
        {
            "Glacial Augment": (
                Disposition.STRUCTURAL_ZERO,
                "its zones slow, and the damage reduction they apply protects "
                "the holder's allies while explicitly excluding the holder",
                (),
            ),
            "Stormraider's Surge": (
                Disposition.STRUCTURAL_ZERO,
                "it grants movement speed and slow resist, neither of which "
                "the engine's damage model reads",
                (
                    "Stormraider's Surge's zero is exact only while the "
                    "holder owns no Swiftmarch, whose passive converts "
                    "movement speed into adaptive force "
                    "(item_effects.swiftmarch_adaptive_force); that coupling "
                    "is disclosed, not modeled.",
                ),
            ),
            "Guardian": (
                Disposition.WITHHELD,
                "it shields the holder or a guarded ally against incoming "
                "damage, and this fight priced no shield for it",
                (),
            ),
            "Aftershock": (
                Disposition.WITHHELD,
                "its shockwave fires only after the holder immobilizes a "
                "champion, and no reviewed crowd-control event landed in "
                "this fight",
                (
                    "Aftershock's bonus resistances are withheld with it and "
                    "are defensive besides: the pair engine prices outgoing "
                    "damage.",
                ),
            ),
            "Dark Harvest": (
                Disposition.WITHHELD,
                "its reap fires only against a champion below a share of "
                "maximum health, and the target never fell below it in this "
                "fight",
                (
                    "Dark Harvest's soul count is unknowable in one fight and "
                    "is priced at the souls the request declares.",
                ),
            ),
        }
    )
)


def _unpriced_receipts(name: str) -> tuple[str, ...]:
    """One keystone's no-row receipt, or none when it always books."""
    declaration = _UNPRICED_KEYSTONES.get(name)
    if declaration is None:
        return ()
    disposition, reason, disclosures = declaration
    return zero_receipts(name, ZeroPolicy(disposition, reason), disclosures)


def _compile_electrocute(entry: Mapping[str, Any]) -> RuneProcEffect:
    """Compile Electrocute: 3 stacks in 3s strike for leveled adaptive damage."""
    name = "Electrocute"
    effects = RuneValues(name, entry.get("effects", {}))
    base_by_level = required_leveling(name, effects)
    bonus_ad_ratio = effects.number("bonus_ad_ratio")
    ap_ratio = effects.number("ap_ratio")
    top = RuneValues(name, entry)

    def raw(inputs: DamageInputs) -> float:
        stats = inputs.champion_stats
        return (
            at_level(base_by_level, inputs.level)
            + bonus_ad_ratio * stats.get("bonus_attack_damage", 0.0)
            + ap_ratio * stats.get("ability_power", 0.0)
        )

    return RuneProcEffect(
        rune_name=name,
        breakdown_key=breakdown_key(name),
        display_name=display_name(name),
        stacks_required=int(effects.number("stacks_required")),
        stack_window_seconds=effects.number("stack_window_seconds"),
        cooldown_seconds=top.number("cooldown"),
        proc_delay_seconds=effects.number("proc_delay_seconds"),
        raw_damage=raw,
        damage_type=ratio_adaptive_type(bonus_ad_ratio, ap_ratio),
    )


def _compile_first_strike(entry: Mapping[str, Any]) -> RuneWindowAmpEffect:
    """Compile First Strike: 7% bonus true damage in a 3s opening window."""
    name = "First Strike"
    effects = RuneValues(name, entry.get("effects", {}))
    melee_ratio, ranged_ratio = required_pair(name, effects, "gold_conversion_ratios")
    return RuneWindowAmpEffect(
        rune_name=name,
        breakdown_key=breakdown_key(name),
        display_name=display_name(name),
        activation_gold=effects.number("flat_gold"),
        gold_conversion_melee=melee_ratio,
        gold_conversion_ranged=ranged_ratio,
    )


def _compile_press_the_attack(entry: Mapping[str, Any]) -> RuneProcAmpEffect:
    """Compile Press the Attack: 3 autos proc leveled damage plus a lasting amp."""
    name = "Press the Attack"
    effects = RuneValues(name, entry.get("effects", {}))
    base_by_level = required_leveling(name, effects)
    top = RuneValues(name, entry)

    def raw(inputs: DamageInputs) -> float:
        return at_level(base_by_level, inputs.level)

    return RuneProcAmpEffect(
        rune_name=name,
        breakdown_key=breakdown_key(name),
        display_name=display_name(name),
        stacks_required=int(effects.number("max_stacks")),
        stack_duration_seconds=effects.number("stack_duration_seconds"),
        cooldown_seconds=top.number("cooldown"),
        raw_damage=raw,
        damage_type=pure_adaptive_type,
    )


# Modeling assumption, not a wiki value: how far the average comet flies
# before landing. The wiki's damage table spans 0-750 units; 375 is a
# mid-range poke distance and sits exactly halfway up the table (+50%).
ARCANE_COMET_ASSUMED_TRAVEL_DISTANCE = 375.0


def _distance_amp_ratio(
    name: str, scaling: Mapping[str, Any], distance: float
) -> float:
    """Interpolate a distance-keyed percent table at one travel distance.

    The table's values are evenly spaced across ``distance_range``;
    distances beyond the span clamp to its ends.
    """
    values = [float(value) for value in scaling["values"]]
    span_start, span_end = (float(value) for value in scaling["distance_range"])
    if len(values) < 2 or span_end <= span_start:
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] distance_scaling is degenerate — "
            "wiki parse degraded; check rune_parser and data/runes.json"
        )
    fraction = min(1.0, max(0.0, (distance - span_start) / (span_end - span_start)))
    position = fraction * (len(values) - 1)
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    percent = values[lower] + (values[upper] - values[lower]) * (position - lower)
    return percent / 100.0


def _certify_comet_leveling_order(
    name: str,
    effects: "RuneValues",
    base_by_level: list[float],
    scaling: Mapping[str, Any],
) -> None:
    """Certify leveling[0] is the minimum-damage table, not the max-range one.

    The comet is the first rune with two level tables, chosen by sentence
    order — a reworded wiki description leading with the max-range table
    would silently double every proc. The wiki prices maximum-range damage
    at exactly (1 + full amp) × minimum, which also certifies folding one
    multiplier over base and ratios together.
    """
    leveling = effects.value("leveling")
    span_end = float(scaling["distance_range"][1])
    full_amp = _distance_amp_ratio(name, scaling, span_end)
    max_by_level = [float(value) for value in leveling[1]] if len(leveling) > 1 else []
    if len(max_by_level) != len(base_by_level) or any(
        abs(max_value - base_value * (1.0 + full_amp)) > 1e-6
        for base_value, max_value in zip(base_by_level, max_by_level)
    ):
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] leveling tables are not minimum then "
            "maximum-range damage (max = min × (1 + full amp)) — wiki parse "
            "degraded or description reordered; check data/runes.json"
        )


def _compile_arcane_comet(entry: Mapping[str, Any]) -> RuneAbilityProcEffect:
    """Compile Arcane Comet: ability casts hurl a leveled adaptive comet.

    The wiki prices the comet as a minimum-damage formula amplified by
    travel distance (up to +100% at 750 units); base and ratios grow
    together, so one multiplier at the assumed distance covers both.
    """
    name = "Arcane Comet"
    effects = RuneValues(name, entry.get("effects", {}))
    base_by_level = required_leveling(name, effects)
    bonus_ad_ratio = effects.number("bonus_ad_ratio")
    ap_ratio = effects.number("ap_ratio")
    scaling = effects.value("distance_scaling")
    amp_ratio = _distance_amp_ratio(name, scaling, ARCANE_COMET_ASSUMED_TRAVEL_DISTANCE)
    _certify_comet_leveling_order(name, effects, base_by_level, scaling)

    def raw(inputs: DamageInputs) -> float:
        stats = inputs.champion_stats
        return (
            at_level(base_by_level, inputs.level)
            + bonus_ad_ratio * stats.get("bonus_attack_damage", 0.0)
            + ap_ratio * stats.get("ability_power", 0.0)
        ) * (1.0 + amp_ratio)

    return RuneAbilityProcEffect(
        rune_name=name,
        breakdown_key=breakdown_key(name),
        display_name=display_name(name),
        cooldown_by_level=required_cooldown_by_level(name, entry),
        proc_delay_seconds=effects.number("proc_delay_seconds"),
        assumed_travel_distance=ARCANE_COMET_ASSUMED_TRAVEL_DISTANCE,
        distance_amp_ratio=amp_ratio,
        raw_damage=raw,
        damage_type=ratio_adaptive_type(bonus_ad_ratio, ap_ratio),
    )


def _compile_summon_aery(entry: Mapping[str, Any]) -> KeystoneAeryEffect:
    """Compile Summon Aery's sourced damage and shielding tables."""
    name = "Summon Aery"
    effects = RuneValues(name, entry.get("effects", {}))
    leveling = effects.value("leveling")
    if not isinstance(leveling, list) or len(leveling) < 2:
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] leveling must contain damage and shield "
            "tables — wiki parse degraded; check rune_parser and data/runes.json"
        )
    damage_by_level = tuple(float(value) for value in leveling[0])
    shield_by_level = tuple(float(value) for value in leveling[1])
    if len(damage_by_level) < 20 or len(shield_by_level) < 20:
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] leveling tables must cover 20 levels — "
            "wiki parse degraded; check rune_parser and data/runes.json"
        )
    bonus_ad_ratio = effects.number("bonus_ad_ratio")
    ap_ratio = effects.number("ap_ratio")

    return KeystoneAeryEffect(
        rune_name=name,
        breakdown_key=breakdown_key(name),
        display_name=display_name(name),
        damage_by_level=damage_by_level,
        shield_by_level=shield_by_level,
        bonus_ad_ratio=bonus_ad_ratio,
        ap_ratio=ap_ratio,
        damage_flight_seconds=effects.number("damage_flight_seconds"),
        shield_flight_seconds=effects.number("shield_flight_seconds"),
        shield_duration_seconds=effects.number("shield_duration_seconds"),
        linger_seconds=effects.number("linger_seconds"),
        damage_type=ratio_adaptive_type(bonus_ad_ratio, ap_ratio),
    )


def _compile_guardian(entry: Mapping[str, Any]) -> KeystoneGuardianEffect:
    """Compile Guardian's threshold, paired shield, and cooldown tables."""
    name = "Guardian"
    effects = RuneValues(name, entry.get("effects", {}))
    leveling = effects.value("leveling")
    if not isinstance(leveling, list) or len(leveling) < 2:
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] leveling must contain threshold and shield "
            "tables — wiki parse degraded; check rune_parser and data/runes.json"
        )
    threshold_by_level = tuple(float(value) for value in leveling[0])
    shield_by_level = tuple(float(value) for value in leveling[1])
    if len(threshold_by_level) < 20 or len(shield_by_level) < 20:
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] leveling tables must cover 20 levels — "
            "wiki parse degraded; check rune_parser and data/runes.json"
        )
    return KeystoneGuardianEffect(
        rune_name=name,
        breakdown_key=breakdown_key(name),
        display_name=display_name(name),
        threshold_by_level=threshold_by_level,
        shield_by_level=shield_by_level,
        cooldown_by_level=required_cooldown_by_level(name, entry),
        ap_ratio=effects.number("ap_ratio"),
        bonus_health_ratio=effects.number("bonus_health_ratio"),
        trigger_window_seconds=effects.number("trigger_window_seconds"),
        unpriced_receipts=_unpriced_receipts(name),
        shield_duration_seconds=effects.number("shield_duration_seconds"),
    )


def _compile_aftershock(entry: Mapping[str, Any]) -> KeystoneAftershockEffect:
    """Compile Aftershock's resistance cap and delayed shockwave tables."""
    name = "Aftershock"
    effects = RuneValues(name, entry.get("effects", {}))
    leveling = effects.value("leveling")
    if not isinstance(leveling, list) or len(leveling) < 2:
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] leveling must contain resistance cap and "
            "shockwave tables — wiki parse degraded; check rune_parser and "
            "data/runes.json"
        )
    cap_by_level = tuple(float(value) for value in leveling[0])
    shockwave_by_level = tuple(float(value) for value in leveling[1])
    if len(cap_by_level) < 20 or len(shockwave_by_level) < 20:
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] leveling tables must cover 20 levels — "
            "wiki parse degraded; check rune_parser and data/runes.json"
        )
    return KeystoneAftershockEffect(
        rune_name=name,
        breakdown_key=breakdown_key(name),
        display_name=display_name(name),
        resistance_cap_by_level=cap_by_level,
        shockwave_damage_by_level=shockwave_by_level,
        cooldown_seconds=RuneValues(name, entry).number("cooldown"),
        flat_armor=effects.number("flat_armor"),
        flat_magic_resistance=effects.number("flat_magic_resistance"),
        bonus_armor_ratio=effects.number("bonus_armor_ratio"),
        bonus_magic_resistance_ratio=effects.number("bonus_magic_resistance_ratio"),
        bonus_health_ratio=effects.number("bonus_health_ratio"),
        duration_seconds=effects.number("resistance_duration_seconds"),
        shockwave_radius=effects.number("shockwave_radius"),
        unpriced_receipts=_unpriced_receipts(name),
    )


def _compile_grasp(entry: Mapping[str, Any]) -> KeystoneGraspEffect:
    """Compile Grasp's timed stacks and maximum-health attack rider."""
    name = "Grasp of the Undying"
    effects = RuneValues(name, entry.get("effects", {}))
    return KeystoneGraspEffect(
        rune_name=name,
        breakdown_key=breakdown_key(name),
        display_name=display_name(name),
        damage_melee_ranged_ratios=required_pair(
            name, effects, "grasp_damage_melee_ranged_ratios"
        ),
        heal_melee_ranged_ratios=required_pair(
            name, effects, "grasp_heal_melee_ranged_ratios"
        ),
        bonus_health_melee_ranged=required_pair(
            name, effects, "grasp_bonus_health_melee_ranged"
        ),
        stack_cadence_seconds=effects.number("combat_stack_cadence_seconds"),
        stack_generation_seconds=effects.number("combat_stack_generation_seconds"),
        max_stacks=int(effects.number("max_stacks")),
        ready_window_seconds=effects.number("ready_window_seconds"),
    )


def _compile_hail_of_blades(entry: Mapping[str, Any]) -> KeystoneHailOfBladesEffect:
    """Compile Hail of Blades' sourced temporary swing window."""
    name = "Hail of Blades"
    effects = RuneValues(name, entry.get("effects", {}))
    return KeystoneHailOfBladesEffect(
        rune_name=name,
        breakdown_key=breakdown_key(name),
        display_name=display_name(name),
        damage_by_level=tuple(required_leveling(name, effects)),
        bonus_ad_ratio=effects.number("bonus_ad_ratio"),
        ap_ratio=effects.number("ap_ratio"),
        bonus_attack_speed_melee_ranged=required_pair(
            name, effects, "hail_bonus_attack_speed_melee_ranged"
        ),
        initial_stacks=int(effects.number("hail_initial_stacks")),
        stack_duration_seconds=effects.number("hail_stack_duration_seconds"),
        reset_stack_limit=int(effects.number("hail_reset_stack_limit")),
        cooldown_seconds=RuneValues(name, entry).number("cooldown"),
    )


def _compile_lethal_tempo(entry: Mapping[str, Any]) -> KeystoneLethalTempoEffect:
    """Compile Lethal Tempo's stacked attack schedule and bolt tables."""
    name = "Lethal Tempo"
    effects = RuneValues(name, entry.get("effects", {}))

    def level_table(key: str) -> tuple[float, ...]:
        values = effects.value(key)
        if not isinstance(values, list) or len(values) < 20:
            raise KeyError(
                f"RUNE_EFFECTS[{name!r}] {key!r} must cover 20 levels — "
                "wiki parse degraded; check rune_parser and data/runes.json"
            )
        return tuple(float(value) for value in values)

    def adaptive_type(stats: Mapping[str, float]) -> str:
        return (
            "physical"
            if stats.get("bonus_attack_damage", 0.0) > stats.get("ability_power", 0.0)
            else "magic"
        )

    return KeystoneLethalTempoEffect(
        rune_name=name,
        breakdown_key=breakdown_key(name),
        display_name=display_name(name),
        bolt_damage_melee_by_level=level_table(
            "lethal_tempo_bolt_damage_melee_by_level"
        ),
        bolt_damage_ranged_by_level=level_table(
            "lethal_tempo_bolt_damage_ranged_by_level"
        ),
        attack_speed_percent_melee_ranged=required_pair(
            name, effects, "lethal_tempo_attack_speed_percent_melee_ranged"
        ),
        bolt_damage_increase_ratio_melee_ranged=required_pair(
            name, effects, "lethal_tempo_bolt_damage_increase_ratio_melee_ranged"
        ),
        max_stacks=int(effects.number("max_stacks")),
        stack_duration_seconds=effects.number("lethal_tempo_stack_duration_seconds"),
        expiry_step_seconds=effects.number("lethal_tempo_expiry_step_seconds"),
        damage_type=adaptive_type,
    )


def _compile_glacial(entry: Mapping[str, Any]) -> KeystoneGlacialEffect:
    """Compile Glacial Augment's sourced zone and reduction values."""
    name = "Glacial Augment"
    effects = RuneValues(name, entry.get("effects", {}))
    return KeystoneGlacialEffect(
        rune_name=name,
        breakdown_key=breakdown_key(name),
        display_name=display_name(name),
        cooldown_seconds=RuneValues(name, entry).number("cooldown"),
        ray_count=int(effects.number("glacial_ray_count")),
        zone_radius_units=effects.number("glacial_zone_radius_units"),
        zone_width_units=effects.number("glacial_zone_width_units"),
        zone_base_duration_seconds=effects.number("glacial_zone_base_duration_seconds"),
        zone_duration_cc_ratio=effects.number("glacial_zone_duration_cc_ratio"),
        slow_base_ratio=effects.number("glacial_slow_base_ratio"),
        slow_bonus_ad_ratio_per_100=effects.number(
            "glacial_slow_bonus_ad_ratio_per_100"
        ),
        slow_ap_ratio_per_100=effects.number("glacial_slow_ap_ratio_per_100"),
        slow_heal_shield_ratio_per_10=effects.number(
            "glacial_slow_heal_shield_ratio_per_10"
        ),
        damage_reduction_ratio=effects.number("glacial_damage_reduction_ratio"),
        unpriced_receipts=_unpriced_receipts(name),
    )


def _compile_stormraider(entry: Mapping[str, Any]) -> KeystoneStormraiderEffect:
    """Compile Stormraider's sourced threshold and movement burst."""
    name = "Stormraider's Surge"
    effects = RuneValues(name, entry.get("effects", {}))
    return KeystoneStormraiderEffect(
        rune_name=name,
        breakdown_key=breakdown_key(name),
        display_name=display_name(name),
        cooldown_by_level=required_cooldown_by_level(name, entry),
        damage_threshold_ratio=effects.number("stormraider_damage_threshold_ratio"),
        damage_window_seconds=effects.number("stormraider_damage_window_seconds"),
        bonus_move_speed_melee_ranged=required_pair(
            name, effects, "stormraider_bonus_move_speed_melee_ranged"
        ),
        slow_resist_ratio=effects.number("stormraider_slow_resist_ratio"),
        unpriced_receipts=_unpriced_receipts(name),
        duration_seconds=effects.number("stormraider_duration_seconds"),
    )


def _compile_fleet(entry: Mapping[str, Any]) -> KeystoneFleetEffect:
    """Compile Fleet Footwork's sourced heal and Energized window."""
    name = "Fleet Footwork"
    effects = RuneValues(name, entry.get("effects", {}))

    def level_table(key: str) -> tuple[float, ...]:
        values = effects.value(key)
        if not isinstance(values, list) or len(values) < 20:
            raise KeyError(
                f"RUNE_EFFECTS[{name!r}] {key!r} must cover 20 levels — "
                "wiki parse degraded; check rune_parser and data/runes.json"
            )
        return tuple(float(value) for value in values)

    return KeystoneFleetEffect(
        rune_name=name,
        breakdown_key=breakdown_key(name),
        display_name=display_name(name),
        heal_melee_by_level=level_table("fleet_heal_melee_by_level"),
        heal_ranged_by_level=level_table("fleet_heal_ranged_by_level"),
        bonus_ad_ratio_melee_ranged=required_pair(
            name, effects, "fleet_bonus_ad_ratio_melee_ranged"
        ),
        ap_ratio_melee_ranged=required_pair(
            name, effects, "fleet_ap_ratio_melee_ranged"
        ),
        bonus_move_speed_melee_ranged=required_pair(
            name, effects, "fleet_bonus_move_speed_melee_ranged"
        ),
        minion_heal_effectiveness=effects.number("fleet_minion_heal_effectiveness"),
        charge_cap=int(effects.number("fleet_charge_cap")),
        move_speed_duration_seconds=effects.number("fleet_move_speed_duration_seconds"),
    )


def _compile_conqueror(entry: Mapping[str, Any]) -> KeystoneConquerorEffect:
    """Compile Conqueror's adaptive-force stack and healing receipts."""
    name = "Conqueror"
    effects = RuneValues(name, entry.get("effects", {}))

    def level_table(key: str) -> tuple[float, ...]:
        values = effects.value(key)
        if not isinstance(values, list) or len(values) < 20:
            raise KeyError(
                f"RUNE_EFFECTS[{name!r}] {key!r} must cover 20 levels — "
                "wiki parse degraded; check rune_parser and data/runes.json"
            )
        return tuple(float(value) for value in values)

    return KeystoneConquerorEffect(
        rune_name=name,
        breakdown_key=breakdown_key(name),
        display_name=display_name(name),
        adaptive_force_by_level=level_table("conqueror_adaptive_force_by_level"),
        adaptive_force_max_by_level=level_table(
            "conqueror_adaptive_force_max_by_level"
        ),
        max_stacks=int(effects.number("max_stacks")),
        stacks_per_application=int(effects.number("conqueror_stacks_per_application")),
        stack_duration_seconds=effects.number("conqueror_stack_duration_seconds"),
        cast_instance_interval_seconds=effects.number(
            "conqueror_cast_instance_interval_seconds"
        ),
        heal_melee_ranged_ratios=required_pair(
            name, effects, "conqueror_heal_melee_ranged_ratios"
        ),
    )


def _compile_deathfire(entry: Mapping[str, Any]) -> KeystoneDeathfireEffect:
    """Compile Deathfire Touch's typed burn tables and durations."""
    name = "Deathfire Touch"
    effects = RuneValues(name, entry.get("effects", {}))

    leveling = effects.value("leveling")
    if not isinstance(leveling, list) or len(leveling) < 2:
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] 'leveling' must contain base and amplified "
            "20-level burn tables — wiki parse degraded; check rune_parser and "
            "data/runes.json"
        )
    tables: list[tuple[float, ...]] = []
    for index, values in enumerate(leveling[:2]):
        if not isinstance(values, list) or len(values) < 20:
            raise KeyError(
                f"RUNE_EFFECTS[{name!r}] 'leveling[{index}]' must cover 20 levels "
                "— wiki parse degraded; check rune_parser and data/runes.json"
            )
        tables.append(tuple(float(value) for value in values))

    duration_values = effects.value("deathfire_duration_seconds")
    if not isinstance(duration_values, Mapping):
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] is missing typed burn duration categories "
            "— wiki parse degraded; check rune_parser and data/runes.json"
        )
    required_categories = (
        "spell_damage",
        "area_damage",
        "persistent_damage",
        "persistent_area_damage",
        "pet_damage",
    )
    durations: dict[str, float] = {}
    for category in required_categories:
        if category not in duration_values:
            raise KeyError(
                f"RUNE_EFFECTS[{name!r}] is missing burn duration {category!r} "
                "— wiki parse degraded; check rune_parser and data/runes.json"
            )
        durations[category] = float(duration_values[category])

    return KeystoneDeathfireEffect(
        rune_name=name,
        breakdown_key=breakdown_key(name),
        display_name=display_name(name),
        damage_by_level=tables[0],
        amplified_damage_by_level=tables[1],
        bonus_ad_ratios_by_state=required_pair(
            name, effects, "deathfire_bonus_ad_ratios_by_state"
        ),
        ap_ratios_by_state=required_pair(name, effects, "deathfire_ap_ratios_by_state"),
        tick_interval_seconds=effects.number("deathfire_tick_interval_seconds"),
        amp_delay_seconds=effects.number("deathfire_amp_delay_seconds"),
        amp_ratio=effects.number("deathfire_amp_ratio"),
        duration_by_category=durations,
    )


def _compile_dark_harvest(entry: Mapping[str, Any]) -> KeystoneDarkHarvestEffect:
    """Compile Dark Harvest's sourced threshold and Soul damage formula."""
    name = "Dark Harvest"
    effects = RuneValues(name, entry.get("effects", {}))
    top = RuneValues(name, entry)
    bonus_ad_ratio = effects.number("bonus_ad_ratio")
    ap_ratio = effects.number("ap_ratio")
    return KeystoneDarkHarvestEffect(
        rune_name=name,
        breakdown_key=breakdown_key(name),
        display_name=display_name(name),
        cooldown_seconds=top.number("cooldown"),
        health_threshold_ratio=effects.number("health_threshold_ratio"),
        base_damage=effects.number("base_damage"),
        soul_damage=effects.number("soul_damage"),
        bonus_ad_ratio=bonus_ad_ratio,
        ap_ratio=ap_ratio,
        proc_delay_seconds=effects.number("proc_delay_seconds"),
        takedown_reset_seconds=effects.number("takedown_reset_seconds"),
        unpriced_receipts=_unpriced_receipts(name),
        damage_type=ratio_adaptive_type(bonus_ad_ratio, ap_ratio),
    )


# The keystones that book no damage: disposition, the reason that becomes
# the receipt, and any further half this engine refuses. A table rather than
# a compiler each, because these differ only in their words — and a
# difference that is only words belongs in a table beside its reader, which
# is what ``_KEYSTONE_COMPILERS`` itself is.
_NO_DAMAGE_KEYSTONES: Mapping[str, tuple[Disposition, str, tuple[str, ...]]] = {
    "Unsealed Spellbook": (
        Disposition.STRUCTURAL_ZERO,
        "it swaps summoner spells out of combat: the holder picks the "
        "equipped and swapped spells, each summoner spell has its own "
        "effect, and no source states a combat number for the rune itself",
        (),
    ),
}


def no_damage_compiler(
    name: str,
    disposition: Disposition,
    reason: str,
    disclosures: tuple[str, ...] = (),
) -> Callable[[Mapping[str, Any]], RuneNoDamageEffect]:
    """The compiler for one damageless rune, from its declaration.

    Public because a path module's damageless runes are the same shape as
    the keystone table's: they differ only in their words, and a difference
    that is only words belongs in a table beside its reader rather than in
    a hand-written compiler per rune.
    """

    def compile_declared(entry: Mapping[str, Any]) -> RuneNoDamageEffect:
        del entry  # the declaration is the whole compilation
        return RuneNoDamageEffect(
            rune_name=name,
            zero_policy=ZeroPolicy(disposition, reason),
            disclosures=disclosures,
        )

    return compile_declared


# The compiled keystone roster. Every name in ``data/runes.json`` not listed
# here fails closed in :func:`resolve_rune` with a named reason.
_KEYSTONE_COMPILERS: dict[str, Callable[[Mapping[str, Any]], RuneEffect]] = {
    "Electrocute": _compile_electrocute,
    "First Strike": _compile_first_strike,
    "Press the Attack": _compile_press_the_attack,
    "Arcane Comet": _compile_arcane_comet,
    "Summon Aery": _compile_summon_aery,
    "Guardian": _compile_guardian,
    "Aftershock": _compile_aftershock,
    "Grasp of the Undying": _compile_grasp,
    "Hail of Blades": _compile_hail_of_blades,
    "Lethal Tempo": _compile_lethal_tempo,
    "Glacial Augment": _compile_glacial,
    "Stormraider's Surge": _compile_stormraider,
    "Fleet Footwork": _compile_fleet,
    "Conqueror": _compile_conqueror,
    "Deathfire Touch": _compile_deathfire,
    "Dark Harvest": _compile_dark_harvest,
    **{
        name: no_damage_compiler(name, *declaration)
        for name, declaration in _NO_DAMAGE_KEYSTONES.items()
    },
}


@cache
def _compilers() -> Mapping[str, Callable[[Mapping[str, Any]], RuneEffect]]:
    """Every rune compiler: the keystones here, the minor runes per path.

    Built once, on first use rather than at import, because the path modules
    import this one for the vocabulary they compile into. The result is
    compiler *functions*, which no data refresh can invalidate — the numbers
    they read are looked up when a rune resolves, not when it registers.
    """
    # Local import: rune_paths compiles into this module's vocabulary, so it
    # cannot be imported while this module is still executing.
    from .rune_paths import path_compilers  # pylint: disable=import-outside-toplevel

    merged: dict[str, Callable[[Mapping[str, Any]], RuneEffect]] = dict(
        _KEYSTONE_COMPILERS
    )
    for name, compiler in path_compilers().items():
        if name in merged:
            raise ValueError(
                f"Rune {name!r} has two compilers; a rune is compiled by "
                "exactly one path module or by the keystone table"
            )
        merged[name] = compiler
    return MappingProxyType(merged)


@cache
def _shard_compilers() -> Mapping[tuple[int, str], Callable[[Mapping], RuneEffect]]:
    """Every stat-shard compiler, keyed by the (row, name) that selects it."""
    # Local import, for the same reason as the rune compilers above.
    from .rune_paths import shard_compilers  # pylint: disable=import-outside-toplevel

    return shard_compilers()


def resolve_rune(name: str) -> RuneEffect | None:
    """Compile one selected rune, failing closed on anything unmodeled."""
    if not name:
        return None
    entry = RUNE_EFFECTS.get(name)
    if entry is None:
        raise ValueError(f"Unknown rune {name!r}")
    compiler = _compilers().get(name)
    if compiler is None:
        raise ValueError(
            f"Rune {name!r} is not modeled yet; its numbers would be "
            "estimates. Choose an implemented rune or none."
        )
    return compiler(entry)


def resolve_keystone(name: str) -> RuneEffect | None:
    """Compile the selected keystone alone — the page's row-0 rune, by name.

    A keystone is a rune, so this is :func:`resolve_rune` restricted to the
    keystone row: the roster is what says which row a name sits in, and a
    caller asking for a keystone gets a refusal rather than a minor rune.
    """
    if name and _rune_row(name) != KEYSTONE_ROW:
        raise ValueError(f"Rune {name!r} is not a keystone")
    return resolve_rune(name)


def resolve_shard(row: int, name: str) -> RuneEffect | None:
    """Compile one selected stat shard, failing closed on anything unmodeled."""
    if not name:
        return None
    compiler = _shard_compilers().get((row, name))
    if compiler is None:
        raise ValueError(
            f"Stat shard {name!r} in row {row} is not modeled yet; its "
            "numbers would be estimates. Choose an implemented shard or none."
        )
    return compiler(_shard_option(row, name))


def _shard_option(row: int, name: str) -> Mapping[str, Any]:
    """The cached record for one shard option, or a loud failure."""
    for option in _shard_row_options(row):
        if option.get("name") == name:
            return option
    raise ValueError(f"Stat shard row {row} offers no option named {name!r}")


def _shard_row_options(row: int) -> list[Mapping[str, Any]]:
    """The cached options of one shard row, in the page's order."""
    return list(_shard_row(row).get("options", ()))


def shard_row_name(row: int) -> str:
    """The Rune page's own name for one shard row — Offense, Flex, Defense.

    Public because a shard names itself by row *and* option: the same
    option appears in two rows and a compiled shard has to say which one it
    is, in the page's words rather than a second set invented here.
    """
    return str(RuneValues(f"stat shard row {row}", _shard_row(row)).value("name"))


def _shard_row(row: int) -> Mapping[str, Any]:
    """The cached slot for one shard row, or an empty one if uncached."""
    for slot in RUNE_SHARDS.get("slots", ()):
        if int(slot.get("row", 0)) == row:
            return slot
    return {}


# The Rune page states the page's own shape: "The primary path has one
# keystone and three lesser runes. The secondary path has two lesser runes.
# There are also three Shard slots."  The primary allowance and the shard
# row count are derived from the cached roster below; the secondary
# allowance is the one number only that sentence states.
SECONDARY_PATH_MINORS = 2
#: Row 0 of a path is its keystone row; rows 1 and up are the minor slots.
KEYSTONE_ROW = 0


@dataclass(frozen=True, slots=True)
class RunePage:
    """One validated rune page: a keystone, its minor runes, its shards.

    ``stat_shards`` is positional — entry *i* is the choice for shard row
    *i + 1*, and an empty string is an empty slot — because the page offers
    three fixed rows and the same shard name appears in two of them.
    """

    keystone: str = ""
    minor_runes: tuple[str, ...] = ()
    stat_shards: tuple[str, ...] = ()
    options: Mapping[str, Mapping[str, float]] = MappingProxyType({})

    @property
    def rune_names(self) -> tuple[str, ...]:
        """Every selected rune, keystone first."""
        return ((self.keystone,) if self.keystone else ()) + self.minor_runes


def _rune_path(name: str) -> str:
    """One rune's path, or a refusal naming the rune the roster lacks.

    A missing path is never defaulted: an empty one would group every
    path-less rune under a single phantom path and quietly pass the
    two-path rule.
    """
    entry = RUNE_EFFECTS.get(name)
    if entry is None:
        raise ValueError(f"Unknown rune {name!r}")
    path = entry.get("path")
    if not path:
        raise KeyError(f"RUNE_EFFECTS[{name!r}] states no path — wiki parse degraded")
    return str(path)


def _minor_rows() -> tuple[int, ...]:
    """The minor-rune rows the roster offers, in order."""
    rows = {
        int(entry.get("row", KEYSTONE_ROW))
        for entry in RUNE_EFFECTS.values()
        if int(entry.get("row", KEYSTONE_ROW)) != KEYSTONE_ROW
    }
    return tuple(sorted(rows))


def _shard_rows() -> tuple[int, ...]:
    """The shard rows the cached table offers, in the page's order."""
    return tuple(int(slot.get("row", 0)) for slot in RUNE_SHARDS.get("slots", ()))


def _name_list(value: Any, field: str, limit: int, *, positional: bool) -> list[str]:
    """Coerce one request list of rune names through the shared list policy.

    ``request_parsing`` owns what a public list may be; the two shapes it
    offers are exactly the two the page needs — a set of distinct names for
    the minor runes, and a positional list for the shards, whose empty
    entries are empty slots and whose repeats are legal.
    """
    reader = request_positional_string_list if positional else request_string_list
    return reader({field: [] if value is None else value}, field, maximum=limit)


def validate_rune_page(
    keystone: Any = "",
    minor_runes: Any = None,
    stat_shards: Any = None,
    rune_options: Any = None,
) -> RunePage:
    """Validate one requested rune page, or refuse it naming the rule broken.

    Every rule the game enforces on a page is enforced here, and every
    refusal says which one: a name the roster does not carry, a rune the
    engine does not model, the same rune twice, two runes in one row, more
    than the primary path's three or a second path's two, a shard row's
    option that is not in that row, or an option for a rune not selected.
    """
    name = _validated_keystone(keystone)
    minors = _validated_minor_runes(minor_runes)
    _certify_path_shape(name, minors)
    # Modeling last, and deliberately: a page that breaks a rule of the game
    # should hear which rule, not which of its runes this engine has yet to
    # compile.  Every name here is already known and legally placed.
    for rune in (name, *minors):
        resolve_rune(rune)
    shards = _validated_stat_shards(stat_shards)
    page = RunePage(name, minors, shards)
    return RunePage(name, minors, shards, _validated_rune_options(rune_options, page))


def _validated_keystone(value: Any) -> str:
    """Parse the request's keystone field: a known rune from a keystone row."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("keystone must be a string")
    name = value.strip()
    if not name:
        return ""
    if _rune_row(name) != KEYSTONE_ROW:
        raise ValueError(
            f"{name!r} is a minor rune, not a keystone; it belongs in " "minor_runes"
        )
    return name


def validate_keystone_request(value: Any) -> str:
    """Parse a request's keystone field on its own, without a whole page.

    The page validator is the fuller door; this is the same check for a
    caller that carries only the keystone name.
    """
    name = _validated_keystone(value)
    if name:
        resolve_rune(name)
    return name


def keystone_input_options_meta() -> dict[str, dict[str, Any]]:
    """Return typed state controls for keystones with explicit inputs."""
    options: dict[str, dict[str, Any]] = {}
    fleet = resolve_keystone("Fleet Footwork")
    if isinstance(fleet, KeystoneFleetEffect):
        options["Fleet Footwork"] = {
            "options": {
                "starting_charges": {
                    "type": "int",
                    "default": 0,
                    "min": 0,
                    "max": fleet.charge_cap,
                    "label": "Starting Fleet charges",
                    "description": (
                        "Charges held before the fight window. Use the cap "
                        "when the first attack starts Energized."
                    ),
                }
            }
        }
    conqueror = resolve_keystone("Conqueror")
    if isinstance(conqueror, KeystoneConquerorEffect):
        options["Conqueror"] = {
            "options": {
                "starting_stacks": {
                    "type": "int",
                    "default": 0,
                    "min": 0,
                    "max": conqueror.max_stacks,
                    "label": "Starting Conqueror stacks",
                    "description": (
                        "Stacks held before the fight window. They expire "
                        f"after {conqueror.stack_duration_seconds:g}s without damage."
                    ),
                }
            }
        }
    return options


def validate_keystone_options(value: Any, rune_name: str) -> dict[str, int | float]:
    """Validate the selected keystone's explicit state inputs."""
    if value is None:
        value = {}
    if not isinstance(value, Mapping):
        raise ValueError("keystone_options must be an object")
    schemas = keystone_input_options_meta().get(rune_name, {}).get("options", {})
    unknown_options = set(value) - set(schemas)
    if unknown_options:
        raise ValueError(
            f"Unknown option for {rune_name or 'keystone'}: "
            f"{sorted(unknown_options)[0]}"
        )
    parsed: dict[str, int | float] = {}
    for option_name, option in schemas.items():
        supplied = value.get(option_name, option["default"])
        if option["type"] == "int" and (
            isinstance(supplied, bool) or not isinstance(supplied, int)
        ):
            raise ValueError(f"keystone_options.{option_name} must be an integer")
        if not option["min"] <= supplied <= option["max"]:
            raise ValueError(
                f"keystone_options.{option_name} must be between "
                f"{option['min']} and {option['max']}"
            )
        parsed[option_name] = supplied
    return parsed


def _rune_row(name: str) -> int:
    """One rune's roster row, or a refusal naming the rune the roster lacks."""
    entry = RUNE_EFFECTS.get(name)
    if entry is None:
        raise ValueError(f"Unknown rune {name!r}")
    return int(entry.get("row", KEYSTONE_ROW))


def _validated_minor_runes(value: Any) -> tuple[str, ...]:
    """Parse the minor-rune list: known, distinct, minor, one per row."""
    rows = _minor_rows()
    requested = _name_list(
        value, "minor_runes", len(rows) + SECONDARY_PATH_MINORS, positional=False
    )
    claimed: dict[tuple[str, int], str] = {}
    for name in requested:
        row = _rune_row(name)
        if row == KEYSTONE_ROW:
            raise ValueError(
                f"{name!r} is a keystone, not a minor rune; it belongs in "
                "the keystone field"
            )
        path = _rune_path(name)
        held = claimed.get((path, row))
        if held is not None:
            raise ValueError(
                f"a rune page takes one rune per row: {held!r} and {name!r} "
                f"are both in {path} row {row}"
            )
        claimed[(path, row)] = name
    return tuple(requested)


def _certify_path_shape(keystone: str, minors: Sequence[str]) -> None:
    """Certify the two-path shape: three from the primary, two from a second."""
    counts: dict[str, int] = {}
    for name in minors:
        path = _rune_path(name)
        counts[path] = counts.get(path, 0) + 1
    if not counts:
        # No minors, no shape to certify — and no reason to ask a keystone
        # for a path nothing is being measured against.
        return
    primary = _primary_path(keystone, counts)
    if len([path for path in counts if path != primary]) > 1:
        drawn = ", ".join(sorted(counts))
        raise ValueError(
            "a rune page draws from two paths; these minor runes come from "
            + drawn
            + (f", and the keystone's path is {primary}" if keystone else "")
        )
    primary_limit = len(_minor_rows())
    for path, count in sorted(counts.items()):
        limit = primary_limit if path == primary else SECONDARY_PATH_MINORS
        if count > limit:
            role = "primary" if path == primary else "secondary"
            raise ValueError(
                f"a rune page takes at most {limit} minor runes from its "
                f"{role} path; {count} came from {path}"
            )


def _primary_path(keystone: str, counts: Mapping[str, int]) -> str:
    """Which path holds the three minor slots.

    The keystone's path when one is selected — that is the rule a page with
    a keystone lives by. Without a keystone the page has no declared primary,
    so the path holding the most minors is treated as it, which refuses
    exactly the shapes no primary could make legal.
    """
    if keystone:
        return _rune_path(keystone)
    return max(sorted(counts), key=lambda path: counts[path], default="")


def _validated_stat_shards(value: Any) -> tuple[str, ...]:
    """Parse the positional shard list: one option per row, in row order."""
    rows = _shard_rows()
    requested = tuple(_name_list(value, "stat_shards", len(rows), positional=True))
    if any(requested) and not rows:
        raise ValueError(
            "the cached stat-shard table is unavailable, so no shard can be "
            "selected; re-run the data update"
        )
    for index, name in enumerate(requested):
        if not name:
            continue
        row = rows[index]
        options = [str(option.get("name")) for option in _shard_row_options(row)]
        if name not in options:
            raise ValueError(
                f"stat_shards[{index}] names shard row {row}, which offers "
                + ", ".join(repr(option) for option in options)
                + f" — not {name!r}"
            )
        resolve_shard(row, name)
    return requested


def _validated_rune_options(value: Any, page: RunePage) -> dict[str, dict[str, float]]:
    """Validate requested rune options against what the page's runes declare.

    Shaped like ``item_options``: one entry per rune, one value per declared
    option key. An option for a rune the page does not select, or a key the
    rune does not declare, is refused rather than ignored — a silently
    dropped option is a number the caller thinks it set.
    """
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("rune_options must be an object")
    # Local import, for the same reason as the rune compilers above.
    from .rune_paths import path_options  # pylint: disable=import-outside-toplevel

    declared = path_options()
    selected = set(page.rune_names)
    resolved: dict[str, dict[str, float]] = {}
    for rune, options in value.items():
        if not isinstance(rune, str) or rune not in selected:
            raise ValueError(
                f"rune_options names {rune!r}, which this rune page does not select"
            )
        if not isinstance(options, Mapping):
            raise ValueError(f"rune_options[{rune!r}] must be an object")
        by_key = {option.key: option for option in declared.get(rune, ())}
        entry: dict[str, float] = {}
        for key, raw in options.items():
            option = by_key.get(str(key))
            if option is None:
                raise ValueError(f"rune {rune!r} declares no option {key!r}")
            entry[option.key] = option.validated(raw)
        if entry:
            resolved[rune] = entry
    return resolved


def resolve_rune_page(page: RunePage) -> tuple[RuneEffect, ...]:
    """Compile every rune and shard a validated page selects, keystone first."""
    effects = [resolve_rune(name) for name in page.rune_names]
    rows = _shard_rows()
    for index, name in enumerate(page.stat_shards):
        if name:
            effects.append(resolve_shard(rows[index], name))
    return tuple(effect for effect in effects if effect is not None)


def adaptive_force_attack_damage_ratio() -> float:
    """What one point of adaptive force is worth in bonus attack damage."""
    return RuneValues("adaptive force", ADAPTIVE_FORCE).number("attack_damage_ratio")


def adaptive_force_split(
    force: float, bonus_attack_damage: float, ability_power: float
) -> tuple[float, float]:
    """Split one adaptive-force grant into (bonus attack damage, ability power).

    The larger of the build's bonus attack damage and ability power decides,
    and a tie takes attack damage: the runes state "Grants bonuses based on
    which stat you already have the most bonuses for. *Defaults to the first
    listed*", and ``Template:Adaptive`` lists attack damage first. (Adaptive
    *damage* defaults the other way — see :func:`pure_adaptive_type` — which
    is why the two rules are separate functions.)
    """
    if ability_power > bonus_attack_damage:
        return 0.0, force
    return force * adaptive_force_attack_damage_ratio(), 0.0


@dataclass(frozen=True, slots=True)
class RuneStatGrants:
    """What one rune page adds to the holder's stats, by channel.

    Named fields rather than a mapping so ``stats.py`` reads each grant
    where that stat belongs — rune adaptive force is bonus attack damage
    for Rabadon's and for the ability ratios, and is *not* a permanent item
    stat for Kai'Sa's evolutions, which a single lump added to the item
    totals could not express.  Every field is zero for a page with no stat
    runes, so a request without runes stays bit-identical.
    """

    bonus_attack_damage: float = 0.0
    ability_power: float = 0.0
    attack_speed_percent: float = 0.0
    ability_haste: float = 0.0
    basic_ability_haste: float = 0.0
    #: Neutral as ``int`` zero, not ``0.0``, and that is load-bearing: the
    #: item side of this one stat sums *terms* (``item_effects``'s declared
    #: sibling read), so a build holding no registry item totals to ``int``
    #: 0 and ``views.publish`` gives an int leaf no disposition entry where
    #: it gives a float one. A neutral ``0.0`` here would publish a leaf
    #: that was not there, moving the coupled golden with no number
    #: changing. A rune that actually grants contributes a float, as an
    #: item's declared read does.
    ultimate_haste: float = 0
    lifesteal_percent: float = 0.0
    move_speed_percent: float = 0.0
    bonus_health: float = 0.0
    lethality: float = 0.0
    magic_penetration_flat: float = 0.0


#: Which :class:`RuneStatGrants` field each grant channel lands in.
_STAT_FIELDS: Mapping[RuneStat, str] = MappingProxyType(
    {
        RuneStat.ATTACK_SPEED_PERCENT: "attack_speed_percent",
        RuneStat.ABILITY_HASTE: "ability_haste",
        RuneStat.BASIC_ABILITY_HASTE: "basic_ability_haste",
        RuneStat.ULTIMATE_HASTE: "ultimate_haste",
        RuneStat.LIFESTEAL_PERCENT: "lifesteal_percent",
        RuneStat.MOVE_SPEED_PERCENT: "move_speed_percent",
        RuneStat.BONUS_HEALTH: "bonus_health",
        RuneStat.LETHALITY: "lethality",
        RuneStat.MAGIC_PENETRATION_FLAT: "magic_penetration_flat",
    }
)


def resolve_stat_grants(
    effects: Sequence[RuneEffect], context: RuneStatContext
) -> RuneStatGrants:
    """Sum every rune stat grant on the page into one typed total.

    Both grant kinds land here through one channel-by-channel adder, so a
    rune granting one stat and a rune granting three reach the fight's stat
    block by exactly the same route — including adaptive force, whose split
    into attack damage or ability power belongs to the channel and not to
    the kind that named it.
    """
    totals: dict[str, float] = {}

    def add(field: str, amount: float) -> None:
        totals[field] = totals.get(field, 0.0) + amount

    def grant(stat: RuneStat, amount: float) -> None:
        if stat is RuneStat.ADAPTIVE_FORCE:
            bonus_ad, ability_power = adaptive_force_split(
                amount, context.bonus_attack_damage, context.ability_power
            )
            add("bonus_attack_damage", bonus_ad)
            add("ability_power", ability_power)
            return
        add(_STAT_FIELDS[stat], amount)

    for effect in effects:
        if isinstance(effect, RuneStatGrantEffect):
            grant(effect.stat, effect.amount(context))
        elif isinstance(effect, RuneMultiStatGrantEffect):
            for stat, amount in effect.declared_amounts(context).items():
                grant(stat, amount)
    return RuneStatGrants(**totals)


def rune_page_stat_grants(
    page: RunePage,
    *,
    level: int,
    is_melee: bool,
    bonus_attack_damage: float,
    ability_power: float,
    item_stat_types: int = 0,
) -> RuneStatGrants:
    """Compile one page and total the stats it grants, in one call.

    The door ``stats.py`` uses: it holds the build's bonus attack damage and
    ability power (which decide every adaptive grant), the count of stat
    types the build's items grant (which is Jack Of All Trades' whole stack
    rule), and nothing else about runes.
    """
    return resolve_stat_grants(
        resolve_rune_page(page),
        RuneStatContext(
            level=level,
            is_melee=is_melee,
            bonus_attack_damage=bonus_attack_damage,
            ability_power=ability_power,
            options=page.options,
            item_stat_types=item_stat_types,
        ),
    )


def rune_catalog() -> list[dict[str, Any]]:
    """Serve the whole rune roster with per-rune model coverage."""
    compilers = _compilers()
    options = rune_options_catalog()
    return [
        {
            "name": entry.get("name", name),
            "path": entry.get("path", ""),
            "row": entry.get("row"),
            "icon": entry.get("icon", ""),
            "cooldown": entry.get("cooldown"),
            "implemented": name in compilers,
            "options": options.get(name, []),
        }
        for name, entry in RUNE_EFFECTS.items()
    ]


def rune_options_catalog() -> dict[str, list[dict[str, Any]]]:
    """Every declared rune option, keyed by rune name, in catalog shape."""
    # Local import, for the same reason as the rune compilers above.
    from .rune_paths import path_options  # pylint: disable=import-outside-toplevel

    return {
        name: [option.as_catalog_entry() for option in options]
        for name, options in path_options().items()
    }


def shard_catalog() -> list[dict[str, Any]]:
    """Serve the stat-shard table row by row, with per-option coverage."""
    compilers = _shard_compilers()
    return [
        {
            "row": int(slot.get("row", 0)),
            "name": slot.get("name", ""),
            "options": [
                {
                    "name": option.get("name", ""),
                    "implemented": (int(slot.get("row", 0)), option.get("name"))
                    in compilers,
                }
                for option in slot.get("options", ())
            ],
        }
        for slot in RUNE_SHARDS.get("slots", ())
    ]
