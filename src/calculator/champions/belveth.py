"""Bel'Veth — revision-backed 26.15 slot map for the archetype engine.

Why each slot is non-generic:
- P (Death in Lavender) has no direct damage. Ability casts grant a flat
  20% bonus attack speed for three seconds; permanent Lavender stacks grant
  0.1-2% bonus attack speed each by champion level. Patch 26.15 restored
  basic attacks to 100% damage and removed the 75% on-hit rider modifier.
- Q (Void Surge) is four directional dashes: the ``q_casts`` option
  multiplies the per-rotation cast count, dashes can crit and each applies
  item on-hit effects at 100% (``applies_item_on_hits``), and the real
  per-direction cooldown is wiki prose (the JSON cooldown field holds only
  the 1s cast lockout).
- W (Above and Below) is the one generic-shaped slot: a plain
  "Magic Damage" attribute read with its sourced knock-up interval; the slow
  remains utility.
- E (Royal Maelstrom) computes its slash count from final bonus attack
  speed — floor(6 + bonus AS% / 40) — and interpolates per-slash damage
  between the JSON min/max attributes by target missing health; slashes
  can crit, and each applies item on-hit effects at 12-24% (interpolated
  by the same missing-health fraction). The monster rows (effect[2]) and
  "Damage Reduction" (defensive) must never parse as damage.
- R (Endless Banquet) is three modeled components: the Void Coral
  explosion (true damage + 25% of target missing health, option-driven),
  the True Form stat buff (bonus health plus a TOTAL-attack-speed
  multiplier that needs custom fight-engine handling and must NOT feed
  E's slash count), and a ramping every-attack true damage proc
  emitted as a synthetic ONHIT slot ("R_onhit"). Void Remora pets are
  skipped (minion-stat summons, no champion combat damage).
"""

import math
from typing import Any

from ..ability_spec import DamagePart
from .engine import BUFF, ONHIT, SlotCtx, build_parser
from .module_helpers import missing_hp_fraction
from .slotlib import (
    ability_on_hit_entry,
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
    find_named_leveling,
    simple_damage,
    sum_modifiers,
    with_control,
)
from .source_receipts import load_champion_sources

# HARDCODED: verify on patch updates — wiki-prose values with no JSON home.
# https://wiki.leagueoflegends.com/en-us/Bel%27Veth
PASSIVE_BASIC_ATTACK_RATIO = 1.0  # patch 26.15 restored full basic-attack damage
PASSIVE_ON_HIT_RATIO = 1.0  # 26.15 removed the 75% on-hit rider modifier
PASSIVE_TEMP_BONUS_AS = 20.0  # refreshed for 3 seconds by every ability cast
Q_DIRECTION_COOLDOWNS = (16.0, 15.0, 14.0, 13.0, 12.0)  # per-direction dash CD
Q_ON_HIT_EFFECTIVENESS = 1.0  # 26.15 removed the 75% Q on-hit reduction
E_BASE_SLASHES = 6  # base slash count
E_BONUS_AS_PER_EXTRA_SLASH = 40.0  # +1 slash per 40% bonus attack speed
# The frenzy's own length, which is also the slashes' schedule: "Bel'Veth
# enters a frenzy for 1.5 seconds" and "she rapidly slashes at the nearest
# enemy ... up to 6 (+ 1 per 40% bonus attack speed) times over the
# duration" (data/champions.json Bel'Veth E).  A count over a duration is a
# whole schedule, so the slashes are spaced across it evenly.
E_DURATION_SECONDS = 1.5
E_ON_HIT_MIN_EFFECTIVENESS = 0.12  # per-slash on-hits at 0% missing HP
E_ON_HIT_MAX_EFFECTIVENESS = 0.24  # per-slash on-hits at 100% missing HP
R_ONHIT_CADENCE = 1  # patch 26.15: R passive procs on every attack


