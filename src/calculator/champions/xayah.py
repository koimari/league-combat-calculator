"""Xayah — reviewed packet slots plus the E3 Clean Cuts stack mechanic.

E3 additions over the CP10.9 packet module:
- P (Clean Cuts) becomes an explicit stack state: each ability cast
  generates 3 stacks (up to 5) and each basic attack consumes one stack
  to shoot a Feather. The feather deals the triggering attack's damage
  to the PRIMARY target — no single-target damage delta — and 35% /
  45% / 55% (based on level) AD to OTHER enemies, priced through the
  ``clean_cuts_secondary_targets`` option. What the stacks materially
  change is the planted feather count that detonates through E.
- E (Bladecaller) prices the detonation: per-feather damage
  ("Physical Damage Per Feather", flat + 40% bonus AD) times the
  recalled feather count. The count is a user option
  (``bladecaller_feathers``, default 7 = the expected contribution: 5
  Clean Cuts-empowered autos + 2 Q daggers; the sourced maximum of 12
  adds R's 5 feathers). The fight model cannot simulate how many
  empowered autos land before E, so the count is priced explicitly —
  the module convention for auto-rate stack systems.
"""

import re
from collections.abc import Mapping
from typing import Any

from ..ability_atoms import (
    AbilityAtomQuery,
    ranked_ability_atom_value,
    required_ability_atom,
)
from ..ability_spec import ControlEvent, DamagePart
from ..binary_roots import data_value, spell_object
from .engine import SlotCtx
from .inputs import int_option
from .packet_module import build_packet_module, repeat_damage_parser
from .slotlib import ability_name, damage_entry, extract_cooldown

PACKET_SHA256 = "1aaff9137640dc9212a82420983ce8b4c7734417696e4529f59d8302d5fbc8e6"

# Rooted in XayahR.RAttackDelay; the cached R prose corroborates the
# one-second delay before the five feathers launch.
_R_LEAP_SECONDS = data_value(spell_object("Xayah", "XayahR"), "RAttackDelay")


# HARDCODED: verify on patch updates — Clean Cuts' stack bookkeeping
# (3 stacks per cast, 5 cap, 8-second window) and the 35/45/55% AD
# secondary-feather damage are wiki prose; the JSON carries no leveling
# for the passive.  The values ARE cached in the P description
# ("35% / 45% / 55% (based on level) AD physical damage to other
# enemies hit. The secondary target damage can critically strike for
# (200% + 30%) damage if the triggering attack does"), and
# ``_secondary_feather_ratio`` / ``_secondary_feather_crit_extra`` read
# them from that prose with the standard 1/7/13 level brackets.
_CLEAN_CUTS_MAX_STACKS = int(
    data_value(spell_object("Xayah", "XayahPassive"), "PStackMax")
)
_DEFAULT_FEATHERS = 7  # 5 empowered autos + 2 Q daggers (expected)
_MAX_FEATHERS = 12  # + 5 R feathers (sourced maximum)
_CLEAN_CUTS_LEVEL_BRACKETS = ((13, 3), (7, 2), (1, 1))  # 1/7/13 -> index


def _secondary_feather_ratio(ability: Mapping[str, Any], level: int) -> float:
    """Level-bracketed 35/45/55% AD secondary-feather damage (P prose)."""
    description = " ".join(
        str(effect.get("description", "")) for effect in ability.get("effects", [])
    )
    match = re.search(
        r"(\d+)% / (\d+)% / (\d+)% \(based on level\) AD physical damage",
        description,
        flags=re.IGNORECASE,
    )
    if not match:
        raise ValueError(
            "Xayah P: the 35/45/55% AD secondary-feather damage is missing "
            "from the cached description"
        )
    values = tuple(float(match.group(index)) for index in range(1, 4))
    for min_level, index in _CLEAN_CUTS_LEVEL_BRACKETS:
        if level >= min_level:
            return values[index - 1] / 100.0
    return values[0] / 100.0


def _secondary_feather_crit_extra(ability: Mapping[str, Any]) -> float:
    """Extra crit multiplier on the secondary feather (P prose).

    "can critically strike for (200% + 30%) damage if the triggering
    attack does" — the feather crits at the triggering attack's crit
    roll with 230% damage, so the expected multiplier is
    ``1 + 0.30 * crit_chance``.
    """
    description = " ".join(
        str(effect.get("description", "")) for effect in ability.get("effects", [])
    )
    match = re.search(
        r"critically strike for \(200% \+ (\d+)%\) damage",
        description,
        flags=re.IGNORECASE,
    )
    if not match:
        raise ValueError(
            "Xayah P: the secondary-feather crit bonus is missing from the "
            "cached description"
        )
    return float(match.group(1)) / 100.0


