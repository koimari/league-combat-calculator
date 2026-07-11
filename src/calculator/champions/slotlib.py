"""Archetype factories and the single JSON extraction core.

One home for the ``effects[].leveling[].modifiers[]`` walk that was
previously duplicated between ``common.py`` and ``generic_parser.py``
(both are kept alive until the Phase 3 ports finish, then deleted).

Extraction core:
    ``_sum_modifiers``       — flat-vs-scaling dispatch over one leveling entry
    ``extract_named``        — damage for an exact attribute name
    ``extract_auto``         — classifier-driven primary-damage detection
    ``extract_cooldown``     — base cooldown at rank
    ``build_stats_context``  — champion stats + current AP for scaling

Archetype factories return slot parsers (``SlotCtx -> entry | None``)
stamped with their engine phase. Shared factory params:
    ``source=(slot, index)`` — which JSON ability entry to read
                               (default: entry 0 of the parser's own slot)
    ``cooldown_from=(slot, index)`` — read cooldown from a different entry
                               (subspell/recast containers)
    ``casts``                — int multiplier, or an attribute name whose
                               leveling value at rank is the multiplier
    ``ranks``                — "rank" (skill order / overrides) or "level"
                               (rank pinned to champion level, for
                               passives and no-skill-point kits)

Later Phase 3 steps add stat_buff / on_hit_pct_health / toggle_dot / etc.
here; the engine needs no changes for them.
"""

from typing import Any

from .attribute_classifier import (
    classify_damage_type,
    is_damage_attribute,
    is_primary_damage_attribute,
)
from .engine import DAMAGE, ONHIT, SlotCtx, SlotParser
from .scaling import is_flat_unit, resolve_scaling

# ---------------------------------------------------------------------------
# Extraction core
# ---------------------------------------------------------------------------


def _sum_modifiers(
    leveling: dict[str, Any],
    rank: int,
    stats: dict[str, float] | None = None,
    target: dict[str, float] | None = None,
) -> float:
    """Sum one leveling entry's modifiers at a rank (flat + scaling).

    Args:
        leveling: One ``effects[].leveling[]`` entry from ability JSON.
        rank: 1-indexed rank (or level, for per-level entries).
        stats: Champion stats for scaling resolution.
        target: Target stats for %HP scaling.

    Returns:
        Total raw damage contribution of this leveling entry.
    """
    total = 0.0
    for modifier in leveling.get("modifiers", []):
        values = modifier.get("values", [])
        units = modifier.get("units", [])
        if not values:
            continue

        idx = min(rank - 1, len(values) - 1)
        value = float(values[idx])
        unit = units[idx] if idx < len(units) else ""

        if is_flat_unit(unit):
            total += value
        else:
            total += resolve_scaling(unit, value, stats, target)
    return total


def extract_named(
    ability: dict[str, Any],
    attribute: str,
    rank: int,
    stats: dict[str, float] | None = None,
    target: dict[str, float] | None = None,
) -> float:
    """Extract damage for an exact attribute name from ability JSON.

    Uses the first matching leveling entry across all effects.

    Args:
        ability: Single ability dict from champion JSON.
        attribute: Exact attribute name (e.g. ``"Total Magic Damage"``).
        rank: Ability rank (1-indexed).
        stats: Champion stats for scaling resolution.
        target: Target stats for %HP scaling.

    Returns:
        Total raw damage at the given rank, or 0.0 if not found.
    """
    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute", "") == attribute:
                return _sum_modifiers(leveling, rank, stats, target)
    return 0.0


def _find_primary_damage_leveling(
    ability: dict[str, Any],
) -> dict[str, Any] | None:
    """Find the leveling entry that best represents primary damage.

    Tiered: exact matches like "Magic Damage" win over compound names
    like "Damage Per Pass"; first match wins within a tier.
    """
    fallback: dict[str, Any] | None = None
    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            attribute = leveling.get("attribute", "")
            if is_primary_damage_attribute(attribute):
                return leveling
            if fallback is None and is_damage_attribute(attribute):
                fallback = leveling
    return fallback


