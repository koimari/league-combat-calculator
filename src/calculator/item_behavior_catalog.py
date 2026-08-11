"""Shapes, not numbers: the tag→family map and the per-family compilers.

``item_effects`` owns every number and this module owns every *shape*.  It
holds no float: it says which family each registry tag belongs to, which
family each survival transition and each defensive source belongs to, and
which compiler turns one registry entry into frozen
:class:`~.item_behavior.BehaviorRule` declarations.  Rules are compiled fresh
from the live registries on every call, so a ``refresh_item_effects()`` moves
the declarations too — a catalog that cached its rules would be the stale
literal one layer up.

It is modelled on ``rune_effects._KEYSTONE_COMPILERS`` + ``resolve_keystone``
— the one existing compile-fresh, fail-closed registry in the repository —
rather than inventing a second idiom for the same job.

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

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Callable, NamedTuple
from urllib.parse import quote

from . import data_registry, item_effects, rune_effects
from .ability_spec import AttackClass, DamageClass, Disposition
from .item_behavior import (
    AbsoluteWindow,
    ActiveCastRule,
    AfterTrigger,
    AllyPacketRule,
    AllyProducer,
    Always,
    AmpChainSlot,
    AtLeast,
    AttackCooldownRefundRule,
    Attribution,
    Basis,
    Compilability,
    Compilable,
    Comparison,
    BonusTyping,
    BehaviorRule,
    BuildContext,
    ChargedSplash,
    CombatStateRule,
    CooldownProcRule,
    CritDamageBonusRule,
    DamageDeferralRule,
    CritOccurrence,
    DamageFormula,
    DEFENSE_FIELD_COMBINE,
    DamageThreshold,
    DefenseExclusivity,
    DefenseField,
    DefenseMechanic,
    DefenseOption,
    DeltaAmpRule,
    ExcludeTrigger,
    ExecuteRule,
    Fixed,
    ForcedCritHeal,
    ForcedCritRule,
    ChainTargets,
    EmpoweredAutoBuffRule,
    EmpoweredHitRule,
    EnergizedCharge,
    Isolation,
    LevelSteppedRate,
    LivePredicate,
    Magnitude,
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
    PeriodicCadence,
    PeriodicRule,
    Persist,
    Persistence,
    Pool,
    PostMitigationHealRule,
    Probe,
    ProcTrigger,
    Recipients,
    RULE_FAMILY_COUNT,
    RampModel,
    RampPerSecond,
    RampPerStack,
    ReactiveRule,
    ReceiptOnly,
    ReceivedHealingRule,
    RegenerationRule,
    RepeatingStrikeRule,
    Resistance,
    ResistanceShredRule,
    ResourceDrainRule,
    RuleFamily,
    Scaling,
    SecondaryTargetRule,
    SelfShield,
    ShapedChargeRule,
    ShieldBypassRule,
    ShieldAbsorbs,
    SpellbladeRule,
    StackGate,
    StackRamp,
    Subject,
    SustainStat,
    SustainStatRule,
    Term,
    TargetBonusHealthScaled,
    TemporaryLethality,
    ThresholdDefenseRule,
    TimesMissingHealth,
    TimesValue,
    TriggerEvent,
    TriggerWindow,
    Typing,
    UltimateProcRule,
    WindowBoundary,
    WindowMerge,
    ZeroPolicy,
    chain_rank,
    validate_rule,
)
from .survival.actions import ActionKind
from .value_ref import (
    Const,
    LateLevelValueRef,
    DerivedValueRef,
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
        "dead: read nowhere in src/. Yun Tal Wildarrows' crit-gated attack "
        "speed is a derived stat, so STAT_DERIVATION is where a rule for it "
        "would land the day one is written"
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
        "dead: read nowhere in src/. Frozen Heart's aura derives a stat on "
        "everyone in range"
    ),
    "defensive_start": (
        "was self-referential — read only by item_coverage's own claim while "
        "the behaviour was reached by item name in defensive_effects — until "
        "3.5 made it a real dispatch: every entry carrying it now compiles an "
        "OPENING_DEFENSE declaration. H4's decision on the tag stands"
    ),
    "stat_conversion": (
        "self-referential: read only by item_coverage's own claim, while the "
        "behaviour is reached by item name in stats. The mechanic derives one "
        "stat from another"
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

# Which slice retires each defence still resolved by name.  Both point at
# 3.7 because :data:`DEFENSE_SOURCE_FAMILY` puts them outside the four
# defence families: Death's Dance defers damage and Spirit Visage multiplies
# healing received, and a slice that declared them here would be doing
# another family's work under this one's zero-diff claim.
# Empty since 3.7 declared the last two: every DefenseMechanic the resolver
# builds now reaches a declaration, and the two that pointed outside the four
# defence families ride their own family's interpreter.  Kept rather than
# deleted because the *shape* is what keeps a future mechanic's refusal dated
# — an omission with no table to name it is the silence this phase removes.
DEFENSE_UNMIGRATED_MECHANICS: Mapping[DefenseMechanic, str] = {}


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


def cached_source_receipt(owner: str, stamp: str) -> SourceReceipt:
    """The cache-backed citation for an owner whose entry carries none."""
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
        """The keys that identify the mechanic — the first one unless stated.

        Armored Advance is the one mechanic that needs two: it carries the
        reactive shield *and* plates, and either key alone names a different
        mechanic on a different item.
        """
        return self.signature or self.requires[:1]

    def claims(self, entry: Mapping[str, Any]) -> bool:
        """Whether *entry* carries this mechanic, by its signature keys alone.

        The signature rather than the whole required set, so a *partly*
        parsed entry is a stop rather than a mechanic that quietly stops
        matching: an entry missing one ramp end would otherwise read as "not
        this mechanic", which is the silent absence this phase exists to
        remove.
        """
        if any(key in entry for key in self.excludes):
            return False
        return all(key in entry for key in self.signature_keys)

    def missing(self, entry: Mapping[str, Any]) -> tuple[str, ...]:
        """The companion keys *entry* does not carry."""
        return tuple(key for key in self.requires if key not in entry)


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
            _REACTIVE_SHIELD_KEYS + ("basic_damage_multiplier",),
            signature=("reactive_shield_base", "basic_damage_multiplier"),
        ),
        writes=_REACTIVE_SHIELD_WRITES + (DefenseField.BASIC_DAMAGE_MULTIPLIER,),
        exclusivity=DefenseExclusivity.NONE,
        trigger=TriggerEvent.CHAMPION_DAMAGE,
        absorbs_key="reactive_shield_damage_type",
        reads=_REACTIVE_SHIELD_READS + ("basic_damage_multiplier",),
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
            )
            + _LIFELINE_POLICY_KEYS
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
            )
            + _LIFELINE_POLICY_KEYS
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
            )
            + _LIFELINE_POLICY_KEYS
        ),
        writes=_THRESHOLD_SHIELD_WRITES + (DefenseField.MAW_LIFELINE_OMNIVAMP_PERCENT,),
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
        shape=DefenseShape(("shield_max_mana_ratio",) + _LIFELINE_POLICY_KEYS),
        writes=_THRESHOLD_SHIELD_WRITES,
        exclusivity=DefenseExclusivity.LIFELINE,
        threshold_key="health_threshold",
        duration_key="duration",
        absorbs_key="damage_type",
        reads=("shield_max_mana_ratio",),
        zero_policy=_LIFELINE_ZERO,
    ),
    DefenseMechanic.LIFELINE_STERAK: DefenseDeclaration(
        shape=DefenseShape(("shield_bonus_health_ratio",) + _LIFELINE_POLICY_KEYS),
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
        reads=("heal_bonus_armor_ratio", "heal_bonus_mr_ratio"),
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
# refuses each.  Partial on purpose — absent means ``Compilable`` — and the
# membership is the kernel's own capability report
# (``survival/compile.COMPILED_WALK_UNREPRESENTABLE_ITEMS``) read at mechanic
# granularity rather than per item, which is D-43's whole argument: three of
# that set's sixteen reasons are conservatism notes about a different
# mechanic of the same item.
COMPILED_KERNEL_CANNOT_STAGE: Mapping[DefenseMechanic, ReceiptOnly] = {
    DefenseMechanic.ANNUL: ReceiptOnly(
        "the compiled score kernel cannot stage an Annul spell shield: "
        "consuming one needs the per-packet cast metadata the light score "
        "ledger does not carry"
    ),
    DefenseMechanic.REBIRTH: ReceiptOnly(
        "the compiled score kernel cannot stage a resurrection: Rebirth's "
        "candidates are authored inside the event walk, after the score "
        "ledger has been built"
    ),
    DefenseMechanic.STEADFAST: ReceiptOnly(
        "the compiled score kernel cannot stage a dynamic-resistance reprice: "
        "Steadfast's stacks are priced against baseline resistances the score "
        "ledger does not keep"
    ),
    DefenseMechanic.VOIDBORN_RESILIENCE: ReceiptOnly(
        "the compiled score kernel cannot stage a dynamic-resistance reprice: "
        "Voidborn Resilience multiplies baseline resistances the score ledger "
        "does not keep"
    ),
    DefenseMechanic.LIFELINE_MAW: ReceiptOnly(
        "the compiled score kernel cannot stage the Lifeline omnivamp state "
        "transition: the temporary stat is granted by an authored threshold "
        "event"
    ),
    DefenseMechanic.IGNORE_PAIN: ReceiptOnly(
        "the compiled score kernel cannot stage deferred damage: Ignore Pain's "
        "ticks and Defy's clearance are authored inside the event walk"
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


# ── the compiled-kernel refusal every amp carries (D-101) ─────────────────

# H5 is descoped by the umbrella, so no ``delta_amp`` rule is compilable and
# every amp holder falls back to the receipt walk with this reason printed.
# It is one constant because it is one fact about the kernel, not a per-item
# judgement — and a per-item copy is how sixteen conservatism notes ended up
# indistinguishable from sixteen representability facts.
COMPILED_KERNEL_CANNOT_AMP = ReceiptOnly(
    "the compiled score kernel cannot represent a timed, typed damage "
    "modifier: unrepresentable_template_receipt returns support_kind=<kind> "
    "for anything but shield/heal and add_support_templates raises on it "
    "(D-101; H5 descoped, so this is the standing answer)"
)


# ── compilers (D-52's ruled exception to "no callables in declarations") ──

Compiler = Callable[
    [RuleFamily, str, ValueRegistry, Mapping[str, Any]], tuple[BehaviorRule, ...]
]

# Which registry tags the delta-amp compiler below turns into declarations,
# and — for the rest — which slice retires each refusal.  ``_unmigrated``
# carries that promise for a whole family; a *partly* migrated family needs
# it per tag, or the family's disappearance from UNMIGRATED_FAMILIES would
# quietly retire promises nobody kept.
MIGRATED_DELTA_AMP_TAGS: frozenset[str] = frozenset(
    {"damage_amp", "hypershot_amp", "magic_true_crit"}
)

DELTA_AMP_UNMIGRATED_TAGS: Mapping[str, str] = {
    "ability_damage_amp": (
        "3.7 — Actualizer's ability amp is applied per ability and per proc "
        "inside the rotation, so it occupies no chain slot"
    ),
    "basic_damage_amp": (
        "3.7 — Hexoptics C44 amplifies each basic attack where it is priced, "
        "so it occupies no chain slot"
    ),
    "magic_damage_amp": (
        "3.7 — Abyssal Mask's magic amp is applied by _mitigate on the "
        "defender's side, so it occupies no chain slot"
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
    },
    "ALLY_ITEM_EFFECTS": {
        key: RuleFamily.DELTA_AMP for key in sorted(ALLY_DELTA_AMP_KEYS)
    },
    "RUNE_EFFECTS": {},
}

# Which keystones declare an amp-chain slot, and which slot.  A rune record
# carries no effect tag — the shape *is* the keystone — so this is the closed
# key set that makes the name dispatch total, exactly as
# ``rune_effects._KEYSTONE_COMPILERS`` is for the runes themselves.  Rule 5
# reaches keystones (D-46), so their numbers are references like any other.
KEYSTONE_AMPS: Mapping[str, AmpChainSlot] = {
    "First Strike": AmpChainSlot.OPENING_WINDOW,
    "Press the Attack": AmpChainSlot.LASTING_PROC_AMP,
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

    base: "str | tuple[str, str]"
    per_level: "str | tuple[str, str]"
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
CAST_PROC_TAGS: frozenset[str] = frozenset({"proc", "ult_proc", "max_hp_proc"})
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


def _mechanic_slug(owner: str) -> str:
    """An owner's identifier spelling, matching Phase 2's mechanic ids.

    Lower case, apostrophes dropped rather than transliterated, every other
    run of non-alphanumerics collapsed to one underscore — which is how
    ``trigger_stream`` already spells ``bloodletters_curse`` and
    ``deaths_dance``.  One spelling rule, so a mechanic id and a capability
    key cannot drift into two names for one mechanic.
    """
    stripped = owner.replace("'", "").replace("’", "")
    slug = "".join(char if char.isalnum() else "_" for char in stripped.lower())
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_")


def _all_damage_typing() -> Typing:
    """Every damage class from every attack class — "from all sources", said.

    D-04 bans empty-means-all, so an amp that really does apply to
    everything has to enumerate everything.  This is that enumeration, in one
    place, so "all" cannot drift into "all the ones somebody remembered".
    """
    return Typing(
        damage_classes=frozenset(DamageClass),
        attack_classes=frozenset(AttackClass),
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
            attribution=Attribution.HOLDER,
            typing=_all_damage_typing(),
            bonus_typing=BonusTyping.SAME_AS_SOURCE,
            subject=Subject.HOLDER,
            lane_chain_rank=chain_rank(AmpChainSlot.HYPERSHOT),
        ),
        compilability=COMPILED_KERNEL_CANNOT_AMP,
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
            attribution=Attribution.HOLDER,
            typing=_all_damage_typing(),
            bonus_typing=BonusTyping.SAME_AS_SOURCE,
            subject=Subject.HOLDER,
            lane_chain_rank=chain_rank(AmpChainSlot.WHOLE_TOTAL),
        ),
        compilability=COMPILED_KERNEL_CANNOT_AMP,
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
            attribution=Attribution.HOLDER,
            typing=_all_damage_typing(),
            bonus_typing=BonusTyping.TRUE,
            subject=Subject.HOLDER,
            lane_chain_rank=chain_rank(AmpChainSlot.OPENING_WINDOW),
        ),
        compilability=COMPILED_KERNEL_CANNOT_AMP,
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
    into two readings of it.  The three facts that used to be an engine's
    loop shape are now what the declaration says:

    * ``TriggerWindow(IMMOBILIZE, …)`` — the trigger is an immobilize and
      nothing wider; the bus's ``CC`` stream is where that lands (D-08).
    * ``merge=EXTEND`` — a second immobilize *extends* the window rather than
      opening a second one or refreshing it (D-12).  Repeat-Command stacking
      shipped as a Phase 0 sentinel and becomes this policy here.
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
                merge=WindowMerge.EXTEND,
                boundary=WindowBoundary.OPEN_CLOSED,
            ),
            consumption=Persist(),
            magnitude=Fixed(ValueRef(registry, owner, "command_damage_amp")),
            attribution=Attribution.HOLDER,
            typing=_all_damage_typing(),
            bonus_typing=BonusTyping.SAME_AS_SOURCE,
            subject=Subject.ANY_ATTACKER,
            lane_chain_rank=chain_rank(AmpChainSlot.POST_IMMOBILIZE),
        ),
        compilability=COMPILED_KERNEL_CANNOT_AMP,
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
            attribution=Attribution.HOLDER,
            typing=_all_damage_typing(),
            bonus_typing=BonusTyping.SAME_AS_SOURCE,
            subject=Subject.ANY_ATTACKER,
            lane_chain_rank=chain_rank(AmpChainSlot.EXPOSE_WEAKNESS),
        ),
        compilability=COMPILED_KERNEL_CANNOT_AMP,
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
            attribution=Attribution.HOLDER,
            typing=_magic_and_true_typing(),
            bonus_typing=BonusTyping.SAME_AS_SOURCE,
            subject=Subject.HOLDER,
            lane_chain_rank=chain_rank(AmpChainSlot.CINDERBLOOM),
        ),
        compilability=COMPILED_KERNEL_CANNOT_AMP,
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

    Physical damage is excluded because the mechanic excludes it, and D-04
    makes that a thing the declaration says rather than a tuple membership
    test inside the ledger walk.
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
    :data:`KEYSTONE_AMPS` is for runes, and for the same reason: the record
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

    True damage is excluded because the mechanic excludes it, and D-04 makes
    that a thing the declaration says rather than a comparison buried in a
    ledger filter.
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
            attribution=Attribution.HOLDER,
            typing=_non_true_typing(),
            bonus_typing=BonusTyping.SAME_AS_SOURCE,
            subject=Subject.HOLDER,
            lane_chain_rank=chain_rank(AmpChainSlot.LASTING_PROC_AMP),
        ),
        compilability=COMPILED_KERNEL_CANNOT_AMP,
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


def _compile_keystone_amp(owner: str) -> tuple[BehaviorRule, ...]:
    """The amp-chain slots one compiled keystone declares.

    Dispatch is on the keystone's name because a rune record has no effect
    tag to dispatch on — the shape *is* the keystone.  That is
    ``rune_effects._KEYSTONE_COMPILERS``' own idiom, and :data:`KEYSTONE_AMPS`
    is the closed key set that makes it total.
    """
    slot = KEYSTONE_AMPS[owner]
    if slot is AmpChainSlot.OPENING_WINDOW:
        return (_opening_window_rule(owner, "RUNE_EFFECTS"),)
    if slot is AmpChainSlot.LASTING_PROC_AMP:
        return (_lasting_proc_amp_rule(owner, "RUNE_EFFECTS"),)
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
        rules.extend(_compile_keystone_amp(owner))
    elif registry == "ALLY_ITEM_EFFECTS":
        rules.extend(_compile_ally_delta_amp(owner, registry, entry))
    else:
        tag = str(entry.get("type"))
        if tag == "hypershot_amp":
            rules.append(_hypershot_rule(owner, registry))
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
    owner: str, registry: ValueRegistry, keys: "str | tuple[str, str]"
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
    """Which keys *owner*'s entry is expected to carry, not which it has.

    The item registry publishes a schema — the shape of the last-known-good
    entry — and reading it rather than the live entry is what keeps a dropped
    parse a stop instead of a declaration silently concluding the mechanic
    does not exist.  The ally registry is hand-authored and refresh-inert
    (D-47), so its entry *is* its schema.
    """
    if registry == "ITEM_EFFECTS":
        return item_effects.entry_schema_keys(owner)
    return frozenset(entry)


def _optional_ref(
    owner: str, registry: ValueRegistry, entry: Mapping[str, Any], key: str
) -> ValueRef | None:
    """A reference to *key*, or ``None`` where the schema does not carry it.

    The declared-absence idiom: a mechanic that has no such sibling declares
    ``None``, which is a different claim from a reference that resolves to
    zero.  The registry's schema is the test, so no item name decides it and
    a parse that dropped the key still raises rather than being read as an
    absence.
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

    The same whole-or-nothing rule the spellblade siblings use: any key of the
    group in the registry's schema makes every key required, so a parse that
    dropped one raises naming item and key rather than compiling a mechanic
    with a hole in it.
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
        compilability=Compilable(),
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


