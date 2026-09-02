"""Shapes, not numbers: the tag→family map and the per-family compilers.

``item_effects`` owns every number and this module owns every *shape*.  It
holds no float: it says which family each registry tag belongs to, which
family each survival transition and each defensive source belongs to, and
which compiler turns one registry entry into frozen
:class:`~.item_behavior.BehaviorRule` declarations.  Rules are compiled fresh
from the live registries on every call, so a ``refresh_item_effects()`` moves
the declarations too — a catalog that cached its rules would be the stale
literal one layer up.

It is modelled on ``rune_effects._compilers()`` + ``resolve_rune`` — the one
existing compile-fresh, fail-closed registry in the repository — rather than
inventing a second idiom for the same job.

**Closure is enforced at import.**  :func:`validate_catalog` runs when this
module loads, so a new ``item_effects._KNOWN_EFFECT_TYPES`` member, a new
``ActionKind`` or a new ``DefenseMechanic`` fails *collection* until somebody
decides which family it belongs to.  That is the whole point of a closed
union: the cost of a new mechanic is one decision, taken deliberately,
instead of a silent default nobody notices.  All three populations are closed
enumerations this package can read directly, so no closure depends on parsing
another module's source text and this stays a light import.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from typing import Any, NamedTuple
from urllib.parse import quote

from . import data_registry, item_effects, rune_effects
from .ability_spec import AttackClass, DamageClass, Disposition
from .item_behavior import (
    DEFENSE_FIELD_COMBINE,
    RULE_FAMILY_COUNT,
    STAT_CHANNEL_PAYLOADS,
    AbsoluteWindow,
    ActiveCastRule,
    ActiveWindowCastEconomyRule,
    AfterTrigger,
    AllyPacketRule,
    AllyProducer,
    Always,
    AmpChainSlot,
    AtLeast,
    AttackCooldownRefundRule,
    Basis,
    BehaviorRule,
    BelowHalfHealingRule,
    BonusTyping,
    BuildContext,
    ChainTargets,
    ChargedSplash,
    CombatStateRule,
    Comparison,
    Compilability,
    Compilable,
    CooldownProcRule,
    CritDamageBonusRule,
    CritOccurrence,
    DamageDeferralRule,
    DamageFormula,
    DamageThreshold,
    DecayingAttackStacks,
    DeclaredRamp,
    DefenseExclusivity,
    DefenseField,
    DefenseMechanic,
    DefenseOption,
    DeltaAmpRule,
    DerivedStat,
    EmpoweredAutoBuffRule,
    EmpoweredHitRule,
    EnergizedCharge,
    ExcludeTrigger,
    ExecuteRule,
    Fixed,
    FlatStatGrantRule,
    ForcedCritHeal,
    ForcedCritRule,
    HolderStat,
    Isolation,
    LevelRamp,
    LevelSteppedRate,
    LevelSubject,
    LivePredicate,
    Magnitude,
    ManaflowRule,
    ManaSpentHealRule,
    MeleeRangedSplit,
    NoFloor,
    NoScaling,
    OnHitHealRule,
    OnHitStrikeRule,
    OpeningDefenseRule,
    PacketKind,
    PacketSpec,
    PacketTrigger,
    PartAmpRule,
    PenetrationChannelRule,
    PeriodicCadence,
    PeriodicRule,
    Persist,
    Persistence,
    Pool,
    PostMitigationHealRule,
    Probe,
    ProcTrigger,
    RampModel,
    RampPerSecond,
    RampPerStack,
    RampSaturation,
    ReactiveRule,
    ReceiptOnly,
    ReceiptScope,
    ReceivedHealingRule,
    Recipients,
    RefundedAttackWindow,
    RegenerationRule,
    RepeatingStrikeRule,
    Resistance,
    ResistanceShredRule,
    ResourceDrainRule,
    ResourceRestoreRule,
    RestrictedChannel,
    RestrictedChannelRule,
    RuleFamily,
    Scaling,
    SecondaryTargetRule,
    SelfShield,
    ShapedChargeRule,
    ShieldAbsorbs,
    ShieldBypassRule,
    SpellbladeRule,
    StackedStatRule,
    StackGate,
    StackRamp,
    StatAuraRule,
    StatAvailability,
    StatBasis,
    StatConversionRule,
    StatMultiplierRule,
    StatScaled,
    Subject,
    SustainStat,
    SustainStatRule,
    SwingScheduleRule,
    TargetBonusHealthScaled,
    TemporaryLethality,
    Term,
    ThresholdDefenseRule,
    ThresholdRegenRule,
    TimesMissingHealth,
    TimesValue,
    TriggerEvent,
    TriggerWindow,
    Typing,
    UltimateProcRule,
    UltimateRefundRule,
    WindowBoundary,
    WindowMerge,
    ZeroPolicy,
    chain_rank,
    validate_rule,
)
from .survival.actions import ActionKind
from .value_ref import (
    Const,
    DerivedValueRef,
    LateLevelValueRef,
    LevelScale,
    LevelValueRef,
    SourceReceipt,
    ValueRef,
    ValueRegistry,
    receipt_for,
)


class BehaviorCatalogError(RuntimeError):
    """The catalog's closure is broken — a tag, kind or source has no family."""


# ── tag → family, total and single-valued over the 38 registry tags ───────

TAG_FAMILY: Mapping[str, RuleFamily] = {
    # strike
    "on_hit": RuleFamily.ON_HIT_STRIKE,
    "on_hit_once": RuleFamily.CHARGED_STRIKE,
    "on_hit_stacking": RuleFamily.CHARGED_STRIKE,
    "shaped_charge": RuleFamily.CHARGED_STRIKE,
    "ult_empowered_autos": RuleFamily.CHARGED_STRIKE,
    "spellblade": RuleFamily.SPELLBLADE,
    "proc": RuleFamily.CAST_PROC,
    "ult_proc": RuleFamily.CAST_PROC,
    "max_hp_proc": RuleFamily.CAST_PROC,
    "burn": RuleFamily.PERIODIC,
    "immolate": RuleFamily.PERIODIC,
    "periodic_aoe": RuleFamily.PERIODIC,
    "active": RuleFamily.ACTIVE_CAST,
    "secondary_target": RuleFamily.SECONDARY_TARGET,
    # pricing
    "ability_damage_amp": RuleFamily.DELTA_AMP,
    "basic_damage_amp": RuleFamily.DELTA_AMP,
    "damage_amp": RuleFamily.DELTA_AMP,
    "magic_damage_amp": RuleFamily.DELTA_AMP,
    "hypershot_amp": RuleFamily.DELTA_AMP,
    "magic_true_crit": RuleFamily.DELTA_AMP,
    "armor_reduction": RuleFamily.RESISTANCE_SHRED,
    "mr_reduction_stacking": RuleFamily.RESISTANCE_SHRED,
    "crit_modifier": RuleFamily.CRIT_PROFILE,
    "first_auto_crit": RuleFamily.CRIT_PROFILE,
    "execute": RuleFamily.DAMAGE_ROUTING,
    "shield_reduction": RuleFamily.DAMAGE_ROUTING,
    # defence
    "defensive_start": RuleFamily.OPENING_DEFENSE,
    "target_mitigation": RuleFamily.OPENING_DEFENSE,
    "target_threshold_health": RuleFamily.THRESHOLD_DEFENSE,
    "target_threshold_shield": RuleFamily.THRESHOLD_DEFENSE,
    "target_state": RuleFamily.COMBAT_STATE,
    "thorns": RuleFamily.REACTIVE,
    # rest
    "sustain": RuleFamily.SUSTAIN,
    "on_hit_heal": RuleFamily.SUSTAIN,
    "stat_conversion": RuleFamily.STAT_DERIVATION,
    "armor_penetration_channel": RuleFamily.STAT_DERIVATION,
    "conditional_attack_speed": RuleFamily.STAT_DERIVATION,
    "target_attack_speed_aura": RuleFamily.STAT_DERIVATION,
    "ult_attack_speed_buff": RuleFamily.STAT_DERIVATION,
}

# The ten tags no engine dispatches on, with the reason each still lands in a
# family rather than being deleted.  Deleting or re-pointing them is **H4**,
# the human's call; this phase's job is to make the fail-closed answer
# explicit and to carry the ten on the frontier so the decision has a
# measured population.  The four/six split and its members are the phase
# document's, and this table and it must not disagree.
H4_DEAD_TAGS: frozenset[str] = frozenset(
    {
        "conditional_attack_speed",
        "shield_reduction",
        "target_state",
        "target_attack_speed_aura",
    }
)

H4_SELF_REFERENTIAL_TAGS: frozenset[str] = frozenset(
    {
        "defensive_start",
        "stat_conversion",
        "sustain",
        "target_mitigation",
        "target_threshold_health",
        "target_threshold_shield",
    }
)

H4_TAG_REASONS: Mapping[str, str] = {
    "conditional_attack_speed": (
        "was dead — read nowhere in src/ — until the stat-derivation "
        "migration declared Yun Tal Wildarrows' crit stacks and its "
        "assumed-active attack speed as STAT_DERIVATION, which is the family "
        "this tag always named. H4's decision on the tag stands"
    ),
    "shield_reduction": (
        "was dead — read nowhere in src/ — until 3.7 declared Serpent's Fang's "
        "venom as DAMAGE_ROUTING: the share of the target's shielding a strike "
        "passes through is a routing rule and not a defence the holder owns, "
        "and it now reaches a real dispatch. H4's decision on the tag stands"
    ),
    "target_state": (
        "was dead — read nowhere in src/ — until 3.5 gave Force of Nature's "
        "and Jak'Sho's stack ledgers a COMBAT_STATE declaration, which is the "
        "family this tag always named. Whether the *tag* is then deleted or "
        "kept is still H4's, the human's"
    ),
    "target_attack_speed_aura": (
        "was dead — read nowhere in src/ — until the stat-derivation "
        "migration gave Winter's Caress a STAT_DERIVATION aura declaration, "
        "which is the family this tag always named. H4's decision on the tag "
        "stands"
    ),
    "defensive_start": (
        "was self-referential — read only by item_coverage's own claim while "
        "the behaviour was reached by item name in defensive_effects — until "
        "3.5 made it a real dispatch: every entry carrying it now compiles an "
        "OPENING_DEFENSE declaration. H4's decision on the tag stands"
    ),
    "stat_conversion": (
        "was self-referential — read only by item_coverage's own claim while "
        "the behaviour was reached by item name in item_effects' stat fold — "
        "until the stat-derivation migration gave every entry carrying it a "
        "STAT_DERIVATION declaration. H4's decision on the tag stands"
    ),
    "sustain": (
        "was self-referential — read only by item_coverage's own claim while "
        "the behaviour was reached by item name — until 3.7 gave every entry "
        "carrying it a SUSTAIN declaration, which is the family this tag "
        "always named. H4's decision on the tag stands"
    ),
    "target_mitigation": (
        "was self-referential — read only by item_coverage's own claim while "
        "the behaviour was reached by item name — until 3.5 declared "
        "Plated Steelcaps-class mitigation as OPENING_DEFENSE. H4's decision "
        "on the tag stands"
    ),
    "target_threshold_health": (
        "was self-referential — read only by item_coverage's own claim — "
        "until 3.5 declared Protoplasm Harness's temporary health as "
        "THRESHOLD_DEFENSE. H4's decision on the tag stands"
    ),
    "target_threshold_shield": (
        "was self-referential — read only by item_coverage's own claim — "
        "until 3.5 declared the Lifeline shields as THRESHOLD_DEFENSE. H4's "
        "decision on the tag stands"
    ),
}


# ── ActionKind → family, total over the 19 survival transitions ───────────

ACTION_KIND_FAMILY: Mapping[ActionKind, RuleFamily] = {
    ActionKind.PLAIN_DAMAGE: RuleFamily.DAMAGE_ROUTING,
    ActionKind.DAMAGE: RuleFamily.DAMAGE_ROUTING,
    ActionKind.EXECUTE: RuleFamily.DAMAGE_ROUTING,
    ActionKind.DEFER: RuleFamily.DAMAGE_ROUTING,
    ActionKind.REDIRECT: RuleFamily.DAMAGE_ROUTING,
    ActionKind.HEAL: RuleFamily.SUSTAIN,
    ActionKind.OVERHEAL_SHIELD: RuleFamily.SUSTAIN,
    ActionKind.ICHOR_CONVERT: RuleFamily.SUSTAIN,
    ActionKind.SHIELD: RuleFamily.OPENING_DEFENSE,
    ActionKind.TEMP_HEALTH: RuleFamily.THRESHOLD_DEFENSE,
    ActionKind.REVIVE: RuleFamily.THRESHOLD_DEFENSE,
    ActionKind.STASIS: RuleFamily.COMBAT_STATE,
    ActionKind.INVULNERABLE: RuleFamily.COMBAT_STATE,
    ActionKind.UNTARGETABLE: RuleFamily.COMBAT_STATE,
    ActionKind.SPELL_SHIELD: RuleFamily.COMBAT_STATE,
    ActionKind.CROWD_CONTROL: RuleFamily.COMBAT_STATE,
    ActionKind.CROWD_CONTROL_RESIST: RuleFamily.COMBAT_STATE,
    ActionKind.STAT_BUFF: RuleFamily.STAT_DERIVATION,
    ActionKind.DAMAGE_MODIFIER: RuleFamily.DELTA_AMP,
    ActionKind.ON_HIT_MAGIC: RuleFamily.ON_HIT_STRIKE,
    ActionKind.UTILITY: RuleFamily.ALLY_PACKET,
}


# ── defence mechanic → family, total over the closed mechanic set ─────────
#
# The population is ``DefenseMechanic``, a closed enum, so the closure below
# fails *collection* on an unmapped mechanic instead of depending on a scrape
# of the resolver's source text for the hand-written provenance records this
# replaced.  The rulings are unchanged, mechanic for mechanic — two of them
# deliberately point outside the four defence families, because Ignore Pain
# reroutes damage over time and Boundless Vitality is sustain, and both ride
# their own family's slice.

DEFENSE_SOURCE_FAMILY: Mapping[DefenseMechanic, RuleFamily] = {
    DefenseMechanic.SHIELD_OF_DURAND: RuleFamily.OPENING_DEFENSE,
    DefenseMechanic.NOXIAN_ENDURANCE: RuleFamily.REACTIVE,
    DefenseMechanic.NOXIAN_PERSISTENCE: RuleFamily.REACTIVE,
    DefenseMechanic.BLESSING_OF_THE_MOUNTAIN: RuleFamily.OPENING_DEFENSE,
    DefenseMechanic.ICHORSHIELD: RuleFamily.OPENING_DEFENSE,
    DefenseMechanic.EVERLASTING: RuleFamily.OPENING_DEFENSE,
    DefenseMechanic.ANNUL: RuleFamily.COMBAT_STATE,
    DefenseMechanic.MAGEBANE: RuleFamily.OPENING_DEFENSE,
    DefenseMechanic.LIFELINE_SHIELDBOW: RuleFamily.THRESHOLD_DEFENSE,
    DefenseMechanic.LIFELINE_HEXDRINKER: RuleFamily.THRESHOLD_DEFENSE,
    DefenseMechanic.LIFELINE_MAW: RuleFamily.THRESHOLD_DEFENSE,
    DefenseMechanic.LIFELINE_SERAPH: RuleFamily.THRESHOLD_DEFENSE,
    DefenseMechanic.LIFELINE_STERAK: RuleFamily.THRESHOLD_DEFENSE,
    DefenseMechanic.LIFELINE_PROTOPLASM: RuleFamily.THRESHOLD_DEFENSE,
    DefenseMechanic.REBIRTH: RuleFamily.THRESHOLD_DEFENSE,
    DefenseMechanic.IGNORE_PAIN: RuleFamily.DAMAGE_ROUTING,
    DefenseMechanic.STEADFAST: RuleFamily.COMBAT_STATE,
    DefenseMechanic.VOIDBORN_RESILIENCE: RuleFamily.COMBAT_STATE,
    DefenseMechanic.TIME_STOP: RuleFamily.COMBAT_STATE,
    DefenseMechanic.BOUNDLESS_VITALITY: RuleFamily.SUSTAIN,
    DefenseMechanic.PLATING: RuleFamily.OPENING_DEFENSE,
    DefenseMechanic.ROCK_SOLID: RuleFamily.OPENING_DEFENSE,
    DefenseMechanic.UNDAUNTED: RuleFamily.OPENING_DEFENSE,
    DefenseMechanic.RESILIENCE: RuleFamily.OPENING_DEFENSE,
    DefenseMechanic.THORNS: RuleFamily.REACTIVE,
}

# The two defences the resolver cites without declaring one of its own, and
# why each is a citation rather than a declaration.  Both reasons are the
# same reason in different clothes: a declaration here would be a *second*
# home for a mechanic that already has one, or none.
UNDECLARED_DEFENSE_MECHANICS: Mapping[DefenseMechanic, str] = {
    DefenseMechanic.SHIELD_OF_DURAND: (
        "champion-owned: Galio's W has no registry entry, so there is no "
        "entry for a declaration to be compiled from"
    ),
    DefenseMechanic.EVERLASTING: (
        "declared once already, as the ally packet that grants the shield; "
        "the opening resolver cites that mechanic to disclose that its "
        "trigger needs authored crowd-control metadata this model will not "
        "infer, and a second declaration would be two homes for one mechanic"
    ),
}

# Which defences can only be priced from an *exactly timed* damage ledger,
# and why each one needs the timestamps.  Every member reads its trigger out
# of the order damage arrived in — a health threshold the ledger has to cross,
# a stack the ledger has to accrue, or an authored control event — so a coarse
# timeline would fire it at the wrong moment rather than not at all, which is
# the one failure a number cannot disclose.  Pricing them against an
# uncertified timed fight is refused (``item_coverage`` withholds the run).
#
# Keyed by the mechanic and never by the item that carries it: six of the nine
# are the same Lifeline shape on six different items, and a per-item list
# would have to be re-reviewed every time a seventh item took a Lifeline.
EVENT_CERTIFIED_MECHANICS: Mapping[DefenseMechanic, str] = {
    DefenseMechanic.LIFELINE_PROTOPLASM: (
        "the Lifeline fires on a health threshold the ordered ledger has to "
        "cross, and its temporary health expires on a sourced window"
    ),
    DefenseMechanic.LIFELINE_HEXDRINKER: (
        "the Lifeline fires on a health threshold the ordered ledger has to " "cross"
    ),
    DefenseMechanic.LIFELINE_SHIELDBOW: (
        "the Lifeline fires on a health threshold the ordered ledger has to " "cross"
    ),
    DefenseMechanic.LIFELINE_MAW: (
        "the Lifeline fires on a health threshold the ordered ledger has to "
        "cross, and its omnivamp runs for a sourced window afterwards"
    ),
    DefenseMechanic.LIFELINE_SERAPH: (
        "the Lifeline fires on a health threshold the ordered ledger has to " "cross"
    ),
    DefenseMechanic.LIFELINE_STERAK: (
        "the Lifeline fires on a health threshold the ordered ledger has to " "cross"
    ),
    DefenseMechanic.EVERLASTING: (
        "the shield is scheduled after an authored immobilize, or a slow for a "
        "melee holder, so the moment it arrives is an event and not a fight "
        "constant"
    ),
    DefenseMechanic.STEADFAST: (
        "stacks accrue from exact incoming champion magic-damage events and "
        "expire on their own window, so the resistance at any instant is a "
        "function of when the damage landed"
    ),
    DefenseMechanic.VOIDBORN_RESILIENCE: (
        "one stack per second of combat, multiplying bonus resistances at the "
        "maximum, so the multiplier at any instant is a function of the clock"
    ),
}


# ── citations ─────────────────────────────────────────────────────────────

# Where a rule's numbers were read from when its registry entry carries no
# citation of its own.  The item and rune caches are patch-stamped and expose
# no MediaWiki revision id, so the id is an explicit zero rather than an
# invented number — the spelling ``defensive_effects`` already uses for the
# same provenance.  The page is derived from the owner rather than typed, so
# a citation cannot name a different item than the rule it sits on.
CACHED_ITEM_SOURCE = "cached data/items.json (patch 16.15)"
CACHED_RUNE_SOURCE = "cached data/runes.json (patch 16.15)"

_WIKI = "https://wiki.leagueoflegends.com/en-us"


@cache
def cached_source_receipt(owner: str, stamp: str) -> SourceReceipt:
    """The cache-backed citation for an owner whose entry carries none.

    Safe to cache without a data version: the receipt is a URL over the
    owner's name and a caller-supplied stamp, and it reads no registry.
    """
    return SourceReceipt(
        url=f"{_WIKI}/{quote(owner.replace(' ', '_'))}",
        revision_id=0,
        revision_timestamp=stamp,
    )


# ── defence declarations ──────────────────────────────────────────────────
#
# One record per defensive mechanic, owner-free: two items carry Annul's
# spell shield and two carry Time Stop, and the declaration is the same
# declaration for both, so binding it to an owner would be the item-name
# literal this migration removes coming back as a table key.  Which owner
# carries a mechanic is answered by the *entry's own keys*, exactly as
# ``ALLY_ENTRY_SHAPES`` answers it for the ally packets.

_WIKI_MODULE = f"{_WIKI}/Module:ItemData/data"


@dataclass(frozen=True, slots=True)
class DefenseShape:
    """Which registry entry carries one defensive mechanic.

    ``requires`` is every key the mechanic reads or gates on; ``excludes``
    the keys whose presence means the entry is a *different* mechanic.  The
    exclusion is not decoration: Armored Advance and Plated Steelcaps both
    carry ``basic_damage_multiplier``, and only the reactive shield tells the
    boots that also plate apart from the boots that only plate.
    """

    requires: tuple[str, ...]
    excludes: frozenset[str] = frozenset()
    signature: tuple[str, ...] = ()

    @property
    def signature_keys(self) -> tuple[str, ...]:
        """The keys that identify the mechanic, the first one unless stated."""
        return self.signature or self.requires[:1]

    def claims(self, entry: Mapping[str, Any]) -> bool:
        """Whether *entry* carries this mechanic, by its signature keys alone."""
        if any(key in entry for key in self.excludes):
            return False
        return all(key in entry for key in self.signature_keys)


@dataclass(frozen=True, slots=True)
class DefenseDeclaration:  # pylint: disable=too-many-instance-attributes
    """One defensive mechanic's shape, before an owner is known.

    ``reads``, ``ramps`` and ``late_ramps`` are the three reference shapes a
    defensive number comes in — a plain sourced key, a one-to-eighteen ramp,
    and a ramp that holds its base until a level the entry itself names — and
    together they are every number the mechanic is allowed to read.  The
    ``*_key`` fields name the entry keys whose values are *policy* rather
    than magnitude: a health threshold, a duration, what a shield stands in
    front of, and what a strike-back is mitigated by.
    """

    shape: DefenseShape
    writes: tuple[DefenseField, ...]
    exclusivity: DefenseExclusivity
    zero_policy: ZeroPolicy
    option: DefenseOption | None = None
    trigger: TriggerEvent | None = None
    threshold_key: str | None = None
    duration_key: str | None = None
    absorbs_key: str | None = None
    damage_class_key: str | None = None
    reads: tuple[str, ...] = ()
    ramps: tuple[tuple[str, str], ...] = ()
    late_ramps: tuple[tuple[str, str, str, str], ...] = ()


_REACTIVE_SHIELD_KEYS: tuple[str, ...] = (
    "reactive_shield_base",
    "reactive_shield_max",
    "reactive_shield_scale_start_level",
    "reactive_shield_scale_end_level",
    "reactive_shield_bonus_health_ratio",
    "reactive_shield_duration",
    "reactive_shield_cooldown",
    "reactive_shield_damage_type",
)

_REACTIVE_SHIELD_RAMP: tuple[str, str, str, str] = (
    "reactive_shield_base",
    "reactive_shield_max",
    "reactive_shield_scale_start_level",
    "reactive_shield_scale_end_level",
)

_REACTIVE_SHIELD_WRITES: tuple[DefenseField, ...] = (
    DefenseField.REACTIVE_SHIELD_AMOUNT,
    DefenseField.REACTIVE_SHIELD_DAMAGE_TYPE,
    DefenseField.REACTIVE_SHIELD_DURATION,
    DefenseField.REACTIVE_SHIELD_COOLDOWN,
    DefenseField.REACTIVE_SHIELD_SOURCE,
)

_REACTIVE_SHIELD_READS: tuple[str, ...] = (
    "reactive_shield_bonus_health_ratio",
    "reactive_shield_duration",
    "reactive_shield_cooldown",
)

_REACTIVE_SHIELD_ZERO = ZeroPolicy(
    Disposition.MEASURED,
    "the shield is a sourced level ramp plus a share of the subject's bonus "
    "health; a zero means both resolved to zero, which the rule measured",
)

_THRESHOLD_SHIELD_WRITES: tuple[DefenseField, ...] = (
    DefenseField.THRESHOLD_SHIELD_AMOUNT,
    DefenseField.THRESHOLD_SHIELD_HEALTH_RATIO,
    DefenseField.THRESHOLD_SHIELD_DURATION,
    DefenseField.THRESHOLD_SHIELD_DAMAGE_TYPE,
)

# The three keys every Lifeline states about *when* it fires and what it
# stands in front of, as opposed to how much it is worth.
_LIFELINE_POLICY_KEYS: tuple[str, ...] = ("health_threshold", "duration", "damage_type")

_LIFELINE_ZERO = ZeroPolicy(
    Disposition.MEASURED,
    "the Lifeline is a sum of sourced shares of the subject's own stats at "
    "the level the build is priced at; a zero means every share resolved to "
    "zero, which the rule measured",
)

_SOURCED_MULTIPLIER_ZERO = ZeroPolicy(
    Disposition.MEASURED,
    "the reduction is a sourced multiplier read live from the registry; a "
    "zero would mean the registry holds zero, which is a measurement",
)

