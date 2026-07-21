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

from .engine import SlotCtx, build_parser
from .slotlib import (
    by_option,
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
    simple_damage,
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


def _breath_of_light(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: full-channel beam + bursts; continuous channel in timed fights."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    ap = ctx.stats.get("ability_power", 0.0)
    beam_per_second = (
        extract_value(ability, "Magic Damage per Second", rank, 0)
        * _w_beam_modifier(ctx)
        + ap * extract_value(ability, "Magic Damage per Second", rank, 1) / 100.0
    )

    stacks = float(ctx.options.get("stardust_stacks", 0))
    max_hp = ctx.target.get("target_max_health", 0.0)
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

    total = beam_per_second * seconds + per_burst * bursts
    return damage_entry(
        ability.get("name", "Breath of Light"), rank, cooldown, total, "magic"
    )


def _singularity(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: full 5s zone total, plus the execute-threshold display line."""
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

    stacks = float(ctx.options.get("stardust_stacks", 0))
    threshold_pct = _E_EXECUTE_BASE_PCT + _E_EXECUTE_PCT_PER_100_STARDUST * (
        stacks / 100.0
    )
    detail = f"Executes below {threshold_pct:.1f}% max HP"
    max_hp = ctx.target.get("target_max_health", 0.0)
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
    "R": by_option(
        "r_empowered",
        {
            False: simple_damage(attr="Magic Damage", dmg_type="magic"),
            True: simple_damage(
                attr="Empowered Magic Damage",
                dmg_type="magic",
                source=("R", 1),
                cooldown_from=("R", 0),
            ),
        },
        default=False,
    ),
}

parse_abilities = build_parser(SLOTS, "Aurelion Sol")
