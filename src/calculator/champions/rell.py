"""Rell — CP10.6 full-entry-reviewed packet module.

E2 DoT fix: R (Magnet Storm) prices 8 sourced 0.25s ticks
(this module's packet timing declaration).

P1-2 fixes:
- P (Break the Mold) is now an ONHIT slot: each basic attack deals
  bonus magic damage equal to 5% of Rell's total armor plus 5% of her
  total magic resistance (the ordered pair is rooted in the binary's
  OnHitDamage calculation).
- W (Ferromancy: Crash Down) shield: the support scanner now targets
  Rell herself (its self-target marker list was missing the
  description's "granting herself" phrasing), emitting the sourced
  Shield Strength (20 : 100 by rank + 11% maximum health).
- E (Full Tilt) coverage flag: the packet manifest carries E as a
  formula slot and the module prices it (Bonus Magic Damage 5% : 7% by
  rank of the target's maximum health + 3% per 100 AP); MODULE_COVERAGE
  marks it modeled.
"""

from typing import Any

from ..binary_roots import calculation_coefficients, spell_object
from .engine import ONHIT, SlotCtx
from .packet_module import build_packet_module
from .slotlib import ability_name, on_hit_entry

# Break the Mold's on-hit formula is the ordered armor/MR pair in the
# binary's RellP.OnHitDamage calculation.
_RELL_P_SPELL = spell_object("Rell", "RellP")
(
    _BREAK_THE_MOLD_ARMOR_RATIO,
    _BREAK_THE_MOLD_MR_RATIO,
) = calculation_coefficients(_RELL_P_SPELL, "OnHitDamage")

PACKET_SHA256 = "c88088e022b4afb695def1471bb4068ad40512c06c50d5a43cd479eebd11445a"


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
    return on_hit_entry(ability_name(ability), per_hit, "magic")


_break_the_mold.phase = ONHIT


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
    # the event ledger; E's explosion lands once on the target.  R already
    # authors its own eight-tick timing above.
    single_hit_slots=frozenset({"Q", "W", "E"}),
    slot_parsers={
        "P": _break_the_mold,
    },
    cc_kinds=MODULE_CC,
)

ASSUMPTIONS = [
    *list(ASSUMPTIONS),
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
