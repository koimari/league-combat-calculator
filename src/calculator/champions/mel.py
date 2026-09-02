"""Mel — CP10.4 full-entry-reviewed packet module.

E5-2 fixes:

- W (Rebuttal): the reviewed spec read "Replicated Projectile Magic
  Damage Modifier" (40-60% + 5% per 100 AP) as FLAT magic damage.  That
  attribute is a percentage of the ORIGINAL enemy projectile's damage;
  the calculator models no enemy projectile source, so the slot prices
  no damage (shield + conditional reflection are state, documented).

- R (Golden Eclipse): the reviewed spec read only the flat "Magic
  Damage" row (125/200/275 + 30% AP) and dropped the per-Overwhelm-
  stack term.  The wiki row's third modifier is "(4/7/10 + 4% AP) per
  Overwhelm stack on the target" (data/champions.json R "Magic
  Damage"), and P's Overwhelm prose says Mel applies a stack for each
  damage instance.  R now prices the flat row PLUS the per-stack term
  times an explicit ``r_overwhelm_stacks`` option (default 3 — the
  Overwhelm stacks accumulated before the blast in a one-rotation
  combo).  The P stored-damage execute (first stack stores
  50/60/70/80 + 10% AP, +2/3/4/5 + 0.75% AP per additional stack,
  consumed when the stored total exceeds the target's current health)
  is a kill-boundary execute and is documented, not priced as damage.

Roadmap slot session (2026-08-21) closes this module's last two
``out_of_scope`` rows.  Both labels were stale, for DIFFERENT reasons:

  - P (Searing Brilliance) is now ``modeled``.  The packet asset's stock
    reason ("no enemy-damage formula for this slot") was simply wrong.
    The slot carries THREE mechanics and the third is ordinary,
    priceable damage: "Mel's ability casts each generate 3 stacks of
    Searing Brilliance for 5 seconds ... Her next basic attack consumes
    all stacks of Searing Brilliance to additionally fire an equal
    number of blazing projectiles at the target.  Each projectile deals
    8 : 30 (based on level) (+ 4% AP) magic damage" (data/champions.json
    Mel P, third effect, whose two "Per-Level Scaling" rows hold the
    per-projectile ramp and the 9-projectile maximum).  It is priced as
    a cast-armed empower window (the Taric Bravado primitive) — see
    ``_searing_brilliance``.  The Overwhelm execute (mechanic 2) stays a
    documented kill boundary and does NOT ride the Zeri
    ``execute_threshold_ratio`` seam — see ``_OVERWHELM_EXECUTE_BOUNDARY``.
  - W (Rebuttal) becomes ``no_damage`` with a named receipt, replacing
    the stale ``out_of_scope`` label: the slot owns no damage of its own
    on any of the three cached sources — see ``_rebuttal``.
"""

from typing import Any

from ..ability_spec import DamagePart
from ..binary_roots import (
    calculation_coefficient,
    calculation_interpolation,
    data_value,
    spell_object,
)
from .engine import CC_PER_PART, ONHIT, SlotCtx
from .inputs import int_option
from .module_contract import coverage
from .module_helpers import ranked_slot
from .packet_module import build_packet_module
from .slotlib import (
    ability_name,
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
    find_named_leveling,
    on_hit_entry,
)

PACKET_SHA256 = "4729cb0ee938dd410196bc3e6ea901bac4caf07fbe25859ce9532c9bf6648aea"


# Default Overwhelm stacks the blast detonates in a one-rotation combo.
# P prose: "Mel's basic attacks and abilities apply a stack of Overwhelm
# for each instance of damage they deal"; Q alone fires 10 bolts, so a
# modest 3-stack default is conservative and user-tunable.
_R_DEFAULT_OVERWHELM_STACKS = 3
# The per-stack term's fixed AP ratio: " (+ 4% AP) per Overwhelm stack".
_R_PER_STACK_AP_RATIO = 0.04

