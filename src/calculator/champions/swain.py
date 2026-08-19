"""Swain — CP10.8 full-entry-reviewed packet module."""

from dataclasses import replace
from typing import Any

from .engine import SlotCtx, build_parser
from .packet_module import build_packet_module

PACKET_SHA256 = "65d9e8cd0840ba7f346dd7faad26a485494c4825f438be91e63491b17ecc5169"

_packet_parse, _packet_slots, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Swain",
    PACKET_SHA256,
    # Each packet prices one blow: Q the cached first-bolt "Magic Damage"
    # row, W the single delayed explosion, E the single detonation, and R
    # either one drain tick or the one Demonflare nova.
    single_hit_slots=frozenset({"Q", "W", "E", "R"}),
)
PACKET_SPEC = _packet_slots.packet_spec
VARIANT_OPTION_KEYS = ("r_variant",)

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
