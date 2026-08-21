"""Milio — CP10.4 full-entry-reviewed packet module.

E2 DoT fix: W (Cozy Campfire) heals 25 sourced ticks (Heal per Tick x25 ==
Total Heal) via the heal rule in src/calculator/healing.py.

E8d ally-support: W (Cozy Campfire, Total Heal 70-150 + 15% AP, scope
one_teammate) and R (Breath of Life, Heal 150-350 + 50% AP, scope
self_and_all_teammates) heal allies, and E (Warm Hugs, Shield Strength
45-165 + 45% AP, scope one_teammate) shields one.  The events are authored by
the engine's ally-support scanner from cached leveling at the cast times (R's
by the healing rule, fanned out to allies by the participant timeline); the
module declares W/E/R in SLOTS so the fight rotation casts them.
"""

from typing import Any

from .engine import ONHIT, SlotCtx
from .healing_contract import declare_healing_rule
from .packet_module import build_packet_module
from .slotlib import extract_named, on_hit_entry

PACKET_SHA256 = "fce2851d13e50c61a320c2195e1618e540b56a81742d3e44cfaa4a0ffe2c163f"

# "Cozy Campfire may grant Fired Up! upon being summoned and at most once
# every 3 seconds thereafter" — one enchantment per cast is the default.
_FIRED_UP_PROCS_PER_CAST = 1


def _fired_up(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: the burn the enchanted hit applies.

    The AD share of the same hit ("7% / 11% / 15% (based on level) of
    enchanted target's AD") is prose with no cached row and no stated level
    breakpoints on the wiki either, so it is disclosed rather than guessed;
    the burn is the half the cache sources.
    """
    ability = ctx.ability()
    if ability is None:
        return None
    burn = extract_named(
        ability, "Per-Level Scaling", ctx.level, ctx.stats, ctx.target, level=ctx.level
    ) + 0.20 * float(ctx.stat("ability_power") or 0.0)
    if burn <= 0:
        return None
    procs = max(0, int(ctx.option("p_procs")))
    entry = on_hit_entry(ability.get("name", "Fired Up!"), burn, "magic")
    entry["on_hit"]["max_procs"] = procs
    entry["detail"] = (
        f"{procs} enchanted hit(s) applying the sourced burn {burn:.2f} "
        "(10 : 50 based on level + 20% of Milio's AP over 1.5s, priced at "
        "the hit); the 7% / 11% / 15% of the enchanted target's AD on the "
        "same hit has no cached row and no sourced level breakpoints"
    )
    return entry


_fired_up.phase = ONHIT

# Cached kit review: Q "knocks back and stuns the first enemy it hits over
# 1 second" — the enemy the bounced explosion this packet prices then
# damages (and slows).  W, E and R are ally heals/shields and P is an
# enchantment on allies, so no other slot emits an enemy damage event.
MODULE_CC = {"Q": "stun"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Milio",
    PACKET_SHA256,
    # The explosion deals its packet once, at the cast (the fireball's
    # own 0.25-second delay is Milio's cast lockout, not a hit offset) —
    # the boundary claim that carries MODULE_CC into the event ledger.
    single_hit_slots=frozenset({"Q"}),
    slot_parsers={"P": _fired_up},
    cc_kinds=MODULE_CC,
)

OPTIONS = list(OPTIONS) + [
    {
        "key": "p_procs",
        "type": "int",
        "default": _FIRED_UP_PROCS_PER_CAST,
        "min": 0,
        "max": 10,
        "label": "Fired Up! hits landed",
    },
]

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "P (Fired Up!) prices the sourced burn the enchanted hit applies "
    "(10 : 50 based on level + 20% of Milio's AP, priced at the hit rather "
    "than over its six 0.25s ticks) once per cast (selectable); the "
    "7% / 11% / 15% of the enchanted target's AD on the same hit has no "
    "cached leveling row and no sourced level breakpoints, so it is "
    "disclosed rather than guessed.",
]
SELF_HEALING_RULE = declare_healing_rule("Milio")
