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
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

from . import data_registry, item_effects, rune_effects
from .ability_spec import AttackClass, DamageClass, Disposition
from .item_behavior import (
    AbsoluteWindow,
    AfterTrigger,
    Always,
    AmpChainSlot,
    Attribution,
    Compilable,
    Comparison,
    BonusTyping,
    BehaviorRule,
    BuildContext,
    DeltaAmpRule,
    ExcludeTrigger,
    Fixed,
    Isolation,
    LivePredicate,
    Magnitude,
    MeleeRangedSplit,
    Persist,
    Pool,
    Probe,
    RULE_FAMILY_COUNT,
    RampModel,
    RampPerSecond,
    RampPerStack,
    ReceiptOnly,
    Resistance,
    ResistanceShredRule,
    RuleFamily,
    StackRamp,
    Subject,
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
    "ITEM_EFFECTS": {"damage_amp_per_second": RuleFamily.DELTA_AMP},
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
    RuleFamily.ON_HIT_STRIKE: _unmigrated,
    RuleFamily.CHARGED_STRIKE: _unmigrated,
    RuleFamily.SPELLBLADE: _unmigrated,
    RuleFamily.CAST_PROC: _unmigrated,
    RuleFamily.PERIODIC: _unmigrated,
    RuleFamily.ACTIVE_CAST: _unmigrated,
    RuleFamily.SECONDARY_TARGET: _unmigrated,
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
    RuleFamily.ALLY_PACKET: _unmigrated,
}

# Which numbered slice of this phase replaces each family's stub compiler.
UNMIGRATED_FAMILIES: Mapping[RuleFamily, str] = {
    RuleFamily.ON_HIT_STRIKE: "3.4",
    RuleFamily.CHARGED_STRIKE: "3.4",
    RuleFamily.SPELLBLADE: "3.4",
    RuleFamily.CAST_PROC: "3.4",
    RuleFamily.PERIODIC: "3.4",
    RuleFamily.ACTIVE_CAST: "3.4",
    RuleFamily.SECONDARY_TARGET: "3.4",
    RuleFamily.OPENING_DEFENSE: "3.5",
    RuleFamily.THRESHOLD_DEFENSE: "3.5",
    RuleFamily.COMBAT_STATE: "3.5",
    RuleFamily.REACTIVE: "3.5",
    RuleFamily.ALLY_PACKET: "3.6",
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


validate_catalog()


__all__ = [
    "ACTION_KIND_FAMILY",
    "ASSUMED_CARVE_LEADING_ABILITY_HITS",
    "ALLY_DELTA_AMP_KEYS",
    "ALLY_DELTA_AMP_SLOTS",
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
    "NO_LEADING_STACKS",
    "TAG_FAMILY",
    "UNMIGRATED_FAMILIES",
    "behavior_rules",
    "build_context",
    "cached_source_receipt",
    "declared_owners",
    "declared_tags",
    "entry_families",
    "keystone_entries",
    "defense_source_labels",
    "registry_entries",
    "registry_owners",
    "rule_owners",
    "undeclared_entry_count",
    "undeclared_owners",
    "validate_catalog",
]