DEFENSE_DECLARATIONS: Mapping[DefenseMechanic, DefenseDeclaration] = {
    DefenseMechanic.NOXIAN_ENDURANCE: DefenseDeclaration(
        shape=DefenseShape(
            (*_REACTIVE_SHIELD_KEYS, "basic_damage_multiplier"),
            signature=("reactive_shield_base", "basic_damage_multiplier"),
        ),
        writes=(*_REACTIVE_SHIELD_WRITES, DefenseField.BASIC_DAMAGE_MULTIPLIER),
        exclusivity=DefenseExclusivity.NONE,
        trigger=TriggerEvent.CHAMPION_DAMAGE,
        absorbs_key="reactive_shield_damage_type",
        reads=(*_REACTIVE_SHIELD_READS, "basic_damage_multiplier"),
        late_ramps=(_REACTIVE_SHIELD_RAMP,),
        zero_policy=_REACTIVE_SHIELD_ZERO,
    ),
    DefenseMechanic.NOXIAN_PERSISTENCE: DefenseDeclaration(
        shape=DefenseShape(
            _REACTIVE_SHIELD_KEYS, frozenset({"basic_damage_multiplier"})
        ),
        writes=_REACTIVE_SHIELD_WRITES,
        exclusivity=DefenseExclusivity.NONE,
        trigger=TriggerEvent.CHAMPION_DAMAGE,
        absorbs_key="reactive_shield_damage_type",
        reads=_REACTIVE_SHIELD_READS,
        late_ramps=(_REACTIVE_SHIELD_RAMP,),
        zero_policy=_REACTIVE_SHIELD_ZERO,
    ),
    DefenseMechanic.BLESSING_OF_THE_MOUNTAIN: DefenseDeclaration(
        shape=DefenseShape(
            (
                "incoming_damage_multiplier",
                "incoming_damage_linger",
                "incoming_damage_cooldown",
            )
        ),
        writes=(
            DefenseField.INCOMING_DAMAGE_MULTIPLIER,
            DefenseField.INCOMING_DAMAGE_LINGER,
            DefenseField.INCOMING_DAMAGE_COOLDOWN,
            DefenseField.INCOMING_DAMAGE_SOURCE,
        ),
        exclusivity=DefenseExclusivity.NONE,
        reads=(
            "incoming_damage_multiplier",
            "incoming_damage_linger",
            "incoming_damage_cooldown",
        ),
        zero_policy=_SOURCED_MULTIPLIER_ZERO,
    ),
    DefenseMechanic.ICHORSHIELD: DefenseDeclaration(
        shape=DefenseShape(
            (
                "ichorshield_min",
                "ichorshield_max",
                "ichorshield_scale_start_level",
                "ichorshield_scale_end_level",
            )
        ),
        writes=(
            DefenseField.BLOODTHIRSTER_SHIELD_CAP,
            DefenseField.BLOODTHIRSTER_STARTING_SHIELD,
            DefenseField.GENERAL_SHIELD,
        ),
        exclusivity=DefenseExclusivity.NONE,
        option=DefenseOption.STARTING_ICHORSHIELD,
        late_ramps=(
            (
                "ichorshield_min",
                "ichorshield_max",
                "ichorshield_scale_start_level",
                "ichorshield_scale_end_level",
            ),
        ),
        zero_policy=ZeroPolicy(
            Disposition.STRUCTURAL_ZERO,
            "the Ichorshield starts empty unless the scenario supplies one — "
            "excess life-steal healing before the modeled exchange is not "
            "guessed — so a zero starting shield is the declared absence of an "
            "input rather than a shield that resolved to nothing",
        ),
    ),
    DefenseMechanic.ANNUL: DefenseDeclaration(
        shape=DefenseShape(("spell_shield_ready", "spell_shield_cooldown")),
        writes=(DefenseField.SPELL_SHIELD_READY, DefenseField.SPELL_SHIELD_SOURCE),
        exclusivity=DefenseExclusivity.ANNUL,
        reads=("spell_shield_cooldown",),
        zero_policy=ZeroPolicy(
            Disposition.STRUCTURAL_ZERO,
            "a spell shield is a state rather than a quantity: it consumes one "
            "hostile ability and grants no number, so it has no measured value "
            "that could be zero",
        ),
    ),
    DefenseMechanic.MAGEBANE: DefenseDeclaration(
        shape=DefenseShape(("magic_shield_max_health_ratio",)),
        writes=(DefenseField.MAGIC_SHIELD,),
        exclusivity=DefenseExclusivity.NONE,
        reads=("magic_shield_max_health_ratio",),
        zero_policy=ZeroPolicy(
            Disposition.MEASURED,
            "the shield is a sourced share of the subject's own maximum "
            "health; a zero means the subject has none, which the rule "
            "measured",
        ),
    ),
    DefenseMechanic.LIFELINE_SHIELDBOW: DefenseDeclaration(
        shape=DefenseShape(
            (
                "shield_base",
                "shield_max",
                "shield_scale_start_level",
                "shield_scale_end_level",
                *_LIFELINE_POLICY_KEYS,
            )
        ),
        writes=_THRESHOLD_SHIELD_WRITES,
        exclusivity=DefenseExclusivity.LIFELINE,
        threshold_key="health_threshold",
        duration_key="duration",
        absorbs_key="damage_type",
        late_ramps=(
            (
                "shield_base",
                "shield_max",
                "shield_scale_start_level",
                "shield_scale_end_level",
            ),
        ),
        zero_policy=_LIFELINE_ZERO,
    ),
    DefenseMechanic.LIFELINE_HEXDRINKER: DefenseDeclaration(
        shape=DefenseShape(
            (
                "shield_melee_min",
                "shield_melee_max",
                "shield_ranged_min",
                "shield_ranged_max",
                *_LIFELINE_POLICY_KEYS,
            )
        ),
        writes=_THRESHOLD_SHIELD_WRITES,
        exclusivity=DefenseExclusivity.LIFELINE,
        threshold_key="health_threshold",
        duration_key="duration",
        absorbs_key="damage_type",
        ramps=(
            ("shield_melee_min", "shield_melee_max"),
            ("shield_ranged_min", "shield_ranged_max"),
        ),
        zero_policy=_LIFELINE_ZERO,
    ),
    DefenseMechanic.LIFELINE_MAW: DefenseDeclaration(
        shape=DefenseShape(
            (
                "shield_melee_base",
                "shield_melee_bonus_ad_ratio",
                "shield_ranged_base",
                "shield_ranged_bonus_ad_ratio",
                "lifeline_omnivamp_percent",
                *_LIFELINE_POLICY_KEYS,
            )
        ),
        writes=(*_THRESHOLD_SHIELD_WRITES, DefenseField.MAW_LIFELINE_OMNIVAMP_PERCENT),
        exclusivity=DefenseExclusivity.LIFELINE,
        threshold_key="health_threshold",
        duration_key="duration",
        absorbs_key="damage_type",
        reads=(
            "shield_melee_base",
            "shield_melee_bonus_ad_ratio",
            "shield_ranged_base",
            "shield_ranged_bonus_ad_ratio",
            "lifeline_omnivamp_percent",
        ),
        zero_policy=_LIFELINE_ZERO,
    ),
    DefenseMechanic.LIFELINE_SERAPH: DefenseDeclaration(
        shape=DefenseShape(("shield_max_mana_ratio", *_LIFELINE_POLICY_KEYS)),
        writes=_THRESHOLD_SHIELD_WRITES,
        exclusivity=DefenseExclusivity.LIFELINE,
        threshold_key="health_threshold",
        duration_key="duration",
        absorbs_key="damage_type",
        reads=("shield_max_mana_ratio",),
        zero_policy=_LIFELINE_ZERO,
    ),
    DefenseMechanic.LIFELINE_STERAK: DefenseDeclaration(
        shape=DefenseShape(("shield_bonus_health_ratio", *_LIFELINE_POLICY_KEYS)),
        writes=_THRESHOLD_SHIELD_WRITES,
        exclusivity=DefenseExclusivity.LIFELINE,
        threshold_key="health_threshold",
        duration_key="duration",
        absorbs_key="damage_type",
        reads=("shield_bonus_health_ratio",),
        zero_policy=_LIFELINE_ZERO,
    ),
    DefenseMechanic.LIFELINE_PROTOPLASM: DefenseDeclaration(
        shape=DefenseShape(
            (
                "bonus_health_min",
                "bonus_health_max",
                "heal_min",
                "heal_max",
                "heal_bonus_armor_ratio",
                "heal_bonus_mr_ratio",
                "health_threshold",
                "duration",
                "heal_tick_interval",
            )
        ),
        writes=(
            DefenseField.THRESHOLD_HEALTH_BONUS,
            DefenseField.THRESHOLD_HEALTH_HEAL,
            DefenseField.THRESHOLD_HEALTH_RATIO,
            DefenseField.THRESHOLD_HEALTH_DURATION,
        ),
        exclusivity=DefenseExclusivity.NONE,
        threshold_key="health_threshold",
        duration_key="duration",
        reads=("heal_bonus_armor_ratio", "heal_bonus_mr_ratio", "heal_tick_interval"),
        ramps=(("bonus_health_min", "bonus_health_max"), ("heal_min", "heal_max")),
        zero_policy=_LIFELINE_ZERO,
    ),
    DefenseMechanic.REBIRTH: DefenseDeclaration(
        shape=DefenseShape(("revive_health_ratio", "revive_delay", "revive_cooldown")),
        writes=(
            DefenseField.REVIVE_HEALTH_AMOUNT,
            DefenseField.REVIVE_DELAY,
            DefenseField.REVIVE_COOLDOWN,
            DefenseField.REVIVE_SOURCE,
        ),
        exclusivity=DefenseExclusivity.NONE,
        reads=("revive_health_ratio", "revive_delay", "revive_cooldown"),
        zero_policy=ZeroPolicy(
            Disposition.MEASURED,
            "the resurrection restores a sourced share of the subject's own "
            "base health; a zero means the subject has none, which the rule "
            "measured",
        ),
    ),
    DefenseMechanic.IGNORE_PAIN: DefenseDeclaration(
        shape=DefenseShape(
            (
                "damage_deferral_melee",
                "damage_deferral_ranged",
                "damage_deferral_duration",
                "damage_deferral_ticks",
                "defy_window",
                "defy_heal_bonus_ad_ratio",
                "defy_heal_duration",
                "defy_heal_ticks",
            )
        ),
        writes=(
            DefenseField.DAMAGE_DEFERRAL_FRACTION,
            DefenseField.DAMAGE_DEFERRAL_DURATION,
            DefenseField.DAMAGE_DEFERRAL_TICKS,
            DefenseField.DEFY_WINDOW,
            DefenseField.DEFY_HEAL_BONUS_AD_RATIO,
            DefenseField.DEFY_HEAL_DURATION,
            DefenseField.DEFY_HEAL_TICKS,
        ),
        exclusivity=DefenseExclusivity.NONE,
        reads=(
            "damage_deferral_melee",
            "damage_deferral_ranged",
            "damage_deferral_duration",
            "damage_deferral_ticks",
            "defy_window",
            "defy_heal_bonus_ad_ratio",
            "defy_heal_duration",
            "defy_heal_ticks",
        ),
        zero_policy=ZeroPolicy(
            Disposition.MEASURED,
            "the deferral is a sourced fraction of each post-mitigation "
            "packet; a zero would mean the registry holds zero, which is a "
            "measurement",
        ),
    ),
    DefenseMechanic.STEADFAST: DefenseDeclaration(
        shape=DefenseShape(
            (
                "steadfast_stack_duration",
                "steadfast_max_stacks",
                "steadfast_stack_interval",
                "steadfast_immobilize_stacks",
                "steadfast_bonus_magic_resistance",
                "steadfast_bonus_move_speed_percent",
            )
        ),
        writes=(
            DefenseField.FORCE_STACK_DURATION,
            DefenseField.FORCE_MAX_STACKS,
            DefenseField.FORCE_STACK_INTERVAL,
            DefenseField.FORCE_IMMOBILIZE_STACKS,
            DefenseField.FORCE_BONUS_MAGIC_RESISTANCE,
            DefenseField.FORCE_BONUS_MOVE_SPEED_PERCENT,
        ),
        exclusivity=DefenseExclusivity.NONE,
        reads=(
            "steadfast_stack_duration",
            "steadfast_max_stacks",
            "steadfast_stack_interval",
            "steadfast_immobilize_stacks",
            "steadfast_bonus_magic_resistance",
            "steadfast_bonus_move_speed_percent",
        ),
        zero_policy=ZeroPolicy(
            Disposition.STRUCTURAL_ZERO,
            "Steadfast starts at zero stacks and the ordered ledger arms them "
            "one per eligible cast instance: the resolver publishes the "
            "schedule, so a zero here is the declared opening state rather "
            "than a resistance bonus that resolved to nothing",
        ),
    ),
    DefenseMechanic.VOIDBORN_RESILIENCE: DefenseDeclaration(
        shape=DefenseShape(
            (
                "voidborn_stack_interval",
                "voidborn_max_stacks",
                "voidborn_bonus_resistance_multiplier",
            )
        ),
        writes=(
            DefenseField.JAKSHO_STACK_INTERVAL,
            DefenseField.JAKSHO_MAX_STACKS,
            DefenseField.JAKSHO_BONUS_RESISTANCE_MULTIPLIER,
        ),
        exclusivity=DefenseExclusivity.NONE,
        reads=(
            "voidborn_stack_interval",
            "voidborn_max_stacks",
            "voidborn_bonus_resistance_multiplier",
        ),
        zero_policy=ZeroPolicy(
            Disposition.STRUCTURAL_ZERO,
            "Voidborn Resilience starts at zero combat seconds and the ordered "
            "ledger counts them: the resolver publishes the schedule, so a "
            "zero here is the declared opening state",
        ),
    ),
    DefenseMechanic.TIME_STOP: DefenseDeclaration(
        shape=DefenseShape(("stasis_duration",)),
        writes=(
            DefenseField.STARTING_STASIS_DURATION,
            DefenseField.STARTING_STASIS_SOURCE,
        ),
        exclusivity=DefenseExclusivity.STASIS,
        option=DefenseOption.STASIS_ACTIVE_SECONDS,
        reads=("stasis_duration",),
        zero_policy=ZeroPolicy(
            Disposition.STRUCTURAL_ZERO,
            "stasis is never assumed active by item presence alone: without "
            "the scenario's own active-seconds input the mechanic does not "
            "apply, which is what a zero here says",
        ),
    ),
    DefenseMechanic.BOUNDLESS_VITALITY: DefenseDeclaration(
        shape=DefenseShape(("shield_received_multiplier",)),
        writes=(DefenseField.HEALING_RECEIVED_MULTIPLIER,),
        exclusivity=DefenseExclusivity.NONE,
        reads=("shield_received_multiplier",),
        zero_policy=_SOURCED_MULTIPLIER_ZERO,
    ),
    DefenseMechanic.PLATING: DefenseDeclaration(
        shape=DefenseShape(
            ("basic_damage_multiplier",), frozenset({"reactive_shield_base"})
        ),
        writes=(DefenseField.BASIC_DAMAGE_MULTIPLIER,),
        exclusivity=DefenseExclusivity.NONE,
        reads=("basic_damage_multiplier",),
        zero_policy=_SOURCED_MULTIPLIER_ZERO,
    ),
    DefenseMechanic.ROCK_SOLID: DefenseDeclaration(
        shape=DefenseShape(
            ("basic_damage_flat_reduction", "basic_damage_flat_reduction_cap")
        ),
        writes=(
            DefenseField.BASIC_DAMAGE_FLAT_REDUCTION,
            DefenseField.BASIC_DAMAGE_FLAT_REDUCTION_CAP,
        ),
        exclusivity=DefenseExclusivity.NONE,
        reads=("basic_damage_flat_reduction", "basic_damage_flat_reduction_cap"),
        zero_policy=ZeroPolicy(
            Disposition.MEASURED,
            "the reduction is a sourced flat amount capped at a sourced share "
            "of the packet; a zero would mean the registry holds zero, which "
            "is a measurement",
        ),
    ),
    DefenseMechanic.UNDAUNTED: DefenseDeclaration(
        # Rock Solid's sibling, and a different mechanic: Undaunted blocks a
        # flat amount of EVERY champion attack and ability rather than the
        # first basic-damage packet of a swing, and it carries its own
        # damage-over-time amount instead of a share-of-the-packet cap.  The
        # two keys are the signature because either one alone is this
        # mechanic and no other entry carries them.
        shape=DefenseShape(
            (
                "champion_damage_flat_reduction",
                "champion_dot_damage_flat_reduction",
            )
        ),
        writes=(
            DefenseField.CHAMPION_DAMAGE_FLAT_REDUCTION,
            DefenseField.CHAMPION_DOT_DAMAGE_FLAT_REDUCTION,
            DefenseField.CHAMPION_DAMAGE_FLAT_SOURCE,
        ),
        exclusivity=DefenseExclusivity.NONE,
        reads=(
            "champion_damage_flat_reduction",
            "champion_dot_damage_flat_reduction",
        ),
        zero_policy=ZeroPolicy(
            Disposition.MEASURED,
            "both reductions are sourced flat amounts; a zero would mean the "
            "registry holds zero, which is a measurement",
        ),
    ),
    DefenseMechanic.RESILIENCE: DefenseDeclaration(
        shape=DefenseShape(("critical_strike_damage_multiplier",)),
        writes=(DefenseField.CRITICAL_STRIKE_DAMAGE_MULTIPLIER,),
        exclusivity=DefenseExclusivity.NONE,
        reads=("critical_strike_damage_multiplier",),
        zero_policy=_SOURCED_MULTIPLIER_ZERO,
    ),
    DefenseMechanic.THORNS: DefenseDeclaration(
        shape=DefenseShape(
            ("base", "bonus_armor_ratio", "grievous_duration", "damage_type")
        ),
        writes=(),
        exclusivity=DefenseExclusivity.NONE,
        trigger=TriggerEvent.BASIC_ATTACK_HIT,
        damage_class_key="damage_type",
        reads=("base", "bonus_armor_ratio", "grievous_duration"),
        zero_policy=ZeroPolicy(
            Disposition.MEASURED,
            "the strike-back is a sourced flat amount plus a share of the "
            "wearer's bonus armour; a zero means both resolved to zero, which "
            "the rule measured",
        ),
    ),
}

# Which defences the compiled score kernel cannot stage, with the clause that
# refuses each.  Partial on purpose, since absent means ``Compilable``, and
# the membership is the kernel's own capability report read at mechanic
# granularity rather than per item: one item's two mechanics can differ on
# whether the kernel can stage them.
#
# Four mechanics are absent because the compiled path serves them, and each
# absence names the clause that serves it rather than a judgement that it
# looks fine: ``ANNUL`` because the kernel's own
# spell-shield lifecycle decides per packet off ``ability_instance``, which
# ``WalkCompiler`` stamps on every enriched damage row;  ``REBIRTH`` because
# ``program.compile.revive_candidate_actions`` authors the candidates with
# their sourced ``delay`` before the walk starts;  ``STEADFAST`` and
# ``VOIDBORN_RESILIENCE`` because ``transitions.reprice_dynamic_resistance``
# reads the pair fight's baseline resistances off the action, which the
# compiler stamps from ``pair_resistance_baselines`` and which receipts
# ``dynamic_resistance_unavailable`` when a fight published none.
# ``LIFELINE_MAW`` left for a fifth: its omnivamp heals are authored mid-walk
# through ``ledger.schedule_heal``, and the compiled search context now builds
# its ``ScoreLedger`` with the ``actions``/``index_of``/``compile_event``
# injections that call needs.
COMPILED_KERNEL_CANNOT_STAGE: Mapping[DefenseMechanic, ReceiptOnly] = {
    DefenseMechanic.IGNORE_PAIN: ReceiptOnly(
        "the compiled score kernel cannot stage deferred damage: Ignore Pain's "
        "ticks and Defy's clearance are authored inside the event walk",
        scope=ReceiptScope.SURVIVAL_LEDGER_TRANSITION,
    ),
}

# Where each defence's numbers were read from.  Partial on purpose: the three
# Annul items are one mechanic with three citations, so no single declared
# constant could name the revision any one of them was read from, and each
# entry carries its own instead — ``receipt_for``'s ruled resolution order,
# entry first.  :func:`_validate_defense_receipts` asserts exactly that, so
# the gap is checked rather than assumed.
DEFENSE_RECEIPTS: Mapping[DefenseMechanic, SourceReceipt] = {
    DefenseMechanic.SHIELD_OF_DURAND: SourceReceipt(
        url=f"{_WIKI}/Template:Data_Galio/Shield_of_Durand",
        revision_id=3990299,
        revision_timestamp="2026-02-07T07:08:21Z",
    ),
    DefenseMechanic.NOXIAN_ENDURANCE: SourceReceipt(
        url=f"{_WIKI}/Armored_Advance",
        revision_id=4013702,
        revision_timestamp="2026-04-29T23:40:53Z",
    ),
    DefenseMechanic.NOXIAN_PERSISTENCE: SourceReceipt(
        url=f"{_WIKI}/Chainlaced_Crushers",
        revision_id=4013705,
        revision_timestamp="2026-04-29T23:41:11Z",
    ),
    DefenseMechanic.BLESSING_OF_THE_MOUNTAIN: SourceReceipt(
        url=f"{_WIKI}/Celestial_Opposition",
        revision_id=4028004,
        revision_timestamp="2026-06-13T11:27:01Z",
    ),
    DefenseMechanic.ICHORSHIELD: SourceReceipt(
        url=f"{_WIKI}/Bloodthirster",
        revision_id=4025103,
        revision_timestamp="2026-06-04T21:03:44Z",
    ),
    DefenseMechanic.EVERLASTING: SourceReceipt(
        url=f"{_WIKI}/Fimbulwinter",
        revision_id=3984419,
        revision_timestamp="2026-01-14T22:19:05Z",
    ),
    DefenseMechanic.MAGEBANE: SourceReceipt(
        url=f"{_WIKI}/Kaenic_Rookern",
        revision_id=3984971,
        revision_timestamp="2026-01-17T16:04:29Z",
    ),
    DefenseMechanic.LIFELINE_SHIELDBOW: SourceReceipt(
        url=f"{_WIKI}/Immortal_Shieldbow",
        revision_id=4030401,
        revision_timestamp="2026-06-15T20:45:46Z",
    ),
    DefenseMechanic.LIFELINE_HEXDRINKER: SourceReceipt(
        url=f"{_WIKI_MODULE}/Hexdrinker",
        revision_id=3905721,
        revision_timestamp="2025-06-04T01:19:48Z",
    ),
    DefenseMechanic.LIFELINE_MAW: SourceReceipt(
        url=f"{_WIKI}/Maw_of_Malmortius",
        revision_id=3984424,
        revision_timestamp="2026-01-14T23:08:00Z",
    ),
    DefenseMechanic.LIFELINE_SERAPH: SourceReceipt(
        url=f"{_WIKI_MODULE}/Seraph%27s_Embrace",
        revision_id=3905841,
        revision_timestamp="2025-06-04T02:29:36Z",
    ),
    DefenseMechanic.LIFELINE_STERAK: SourceReceipt(
        url=f"{_WIKI_MODULE}/Sterak%27s_Gage",
        revision_id=3905864,
        revision_timestamp="2025-06-04T02:46:55Z",
    ),
    DefenseMechanic.LIFELINE_PROTOPLASM: SourceReceipt(
        url=_WIKI_MODULE,
        revision_id=4046863,
        revision_timestamp="2026-07-28T22:43:08Z",
    ),
    DefenseMechanic.REBIRTH: SourceReceipt(
        url=f"{_WIKI}/Guardian_Angel",
        revision_id=4046863,
        revision_timestamp="2026-07-28T22:43:08Z",
    ),
    DefenseMechanic.IGNORE_PAIN: SourceReceipt(
        url=f"{_WIKI}/Death%27s_Dance",
        revision_id=0,
        revision_timestamp=CACHED_ITEM_SOURCE,
    ),
    DefenseMechanic.STEADFAST: SourceReceipt(
        url=f"{_WIKI}/Force_of_Nature",
        revision_id=4016272,
        revision_timestamp="2026-05-10T11:45:30Z",
    ),
    DefenseMechanic.VOIDBORN_RESILIENCE: SourceReceipt(
        url=f"{_WIKI}/Jak%27Sho,_The_Protean",
        revision_id=3984950,
        revision_timestamp="2026-01-17T15:12:22Z",
    ),
    DefenseMechanic.TIME_STOP: SourceReceipt(
        url=f"{_WIKI}/Zhonya%27s_Hourglass",
        revision_id=3902922,
        revision_timestamp="2025-05-29T13:29:45Z",
    ),
    DefenseMechanic.BOUNDLESS_VITALITY: SourceReceipt(
        url=f"{_WIKI}/Spirit_Visage",
        revision_id=4016166,
        revision_timestamp="2026-05-09T17:09:08Z",
    ),
    DefenseMechanic.PLATING: SourceReceipt(
        url=f"{_WIKI}/Plated_Steelcaps",
        revision_id=4022248,
        revision_timestamp="2026-05-24T02:13:22Z",
    ),
    DefenseMechanic.ROCK_SOLID: SourceReceipt(
        url=f"{_WIKI}/Warden%27s_Mail",
        revision_id=3987228,
        revision_timestamp="2026-01-25T05:28:19Z",
    ),
    DefenseMechanic.UNDAUNTED: SourceReceipt(
        url=f"{_WIKI}/Guardian%27s_Horn",
        # The tracked item cache exposes no MediaWiki revision id for this
        # record; zero is the spelled marker for a cache-backed reading.
        revision_id=0,
        revision_timestamp="cached data/items.json (patch 16.16.1)",
    ),
    DefenseMechanic.RESILIENCE: SourceReceipt(
        url=f"{_WIKI}/Randuin%27s_Omen",
        revision_id=4021798,
        revision_timestamp="2026-05-21T14:21:13Z",
    ),
    DefenseMechanic.THORNS: SourceReceipt(
        url=_WIKI_MODULE,
        revision_id=0,
        revision_timestamp=CACHED_ITEM_SOURCE,
    ),
}


# ── the sustain shapes the score ledger cannot stage ──────────────────────

# Each entry names one **sustain shape** the compiled score ledger has
# nowhere to put.  Each shape has exactly one owner today only because
# exactly one item carries it.  Keyed by the payload type, so the fact stays
# attached to the mechanic and a second item growing the same shape inherits
# the refusal instead of being forgotten, which is the whole difference
# between a declaration and a name list.
LEDGER_UNSTAGEABLE_SUSTAIN: Mapping[type, ReceiptOnly] = {
    ManaSpentHealRule: ReceiptOnly(
        "the compiled score kernel cannot stage a mana-spent heal: the "
        "restore is credited by a second pass over the receipt walk's own "
        "ledger, and the score ledger runs no second pass",
        scope=ReceiptScope.SURVIVAL_LEDGER_TRANSITION,
    ),
    PostMitigationHealRule: ReceiptOnly(
        "the compiled score kernel cannot stage a post-mitigation heal: the "
        "share is taken from damage the walk has already resolved, which is a "
        "hook the score ledger's damage rows do not carry",
        scope=ReceiptScope.SURVIVAL_LEDGER_TRANSITION,
    ),
    ResourceDrainRule: ReceiptOnly(
        "the compiled score kernel cannot stage a resource drain: the "
        "restoration is a tick cadence over a combat window, and the score "
        "ledger holds no per-second schedule to tick it on",
        scope=ReceiptScope.SURVIVAL_LEDGER_TRANSITION,
    ),
    RegenerationRule: ReceiptOnly(
        "the compiled score kernel cannot stage a regeneration window: the "
        "ticks are authored inside the event walk once the window opens, "
        "after the score ledger has been built",
        scope=ReceiptScope.SURVIVAL_LEDGER_TRANSITION,
    ),
    BelowHalfHealingRule: ReceiptOnly(
        "the compiled score kernel cannot stage a below-half healing bonus: "
        "the bonus applies only while the walk has already taken the holder "
        "under the boundary, which is live health state the score ledger "
        "carries no crossing for",
        scope=ReceiptScope.SURVIVAL_LEDGER_TRANSITION,
    ),
}

# One self-shield fact, said once for the two families that can declare one:
# a shield the holder puts on itself is stamped onto its own damage rows by
# the receipt path, and ``survival/compile.unrepresentable_damage_receipt``
# refuses exactly that with ``self_shield_payload``.  Eclipse declares it as a
# cast proc and Fimbulwinter as an ally packet addressed to ``Recipients.SELF``
# — two shapes, one refusal, and the hand set records the same fact per item.
COMPILED_KERNEL_CANNOT_SELF_SHIELD = ReceiptOnly(
    "the compiled score kernel cannot stage a self-shield: the receipt path "
    "attaches it to the holder's own damage rows, which is what "
    "survival/compile.unrepresentable_damage_receipt refuses as "
    "self_shield_payload",
    scope=ReceiptScope.SURVIVAL_LEDGER_TRANSITION,
)


# ── the compiled-kernel refusal every amp carries (D-101) ─────────────────

# The refusal ``AMP_COMPILABILITY`` is pointed back at to revert the compiled
# amp lane in one symbol.  It carries no live rule today; it is declared
# rather than deleted so the revert stays a one-line change.
#
# It is one constant because it is one fact about the kernel, not a per-item
# judgement — and a per-item copy is how sixteen conservatism notes ended up
# indistinguishable from sixteen representability facts.
COMPILED_KERNEL_CANNOT_AMP = ReceiptOnly(
    "the compiled score kernel cannot represent a timed, typed damage "
    "modifier: unrepresentable_template_receipt returns support_kind=<kind> "
    "for anything but shield/heal and add_support_templates raises on it "
    "(D-101)",
    scope=ReceiptScope.SCORE_KERNEL_DAMAGE_MODIFIER,
)

# The live answer.  The compiled score kernel stages an armed
# ``damage_modifier`` as an ``ActionKind.DAMAGE_MODIFIER`` through the one
# ``SurvivalAction`` constructor, and the compiled damage rows it applies to
# carry the delivery flags and resistance baselines an attack-class
# restriction and a resistance reduction read; the equivalence fixture that
# proves the compiled lane reproduces the receipt walk over every producer is
# ``tests/test_amp_kernel.py``.
COMPILED_KERNEL_CAN_AMP = Compilable()

# The one symbol every ``delta_amp`` rule declares its compiled-kernel answer
# through, so moving the whole population is a change to this line and to
# nothing else — holder-side amps the pair engine prices into its own damage
# rows and the two that author a cross-participant packet (Bloodsong's Expose
# Weakness and Imperial Mandate's Command) alike.
#
# ``tests/test_interp_delta_amp.py`` pins that population by mechanic id, so
# the blast radius of moving this line is a committed set rather than a
# consequence discovered afterwards.
AMP_COMPILABILITY: Compilability = COMPILED_KERNEL_CAN_AMP


# ── compilers (D-52's ruled exception to "no callables in declarations") ──

Compiler = Callable[
    [RuleFamily, str, ValueRegistry, Mapping[str, Any]], tuple[BehaviorRule, ...]
]

# Which registry tags the delta-amp compiler below turns into declarations,
# and — for the rest — which slice retires each refusal.
MIGRATED_DELTA_AMP_TAGS: frozenset[str] = frozenset(
    {
        "ability_damage_amp",
        "basic_damage_amp",
        "damage_amp",
        "hypershot_amp",
        "magic_damage_amp",
        "magic_true_crit",
    }
)

# Empty: every delta-amp tag compiles.  Kept as the family's declared place
# to book a refusal, which `validate_catalog` reads together with the set
# above — a new tag with no compiler goes here or fails collection.
DELTA_AMP_UNMIGRATED_TAGS: Mapping[str, str] = {}

# The key Abyssal Mask's curse is read from.  Occupying no chain slot is what
# makes it a `PartAmpRule`, not a refusal: it multiplies each magic packet
# where the mitigation prices it.
MAGIC_AMP_KEY = "magic_amp"


# Rules whose sources disagree about a *reading* rather than about a number,
# where the declaration ships the conservative one.  Keyed by ``mechanic_id``
# and co-located with the declarations it qualifies — the repo idiom
# ``trigger_stream`` names (``item_source.ACKNOWLEDGED_SOURCE_CONFLICTS``,
# ``rune_paths.keystones.COMPILERS``): a frozen table beside its reader.
#
# The two existing divergence tables are the wrong shape for this and are
# gated shut against it.  ``item_source.ACKNOWLEDGED_SOURCE_CONFLICTS`` is
# keyed by an effect Riot declares and the Wiki cache lacks, and its
# staleness gate rejects an entry whose effect both sources carry.
# ``trigger_stream.DIVERGENCES`` records a *pair-versus-walk* disagreement
# and is asserted empty (D-92); the entry below is one both engines agree
# on, so it has no second reading to put in ``walk_reading``.
#
# No measured figure is restated here.  Every exposure this note grades moves
# with the champion corpus, so the note names the gate that prices it and the
# gate re-measures at run time.
ACKNOWLEDGED_READING_DIVERGENCES: Mapping[str, str] = {
    "imperial_mandate.command": (
        "Merge policy, ruled REFRESH against the Wiki's wording. The League "
        "Wiki's Imperial Mandate page says 'Subsequent immobilizes against a "
        "target extend the duration of the effect', which admits an additive "
        "reading — a second immobilize adding its own 4 s to whatever is "
        "left. Riot's own sources do not: the in-client tooltip "
        "(CommunityDragon items.json id 4005) says only 'mark them as 7% "
        "Vulnerable for 4 seconds', and items.cdtb.bin.json Items/4005 "
        "carries DamageAmp 0.07 and DamageAmpDuration 4.0 with no merge "
        "script at all. So the sources settle that the amp never stacks and "
        "leave refresh-versus-additive open. Both engines have always "
        "computed refresh — delta_amp.trigger_windows moves the window's end "
        "to trigger + duration, and survival.transitions._refresh_live_modifier "
        "keeps one modifier at the later expiry — so REFRESH is the shipped "
        "reading and the conservative one. WindowMerge.EXTEND stays in the "
        "enum, unreached, as the additive answer a source could still "
        "settle. tests/test_command_amp_roster.py prices what the additive "
        "reading would add, over the champions who author two immobilizes "
        "inside one window."
    ),
}


# Which value keys of an ``ALLY_ITEM_EFFECTS`` record declare an amp-chain
# slot.  That registry carries no effect tag at all — every entry is an ally
# packet by construction — so a cross-participant amplifier's *shape* has to
# come from the keys its numbers live under.  Closed, and keyed by the number
# keys rather than by the item's name, so no item-name literal enters the
# dispatch.
#
# Every key of a slot is listed, not just the one that routes: a record
# carrying *some* of them is a broken parse, and the whole point of routing
# on keys is that it must not turn a broken parse into an item that quietly
# declares no amplifier.
ALLY_DELTA_AMP_SLOTS: Mapping[AmpChainSlot, tuple[str, ...]] = {
    AmpChainSlot.EXPOSE_WEAKNESS: ("expose_weakness_melee", "expose_weakness_ranged"),
    AmpChainSlot.POST_IMMOBILIZE: ("command_damage_amp", "command_duration"),
}

ALLY_DELTA_AMP_KEYS: frozenset[str] = frozenset(
    key for keys in ALLY_DELTA_AMP_SLOTS.values() for key in keys
)

# The signature key and the tag of the one declaration that carries no number
# of its own: which half of a resistance an item's *cached* percent
# penetration reaches.  ``True`` is the bonus-armour channel and ``False`` the
# ordinary total one, and both are stated: an item whose channel is the
# ordinary one says so, because the alternative is silence.
ARMOR_PENETRATION_CHANNEL_KEY = "armor_penetration_bonus_only"
ARMOR_PENETRATION_CHANNEL_TAG = "armor_penetration_channel"

# The tags whose whole content is where a *cached stat* lands.  An entry
# carrying one declares no effect: the number was already in the stat block
# and the declaration only says which field of it the number belongs to.
# ``item_coverage`` reads this to keep such an entry out of the coverage
# ladder, because publishing "damage-relevant effects are declared" for an
# item whose passive is still unmodelled is the prose-outruns-code shape that
# flip removed.
STAT_CHANNEL_TAGS: frozenset[str] = frozenset({ARMOR_PENETRATION_CHANNEL_TAG})

# A registry entry's ``type`` names its *primary* mechanic, but a few entries
# carry a second one in their value keys — Liandry's Torment is a burn that
# also amplifies the whole total, and every ally-registry amp is a second
# mechanic on an ally-packet record.  Declared here and closed, so a second
# mechanic hiding in a value key is a table entry rather than an if-statement
# somebody has to notice.  Counter 3's population is unchanged: it counts
# entries with no rule at all, and this only changes which compilers an entry
# is offered to.
#
# Keyed by registry, because a key name is only evidence *in the registry
# that owns the mechanic*: Bloodsong's spellblade record carries the same
# ``expose_weakness_*`` keys as its ally record, and reading them there would
# claim the pair-side spellblade entry declares an amplifier it does not.
SECONDARY_KEY_FAMILY: Mapping[ValueRegistry, Mapping[str, RuleFamily]] = {
    "ITEM_EFFECTS": {
        "damage_amp_per_second": RuleFamily.DELTA_AMP,
        # An ally packet hung on an item-registry record.  The key is the
        # producer's own signature key from ALLY_ENTRY_SHAPES, so the two
        # tables cannot name different keys for one mechanic.
        "everlasting_base_shield": RuleFamily.ALLY_PACKET,
        "reap_gold_per_minion": RuleFamily.ALLY_PACKET,
        "rage_duration": RuleFamily.ALLY_PACKET,
        "support_quest_threshold": RuleFamily.ALLY_PACKET,
        "front_offset": RuleFamily.ALLY_PACKET,
        "nightstalker_unseen_seconds": RuleFamily.ALLY_PACKET,
        # A defence hung on an entry whose tag names a different family.  The
        # key is the mechanic's own signature key from DEFENSE_DECLARATIONS,
        # so the two tables cannot name different keys for one mechanic, and
        # an entry the key does not fit compiles no defence rather than a
        # wrong one.
        "health_threshold": RuleFamily.THRESHOLD_DEFENSE,
        "revive_health_ratio": RuleFamily.THRESHOLD_DEFENSE,
        "damage_deferral_melee": RuleFamily.DAMAGE_ROUTING,
        "shield_received_multiplier": RuleFamily.SUSTAIN,
        "spell_shield_ready": RuleFamily.COMBAT_STATE,
        "stasis_duration": RuleFamily.COMBAT_STATE,
        "reactive_shield_base": RuleFamily.REACTIVE,
        # The below-half half of a health-state passive whose tag names the
        # above-half half: Immortal Path's entry is tagged ``damage_amp`` for
        # the amplifier it grants above the boundary, and the healing bonus
        # it grants below one is a second mechanic on the same entry rather
        # than a second entry.
        "health_state_healing_multiplier_below_half": RuleFamily.SUSTAIN,
        # A stat derivation hung on an entry whose tag names a different
        # family.  Muramana's Awe is filed under its on-hit record and three
        # ultimate-haste grants under their proc records, and every one of
        # them is folded into the stat block by
        # ``item_effects.resolve_stat_effects`` — so without these two keys a
        # live conversion would compile to nothing while its number kept
        # moving builds.
        # The two shapes that re-rate the holder's own attack stream, each
        # hung on an entry whose tag names another family: a ramp on an
        # on-hit record and a re-armed window on a conditional-attack-speed
        # one.  The schedule is a strike-family mechanic — it decides how
        # many attacks land and when — and it is claimed by its signature key
        # because neither tag says a word about it.
        "seething_attack_speed_per_stack": RuleFamily.CHARGED_STRIKE,
        "attack_refund_base": RuleFamily.CHARGED_STRIKE,
        # The omnivamp Void Corruption's own ramp arms, hung on the entry
        # whose tag names the amplifier that ramp pays.  The grant is a
        # fight state rather than a stat, which is why it is a second
        # mechanic on one entry and not a second entry.
        "max_stack_omnivamp": RuleFamily.SUSTAIN,
        "max_mana_to_ad_ratio": RuleFamily.STAT_DERIVATION,
        "ultimate_haste": RuleFamily.STAT_DERIVATION,
        # Slay's omnivamp, hung on an entry tagged for the sustain the
        # vampirism is: what the mechanic *grants* is a stat that grows per
        # takedown stack, so the stacked-stat shape is where it is declared
        # and the sustain tag keeps naming the wiki's own reading.
        "slay_omnivamp_per_takedown": RuleFamily.STAT_DERIVATION,
        # Where an item's cached percent armour penetration lands, hung on an
        # entry whose tag names the amplifier the item is bought for.  Lord
        # Dominik's Giant Slayer and its bonus-armour channel are two
        # mechanics on one record, and the channel is resolved with the stat
        # block rather than with the amp chain.
        ARMOR_PENETRATION_CHANNEL_KEY: RuleFamily.STAT_DERIVATION,
        # The casting trade an amp entry's own active window makes.  The tag
        # names the amp because the amp is what the item is bought for; the
        # resource cost and the cooldown progression the window also moves are
        # a second mechanic on the same entry, resolved before any damage
        # exists and read by the rotation rather than by the amp chain.
        "mana_cost_multiplier": RuleFamily.STAT_DERIVATION,
    },
    "ALLY_ITEM_EFFECTS": dict.fromkeys(
        sorted(ALLY_DELTA_AMP_KEYS), RuleFamily.DELTA_AMP
    ),
    "RUNE_EFFECTS": {},
}

