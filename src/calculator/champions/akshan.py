"""Akshan — slot map for the archetype engine.

The design's honest ceiling: most of Akshan's numbers live in
description TEXT rather than leveling data, so this module is mostly
custom fns over regex extraction — deliberately NOT archetypes, since
no other champion shares these mechanics.

Why each slot is non-generic:
- Q (Avengerang) hits on both passes — the "Total Physical Damage"
  attribute (the classifier would pick the single-pass value).
- E (Heroic Swing) fires ``e_shots`` shots (option, default 5); the
  per-shot leveling data uses unusual unit strings ("×" for the flat
  base, a prose per-100%-bonus-AS ratio) handled by the
  ``_extract_e_per_shot`` seam.
- R (Comeuppance) is min-damage-per-bullet × stored bullets, plus two
  fight-engine scaling constants: crits amplify at 30% effectiveness and
  missing HP scales the barrage up to +200%.
- P (Dirty Fighting) is TWO results entries from one JSON passive:
  ``passive_double_shot`` (every auto fires a second shot at a %AD
  ratio regex-read from the description) and ``passive`` (the 3-stack
  magic proc whose level breakpoints and AP ratio are also
  description text, × the ``passive_procs`` option, default 3).
- W (Going Rogue) is stealth/revive utility — no enemy-damage attribute
  of its own.

All numeric values are read from the champion JSON data (several from
description text). The R scaling values below are rooted in AkshanR's binary;
the missing-health value is converted from the binary's total multiplier to
the additive bonus used by this module.

Roadmap session (2026-08-21): closes the single out_of_scope slot (W).
W (Going Rogue): ``data/champions.json`` Akshan W carries
``damageType: None`` and every effect row is stealth/mark/resurrection/
recast-timing text — no HP number against an enemy champion anywhere.
The one leveling row on the ability ("Bonus Movement Speed" 80-120 by
rank) is a conditional self-buff ("while facing them if they are within
5000 units, he gains bonus mana regeneration ... as well as bonus
movement speed" during camouflage) — situational utility, not a
default-active steroid for a one-rotation combat calc, so it stays a
documented, sourced-but-unmodeled rider in ASSUMPTIONS rather than an
unconditional stat_buff (the Singed R precedent for riders with no
default-on consumer). Reclassified from out_of_scope to no_damage (an
atoms-confirmed zero-HP-number effect), not left silently absent.
"""

import re
from typing import Any

from ..ability_spec import DamagePart
from .inputs import champion_stat, int_option
from ..binary_roots import data_value, spell_object
from .engine import SlotCtx, build_parser
from .module_helpers import no_damage
from .slotlib import (
    ability_name,
    attach_self_shield,
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
    find_named_leveling,
    proc_damage,
    simple_damage,
    sum_modifiers,
)
from .source_receipts import load_champion_sources
from .module_contract import coverage

# R bullets can crit at 30% effectiveness (3% damage per 10% crit chance) and
# scale up to +200% based on the target's missing health. The binary stores
# MaxIncrease as the total endpoint multiplier (3x), while this formula uses
# the additive bonus (2x), so subtract one at the representation boundary.
_R_CRIT_EFFECTIVENESS = data_value(spell_object("Akshan", "AkshanR"), "CritDamageMod")
_R_MISSING_HP_MAX_BONUS = (
    data_value(spell_object("Akshan", "AkshanR"), "MaxIncrease") - 1.0
)

# Heroic Swing's shots are on a cached beat, not on Akshan's attack speed:
# "While swinging, he fires at the nearest visible enemy every 0.231
# seconds" (data/champions.json Akshan E).
_E_SHOT_INTERVAL_S = 0.231


