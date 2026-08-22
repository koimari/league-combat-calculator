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
  one damage row is emitted; the Shield Strength row feeds the
  ally-support scanner, which grants the self shield at the cast
  (E8c).
- R (Emperor's Divide) pins "Magic Damage"; effect[0] carries geometry
  rows ("Width" with units of " soldiers") that must never parse as
  damage or scaling values.

P is wired nowhere: it carries ``kind: "no_damage"`` in MODULE_COVERAGE and
in the pinned reviewed packet (static/reviewed-packets.json), and
``parse_champion_abilities`` emits no passive key for Azir at all, so the
fight ledger never invents an enemy hit for it.
"""

from typing import Any

from .engine import SlotCtx, build_parser
from .slotlib import extract_cooldown, extract_value, simple_damage
from .source_receipts import load_champion_sources
from .inputs import bool_option, int_option
from .module_contract import coverage

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

    All three are modifiers of the single "Magic Damage" leveling entry.
    """
    flat_level = extract_value(ability, "Magic Damage", level, modifier_index=0)
    rank_base = extract_value(ability, "Magic Damage", rank, modifier_index=1)
    ap_ratio = extract_value(ability, "Magic Damage", rank, modifier_index=2)
    return flat_level + rank_base + ap_ratio / 100.0 * ability_power


def _arise(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: zero-damage entry carrying the Sand Soldier auto replacement."""
    if not bool(ctx.options.get("soldier_autos", True)):
        return None  # Azir autos normally (physical, crits, full on-hit)
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked

    per_soldier = _soldier_attack_damage(
        ability, rank, ctx.level, ctx.stat("ability_power")
    )
    soldiers = max(1, int(ctx.option("soldier_count")))
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
    int_option(
        "soldier_count",
        1,
        minimum=1,
        maximum=3,
        label="Sand Soldiers attacking the target",
    ),
    bool_option(
        "soldier_autos", True, label="Replace basic attacks with Sand Soldier attacks"
    ),
]

ASSUMPTIONS = [
    "Passive Sun Disc not modeled (requires a destroyed tower; separate "
    "entity) (MODULE_COVERAGE: no_damage, not out_of_scope)",
    "Single-target: soldier spear line's reduced damage to targets beyond "
    "the closest (20-100% by level) not modeled",
    "Q deals one instance regardless of soldier count (in-game rule)",
    "E (Shifting Sands) shields Azir for the sourced 70/110/150/190/230 "
    "+ 60% AP for 1.5s at the cast; the shield is emitted by the "
    "ally-support scanner from the cached Shield Strength row (untimed "
    "packet — the 1.5s expiry is a documented boundary of that "
    "interface) and absorbs incoming damage in the participant ledger",
    "Soldier attacks use Azir's attack speed; they cannot crit, apply no "
    "lifesteal, and apply on-hit effects at 50% effectiveness to the "
    "primary target",
    "Additional soldiers' 25% instances apply no on-hit effects",
    "All per-attack and proc-style item effects (on-hit, spellblade, "
    "energized, stack-counter procs like Kraken Slayer) apply at 50% "
    "effectiveness on soldier attacks; Sundered Sky does not apply at all",
]

SLOTS = {
    # Each of the three lands its damage once on a given target — Q states
    # it outright ("Enemies hit by subsequent soldiers take no additional
    # damage or slow"), E damages "enemies within his path" as it passes,
    # and R's phalanx impacts once — so all three certify the cast boundary.
    "Q": simple_damage(
        attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
    ),
    "W": _arise,
    "E": simple_damage(
        attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
    ),
    "R": simple_damage(
        attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
    ),
}

# Cached kit review.  Q slows enemies the soldiers pass through "by 25% for
# 1 second"; E only deals damage along the dash (its shield is Azir's own);
# R's phalanx knocks enemies "away over 1 second to a line 650 units in
# front of Azir".  W summons a soldier and emits no damage row of its own.
MODULE_CC = {"Q": "slow", "E": "none", "R": "knockback"}

parse_abilities = build_parser(SLOTS, "Azir", cc_kinds=MODULE_CC)


SOURCES = load_champion_sources("Azir")

# P is not absent for want of a parser: Sun Disc is a separate destroyed-tower
# entity that deals no enemy damage, which the derived map cannot say.
MODULE_COVERAGE = coverage(no_damage="P")
