"""Braum — slot map for the archetype engine.

Why each slot is non-generic:
- P (Concussive Blows) is a stack-cycle passive the on-hit framework
  cannot express: autos AND Q applications build stacks, the 4th stack
  procs trigger damage, then the target is stack-IMMUNE for 8/6/4s
  (levels 1/6/11) during which each auto (autos only — not Q) deals 40%
  of the trigger as bonus magic damage, and the cycle restarts. The
  generic parser instead applied the 40% bonus on EVERY auto (the
  JSON's only leveling array, attribute=None). Trigger damage
  (16 + 10 x level), stun, and immunity period exist only in
  description prose, so the formula lives here. Timed fights walk the
  fight's auto/Q hit timeline (via the pipeline-injected
  ``fight_duration_seconds`` / ``auto_attack_uptime`` reserved
  options); one-rotation mode emits nothing — a single Q application
  never reaches 4 stacks.
- Q (Winter's Bite) scales with 2.5% of BRAUM'S OWN max health — the
  JSON unit ("% of Braum's maximum health") is champion-named, which
  ``scaling.resolve_scaling`` cannot map, so a ``sum_modifiers``
  override resolves it against ``ctx.stats["health"]``.
- W (Stand Behind Me) is a zero-damage BUFF slot granting SELF
  20-40 (+36% bonus) armor AND magic resistance (effect[1]; the
  effect[0] ally values are ignored — single-champion calculator).
  Two coupled stats with flat+percent parts exceed the ``stat_buff``
  factory (one stat, flat or percent). Stats-panel only: no damage in
  the kit scales off resistances, so nothing feeds back into parsing.
- E (Unbreakable) is a typed directional projectile-defense atom. The
  selected active window blocks the first selected hit and reduces later
  selected hits by the sourced rank value.
- R (Glacial Fissure) is a clean generic read ("Magic Damage",
  150/250/350 + 60% AP); knockup and slow field are CC only.
"""

import math
from typing import Any

from ..ability_spec import DamagePart
from ..damage import effective_cooldown
from .engine import BUFF, SlotCtx, build_parser
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_value,
    find_named_leveling,
    simple_damage,
    sum_modifiers,
    with_control,
)

# HARDCODED: verify on patch updates — Concussive Blows' trigger damage,
# stack count, stack duration, and immunity period exist only in
# description prose (the JSON's sole leveling array is the 40% bonus
# with attribute=None, over-extended to 40 entries — trust the formula).
# https://wiki.leagueoflegends.com/en-us/Braum
_STACKS_TO_PROC = 4
_STACK_DURATION = 4.0  # seconds, refreshing per application
_TRIGGER_BASE = 16.0  # trigger magic damage = 16 + 10 x level
_TRIGGER_PER_LEVEL = 10.0
_BONUS_AUTO_RATIO = 0.4  # immunity-window autos deal 40% of the trigger
# Stack-immunity window after a proc: 8/6/4s at champion levels 1/6/11.
_IMMUNITY_BREAKPOINTS = ((11, 4.0), (6, 6.0), (1, 8.0))
# Event kinds for the passive's hit timeline; Q sorts before autos on
# equal timestamps (the rotation leads the fight model, as in damage.py).
_Q_HIT = 0
_AUTO = 1


def _trigger_damage(level: int) -> float:
    """Concussive Blows trigger damage at a champion level (16 + 10 x lvl).

    Extrapolates linearly past 18 (216 at level 20), consistent with the
    JSON's 40%-bonus array.
    """
    return _TRIGGER_BASE + _TRIGGER_PER_LEVEL * level


def _immunity_window(level: int) -> float:
    """Stack-immunity duration after a proc at a champion level."""
    for min_level, seconds in _IMMUNITY_BREAKPOINTS:
        if level >= min_level:
            return seconds
    return _IMMUNITY_BREAKPOINTS[-1][1]


def _hit_timeline(ctx: SlotCtx, duration: float) -> list[tuple[float, int]]:
    """Braum's stacking hits over a timed fight: autos + Q applications.

    Mirrors the fight engine's scheduling: autos land at ``i / rate``
    with ``rate = attack_speed x auto_attack_uptime`` (uptime 0 means no
    autos), and Q is cast at t=0 then on cooldown (ability haste plus
    basic-ability haste), giving ``1 + duration // cd`` casts — the same
    count the rotation computes.
    """
    events: list[tuple[float, int]] = []

    uptime = float(ctx.options.get("auto_attack_uptime", 0.0))
    autos_per_second = ctx.stats.get("attack_speed", 0.0) * uptime
    if autos_per_second > 0:
        events.extend(
            (i / autos_per_second, _AUTO)
            for i in range(math.floor(autos_per_second * duration))
        )

    q_ability = ctx.ability("Q")
    q_rank = ctx.rank_for("Q")
    if q_ability is not None and q_rank >= 1:
        haste = ctx.stats.get("ability_haste", 0.0) + ctx.stats.get(
            "basic_ability_haste", 0.0
        )
        cd = effective_cooldown(extract_cooldown(q_ability, q_rank), haste)
        casts = 1 + int(duration / cd) if cd > 0 else 1
        events.extend((i * cd, _Q_HIT) for i in range(casts))

    events.sort()
    return events