# ---------------------------------------------------------------------------
# P (Searing Brilliance) — game-file rule declaration.
# Verify on patch updates against "MelPassive" {64e86cf4} in the game file
# data/bin/characters/mel.bin.json:
#   mSpell.DataValues       PassiveBonusMissiles      3.0 (every rank)
#                           MaxPassiveBonusMissiles   9.0 (every rank)
#                           BonusAttackDuration       5.0 (every rank)
#   mSpell.mSpellCalculations.PassiveBonusMissileDamage
#       ByCharLevelInterpolationCalculationPart  8.0 -> 30.0
#     + StatByCoefficientCalculationPart         0.04  (ability power)
# Every one of those five numbers is cross-checked against the cached
# wiki entry below (3 stacks per cast / 9 maximum / 5 seconds in the P
# prose; the 8 : 30 ramp and the 9x maximum as the two "Per-Level
# Scaling" rows), so a patch that moves either source fails loudly.
# ---------------------------------------------------------------------------
_MEL_P_SPELL = spell_object("Mel", "MelPassive")
_P_MISSILES_PER_CAST = int(data_value(_MEL_P_SPELL, "PassiveBonusMissiles"))
_P_MAX_MISSILES = int(data_value(_MEL_P_SPELL, "MaxPassiveBonusMissiles"))
_P_WINDOW_DURATION = data_value(_MEL_P_SPELL, "BonusAttackDuration")
_P_MISSILE_AP_RATIO = calculation_coefficient(_MEL_P_SPELL, "PassiveBonusMissileDamage")
_P_MISSILE_LEVEL_1, _P_MISSILE_LEVEL_18 = calculation_interpolation(
    _MEL_P_SPELL, "PassiveBonusMissileDamage"
)
# The cached wiki rows the game-file ladder must reproduce.  Occurrence 0
# is the per-projectile ramp ("8 : 30 (based on level)"); occurrence 1 is
# the all-9-projectiles total ("72 : 270"), which corroborates the
# 9-missile cap independently of the binary.
_P_WIKI_ATTRIBUTE = "Per-Level Scaling"
# Rounding headroom: the cached rows are stored to 2 decimals, so the
# per-projectile check allows +/- 0.01 and the 9x total check allows the
# same error amplified nine-fold (worst observed 0.0047 and 0.04).
_P_PER_MISSILE_TOLERANCE = 0.01
_P_TOTAL_TOLERANCE = 0.06
# Every slot whose cast generates Searing Brilliance stacks: "Mel's
# ability casts each generate 3 stacks" — all four ability slots.
_P_ARMED_BY = ("Q", "W", "E", "R")

_OVERWHELM_EXECUTE_BOUNDARY = (
    "Overwhelm (P mechanic 2) stores 50/60/70/80 (+ 10% AP) magic damage "
    "with the first stack and 2/3/4/5 (+ 0.75% AP) more per stack, and "
    "detonates only when 'the total POST-MITIGATION damage stored "
    "exceeds the target's current health and shields'.  It is a kill "
    "boundary, priced as neither damage nor an execute ratio: the "
    "engine's execute seam (execute_threshold_ratio, Zeri's Living "
    "Battery) takes a fraction of the target's MAXIMUM health, and "
    "Zeri's threshold is itself a health value.  Mel's threshold is a "
    "DAMAGE quantity whose post-mitigation size depends on the target's "
    "magic resistance and on Mel's own magic penetration at fight time; "
    "a champion module parses before mitigation exists and owns no "
    "mitigation function, so the only ratio it could stamp is the "
    "unmitigated one — strictly larger than the real threshold, i.e. "
    "invented kills.  The slot therefore documents the mechanic and "
    "prices Searing Brilliance only."
)


