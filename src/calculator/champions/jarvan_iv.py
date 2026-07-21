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
- W (Golden Aegis) is shield/slow only — zero enemy damage, absent.
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
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
    simple_damage,
)

# HARDCODED: verify on patch updates — P (Martial Cadence) has no JSON
# leveling; these values exist only in description prose. Source:
# https://wiki.leagueoflegends.com/en-us/Jarvan_IV
# 8% of the target's CURRENT health, minimum 20, uncapped vs champions
# (the 400 cap applies only to non-champion targets, not modeled here).
PASSIVE_CURRENT_HP_PERCENT = 8.0
PASSIVE_MIN_DAMAGE = 20.0
# Per-target cooldown: 6/5/4/3s at champion levels 1/6/11/16.
PASSIVE_COOLDOWN_BREAKPOINTS = ((16, 3.0), (11, 4.0), (6, 5.0), (1, 6.0))


def _passive_cooldown(level: int) -> float:
    """Martial Cadence per-target cooldown at a champion level."""
    for min_level, cooldown in PASSIVE_COOLDOWN_BREAKPOINTS:
        if level >= min_level:
            return cooldown
    return PASSIVE_COOLDOWN_BREAKPOINTS[-1][1]


def _martial_cadence(ctx: SlotCtx) -> dict[str, Any]:
    """P: current-HP% on-hit proc on a per-target cooldown (fight-scheduled)."""
    ability = ctx.ability()
    name = ability.get("name", "Martial Cadence") if ability else "Martial Cadence"
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
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    damage = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Dragon Strike"),
        rank,
        extract_cooldown(ability, rank),
        damage,
        "physical",
    )

    # Armor REDUCTION (not penetration): damage.py shreds target armor
    # after Q's own damage, so post-Q hits see the reduced armor.
    shred = extract_value(ability, "Armor Reduction", rank)
    if ctx.options.get("q_armor_shred", True) and shred > 0:
        entry["target_debuff"] = {"armor_reduction_percent": shred}
    return entry


_dragon_strike.phase = DEBUFF


def _demacian_standard(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: magic active damage + bonus-AS stat buff (doubled near the flag)."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    damage = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Demacian Standard"),
        rank,
        extract_cooldown(ability, rank),
        damage,
        "magic",
    )

    # Bonus attack speed: the fight engine recalculates the auto count
    # (and therefore the passive's proc schedule) from the stat_buff.
    bonus_as = extract_value(ability, "Bonus Attack Speed", rank)
    if ctx.options.get("near_flag", True):
        bonus_as *= 2.0
    if bonus_as > 0:
        entry["stat_buff"] = {"bonus_attack_speed": bonus_as}
    return entry


_demacian_standard.phase = BUFF


OPTIONS: list[dict[str, Any]] = [
    {
        "key": "q_armor_shred",
        "type": "bool",
        "default": True,
        "label": "Q armor shred active",
    },
    {
        "key": "near_flag",
        "type": "bool",
        "default": True,
        "label": "Near Demacian Standard (flag planted)",
    },
]

ASSUMPTIONS = [
    "Passive procs are derived from the fight timeline: the first auto "
    "procs, then again once the per-target cooldown (6/5/4/3s by level) "
    "elapses given auto spacing from final attack speed; each proc deals "
    "8% of the target's decaying current health (min 20) as physical",
    "Q's armor shred applies to damage dealt after Q (autos, passive "
    "procs, R), not to Q itself",
    "W (Golden Aegis) deals no damage (shield/slow only) — skipped",
    "E flag assumed planted with Jarvan in its aura by default "
    "(doubled attack speed bonus, toggleable)",
    "E ally aura not modeled (single-champion calculator)",
]

SLOTS = {
    "P": _martial_cadence,
    "Q": _dragon_strike,
    "E": _demacian_standard,
    "R": simple_damage(attr="Physical Damage", dmg_type="physical"),
}

parse_abilities = build_parser(SLOTS, "Jarvan IV")
