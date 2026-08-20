"""LeBlanc — full-entry reviewed CP10.3 module.

Option keys consumed by the shared parser: "q_consume", "e_chain_complete", "r_mimic".
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .module_helpers import REVIEWED_MODULE_ASSUMPTIONS, no_damage, typed_damage
from .slotlib import extract_cooldown, extract_named, simple_damage
from .source_receipts import load_champion_sources


def _sigil_of_malice(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    attribute = (
        "Total Magic Damage"
        if bool(ctx.options.get("q_consume", True))
        else "Magic Damage"
    )
    value = extract_named(ability, attribute, rank, ctx.stats, ctx.target)
    return {
        "name": ability.get("name", "Sigil of Malice"),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "magic",
        "total_raw": value,
        "parts": (DamagePart("magic", value),),
        "detail": (
            "Sigil orb plus optional mark consumption are one explicitly "
            "ordered target sequence."
        ),
    }


def _ethereal_chains(ctx: SlotCtx) -> dict[str, Any] | None:
    attribute = (
        "Total Damage"
        if bool(ctx.options.get("e_chain_complete", True))
        else "Magic Damage"
    )
    result = typed_damage(ctx, attribute, "magic")
    if result:
        result["detail"] = (
            "Ethereal Chains application and fracture are included only when "
            "the tether completes."
        )
    return result


def _mimic(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    choice = str(ctx.options.get("r_mimic", "Q"))
    attribute = {
        "Q": "Total Magic Damage",
        "W": "Magic Damage",
        "E": "Total Magic Damage",
    }.get(choice, "Total Magic Damage")
    value = extract_named(ability, attribute, rank, ctx.stats, ctx.target)
    return {
        "name": ability.get("name", "Mimic"),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "magic",
        "total_raw": value,
        # Mimic's reviewed control is the copied ability's, so it is
        # authored here rather than declared for the slot.  Sigil of Malice
        # and Distortion control nothing; the Ethereal Chains variant
        # prices the application and the fracture together and only the
        # fracture roots, so that variant is left unreviewed.
        "parts": (
            DamagePart(
                "magic",
                value,
                time_offset=0.2,
                cc_kind=None if choice == "E" else "none",
            ),
        ),
        "detail": (
            f"Mimic variant {choice}; copied basic-ability effects remain in "
            "the explicit variant choice."
        ),
    }


SLOTS = {
    "P": lambda ctx: no_damage(
        ctx,
        name="Mirror Image",
        reason=(
            "Clone spawning, invisibility and pet movement are state; the "
            "clone's basic attacks deal no damage."
        ),
    ),
    "Q": _sigil_of_malice,
    # One arrival ("dealing magic damage to all nearby enemies upon
    # arrival") — one part and one hit, which carries W's reviewed answer
    # into the event ledger.
    "W": simple_damage(
        attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
    ),
    "E": _ethereal_chains,
    "R": _mimic,
}
OPTIONS = [
    {
        "key": "q_consume",
        "type": "bool",
        "default": True,
        "label": "Sigil mark is consumed",
    },
    {
        "key": "e_chain_complete",
        "type": "bool",
        "default": True,
        "label": "Ethereal Chains completes",
    },
    {
        "key": "r_mimic",
        "type": "select",
        "default": "Q",
        "label": "Mimic variant",
        "choices": [
            {"value": "Q", "label": "Mimic Q"},
            {"value": "W", "label": "Mimic W"},
            {"value": "E", "label": "Mimic E"},
        ],
    },
]
ASSUMPTIONS = list(REVIEWED_MODULE_ASSUMPTIONS)
SOURCES = load_champion_sources("LeBlanc")
# Reviewed crowd control, read from the cached kit.  W (Distortion)
# "deal[s] magic damage to all nearby enemies upon arrival" with no
# control clause.  R (Mimic) copies a basic ability, so its answer is the
# copied ability's and is authored on the part (see ``_mimic``).  P
# authors no damage part.
#
# Q and E stay UNREVIEWED, so this kit keeps the coarse control-armed
# scan.  Sigil of Malice controls nothing, but its row is the orb plus the
# mark's consumption — two hits in one part.  Ethereal Chains does root,
# but only at the fracture ("if the tether is not broken by the end of its
# duration, it fractures to deal magic damage to the target and root them
# for 1.5 seconds"), and its row is the application and the fracture
# summed, two hits that do not control alike.
MODULE_CC = {"W": "none"}

parse_abilities = build_parser(SLOTS, "LeBlanc", cc_kinds=MODULE_CC)

MODULE_COVERAGE = {
    slot: ("modeled" if slot != "P" else "no_damage") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