def _searing_brilliance_per_missile(ctx: SlotCtx, ability: dict[str, Any]) -> float:
    """One blazing projectile's damage at ``ctx.level``, cross-checked.

    The magnitude comes from the cached wiki row (the level ramp the
    calculator can index at any level up to MAX_LEVEL); the game file's
    ``PassiveBonusMissileDamage`` interpolation (8.0 -> 30.0 by champion
    level, + 0.04 AP) is asserted against it here, and the second cached
    row (the all-9-projectile total) is asserted to be exactly nine
    times the first.  A patch that moves either source raises instead of
    silently pricing a stale projectile.
    """
    leveling = find_named_leveling(ability, _P_WIKI_ATTRIBUTE, occurrence=0)
    modifiers = (leveling or {}).get("modifiers") or []
    values = list(modifiers[0].get("values") or []) if modifiers else []
    if not values:
        raise ValueError(
            "Mel P (Searing Brilliance) is missing its cached "
            f"{_P_WIKI_ATTRIBUTE!r} row; the blazing-projectile damage "
            "cannot be sourced"
        )
    index = min(max(int(ctx.level), 1), len(values)) - 1
    cached = float(values[index])
    interpolated = _P_MISSILE_LEVEL_1 + (_P_MISSILE_LEVEL_18 - _P_MISSILE_LEVEL_1) * (
        index / 17.0
    )
    if abs(cached - interpolated) > _P_PER_MISSILE_TOLERANCE:
        raise ValueError(
            "Mel P (Searing Brilliance) projectile damage drifted: the game "
            f"file interpolates {interpolated:.6g} at level {index + 1}, the "
            f"cached wiki {_P_WIKI_ATTRIBUTE!r} row gives {cached:.6g}"
        )

    total_leveling = find_named_leveling(ability, _P_WIKI_ATTRIBUTE, occurrence=1)
    total_modifiers = (total_leveling or {}).get("modifiers") or []
    total_values = (
        list(total_modifiers[0].get("values") or []) if total_modifiers else []
    )
    if not total_values:
        raise ValueError(
            "Mel P (Searing Brilliance) is missing its cached maximum-stack "
            f"{_P_WIKI_ATTRIBUTE!r} row; the {_P_MAX_MISSILES}-projectile cap "
            "cannot be corroborated"
        )
    cached_total = float(total_values[min(index, len(total_values) - 1)])
    if abs(cached_total - _P_MAX_MISSILES * cached) > _P_TOTAL_TOLERANCE:
        raise ValueError(
            "Mel P (Searing Brilliance) stack cap drifted: the cached "
            f"maximum-stack row gives {cached_total:.6g} at level "
            f"{index + 1}, which is not {_P_MAX_MISSILES} x the cached "
            f"per-projectile {cached:.6g}"
        )
    return cached + _P_MISSILE_AP_RATIO * float(ctx.stat("ability_power") or 0.0)


