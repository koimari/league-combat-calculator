"""Master Yi — reviewed packet slots plus the E3 Double Strike passive.

E3 addition over the CP10.4 packet module:
- P (Double Strike) becomes an ONHIT stack slot: basic attacks on-hit
  generate a stack (up to 3); at 3 stacks the next basic attack strikes
  twice, the second strike dealing 50% AD physical damage. The fight
  engine's every-Nth-hit on-hit machinery prices it exactly like Vayne
  W (``stacks_required`` 3, autos-only): the per-proc 50%-AD strike is
  spread across the 3 stacking hits. Alpha Strike explicitly does NOT
  grant Double Strike stacks (wiki note), so ability hits never count —
  only the simulated auto stream.

P1-2 addition — W (Meditate): the module now declares W in SLOTS so the
fight rotation casts the channel; the channel's self-heal is authored
by the healing rule (``healing.derive_self_healing`` "Master Yi"
branch): 8 ticks at the sourced 0.5-second cadence over the 4-second
channel, each tick interpolated between the Minimum Heal Per Tick and
Maximum Heal Per Tick rows by the fighter's live missing health.  W's
damage-reduction window is a defensive state the damage model does not
stage.
"""

from typing import Any

from .engine import ONHIT, SlotCtx
from .packet_module import build_packet_module
from .slotlib import ability_on_hit_entry, damage_entry, extract_cooldown

PACKET_SHA256 = "a6d43d11733ede3c9a2f3daa2d2f6afb754fc83e580b27dff8e8ffeb76783164"

# Alpha Strike's priced hit is its primary damage, and the cached entry
# puts that after the whole vanish: Master Yi "reappears ... and then
# becomes able to act again[ after 0.165 seconds. ][ 1.087 seconds total
# after the start of the cast with 4 bounces. ]" with the note "Alpha
# Strike's primary damage applies after Master Yi reappears."  The cached
# number is already measured from the cast start, which is where
# ``time_offset`` starts.  The lesser marks that "detonate instantly upon
# application to deal 25% damage" are a multi-target branch this
# single-target packet does not price.
_Q_REAPPEAR_SECONDS = 1.087


# HARDCODED: verify on patch updates — Double Strike's 3-hit cadence and
# the second strike's 50% AD are wiki prose; the JSON carries no
# leveling for the passive.
_DOUBLE_STRIKE_STACKS = 3
_SECOND_STRIKE_AD_RATIO = 0.5


def _double_strike(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: every 3rd auto strikes twice — second strike 50% AD physical."""
    ability = ctx.ability()
    if ability is None:
        return None
    ad = ctx.stat("attack_damage")
    per_proc = _SECOND_STRIKE_AD_RATIO * ad
    return ability_on_hit_entry(
        ability.get("name", "Double Strike"),
        ctx.level,
        "physical",
        {
            "name": "Double Strike (second strike)",
            "damage_per_hit": per_proc / _DOUBLE_STRIKE_STACKS,
            "damage_type": "physical",
            "stacks_required": _DOUBLE_STRIKE_STACKS,
        },
    )


_double_strike.phase = ONHIT


def _meditate(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: a zero-damage channel receipt (the heal lives in healing.py)."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    entry = damage_entry(
        ability.get("name", "Meditate"),
        rank,
        extract_cooldown(ability, rank),
        0.0,
        "physical",
    )
    entry["parts"] = ()
    entry["detail"] = (
        "4-second channel: the self-heal (Minimum/Maximum Heal Per Tick, "
        "missing-health scaled) is authored by healing.py; the damage-"
        "reduction window is a defensive state not staged by the damage "
        "model"
    )
    return entry


# Reviewed crowd control, read from the cached kit.  Alpha Strike marks
# and detonates for damage and on-hit effects only — nothing in the entry
# controls the enemies it strikes (Master Yi is the one made unable to
# act).  P is an on-hit rider, W a self-channel, R a self-buff.
#
# E stays UNREVIEWED, so this kit keeps the coarse control-armed scan,
# and the reason is not timing: Wuju Style "empowers his basic attacks
# within the next 5 seconds to deal bonus true damage on-hit", but the
# reviewed packet prices it as one direct hit on the E row.  Certifying
# that hit at the cast boundary would state an instant the ability does
# not have — the rider lands on a later basic attack — so the row needs
# to move onto the on-hit stream before it can carry any marker.
MODULE_CC = {"Q": "none"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Master Yi",
    PACKET_SHA256,
    packet_part_timings={"Q": {"time_offset": _Q_REAPPEAR_SECONDS}},
    slot_parsers={
        "P": _double_strike,
        "W": _meditate,
    },
    cc_kinds=MODULE_CC,
)

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "Double Strike procs on every 3rd basic attack; the second strike "
    "deals 50% AD physical damage — wiki prose (module constants)",
    "Only basic attacks generate stacks (Alpha Strike explicitly does "
    "not; Meditate's channel stacks are not simulated)",
    "The engine prices the proc spread across the 3 stacking hits "
    "(Vayne W convention); the 4-second stack window is assumed not to "
    "expire during sustained combat",
    "W (Meditate) heals for 8 ticks at 0.5-second intervals over the "
    "4-second channel, interpolated between Minimum Heal Per Tick and "
    "Maximum Heal Per Tick by the fighter's live missing health "
    "(healing.py 'Master Yi' rule); the channel's damage reduction is "
    "a defensive state not staged by the damage model.",
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"P", "Q", "W", "E"} else "out_of_scope")
    for slot in "PQWER"
}

from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Master Yi")
