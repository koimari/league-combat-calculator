"""Archetype factories and the single JSON extraction core.

The one home for the ``effects[].leveling[].modifiers[]`` walk.

Extraction core:
    ``sum_modifiers``        — flat/scaling dispatch with unusual-unit override
    ``find_named_leveling``  — one exact attribute lookup
    ``extract_named``        — damage for an exact attribute name
    ``extract_auto``         — classifier-driven primary-damage detection
    ``extract_cooldown``     — base cooldown at rank
    ``extract_recharge``     — charge-ability recharge rate at rank
    ``pct_health_per_hit``   — %maxHP on-hit math (AP ratio/floor/stacks)
    ``build_stats_context``  — champion stats + current AP for scaling
"""

import re
from dataclasses import replace
from typing import Any, Callable

from ..ability_spec import ControlEvent, DamagePart, Disposition, ZeroPolicy
from .attribute_classifier import (
    classify_damage_type,
    is_damage_attribute,
    is_primary_damage_attribute,
)
from .engine import BUFF, DAMAGE, SlotCtx, SlotParser
from .inputs import target_stat
from .scaling import is_flat_unit, resolve_scaling

# ---------------------------------------------------------------------------
# Extraction core
# ---------------------------------------------------------------------------


ModifierOverride = Callable[[str, float], float | None]


_MODIFIER_PAIRS_MEMO: dict[tuple[int, int, int | None], tuple[dict, tuple]] = {}
# Attribute-lookup memos over the same cached JSON, keyed and
# identity-verified the same way.
_NAMED_LEVELING_MEMO: dict[tuple[int, str, int], tuple[dict, Any]] = {}
_PRIMARY_LEVELING_MEMO: dict[int, tuple[dict, Any]] = {}

_PROSE_SECONDS_RE = re.compile(
    r"(?<![\w.])(?P<value>\d+(?:\.\d+)?)\s+seconds?\b", re.IGNORECASE
)
_PROSE_SHIELD_SECONDS_RE = re.compile(
    r"\bshield(?:s|ed|ing)?\b.*?\bfor\s+(?:up to\s+)?"
    r"(?P<value>\d+(?:\.\d+)?)\s+seconds?\b",
    re.IGNORECASE,
)
_PROSE_INVULNERABILITY_DELAY_RE = re.compile(
    r"\bdescends?\b.*?\bover\s+(?P<value>\d+(?:\.\d+)?)\s+seconds?\b",
    re.IGNORECASE,
)
_PROSE_INVULNERABILITY_DURATION_RE = re.compile(
    r"\binvulnerable\b.*?\bfor\s+(?P<value>\d+(?:\.\d+)?)\s+seconds?\b",
    re.IGNORECASE,
)
_PROSE_CONTROL_DURATION_RE = re.compile(
    r"\b(?:airborne|charm(?:s|ed|ing)?|fear(?:s|ed|ing)?|"
    r"immobiliz(?:e|es|ed|ing)|knockback|knockup|"
    r"knock(?:s|ed|ing)?\s+(?:\w+\s+)?up|polymorph(?:s|ed|ing)?|"
    r"root(?:s|ed|ing)?|sleep(?:s|ed|ing)?|slow(?:s|ed|ing)?|"
    r"stun(?:s|ned|ning)?|"
    r"suppression|suppress(?:es|ed|ing)?|taunt(?:s|ed|ing)?)\b"
    r".*?\bfor\s+(?P<value>\d+(?:\.\d+)?)\s+seconds?\b",
    re.IGNORECASE,
)
_PROSE_DAMAGE_REDUCTION_CAP_RE = re.compile(
    r"\bcapped\s+at\s+(?P<value>\d+(?:\.\d+)?)\s*%\s+of\s+"
    r"(?:the\s+)?damage\s+instance\b",
    re.IGNORECASE,
)
_PROSE_DAMAGE_REDUCTION_RE = re.compile(
    r"\b(?:gains?|has)\s+(?P<value>\d+(?:\.\d+)?)\s*%\s+" r"damage\s+reduction\b",
    re.IGNORECASE,
)


def extract_description_duration(
    ability: dict[str, Any], effect_index: int = 0
) -> float | None:
    """Read the first seconds value from one cached effect description."""
    effects = ability.get("effects") or []
    if not isinstance(effects, list) or not 0 <= effect_index < len(effects):
        return None
    effect = effects[effect_index]
    if not isinstance(effect, dict):
        return None
    description = str(effect.get("description") or "")
    match = _PROSE_SECONDS_RE.search(description)
    return float(match.group("value")) if match else None


def extract_description_shield_duration(
    ability: dict[str, Any], effect_index: int = 0
) -> float | None:
    """Read the duration attached to a shield phrase in one effect."""
    effects = ability.get("effects") or []
    if not isinstance(effects, list) or not 0 <= effect_index < len(effects):
        return None
    effect = effects[effect_index]
    if not isinstance(effect, dict):
        return None
    description = str(effect.get("description") or "")
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", description)
    for sentence in sentences:
        match = _PROSE_SHIELD_SECONDS_RE.search(sentence)
        if match:
            return float(match.group("value"))
    return None


def extract_description_invulnerability_timing(
    ability: dict[str, Any], effect_index: int = 0
) -> tuple[float | None, float | None]:
    """Read a sourced invulnerability delay and window from one description."""
    effects = ability.get("effects") or []
    if not isinstance(effects, list) or not 0 <= effect_index < len(effects):
        return None, None
    effect = effects[effect_index]
    if not isinstance(effect, dict):
        return None, None
    description = str(effect.get("description") or "")
    delay_match = _PROSE_INVULNERABILITY_DELAY_RE.search(description)
    duration_match = _PROSE_INVULNERABILITY_DURATION_RE.search(description)
    return (
        float(delay_match.group("value")) if delay_match else None,
        float(duration_match.group("value")) if duration_match else None,
    )


def extract_description_control_duration(
    ability: dict[str, Any], effect_index: int = 0
) -> float | None:
    """Read the first action-blocking control duration from one description."""
    durations = extract_description_control_durations(ability, effect_index)
    return durations[0] if durations else None