def _concussive_blows(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: walk the auto/Q timeline through stack -> proc -> immunity cycles.

    Each auto or Q application adds a stack (stacks reset if 4s pass
    without one — matters when only Q applies them); the 4th procs the
    trigger damage and opens the immunity window, inside which each AUTO
    deals 40% of the trigger and nothing stacks. Emits one aggregate
    proc entry; per-cast mode (no injected fight window) emits nothing —
    a single rotation's lone Q application never reaches 4 stacks.
    """
    ability = ctx.ability()
    if ability is None:
        return None
    duration = ctx.options.get("fight_duration_seconds")
    if duration is None:
        return None

    trigger = _trigger_damage(ctx.level)
    bonus_per_auto = _BONUS_AUTO_RATIO * trigger
    window = _immunity_window(ctx.level)

    stacks = 0
    procs = 0
    bonus_autos = 0
    immune_until = 0.0
    last_application: float | None = None
    damage_events: list[dict[str, Any]] = []
    for time, kind in _hit_timeline(ctx, float(duration)):
        if time < immune_until:
            if kind == _AUTO:
                bonus_autos += 1
                damage_events.append(
                    {
                        "time": time,
                        "damage_type": "magic",
                        "damage": bonus_per_auto,
                        "event_precision": "exact",
                    }
                )
            continue
        if last_application is not None and time - last_application > _STACK_DURATION:
            stacks = 0
        stacks += 1
        last_application = time
        if stacks >= _STACKS_TO_PROC:
            procs += 1
            stacks = 0
            last_application = None
            immune_until = time + window
            damage_events.append(
                {
                    "time": time,
                    "damage_type": "magic",
                    "damage": trigger,
                    "event_precision": "exact",
                    "cc_kind": "stun",
                    "cc_duration": 1.25 + 0.5 * (ctx.level - 1) / 17.0,
                    "cc_reviewed": True,
                }
            )

    if procs == 0:
        return None

    total = procs * trigger + bonus_autos * bonus_per_auto
    return {
        "name": ability.get("name", "Concussive Blows"),
        "damage_type": "magic",
        "total_raw": total,
        "parts": (
            DamagePart("magic", trigger, count=procs),
            DamagePart("magic", bonus_per_auto, count=bonus_autos),
        ),
        "proc_count": 1,
        "timeline_event_model": "braum_concussive",
        "damage_events": damage_events,
        "event_phase": "effect",
        "detail": (
            f"{procs} proc(s) + {bonus_autos} empowered auto(s) "
            f"over {float(duration):g}s"
        ),
    }


def _winters_bite(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: base magic damage + 2.5% of Braum's OWN built max health."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    leveling = find_named_leveling(ability, "Magic Damage")
    if leveling is None:
        # A silent 0 would hide the whole ability — fail loudly instead.
        raise ValueError(
            "Braum Q: 'Magic Damage' leveling entry missing from the "
            "ability JSON — cannot compute Winter's Bite damage"
        )

    def own_max_health(unit: str, value: float) -> float | None:
        if "Braum" in unit and "maximum health" in unit:
            return value / 100.0 * ctx.stats.get("health", 0.0)
        return None

    total = sum_modifiers(
        leveling, rank, ctx.stats, ctx.target, modifier_override=own_max_health
    )
    return damage_entry(
        ability.get("name", "Winter's Bite"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )


def _stand_behind_me(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: self 20-40 (+36% bonus) armor AND magic resist; zero damage."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    entry = damage_entry(
        ability.get("name", "Stand Behind Me"),
        rank,
        extract_cooldown(ability, rank),
        0.0,
        "magic",
    )
    if not ctx.options.get("w_active", True):
        return entry

    def self_buff(attr: str, bonus_stat: str) -> float:
        flat = extract_value(ability, attr, rank)
        percent = extract_value(ability, attr, rank, modifier_index=1)
        return flat + percent / 100.0 * ctx.stats.get(bonus_stat, 0.0)

    entry["stat_buff"] = {
        "armor": self_buff("Self Bonus Armor", "bonus_armor"),
        "magic_resistance": self_buff(
            "Self Bonus Magic Resistance", "bonus_magic_resistance"
        ),
    }
    return entry


_stand_behind_me.phase = BUFF


def _unbreakable(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: expose the selected directional projectile-defense atom."""
    ability = ctx.ability()
    rank = ctx.rank_for()
    if ability is None or rank < 1:
        return None
    reduction = extract_value(ability, "Damage reduction", rank) / 100.0
    duration = extract_value(ability, "Barrier Duration", rank)
    active = bool(ctx.options.get("e_active", False))
    selected_duration = float(ctx.options.get("e_active_seconds", 0.0) or 0.0)
    if selected_duration > 0.0:
        duration = min(duration, selected_duration)
    return {
        "name": ability.get("name", "Unbreakable"),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "total_raw": 0.0,
        "damage_type": "magic",
        "parts": (),
        "defensive_interaction": {
            "kind": "braum_unbreakable",
            "active": active,
            "duration": duration if active else 0.0,
            "damage_reduction": reduction,
            "full_block_first": True,
            "blocked_sources": list(ctx.options.get("e_blocked_skillshots", [])),
        },
        "detail": (
            "Directional barrier: first selected champion hit is fully "
            f"reduced, later selected hits lose {reduction:.0%} damage. "
            f"Source duration at rank: {duration:g}s."
        ),
    }


_unbreakable.phase = BUFF


OPTIONS: list[dict[str, Any]] = [
    {
        "key": "w_active",
        "type": "bool",
        "default": True,
        "label": (
            "W (Stand Behind Me) active: grants self 20-40 (+36% bonus) "
            "armor and magic resistance"
        ),
    },
    {
        "key": "e_active",
        "type": "bool",
        "default": False,
        "label": "E (Unbreakable) active against selected skillshots",
    },
    {
        "key": "e_active_from",
        "type": "float",
        "default": 0.0,
        "min": 0.0,
        "max": 120.0,
        "label": "E active start time in seconds",
    },
    {
        "key": "e_active_seconds",
        "type": "float",
        "default": 0.0,
        "min": 0.0,
        "max": 4.0,
        "label": "E active seconds; zero uses the sourced rank duration",
    },
    {
        "key": "e_blocked_skillshots",
        "type": "string_list",
        "default": [],
        "max_items": 24,
        "label": (
            "Skillshot slots to block; an empty list blocks all marked " "skillshots"
        ),
    },
    {
        "key": "e_blocked_event_ids",
        "type": "string_list",
        "default": [],
        "max_items": 24,
        "label": (
            "Specific incoming event ids to block (e.g. "
            "'main:enemy:Braum:1'). Event ids are positional per "
            "scenario: builds, ranks, or roster changes renumber them. "
            "An empty list blocks nothing by event id."
        ),
    },
]

ASSUMPTIONS = [
    "Passive stacks come only from Braum's own basic attacks and Q "
    "(solo — allied champions' attacks, which add stacks in real games, "
    "are not modeled)",
    "Passive trigger damage extrapolates linearly past level 18 "
    "(16 + 10 x level; 216 at level 20), consistent with the JSON's "
    "bonus-damage array",
    "Passive is valued only in timed fights (the stack cycle walks the "
    "auto/Q timeline, with Q assumed cast on cooldown from t=0); in "
    "one-rotation mode a single Q application never reaches 4 stacks, so "
    "no passive damage is shown",
    "Passive stacks last 4s (refreshing) — with autos in the timeline "
    "they never expire mid-buildup; without autos (Q-only stacking) the "
    "expiry IS modeled, so the passive correctly never procs off Q alone",
    "Passive stun (1.25-1.75s) is an authored control interval. R's "
    "maximum knock-up duration is sourced from the cached rank row; the "
    "slow field remains utility",
    "Q's 2.5% max HP scaling uses Braum's own built max HP",
    "Q applies a passive stack but no on-hit effects and no "
    "immunity-window bonus (autos only)",
    "E (Unbreakable) uses the cached Barrier Duration and Damage reduction "
    "rows. The interaction atom blocks the first selected hit and reduces "
    "later selected hits. The scenario chooses the active window, source "
    "slots, and optional specific event ids (e_blocked_event_ids). Event "
    "ids are positional per scenario ('attacker:defender:index'); changes "
    "to the build, ranks, or roster renumber them, and any selected id that "
    "never matches an incoming event is reported on the survival receipt "
    "as blocked_event_ids_unmatched.",
    "W resistances affect the stats panel only; no damage in the kit "
    "scales off them",
]

SLOTS = {
    "Q": _winters_bite,
    "W": _stand_behind_me,
    "E": _unbreakable,
    "R": with_control(
        simple_damage(attr="Magic Damage", dmg_type="magic"),
        kind="knockup",
        duration_attr="Maximum Knock up Duration",
    ),
    "P": _concussive_blows,
}

parse_abilities = build_parser(SLOTS, "Braum")


# Authoritative review metadata (issue #161).
SOURCES = [
    {
        "label": "Local League Wiki cache",
        "url": "https://wiki.leagueoflegends.com/en-us/Braum",
        "revision_id": 4022592,
        "revision_timestamp": "2026-05-27T00:32:44Z",
    }
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in SLOTS else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
