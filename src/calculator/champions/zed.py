"""Zed — E5-1 corrected slot map for the archetype engine.

Why each slot is non-generic:

- R (Death Mark) is a damage-storage mechanic, not a flat hit: the wiki
  leveling row is "Physical Damage: 100% AD (+ 25 / 40 / 55% of damage
  stored)".  The previous wiki_attribute read resolved only the first
  modifier (100% AD) and silently dropped the stored-damage term (the
  "% of damage stored" unit is not a stat scaling), pricing the mark as
  a flat ~AD hit.  The corrected packet reads BOTH modifiers: the mark
  detonates for 100% AD plus 25 / 40 / 55% of the pre-mitigation damage
  Zed dealt to the target during the mark.  The fight model's one
  rotation prices the stored pool as the pre-mitigation raw spell damage
  of the kit's damaging abilities (Q + E, read from ``ctx.results``);
  basic attacks and Shadow copies are not tracked in the ability parse.
  The detonation lands 3 seconds after the cast ("renders the target
  Marked for Death for 3 seconds ... detonating at the end of the
  duration").
- Q (Razor Shuriken) prices one enemy-champion hit (80 / 120 / 160 /
  200 / 240 + 100% bonus AD); the 60%-reduced second-target branch is
  not the single-target model.
- E (Shadow Slash) is a plain "Physical Damage" read (70 / 92.5 / 115 /
  137.5 / 160 + 70% bonus AD).
- P (Contempt for the Weak) and W (Living Shadow) are explicit
  no-damage slots.

All numeric values are read from the champion JSON data; nothing is
hardcoded.
"""

from typing import Any

from .engine import SlotCtx, build_parser
from .source_receipts import load_champion_sources
from .slotlib import (
    extract_cooldown,
    extract_value,
    simple_damage,
)
from ..ability_spec import DamagePart

# Death Mark detonates at the end of its 3-second mark (wiki prose:
# "renders the target Marked for Death for 3 seconds", "detonating at
# the end of the duration").
_DEATH_MARK_DETONATION_DELAY = 3.0


def _no_damage(slot: str, reason: str):
    """Emit an explicit zero-damage entry for a non-damaging slot."""

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        ability = ctx.ability()
        if ability is None:
            return None
        return {
            "name": ability.get("name", f"Ability {slot}"),
            "rank": ctx.rank_for(),
            "cooldown": 0.0,
            "damage_type": "magic",
            "total_raw": 0.0,
            "parts": (),
            "detail": reason,
        }

    parse.phase = "damage"
    return parse


def _death_mark(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: 100% AD + 25/40/55% of the mark's stored pre-mitigation damage."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    # Leveling row "Physical Damage": modifier 0 = 100 (% AD), modifier 1
    # = 25 / 40 / 55 (% of damage stored).  Read each modifier's raw value
    # directly; the "% AD" unit resolves 100 -> 1.0 x total AD, while
    # "% of damage stored" has no stat the scaling layer can resolve.
    ad_percent = extract_value(ability, "Physical Damage", rank, 0)
    stored_percent = extract_value(ability, "Physical Damage", rank, 1)
    ad_damage = (ad_percent / 100.0) * float(ctx.stats.get("attack_damage", 0.0))

    # The stored pool: pre-mitigation raw spell damage the fight rotation
    # prices for the kit's damaging abilities (Q + E).  R is evaluated
    # after Q/E in the slot map, so their entries are already in
    # ``ctx.results`` (the engine guarantees cross-slot reads within a
    # phase for later-listed slots).
    stored_pool = 0.0
    for slot in ("Q", "E"):
        entry = ctx.results.get(slot)
        if isinstance(entry, dict):
            stored_pool += float(entry.get("total_raw", 0.0) or 0.0)
    stored_damage = (stored_percent / 100.0) * stored_pool

    total = ad_damage + stored_damage
    entry = {
        "name": ability.get("name", "Death Mark"),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "physical",
        "total_raw": total,
        "parts": (
            DamagePart(
                "physical",
                total,
                time_offset=_DEATH_MARK_DETONATION_DELAY,
            ),
        ),
        "detail": (
            f"100% AD ({ad_damage:.2f}) + {stored_percent:g}% of stored "
            f"pre-mitigation spell damage ({stored_damage:.2f}); detonates "
            "3s after the mark"
        ),
    }
    return entry


ASSUMPTIONS = [
    "R (Death Mark) stores the fight rotation's pre-mitigation spell "
    "damage (Q + E raw totals); basic attacks and Shadow copies are not "
    "tracked in the ability parse, so they are excluded from the stored "
    "pool.",
    "The mark detonates 3 seconds after cast ('Marked for Death for 3 "
    "seconds ... detonating at the end of the duration').",
    "Q prices one enemy-champion hit; the 60%-reduced beyond-first-target "
    "branch is not the single-target model.",
    "P and W deal no enemy damage and are explicit no-damage slots.",
]

SOURCES = list(load_champion_sources("Zed"))

SLOTS = {
    "P": _no_damage(
        "P",
        "Contempt for the Weak is a % max-HP on-hit rider on basic attacks; "
        "no separate enemy-damage formula is priced for the passive slot.",
    ),
    "Q": simple_damage(attr="Physical Damage", dmg_type="physical"),
    "W": _no_damage(
        "W",
        "Living Shadow is a shadow/utility placement; no enemy damage.",
    ),
    "E": simple_damage(attr="Physical Damage", dmg_type="physical"),
    "R": _death_mark,
}

MODULE_COVERAGE = {
    "P": "no_damage",
    "Q": "modeled",
    "W": "no_damage",
    "E": "modeled",
    "R": "modeled",
}

OPTIONS: list[dict[str, Any]] = []

parse_abilities = build_parser(SLOTS, "Zed")
REVIEW_STATUS = "reviewed_module"
