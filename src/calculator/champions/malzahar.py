"""Malzahar — CP10.4 full-entry-reviewed packet module.

E (Malefic Visions) and R (Nether Grasp) override the batch packet with
full-total DoT pricing: the packets carried the PER-TICK rows, so the
fight priced one tick of each multi-tick ability.  Both totals are
sourced:

- E: "Total Magic Damage" 80/115/150/185/220 is exactly 16x the "Magic
  Damage Per Tick" row (5/7.1875/9.375/11.5625/13.75); the wiki text
  ("dealing magic damage every 0.25 seconds over 4 seconds") confirms
  the 16-tick cadence.
- R: "Total Magic Damage" 125/200/275 is exactly 10x the "Magic Damage
  Per Tick" row (12.5/20/27.5); the wiki text ("channels for up to 2.5
  seconds ... every 0.25 seconds") confirms the 10-tick cadence.

W (Void Swarm) overrides the batch packet's single-attack price with
the sourced voidling swarm: the W cast itself deals no direct damage
(the packet's 39 was one voidling attack priced as the whole ability),
and the voidling attacks ride a separate ``voidling_attacks`` proc row.
The per-attack formula and the attack-speed growth are sourced from the
wiki's Malzahar pets entry and the ability JSON:
- Per attack: level-based 5-64.5 (the 18-value per-level array) + rank
  base 12-20 + 40% bonus AD + 20% AP magic.
- Attack speed: 0.665*(1 + 0.02*(level-1)*(0.7025+0.0175*(level-1))),
  so ~0.891 AS at level 18 (~1.12s per attack).
- Summoning: the first Voidling appears after a 0.5s delay, each extra
  Voidling 0.5s later (the ability description); voidlings attack the
  target from their summon time.
"""

from __future__ import annotations

from typing import Any

from ..ability_spec import DamagePart
from ..stats import growth_multiplier
from .engine import SlotCtx, build_parser
from .reviewed_batch_01 import rank
from .reviewed_batch_04 import build_batch_module
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
    find_named_leveling,
    fixed_count_pet_row,
)

# E: 16 ticks over 4s (every 0.25s); R: 10 ticks over 2.5s (every 0.25s).
_E_TICKS = 16
_E_DURATION = 4.0
_E_TICK_INTERVAL = _E_DURATION / _E_TICKS  # "every 0.25 seconds"
_R_TICKS = 10
_R_DURATION = 2.5
_R_TICK_INTERVAL = _R_DURATION / _R_TICKS  # "every 0.25 seconds"

# HARDCODED: verify on patch updates — pet attack-speed growth is not in
# the champion JSON (the wiki's Malzahar#Pets entry):
# https://wiki.leagueoflegends.com/en-us/Malzahar
# Voidling attack speed = 0.665*(1 + 0.02*(level-1)*(0.7025+0.0175*(level-1))).
# Summon cadence: first Voidling after 0.5s, each extra 0.5s later
# (the W description).  The per-attack damage rows themselves are read
# from the champion JSON ("Magic Damage" leveling entry).
_VOIDLING_AS_BASE = 0.665
_VOIDLING_AS_GROWTH = 0.02
_VOIDLING_SUMMON_DELAY = 0.5
_VOIDLING_SUMMON_STAGGER = 0.5
_VOIDLING_DEFAULT_WINDOW = 5.0  # one rotation; timed fights pass the real window
_VOIDLING_MAX_ATTACKS_PER_UNIT = 40
_VOIDLING_ATTACK_ATTR = "Magic Damage"


def _voidling_attack_speed(level: int) -> float:
    """One Voidling's attacks per second at champion level (wiki pets).

    Relative growth reuses the canonical ``stats.growth_multiplier`` so the
    level 1-20 contract is enforced in one place (issue #164).
    """
    return _VOIDLING_AS_BASE * (
        1.0 + _VOIDLING_AS_GROWTH * (level - 1) * growth_multiplier(level)
    )


def _voidling_attack_damage(
    ability: dict[str, Any],
    level: int,
    w_rank: int,
    stats: dict[str, float],
) -> float:
    """One Voidling attack: per-level flat + per-rank base + 40% bAD + 20% AP.

    The four modifiers of the single "Magic Damage" leveling entry are,
    in order: the 18-value per-level flat, the 5-value per-rank flat,
    the 40% bonus-AD ratio, and the 20% AP ratio.
    """
    leveling = find_named_leveling(ability, _VOIDLING_ATTACK_ATTR)
    if leveling is None:
        raise ValueError(
            "Malzahar W: 'Magic Damage' leveling entry is missing from "
            "the ability JSON — cannot compute voidling attack damage"
        )
    flat_level = extract_value(ability, _VOIDLING_ATTACK_ATTR, level, 0)
    flat_rank = extract_value(ability, _VOIDLING_ATTACK_ATTR, w_rank, 1)
    bad_ratio = extract_value(ability, _VOIDLING_ATTACK_ATTR, w_rank, 2)
    ap_ratio = extract_value(ability, _VOIDLING_ATTACK_ATTR, w_rank, 3)
    return (
        flat_level
        + flat_rank
        + bad_ratio / 100.0 * stats.get("bonus_attack_damage", 0.0)
        + ap_ratio / 100.0 * stats.get("ability_power", 0.0)
    )


