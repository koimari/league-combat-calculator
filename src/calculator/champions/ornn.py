"""Ornn's authored multi-hit combat timeline.

Roadmap session 4 batch E (2026-08-21): P (Living Forge) grants
item-upgrade/anvil-drop state with no enemy-damage formula — pure
item/state system, already noted in ASSUMPTIONS below. The pinned
reviewed packet (static/reviewed-packets.json) independently declares P
``kind: "no_damage"`` with a sourced reason ("no enemy-damage formula is
listed for this slot"). P is not a cast slot in this custom module's
SLOTS map (unlike the packet-module champions in this batch, Ornn's
SLOTS dict was authored directly and never wired P at all), so this is
a documentation-only reclassification with zero fight-computation
change — the Malzahar precedent from roadmap session 4 batch D, where a
non-cast P slot was corrected from "out_of_scope" to "no_damage" on the
same sourced-evidence basis.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .slotlib import damage_entry, extract_cooldown, extract_named, simple_damage


def _bellows_breath(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability("W")
    if ability is None:
        return None
    rank = ctx.rank_for("W")
    if rank < 1:
        return None
    per_tick = extract_named(
        ability, "Magic Damage Per Tick", rank, ctx.stats, ctx.target
    )
    total = per_tick * 5
    entry = damage_entry(
        ability.get("name", "Bellows Breath"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    entry["parts"] = (
        DamagePart("magic", per_tick, count=5, time_offset=0.0, hit_interval=0.15),
    )
    entry["detail"] = "five sourced 0.15-second fire ticks; final gout applies Brittle"
    return entry


def _call_of_the_forge_god(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability("R")
    if ability is None:
        return None
    rank = ctx.rank_for("R")
    if rank < 1:
        return None
    passes = min(max(int(ctx.options.get("r_passes", 2)), 1), 2)
    attr = "Total Magic Damage" if passes == 2 else "Magic Damage"
    total = extract_named(ability, attr, rank, ctx.stats, ctx.target)
    per_pass = total / passes
    entry = damage_entry(
        ability.get("name", "Call of the Forge God"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    entry["parts"] = (
        DamagePart(
            "magic",
            per_pass,
            count=passes,
            time_offset=0.0,
            hit_interval=1.25 if passes > 1 else None,
        ),
    )
    entry["detail"] = f"{passes} elemental pass(es); each pass applies Brittle"
    return entry


SLOTS = {
    "Q": simple_damage(attr="Physical Damage", dmg_type="physical"),
    "W": _bellows_breath,
    "E": simple_damage(attr="Physical Damage", dmg_type="physical"),
    "R": _call_of_the_forge_god,
}

parse_abilities = build_parser(SLOTS, "Ornn")

OPTIONS = [
    {
        "key": "r_passes",
        "type": "int",
        "default": 2,
        "min": 1,
        "max": 2,
        "label": "R elemental passes",
    }
]

ASSUMPTIONS = [
    "Bellows Breath uses five sourced 0.15-second ticks and exposes the final-gout Brittle state in its detail receipt.",
    "Call of the Forge God defaults to both sourced passes; one pass is available as an explicit option.",
    "Living Forge and Master Craftsman are item/state systems, not direct enemy damage.",
    "P (Living Forge) has no enemy-damage formula (confirmed by the pinned "
    "reviewed packet's kind='no_damage' declaration for P); it is not a "
    "cast slot in this module's SLOTS map, so MODULE_COVERAGE reflects a "
    "sourced no-damage classification rather than an unmodeled gap "
    "(no_damage, not out_of_scope).",
]

SOURCES = [
    {
        "label": "Ornn — full champion entry",
        "url": "https://wiki.leagueoflegends.com/en-us/Ornn",
        "revision_id": 4012186,
        "revision_timestamp": "2026-04-25T08:28:03Z",
    }
]


# Authoritative review metadata (issue #161).
MODULE_COVERAGE = {
    slot: (
        "modeled" if slot in SLOTS else ("no_damage" if slot == "P" else "out_of_scope")
    )
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