def _per_level_scaling(ability: dict[str, Any], occurrence: int, level: int) -> float:
    """Value of the N-th "Per-Level Scaling" leveling entry at *level*.

    Death in Lavender stores its permanent-stack AS under this generic
    attribute name. Arrays clamp at their last value when shorter than the
    requested level (``sum_modifiers`` index clamping).
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
    """P: full basic-attack damage, full on-hits, and bonus attack speed.

    BUFF phase — the bonus AS (temporary buff + permanent Lavender stacks)
    is fed into ``ctx.stats`` so E's slash count sees it, and emitted as
    a ``stat_buff`` so the fight engine's auto count scales too. The attack
    override keeps attacks at full damage while scaling every on-hit rider
    (items, spellblade, R's ramping proc).
    """
    ability = ctx.ability()
    if ability is None:
        return None

    temp_as = PASSIVE_TEMP_BONUS_AS
    per_stack = _per_level_scaling(ability, 0, ctx.level)
    stacks = max(0, int(ctx.option("lavender_stacks")))
    bonus_as = temp_as + per_stack * stacks

    # Parse-time context: E's slash count reads bonus_attack_speed.
    ctx.stats["bonus_attack_speed"] = ctx.stat("bonus_attack_speed") + bonus_as
    ctx.stats["attack_speed"] = ctx.stat("attack_speed") + ctx.stat(
        "attack_speed_ratio"
    ) * (bonus_as / 100.0)

    entry = damage_entry(
        ability.get("name", "Death in Lavender"), ctx.level, 0.0, 0.0, "physical"
    )
    entry["stat_buff"] = {"bonus_attack_speed": bonus_as}
    entry["auto_attack_override"] = {
        "damage_ratio": PASSIVE_BASIC_ATTACK_RATIO,
        "on_hit_effectiveness": PASSIVE_ON_HIT_RATIO,
    }
    entry["detail"] = (
        f"+{bonus_as:.1f}% bonus attack speed; basic attacks deal full "
        f"damage and on-hit riders deal {PASSIVE_ON_HIT_RATIO:.0%}"
    )
    return entry


_death_in_lavender.phase = BUFF


def _void_surge(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: ``q_casts`` directional dashes, each 12-20 + 105% AD, can crit."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    per_dash = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
    casts = min(max(int(ctx.option("q_casts")), 1), 4)
    cooldown = Q_DIRECTION_COOLDOWNS[min(rank - 1, len(Q_DIRECTION_COOLDOWNS) - 1)]

    return {
        "name": ability.get("name", "Void Surge"),
        "rank": rank,
        "cooldown": cooldown,
        "damage_type": "physical",
        "total_raw": per_dash * casts,
        "parts": (
            # Directional dashes are an explicitly ordered sequence inside
            # the cast.  The current cache does not publish a sub-dash delay,
            # so they share the cast boundary while retaining deterministic
            # application order for R's carried on-hit state.
            DamagePart(
                "physical",
                per_dash,
                count=casts,
                crit_effectiveness=1.0,
            ),
        ),
        # Each dash is its own cast (per-cast item procs, e.g. Muramana).
        "cast_instances": casts,
        # Each dash applies item on-hit effects at 100% — Q's own
        # modifier, independent of the passive's auto-only modifier. Q is
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

    missing = missing_hp_fraction(ctx)
    min_hit = extract_named(
        ability, "Minimum Physical Damage per hit", rank, ctx.stats, ctx.target
    )
    max_hit = extract_named(
        ability, "Maximum Physical Damage per hit", rank, ctx.stats, ctx.target
    )
    per_slash = min_hit + (max_hit - min_hit) * missing

    # Final bonus AS: items + passive (P is BUFF phase, already applied).
    # True Form's total-AS multiplier is NOT bonus AS and never counts.
    bonus_as = ctx.stat("bonus_attack_speed")
    slashes = E_BASE_SLASHES + math.floor(bonus_as / E_BONUS_AS_PER_EXTRA_SLASH + 1e-9)

    return {
        "name": ability.get("name", "Royal Maelstrom"),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "physical",
        "total_raw": per_slash * slashes,
        "parts": (
            # The slash count and the frenzy's duration are both cached, so
            # the slashes spread evenly across it: the first on the cast
            # boundary, the rest one share of the duration apart.  Royal
            # Maelstrom only slashes — nothing in the cached text controls
            # what it damages.
            DamagePart(
                "physical",
                per_slash,
                count=slashes,
                crit_effectiveness=1.0,
                time_offset=0.0,
                hit_interval=E_DURATION_SECONDS / slashes,
                cc_kind="none",
            ),
        ),
        # Each slash applies item on-hits at 12-24%, interpolated by the
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
    """R active: Void Coral explosion (true damage + 20% missing health),
    plus the True Form stat buff when the ``true_form`` option is on."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    missing = missing_hp_fraction(ctx)
    max_hp = ctx.target_stat("target_max_health")

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
        # One explosion at the Coral ("creates an explosion at the location
        # to deal true damage to enemies within") — one part, one hit,
        # which carries R's reviewed slow into the event ledger.
        event_order_certified="single_hit",
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
    """R passive: ramping true damage on every attack and Q/E on-hit.

    Hit k deals k x (2/4/6 + 3% bonus AD) — stacks accumulate on one target
    and expire after five seconds without a hit. Emitted as a ramping on-hit;
    the fight engine owns the hit sequence, and each carrier's on-hit
    modifier (100% autos/Q, 12-24% E) applies to that instance.
    """
    ability = ctx.ability("R")
    if ability is None:
        return None
    rank = ctx.rank_for("R")
    if rank < 1:
        return None

    per_stack = extract_named(ability, "Bonus True Damage", rank, ctx.stats, ctx.target)
    name = "Endless Banquet (ramping on-hit)"
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
            "applies_on_ability_on_hits": True,
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
    "Passive 20% temporary attack speed is treated as active throughout the "
    "selected combo because every ability cast refreshes its three seconds",
    "Patch 26.15 restored basic attacks and crits to 100% damage; on-hit "
    "riders use Bel'Veth's sourced 100% modifier (75% removed in 26.15)",
    "Q applies item on-hit effects once per dash at 100%; E once per slash "
    "at 12-24% (interpolated by target missing health) — each is that "
    "ability's own modifier, independent of the passive's auto-only modifier",
    "R's ramping true-damage passive applies on every basic attack and on "
    "Q/E on-hit instance, using the carrier's own on-hit effectiveness",
    "Q/E applications trigger on-hit item damage (Nashor's, Wit's End, "
    "BotRK, ...) and count on the shared on-hit stack counters "
    "(Kraken/Hullbreaker) — a proc fires at the effectiveness of the hit "
    "that landed it",
    "E slashes are real attacks (wiki: on-hit, on-attack, and ability "
    "effects) and advance on-attack cadences: Guinsoo's phantom-hit "
    "counter (a slash-fired phantom re-applies item on-hits at the "
    "slash's 12-24%); Q is on-hit only and never advances on-attack "
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
    "Target missing health defaults to 50% (shared option driving E slash "
    "damage, E on-hit effectiveness, and R explosion)",
    "Q per-direction dash cooldown (16-12s) is wiki prose (the JSON holds "
    "the 1s cast lockout); its bonus-AS haste conversion (0.25 haste per "
    "1% bonus AS) is not modeled",
    "Monster/minion-only damage components skipped (champion combat calculator)",
    "Void Remora pets, R heal, and E damage reduction/lifesteal remain "
    "outside the combat ledger; W knock-up downtime is sourced and counted, "
    "while its slow remains utility",
    "True Form's total-AS increase multiplies final attack speed and does "
    "not count as bonus AS for E's slash count",
    "'Based on level' scalings read the JSON per-level arrays (which "
    "extend past level 18); a shorter array would clamp at its last entry",
]

