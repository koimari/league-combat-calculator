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
is modeled.  The coverage-frontier riders close P and W:

- P (Love Tap) is an auto-attack rider, not an on-hit that item on-hits
  proc from: "Miss Fortune's basic attacks are empowered to apply a mark
  that expires upon attacking a new enemy.  If the enemy was unmarked,
  this also deals 50% : 100% (based on level) AD bonus physical damage."
  Its per-level ladder comes from the game binary (see the constants
  below), which is the only source carrying the level-20 tier this
  calculator can reach; the cached wiki row cross-checks the first six.
  The mark never refreshes on the same enemy, so the number of Love Taps
  is the number of times the player tags a NEW enemy — the ``p_procs``
  option, defaulting to the one tap the duel target eats.  Neither the
  minion-halved row nor Double Up's "on-attack effects" re-arming the
  mark is claimed here.
- W (Strut) carries no damage instance anywhere (data/atoms/
  missfortune.atoms.json holds only MissFortuneStrutStacks,
  MissFortuneViciousStrikes and Miss_Fortune_Strut_Cooldown).  What it
  does carry is priced: the active's sourced Bonus Attack Speed row
  (40-100% by rank) through the ``stat_buff`` channel, prorated over its
  cached 4-second window so a 4s steroid does not take full uptime of an
  arbitrary fight.  The movement-speed rows have no engine channel.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import BUFF, ONHIT, SlotCtx
from .module_helpers import buff_window_share, ranked_slot
from .packet_module import build_packet_module
from .slotlib import (
    STEROID_ZERO,
    ability_name,
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
    find_named_leveling,
    on_hit_entry,
)

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
# The cached wiki row this ladder must reproduce, as percentages.
_LOVE_TAP_WIKI_ATTRIBUTE = "Per-Level Scaling"


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

    leveling = find_named_leveling(ability, _LOVE_TAP_WIKI_ATTRIBUTE, occurrence=0)
    modifiers = (leveling or {}).get("modifiers") or []
    values = list(modifiers[0].get("values") or []) if modifiers else []
    if not values:
        raise ValueError(
            "Miss Fortune P (Love Tap) is missing its cached "
            f"{_LOVE_TAP_WIKI_ATTRIBUTE!r} row; the bonus-damage "
            "coefficient cannot be sourced"
        )
    if tier < len(values):
        cached = float(values[tier]) / 100.0
        if abs(cached - ratio) > 1e-9:
            raise ValueError(
                "Miss Fortune P (Love Tap) coefficient drifted: game file "
                f"gives {ratio:.6g} x AD at level {ctx.level}, cached wiki "
                f"{_LOVE_TAP_WIKI_ATTRIBUTE!r} tier {tier} gives {cached:.6g}"
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


def _love_tap(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: the AD-scaled bonus on each attack that tags a NEW enemy."""
    ability = ctx.ability()
    if ability is None:
        return None
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
    """W: the active's sourced bonus attack speed over its own window.

    The slot deals no damage at all (no damage instance exists in the
    atoms capture), so the row is the steroid: the cached Bonus Attack
    Speed value, taken through :func:`buff_window_share` so a 4-second
    active does not hold full uptime of a longer fight.  The two
    movement-speed rows have no ``stat_buff`` key to land in.
    """

    granted = extract_value(ability, "Bonus Attack Speed", rank)
    bonus_as = granted * buff_window_share(ctx, _STRUT_ACTIVE_SECONDS)
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        0.0,
        "physical",
        zero_policy=STEROID_ZERO,
    )
    entry["stat_buff"] = {"bonus_attack_speed": bonus_as}
    entry["detail"] = (
        f"+{granted:g}% bonus attack speed for {_STRUT_ACTIVE_SECONDS:g}s "
        f"({bonus_as:g}% over the fight window); the passive's 30-50 / "
        "60-100 bonus movement speed has no stat_buff key"
    )
    return entry


_strut.phase = BUFF


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
    }
)

ASSUMPTIONS = [
    *list(ASSUMPTIONS),
    "R (Bullet Time) prices the full channel: per-wave damage x the "
    "sourced Total Waves row (14/16/18 by rank) at the sourced Wave "
    "Interval Time cadence.  The wiki's Maximum Total Physical Damage "
    "row matches per-wave x waves at every rank except its rank-2 "
    "display (500 vs 480) — a rounding artifact.",
    "Each wave is a 6-projectile spread that can critically strike for "
    "130% + 9% per 10% critical strike chance (wiki R effect[1]); the "
    "fight model prices the whole wave as one event without rolling "
    "per-projectile crits.",
    "P (Love Tap) rides basic attacks that tag a NEW enemy, adding "
    "50/60/70/80/90/100/110/120/130% of TOTAL AD as bonus physical "
    "damage at levels 1/4/7/9/11/13/20/25/30 (game file "
    "MissFortunePassive TotalDamage: mStat 2 with no mStatFormula over a "
    "ByCharLevelBreakpoints ladder; the cached wiki 'Per-Level Scaling' "
    "row 50-100 reproduces the first six tiers and is asserted against "
    "the ladder at parse time).  The mark expires only on attacking a "
    "different enemy, so the duel model gives it one tap by default "
    "(p_procs); raise it to price a fight where the player taps back and "
    "forth.  Love Tap modifies the attack rather than applying on-hit, so "
    "item on-hit effects do not proc from it; it is not modeled as "
    "critting, its life-steal clause is out of scope (healing), and the "
    "against-minions half-value row is not priced (no minions here).",
    "W (Strut) carries no damage instance in the atoms capture.  It "
    "grants the sourced Bonus Attack Speed row (40-100% by rank) for the "
    "cached 4-second active window, taken as that window's share of the "
    "fight (whole bonus in one-rotation mode, prorated in a timed fight) "
    "rather than as full uptime.  Both movement-speed rows are not "
    "modeled (stat_buff has no movement-speed key).",
]
