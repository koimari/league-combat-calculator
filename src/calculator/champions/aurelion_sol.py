"""Aurelion Sol — slot map for the archetype engine.

Why each slot is non-generic:
- Q (Breath of Light) is a channeled beam the classifier cannot model:
  the per-cast entry is one full 3.25s channel (beam per-second x 3.25
  plus 3 bursts), the burst's Stardust %maxHP component is a degraded
  wiki parse (values all 0, garbage units) hardcoded below, the W toggle
  multiplies the beam's flat damage, and timed fights channel Q
  continuously for the whole fight (the pipeline injects the duration
  via the ``fight_duration_seconds`` option; see ``pipeline.run_fight``).
  The JSON attr "Total Maximum Magic Damage" has only 4 values because
  rank 5 has no practical channel cap (160s) — never read it; the
  per-second attr is complete at every rank.
- W (Astral Flight) is a damage-less dash, deliberately absent from the
  map; its only calc effect is Q's beam modifier, gated by ``w_active``.
- E (Singularity) must read "Total Magic Damage" (full 5s zone) and
  carries the execute-threshold display line (5% + 2.6% per 100
  Stardust of max HP — wiki prose with no usable JSON home).
- R swaps between Falling Star (R[0]) and The Skies Descend (R[1]) via
  the ``r_empowered`` option. The empowered shockwave (R[1] effect[1])
  is excluded: a target hit by the star is immune to the shockwave.
- P (Cosmic Creator) is the Stardust stack mechanic — no damage row; it
  exists as the ``stardust_stacks`` option feeding Q and E.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .module_helpers import delayed_damage
from .slotlib import (
    by_option,
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
)

# One full Q channel: 3.25 s of beam, with a burst on the primary target
# at each full second of channel (3 bursts).
_Q_CHANNEL_SECONDS = 3.25
_Q_BURSTS_PER_CHANNEL = 3

# HARDCODED: verify on patch updates — wiki prose the modifier parser
# degrades (Q burst: values [0,...], units "(3.1% Stardust)% of target's
# maximum health"; E execute threshold has no JSON entry at all).
# https://wiki.leagueoflegends.com/en-us/Aurelion_Sol
_Q_BURST_MAXHP_PCT_PER_STARDUST = 0.031  # % of target max HP per stack
_E_EXECUTE_BASE_PCT = 5.0
_E_EXECUTE_PCT_PER_100_STARDUST = 2.6

# Both R branches strike after their own sourced delay, from cast start:
# "calls down a star that strikes the target location after 1.25 seconds,
# dealing magic damage to enemies hit and stunning them for 1 second"
# (R[0]) and "calls down a giant star that strikes the target location
# after 2 seconds, dealing 25% increased damage in a larger area and
# knocking up enemies hit for 1 second" (R[1]).
_R_FALLING_STAR_SECONDS = 1.25
_R_SKIES_DESCEND_SECONDS = 2.0


def _w_beam_modifier(ctx: SlotCtx) -> float:
    """W's 108-112% multiplier on Q's beam flat damage; 1.0 when inactive.

    Beam only, per the wiki's "its non-burst flat damage is increased" —
    never the burst base or any AP portion. No effect until W is learned.
    """
    if not ctx.options.get("w_active", False):
        return 1.0
    w_ability = ctx.ability("W")
    w_rank = ctx.rank_for("W")
    if w_ability is None or w_rank < 1:
        return 1.0
    modifier = extract_value(
        w_ability, "Breath of Light Flat Damage Modifier", w_rank, 0
    )
    if modifier <= 0:
        # A missing attribute reads as 0.0, which would annihilate the
        # beam instead of scaling it — fail loudly (a patch renamed it).
        raise ValueError(
            "Aurelion Sol W: 'Breath of Light Flat Damage Modifier' is "
            "missing from the ability JSON — cannot scale Q's beam damage"
        )
    return modifier / 100.0


# The beam ticks 8 times per second — the JSON's per-tick row is
# exactly 1/8 of the per-second row at every rank (5.625 = 45/8 ...
# 13.125 = 105/8), and its "Total Maximum Magic Damage" is 26 ticks of
# it (146.25 = 26 x 5.625 at rank 1), i.e. one full 3.25s channel.  A
# burst lands on the primary target at each full second of the channel.
_Q_TICKS_PER_SECOND = 8
_Q_TICK_INTERVAL = 1.0 / _Q_TICKS_PER_SECOND  # "every 0.125 seconds"


def _breath_of_light(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: full-channel beam + bursts; continuous channel in timed fights."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    ap = ctx.stat("ability_power")
    beam_per_second = (
        extract_value(ability, "Magic Damage per Second", rank, 0)
        * _w_beam_modifier(ctx)
        + ap * extract_value(ability, "Magic Damage per Second", rank, 1) / 100.0
    )

    stacks = float(ctx.option("stardust_stacks"))
    max_hp = ctx.target_stat("target_max_health")
    per_burst = (
        extract_value(ability, "Bonus Magic Damage", rank, 0)
        + ap * extract_value(ability, "Bonus Magic Damage", rank, 1) / 100.0
        + (_Q_BURST_MAXHP_PCT_PER_STARDUST * stacks / 100.0) * max_hp
    )

    fight_seconds = ctx.options.get("fight_duration_seconds")
    if fight_seconds is not None:
        # Timed fight: Q channels continuously for the whole fight —
        # one burst per full second, and the entry never recasts.
        seconds = float(fight_seconds)
        bursts = int(seconds)
        cooldown = 999.0
    else:
        seconds = _Q_CHANNEL_SECONDS
        bursts = _Q_BURSTS_PER_CHANNEL
        cooldown = extract_cooldown(ability, rank)

    # The beam is per-tick damage x (seconds / tick interval): 26 ticks
    # of the per-tick row for one 3.25s channel, exactly the sourced
    # "Total Maximum Magic Damage" (per-second x 3.25).
    ticks = int(round(seconds / _Q_TICK_INTERVAL))
    per_tick = beam_per_second * _Q_TICK_INTERVAL
    total = per_tick * ticks + per_burst * bursts
    entry = damage_entry(
        ability.get("name", "Breath of Light"), rank, cooldown, total, "magic"
    )
    entry["parts"] = (
        DamagePart(
            "magic",
            per_tick,
            count=ticks,
            time_offset=_Q_TICK_INTERVAL,
            hit_interval=_Q_TICK_INTERVAL,
        ),
        DamagePart(
            "magic",
            per_burst,
            count=bursts,
            time_offset=1.0,
            hit_interval=1.0,
        ),
    )
    entry["detail"] = (
        f"{ticks} sourced beam tick(s) at 0.125s intervals; {bursts} burst(s) "
        f"at each full second."
    )
    return entry


# E (Singularity) ticks 20 times over its 5-second zone — the JSON's
# "Total Magic Damage" row is exactly 20x the "Magic Damage per Tick"
# row at every rank (50/2.5 .. 150/7.5), so the tick count is sourced
# rather than invented.  Each tick is one 0.25s step of the zone.
_E_TICKS = 20
_E_DURATION = 5.0
_E_TICK_INTERVAL = _E_DURATION / _E_TICKS  # "every 0.25 seconds"


def _singularity(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: 20 sourced ticks of the full-zone total, plus the execute line."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    total = extract_named(ability, "Total Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Singularity"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    entry["parts"] = (
        DamagePart(
            "magic",
            total / _E_TICKS,
            count=_E_TICKS,
            time_offset=_E_TICK_INTERVAL,
            hit_interval=_E_TICK_INTERVAL,
        ),
    )
    # Item burns stay refreshed through the whole 5s zone (the
    # Cassiopeia rule).
    entry["dot_duration"] = _E_DURATION

    stacks = float(ctx.option("stardust_stacks"))
    threshold_pct = _E_EXECUTE_BASE_PCT + _E_EXECUTE_PCT_PER_100_STARDUST * (
        stacks / 100.0
    )
    detail = f"Executes below {threshold_pct:.1f}% max HP"
    max_hp = ctx.target_stat("target_max_health")
    if max_hp > 0:
        detail += f" ({threshold_pct / 100.0 * max_hp:.0f} HP)"
    entry["detail"] = detail
    return entry


OPTIONS: list[dict[str, Any]] = [
    {
        "key": "stardust_stacks",
        "type": "int",
        "default": 0,
        "label": "Stardust stacks",
        "min": 0,
        "max": 999,
    },
    {
        "key": "w_active",
        "type": "bool",
        "default": False,
        "label": "W (Astral Flight) active",
    },
    {
        "key": "r_empowered",
        "type": "bool",
        "default": False,
        "label": "R empowered (The Skies Descend)",
    },
]

ASSUMPTIONS = [
    "Q is modeled as one full 3.25s channel per cast: full beam damage "
    "plus 3 bursts on the primary target (in-game the channel can run "
    "longer — up to 160s at rank 5, unlimited during W)",
    "Timed fights assume Q channels continuously for the whole duration, "
    "uninterrupted by other casts — beam damage every second, one burst "
    "per full second; below rank 5 without W this overstates Q uptime "
    "(3.25s channel cap plus cooldown gaps)",
    "Timed fights count the whole Q channel as a single cast for "
    "cast-counted item effects (e.g. spellblade procs)",
    "W active multiplies Q's beam flat damage only (wiki: 'non-burst flat "
    "damage'), never the burst base or AP portions; the channel window is "
    "unchanged for an apples-to-apples toggle comparison",
    "E assumes the target stays in the zone for the full 5s (all 20 ticks)",
    "Empowered R shows the star impact only — a target hit by the star is "
    "immune to the shockwave",
    "Secondary-target Q beam damage (50% of primary) is not modeled — "
    "primary target only",
]

SLOTS = {
    "Q": _breath_of_light,
    "E": _singularity,
    # Both R branches land on their own sourced delay, and the two apply
    # different control, so each authors its own kind on its own part
    # rather than sharing one MODULE_CC answer.
    "R": by_option(
        "r_empowered",
        {
            False: delayed_damage(
                delay=_R_FALLING_STAR_SECONDS,
                attr="Magic Damage",
                dmg_type="magic",
                cc_kind="stun",
            ),
            True: delayed_damage(
                delay=_R_SKIES_DESCEND_SECONDS,
                attr="Empowered Magic Damage",
                dmg_type="magic",
                source=("R", 1),
                cooldown_from=("R", 0),
                cc_kind="knockup",
            ),
        },
        default=False,
    ),
}

# Cached kit review.  Q's beam only burns and reveals.  E's black hole
# "drag[s] [enemies] inward", which the Wiki's crowd-control taxonomy does
# not list among its four displacements (knock aside/back/up, pull) nor
# among the immobilizing effects, and its movement-speed floor applies to
# "minions and monsters" only — so neither slot controls the champion it
# damages.  R is deliberately absent from this dict rather than
# unreviewed: its two branches apply different control (Falling Star
# stuns, The Skies Descend knocks up) on different sourced delays, so the
# answer is a property of the branch and each variant authors its own
# ``cc_kind`` on its own part above.
MODULE_CC = {"Q": "none", "E": "none"}

parse_abilities = build_parser(SLOTS, "Aurelion Sol", cc_kinds=MODULE_CC)


# Authoritative review metadata (issue #161).
SOURCES = [
    {
        "label": "Local League Wiki cache",
        "url": "https://wiki.leagueoflegends.com/en-us/Aurelion_Sol",
        "revision_id": 3952788,
        "revision_timestamp": "2025-09-10T01:55:29Z",
    }
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in SLOTS else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
