"""Syndra — slot map for the archetype engine.

Why each slot is non-generic:
- P (Transcendent) is a splinter-stack threshold system the JSON cannot
  express: its only leveling row ("Per-Level Scaling" 20/25/30/35/40) is
  stack bookkeeping, not damage. At 120 splinters the passive multiplies
  TOTAL AP by 1.15 — a BUFF-phase slot listed first, so every damage
  slot parses against the multiplied AP. The 15% has no JSON home
  (module constant). Below 120 the passive grants nothing direct and
  emits no row.
- Q (Dark Sphere) is a plain "Magic Damage" read wrapped twice over the
  generic path: R passively grants 10/20/30 ability haste TO Q ONLY
  (R[0] effect[0] "Ability Haste"), folded into the emitted cooldown
  against the build's global haste so the fight engine's own haste
  division lands on the true 7 x 100/(100 + Q haste + global haste);
  and at 40+ splinters Q holds 2 charges, modeled as the synthetic
  "Q2" slot below.
- Q2 is the second charge: ONE extra Q cast available at fight open
  (cooldown 0.0 = the engine's cast-exactly-once idiom; charge
  recharge beyond the opener is not simulated).
- W (Force of Will) at 60+ splinters adds bonus TRUE damage equal to
  (12% + 2% per 100 AP) of W's magic damage — quadratic in AP, so the
  formula lives here as module constants. The JSON's effect[3] rows
  ("Bonus True Damage" / "Total Mixed Damage") are a half-parsed
  expansion of this exact formula with garbled squared-AP units
  ('  2') and must never be read (sanity anchor: their flat 8.4 at
  rank 1 = 0.12 x 70).
- E (Scatter the Weak) is a clean "Magic Damage" read; explicit attr
  for symmetry with the rest of the kit. The 80-splinter upgrade
  (wider angle, 70% slow) is utility only.
- R (Unleashed Power) must read "Magic Damage per Sphere" — the
  "Minimum/Maximum Magic Damage" rows are precomputed 3- and 7-sphere
  totals that would double-count with the sphere-count option. The
  100-splinter execute is not modeled (the fight target never dies —
  the Darius R call).
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import BUFF, SlotCtx, build_parser
from .slotlib import (
    damage_entry,
    extract_cast_time,
    extract_cooldown,
    extract_named,
    extract_value,
    simple_damage,
)

# HARDCODED: verify on patch updates — Transcendent's 120-splinter
# upgrade multiplies TOTAL ability power by 15% (stacks multiplicatively
# with item AP like Rabadon's). The passive JSON carries no trace of it.
# https://wiki.leagueoflegends.com/en-us/Syndra
TRANSCENDENT_AP_MULTIPLIER = 0.15

# HARDCODED: verify on patch updates — W's 60-splinter bonus true damage
# is (12% + 2% per 100 AP) of W's magic damage. Implemented from the
# wiki formula: the JSON's effect[3] rows are a garbled expansion of
# this same formula (squared-AP units parse as '  2') and are unusable.
# https://wiki.leagueoflegends.com/en-us/Syndra
W_TRUE_RATIO_BASE = 0.12
W_TRUE_RATIO_PER_100_AP = 0.02

# Splinters of Wrath thresholds (wiki; the 80-stack E upgrade is
# utility only and the 100-stack R execute is not modeled).
SPLINTERS_Q_SECOND_CHARGE = 40
SPLINTERS_W_TRUE_DAMAGE = 60
SPLINTERS_FULL = 120
_MAX_SPLINTERS = 120

_DEFAULT_SPLINTERS = 120
_R_MIN_SPHERES = 3  # R always fires 3 of its own
_R_MAX_SPHERES = 7  # plus up to 4 Dark Spheres already on the field
_DEFAULT_R_SPHERES = 3


def _splinters(ctx: SlotCtx) -> int:
    """Current Splinters of Wrath stacks — the ONE source every
    threshold consumer (P, Q2, W) reads."""
    stacks = int(ctx.options.get("splinters", _DEFAULT_SPLINTERS))
    return min(max(stacks, 0), _MAX_SPLINTERS)


# ---------------------------------------------------------------------------
# P: Transcendent — BUFF phase, listed first (all damage sees the AP)
# ---------------------------------------------------------------------------


def _transcendent(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: at 120 splinters, +15% total AP applied before all damage.

    Mutates the parse context's AP (the BUFF-phase guarantee: Q/W/E/R
    scale off the multiplied total) and echoes the delta in
    ``stat_buff`` so the fight engine's stats panel and AP-scaling item
    effects see the fight-effective AP. Below 120 the passive has no
    direct damage or stat effect — no row.
    """
    ability = ctx.ability()
    if ability is None or _splinters(ctx) < SPLINTERS_FULL:
        return None

    ap = ctx.stats.get("ability_power", 0.0)
    delta = ap * TRANSCENDENT_AP_MULTIPLIER
    ctx.stats["ability_power"] = ap + delta

    return {
        "name": ability.get("name", "Transcendent"),
        "damage_type": "magic",
        "total_raw": 0.0,
        "parts": (),
        "stat_buff": {"ability_power": delta},
    }