# Which runes declare an amp-chain slot, and which slot.  A rune record
# carries no effect tag — the shape *is* the rune — so this is the closed key
# set that makes the name dispatch total, exactly as
# ``rune_effects._compilers()`` is for the runes themselves.  Rule 5 reaches
# runes (D-46), so their numbers are references like any other.  Keystones
# and minor runes are both here: a rune's row decides where the page puts it,
# not whether the chain can hold its amplifier.
#
# One rune-page amplifier kind is deliberately *not* here.  Last Stand and
# Axiom Arcanist keep their ratio in a compiled ``RuneFlatAmpEffect`` and
# walk their own ledger in ``damage.py``, because a ``DeltaAmpRule`` cannot
# state either of them.  Last Stand's magnitude is a linear interpolation
# between two sourced ends keyed on a declared rune *option* (the holder's
# own health, which the pair engine does not track), and no ``Magnitude``
# member reads an option: a magnitude resolves against ``BuildContext``,
# which carries build facts, and feeding a request-scoped scenario control
# into it would put an option key where ``value_ref`` says only a sourced
# number may go.  Axiom Arcanist's filter is the cast slot that authored the
# row, which no ``Typing`` field expresses — ``Typing`` names damage and
# attack classes, and "the ultimate" is neither.  Two new vocabulary members
# for two runes buys nothing the flat kind does not already say, so the flat
# kind stays where it is and this comment is the reason.
RUNE_AMP_SLOTS: Mapping[str, AmpChainSlot] = {
    "First Strike": AmpChainSlot.OPENING_WINDOW,
    "Press the Attack": AmpChainSlot.LASTING_PROC_AMP,
    "Coup de Grace": AmpChainSlot.TARGET_HEALTH_GATE,
    "Cut Down": AmpChainSlot.TARGET_HEALTH_GATE,
}

# Which side of its health threshold each target-health-gated rune arms on.
# The cache states this too, under ``damage_amp_health_gate``, and the rule
# builder reads it there and checks it against this table: a wiki description
# whose two halves were reordered would otherwise price Coup de Grace as the
# rune that rewards attacking a healthy target.  Declared here rather than in
# the rune's compiler because this is the chain's vocabulary — a
# ``Comparison`` — and the compiler produces no comparison of its own.
TARGET_HEALTH_GATE_DIRECTIONS: Mapping[str, Comparison] = {
    "Coup de Grace": Comparison.LT,
    "Cut Down": Comparison.GT,
}

# How ``data/runes.json`` spells each comparison under
# ``damage_amp_health_gate``.  Closed: a word outside it is a parse this
# catalog refuses rather than a gate it guesses the side of.  ``self_below``
# is deliberately absent — that is Last Stand's gate on the *holder's* own
# health, which no chain slot reads.
CACHED_HEALTH_GATE_WORDS: Mapping[str, Comparison] = {
    "target_below": Comparison.LT,
    "target_above": Comparison.GT,
}


# ── registry formula schemas: which shares each formula name is made of ───
#
# The registry names a shape (``"flat_bonus_ad_ap"``) and these tables say
# what that name means, term by term, in the order the registry's own
# compiler summed them.  A schema entry is ``(basis, key)`` for a single
# sourced rate or ``(basis, (melee_key, ranged_key))`` where the registry pays
# a melee holder differently.  They live here, with the shapes, because a
# formula name is a *schema* of the registry and not policy of a rule.
class LevelRampKeys(NamedTuple):
    """A schema coefficient the registry states as a two-key level ramp.

    The third coefficient shape, beside a single key and a melee/ranged pair:
    the registry says a number's value at the bottom and the top of the level
    span and the ramp between them is interpolation, not a share of anything.
    ``scale`` names which span, so the two live ramps differ in a declared
    word rather than in two arithmetic branches.
    """

    min_key: str
    max_key: str
    scale: LevelScale


class LevelSteppedKeys(NamedTuple):
    """A schema coefficient that is flat until a level and then steps per level.

    The fourth coefficient shape.  Both ends may themselves be melee/ranged
    pairs, because the one schema that needs this pays a melee holder more at
    both, and ``from_level_key`` names the registry key holding the level the
    stepping starts at rather than stating a level here.
    """

    base: str | tuple[str, str]
    per_level: str | tuple[str, str]
    from_level_key: str


TermSchema = tuple[Basis, "str | tuple[str, str] | LevelRampKeys | LevelSteppedKeys"]

ON_HIT_FORMULA_TERMS: Mapping[str, tuple[TermSchema, ...]] = {
    "flat": ((Basis.FLAT, "base"),),
    "flat_ap": ((Basis.FLAT, "base"), (Basis.ABILITY_POWER, "ap_ratio")),
    "flat_bonus_ad_ap": (
        (Basis.FLAT, "base"),
        (Basis.BONUS_ATTACK_DAMAGE, "bonus_ad_ratio"),
        (Basis.ABILITY_POWER, "ap_ratio"),
    ),
    "current_hp": (
        (
            Basis.TARGET_CURRENT_HEALTH,
            ("current_hp_ratio_melee", "current_hp_ratio_ranged"),
        ),
    ),
    "max_hp": (
        (Basis.HOLDER_MAX_HEALTH, ("max_hp_ratio_melee", "max_hp_ratio_ranged")),
    ),
    "max_mana": ((Basis.HOLDER_MAX_MANA, "max_mana_ratio_on_hit"),),
}

# Which on-hit schemas carry a sourced minimum, and the key holding it.
ON_HIT_FORMULA_FLOORS: Mapping[str, str] = {"current_hp": "min_damage"}

# The active-item schemas.  ``level_ap``'s base is a two-key ramp rather than
# two terms: the registry states one number with a low and a high end, and
# splitting it into shares would invent a mechanic ("so much per level") the
# item does not have.  The ramp spans levels 1 to 20, the top-lane cap
# CLAUDE.md records, which is what the registry's own compiler interpolated
# across.
ACTIVE_FORMULA_TERMS: Mapping[str, tuple[TermSchema, ...]] = {
    "flat_ap": ((Basis.FLAT, "base"), (Basis.ABILITY_POWER, "ap_ratio")),
    "total_ad": ((Basis.TOTAL_ATTACK_DAMAGE, "total_ad_ratio"),),
    "level_ap": (
        (Basis.FLAT, LevelRampKeys("base_min", "base_max", "linear_1_20")),
        (Basis.ABILITY_POWER, "ap_ratio"),
    ),
}

# The charged-strike schemas, across all four tags.  ``level_missing_hp`` is
# the one schema whose flat share *steps* with level rather than being a
# constant or a two-ended ramp, and whose sum is then scaled by how much
# health the target is missing; both of those are shapes of the mechanic and
# neither is a share, which is why the table stays a list of shares.
CHARGED_STRIKE_FORMULA_TERMS: Mapping[str, tuple[TermSchema, ...]] = {
    "flat": ((Basis.FLAT, "base"),),
    "flat_base_ad": (
        (Basis.FLAT, "base"),
        (Basis.BASE_ATTACK_DAMAGE, "base_ad_ratio"),
    ),
    "flat_max_hp": (
        (Basis.FLAT, "base"),
        (Basis.HOLDER_MAX_HEALTH, "max_hp_ratio"),
    ),
    "flat_plus_lethality": (
        (Basis.FLAT, "base"),
        (Basis.LETHALITY, "lethality_ratio"),
    ),
    "current_hp": (
        (
            Basis.TARGET_CURRENT_HEALTH,
            ("current_hp_ratio_melee", "current_hp_ratio_ranged"),
        ),
    ),
    "base_ad_max_hp": (
        (
            Basis.BASE_ATTACK_DAMAGE,
            ("base_ad_ratio_melee", "base_ad_ratio_ranged"),
        ),
        (Basis.HOLDER_MAX_HEALTH, ("max_hp_ratio_melee", "max_hp_ratio_ranged")),
    ),
    "level_missing_hp": (
        (
            Basis.FLAT,
            LevelSteppedKeys(
                base=("base_melee", "base_ranged"),
                per_level=("per_level_melee", "per_level_ranged"),
                from_level_key="scaling_start_level",
            ),
        ),
    ),
    # The shaped charge names no formula in the registry at all: its shape is
    # part of the mechanic's definition, so the compiler supplies the name.
    "shaped_charge": (
        (Basis.FLAT, ("base_melee", "base_ranged")),
        (Basis.LETHALITY, ("lethality_ratio_melee", "lethality_ratio_ranged")),
    ),
}

# Which charged-strike tag declares which of the four shapes.
EMPOWERED_HIT_TAG = "on_hit_once"
REPEATING_STRIKE_TAG = "on_hit_stacking"
SHAPED_CHARGE_TAG = "shaped_charge"
EMPOWERED_AUTO_BUFF_TAG = "ult_empowered_autos"

# The schema name the shaped charge's own compiler supplies, the damage class
# its mechanic is defined in, and the key holding how deep the missing-health
# scaling reaches.
SHAPED_CHARGE_FORMULA = "shaped_charge"
MISSING_HEALTH_BONUS_KEY = "missing_hp_bonus_max"

# The keys the charged strikes' optional mechanics live under, grouped so each
# is declared whole or not at all.
ENERGIZED_KEYS = ("energized_max_stacks", "energized_attack_stacks")
ENERGIZED_ABILITY_FLAG = "energized_ability_trigger"
TEMPORARY_LETHALITY_KEYS = (
    "temporary_lethality_melee",
    "temporary_lethality_ranged",
    "temporary_lethality_duration",
)
CHAIN_TARGET_KEYS = ("chain_targets_min", "chain_targets_max")

# The structural flag that says an empowered hit fires as many times as the
# holder has empowered attacks, the key holding that count, and the key
# holding how many on-hit applications a repeating strike waits for.
USES_EMPOWERED_AUTO_COUNT = "uses_empowered_auto_count"
EMPOWERED_AUTO_COUNT_KEY = "empowered_auto_count"
HITS_REQUIRED_KEY = "hits_required"

# What an empowered hit that fires exactly once declares.  Spelled rather
# than left to the absence of a key: "this fires once" is a statement about
# the mechanic, and a second such strike must not inherit it by omission.
FIRES_ONCE = Const(1.0, "count")

# The five keys an ultimate's empowered-attack window is made of.
EMPOWERED_AUTO_BUFF_KEYS = (
    "bonus_attack_speed_percent",
    "empowered_auto_count",
    "duration",
    "reduced_crit_ratio",
    "natural_crit_true_damage_ratio",
)

# The cast-proc schemas, across all three tags.  ``charged_ap`` is the one
# schema whose registry compiler multiplied the *sum* rather than a share, so
# its rule carries a `TimesValue` scaling and this table stays a list of
# shares like every other.
CAST_PROC_FORMULA_TERMS: Mapping[str, tuple[TermSchema, ...]] = {
    "charged_ap": (
        (Basis.FLAT, "base_per_charge"),
        (Basis.ABILITY_POWER, "ap_ratio_per_charge"),
    ),
    "flat_ap": ((Basis.FLAT, "base"), (Basis.ABILITY_POWER, "ap_ratio")),
    "flat": ((Basis.FLAT, "base"),),
    "flat_ap_max_hp": (
        (Basis.FLAT, "base"),
        (Basis.ABILITY_POWER, "ap_ratio"),
        (Basis.TARGET_MAX_HEALTH, "target_max_hp_ratio"),
    ),
    "max_hp": (
        (
            Basis.TARGET_MAX_HEALTH,
            ("target_max_hp_ratio_melee", "target_max_hp_ratio_ranged"),
        ),
    ),
}

# Which cast-proc tag arms which of the engine's two records, and — for the
# cooldown proc — whether its row is stamped in the fight's late phase.  The
# tag is the registry's whole statement of the mechanic's shape.
LATE_PHASE_TAGS: frozenset[str] = frozenset({"max_hp_proc"})
ULTIMATE_PROC_TAG = "ult_proc"

# The schema name whose sum is multiplied rather than shared out, and the two
# keys that describe the split.
CHARGED_FORMULA = "charged_ap"
CHARGE_COUNT_KEY = "charges"
SINGLE_TARGET_MULTIPLIER_KEY = "single_target_multiplier"

# The registry's own trigger vocabulary, and the trigger an entry that names
# none is on.  Spelled rather than defaulted at the point of use, because the
# absence of a key really does mean "the coarse scheduler owns this".
PROC_TRIGGER_KEY = "trigger"
DEFAULT_PROC_TRIGGER = ProcTrigger.COARSE

# The two keys a damage-threshold trigger carries, the structural flag that
# says an entry refunds cooldown per attack windup and the key holding the
# refund, and the sibling groups only some procs carry.
THRESHOLD_KEYS = ("damage_threshold_ratio", "damage_threshold_window")
ATTACK_REFUND_FLAG = "attack_refund"
ATTACK_REFUND_KEY = "on_attack_cooldown_refund"
STACK_GATE_KEYS = ("stack_required", "stack_window")
SELF_SHIELD_KEYS = (
    "shield_melee_base",
    "shield_ranged_base",
    "shield_melee_bonus_ad_ratio",
    "shield_ranged_bonus_ad_ratio",
    "shield_duration",
)

# The keys an ultimate proc's window and its one sibling live under.
DURATION_KEY = "duration"
MR_REDUCTION_KEY = "mr_reduction"

# The structural flags a strike's row carries: whether it counts as ability
# damage downstream, whether it is basic damage, and whether the cooldown
# re-arms it.
IS_ABILITY_DAMAGE_KEY = "is_ability_damage"
BASIC_DAMAGE_KEY = "basic_damage"
REPEAT_ON_COOLDOWN_KEY = "repeat_on_cooldown"

# The spellblade schemas.  ``base_ad_crit`` reads the holder's crit chance as
# a *fraction* — the basis caps it at one — which is the reading the registry
# compiler's own `min(chance / 100, 1.0)` encoded inside its closure.
SPELLBLADE_FORMULA_TERMS: Mapping[str, tuple[TermSchema, ...]] = {
    "base_ad": ((Basis.BASE_ATTACK_DAMAGE, "base_ad_ratio"),),
    "base_ad_ap": (
        (Basis.BASE_ATTACK_DAMAGE, "base_ad_ratio"),
        (Basis.ABILITY_POWER, "ap_ratio"),
    ),
    "base_ad_crit": (
        (Basis.BASE_ATTACK_DAMAGE, "base_ad_ratio"),
        (Basis.HOLDER_CRIT_FRACTION, "crit_bonus_max"),
    ),
}

# The sibling mechanics specific spellblades carry, grouped so each is
# declared whole or not at all.  The registry's own compiler decided which
# entry carried which by comparing item names — Lich Bane, Essence Reaver,
# Dusk and Dawn — and required every key of the group it named, so that a
# successful parse which dropped one failed closed rather than compiling a
# weaker item.  Keying on the group's own keys keeps the fail-closed contract
# and drops the names: any key present means every key is required.
SPELLBLADE_SIBLING_GROUPS: tuple[tuple[str, ...], ...] = (
    ("bonus_attack_speed_percent",),
    ("mana_restore_base_ad_ratio", "mana_restore_crit_ratio"),
    ("self_heal_ap_ratio", "self_heal_bonus_health_ratio"),
)

# The key a spellblade's delay between the arming cast and the empowered
# attack lives under, and the registry's structural flag for an empowered
# attack that applies on-hit effects twice.
WEAVE_DELAY_KEY = "weave_delay"
DOUBLE_ON_HIT_KEY = "double_on_hit"

# The periodic schemas, across all three cadences.  One table rather than
# three because the six formula names are distinct: the registry never spells
# a burn's shares and an aura's with one name, and a table keyed by name is
# what makes a collision a merge conflict rather than a silent re-pointing.
# ``max_hp`` here is a share of the *target's* pool, where the on-hit table's
# ``max_hp`` is a share of the holder's — the split the registry's own key
# names could not express, and the reason the two tables are separate.
PERIODIC_FORMULA_TERMS: Mapping[str, tuple[TermSchema, ...]] = {
    "max_hp": ((Basis.TARGET_MAX_HEALTH, "max_hp_ratio_total"),),
    "flat_ap": (
        (Basis.FLAT, "base_total"),
        (Basis.ABILITY_POWER, "ap_ratio_total"),
    ),
    "flat": ((Basis.FLAT, "base_total"),),
    "bonus_hp_dps": (
        (Basis.FLAT, "base_per_second"),
        (Basis.HOLDER_BONUS_HEALTH, "bonus_hp_ratio_per_second"),
    ),
    "flat_dps": ((Basis.FLAT, "base_per_second"),),
    "bonus_hp": ((Basis.HOLDER_BONUS_HEALTH, "bonus_hp_ratio"),),
}

# Which cadence each periodic tag declares, and which key holds its clock.
# The tag is the registry's whole statement of the mechanic's shape, so the
# translation lives here rather than as three branches at the point of use.
PERIODIC_CADENCE_TAGS: Mapping[str, tuple[PeriodicCadence, str]] = {
    "burn": (PeriodicCadence.REFRESHED_BURN, "tick_interval"),
    "immolate": (PeriodicCadence.CONTINUOUS_AURA, "event_interval"),
    "periodic_aoe": (PeriodicCadence.FIXED_INTERVAL, "interval"),
}

# The key a burn's re-armed window lives under.
BURN_DURATION_KEY = "duration"

# The two keys a fixed-interval strike may publish beside its damage: the
# radius its event receipt names, and the share of its post-mitigation damage
# the holder heals for.
AOE_RANGE_KEY = "range_units"
SELF_HEAL_SHARE_KEY = "self_heal_post_mitigation_multiplier"

# The registry key an active's life-steal inheritance lives under.  Absent
# means the active inherits none — a declared ``None``, not a zero.
LIFESTEAL_EFFECTIVENESS_KEY = "lifesteal_effectiveness"

# The key every item-registry cooldown lives under.
COOLDOWN_KEY = "cooldown"

# The registry's spelling for "this item also pays per ability hit".  Named
# once so the declaration and the build projection read one string.
PER_ABILITY_HIT_BEHAVIOR = "per_ability_hit"

# The fight's own ``t = 0``.  A coordinate the model measures from, not a
# quantity anybody patches, which is what ``origin`` says and ``count`` would
# not.
COMBAT_START = Const(0.0, "origin")

# The origin of the multiplier axis.  A registry entry that states an
# amplifier as a *multiplier* (Shadowflame's Cinderbloom is 120%) states the
# same mechanic the chain prices as a *fraction*; 1.0 is the coordinate the
# two are measured from, not a quantity anybody patches.
MULTIPLIER_ORIGIN = Const(1.0, "origin")

# How long the engine assumes one whole-total amp stack takes to accrue.  A
# modelling assumption, not a wiki number — Spear of Shojin stacks per
# ability cast and the compact damage model does not simulate casts for this
# purpose — so it is declared where a reader can see and challenge it rather
# than living as a `duration / 2` inside the arithmetic.
ASSUMED_SECONDS_PER_AMP_STACK = Const(2.0, "unit_scale")

# How many stack-applying ability hits the pair engine assumes precede the
# auto stream it counts for Black Cleaver's Carve.  A modelling assumption
# about the rotation's shape, not a wiki number, and it was living as a
# ``+ 4`` inside the averaging helper where no reader could challenge it.
ASSUMED_CARVE_LEADING_ABILITY_HITS = Const(4.0, "count")

# The declaration a shred makes when it counts every applying event exactly
# and assumes nothing preceded the stream.  Spelled rather than defaulted:
# "no leading stacks" is a claim about the model, and a defaulted zero would
# be the same silence this phase removes from the other side.
NO_LEADING_STACKS = Const(0.0, "count")


def _declares_secondary(
    registry: ValueRegistry, entry: Mapping[str, Any], family: RuleFamily
) -> bool:
    """Whether *entry*'s value keys declare a second mechanic in *family*."""
    return any(
        key in entry
        for key, declared in SECONDARY_KEY_FAMILY[registry].items()
        if declared is family
    )


@cache
def _mechanic_slug(owner: str) -> str:
    """An owner's identifier spelling, matching the bus's mechanic ids.

    Lower case, apostrophes dropped, other non-alphanumeric runs collapsed to
    one underscore, so a mechanic id and a capability key cannot drift apart.
    """
    stripped = owner.replace("'", "").replace("’", "")
    slug = "".join(char if char.isalnum() else "_" for char in stripped.lower())
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_")


def _all_damage_typing() -> Typing:
    """Every damage class from every attack class, "from all sources" said.

    Enumerated rather than empty, so "all" cannot drift into "all remembered".
    """
    return Typing(
        damage_classes=frozenset(DamageClass),
        attack_classes=frozenset(AttackClass),
    )


def _part_amp_typing(attack_class: AttackClass) -> Typing:
    """Every damage class, delivered by one attack class.

    A per-part amp restricts how damage arrived, not what mitigates it.
    """
    return Typing(
        damage_classes=frozenset(DamageClass),
        attack_classes=frozenset({attack_class}),
    )


def _damage_class_amp_typing(damage_class: DamageClass) -> Typing:
    """One damage class however it arrived, the dual of the above: a curse
    restricts what mitigates a number rather than how it was delivered, which
    is what makes it a different selector.
    """
    return Typing(
        damage_classes=frozenset({damage_class}),
        attack_classes=frozenset(AttackClass),
    )


def _ability_part_amp_rule(owner: str, registry: ValueRegistry) -> BehaviorRule:
    """Actualizer's Mana Made Real: every ability, while the active is up.

    The magnitude is a sourced base plus a sourced rate per 100 bonus mana,
    and the stat is *named* rather than resolved here — the holder's stat
    block is not a build fact, so the reading arrives at use.  The declared
    window is the sourced duration; how much of it a scenario authors is the
    item's own input option, which clips to exactly this number.
    """
    return BehaviorRule(
        family=RuleFamily.DELTA_AMP,
        owner=owner,
        mechanic_id=f"{_mechanic_slug(owner)}.ability_part_amp",
        payload=PartAmpRule(
            pool=Pool.ALL_EVENTS,
            activation=AbsoluteWindow(
                start=Const(0.0, "count"),
                end=ValueRef(registry, owner, "mana_made_real_duration"),
            ),
            consumption=Persist(),
            magnitude=StatScaled(
                base=ValueRef(registry, owner, "base_amp"),
                per_hundred=ValueRef(registry, owner, "amp_per_100_bonus_mana"),
                stat=HolderStat.BONUS_MANA,
            ),
            typing=_part_amp_typing(AttackClass.ABILITY),
            bonus_typing=BonusTyping.SAME_AS_SOURCE,
            subject=Subject.HOLDER,
        ),
        compilability=AMP_COMPILABILITY,
        receipt=receipt_for(
            registry, owner, declared=cached_source_receipt(owner, CACHED_ITEM_SOURCE)
        ),
        zero_policy=ZeroPolicy(
            Disposition.MEASURED,
            "the amp is a sourced base plus a sourced rate on the holder's "
            "own bonus mana; a zero means the holder bought no mana, which "
            "the rule measured",
        ),
    )


def _basic_part_amp_rule(owner: str, registry: ValueRegistry) -> BehaviorRule:
    """Hexoptics C44's Magnification: every basic-damage part, all fight.

    The range split is the fight's one modelling assumption and it is
    declared rather than computed: a ranged holder is assumed to attack from
    the full Magnification distance and earns the whole amp, a melee holder
    from the sourced assumed distance and earns the amp scaled by the ratio
    of the two — a derivation over sourced numbers, so a patch that re-tunes
    either moves the fight without touching this declaration.
    """
    max_amp = ValueRef(registry, owner, "max_amp")
    max_distance = ValueRef(registry, owner, "max_distance")
    return BehaviorRule(
        family=RuleFamily.DELTA_AMP,
        owner=owner,
        mechanic_id=f"{_mechanic_slug(owner)}.basic_part_amp",
        payload=PartAmpRule(
            pool=Pool.ALL_EVENTS,
            activation=Always(),
            consumption=Persist(),
            magnitude=MeleeRangedSplit(
                melee=DerivedValueRef(
                    "MUL",
                    (
                        max_amp,
                        DerivedValueRef(
                            "RATIO",
                            (
                                DerivedValueRef(
                                    "MIN",
                                    (
                                        ValueRef(
                                            registry, owner, "melee_assumed_distance"
                                        ),
                                        max_distance,
                                    ),
                                ),
                                max_distance,
                            ),
                        ),
                    ),
                ),
                ranged=max_amp,
            ),
            typing=_part_amp_typing(AttackClass.BASIC_ATTACK),
            bonus_typing=BonusTyping.SAME_AS_SOURCE,
            subject=Subject.HOLDER,
        ),
        compilability=AMP_COMPILABILITY,
        receipt=receipt_for(
            registry, owner, declared=cached_source_receipt(owner, CACHED_ITEM_SOURCE)
        ),
        zero_policy=ZeroPolicy(
            Disposition.MEASURED,
            "the amp is a sourced ratio scaled by the declared range "
            "assumption; a zero would mean the registry holds zero, which is "
            "a measurement",
        ),
    )


def _magic_part_amp_rule(owner: str, registry: ValueRegistry) -> BehaviorRule:
    """Abyssal Mask's Unmake: every magic part the cursed target takes.

    Not a chain slot and deliberately so — the curse multiplies each magic
    packet where ``damage._mitigate`` prices it, which is what the two
    attack-class part amps do for their own deliveries.  The mechanic id is
    the one ``trigger_stream`` already pairs the walk's aura against, so the
    pair half it names is now a declaration rather than a ladder field.
    """
    return BehaviorRule(
        family=RuleFamily.DELTA_AMP,
        owner=owner,
        mechanic_id=f"{_mechanic_slug(owner)}.magic_amp",
        payload=PartAmpRule(
            pool=Pool.ALL_EVENTS,
            activation=Always(),
            consumption=Persist(),
            magnitude=Fixed(ValueRef(registry, owner, MAGIC_AMP_KEY)),
            typing=_damage_class_amp_typing(DamageClass.MAGIC),
            bonus_typing=BonusTyping.SAME_AS_SOURCE,
            subject=Subject.TARGET,
        ),
        compilability=AMP_COMPILABILITY,
        receipt=receipt_for(
            registry, owner, declared=cached_source_receipt(owner, CACHED_ITEM_SOURCE)
        ),
        zero_policy=ZeroPolicy(
            Disposition.MEASURED,
            "the curse is a sourced share added to every magic packet the "
            "target takes; a zero would mean the registry holds zero, which "
            "is a measurement",
        ),
    )


def _hypershot_rule(owner: str, registry: ValueRegistry) -> BehaviorRule:
    """Horizon Focus's Hypershot: everything except the cast that armed it.

    The exclusion set is "the trigger ability's own damage" — a pair-local
    rotation fact, which is why the mechanic is ``PAIR_ONLY`` and the coupled
    walk emits nothing for it.
    """
    return BehaviorRule(
        family=RuleFamily.DELTA_AMP,
        owner=owner,
        mechanic_id="horizon_focus.hypershot",
        payload=DeltaAmpRule(
            pool=Pool.ALL_EVENTS,
            activation=ExcludeTrigger(
                trigger=TriggerEvent.ABILITY_HIT,
                isolation=Isolation.TRIGGER_EVENT_ONLY,
            ),
            consumption=Persist(),
            magnitude=Fixed(ValueRef(registry, owner, "amp")),
            typing=_all_damage_typing(),
            bonus_typing=BonusTyping.SAME_AS_SOURCE,
            subject=Subject.HOLDER,
            lane_chain_rank=chain_rank(AmpChainSlot.HYPERSHOT),
        ),
        compilability=AMP_COMPILABILITY,
        receipt=receipt_for(
            registry, owner, declared=cached_source_receipt(owner, CACHED_ITEM_SOURCE)
        ),
        zero_policy=ZeroPolicy(
            Disposition.MEASURED,
            "the amp is a sourced ratio read live from the registry; a zero "
            "here would mean the registry holds zero, which is a measurement",
        ),
    )


def _whole_total_magnitude(
    owner: str, registry: ValueRegistry, entry: Mapping[str, Any]
) -> Magnitude:
    """Which magnitude shape one whole-total amp's value keys describe.

    The ladder is the registry's own schema ladder, in its order, because an
    entry carrying two of these keys must keep resolving to the same shape it
    resolved to before.  An entry the ladder does not recognise is a stop:
    the alternative is an item that quietly amplifies nothing.
    """
    if "health_state_damage_amp_above_half" in entry:
        # The public scenario starts at full health; the below-half branch is
        # a healing rule the ordered survival ledger owns, so the amp's
        # above-half starting state is declared rather than guessed.
        return Fixed(ValueRef(registry, owner, "health_state_damage_amp_above_half"))
    for per_second, maximum in (
        ("damage_amp_per_second", "damage_amp_max"),
        ("amp_per_second", "amp_max"),
    ):
        if per_second in entry:
            return RampPerSecond(
                per_second=ValueRef(registry, owner, per_second),
                maximum=ValueRef(registry, owner, maximum),
            )
    if "bonus_hp_cap" in entry:
        return TargetBonusHealthScaled(
            maximum=ValueRef(registry, owner, "max_amp"),
            bonus_health_cap=ValueRef(registry, owner, "bonus_hp_cap"),
        )
    if "amp_per_stack" in entry:
        return RampPerStack(
            per_stack=ValueRef(registry, owner, "amp_per_stack"),
            max_stacks=ValueRef(registry, owner, "max_stacks"),
            seconds_per_stack=ASSUMED_SECONDS_PER_AMP_STACK,
            model=RampModel.EXACT,
        )
    raise BehaviorCatalogError(
        f"{registry}[{owner!r}] declares a whole-total amp in no shape the "
        "magnitude union names; a new schema is a new member and a new "
        "interpreter branch, never a silent zero"
    )


def _whole_total_rule(
    owner: str, registry: ValueRegistry, entry: Mapping[str, Any]
) -> BehaviorRule:
    """One general amplifier: the whole running total, for the whole fight.

    The occupants of this slot are additive among themselves and multiply
    everything the earlier slots already moved, which is why they share one
    chain rank rather than each having their own.
    """
    return BehaviorRule(
        family=RuleFamily.DELTA_AMP,
        owner=owner,
        mechanic_id=f"{_mechanic_slug(owner)}.whole_total_amp",
        payload=DeltaAmpRule(
            pool=Pool.ALL_EVENTS,
            activation=Always(),
            consumption=Persist(),
            magnitude=_whole_total_magnitude(owner, registry, entry),
            typing=_all_damage_typing(),
            bonus_typing=BonusTyping.SAME_AS_SOURCE,
            subject=Subject.HOLDER,
            lane_chain_rank=chain_rank(AmpChainSlot.WHOLE_TOTAL),
        ),
        compilability=AMP_COMPILABILITY,
        receipt=receipt_for(
            registry, owner, declared=cached_source_receipt(owner, CACHED_ITEM_SOURCE)
        ),
        zero_policy=ZeroPolicy(
            Disposition.MEASURED,
            "the amp is a sourced ratio scaled by declared fight facts; a "
            "zero means the ramp had no time or the target no bonus health, "
            "both of which the rule measured",
        ),
    )


def _opening_window_rule(owner: str, registry: ValueRegistry) -> BehaviorRule:
    """A First Strike-class keystone: the opening seconds of the exchange.

    The window is absolute because the engine's is: a continuous fight
    initiates combat once, at ``t = 0``, so the buff covers ``[0, duration)``
    rather than tracking a re-entry the model has no way to reach.  The bonus
    lands as true damage whatever it amplified, which is why ``bonus_typing``
    exists as a separate axis from ``typing``.
    """
    return BehaviorRule(
        family=RuleFamily.DELTA_AMP,
        owner=owner,
        mechanic_id=f"{_mechanic_slug(owner)}.opening_window_amp",
        payload=DeltaAmpRule(
            pool=Pool.CERTIFIED_ONLY,
            activation=AbsoluteWindow(
                start=COMBAT_START,
                end=ValueRef(registry, owner, "buff_duration_seconds"),
            ),
            consumption=Persist(),
            magnitude=Fixed(ValueRef(registry, owner, "bonus_true_damage_ratio")),
            typing=_all_damage_typing(),
            bonus_typing=BonusTyping.TRUE,
            subject=Subject.HOLDER,
            lane_chain_rank=chain_rank(AmpChainSlot.OPENING_WINDOW),
        ),
        compilability=AMP_COMPILABILITY,
        receipt=receipt_for(
            registry, owner, declared=cached_source_receipt(owner, CACHED_RUNE_SOURCE)
        ),
        zero_policy=ZeroPolicy(
            Disposition.MEASURED,
            "the bonus is a sourced ratio of the certified damage inside the "
            "window; a zero means nothing certified landed there, which the "
            "rule measured over the ledger",
        ),
    )


