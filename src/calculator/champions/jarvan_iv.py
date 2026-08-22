"""Jarvan IV — slot map for the archetype engine.

Why each slot is non-generic:
- P (Martial Cadence) has NO JSON leveling entries — the 8% current-HP,
  minimum-20, and per-target cooldown values exist only in description
  prose, so they live here as module constants. The entry emits a
  cooldown-scheduled ``on_hit`` payload: the fight engine derives the
  proc schedule from the fight timeline (first auto procs, then the
  first auto at/after last proc + cooldown) with each proc reading the
  target's decayed current HP — a configurable proc count would ignore
  attack speed, and proc-every-auto would badly overstate the passive.
- Q (Dragon Strike) is a DEBUFF-phase custom fn: physical damage plus a
  % armor reduction ``target_debuff`` (``q_armor_shred`` option, default
  True). damage.py applies the shred AFTER Q's own damage, so autos,
  passive procs, and R benefit but Q does not — matching in-game.
- W (Golden Aegis) is shield/slow only: a zero-damage cast that exists so
  the rotation casts it and the ally-support scanner prices the sourced
  self shield (140.0 at rank 5 with no bonus AD, the cached "Shield
  Strength" row; see ``support_effects._SHIELD_DURATION_ATOM_QUERIES[
  ("Jarvan IV", "W")]``, which the scanner was pre-wired with).  The
  prose-only "+1.3% of his maximum health for each enemy champion hit"
  has no leveling row and is not priced; the slow is crowd control the
  model does not price.
- E (Demacian Standard) is a BUFF-phase custom fn: magic active damage
  plus a bonus-attack-speed ``stat_buff``. The ``near_flag`` option
  (default True) doubles the AS bonus — Jarvan near his planted flag
  gets both the aura and the flag's own aura. The buffed attack speed
  also raises the passive's derived proc count at fight time.
- R (Cataclysm) is a plain "Physical Damage" read; terrain and recast
  are CC/utility only (no recast slot).
"""

from typing import Any

from .engine import BUFF, DEBUFF, ONHIT, SlotCtx, build_parser
from .slotlib import (
    ability_name,
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
    simple_damage,
    support_cast,
)
from .source_receipts import load_champion_sources
from .inputs import bool_option

# HARDCODED: verify on patch updates — P (Martial Cadence) has no JSON
# leveling; these values exist only in description prose. Source:
# https://wiki.leagueoflegends.com/en-us/Jarvan_IV
# 8% of the target's CURRENT health, minimum 20, uncapped vs champions
# (the 400 cap applies only to non-champion targets, not modeled here).
PASSIVE_CURRENT_HP_PERCENT = 8.0
PASSIVE_MIN_DAMAGE = 20.0
# Per-target cooldown: 6/5/4/3s at champion levels 1/6/11/16.
PASSIVE_COOLDOWN_BREAKPOINTS = ((16, 3.0), (11, 4.0), (6, 5.0), (1, 6.0))


# Dragon Strike inflicts "armor reduction for 3 seconds".
Q_SHRED_DURATION = 3.0


def _passive_cooldown(level: int) -> float:
    """Martial Cadence per-target cooldown at a champion level."""
    for min_level, cooldown in PASSIVE_COOLDOWN_BREAKPOINTS:
        if level >= min_level:
            return cooldown
    return PASSIVE_COOLDOWN_BREAKPOINTS[-1][1]


def _martial_cadence(ctx: SlotCtx) -> dict[str, Any]:
    """P: current-HP% on-hit proc on a per-target cooldown (fight-scheduled)."""
    ability = ctx.ability()
    name = ability_name(ability) if ability else "Martial Cadence"
    return {
        "name": name,
        "on_hit": {
            "name": name,
            "damage_type": "physical",
            "current_health_percent": PASSIVE_CURRENT_HP_PERCENT,
            "min_damage": PASSIVE_MIN_DAMAGE,
            "proc_cooldown": _passive_cooldown(ctx.level),
        },
    }


_martial_cadence.phase = ONHIT


