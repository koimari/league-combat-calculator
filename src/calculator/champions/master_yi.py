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

from .engine import ONHIT, SlotCtx, build_parser
from .reviewed_batch_04 import build_batch_module
from .slotlib import ability_on_hit_entry, damage_entry, extract_cooldown

_packet_parse, _packet_slots, _packet_assumptions, _packet_sources, _packet_options = (
    build_batch_module("Master Yi")
)

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
    ad = ctx.stats.get("attack_damage", 0.0)
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


SLOTS = dict(_packet_slots)
SLOTS["P"] = _double_strike
SLOTS["W"] = _meditate
parse_abilities = build_parser(SLOTS, "Master Yi")

OPTIONS = list(_packet_options)
ASSUMPTIONS = list(_packet_assumptions) + [
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
SOURCES = list(_packet_sources)
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"P", "Q", "W", "E"} else "out_of_scope")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
