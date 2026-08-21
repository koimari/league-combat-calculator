"""Xerath — CP10.10 full-entry-reviewed packet module, plus the E9-3 R fix.

E9-3: Rite of the Arcane (R) is a multi-recast channel.  The reviewed
packet priced ONE Arcane Barrage ("Magic Damage" per-shot row); the
cached JSON carries "Number of Recasts" (4/5/6) and "Total Magic
Damage" (680/1100/1620 + 180/225/270% AP == per-shot x recasts).  The
module now prices all recasts at the sourced 0.627-second cadence, and
the E3-stacks worklist entry (Arcane Perfection: "Maximum Stacks" 3/4/5
and "Increased Damage per Stack" 20/25/30 + 5% AP) is modeled through
the ``r_arcane_perfection`` option — each barrage beyond the first
carries the accumulated per-stack bonus (capped at the sourced Maximum
Stacks), 0 by default so the unoptioned price is the sourced Total row.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .packet_module import build_packet_module
from .slotlib import damage_entry, extract_cooldown, extract_named

PACKET_SHA256 = "3bd191171432197d87f1d33ec2ab9bf3f483d15f73f892c373a32c249fd764db"

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Xerath", PACKET_SHA256
)
PACKET_SPEC = SLOTS.packet_spec

# HARDCODED: verify on patch updates — the 0.627-second barrage cadence is
# prose in the cached R description ("Each cast has a static cooldown of
# 0.627 seconds"); the recast count, per-shot damage, stacks, and
# per-stack bonus are cached leveling rows read live.
_R_BARRAGE_INTERVAL_SECONDS = 0.627


def _rite_of_the_arcane(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: every Arcane Barrage of the channel, plus Arcane Perfection stacks."""
    ability = ctx.ability("R")
    if ability is None:
        return None
    rank = ctx.rank_for("R")
    if rank < 1:
        return None
    recasts = int(round(extract_named(ability, "Number of Recasts", rank)))
    per_shot = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    stacks = min(max(int(ctx.options.get("r_arcane_perfection", 0)), 0), 6)
    if stacks > 0:
        maximum_stacks = int(round(extract_named(ability, "Maximum Stacks", rank)))
        per_stack = extract_named(
            ability, "Increased Damage per Stack", rank, ctx.stats, ctx.target
        )
        parts = []
        total = 0.0
        for index in range(recasts):
            shot_stacks = min(index, stacks, maximum_stacks)
            amount = per_shot + shot_stacks * per_stack
            parts.append(
                DamagePart(
                    "magic",
                    amount,
                    time_offset=_R_BARRAGE_INTERVAL_SECONDS * (index + 1),
                )
            )
            total += amount
        entry = damage_entry(
            ability.get("name", "Rite of the Arcane"),
            rank,
            extract_cooldown(ability, rank),
            total,
            "magic",
        )
        entry["parts"] = tuple(parts)
        entry["detail"] = (
            f"{recasts} Arcane Barrages at the sourced 0.627s cadence with "
            f"{stacks} Arcane Perfection stack(s) (per-stack bonus capped "
            f"at the sourced {maximum_stacks}); all barrages land on the "
            "single duel target"
        )
        return entry
    total = per_shot * recasts
    entry = damage_entry(
        ability.get("name", "Rite of the Arcane"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    entry["parts"] = (
        DamagePart(
            "magic",
            per_shot,
            count=recasts,
            time_offset=_R_BARRAGE_INTERVAL_SECONDS,
            hit_interval=_R_BARRAGE_INTERVAL_SECONDS,
        ),
    )
    entry["detail"] = (
        f"{recasts} Arcane Barrages x {per_shot:.2f} == Total Magic Damage "
        f"{total:.2f} at rank {rank} (0.627s cadence)"
    )
    return entry


SLOTS = dict(SLOTS)
SLOTS["R"] = _rite_of_the_arcane
parse_abilities = build_parser(SLOTS, "Xerath")

OPTIONS = list(OPTIONS) + [
    {
        "key": "r_arcane_perfection",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 6,
        "label": "Arcane Perfection stacks (R barrage bonus)",
    },
]

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "R (Rite of the Arcane) prices every Arcane Barrage: 'Number of "
    "Recasts' (4/5/6) x 'Magic Damage' per shot == the cached 'Total "
    "Magic Damage' row (680/1100/1620 + 180/225/270% AP) at the sourced "
    "0.627-second cadence.",
    "Arcane Perfection (the E3-stacks worklist entry) is option-gated: "
    "r_arcane_perfection stacks add 'Increased Damage per Stack' "
    "(20/25/30 + 5% AP) to every barrage beyond the first, capped at the "
    "sourced 'Maximum Stacks' (3/4/5); 0 (default) prices the sourced "
    "Total row.",
    "Every barrage is assumed to hit the single duel target (a champion "
    "duel); the 0.5s-first-recast window and the 10s channel are state.",
    "P (Mana Surge) has no enemy-damage formula: its cached effects are "
    "a self mana-restore-on-next-auto-attack proc and a kill-triggered "
    "cooldown reduction, with no enemy-damage leveling row (confirmed by "
    "the pinned reviewed packet's kind='no_damage' declaration for P, "
    "and live: parse_champion_abilities emits P as a zero total_raw row "
    "absent from the fight breakdown). P is a cast slot in this module "
    "(never reassigned away from build_packet_module's no_damage "
    "branch — only R is overridden above), so MODULE_COVERAGE reflects "
    "a sourced no-damage classification rather than an unmodeled gap "
    "(no_damage, not out_of_scope).",
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "E", "R"} else "no_damage")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