def _extract_e_per_shot(
    ability: dict[str, Any],
    rank: int,
    stats_context: dict[str, float] | None = None,
) -> float:
    """Extract Heroic Swing per-shot damage from JSON.

    The JSON has modifiers with unusual unit strings (``"  ×"`` for flat
    damage) and a prose AS ratio ("+N per 100% bonus attack speed").
    (Test seam: tests/test_akshan.py validates the JSON values here.)

    Args:
        ability: E ability dict from champion JSON.
        rank: E rank (1-indexed).
        stats_context: Champion stats for AD/AS scaling.

    Returns:
        Physical damage per shot before resistances.
    """
    leveling = find_named_leveling(ability, "Physical Damage per Shot")
    if leveling is None:
        return 0.0

    def unusual_unit(unit: str, value: float) -> float | None:
        unit_stripped = unit.strip()
        if not unit_stripped or unit_stripped in ("×", "x"):
            return value
        if "per 100% bonus attack speed" not in unit:
            return None
        match = re.search(r"(\d+(?:\.\d+)?)\s*per\s*100%", unit)
        if not match:
            return 0.0
        as_ratio = float(match.group(1))
        # ESCALATED DEFECT akshan-bonus-attack-speed-percent
        # (docs/receipts/escalated-defects-P3-3.7.json): the stat block this
        # reads has no ``bonus_attack_speed_percent`` key —
        # ``calculate_total_stats`` emits ``bonus_attack_speed`` — so this
        # term resolves to zero and Heroic Swing does not price its
        # attack-speed scaling.  Correcting it moves a number, so the zero
        # is stated here rather than defaulted.
        bonus_as_pct = 0.0
        return as_ratio * (bonus_as_pct / 100.0) * value

    return sum_modifiers(
        leveling,
        rank,
        stats_context,
        modifier_override=unusual_unit,
    )


def _parse_passive_proc_damage(
    passive: dict[str, Any],
    level: int,
    stats_context: dict[str, float] | None = None,
) -> float:
    """Parse Dirty Fighting 3-stack proc magic damage from the JSON.

    The structured leveling data contains shield values (labelled
    "Bonus Damage"), not the proc damage. The proc breakpoints
    (15/40/80/150 based on level) and 60% AP ratio are description
    text, so they are regex-extracted. (Test seam: tests/test_akshan.py
    validates the JSON values here.)

    Args:
        passive: Passive ability dict from champion JSON.
        level: Champion level (1-20).
        stats_context: Champion stats (for AP).

    Returns:
        Magic damage per proc before resistances.
    """
    for effect in passive.get("effects", []):
        desc = effect.get("description", "")
        # Match "deal them N / N / N / N (based on level) (+ N% AP)".
        dmg_match = re.search(
            r"deal them (\d+)\s*/\s*(\d+)\s*/\s*(\d+)\s*/\s*(\d+)\s*"
            r"\(based on level\)",
            desc,
        )
        if not dmg_match:
            continue

        breakpoints = [int(dmg_match.group(i)) for i in range(1, 5)]
        # Standard 4-breakpoint levels: 1, 6, 11, 16.
        if level >= 16:
            base = float(breakpoints[3])
        elif level >= 11:
            base = float(breakpoints[2])
        elif level >= 6:
            base = float(breakpoints[1])
        else:
            base = float(breakpoints[0])

        ap_match = re.search(r"\+\s*(\d+)%\s*AP", desc)
        ap_ratio = float(ap_match.group(1)) / 100.0 if ap_match else 0.0

        ap = champion_stat(stats_context or {}, "ability_power")
        return base + ap_ratio * ap

    return 0.0


def _extract_double_shot_ratio(passive: dict[str, Any]) -> float:
    """Extract the double shot AD ratio from the passive description.

    The description says the additional shot deals ``50% AD`` physical
    damage. (Test seam: tests/test_akshan.py validates it here.)
    """
    for effect in passive.get("effects", []):
        desc = effect.get("description", "")
        match = re.search(r"deals?\s+(\d+)%\s*AD\s+physical damage", desc)
        if match:
            return float(match.group(1)) / 100.0
    raise ValueError("Akshan P double-shot AD ratio is unavailable")