def _post_immobilize_rule(owner: str, registry: ValueRegistry) -> BehaviorRule:
    """Imperial Mandate's Command: the window an immobilize opens.

    **One declaration, both engines.**  An immobilize marks the target
    *Vulnerable* and every attacker's damage inside the window is amplified,
    which is why the subject is ``ANY_ATTACKER``: the pair engine prices the
    holder's own contribution and the coupled walk prices everyone else's,
    but the *rule* is one rule and the two halves must not be free to drift
    into two readings of it.  Three facts, all of them declared:

    * ``TriggerWindow(IMMOBILIZE, …)`` — the trigger is an immobilize and
      nothing wider; the bus's ``CC`` stream is where that lands (D-08).
    * ``merge=REFRESH`` — a second immobilize moves the mark's expiry to its
      own time plus the duration, rather than opening a second window or
      adding a second amp (D-12).  This is what both engines compute, and the
      name is now the one they compute: ``EXTEND``'s additive reading is a
      third answer neither of them has ever given.  The Wiki's wording admits
      that third answer and is filed as a divergence
      (:data:`ACKNOWLEDGED_READING_DIVERGENCES`).
    * ``boundary=OPEN_CLOSED`` — the trigger itself is outside the window and
      an event exactly on the expiry is inside (D-13).

    The authority move to ``COUPLED_AUTHORITATIVE_WITH_PAIR_PREVIEW`` is
    Phase 4's and is blocked on H2; this slice does not move it.
    """
    return BehaviorRule(
        family=RuleFamily.DELTA_AMP,
        owner=owner,
        mechanic_id=f"{_mechanic_slug(owner)}.command",
        payload=DeltaAmpRule(
            pool=Pool.ALL_EVENTS,
            activation=TriggerWindow(
                trigger=TriggerEvent.IMMOBILIZE,
                duration=ValueRef(registry, owner, "command_duration"),
                merge=WindowMerge.REFRESH,
                boundary=WindowBoundary.OPEN_CLOSED,
            ),
            consumption=Persist(),
            magnitude=Fixed(ValueRef(registry, owner, "command_damage_amp")),
            typing=_all_damage_typing(),
            bonus_typing=BonusTyping.SAME_AS_SOURCE,
            subject=Subject.ANY_ATTACKER,
            lane_chain_rank=chain_rank(AmpChainSlot.POST_IMMOBILIZE),
        ),
        compilability=AMP_COMPILABILITY,
        receipt=receipt_for(
            registry, owner, declared=cached_source_receipt(owner, CACHED_ITEM_SOURCE)
        ),
        zero_policy=ZeroPolicy(
            Disposition.MEASURED,
            "the amp is a sourced ratio of the damage inside a window an "
            "authored immobilize opened; a zero means no immobilize was "
            "authored or nothing landed inside the window, and the walk over "
            "the ledger is what measured that",
        ),
    )


def _expose_weakness_rule(owner: str, registry: ValueRegistry) -> BehaviorRule:
    """Bloodsong's Expose Weakness — **the pair engine's reading of it**.

    This declaration is deliberately *not* the mechanic's whole truth, and
    the difference is the point.  The pair engine prices one amp of the
    holder's running total, less the chain that armed the buff (the first
    ability cast, the first attack that consumed it, and the first empowered
    proc), filed as one coarse row carrying no authored events.  The coupled
    walk arms a timed modifier per proc, on a cooldown, and prices each
    roster attacker's packets inside it.  Those are two different numbers
    for one item.

    Freezing the pair reading here — with
    ``DIVERGENCES["bloodsong.expose_weakness"]`` naming both readings, their
    source and the phase that reconciles them — is what keeps the
    disagreement a *declared* one.  Unifying it inside a slice labelled a
    pure refactor would land a semantic correction under a zero-diff claim,
    which is the shape this campaign exists to end.  Phase 4 corrects it.
    """
    return BehaviorRule(
        family=RuleFamily.DELTA_AMP,
        owner=owner,
        mechanic_id=f"{_mechanic_slug(owner)}.expose_weakness",
        payload=DeltaAmpRule(
            pool=Pool.COARSE_ROW,
            activation=ExcludeTrigger(
                trigger=TriggerEvent.BASIC_ATTACK_HIT,
                isolation=Isolation.TRIGGER_SEQUENCE,
            ),
            consumption=Persist(),
            magnitude=MeleeRangedSplit(
                melee=ValueRef(registry, owner, "expose_weakness_melee"),
                ranged=ValueRef(registry, owner, "expose_weakness_ranged"),
            ),
            typing=_all_damage_typing(),
            bonus_typing=BonusTyping.SAME_AS_SOURCE,
            subject=Subject.ANY_ATTACKER,
            lane_chain_rank=chain_rank(AmpChainSlot.EXPOSE_WEAKNESS),
        ),
        compilability=AMP_COMPILABILITY,
        receipt=receipt_for(
            registry, owner, declared=cached_source_receipt(owner, CACHED_ITEM_SOURCE)
        ),
        zero_policy=ZeroPolicy(
            Disposition.MEASURED,
            "the amp is a sourced ratio of the total left after the arming "
            "chain; a zero means the spellblade never procced or nothing "
            "landed after it, which the rule measured over the ledger",
        ),
    )


def _cinderbloom_rule(owner: str, registry: ValueRegistry) -> BehaviorRule:
    """Shadowflame's Cinderbloom: the one amp whose pool is not precomputable.

    Every other amp in the chain resolves to a number before the first event
    exists.  This one reads the target's health *at the instant of the hit*,
    under fire from a whole roster, so forcing it into a window would make
    the algebra claim a certainty the mechanic does not have.  It declares a
    :class:`~.item_behavior.LivePredicate`, whose ``requires_live_pool`` is a
    property of the shape rather than a flag a caller may forget, and the
    interpreter compiles the *threshold* while the *reading* arrives event by
    event.

    The magnitude is a subtraction because the registry states the mechanic
    the way the Wiki does — "critically strike for 120% damage" — and the
    chain prices fractions.  Declaring ``crit_multiplier - 1`` keeps the
    sourced number the one the page states, instead of a second number
    nobody can check against it.

    Subject is the holder: the cached text reads "**Your** magic damage and
    true damage will critically strike".  The authority is nevertheless
    coupled-with-preview, because the *predicate* reads a roster fact — how
    much health the target has left under everyone's fire — and that move is
    Phase 4's, last of seven.
    """
    return BehaviorRule(
        family=RuleFamily.DELTA_AMP,
        owner=owner,
        mechanic_id=f"{_mechanic_slug(owner)}.cinderbloom",
        payload=DeltaAmpRule(
            pool=Pool.ALL_EVENTS,
            activation=LivePredicate(
                probe=Probe.TARGET_HEALTH_FRACTION,
                cmp=Comparison.LT,
                threshold=ValueRef(registry, owner, "health_threshold"),
            ),
            consumption=Persist(),
            magnitude=Fixed(
                DerivedValueRef(
                    "SUB",
                    (
                        ValueRef(registry, owner, "crit_multiplier"),
                        MULTIPLIER_ORIGIN,
                    ),
                )
            ),
            typing=_magic_and_true_typing(),
            bonus_typing=BonusTyping.SAME_AS_SOURCE,
            subject=Subject.HOLDER,
            lane_chain_rank=chain_rank(AmpChainSlot.CINDERBLOOM),
        ),
        compilability=AMP_COMPILABILITY,
        receipt=receipt_for(
            registry, owner, declared=cached_source_receipt(owner, CACHED_ITEM_SOURCE)
        ),
        zero_policy=ZeroPolicy(
            Disposition.MEASURED,
            "the bonus is a sourced ratio of the magic and true damage that "
            "landed while the target was under the declared health "
            "threshold; a zero means the target never went low enough or "
            "nothing qualifying landed there, which the ordered ledger "
            "measured",
        ),
    )


def _magic_and_true_typing() -> Typing:
    """The two damage classes Cinderbloom crits, from every attack class.

    Physical is excluded by the mechanic, and the declaration says so.
    """
    return Typing(
        damage_classes=frozenset({DamageClass.MAGIC, DamageClass.TRUE}),
        attack_classes=frozenset(AttackClass),
    )


def _compile_ally_delta_amp(
    owner: str, registry: ValueRegistry, entry: Mapping[str, Any]
) -> tuple[BehaviorRule, ...]:
    """The amp-chain slots one ally-registry record declares.

    Dispatch is on the value keys, through :data:`ALLY_DELTA_AMP_SLOTS`,
    which is the closed key set that makes it total — the same device
    :data:`RUNE_AMP_SLOTS` is for runes, and for the same reason: the record
    carries no effect tag to dispatch on.  A record holding some of a slot's
    keys and not the rest raises: routing on key presence must not let a
    broken parse read as an item that declares no amplifier.
    """
    rules: list[BehaviorRule] = []
    for slot, keys in ALLY_DELTA_AMP_SLOTS.items():
        missing = [key for key in keys if key not in entry]
        if len(missing) == len(keys):
            continue
        if missing:
            raise BehaviorCatalogError(
                f"ALLY_ITEM_EFFECTS[{owner!r}] declares the {slot.value} chain "
                f"slot and is missing {missing}; a partly-parsed amplifier is a "
                "registry defect, not an item that quietly amplifies nothing"
            )
        if slot is AmpChainSlot.EXPOSE_WEAKNESS:
            rules.append(_expose_weakness_rule(owner, registry))
            continue
        if slot is AmpChainSlot.POST_IMMOBILIZE:
            rules.append(_post_immobilize_rule(owner, registry))
            continue
        raise BehaviorCatalogError(
            f"ALLY_ITEM_EFFECTS[{owner!r}] is declared in the {slot.value} chain "
            "slot and no compiler builds that slot's rule yet"
        )
    return tuple(rules)


def _non_true_typing() -> Typing:
    """Every attack class, but only the two damage classes resistances touch.

    True damage is excluded by the mechanic, and the declaration says so.
    """
    return Typing(
        damage_classes=frozenset({DamageClass.MAGIC, DamageClass.PHYSICAL}),
        attack_classes=frozenset(AttackClass),
    )


def _lasting_proc_amp_rule(owner: str, registry: ValueRegistry) -> BehaviorRule:
    """A Press the Attack-class keystone: everything after the proc lands.

    ``AfterTrigger(strict=True)`` is the wiki's triggering-attack rule: the
    swing that procs the buff, and the proc itself, land the same instant the
    buff turns on and are therefore outside it.  The exclusion of true damage
    is the rule's ``typing``, not a comparison inside the ledger filter.
    """
    return BehaviorRule(
        family=RuleFamily.DELTA_AMP,
        owner=owner,
        mechanic_id=f"{_mechanic_slug(owner)}.lasting_proc_amp",
        payload=DeltaAmpRule(
            pool=Pool.CERTIFIED_ONLY,
            activation=AfterTrigger(trigger=TriggerEvent.BASIC_ATTACK_HIT, strict=True),
            consumption=Persist(),
            magnitude=Fixed(ValueRef(registry, owner, "damage_amp_ratio")),
            typing=_non_true_typing(),
            bonus_typing=BonusTyping.SAME_AS_SOURCE,
            subject=Subject.HOLDER,
            lane_chain_rank=chain_rank(AmpChainSlot.LASTING_PROC_AMP),
        ),
        compilability=AMP_COMPILABILITY,
        receipt=receipt_for(
            registry, owner, declared=cached_source_receipt(owner, CACHED_RUNE_SOURCE)
        ),
        zero_policy=ZeroPolicy(
            Disposition.MEASURED,
            "the amp is a sourced ratio of the certified non-true damage after "
            "the first proc; a zero means nothing qualifying landed after it, "
            "which the rule measured over the ledger",
        ),
    )


def _cached_health_gate(owner: str) -> Comparison:
    """Which side of its threshold *owner*'s cached description arms on.

    Read from the cache and then checked against
    :data:`TARGET_HEALTH_GATE_DIRECTIONS`, so neither source can quietly win:
    a description whose halves were reordered stops the rune instead of
    pricing it as its opposite, and a direction this catalog states against a
    cache that says otherwise stops too.
    """
    stated = str(rune_effects.cached_effects(owner).value("damage_amp_health_gate"))
    cached = CACHED_HEALTH_GATE_WORDS.get(stated)
    if cached is None:
        raise BehaviorCatalogError(
            f"RUNE_EFFECTS[{owner!r}] states the {stated!r} health gate, which "
            f"is not one of {sorted(CACHED_HEALTH_GATE_WORDS)} — wiki parse "
            "degraded or a gate no chain slot reads"
        )
    declared = TARGET_HEALTH_GATE_DIRECTIONS[owner]
    if cached is not declared:
        raise BehaviorCatalogError(
            f"RUNE_EFFECTS[{owner!r}] states a {stated!r} gate and this catalog "
            f"declares the {declared.value} one — wiki description reordered"
        )
    return declared


def _target_health_gate_rule(owner: str, registry: ValueRegistry) -> BehaviorRule:
    """A Coup de Grace-class rune: everything landing on one side of a gate.

    The second amp whose pool is not precomputable, and the same shape
    Cinderbloom declares: the *threshold* is a sourced share of the target's
    maximum health and compiles at build time, while the *reading* — how much
    health the target has left when this packet lands — arrives event by
    event.  Which side arms is the rule's ``cmp``, so Coup de Grace and Cut
    Down are one declaration with one number different rather than two
    walkers.

    ``Pool.ALL_EVENTS`` and every damage class: the wiki gates these on the
    target's health and on nothing about the damage, so a filter here would
    be a restriction no source states.
    """
    return BehaviorRule(
        family=RuleFamily.DELTA_AMP,
        owner=owner,
        mechanic_id=f"{_mechanic_slug(owner)}.target_health_gate",
        payload=DeltaAmpRule(
            pool=Pool.ALL_EVENTS,
            activation=LivePredicate(
                probe=Probe.TARGET_HEALTH_FRACTION,
                cmp=_cached_health_gate(owner),
                threshold=ValueRef(registry, owner, "damage_amp_health_ratio"),
            ),
            consumption=Persist(),
            magnitude=Fixed(ValueRef(registry, owner, "damage_amp_ratio")),
            typing=_all_damage_typing(),
            bonus_typing=BonusTyping.SAME_AS_SOURCE,
            subject=Subject.HOLDER,
            lane_chain_rank=chain_rank(AmpChainSlot.TARGET_HEALTH_GATE),
        ),
        compilability=AMP_COMPILABILITY,
        receipt=receipt_for(
            registry, owner, declared=cached_source_receipt(owner, CACHED_RUNE_SOURCE)
        ),
        zero_policy=ZeroPolicy(
            Disposition.MEASURED,
            "the bonus is a sourced ratio of the timestamped damage that "
            "landed while the target's health satisfied the declared gate; a "
            "zero means none did, which the ordered ledger measured",
        ),
    )


def _compile_rune_amp(owner: str) -> tuple[BehaviorRule, ...]:
    """The amp-chain slots one compiled rune declares.

    Dispatch is on the rune's name because a rune record has no effect tag to
    dispatch on — the shape *is* the rune.  That is
    ``rune_effects._compilers()``' own idiom, and :data:`RUNE_AMP_SLOTS` is
    the closed key set that makes it total.
    """
    slot = RUNE_AMP_SLOTS[owner]
    if slot is AmpChainSlot.OPENING_WINDOW:
        return (_opening_window_rule(owner, "RUNE_EFFECTS"),)
    if slot is AmpChainSlot.LASTING_PROC_AMP:
        return (_lasting_proc_amp_rule(owner, "RUNE_EFFECTS"),)
    if slot is AmpChainSlot.TARGET_HEALTH_GATE:
        return (_target_health_gate_rule(owner, "RUNE_EFFECTS"),)
    raise BehaviorCatalogError(
        f"RUNE_EFFECTS[{owner!r}] is declared in the {slot.value} chain slot "
        "and no compiler builds that slot's rule yet"
    )


def _compile_delta_amp(
    family: RuleFamily,
    owner: str,
    registry: ValueRegistry,
    entry: Mapping[str, Any],
) -> tuple[BehaviorRule, ...]:
    """Compile the amp-chain slots one registry entry declares.

    Dispatch is on the entry's **tag** and value keys, never on the owner's
    name: the shape comes from the tag, the numbers from a
    :class:`~.value_ref.ValueRef` into the entry, and the owner from whichever
    item the registry hung it on — so no item name is a literal here and none
    needs to be.
    """
    del family
    rules: list[BehaviorRule] = []
    if registry == "RUNE_EFFECTS":
        rules.extend(_compile_rune_amp(owner))
    elif registry == "ALLY_ITEM_EFFECTS":
        rules.extend(_compile_ally_delta_amp(owner, registry, entry))
    else:
        tag = str(entry.get("type"))
        if tag == "ability_damage_amp":
            rules.append(_ability_part_amp_rule(owner, registry))
        if tag == "basic_damage_amp":
            rules.append(_basic_part_amp_rule(owner, registry))
        if tag == "hypershot_amp":
            rules.append(_hypershot_rule(owner, registry))
        if tag == "magic_damage_amp":
            rules.append(_magic_part_amp_rule(owner, registry))
        if tag == "magic_true_crit":
            rules.append(_cinderbloom_rule(owner, registry))
        if tag == "damage_amp" or _declares_secondary(
            registry, entry, RuleFamily.DELTA_AMP
        ):
            rules.append(_whole_total_rule(owner, registry, entry))
    for rule in rules:
        validate_rule(rule)
    return tuple(rules)


def _rate_reference(
    owner: str, registry: ValueRegistry, keys: str | tuple[str, str]
) -> ValueRef | MeleeRangedSplit:
    """One schema rate: a single sourced key, or a melee/ranged pair of them."""
    if isinstance(keys, tuple):
        melee_key, ranged_key = keys
        return MeleeRangedSplit(
            melee=ValueRef(registry, owner, melee_key),
            ranged=ValueRef(registry, owner, ranged_key),
        )
    return ValueRef(registry, owner, keys)


def _formula_terms(
    owner: str, registry: ValueRegistry, schema: tuple[TermSchema, ...]
) -> tuple[Term, ...]:
    """One registry schema's terms, in the order the schema names them.

    Order is load-bearing: the registry's own compilers summed their shares in
    the order their formula name spelled them, and floating-point addition is
    not associative.  A schema that lists them in that order is what makes the
    migration reproduce the same float.
    """
    terms: list[Term] = []
    for basis, keys in schema:
        if isinstance(keys, LevelSteppedKeys):
            coefficient = LevelSteppedRate(
                base=_rate_reference(owner, registry, keys.base),
                per_level=_rate_reference(owner, registry, keys.per_level),
                from_level=ValueRef(registry, owner, keys.from_level_key),
            )
        elif isinstance(keys, LevelRampKeys):
            coefficient = LevelValueRef(
                registry, owner, keys.min_key, keys.max_key, keys.scale
            )
        elif isinstance(keys, tuple):
            melee_key, ranged_key = keys
            coefficient = MeleeRangedSplit(
                melee=ValueRef(registry, owner, melee_key),
                ranged=ValueRef(registry, owner, ranged_key),
            )
        else:
            coefficient = ValueRef(registry, owner, keys)
        terms.append(Term(coefficient=coefficient, basis=basis))
    return tuple(terms)


def _damage_formula(
    owner: str,
    registry: ValueRegistry,
    entry: Mapping[str, Any],
    schemas: Mapping[str, tuple[TermSchema, ...]],
    floors: Mapping[str, str],
    *,
    scaling: Scaling | None = None,
    damage_class: DamageClass | None = None,
    formula_name: str | None = None,
) -> DamageFormula:
    """The declared formula one entry's ``formula`` name describes.

    The registry names a shape and this resolves that name into the shares it
    is made of.  A name the table does not carry is a stop, never a strike
    that quietly deals nothing: the whole point of the closed vocabulary is
    that a new schema costs one deliberate decision.

    ``scaling``, ``damage_class`` and ``formula_name`` are the three things a
    schema name cannot always say: a factor over the whole sum belongs to the
    mechanic rather than to the shape, and one registry tag carries neither a
    ``damage_type`` key nor a ``formula`` key at all because both are part of
    its mechanic's definition.  All three default to what the entry states.
    """
    name = str(entry.get("formula")) if formula_name is None else formula_name
    schema = schemas.get(name)
    if schema is None:
        raise BehaviorCatalogError(
            f"{registry}[{owner!r}] declares formula {name!r}, which no term "
            "schema describes; a new registry schema is a new entry in the "
            "table, never a silent zero"
        )
    floor_key = floors.get(name)
    return DamageFormula(
        terms=_formula_terms(owner, registry, schema),
        scaling=NoScaling() if scaling is None else scaling,
        floor=(
            AtLeast(ValueRef(registry, owner, floor_key))
            if floor_key is not None
            else NoFloor()
        ),
        damage_class=(
            DamageClass(str(entry.get("damage_type")))
            if damage_class is None
            else damage_class
        ),
    )


def _on_hit_strike_rule(
    owner: str, registry: ValueRegistry, entry: Mapping[str, Any]
) -> BehaviorRule:
    """One item's on-hit strike: the damage every basic attack carries.

    ``superseded_by_ability_proc`` is the Wiki's no-double-dip rule, declared
    rather than inferred at the point of use: an item that also pays per
    ability hit pays the ability number instead of this one when an ability
    carries the on-hit application, and that is a property of the mechanic
    rather than of whichever loop happens to be reading it.
    """
    return BehaviorRule(
        family=RuleFamily.ON_HIT_STRIKE,
        owner=owner,
        mechanic_id=f"{_mechanic_slug(owner)}.on_hit",
        payload=OnHitStrikeRule(
            formula=_damage_formula(
                owner, registry, entry, ON_HIT_FORMULA_TERMS, ON_HIT_FORMULA_FLOORS
            ),
            superseded_by_ability_proc=(
                entry.get("secondary_behavior") == PER_ABILITY_HIT_BEHAVIOR
            ),
        ),
        compilability=Compilable(),
        receipt=receipt_for(
            registry, owner, declared=cached_source_receipt(owner, CACHED_ITEM_SOURCE)
        ),
        zero_policy=ZeroPolicy(
            Disposition.MEASURED,
            "the strike is a sum of sourced shares of the holder's stats and "
            "the target's pools; a zero means every share resolved to zero, "
            "which the formula measured",
        ),
    )


def _compile_on_hit_strike(
    family: RuleFamily,
    owner: str,
    registry: ValueRegistry,
    entry: Mapping[str, Any],
) -> tuple[BehaviorRule, ...]:
    """Compile the on-hit strike one registry entry declares."""
    del family
    rule = _on_hit_strike_rule(owner, registry, entry)
    validate_rule(rule)
    return (rule,)


def _compile_secondary_target(
    family: RuleFamily,
    owner: str,
    registry: ValueRegistry,
    entry: Mapping[str, Any],
) -> tuple[BehaviorRule, ...]:
    """Compile the secondary-target strike one registry entry declares.

    The bolts carry a *share of the attack that fired them* rather than a
    formula of their own, which is why this family declares a count and a
    share instead of a :class:`~.item_behavior.DamageFormula`.
    """
    del family
    rule = BehaviorRule(
        family=RuleFamily.SECONDARY_TARGET,
        owner=owner,
        mechanic_id=f"{_mechanic_slug(owner)}.secondary_target",
        payload=SecondaryTargetRule(
            max_targets=ValueRef(registry, owner, "max_secondary_targets"),
            damage_share=ValueRef(registry, owner, "secondary_ad_ratio"),
            applies_on_hit=bool(entry.get("applies_on_hit", False)),
        ),
        compilability=Compilable(),
        receipt=receipt_for(
            registry, owner, declared=cached_source_receipt(owner, CACHED_ITEM_SOURCE)
        ),
        zero_policy=ZeroPolicy(
            Disposition.MEASURED,
            "the bolts are a sourced share of the attack that fired them, "
            "priced over the roster's own event ledger; a zero means no extra "
            "target was in range, which the ledger measured",
        ),
    )
    validate_rule(rule)
    return (rule,)


def _schema_keys(
    owner: str, registry: ValueRegistry, entry: Mapping[str, Any]
) -> frozenset[str]:
    """Which keys *owner*'s entry is expected to carry, not which it has."""
    if registry == "ITEM_EFFECTS":
        return item_effects.entry_schema_keys(owner)
    return frozenset(entry)


def _optional_ref(
    owner: str, registry: ValueRegistry, entry: Mapping[str, Any], key: str
) -> ValueRef | None:
    """A reference to *key*, or ``None`` where the schema does not carry it.

    Declared absence differs from a reference resolving to zero.  The schema
    is the test, so a dropped parse raises rather than reading as absent.
    """
    return (
        ValueRef(registry, owner, key)
        if key in _schema_keys(owner, registry, entry)
        else None
    )


def _sibling_refs(
    owner: str, registry: ValueRegistry, entry: Mapping[str, Any]
) -> dict[str, ValueRef | None]:
    """One entry's spellblade siblings, each group declared whole or not at all.

    Presence of *any* key of a group makes *every* key of it required, so a
    parse that dropped half of a sibling mechanic raises when the rule reads
    it rather than compiling a quietly weaker item.
    """
    schema = _schema_keys(owner, registry, entry)
    refs: dict[str, ValueRef | None] = {}
    for group in SPELLBLADE_SIBLING_GROUPS:
        declared = any(key in schema for key in group)
        for key in group:
            refs[key] = ValueRef(registry, owner, key) if declared else None
    return refs


def _group_refs(
    owner: str,
    registry: ValueRegistry,
    entry: Mapping[str, Any],
    keys: Sequence[str],
) -> tuple[ValueRef, ...] | None:
    """Every key of one sibling group, or ``None`` if the schema has none.

    Any key present makes every key required, so a dropped parse raises.
    """
    schema = _schema_keys(owner, registry, entry)
    if not any(key in schema for key in keys):
        return None
    return tuple(ValueRef(registry, owner, key) for key in keys)


def _cooldown_proc_rule(
    owner: str, registry: ValueRegistry, entry: Mapping[str, Any]
) -> BehaviorRule:
    """One item's cooldown proc: what arms it, how much, and what rides along."""
    trigger = ProcTrigger(str(entry.get(PROC_TRIGGER_KEY, DEFAULT_PROC_TRIGGER.value)))
    charged = (
        ChargedSplash(
            charges=ValueRef(registry, owner, CHARGE_COUNT_KEY),
            single_target_multiplier=ValueRef(
                registry, owner, SINGLE_TARGET_MULTIPLIER_KEY
            ),
        )
        if str(entry.get("formula")) == CHARGED_FORMULA
        else None
    )
    threshold_refs = (
        tuple(ValueRef(registry, owner, key) for key in THRESHOLD_KEYS)
        if trigger is ProcTrigger.DAMAGE_THRESHOLD
        else None
    )
    stack_refs = _group_refs(owner, registry, entry, STACK_GATE_KEYS)
    shield_refs = _group_refs(owner, registry, entry, SELF_SHIELD_KEYS)
    return BehaviorRule(
        family=RuleFamily.CAST_PROC,
        owner=owner,
        mechanic_id=f"{_mechanic_slug(owner)}.proc",
        payload=CooldownProcRule(
            formula=_damage_formula(
                owner,
                registry,
                entry,
                CAST_PROC_FORMULA_TERMS,
                {},
                scaling=(
                    TimesValue(charged.single_target_multiplier)
                    if charged is not None
                    else None
                ),
            ),
            cooldown=ValueRef(registry, owner, COOLDOWN_KEY),
            trigger=trigger,
            repeat_on_cooldown=bool(entry.get(REPEAT_ON_COOLDOWN_KEY, True)),
            is_ability_damage=bool(entry.get(IS_ABILITY_DAMAGE_KEY, False)),
            basic_damage=bool(entry.get(BASIC_DAMAGE_KEY, False)),
            late_phase=str(entry.get("type")) in LATE_PHASE_TAGS,
            threshold=(
                DamageThreshold(*threshold_refs) if threshold_refs is not None else None
            ),
            attack_cooldown_refund=(
                ValueRef(registry, owner, ATTACK_REFUND_KEY)
                if entry.get(ATTACK_REFUND_FLAG)
                else None
            ),
            charged=charged,
            stacks=StackGate(*stack_refs) if stack_refs is not None else None,
            self_shield=SelfShield(*shield_refs) if shield_refs is not None else None,
        ),
        compilability=(
            COMPILED_KERNEL_CANNOT_SELF_SHIELD
            if shield_refs is not None
            else Compilable()
        ),
        receipt=receipt_for(
            registry, owner, declared=cached_source_receipt(owner, CACHED_ITEM_SOURCE)
        ),
        zero_policy=ZeroPolicy(
            Disposition.MEASURED,
            "the proc is a sum of sourced shares priced once per arming; a "
            "zero means the trigger never armed or every share resolved to "
            "zero, both of which the rule measured",
        ),
    )


def _ultimate_proc_rule(
    owner: str, registry: ValueRegistry, entry: Mapping[str, Any]
) -> BehaviorRule:
    """One item's ultimate proc: a window an R cast opens."""
    return BehaviorRule(
        family=RuleFamily.CAST_PROC,
        owner=owner,
        mechanic_id=f"{_mechanic_slug(owner)}.ultimate_proc",
        payload=UltimateProcRule(
            formula=_damage_formula(
                owner, registry, entry, CAST_PROC_FORMULA_TERMS, {}
            ),
            duration=ValueRef(registry, owner, DURATION_KEY),
            mr_reduction=_optional_ref(owner, registry, entry, MR_REDUCTION_KEY),
        ),
        compilability=Compilable(),
        receipt=receipt_for(
            registry, owner, declared=cached_source_receipt(owner, CACHED_ITEM_SOURCE)
        ),
        zero_policy=ZeroPolicy(
            Disposition.MEASURED,
            "the ultimate proc is a sum of sourced shares spread over its "
            "declared window; a zero means the rotation cast no ultimate, "
            "which the rotation walk measured",
        ),
    )


def _empowered_hit_rule(
    owner: str, registry: ValueRegistry, entry: Mapping[str, Any]
) -> BehaviorRule:
    """One item's empowered hit: a charge spent on one attack, not every one."""
    energized = _group_refs(owner, registry, entry, ENERGIZED_KEYS)
    lethality = _group_refs(owner, registry, entry, TEMPORARY_LETHALITY_KEYS)
    chain = _group_refs(owner, registry, entry, CHAIN_TARGET_KEYS)
    return BehaviorRule(
        family=RuleFamily.CHARGED_STRIKE,
        owner=owner,
        mechanic_id=f"{_mechanic_slug(owner)}.empowered_hit",
        payload=EmpoweredHitRule(
            formula=_damage_formula(
                owner, registry, entry, CHARGED_STRIKE_FORMULA_TERMS, {}
            ),
            max_procs=(
                ValueRef(registry, owner, EMPOWERED_AUTO_COUNT_KEY)
                if entry.get(USES_EMPOWERED_AUTO_COUNT)
                else FIRES_ONCE
            ),
            basic_damage=bool(entry.get(BASIC_DAMAGE_KEY, False)),
            energized=(
                EnergizedCharge(
                    *energized,
                    abilities_also_charge=bool(
                        entry.get(ENERGIZED_ABILITY_FLAG, False)
                    ),
                )
                if energized is not None
                else None
            ),
            temporary_lethality=(
                TemporaryLethality(*lethality) if lethality is not None else None
            ),
            chain_targets=ChainTargets(*chain) if chain is not None else None,
        ),
        compilability=Compilable(),
        receipt=receipt_for(
            registry, owner, declared=cached_source_receipt(owner, CACHED_ITEM_SOURCE)
        ),
        zero_policy=ZeroPolicy(
            Disposition.MEASURED,
            "the empowered hit is a sum of sourced shares priced once per "
            "charge spent; a zero means the fight spent no charge or every "
            "share resolved to zero, both of which the rule measured",
        ),
    )


def _repeating_strike_rule(
    owner: str, registry: ValueRegistry, entry: Mapping[str, Any]
) -> BehaviorRule:
    """One item's every-Nth-hit strike.

    ``level_missing_hp`` is the schema whose base steps with level above a
    declared one and whose sum then grows with the target's missing health.
    Both are shapes rather than shares, which is why one is a coefficient and
    the other a scaling instead of two more terms.
    """
    scaling = (
        TimesMissingHealth(ValueRef(registry, owner, MISSING_HEALTH_BONUS_KEY))
        if MISSING_HEALTH_BONUS_KEY in _schema_keys(owner, registry, entry)
        else None
    )
    return BehaviorRule(
        family=RuleFamily.CHARGED_STRIKE,
        owner=owner,
        mechanic_id=f"{_mechanic_slug(owner)}.repeating_strike",
        payload=RepeatingStrikeRule(
            formula=_damage_formula(
                owner,
                registry,
                entry,
                CHARGED_STRIKE_FORMULA_TERMS,
                {},
                scaling=scaling,
            ),
            hits_required=ValueRef(registry, owner, HITS_REQUIRED_KEY),
            basic_damage=bool(entry.get(BASIC_DAMAGE_KEY, False)),
        ),
        compilability=Compilable(),
        receipt=receipt_for(
            registry, owner, declared=cached_source_receipt(owner, CACHED_ITEM_SOURCE)
        ),
        zero_policy=ZeroPolicy(
            Disposition.MEASURED,
            "the strike is a sum of sourced shares priced every declared "
            "number of on-hit applications; a zero means the fight landed "
            "fewer, which the swing schedule measured",
        ),
    )


