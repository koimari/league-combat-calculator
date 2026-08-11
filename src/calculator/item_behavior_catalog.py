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
``ActionKind`` or a new ``DefenseSource`` construction in
``defensive_effects.py`` fails *collection* until somebody decides which
family it belongs to.  That is the whole point of a closed union: the cost of
a new mechanic is one decision, taken deliberately, instead of a silent
default nobody notices.  The defensive-source set is read from
``defensive_effects.py``'s own source with ``ast`` rather than by importing
it, so the count is derived from the module's constructions and never typed
here, and this stays a light import.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
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
    Attribution,
    Basis,
    Compilability,
    Compilable,
    Comparison,
    BonusTyping,
    BehaviorRule,
    BuildContext,
    DamageFormula,
    DeltaAmpRule,
    ExcludeTrigger,
    Fixed,
    Isolation,
    LivePredicate,
    Magnitude,
    MeleeRangedSplit,
    NoFloor,
    OnHitStrikeRule,
    PacketKind,
    PacketSpec,
    PacketTrigger,
    Persist,
    Persistence,
    Pool,
    Probe,
    Recipients,
    RULE_FAMILY_COUNT,
    RampModel,
    RampPerSecond,
    RampPerStack,
    ReceiptOnly,
    Resistance,
    ResistanceShredRule,
    RuleFamily,
    SecondaryTargetRule,
    StackRamp,
    Subject,
    Term,
    TargetBonusHealthScaled,
    TriggerEvent,
    TriggerWindow,
    Typing,
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
        "dead: read nowhere in src/. Serpent's Fang changes how much shielding "
        "a strike must pass through on its way to health, which is a routing "
        "rule and not a defence the holder owns"
    ),
    "target_state": (
        "dead: read nowhere in src/. Force of Nature and Jak'Sho carry stack "
        "ledgers on the defender, which is COMBAT_STATE's shape"
    ),
    "target_attack_speed_aura": (
        "dead: read nowhere in src/. Frozen Heart's aura derives a stat on "
        "everyone in range"
    ),
    "defensive_start": (
        "self-referential: read only by item_coverage's own claim, while the "
        "behaviour is reached by item name in defensive_effects. The mechanic "
        "is a defence ready when the exchange opens"
    ),
    "stat_conversion": (
        "self-referential: read only by item_coverage's own claim, while the "
        "behaviour is reached by item name in stats. The mechanic derives one "
        "stat from another"
    ),
    "sustain": (
        "self-referential: read only by item_coverage's own claim, while the "
        "behaviour is reached by item name. The mechanic is sustain and the "
        "family it names is SUSTAIN"
    ),
    "target_mitigation": (
        "self-referential: read only by item_coverage's own claim, while the "
        "behaviour is reached by item name in defensive_effects. Plated "
        "Steelcaps-class mitigation is part of StartingDefenses"
    ),
    "target_threshold_health": (
        "self-referential: read only by item_coverage's own claim. A lifeline "
        "on a health threshold is THRESHOLD_DEFENSE"
    ),
    "target_threshold_shield": (
        "self-referential: read only by item_coverage's own claim. A lifeline "
        "granting a shield at a threshold is THRESHOLD_DEFENSE"
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


# ── DefenseSource label → family, total over the module's constructions ───

DEFENSE_SOURCE_FAMILY: Mapping[str, RuleFamily] = {
    "Galio — Shield of Durand": RuleFamily.OPENING_DEFENSE,
    "Kaenic Rookern — Magebane": RuleFamily.OPENING_DEFENSE,
    "Spirit Visage — Boundless Vitality": RuleFamily.SUSTAIN,
    "Plated Steelcaps — Plating": RuleFamily.OPENING_DEFENSE,
    "Warden's Mail — Rock Solid": RuleFamily.OPENING_DEFENSE,
    "Randuin's Omen — Resilience": RuleFamily.OPENING_DEFENSE,
    "Guardian Angel — Rebirth": RuleFamily.THRESHOLD_DEFENSE,
    "Death's Dance — Ignore Pain / Defy": RuleFamily.DAMAGE_ROUTING,
    "Force of Nature — Steadfast": RuleFamily.COMBAT_STATE,
    "Jak'Sho, The Protean — Voidborn Resilience": RuleFamily.COMBAT_STATE,
    "Zhonya's Hourglass / Seeker's Armguard — Time Stop": RuleFamily.COMBAT_STATE,
    "Immortal Shieldbow — Lifeline": RuleFamily.THRESHOLD_DEFENSE,
    "Hexdrinker — Lifeline": RuleFamily.THRESHOLD_DEFENSE,
    "Maw of Malmortius — Lifeline": RuleFamily.THRESHOLD_DEFENSE,
    "Seraph's Embrace — Lifeline": RuleFamily.THRESHOLD_DEFENSE,
    "Sterak's Gage — Lifeline": RuleFamily.THRESHOLD_DEFENSE,
    "Protoplasm Harness — Lifeline": RuleFamily.THRESHOLD_DEFENSE,
    "Banshee's Veil — Annul": RuleFamily.COMBAT_STATE,
    "Edge of Night — Annul": RuleFamily.COMBAT_STATE,
    "Verdant Barrier — Annul": RuleFamily.COMBAT_STATE,
    "Armored Advance — Noxian Endurance / Plating": RuleFamily.REACTIVE,
    "Chainlaced Crushers — Noxian Persistence": RuleFamily.REACTIVE,
    "Celestial Opposition — Blessing of the Mountain": RuleFamily.OPENING_DEFENSE,
    "Bloodthirster — Ichorshield": RuleFamily.OPENING_DEFENSE,
    "Fimbulwinter — Everlasting": RuleFamily.OPENING_DEFENSE,
}


def defense_source_labels() -> frozenset[str]:
    """Every ``DefenseSource`` label constructed in ``defensive_effects.py``.

    Derived from that module's own source rather than typed here, and read
    with ``ast`` rather than by importing the module: the closure this backs
    is "no defensive source exists without a family", and a hand list would
    be a second population to keep in step with the first.
    """
    source = (
        Path(__file__).with_name("defensive_effects.py").read_text(encoding="utf-8")
    )
    labels: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != "DefenseSource":
            continue
        for keyword in node.keywords:
            if keyword.arg != "label":
                continue
            if not isinstance(keyword.value, ast.Constant) or not isinstance(
                keyword.value.value, str
            ):
                raise BehaviorCatalogError(
                    "a DefenseSource label must be a string literal so the "
                    "closure over defensive_effects.py can read it"
                )
            labels.add(keyword.value.value)
    return frozenset(labels)


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


TermSchema = tuple[Basis, "str | tuple[str, str] | LevelRampKeys"]

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
        if isinstance(keys, LevelRampKeys):
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
) -> DamageFormula:
    """The declared formula one entry's ``formula`` name describes.

    The registry names a shape and this resolves that name into the shares it
    is made of.  A name the table does not carry is a stop, never a strike
    that quietly deals nothing: the whole point of the closed vocabulary is
    that a new schema costs one deliberate decision.
    """
    name = str(entry.get("formula"))
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
        floor=(
            AtLeast(ValueRef(registry, owner, floor_key))
            if floor_key is not None
            else NoFloor()
        ),
        damage_class=DamageClass(str(entry.get("damage_type"))),
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


