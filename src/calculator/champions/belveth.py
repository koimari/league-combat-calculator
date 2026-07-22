"""Bel'Veth — slot map for the archetype engine.

Why each slot is non-generic:
- P (Death in Lavender) is three stat/modifier components with no direct
  damage: a 75% modifier on ALL basic-attack damage (base AD, crits, and
  every on-hit rider) emitted as an ``auto_attack_override``; always-active
  temporary bonus attack speed (20-40% by level); and permanent
  Lavender-stack attack speed (0.28-1.1% per stack by level, driven by the
  ``lavender_stacks`` option). The JSON stores both AS arrays under the
  generic attribute "Per-Level Scaling" (effect[1] = temp AS, effect[2] =
  per-stack), which no classifier can attribute.
- Q (Void Surge) is four directional dashes: the ``q_casts`` option
  multiplies the per-rotation cast count, dashes can crit and each applies
  item on-hit effects at 75% (``applies_item_on_hits``), and the real
  per-direction cooldown is wiki prose (the JSON cooldown field holds only
  the 1s cast lockout).
- W (Above and Below) is the one generic-shaped slot: a plain
  "Magic Damage" attribute read (knockup/slow are utility, not modeled).
- E (Royal Maelstrom) computes its slash count from final bonus attack
  speed — floor(6 + bonus AS% / 33.3) — and interpolates per-slash damage
  between the JSON min/max attributes by target missing health; slashes
  can crit, and each applies item on-hit effects at 8-32% (interpolated
  by the same missing-health fraction). The monster rows (effect[2]) and
  "Damage Reduction" (defensive) must never parse as damage.
- R (Endless Banquet) is three modeled components: the Void Coral
  explosion (true damage + 25% of target missing health, option-driven),
  the True Form stat buff (bonus health plus a TOTAL-attack-speed
  multiplier that needs custom fight-engine handling and must NOT feed
  E's slash count), and a ramping every-2nd-attack true damage proc
  emitted as a synthetic ONHIT slot ("R_onhit"). Void Remora pets are
  skipped (minion-stat summons, no champion combat damage).
"""

import math
from typing import Any

from ..ability_spec import DamagePart
from .engine import BUFF, ONHIT, SlotCtx, build_parser
from .slotlib import (
    ability_on_hit_entry,
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
    find_named_leveling,
    simple_damage,
    sum_modifiers,
)

# HARDCODED: verify on patch updates — wiki-prose values with no JSON home.
# https://wiki.leagueoflegends.com/en-us/Bel%27Veth
PASSIVE_BASIC_ATTACK_RATIO = 0.75  # all basic-attack damage reduced to 75%
Q_DIRECTION_COOLDOWNS = (16.0, 15.0, 14.0, 13.0, 12.0)  # per-direction dash CD
Q_ON_HIT_EFFECTIVENESS = 0.75  # each dash applies item on-hits at 75%
E_BASE_SLASHES = 6  # base slash count
E_BONUS_AS_PER_EXTRA_SLASH = 33.3  # +1 slash per 33.3% bonus attack speed
E_ON_HIT_MIN_EFFECTIVENESS = 0.08  # per-slash item on-hits at 0% missing HP
E_ON_HIT_MAX_EFFECTIVENESS = 0.32  # per-slash item on-hits at 100% missing HP
R_ONHIT_CADENCE = 2  # R passive procs on every 2nd basic attack


def _missing_hp_fraction(ctx: SlotCtx) -> float:
    """Shared ``target_missing_hp_pct`` option as a 0..1 fraction."""
    pct = float(ctx.options.get("target_missing_hp_pct", 50))
    return min(max(pct, 0.0), 100.0) / 100.0


