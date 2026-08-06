"""Vel'Koz — slot map for the archetype engine (E3 stack systems).

Why each slot is non-generic:
- P (Organic Deconstruction) is the stack system: Vel'Koz's abilities
  apply Deconstruction stacks (max 3, 7s, refreshing; basic attacks
  refresh but do not add). The third stack consumes all stacks to deal
  level-scaled TRUE damage ("Per-Level Scaling" 35-197.06 array) plus
  60% AP (prose ratio). The rotation's damaging abilities (Q, W x2
  hits, E, R ticks) always exceed three applications, so the proc is
  priced once per fight — the conservative floor (Brand's Blaze
  once-per-rotation precedent); R's repeated 0.7s Deconstruction
  applications could proc more in a long channel.
- Q (Plasma Fission), W (Void Rift), E (Tectonic Disruption) are plain
  attribute reads: W uses "Total Magic Damage" (both rift hits — the
  classifier would pick only the first).
- R (Life Form Disintegration Ray) keeps the reviewed packet's
  per-tick pricing (one 0.2s tick of "Damage Per Tick"); the full
  channel ("Maximum Damage" = 13 ticks) and the Researched
  true-damage conversion are documented boundaries, not modeled.
"""

import json
from pathlib import Path
from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_named,
    simple_damage,
)

# HARDCODED: verify on patch updates — the proc's 60% AP ratio exists
# only in the passive's description prose; the leveling array carries
# only the flat level values.
_PROC_AP_RATIO = 0.6  # "35 : 197.06 (based on level) (+ 60% AP)"
_PROC_STACKS = 3
_PROC_LEVELING_ATTR = "Per-Level Scaling"


def _organic_deconstruction(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: one 3-stack true-damage consume per fight, when 3+ abilities land."""
    ability = ctx.ability()
    if ability is None:
        return None

    # Deconstruction stacks come from damaging abilities (Q, W's two
    # rift hits, E, R). Any full rotation applies 3+, so a fight with
    # the rotation present prices one proc.
    applications = sum(1 for slot in ("Q", "W", "E", "R") if slot in ctx.results)
    if applications < _PROC_STACKS:
        return None

    flat = extract_named(ability, _PROC_LEVELING_ATTR, ctx.level, ctx.stats, ctx.target)
    ap = ctx.stats.get("ability_power", 0.0)
    total = flat + _PROC_AP_RATIO * ap
    return {
        "name": ability.get("name", "Organic Deconstruction"),
        "rank": ctx.level,
        "cooldown": 0.0,
        "damage_type": "true",
        "total_raw": total,
        "parts": (DamagePart("true", total),),
        "proc_count": 1,
        "detail": (
            f"3 Deconstruction stacks consumed at level {ctx.level} "
            f"({flat:.2f} + {_PROC_AP_RATIO * 100:g}% AP)"
        ),
    }


OPTIONS: list[dict[str, Any]] = []

ASSUMPTIONS = [
    "Organic Deconstruction procs once per fight: the rotation's "
    "damaging abilities apply 3+ stacks (Q, W's two rift hits, E, and R "
    "ticks), so the conservative floor is one 3-stack consume per fight",
    "Proc damage = the 'Per-Level Scaling' array value at the champion's "
    "level (35 at 1 up to 197.06 at 19+) + 60% AP (prose ratio, module "
    "constant)",
    "R keeps the reviewed packet's single-tick pricing; the full "
    "13-tick channel (the 'Maximum Damage' row) and the Researched "
    "true-damage conversion are not modeled",
    "The Researched mark (applying 3 stacks marks the target for 7s, "
    "making R deal true damage) is not modeled — R stays magic",
    "Q slow, W sight, and E knockup/stun are CC/utility only",
]

SLOTS = {
    "Q": simple_damage(attr="Magic Damage", dmg_type="magic"),
    "W": simple_damage(attr="Total Magic Damage", dmg_type="magic"),
    "E": simple_damage(attr="Magic Damage", dmg_type="magic"),
    "R": simple_damage(attr="Damage Per Tick", dmg_type="magic"),
    "P": _organic_deconstruction,  # after the damage slots: reads their emissions
}

parse_abilities = build_parser(SLOTS, "Vel'Koz")

MODULE_COVERAGE = {slot: "modeled" for slot in "PQWER"}
REVIEW_STATUS = "reviewed_module"

_SOURCE_PATH = (
    Path(__file__).resolve().parents[3] / "static" / "cp10_batch_09_sources.json"
)


def _load_sources(name: str) -> list[dict[str, object]]:
    try:
        payload = json.loads(_SOURCE_PATH.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"CP10.9 source receipts are unavailable: {_SOURCE_PATH}"
        ) from exc
    rows = payload.get(name) if isinstance(payload, dict) else None
    if (
        not isinstance(rows, list)
        or len(rows) != 6
        or any(not isinstance(row, dict) or not all(row.values()) for row in rows)
    ):
        raise RuntimeError(f"CP10.9 source receipts for {name!r} are incomplete")
    return rows


SOURCES = _load_sources("Vel'Koz")
