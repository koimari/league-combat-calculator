"""Swain — CP10.8 full-entry-reviewed packet module.

Row-selection fix (Q): Death's Hand "unleashes five bolts of eldritch
power over 0.264 seconds ... Subsequent bolts against an enemy deal 25%
bonus damage".  The generated packet priced the cached per-bolt "Magic
Damage" row (60/90/120/150/180 + 45% AP); the single-target total the
cache computes for the whole cast is "Total Damage"
(120/180/240/300/360 + 90% AP) — the first bolt at 100% plus four at the
25% "Bonus Damage Per Bolt" row, exactly twice the per-bolt row at every
rank.  Five bolts is not one hit, so Q declares its aggregate at the cast
boundary instead of certifying a single hit; the 0.264-second bolt
cadence is left for the timing wave.

R (variant 0, Demonic Ascension) still prices ONE 0.5-second drain tick
for a whole channel on a 120-second cooldown.  The cache carries no total
for it — the channel's length is a Demonic Energy economy (50 energy,
-5 per 0.5s and -7.5 after five seconds, +10 per 0.5s while draining a
champion) — so pricing it needs a modeled duration, not another row.
"""

from dataclasses import replace
from typing import Any

from .engine import SlotCtx, build_parser
from .module_helpers import typed_damage
from .packet_module import build_packet_module

PACKET_SHA256 = "65d9e8cd0840ba7f346dd7faad26a485494c4825f438be91e63491b17ecc5169"


def _deaths_hand(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: all five bolts against one enemy, declared at the cast."""
    return typed_damage(ctx, "Total Damage", "magic", time_offset=0.0)


_packet_parse, _packet_slots, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Swain",
    PACKET_SHA256,
    # Each of these packets prices one blow: W the single delayed
    # explosion, E the single detonation, and R either one drain tick or
    # the one Demonflare nova.  Q prices five bolts and declares their
    # aggregate at the cast instead.
    single_hit_slots=frozenset({"W", "E", "R"}),
    slot_parsers={"Q": _deaths_hand},
    assumption_overrides=(
        "Q (Death's Hand) prices the single-target total of all five "
        "bolts — the cached Total Damage row (120/180/240/300/360 + 90% "
        "AP), which is the per-bolt Magic Damage row plus four "
        "subsequent bolts at the 25% Bonus Damage Per Bolt row.  The "
        "generated packet priced one bolt.  The 0.264-second cadence "
        "across the five bolts is not authored.",
        "R variant 0 (Demonic Ascension) prices ONE 0.5-second drain "
        "tick.  The cache lists no total for the channel, whose length "
        "is set by the Demonic Energy economy, so the whole-channel "
        "price is withheld rather than guessed.",
    ),
)
PACKET_SPEC = _packet_slots.packet_spec

# Reviewed crowd control, read from the cached kit.  Q (Death's Hand)
# "deal[s] magic damage to enemies hit" with no control clause.  W (Vision
# of Empire) explodes "dealing magic damage to enemies within ... and
# slowing them by 50% for 1.5 seconds".  E (Nevermove) "detonates upon the
# first enemy hit, dealing magic damage to nearby enemies and rooting them
# for 1.5 seconds".  R is variant-dependent and is authored on its parts
# below, because the two casts under that one slot answer differently.
MODULE_CC = {"Q": "none", "W": "slow", "E": "root"}

# Demonic Ascension "drains the lifeforce of nearby enemies, both dealing
# magic damage and healing himself every 0.5 seconds" — no control.
# Demonflare "deals magic damage to nearby enemies and slows them by 50%".
_R_VARIANT_CC = ("none", "slow")


def _ravenous_flock_ultimate(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: the selected variant's packet, carrying that variant's own cc."""
    entry = _packet_slots["R"](ctx)
    if entry is None:
        return None
    try:
        index = int(ctx.option("r_variant"))
    except (TypeError, ValueError):
        index = 0
    kind = _R_VARIANT_CC[min(max(index, 0), len(_R_VARIANT_CC) - 1)]
    entry["parts"] = tuple(
        part if part.cc_kind is not None else replace(part, cc_kind=kind)
        for part in entry.get("parts") or ()
    )
    return entry


_ravenous_flock_ultimate.phase = getattr(_packet_slots["R"], "phase", "damage")

SLOTS = dict(_packet_slots)
SLOTS["R"] = _ravenous_flock_ultimate
parse_abilities = build_parser(SLOTS, "Swain", cc_kinds=MODULE_CC)

MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "E", "R"} else "out_of_scope")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"

from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Swain")
