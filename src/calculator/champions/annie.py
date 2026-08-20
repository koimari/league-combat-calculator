"""Annie — slot map for the archetype engine.

Why each slot is non-generic:
- R (Summon: Tibbers) is a custom BUFF-phase slot with three parts:
  a % magic-penetration stat buff (mutated into ``ctx.stats`` and
  emitted as ``stat_buff`` — BUFF phase guarantees Q/W parse after it),
  the initial burst ("Initial Magic Damage"), the Tibbers aura, and the
  Tibbers auto attacks.  The aura and auto-attack numbers are NOT in the
  JSON (pet stats are not scraped from the wiki) — they come from the
  wiki's Annie pets entry (see the quarantined constants below).  The
  attacks are emitted as a separate ``tibbers_attacks`` proc row (the R
  cast itself stays burst + aura) so the fight prices them once over
  the window instead of per R cast.
- P (Pyromania) is a stun-only passive shown as a zero-damage row under
  the literal "P" results key (the pre-engine UI shape), so a custom
  slot fn writes it into ``ctx.results`` directly instead of using the
  engine's "P" -> "passive" mapping.
- E (Molten Shield) is shield/retaliation only — champion-local
  ``_molten_shield`` preserves its zero-damage display row.
- Q/W are plain "Magic Damage" attribute reads.

All numeric values are read from the champion JSON data except the
Tibbers aura and auto-attack constants (wiki pets entry).
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import BUFF, SlotCtx, build_parser
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
    fixed_count_pet_row,
    simple_damage,
)
from .source_receipts import load_champion_sources

# HARDCODED: verify on patch updates — pet stats are not in the JSON.
# Tibbers pet numbers come from the LoL Wiki "Annie#Pets" entry:
# https://wiki.leagueoflegends.com/en-us/Annie
# - Flame Aura ticks every 0.25 seconds; base damage per tick 2/3/4 at
#   R rank 1/2/3; AP ratio per tick 1% AP (0.01).
# - Auto attack: 30 / 45 / 60 (based on R rank) + 10% AP magic damage.
# - Base attack speed 0.625; on summon Tibbers ENRAGES for 3 seconds,
#   attacking at 1.736 AS for his next 5 attacks, decaying with each
#   attack (wiki formula:
#   1.736*(1-(11.505*(x-1)+0.3*((x-2)^3-(x-2))/6+1.7*(x-2)*(x-1)/2)/100)
#   for x = attacks consumed 1..5), then returning to 0.625 AS.
_TIBBERS_AURA_BASE_PER_TICK = [2.0, 3.0, 4.0]
_TIBBERS_AURA_AP_RATIO_PER_TICK = 0.01
_TIBBERS_AURA_TICK_INTERVAL = 0.25
_TIBBERS_AUTO_BASE = [30.0, 45.0, 60.0]
_TIBBERS_AUTO_AP_RATIO = 0.10
_TIBBERS_BASE_ATTACK_SPEED = 0.625
_TIBBERS_ENRAGE_ATTACK_COUNT = 5
_TIBBERS_ENRAGE_BASE_AS = 1.736
_TIBBERS_DEFAULT_WINDOW = 5.0  # one rotation; timed fights pass the real window
_TIBBERS_MAX_ATTACKS = 30


def _tibbers_enrage_attack_speeds() -> tuple[float, ...]:
    """The five enrage attack speeds (attacks per second, wiki formula)."""
    speeds = []
    for consumed in range(1, _TIBBERS_ENRAGE_ATTACK_COUNT + 1):
        decay = (
            11.505 * (consumed - 1)
            + 0.3 * ((consumed - 2) ** 3 - (consumed - 2)) / 6
            + 1.7 * (consumed - 2) * (consumed - 1) / 2
        )
        speeds.append(_TIBBERS_ENRAGE_BASE_AS * (1.0 - decay / 100.0))
    return tuple(speeds)


def _tibbers_attack_times(count: int) -> list[float]:
    """First ``count`` Tibbers auto-attack timestamps from the sourced cadence.

    The enrage attacks land at the five decayed attack speeds, then the
    base 0.625 AS (1.6s interval) takes over.  Timestamps are seconds
    from the summon cast.
    """
    times: list[float] = []
    elapsed = 0.0
    for speed in _tibbers_enrage_attack_speeds():
        elapsed += 1.0 / speed
        times.append(elapsed)
        if len(times) >= count:
            return times
    while len(times) < count:
        elapsed += 1.0 / _TIBBERS_BASE_ATTACK_SPEED
        times.append(elapsed)
    return times


def _tibbers_attacks_row(ctx: SlotCtx, rank: int) -> dict[str, Any] | None:
    """The Tibbers auto-attack proc row (None when the player wants none).

    The default attack count is the sourced cadence (5 enrage attacks
    then the 1.6s base-AS interval) truncated to the fight window; the
    ``tibbers_attacks`` option overrides it — the player steers Tibbers,
    so positioning/leash uptime is a player choice.

    An ``auto_attacks_only`` window casts no R, and R's Active is what
    summons Tibbers, so there is no pet to steer.
    """
    if ctx.option("auto_attacks_only"):
        return None
    window = float(ctx.options.get("fight_duration_seconds", _TIBBERS_DEFAULT_WINDOW))
    requested = ctx.options.get("tibbers_attacks")
    if requested is None:
        attack_count = sum(
            1 for time in _tibbers_attack_times(_TIBBERS_MAX_ATTACKS) if time <= window
        )
    else:
        attack_count = min(max(int(requested), 0), _TIBBERS_MAX_ATTACKS)
    if attack_count <= 0:
        return None
    per_attack = (
        _TIBBERS_AUTO_BASE[min(rank - 1, len(_TIBBERS_AUTO_BASE) - 1)]
        + _TIBBERS_AUTO_AP_RATIO * ctx.stats["ability_power"]
    )
    return fixed_count_pet_row(
        "Tibbers Attacks",
        "magic",
        per_attack,
        _tibbers_attack_times(attack_count),
        (
            f"{attack_count} Tibbers auto attack(s) at {per_attack:.2f} "
            f"magic each (5 enrage attacks, then "
            f"{1.0 / _TIBBERS_BASE_ATTACK_SPEED:.1f}s cadence)"
        ),
    )


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
        ctx.stat("magic_penetration_percent") + magic_pen
    )

    burst = extract_named(ability, "Initial Magic Damage", rank, ctx.stats)
    cooldown = extract_cooldown(ability, rank)

    # Tibbers aura damage (not in JSON — wiki constants above).
    aura_seconds = float(ctx.option("tibbers_aura_seconds"))
    aura_base = _TIBBERS_AURA_BASE_PER_TICK[
        min(rank - 1, len(_TIBBERS_AURA_BASE_PER_TICK) - 1)
    ]
    aura_per_tick = (
        aura_base + _TIBBERS_AURA_AP_RATIO_PER_TICK * ctx.stats["ability_power"]
    )
    total_ticks = aura_seconds / _TIBBERS_AURA_TICK_INTERVAL
    aura_total = aura_per_tick * total_ticks

    total = burst + aura_total

    # Tibbers auto attacks: a fixed proc row priced over the fight
    # window, not per R cast (see _tibbers_attacks_row).
    attacks = _tibbers_attacks_row(ctx, rank)
    if attacks is not None:
        ctx.results["tibbers_attacks"] = attacks

    return {
        "name": ability.get("name", "Summon: Tibbers"),
        "rank": rank,
        "cooldown": cooldown,
        "damage_type": "magic",
        "parts": (DamagePart("magic", total),),
        "total_raw": total,
        "initial_burst": burst,
        "tibbers_aura": {
            "damage_per_tick": aura_per_tick,
            "total_ticks": total_ticks,
            "aura_total": aura_total,
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


# HARDCODED: verify on patch updates — Molten Shield's duration is prose
# in the cached ability description ("a shield for 3 seconds"); the
# shield amount (60/95/130/165/200 + 40% AP) is the cached Shield
# Strength leveling row, emitted by the ally-support scanner at the E
# cast (E8c).
_MOLTEN_SHIELD_DURATION_SECONDS = 3.0


def _molten_shield(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: ranked zero-damage row with the real cooldown."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    return damage_entry(
        ability.get("name", "Molten Shield"),
        rank,
        extract_cooldown(ability, rank),
        0.0,
        "magic",
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
    {
        "key": "tibbers_attacks",
        "type": "int",
        "default": 5,
        "label": (
            "Tibbers auto attacks (0 = none; defaults to the fight "
            "window at the sourced enrage + 0.625 AS cadence)"
        ),
        "min": 0,
        "max": 30,
    },
]

ASSUMPTIONS = [
    "R magic penetration passive is always active",
    "E (Molten Shield) shields Annie for the sourced 60/95/130/165/200 "
    "+ 40% AP (cached Shield Strength row) for 3s at the cast; the "
    "ally-support scanner emits the packet (untimed — the 3s expiry is "
    "a documented boundary of that interface) and it absorbs incoming "
    "damage in the participant ledger",
    "Tibbers auto attacks are priced at the wiki pets cadence (5 enrage "
    "attacks from the summon, then the 0.625 base AS) truncated to the "
    "fight window; positioning/leash uptime is a player choice via the "
    "tibbers_attacks option",
    "An autos-only fight has no Tibbers at all (the pipeline states this "
    "with the auto_attacks_only reserved option): the cached R text "
    "sources him to 'Active: Annie summons Tibbers to the target "
    "location', which no basic attack performs. R's magic-penetration "
    "passive is innate and still applies",
    "Tibbers aura defaults to 5 seconds of damage",
    "E retaliation damage is not modeled (requires enemies to hit Annie)",
]

SLOTS = {
    "R": _summon_tibbers,
    "P": _pyromania_placeholder,
    "Q": simple_damage(attr="Magic Damage", dmg_type="magic"),
    "W": simple_damage(attr="Magic Damage", dmg_type="magic"),
    "E": _molten_shield,
}

parse_abilities = build_parser(SLOTS, "Annie")


SOURCES = load_champion_sources("Annie")
