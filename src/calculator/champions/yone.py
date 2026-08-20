"""Yone — Gathering Storm (Q3) stack system.

Stack mechanics modeled (E3):
- Q (Mortal Steel): Gathering Storm stacks up to 2 (6-second window).
  At 2 stacks the next Q cast consumes them to become the Q3 whirlwind.
  The whirlwind deals the SAME sourced damage as a normal Q — the
  empower is a 0.75-second knock-up (CC state, not damage).
  ``q_gathering_storm`` is the explicit pre-stack state.
- P (Way of the Hunter): the soul-mark / spirit-form store is a state
  row.
- E (Soul Unbound) (E9-3): Spirit Form stores a portion of the
  post-mitigation physical and magic damage dealt to champions, then the
  recast deals that stored amount as true damage. The fight engine applies
  this from the authored ability and auto-attack event ledger.

W (Spirit Cleave) and R (Fate Sealed) read the sourced physical and magic
rows. All numeric values are read from the champion JSON data.
"""

from __future__ import annotations

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx
from .module_helpers import no_damage
from .packet_module import build_packet_module
from .slotlib import damage_entry, extract_cooldown, extract_named, extract_value

# HARDCODED: verify on patch updates — the 5-second Spirit Form window
# and the +0.5s earliest recast are prose in the cached E description
# ("entering Spirit Form for 5 seconds" / "can be recast after 0.5
# seconds, and automatically does so after the duration"); the stored
# percentage is the cached "Damage Stored" row read live.
_E_SPIRIT_FORM_SECONDS = 5.0

# Fate Sealed's damage is the gust's, not the mark's: "After 0.3 seconds, a
# gust rushes along the same area that deals equal parts physical and magic
# damage to marked enemies" (cached R prose).
_R_GUST_DELAY_SECONDS = 0.3

PACKET_SHA256 = "806d48d7af49a8e38076a40e8ab180ee25751185eb1c7a31caf2b97e338aaaf1"


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
    stacks = min(max(int(ctx.option("q_gathering_storm")), 0), 2)
    damage = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Mortal Steel"),
        rank,
        extract_cooldown(ability, rank),
        damage,
        "physical",
    )
    # The knock-up is a property of the branch, not of the slot, so it is
    # authored here rather than in MODULE_CC: only the 2-stack cast is the
    # whirlwind that "additionally knock[s] up enemies hit in their path".
    entry["parts"] = (
        DamagePart("physical", damage, cc_kind="knockup" if stacks >= 2 else "none"),
    )
    # One thrust on the first enemy hit; the cached packet has no separate
    # travel or tick phase to place.
    entry["event_order_certified"] = "single_hit"
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


def _mixed_damage_entry(
    ctx: SlotCtx,
    *,
    attributes: tuple[tuple[str, str], ...],
    time_offset: float,
) -> dict[str, Any] | None:
    """Build one mixed packet from its sourced physical and magic rows.

    ``time_offset`` is when the cast's one damage instance lands, relative
    to the cast: both rows are "equal parts" of a single hit, so they share
    it.  Authoring it is what carries the cast into the event ledger — a
    two-part mixed entry cannot use the single-part ``single_hit``
    certification.
    """
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    parts = tuple(
        DamagePart(
            damage_type,
            extract_named(ability, attribute, rank, ctx.stats, ctx.target),
            time_offset=time_offset,
        )
        for damage_type, attribute in attributes
    )
    total = sum(part.amount for part in parts)
    entry = damage_entry(
        ability.get("name", f"Ability {ctx.slot}"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "mixed",
    )
    entry["parts"] = parts
    entry["total_raw"] = total
    entry["detail"] = "Sourced physical and magic damage instances"
    return entry


def _spirit_cleave(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: physical damage lands before the equal magic damage instance."""
    return _mixed_damage_entry(
        ctx,
        attributes=(
            ("physical", "Physical Damage"),
            ("magic", "Magic Damage"),
        ),
        time_offset=0.0,
    )


def _fate_sealed(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: magic damage lands before the equal physical damage instance."""
    return _mixed_damage_entry(
        ctx,
        attributes=(
            ("magic", "Magic Damage"),
            ("physical", "Physical Damage"),
        ),
        time_offset=_R_GUST_DELAY_SECONDS,
    )


def _soul_unbound(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: declare a post-mitigation damage store for the fight engine."""
    ability = ctx.ability("E")
    if ability is None:
        return None
    rank = ctx.rank_for("E")
    if rank < 1:
        return None
    ratio = extract_value(ability, "Damage Stored", rank, 0) / 100.0
    entry = damage_entry(
        ability.get("name", "Soul Unbound"),
        rank,
        extract_cooldown(ability, rank),
        0.0,
        "true",
    )
    entry["parts"] = ()
    entry["stored_damage"] = {
        "ratio": ratio,
        "duration": _E_SPIRIT_FORM_SECONDS,
        "source_slots": ("Q", "W", "R"),
        "include_auto_attacks": True,
    }
    entry["detail"] = (
        f"{ratio * 100:g}% of post-mitigation physical and magic champion "
        "damage during Spirit Form, re-dealt as true damage at the "
        "five-second auto-recast"
    )
    return entry


# Spirit Cleave only cleaves; Fate Sealed's gust "deals equal parts
# physical and magic damage to marked enemies within and pulls them towards
# the location Yone blinked to, then knocks them up for 0.75 seconds" — the
# pull is the control that lands with the damage (the 1-second stun is
# applied at the mark and "ends prematurely upon the pull").  Q is not here:
# its knock-up belongs to the Gathering Storm branch, so the kind is
# authored per part in ``_mortal_steel``.  P is the soul-mark state row.
#
# E stays UNREVIEWED, so this kit keeps the coarse control-armed scan.
# Soul Unbound's recast controls nothing, but its true-damage event is
# built by the fight engine from the ``stored_damage`` declaration, not
# from a part this module authors — there is nothing here for a kind to be
# stamped on, and a declaration that never reaches the ledger would claim a
# review the coverage scan cannot see.
MODULE_CC = {"W": "none", "R": "pull"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Yone",
    PACKET_SHA256,
    assumption_overrides=(
        "Q3 (Gathering Storm at 2 stacks) deals the same sourced damage as a normal Q; its empower "
        "is the 0.75s knock-up, modeled as crowd-control state, so q_gathering_storm only changes "
        "the Q row's detail",
        "P (Way of the Hunter) soul mark is state",
        "E (Soul Unbound) stores the sourced percentage of post-mitigation physical and magic "
        "champion damage from Q/W/R and basic attacks inside each five-second Spirit Form window. "
        "The fight engine emits the stored amount as a true-damage recast event.",
        "W (Spirit Cleave) uses the sourced physical row followed by the sourced magic row.",
        "R (Fate Sealed) uses the sourced magic row followed by the sourced physical row.",
    ),
    single_hit_slots=frozenset({"W"}),
    slot_parsers={
        "W": _spirit_cleave,
        "R": _fate_sealed,
        "P": _way_of_the_hunter,
        "Q": _mortal_steel,  # E declares metadata consumed after the fight event ledger is authored.
        "E": _soul_unbound,
    },
    slot_order=("P", "Q", "W", "R", "E"),
    cc_kinds=MODULE_CC,
)

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
