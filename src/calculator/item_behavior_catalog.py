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

from . import data_registry, item_effects
from .item_behavior import (
    BehaviorRule,
    BuildContext,
    RULE_FAMILY_COUNT,
    RuleFamily,
)
from .survival.actions import ActionKind
from .value_ref import ValueRegistry


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


# ── compilers (D-52's ruled exception to "no callables in declarations") ──

Compiler = Callable[
    [RuleFamily, str, ValueRegistry, Mapping[str, Any]], tuple[BehaviorRule, ...]
]


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
    RuleFamily.DELTA_AMP: _unmigrated,
    RuleFamily.RESISTANCE_SHRED: _unmigrated,
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
    RuleFamily.DELTA_AMP: "3.2",
    RuleFamily.RESISTANCE_SHRED: "3.3",
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
    for registry, family, entry in registry_entries(owner):
        rules.extend(_COMPILERS[family](family, owner, registry, entry))
    return tuple(rules)


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


def build_context(owner: str, level: int) -> BuildContext:
    """The build-time context an interpreter reads, stamped with the data version.

    ``data_registry.data_version()`` (D-49) is read here rather than by each
    interpreter, so every memo downstream keys on one counter instead of on
    object identity.
    """
    return BuildContext(
        level=level, owner=owner, data_version=data_registry.data_version()
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


validate_catalog()


__all__ = [
    "ACTION_KIND_FAMILY",
    "BehaviorCatalogError",
    "Compiler",
    "DEFENSE_SOURCE_FAMILY",
    "H4_DEAD_TAGS",
    "H4_SELF_REFERENTIAL_TAGS",
    "H4_TAG_REASONS",
    "TAG_FAMILY",
    "UNMIGRATED_FAMILIES",
    "behavior_rules",
    "build_context",
    "declared_owners",
    "defense_source_labels",
    "registry_entries",
    "registry_owners",
    "undeclared_entry_count",
    "undeclared_owners",
    "validate_catalog",
]
