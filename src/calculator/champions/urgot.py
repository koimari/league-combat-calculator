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
from ..binary_roots import data_value, spell_object
from .engine import SlotCtx
from .inputs import int_option
from .module_helpers import ranked_slot
from .packet_module import build_packet_module
from .slotlib import (
    ability_name,
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
    proc_damage,
)

PACKET_SHA256 = "9d82bf325e3fbc81b2fed62c53b2501f2bb7aa95228e266e6daeb24e5e7392d6"


# HARDCODED: verify on patch updates — Purge "autonomously fir[es] at the
# nearest enemy at a fixed 3.0 attack speed" for 4 seconds (cached W
# description): 12 shots at a 1/3s cadence.  The leg on-hit reads the
# cached Per-Level Scaling (% AD) and Max Health Damage (%) rows.
# ROOTED IN THE BINARY: UrgotW.Duration and WAttacksPerSecond; the
# shot count is the rate times the window (12), the cadence its
# reciprocal (1/3s) — the cached description corroborates all three.
_URGOT_W_SPELL = spell_object("Urgot", "UrgotW")
_W_DURATION = data_value(_URGOT_W_SPELL, "Duration")
_W_ATTACKS_PER_SECOND = data_value(_URGOT_W_SPELL, "WAttacksPerSecond")
_W_SHOTS = int(_W_DURATION * _W_ATTACKS_PER_SECOND)
_W_TICK_INTERVAL = 1.0 / _W_ATTACKS_PER_SECOND


@ranked_slot
def _purge(ctx: SlotCtx, ability: dict[str, Any], rank: int) -> dict[str, Any] | None:
    """W: 12 sourced shots at the fixed 3.0 attack speed over 4 seconds."""

    per_shot = extract_named(
        ability, "Modified Physical Damage", rank, ctx.stats, ctx.target
    )
    entry = damage_entry(
        ability_name(ability),
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
    ad = float(ctx.stat("attack_damage") or 0.0)
    target_max = float(ctx.target_stat("target_max_health") or 0.0)
    return ad_percent / 100.0 * ad + max_hp_percent / 100.0 * target_max


@ranked_slot
def _fear_beyond_death(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """R: chem-drill initial damage; the sub-25% execution is a boundary."""
    value = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        value,
        "physical",
    )
    entry["parts"] = (DamagePart("physical", value),)
    # One chem-drill, one impale ("impales the first enemy champion hit").
    entry["event_order_certified"] = "single_hit"
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


# Reviewed crowd control, read from the cached kit.  Q (Corrosive Charge)
# explodes "to deal physical damage to enemies hit and slow them for 1.25
# seconds".  W (Purge) is a machine-gun attack stream with no control.  E
# (Disdain) deals its damage "knocking them aside and stunning them for 1
# second" — two immobilize kinds on one target, so the reviewed answer is
# the un-narrowed one.  R prices the chem-drill impale, which leashes the
# target "during which they are revealed and slowed by 0% : 75%"; the
# Mercy recast's suppression and post-execution fear ride the execution
# branch this row does not price.  P is an attack-stream shotgun rider.
MODULE_CC = {"Q": "slow", "W": "none", "E": "immobilize", "R": "slow", "P": "none"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Urgot",
    PACKET_SHA256,
    # One canister explosion and one dash blow per target, so each row
    # is a hit the ledger can time.
    single_hit_slots=frozenset({"Q", "E"}),
    slot_parsers={
        "P": _echoing_flames_proc,
        "W": _purge,
        "R": _fear_beyond_death,
    },
    cc_kinds=MODULE_CC,
)

OPTIONS: list[dict[str, Any]] = [
    *list(OPTIONS),
    int_option(
        "p_legs",
        1,
        minimum=0,
        maximum=6,
        label="Echoing Flames legs that fire (each shotgun leg procs once "
        "per its cooldown)",
    ),
]

ASSUMPTIONS = [
    *list(ASSUMPTIONS),
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
