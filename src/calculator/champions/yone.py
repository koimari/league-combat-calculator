"""Yone — Gathering Storm (Q3) stack system.

Stack mechanics modeled (E3):
- Q (Mortal Steel): Gathering Storm stacks up to 2 (6-second window).
  At 2 stacks the next Q cast consumes them to become the Q3 whirlwind.
  The whirlwind deals the SAME sourced damage as a normal Q — the
  empower is a 0.75-second knock-up (CC state, not damage).
  ``q_gathering_storm`` is the explicit pre-stack state.
- P (Way of the Hunter): the soul-mark / spirit-form store is a state
  row.
- E (Soul Unbound) (E9-3): the mark stores a portion of the
  post-mitigation damage dealt during Spirit Form — the "Damage Stored"
  row (25/27.5/30/32.5/35% of damage dealt) — and the recast deals that
  stored damage as TRUE damage.  The reviewed packet's static read of
  the percentage row emitted 0.0 (the row has no damage context), so
  the module now prices E as the stored percentage of the fight's
  ability-cast damage (its own Q/W/R results, evaluated in-slot after
  them) at the +5s auto-recast boundary; the basic-attack share of the
  stored damage needs the E window's auto ledger and is state.

W (Spirit Cleave) and R (Fate Sealed) keep the reviewed CP10.10 packet
pricing. All numeric values are read from the champion JSON data.
"""

from __future__ import annotations

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .module_helpers import no_damage
from .packet_module import build_packet_module
from .source_receipts import load_champion_sources
from .slotlib import damage_entry, extract_cooldown, extract_named, extract_value

# HARDCODED: verify on patch updates — the 5-second Spirit Form window
# and the +0.5s earliest recast are prose in the cached E description
# ("entering Spirit Form for 5 seconds" / "can be recast after 0.5
# seconds, and automatically does so after the duration"); the stored
# percentage is the cached "Damage Stored" row read live.
_E_SPIRIT_FORM_SECONDS = 5.0

PACKET_SHA256 = "806d48d7af49a8e38076a40e8ab180ee25751185eb1c7a31caf2b97e338aaaf1"

_BATCH_PARSE, _BATCH_SLOTS, _BATCH_ASSUMPTIONS, _BATCH_SOURCES, _BATCH_OPTIONS = (
    build_packet_module("Yone", PACKET_SHA256, single_hit_slots=frozenset({"W"}))
)
PACKET_SPEC = _BATCH_SLOTS.packet_spec


def _way_of_the_hunter(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: soul-mark state row (no enemy damage)."""
    ability = ctx.ability()
    if ability is None:
        return None
    return no_damage(
        ctx,
        name=ability.get("name", "Way of the Hunter"),
        reason=(
            "Soul Unbound's mark stores 25/27.5/30/32.5/35% of post-"
            "mitigation damage dealt during Spirit Form (E row); the "
            "mark itself deals no direct damage."
        ),
    )


def _mortal_steel(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: Mortal Steel, empowered into the Q3 whirlwind at 2 Gathering Storm stacks."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    stacks = min(max(int(ctx.options.get("q_gathering_storm", 0)), 0), 2)
    damage = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Mortal Steel"),
        rank,
        extract_cooldown(ability, rank),
        damage,
        "physical",
    )
    entry["parts"] = (DamagePart("physical", damage),)
    if stacks >= 2:
        entry["detail"] = (
            "Gathering Storm at 2 stacks: this cast is the Q3 whirlwind — "
            "same sourced damage as a normal thrust, adding a 0.75s "
            "knock-up (crowd-control state, not damage)."
        )
    else:
        entry["detail"] = (
            f"Gathering Storm {stacks}/2 stacks; the Q3 whirlwind at 2 "
            "stacks deals the same sourced damage (the empower is the "
            "knock-up, a crowd-control state)."
        )
    return entry


def _soul_unbound(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: the death-mark's stored damage dealt as true damage at the recast.

    Spirit Form stores the sourced percentage of the post-mitigation
    damage Yone deals to the target, and the (auto-)recast consumes the
    mark to deal that stored damage as true damage.  The static read of
    the percentage row has no damage context, so the module prices E
    against its OWN parsed results: the stored share of the fight's
    ability-cast damage (Q/W/R total_raw, evaluated in-slot after them
    — E is last in the slot map).  With 0 target resists post-mitigation
    equals pre-mitigation, so total_raw is the exact stored amount; the
    basic-attack share of the stored damage and the exact in-window
    timing are state (boundary note).
    """
    ability = ctx.ability("E")
    if ability is None:
        return None
    rank = ctx.rank_for("E")
    if rank < 1:
        return None
    ratio = extract_value(ability, "Damage Stored", rank, 0) / 100.0
    ability_damage = sum(
        float(entry.get("total_raw", 0.0) or 0.0)
        for slot in ("Q", "W", "R")
        if (entry := ctx.results.get(slot)) is not None
    )
    total = ratio * ability_damage
    entry = damage_entry(
        ability.get("name", "Soul Unbound"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "true",
    )
    entry["parts"] = (DamagePart("true", total, time_offset=_E_SPIRIT_FORM_SECONDS),)
    entry["detail"] = (
        f"{ratio * 100:g}% of the fight's ability-cast damage "
        f"({ability_damage:.2f}) stored and re-dealt as true damage at "
        "the auto-recast (+5s); the basic-attack share of the stored "
        "damage is state"
    )
    return entry


SLOTS = {
    "P": _way_of_the_hunter,
    "Q": _mortal_steel,
    "W": _BATCH_SLOTS["W"],
    "R": _BATCH_SLOTS["R"],
    # E is last so the stored-damage read sees Q/W/R in ctx.results.
    "E": _soul_unbound,
}
parse_abilities = build_parser(SLOTS, "Yone")

OPTIONS = [
    {
        "key": "q_gathering_storm",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 2,
        "label": "Gathering Storm stacks (2 = Q3 ready)",
    },
]

ASSUMPTIONS = [
    "Q3 (Gathering Storm at 2 stacks) deals the same sourced damage as a "
    "normal Q; its empower is the 0.75s knock-up, modeled as crowd-"
    "control state, so q_gathering_storm only changes the Q row's detail",
    "P (Way of the Hunter) soul mark is state",
    "E (Soul Unbound) prices the stored damage as the 'Damage Stored' "
    "percentage (25/27.5/30/32.5/35% of damage dealt by rank) of the "
    "fight's ability-cast damage (the module's own Q/W/R results, "
    "post-mitigation == pre-mitigation at 0 target resists), re-dealt as "
    "true damage at the +5s auto-recast; the basic-attack share of the "
    "stored damage needs the E window's auto ledger and is state — the "
    "old static read of the percentage row emitted 0.0 with no boundary "
    "note",
    "W (Spirit Cleave) and R (Fate Sealed) keep the reviewed CP10.10 packet pricing",
]

SOURCES = load_champion_sources("Yone")
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"P", "Q", "E"} else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
