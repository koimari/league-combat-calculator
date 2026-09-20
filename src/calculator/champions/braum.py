"""Braum: slot map for the archetype engine.

P (Concussive Blows) is a stack cycle no on-hit shape expresses.  Attacks AND Q
applications build stacks, the fourth procs the trigger damage, and the target is
then stack-immune for 8, 6 or 4 seconds by level, during which every basic
attack, autos only and never Q, deals 40% of the trigger before the cycle
restarts.  Trigger damage, stun and immunity live only in description prose, so
the formula lives here, and one-rotation emits nothing: one Q never reaches four.
Q (Winter's Bite) scales with 2.5% of BRAUM'S OWN maximum health, and that
champion-named unit is one ``scaling.resolve_scaling`` cannot map, so a
``sum_modifiers`` override resolves it against ``ctx.stats["health"]``.
W (Stand Behind Me) is a zero-damage BUFF slot granting himself both armor and
magic resistance.  Two coupled stats with flat and percent parts exceed the
``stat_buff`` factory, and nothing in the kit scales off resistances, so it
reaches the stats panel and never feeds back into parsing.
E (Unbreakable) is a typed directional projectile-defense atom: the active
window blocks the first selected hit and reduces later ones by the ranked value.
R (Glacial Fissure) is a clean generic read; its knockup and slow field are
control only.
"""

import math
from typing import Any

from ..ability_spec import DamagePart
from ..binary_roots import data_value, spell_object
from ..stat_formulas import effective_cooldown
from .engine import BUFF, SlotCtx, build_parser
from .inputs import bool_option, float_option
from .module_helpers import ability_slot, at_level, ranked_slot
from .shared_option_keys import E_BLOCKED_EVENT_IDS, E_BLOCKED_SKILLSHOTS, E_WINDOW
from .slot_cc import CC_PER_PART
from .slot_control import with_control
from .slot_entries import damage_entry
from .slot_extract import (
    ability_name,
    extract_cooldown,
    extract_value,
    find_named_leveling,
    sum_modifiers,
)
from .slotlib import simple_damage
from .source_receipts import load_champion_sources

# HARDCODED: verify on patch updates — Concussive Blows' trigger damage,
# stack count, stack duration, and immunity period remain description/prose
# roots.  The binary's AlreadyStunnedDamageAmp roots the 40% bonus-autos term.
# https://wiki.leagueoflegends.com/en-us/Braum
_BRAUM_P_SPELL = spell_object("Braum", "BraumPassive")
_STACKS_TO_PROC = int(data_value(_BRAUM_P_SPELL, "StackCap"))
_STACK_DURATION = data_value(
    _BRAUM_P_SPELL, "StackDuration"
)  # seconds, refreshing per application
_TRIGGER_BASE = 16.0  # trigger magic damage = 16 + 10 x level
_TRIGGER_PER_LEVEL = 10.0
_BONUS_AUTO_RATIO = data_value(_BRAUM_P_SPELL, "AlreadyStunnedDamageAmp")
# Stack-immunity window after a proc: 8/6/4s at champion levels 1/6/11.
_IMMUNITY_BREAKPOINTS = ((11, 4.0), (6, 6.0), (1, 8.0))
# Event kinds for the passive's hit timeline; Q sorts before autos on
# equal timestamps (the rotation leads the fight model, as in damage.py).
_Q_HIT = 0
_AUTO = 1


def _trigger_damage(level: int) -> float:
    """Trigger damage at a level (16 + 10 x lvl, linear past 18: 216 at 20)."""
    return _TRIGGER_BASE + _TRIGGER_PER_LEVEL * level


def _hit_timeline(ctx: SlotCtx, duration: float) -> list[tuple[float, int]]:
    """Braum's stacking hits over a timed fight: autos + Q applications.

    Mirrors the fight engine's scheduling: autos land at ``i / rate``
    with ``rate = attack_speed x auto_attack_uptime`` (uptime 0 means no
    autos), and Q is cast at t=0 then on cooldown (ability haste plus
    basic-ability haste), giving ``1 + duration // cd`` casts — the same
    count the rotation computes.  An ``auto_attacks_only`` window
    schedules zero casts, so the stream is the ambient swings alone.
    """
    events: list[tuple[float, int]] = []

    uptime = float(ctx.option("auto_attack_uptime"))
    autos_per_second = ctx.stat("attack_speed") * uptime
    if autos_per_second > 0:
        events.extend(
            (i / autos_per_second, _AUTO)
            for i in range(math.floor(autos_per_second * duration))
        )

    q_ability = ctx.ability("Q")
    q_rank = ctx.rank_for("Q")
    if q_ability is not None and q_rank >= 1 and not ctx.option("auto_attacks_only"):
        haste = ctx.stat("ability_haste") + ctx.stat("basic_ability_haste")
        cd = effective_cooldown(extract_cooldown(q_ability, q_rank), haste)
        casts = 1 + int(duration / cd) if cd > 0 else 1
        events.extend((i * cd, _Q_HIT) for i in range(casts))

    events.sort()
    return events


