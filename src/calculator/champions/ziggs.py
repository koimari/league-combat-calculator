"""Ziggs — slot map for the archetype engine.

Why each slot is non-generic:
- P (Short Fuse) is invisible to the generic path: its JSON leveling
  carries ONLY the per-level base values (no AP modifier at all), so the
  50% AP ratio is hardcoded here from the wiki, and the proc count is a
  champion option (``passive_procs``) — its 12s cooldown is refunded
  4/5/6s per ability cast, so uptime depends on the rotation. Row 0 of
  the "Per-Level Scaling" pair is vs champions; row 1 (the 175%
  vs-structures multiple) is deliberately ignored.
- E (Hexplosive Minefield) is multi-hit: 1 full mine plus
  ``mines_hit - 1`` at the "Reduced Damage per Mine" values, clamped at
  the "Maximum Total Magic Damage" row. The generic path counts one
  mine.
- R (Mega Inferno Bomb) is a sweet-spot toggle (``r_sweet_spot``):
  "Epicenter Magic Damage" vs the outer-ring "Reduced Damage" row.
- Q and W are plain reads, pinned to their exact "Magic Damage"
  attribute so W's turret-only "Demolition Threshold" row can never win.

All numeric values are read from the champion JSON data except the
Short Fuse AP ratio (see HARDCODED below).
"""

from typing import Any

from .engine import SlotCtx, build_parser
from .slotlib import (
    by_option,
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
    proc_damage,
    simple_damage,
)

# HARDCODED: verify on patch updates — the wiki-scraped JSON stores
# Short Fuse's per-level base but drops its AP modifier entirely.
# https://wiki.leagueoflegends.com/en-us/Ziggs (Short Fuse: 50% AP)
SHORT_FUSE_AP_RATIO = 0.5


def _short_fuse_damage(ctx: SlotCtx, ability: dict[str, Any]) -> float:
    """One Short Fuse proc: per-level JSON base + hardcoded 50% AP."""
    base = extract_value(ability, "Per-Level Scaling", ctx.level)
    return base + SHORT_FUSE_AP_RATIO * ctx.stats.get("ability_power", 0.0)


def _hexplosive_minefield(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: 1 full mine + (mines_hit - 1) reduced mines, capped by JSON."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    mines = max(1, int(ctx.options.get("mines_hit", 4)))
    full = extract_named(ability, "Magic Damage per Mine", rank, ctx.stats, ctx.target)
    reduced = extract_named(
        ability, "Reduced Damage per Mine", rank, ctx.stats, ctx.target
    )
    cap = extract_named(
        ability, "Maximum Total Magic Damage", rank, ctx.stats, ctx.target
    )
    total = min(full + (mines - 1) * reduced, cap)
    return damage_entry(
        ability.get("name", "Hexplosive Minefield"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )


OPTIONS = [
    {
        "key": "passive_procs",
        "type": "int",
        "default": 2,
        "label": "Short Fuse procs",
        "min": 0,
        "max": 10,
    },
    {
        "key": "mines_hit",
        "type": "int",
        "default": 4,
        "label": "E mines hit",
        "min": 1,
        "max": 11,
    },
    {
        "key": "r_sweet_spot",
        "type": "bool",
        "default": True,
        "label": "R hits epicenter (sweet spot)",
    },
]

ASSUMPTIONS = [
    "Short Fuse structure bonus (175% damage, 87.5% AP vs turrets) not "
    "modeled — champion-fight calculator",
    "Short Fuse proc count is user-set (default 2); its per-ability-cast "
    "cooldown refund (4/5/6s) is not simulated tick-by-tick",
    "Q bounces don't change damage; single explosion assumed to hit",
    "W turret-execute threshold (Demolition) not modeled — turrets only",
    "E slow and W knockback are utility, no damage contribution",
    "Enemy hits 4 E mines by default (1 full + 3 reduced); configurable",
    "R defaults to epicenter (sweet spot) damage; toggle for outer ring",
]

SLOTS = {
    "Q": simple_damage(attr="Magic Damage", dmg_type="magic"),
    "W": simple_damage(attr="Magic Damage", dmg_type="magic"),
    "E": _hexplosive_minefield,
    "R": by_option(
        "r_sweet_spot",
        {
            True: simple_damage(attr="Epicenter Magic Damage", dmg_type="magic"),
            False: simple_damage(attr="Reduced Damage", dmg_type="magic"),
        },
        default=True,
    ),
    "P": proc_damage(
        per_proc=_short_fuse_damage,
        dmg_type="magic",
        count_option="passive_procs",
        default_count=2,
    ),
}

parse_abilities = build_parser(SLOTS, "Ziggs")