def extract_description_control_durations(
    ability: dict[str, Any], effect_index: int = 0
) -> list[float]:
    """Read every action-blocking control duration from one description."""
    effects = ability.get("effects") or []
    if not isinstance(effects, list) or not 0 <= effect_index < len(effects):
        return []
    effect = effects[effect_index]
    if not isinstance(effect, dict):
        return []
    description = str(effect.get("description") or "")
    return [
        float(match.group("value"))
        for match in _PROSE_CONTROL_DURATION_RE.finditer(description)
    ]


def extract_description_damage_reduction_cap(
    ability: dict[str, Any], effect_index: int = 0
) -> float | None:
    """Read a percentage cap on one pre-mitigation damage instance."""
    effects = ability.get("effects") or []
    if not isinstance(effects, list) or not 0 <= effect_index < len(effects):
        return None
    effect = effects[effect_index]
    if not isinstance(effect, dict):
        return None
    description = str(effect.get("description") or "")
    match = _PROSE_DAMAGE_REDUCTION_CAP_RE.search(description)
    return float(match.group("value")) if match else None


def extract_description_damage_reduction(
    ability: dict[str, Any], effect_index: int = 0
) -> float | None:
    """Read a sourced percentage of incoming damage reduction."""
    effects = ability.get("effects") or []
    if not isinstance(effects, list) or not 0 <= effect_index < len(effects):
        return None
    effect = effects[effect_index]
    if not isinstance(effect, dict):
        return None
    description = str(effect.get("description") or "")
    match = _PROSE_DAMAGE_REDUCTION_RE.search(description)
    return float(match.group("value")) if match else None


# An ability's rank array holds one value per rank — five, or six for
# Jayce's dual-form kit, which is the longest rank axis the cache carries.
# An array this long can only hold one value per champion level.  It is the
# same rule ``extract_resource_cost`` applies to cost rows, and it is a
# length test rather than a unit test because the Wiki emits per-level
# terms under a bare unit.  Level-*bracket* arrays (Pyke R's levels 6-18,
# Aphelios P's every-third-level steps) are shorter than this and stay on
# the rank axis, unchanged: reading them needs their own sourced domain,
# not this rule.
_PER_LEVEL_VALUES = 18


def _axis_index(values: list[Any], rank: int, level: int | None) -> int:
    """Index one modifier array by its own length: a row can mix both axes."""
    axis = level if level is not None and len(values) >= _PER_LEVEL_VALUES else rank
    return min(axis - 1, len(values) - 1)


def sum_modifiers(  # pylint: disable=too-many-arguments
    leveling: dict[str, Any],
    rank: int,
    stats: dict[str, float] | None = None,
    target: dict[str, float] | None = None,
    modifier_override: ModifierOverride | None = None,
    *,
    level: int | None = None,
) -> float:
    """Sum one leveling entry's modifiers at a rank (flat + scaling).

    Args:
        leveling: One ``effects[].leveling[]`` entry from ability JSON.
        rank: 1-indexed rank (or level, for per-level entries).
        stats: Champion stats for scaling resolution.
        target: Target stats for %HP scaling.
        level: Champion level, when the caller knows it. Per-level
            modifier arrays in this row are then read at the level
            (:func:`_axis_index`) instead of at *rank*.

    Returns:
        Total raw damage contribution of this leveling entry.
    """
    # The (value, unit) pair at a rank is pure cached-JSON data; memoize it
    # by leveling-entry identity (verified on every hit) so the optimizer's
    # thousands of identical parses skip the JSON walk.
    memo_key = (id(leveling), rank, level)
    memo = _MODIFIER_PAIRS_MEMO.get(memo_key)
    if memo is not None and memo[0] is leveling:
        pairs = memo[1]
    else:
        pairs = []
        for modifier in leveling.get("modifiers", []):
            values = modifier.get("values", [])
            units = modifier.get("units", [])
            if not values:
                continue
            idx = _axis_index(values, rank, level)
            pairs.append((float(values[idx]), units[idx] if idx < len(units) else ""))
        pairs = tuple(pairs)
        _MODIFIER_PAIRS_MEMO[memo_key] = (leveling, pairs)

    total = 0.0
    for value, unit in pairs:
        overridden = modifier_override(unit, value) if modifier_override else None
        if overridden is not None:
            total += overridden
        elif is_flat_unit(unit):
            total += value
        else:
            total += resolve_scaling(unit, value, stats, target)
    return total


def extract_named(  # pylint: disable=too-many-arguments
    ability: dict[str, Any],
    attribute: str,
    rank: int,
    stats: dict[str, float] | None = None,
    target: dict[str, float] | None = None,
    *,
    level: int | None = None,
) -> float:
    """Damage for an exact attribute name, from the first matching leveling entry.

    Returns 0.0 when absent; *level* is read by :func:`sum_modifiers`.
    """
    leveling = find_named_leveling(ability, attribute)
    if leveling is None:
        return 0.0
    return sum_modifiers(leveling, rank, stats, target, level=level)


def _find_primary_damage_leveling(
    ability: dict[str, Any],
) -> dict[str, Any] | None:
    """Find the leveling entry that best represents primary damage.

    Tiered: exact matches like "Magic Damage" win over compound names
    like "Damage Per Pass"; first match wins within a tier.
    """
    memo = _PRIMARY_LEVELING_MEMO.get(id(ability))
    if memo is not None and memo[0] is ability:
        return memo[1]
    found: dict[str, Any] | None = None
    fallback: dict[str, Any] | None = None
    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            attribute = leveling.get("attribute", "")
            if is_primary_damage_attribute(attribute):
                found = leveling
                break
            if fallback is None and is_damage_attribute(attribute):
                fallback = leveling
        if found is not None:
            break
    result = found if found is not None else fallback
    _PRIMARY_LEVELING_MEMO[id(ability)] = (ability, result)
    return result