def extract_auto(
    ability: dict[str, Any],
    rank: int,
    stats: dict[str, float] | None = None,
    target: dict[str, float] | None = None,
) -> tuple[float, str]:
    """Extract damage with classifier-driven attribute auto-detection.

    The old generic-parser behavior: classify the damage type from the
    ability JSON and sum the best primary-damage leveling entry.

    Args:
        ability: Single ability dict from champion JSON.
        rank: Ability rank (1-indexed), or level for per-level entries.
        stats: Champion stats for scaling resolution.
        target: Target stats for %HP scaling.

    Returns:
        Tuple of (total_raw_damage, damage_type). Damage is 0.0 when no
        damage attribute is found; the type is still classified.
    """
    damage_type = classify_damage_type(ability)
    leveling = _find_primary_damage_leveling(ability)
    if leveling is None:
        return 0.0, damage_type
    return _sum_modifiers(leveling, rank, stats, target), damage_type


def extract_value(
    ability: dict[str, Any],
    attribute: str,
    rank: int,
    modifier_index: int = 0,
) -> float:
    """Extract a raw numeric leveling value without resolving scaling.

    For non-damage numbers like penetration percentages, attack-speed
    bonuses, or flurry ratios, where the unit is descriptive rather than
    a stat scaling to resolve.

    Args:
        ability: Single ability dict from champion JSON.
        attribute: Exact attribute name to look for.
        rank: Ability rank (1-indexed).
        modifier_index: Which modifier to read (default 0 = first).

    Returns:
        The flat numeric value at the given rank, or 0.0 if not found.
    """
    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute", "") != attribute:
                continue

            modifiers = leveling.get("modifiers", [])
            if modifier_index >= len(modifiers):
                return 0.0

            values = modifiers[modifier_index].get("values", [])
            if not values:
                return 0.0

            idx = min(rank - 1, len(values) - 1)
            return float(values[idx])
    return 0.0


def extract_cooldown(ability: dict[str, Any], rank: int) -> float:
    """Extract the base cooldown for an ability at a given rank.

    Args:
        ability: Single ability dict from champion JSON.
        rank: Ability rank (1-indexed).

    Returns:
        Base cooldown in seconds, or 0.0 if not found.
    """
    cd_data = ability.get("cooldown")
    if not cd_data or not cd_data.get("modifiers"):
        return 0.0

    values = cd_data["modifiers"][0].get("values", [])
    if not values:
        return 0.0

    idx = min(rank - 1, len(values) - 1)
    return float(values[idx])


def build_stats_context(
    champion_stats: dict[str, float] | None,
    total_ability_power: float,
) -> dict[str, float]:
    """Build the mutable stats context dict for scaling resolution.

    Copies champion_stats (BUFF parsers mutate the context, never the
    caller's dict) and overrides AP with the current total (stats may
    have been computed before AP items).

    Args:
        champion_stats: Champion's calculated stats dict.
        total_ability_power: Total AP after items and multipliers.

    Returns:
        Stats context dict usable by ``resolve_scaling()``.
    """
    ctx = dict(champion_stats) if champion_stats else {}
    ctx["ability_power"] = total_ability_power
    return ctx


# ---------------------------------------------------------------------------
# Entry builders (fight-engine output shapes)
# ---------------------------------------------------------------------------


def damage_entry(
    name: str,
    rank: int,
    cooldown: float,
    total: float,
    dmg_type: str,
) -> dict[str, Any]:
    """Build a castable-ability entry in the fight-engine format.

    Sets the type-specific damage key from the damage type; "mixed"
    splits evenly between magic and true (like Ahri Q).
    """
    entry: dict[str, Any] = {
        "name": name,
        "rank": rank,
        "cooldown": cooldown,
        "damage_type": dmg_type,
        "total_raw": total,
    }
    if dmg_type == "magic":
        entry["magic_damage"] = total
    elif dmg_type == "physical":
        entry["physical_damage"] = total
    elif dmg_type == "true":
        entry["true_damage"] = total
    elif dmg_type == "mixed":
        entry["magic_damage"] = total / 2.0
        entry["true_damage"] = total / 2.0
    return entry


def on_hit_entry(
    name: str,
    damage_per_hit: float,
    dmg_type: str,
) -> dict[str, Any]:
    """Build an on-hit entry the fight engine applies per auto attack."""
    return {
        "name": name,
        "on_hit": {
            "name": f"{name} (on-hit)",
            "damage_per_hit": damage_per_hit,
            "damage_type": dmg_type,
        },
    }


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