def _heroic_swing(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: per-shot damage x ``e_shots`` option (default 5), on its cadence."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    shots = int(ctx.option("e_shots"))
    if rank < 1 or shots <= 0:
        return None

    per_shot = _extract_e_per_shot(ability, rank, ctx.stats)
    if per_shot <= 0:
        return None

    name = ability_name(ability)
    cooldown = extract_cooldown(ability, rank)
    entry = damage_entry(name, rank, cooldown, per_shot * shots, "physical")
    # The swing's shots have a cached beat: "While swinging, he fires at the
    # nearest visible enemy every 0.231 seconds to deal them physical damage
    # and apply on-hit effects for each shot" (data/champions.json Akshan E).
    # "Akshan immediately fires one shot at the beginning of his swing", so
    # the first shot sits on the cast start and the rest follow on the beat.
    entry["parts"] = (
        DamagePart(
            "physical",
            per_shot,
            count=shots,
            time_offset=0.0,
            hit_interval=_E_SHOT_INTERVAL_S,
        ),
    )
    # Wiki: every Heroic Swing shot applies on-hit effects at 25% effectiveness.
    entry["applies_item_on_hits"] = {
        "effectiveness": 0.25,
        "hits": shots,
        "triggers": ("on_hit",),
    }
    return entry


def _comeuppance(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: min damage per bullet x stored bullets + crit/missing-HP flags.

    Uses "Minimum Physical Damage per Bullet" — the JSON's "Maximum"
    variant already has the 3x missing-HP multiplier baked in; the
    fight engine applies that scaling itself from the flags.
    """
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked

    per_bullet = extract_named(
        ability, "Minimum Physical Damage per Bullet", rank, ctx.stats, ctx.target
    )
    bullets = int(extract_value(ability, "Maximum Bullets Stored", rank))

    name = ability_name(ability)
    total = per_bullet * bullets
    entry = damage_entry(name, rank, extract_cooldown(ability, rank), total, "physical")
    # Barrage scales up to +200% with target missing HP; crits amplify
    # at 30% effectiveness (both wiki-prose constants, see module doc).
    entry["parts"] = (
        DamagePart(
            "physical",
            hp_scaled_damage=lambda missing: total
            * (1.0 + _R_MISSING_HP_MAX_BONUS * missing),
            crit_effectiveness=_R_CRIT_EFFECTIVENESS,
        ),
    )
    # Comeuppance is one authored barrage event.  Its missing-health curve
    # is evaluated at that cast boundary; there is no hidden sub-hit timing
    # in the single-target packet.
    entry["event_order_certified"] = "single_hit"
    return entry


def _double_shot(ctx: SlotCtx) -> dict[str, Any] | None:
    """passive_double_shot: every auto fires a second %AD shot."""
    passive = ctx.ability("P")
    if passive is None:
        return None
    return {
        "name": "Dirty Fighting (Double Shot)",
        "double_shot": {
            "name": "Dirty Fighting (Double Shot)",
            "ad_ratio": _extract_double_shot_ratio(passive),
        },
    }


def _dirty_fighting_damage(ctx: SlotCtx, passive: dict[str, Any]) -> float:
    """Resolve one Dirty Fighting three-stack proc from description text."""
    return _parse_passive_proc_damage(passive, ctx.level, ctx.stats)


_dirty_fighting_packet = proc_damage(
    _dirty_fighting_damage,
    "magic",
    default_count=3,
    name="Dirty Fighting (3-Stack Proc)",
    phase_order_events=True,
)


# HARDCODED: verify on patch updates — the 3-stack proc shield's duration is
# prose in the cached passive description ("Akshan will also gain a
# 40 : 280 (based on level) (+ 35% bonus AD) shield for 2 seconds. The
# shield may be gained only once every few seconds."); the leveling row
# "Bonus Damage" (data/champions.json P[2]) carries the 40 : 280 per-level
# array and the 35% bonus-AD ratio, so the amount is read live.  The
# internal cooldown is the game-file PassiveCooldown (16/12/8/4 by level
# breakpoints 6/11/16; 4s at level 18) — the fight's proc events all ride
# the cast boundary, so the model grants one shield per proc burst and the
# ICD is a documented boundary.
_DIRTY_FIGHTING_SHIELD_DURATION_SECONDS = data_value(
    spell_object("Akshan", "AkshanPassive"), "ShieldDuration"
)


def _dirty_fighting_shield(passive: dict[str, Any], ctx: SlotCtx) -> float:
    """Dirty Fighting 3-stack proc shield amount (40:280 + 35% bAD by level)."""
    return extract_named(passive, "Bonus Damage", ctx.level, ctx.stats, ctx.target)


def _dirty_fighting(ctx: SlotCtx) -> dict[str, Any] | None:
    """Emit the 3-stack proc with its sourced auto-stack cadence.

    Dirty Fighting triggers on every third damaging attack.  The proc count
    remains the user-controlled packet count, while the event ledger places
    each proc on the corresponding third auto swing in timed fights.  Each
    completed 3-stack detonation against a champion also grants the proc
    shield (40:280 by level + 35% bonus AD for 2s, sourced from the cached
    "Bonus Damage" leveling row); the fight model grants one shield per
    proc burst — every proc event rides the cast boundary and the shield's
    internal cooldown (16/12/8/4 by level) cannot elapse between them.
    """
    entry = _dirty_fighting_packet(ctx)
    if entry is None:
        return None
    entry["event_order_certified"] = "auto_stack_proc"
    entry["auto_stack_every"] = 3
    passive = ctx.ability("P")
    if passive is not None:
        attach_self_shield(
            entry,
            amount=_dirty_fighting_shield(passive, ctx),
            duration=_DIRTY_FIGHTING_SHIELD_DURATION_SECONDS,
            source="Dirty Fighting (3-Stack Shield)",
            detail=(
                "Each completed 3-stack detonation grants Akshan the proc "
                "shield (40:280 by level + 35% bonus AD) for 2s; one shield "
                "per proc burst (the internal cooldown of 16/12/8/4s by "
                "level cannot elapse between the fight's cast-boundary "
                "procs)"
            ),
        )
    return entry


def _going_rogue(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: stealth/mark/resurrection utility — sourced zero-enemy-damage row.

    The cached W entry carries ``damageType: None``; every effect row is
    Scoundrel-marking, resurrection, camouflage, or recast-timing text with
    no HP number against an enemy champion. The one leveling row on the
    ability (Bonus Movement Speed, conditional on facing a marked Scoundrel
    during camouflage) is documented as a sourced-but-unmodeled rider in
    ASSUMPTIONS rather than an unconditional stat_buff.
    """
    ability = ctx.ability()
    if ability is None:
        return None
    return no_damage(
        ctx,
        name=ability_name(ability),
        reason=(
            "Going Rogue is stealth/Scoundrel-mark/resurrection utility "
            "with no enemy-damage attribute of its own (data/champions.json "
            "Akshan W carries damageType: None); its conditional bonus "
            "movement speed (80-120 by rank, only while facing a marked "
            "Scoundrel in camouflage) has no default-on consumer for a "
            "one-rotation combat calc and stays a documented rider."
        ),
    )


OPTIONS = [
    int_option(
        "passive_procs", 3, minimum=0, maximum=20, label="Passive procs (3-stack)"
    ),
    int_option("e_shots", 5, minimum=0, maximum=20, label="E shots fired"),
]

ASSUMPTIONS = [
    "Q always hits both passes (outgoing and return)",
    "R assumes full channel (max bullets at max damage)",
    "R crit scaling at 30% effectiveness applied",
    "Double shot applies on-hit effects and can crit",
    "Dirty Fighting stacks up to 3 (cap) on the target and the third "
    "stack consumes them all: each passive_procs entry is one completed "
    "3-stack detonation (15/40/80/150 by level + 60% AP, the level "
    "breakpoints and AP ratio regex-read from the wiki description)",
    "Each completed 3-stack detonation also grants the proc shield "
    "(40:280 by level + 35% bonus AD for 2s, the cached 'Bonus Damage' "
    "row); one shield per proc burst — the proc events ride the cast "
    "boundary and the shield internal cooldown (16/12/8/4s by level, "
    "game-file PassiveCooldown) cannot elapse between them",
    "W (Going Rogue) carries no enemy-damage attribute (damageType: None, "
    "no effect row deals HP loss to a champion); it emits a sourced "
    "no_damage row. Its conditional bonus movement speed (80-120 by rank, "
    "only while facing a marked Scoundrel in camouflage) is a documented, "
    "sourced-but-unmodeled rider — not a default-on steroid.",
]

SLOTS = {
    "Q": simple_damage(attr="Total Physical Damage", dmg_type="physical"),
    "E": _heroic_swing,
    "R": _comeuppance,
    "passive_double_shot": _double_shot,
    "P": _dirty_fighting,
    "W": _going_rogue,
}

# Cached kit review.  R's bullets, P's 3-stack detonation and E's swing
# shots only damage — nothing in the cached text controls the target they
# hit (Q's and W's reveals and camouflage are vision, not control).  E's
# shots now land on their cached 0.231-second beat, which is what lets that
# review reach the event ledger.
#
# Q stays UNREVIEWED, so this kit keeps the coarse control-armed scan: its
# row is the cached "Total Physical Damage" of both boomerang passes, and
# the return pass has no cached arrival time — the cache gives the two
# speeds ("1500 • 2400") but no distance to fly, and a speed without a
# distance is half a schedule.
MODULE_CC = {"R": "none", "P": "none", "E": "none"}

parse_abilities = build_parser(SLOTS, "Akshan", cc_kinds=MODULE_CC)


SOURCES = load_champion_sources("Akshan")

# W is emitted, but its row is a sourced zero — a fact SLOTS cannot derive.
MODULE_COVERAGE = coverage(no_damage="W")
