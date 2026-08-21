"""Miss Fortune — CP10.4 packet module with the E9-1 R gap fix.

E9-1 closes the remaining audit gap: R (Bullet Time) priced ONE wave of
the channel.  The wiki cache carries the explicit "Total Waves"
14/16/18 row and the "Wave Interval Time" cadence
(0.2036/0.1781/0.1583s by rank), so this module prices per-wave damage
x the sourced wave count at the sourced cadence — the full channel.
The wiki's "Maximum Total Physical Damage" row equals per-wave x waves
at ranks 1 and 3; the rank-2 display (500) is a rounding artifact of
16 x 30 == 480.

E2 already fixed E (Make It Rain) to its 8 sourced ticks and Q double-up
is modeled.  The roadmap slot session closes the module's last two
``out_of_scope`` rows:

  - P (Love Tap) is now ``modeled``.  The packet asset's stock reason
    ("no enemy-damage formula for this slot") was simply wrong: the
    cached entry states "If the enemy was unmarked, this also deals
    50% : 100% (based on level) AD bonus physical damage" and carries
    the six-tier "Per-Level Scaling" row 50/60/70/80/90/100.  The mark
    "expires upon attacking a new enemy", so against ONE target the
    bonus lands exactly once — the first basic attack of the fight.
    That is priced as a one-application on-hit (``max_procs`` 1, the
    Viktor Q Discharge convention), which also means a rotation with no
    basic attacks prices zero, since Love Tap needs a swing to ride.
    Boundary (understating, deliberately): weaving between targets
    re-arms the mark and would proc it again, and the module does not
    claim Double Up's "on-attack effects" re-arm it either — the cached
    Love Tap prose says "basic attacks" and nothing more (the Ezreal W
    single-always-applied-detonation precedent).
  - W (Strut) becomes ``no_damage`` with a named receipt, replacing the
    stale ``out_of_scope`` label; see ``_strut`` for the atom evidence
    and for why the attack-speed window itself stays unpriced.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import ONHIT, SlotCtx, build_parser
from .module_helpers import no_damage_parser
from .packet_module import build_packet_module
from .slotlib import (
    ability_on_hit_entry,
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
    find_named_leveling,
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
    return sum(1 for breakpoint in _LOVE_TAP_BREAKPOINT_LEVELS if level >= breakpoint)


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


def _love_tap(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: the first basic attack on an unmarked target, priced once.

    One-application on-hit (``max_procs`` 1).  The mark only expires
    "upon attacking a new enemy", so in this one-target fight model the
    bonus fires on the opening swing and never again; a rotation with no
    basic attacks prices nothing at all, because Love Tap has no swing to
    ride (the engine caps the on-hit at the auto count).
    """
    ability = ctx.ability()
    if ability is None:
        return None

    ratio = _love_tap_ad_ratio(ctx, ability)
    per_hit = ratio * float(ctx.stats.get("attack_damage", 0.0))
    name = ability.get("name", "Love Tap")
    entry = ability_on_hit_entry(
        name,
        ctx.level,
        "physical",
        {
            "name": f"{name} (first hit)",
            "damage_per_hit": per_hit,
            "damage_type": "physical",
            "max_procs": 1,
            "detail": (
                f"{ratio * 100:.0f}% of total AD on the first basic attack "
                "against an unmarked target"
            ),
        },
        cooldown=0.0,
    )
    entry["detail"] = (
        f"first basic attack on an unmarked target adds {ratio * 100:.0f}% "
        f"of total AD ({per_hit:.6g}) as bonus physical damage; one "
        "application against a single target — the mark only re-arms on a "
        "NEW enemy, so multi-target weaving is understated"
    )
    return entry


_love_tap.phase = ONHIT


_STRUT_REASON = (
    "Strut is state, not damage: its passive grants 30-50 / 60-100 bonus "
    "movement speed and its active grants 40/55/70/85/100% bonus attack "
    "speed for 4 seconds (cached W 'Bonus Attack Speed' row), with Love "
    "Tap marking a NEW target refunding 2s of its cooldown.  No damage "
    "instance exists anywhere in the slot — data/atoms/missfortune.atoms."
    "json carries only MissFortuneStrutStacks (stack), "
    "MissFortuneViciousStrikes (buff) and Miss_Fortune_Strut_Cooldown "
    "(tag-activespell) for Strut, and no damage.damage-instance.  The "
    "attack-speed window is deliberately NOT applied as a stat buff: the "
    "engine's only timed attack-speed window "
    "(auto_attack_override.active_duration) resolves its window start "
    "from slot Q, so a plain stat_buff would spread a 4-second steroid on "
    "a 12-second cooldown across the whole fight and overstate it."
)


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


PACKET_SHA256 = "3c5d28681b774a275e1c2b8bfd6150c08bad192051ac56c0a49c6a96462ad2f7"

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
)
PACKET_SPEC = SLOTS.packet_spec
SLOTS["R"] = _bullet_time
SLOTS["W"] = no_damage_parser("W", reason=_STRUT_REASON)
SLOTS["P"] = _love_tap
parse_abilities = build_parser(SLOTS, "Miss Fortune")

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
    "P (Love Tap) is priced as a ONE-application on-hit: the first basic "
    "attack against an unmarked target adds 50/60/70/80/90/100/110/120/"
    "130% of TOTAL AD as bonus physical damage at levels 1/4/7/9/11/13/"
    "20/25/30 (game file MissFortunePassive TotalDamage: mStat 2 with no "
    "mStatFormula over a ByCharLevelBreakpoints ladder; the cached wiki "
    "'Per-Level Scaling' row 50-100 reproduces the first six tiers and is "
    "asserted against the ladder at parse time).  The mark expires only "
    "on attacking a NEW enemy, so a one-target fight procs it exactly "
    "once and multi-target weaving is understated; a rotation with no "
    "basic attacks prices zero.  Love Tap is not modeled as critting and "
    "its life-steal clause is out of scope (healing).",
    "W (Strut) is an atoms-confirmed zero-damage state row.  Its 4-second "
    "40-100% bonus-attack-speed active is NOT applied to the fight's "
    "attack speed: the engine's only timed attack-speed window is "
    "slot-Q-anchored, and an untimed stat buff would give a 4s/12s "
    "steroid full uptime over an arbitrary fight length.",
]
MODULE_COVERAGE = {
    "P": "modeled",
    "Q": "modeled",
    "W": "no_damage",
    "E": "modeled",
    "R": "modeled",
}
REVIEW_STATUS = "reviewed_module"