def _void_swarm(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: zero-damage summon cast + the voidling-attack proc row.

    One summon wave per fight window: ``voidling_count`` Voidlings (2-4,
    default 3 — the sourced per-cast cap of 1 + 2 Zz'Rot stacks) attack
    from their staggered summon times at the sourced attack speed.
    ``voidling_attacks`` overrides the per-Voidling attack count; the
    default is the sourced cadence truncated to the fight window.  The
    proc row is fixed-count — re-casting W refreshes the swarm in-game,
    which the option models instead of multiplying by W casts.
    """
    ability = ctx.ability()
    if ability is None:
        return None
    w_rank = ctx.rank_for()
    if w_rank < 1:
        return None

    count = min(max(int(ctx.options.get("voidling_count", 3)), 2), 4)
    per_attack = _voidling_attack_damage(ability, ctx.level, w_rank, ctx.stats)
    interval = 1.0 / _voidling_attack_speed(ctx.level)
    window = float(ctx.options.get("fight_duration_seconds", _VOIDLING_DEFAULT_WINDOW))
    requested = ctx.options.get("voidling_attacks")
    attack_times: list[float] = []
    for index in range(count):
        summon_time = _VOIDLING_SUMMON_DELAY + _VOIDLING_SUMMON_STAGGER * index
        if requested is None:
            per_unit = int((window - summon_time) // interval)
            per_unit = max(0, per_unit)
        else:
            per_unit = min(max(int(requested), 0), _VOIDLING_MAX_ATTACKS_PER_UNIT)
        attack_times.extend(summon_time + (n + 1) * interval for n in range(per_unit))
    total_attacks = len(attack_times)
    if total_attacks > 0:
        ctx.results["voidling_attacks"] = fixed_count_pet_row(
            "Voidling Attacks",
            "magic",
            per_attack,
            attack_times,
            (
                f"{count} Voidling(s), {total_attacks} attack(s) total at "
                f"{per_attack:.2f} magic each ({interval:.2f}s cadence)"
            ),
        )

    return {
        "name": ability.get("name", "Void Swarm"),
        "rank": w_rank,
        "cooldown": extract_cooldown(ability, w_rank),
        "damage_type": "magic",
        "total_raw": 0.0,  # the summon itself deals no direct damage
        "parts": (),
        "detail": (
            f"Summons {count} Voidling(s); their attacks are priced on the "
            "voidling_attacks row."
        ),
    }


def _malefic_visions(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: the full 4-second Total Magic Damage across 16 sourced ticks."""
    ability = ctx.ability()
    if ability is None:
        return None
    selected_rank = rank(ctx)
    if selected_rank < 1:
        return None
    total = extract_named(
        ability, "Total Magic Damage", selected_rank, ctx.stats, ctx.target
    )
    entry = damage_entry(
        ability.get("name", "Malefic Visions"),
        selected_rank,
        extract_cooldown(ability, selected_rank),
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
    # Item burns (Liandry's, Blackfire Torch) stay refreshed through the
    # whole 4-second infection (the Cassiopeia rule).
    entry["dot_duration"] = _E_DURATION
    return entry


def _nether_grasp(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: the full 2.5-second Total Magic Damage across 10 sourced ticks.

    Only the flat "Total Magic Damage" row (effect 0) is read; the
    Null Zone's separate max-health row stays out of scope, as in the
    reviewed packet.
    """
    ability = ctx.ability()
    if ability is None:
        return None
    selected_rank = rank(ctx)
    if selected_rank < 1:
        return None
    total = extract_named(
        ability, "Total Magic Damage", selected_rank, ctx.stats, ctx.target
    )
    entry = damage_entry(
        ability.get("name", "Nether Grasp"),
        selected_rank,
        extract_cooldown(ability, selected_rank),
        total,
        "magic",
    )
    entry["parts"] = (
        DamagePart(
            "magic",
            total / _R_TICKS,
            count=_R_TICKS,
            time_offset=_R_TICK_INTERVAL,
            hit_interval=_R_TICK_INTERVAL,
        ),
    )
    entry["dot_duration"] = _R_DURATION
    return entry


parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("Malzahar")
# Override the packet DoT rows with the full-total tick pricing above and
# the packet's single-attack W with the sourced voidling swarm, then
# rebuild the parser so the module's parse_abilities sees them.
SLOTS = {**SLOTS, "W": _void_swarm, "E": _malefic_visions, "R": _nether_grasp}
parse_abilities = build_parser(SLOTS, "Malzahar")
OPTIONS = [
    *OPTIONS,
    {
        "key": "voidling_count",
        "type": "int",
        "default": 3,
        "min": 2,
        "max": 4,
        "label": (
            "Active Voidlings (3 = one full W cast at 2 Zz'Rot stacks; "
            "4 models an overlapping second wave in a sustained window)"
        ),
    },
    {
        "key": "voidling_attacks",
        "type": "int",
        "default": 8,
        "label": (
            "Attacks per Voidling (0 = none; defaults to the sourced "
            "attack-speed cadence over the fight window)"
        ),
        "min": 0,
        "max": 40,
    },
]

ASSUMPTIONS = [
    *ASSUMPTIONS,
    "W is a summon: the cast row carries no direct damage; voidling "
    "attacks ride the sourced 'Magic Damage' leveling formula "
    "(per-level flat + per-rank base + 40% bonus AD + 20% AP) on a "
    "separate voidling_attacks proc row",
    "Voidling attack cadence is the wiki pets attack speed "
    "(0.665 + 2% growth per level, ~0.891 AS at 18) with the 0.5s "
    "summon delay and 0.5s stagger; the default attack count truncates "
    "that cadence to the fight window",
    "One summon wave per fight window; re-casting W refreshes the swarm "
    "in-game, modeled by the voidling_count option (up to 4) instead of "
    "multiplying the proc row by W casts",
]

MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "E", "R"} else "out_of_scope")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