def extract_auto(
    ability: dict[str, Any],
    rank: int,
    stats: dict[str, float] | None = None,
    target: dict[str, float] | None = None,
    *,
    level: int | None = None,
) -> tuple[float, str]:
    """Damage with classifier-driven attribute auto-detection, as (raw, type).

    Damage is 0.0 when the ability has no damage attribute; the type is still
    classified.
    """
    damage_type = classify_damage_type(ability)
    leveling = _find_primary_damage_leveling(ability)
    if leveling is None:
        return 0.0, damage_type
    return sum_modifiers(leveling, rank, stats, target, level=level), damage_type


def find_named_leveling(
    ability: dict[str, Any],
    attribute: str,
    occurrence: int = 0,
) -> dict[str, Any] | None:
    """Return the N-th leveling entry with this exact attribute name.

    ``occurrence`` addresses abilities that store several arrays under one
    generic attribute (Diana P keeps base AND tripled attack speed as two
    "Per-Level Scaling" entries); the default 0 is the plain first match.
    """
    memo_key = (id(ability), attribute, occurrence)
    memo = _NAMED_LEVELING_MEMO.get(memo_key)
    if memo is not None and memo[0] is ability:
        return memo[1]
    found = None
    seen = 0
    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute", "") == attribute:
                if seen == occurrence:
                    found = leveling
                    break
                seen += 1
        if found is not None:
            break
    _NAMED_LEVELING_MEMO[memo_key] = (ability, found)
    return found


def _modifier_value(
    leveling: dict[str, Any],
    modifier_index: int,
    rank: int,
    level: int | None = None,
) -> float:
    """Raw value of one modifier at a rank (0.0 when absent/empty)."""
    modifiers = leveling.get("modifiers", [])
    if modifier_index >= len(modifiers):
        return 0.0
    values = modifiers[modifier_index].get("values", [])
    if not values:
        return 0.0
    return float(values[_axis_index(values, rank, level)])


def extract_value(
    ability: dict[str, Any],
    attribute: str,
    rank: int,
    modifier_index: int = 0,
    *,
    level: int | None = None,
    occurrence: int = 0,
) -> float:
    """A raw numeric leveling value, with no scaling resolved.

    *occurrence* picks among rows repeating one attribute name (Dr. Mundo's P).
    """
    leveling = find_named_leveling(ability, attribute, occurrence=occurrence)
    if leveling is None:
        return 0.0
    return _modifier_value(leveling, modifier_index, rank, level)


def pct_health_per_hit(
    ability: dict[str, Any],
    attr: str,
    rank: int,
    target: dict[str, float] | None,
    ap: float = 0.0,
    ap_ratio_per_100: bool = False,
    floor_attr: str | None = None,
    stacks_required: int = 1,
    *,
    level: int | None = None,
) -> float | None:
    """Per-hit on-hit damage as a percentage of the target's max health.

    The shared math behind %maxHP on-hit mechanics (Kog'Maw W, Vayne W, Aatrox
    P): modifier 0 of *attr* holds the base percentage; with
    ``ap_ratio_per_100``, modifier 1 holds extra percentage per 100 AP (Kog'Maw
    W).  The per-proc damage is floored at *floor_attr*'s value when given
    (Vayne W's minimum bonus damage), then spread evenly across
    ``stacks_required`` hits (Vayne W procs every 3rd hit).

    ``None`` means *attr* is absent from the ability, so this is not the
    mechanic and the caller drops the slot.  A ``target`` of ``None`` is zero
    damage.
    """
    leveling = find_named_leveling(ability, attr)
    if leveling is None:
        return None

    percent = _modifier_value(leveling, 0, rank, level)
    if ap_ratio_per_100:
        percent += ap * _modifier_value(leveling, 1, rank, level) / 100.0

    max_health = target_stat(target or {}, "target_max_health")
    per_proc = (percent / 100.0) * max_health
    if floor_attr:
        per_proc = max(per_proc, extract_value(ability, floor_attr, rank, level=level))
    return per_proc / stacks_required


def extract_cooldown(
    ability: dict[str, Any], rank: int, *, level: int | None = None
) -> float:
    """The base cooldown at *rank*, or 0.0 when the ability declares none.

    A per-level cooldown row (Aphelios' rankless weapon cooldowns) is read at
    *level* when the caller knows it; see :func:`_axis_index`.
    """
    cd_data = ability.get("cooldown")
    if not cd_data or not cd_data.get("modifiers"):
        return 0.0

    values = cd_data["modifiers"][0].get("values", [])
    if not values:
        return 0.0

    return float(values[_axis_index(values, rank, level)])


def extract_resource_cost(ability: dict[str, Any], rank: int, level: int) -> float:
    """What one cast of this ability spends, from its own cost row.

    The sole home of the cached cost lookup: ``engine._stamp_resource_cost``
    calls it for every slot that owns an ability JSON, and a synthetic slot,
    one the wiki has no ability entry for, calls it with the ability it is a
    cast of.  An 18-or-more-value cost row is indexed by level and a shorter
    one by rank, the same rule every cached cost row obeys.
    """
    modifiers = (ability.get("cost") or {}).get("modifiers", [])
    values = modifiers[0].get("values", []) if modifiers else []
    if not values:
        return 0.0
    index = level - 1 if len(values) >= 18 else rank - 1
    if index < 0:
        return 0.0
    return float(values[min(index, len(values) - 1)])


_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_PERCENT = re.compile(r"\d+(?:\.\d+)?\s*%")


def extract_cast_time(ability: dict[str, Any]) -> float:
    """Seconds the champion is locked out casting this ability.

    The wiki's ``castTime`` is free text: "0.25", "none", "0.25 / 0.2 (based on
    level)", "0.25 : 0.1 (based on bonus attack speed)", "0.25 • None"
    (cast • recast), "80% of X's windup time (0.4 at base attack speed)".  Read
    the first cast segment and take its first number with percentages stripped,
    so a scaled form yields its base value and pure text is instant.
    """
    raw = ability.get("castTime")
    if raw is None:
        return 0.0
    if isinstance(raw, (int, float)):
        return float(raw)
    first_cast_segment = str(raw).split("•", 1)[0]
    match = _NUMBER.search(_PERCENT.sub("", first_cast_segment))
    return float(match.group()) if match else 0.0


