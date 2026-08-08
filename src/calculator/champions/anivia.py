"""Anivia — slot map for the archetype engine.

Why each slot is non-generic:
- Q (Flash Frost) must read "Total Magic Damage" (pass-through +
  detonation combined) — an attribute override, not a classifier pick.
- E (Frostbite) must read "Enhanced Damage" (target assumed Chilled).
- R (Glacial Storm) is a two-phase toggle DoT: the first 1.5 s (3 ticks
  at 0.5 s) deal the initial per-tick damage, everything after deals the
  empowered value. Duration comes from the ``r_duration`` option
  (default 5 s, floored at 1.5 s so the initial phase always completes),
  and the cooldown is pinned to 999 s so the fight engine casts it
  exactly once per fight.
- W (utility wall) and the passive (resurrection) deal no damage and are
  deliberately absent from the slot map.

All numeric values are read from the champion JSON data; nothing is
hardcoded.
"""

from typing import Any

from .engine import SlotCtx, build_parser
from .slotlib import damage_entry, extract_named, simple_damage


def _glacial_storm(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: three initial half-second ticks, then empowered ticks."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    duration = max(float(ctx.options.get("r_duration", 5.0)), 1.5)
    total_ticks = int(duration / 0.5)
    initial_ticks = min(3, total_ticks)
    empowered_ticks = total_ticks - initial_ticks
    initial = extract_named(
        ability, "Magic Damage per Tick", rank, ctx.stats, ctx.target
    )
    empowered = extract_named(
        ability, "Empowered Damage per Tick", rank, ctx.stats, ctx.target
    )
    total = initial_ticks * initial + empowered_ticks * empowered
    return damage_entry(
        ability.get("name", "Glacial Storm"), rank, 999.0, total, "magic"
    )


OPTIONS = [
    {
        "key": "r_duration",
        "type": "float",
        "default": 5.0,
        "label": "R duration (seconds)",
        "min": 1.5,
        "max": 30,
        "step": 0.5,
    },
]

# E8d: sourced Rebirth revive values.  The cached passive prose (data/
# champions.json, Anivia P Rebirth) is the authoritative source: "Periodically,
# upon taking fatal damage, Anivia enters resurrection for 6 seconds and
# restores all of her health. ... If Anivia remains alive by the end of the
# duration, she is revived with her current health."  The CDragon live-game
# description agrees ("reborn with full health").  The engine's revive state
# transition consumes ``StartingDefenses.revive_*`` fields, so the module
# exposes the sourced revive contract here and the shared defense resolver
# wires it in per champion.
REVIVE_DELAY_SECONDS = 6.0
REVIVE_COOLDOWN_SECONDS = 240.0
REVIVE_MAX_HEALTH_RATIO = 1.0  # "restores all of her health"


def starting_revive_defense(level: int, stats: dict[str, float]) -> dict[str, float]:
    """Return Anivia's sourced Rebirth revive fields for StartingDefenses.

    The passive revives with full maximum health after the six-second
    resurrection window on the cached 240-second cooldown.
    """
    return {
        "revive_health_amount": float(stats.get("health", 0.0))
        * REVIVE_MAX_HEALTH_RATIO,
        "revive_delay": REVIVE_DELAY_SECONDS,
        "revive_cooldown": REVIVE_COOLDOWN_SECONDS,
    }


ASSUMPTIONS = [
    "Q hits both pass-through and detonation (total damage used)",
    "E target is always Chilled (empowered damage used)",
    "R first 1.5s uses initial tick damage, remaining uses fully-formed tick damage",
    "W skipped (utility wall, no damage)",
    "P (Rebirth) is modeled as the sourced revive state: full maximum health "
    "after a 6s resurrection on a 240s cooldown (cached passive prose).",
]

SLOTS = {
    "Q": simple_damage(attr="Total Magic Damage", dmg_type="magic"),
    "E": simple_damage(attr="Enhanced Damage", dmg_type="magic"),
    "R": _glacial_storm,
}

parse_abilities = build_parser(SLOTS, "Anivia")


# Authoritative review metadata (issue #161).
SOURCES = [
    {
        "label": "Local League Wiki cache",
        "url": "https://wiki.leagueoflegends.com/en-us/Anivia",
        "revision_id": 3891994,
        "revision_timestamp": "2025-05-01T05:31:01Z",
    }
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in SLOTS else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
