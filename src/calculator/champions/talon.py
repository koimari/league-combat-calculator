"""Talon — CP10.8 packet module with the E9-1 gap fixes.

E9-1 closes the two remaining audit gaps over the CP10.8 packet:
- P (Blade's End) prices the 3-stack consume bleed.  Talon's abilities
  apply Wound stacks (max 3, 6s, refreshing); the next basic attack
  consumes them to bleed the target for the wiki's per-level total
  (80 : 303.53 based on level + 210% bonus AD), delivered as 16 ticks
  of the sourced per-tick array ("5 : 18.97 (based on level) (+
  13.125% bonus AD) physical damage every 0.125 seconds").  The bleed
  is priced once per fight from the ``passive_procs`` option (default
  1 = one 3-stack consume).
- Q's on-kill self-heal (9 : 60.41 based on level) is authored by this
  module's own ``derive_self_healing`` (the kill condition is the
  boundary the assumption below documents).

W two-hit and R are modeled.

Coverage: E (Assassin's Path) vaults terrain and deals nothing. Mobility
is an axis the engine does not have, so the slot stays out of scope.
"""

from typing import Any

from .. import healing_helpers as _healing
from ..ability_spec import DamagePart
from .inputs import champion_stat
from .engine import SlotCtx
from .healing_contract import declare_healing_rule
from .packet_module import build_packet_module
from .slotlib import find_named_leveling, sum_modifiers

# Sourced bleed cadence (wiki P): "5 : 18.97 (based on level)
# (+ 13.125% bonus AD) physical damage every 0.125 seconds" — 16 ticks
# of the per-tick array == the total array at every level (80/16 == 5,
# 303.53/16 == 18.97).  The total bleed's +210% bonus AD ratio is wiki
# prose (the JSON carries only the flat per-level arrays), pinned here
# with the source cited.
_P_BLEED_TICKS = 16
_P_BLEED_BONUS_AD_RATIO = 2.10
_P_BLEED_DURATION = 2.0  # 16 x 0.125s
_P_BLEED_TICK_INTERVAL = 0.125