def build_stats_context(
    champion_stats: dict[str, float] | None,
    total_ability_power: float,
) -> dict[str, float]:
    """A copy of *champion_stats* with ``ability_power`` set to the current total."""
    ctx = dict(champion_stats) if champion_stats else {}
    ctx["ability_power"] = total_ability_power
    return ctx


# ---------------------------------------------------------------------------
# Entry builders (fight-engine output shapes)
# ---------------------------------------------------------------------------


MODULE_FORMULA_ZERO = ZeroPolicy(
    Disposition.MEASURED,
    "a champion module's formula ran against its parsed ability data and "
    "produced this total; a zero here is a computed zero, not a rule that "
    "never ran",
)
"""The one declared ``zero_policy`` default in the champion tree (D-24).

Every numeric leaf a champion authors is born in one of the two builders
below, so this is the single place the disposition has to be stated — the
399 call sites across 152 champion modules are deliberately **not** edited,
and a required-no-default field there would be a campaign-wide champion
sweep smuggled in by an idiom.  Those two figures are measured, not
recalled: ``tests/test_zero_policy.py`` counts the calls and states the
counting rule, so restating them anywhere turns it red.  ``MEASURED`` is the honest default at this layer
and only at this layer: a module formula that evaluates to zero *computed*
that zero.  Any slot whose zero means something else passes its own policy.

The default's safety rests on the inputs being wired, which is why it ships
with a guard rather than on its own.  A ``.get(key, <literal>)`` on one of
the three champion input blocks is **forbidden** — ``champions/inputs.py``
holds their vocabularies and declared defaults, and reading an undeclared
name raises — so a zero produced by an option that never resolved fails loud
instead of being stamped ``MEASURED`` here.
``scripts/behavior_frontier.py``'s zero-policy frontier enforces that
refusal and additionally pins the two ratcheted populations non-growing:
the same shape on a block the tree *produced*, and hand-built entries that
bypass these builders.
"""


STEROID_ZERO = ZeroPolicy(
    Disposition.STRUCTURAL_ZERO,
    "a steroid slot with no damage attribute grants a stat and deals no "
    "damage by declaration; the zero is the answer, not a missing formula",
)
"""The one place a champion-tree zero is a declaration rather than a result.

``stat_buff`` without a ``damage_attr`` emits a zero-damage entry so the
buff has a row to ride on.  That zero is ``STRUCTURAL_ZERO``, and saying so
here is what makes ``damage_entry``'s default overridable in fact rather
than only in signature.
"""


def damage_entry(
    name: str,
    rank: int,
    cooldown: float,
    total: float,
    dmg_type: str,
    cc_kind: str | None = None,
    *,
    zero_policy: ZeroPolicy = MODULE_FORMULA_ZERO,
    event_order_certified: str | None = None,
) -> dict[str, Any]:
    """Build a castable-ability entry in the fight-engine format.

    Damage arithmetic goes in typed ``parts``; "mixed" splits evenly between a
    magic part and a true part (like Ahri Q), magic first, because the first
    part is the Horizon Focus trigger.  ``total_raw`` is a producer-side
    test/golden diagnostic with per-entry semantics (usually the parts sum;
    proc entries store per-proc x count, and hp-scaled entries store a bound);
    the fight engine reads ONLY ``parts``.

    ``zero_policy`` says what a zero total *means*.  It defaults to
    :data:`MODULE_FORMULA_ZERO`, the one declared default in the champion tree,
    and a slot whose zero is a declaration rather than a computation passes its
    own.  It is **keyword-only**: a trailing positional would let a seventh
    positional argument at any of the hundreds of call sites bind a
    non-``ZeroPolicy`` value into it silently.

    ``cc_kind`` marks the cast's reviewed crowd control ("stun", "immobilize")
    on the entry's single part.  It is a statement about the kit and not about
    event timing: that the cast's hit lands at the cast boundary is a separate
    claim the caller makes with ``event_order_certified="single_hit"``.  A
    "mixed" entry is two parts, which the engine's certified single-hit export
    cannot carry, so that combination raises rather than silently dropping the
    marker.
    """
    if cc_kind is not None and dmg_type == "mixed":
        raise ValueError(
            f"damage_entry({name!r}): cc_kind requires a single-part entry "
            "(dmg_type must not be 'mixed')"
        )
    entry: dict[str, Any] = {
        "name": name,
        "rank": rank,
        "cooldown": cooldown,
        "damage_type": dmg_type,
        "total_raw": total,
    }
    if dmg_type == "mixed":
        entry["parts"] = (
            DamagePart("magic", total / 2.0, zero_policy=zero_policy),
            DamagePart("true", total / 2.0, zero_policy=zero_policy),
        )
    else:
        entry["parts"] = (
            DamagePart(dmg_type, total, cc_kind=cc_kind, zero_policy=zero_policy),
        )
    if event_order_certified is not None:
        entry["event_order_certified"] = event_order_certified
    return entry


def support_cast(
    *,
    default_name: str,
    detail: str,
    dmg_type: str = "magic",
    resource_cost: float | None = None,
) -> Any:
    """A slot parser for a shield/heal-only ability that damages nothing.

    ``support_effects`` hangs its packet on a CAST, so a shield- or heal-only
    ability has to be in ``SLOTS`` for the rotation to schedule one — the
    slot exists to produce the cast, not to price damage.  ``resource_cost``
    is stated only when the cached cost row is something the engine's mana
    ledger would mislabel (Soraka W's 10%-of-max-health cost).
    """

    def parse(ctx: Any) -> dict[str, Any] | None:
        ranked = ctx.ranked()
        if ranked is None:
            return None
        ability, rank = ranked
        entry = damage_entry(
            ability.get("name", default_name),
            rank,
            extract_cooldown(ability, rank),
            0.0,
            dmg_type,
        )
        # The shared builder always writes one part; a support cast has none
        # to price, and an authored zero part would put a zero-damage
        # instance in the ledger.
        entry["parts"] = ()
        entry["detail"] = detail
        if resource_cost is not None:
            entry["resource_cost"] = resource_cost
        return entry

    return parse


