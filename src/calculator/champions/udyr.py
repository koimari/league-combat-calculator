"""Udyr — CP10.9 full-entry-reviewed packet module.

E1/E2: W Iron Mantle heal streams and R Wingborne Storm 8-tick total are
modeled (healing.py + this module's packet timing declaration); the W shield is
emitted by the ally-support scanner from the cached Shield Strength row.

P1-2 fix — Q (Wilding Claw) becomes a modeled ONHIT slot.  The stance
empowers the next ``q_empowered_attacks`` basic attacks (default 2,
wiki prose) with the sourced on-hit payload: the stance's "Bonus
Physical Damage" row (3% : 8% by rank of the target's maximum health +
3.5% per 100 bonus AD) plus the 4-second "Bonus Physical Damage
On-Hit" row (6 : 36 by rank + 20% bonus AD + 1% : 2% by rank of bonus
health).  With ``q_awaken`` (default False) the Awaken recast adds the
per-level "Max Health Damage" row (2% : 4.24% by level + 1.5% per 100
bonus AD + 0.1% per 100 bonus health) to the empowered attacks, and
each empowered attack's lightning chain is priced as 6 magic strikes at
the sourced 0.2-second cadence (per-strike row 1.5% : 3.18% by level +
0.6% per 100 AP of the target's maximum health; all six chain onto the
single target).

The cache's Q "Heal" row (40 : 174.12 by level) is the lightning
strike's minimum damage against MINIONS (wiki prose), not a self-heal;
the Awaken self-heal family is the W stance stream, which the healing
rule already models.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import ONHIT, SlotCtx, build_parser
from .packet_module import build_packet_module, repeat_damage_parser
from .slotlib import (
    ability_on_hit_entry,
    extract_named,
    find_named_leveling,
    resolve_scaling,
)

# HARDCODED: verify on patch updates — wiki Q prose, not JSON:
# the stance empowers the next two basic attacks; the Awaken lightning
# chain fires 6 strikes per empowered attack at 0.2-second intervals.
_Q_EMPOWERED_ATTACKS_DEFAULT = 2
_Q_LIGHTNING_STRIKES_PER_ATTACK = 6
_Q_LIGHTNING_HIT_INTERVAL = 0.2

PACKET_SHA256 = "468fd3bf2d2dd7e836b89c0ae6eff50d844990c0c03442f7f864a2032525dd9c"

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Udyr",
    PACKET_SHA256,
    assumption_overrides=(
        "Wingborne Storm prices all 8 blizzard ticks (Magic Damage per Tick "
        "x 8 == Total Magic Damage) at 0.5-second intervals over 4 seconds.",
    ),
    slot_parsers={
        "R": repeat_damage_parser(
            attr="Magic Damage per Tick",
            dmg_type="magic",
            count=8,
            time_offset=0.5,
            hit_interval=0.5,
            dot_duration=4.0,
        )
    },
)
PACKET_SPEC = SLOTS.packet_spec


def _target_max_health_percent(
    ability: dict[str, Any],
    attribute: str,
    level: int,
    stats: dict[str, float],
    target: dict[str, float],
    *,
    occurrence: int = 0,
) -> float:
    """Resolve a per-level '%' row as '% of the target's maximum health'.

    The scraper stored the Awaken rows' leading unit as bare "%" (the
    "of the target's maximum health" suffix was dropped), so the generic
    resolver prices them as flat.  This reads the row at champion level
    and resolves the leading modifier against the target's max health;
    the remaining modifiers ("% per 100 bonus AD"/"AP"/"bonus health")
    go through the ordinary scaling layer.
    """
    leveling = find_named_leveling(ability, attribute, occurrence)
    if leveling is None:
        raise ValueError(f"Udyr Q {attribute!r} leveling row is unavailable")
    total = 0.0
    index = min(max(level - 1, 0), 19)
    for modifier in leveling.get("modifiers", []):
        values = modifier.get("values", [])
        units = modifier.get("units", [])
        if not values:
            continue
        idx = min(index, len(values) - 1)
        value = float(values[idx])
        unit = units[idx] if idx < len(units) else ""
        stripped = unit.strip()
        if stripped == "%":
            total += value / 100.0 * float(target.get("target_max_health", 0.0))
        else:
            total += resolve_scaling(unit, value, stats, target)
    return total


def _wilding_claw(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: the stance's empowered-attack on-hit (+ Awaken rows)."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    awaken = bool(ctx.options.get("q_awaken", False))
    empowered = min(
        max(
            int(ctx.options.get("q_empowered_attacks", _Q_EMPOWERED_ATTACKS_DEFAULT)), 0
        ),
        _Q_EMPOWERED_ATTACKS_DEFAULT,
    )

    stance_bonus = extract_named(
        ability, "Bonus Physical Damage", rank, ctx.stats, ctx.target
    )
    on_hit_flat = extract_named(
        ability, "Bonus Physical Damage On-Hit", rank, ctx.stats, ctx.target
    )
    per_hit = stance_bonus + on_hit_flat
    detail = (
        f"Claw Stance: {empowered} empowered basic attack(s) at "
        f"Bonus Physical Damage ({stance_bonus:g}, % max health + 3.5% per "
        f"100 bonus AD) + Bonus Physical Damage On-Hit ({on_hit_flat:g}, "
        "flat + 20% bonus AD + % bonus health)"
    )

    parts: tuple[DamagePart, ...] = ()
    if awaken:
        max_hp_bonus = _target_max_health_percent(
            ability, "Max Health Damage", ctx.level, ctx.stats, ctx.target
        )
        per_hit += max_hp_bonus
        lightning_per_strike = _target_max_health_percent(
            ability,
            "Per-Level Scaling",
            ctx.level,
            ctx.stats,
            ctx.target,
            occurrence=1,
        )
        strikes = _Q_LIGHTNING_STRIKES_PER_ATTACK * empowered
        parts = (
            DamagePart(
                "magic",
                lightning_per_strike,
                count=strikes,
                time_offset=0.0,
                hit_interval=_Q_LIGHTNING_HIT_INTERVAL,
            ),
        )
        detail += (
            f"; Awaken adds Max Health Damage ({max_hp_bonus:g}, per-level "
            f"% max health) and the lightning chain: {strikes} magic "
            f"strikes at {_Q_LIGHTNING_HIT_INTERVAL:g}s intervals "
            f"({lightning_per_strike:g} each, all chained to the single target)"
        )

    entry = ability_on_hit_entry(
        ability.get("name", "Wilding Claw"),
        rank,
        "physical",
        {
            "name": "Wilding Claw (empowered attack)",
            "damage_per_hit": per_hit,
            "damage_type": "physical",
            "max_procs": empowered,
        },
        cooldown=0.0,
    )
    entry["parts"] = parts
    entry["total_raw"] = per_hit * empowered + sum(
        (part.amount or 0.0) * part.count for part in parts
    )
    entry["detail"] = detail
    return entry


_wilding_claw.phase = ONHIT

SLOTS = dict(SLOTS)
SLOTS["Q"] = _wilding_claw
parse_abilities = build_parser(SLOTS, "Udyr")

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "Q (Wilding Claw) empowers q_empowered_attacks (default 2) basic "
    "attacks with the sourced on-hit payload: Bonus Physical Damage "
    "(3% : 8% by rank of the target's maximum health + 3.5% per 100 bonus "
    "AD) plus the 4-second Bonus Physical Damage On-Hit (6 : 36 by rank + "
    "20% bonus AD + 1% : 2% by rank of bonus health).",
    "q_awaken (default False) adds the per-level Max Health Damage row "
    "(2% : 4.24% by level + 1.5% per 100 bonus AD + 0.1% per 100 bonus "
    "health) to the empowered attacks and prices each empowered attack's "
    "lightning chain as 6 magic strikes at the sourced 0.2s cadence "
    "(1.5% : 3.18% by level + 0.6% per 100 AP of the target's maximum "
    "health per strike; all six chain onto the single target).",
    "The cache's Q 'Heal' row (40 : 174.12 by level) is the lightning "
    "strike's minimum damage against minions, not a self-heal; the Awaken "
    "self-heal family is the W stance stream, which healing.py models.",
    "W (Iron Mantle) shield (Shield Strength 45 : 145 by rank + 50% bonus "
    "AD + 40% AP + 2% : 3.5% by rank maximum health) is emitted by the "
    "ally-support scanner at the W cast.",
]
OPTIONS.append(
    {
        "key": "q_awaken",
        "type": "bool",
        "default": False,
        "label": "Q Awaken recast (empowered attacks + lightning)",
    }
)
OPTIONS.append(
    {
        "key": "q_empowered_attacks",
        "type": "int",
        "default": _Q_EMPOWERED_ATTACKS_DEFAULT,
        "min": 0,
        "max": _Q_EMPOWERED_ATTACKS_DEFAULT,
        "label": "Q empowered basic attacks",
    }
)
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "R", "W"} else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
