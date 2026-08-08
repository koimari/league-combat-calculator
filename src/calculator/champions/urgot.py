"""Urgot — CP10.9 full-entry-reviewed packet module (E9-2 fixes).

E9-2 gap fixes over the packet module:
- W (Purge) is a 4-second channel firing at a fixed 3.0 attack speed:
  12 sourced shots (3.0 AS x 4s), each dealing the "Modified Physical
  Damage" row (12 + 20-34% AD), at a 1/3s cadence.  The packet priced
  ONE shot, understating the core DPS.
- P (Echoing Flames) is modeled as the leg on-hit: each shotgun leg
  that fires deals 40% : 100% (based on level) AD (+ 2% : 6% (based on
  level) of the target's maximum health) physical damage.  The leg
  rotation/cooldown cadence is combat state, so the user sets how many
  legs fire (``p_legs``, default 1).
- R (Fear Beyond Death) prices the chem-drill's initial physical damage
  row; the Mercy recast below 25% maximum health is an execution — a
  kill boundary, documented like Pyke's R (not priced as damage).
- E (Disdain) shield stays authored by the E8c support scanner.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .packet_module import build_packet_module
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
    proc_damage,
)

PACKET_SHA256 = "9d82bf325e3fbc81b2fed62c53b2501f2bb7aa95228e266e6daeb24e5e7392d6"

_packet_parse, _packet_slots, _packet_assumptions, _packet_sources, _packet_options = (
    build_packet_module("Urgot", PACKET_SHA256)
)
PACKET_SPEC = _packet_slots.packet_spec

# HARDCODED: verify on patch updates — Purge "autonomously fir[es] at the
# nearest enemy at a fixed 3.0 attack speed" for 4 seconds (cached W
# description): 12 shots at a 1/3s cadence.  The leg on-hit reads the
# cached Per-Level Scaling (% AD) and Max Health Damage (%) rows.
_W_SHOTS = 12
_W_TICK_INTERVAL = 1.0 / 3.0
_W_DURATION = 4.0


def _purge(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: 12 sourced shots at the fixed 3.0 attack speed over 4 seconds."""
    ability = ctx.ability("W", 0)
    if ability is None:
        return None
    rank = ctx.rank_for("W")
    if rank < 1:
        return None

    per_shot = extract_named(
        ability, "Modified Physical Damage", rank, ctx.stats, ctx.target
    )
    entry = damage_entry(
        ability.get("name", "Purge"),
        rank,
        extract_cooldown(ability, rank),
        per_shot * _W_SHOTS,
        "physical",
    )
    entry["parts"] = (
        DamagePart(
            "physical",
            per_shot,
            count=_W_SHOTS,
            time_offset=0.0,
            hit_interval=_W_TICK_INTERVAL,
        ),
    )
    entry["dot_duration"] = _W_DURATION
    entry["detail"] = (
        f"{_W_SHOTS} sourced shots over {_W_DURATION:g}s at the fixed 3.0 "
        "attack speed (Modified Physical Damage x 12); on-hit effects at "
        "50% effectiveness are state."
    )
    return entry


def _echoing_flames_per_proc(ctx: SlotCtx, ability: dict[str, Any]) -> float:
    """One leg shot: per-level % AD + per-level % of target max health."""
    ad_percent = extract_value(ability, "Per-Level Scaling", ctx.level, 0)
    max_hp_percent = extract_value(ability, "Max Health Damage", ctx.level, 0)
    ad = float(ctx.stats.get("attack_damage", 0.0) or 0.0)
    target_max = float(ctx.target.get("target_max_health", 0.0) or 0.0)
    return ad_percent / 100.0 * ad + max_hp_percent / 100.0 * target_max


def _fear_beyond_death(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: chem-drill initial damage; the sub-25% execution is a boundary."""
    ability = ctx.ability("R", 0)
    if ability is None:
        return None
    rank = ctx.rank_for("R")
    if rank < 1:
        return None
    value = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Fear Beyond Death"),
        rank,
        extract_cooldown(ability, rank),
        value,
        "physical",
    )
    entry["parts"] = (DamagePart("physical", value),)
    entry["detail"] = (
        "Chem-drill initial physical damage; the Mercy recast below 25% "
        "of the target's maximum health is an execution — a kill "
        "boundary (Pyke R convention), documented not priced.  The "
        "post-execution fear is CC state."
    )
    return entry


_echoing_flames_proc = proc_damage(
    _echoing_flames_per_proc,
    "physical",
    count_option="p_legs",
    default_count=1,
    name="Echoing Flames",
    phase_order_events=True,
)


SLOTS = dict(_packet_slots)
SLOTS["P"] = _echoing_flames_proc
SLOTS["W"] = _purge
SLOTS["R"] = _fear_beyond_death
parse_abilities = build_parser(SLOTS, "Urgot")

OPTIONS: list[dict[str, Any]] = list(_packet_options) + [
    {
        "key": "p_legs",
        "type": "int",
        "default": 1,
        "min": 0,
        "max": 6,
        "label": (
            "Echoing Flames legs that fire (each shotgun leg procs once "
            "per its cooldown)"
        ),
    },
]

ASSUMPTIONS = list(_packet_assumptions) + [
    "W (Purge) prices all 12 sourced shots of the 4-second channel at the "
    "fixed 3.0 attack speed (3.0 AS x 4s; Modified Physical Damage row "
    "per shot, 1/3s cadence); on-hit effects at 50% effectiveness and "
    "the monster/minion minimum threshold are state",
    "P (Echoing Flames) deals per-level % AD (40% : 100%) plus per-level "
    "% of the target's maximum health (2% : 6%) physical damage per leg "
    "shot; the leg rotation/cooldown cadence is combat state, so the "
    "user sets how many legs fire (p_legs, default 1)",
    "R (Fear Beyond Death) prices the chem-drill's initial Physical "
    "Damage row; the Mercy recast below 25% maximum health is an "
    "execution — a kill boundary, documented not priced (Pyke R "
    "convention); the post-execution fear is CC state",
    "E (Disdain) shield is authored by the E8c support scanner.",
]

SOURCES = list(_packet_sources)
MODULE_COVERAGE = {
    "P": "modeled",
    "Q": "modeled",
    "W": "modeled",
    "E": "modeled",
    "R": "modeled",
}
REVIEW_STATUS = "reviewed_module"