def _clean_cuts(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: explicit Clean Cuts stack state + secondary-feather damage.

    Each empowered auto's Feather deals the triggering attack's damage
    to the PRIMARY target (no single-target delta) and the level-scaled
    35/45/55% AD to OTHER enemies.  With ``clean_cuts_secondary_targets``
    (default 0) selected, the per-auto secondary damage rides this row's
    ``on_hit`` payload; the crit rider ("can critically strike for
    (200% + 30%) damage if the triggering attack does") is baked into
    the per-hit value as an expected-value multiplier.
    """
    ability = ctx.ability()
    if ability is None:
        return None
    stacks = int(ctx.options.get("clean_cuts_stacks", _CLEAN_CUTS_MAX_STACKS))
    stacks = min(max(stacks, 0), _CLEAN_CUTS_MAX_STACKS)
    detail = (
        f"{stacks}/{_CLEAN_CUTS_MAX_STACKS} stack(s); each empowered "
        "auto plants one Feather (primary target takes the triggering "
        "attack's damage — no single-target delta); E detonates "
        "planted Feathers"
    )
    secondary = min(max(int(ctx.option("clean_cuts_secondary_targets")), 0), 5)
    entry: dict[str, Any] = {
        "name": ability_name(ability),
        "rank": ctx.level,
        "damage_type": "physical",
        "total_raw": 0.0,
        "parts": (),
        "detail": detail,
    }
    if secondary:
        ratio = _secondary_feather_ratio(ability, ctx.level)
        crit_extra = _secondary_feather_crit_extra(ability)
        crit_chance = min(
            max(ctx.stat("critical_strike_chance") / 100.0, 0.0),
            1.0,
        )
        per_auto = (
            secondary
            * ratio
            * ctx.stat("attack_damage")
            * (1.0 + crit_extra * crit_chance)
        )
        entry["on_hit"] = {
            "name": "Clean Cuts (secondary feather)",
            "damage_per_hit": per_auto,
            "damage_type": "physical",
        }
        entry["detail"] = (
            f"{detail}  {secondary} other enemy(enemies) per feather at "
            f"{ratio * 100:g}% AD each (crit expectation "
            f"{1.0 + crit_extra * crit_chance:.3f}x)"
        )
    return entry


def _bladecaller(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: per-Feather damage x recalled Feather count (stack detonation)."""
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked

    base_source = "Xayah.E[0].effects[0].leveling[0].modifiers[0]"
    ratio_source = "Xayah.E[0].effects[0].leveling[0].modifiers[1]"
    base_atom = required_ability_atom(
        ctx.champion_name,
        {"name": ctx.champion_name, "abilities": ctx.abilities},
        "E",
        query=AbilityAtomQuery(
            source=base_source,
            behavior="ability",
            evidence_prefix="Physical Damage Per Feather@",
        ),
    )
    ratio_atom = required_ability_atom(
        ctx.champion_name,
        {"name": ctx.champion_name, "abilities": ctx.abilities},
        "E",
        query=AbilityAtomQuery(
            source=ratio_source,
            behavior="ability",
            evidence_prefix="Physical Damage Per Feather@",
        ),
    )
    base = ranked_ability_atom_value(base_atom, rank, source=base_source)
    ratio = ranked_ability_atom_value(ratio_atom, rank, source=ratio_source)
    if base_atom.get("units") != [""] * len(base_atom.get("values", [])):
        raise ValueError("Xayah E base damage atom must use flat units")
    if ratio_atom.get("units") != ["% bonus AD"] * len(ratio_atom.get("values", [])):
        raise ValueError("Xayah E ratio atom must use bonus-AD units")
    per_feather = base + ratio * ctx.stat("bonus_attack_damage") / 100.0
    feathers = int(ctx.options.get("bladecaller_feathers", _DEFAULT_FEATHERS))
    feathers = min(max(feathers, 0), _MAX_FEATHERS)

    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        per_feather * feathers,
        "physical",
    )
    entry["parts"] = (DamagePart("physical", per_feather, count=feathers),)
    if feathers >= 3:
        root_source = "Xayah.E[0].effects[2].description"
        root_atom = required_ability_atom(
            ctx.champion_name,
            {"name": ctx.champion_name, "abilities": ctx.abilities},
            "E",
            query=AbilityAtomQuery(
                source=root_source,
                behavior="timing",
                evidence_prefix="control duration@",
            ),
        )
        root_duration = ranked_ability_atom_value(root_atom, 1, source=root_source)
        if root_atom.get("units") != ["s"]:
            raise ValueError("Xayah E root duration atom must use seconds")
        entry["control_events"] = (ControlEvent("root", root_duration),)
        entry["control_source_atoms"] = [root_atom]
    entry["detail"] = (
        f"{feathers} recalled Feather(s) x {per_feather:g} per-Feather damage"
    )
    return entry


# Double Daggers' feathers "each deal physical damage to enemies hit",
# Deadly Plumage's extra feather only damages, and Featherstorm's cone
# "deal[s] physical damage to enemies hit".  P is the stack bookkeeping
# row and authors no damage part.
#
# E is absent from the declaration on purpose: Bladecaller's root — "a
# target hit by at least three Feathers is rooted for 1.25 seconds" — is a
# property of the recalled feather count, this module's option, not of the
# slot, so a per-slot kind would be false below three Feathers.  The recall
# is one aggregated part of ``bladecaller_feathers`` hits with no sourced
# cadence between them, so a part marker could never reach the ledger
# either; ``_bladecaller`` instead authors the sourced root as a
# ``control_events`` payload exactly when the feather count arms it.
MODULE_CC = {"Q": "none", "W": "none", "R": "none"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Xayah",
    PACKET_SHA256,
    assumption_overrides=(
        "Double Daggers prices both daggers (Physical Damage Per Hit x 2 "
        "== Total Physical Damage).",
    ),
    # W's row is the one extra feather the frenzy fires per attack.
    single_hit_slots=frozenset({"W"}),
    # "After 1 second, she shoots 5 Feathers" — R's hit is not at the
    # cast, so it authors the sourced delay instead of certifying.
    packet_part_timings={"R": {"time_offset": _R_LEAP_SECONDS}},
    slot_parsers={
        "Q": repeat_damage_parser(
            attr="Physical Damage Per Hit",
            dmg_type="physical",
            count=2,
            time_offset=0.0,
            hit_interval=0.1,
        ),
        "P": _clean_cuts,
        "E": _bladecaller,
    },
    cc_kinds=MODULE_CC,
)

OPTIONS = [
    *list(OPTIONS),
    int_option(
        "clean_cuts_secondary_targets",
        0,
        minimum=0,
        maximum=5,
        label="Other enemies hit by each Clean Cuts Feather (level-scaled "
        "35/45/55% AD, per empowered auto)",
        rotation={"role": "irrelevant", "slot": "P"},
    ),
    int_option(
        "clean_cuts_stacks",
        _CLEAN_CUTS_MAX_STACKS,
        minimum=0,
        maximum=_CLEAN_CUTS_MAX_STACKS,
        label="Clean Cuts stacks",
    ),
    int_option(
        "bladecaller_feathers",
        _DEFAULT_FEATHERS,
        minimum=0,
        maximum=_MAX_FEATHERS,
        label="Feathers recalled by Bladecaller",
    ),
]

ASSUMPTIONS = [
    *list(ASSUMPTIONS),
    "Clean Cuts stack count is user-set (default 5); the 8-second stack "
    "window and which casts generate stacks are not simulated",
    "Each empowered auto deals the triggering attack's damage to the "
    "primary target (no single-target delta); with "
    "clean_cuts_secondary_targets (default 0) selected, each Feather "
    "also hits that many OTHER enemies at the level-scaled 35/45/55% "
    "AD read from the cached P prose (1/7/13 level brackets), with the "
    "sourced '(200% + 30%)' crit rider baked in as an expected-value "
    "multiplier on the triggering attack's crit chance; the on-hit "
    "rides every auto (the fight model cannot simulate how many "
    "empowered autos land before E — the existing Clean Cuts "
    "simplification)",
    "Bladecaller prices per-Feather damage x the recalled Feather count "
    "(user-set, default 7 = 5 empowered autos + 2 Q daggers; maximum 12 "
    "adds R's 5 Feathers) — the fight model cannot simulate how many "
    "empowered autos land before the recall",
    "Bladecaller's crit-chance damage increase (0-50% + 0-15%) is not "
    "modeled; the root is emitted when at least three Feathers are recalled",
    "W's bonus attack speed is the packet read; its extra 25%-damage "
    "feather to the primary target is not double-counted with Clean Cuts",
]