def _compile_charged_strike(
    family: RuleFamily,
    owner: str,
    registry: ValueRegistry,
    entry: Mapping[str, Any],
) -> tuple[BehaviorRule, ...]:
    """Compile the charged strike one registry entry declares.

    Four tags, four shapes: a hit that spends a charge, a hit that lands every
    Nth application, a charge an ability arms, and an ultimate that empowers
    the holder's own attacks.  Dispatch is on the tag, so no item name decides
    a shape.
    """
    del family
    tag = str(entry.get("type"))
    rule = _CHARGED_STRIKE_RULES[tag](owner, registry, entry)
    validate_rule(rule)
    return (rule,)


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
    "Magic ability" is the rule's ``typing`` — the damage class that applies a
    stack and the attack class that delivers it — which is where a comparison
    inside the rotation loop used to live.
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

    The trigger is the basic attack, declared rather than implied by the
    accumulator the refund used to be summed into.  It changes a cooldown and
    not a damage number, which is why it is its own payload inside the family
    the registry files it under.
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
        compilability=Compilable(),
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
                subject=Subject.HOLDER,
            ),
        )
        for key, stat in SUSTAIN_STAT_KEYS.items()
        if key in schema
    ]


def _compile_sustain(
    family: RuleFamily,
    owner: str,
    registry: ValueRegistry,
    entry: Mapping[str, Any],
) -> tuple[BehaviorRule, ...]:
    """Compile every sustain mechanic one registry entry declares.

    A fan-out rather than a ladder: an entry may grant a stat *and* carry a
    named mechanic, and Doran's Blade does exactly that — its retired
    omnivamp correction and its Life Draining heal are two declarations on
    one entry.  An entry tagged into the family carrying no signature key is
    a stop.
    """
    schema = _schema_keys(owner, registry, entry)
    rules = _sustain_rule_list(owner, registry, schema)
    rules.extend(_compile_defense(family, owner, registry, entry))
    if not rules:
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