@ability_slot()
def _concussive_blows(ctx: SlotCtx, ability: dict[str, Any]) -> dict[str, Any] | None:
    """P: walk the auto/Q timeline through stack -> proc -> immunity cycles.

    Each auto or Q application adds a stack (stacks reset if 4s pass
    without one — matters when only Q applies them); the 4th procs the
    trigger damage and opens the immunity window, inside which each AUTO
    deals 40% of the trigger and nothing stacks. Emits one aggregate
    proc entry; per-cast mode (no injected fight window) emits nothing —
    a single rotation's lone Q application never reaches 4 stacks.
    """
    duration = ctx.options.get("fight_duration_seconds")
    if duration is None:
        return None

    trigger = _trigger_damage(ctx.level)
    bonus_per_auto = _BONUS_AUTO_RATIO * trigger
    window = at_level(_IMMUNITY_BREAKPOINTS, ctx.level)

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
        "name": ability_name(ability),
        "damage_type": "magic",
        "total_raw": total,
        "parts": (
            DamagePart("magic", trigger, count=procs),
            DamagePart("magic", bonus_per_auto, count=bonus_autos),
        ),
        "proc_count": 1,
        "timeline_event_model": "module_walk",
        "damage_events": damage_events,
        "event_phase": "effect",
        "detail": (
            f"{procs} proc(s) + {bonus_autos} empowered auto(s) "
            f"over {float(duration):g}s"
        ),
    }


@ranked_slot
def _winters_bite(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """Q: base magic damage + 2.5% of Braum's OWN built max health."""

    leveling = find_named_leveling(ability, "Magic Damage")
    if leveling is None:
        # A silent 0 would hide the whole ability — fail loudly instead.
        raise ValueError(
            "Braum Q: 'Magic Damage' leveling entry missing from the "
            "ability JSON — cannot compute Winter's Bite damage"
        )

    def own_max_health(unit: str, value: float) -> float | None:
        if "Braum" in unit and "maximum health" in unit:
            return value / 100.0 * ctx.stat("health")
        return None

    total = sum_modifiers(
        leveling, rank, ctx.stats, ctx.target, modifier_override=own_max_health
    )
    # One shot of ice on "the first enemy hit" — one part and one hit,
    # which carries Q's reviewed slow into the event ledger.
    return damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
        event_order_certified="single_hit",
    )


@ranked_slot
def _stand_behind_me(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """W: self 20-40 (+36% bonus) armor AND magic resist; zero damage."""

    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        0.0,
        "magic",
    )
    if not ctx.option("w_active"):
        return entry

    def self_buff(attr: str, bonus_stat: str) -> float:
        flat = extract_value(ability, attr, rank)
        percent = extract_value(ability, attr, rank, modifier_index=1)
        return flat + percent / 100.0 * ctx.stat(bonus_stat)

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
    active = bool(ctx.option(E_WINDOW.active))
    selected_duration = float(ctx.option(E_WINDOW.active_seconds) or 0.0)
    if selected_duration > 0.0:
        duration = min(duration, selected_duration)
    return {
        "name": ability_name(ability),
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
            "blocked_sources": list(ctx.option(E_BLOCKED_SKILLSHOTS)),
        },
        "detail": (
            "Directional barrier: first selected champion hit is fully "
            f"reduced, later selected hits lose {reduction:.0%} damage. "
            f"Source duration at rank: {duration:g}s."
        ),
    }


_unbreakable.phase = BUFF


