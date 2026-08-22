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

Coverage: P (Mana Surge) restores mana on his basic attacks. A resource
refund is an axis the engine does not have, so the slot is out of
scope.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx
from .packet_module import build_packet_module
from .slotlib import damage_entry, extract_cooldown, extract_named
from .inputs import int_option
from .module_contract import coverage

PACKET_SHA256 = "3bd191171432197d87f1d33ec2ab9bf3f483d15f73f892c373a32c249fd764db"

# Both basic-ability hits land 0.528 seconds after their cast: Arcanopulse's
# recast makes Xerath "unable to act for 0.528 seconds and afterwards fires
# a beam", and Eye of Destruction "strikes the target location after 0.528
# seconds" (cached Q and W prose).
_BLAST_DELAY_SECONDS = 0.528


# HARDCODED: verify on patch updates — the 0.627-second barrage cadence is
# prose in the cached R description ("Each cast has a static cooldown of
# 0.627 seconds"); the recast count, per-shot damage, stacks, and
# per-stack bonus are cached leveling rows read live.
_R_BARRAGE_INTERVAL_SECONDS = 0.627


def _rite_of_the_arcane(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: every Arcane Barrage of the channel, plus Arcane Perfection stacks."""
    ranked = ctx.ranked("R")
    if ranked is None:
        return None
    ability, rank = ranked
    recasts = int(round(extract_named(ability, "Number of Recasts", rank)))
    per_shot = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    stacks = min(max(int(ctx.option("r_arcane_perfection")), 0), 6)
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


# Eye of Destruction lands "dealing magic damage to enemies hit and slowing
# them by 25% for 2.5 seconds"; Shocking Orb "deals magic damage to the
# first enemy hit and stuns them for 0.75 : 2.25 ... seconds".  Arcanopulse
# only beams (its 0% : 40% slow is Xerath's own charge penalty) and the
# Arcane Barrages only strike.  P restores mana on a basic attack and
# authors no ability part.
MODULE_CC = {"Q": "none", "W": "slow", "E": "stun", "R": "none"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Xerath",
    PACKET_SHA256,
    # E's orb has no sourced travel number to place — the packet is one hit.
    single_hit_slots=frozenset({"E"}),
    packet_part_timings={
        "Q": {"time_offset": _BLAST_DELAY_SECONDS},
        "W": {"time_offset": _BLAST_DELAY_SECONDS},
    },
    slot_parsers={
        "R": _rite_of_the_arcane,
    },
    cc_kinds=MODULE_CC,
)

OPTIONS = list(OPTIONS) + [
    int_option(
        "r_arcane_perfection",
        0,
        minimum=0,
        maximum=6,
        label="Arcane Perfection stacks (R barrage bonus)",
    ),
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
MODULE_COVERAGE = coverage(no_damage="P")