def _resolve_casts(
    casts: int | str,
    ability: dict[str, Any],
    rank: int,
) -> float:
    """Resolve a casts param to a damage multiplier.

    An int is used as-is; a string names a leveling attribute (e.g.
    Xerath R's "Number of Recasts") whose value at rank is the count.
    A missing/zero count attribute falls back to 1 (single cast) rather
    than silently zeroing the slot's damage.
    """
    if isinstance(casts, str):
        count = extract_named(ability, casts, rank)
        return count if count > 0 else 1.0
    return float(casts)


def _extract_recharge(ability: dict[str, Any], rank: int) -> float:
    """Cooldown for a charge ability: rechargeRate at rank.

    The JSON ``cooldown`` field of a charge ability stores the short
    inter-cast timer; the limiter for sustained use is how fast charges
    come back. Falls back to the plain cooldown when the ability has no
    rechargeRate data.
    """
    rates = ability.get("rechargeRate") or []
    if not rates:
        return extract_cooldown(ability, rank)
    idx = min(rank - 1, len(rates) - 1)
    return float(rates[idx])


def simple_damage(
    attr: str | None = None,
    dmg_type: str = "auto",
    casts: int | str = 1,
    source: tuple[str, int] | None = None,
    cooldown_from: tuple[str, int] | None = None,
    cooldown: str = "standard",
    ranks: str = "rank",
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

    Returns:
        A DAMAGE-phase slot parser.
    """
    if cooldown not in ("standard", "recharge"):
        raise ValueError(
            f"simple_damage: unknown cooldown mode {cooldown!r} "
            "(must be 'standard' or 'recharge')"
        )
    extract_cd = _extract_recharge if cooldown == "recharge" else extract_cooldown

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
        cd_value = extract_cd(cd_ability, rank) if cd_ability else 0.0

        if attr is None:
            total, resolved_type = extract_auto(
                ability,
                rank,
                ctx.stats,
                ctx.target,
            )
            if total <= 0 and not ability.get("damageType"):
                # Non-damaging ability (shields, buffs, etc.)
                return None
        else:
            total = extract_named(ability, attr, rank, ctx.stats, ctx.target)
            resolved_type = classify_damage_type(ability)

        if dmg_type != "auto":
            resolved_type = dmg_type

        total *= _resolve_casts(casts, ability, rank)
        name = ability.get("name", f"Ability {ctx.slot}")
        return damage_entry(name, rank, cd_value, total, resolved_type)

    parse.phase = DAMAGE
    return parse


def toggle_dot(
    phases: list[tuple[str, int | None]],
    duration_option: tuple[str, float],
    interval: float = 0.5,
    min_duration: float = 0.0,
    cooldown: float = 0.0,
    dmg_type: str = "auto",
    source: tuple[str, int] | None = None,
) -> SlotParser:
    """Toggle/channel DoT summed over its ticks into a damage entry.

    The active duration comes from a champion option; total tick count is
    ``int(duration / interval)``. Ticks are consumed by ``phases`` in
    order — e.g. Anivia R deals 3 initial-damage ticks, then empowered
    ticks for the rest — and the phase damages are summed into ONE
    standard damage entry (same shape as ``simple_damage``).

    Args:
        phases: Ordered ``(leveling_attribute, tick_cap)`` pairs. A cap
            of None means "all remaining ticks" (use it last).
        duration_option: ``(option_key, default_seconds)`` — the champion
            option holding the active duration.
        interval: Seconds per tick.
        min_duration: Floor for the duration option (e.g. Anivia R's
            first phase always completes).
        cooldown: Emitted verbatim — toggles have no base cooldown, so
            the caller pins it (0.0 = free toggle, 999.0 = model the
            ability as cast exactly once per fight).
        dmg_type: "magic"/"physical"/"true"/"mixed", or "auto" to
            classify from the ability JSON.
        source: (slot, index) of the JSON entry to read; defaults to
            entry 0 of the parser's own slot.

    Returns:
        A DAMAGE-phase slot parser.
    """

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        ability, src_slot = _resolve_source(ctx, source)
        if ability is None:
            return None

        rank = ctx.rank_for(src_slot)
        if rank < 1:
            return None

        option_key, default_seconds = duration_option
        duration = float(ctx.options.get(option_key, default_seconds))
        duration = max(duration, min_duration)

        ticks_remaining = int(duration / interval)
        total = 0.0
        for attr, tick_cap in phases:
            ticks = (
                ticks_remaining
                if tick_cap is None
                else min(tick_cap, ticks_remaining)
            )
            per_tick = extract_named(ability, attr, rank, ctx.stats, ctx.target)
            total += ticks * per_tick
            ticks_remaining -= ticks

        resolved_type = classify_damage_type(ability) if dmg_type == "auto" else dmg_type
        name = ability.get("name", f"Ability {ctx.slot}")
        return damage_entry(name, rank, cooldown, total, resolved_type)

    parse.phase = DAMAGE
    return parse


# Damage type -> entry key for per-proc damage values.
_DAMAGE_TYPE_KEYS = {
    "magic": "magic_damage",
    "physical": "physical_damage",
    "true": "true_damage",
}


def proc_damage(
    attr: str,
    dmg_type: str,
    count_option: str = "passive_procs",
    default_count: int = 4,
) -> SlotParser:
    """Passive that procs N times per fight (Akali/Ambessa/Akshan P).

    Per-proc damage scales per LEVEL (rank pinned to champion level);
    the proc count comes from a champion option. Emits
    ``{name, damage_type, <type>_damage: per_proc, total_raw:
    per_proc * count, proc_count}`` — damage.py schedules entries with a
    ``proc_count`` outside the cast rotation.

    Args:
        attr: Exact leveling attribute holding the per-proc damage.
        dmg_type: "magic"/"physical"/"true" — picks the per-proc key.
        count_option: Champion option holding the proc count.
        default_count: Proc count when the option is absent.

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

        per_proc = extract_named(ability, attr, ctx.level, ctx.stats, ctx.target)
        if per_proc <= 0:
            return None

        return {
            "name": ability.get("name", f"Ability {ctx.slot}"),
            "damage_type": dmg_type,
            _DAMAGE_TYPE_KEYS[dmg_type]: per_proc,
            "total_raw": per_proc * count,
            "proc_count": count,
        }

    parse.phase = DAMAGE
    return parse


def utility(dmg_type: str = "magic") -> SlotParser:
    """Zero-damage display placeholder for a ranked utility ability.

    Shields, walls, and other non-damaging-but-castable slots that the
    UI should still list: emits a standard damage entry with 0.0 damage
    and the real cooldown, gated on the slot being ranked.

    Args:
        dmg_type: Damage type to label the placeholder with (drives
            which zero-valued damage key is emitted).

    Returns:
        A DAMAGE-phase slot parser.
    """

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        ability = ctx.ability()
        if ability is None:
            return None

        rank = ctx.rank_for()
        if rank < 1:
            return None

        name = ability.get("name", f"Ability {ctx.slot}")
        return damage_entry(name, rank, extract_cooldown(ability, rank), 0.0, dmg_type)

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

    total, resolved_type = extract_auto(ability, rank, ctx.stats, ctx.target)
    if total <= 0:
        return None

    name = ability.get("name", f"Ability {ctx.slot}")
    return on_hit_entry(name, total, resolved_type)


# Keywords marking a champion passive as an on-hit effect.
_ON_HIT_KEYWORDS = ("on-hit", "on hit", "basic attack", "auto-attack")


def on_hit_auto(source: tuple[str, int] | None = None) -> SlotParser:
    """Auto-detected on-hit champion passive (P slot).

    The old generic-parser behavior: the passive must carry a
    ``damageType`` and mention an on-hit keyword in its effect
    descriptions; damage scales per level (not rank). Emits nothing
    when detection fails or the damage is zero.

    Args:
        source: (slot, index) of the JSON entry to read; defaults to
            entry 0 of the parser's own slot.

    Returns:
        An ONHIT-phase slot parser.
    """

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        ability, _ = _resolve_source(ctx, source)
        if ability is None:
            return None

        if not ability.get("damageType"):
            return None

        desc = ""
        for effect in ability.get("effects", []):
            desc += effect.get("description", "").lower()
        if not any(kw in desc for kw in _ON_HIT_KEYWORDS):
            return None

        total, resolved_type = extract_auto(
            ability,
            ctx.level,
            ctx.stats,
            ctx.target,
        )
        if total <= 0:
            return None

        return on_hit_entry(ability.get("name", "Passive"), total, resolved_type)

    parse.phase = ONHIT
    return parse