OPTIONS: list[dict[str, Any]] = [
    bool_option(
        "w_active",
        True,
        label="W (Stand Behind Me) active: grants self 20-40 (+36% bonus) "
        "armor and magic resistance",
        rotation={"role": "self_state", "slot": "W"},
    ),
    bool_option(
        E_WINDOW.active,
        False,
        label="E (Unbreakable) active against selected skillshots",
        rotation={"role": "self_state", "slot": "E"},
    ),
    float_option(
        E_WINDOW.active_from,
        0.0,
        minimum=0.0,
        maximum=120.0,
        label="E active start time in seconds",
        rotation={"role": "self_state", "slot": "E"},
    ),
    float_option(
        E_WINDOW.active_seconds,
        0.0,
        minimum=0.0,
        maximum=4.0,
        label="E active seconds; zero uses the sourced rank duration",
        rotation={"role": "self_state", "slot": "E"},
    ),
    {
        "key": E_BLOCKED_SKILLSHOTS,
        "type": "string_list",
        "default": [],
        "max_items": 24,
        "label": (
            "Skillshot slots to block; an empty list blocks all marked " "skillshots"
        ),
        "rotation": {"role": "irrelevant", "slot": "E"},
    },
    {
        "key": E_BLOCKED_EVENT_IDS,
        "type": "string_list",
        "default": [],
        "max_items": 24,
        "label": (
            "Specific incoming event ids to block (e.g. "
            "'main:enemy:Braum:1'). Event ids are positional per "
            "scenario: builds, ranks, or roster changes renumber them. "
            "An empty list blocks nothing by event id."
        ),
        "rotation": {"role": "irrelevant", "slot": "E"},
    },
]

ASSUMPTIONS = [
    "Passive stacks come only from Braum's own attacks and Q; allied champions' "
    "attacks are not modeled.",
    "Passive trigger damage extrapolates linearly past 18 (16 + 10 x level, 216 at "
    "20), as the JSON array does.",
    "The passive prices in timed fights only: the stack cycle walks the auto and Q "
    "timeline, Q assumed on cooldown.",
    "One rotation never reaches 4 stacks from a single Q, so it shows no passive "
    "damage.",
    "An autos-only fight casts no Q, so only the ambient swings stack "
    "(auto_attacks_only).",
    "Passive stacks last 4s and refresh, so with autos in the timeline they never "
    "expire mid-buildup.",
    "With Q-only stacking the expiry is modeled, so the passive never procs off Q "
    "alone.",
    "The passive stun of 1.25 to 1.75s is an authored control interval.",
    "R's maximum knock-up is the cached rank row; its slow field remains utility.",
    "Q's 2.5% max HP scaling uses Braum's own built max HP",
    "Q applies a passive stack but no on-hit effects and no "
    "immunity-window bonus (autos only)",
    "E (Unbreakable) reads the cached Barrier Duration and Damage reduction rows.",
    "Its atom blocks the first selected hit and reduces later ones; the scenario "
    "picks window, slots and event ids.",
    "Event ids are positional per scenario, and an id matching nothing is reported as "
    "blocked_event_ids_unmatched.",
    "W resistances affect the stats panel only; no damage in the kit "
    "scales off them",
]

SLOTS = {
    "Q": _winters_bite,
    "W": _stand_behind_me,
    "E": _unbreakable,
    # One fissure sweep on one target, so one part and one hit — the
    # certification that carries R's reviewed knockup into the ledger,
    # with the interval itself read off the cached rank row.
    "R": with_control(
        simple_damage(
            attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
        ),
        duration_attr="Maximum Knock up Duration",
    ),
    "P": _concussive_blows,
}

# Reviewed crowd control, read from the cached kit.  Q (Winter's Bite)
# deals "magic damage to the first enemy hit and slow[s] them by 70%
# decaying over 2 seconds".  R (Glacial Fissure) damages "enemies within
# its path as well as those around Braum", and "the first target hit is
# knocked up for at least 0.6 seconds.  All other enemies hit are knocked
# up for 0.6 seconds".  W is the shield/dash row with no damage part and
# E is the directional barrier, which controls nobody.  P's Concussive
# Blows stun is not declared here because the proc is not a cast: the
# slot authors its own timeline events and stamps the level-scaled stun
# interval on the one that procs.
MODULE_CC = {"Q": "slow", "R": "knockup", "P": CC_PER_PART, "W": "none", "E": "none"}

parse_abilities = build_parser(SLOTS, "Braum", cc_kinds=MODULE_CC)


SOURCES = load_champion_sources("Braum")