def _optional_ref(
    owner: str, registry: ValueRegistry, entry: Mapping[str, Any], key: str
) -> ValueRef | None:
    """A reference to *key*, or ``None`` where the entry does not carry it.

    The declared-absence idiom: a mechanic that has no such sibling declares
    ``None``, which is a different claim from a reference that resolves to
    zero.  Presence in the entry is the test, so no item name decides it.
    """
    return ValueRef(registry, owner, key) if key in entry else None


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
    RuleFamily.CHARGED_STRIKE: _unmigrated,
    RuleFamily.SPELLBLADE: _unmigrated,
    RuleFamily.CAST_PROC: _unmigrated,
    RuleFamily.PERIODIC: _unmigrated,
    RuleFamily.ACTIVE_CAST: _compile_active_cast,
    RuleFamily.SECONDARY_TARGET: _compile_secondary_target,
    RuleFamily.DELTA_AMP: _compile_delta_amp,
    RuleFamily.RESISTANCE_SHRED: _compile_resistance_shred,
    RuleFamily.CRIT_PROFILE: _unmigrated,
    RuleFamily.DAMAGE_ROUTING: _unmigrated,
    RuleFamily.OPENING_DEFENSE: _unmigrated,
    RuleFamily.THRESHOLD_DEFENSE: _unmigrated,
    RuleFamily.COMBAT_STATE: _unmigrated,
    RuleFamily.REACTIVE: _unmigrated,
    RuleFamily.SUSTAIN: _unmigrated,
    RuleFamily.STAT_DERIVATION: _unmigrated,
    RuleFamily.ALLY_PACKET: _compile_ally_packet,
}

# Which numbered slice of this phase replaces each family's stub compiler.
UNMIGRATED_FAMILIES: Mapping[RuleFamily, str] = {
    RuleFamily.CHARGED_STRIKE: "3.4",
    RuleFamily.SPELLBLADE: "3.4",
    RuleFamily.CAST_PROC: "3.4",
    RuleFamily.PERIODIC: "3.4",
    RuleFamily.OPENING_DEFENSE: "3.5",
    RuleFamily.THRESHOLD_DEFENSE: "3.5",
    RuleFamily.COMBAT_STATE: "3.5",
    RuleFamily.REACTIVE: "3.5",
    RuleFamily.CRIT_PROFILE: "3.7",
    RuleFamily.DAMAGE_ROUTING: "3.7",
    RuleFamily.SUSTAIN: "3.7",
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


def _validate_defense_source_closure(labels: frozenset[str] | None = None) -> None:
    """Every ``DefenseSource`` construction has a family (seam: R-05)."""
    labels = defense_source_labels() if labels is None else labels
    mapped = frozenset(DEFENSE_SOURCE_FAMILY)
    if mapped != labels:
        raise BehaviorCatalogError(
            "DEFENSE_SOURCE_FAMILY must name every DefenseSource constructed in "
            f"defensive_effects.py; unmapped={sorted(labels - mapped)} "
            f"stale={sorted(mapped - labels)}"
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
    "DEFENSE_SOURCE_FAMILY",
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
    "defense_source_labels",
    "owners_for",
    "producers_for",
    "registry_entries",
    "registry_owners",
    "rule_owners",
    "undeclared_entry_count",
    "undeclared_owners",
    "validate_catalog",
]
