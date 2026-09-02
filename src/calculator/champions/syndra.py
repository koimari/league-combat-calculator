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
  (wider angle, 70% slow) is utility only. Its authored stun is the
  one slot in this kit whose cast order is a mechanic rather than a
  preference, which is what ``CAST_DEPENDENCIES`` below declares.
- R (Unleashed Power) must read "Magic Damage per Sphere" — the
  "Minimum/Maximum Magic Damage" rows are precomputed 3- and 7-sphere
  totals that would double-count with the sphere-count option. The
  100-splinter upgrade executes a target when R leaves it below 15% of
  maximum health. The entry carries that terminal threshold into the
  shared participant ledger.
"""

from typing import Any

from ..ability_spec import DamagePart
from ..binary_roots import data_value, spell_object
from ..cast_dependency import CastDependency, SuppressedInference
from .engine import BUFF, SlotCtx, build_parser
from .inputs import int_option
from .slotlib import (
    ability_name,
    damage_entry,
    extract_cast_time,
    extract_cooldown,
    extract_named,
    extract_resource_cost,
    extract_value,
    simple_damage,
)
from .source_receipts import load_champion_sources

# Transcendent's full-splinter upgrade multiplies TOTAL ability power by
# the binary SyndraPassive.CapstoneAPPerc (stacks multiplicatively with
# item AP like Rabadon's). The passive JSON carries no trace of it.
# https://wiki.leagueoflegends.com/en-us/Syndra
_SYNDRA_P_SPELL = spell_object("Syndra", "SyndraPassive")
_SYNDRA_R_SPELL = spell_object("Syndra", "SyndraR")
TRANSCENDENT_AP_MULTIPLIER = data_value(_SYNDRA_P_SPELL, "CapstoneAPPerc")

# HARDCODED: verify on patch updates — W's 60-splinter bonus true damage
# is (12% + 2% per 100 AP) of W's magic damage. Implemented from the
# wiki formula: the JSON's effect[3] rows are a garbled expansion of
# this same formula (squared-AP units parse as '  2') and are unusable.
# https://wiki.leagueoflegends.com/en-us/Syndra
W_TRUE_RATIO_BASE = 0.12
W_TRUE_RATIO_PER_100_AP = 0.02

# Splinters of Wrath thresholds (the 80-stack E upgrade is utility only).
# The full-splinter cap is the binary MaxStackAmount.
SPLINTERS_Q_SECOND_CHARGE = int(data_value(_SYNDRA_P_SPELL, "Q1UpgradeThreshold"))
SPLINTERS_W_TRUE_DAMAGE = int(data_value(_SYNDRA_P_SPELL, "WUpgradeThreshold"))
SPLINTERS_R_EXECUTE = int(data_value(_SYNDRA_P_SPELL, "RUpgradeThreshold"))
SPLINTERS_FULL = int(data_value(_SYNDRA_P_SPELL, "MaxStackAmount"))
_MAX_SPLINTERS = SPLINTERS_FULL

R_EXECUTE_HEALTH_RATIO = data_value(_SYNDRA_R_SPELL, "UpgradeExecuteThreshold")

_DEFAULT_SPLINTERS = 120
_R_MIN_SPHERES = int(data_value(_SYNDRA_R_SPELL, "MinSpheresToUse"))
_R_MAX_SPHERES = int(data_value(_SYNDRA_R_SPELL, "MaxSpheresToUse"))
_DEFAULT_R_SPHERES = _R_MIN_SPHERES


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

    ap = ctx.stat("ability_power")
    delta = ap * TRANSCENDENT_AP_MULTIPLIER
    ctx.stats["ability_power"] = ap + delta

    return {
        "name": ability_name(ability),
        "damage_type": "magic",
        "total_raw": 0.0,
        "parts": (),
        "stat_buff": {"ability_power": delta},
    }


_transcendent.phase = BUFF


# ---------------------------------------------------------------------------
# Q: Dark Sphere — R's Q-only ability haste folded into the cooldown
# ---------------------------------------------------------------------------

# One sphere, one detonation ("appears after a 0.6-second delay, dealing
# magic damage to nearby enemies") — one part and one hit, which is the
# certification that carries Q's reviewed control answer into the ledger.
_q_damage = simple_damage(
    attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
)


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
        global_haste = ctx.stat("ability_haste") + ctx.stat("basic_ability_haste")
        entry["cooldown"] *= (100.0 + global_haste) / (100.0 + global_haste + q_haste)
    return entry


def _dark_sphere_second_charge(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q2: the 40-splinter second charge — one extra Q cast at fight open.

    Cooldown 0.0 is the engine's cast-exactly-once idiom (timed mode
    schedules it once at the first free moment; one-rotation mode casts
    every entry once anyway). Charge recharge beyond the opener is not
    simulated.

    ``recast_of="Q"`` is the single authority for this row's parentage
    (D-11): it is what keeps the charge riding Q's slot in a requested
    cast order instead of being dropped, and what the rotation resolver
    reads to place it after Q. Nothing may infer the link from the name.

    Parentage is not price. A stocked charge is a whole cast of Dark
    Sphere and pays Dark Sphere's mana, so the cost is read off Q's own
    cached cost row at Q's rank — the engine's free-recast default is for
    a recast that a single paid cast bought, which this is not:

        Transcendent Bonus: Collecting 40 Splinters of Wrath causes
        Syndra to periodically stock a Dark Sphere charge, up to a
        maximum of 2.

    (``data/champions.json`` Syndra Q, effect 2 — the charge gates
    availability and says nothing about price.)
    """
    if _splinters(ctx) < SPLINTERS_Q_SECOND_CHARGE:
        return None
    ranked = ctx.ranked("Q")
    if ranked is None:
        return None
    ability, rank = ranked

    total = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    name = ability_name(ability)
    # A stocked charge is a whole cast of Dark Sphere, so it is the same
    # one sphere and one detonation Q certifies above.
    entry = damage_entry(
        f"{name} (2nd charge)",
        rank,
        0.0,
        total,
        "magic",
        event_order_certified="single_hit",
    )
    entry["recast_of"] = "Q"
    entry["resource_type"] = str(ability.get("resource", "NONE"))
    entry["resource_cost"] = extract_resource_cost(ability, rank, ctx.level)
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
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked

    magic = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    cooldown = extract_cooldown(ability, rank)
    name = ability_name(ability)
    # One landing either way: the thrown target deals its damage "once
    # they land", which is the instant this row certifies.  Above 60
    # splinters that landing is split into a magic and a true part, which
    # is still one landing (``engine._certify_shared_instant``).
    if _splinters(ctx) < SPLINTERS_W_TRUE_DAMAGE:
        return damage_entry(
            name,
            rank,
            cooldown,
            magic,
            "magic",
            event_order_certified="single_hit",
        )

    ap = ctx.stat("ability_power")
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
        "event_order_certified": "single_hit",
    }