COMPILED_KERNEL_CANNOT_REDIRECT = ReceiptOnly(
    "the compiled score kernel cannot represent a producer that re-routes "
    "another participant's incoming damage: the redirect is stamped on the "
    "victim's own events by the receipt scheduler, which the score ledger "
    "does not run (survival/compile.COMPILED_WALK_UNREPRESENTABLE_ITEMS "
    "records the same fact per item)"
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
    """

    trigger: PacketTrigger
    packets: tuple[PacketSpec, ...]
    secondary_target: Recipients | None
    persistence: Persistence
    redirects_incoming_damage: bool
    reads: tuple[str, ...]
    ramps: tuple[tuple[str, str], ...]
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
            "target_area_reveal_duration",
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


# One entry per migrated producer.  Each slice of 3.6 moves a producer group
# from ``ALLY_PACKET_UNMIGRATED_PRODUCERS`` to here together with its emitter,
# so a declaration never lands without the code that reads it.
ALLY_PACKET_DECLARATIONS: Mapping[AllyProducer, AllyPacketDeclaration] = {
    AllyProducer.EVERLASTING: AllyPacketDeclaration(
        trigger=PacketTrigger.CROWD_CONTROL,
        packets=(PacketSpec(PacketKind.SHIELD, Recipients.SELF),),
        secondary_target=None,
        persistence=Persistence.TIMED_WINDOW,
        redirects_incoming_damage=False,
        reads=(
            "everlasting_mana_threshold_ratio",
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
        ramps=(("charge_cap_min", "charge_cap_max"),),
        zero_reason=(
            "the heal is the stored charge pool, a sourced share of the "
            "authored damage capped by a sourced level ramp; a zero means the "
            "ledger carried no damage to charge from"
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
        ramps=(("temporary_health_min", "temporary_health_max"),),
        zero_reason=(
            "the temporary health is a sourced level ramp read at the "
            "recipient's own level; a zero means no authored control landed"
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
        ramps=(("blue_reduction_min", "blue_reduction_max"),),
        zero_reason=(
            "the reduction is a sourced level ramp read at the shielded ally's "
            "own level; a zero means the holder healed or shielded nobody"
        ),
    ),
    AllyProducer.PURPLE_BUBBLE: AllyPacketDeclaration(
        trigger=PacketTrigger.ALLY_HEAL_OR_SHIELD,
        packets=(PacketSpec(PacketKind.ON_HIT_MAGIC, Recipients.TRIGGERING_ALLY),),
        secondary_target=None,
        persistence=Persistence.TIMED_WINDOW,
        redirects_incoming_damage=False,
        reads=("dream_duration",),
        ramps=(("purple_magic_min", "purple_magic_max"),),
        zero_reason=(
            "the on-hit bonus is a sourced level ramp read at the buffed ally's "
            "own level; a zero means the holder healed or shielded nobody"
        ),
    ),
    AllyProducer.DEVOTION: AllyPacketDeclaration(
        trigger=PacketTrigger.ITEM_ACTIVE,
        packets=(PacketSpec(PacketKind.SHIELD, Recipients.HOLDER_AND_ALLIES),),
        secondary_target=None,
        persistence=Persistence.TIMED_WINDOW,
        redirects_incoming_damage=False,
        reads=("shield_duration",),
        ramps=(("shield_min", "shield_max"),),
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
        ramps=(("heal_min", "heal_max"),),
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
        ramps=(("heal_min", "heal_max"),),
        zero_reason=(
            "the heal is a sourced level ramp and the beam a sourced share of "
            "each enemy's maximum health; a zero means the scenario cast no "
            "active"
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


# Which slice of 3.6 retires each producer's stub, in the idiom
# :data:`DELTA_AMP_UNMIGRATED_TAGS` uses for the other partly-migrated family:
# a family whose compiler is real no longer appears in
# :data:`UNMIGRATED_FAMILIES`, so without this the promises would disappear
# with the stub rather than being kept.
ALLY_PACKET_UNMIGRATED_PRODUCERS: Mapping[AllyProducer, str] = {}


def _ally_compilability(declaration: AllyPacketDeclaration) -> Compilability:
    """Whether the compiled score kernel can stage this producer's packets.

    Derived from three declared axes rather than judged per item, because a
    per-item judgement is exactly how sixteen conservatism notes ended up
    indistinguishable from sixteen representability facts (D-43).  Each
    refusal names the kernel clause that produces it.
    """
    if declaration.redirects_incoming_damage:
        return COMPILED_KERNEL_CANNOT_REDIRECT
    unstageable = sorted(
        spec.kind.value
        for spec in declaration.packets
        if spec.kind not in COMPILED_SUPPORT_KINDS
    )
    if unstageable:
        return ReceiptOnly(
            "the compiled score kernel stages only shield and heal support "
            "templates: unrepresentable_template_receipt returns "
            f"support_kind=<kind> for {unstageable}"
        )
    if declaration.persistence is not Persistence.SINGLE_MOMENT:
        return ReceiptOnly(
            "the compiled score kernel stages only instantaneous support "
            "templates: unrepresentable_template_receipt returns "
            "support_duration=<d> for a shield or heal that stays in force"
        )
    return Compilable()


def _ally_packet_rule(
    producer: AllyProducer, owner: str, registry: ValueRegistry
) -> BehaviorRule:
    """One producer's declaration, bound to the owner whose entry carries it."""
    declaration = ALLY_PACKET_DECLARATIONS[producer]
    values: tuple[Any, ...] = tuple(
        ValueRef(registry, owner, key) for key in declaration.reads
    ) + tuple(
        LevelValueRef(registry, owner, minimum, maximum, "registry_start")
        for minimum, maximum in declaration.ramps
    )
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
    """Compile the cross-participant producers one registry entry declares.

    A producer whose emitter has not migrated yet compiles no rule and is
    named in :data:`ALLY_PACKET_UNMIGRATED_PRODUCERS` with the slice that
    retires it — the same refusal-with-a-date :func:`_unmigrated` gives a
    whole family, at the granularity a partly-migrated family needs.
    """
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

    An entry that declares none compiles none, and that is an *answer* — a
    Guardian Angel is tagged as a starting defence and its mechanic is a
    resurrection, so the opening-defence compiler is right to hand back
    nothing.  A mechanic whose family sits outside this slice is named in
    :data:`DEFENSE_UNMIGRATED_MECHANICS` with the slice that retires it, so
    the refusal carries a date as well as a reason.
    """
    return tuple(
        _defense_rule(mechanic, owner, registry)
        for mechanic in defense_mechanics_for(family, entry)
        if mechanic not in DEFENSE_UNMIGRATED_MECHANICS
        and _defense_flag_holds(mechanic, entry)
    )


def _defense_flag_holds(mechanic: DefenseMechanic, entry: Mapping[str, Any]) -> bool:
    """Whether the entry's own flags say this mechanic is live at the opening.

    One member today, and it is a real rule rather than a convenience: a
    spell shield the registry says is not ready compiles no declaration at
    all, which is the fail-closed reading the retired name ladder spelled as
    ``.get("spell_shield_ready", False)``.
    """
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


def _unmigrated(
    family: RuleFamily,
    owner: str,
    registry: ValueRegistry,
    entry: Mapping[str, Any],
) -> tuple[BehaviorRule, ...]:
    """No rule yet: this family's behaviour still lives as engine code.

    Returning no rules is *not* a silent zero.  Every owner this compiler
    declines is named by :func:`undeclared_owners` and counted by the
    behaviour frontier's counter 3, and :func:`compilability_for`'s fold in
    ``interpreters`` refuses to call such an owner compilable.  The slice
    that replaces each entry of :data:`_COMPILERS` is named in
    :data:`UNMIGRATED_FAMILIES`, so the refusal carries a date as well as a
    reason.
    """
    del family, owner, registry, entry
    return ()


# One module-level ``def`` per key, keyed by a closed enum, totality asserted
# — D-52's three conditions, which is what makes a callable registry a ruled
# exception rather than a hole in "no callables in declarations".  Every
# entry points at ``_unmigrated`` today; each migration slice replaces
# exactly one, which is what keeps a slice's diff a one-symbol change.
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
    RuleFamily.STAT_DERIVATION: _unmigrated,
    RuleFamily.ALLY_PACKET: _compile_ally_packet,
}

# Which numbered slice of this phase replaces each family's stub compiler.
UNMIGRATED_FAMILIES: Mapping[RuleFamily, str] = {
    RuleFamily.STAT_DERIVATION: "3.7",
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


def behavior_rules(owner: str) -> tuple[BehaviorRule, ...]:
    """Compile *owner*'s declarations fresh from the live registries.

    An owner with no registry entry has no rules and that is an *answer*:
    the item declares no behaviour at all, which is the stats-only case.  An
    owner **with** an entry whose family is not yet migrated also returns no
    rules, and that is a *refusal* — a different thing with the same shape,
    which is why :func:`undeclared_owners` names it and the frontier counts
    it.  Never memoized: ``refresh_item_effects()`` must move the answer.
    """
    rules: list[BehaviorRule] = []
    for registry, family, entry in registry_entries(owner) + keystone_entries(owner):
        for claimed in entry_families(registry, family, entry):
            rules.extend(_COMPILERS[claimed](claimed, owner, registry, entry))
    return tuple(rules)


def keystone_entries(owner: str) -> tuple[tuple[ValueRegistry, RuleFamily, Any], ...]:
    """The rune record *owner* declares an amp-chain slot from, if any.

    Deliberately not part of :func:`registry_entries`: counter 3's population
    is the two **item** registries, and folding runes into it would silently
    change what the frontier's headline number counts.  Keystones are still
    bound by rule 5 — their numbers are references — they are simply not
    entries of the registries that counter measures.
    """
    if owner not in KEYSTONE_AMPS:
        return ()
    entry = rune_effects.RUNE_EFFECTS.get(owner)
    if not isinstance(entry, Mapping):
        raise BehaviorCatalogError(
            f"{owner!r} declares an amp-chain slot and RUNE_EFFECTS holds no "
            "record for it — a declaration against a missing rune is a stop, "
            "not a keystone that quietly amplifies nothing"
        )
    return (("RUNE_EFFECTS", RuleFamily.DELTA_AMP, entry),)


def rule_owners() -> frozenset[str]:
    """Every owner a rule can be compiled for — items and declared keystones."""
    return registry_owners() | frozenset(KEYSTONE_AMPS)


def entry_families(
    registry: ValueRegistry, family: RuleFamily, entry: Mapping[str, Any]
) -> tuple[RuleFamily, ...]:
    """Every family one entry declares: its tag's, plus any a value key adds.

    The primary family always comes first, so a compiler ladder's order is
    the entry's order.  A secondary family is not a second *entry* — counter
    3's population is unchanged — it is a second mechanic hung on one entry,
    which is a thing the registry really does and a thing a tag alone cannot
    express.
    """
    extra = tuple(
        declared
        for key, declared in SECONDARY_KEY_FAMILY[registry].items()
        if key in entry and declared is not family
    )
    return (family, *dict.fromkeys(extra))


def declared_tags() -> frozenset[str]:
    """Every ``ITEM_EFFECTS`` tag some entry now declares a rule for.

    The migration's answer to "which tags does a live handler branch on".
    Behaviour that has moved into a declaration is no longer dispatched by
    ``item_effects``' effect-type ladder, so a totality check reading only
    that ladder would report a tag as *undispatched* on the very commit that
    gave it a real home.  Derived from what actually compiles, never listed.
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
    """Registry owners whose behaviour is still engine code, not a declaration.

    Counter 3's population and ``item_coverage``'s ``review_pending`` read the
    same set, so the frontier's number and the public coverage answer cannot
    drift apart.
    """
    return registry_owners() - declared_owners()


def undeclared_entry_count() -> int:
    """Counter 3's value: undeclared **entries**, not owners.

    Six owners hold an entry in both registries, and each entry is a separate
    declaration obligation, so the count is over entries.
    """
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

    ``data_registry.data_version()`` (D-49) is read here rather than by each
    interpreter, so every memo downstream keys on one counter instead of on
    object identity.  The three fight facts are keyword-only and required: a
    caller that forgets one gets a ``TypeError``, never a defaulted zero
    duration silently flattening a ramping magnitude or a defaulted range
    class silently paying every holder the ranged rate.
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
    it.  The same closure used to be got by scraping the resolver's source
    for its hand-written provenance records; it is now over a closed enum
    rather than over another module's text.
    """
    declared = frozenset(DefenseMechanic) if mechanics is None else mechanics
    mapped = frozenset(DEFENSE_SOURCE_FAMILY)
    if mapped != declared:
        raise BehaviorCatalogError(
            "DEFENSE_SOURCE_FAMILY must name every DefenseMechanic; unmapped="
            f"{sorted(str(getattr(m, 'value', m)) for m in declared - mapped)} "
            f"stale={sorted(str(getattr(m, 'value', m)) for m in mapped - declared)}"
        )


def _validate_defense_migration() -> None:
    """Every defence is declared here or carries the slice that retires it.

    Three clauses, because a defence can go missing in three ways: a mechanic
    with no declaration and no promise, a declaration whose family is not the
    one :data:`DEFENSE_SOURCE_FAMILY` rules it into, and a registry entry
    whose tag says *defence* while no mechanic claims a single one of its
    keys — the last being the shape that would let an item silently stop
    defending after a parser rename.
    """
    declared = frozenset(DEFENSE_DECLARATIONS)
    promised = frozenset(DEFENSE_UNMIGRATED_MECHANICS)
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
    if promised - declared:
        raise BehaviorCatalogError(
            "a defence awaiting a slice still declares the entry shape it "
            "will be compiled from, so the promise names a real mechanic"
        )
    for mechanic, declaration in DEFENSE_DECLARATIONS.items():
        if not declaration.shape.requires:
            raise BehaviorCatalogError(
                f"{mechanic.value} declares no signature key, so no entry "
                "could ever carry it"
            )
        if mechanic in DEFENSE_UNMIGRATED_MECHANICS:
            continue
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
    stubbed = frozenset(
        family for family, compiler in _COMPILERS.items() if compiler is _unmigrated
    )
    if frozenset(UNMIGRATED_FAMILIES) != stubbed:
        raise BehaviorCatalogError(
            "UNMIGRATED_FAMILIES must name exactly the families whose compiler "
            "is still the stub, so a migrated family cannot keep a stale "
            "promise and a stub cannot exist without a slice that retires it"
        )


def _validate_delta_amp_migration() -> None:
    """Every delta-amp tag is either compiled here or named with its slice.

    A family whose compiler is real no longer appears in
    :data:`UNMIGRATED_FAMILIES`, so a partly migrated family would otherwise
    lose the record of what it still refuses.  This is that record, closed:
    the two sets partition the family's tags exactly.
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


def _validate_ally_packet_migration() -> None:
    """Every producer is compiled here or carries the commit that retires it.

    The same record :data:`DELTA_AMP_UNMIGRATED_TAGS` keeps for the other
    partly-migrated family, and closed the same way: the two tables partition
    :class:`~.item_behavior.AllyProducer` exactly, so a producer cannot be
    silently dropped and a kept promise cannot outlive the stub it described.
    """
    declared = frozenset(AllyProducer)
    migrated = frozenset(ALLY_PACKET_DECLARATIONS)
    promised = frozenset(ALLY_PACKET_UNMIGRATED_PRODUCERS)
    if migrated & promised:
        raise BehaviorCatalogError(
            "an ally-packet producer cannot be both migrated and awaiting a "
            f"commit: {sorted(p.value for p in migrated & promised)}"
        )
    if migrated | promised != declared:
        raise BehaviorCatalogError(
            "every AllyProducer is either migrated or carries the commit that "
            f"retires it; unnamed={sorted(p.value for p in declared - migrated - promised)}"
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
    registry entry that no longer exists, which is the stale-literal failure
    one layer up.
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
    _validate_defense_migration()
    _validate_defense_receipts()
    _validate_compilers()
    _validate_delta_amp_migration()
    _validate_ally_packet_migration()
    _validate_ally_entry_closure()


validate_catalog()


__all__ = [
    "ACTION_KIND_FAMILY",
    "ASSUMED_CARVE_LEADING_ABILITY_HITS",
    "ALLY_DELTA_AMP_KEYS",
    "ALLY_DELTA_AMP_SLOTS",
    "ALLY_ENTRY_SHAPES",
    "ALLY_PACKET_DECLARATIONS",
    "ALLY_PACKET_UNMIGRATED_PRODUCERS",
    "AllyPacketDeclaration",
    "CITATION_KEYS",
    "COMPILED_KERNEL_CANNOT_REDIRECT",
    "COMPILED_SUPPORT_KINDS",
    "EntryShape",
    "CACHED_ITEM_SOURCE",
    "CACHED_RUNE_SOURCE",
    "COMPILED_KERNEL_CANNOT_AMP",
    "BehaviorCatalogError",
    "Compiler",
    "COMPILED_KERNEL_CANNOT_STAGE",
    "DEFENSE_DECLARATIONS",
    "DEFENSE_RECEIPTS",
    "DEFENSE_SOURCE_FAMILY",
    "DEFENSE_UNMIGRATED_MECHANICS",
    "UNDECLARED_DEFENSE_MECHANICS",
    "DefenseDeclaration",
    "DefenseShape",
    "defense_mechanics_for",
    "DELTA_AMP_UNMIGRATED_TAGS",
    "COMBAT_START",
    "H4_DEAD_TAGS",
    "H4_SELF_REFERENTIAL_TAGS",
    "H4_TAG_REASONS",
    "KEYSTONE_AMPS",
    "MIGRATED_DELTA_AMP_TAGS",
    "MULTIPLIER_ORIGIN",
    "ON_HIT_FORMULA_FLOORS",
    "ON_HIT_FORMULA_TERMS",
    "NO_LEADING_STACKS",
    "PER_ABILITY_HIT_BEHAVIOR",
    "TAG_FAMILY",
    "TermSchema",
    "UNMIGRATED_FAMILIES",
    "behavior_rules",
    "build_context",
    "cached_source_receipt",
    "declared_owners",
    "declared_tags",
    "entry_families",
    "keystone_entries",
    "owners_for",
    "producers_for",
    "registry_entries",
    "registry_owners",
    "rule_owners",
    "undeclared_entry_count",
    "undeclared_owners",
    "validate_catalog",
]