_transcendent.phase = BUFF


# ---------------------------------------------------------------------------
# Q: Dark Sphere — R's Q-only ability haste folded into the cooldown
# ---------------------------------------------------------------------------

_q_damage = simple_damage(attr="Magic Damage", dmg_type="magic")


def _q_only_haste(ctx: SlotCtx) -> float:
    """R's passive 10/20/30 ability haste, granted to Q alone."""
    r_ability = ctx.ability("R")
    if r_ability is None:
        return 0.0
    r_rank = ctx.rank_for("R")
    if r_rank < 1:
        return 0.0
    return extract_value(r_ability, "Ability Haste", r_rank)


def _dark_sphere(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: plain magic damage; cooldown folds in R's Q-only haste.

    The fight engine divides every cooldown by (100 + global haste)/100,
    with no per-slot haste hook — so the emitted base is pre-scaled by
    (100 + global) / (100 + global + Q haste), which lands the engine's
    own division exactly on 7 x 100 / (100 + global + Q haste).
    """
    entry = _q_damage(ctx)
    if entry is None:
        return None
    q_haste = _q_only_haste(ctx)
    if q_haste > 0:
        global_haste = ctx.stats.get("ability_haste", 0.0) + ctx.stats.get(
            "basic_ability_haste", 0.0
        )
        entry["cooldown"] *= (100.0 + global_haste) / (100.0 + global_haste + q_haste)
    return entry


def _dark_sphere_second_charge(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q2: the 40-splinter second charge — one extra Q cast at fight open.

    Cooldown 0.0 is the engine's cast-exactly-once idiom (timed mode
    schedules it once at the first free moment; one-rotation mode casts
    every entry once anyway). Charge recharge beyond the opener is not
    simulated.
    """
    if _splinters(ctx) < SPLINTERS_Q_SECOND_CHARGE:
        return None
    ability = ctx.ability("Q")
    if ability is None:
        return None
    rank = ctx.rank_for("Q")
    if rank < 1:
        return None

    total = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    name = ability.get("name", "Dark Sphere")
    entry = damage_entry(f"{name} (2nd charge)", rank, 0.0, total, "magic")
    # The engine can only auto-stamp cast time from the slot's own JSON
    # entry; a synthetic slot copies its parent's.
    cast_time = extract_cast_time(ability)
    if cast_time > 0:
        entry["cast_time"] = cast_time
    return entry


# ---------------------------------------------------------------------------
# W: Force of Will — 60-splinter bonus true damage (quadratic in AP)
# ---------------------------------------------------------------------------


def _force_of_will(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: base magic damage; at 60+ splinters a bonus TRUE damage part
    equal to (12% + 2% per 100 AP) of the magic damage."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    magic = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    cooldown = extract_cooldown(ability, rank)
    name = ability.get("name", "Force of Will")
    if _splinters(ctx) < SPLINTERS_W_TRUE_DAMAGE:
        return damage_entry(name, rank, cooldown, magic, "magic")

    ap = ctx.stats.get("ability_power", 0.0)
    true_bonus = (W_TRUE_RATIO_BASE + W_TRUE_RATIO_PER_100_AP * ap / 100.0) * magic
    return {
        "name": name,
        "rank": rank,
        "cooldown": cooldown,
        "damage_type": "mixed",
        "total_raw": magic + true_bonus,
        # Magic part FIRST: the evaluator's first-part return is the
        # Horizon Focus trigger for mixed entries.
        "parts": (DamagePart("magic", magic), DamagePart("true", true_bonus)),
    }


# ---------------------------------------------------------------------------
# R: Unleashed Power — per-sphere damage x sphere count
# ---------------------------------------------------------------------------


def _unleashed_power(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: sphere-count option x "Magic Damage per Sphere" (one hit per
    sphere; the Min/Max JSON rows are derived totals, never read)."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    per_sphere = extract_named(
        ability, "Magic Damage per Sphere", rank, ctx.stats, ctx.target
    )
    spheres = int(ctx.options.get("r_spheres", _DEFAULT_R_SPHERES))
    spheres = min(max(spheres, _R_MIN_SPHERES), _R_MAX_SPHERES)

    entry = damage_entry(
        ability.get("name", "Unleashed Power"),
        rank,
        extract_cooldown(ability, rank),
        per_sphere * spheres,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", per_sphere, count=spheres),)
    return entry


OPTIONS: list[dict[str, Any]] = [
    {
        "key": "splinters",
        "type": "int",
        "default": _DEFAULT_SPLINTERS,
        "min": 0,
        "max": _MAX_SPLINTERS,
        "label": (
            "Splinters of Wrath stacks (40: Q gains a 2nd charge; 60: W "
            "bonus true damage; 100: R execute — not modeled; 120: +15% "
            "total AP)"
        ),
    },
    {
        "key": "r_spheres",
        "type": "int",
        "default": _DEFAULT_R_SPHERES,
        "min": _R_MIN_SPHERES,
        "max": _R_MAX_SPHERES,
        "label": "Dark Spheres hit by R (3 fired + up to 4 already on the field)",
    },
]

ASSUMPTIONS = [
    "Splinter stacks are user-set (default 120 = fully stacked late "
    "game); stack accumulation during the fight is not simulated",
    "At 120 splinters the +15% total AP multiplier applies before all "
    "damage calculation",
    "At 40+ splinters Q's second charge is modeled as one extra Q cast "
    "available when the fight opens; charge recharge beyond that is not "
    "simulated",
    "At 60+ splinters W's bonus true damage uses the exact formula "
    "(12% + 2% per 100 AP) of W's magic damage, computed in the module "
    "(quadratic in AP)",
    "R's 100-splinter execute (kills targets it would bring below 15% "
    "max HP) is not modeled — the fight target never dies",
    "R sphere count is user-set (default 3 = no setup; max 7 with "
    "spheres banked on the field); the Min/Max JSON damage rows are "
    "derived totals and are not used",
    "E's 80-splinter upgrade (wider angle, slow) and all CC (stun, "
    "knockback, W slow) are utility only — no damage contribution",
    "R's passive 10/20/30 ability haste applies to Q's cooldown only",
]

SLOTS = {
    # BUFF phase first: the 120-splinter AP multiplier must be live
    # before any damage slot parses.
    "P": _transcendent,
    "Q": _dark_sphere,
    "Q2": _dark_sphere_second_charge,
    "W": _force_of_will,
    "E": simple_damage(attr="Magic Damage", dmg_type="magic"),
    "R": _unleashed_power,
}

parse_abilities = build_parser(SLOTS, "Syndra")


# Authoritative review metadata (issue #161).
SOURCES = [
    {
        "label": "Local League Wiki cache",
        "url": "https://wiki.leagueoflegends.com/en-us/Syndra",
        "revision_id": 4024662,
        "revision_timestamp": "2026-06-02T13:31:37Z",
    }
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in SLOTS else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