def attach_self_shield(
    entry: dict[str, Any],
    *,
    amount: float,
    duration: float,
    source: str,
    detail: str | None = None,
) -> dict[str, Any]:
    """Attach a module-authored self-shield payload to an ability entry.

    The payload shape mirrors the Eclipse item's ``self_shield_events``
    receipt: the engine copies the list onto the ability's damage-event
    rows by ordinal, and the participant ledger grants a timed self-shield
    at that event's timestamp.  Only an ability emitting damage events can
    carry it, so a shield-only slot stays on the ally-support scanner.
    ``actor_wide`` is the flag actor-wide heals carry -- one activation is
    one shield, de-duplicated across enemy pairs in ``participant_timeline``
    rather than by a per-module roster-index gate.
    """
    entry["self_shield_events"] = [
        {
            "amount": round(float(amount), 6),
            "duration": float(duration),
            "source": str(source),
            "actor_wide": True,
        }
    ]
    if detail:
        entry["detail"] = detail
    return entry


def on_hit_entry(
    name: str,
    damage_per_hit: float,
    dmg_type: str,
) -> dict[str, Any]:
    """Build an on-hit entry the fight engine applies per auto attack."""
    return {
        "name": name,
        "damage_type": dmg_type,
        "total_raw": 0.0,
        # Rotation consumers expect every ability row to expose an ordered
        # parts tuple, even when the row's damage is attached to the next
        # basic attack rather than dealt by the cast itself.
        "parts": (),
        "on_hit": {
            "name": f"{name} (on-hit)",
            "damage_per_hit": damage_per_hit,
            "damage_type": dmg_type,
        },
    }


def fixed_count_pet_row(
    name: str,
    damage_type: str,
    damage_per_hit: float,
    attack_times: list[float],
    detail: str,
) -> dict[str, Any]:
    """Build a fixed-count pet-attack proc row (E4 summoned units).

    The fight engine prices ``proc_count`` independent procs for entries
    outside the cast rotation (Tibbers attacks, Voidling attacks, ...):
    one ``DamagePart`` per hit, the authored attack timestamps as an
    exact event ledger, and the row's own display detail.  ``total_raw``
    is the producer-side diagnostic (per-hit x count); the engine reads
    only ``parts``.
    """
    return {
        "name": name,
        "damage_type": damage_type,
        "total_raw": damage_per_hit * len(attack_times),
        "parts": (DamagePart(damage_type, damage_per_hit),),
        "proc_count": len(attack_times),
        "damage_events": [
            {
                "time": round(time, 3),
                "damage_type": damage_type,
                "damage": damage_per_hit,
                "event_precision": "exact",
            }
            for time in attack_times
        ],
        "event_phase": "effect",
        "detail": detail,
    }


def ability_on_hit_entry(
    name: str,
    rank: int,
    damage_type: str,
    on_hit: dict[str, Any],
    cooldown: float | None = None,
) -> dict[str, Any]:
    """Wrap an on-hit payload in a zero-direct-damage ability shell."""
    entry: dict[str, Any] = {
        "name": name,
        "rank": rank,
        "damage_type": damage_type,
        "total_raw": 0.0,
        "parts": (),
        "on_hit": on_hit,
    }
    if cooldown is not None:
        entry["cooldown"] = cooldown
    return entry


# ---------------------------------------------------------------------------
# Archetype factories
# ---------------------------------------------------------------------------


def _resolve_source(
    ctx: SlotCtx,
    source: tuple[str, int] | None,
) -> tuple[dict[str, Any] | None, str]:
    """Resolve a factory's source param to (ability JSON, source slot)."""
    src_slot, src_index = source if source else (ctx.slot, 0)
    return ctx.ability(src_slot, src_index), src_slot


def _control_duration_atom(
    ctx: SlotCtx,
    source: tuple[str, int] | None,
    attribute: str,
    rank: int,
    effect_index: int = 0,
) -> tuple[float, dict[str, Any]]:
    """Read a control duration through the validated ability atom catalog."""
    src_slot, src_index = source if source else (ctx.slot, 0)
    # Deferred import avoids the slotlib -> atomizer_domains -> slotlib cycle.
    from ..ability_atoms import (
        AbilityAtomQuery,
        ranked_ability_atom_value,
        required_ability_atom,
        required_ranked_attribute_atom,
    )

    champion_data = {"name": ctx.champion_name, "abilities": ctx.abilities}
    try:
        value, atom = required_ranked_attribute_atom(
            ctx.champion_name,
            champion_data,
            src_slot,
            attribute,
            rank,
            entry_index=src_index,
        )
    except KeyError:
        source_path = (
            f"{ctx.champion_name}.{src_slot}[{src_index}].effects[{effect_index}]"
            ".description"
        )
        query = AbilityAtomQuery(
            source=source_path,
            behavior="timing",
            evidence_prefix="control duration@",
        )
        atom = required_ability_atom(
            ctx.champion_name,
            champion_data,
            src_slot,
            query=query,
        )
        value = ranked_ability_atom_value(atom, 1, source=source_path)
    units = atom.get("units", [])
    allowed_units = {"seconds", "s"}
    if not isinstance(units, list) or any(
        str(unit).strip().lower() not in allowed_units for unit in units
    ):
        raise ValueError(
            f"{ctx.champion_name} {src_slot} control duration atom must use seconds"
        )
    receipt = {
        key: atom[key]
        for key in (
            "atom_id",
            "behavior",
            "source",
            "values",
            "units",
            "evidence",
            "hash",
        )
    }
    return value, receipt


def _resolve_casts(
    casts: int | str,
    ability: dict[str, Any],
    rank: int,
    level: int | None = None,
) -> float:
    """Resolve a casts param to a damage multiplier.

    An int is used as is; a string names a leveling attribute holding the count.
    """
    if isinstance(casts, str):
        count = extract_named(ability, casts, rank, level=level)
        return count if count > 0 else 1.0
    return float(casts)


