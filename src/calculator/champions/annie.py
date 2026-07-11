"""Annie — slot map for the archetype engine.

Why each slot is non-generic:
- R (Summon: Tibbers) is a custom BUFF-phase slot with three parts:
  a % magic-penetration stat buff (mutated into ``ctx.stats`` and
  emitted as ``stat_buff`` — BUFF phase guarantees Q/W parse after it),
  the initial burst ("Initial Magic Damage"), and the Tibbers aura,
  whose numbers are NOT in the JSON (pet stats are not scraped from the
  wiki) — see the quarantined constants below.
- P (Pyromania) is a stun-only passive shown as a zero-damage row under
  the literal "P" results key (the pre-engine UI shape), so a custom
  slot fn writes it into ``ctx.results`` directly instead of using the
  engine's "P" -> "passive" mapping.
- E (Molten Shield) is shield/retaliation only — a zero-damage
  ``utility`` placeholder.
- Q/W are plain "Magic Damage" attribute reads.

All numeric values are read from the champion JSON data except the
Tibbers aura constants.
"""

from typing import Any

from .engine import BUFF, SlotCtx, build_parser
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
    simple_damage,
    utility,
)

# HARDCODED: verify on patch updates — pet stats are not in the JSON.
# Tibbers aura tick damage comes from the LoL Wiki directly:
# https://wiki.leagueoflegends.com/en-us/Annie
# Aura ticks every 0.25 seconds.
# Base damage per tick: 2 / 3 / 4 at R rank 1/2/3.
# AP ratio per tick: 1% AP (0.01).
_TIBBERS_AURA_BASE_PER_TICK = [2.0, 3.0, 4.0]
_TIBBERS_AURA_AP_RATIO_PER_TICK = 0.01
_TIBBERS_AURA_TICK_INTERVAL = 0.25


def _summon_tibbers(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: % magic-pen stat buff + initial burst + Tibbers aura.

    Supports the ``tibbers_aura_seconds`` option (default 5.0) — how
    many seconds of aura damage to include in the R total.
    """
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    # R passive: % magic penetration, applied to the shared stats
    # context (BUFF phase runs before every damage slot) and reported
    # via stat_buff for the fight engine.
    magic_pen = extract_value(ability, "Magic Penetration", rank)
    ctx.stats["magic_penetration_percent"] = (
        ctx.stats.get("magic_penetration_percent", 0.0) + magic_pen
    )

    burst = extract_named(ability, "Initial Magic Damage", rank, ctx.stats)
    cooldown = extract_cooldown(ability, rank)

    # Tibbers aura damage (not in JSON — wiki constants above).
    aura_seconds = float(ctx.options.get("tibbers_aura_seconds", 5.0))
    aura_base = _TIBBERS_AURA_BASE_PER_TICK[
        min(rank - 1, len(_TIBBERS_AURA_BASE_PER_TICK) - 1)
    ]
    aura_per_tick = (
        aura_base + _TIBBERS_AURA_AP_RATIO_PER_TICK * ctx.stats["ability_power"]
    )
    total_ticks = aura_seconds / _TIBBERS_AURA_TICK_INTERVAL
    aura_total = aura_per_tick * total_ticks

    total = burst + aura_total
    return {
        "name": ability.get("name", "Summon: Tibbers"),
        "rank": rank,
        "cooldown": cooldown,
        "damage_type": "magic",
        "magic_damage": total,
        "total_raw": total,
        "initial_burst": burst,
        "tibbers_aura": {
            "damage_per_tick": aura_per_tick,
            "total_ticks": total_ticks,
            "magic_damage": aura_total,
        },
        "stat_buff": {
            "magic_penetration_percent": magic_pen,
        },
    }


_summon_tibbers.phase = BUFF


def _pyromania_placeholder(ctx: SlotCtx) -> None:
    """P: stun-only passive — zero-damage display row under key "P".

    Written into ``ctx.results`` directly because the engine maps a
    returned P-slot entry to the "passive" key, and this row's home in
    the emitted shape is the literal "P".
    """
    ability = ctx.ability()
    if ability is not None:
        ctx.results["P"] = damage_entry(
            ability.get("name", "Pyromania"), 0, 0.0, 0.0, "magic"
        )


OPTIONS = [
    {
        "key": "tibbers_aura_seconds",
        "type": "float",
        "default": 5.0,
        "label": "Tibbers aura duration (seconds)",
        "min": 0,
        "max": 45,
        "step": 0.5,
    },
]

ASSUMPTIONS = [
    "R magic penetration passive is always active",
    "Tibbers auto-attack damage is not modeled (positioning-dependent)",
    "E retaliation damage is not modeled (requires enemies to hit Annie)",
    "Tibbers aura defaults to 5 seconds of damage",
]

SLOTS = {
    "R": _summon_tibbers,
    "P": _pyromania_placeholder,
    "Q": simple_damage(attr="Magic Damage", dmg_type="magic"),
    "W": simple_damage(attr="Magic Damage", dmg_type="magic"),
    "E": utility(dmg_type="magic"),
}

parse_abilities = build_parser(SLOTS, "Annie")
