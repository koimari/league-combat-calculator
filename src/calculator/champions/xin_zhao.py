"""Xin Zhao — CP10.10 full-entry-reviewed packet module.

Row-selection fix.  The generated packet picked, for both Q and W, a
single-instance row where the cached entry also carries the Total the
wiki computes for one cast, so this module reads the Total instead:

- Q (Three Talon Strike) "empowers his next three basic attacks ... to
  each have an uncancellable windup, deal bonus physical damage".  The
  packet priced "Bonus Physical Damage" (15/30/45/60/75 + 40% bonus AD),
  one of the three; the cache's "Total Bonus Physical Damage" row is
  45/90/135/180/225 + 120% bonus AD — exactly three of them.
- W (Wind Becomes Lightning) "unleashes 4 slashes ... each dealing
  physical damage ... he then thrusts his spear in a line ... dealing
  physical damage".  The packet priced "Physical Damage per Slash"
  (7.5/10/12.5/15/17.5 + 7.5% AD), one slash of four and no thrust; the
  cache's "Total Physical Damage" row is 80/125/170/215/260 + 120% AD
  + 65% AP == "Slash Total Physical Damage" + "Thrust Physical Damage".

Each row is now several hits, so neither certifies a cast-boundary single
hit.  W declares its one aggregate hit at the cast so its reviewed slow
still reaches the event ledger; the slashes' sourced cadence ("over the
first 0.15 seconds of the cast time") and the thrust's offset behind the
remaining cast time are left for the timing wave.
"""

from typing import Any

from .engine import SlotCtx
from .module_helpers import typed_damage
from .packet_module import build_packet_module
from .slotlib import simple_damage

PACKET_SHA256 = "c39efd0eac006d4b59799a0b3c5de44ef6ec31f9f9a23bea7ab8a25d2f4ccf64"


def _wind_becomes_lightning(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: the whole cast — four slashes plus the thrust — at the cast."""
    return typed_damage(ctx, "Total Physical Damage", "physical", time_offset=0.0)


# Wind Becomes Lightning ends in a thrust "dealing physical damage to
# enemies hit ... and slowing them by 50%" — the cast slows the target it
# damages, and now that W prices the whole cast (four slashes plus that
# thrust) the reviewed kind covers every hit the row contains.  Audacious
# Charge "slow[s] all targets hit by 30% for 0.5 seconds".  Crescent
# Guard's knockback and stun reach only "targets hit that are not
# Challenged", and its own passive marks the duel target — "Xin Zhao's
# basic attacks and Audacious Charge apply the Challenged mark to enemy
# champions hit" — so the one enemy this module prices is never displaced
# by it.
#
# Q stays UNREVIEWED, so this kit keeps the coarse control-armed scan.
# Its row is now all three empowered attacks, but only "the third attack
# knocks up the target" — one of three, and no slot-wide answer covers a
# row whose hits differ (the Annie Pyromania rule).
MODULE_CC = {"W": "slow", "E": "slow", "R": "none"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Xin Zhao",
    PACKET_SHA256,
    # E's arrival and R's sweep are one hit each at the cast.  W is no
    # longer among them: its row is four slashes plus a thrust, declared
    # at the cast boundary by ``_wind_becomes_lightning``.
    single_hit_slots=frozenset({"E", "R"}),
    slot_parsers={
        "Q": simple_damage(
            attr="Total Bonus Physical Damage",
            dmg_type="physical",
        ),
        "W": _wind_becomes_lightning,
    },
    assumption_overrides=(
        "Q (Three Talon Strike) prices all three empowered attacks — the "
        "cached Total Bonus Physical Damage row (45/90/135/180/225 + 120% "
        "bonus AD), three times the per-attack Bonus Physical Damage row "
        "the generated packet selected.  Their spacing across the "
        "5-second window is not authored.",
        "W (Wind Becomes Lightning) prices the whole cast — the cached "
        "Total Physical Damage row (80/125/170/215/260 + 120% AD + 65% "
        "AP), which is the four slashes plus the thrust.  The generated "
        "packet priced Physical Damage per Slash, one slash of four with "
        "no thrust.  The row is declared as one aggregate hit at the cast "
        "boundary; the thrust's crit-chance increase (0% : 33.3%) and the "
        "slash cadence remain unpriced.",
    ),
    cc_kinds=MODULE_CC,
)
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "E", "R"} else "out_of_scope")
    for slot in "PQWER"
}

from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Xin Zhao")