def extract_recharge(
    ability: dict[str, Any], rank: int, *, level: int | None = None
) -> float:
    """Cooldown for a charge ability: ``rechargeRate`` at rank.

    The JSON ``cooldown`` of a charge ability is the short inter-cast timer.
    """
    rates = ability.get("rechargeRate") or []
    if not rates:
        return extract_cooldown(ability, rank, level=level)
    return float(rates[_axis_index(rates, rank, level)])


def simple_damage(
    attr: str | None = None,
    dmg_type: str = "auto",
    casts: int | str = 1,
    source: tuple[str, int] | None = None,
    cooldown_from: tuple[str, int] | None = None,
    cooldown: str = "standard",
    ranks: str = "rank",
    dot_duration: float | None = None,
    cc_kind: str | None = None,
    *,
    zero_policy: ZeroPolicy = MODULE_FORMULA_ZERO,
    event_order_certified: str | None = None,
) -> SlotParser:
    """Standard castable damage slot.

    With ``attr=None`` (auto mode) this is the old generic-parser
    behavior: classifier-driven attribute detection, in-slot on-hit
    passive detection (targeting "Passive", e.g. Vayne W), and the
    generic drop rule (no damage found AND no damageType field -> slot
    omitted). With an explicit ``attr`` the named attribute is summed
    and the entry is always emitted, even at zero damage.

    Args:
        attr: Exact leveling attribute to sum, or None to auto-detect.
        dmg_type: "magic"/"physical"/"true"/"mixed", or "auto" to
            classify from the ability JSON.
        casts: Damage multiplier — int, or leveling attribute name.
        source: (slot, index) of the JSON entry to read; defaults to
            entry 0 of the parser's own slot.
        cooldown_from: (slot, index) to read cooldown from instead of
            the damage source (subspell/recast containers).
        cooldown: "standard" (the ability's cooldown field) or
            "recharge" (charge abilities — rechargeRate at rank, e.g.
            Amumu Q).
        ranks: "rank" (skill order / overrides, slot skipped below
            rank 1) or "level" (rank pinned to champion level).
        dot_duration: Seconds the ability keeps dealing ability damage
            after the cast (poisons, zone ticks). Item burns (Liandry's,
            Blackfire) stay refreshed for this tail — see
            ``_add_burn_damage``. None (default) emits nothing.
        cc_kind: Reviewed crowd control the cast applies ("stun",
            "immobilize", "root", "slow", …), stamped on the entry's
            first part so CC-triggered item passives can see the cast
            in the event ledger. Requires a single-part slot
            (``dmg_type != "mixed"``). None (default) authors no CC.
            A whole kit's kinds are better declared once in the module's
            ``MODULE_CC``; this stays for a kind that is genuinely a
            property of one construction rather than of the slot.
        zero_policy: Keyword-only. What a zero total from this slot means.
            Defaults to
            :data:`MODULE_FORMULA_ZERO`, the champion tree's one declared
            disposition (D-24); pass a different policy where a zero is a
            declaration rather than a computed result.
        event_order_certified: Keyword-only. ``"single_hit"`` states that
            this cast's one hit lands at the cast boundary, so the engine
            exports it as an authored event instead of folding it into a
            coarse aggregate row. It is a claim about timing and nothing
            else — an ability with sourced travel or delay authors the
            part's ``time_offset`` instead of certifying. A ``"mixed"``
            slot is one landing split into a magic and a true part, which
            certifies too: ``engine._certify_shared_instant`` gives the
            split parts the instant they share.

    Returns:
        A DAMAGE-phase slot parser.
    """
    if cooldown not in ("standard", "recharge"):
        raise ValueError(
            f"simple_damage: unknown cooldown mode {cooldown!r} "
            "(must be 'standard' or 'recharge')"
        )
    if cc_kind is not None and dmg_type == "mixed":
        # The engine exports a certified single-hit event only for a
        # one-part cast; a two-part "mixed" entry would silently drop
        # the CC marker from the ledger. Fail closed instead.
        raise ValueError(
            "simple_damage: cc_kind requires a single-part slot "
            "(dmg_type must not be 'mixed')"
        )
    extract_cd = extract_recharge if cooldown == "recharge" else extract_cooldown

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        ability, src_slot = _resolve_source(ctx, source)
        if ability is None:
            return None

        # In-slot on-hit passives (e.g. Vayne W Silver Bolts) are only
        # auto-detected in auto mode; explicit specs say what they want.
        if attr is None and (ability.get("targeting") or "").lower() == "passive":
            return _slot_passive_on_hit(ctx, ability)

        rank = ctx.level if ranks == "level" else ctx.rank_for(src_slot)
        if rank < 1:
            return None

        cd_ability = ctx.ability(*cooldown_from) if cooldown_from else ability
        cd_value = extract_cd(cd_ability, rank, level=ctx.level) if cd_ability else 0.0

        if attr is None:
            total, resolved_type = extract_auto(
                ability,
                rank,
                ctx.stats,
                ctx.target,
                level=ctx.level,
            )
            if total <= 0 and not ability.get("damageType"):
                # Non-damaging ability (shields, buffs, etc.)
                return None
        else:
            total = extract_named(
                ability, attr, rank, ctx.stats, ctx.target, level=ctx.level
            )
            resolved_type = classify_damage_type(ability)

        if dmg_type != "auto":
            resolved_type = dmg_type

        total *= _resolve_casts(casts, ability, rank, ctx.level)
        name = ability.get("name", f"Ability {ctx.slot}")
        entry = damage_entry(
            name,
            rank,
            cd_value,
            total,
            resolved_type,
            cc_kind,
            zero_policy=zero_policy,
            event_order_certified=event_order_certified,
        )
        if dot_duration is not None:
            entry["dot_duration"] = dot_duration
        return entry

    parse.phase = DAMAGE
    return parse