def _searing_brilliance(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: the stack-consuming empowered attack — a cast-armed on-hit.

    Every ability cast generates 3 Searing Brilliance stacks for 5
    seconds (capped at 9) and Mel's next basic attack consumes them all
    to fire one blazing projectile per stack.  That is the engine's
    cast-armed empower window (Taric's Bravado primitive): one arming
    cast, one empowered swing, no flat multiplication by cast count.

    ``charges_per_arm`` and ``max_charges`` are 1 because the kit grants
    ONE empowered attack, not one per stack — the stacks are the
    projectile COUNT inside that single swing, priced by
    ``p_searing_brilliance_missiles`` (default 3, one cast's worth;
    the sourced maximum 9 is the option's ceiling).  Consequence, a
    deliberate understatement in the same direction as Miss Fortune's
    Love Tap: when several casts stack before one swing the live game
    detonates up to 9 projectiles on that swing while this row prices
    the option's count on each consumed charge.  ``refresh_on_consume``
    is deliberately absent — no cached source says consuming the buff
    restarts its 5 seconds.
    """
    ability = ctx.ability("P", 0)
    if ability is None:
        return None
    per_missile = _searing_brilliance_per_missile(ctx, ability)
    missiles = int(ctx.option("p_searing_brilliance_missiles"))
    missiles = max(0, min(missiles, _P_MAX_MISSILES))
    name = ability_name(ability)
    entry = on_hit_entry(name, per_missile * missiles, "magic")
    entry["on_hit"]["empower_window"] = {
        "armed_by": _P_ARMED_BY,
        "duration": _P_WINDOW_DURATION,
        "charges_per_arm": 1,
        "max_charges": 1,
        "consumed_by": ("auto",),
    }
    entry["certified_constants"] = {
        "missiles_per_cast": _P_MISSILES_PER_CAST,
        "max_missiles": _P_MAX_MISSILES,
        "window_duration": _P_WINDOW_DURATION,
        "missile_ap_ratio": _P_MISSILE_AP_RATIO,
        "missile_level_1": _P_MISSILE_LEVEL_1,
        "missile_level_18": _P_MISSILE_LEVEL_18,
    }
    entry["detail"] = (
        f"{missiles} blazing projectile(s) of {per_missile:.6g} magic damage "
        f"on the empowered attack (level {ctx.level}); an ability cast arms "
        f"one empowered attack for {_P_WINDOW_DURATION:g}s, stacking "
        f"{_P_MISSILES_PER_CAST} projectiles per cast up to {_P_MAX_MISSILES}. "
        + _OVERWHELM_EXECUTE_BOUNDARY
    )
    return entry


_searing_brilliance.phase = ONHIT


def _rebuttal(ctx: SlotCtx):
    """W: shield + conditional projectile reflection, priced ``no_damage``.

    Rebuttal owns no damage on any cached source, so the slot is
    ``no_damage`` rather than a gap awaiting a kernel:

    * Wiki (data/champions.json Mel W): "Shield" (80-200 + 70% AP), plus two
      "Replicated Projectile ... Modifier" rows (40-60% magic, 28-42%
      physical) whose unit is "% of the original damage" of an enemy
      projectile, not a damage amount.
    * Game binary (data/bin/characters/mel.bin.json,
      Characters/Mel/Spells/MelWAbility/MelW): mSpellCalculations holds only
      ``DamagePercent`` (0.40/0.45/0.50/0.55/0.60, + 0.0005 per AP) and
      ``ShieldAmount`` (80-200 + 0.7 AP).  ``PhysDamageMod`` 0.30 is the
      conversion step behind the cached 28% (0.7 x 40%).
    * Atoms (data/atoms/mel.atoms.json): MelW emits ``cc-immunity``,
      ``shield`` and ``projectile-destruction``, and no ``damage.*`` atom.

    The multiplicand is structurally absent: this calculator models one
    attacker against a target that never casts, so no enemy projectile can
    exist for any build.
    """
    ability = ctx.ability("W", 0)
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    return {
        "name": ability_name(ability),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "magic",
        "total_raw": 0.0,
        "parts": (),
        "detail": (
            "Rebuttal shields Mel (80-200 + 70% AP) and reflects enemy "
            "projectiles at 40-60% (+ 5% per 100 AP) of their original "
            "damage; no enemy projectile source is modeled — the target "
            "never casts — so the slot prices no damage. The game binary's "
            "MelW carries only DamagePercent and ShieldAmount, and no "
            "damage.* atom exists for MelW."
        ),
    }


def _golden_eclipse(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: flat Magic Damage row + (4/7/10 + 4% AP) per Overwhelm stack."""
    ability = ctx.ability("R", 0)
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    # The wiki's "Magic Damage" row: flat + 30% AP + per-stack term.  The
    # per-stack unit (" (+ 4% AP) per Overwhelm stack on the target") is
    # not a generic scaling unit, so the flat+AP share comes from the row
    # and the per-stack share is priced explicitly below.
    flat_share = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    per_stack = extract_value(ability, "Magic Damage", rank, modifier_index=2)
    per_stack += _R_PER_STACK_AP_RATIO * float(ctx.stat("ability_power") or 0.0)
    stacks = int(ctx.options.get("r_overwhelm_stacks", _R_DEFAULT_OVERWHELM_STACKS))
    stacks = max(0, min(stacks, 50))
    total = flat_share + per_stack * stacks
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
        # One radiant blast on the marked target, so one part and one hit —
        # the certification that carries R's reviewed "no control" into the
        # event ledger.
        event_order_certified="single_hit",
    )
    entry["detail"] = (
        f"{flat_share:g} flat + {per_stack:g} per Overwhelm stack x "
        f"{stacks} stack(s)"
    )
    return entry


@ranked_slot
def _radiant_volley(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """Q: the full 6-10 bolt volley — Initial Explosion + subsequent bolts.

    The reviewed packet priced only the "Initial Explosion Magic Damage"
    row.  The wiki's "Total Magic Damage" row equals the initial
    explosion plus (Number of Bolts - 1) subsequent explosions (160 + 9 x
    13 == 277 at rank 5, and the AP shares 55 + 9 x 5 == 100), so one
    cast against the primary target prices every bolt that lands in the
    target area.  The volley launches over the sourced 0.5 seconds, with
    the bolts distributing evenly.
    """
    initial = extract_named(
        ability, "Initial Explosion Magic Damage", rank, ctx.stats, ctx.target
    )
    subsequent = extract_named(
        ability, "Magic Damage per Subsequent Explosion", rank, ctx.stats, ctx.target
    )
    bolts = max(1, int(extract_value(ability, "Number of Bolts", rank)))
    total = initial + subsequent * (bolts - 1)
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    interval = 0.5 / bolts
    entry["parts"] = (
        DamagePart("magic", amount=initial, time_offset=0.0),
        DamagePart(
            "magic",
            amount=subsequent,
            count=bolts - 1,
            time_offset=interval,
            hit_interval=interval,
        ),
    )
    entry["detail"] = (
        f"{bolts} bolts: initial explosion {initial:g} + {bolts - 1} x "
        f"subsequent {subsequent:g} over the 0.5s volley"
    )
    return entry


@ranked_slot
def _solar_snare(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """E: orb hit + the solar-field DoT (game-file-sourced 0.5s window).

    The reviewed packet priced only the orb.  The orb also emanates a
    field that deals "Field Magic Damage per Tick" every 0.125 seconds;
    the game files (mel.bin.json MelE DataValues) source the field's
    DoTDuration as 0.5s at AreaTicksPerSecond 8, so a target inside the
    field takes 4 ticks (2 / 3.5 / 5 / 6.5 / 8 + 1% AP each), matching
    the wiki's per-second row (8 x per-tick == Field Magic Damage per
    Second) over the 0.5s window.  The field expands after the sourced
    0.5-second delay, so the first tick lands at 0.5s.
    """
    orb = extract_named(ability, "Orb Magic Damage", rank, ctx.stats, ctx.target)
    per_tick = extract_named(
        ability, "Field Magic Damage per Tick", rank, ctx.stats, ctx.target
    )
    total = orb + per_tick * 4
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    # The two halves of Solar Snare do not control alike — "enemies hit by
    # the orb are dealt magic damage and rooted for 1.5 seconds", while
    # "enemies within the field are dealt magic damage and slowed by 30%
    # every 0.125 seconds" — so the reviewed kind is authored per part
    # rather than declared once for the slot.
    entry["parts"] = (
        DamagePart("magic", amount=orb, time_offset=0.0, cc_kind="root"),
        DamagePart(
            "magic",
            amount=per_tick,
            count=4,
            time_offset=0.5,
            hit_interval=0.125,
            cc_kind="slow",
        ),
    )
    entry["dot_duration"] = 0.5
    entry["detail"] = (
        f"orb {orb:g} + 4 field ticks of {per_tick:g} (0.5s DoT at "
        "8 ticks/s, game-file MelE DoTDuration)"
    )
    return entry


# Reviewed crowd control, read from the cached kit.  Q (Radiant Volley)
# is bolts that "explode[] upon landing to deal magic damage to nearby
# enemies" with no control clause, and R (Golden Eclipse) "deal[s] magic
# damage to each of them" and reveals, which is not control.  E's orb and
# field answer differently and are authored per part (see
# ``_solar_snare``).  P's Searing Brilliance projectiles "fire ... at the
# target" and do nothing else, so the slot answers "none" for the
# empowered swing it arms; W authors no damage part of its own.
MODULE_CC = {"P": "none", "Q": "none", "E": CC_PER_PART, "R": "none"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Mel",
    PACKET_SHA256,
    slot_parsers={
        "P": _searing_brilliance,
        "W": _rebuttal,
        "Q": _radiant_volley,
        "E": _solar_snare,
        "R": _golden_eclipse,
    },
    cc_kinds=MODULE_CC,
)

OPTIONS = [
    *list(OPTIONS),
    int_option(
        "r_overwhelm_stacks",
        _R_DEFAULT_OVERWHELM_STACKS,
        minimum=0,
        maximum=50,
        label="Overwhelm stacks on the target when Golden Eclipse detonates",
    ),
    int_option(
        "p_searing_brilliance_missiles",
        _P_MISSILES_PER_CAST,
        minimum=0,
        maximum=_P_MAX_MISSILES,
        label="Searing Brilliance projectiles consumed per empowered attack",
    ),
]

ASSUMPTIONS = [
    *list(ASSUMPTIONS),
    "P (Searing Brilliance) prices the empowered attack: each ability "
    "cast arms ONE empowered basic attack for 5 seconds and the swing "
    "fires 8 : 30 (based on level) (+ 4% AP) magic damage per consumed "
    "stack (data/champions.json Mel P third effect, 'Per-Level Scaling' "
    "occurrence 0; game file mel.bin.json MelPassive "
    "PassiveBonusMissileDamage interpolates the same 8.0 -> 30.0 with a "
    "0.04 AP coefficient, and its PassiveBonusMissiles 3 / "
    "MaxPassiveBonusMissiles 9 / BonusAttackDuration 5.0 match the "
    "cached prose). The projectile count is the "
    "p_searing_brilliance_missiles option (default 3 == one cast's "
    "stacks, ceiling 9 == the sourced cap); a swing that consumed "
    "several casts' stacks at once is therefore UNDERSTATED, never "
    "overstated. Both cached 'Per-Level Scaling' rows are asserted "
    "against the game-file ladder at parse time, so source drift raises.",
    "P's Overwhelm stored-damage execute is documented, not priced: "
    + _OVERWHELM_EXECUTE_BOUNDARY,
    "W (Rebuttal) prices no damage: the 'Replicated Projectile Magic "
    "Damage Modifier' (40-60% + 5% per 100 AP) and its physical twin "
    "(28-42% + 3.5% per 100 AP) are percentages of the original enemy "
    "projectile's damage (data/champions.json W), the game binary's "
    "MelW owns only DamagePercent and ShieldAmount nodes "
    "(data/bin/characters/mel.bin.json), and the atom corpus "
    "emits no damage.* atom for MelW at all — only cc-immunity, "
    "heal-shield.shield and interaction.projectile-destruction. The "
    "calculator's target never casts, so the multiplicand is "
    "structurally absent for every build.",
    "Q (Radiant Volley) prices the full volley: 'Initial Explosion "
    "Magic Damage' + (Number of Bolts - 1) x 'Magic Damage per "
    "Subsequent Explosion' == the wiki's 'Total Magic Damage' row "
    "(data/champions.json Q), all bolts landing on the primary target "
    "over the sourced 0.5s volley.",
    "E (Solar Snare) prices the orb hit plus the field DoT: 4 ticks of "
    "'Field Magic Damage per Tick' (data/champions.json E) at 0.125s "
    "intervals — the game-file MelE DataValues source DoTDuration 0.5s "
    "at AreaTicksPerSecond 8 (raw.communitydragon.org mel.bin.json), "
    "starting after the 0.5s field-expansion delay.",
    "R (Golden Eclipse) prices the wiki's 'Magic Damage' row "
    "(125/200/275 + 30% AP) plus (4/7/10 + 4% AP) per Overwhelm stack "
    "on the target (data/champions.json R), with the stack count from "
    "the r_overwhelm_stacks option (default 3).",
    "The Overwhelm stored-damage execute (P: first stack stores "
    "50/60/70/80 + 10% AP, +2/3/4/5 + 0.75% AP per additional stack, "
    "consumed when stored damage exceeds the target's current health "
    "and shields) is a kill boundary and is documented, not priced as "
    "damage.",
    "KNOWN CACHE LAG (verified 16.16.1, not fixed here — out of this "
    "module's file scope): W (Rebuttal)'s cached cooldown row is "
    "[38, 35, 32, 29, 26]; the game files disagree at rank 3 only — bin "
    "MelWAbility/MelW 'cooldownTime' [38, 38, 35, 33, 29, 26, 26] and "
    "ddragon Mel.json cooldownBurn '38/35/33/29/26' both say 33, not "
    "32. This module reads the cooldown dynamically via "
    "extract_cooldown(ability, rank) (no hardcoded value to re-pin), so "
    "the flag traces to data/champions.json's W cache entry, not to "
    "this module or its tests — no test currently asserts W's cooldown "
    "value, so this module's behavior is otherwise unaffected. Clearing "
    "patch_regression.py's ability_rows_stale flag requires a "
    "data/champions.json re-pull/re-cert, which is outside this task's "
    "scope (see docs/patch-day-runbook.md Step 3.A).",
]
MODULE_COVERAGE = coverage(no_damage="W")
