"""Rell — CP10.6 full-entry-reviewed packet module.

E2 DoT fix: R (Magnet Storm) prices 8 sourced 0.25s ticks
(this module's packet timing declaration).

P1-2 fixes:
- P (Break the Mold) is now an ONHIT slot: each basic attack deals
  bonus magic damage equal to 5% of Rell's total armor plus 5% of her
  total magic resistance (wiki P prose — the JSON carries only the
  minimum-reduction leveling row, so the ratios are module constants).
- W (Ferromancy: Crash Down) shield: the support scanner now targets
  Rell herself (its self-target marker list was missing the
  description's "granting herself" phrasing), emitting the sourced
  Shield Strength (20 : 100 by rank + 11% maximum health).
- E (Full Tilt) coverage flag: the packet manifest carries E as a
  formula slot and the module prices it (Bonus Magic Damage 5% : 7% by
  rank of the target's maximum health + 3% per 100 AP); MODULE_COVERAGE
  now marks it modeled (it previously said out_of_scope — inconsistent).
"""

from typing import Any

from .packet_module import build_packet_module
from .engine import ONHIT, SlotCtx, build_parser
from .slotlib import on_hit_entry

# HARDCODED: verify on patch updates — Break the Mold's on-hit formula
# ("5% of her total armor and 5% of her total magic resistance") is wiki
# P prose; the cached JSON carries no leveling row for it (only the
# minimum-resistance-reduction row, which is the debuff floor).
_BREAK_THE_MOLD_ARMOR_RATIO = 0.05
_BREAK_THE_MOLD_MR_RATIO = 0.05

PACKET_SHA256 = "c88088e022b4afb695def1471bb4068ad40512c06c50d5a43cd479eebd11445a"

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Rell",
    PACKET_SHA256,
    packet_tick_fixes={
        "Magnet Storm": {
            "count": 8,
            "first_tick": 0.25,
            "tick_interval": 0.25,
            "dot_duration": 2.0,
        }
    },
)
PACKET_SPEC = SLOTS.packet_spec
VARIANT_OPTION_KEYS = ("w_variant",)


def _break_the_mold(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: on-hit bonus magic damage from Rell's own resistances."""
    ability = ctx.ability("P", 0)
    if ability is None:
        return None
    armor = float(ctx.stats.get("armor", 0.0))
    magic_resistance = float(ctx.stats.get("magic_resistance", 0.0))
    per_hit = (
        _BREAK_THE_MOLD_ARMOR_RATIO * armor
        + _BREAK_THE_MOLD_MR_RATIO * magic_resistance
    )
    return on_hit_entry(ability.get("name", "Break the Mold"), per_hit, "magic")


_break_the_mold.phase = ONHIT

SLOTS = dict(SLOTS)
SLOTS["P"] = _break_the_mold
parse_abilities = build_parser(SLOTS, "Rell")

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "P (Break the Mold) deals 5% of Rell's total armor + 5% of her total "
    "magic resistance as bonus magic damage on-hit (wiki prose; module "
    "constants). The 3%-per-stack armor/MR reduction (5 stacks max, 5s "
    "window) is a debuff ramp the single-target damage model does not "
    "stage; the on-hit damage itself is priced.",
    "W (Ferromancy: Crash Down) grants Rell the sourced Shield Strength "
    "(20 : 100 by rank + 11% maximum health), emitted as a self shield by "
    "the ally-support scanner.",
    "E (Full Tilt) is modeled: Bonus Magic Damage 5% : 7% by rank of the "
    "target's maximum health + 3% per 100 AP on the empowered basic "
    "attack or Shattering Strike.",
]
MODULE_COVERAGE = {slot: "modeled" for slot in "PQWER"}
REVIEW_STATUS = "reviewed_module"