def with_control(
    parser: SlotParser,
    *,
    duration_attr: str,
    kind: str | None = None,
    source: tuple[str, int] | None = None,
    ranks: str = "rank",
    part_index: int = 0,
    effect_index: int = 0,
) -> SlotParser:
    """Attach one sourced action-blocking control interval to a damage slot.

    The interval is what this helper sources: how long, from which cached
    attribute, with the atom that proves it.  *Which* control the slot
    applies is normally the module's ``MODULE_CC`` entry, stamped after
    every phase — so a slot wrapped here and left undeclared stops the
    parse at ``engine._validate_cc_event_contract`` (a duration with no
    kind is half a declaration) instead of carrying the kind twice.

    ``kind`` is for the one slot shape ``MODULE_CC`` cannot state: a cast
    whose control differs part by part or branch by branch (Twisted Fate's
    three cards, Zilean's primed bomb).  Such a slot declares
    :data:`engine.CC_PER_PART` and authors the kind here; the engine
    refuses this argument on any slot that declared a constant.
    """
    if kind is not None and not kind.strip():
        raise ValueError("with_control kind must be a non-empty string")
    if ranks not in {"rank", "level"}:
        raise ValueError("with_control ranks must be 'rank' or 'level'")

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        entry = parser(ctx)
        if entry is None:
            return None
        ability, source_slot = _resolve_source(ctx, source)
        if ability is None:
            raise ValueError(
                f"{ctx.champion_name} {ctx.slot}: control source ability is missing"
            )
        rank = ctx.level if ranks == "level" else ctx.rank_for(source_slot)
        duration, duration_atom = _control_duration_atom(
            ctx, source, duration_attr, rank, effect_index
        )
        if duration <= 0.0:
            raise ValueError(
                f"{ctx.champion_name} {ctx.slot}: sourced control duration "
                f"{duration_attr!r} is missing or zero"
            )
        parts = list(entry.get("parts", ()))
        if not parts or part_index >= len(parts):
            raise ValueError(
                f"{ctx.champion_name} {ctx.slot}: control part index "
                f"{part_index} is absent"
            )
        if not isinstance(parts[part_index], DamagePart):
            raise TypeError(
                f"{ctx.champion_name} {ctx.slot}: control part is not a DamagePart"
            )
        part = parts[part_index]
        parts[part_index] = replace(
            part,
            cc_kind=kind if kind is not None else part.cc_kind,
            cc_duration=duration,
            control_source_atoms=(
                *part.control_source_atoms,
                {
                    key: duration_atom[key]
                    for key in (
                        "atom_id",
                        "behavior",
                        "source",
                        "values",
                        "units",
                        "evidence",
                        "hash",
                    )
                },
            ),
        )
        entry["parts"] = tuple(parts)
        return entry

    parse.phase = getattr(parser, "phase", DAMAGE)
    return parse


def with_control_event(
    parser: SlotParser,
    *,
    kind: str,
    duration_attr: str,
    source: tuple[str, int] | None = None,
    ranks: str = "rank",
    time_offset: float | None = 0.0,
    effect_index: int = 0,
) -> SlotParser:
    """Add one sourced control event, including to a utility-only slot."""
    if not kind.strip():
        raise ValueError("with_control_event kind must be a non-empty string")
    if ranks not in {"rank", "level"}:
        raise ValueError("with_control_event ranks must be 'rank' or 'level'")

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        entry = parser(ctx)
        ability, source_slot = _resolve_source(ctx, source)
        if ability is None:
            raise ValueError(
                f"{ctx.champion_name} {ctx.slot}: control source ability is missing"
            )
        rank = ctx.level if ranks == "level" else ctx.rank_for(source_slot)
        if rank < 1:
            return entry
        duration, duration_atom = _control_duration_atom(
            ctx, source, duration_attr, rank, effect_index
        )
        if duration <= 0.0:
            raise ValueError(
                f"{ctx.champion_name} {ctx.slot}: sourced control duration "
                f"{duration_attr!r} is missing or zero"
            )
        if entry is None:
            entry = {
                "name": ability.get("name", f"Ability {ctx.slot}"),
                "rank": rank,
                "cooldown": extract_cooldown(ability, rank),
                "damage_type": "magic",
                "total_raw": 0.0,
                "parts": (),
            }
        controls = list(entry.get("control_events", ()))
        controls.append(
            ControlEvent(
                kind,
                duration,
                time_offset=time_offset,
                skillshot=False,
            )
        )
        entry["control_events"] = tuple(controls)
        entry["control_source_atoms"] = [
            *entry.get("control_source_atoms", []),
            duration_atom,
        ]
        return entry

    parse.phase = getattr(parser, "phase", DAMAGE)
    return parse