def _shaped_charge_rule(
    owner: str, registry: ValueRegistry, entry: Mapping[str, Any]
) -> BehaviorRule:
    """One item's shaped charge: true damage an ability arms, on a cooldown.

    The registry entry names neither a formula nor a damage type, because both
    are part of this mechanic's definition rather than of the item's tuning.
    The compiler supplies them, which is why they are arguments here and not
    a fourth and fifth key nobody would source.
    """
    return BehaviorRule(
        family=RuleFamily.CHARGED_STRIKE,
        owner=owner,
        mechanic_id=f"{_mechanic_slug(owner)}.shaped_charge",
        payload=ShapedChargeRule(
            formula=_damage_formula(
                owner,
                registry,
                entry,
                CHARGED_STRIKE_FORMULA_TERMS,
                {},
                damage_class=DamageClass.TRUE,
                formula_name=SHAPED_CHARGE_FORMULA,
            ),
            cooldown=ValueRef(registry, owner, COOLDOWN_KEY),
        ),
        compilability=Compilable(),
        receipt=receipt_for(
            registry, owner, declared=cached_source_receipt(owner, CACHED_ITEM_SOURCE)
        ),
        zero_policy=ZeroPolicy(
            Disposition.MEASURED,
            "the charge is a sum of sourced shares of the holder's lethality; "
            "a zero means the rotation armed none, which the cast walk "
            "measured",
        ),
    )


def _empowered_auto_buff_rule(
    owner: str, registry: ValueRegistry, entry: Mapping[str, Any]
) -> BehaviorRule:
    """One item's ultimate-triggered empowered-attack window.

    The family's one member that deals no damage of its own: it changes how
    the holder's own attacks land.  Every one of its five numbers is required,
    because a window with a duration and no attack count — or an attack count
    with no critical multiplier — is a mechanic with a hole in it.
    """
    del entry
    references = tuple(
        ValueRef(registry, owner, key) for key in EMPOWERED_AUTO_BUFF_KEYS
    )
    return BehaviorRule(
        family=RuleFamily.CHARGED_STRIKE,
        owner=owner,
        mechanic_id=f"{_mechanic_slug(owner)}.empowered_autos",
        payload=EmpoweredAutoBuffRule(*references),
        compilability=Compilable(),
        receipt=receipt_for(
            registry, owner, declared=cached_source_receipt(owner, CACHED_ITEM_SOURCE)
        ),
        zero_policy=ZeroPolicy(
            Disposition.STRUCTURAL_ZERO,
            "the window deals no damage of its own; it changes how the "
            "holder's own attacks land, and the attacks carry the number",
        ),
    )


_CHARGED_STRIKE_RULES: Mapping[str, Any] = {
    EMPOWERED_HIT_TAG: _empowered_hit_rule,
    REPEATING_STRIKE_TAG: _repeating_strike_rule,
    SHAPED_CHARGE_TAG: _shaped_charge_rule,
    EMPOWERED_AUTO_BUFF_TAG: _empowered_auto_buff_rule,
}


class SwingScheduleSchema(NamedTuple):
    """One swing-rate mechanic's key groups and the fight modes it schedules.

    Keyed by its own signature key like every other group in this module, so
    the table says which *registry shape* re-rates the attack stream and never
    which item does.  A group is declared whole: naming three keys and finding
    two is a parse that dropped one, not a weaker mechanic.
    """

    stack_keys: tuple[str, str, str] | None
    window_keys: tuple[str, str, str, str, str] | None
    schedules_single_rotation: bool


# The two swing-rate shapes the registry states, each under its signature
# key.  Seething Strike is a ramp the attacks build; Flurry is a window the
# attacks re-arm.  ``schedules_single_rotation`` carries the engine's own
# long-standing gate — the ramp was excluded from a one-rotation fight and
# the window was not — as a declared axis rather than an item-name test.
SWING_SCHEDULES: Mapping[str, SwingScheduleSchema] = {
    "seething_attack_speed_per_stack": SwingScheduleSchema(
        (
            "seething_attack_speed_per_stack",
            "seething_max_stacks",
            "seething_duration",
        ),
        None,
        False,
    ),
    "attack_refund_base": SwingScheduleSchema(
        None,
        (
            "bonus_attack_speed_percent",
            "duration",
            "cooldown",
            "attack_refund_base",
            "attack_refund_crit",
        ),
        True,
    ),
}


def _swing_group_refs(
    owner: str,
    registry: ValueRegistry,
    schema: frozenset[str],
    keys: Sequence[str] | None,
) -> tuple[ValueRef, ...] | None:
    """One swing-rate key group as references, declared whole or absent."""
    if keys is None:
        return None
    missing = sorted(key for key in keys if key not in schema)
    if missing:
        raise BehaviorCatalogError(
            f"{registry}[{owner!r}] carries the swing-rate group {keys[0]!r} "
            f"and is missing {missing}; a schedule is claimed whole or not at "
            "all, because half of one re-rates the attack stream with a "
            "number nobody sourced"
        )
    return tuple(ValueRef(registry, owner, key) for key in keys)


def _swing_schedule_rules(
    owner: str, registry: ValueRegistry, entry: Mapping[str, Any]
) -> list[BehaviorRule]:
    """Every re-rating of the holder's own attack stream one entry declares.

    One rule per entry rather than one per group: a single entry carrying both
    a ramp and a re-armed window would be one mechanic scheduling one stream,
    and the schedule the engine walks is the merge of every held rule anyway.
    """
    keys = _schema_keys(owner, registry, entry)
    rules: list[BehaviorRule] = []
    for signature, spec in SWING_SCHEDULES.items():
        if signature not in keys:
            continue
        stacks = _swing_group_refs(owner, registry, keys, spec.stack_keys)
        window = _swing_group_refs(owner, registry, keys, spec.window_keys)
        rules.append(
            BehaviorRule(
                family=RuleFamily.CHARGED_STRIKE,
                owner=owner,
                mechanic_id=f"{_mechanic_slug(owner)}.swing_rate",
                payload=SwingScheduleRule(
                    decaying_stacks=(
                        None if stacks is None else DecayingAttackStacks(*stacks)
                    ),
                    refunded_window=(
                        None if window is None else RefundedAttackWindow(*window)
                    ),
                    schedules_single_rotation=spec.schedules_single_rotation,
                ),
                compilability=Compilable(),
                receipt=receipt_for(
                    registry,
                    owner,
                    declared=cached_source_receipt(owner, CACHED_ITEM_SOURCE),
                ),
                zero_policy=ZeroPolicy(
                    Disposition.STRUCTURAL_ZERO,
                    "the schedule deals no damage of its own; it re-rates the "
                    "holder's own attack stream, and the attacks carry the "
                    "number",
                ),
            )
        )
    return rules


def _compile_charged_strike(
    family: RuleFamily,
    owner: str,
    registry: ValueRegistry,
    entry: Mapping[str, Any],
) -> tuple[BehaviorRule, ...]:
    """Compile the charged strikes one registry entry declares.

    Four tags, four shapes: a hit that spends a charge, a hit that lands every
    Nth application, a charge an ability arms, and an ultimate that empowers
    the holder's own attacks.  Dispatch is on the tag, so no item name decides
    a shape.

    A fifth shape is claimed by a key group rather than by the tag — the swing
    schedule, which re-rates the attack stream and is hung on entries whose
    tags name other families.  An entry that reaches this compiler and claims
    neither is a stop.
    """
    del family
    rules: list[BehaviorRule] = []
    shape = _CHARGED_STRIKE_RULES.get(str(entry.get("type")))
    if shape is not None:
        rules.append(shape(owner, registry, entry))
    rules.extend(_swing_schedule_rules(owner, registry, entry))
    if not rules:
        raise BehaviorCatalogError(
            f"{registry}[{owner!r}] is claimed by the charged-strike family and "
            "carries neither one of its tags nor a swing-rate key group; a "
            "charged strike that strikes nothing is a parse that failed"
        )
    for rule in rules:
        validate_rule(rule)
    return tuple(rules)


def _compile_cast_proc(
    family: RuleFamily,
    owner: str,
    registry: ValueRegistry,
    entry: Mapping[str, Any],
) -> tuple[BehaviorRule, ...]:
    """Compile the cast-triggered proc one registry entry declares.

    Three tags, two shapes: an ultimate proc opens a window an R cast owns,
    and everything else is a cooldown proc whose trigger the entry names.
    Dispatch is on the tag, so no item name decides a shape.
    """
    del family
    tag = str(entry.get("type"))
    if tag == ULTIMATE_PROC_TAG:
        rule = _ultimate_proc_rule(owner, registry, entry)
    else:
        rule = _cooldown_proc_rule(owner, registry, entry)
    validate_rule(rule)
    return (rule,)


def _compile_spellblade(
    family: RuleFamily,
    owner: str,
    registry: ValueRegistry,
    entry: Mapping[str, Any],
) -> tuple[BehaviorRule, ...]:
    """Compile the empowered attack one registry entry declares.

    Seven items share one mechanic — an ability cast arms the next basic
    attack — and differ in a formula and in which sibling mechanic rides
    along.  Both are read off the entry's own keys, so no item name decides
    either.
    """
    del family
    siblings = _sibling_refs(owner, registry, entry)
    rule = BehaviorRule(
        family=RuleFamily.SPELLBLADE,
        owner=owner,
        mechanic_id=f"{_mechanic_slug(owner)}.spellblade",
        payload=SpellbladeRule(
            formula=_damage_formula(
                owner, registry, entry, SPELLBLADE_FORMULA_TERMS, {}
            ),
            cooldown=ValueRef(registry, owner, COOLDOWN_KEY),
            weave_delay=ValueRef(registry, owner, WEAVE_DELAY_KEY),
            double_on_hit=bool(entry.get(DOUBLE_ON_HIT_KEY, False)),
            bonus_attack_speed_percent=siblings["bonus_attack_speed_percent"],
            mana_restore_base_ad_ratio=siblings["mana_restore_base_ad_ratio"],
            mana_restore_crit_ratio=siblings["mana_restore_crit_ratio"],
            self_heal_ap_ratio=siblings["self_heal_ap_ratio"],
            self_heal_bonus_health_ratio=siblings["self_heal_bonus_health_ratio"],
        ),
        compilability=Compilable(),
        receipt=receipt_for(
            registry, owner, declared=cached_source_receipt(owner, CACHED_ITEM_SOURCE)
        ),
        zero_policy=ZeroPolicy(
            Disposition.MEASURED,
            "the empowered attack is a sum of sourced shares of the holder's "
            "stats; a zero means every share resolved to zero, which the "
            "formula measured",
        ),
    )
    validate_rule(rule)
    return (rule,)


def _compile_periodic(
    family: RuleFamily,
    owner: str,
    registry: ValueRegistry,
    entry: Mapping[str, Any],
) -> tuple[BehaviorRule, ...]:
    """Compile the on-a-clock strike one registry entry declares.

    Three tags, one family: a burn, an aura and a fixed-interval strike are
    three cadences of the same mechanic — damage the fight's clock produces
    rather than damage an event produces — and the tag is what says which.
    Dispatch is on that tag, so no item name decides a cadence.
    """
    del family
    tag = str(entry.get("type"))
    cadence, interval_key = PERIODIC_CADENCE_TAGS[tag]
    rule = BehaviorRule(
        family=RuleFamily.PERIODIC,
        owner=owner,
        mechanic_id=f"{_mechanic_slug(owner)}.{cadence.value}",
        payload=PeriodicRule(
            formula=_damage_formula(owner, registry, entry, PERIODIC_FORMULA_TERMS, {}),
            cadence=cadence,
            interval=ValueRef(registry, owner, interval_key),
            duration=(
                ValueRef(registry, owner, BURN_DURATION_KEY)
                if cadence is PeriodicCadence.REFRESHED_BURN
                else None
            ),
            aoe_range_units=_optional_ref(owner, registry, entry, AOE_RANGE_KEY),
            self_heal_share=_optional_ref(owner, registry, entry, SELF_HEAL_SHARE_KEY),
        ),
        compilability=Compilable(),
        receipt=receipt_for(
            registry, owner, declared=cached_source_receipt(owner, CACHED_ITEM_SOURCE)
        ),
        zero_policy=ZeroPolicy(
            Disposition.MEASURED,
            "the tick is a sum of sourced shares priced over the clock the "
            "cadence declares; a zero means the fight was too short to hold a "
            "tick or every share resolved to zero, both of which the rule "
            "measured",
        ),
    )
    validate_rule(rule)
    return (rule,)


def _compile_active_cast(
    family: RuleFamily,
    owner: str,
    registry: ValueRegistry,
    entry: Mapping[str, Any],
) -> tuple[BehaviorRule, ...]:
    """Compile the once-per-fight active one registry entry declares.

    An active is the strike whose trigger is the player: the engine fires it
    at the end of the rotation opener and the declaration says only how much
    it deals, how long before it could be pressed again, and whether the
    holder's life steal follows it.
    """
    del family
    rule = BehaviorRule(
        family=RuleFamily.ACTIVE_CAST,
        owner=owner,
        mechanic_id=f"{_mechanic_slug(owner)}.active",
        payload=ActiveCastRule(
            formula=_damage_formula(owner, registry, entry, ACTIVE_FORMULA_TERMS, {}),
            cooldown=ValueRef(registry, owner, COOLDOWN_KEY),
            lifesteal_effectiveness=_optional_ref(
                owner, registry, entry, LIFESTEAL_EFFECTIVENESS_KEY
            ),
        ),
        compilability=Compilable(),
        receipt=receipt_for(
            registry, owner, declared=cached_source_receipt(owner, CACHED_ITEM_SOURCE)
        ),
        zero_policy=ZeroPolicy(
            Disposition.MEASURED,
            "the active is a sum of sourced shares of the holder's stats; a "
            "zero means every share resolved to zero, which the formula "
            "measured",
        ),
    )
    validate_rule(rule)
    return (rule,)


def _carve_rule(owner: str, registry: ValueRegistry) -> BehaviorRule:
    """Black Cleaver's Carve — the pair engine's averaged reading of it.

    Carve applies a stack on dealing physical damage and the pair engine
    counts one stream, the auto attacks, assuming the rotation's opening
    abilities have already applied :data:`ASSUMED_CARVE_LEADING_ABILITY_HITS`
    of them.  Both halves of that model are now declared:
    ``accrual=BASIC_ATTACK_HIT`` is the stream it counts and
    ``leading_stacks`` is what it believes preceded it.

    ``CESARO_APPROX`` is declared, **not changed**.  ``docs/math-foundations.md``
    §2.3 calls re-tuning the closed-form average a balance change, so this
    slice's whole intervention is making the model visible: a reader can now
    see which summation a number came from instead of inferring it from a
    constant inside an arithmetic helper.  The authority move to
    coupled-with-preview is H1's and is not taken here.
    """
    return BehaviorRule(
        family=RuleFamily.RESISTANCE_SHRED,
        owner=owner,
        mechanic_id=f"{_mechanic_slug(owner)}.armor_reduction",
        payload=ResistanceShredRule(
            resistance=Resistance.ARMOR,
            ramp=StackRamp(
                per_stack=ValueRef(registry, owner, "reduction_per_stack"),
                max_stacks=ValueRef(registry, owner, "max_stacks"),
                accrual=TriggerEvent.BASIC_ATTACK_HIT,
                leading_stacks=ASSUMED_CARVE_LEADING_ABILITY_HITS,
                model=RampModel.CESARO_APPROX,
            ),
            typing=Typing(
                damage_classes=frozenset({DamageClass.PHYSICAL}),
                attack_classes=frozenset(AttackClass),
            ),
            subject=Subject.TARGET,
        ),
        compilability=Compilable(),
        receipt=receipt_for(
            registry, owner, declared=cached_source_receipt(owner, CACHED_ITEM_SOURCE)
        ),
        zero_policy=ZeroPolicy(
            Disposition.MEASURED,
            "the reduction is a sourced per-stack ratio averaged over the "
            "fight's own hit count; a zero means the fight landed no hits, "
            "which the rule measured",
        ),
    )


def _vile_decay_rule(owner: str, registry: ValueRegistry) -> BehaviorRule:
    """Bloodletter's Curse's Vile Decay — one stack per magic ability hit.

    Counted exactly rather than averaged: the rotation walks its abilities in
    order and each magic one applies a stack the ability's own damage then
    benefits from, so the model is ``EXACT`` and ``leading_stacks`` is zero.
    "Magic ability" is the rule's ``typing``: the damage class that applies a
    stack and the attack class that delivers it.
    """
    return BehaviorRule(
        family=RuleFamily.RESISTANCE_SHRED,
        owner=owner,
        mechanic_id=f"{_mechanic_slug(owner)}.mr_reduction",
        payload=ResistanceShredRule(
            resistance=Resistance.MAGIC_RESIST,
            ramp=StackRamp(
                per_stack=ValueRef(registry, owner, "mr_reduction_per_stack"),
                max_stacks=ValueRef(registry, owner, "max_stacks"),
                accrual=TriggerEvent.ABILITY_HIT,
                leading_stacks=NO_LEADING_STACKS,
                model=RampModel.EXACT,
            ),
            typing=Typing(
                damage_classes=frozenset({DamageClass.MAGIC}),
                attack_classes=frozenset({AttackClass.ABILITY}),
            ),
            subject=Subject.TARGET,
        ),
        compilability=Compilable(),
        receipt=receipt_for(
            registry, owner, declared=cached_source_receipt(owner, CACHED_ITEM_SOURCE)
        ),
        zero_policy=ZeroPolicy(
            Disposition.MEASURED,
            "the reduction is a sourced per-stack ratio at the stack count the "
            "rotation applied; a zero means no magic ability landed, which the "
            "rotation walk measured",
        ),
    )


def _compile_resistance_shred(
    family: RuleFamily,
    owner: str,
    registry: ValueRegistry,
    entry: Mapping[str, Any],
) -> tuple[BehaviorRule, ...]:
    """Compile the stacking resistance reduction one registry entry declares.

    Dispatch is on the entry's tag: the tag says which resistance is cut and
    the value keys hold how deeply, so no item name is a literal here.
    """
    del family
    tag = str(entry.get("type"))
    rules: list[BehaviorRule] = []
    if tag == "armor_reduction":
        rules.append(_carve_rule(owner, registry))
    if tag == "mr_reduction_stacking":
        rules.append(_vile_decay_rule(owner, registry))
    if not rules:
        raise BehaviorCatalogError(
            f"{registry}[{owner!r}] carries tag {tag!r} in the resistance-shred "
            "family and no compiler builds a rule for it; a shred with no "
            "declaration is an item that quietly cuts nothing"
        )
    for rule in rules:
        validate_rule(rule)
    return tuple(rules)


# ── the critical-strike profile (3.7) ─────────────────────────────────────
#
# Three mechanics share one registry tag pair and nothing else: a flat bonus
# on the crit multiplier, a strike that is made to crit whether or not the
# roll would have, and an ability-cooldown refund that rides a crit item's
# passive.  Which one an entry declares is answered by the entry's own value
# keys — the device the defence and ally families already use — so no item
# name enters the dispatch.

# The heal a forced crit pays is declared whole or not at all: an entry
# carrying some of these keys is a broken parse, and reading the survivors as
# "this crit heals a little" is exactly the silent weakening rule 5 forbids.
FORCED_CRIT_HEAL_KEYS: tuple[str, ...] = (
    "heal_base_ad_ratio",
    "heal_base_ad_ratio_ranged",
    "heal_missing_health_ratio",
    "temporary_health_duration",
)

CRIT_DAMAGE_BONUS_KEY = "bonus_crit_damage"
COOLDOWN_REFUND_KEY = "cd_refund_percent"
FORCED_CRIT_RATIO_KEY = "reduced_crit_ratio"

# The three signature keys, as one set: an entry tagged into this family that
# carries none of them is a parse that failed, and the refusal names them.
CRIT_PROFILE_KEYS: frozenset[str] = frozenset(
    {CRIT_DAMAGE_BONUS_KEY, COOLDOWN_REFUND_KEY, FORCED_CRIT_RATIO_KEY}
)


def _crit_damage_bonus_rule(owner: str, registry: ValueRegistry) -> BehaviorRule:
    """Infinity Edge's shape: every critical strike pays a bigger multiplier.

    The base multiplier is the game's and belongs to the engine (CLAUDE.md
    records 200%); what the item declares is the bonus added to it.  The
    typing is every damage class from every attack class because a crit
    multiplier applies to whatever critically struck — an ability that can
    crit pays the same bonus an attack does.
    """
    return BehaviorRule(
        family=RuleFamily.CRIT_PROFILE,
        owner=owner,
        mechanic_id=f"{_mechanic_slug(owner)}.crit_damage_bonus",
        payload=CritDamageBonusRule(
            bonus=ValueRef(registry, owner, CRIT_DAMAGE_BONUS_KEY),
            typing=_all_damage_typing(),
            subject=Subject.HOLDER,
        ),
        compilability=Compilable(),
        receipt=receipt_for(
            registry, owner, declared=cached_source_receipt(owner, CACHED_ITEM_SOURCE)
        ),
        zero_policy=ZeroPolicy(
            Disposition.MEASURED,
            "the bonus is a sourced fraction added to the crit multiplier; a "
            "zero would be the registry stating the item adds nothing, which "
            "the rule read rather than assumed",
        ),
    )


def _attack_cooldown_refund_rule(owner: str, registry: ValueRegistry) -> BehaviorRule:
    """Navori Flickerblade's shape: attacks refund basic ability cooldowns.

    The trigger is the basic attack, declared rather than implied by an
    accumulator.  It changes a cooldown and not a damage number, which is why
    it is its own payload inside the family the registry files it under.
    """
    return BehaviorRule(
        family=RuleFamily.CRIT_PROFILE,
        owner=owner,
        mechanic_id=f"{_mechanic_slug(owner)}.cooldown_refund",
        payload=AttackCooldownRefundRule(
            refund_fraction=ValueRef(registry, owner, COOLDOWN_REFUND_KEY),
            trigger=TriggerEvent.BASIC_ATTACK_HIT,
            subject=Subject.HOLDER,
        ),
        compilability=Compilable(),
        receipt=receipt_for(
            registry, owner, declared=cached_source_receipt(owner, CACHED_ITEM_SOURCE)
        ),
        zero_policy=ZeroPolicy(
            Disposition.MEASURED,
            "the refund is a sourced fraction of the remaining cooldown per "
            "attack; a zero means the registry states no refund, which the "
            "rule read",
        ),
    )


def _forced_crit_heal(
    owner: str, registry: ValueRegistry, entry: Mapping[str, Any]
) -> Any:
    """The heal a forced crit pays, or ``None`` where its entry declares none.

    All four keys or none: presence of any of them makes every one of them
    required, so a parse that dropped half the heal raises when the rule is
    read instead of compiling a quietly weaker item.
    """
    schema = _schema_keys(owner, registry, entry)
    if not any(key in schema for key in FORCED_CRIT_HEAL_KEYS):
        return None
    return ForcedCritHeal(
        base_ad_ratio=ValueRef(registry, owner, "heal_base_ad_ratio"),
        base_ad_ratio_ranged=ValueRef(registry, owner, "heal_base_ad_ratio_ranged"),
        missing_health_ratio=ValueRef(registry, owner, "heal_missing_health_ratio"),
        temporary_health_duration=ValueRef(
            registry, owner, "temporary_health_duration"
        ),
    )


def _forced_crit_rule(
    owner: str, registry: ValueRegistry, entry: Mapping[str, Any]
) -> BehaviorRule:
    """Sundered Sky's shape: one strike is made to crit, at a reduced ratio.

    The ratio is a fraction of a *full* critical strike, and the forced crit
    overrides a natural one — so a holder who would have critted anyway is
    made weaker, which is a real property of the item and not a modelling
    choice.  Declaring the ratio rather than a multiplier is what keeps that
    visible.
    """
    return BehaviorRule(
        family=RuleFamily.CRIT_PROFILE,
        owner=owner,
        mechanic_id=f"{_mechanic_slug(owner)}.forced_crit",
        payload=ForcedCritRule(
            occurrence=CritOccurrence.FIRST_ATTACK,
            reduced_ratio=ValueRef(registry, owner, FORCED_CRIT_RATIO_KEY),
            cooldown=ValueRef(registry, owner, COOLDOWN_KEY),
            heal=_forced_crit_heal(owner, registry, entry),
            typing=Typing(
                damage_classes=frozenset(DamageClass),
                attack_classes=frozenset({AttackClass.BASIC_ATTACK}),
            ),
            subject=Subject.HOLDER,
        ),
        compilability=Compilable(),
        receipt=receipt_for(
            registry, owner, declared=cached_source_receipt(owner, CACHED_ITEM_SOURCE)
        ),
        zero_policy=ZeroPolicy(
            Disposition.MEASURED,
            "the forced strike pays a sourced fraction of a full critical "
            "strike; a zero means the registry states the strike does not "
            "crit, which the rule read rather than defaulted",
        ),
    )


def _compile_crit_profile(
    family: RuleFamily,
    owner: str,
    registry: ValueRegistry,
    entry: Mapping[str, Any],
) -> tuple[BehaviorRule, ...]:
    """Compile every crit-profile mechanic one registry entry declares.

    One entry may carry more than one — the tag names the family and the
    value keys name the mechanics — so this is a fan-out rather than a
    ladder, and an entry whose tag lands here carrying none of the keys is a
    stop: a crit modifier that modifies nothing is a parse that failed.
    """
    del family
    schema = _schema_keys(owner, registry, entry)
    rules: list[BehaviorRule] = []
    if CRIT_DAMAGE_BONUS_KEY in schema:
        rules.append(_crit_damage_bonus_rule(owner, registry))
    if COOLDOWN_REFUND_KEY in schema:
        rules.append(_attack_cooldown_refund_rule(owner, registry))
    if FORCED_CRIT_RATIO_KEY in schema:
        rules.append(_forced_crit_rule(owner, registry, entry))
    if not rules:
        raise BehaviorCatalogError(
            f"{registry}[{owner!r}] is tagged into the crit-profile family and "
            f"carries none of {sorted(CRIT_PROFILE_KEYS)}; a crit modifier that "
            "modifies nothing is a parse that failed, not an item with no "
            "behaviour"
        )
    for rule in rules:
        validate_rule(rule)
    return tuple(rules)


# ── damage routing (3.7) ──────────────────────────────────────────────────
#
# Three mechanics that move a damage packet rather than resize it.  Two are
# tagged into the family by the registry; the third — Death's Dance's Ignore
# Pain — is tagged as a starting defence, because that is where the resolver
# builds it, and reaches this compiler through its own signature key.  The
# tag says where a mechanic is *built*; the family says what it *does*.

EXECUTE_THRESHOLD_KEY = "threshold"
SHIELD_BYPASS_KEYS = ("shield_reduction_melee", "shield_reduction_ranged")
VENOM_DURATION_KEY = "venom_duration"


def _execute_rule(owner: str, registry: ValueRegistry) -> BehaviorRule:
    """The Collector's shape: below a sourced share of health, the target dies.

    Nothing about the damage changes, which is why the threshold is a routing
    declaration and not a magnitude.  The typing is every class from every
    attack class: the execution reads the target's health after the packet
    lands, whatever delivered it.
    """
    return BehaviorRule(
        family=RuleFamily.DAMAGE_ROUTING,
        owner=owner,
        mechanic_id=f"{_mechanic_slug(owner)}.execute",
        payload=ExecuteRule(
            threshold=ValueRef(registry, owner, EXECUTE_THRESHOLD_KEY),
            typing=_all_damage_typing(),
            subject=Subject.TARGET,
        ),
        compilability=Compilable(),
        receipt=receipt_for(
            registry, owner, declared=cached_source_receipt(owner, CACHED_ITEM_SOURCE)
        ),
        zero_policy=ZeroPolicy(
            Disposition.MEASURED,
            "the threshold is a sourced share of the target's maximum health; "
            "a zero would be the registry stating nothing is ever executed, "
            "which the rule read rather than assumed",
        ),
    )


def _shield_bypass_rule(owner: str, registry: ValueRegistry) -> BehaviorRule:
    """Serpent's Fang's shape: a share of the target's shielding is bypassed.

    Melee and ranged holders are paid different shares and both are declared
    — a schema that supplied one and defaulted the other would price a whole
    class of holders at zero with nothing saying so.  The window is opened by
    a champion hit and lasts the sourced venom duration.
    """
    melee_key, ranged_key = SHIELD_BYPASS_KEYS
    return BehaviorRule(
        family=RuleFamily.DAMAGE_ROUTING,
        owner=owner,
        mechanic_id=f"{_mechanic_slug(owner)}.shield_bypass",
        payload=ShieldBypassRule(
            fraction=MeleeRangedSplit(
                melee=ValueRef(registry, owner, melee_key),
                ranged=ValueRef(registry, owner, ranged_key),
            ),
            duration=ValueRef(registry, owner, VENOM_DURATION_KEY),
            trigger=TriggerEvent.CHAMPION_DAMAGE,
            typing=_all_damage_typing(),
            subject=Subject.TARGET,
        ),
        compilability=Compilable(),
        receipt=receipt_for(
            registry, owner, declared=cached_source_receipt(owner, CACHED_ITEM_SOURCE)
        ),
        zero_policy=ZeroPolicy(
            Disposition.MEASURED,
            "the bypassed share is a sourced fraction of the shielding the "
            "target holds; a zero means the registry states no shielding is "
            "bypassed, which the rule read",
        ),
    )


def _compile_damage_routing(
    family: RuleFamily,
    owner: str,
    registry: ValueRegistry,
    entry: Mapping[str, Any],
) -> tuple[BehaviorRule, ...]:
    """Compile every routing mechanic one registry entry declares.

    The two tagged mechanics are dispatched on the entry's tag and the
    deferral through the shared defence machinery, so one entry carrying both
    a tag and a defence signature declares both — and an entry tagged into
    this family carrying neither is a stop rather than an item that quietly
    routes nothing.
    """
    tag = str(entry.get("type"))
    rules: list[BehaviorRule] = []
    if tag == "execute":
        rules.append(_execute_rule(owner, registry))
    if tag == "shield_reduction":
        rules.append(_shield_bypass_rule(owner, registry))
    rules.extend(_compile_defense(family, owner, registry, entry))
    if not rules:
        raise BehaviorCatalogError(
            f"{registry}[{owner!r}] is offered to the damage-routing compiler "
            f"carrying tag {tag!r} and no routing signature key; a routing rule "
            "that routes nothing is a parse that failed"
        )
    for rule in rules:
        validate_rule(rule)
    return tuple(rules)


# ── sustain (3.7) ─────────────────────────────────────────────────────────
#
# Six mechanics that put health back and share no arithmetic.  Five are
# tagged ``sustain`` and are told apart by their entry's own value keys —
# the same device the defence and ally families use — and the sixth,
# Spirit Visage's Boundless Vitality, is tagged as a starting defence
# because that is where the resolver builds it.
#
# The signature key of each shape, and every key it then requires.  A shape
# is claimed whole or not at all: an entry carrying its signature and missing
# a companion raises when the rule is compiled, rather than declaring a
# quietly weaker mechanic.

SUSTAIN_STAT_KEYS: Mapping[str, SustainStat] = {
    "lifesteal_percent": SustainStat.LIFESTEAL_PERCENT,
    "stat_override_omnivamp_percent": SustainStat.OMNIVAMP_PERCENT,
}


class SaturatingGrantSchema(NamedTuple):
    """A vampirism grant the stat block does not carry until a ramp tops out.

    Keyed by its own signature key, so the table says which registry *shape*
    arms on saturation and never which item does.  ``ranged_key`` is the
    melee/ranged pair every such grant has had so far; the two ramp keys are
    the ones the sibling amplifier on the same entry is already declared
    from, which is why the arming time is never a third number to source.
    """

    stat: SustainStat
    ranged_key: str
    per_second_key: str
    maximum_key: str


# The one saturating grant the registry states: Void Corruption's omnivamp,
# hung on an entry tagged for the amplifier its own ramp pays.
SATURATING_SUSTAIN_STATS: Mapping[str, SaturatingGrantSchema] = {
    "max_stack_omnivamp": SaturatingGrantSchema(
        SustainStat.OMNIVAMP_PERCENT,
        "max_stack_omnivamp_ranged",
        "amp_per_second",
        "amp_max",
    ),
}

# The prefix that makes a stat grant a *correction* to the cached stat block
# rather than a second source of it.  One spelling, read here and by
# ``item_effects.override_item_stat``, so the two cannot disagree about what
# an override is.
STAT_OVERRIDE_PREFIX = "stat_override_"

ON_HIT_HEAL_KEY = "health_per_on_hit"

POST_MITIGATION_HEAL_KEYS = (
    "direct_heal_post_mitigation_ratio",
    "direct_heal_aoe_effectiveness",
)

RESOURCE_DRAIN_KEYS = (
    "drain_restoration_per_second",
    "drain_combat_restoration_per_second",
    "drain_combat_duration",
    "drain_health_conversion",
    "drain_tick_interval",
)

MANA_SPENT_HEAL_KEYS = (
    "mana_spent_heal_ratio",
    "mana_spent_heal_cap_per_cast",
    "mana_spent_heal_cap_per_second",
    "damage_taken_to_mana_ratio",
)

BELOW_HALF_HEALING_KEY = "health_state_healing_multiplier_below_half"

