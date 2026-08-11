"""Rek'Sai — CP10.6 full-entry-reviewed packet module, plus the P1 max-Fury E.

P1 addition over the reviewed packet:
- E (Furious Bite) prices the max-Fury branch: "At maximum Fury, Furious
  Bite deals 120% damage and is converted to true damage" (cached E
  second effect; the leveling row "True Damage" 84-204 + 72% bonus AD ==
  120% of the "Physical Damage" row at every rank).  Fury is player
  state, so the fight is deterministic through the ``e_fury`` option
  (0-100, default 0 = no Fury): at 100 Fury the E packet prices the
  sourced true-damage row, otherwise the reviewed physical row.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .packet_module import build_packet_module
from .slotlib import damage_entry, extract_cooldown, extract_named

PACKET_SHA256 = "004116a55524cf55d387d236bcd22e8fbad9b79deb5679fc0c2be4257d364c0a"

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Rek'Sai", PACKET_SHA256, single_hit_slots=frozenset({"R"})
)
PACKET_SPEC = SLOTS.packet_spec


def _furious_bite(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: physical bite, or the 120% true-damage variant at max Fury."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    fury = max(0, min(100, int(ctx.options.get("e_fury", 0))))
    if fury >= 100:
        value = extract_named(ability, "True Damage", rank, ctx.stats, ctx.target)
        dtype = "true"
        detail = (
            "Maximum Fury: Furious Bite deals 120% damage converted to "
            "true damage (the cached True Damage row: 84-204 + 72% bonus "
            "AD)"
        )
    else:
        value = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
        dtype = "physical"
        detail = (
            f"Fury {fury}/100: the physical bite (70-170 + 60% bonus AD); "
            "at 100 Fury the E packet prices the true-damage variant"
        )
    entry = damage_entry(
        ability.get("name", "Furious Bite"),
        rank,
        extract_cooldown(ability, rank),
        value,
        dtype,
    )
    entry["parts"] = (DamagePart(dtype, value),)
    entry["detail"] = detail
    return entry


SLOTS = dict(SLOTS)
SLOTS["E"] = _furious_bite
parse_abilities = build_parser(SLOTS, "Rek'Sai")

OPTIONS = list(OPTIONS) + [
    {
        "key": "e_fury",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 100,
        "step": 25,
        "label": (
            "Fury (0-100): at 100, Furious Bite deals 120% damage as true "
            "damage (the cached True Damage row)"
        ),
    },
]

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "E (Furious Bite) is deterministic through the e_fury option: below "
    "100 Fury it prices the physical row (70-170 + 60% bonus AD); at 100 "
    "Fury it prices the sourced true-damage variant (84-204 + 72% bonus "
    "AD == 120% of the physical row, 'converted to true damage').  Fury "
    "generation (P Fury of the Xer'Sai) and burrow CC remain documented "
    "out-of-scope",
    "P (Fury of the Xer'Sai) heals on Burrow: 'consumes her current Fury "
    "over 3 seconds to heal for 0% : 100% (based on Fury) of 9% : "
    "21.29% (based on level) maximum health' (cached P prose).  The "
    "heal is documented-only: the rotation's W slot is a damaging row, "
    "not the burrow stance switch, so the ledger has no faithful burrow "
    "trigger for the heal; the e_fury option prices E's max-Fury bite "
    "but not a burrow state.",
]

VARIANT_OPTION_KEYS = ("q_variant", "e_fury")
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "E", "R"} else "out_of_scope")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
