"""Azir — slot map for the archetype engine.

Why each slot is non-generic:
- P (Shurima's Legacy) is deliberately absent: it raises a Sun Disc
  turret from a destroyed enemy tower — a separate entity with its own
  HP and decay, out of scope for a target-dummy fight. The JSON also
  has zero leveling data for it and misparses its damageType as
  PHYSICAL (it deals magic). Skipped, never hardcoded.
- Q (Conquering Sands) is a pinned attribute read: one damage instance
  per cast REGARDLESS of soldier count (in-game rule), so it must never
  read the ``soldier_count`` option.
- W (Arise!) is the custom centerpiece. The JSON mixes an 18-value
  per-level modifier with two 5-value per-rank modifiers inside ONE
  "Magic Damage" leveling entry — no generic extractor can combine
  them. The soldier damage is emitted as an ``auto_attack_override``
  that REPLACES Azir's autos: magic damage on his own attack timer,
  cannot crit, applies on-hit and proc-style item effects (spellblade,
  energized, Kraken-style stack procs) at 50% effectiveness — except
  Sundered Sky, which does not apply at all — and +25% damage per
  soldier past the first (those extra instances apply no on-hit). The W entry itself deals no direct damage — all soldier
  damage rides the auto stream, never a cast row too (no double
  count). The "Per-Level Scaling" leveling entry (20-100%) is the
  reduced damage to targets BEYOND the closest in the spear line —
  single-target sim ignores it; it must never become a damage row.
  W stocks 2 charges: rechargeRate is the cooldown, cast counts are
  never pre-multiplied (Amumu charge pattern).
- E (Shifting Sands) pins the "Magic Damage" attribute because the
  JSON duplicates identical values under "Shield Strength" — exactly
  one damage row is emitted (the shield is not modeled).
- R (Emperor's Divide) pins "Magic Damage"; effect[0] carries geometry
  rows ("Width" with units of " soldiers") that must never parse as
  damage or scaling values.
"""

from typing import Any

from .engine import SlotCtx, build_parser
from .slotlib import extract_cooldown, extract_value, simple_damage

# HARDCODED: wiki-prose soldier mechanics with no JSON home — verify on
# patch updates. https://wiki.leagueoflegends.com/en-us/Azir
SOLDIER_EXTRA_DAMAGE = 0.25  # each soldier past the first adds 25% damage
SOLDIER_ON_HIT_EFFECTIVENESS = 0.5  # on-hit items at 50% on soldier attacks


def _soldier_attack_damage(
    ability: dict[str, Any],
    rank: int,
    level: int,
    ability_power: float,
) -> float:
    """One Sand Soldier attack: per-level flat + per-rank base + AP ratio.

    The JSON stores all three as modifiers of the single "Magic Damage"
    leveling entry: modifier 0 is an 18-value per-level array (0-72
    linear over levels 1-18), modifiers 1-2 are 5-value per-rank arrays
    (base damage and % AP ratio).
    """
    flat_level = extract_value(ability, "Magic Damage", level, modifier_index=0)
    rank_base = extract_value(ability, "Magic Damage", rank, modifier_index=1)
    ap_ratio = extract_value(ability, "Magic Damage", rank, modifier_index=2)
    return flat_level + rank_base + ap_ratio / 100.0 * ability_power


def _arise(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: zero-damage entry carrying the Sand Soldier auto replacement."""
    if not bool(ctx.options.get("soldier_autos", True)):
        return None  # Azir autos normally (physical, crits, full on-hit)
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    per_soldier = _soldier_attack_damage(
        ability, rank, ctx.level, ctx.stats.get("ability_power", 0.0)
    )
    soldiers = max(1, int(ctx.options.get("soldier_count", 1)))
    per_attack = per_soldier * (1.0 + SOLDIER_EXTRA_DAMAGE * (soldiers - 1))

    # Charge ability: rechargeRate is the sustained-use cooldown (the
    # JSON cooldown field holds only the 1.5s inter-cast timer).
    rates = ability.get("rechargeRate") or []
    cooldown = (
        float(rates[min(rank - 1, len(rates) - 1)])
        if rates
        else extract_cooldown(ability, rank)
    )

    return {
        "name": ability.get("name", "Arise!"),
        "rank": rank,
        "cooldown": cooldown,
        "damage_type": "magic",
        "total_raw": 0.0,  # all soldier damage rides the auto stream
        "parts": (),
        "detail": (f"Soldier attacks replace autos: {per_attack:.0f} magic per attack"),
        "auto_attack_override": {
            "name": "Sand Soldier Attacks",
            "replace_raw": per_attack,
            "damage_type": "magic",
            "on_hit_effectiveness": SOLDIER_ON_HIT_EFFECTIVENESS,
        },
    }


OPTIONS: list[dict[str, Any]] = [
    {
        "key": "soldier_count",
        "type": "int",
        "default": 1,
        "min": 1,
        "max": 3,
        "label": "Sand Soldiers attacking the target",
    },
    {
        "key": "soldier_autos",
        "type": "bool",
        "default": True,
        "label": "Replace basic attacks with Sand Soldier attacks",
    },
]

ASSUMPTIONS = [
    "Passive Sun Disc not modeled (requires a destroyed tower; separate entity)",
    "Single-target: soldier spear line's reduced damage to targets beyond "
    "the closest (20-100% by level) not modeled",
    "Q deals one instance regardless of soldier count (in-game rule)",
    "E shield (70-230 +60% AP) not modeled; damage component only",
    "Soldier attacks use Azir's attack speed; they cannot crit, apply no "
    "lifesteal, and apply on-hit effects at 50% effectiveness to the "
    "primary target",
    "Additional soldiers' 25% instances apply no on-hit effects",
    "All per-attack and proc-style item effects (on-hit, spellblade, "
    "energized, stack-counter procs like Kraken Slayer) apply at 50% "
    "effectiveness on soldier attacks; Sundered Sky does not apply at all",
]

SLOTS = {
    "Q": simple_damage(attr="Magic Damage", dmg_type="magic"),
    "W": _arise,
    "E": simple_damage(attr="Magic Damage", dmg_type="magic"),
    "R": simple_damage(attr="Magic Damage", dmg_type="magic"),
}

parse_abilities = build_parser(SLOTS, "Azir")
