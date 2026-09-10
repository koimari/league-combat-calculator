"""The one effects[].leveling[].modifiers[] walk."""

import re
from collections.abc import Callable, Mapping
from typing import Any

from .attribute_classifier import (
    classify_damage_type,
    is_damage_attribute,
    is_primary_damage_attribute,
)
from .inputs import ChampionInputError, target_stat
from .scaling import is_flat_unit, resolve_scaling

ModifierOverride = Callable[[str, float], float | None]


# The cached wiki leveling attribute a per-level ramp is filed under.
PER_LEVEL_SCALING = "Per-Level Scaling"


_MODIFIER_PAIRS_MEMO: dict[tuple[int, int, int | None], tuple[dict, tuple]] = {}


# Attribute-lookup memos over the same cached JSON, keyed and
# identity-verified the same way.
_NAMED_LEVELING_MEMO: dict[tuple[int, str, int], tuple[dict, Any]] = {}


_PRIMARY_LEVELING_MEMO: dict[int, tuple[dict, Any]] = {}


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
    leveling: Mapping[str, Any],
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
    *,
    ap: float = 0.0,
    ap_ratio_per_100: bool = False,
    floor_attr: str | None = None,
    stacks_required: int = 1,
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

    percent = _modifier_value(leveling, 0, rank)
    if ap_ratio_per_100:
        percent += ap * _modifier_value(leveling, 1, rank) / 100.0

    max_health = target_stat(target or {}, "target_max_health")
    per_proc = (percent / 100.0) * max_health
    if floor_attr:
        per_proc = max(per_proc, extract_value(ability, floor_attr, rank))
    return per_proc / stacks_required


def ability_name(ability: Mapping[str, Any]) -> str:
    """The cached row's own name — the fourth input block read with no literal.

    ``SlotCtx`` refuses a ``.get(key, <literal>)`` on stats, target and
    options; the ability JSON is the fourth such block, and every cached row
    carries a name.  A module's own spelling of it would outlive the parse
    that stopped supplying it.
    """
    name = ability.get("name")
    if not isinstance(name, str) or not name:
        raise ChampionInputError(
            f"cached ability row carries no 'name' (data/champions.json, "
            f"icon {ability.get('icon')!r})"
        )
    return name


def extract_cooldown(
    ability: Mapping[str, Any], rank: int, *, level: int | None = None
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


def extract_resource_cost(ability: Mapping[str, Any], rank: int, level: int) -> float:
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


def extract_cast_time(ability: Mapping[str, Any]) -> float:
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
