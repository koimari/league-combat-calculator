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
from .slotlib import on_hit_entry, simple_damage

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
    # Shattering Strike thrusts once and both W forms land one hit — the
    # crash-down impact and the mounted charge's empowered attack — which
    # is the boundary claim that carries MODULE_CC's reviewed answers into
    # the event ledger.  R already authors its own eight-tick timing above.
    single_hit_slots=frozenset({"Q", "W"}),
)
PACKET_SPEC = SLOTS.packet_spec


def _break_the_mold(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: on-hit bonus magic damage from Rell's own resistances."""
    ability = ctx.ability("P", 0)
    if ability is None:
        return None
    armor = float(ctx.stat("armor"))
    magic_resistance = float(ctx.stat("magic_resistance"))
    per_hit = (
        _BREAK_THE_MOLD_ARMOR_RATIO * armor
        + _BREAK_THE_MOLD_MR_RATIO * magic_resistance
    )
    return on_hit_entry(ability.get("name", "Break the Mold"), per_hit, "magic")


_break_the_mold.phase = ONHIT

SLOTS = dict(SLOTS)
SLOTS["P"] = _break_the_mold
# E's explosion lands once on the target, so it certifies the cast
# boundary its reviewed answer rides on.  The parser is rebuilt from the
# pinned packet's own evidence rather than restating the attribute here.
_E_SPEC = PACKET_SPEC["slots"]["E"]
SLOTS["E"] = simple_damage(
    attr=str(_E_SPEC["attribute"]),
    dmg_type=str(_E_SPEC.get("damage_type", "auto")),
    ranks=str(_E_SPEC.get("ranks", "rank")),
    source=tuple(_E_SPEC["source"]) if _E_SPEC.get("source") else None,
    event_order_certified="single_hit",
)

# Cached kit review.  Q "deal[s] them magic damage and stun[s] them for
# 0.65 seconds"; its "immobilized" wording is about Rell failing to lunge,
# not control she applies.  Both W forms apply two immobilize kinds at
# once, which is what the un-narrowed "immobilize" states: Crash Down
# "deals magic damage to nearby enemies, stuns them for 0.8 seconds, and
# knocks them up for 0.4 seconds", and Mount Up's charge "deals bonus
# magic damage, stuns the target for 0.6 seconds, and flings them 150
# units over herself".  E only "deals bonus magic damage" through the
# explosion it creates.  R's field "deals magic damage every 0.25 seconds
# to nearby enemies and drags them towards her".  P is an on-hit rider on
# the auto stream, so it carries no ability event of its own.
MODULE_CC = {"Q": "stun", "W": "immobilize", "E": "none", "R": "pull"}

parse_abilities = build_parser(SLOTS, "Rell", cc_kinds=MODULE_CC)

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
