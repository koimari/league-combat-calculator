"""Miss Fortune — CP10.4 packet module with the E9-1 R gap fix.

E9-1 closes the remaining audit gap: R (Bullet Time) priced ONE wave of
the channel.  The wiki cache carries the explicit "Total Waves"
14/16/18 row and the "Wave Interval Time" cadence
(0.2036/0.1781/0.1583s by rank), so this module prices per-wave damage
x the sourced wave count at the sourced cadence — the full channel.
The wiki's "Maximum Total Physical Damage" row equals per-wave x waves
at ranks 1 and 3; the rank-2 display (500) is a rounding artifact of
16 x 30 == 480.

E2 already fixed E (Make It Rain) to its 8 sourced ticks; Q double-up
is modeled.

The coverage-frontier riders close P and W:

- P (Love Tap) is an auto-attack rider, not an on-hit that item on-hits
  proc from: "Miss Fortune's basic attacks are empowered to apply a mark
  that expires upon attacking a new enemy.  If the enemy was unmarked,
  this also deals 50% : 100% (based on level) AD bonus physical damage."
  In a duel the mark lands once and never refreshes, so the number of
  Love Taps is the number of times the player tags a NEW enemy — the
  ``p_procs`` option, defaulting to the one tap the duel target eats.
- W (Strut) is the sourced Bonus Attack Speed active (40-100% by rank)
  through the engine's ``stat_buff`` channel; its movement speed has no
  engine channel.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import ONHIT, SlotCtx
from .packet_module import build_packet_module
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
    on_hit_entry,
    stat_buff,
)

# HARDCODED: verify on patch updates — the cached Love Tap row is six
# values under one generic "Per-Level Scaling" attribute with no level
# axis, so the breakpoints come from the wiki template
# (Template:Data Miss Fortune/Love Tap, "50 to 100 for 6|1;4;7 to 13":
# 50% at levels 1-3, then 60/70/80/90/100% from levels 4/7/9/11/13).
_LOVE_TAP_BANDS = (1, 4, 7, 9, 11, 13)


def _bullet_time(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: per-wave damage x sourced Total Waves (14/16/18 by rank)."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    per_wave = extract_named(
        ability, "Physical Damage per Wave", rank, ctx.stats, ctx.target
    )
    waves = max(1, int(extract_value(ability, "Total Waves", rank)))
    interval = extract_value(ability, "Wave Interval Time", rank)
    total = per_wave * waves
    entry = damage_entry(
        ability.get("name", "Bullet Time"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "physical",
    )
    entry["parts"] = (
        DamagePart(
            "physical",
            per_wave,
            count=waves,
            time_offset=0.0,
            hit_interval=interval,
        ),
    )
    entry["dot_duration"] = waves * interval
    entry["detail"] = (
        f"{waves} sourced waves of {per_wave:.6g} physical damage "
        f"(per-wave x{waves} == the wiki Maximum Total Physical Damage "
        "row at ranks 1 and 3; the rank-2 display 500 vs 480 is a wiki "
        "rounding artifact)"
    )
    return entry


def _love_tap(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: the AD-scaled bonus on each attack that tags a NEW enemy."""
    ability = ctx.ability()
    if ability is None:
        return None
    band = sum(1 for start in _LOVE_TAP_BANDS if ctx.level >= start)
    # ``extract_value`` indexes the cached array positionally, so the band
    # ordinal IS the index the wiki template pins.
    ratio = extract_value(ability, "Per-Level Scaling", band) / 100.0
    per_tap = ratio * ctx.stat("attack_damage")
    if per_tap <= 0:
        return None

    taps = max(0, int(ctx.option("p_procs")))
    entry = on_hit_entry(ability.get("name", "Love Tap"), per_tap, "physical")
    entry["on_hit"]["max_procs"] = taps
    entry["detail"] = (
        f"{taps} Love Tap(s) of {per_tap:.2f} physical damage "
        f"({ratio:.0%} AD at level {ctx.level}); the mark expires only on "
        "attacking a NEW enemy, so a duel eats one tap unless the player "
        "tags another target"
    )
    return entry


_love_tap.phase = ONHIT


PACKET_SHA256 = "3c5d28681b774a275e1c2b8bfd6150c08bad192051ac56c0a49c6a96462ad2f7"


# Cached kit review: E's bullet storm deals damage every 0.25 seconds
# "and slow[s] them by 40% (+ 6% per 100 AP)"; Q's shot only bounces and
# R's waves only damage.  P is an on-hit mark and W a self-buff.
MODULE_CC = {"Q": "none", "E": "slow", "R": "none"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Miss Fortune",
    PACKET_SHA256,
    packet_tick_fixes={
        "Make It Rain": {
            "count": 8,
            "first_tick": 0.25,
            "tick_interval": 0.25,
            "dot_duration": 2.0,
        }
    },
    # Double Up's shot deals its packet once, on the primary target, at
    # the cast — the boundary claim that carries MODULE_CC's reviewed
    # answer for Q into the event ledger.
    single_hit_slots=frozenset({"Q"}),
    slot_parsers={
        "P": _love_tap,
        "W": stat_buff("Bonus Attack Speed", "bonus_attack_speed"),
        "R": _bullet_time,
    },
    cc_kinds=MODULE_CC,
)

OPTIONS.append(
    {
        "key": "p_procs",
        "type": "int",
        "default": 1,
        "min": 0,
        "max": 20,
        "label": "Love Taps (attacks that tag a new enemy)",
    }
)

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "R (Bullet Time) prices the full channel: per-wave damage x the "
    "sourced Total Waves row (14/16/18 by rank) at the sourced Wave "
    "Interval Time cadence.  The wiki's Maximum Total Physical Damage "
    "row matches per-wave x waves at every rank except its rank-2 "
    "display (500 vs 480) — a rounding artifact.",
    "Each wave is a 6-projectile spread that can critically strike for "
    "130% + 9% per 10% critical strike chance (wiki R effect[1]); the "
    "fight model prices the whole wave as one event without rolling "
    "per-projectile crits.",
    "P (Love Tap) rides basic attacks that tag a NEW enemy, at the "
    "sourced 50% : 100% (based on level) AD.  The mark expires only on "
    "attacking a different enemy, so the duel model gives it one tap by "
    "default (p_procs); raise it to price a fight where the player taps "
    "back and forth.  Love Tap modifies the attack rather than applying "
    "on-hit, so item on-hit effects do not proc from it, and the "
    "against-minions half-value row is not priced (no minions here).",
    "W (Strut) grants the sourced Bonus Attack Speed row (40-100% by "
    "rank) for the whole fight; the active's 4-second window and both "
    "movement-speed rows are not modeled (stat_buff has no "
    "movement-speed key).",
]