def _dragon_strike(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: physical damage + % armor reduction debuff (option-gated)."""
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked

    damage = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        damage,
        "physical",
        event_order_certified="single_hit",
    )

    # Armor REDUCTION (not penetration): damage.py shreds target armor
    # after Q's own damage, so post-Q hits see the reduced armor.
    shred = extract_value(ability, "Armor Reduction", rank)
    if ctx.option("q_armor_shred") and shred > 0:
        entry["target_debuff"] = {
            "armor_reduction_percent": shred,
            "duration": Q_SHRED_DURATION,
        }
    return entry


_dragon_strike.phase = DEBUFF


def _demacian_standard(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: magic active damage + bonus-AS stat buff (doubled near the flag)."""
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked

    damage = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        damage,
        "magic",
        event_order_certified="single_hit",
    )

    # Bonus attack speed: the fight engine recalculates the auto count
    # (and therefore the passive's proc schedule) from the stat_buff.
    bonus_as = extract_value(ability, "Bonus Attack Speed", rank)
    if ctx.option("near_flag"):
        bonus_as *= 2.0
    if bonus_as > 0:
        entry["stat_buff"] = {"bonus_attack_speed": bonus_as}
    return entry


_demacian_standard.phase = BUFF


OPTIONS: list[dict[str, Any]] = [
    bool_option("q_armor_shred", True, label="Q armor shred active"),
    bool_option("near_flag", True, label="Near Demacian Standard (flag planted)"),
]

ASSUMPTIONS = [
    "Passive procs are derived from the fight timeline: the first auto "
    "procs, then again once the per-target cooldown (6/5/4/3s by level) "
    "elapses given auto spacing from final attack speed; each proc deals "
    "8% of the target's decaying current health (min 20) as physical",
    "Q's armor shred applies to damage dealt after Q (autos, passive "
    "procs, R), not to Q itself",
    "W (Golden Aegis) deals no direct damage; the slow (15-35% for 2s) "
    "is utility-only and not modeled. Its self-shield (60/80/100/120/"
    "140 + 70% bonus AD, 4s) is granted by the ally-support scanner "
    "(self-targeted) from the cached Shield Strength row at the W cast. "
    "The 'increased by 1.3% of Jarvan's maximum health for each enemy "
    "champion hit' "
    "rider is prose-only (not a modifier row) and not modeled — a "
    "documented boundary that is exact in a 1v1 fight, which can hit "
    "at most one enemy champion",
    "E flag assumed planted with Jarvan in its aura by default "
    "(doubled attack speed bonus, toggleable)",
    "E ally aura not modeled (single-champion calculator)",
]

SLOTS = {
    "P": _martial_cadence,
    "Q": _dragon_strike,
    # Golden Aegis shields Jarvan himself ("Jarvan IV also grants himself a
    # shield for 4 seconds", cached "Shield Strength" 60-140 + 70% bonus AD);
    # the slot exists so the rotation casts it and the support scanner can
    # price the shield.  The prose-only "+1.3% of his maximum health for each
    # enemy champion hit" has no leveling row and is not priced.
    "W": support_cast(
        default_name="Golden Aegis",
        detail="Self shield (sourced by the support scanner); the "
        "per-champion-hit maximum-health increase is not priced.",
    ),
    "E": _demacian_standard,
    "R": simple_damage(
        attr="Physical Damage",
        dmg_type="physical",
        event_order_certified="single_hit",
    ),
}

# Q's lance damages and shreds armor; its knock-up needs the lance to
# connect with a deployed Demacian Standard, a flag-plus-lance combo this
# module does not model, so the reviewed kind is the unconditional none.
# E's flag only damages on landing.  R's impact "knocks aside enemies
# within the perimeter".  P is the on-hit row; W's own row deals no
# damage, and its slow is control this model does not price.
MODULE_CC = {"Q": "none", "E": "none", "R": "knockback"}

parse_abilities = build_parser(SLOTS, "Jarvan IV", cc_kinds=MODULE_CC)


SOURCES = load_champion_sources("Jarvan IV")