# ---------------------------------------------------------------------------
# R: Unleashed Power — per-sphere damage x sphere count
# ---------------------------------------------------------------------------


def _unleashed_power(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: sphere-count option x "Magic Damage per Sphere" (one hit per
    sphere; the Min/Max JSON rows are derived totals, never read)."""
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked

    per_sphere = extract_named(
        ability, "Magic Damage per Sphere", rank, ctx.stats, ctx.target
    )
    spheres = int(ctx.options.get("r_spheres", _DEFAULT_R_SPHERES))
    spheres = min(max(spheres, _R_MIN_SPHERES), _R_MAX_SPHERES)

    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        per_sphere * spheres,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", per_sphere, count=spheres),)
    if _splinters(ctx) >= SPLINTERS_R_EXECUTE:
        entry["execute_threshold_ratio"] = R_EXECUTE_HEALTH_RATIO
        entry["execute_source"] = entry["name"]
    return entry


OPTIONS: list[dict[str, Any]] = [
    int_option(
        "splinters",
        _DEFAULT_SPLINTERS,
        minimum=0,
        maximum=_MAX_SPLINTERS,
        label="Splinters of Wrath stacks (40: Q gains a 2nd charge; 60: W "
        "bonus true damage; 100: R executes below 15% max HP; 120: +15% "
        "total AP)",
    ),
    int_option(
        "r_spheres",
        _DEFAULT_R_SPHERES,
        minimum=_R_MIN_SPHERES,
        maximum=_R_MAX_SPHERES,
        label="Dark Spheres hit by R (3 fired + up to 4 already on the field)",
    ),
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
    "At 100+ splinters R executes a target when R leaves it below 15% "
    "maximum health; the resolved combo places R after the other damage casts",
    "R sphere count is user-set (default 3 = no setup; max 7 with "
    "spheres banked on the field); the Min/Max JSON damage rows are "
    "derived totals and are not used",
    "E is assumed to scatter a sphere into the target (the standard QE "
    "combo), so its cast is authored as a stun event (MODULE_CC) for "
    "CC-triggered item passives (Imperial Mandate, Fimbulwinter, …); the "
    "stun itself adds no damage. The 80-splinter upgrade (wider angle, "
    "slow), the sphere-less knockback, and W's slow remain unmodeled "
    "utility",
    "R's passive 10/20/30 ability haste applies to Q's cooldown only",
]

SLOTS = {
    # BUFF phase first: the 120-splinter AP multiplier must be live
    # before any damage slot parses.
    "P": _transcendent,
    "Q": _dark_sphere,
    "Q2": _dark_sphere_second_charge,
    "W": _force_of_will,
    # The stun itself is declared once, in MODULE_CC below; what E states
    # here is the separate claim that its one hit lands at the cast
    # boundary, which is what puts the marker in the event ledger.
    "E": simple_damage(
        attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
    ),
    "R": _unleashed_power,
}

# Reviewed crowd control, read from the cached kit.  Q (Dark Sphere)
# "appears after a 0.6-second delay, dealing magic damage to nearby
# enemies" with no control clause, and Q2 is a stocked charge of that same
# cast.  E (Scatter the Weak) scatters a sphere into the target, and
# "targets hit are also stunned for 1.25 seconds".
#
# W (Force of Will) throws the grabbed target and deals its damage "once
# they land"; "all targets hit are slowed by 25% for 1.5 seconds".
#
# R stays UNREVIEWED, so this kit keeps the coarse control-armed scan.
# Unleashed Power is control-free ("each dealing magic damage upon hit")
# but its row is one aggregated part of ``r_spheres`` hits with no sourced
# cadence between them — a schedule, which ``single_hit`` refuses.
MODULE_CC = {"E": "stun", "Q": "none", "Q2": "none", "W": "slow"}

# The revision these declarations were read from, in the shape
# scripts/cast_dependency_audit.py will resolve against the committed
# wiki audit once this phase's audit slice lands -- that script is not
# in the tree yet, so today this string is shape-checked and pinned
# equal to SOURCES by test, nothing more. It is the same parent entry
# SOURCES publishes below.
_WIKI_SOURCE = "https://wiki.leagueoflegends.com/en-us/Syndra@4024662"

_STUN_RIDES_A_SPHERE = (
    "Scatter the Weak's stun is the Dark Sphere's, not the cone's: the "
    "wave knocks a sphere through the target and only 'targets hit are "
    "also stunned for 1.25 seconds'. E carries cc_kind='stun' on exactly "
    "that assumption, so a sphere has to be on the field before E is cast "
    "or the authored stun has no referent — and an amplifier keyed on "
    "immobilizing CC would then price a stun that never happened."
)

_INFERENCE_READS_THE_STUN_BACKWARDS = (
    "The detector reads E's cc_kind and fans a cc_setup edge out to every "
    "castable damage row, Q among them, which would place E first. E's "
    "stun is the sphere's consumer, never its setup; the inference has "
    "the mechanic the wrong way round."
)

CAST_DEPENDENCIES = (
    CastDependency(
        slot="E",
        requires="Q",
        kind="cc_enabler",
        reason=_STUN_RIDES_A_SPHERE,
        source=_WIKI_SOURCE,
        suppresses=(
            SuppressedInference(
                setup="E",
                consume="Q",
                kind="cc_setup",
                reason=_INFERENCE_READS_THE_STUN_BACKWARDS,
            ),
        ),
    ),
    CastDependency(
        slot="E",
        requires="Q2",
        kind="cc_enabler",
        reason=(
            "The 40-splinter second charge is another Dark Sphere ('causes "
            "Syndra to periodically stock a Dark Sphere charge, up to a "
            "maximum of 2'), so it is subject to the same rule as Q: the "
            "stored charge is spent before E, not after it. Load-bearing, "
            "not a restatement of E requires Q — without it the resolver's "
            "tie-break ranks E ahead of Q2, which has no outgoing edges, "
            "and the derived order changes (D-83)."
        ),
        source=_WIKI_SOURCE,
        suppresses=(
            SuppressedInference(
                setup="E",
                consume="Q2",
                kind="cc_setup",
                reason=_INFERENCE_READS_THE_STUN_BACKWARDS,
                latent_reason=(
                    "No E->Q2 cc_setup edge exists in this tree: the "
                    "detector's _castable() requires cooldown > 0 and Q2 "
                    "carries the 0.0 cast-exactly-once cooldown, so the "
                    "fan-out skips it. Declared latent rather than dropped "
                    "because a Q2 that ever gains a real charge cooldown "
                    "brings the reversed edge with it. This is the fact "
                    "the ('E','Q2') seed exception in "
                    "tests/test_f3_rotation_all.py claimed while silently "
                    "passing, moved where the audit can see it (D-84)."
                ),
            ),
        ),
    ),
)

parse_abilities = build_parser(SLOTS, "Syndra", cc_kinds=MODULE_CC)


SOURCES = load_champion_sources("Syndra")
