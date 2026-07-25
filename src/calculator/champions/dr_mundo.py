"""Dr. Mundo — slot map for the archetype engine.

Why each slot is non-generic:
- P (Goes Where He Pleases) is deliberately ABSENT: health regeneration,
  an immobilize cleanse and a self-heal on the dropped canister. It deals
  no damage to an enemy, so it gets no slot.
- Q (Infected Bonesaw) is %CURRENT-health magic damage floored at a flat
  minimum, and both halves defeat the generic path. The unit
  ``"% of target's current health"`` resolves against a
  ``target_current_health`` stat nothing supplies, so the percent scores
  0.0; the floor lives in a second effect the primary-damage classifier
  never reaches.
- W (Heart Zapper) is a 3s charge DoT plus an automatic detonation. The
  charge total has to be rebuilt from the per-tick value (the JSON's
  "Total Magic Damage" is stale — see ``W_CHARGE_TICKS``) and the
  detonation lives in its own effect, so the generic path reads the
  detonation base alone and misses everything else.
- E (Blunt Force Trauma) is two mechanics inside one JSON ability: a
  BUFF-phase %MAXIMUM-health -> bonus AD steroid that roughly doubles
  Mundo's AD, and an empowered next basic attack whose bonus is amplified
  by Mundo's OWN missing health. The generic path modeled neither.
- R (Maximum Dosage) deals no damage whatsoever, so the generic path drops
  it — but it grants BASE health scaled off missing health, which raises
  max health and therefore feeds E's passive. That chain
  (R -> max health -> E's bonus AD -> autos and the forced swing) is why R
  is listed BEFORE E in ``SLOTS``: both are BUFF phase, and the engine
  evaluates a phase in slot-map insertion order.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import BUFF, SlotCtx, build_parser
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
    stat_buff,
)

# HARDCODED: verify on patch updates — W's charge lasts 3.0s and ticks 4
# times a second, so the charge total is per-tick x 12.
#
# DO NOT replace this with the JSON's "Total Magic Damage" attribute
# (80/140/200/260/320). That attribute is STALE: the wiki's raw data
# template still hardcodes ``{{ap|5*16 to 20*16}}`` = 16 ticks from W's
# pre-V12.23 FOUR-second duration, and was never updated when V12.23 cut
# the duration to 3s. Confirmed three ways — 3.0s / 0.25s per tick = 12;
# the game file's ``Duration`` = 3.0; and the game's own damage formula
# in ``drmundo.bin.json`` BotData is 4 (ticks/sec) x DamagePerTick x
# Duration. Using the attribute overstates W's charge by a third.
# https://wiki.leagueoflegends.com/en-us/Dr._Mundo
W_CHARGE_TICKS = 12
W_DURATION = 3.0  # seconds the field ticks; item burns ride the whole tail

# HARDCODED: verify on patch updates — E's bonus damage reaches its
# maximum amp at 70% missing health, NOT 100%. The wiki ability page only
# says "0% - 40% (based on missing health)" and never publishes the
# threshold; it comes from the game files (``drmundo.bin.json``:
# ``MaxMissingHealthThreshold`` 0.7, ``MaxDamageAmp`` 1.4) and is
# confirmed by patch V25.23 ("Maximum bonus damage now correctly applies
# at 70% missing health").
E_MAX_DAMAGE_AMP = 0.4
E_MAX_AMP_MISSING_HEALTH_PERCENT = 70.0

# HARDCODED: verify on patch updates — at rank 3 ONLY, R's increased base
# health is further increased by 5% per enemy champion within 1200 units
# at cast time (game file ``BonusPerNearbyChampion`` = 0.05). The JSON
# leveling carries no trace of it.
R_NEARBY_CHAMPION_BONUS = 0.05
R_NEARBY_BONUS_RANK = 3
R_MAX_NEARBY_CHAMPIONS = 4

_DEFAULT_MISSING_HEALTH_PERCENT = 30
_DEFAULT_NEARBY_CHAMPIONS = 0


# ---------------------------------------------------------------------------
# Shared fight state
# ---------------------------------------------------------------------------


def _missing_health_fraction(ctx: SlotCtx) -> float:
    """Mundo's own missing health as a 0..1 fraction — the ONE source.

    E's damage amp and R's base-health grant both read how hurt Mundo is.
    They describe a single game state, so they derive from a single option
    and can never disagree (the Darius one-input rule); neither consumer
    gets an override of its own.
    """
    percent = float(
        ctx.options.get("mundo_missing_health_percent", _DEFAULT_MISSING_HEALTH_PERCENT)
    )
    return min(max(percent, 0.0), 100.0) / 100.0


# ---------------------------------------------------------------------------
# R: Maximum Dosage — BUFF phase, listed first (E's passive reads its health)
# ---------------------------------------------------------------------------


def _nearby_champions(ctx: SlotCtx) -> int:
    """Enemy champions inside R's 1200-unit radius when it is cast."""
    count = int(ctx.options.get("r_nearby_champions", _DEFAULT_NEARBY_CHAMPIONS))
    return min(max(count, 0), R_MAX_NEARBY_CHAMPIONS)