def stat_buff(
    attr: str,
    stat: str,
    mode: str = "flat",
    percent_of: str = "attack_damage",
    apply_to: tuple[str, ...] = (),
    damage_attr: str | None = None,
    dmg_type: str = "physical",
    couples: tuple[str, str] | None = None,
) -> SlotParser:
    """BUFF-phase stat steroid (Vayne/Aatrox/Ambessa R pattern).

    Emits a standard damage entry (zero damage unless ``damage_attr``)
    carrying a ``stat_buff`` dict for the fight engine, and optionally
    feeds the buff into the shared ``ctx.stats`` so every later damage
    slot scales off buffed stats (the BUFF phase guarantee).

    Args:
        attr: Leveling attribute holding the buff value.
        stat: Key inside the emitted ``stat_buff`` dict (the fight
            engine dispatches on it, e.g. ``"bonus_attack_damage"``).
        mode: "flat" — the leveling value IS the buff (Vayne R);
            "percent_of" — the leveling value is a percentage of the
            ``percent_of`` stat (Aatrox R: % of total AD).
        percent_of: Stat the percentage applies to (mode="percent_of").
        apply_to: ctx.stats keys the buff value is added to, for
            in-parse scaling. Empty when only the fight engine applies
            it (Ambessa R's armor pen is not a parse-time scaling stat).
        damage_attr: Leveling attribute for the ability's own active
            damage (Ambessa R), extracted from PRE-buff stats. None
            emits 0.0 damage.
        dmg_type: Damage type labeling the entry.
        couples: ``(stats_key, attr_name)`` — publish another leveling
            value into ``ctx.stats`` under ``stats_key`` for a dependent
            slot listed later (Vayne R's Tumble cooldown reduction,
            read by Q). The key never leaves the parse context.

    Returns:
        A BUFF-phase slot parser.
    """
    if mode not in ("flat", "percent_of"):
        raise ValueError(
            f"stat_buff: unknown mode {mode!r} (must be 'flat' or 'percent_of')"
        )

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        ranked = ctx.ranked()
        if ranked is None:
            return None
        ability, rank = ranked

        value = extract_value(ability, attr, rank, level=ctx.level)
        if mode == "percent_of":
            value = value / 100.0 * ctx.stat(percent_of)

        damage = 0.0
        if damage_attr is not None:
            damage = extract_named(
                ability, damage_attr, rank, ctx.stats, ctx.target, level=ctx.level
            )

        for key in apply_to:
            ctx.stats[key] = ctx.stat(key) + value
        if couples is not None:
            stats_key, couple_attr = couples
            ctx.stats[stats_key] = extract_value(
                ability, couple_attr, rank, level=ctx.level
            )

        name = ability.get("name", f"Ability {ctx.slot}")
        entry = damage_entry(
            name,
            rank,
            extract_cooldown(ability, rank, level=ctx.level),
            damage,
            dmg_type,
            zero_policy=(
                MODULE_FORMULA_ZERO if damage_attr is not None else STEROID_ZERO
            ),
        )
        entry["stat_buff"] = {stat: value}
        return entry

    parse.phase = BUFF
    return parse


def by_option(
    option: str,
    cases: dict[Any, SlotParser],
    default: Any,
) -> SlotParser:
    """Dispatch a slot to one of several parsers by a champion option.

    The sweetspot/condemn_wall pattern: the option value picks which configured
    parser runs (Aatrox Q's sweetspot triad vs its normal triad).  All cases
    MUST emit the same entry keys, because an option may change values and
    never the emitted shape, and must share one engine phase, which is checked
    at factory time.

    Bool-keyed cases normalize the option value with ``bool()``, so a truthy
    int from the frontend selects the True case.  An unmatched selector emits
    nothing.
    """
    phases = {getattr(parser, "phase", DAMAGE) for parser in cases.values()}
    if len(phases) != 1:
        raise ValueError(
            f"by_option({option!r}): case parsers span multiple engine "
            f"phases {sorted(phases)} — a slot has exactly one phase"
        )
    bool_cases = all(isinstance(key, bool) for key in cases)

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        value = ctx.options.get(option, default)
        if bool_cases:
            value = bool(value)
        case = cases.get(value)
        return case(ctx) if case is not None else None

    parse.phase = phases.pop()
    return parse


ProcDamageResolver = Callable[[SlotCtx, dict[str, Any]], float]


def proc_damage(
    per_proc: ProcDamageResolver,
    dmg_type: str,
    count_option: str = "passive_procs",
    default_count: int = 4,
    name: str | None = None,
    phase_order_events: bool = False,
) -> SlotParser:
    """Passive that procs N times per fight (Akali/Ambessa/Akshan P).

    Per-proc damage scales per LEVEL (rank pinned to champion level);
    the proc count comes from a champion option. Emits
    ``{name, damage_type, parts: (per-proc DamagePart,), total_raw:
    per_proc * count, proc_count}`` — damage.py schedules entries with a
    ``proc_count`` outside the cast rotation.

    Args:
        per_proc: Champion-owned damage resolver for one proc.
        dmg_type: "magic"/"physical"/"true" — picks the per-proc key.
        count_option: Champion option holding the proc count.
        default_count: Proc count when the option is absent.
        name: Optional emitted label override.

    Returns:
        A DAMAGE-phase slot parser; emits nothing at zero procs or zero
        per-proc damage.
    """

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        ability = ctx.ability()
        if ability is None:
            return None

        count = int(ctx.options.get(count_option, default_count))
        if count <= 0:
            return None

        per_proc_damage = per_proc(ctx, ability)
        if per_proc_damage <= 0:
            return None

        result = {
            "name": name or ability.get("name", f"Ability {ctx.slot}"),
            "damage_type": dmg_type,
            "total_raw": per_proc_damage * count,
            "parts": (DamagePart(dmg_type, per_proc_damage),),
            "proc_count": count,
        }
        if phase_order_events:
            # Only modules with an explicit sourced post-ability trigger
            # order opt into this ledger. Other fixed-count passives remain
            # partial and are withheld by BIS rather than guessed.
            result["event_phase"] = "effect"
            result["damage_events"] = [
                {
                    "time": 0.0,
                    "damage_type": dmg_type,
                    "damage": per_proc_damage,
                    "event_precision": "phase_order",
                }
                for _ in range(count)
            ]
        return result

    parse.phase = DAMAGE
    return parse


def _slot_passive_on_hit(
    ctx: SlotCtx,
    ability: dict[str, Any],
) -> dict[str, Any] | None:
    """Parse a Q/W/E/R ability with ``targeting: "Passive"`` as on-hit."""
    rank = ctx.rank_for()
    if rank < 1:
        return None

    total, resolved_type = extract_auto(
        ability, rank, ctx.stats, ctx.target, level=ctx.level
    )
    if total <= 0:
        return None

    name = ability.get("name", f"Ability {ctx.slot}")
    return on_hit_entry(name, total, resolved_type)


def with_item_on_hits(parser, *, effectiveness, hits=1, triggers=("on_hit",)):
    """Wrap a slot parser so its entry declares item on-hit application.

    Used by named champion modules to add wiki-sourced
    ``applies_item_on_hits`` metadata to abilities that apply item on-hits
    (spellblade charges, on-hit items) without rewriting the packet parser.
    """

    def parse(ctx):
        entry = parser(ctx)
        if entry is None:
            return None
        entry["applies_item_on_hits"] = {
            "effectiveness": effectiveness,
            "hits": hits,
            "triggers": tuple(triggers),
        }
        return entry

    return parse