SOURCES = load_champion_sources("Bel'Veth")

SLOTS = {
    "P": _death_in_lavender,
    "Q": _void_surge,
    # One tail slam on one target, so one part and one hit — the
    # certification that carries W's reviewed knockup into the ledger,
    # with the interval read off the cached "Knock Up Duration" row
    # (0.6-1.0s) rather than left unsourced.
    "W": with_control(
        simple_damage(
            attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
        ),
        kind="knockup",
        duration_attr="Knock Up Duration",
    ),
    "E": _royal_maelstrom,
    "R": _endless_banquet,
    "R_onhit": _endless_banquet_onhit,
}

# Reviewed crowd control, read from the cached kit.  W (Above and Below)
# "deals magic damage to enemies hit, knocks them up for a duration, and
# slows them by 30% for 2 seconds" — the immobilize is the narrower answer
# of the two.  R (Endless Banquet) consumes the Coral "slowing nearby
# enemies by 25% : 96% (based on seconds elapsed) for the duration" before
# its explosion.
#
# E's slashes are control-free ("Royal Maelstrom" only slashes) and now
# ride the cached schedule their own row states — a count "over the
# duration" of a 1.5-second frenzy — so that review is authored on the part
# in ``_royal_maelstrom``.
#
# Q stays UNREVIEWED, so this kit keeps the coarse control-armed scan.  It
# too is control-free in the cache — Void Surge "deal[s] physical damage to
# enemies she passes through" — but its row is the four cardinal dashes in
# one part and the cache spaces them with nothing but "incurs a cooldown
# between casts", a cooldown it never names.
MODULE_CC = {"W": "knockup", "R": "slow"}

parse_abilities = build_parser(SLOTS, "Bel'Veth", cc_kinds=MODULE_CC)