REGENERATION_KEYS = (
    "enduring_focus_total_melee",
    "enduring_focus_total_reduced",
    "enduring_focus_duration",
    "enduring_focus_missing_health_cap",
    "health_regen_tick_interval",
)

_SOURCED_HEAL_ZERO = ZeroPolicy(
    Disposition.MEASURED,
    "every share is a sourced registry number; a zero means the registry "
    "states the mechanic restores nothing, which the rule read rather than "
    "defaulted",
)


def _sustain_rule(
    owner: str,
    registry: ValueRegistry,
    mechanic: str,
    payload: Any,
) -> BehaviorRule:
    """One sustain declaration, with the citation its entry resolves to."""
    return BehaviorRule(
        family=RuleFamily.SUSTAIN,
        owner=owner,
        mechanic_id=f"{_mechanic_slug(owner)}.{mechanic}",
        payload=payload,
        compilability=LEDGER_UNSTAGEABLE_SUSTAIN.get(type(payload), Compilable()),
        receipt=receipt_for(
            registry, owner, declared=cached_source_receipt(owner, CACHED_ITEM_SOURCE)
        ),
        zero_policy=_SOURCED_HEAL_ZERO,
    )


def _sustain_stat_rules(
    owner: str, registry: ValueRegistry, schema: frozenset[str]
) -> list[BehaviorRule]:
    """Every vampirism stat one entry grants, in the order the table names them."""
    return [
        _sustain_rule(
            owner,
            registry,
            f"{stat.value}_grant",
            SustainStatRule(
                stat=stat,
                percent=ValueRef(registry, owner, key),
                overrides_cached_stat=key.startswith(STAT_OVERRIDE_PREFIX),
                arms_at=None,
                subject=Subject.HOLDER,
            ),
        )
        for key, stat in SUSTAIN_STAT_KEYS.items()
        if key in schema
    ]


def _saturating_stat_rules(
    owner: str, registry: ValueRegistry, schema: frozenset[str]
) -> list[BehaviorRule]:
    """Every vampirism grant one entry arms on a ramp, in table order."""
    rules: list[BehaviorRule] = []
    for key, spec in SATURATING_SUSTAIN_STATS.items():
        if key not in schema:
            continue
        missing = sorted(
            named
            for named in (spec.ranged_key, spec.per_second_key, spec.maximum_key)
            if named not in schema
        )
        if missing:
            raise BehaviorCatalogError(
                f"{registry}[{owner!r}] carries the saturating grant {key!r} and "
                f"is missing {missing}; the grant and the ramp that arms it are "
                "claimed together, because a grant nothing arms would be paid "
                "from the first tick"
            )
        rules.append(
            _sustain_rule(
                owner,
                registry,
                f"{spec.stat.value}_on_saturation",
                SustainStatRule(
                    stat=spec.stat,
                    percent=MeleeRangedSplit(
                        melee=ValueRef(registry, owner, key),
                        ranged=ValueRef(registry, owner, spec.ranged_key),
                    ),
                    overrides_cached_stat=False,
                    arms_at=RampSaturation(
                        per_second=ValueRef(registry, owner, spec.per_second_key),
                        maximum=ValueRef(registry, owner, spec.maximum_key),
                    ),
                    subject=Subject.HOLDER,
                ),
            )
        )
    return rules


# The sustain family's own "declared elsewhere", the sibling of
# :data:`STAT_DERIVATION_DECLARED_ELSEWHERE`: a key whose whole mechanic
# another surface owns, so an entry carrying only that key compiles no
# sustain rule on purpose rather than by a parse failure.
SUSTAIN_DECLARED_ELSEWHERE: Mapping[str, str] = {
    "slay_omnivamp_per_takedown": (
        "declared as the stacked omnivamp grant of the stat-derivation "
        "family, whose per-stack shape carries both of Slay's ceilings; a "
        "takedown is not pre-fight-projectable, so the stacks arrive as the "
        "bounded ``slay_stacks`` scenario control rather than from a sustain "
        "formula resolving them"
    ),
}


def _compile_sustain(
    family: RuleFamily,
    owner: str,
    registry: ValueRegistry,
    entry: Mapping[str, Any],
) -> tuple[BehaviorRule, ...]:
    """Compile every sustain mechanic one registry entry declares.

    A fan-out rather than a ladder: an entry may grant a stat *and* carry a
    named mechanic, and Doran's Blade does exactly that, with two
    declarations on one entry.  An entry tagged into the family carrying no
    signature key is a stop.
    """
    schema = _schema_keys(owner, registry, entry)
    rules = _sustain_rule_list(owner, registry, schema)
    rules.extend(_compile_defense(family, owner, registry, entry))
    if not rules and not any(key in schema for key in SUSTAIN_DECLARED_ELSEWHERE):
        raise BehaviorCatalogError(
            f"{registry}[{owner!r}] is tagged into the sustain family and "
            "carries none of its signature keys; sustain that restores nothing "
            "is a parse that failed, not an item with no behaviour"
        )
    for rule in rules:
        validate_rule(rule)
    return tuple(rules)


def _sustain_rule_list(
    owner: str, registry: ValueRegistry, schema: frozenset[str]
) -> list[BehaviorRule]:
    """The four keyed sustain shapes one entry declares, in declaration order."""
    rules = _sustain_stat_rules(owner, registry, schema)
    rules.extend(_saturating_stat_rules(owner, registry, schema))
    if ON_HIT_HEAL_KEY in schema:
        rules.append(
            _sustain_rule(
                owner,
                registry,
                "on_hit_heal",
                OnHitHealRule(
                    amount=ValueRef(registry, owner, ON_HIT_HEAL_KEY),
                    trigger=TriggerEvent.BASIC_ATTACK_HIT,
                    subject=Subject.HOLDER,
                ),
            )
        )
    if POST_MITIGATION_HEAL_KEYS[0] in schema:
        ratio, area = (
            ValueRef(registry, owner, key) for key in POST_MITIGATION_HEAL_KEYS
        )
        rules.append(
            _sustain_rule(
                owner,
                registry,
                "post_mitigation_heal",
                PostMitigationHealRule(
                    ratio=ratio, area_effectiveness=area, subject=Subject.HOLDER
                ),
            )
        )
    if RESOURCE_DRAIN_KEYS[0] in schema:
        rate, combat_rate, window, conversion, tick = (
            ValueRef(registry, owner, key) for key in RESOURCE_DRAIN_KEYS
        )
        rules.append(
            _sustain_rule(
                owner,
                registry,
                "resource_drain",
                ResourceDrainRule(
                    restoration_per_second=rate,
                    combat_restoration_per_second=combat_rate,
                    combat_window=window,
                    health_conversion=conversion,
                    tick_interval=tick,
                    subject=Subject.HOLDER,
                ),
            )
        )
    if MANA_SPENT_HEAL_KEYS[0] in schema:
        heal, per_cast, per_second, taken = (
            ValueRef(registry, owner, key) for key in MANA_SPENT_HEAL_KEYS
        )
        rules.append(
            _sustain_rule(
                owner,
                registry,
                "mana_spent_heal",
                ManaSpentHealRule(
                    heal_ratio=heal,
                    cap_per_cast=per_cast,
                    cap_per_second=per_second,
                    damage_taken_to_mana_ratio=taken,
                    subject=Subject.HOLDER,
                ),
            )
        )
    if REGENERATION_KEYS[0] in schema:
        melee, reduced, duration, cap, tick = (
            ValueRef(registry, owner, key) for key in REGENERATION_KEYS
        )
        rules.append(
            _sustain_rule(
                owner,
                registry,
                "regeneration_window",
                RegenerationRule(
                    total_melee=melee,
                    total_reduced=reduced,
                    duration=duration,
                    missing_health_cap=cap,
                    tick_interval=tick,
                    subject=Subject.HOLDER,
                ),
            )
        )
    if BELOW_HALF_HEALING_KEY in schema:
        rules.append(
            _sustain_rule(
                owner,
                registry,
                "below_half_healing",
                BelowHalfHealingRule(
                    bonus=ValueRef(registry, owner, BELOW_HALF_HEALING_KEY),
                    subject=Subject.HOLDER,
                ),
            )
        )
    return rules


# ── ally packets (3.6) ────────────────────────────────────────────────────
#
# The one family whose mechanics share no arithmetic.  Redemption heals a
# radius and Phage grants move speed; what they have in common is only the
# *shape of the emission* — which producer, what kinds, to whom, on what
# trigger — so that is what the declarations say, and the emitters in
# ``item_support_effects`` read their numbers back through the rule instead of
# spelling an item's name.
#
# Dispatch is on the entry's **value keys**, the device ``ALLY_DELTA_AMP_SLOTS``
# already uses for the same registry and for the same reason: an
# ``ALLY_ITEM_EFFECTS`` record carries no effect tag, so the only thing that
# can identify its mechanic without naming its item is the set of keys its
# numbers live under.

# The three keys every registry entry may carry that are citations rather than
# numbers.  Excluded from shape matching so a record that grows a citation
# does not stop matching the mechanic it has always been.
CITATION_KEYS: frozenset[str] = frozenset(
    {"source_url", "source_revision_id", "source_revision_timestamp"}
)

# The packet kinds the compiled score kernel can stage.  ``shield`` and
# ``heal`` are the two ``survival/compile.unrepresentable_template_receipt``
# admits as support templates; ``damage`` is not a support template at all and
# rides the compiled damage walk like any other damage row.
COMPILED_SUPPORT_KINDS: frozenset[PacketKind] = frozenset(
    {PacketKind.HEAL, PacketKind.SHIELD, PacketKind.DAMAGE}
)


@dataclass(frozen=True, slots=True)
class EntryShape:
    """Which registry entry carries a producer, said in value keys.

    Matching differs by registry, and the difference is a property of the
    registries rather than a convenience.  ``ALLY_ITEM_EFFECTS`` is
    hand-authored and refresh-**inert** (D-47), so its records do not grow
    keys on patch day and the match can be exact — an entry whose key set
    stops equalling its shape is a defect somebody must look at.
    ``ITEM_EFFECTS`` is parsed from the wiki on every refresh, so a match that
    demanded equality there would fail the first time a page grew a number;
    the first key is a **signature** instead, and the rest must accompany it —
    a record carrying the signature and missing the rest is a broken parse,
    never an item that quietly emits nothing.
    """

    registry: ValueRegistry
    keys: tuple[str, ...]

    def matches(self, entry: Mapping[str, Any]) -> bool:
        """Whether *entry* carries this producer."""
        if self.registry == "ALLY_ITEM_EFFECTS":
            return frozenset(entry) - CITATION_KEYS == frozenset(self.keys)
        return self.keys[0] in entry

    def missing(self, entry: Mapping[str, Any]) -> tuple[str, ...]:
        """The signature's companion keys *entry* does not carry."""
        return tuple(key for key in self.keys if key not in entry)


@dataclass(frozen=True, slots=True)
class AllyPacketDeclaration:
    """One cross-participant producer's shape, before an owner is known.

    Owner-free on purpose: two items carry the support quest and the
    declaration is the same declaration for both, so binding it to an owner
    would be the item-name literal this migration removes coming back as a
    table key.

    ``ramps`` carries each level-scaled number's :class:`LevelSubject`, read
    from the cached sentence rather than guessed by an emitter.
    ``tests/test_coupled_ally_item_packets.py::TestDeclaredRampSubjects``
    reads the ``type=`` qualifier back out of every owner's cached branch
    text, so a patch that re-scales one of these is a red test rather than a
    number only the source moved.
    """

    trigger: PacketTrigger
    packets: tuple[PacketSpec, ...]
    secondary_target: Recipients | None
    persistence: Persistence
    redirects_incoming_damage: bool
    reads: tuple[str, ...]
    ramps: tuple[DeclaredRamp, ...]
    zero_reason: str


# Two records carry two mechanics each, so two producers share one shape:
# Dream Maker's blue and purple bubbles are one item's two bubbles with two
# packet sources, and the support quest's gold and ward are two outcomes of
# one quest carried by whichever transformed item is equipped.
_DREAM_KEYS: tuple[str, ...] = (
    "blue_reduction_max",
    "blue_reduction_min",
    "dream_duration",
    "level_scaling_start",
    "purple_magic_max",
    "purple_magic_min",
)

_QUEST_KEYS: tuple[str, ...] = ("support_quest_threshold", "ward_charges")

# Every producer's entry shape, including the ones whose emitter has not
# migrated yet: the closure below asserts that every ``ALLY_ITEM_EFFECTS``
# record is claimed by one, and a shape table missing the unmigrated half
# could not make that claim on the commit that first states it.
ALLY_ENTRY_SHAPES: Mapping[AllyProducer, EntryShape] = {
    AllyProducer.EVERLASTING: EntryShape(
        "ITEM_EFFECTS",
        (
            "everlasting_base_shield",
            "everlasting_cooldown",
            "everlasting_current_mana_ratio",
            "everlasting_duration",
            # The gate the producer reads, and the authority behind it: the
            # ratio prices the gate and the status says whether a source
            # authorizes it, so a future de-sourcing is a named denial
            # rather than a silently missing key.
            "everlasting_mana_gate_status",
            "everlasting_mana_threshold_ratio",
            "everlasting_multi_target_multiplier",
        ),
    ),
    AllyProducer.LIFE_FROM_DEATH: EntryShape(
        "ALLY_ITEM_EFFECTS",
        (
            "life_from_death_ap_ratio",
            "life_from_death_base_heal",
            "life_from_death_cooldown",
            "life_from_death_nova_duration",
        ),
    ),
    AllyProducer.STARLIT_GRACE: EntryShape(
        "ALLY_ITEM_EFFECTS", ("heal_chain_fraction", "shield_chain_fraction")
    ),
    AllyProducer.SOUL_SIPHON: EntryShape(
        "ALLY_ITEM_EFFECTS",
        ("charge_cap_max", "charge_cap_min", "charge_damage_ratio"),
    ),
    AllyProducer.CONSONANCE: EntryShape(
        "ALLY_ITEM_EFFECTS",
        (
            "consonance_cooldown",
            "consonance_max_mana_ratio",
            "harmony_bonus_mana_ratio",
        ),
    ),
    AllyProducer.GOING_SLEDDING: EntryShape(
        "ALLY_ITEM_EFFECTS",
        (
            "bonus_move_speed_percent",
            "cooldown",
            "duration",
            "level_scaling_start",
            "temporary_health_max",
            "temporary_health_min",
        ),
    ),
    AllyProducer.SACRIFICE: EntryShape(
        "ALLY_ITEM_EFFECTS",
        (
            "holder_heal_fraction",
            "holder_health_threshold_ratio",
            "redirect_fraction",
            "worthy_range_units",
        ),
    ),
    AllyProducer.SANCTIFY: EntryShape(
        "ALLY_ITEM_EFFECTS",
        (
            "sanctify_bonus_attack_speed",
            "sanctify_duration",
            "sanctify_on_hit_magic",
        ),
    ),
    AllyProducer.RAPIDS: EntryShape(
        "ALLY_ITEM_EFFECTS",
        ("bonus_ability_haste", "bonus_ability_power", "duration"),
    ),
    AllyProducer.FANFARE: EntryShape(
        "ALLY_ITEM_EFFECTS",
        (
            "fanfare_ally_attack_speed_melee",
            "fanfare_ally_attack_speed_ranged",
            "fanfare_bonus_move_speed",
            "fanfare_duration_melee",
            "fanfare_duration_ranged",
        ),
    ),
    AllyProducer.UNMAKE: EntryShape("ALLY_ITEM_EFFECTS", ("magic_damage_amp",)),
    AllyProducer.EXPOSE_WEAKNESS: EntryShape(
        "ALLY_ITEM_EFFECTS",
        (
            "expose_weakness_cooldown",
            "expose_weakness_duration",
            "expose_weakness_melee",
            "expose_weakness_ranged",
        ),
    ),
    AllyProducer.CARVE: EntryShape(
        "ALLY_ITEM_EFFECTS",
        (
            "armor_reduction_duration",
            "armor_reduction_max_stacks",
            "armor_reduction_per_stack",
        ),
    ),
    AllyProducer.VILE_DECAY: EntryShape(
        "ALLY_ITEM_EFFECTS",
        ("mr_reduction_duration", "mr_reduction_max_stacks", "mr_reduction_per_stack"),
    ),
    AllyProducer.BLUE_BUBBLE: EntryShape("ALLY_ITEM_EFFECTS", _DREAM_KEYS),
    AllyProducer.PURPLE_BUBBLE: EntryShape("ALLY_ITEM_EFFECTS", _DREAM_KEYS),
    AllyProducer.COMMAND: EntryShape(
        "ALLY_ITEM_EFFECTS",
        ("command_damage_amp", "command_duration", "control_ability_haste"),
    ),
    AllyProducer.REAP: EntryShape(
        "ITEM_EFFECTS",
        ("reap_gold_per_minion", "reap_completion_gold", "reap_max_gold"),
    ),
    AllyProducer.RAGE: EntryShape(
        "ITEM_EFFECTS",
        (
            "rage_duration",
            "rage_bonus_move_speed_melee",
            "rage_bonus_move_speed_ranged",
        ),
    ),
    AllyProducer.SHARED_RICHES: EntryShape("ITEM_EFFECTS", _QUEST_KEYS),
    AllyProducer.WARD: EntryShape("ITEM_EFFECTS", _QUEST_KEYS),
    AllyProducer.NIGHTSTALKER: EntryShape(
        "ITEM_EFFECTS",
        (
            "nightstalker_unseen_seconds",
            "nightstalker_trigger_window",
            "blackout_duration",
        ),
    ),
    AllyProducer.DEVOTION: EntryShape(
        "ALLY_ITEM_EFFECTS",
        ("level_scaling_start", "shield_duration", "shield_max", "shield_min"),
    ),
    AllyProducer.PURIFY: EntryShape("ALLY_ITEM_EFFECTS", ("heal_max", "heal_min")),
    AllyProducer.INTERVENTION: EntryShape(
        "ALLY_ITEM_EFFECTS",
        (
            "beam_delay",
            "cooldown",
            "enemy_max_health_true_damage_ratio",
            "heal_max",
            "heal_min",
            "target_area_range_units",
        ),
    ),
    AllyProducer.INSPIRING_SPEECH: EntryShape(
        "ALLY_ITEM_EFFECTS", ("bonus_move_speed_percent", "duration")
    ),
    AllyProducer.BREAKING_SHOCKWAVE: EntryShape(
        "ITEM_EFFECTS",
        (
            "front_offset",
            "area_radius",
            "bonus_move_speed_duration",
            "bonus_move_speed_percent",
            "slow_duration",
            "slow_percent",
        ),
    ),
}


# One entry per producer, landed together with the emitter that reads it.
ALLY_PACKET_DECLARATIONS: Mapping[AllyProducer, AllyPacketDeclaration] = {
    AllyProducer.EVERLASTING: AllyPacketDeclaration(
        trigger=PacketTrigger.CROWD_CONTROL,
        packets=(PacketSpec(PacketKind.SHIELD, Recipients.SELF),),
        secondary_target=None,
        persistence=Persistence.TIMED_WINDOW,
        redirects_incoming_damage=False,
        reads=(
            "everlasting_mana_threshold_ratio",
            "everlasting_mana_gate_status",
            "everlasting_cooldown",
            "everlasting_multi_target_multiplier",
            "everlasting_base_shield",
            "everlasting_current_mana_ratio",
            "everlasting_duration",
        ),
        ramps=(),
        zero_reason=(
            "the shield is a sourced base plus a sourced share of the mana the "
            "ordered cast receipt says the holder still had; a zero means the "
            "receipt measured no qualifying immobilize"
        ),
    ),
    AllyProducer.LIFE_FROM_DEATH: AllyPacketDeclaration(
        trigger=PacketTrigger.TAKEDOWN,
        packets=(PacketSpec(PacketKind.HEAL, Recipients.HOLDER_AND_ALLIES),),
        secondary_target=None,
        persistence=Persistence.TIMED_WINDOW,
        redirects_incoming_damage=False,
        reads=(
            "life_from_death_base_heal",
            "life_from_death_ap_ratio",
            "life_from_death_nova_duration",
            "life_from_death_cooldown",
        ),
        ramps=(),
        zero_reason=(
            "the nova is a sourced base plus a sourced share of the holder's "
            "ability power; a zero means the authored stream carried no "
            "takedown, which the walk measured"
        ),
    ),
    AllyProducer.STARLIT_GRACE: AllyPacketDeclaration(
        trigger=PacketTrigger.ALLY_HEAL_OR_SHIELD,
        packets=(
            PacketSpec(PacketKind.HEAL, Recipients.OTHER_ALLY),
            PacketSpec(PacketKind.SHIELD, Recipients.OTHER_ALLY),
        ),
        secondary_target=None,
        persistence=Persistence.TIMED_WINDOW,
        redirects_incoming_damage=False,
        reads=("heal_chain_fraction", "shield_chain_fraction"),
        ramps=(),
        zero_reason=(
            "the chain is a sourced share of the heal or shield that triggered "
            "it; a zero means the triggering packet carried nothing to chain"
        ),
    ),
    AllyProducer.SOUL_SIPHON: AllyPacketDeclaration(
        trigger=PacketTrigger.ALLY_HEAL_OR_SHIELD,
        packets=(PacketSpec(PacketKind.HEAL, Recipients.TRIGGERING_ALLY),),
        secondary_target=None,
        persistence=Persistence.SINGLE_MOMENT,
        redirects_incoming_damage=False,
        reads=("charge_damage_ratio",),
        ramps=(DeclaredRamp("charge_cap_min", "charge_cap_max", LevelSubject.HOLDER),),
        zero_reason=(
            "the heal is the stored charge pool, a sourced share of the "
            "authored damage capped by a sourced level ramp read at the "
            "holder's level; a zero means the ledger carried no damage to "
            "charge from"
        ),
    ),
    AllyProducer.CONSONANCE: AllyPacketDeclaration(
        trigger=PacketTrigger.ALLY_HEAL_OR_SHIELD,
        packets=(PacketSpec(PacketKind.HEAL, Recipients.TRIGGERING_ALLY),),
        secondary_target=None,
        persistence=Persistence.SINGLE_MOMENT,
        redirects_incoming_damage=False,
        reads=("consonance_max_mana_ratio", "consonance_cooldown"),
        ramps=(),
        zero_reason=(
            "the heal is a sourced share of the holder's own mana pool; a zero "
            "means the holder has no mana, which the stat block measured"
        ),
    ),
    AllyProducer.GOING_SLEDDING: AllyPacketDeclaration(
        trigger=PacketTrigger.CROWD_CONTROL,
        packets=(
            PacketSpec(
                PacketKind.TEMPORARY_HEALTH, Recipients.HOLDER_AND_SELECTED_ALLY
            ),
        ),
        secondary_target=None,
        persistence=Persistence.TIMED_WINDOW,
        redirects_incoming_damage=False,
        reads=("duration", "bonus_move_speed_percent", "cooldown"),
        ramps=(
            DeclaredRamp(
                "temporary_health_min", "temporary_health_max", LevelSubject.HOLDER
            ),
        ),
        zero_reason=(
            "the temporary health is a sourced level ramp read at the holder's "
            "level; a zero means no authored control landed"
        ),
    ),
    AllyProducer.SACRIFICE: AllyPacketDeclaration(
        trigger=PacketTrigger.ALLY_DAMAGE_DEALT,
        packets=(PacketSpec(PacketKind.HEAL, Recipients.SELF),),
        secondary_target=None,
        persistence=Persistence.SINGLE_MOMENT,
        redirects_incoming_damage=True,
        reads=(
            "redirect_fraction",
            "holder_heal_fraction",
            "holder_health_threshold_ratio",
            "worthy_range_units",
            "source_revision_id",
        ),
        ramps=(),
        zero_reason=(
            "the holder's heal is a sourced share of the damage the Worthy "
            "ally dealt; a zero means the Worthy dealt none, which the "
            "outgoing ledger measured"
        ),
    ),
    AllyProducer.SANCTIFY: AllyPacketDeclaration(
        trigger=PacketTrigger.ALLY_HEAL_OR_SHIELD,
        packets=(
            PacketSpec(PacketKind.STAT_BUFF, Recipients.HOLDER_AND_TRIGGERING_ALLY),
        ),
        secondary_target=None,
        persistence=Persistence.TIMED_WINDOW,
        redirects_incoming_damage=False,
        reads=(
            "sanctify_bonus_attack_speed",
            "sanctify_duration",
            "sanctify_on_hit_magic",
        ),
        ramps=(),
        zero_reason=(
            "the buff is a sourced attack-speed ratio and a sourced on-hit "
            "number; a zero means the holder healed or shielded nobody, which "
            "the authored trigger stream measured"
        ),
    ),
    AllyProducer.RAPIDS: AllyPacketDeclaration(
        trigger=PacketTrigger.ALLY_HEAL_OR_SHIELD,
        packets=(
            PacketSpec(PacketKind.STAT_BUFF, Recipients.HOLDER_AND_TRIGGERING_ALLY),
        ),
        secondary_target=None,
        persistence=Persistence.TIMED_WINDOW,
        redirects_incoming_damage=False,
        reads=("bonus_ability_power", "duration", "bonus_ability_haste"),
        ramps=(),
        zero_reason=(
            "the buff is a sourced ability-power and ability-haste grant; a "
            "zero means the holder healed or shielded nobody"
        ),
    ),
    AllyProducer.FANFARE: AllyPacketDeclaration(
        trigger=PacketTrigger.CROWD_CONTROL,
        packets=(
            PacketSpec(PacketKind.MOVEMENT, Recipients.SELF),
            PacketSpec(PacketKind.STAT_BUFF, Recipients.HOLDER_AND_ALLIES),
        ),
        secondary_target=Recipients.HOLDER_AND_ALLIES,
        persistence=Persistence.TIMED_WINDOW,
        redirects_incoming_damage=False,
        reads=(
            "fanfare_bonus_move_speed",
            "fanfare_duration_melee",
            "fanfare_duration_ranged",
            "fanfare_ally_attack_speed_melee",
            "fanfare_ally_attack_speed_ranged",
        ),
        ramps=(),
        zero_reason=(
            "both halves are sourced ratios chosen by the holder's own range "
            "class; a zero means no authored control landed, which the bus's "
            "CC stream measured"
        ),
    ),
    AllyProducer.UNMAKE: AllyPacketDeclaration(
        trigger=PacketTrigger.FIGHT_START,
        packets=(PacketSpec(PacketKind.DAMAGE_MODIFIER, Recipients.ENEMIES),),
        secondary_target=None,
        persistence=Persistence.PERSISTENT_AURA,
        redirects_incoming_damage=False,
        reads=("magic_damage_amp",),
        ramps=(),
        zero_reason=(
            "the curse is a sourced magic-damage ratio in force from the first "
            "frame; a zero would mean the registry holds zero, which is a "
            "measurement"
        ),
    ),
    AllyProducer.EXPOSE_WEAKNESS: AllyPacketDeclaration(
        trigger=PacketTrigger.DAMAGE_DEALT,
        packets=(PacketSpec(PacketKind.DAMAGE_MODIFIER, Recipients.TRIGGERING_ENEMY),),
        secondary_target=None,
        persistence=Persistence.TIMED_WINDOW,
        redirects_incoming_damage=False,
        reads=(
            "expose_weakness_melee",
            "expose_weakness_ranged",
            "expose_weakness_duration",
            "expose_weakness_cooldown",
        ),
        ramps=(),
        zero_reason=(
            "the modifier is a sourced ratio chosen by the holder's range "
            "class; a zero means the spellblade never procced, which the "
            "authored damage stream measured"
        ),
    ),
    AllyProducer.CARVE: AllyPacketDeclaration(
        trigger=PacketTrigger.DAMAGE_DEALT,
        packets=(PacketSpec(PacketKind.DAMAGE_MODIFIER, Recipients.TRIGGERING_ENEMY),),
        secondary_target=None,
        persistence=Persistence.TIMED_WINDOW,
        redirects_incoming_damage=False,
        reads=(
            "armor_reduction_max_stacks",
            "armor_reduction_per_stack",
            "armor_reduction_duration",
        ),
        ramps=(),
        zero_reason=(
            "the reduction is a sourced per-stack ratio at the stack count the "
            "authored physical stream applied; a zero means it applied none"
        ),
    ),
    AllyProducer.VILE_DECAY: AllyPacketDeclaration(
        trigger=PacketTrigger.DAMAGE_DEALT,
        packets=(PacketSpec(PacketKind.DAMAGE_MODIFIER, Recipients.TRIGGERING_ENEMY),),
        secondary_target=None,
        persistence=Persistence.TIMED_WINDOW,
        redirects_incoming_damage=False,
        reads=(
            "mr_reduction_max_stacks",
            "mr_reduction_per_stack",
            "mr_reduction_duration",
        ),
        ramps=(),
        zero_reason=(
            "Carve's shape, magic- and ability-gated: a zero means no magic "
            "ability hit landed, which the authored stream measured"
        ),
    ),
    AllyProducer.BLUE_BUBBLE: AllyPacketDeclaration(
        trigger=PacketTrigger.ALLY_HEAL_OR_SHIELD,
        packets=(PacketSpec(PacketKind.DAMAGE_MODIFIER, Recipients.TRIGGERING_ALLY),),
        secondary_target=None,
        persistence=Persistence.TIMED_WINDOW,
        redirects_incoming_damage=False,
        reads=("dream_duration",),
        ramps=(
            DeclaredRamp(
                "blue_reduction_min", "blue_reduction_max", LevelSubject.HOLDER
            ),
        ),
        zero_reason=(
            "the reduction is a sourced level ramp read at the holder's level; "
            "a zero means the holder healed or shielded nobody"
        ),
    ),
    AllyProducer.PURPLE_BUBBLE: AllyPacketDeclaration(
        trigger=PacketTrigger.ALLY_HEAL_OR_SHIELD,
        packets=(PacketSpec(PacketKind.ON_HIT_MAGIC, Recipients.TRIGGERING_ALLY),),
        secondary_target=None,
        persistence=Persistence.TIMED_WINDOW,
        redirects_incoming_damage=False,
        reads=("dream_duration",),
        ramps=(
            DeclaredRamp("purple_magic_min", "purple_magic_max", LevelSubject.HOLDER),
        ),
        zero_reason=(
            "the on-hit bonus is a sourced level ramp read at the holder's "
            "level; a zero means the holder healed or shielded nobody"
        ),
    ),
    AllyProducer.DEVOTION: AllyPacketDeclaration(
        trigger=PacketTrigger.ITEM_ACTIVE,
        packets=(PacketSpec(PacketKind.SHIELD, Recipients.HOLDER_AND_ALLIES),),
        secondary_target=None,
        persistence=Persistence.TIMED_WINDOW,
        redirects_incoming_damage=False,
        reads=("shield_duration",),
        ramps=(DeclaredRamp("shield_min", "shield_max", LevelSubject.RECIPIENT),),
        zero_reason=(
            "the shield is a sourced level ramp read at each recipient's own "
            "level; a zero means the scenario cast no active, and no packet is "
            "emitted at all rather than one carrying nothing"
        ),
    ),
    AllyProducer.PURIFY: AllyPacketDeclaration(
        trigger=PacketTrigger.ITEM_ACTIVE,
        packets=(PacketSpec(PacketKind.HEAL, Recipients.SELECTED_ALLY),),
        secondary_target=None,
        persistence=Persistence.SINGLE_MOMENT,
        redirects_incoming_damage=False,
        reads=(),
        ramps=(DeclaredRamp("heal_min", "heal_max", LevelSubject.RECIPIENT),),
        zero_reason=(
            "the heal is a sourced level ramp read at the tethered ally's own "
            "level; a zero means the scenario cast no active"
        ),
    ),
    AllyProducer.INTERVENTION: AllyPacketDeclaration(
        trigger=PacketTrigger.ITEM_ACTIVE,
        packets=(
            PacketSpec(PacketKind.HEAL, Recipients.HOLDER_AND_ALLIES),
            PacketSpec(PacketKind.DAMAGE, Recipients.ENEMIES),
        ),
        secondary_target=Recipients.ENEMIES,
        persistence=Persistence.SINGLE_MOMENT,
        redirects_incoming_damage=False,
        reads=(
            "beam_delay",
            "target_area_range_units",
            "enemy_max_health_true_damage_ratio",
        ),
        ramps=(DeclaredRamp("heal_min", "heal_max", LevelSubject.RECIPIENT),),
        zero_reason=(
            "the heal is a sourced level ramp read at each healed ally's own "
            "level and the beam a sourced share of each enemy's maximum "
            "health; a zero means the scenario cast no active"
        ),
    ),
    AllyProducer.INSPIRING_SPEECH: AllyPacketDeclaration(
        trigger=PacketTrigger.ITEM_ACTIVE,
        packets=(PacketSpec(PacketKind.MOVEMENT, Recipients.HOLDER_AND_ALLIES),),
        secondary_target=None,
        persistence=Persistence.TIMED_WINDOW,
        redirects_incoming_damage=False,
        reads=("bonus_move_speed_percent", "duration"),
        ramps=(),
        zero_reason=(
            "the bonus is a sourced ratio for a sourced duration; a zero means "
            "the scenario cast no active"
        ),
    ),
    AllyProducer.BREAKING_SHOCKWAVE: AllyPacketDeclaration(
        trigger=PacketTrigger.ITEM_ACTIVE,
        packets=(
            PacketSpec(PacketKind.SLOW, Recipients.ENEMIES),
            PacketSpec(PacketKind.MOVEMENT, Recipients.SELF),
        ),
        secondary_target=Recipients.SELF,
        persistence=Persistence.TIMED_WINDOW,
        redirects_incoming_damage=False,
        reads=(
            "front_offset",
            "area_radius",
            "slow_percent",
            "slow_duration",
            "bonus_move_speed_percent",
            "bonus_move_speed_duration",
        ),
        ramps=(),
        zero_reason=(
            "both halves are sourced ratios and durations under the sourced "
            "area radius; a zero means the scenario cast no active"
        ),
    ),
    AllyProducer.REAP: AllyPacketDeclaration(
        trigger=PacketTrigger.FIGHT_START,
        packets=(PacketSpec(PacketKind.ECONOMY, Recipients.SELF),),
        secondary_target=None,
        persistence=Persistence.SINGLE_MOMENT,
        redirects_incoming_damage=False,
        reads=("reap_max_gold", "reap_gold_per_minion", "reap_completion_gold"),
        ramps=(),
        zero_reason=(
            "the gold is a sourced per-minion rate over the authored kill "
            "count, plus a sourced completion bonus; a zero means the caller "
            "supplied no kills, and the packet is withheld rather than booked"
        ),
    ),
    AllyProducer.RAGE: AllyPacketDeclaration(
        trigger=PacketTrigger.BASIC_ATTACK,
        packets=(PacketSpec(PacketKind.MOVEMENT, Recipients.SELF),),
        secondary_target=None,
        persistence=Persistence.TIMED_WINDOW,
        redirects_incoming_damage=False,
        reads=(
            "rage_duration",
            "rage_bonus_move_speed_melee",
            "rage_bonus_move_speed_ranged",
        ),
        ramps=(),
        zero_reason=(
            "the bonus is a sourced ratio chosen by the holder's range class; "
            "a zero means the authored auto stream carried no basic attack"
        ),
    ),
    AllyProducer.SHARED_RICHES: AllyPacketDeclaration(
        trigger=PacketTrigger.FIGHT_START,
        packets=(PacketSpec(PacketKind.ECONOMY, Recipients.SELF),),
        secondary_target=None,
        persistence=Persistence.SINGLE_MOMENT,
        redirects_incoming_damage=False,
        reads=("support_quest_threshold",),
        ramps=(),
        zero_reason=(
            "the gold is the authored quest progress capped by the sourced "
            "threshold; a zero means the caller supplied no progress, and the "
            "packet is withheld rather than booked"
        ),
    ),
    AllyProducer.WARD: AllyPacketDeclaration(
        trigger=PacketTrigger.FIGHT_START,
        packets=(PacketSpec(PacketKind.VISION, Recipients.SELF),),
        secondary_target=None,
        persistence=Persistence.SINGLE_MOMENT,
        redirects_incoming_damage=False,
        reads=("ward_charges", "support_quest_threshold"),
        ramps=(),
        zero_reason=(
            "the ward count is the authored use count capped by the sourced "
            "charge count; a zero means the caller placed none, and the packet "
            "is withheld rather than booked"
        ),
    ),
    AllyProducer.NIGHTSTALKER: AllyPacketDeclaration(
        trigger=PacketTrigger.FIGHT_START,
        packets=(PacketSpec(PacketKind.VISION, Recipients.SELF),),
        secondary_target=None,
        persistence=Persistence.SINGLE_MOMENT,
        redirects_incoming_damage=False,
        reads=(
            "nightstalker_unseen_seconds",
            "nightstalker_trigger_window",
            "blackout_duration",
        ),
        ramps=(),
        zero_reason=(
            "the receipt states the sourced unseen gate, trigger window and "
            "denial duration for an authored ready state; a zero means the "
            "caller armed no Nightstalker, and no packet is emitted at all"
        ),
    ),
    AllyProducer.COMMAND: AllyPacketDeclaration(
        trigger=PacketTrigger.CROWD_CONTROL,
        packets=(PacketSpec(PacketKind.DAMAGE_MODIFIER, Recipients.TRIGGERING_ENEMY),),
        secondary_target=None,
        persistence=Persistence.TIMED_WINDOW,
        redirects_incoming_damage=False,
        reads=("command_damage_amp", "command_duration"),
        ramps=(),
        zero_reason=(
            "the amp is a sourced ratio on a target an authored immobilize "
            "marked; a zero means no immobilize was authored, which the bus's "
            "CC stream measured"
        ),
    ),
}