def _blades_end(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: one 3-stack consume bleed per fight (``passive_procs`` option).

    Abilities apply the Wound stacks and a basic attack consumes them, so
    an ``auto_attacks_only`` window has nothing to consume however many
    procs the option asks for.
    """
    ability = ctx.ability()
    if ability is None:
        return None
    if ctx.option("auto_attacks_only"):
        return None
    count = max(0, int(ctx.option("passive_procs")))
    if count <= 0:
        return None

    total_leveling = find_named_leveling(ability, "Per-Level Scaling", 0)
    tick_leveling = find_named_leveling(ability, "Per-Level Scaling", 1)
    if total_leveling is None or tick_leveling is None:
        return None

    per_tick = sum_modifiers(tick_leveling, ctx.level, ctx.stats, ctx.target)
    per_tick += (
        _P_BLEED_BONUS_AD_RATIO / _P_BLEED_TICKS * ctx.stat("bonus_attack_damage")
    )
    total = per_tick * _P_BLEED_TICKS
    return {
        "name": ability.get("name", "Blade's End"),
        "rank": ctx.level,
        "cooldown": 0.0,
        "damage_type": "physical",
        "total_raw": total * count,
        "parts": (DamagePart("physical", per_tick, count=_P_BLEED_TICKS),),
        "proc_count": count,
        "dot_duration": _P_BLEED_DURATION,
        "dot_tick_interval": _P_BLEED_TICK_INTERVAL,
        # One sourced event per 3-stack consume: the consuming basic
        # attack lands the full per-level bleed (16 ticks at the sourced
        # 0.125s cadence are priced as the per-proc total; the tick
        # cadence metadata above keeps item burns refreshing through the
        # tail).  damage.py re-prices each event at the proc's own
        # mitigated total, so the ledger sums exactly to the row.  The
        # event is declared at the fight-window end (the engine's
        # end-of-rotation fallback this replaces) so ordering-certifying
        # the row does not move its ledger position and cannot change
        # window-order item outcomes (e.g. Shadowflame's threshold).
        "event_phase": "effect",
        "damage_events": [
            {
                "time": float(ctx.option("fight_duration_seconds") or 0.0),
                "damage_type": "physical",
                "damage": total,
                "event_precision": "phase_order",
            }
            for _ in range(count)
        ],
        "detail": (
            f"{count} 3-stack consume(s): per-tick x{_P_BLEED_TICKS} == "
            f"the wiki total bleed ({sum_modifiers(total_leveling, ctx.level):g} "
            f"+ 210% bonus AD at level {ctx.level}) over "
            f"{_P_BLEED_DURATION:g}s"
        ),
    }


PACKET_SHA256 = "7a3d30a61866ada61c6491cf4aecec11630184dd05c83eba0b177309e54647fb"


# Reviewed crowd control, read from the cached kit.  Q (Noxian Diplomacy)
# "dashes toward the target enemy, stabbing the target upon arrival to
# deal physical damage" and applies no control.  W (Rake)'s return pass is
# "dealing physical damage to enemies hit and slowing them for 1 second".
# R (Shadow Assault) "disperses a ring of blades ... that deals physical
# damage to enemies hit" and its recast converges them — no control
# either.  P's bleed is an attack-stream rider with its own authored
# events, and E (Assassin's Path) is terrain parkour with no damage.
MODULE_CC = {"Q": "none", "W": "slow", "R": "none"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Talon",
    PACKET_SHA256,
    single_hit_slots=frozenset({"Q", "W", "R"}),
    slot_parsers={
        "P": _blades_end,
    },
    cc_kinds=MODULE_CC,
)

OPTIONS = list(OPTIONS) + [
    {
        "key": "passive_procs",
        "type": "int",
        "default": 1,
        "min": 0,
        "max": 10,
        "label": "Blade's End 3-stack consumes",
    },
]

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "P (Blade's End) prices one 3-stack consume per fight (the "
    "passive_procs option): abilities apply Wound stacks (max 3, 6s, "
    "refreshing); the next basic attack consumes them to bleed the "
    "target for the per-level total (80 : 303.53 based on level + 210% "
    "bonus AD — the ratio is wiki prose, module constant), as 16 ticks "
    "of the sourced per-tick array every 0.125 seconds.  The "
    "consuming basic attack's own swing is not a separate damage "
    "event.",
    "An autos-only fight bleeds nothing (the pipeline states this with "
    "the auto_attacks_only reserved option): the cached P text sources "
    "stacking to \"Talon's abilities apply a stack of Wound... refreshing "
    'on basic attacks", so the consuming swing has no stacks to consume '
    "when no ability was cast.",
    "Q's on-kill self-heal (9 : 60.41 based on level) is authored by "
    "this module's derive_self_healing; the fight model prices it once "
    "per Q cast because the outgoing ledger cannot identify the "
    "killing blow.",
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"P", "Q", "W", "R"} else "out_of_scope")
    for slot in "PQWER"
}


# pylint: disable=protected-access,too-many-arguments,too-many-locals,too-many-positional-arguments,unused-argument
def derive_self_healing(
    champion_data,
    champion_stats,
    ability_damages,
    damage_events,
    cast_timeline=None,
    fight_duration_seconds=None,
):
    """Resolve Talon self-healing events from its authored packet."""
    healing = []
    level = max(1, int(champion_stat(champion_stats, "level")))
    heal = _healing._leveling_value(
        _healing._ability(champion_data, "Q"), "Heal", level
    )
    for payment in _healing._payments(
        _healing.HealAnchor.CAST, "Q", damage_events, cast_timeline
    ):
        event = payment.event
        _healing._heal_from_damage(healing, event, heal, "Noxian Diplomacy")
    return sorted(healing, key=lambda event: (event["time"], event["source"]))


SELF_HEALING_RULE = declare_healing_rule("Talon", derive_self_healing)
