"""Miss Fortune: packet module over the channel and the tap.

R (Bullet Time) prices the whole channel: per-wave damage times the cached
"Total Waves" row at the cached "Wave Interval Time" cadence.  The cached
"Maximum Total Physical Damage" row agrees at ranks 1 and 3; its rank-2 display
is a rounding artifact of 16 x 30.
E (Make It Rain) prices its eight sourced ticks and Q's double-up is modeled.
P (Love Tap) is an auto-attack RIDER, not an on-hit item effects proc from.  Its
per-level ladder comes from the game binary, the only source carrying the
level-20 tier this calculator reaches, and the cached wiki row cross-checks the
first six.  The mark never refreshes on the same enemy, so ``p_procs`` is how
many times the player tags a NEW one and defaults to the single tap the duel
target eats.
W (Strut) carries no damage instance anywhere.  What it does carry is priced:
the active's sourced "Bonus Attack Speed" row through ``stat_buff``, prorated
over its cached 4-second window so a short steroid does not take full uptime of
an arbitrary fight.  Its movement-speed rows have no channel.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import BUFF, ONHIT, SlotCtx
from .module_helpers import ability_slot, ranked_slot
from .packet_module import build_packet_module
from .slot_entries import damage_entry, on_hit_entry
from .slot_extract import (
    PER_LEVEL_SCALING,
    ability_name,
    extract_cooldown,
    extract_named,
    extract_value,
    find_named_leveling,
)
from .stat_grants import attack_speed_steroid

# HARDCODED game-file rule declaration — verify on patch updates.
# data/gamefiles/characters/missfortune.bin.json,
# Characters/MissFortune/Spells/MissFortunePassiveAbility/MissFortunePassive,
# mSpellCalculations.TotalDamage: a single StatBySubPartCalculationPart
# with mStat 2 and NO mStatFormula — TOTAL attack damage under the
# repo-pinned convention (the Senna P Relic Cannon reading) — over a
# ByCharLevelBreakpointsCalculationPart with mLevel1Value 0.5 and eight
# Breakpoints each adding mAdditionalBonusAtThisLevel 0.1 at the levels
# below.  (MinionDamage is the same calculation x 0.5, which reproduces
# the cache's "halved to 25% : 50% against minions" clause; minions are
# not modeled here.)  The binary is the level ladder's only home: the
# wiki cache stores the six tier VALUES but not the levels they start
# at, and only the binary carries the level-20 tier this calculator can
# actually reach (MAX_LEVEL is 20).
_LOVE_TAP_LEVEL1_AD_RATIO = 0.5
_LOVE_TAP_BREAKPOINT_LEVELS = (4, 7, 9, 11, 13, 20, 25, 30)
_LOVE_TAP_BREAKPOINT_STEP = 0.1


def _love_tap_tier(level: int) -> int:
    """Index of the breakpoint tier a champion level falls in."""
    return sum(1 for threshold in _LOVE_TAP_BREAKPOINT_LEVELS if level >= threshold)


def _love_tap_ad_ratio(ctx: SlotCtx, ability: dict[str, Any]) -> float:
    """Love Tap's total-AD coefficient at ``ctx.level``, cross-checked.

    The ladder comes from the game binary (see the constants above); the
    cached wiki "Per-Level Scaling" row carries the same tier values as
    percentages and is asserted against it here, so a patch that moves
    either source fails loudly instead of silently pricing a stale
    coefficient.  Tiers past the end of the cached row (level 20+) are
    binary-only and carry no wiki cross-check.
    """
    tier = _love_tap_tier(ctx.level)
    ratio = _LOVE_TAP_LEVEL1_AD_RATIO + _LOVE_TAP_BREAKPOINT_STEP * tier

    leveling = find_named_leveling(ability, PER_LEVEL_SCALING, occurrence=0)
    modifiers = (leveling or {}).get("modifiers") or []
    values = list(modifiers[0].get("values") or []) if modifiers else []
    if not values:
        raise ValueError(
            "Miss Fortune P (Love Tap) is missing its cached "
            f"{PER_LEVEL_SCALING!r} row; the bonus-damage "
            "coefficient cannot be sourced"
        )
    if tier < len(values):
        cached = float(values[tier]) / 100.0
        if abs(cached - ratio) > 1e-9:
            raise ValueError(
                "Miss Fortune P (Love Tap) coefficient drifted: game file "
                f"gives {ratio:.6g} x AD at level {ctx.level}, cached wiki "
                f"{PER_LEVEL_SCALING!r} tier {tier} gives {cached:.6g}"
            )
    return ratio


# Cached W active prose: "Miss Fortune gains bonus attack speed for 4
# seconds."  The window has no leveling row of its own.
_STRUT_ACTIVE_SECONDS = 4.0


@ranked_slot
def _bullet_time(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """R: per-wave damage x sourced Total Waves (14/16/18 by rank)."""

    per_wave = extract_named(
        ability, "Physical Damage per Wave", rank, ctx.stats, ctx.target
    )
    waves = max(1, int(extract_value(ability, "Total Waves", rank)))
    interval = extract_value(ability, "Wave Interval Time", rank)
    total = per_wave * waves
    entry = damage_entry(
        ability_name(ability),
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


@ability_slot()
def _love_tap(ctx: SlotCtx, ability: dict[str, Any]) -> dict[str, Any] | None:
    """P: the AD-scaled bonus on each attack that tags a NEW enemy."""
    ratio = _love_tap_ad_ratio(ctx, ability)
    per_tap = ratio * ctx.stat("attack_damage")
    if per_tap <= 0:
        return None

    taps = max(0, int(ctx.option("p_procs")))
    entry = on_hit_entry(ability_name(ability), per_tap, "physical")
    entry["on_hit"]["max_procs"] = taps
    entry["detail"] = (
        f"{taps} Love Tap(s) of {per_tap:.2f} physical damage "
        f"({ratio:.0%} of total AD at level {ctx.level}); the mark expires "
        "only on attacking a NEW enemy, so a duel eats one tap unless the "
        "player tags another target"
    )
    return entry


_love_tap.phase = ONHIT


@ranked_slot
def _strut(ctx: SlotCtx, ability: dict[str, Any], rank: int) -> dict[str, Any] | None:
    """W: the steroid alone; the atoms capture holds no damage instance."""

    return attack_speed_steroid(
        ctx,
        ability,
        rank,
        duration=_STRUT_ACTIVE_SECONDS,
        aside="the passive's 30-50 / 60-100 bonus movement speed has no stat_buff key",
    )


_strut.phase = BUFF


PACKET_SHA256 = "3c5d28681b774a275e1c2b8bfd6150c08bad192051ac56c0a49c6a96462ad2f7"


# Cached kit review: E's bullet storm deals damage every 0.25 seconds
# "and slow[s] them by 40% (+ 6% per 100 AP)"; Q's shot only bounces and
# R's waves only damage.  P is an on-hit mark and W a self-buff.
MODULE_CC = {"Q": "none", "E": "slow", "R": "none", "P": "none", "W": "none"}

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
        "W": _strut,
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
        "rotation": {"role": "self_state", "slot": "P"},
    }
)

ASSUMPTIONS = [
    *list(ASSUMPTIONS),
    "R (Bullet Time) prices per-wave damage x the sourced 14/16/18 waves at the "
    "cached Wave Interval.",
    "The wiki's Maximum Total row matches that at every rank but its rank-2 display, "
    "500 against 480.",
    "Each R wave is a 6-projectile spread critting for 130% + 9% per 10% crit chance "
    "(wiki R effect).",
    "The fight prices the whole wave as one event, with no per-projectile crit roll.",
    "P (Love Tap) rides a basic attack that tags a new enemy, adding 50 to 130% of "
    "total AD as physical.",
    "Love Tap's ByCharLevelBreakpoints ladder is 50/60/70/80/90/100/110/120/130% at "
    "levels 1/4/7/9/11/13/20/25/30.",
    "The game file's MissFortunePassive TotalDamage is mStat 2 with no mStatFormula, "
    "asserted at parse time.",
    "The cached 'Per-Level Scaling' row 50-100 reproduces the first six tiers.",
    "P's mark expires only on attacking a different enemy, so the duel gives one tap "
    "by default (p_procs).",
    "Love Tap modifies the attack rather than applying on-hit, so item on-hits do not "
    "proc from it.",
    "It is not modeled as critting, its life steal is out of scope, and the minion "
    "half-value row is unpriced.",
    "W (Strut) carries no damage instance in the atoms capture.",
    "W (Strut) grants the sourced 40 to 100% Bonus Attack Speed for its cached 4s "
    "window, as its share.",
    "W is prorated in a timed fight rather than full uptime; both movement-speed rows "
    "are not modeled.",
]