def _per_level_scaling(ability: dict[str, Any], occurrence: int, level: int) -> float:
    """Value of the N-th "Per-Level Scaling" leveling entry at *level*.

    P stores two arrays under this one generic attribute name (temp AS in
    effect[1], Lavender per-stack AS in effect[2]), so the shared
    first-match lookup cannot address the second. 18-entry arrays clamp at
    their last value for levels 19-20 (``sum_modifiers`` index clamping).
    """
    seen = 0
    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute", "") == "Per-Level Scaling":
                if seen == occurrence:
                    return sum_modifiers(leveling, level)
                seen += 1
    return 0.0


def _death_in_lavender(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: 75% basic-attack modifier + always-active bonus attack speed.

    BUFF phase — the bonus AS (temp stacks + permanent Lavender stacks)
    is fed into ``ctx.stats`` so E's slash count sees it, and emitted as
    a ``stat_buff`` so the fight engine's auto count scales too. The 75%
    modifier rides an ``auto_attack_override``: ``damage_ratio`` scales
    the autos themselves, ``on_hit_effectiveness`` scales every on-hit
    rider on them (items, spellblade, R's ramping proc).
    """
    ability = ctx.ability()
    if ability is None:
        return None

    temp_as = _per_level_scaling(ability, 0, ctx.level)
    per_stack = _per_level_scaling(ability, 1, ctx.level)
    stacks = max(0, int(ctx.options.get("lavender_stacks", 0)))
    bonus_as = temp_as + per_stack * stacks

    # Parse-time context: E's slash count reads bonus_attack_speed.
    ctx.stats["bonus_attack_speed"] = (
        ctx.stats.get("bonus_attack_speed", 0.0) + bonus_as
    )
    ctx.stats["attack_speed"] = ctx.stats.get("attack_speed", 0.0) + ctx.stats.get(
        "attack_speed_ratio", 0.0
    ) * (bonus_as / 100.0)

    entry = damage_entry(
        ability.get("name", "Death in Lavender"), ctx.level, 0.0, 0.0, "physical"
    )
    entry["stat_buff"] = {"bonus_attack_speed": bonus_as}
    entry["auto_attack_override"] = {
        "damage_ratio": PASSIVE_BASIC_ATTACK_RATIO,
        "on_hit_effectiveness": PASSIVE_BASIC_ATTACK_RATIO,
    }
    entry["detail"] = (
        f"+{bonus_as:.1f}% bonus attack speed; basic attacks and their "
        f"on-hit riders deal {PASSIVE_BASIC_ATTACK_RATIO:.0%} damage"
    )
    return entry


_death_in_lavender.phase = BUFF


def _void_surge(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: ``q_casts`` directional dashes, each 0-20 + 100% AD, can crit."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    per_dash = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
    casts = min(max(int(ctx.options.get("q_casts", 4)), 1), 4)
    cooldown = Q_DIRECTION_COOLDOWNS[min(rank - 1, len(Q_DIRECTION_COOLDOWNS) - 1)]

    return {
        "name": ability.get("name", "Void Surge"),
        "rank": rank,
        "cooldown": cooldown,
        "damage_type": "physical",
        "total_raw": per_dash * casts,
        "parts": (
            DamagePart("physical", per_dash, count=casts, crit_effectiveness=1.0),
        ),
        # Each dash is its own cast (per-cast item procs, e.g. Muramana).
        "cast_instances": casts,
        # Each dash applies item on-hit effects at 75% — Q's own
        # modifier, independent of the passive's auto-only 75%. Q is
        # NOT an attack: on-hit trigger only (no on-attack cadences).
        "applies_item_on_hits": {
            "effectiveness": Q_ON_HIT_EFFECTIVENESS,
            "hits": casts,
            "triggers": ("on_hit",),
        },
    }


def _royal_maelstrom(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: slash count from final bonus AS; per-slash damage interpolates
    between the JSON min/max attributes by target missing health."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    missing = _missing_hp_fraction(ctx)
    min_hit = extract_named(
        ability, "Minimum Physical Damage per hit", rank, ctx.stats, ctx.target
    )
    max_hit = extract_named(
        ability, "Maximum Physical Damage per hit", rank, ctx.stats, ctx.target
    )
    per_slash = min_hit + (max_hit - min_hit) * missing

    # Final bonus AS: items + passive (P is BUFF phase, already applied).
    # True Form's total-AS multiplier is NOT bonus AS and never counts.
    bonus_as = ctx.stats.get("bonus_attack_speed", 0.0)
    slashes = E_BASE_SLASHES + math.floor(bonus_as / E_BONUS_AS_PER_EXTRA_SLASH + 1e-9)

    return {
        "name": ability.get("name", "Royal Maelstrom"),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "physical",
        "total_raw": per_slash * slashes,
        "parts": (
            DamagePart("physical", per_slash, count=slashes, crit_effectiveness=1.0),
        ),
        # Each slash applies item on-hits at 8-32%, interpolated by the
        # same missing-health fraction as the slash damage. Slashes are
        # real attacks (wiki: "on-hit, on-attack, and ability effects"),
        # so they also advance on-attack cadences (Guinsoo phantom).
        "applies_item_on_hits": {
            "effectiveness": E_ON_HIT_MIN_EFFECTIVENESS
            + (E_ON_HIT_MAX_EFFECTIVENESS - E_ON_HIT_MIN_EFFECTIVENESS) * missing,
            "hits": slashes,
            "triggers": ("on_hit", "on_attack"),
        },
        "detail": (
            f"{slashes} slashes at {per_slash:.0f} each "
            f"({missing:.0%} target missing health)"
        ),
    }


def _endless_banquet(ctx: SlotCtx) -> dict[str, Any] | None:
    """R active: Void Coral explosion (true damage + 25% missing health),
    plus the True Form stat buff when the ``true_form`` option is on."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    missing = _missing_hp_fraction(ctx)
    max_hp = (ctx.target or {}).get("target_max_health", 0.0)

    def missing_health_override(unit: str, value: float) -> float | None:
        # The JSON's missing-health modifier resolves against the shared
        # ``target_missing_hp_pct`` option, not the parser's full-HP target.
        if "missing health" in unit:
            return value / 100.0 * max_hp * missing
        return None

    leveling = find_named_leveling(ability, "True Damage")
    total = (
        sum_modifiers(leveling, rank, ctx.stats, ctx.target, missing_health_override)
        if leveling
        else 0.0
    )

    entry = damage_entry(
        ability.get("name", "Endless Banquet"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "true",
    )
    if bool(ctx.options.get("true_form", False)):
        bonus_health = extract_named(ability, "Bonus Health", rank, ctx.stats)
        total_as = extract_value(ability, "Increased Total Attack Speed", rank)
        entry["stat_buff"] = {
            "health": bonus_health,
            # Multiplier on FINAL attack speed (fight-engine handling);
            # deliberately not bonus_attack_speed — it must not feed the
            # base + ratio x bonus formula or E's slash count.
            "total_attack_speed_percent": total_as,
        }
        entry["detail"] = (
            f"True Form: +{bonus_health:.0f} health, "
            f"+{total_as:.0f}% total attack speed"
        )
    return entry


def _endless_banquet_onhit(ctx: SlotCtx) -> dict[str, Any] | None:
    """R passive: ramping true damage on every 2nd basic attack.

    Proc k deals k x (6/10/14 + 12% bonus AD) — stacks accumulate and
    never reset. Emitted as a ramping on-hit; the fight engine owns the
    auto-count cadence, and the passive's 75% basic-attack modifier
    applies through the override's ``on_hit_effectiveness``.
    """
    ability = ctx.ability("R")
    if ability is None:
        return None
    rank = ctx.rank_for("R")
    if rank < 1:
        return None

    per_stack = extract_named(ability, "Bonus True Damage", rank, ctx.stats, ctx.target)
    name = "Endless Banquet (every 2nd attack)"
    return ability_on_hit_entry(
        name,
        rank,
        "true",
        {
            "name": name,
            "damage_per_hit": per_stack,
            "damage_type": "true",
            "stacks_required": R_ONHIT_CADENCE,
            "ramping": True,
        },
    )


_endless_banquet_onhit.phase = ONHIT


OPTIONS: list[dict[str, Any]] = [
    {
        "key": "target_missing_hp_pct",
        "type": "int",
        "default": 50,
        "min": 0,
        "max": 100,
        "label": "Target missing health %",
    },
    {
        "key": "lavender_stacks",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 200,
        "label": "Permanent Lavender stacks (takedowns)",
    },
    {
        "key": "q_casts",
        "type": "int",
        "default": 4,
        "min": 1,
        "max": 4,
        "label": "Q casts (directional charges used)",
    },
    {
        "key": "true_form",
        "type": "bool",
        "default": False,
        "label": "True Form active (consumed Void Coral)",
    },
]

ASSUMPTIONS = [
    "Passive temporary attack speed (20-40% by level) treated as always "
    "active — she holds Death in Lavender stacks throughout a real combo",
    "Basic attacks and ALL their riders (on-hit items, crits, R passive "
    "true damage) deal 75% damage per her passive; ability damage is "
    "unaffected",
    "Q applies item on-hit effects once per dash at 75%; E once per slash "
    "at 8-32% (interpolated by target missing health) — each is that "
    "ability's own modifier, independent of the passive's auto-only 75%",
    "Q/E applications trigger on-hit item damage (Nashor's, Wit's End, "
    "BotRK, ...) and count on the shared on-hit stack counters "
    "(Kraken/Hullbreaker) — a proc fires at the effectiveness of the hit "
    "that landed it",
    "E slashes are real attacks (wiki: on-hit, on-attack, and ability "
    "effects) and advance on-attack cadences: Guinsoo's phantom-hit "
    "counter (a slash-fired phantom re-applies item on-hits at the "
    "slash's 8-32%); Q is on-hit only and never advances on-attack "
    "mechanics",
    "On-attack mechanics the engine does not model per-hit are "
    "unaffected by E: energized stacking (RFC/Voltaic use a cooldown "
    "model), Navori's refund (continuous auto rate), Yun Tal (baked "
    "stat), Runaan's (unmodeled)",
    "Spellblade (Sheen line) is consumed by the next basic attack — "
    "never by Q/E applications",
    "Shared counter hit order: rotation ability hits (cast order, "
    "recasts grouped) land before the fight's autos — the sim's "
    "existing rotation-then-autos timeline",
    "R's every-2nd-attack true damage counts basic attacks only — Q "
    "resets the attack timer but is not a basic attack",
    "Target missing health defaults to 50% (shared option driving E slash "
    "damage, E on-hit effectiveness, and R explosion)",
    "Q per-direction dash cooldown (16-12s) is wiki prose (the JSON holds "
    "the 1s cast lockout); its bonus-AS haste conversion (0.25 haste per "
    "1% bonus AS) is not modeled",
    "Monster/minion-only damage components skipped (champion combat calculator)",
    "Void Remora pets, R heal, E damage reduction/lifesteal, and W "
    "knockup/slow skipped (no enemy champion damage)",
    "True Form's total-AS increase multiplies final attack speed and does "
    "not count as bonus AS for E's slash count",
    "'Based on level' scalings read the JSON per-level arrays (which "
    "extend past level 18); a shorter array would clamp at its last entry",
]

SLOTS = {
    "P": _death_in_lavender,
    "Q": _void_surge,
    "W": simple_damage(attr="Magic Damage", dmg_type="magic"),
    "E": _royal_maelstrom,
    "R": _endless_banquet,
    "R_onhit": _endless_banquet_onhit,
}

parse_abilities = build_parser(SLOTS, "Bel'Veth")