def _ally_compilability(declaration: AllyPacketDeclaration) -> Compilability:
    """Whether the compiled score kernel can stage this producer's packets.

    Derived from three declared axes rather than judged per item, because a
    per-item judgement is exactly how sixteen conservatism notes ended up
    indistinguishable from sixteen representability facts (D-43).  Each
    refusal names the kernel clause that produces it.

    The order is the order the kernel would meet them, not a preference: the
    self-shield is refused by the *build*-level scan before any template is
    staged, and the kind and duration clauses are the template gate itself.
    A producer that trips more than one is reported by the first gate that
    would have stopped it, which is the one whose receipt a caller would
    actually read.
    """
    if any(
        spec.kind is PacketKind.SHIELD and spec.recipients is Recipients.SELF
        for spec in declaration.packets
    ):
        return COMPILED_KERNEL_CANNOT_SELF_SHIELD
    unstageable = sorted(
        spec.kind.value
        for spec in declaration.packets
        if spec.kind not in COMPILED_SUPPORT_KINDS
    )
    if unstageable:
        return ReceiptOnly(
            "the compiled score kernel stages only shield and heal support "
            "templates: unrepresentable_template_receipt returns "
            f"support_kind=<kind> for {unstageable}",
            scope=ReceiptScope.SUPPORT_TEMPLATE_SHAPE,
        )
    if declaration.persistence is not Persistence.SINGLE_MOMENT:
        return ReceiptOnly(
            "the compiled score kernel stages only instantaneous support "
            "templates: unrepresentable_template_receipt returns "
            "support_duration=<d> for a shield or heal that stays in force",
            scope=ReceiptScope.SUPPORT_TEMPLATE_SHAPE,
        )
    return Compilable()


def _ally_packet_rule(
    producer: AllyProducer, owner: str, registry: ValueRegistry
) -> BehaviorRule:
    """One producer's declaration, bound to the owner whose entry carries it."""
    declaration = ALLY_PACKET_DECLARATIONS[producer]
    ramps = tuple(
        LevelRamp(
            LevelValueRef(
                registry, owner, ramp.min_key, ramp.max_key, "registry_start"
            ),
            ramp.subject,
        )
        for ramp in declaration.ramps
    )
    values: tuple[Any, ...] = tuple(
        ValueRef(registry, owner, key) for key in declaration.reads
    ) + tuple(ramp.reference for ramp in ramps)
    return BehaviorRule(
        family=RuleFamily.ALLY_PACKET,
        owner=owner,
        mechanic_id=f"{_mechanic_slug(owner)}.{producer.value}",
        payload=AllyPacketRule(
            producer=producer,
            trigger=declaration.trigger,
            packets=declaration.packets,
            secondary_target=declaration.secondary_target,
            persistence=declaration.persistence,
            redirects_incoming_damage=declaration.redirects_incoming_damage,
            values=values,
            ramps=ramps,
        ),
        compilability=_ally_compilability(declaration),
        receipt=receipt_for(
            registry, owner, declared=cached_source_receipt(owner, CACHED_ITEM_SOURCE)
        ),
        zero_policy=ZeroPolicy(Disposition.MEASURED, declaration.zero_reason),
    )


def producers_for(
    registry: ValueRegistry, entry: Mapping[str, Any]
) -> tuple[AllyProducer, ...]:
    """Every ally-packet producer *entry*'s value keys declare.

    A record can carry more than one — Dream Maker's two bubbles and the
    support quest's gold and ward are two mechanics each, with two packet
    sources and two capabilities apiece — so this returns a tuple in
    declaration order rather than an answer.
    """
    matched: list[AllyProducer] = []
    for producer, shape in ALLY_ENTRY_SHAPES.items():
        if shape.registry != registry or not shape.matches(entry):
            continue
        missing = shape.missing(entry)
        if missing:
            raise BehaviorCatalogError(
                f"{registry} declares the {producer.value} producer and is "
                f"missing {list(missing)}; a partly-parsed producer is a "
                "registry defect, not an item that quietly emits nothing"
            )
        matched.append(producer)
    return tuple(matched)


def owners_for(producer: AllyProducer) -> frozenset[str]:
    """Every registry owner whose entry carries *producer*.

    The inverse of :func:`producers_for`, derived by walking the registries
    rather than tabulated: "which item has this mechanic" is a question about
    the data, and answering it from a list beside the shapes would be the
    item-name literal this migration removes, re-entering as a lookup table.
    """
    shape = ALLY_ENTRY_SHAPES[producer]
    records = (
        item_effects.ITEM_EFFECTS
        if shape.registry == "ITEM_EFFECTS"
        else item_effects.ALLY_ITEM_EFFECTS
    )
    return frozenset(
        owner
        for owner, entry in records.items()
        if isinstance(entry, Mapping)
        and producer in producers_for(shape.registry, entry)
    )


def _compile_ally_packet(
    family: RuleFamily,
    owner: str,
    registry: ValueRegistry,
    entry: Mapping[str, Any],
) -> tuple[BehaviorRule, ...]:
    """Compile the cross-participant producers one registry entry declares."""
    del family
    rules = tuple(
        _ally_packet_rule(producer, owner, registry)
        for producer in producers_for(registry, entry)
        if producer in ALLY_PACKET_DECLARATIONS
    )
    for rule in rules:
        validate_rule(rule)
    return rules


def _defense_values(
    declaration: DefenseDeclaration, owner: str, registry: ValueRegistry
) -> tuple[Any, ...]:
    """Every number one defence may read, as references in declared order.

    Three shapes, in the order a reader of the declaration meets them: the
    plain sourced keys, the one-to-eighteen ramps, and the ramps that hold
    their base until a level the entry names.  Order is load-bearing only in
    that the resolver looks a reference up by the key it names, never by
    position.
    """
    return (
        tuple(ValueRef(registry, owner, key) for key in declaration.reads)
        + tuple(
            LevelValueRef(registry, owner, low, high, "linear_1_18")
            for low, high in declaration.ramps
        )
        + tuple(
            LateLevelValueRef(registry, owner, low, high, start, end)
            for low, high, start, end in declaration.late_ramps
        )
    )


def _defense_policy(owner: str, key: str | None, kind: type) -> Any:
    """One entry value whose *meaning* is policy, resolved into its enum.

    Read through ``required_effect_value`` so a missing key raises naming the
    item and the key — the registry's own fail-loud accessor rather than a
    second message that says the same thing differently — and converted at
    compile time, so a spelling the enum does not carry is a stop when the
    build is made rather than a string compared at runtime.
    """
    if key is None:
        return None
    value = item_effects.required_effect_value(owner, key)
    try:
        return kind(str(value))
    except ValueError as error:
        raise BehaviorCatalogError(
            f"ITEM_EFFECTS[{owner!r}][{key!r}] is {value!r}, which is not a "
            f"{kind.__name__}"
        ) from error


def _defense_rule(
    mechanic: DefenseMechanic, owner: str, registry: ValueRegistry
) -> BehaviorRule:
    """One defensive mechanic's declaration, bound to the owner that carries it.

    Every companion key is read through the registry's own accessor before
    the rule exists, so a partly parsed entry stops the build with the item
    and the key named instead of compiling a defence that quietly grants
    less than the item does.
    """
    declaration = DEFENSE_DECLARATIONS[mechanic]
    for key in declaration.shape.requires:
        item_effects.required_effect_value(owner, key)
    family = DEFENSE_SOURCE_FAMILY[mechanic]
    values = _defense_values(declaration, owner, registry)
    absorbs = _defense_policy(owner, declaration.absorbs_key, ShieldAbsorbs)
    payload: Any
    if family is RuleFamily.OPENING_DEFENSE:
        payload = OpeningDefenseRule(
            mechanic=mechanic,
            writes=declaration.writes,
            exclusivity=declaration.exclusivity,
            option=declaration.option,
            values=values,
        )
    elif family is RuleFamily.THRESHOLD_DEFENSE:
        payload = ThresholdDefenseRule(
            mechanic=mechanic,
            writes=declaration.writes,
            exclusivity=declaration.exclusivity,
            threshold=_optional_key_ref(registry, owner, declaration.threshold_key),
            duration=_optional_key_ref(registry, owner, declaration.duration_key),
            absorbs=absorbs,
            values=values,
        )
    elif family is RuleFamily.SUSTAIN:
        payload = ReceivedHealingRule(
            mechanic=mechanic,
            writes=declaration.writes,
            exclusivity=declaration.exclusivity,
            values=values,
        )
    elif family is RuleFamily.DAMAGE_ROUTING:
        payload = DamageDeferralRule(
            mechanic=mechanic,
            writes=declaration.writes,
            exclusivity=declaration.exclusivity,
            values=values,
        )
    elif family is RuleFamily.COMBAT_STATE:
        payload = CombatStateRule(
            mechanic=mechanic,
            writes=declaration.writes,
            exclusivity=declaration.exclusivity,
            option=declaration.option,
            values=values,
        )
    else:
        payload = ReactiveRule(
            mechanic=mechanic,
            writes=declaration.writes,
            exclusivity=declaration.exclusivity,
            trigger=declaration.trigger,
            absorbs=absorbs,
            damage_class=_defense_policy(
                owner, declaration.damage_class_key, DamageClass
            ),
            values=values,
        )
    rule = BehaviorRule(
        family=family,
        owner=owner,
        mechanic_id=f"{_mechanic_slug(owner)}.{mechanic.value}",
        payload=payload,
        compilability=COMPILED_KERNEL_CANNOT_STAGE.get(mechanic, Compilable()),
        receipt=receipt_for(registry, owner, declared=DEFENSE_RECEIPTS.get(mechanic)),
        zero_policy=declaration.zero_policy,
    )
    validate_rule(rule)
    return rule


def _optional_key_ref(registry: ValueRegistry, owner: str, key: str | None) -> Any:
    """A reference to *key*, or ``None`` where the mechanic declares none."""
    return None if key is None else ValueRef(registry, owner, key)


def defense_mechanics_for(
    family: RuleFamily, entry: Mapping[str, Any]
) -> tuple[DefenseMechanic, ...]:
    """Every defence of *family* one registry entry declares, in resolution order.

    Iterating :class:`~.item_behavior.DefenseMechanic` rather than the
    declarations mapping is what keeps the resolution order the enum's, so
    one entry carrying two mechanics resolves them in the same order two
    entries would.
    """
    return tuple(
        mechanic
        for mechanic in DefenseMechanic
        if DEFENSE_SOURCE_FAMILY[mechanic] is family
        and mechanic in DEFENSE_DECLARATIONS
        and DEFENSE_DECLARATIONS[mechanic].shape.claims(entry)
    )


def _compile_defense(
    family: RuleFamily,
    owner: str,
    registry: ValueRegistry,
    entry: Mapping[str, Any],
) -> tuple[BehaviorRule, ...]:
    """Compile the defences of one family that a registry entry declares.

    An entry declaring none compiles none, and that is an answer: Guardian
    Angel's mechanic is a resurrection, so this compiler returns nothing.
    """
    return tuple(
        _defense_rule(mechanic, owner, registry)
        for mechanic in defense_mechanics_for(family, entry)
        if _defense_flag_holds(mechanic, entry)
    )


def _defense_flag_holds(mechanic: DefenseMechanic, entry: Mapping[str, Any]) -> bool:
    """Whether the entry's own flags say this mechanic is live at the opening."""
    if mechanic is DefenseMechanic.ANNUL:
        return bool(entry.get("spell_shield_ready", False))
    return True


def _compile_opening_defense(
    family: RuleFamily,
    owner: str,
    registry: ValueRegistry,
    entry: Mapping[str, Any],
) -> tuple[BehaviorRule, ...]:
    """Defences already in force when the modeled exchange opens."""
    return _compile_defense(family, owner, registry, entry)


def _compile_threshold_defense(
    family: RuleFamily,
    owner: str,
    registry: ValueRegistry,
    entry: Mapping[str, Any],
) -> tuple[BehaviorRule, ...]:
    """Defences armed by the subject's health crossing a declared fraction."""
    return _compile_defense(family, owner, registry, entry)


def _compile_combat_state(
    family: RuleFamily,
    owner: str,
    registry: ValueRegistry,
    entry: Mapping[str, Any],
) -> tuple[BehaviorRule, ...]:
    """Defences that accrue, or are spent, while the fight is in progress."""
    return _compile_defense(family, owner, registry, entry)


def _compile_reactive(
    family: RuleFamily,
    owner: str,
    registry: ValueRegistry,
    entry: Mapping[str, Any],
) -> tuple[BehaviorRule, ...]:
    """Defences armed by an incoming event rather than by the clock."""
    return _compile_defense(family, owner, registry, entry)


# ── stat derivation (3.7 residual) ────────────────────────────────────────
#
# Eight shapes the build's stat block is made of, told apart by the value
# keys of the entry that carries them — the same device the defence, sustain
# and ally families use, and for the same reason: four tags land in this
# family and one of them (``stat_conversion``) covers eighteen entries whose
# only common property is that they end up in the stat block.
#
# What this migration makes visible is ``availability``.  Three of these
# grants are conditional buffs the resolver folds in *whole* because it has
# no event to arm them from — ``item_effects.passive_attack_speed_bonus``
# says so in a docstring and nothing checked it — and five more exist only
# when the request's item options say so.  Those are now fields.


class StatConversionSchema(NamedTuple):
    """What one conversion key means: from which stat, into which, and how.

    ``ranged_key`` is the second half of a rate the registry pays melee and
    ranged holders differently; ``basis_unit_key`` the size of one unit of
    the basis where the rate is stated per unit rather than per point; and
    ``flat_base_key`` the part of the grant that does not scale.  Each is
    ``None`` where the conversion genuinely has none, which is a different
    claim from a key that resolves to zero.
    """

    basis: StatBasis
    granted: DerivedStat
    ranged_key: str | None
    basis_unit_key: str | None
    flat_base_key: str | None


STAT_CONVERSIONS: Mapping[str, StatConversionSchema] = {
    "bonus_mana_to_ap_ratio": StatConversionSchema(
        StatBasis.BONUS_MANA, DerivedStat.ABILITY_POWER, None, None, None
    ),
    "max_mana_to_ad_ratio": StatConversionSchema(
        StatBasis.MAX_MANA, DerivedStat.ATTACK_DAMAGE, None, None, None
    ),
    "bonus_mana_to_health_ratio": StatConversionSchema(
        StatBasis.BONUS_MANA, DerivedStat.HEALTH, None, None, None
    ),
    "bonus_mana_to_heal_shield_power_ratio": StatConversionSchema(
        StatBasis.BONUS_MANA, DerivedStat.HEAL_AND_SHIELD_POWER, None, None, None
    ),
    "bonus_health_to_ad_ratio": StatConversionSchema(
        StatBasis.BONUS_HEALTH, DerivedStat.ATTACK_DAMAGE, None, None, None
    ),
    "base_ad_to_bonus_ad_ratio": StatConversionSchema(
        StatBasis.BASE_ATTACK_DAMAGE, DerivedStat.ATTACK_DAMAGE, None, None, None
    ),
    "adaptive_force_per_total_move_speed": StatConversionSchema(
        StatBasis.TOTAL_MOVE_SPEED, DerivedStat.ADAPTIVE_FORCE, None, None, None
    ),
    "ap_per_mana_regen_unit": StatConversionSchema(
        StatBasis.BONUS_MANA_REGEN_PERCENT,
        DerivedStat.ABILITY_POWER,
        None,
        "mana_regen_threshold_percent",
        None,
    ),
    "famine_bonus_ad_to_ability_haste_melee": StatConversionSchema(
        StatBasis.BONUS_ATTACK_DAMAGE,
        DerivedStat.ABILITY_HASTE,
        "famine_bonus_ad_to_ability_haste_ranged",
        None,
        "famine_base_ability_haste",
    ),
}

# Which keys state a share by which a total stat is increased, and of what.
STAT_MULTIPLIERS: Mapping[str, DerivedStat] = {
    "ap_percent_increase": DerivedStat.ABILITY_POWER,
    "item_bonus_health_ratio": DerivedStat.HEALTH,
}

# The charge ledger, whole or not at all, plus the optional transform pair.
MANAFLOW_KEYS = (
    "manaflow_charge_interval",
    "manaflow_bonus_mana_per_trigger",
    "manaflow_bonus_mana_per_champion",
    "manaflow_bonus_mana_max",
)
MANAFLOW_TRANSFORM_KEYS = ("manaflow_max_charges", "manaflow_transform_bonus_mana")


class StackedStatSchema(NamedTuple):
    """One per-stack key's meaning, with both ceilings it may declare."""

    granted: DerivedStat
    ranged_key: str | None
    max_stacks_key: str | None
    max_stacks_ranged_key: str | None
    cap_key: str | None
    flat_base_key: str | None
    duration_key: str | None
    level_gain_key: str | None
    availability: StatAvailability


STACKED_STATS: Mapping[str, StackedStatSchema] = {
    "timeless_bonus_ap_per_stack": StackedStatSchema(
        DerivedStat.ABILITY_POWER,
        None,
        "timeless_max_stacks",
        None,
        None,
        None,
        None,
        "timeless_level_gain_at_max",
        StatAvailability.BUILD_OPTION,
    ),
    "timeless_bonus_health_per_stack": StackedStatSchema(
        DerivedStat.HEALTH,
        None,
        "timeless_max_stacks",
        None,
        None,
        None,
        None,
        "timeless_level_gain_at_max",
        StatAvailability.BUILD_OPTION,
    ),
    "timeless_bonus_mana_per_stack": StackedStatSchema(
        DerivedStat.MANA,
        None,
        "timeless_max_stacks",
        None,
        None,
        None,
        None,
        "timeless_level_gain_at_max",
        StatAvailability.BUILD_OPTION,
    ),
    "eminence_ad_per_stack": StackedStatSchema(
        DerivedStat.ATTACK_DAMAGE,
        None,
        None,
        None,
        None,
        "eminence_base_ad",
        "eminence_duration",
        None,
        StatAvailability.BUILD_OPTION,
    ),
    "crit_chance_per_stack_melee": StackedStatSchema(
        DerivedStat.CRITICAL_STRIKE_CHANCE,
        "crit_chance_per_stack_ranged",
        "crit_stack_max_melee",
        "crit_stack_max_ranged",
        "crit_chance_cap",
        None,
        None,
        None,
        StatAvailability.BUILD_OPTION,
    ),
    # Slay's per-takedown omnivamp: both ceilings, because the registry states
    # both and they are different claims — ten stacks, and the six percent
    # those ten come to.  A takedown is not pre-fight-projectable, so the
    # stacks arrive as the bounded scenario control.
    "slay_omnivamp_per_takedown": StackedStatSchema(
        DerivedStat.OMNIVAMP_PERCENT,
        None,
        "slay_max_stacks",
        None,
        "slay_max_omnivamp",
        None,
        None,
        None,
        StatAvailability.BUILD_OPTION,
    ),
}


class FlatStatGrantSchema(NamedTuple):
    """One flat grant's meaning, including whether anything arms it."""

    granted: DerivedStat
    ranged_key: str | None
    duration_key: str | None
    cooldown_key: str | None
    window_key: str | None
    availability: StatAvailability


FLAT_STAT_GRANTS: Mapping[str, FlatStatGrantSchema] = {
    "ultimate_haste": FlatStatGrantSchema(
        DerivedStat.ULTIMATE_HASTE, None, None, None, None, StatAvailability.ALWAYS
    ),
    # Two items carry this pair and the resolver folds both in whole: one
    # grants it from an ultimate cast and the other to everyone nearby.  The
    # ally-side half of the second is its own declaration; this is the
    # holder-side half both of them have.
    "bonus_attack_speed_melee": FlatStatGrantSchema(
        DerivedStat.ATTACK_SPEED_PERCENT,
        "bonus_attack_speed_ranged",
        "duration",
        "cooldown",
        None,
        StatAvailability.ASSUMED_ACTIVE,
    ),
    "bonus_attack_speed_percent": FlatStatGrantSchema(
        DerivedStat.ATTACK_SPEED_PERCENT,
        None,
        "duration",
        "cooldown",
        None,
        StatAvailability.ASSUMED_ACTIVE,
    ),
    "rapids_bonus_ap": FlatStatGrantSchema(
        DerivedStat.ABILITY_POWER,
        None,
        None,
        None,
        None,
        StatAvailability.ASSUMED_ACTIVE,
    ),
    "feast_omnivamp_percent": FlatStatGrantSchema(
        DerivedStat.OMNIVAMP_PERCENT,
        None,
        "feast_duration",
        None,
        "feast_trigger_window",
        StatAvailability.BUILD_OPTION,
    ),
}

# The remaining three shapes, each carried by exactly one entry today and
# each keyed by its own signature key rather than by the item that has it.
STAT_AURA_KEYS = ("attack_speed_reduction", "range_units")
THRESHOLD_REGEN_KEYS = (
    "heart_bonus_health_threshold",
    "heart_max_health_ratio_per_tick",
    "heart_tick_interval",
    "heart_champion_damage_cooldown",
    "heart_nonchampion_damage_cooldown",
)
ULTIMATE_REFUND_KEYS = (
    "ultimate_refund_base_ratio",
    "ultimate_refund_per_lethality_ratio",
    "ultimate_refund_trigger_window",
)
# The casting trade an item active makes while its own window is open: what a
# cast costs and how fast a basic ability's cooldown progresses, plus the
# window both are paid inside.  Signature key first, as every group here.
ACTIVE_WINDOW_CAST_ECONOMY_KEYS = (
    "mana_cost_multiplier",
    "basic_cooldown_progress_multiplier",
    "mana_made_real_duration",
)
# A share of the holder's maximum resource, restored over a window in a stated
# number of ticks.  Signature key first, as every group here.
RESOURCE_RESTORE_KEYS = (
    "enlighten_restore_percent",
    "enlighten_duration_seconds",
    "enlighten_ticks",
)

# Which key states a number no stat block holds, and which channel it
# reaches.  Keyed by the registry key rather than by the item, so both
# entries carrying Helping Hand declare the one mechanic and a fight whose
# target class arms it arms both — which is what keeps "who pays this" from
# being a second name list beside the declaration.
RESTRICTED_CHANNELS: Mapping[str, RestrictedChannel] = {
    "summoner_spell_haste": RestrictedChannel.SUMMONER_SPELL_HASTE,
    "helping_hand_minion_damage": RestrictedChannel.MINION_CLASS_ON_HIT,
}

# Entries this family's tags claim whose *whole* mechanic another family
# already declares, keyed by the signature key that proves it.  The same
# device the defence table uses for Everlasting: a second declaration would
# be two homes for one mechanic, and an entry that silently compiled nothing
# would be indistinguishable from one nobody had looked at.
STAT_DERIVATION_DECLARED_ELSEWHERE: Mapping[str, str] = {
    "rage_duration": (
        "declared as the ally packet that grants the move speed; Rage is a "
        "movement buff the packet ledger carries and not a number the stat "
        "block holds"
    ),
    "support_quest_threshold": (
        "declared as the ally packet that pays the shared gold and the ward "
        "charges; neither is a stat the build's block holds"
    ),
    "health_threshold": (
        "declared as the threshold defence the resolver builds, together with "
        "the omnivamp its own Lifeline grants"
    ),
}

_SOURCED_STAT_ZERO = ZeroPolicy(
    Disposition.MEASURED,
    "every rate is a sourced registry number; a zero means the registry "
    "states the derivation grants nothing, which the rule read rather than "
    "defaulted",
)


def _stat_rule(
    owner: str,
    registry: ValueRegistry,
    mechanic: str,
    payload: Any,
) -> BehaviorRule:
    """One stat-derivation declaration, with the citation its entry resolves to.

    Every rule of the family is ``Compilable``: the stat block is resolved
    before any damage exists and the compiled kernel reads the resolved
    block, so there is nothing here for it to fail to represent.
    """
    return BehaviorRule(
        family=RuleFamily.STAT_DERIVATION,
        owner=owner,
        mechanic_id=f"{_mechanic_slug(owner)}.{mechanic}",
        payload=payload,
        compilability=Compilable(),
        receipt=receipt_for(
            registry, owner, declared=cached_source_receipt(owner, CACHED_ITEM_SOURCE)
        ),
        zero_policy=_SOURCED_STAT_ZERO,
    )


def _split_or_ref(
    owner: str,
    registry: ValueRegistry,
    melee_key: str,
    ranged_key: str | None,
) -> ValueRef | MeleeRangedSplit:
    """One rate, as a melee/ranged pair where the registry states two."""
    if ranged_key is None:
        return ValueRef(registry, owner, melee_key)
    return MeleeRangedSplit(
        melee=ValueRef(registry, owner, melee_key),
        ranged=ValueRef(registry, owner, ranged_key),
    )


def _stat_conversion_rules(
    owner: str,
    registry: ValueRegistry,
    entry: Mapping[str, Any],
    schema: frozenset[str],
) -> list[BehaviorRule]:
    """Every stat one entry derives from another, in table order."""
    return [
        _stat_rule(
            owner,
            registry,
            f"{spec.granted.value}_from_{spec.basis.value}",
            StatConversionRule(
                basis=spec.basis,
                granted=spec.granted,
                ratio=_split_or_ref(owner, registry, key, spec.ranged_key),
                basis_unit=(
                    None
                    if spec.basis_unit_key is None
                    else ValueRef(registry, owner, spec.basis_unit_key)
                ),
                flat_base=(
                    None
                    if spec.flat_base_key is None
                    else ValueRef(registry, owner, spec.flat_base_key)
                ),
                availability=StatAvailability.ALWAYS,
                subject=Subject.HOLDER,
            ),
        )
        for key, spec in STAT_CONVERSIONS.items()
        if key in schema
    ]


def _stacked_stat_rules(
    owner: str,
    registry: ValueRegistry,
    entry: Mapping[str, Any],
    schema: frozenset[str],
) -> list[BehaviorRule]:
    """Every stat one entry grows per stack, in table order.

    ``grants_level_at_max`` is the one structural flag in the family and is
    read off the entry as a :class:`Const` rather than a :class:`ValueRef`:
    the registry states it as a boolean, and a reference into a non-numeric
    key raises.  It is still live — the rules are recompiled from the
    registry on every call, so a refresh moves it like everything else.
    """
    return [
        _stat_rule(
            owner,
            registry,
            f"{spec.granted.value}_per_stack",
            StackedStatRule(
                granted=spec.granted,
                per_stack=_split_or_ref(owner, registry, key, spec.ranged_key),
                max_stacks=(
                    None
                    if spec.max_stacks_key is None
                    else _split_or_ref(
                        owner, registry, spec.max_stacks_key, spec.max_stacks_ranged_key
                    )
                ),
                cap=(
                    None
                    if spec.cap_key is None
                    else ValueRef(registry, owner, spec.cap_key)
                ),
                flat_base=(
                    None
                    if spec.flat_base_key is None
                    else ValueRef(registry, owner, spec.flat_base_key)
                ),
                duration=(
                    None
                    if spec.duration_key is None
                    else ValueRef(registry, owner, spec.duration_key)
                ),
                grants_level_at_max=(
                    None
                    if spec.level_gain_key is None
                    else Const(
                        1.0 if bool(entry.get(spec.level_gain_key)) else 0.0, "flag"
                    )
                ),
                availability=spec.availability,
                subject=Subject.HOLDER,
            ),
        )
        for key, spec in STACKED_STATS.items()
        if key in schema
    ]


def _flat_stat_grant_rules(
    owner: str,
    registry: ValueRegistry,
    entry: Mapping[str, Any],
    schema: frozenset[str],
) -> list[BehaviorRule]:
    """Every flat stat one entry grants, in table order."""
    return [
        _stat_rule(
            owner,
            registry,
            f"{spec.granted.value}_grant",
            FlatStatGrantRule(
                granted=spec.granted,
                amount=_split_or_ref(owner, registry, key, spec.ranged_key),
                duration=(
                    None
                    if spec.duration_key is None
                    else _optional_ref(owner, registry, entry, spec.duration_key)
                ),
                cooldown=(
                    None
                    if spec.cooldown_key is None
                    else _optional_ref(owner, registry, entry, spec.cooldown_key)
                ),
                trigger_window=(
                    None
                    if spec.window_key is None
                    else ValueRef(registry, owner, spec.window_key)
                ),
                availability=spec.availability,
                subject=Subject.HOLDER,
            ),
        )
        for key, spec in FLAT_STAT_GRANTS.items()
        if key in schema
    ]