def _maximum_dosage(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: zero damage; grants BASE health from Mundo's missing health.

    BASE, not bonus (the Gnar classification trap): the grant raises max
    health — which is exactly what feeds E's passive bonus AD — but must
    never reach items that convert BONUS health (Overlord's Bloodmail).
    ``base_health`` is the fight engine's key for that distinction.
    """
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    # "% missing health" is Mundo's OWN missing health — no scaling unit
    # covers that, so the percentage is read raw and applied here.
    percent = extract_value(ability, "Increased Base Health", rank) / 100.0
    if rank >= R_NEARBY_BONUS_RANK:
        percent *= 1.0 + R_NEARBY_CHAMPION_BONUS * _nearby_champions(ctx)

    max_health = ctx.stats.get("health", 0.0)
    grant = percent * max_health * _missing_health_fraction(ctx)
    # Raise base and total together — bonus health is untouched, which is
    # what keeps the grant away from bonus-health item conversions.
    ctx.stats["health"] = max_health + grant
    ctx.stats["base_health"] = ctx.stats.get("base_health", 0.0) + grant

    entry = damage_entry(
        ability.get("name", "Maximum Dosage"),
        rank,
        extract_cooldown(ability, rank),
        0.0,
        "physical",
    )
    entry["stat_buff"] = {"base_health": grant}
    return entry


_maximum_dosage.phase = BUFF


# ---------------------------------------------------------------------------
# E: Blunt Force Trauma — the AD steroid and the empowered auto it rides
# ---------------------------------------------------------------------------

# The passive is a plain percent-of-a-stat steroid: "% maximum health" is
# TOTAL health (the game file's ``PassiveBonusAD`` carries no
# ``mStatFormula`` key, which defaults to total). E's ACTIVE, one JSON line
# below in the same ability, is "% BONUS health" — the two are one line
# apart and trivially mixed up.
_passive_bonus_ad = stat_buff(
    attr="Bonus Attack Damage",
    stat="bonus_attack_damage",
    mode="percent_of",
    percent_of="health",
    apply_to=("bonus_attack_damage", "attack_damage"),
)


def _damage_amp(ctx: SlotCtx) -> float:
    """E's bonus-damage multiplier: 1.0 at full health, 1.4 at 70% missing."""
    missing_percent = _missing_health_fraction(ctx) * 100.0
    ramp = min(missing_percent / E_MAX_AMP_MISSING_HEALTH_PERCENT, 1.0)
    return 1.0 + E_MAX_DAMAGE_AMP * ramp


def _blunt_force_trauma(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: the %max-health AD steroid plus one missing-health-amped swing.

    BUFF phase and listed after R, so the passive converts the max health R
    has already raised. The amp multiplies the WHOLE minimum bonus (flat +
    % bonus health), which reproduces the wiki's "Maximum Bonus Physical
    Damage" row exactly at full amp — that row is this same damage at amp
    1.4, never a second damage source to add.

    The empowered attack lands ONCE per cast, not on every auto (the
    Alistar rule); with no auto stream to ride, the fight engine appends
    the expected-crit base swing to this row (Blitzcrank/Caitlyn).
    """
    entry = _passive_bonus_ad(ctx)
    if entry is None:
        return None
    ability = ctx.ability()
    if ability is None:
        return None

    # Read after the passive mutated ctx.stats: safe, and deliberately so —
    # the active scales off BONUS health, which the AD buff cannot touch.
    bonus = extract_named(
        ability,
        "Minimum Bonus Physical Damage",
        entry["rank"],
        ctx.stats,
        ctx.target,
    )
    total = bonus * _damage_amp(ctx)
    entry["total_raw"] = total
    entry["parts"] = (DamagePart("physical", total),)
    entry["empowers_next_auto"] = True
    return entry


_blunt_force_trauma.phase = BUFF


# ---------------------------------------------------------------------------
# Q: Infected Bonesaw
# ---------------------------------------------------------------------------


def _infected_bonesaw(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: % of the target's current health, floored at a flat minimum.

    The percent's unit ("% of target's current health") has no stat behind
    it in scaling.py, so the value is read raw and applied here. Every cast
    is priced against the target's FULL health (see ASSUMPTIONS): Q does
    not decay its own target across casts. The floor is not decoration —
    at rank 5 it takes over below roughly 933 target health.
    """
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    percent = extract_value(ability, "Magic Damage", rank) / 100.0
    minimum = extract_value(ability, "Minimum Damage", rank)
    total = max(percent * ctx.target.get("target_max_health", 0.0), minimum)

    return damage_entry(
        ability.get("name", "Infected Bonesaw"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )


# ---------------------------------------------------------------------------
# W: Heart Zapper
# ---------------------------------------------------------------------------


def _heart_zapper(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: 12 charge ticks plus the detonation that always follows them.

    The detonation is not optional and is not a recast the player may skip
    — the field "does so automatically after the duration" — so it is one
    guaranteed instance per W cast, folded into the same entry.
    """
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    per_tick = extract_named(
        ability, "Magic Damage per Tick", rank, ctx.stats, ctx.target
    )
    detonation = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)

    entry = damage_entry(
        ability.get("name", "Heart Zapper"),
        rank,
        extract_cooldown(ability, rank),
        per_tick * W_CHARGE_TICKS + detonation,
        "magic",
    )
    # Item burns (Liandry's, Blackfire Torch) stay refreshed through the
    # whole channel, not just to the cast instant (the Cassiopeia rule).
    entry["dot_duration"] = W_DURATION
    return entry


OPTIONS: list[dict[str, Any]] = [
    {
        "key": "mundo_missing_health_percent",
        "type": "int",
        "default": _DEFAULT_MISSING_HEALTH_PERCENT,
        "min": 0,
        "max": 100,
        "label": "Dr. Mundo's missing health (%)",
    },
    {
        "key": "r_nearby_champions",
        "type": "int",
        "default": _DEFAULT_NEARBY_CHAMPIONS,
        "min": 0,
        "max": R_MAX_NEARBY_CHAMPIONS,
        "label": "Enemy champions near R cast (rank 3 bonus)",
    },
]

ASSUMPTIONS = [
    "Q is priced against the target's FULL health on every cast. Because "
    "Q scales with CURRENT health, repeated casts in one fight are "
    "overestimated (roughly 18% high on a two-Q rotation)",
    "Q's minimum damage floor is modeled and takes over against low-health "
    "targets; Q's capped monster damage and E's 140% minion/monster "
    "amplification are not — the target is a champion",
    "All 12 ticks of W's charge are assumed to connect (the full 3s inside "
    "the 325-unit radius), and the detonation always follows automatically "
    "at the end of the duration",
    "W's charge total is per-tick x 12 ticks, NOT the 16-tick 'Total Magic "
    "Damage' still cached from W's pre-V12.23 four-second duration",
    "E's bonus damage reaches its maximum amp at 70% missing health, not "
    "100% (undocumented on the wiki; from the game files and V25.23)",
    "E's empowered attack applies once per cast, not on every auto; it "
    "resets the attack timer, which is not modeled as extra attacks",
    "E's corpse knockback (100% AD to enemies the flung body passes "
    "through) is not modeled — it only triggers on a kill or a small "
    "monster, so it is not a repeatable source against a champion",
    "R grants BASE health, so it raises max health (feeding E's passive "
    "bonus AD) but does not feed bonus-health item conversions such as "
    "Overlord's Bloodmail",
    "R's bonus movement speed, health regeneration and takedown duration "
    "extension are not modeled (no damage impact)",
    "Mundo's passive, Q's health cost and refund, and W's grey-health "
    "healing are self-sustain and are not modeled",
    "Dr. Mundo has no AP scaling anywhere in his kit",
]

SLOTS = {
    # BUFF phase, in this order: R raises max health, and E's passive then
    # converts that raised max health into bonus AD.
    "R": _maximum_dosage,
    "E": _blunt_force_trauma,
    "Q": _infected_bonesaw,
    "W": _heart_zapper,
}

parse_abilities = build_parser(SLOTS, "Dr. Mundo")