def _manaflow_rule(
    owner: str, registry: ValueRegistry, schema: frozenset[str]
) -> BehaviorRule:
    """The charge ledger, with its transform pair declared whole or absent."""
    interval, per_trigger, per_champion, ceiling = MANAFLOW_KEYS
    missing = sorted(key for key in MANAFLOW_KEYS if key not in schema)
    if missing:
        raise BehaviorCatalogError(
            f"{registry}[{owner!r}] carries a manaflow ledger missing {missing}; "
            "a charge ledger is claimed whole or not at all, because half of "
            "one is a parse that dropped a key rather than a weaker item"
        )
    charges_key, transform_key = MANAFLOW_TRANSFORM_KEYS
    return _stat_rule(
        owner,
        registry,
        "mana_charge",
        ManaflowRule(
            granted=DerivedStat.MANA,
            charge_interval=ValueRef(registry, owner, interval),
            bonus_mana_per_trigger=ValueRef(registry, owner, per_trigger),
            bonus_mana_per_champion=ValueRef(registry, owner, per_champion),
            bonus_mana_max=ValueRef(registry, owner, ceiling),
            max_charges=(
                ValueRef(registry, owner, charges_key)
                if charges_key in schema
                else None
            ),
            transform_bonus_mana=(
                ValueRef(registry, owner, transform_key)
                if transform_key in schema
                else None
            ),
            availability=StatAvailability.BUILD_OPTION,
            subject=Subject.HOLDER,
        ),
    )


def _keyed_stat_rules(
    owner: str, registry: ValueRegistry, schema: frozenset[str]
) -> list[BehaviorRule]:
    """The four single-carrier shapes, each claimed by its own key group."""
    rules: list[BehaviorRule] = []
    if MANAFLOW_KEYS[0] in schema:
        rules.append(_manaflow_rule(owner, registry, schema))
    reduction_key, radius_key = STAT_AURA_KEYS
    if reduction_key in schema:
        rules.append(
            _stat_rule(
                owner,
                registry,
                f"{DerivedStat.ATTACK_SPEED_PERCENT.value}_aura",
                StatAuraRule(
                    granted=DerivedStat.ATTACK_SPEED_PERCENT,
                    reduction=ValueRef(registry, owner, reduction_key),
                    radius=ValueRef(registry, owner, radius_key),
                    availability=StatAvailability.ALWAYS,
                    subject=Subject.TARGET,
                ),
            )
        )
    if THRESHOLD_REGEN_KEYS[1] in schema:
        threshold, share, tick, champion_cooldown, other_cooldown = THRESHOLD_REGEN_KEYS
        rules.append(
            _stat_rule(
                owner,
                registry,
                "threshold_regeneration",
                ThresholdRegenRule(
                    granted=DerivedStat.HEALTH_REGEN,
                    bonus_health_threshold=ValueRef(registry, owner, threshold),
                    share_of_max_health=ValueRef(registry, owner, share),
                    tick_interval=ValueRef(registry, owner, tick),
                    champion_damage_cooldown=ValueRef(
                        registry, owner, champion_cooldown
                    ),
                    nonchampion_damage_cooldown=ValueRef(
                        registry, owner, other_cooldown
                    ),
                    availability=StatAvailability.ALWAYS,
                    subject=Subject.HOLDER,
                ),
            )
        )
    if ULTIMATE_REFUND_KEYS[0] in schema:
        base, per_lethality, window = ULTIMATE_REFUND_KEYS
        rules.append(
            _stat_rule(
                owner,
                registry,
                "ultimate_refund",
                UltimateRefundRule(
                    base_ratio=ValueRef(registry, owner, base),
                    per_lethality_ratio=ValueRef(registry, owner, per_lethality),
                    trigger_window=ValueRef(registry, owner, window),
                    availability=StatAvailability.ALWAYS,
                    subject=Subject.HOLDER,
                ),
            )
        )
    if RESOURCE_RESTORE_KEYS[0] in schema:
        share, duration, ticks = RESOURCE_RESTORE_KEYS
        rules.append(
            _stat_rule(
                owner,
                registry,
                "resource_restore",
                ResourceRestoreRule(
                    granted=DerivedStat.MANA,
                    share_of_maximum=ValueRef(registry, owner, share),
                    duration=ValueRef(registry, owner, duration),
                    ticks=ValueRef(registry, owner, ticks),
                    # The level-up the restore is paid on is a moment the
                    # fixed-level model cannot produce, so the request states
                    # it or nothing is restored at all.
                    availability=StatAvailability.BUILD_OPTION,
                    subject=Subject.HOLDER,
                ),
            )
        )
    if ACTIVE_WINDOW_CAST_ECONOMY_KEYS[0] in schema:
        cost, cooldown_progress, window = ACTIVE_WINDOW_CAST_ECONOMY_KEYS
        rules.append(
            _stat_rule(
                owner,
                registry,
                "active_window_cast_economy",
                ActiveWindowCastEconomyRule(
                    resource_cost_multiplier=ValueRef(registry, owner, cost),
                    basic_cooldown_progress_multiplier=ValueRef(
                        registry, owner, cooldown_progress
                    ),
                    window=ValueRef(registry, owner, window),
                    # The window is opened by a bounded scenario control, not
                    # by anything the fight produces, which is exactly what
                    # this member means.
                    availability=StatAvailability.BUILD_OPTION,
                    subject=Subject.HOLDER,
                ),
            )
        )
    return rules


def _restricted_channel_rules(
    owner: str, registry: ValueRegistry, schema: frozenset[str]
) -> list[BehaviorRule]:
    """Every number one entry sends to a channel this model does not run."""
    return [
        _stat_rule(
            owner,
            registry,
            f"{channel.value}_channel",
            RestrictedChannelRule(
                channel=channel,
                amount=ValueRef(registry, owner, key),
                availability=StatAvailability.ALWAYS,
                subject=Subject.HOLDER,
            ),
        )
        for key, channel in RESTRICTED_CHANNELS.items()
        if key in schema
    ]


def _penetration_channel_rule(
    owner: str, registry: ValueRegistry, entry: Mapping[str, Any]
) -> BehaviorRule:
    """Where one entry says its cached percent armour penetration lands.

    The value is read off the live entry rather than through a
    :class:`~..value_ref.ValueRef` because it is not a number: it is the
    structural flag that picks one of two stat-block fields, and the schema —
    not the parse — is what claimed the mechanic, so a dropped key would have
    stopped the compile before reaching here.
    """
    bonus_only = bool(entry.get(ARMOR_PENETRATION_CHANNEL_KEY, False))
    return _stat_rule(
        owner,
        registry,
        ARMOR_PENETRATION_CHANNEL_TAG,
        PenetrationChannelRule(
            granted=(
                DerivedStat.ARMOR_PENETRATION_BONUS_PERCENT
                if bonus_only
                else DerivedStat.ARMOR_PENETRATION_PERCENT
            ),
            availability=StatAvailability.ALWAYS,
            subject=Subject.HOLDER,
        ),
    )


def _compile_stat_derivation(
    family: RuleFamily,
    owner: str,
    registry: ValueRegistry,
    entry: Mapping[str, Any],
) -> tuple[BehaviorRule, ...]:
    """Compile every stat one registry entry derives, grants or reduces.

    A fan-out rather than a ladder: one entry routinely carries two or three
    of these — Archangel's converts bonus mana *and* runs a charge ledger,
    and Warmog's multiplies bonus health *and* regenerates from it.  An entry
    this family's tags claim that compiles nothing is a stop unless
    :data:`STAT_DERIVATION_DECLARED_ELSEWHERE` says which family already owns
    its whole mechanic, so "this item derives no stat" is never something the
    compiler concludes by silence.
    """
    del family
    schema = _schema_keys(owner, registry, entry)
    rules = _stat_conversion_rules(owner, registry, entry, schema)
    rules.extend(
        _stat_rule(
            owner,
            registry,
            f"{granted.value}_multiplier",
            StatMultiplierRule(
                granted=granted,
                share=ValueRef(registry, owner, key),
                availability=StatAvailability.ALWAYS,
                subject=Subject.HOLDER,
            ),
        )
        for key, granted in STAT_MULTIPLIERS.items()
        if key in schema
    )
    rules.extend(_stacked_stat_rules(owner, registry, entry, schema))
    rules.extend(_flat_stat_grant_rules(owner, registry, entry, schema))
    rules.extend(_keyed_stat_rules(owner, registry, schema))
    rules.extend(_restricted_channel_rules(owner, registry, schema))
    if ARMOR_PENETRATION_CHANNEL_KEY in schema:
        rules.append(_penetration_channel_rule(owner, registry, entry))
    if not rules:
        elsewhere = sorted(
            reason
            for key, reason in STAT_DERIVATION_DECLARED_ELSEWHERE.items()
            if key in schema
        )
        if not elsewhere:
            raise BehaviorCatalogError(
                f"{registry}[{owner!r}] is tagged into the stat-derivation "
                "family and carries none of its signature keys; a derivation "
                "that derives nothing is a parse that failed, not an item with "
                "no behaviour"
            )
    for rule in rules:
        validate_rule(rule)
    return tuple(rules)


# One module-level ``def`` per key, keyed by a closed enum, totality asserted
# — D-52's three conditions, which is what makes a callable registry a ruled
# exception rather than a hole in "no callables in declarations".
_COMPILERS: Mapping[RuleFamily, Compiler] = {
    RuleFamily.ON_HIT_STRIKE: _compile_on_hit_strike,
    RuleFamily.CHARGED_STRIKE: _compile_charged_strike,
    RuleFamily.SPELLBLADE: _compile_spellblade,
    RuleFamily.CAST_PROC: _compile_cast_proc,
    RuleFamily.PERIODIC: _compile_periodic,
    RuleFamily.ACTIVE_CAST: _compile_active_cast,
    RuleFamily.SECONDARY_TARGET: _compile_secondary_target,
    RuleFamily.DELTA_AMP: _compile_delta_amp,
    RuleFamily.RESISTANCE_SHRED: _compile_resistance_shred,
    RuleFamily.CRIT_PROFILE: _compile_crit_profile,
    RuleFamily.DAMAGE_ROUTING: _compile_damage_routing,
    RuleFamily.OPENING_DEFENSE: _compile_opening_defense,
    RuleFamily.THRESHOLD_DEFENSE: _compile_threshold_defense,
    RuleFamily.COMBAT_STATE: _compile_combat_state,
    RuleFamily.REACTIVE: _compile_reactive,
    RuleFamily.SUSTAIN: _compile_sustain,
    RuleFamily.STAT_DERIVATION: _compile_stat_derivation,
    RuleFamily.ALLY_PACKET: _compile_ally_packet,
}


# ── compilation ───────────────────────────────────────────────────────────


def registry_entries(owner: str) -> tuple[tuple[ValueRegistry, RuleFamily, Any], ...]:
    """Every registry entry that names *owner*, with the family it declares.

    An owner can appear in both registries — six do, because a dual-sided
    mechanic has a pair-side number and an ally-packet number — so this
    returns a tuple rather than an entry.
    """
    found: list[tuple[ValueRegistry, RuleFamily, Any]] = []
    item_entry = item_effects.ITEM_EFFECTS.get(owner)
    if isinstance(item_entry, Mapping):
        tag = item_entry.get("type")
        family = TAG_FAMILY.get(str(tag))
        if family is None:
            raise BehaviorCatalogError(
                f"ITEM_EFFECTS[{owner!r}] carries tag {tag!r}, which no family "
                "claims — extend TAG_FAMILY in the slice that models it"
            )
        found.append(("ITEM_EFFECTS", family, item_entry))
    ally_entry = item_effects.ALLY_ITEM_EFFECTS.get(owner)
    if isinstance(ally_entry, Mapping):
        found.append(("ALLY_ITEM_EFFECTS", RuleFamily.ALLY_PACKET, ally_entry))
    return tuple(found)


# One owner's compiled rules, keyed by cache generation and owner, holding
# the registry entries they were compiled from (D-49).  Never memoized
# *across* a generation, which is the property the catalog owes: the key
# carries ``data_version()`` and the value carries the entry objects, so a
# refresh that rebuilds the registry without bumping the counter still misses
# — ``refresh_item_effects()`` replaces every entry dict, and holding the old
# ones is also what makes an identity check safe from a recycled ``id()``.
_BEHAVIOR_RULES_MEMO: dict[
    tuple[int, str],
    tuple[Any, Any, Any, tuple[BehaviorRule, ...]],
] = {}


def _live_registry_records(owner: str) -> tuple[Any, Any, Any]:
    """The three registry records *owner*'s rules compile from, read raw.

    Everything :func:`registry_entries` builds is derived from these three.
    ``None`` where the registry holds nothing or declares no amp-chain slot.
    """
    return (
        item_effects.ITEM_EFFECTS.get(owner),
        item_effects.ALLY_ITEM_EFFECTS.get(owner),
        rune_effects.RUNE_EFFECTS.get(owner) if owner in RUNE_AMP_SLOTS else None,
    )


def behavior_rules(owner: str) -> tuple[BehaviorRule, ...]:
    """Compile *owner*'s declarations from the live registries.

    An owner with no registry entry has no rules, and that is an *answer*:
    the item declares no behaviour at all.  An owner **with** an entry whose
    family is not yet migrated also returns no rules, and that is a
    *refusal*, which is why :func:`undeclared_owners` names it.

    Memoized within one cache generation and never across one: the optimizer
    asks a quarter of a million times per request, and the answer can only
    change when the registries do.  Both halves of that are checked, the
    generation counter in the key and the registry records in the value,
    because ``refresh_item_effects()`` rebuilds without writing a cache file.

    The re-check is by entry object identity, the memo's one blind spot:
    mutating a live entry in place leaves the same object in the registry, so
    the memo serves its old contents until ``data_version()`` moves.
    """
    key = (data_registry.data_version(), owner)
    cached = _BEHAVIOR_RULES_MEMO.get(key)
    if cached is not None:
        records = _live_registry_records(owner)
        if (
            cached[0] is records[0]
            and cached[1] is records[1]
            and cached[2] is records[2]
        ):
            return cached[3]
    entries = registry_entries(owner) + rune_amp_entries(owner)
    rules: list[BehaviorRule] = []
    for registry, family, entry in entries:
        for claimed in entry_families(registry, family, entry, owner):
            rules.extend(_COMPILERS[claimed](claimed, owner, registry, entry))
    compiled = tuple(rules)
    data_registry.store_for_generation(
        _BEHAVIOR_RULES_MEMO, key, (*_live_registry_records(owner), compiled)
    )
    return compiled


def rune_amp_entries(owner: str) -> tuple[tuple[ValueRegistry, RuleFamily, Any], ...]:
    """The rune record *owner* declares an amp-chain slot from, if any.

    Deliberately not part of :func:`registry_entries`: counter 3's population
    is the two **item** registries, and folding runes into it would silently
    change what the frontier's headline number counts.  Runes are still
    bound by rule 5 — their numbers are references — they are simply not
    entries of the registries that counter measures.
    """
    if owner not in RUNE_AMP_SLOTS:
        return ()
    entry = rune_effects.RUNE_EFFECTS.get(owner)
    if not isinstance(entry, Mapping):
        raise BehaviorCatalogError(
            f"{owner!r} declares an amp-chain slot and RUNE_EFFECTS holds no "
            "record for it — a declaration against a missing rune is a stop, "
            "not a rune that quietly amplifies nothing"
        )
    return (("RUNE_EFFECTS", RuleFamily.DELTA_AMP, entry),)


def declares_runtime_behaviour(rule: BehaviorRule) -> bool:
    """Whether a compiled rule says its owner *does* something in a fight."""
    return not isinstance(rule.payload, STAT_CHANNEL_PAYLOADS)


def rule_owners() -> frozenset[str]:
    """Every owner a rule can be compiled for — items and declared runes."""
    return registry_owners() | frozenset(RUNE_AMP_SLOTS)


def entry_families(
    registry: ValueRegistry,
    family: RuleFamily,
    entry: Mapping[str, Any],
    owner: str,
) -> tuple[RuleFamily, ...]:
    """Every family one entry declares: its tag's, plus any a value key adds.

    The primary family comes first, so a compiler ladder's order is the
    entry's order.  The signature key is looked for in the entry's **schema**
    and never in what the parse produced: read live, a dropped key would
    silently un-declare the mechanic instead of raising with item and key.
    """
    keys = _schema_keys(owner, registry, entry)
    extra = tuple(
        declared
        for key, declared in SECONDARY_KEY_FAMILY[registry].items()
        if key in keys and declared is not family
    )
    return (family, *dict.fromkeys(extra))


def declared_tags() -> frozenset[str]:
    """Every ``ITEM_EFFECTS`` tag some entry declares a rule for.

    Behaviour declared here is not dispatched by ``item_effects``'
    effect-type ladder, so a totality check reading only that ladder would
    report a tag as undispatched.  Derived from what compiles, never listed.
    """
    return frozenset(
        str(entry.get("type"))
        for owner in registry_owners()
        for registry, family, entry in registry_entries(owner)
        if registry == "ITEM_EFFECTS"
        and _COMPILERS[family](family, owner, registry, entry)
    )


def registry_owners() -> frozenset[str]:
    """Every owner either number registry holds an entry for."""
    return frozenset(item_effects.ITEM_EFFECTS) | frozenset(
        item_effects.ALLY_ITEM_EFFECTS
    )


def declared_owners() -> frozenset[str]:
    """Registry owners that compile to at least one rule."""
    return frozenset(owner for owner in registry_owners() if behavior_rules(owner))


def undeclared_owners() -> frozenset[str]:
    """Registry owners whose behaviour is still engine code, not a declaration."""
    return registry_owners() - declared_owners()


def undeclared_entry_count() -> int:
    """Counter 3's value: undeclared **entries**, not owners."""
    return sum(len(registry_entries(owner)) for owner in sorted(undeclared_owners()))


def build_context(
    owner: str,
    level: int,
    *,
    fight_duration_seconds: float,
    target_bonus_health: float,
    holder_is_melee: bool,
) -> BuildContext:
    """The build-time context an interpreter reads, stamped with the data version.

    ``data_registry.data_version()`` is read here rather than by each
    interpreter, so every memo downstream keys on one counter.  The three
    fight facts are keyword-only and required: a caller that forgets one gets
    a ``TypeError``, never a defaulted zero duration flattening a ramping
    magnitude or a defaulted range class paying every holder the ranged rate.
    """
    return BuildContext(
        level=level,
        owner=owner,
        data_version=data_registry.data_version(),
        fight_duration_seconds=fight_duration_seconds,
        target_bonus_health=target_bonus_health,
        holder_is_melee=holder_is_melee,
    )


# ── closure ───────────────────────────────────────────────────────────────


def _validate_tag_closure(tags: frozenset[str] | None = None) -> None:
    """``TAG_FAMILY`` is total and single-valued over the registry's tags.

    ``tags`` is the seam the closure's own negative test drives (R-05): a
    gate that cannot be made to fail on demand is indistinguishable from a
    gate that passes.
    """
    known = frozenset(item_effects.known_effect_types()) if tags is None else tags
    mapped = frozenset(TAG_FAMILY)
    if mapped != known:
        missing = sorted(known - mapped)
        extra = sorted(mapped - known)
        raise BehaviorCatalogError(
            "TAG_FAMILY must be total over item_effects' effect tags; "
            f"unmapped={missing} unknown={extra}"
        )
    for tag, family in TAG_FAMILY.items():
        if not isinstance(family, RuleFamily):
            raise BehaviorCatalogError(f"TAG_FAMILY[{tag!r}] is not a RuleFamily")


def _validate_h4_closure() -> None:
    """The ten undispatched tags are declared, split four/six, and reasoned."""
    if len(H4_DEAD_TAGS) != 4 or len(H4_SELF_REFERENTIAL_TAGS) != 6:
        raise BehaviorCatalogError(
            "H4 is a four/six split: four dead tags and six self-referential "
            "ones. Changing the membership is the human's decision, not a "
            "consequence of an edit here"
        )
    ten = H4_DEAD_TAGS | H4_SELF_REFERENTIAL_TAGS
    if H4_DEAD_TAGS & H4_SELF_REFERENTIAL_TAGS:
        raise BehaviorCatalogError("a tag cannot be both dead and self-referential")
    unknown = sorted(ten - frozenset(TAG_FAMILY))
    if unknown:
        raise BehaviorCatalogError(f"H4 names tags no registry declares: {unknown}")
    unreasoned = sorted(ten - frozenset(H4_TAG_REASONS))
    if unreasoned or frozenset(H4_TAG_REASONS) != ten:
        raise BehaviorCatalogError(
            "every H4 tag carries an explicit reason for the family it "
            f"fails closed into; missing={unreasoned}"
        )


def _validate_action_kind_closure(kinds: frozenset[Any] | None = None) -> None:
    """``ACTION_KIND_FAMILY`` is total over ``ActionKind`` (seam: R-05)."""
    mapped = frozenset(ACTION_KIND_FAMILY)
    declared = frozenset(ActionKind) if kinds is None else kinds
    if mapped != declared:
        raise BehaviorCatalogError(
            "ACTION_KIND_FAMILY must be total over ActionKind; unmapped="
            f"{sorted(str(getattr(kind, 'value', kind)) for kind in declared - mapped)}"
        )


def _validate_defense_source_closure(
    mechanics: frozenset[DefenseMechanic] | None = None,
) -> None:
    """Every defensive mechanic has a family (seam: R-05).

    The population is :class:`~.item_behavior.DefenseMechanic` itself, so a
    new defence fails *collection* until somebody decides which family models
    it.  A closed enum rather than another module's text.
    """
    declared = frozenset(DefenseMechanic) if mechanics is None else mechanics
    mapped = frozenset(DEFENSE_SOURCE_FAMILY)
    if mapped != declared:
        raise BehaviorCatalogError(
            "DEFENSE_SOURCE_FAMILY must name every DefenseMechanic; unmapped="
            f"{sorted(str(getattr(m, 'value', m)) for m in declared - mapped)} "
            f"stale={sorted(str(getattr(m, 'value', m)) for m in mapped - declared)}"
        )


def _validate_event_certification(
    certified: Mapping[DefenseMechanic, str] | None = None,
) -> None:
    """Every certification names a known mechanic *and* says why (seam: R-05).

    Two clauses.  The first is structural: the certification is a property
    *of* a declared defence, so a member no declaration and no citation names
    would be a refusal filed against nothing.  The second is the one that can
    go red on demand and the one worth having — a mechanic certified with no
    stated reason withholds a whole calculation on the strength of a blank
    string, which is the unexplained refusal this campaign removes rather than
    a new one it adds.
    """
    claimed = EVENT_CERTIFIED_MECHANICS if certified is None else certified
    known = frozenset(DEFENSE_DECLARATIONS) | frozenset(UNDECLARED_DEFENSE_MECHANICS)
    unknown = sorted(
        str(getattr(mechanic, "value", mechanic))
        for mechanic in frozenset(claimed) - known
    )
    if unknown:
        raise BehaviorCatalogError(
            "every event-certified mechanic is one this catalog declares or "
            f"cites; unknown={unknown}"
        )
    unexplained = sorted(
        str(getattr(mechanic, "value", mechanic))
        for mechanic, reason in claimed.items()
        if not str(reason).strip()
    )
    if unexplained:
        raise BehaviorCatalogError(
            "an event-certified mechanic withholds a calculation, so each one "
            f"states why its timing cannot be inferred; unexplained={unexplained}"
        )


def _validate_defense_migration() -> None:
    """Every defence is declared here or owned by a champion.

    Three clauses, because a defence can go missing in three ways: a mechanic
    with no declaration, a declaration whose family is not the
    one :data:`DEFENSE_SOURCE_FAMILY` rules it into, and a registry entry
    whose tag says *defence* while no mechanic claims a single one of its
    keys — the last being the shape that would let an item silently stop
    defending after a parser rename.
    """
    declared = frozenset(DEFENSE_DECLARATIONS)
    covered = declared | frozenset(UNDECLARED_DEFENSE_MECHANICS)
    unnamed = sorted(
        mechanic.value for mechanic in frozenset(DefenseMechanic) - covered
    )
    if unnamed:
        raise BehaviorCatalogError(
            "every DefenseMechanic is either declared with the entry shape "
            "that carries it or owned by a champion; unshaped="
            f"{unnamed}"
        )
    for mechanic, declaration in DEFENSE_DECLARATIONS.items():
        if not declaration.shape.requires:
            raise BehaviorCatalogError(
                f"{mechanic.value} declares no signature key, so no entry "
                "could ever carry it"
            )
        for field in declaration.writes:
            if field not in DEFENSE_FIELD_COMBINE:
                raise BehaviorCatalogError(
                    f"{mechanic.value} writes {field} with no declared combine"
                )
    _validate_defense_entry_closure()


def _validate_defense_entry_closure() -> None:
    """Every defence-tagged registry entry is claimed by at least one mechanic."""
    defence_families = frozenset(
        {
            RuleFamily.OPENING_DEFENSE,
            RuleFamily.THRESHOLD_DEFENSE,
            RuleFamily.COMBAT_STATE,
            RuleFamily.REACTIVE,
        }
    )
    unclaimed: list[str] = []
    for owner, entry in item_effects.ITEM_EFFECTS.items():
        if not isinstance(entry, Mapping):
            continue
        family = TAG_FAMILY.get(str(entry.get("type")))
        if family not in defence_families:
            continue
        claimed = any(
            declaration.shape.claims(entry)
            for declaration in DEFENSE_DECLARATIONS.values()
        )
        if not claimed:
            unclaimed.append(owner)
    if unclaimed:
        raise BehaviorCatalogError(
            "every entry tagged as a defence must be claimed by one declared "
            f"mechanic's signature key; unclaimed={sorted(unclaimed)}"
        )


def _validate_defense_receipts() -> None:
    """Every declared defence resolves a citation, or its owners carry one.

    The one mechanic with no declared constant is Annul, whose three items
    are one mechanic with three revisions.  Rather than trusting that, this
    walks the registry: a mechanic missing from :data:`DEFENSE_RECEIPTS`
    whose owner's entry carries no complete citation would be a declaration
    against an unsourced number, and ``receipt_for`` would raise at compile
    time on a build nobody happened to price.
    """
    for mechanic, declaration in DEFENSE_DECLARATIONS.items():
        if mechanic in DEFENSE_RECEIPTS:
            continue
        for owner, entry in item_effects.ITEM_EFFECTS.items():
            if not isinstance(entry, Mapping) or not declaration.shape.claims(entry):
                continue
            if CITATION_KEYS - frozenset(entry):
                raise BehaviorCatalogError(
                    f"{mechanic.value} declares no constant receipt and "
                    f"ITEM_EFFECTS[{owner!r}] carries no complete citation of "
                    "its own, so the rule would be declared against an "
                    "unsourced number"
                )


def _validate_compilers() -> None:
    """One compiler per family, and every stub names the slice that retires it."""
    families = frozenset(RuleFamily)
    if len(families) != RULE_FAMILY_COUNT:
        raise BehaviorCatalogError(
            f"RuleFamily is closed at {RULE_FAMILY_COUNT}; it now has "
            f"{len(families)} members"
        )
    if frozenset(_COMPILERS) != families:
        raise BehaviorCatalogError(
            "_COMPILERS must be total over RuleFamily; unmapped="
            f"{sorted(family.value for family in families - frozenset(_COMPILERS))}"
        )


def _validate_delta_amp_migration() -> None:
    """Every delta-amp tag is either compiled here or named with its slice.

    The record of what a partly migrated family still refuses, closed: the
    two sets partition the family's tags exactly.
    """
    declared = frozenset(
        tag for tag, family in TAG_FAMILY.items() if family is RuleFamily.DELTA_AMP
    )
    named = MIGRATED_DELTA_AMP_TAGS | frozenset(DELTA_AMP_UNMIGRATED_TAGS)
    if MIGRATED_DELTA_AMP_TAGS & frozenset(DELTA_AMP_UNMIGRATED_TAGS):
        raise BehaviorCatalogError(
            "a delta-amp tag cannot be both migrated and awaiting a slice"
        )
    if named != declared:
        raise BehaviorCatalogError(
            "every delta_amp tag is either migrated or carries the slice that "
            f"retires it; unnamed={sorted(declared - named)} "
            f"stale={sorted(named - declared)}"
        )


def _validate_target_health_gate_closure() -> None:
    """Exactly the runes in the gated slot declare which side they arm on.

    Structural, so it runs at import beside the other closures: a rune added
    to the slot with no declared direction, or a direction left behind by a
    rune that moved out of it, both stop collection here rather than at the
    first fight that selects one.
    """
    gated = frozenset(
        owner
        for owner, slot in RUNE_AMP_SLOTS.items()
        if slot is AmpChainSlot.TARGET_HEALTH_GATE
    )
    declared = frozenset(TARGET_HEALTH_GATE_DIRECTIONS)
    if gated != declared:
        raise BehaviorCatalogError(
            "every target-health-gated rune declares which side it arms on; "
            f"undeclared={sorted(gated - declared)} "
            f"stale={sorted(declared - gated)}"
        )


def _validate_ally_packet_migration() -> None:
    """Every producer is declared, so none can be silently dropped."""
    declared = frozenset(AllyProducer)
    migrated = frozenset(ALLY_PACKET_DECLARATIONS)
    if migrated != declared:
        raise BehaviorCatalogError(
            "every AllyProducer is declared; "
            f"undeclared={sorted(p.value for p in declared - migrated)}"
        )
    if frozenset(ALLY_ENTRY_SHAPES) != declared:
        raise BehaviorCatalogError(
            "every AllyProducer declares the entry shape that carries it; "
            f"unshaped={sorted(p.value for p in declared - frozenset(ALLY_ENTRY_SHAPES))}"
        )


def _validate_ally_entry_closure() -> None:
    """Every ally-registry record is claimed by a producer, and vice versa.

    Both directions, because both failures are real.  A record no producer
    claims is a mechanic that would silently emit nothing once the emitters
    stop naming items; a producer no record carries is a declaration against a
    missing registry entry, which is the stale-literal failure one layer up.
    """
    unclaimed = sorted(
        owner
        for owner, entry in item_effects.ALLY_ITEM_EFFECTS.items()
        if isinstance(entry, Mapping) and not producers_for("ALLY_ITEM_EFFECTS", entry)
    )
    if unclaimed:
        raise BehaviorCatalogError(
            "every ALLY_ITEM_EFFECTS record is an ally packet by construction "
            "and must match one producer's value keys; unclaimed="
            f"{unclaimed}"
        )
    carried = {
        producer
        for registry, records in (
            ("ITEM_EFFECTS", item_effects.ITEM_EFFECTS),
            ("ALLY_ITEM_EFFECTS", item_effects.ALLY_ITEM_EFFECTS),
        )
        for entry in records.values()
        if isinstance(entry, Mapping)
        for producer in producers_for(registry, entry)
    }
    orphans = sorted(producer.value for producer in frozenset(AllyProducer) - carried)
    if orphans:
        raise BehaviorCatalogError(
            f"these producers are declared and no registry record carries "
            f"them: {orphans}"
        )


def validate_catalog() -> None:
    """Every closure this catalog claims, checked at import.

    Structural only — it reads the registries' *keys* and one sibling
    module's source text, never ``data/`` and never a number.
    """
    _validate_tag_closure()
    _validate_h4_closure()
    _validate_action_kind_closure()
    _validate_defense_source_closure()
    _validate_event_certification()
    _validate_defense_migration()
    _validate_defense_receipts()
    _validate_compilers()
    _validate_delta_amp_migration()
    _validate_target_health_gate_closure()
    _validate_ally_packet_migration()
    _validate_ally_entry_closure()


validate_catalog()


__all__ = [
    "ACKNOWLEDGED_READING_DIVERGENCES",
    "ACTION_KIND_FAMILY",
    "ALLY_DELTA_AMP_KEYS",
    "ALLY_DELTA_AMP_SLOTS",
    "ALLY_ENTRY_SHAPES",
    "ALLY_PACKET_DECLARATIONS",
    "AMP_COMPILABILITY",
    "ASSUMED_CARVE_LEADING_ABILITY_HITS",
    "CACHED_HEALTH_GATE_WORDS",
    "CACHED_ITEM_SOURCE",
    "CACHED_RUNE_SOURCE",
    "CITATION_KEYS",
    "COMBAT_START",
    "COMPILED_KERNEL_CANNOT_AMP",
    "COMPILED_KERNEL_CANNOT_STAGE",
    "COMPILED_KERNEL_CAN_AMP",
    "COMPILED_SUPPORT_KINDS",
    "DEFENSE_DECLARATIONS",
    "DEFENSE_RECEIPTS",
    "DEFENSE_SOURCE_FAMILY",
    "DELTA_AMP_UNMIGRATED_TAGS",
    "EVENT_CERTIFIED_MECHANICS",
    "H4_DEAD_TAGS",
    "H4_SELF_REFERENTIAL_TAGS",
    "H4_TAG_REASONS",
    "MIGRATED_DELTA_AMP_TAGS",
    "MULTIPLIER_ORIGIN",
    "NO_LEADING_STACKS",
    "ON_HIT_FORMULA_FLOORS",
    "ON_HIT_FORMULA_TERMS",
    "PER_ABILITY_HIT_BEHAVIOR",
    "RUNE_AMP_SLOTS",
    "TAG_FAMILY",
    "TARGET_HEALTH_GATE_DIRECTIONS",
    "UNDECLARED_DEFENSE_MECHANICS",
    "AllyPacketDeclaration",
    "BehaviorCatalogError",
    "Compiler",
    "DefenseDeclaration",
    "DefenseShape",
    "EntryShape",
    "TermSchema",
    "behavior_rules",
    "build_context",
    "cached_source_receipt",
    "declared_owners",
    "declared_tags",
    "declares_runtime_behaviour",
    "defense_mechanics_for",
    "entry_families",
    "owners_for",
    "producers_for",
    "registry_entries",
    "registry_owners",
    "rule_owners",
    "rune_amp_entries",
    "undeclared_entry_count",
    "undeclared_owners",
    "validate_catalog",
]
